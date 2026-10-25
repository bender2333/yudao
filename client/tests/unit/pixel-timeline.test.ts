// 播放时间线的规则测试（工单 #951 验收标准 1）：把原型 v13 checks/timeline.js 的各组检查改写为对客户端的测试。
// 用 pixel/clock.ts 的手动时钟推进，用一个只记录调用的渲染驱动它，不需要浏览器。
//
// 覆盖：排队与同时演、演满声明时长与等渲染演完、状态等动作、队伍过长、进度不排队、
// 堆积（H8 落后上限、H9 关键动作不丢不截断、缩短与合并、最短时长）、极端堆积、
// 限时演完与加快倍率、合并、跳到最新、后台切回、旧的状态、声明时长的倍率、参数与入队的校验。

import { test } from "node:test";
import assert from "node:assert/strict";

import { createManualClock } from "../../src/renderer/src/pixel/clock.ts";
import { MAX_NORMAL, RUSH_EXTRA, TIERS, create, settings } from "../../src/renderer/src/pixel/timeline.ts";
import type { ActionClass, Tier, Timeline, TimelineOptions } from "../../src/renderer/src/pixel/timeline.ts";
import type { PixelAction } from "../../src/renderer/src/pixel/contract.ts";

/** 原型 v13 checks/timeline.js 的声明表：级别与声明时长。 */
interface Decl {
  tier: Tier;
  ms: number;
}

const DEFAULT_DECL: Record<string, Decl> = {
  handoff: { tier: "key", ms: 2000 },
  stamp: { tier: "key", ms: 1000 },
  read: { tier: "normal", ms: 1200 },
  write: { tier: "normal", ms: 1200 },
  think: { tier: "progress", ms: 0 },
  flash: { tier: "normal", ms: 700 },
};

/** rig 的选项：播放参数、声明表、渲染自己演完要多久（默认等于声明时长）。 */
interface RigOptions {
  settings?: Partial<typeof settings>;
  decl?: Record<string, Decl>;
  natural?: (action: PixelAction, ms: number) => number;
}

interface Begun {
  at: number;
  kind: string;
  pos: number;
  ms: number;
  lanes: string[];
  tier: Tier;
}

interface Cut {
  at: number;
  kind: string;
  pos: number;
  tier: Tier;
}

/**
 * 一条时间线与它的渲染：自然演完的时间按时间线给出的加快倍率 rate() 推进，
 * 限时演完的动作能不能赶上由倍率决定。每帧先把演完的动作报告给时间线，再推进时间线。
 */
function rig(opts: RigOptions = {}) {
  Object.assign(settings, { lagMs: 5000, minMs: 300, speed: 1 }, opts.settings ?? {});
  const DECL: Record<string, Decl> = { ...DEFAULT_DECL, ...(opts.decl ?? {}) };
  const clock = createManualClock();
  const begun: Begun[] = [];
  const applied: { at: number; pos: number }[] = [];
  const progress: { at: number; kind: string }[] = [];
  const cut: Cut[] = [];
  const live = new Map<number, number>();
  const natural = opts.natural ?? ((_action: PixelAction, ms: number): number => ms);
  const tl: Timeline = create({
    clock: () => clock.now(),
    classify: (a): ActionClass => ({ lanes: a.lanes ?? [], ...DECL[a.kind] }),
    begin(e) {
      begun.push({ at: clock.now(), kind: e.action.kind, pos: e.pos, ms: e.ms, lanes: e.lanes.slice(), tier: e.tier });
      live.set(e.id, natural(e.action, e.ms0));
    },
    cut(e) {
      cut.push({ at: clock.now(), kind: e.action.kind, pos: e.pos, tier: e.tier });
      live.delete(e.id);
    },
    apply(s) {
      applied.push({ at: clock.now(), pos: s.position });
    },
    progress(a) {
      progress.push({ at: clock.now(), kind: a.kind });
    },
  });
  let pos = 0;
  const run = (ms: number, dt = 16): void => {
    const step = dt || 16;
    const until = clock.now() + ms;
    while (clock.now() < until) {
      const d = Math.min(until, clock.now() + step) - clock.now();
      const rate = tl.rate();
      clock.advance(clock.now() + d);
      live.forEach((left, id) => {
        const rest = left - d * rate;
        live.set(id, rest);
        if (rest <= 0) {
          tl.done(id);
          live.delete(id);
        }
      });
      tl.tick();
    }
  };
  const act = (kind: string, lanes: string[], extra: Record<string, unknown> = {}): number => {
    pos += 1;
    tl.push({ ...extra, kind, position: pos, lanes });
    return pos;
  };
  return {
    tl,
    begun,
    applied,
    progress,
    cut,
    run,
    act,
    now: (): number => clock.now(),
    jump: (): void => tl.jump({ position: pos }),
    state: (p?: number): void => tl.state({ position: p === undefined ? pos : p }),
    pos: (): number => pos,
  };
}

// ---------------------------------------------------------------------------
// 1. 排队

test("排队：不同参与方的动作同一帧开始，同一个参与方的下一件事等上一件演完", () => {
  const r = rig();
  r.jump();
  r.act("read", ["e"]);
  r.act("write", ["e"]);
  r.act("read", ["q"]);
  r.run(16);
  assert.equal(r.begun.length, 2, `同一帧应当按参与方各开始一件：${JSON.stringify(r.begun)}`);
  assert.ok(r.begun.every((b) => b.at === 16), JSON.stringify(r.begun));
  r.run(1200);
  const w = r.begun.find((b) => b.kind === "write");
  assert.ok(w, "同一个参与方的下一件事应当在上一件演完以后开始");
  assert.ok(w.at >= 1216, `write 在 ${w.at} 毫秒开始，应当不早于上一件演完的 1216 毫秒`);
});

// ---------------------------------------------------------------------------
// 2. 状态等动作

test("状态：只等位置不大于它、还在队里或正在演的动作，演完它才上画面", () => {
  const r = rig();
  r.jump();
  r.act("handoff", ["e", "q"]);
  const p2 = r.act("stamp", ["q"]);
  r.state(p2);
  r.act("read", ["e"]);
  r.state();
  r.run(16);
  assert.equal(r.applied.length, 1, "前面的动作还在演时不上画面");
  r.run(3100);
  const a2 = r.applied.find((x) => x.pos === p2);
  assert.ok(a2, `位置 ${p2} 的状态应当已经上画面：${JSON.stringify(r.applied)}`);
  assert.ok(a2.at >= 3000, `它前面的动作演完才上画面，实际在 ${a2.at} 毫秒`);
  r.run(2000);
  assert.equal(r.applied[r.applied.length - 1].pos, r.pos(), "位置更大的动作不挡它");
});

test("状态：没有要等的动作时下一帧上画面；比画面上的状态还旧的结果不上画面", () => {
  const empty = rig();
  empty.jump();
  empty.state();
  empty.run(16);
  assert.equal(empty.applied.length, 2, "跳到最新算一次，状态再算一次");
  assert.equal(empty.applied[1].at, 16, "没有要等的动作时下一帧上画面");

  const r = rig();
  r.act("read", ["e"]);
  r.jump();
  r.tl.state({ position: 0 });
  r.run(100);
  assert.equal(r.applied.length, 1, "比画面上还旧的状态不上画面");
});

// ---------------------------------------------------------------------------
// 3. 时长

test("时长：演满声明的时长，渲染演得比声明长时等它演完，平常没有截断", () => {
  const r = rig({ natural: (a, ms) => (a.slow ? ms + 900 : 100) });
  r.jump();
  r.act("read", ["e"]);
  r.act("write", ["e"]);
  r.act("read", ["q"], { slow: true });
  r.act("write", ["q"]);
  r.run(3000);
  const writes = r.begun.filter((b) => b.kind === "write");
  const first = writes.find((b) => b.lanes[0] === "e");
  const second = writes.find((b) => b.lanes[0] === "q");
  assert.ok(first, "第一个参与方应当演到 write");
  assert.ok(first.at >= 1200, `渲染提前演完也要演满声明的时长，实际在 ${first.at} 毫秒`);
  assert.ok(second, "第二个参与方应当演到 write");
  assert.ok(second.at >= 2100, `渲染演得比声明长时等它演完，实际在 ${second.at} 毫秒`);
  assert.equal(r.cut.length, 0, `平常没有被截断的动作：${JSON.stringify(r.cut)}`);
});

// ---------------------------------------------------------------------------
// 4. 队伍过长

test("队伍过长：一个参与方排着的普通动作最多三条，丢掉最早的", () => {
  const r = rig();
  r.jump();
  r.act("handoff", ["e"]);
  for (let i = 0; i < 6; i++) r.act("read", ["e"]);
  const ins = r.tl.inspect();
  assert.equal(ins.queued, 4, "排着的普通动作留三条，加上排着的一条关键动作");
  assert.equal(ins.stats.dropped, 3, `丢掉的是最早的三条普通动作：${JSON.stringify(ins.stats)}`);
  assert.equal(ins.stats.droppedKey, 0, "关键动作不丢");
});

// ---------------------------------------------------------------------------
// 5. 进度

test("进度：不排队，到了就交给渲染，状态不等它", () => {
  const r = rig();
  r.jump();
  r.act("read", ["e"]);
  r.act("think", ["e"]);
  r.state();
  r.run(16);
  assert.equal(r.progress.length, 1, "进度动作到了立刻交给渲染");
  assert.equal(r.progress[0].at, 0);
  r.run(1300);
  assert.equal(r.applied.length, 2, `状态只等普通动作，不等进度：${JSON.stringify(r.applied)}`);
  assert.ok(r.applied[1].at <= 1300);
});

// ---------------------------------------------------------------------------
// 6. 堆积（H8、H9）

/** 两秒里到达 count 条动作，三个参与方，关键与普通混着，每条事件后面跟一份状态。 */
function burst(seed: number, over: Partial<typeof settings> | null, frame: number, overrun: number, count = 120) {
  const r = rig({ settings: over ?? undefined, natural: (a, ms) => ms + Number(a.extra || 0) });
  let s = seed;
  const rnd = (): number => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
  r.jump();
  const lanes = [["p"], ["e"], ["q"], ["e", "q"], ["p", "e"]];
  for (let i = 0; i < count; i++) {
    const k = rnd();
    const kind = k < 0.25 ? "handoff" : k < 0.4 ? "stamp" : k < 0.7 ? "read" : k < 0.85 ? "write" : "think";
    const ln = kind === "handoff" ? lanes[3 + Math.floor(rnd() * 2)] : lanes[Math.floor(rnd() * 3)];
    r.act(kind, ln, { extra: rnd() < overrun ? 1500 : 0 });
    r.state();
    r.run(16, frame);
  }
  r.run(60000, frame);
  return r;
}

/** overrun 为渲染演得比声明时长更久的概率（走路、包裹在管道里走这类时间不在声明里）。 */
const BURSTS: { seed: number; over?: Partial<typeof settings>; frame: number; overrun: number }[] = [
  { seed: 1, frame: 16, overrun: 0 },
  { seed: 7, frame: 50, overrun: 0 },
  { seed: 42, over: { lagMs: 2000 }, frame: 16, overrun: 0 },
  { seed: 99, over: { lagMs: 8000, speed: 2 }, frame: 33, overrun: 0 },
  { seed: 3, frame: 16, overrun: 0.3 },
  { seed: 5, over: { lagMs: 3000 }, frame: 50, overrun: 0.5 },
];

for (const cfg of BURSTS) {
  const tag = `（种子 ${cfg.seed}，上限 ${cfg.over?.lagMs ?? 5000}，每帧 ${cfg.frame} 毫秒${cfg.overrun ? "，渲染常常超时" : ""}）`;
  test(`堆积：H8 落后有上限、H9 关键动作全部演完且不截断${tag}`, () => {
    const r = burst(cfg.seed, cfg.over ?? null, cfg.frame, cfg.overrun);
    const st = r.tl.inspect().stats;
    const lagMs = cfg.over?.lagMs ?? 5000;
    const minMs = cfg.over?.minMs ?? 300;
    assert.ok(st.maxLag <= lagMs + cfg.frame, `H8：最大落后 ${st.maxLag} 毫秒，超过上限 ${lagMs} 加一帧 ${cfg.frame}`);
    assert.equal(st.droppedKey, 0, `H9：关键动作不丢：${JSON.stringify(st)}`);
    assert.equal(st.startedKey, st.pushedKey, `H9：关键动作全部演完：${JSON.stringify(st)}`);
    assert.equal(st.cutKey, 0, `H9：正在演的关键动作不截断：${JSON.stringify(st)}`);
    assert.ok(!r.cut.some((c) => c.tier === "key"), `H9：没有关键动作被立刻结束：${JSON.stringify(r.cut)}`);
    assert.equal(st.late, 0, `H9：限时演完的都在限定的时间内演完：${JSON.stringify(st)}`);
    assert.ok(st.dropped > 0, `堆积时普通动作被丢掉：${JSON.stringify(st)}`);
    assert.ok(st.shortened > 0 || st.merged > 0, `堆积时关键动作被缩短或合并：${JSON.stringify(st)}`);
    for (const b of r.begun.filter((x) => x.tier === "key")) {
      assert.ok(b.ms >= minMs, `缩短的关键动作不短于最短时长 ${minMs}：${JSON.stringify(b)}`);
    }
    assert.equal(r.applied[r.applied.length - 1].pos, r.pos(), "最后显示的是最新的状态");
  });
}

// 6b. 缩到最短时长还放得下的堆积（一秒半里 40 条）：快进赶在上限之前，不用强制，也没有截断正在演的关键动作
for (const seed of [11, 23, 57]) {
  test(`放得下的堆积：快进赶在上限之前，不用强制（种子 ${seed}）`, () => {
    const r = burst(seed, null, 16, 0, 40);
    const st = r.tl.inspect().stats;
    assert.equal(st.forced, 0, `不用强制上画面：${JSON.stringify(st)}`);
    assert.ok(st.maxLag <= 5016, `H8：最大落后 ${st.maxLag} 毫秒，超过上限加一帧`);
    assert.equal(st.droppedKey, 0, `H9：关键动作不丢：${JSON.stringify(st)}`);
    assert.equal(st.startedKey, st.pushedKey, `H9：关键动作全部演完：${JSON.stringify(st)}`);
    assert.equal(st.cutKey, 0, `H9：正在演的关键动作不截断：${JSON.stringify(st)}`);
  });
}

// ---------------------------------------------------------------------------
// 7. 极端堆积

test("极端堆积：到了上限状态照样上画面，排着的关键动作接着演完，正在演的不截断", () => {
  const r = rig();
  r.jump();
  for (let i = 0; i < 120; i++) r.act(i % 2 ? "stamp" : "handoff", ["e"]);
  r.state();
  r.run(5200);
  const st = r.tl.inspect().stats;
  assert.equal(r.applied.length, 2, `到了上限，状态照样上画面：${JSON.stringify(r.applied)}`);
  assert.ok(r.applied[1].at <= 5016, `状态在上限之内上画面，实际在 ${r.applied[1].at} 毫秒`);
  assert.equal(st.forced, 1, `到了上限算一次强制：${JSON.stringify(st)}`);
  r.run(30000);
  const st2 = r.tl.inspect().stats;
  assert.equal(st2.startedKey, 120, `排着的关键动作全部演完：${JSON.stringify(st2)}`);
  assert.equal(st2.droppedKey, 0, `关键动作不丢：${JSON.stringify(st2)}`);
  assert.ok(st2.rushed >= 1, `正在演的关键动作被限定演完的时间：${JSON.stringify(st2)}`);
  assert.equal(st2.cutKey, 0, `关键动作不截断：${JSON.stringify(st2)}`);
  assert.equal(r.cut.length, 0, `没有被立刻结束的动作：${JSON.stringify(r.cut)}`);
  assert.equal(st2.late, 0, `限时演完的都在限定的时间内演完：${JSON.stringify(st2)}`);
});

// ---------------------------------------------------------------------------
// 7b. 限时演完

test("限时演完：来不及时正在演的关键动作不截断，渲染按加快倍率在限定的时间内演完", () => {
  const r = rig({ settings: { lagMs: 1500 }, natural: (_a, ms) => ms + 2000 });
  r.jump();
  r.act("handoff", ["e"]);
  r.act("handoff", ["e"]);
  r.state();
  r.run(16);
  r.run(200);
  const ins = r.tl.inspect();
  const first = ins.playing[0];
  assert.ok(first, `应当有一个正在演的动作：${JSON.stringify(ins)}`);
  assert.notEqual(first.rushBy, null, `正在演的关键动作被限定演完的时间：${JSON.stringify(ins)}`);
  assert.ok(ins.rate > 1, `加快倍率大于 1：${ins.rate}`);
  const by = first.rushBy as number;
  assert.ok(by - r.now() >= 0, `限定的时间还没有过去：${by} / ${r.now()}`);
  assert.ok(by >= 16 + 300, `限定的时间不短于最短时长：${by}`);
  r.run(by - r.now() + 150);
  const after = r.tl.inspect();
  assert.ok(!after.playing.some((p) => p.id === first.id), `限定的时间之内演完：${JSON.stringify(after)}`);
  assert.equal(r.cut.length, 0, `没有被截断的动作：${JSON.stringify(r.cut)}`);
  assert.equal(after.stats.late, 0, `没有超时：${JSON.stringify(after.stats)}`);
  r.run(20000);
  assert.equal(r.tl.inspect().rate, 1, "没有限时的动作时倍率是 1");
});

// ---------------------------------------------------------------------------
// 8. 合并

test("合并：同一个参与方连续的同类关键动作在来不及时合并成一次，算作开始演了", () => {
  const r = rig();
  r.jump();
  for (let i = 0; i < 12; i++) r.act("stamp", ["q"]);
  r.state();
  r.run(8000);
  const st = r.tl.inspect().stats;
  assert.ok(st.merged > 0, `连续的同类关键动作合并：${JSON.stringify(st)}`);
  assert.ok(r.begun.length < 12, `合并以后开始演的次数少于 12：${r.begun.length}`);
  assert.equal(st.startedKey, 12, `合并的动作算作开始演了：${st.startedKey}`);
  assert.ok(st.maxLag <= 5016, `状态在上限之内上画面：${st.maxLag}`);
});

// ---------------------------------------------------------------------------
// 9. 跳到最新

test("跳到最新：正在演的立刻结束，排着的清掉，直接显示给出的状态，不补播", () => {
  const r = rig();
  r.jump();
  r.act("handoff", ["e"]);
  r.act("read", ["e"]);
  r.act("stamp", ["q"]);
  r.state();
  r.run(100);
  const before = r.begun.length;
  r.jump();
  r.run(5000);
  assert.equal(r.cut.length, 2, `正在演的动作立刻结束：${JSON.stringify(r.cut)}`);
  assert.equal(r.begun.length, before, `排着的动作不再演：${r.begun.length} / ${before}`);
  assert.equal(r.applied[r.applied.length - 1].pos, r.pos(), "直接显示给出的状态");
  assert.equal(r.applied[r.applied.length - 1].at, 100, `跳到时直接上画面，不用等：${JSON.stringify(r.applied)}`);
});

// ---------------------------------------------------------------------------
// 10. 标签页在后台

test("后台切回：积下的状态没有逐份补上，积下的动作不补播", () => {
  const r = rig();
  r.jump();
  for (let i = 0; i < 200; i++) {
    r.act(i % 3 ? "read" : "handoff", [["p"], ["e"], ["q"]][i % 3]);
    r.state();
  }
  const piled = r.tl.inspect();
  r.jump();
  r.run(1000);
  const ins = r.tl.inspect();
  assert.equal(r.applied.length, 2, `积下的状态没有逐份补上：${r.applied.length}`);
  assert.equal(r.begun.length, 0, "积下的动作不补播");
  assert.equal(ins.queued, 0, `积下的动作清掉了（切回前排着 ${piled.queued} 条）`);
});

// ---------------------------------------------------------------------------
// 12. 倍率

test("倍率：声明时长乘以倍率", () => {
  const r = rig({ settings: { speed: 0.5 } });
  r.jump();
  r.act("handoff", ["e"]);
  r.run(16);
  assert.equal(r.begun[0].ms, 1000, "声明 2000 毫秒，倍率 0.5");
});

// ---------------------------------------------------------------------------
// 参数与入队的校验

test("参数：落后上限 5 秒、最短时长 0.3 秒、倍率 1、限时估算 2.5 秒、一个参与方排着的普通动作最多三条", () => {
  rig(); // 创建一条时间线时把 settings 复位成默认值
  assert.deepEqual({ ...settings }, { lagMs: 5000, minMs: 300, speed: 1 });
  assert.equal(RUSH_EXTRA, 2500);
  assert.equal(MAX_NORMAL, 3);
  assert.deepEqual([...TIERS], ["key", "normal", "progress"]);
});

function blankOptions(): TimelineOptions {
  return {
    clock: () => 0,
    classify: () => ({ tier: "normal", ms: 1, lanes: [] }),
    begin() {},
    cut() {},
    apply() {},
    progress() {},
  };
}

test("创建时间线：缺少回调时抛错", () => {
  const full = blankOptions();
  for (const key of ["clock", "classify", "begin", "cut", "apply", "progress"] as const) {
    const broken: Partial<TimelineOptions> = { ...full };
    delete broken[key];
    assert.throws(() => create(broken as TimelineOptions), /播放时间线缺少回调/);
  }
});

test("入队：动作要带位置与合法的级别，进度不进队；状态要带位置，没声明时长的不入队", () => {
  const r = rig({ decl: { broken: { tier: "normal", ms: -1 } } });
  assert.throws(() => r.tl.push({ kind: "read" } as never), /动作没有位置/);
  assert.throws(() => r.tl.push({ kind: "不存在的动作", position: 1 }), /动作的级别无效/);
  assert.throws(() => r.tl.push({ kind: "broken", position: 2 }), /动作没有声明时长/);
  assert.equal(r.tl.push({ kind: "think", position: 3 }), null, "进度动作不进队");
  assert.equal(r.progress.length, 1, "进度动作交给渲染");
  assert.throws(() => r.tl.state({} as never), /状态没有位置/);
  assert.throws(() => r.tl.jump({} as never), /状态没有位置/);
});
