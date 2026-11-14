// 房间与连接从事项定义推出的单元测试（画面与播放 docs/design/visualization.md「画面跟着定义伸缩」「画面合同」「视觉通道表」，工单 #1383）。
//
// 守 docs/design/test-pyramid.md「测试按三环留」的 R2（画面合同的楼层拓扑与楼亮灯格子、画面层只认声明与角色标识不认职能名）
// 与 R3（默认三职能与三职能全部改名跑同一段录制时事实通道一致、放行章与检验覆盖牌随核验角色房间定位、信息条绘制「所在职能：…」）。

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { createServer, type ViteDevServer } from "vite";
import { chromium, type Browser } from "@playwright/test";

import { floorActions, floorState } from "../../src/translate/floor.ts";
import { buildingActions, buildingState } from "../../src/translate/building.ts";
import { actions as roomActions, state as translateRoomState } from "../../src/translate/room.ts";
import { hasDeclaredFloorAppearance } from "../../src/pixel/world/floor-decl.ts";
import { hasDeclaredRoomVisual } from "../../src/pixel/floor/render-decl.ts";
import { hasDeclaredRoomAppearance } from "../../src/pixel/room/decl.ts";
import type { CoverageOverlayData } from "../../src/pixel/contract.ts";
import {
  FakeServer,
  fakeClock,
  fakeHost,
  fakeSurface,
  loadEvents,
  loadFixtures,
  recordingOf,
  responseOf,
  settle,
  shellFor,
  type Fixtures,
  type Recording,
} from "./session-harness.ts";

const here = dirname(fileURLToPath(import.meta.url));
const viewRoot = resolve(here, "..", "..");
const srcRoot = join(viewRoot, "src");

let server: ViteDevServer;
let browser: Browser;
let address = "";

before(async () => {
  server = await createServer({
    root: viewRoot,
    cacheDir: join(viewRoot, "node_modules", ".vite-pixel-topology"),
    plugins: [],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
  });
  try {
    await server.listen();
    const url = server.resolvedUrls?.local[0];
    if (!url) throw new Error("模块服务器未给出本地监听地址");
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

/** 在空白浏览器页里执行驱动函数并返回读数。 */
async function runInPage<T>(driver: (input: never) => Promise<T>, input: unknown): Promise<T> {
  const page = await browser.newPage();
  const pageErrors: string[] = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));
  try {
    await page.route(address + "topology.html", (route) => route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><html><head><meta charset=\"utf-8\"></head><body></body></html>",
    }));
    await page.goto(address + "topology.html");
    const result = await page.evaluate(async (payload: { fnSource: string; input: unknown }) => {
      try {
        const fn = (0, eval)(`(${payload.fnSource})`) as (arg: unknown) => Promise<unknown>;
        return { ok: await fn(payload.input) };
      } catch (e) {
        return { failed: String((e as Error)?.stack ?? e) };
      }
    }, { fnSource: driver.toString(), input });
    if ("failed" in result) throw new Error(`浏览器驱动执行失败：${String(result.failed)}`);
    assert.deepEqual(pageErrors, [], `浏览器页面异常：${pageErrors.join("\n")}`);
    return result.ok as T;
  } finally {
    await page.close();
  }
}

/** 解析 SSE 文本里的全部 JSON 事件帧。 */
function parseSseEvents(raw: string): Record<string, unknown>[] {
  const events: Record<string, unknown>[] = [];
  for (const line of raw.split(/\r?\n/)) {
    if (!line.startsWith("data: ")) continue;
    events.push(JSON.parse(line.slice(6)) as Record<string, unknown>);
  }
  return events;
}

/** 把事件对象序列重新编码为 SSE 帧流文本。 */
function encodeSseEvents(events: readonly Record<string, unknown>[]): string {
  return events.map((ev) => `event: event\ndata: ${JSON.stringify(ev)}\nid: ${String(ev.position)}\n\n`).join("");
}

/** 默认三职能与全部改名三职能之间的双射。 */
const FORWARD_ID: Record<string, string> = {
  product: "spec_role",
  engineering: "impl_role",
  quality: "check_role",
};
const INVERSE_ID: Record<string, string> = {
  spec_role: "product",
  impl_role: "engineering",
  check_role: "quality",
};
const FORWARD_LABEL: Record<string, string> = {
  产品: "策划",
  工程: "建造",
  质检: "把关",
};
const INVERSE_LABEL: Record<string, string> = {
  策划: "产品",
  建造: "工程",
  把关: "质检",
};

/** 属于业务正文（意图、提问与回答原文、标题）的字段名：不替换其中的普通英文单词 product 等。 */
const PROSE_KEYS = new Set([
  "goal",
  "title",
  "text",
  "sign",
  "task",
  "question",
  "answer",
  "background",
  "expected",
  "summary",
  "output",
]);

/** 递归替换 JSON 值里的角色标识与中文显示名（用于构造改名录制及反向还原比对）。 */
function mapRoleTokens<T>(
  value: T,
  idMap: Readonly<Record<string, string>>,
  labelMap: Readonly<Record<string, string>>,
  parentKey = "",
): T {
  if (PROSE_KEYS.has(parentKey)) return value;
  const replaceText = (text: string): string => {
    if (Object.prototype.hasOwnProperty.call(idMap, text)) return idMap[text];
    if (Object.prototype.hasOwnProperty.call(labelMap, text)) return labelMap[text];
    let out = text;
    for (const [from, to] of Object.entries(idMap)) {
      out = out.replace(new RegExp(`(?<![A-Za-z0-9_])${from}(?![A-Za-z0-9_])`, "g"), to);
    }
    for (const [from, to] of Object.entries(labelMap)) {
      out = out.split(from).join(to);
    }
    return out;
  };
  if (typeof value === "string") return replaceText(value) as unknown as T;
  if (Array.isArray(value)) return value.map((item) => mapRoleTokens(item, idMap, labelMap, parentKey)) as unknown as T;
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      const mappedKey = PROSE_KEYS.has(k) ? k : replaceText(k);
      out[mappedKey] = mapRoleTokens(v, idMap, labelMap, k);
    }
    return out as T;
  }
  return value;
}

/** 从录制夹具提取楼层与楼翻译所需的快照输入。 */
function queryInputsOf(recording: Recording) {
  const projectsResp = responseOf(recording, "projects.list", {});
  const loopResp = responseOf(recording, "project.loop", { project_id: recording.ids.project_id });
  const decisionsResp = responseOf(recording, "decisions.list", { project_id: recording.ids.project_id, status: ["open"] });
  const asksResp = responseOf(recording, "run.asks", { run_id: recording.ids.run_id });
  const loopData = loopResp.data as {
    project_id: string;
    work_items: { organization?: { roles?: { id: string }[] } }[];
  };
  const roleIds = loopData.work_items[0]?.organization?.roles?.map((r) => r.id) ?? ["product", "engineering", "quality"];
  const roles: Record<string, unknown[]> = {};
  for (const roleId of roleIds) {
    const ws = responseOf(recording, "department.workspace", {
      project_id: recording.ids.project_id,
      department: roleId,
      work_item: recording.ids.work_item_id,
    });
    const room = (ws.data as { room?: { roles?: unknown[] } }).room;
    if (room?.roles) roles[roleId] = room.roles;
  }
  return {
    floorInput: {
      position: loopResp.position,
      loop: loopResp.data,
      decisions: (decisionsResp.data as { decisions: unknown[] }).decisions,
      asks: { [recording.ids.run_id]: (asksResp.data as { asks: unknown[] }).asks },
      roles,
    },
    buildingInput: {
      position: projectsResp.position,
      projects: (projectsResp.data as { projects: unknown[] }).projects,
      loops: { [recording.ids.project_id]: loopResp.data },
    },
  };
}

interface PageTopologySnapshot {
  floorChannels: Record<string, unknown>;
  buildingChannels: {
    position: number;
    floors: {
      project_id: string;
      name: string;
      status: string;
      rooms?: { id: string; label: string; lit: boolean }[];
      lit: Record<string, boolean>;
      valve_closed: boolean;
      decisions: number;
      flags: unknown[];
    }[];
  };
  drawnTexts: string[];
  stampRect: { x: number; y: number; w: number; h: number; drawn: boolean } | null;
  verifierBounds: { id: string; x: number; w: number } | null;
  criterionLabels: { key: string; x: number; y: number; w: number; h: number }[];
}

/** 浏览器内驱动：装载楼层与楼画面，读取事实通道、信息条绘制文字、放行章矩形与检验覆盖牌坐标。 */
async function inspectTopologyInBrowser(input: {
  floorModel: Record<string, unknown>;
  buildingModel: Record<string, unknown>;
  releasedFloorModel: Record<string, unknown>;
  coverageData: CoverageOverlayData;
}): Promise<PageTopologySnapshot> {
  const FloorMod = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/pixel/floor/view.ts");
  const BuildingMod = await import(/* @vite-ignore */ "/src/pixel/building/view.ts" as string) as typeof import("../../src/pixel/building/view.ts");
  const ClockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");

  const drawnTexts: string[] = [];
  const origFillText = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (text: string, x: number, y: number, maxWidth?: number): void {
    drawnTexts.push(String(text));
    if (maxWidth !== undefined) origFillText.call(this, text, x, y, maxWidth);
    else origFillText.call(this, text, x, y);
  };

  const hostFloor = document.createElement("div");
  hostFloor.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px";
  document.body.appendChild(hostFloor);
  const hostBuilding = document.createElement("div");
  hostBuilding.style.cssText = "position:fixed;left:0;top:330px;width:640px;height:320px";
  document.body.appendChild(hostBuilding);

  const clock = ClockMod.createManualClock();
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };

  let floorView: Awaited<ReturnType<typeof FloorMod.createFloorView>> | null = null;
  let buildingView: Awaited<ReturnType<typeof BuildingMod.createBuildingView>> | null = null;
  try {
    floorView = await FloorMod.createFloorView({ host: hostFloor, clock });
    buildingView = await BuildingMod.createBuildingView({ host: hostBuilding, clock });

    floorView.jump(input.floorModel as never);
    buildingView.jump(input.buildingModel as never);
    drawnTexts.length = 0;
    advance(250);

    const floorChannels = floorView.inspect().channels() as unknown as Record<string, unknown>;
    const buildingChannels = buildingView.inspect().channels() as unknown as PageTopologySnapshot["buildingChannels"];
    const infoTexts = drawnTexts.slice();

    // 切到已放行并开启覆盖层「检验」的状态，读取放行章命中框与核验房间上的条件牌坐标
    floorView.jump(input.releasedFloorModel as never);
    floorView.setOverlay("coverage", input.coverageData);
    advance(200);

    const stampRect = floorView.factRects().find((r) => r.element === "stamp") ?? null;
    const world = floorView.inspect().driver.world;
    const verifierRoom = world.roomOrder
      .map((id) => world.rooms[id])
      .find((r) => r && r.roomKind === "dept" && Boolean(r.def.verifier)) ?? null;
    const criterionLabels = floorView.inspect().renderer.overlayLabels
      .filter((item) => item.key.startsWith("coverage:criterion:"));

    return {
      floorChannels,
      buildingChannels,
      drawnTexts: infoTexts,
      stampRect: stampRect ? { x: stampRect.x, y: stampRect.y, w: stampRect.w, h: stampRect.h, drawn: stampRect.drawn } : null,
      verifierBounds: verifierRoom ? { id: verifierRoom.id, x: verifierRoom.x, w: verifierRoom.w } : null,
      criterionLabels,
    };
  } finally {
    CanvasRenderingContext2D.prototype.fillText = origFillText;
    floorView?.destroy();
    buildingView?.destroy();
    hostFloor.remove();
    hostBuilding.remove();
  }
}

const SAMPLE_COVERAGE: CoverageOverlayData = {
  bar: {
    criteria_total: 2,
    covered: 2,
    coverage_ratio: 1,
    executable: 2,
    open: 0,
    model_reading: 0,
    text: "检验覆盖 2/2 · 开环 0 条",
  },
  legend: [
    { key: "passed", label: "通过", count: 2, text: "通过 2" },
    { key: "failed", label: "不通过", count: 0, text: "不通过 0" },
    { key: "unverified", label: "未核验", count: 0, text: "未核验 0" },
    { key: "open", label: "开环条件", count: 0, text: "开环 0 条" },
  ],
  criteria: [
    {
      criterion: "AC1",
      open: false,
      executable: true,
      method: "check",
      method_label: "可执行检查",
      result: "passed",
      result_label: "通过",
      text: "AC1 · 可执行检查 · 通过",
    },
    {
      criterion: "AC2",
      open: false,
      executable: true,
      method: "check",
      method_label: "可执行检查",
      result: "passed",
      result_label: "通过",
      text: "AC2 · 可执行检查 · 通过",
    },
  ],
};

function makeReleasedFloorModel(base: ReturnType<typeof floorState>): ReturnType<typeof floorState> {
  return {
    ...base,
    coverage: SAMPLE_COVERAGE,
    items: base.items.map((it, idx) => (idx === 0
      ? {
          ...it,
          status: "done",
          refs: { ...(it.refs ?? {}), stamp: { position: 118, source: "role_statement" } },
        }
      : it)),
  };
}

// 守 R2 与 R3：默认三职能下楼层与楼的事实通道与改前一致，信息条绘制「所在职能：…」。
test("默认三职能录制回放：楼层与楼的事实通道与拓扑一致，信息条绘制「所在职能：…」", async () => {
  const fixtures = loadFixtures();
  const demo = recordingOf(fixtures, "demo");
  const { floorInput, buildingInput } = queryInputsOf(demo);

  const fState = floorState(floorInput as never);
  const bState = buildingState(buildingInput as never);
  assert.ok(fState.topology, "翻译层必须从事项冻结定义给出楼层拓扑");
  assert.deepEqual(
    fState.topology.rooms,
    [
      { id: "product", label: "产品", verifier: false, exit_tray: false },
      { id: "engineering", label: "工程", verifier: false, exit_tray: false },
      { id: "quality", label: "质检", verifier: true, exit_tray: false },
    ],
  );

  const snap = await runInPage<PageTopologySnapshot>(
    inspectTopologyInBrowser as unknown as (input: never) => Promise<PageTopologySnapshot>,
    {
      floorModel: fState,
      buildingModel: bState,
      releasedFloorModel: makeReleasedFloorModel(fState),
      coverageData: SAMPLE_COVERAGE,
    },
  );

  const rooms = snap.floorChannels.rooms as Record<string, { label: string; lit: boolean; verifier: boolean; exit_tray: boolean }>;
  assert.deepEqual(Object.keys(rooms), ["product", "engineering", "quality"]);
  assert.equal(rooms.product.label, "产品");
  assert.equal(rooms.engineering.label, "工程");
  assert.equal(rooms.quality.label, "质检");
  assert.equal(rooms.product.lit, false);
  assert.equal(rooms.engineering.lit, true);
  assert.equal(rooms.quality.lit, true);
  assert.equal(rooms.product.verifier, false);
  assert.equal(rooms.engineering.verifier, false);
  assert.equal(rooms.quality.verifier, true);
  assert.deepEqual(snap.floorChannels.links, {
    handoffs: ["engineering>quality", "hall>product", "product>engineering", "product>quality", "quality>library"],
    tubes: ["engineering~quality", "product~engineering", "product~quality"],
    returns: ["quality>engineering"],
  });

  assert.equal(snap.buildingChannels.floors.length, 1);
  assert.deepEqual(snap.buildingChannels.floors[0].rooms, [
    { id: "product", label: "产品", lit: false },
    { id: "engineering", label: "工程", lit: true },
    { id: "quality", label: "质检", lit: true },
  ]);
  assert.deepEqual(snap.buildingChannels.floors[0].lit, {
    product: false,
    engineering: true,
    quality: true,
    operations: false,
  });

  assert.ok(
    snap.drawnTexts.includes("所在职能：质检"),
    `楼层信息条未绘制「所在职能：质检」，实际绘制文字：${snap.drawnTexts.join(" | ")}`,
  );
  assert.ok(
    !snap.drawnTexts.some((t) => t.includes("当前部门")),
    `楼层画布仍出现旧称「当前部门」：${snap.drawnTexts.filter((t) => t.includes("当前部门")).join(" | ")}`,
  );
});

// 守 R2 与 R3：三职能全部改名的定义跑同一段录制时，事实通道与动作序列除角色标识与屋名外与默认三职能完全一致，
// 且放行章与覆盖层「检验」的条件牌落在改名后的核验角色房间内。
test("三职能全部改名跑同一段录制：事实通道除门牌与屋名外与默认三职能一致，放行章与检验牌跟核验角色走", async () => {
  const baseFixtures = loadFixtures();
  const rawSse = loadEvents("events.sse");
  const parsedEvents = parseSseEvents(rawSse);

  const renamedFixtures: Fixtures = {
    capabilities: baseFixtures.capabilities,
    recordings: baseFixtures.recordings.map((rec) => (
      rec.name === "demo" ? mapRoleTokens(rec, FORWARD_ID, FORWARD_LABEL) : rec
    )),
  };
  const renamedEvents = mapRoleTokens(parsedEvents, FORWARD_ID, FORWARD_LABEL);
  const renamedSse = encodeSseEvents(renamedEvents);

  const defaultDemo = recordingOf(baseFixtures, "demo");
  const renamedDemo = recordingOf(renamedFixtures, "demo");

  // 1. 经真正的 Shell + EventStream 完整回放同一段 120 帧事件，比对壳交出的楼层动作序列
  const runShellSession = async (fixtures: Fixtures, sseText: string) => {
    const srv = new FakeServer(fixtures, "demo");
    const surface = fakeSurface();
    const shell = shellFor(srv);
    await shell.open("http://view.test", "");
    shell.goFloor(defaultDemo.ids.project_id, defaultDemo.ids.work_item_id);
    const detach = shell.attachHost(fakeHost, fakeClock, async () => surface);
    try {
      await settle();
      srv.pushFrames(sseText);
      await settle();
      return { actions: surface.actions.slice(), jumped: surface.jumped.slice() };
    } finally {
      detach();
      shell.close();
    }
  };

  const defaultRun = await runShellSession(baseFixtures, rawSse);
  const renamedRun = await runShellSession(renamedFixtures, renamedSse);
  assert.ok(defaultRun.actions.length > 0, "默认录制回放未产出楼层动作");
  assert.equal(renamedRun.actions.length, defaultRun.actions.length, "改名录制回放产出的楼层动作条数不一致");
  assert.deepEqual(
    mapRoleTokens(renamedRun.actions, INVERSE_ID, INVERSE_LABEL),
    defaultRun.actions,
    "改名录制回放的楼层动作经双射还原后与默认三职能不一致",
  );

  // 同时直接对全量事件调用翻译层函数核对楼层与楼动作
  const defaultOrg = (responseOf(defaultDemo, "project.loop", { project_id: defaultDemo.ids.project_id }).data as {
    work_items: { organization?: unknown }[];
  }).work_items[0]?.organization;
  const renamedOrg = (responseOf(renamedDemo, "project.loop", { project_id: renamedDemo.ids.project_id }).data as {
    work_items: { organization?: unknown }[];
  }).work_items[0]?.organization;
  const defaultDirectActions = parsedEvents.flatMap((ev) => floorActions(ev as never, { organization: defaultOrg as never }));
  const renamedDirectActions = renamedEvents.flatMap((ev) => floorActions(ev as never, { organization: renamedOrg as never }));
  assert.deepEqual(mapRoleTokens(renamedDirectActions, INVERSE_ID, INVERSE_LABEL), defaultDirectActions);
  assert.deepEqual(
    renamedEvents.flatMap((ev) => buildingActions(ev as never)),
    parsedEvents.flatMap((ev) => buildingActions(ev as never)),
  );

  // 2. 在浏览器画布上比对楼层与楼的事实通道、信息条、放行章及覆盖层「检验」牌子坐标
  const defaultInputs = queryInputsOf(defaultDemo);
  const renamedInputs = queryInputsOf(renamedDemo);
  const defaultFloorState = floorState(defaultInputs.floorInput as never);
  const renamedFloorState = floorState(renamedInputs.floorInput as never);
  const defaultBuildingState = buildingState(defaultInputs.buildingInput as never);
  const renamedBuildingState = buildingState(renamedInputs.buildingInput as never);

  const defaultSnap = await runInPage<PageTopologySnapshot>(
    inspectTopologyInBrowser as unknown as (input: never) => Promise<PageTopologySnapshot>,
    {
      floorModel: defaultFloorState,
      buildingModel: defaultBuildingState,
      releasedFloorModel: makeReleasedFloorModel(defaultFloorState),
      coverageData: SAMPLE_COVERAGE,
    },
  );
  const renamedSnap = await runInPage<PageTopologySnapshot>(
    inspectTopologyInBrowser as unknown as (input: never) => Promise<PageTopologySnapshot>,
    {
      floorModel: renamedFloorState,
      buildingModel: renamedBuildingState,
      releasedFloorModel: makeReleasedFloorModel(renamedFloorState),
      coverageData: SAMPLE_COVERAGE,
    },
  );

  // 改名后的房间键与门口牌子是新名字
  const renamedRooms = renamedSnap.floorChannels.rooms as Record<string, { label: string; verifier: boolean }>;
  assert.deepEqual(Object.keys(renamedRooms), ["spec_role", "impl_role", "check_role"]);
  assert.equal(renamedRooms.spec_role.label, "策划");
  assert.equal(renamedRooms.impl_role.label, "建造");
  assert.equal(renamedRooms.check_role.label, "把关");
  assert.equal(renamedRooms.check_role.verifier, true);
  assert.deepEqual(renamedSnap.buildingChannels.floors[0].rooms, [
    { id: "spec_role", label: "策划", lit: false },
    { id: "impl_role", label: "建造", lit: true },
    { id: "check_role", label: "把关", lit: true },
  ]);

  // 双射还原角色标识与屋名后（对按角色标识字典序排列的连接列表重新排序），楼层承载事实的全部通道与默认三职能完全一致
  const normalizeFloorChannels = (ch: Record<string, unknown>) => {
    const mapped = mapRoleTokens(ch, INVERSE_ID, INVERSE_LABEL) as {
      links?: { handoffs: string[]; tubes: string[]; returns: string[] };
      [k: string]: unknown;
    };
    if (mapped.links) {
      mapped.links = {
        handoffs: mapped.links.handoffs.slice().sort(),
        tubes: mapped.links.tubes.slice().sort(),
        returns: mapped.links.returns.slice().sort(),
      };
    }
    return mapped;
  };
  assert.deepEqual(
    normalizeFloorChannels(renamedSnap.floorChannels),
    normalizeFloorChannels(defaultSnap.floorChannels),
  );
  // 楼的事实通道（按 rooms 列表与其余字段核对，排除保留一版的旧四键兼容别名 lit）经双射还原后完全一致
  const stripLegacyLit = (ch: PageTopologySnapshot["buildingChannels"]) => ({
    position: ch.position,
    floors: ch.floors.map(({ lit: _legacyLit, ...rest }) => rest),
  });
  assert.deepEqual(
    mapRoleTokens(stripLegacyLit(renamedSnap.buildingChannels), INVERSE_ID, INVERSE_LABEL),
    stripLegacyLit(defaultSnap.buildingChannels),
  );

  // 信息条显示改名后的核验职能显示名
  assert.ok(
    renamedSnap.drawnTexts.includes("所在职能：把关"),
    `改名楼层信息条未绘制「所在职能：把关」，实际：${renamedSnap.drawnTexts.join(" | ")}`,
  );

  // 放行章与覆盖层「检验」条件牌均定位在改名后的核验角色房间 check_role 内，坐标与默认三职能相同
  assert.ok(renamedSnap.verifierBounds, "改名楼层未找到核验角色房间");
  assert.equal(renamedSnap.verifierBounds.id, "check_role");
  assert.ok(renamedSnap.stampRect && renamedSnap.stampRect.drawn, "改名楼层未画出放行章命中框");
  const stampCenterX = renamedSnap.stampRect.x + renamedSnap.stampRect.w / 2;
  assert.ok(
    stampCenterX >= renamedSnap.verifierBounds.x
      && stampCenterX <= renamedSnap.verifierBounds.x + renamedSnap.verifierBounds.w,
    `放行章中心 ${stampCenterX} 未落在核验角色房间 [${renamedSnap.verifierBounds.x}, ${renamedSnap.verifierBounds.x + renamedSnap.verifierBounds.w}] 内`,
  );
  assert.deepEqual(renamedSnap.stampRect, defaultSnap.stampRect);

  assert.equal(renamedSnap.criterionLabels.length, 2);
  for (const labelRect of renamedSnap.criterionLabels) {
    const labelCenterX = labelRect.x + labelRect.w / 2;
    assert.ok(
      labelCenterX >= renamedSnap.verifierBounds.x - 40
        && labelCenterX <= renamedSnap.verifierBounds.x + renamedSnap.verifierBounds.w + 40,
      `检验条件牌 ${labelRect.key} 中心 ${labelCenterX} 偏离核验角色房间 check_role`,
    );
  }
  assert.deepEqual(renamedSnap.criterionLabels, defaultSnap.criterionLabels);
});

// ---------------------------------------------------------------------------
// 单屋直做、两屋无核验 / 直做加核验、同层多份定义并集与未声明角色通用外观（工单 #1385）

const TOPO_REF = { position: 2, source: "rule" as const };

function makeTopoRow(over: Record<string, unknown>): Record<string, unknown> {
  return {
    work_item_id: "w_topo",
    kind: "request",
    sign: "示例事项",
    color_index: 1,
    status: "in_progress",
    department: "engineering",
    progress: null,
    round: 1,
    started_at: "2026-11-14T09:00:00+08:00",
    elapsed_sec: 45,
    time_limit_sec: 3600,
    pending_question: null,
    run_id: "r_topo",
    adoption_id: null,
    recovery_state: null,
    version: 1,
    refs: { sign: TOPO_REF, round: TOPO_REF, elapsed: TOPO_REF },
    ...over,
  };
}

// 守 R2 与 R3：「工程」只有一个职能时，大厅与成果库之间只画一间自适应铺满标准跨度的「工程」屋，设出口托盘，
// 交完成时演关键动作盖虚线的开环完成章，采纳后出口托盘与成果库箱子均保留虚线章，进入工程房间也画出口托盘与虚线章。
test("「工程」单职能直做：只画一间工程屋设出口托盘，楼层、房间与成果库箱子均盖虚线的开环完成章", async () => {
  const soloOrg = {
    form: "solo_engineering",
    routing: "watched_outputs",
    entry: { id: "engineering", label: "工程", ref: TOPO_REF },
    roles: [{ id: "engineering", label: "工程", ref: TOPO_REF }],
    verifiers: [],
    completing: { id: "engineering", label: "工程", ref: TOPO_REF },
    watched: [],
    asks: [],
    rejections: [],
  };

  const workingModel = floorState({
    position: 10,
    loop: {
      project_id: "p_solo",
      work_items: [makeTopoRow({ work_item_id: "w_solo", sign: "修一处样式", organization: soloOrg })] as never,
      adoptions: [],
    },
    roles: { engineering: [{ id: "eng-lead", name: "主程", kind: "lead", status: "working" }] },
  });
  const adoptedModel = floorState({
    position: 20,
    loop: {
      project_id: "p_solo",
      work_items: [
        makeTopoRow({
          work_item_id: "w_solo",
          sign: "修一处样式",
          status: "adopted",
          stop_reason: "open_loop",
          department: null,
          organization: soloOrg,
          refs: { sign: TOPO_REF, stamp: { position: 19, source: "role_statement" }, box: { position: 20, source: "rule" } },
        }),
      ] as never,
      adoptions: [{ adoption_id: "ad_solo", work_item_id: "w_solo", run_id: "r_topo" } as never],
    },
  });
  const completionActions = floorActions(
    {
      type: "artifact_accepted",
      position: 19,
      department: "engineering",
      work_item_id: "w_solo",
      payload: { artifact_kind: "completion", artifact_issuer: "engineering" },
    },
    { organization: soloOrg as never },
  );
  const roomCompletionActions = roomActions(
    {
      type: "artifact_accepted",
      position: 19,
      department: "engineering",
      work_item_id: "w_solo",
      payload: { artifact_kind: "completion", artifact_issuer: "engineering" },
    },
    "engineering",
    { organization: soloOrg as never },
  );
  const soloWorkingRoomState = translateRoomState({
    position: 10,
    workspace: {
      room: {
        department: "engineering",
        level: "S5",
        status: "working",
        crt: { target: "修一处样式", model: "m", protocol: "Responses", status: "进行中", cycle: 1 },
        roles: [{ id: "eng-lead", name: "主程", kind: "lead", status: "working", task: "修一处样式" }],
        pose: { role_id: "eng-lead", action: "reading" },
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
    },
    department: "engineering",
    organization: soloOrg as never,
  });
  const soloRoomState = translateRoomState({
    position: 20,
    workspace: {
      room: {
        department: "engineering",
        level: "S5",
        status: "done",
        crt: { target: "修一处样式", model: "m", protocol: "Responses", status: "已完成", cycle: 1 },
        roles: [{ id: "eng-lead", name: "主程", kind: "lead", status: "idle", task: null }],
        pose: { role_id: "eng-lead", action: "idle" },
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
    },
    department: "engineering",
    organization: soloOrg as never,
  });

  const snap = await runInPage(
    async (input: {
      workingModel: Record<string, unknown>;
      adoptedModel: Record<string, unknown>;
      completionActions: Record<string, unknown>[];
      soloWorkingRoomState: Record<string, unknown>;
      soloRoomState: Record<string, unknown>;
      roomCompletionActions: Record<string, unknown>[];
    }) => {
      const FloorMod = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/pixel/floor/view.ts");
      const RoomMod = await import(/* @vite-ignore */ "/src/pixel/room/view.ts" as string) as typeof import("../../src/pixel/room/view.ts");
      const ClockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");

      const hostF = document.createElement("div");
      hostF.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px";
      document.body.appendChild(hostF);
      const hostR = document.createElement("div");
      hostR.style.cssText = "position:fixed;left:0;top:330px;width:640px;height:320px";
      document.body.appendChild(hostR);

      const clock = ClockMod.createManualClock();
      const advance = (ms: number): void => {
        const frames = Math.max(1, Math.round(ms / 50));
        for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
      };

      const fView = await FloorMod.createFloorView({ host: hostF, clock });
      const rView = await RoomMod.createRoomView({ host: hostR, clock, department: "engineering" });
      try {
        fView.jump(input.workingModel as never);
        advance(200);
        for (const act of input.completionActions) fView.play(act as never);
        advance(200);
        const playingFloor = fView.inspect().driver.inspectTimeline().playing.map((p) => p.kind);

        fView.jump(input.adoptedModel as never);
        advance(250);
        const world = fView.inspect().driver.world;
        const engRoom = world.rooms.engineering;
        const fChannels = fView.inspect().channels();
        const stampRect = fView.factRects().find((r) => r.element === "stamp") ?? null;
        const boxRect = fView.factRects().find((r) => r.element === "box") ?? null;

        rView.jump(input.soloWorkingRoomState as never);
        advance(200);
        for (const act of input.roomCompletionActions) rView.play(act as never);
        rView.setState(input.soloRoomState as never);
        advance(800);
        const playingRoom = rView.inspect().driver.timeline().playing.map((p) => p.kind);
        let sawBenchMark: { text: string; color: string; dashed?: boolean } | null = null;
        for (let step = 0; step < 140; step++) {
          advance(50);
          const cur = rView.inspect().driver.state.bench.mark;
          if (cur?.dashed) sawBenchMark = { ...cur };
        }
        const rChannels = rView.inspect().channels();

        return {
          roomOrder: world.roomOrder.slice(),
          engBounds: engRoom ? { x: engRoom.x, w: engRoom.w, verifier: Boolean(engRoom.def.verifier), exitTray: Boolean(engRoom.def.exitTray) } : null,
          fChannels,
          playingFloor,
          stampRect: stampRect ? { x: stampRect.x, y: stampRect.y, w: stampRect.w, h: stampRect.h, drawn: stampRect.drawn } : null,
          boxRect: boxRect ? { x: boxRect.x, y: boxRect.y, w: boxRect.w, h: boxRect.h, drawn: boxRect.drawn } : null,
          playingRoom,
          rChannels,
          benchMark: sawBenchMark,
        };
      } finally {
        fView.destroy();
        rView.destroy();
        hostF.remove();
        hostR.remove();
      }
    },
    { workingModel, adoptedModel, completionActions, soloWorkingRoomState, soloRoomState, roomCompletionActions },
  );

  // 大厅与成果库之间只有一间铺满标准跨度 342 的工程屋，带出口托盘，整层无盖章台
  assert.deepEqual(snap.roomOrder, ["hall", "engineering", "library"]);
  assert.ok(snap.engBounds);
  assert.equal(snap.engBounds.w, 342);
  assert.equal(snap.engBounds.verifier, false);
  assert.equal(snap.engBounds.exitTray, true);
  assert.deepEqual(snap.fChannels.links, {
    handoffs: ["engineering>library", "hall>engineering"],
    tubes: [],
    returns: [],
  });

  // 交完成时演关键动作 stamp_open_loop；已采纳时出口托盘与成果库箱子均保留虚线章且回链命中框落在对应区域
  assert.ok(snap.playingFloor.includes("stamp_open_loop"), `楼层未演 stamp_open_loop：${snap.playingFloor.join(",")}`);
  assert.deepEqual(snap.fChannels.stamps, [
    { work_item_id: "w_solo", room: "engineering", kind: "open_loop", outsourced: false, text: "开环完成" },
  ]);
  assert.deepEqual(snap.fChannels.shelf.boxes, [
    { work_item_id: "w_solo", stamp_kind: "open_loop", outsourced: false },
  ]);
  assert.ok(snap.stampRect && snap.stampRect.drawn, "出口托盘虚线章未登记点击回链命中框");
  const stampCenterX = snap.stampRect.x + snap.stampRect.w / 2;
  assert.ok(
    stampCenterX >= snap.engBounds.x + snap.engBounds.w - 60 && stampCenterX <= snap.engBounds.x + snap.engBounds.w,
    `虚线章中心 ${stampCenterX} 未落在工程屋右侧出口托盘区域`,
  );
  assert.ok(snap.boxRect && snap.boxRect.drawn, "成果库箱子未登记点击回链命中框");

  // 工程房间：具备出口托盘、无检验台，演出 stamp_open_loop 留下虚线印记，事实通道为 open_loop
  assert.ok(snap.playingRoom.includes("stamp_open_loop"), `房间未演 stamp_open_loop：${snap.playingRoom.join(",")}`);
  assert.equal(snap.rChannels.verifier, false);
  assert.equal(snap.rChannels.exit_tray, true);
  assert.deepEqual(snap.rChannels.stamp, { kind: "open_loop", outsourced: false, text: "开环完成" });
  assert.equal(snap.benchMark?.text, "开环完成");
  assert.equal(snap.benchMark?.dashed, true);

  // 外包字样分支：外包标记为真时，楼层出口托盘、成果库箱子与房间印文均为「开环完成 · 外包」
  const outsourcedFloorModel = floorState({
    position: 25,
    loop: {
      project_id: "p_solo",
      work_items: [
        makeTopoRow({
          work_item_id: "w_solo_ext",
          sign: "外包直做事项",
          status: "adopted",
          stop_reason: "open_loop",
          outsourced: true,
          department: null,
          organization: soloOrg,
          refs: { sign: TOPO_REF, stamp: { position: 24, source: "role_statement" }, box: { position: 25, source: "rule" } },
        }),
      ] as never,
      adoptions: [{ adoption_id: "ad_solo_ext", work_item_id: "w_solo_ext", run_id: "r_ext" } as never],
    },
  });
  const outsourcedRoomState = translateRoomState({
    position: 25,
    workspace: {
      room: {
        department: "engineering",
        level: "S5",
        status: "done",
        outsourced: true,
        crt: { target: "外包直做事项", model: "m", protocol: "Responses", status: "已完成", cycle: 1 },
        roles: [{ id: "eng-lead", name: "主程", kind: "lead", status: "idle", task: null }],
        pose: { role_id: "eng-lead", action: "idle" },
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
    },
    department: "engineering",
    organization: soloOrg as never,
  });
  const extSnap = await runInPage(
    async (input: { f: Record<string, unknown>; r: Record<string, unknown> }) => {
      const FloorMod = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/pixel/floor/view.ts");
      const RoomMod = await import(/* @vite-ignore */ "/src/pixel/room/view.ts" as string) as typeof import("../../src/pixel/room/view.ts");
      const ClockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");
      const hF = document.createElement("div");
      hF.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px";
      document.body.appendChild(hF);
      const hR = document.createElement("div");
      hR.style.cssText = "position:fixed;left:0;top:330px;width:640px;height:320px";
      document.body.appendChild(hR);
      const clock = ClockMod.createManualClock();
      const fv = await FloorMod.createFloorView({ host: hF, clock });
      const rv = await RoomMod.createRoomView({ host: hR, clock, department: "engineering" });
      try {
        fv.jump(input.f as never);
        rv.jump(input.r as never);
        clock.advance(200);
        return { fc: fv.inspect().channels(), rc: rv.inspect().channels() };
      } finally {
        fv.destroy();
        rv.destroy();
        hF.remove();
        hR.remove();
      }
    },
    { f: outsourcedFloorModel, r: outsourcedRoomState },
  );
  assert.deepEqual(extSnap.fc.stamps, [
    { work_item_id: "w_solo_ext", room: "engineering", kind: "open_loop", outsourced: true, text: "开环完成 · 外包" },
  ]);
  assert.deepEqual(extSnap.fc.shelf.boxes, [
    { work_item_id: "w_solo_ext", stamp_kind: "open_loop", outsourced: true },
  ]);
  assert.deepEqual(extSnap.rc.stamp, { kind: "open_loop", outsourced: true, text: "开环完成 · 外包" });
});

// 守 R2 与 R3：「产品 · 工程」无核验角色（两屋 + 传信管 + 出口托盘虚线章）与「工程 · 质检」直做加核验（两屋 + 盖章台实心章 + 回流管）。
test("两屋拓扑：「产品 · 工程」无核验设传信管与出口托盘，「工程 · 质检」直做加核验设盖章台与回流管", async () => {
  const prodEngOrg = {
    form: "product_engineering_open",
    routing: "watched_outputs",
    entry: { id: "product", label: "产品", ref: TOPO_REF },
    roles: [
      { id: "product", label: "产品", ref: TOPO_REF },
      { id: "engineering", label: "工程", ref: TOPO_REF },
    ],
    verifiers: [],
    completing: { id: "engineering", label: "工程", ref: TOPO_REF },
    watched: [{ source: "product", recipient: "engineering", outcome: "product_spec", ref: TOPO_REF }],
    asks: [
      { requester: "engineering", recipient: "product", ref: TOPO_REF },
      { requester: "product", recipient: "engineering", ref: TOPO_REF },
    ],
    rejections: [],
  };
  const engQaOrg = {
    form: "engineering_quality_verified",
    routing: "watched_outputs",
    entry: { id: "engineering", label: "工程", ref: TOPO_REF },
    roles: [
      { id: "engineering", label: "工程", ref: TOPO_REF },
      { id: "quality", label: "质检", ref: TOPO_REF },
    ],
    verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["completion"] }], ref: TOPO_REF }],
    completing: null,
    watched: [{ source: "engineering", recipient: "quality", outcome: "completion", ref: TOPO_REF }],
    asks: [],
    rejections: [{ verifier: "quality", role: "engineering", outcome: "completion", ref: TOPO_REF }],
  };

  const prodEngModel = floorState({
    position: 30,
    loop: {
      project_id: "p_pe",
      work_items: [
        makeTopoRow({
          work_item_id: "w_pe",
          status: "adopted",
          stop_reason: "open_loop",
          department: null,
          organization: prodEngOrg,
          refs: { sign: TOPO_REF, stamp: TOPO_REF, box: TOPO_REF },
        }),
      ] as never,
      adoptions: [{ adoption_id: "ad_pe", work_item_id: "w_pe", run_id: "r_pe" } as never],
    },
  });
  const engQaModel = floorState({
    position: 40,
    loop: {
      project_id: "p_eq",
      work_items: [
        makeTopoRow({
          work_item_id: "w_eq",
          status: "adopted",
          stop_reason: null,
          department: null,
          organization: engQaOrg,
          refs: { sign: TOPO_REF, stamp: TOPO_REF, box: TOPO_REF },
        }),
      ] as never,
      adoptions: [{ adoption_id: "ad_eq", work_item_id: "w_eq", run_id: "r_eq" } as never],
    },
  });

  const readTwo = await runInPage(
    async (input: { prodEngModel: Record<string, unknown>; engQaModel: Record<string, unknown> }) => {
      const FloorMod = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/pixel/floor/view.ts");
      const ClockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");
      const host = document.createElement("div");
      host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px";
      document.body.appendChild(host);
      const clock = ClockMod.createManualClock();
      const advance = (ms: number): void => {
        const frames = Math.max(1, Math.round(ms / 50));
        for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
      };
      const view = await FloorMod.createFloorView({ host, clock });
      try {
        view.jump(input.prodEngModel as never);
        advance(200);
        const peWorld = view.inspect().driver.world;
        const peWidths = ["product", "engineering"].map((id) => peWorld.rooms[id]?.w ?? 0);
        const peChannels = view.inspect().channels();

        view.jump(input.engQaModel as never);
        advance(200);
        const eqWorld = view.inspect().driver.world;
        const eqWidths = ["engineering", "quality"].map((id) => eqWorld.rooms[id]?.w ?? 0);
        const eqChannels = view.inspect().channels();

        return { peWidths, peChannels, eqWidths, eqChannels };
      } finally {
        view.destroy();
        host.remove();
      }
    },
    { prodEngModel, engQaModel },
  );

  // 「产品 · 工程」无核验：两屋各宽 168，有传信管，工程设出口托盘盖虚线章，无盖章台与回流管
  assert.deepEqual(readTwo.peWidths, [168, 168]);
  assert.deepEqual(Object.keys(readTwo.peChannels.rooms), ["product", "engineering"]);
  assert.equal(readTwo.peChannels.rooms.product.verifier, false);
  assert.equal(readTwo.peChannels.rooms.engineering.verifier, false);
  assert.equal(readTwo.peChannels.rooms.engineering.exit_tray, true);
  assert.deepEqual(readTwo.peChannels.links, {
    handoffs: ["engineering>library", "hall>product", "product>engineering"],
    tubes: ["product~engineering"],
    returns: [],
  });
  assert.deepEqual(readTwo.peChannels.stamps, [
    { work_item_id: "w_pe", room: "engineering", kind: "open_loop", outsourced: false, text: "开环完成" },
  ]);

  // 「工程 · 质检」直做加核验：两屋各宽 168，质检设盖章台盖实心放行章，带红色回流管，两屋均无出口托盘与虚线章
  assert.deepEqual(readTwo.eqWidths, [168, 168]);
  assert.deepEqual(Object.keys(readTwo.eqChannels.rooms), ["engineering", "quality"]);
  assert.equal(readTwo.eqChannels.rooms.engineering.exit_tray, false);
  assert.equal(readTwo.eqChannels.rooms.quality.exit_tray, false);
  assert.equal(readTwo.eqChannels.rooms.quality.verifier, true);
  assert.deepEqual(readTwo.eqChannels.links, {
    handoffs: ["engineering>quality", "hall>engineering", "quality>library"],
    tubes: [],
    returns: ["quality>engineering"],
  });
  assert.deepEqual(readTwo.eqChannels.stamps, [
    { work_item_id: "w_eq", room: "quality", kind: "release", outsourced: false, text: "放行" },
  ]);
});

// 守 R2 与 R3：同一楼层同时有一个「产品 · 工程 · 质检」事项与一个「工程」事项时，房间与管道取并集，
// 每件事项的入口包裹、小旗、门牌与结束章位置各自严格按自身冻结定义流转，直做事项不进产品与质检屋。
test("同层并存「产品 · 工程 · 质检」与「工程」两份定义：房间取并集，每件事项只按自身冻结定义走", async () => {
  const triOrg = {
    form: "three_departments",
    routing: "watched_outputs",
    entry: { id: "product", label: "产品", ref: TOPO_REF },
    roles: [
      { id: "product", label: "产品", ref: TOPO_REF },
      { id: "engineering", label: "工程", ref: TOPO_REF },
      { id: "quality", label: "质检", ref: TOPO_REF },
    ],
    verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["delivery_spec"] }], ref: TOPO_REF }],
    completing: null,
    watched: [
      { source: "product", recipient: "engineering", outcome: "product_spec", ref: TOPO_REF },
      { source: "product", recipient: "quality", outcome: "product_spec", ref: TOPO_REF },
      { source: "engineering", recipient: "quality", outcome: "delivery_spec", ref: TOPO_REF },
    ],
    asks: [
      { requester: "product", recipient: "engineering", ref: TOPO_REF },
      { requester: "engineering", recipient: "quality", ref: TOPO_REF },
    ],
    rejections: [{ verifier: "quality", role: "engineering", outcome: "delivery_spec", ref: TOPO_REF }],
  };
  const soloOrg = {
    form: "solo_engineering",
    routing: "watched_outputs",
    entry: { id: "engineering", label: "工程", ref: TOPO_REF },
    roles: [{ id: "engineering", label: "工程", ref: TOPO_REF }],
    verifiers: [],
    completing: { id: "engineering", label: "工程", ref: TOPO_REF },
    watched: [],
    asks: [],
    rejections: [],
  };

  // 阶段 1：两件事项同时进行中（w_tri 在质检核验，w_solo 在工程直做）
  const workingUnion = floorState({
    position: 50,
    loop: {
      project_id: "p_mix",
      work_items: [
        makeTopoRow({ work_item_id: "w_tri", sign: "三职能事项", color_index: 1, status: "in_progress", department: "quality", organization: triOrg }),
        makeTopoRow({ work_item_id: "w_solo", sign: "直做事项", color_index: 2, status: "in_progress", department: "engineering", organization: soloOrg }),
      ] as never,
      adoptions: [],
    },
  });

  // 阶段 2：两件事项均结束并采纳（w_tri 放行，w_solo 开环完成）
  const finishedUnion = floorState({
    position: 60,
    loop: {
      project_id: "p_mix",
      work_items: [
        makeTopoRow({
          work_item_id: "w_tri",
          sign: "三职能事项",
          color_index: 1,
          status: "adopted",
          stop_reason: null,
          department: null,
          organization: triOrg,
          refs: { sign: TOPO_REF, stamp: { position: 58, source: "role_statement" }, box: { position: 59, source: "rule" } },
        }),
        makeTopoRow({
          work_item_id: "w_solo",
          sign: "直做事项",
          color_index: 2,
          status: "adopted",
          stop_reason: "open_loop",
          department: null,
          organization: soloOrg,
          refs: { sign: TOPO_REF, stamp: { position: 56, source: "role_statement" }, box: { position: 60, source: "rule" } },
        }),
      ] as never,
      adoptions: [
        { adoption_id: "ad_tri", work_item_id: "w_tri", run_id: "r1" } as never,
        { adoption_id: "ad_solo", work_item_id: "w_solo", run_id: "r2" } as never,
      ],
    },
  });

  const unionSnap = await runInPage(
    async (input: { workingUnion: Record<string, unknown>; finishedUnion: Record<string, unknown> }) => {
      const FloorMod = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/pixel/floor/view.ts");
      const ClockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");
      const host = document.createElement("div");
      host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px";
      document.body.appendChild(host);
      const clock = ClockMod.createManualClock();
      const advance = (ms: number): void => {
        const frames = Math.max(1, Math.round(ms / 50));
        for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
      };
      const view = await FloorMod.createFloorView({ host, clock });
      try {
        view.jump(input.workingUnion as never);
        advance(150);

        // 分别触发两件事项的入口包裹动作，观察在途包裹各自走哪条入口管道
        view.play({ kind: "parcel_enter", position: 51, item: "w_solo" });
        advance(150);
        const soloPkgLinks = Object.values(view.inspect().driver.world.packages)
          .map((p) => p.transit?.linkKey)
          .filter((k): k is string => Boolean(k));

        view.jump(input.workingUnion as never);
        advance(100);
        view.play({ kind: "parcel_enter", position: 52, item: "w_tri" });
        advance(150);
        const triPkgLinks = Object.values(view.inspect().driver.world.packages)
          .map((p) => p.transit?.linkKey)
          .filter((k): k is string => Boolean(k));

        const workingChannels = view.inspect().channels();
        const signRects = view.factRects().filter((r) => r.element === "sign");
        const world = view.inspect().driver.world;
        const roomBounds = Object.fromEntries(
          ["product", "engineering", "quality"].map((id) => [id, { x: world.rooms[id]!.x, w: world.rooms[id]!.w }]),
        );

        view.jump(input.finishedUnion as never);
        advance(250);
        const finishedChannels = view.inspect().channels();
        const stampRects = view.factRects().filter((r) => r.element === "stamp");

        return { soloPkgLinks, triPkgLinks, workingChannels, signRects, roomBounds, finishedChannels, stampRects };
      } finally {
        view.destroy();
        host.remove();
      }
    },
    { workingUnion, finishedUnion },
  );

  // 房间并集：engineering 带出口托盘，quality 带盖章台；入口管道同时有 hall>product 与 hall>engineering
  assert.deepEqual(Object.keys(unionSnap.workingChannels.rooms), ["product", "engineering", "quality"]);
  assert.equal(unionSnap.workingChannels.rooms.product.verifier, false);
  assert.equal(unionSnap.workingChannels.rooms.engineering.exit_tray, true);
  assert.equal(unionSnap.workingChannels.rooms.engineering.verifier, false);
  assert.equal(unionSnap.workingChannels.rooms.quality.verifier, true);
  assert.equal(unionSnap.workingChannels.rooms.quality.exit_tray, false);
  assert.ok(unionSnap.workingChannels.links.handoffs.includes("hall>product"));
  assert.ok(unionSnap.workingChannels.links.handoffs.includes("hall>engineering"));
  assert.ok(unionSnap.workingChannels.links.handoffs.includes("engineering>library"));
  assert.ok(unionSnap.workingChannels.links.handoffs.includes("quality>library"));

  // 直做事项入口包裹直奔 hall>engineering，不进 product；三职能事项走 hall>product
  assert.deepEqual(unionSnap.soloPkgLinks, ["hall>engineering"]);
  assert.deepEqual(unionSnap.triPkgLinks, ["hall>product"]);

  // 小旗与门牌各自落在自己所在职能屋门口，直做事项不挂在产品或质检屋
  assert.deepEqual(unionSnap.workingChannels.rooms.product.flags, []);
  assert.deepEqual(unionSnap.workingChannels.rooms.engineering.flags.map((f) => f.id), ["w_solo"]);
  assert.deepEqual(unionSnap.workingChannels.rooms.quality.flags.map((f) => f.id), ["w_tri"]);
  const soloSign = unionSnap.signRects.find((r) => r.work_item_id === "w_solo");
  assert.ok(soloSign);
  const soloSignCenter = soloSign.x + soloSign.w / 2;
  assert.ok(
    soloSignCenter >= unionSnap.roomBounds.engineering.x
      && soloSignCenter <= unionSnap.roomBounds.engineering.x + unionSnap.roomBounds.engineering.w,
  );

  // 结束章与货架箱子：w_tri 在 quality 盖实心放行章，w_solo 在 engineering 出口托盘盖虚线开环完成章
  assert.deepEqual(unionSnap.finishedChannels.stamps, [
    { work_item_id: "w_tri", room: "quality", kind: "release", outsourced: false, text: "放行" },
    { work_item_id: "w_solo", room: "engineering", kind: "open_loop", outsourced: false, text: "开环完成" },
  ]);
  assert.deepEqual(unionSnap.finishedChannels.shelf.boxes, [
    { work_item_id: "w_tri", stamp_kind: "release", outsourced: false },
    { work_item_id: "w_solo", stamp_kind: "open_loop", outsourced: false },
  ]);
  const triStampRect = unionSnap.stampRects.find((r) => r.work_item_id === "w_tri");
  const soloStampRect = unionSnap.stampRects.find((r) => r.work_item_id === "w_solo");
  assert.ok(triStampRect && soloStampRect);
  assert.ok(
    triStampRect.x + triStampRect.w / 2 >= unionSnap.roomBounds.quality.x
      && triStampRect.x + triStampRect.w / 2 <= unionSnap.roomBounds.quality.x + unionSnap.roomBounds.quality.w,
  );
  assert.ok(
    soloStampRect.x + soloStampRect.w / 2 >= unionSnap.roomBounds.engineering.x
      && soloStampRect.x + soloStampRect.w / 2 <= unionSnap.roomBounds.engineering.x + unionSnap.roomBounds.engineering.w,
  );
});

// 守 R2 与 R3：场景声明里未登记专属外观的角色（如 security「安全审校」），显式检查函数返回 false，
// 楼、楼层、房间三个场景均采用中性灰米通用外观、单张标准工位与通用小人精灵正常渲染。
test("未声明专属外观的角色 security（安全审校）：显式声明函数返回 false，三个场景使用通用外观正常渲染", async () => {
  assert.equal(hasDeclaredFloorAppearance("product"), true);
  assert.equal(hasDeclaredRoomVisual("engineering"), true);
  assert.equal(hasDeclaredRoomAppearance("quality"), true);
  assert.equal(hasDeclaredFloorAppearance("security"), false);
  assert.equal(hasDeclaredRoomVisual("security"), false);
  assert.equal(hasDeclaredRoomAppearance("security"), false);

  const secOrg = {
    form: "security_audit",
    routing: "watched_outputs",
    entry: { id: "engineering", label: "工程", ref: TOPO_REF },
    roles: [
      { id: "engineering", label: "工程", ref: TOPO_REF },
      { id: "security", label: "安全审校", ref: TOPO_REF },
    ],
    verifiers: [{ role: "security", verifies: [{ role: "engineering", outcomes: ["completion"] }], ref: TOPO_REF }],
    completing: null,
    watched: [{ source: "engineering", recipient: "security", outcome: "completion", ref: TOPO_REF }],
    asks: [],
    rejections: [{ verifier: "security", role: "engineering", outcome: "completion", ref: TOPO_REF }],
  };
  const secLoop = {
    project_id: "p_sec",
    work_items: [makeTopoRow({ work_item_id: "w_sec", sign: "核查令牌权限", department: "security", organization: secOrg })] as never,
    adoptions: [],
  };
  const fModel = floorState({
    position: 70,
    loop: secLoop,
    roles: { security: [{ id: "sec-1", name: "审校员", kind: "agent", status: "working" }] },
  });
  const bModel = buildingState({
    position: 70,
    projects: [{ project_id: "p_sec", name: "安全项目", goal: "审计", pinned: false, archived: false, last_activity_at: "2026-11-14T10:00:00+08:00", decisions_waiting: 0 }] as never,
    loops: { p_sec: secLoop },
  });
  const rModel = translateRoomState({
    position: 70,
    workspace: {
      room: {
        department: "security",
        level: "S5",
        status: "working",
        crt: { target: "核查令牌权限", model: "m", protocol: "Responses", status: "进行中", cycle: 1 },
        roles: [{ id: "sec-1", name: "审校员", kind: "agent", status: "working", task: null }],
        pose: { role_id: "sec-1", action: "reading" },
        door: null,
        hold_card: null,
        mailbox: 0,
        summaries: 0,
        scrolls: 1,
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
    },
    department: "security",
    organization: secOrg as never,
  });

  const secSnap = await runInPage(
    async (input: { fModel: Record<string, unknown>; bModel: Record<string, unknown>; rModel: Record<string, unknown> }) => {
      const BuildingMod = await import(/* @vite-ignore */ "/src/pixel/building/view.ts" as string) as typeof import("../../src/pixel/building/view.ts");
      const FloorMod = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/pixel/floor/view.ts");
      const FloorDeclMod = await import(/* @vite-ignore */ "/src/pixel/world/floor-decl.ts" as string) as typeof import("../../src/pixel/world/floor-decl.ts");
      const RoomMod = await import(/* @vite-ignore */ "/src/pixel/room/view.ts" as string) as typeof import("../../src/pixel/room/view.ts");
      const RoomDeclMod = await import(/* @vite-ignore */ "/src/pixel/room/decl.ts" as string) as typeof import("../../src/pixel/room/decl.ts");
      const ClockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");

      const makeHost = (top: number): HTMLDivElement => {
        const el = document.createElement("div");
        el.style.cssText = `position:fixed;left:0;top:${top}px;width:640px;height:320px`;
        document.body.appendChild(el);
        return el;
      };
      const hB = makeHost(0);
      const hF = makeHost(330);
      const hR = makeHost(660);
      const clock = ClockMod.createManualClock();
      const advance = (ms: number): void => {
        const frames = Math.max(1, Math.round(ms / 50));
        for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
      };

      const bView = await BuildingMod.createBuildingView({ host: hB, clock });
      const fView = await FloorMod.createFloorView({ host: hF, clock });
      const rView = await RoomMod.createRoomView({ host: hR, clock, department: "security" });
      try {
        bView.jump(input.bModel as never);
        fView.jump(input.fModel as never);
        rView.jump(input.rModel as never);
        advance(250);

        const world = fView.inspect().driver.world;
        const secChar = Object.values(world.characters).find((c) => c.department === "security");
        const rInspected = rView.inspect();
        const rActor = rInspected.driver.actors()[0];
        const secApp = RoomDeclMod.roomAppearanceOf("security");
        return {
          bRooms: bView.inspect().channels().floors[0]?.rooms,
          fSecRoom: fView.inspect().channels().rooms.security,
          fCharSprite: secChar ? FloorDeclMod.characterSprite(secChar.department ?? "", secChar.roleKind) : null,
          rChannels: rInspected.channels(),
          rWallPalette: [secApp.shell.wall, secApp.shell.wall2, secApp.shell.wall3],
          rDesksCount: rInspected.driver.state.desks.length,
          rCharSprite: rActor ? RoomDeclMod.spriteForRole("security", rActor.role.kind) : null,
        };
      } finally {
        bView.destroy();
        fView.destroy();
        rView.destroy();
        hB.remove();
        hF.remove();
        hR.remove();
      }
    },
    { fModel, bModel, rModel },
  );

  assert.deepEqual(secSnap.bRooms, [
    { id: "engineering", label: "工程", lit: false },
    { id: "security", label: "安全审校", lit: true },
  ]);
  assert.equal(secSnap.fSecRoom.label, "安全审校");
  assert.equal(secSnap.fSecRoom.verifier, true);
  assert.ok(secSnap.fCharSprite?.startsWith("generic."), `未声明角色在楼层未使用通用精灵配色：${String(secSnap.fCharSprite)}`);
  assert.equal(secSnap.rChannels.department, "security");
  assert.equal(secSnap.rChannels.label, "安全审校");
  assert.equal(secSnap.rChannels.verifier, true);
  assert.deepEqual(secSnap.rWallPalette, ["#e4dfd3", "#d6d0c2", "#c7c0b0"]);
  assert.equal(secSnap.rDesksCount, 1);
  assert.ok(secSnap.rCharSprite?.startsWith("generic."), `未声明角色在房间未使用通用精灵配色：${String(secSnap.rCharSprite)}`);
});

// ---------------------------------------------------------------------------
// 画面层非场景声明文件零职能名扫描

/** 允许登记默认外观与默认精灵的场景声明文件（相对于 view/src）。 */
const SCENE_DECLARATION_FILES = new Set([
  "pixel/world/floor-decl.ts",
  "pixel/floor/render-decl.ts",
]);

/** 禁止出现在非声明文件代码里的默认四职能英文标识与中文名。 */
const FORBIDDEN_ROLE_NAME_RE = /product|engineering|quality|operations|产品|工程|质检|运维/i;

/** 提取 TypeScript 源文件剥离全部单行、多行与文档注释后的语法叶子词元（保留标识符、类型字面量、字符串与模板字面量）。 */
function nonCommentLeafTokens(file: string, text: string): { line: number; tokenText: string }[] {
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  const out: { line: number; tokenText: string }[] = [];
  const visit = (node: ts.Node): void => {
    const children = node.getChildren(sf);
    if (children.length === 0) {
      if (node.kind !== ts.SyntaxKind.EndOfFileToken) {
        const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
        out.push({ line, tokenText: node.getText(sf) });
      }
      return;
    }
    for (const child of children) {
      if (ts.isJSDoc(child)) continue;
      visit(child);
    }
  };
  visit(sf);
  return out;
}

function scanDepartmentNameHits(sources: readonly { file: string; text: string }[]): string[] {
  const hits: string[] = [];
  for (const { file, text } of sources) {
    if (SCENE_DECLARATION_FILES.has(file)) continue;
    for (const { line, tokenText } of nonCommentLeafTokens(file, text)) {
      const m = tokenText.match(FORBIDDEN_ROLE_NAME_RE);
      if (m) hits.push(`${file}:${line} 出现了职能名「${m[0]}」（词元：${tokenText}）`);
    }
  }
  return hits;
}

function collectNonDeclPixelSources(): { file: string; text: string }[] {
  const out: { file: string; text: string }[] = [];
  for (const subdir of ["pixel/world", "pixel/floor", "pixel/building"]) {
    const root = join(srcRoot, subdir);
    const walk = (dir: string): void => {
      for (const name of readdirSync(dir).sort()) {
        const full = join(dir, name);
        if (statSync(full).isDirectory()) {
          if (name === "generated") continue;
          walk(full);
          continue;
        }
        if (!/\.tsx?$/.test(name)) continue;
        const rel = relative(srcRoot, full).split(sep).join("/");
        if (SCENE_DECLARATION_FILES.has(rel)) continue;
        out.push({ file: rel, text: readFileSync(full, "utf8") });
      }
    };
    walk(root);
  }
  return out;
}

// 守 R2：画面层（world、floor、building）除两份场景声明文件以外，剥离注释后的代码零出现默认四职能名。
test("画面层非声明文件扫描：pixel/{world,floor,building} 剥离注释后零出现默认四职能标识与中文名", () => {
  for (const decl of SCENE_DECLARATION_FILES) {
    assert.ok(existsSync(join(srcRoot, decl)), `缺少场景声明文件 ${decl}`);
  }
  const sources = collectNonDeclPixelSources();
  assert.ok(sources.length >= 10, `扫描到的非声明文件数量过少：${sources.length}`);
  assert.deepEqual(scanDepartmentNameHits(sources), []);

  // 反向自检：注释中的职能名不报错，代码标识符、类型字面量、字符串与模板字面量中的职能名逐条报出
  const sampleHits = scanDepartmentNameHits([
    {
      file: "pixel/floor/sample-clean.ts",
      text: [
        "// 单行注释里的 product 与 质检",
        "/* 块注释里的 engineering 与 工程 */",
        "/** 文档注释里的 quality 与 运维 */",
        "export const count = 1; // 行尾注释 产品 operations",
      ].join("\n"),
    },
    {
      file: "pixel/floor/sample-bad.ts",
      text: [
        'type BadRole = "operations";',
        'const label = "质检";',
        "const msg = `送往 ${1} 产品`;",
        "const qualityRoom = 2;",
      ].join("\n"),
    },
  ]);
  assert.equal(sampleHits.length, 4, `反向自检命中数异常：\n${sampleHits.join("\n")}`);
  assert.ok(sampleHits.every((h) => h.startsWith("pixel/floor/sample-bad.ts:")));
});
