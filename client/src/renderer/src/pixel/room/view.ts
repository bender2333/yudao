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
import { H, W, STATUS_TEXT } from "./layout.ts";
import type { PixelAction, PixelState } from "../contract.ts";
import type { SceneLike } from "../world/types.ts";

export type { RoomData } from "./room.ts";

/** 流式文字接在哪个角色头上（room 为部门，role 为角色 id、种类或名称）。 */
export interface RoomStreamWho {
  room?: string | null;
  role?: string | null;
}

/**
 * 房间承载事实的视觉通道（画面与播放设计说明第 8.1 节的房间那一行）：房间状态与状态文字、状态给出的姿势、
 * 角色与角色的状态、信箱与卷轴等物件的数量、头顶的流式文字。
 *
 * 只读状态给出的东西：工作台上的零件、抽屉、灯、动作的姿势与说话气泡属于表演层，不在这里。
 */
export interface RoomChannels {
  /** 上画面的状态来自的查询快照的位置。 */
  position: number;
  /** 房间状态与 CRT 上的状态文字。 */
  status: { value: string; text: string };
  /** 状态给出的姿势（哪个角色摆的、什么姿势）。 */
  pose: { role_id: string | null; anim: string } | null;
  /** 角色与角色的状态（状态给出的那一个，不是正在演的动作）。 */
  roles: { id: string; kind: string; status: string | null }[];
  /** 信箱、卷轴等物件的数量。 */
  objects: {
    mailbox: number;
    scrolls: number;
    summaries: number;
    pinned_notes: number;
    semantic_cards: number;
    letters_waiting: number;
  };
  /** 头顶的流式文字。 */
  stream: { role: string; text: string }[];
}

/** 读一份状态承载事实的视觉通道：状态给出的部分（动作期间的临时状态不算）。 */
function roomChannels(driver: RoomDriver): RoomChannels {
  const model = driver.model;
  const status = model.status || "idle";
  const actors = driver.actors();
  return {
    position: model.position,
    status: { value: status, text: STATUS_TEXT[status] ?? status },
    pose: model.pose ? { role_id: model.pose.role_id ?? null, anim: model.pose.anim } : null,
    roles: model.roles
      .map((r) => ({ id: r.id, kind: r.kind, status: r.status }))
      .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
    objects: {
      mailbox: model.mailbox || 0,
      scrolls: model.scrolls || 0,
      summaries: model.summaries || 0,
      pinned_notes: model.pinned_notes || 0,
      semantic_cards: model.semantic_cards || 0,
      letters_waiting: model.pipes?.letters_waiting || 0,
    },
    stream: actors
      .filter((a) => typeof a.streamText === "string" && a.streamText !== "")
      .map((a) => ({ role: a.id, text: String(a.streamText) }))
      .sort((a, b) => (a.role < b.role ? -1 : a.role > b.role ? 1 : 0)),
  };
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
  /**
   * 关掉或打开表演层（待机活动与动作）的测试入口（设计说明第 8.1 节的 H2）。
   * 关掉以后动作与特效不演，画面只画状态给出的样子；承载事实的通道不受影响。
   */
  performance(on: boolean): void;
  /** 画面逻辑尺寸，供宿主与测试读取。 */
  readonly size: { W: number; H: number };
  /** 世界（角色、场景与临时状态）与驱动（测试与回放读取），以及承载事实的视觉通道。 */
  inspect(): {
    driver: RoomDriver; scene: SceneLike; renderer: RoomRenderer;
    /** 承载事实的视觉通道（设计说明第 8.1 节的房间那一行）。 */
    channels: () => RoomChannels;
  };
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

  let last = opts.clock.now();

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
    performance(on) {
      // 待机活动与动作一起关掉：动作停在原处，不再开始新的步子（承载事实的通道只由状态决定）
      driver.scene.performance = on;
      driver.scene.autonomy = on;
      if (!on) for (const actor of driver.scene.actors.slice()) driver.scene.cancel(actor);
      draw();
    },
    destroy() {
      offTick();
      window.removeEventListener("resize", onResize);
      observer?.disconnect();
      if (surface.canvas.parentNode === opts.host) opts.host.removeChild(surface.canvas);
    },
    inspect: () => ({ driver, scene: driver.scene, renderer, channels: () => roomChannels(driver) }),
  };
}

/** 系统设置为减少动画。 */
function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
