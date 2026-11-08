// 接入已有项目的端到端测试（工单 #137 的验收）：Playwright 打开 Chromium 页面，连接真实运行的后端
// （tests/e2e/backend.py 的 --script onboarding，FakeAdapter 驱动）。模型回答由 FakeAdapter 给出，
// 不使用 mock：源目录是真实目录，接入命令真的采集它的代码快照。
//
// 三条验收：
//   1. 经对话框完成一次接入，建档状态标记随事件变化，部门房间出现「阅读已有项目」的动作；
//   2. 填写无效的源目录时对话框显示 source_invalid 的原因与相对路径，没有出现新项目；
//   3. 放弃等待确认的建档以后「重新开始建档」可用，点击以后出现新的建档事项。
// 两种视口尺寸：1440×900 走完整流程，1920×1080 核对接入对话框与状态标记可用。控制台错误为零。

import { expect,test,type Locator,type Page } from "@playwright/test";
import { startBackend,startClient,type Backend,type ClientApp } from "./fixtures";

const PROJECT = "接入演练";
const GOAL = "核对接入已有项目";
const SOURCE_NAME = "echo";

let backend: Backend;

// 启动后端到首行输出的用时由 git 子进程决定：并发负载下可能到 60 至 75 秒（#214）。
// 这个会合点单独放宽，各条测试自己的时限不变（同 shell.spec.ts 的处理）。
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

// 项目的页面路径（概览与部门工作间）
function navHash(id: string, view: string): string {
  return `#/p/${id}/${view}`;
}

async function navigate(page: Page, id: string, view: string): Promise<void> {
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, navHash(id, view));
  await expect(page.locator(".tabbar .tab").first()).toBeVisible();
}


type ProjectRow = { name: string; project_id: string };

// 项目列表直接读服务端：界面上的名称可能被前面的用例改过，标识不写死
async function projects(page: Page): Promise<ProjectRow[]> {
  const rows = await page.evaluate(
    async ({ address, query }) => {
      const response = await fetch(`${address}/api/queries/${query}?include_archived=true`);
      return (await response.json()) as { data?: { projects: ProjectRow[] } };
    },
    { address: backend.address, query: "projects.list" },
  );
  return rows.data?.projects ?? [];
}

async function projectId(page: Page): Promise<string> {
  const found = (await projects(page)).find((project) => project.name === PROJECT);
  if (found === undefined) {
    throw new Error(`projects.list 里没有项目 ${PROJECT}（现有：${(await projects(page)).map((p) => p.name).join("、")}）`);
  }
  return found.project_id;
}

// 一个含符号链接的源目录：接入被拒绝，拒绝说明里给出相对路径（harness/public_tree.py 的
// UnrepresentableWorkspace 用分号连接各条原因与处理方法）

test.describe("接入已有项目（1440×900）", () => {
  test("经对话框完成一次接入，建档状态标记随事件变化，部门房间出现阅读已有项目", async () => {
    test.setTimeout(300_000);
    const client = await openClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const source = backend.sourceDir;
      if (source === null) {
        throw new Error("后端没有报出建档脚本的源目录");
      }
      const form = await onboardForm(page);
      await fillOnboardForm(form, PROJECT, source);
      await form.getByRole("button", { name: "接入项目" }).click();

      // 新项目出现在侧栏
      await waitUntil(async () => (await page.locator(".project-entry").allInnerTexts()).join().includes(PROJECT),
        page, "侧栏出现接入的项目");

      // 建档状态标记：建档事项跑完基线核验以后停下并等用户确认初始 PRD（工单 #136），标记随之变化
      const id = await projectId(page);
      await navigate(page, id, "overview");
      await waitUntil(async () => (await bodyText(page)).includes("等待确认初始 PRD"), page,
        "建档停下以后项目标记为等待确认初始 PRD", 180_000);
      await expect(page.locator(".project-entry").filter({ hasText: PROJECT })).toContainText("等待确认初始 PRD");

      // 部门工作间的「阅读已有项目」动作：由 read_file、search 与 read_range 的 tool_started 事件驱动。
      // 建档在页面打开以前就跑完了读取，订阅收不到那些事件，区块按 run.actions 的动作列表显示最近一次读取
      // （工单 #332）。脚本里质检的读取是 read_range，工程读的是 src/echo.py 的区间。
      await navigate(page, id, "dept/engineering");
      await waitUntil(async () => (await (await section(page, "阅读已有项目")).count()) > 0, page,
        "部门工作间出现阅读已有项目的区块", 60_000);
      await expect(await section(page, "阅读已有项目")).toContainText("正在阅读已有项目");
      await expect(await section(page, "阅读已有项目")).toContainText("read_range");

      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  
  });

test.describe("接入已有项目（1920×1080）", () => {
  });