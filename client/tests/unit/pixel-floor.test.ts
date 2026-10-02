// 世界与系统的行为测试（工单 #82 验收标准 1）：把原型 checks/behaviors.js 里关于项目楼层的检查
// 改写为对客户端的测试，直接对世界、系统与状态机运行，用确定的时钟与手写的数据。
//
// 覆盖：多角色（角色实体、工位、同时做不同的任务、事件按角色找到人、交接由经理做、没有角色设置时一个部门一个小人）、
// 自主行为（待机活动出现、成对说话、真正的任务立刻打断待机、关闭以后没有）、管道流动（满速、停下光点留下、空闲光点淡出）、
// 包裹沿管道一段一段走、运维数据出现时世界重新声明而在途的包裹与角色保留、说话目录与气泡、
// 声明（去掉一个房间照常运转、只写声明加一个新房间与一种任务）、状态机。

import { test } from "node:test";
import assert from "node:assert/strict";

import { catalog, eventActionTypes, sayCatalogTypes } from "../../src/renderer/src/pixel/world/floor-decl.ts";
import { declareLinks, declareRooms, createWorld, polyLength, pointAt, route } from "../../src/renderer/src/pixel/world/declare.ts";
import { dispatch, enqueue, stepCharacters, stepPackages, stepPipes, bubbleFor } from "../../src/renderer/src/pixel/world/characters.ts";
import { say, sayMs } from "../../src/renderer/src/pixel/world/say.ts";
import { mountMachines, syncCharacters } from "../../src/renderer/src/pixel/world/scene.ts";
import { createFloorState } from "../../src/renderer/src/pixel/world/floor.ts";
import { createScene } from "../../src/renderer/src/pixel/world/scene.ts";
import { createFloorDriver } from "../../src/renderer/src/pixel/world/floor.ts";

// ---------------------------------------------------------------------------
// 确定时钟与手写数据

function seeded(): () => number {
  let seed = 246813579;
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

const TIME = { clock: (iso: string | null) => iso ?? "", duration: (sec: number) => String(sec) };

const ROLE = (id: string, kind: string, name: string, status = "idle"): RoleInfo => ({ id, kind, name, status, task: null });

const ROLES: Record<string, RoleInfo[]> = {
  product: [ROLE("p-mgr", "manager", "产品部门经理"), ROLE("p-arch", "architect", "产品架构师", "working"), ROLE("p-exp", "explorer", "产品探索者"), ROLE("p-rev", "reviewer", "产品审查者")],
  engineering: [ROLE("e-mgr", "manager", "工程经理"), ROLE("e-arch", "architect", "工程架构师", "working"), ROLE("e-lead", "lead", "主程"), ROLE("e-exp", "explorer", "工程探索者"), ROLE("e-rev", "reviewer", "工程审查者")],
  quality: [ROLE("q-mgr", "manager", "质检经理"), ROLE("q-test", "tester", "测试工程师", "working"), ROLE("q-exp", "explorer", "质检探索者"), ROLE("q-rev", "reviewer", "质检审查者")],
};

const item = (status: string, department: string | null): LoopItem => ({
  work_item_id: "w1", kind: "request", sign: "测试事项", color_index: 0, status, department, round: 1,
  elapsed_sec: 100, time_limit_sec: 7200, version: 1, phase: null, started_at: null, pending_question: null,
  run_id: "r1", adoption_id: null, recovery_state: null,
});

function model(over: Partial<FloorModel> = {}): FloorModel {
  return {
    items: [item("running", "engineering")], open_requests: [], shelves: { adopted: [] }, slots: { total: 3, used: 1 },
    waiting_provider: [], machines: null, ops: null, interrupted: false, roles: ROLES, decisions: [], ...over,
  };
}

interface Harness {
  driver: ReturnType<typeof createFloorDriver>;
  step: (ms: number) => void;
  scene: ReturnType<typeof createScene>;
}

function mountFloor(m: FloorModel, opts: { autonomy?: boolean; reduced?: boolean } = {}): Harness {
  const scene = createScene({ W: 640, H: 320, random: seeded(), reduced: opts.reduced ?? false });
  scene.autonomy = opts.autonomy ?? false;
  const driver = createFloorDriver({ model: m, scene, state: createFloorState(), catalog, W: 640, H: 320, time: TIME });
  const step = (ms: number): void => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) {
      scene.stepScene(50);
      driver.step();
    }
  };
  return { driver, step, scene };
}

const event = (type: string, role?: string, payload?: Record<string, unknown>, department = "engineering"): PixelFloorEvent =>
  ({ type, department, role: role ?? null, work_item_id: "w1", payload: payload ?? {} });

// ---------------------------------------------------------------------------
// 多角色

test("多角色：三个部门共 13 个角色实体，工程部门 5 个角色的工位各不相同", () => {
  const h = mountFloor(model());
  h.step(1500);
  const world = h.driver.world;
  assert.equal(Object.keys(world.characters).length, 13);
  const room = world.rooms.engineering;
  assert.equal(room.seats?.length, 5);
  assert.equal(new Set(room.seats!.map((s) => s.seatX)).size, 5);
  const sprites = h.scene.actors.filter((a) => a.data.ecsChar && a.data.dept === "engineering").map((a) => a.sprite).sort();
  assert.deepEqual(sprites, ["engineering.architect", "engineering.explorer", "engineering.lead", "engineering.manager", "engineering.reviewer"]);
});

test("多角色：同一个部门里至少 4 个角色同时做着不同的任务，事件按角色找到人", () => {
  const h = mountFloor(model());
  h.step(1500);
  const world = h.driver.world;
  h.driver.playEvent(event("x_role_task_assigned", "e-lead", { to: "e-lead", task: "实现" }));
  h.driver.playEvent(event("x_explorer_fetch", "e-exp"));
  h.driver.playEvent(event("x_review_recorded", "e-rev", { verdict: "passed" }));
  h.driver.playEvent(event("model_request_serialized", "e-arch"));
  h.step(600);
  const busy = Object.values(world.characters).filter((c) => c.department === "engineering" && c.current);
  assert.ok(busy.length >= 4, `同时有任务的工程角色 ${busy.length} 个`);
  assert.ok(new Set(busy.map((c) => c.current!.taskKey)).size >= 4);
  assert.equal(world.characters["e-mgr"].current?.taskKey, "x_role_task_assigned");
  assert.equal(world.characters["e-mgr"].current?.withId, "e-lead");
  assert.equal(world.characters["e-exp"].current?.taskKey, "x_explorer_fetch");
  assert.equal(world.characters["e-rev"].current?.taskKey, "x_review_recorded_passed");
  assert.equal(world.characters["e-arch"].current?.taskKey, "model_requested");
});

test("多角色：任务做完以后角色回到工位，队列清空", () => {
  const h = mountFloor(model());
  h.step(1500);
  h.driver.playEvent(event("x_role_result_returned", "e-lead", { to: "e-lead" }));
  h.step(8000);
  for (const ch of Object.values(h.driver.world.characters).filter((c) => c.department === "engineering")) {
    assert.equal(ch.current, null, `${ch.id} 还有正在做的任务`);
    assert.equal(ch.queue.length, 0, `${ch.id} 的队列没有清空`);
  }
});

test("多角色：对外交接由经理做，中心角色不做交接", () => {
  const h = mountFloor(model());
  h.step(1500);
  const world = h.driver.world;
  h.driver.playEvent({ type: "transition", work_item_id: "w1", payload: { from: "engineering", to: "quality", artifact: "box" } });
  h.step(200);
  const mgr = world.characters["e-mgr"];
  const task = mgr.current ?? mgr.queue[0];
  assert.equal(task?.taskKey, "package_handoff_out");
  assert.equal(world.characters["e-arch"].current, null);
  assert.equal(world.characters["e-arch"].queue.length, 0);
});

test("多角色：包裹沿管道到质检，接收方的经理取出来", () => {
  const h = mountFloor(model());
  h.step(1500);
  h.driver.playEvent({ type: "transition", work_item_id: "w1", payload: { from: "engineering", to: "quality", artifact: "box" } });
  let received = false;
  for (let i = 0; i < 160 && !received; i++) {
    h.step(100);
    received = h.driver.world.characters["q-mgr"].current?.taskKey === "package_handoff_in";
  }
  assert.ok(received, "质检的经理没有取包裹");
  h.step(9000);
  assert.equal(Object.keys(h.driver.world.packages).length, 0);
});

test("没有角色设置（低档位）：一个部门一个小人，分派事件不产生任务", () => {
  const h = mountFloor(model({ roles: null }));
  h.step(500);
  assert.deepEqual(Object.keys(h.driver.world.characters).sort(), ["engineering", "product", "quality"]);
  h.driver.playEvent(event("x_role_task_assigned", "e-lead", { to: "e-lead" }));
  h.step(300);
  for (const ch of Object.values(h.driver.world.characters)) {
    assert.equal(ch.current, null);
    assert.equal(ch.queue.length, 0);
  }
});

// ---------------------------------------------------------------------------
// 自主行为

test("自主行为关闭：没有待机活动", () => {
  const h = mountFloor(model({ items: [] }), { autonomy: false });
  h.step(40000);
  const idle = Object.values(h.driver.world.characters).flatMap((c) => [c.current, ...c.queue]).filter((t) => t?.idle);
  assert.equal(idle.length, 0);
});

test("自主行为：空闲的角色自己挑事情做，不止一种，成对说话的两个角色同时出现", () => {
  const h = mountFloor(model({ items: [] }), { autonomy: true });
  const seen: string[] = [];
  const original = h.driver.world.characters;
  void original;
  // 观察队列里出现的待机任务
  for (let i = 0; i < 1200; i++) {
    h.step(100);
    for (const ch of Object.values(h.driver.world.characters)) {
      const t = ch.current;
      if (t?.idle && !seen.includes(t.taskKey)) seen.push(t.taskKey);
    }
  }
  assert.ok(seen.length >= 3, `待机活动种类 ${seen.join(",")}`);
  assert.ok(seen.includes("idle_chat"), `没有出现两个角色碰头说话：${seen.join(",")}`);
});

test("自主行为：真正的任务来了，正在做的待机活动立刻放弃", () => {
  const h = mountFloor(model({ items: [] }), { autonomy: true });
  let victimId: string | null = null;
  for (let i = 0; i < 4000 && !victimId; i++) {
    h.step(100);
    const found = Object.values(h.driver.world.characters).find((c) => c.current?.idle && c.department === "engineering");
    if (found) victimId = found.id;
  }
  assert.ok(victimId, "没有找到正在待机活动中的角色");
  h.driver.playEvent(event("model_request_serialized", victimId!, {}));
  h.step(100);
  assert.equal(h.driver.world.characters[victimId!].current?.taskKey, "model_requested");
});

// ---------------------------------------------------------------------------
// 管道流动

test("管道：有活跃事项时满速流动、光点布满，光点持续向前移动", () => {
  const h = mountFloor(model(), { autonomy: true });
  h.step(2500);
  const link = h.driver.world.links["product>engineering"];
  assert.equal(link.flow!.state, "flowing");
  assert.ok(link.flow!.speed > 0.99, `流速 ${link.flow!.speed}`);
  assert.ok(link.flow!.load > 0.95, `光点 ${link.flow!.load}`);
  const phase = link.flow!.phase;
  h.step(500);
  assert.ok(link.flow!.phase > phase + 400, `相位差 ${link.flow!.phase - phase}`);
});

test("管道：等待模型服务时停下，光点留在管道里，恢复以后继续", () => {
  const h = mountFloor(model(), { autonomy: true });
  h.step(2500);
  const waiting: FloorModel = model({
    items: [item("waiting_provider", "engineering")],
    waiting_provider: [{ department: "engineering", next_retry_at: "2026-09-29T12:00:00+08:00" }],
  });
  h.driver.setModel(waiting);
  h.step(1500);
  const link = h.driver.world.links["product>engineering"];
  assert.equal(link.flow!.state, "stopped");
  assert.ok(link.flow!.speed < 0.05, `流速 ${link.flow!.speed}`);
  assert.ok(link.flow!.load > 0.9, `光点 ${link.flow!.load}`);
  const phase = link.flow!.phase;
  h.step(1000);
  assert.ok(Math.abs(link.flow!.phase - phase) < 1, "停下来以后光点还在移动");
});

test("管道：空闲以后减速，光点淡出", () => {
  const h = mountFloor(model(), { autonomy: true });
  h.step(2500);
  h.driver.setModel(model({ items: [] }));
  h.step(3500);
  const link = h.driver.world.links["product>engineering"];
  assert.equal(link.flow!.state, "idle");
  assert.ok(link.flow!.speed < 0.02, `流速 ${link.flow!.speed}`);
  assert.ok(link.flow!.load < 0.05, `光点 ${link.flow!.load}`);
});

test("管道：关闭自主行为时状态直接对应静止画面（满速或者没有）", () => {
  const h = mountFloor(model(), { autonomy: false });
  h.step(600);
  const link = h.driver.world.links["product>engineering"];
  assert.equal(link.flow!.speed, 1);
  assert.equal(link.flow!.load, 1);
});

// ---------------------------------------------------------------------------
// 声明

test("声明：有运维数据时运维房间出现，去掉声明的运行时判断以后事件没有反应也不出错", () => {
  const h = mountFloor(model({ ops: { version: "r1", fault: false } }));
  h.step(300);
  assert.ok(h.driver.world.roomOrder.includes("operations"));
  h.driver.playEvent({ type: "x_deployed", work_item_id: "w1", payload: { version: "r1", machine_id: "m1" } });
  h.step(200);
  const ops = Object.values(h.driver.world.characters).find((c) => c.department === "operations");
  assert.equal(ops?.current?.taskKey, "x_deployed");
  // 成果库在有运维房间时变窄
  assert.equal(h.driver.world.rooms.library.w, 82);
});

test("声明：没有运维数据时运维房间不出现，运维事件没有反应", () => {
  const h = mountFloor(model());
  h.step(300);
  assert.ok(!h.driver.world.roomOrder.includes("operations"));
  assert.equal(h.driver.world.rooms.library.w, 136);
  h.driver.playEvent({ type: "x_deployed", work_item_id: "w1", payload: { version: "r1" } });
  h.step(300);
  assert.equal(Object.keys(h.driver.world.packages).length, 0);
});

test("声明：运维数据出现时房间重新声明，在途的包裹与原来的角色实体保留", () => {
  const h = mountFloor(model());
  h.step(500);
  h.driver.playEvent({ type: "transition", work_item_id: "w1", payload: { from: "engineering", to: "quality", artifact: "box" } });
  let inFlight = 0;
  for (let i = 0; i < 80 && !inFlight; i++) {
    h.step(100);
    inFlight = Object.keys(h.driver.world.packages).length;
  }
  assert.equal(inFlight, 1);
  const before = h.driver.world.characters["e-mgr"];
  h.driver.setModel(model({ ops: { version: "r1", fault: false } }));
  h.step(100);
  assert.ok(h.driver.world.roomOrder.includes("operations"));
  assert.equal(Object.keys(h.driver.world.packages).length, 1);
  assert.equal(h.driver.world.characters["e-mgr"], before);
});

test("声明：只写声明就加一个新房间与一种任务，新房间按顺序排进去，新任务落在它的小人身上", () => {
  const extra = {
    id: "audit", label: "审计", roomKind: "dept", w: 100, agentKind: "agent", ports: ["in", "out"],
  };
  const rooms = catalog.roomDefs.slice();
  const links = catalog.linkDefs.slice();
  const tasks = { ...catalog.tasks, x_audit_done: { label: "审计完成", spot: "desk" as const, pose: "sit_happy", bubble: "say" as const, ms: 800, dept: "audit" } };
  const local = { ...catalog, roomDefs: rooms, linkDefs: links, tasks };
  rooms.splice(rooms.findIndex((r) => r.id === "library"), 0, extra as never);
  const world = createWorld(local);
  declareRooms(world, local.roomDefs, { ops: false });
  declareLinks(world, local.linkDefs);
  const order = world.roomOrder;
  assert.equal(order.indexOf("audit"), order.indexOf("quality") + 1);
  const list = order.map((id) => world.rooms[id]);
  for (let i = 1; i < list.length; i++) assert.ok(list[i].x >= list[i - 1].x + list[i - 1].w, "新房间与别的房间重叠");
  const scene = createScene({ W: 640, H: 320, random: seeded(), reduced: false });
  scene.autonomy = false;
  syncCharacters(world, scene, [{ id: "audit", department: "audit", roleKind: "agent", name: "审计" }], (s) => `${s.department}.${s.roleKind}`);
  mountMachines(scene, Object.values(world.characters), Object.values(world.links));
  const ch = world.characters["audit"];
  ch.rest = { spot: "desk", pose: "tea" };
  assert.ok(dispatch(world, { type: "x_audit_done", work_item_id: "w1", department: "audit", payload: {} }));
  assert.equal(ch.queue.length + (ch.current ? 1 : 0), 1);
});

// ---------------------------------------------------------------------------
// 路由与几何

test("路由：两个房间之间没有直接管道时沿声明的管道一段一段接起来", () => {
  const world = createWorld(catalog);
  declareRooms(world, catalog.roomDefs, { ops: true });
  declareLinks(world, catalog.linkDefs);
  const direct = route(world, "quality", "library");
  assert.equal(direct.length, 1);
  assert.equal(direct[0].key, "quality>library");
  // 质检放行交给运维：先到成果库再一段
  const hops = route(world, "quality", "operations");
  assert.deepEqual(hops.map((x) => x.key), ["quality>library", "library>operations"]);
});

test("几何：折线长度与沿线取点的端点正确", () => {
  const pts: [number, number][] = [[0, 0], [100, 0], [100, 50]];
  assert.equal(polyLength(pts), 150);
  assert.deepEqual(pointAt(pts, 0), [0, 0]);
  assert.deepEqual(pointAt(pts, 150), [100, 50]);
  assert.deepEqual(pointAt(pts, 100), [100, 0]);
});

// ---------------------------------------------------------------------------
// 说话目录与气泡

test("说话气泡：每个会引起动作的事件类型都在目录里", () => {
  const missing = eventActionTypes.filter((k) => !sayCatalogTypes.includes(k));
  assert.deepEqual(missing, [], `说话目录缺少：${missing.join(",")}`);
});

test("说话气泡：内容来自事件已经带着的事实", () => {
  assert.equal(say({ type: "proposal_submitted", department: "engineering", label: "工程经理代表部门提交交付说明", payload: {} }), "现在提交交付说明");
  assert.equal(say({ type: "proposal_submitted", department: "quality", payload: { kind: "qa_review" } }), "现在提交质检结论");
  assert.equal(say({ type: "tool_started", tool: "edit_range", department: "engineering", label: "工程部门按区间编辑 app.js：导出为 CSV", payload: {} }), "现在编辑 app.js");
  assert.equal(say({ type: "tool_started", tool: "run_command", department: "engineering", label: "工程部门走到终端执行登记命令 npm_test", payload: {} }), "现在执行 npm_test");
  assert.equal(say({ type: "x_role_task_assigned", department: "engineering", payload: { to: "e-lead", task: "起草 PLAN" } }, { dept: "engineering", roleName: () => "主程" }), "现在把任务交给主程：起草 PLAN");
  assert.equal(say({ type: "x_role_task_assigned", department: "engineering", payload: { to: "e-lead", task: "起草 PLAN" } }, { dept: "engineering", side: "to" }), "收到任务：起草 PLAN");
});

test("说话气泡：交接的两端说不同的话", () => {
  const ev: PixelFloorEvent = { type: "transition", payload: { from: "engineering", to: "quality", artifact: "box" } };
  assert.equal(say(ev, { dept: "engineering" }), "现在把交付箱送给质检");
  assert.equal(say(ev, { dept: "quality" }), "收到交付箱，来自工程");
  assert.equal(say(ev, { dept: "quality", side: "to" }), "收到交付箱，来自工程");
});

test("说话气泡：一句话停留的时间读得完，最长 4.6 秒", () => {
  assert.equal(sayMs("短"), 1800 + 170);
  assert.equal(sayMs("很长的句子".repeat(40)), 4600);
});

test("说话气泡：楼层里经理提交交付说明时头顶说这句话，做完以后不再显示", () => {
  const h = mountFloor(model());
  h.step(500);
  h.driver.playEvent({ type: "proposal_submitted", department: "engineering", role: "e-mgr", work_item_id: "w1", label: "工程经理代表部门提交交付说明", payload: {} });
  h.step(100);
  const ch = h.driver.world.characters["e-mgr"];
  assert.deepEqual(ch.bubble, { text: "现在提交交付说明", kind: "say", tail: false });
  h.step(9000);
  assert.equal(ch.current, null);
  assert.equal(h.driver.saidOf("e-mgr", h.scene.realT), null);
});

test("说话气泡：正在做说话任务时头顶是说话气泡，队列里的下一项是思考气泡", () => {
  const world = createWorld(catalog);
  declareRooms(world, catalog.roomDefs, { ops: false });
  declareLinks(world, catalog.linkDefs);
  const scene = createScene({ W: 640, H: 320, random: seeded(), reduced: false });
  syncCharacters(world, scene, [{ id: "engineering", department: "engineering", roleKind: "agent", name: "工程" }], (s) => `${s.department}.${s.roleKind}`);
  mountMachines(scene, Object.values(world.characters), Object.values(world.links));
  const ch = world.characters.engineering;
  // 正在做的说话任务：头顶是说话气泡
  // 任务自己声明的标签没有登记事件时作为气泡内容
  ch.current = enqueue(world, "engineering", "model_requested");
  ch.queue.shift();
  assert.equal(bubbleFor(ch)?.kind, "say");
  assert.equal(bubbleFor(ch)?.text, "打字");
  // 队列里的下一项：思考气泡（正在做的这一项还是优先）
  enqueue(world, "engineering", "x_explorer_fetch");
  assert.equal(bubbleFor(ch)?.kind, "say");
  ch.current = null;
  assert.equal(bubbleFor(ch)?.kind, "think");
  assert.equal(bubbleFor(ch)?.text, "查资料");
});

test("减少动画：小人不走动，交接的两端仍然在原处说话", () => {
  const h = mountFloor(model(), { reduced: true });
  h.step(200);
  const before = { ...h.scene.actors.find((a) => a.id === "ch-e-mgr")! };
  h.driver.playEvent({ type: "transition", work_item_id: "w1", payload: { from: "engineering", to: "quality", artifact: "box" } });
  h.step(200);
  const mgr = h.scene.actors.find((a) => a.id === "ch-e-mgr")!;
  assert.equal(mgr.x, before.x, "减少动画时小人走动了");
  const said = h.driver.saidOf("e-mgr", h.scene.realT);
  assert.equal(said?.text, "现在把交付箱送给质检");
  assert.equal(h.driver.saidOf("q-mgr", h.scene.realT)?.text, "收到交付箱，来自工程");
});

// ---------------------------------------------------------------------------
// 状态机

test("状态机：每个角色与每根管道各有一个，状态随推进改变", () => {
  const h = mountFloor(model());
  h.step(1500);
  const world = h.driver.world;
  assert.equal(h.scene.machines.size, Object.keys(world.characters).length + Object.keys(world.links).length);
  h.driver.playEvent(event("model_request_serialized", "e-arch"));
  h.step(200);
  assert.equal(h.scene.characterState("e-arch")?.state, "working");
  h.step(3000);
  assert.equal(h.scene.characterState("e-arch")?.state, "choosing");
  assert.equal(h.scene.pipeState("product>engineering")?.state, "flowing");
});

test("状态机：整层中断时角色不出发，管道停下", () => {
  const h = mountFloor(model({ interrupted: true }));
  h.step(1000);
  assert.equal(h.scene.frozen, true);
  assert.equal(h.scene.pipeState("product>engineering")?.state, "stopped");
  const before = { ...h.scene.actors.find((a) => a.id === "ch-e-mgr")! };
  h.driver.playEvent({ type: "transition", work_item_id: "w1", payload: { from: "engineering", to: "quality", artifact: "box" } });
  h.step(2000);
  const mgr = h.scene.actors.find((a) => a.id === "ch-e-mgr")!;
  assert.equal(mgr.x, before.x);
});

// ---------------------------------------------------------------------------
// 推进系统的最小接口

test("系统：队列上限保留最多 3 个可以被挤掉的任务，交接的任务放在队首不被挤掉", () => {
  const world = createWorld(catalog);
  declareRooms(world, catalog.roomDefs, { ops: false });
  declareLinks(world, catalog.linkDefs);
  const scene = createScene({ W: 640, H: 320, random: seeded(), reduced: false });
  syncCharacters(world, scene, [{ id: "engineering", department: "engineering", roleKind: "agent", name: "工程" }], (s) => `${s.department}.${s.roleKind}`);
  mountMachines(scene, Object.values(world.characters), Object.values(world.links));
  const ch = world.characters.engineering;
  for (const key of ["model_requested", "context_assembled", "x_explorer_fetch", "x_review_recorded_passed", "compaction_recorded"]) {
    enqueue(world, "engineering", key);
  }
  assert.ok(ch.queue.filter((t) => !t.must).length <= 3, `队列里排了 ${ch.queue.length} 个`);
  // 交接的任务由画面放进队列时标 must 并放队首
  enqueue(world, "engineering", "package_handoff_out", { front: true, must: true });
  assert.equal(ch.queue.filter((t) => t.must).length, 1);
  assert.equal(ch.queue[0].taskKey, "package_handoff_out");
  // 交接的任务不会被队列上限挤掉
  for (const key of ["model_requested", "context_assembled", "x_explorer_fetch", "compaction_recorded"]) enqueue(world, "engineering", key);
  assert.equal(ch.queue[0].taskKey, "package_handoff_out");
  assert.equal(ch.queue.filter((t) => t.must).length, 1);
});

test("系统：包裹沿管道移动，到达终点以后执行回调", () => {
  const world = createWorld(catalog);
  declareRooms(world, catalog.roomDefs, { ops: false });
  declareLinks(world, catalog.linkDefs);
  const scene = createScene({ W: 640, H: 320, random: seeded(), reduced: false });
  const link = world.links["product>engineering"];
  let arrived = false;
  const scene2 = createScene({ W: 640, H: 320, random: seeded(), reduced: false });
  syncCharacters(world, scene2, [{ id: "product", department: "product", roleKind: "agent", name: "产品" }], (s) => `${s.department}.${s.roleKind}`);
  mountMachines(scene2, Object.values(world.characters), Object.values(world.links));
  assert.ok(dispatch(world, { type: "model_requested", department: "product", payload: {} }));
  void stepCharacters;
  const pk = { kind: "package" as const, id: "p1", workItemId: "w1", colorIndex: 0, artifact: "box", atRest: null, transit: { linkKey: link.id, pts: link.pts, t0: null, k: 0, ms: 700, onDone: () => { arrived = true; } } };
  world.packages["p1"] = pk;
  for (let i = 0; i < 40 && !arrived; i++) {
    scene.stepScene(50);
    stepPackages(world, scene);
  }
  assert.ok(arrived);
  assert.equal(world.packages["p1"].transit, null);
});

test("系统：管道的流动由 stateOf 决定，停止以后光点留在原地", () => {
  const world = createWorld(catalog);
  declareRooms(world, catalog.roomDefs, { ops: false });
  declareLinks(world, catalog.linkDefs);
  const scene = createScene({ W: 640, H: 320, random: seeded(), reduced: false });
  scene.autonomy = true;
  let state: "flowing" | "idle" | "stopped" = "flowing";
  for (let i = 0; i < 60; i++) {
    stepPipes(world, scene, () => state);
    scene.stepScene(50);
  }
  const pipe = world.links["product>engineering"];
  assert.ok(pipe.flow!.phase > 0);
  state = "stopped";
  for (let i = 0; i < 40; i++) {
    stepPipes(world, scene, () => state);
    scene.stepScene(50);
  }
  const phase = pipe.flow!.phase;
  for (let i = 0; i < 40; i++) {
    stepPipes(world, scene, () => state);
    scene.stepScene(50);
  }
  assert.ok(Math.abs(pipe.flow!.phase - phase) < 1, "停下的管道里光点还在移动");
});
