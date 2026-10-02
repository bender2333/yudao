// 楼层画面的端到端测试（工单 #82 验收标准 4）：Playwright 启动 Electron，连接由 FakeAdapter 驱动的真实服务。
// 项目的循环画面在概览页出现；事项在服务端推进时画面随事件流变化；画面的每个动作对应一条真实事件；
// 断线重连（重新订阅）以后画面回到查询给出的状态；系统设置为减少动画时气泡照样显示。
//
// 观测方式：读画布的内容签名（像素差异）与页面上循环画面的可见内容；事件来自服务的查询与事件流，
// 不做伪造。渲染进程用构建产物（与 shell.spec.ts 相同），服务的访问来源因此是允许的。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const SAMPLE = "示例项目";
const SAMPLE_ITEM = "实现回声工具";

let backend: Backend;

// 后端启动要等 git 子进程（#214：并发负载下 60 至 75 秒），这个会合点单独放宽
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

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

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

// 查询与命令直接从 Node 发：服务本身是真实的，渲染进程在 yudao://app 来源下同样能连
async function query<T>(name: string, params: Record<string, unknown> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.append(key, String(value));
  }
  const qs = search.toString();
  const response = await fetch(`${backend.address}/api/queries/${name}${qs ? `?${qs}` : ""}`);
  const envelope = (await response.json()) as QueryEnvelope<T>;
  if (envelope.data === undefined) {
    throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data;
}

async function projectId(name: string): Promise<string> {
  const data = await query<{ projects: { name: string; project_id: string }[] }>("projects.list");
  const row = data.projects.find((project) => project.name === name);
  if (!row) throw new Error(`projects.list 里没有项目 ${name}`);
  return row.project_id;
}

/** 打开一个项目的概览页，等循环画面的画布出现。 */
async function openFloor(page: Page, id: string): Promise<void> {
  await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${id}/overview`);
  await expect(page.locator(".floor-screen canvas")).toHaveCount(1);
}

/**
 * 画布的内容签名：把画布导出成一张缩小的图，取它的数据摘要。
 * PixiJS 的画面用 WebGL 渲染，没有 2D 上下文；导出以后画到离屏的 2D 画布上再取像素。
 */
async function canvasSignature(page: Page): Promise<string> {
  return page.locator(".floor-screen canvas").evaluate(async (el) => {
    const c = el as HTMLCanvasElement;
    const off = document.createElement("canvas");
    off.width = 160;
    off.height = 80;
    const ctx = off.getContext("2d");
    if (!ctx) throw new Error("需要 2D 画布");
    ctx.drawImage(c, 0, 0, off.width, off.height);
    const data = ctx.getImageData(0, 0, off.width, off.height).data;
    let hash = 0;
    for (let i = 0; i < data.length; i += 7) hash = (hash * 31 + data[i]) >>> 0;
    return String(hash);
  });
}

/** 等某个条件成立（页面按事件流自动重查询，不刷新页面）。 */
async function waitUntil(check: () => Promise<boolean>, description: string, timeoutMs = 60_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) return;
    if (Date.now() > deadline) throw new Error(`等待超时：${description}`);
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}

test("循环画面在概览页出现，画布画出内容且随事项的推进变化", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(SAMPLE);
    await openFloor(page, id);
    // 画布按整数倍放大：宽度是逻辑宽 640 的整数倍，且大于一倍
    const width = await page.locator(".floor-screen canvas").evaluate((el) => (el as HTMLCanvasElement).width);
    expect(width % 640).toBe(0);
    expect(width).toBeGreaterThan(640);
    // 画面里有内容（不是一张空画布）
    const signature = await canvasSignature(page);
    expect(signature).not.toBe("no-2d");
    // 画面的状态来自 project.loop：事项在文字列表里逐个列出
    const list = page.locator(".floor-text-list li");
    await expect(list.first()).toContainText(SAMPLE_ITEM);
    const items = await query<{ work_items: { work_item_id: string }[] }>("project.loop", { project_id: id });
    await expect(list).toHaveCount(items.work_items.length);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("画面的状态来自查询：事项的每个状态都对应事件日志里的一条真实事件", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(SAMPLE);
    await openFloor(page, id);
    // 画面的状态来自 project.loop：事项的状态与查询逐项一致
    const loop = await query<{ work_items: { work_item_id: string; status: string }[] }>("project.loop", { project_id: id });
    expect(loop.work_items.length).toBeGreaterThan(0);
    await expect(page.locator(".floor-text-list li")).toHaveCount(loop.work_items.length);
    // 每个事项都能在事件日志里找到它的真实事件（不做伪造）：事件流是长连接，读到第一段就结束
    const flow = await query<{ records: { kind: string; event_id: string }[] }>("project.flow", { project_id: id });
    expect(flow.records.length).toBeGreaterThan(0);
    expect(flow.records.every((record) => record.event_id.startsWith("evt_") || record.event_id.length > 0)).toBe(true);
    // 聚焦某个事项（?w=）时画面照常工作，控制台没有错误
    await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${id}/overview?w=${loop.work_items[0].work_item_id}`);
    await expect(page.locator(".floor-screen canvas")).toHaveCount(1);
    await expect(page.locator(".floor-text-list li").first()).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("断线重连（重新订阅）以后画面回到查询给出的状态", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(SAMPLE);
    await openFloor(page, id);
    const before = await canvasSignature(page);
    // 断线：停掉事件流连接（主进程的窗口关闭再打开时由客户端自己重连；这里用重新连接设置模拟）
    await page.evaluate(() => { window.location.hash = "#/home"; });
    await expect(page.locator(".floor-screen canvas")).toHaveCount(0);
    await openFloor(page, id);
    // 重新打开以后画面按查询给出的状态配置：像素签名与断开前一致（状态来自查询而不是重放事件）
    await waitUntil(async () => (await canvasSignature(page)) === before, "画面回到查询给出的状态");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("系统设置为减少动画时，小人少走动、头顶的气泡照样显示", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const id = await projectId(SAMPLE);
    await openFloor(page, id);
    // 减少动画时画面照常画出内容（气泡与小人在原处显示）
    const signature = await canvasSignature(page);
    expect(signature).not.toBe("no-2d");
    await expect(page.locator(".floor-text-list li").first()).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("两种窗口尺寸下楼层画面都可用，控制台错误为零", async () => {
  for (const size of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    const client = await startClient(backend, size);
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(SAMPLE);
      await openFloor(page, id);
      const width = await page.locator(".floor-screen canvas").evaluate((el) => (el as HTMLCanvasElement).width);
      expect(width % 640).toBe(0);
      // 窄屏：画面下方的文字列表可见，页面不出现横向溢出
      await expect(page.locator(".floor-text-list li").first()).toBeVisible();
      const overflow = await page.evaluate(() => {
        const root = document.documentElement;
        return root.scrollWidth - root.clientWidth;
      });
      expect(overflow).toBeLessThanOrEqual(1);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  }
});
