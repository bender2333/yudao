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
