// 项目楼层的画面对象：画布挂在宿主元素上，提供 setModel、playEvent、focus、setOverlay、resize、destroy
// （原型 v9 floor.js 的对外接口与设计说明第 5.2 至 5.7 节，工单 #82）。
//
// 世界的推进（floor.ts）与绘制（render.ts）都不依赖画布与 WebGL；这里只把画好的画布挂到页面上，
// 画布按设备分辨率绘制（surface.ts：像素尺寸为逻辑尺寸乘整数倍 k，先设缩放再按逻辑坐标绘制，
// 工单 #365），每帧由共用的时钟驱动。

import type { Clock } from "../clock.ts";
import { createPixelSurface } from "../surface.ts";
import { buildCatalog } from "./../world/floor-decl.ts";
import { createFloorDriver, createFloorState, type FloorDriver, type FloorState } from "./../world/floor.ts";
import { createScene } from "./../world/scene.ts";
import { FloorRenderer, H, W } from "./render.ts";
import { createDecisionCard, type DecisionCard } from "./card.ts";
import { ROOM_VISUALS } from "./render-decl.ts";
import type { DecisionAnswer, DecisionResult } from "./card.ts";
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
  inspect(): { driver: FloorDriver; scene: SceneLike; state: FloorState; renderer: FloorRenderer; card: DecisionCard };
  /** 大厅决定板在画面逻辑坐标里的矩形（点击与测试共用）。 */
  boardRect(): { x: number; y: number; w: number; h: number };
  /** 打开着的决定卡片（测试与宿主读取）。 */
  card(): DecisionCard;
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
  /** 当前画在画布上的覆盖层，供真实系统端到端测试核对查询结果。 */
  overlay: () => { id: string | null; data: Record<string, unknown> | null };
  /** 决定板与决定卡片的状态（工单 #179 的端到端核对）。 */
  decisions: () => {
    board: { x: number; y: number; w: number; h: number };
    faces: { id: string; kind: string; version: number; title: string }[];
    card: { openId: string | null; submitted: string[]; message: string | null; stamp: { id: string; text: string } | null };
  };
  /** 打开指定决定的卡片（端到端测试直接打开，绕过点击坐标的缩放）。 */
  openCard: (id: string) => void;
  /** 点一个选项（端到端测试在真实画布上点章，这里给直接入口）。 */
  answer: (option: string) => Promise<void>;
  resync: () => void;
}

/** 建立给端到端测试用的读取入口：读的是画面里世界的当前状态。 */
export function floorTestHooks(view: FloorView, onResync: () => void): FloorTestHooks {
  return {
    overlay: () => view.inspect().renderer.overlay,
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
    decisions: () => {
      const { driver, card } = view.inspect();
      const info = card.inspect();
      return {
        board: view.boardRect(),
        faces: driver.model.decisions.map((d) => ({ id: d.id, kind: d.kind, version: d.version, title: d.title })),
        card: { openId: info.openId, submitted: info.submitted, message: info.message, stamp: info.stamp ? { id: info.stamp.id, text: info.stamp.text } : null },
      };
    },
    openCard: (id) => view.card().open(id),
    answer: (option) => view.card().answer(option),
    resync: () => onResync(),
  };
}

export interface FloorViewOptions {
  host: HTMLElement;
  clock: Clock;
  /** 决定卡的挂载容器（说明栏的输入框加在这里）。 */
  cardHost?: HTMLElement;
  /** 点选项时的回答：带上决定的版本与说明，返回命令的结果（被拒绝时给出原因）。 */
  onDecide?: (payload: DecisionAnswer) => Promise<DecisionResult> | DecisionResult;
  onGo?: (target: string) => void;
}

/** 建立一个项目楼层画面：画布按设备分辨率绘制，整数倍铺满容器宽度。 */
export async function createFloorView(opts: FloorViewOptions): Promise<FloorView> {
  // 画布按设备分辨率绘制：像素尺寸为 W×H 的整数倍，图形与文字都按设备分辨率光栅化
  const surface = createPixelSurface({ host: opts.host, W, H });
  const canvas = surface.canvas;

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
  // 世界里的决定卡片：点大厅的板子打开，回答调用 onDecide（工单 #179）
  const card = createDecisionCard(canvas, {
    cardHost: opts.cardHost ?? null,
    onDecide: (payload) => (opts.onDecide ? opts.onDecide(payload) : { accepted: false, message: "画面没有接上回答命令" }),
    onGo: (target) => opts.onGo?.(target),
    now: () => scene.realT,
    after: (ms, fn) => scene.after(ms, fn),
    W,
    H,
  });
  renderer.card = card;
  scene.cardStamped = (id, text) => card.stamp(id, text);

  let last = 0;

  function draw(): void {
    renderer.draw(surface.frame());
  }

  /** 画布上的坐标换成画面逻辑坐标（画布按整数倍缩放显示）。 */
  function worldXY(ev: MouseEvent): [number, number] {
    const rect = canvas.getBoundingClientRect();
    return [((ev.clientX - rect.left) / rect.width) * W, ((ev.clientY - rect.top) / rect.height) * H];
  }

  /** 决定板的命中范围：板子与它上方的「待你决定」牌子；没有等待回答的决定请求时不命中。 */
  function overBoard(x: number, y: number): boolean {
    if (driver.model.decisions.length === 0) return false;
    const b = driver.boardRect();
    return x >= b.x - 2 && x <= b.x + b.w + 2 && y >= b.y - 12 && y <= b.y + b.h + 10;
  }

  const onClick = (ev: MouseEvent): void => {
    const [x, y] = worldXY(ev);
    if (card.click(x, y)) return;
    if (overBoard(x, y)) card.open();
  };
  const onMove = (ev: MouseEvent): void => {
    const [x, y] = worldXY(ev);
    canvas.style.cursor = card.cursor(x, y) ?? (!card.isOpen() && overBoard(x, y) ? "pointer" : "default");
  };
  canvas.addEventListener("click", onClick);
  canvas.addEventListener("mousemove", onMove);

  surface.resize();
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
    surface.resize();
    draw();
  };
  window.addEventListener("resize", onResize);

  return {
    size: { W, H },
    setModel(model) {
      driver.setModel(model);
      card.setDecisions(model.decisions);
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
      surface.resize();
      draw();
    },
    destroy() {
      offTick();
      window.removeEventListener("resize", onResize);
      canvas.removeEventListener("click", onClick);
      canvas.removeEventListener("mousemove", onMove);
      card.destroy();
      if (canvas.parentNode === opts.host) opts.host.removeChild(canvas);
    },
    inspect: () => ({ driver, scene, state: driver.state, renderer, card }),
    boardRect: () => driver.boardRect(),
    card: () => card,
  };
}

/** 系统设置为减少动画。 */
function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
