// 楼层画面的回放核对（工单 #957 验收标准 2）：把原型 v13 的页面上录下的调用送进客户端的画面，
// 静置到时间线放空（最后一个检查点），与 v13 的画面逐像素、逐个小人比较。
//
// 录下的调用是在 docs/prototypes/v13 的页面上录的（client/scripts/record-floor-calls.mjs）：
// 状态是 v13 的翻译层从查询结果（project.loop）翻好、交给画面的画面合同状态，事件是页面收到的原始事件。
// 回放时状态直接交给画面，事件经客户端的翻译层（src/translate/floor.ts）翻成动作——就是页面上走的那条路。
//
// 录下的调用序列在 tests/fixtures/floor/recordings.json，只经 record-floor-calls.mjs --write 更新。
// 回放测试不进 CI（AGENTS.md「执行者」），按本文件底的命令单独运行。

import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import type { Browser } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compareActors, diffPixels, launch, v13Checkpoint, type ActorShot, type CheckpointShot, type RecordedOp } from "./prototype-v13.ts";
import type { FloorModel } from "../../src/renderer/src/pixel/world/types.ts";
import type { FloorEvent } from "../../src/renderer/src/translate/floor.ts";
import type { DecisionFace } from "../../src/renderer/src/pixel/world/types.ts";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

export interface RecordedScenario {
  id: string;
  name: string;
  level: string;
  project: string;
  ops: RecordedOp[];
}

export interface RecordingFile {
  generatedFrom: string;
  gapMs: { event: number; other: number };
  settleMs: number;
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
 * v13 的画面合同状态 → 客户端画面合同的状态。
 *
 * 两边的合同说的是同一件事，字段名不同：v13 原型的事项用 id、cycle、limit_sec，客户端的画面合同用
 * work_item_id、round、time_limit_sec（服务端的说法，工单 #952 定下）。这里只换名，不改取值：状态的取值
 * （working、waiting_model 这些画面的词）两边本来一样，客户端画面收到状态以后自己校验。
 */
export function toViewState(raw: unknown): FloorModel {
  const s = (raw ?? {}) as Record<string, unknown>;
  const items = ((s.items ?? []) as Record<string, unknown>[]).map((it) => ({
    ...it,
    work_item_id: String(it.id ?? ""),
    round: Number(it.cycle ?? 0),
    time_limit_sec: Number(it.limit_sec ?? 0),
    kind: String(it.kind ?? "request"),
    sign: (it.sign as string | null) ?? null,
    department: (it.department as string | null) ?? null,
    color_index: Number(it.color_index ?? 0),
    elapsed_sec: it.elapsed_sec === undefined || it.elapsed_sec === null ? null : Number(it.elapsed_sec),
  }));
  const shelves = (s.shelves ?? {}) as { adopted?: string[] };
  return {
    position: Number(s.position ?? 0),
    items,
    open_requests: (s.open_requests ?? []) as FloorModel["open_requests"],
    shelves: { adopted: shelves.adopted ?? [] },
    slots: (s.slots ?? null) as FloorModel["slots"],
    waiting_provider: (s.waiting_provider ?? []) as FloorModel["waiting_provider"],
    machines: (s.machines ?? null) as FloorModel["machines"],
    ops: (s.ops ?? null) as FloorModel["ops"],
    interrupted: Boolean(s.interrupted),
    roles: (s.roles ?? null) as FloorModel["roles"],
    decisions: [],
    ...(s.focus_id ? { focus_id: String(s.focus_id) } : {}),
  } as unknown as FloorModel;
}

/**
 * 在页面里运行的驱动：把录下的调用送进客户端的楼层画面，静置到时间线放空，固定小人的动画计时，
 * 取画布与逐个小人。函数体在浏览器里执行，只能引用浏览器里可用的模块（经开发服务器的绝对路径加载）。
 */
async function driver(input: {
  ops: RecordedOp[];
  gapMs: { event: number; other: number };
  settleMs: number;
}): Promise<{ png: string; actors: ActorShot[]; size: [number, number]; errors: string[] }> {
  const P = await import(/* @vite-ignore */ "/src/pixel/floor/view.ts" as string) as typeof import("../../src/renderer/src/pixel/floor/view.ts");
  const clockMod = await import(/* @vite-ignore */ "/src/pixel/clock.ts" as string) as typeof import("../../src/renderer/src/pixel/clock.ts");
  const tr = await import(/* @vite-ignore */ "/src/translate/floor.ts" as string) as typeof import("../../src/renderer/src/translate/floor.ts");
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:9999;background:#000";
  document.body.appendChild(host);
  // 确定的随机数：待机活动关掉以后画面只由状态与动作决定，随机数只是让两次运行的结果一致
  let seed = 987654321;
  Math.random = (): number => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const clock = clockMod.createManualClock();
  let view = await P.createFloorView({ host, clock });
  view.inspect().scene.autonomy = false;
  const errors: string[] = [];
  const origError = console.error;
  console.error = (...a: unknown[]): void => {
    errors.push(a.map(String).join(" "));
    origError.apply(console, a);
  };
  let roles: { id: string; name: string; kind: string }[] = [];
  const collect = (input2: unknown): { id: string; name: string; kind: string }[] => {
    if (!input2) return [];
    return Object.values(input2 as Record<string, unknown>).reduce<{ id: string; name: string; kind: string }[]>(
      (list, x) => list.concat((x ?? []) as { id: string; name: string; kind: string }[]), []);
  };
  const roleName = (id: string | null): string | null => {
    const hit = roles.find((r) => r.id === id || r.kind === id);
    return hit ? hit.name : null;
  };
  // 与原型一致：按 50 毫秒一帧推进
  const advance = (ms: number): void => {
    const frames = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < frames; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  for (const op of input.ops) {
    try {
      if (op.op === "mount") {
        view.destroy();
        view = await P.createFloorView({ host, clock });
        view.inspect().scene.autonomy = false;
        advance(input.gapMs.other);
        continue;
      }
      if (op.op === "state") {
        const state = op.arg as unknown as FloorModel;
        roles = collect((op.arg as { roles?: unknown }).roles);
        if (op.jump) view.jump(state);
        else view.setState(state);
      } else if (op.op === "event") {
        const raw = (op.arg ?? {}) as Record<string, unknown>;
        const ev: FloorEvent = {
          type: String(raw.type ?? ""),
          position: Number(raw.position ?? 0),
          event_id: (raw.event_id as string) ?? null,
          project_id: (raw.project_id as string) ?? null,
          department: (raw.department as string) ?? null,
          role: (raw.role as string) ?? null,
          tool: (raw.tool as string) ?? null,
          label: (raw.label as string) ?? null,
          work_item_id: (raw.work_item_id as string) ?? null,
          payload: (raw.payload as Record<string, unknown>) ?? null,
        };
        const stream = tr.streamText(ev);
        if (stream) view.stream({ room: stream.room, role: stream.role }, stream.text);
        for (const action of tr.floorActions(ev, { roleName })) view.play(action);
      } else if (op.op === "decisions") view.setDecisions((op.arg ?? []) as unknown as DecisionFace[]);
      else if (op.op === "overlay") view.setOverlay((op.arg as { id: string | null }).id, (op.arg as { data: unknown }).data);
      else if (op.op === "focus") view.focus((op.arg as string | null) ?? null);
      // destroy：最后一个检查点要在画面上取，销毁画面的调用不执行
    } catch (e) {
      errors.push(String((e as Error)?.message ?? e));
    }
    advance(op.op === "event" ? input.gapMs.event : input.gapMs.other);
  }
  advance(input.settleMs);
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
    anim: a.anim, facing: a.facing, icon: a.icon ? { kind: a.icon.kind, text: a.icon.text ?? null } : null,
    visible: a.visible, dim: a.dim, hold: a.hold ?? null, sign: a.sign ?? null, script: Boolean(a.script),
  }));
  console.error = origError;
  view.destroy();
  host.remove();
  return { png: canvas.toDataURL("image/png"), actors, size: [canvas.width, canvas.height], errors };
}

/** 起一个渲染进程的开发服务器，把一段录制送进客户端的楼层画面，取最后一个检查点。 */
export async function replayScenario(serverUrl: string, browser: Browser, rec: RecordedScenario, recording: RecordingFile): Promise<CheckpointShot> {
  const page = await browser.newPage();
  try {
    await page.goto(serverUrl + "index.html");
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
    }, { ops: rec.ops.map((op) => (op.op === "state" ? { ...op, arg: toViewState(op.arg) } : op)), gapMs: recording.gapMs, settleMs: recording.settleMs });
    if ("failed" in result) {
      return { png: "", actors: [], size: [0, 0], errors: [`驱动失败：${String(result.failed)}`] };
    }
    return result.ok as CheckpointShot;
  } finally {
    await page.close();
  }
}

/** 起开发服务器与浏览器，回放录下的场景，返回每个场景的比较结果。 */
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
  const { browser, proto, diff } = await launch();
  const results: CompareResult[] = [];
  try {
    for (const scenario of recording.scenarios) {
      if (options.only && !options.only.includes(scenario.id)) continue;
      const expected = await v13Checkpoint(proto, { screen: "floor", ops: scenario.ops, gapMs: recording.gapMs, settleMs: recording.settleMs });
      const actual = await replayScenario(address, browser, scenario, recording);
      const mismatches: string[] = [];
      if (expected.png && actual.png) {
        const d = await diffPixels(diff, expected.png, actual.png);
        if (d.count < 0) mismatches.push(`画布尺寸不同：v13 ${JSON.stringify(d.size)}`);
        else if (d.count > 0) mismatches.push(`逐像素比较：${d.count} 个像素不同，外接矩形 ${JSON.stringify(d.bbox)}`);
      }
      mismatches.push(...compareActors(expected.actors, actual.actors));
      results.push({ scenario: scenario.id, mismatches, clientErrors: [...expected.errors, ...actual.errors] });
    }
  } finally {
    await browser.close();
    await server.close();
  }
  return results;
}
