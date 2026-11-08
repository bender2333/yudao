// 部门工作间的步骤时间线（工单 #1235 的验收）：Playwright 打开 Chromium，连接真实运行的后端
// （tests/e2e/backend.py 的 --script steps，FakeAdapter 驱动；事件日志、工件与工作区都是真实实现）。
//
// 种子：产品第一次激活三步——第一步有推理、一句模型文字、一个成功动作（列出文件）与一个失败动作
// （读一个不存在的文件），第二步只有动作，第三步提交规格；之后工程问产品一次。工程的询问在流式片段里
// 等数据目录里的 advance-step 文件，用例在断言完第一次激活以后创建它，产品因此多出一次激活（第 2 次工作）。
//
// 验收：默认选中最近一次激活、步骤按序；思考默认折叠，点开后出现整句话；失败动作的回执块显示失败原因，
// 且这个原因不出现在「模型说的话」里；新激活到达以后回到第一次激活，已展开的思考保持展开；
// 页签里没有 table；1280 宽的视口下页签内容没有横向滚动条；控制台错误为零。

import { expect, test, type Locator, type Page } from "@playwright/test";
import { rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const GOAL = "做一个小工具";
const ITEM_TEXT = "做一个小工具";
// 种子第一步里读的那个不存在的文件：失败动作的回执里出现它的名字
const MISSING = "missing-1235.txt";
// 折叠时只显示推理的前两行；第三行只有展开以后才出现
const FOLDED_LINE = "第三个文件先不读，等需求确认。";
// 模型说的话：失败原因不能出现在这一块里
const SAYING = "我先列出工作区里的文件，再读一个文件。";

let backend: Backend;

test.beforeAll(async () => {
  // 启动后端到首行输出的用时由 git 子进程决定，并发负载下可能较慢（同 onboarding.spec.ts 的处理）
  test.setTimeout(300_000);
  backend = await startBackend({ script: "steps" });
});

test.afterAll(async () => {
  await backend?.stop();
});

async function openClient(size: { width: number; height: number }): Promise<ClientApp> {
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  return client;
}

function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

async function waitUntil(check: () => Promise<boolean>, page: Page, description: string, timeoutMs = 120_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) {
      return;
    }
    if (Date.now() > deadline) {
      const text = await page.evaluate(() => document.body.innerText).catch(() => "");
      throw new Error(`等待超时：${description}（当前页面文本：${text.slice(0, 400)}）`);
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}

async function newProjectForm(page: Page): Promise<Locator> {
  await page.locator(".sidebar .nav-item", { hasText: "从想法新建" }).click();
  const form = page.locator("form.card").filter({ has: page.getByRole("heading", { name: "从想法新建项目" }) });
  await expect(form).toBeVisible();
  return form;
}

type ProjectRow = { name: string; project_id: string };

async function projects(page: Page): Promise<ProjectRow[]> {
  return page.evaluate(
    async (address) => {
      const response = await fetch(`${address}/api/queries/projects.list?include_archived=true`);
      return (await response.json()) as { data?: { projects: ProjectRow[] } };
    },
    backend.address,
  ).then((envelope) => envelope.data?.projects ?? []);
}

async function projectId(page: Page, name: string): Promise<string> {
  const found = (await projects(page)).find((project) => project.name === name);
  if (found === undefined) {
    throw new Error(`projects.list 里没有项目 ${name}（现有：${(await projects(page)).map((p) => p.name).join("、")}）`);
  }
  return found.project_id;
}

async function navigate(page: Page, id: string, view: string): Promise<void> {
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, `#/p/${id}/${view}`);
  await expect(page.locator(".tabbar .tab").first()).toBeVisible();
}

// 布局验收：文档与页面内每个可见容器都不出现横向溢出（滚动容器允许，溢出到窗口外不允许）
async function overflowReport(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const offenders: string[] = [];
    const root = document.documentElement;
    if (root.scrollWidth - root.clientWidth > 1) {
      offenders.push(`html +${root.scrollWidth - root.clientWidth}`);
    }
    for (const node of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      if (["INPUT", "SELECT", "TEXTAREA"].includes(node.tagName)) {
        continue;
      }
      const over = node.scrollWidth - node.clientWidth;
      if (over <= 1 || node.offsetParent === null) {
        continue;
      }
      const style = getComputedStyle(node);
      if (style.overflowX === "auto" || style.overflowX === "scroll") {
        continue;
      }
      const classes = typeof node.className === "string" && node.className.trim() !== "" ? `.${node.className.trim().split(/\s+/).join(".")}` : "";
      offenders.push(`${node.tagName.toLowerCase()}${classes} +${over} 「${(node.textContent ?? "").trim().slice(0, 40)}」`);
    }
    return offenders;
  });
}

// 新建项目并开始一个事项，打开产品部门的部门工作间（检查区的第一个页签就是动作与回执）
async function openProductWorkspace(page: Page): Promise<string> {
  const name = `步骤项目 ${Date.now()}`;
  const form = await newProjectForm(page);
  await form.getByLabel("项目名称").fill(name);
  await form.getByLabel("长期目标").fill(GOAL);
  await form.getByRole("button", { name: "新建项目" }).click();
  const id = await projectId(page, name);
  await waitUntil(async () => (await page.evaluate(() => window.location.hash)) === `#/p/${id}/overview`,
    page, "新建成功以后转到新项目的概览");
  await page.getByLabel("新的想法或材料").fill(ITEM_TEXT);
  await page.getByRole("button", { name: "作为新事项开始" }).click();
  await navigate(page, id, "dept/product");
  return id;
}

// 检查区（动作与回执那个页签所在的那张卡）
function inspectCard(page: Page): Locator {
  return page.locator("section.card").filter({ has: page.getByRole("tab", { name: "动作与回执" }) });
}

// 第 N 步的块（1 起）
function stepBlock(page: Page, index: number): Locator {
  return inspectCard(page).locator(".y10-ws-step").nth(index - 1);
}

test("步骤时间线：激活选择、步骤按序、思考折叠与展开、回执、新激活以后保持展开、没有表格（1440×900）", async () => {
  test.setTimeout(300_000);
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await openProductWorkspace(page);
    const card = inspectCard(page);
    const strip = card.locator(".y10-ws-activations button");

    // 第一次激活的三步（第一步有推理、话与两个动作；第二步只有动作；第三步提交规格式，只有标题行）
    await waitUntil(async () => (await strip.count()) >= 1 && (await card.locator(".y10-ws-step").count()) >= 2,
      page, "部门工作间出现产品这次工作的步骤", 180_000);
    // 默认选中最近一次激活（这时只有第 1 次工作）
    await expect(strip.first()).toContainText("第 1 次工作");
    await expect(strip.first()).toHaveAttribute("aria-selected", "true");

    // 步骤按 step_id 升序：第 1 步在上
    await expect(stepBlock(page, 1).locator(".y10-ws-step-head")).toContainText("第 1 步");
    await expect(stepBlock(page, 2).locator(".y10-ws-step-head")).toContainText("第 2 步");

    // 第一步：思考块默认折叠，只有预览的前两行与字数；第三行还没有出现
    const thinking = stepBlock(page, 1).locator(".y10-ws-step-block.is-thinking");
    await expect(thinking).toContainText("模型的思考");
    await expect(thinking).toContainText("先看工作区里有什么。");
    await expect(thinking).toContainText("再挑一个文件读一下。");
    await expect(thinking).toContainText(/共 \d+ 字/);
    await expect(thinking).not.toContainText(FOLDED_LINE);

    // 模型说的话：默认展开，写的是那句交接
    const saying = stepBlock(page, 1).locator(".y10-ws-step-block.is-saying");
    await expect(saying).toContainText("模型说的话");
    await expect(saying).toContainText(SAYING);

    // 动作：成功的列出文件与失败的读取各一行；失败的回执里是失败原因，且它不在「模型说的话」里
    const acts = stepBlock(page, 1).locator(".y10-ws-act");
    await expect(acts.filter({ hasText: "list_files" })).toContainText("成功");
    const failed = acts.filter({ hasText: "read_file" });
    await expect(failed.locator(".y10-ws-receipt")).toContainText(MISSING);
    await expect(saying).not.toContainText(MISSING);

    // 第二步只有动作：没有思考块与话块
    await expect(stepBlock(page, 2).locator(".y10-ws-step-block.is-thinking")).toHaveCount(0);
    await expect(stepBlock(page, 2).locator(".y10-ws-step-block.is-saying")).toHaveCount(0);
    await expect(stepBlock(page, 2).locator(".y10-ws-act")).not.toHaveCount(0);

    // 点开思考：读取 event.detail 的全文，第三行出现
    await thinking.getByRole("button", { name: "展开全文" }).click();
    await expect(thinking).toContainText(FOLDED_LINE);
    await expect(thinking.getByRole("button", { name: "收起" })).toBeVisible();

    // 打开「追加一步」的开关：工程的询问这时才发出，产品因此多出一次激活（第 2 次工作）
    writeFileSync(join(backend.dataDir, "advance-step"), "");
    await waitUntil(async () => (await strip.count()) >= 2, page, "产品出现第二次激活", 180_000);
    await expect(strip.nth(1)).toContainText("第 2 次工作");

    // 回到第一次激活：已展开的思考保持展开（展开状态以事件编号为键，数据刷新以后还在）
    await strip.first().click();
    await expect(stepBlock(page, 1).locator(".y10-ws-step-block.is-thinking")).toContainText(FOLDED_LINE);

    // 页签里没有表格（表格换成了时间线），1440×900 下没有横向滚动
    await expect(card.locator("table")).toHaveCount(0);
    expect(await overflowReport(page)).toEqual([]);
    expect(errors).toEqual([]);
    // 页面证据（验收要求交付说明附一张）：给出手稿路径时截一张整页图，
    // 内容是第一次激活里的思考、话、成功的动作与失败的动作
    if (process.env.STEP_TIMELINE_SHOT) {
      await card.screenshot({ path: process.env.STEP_TIMELINE_SHOT });
    }
  } finally {
    // 第二条用例（1280 宽）各自建一个项目，工程同样要在这条用例读完第一次激活以后才发问：
    // 把开关收回去，下一条用例的种子重新等一次
    rmSync(join(backend.dataDir, "advance-step"), { force: true });
    await client.close();
  }
});

test("步骤时间线：1280 宽的视口下页签内容没有横向滚动条", async () => {
  test.setTimeout(300_000);
  const client = await openClient({ width: 1280, height: 800 });
  const page = client.page;
  try {
    await openProductWorkspace(page);
    const card = inspectCard(page);
    await waitUntil(async () => (await card.locator(".y10-ws-step").count()) >= 2, page,
      "部门工作间出现产品这次工作的步骤", 180_000);
    expect(await overflowReport(page)).toEqual([]);
  } finally {
    await client.close();
  }
});
