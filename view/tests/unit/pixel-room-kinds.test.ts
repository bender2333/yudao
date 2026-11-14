// 房间陈设按声明外观与核验角色推出的单元测试（画面与播放 docs/design/visualization.md「画面跟着定义伸缩」「画面合同」「视觉通道表」「画面诚实性的不变式」，工单 #1384）。
//
// 守 docs/design/test-pyramid.md「测试按三环留」的 R2（画面合同 RoomState 的角色标识与检验台及出口托盘标记、房间非声明代码零职能名）
// 与 R3（默认三职能的三间屋事实层一致、把质检改名后仍是核验角色时保留检验台、去掉核验角色后全部房间无检验台）。

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { createServer, type ViteDevServer } from "vite";
import { chromium, type Browser } from "@playwright/test";

import { roomState as checkRoomState } from "../../src/pixel/contract.ts";
import { actions as roomActions, state as roomState } from "../../src/translate/room.ts";
import {
  FakeServer,
  fakeClock,
  fakeHost,
  fakeSurface,
  loadFixtures,
  recordingOf,
  responseOf,
  settle,
  shellFor,
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
    cacheDir: join(viewRoot, "node_modules", ".vite-pixel-room-kinds"),
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
    await page.route(address + "room-kinds.html", (route) => route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><html><head><meta charset=\"utf-8\"></head><body></body></html>",
    }));
    await page.goto(address + "room-kinds.html");
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

interface RoomCanvasReadout {
  channels: {
    position: number;
    department: string;
    label: string;
    verifier: boolean;
    exit_tray: boolean;
    status: { value: string; text: string };
    pose: { role_id: string | null; anim: string } | null;
    roles: { id: string; kind: string; status: string | null }[];
    objects: {
      mailbox: number;
      scrolls: number;
      summaries: number;
      pinned_notes: number;
      semantic_cards: number;
      letters_waiting: number;
    };
    stream: { role: string; text: string }[];
  };
  hasTrialSeat: boolean;
  drawnTexts: string[];
  /** 工作台区域（逻辑坐标 x: 298..388, y: 144..196）白色检验台面、灯臂、勾选框与木质台面像素计数。 */
  benchPixels: {
    whiteTopCount: number;
    lampSteelCount: number;
    checkBoxCount: number;
    nonVerifierTopCount: number;
  };
}

/** 浏览器内驱动：装载一间部门房间，读取事实通道、试用台座位、画布绘制文字与工作台区域像素。 */
async function inspectRoomInBrowser(input: {
  department: string;
  model: Record<string, unknown>;
}): Promise<RoomCanvasReadout> {
  const RoomMod = await import(/* @vite-ignore */ "/src/pixel/room/view.ts" as string) as typeof import("../../src/pixel/room/view.ts");
  const ClockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/pixel/clock.ts");
  const RegMod = await import(/* @vite-ignore */ "/src/pixel/registry.ts" as string) as typeof import("../../src/pixel/registry.ts");

  const hexRgb = (hex: string): [number, number, number] => {
    const clean = hex.replace("#", "");
    return [
      Number.parseInt(clean.slice(0, 2), 16),
      Number.parseInt(clean.slice(2, 4), 16),
      Number.parseInt(clean.slice(4, 6), 16),
    ];
  };
  const nearRgb = (r: number, g: number, b: number, target: [number, number, number], maxDiff = 38): boolean =>
    Math.abs(r - target[0]) + Math.abs(g - target[1]) + Math.abs(b - target[2]) <= maxDiff;
  const blendDark = (rgb: [number, number, number], dark: number): [number, number, number] => [
    Math.round(rgb[0] * (1 - dark) + 14 * dark),
    Math.round(rgb[1] * (1 - dark) + 12 * dark),
    Math.round(rgb[2] * (1 - dark) + 34 * dark),
  ];

  const rawWhite = hexRgb(RegMod.PAL.white);
  const rawInk = hexRgb(RegMod.PAL.ink);
  const rawWood1 = hexRgb(RegMod.PAL.wood1);
  const rawWood2 = hexRgb(RegMod.PAL.wood2);
  const rawMetal1 = hexRgb(RegMod.PAL.metal1);

  const drawnTexts: string[] = [];
  const origFillText = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (text: string, x: number, y: number, maxWidth?: number): void {
    drawnTexts.push(String(text));
    if (maxWidth !== undefined) origFillText.call(this, text, x, y, maxWidth);
    else origFillText.call(this, text, x, y);
  };

  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:480px;height:240px";
  document.body.appendChild(host);

  const clock = ClockMod.createManualClock();
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };

  let view: Awaited<ReturnType<typeof RoomMod.createRoomView>> | null = null;
  try {
    view = await RoomMod.createRoomView({
      host,
      clock,
      department: input.department,
      random: () => 0.5,
    });
    view.jump(input.model as never);
    drawnTexts.length = 0;
    advance(800);

    const inspected = view.inspect();
    const channels = inspected.channels() as unknown as RoomCanvasReadout["channels"];
    const hasTrialSeat = inspected.driver.state.trialSeat !== null;
    const dark = inspected.driver.state.dark;
    const palWhite = blendDark(rawWhite, dark);
    const palInk = blendDark(rawInk, dark);
    const palWood1 = blendDark(rawWood1, dark);
    const palWood2 = blendDark(rawWood2, dark);
    const palMetal1 = blendDark(rawMetal1, dark);

    // 单独将一帧直接绘制在 480×240 离屏 1x 画布上统计工作台区域像素，消除设备像素比缩放影响
    const offscreen = document.createElement("canvas");
    offscreen.width = 480;
    offscreen.height = 240;
    const ctx = offscreen.getContext("2d")!;
    inspected.renderer.draw(ctx);
    // 台面区域（x: 300..386, y: 170..176）与台面上方检验台灯罩描边区域（x: 359..370, y: 145..152）
    const topImg = ctx.getImageData(300, 170, 86, 6).data;
    const lampImg = ctx.getImageData(359, 145, 11, 7).data;

    let whiteTopCount = 0;
    let nonVerifierTopCount = 0;
    for (let i = 0; i < topImg.length; i += 4) {
      const r = topImg[i];
      const g = topImg[i + 1];
      const b = topImg[i + 2];
      if (nearRgb(r, g, b, palWhite, 20)) whiteTopCount += 1;
      if (nearRgb(r, g, b, palWood1, 24) || nearRgb(r, g, b, palWood2, 24) || nearRgb(r, g, b, palMetal1, 24)) {
        nonVerifierTopCount += 1;
      }
    }

    let lampSteelCount = 0;
    for (let i = 0; i < lampImg.length; i += 4) {
      const r = lampImg[i];
      const g = lampImg[i + 1];
      const b = lampImg[i + 2];
      if (nearRgb(r, g, b, palInk, 24)) lampSteelCount += 1;
    }

    // 读取检验板左侧区域（x: 304..320, y: 169..176）白色板面的像素数
    const checkImg = ctx.getImageData(304, 169, 16, 7).data;
    let checkBoxCount = 0;
    for (let i = 0; i < checkImg.length; i += 4) {
      const r = checkImg[i];
      const g = checkImg[i + 1];
      const b = checkImg[i + 2];
      if (nearRgb(r, g, b, palWhite, 20)) {
        checkBoxCount += 1;
      }
    }

    return {
      channels,
      hasTrialSeat,
      drawnTexts: drawnTexts.slice(),
      benchPixels: {
        whiteTopCount,
        lampSteelCount,
        checkBoxCount,
        nonVerifierTopCount,
      },
    };
  } finally {
    CanvasRenderingContext2D.prototype.fillText = origFillText;
    view?.destroy();
    host.remove();
  }
}

const REF_USER = { position: 2, source: "user" } as const;

// 守 R2 与 R3：默认三职能的三间房间事实层一致，合同校验角色标识、检验台与出口托盘字段。
test("默认三职能房间：三间屋的事实通道、工作台种类与壳层导航一致，合同校验新增字段", async () => {
  const fixtures = loadFixtures();
  const demo = recordingOf(fixtures, "demo");
  const loopResp = responseOf(demo, "project.loop", { project_id: demo.ids.project_id });

  const expectedByDept = {
    product: { label: "产品", verifier: false, exit_tray: false, benchLabel: "卷轴台", trialSeat: false },
    engineering: { label: "工程", verifier: false, exit_tray: false, benchLabel: "封存台", trialSeat: false },
    quality: { label: "质检", verifier: true, exit_tray: false, benchLabel: "检验台", trialSeat: true },
  } as const;

  for (const dept of ["product", "engineering", "quality"] as const) {
    const wsResp = responseOf(demo, "department.workspace", {
      project_id: demo.ids.project_id,
      department: dept,
      work_item: demo.ids.work_item_id,
    });
    const withLoop = roomState({
      position: wsResp.position,
      workspace: wsResp.data as never,
      department: dept,
      loop: loopResp.data as never,
      workItemId: demo.ids.work_item_id,
    });
    const legacyFallback = roomState({
      position: wsResp.position,
      workspace: wsResp.data as never,
    });
    assert.deepEqual(withLoop, legacyFallback, `${dept} 显式传入事项定义与默认三职能回退翻译结果须一致`);

    const exp = expectedByDept[dept];
    assert.equal(withLoop.department, dept);
    assert.equal(withLoop.label, exp.label);
    assert.equal(withLoop.verifier, exp.verifier);
    assert.equal(withLoop.exit_tray, exp.exit_tray);

    const readout = await runInPage<RoomCanvasReadout>(
      inspectRoomInBrowser as unknown as (input: never) => Promise<RoomCanvasReadout>,
      { department: dept, model: withLoop },
    );
    assert.equal(readout.channels.department, dept);
    assert.equal(readout.channels.label, exp.label);
    assert.equal(readout.channels.verifier, exp.verifier);
    assert.equal(readout.channels.exit_tray, exp.exit_tray);
    assert.equal(readout.hasTrialSeat, exp.trialSeat && withLoop.level === "S5");
    assert.ok(readout.drawnTexts.includes(exp.label), `${dept} 门顶未绘制职能显示名「${exp.label}」`);
    assert.ok(readout.drawnTexts.includes(`${exp.label} CRT`), `${dept} 屏幕未绘制「${exp.label} CRT」`);
    assert.ok(readout.drawnTexts.includes(exp.benchLabel), `${dept} 工作台未绘制「${exp.benchLabel}」`);
    if (exp.verifier) {
      assert.ok(readout.benchPixels.whiteTopCount > 200, `质检房间检验台须绘制白色台面（实得 ${readout.benchPixels.whiteTopCount}）`);
      assert.ok(readout.benchPixels.lampSteelCount >= 18, `质检房间检验台须绘制检验台灯罩描边（实得 ${readout.benchPixels.lampSteelCount}）`);
      assert.ok(readout.benchPixels.checkBoxCount > 30, `质检房间检验台须绘制白色检验单板面（实得 ${readout.benchPixels.checkBoxCount}）`);
      assert.equal(readout.benchPixels.nonVerifierTopCount, 0, `质检房间检验台不画非核验台面（实得 ${readout.benchPixels.nonVerifierTopCount}）`);
    } else {
      assert.equal(readout.benchPixels.whiteTopCount, 0, `${dept} 非核验房间工作台不画白色检验台面（实得 ${readout.benchPixels.whiteTopCount}）`);
      assert.equal(readout.benchPixels.lampSteelCount, 0, `${dept} 非核验房间工作台不画检验台灯臂（实得 ${readout.benchPixels.lampSteelCount}）`);
      assert.equal(readout.benchPixels.checkBoxCount, 0, `${dept} 非核验房间工作台不画白色检验单板面（实得 ${readout.benchPixels.checkBoxCount}）`);
      assert.ok(readout.benchPixels.nonVerifierTopCount > 150, `${dept} 非核验房间工作台须绘制专属台面（实得 ${readout.benchPixels.nonVerifierTopCount}）`);
    }
  }

  // 经 Shell 进入房间，核对 project.loop 订阅把核验角色标记与面包屑送到房间画面
  const srv = new FakeServer(fixtures, "demo");
  const surface = fakeSurface();
  const shell = shellFor(srv);
  await shell.open("http://view.test", "");
  shell.goFloor(demo.ids.project_id, demo.ids.work_item_id);
  shell.goRoom("quality");
  const detach = shell.attachHost(fakeHost, fakeClock, async () => surface);
  try {
    await settle();
    const lastModel = (surface.states.at(-1) ?? surface.jumped.at(-1)) as {
      department?: string; label?: string; verifier?: boolean; exit_tray?: boolean;
    } | undefined;
    assert.ok(lastModel, "进入房间后壳层须把房间状态推上画面");
    assert.equal(lastModel.department, "quality");
    assert.equal(lastModel.label, "质检");
    assert.equal(lastModel.verifier, true);
    assert.equal(lastModel.exit_tray, false);
    assert.equal(shell.state.crumbs.at(-1)?.label, "质检");
  } finally {
    detach();
    shell.close();
  }

  // 画面合同对新增可选字段的类型校验
  assert.throws(
    () => checkRoomState({ position: 1, status: "idle", roles: [], department: "" }),
    /房间的角色标识/,
  );
  assert.throws(
    () => checkRoomState({ position: 1, status: "idle", roles: [], verifier: "yes" as unknown as boolean }),
    /房间的核验角色标记/,
  );
  assert.throws(
    () => checkRoomState({ position: 1, status: "idle", roles: [], exit_tray: 1 as unknown as boolean }),
    /房间的出口托盘标记/,
  );
  assert.throws(
    () => checkRoomState({ position: 1, status: "idle", roles: [], label: 42 as unknown as string }),
    /房间的显示名/,
  );
});

// 守 R2 与 R3：把质检改名但仍是核验角色的定义下该屋有检验台；把核验角色去掉的定义下全部房间无检验台。
test("核验角色伸缩：质检改名为审计但仍是核验角色时该屋有检验台，去掉核验角色后全部房间无检验台", async () => {
  // 1. 把质检改名为 audit（「审计」）且保持为核验角色的定义
  const auditVerifierOrg = {
    form: "three_roles_audited",
    routing: "watched_outputs",
    entry: { id: "product", label: "产品", ref: REF_USER },
    roles: [
      { id: "product", label: "产品", ref: REF_USER },
      { id: "engineering", label: "工程", ref: REF_USER },
      { id: "audit", label: "审计", ref: REF_USER },
    ],
    verifiers: [
      {
        role: "audit",
        verifies: [{ role: "engineering", outcomes: ["code_bundle"] }],
        ref: REF_USER,
      },
    ],
    completing: null,
    watched: [
      { source: "product", recipient: "engineering", outcome: "product_spec", ref: REF_USER },
      { source: "engineering", recipient: "audit", outcome: "code_bundle", ref: REF_USER },
    ],
    asks: [
      { requester: "audit", recipient: "engineering", ref: REF_USER },
    ],
    rejections: [
      { verifier: "audit", role: "engineering", outcome: "code_bundle", ref: REF_USER },
    ],
  };

  const auditWorkspace = {
    project_id: "p_audit",
    department: "audit",
    status: "working",
    active_work_items: ["w_audit"],
    pending_inbound_asks: 0,
    room: {
      department: "audit",
      level: "S5",
      status: "working",
      roles: [
        { id: "audit-lead", kind: "tester", name: "主审", status: "working" },
        { id: "audit-mgr", kind: "manager", name: "主管", status: "idle" },
      ],
    },
  };

  const auditState = roomState({
    position: 42,
    workspace: auditWorkspace,
    department: "audit",
    organization: auditVerifierOrg as never,
  });
  assert.equal(auditState.department, "audit");
  assert.equal(auditState.label, "审计");
  assert.equal(auditState.verifier, true);
  assert.equal(auditState.exit_tray, false);

  const auditReadout = await runInPage<RoomCanvasReadout>(
    inspectRoomInBrowser as unknown as (input: never) => Promise<RoomCanvasReadout>,
    { department: "audit", model: auditState },
  );
  assert.equal(auditReadout.channels.department, "audit");
  assert.equal(auditReadout.channels.label, "审计");
  assert.equal(auditReadout.channels.verifier, true);
  assert.equal(auditReadout.channels.exit_tray, false);
  assert.equal(auditReadout.hasTrialSeat, true, "核验角色房间在 S5 档位须配备试用台座位");
  assert.ok(auditReadout.drawnTexts.includes("审计"), `门顶未绘制「审计」：${auditReadout.drawnTexts.join(" | ")}`);
  assert.ok(auditReadout.drawnTexts.includes("审计 CRT"), `屏幕未绘制「审计 CRT」：${auditReadout.drawnTexts.join(" | ")}`);
  assert.ok(auditReadout.drawnTexts.includes("检验台"), `核验角色审计屋未绘制「检验台」：${auditReadout.drawnTexts.join(" | ")}`);
  assert.ok(!auditReadout.drawnTexts.includes("工作台"), "核验角色审计屋不应把检验台画成普通工作台");
  assert.ok(auditReadout.benchPixels.whiteTopCount > 200, `审计屋检验台须绘制白色检验台面（实得 ${auditReadout.benchPixels.whiteTopCount}）`);
  assert.ok(auditReadout.benchPixels.lampSteelCount >= 18, `审计屋检验台须绘制检验台灯罩描边（实得 ${auditReadout.benchPixels.lampSteelCount}）`);
  assert.ok(auditReadout.benchPixels.checkBoxCount > 30, `审计屋检验台须绘制白色检验单板面（实得 ${auditReadout.benchPixels.checkBoxCount}）`);
  assert.equal(auditReadout.benchPixels.nonVerifierTopCount, 0, `审计屋检验台不画非核验台面（实得 ${auditReadout.benchPixels.nonVerifierTopCount}）`);

  // 翻译动作：核验角色改名为 audit 后，工程交出交付与核验盖章归档动作在 audit 房间正常生成
  const deliveryIntoAudit = roomActions(
    {
      position: 43,
      type: "delivery_accepted",
      department: "engineering",
      work_item_id: "w_audit",
      payload: {},
    },
    "audit",
    { organization: auditVerifierOrg as never },
  );
  assert.equal(deliveryIntoAudit.length, 1);
  assert.equal(deliveryIntoAudit[0].kind, "handoff");
  assert.equal(deliveryIntoAudit[0].from, "engineering");
  assert.equal(deliveryIntoAudit[0].to, "audit");

  const stampInAudit = roomActions(
    {
      position: 44,
      type: "qa_submitted",
      department: "audit",
      work_item_id: "w_audit",
      payload: { verdict: "release" },
    },
    "audit",
    { organization: auditVerifierOrg as never },
  );
  assert.deepEqual(stampInAudit.map((a) => a.kind), ["stamp_release", "handoff"]);
  assert.equal(stampInAudit[1].from, "audit");
  assert.equal(stampInAudit[1].to, "library");

  // 2. 把核验角色去掉的定义（verifiers 为空，含开环完成角色，甚至保留名为 quality 的非核验角色）
  const noVerifierOrg = {
    form: "open_completion",
    routing: "watched_outputs",
    entry: { id: "product", label: "产品", ref: REF_USER },
    roles: [
      { id: "product", label: "产品", ref: REF_USER },
      { id: "engineering", label: "工程", ref: REF_USER },
      { id: "audit", label: "审计", ref: REF_USER },
      { id: "quality", label: "质检", ref: REF_USER },
    ],
    verifiers: [],
    completing: { id: "engineering", label: "工程", ref: REF_USER },
    watched: [
      { source: "product", recipient: "engineering", outcome: "product_spec", ref: REF_USER },
    ],
    asks: [],
    rejections: [],
  };

  for (const role of noVerifierOrg.roles) {
    const ws = {
      project_id: "p_open",
      department: role.id,
      status: "idle",
      active_work_items: ["w_open"],
      pending_inbound_asks: 0,
      room: { department: role.id, level: "S5", status: "idle", roles: [] },
    };
    const st = roomState({
      position: 60,
      workspace: ws,
      department: role.id,
      organization: noVerifierOrg as never,
    });
    assert.equal(st.verifier, false, `去掉核验角色后，房间 ${role.id} 的 verifier 必须为 false`);
    assert.equal(st.exit_tray, role.id === "engineering");

    const readout = await runInPage<RoomCanvasReadout>(
      inspectRoomInBrowser as unknown as (input: never) => Promise<RoomCanvasReadout>,
      { department: role.id, model: st },
    );
    assert.equal(readout.channels.verifier, false, `去掉核验角色后，房间 ${role.id} 的通道 verifier 必须为 false`);
    assert.equal(readout.hasTrialSeat, false, `去掉核验角色后，房间 ${role.id} 不设试用台座位`);
    assert.ok(
      !readout.drawnTexts.includes("检验台"),
      `去掉核验角色后，房间 ${role.id} 画布不应出现「检验台」，实际：${readout.drawnTexts.join(" | ")}`,
    );
    assert.equal(readout.benchPixels.whiteTopCount, 0, `去掉核验角色后，房间 ${role.id} 不画白色检验台面（实得 ${readout.benchPixels.whiteTopCount}）`);
    assert.equal(readout.benchPixels.lampSteelCount, 0, `去掉核验角色后，房间 ${role.id} 不画检验台灯臂（实得 ${readout.benchPixels.lampSteelCount}）`);
    assert.equal(readout.benchPixels.checkBoxCount, 0, `去掉核验角色后，房间 ${role.id} 不画白色检验单板面（实得 ${readout.benchPixels.checkBoxCount}）`);
    assert.ok(readout.benchPixels.nonVerifierTopCount > 150, `去掉核验角色后，房间 ${role.id} 绘制普通工作台面（实得 ${readout.benchPixels.nonVerifierTopCount}）`);
  }
});

// ---------------------------------------------------------------------------
// 房间模块非声明文件零职能名扫描

/** 房间目录下唯一允许登记默认四职能房间外观的声明文件（相对于 view/src）。 */
const ROOM_DECLARATION_FILES = new Set([
  "pixel/room/decl.ts",
]);

/** 禁止出现在房间非声明文件代码里的默认四职能英文标识与中文名。 */
const FORBIDDEN_ROLE_NAME_RE = /product|engineering|quality|operations|产品|工程|质检|运维/i;

/** 提取 TypeScript 源文件剥离全部单行、多行与文档注释后的语法叶子词元。 */
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

function scanRoomDepartmentNameHits(sources: readonly { file: string; text: string }[]): string[] {
  const hits: string[] = [];
  for (const { file, text } of sources) {
    if (ROOM_DECLARATION_FILES.has(file)) continue;
    for (const { line, tokenText } of nonCommentLeafTokens(file, text)) {
      const m = tokenText.match(FORBIDDEN_ROLE_NAME_RE);
      if (m) hits.push(`${file}:${line} 出现了职能名「${m[0]}」（词元：${tokenText}）`);
    }
  }
  return hits;
}

function collectNonDeclRoomSources(): { file: string; text: string }[] {
  const out: { file: string; text: string }[] = [];
  const roomRoot = join(srcRoot, "pixel/room");
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir).sort()) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) {
        walk(full);
        continue;
      }
      if (!/\.tsx?$/.test(name)) continue;
      const rel = relative(srcRoot, full).split(sep).join("/");
      if (ROOM_DECLARATION_FILES.has(rel)) continue;
      out.push({ file: rel, text: readFileSync(full, "utf8") });
    }
  };
  walk(roomRoot);
  return out;
}

// 守 R2：view/src/pixel/room/ 下除 decl.ts 以外的全部文件剥离注释后的代码零出现默认四职能标识与中文名。
test("房间非声明文件扫描：pixel/room/ 除 decl.ts 外剥离注释后零出现默认四职能标识与中文名", () => {
  for (const decl of ROOM_DECLARATION_FILES) {
    assert.ok(existsSync(join(srcRoot, decl)), `缺少房间声明文件 ${decl}`);
  }
  const sources = collectNonDeclRoomSources();
  assert.ok(sources.length >= 7, `扫描到的房间非声明文件数量过少：${sources.length}`);
  assert.deepEqual(scanRoomDepartmentNameHits(sources), []);

  // 反向自检：注释里的职能名忽略，代码里的标识符、类型字面量、字符串与模板字面量逐条命中
  const sampleHits = scanRoomDepartmentNameHits([
    {
      file: "pixel/room/sample-clean.ts",
      text: [
        "// 单行注释里的 product 与 质检",
        "/* 块注释里的 engineering 与 工程 */",
        "/** 文档注释里的 quality 与 运维 */",
        "export const flag = true; // 行尾注释 产品 operations",
      ].join("\n"),
    },
    {
      file: "pixel/room/sample-bad.ts",
      text: [
        'type BadDept = "quality";',
        'const bench = "工程";',
        "const title = `${1} 运维`;",
        "const productDesk = 3;",
      ].join("\n"),
    },
  ]);
  assert.equal(sampleHits.length, 4, `反向自检命中数异常：\n${sampleHits.join("\n")}`);
  assert.ok(sampleHits.every((h) => h.startsWith("pixel/room/sample-bad.ts:")));
});
