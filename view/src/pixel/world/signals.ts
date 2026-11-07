// 命名信号（原型 ecs.js 第 3.4 节）：不需要角色去做什么的画面指示，在毫秒内为真，可以带一个值。
// 门缝亮灯、信箱闪、监控屏告警、设备闪光都用它；画面按名字读取。

import type { Signal, World } from "./types.ts";

export interface SignalScene {
  realT: number;
}

export function signal(world: World, scene: SignalScene, name: string, ms: number, value?: unknown): void {
  world.signals[name] = { until: scene.realT + ms, value: value === undefined ? true : value };
}

export function signalOn(world: World, scene: SignalScene, name: string): boolean {
  const s: Signal | undefined = world.signals[name];
  return Boolean(s) && s.until > scene.realT;
}

export function signalValue(world: World, scene: SignalScene, name: string): unknown {
  return signalOn(world, scene, name) ? world.signals[name].value : null;
}
