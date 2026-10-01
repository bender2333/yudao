// GSAP 与 PixiJS 共用的时钟（工单 #176 验收标准 2）。
// 正式运行时用 requestAnimationFrame 驱动，测试与回放时换成 createManualClock 手动推进时间。
// 关键点：每次回放前把 gsap.globalTimeline 的时间归零，GSAP 的补间位置只由「本次推进到第几毫秒」决定，
// 与墙钟无关；PixiJS 的 ticker 读同一个时钟的当前时间，两者看到的时间始终一致。

import { gsap } from "gsap";
import { Ticker } from "pixi.js";

/** GSAP 补间的最小接口：图鉴与画面只用到归零与结束。 */
export interface GsapTween {
  totalTime(value: number): GsapTween;
  kill(): void;
}

export interface Clock {
  /** 当前时间（毫秒，从本次运行的零点起算）。 */
  now(): number;
  /** 订阅时间推进；返回取消订阅的函数。回调收到本次的经过毫秒数。 */
  onTick(fn: (elapsedMs: number, deltaMs: number) => void): () => void;
  /**
   * 建立一个受本时钟驱动的 GSAP 补间：起点钉在时钟零点上，
   * 位置只由「推进到第几毫秒」决定，与建立补间时的墙钟无关。
   */
  tween(target: Record<string, unknown>, vars: Record<string, unknown>): GsapTween;
  /** 重置到零点并清掉本次运行的补间与订阅者（回放与测试用）。 */
  reset(): void;
  /** 停止推进并释放资源。 */
  destroy(): void;
}

type Listener = (elapsedMs: number, deltaMs: number) => void;

/** 让 GSAP 接受外部时间：关闭 lagSmoothing 与自动 ticker，由本模块统一驱动。 */
function sleepGsapTicker(): void {
  gsap.ticker.lagSmoothing(0);
  gsap.ticker.sleep();
  // PixiJS 的共享 ticker 也在跑；停掉它，时间才完全由本时钟给出
  Ticker.shared.autoStart = false;
  Ticker.shared.stop();
}

/**
 * 把 GSAP 的全局时间线复位，让下一次推进从头开始（可重复回放的前提）。
 * 只调用 totalTime(0) 不够：补间还留着上一次的起点，同一次推进拿到的位置会逐次不同；
 * 清空全局时间线并让根时钟停在零点，位置才只由「推进到第几毫秒」决定。
 */
/**
 * 手动时钟：由调用方用 advance 推进到指定的经过毫秒数。
 * 每一步都让 GSAP 走到同一时间点，因此同样的推进序列必得同样的补间位置。
 */
export function createManualClock(): Clock & { advance(toMs: number): void } {
  sleepGsapTicker();
  let now = 0;
  const listeners = new Set<Listener>();
  let destroyed = false;
  /** 本次回放的 GSAP 作用域：回放结束后 revert，下一次回放从干净状态开始。 */
  let ctx = gsap.context(() => {});

  /** 把 GSAP 的 ticker 时钟拨到给定秒数并更新根时钟。 */
  function seek(seconds: number): void {
    gsap.ticker.time = seconds;
    (gsap.updateRoot as (t: number, force?: boolean) => void)(seconds, true);
  }

  /** 让 GSAP 完成一次预热：第一次推进与之后的推进结果一致，位置才可重复。 */
  function prime(): void {
    seek(0);
    const warm = { x: 0 };
    const tw = gsap.to(warm, { x: 1, duration: 1 });
    for (let t = 100; t <= 1000; t += 100) seek(t / 1000);
    tw.kill();
    seek(0);
  }

  /** 回到零点：结束本次作用域、清掉残留补间，再建一个干净的作用域。 */
  function rewind(): void {
    ctx.revert();
    ctx = gsap.context(() => {});
    now = 0;
    seek(0);
  }

  prime();
  seek(0);

  return {
    now: () => now,
    onTick(fn) {
      if (destroyed) throw new Error("时钟已释放");
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    tween(target, vars) {
      if (destroyed) throw new Error("时钟已释放");
      return ctx.add ? (ctx.add(() => gsap.to(target, vars)) as unknown as GsapTween) : (gsap.to(target, vars) as unknown as GsapTween);
    },
    advance(toMs) {
      if (destroyed) throw new Error("时钟已释放");
      const delta = toMs - now;
      if (delta < 0) throw new Error("手动时钟不能倒退");
      now = toMs;
      // 根时间是「推进到的毫秒数」，补间位置只由它决定
      seek(now / 1000);
      for (const fn of [...listeners]) fn(now, delta);
    },
    reset() {
      rewind();
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      ctx.revert();
      listeners.clear();
    },
  };
}

/**
 * 实时时钟：用 requestAnimationFrame 推进，并把同一个时间同时交给 GSAP 与 PixiJS 的 ticker。
 * PixiJS 的 Application 使用 autoStart=false 并手动 update，避免它再启动自己的 ticker。
 */
export function createRafClock(raf: (cb: (t: number) => void) => number, now: () => number, cancel?: (handle: number) => void): Clock {
  sleepGsapTicker();
  let start: number | null = null;
  let nowMs = 0;
  const listeners = new Set<Listener>();
  let handle = 0;
  let ctx = gsap.context(() => {});
  const pixiTicker = Ticker.shared;
  pixiTicker.autoStart = false;
  pixiTicker.stop();
  gsap.ticker.time = 0;
  (gsap.updateRoot as (t: number, force?: boolean) => void)(0, true);

  const step = (stamp: number): void => {
    if (start === null) start = stamp;
    const elapsed = stamp - start;
    const delta = elapsed - nowMs;
    nowMs = elapsed;
    gsap.ticker.time = elapsed / 1000;
    (gsap.updateRoot as (t: number, force?: boolean) => void)(elapsed / 1000, true);
    pixiTicker.update(now());
    for (const fn of [...listeners]) fn(elapsed, delta);
    handle = raf(step);
  };
  handle = raf(step);

  return {
    now: () => nowMs,
    onTick(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    tween(target, vars) {
      return gsap.to(target, vars) as unknown as GsapTween;
    },
    reset() {
      start = null;
      nowMs = 0;
      ctx.revert();
      ctx = gsap.context(() => {});
      gsap.ticker.time = 0;
      (gsap.updateRoot as (t: number, force?: boolean) => void)(0, true);
      pixiTicker.update(0);
    },
    destroy() {
      if (handle && cancel) cancel(handle);
      ctx.revert();
      listeners.clear();
    },
  };
}
