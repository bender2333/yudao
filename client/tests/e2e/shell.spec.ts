// 页面外壳的端到端测试（工单 #79 的验收）：Playwright 打开 Chromium 页面，连接真实运行的后端
// （FakeAdapter 驱动的服务，见 tests/e2e/backend.py）。视口尺寸 1440×900 与 1920×1080，控制台错误为零。

import { expect, test } from "@playwright/test";
import { join } from "node:path";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";
import { CLIENT_API_VERSION } from "../../src/renderer/src/api/interface-version";

let backend: Backend;

// 本机留证据时的截图目录（环境变量 YUDAO_SHOTS 给出，交付说明里列路径）；CI 里不设，不写文件
const SHOTS = process.env.YUDAO_SHOTS ?? "";

async function shot(page: ClientApp["page"], name: string): Promise<void> {
  if (SHOTS === "") return;
  await page.screenshot({ path: join(SHOTS, name), fullPage: false });
}

// 启动后端（FakeAdapter 驱动的服务）到首行输出的用时由后端的 git 子进程决定：本机空闲时 18 至 25 秒，
// 并发负载下 60 至 75 秒（#214）。这个界限只用来防止后端不输出时一直等待，按 #107 的裁定
// （docs/archive/architecture-issues-2026-09-10.md，架构师 2026-09-27 16:55）设为远大于正常用时的值。Playwright 的
// beforeAll 默认沿用配置里的测试时限（client/playwright.config.ts 的 60 秒），在这里单独放宽这一个会合点，
// 各条测试自己的时限不变。
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

async function openClient(size: { width: number; height: number }): Promise<ClientApp> {
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  return client;
}

// 控制台错误：在每个用例里收集，结束时核对为零
function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test("页面打开以后直接读取能力清单并进入外壳", async () => {
  // 网页里没有连接设置：页面从自己来源的服务读取能力清单；两种视口各核对一次
  // （首条验收：能力清单可读、外壳打开）
  for (const size of [
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ]) {
    const client = await openClient(size);
    const errors = watchErrors(client);
    try {
      await expect(client.page.locator(".sidebar")).toBeVisible();
      await expect(client.page.locator("text=页面与服务的接口版本不同")).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  }
});


test("能力清单缺少某个查询时，依赖它的页面入口不出现", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    // 当前部署的注册表没有 machines.list、tools.registry 等查询
    await expect(client.page.getByRole("button", { name: "机器" })).toHaveCount(0);
    await expect(client.page.getByRole("button", { name: "工具与扩展" })).toHaveCount(0);
    // 执行槽位这一页的数据来自 system.status（工单 #727），所以它的入口在
    await expect(client.page.getByRole("button", { name: "运行与执行槽位" })).toHaveCount(1);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("顶栏的待你决定数量与 decisions.list 中等待回答的数量一致", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const waiting = await client.page.evaluate(async (address: string) => {
      const result = await fetch(`${address}/api/queries/decisions.list?status=open`);
      const body = (await result.json()) as { data: { decisions: unknown[] } };
      return body.data.decisions.length;
    }, backend.address);
    expect(waiting).toBeGreaterThan(0);
    await expect(client.page.locator(".topbar .status-item").filter({ hasText: "待你决定：" })).toHaveText(`待你决定：${waiting}`);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});


test("事件流驱动视图刷新：经命令新建项目以后，左侧栏无需刷新即出现新项目", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const before = await client.page.locator(".sidebar .nav-group button").count();
    const created = await client.page.evaluate(async (address: string) => {
      const response = await fetch(`${address}/api/commands/project.create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command_id: crypto.randomUUID(), name: "流驱动的新项目", goal: "验证事件流" }),
      });
      return response.status;
    }, backend.address);
    expect(created).toBe(200);
    // 视图同步按能力清单声明的 changed_by 重新查询 projects.list
    await expect(client.page.locator(".sidebar", { hasText: "流驱动的新项目" })).toBeVisible();
    const after = await client.page.locator(".sidebar .nav-group button").count();
    expect(after).toBeGreaterThan(before);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});



// 首页两个入口各带一行场景说明，新建项目表单写清需求材料在下一步作为事项输入提交（工单 #1240，
// 试用问题 Te28ea596-04）：拿 16KB 需求正文的新手原来从首页看不出走哪个入口、材料放在哪一步。
test("首页两个入口各带场景说明，新建项目表单说明需求材料在下一步作为事项提交", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.evaluate(() => {
      window.location.hash = "#/home";
    });
    await expect(page.locator(".page.home")).toBeVisible();

    // 两个入口在这里能看到，各自带一句说明
    const notes = page.locator(".sidebar .y10-entry-note");
    await expect(notes).toHaveText([
      "从一段想法或需求文字开始，可以先建一个空项目。",
      "把电脑上已有的代码目录接进来，先建档再做事项。",
    ]);
    // 每条说明跟着自己的入口按钮：说明写在按钮所在的那一格里，不会串到另一个入口
    const ideaEntry = page.locator(".y10-side-actions .y10-side-action").filter({ hasText: "从想法新建" });
    const onboardEntry = page.locator(".y10-side-actions .y10-side-action").filter({ hasText: "接入已有项目" });
    await expect(ideaEntry.locator(".y10-new-project")).toBeVisible();
    await expect(onboardEntry.locator(".y10-onboard")).toBeVisible();
    await expect(ideaEntry.locator(".y10-entry-note")).toHaveText("从一段想法或需求文字开始，可以先建一个空项目。");
    await expect(onboardEntry.locator(".y10-entry-note")).toHaveText("把电脑上已有的代码目录接进来，先建档再做事项。");

    // 打开「从想法新建」的表单：说明里写清项目不调用模型、材料在建好项目以后到概览里作为新事项开始时提交
    await page.getByRole("button", { name: "从想法新建" }).click();
    const form = page.locator("form.card").filter({ has: page.getByRole("heading", { name: "从想法新建项目" }) });
    await expect(form).toBeVisible();
    const note = form.locator("p.y10-note");
    await expect(note).toContainText("新建项目不调用模型");
    await expect(note).toContainText("需求材料");
    await expect(note).toContainText("作为新事项开始时提交");
    await expect(note).toContainText("概览");

    await shot(page, "shell-home-entries-and-new-project-note.png");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});


test("接口版本不同时页面只显示版本不同的提示（写明两边的版本），不打开页面、不执行命令", async () => {
  const other = await startBackend({ apiVersion: CLIENT_API_VERSION + 1 });
  try {
    const client = await startClient(other, { width: 1440, height: 900 });
    const errors = watchErrors(client);
    try {
      await expect(client.page.getByRole("heading", { name: "页面与服务的接口版本不同" })).toBeVisible();
      // 页面上的措辞按工单 #704 改过：写清这一份页面文件与服务各是哪个版本（原来写「页面的接口版本是 7」）
      await expect(client.page.locator(".gate .error")).toContainText(`这一份页面文件的接口版本是 ${CLIENT_API_VERSION}`);
      await expect(client.page.locator(".gate .error")).toContainText(`服务要的是 ${CLIENT_API_VERSION + 1}`);
      // 不打开任何页面：外壳与左侧栏都不出现
      await expect(client.page.locator(".sidebar")).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  } finally {
    await other.stop();
  }
});


// 连接断开时窗口整体变灰、顶栏写明断开的时间，重新连上以后恢复（设计说明第 3.4 节，工单 #296）
test("事件流断开时窗口整体变灰并写明断开的时间，重新连上以后恢复", async () => {
  test.setTimeout(240_000);
  // 这个用例自己起服务：断线要真的停掉它，再用同一端口与数据目录起回来
  const own = await startBackend();
  const client = await startClient(own, { width: 1440, height: 900 });
  try {
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: 90_000 });

    await own.stop();
    await expect(client.page.locator("body")).toHaveClass(/is-disconnected/, { timeout: 60_000 });
    // 顶栏写明断开的时间与正在重新连接（不是「连接中断，数据可能过时」这一句旧文案）
    await expect(client.page.locator(".connection.interrupted")).toContainText("断开，正在重新连接");
    const stamp = await client.page.locator(".connection.interrupted").innerText();
    expect(stamp).toMatch(/\d{2}:\d{2}/);
    // 数据保留最后一次的：首页仍然显示
    await expect(client.page.locator(".page.home")).toBeVisible();

    const again = await startBackend({ port: own.port, dataDir: own.dataDir });
    try {
      await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: 90_000 });
      await expect(client.page.locator("body")).not.toHaveClass(/is-disconnected/);
    } finally {
      await again.stop();
    }
  } finally {
    await client.close();
    await own.stop();
  }
});





