// 角色、包裹与管道的推进，任务派发与队列规则（原型 v9 设计说明第 4、5 节与 ecs.js 第 3.3 至 3.6 节，
// 工单 #82）。世界与系统不依赖渲染：角色空着时取队首、走到 spot、做 ms 毫秒的 pose；
// 事件按规则找到做事的角色；包裹沿管道的折线移动；管道带着惯性流动。每个角色与每根管道各有一个状态机。

import { roomOf } from "./declare.ts";
import { actorOf, charsOf, charFor } from "./scene.ts";
import { polyLength, pointAt } from "./declare.ts";
import type { Character, HeadIconKind, IdleDef, RestState, Seat, SpotKind, Step, Task, TaskDef, World } from "./types.ts";
import type { SceneLike } from "./types.ts";

/** 队列里最多留几个可以被挤掉的任务（must 的任务不受限制）。 */
const MAX_QUEUE = 3;

const GEO = {
  TOP: 50, ROOM_B: 214, FLOOR_LINE: 150, DESK_Y: 196, PORT_STAND: 176, PIPE_Y: 138, TUBE_Y: 104,
  DUCT_Y: 30, DUCT_TUBE_Y: 42, UNDER_Y: 276, GAP: 6,
};

/** 放进队列时的附加字段：front 插到队首，roleId 指定事件的接任务角色。 */
export interface EnqueueExtra extends Partial<Task> {
  front?: boolean;
  roleId?: string;
}

/** 把一个任务放进角色的队列。who 是角色 id 或部门 id；extra 覆盖任务的字段。 */
export function enqueue(world: World, who: string, key: string, extra?: EnqueueExtra | null): Task | null {
  const def = world.catalog.tasks[key];
  if (!def) return null;
  const e = extra ?? {};
  const ch = world.characters[who] ?? charFor(world, who, def.actor ? null : (e.roleId ?? null), def.actor ?? def.by ?? null);
  if (!ch) return null;
  const task: Task = { ...def, ...e, taskKey: key, _t0: null };
  if (!task.idle) {
    // 真正的事情优先：正在做和排着的待机活动放弃
    if (ch.current && ch.current.idle) ch.current = null;
    ch.queue = ch.queue.filter((t) => !t.idle);
  }
  if (e.front) {
    ch.queue.unshift(task);
    if (ch.current && !ch.current.must) ch.current = null;
  } else {
    ch.queue.push(task);
  }
  while (ch.queue.filter((t) => !t.must).length > MAX_QUEUE) {
    ch.queue.splice(ch.queue.findIndex((t) => !t.must), 1);
  }
  return task;
}

/** 事件到达：命中任务目录则入队并返回真；没有命中返回假，由调用方按信号处理。 */
export function dispatch<E>(
  world: World,
  event: { type: string; department?: string | null; role?: string | null; work_item_id?: string | null; payload?: Record<string, unknown> },
  make?: (def: TaskDef, event: E, character: Character, side?: "to" | "from") => Partial<Task> | null,
): boolean {
  if (!event || !event.type) throw new Error("dispatch 需要事件对象");
  const key = world.catalog.keyOf(event as never);
  const def = world.catalog.tasks[key];
  if (!def) return false;
  // 任务声明了 dept 就由那个部门做（事件本身可以没有部门字段），否则是事件的部门
  const department = def.dept ?? event.department ?? null;
  if (!department) return false;
  const ch = charFor(world, department, def.actor ? null : (event.role ?? null), def.actor ?? def.by ?? null);
  if (!ch) return false;
  const payload = event.payload ?? {};
  if (def.streaming) {
    // 流式输出：文字接在正在做的模型请求上（第一段文字取代默认的标签）；没有正在做的请求就不产生任务
    const cur = ch.current;
    if (cur && cur.taskKey === "model_requested") {
      cur.label = ((cur.streamed ? cur.label : "") + String(payload.text ?? "")).slice(-120);
      cur.streamed = true;
      cur._t0 = null;
      return true;
    }
    return false;
  }
  const extra: Partial<Task> = { workItemId: event.work_item_id ?? null };
  if (payload.n !== undefined && payload.of !== undefined) extra.iconText = `${payload.n}/${payload.of}`;
  if (def.spot === "peer") {
    const toward = def.toward === "role" ? charFor(world, department, event.role ?? null, null) : charFor(world, department, null, def.toward ?? null);
    if (!toward || toward === ch) return false;
    extra.withId = toward.id;
    if (def.then) {
      extra.onDone = () => {
        enqueue(world, toward.id, def.then!, make ? make(world.catalog.tasks[def.then!], event as unknown as E, toward, "to") : null);
      };
    }
  }
  if (make) Object.assign(extra, make(def, event as unknown as E, ch));
  return Boolean(enqueue(world, ch.id, key, extra));
}

/** 命名位置在画面上的坐标与朝向。 */
export interface SpotResult {
  x: number;
  y: number;
  seat: Seat | null;
  facing?: number;
}

/** 命名位置到画面坐标（原型 ecs.js 的 spotXY）。 */
export function spotXY(world: World, ch: Character, kind: SpotKind | null | undefined, task: Task | RestState): SpotResult {
  const room = ch.department === null ? null : roomOf(world, ch.department);
  if (!room || !kind) return { x: ch.spot.x, y: ch.spot.y, seat: null };
  const seat = seatOf(room, ch);
  if (kind === "desk" || kind === "inspect") return { x: seat.seatX, y: seat.seatY, seat };
  if (kind === "stand") return { x: seat.seatX, y: seat.seatY, seat: null };
  if (kind === "cabinet") return { x: room.cabinet.x, y: GEO.DESK_Y, seat: null };
  if (kind === "terminal") return { x: room.terminal.x, y: room.terminal.y, seat: null };
  if (kind === "monitor") return { x: room.monitor.x, y: room.monitor.y, seat: null };
  if (kind === "door") return { x: room.door, y: GEO.ROOM_B - 10, seat: null };
  if (kind === "port_out") return { x: room.outPort - 6, y: GEO.PORT_STAND, seat: null };
  if (kind === "port_in") return { x: room.inPort + 6, y: GEO.PORT_STAND, seat: null };
  if (kind === "at") {
    const at = (task as Task).at;
    if (!at) throw new Error("spot 为 at 的任务缺少坐标");
    return { x: at.x, y: at.y, seat: null };
  }
  if (kind === "peer") {
    const peerId = (task as Task).withId;
    const peer = peerId ? world.characters[peerId] : null;
    const peerRoom = peer && peer.department ? roomOf(world, peer.department) : null;
    if (!peer || !peerRoom) return { x: seat.seatX, y: seat.seatY, seat: null };
    const ps = seatOf(peerRoom, peer);
    const dir = ps.seatX >= seat.seatX ? 1 : -1;
    return { x: ps.seatX - dir * 12, y: GEO.PORT_STAND, seat: null, facing: dir };
  }
  throw new Error(`未知的 spot：${kind}`);
}

function seatOf(room: { seats: Seat[] | null; desk: Seat }, ch: Character): Seat {
  return (room.seats && room.seats[ch.seatIndex]) || room.desk;
}

/** 空闲角色的默认摆放：坐在自己的工位喝茶。 */
function idleRestFor(world: World, ch: Character): SpotResult {
  const room = ch.department === null ? null : roomOf(world, ch.department);
  if (!room) return { x: ch.spot.x, y: ch.spot.y, seat: null };
  const seat = seatOf(room, ch);
  return { x: seat.seatX, y: seat.seatY, seat };
}

/** 空闲的角色自己挑一件事做（按权重抽一项）；同一个房间里的角色越多，每个人挑得越稀。 */
function startIdle(world: World, ch: Character, scene: SceneLike): void {
  const room = ch.department === null ? null : roomOf(world, ch.department);
  if (!room) return;
  const mates = charsOf(world, ch.department!).filter((c) => c !== ch && idleFree(c));
  const pool = world.catalog.idle.filter((it: IdleDef) => (!it.kinds || it.kinds.includes(ch.roleKind)) && (!it.needs || mates.length));
  const total = pool.reduce((s, it) => s + it.weight, 0);
  if (!total) return;
  let k = scene.random() * total;
  const pick = pool.find((it) => (k -= it.weight) < 0) ?? pool[pool.length - 1];
  const mate = pick.needs ? mates[Math.floor(scene.random() * mates.length)] : null;
  const pos = (frac: number): number => Math.round(room.x + 18 + frac * (room.w - 36));
  if (pick.at === "wander") {
    enqueue(world, ch.id, pick.key, { idle: true, at: { x: pos(scene.random()), y: GEO.PORT_STAND } });
  } else if (pick.at === "door") {
    enqueue(world, ch.id, pick.key, { idle: true, at: { x: room.door, y: GEO.PORT_STAND } });
  } else if (pick.needs && mate) {
    // 两个空闲的角色在房间中间碰头说话
    const mid = pos(scene.random());
    enqueue(world, ch.id, pick.key, { idle: true, at: { x: mid - 9, y: GEO.PORT_STAND }, facing: 1 });
    enqueue(world, mate.id, pick.key, { idle: true, at: { x: mid + 9, y: GEO.PORT_STAND }, facing: -1 });
  } else {
    enqueue(world, ch.id, pick.key, { idle: true });
  }
}

function idleFree(ch: Character): boolean {
  return !ch.current && !ch.queue.length && ch.rest !== null && ch.rest.pose === "tea" && !ch.rest.away;
}

/** 当前应显示的气泡：说话气泡是正在做的任务，思考气泡是队列里的下一项（只读）。 */
export function bubbleFor(ch: Character): Character["bubble"] {
  const cur = ch.current;
  if (cur && cur.bubble === "say" && cur.label) return { text: cur.label, kind: "say", tail: Boolean(cur.streamed) };
  const next = ch.queue[0];
  if (next && next.bubble === "say" && next.label) return { text: next.label, kind: "think" };
  return null;
}

/** 每帧推进一步：取队首、走到目标、播放姿势与计时。角色与管道的状态机在这里被驱动。 */
export function stepCharacters(world: World, scene: SceneLike): void {
  for (const ch of Object.values(world.characters)) stepOne(world, scene, ch);
}

function stepOne(world: World, scene: SceneLike, ch: Character): void {
  const actor = actorOf(scene, ch.id);
  if (!actor) return;
  if (ch.current || ch.queue.length) ch.idleAt = null;
  // 待机活动的走路被真正的任务打断：放弃走到一半的路，直接去做真正的任务
  if (!ch.current && ch.queue.length && actor.script && actor.data.idleWalk) {
    scene.cancel(actor);
    actor.data.idleWalk = false;
  }
  // 走路的脚本还没结束不换任务；整层静止（中断）时小人不出发，队列等着
  if (!ch.current && ch.queue.length && !actor.script && !scene.frozen) {
    ch.current = ch.queue.shift()!;
    ch.current._t0 = null;
  }
  const task = ch.current;
  const goal: Task | RestState | null = task ?? ch.rest;
  const room = ch.department === null ? null : roomOf(world, ch.department);
  // 不在房间里（外出）：从画面上消失，回来时从门口走进来
  if (goal && goal.away) {
    actor.visible = false;
    actor.seat = null;
    ch.bubble = null;
    scene.setCharacterState(ch, "away");
    return;
  }
  if (!actor.visible && room) {
    actor.visible = true;
    actor.seat = null;
    actor.x = room.door;
    actor.y = GEO.ROOM_B - 6;
  }
  const spot = goal ? spotXY(world, ch, goal.spot ?? null, goal) : idleRestFor(world, ch);
  const pose = goal ? (goal.pose ?? "idle") : (spot.seat ? "tea" : "idle");
  const facing = (goal?.facing ?? 0) || spot.facing || 0;
  const atSpot = Math.hypot(actor.x - spot.x, actor.y - spot.y) < 1.5 && (spot.seat ? actor.seat === spot.seat : !actor.seat);
  if (!atSpot) {
    if (!actor.script && !scene.frozen) {
      scene.setCharacterState(ch, task ? "going" : "resting");
      const steps: Step[] = [];
      if (actor.seat) steps.push({ t: "seat", seat: null }, { t: "anim", name: "idle", ms: 120 });
      steps.push({ t: "go", x: spot.x, y: spot.y });
      if (spot.seat) steps.push({ t: "seat", seat: spot.seat }, { t: "turn", facing: 1 });
      if (facing) steps.push({ t: "turn", facing });
      scene.run(actor, steps, {});
      actor.data.idleWalk = Boolean(task && task.idle);
    }
    ch.bubble = bubbleFor(ch);
    return;
  }
  if (!actor.script) {
    if (facing) actor.facing = facing;
    scene.play(actor, pose);
    actor.hold = goal?.hold ?? null;
  }
  if (goal && goal.icon) {
    const kind = goal.icon as HeadIconKind;
    const text = goal.iconText || (kind === "text" ? goal.label : undefined) || undefined;
    if (!actor.icon || actor.icon.kind !== kind || actor.icon.text !== text) {
      actor.icon = { kind, text, t0: scene.realT, fromTask: true };
    }
  } else if (actor.icon && actor.icon.fromTask) {
    actor.icon = null;
  }
  if (task) {
    // 任务从到达位置开始计时：走路的时间不算在动作里
    if (task._t0 === null) {
      task._t0 = scene.realT;
      scene.setCharacterState(ch, "working");
      if (task.start && !task._started) {
        task._started = true;
        task.start(task);
      }
    }
    if (scene.realT - task._t0 >= task.ms) {
      ch.current = null;
      scene.setCharacterState(ch, "choosing");
      task.onDone?.(task);
      task.done?.(task);
    }
  }
  // 待机（持续状态是喝茶）时隔几秒自己挑一件事做
  if (!task && !ch.queue.length && goal && goal.pose === "tea" && spot.seat && scene.autonomy && !scene.frozen && !scene.reduced) {
    if (ch.idleAt === null) {
      ch.idleAt = scene.realT + (5000 + scene.random() * 7000) * (1 + 0.15 * (charsOf(world, ch.department!).length - 1));
    } else if (scene.realT >= ch.idleAt) {
      ch.idleAt = null;
      startIdle(world, ch, scene);
    }
  }
  ch.bubble = bubbleFor(ch);
}

// ---------------------------------------------------------------------------
// 包裹：沿管道的折线移动，到达终点后销毁并执行回调

/** 生成一个包裹；画面在生成时写上画法字段（bmp、color、small）。 */
export function spawnPackage(world: World, id: string, workItemId: string | null, colorIndex: number | null, artifact: string | null, roomId: string | null): void {
  world.packages[id] = {
    kind: "package", id, workItemId, colorIndex, artifact,
    atRest: { roomId: roomId ?? null, spotKind: "port_in" }, transit: null,
  };
}

let packageSeq = 0;

/** 包裹的编号：同一进程内不重复。 */
export function nextPackageId(): string {
  packageSeq += 1;
  return `pk-${packageSeq}`;
}

export function removePackage(world: World, id: string): void {
  delete world.packages[id];
}

export function sendPackage(world: World, scene: SceneLike, id: string, linkKey: string | null, pts: [number, number][], ms?: number, onDone?: (pk: World["packages"][string]) => void): void {
  const pk = world.packages[id];
  if (!pk) return;
  pk.atRest = null;
  const duration = (ms ?? Math.max(700, polyLength(pts) * 9)) / 1000;
  pk.transit = { linkKey, pts, t0: null, k: 0, ms: duration * 1000, pos: pts[0], onDone: onDone ?? null };
  // 包裹沿管道折线移动：由 GSAP 的补间推进一步，位置只由共用时钟决定
  const transit = pk.transit;
  if (scene?.hasTween) {
    const proxy = { k: 0 };
    transit.tweenKill = () => proxy.k;
    transit.tweenStart = (s) => {
      s.tween(proxy, { k: 1, duration, ease: "none", onUpdate: () => { transit.k = proxy.k; } });
    };
  }
}

export function stepPackages(world: World, scene: SceneLike): void {
  for (const pk of Object.values(world.packages)) {
    if (!pk.transit) continue;
    if (pk.transit.t0 === null) {
      pk.transit.t0 = scene.realT;
      pk.transit.tweenStart?.(scene);
    }
    const k = pk.transit.tweenKill ? pk.transit.k : Math.min(1, (scene.realT - pk.transit.t0) / pk.transit.ms);
    pk.transit.k = k;
    pk.transit.pos = pointAt(pk.transit.pts, polyLength(pk.transit.pts) * scene.easeInOut(k));
    if (k >= 1) {
      const done = pk.transit.onDone;
      pk.transit = null;
      pk.atRest = { roomId: null, spotKind: "port_out" };
      done?.(pk);
    }
  }
}

/** 当前画面坐标：正在移动时取沿线插值的点，静止时返回空（调用方按 atRest 决定画在哪里）。 */
export function packagePosition(pk: World["packages"][string]): [number, number] | null {
  return pk.transit ? (pk.transit.pos ?? null) : null;
}

/** 这条管道上有没有正在移动的包裹。 */
export function linkActive(world: World, linkKey: string): boolean {
  return Object.values(world.packages).some((pk) => pk.transit && pk.transit.linkKey === linkKey);
}

// ---------------------------------------------------------------------------
// 管道的流动：流速带着惯性跟随状态，光点按累计的相位向前移动

export function stepPipes(world: World, scene: SceneLike, stateOf: (pipe: World["links"][string]) => "flowing" | "idle" | "stopped"): void {
  const now = scene.realT;
  for (const p of Object.values(world.links)) {
    const f = p.flow ?? (p.flow = { state: "idle", speed: 0, load: 0, phase: 0, t: now });
    const dt = Math.max(0, Math.min(200, now - f.t));
    f.t = now;
    f.state = stateOf(p);
    if (!scene.autonomy) {
      f.speed = f.state === "flowing" ? 1 : 0;
      f.load = f.speed;
      scene.setPipeState(p, f.state);
      continue;
    }
    const goal = f.state === "flowing" ? 1 : 0;
    f.speed += (goal - f.speed) * Math.min(1, dt / (f.state === "stopped" ? 120 : 350));
    if (Math.abs(goal - f.speed) < 0.01) f.speed = goal;
    if (f.state === "flowing") f.load = Math.min(1, f.load + dt / 500);
    else if (f.state === "idle") f.load = Math.max(0, f.load - dt / 1600);
    f.phase += f.speed * dt;
    scene.setPipeState(p, f.state);
  }
}

export { syncCharacters, layoutSeats, charsOf, charFor, primaryOf, actorOf } from "./scene.ts";
