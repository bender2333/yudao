// 楼层画面的回放核对（工单 #82 验收标准 2）：把原型录下的调用序列送进客户端的画面，
// 按录下的固定时刻取状态，与原型录下的状态逐项比较：每个角色的任务、姿势与头顶的话，
// 每个包裹的去向，每根管道的状态与各个信号。
//
// 录下的调用与状态记录在 tests/fixtures/floor/recordings.json，只经 record-floor-calls.mjs --write 更新。
// 这个模块输出比较结果，测试与命令行都调用它。

import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { adaptRecordedArg } from "./recorded-tool-names.ts";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

export interface RecordedSample {
  after: number;
  ms: number;
  state: {
    chars: [string, string | null, string[], string | null, string | null, string | null, number | null, number | null, boolean | null, boolean | null][];
    packages: [string, string, [number, number] | null][];
    pipes: [string, string | null, number | null][];
    signals: string[];
  };
}

export interface RecordedScenario {
  id: string;
  name: string;
  project: string;
  ops: { op: string; arg?: unknown; model?: number }[];
  samples: RecordedSample[];
}

export interface RecordingFile {
  generatedFrom: string;
  sampleMs: number[];
  models: Record<string, unknown>[];
  scenarios: RecordedScenario[];
}

export interface CompareResult {
  scenario: string;
  mismatches: string[];
  clientErrors: string[];
}

export function loadRecordings(): RecordingFile {
  return JSON.parse(readFileSync(join(clientRoot, "tests", "fixtures", "floor", "recordings.json"), "utf8")) as RecordingFile;
}

/**
 * 在页面里运行的驱动：把调用序列送进客户端的画面，按固定时刻取状态。
 * 注册进页面以后由 replayScenario 调用（函数体在浏览器里执行，只能引用浏览器里可用的模块）。
 */
async function driver(input: { ops: RecordedScenario["ops"]; models: Record<string, unknown>[]; sampleMs: number[] }): Promise<{ samples: RecordedSample[]; errors: string[] }> {
  // 驱动在浏览器里执行：这两个模块经开发服务器的绝对路径加载（不在 Node 的类型系统里）
  const P = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/renderer/src/pixel/floor/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/renderer/src/pixel/clock.ts");
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:9999;background:#000";
  document.body.appendChild(host);
  const clock = clockMod.createManualClock();
  const view = await P.createFloorView({ host, clock });
  // 与录制时一致：关掉自主行为（待机活动与管道的惯性），静止的画面只由快照决定
  view.inspect().scene.autonomy = false;
  const errors: string[] = [];
  const origError = console.error;
  console.error = (...a: unknown[]): void => {
    errors.push(a.map(String).join(" "));
    origError.apply(console, a);
  };
  function snapshot(): RecordedSample["state"] & { realT: number } {
    const world = view.inspect().driver.world;
    const scene = view.inspect().scene;
    const chars = Object.values(world.characters).sort((a, b) => (a.id < b.id ? -1 : 1)).map((c) => {
      const a = scene.actors.find((x) => x.id === "ch-" + c.id);
      return [c.id, c.current ? c.current.taskKey : null, c.queue.map((x) => x.taskKey), a ? a.anim : null,
        a && a.icon ? a.icon.kind : null, c.bubble ? c.bubble.text : null, a ? Math.round(a.x) : null,
        a ? Math.round(a.y) : null, a ? Boolean(a.seat) : null, a ? a.visible : null];
    });
    const packages = Object.values(world.packages).map((pk) => [pk.id, pk.transit ? pk.transit.linkKey : "rest",
      pk.transit && pk.transit.pos ? [Math.round(pk.transit.pos[0]), Math.round(pk.transit.pos[1])] : null] as [string, string, [number, number] | null])
      .sort((a, b) => (a[0] < b[0] ? -1 : 1));
    const pipes = Object.keys(world.links).sort().map((key) => [key,
      world.links[key].flow ? world.links[key].flow.state : null,
      world.links[key].flow ? Math.round(world.links[key].flow.load * 10) / 10 : null] as [string, string | null, number | null]);
    const signals = Object.keys(world.signals).sort().filter((name) => world.signals[name].until > scene.realT);
    return { chars: chars as never, packages, pipes, signals, realT: Math.round(scene.realT * 100) / 100 };
  }
  const samples: RecordedSample[] = [];
  // 与原型一致：按 50 毫秒一帧推进（原型的 step 把 0 毫秒也算作一帧）
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  for (let i = 0; i < input.ops.length; i++) {
    const op = input.ops[i];
    if (op.op === "mount") continue;
    if (op.op === "setModel") view.setModel(input.models[op.model as number] as never);
    else if (op.op === "playEvent") view.playEvent(op.arg as never);
    else if (op.op === "focus") view.focus(op.arg as string | null);
    else if (op.op === "setOverlay") view.setOverlay((op.arg as { id: string }).id, (op.arg as { data: unknown }).data);
    // 与原型一致：只在 setModel、playEvent、focus 之后取状态
    if (op.op === "setModel" || op.op === "playEvent" || op.op === "focus") {
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

/** 起一个渲染进程的开发服务器，把一个场景的调用序列送进画面，返回取到的状态。 */
export async function replayScenario(serverUrl: string, scenario: RecordedScenario, models: Record<string, unknown>[], sampleMs: number[]): Promise<{ samples: RecordedSample[]; errors: string[] }> {
  const browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
  try {
    const page = await browser.newPage();
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));
    await page.goto(serverUrl + "index.html");
    // 驱动注册进页面：evaluate 只送参数，函数体在浏览器里执行
    await page.evaluate((fnSource) => {
      (window as unknown as { __floorDriver: unknown }).__floorDriver = (0, eval)(`(${fnSource})`);
    }, driver.toString());
    const result = await page.evaluate(async (input) => {
      try {
        const fn = (window as unknown as { __floorDriver: (i: typeof input) => Promise<unknown> }).__floorDriver;
        return { ok: await fn(input) };
      } catch (e) {
        return { failed: String((e as Error)?.stack ?? e) };
      }
    }, { ops: scenario.ops.map((op) => ({ ...op, arg: adaptRecordedArg(op.arg) })), models, sampleMs });
    if ("failed" in result) {
      return { samples: [], errors: [...pageErrors, `驱动失败：${String(result.failed)}`] };
    }
    const ok = result.ok as { samples: RecordedSample[]; errors: string[] };
    return { samples: ok.samples, errors: [...pageErrors, ...ok.errors] };
  } finally {
    await browser.close();
  }
}

/** 比较两份状态：逐项列出不同（角色的任务/姿势/话、包裹的去向、管道的状态、信号）。 */
export function compareStates(recorded: RecordedSample[], replayed: RecordedSample[]): string[] {
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
    // 角色：任务、姿势、头顶的话、位置与是否坐在工位
    const ca = new Map(a.state.chars.map((c) => [c[0], c]));
    const cb = new Map(b.state.chars.map((c) => [c[0], c]));
    for (const [id, left] of ca) {
      const right = cb.get(id);
      if (!right) {
        out.push(`样本 ${i}（${a.ms} 毫秒）缺少角色 ${id}`);
        continue;
      }
      const fields = ["任务", "队列", "姿势", "图标", "头顶的话", "x", "y", "坐着", "可见"];
      for (let k = 1; k <= 9; k++) {
        if (JSON.stringify(left[k]) !== JSON.stringify(right[k])) {
          out.push(`样本 ${i}（${a.ms} 毫秒）角色 ${id} 的${fields[k - 1]}不同：原型 ${JSON.stringify(left[k])}，客户端 ${JSON.stringify(right[k])}`);
        }
      }
    }
    // 包裹：去向与位置
    const pkA = JSON.stringify(a.state.packages);
    const pkB = JSON.stringify(b.state.packages);
    if (pkA !== pkB) out.push(`样本 ${i}（${a.ms} 毫秒）包裹不同：原型 ${pkA}，客户端 ${pkB}`);
    // 管道：状态与光点
    const pipeA = JSON.stringify(a.state.pipes);
    const pipeB = JSON.stringify(b.state.pipes);
    if (pipeA !== pipeB) out.push(`样本 ${i}（${a.ms} 毫秒）管道不同：原型 ${pipeA}，客户端 ${pipeB}`);
    // 信号
    if (JSON.stringify(a.state.signals) !== JSON.stringify(b.state.signals)) {
      out.push(`样本 ${i}（${a.ms} 毫秒）信号不同：原型 ${JSON.stringify(a.state.signals)}，客户端 ${JSON.stringify(b.state.signals)}`);
    }
  }
  return out;
}

/** 起一个开发服务器，回放全部录下的场景，返回每个场景的比较结果。 */
export async function replayAll(options: { only?: string[] } = {}): Promise<CompareResult[]> {
  const recording = loadRecordings();
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
  const results: CompareResult[] = [];
  try {
    for (const scenario of recording.scenarios) {
      if (options.only && !options.only.includes(scenario.id)) continue;
      const replayed = await replayScenario(address, scenario, recording.models, recording.sampleMs);
      results.push({
        scenario: scenario.id,
        mismatches: compareStates(scenario.samples, replayed.samples),
        clientErrors: replayed.errors,
      });
    }
  } finally {
    await server.close();
  }
  return results;
}
