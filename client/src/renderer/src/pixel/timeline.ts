// 播放时间线（画面与播放设计说明第 5.2 节、原型 v13 js/pixel/timeline.js、工单 #951）：决定演什么、什么时候演、丢什么。
// 楼、楼层、房间三个场景各有一条，规则只写在这里。
//
// 纯逻辑：不碰画布，不读页面的时钟，时钟由创建者传入（clock() 返回毫秒）。
//
// 输入：动作（画面合同，带 position）、状态（画面合同，带 position）、跳到最新、渲染报告某个动作演完。
// 输出（回调）：开始演一个动作、立刻结束一个动作（普通动作与跳到最新）、把一份状态放上画面、显示一个进度动作；
// 另有 rate()：渲染要把画面里的时间推进得比真实时间快几倍（关键动作被要求限时演完时大于 1）。
//
// 规则：
// - 动作按位置进入时间线。一个动作占用它的参与方（lanes，通常是角色）；同一个参与方一次只演一件事，不同参与方可以同时演。
// - 动作分三级：关键一定演，堆积时可以缩短；普通排队演，排得太长或画面落后超过上限时丢掉；进度不排队，到了就交给渲染。
// - 动作至少演满声明的时长（ms），并且等渲染报告演完（done）才结束。
// - 状态只等位置不大于它、还在队里或正在演的动作；这些动作结束以后它上画面，没有这样的动作时下一帧就上画面。
// - 画面落后上限：一份状态到达以后最多等 lagMs。来不及时快进：普通动作丢掉，同一个参与方连续的同类关键动作合并成一次，
//   关键动作按比例缩短（最短 minMs）；缩短的和到了上限仍没有演完的关键动作不截断，限定在时间之内演完：
//   rate() 把画面时间加快，剩下的部分（包括包裹沿管道走完）在限定的时间内演完。状态在上限到了时照样上画面，排着的关键动作接着演。
// - 跳到最新：清空时间线，正在演的立刻结束，直接显示给出的状态，不补播。

import type { PixelAction, PixelState } from "./contract.ts";

/** 三个场景共用的播放参数：落后上限、缩短时的最短时长、声明时长的倍率（2026-10-25 用户确认）。 */
export const settings = { lagMs: 5000, minMs: 300, speed: 1 };

/** 一个参与方排着的普通动作最多几条，再多就丢掉最早的一条。 */
export const MAX_NORMAL = 3;

/** 动作的级别（tier）：关键、普通、进度。 */
export const TIERS = ["key", "normal", "progress"] as const;
export type Tier = (typeof TIERS)[number];

/** 限时演完的动作，剩下的部分最长按「声明时长 + 这个数」估算（毫秒）：声明里不含小人走路与包裹在管道里走的时间。 */
export const RUSH_EXTRA = 2500;
/** 加快倍率的分母下限：离限定的时间只剩这么多毫秒时不再继续抬高倍率。 */
const RUSH_FLOOR = 20;
/** 过了限定的时间这么多毫秒还没演完，才记为超时（一帧之内的误差不算）。 */
const RUSH_GRACE = 100;

/** 场景的声明表给出的：级别、声明时长、参与方。 */
export interface ActionClass {
  tier: Tier;
  /** 声明的时长（毫秒）。 */
  ms: number;
  /** 这个动作占用哪些参与方（通常是角色）。 */
  lanes?: string[];
}

/**
 * 时间线里的一个动作条目。
 * ms0：声明的时长（乘过倍率）；ms：缩短以后的时长；until：最早结束的时间；rushBy：限定演完的时间（没有限定时为 null）。
 */
export interface TimelineEntry {
  id: number;
  action: PixelAction;
  /** 动作的位置（来源事件的位置）。 */
  pos: number;
  tier: Tier;
  ms: number;
  ms0: number;
  lanes: string[];
  arrivedAt: number;
  startAt: number | null;
  until: number | null;
  doneAt: number | null;
  rushBy: number | null;
  late: boolean;
  short: boolean;
  merged: number;
}

/** 时间线的计数（调节面板的读数与测试用）。 */
export interface TimelineStats {
  pushed: number;
  pushedKey: number;
  started: number;
  startedKey: number;
  dropped: number;
  droppedKey: number;
  merged: number;
  shortened: number;
  cut: number;
  cutKey: number;
  rushed: number;
  late: number;
  forced: number;
  maxLag: number;
}

/** 正在演的一个动作（inspect 的读数）。 */
export interface PlayingEntry {
  id: number;
  kind: string;
  lanes: string[];
  tier: Tier;
  ms: number;
  rushBy: number | null;
}

/** 时间线此刻的读数（inspect）：画面上的位置、排着的几份状态、落后多少、加快倍率与计数。 */
export interface TimelineInspect {
  shown: number | null;
  pending: number;
  lag: number;
  rate: number;
  queued: number;
  playing: PlayingEntry[];
  stats: TimelineStats;
}

/** 创建一条时间线需要的回调：时钟、声明表的查询、开始演、立刻结束、状态上画面、进度动作。 */
export interface TimelineOptions {
  /** 当前时间（毫秒）。 */
  clock: () => number;
  /** 按场景的声明表给出级别、时长与参与方。 */
  classify: (action: PixelAction) => ActionClass;
  begin: (entry: TimelineEntry) => void;
  cut: (entry: TimelineEntry) => void;
  apply: (state: PixelState) => void;
  progress: (action: PixelAction) => void;
}

/** 一条时间线：场景只经过这几个口子与它打交道。 */
export interface Timeline {
  push(action: PixelAction): TimelineEntry | null;
  state(state: PixelState): void;
  jump(state: PixelState): void;
  done(id: number): void;
  tick(): void;
  rate(): number;
  inspect(): TimelineInspect;
}

/** 还没上画面的一份状态。 */
interface PendingState {
  state: PixelState;
  pos: number;
  arrivedAt: number;
}

export function create(o: TimelineOptions): Timeline {
  (["clock", "classify", "begin", "cut", "apply", "progress"] as const).forEach((k) => {
    if (typeof o[k] !== "function") throw new Error("播放时间线缺少回调：" + k);
  });
  let seq = 0;
  let entries: TimelineEntry[] = [];
  let pending: PendingState[] = [];
  let shown: number | null = null;
  const stats: TimelineStats = {
    pushed: 0, pushedKey: 0, started: 0, startedKey: 0, dropped: 0, droppedKey: 0, merged: 0, shortened: 0,
    cut: 0, cutKey: 0, rushed: 0, late: 0, forced: 0, maxLag: 0,
  };

  const playing = (e: TimelineEntry): boolean => e.startAt !== null;
  const queued = (e: TimelineEntry): boolean => e.startAt === null;
  const shares = (a: TimelineEntry, b: TimelineEntry): boolean => a.lanes.some((l) => b.lanes.includes(l));
  const sameLanes = (a: TimelineEntry, b: TimelineEntry): boolean =>
    a.lanes.length === b.lanes.length && a.lanes.every((l, i) => l === b.lanes[i]);

  function remove(e: TimelineEntry): void {
    entries = entries.filter((x) => x !== e);
  }

  function drop(e: TimelineEntry): void {
    remove(e);
    stats.dropped += 1;
    if (e.tier === "key") throw new Error("关键动作不能丢掉：" + e.action.kind);
  }

  // 结束一个正在演的动作；byCut 为真时立刻停掉它（只用于普通动作）
  function end(e: TimelineEntry, byCut: boolean): void {
    remove(e);
    if (!byCut) return;
    if (e.tier === "key") stats.cutKey += 1;
    stats.cut += 1;
    o.cut(e);
  }

  // 限定一个正在演的关键动作在 by 之前演完：不截断，渲染按 rate() 加快剩下的部分
  function rush(e: TimelineEntry, by: number): void {
    if (e.rushBy !== null && e.rushBy <= by) return;
    if (e.rushBy === null) stats.rushed += 1;
    e.rushBy = by;
  }

  function push(a: PixelAction): TimelineEntry | null {
    if (!a || !a.kind) throw new Error("时间线需要画面合同的动作");
    if (!Number.isFinite(a.position)) throw new Error("动作没有位置：" + a.kind);
    const c = o.classify(a);
    if (!c || !TIERS.includes(c.tier)) throw new Error("动作的级别无效：" + a.kind);
    stats.pushed += 1;
    if (c.tier === "progress") {
      o.progress(a);
      return null;
    }
    if (!(c.ms >= 0)) throw new Error("动作没有声明时长：" + a.kind);
    if (c.tier === "key") stats.pushedKey += 1;
    const ms = c.ms * settings.speed;
    const e: TimelineEntry = {
      id: ++seq, action: a, pos: a.position, tier: c.tier, ms, ms0: ms, lanes: c.lanes ?? [],
      arrivedAt: o.clock(), startAt: null, until: null, doneAt: null, rushBy: null, late: false, short: false, merged: 0,
    };
    // 按位置插入：位置更大的、还没有开始的动作排在它后面
    let i = entries.length;
    while (i > 0 && queued(entries[i - 1]) && entries[i - 1].pos > e.pos) i -= 1;
    entries.splice(i, 0, e);
    // 队伍过长：这个动作经过的每个参与方，排着的普通动作超过上限时丢掉最早的一条
    e.lanes.forEach((lane) => {
      let list = entries.filter((x) => queued(x) && x.tier === "normal" && x.lanes.includes(lane));
      while (list.length > MAX_NORMAL) {
        drop(list[0]);
        list = list.slice(1);
      }
    });
    return e;
  }

  function state(s: PixelState): void {
    if (!s || !Number.isFinite(s.position)) throw new Error("状态没有位置");
    // 比画面上的状态还旧的结果（跳到最新以后才回来的查询）不再上画面
    if (shown !== null && s.position < shown) return;
    pending.push({ state: s, pos: s.position, arrivedAt: o.clock() });
  }

  function jump(s: PixelState): void {
    if (!s || !Number.isFinite(s.position)) throw new Error("状态没有位置");
    entries.filter(playing).forEach((e) => {
      stats.cut += 1;
      o.cut(e);
    });
    entries = [];
    pending = [];
    shown = s.position;
    o.apply(s);
  }

  function done(id: number): void {
    const e = entries.find((x) => x.id === id);
    if (e && e.doneAt === null) e.doneAt = o.clock();
  }

  const blockersOf = (pos: number): TimelineEntry[] => entries.filter((e) => e.pos <= pos);

  // 每个参与方还要多久：限定了演完时间的正在演的动作按限定的时间算；其余正在演的按声明时长算剩下的部分，
  // 已经演满声明时长、渲染还没演完的按一个最短时长算；排着的按声明时长；不占参与方的动作各算各的
  function need(list: TimelineEntry[], now: number): number {
    const per: Record<string, number> = {};
    let free = 0;
    list.forEach((e) => {
      const over = playing(e) && e.doneAt === null && now >= (e.until as number);
      const left = !playing(e) ? e.ms : e.rushBy !== null ? Math.max(0, e.rushBy - now) : over ? settings.minMs : Math.max(0, (e.until as number) - now);
      if (!e.lanes.length) {
        free = Math.max(free, left);
        return;
      }
      e.lanes.forEach((l) => {
        per[l] = (per[l] || 0) + left;
      });
    });
    return Math.max(free, ...Object.values(per), 0);
  }

  // 最紧的一份状态：没上画面的状态里，剩下的时间与它前面的动作还要多久之比最小的一份
  function tightest(now: number): { p: PendingState; ratio: number } | null {
    let worst: { p: PendingState; ratio: number } | null = null;
    pending.forEach((p) => {
      const n = need(blockersOf(p.pos), now);
      if (n <= 0) return;
      const ratio = (p.arrivedAt + settings.lagMs - now) / n;
      if (!worst || ratio < worst.ratio) worst = { p, ratio };
    });
    return worst;
  }

  // 快进：有状态来不及在上限之内上画面时，按规则丢、合并、缩短它前面的动作
  function fastForward(now: number): void {
    let w = tightest(now);
    if (!w || w.ratio >= 1) return;
    blockersOf(w.p.pos).filter((e) => e.tier === "normal").forEach((e) => {
      if (playing(e)) end(e, true);
      else drop(e);
    });
    w = tightest(now);
    if (!w || w.ratio >= 1) return;
    // 同一个参与方连续排着的同类关键动作并进第一条：内容取最新的一条，位置取最大的
    const list = blockersOf(w.p.pos).filter(queued);
    for (let i = 0; i < list.length; i++) {
      const a = list[i];
      if (!entries.includes(a)) continue;
      for (let j = i + 1; j < list.length; j++) {
        const b = list[j];
        if (!entries.includes(b)) continue;
        if (!shares(a, b)) continue;
        if (b.action.kind !== a.action.kind || !sameLanes(a, b)) break;
        a.action = b.action;
        a.pos = Math.max(a.pos, b.pos);
        a.merged += 1 + b.merged;
        remove(b);
        stats.merged += 1;
      }
    }
    w = tightest(now);
    // 已经过了上限的由第 4 步强制上画面
    if (!w || w.ratio >= 1 || w.ratio <= 0) return;
    const k = w.ratio;
    blockersOf(w.p.pos).forEach((e) => {
      if (playing(e)) {
        // 正在演的关键动作不截断：限定一个演完的时间（按比例缩短，不短于最短时长），渲染把剩下的部分加快
        const left = Math.max(0, (e.until as number) - now);
        rush(e, Math.max((e.startAt as number) + settings.minMs, now + Math.max(left * k, settings.minMs)));
      } else {
        const ms = Math.max(settings.minMs, e.ms * k);
        if (ms < e.ms) {
          e.ms = ms;
          if (!e.short) stats.shortened += 1;
          e.short = true;
        }
      }
    });
  }

  function tick(): void {
    const now = o.clock();
    // 1. 结束：至少演满声明的时长并且渲染报告演完；限定了演完时间的，渲染演完就结束。过了限定的时间还没演完的记一次
    entries.filter(playing).forEach((e) => {
      if (e.doneAt !== null && (e.rushBy !== null || now >= (e.until as number))) end(e, false);
      else if (e.rushBy !== null && now > e.rushBy + RUSH_GRACE && !e.late) {
        e.late = true;
        stats.late += 1;
      }
    });
    // 2. 快进
    if (pending.length) fastForward(now);
    // 3. 开始：参与方都空着，并且这些参与方上没有位置更早、还排着的动作
    entries.slice().forEach((e) => {
      if (!queued(e) || !entries.includes(e)) return;
      const busy = entries.some((x) => x !== e && shares(x, e) && (playing(x) || entries.indexOf(x) < entries.indexOf(e)));
      if (busy) return;
      e.startAt = now;
      e.until = now + e.ms;
      if (e.short) rush(e, now + e.ms);
      stats.started += 1;
      if (e.tier === "key") stats.startedKey += 1 + e.merged;
      o.begin(e);
    });
    // 4. 状态上画面：前面的动作都结束了的最新一份；或者到了落后上限的最新一份（它前面正在演的关键动作限定在最短时长内演完，
    // 正在演的普通动作立刻结束，排着的普通动作丢掉）。
    // 落后多少按最早一份没上画面的状态等了多久算，在上画面之前量（逐帧推进，最多比上限多一帧）
    const lag = pending.length ? now - pending[0].arrivedAt : 0;
    if (lag > stats.maxLag) stats.maxLag = lag;
    let k = -1;
    pending.forEach((p, i) => {
      if (!blockersOf(p.pos).length || now >= p.arrivedAt + settings.lagMs) k = i;
    });
    if (k >= 0) {
      const p = pending[k];
      const left = blockersOf(p.pos);
      if (left.length) {
        stats.forced += 1;
        left.forEach((e) => {
          if (playing(e) && e.tier === "key") rush(e, now + settings.minMs);
          else if (playing(e)) end(e, true);
          else if (e.tier === "normal") drop(e);
        });
      }
      pending = pending.slice(k + 1);
      shown = p.pos;
      o.apply(p.state);
    }
  }

  // 画面时间要比真实时间快几倍：限定了演完时间的正在演的动作，剩下的部分按「声明时长 + 估算的走路与包裹时间」
  // 在限定的时间内演完，离限定的时间越近倍率越高；没有这样的动作时是 1
  function rate(): number {
    const now = o.clock();
    let r = 1;
    entries.filter(playing).forEach((e) => {
      if (e.rushBy === null || e.doneAt !== null) return;
      r = Math.max(r, (e.ms0 + RUSH_EXTRA) / Math.max((e.rushBy as number) - now, RUSH_FLOOR));
    });
    return r;
  }

  function inspect(): TimelineInspect {
    const now = o.clock();
    return {
      shown, pending: pending.length, lag: pending.length ? now - pending[0].arrivedAt : 0, rate: rate(),
      queued: entries.filter(queued).length,
      playing: entries.filter(playing).map((e) => ({ id: e.id, kind: e.action.kind, lanes: e.lanes.slice(), tier: e.tier, ms: e.ms, rushBy: e.rushBy })),
      stats: { ...stats },
    };
  }

  return { push, state, jump, done, tick, rate, inspect };
}
