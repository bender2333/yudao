// 部门房间画面的回放核对（工单 #1069；#957 立框架、#1068 对齐楼层与楼的画法以后照同一做法做房间）：
// 把原型 v13 的页面上录下的调用送进客户端的房间画面，静置到时间线放空（最后一个检查点），
// 与 v13 的画面逐像素、逐个小人比较。
//
// 录下的调用是在 docs/prototypes/v13 的页面上录的（client/scripts/record-room-calls.mjs）：
// 状态是 department.workspace 结果里房间的那一块（带快照位置），事件是页面收到的原始事件。
// 回放时两边的翻译层各翻一次：v13 一侧 T.room.state / T.room.actions，客户端一侧
// src/translate/room.ts 的 state / actions——就是页面上走的那条路。
//
// 录下的调用序列在 tests/fixtures/room/recordings.json，只经 record-room-calls.mjs --write 更新。
// 回放测试不进 CI（AGENTS.md「执行者」），按本文件底的命令单独运行。

import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import type { Browser } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compareActors, diffPixels, launch, v13Checkpoint, type ActorShot, type CheckpointShot, type PixelDiff, type RecordedOp } from "./prototype-v13.ts";
import type { PixelAction, RoomState } from "../../src/renderer/src/pixel/contract.ts";
import type { RoomEvent } from "../../src/renderer/src/translate/room.ts";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

export interface RecordedRoomScenario {
  id: string;
  name: string;
  level: string;
  department: string;
  project: string;
  ops: RecordedOp[];
}

export interface RoomRecordingFile {
  generatedFrom: string;
  gapMs: { event: number; other: number };
  settleMs: number;
  scenarios: RecordedRoomScenario[];
}

export interface RoomCompareResult {
  scenario: string;
  pixelDiff: PixelDiff;
  actorMismatches: string[];
  mismatches: string[];
  clientErrors: string[];
  expectedPng?: string;
  actualPng?: string;
}

export function loadRoomRecordings(): RoomRecordingFile {
  return JSON.parse(readFileSync(join(clientRoot, "tests", "fixtures", "room", "recordings.json"), "utf8")) as RoomRecordingFile;
}

/**
 * 在页面里运行的驱动：把录下的调用送进客户端的房间画面，静置到时间线放空，固定小人的动画计时，
 * 取画布与逐个小人。函数体在浏览器里执行，只能引用浏览器里可用的模块（经开发服务器的绝对路径加载）。
 */
async function driver(input: {
  ops: RecordedOp[];
  department: string;
  gapMs: { event: number; other: number };
  settleMs: number;
}): Promise<{ png: string; actors: ActorShot[]; size: [number, number]; errors: string[] }> {
  const P = await import(/* @vite-ignore */ "/src/pixel/room/view.ts" as string) as typeof import("../../src/renderer/src/pixel/room/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/renderer/src/pixel/clock.ts");
  const tr = await import(/* @vite-ignore */ "/src/translate/room.ts" as string) as typeof import("../../src/renderer/src/translate/room.ts");
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:480px;height:240px;z-index:9999;background:#000";
  document.body.appendChild(host);
  // 与录制时一致的确定随机数（待机伸懒腰与打字停顿的时机）
  let seed = 987654321;
  const random = (): number => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const clock = clockMod.createManualClock();
  let view = await P.createRoomView({ host, clock, department: input.department, random, tween: null });
  // 静止的画面只由状态决定：关掉自主行为（待机活动）
  view.inspect().scene.autonomy = false;
  const errors: string[] = [];
  const origError = console.error;
  console.error = (...a: unknown[]): void => {
    errors.push(a.map(String).join(" "));
    origError.apply(console, a);
  };
  let roles: { id: string; name: string; kind: string }[] = [];
  const roleName = (id: string | null): string | null => {
    const hit = roles.find((r) => r.id === id || r.kind === id);
    return hit ? hit.name : null;
  };
  // 与原型一致：按 50 毫秒一帧推进
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) {
      clock.advance(Math.round(clock.now()) + 50);
    }
  };
  for (const op of input.ops) {
    try {
      if (op.op === "mount") {
        view.destroy();
        view = await P.createRoomView({ host, clock, department: input.department, random, tween: null });
        view.inspect().scene.autonomy = false;
        advance(input.gapMs.other);
        continue;
      }
      if (op.op === "workspace") {
        const state = tr.state({ position: op.position ?? 0, workspace: (op.arg ?? { room: null }) as { room: unknown } }) as RoomState;
        roles = (state.roles ?? []).map((r) => ({ id: String(r.id), name: String(r.name ?? r.id), kind: String(r.kind ?? "") }));
        if (op.jump) view.jump(state);
        else view.setState(state);
      } else if (op.op === "event") {
        const raw = (op.arg ?? {}) as Record<string, unknown>;
        const ev: RoomEvent = {
          type: String(raw.type ?? ""),
          position: Number(raw.position ?? 0),
          department: (raw.department as string) ?? null,
          role: (raw.role as string) ?? null,
          tool: (raw.tool as string) ?? null,
          label: (raw.label as string) ?? null,
          work_item_id: (raw.work_item_id as string) ?? null,
          payload: (raw.payload as Record<string, unknown>) ?? null,
        };
        const stream = tr.streamOfEvent(ev);
        if (stream) view.stream(stream.who, stream.text);
        for (const action of tr.actions(ev, input.department, { roleName }) as PixelAction[]) view.play(action);
      }
      // destroy：最后一个检查点要在画面上取，销毁画面的调用不执行
    } catch (e) {
      errors.push(String((e as Error)?.message ?? e));
    }
    advance(op.op === "event" ? input.gapMs.event : input.gapMs.other);
  }
  advance(input.settleMs);
  // 静置到时间线与动作放空（小人走回原位）
  const isBusy = (): boolean => {
    const tl = view.inspect().driver.timeline();
    return tl.pending > 0 || tl.playing.length > 0 || view.inspect().scene.actors.some((a) => a.script);
  };
  for (let i = 0; i < 60 && isBusy(); i++) {
    advance(100);
  }
  // 固定小人的动画计时与场景的动画时钟：与 v13 一侧取同一个值
  const scene = view.inspect().scene;
  const list = scene.actors.slice().sort((a, b) => (a.sprite < b.sprite ? -1 : 1));
  list.forEach((a, i) => { a.clock = 5000; a.animStart = 0; a.seed = 100 + i; });
  scene.animT = 20000;
  // 重画一帧（重排尺寸会清屏并按当前的世界重画，不推进时间）
  view.resize();
  const canvas = host.querySelector("canvas");
  if (!canvas) return { png: "", actors: [], size: [0, 0], errors: [...errors, "画面上没有画布"] };
  const actors: ActorShot[] = list.map((a) => ({
    sprite: a.sprite, x: Math.round(a.x * 100) / 100, y: Math.round(a.y * 100) / 100, seat: Boolean(a.seat),
    anim: a.anim, facing: a.facing ?? 0, icon: a.icon ? { kind: a.icon.kind, text: a.icon.text ?? null } : null,
    visible: a.visible !== false, dim: a.dim ?? 0, hold: a.hold ?? null, sign: a.sign ?? null, script: Boolean(a.script),
  }));
  console.error = origError;
  view.destroy();
  host.remove();
  return { png: canvas.toDataURL("image/png"), actors, size: [canvas.width, canvas.height], errors };
}

/** 起一个渲染进程的开发服务器，把一段录制送进客户端的房间画面，取最后一个检查点。 */
export async function replayRoomScenario(serverUrl: string, browser: Browser, rec: RecordedRoomScenario, recording: RoomRecordingFile): Promise<CheckpointShot> {
  const page = await browser.newPage();
  try {
    await page.goto(serverUrl + "index.html");
    await page.evaluate((fnSource) => {
      (window as any).__name = (target: any) => target;
      (window as unknown as { __roomDriver: unknown }).__roomDriver = (0, eval)(`(${fnSource})`);
    }, driver.toString());
    const result = await page.evaluate(async (input) => {
      try {
        const fn = (window as unknown as { __roomDriver: (i: typeof input) => Promise<unknown> }).__roomDriver;
        return { ok: await fn(input) };
      } catch (e) {
        return { failed: String((e as Error)?.stack ?? e) };
      }
    }, { ops: rec.ops, department: rec.department, gapMs: recording.gapMs, settleMs: recording.settleMs });
    if ("failed" in result) {
      return { png: "", actors: [], size: [0, 0], errors: [`驱动失败：${String(result.failed)}`] };
    }
    return result.ok as CheckpointShot;
  } finally {
    await page.close();
  }
}

/** 起开发服务器与浏览器，回放录下的场景，返回每段录制的比较结果。 */
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
  const { browser, proto, diff } = await launch();
  const results: RoomCompareResult[] = [];
  try {
    for (const scenario of recording.scenarios) {
      if (options.only && !options.only.includes(scenario.id)) continue;
      const expected = await v13Checkpoint(proto, {
        screen: "room", ops: scenario.ops, department: scenario.department,
        gapMs: recording.gapMs, settleMs: recording.settleMs,
      });
      const actual = await replayRoomScenario(address, browser, scenario, recording);
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
        expectedPng: expected.png,
        actualPng: actual.png,
      });
    }
  } finally {
    await browser.close();
    await server.close();
  }
  return results;
}
