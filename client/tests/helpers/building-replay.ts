// 首页楼的回放核对（工单 #957 验收标准 2）：把原型 v13 的页面上录下的调用送进客户端的楼画面，
// 静置到时间线放空（最后一个检查点），与 v13 的画面逐像素、逐个小人比较。
//
// 录下的调用是在 docs/prototypes/v13 的页面上录的（client/scripts/record-building-calls.mjs）：
// 状态是 v13 的翻译层从 projects.list 与各项目的 project.loop 翻好、交给画面的画面合同状态，
// 事件是页面收到的原始事件。回放时事件经客户端的翻译层（src/translate/building.ts）翻成动作。
//
// 录下的调用序列在 tests/fixtures/building/recordings.json，只经 record-building-calls.mjs --write 更新。
// 回放测试不进 CI（AGENTS.md「执行者」），按本文件底的命令单独运行。

import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import type { Browser } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compareActors, diffPixels, launch, v13Checkpoint, type ActorShot, type CheckpointShot, type PixelDiff, type RecordedOp } from "./prototype-v13.ts";
import type { BuildingModel } from "../../src/renderer/src/pixel/world/building.ts";
import type { BuildingEvent } from "../../src/renderer/src/translate/building.ts";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

export interface RecordedScenario {
  id: string;
  name: string;
  level: string;
  ops: RecordedOp[];
}

export interface BuildingRecordingFile {
  generatedFrom: string;
  gapMs: { event: number; other: number };
  settleMs: number;
  scenarios: RecordedScenario[];
}

export interface BuildingCompareResult {
  scenario: string;
  pixelDiff: PixelDiff;
  actorMismatches: string[];
  mismatches: string[];
  clientErrors: string[];
}

export function loadBuildingRecordings(): BuildingRecordingFile {
  return JSON.parse(readFileSync(join(clientRoot, "tests", "fixtures", "building", "recordings.json"), "utf8")) as BuildingRecordingFile;
}

/**
 * 在页面里运行的驱动：把录下的调用送进客户端的楼画面，静置到时间线放空，固定小人的动画计时，
 * 取画布与逐个小人。函数体在浏览器里执行，只能引用浏览器里可用的模块。
 */
async function driver(input: {
  ops: RecordedOp[];
  gapMs: { event: number; other: number };
  settleMs: number;
}): Promise<{ png: string; actors: ActorShot[]; size: [number, number]; errors: string[] }> {
  const P = await import(/* @vite-ignore */ "/src/pixel/building/view.ts" as string) as typeof import("../../src/renderer/src/pixel/building/view.ts");
  const tr = await import(/* @vite-ignore */ "/src/translate/building.ts" as string) as typeof import("../../src/renderer/src/translate/building.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/renderer/src/pixel/clock.ts");
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:640px;z-index:9999;background:#000";
  document.body.appendChild(host);
  let seed = 987654321;
  Math.random = (): number => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const clock = clockMod.createManualClock();
  let view = await P.createBuildingView({ host, clock });
  view.inspect().scene.autonomy = false;
  const errors: string[] = [];
  const origError = console.error;
  console.error = (...a: unknown[]): void => {
    errors.push(a.map(String).join(" "));
    origError.apply(console, a);
  };
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  for (const op of input.ops) {
    try {
      if (op.op === "mount") {
        view.destroy();
        view = await P.createBuildingView({ host, clock });
        view.inspect().scene.autonomy = false;
        advance(input.gapMs.other);
        continue;
      }
      if (op.op === "state") {
        const state = op.arg as unknown as BuildingModel;
        if (op.jump) view.jump(state);
        else view.setState(state);
      } else if (op.op === "event") {
        const raw = (op.arg ?? {}) as Record<string, unknown>;
        const ev: BuildingEvent = {
          type: String(raw.type ?? ""),
          position: Number(raw.position ?? 0),
          project_id: (raw.project_id as string) ?? null,
          department: (raw.department as string) ?? null,
          work_item_id: (raw.work_item_id as string) ?? null,
          payload: (raw.payload as Record<string, unknown>) ?? null,
        };
        for (const action of tr.buildingActions(ev)) view.play(action);
      }
      // destroy：最后一个检查点要在画面上取，销毁画面的调用不执行
    } catch (e) {
      errors.push(String((e as Error)?.message ?? e));
    }
    advance(op.op === "event" ? input.gapMs.event : input.gapMs.other);
  }
  advance(input.settleMs);
  const scene = view.inspect().scene;
  const list = scene.actors.slice().sort((a, b) => (a.sprite < b.sprite ? -1 : 1));
  list.forEach((a, i) => { a.clock = 5000; a.animStart = 0; a.seed = 100 + i; });
  scene.animT = 20000;
  view.resize();
  const canvas = host.querySelector("canvas");
  if (!canvas) return { png: "", actors: [], size: [0, 0], errors: [...errors, "画面上没有画布"] };
  const actors: ActorShot[] = list.map((a) => ({
    sprite: a.sprite, x: Math.round(a.x * 100) / 100, y: Math.round(a.y * 100) / 100, seat: Boolean(a.seat),
    anim: a.anim, facing: a.facing, icon: a.icon ? { kind: a.icon.kind, text: a.icon.text ?? null } : null,
    visible: a.visible, dim: a.dim, hold: a.hold ?? null, sign: a.sign ?? null, script: Boolean(a.script),
  }));
  console.error = origError;
  view.destroy();
  host.remove();
  return { png: canvas.toDataURL("image/png"), actors, size: [canvas.width, canvas.height], errors };
}

/** 起一个渲染进程的开发服务器，把一段录制送进客户端的楼画面，取最后一个检查点。 */
export async function replayBuildingScenario(serverUrl: string, browser: Browser, scenario: RecordedScenario, recording: BuildingRecordingFile): Promise<CheckpointShot> {
  const page = await browser.newPage();
  try {
    await page.goto(serverUrl + "index.html");
    await page.evaluate((fnSource) => {
      (window as unknown as { __buildingDriver: unknown }).__buildingDriver = (0, eval)(`(${fnSource})`);
    }, driver.toString());
    const result = await page.evaluate(async (input) => {
      try {
        const fn = (window as unknown as { __buildingDriver: (i: typeof input) => Promise<unknown> }).__buildingDriver;
        return { ok: await fn(input) };
      } catch (e) {
        return { failed: String((e as Error)?.stack ?? e) };
      }
    }, { ops: scenario.ops, gapMs: recording.gapMs, settleMs: recording.settleMs });
    if ("failed" in result) {
      return { png: "", actors: [], size: [0, 0], errors: [`驱动失败：${String(result.failed)}`] };
    }
    return result.ok as CheckpointShot;
  } finally {
    await page.close();
  }
}

/** 起开发服务器与浏览器，回放录下的场景，返回每个场景的比较结果。 */
export async function replayBuildingAll(options: { only?: string[] } = {}): Promise<BuildingCompareResult[]> {
  const recording = loadBuildingRecordings();
  const server = await createServer({
    root: join(clientRoot, "src", "renderer"),
    plugins: [react()],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
  });
  await server.listen();
  const address = server.resolvedUrls?.local[0];
  if (!address) throw new Error("渲染进程的开发服务器没有给出地址");
  const { browser, proto, diff } = await launch();
  const results: BuildingCompareResult[] = [];
  try {
    for (const scenario of recording.scenarios) {
      if (options.only && !options.only.includes(scenario.id)) continue;
      // 地下室（机房）属于 3.2C，客户端的楼不画（设计说明第 8.1 节的视觉通道表里没有它）：
      // 两边都按不留地下室的位置比较，比较的是每层的灯、小旗、阀门与小人
      const ops = scenario.ops.map((op) => (op.op === "state"
        ? { ...op, arg: { ...(op.arg as Record<string, unknown>), show_basement: false } }
        : op));
      const expected = await v13Checkpoint(proto, { screen: "building", ops, gapMs: recording.gapMs, settleMs: recording.settleMs });
      const actual = await replayBuildingScenario(address, browser, { ...scenario, ops }, recording);
      const actorMismatches = compareActors(expected.actors, actual.actors);
      const mismatches: string[] = [...actorMismatches];
      let pixelDiff: PixelDiff = { count: 0 };
      if (expected.png && actual.png) {
        pixelDiff = await diffPixels(diff, expected.png, actual.png);
        if (pixelDiff.count < 0) mismatches.push(`画布尺寸不同：v13 ${JSON.stringify(pixelDiff.size)}`);
      }
      results.push({
        scenario: scenario.id,
        pixelDiff,
        actorMismatches,
        mismatches,
        clientErrors: [...expected.errors, ...actual.errors],
      });
    }
  } finally {
    await browser.close();
    await server.close();
  }
  return results;
}
