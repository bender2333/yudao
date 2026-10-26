// H1 与 H2 的单元测试（画面与播放设计说明第 8 节、第 8.1 节；工单 #959）。
//
// H1 事实层是事件的函数：同一份查询结果两次翻译得到的状态相同；同一份状态两次上画面，承载事实的通道相同。
// H2 表演层不占用承载事实的视觉通道：同一份状态上画面以后，开着表演层（待机活动与动作）与关掉它各读一次
//    承载事实的通道，两次相同。
//
// 三个场景各一组（楼、楼层、房间）。画面用 PixiJS 画，需要浏览器：模块由 Vite 的模块服务器提供，
// 与逐场景回放、部门切换的测试同一方式（一张空白页、一个手动时钟、画面自己推进到固定的时刻）。
// 通道由各场景的 inspect() 交出（inspect().channels()），关掉表演层用 view.performance(false)。

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer, type ViteDevServer } from "vite";
import { chromium, type Browser } from "@playwright/test";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

let server: ViteDevServer;
let browser: Browser;
let address = "";

before(async () => {
  server = await createServer({
    root: join(clientRoot, "src", "renderer"),
    // 单元测试文件之间并行运行：缓存目录与别的浏览器测试分开，避免两个服务器同时改写同一份缓存
    cacheDir: join(clientRoot, "node_modules", ".vite-pixel-honesty"),
    plugins: [],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
  });
  await server.listen();
  const url = server.resolvedUrls?.local[0];
  if (!url) throw new Error("渲染进程的模块服务器没有给出地址");
  address = url;
  browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
});

after(async () => {
  await browser?.close();
  await server?.close();
});

/** 一次核对的读数：翻译是否稳定、同一份状态两次上画面的通道、表演层开着与关掉时的通道。 */
interface HonestyReport {
  /** 同一份查询结果两次翻译得到的状态是否相同。 */
  stable: boolean;
  /** 翻译出来的状态的位置（画面上的状态来自的查询快照）。 */
  translatedPosition: number;
  /** 同一份状态两次上画面，各读一次承载事实的通道。 */
  twice: [unknown, unknown];
  /** 同一份状态上画面以后，开着表演层与关掉表演层各读一次承载事实的通道。 */
  performance: [unknown, unknown];
  /** 关掉表演层之前时间线里在演的动作（证明表演层确实在做事）。 */
  playing: string[];
  /** 翻出来的动作条数。 */
  actions: number;
}

/** 在页面里跑一段核对：driver 经字符串化以后在页面里求值（只收一个参数）。 */
async function run(driver: (...args: never[]) => Promise<HonestyReport>, input: unknown): Promise<HonestyReport> {
  const page = await browser.newPage();
  const pageErrors: string[] = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));
  try {
    await page.route(address + "honesty.html", (route) => route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><html><head><meta charset=\"utf-8\"></head><body></body></html>",
    }));
    await page.goto(address + "honesty.html");
    const result = await page.evaluate(async (payload: { fnSource: string; input: unknown }) => {
      try {
        const fn = (0, eval)(`(${payload.fnSource})`) as (i: unknown) => Promise<HonestyReport>;
        return { ok: await fn(payload.input) };
      } catch (e) {
        return { failed: String((e as Error)?.stack ?? e) };
      }
    }, { fnSource: driver.toString(), input });
    if ("failed" in result) throw new Error(`驱动失败：${String(result.failed)}`);
    assert.deepEqual(pageErrors, [], `页面不应报错：${pageErrors.join("\n")}`);
    return result.ok as HonestyReport;
  } finally {
    await page.close();
  }
}

// 页面里的驱动：建宿主、手动时钟，按 50 毫秒一帧推进（与原型一致）

/** 楼层：翻译一份 project.loop 的结果、上画面两次、开着与关掉表演层各读一次通道。 */
async function floorHonesty(input: { query: Record<string, unknown>; events: Record<string, unknown>[] }): Promise<HonestyReport> {
  const P = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/renderer/src/pixel/floor/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/renderer/src/pixel/clock.ts");
  const T = await import(/* @vite-ignore */ "/src/translate/floor.ts" as string) as typeof import("../../src/renderer/src/translate/floor.ts");
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:9999;background:#000";
  document.body.appendChild(host);
  const clock = clockMod.createManualClock();
  const view = await P.createFloorView({ host, clock });
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  // H1：同一份查询结果两次翻译
  const first = T.floorState(input.query as never);
  const second = T.floorState(input.query as never);
  const stable = JSON.stringify(first) === JSON.stringify(second);
  // H1：同一份状态两次上画面
  view.jump(first);
  advance(250);
  const once = view.inspect().channels();
  view.jump(second);
  advance(250);
  const twice = view.inspect().channels();
  // H2：开着表演层（动作在演、待机活动在走）读一次，关掉表演层再读一次
  const actions = input.events.flatMap((ev) => T.floorActions(ev as never));
  for (const action of actions) view.play(action);
  advance(400);
  const playing = view.inspect().driver.inspectTimeline().playing.map((p) => p.kind);
  const performing = view.inspect().channels();
  view.performance(false);
  advance(300);
  const performanceOff = view.inspect().channels();
  view.destroy();
  host.remove();
  return {
    stable,
    translatedPosition: first.position,
    twice: [once, twice],
    performance: [performing, performanceOff],
    playing,
    actions: actions.length,
  };
}

/** 房间：翻译一份 department.workspace 的结果、上画面两次、开着与关掉表演层各读一次通道。 */
async function roomHonesty(input: { query: Record<string, unknown>; events: Record<string, unknown>[]; department: string }): Promise<HonestyReport> {
  const P = await import(/* @vite-ignore */ "/src/pixel/room/view.ts" as string) as typeof import("../../src/renderer/src/pixel/room/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/renderer/src/pixel/clock.ts");
  const T = await import(/* @vite-ignore */ "/src/translate/room.ts" as string) as typeof import("../../src/renderer/src/translate/room.ts");
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:9999;background:#000";
  document.body.appendChild(host);
  const clock = clockMod.createManualClock();
  const view = await P.createRoomView({ host, clock, department: input.department });
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  const first = T.state(input.query as never);
  const second = T.state(input.query as never);
  const stable = JSON.stringify(first) === JSON.stringify(second);
  view.jump(first);
  advance(250);
  const once = view.inspect().channels();
  view.jump(second);
  advance(250);
  const twice = view.inspect().channels();
  const actions = input.events.flatMap((ev) => T.actions(ev as never, input.department));
  for (const action of actions) view.play(action);
  advance(400);
  const playing = view.inspect().driver.timeline().playing.map((p) => p.kind);
  const performing = view.inspect().channels();
  view.performance(false);
  advance(300);
  const performanceOff = view.inspect().channels();
  view.destroy();
  host.remove();
  return {
    stable,
    translatedPosition: first.position,
    twice: [once, twice],
    performance: [performing, performanceOff],
    playing,
    actions: actions.length,
  };
}

/** 楼：翻译一份 projects.list 与 project.loop 的结果、上画面两次、开着与关掉表演层各读一次通道。 */
async function buildingHonesty(input: { query: Record<string, unknown>; events: Record<string, unknown>[] }): Promise<HonestyReport> {
  const P = await import(/* @vite-ignore */ "/src/pixel/building/view.ts" as string) as typeof import("../../src/renderer/src/pixel/building/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/renderer/src/pixel/clock.ts");
  const T = await import(/* @vite-ignore */ "/src/translate/building.ts" as string) as typeof import("../../src/renderer/src/translate/building.ts");
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:9999;background:#000";
  document.body.appendChild(host);
  const clock = clockMod.createManualClock();
  const view = await P.createBuildingView({ host, clock });
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  const first = T.buildingState(input.query as never);
  const second = T.buildingState(input.query as never);
  const stable = JSON.stringify(first) === JSON.stringify(second);
  view.jump(first);
  advance(250);
  const once = view.inspect().channels();
  view.jump(second);
  advance(250);
  const twice = view.inspect().channels();
  const actions = input.events.flatMap((ev) => T.buildingActions(ev as never));
  for (const action of actions) view.play(action);
  advance(400);
  const playing = view.inspect().driver.inspectTimeline().playing.map((p) => p.kind);
  const performing = view.inspect().channels();
  view.performance(false);
  advance(300);
  const performanceOff = view.inspect().channels();
  view.destroy();
  host.remove();
  return {
    stable,
    translatedPosition: first.position,
    twice: [once, twice],
    performance: [performing, performanceOff],
    playing,
    actions: actions.length,
  };
}

// ---------------------------------------------------------------------------
// 三个场景的输入：查询结果的样例（形状按接口合同，取值按画面合同的词）

const loopRow = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  work_item_id: "w1", kind: "request", sign: "测试事项", color_index: 0, status: "in_progress", department: "engineering",
  progress: null, round: 1, started_at: "2026-10-26T09:00:00+08:00", elapsed_sec: 100, time_limit_sec: 7200,
  pending_question: null, run_id: "r1", adoption_id: null, recovery_state: null, version: 1, ...over,
});

const FLOOR_QUERY = {
  position: 41,
  loop: {
    project_id: "p1",
    work_items: [
      loopRow(),
      loopRow({ work_item_id: "w2", status: "awaiting_initial_prd", department: null, run_id: "r2" }),
      loopRow({ work_item_id: "w3", status: "adopted", department: "quality", color_index: 2, run_id: "r3" }),
      loopRow({ work_item_id: "w4", status: "in_progress", recovery_state: "interrupted", department: "product", run_id: "r4" }),
    ],
    adoptions: [{ adoption_id: "a1", work_item_id: "w1", run_id: "r1" }],
  },
  asks: { r1: [{ requester: "engineering", recipient: "product", question: "线路偏好是否改变", status: "进行中" }] },
  roles: {
    engineering: [{ id: "e-mgr", name: "工程经理", kind: "manager", status: "working" }],
    quality: [{ id: "q-test", name: "测试工程师", kind: "tester", status: "working" }],
  },
};

const FLOOR_EVENTS = [
  { type: "spec_accepted", position: 51, department: "product", work_item_id: "w1", label: "产品接纳 PRD", payload: {} },
];

const ROOM_QUERY = {
  position: 42,
  workspace: {
    room: {
      department: "engineering", level: "S5", status: "working",
      crt: { target: "为待办清单增加截止日期", model: "kimi-k2.6", protocol: "Responses", status: "进行中", cycle: 2 },
      roles: [
        { id: "eng-manager", name: "工程经理", kind: "manager", status: "idle", task: null },
        { id: "eng-architect", name: "工程架构师", kind: "architect", status: "working", task: null },
        { id: "eng-lead", name: "主程", kind: "lead", status: "idle", task: null },
      ],
      pose: { role_id: "eng-architect", action: "typing" },
      door: null, hold_card: null, mailbox: 1, summaries: 2, scrolls: 1, pinned_notes: 1, semantic_cards: 0,
      machine: null, remote_unknown: false, waiting_provider: false,
      pipes: { out: "idle", letters_waiting: 1 }, existing_read: false, trial: null, tool_panel: null, self_test: null,
    },
  },
};

const ROOM_EVENTS = [
  // 工程部门的交付被接纳：工程先封存交付箱，再把箱子送进管道（两个关键动作，演得够久）
  { type: "delivery_accepted", position: 52, department: "engineering", work_item_id: "w1", label: "交付被接纳", payload: {} },
];

const BUILDING_QUERY = {
  position: 43,
  projects: [
    {
      project_id: "p1", name: "待办清单网页", goal: "记账", source: "", pinned: false, archived: false,
      created_at: "2026-10-26T09:00:00+08:00", updated_at: "2026-10-26T09:00:00+08:00", version: 1,
      work_item_count: 1, in_progress_count: 1, waiting_count: 0, decisions_waiting: 2,
      last_activity_at: "2026-10-26T09:00:00+08:00", active_work_item_id: null, current_adoption: null,
      onboarding_status: null, interrupted_count: 0, waiting_resume_count: 0,
    },
  ],
  loops: {
    p1: {
      project_id: "p1",
      work_items: [loopRow()],
      adoptions: [],
    },
  },
};

const BUILDING_EVENTS = [
  { type: "qa_submitted", position: 53, project_id: "p1", department: "quality", payload: { verdict: "release" } },
];

// ---------------------------------------------------------------------------
// 楼层

test("H1/H2 楼层：同一份查询结果两次翻译相同、同一份状态两次上画面通道相同、关掉表演层通道不变", async () => {
  const report = await run(floorHonesty as never, { query: FLOOR_QUERY, events: FLOOR_EVENTS });
  // H1：翻译是查询结果的函数
  assert.equal(report.stable, true, "同一份查询结果两次翻译得到的状态不同");
  assert.equal(report.translatedPosition, FLOOR_QUERY.position);
  // H1：同一份状态两次上画面，承载事实的通道相同
  assert.deepEqual(report.twice[1], report.twice[0]);
  // 通道不是空的：事项、房间的亮灯与角色都读到了
  const channels = report.twice[0] as {
    items: unknown[]; rooms: Record<string, { lit: boolean; flags: unknown[] }>; roles: Record<string, unknown[]>;
    tubes: { department: string; count: number }[]; shelf: { adopted: string[] };
  };
  assert.equal(channels.items.length, 4);
  assert.equal(channels.rooms.engineering.flags.length, 1, "工程门口有一面小旗（进行中的 w1）");
  assert.equal(channels.rooms.product.flags.length, 1, "产品门口有一面小旗（中断的 w4）");
  assert.equal(channels.rooms.quality.flags.length, 0, "已采纳的 w3 不再待在房间里");
  assert.ok(channels.rooms.engineering.lit, "工程有进行中的事项，房间亮灯");
  assert.equal(channels.tubes.find((t) => t.department === "product")?.count, 1, "产品管口有一封没回答的询问");
  assert.deepEqual(channels.shelf.adopted, ["w1"], "采纳记录在成果库里按事项列出");
  assert.ok(Object.keys(channels.roles).length > 0);
  // H2：动作在演的时候关掉表演层，承载事实的通道不变
  assert.ok(report.actions > 0, "样例事件没有翻出动作");
  assert.ok(report.playing.length > 0, `关掉表演层之前应有动作在演：${report.playing.join(",")}`);
  assert.deepEqual(report.performance[1], report.performance[0]);
  assert.deepEqual((report.performance[0] as { position: number }).position, FLOOR_QUERY.position);
});

// ---------------------------------------------------------------------------
// 房间

test("H1/H2 房间：同一份查询结果两次翻译相同、同一份状态两次上画面通道相同、关掉表演层通道不变", async () => {
  const report = await run(roomHonesty as never, { query: ROOM_QUERY, events: ROOM_EVENTS, department: "engineering" });
  assert.equal(report.stable, true, "同一份查询结果两次翻译得到的状态不同");
  assert.equal(report.translatedPosition, ROOM_QUERY.position);
  assert.deepEqual(report.twice[1], report.twice[0]);
  const channels = report.twice[0] as {
    status: { value: string; text: string };
    pose: { role_id: string; anim: string } | null;
    roles: { id: string; status: string }[];
    objects: { mailbox: number; letters_waiting: number };
  };
  assert.deepEqual(channels.status, { value: "working", text: "工作中" });
  assert.deepEqual(channels.pose, { role_id: "eng-architect", anim: "type" });
  assert.deepEqual(channels.roles.map((r) => r.id), ["eng-architect", "eng-lead", "eng-manager"]);
  assert.equal(channels.objects.mailbox, 1);
  assert.equal(channels.objects.letters_waiting, 1);
  assert.ok(report.actions > 0, "样例事件没有翻出动作");
  assert.ok(report.playing.length > 0, `关掉表演层之前应有动作在演：${report.playing.join(",")}`);
  assert.deepEqual(report.performance[1], report.performance[0]);
  assert.deepEqual((report.performance[0] as { position: number }).position, ROOM_QUERY.position);
});

// ---------------------------------------------------------------------------
// 楼

test("H1/H2 楼：同一份查询结果两次翻译相同、同一份状态两次上画面通道相同、关掉表演层通道不变", async () => {
  const report = await run(buildingHonesty as never, { query: BUILDING_QUERY, events: BUILDING_EVENTS });
  assert.equal(report.stable, true, "同一份查询结果两次翻译得到的状态不同");
  assert.equal(report.translatedPosition, BUILDING_QUERY.position);
  assert.deepEqual(report.twice[1], report.twice[0]);
  const channels = report.twice[0] as {
    floors: { project_id: string; status: string; lit: Record<string, boolean>; decisions: number; flags: { work_item_id: string }[] }[];
  };
  assert.equal(channels.floors.length, 1);
  assert.equal(channels.floors[0].project_id, "p1");
  assert.equal(channels.floors[0].status, "working", "进行中的事项让这一层显示工作中");
  assert.equal(channels.floors[0].lit.engineering, true);
  assert.equal(channels.floors[0].decisions, 2);
  assert.deepEqual(channels.floors[0].flags.map((f) => f.work_item_id), ["w1"]);
  assert.ok(report.actions > 0, "样例事件没有翻出动作");
  assert.deepEqual(report.performance[1], report.performance[0]);
  assert.deepEqual((report.performance[0] as { position: number }).position, BUILDING_QUERY.position);
});
