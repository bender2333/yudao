// 项目楼层的驱动：按快照配置世界（声明、角色、持续状态），把事件变成任务、包裹与信号（原型 v10 floor.js
// 与设计说明第 4、5 节，工单 #82）。
//
// 世界与系统都在这里维护；画面渲染只读这里给出的世界与状态。驱动不依赖 PixiJS：
// 飞行物、粒子与说话停留都记在驱动自己的状态里，渲染层照读。

import { declareLinks, declareRooms, linkBetween, route, roomOf } from "./declare.ts";
import { dispatch, enqueue, nextPackageId, sendPackage, spawnPackage, stepCharacters, stepPackages, stepPipes } from "./characters.ts";
import { actorOf, charFor, primaryOf, syncCharacters, mountMachines } from "./scene.ts";
import { say, sayMs } from "./say.ts";
import { signal, signalOn } from "./signals.ts";
import type {
  Catalog, Character, DecisionFace, DeclContext, FloorModel, LoopItem, PackageVisual, PixelFloorEvent, SceneLike, Task, TaskDef, TaskFx, World,
} from "./types.ts";
import { createWorld } from "./declare.ts";

/** 会待在房间内的事项状态（原型 floor.js 的 IN_ROOM）。 */
export const IN_ROOM = ["running", "asking", "waiting_provider", "paused", "failed", "done", "cancelled", "interrupted", "waiting_resume", "waiting_decision", "stopped_for_upgrade"];
/** 房间亮灯与管道流动对应的活跃事项状态。 */
export const ACTIVE = ["running", "asking"];

const PIPE_Y = 138;
const TOP = 50;
const ROOM_B = 214;
const CORR_Y = 238;

const ART_BMP: Record<string, string> = { prd: "scroll", box: "box_sealed", defect: "box_rework", release: "box_release", letter: "letter" };

const ITEM_COLORS = ["#d9534f", "#4a90d9", "#5cb85c", "#f0ad4e", "#9b59b6", "#e67e22"];

const PAL_MAP: Record<string, string> = {
  red2: "#d9534f", red3: "#b52b27", green2: "#5cb85c", green3: "#3d8b40", orange1: "#e67e22",
  orange2: "#f0ad4e", yellow1: "#ffd66b", yellow2: "#f7e07a", white: "#ffffff", blue1: "#6ba8d9", blue2: "#4a90d9",
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

export interface FloorDriver {
  world: World;
  model: FloorModel;
  state: FloorState;
  /** 重新按快照配置世界与角色。 */
  setModel: (model: FloorModel) => void;
  /** 把一条事件变成任务、包裹与信号。 */
  playEvent: (event: PixelFloorEvent) => void;
  /** 每帧推进：包裹、管道、角色。 */
  step: () => void;
  /** 决定板的矩形（画面与点击共用）。 */
  boardRect: () => BoardRect;
  /** 决定单还在路上（板上暂时看不到它）。 */
  decisionHidden: (id: string, now: number) => boolean;
  /** 每个角色此刻头顶说的话（画面按 until 读取）。 */
  saidOf: (id: string, now: number) => { text: string; until: number } | null;
  /** 房间声明的 props、lit、tint 读取画面数据的窗口。 */
  declCtx: () => DeclContext;
}

/** 建立一个楼层驱动：世界、角色与画面状态都在这里维护。 */
export function createFloorDriver(opts: FloorDriverOptions): FloorDriver {
  const scene = opts.scene;
  const state = opts.state;
  const catalog = opts.catalog;
  let model = opts.model;
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

  function rooms(): { hall: NonNullable<ReturnType<typeof roomOf>>; lib: NonNullable<ReturnType<typeof roomOf>> | null; depts: NonNullable<ReturnType<typeof roomOf>>[]; out: World["links"][string]; door: NonNullable<World["machineDoor"]> } {
    const list = world.roomOrder.map((id) => world.rooms[id]);
    const hall = list.find((r) => r.roomKind === "hall");
    if (!hall) throw new Error("楼层没有声明大厅");
    const out = Object.values(world.links).find((l) => l.from === hall.id && l.linkKind === "handoff");
    if (!out) throw new Error("大厅没有交接管道");
    if (!world.machineDoor) throw new Error("楼层没有声明通往机房的门");
    return { hall, lib: list.find((r) => r.roomKind === "shelf") ?? null, depts: list.filter((r) => r.roomKind === "dept"), out, door: world.machineDoor };
  }

  const itemsIn = (department: string): LoopItem[] => model.items.filter((it) => it.department === department && IN_ROOM.includes(it.status));
  const waitingDept = (department: string): { department: string; next_retry_at: string | null } | null =>
    model.waiting_provider.find((w) => w.department === department) ?? null;
  const primaryItem = (department: string): LoopItem | null => {
    const here = itemsIn(department);
    return here.find((it) => ACTIVE.includes(it.status)) ?? here.find((it) => it.status === "waiting_provider") ?? here[0] ?? null;
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

  /** 小人头顶说的话（来自 say.ts）；目录里没有这类事件时任务用自己声明的标签。 */
  function sayOf(ev: PixelFloorEvent, department: string, side: "to" | "from" | null): Partial<Task> {
    const text = say(ev, { dept: department, side, roleName: (id) => world.characters[id ?? ""]?.name ?? null });
    return text ? { label: text } : {};
  }

  /** 小人走到管道口放下或取出包裹：任务放到队首（交接不排队），做完以后执行 after。 */
  function trip(department: string, key: string, after?: (() => void) | null, extra?: Partial<Task> | null): void {
    if (scene.reduced) {
      const def = catalog.tasks[key];
      const ch = def ? charFor(world, department, null, def.actor ?? def.by ?? null) : null;
      if (ch && extra?.label) state.said[ch.id] = { text: extra.label, until: scene.realT + sayMs(extra.label) };
      after?.();
      return;
    }
    const task = enqueue(world, department, key, { front: true, must: true, onDone: after ?? undefined, ...(extra ?? {}) });
    if (!task) after?.();
  }

  /** 包裹沿管道走：减少动画时改成管道上的箭头。 */
  function send(pts: [number, number][] | null, bmp: string, opt: Partial<PackageVisual>): void {
    if (!pts) {
      opt.onDone?.();
      return;
    }
    if (scene.reduced) {
      state.arrows.push({ pts, color: opt.color ?? "#ffffff", bmp, itemId: opt.itemId ?? null, dash: Boolean(opt.small), until: scene.realT + 3600 });
      opt.onDone?.();
      return;
    }
    const id = nextPackageId();
    spawnPackage(world, id, opt.itemId ?? null, null, opt.artifact ?? null, null);
    const pk = world.packages[id];
    pk.bmp = bmp;
    pk.color = opt.color ?? null;
    pk.small = opt.small;
    sendPackage(world, scene, id, opt.linkKey ?? null, pts, opt.ms, () => {
      delete world.packages[id];
      opt.onDone?.();
    });
  }

  const flash = (roomId: string, color: string, ms: number): void => {
    state.flash[roomId] = { color, until: scene.realT + ms };
  };

  /** 任务声明里的效果：信号、房间闪光、包裹沿管道走。 */
  function applyFx(fx: TaskFx, department: string): void {
    if (fx.signal) signal(world, scene, fx.signal, fx.ms ?? 0);
    if (fx.flash) flash(fx.flash.room === "self" ? department : fx.flash.room, PAL_MAP[fx.flash.color] ?? "#ffffff", fx.flash.ms ?? 900);
    if (fx.send) {
      const link = world.links[fx.send.link];
      if (!link) return;
      send(fx.send.reverse ? link.pts.slice().reverse() : link.pts, fx.send.bmp, {
        color: fx.send.color ? (PAL_MAP[fx.send.color] ?? "#ffffff") : null,
        linkKey: link.id,
        onDone: () => {
          for (const next of fx.send!.then ?? []) applyFx(next, department);
        },
      });
    }
  }

  /** 交给 dispatch 的 make：任务头顶说的内容与声明里的效果。 */
  function extrasOf(def: TaskDef, ev: PixelFloorEvent, ch: Character, side?: "to" | "from"): Partial<Task> {
    const out: Partial<Task> = sayOf(ev, ch.department!, side ?? null);
    if (def.fx) {
      const run = (when: string) => (): void => {
        for (const fx of def.fx!.filter((x) => x.when === when)) applyFx(fx, ch.department!);
      };
      out.start = run("start");
      out.done = run("done");
    }
    return out;
  }

  const dispatchTask = (ev: PixelFloorEvent): boolean => dispatch(world, ev, extrasOf);

  function playEvent(ev: PixelFloorEvent): void {
    if (!ev || !ev.type) throw new Error("playEvent 需要事件对象");
    const pl = (ev.payload ?? {}) as Record<string, unknown>;
    const wid = ev.work_item_id ?? null;
    // 原型 floor.js 的 itemById 按事项的 id 查；快照里的事项同时带 work_item_id
    const item = wid ? (model.items.find((x) => x.id === wid || x.work_item_id === wid) ?? null) : null;
    const color = item ? ITEM_COLORS[item.color_index % ITEM_COLORS.length] : null;
    const lay = rooms();
    const order = world.roomOrder;
    switch (ev.type) {
      case "user_input_received":
      case "work_item_created":
        if (!scene.reduced) {
          scene.fly({ bmp: "letter", from: [-6, PIPE_Y - 20], to: [lay.hall.x + 16, PIPE_Y + 6], ms: 900, arc: 20, onDone: () => signal(world, scene, "mail", 1500) });
        } else {
          signal(world, scene, "mail", 1500);
        }
        return;
      case "department_activated":
        if (ev.department && world.rooms[ev.department]) flash(ev.department, "#ffd66b", 700);
        return;
      case "transition": {
        let to = pl.to as string;
        if (to === "adopted" || to === "adoption") to = lay.lib!.id;
        const from = pl.from as string;
        // 两个房间之间没有直接的管道时，包裹沿声明的管道一段一段走过去
        const hops = route(world, from, to);
        if (!hops.length) return;
        const ids = lay.depts.map((r) => r.id);
        const rework = pl.artifact === "defect" || hops[0].link.linkKind === "return" || (ids.includes(from) && ids.includes(to) && order.indexOf(from) > order.indexOf(to));
        if (rework) for (const hop of hops) state.pipeFlash[hop.key] = scene.realT + 2600;
        const bmp = ART_BMP[pl.artifact as string] ?? "box_sealed";
        // 交出方走到管道口放下包裹，包裹沿管道移动，接收方走到管道口取出：两端各是一个任务
        const arrive = (): void => {
          flash(to, "#ffffff", 500);
          trip(to, rework ? "package_return_in" : "package_handoff_in", null, sayOf(ev, to, "to"));
        };
        const leg = (i: number): void => send(hops[i].pts, bmp, {
          itemId: wid, color, linkKey: hops[i].key,
          onDone: () => (i + 1 < hops.length ? leg(i + 1) : arrive()),
        });
        trip(from, rework ? "package_return_out" : "package_handoff_out", () => leg(0), sayOf(ev, from, "from"));
        return;
      }
      case "qa_submitted":
        if (ev.department) flash(ev.department, pl.verdict === "release" ? "#5cb85c" : "#d9534f", 1200);
        dispatchTask(ev);
        return;
      // 传信：发信的经理走到管口塞进信，信沿传信管走，收信的经理走到信来的那一侧管口取信
      case "collaboration_requested": {
        const from = pl.from as string;
        const to = pl.to as string;
        const forward = order.indexOf(to) > order.indexOf(from);
        trip(from, forward ? "letter_out" : "letter_in", () => send(tubeFor(world, from, to), "letter", {
          small: true, itemId: wid, color: "#4a90d9", linkKey: tubeKeyOf(world, from, to) ?? undefined,
          onDone: () => trip(to, forward ? "letter_arrive_in" : "letter_arrive_out", null, sayOf(ev, to, "to")),
        }), sayOf(ev, from, "from"));
        return;
      }
      case "collaboration_responded": {
        // 回答方是事件所在的部门（示例数据里 from 是回答方，v8 构建约定里 to 是回答方），另一头是发问方
        const answerer = (ev.department ?? pl.to) as string;
        const asker = pl.from === answerer ? (pl.to as string) : (pl.from as string);
        const forward = order.indexOf(asker) > order.indexOf(answerer);
        trip(answerer, forward ? "letter_out" : "letter_in", () => send(tubeFor(world, answerer, asker), "letter", {
          small: true, itemId: wid, color: "#5cb85c", linkKey: tubeKeyOf(world, answerer, asker) ?? undefined,
          onDone: () => trip(asker, forward ? "letter_arrive_in" : "letter_arrive_out", null, sayOf(ev, asker, "to")),
        }), sayOf(ev, answerer, "from"));
        return;
      }
      case "deliverable_adopted":
        signal(world, scene, "shelf", 1800);
        scene.emit("spark", lay.lib!.x + lay.lib!.w / 2, 110, 16);
        return;
      case "x_queued":
      case "x_repair_created":
        signal(world, scene, "mail", 1500);
        if (!scene.reduced) {
          scene.fly({ bmp: ev.type === "x_repair_created" ? "box_rework" : "box", from: [lay.hall.x + 16, PIPE_Y + 10], to: [lay.hall.x + 50, PIPE_Y - 4], ms: 700, arc: 14 });
        }
        return;
      case "x_slot_acquired":
        flash(lay.hall.id, "#5cb85c", 900);
        send(lay.out.pts, "box", { itemId: wid, color, linkKey: lay.out.id, onDone: () => trip(lay.out.to, "package_handoff_in") });
        return;
      case "x_queue_reordered":
        flash(lay.hall.id, "#6ba8d9", 900);
        return;
      case "x_run_interrupted":
        return;
      case "x_run_auto_resumed":
        for (const id of Object.keys(world.characters)) enqueue(world, id, "x_run_auto_resumed");
        for (const room of lay.depts) flash(room.id, "#ffd66b", 700);
        return;
      case "x_action_unknown":
        if (ev.department) flash(ev.department, "#f0c040", 1400);
        return;
      case "x_remote_action_started":
      case "x_remote_action_finished":
      case "x_late_receipt": {
        signal(world, scene, "door", 1800);
        const room = ev.department ? roomOf(world, ev.department) : null;
        if (room && !scene.reduced) {
          const from: [number, number] = ev.type === "x_remote_action_started" ? [room.door, ROOM_B + 6] : [lay.door.x, CORR_Y];
          const to: [number, number] = ev.type === "x_remote_action_started" ? [lay.door.x, CORR_Y] : [room.door, ROOM_B + 6];
          state.remoteDots.push({ from, to, t0: scene.realT, ms: 1400 });
        }
        return;
      }
      case "decision_requested":
      case "x_decision_issued":
      case "project_decision_requested": {
        // 提出决定的部门的小人走到门口送出决定单，决定单飞到大厅的板上；决定单在路上的时候板上还看不到它。
        // 决定的身份是事件的 event_id（投影按它登记决定请求）；没有部门的决定请求（初始 PRD）从大厅上方飞进来
        // 事件没有部门时按它所属事项的部门承担动作（原型 floor.js：ev.department || it.department）
        const department = (ev.department ?? item?.department ?? null) as string | null;
        const room = department && world.rooms[department] && world.rooms[department].roomKind === "dept" ? world.rooms[department] : null;
        const board = boardRectOf(lay);
        const decisionId = (ev.event_id ?? (pl.decision_id as string | undefined)) ?? null;
        if (decisionId) state.hidden[decisionId] = scene.realT + 12000;
        let posted = false;
        const post = (): void => {
          if (posted) return;
          posted = true;
          scene.fly({
            bmp: "decision",
            from: room ? [room.door, ROOM_B + 4] : [board.x + board.w / 2, TOP - 6],
            to: [board.x + board.w / 2, board.y + board.h / 2],
            ms: 1000, arc: 26,
            onDone: () => {
              if (decisionId) delete state.hidden[decisionId];
              signal(world, scene, "board", 1600);
            },
          });
        };
        // 送单由经理做：任务键用事件本身的类型（原型 floor.js 只补部门），
        // 事件类型是 decision_requested 时才换成原型声明里的 x_decision_issued。
        // 说话用任务声明里的标签（原型 floor.js：make 只带 done，不按事件的 kind 换词）
        const postKey = ev.type === "decision_requested" ? "x_decision_issued" : ev.type;
        const postEvent = { ...ev, type: postKey, department } as PixelFloorEvent;
        const postMake = (): Partial<Task> => ({ done: post });
        if (room && !scene.reduced && dispatch(world, postEvent, postMake)) {
          scene.after(8000, post);
        } else post();
        return;
      }
      case "decision_answered":
      case "x_decision_answered":
      case "project_decision_answered": {
        // 回答过的决定单从板上飞回提出决定的部门的门口，经理在门口收下；正在展开的那张纸盖上章
        // 事件没有部门时按它所属事项的部门承担动作（原型 floor.js：ev.department || it.department）
        const department = (ev.department ?? item?.department ?? null) as string | null;
        const room = department && world.rooms[department] && world.rooms[department].roomKind === "dept" ? world.rooms[department] : null;
        const board = boardRectOf(lay);
        const decisionId = pl.decision_id as string | undefined;
        if (decisionId && scene.cardStamped) scene.cardStamped(decisionId, "已回答");
        // 任务键用事件本身的类型（原型 floor.js 只补部门）；decision_answered 换成原型声明里的 x_decision_answered
        const answerEvent = { ...ev, type: ev.type === "decision_answered" ? "x_decision_answered" : ev.type, department } as PixelFloorEvent;
        if (room) {
          scene.fly({
            bmp: "decision",
            from: [board.x + board.w / 2, board.y + board.h / 2],
            to: [room.door, ROOM_B + 4],
            ms: 1000, arc: 26,
            onDone: () => {
              if (!scene.reduced) dispatch(world, answerEvent, (def, event, ch) => extrasOf(def, event, ch, "to"));
            },
          });
        }
        return;
      }
      case "decision_withdrawn": {
        // 决定请求被撤销：板上不再有它（快照刷新以后由查询结果决定），画面上只把板子闪一下
        signal(world, scene, "board", 900);
        return;
      }
      case "x_provider_wait_entered":
      case "x_provider_wait_left":
        if (ev.department) flash(ev.department, ev.type === "x_provider_wait_entered" ? "#8a90a0" : "#ffd66b", 900);
        if (ev.type === "x_provider_wait_left") dispatchTask(ev);
        return;
      case "run_done":
        scene.emit("confetti", opts.W / 2, 60, 40, { spread: 560 });
        dispatchTask(ev);
        return;
      default:
        // 其余事件由任务目录决定：命中的事件变成角色的任务，没有命中的事件在画面上没有小人的动作
        dispatchTask(ev);
    }
  }

  /** 管道通不通：快照里两端有活跃事项，或者管道上有包裹在移动。 */
  function pipeState(pipe: World["links"][string]): "flowing" | "idle" | "stopped" {
    if (model.interrupted) return "stopped";
    const [a, b] = pipe.id.split(/[>~]/);
    if (waitingDept(a) || waitingDept(b)) return "stopped";
    const active = (department: string): boolean => itemsIn(department).some((it) => ACTIVE.includes(it.status));
    if (Object.values(world.packages).some((pk) => pk.transit && pk.transit.linkKey === pipe.id)) return "flowing";
    if (pipe.linkKind === "tube") return model.open_requests.length ? "flowing" : "idle";
    return active(a) || active(b) ? "flowing" : "idle";
  }

  function step(): void {
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

  function setModel(next: FloorModel): void {
    model = next;
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
    scene.frozen = Boolean(model.interrupted);
  }

  function boardRectOf(lay: { hall: NonNullable<ReturnType<typeof roomOf>> }): BoardRect {
    return { x: lay.hall.x + 62, y: 160, w: 32, h: 24 };
  }

  setModel(model);

  return {
    get world(): World {
      return world;
    },
    get model(): FloorModel {
      return model;
    },
    state,
    setModel,
    playEvent,
    step,
    boardRect: () => boardRectOf(rooms()),
    decisionHidden: (id, now) => (state.hidden[id] ?? 0) > now,
    saidOf: (id, now) => {
      const s = state.said[id];
      return s && s.until > now ? s : null;
    },
    declCtx: () => ctx as DeclContext,
  };
}

/** 大厅的决定板上的决定请求：还在路上的不算；最多画 6 张。 */
export function visibleDecisions(decisions: DecisionFace[], hidden: HiddenMap, now: number): DecisionFace[] {
  return decisions.filter((d) => !((hidden[d.id] ?? 0) > now));
}

/** 事项的颜色序号到色板。 */
export function itemColor(item: LoopItem): string {
  return ITEM_COLORS[item.color_index % ITEM_COLORS.length];
}

function tubeFor(world: World, from: string, to: string): [number, number][] | null {
  const link = linkBetween(world, from, to, "tube");
  return link ? link.pts : null;
}

function tubeKeyOf(world: World, from: string, to: string): string | null {
  const link = linkBetween(world, from, to, "tube");
  return link ? link.key : null;
}
