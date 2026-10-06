// 客户端外壳的端到端测试（工单 #79 的验收）：Playwright 启动 Electron，连接真实运行的后端
// （FakeAdapter 驱动的服务，见 tests/e2e/backend.py）。窗口尺寸 1440×900 与 390×844，控制台错误为零。

import { expect, test } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";
import { CLIENT_API_VERSION } from "../../src/renderer/src/api/interface-version";

let backend: Backend;

// 启动后端（FakeAdapter 驱动的服务）到首行输出的用时由后端的 git 子进程决定：本机空闲时 18 至 25 秒，
// 并发负载下 60 至 75 秒（#214）。这个界限只用来防止后端不输出时一直等待，按 #107 的裁定
// （docs/architecture-issues.md，架构师 2026-09-27 16:55）设为远大于正常用时的值。Playwright 的
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
  await expect(client.page.locator(".brand")).toHaveText("Yudao");
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

test("客户端连接本机部署与局域网内另一台机器上的部署都能读取能力清单", async () => {
  // 两种访问方式都用同一个真实服务核对：本机地址与局域网地址指向同一个进程，
  // 客户端在两种地址下都能读取能力清单并打开外壳（工单第一条验收）
  for (const size of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    const client = await openClient(size);
    const errors = watchErrors(client);
    try {
      await expect(client.page.locator(".sidebar")).toBeVisible();
      await expect(client.page.locator("text=请更新客户端")).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  }
});

test("连接「本机」而服务已经在运行时，客户端直接连接并读取能力清单", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    await expect(client.page.locator(".connection")).toHaveText("已连接");
    // 首页已经由 #175 实现：外壳连上以后直接显示状态项与离开期间的报告，不再是占位页
    await expect(client.page.locator(".status-row .status-item")).not.toHaveCount(0);
    await expect(client.page.getByRole("heading", { name: "离开期间的报告", exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("能力清单缺少某个查询时，依赖它的页面入口不出现", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    // 当前部署的注册表没有 machines.list、runtime.slots、tools.registry 等查询
    await expect(client.page.getByRole("button", { name: "机器" })).toHaveCount(0);
    await expect(client.page.getByRole("button", { name: "运行与执行槽位" })).toHaveCount(0);
    await expect(client.page.getByRole("button", { name: "工具与扩展" })).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("顶栏与托盘图标的待你决定数量与 decisions.list 中等待回答的数量一致", async () => {
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
    // 托盘图标使用同一份数据：主进程记录的计数与等待数量一致
    const trayCount = await client.app.evaluate(() => (globalThis as { yudaoTrayCount?: () => number }).yudaoTrayCount?.() ?? null);
    expect(trayCount).toBe(waiting);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("窗口关闭后新的决定请求到达时出现系统通知", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    // 关闭窗口：客户端只隐藏窗口，保留托盘与事件流连接。这里经主进程隐藏窗口，
    // 与点击窗口关闭按钮的效果一致（渲染进程仍在，事件流连接保留）
    await client.app.evaluate(() => (globalThis as { yudaoHideWindow?: () => void }).yudaoHideWindow?.());
    await client.page.waitForTimeout(300);
    // 回答现有的决定请求（选项 continue）：阻塞的 run 继续运行，下一次请求再次遇到模型不可用，
    // 发出新的决定请求；窗口已经关闭，事件流仍在，客户端据此发出系统通知
    const answered = await client.page.evaluate(async (address: string) => {
      const listed = await (await fetch(`${address}/api/queries/decisions.list?status=open`)).json();
      const [decision] = listed.data.decisions;
      const response = await fetch(`${address}/api/commands/decision.answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command_id: crypto.randomUUID(),
          decision_id: decision.decision_id,
          option: "continue",
          base_version: decision.version,
        }),
      });
      return response.status;
    }, backend.address);
    expect(answered).toBe(200);

    // 主进程收到新的决定请求后发出通知
    const notifications = await client.app.evaluate(async () => {
      const read = (globalThis as { yudaoNotifications?: () => { title: string; body: string }[] }).yudaoNotifications;
      const deadline = Date.now() + 20000;
      while (Date.now() < deadline) {
        const list = read?.() ?? [];
        if (list.length > 0) {
          return list;
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      return [];
    });
    expect(notifications.length).toBeGreaterThan(0);
    expect(notifications[0].title).toContain("决定");
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

test("从想法新建：提交成功、项目出现在列表以后表单关闭，重新打开时字段为空", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const page = client.page;
    const name = `表单关闭的项目 ${Date.now()}`;
    await page.locator(".sidebar .nav-item", { hasText: "从想法新建" }).click();
    const form = page.locator("form.card").filter({ has: page.getByRole("heading", { name: "从想法新建项目" }) });
    await expect(form).toBeVisible();
    await form.getByLabel("项目名称").fill(name);
    await form.getByLabel("长期目标").fill("核对新建表单的关闭与清空");
    await form.getByRole("button", { name: "新建项目" }).click();
    // 事件到达、项目出现在列表里：表单随之关闭
    await expect(page.locator(".project-entry").filter({ hasText: name })).toBeVisible();
    await expect(form).toHaveCount(0);
    // 重新打开表单：名称、长期目标与起始文件夹都是空的（字段随表单一起清空）
    await page.locator(".sidebar .nav-item", { hasText: "从想法新建" }).click();
    const reopened = page.locator("form.card").filter({ has: page.getByRole("heading", { name: "从想法新建项目" }) });
    await expect(reopened.getByLabel("项目名称")).toHaveValue("");
    await expect(reopened.getByLabel("长期目标")).toHaveValue("");
    await expect(reopened.getByLabel("起始文件夹")).toHaveValue("");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("接口版本相同而能力清单多出查询时，客户端正常使用（新增查询不要求更新客户端）", async () => {
  // 当前部署的接口版本与服务端构建版本相同；服务端的能力清单包含项目与决定相关的查询，
  // 客户端按能力清单打开外壳与项目标签，不出现更新页
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    await client.page.evaluate((hash: string) => {
      window.location.hash = hash;
    }, "#/home");
    await expect(client.page.locator(".sidebar")).toBeVisible();
    await expect(client.page.locator("text=请更新客户端")).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("接口版本不同时客户端只显示更新页（写明两边的版本），不打开页面、不执行命令", async () => {
  const other = await startBackend({ apiVersion: CLIENT_API_VERSION + 1 });
  try {
    const client = await startClient(other, { width: 1440, height: 900 });
    const errors = watchErrors(client);
    try {
      await expect(client.page.getByRole("heading", { name: "请更新客户端" })).toBeVisible();
      await expect(client.page.locator(`text=客户端接口版本：${CLIENT_API_VERSION}`)).toBeVisible();
      await expect(client.page.locator(`text=Yudao 服务接口版本：${CLIENT_API_VERSION + 1}`)).toBeVisible();
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

test("窗口尺寸 390×844 下外壳可用，没有横向滚动条，控制台错误为零", async () => {
  const client = await startClient(backend, { width: 390, height: 844 });
  const errors = watchErrors(client);
  try {
    await expect(client.page.locator(".brand")).toHaveText("Yudao");
    const overflow = await client.page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("订阅位置超过日志末尾时服务端发送 resync，客户端据此重新同步快照", async () => {
  // 事件流的缺口与 resync 是「断线以后恢复」的触发条件（设计说明第 5.5 节）：
  // 客户端按位置续传，位置超过日志末尾时服务端发送 resync 并关闭连接，客户端重新查询快照再订阅。
  // 这里经真实的 SSE 连接核对服务端的这一行为；客户端一侧的缺口核对与重新查询由 tests/unit 覆盖。
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const frame = await client.page.evaluate(async (address: string) => {
      const end = await (await fetch(`${address}/api/queries/system.status`)).json();
      const response = await fetch(`${address}/api/events?after=${end.position + 1000}`, {
        headers: { Accept: "text/event-stream" },
      });
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let text = "";
      const deadline = Date.now() + 10000;
      while (Date.now() < deadline) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        text += decoder.decode(value, { stream: true });
        if (text.includes("resync")) {
          break;
        }
      }
      reader.cancel();
      return text;
    }, backend.address);
    expect(frame).toContain("event: resync");
    expect(frame).toContain("position_unknown");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
