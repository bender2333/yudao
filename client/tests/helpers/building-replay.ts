// 首页楼的回放核对（工单 #178 验收标准 2）：把原型录下的调用序列送进客户端的楼画面，
// 按录下的固定时刻取状态，与原型录下的状态逐项比较：每层的灯、小旗、阀门、状态灯与决定计数，以及每层小人的位置、姿势与朝向。
//
// 录下的调用与状态记录在 tests/fixtures/building/recordings.json，只经 record-building-calls.mjs --write 更新。
// 这个模块输出比较结果，测试与命令行都调用它。

import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { BuildingView } from "../../src/renderer/src/pixel/building/view.ts";
import type { BuildingModel } from "../../src/renderer/src/pixel/world/building.ts";
import type { PixelFloorEvent } from "../../src/renderer/src/pixel/world/types.ts";
import type { Clock } from "../../src/renderer/src/pixel/clock.ts";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

/** 一层在画面上的状态元组：[项目标识, 状态灯, 四个部门的灯, 小旗, 阀门, 决定计数]。 */
export type RecordedFloor = [string, string, number[], [string, string, number][], number, number];

export interface RecordedSample {
  after: number;
  ms: number;
  state: {
    floors: RecordedFloor[];
    walkers: [string, number | null, number | null, string | null, number | null, number | null][];
  };
}

export interface RecordedScenario {
  id: string;
  name: string;
  level: string;
  ops: { op: string; arg?: unknown; model?: number }[];
  samples: RecordedSample[];
}

export interface BuildingRecordingFile {
  generatedFrom: string;
  sampleMs: number[];
  models: BuildingModel[];
  scenarios: RecordedScenario[];
}

export interface BuildingCompareResult {
  scenario: string;
  mismatches: string[];
  clientErrors: string[];
}

export function loadBuildingRecordings(): BuildingRecordingFile {
  return JSON.parse(readFileSync(join(clientRoot, "tests", "fixtures", "building", "recordings.json"), "utf8")) as BuildingRecordingFile;
}

/**
 * 在页面里运行的驱动：把调用序列送进客户端的楼画面，按固定时刻取状态。
 * 注册进页面以后由 replayBuildingScenario 调用（函数体在浏览器里执行，只能引用浏览器里可用的模块）。
 */
async function driver(input: { ops: RecordedScenario["ops"]; models: BuildingModel[]; sampleMs: number[] }): Promise<{ samples: RecordedSample[]; errors: string[] }> {
  // 驱动在浏览器里执行：这两个模块经开发服务器的绝对路径加载（Vite 在浏览器里提供它们，不能在 Node 里静态 import）
  const P = await import(/* @vite-ignore */ "/src/pixel/building/view.ts" as string) as { createBuildingView: (opts: { host: HTMLElement; clock: Clock }) => Promise<BuildingView> };
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as { createManualClock: () => Clock & { advance(toMs: number): void } };
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:9999;background:#000";
  document.body.appendChild(host);
  // 与录制时一致：楼的画面建立前把随机数复位到同一个起点，随机数用同一套播种的序列（seed=987654321）
  let seed = 987654321;
  Math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const clock = clockMod.createManualClock();
  const view = await P.createBuildingView({ host, clock });
  // 与录制时一致：关掉自主行为，静止的画面只由快照决定
  view.inspect().scene.autonomy = false;
  const errors: string[] = [];
  const origError = console.error;
  console.error = (...a: unknown[]): void => {
    errors.push(a.map(String).join(" "));
    origError.apply(console, a);
  };
  function snapshot(): RecordedSample["state"] {
    const { driver: d, scene } = view.inspect();
    const floors = d.model.floors.map((f) => [
      f.project_id,
      f.status,
      [f.lit.product ? 1 : 0, f.lit.engineering ? 1 : 0, f.lit.quality ? 1 : 0, f.lit.operations ? 1 : 0],
      f.flags.map((fl) => [fl.work_item_id, fl.department, fl.color_index] as [string, string, number]),
      f.valve_closed ? 1 : 0,
      f.decisions,
    ] as RecordedFloor);
    const walkers = Object.keys(d.world.characters).sort().map((id) => {
      const a = scene.actors.find((x) => x.id === "ch-" + id);
      return [id, a ? Math.round(a.x) : null, a ? Math.round(a.y) : null, a ? a.anim : null, a ? a.speed : null, a ? a.facing : null] as [string, number | null, number | null, string | null, number | null, number | null];
    });
    return { floors, walkers };
  }
  const samples: RecordedSample[] = [];
  // 与原型一致：按 50 毫秒一帧推进
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  for (let i = 0; i < input.ops.length; i++) {
    const op = input.ops[i];
    if (op.op === "mount") continue;
    if (op.op === "setModel") view.setModel(input.models[op.model as number]);
    else if (op.op === "playEvent") view.playEvent(op.arg as PixelFloorEvent);
    if (op.op === "setModel" || op.op === "playEvent") {
      for (const ms of input.sampleMs) {
        advance(ms);
        samples.push({ after: i, ms, state: snapshot() });
      }
    }
  }
  console.error = origError;
  view.destroy();
  host.remove();
  return { samples, errors };
}

/** 起一个渲染进程的开发服务器，把一个场景的调用序列送进楼的画面，返回取到的状态。 */
export async function replayBuildingScenario(serverUrl: string, scenario: RecordedScenario, models: BuildingRecordingFile["models"], sampleMs: number[]): Promise<{ samples: RecordedSample[]; errors: string[] }> {
  const browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
  try {
    const page = await browser.newPage();
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));
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
    }, { ops: scenario.ops, models, sampleMs });
    if ("failed" in result) {
      return { samples: [], errors: [...pageErrors, `驱动失败：${String(result.failed)}`] };
    }
    const ok = result.ok as { samples: RecordedSample[]; errors: string[] };
    return { samples: ok.samples, errors: [...pageErrors, ...ok.errors] };
  } finally {
    await browser.close();
  }
}

/** 比较两份状态：逐项列出不同（每层的灯、小旗、阀门、状态灯、决定计数与小人）。 */
export function compareBuildingStates(recorded: RecordedSample[], replayed: RecordedSample[]): string[] {
  const out: string[] = [];
  if (recorded.length !== replayed.length) {
    return [`样本数量不同：原型 ${recorded.length}，客户端 ${replayed.length}`];
  }
  for (let i = 0; i < recorded.length; i++) {
    const a = recorded[i];
    const b = replayed[i];
    if (a.after !== b.after || a.ms !== b.ms) {
      out.push(`样本 ${i} 的位置不同：原型 ${a.after}/${a.ms}，客户端 ${b.after}/${b.ms}`);
      continue;
    }
    const fa = new Map(a.state.floors.map((f) => [f[0], f]));
    const fb = new Map(b.state.floors.map((f) => [f[0], f]));
    for (const [pid, left] of fa) {
      const right = fb.get(pid);
      if (!right) {
        out.push(`样本 ${i}（${a.ms} 毫秒）缺少楼层 ${pid}`);
        continue;
      }
      const fields = ["状态灯", "四个部门的灯", "小旗", "阀门", "决定计数"];
      for (let k = 1; k <= 5; k++) {
        if (JSON.stringify(left[k]) !== JSON.stringify(right[k])) {
          out.push(`样本 ${i}（${a.ms} 毫秒）楼层 ${pid} 的${fields[k - 1]}不同：原型 ${JSON.stringify(left[k])}，客户端 ${JSON.stringify(right[k])}`);
        }
      }
    }
    const wa = new Map(a.state.walkers.map((w) => [w[0], w]));
    const wb = new Map(b.state.walkers.map((w) => [w[0], w]));
    for (const [id, left] of wa) {
      const right = wb.get(id);
      if (!right) {
        out.push(`样本 ${i}（${a.ms} 毫秒）缺少小人 ${id}`);
        continue;
      }
      const fields = ["x", "y", "姿势", "速度", "朝向"];
      for (let k = 1; k <= 5; k++) {
        if (JSON.stringify(left[k]) !== JSON.stringify(right[k])) {
          out.push(`样本 ${i}（${a.ms} 毫秒）小人 ${id} 的${fields[k - 1]}不同：原型 ${JSON.stringify(left[k])}，客户端 ${JSON.stringify(right[k])}`);
        }
      }
    }
  }
  return out;
}

/** 起一个开发服务器，回放录下的场景，返回每个场景的比较结果。 */
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
  const results: BuildingCompareResult[] = [];
  try {
    for (const scenario of recording.scenarios) {
      if (options.only && !options.only.includes(scenario.id)) continue;
      const replayed = await replayBuildingScenario(address, scenario, recording.models, recording.sampleMs);
      results.push({
        scenario: scenario.id,
        mismatches: compareBuildingStates(scenario.samples, replayed.samples),
        clientErrors: replayed.errors,
      });
    }
  } finally {
    await server.close();
  }
  return results;
}
