// 角色、包裹与管道的推进，任务派发与队列规则（原型 v13 ecs.js 第 3.3 至 3.6 节与 design.md 第 5 节，
// 工单 #82、#953）。世界与系统不依赖渲染：角色空着时取队首、走到 spot、做 ms 毫秒的 pose；
// 画面的动作按 kind 找到做它的角色；包裹沿管道的折线移动；管道带着惯性流动。每个角色与每根管道各有一个状态机。
//
// 排队与丢弃不在这里：演什么、什么时候演、丢什么由播放时间线决定（pixel/timeline.ts）。
// 一个角色的队列里只有时间线交给它的那几个动作的步骤；一个动作被立刻结束（跳到最新、普通动作到了上限）时，
// 由 dropAction 把这些步骤与它沿管道走的包裹一起清掉。

import { roomOf } from "./declare.ts";
import { actorOf, charsOf, charFor } from "./scene.ts";
import { polyLength, pointAt } from "./declare.ts";
import type { PixelAction } from "../contract.ts";
import type { Character, HeadIconKind, IdleDef, RestState, Seat, SpotKind, Step, Task, TaskDef, World } from "./types.ts";
import type { SceneLike } from "./types.ts";

const GEO = {
  TOP: 50, ROOM_B: 214, FLOOR_LINE: 150, DESK_Y: 196, PORT_STAND: 176, PIPE_Y: 138, TUBE_Y: 104,
  DUCT_Y: 30, DUCT_TUBE_Y: 42, UNDER_Y: 276, GAP: 6,
};

/** 放进队列时的附加字段：roleId 指定做这件事的角色（按角色 id 或角色种类取）。 */
export interface EnqueueExtra extends Partial<Task> {
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
  ch.queue.push(task);
  return task;
}

/**
 * 一个由角色做的动作（画面合同的动作，kind 是任务目录里的键）：找到做它的角色，放进它的队列。
 * 返回放进去的任务；找不到角色时为 null（调用方据此把动作立刻演完）。
 * make 为任务装上动作相关的字段（效果回调、气泡文字、actionId……）；side 为 'to' 表示这个任务是动作里
 * 收东西的一方做的（任务的 then 后续步骤）。
 */
export function dispatch(
  world: World,
  action: PixelAction,
  make?: (def: TaskDef, action: PixelAction, character: Character, side?: "to" | "from") => Partial<Task> | null,
): Task | null {
  if (!action || !action.kind) throw new Error("dispatch 需要画面合同的动作");
  const def = world.catalog.tasks[action.kind];
  if (!def) throw new Error("任务目录里没有这种动作：" + action.kind);
  // 任务声明了 dept 就由那个部门做，否则是动作所在的房间
  const department = def.dept ?? asText(action.room) ?? null;
  if (!department) return null;
  const ch = charFor(world, department, def.actor ? null : asText(action.role), def.actor ?? def.by ?? null);
  if (!ch) return null;
  const extra: Partial<Task> = { workItemId: asText(action.item) ?? null };
  if (action.count !== undefined && action.count !== null) extra.iconText = String(action.count);
  if (def.spot === "peer") {
    // 走向另一个角色的任务：对象是动作指定的角色，或者部门里某种角色
    const toward = def.toward === "role" ? charFor(world, department, asText(action.role), null) : charFor(world, department, null, def.toward ?? null);
    if (!toward || toward === ch) return null;
    extra.withId = toward.id;
    if (def.then) {
      extra.onDone = () => {
        enqueue(world, toward.id, def.then!, make ? make(world.catalog.tasks[def.then!], action, toward, "to") : null);
      };
    }
  }
  if (make) Object.assign(extra, make(def, action, ch));
  return enqueue(world, ch.id, action.kind, extra);
}

/** 动作的字段可能来自画面合同的额外字段（`[key: string]: unknown`），取值时先收窄。 */
export function asText(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

/**
 * 时间线立刻结束一个动作（跳到最新、普通动作到了上限、整层的动作被丢掉）：
 * 它在各个角色队列里的步骤与沿管道走的包裹立刻去掉，不再执行做完以后的效果。
 * 关键动作不走这里，它们限时演完（pixel/timeline.ts 的 rate()）。
 */
export function dropAction(world: World, actionId: number): void {
  for (const ch of Object.values(world.characters)) {
    if (ch.current && ch.current.actionId === actionId) ch.current = null;
    ch.queue = ch.queue.filter((t) => t.actionId !== actionId);
  }
  for (const id of Object.keys(world.packages)) {
    if (world.packages[id].actionId === actionId) delete world.packages[id];
  }
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

/** 一句话在头顶停留的毫秒数：读得完一句话，最长 4.6 秒（原型 v10 say.js 的时长，工单 #82）。 */
export function sayMs(text: string): number {
  return Math.min(4600, 1800 + String(text).length * 170);
}

/** 当前应显示的气泡：说话气泡是正在做（或正在保持的进度姿势）的那一项，思考气泡是队列里的下一项（只读）。 */
export function bubbleFor(ch: Character, scene?: SceneLike): Character["bubble"] {
  const cur = ch.current ?? (scene ? progressOf(ch, scene) : ch.progress);
  if (cur && cur.bubble === "say" && cur.label) return { text: cur.label, kind: "say", tail: Boolean(cur.streamed) };
  const next = ch.queue[0];
  if (next && next.bubble === "say" && next.label) return { text: next.label, kind: "think" };
  return null;
}

/** 还在保持的进度姿势（原型 v13 ecs.js 的 progressOf）：进度动作不排队，到达就换上，until 过后不再保持。 */
export function progressOf(ch: Character, scene: SceneLike): Task | null {
  return ch.progress && (ch.progress.until ?? 0) > scene.realT ? ch.progress : null;
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
  // 没有任务在做时，持续姿势可以由进度动作（整理资料、思考）暂时取代（原型 v13 ecs.js 的 goal）
  const goal: Task | RestState | null = task ?? progressOf(ch, scene) ?? ch.rest;
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
    ch.bubble = bubbleFor(ch, scene);
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
  ch.bubble = bubbleFor(ch, scene);
}

// ---------------------------------------------------------------------------
// 包裹：沿管道的折线移动，到达终点后销毁并执行回调

/** 生成一个包裹；画面在生成时写上画法字段（bmp、color、small、actionId）。 */
export function spawnPackage(world: World, id: string, workItemId: string | null, colorIndex: number | null, artifact: string | null, roomId: string | null): World["packages"][string] {
  world.packages[id] = {
    kind: "package", id, workItemId, colorIndex, artifact,
    atRest: { roomId: roomId ?? null, spotKind: "port_in" }, transit: null,
  };
  return world.packages[id];
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
  // pos 留空：第一个位置在第一次推进时算出（与原型一致，发送的当帧还没有位置）
  pk.transit = { linkKey, pts, t0: null, k: 0, ms: duration * 1000, onDone: onDone ?? null };
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
    const k = Math.min(1, (scene.realT - pk.transit.t0) / pk.transit.ms);
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
