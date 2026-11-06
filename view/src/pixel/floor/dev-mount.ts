// 开发构建里的像素画面测试入口（对应原型 v13 checks/behaviors.js 在浏览器里驱动画面的做法，工单 #179、#953）。
// 端到端测试用它把项目楼层画面用给定的数据挂到一个独立容器上，再直接驱动世界、卡片与点击。
// 只在开发构建里由 main.tsx 安装（import.meta.env.DEV），构建产物里不出现。

import { createManualClock, type Clock } from "../clock.ts";
import { createFloorView, floorTestHooks, type FloorTestHooks, type FloorView } from "./view.ts";
import { H, W } from "./render.ts";
import type { DecisionAnswer, DecisionResult } from "./card.ts";
import type { DecisionFace, FloorModel } from "../world/types.ts";
import type { PixelAction } from "../contract.ts";

/** 挂载一个楼层画面并返回驱动它的句柄。 */
export interface PixelFloorTestMount {
  view: FloorView;
  hooks: FloorTestHooks;
  /** 换成新的状态（与 FloorScreen 的 setState 同一入口：等它之前的动作演完再上画面）。 */
  setModel: (model: FloorModel) => void;
  /** 换成新的状态并直接显示（跳到最新）。 */
  jump: (model: FloorModel) => void;
  /** 播一个动作。 */
  play: (action: PixelAction) => void;
  /** 换成新的决定卡片（实时内容）。 */
  setDecisions: (list: DecisionFace[]) => void;
  /** 推进给定的毫秒数（手动时钟）。 */
  step: (ms: number) => void;
  /** 在画面逻辑坐标上点一下（与真实点击同一条路）。 */
  click: (x: number, y: number) => void;
  /** 在画布上派发一次点击（带坐标换算）。 */
  clickCanvas: (x: number, y: number) => void;
  /** 回答过的记录（onDecide 收到的载荷）。 */
  answers: DecisionAnswer[];
  /** 卸载。 */
  destroy: () => void;
}

/** 把像素画面测试入口装到 window 上（只在开发构建里调用）。 */
export function installDevMount(): void {
  window.__pixelFloorTest = { mount: mountFloor };
}

async function mountFloor(model: FloorModel, opts?: { answer?: (payload: DecisionAnswer) => DecisionResult }): Promise<PixelFloorTestMount> {
  const host = document.createElement("div");
  host.style.cssText = `position:fixed;left:0;top:0;width:${W}px;height:${H}px;z-index:99999;background:#000`;
  document.body.appendChild(host);
  const clock: Clock & { advance(toMs: number): void } = createManualClock();
  // 手动时钟的推进是异步的（requestAnimationFrame 由测试驱动），这里用一个每步推进的时间点
  let elapsed = 0;
  const answers: DecisionAnswer[] = [];
  const view = await createFloorView({
    host,
    clock,
    cardHost: host,
    onDecide: (payload) => {
      answers.push(payload);
      return opts?.answer ? opts.answer(payload) : { accepted: true };
    },
    onGo: () => {},
  });
  // 测试给的模型可能没有位置（画面合同要求带位置）：补上 0，其余原样
  const positioned = (m: FloorModel): FloorModel => ({ ...m, position: Number.isFinite(m.position) ? m.position : 0 });
  view.jump(positioned(model));
  view.setDecisions(model.decisions ?? []);
  const hooks = floorTestHooks(view, () => view.jump(positioned(model)));

  const rectOf = (): DOMRect => {
    const canvas = host.querySelector("canvas");
    if (!canvas) throw new Error("楼层画面没有画布");
    return canvas.getBoundingClientRect();
  };

  return {
    view,
    hooks,
    answers,
    setModel: (next) => {
      view.setState(positioned(next));
      view.setDecisions(next.decisions ?? []);
    },
    jump: (next) => view.jump(positioned(next)),
    play: (action) => view.play(action),
    setDecisions: (list) => view.setDecisions(list),
    step: (ms) => {
      elapsed += ms;
      clock.advance(elapsed);
    },
    click: (x, y) => {
      // 直接按画面逻辑坐标点击（端到端测试用，绕过画布缩放）
      const canvas = host.querySelector("canvas");
      if (!canvas) throw new Error("楼层画面没有画布");
      const rect = rectOf();
      const clientX = rect.left + (x / W) * rect.width;
      const clientY = rect.top + (y / H) * rect.height;
      canvas.dispatchEvent(new MouseEvent("click", { clientX, clientY, bubbles: true }));
    },
    clickCanvas: (x, y) => {
      const canvas = host.querySelector("canvas");
      if (!canvas) throw new Error("楼层画面没有画布");
      canvas.dispatchEvent(new MouseEvent("click", { clientX: x, clientY: y, bubbles: true }));
    },
    destroy: () => {
      view.destroy();
      host.remove();
      clock.destroy();
    },
  };
}
