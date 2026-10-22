// 服务中断期间的页面行为（工单 #301）：页面由后端提供，在 Playwright Chromium 中打开。
// 服务停掉以后二十秒内页面没有 pageerror，页面整体变灰、顶栏写明正在重新连接，
// 事件流重连的间隔递增；服务在同一端口恢复以后页面自动恢复，不用刷新页面。
//
// 第二条用例（工单 #777）覆盖同一类问题：一次读取失败不能变成未处理的拒绝。
// 服务停机那条用例要碰上「事件到了以后页面去取名称，而这时服务正好停掉」才触发，时序上不一定碰上；
// 这里把 project.overview 拦成 500（走的正是与真实失败同一条路径），确定性地走到那一次读取。
import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

test("服务停止以后二十秒内没有 pageerror，重连间隔递增；服务恢复以后自动恢复", async () => {
  test.setTimeout(180_000);
  const backend: Backend = await startBackend();
  const client: ClientApp = await startClient(backend, { width: 1440, height: 900 });
  const page = client.page;
  const pageerrors: string[] = [];
  page.on("pageerror", (error) => pageerrors.push(error.message));
  const failedAt: number[] = [];
  page.on("requestfailed", (request) => {
    if (request.url().includes("/api/events")) {
      failedAt.push(Date.now());
    }
  });
  try {
    await expect(page.locator(".brand .y10-brand-name")).toContainText("Yudao");
    await expect(page.locator(".connection")).toHaveText("已连接");
    await backend.stop();
    // 断线：页面整体变灰，顶栏写明正在重新连接，页面不抛错
    await expect(page.locator("body")).toHaveClass(/is-disconnected/, { timeout: 60_000 });
    await expect(page.locator(".connection.interrupted")).toContainText("正在重新连接");
    await page.waitForTimeout(20_000);
    expect(pageerrors).toEqual([]);
    // 重连间隔递增：20 秒内至少失败 4 次，最后一个间隔是第一个的 1.5 倍以上；
    // 固定间隔的重连（例如以前的 3 秒）通不过这一条
    expect(failedAt.length).toBeGreaterThanOrEqual(4);
    const gaps: number[] = [];
    for (let index = 1; index < failedAt.length; index += 1) {
      gaps.push(failedAt[index]! - failedAt[index - 1]!);
    }
    expect(gaps[gaps.length - 1]).toBeGreaterThan(gaps[0]! * 1.5);
    // 服务恢复：同一端口再起一个后端，页面自动恢复，不用刷新页面
    const revived: Backend = await startBackend({ port: backend.port, dataDir: backend.dataDir });
    try {
      await expect(page.locator(".connection")).toHaveText("已连接", { timeout: 60_000 });
      await expect(page.locator("body")).not.toHaveClass(/is-disconnected/);
      expect(pageerrors).toEqual([]);
    } finally {
      await revived.stop();
    }
  } finally {
    await client.close();
  }
});

// 记录 window.Notification 的调用：包装仍然调用真实的构造函数，页面的通知逻辑原样运行。
// window.notifications 的类型在 notifications.spec.ts 里声明（两个文件共用同一个全局声明）
function recordNotifications(): void {
  const Real = window.Notification;
  const recorded: Window["notifications"] = [];
  window.notifications = recorded;
  const Recorded = function (this: Notification, title: string, options?: NotificationOptions) {
    const notification = new Real(title, options);
    recorded.push({ title, body: options?.body ?? "", tag: options?.tag ?? "", notification });
    return notification;
  } as unknown as typeof Notification;
  Object.defineProperty(Recorded, "permission", { get: () => Real.permission });
  Recorded.requestPermission = Real.requestPermission.bind(Real);
  window.Notification = Recorded;
}

test("取名字的那次读取失败时不产生未处理的拒绝，也不发没有名字的通知（工单 #777）", async () => {
  test.setTimeout(180_000);
  const backend: Backend = await startBackend();
  const client: ClientApp = await startClient(backend, { width: 1440, height: 900 }, {
    permissions: ["notifications"],
    initScript: recordNotifications,
    // 事件到了以后页面要取项目名与事项标题：把这一次读取拦成失败
    intercept: async (page: Page) => {
      await page.route("**/api/queries/project.overview*", async (route) => {
        await route.fulfill({ status: 500, contentType: "text/plain", body: "Internal Server Error" });
      });
    },
  });
  const page = client.page;
  const pageerrors: string[] = [];
  page.on("pageerror", (error) => pageerrors.push(error.message));
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    // 浏览器为失败的资源请求自己记一条控制台消息：这一次读取被拦成 500 就是这样的消息，
    // 它不是应用的错误（应用的错误是 pageerror 与页面自己写的错误）
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) {
      consoleErrors.push(message.text());
    }
  });
  try {
    await expect(page.locator(".brand .y10-brand-name")).toContainText("Yudao");
    // 预置的项目里有一条模型不可用的决定请求：它的事件到达页面时页面要去取名称
    await expect.poll(async () => page.title(), { timeout: 60_000 }).toMatch(/^\(\d+\) Yudao$/);
    // 那一次读取失败以后：控制台干净，没有未处理的拒绝
    await page.waitForTimeout(3_000);
    expect(pageerrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
    // 名称没取到就不发那条通知：正文要写明是哪个项目、哪件事，没有名字就不写
    expect(await page.evaluate(() => window.notifications)).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});
