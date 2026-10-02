// 项目楼层的画面对象：PixiJS 挂在宿主元素上，提供 setModel、playEvent、focus、setOverlay、resize、destroy
// （原型 v9 floor.js 的对外接口与设计说明第 5.2 至 5.7 节，工单 #82）。
//
// 世界的推进（floor.ts）与绘制（render.ts）都不依赖 PixiJS；这里只把画好的画布贴到舞台，
// 缩放用最近邻（layoutFor 的整数倍），每帧由共用的时钟驱动。

import { Application, Sprite, Texture } from "pixi.js";
import type { Clock } from "../clock.ts";
import { layoutFor } from "../scale.ts";
import { buildCatalog } from "./../world/floor-decl.ts";
import { createFloorDriver, createFloorState, type FloorDriver, type FloorState } from "./../world/floor.ts";
import { createScene } from "./../world/scene.ts";
import { FloorRenderer, H, W } from "./render.ts";
import { ROOM_VISUALS } from "./render-decl.ts";
import type { FloorModel, PixelFloorEvent, SceneLike } from "../world/types.ts";
import type { TimeText } from "../world/types.ts";

export type { FloorModel, PixelFloorEvent } from "../world/types.ts";

/** 概览页与测试共用的时间写法（原型 Y9.time）。 */
export const FLOOR_TIME: TimeText = {
  clock: (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  },
  duration: (sec) => {
    if (sec < 60) return `${Math.round(sec)} 秒`;
    if (sec < 3600) return `${Math.round(sec / 60)} 分`;
    return `${Math.round(sec / 3600)} 小时`;
  },
};

/** 项目楼层画面对象。 */
export interface FloorView {
  setModel(model: FloorModel): void;
  playEvent(event: PixelFloorEvent): void;
  focus(id: string | null): void;
  setOverlay(id: string | null, data: unknown): void;
  resize(): void;
  destroy(): void;
  /** 画面逻辑尺寸，供宿主与测试读取。 */
  readonly size: { W: number; H: number };
  /** 世界的当前状态、驱动与场景（测试与回放读取）。 */
  inspect(): { driver: FloorDriver; scene: SceneLike; state: FloorState; renderer: FloorRenderer };
  /** 大厅决定板在画面逻辑坐标里的矩形（点击与测试共用）。 */
  boardRect(): { x: number; y: number; w: number; h: number };
}

/** 端到端测试的入口：按需要给出世界、角色、包裹、管道与信号的当前状态（含类型，测试不猜形状）。 */
export interface FloorTestHooks {
  state: () => {
    characters: { id: string; department: string | null; task: string | null; queued: string[]; bubble: string | null; pose: string | null }[];
    packages: { id: string; link: string | null }[];
    pipes: [string, string | null][];
    signals: string[];
    items: { id: string; status: string; department: string | null }[];
    reduced: boolean;
    canvasWidth: number;
  };
  resync: () => void;
}

/** 建立给端到端测试用的读取入口：读的是画面里世界的当前状态。 */
export function floorTestHooks(view: FloorView, onResync: () => void): FloorTestHooks {
  return {
    state: () => {
      const { driver, scene } = view.inspect();
      const world = driver.world;
      const canvas = view.inspect().renderer;
      void canvas;
      return {
        characters: Object.values(world.characters).map((c) => ({
          id: c.id,
          department: c.department,
          task: c.current ? c.current.taskKey : null,
          queued: c.queue.map((t) => t.taskKey),
          bubble: c.bubble ? c.bubble.text : null,
          pose: scene.actors.find((a) => a.id === "ch-" + c.id)?.anim ?? null,
        })),
        packages: Object.values(world.packages).map((pk) => ({ id: pk.id, link: pk.transit ? pk.transit.linkKey : null })),
        pipes: Object.entries(world.links).map(([key, p]) => [key, p.flow ? p.flow.state : null] as [string, string | null]),
        signals: Object.keys(world.signals).filter((name) => world.signals[name].until > scene.realT),
        items: driver.model.items.map((it) => ({ id: it.work_item_id, status: it.status, department: it.department })),
        reduced: scene.reduced,
        canvasWidth: 0,
      };
    },
    resync: () => onResync(),
  };
}

export interface FloorViewOptions {
  host: HTMLElement;
  clock: Clock;
  /** 决定卡的挂载容器（说明栏的输入框加在这里）。 */
  cardHost?: HTMLElement;
  onDecide?: (payload: { decision_id: string; option: string; note: string; base_version: number }) => unknown;
  onGo?: (target: string) => void;
}

/** 建立一个项目楼层画面：画好的画布贴到 PixiJS 的舞台上，整数倍最近邻缩放到容器宽度。 */
export async function createFloorView(opts: FloorViewOptions): Promise<FloorView> {
  const app = new Application();
  await app.init({ background: "#12101c", antialias: false, autoDensity: false, resolution: 1 });
  const canvas = app.canvas;
  canvas.style.imageRendering = "pixelated";
  canvas.style.display = "block";
  opts.host.appendChild(canvas);

  // 离屏画布：世界与画法都画在这里，再作为纹理贴到舞台
  const surface = document.createElement("canvas");
  surface.width = W;
  surface.height = H;
  const ctx = surface.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;
  const texture = Texture.from(surface);
  const sprite = new Sprite(texture);
  app.stage.addChild(sprite);

  const catalog = buildCatalog(ROOM_VISUALS);
  const scene = createScene({
    W,
    H,
    random: () => Math.random(),
    reduced: reducedMotion(),
    // 走动与包裹的移动由 GSAP 的补间推进，共用同一个时钟
    tween: (target, vars) => opts.clock.tween(target, vars),
    reapply: () => opts.clock.reapply(),
  });
  const emptyModel: FloorModel = {
    items: [], open_requests: [], shelves: { adopted: [] }, slots: null, waiting_provider: [],
    machines: null, ops: null, interrupted: false, roles: null, decisions: [],
  };
  const driver = createFloorDriver({ model: emptyModel, scene, state: createFloorState(), catalog, W, H, time: FLOOR_TIME });
  const renderer = new FloorRenderer(driver, scene);

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
    // 画面自己渲染：PixiJS 的共享 ticker 被时钟停掉了（时间全部由共用时钟给出），这里主动画一帧
    app.renderer.render(app.stage);
  }

  applyLayout();
  draw();
  const offTick = opts.clock.onTick((elapsed) => {
    // 缓动与行走由 GSAP 的补间按共用时钟的位置计算，这里只把时钟的经过时间交给场景
    const delta = Math.max(0, elapsed - last);
    last = elapsed;
    scene.stepScene(delta);
    driver.step();
    // 本次推进里新建的补间（走动、包裹移动）立刻落到当前时间上：位置与「推进到第几毫秒」一致
    scene.reapply();
    draw();
  });

  const onResize = (): void => {
    applyLayout();
    draw();
  };
  window.addEventListener("resize", onResize);

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
    focus(id) {
      scene.focusId = id ?? null;
      draw();
    },
    setOverlay(id, data) {
      renderer.overlay = { id: id ?? null, data: (data as Record<string, unknown>) ?? null };
      draw();
    },
    resize() {
      applyLayout();
      draw();
    },
    destroy() {
      offTick();
      window.removeEventListener("resize", onResize);
      if (canvas.parentNode === opts.host) opts.host.removeChild(canvas);
      texture.destroy(true);
      app.destroy(false, { children: true });
    },
    inspect: () => ({ driver, scene, state: driver.state, renderer }),
    boardRect: () => driver.boardRect(),
  };
}

/** 系统设置为减少动画。 */
function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
