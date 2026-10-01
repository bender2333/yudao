// 像素画面对象：PixiJS 8 的 Application 挂在宿主元素上，提供 setModel、playEvent、focus、resize、destroy
// 五个方法，接口与原型 v9 的 floor.js、room.js 一致（工单 #176 验收标准）。
// 状态与入参校验在 view-state.ts 里（可在 node --test 下验证）；这里只做渲染：
// 把每个小人的帧取成纹理贴到舞台上，缩放按 layoutFor 取整数倍、采样 nearest。

import { Application, Container, Sprite, Text } from "pixi.js";
import type { Clock } from "./clock.ts";
import { CHAR_H, PIXEL_FONT_STACK } from "./registry.ts";
import { layoutFor } from "./scale.ts";
import { charFrameTextures } from "./textures.ts";
import { createPixelViewState } from "./view-state.ts";
import type { OverlayModel, PixelEvent, PixelModel, PixelViewSize } from "./view-types.ts";

export type { ActorModel, OverlayModel, PixelEvent, PixelModel, PixelViewSize } from "./view-types.ts";

export interface PixelView {
  setModel(model: PixelModel): void;
  playEvent(event: PixelEvent): void;
  focus(id: string): void;
  resize(): void;
  destroy(): void;
  /** 画面逻辑尺寸，供宿主与测试读取。 */
  readonly size: PixelViewSize;
  /** 取某个小人的当前所在逻辑坐标（缩放前）。 */
  positionOf(id: string): { x: number; y: number } | null;
  /** 取某个小人此刻的姿势名（确定时钟下同样的时间必得同样的姿势）。 */
  poseOf(id: string): string | null;
  /** 当前聚焦的小人。 */
  focused(): string | null;
}

export interface PixelViewOptions extends PixelViewSize {
  host: HTMLElement;
  clock: Clock;
}

/** 建立像素画面：PixiJS 的 Application 挂在 host 上，尺寸与整数倍缩放由 resize 决定。 */
export async function createPixelView(opts: PixelViewOptions): Promise<PixelView> {
  const app = new Application();
  await app.init({ background: "#12101c", antialias: false, autoDensity: false, resolution: 1 });
  const canvas = app.canvas;
  canvas.style.imageRendering = "pixelated";
  canvas.style.display = "block";
  opts.host.appendChild(canvas);

  const world = new Container();
  const actorLayer = new Container();
  const overlayLayer = new Container();
  world.addChild(actorLayer, overlayLayer);
  app.stage.addChild(world);

  const state = createPixelViewState({ W: opts.W, H: opts.H, now: () => opts.clock.now(), onChange: () => draw() });

  function applyLayout(): void {
    const rect = opts.host.getBoundingClientRect();
    const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
    const lay = layoutFor(opts.W, opts.H, rect.width || opts.W, rect.height || opts.H, dpr);
    app.renderer.resize(lay.bufferW, lay.bufferH);
    canvas.style.width = `${lay.cssW}px`;
    canvas.style.height = `${lay.cssH}px`;
    world.scale.set(lay.k);
  }

  /** 按状态机里的动作与当前时间取姿势，贴上身体层与前景层两张纹理。 */
  function draw(): void {
    for (const child of actorLayer.removeChildren()) child.destroy({ children: true });
    for (const child of overlayLayer.removeChildren()) child.destroy({ children: true });
    const focusedId = state.focused();
    for (const a of state.actors()) {
      const pose = state.poseOf(a.id);
      if (!pose) continue;
      const tex = charFrameTextures(a.sprite, pose, null, a.hold, a.flip);
      const holder = new Container();
      for (const t of [tex.base, tex.front]) {
        const s = new Sprite(t);
        s.x = a.x;
        s.y = a.y;
        // 帧缓冲高 40、脚底在第 37 行，锚点落在脚底，小人便站在 (x, y)
        s.anchor.set(0, 37 / CHAR_H);
        s.roundPixels = true;
        holder.addChild(s);
      }
      if (focusedId === a.id) holder.tint = 0xfff6c8;
      actorLayer.addChild(holder);
    }
    for (const ov of state.overlays()) addOverlay(ov);
  }

  function addOverlay(ov: OverlayModel): void {
    const t = new Text({
      text: ov.text,
      style: {
        fontFamily: PIXEL_FONT_STACK,
        fontSize: 10,
        fill: ov.kind === "notice" ? "#ffd66b" : "#f4efe6",
        stroke: { color: "#12101c", width: 2 },
      },
    });
    t.resolution = 1;
    t.scale.set(0.5);
    t.x = ov.x;
    t.y = ov.y;
    t.roundPixels = true;
    overlayLayer.addChild(t);
  }

  applyLayout();
  draw();
  const offTick = opts.clock.onTick(() => draw());
  const onResize = (): void => {
    applyLayout();
    draw();
  };
  window.addEventListener("resize", onResize);

  return {
    size: { W: opts.W, H: opts.H },
    setModel: state.setModel,
    playEvent: state.playEvent,
    focus: state.focus,
    resize: () => {
      state.resize();
      onResize();
    },
    destroy: () => {
      state.destroy();
      offTick();
      window.removeEventListener("resize", onResize);
      if (canvas.parentNode === opts.host) opts.host.removeChild(canvas);
      app.destroy(false, { children: true });
    },
    positionOf: state.positionOf,
    poseOf: state.poseOf,
    focused: state.focused,
  };
}
