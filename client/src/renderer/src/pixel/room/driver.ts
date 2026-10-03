// 部门房间的驱动：按快照配置角色与持续状态，把事件变成动作放进角色的队列（原型 v9 room.js 的
// setModel、playEvent、restFor、applyLights 与 handlers，工单 #177）。
//
// 驱动持有一个场景（world/scene.ts 的 createScene），小人的走位与动作由场景的脚本按帧推进；
// 渲染层只读驱动的房间数据与场景里 actor 的状态。这里不依赖渲染与 PixiJS，可以直接在 node --test 下驱动。

import { createScene } from "../world/scene.ts";
import { say as sayCatalog, sayMs } from "../world/say.ts";
import { PAL } from "../registry.ts";
import { hash } from "../anims.ts";
import { headTop } from "../shapes.ts";
import type { Actor, PixelFloorEvent, SceneLike, SceneOptions, Step } from "../world/types.ts";
import { handoffOf, layoutDesks, levelAtLeast, poseAnim, resolveAction, rolesOf, spriteForRole, toolSpot } from "./decl.ts";
import { L, ROW_A, ROW_B, S, SPOT } from "./layout.ts";
import type { RoomRole, RoomSeat } from "./layout.ts";
import { createRoomState, emptyRoomModel, letterSides, quoted, type DeskState, type RoomModel, type RoomState } from "./room.ts";

const PROP_KEEP = 7000;
const BENCH_KEEP = 12000;

/** 桌上保留时间的字段：值是从保留到期的时刻（其余字段不是时间）。 */
type DeskNumberKey = "folder" | "doc" | "box" | "card" | "cardResult" | "scroll" | "letter";

/** 房间里的一个角色：角色的持续与动作状态（渲染只读）。 */
export interface RoomActor {
  id: string;
  role: RoomRole;
  desk: RoomSeat;
  doing: string | null;
  persist: { anim: string; icon?: { kind: string; text?: string } | null; hold?: string | null; write?: boolean; until?: number } | null;
  say: { text: string; until: number } | null;
  /** 排队的动作：`from` 是产生它的真实事件类型，事项进入停止态时据此决定保留或清除。 */
  queue: { fn: () => void; at: number; from: string }[];
  formSign: string | null;
  /** 流式输出的累计文字：第一段取代默认的标签，后续片段接在后面。 */
  streamText: string | null;
  nextStretch: number;
  nextPause: number;
}

/** 持续状态：与任务相同形状（原型 room.js 的 restFor 返回值）。 */
interface RestSpec {
  x: number;
  y: number;
  seat: RoomSeat | null;
  anim: string;
  facing?: number;
  icon?: { kind: string; text?: string } | null;
  hold?: string | null;
  sign?: string | null;
  away?: boolean;
}

/** 房间驱动：世界（角色与场景）与画面状态都在这里维护。 */
export interface RoomDriver {
  model: RoomModel;
  state: RoomState;
  scene: SceneLike;
  actors(): RoomActor[];
  primary(): RoomActor | null;
  actorById(id: string): RoomActor | null;
  setModel(model: RoomModel): void;
  playEvent(ev: PixelFloorEvent): void;
  setStreamText(text: string): void;
  step(): void;
}

/** 走位与动作的脚本构造器（原型 room.js 的 plan）。 */
interface Plan {
  steps: Step[];
  x: number;
  y: number;
  seated: boolean;
  tailAt?: number;
}

function makePlan(scene: SceneLike, a: RoomActor, actor: Actor, blocks: Block[]): PlanApi {
  const p: PlanApi = {
    steps: [], x: actor.x, y: actor.y, seated: !!actor.seat,
    stand() {
      if (this.seated) { this.steps.push(S.seat(null), S.anim("idle", 180)); this.seated = false; }
      return this;
    },
    to(x, y, gait, speed) {
      this.stand();
      const pts: [number, number][] = [];
      const behindDesk = ROW_B - 14;
      if (this.y >= ROW_B - 2 && Math.abs(this.y - y) > 2) pts.push([this.x, behindDesk]);
      const viaDesk = y >= ROW_B - 2 && Math.abs(this.y - y) > 2;
      const goal: [number, number] = viaDesk ? [x, behindDesk] : [x, y];
      const from = (pts.length ? pts[pts.length - 1] : [this.x, this.y]) as [number, number];
      if (blocked(blocks, from, goal)) {
        const vias = blocks.flatMap((b) => [
          [b.x0 - 8, b.y0 - 10], [b.x1 + 8, b.y0 - 10], [b.x0 - 8, b.y1 + 6], [b.x1 + 8, b.y1 + 6],
        ] as [number, number][]);
        const via = vias
          .filter((v) => !blocked(blocks, from, v) && !blocked(blocks, v, goal))
          .sort((m, n) => (Math.hypot(m[0] - from[0], m[1] - from[1]) + Math.hypot(goal[0] - m[0], goal[1] - m[1]))
            - (Math.hypot(n[0] - from[0], n[1] - from[1]) + Math.hypot(goal[0] - n[0], goal[1] - n[1])))[0];
        if (via) pts.push(via);
        else pts.push([from[0], 140], [goal[0], 140]);
      }
      pts.push(goal);
      if (goal[1] !== y || goal[0] !== x) pts.push([x, y]);
      let cx = this.x;
      let cy = this.y;
      for (const [px, py] of pts) {
        if (Math.hypot(px - cx, py - cy) > 0.5) this.steps.push(S.go(px, py, gait, speed));
        cx = px;
        cy = py;
      }
      this.x = x;
      this.y = y;
      return this;
    },
    spot(name, gait) {
      const s = SPOT[name] as [number, number, number?];
      this.to(s[0], s[1], gait);
      if (s[2]) this.steps.push(S.turn(s[2]));
      return this;
    },
    sit(gait) {
      if (!this.seated) {
        const d = a.desk;
        this.to(d.seatX, d.seatY, gait);
        this.steps.push(S.seat(d), S.turn(1));
        this.seated = true;
      }
      return this;
    },
    add(...list) { this.steps.push(...list); return this; },
    mark() { this.tailAt = this.steps.length; return this; },
    back(gait) { this.mark(); return this.sit(gait); },
    run(finalize, tail) {
      const t = tail !== undefined ? tail : this.tailAt;
      scene.run(actor, this.steps, { tail: t, finalize: () => { finalize?.(); actor.icon = null; } });
      return this;
    },
  };
  return p;
}

interface PlanApi extends Plan {
  stand(): PlanApi;
  to(x: number, y: number, gait?: string, speed?: number): PlanApi;
  spot(name: string, gait?: string): PlanApi;
  sit(gait?: string): PlanApi;
  add(...list: Step[]): PlanApi;
  mark(): PlanApi;
  back(gait?: string): PlanApi;
  run(finalize?: () => void, tail?: number): PlanApi;
}

interface Block {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

function blocked(blocks: Block[], p0: [number, number], p1: [number, number]): boolean {
  const n = Math.max(1, Math.ceil(Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / 3));
  for (let i = 1; i < n; i++) {
    const x = p0[0] + ((p1[0] - p0[0]) * i) / n;
    const y = p0[1] + ((p1[1] - p0[1]) * i) / n;
    if (blocks.some((b) => x > b.x0 && x < b.x1 && y > b.y0 && y < b.y1)) return true;
  }
  return false;
}

/** 交接的物件到画法位图（原型 room.js 的 ART_BMP）。 */
const ART_BMP: Record<string, string | false> = { prd: "scroll", box: "box_sealed", defect: "box_rework", release: "box_release", letter: "letter" };
/** 提案被接纳或退回后托盘清空（原型 PROPOSAL_DONE）。 */
const PROPOSAL_DONE = new Set(["spec_accepted", "contract_accepted", "plan_accepted", "delivery_accepted", "qa_submitted", "proposal_rejected"]);
/** 只改变房间物件的事件：不影响小人正在做和排队的动作（原型 SIDE_ONLY）。 */
const SIDE_ONLY = new Set(["guidance_in", "semantic", "freeze"]);
/** 由动作自己让两端说话的（原型 OWN_SPEECH）。 */
const OWN_SPEECH = new Set(["hand_back"]);
/** 打字思考类动作：头顶已有思考气泡，不再重复说话（原型 THINK_ACTIONS）。 */
const THINK_ACTIONS = new Set(["type_think", "stream_text"]);
/** 状态类动作立即执行（原型 IMMEDIATE）。 */
const IMMEDIATE = new Set(["paused", "failed", "done", "cancelled", "puzzled", "hold_card", "resume"]);
/** 事项进入停止态时保留的排队动作：传信与交接的说话与送信不因事项很快结束而丢失。
 *  真实系统的 FakeAdapter 让一个事项在 1 秒左右跑到 done，传信事件排队后不到 900 毫秒就被清除，
 *  两端因此从不说话；这些动作已经由事件排入，继续执行到结束。 */
const KEEP_ON_STOP: Record<string, true> = { collaboration_requested: true, collaboration_responded: true, transition: true };

/** 建立部门房间的驱动。 */
export function createRoomDriver(opts: { department: string; sceneOptions: SceneOptions }): RoomDriver {
  const dept = opts.department;
  const scene = createScene(opts.sceneOptions);
  const state = createRoomState();
  const actors = new Map<string, RoomActor>();
  const blocks: Block[] = dept === "operations" ? [] : [{ x0: L.bench.x - 4, x1: L.bench.x + L.bench.w + 4, y0: ROW_A + 1, y1: ROW_A + 16 }];
  let model = emptyRoomModel(dept);

  function actorOf(id: string): Actor | null {
    return scene.actors.find((x) => x.id === `ch-${id}`) ?? null;
  }
  function roleActors(): RoomActor[] {
    return [...actors.values()];
  }
  function primary(): RoomActor | null {
    const centerKind = dept === "quality" ? "tester" : dept === "operations" ? "ops" : "architect";
    return roleActors().find((a) => a.role.kind === centerKind)
      ?? roleActors().find((a) => a.role.kind === "manager") ?? roleActors()[0] ?? null;
  }
  function actorById(id: string): RoomActor | null {
    return actors.get(id) ?? null;
  }
  function byKind(kind: string): RoomActor | null {
    return roleActors().find((a) => a.role.kind === kind) ?? null;
  }
  function actorFor(ev: PixelFloorEvent): RoomActor | null {
    const list = roleActors();
    if (ev.role) {
      const hit = list.find((a) => a.id === ev.role || a.role.kind === ev.role || a.role.name === ev.role);
      if (hit) return hit;
    }
    return primary();
  }
  function ds(a: RoomActor): DeskState {
    return state.deskState[a.id];
  }
  function shown(a: RoomActor, key: DeskNumberKey): boolean {
    return ds(a)[key] > scene.realT;
  }
  function keep(a: RoomActor, key: DeskNumberKey): void {
    ds(a)[key] = scene.realT + PROP_KEEP;
  }
  function drop(a: RoomActor, key: DeskNumberKey): void {
    ds(a)[key] = 0;
  }
  function nameOfRole(k: string | null | undefined): string | null {
    const hit = roleActors().find((r) => r.id === k || r.role.kind === k || r.role.name === k);
    return hit ? hit.role.name : null;
  }
  function say(ev: PixelFloorEvent, a: RoomActor | null, side?: "to" | "from"): void {
    if (!a) return;
    const text = sayCatalog(ev, { dept, side, roleName: nameOfRole });
    if (text) a.say = { text, until: scene.realT + sayMs(text) };
  }
  function plan(a: RoomActor): PlanApi {
    return makePlan(scene, a, actorOf(a.id)!, blocks);
  }
  function effStatus(): string {
    return state.eventStatus || model.status || "idle";
  }
  function isOps(): boolean {
    return dept === "operations";
  }
  function waitingProvider(): boolean {
    return Boolean(model.waiting_provider || state.eventWaiting);
  }
  function remoteUnknown(): boolean {
    return Boolean(model.remote_unknown || state.eventRemote);
  }
  function applyLights(): void {
    const s = effStatus();
    const target = s === "interrupted" ? 0.74 : waitingProvider() ? 0.42
      : (s === "working" || s === "asking" || s === "pending_verification" || s === "done") ? 0 : 0.36;
    state.darkTarget = target;
    state.dark = target;
    state.yellow = s === "pending_verification";
    scene.frozen = s === "interrupted";
  }
  function syncRoles(): void {
    const list = rolesOf(model).map((r) => ({ ...r, name: r.name || r.id }));
    const keepIds = new Set(list.map((r) => r.id));
    for (const [id] of actors) {
      if (!keepIds.has(id)) {
        const a = actorOf(id);
        if (a) scene.removeActor(a);
        actors.delete(id);
      }
    }
    const lay = layoutDesks(dept, list, model.level ?? "ui");
    state.desks = list.map((r, i) => ({
      x: lay[i].x, w: lay[i].w, seatX: lay[i].x + 18, seatY: ROW_B, roleId: r.id, role: r,
    }));
    list.forEach((r, i) => {
      const d = state.desks[i];
      let actor = actorOf(r.id);
      const sprite = spriteForRole(dept, r.kind);
      if (!actor) {
        actor = scene.addActor({ id: `ch-${r.id}`, sprite, x: d.seatX, y: d.seatY, anim: "sit", data: { room: true } });
        actor.seat = d;
      } else if (actor.seat) {
        // 重新排布以后工位是新对象：原来坐在工位上的角色改指新的工位
        actor.seat = d;
      }
      actor.sprite = sprite;
      const existing = actors.get(r.id);
      if (existing) {
        existing.role = r;
        existing.desk = d;
      } else {
        actors.set(r.id, { id: r.id, role: r, desk: d, doing: null, persist: null, say: null, queue: [], formSign: null, streamText: null, nextStretch: 0, nextPause: 0 });
      }
      if (!state.deskState[r.id]) {
        state.deskState[r.id] = {
          papers: 3 + (i % 3), hidePapers: false, folder: 0, doc: 0, box: 0, card: 0, cardResult: 0,
          scroll: 0, letter: 0, redLamp: false,
        };
      }
    });
    const prim = primary();
    state.bin = { x: state.desks[0].x + state.desks[0].w + 2, y: ROW_B + 9 };
    if (prim) state.bin.x = prim.desk.x + prim.desk.w + 2;
    // 质检的试用台座位（3.2D）：档位达到且房间有试用数据时，测试工程师坐在试用台前
    state.trialSeat = dept === "quality" && levelAtLeast(model.level, "3.2D")
      ? { x: SPOT.trial[0], w: 30, seatX: SPOT.trial[0], seatY: SPOT.trial[1], roleId: "", role: prim?.role ?? list[0], trial: true }
      : null;
  }
  // 排队与临时状态的清空只在真正停下来的时候发生（暂停、失败、完成、取消）：真实系统的查询状态
  // 在动作进行中会在「工作」与「待核实」之间来回变化，按每一次变化清空会把已经排队的动作丢掉，
  // 画面就停在第一次动作上。原型 setModel 在任何非工作状态都清空，这里保留原型的意图，只把
  // 进行中的临时事实（待核实、待恢复、空闲）排除在外。
  const STOPPED_STATES = new Set(["paused", "failed", "done", "cancelled"]);
  function setModel(m: RoomModel): void {
    if (!m) throw new Error("setModel 需要 roomModel");
    if (m.department && m.department !== dept) throw new Error(`roomModel 的部门与画面不一致：${m.department}`);
    const prev = effStatus();
    model = { ...m };
    state.eventStatus = null;
    state.eventCard = null;
    state.eventTool = null;
    state.eventRemote = false;
    state.eventMachine = null;
    state.eventWaiting = false;
    state.eventStep = 0;
    state.eventLines = null;
    if (m.pending_tool) state.lastPendingTool = m.pending_tool;
    state.wbTags = {};
    state.wbDone = {};
    syncRoles();
    const s = effStatus();
    if (s !== prev && STOPPED_STATES.has(s)) {
      for (const a of roleActors()) {
        if (s === "interrupted" || a.role.status === "away") continue;
        a.persist = null;
        // 持续状态与走位清除；已经排入的传信与交接动作继续执行到结束
        a.queue = a.queue.filter((q) => KEEP_ON_STOP[q.from]);
      }
      if (s !== "failed") for (const a of roleActors()) { if (!a.persist) ds(a).redLamp = false; }
    }
    applyLights();
  }
  function restFor(a: RoomActor): RestSpec | null {
    const s = effStatus();
    const d = a.desk;
    const r = a.role;
    const isPrim = a === primary();
    const seatRest = (anim: string, extra?: Partial<RestSpec>): RestSpec => ({ x: d.seatX, y: d.seatY, seat: d, anim, facing: 1, ...(extra ?? {}) });
    const standRest = (x: number, y: number, anim: string, extra?: Partial<RestSpec>): RestSpec => ({ x, y, seat: null, anim, ...(extra ?? {}) });
    if (s === "pending_verification" && isPrim) {
      const spot = toolSpot(state.eventTool || model.pending_tool);
      if (spot === "desk") return seatRest("sit_scratch", { icon: { kind: "question" } });
      const sp = SPOT[spot] as [number, number, number];
      return standRest(sp[0], sp[1], "puzzled", { icon: { kind: "question" }, facing: sp[2] || 1 });
    }
    if (s === "waiting_resume" && isPrim) {
      return standRest(SPOT.center[0], SPOT.center[1], "hold_sign", { sign: model.hold_card || state.eventCard || "待恢复" });
    }
    if (s === "asking" && isPrim) return standRest(SPOT.door[0] - 14, SPOT.door[1] + 2, "wait", { facing: 1 });
    // 试用台：测试工程师坐在试用台前（3.2D）
    if (state.trialSeat && model.trial && r.kind === "tester") {
      return { x: state.trialSeat.seatX, y: state.trialSeat.seatY, seat: state.trialSeat, anim: "type", facing: 1 };
    }
    if (waitingProvider() && isPrim && (s === "working" || s === "idle")) return seatRest("sit_up");
    if (remoteUnknown() && isPrim) {
      return standRest(SPOT.terminal[0], SPOT.terminal[1], "watch_r", { icon: { kind: "question" }, facing: 1 });
    }
    if (s === "idle") return seatRest("tea");
    if (s === "paused") return seatRest("sit_relax", { icon: isPrim ? { kind: "zzz" } : null });
    if (s === "failed") return seatRest("slump");
    if (s === "done") return standRest(d.seatX, d.seatY, isPrim ? "cheer" : "idle_happy");
    if (s === "cancelled") return standRest(d.seatX, d.seatY, "idle");
    if (s === "interrupted") return null;
    if (a.persist && (!a.persist.until || scene.realT < a.persist.until)) {
      const ps = a.persist;
      return seatRest(ps.anim, { icon: ps.icon ?? null, hold: ps.hold ?? null });
    }
    if (r.status === "away") return { x: SPOT.doorIn[0], y: SPOT.doorIn[1], seat: null, anim: "idle", away: true };
    if (r.status === "idle") return seatRest("tea");
    if (r.status === "assigned") return seatRest("sit_card", { hold: "card_task" });
    if (r.status === "returned") return seatRest("sit_happy");
    if (r.status === "failed") return seatRest("slump");
    if (model.pose && (model.pose.role_id === a.id || (!model.pose.role_id && isPrim))) {
      const anim = poseAnim(model.pose.action);
      return seatRest(anim, { hold: anim === "read_sit" ? "doc" : null });
    }
    return seatRest("type");
  }
  function applyRest(a: RoomActor): void {
    const r = restFor(a);
    const actor = actorOf(a.id);
    if (!r || !actor) return;
    if (r.away) {
      actor.visible = false;
      actor.seat = null;
      actor.x = r.x;
      actor.y = r.y;
      return;
    }
    if (!actor.visible) {
      actor.visible = true;
      actor.alpha = 0;
      actor.x = SPOT.doorIn[0];
      actor.y = SPOT.doorIn[1];
      const p = plan(a);
      p.add(S.fade(1, 240));
      p.to(SPOT.door[0], SPOT.door[1]);
      p.run();
      return;
    }
    const atSpot = Math.hypot(actor.x - r.x, actor.y - r.y) < 1.5 && (r.seat ? actor.seat === r.seat : !actor.seat);
    if (!atSpot) {
      const p = plan(a);
      if (r.seat && r.seat !== a.desk) {
        p.to(r.x, r.y);
        p.steps.push(S.seat(r.seat), S.turn(r.facing ?? 1));
        p.seated = true;
      } else if (r.seat) {
        p.sit();
      } else {
        p.to(r.x, r.y);
      }
      if (r.facing) p.add(S.turn(r.facing));
      p.run();
      return;
    }
    if (r.facing) actor.facing = r.facing;
    actor.hold = r.hold ?? null;
    actor.sign = r.sign ?? null;
    actor.icon = r.icon ? { kind: r.icon.kind as never, text: r.icon.text, t0: scene.realT } : null;
    scene.play(actor, r.anim);
    if (r.anim === "tea") {
      if (!a.nextStretch) a.nextStretch = scene.realT + 5000 + hash(actor.seed) * 6000;
      if (scene.realT > a.nextStretch) {
        a.nextStretch = scene.realT + 9000 + scene.random() * 6000;
        scene.run(actor, [S.anim("stretch_sit"), S.anim("sit", 400)], { tail: 0 });
      }
    }
    if (r.anim === "type" && !r.icon) {
      if (!a.nextPause) a.nextPause = scene.realT + 4000 + hash(actor.seed + 5) * 5000;
      if (scene.realT > a.nextPause) {
        a.nextPause = scene.realT + 7000 + scene.random() * 6000;
        scene.run(actor, [S.anim(scene.random() < 0.5 ? "think" : "sit_up", 1300)], { tail: 0 });
      }
    }
    if (r.anim === "cheer" && scene.realT > state.confettiAt) {
      state.confettiAt = scene.realT + 2600;
      scene.emit("confetti", 240, 10, 40, { spread: 440 });
    }
  }
  function tickBench(): void {
    const b = state.bench;
    const sig = [b.item, b.mark && b.mark.text, b.slip, b.slipMark && b.slipMark.text, b.ticks, b.tape].join("|");
    if (sig !== b.sig) {
      b.sig = sig;
      b.until = scene.realT + BENCH_KEEP;
    }
    if ((b.item || b.slip) && b.until <= scene.realT) {
      Object.assign(b, { item: null, mark: null, slip: null, slipMark: null, ticks: 0, tape: 0 });
    }
  }
  function step(): void {
    if (effStatus() !== "interrupted") state.clock += scene.reduced ? 0 : 16.7;
    for (const a of roleActors()) {
      const q = a.queue;
      if (q.length && !scene.frozen) {
        const waited = scene.realT - q[0].at;
        const actor = actorOf(a.id);
        const inTail = actor ? scene.inTail(actor) : true;
        const justStarted = actor?.step?.st.key === true && scene.realT - actor.step.t0 < 600;
        if (inTail || (waited >= 900 && !justStarted)) {
          const next = q.shift()!;
          if (actor?.script) scene.cancel(actor);
          next.fn();
          continue;
        }
      }
      const actor = actorOf(a.id);
      if (actor && !actor.script) applyRest(a);
    }
    tickBench();
    // 与原型 room.js 的 update 一致：终端冒烟与茶水台蒸汽（同时保持随机数的消耗顺序一致）
    if (state.smokeUntil > scene.realT && !scene.reduced && scene.random() < 0.3) {
      scene.emit("smoke", L.terminal.x + 14, L.terminal.base - 38, 1);
    }
    if (!scene.frozen && scene.random() < 0.035) scene.emit("steam", 413, ROW_B - 15, 1);
    for (const a of roleActors()) {
      const actor = actorOf(a.id);
      if (actor && actor.anim === "tea" && actor.seat && !scene.frozen && scene.random() < 0.03) {
        const [hx, hy] = headTop(scene, actor);
        scene.emit("steam", hx + 2, hy + 12, 1);
      }
    }
  }

  // -------------------------------------------------------------------------
  // 事件的处理

  function giveSpot(d: RoomSeat): [number, number, number] {
    return d.x - 8 >= 10 ? [d.x - 8, ROW_B, 1] : [d.x + d.w + 8, ROW_B, -1];
  }

  function setPersist(a: RoomActor, ps: RoomActor["persist"]): void {
    a.persist = ps;
  }

  function stampSteps(item: string, hitFn: (i: number) => void, anim?: string): Step[] {
    const name = anim || "stamp_once";
    const hits = name === "stamp" ? [450 + 380, 380 + 70 + 450 + 300 + 70 + 450] : [400 + 70 + 10];
    return [
      S.hold(item),
      S.call(() => hits.forEach((ms, i) => scene.after(scene.reduced ? 0 : ms, () => hitFn(i)))),
      S.anim(name, undefined, true),
      S.hold(null),
    ];
  }

  function arrivalArt(a: RoomActor, art: string): void {
    if (art === "prd") keep(a, "scroll");
    else if (art === "box") {
      state.bench.item = "box_sealed";
      state.bench.mark = { text: "封存", color: PAL.blue2 };
      state.bench.slip = null;
      state.bench.slipMark = null;
      state.bench.ticks = 0;
    } else if (art === "defect") {
      if (isOps()) keep(a, "box");
      else {
        state.bench.item = "box_rework";
        state.bench.slip = "defect";
        state.bench.slipMark = { text: "返工", color: PAL.red2 };
      }
    } else if (art === "release") {
      if (isOps()) keep(a, "box");
      else {
        state.bench.item = "box_sealed";
        state.bench.slip = "release";
        state.bench.slipMark = null;
      }
    }
  }

  function transition(ev: PixelFloorEvent): void {
    const raw = (ev.payload ?? {}) as Record<string, unknown>;
    const handoff = handoffOf(raw);
    if (!handoff) return;
    const pl = { ...raw, from: handoff.from, to: handoff.to, artifact: handoff.artifact };
    const sayEv: PixelFloorEvent = { ...ev, payload: pl };
    const art = handoff.artifact;
    const bmp = ART_BMP[art];
    if (!bmp) return;
    const a = primary();
    if (!a) return;
    if (pl.from === dept) {
      say(sayEv, a, "from");
      const p = plan(a);
      p.stand();
      if (state.bench.item === bmp) p.add(S.call(() => { state.bench.item = null; state.bench.mark = null; }));
      else if (dept === "quality" && state.bench.slip) p.add(S.call(() => { state.bench.slip = null; state.bench.slipMark = null; state.bench.item = null; }));
      p.add(S.hold(bmp));
      p.spot("pipe", "carry");
      p.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
        a.doing = a.doing;
        const actor = actorOf(a.id);
        if (actor) actor.hold = null;
        scene.fly({ bmp, from: [p.x + 6, p.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8, onDone: undefined });
      })), S.anim("side_reach", 900, true));
      p.back();
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; });
    } else if (pl.to === dept) {
      const p = plan(a);
      p.spot("pipe");
      p.add(S.call(() => {
        say(sayEv, a, "to");
        scene.fly({ bmp, from: [L.pipe.x + 10, L.pipe.base - 8], to: [p.x + 6, p.y - 18], ms: 620, arc: 8, onDone: () => { const actor = actorOf(a.id); if (actor) actor.hold = bmp; } });
      }), S.anim("reach", 700, true), S.anim("catch", 900));
      if (isOps() || art === "prd") {
        p.sit("carry");
        p.add(S.call(() => arrivalArt(a, art)), S.hold(null), S.anim("sit_happy", 600));
      } else {
        p.spot("bench", "carry");
        p.add(S.anim("place", 700), S.hold(null), S.call(() => arrivalArt(a, art)));
      }
      p.back();
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; });
    }
  }

  /** 事件到动作的处理函数（原型 room.js 的 handlers）。 */
  const handlers: Record<string, (ev: PixelFloorEvent, a: RoomActor) => void> = {
    activate(_ev: PixelFloorEvent, a: RoomActor) {
      if ((model.status || "idle") === "idle") state.eventStatus = "working";
      applyLights();
      setPersist(a, null);
      state.crtBoot = 0;
      const p = plan(a);
      const actor = actorOf(a.id)!;
      p.add(S.anim(actor.seat ? "sit_up" : "look_up", 300));
      p.to(SPOT.crtLook[0], SPOT.crtLook[1]);
      p.add(S.anim("look_up", 1300, true), S.anim("idle_happy", 500));
      p.sit();
      p.add(S.anim("type", 500));
      p.run(() => { state.crtBoot = 1; });
    },
    fetch_folder(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.spot("cabinet");
      let placed = false;
      const place = (): void => { if (!placed) { placed = true; keep(a, "folder"); } };
      p.add(S.call(() => { state.drawer = 1; }), S.anim("rummage", 1100), S.anim("grab_folder", 700, true),
        S.call(() => { state.drawer = 0; }), S.hold("folder"));
      p.sit("carry");
      p.add(S.call(place), S.hold(null), S.anim("sit_happy", 600));
      p.run(() => { state.drawer = 0; const actor = actorOf(a.id); if (actor) actor.hold = null; place(); });
    },
    type_think(_ev: PixelFloorEvent, a: RoomActor) {
      a.streamText = null;
      setPersist(a, { anim: "type", icon: { kind: "think" } });
      ds(a).redLamp = false;
      const p = plan(a);
      p.sit();
      p.add(S.icon({ kind: "think" }), S.anim("type", 1200, true));
      p.run();
    },
    stream_text(ev, a) {
      const pl = (ev.payload ?? {}) as Record<string, unknown>;
      const chunk = String(pl.text ?? pl.delta ?? pl.chunk ?? quoted(ev.label) ?? "……");
      // 流式输出：文字接在正在做的模型请求上（第一段取代默认标签），保留最后一段
      a.streamText = ((a.streamText ?? "") + chunk).slice(-120);
      setPersist(a, { anim: "type", icon: { kind: "stream", text: a.streamText } });
      const p = plan(a);
      p.sit();
      p.add(S.icon({ kind: "stream", text: a.streamText }), S.anim("type", 1500, true));
      p.run();
    },
    idea(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, { anim: "sit_happy", icon: { kind: "bulb" }, until: scene.realT + 2600 });
      const p = plan(a);
      p.sit();
      p.add(S.icon({ kind: "bulb" }), S.call(() => {
        const actor = actorOf(a.id);
        if (actor) {
          const [hx, hy] = headTop(scene, actor);
          scene.emit("spark", hx, hy - 10, 12);
        }
      }), S.anim("sit_happy", 1600, true));
      p.run();
    },
    retry_wait(ev, a) {
      const pl = (ev.payload ?? {}) as Record<string, unknown>;
      const n = pl.n || pl.attempt || pl.attempt_no || 2;
      const of = pl.of || pl.max || pl.max_attempts || 3;
      const text = `第 ${n}/${of} 次`;
      setPersist(a, { anim: "sit_wait", icon: { kind: "hourglass", text } });
      const p = plan(a);
      p.sit();
      p.add(S.icon({ kind: "hourglass", text }), S.anim("sit_wait", 1600, true));
      p.run();
    },
    slump(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, { anim: "slump" });
      ds(a).redLamp = true;
      const p = plan(a);
      p.sit();
      p.add(S.anim("shock", 300), S.anim("slump", 1600, true));
      p.run();
    },
    search(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.spot("cabinet");
      p.add(S.call(() => { state.drawer = 1; }), S.anim("rummage", 1300), S.anim("magnify", 1600, true),
        S.call(() => { state.drawer = 0; }));
      p.back();
      p.run(() => { state.drawer = 0; });
    },
    read(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, { anim: "read_sit", hold: "doc" });
      const p = plan(a);
      p.sit();
      p.add(S.hold("doc"), S.anim("read_sit", 1800, true));
      p.run();
    },
    write(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, { anim: "write", write: true });
      const p = plan(a);
      p.sit();
      p.add(S.call(() => keep(a, "doc")), S.anim("write", 1800, true));
      p.run();
    },
    run_command(ev, a) {
      if (ev.type === "tool_called") { commandDone(ev, a); return; }
      setPersist(a, null);
      state.exit = null;
      const p = plan(a);
      p.spot("terminal");
      p.add(S.call(() => scene.after(scene.reduced ? 0 : 450, () => {
        state.lever = 1;
        state.termRun = true;
      })), S.anim("lever", 1000, true));
      p.mark();
      p.add(S.anim("watch_r", 14000));
      p.run();
    },
    submit(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      let placed = false;
      const place = (): void => { if (!placed) { placed = true; state.trayPaper = true; const actor = actorOf(a.id); if (actor) actor.hold = null; } };
      const p = plan(a);
      p.stand();
      p.add(S.hold("doc"), S.call(() => drop(a, "doc")));
      p.spot("tray", "carry");
      p.add(S.call(() => scene.after(scene.reduced ? 0 : 450, place)), S.anim("side_place", 700, true), S.anim("side", 300));
      p.back();
      p.run(place);
    },
    returned(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const d = a.desk;
      state.trayPaper = false;
      scene.fly({ bmp: "doc", from: [L.tray.x + 13, L.tray.base - 24], to: [d.x + d.w / 2 - 8, ROW_B - 6], ms: 800, arc: 26, onDone: () => keep(a, "doc") });
      const p = plan(a);
      p.sit();
      p.add(S.anim("sit_up", 700), S.icon({ kind: "question" }), S.anim("sit_scratch", 1800, true), S.icon(null));
      p.run(() => keep(a, "doc"));
    },
    stamp_valid(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      let shelved = false;
      const shelve = (): void => { if (!shelved) { shelved = true; state.scrollHide = 0; state.scrollFlash = scene.realT + 1500; state.bench.item = null; state.bench.mark = null; } };
      const p = plan(a);
      p.add(S.call(() => { state.bench.item = "scroll_open"; state.bench.mark = null; }));
      p.spot("bench");
      p.add(...stampSteps("stamp_valid", () => { state.bench.mark = { text: "有效", color: "#d4353f" }; }, "stamp"));
      p.add(S.anim("idle_happy", 400), S.call(() => { state.bench.item = null; state.bench.mark = null; }), S.hold("scroll"));
      p.spot("pipe", "carry");
      p.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
        const actor = actorOf(a.id);
        if (actor) actor.hold = null;
        scene.fly({ bmp: "scroll", from: [p.x + 6, p.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8, onDone: shelve });
      })), S.anim("side_reach", 900, true));
      p.back();
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; shelve(); });
    },
    pin_plan(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.stand();
      p.add(S.hold("doc"));
      p.spot("wb", "carry");
      p.add(S.anim("board_pin", undefined, true), S.call(() => { state.wbSheetUntil = scene.realT + PROP_KEEP; }), S.hold(null), S.anim("back", 500), S.anim("idle_happy", 400));
      p.back();
      p.run(() => { if (state.wbSheetUntil < scene.realT) state.wbSheetUntil = scene.realT + PROP_KEEP; const actor = actorOf(a.id); if (actor) actor.hold = null; });
    },
    seal(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.add(S.call(() => { state.bench.item = "box_open"; state.bench.mark = null; state.bench.tape = 0; }));
      p.stand();
      p.add(S.hold("docs"));
      p.spot("bench", "carry");
      p.add(S.anim("place", 700), S.hold(null), S.call(() => { state.bench.item = "box"; }),
        S.call(() => { state.bench.tape = 1; }), S.anim("tidy", 800),
        S.call(() => { state.bench.item = "box_sealed"; }));
      p.add(...stampSteps("stamp_seal", () => { state.bench.mark = { text: "封存", color: PAL.blue2 }; }));
      p.add(S.anim("idle_happy", 500));
      p.back();
      p.run(() => {
        if (state.bench.item === "box" || state.bench.item === "box_open") state.bench.item = "box_sealed";
        if (state.bench.item === "box_sealed" && !state.bench.mark) state.bench.mark = { text: "封存", color: PAL.blue2 };
        state.bench.tape = 1;
        const actor = actorOf(a.id);
        if (actor) actor.hold = null;
      });
      scene.after(scene.reduced ? 1700 : 4600, () => {
        if (state.bench.item !== "box_sealed") return;
        const pa = primary();
        if (!pa) return;
        const p2 = plan(pa);
        p2.stand();
        p2.spot("bench");
        p2.add(S.call(() => { state.bench.item = null; state.bench.mark = null; }), S.hold("box_sealed"));
        p2.spot("pipe", "carry");
        p2.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
          const actor = actorOf(pa.id);
          if (actor) actor.hold = null;
          scene.fly({ bmp: "box_sealed", from: [p2.x + 6, p2.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8 });
        })), S.anim("side_reach", 900, true));
        p2.back();
        p2.run(() => { const actor = actorOf(pa.id); if (actor) actor.hold = null; });
      });
    },
    inspect(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.add(S.call(() => { if (!state.bench.item) state.bench.item = "box_sealed"; state.bench.ticks = 0; }));
      p.spot("bench");
      p.add(S.anim("inspect", 1800, true), S.call(() => {
        [0, 1, 2].forEach((i) => scene.after(scene.reduced ? 0 : 300 + i * 450, () => { state.bench.ticks = i + 1; }));
      }), S.anim("tick", 1600), S.anim("idle_happy", 400));
      p.back();
      p.run(() => { state.bench.ticks = 3; });
    },
    stamp_release(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.add(S.call(() => { state.bench.slip = "release"; state.bench.slipMark = null; }));
      p.spot("bench");
      p.add(...stampSteps("stamp_green", () => {
        state.bench.slipMark = { text: "放行", color: PAL.green2 };
        scene.emit("spark", SPOT.bench[0] + 10, ROW_A - 10, 10);
      }));
      p.add(S.icon({ kind: "check" }), S.anim("idle_happy", 700), S.icon(null));
      p.add(S.call(() => { state.bench.item = null; state.bench.slip = null; state.bench.slipMark = null; }), S.hold("box_sealed"));
      p.spot("pipe", "carry");
      p.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
        const actor = actorOf(a.id);
        if (actor) actor.hold = null;
        scene.fly({ bmp: "box_sealed", from: [p.x + 6, p.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8 });
      })), S.anim("side_reach", 900, true));
      p.back();
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; state.bench.item = null; state.bench.slip = null; state.bench.slipMark = null; });
    },
    stamp_rework(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.add(S.call(() => { state.bench.slip = "defect"; state.bench.slipMark = null; if (!state.bench.item) state.bench.item = "box_sealed"; }));
      p.spot("bench");
      p.add(...stampSteps("stamp_red", () => { state.bench.slipMark = { text: "返工", color: PAL.red2 }; }));
      p.add(S.call(() => { state.bench.item = "box_rework"; }), S.icon({ kind: "exclaim" }), S.anim("stand_sad", 800), S.icon(null));
      p.back();
      p.run(() => { state.bench.item = "box_rework"; state.bench.slipMark = { text: "返工", color: PAL.red2 }; });
      scene.after(scene.reduced ? 1700 : 3800, () => {
        if (state.bench.item !== "box_rework") return;
        const pa = primary();
        if (!pa) return;
        const p2 = plan(pa);
        p2.stand();
        p2.spot("bench");
        p2.add(S.call(() => { state.bench.item = null; state.bench.slip = null; state.bench.slipMark = null; }), S.hold("box_rework"));
        p2.spot("pipe", "carry");
        p2.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
          const actor = actorOf(pa.id);
          if (actor) actor.hold = null;
          scene.fly({ bmp: "box_rework", from: [p2.x + 6, p2.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8 });
        })), S.anim("side_reach", 900, true));
        p2.back();
        p2.run(() => { const actor = actorOf(pa.id); if (actor) actor.hold = null; });
      });
    },
    send_letter(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.sit();
      p.add(S.anim("write", 1200), S.hold("letter"));
      p.spot("tube", "carry");
      p.add(S.anim("side_place", 800, true), S.call(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; }), S.anim("wait", 2600, true));
      p.back();
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; });
    },
    answer_letter(ev, a) {
      setPersist(a, null);
      const sides = letterSides(ev);
      const reads = ev.type === "collaboration_requested" || sides.asker === dept;
      const p = plan(a);
      const take = (ms: number): Step => S.call(() => {
        scene.fly({ bmp: "letter", from: [L.tube.x + 4, L.tube.base - 8], to: [p.x + 4, p.y - 20], ms, arc: 8, onDone: () => { const actor = actorOf(a.id); if (actor) actor.hold = "letter"; } });
      });
      p.spot("tube");
      p.add(take(600), S.anim("reach", 800, true), S.anim("catch", 700));
      if (reads) {
        p.add(S.anim("read_stand", 1500, true), S.hold(null));
      } else {
        p.add(S.hold("letter"), S.anim("write", 1400));
        p.add(S.anim("side_place", 800, true), S.call(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; }), S.anim("wait", 900, true));
      }
      p.back();
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; });
    },
    compact(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.stand();
      p.add(S.anim("gather", 1000), S.call(() => { ds(a).hidePapers = true; drop(a, "folder"); }), S.hold("docs"));
      p.spot("archive", "carry");
      p.add(S.call(() => {
        const actor = actorOf(a.id);
        if (actor) actor.hold = null;
        scene.fly({ bmp: "docs", from: [p.x - 8, p.y - 22], to: [L.cabinet.x + 12, L.cabinet.base - 50], ms: 450, arc: 10, onDone: () => { state.archiveFlash = scene.realT + 1600; } });
      }), S.anim("side_place", 900, true), S.anim("idle_happy", 600));
      p.back();
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; ds(a).hidePapers = false; });
    },
    compact_fail(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const d = a.desk;
      ds(a).hidePapers = true;
      scene.emit("paper", d.x + 10, ROW_B - 8, ds(a).papers * 2, { floor: ROW_B - 12 });
      const p = plan(a);
      p.stand();
      p.add(S.anim("shock", 500));
      p.to(d.seatX - 14, ROW_B - 12);
      p.add(S.anim("crouch", 900, true));
      p.to(d.seatX + 16, ROW_B - 14);
      p.add(S.anim("crouch", 900), S.hold("docs"), S.anim("gather", 700), S.call(() => { ds(a).hidePapers = false; }), S.hold(null));
      p.back();
      p.run(() => { ds(a).hidePapers = false; const actor = actorOf(a.id); if (actor) actor.hold = null; });
    },
    paused(_ev: PixelFloorEvent, a: RoomActor) {
      state.doorEvent = "已暂停";
      state.eventStatus = "paused";
      applyLights();
      const p = plan(a);
      p.sit();
      p.add(S.anim("sit_relax", 1200, true));
      p.run();
    },
    failed(ev, a) {
      const pl = (ev.payload ?? {}) as Record<string, unknown>;
      state.doorEvent = `失败${pl.reason || pl.stopReason ? `：${pl.reason || pl.stopReason}` : ""}`;
      state.eventStatus = "failed";
      applyLights();
      ds(a).redLamp = true;
      const p = plan(a);
      p.sit();
      p.add(S.anim("slump", 1400, true));
      p.run();
    },
    done(_ev: PixelFloorEvent, a: RoomActor) {
      state.doorEvent = "已完成";
      state.eventStatus = "done";
      applyLights();
      const p = plan(a);
      p.stand();
      p.add(S.call(() => scene.emit("confetti", 240, 8, 60, { spread: 460 })), S.anim("cheer", 2200, true));
      p.run();
    },
    cancelled(_ev: PixelFloorEvent, a: RoomActor) {
      state.doorEvent = "已取消";
      state.eventStatus = "cancelled";
      applyLights();
      const p = plan(a);
      p.stand();
      p.add(S.anim("tidy", 1800, true), S.anim("idle", 400));
      p.run();
    },
    freeze() {
      state.eventStatus = "interrupted";
      state.doorEvent = "中断";
      applyLights();
    },
    puzzled(ev) {
      state.eventStatus = "pending_verification";
      state.eventTool = ((ev.payload as Record<string, unknown>)?.tool as string) || ev.tool || "run_command";
      state.lastPendingTool = state.eventTool;
      scene.frozen = false;
      applyLights();
    },
    hold_card(ev) {
      const pl = (ev.payload ?? {}) as Record<string, unknown>;
      state.eventStatus = "waiting_resume";
      state.eventCard = (pl.missing as string) || (pl.text as string) || quoted(ev.label) || "待恢复";
      state.doorEvent = "待恢复";
      scene.frozen = false;
      applyLights();
    },
    resume(_ev: PixelFloorEvent, a: RoomActor) {
      state.eventStatus = "working";
      state.eventCard = null;
      state.eventTool = null;
      state.doorEvent = null;
      scene.frozen = false;
      applyLights();
      for (const x of roleActors()) {
        const actor = actorOf(x.id);
        if (actor?.script) scene.cancel(actor);
        setPersist(x, null);
        const p = plan(x);
        p.add(S.anim(x === a ? "stretch_sit" : "stretch", undefined, x === a));
        p.back();
        p.run();
      }
    },
    assign(ev) {
      const mgr = byKind("manager") || primary();
      if (!mgr) return;
      const list = roleActors();
      const target = list.find((x) => x.id === (((ev.payload as Record<string, unknown>)?.to as string) || ev.role) && x !== mgr)
        || list.find((x) => x !== mgr);
      if (!target) return;
      const gs = giveSpot(target.desk);
      const p = plan(mgr);
      p.stand();
      p.add(S.hold("card_task"));
      p.to(gs[0], gs[1]);
      p.add(S.turn(gs[2]), S.anim("give", undefined, true), S.call(() => {
        keep(target, "card");
        state.wbTags[target.id] = true;
        say(ev, target, "to");
      }), S.hold(null), S.anim("idle_happy", 400));
      p.back();
      p.run(() => {
        const actor = actorOf(mgr.id);
        if (actor) actor.hold = null;
        if (!shown(target, "card")) keep(target, "card");
        state.wbTags[target.id] = true;
      });
      const targetActor = actorOf(target.id);
      if (targetActor && scene.inTail(targetActor)) scene.run(targetActor, [S.anim("sit_up", 1600)], { tail: 0 });
    },
    hand_back(ev, a) {
      const mgr = byKind("manager") || primary();
      if (!mgr) return;
      const worker = a === mgr ? roleActors().find((x) => x !== mgr) : a;
      if (!worker) return;
      const gs = giveSpot(mgr.desk);
      say(ev, worker);
      const p = plan(worker);
      p.stand();
      p.add(S.call(() => drop(worker, "card")), S.hold("card_result"));
      p.to(gs[0], gs[1]);
      p.add(S.turn(gs[2]), S.anim("give", undefined, true), S.call(() => {
        keep(mgr, "cardResult");
        state.wbDone[worker.id] = true;
        say(ev, mgr, "to");
      }), S.hold(null), S.anim("idle_happy", 400));
      p.back();
      p.run(() => {
        const actor = actorOf(worker.id);
        if (actor) actor.hold = null;
        if (!shown(mgr, "cardResult")) keep(mgr, "cardResult");
        state.wbDone[worker.id] = true;
      });
      const mgrActor = actorOf(mgr.id);
      if (mgrActor && scene.inTail(mgrActor)) scene.run(mgrActor, [S.anim(mgrActor.seat ? "sit_happy" : "idle_happy", 1800)], { tail: 0 });
    },
    explore(_ev: PixelFloorEvent, a: RoomActor) {
      const ex = byKind("explorer") || a;
      setPersist(ex, null);
      let filed = false;
      const file = (): void => { if (!filed) { filed = true; keep(ex, "folder"); } };
      const p = plan(ex);
      p.stand();
      p.to(SPOT.door[0], SPOT.door[1]);
      p.add(S.go(SPOT.doorIn[0], SPOT.doorIn[1]), S.fade(0, 260), S.wait(2400), S.hold("docs"), S.fade(1, 260));
      p.x = SPOT.doorIn[0];
      p.y = SPOT.doorIn[1];
      p.to(SPOT.door[0], SPOT.door[1], "carry");
      p.add(S.anim("carry_f", 800, true));
      p.sit("carry");
      p.add(S.call(file), S.hold(null), S.anim("sit_happy", 800));
      p.run(() => {
        const actor = actorOf(ex.id);
        if (actor) { actor.alpha = 1; actor.hold = null; }
        state.door = 0;
        file();
      });
    },
    replan() {
      const mgr = byKind("manager") || primary();
      if (!mgr) return;
      let rewritten = false;
      const rewrite = (): void => {
        if (!rewritten) {
          rewritten = true;
          state.wbErase = 0;
          state.wbSeed += 1;
          state.wbSheetUntil = 0;
          state.wbTags = {};
          state.wbDone = {};
        }
      };
      const p = plan(mgr);
      p.spot("wb");
      p.add(S.call(() => { state.wbErase = 0; state.wbErase = 1; }), S.anim("board_erase", 1500, true),
        S.call(rewrite), S.anim("board_write", 1600), S.anim("back", 300));
      p.back();
      p.run(rewrite);
    },
    review(ev, a) {
      setPersist(a, null);
      const pl = (ev.payload ?? {}) as Record<string, unknown>;
      const verdict = pl.verdict === "return" || pl.verdict === "reject" ? "退回" : "通过";
      const color = verdict === "通过" ? PAL.green2 : PAL.red2;
      const rv = byKind("reviewer") || a;
      const p = plan(rv);
      p.stand();
      p.spot("bench");
      p.add(S.hold("pen_red"), S.anim("write", 1200), S.hold(null), S.anim("inspect", 900));
      p.add(...stampSteps("stamp", () => { state.bench.mark = { text: verdict, color }; }, "stamp_once"));
      p.back();
      p.run(() => { state.bench.mark = { text: verdict, color }; });
    },
    guidance_in() {
      scene.fly({ bmp: "note", from: [L.door.x + 18, L.door.base - 9], to: [L.mailbox.x + 7, L.mailbox.base - 9], ms: 700, arc: 2 });
    },
    guidance_read(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.spot("mailbox");
      p.add(S.anim("crouch", 700), S.hold("note"), S.anim("read_stand", 1400));
      p.spot("cork");
      p.add(S.call(() => scene.after(scene.reduced ? 0 : 450, () => {
        const actor = actorOf(a.id);
        if (actor) actor.hold = null;
        const k = Math.max(0, (model.pinned_notes || 1) - 1) % 6;
        scene.fly({ bmp: "note", from: [SPOT.cork[0], SPOT.cork[1] - 24], to: [L.cork.x + 3 + (k % 3) * 9, L.cork.y + 4 + Math.floor(k / 3) * 13], ms: 350, arc: 4, onDone: () => { state.noteHide = 0; } });
      })), S.anim("note_pin", undefined, true), S.hold(null), S.anim("back", 500));
      p.back();
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; state.noteHide = 0; });
    },
    guidance_reply(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.spot("cork");
      p.add(S.anim("board_write", 1700, true), S.call(() => { state.replyUntil = scene.realT + 3000; }), S.anim("back", 400));
      p.back();
      p.run();
    },
    // 试用网页或桌面程序：测试工程师坐在试用台前点击与输入（3.2D）
    trial(ev, _a: RoomActor) {
      const pl = (ev.payload ?? {}) as Record<string, unknown>;
      const t = byKind("tester") || primary();
      if (!t) return;
      setPersist(t, null);
      state.eventStep = (pl.step as number) || (model.trial && (model.trial.step as number)) || 1;
      if (pl.text_lines) state.eventLines = pl.text_lines as string[];
      if (!state.trialSeat) return;
      const p = plan(t);
      p.to(state.trialSeat.seatX, state.trialSeat.seatY);
      p.steps.push(S.seat(state.trialSeat), S.turn(1));
      p.seated = true;
      p.add(S.anim("type", 2200, true));
      p.back();
      p.run(() => { state.eventStep = 0; state.eventLines = null; });
    },
    self_test(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, { anim: "type" });
      state.selfShot = true;
      const p = plan(a);
      p.sit();
      p.add(S.anim("type", 2200, true), S.anim("sit_up", 900, true));
      p.run(() => { state.selfShot = true; });
    },
    read_existing(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.to(SPOT.door[0], SPOT.door[1]);
      p.add(S.go(SPOT.doorIn[0], SPOT.doorIn[1]), S.fade(0, 260), S.wait(1400), S.hold("docs"), S.fade(1, 260));
      p.x = SPOT.doorIn[0];
      p.y = SPOT.doorIn[1];
      p.to(SPOT.door[0], SPOT.door[1], "carry");
      p.sit("carry");
      p.add(S.call(() => { state.wbExisting = true; }), S.hold("doc"), S.anim("read_sit", 3200, true));
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; state.wbExisting = true; });
    },
    remote_run(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      state.eventMachine = (model.machine as string) || "登记的机器";
      const p = plan(a);
      p.spot("terminal");
      p.add(S.call(() => { state.lever = 1; state.termRun = true; state.exit = null; }), S.anim("lever", 1000), S.anim("watch_r", 2600, true));
      p.run(() => { state.eventMachine = null; state.termRun = false; });
    },
    remote_unknown(_ev: PixelFloorEvent, a: RoomActor) {
      state.eventRemote = true;
      state.eventMachine = (model.machine as string) || null;
      state.termRun = false;
      const p = plan(a);
      p.spot("terminal");
      p.add(S.icon({ kind: "question" }), S.anim("watch_r", 1500), S.anim("puzzled", 3000, true), S.icon(null));
      p.run(() => { state.eventRemote = false; });
    },
    net_fetch(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.spot("post", "carry");
      p.add(S.hold("letter"), S.anim("side_place", 700, true), S.call(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; state.postFlag = 1; }), S.anim("wait", 1400, true));
      p.add(S.call(() => {
        state.postFlag = 0;
        scene.fly({ bmp: "docs", from: [L.post.x + 6, L.post.base - 22], to: [p.x + 4, p.y - 20], ms: 620, arc: 12, onDone: () => { const actor = actorOf(a.id); if (actor) actor.hold = "docs"; } });
      }), S.anim("catch", 900));
      p.back("carry");
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; state.postFlag = 0; });
    },
    mcp_press(ev, a: RoomActor) {
      setPersist(a, null);
      const pl = (ev.payload ?? {}) as Record<string, unknown>;
      const idx = (pl.index as number) ?? (pl.button as number) ?? 0;
      const panel = model.tool_panel;
      const n = (panel?.buttons?.length) || 3;
      const k = Math.max(0, Math.min(n - 1, idx));
      const p = plan(a);
      p.spot("tool");
      p.add(S.anim("reach", 900, true), S.call(() => { state.toolLit = k; scene.emit("spark", L.tool.x + 6 + k * 14, L.tool.y + L.tool.h - 4, 8); }), S.anim("idle_happy", 800));
      p.back();
      p.run(() => { state.toolLit = -1; });
    },
    deploy(_ev: PixelFloorEvent, a: RoomActor) {
      const p = plan(a);
      state.cart.box = "box_sealed";
      state.cart.pushed = true;
      state.mdoorGlow = 1;
      p.stand();
      p.add(S.anim("push", undefined, true));
      p.to(SPOT.mdoor[0], SPOT.mdoor[1], "push", 30);
      p.add(S.turn(1), S.anim("side_reach", 700, true), S.call(() => {
        state.cart.box = null;
        state.cart.pushed = false;
        state.cart.x = 296;
        state.backupLit = Math.min(3, state.backupLit + 1);
        state.backupFlash = scene.realT + 1800;
        scene.emit("spark", L.mdoor.x + 8, L.mdoor.base - 34, 10, { color: PAL.green1 });
      }), S.anim("idle_happy", 600));
      p.back();
      p.run(() => { state.mdoorGlow = 0; state.cart.pushed = false; state.cart.box = null; state.cart.x = 296; });
    },
    rollback(_ev: PixelFloorEvent, a: RoomActor) {
      const p = plan(a);
      p.spot("mdoor");
      p.add(S.call(() => { state.mdoorGlow = 1; }), S.anim("reach", 700, true), S.call(() => {
        scene.fly({ bmp: "box", from: [L.mdoor.x + 8, L.mdoor.base - 30], to: [p.x + 4, p.y - 20], ms: 700, arc: 10, onDone: () => { const actor = actorOf(a.id); if (actor) actor.hold = "box"; } });
      }), S.anim("catch", 900), S.anim("idle_happy", 600));
      p.back("carry");
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; state.mdoorGlow = 0; });
    },
    fault(_ev: PixelFloorEvent, a: RoomActor) {
      const p = plan(a);
      p.stand();
      p.add(S.icon({ kind: "exclaim" }), S.anim("shock", 400));
      p.to(SPOT.monitor[0], SPOT.monitor[1], "run", 90);
      p.add(S.icon(null), S.anim("board_write", 1400, true), S.call(() => { state.monitorAlarmUntil = scene.realT + 9000; }), S.hold("letter"));
      p.spot("pipe", "carry");
      p.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
        const actor = actorOf(a.id);
        if (actor) actor.hold = null;
        scene.fly({ bmp: "letter", from: [p.x + 6, p.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8 });
      })), S.anim("side_reach", 900, true));
      p.back();
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; state.monitorAlarmUntil = scene.realT + 9000; });
    },
    wait_provider(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      state.eventWaiting = true;
      applyLights();
      const p = plan(a);
      p.sit();
      p.add(S.anim("sit_up", 2600, true));
      p.run(() => { state.eventWaiting = false; applyLights(); });
    },
    hold_form(ev, a: RoomActor) {
      setPersist(a, null);
      const pl = (ev.payload ?? {}) as Record<string, unknown>;
      const what = (pl.action as string) || (pl.kind === "external_action" ? "外部动作" : (pl.kind as string)) || quoted(ev.label) || "外部动作";
      const text = `待授权：${what}`;
      const p = plan(a);
      p.to(SPOT.door[0] - 16, SPOT.door[1] + 4);
      p.add(S.turn(1), S.call(() => { a.formSign = text; }), S.anim("hold_form", 1600, true));
      p.mark();
      p.add(S.anim("hold_form", 3600), S.call(() => { a.formSign = null; }));
      p.back();
      p.run(() => { a.formSign = null; });
    },
    decided(ev, a: RoomActor) {
      const pl = (ev.payload ?? {}) as Record<string, unknown>;
      const choice = (pl.choice as string) || "accept_current";
      const tool = ev.tool || (pl.tool as string) || state.lastPendingTool || model.pending_tool || "run_command";
      const words: Record<string, string> = { rerun: "重新执行", accept_current: "按当前实际状态继续", stop: "停止事项" };
      state.eventStatus = choice === "stop" ? "cancelled" : "working";
      state.eventTool = null;
      if (choice === "stop") state.doorEvent = "已停止";
      applyLights();
      setPersist(a, null);
      const p = plan(a);
      p.to(SPOT.door[0] - 14, SPOT.door[1] + 2);
      p.add(S.turn(1), S.call(() => {
        scene.fly({ bmp: "decision", from: [L.door.x + 18, L.door.base - 9], to: [p.x + 6, p.y - 2], ms: 500, arc: 2 });
      }), S.anim("crouch", 700), S.hold("decision"), S.icon({ kind: "text", text: words[choice] || choice }), S.anim("read_stand", 1500, true), S.icon(null), S.hold(null));
      if (choice === "rerun") {
        const spot = toolSpot(tool);
        if (spot === "terminal") {
          p.spot("terminal");
          p.add(S.call(() => scene.after(scene.reduced ? 0 : 450, () => { state.lever = 1; state.termRun = true; state.exit = null; })), S.anim("lever", 1000), S.anim("watch_r", 1600));
        } else if (spot === "cabinet") {
          p.spot("cabinet");
          p.add(S.call(() => { state.drawer = 1; }), S.anim("rummage", 1200), S.call(() => { state.drawer = 0; }));
        } else if (spot === "bench") {
          p.spot("bench");
          p.add(S.anim("inspect", 1400));
        } else {
          p.sit();
          p.add(S.anim("write", 1400));
        }
        p.back();
      } else if (choice === "stop") {
        p.to(a.desk.seatX, a.desk.seatY);
        p.add(S.anim("tidy", 1600));
      } else {
        p.back();
        p.add(S.anim("type", 800));
      }
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; });
    },
    manager_out(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const mgr = byKind("manager") || a;
      const p = plan(mgr);
      p.stand();
      p.spot("pipe", "carry");
      p.add(S.hold("box_sealed"), S.anim("side_reach", 800, true), S.call(() => { const actor = actorOf(mgr.id); if (actor) actor.hold = null; }), S.anim("idle", 400));
      p.spot("tube", "carry");
      p.add(S.hold("letter"), S.anim("side_place", 800, true), S.call(() => { const actor = actorOf(mgr.id); if (actor) actor.hold = null; }), S.anim("idle", 500));
      p.back();
      p.run(() => { const actor = actorOf(mgr.id); if (actor) actor.hold = null; });
    },
    semantic(_ev: PixelFloorEvent, a: RoomActor) {
      const d = a.desk;
      if ((model.semantic_cards || 0) > 0) state.cardHide = scene.realT + 5000;
      scene.fly({ bmp: "card", from: [d.seatX, ROW_B - 22], to: [L.cards.x + 12, L.cards.base - 32], ms: 900, arc: 30, onDone: () => { state.cardHide = 0; state.cardFlash = scene.realT + 1600; } });
      const actor = actorOf(a.id);
      if (actor && scene.inTail(actor)) scene.run(actor, [S.anim("sit_up", 1200)], { tail: 0 });
    },
    toss(_ev: PixelFloorEvent, a: RoomActor) {
      setPersist(a, null);
      const p = plan(a);
      p.stand();
      p.add(S.anim("shake", undefined), S.anim("fold", 600), S.hold("paperball"), S.call(() => scene.after(scene.reduced ? 0 : 450, () => {
        const actor = actorOf(a.id);
        if (actor) actor.hold = null;
        scene.fly({ bmp: "paperball", from: [p.x + 6, p.y - 20], to: [state.bin.x + 5, state.bin.y - 10], ms: 650, arc: 22, onDone: () => { state.binUntil = scene.realT + 3500; } });
      })), S.anim("throw", 1000, true));
      p.back();
      p.run(() => { const actor = actorOf(a.id); if (actor) actor.hold = null; });
    },
  };

  function commandDone(ev: PixelFloorEvent, a: RoomActor): void {
    const pl = (ev.payload ?? {}) as Record<string, unknown>;
    const code = pl.exit_code as number;
    const timedOut = Boolean(pl.timed_out);
    state.termRun = false;
    state.exit = timedOut ? "red" : code === 0 ? "green" : "red";
    if (timedOut) state.smokeUntil = scene.realT + 4200;
    state.lever = 0;
    const ok = state.exit === "green";
    const p = plan(a);
    p.spot("terminal");
    p.add(S.icon({ kind: timedOut ? "exclaim" : ok ? "check" : "cross" }), S.anim(ok ? "idle_happy" : "stand_sad", 1200, true), S.icon(null));
    p.back();
    p.run();
  }

  /** 流式输出：把 attempt.live 已收到的文字交给正在做模型请求的角色（设计说明第 6 节）。
   *  没有正在做模型请求的角色时不改动画面的任何状态。 */
  function setStreamText(text: string): void {
    const target = roleActors().find((a) => a.persist?.icon?.kind === "stream")
      ?? roleActors().find((a) => a.doing === "type_think" || a.doing === "stream_text")
      ?? primary();
    if (!target) return;
    target.streamText = text.slice(-120);
    target.persist = { anim: "type", icon: { kind: "stream", text: target.streamText } };
  }

  function playEvent(ev: PixelFloorEvent): void {
    if (!ev || !ev.type) throw new Error("playEvent 需要事件对象");
    const pl = (ev.payload ?? {}) as Record<string, unknown>;
    const related = !ev.department || ev.department === dept || pl.from === dept || pl.to === dept;
    if (!related) return;
    if (PROPOSAL_DONE.has(ev.type)) state.trayPaper = false;
    if ((ev.type === "spec_accepted" || ev.type === "contract_accepted") && dept === "product" && (model.scrolls || 0) > 0) {
      state.scrollHide = scene.realT + 15000;
    }
    if (ev.type === "department_guidance_applied" && (model.pinned_notes || 0) > 0) state.noteHide = scene.realT + 15000;
    if (ev.type === "transition") {
      transition(ev);
      return;
    }
    if (ev.type === "collaboration_closed") {
      for (const x of roleActors()) {
        const actor = actorOf(x.id);
        if (actor?.script && actor.anim === "wait") scene.cancel(actor);
      }
      if (state.eventStatus === "asking") state.eventStatus = null;
      return;
    }
    let action = resolveAction(ev);
    // 建档事项（3.8）中读取与搜索工具的 tool_started 播放「阅读已有项目」
    if (model.existing_read && (action === "read" || action === "search")) action = "read_existing";
    if (action === "send_letter") {
      const sides = letterSides(ev);
      if (sides.answerer === dept && sides.asker !== dept) action = "answer_letter";
    }
    const a = (action === "assign" || action === "replan") ? (byKind("manager") || primary())
      : action === "explore" ? (byKind("explorer") || actorFor(ev)) : actorFor(ev);
    if (!a) return;
    if (scene.frozen && action !== "resume" && action !== "puzzled" && action !== "hold_card") return;
    if (a.role.status === "away" && action !== "explore") return;
    if (!action) {
      if (ev.type === "tool_started") {
        setPersist(a, { anim: "type" });
        if (!scene.frozen) say(ev, a);
      }
      return;
    }
    const fn = handlers[action];
    if (!fn) return;
    if (SIDE_ONLY.has(action)) {
      say(ev, a);
      fn(ev, a);
      return;
    }
    const actor = actorOf(a.id);
    if (!IMMEDIATE.has(action) && actor && !scene.inTail(actor) && a.doing === action) return;
    if (action !== "slump" && action !== "failed") ds(a).redLamp = false;
    const start = (): void => {
      const actor2 = actorOf(a.id);
      if (actor2) actor2.icon = null;
      a.doing = action;
      if (!OWN_SPEECH.has(action) && !THINK_ACTIONS.has(action)) say(ev, a);
      fn(ev, a);
    };
    if (IMMEDIATE.has(action) || (actor && scene.inTail(actor))) {
      a.queue = [];
      start();
      return;
    }
    a.queue.push({ fn: start, at: scene.realT, from: ev.type });
    if (a.queue.length > 3) a.queue.shift();
  }

  // 与原型 room.js 一致：建立画面时先按缺省角色设置同步一次（一个部门一个 Agent），快照到达时再同步
  syncRoles();
  applyLights();

  return {
    get model() { return model; },
    state,
    scene,
    actors: roleActors,
    primary,
    actorById,
    setModel,
    playEvent,
    setStreamText,
    step,
  };
}


