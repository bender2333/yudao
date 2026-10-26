// 原型 v13 一侧的回放与逐像素比较（工单 #957）。
//
// 三个画面的回放核对做同一件事：把录下的调用（v13 页面上录到的状态、实时内容与事件）交给 v13 自己的画面，
// 静置到时间线放空，固定小人的动画计时与场景的动画时钟，取画布与逐个小人的状态；客户端的画面用同一串调用
// 得到同样的两份读数，最后逐像素相减、逐个小人比较。这份文件是共用的那一半（v13 一侧的驱动、像素差、小人比较），
// 各画面自己的接线（建立哪个画面、哪些调用、哪些字段）在 floor-replay.ts、room-replay.ts、building-replay.ts。
//
// 画布上的比较不用截图基线（跨机器的字体会让它不稳定）：v13 的画面在同一个浏览器里现画，两边用同一份字体。

import { chromium, type Browser, type Page } from "@playwright/test";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");
const repoRoot = resolve(clientRoot, "..");

/** 原型 v13 的页面地址（file:// 的同一次检出，换一份检出就录那一份）。 */
export function prototypeUrl(): string {
  const index = join(repoRoot, "docs", "prototypes", "v13", "index.html");
  return "file:///" + index.replace(/\\/g, "/").replace(/^\//, "");
}

/** 录下的一条调用（形状见 client/scripts/record-*-calls.mjs）。 */
export interface RecordedOp {
  op: string;
  arg?: unknown;
  /** 状态：true 是 jump（清空时间线直接显示），false 是 setState（等它之前的动作演完）。 */
  jump?: boolean;
  /** 查询结果来自的快照位置。 */
  position?: number;
}

/** 一个小人在画面上的一帧：位置、姿势、朝向、图标、手里的东西与牌子（原型 checks/replay.js 的 shoot）。 */
export interface ActorShot {
  sprite: string;
  x: number;
  y: number;
  seat: boolean;
  anim: string;
  facing: number;
  icon: { kind: string; text: string | null } | null;
  visible: boolean;
  dim: number;
  hold: string | null;
  sign: string | null;
  script: boolean;
}

/** 一段录制在最后一个检查点上的读数：画布（PNG 的 data URL）与逐个小人。 */
export interface CheckpointShot {
  png: string;
  actors: ActorShot[];
  /** 画布尺寸（逻辑尺寸乘整数倍）。 */
  size: [number, number];
  errors: string[];
}

/** 逐像素比较的结果：不同的像素个数与它们的外接矩形。 */
export interface PixelDiff {
  count: number;
  bbox?: [number, number, number, number];
  size?: [number, number, number, number];
}

/**
 * 在 v13 的页面里运行的驱动：用确定的时钟把录下的调用交给 v13 自己的画面，静置到时间线放空，
 * 固定小人的动画计时与场景的动画时钟，取画布与逐个小人。
 *
 * 只引用页面里的 window.Y13（这个函数经 toString 送进页面执行）。
 */
async function v13Driver(input: {
  screen: "floor" | "room" | "building";
  ops: RecordedOp[];
  department: string | null;
  gapMs: { event: number; other: number };
  settleMs: number;
}): Promise<{ png: string; actors: ActorShot[]; size: [number, number]; errors: string[] }> {
  const Y = (window as unknown as { Y13: Record<string, any> }).Y13;
  const P = Y.pixel;
  const T = Y.translate;
  await Promise.all([1, 2, 3, 4, 5, 6].map((i) => new Promise((resolve) => {
    P.shotImage(`todo-trial-${i}.png`);
    const img = new Image();
    img.onload = img.onerror = resolve;
    img.src = `assets/todo-trial-${i}.png`;
  })));
  const errors: string[] = [];
  // 确定的时钟与随机数：rAF 的回调收进队列，由 step 按 50 毫秒一帧推进
  let t = 0;
  const q: ((time: number) => void)[] = [];
  window.requestAnimationFrame = (cb: (time: number) => void): number => { q.push(cb); return q.length; };
  window.cancelAnimationFrame = (): void => {};
  performance.now = (): number => t;
  let seed = 987654321;
  Math.random = (): number => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  const step = (ms: number): void => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) {
      t += 50;
      const cbs = q.splice(0);
      for (const cb of cbs) cb(t);
    }
  };
  // 静止的画面只由状态决定：关掉自主行为（待机活动、管道的惯性）
  if (P.ecs && P.ecs.config) P.ecs.config.autonomy = false;

  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;z-index:9999;background:#000";
  document.body.appendChild(host);
  const canvas = document.createElement("canvas");
  host.appendChild(canvas);

  let obj: any = null;
  let roles: { id: string; name: string; kind: string }[] = [];
  const collect = (rolesInput: unknown): { id: string; name: string; kind: string }[] => {
    if (!rolesInput) return [];
    if (Array.isArray(rolesInput)) return rolesInput as { id: string; name: string; kind: string }[];
    return Object.values(rolesInput as Record<string, unknown>).reduce<{ id: string; name: string; kind: string }[]>(
      (list, x) => list.concat((x ?? []) as { id: string; name: string; kind: string }[]), []);
  };
  const roleName = (id: string | null): string | null => {
    const hit = roles.find((r) => r.id === id || r.kind === id);
    return hit ? hit.name : null;
  };
  const mount = (): void => {
    if (obj) obj.destroy();
    if (input.screen === "floor") obj = P.createFloorScene(canvas, { onDoorClick(): void {} });
    else if (input.screen === "room") obj = P.createRoomScene(canvas, { department: input.department });
    else obj = P.createBuildingScene(canvas, { onFloorClick(): void {} });
    if (obj.scene) obj.scene.autonomy = false;
  };

  try {
    for (const op of input.ops) {
      try {
        if (op.op === "mount") { mount(); step(input.gapMs.other); continue; }
        if (!obj) mount();
        if (op.op === "state") {
          roles = collect((op.arg as { roles?: unknown })?.roles);
          obj[op.jump ? "jump" : "setState"](op.arg);
        } else if (op.op === "workspace") {
          const s = T.room.state({ position: op.position ?? 0, workspace: op.arg });
          roles = collect(s.roles);
          obj[op.jump ? "jump" : "setState"](s);
        } else if (op.op === "event") {
          const ev = op.arg as Record<string, unknown>;
          const s = T.stream(ev);
          if (s && (input.screen !== "room" || s.who.room === input.department)) obj.stream(s.who, s.text);
          const acts = input.screen === "floor" ? T.floor.actions(ev, { roleName })
            : input.screen === "room" ? T.room.actions(ev, input.department, { roleName })
              : T.building.actions(ev).filter((a: { kind: string }) => a.kind.indexOf("machine_") !== 0);
          acts.forEach((a: unknown) => obj.play(a));
        } else if (op.op === "decisions") obj.setDecisions(op.arg);
        else if (op.op === "overlay") obj.setOverlay((op.arg as { id: string | null }).id, (op.arg as { data: unknown }).data);
        else if (op.op === "focus") obj.focus(op.arg);
        // destroy：最后一个检查点要在画面上取，销毁画面的调用不执行
      } catch (e) {
        errors.push(String((e as Error)?.message ?? e));
      }
      step(op.op === "event" ? input.gapMs.event : input.gapMs.other);
    }
    step(input.settleMs);
    if (!obj) mount();
    const sc = obj.scene;
    // 固定小人的动画计时与场景的动画时钟：两边的相位、眨眼与目光取同一个值
    const list = sc.actors.slice().sort((a: { sprite: string }, b: { sprite: string }) => (a.sprite < b.sprite ? -1 : 1));
    list.forEach((a: { clock: number; animStart: number; seed: number }, i: number) => { a.clock = 5000; a.animStart = 0; a.seed = 100 + i; });
    sc.animT = 20000;
    sc.drawNow();
    const actors: ActorShot[] = list.map((a: any) => ({
      sprite: a.sprite, x: Math.round(a.x * 100) / 100, y: Math.round(a.y * 100) / 100, seat: Boolean(a.seat),
      anim: a.anim, facing: a.facing, icon: a.icon ? { kind: a.icon.kind, text: a.icon.text ?? null } : null,
      visible: a.visible, dim: a.dim, hold: a.hold ?? null, sign: a.sign ?? null, script: Boolean(a.script),
    }));
    return { png: canvas.toDataURL("image/png"), actors, size: [canvas.width, canvas.height], errors } as CheckpointShot;
  } finally {
    host.remove();
  }
}

/** 打开原型 v13 的页面（档位 S5，与录制时相同），装好驱动。 */
export async function openPrototype(browser: Browser): Promise<Page> {
  const page = await browser.newPage();
  await page.addInitScript(() => {
    (window as any).__name = (target: any) => target;
    sessionStorage.setItem("y13.level", JSON.stringify("S5"));
  });
  await page.goto(prototypeUrl() + "#/sys/machines");
  await page.waitForTimeout(500);
  await page.evaluate((fnSource) => {
    (window as any).__name = (target: any) => target;
    (window as unknown as { __v13Driver: unknown }).__v13Driver = (0, eval)(`(${fnSource})`);
  }, v13Driver.toString());
  return page;
}

/** 在 v13 的页面上把这个场景的调用放完，取最后一个检查点。 */
export async function v13Checkpoint(page: Page, input: {
  screen: "floor" | "room" | "building";
  ops: RecordedOp[];
  department?: string | null;
  gapMs: { event: number; other: number };
  settleMs: number;
}): Promise<CheckpointShot> {
  const result = await page.evaluate(async (arg) => {
    try {
      const fn = (window as unknown as { __v13Driver: (i: typeof arg) => Promise<unknown> }).__v13Driver;
      return { ok: await fn(arg) };
    } catch (e) {
      return { failed: String((e as Error)?.stack ?? e) };
    }
  }, { screen: input.screen, ops: input.ops, department: input.department ?? null, gapMs: input.gapMs, settleMs: input.settleMs });
  if ("failed" in result) {
    return { png: "", actors: [], size: [0, 0], errors: [`v13 驱动失败：${String(result.failed)}`] };
  }
  return result.ok as CheckpointShot;
}

/** 一张空白页，用来做像素减法（两边都是 data URL 的 PNG）。 */
export async function openDiffPage(browser: Browser): Promise<Page> {
  const page = await browser.newPage();
  await page.addInitScript(() => {
    (window as any).__name = (target: any) => target;
  });
  await page.goto("about:blank");
  await page.evaluate(() => {
    (window as any).__name = (target: any) => target;
  });
  return page;
}

/** 逐像素比较两张画布（RGB 不同即不同），返回不同的像素个数与外接矩形。 */
export async function diffPixels(page: Page, a: string, b: string): Promise<PixelDiff> {
  return page.evaluate(async ([x, y]) => {
    const load = (src: string): Promise<HTMLImageElement> => new Promise((res) => {
      const im = new Image();
      im.onload = (): void => res(im);
      im.src = src;
    });
    const [ia, ib] = await Promise.all([load(x), load(y)]);
    if (ia.width !== ib.width || ia.height !== ib.height) {
      return { count: -1, size: [ia.width, ia.height, ib.width, ib.height] as [number, number, number, number] };
    }
    const cv = document.createElement("canvas");
    cv.width = ia.width; cv.height = ia.height;
    const cx = cv.getContext("2d")!;
    cx.drawImage(ia, 0, 0);
    const da = cx.getImageData(0, 0, cv.width, cv.height).data;
    cx.clearRect(0, 0, cv.width, cv.height);
    cx.drawImage(ib, 0, 0);
    const db = cx.getImageData(0, 0, cv.width, cv.height).data;
    let count = 0, x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
    for (let i = 0; i < da.length; i += 4) {
      if (da[i] === db[i] && da[i + 1] === db[i + 1] && da[i + 2] === db[i + 2]) continue;
      const p = i / 4, px = p % cv.width, py = (p - px) / cv.width;
      count++;
      x0 = Math.min(x0, px); y0 = Math.min(y0, py); x1 = Math.max(x1, px); y1 = Math.max(y1, py);
    }
    return count === 0 ? { count: 0 } : { count, bbox: [x0, y0, x1, y1] as [number, number, number, number] };
  }, [a, b] as [string, string]);
}

/** 逐个小人比较（位置、姿势、朝向、图标、手里的东西、牌子、是否可见、是否调暗、有没有脚本）。 */
export function compareActors(expected: readonly ActorShot[], actual: readonly ActorShot[]): string[] {
  const out: string[] = [];
  if (expected.length !== actual.length) {
    out.push(`小人数量不同：v13 ${expected.length}，客户端 ${actual.length}（${expected.map((a) => a.sprite).join(",")} / ${actual.map((a) => a.sprite).join(",")}）`);
  }
  const fields: (keyof ActorShot)[] = ["x", "y", "seat", "anim", "facing", "icon", "visible", "dim", "hold", "sign", "script"];
  for (const [index, left] of expected.entries()) {
    const right = actual[index];
    if (!right) continue;
    for (const field of fields) {
      if (JSON.stringify(left[field]) !== JSON.stringify(right[field])) {
        out.push(`小人 ${left.sprite} 的${field}不同：v13 ${JSON.stringify(left[field])}，客户端 ${JSON.stringify(right[field])}`);
      }
    }
  }
  return out;
}

/** 起一个浏览器：打开 v13 的页面与一个做像素减法的空白页。 */
export async function launch(): Promise<{ browser: Browser; proto: Page; diff: Page }> {
  const browser = await chromium.launch({
    ...(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {}),
    args: ["--allow-file-access-from-files", "--disable-web-security"],
  });
  const proto = await openPrototype(browser);
  const diff = await openDiffPage(browser);
  return { browser, proto, diff };
}
