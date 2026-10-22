// 初始 PRD 决定卡片与资料页的端到端测试（工单 #138 的验收）：Playwright 打开 Chromium 页面，
// 连接真实运行的后端（tests/e2e/backend.py 的 --script onboarding，FakeAdapter 驱动）。
// 模型回答由 FakeAdapter 给出，不使用 mock；源目录是真实目录，接入与建档都真实跑完。
//
// 五条验收：
//   1. 经对话框接入后出现第一轮建档的 initial_prd 决定卡片；点「提出修改」而说明为空时给出提示，
//      不提交、不出现第二轮；
//   2. 填了修改意见提交以后出现第二轮建档，新决定卡片写明「第 2 轮」并给出上一轮修改意见；
//   3. 随后点「确认」，概览显示建档基线、快照来源与现有缺陷数；
//   4. 决定卡片显示初始 PRD、现有结构说明、基线核验汇总、快照来源与轮次；PRD.md 与
//      STRUCTURE.md 两个链接跳到资料页，资料页按轮列出各轮的初始 PRD 与确认记录，
//      并显示结构说明、基线核验与基线检查；
//   5. 控制台错误为零。
// 两种视口尺寸：1440×900 走完整往返，1920×1080 核对接入与资料页可用、没有横向滚动。

import { expect, test, type Locator, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

// 每条用例接入的项目名各不相同：projectId() 按名称取第一个，同名会让后一条用例取到前一条
// 已经确认过的项目（第 138 号工单「端到端通过的条件」第 4 条）。名称在本文件独有，
// 建档脚本的模型调用队列在文件之间共享，名称只用来从 projects.list 取项目标识
const GOAL = "核对待确认的初始 PRD";
const SOURCE_NAME = "echo";
// 提交的修改意见（写入第二轮的决定卡片、资料页与 run 的 additional_input）
const NOTE = "把入口的运行方式写进结构说明";
// 一个项目两轮共 12 次模型调用（两轮各 6 次）：脚本队列由本文件与第 137 号工单的用例共享
const MODEL_CALLS_PER_PROJECT = 12;

let backend: Backend;

// 启动后端到首行输出的用时由 git 子进程决定：并发负载下可能到 60 至 75 秒（#214）。
// 这个会合点单独放宽，各条测试自己的时限不变（同 onboarding.spec.ts 的处理）。
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend({ script: "onboarding" });
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
    // 服务端按设计用 409 拒绝命令（源目录无效、基准版本过期等），界面已经把原因显示给用户；
    // 浏览器对非 2xx 响应自己记一条控制台消息，那不是应用的错误
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

async function bodyText(page: Page): Promise<string> {
  return page.evaluate(() => document.body.innerText);
}

// 等待某个条件成立：界面按事件流自动重查询，这里轮询页面文本，不刷新页面
async function waitUntil(check: () => Promise<boolean>, page: Page, description: string, timeoutMs = 120_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) {
      return;
    }
    if (Date.now() > deadline) {
      const text = await bodyText(page).catch(() => "");
      throw new Error(`等待超时：${description}（当前页面文本：${text.slice(0, 400)}）`);
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}

async function section(page: Page, heading: string): Promise<Locator> {
  return page.locator("section.card").filter({ has: page.getByRole("heading", { name: heading, exact: true }) }).first();
}

// 接入对话框：侧栏的「接入已有项目」按钮展开的表单
async function onboardForm(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "接入已有项目" }).click();
  const form = page.locator("form.card").filter({ has: page.getByRole("heading", { name: "接入已有项目" }) });
  await expect(form).toBeVisible();
  return form;
}

async function fillOnboardForm(form: Locator, name: string, sourcePath: string): Promise<void> {
  await form.getByLabel("项目名称").fill(name);
  await form.getByLabel("长期目标").fill(GOAL);
  await form.getByLabel("源目录名称").fill(SOURCE_NAME);
  await form.getByLabel("源目录路径").fill(sourcePath);
}

// 项目列表直接读服务端：界面上的名称可能被前面的用例改过，标识不写死
async function projects(page: Page): Promise<{ name: string; project_id: string }[]> {
  const rows = await page.evaluate(
    async ({ address, query }) => {
      const response = await fetch(`${address}/api/queries/${query}?include_archived=true`);
      return (await response.json()) as { data?: { projects: { name: string; project_id: string }[] } };
    },
    { address: backend.address, query: "projects.list" },
  );
  return rows.data?.projects ?? [];
}

async function projectId(page: Page, project: string): Promise<string> {
  const found = (await projects(page)).find((item) => item.name === project);
  if (found === undefined) {
    throw new Error(`projects.list 里没有项目 ${project}（现有：${(await projects(page)).map((p) => p.name).join("、")}）`);
  }
  return found.project_id;
}

// 项目的页面路径（概览与资料）
function navHash(id: string, view: string): string {
  return `#/p/${id}/${view}`;
}

async function navigate(page: Page, id: string, view: string): Promise<void> {
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, navHash(id, view));
  await expect(page.locator(".tabbar .tab").first()).toBeVisible();
}

// initial_prd 的决定卡片：概览页上的同一张卡片在默认折叠的文字列表里（点不开），
// 顶栏「待你决定 · N」展开的下拉列出本项目的等待请求，在那里回答（同 home.spec.ts 的做法）
function overviewCard(page: Page): Locator {
  return page.locator(".decisions-dropdown article.decision-card")
    .filter({ hasText: "接入已有项目的初始需求文档等待确认" }).first();
}

// 首轮建档结束、决定请求在等待列表里（接口层的事件流已经把它送进页面）
async function waitFirstCard(page: Page, project: string): Promise<void> {
  await navigate(page, await projectId(page, project), "overview");
  const waiting = page.locator(".topbar .status-item").filter({ hasText: "待你决定 · " });
  await waitUntil(async () => (await waiting.count()) > 0, page, "顶栏显示本项目等待回答的决定", 240_000);
  await waiting.click();
  await expect(page.locator(".decisions-dropdown")).toBeVisible();
  await waitUntil(async () => (await overviewCard(page).count()) > 0, page, "首轮建档的初始 PRD 决定卡片", 240_000);
}

// 接入一次的建档结束：一个项目两轮共 12 次模型调用，本地一次在秒级，这里按分钟留出余量
async function onboardAndWaitFirstCard(page: Page, project: string): Promise<void> {
  const source = backend.sourceDir;
  if (source === null) {
    throw new Error("后端没有报出建档脚本的源目录");
  }
  const form = await onboardForm(page);
  await fillOnboardForm(form, project, source);
  await form.getByRole("button", { name: "接入项目" }).click();
  await waitUntil(async () => (await page.locator(".project-entry").allInnerTexts()).join().includes(project),
    page, "侧栏出现接入的项目");
  await waitFirstCard(page, project);
}

test.describe("初始 PRD 的修改往返（1440×900）", () => {
  test("1440×900：说明为空的修改不提交，填了修改意见出现第二轮，确认以后概览显示建档基线", async () => {
    const project = "修改往返主用例";
    test.setTimeout(300_000);
    const client = await openClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      await onboardAndWaitFirstCard(page, project);
      const card = overviewCard(page);

      // 卡片材料：轮次、初始 PRD 与结构说明的引用、基线核验汇总、快照来源（工单 #138 验收第 2、4 条）
      await expect(card).toContainText("第 1 轮");
      await expect(card).toContainText("PRD.md");
      await expect(card).toContainText("STRUCTURE.md");
      await expect(card).toContainText("没有 git 仓库，快照采集时的目录内容");
      await expect(card).toContainText("文件 3 项");

      // 顶栏的跨项目待决数量跟着加上（工单 #701）：初始 PRD 的决定写在项目流里，
      // 决定请求到达以后这个数字要变成 1，不刷新页面
      await expect(page.locator(".topbar .status-item").filter({ hasText: "待你决定：" }))
        .toHaveText("待你决定：1");

      // 说明为空时提交被卡片自己拦下：给出提示、不送出命令、不出现第二轮
      await card.getByRole("button", { name: "提出修改" }).click();
      await expect(card.getByRole("status")).toHaveText("「提出修改」需要在说明里写明修改意见");
      await expect(card).not.toContainText("已提交，等待控制主机确认");
      await card.getByLabel("说明（可选）").fill(NOTE);
      await card.getByRole("button", { name: "提出修改" }).click();
      await expect(card).toContainText("已提交，等待控制主机确认");

      // 第二轮建档：新的决定请求写明轮次并给出上一轮修改意见
      await expect(overviewCard(page)).toContainText("上一轮修改意见");
      await expect(overviewCard(page)).toContainText(NOTE);

      // 确认以后基线被采纳：概览写明建档基线、快照来源与现有缺陷数
      await overviewCard(page).getByRole("button", { name: "确认" }).click();
      await waitUntil(async () => (await bodyText(page)).includes("建档基线"), page, "概览显示建档基线", 240_000);
      await expect(await section(page, "项目摘要")).toContainText("快照来源");
      await expect(await section(page, "项目摘要")).toContainText("现有缺陷 0 项");
      if (backend.sourceDir !== null) {
        await expect(await section(page, "项目摘要")).toContainText(backend.sourceDir);
      }
      // 顶栏的跨项目待决数量跟着更新（工单 #701）：初始 PRD 的决定写在项目流里，
      // 回答以后这个数字要跟着少，不刷新页面
      await expect(page.locator(".topbar .status-item").filter({ hasText: "待你决定：" })).toHaveText("待你决定：无");
      expect(MODEL_CALLS_PER_PROJECT).toBe(12);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});

test.describe("初始 PRD 的资料（1440×900）", () => {
  test("1440×900：提出修改等到第二轮后，资料页按轮列出第 1、2 轮与确认记录，链接定位到第 2 轮", async () => {
    const project = "修改往返资料页";
    test.setTimeout(300_000);
    const client = await openClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      await onboardAndWaitFirstCard(page, project);
      const card1 = overviewCard(page);

      // 提出一次修改，等到第二轮的决定卡片（验收第 1 条）
      await card1.getByLabel("说明（可选）").fill(NOTE);
      await card1.getByRole("button", { name: "提出修改" }).click();
      await expect(card1).toContainText("已提交，等待控制主机确认");
      await expect(overviewCard(page)).toContainText("第 2 轮");
      await expect(overviewCard(page)).toContainText("上一轮修改意见");
      await expect(overviewCard(page)).toContainText(NOTE);
      const card2 = overviewCard(page);

      // 从第 2 轮卡片的 PRD.md 链接进入资料页，页面定位到第 2 轮
      await card2.getByRole("button", { name: "PRD.md" }).click();
      await waitUntil(async () => (await bodyText(page)).includes("建档各轮"), page, "资料页显示建档各轮");
      const materials = page.locator(".page.y10-mt");
      await expect(materials).toContainText("建档各轮");
      await expect(materials).toContainText("第 1 轮");
      await expect(materials).toContainText("第 2 轮");

      const round1 = page.locator("#onboarding-round-1");
      const round2 = page.locator("#onboarding-round-2");

      // 第 2 轮卡片链接进入时，页面定位到第 2 轮的初始 PRD 与结构说明（在可见区域内）
      await expect(round2.getByRole("heading", { name: "初始 PRD" })).toBeInViewport();
      await expect(round2.getByRole("heading", { name: "现有结构说明" })).toBeInViewport();

      // 第 1 轮：初始 PRD 原文、结构说明原文、基线核验逐条结论、基线检查（名称、命令、退出状态）与其他失败
      await expect(round1).toContainText("初始 PRD");
      await expect(round1).toContainText("# 现有结构说明");
      await expect(round1).toContainText("要求所在的位置");
      await expect(round1).toContainText("已核实");
      await expect(round1).toContainText("smoke");
      await expect(round1).toContainText("python");
      await expect(round1).toContainText("退出状态 0");
      await expect(round1).toContainText("其他失败");
      // 第 1 轮的确认记录是「提出修改」与修改意见原文
      await expect(round1).toContainText("回答：提出修改");
      await expect(round1).toContainText(NOTE);

      // 第 2 轮：写出上一轮的修改意见
      await expect(round2).toContainText("上一轮的修改意见：");
      await expect(round2).toContainText(NOTE);
      // 第 2 轮的 PRD 原文是第二轮 ProductSpec 的内容（要求与第 1 轮不同）
      const firstPrd = await round1.locator("pre.raw").first().innerText();
      const secondPrd = await round2.locator("pre.raw").first().innerText();
      expect(firstPrd).toContain("read the project layout at step ");
      expect(secondPrd).toContain("read the project layout at step ");
      expect(secondPrd).not.toEqual(firstPrd);
      // 结构说明原文、基线核验逐条结论、基线检查（名称、命令、退出状态）与其他失败
      await expect(round2).toContainText("# 现有结构说明");
      await expect(round2).toContainText("要求所在的位置");
      await expect(round2).toContainText("已核实");
      await expect(round2).toContainText("smoke");
      await expect(round2).toContainText("python");
      await expect(round2).toContainText("退出状态 0");
      await expect(round2).toContainText("其他失败");

      // 从第 2 轮卡片的 STRUCTURE.md 链接进入，同样定位到第 2 轮的初始 PRD 与结构说明
      await page.evaluate(() => {
        window.location.hash = "#/home";
      });
      await expect(page.locator(".page.home")).toBeVisible();
      const home = page.locator(".page.home article.decision-card")
        .filter({ hasText: "接入已有项目的初始需求文档等待确认" }).first();
      await waitUntil(async () => (await home.count()) > 0, page, "回到首页的决定卡片");
      await expect(home).toContainText("第 2 轮");
      await home.getByRole("button", { name: "STRUCTURE.md" }).click();
      await waitUntil(async () => (await bodyText(page)).includes("建档各轮"), page, "STRUCTURE.md 跳到资料页");
      await expect(round2.getByRole("heading", { name: "初始 PRD" })).toBeInViewport();
      await expect(round2.getByRole("heading", { name: "现有结构说明" })).toBeInViewport();

      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});

test.describe("初始 PRD（1920×1080）", () => {
  test("1920×1080：宽屏下卡片与资料页可用，没有横向滚动", async () => {
    const project = "修改往返宽屏";
    test.setTimeout(300_000);
    const client = await openClient({ width: 1920, height: 1080 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      await onboardAndWaitFirstCard(page, project);
      const card = overviewCard(page);
      await expect(card).toContainText("第 1 轮");
      await expect(card).toContainText("PRD.md");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);

      await card.getByRole("button", { name: "PRD.md" }).click();
      await waitUntil(async () => (await bodyText(page)).includes("建档各轮"), page, "资料页显示建档各轮");
      const overflowMaterials = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflowMaterials).toBeLessThanOrEqual(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});
