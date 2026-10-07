// 服务中断期间的页面行为（工单 #301）：页面由后端提供，在 Playwright Chromium 中打开。
// 服务停掉以后二十秒内页面没有 pageerror，页面整体变灰、顶栏写明正在重新连接，
// 事件流重连的间隔递增；服务在同一端口恢复以后页面自动恢复，不用刷新页面。
import { expect, test } from "@playwright/test";
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
    await expect(page.locator(".brand")).toHaveText("Yudao");
    await expect(page.locator(".connection")).toHaveText("已连接");
    await backend.stop();
    // 断线：页面整体变灰，顶栏写明正在重新连接，页面不抛错
    await expect(page.locator(".app")).toHaveClass(/is-disconnected/, { timeout: 60_000 });
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
      await expect(page.locator(".app")).not.toHaveClass(/is-disconnected/);
      expect(pageerrors).toEqual([]);
    } finally {
      await revived.stop();
    }
  } finally {
    await client.close();
  }
});
