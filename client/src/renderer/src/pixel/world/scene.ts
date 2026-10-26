// 画面（scene）：走路的脚本、缓动与共用时钟，以及每个角色与每根管道的 XState 状态机（原型 engine.js
// 第 4 至 6 节与 ecs.js 第 3.4 节，工单 #82）。
//
// 场景不依赖 PixiJS：它保存 actor（小人、包裹与陈设的显示状态）、时间、随机数与状态机，
// 用脚本按帧推进位置与姿势。渲染层只读 actor 的当前状态；测试用确定的时钟与随机数驱动同一个场景。
// GSAP 的补间与 PixiJS 的渲染读同一个时钟（clock.ts），全场景的时间都由 scene.stepped 累加。

import { createActor } from "xstate";
import { animDuration as animTotal, hash } from "../anims.ts";
import { characterMachine, pipeMachine } from "./state.ts";
import type {
  Actor, ActorInit, Character, Geo, HeadIconKind, PackageVisual, ParticleModel, Pipe, SceneLike, SceneOptions, Seat, Step, World,
} from "./types.ts";

/** 角色实体对应的 actor 的 id 前缀。 */
export const CHAR_ACTOR_PREFIX = "ch-";

/**
 * 表演层开着吗（设计说明第 8.1 节的 H2）：关掉以后动作与特效都不演，只画状态给出的样子。
 * 待机活动由 scene.autonomy 控制（行为开关），两者一起关掉就是「只画状态」。
 */
function performing(scene: SceneLike): boolean {
  return scene.performance !== false;
}

/** 建立一个场景：actor 的脚本按帧推进，走路的耗时由距离与速度决定。 */
export function createScene(opts: SceneOptions): SceneLike {
  const scene: SceneLike = {
    W: opts.W,
    H: opts.H,
    realT: 0,
    animT: 0,
    reduced: opts.reduced,
    frozen: false,
    autonomy: true,
    performance: true,
    actors: [],
    flyers: [],
    particles: [],
    focusId: null,
    random: opts.random,
    easeInOut: (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2),
    pointAlong,
    machines: new Map(),
    characterStates: new Map(),
    pipeStates: new Map(),
    afterCallbacks: [],
    packageRequests: [],
    addActor(o: ActorInit) {
      const actor: Actor = {
        id: o.id,
        sprite: o.sprite,
        x: o.x,
        y: o.y,
        facing: o.facing ?? 1,
        anim: o.anim ?? "idle",
        animStart: 0,
        clock: 0,
        // 小人的随机相位取声明序号的哈希（原型 engine.js 第 843 行）；不消耗场景的随机数序列
        seed: Math.floor(hash(scene.actors.length + 7) * 3000),
        hold: o.hold ?? null,
        face: null,
        alpha: 1,
        dim: 1,
        visible: o.visible !== false,
        seat: null,
        script: null,
        step: null,
        icon: null,
        sign: null,
        bubble: null,
        speed: o.speed ?? 84,
        shadow: o.shadow !== false,
        data: o.data ?? {},
      };
      scene.actors.push(actor);
      return actor;
    },
    removeActor(a) {
      scene.actors = scene.actors.filter((x) => x !== a);
    },
    play(a, animName, restart) {
      if (a.anim !== animName || restart) {
        a.anim = animName;
        a.animStart = a.clock;
      }
    },
    cancel(a) {
      a.script?.finalize?.();
      a.step?.tween?.kill();
      a.script = null;
      a.step = null;
    },
    run(a, steps, o) {
      a.script?.finalize?.();
      const explicit = o?.tail !== undefined && o.tail !== null ? o.tail : steps.length;
      const key = steps.findIndex((s) => s.key);
      const tail = Math.min(explicit, key >= 0 ? key + 1 : steps.length);
      a.script = { steps: steps.slice(), i: 0, tail, finalize: o?.finalize, onDone: o?.onDone };
      a.step = null;
    },
    inTail(a) {
      return !a.script || a.script.i >= a.script.tail;
    },
    after(ms, fn) {
      scene.afterCallbacks.push({ at: scene.realT + ms, fn });
    },
    fly(o) {
      if (scene.reduced || !performing(scene)) {
        if (o.onDone) scene.after(0, o.onDone);
        return;
      }
      scene.flyers.push({ bmp: o.bmp, from: o.from, to: o.to, t0: scene.realT, ms: o.ms, arc: o.arc ?? 10, onDone: o.onDone });
    },
    emit(kind, x, y, n, o) {
      if (scene.reduced || !performing(scene)) return;
      const opt = o ?? {};
      for (let i = 0; i < n; i++) {
        const r1 = scene.random();
        const r2 = scene.random();
        const r3 = scene.random();
        const p: ParticleModel = { kind, x, y, vx: 0, vy: 0, g: 0, life: 800, age: 0, size: 1, color: "#ffffff", drag: 1 };
        switch (kind) {
          case "dust":
            p.vx = (r1 - 0.5) * 70; p.vy = -r2 * 30 - 6; p.g = 90; p.life = 420 + r3 * 250;
            p.color = r3 > 0.5 ? "#d8cfbd" : "#f4efe6"; p.size = r2 > 0.6 ? 2 : 1;
            break;
          case "confetti":
            p.x = x + (r1 - 0.5) * (opt.spread ?? 120); p.y = y - r2 * 20;
            p.vx = (r2 - 0.5) * 20; p.vy = 10 + r3 * 20; p.g = 8; p.life = 2200 + r1 * 1200;
            p.color = ["#d9534f", "#ffd66b", "#4a90d9", "#5cb85c", "#e88fb8", "#e67e22"][Math.floor(r3 * 6)];
            p.size = 2; p.sway = r1 * 6.28;
            break;
          case "smoke":
            p.x = x + (r1 - 0.5) * 6; p.vx = (r2 - 0.5) * 8; p.vy = -12 - r3 * 10; p.life = 1400 + r1 * 700; p.size = r2 > 0.5 ? 2 : 1;
            break;
          case "spark":
            p.vx = Math.cos(r1 * 6.28) * (20 + r2 * 25); p.vy = Math.sin(r1 * 6.28) * (20 + r2 * 25); p.life = 380 + r3 * 200;
            p.color = r3 > 0.5 ? "#ffd66b" : "#ffffff";
            break;
          case "steam":
            p.x = x + (r1 - 0.5) * 3; p.vx = (r2 - 0.5) * 3; p.vy = -6 - r3 * 4; p.life = 900 + r1 * 400; p.color = "#f4efe6";
            break;
          default:
            throw new Error(`未知粒子：${kind}`);
        }
        if (opt.color) p.color = opt.color;
        if (opt.floor !== undefined) p.floor = opt.floor;
        scene.particles.push(p);
      }
    },
    setCharacterState(ch, state, at) {
      scene.machines.get(ch.id)?.send({ type: "STATE", value: state, at: at ?? scene.realT });
      scene.characterStates.set(ch.id, { state, since: at ?? scene.realT });
    },
    characterState(id) {
      return scene.characterStates.get(id) ?? null;
    },
    setPipeState(pipe, state, at) {
      scene.machines.get(`pipe:${pipe.id}`)?.send({ type: "STATE", value: state, at: at ?? scene.realT });
      scene.pipeStates.set(pipe.id, { state, since: at ?? scene.realT });
    },
    pipeState(id) {
      return scene.pipeStates.get(id) ?? null;
    },
    disposeCharacter(id) {
      scene.machines.get(id)?.stop();
      scene.machines.delete(id);
      scene.characterStates.delete(id);
    },
    stepScene(deltaMs) {
      scene.realT += deltaMs;
      if (!scene.frozen && !scene.reduced && performing(scene)) scene.animT += deltaMs;
      // 一帧里的顺序与原型 engine.js 的 frame 一致：先到点的回调，再小人，再粒子与飞行物。
      // 回调先跑，定时开始的脚本才能在同一帧里迈出第一步，与原型一样。
      for (const timer of scene.afterCallbacks.filter((x) => x.at <= scene.realT)) timer.fn();
      scene.afterCallbacks = scene.afterCallbacks.filter((x) => x.at > scene.realT);
      for (const actor of scene.actors.slice()) advanceActor(scene, actor, deltaMs);
      advanceParticles(scene, deltaMs);
      advanceFlyers(scene);
    },
    hasTween: opts.tween !== undefined,
    tween: opts.tween ?? (() => ({ kill: () => {} })),
    reapply: opts.reapply ?? (() => {}),
    makeCharacterMachine: opts.makeCharacterMachine ?? ((input) => characterMachine(input)),
    makePipeMachine: opts.makePipeMachine ?? ((input) => pipeMachine(input)),
  };
  return scene;
}

/** 为角色与管道建立状态机，并登记到场景里（世界每次声明之后调用）。 */
export function mountMachines(
  scene: SceneLike,
  characters: Character[],
  pipes: Pipe[],
): void {
  for (const ch of characters) {
    if (scene.machines.has(ch.id)) continue;
    const machine = scene.makeCharacterMachine({ id: ch.id, department: ch.department, roleKind: ch.roleKind }) as Parameters<typeof createActor>[0];
    const actor = createActor(machine);
    actor.start();
    scene.machines.set(ch.id, actor);
  }
  for (const pipe of pipes) {
    const key = `pipe:${pipe.id}`;
    if (scene.machines.has(key)) continue;
    const machine = scene.makePipeMachine({ id: pipe.id, from: pipe.from, to: pipe.to, linkKind: pipe.linkKind }) as Parameters<typeof createActor>[0];
    const actor = createActor(machine);
    actor.start();
    scene.machines.set(key, actor);
  }
}

/** 折线上按弧长取点。 */
export function pointAlong(pts: [number, number][], d: number): [number, number] {
  let left = d;
  for (let i = 1; i < pts.length; i++) {
    const seg = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    if (left <= seg || i === pts.length - 1) {
      const k = seg ? Math.min(1, left / seg) : 1;
      return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * k, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * k];
    }
    left -= seg;
  }
  return pts[pts.length - 1];
}

/** 角色实体对应的 actor。 */
export function actorOf(scene: SceneLike, id: string): Actor | null {
  return scene.actors.find((x) => x.id === CHAR_ACTOR_PREFIX + id) ?? null;
}

/** 一个部门里的全部角色实体。 */
export function charsOf(world: World, department: string): Character[] {
  return Object.values(world.characters).filter((c) => c.department === department);
}

/**
 * 事件或任务落在哪个角色上：指定了角色（id 或种类）就是它，
 * 否则按任务声明的 by（角色种类），再没有就是中心角色。
 */
export function charFor(world: World, department: string, role: string | null, by: string | null): Character | null {
  const list = charsOf(world, department);
  if (!list.length) return null;
  const hit = (k: string): Character | undefined => list.find((c) => c.id === k || c.roleKind === k);
  return (role ? hit(role) : undefined) ?? (by ? hit(by) : undefined) ?? primaryOf(world, department);
}

/** 部门里的中心角色：没有中心角色时是经理，再没有就是第一个。 */
const CENTER_KINDS = ["architect", "tester", "agent", "ops"];
export function primaryOf(world: World, department: string): Character | null {
  const list = charsOf(world, department);
  return list.find((c) => CENTER_KINDS.includes(c.roleKind)) ?? list.find((c) => c.roleKind === "manager") ?? list[0] ?? null;
}

/** 房间里 n 个角色的工位；n 为 1 时就是 declareRooms 算出的 desk。 */
export function layoutSeats(room: { x: number; w: number; desk: Seat; seats: Seat[] | null }, n: number, deskY: number): Seat[] {
  if (n <= 1) {
    room.seats = [room.desk];
    return room.seats;
  }
  const gap = 2;
  const w = Math.min(34, Math.floor((room.w - 10) / n) - gap);
  const total = n * (w + gap) - gap;
  const x0 = room.x + Math.round((room.w - total) / 2);
  room.seats = [];
  for (let i = 0; i < n; i++) {
    const x = x0 + i * (w + gap);
    room.seats.push({ x, w, seatX: x + Math.round((w * 12) / 34), seatY: deskY });
  }
  return room.seats;
}

const SEAT_RANK: Record<string, number> = { explorer: 0, reviewer: 1, lead: 2, agent: 3, ops: 3, architect: 3, tester: 3, manager: 4 };

/**
 * 让 specs 里的每个角色都有一个角色实体与对应的 actor（id 为 'ch-' + 角色 id），
 * 去掉不再需要的，并给每个房间排好工位。
 */
export function syncCharacters(
  world: World,
  scene: SceneLike,
  specs: { id: string; department: string; roleKind: string; name: string }[],
  spriteOf: (spec: { id: string; department: string; roleKind: string; name: string }) => string,
): void {
  const want = new Set(specs.map((s) => s.id));
  for (const actor of scene.actors.filter((x) => x.data.ecsChar && !want.has(String(x.data.charId)))) scene.removeActor(actor);
  for (const id of Object.keys(world.characters)) {
    if (!want.has(id)) {
      delete world.characters[id];
      scene.disposeCharacter(id);
    }
  }
  const byRoom: Record<string, typeof specs> = {};
  for (const s of specs) (byRoom[s.department] ??= []).push(s);
  for (const department of Object.keys(byRoom)) {
    const room = world.rooms[department];
    if (!room) throw new Error(`角色所在的房间未声明：${department}`);
    const list = byRoom[department].slice().sort(
      (p, q) => (SEAT_RANK[p.roleKind] ?? 0) - (SEAT_RANK[q.roleKind] ?? 0) || (p.id < q.id ? -1 : 1),
    );
    const relayout = !room.seats || room.seats.length !== list.length;
    if (relayout) layoutSeats(room, list.length, world.catalog.geo.DESK_Y);
    list.forEach((s, i) => {
      const seat = room.seats![i];
      let ch = world.characters[s.id];
      if (!ch) {
        ch = world.characters[s.id] = {
          kind: "character",
          id: s.id,
          department,
          roleKind: s.roleKind,
          name: s.name,
          spot: { x: seat.seatX, y: seat.seatY },
          seatIndex: i,
          queue: [],
          current: null,
          progress: null,
          rest: null,
          bubble: null,
          item: null,
          roleInfo: null,
          idleAt: null,
        };
      }
      ch.seatIndex = i;
      ch.roleKind = s.roleKind;
      ch.name = s.name;
      let actor = actorOf(scene, s.id);
      if (!actor) {
        actor = scene.addActor({
          id: CHAR_ACTOR_PREFIX + s.id,
          sprite: spriteOf(s),
          x: seat.seatX,
          y: seat.seatY,
          anim: "sit",
          data: { ecsChar: true, dept: department, charId: s.id },
        });
        actor.seat = seat;
      } else if (relayout && actor.seat) {
        actor.seat = seat;
      }
    });
  }
}

function startStep(scene: SceneLike, actor: Actor, st: Step): void {
  const step: NonNullable<Actor["step"]> = { st, t0: scene.realT, fromX: actor.x, fromY: actor.y, dur: 0, done: false };
  actor.step = step;
  switch (st.t) {
    case "go": {
      const dx = (st.x ?? actor.x) - actor.x;
      const dy = (st.y ?? actor.y) - actor.y;
      const dist = Math.hypot(dx, dy);
      if (Math.abs(dx) > 0.5) actor.facing = dx > 0 ? 1 : -1;
      const seconds = scene.reduced || dist < 0.5 ? 0 : dist / (st.speed ?? actor.speed);
      step.dur = seconds * 1000;
      scene.play(actor, st.gait ?? "walk");
      actor.seat = null;
      // 走动由 GSAP 的补间推进：补间的位置由共用的时钟推进到第几毫秒决定
      step.tween?.kill();
      if (scene.hasTween) {
        // GSAP 的补间负责把小人移到目标；步骤的完成仍按时间判定，补间只影响位置
        step.tween = scene.tween(actor as unknown as Record<string, unknown>, {
          x: st.x ?? actor.x, y: st.y ?? actor.y, duration: seconds, ease: "none",
        });
      }
      break;
    }
    case "anim":
      scene.play(actor, st.name!, true);
      if (st.facing) actor.facing = st.facing;
      step.dur = scene.reduced ? (st.key ? Math.max(st.ms ?? 0, 1600) : 0) : st.ms !== undefined ? st.ms : animTotal(st.name!);
      break;
    case "wait":
      step.dur = scene.reduced ? (st.key ? Math.max(st.ms ?? 0, 1600) : 0) : (st.ms ?? 0);
      break;
    case "fade": {
      step.fromAlpha = actor.alpha;
      step.dur = scene.reduced ? 0 : (st.ms ?? 0);
      break;
    }
    case "turn":
      actor.facing = st.facing ?? actor.facing;
      break;
    case "seat":
      actor.seat = (st.seat ?? null) as Seat | null;
      break;
    case "hold":
      actor.hold = st.item ?? null;
      break;
    case "icon":
      actor.icon = st.icon ? { kind: st.icon.kind as HeadIconKind, text: st.icon.text ?? undefined, t0: scene.realT } : null;
      break;
    case "call":
      break;
    default:
      throw new Error(`未知的脚本步骤：${st.t}`);
  }
}

/** 飞行物走到终点：执行一次 onDone 并移除（原型 updateFlyers）。 */
function advanceFlyers(scene: SceneLike): void {
  if (scene.frozen || !performing(scene)) return;
  for (const f of scene.flyers) {
    const k = Math.min(1, (scene.realT - f.t0) / f.ms);
    if (k >= 1 && !f.done) {
      f.done = true;
      f.onDone?.();
    }
  }
  scene.flyers = scene.flyers.filter((f) => !f.done);
}

function advanceParticles(scene: SceneLike, dt: number): void {
  if (scene.frozen || !performing(scene)) return;
  const s = dt / 1000;
  for (const p of scene.particles) {
    p.age += dt;
    p.vy += p.g * s;
    p.vx *= p.drag;
    p.vy *= p.drag;
    p.x += p.vx * s;
    p.y += p.vy * s;
    if (p.kind === "confetti" && p.sway !== undefined) p.x += Math.sin(p.age / 180 + p.sway) * 0.4;
    if (p.floor !== undefined && p.y > p.floor) {
      p.y = p.floor;
      p.vy = 0;
      p.vx *= 0.5;
    }
  }
  scene.particles = scene.particles.filter((p) => p.age < p.life);
}

function advanceActor(scene: SceneLike, actor: Actor, dt: number): void {
  if (!scene.reduced && !scene.frozen) actor.clock += dt;
  // 表演层关掉时动作不推进：正在演的停在原处，不再开始新的步子
  if (scene.frozen || !performing(scene) || !actor.script) return;
  let guard = 0;
  while (actor.script && guard++ < 40) {
    if (!actor.step) {
      const st = actor.script.steps[actor.script.i];
      if (!st) {
        const done = actor.script.onDone;
        actor.script = null;
        done?.();
        return;
      }
      startStep(scene, actor, st);
      if (st.t === "call" && st.fn) st.fn(actor);
    }
    const step = actor.step!;
    const elapsed = scene.realT - step.t0;
    const k = step.dur > 0 ? Math.min(1, elapsed / step.dur) : 1;
    // 没有接 GSAP 的补间时（纯逻辑测试）自己按经过时间插值
    if (step.st.t === "go" && !scene.hasTween) {
      actor.x = step.fromX + ((step.st.x ?? step.fromX) - step.fromX) * k;
      actor.y = step.fromY + ((step.st.y ?? step.fromY) - step.fromY) * k;
    }
    if (step.st.t === "fade") {
      const from = step.fromAlpha ?? actor.alpha;
      actor.alpha = from + ((step.st.to ?? 1) - from) * k;
    }
    if (k >= 1) {
      step.tween?.kill();
      // 走到目标位置时就地落到目标坐标（补间的终点与它一致）
      if (step.st.t === "go" && scene.hasTween) {
        actor.x = step.st.x ?? actor.x;
        actor.y = step.st.y ?? actor.y;
      }
      if (step.st.t === "fade") actor.alpha = step.st.to ?? 1;
      actor.step = null;
      actor.script.i++;
      // 到达与下一个动作在同一帧里接上，中间不留空档
      if (actor.script && !actor.step) {
        const next = actor.script.steps[actor.script.i];
        if (next) {
          startStep(scene, actor, next);
          if (next.t === "call" && next.fn) next.fn(actor);
        } else {
          const done = actor.script.onDone;
          actor.script = null;
          done?.();
          return;
        }
      }
      continue;
    }
    return;
  }
}

export type { Geo, PackageVisual, SceneLike, SceneOptions };
