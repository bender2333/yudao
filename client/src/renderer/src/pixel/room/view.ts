// 部门房间的画面对象：画布挂在宿主元素上，提供 setModel、playEvent、resize、destroy、inspect
// （原型 v9 room.js 的对外接口与设计说明第 1 节，工单 #177）。
//
// 世界的推进（driver.ts）与绘制（render.ts）都不依赖画布与 WebGL；这里只把画好的画布挂到页面上，
// 画布按设备分辨率绘制（surface.ts：像素尺寸为逻辑尺寸乘整数倍 k，先设缩放再按逻辑坐标绘制，
// 工单 #365），每帧由共用的时钟驱动。

import type { Clock } from "../clock.ts";
import { createPixelSurface } from "../surface.ts";
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

/** 建立一个部门房间画面：画布按设备分辨率绘制，整数倍铺满容器宽度。 */
export async function createRoomView(opts: RoomViewOptions): Promise<RoomView> {
  // 画布按设备分辨率绘制：像素尺寸为 W×H 的整数倍，图形与文字都按设备分辨率光栅化
  const surface = createPixelSurface({ host: opts.host, W, H });

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

  function draw(): void {
    renderer.draw(surface.frame());
  }

  surface.resize();
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
    surface.resize();
    draw();
  };
  window.addEventListener("resize", onResize);
  // 宿主尺寸变化（窄屏下滚动条出现、侧栏展开）不一定伴随窗口 resize：
  // 直接观察宿主元素，尺寸变了就按新的宽度重排，画布不会比容器宽。
  const observer = typeof ResizeObserver === "undefined" ? null
    : new ResizeObserver(() => { surface.resize(); draw(); });
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
      surface.resize();
      draw();
    },
    destroy() {
      offTick();
      window.removeEventListener("resize", onResize);
      observer?.disconnect();
      if (surface.canvas.parentNode === opts.host) opts.host.removeChild(surface.canvas);
    },
    inspect: () => ({ driver, scene: driver.scene, renderer }),
  };
}

/** 系统设置为减少动画。 */
function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
