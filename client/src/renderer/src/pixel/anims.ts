// 动作帧序列与缓动：由原型 v9 engine.js 第 4、5 节（an、animFrame、animDuration、ease、hash）
// 改写为 TypeScript。取帧只做纯计算：给定动作与经过时间，得到姿势名；工单 #176 的确定时钟依赖这一点。

import { ANIMS, POSES, type Pose } from "./registry.ts";

/** 尊重「减少动效」系统偏好：只取静止帧（原型 reducedMotion）。 */
export function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** 动作帧序列取帧（对应 engine.js 的 animFrame）：elapsed 为经过的毫秒。 */
export function animFrameAt(animName: string, elapsed: number, reduced = false): string {
  const a = ANIMS[animName];
  if (!a) throw new Error(`未知动作帧序列：${animName}`);
  if (reduced) return a.frames[a.still][0];
  let t = a.loop ? elapsed % a.total : Math.min(elapsed, a.total - 1);
  for (const fr of a.frames) {
    if (t < fr[1]) return fr[0];
    t -= fr[1];
  }
  return a.frames[a.frames.length - 1][0];
}

/** 动作总时长（毫秒）。 */
export function animDuration(name: string): number {
  const a = ANIMS[name];
  if (!a) throw new Error(`未知动作帧序列：${name}`);
  return a.total;
}

export function poseFor(name: string): Pose {
  const p = POSES[name];
  if (!p) throw new Error(`未知姿势：${name}`);
  return p;
}

/** 缓动曲线名 → 进度函数（对应 engine.js 的 P.ease）：t 归一到 0..1，返回 0..1 的进度。 */
export const EASE: Record<string, (t: number) => number> = {
  linear: (t) => t,
  inOut: (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2),
  out: (t) => 1 - Math.pow(1 - t, 3),
  in: (t) => t * t * t,
  outBack: (t) => {
    const c1 = 1.70158;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
  },
  bounce: (t) => {
    const n1 = 7.5625;
    const d1 = 2.75;
    if (t < 1 / d1) return n1 * t * t;
    if (t < 2 / d1) {
      t -= 1.5 / d1;
      return n1 * t * t + 0.75;
    }
    if (t < 2.5 / d1) {
      t -= 2.25 / d1;
      return n1 * t * t + 0.9375;
    }
    t -= 2.625 / d1;
    return n1 * t * t + 0.984375;
  },
};

/** 取缓动曲线；未知名字按线性处理，与原型一致。 */
export function ease(name: string, t: number): number {
  const fn = EASE[name];
  return fn ? fn(t) : t;
}

/** 稳定散列（原型 hash）：同一个整数每次得到同一个 0..1 的数。 */
export function hash(n: number): number {
  let x = (n | 0) * 374761393 + 668265263;
  x = (x ^ (x >>> 13)) * 1274126177;
  return ((x ^ (x >>> 16)) >>> 0) / 4294967296;
}
