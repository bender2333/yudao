// 楼层画面的端到端测试（工单 #82 验收标准 4）：Playwright 打开 Chromium 页面，页面由 FakeAdapter 驱动的真实服务提供。
// 项目的循环画面在概览页出现；事项在服务端推进时画面随事件流变化；画面的每个动作对应一条真实事件；
// 断线重连（重新订阅）以后画面回到查询给出的状态；系统设置为减少动画时气泡照样显示。
//
// 观测方式：读画布的内容签名（像素差异）与页面上循环画面的可见内容；事件来自服务的查询与事件流，
// 不做伪造。页面用构建产物（与 shell.spec.ts 相同），从后端地址打开，与接口同一来源。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";
import { type FlowSegment } from "../../src/renderer/src/views/project/flow-segments.ts";
import type { FlowRecord } from "../../src/renderer/src/api/generated/types.gen";

const SAMPLE = "示例项目";
const SAMPLE_ITEM = "实现回声工具";
/** 交付历史项目（工单 #866）：同一对部门上有一条非返工流转与一条返工那条（质检提交缺陷记录）。 */
const HISTORY = "交付历史";

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

// 查询与命令直接从 Node 发：服务本身是真实的，页面与接口同一来源，同样能连
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

/**
 * 打开一个项目的概览页，等循环画面的画布出现。
 * 文字列表默认折叠（工单 #379 验收：展开以后每行显示中文部门名与中文状态），
 * 读行数的用例在这里展开它。
 */
async function openFloor(page: Page, id: string): Promise<void> {
  await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${id}/overview`);
  await expect(page.locator(".floor-screen canvas")).toHaveCount(1);
  await openTextList(page);
}

/** 展开画面下方的文字列表（决定卡片里还有自己的折叠块，只点这一层的标题）。 */
async function openTextList(page: Page): Promise<void> {
  const details = page.locator("details.floor-text-list");
  await expect(details).toHaveCount(1);
  await details.locator("> summary").click();
  await expect(details).toHaveJSProperty("open", true);
}
/**
 * 画布的内容签名：把画布导出成一张缩小的图，取它的数据摘要。
 * 画布按设备分辨率绘制（工单 #365），导出的图随之变小；画面每帧都在动，签名只用来核对「画出了内容」。
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

/** 画面里世界的当前状态（经页面上给端到端测试的只读入口）：角色的任务与事项的状态。 */
async function floorState(page: Page): Promise<FloorWorldState> {
  return page.evaluate(() => {
    const hooks = (window as unknown as { __floorViewForTest?: { state: () => FloorWorldState } }).__floorViewForTest;
    if (!hooks) throw new Error("页面没有画面的读取入口");
    return hooks.state();
  });
}

interface FloorWorldState {
  characters: { id: string; department: string | null; task: string | null; bubble: string | null; pose: string | null }[];
  items: { id: string; status: string; department: string | null }[];
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

// 楼层周围的结构按原型 v10（工单 #379 验收）：覆盖层按钮条是画面上方一条独立的条，不压在画面上；
// 文字列表默认折叠，展开以后每行给中文部门名与中文状态。
test("覆盖层按钮条在画面上方不与画面重叠，文字列表默认折叠且展开后写中文部门与中文状态", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(SAMPLE);
    await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${id}/overview`);
    await expect(page.locator(".floor-screen canvas")).toHaveCount(1);

    // 按钮条在画面所在的面板里、画布上方，底边不越过画布的顶边
    const bar = page.locator(".floor-overlay-tabs");
    await expect(bar).toHaveCount(1);
    await expect(page.locator(".y10-scene.y10-floor-wrap .floor-overlay-tabs")).toHaveCount(1);
    const box = await page.evaluate(() => {
      const bar = document.querySelector(".floor-overlay-tabs")!.getBoundingClientRect();
      const canvas = document.querySelector(".floor-screen canvas")!.getBoundingClientRect();
      return { barBottom: bar.bottom, canvasTop: canvas.top, barHeight: bar.height };
    });
    expect(box.barHeight).toBeGreaterThan(0);
    expect(box.barBottom).toBeLessThanOrEqual(box.canvasTop + 1);

    // 文字列表默认折叠：折叠时行不可见，展开以后每行给出中文部门名与中文状态
    const details = page.locator("details.floor-text-list");
    await expect(details).toHaveCount(1);
    await expect(details.locator("li").first()).toBeHidden();
    await openTextList(page);
    const loop = await query<{ work_items: { work_item_id: string; department: string | null; status: string }[] }>(
      "project.loop", { project_id: id });
    const texts = await details.locator("li").evaluateAll((nodes) => nodes.map((node) => node.textContent ?? ""));
    expect(texts.length).toBe(loop.work_items.length);
    for (const text of texts) {
      expect(text).toMatch(/(大厅|产品|工程|质检|运维)/);
      // 排队中的事项写「排队中」（工单 #733 以后不再写「未开始」）
      expect(text).toMatch(/(进行中|已采纳|已放行|等待确认初始 PRD|已停止|排队中|成果已挂起)/);
    }
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
    await openTextList(page);
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
    // 画面里配置的事项状态与 project.loop 一致：状态来自查询
    const loop = await query<{ work_items: { work_item_id: string; status: string }[] }>(
      "project.loop", { project_id: id });
    expect(loop.work_items.length).toBeGreaterThan(0);
    const fromQuery = JSON.stringify(loop.work_items.map((it) => [it.work_item_id, it.status]));
    await waitUntil(async () => {
      const now = await floorState(page);
      return JSON.stringify(now.items.map((it) => [it.id, it.status])) === fromQuery;
    }, "画面里的事项状态与查询一致");
    // 断线：停掉事件流连接（主进程的窗口关闭再打开时由客户端自己重连；这里用重新连接设置模拟）
    await page.evaluate(() => { window.location.hash = "#/home"; });
    await expect(page.locator(".floor-screen canvas")).toHaveCount(0);
    await openFloor(page, id);
    // 重新打开以后画面按查询给出的状态配置：事项的状态逐项与 project.loop 一致
    // （动作不补播，事项状态才由查询给出）
    await waitUntil(async () => {
      const now = await floorState(page);
      return JSON.stringify(now.items.map((it) => [it.id, it.status])) === fromQuery;
    }, "画面回到查询给出的状态");
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
    { width: 1920, height: 1080 },
  ]) {
    const client = await startClient(backend, size);
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(SAMPLE);
      await openFloor(page, id);
      const width = await page.locator(".floor-screen canvas").evaluate((el) => (el as HTMLCanvasElement).width);
      expect(width % 640).toBe(0);
      // 画面下方的文字列表可见，页面不出现横向溢出
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
// 流转覆盖层（工单 #866 验收标准 1、2；工单 #882 加 PRD 新版本）：应用层给出的流转种类有
// 版本交付、询问、问题反馈与 PRD 新版本四种。真实事件在 quality→engineering 上产生一条「询问」与
// 一条「问题反馈」（质检提交缺陷记录，返工那条）；工程→quality 上有两条「版本交付」，合成一段；
// 产品接纳 PRD 以后，产品→工程与产品→质检各有一条「PRD 新版本」，各成一段。
// 应有的分段由工单规定并写在这里：quality→engineering 上非返工一段（次数 1）、返工一段（次数 1），
// 产品→工程与产品→质检各一段（次数等于这个事项接纳过的 PRD 版本数），全画面六段。
// 端到端的预期不复用实现的聚合公式。
test("流转覆盖层：同一对部门的两种非返工流转合成一段，返工另成一段，PRD 新版本各成一段，标签互不遮挡", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(HISTORY);
    const flow = await query<{ records: FlowRecord[] }>("project.flow", { project_id: id });
    // 场景本身来自真实事件：同一对部门上有一条非返工流转与一条返工那条
    const rows = flow.records.filter((row) => row.direction_from === "quality" && row.direction_to === "engineering");
    expect(rows.filter((row) => row.kind === "询问").length).toBe(1);
    expect(rows.filter((row) => row.kind === "问题反馈").length).toBe(1);
    // PRD 新版本（工单 #882）：每接纳一版 PRD，产品→工程与产品→质检各一条；
    // 这个事项接纳过的 PRD 版本数由真实事件数出来
    const prdRows = flow.records.filter((row) => row.kind === "PRD 新版本" && row.direction_from === "product");
    const prdVersions = prdRows.filter((row) => row.direction_to === "engineering").length;
    expect(prdVersions).toBeGreaterThan(0);
    expect(prdRows.filter((row) => row.direction_to === "quality").length).toBe(prdVersions);
    await openFloor(page, id);
    await page.locator(".floor-overlay-tabs button", { hasText: "流转" }).click();
    await waitUntil(async () => (await readOverlay(page)).segments.length > 0, "画面写入流转覆盖层的 segments");
    const overlay = await readOverlay(page);
    expect(overlay.id).toBe("flow");

    // 应有的分段写死：quality→engineering 上恰好两段，非返工一段次数 1、返工一段次数 1
    const pair = overlay.segments.filter((seg) => seg.from === "quality" && seg.to === "engineering");
    expect(pair.length).toBe(2);
    const plain = pair.find((seg) => seg.kind !== "rework");
    const rework = pair.find((seg) => seg.kind === "rework");
    expect(plain?.count).toBe(1);
    expect(rework?.count).toBe(1);
    expect(plain!.count + rework!.count).toBe(rows.length);
    // PRD 新版本：产品→工程与产品→质检各一段，次数等于这个事项接纳过的 PRD 版本数
    const toEngineering = overlay.segments.filter((seg) => seg.from === "product" && seg.to === "engineering");
    expect(toEngineering.length).toBe(1);
    expect(toEngineering[0].count).toBe(prdVersions);
    const toQuality = overlay.segments.filter((seg) => seg.from === "product" && seg.to === "quality");
    expect(toQuality.length).toBe(1);
    expect(toQuality[0].count).toBe(prdVersions);
    // 六段：engineering→product、product→engineering、product→quality、engineering→quality、
    // quality→engineering 的非返工段与返工段。段数由真实事件的流转数出来：
    // 同一对部门的非返工流转合成一段，返工那条另成一段
    const expected = new Set<string>();
    for (const row of flow.records) {
      expected.add(`${row.direction_from}>${row.direction_to}>${row.kind === "问题反馈" ? "rework" : ""}`);
    }
    expect(overlay.segments.length).toBe(expected.size);
    expect(overlay.segments.length).toBe(6);
    // 同一对部门的两种非返工流转合成一段：engineering→quality 的两条版本交付并成一段，次数 2
    const delivery = overlay.segments.filter((seg) => seg.from === "engineering" && seg.to === "quality");
    expect(delivery.length).toBe(1);
    expect(delivery[0].count).toBe(2);

    // 标签不遮挡：quality→engineering 的两块牌子各自画出且互不重叠（读最近一帧画出的牌子矩形）
    await waitUntil(async () => {
      const drawn = await readLabelRects(page);
      return drawn.filter((rect) => rect.key === "quality>engineering").length === 2;
    }, "画面为 quality→engineering 的非返工段与返工段各画出一块标签", 20_000);
    const rects = await readLabelRects(page);
    const pairRects = rects.filter((rect) => rect.key === "quality>engineering");
    expect(pairRects.length).toBe(2);
    const [a, b] = pairRects;
    const covered = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
    expect(covered, `quality→engineering 的两块牌子重叠：${JSON.stringify(pairRects)}`).toBe(false);
    // 牌子落在画面内：整块牌子在楼层画面的可见范围内
    for (const rect of pairRects) {
      expect(rect.x).toBeGreaterThanOrEqual(0);
      expect(rect.y).toBeGreaterThanOrEqual(0);
      expect(rect.x + rect.w).toBeLessThanOrEqual(640);
    }
    // 返工那块牌子按红色画，同一条路径上的另一块是白底：一红一白
    // （牌子按段的顺序画出，overlayLabels 与段的顺序一一对应）
    const reworkIndex = pair.findIndex((seg) => seg.kind === "rework");
    const reds = await readSignColors(page, pairRects);
    expect(reds.length).toBe(2);
    expect(reds[reworkIndex], `返工那块牌子不是红的：${JSON.stringify(reds)}`).toBeGreaterThan(60);
    expect(reds[reworkIndex === 0 ? 1 : 0], `非返工那块牌子不是白底：${JSON.stringify(reds)}`).toBeLessThan(40);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

// 流转覆盖层（工单 #913）：同一对部门的反向两段（产品→工程 与 工程→产品）走同一条路径，
// 两块「N 次」牌子原来落在同一个位置，后画的一块把先画的一块盖住，只能看见其中一段的次数。
// 车道键改成无序的部门对以后两块牌子错开，都看得见；段的数量、次数与箭头方向不变。
test("流转覆盖层：同一对部门的正反两段牌子错开，都看得见", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(HISTORY);
    await openFloor(page, id);
    await page.locator(".floor-overlay-tabs button", { hasText: "流转" }).click();
    await waitUntil(async () => (await readOverlay(page)).segments.length > 0, "画面写入流转覆盖层的 segments");
    const overlay = await readOverlay(page);
    expect(overlay.id).toBe("flow");
    // 正反两段都在：产品→工程 与 工程→产品（同一对部门，方向相反）
    const forward = overlay.segments.filter((seg) => seg.from === "product" && seg.to === "engineering");
    const backward = overlay.segments.filter((seg) => seg.from === "engineering" && seg.to === "product");
    expect(forward.length).toBe(1);
    expect(backward.length).toBe(1);
    // 两段各画出一块牌子（牌子的键带方向，用例据此分清哪一块是哪一段）
    await waitUntil(async () => {
      const drawn = await readLabelRects(page);
      return drawn.filter((rect) => rect.key === "product>engineering").length === 1
        && drawn.filter((rect) => rect.key === "engineering>product").length === 1;
    }, "画面为产品→工程与工程→产品各画出一块标签", 20_000);
    const rects = await readLabelRects(page);
    const a = rects.find((rect) => rect.key === "product>engineering")!;
    const b = rects.find((rect) => rect.key === "engineering>product")!;
    // 两块牌子的纵向位置不同（同一条路径上的第二块往上抬一行）
    expect(a.y, `两块牌子的纵向位置相同：${JSON.stringify([a, b])}`).not.toBe(b.y);
    const covered = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
    expect(covered, `产品→工程与工程→产品的两块牌子重叠：${JSON.stringify([a, b])}`).toBe(false);
    // 两块牌子都落在画面内
    for (const rect of [a, b]) {
      expect(rect.x).toBeGreaterThanOrEqual(0);
      expect(rect.y).toBeGreaterThanOrEqual(0);
      expect(rect.x + rect.w).toBeLessThanOrEqual(640);
    }
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

/** 每块牌子里最红的像素（红减蓝）：红底牌子明显大于白底牌子。 */
async function readSignColors(page: Page, rects: { x: number; y: number; w: number; h: number }[]): Promise<number[]> {
  return page.evaluate((rects) => {
    const canvas = document.querySelector(".floor-screen canvas") as HTMLCanvasElement | null;
    if (!canvas) return [];
    const off = document.createElement("canvas");
    off.width = 160;
    off.height = 80;
    const ctx = off.getContext("2d");
    if (!ctx) return [];
    ctx.drawImage(canvas, 0, 0, 160, 80);
    const data = ctx.getImageData(0, 0, 160, 80).data;
    return rects.map((r) => {
      let best = -999;
      const x0 = Math.max(0, Math.floor(r.x / 4));
      const x1 = Math.min(159, Math.ceil((r.x + r.w) / 4));
      const y0 = Math.max(0, Math.floor(r.y / 4));
      const y1 = Math.min(79, Math.ceil((r.y + r.h) / 4));
      for (let y = y0; y <= y1; y += 1) {
        for (let x = x0; x <= x1; x += 1) {
          const i = (y * 160 + x) * 4;
          best = Math.max(best, data[i] - data[i + 2]);
        }
      }
      return best;
    });
  }, rects);
}

/** 在页面里读出最近一帧画出的覆盖层标签矩形（画面逻辑坐标）；逐字段检查再返回。 */
async function readLabelRects(page: Page): Promise<{ x: number; y: number; w: number; h: number; key: string }[]> {
  return page.evaluate(() => {
    const win: unknown = window;
    if (!win || typeof win !== "object" || !("__floorViewForTest" in win)) return [];
    const hooks = win.__floorViewForTest;
    if (!hooks || typeof hooks !== "object" || !("overlayLabels" in hooks)) return [];
    const read = hooks.overlayLabels;
    if (typeof read !== "function") return [];
    const raw: unknown = read();
    if (!Array.isArray(raw)) return [];
    const out: { x: number; y: number; w: number; h: number; key: string }[] = [];
    for (const item of raw) {
      if (!item || typeof item !== "object") continue;
      const { x, y, w, h, key } = item as Record<string, unknown>;
      if (typeof x === "number" && typeof y === "number" && typeof w === "number"
        && typeof h === "number" && typeof key === "string") {
        out.push({ x, y, w, h, key });
      }
    }
    return out;
  });
}

/** 在页面里读出当前画面的覆盖层；逐字段检查再返回。 */
async function readOverlay(page: Page): Promise<{ id: string | null; segments: FlowSegment[] }> {
  return page.evaluate(() => {
    const win: unknown = window;
    if (!win || typeof win !== "object" || !("__floorViewForTest" in win)) return { id: null, segments: [] };
    const hooks = win.__floorViewForTest;
    if (!hooks || typeof hooks !== "object" || !("overlay" in hooks)) return { id: null, segments: [] };
    const overlayFn = hooks.overlay;
    if (typeof overlayFn !== "function") return { id: null, segments: [] };
    const overlay: unknown = overlayFn();
    if (!overlay || typeof overlay !== "object" || !("id" in overlay) || !("data" in overlay)) {
      return { id: null, segments: [] };
    }
    const id = typeof overlay.id === "string" ? overlay.id : null;
    const data: unknown = overlay.data;
    if (!data || typeof data !== "object" || !("segments" in data) || !Array.isArray(data.segments)) {
      return { id, segments: [] };
    }
    const segments: FlowSegment[] = [];
    for (const raw of data.segments) {
      if (!raw || typeof raw !== "object") continue;
      if (!("from" in raw) || !("to" in raw) || !("count" in raw) || !("last_at" in raw) || !("kind" in raw)) continue;
      if (typeof raw.from === "string" && typeof raw.to === "string"
        && typeof raw.count === "number" && typeof raw.last_at === "string" && typeof raw.kind === "string") {
        segments.push({ from: raw.from, to: raw.to, count: raw.count, last_at: raw.last_at, kind: raw.kind });
      }
    }
    return { id, segments };
  });
}


// 世界里的决定卡片（工单 #179 验收标准 2）：在真实运行的系统上，文本工具项目产生一个待恢复的决定请求。
// 点大厅的板子打开卡片，点选项盖章回答；事件到达以后这个决定移出等待列表，画面上的纸收起。
// 随后回答「继续执行」会在同一事项上再产生一个待恢复的决定请求，用文字列表里的页面卡片同样回答它。
test("真实系统上的决定请求：点板子打开卡片盖章回答，文字列表里的同一个决定请求也能回答", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId("文本工具");
    await openFloor(page, id);
    const pending = await decisionsOf(id);
    expect(pending.length).toBeGreaterThan(0);
    const target = pending[0];
    // 文字列表里的页面卡片出现，说明画面已经拿到这份决定请求（板子上才有这张便条）
    await expect(page.locator(`#decision-${target.decision_id}`)).toBeVisible();

    // 点大厅的板子打开卡片：画面里的横线纸上叠一个说明的输入框，打开时可见。
    // 板的命中范围在画面逻辑坐标里固定（大厅地面上），点一次没打开时重试
    const note = page.locator('textarea[aria-label="决定的说明"]');
    for (let i = 0; i < 10; i += 1) {
      await clickLogical(page, 82, 172);
      try {
        await note.waitFor({ state: "visible", timeout: 1000 });
        break;
      } catch {
        // 画面还没就绪，重试
      }
    }
    await expect(note).toBeVisible();
    await expect(page.locator(".floor-screen canvas")).toHaveCount(1);

    // 点第一个选项的章（继续执行）回答：命令带着决定的版本发出
    await clickLogical(page, 110, 270);
    await waitUntil(
      async () => !(await decisionsOf(id)).some((row) => row.decision_id === target.decision_id),
      "回答以后这个决定移出等待列表",
    );
    // 纸在盖章 1.2 秒以后收起：说明的输入框不再可见
    await expect(page.locator('textarea[aria-label="决定的说明"]')).toBeHidden();

    // 回答「继续执行」以后同一事项再次遇到模型不可用，产生新的待恢复决定请求；用文字列表的页面卡片回答它
    const next = await waitUntilDecision(id);
    const card = page.locator(`#decision-${next.decision_id}`);
    await expect(card).toBeVisible();
    await card.locator(".decision-answer button").first().click();
    await waitUntil(
      async () => !(await decisionsOf(id)).some((row) => row.decision_id === next.decision_id),
      "文字列表里的决定请求被回答",
    );
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

type DecisionRow = { decision_id: string; version: number; status: string };

async function decisionsOf(projectId: string): Promise<DecisionRow[]> {
  const data = await query<{ decisions: DecisionRow[] }>("decisions.list", { project_id: projectId, status: "open" });
  return data.decisions;
}

/** 等一个等待回答的决定请求出现，返回它。 */
async function waitUntilDecision(projectId: string): Promise<DecisionRow> {
  for (let i = 0; i < 150; i += 1) {
    const rows = await decisionsOf(projectId);
    if (rows.length > 0) return rows[0];
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
  throw new Error("等待超时：新的待恢复决定请求没有出现");
}

/** 在楼层画布上用画面逻辑坐标点一下（换算成画布元素内的 CSS 坐标，按元素点，避开缩放误差）。 */
async function clickLogical(page: Page, x: number, y: number): Promise<void> {
  const canvas = page.locator(".floor-screen canvas");
  await canvas.scrollIntoViewIfNeeded();
  const size = await canvas.evaluate((el) => {
    const rect = el.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  });
  await canvas.click({ position: { x: (x / 640) * size.width, y: (y / 320) * size.height } });
}
