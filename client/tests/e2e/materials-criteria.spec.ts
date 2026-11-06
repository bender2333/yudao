// 资料页的逐条结论表与启动方式（工单 #154；浏览器与 computer use docs/design/browser-and-computer-use.md「页面与画面」、「QAReview 的逐条结论与放行」、「无法核验」；
// 验证的独立性 docs/design/independent-verification.md「检验覆盖与开环」、「口径」）。预置见 tests/e2e/backend.py 的 --script materials：
// 一件进行中的事项，交付说明写了启动方式；放行记录有四条验收条件（试用用例通过、命令检查通过、
// 带参照材料的判定点无法核验、开环无法核验），试用用例的一步有一张截图。
//
// 只看页面：断言读页面文字与图片，不读画布。表头的检验覆盖比例、模型阅读与开环条数与
// acceptance.coverage 的数逐字相同（放行记录里一次算好，页面不重算）。
//
// 后端是 FakeAdapter 驱动的真实服务，页面文件由它提供（npm run build:pages 的产物）。

import { expect, test } from "@playwright/test";
import { collectConsoleErrors, startBackend, startClient, type Backend } from "./fixtures";

let backend: Backend;

// 后端启动要等预置写好（这个模式不跑模型），会合点给足
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend({ script: "materials" });
});

test.afterAll(async () => {
  await backend?.stop();
});

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

// 从页面所在的来源读一条查询（与首页、离开期间报告的用例同一做法）：用来核对页面上写的数与查询一致
async function fetchQuery<T>(
  page: import("@playwright/test").Page,
  name: string,
  params: Record<string, string | number> = {},
): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.set(key, String(value));
  }
  const suffix = search.toString();
  const envelope = await page.evaluate(
    async ({ address, query, qs }) => {
      const response = await fetch(`${address}/api/queries/${query}${qs ? `?${qs}` : ""}`);
      return (await response.json()) as QueryEnvelope<unknown>;
    },
    { address: backend.address, query: name, qs: suffix },
  );
  if (envelope.data === undefined) {
    throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data as T;
}

interface CoverageNumbers {
  criteria_total: number;
  executable: number;
  covered: number;
  coverage_ratio: number;
  model_reading: number;
  open: number;
}

interface CoverageResult {
  numbers: CoverageNumbers;
  criteria: { criterion: string; method: string; result: string; executable: boolean; open: boolean }[];
  open_criteria: string[];
}

test("资料页列出质检的逐条结论与表头数字，交付一项显示启动方式", async () => {
  test.setTimeout(180_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = collectConsoleErrors(client.page);
  const { page } = client;
  try {
    await expect(page.locator(".brand .y10-brand-name")).toContainText("Yudao");

    // 预置的项目与事项：页面按事项打开资料页，事项范围写在 ?w= 里
    const projects = await fetchQuery<{ projects: { project_id: string; name: string }[] }>(page, "projects.list");
    const projectId = projects.projects.find((row) => row.name === "逐条结论")?.project_id ?? "";
    expect(projectId).not.toBe("");
    const overview = await fetchQuery<{ work_items: { work_item_id: string; run_id: string; title: string }[] }>(
      page, "project.overview", { project_id: projectId });
    const card = overview.work_items.find((row) => row.title === "实现待办清单");
    expect(card, "预置的事项没有出现在项目里").toBeDefined();
    const coverage = await fetchQuery<CoverageResult>(page, "acceptance.coverage", { run_id: card!.run_id });

    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${projectId}/materials?w=${card!.work_item_id}`);

    // 质检一项：表头就是放行记录里的那三个数
    const qa = page.locator("section.card").filter({
      has: page.getByRole("heading", { name: "质检", exact: true }),
    });
    await expect(qa).toBeVisible();
    const expectedSummary = `检验覆盖 ${Math.round(coverage.numbers.coverage_ratio * 100)}`
      + `%（${coverage.numbers.covered}/${coverage.numbers.criteria_total}）`
      + `· 开环条件 ${coverage.numbers.open} 条（其中模型阅读 ${coverage.numbers.model_reading} 条）`;
    await expect(qa.locator(".y10-mt-coverage")).toHaveText(expectedSummary);

    // 每条验收条件一行，检验方式与结果写中文
    const rows = qa.locator("table.y10-table tbody tr");
    await expect(rows).toHaveCount(coverage.criteria.length);
    await expect(rows.nth(0)).toContainText("AC1");
    await expect(rows.nth(0)).toContainText("试用用例");
    await expect(rows.nth(0)).toContainText("通过");
    await expect(rows.nth(1)).toContainText("命令检查");
    await expect(rows.nth(2)).toContainText("带参照材料的判定点");
    await expect(rows.nth(2)).toContainText("未核验");
    await expect(rows.nth(3)).toContainText("开环");

    // 开环标记按放行记录：判定点与开环两条带标记，通过的两条不带
    await expect(rows.nth(2).locator(".y10-tag")).toContainText("开环");
    await expect(rows.nth(3).locator(".y10-tag")).toContainText("开环");
    await expect(rows.nth(0).locator(".y10-tag")).toHaveCount(0);
    expect(coverage.open_criteria).toEqual(["AC3", "AC4"]);

    // 无法核验的条目与原因写在表下
    const unverified = qa.locator(".y10-mt-unverified");
    await expect(unverified).toContainText("AC3");
    await expect(unverified).toContainText("参照材料里没有写清楚字号");
    await expect(unverified).toContainText("AC4");
    await expect(unverified).toContainText("需要真实打印机，这台机器上没有");

    // 试用用例的截图缩略图：一张，内容真的读到了（naturalWidth 大于 0）
    const shots = qa.locator("img.y10-mt-shot");
    await expect(shots).toHaveCount(1);
    expect(await shots.first().evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);

    // 交付一项的启动方式：名称、种类、两个系统的命令、就绪地址
    const delivery = page.locator("section.card").filter({
      has: page.getByRole("heading", { name: "交付", exact: true }),
    });
    await expect(delivery).toContainText("启动方式");
    await expect(delivery).toContainText("待办清单网页");
    await expect(delivery).toContainText("网页");
    await expect(delivery).toContainText("python -m http.server {port}");
    await expect(delivery).toContainText("python3 -m http.server {port}");
    await expect(delivery).toContainText("http://127.0.0.1:{port}/");
    await expect(delivery).toContainText("就绪时限 30 秒");

    // 页面文字：没有英文内部标识（命令原文与文件名是交付自己的内容，不算内部标识）
    const body = await page.evaluate(() => document.body.innerText);
    for (const word of ["passed", "failed", "unverified", "trial_cases", "criteria", "rework_engineering",
      "cannot_verify", "qa_submitted", "judgement", "active", "superseded", "text"]) {
      expect(body, `页面文字里出现了 ${word}`).not.toContain(word);
    }
    // 1440×900 与 1920×1080 下都不出现横向滚动条
    for (const size of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
      await page.setViewportSize(size);
      await expect(qa).toBeVisible();
      const overflow = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }));
      expect(overflow.scroll, `${size.width}×${size.height} 出现了横向滚动条`).toBeLessThanOrEqual(overflow.client + 1);
    }
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
