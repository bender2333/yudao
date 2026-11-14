// H1、H2、H5 与 H6 的单元测试（画面与播放 docs/design/visualization.md「画面诚实性的不变式」、docs/design/visualization.md「视觉通道表」；工单 #959、#1383、#1385）。
// 守 docs/design/test-pyramid.md「测试按三环留」的 R2（承载事实的视觉通道与楼层拓扑合同）与 R3（画面跟着事项冻结定义伸缩、开环完成不画成放行、空事件零轨迹元素）。
//
// H1 事实层是事件的函数：同一份查询结果两次翻译得到的状态相同；同一份状态两次上画面，承载事实的通道相同。
// H2 表演层不占用承载事实的视觉通道：同一份状态上画面以后，开着表演层（待机活动与动作）与关掉它各读一次
//    承载事实的通道，两次相同。
// H5 开环完成不画成放行：以开环完成结束的事项，在楼、楼层、房间任何场景的事实通道里都没有实心放行章，
//    只有虚线的开环完成章；放行结束的事项只有实心放行章，没有虚线章。
// H6 固定画出的只有边界、裁决点与权威关系：事件为空时轨迹元素的数量为 0；房间的集合等于楼层上事项冻结的定义里
//    角色的并集，连线的集合等于这些定义中的关注、询问与打回关系，盖章台只出现在核验角色的屋里。
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
import { SCENES, type Scene } from "../../src/translate/coverage.ts";
import { VISUAL_CHANNELS, verifyMapping, visualChannelsOf } from "../../src/translate/mapping.ts";

const here = dirname(fileURLToPath(import.meta.url));
const viewRoot = resolve(here, "..", "..");

let server: ViteDevServer;
let browser: Browser;
let address = "";

before(async () => {
  server = await createServer({
    // 模块服务器以画面的包根为根：测试页用 /src/… 的路径导入画面自己的模块
    root: viewRoot,
    // 单元测试文件之间并行运行：缓存目录与别的浏览器测试分开，避免两个服务器同时改写同一份缓存
    cacheDir: join(viewRoot, "node_modules", ".vite-pixel-honesty"),
    plugins: [],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
  });
  try {
    await server.listen();
    const url = server.resolvedUrls?.local[0];
    if (!url) throw new Error("渲染进程的模块服务器没有给出地址");
    address = url;
    browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
  } catch (error) {
    await browser?.close();
    await server?.close();
    throw error;
  }
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
async function run<R = HonestyReport>(driver: (...args: never[]) => Promise<R>, input: unknown): Promise<R> {
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
        const fn = (0, eval)(`(${payload.fnSource})`) as (i: unknown) => Promise<unknown>;
        return { ok: await fn(payload.input) };
      } catch (e) {
        return { failed: String((e as Error)?.stack ?? e) };
      }
    }, { fnSource: driver.toString(), input });
    if ("failed" in result) throw new Error(`驱动失败：${String(result.failed)}`);
    assert.deepEqual(pageErrors, [], `页面不应报错：${pageErrors.join("\n")}`);
    return result.ok as R;
  } finally {
    await page.close();
  }
}

// 页面里的驱动：建宿主、手动时钟，按 50 毫秒一帧推进（与原型一致）

/** 楼层：翻译一份 project.loop 的结果、上画面两次、开着与关掉表演层各读一次通道。 */
async function floorHonesty(input: { query: Record<string, unknown>; events: Record<string, unknown>[] }): Promise<HonestyReport> {
  const P = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/pixel/floor/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");
  const T = await import(/* @vite-ignore */ "/src/translate/floor.ts" as string) as typeof import("../../src/translate/floor.ts");
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
  const P = await import(/* @vite-ignore */ "/src/pixel/room/view.ts" as string) as typeof import("../../src/pixel/room/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");
  const T = await import(/* @vite-ignore */ "/src/translate/room.ts" as string) as typeof import("../../src/translate/room.ts");
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
  const P = await import(/* @vite-ignore */ "/src/pixel/building/view.ts" as string) as typeof import("../../src/pixel/building/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");
  const T = await import(/* @vite-ignore */ "/src/translate/building.ts" as string) as typeof import("../../src/translate/building.ts");
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

/** 按翻译层导出的视觉通道清单逐项核对承载事实的通道：清单里每个通道都能从场景的 channels() 读出且前后取值一致。 */
function assertFactChannelsUnchanged(
  scene: Scene,
  firstRead: Record<string, unknown>,
  secondRead: Record<string, unknown>,
  stage: string,
): void {
  const declared = visualChannelsOf(scene, VISUAL_CHANNELS);
  assert.ok(declared.length > 0, `${scene} 场景在视觉通道清单里缺少登记`);
  for (const channel of declared) {
    assert.ok(
      Object.prototype.hasOwnProperty.call(firstRead, channel.key),
      `${stage}：${scene} 的 channels() 缺少视觉通道 ${channel.id} 对应的字段 ${channel.key}`,
    );
    assert.ok(
      Object.prototype.hasOwnProperty.call(secondRead, channel.key),
      `${stage}：${scene} 的 channels() 缺少视觉通道 ${channel.id} 对应的字段 ${channel.key}`,
    );
    const beforeValue = channel.read(firstRead);
    const afterValue = channel.read(secondRead);
    assert.notEqual(beforeValue, undefined, `${stage}：视觉通道 ${channel.id}（${channel.label}）读数为 undefined`);
    assert.deepEqual(afterValue, beforeValue, `${stage}：视觉通道 ${channel.id}（${channel.label}）前后不一致`);
  }
  assert.deepEqual(secondRead, firstRead, `${stage}：${scene} 的承载事实通道整体不一致`);
}

test("H2 视觉通道清单：三个场景承载事实的通道均在翻译层导出并在对照表里有对应行", () => {
  verifyMapping();
  for (const scene of SCENES) {
    assert.ok(visualChannelsOf(scene, VISUAL_CHANNELS).length > 0, `${scene} 场景没有登记承载事实的视觉通道`);
  }
});

// ---------------------------------------------------------------------------
// 楼层

test("H1/H2 楼层：同一份查询结果两次翻译相同、同一份状态两次上画面通道相同、关掉表演层通道不变", async () => {
  const report = await run(floorHonesty as never, { query: FLOOR_QUERY, events: FLOOR_EVENTS });
  // H1：翻译是查询结果的函数
  assert.equal(report.stable, true, "同一份查询结果两次翻译得到的状态不同");
  assert.equal(report.translatedPosition, FLOOR_QUERY.position);
  // H1：同一份状态两次上画面，按导出的视觉通道清单逐项核对一致
  assertFactChannelsUnchanged(
    "floor",
    report.twice[0] as Record<string, unknown>,
    report.twice[1] as Record<string, unknown>,
    "H1 楼层",
  );
  // 通道不是空的：事项、房间的亮灯与角色都读到了
  const channels = report.twice[0] as {
    items: unknown[]; rooms: Record<string, { lit: boolean; flags: unknown[] }>; roles: Record<string, unknown[]>;
    tubes: { department: string; count: number }[]; shelf: { adopted: string[] };
  };
  assert.equal(channels.items.length, 4);
  assert.equal(channels.rooms.engineering.flags.length, 1, "工程门口有一面小旗（进行中的 w1）");
  assert.equal(channels.rooms.product.flags.length, 1, "产品门口有一面小旗（中断的 w4）");
  assert.equal(channels.rooms.quality.flags.length, 0, "已采纳的 w3 不停在房间里");
  assert.ok(channels.rooms.engineering.lit, "工程有进行中的事项，房间亮灯");
  assert.equal(channels.tubes.find((t) => t.department === "product")?.count, 1, "产品管口有一封没回答的询问");
  assert.deepEqual(channels.shelf.adopted, ["w1"], "采纳记录在成果库里按事项列出");
  assert.ok(Object.keys(channels.roles).length > 0);
  // H2：动作在演的时候关掉表演层，按导出的视觉通道清单逐项核对不变
  assert.ok(report.actions > 0, "样例事件没有翻出动作");
  assert.ok(report.playing.length > 0, `关掉表演层之前应有动作在演：${report.playing.join(",")}`);
  assertFactChannelsUnchanged(
    "floor",
    report.performance[0] as Record<string, unknown>,
    report.performance[1] as Record<string, unknown>,
    "H2 楼层",
  );
  assert.deepEqual((report.performance[0] as { position: number }).position, FLOOR_QUERY.position);
});

// ---------------------------------------------------------------------------
// 房间

test("H1/H2 房间：同一份查询结果两次翻译相同、同一份状态两次上画面通道相同、关掉表演层通道不变", async () => {
  const report = await run(roomHonesty as never, { query: ROOM_QUERY, events: ROOM_EVENTS, department: "engineering" });
  assert.equal(report.stable, true, "同一份查询结果两次翻译得到的状态不同");
  assert.equal(report.translatedPosition, ROOM_QUERY.position);
  assertFactChannelsUnchanged(
    "room",
    report.twice[0] as Record<string, unknown>,
    report.twice[1] as Record<string, unknown>,
    "H1 房间",
  );
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
  assertFactChannelsUnchanged(
    "room",
    report.performance[0] as Record<string, unknown>,
    report.performance[1] as Record<string, unknown>,
    "H2 房间",
  );
  assert.deepEqual((report.performance[0] as { position: number }).position, ROOM_QUERY.position);
});

// ---------------------------------------------------------------------------
// 楼

test("H1/H2 楼：同一份查询结果两次翻译相同、同一份状态两次上画面通道相同、关掉表演层通道不变", async () => {
  const report = await run(buildingHonesty as never, { query: BUILDING_QUERY, events: BUILDING_EVENTS });
  assert.equal(report.stable, true, "同一份查询结果两次翻译得到的状态不同");
  assert.equal(report.translatedPosition, BUILDING_QUERY.position);
  assertFactChannelsUnchanged(
    "building",
    report.twice[0] as Record<string, unknown>,
    report.twice[1] as Record<string, unknown>,
    "H1 楼",
  );
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
  assertFactChannelsUnchanged(
    "building",
    report.performance[0] as Record<string, unknown>,
    report.performance[1] as Record<string, unknown>,
    "H2 楼",
  );
  assert.deepEqual((report.performance[0] as { position: number }).position, BUILDING_QUERY.position);
});

// ---------------------------------------------------------------------------
// H6：固定画出的只有边界、裁决点与权威关系（工单 #1383）

interface FloorH6Readout {
  roomOrder: string[];
  deptBounds: Record<string, { x: number; w: number; verifier: boolean; exitTray: boolean }>;
  channels: {
    items: unknown[];
    rooms: Record<string, { label: string; verifier: boolean; exit_tray: boolean }>;
    links: { handoffs: string[]; tubes: string[]; returns: string[] };
    board: unknown[];
    shelf: { adopted: string[]; shown: string[] };
    tubes: { department: string; count: number }[];
  };
  stamps: { work_item_id: string; x: number; w: number; drawn: boolean }[];
  trajectories: {
    packages: number;
    flyers: number;
    arrows: number;
    remoteDots: number;
    playing: number;
  };
}

/** 浏览器内驱动：装载一份楼层查询快照并读取房间集合、权威连接、盖章台与轨迹元素读数。 */
async function floorH6Driver(input: { query: Record<string, unknown> }): Promise<FloorH6Readout> {
  const P = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/pixel/floor/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");
  const T = await import(/* @vite-ignore */ "/src/translate/floor.ts" as string) as typeof import("../../src/translate/floor.ts");
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:9999;background:#000";
  document.body.appendChild(host);
  const clock = clockMod.createManualClock();
  const view = await P.createFloorView({ host, clock });
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  try {
    const state = T.floorState(input.query as never);
    view.jump(state);
    advance(400);
    const inspected = view.inspect();
    const world = inspected.driver.world;
    const deptBounds: FloorH6Readout["deptBounds"] = {};
    for (const id of world.roomOrder) {
      const r = world.rooms[id];
      if (!r || r.roomKind !== "dept") continue;
      deptBounds[id] = {
        x: r.x,
        w: r.w,
        verifier: Boolean(r.def.verifier),
        exitTray: Boolean(r.def.exitTray),
      };
    }
    const stamps = view.factRects()
      .filter((rect) => rect.element === "stamp")
      .map((rect) => ({ work_item_id: rect.work_item_id, x: rect.x, w: rect.w, drawn: rect.drawn }));
    return {
      roomOrder: world.roomOrder.slice(),
      deptBounds,
      channels: inspected.channels() as unknown as FloorH6Readout["channels"],
      stamps,
      trajectories: {
        packages: Object.keys(world.packages).length,
        flyers: inspected.state.flyers.length,
        arrows: inspected.state.arrows.length,
        remoteDots: inspected.state.remoteDots.length,
        playing: inspected.driver.inspectTimeline().playing.length,
      },
    };
  } finally {
    view.destroy();
    host.remove();
  }
}

const REF_POS3 = { position: 3, source: "user" } as const;

// 守 R2 与 R3：房间集合等于楼层上事项冻结定义里角色的并集，连线集合等于定义关系，盖章台只在核验角色屋里。
test("H6 楼层拓扑与盖章台：房间集合等于事项定义角色并集，管道传信管与回流管等于定义关系，盖章台只在核验角色屋里", async () => {
  // 同一楼层并存两件冻结了不同定义的事项：旧事项用 alpha → beta（开环完成），新事项用 beta → gamma（gamma 为核验角色）
  const unionQuery = {
    position: 90,
    loop: {
      project_id: "p_union",
      work_items: [
        loopRow({
          work_item_id: "w_old",
          status: "in_progress",
          department: "alpha",
          run_id: "r_old",
          organization: {
            form: "two_roles_open",
            routing: "watched_outputs",
            entry: { id: "alpha", label: "草案", ref: REF_POS3 },
            roles: [
              { id: "alpha", label: "草案", ref: REF_POS3 },
              { id: "beta", label: "编排", ref: REF_POS3 },
            ],
            verifiers: [],
            completing: { id: "beta", label: "编排", ref: REF_POS3 },
            watched: [{ source: "alpha", recipient: "beta", outcome: "draft_doc", ref: REF_POS3 }],
            asks: [{ requester: "beta", recipient: "alpha", ref: REF_POS3 }],
            rejections: [],
          },
        }),
        loopRow({
          work_item_id: "w_new",
          status: "released_unsettled",
          department: "gamma",
          run_id: "r_new",
          refs: { stamp: { position: 88, source: "role_statement" } },
          organization: {
            form: "two_roles_verified",
            routing: "watched_outputs",
            entry: { id: "beta", label: "编排", ref: REF_POS3 },
            roles: [
              { id: "beta", label: "编排", ref: REF_POS3 },
              { id: "gamma", label: "把关", ref: REF_POS3 },
            ],
            verifiers: [
              {
                role: "gamma",
                verifies: [{ role: "beta", outcomes: ["bundle_spec"] }],
                ref: REF_POS3,
              },
            ],
            completing: null,
            watched: [{ source: "beta", recipient: "gamma", outcome: "bundle_spec", ref: REF_POS3 }],
            asks: [{ requester: "gamma", recipient: "beta", ref: REF_POS3 }],
            rejections: [{ verifier: "gamma", role: "beta", outcome: "bundle_spec", ref: REF_POS3 }],
          },
        }),
      ],
      adoptions: [],
    },
    asks: {},
    decisions: [],
    roles: {},
  };

  const unionRead = await run<FloorH6Readout>(floorH6Driver as never, { query: unionQuery });
  assert.deepEqual(unionRead.roomOrder, ["hall", "alpha", "beta", "gamma", "library"]);
  assert.deepEqual(Object.keys(unionRead.channels.rooms), ["alpha", "beta", "gamma"]);
  assert.equal(unionRead.channels.rooms.alpha.label, "草案");
  assert.equal(unionRead.channels.rooms.beta.label, "编排");
  assert.equal(unionRead.channels.rooms.gamma.label, "把关");
  assert.deepEqual(unionRead.channels.links, {
    handoffs: ["alpha>beta", "beta>gamma", "beta>library", "gamma>library", "hall>alpha", "hall>beta"],
    tubes: ["alpha~beta", "beta~gamma"],
    returns: ["gamma>beta"],
  });
  // 盖章台只出现在核验角色 gamma 的屋里，开环完成角色 beta 只有出口托盘没有盖章台
  assert.equal(unionRead.channels.rooms.alpha.verifier, false);
  assert.equal(unionRead.channels.rooms.beta.verifier, false);
  assert.equal(unionRead.channels.rooms.gamma.verifier, true);
  assert.equal(unionRead.channels.rooms.alpha.exit_tray, false);
  assert.equal(unionRead.channels.rooms.beta.exit_tray, true);
  assert.equal(unionRead.channels.rooms.gamma.exit_tray, false);
  assert.equal(unionRead.stamps.length, 1);
  const stampCenter = unionRead.stamps[0].x + unionRead.stamps[0].w / 2;
  const gammaBox = unionRead.deptBounds.gamma;
  assert.ok(stampCenter >= gammaBox.x && stampCenter <= gammaBox.x + gammaBox.w, "放行章必须画在核验角色 gamma 房间内");

  // 无核验角色的开环完成楼层：任何房间都没有盖章台，画布上零枚放行章
  const openLoopQuery = {
    position: 12,
    loop: {
      project_id: "p_open",
      work_items: [
        loopRow({
          work_item_id: "w_open",
          status: "released_unsettled",
          department: "finish_role",
          run_id: "r_open",
          organization: {
            form: "open_only",
            routing: "watched_outputs",
            entry: { id: "draft_role", label: "起草", ref: REF_POS3 },
            roles: [
              { id: "draft_role", label: "起草", ref: REF_POS3 },
              { id: "finish_role", label: "收口", ref: REF_POS3 },
            ],
            verifiers: [],
            completing: { id: "finish_role", label: "收口", ref: REF_POS3 },
            watched: [{ source: "draft_role", recipient: "finish_role", outcome: "draft_doc", ref: REF_POS3 }],
            asks: [],
            rejections: [],
          },
        }),
      ],
      adoptions: [],
    },
    asks: {},
    decisions: [],
    roles: {},
  };
  const openRead = await run<FloorH6Readout>(floorH6Driver as never, { query: openLoopQuery });
  assert.deepEqual(openRead.roomOrder, ["hall", "draft_role", "finish_role", "library"]);
  assert.deepEqual(openRead.channels.links, {
    handoffs: ["draft_role>finish_role", "finish_role>library", "hall>draft_role"],
    tubes: [],
    returns: [],
  });
  assert.equal(openRead.channels.rooms.draft_role.verifier, false);
  assert.equal(openRead.channels.rooms.finish_role.verifier, false);
  assert.equal(openRead.channels.rooms.finish_role.exit_tray, true);
  assert.equal(openRead.stamps.length, 0, "无核验角色的楼层不设盖章台，也不画放行章");
});

// 守 R2 与 R3：事件为空时轨迹元素数量为 0；楼层无事项时固定画出的只有大厅与成果库边界。
test("H6 空事件与空楼层：事件为空时轨迹元素数量为 0，无事项时只画大厅与成果库边界", async () => {
  const emptyFloorQuery = {
    position: 0,
    loop: { project_id: "p_empty", work_items: [], adoptions: [] },
    asks: {},
    decisions: [],
    roles: {},
  };
  const emptyRead = await run<FloorH6Readout>(floorH6Driver as never, { query: emptyFloorQuery });
  assert.deepEqual(emptyRead.roomOrder, ["hall", "library"]);
  assert.deepEqual(emptyRead.channels.rooms, {});
  assert.deepEqual(emptyRead.channels.links, { handoffs: [], tubes: [], returns: [] });
  assert.equal(emptyRead.channels.items.length, 0);
  assert.equal(emptyRead.channels.board.length, 0);
  assert.equal(emptyRead.channels.shelf.adopted.length, 0);
  assert.deepEqual(emptyRead.trajectories, {
    packages: 0,
    flyers: 0,
    arrows: 0,
    remoteDots: 0,
    playing: 0,
  });

  // 有冻结定义但尚无流转事件的初始静止状态：房间与权威管道按定义画出，轨迹与在途元素全部为 0
  const idleDefinedQuery = {
    position: 1,
    loop: {
      project_id: "p_idle",
      work_items: [
        loopRow({
          work_item_id: "w_idle",
          status: "awaiting_initial_prd",
          department: null,
          run_id: "r_idle",
          organization: {
            form: "two_roles_verified",
            routing: "watched_outputs",
            entry: { id: "spec_role", label: "规格", ref: REF_POS3 },
            roles: [
              { id: "spec_role", label: "规格", ref: REF_POS3 },
              { id: "check_role", label: "核验", ref: REF_POS3 },
            ],
            verifiers: [
              {
                role: "check_role",
                verifies: [{ role: "spec_role", outcomes: ["product_spec"] }],
                ref: REF_POS3,
              },
            ],
            completing: null,
            watched: [{ source: "spec_role", recipient: "check_role", outcome: "product_spec", ref: REF_POS3 }],
            asks: [{ requester: "check_role", recipient: "spec_role", ref: REF_POS3 }],
            rejections: [{ verifier: "check_role", role: "spec_role", outcome: "product_spec", ref: REF_POS3 }],
          },
        }),
      ],
      adoptions: [],
    },
    asks: {},
    decisions: [],
    roles: {},
  };
  const idleRead = await run<FloorH6Readout>(floorH6Driver as never, { query: idleDefinedQuery });
  assert.deepEqual(idleRead.roomOrder, ["hall", "spec_role", "check_role", "library"]);
  assert.deepEqual(idleRead.trajectories, {
    packages: 0,
    flyers: 0,
    arrows: 0,
    remoteDots: 0,
    playing: 0,
  });
  assert.equal(idleRead.channels.board.length, 0);
  assert.equal(idleRead.channels.shelf.adopted.length, 0);
  assert.ok(idleRead.channels.tubes.every((t) => t.count === 0));
});

// ---------------------------------------------------------------------------
// H5：开环完成不画成放行（工单 #1385，docs/design/visualization.md「画面诚实性的不变式」 H5）

interface H5StampReadout {
  buildingStamps: { work_item_id: string; kind: string; outsourced?: boolean }[];
  floorStamps: { work_item_id: string; room: string; kind: string; outsourced: boolean; text: string }[];
  shelfBoxes: { work_item_id: string; stamp_kind: string; outsourced?: boolean }[];
  roomStamp: { kind: string; outsourced: boolean; text: string } | null;
  floorTexts: string[];
  roomTexts: string[];
}

async function h5StampHonestyDriver(input: {
  buildingQuery: Record<string, unknown>;
  floorQuery: Record<string, unknown>;
  roomQuery: Record<string, unknown>;
  department: string;
}): Promise<H5StampReadout> {
  const BuildingMod = await import(/* @vite-ignore */ "/src/pixel/building/view.ts" as string) as typeof import("../../src/pixel/building/view.ts");
  const FloorMod = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/pixel/floor/view.ts");
  const RoomMod = await import(/* @vite-ignore */ "/src/pixel/room/view.ts" as string) as typeof import("../../src/pixel/room/view.ts");
  const ClockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");
  const TB = await import(/* @vite-ignore */ "/src/translate/building.ts" as string) as typeof import("../../src/translate/building.ts");
  const TF = await import(/* @vite-ignore */ "/src/translate/floor.ts" as string) as typeof import("../../src/translate/floor.ts");
  const TR = await import(/* @vite-ignore */ "/src/translate/room.ts" as string) as typeof import("../../src/translate/room.ts");

  const captured: string[] = [];
  const origFillText = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (text: string, x: number, y: number, maxWidth?: number): void {
    captured.push(String(text));
    if (maxWidth !== undefined) origFillText.call(this, text, x, y, maxWidth);
    else origFillText.call(this, text, x, y);
  };

  const makeHost = (top: number): HTMLDivElement => {
    const el = document.createElement("div");
    el.style.cssText = `position:fixed;left:0;top:${top}px;width:640px;height:320px`;
    document.body.appendChild(el);
    return el;
  };
  const hostB = makeHost(0);
  const hostF = makeHost(330);
  const hostR = makeHost(660);
  const clock = ClockMod.createManualClock();
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };

  let bView: Awaited<ReturnType<typeof BuildingMod.createBuildingView>> | null = null;
  let fView: Awaited<ReturnType<typeof FloorMod.createFloorView>> | null = null;
  let rView: Awaited<ReturnType<typeof RoomMod.createRoomView>> | null = null;
  try {
    bView = await BuildingMod.createBuildingView({ host: hostB, clock });
    fView = await FloorMod.createFloorView({ host: hostF, clock });
    rView = await RoomMod.createRoomView({ host: hostR, clock, department: input.department });

    bView.jump(TB.buildingState(input.buildingQuery as never));
    advance(150);

    captured.length = 0;
    fView.jump(TF.floorState(input.floorQuery as never));
    advance(200);
    const floorTexts = captured.slice();

    captured.length = 0;
    rView.jump(TR.state(input.roomQuery as never));
    advance(200);
    const roomTexts = captured.slice();

    const bChannels = bView.inspect().channels();
    const fChannels = fView.inspect().channels();
    const rChannels = rView.inspect().channels();
    return {
      buildingStamps: (bChannels.floors[0]?.stamps ?? []) as H5StampReadout["buildingStamps"],
      floorStamps: fChannels.stamps as H5StampReadout["floorStamps"],
      shelfBoxes: (fChannels.shelf.boxes ?? []) as H5StampReadout["shelfBoxes"],
      roomStamp: rChannels.stamp as H5StampReadout["roomStamp"],
      floorTexts,
      roomTexts,
    };
  } finally {
    CanvasRenderingContext2D.prototype.fillText = origFillText;
    bView?.destroy();
    fView?.destroy();
    rView?.destroy();
    hostB.remove();
    hostF.remove();
    hostR.remove();
  }
}

// 守 R2 与 R3：以开环完成结束的事项（含外包核验分支），在楼、楼层、房间任何场景的事实通道里都没有实心放行章，只有虚线的开环完成章；放行结束的事项只有实心放行章。
test("H5 开环完成不画成放行：三个场景的事实通道与成果库箱子严格区分虚线开环完成章与实心放行章", async () => {
  const soloOrg = {
    form: "solo_engineering",
    routing: "watched_outputs",
    entry: { id: "engineering", label: "工程", ref: REF_POS3 },
    roles: [{ id: "engineering", label: "工程", ref: REF_POS3 }],
    verifiers: [],
    completing: { id: "engineering", label: "工程", ref: REF_POS3 },
    watched: [],
    asks: [],
    rejections: [],
  };
  const openLoopData = {
    project_id: "p_h5_open",
    work_items: [
      loopRow({
        work_item_id: "w_open_plain",
        sign: "直做事项甲",
        status: "adopted",
        stop_reason: "open_loop",
        department: null,
        organization: soloOrg,
        refs: { sign: REF_POS3, stamp: { position: 18, source: "role_statement" }, box: { position: 19, source: "rule" } },
      }),
      loopRow({
        work_item_id: "w_open_ext",
        sign: "外包事项乙",
        status: "adopted",
        stop_reason: "open_loop",
        outsourced: true,
        department: null,
        organization: soloOrg,
        refs: { sign: REF_POS3, stamp: { position: 28, source: "role_statement" }, box: { position: 29, source: "rule" } },
      }),
    ],
    adoptions: [
      { adoption_id: "ad_1", work_item_id: "w_open_plain", run_id: "r1" },
      { adoption_id: "ad_2", work_item_id: "w_open_ext", run_id: "r2" },
    ],
  };

  const makeRoomWorkspace = (dept: string) => ({
    room: {
      department: dept,
      level: "S5",
      status: "done",
      crt: { target: "完成", model: "m", protocol: "Responses", status: "已完成", cycle: 1 },
      roles: [{ id: `${dept}-lead`, name: "主责人", kind: "lead", status: "idle", task: null }],
      pose: { role_id: `${dept}-lead`, action: "idle" },
      door: null,
      hold_card: null,
      mailbox: 0,
      summaries: 0,
      scrolls: 0,
      pinned_notes: 0,
      semantic_cards: 0,
      machine: null,
      remote_unknown: false,
      waiting_provider: false,
      pipes: { out: "idle", letters_waiting: 0 },
      existing_read: false,
      trial: null,
      tool_panel: null,
      self_test: null,
    },
  });

  const openReadPlain = await run<H5StampReadout>(h5StampHonestyDriver as never, {
    buildingQuery: {
      position: 30,
      projects: [{ project_id: "p_h5_open", name: "直做项目", goal: "开环", pinned: false, archived: false, last_activity_at: "2026-11-14T10:00:00+08:00", decisions_waiting: 0 }],
      loops: { p_h5_open: openLoopData },
    },
    floorQuery: { position: 30, loop: openLoopData, asks: {}, roles: {} },
    roomQuery: { position: 30, workspace: makeRoomWorkspace("engineering"), department: "engineering", loop: openLoopData, workItemId: "w_open_plain" },
    department: "engineering",
  });

  // 1. 开环完成：楼、楼层、房间与成果库箱子均无任何 release 实心放行章，只有 open_loop 虚线章
  assert.deepEqual(openReadPlain.buildingStamps, [
    { work_item_id: "w_open_plain", kind: "open_loop", outsourced: false },
    { work_item_id: "w_open_ext", kind: "open_loop", outsourced: true },
  ]);
  assert.equal(openReadPlain.buildingStamps.some((s) => s.kind === "release"), false);
  assert.deepEqual(openReadPlain.floorStamps, [
    { work_item_id: "w_open_plain", room: "engineering", kind: "open_loop", outsourced: false, text: "开环完成" },
    { work_item_id: "w_open_ext", room: "engineering", kind: "open_loop", outsourced: true, text: "开环完成 · 外包" },
  ]);
  assert.equal(openReadPlain.floorStamps.some((s) => s.kind === "release"), false);
  assert.deepEqual(openReadPlain.shelfBoxes, [
    { work_item_id: "w_open_plain", stamp_kind: "open_loop", outsourced: false },
    { work_item_id: "w_open_ext", stamp_kind: "open_loop", outsourced: true },
  ]);
  assert.deepEqual(openReadPlain.roomStamp, { kind: "open_loop", outsourced: false, text: "开环完成" });
  assert.ok(openReadPlain.floorTexts.includes("开环完成"), `楼层未绘制「开环完成」：${openReadPlain.floorTexts.join(" | ")}`);
  assert.ok(openReadPlain.floorTexts.includes("开环完成 · 外包"), `楼层未绘制「开环完成 · 外包」：${openReadPlain.floorTexts.join(" | ")}`);
  assert.equal(openReadPlain.floorTexts.includes("放行"), false, "开环完成楼层禁止绘制「放行」");
  assert.ok(openReadPlain.roomTexts.includes("出口托盘"), `直做房间未绘制「出口托盘」：${openReadPlain.roomTexts.join(" | ")}`);
  assert.ok(openReadPlain.roomTexts.includes("开环完成"), `直做房间未绘制「开环完成」：${openReadPlain.roomTexts.join(" | ")}`);
  assert.equal(openReadPlain.roomTexts.includes("放行"), false, "开环完成房间禁止绘制「放行」");

  // 外包事项在房间场景下也给出「开环完成 · 外包」虚线章
  const openReadExtRoom = await run<H5StampReadout>(h5StampHonestyDriver as never, {
    buildingQuery: {
      position: 30,
      projects: [{ project_id: "p_h5_open", name: "直做项目", goal: "开环", pinned: false, archived: false, last_activity_at: "2026-11-14T10:00:00+08:00", decisions_waiting: 0 }],
      loops: { p_h5_open: openLoopData },
    },
    floorQuery: { position: 30, loop: openLoopData, asks: {}, roles: {} },
    roomQuery: { position: 30, workspace: makeRoomWorkspace("engineering"), department: "engineering", loop: openLoopData, workItemId: "w_open_ext" },
    department: "engineering",
  });
  assert.deepEqual(openReadExtRoom.roomStamp, { kind: "open_loop", outsourced: true, text: "开环完成 · 外包" });
  assert.ok(openReadExtRoom.roomTexts.includes("开环完成 · 外包"));

  // 2. 独立核验角色放行结束：三个场景与成果库箱子只有 release 实心放行章，没有 open_loop 虚线章
  const verifiedOrg = {
    form: "direct_verified",
    routing: "watched_outputs",
    entry: { id: "engineering", label: "工程", ref: REF_POS3 },
    roles: [
      { id: "engineering", label: "工程", ref: REF_POS3 },
      { id: "quality", label: "质检", ref: REF_POS3 },
    ],
    verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["completion"] }], ref: REF_POS3 }],
    completing: null,
    watched: [{ source: "engineering", recipient: "quality", outcome: "completion", ref: REF_POS3 }],
    asks: [],
    rejections: [{ verifier: "quality", role: "engineering", outcome: "completion", ref: REF_POS3 }],
  };
  const releasedLoopData = {
    project_id: "p_h5_rel",
    work_items: [
      loopRow({
        work_item_id: "w_rel",
        sign: "经核验放行事项",
        status: "adopted",
        stop_reason: null,
        department: null,
        organization: verifiedOrg,
        refs: { sign: REF_POS3, stamp: { position: 38, source: "role_statement" }, box: { position: 39, source: "rule" } },
      }),
    ],
    adoptions: [{ adoption_id: "ad_rel", work_item_id: "w_rel", run_id: "r_rel" }],
  };
  const relRead = await run<H5StampReadout>(h5StampHonestyDriver as never, {
    buildingQuery: {
      position: 40,
      projects: [{ project_id: "p_h5_rel", name: "核验项目", goal: "放行", pinned: false, archived: false, last_activity_at: "2026-11-14T10:05:00+08:00", decisions_waiting: 0 }],
      loops: { p_h5_rel: releasedLoopData },
    },
    floorQuery: { position: 40, loop: releasedLoopData, asks: {}, roles: {} },
    roomQuery: { position: 40, workspace: makeRoomWorkspace("quality"), department: "quality", loop: releasedLoopData, workItemId: "w_rel" },
    department: "quality",
  });
  assert.deepEqual(relRead.buildingStamps, [{ work_item_id: "w_rel", kind: "release", outsourced: false }]);
  assert.deepEqual(relRead.floorStamps, [{ work_item_id: "w_rel", room: "quality", kind: "release", outsourced: false, text: "放行" }]);
  assert.deepEqual(relRead.shelfBoxes, [{ work_item_id: "w_rel", stamp_kind: "release", outsourced: false }]);
  assert.deepEqual(relRead.roomStamp, { kind: "release", outsourced: false, text: "放行" });
  assert.equal(relRead.floorTexts.some((t) => t.includes("开环完成")), false, "独立核验放行楼层禁止绘制「开环完成」");
  assert.ok(relRead.floorTexts.includes("放行"));
  assert.ok(relRead.roomTexts.includes("放行"));
});
