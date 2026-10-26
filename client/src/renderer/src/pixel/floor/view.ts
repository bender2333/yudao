// 项目楼层的画面对象：画布挂在宿主元素上，提供 setState、jump、play、setDecisions、stream、focus、
// setOverlay、resize、destroy（原型 v13 js/pixel/floor.js 的 createFloorScene 与画面与播放设计说明第 4、5 节，
// 工单 #82、#953）。
//
// 画面的输入只有画面合同（pixel/contract.ts）：状态带位置、动作带位置与 kind，实时内容（决定卡片、流式文字）
// 到了就显示。打开画面、重新同步、标签页切回与回放拖动都用 jump：清空时间线，直接显示最新状态，不补播。
//
// 世界的推进（floor.ts）与绘制（render.ts）都不依赖画布与 WebGL；这里只把画好的画布挂到页面上，
// 画布按设备分辨率绘制（surface.ts），每帧由共用的时钟驱动。

import type { Clock } from "../clock.ts";
import { createPixelSurface } from "../surface.ts";
import { buildCatalog } from "./../world/floor-decl.ts";
import { ACTIVE, IN_ROOM, busyItems, createFloorDriver, createFloorState, itemColor, type FloorDriver, type FloorState } from "./../world/floor.ts";
import { createScene } from "./../world/scene.ts";
import { FloorRenderer, H, W } from "./render.ts";
import { createDecisionCard, type DecisionCard } from "./card.ts";
import { ROOM_VISUALS } from "./render-decl.ts";
import type { DecisionAnswer, DecisionResult } from "./card.ts";
import type { DecisionFace, FloorModel, SceneLike, TimeText } from "../world/types.ts";
import type { PixelAction } from "../contract.ts";

/** 概览页与测试共用的时间写法（原型 Y13.time）。 */
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

/** 没有数据时的空状态：带位置 0，事项为空。 */
export function emptyFloorModel(): FloorModel {
  return {
    position: 0,
    items: [], open_requests: [], shelves: { adopted: [] }, slots: null, waiting_provider: [],
    machines: null, ops: null, interrupted: false, roles: null, decisions: [],
  };
}

/** 项目楼层画面对象。 */
export interface FloorView {
  /** 一份状态：等它之前的动作演完再上画面（由播放时间线决定）。 */
  setState(state: FloorModel): void;
  /** 跳到最新：清空时间线，正在演的立刻结束，直接显示给出的状态，不补播。 */
  jump(state: FloorModel): void;
  /** 一个动作：进播放时间线，按声明演出。 */
  play(action: PixelAction): void;
  /** 决定卡片（实时内容，不进时间线）。 */
  setDecisions(list: DecisionFace[]): void;
  /** 流式文字（实时内容，不进时间线）。 */
  stream(who: { room: string | null; role?: string | null }, text: string): void;
  focus(id: string | null): void;
  setOverlay(id: string | null, data: unknown): void;
  resize(): void;
  destroy(): void;
  /**
   * 关掉或打开表演层（待机活动与动作）的测试入口（设计说明第 8.1 节的 H2）。
   * 关掉以后动作与特效不演，画面只画状态给出的样子；承载事实的通道不受影响。
   */
  performance(on: boolean): void;
  /** 画面逻辑尺寸，供宿主与测试读取。 */
  readonly size: { W: number; H: number };
  /** 世界的当前状态、驱动与场景（测试与回放读取），以及承载事实的视觉通道。 */
  inspect(): {
    driver: FloorDriver; scene: SceneLike; state: FloorState; renderer: FloorRenderer; card: DecisionCard;
    /** 承载事实的视觉通道（设计说明第 8.1 节的楼层那一行）。 */
    channels: () => FloorChannels;
  };
  /** 大厅决定板在画面逻辑坐标里的矩形（点击与测试共用）。 */
  boardRect(): { x: number; y: number; w: number; h: number };
  /** 打开着的决定卡片（测试与宿主读取）。 */
  card(): DecisionCard;
}

/**
 * 楼层承载事实的视觉通道（画面与播放设计说明第 8.1 节的楼层那一行）：事项在哪个房间或在大厅、事项的颜色，
 * 房间亮灯与屏幕滚动，门口的小旗与牌子文字，大厅板上的决定单，成果库里的成果，传信管里等待回答的询问数，
 * 等待模型服务的文字，各部门的角色与角色的状态。
 *
 * 只读状态给出的东西：还在路上的决定单、包裹与飞行物、说话气泡、走位与待机活动属于表演层，不在这里。
 */
export interface FloorChannels {
  /** 上画面的状态来自的查询快照的位置。 */
  position: number;
  /** 事项在哪个房间或在大厅、事项的颜色。 */
  items: { id: string; department: string | null; status: string; where: "room" | "hall" | "other"; color: string }[];
  /** 部门 → 房间的亮灯、屏幕与门口的小旗；label 是门口的牌子文字。 */
  rooms: Record<string, {
    label: string;
    lit: boolean;
    screen: "off" | "code" | "idle";
    flags: { id: string; color: string; status: string }[];
  }>;
  /** 大厅板上的决定单。 */
  board: { id: string; kind: string; title: string; color: string | null }[];
  /** 成果库里的成果：已采纳的全部与货架上摆得下的那几个。 */
  shelf: { adopted: string[]; shown: string[] };
  /** 传信管里等待回答的询问数（接收的部门、封数）。 */
  tubes: { department: string; count: number }[];
  /** 等待模型服务的文字（部门与牌子上的字）。 */
  waiting: { department: string; text: string }[];
  /** 部门 → 角色与角色的状态。 */
  roles: Record<string, { id: string; kind: string; status: string | null }[]>;
}

/** 读一份状态承载事实的视觉通道：与渲染层取同一份状态数据（渲染层在动作期间另加的临时效果不算）。 */
function floorChannels(driver: FloorDriver): FloorChannels {
  const model = driver.model;
  const world = driver.world;
  const ctx = driver.declCtx();
  const itemsOf = (department: string): FloorChannels["items"] => model.items
    .filter((it) => it.department === department && IN_ROOM.includes(it.status))
    .map((it) => ({ id: it.work_item_id, department: it.department, status: it.status, where: "room", color: itemColor(it) }));
  const rooms: FloorChannels["rooms"] = {};
  let shelfRoom: (typeof world.rooms)[string] | null = null;
  for (const id of world.roomOrder) {
    const room = world.rooms[id];
    if (room.roomKind === "shelf") {
      shelfRoom = room;
      continue;
    }
    if (room.roomKind !== "dept") continue;
    // 与渲染层同一口径：亮灯按这个房间忙碌的事项算；门口的小旗只看停在这里的事项
    const here = busyItems(model, id);
    rooms[id] = {
      label: room.label,
      lit: here.some((it) => ACTIVE.includes(it.status) || it.status === "done") || Boolean(room.def.lit?.(ctx)),
      screen: model.interrupted ? "off" : here.some((it) => ACTIVE.includes(it.status)) ? "code" : "idle",
      flags: itemsOf(id).map((it) => ({ id: it.id, color: it.color, status: it.status })),
    };
  }
  const adopted = model.shelves.adopted.slice();
  const per = shelfRoom ? Math.max(1, Math.floor((shelfRoom.w - 26) / 18)) : adopted.length;
  const itemById = (id: string | null): (typeof model.items)[number] | null =>
    (id ? model.items.find((it) => it.id === id || it.work_item_id === id) ?? null : null);
  const roles: FloorChannels["roles"] = {};
  for (const id of world.roomOrder) {
    if (world.rooms[id].roomKind !== "dept") continue;
    roles[id] = Object.values(world.characters)
      .filter((ch) => ch.department === id)
      .map((ch) => ({ id: ch.id, kind: ch.roleKind, status: ch.roleInfo ? ch.roleInfo.status : null }))
      .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  }
  return {
    position: model.position,
    items: model.items.map((it) => ({
      id: it.work_item_id,
      department: it.department,
      status: it.status,
      where: IN_ROOM.includes(it.status) ? "room" : it.status === "queued" || it.status === "waiting_slot" ? "hall" : "other",
      color: itemColor(it),
    })),
    rooms,
    board: (model.decisions ?? []).map((d) => {
      const item = itemById(d.work_item_id ?? null);
      return { id: d.id, kind: d.kind, title: d.title, color: item ? itemColor(item) : null };
    }),
    shelf: { adopted, shown: adopted.slice(-per) },
    tubes: world.roomOrder.filter((id) => world.rooms[id].roomKind === "dept")
      .map((id) => ({ department: id, count: model.open_requests.filter((q) => q.to === id).length })),
    waiting: model.waiting_provider.map((w) => ({
      department: w.department,
      text: "等待模型服务" + (w.retry_text ? " · " + w.retry_text : ""),
    })),
    roles,
  };
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
  /** 时间线此刻的读数：画面上状态的位置、还排着几份状态、落后多少（工单 #953 的「不补播」核对）。 */
  timeline: () => { shown: number | null; pending: number; lag: number; queued: number; playing: string[] };
  /** 当前画在画布上的覆盖层，供真实系统端到端测试核对查询结果。 */
  overlay: () => { id: string | null; data: Record<string, unknown> | null };
  overlayLabels: () => { x: number; y: number; w: number; h: number; key: string }[];
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
    overlayLabels: () => view.inspect().renderer.overlayLabels.map((r) => ({ ...r })),
    state: () => {
      const { driver, scene } = view.inspect();
      const world = driver.world;
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
        items: driver.model.items.map((it) => ({ id: it.id, status: it.status, department: it.department })),
        reduced: scene.reduced,
        canvasWidth: 0,
      };
    },
    timeline: () => {
      const info = view.inspect().driver.inspectTimeline();
      return { shown: info.shown, pending: info.pending, lag: info.lag, queued: info.queued, playing: info.playing.map((p) => p.kind) };
    },
    decisions: () => {
      const { driver, card } = view.inspect();
      const info = card.inspect();
      return {
        board: view.boardRect(),
        faces: (driver.model.decisions ?? []).map((d) => ({ id: d.id, kind: d.kind, version: d.version, title: d.title })),
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
  cardHost?: HTMLElement | null;
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
  const driver = createFloorDriver({ model: emptyFloorModel(), scene, state: createFloorState(), catalog, W, H, time: FLOOR_TIME });
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
    if ((driver.model.decisions ?? []).length === 0) return false;
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
    setDecisions(list) {
      driver.setDecisions(list);
      card.setDecisions(list);
      draw();
    },
    stream(who, text) {
      driver.stream(who, text);
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
    performance(on) {
      // 待机活动与动作一起关掉：动作停在原处，不再开始新的步子（承载事实的通道只由状态决定）
      scene.performance = on;
      scene.autonomy = on;
      if (!on) for (const actor of scene.actors.slice()) scene.cancel(actor);
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
    inspect: () => ({ driver, scene, state: driver.state, renderer, card, channels: () => floorChannels(driver) }),
    boardRect: () => driver.boardRect(),
    card: () => card,
  };
}

/** 系统设置为减少动画。 */
function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
