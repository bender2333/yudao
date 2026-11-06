// 离开期间的报告里的开环明细（工单 #401 的验收第 1、2 条；应用层与接口层设计说明第 4.3 节
// `home.away_report` 与 `acceptance.coverage`；验证的独立性设计说明第 7、7.1 节）。
//
// 一个放行带两条开环条件（一条判定点、一条开环）：报告的这一项要逐条列出它们，条数与
// `acceptance.coverage` 的数一致；「跳到逐条结论表」的链接在逐条结论表交付以后（#154）出现；
// 页面文字里没有英文内部标识，也没有事项一级的「开环完成」。
//
// 只看页面：断言读的是页面上的文字与按钮，不读画布、不用画面的测试钩子（测试分层设计说明第 7 节）。
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py 的 --script coverage），页面文件由它提供。

import { expect, test } from "@playwright/test";
import { collectConsoleErrors, startBackend, startClient, type Backend } from "./fixtures";

let backend: Backend;

// 后端启动要等预置跑完一轮三部门（后端启动本身约 60 到 75 秒），这个会合点单独放宽
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend({ script: "coverage" });
});

test.afterAll(async () => {
  await backend?.stop();
});

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

// 从页面所在的来源读一条查询（与首页其余用例同一做法）：用来核对页面上那几行字与查询结果一致。
// 这不是读画布：读的是接口给的数，页面上写的就是它
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

test("离开期间的报告逐条列出带开环条件的放行：条数与检验覆盖一致，可以从那里跳到逐条结论表", async () => {
  test.setTimeout(180_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = collectConsoleErrors(client.page);
  const { page } = client;
  try {
    await expect(page.locator(".brand .y10-brand-name")).toContainText("Yudao");
    await page.evaluate(() => {
      window.location.hash = "#/home";
    });
    const report = page.locator("section.card").filter({
      has: page.getByRole("heading", { name: "离开期间的报告", exact: true }),
    });
    await expect(report).toBeVisible();

    // 报告里有「带开环条件的放行」一项：值是放行的次数（一次）
    const item = report.locator(".report-item").filter({ hasText: "带开环条件的放行" });
    await expect(item).toBeVisible();
    await expect(item.locator(".report-value")).toContainText("1");

    // 逐条列出：一行一个放行，写项目名、事项标题与开环条件
    const rows = item.locator(".open-release-row");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("开环报告 / 实现带开环条件的放行");

    // 条数与明细取自 acceptance.coverage：读同一个 run 的检验覆盖，与页面上写的那一行对得上
    const projects = await fetchQuery<{ projects: { project_id: string; name: string }[] }>(page, "projects.list");
    const projectId = projects.projects.find((row) => row.name === "开环报告")?.project_id ?? "";
    expect(projectId).not.toBe("");
    const overview = await fetchQuery<{
      work_items: { work_item_id: string; run_id: string; title: string }[];
    }>(page, "project.overview", { project_id: projectId });
    const card = overview.work_items.find((row) => row.title === "实现带开环条件的放行");
    expect(card, "预置的事项没有出现在项目里").toBeDefined();
    const coverage = await fetchQuery<{
      numbers: { open: number };
      open_criteria: string[];
    }>(page, "acceptance.coverage", { run_id: card!.run_id });
    const expected = `开环条件 ${coverage.numbers.open} 条：${coverage.open_criteria.join("、")}`;
    await expect(rows.first()).toContainText(expected);
    // 这份放行确实带两条开环条件（预置的脚本决定的），页面上写的不是空话
    expect(coverage.numbers.open).toBe(2);
    expect(coverage.open_criteria).toEqual(["AC2", "AC3"]);

    // 逐条结论表已经交付（#154）：这一行给出跳到这个事项资料页那张表的链接
    await expect(report.getByRole("button", { name: "跳到逐条结论表", exact: true })).toHaveCount(1);

    // 页面文字：没有英文内部标识，也没有事项一级的「开环完成」
    const text = await rows.first().innerText();
    for (const word of ["judgement", "open_criteria", "coverage", "unverified", "wi_", "run_", "AC1"]) {
      expect(text, `明细里出现了 ${word}：${text}`).not.toContain(word);
    }
    const body = await page.evaluate(() => document.body.innerText);
    expect(body).not.toContain("开环完成");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
