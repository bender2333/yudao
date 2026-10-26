// 部门房间的画面对象：画布挂在宿主元素上，提供 setState、jump、play、stream、resize、destroy、inspect
// （原型 v13 js/pixel/room.js 的接口与画面与播放设计说明第 3 至 5 节，工单 #954）。
//
// 世界的推进（driver.ts）与绘制（render.ts）都不依赖画布与 WebGL；这里只把画好的画布挂到页面上，
// 画布按设备分辨率绘制（surface.ts：像素尺寸为逻辑尺寸乘整数倍 k，先设缩放再按逻辑坐标绘制，
// 工单 #365），每帧由共用的时钟驱动。画面时间的加快倍率由驱动的播放时间线给出。

import type { Clock } from "../clock.ts";
import { createPixelSurface } from "../surface.ts";
import { createRoomDriver, type RoomDriver } from "./driver.ts";
import { RoomRenderer } from "./render.ts";
import { emptyRoomData } from "./room.ts";
import { H, W } from "./layout.ts";
import type { PixelAction, PixelState } from "../contract.ts";
import type { SceneLike } from "../world/types.ts";

export type { RoomData } from "./room.ts";

/** 流式文字接在哪个角色头上（room 为部门，role 为角色 id、种类或名称）。 */
export interface RoomStreamWho {
  room?: string | null;
  role?: string | null;
}

/** 部门房间画面对象：只认画面合同（状态、动作）与实时内容（流式文字）。 */
export interface RoomView {
  /** 一份状态：等它之前的动作演完再上画面。 */
  setState(state: PixelState): void;
  /** 跳到最新：清空时间线，直接显示给出的状态（打开、重新同步、切换部门、标签页切回）。 */
  jump(state: PixelState): void;
  /** 一个动作：按位置进入播放时间线。 */
  play(action: PixelAction): void;
  /** 实时内容：流式文字，到了就显示，不进时间线。 */
  stream(who: RoomStreamWho, text: string): void;
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
  driver.jump(emptyRoomData(opts.department));

  let last = 0;

  function draw(): void {
    renderer.draw(surface.frame());
  }

  surface.resize();
  draw();
  const offTick = opts.clock.onTick((elapsed) => {
    const delta = Math.max(0, elapsed - last);
    last = elapsed;
    // 推进一帧：画面时间按时间线给出的加快倍率前进，再把本帧新建的补间落到当前时间上
    driver.step(delta);
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
    setState(state) {
      driver.setState(state);
      draw();
    },
    jump(state) {
      driver.jump(state);
      draw();
    },
    play(action) {
      driver.play(action);
      draw();
    },
    stream(who, text) {
      driver.stream(who, text);
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
