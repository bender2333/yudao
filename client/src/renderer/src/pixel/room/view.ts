// 部门房间的画面对象：PixiJS 挂在宿主元素上，提供 setModel、playEvent、resize、destroy、inspect
// （原型 v9 room.js 的对外接口与设计说明第 1 节，工单 #177）。
//
// 世界的推进（driver.ts）与绘制（render.ts）都不依赖 PixiJS；这里只把画好的画布贴到舞台，
// 缩放用最近邻（layoutFor 的整数倍），每帧由共用的时钟驱动。

import { Application, Sprite, Texture } from "pixi.js";
import type { Clock } from "../clock.ts";
import { layoutFor } from "../scale.ts";
import { createRoomDriver, type RoomDriver } from "./driver.ts";
import { RoomRenderer } from "./render.ts";
import { emptyRoomModel, type RoomModel } from "./room.ts";
import { H, W } from "./layout.ts";
import type { PixelFloorEvent, SceneLike } from "../world/types.ts";

export type { RoomModel } from "./room.ts";

/** 部门房间画面对象。 */
export interface RoomView {
  setModel(model: RoomModel): void;
  playEvent(event: PixelFloorEvent): void;
  /** 流式输出：把 attempt.live 已收到的文字交给正在做模型请求的角色（设计说明第 6 节）。 */
  setStreamText(text: string): void;
  resize(): void;
  destroy(): void;
  /** 画面逻辑尺寸，供宿主与测试读取。 */
  readonly size: { W: number; H: number };
  /** 世界（角色、场景与临时状态）与驱动（测试与回放读取）。 */
  inspect(): { driver: RoomDriver; scene: SceneLike; renderer: RoomRenderer };
}

export interface RoomViewOptions {
  host: HTMLElement;
  clock: Clock;
  department: string;
  /** 取 0..1 的随机数；回放比较时用确定的随机数。 */
  random?: () => number;
  /** 走动与包裹移动的补间；回放比较时用线性插值（与原型一致），传 null 关闭。 */
  tween?: ((target: Record<string, unknown>, vars: Record<string, unknown>) => { kill: () => void }) | null;
}

/** 建立一个部门房间画面：画好的画布贴到 PixiJS 的舞台上，整数倍最近邻缩放到容器宽度。 */
export async function createRoomView(opts: RoomViewOptions): Promise<RoomView> {
  const app = new Application();
  await app.init({ background: "#12101c", antialias: false, autoDensity: false, resolution: 1 });
  const canvas = app.canvas;
  canvas.style.imageRendering = "pixelated";
  canvas.style.display = "block";
  opts.host.appendChild(canvas);

  const surface = document.createElement("canvas");
  surface.width = W;
  surface.height = H;
  const ctx = surface.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;
  const texture = Texture.from(surface);
  const sprite = new Sprite(texture);
  app.stage.addChild(sprite);

  const driver = createRoomDriver({
    department: opts.department,
    sceneOptions: {
      W,
      H,
      random: opts.random ?? (() => Math.random()),
      reduced: reducedMotion(),
      tween: opts.tween === null ? undefined : (target, vars) => (opts.tween ?? opts.clock.tween)(target, vars),
      reapply: () => opts.clock.reapply(),
    },
  });
  const renderer = new RoomRenderer(driver, driver.scene);
  driver.setModel(emptyRoomModel(opts.department));

  let last = 0;

  function applyLayout(): void {
    const rect = opts.host.getBoundingClientRect();
    const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
    const lay = layoutFor(W, H, rect.width || W, rect.height || H, dpr);
    app.renderer.resize(lay.bufferW, lay.bufferH);
    canvas.style.width = `${lay.cssW}px`;
    canvas.style.height = `${lay.cssH}px`;
    sprite.scale.set(lay.k);
  }

  function draw(): void {
    ctx.clearRect(0, 0, W, H);
    renderer.draw(ctx);
    texture.source.update();
    app.renderer.render(app.stage);
  }

  applyLayout();
  draw();
  const offTick = opts.clock.onTick((elapsed) => {
    const delta = Math.max(0, elapsed - last);
    last = elapsed;
    driver.scene.stepScene(delta);
    driver.step();
    driver.scene.reapply();
    draw();
  });

  const onResize = (): void => {
    applyLayout();
    draw();
  };
  window.addEventListener("resize", onResize);
  // 宿主尺寸变化（窄屏下滚动条出现、侧栏展开）不一定伴随窗口 resize：
  // 直接观察宿主元素，尺寸变了就按新的宽度重排，画布不会比容器宽。
  const observer = typeof ResizeObserver === "undefined" ? null
    : new ResizeObserver(() => { applyLayout(); draw(); });
  observer?.observe(opts.host);

  return {
    size: { W, H },
    setModel(model) {
      driver.setModel(model);
      draw();
    },
    playEvent(event) {
      driver.playEvent(event);
      draw();
    },
    setStreamText(text) {
      driver.setStreamText(text);
      draw();
    },
    resize() {
      applyLayout();
      draw();
    },
    destroy() {
      offTick();
      window.removeEventListener("resize", onResize);
      observer?.disconnect();
      if (canvas.parentNode === opts.host) opts.host.removeChild(canvas);
      texture.destroy(true);
      app.destroy(false, { children: true });
    },
    inspect: () => ({ driver, scene: driver.scene, renderer }),
  };
}

/** 系统设置为减少动画。 */
function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
