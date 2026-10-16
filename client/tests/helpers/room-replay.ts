// 部门房间的回放核对（工单 #177 验收标准 2）：把原型录下的调用序列送进客户端的房间画面，
// 按录下的固定时刻取状态，与原型录下的状态逐项比较：每个角色的任务与姿势、头顶的话、
// 房间状态、管道口的未回答信件数。
//
// 录下的调用与状态记录在 tests/fixtures/room/recordings.json，只经 record-room-calls.mjs --write 更新。

import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { adaptRecordedArg } from "./recorded-tool-names.ts";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

export interface RoomSample {
  after: number;
  ms: number;
  state: {
    chars: (string | number | boolean | null)[][];
    status: string | null;
    door: string | null;
    letters: number;
  };
}

export interface RoomRecording {
  id: string;
  name: string;
  department: string;
  project: string;
  ops: { op: string; arg?: unknown }[];
  samples: RoomSample[];
}

export interface RoomRecordingFile {
  generatedFrom: string;
  sampleMs: number[];
  scenarios: RoomRecording[];
}

export interface RoomCompareResult {
  scenario: string;
  mismatches: string[];
  clientErrors: string[];
}

export function loadRoomRecordings(): RoomRecordingFile {
  return JSON.parse(readFileSync(join(clientRoot, "tests", "fixtures", "room", "recordings.json"), "utf8")) as RoomRecordingFile;
}

/** 在页面里运行的驱动：把调用序列送进客户端的房间画面，按固定时刻取状态。 */
async function driver(input: { ops: RoomRecording["ops"]; department: string; sampleMs: number[] }): Promise<{ samples: RoomSample[]; errors: string[] }> {
  const P = await import(/* @vite-ignore */ "/src/pixel/room/view.ts" as string) as typeof import("../../src/renderer/src/pixel/room/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/renderer/src/pixel/clock.ts");
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:480px;height:240px;z-index:9999;background:#000";
  document.body.appendChild(host);
  const clock = clockMod.createManualClock();
  // 与录制时一致的确定随机数（待机伸懒腰与打字停顿的时机）
  let seed = 987654321;
  const random = (): number => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const view = await P.createRoomView({ host, clock, department: input.department, random, tween: null });
  const errors: string[] = [];
  const origError = console.error;
  console.error = (...a: unknown[]): void => {
    errors.push(a.map(String).join(" "));
    origError.apply(console, a);
  };
  function snapshot(): RoomSample["state"] {
    const driver = view.inspect().driver;
    const scene = view.inspect().scene;
    const chars = driver.actors()
      .slice()
      .sort((a, b) => (a.id < b.id ? -1 : 1))
      .map((c) => {
        const a = scene.actors.find((x) => x.id === `ch-${c.id}`);
        return [c.id, c.role.kind, c.doing, a ? a.anim : null, a && a.icon ? a.icon.kind : null,
          c.say ? c.say.text : null, a ? Math.round(a.x) : null, a ? Math.round(a.y) : null,
          a ? Boolean(a.seat) : null, a ? a.visible : null];
      });
    return {
      chars, status: driver.model.status ?? null, door: driver.model.door ?? null,
      letters: driver.model.pipes?.letters_waiting ?? 0,
    };
  }
  const samples: RoomSample[] = [];
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  for (let i = 0; i < input.ops.length; i++) {
    const op = input.ops[i];
    if (op.op === "mount" || op.op === "destroy") continue;
    if (op.op === "setModel") view.setModel(op.arg as never);
    else if (op.op === "playEvent") view.playEvent(op.arg as never);
    for (const ms of input.sampleMs) {
      advance(ms);
      samples.push({ after: i, ms, state: snapshot() });
    }
  }
  console.error = origError;
  view.destroy();
  host.remove();
  return { samples, errors };
}

/** 起一个渲染进程的开发服务器，把一份录制的调用序列送进画面，返回取到的状态。 */
export async function replayRoom(serverUrl: string, rec: RoomRecording, sampleMs: number[]): Promise<{ samples: RoomSample[]; errors: string[] }> {
  const browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
  try {
    const page = await browser.newPage();
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));
    await page.goto(serverUrl + "index.html");
    await page.evaluate((fnSource) => {
      (window as unknown as { __roomDriver: unknown }).__roomDriver = (0, eval)(`(${fnSource})`);
    }, driver.toString());
    const result = await page.evaluate(async (input) => {
      try {
        const fn = (window as unknown as { __roomDriver: (i: typeof input) => Promise<unknown> }).__roomDriver;
        return { ok: await fn(input) };
      } catch (e) {
        return { failed: String((e as Error)?.stack ?? e) };
      }
    }, { ops: rec.ops.map((op) => ({ ...op, arg: adaptRecordedArg(op.arg) })), department: rec.department, sampleMs });
    if ("failed" in result) {
      return { samples: [], errors: [...pageErrors, `驱动失败：${String(result.failed)}`] };
    }
    const ok = result.ok as { samples: RoomSample[]; errors: string[] };
    return { samples: ok.samples, errors: [...pageErrors, ...ok.errors] };
  } finally {
    await browser.close();
  }
}

/** 待机时的装饰性姿势：空闲角色偶尔伸懒腰、停下来想一想或抬头看屏幕，不改变任何事实，比较时视为同一姿势。 */
const IDLE_DECOR = new Set(["tea", "stretch_sit", "stretch", "sit", "sit_up", "think", "type", "idle", "idle_happy"]);

/** 两个姿势在待机时是否等价：都是待机的装饰性姿势（伸懒腰、停下来想一想、坐着），
 *  不改变任何事实；角色的任务与头顶的话另行比较。 */
function idleEquivalent(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  return IDLE_DECOR.has(String(left)) && IDLE_DECOR.has(String(right));
}

/** 比较两份状态：逐项列出不同（角色的任务、姿势与头顶的话、房间状态、管道口）。
 *  位置是动作进行中的瞬时值，比较的是任务与姿势；座位与可见性一并比较。 */
export function compareRoomStates(recorded: RoomSample[], replayed: RoomSample[]): string[] {
  const out: string[] = [];
  if (recorded.length !== replayed.length) {
    return [`样本数量不同：原型 ${recorded.length}，客户端 ${replayed.length}`];
  }
  for (let i = 0; i < recorded.length; i++) {
    const a = recorded[i];
    const b = replayed[i];
    const ca = new Map(a.state.chars.map((c) => [c[0] as string, c]));
    const cb = new Map(b.state.chars.map((c) => [c[0] as string, c]));
    for (const [id, left] of ca) {
      const right = cb.get(id);
      if (!right) {
        out.push(`样本 ${i}（${a.ms} 毫秒）缺少角色 ${id}`);
        continue;
      }
      // 索引：1 角色种类、2 动作、3 姿势、4 图标、5 头顶的话、8 坐着、9 可见（6、7 是动作进行中的坐标）
      const fields = ["角色种类", "动作", "姿势", "图标", "头顶的话", "坐着", "可见"];
      const indexes = [1, 2, 3, 4, 5, 8, 9];
      indexes.forEach((k, j) => {
        if (k === 3 && idleEquivalent(left[k], right[k])) return;
        if (JSON.stringify(left[k]) !== JSON.stringify(right[k])) {
          out.push(`样本 ${i}（${a.ms} 毫秒）角色 ${id} 的${fields[j]}不同：原型 ${JSON.stringify(left[k])}，客户端 ${JSON.stringify(right[k])}`);
        }
      });
    }
    if (a.state.status !== b.state.status) {
      out.push(`样本 ${i}（${a.ms} 毫秒）房间状态不同：原型 ${a.state.status}，客户端 ${b.state.status}`);
    }
    if (a.state.letters !== b.state.letters) {
      out.push(`样本 ${i}（${a.ms} 毫秒）传信管口不同：原型 ${a.state.letters}，客户端 ${b.state.letters}`);
    }
  }
  return out;
}

/** 起一个开发服务器，回放全部录下的部门房间调用序列，返回每份的比较结果。 */
export async function replayAllRooms(options: { only?: string[] } = {}): Promise<RoomCompareResult[]> {
  const recording = loadRoomRecordings();
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
  const results: RoomCompareResult[] = [];
  try {
    for (const rec of recording.scenarios) {
      if (options.only && !options.only.includes(rec.id)) continue;
      const replayed = await replayRoom(address, rec, recording.sampleMs);
      results.push({
        scenario: rec.id,
        mismatches: compareRoomStates(rec.samples, replayed.samples),
        clientErrors: replayed.errors,
      });
    }
  } finally {
    await server.close();
  }
  return results;
}
