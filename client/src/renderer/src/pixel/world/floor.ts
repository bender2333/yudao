// 项目楼层的驱动：按状态配置世界（声明、角色、持续状态），按动作演出（原型 v13 js/pixel/floor.js 与
// 画面与播放设计说明第 4 至 6 节，工单 #82、#953）。
//
// 状态与动作都来自画面合同（pixel/contract.ts），由翻译层翻好（translate/floor.ts）：
//   - 状态进播放时间线，等它之前的动作演完再上画面（apply）；
//   - 动作进时间线，按它的 kind 在楼层的声明表里找到级别、时长与做它的角色，然后演（perform）；
//   - 决定卡片与流式文字是实时内容，到了就显示，不进时间线。
// 打开画面、重新同步、标签页切回与回放拖动都用 jump：清空时间线，直接显示最新状态，不补播。
//
// 世界与系统都在这里维护；画面渲染只读这里给出的世界与状态。驱动不依赖 PixiJS：
// 飞行物、粒子与说话停留都记在驱动自己的状态里，渲染层照读。

import {
  action as checkAction, floorState as checkFloorState, type BusyState, type ItemState, type PixelAction, type PixelState,
} from "../contract.ts";
import { create as createTimeline, type Timeline, type TimelineEntry, type TimelineInspect } from "../timeline.ts";
import { asText, dispatch, dropAction, enqueue, nextPackageId, progressOf, sendPackage, spawnPackage, stepCharacters, stepPackages, stepPipes } from "./characters.ts";
import { declareLinks, declareRooms, linkBetween, route, roomOf } from "./declare.ts";
import { actorOf, charFor, primaryOf, syncCharacters, mountMachines } from "./scene.ts";
import { sayMs } from "./say.ts";
import { signal, signalOn } from "./signals.ts";
import type {
  Catalog, Character, DecisionFace, DeclContext, FloorModel, LoopItem, PackageVisual, SceneLike, Task, TaskDef, TaskFx, World,
} from "./types.ts";
import { createWorld } from "./declare.ts";

/** 会待在房间内的事项状态（画面合同的事项状态；进行中的事项在房间里，工单 #900）。 */
export const IN_ROOM: readonly ItemState[] = [
  "working", "asking", "waiting_model", "paused", "failed", "done", "cancelled", "interrupted", "waiting_resume", "waiting_user",
  "upgrade_stopped",
];
/** 房间亮灯与管道流动对应的活跃事项状态。 */
export const ACTIVE: readonly ItemState[] = ["working", "asking"];

/** 部门在事项上正做着（工作中、回答询问）：停在别的房间的事项也让这个部门忙碌。 */
const BUSY_STATES: readonly BusyState[] = ["working", "answering"];

/**
 * 在这个房间忙碌的事项（原型 v13 floor.js 的 alsoIn 与 busyIn）：
 * 事项停在这个房间，或者停在别的房间、这个部门同时在为它做事（一轮工作中、回答询问，例如质检的预测性探索）。
 * 包裹与门口的小旗不按这个算，它们只在事项所在的房间。
 */
export function busyItems(model: FloorModel, department: string): LoopItem[] {
  const here = model.items.filter((it) => it.department === department && IN_ROOM.includes(it.status));
  const also = model.items.filter((it) => it.department !== department && ACTIVE.includes(it.status)
    && BUSY_STATES.includes(it.departments?.[department] as BusyState));
  return here.concat(also);
}

const PIPE_Y = 138;
const TOP = 50;
const ROOM_B = 214;
const CORR_Y = 238;

const ART_BMP: Record<string, string> = { prd: "scroll", box: "box_sealed", defect: "box_rework", release: "box_release", letter: "letter" };

const ITEM_COLORS = ["#d9534f", "#4a90d9", "#5cb85c", "#f0ad4e", "#9b59b6", "#e67e22"];

const PAL_MAP: Record<string, string> = {
  red2: "#d9534f", red3: "#b52b27", green2: "#5cb85c", green3: "#3d8b40", orange1: "#e67e22",
  orange2: "#f0ad4e", yellow1: "#ffd66b", yellow2: "#f7e07a", white: "#ffffff", blue1: "#6ba8d9", blue2: "#4a90d9",
  grey3: "#8a90a0",
};

/** 大厅的决定板矩形。 */
export interface BoardRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 一块正在飞的纸（决定单、信件）。 */
export interface Flyer {
  bmp: string;
  t0: number;
  ms: number;
  arc: number;
  from: [number, number];
  to: [number, number];
  onDone?: () => void;
}

/** 决定单还在路上时的隐藏截止时刻：决定 id → 时刻。 */
export type HiddenMap = Record<string, number>;

/** 楼层驱动自己的画面状态：时钟、闪光、说话停留、飞行物与箭头。 */
export interface FloorState {
  clock: number;
  flash: Record<string, { color: string; until: number }>;
  pipeFlash: Record<string, number>;
  arrows: { pts: [number, number][]; color: string; bmp: string; itemId: string | null; dash: boolean; until: number }[];
  hidden: HiddenMap;
  /** 排队中的包裹滑到自己的位置。 */
  queueX: Record<string, number>;
  flyers: Flyer[];
  /** 小人头顶这句话停留的截止时刻。 */
  said: Record<string, { text: string; until: number }>;
  /** 远程动作的光点：走廊里门与人之间。 */
  remoteDots: { from: [number, number]; to: [number, number]; t0: number; ms: number }[];
}

export function createFloorState(): FloorState {
  return { clock: 15.5 * 3600000, flash: {}, pipeFlash: {}, arrows: [], hidden: {}, queueX: {}, flyers: [], said: {}, remoteDots: [] };
}

export interface FloorDriverOptions {
  model: FloorModel;
  scene: SceneLike;
  state: FloorState;
  catalog: Catalog;
  W: number;
  H: number;
  /** 时间与数字在画面上的写法（原型 Y10.time）。 */
  time: { clock: (iso: string | null) => string; duration: (sec: number) => string };
}

/** 时间线上的一个动作在这里演：run = { id, action, alive(), finish() }。 */
interface Run {
  id: number;
  action: PixelAction;
  lanes: string[];
  dead: boolean;
  alive: () => boolean;
  finish: () => void;
}

export interface FloorDriver {
  world: World;
  model: FloorModel;
  state: FloorState;
  /** 一份状态上画面（由播放时间线决定什么时候）。 */
  setState: (state: FloorModel) => void;
  /** 跳到最新：清空时间线，正在演的立刻结束，直接显示给出的状态。 */
  jump: (state: FloorModel) => void;
  /** 一个动作进播放时间线（按位置排队，按声明演出）。 */
  play: (action: PixelAction) => void;
  /** 流式文字：实时内容，到了就显示，不进时间线。 */
  stream: (who: { room: string | null; role?: string | null }, text: string) => void;
  /** 决定卡片（实时内容）：大厅的板上贴着的几张，点开可以回答。 */
  setDecisions: (list: DecisionFace[]) => void;
  /** 每帧推进：时间线、包裹、管道、角色。 */
  step: () => void;
  /** 决定板的矩形（画面与点击共用）。 */
  boardRect: () => BoardRect;
  /** 决定单还在路上（板上暂时看不到它）。 */
  decisionHidden: (id: string, now: number) => boolean;
  /** 每个角色此刻头顶说的话（画面按 until 读取）。 */
  saidOf: (id: string, now: number) => { text: string; until: number } | null;
  /** 房间声明的 props、lit、tint 读取画面数据的窗口。 */
  declCtx: () => DeclContext;
  /** 时间线此刻的读数（测试与调节面板）。 */
  inspectTimeline: () => TimelineInspect;
}

/** 建立一个楼层驱动：世界、角色、播放时间线与画面状态都在这里维护。 */
export function createFloorDriver(opts: FloorDriverOptions): FloorDriver {
  const scene = opts.scene;
  const state = opts.state;
  const catalog = opts.catalog;
  let model = opts.model;
  let decisions: DecisionFace[] = model.decisions ?? [];
  let flags = flagsOf(model, catalog);
  let world = declareWorld(model, catalog);

  function flagsOf(m: FloorModel, cat: Catalog): Record<string, boolean> {
    const out: Record<string, boolean> = {};
    for (const key of cat.flags) out[key] = Boolean((m as unknown as Record<string, unknown>)[key]);
    return out;
  }

  function declareWorld(m: FloorModel, cat: Catalog): World {
    const w = createWorld(cat);
    declareRooms(w, cat.roomDefs, flagsOf(m, cat));
    declareLinks(w, cat.linkDefs);
    return w;
  }

  function rooms(): { hall: NonNullable<ReturnType<typeof roomOf>>; lib: NonNullable<ReturnType<typeof roomOf>>; depts: NonNullable<ReturnType<typeof roomOf>>[]; out: World["links"][string]; door: NonNullable<World["machineDoor"]> } {
    const list = world.roomOrder.map((id) => world.rooms[id]);
    const hall = list.find((r) => r.roomKind === "hall");
    if (!hall) throw new Error("楼层没有声明大厅");
    const out = Object.values(world.links).find((l) => l.from === hall.id && l.linkKind === "handoff");
    if (!out) throw new Error("大厅没有交接管道");
    if (!world.machineDoor) throw new Error("楼层没有声明通往机房的门");
    const lib = list.find((r) => r.roomKind === "shelf");
    if (!lib) throw new Error("楼层没有声明成果库");
    return { hall, lib, depts: list.filter((r) => r.roomKind === "dept"), out, door: world.machineDoor };
  }

  const waitingDept = (department: string): { department: string; retry_text: string | null } | null =>
    model.waiting_provider.find((w) => w.department === department) ?? null;
  const primaryItem = (department: string): LoopItem | null => {
    // 停在别的房间、这个部门同时在为它做事的事项也算：这个房间的小人坐在桌前工作（原型 v13 floor.js 的 primaryItem）
    const here = busyItems(model, department);
    return here.find((it) => ACTIVE.includes(it.status)) ?? here.find((it) => it.status === "waiting_model") ?? here[0] ?? null;
  };

  const ctx = {
    model,
    order: world.roomOrder,
    waitingDept,
    time: opts.time,
    sig: (name: string) => signalOn(world, scene, name),
    get reduced(): boolean {
      return scene.reduced;
    },
  };

  function specsFor(): { id: string; department: string; roleKind: string; name: string; role: Character["roleInfo"] }[] {
    const out: { id: string; department: string; roleKind: string; name: string; role: Character["roleInfo"] }[] = [];
    for (const room of rooms().depts) {
      const roles = model.roles?.[room.id];
      if (roles && roles.length) {
        for (const ro of roles) out.push({ id: ro.id, department: room.id, roleKind: ro.kind, name: ro.name, role: ro });
      } else {
        out.push({ id: room.id, department: room.id, roleKind: room.def.agentKind ?? "agent", name: room.label, role: null });
      }
    }
    return out;
  }

  function syncWorkers(): void {
    ctx.model = model;
    ctx.order = world.roomOrder;
    const specs = specsFor();
    syncCharacters(world, scene, specs, (s) => `${s.department}.${s.roleKind}`);
    mountMachines(scene, Object.values(world.characters), Object.values(world.links));
    for (const spec of specs) {
      const ch = world.characters[spec.id];
      const room = world.rooms[spec.department];
      ch.item = primaryItem(spec.department);
      ch.roleInfo = spec.role;
      const roomRest = room.def.rest ?? catalog.deptRest;
      ch.rest = catalog.roleRest(ctx, spec.department, ch.item, spec.role, primaryOf(world, spec.department) === ch, roomRest);
    }
  }

  // ---------------------------------------------------------------------------
  // 动作：播放时间线决定什么时候开始；一个动作的演出在几个角色、管道与飞行物之间接力，
  // 最后一步做完时告诉时间线。

  /** 小人头顶说的话：动作带着的话由翻译层写好（say 是做事的一方，sayTo 是收东西的一方）。 */
  function sayOf(a: PixelAction, side: "to" | "from" | null): Partial<Task> {
    const text = side === "to" ? a.sayTo : a.say;
    return typeof text === "string" && text ? { label: text } : {};
  }

  function said(ch: Character, text: string): void {
    state.said[ch.id] = { text, until: scene.realT + sayMs(text) };
  }

  /** 小人走到管道口放下或取出包裹：做完以后执行 after；没有角色时直接执行。减少动画时小人不走动，只在原处说话。 */
  function trip(run: Run, department: string, key: string, after?: (() => void) | null, extra?: Partial<Task> | null): void {
    const next = (): void => {
      if (run.alive()) after?.();
    };
    if (scene.reduced) {
      const def = catalog.tasks[key];
      const ch = def ? charFor(world, department, null, def.actor ?? def.by ?? null) : null;
      if (ch && extra?.label) said(ch, extra.label);
      next();
      return;
    }
    const task = enqueue(world, department, key, { onDone: next, actionId: run.id, ...(extra ?? {}) });
    if (!task) next();
  }

  /** 包裹沿管道走；option.run 是这个包裹属于的演出，截断以后不再执行 onDone。减少动画时改成管道上的箭头。 */
  function send(pts: [number, number][] | null, bmp: string, opt: Partial<PackageVisual> & { run?: Run }): void {
    const run = opt.run;
    const next = (): void => {
      if ((!run || run.alive()) && opt.onDone) opt.onDone();
    };
    if (!pts) {
      next();
      return;
    }
    if (scene.reduced) {
      state.arrows.push({ pts, color: opt.color ?? "#ffffff", bmp, itemId: opt.itemId ?? null, dash: Boolean(opt.small), until: scene.realT + 3600 });
      next();
      return;
    }
    const id = nextPackageId();
    const pk = spawnPackage(world, id, opt.itemId ?? null, null, opt.artifact ?? null, null);
    pk.bmp = bmp;
    pk.color = opt.color ?? null;
    pk.small = opt.small;
    pk.actionId = run ? run.id : undefined;
    sendPackage(world, scene, id, opt.linkKey ?? null, pts, opt.ms, () => {
      delete world.packages[id];
      next();
    });
  }

  const flash = (roomId: string, color: string, ms: number): void => {
    state.flash[roomId] = { color, until: scene.realT + ms };
  };

  /** 任务声明里的效果（floor-decl.js 的 fx）：信号、房间闪光、包裹沿管道走。 */
  function applyFx(fx: TaskFx, a: PixelAction, ch: Character, run: Run, after?: (() => void) | null): void {
    if (fx.signal) signal(world, scene, fx.signal, fx.ms ?? 0);
    if (fx.flash) flash(fx.flash.room === "self" ? (ch.department ?? "") : fx.flash.room, PAL_MAP[fx.flash.color] ?? "#ffffff", fx.flash.ms ?? 900);
    if (fx.send) {
      const link = world.links[fx.send.link];
      if (!link) {
        after?.();
        return;
      }
      send(fx.send.reverse ? link.pts.slice().reverse() : link.pts, fx.send.bmp, {
        color: fx.send.color ? (PAL_MAP[fx.send.color] ?? "#ffffff") : null,
        linkKey: link.id,
        run,
        onDone: () => {
          for (const next of fx.send!.then ?? []) applyFx(next, a, ch, run);
          after?.();
        },
      });
      return;
    }
    after?.();
  }

  /** 交给 dispatch 的 make：任务头顶说的内容、声明里的效果、属于哪个动作；动作的最后一步做完时告诉时间线。 */
  function extrasOf(run: Run) {
    return (def: TaskDef, a: PixelAction, ch: Character, side?: "to" | "from"): Partial<Task> => {
      const out: Partial<Task> = { ...sayOf(a, side ?? null), actionId: run.id };
      const last = side === "to" || !def.then;
      const sends = Boolean(def.fx && def.fx.some((f) => f.when === "done" && f.send));
      if (def.fx) {
        out.start = () => {
          for (const fx of def.fx!.filter((f) => f.when === "start")) applyFx(fx, a, ch, run);
        };
      }
      out.done = () => {
        const list = def.fx ? def.fx.filter((f) => f.when === "done") : [];
        // 做完以后有包裹要走的，等包裹走完再算这个动作演完
        for (const fx of list) applyFx(fx, a, ch, run, fx.send && last ? run.finish : null);
        if (last && !sends) run.finish();
      };
      return out;
    };
  }

  /** 一个角色的任务：找不到做它的角色时这个动作没有可演的。 */
  function task(run: Run): void {
    if (!dispatch(world, run.action, extrasOf(run))) run.finish();
  }

  /** 时间线上的一个动作在这里演（按动作的 kind，不再按事件种类分支）。 */
  function perform(run: Run): void {
    const a = run.action;
    const it = itemById(asText(a.item));
    const color = it ? ITEM_COLORS[(Number(it.color_index) || 0) % ITEM_COLORS.length] : null;
    const lay = rooms();
    const order = world.roomOrder;
    // 整层静止（中断）时不演动作；自动继续本身让画面重新动起来
    if (scene.frozen && a.kind !== "resume") {
      run.finish();
      return;
    }
    switch (a.kind) {
      case "mail":
        if (!scene.reduced) {
          scene.fly({ bmp: "letter", from: [-6, PIPE_Y - 20], to: [lay.hall.x + 16, PIPE_Y + 6], ms: 900, arc: 20, onDone: () => { signal(world, scene, "mail", 1500); run.finish(); } });
        } else {
          signal(world, scene, "mail", 1500);
          run.finish();
        }
        return;
      case "room_light":
        if (a.room) flash(String(a.room), PAL_MAP.yellow1, 700);
        run.finish();
        return;
      case "handoff": {
        const to = asText(a.to) ?? "";
        const from = asText(a.from) ?? "";
        // 两个房间之间没有直接的管道时，包裹沿声明的管道一段一段走过去
        const hops = route(world, from, to);
        if (!hops.length) {
          run.finish();
          return;
        }
        const ids = lay.depts.map((r) => r.id);
        const rework = a.artifact === "defect" || hops[0].link.linkKind === "return" || (ids.includes(from) && ids.includes(to) && order.indexOf(from) > order.indexOf(to));
        if (rework) hops.forEach((h) => { state.pipeFlash[h.key] = scene.realT + 2600; });
        const bmp = ART_BMP[asText(a.artifact) ?? ""] ?? "box_sealed";
        // 交出方走到管道口放下包裹，包裹沿管道移动，接收方走到管道口取出：两端各是一步
        const arrive = (): void => {
          flash(to, "#ffffff", 500);
          trip(run, to, rework ? "package_return_in" : "package_handoff_in", run.finish, sayOf(a, "to"));
        };
        const leg = (i: number): void => send(hops[i].pts, bmp, {
          itemId: asText(a.item), color, linkKey: hops[i].key, run,
          onDone: () => (i + 1 < hops.length ? leg(i + 1) : arrive()),
        });
        trip(run, from, rework ? "package_return_out" : "package_handoff_out", () => leg(0), sayOf(a, "from"));
        return;
      }
      case "stamp_release":
      case "stamp_defect":
        if (a.room) flash(String(a.room), a.kind === "stamp_release" ? PAL_MAP.green2 : PAL_MAP.red2, 1200);
        task(run);
        return;
      // 传信：发信的经理走到管口塞进信，信沿传信管走，收信的经理走到信来的那一侧管口取信；回答的信是绿色
      case "letter": {
        const from = asText(a.from) ?? "";
        const to = asText(a.to) ?? "";
        const pts = tubeFor(world, from, to);
        const forward = order.indexOf(to) > order.indexOf(from);
        trip(run, from, forward ? "letter_out" : "letter_in", () => send(pts, "letter", {
          small: true, itemId: asText(a.item), color: a.answer ? PAL_MAP.green2 : PAL_MAP.blue2, linkKey: tubeKeyOf(world, from, to) ?? undefined, run,
          onDone: () => trip(run, to, forward ? "letter_arrive_in" : "letter_arrive_out", run.finish, sayOf(a, "to")),
        }), sayOf(a, "from"));
        return;
      }
      case "adopt":
        signal(world, scene, "shelf", 1800);
        scene.emit("spark", lay.lib.x + lay.lib.w / 2, 110, 16);
        run.finish();
        return;
      case "parcel_in":
        signal(world, scene, "mail", 1500);
        if (!scene.reduced) {
          scene.fly({ bmp: a.repair ? "box_rework" : "box", from: [lay.hall.x + 16, PIPE_Y + 10], to: [lay.hall.x + 50, PIPE_Y - 4], ms: 700, arc: 14, onDone: run.finish });
        } else {
          run.finish();
        }
        return;
      case "parcel_enter":
        flash(lay.hall.id, PAL_MAP.green2, 900);
        send(lay.out.pts, "box", { itemId: asText(a.item), color, linkKey: lay.out.id, run, onDone: () => trip(run, lay.out.to, "package_handoff_in", run.finish) });
        return;
      case "queue_moved":
        flash(lay.hall.id, PAL_MAP.blue1, 900);
        run.finish();
        return;
      case "resume": {
        // 自动继续：画面重新动起来，每个角色伸一个懒腰，部门房间亮一下；都伸完了才算演完
        scene.frozen = false;
        const ids = Object.keys(world.characters);
        let left = ids.length;
        const one = (): void => {
          left -= 1;
          if (left <= 0) run.finish();
        };
        ids.forEach((id) => {
          if (!enqueue(world, id, "stretch", { actionId: run.id, onDone: one })) one();
        });
        if (!ids.length) run.finish();
        lay.depts.forEach((r) => flash(r.id, PAL_MAP.yellow1, 700));
        return;
      }
      case "unsure":
        if (a.room) flash(String(a.room), PAL_MAP.yellow2, 1400);
        run.finish();
        return;
      case "remote": {
        const r = a.room ? roomOf(world, String(a.room)) : null;
        if (r && !scene.reduced) {
          signal(world, scene, "door", 1800);
          const from: [number, number] = a.out ? [r.door, ROOM_B + 6] : [lay.door.x, CORR_Y];
          const to: [number, number] = a.out ? [lay.door.x, CORR_Y] : [r.door, ROOM_B + 6];
          state.remoteDots.push({ from, to, t0: scene.realT, ms: 1400 });
        }
        run.finish();
        return;
      }
      case "decision_out": {
        // 提出决定的部门的小人走到门口送出决定单，决定单飞到大厅的板上（板上的决定单是实时内容，已经贴着）
        const roomId = asText(a.room);
        const room = roomId && world.rooms[roomId] && world.rooms[roomId].roomKind === "dept" ? world.rooms[roomId] : null;
        const b = boardRectOf(lay);
        const post = (): void => {
          scene.fly({
            bmp: "decision", from: room ? [room.door, ROOM_B + 4] : [b.x + b.w / 2, TOP - 6], to: [b.x + b.w / 2, b.y + b.h / 2], ms: 1000, arc: 26,
            onDone: () => { signal(world, scene, "board", 1600); run.finish(); },
          });
        };
        if (room && !scene.reduced) trip(run, roomId!, "decision_give", post, sayOf(a, null));
        else if (!scene.reduced) post();
        else run.finish();
        return;
      }
      case "decision_back": {
        // 回答过的决定单从板上飞回提出决定的部门的门口，小人在门口收下
        const roomId = asText(a.room);
        const room = roomId && world.rooms[roomId] && world.rooms[roomId].roomKind === "dept" ? world.rooms[roomId] : null;
        const b = boardRectOf(lay);
        const decisionId = asText(a.decision);
        if (decisionId && scene.cardStamped) scene.cardStamped(decisionId, "已回答");
        if (!room || scene.reduced) {
          run.finish();
          return;
        }
        scene.fly({
          bmp: "decision", from: [b.x + b.w / 2, b.y + b.h / 2], to: [room.door, ROOM_B + 4], ms: 1000, arc: 26,
          onDone: () => trip(run, roomId!, "decision_take", run.finish, sayOf(a, null)),
        });
        return;
      }
      case "model_wait":
        if (a.room) flash(String(a.room), PAL_MAP.grey3, 900);
        run.finish();
        return;
      case "model_back":
        if (a.room) flash(String(a.room), PAL_MAP.yellow1, 900);
        task(run);
        return;
      case "done":
        scene.emit("confetti", opts.W / 2, 60, 40, { spread: 560 });
        task(run);
        return;
      default:
        // 其余动作是任务目录里的一件事：变成做它的角色的任务
        task(run);
    }
  }

  /** 进度：不排队，合并成做它的角色的一个持续姿势，头顶写最近的一项（原型 v13 floor.js 的 progress）。 */
  function progress(a: PixelAction): void {
    if (scene.frozen) return;
    const ch = doerOf(world, a);
    if (!ch) return;
    const def = catalog.tasks[a.kind];
    if (!def) return;
    // 真正的事情优先：正在做和排着的待机活动放弃
    if (ch.current && ch.current.idle) ch.current = null;
    ch.queue = ch.queue.filter((t) => !t.idle);
    const base: Task = { ...def, taskKey: a.kind, _t0: null, ...sayOf(a, null), until: scene.realT + def.ms };
    if (a.count !== undefined && a.count !== null) base.iconText = String(a.count);
    ch.progress = base;
  }

  /** 流式文字：接在正在做的进度姿势上（第一段文字取代默认的标签），不进时间线。 */
  function stream(who: { room: string | null; role?: string | null }, text: string): void {
    const ch = charFor(world, who.room ?? "", who.role ?? null, null);
    if (!ch || scene.frozen) return;
    const def = catalog.tasks.think;
    const base: Task = progressOf(ch, scene) ?? { ...def, taskKey: "think", _t0: null };
    const label = ((base.streamed ? base.label : "") + text).slice(-120);
    ch.progress = { ...base, label, streamed: true, until: scene.realT + def.ms };
  }

  /** 做这个动作的角色。 */
  function doerOf(w: World, a: PixelAction): Character | null {
    const def = catalog.tasks[a.kind];
    const department = def?.dept ?? asText(a.room);
    if (!department) return null;
    return charFor(w, department, def && def.actor ? null : asText(a.role), def ? (def.actor ?? def.by ?? null) : null);
  }

  /** 时间线：动作的级别与时长来自声明表，参与方是做这件事的角色（大厅与成果库按房间算）。 */
  const laneOf = (room: string | null, by?: string | null): string | null => {
    const id = room ?? "";
    if (!id) return null;
    if (!world.rooms[id] || world.rooms[id].roomKind !== "dept") return "room:" + id;
    const ch = charFor(world, id, null, by || "manager");
    return ch ? ch.id : "room:" + id;
  };

  function lanesOf(a: PixelAction): string[] {
    const def = catalog.tasks[a.kind];
    if (def) {
      const ch = doerOf(world, a);
      const peer = peerOf(world, a);
      return [ch && ch.id, peer && peer.id].filter((x): x is string => typeof x === "string");
    }
    switch (a.kind) {
      case "handoff":
      case "letter":
        return [laneOf(asText(a.from)), laneOf(asText(a.to))].filter((x): x is string => typeof x === "string");
      case "decision_out":
      case "decision_back":
        return [laneOf(asText(a.room))].filter((x): x is string => typeof x === "string");
      case "adopt":
        return ["room:" + rooms().lib.id];
      case "mail":
      case "parcel_in":
      case "queue_moved":
        return ["room:" + rooms().hall.id];
      case "parcel_enter":
        return ["room:" + rooms().hall.id, laneOf(rooms().out.to)].filter((x): x is string => typeof x === "string");
      case "resume":
        return Object.keys(world.characters);
      default:
        return [];
    }
  }

  /** 动作走向的另一个角色（分派与交回）。 */
  function peerOf(w: World, a: PixelAction): Character | null {
    const def = catalog.tasks[a.kind];
    if (!def || def.spot !== "peer") return null;
    const department = def.dept ?? asText(a.room);
    if (!department) return null;
    const ch = doerOf(w, a);
    const to = def.toward === "role" ? charFor(w, department, asText(a.role), null) : charFor(w, department, null, def.toward ?? null);
    return to && to !== ch ? to : null;
  }

  const runs = new Map<number, Run>();
  const tl: Timeline = createTimeline({
    clock: () => scene.realT,
    classify(a) {
      const k = catalog.kinds[a.kind];
      if (!k) throw new Error("楼层的声明表里没有这种动作：" + a.kind);
      return { tier: k.tier, ms: k.ms, lanes: lanesOf(a) };
    },
    begin(e: TimelineEntry) {
      const run: Run = {
        id: e.id,
        action: e.action,
        lanes: e.lanes,
        dead: false,
        alive: () => !run.dead,
        finish: () => {
          if (!run.dead && runs.has(e.id)) {
            runs.delete(e.id);
            tl.done(e.id);
          }
        },
      };
      runs.set(e.id, run);
      perform(run);
    },
    cut(e: TimelineEntry) {
      const run = runs.get(e.id);
      if (run) run.dead = true;
      runs.delete(e.id);
      dropAction(world, e.id);
    },
    apply(s: PixelState) {
      applyState(s as unknown as FloorModel);
    },
    progress,
  });

  function applyState(next: FloorModel): void {
    model = { ...next, decisions };
    const nextFlags = flagsOf(model, catalog);
    if (JSON.stringify(nextFlags) !== JSON.stringify(flags)) {
      // 快照里的运维数据出现或消失：房间与管道按新的条件重新声明，角色、包裹、信号与管道的流动状态原样带过去
      flags = nextFlags;
      const old = world;
      world = declareWorld(model, catalog);
      world.characters = old.characters;
      world.packages = old.packages;
      world.signals = old.signals;
      for (const key of Object.keys(world.links)) {
        if (old.links[key]) world.links[key].flow = old.links[key].flow;
      }
    }
    syncWorkers();
    // 角色被撤走（状态里的角色变了）：用到它们的动作不会再演完，时间线不再等它们
    for (const run of Array.from(runs.values())) {
      if (run.lanes.some((l) => !l.startsWith("room:") && !world.characters[l])) run.finish();
    }
    // 整层静止（中断）时，演到一半的动作停在原处，时间线不再等它们
    if (model.interrupted && !scene.frozen) Array.from(runs.values()).forEach((run) => run.finish());
    scene.frozen = Boolean(model.interrupted);
  }

  function setState(next: FloorModel): void {
    tl.state(checkFloorState(next));
  }

  function jump(next: FloorModel): void {
    tl.jump(checkFloorState(next));
  }

  function play(a: PixelAction): void {
    tl.push(checkAction("楼层", a, catalog.kinds));
  }

  function setDecisions(list: DecisionFace[]): void {
    decisions = list ?? [];
    model = { ...model, decisions };
  }

  function itemById(id: string | null): LoopItem | null {
    if (!id) return null;
    return model.items.find((x) => x.id === id || x.work_item_id === id) ?? null;
  }

  /** 管道通不通：快照里两端有活跃事项，或者管道上有包裹在移动。 */
  function pipeState(pipe: World["links"][string]): "flowing" | "idle" | "stopped" {
    if (model.interrupted) return "stopped";
    const [a, b] = pipe.id.split(/[>~]/);
    if (waitingDept(a) || waitingDept(b)) return "stopped";
    const active = (department: string): boolean => busyItems(model, department).some((it) => ACTIVE.includes(it.status));
    if (Object.values(world.packages).some((pk) => pk.transit && pk.transit.linkKey === pipe.id)) return "flowing";
    if (pipe.linkKind === "tube") return model.open_requests.length ? "flowing" : "idle";
    return active(a) || active(b) ? "flowing" : "idle";
  }

  function step(): void {
    tl.tick();
    scene.rate = tl.rate();
    if (!model.interrupted) state.clock += scene.reduced ? 0 : 16.7;
    stepPackages(world, scene);
    stepPipes(world, scene, pipeState);
    stepCharacters(world, scene);
    for (const ch of Object.values(world.characters)) {
      const actor = actorOf(scene, ch.id);
      if (actor) actor.dim = dimFor(ch.item?.work_item_id ?? null);
    }
    state.arrows = state.arrows.filter((ar) => ar.until > scene.realT);
    state.remoteDots = state.remoteDots.filter((dot) => scene.realT - dot.t0 < dot.ms);
  }

  function dimFor(itemId: string | null): number {
    const focus = scene.focusId;
    return focus && itemId && itemId !== focus ? 0.3 : 1;
  }

  function boardRectOf(lay: { hall: NonNullable<ReturnType<typeof roomOf>> }): BoardRect {
    return { x: lay.hall.x + 62, y: 160, w: 32, h: 24 };
  }

  applyState(model);

  return {
    get world(): World {
      return world;
    },
    get model(): FloorModel {
      return model;
    },
    state,
    setState,
    jump,
    play,
    stream,
    setDecisions,
    step,
    boardRect: () => boardRectOf(rooms()),
    decisionHidden: (id, now) => (state.hidden[id] ?? 0) > now,
    saidOf: (id, now) => {
      const s = state.said[id];
      return s && s.until > now ? s : null;
    },
    declCtx: () => ctx as DeclContext,
    inspectTimeline: () => tl.inspect(),
  };
}

/** 大厅的决定板上的决定请求：还在路上的不算。 */
export function visibleDecisions(decisions: DecisionFace[], hidden: HiddenMap, now: number): DecisionFace[] {
  return decisions.filter((d) => !((hidden[d.id] ?? 0) > now));
}

/** 事项的颜色序号到色板。 */
export function itemColor(item: { color_index?: number }): string {
  return ITEM_COLORS[(Number(item.color_index) || 0) % ITEM_COLORS.length];
}

function tubeFor(world: World, from: string, to: string): [number, number][] | null {
  const link = linkBetween(world, from, to, "tube");
  return link ? link.pts : null;
}

function tubeKeyOf(world: World, from: string, to: string): string | null {
  const link = linkBetween(world, from, to, "tube");
  return link ? link.key : null;
}
