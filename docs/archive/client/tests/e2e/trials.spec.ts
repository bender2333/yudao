// 部门工作间的「试用记录」页签（工单 #153；浏览器与 computer use
// docs/design/browser-and-computer-use.md「查询」、「页面与画面」）。预置见 tests/e2e/backend.py 的 --script trials：
// 一件进行中的事项，一个已经结束的质检试用会话（试用副本等于交付快照），一个通过的试用用例
// （引用两条验收条件、计划两步、三步里有两张截图），收到结果的两次请求都只看文字。
//
// 只看页面：断言读页面文字与图片，不读画布。页签上的会话、用例与步骤与 run.trials 的查询结果逐字相同；
// 截图经 evidence.screenshot 真的读到了（naturalWidth 大于 0）；点开一张看原尺寸与页面结构摘录。
// 页面文字不出现英文内部标识与开发者措辞。
//
// 后端是真实服务，页面文件由它提供（npm run build:pages 的产物）；试用事件按生产路径的形状预置，
// 与资料页逐条结论表的预置同一做法（这条路径不启动浏览器执行一次真实试用，见交付说明）。

import { expect, test } from "@playwright/test";
import { collectConsoleErrors, startBackend, startClient, type Backend } from "./fixtures";

let backend: Backend;

// 后端启动要等预置写好（这个模式不跑模型），会合点给足
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend({ script: "trials" });
});

test.afterAll(async () => {
  await backend?.stop();
});

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

// 从页面所在的来源读一条查询（与首页、资料页的用例同一做法）：用来核对页面上写的与查询一致
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

interface TrialStepResult {
  tool: string;
  status: string;
  request_had_images: boolean | null;
  screenshots: Record<string, unknown>[];
}

interface TrialCaseResult {
  title: string;
  criteria: { criterion: string; text: string | null }[];
  result: string | null;
  steps: TrialStepResult[];
}

interface TrialsResult {
  departments: {
    department: string;
    sessions: { launch_name: string; kind: string; status: string; matches_delivery_snapshot: boolean | null }[];
    cases: TrialCaseResult[];
  }[];
}

test("部门工作间的试用记录页签显示会话、用例、步骤与截图，文本模型写明只读取文字", async () => {
  test.setTimeout(180_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = collectConsoleErrors(client.page);
  const { page } = client;
  try {
    await expect(page.locator(".brand .y10-brand-name")).toContainText("Yudao");

    // 预置的项目与事项：页面按事项打开部门工作间，事项范围写在 ?w= 里
    const projects = await fetchQuery<{ projects: { project_id: string; name: string }[] }>(page, "projects.list");
    const projectId = projects.projects.find((row) => row.name === "试用记录")?.project_id ?? "";
    expect(projectId).not.toBe("");
    const overview = await fetchQuery<{ work_items: { work_item_id: string; title: string; run_id: string }[] }>(
      page, "project.overview", { project_id: projectId });
    const card = overview.work_items.find((row) => row.title === "核验待办清单");
    expect(card, "预置的事项没有出现在项目里").toBeDefined();

    // 页签要显示的与查询给出的一致：一个会话、一个用例、三步、两张截图、两次只看文字的请求
    const trials = await fetchQuery<TrialsResult>(page, "run.trials", { run_id: card!.run_id });
    const quality = trials.departments.find((group) => group.department === "quality");
    expect(quality, "预置的质检试用记录没有读出来").toBeDefined();
    expect(quality!.sessions).toHaveLength(1);
    expect(quality!.cases).toHaveLength(1);
    const trialCase = quality!.cases[0];
    expect(trialCase.steps).toHaveLength(3);
    expect(trialCase.steps.flatMap((step) => step.screenshots)).toHaveLength(2);
    // 两张有截图的步骤之后的那次请求都只看文字
    expect(trialCase.steps.filter(
      (step) => step.screenshots.length > 0 && step.request_had_images === false).length).toBe(2);

    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${projectId}/dept/quality?w=${card!.work_item_id}`);

    // 检查区多了「试用记录」页签，四个页签都在
    const inspect = page.locator("section.card").filter({ has: page.getByRole("heading", { name: "检查区" }) });
    await expect(inspect).toBeVisible();
    await expect(inspect.getByRole("tab")).toHaveCount(4);
    const tab = inspect.getByRole("tab", { name: "试用记录" });
    await expect(tab).toBeVisible();
    await tab.click();

    // 试用会话：种类、启动方式、试用副本与交付快照的比较、结束方式
    await expect(inspect).toContainText("试用会话（1 个）");
    const sessionRow = inspect.locator("table.y10-table tbody tr").first();
    await expect(sessionRow).toContainText("网页");
    await expect(sessionRow).toContainText("待办清单网页");
    await expect(sessionRow).toContainText("交付快照的副本，与交付快照相同");
    await expect(sessionRow).toContainText("已结束（已停止）");

    // 试用用例：标题、验收条件与原文、计划、预期、结论与观察到的结果
    await expect(inspect).toContainText("试用用例（1 个）");
    await expect(inspect).toContainText("添加一条待办");
    await expect(inspect).toContainText("AC1 列表显示一条待办");
    await expect(inspect).toContainText("AC2 点击添加以后列表里有这条待办");
    await expect(inspect).toContainText("计划的操作");
    await expect(inspect).toContainText("在输入框里输入“买牛奶”并点添加");
    await expect(inspect).toContainText("预期结果：列表里出现这条待办");
    await expect(inspect).toContainText("观察到的结果：列表里出现了「买牛奶」");
    await expect(inspect).toContainText("通过");

    // 三步的操作写成中文，作为证据的一步有标记
    await expect(inspect).toContainText("步骤（3 步）");
    await expect(inspect).toContainText("打开页面");
    await expect(inspect).toContainText("输入文字「买牛奶」");
    await expect(inspect).toContainText("核对页面上出现「买牛奶」");
    await expect(inspect).toContainText("已完成");
    await expect(inspect).toContainText("证据");

    // 文本模型：页签上写明「模型只读取文字」，每张截图旁边也写这一句
    await expect(inspect).toContainText("模型只读取文字：这次试用里模型收到的内容只有文字");
    await expect(inspect.getByText("模型只读取文字", { exact: true })).toHaveCount(2);

    // 两张截图真的读到了内容
    const shots = inspect.locator("img");
    await expect(shots).toHaveCount(2);
    for (const shot of await shots.all()) {
      expect(await shot.evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
    }

    // 点开第一张：原尺寸的图与同一步的页面结构摘录
    await inspect.locator("button.y10-mt-shot").first().click();
    const modal = page.locator(".y10-modal");
    await expect(modal).toBeVisible();
    await expect(modal).toContainText("这一步的页面结构");
    await expect(modal).toContainText("按钮「添加」 输入框「待办」 列表「买牛奶」");
    await expect(modal.locator("img")).toHaveCount(1);
    await modal.getByRole("button", { name: "关闭" }).click();
    await expect(modal).toHaveCount(0);

    // 页面文字：不出现英文内部标识与开发者措辞
    const body = await page.evaluate(() => document.body.innerText);
    for (const word of ["browser_", "screen_", "delivery_snapshot", "workspace_seal", "sha256",
      "trial_case", "request_had_images", "case_trials", "ses_trials", "passed", "completed",
      "concluded", "stopped"]) {
      expect(body, `页面文字里出现了 ${word}`).not.toContain(word);
    }

    // 1440×900 与 1920×1080 下都不出现横向滚动条
    for (const size of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
      await page.setViewportSize(size);
      await expect(inspect).toBeVisible();
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
