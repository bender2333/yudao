// 画面对象的状态机：小人、动作、焦点与尺寸的读写，与 PixiJS 渲染分离。
// 这样五方法（setModel、playEvent、focus、resize、destroy）的入参校验与状态变化可以在 node --test 下验证，
// 渲染部分（纹理、整数倍最近邻缩放）由 view.ts 接到 PixiJS 上，浏览器行为由 e2e 覆盖。

import { animFrameAt, reducedMotion } from "./anims.ts";
import type { ActorModel, OverlayModel, PixelEvent, PixelModel, PixelViewSize } from "./view-types.ts";

export interface ActorState {
  id: string;
  sprite: string;
  action: string;
  hold: string | null;
  flip: boolean;
  /** 本段动作开始的时钟毫秒数。 */
  from: number;
  x: number;
  y: number;
}

export interface PixelViewState {
  setModel(model: PixelModel): void;
  playEvent(event: PixelEvent): void;
  focus(id: string): void;
  resize(): void;
  destroy(): void;
  readonly size: PixelViewSize;
  positionOf(id: string): { x: number; y: number } | null;
  poseOf(id: string): string | null;
  focused(): string | null;
  actors(): ActorState[];
  overlays(): OverlayModel[];
  destroyed(): boolean;
  /** 取当前时钟毫秒数（由宿主注入，测试用固定值）。 */
  advance(toMs: number): void;
}

export interface ViewStateOptions extends PixelViewSize {
  /** 取当前时间（毫秒）。 */
  now: () => number;
  /** 状态变化后的回调（渲染层据此重画）。 */
  onChange?: () => void;
  /** 测试与回放用：手动把时钟推到某个时刻（不传时用注入的 now）。 */
  advanceTo?: (ms: number) => void;
}

/** 建立画面状态机：宿主（React 组件）注入时钟与变化回调。 */
export function createPixelViewState(opts: ViewStateOptions): PixelViewState {
  let actors: ActorState[] = [];
  let overlayList: OverlayModel[] = [];
  let focusedId: string | null = null;
  let destroyed = false;
  let manual: number | null = null;
  const nowMs = (): number => manual ?? opts.now();

  const changed = (): void => {
    opts.onChange?.();
  };

  const byId = (id: string): ActorState => {
    const a = actors.find((x) => x.id === id);
    if (!a) throw new Error(`画面里没有这个小人：${id}`);
    return a;
  };

  return {
    size: { W: opts.W, H: opts.H },
    setModel(model) {
      if (!model || !Array.isArray(model.items)) throw new Error("setModel 需要含 items 数组的画面数据");
      actors = model.items.map((item: ActorModel) => ({
        id: item.id,
        sprite: item.sprite,
        action: item.action ?? "idle",
        hold: item.hold ?? null,
        flip: Boolean(item.flip),
        from: nowMs(),
        x: item.x,
        y: item.y,
      }));
      overlayList = model.overlays ?? [];
      focusedId = null;
      changed();
    },
    playEvent(event) {
      if (!event || !event.type) throw new Error("playEvent 需要事件对象");
      if (event.actorId) {
        const a = byId(event.actorId);
        if (event.action) {
          a.action = event.action;
          a.from = nowMs() - (event.at ?? 0);
        }
        if (event.hold !== undefined) a.hold = event.hold;
      }
      changed();
    },
    focus(id) {
      byId(id);
      focusedId = id;
      changed();
    },
    resize() {
      changed();
    },
    destroy() {
      destroyed = true;
      actors = [];
      overlayList = [];
      focusedId = null;
    },
    positionOf(id) {
      const a = actors.find((x) => x.id === id);
      return a ? { x: a.x, y: a.y } : null;
    },
    poseOf(id) {
      const a = actors.find((x) => x.id === id);
      if (!a) return null;
      // 与画面渲染同一条取帧路径：同样经过时间必得同样的姿势
      return animFrameAt(a.action, Math.max(0, nowMs() - a.from), reducedMotion());
    },
    focused() {
      return focusedId;
    },
    actors() {
      return actors.slice();
    },
    overlays() {
      return overlayList.slice();
    },
    destroyed() {
      return destroyed;
    },
    advance(toMs) {
      manual = toMs;
    },
  };
}
