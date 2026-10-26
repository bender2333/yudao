// 楼层画面的行为测试（工单 #82、#953）：把原型 v13 checks/behaviors.js 与 checks/playback.js 里
// 关于项目楼层的检查改写为对客户端的测试，直接对世界、系统与播放时间线运行，用确定的时钟与手写的数据。
//
// 覆盖：多角色（角色实体、工位、同时做不同的任务、动作按角色找人、交接由经理做、没有角色设置时一个部门一个小人）、
// 自主行为、管道流动、包裹沿管道走、运维数据出现时世界重新声明、状态机、决定单与大厅的板、
// 画面合同接线后的四条行为（交付箱还在管道里走时质检不提前显示收到、PRD 被接纳盖有效章加交接、
// 进行中的事项进房间、决定单一到就贴在大厅的板上）、跳到最新不补播、以及画面层的导入方向。
//
// 事件 → 动作的翻译由 translate/floor.ts 负责，它的测试在 translate-floor.test.ts；这里只用它翻好的动作。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

import { buildCatalog, sayCatalogTypes } from "../../src/renderer/src/pixel/world/floor-decl.ts";
import { declareLinks, declareRooms, createWorld, polyLength, pointAt, route } from "../../src/renderer/src/pixel/world/declare.ts";
import { bubbleFor, dispatch, dropAction, enqueue, stepCharacters, stepPackages, stepPipes } from "../../src/renderer/src/pixel/world/characters.ts";
import { mountMachines, syncCharacters } from "../../src/renderer/src/pixel/world/scene.ts";
import { ACTIVE, IN_ROOM, createFloorDriver, createFloorState, itemColor, visibleDecisions } from "../../src/renderer/src/pixel/world/floor.ts";
import { createScene } from "../../src/renderer/src/pixel/world/scene.ts";
import type { DecisionFace, FloorModel, LoopItem, RoleInfo, Task } from "../../src/renderer/src/pixel/world/types.ts";
import type { PixelAction } from "../../src/renderer/src/pixel/contract.ts";
import { COVERAGE } from "../../src/renderer/src/translate/coverage.ts";
import { floorActions, type FloorEvent } from "../../src/renderer/src/translate/floor.ts";
import { say } from "../../src/renderer/src/translate/say.ts";

// ---------------------------------------------------------------------------
// 确定时钟与手写数据

function seeded(): () => number {
  let seed = 246813579;
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

// 世界与系统不需要画布，因此目录不带房间的陈设画法（渲染层在 floor-view 里合成）
const catalog = buildCatalog({});

const TIME = { clock: (iso: string | null) => iso ?? "", duration: (sec: number) => String(sec) };

const ROLE = (id: string, kind: string, name: string, status: string = "idle"): RoleInfo => ({
  id, kind, name, status: status as RoleInfo["status"], task: null,
});

const ROLES: Record<string, RoleInfo[]> = {
  product: [ROLE("p-mgr", "manager", "产品部门经理"), ROLE("p-arch", "architect", "产品架构师", "working"), ROLE("p-exp", "explorer", "产品探索者"), ROLE("p-rev", "reviewer", "产品审查者")],
  engineering: [ROLE("e-mgr", "manager", "工程经理"), ROLE("e-arch", "architect", "工程架构师", "working"), ROLE("e-lead", "lead", "主程"), ROLE("e-exp", "explorer", "工程探索者"), ROLE("e-rev", "reviewer", "工程审查者")],
  quality: [ROLE("q-mgr", "manager", "质检经理"), ROLE("q-test", "tester", "测试工程师", "working"), ROLE("q-exp", "explorer", "质检探索者"), ROLE("q-rev", "reviewer", "质检审查者")],
};

const item = (status: LoopItem["status"], department: string | null): LoopItem => ({
  id: "w1", work_item_id: "w1", kind: "request", sign: "测试事项", color_index: 0, status, department, round: 1,
  elapsed_sec: 100, time_limit_sec: 7200, started_at: null,
});

/** 一份楼层状态：位置 0，事项与角色按参数。 */
function model(over: Partial<FloorModel> = {}): FloorModel {
  return {
    position: 0,
    items: [item("working", "engineering")], open_requests: [], shelves: { adopted: [] }, slots: { total: 3, used: 1 },
    waiting_provider: [], machines: null, ops: null, interrupted: false, roles: ROLES, decisions: [], ...over,
  };
}

/** 一个画面合同的动作：位置按调用顺序递增，`say` 是做事的一方说的话。 */
let seq = 0;
const act = (kind: string, extra: Partial<PixelAction> = {}): PixelAction => ({ kind, position: ++seq, ...extra });

interface Harness {
  driver: ReturnType<typeof createFloorDriver>;
  step: (ms: number) => void;
  scene: ReturnType<typeof createScene>;
  /** 一帧一帧推进，直到条件成立（最多 maxMs 毫秒）。 */
  until: (check: () => boolean, maxMs?: number) => boolean;
}

function mountFloor(m: FloorModel, opts: { autonomy?: boolean; reduced?: boolean } = {}): Harness {
  const scene = createScene({ W: 640, H: 320, random: seeded(), reduced: opts.reduced ?? false });
  scene.autonomy = opts.autonomy ?? false;
  const driver = createFloorDriver({ model: m, scene, state: createFloorState(), catalog, W: 640, H: 320, time: TIME });
  const frame = (): void => {
    scene.stepScene(50);
    driver.step();
  };
  const step = (ms: number): void => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) frame();
  };
  const until = (check: () => boolean, maxMs = 20000): boolean => {
    for (let waited = 0; waited <= maxMs; waited += 50) {
      if (check()) return true;
      frame();
    }
    return check();
  };
  return { driver, step, scene, until };
}

const roleTask = (h: Harness, id: string): Task | null => {
  const ch = h.driver.world.characters[id];
  return ch ? ch.current ?? ch.queue[0] ?? null : null;
};

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

test("多角色：同一个部门里至少 4 个角色同时做着不同的事，动作按角色找到人", () => {
  const h = mountFloor(model());
  h.step(1500);
  h.driver.play(act("assign", { room: "engineering", role: "e-lead", item: "w1", say: "现在把任务交给主程" }));
  h.driver.play(act("explore", { room: "engineering", role: "e-exp" }));
  h.driver.play(act("review_pass", { room: "engineering", role: "e-rev" }));
  h.driver.play(act("think", { room: "engineering", role: "e-arch" }));
  h.step(600);
  const world = h.driver.world;
  const busy = Object.values(world.characters).filter((c) => c.department === "engineering" && (c.current || c.progress));
  assert.ok(busy.length >= 4, `同时有事的工程角色 ${busy.length} 个`);
  assert.equal(world.characters["e-mgr"].current?.taskKey, "assign");
  assert.equal(world.characters["e-mgr"].current?.withId, "e-lead");
  assert.equal(world.characters["e-exp"].current?.taskKey, "explore");
  assert.equal(world.characters["e-rev"].current?.taskKey, "review_pass");
  // 思考是进度一级：不排队，合并成坐在桌前的持续姿势
  assert.equal(world.characters["e-arch"].current, null);
  assert.equal(world.characters["e-arch"].progress?.taskKey, "think");
});

test("多角色：任务做完以后角色回到工位，队列清空", () => {
  const h = mountFloor(model());
  h.step(1500);
  h.driver.play(act("review_pass", { room: "engineering", role: "e-rev" }));
  h.step(9000);
  for (const ch of Object.values(h.driver.world.characters).filter((c) => c.department === "engineering")) {
    assert.equal(ch.current, null, `${ch.id} 还有正在做的任务`);
    assert.equal(ch.queue.length, 0, `${ch.id} 的队列没有清空`);
  }
});

test("多角色：对外交接由经理做，中心角色不做交接", () => {
  const h = mountFloor(model());
  h.step(1500);
  h.driver.play(act("handoff", { item: "w1", from: "engineering", to: "quality", artifact: "box", say: "现在把交付箱送给质检", sayTo: "收到交付箱，来自工程" }));
  h.step(200);
  assert.equal(roleTask(h, "e-mgr")?.taskKey, "package_handoff_out");
  assert.equal(h.driver.world.characters["e-arch"].current, null);
  assert.equal(h.driver.world.characters["e-arch"].queue.length, 0);
});

test("多角色：包裹沿管道到质检，接收方的经理取出来", () => {
  const h = mountFloor(model());
  h.step(1500);
  h.driver.play(act("handoff", { item: "w1", from: "engineering", to: "quality", artifact: "box" }));
  const received = h.until(() => h.driver.world.characters["q-mgr"].current?.taskKey === "package_handoff_in");
  assert.ok(received, "质检的经理没有取包裹");
  h.step(9000);
  assert.equal(Object.keys(h.driver.world.packages).length, 0);
});

test("没有角色设置（低档位）：一个部门一个小人，分派动作不产生任务", () => {
  const h = mountFloor(model({ roles: null }));
  h.step(500);
  assert.deepEqual(Object.keys(h.driver.world.characters).sort(), ["engineering", "product", "quality"]);
  h.driver.play(act("assign", { room: "engineering", role: "e-lead" }));
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

test("自主行为：真正的动作来了，正在做的待机活动立刻放弃", () => {
  const h = mountFloor(model({ items: [] }), { autonomy: true });
  let victimId: string | null = null;
  for (let i = 0; i < 4000 && !victimId; i++) {
    h.step(100);
    const found = Object.values(h.driver.world.characters).find((c) => c.current?.idle && c.department === "engineering");
    if (found) victimId = found.id;
  }
  assert.ok(victimId, "没有找到正在待机活动中的角色");
  h.driver.play(act("think", { room: "engineering", role: victimId! }));
  h.step(100);
  assert.equal(h.driver.world.characters[victimId!].progress?.taskKey, "think");
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
    items: [item("waiting_model", "engineering")],
    waiting_provider: [{ department: "engineering", retry_text: "12:30 重试" }],
  });
  h.driver.jump(waiting);
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
  h.driver.jump(model({ items: [] }));
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

test("声明：有运维数据时运维房间出现，运维的发布动作由运维的小人做", () => {
  const h = mountFloor(model({ ops: { version: "r1", fault: false } }));
  h.step(300);
  assert.ok(h.driver.world.roomOrder.includes("operations"));
  h.driver.play(act("deploy", { item: "w1" }));
  h.step(200);
  const ops = Object.values(h.driver.world.characters).find((c) => c.department === "operations");
  assert.equal(ops?.current?.taskKey, "deploy");
  // 成果库在有运维房间时变窄
  assert.equal(h.driver.world.rooms.library.w, 82);
});

test("声明：没有运维数据时运维房间不出现，运维动作没有反应", () => {
  const h = mountFloor(model());
  h.step(300);
  assert.ok(!h.driver.world.roomOrder.includes("operations"));
  assert.equal(h.driver.world.rooms.library.w, 136);
  h.driver.play(act("deploy", { item: "w1" }));
  h.step(300);
  assert.equal(Object.keys(h.driver.world.packages).length, 0);
});

test("声明：运维数据出现时房间重新声明，在途的包裹与原来的角色实体保留", () => {
  const h = mountFloor(model());
  h.step(500);
  h.driver.play(act("handoff", { item: "w1", from: "engineering", to: "quality", artifact: "box" }));
  const inFlight = h.until(() => Object.keys(h.driver.world.packages).length > 0);
  assert.ok(inFlight);
  const before = h.driver.world.characters["e-mgr"];
  h.driver.jump(model({ ops: { version: "r1", fault: false }, position: 999 }));
  h.step(100);
  assert.ok(h.driver.world.roomOrder.includes("operations"));
  assert.equal(h.driver.world.characters["e-mgr"], before);
});

test("声明：只写声明就加一个新房间与一种任务，新房间按顺序排进去，新任务落在它的小人身上", () => {
  const extra = {
    id: "audit", label: "审计", roomKind: "dept", w: 100, agentKind: "agent", ports: ["in", "out"],
  };
  const rooms = catalog.roomDefs.slice();
  const links = catalog.linkDefs.slice();
  const tasks = { ...catalog.tasks, audit_done: { label: "审计完成", spot: "desk" as const, pose: "sit_happy", bubble: "say" as const, ms: 800, dept: "audit" } };
  const kinds = { ...catalog.kinds, audit_done: { tier: "normal" as const, ms: 800 } };
  const local = { ...catalog, roomDefs: rooms, linkDefs: links, tasks, kinds };
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
  assert.ok(dispatch(world, { kind: "audit_done", position: 1 }));
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
// 说话气泡（楼层的动作带着翻译层写好的话）

// 原型 v13 checks/behaviors.js 同一条检查：翻译层在楼层翻出的每种动作，事件都有一句话（目录里有，或者取事件说明）。
// 不说话的几类由翻译层单独写或没有小人说话：包裹与邮件（只飞一张纸）、成果库的采纳、询问与回答（sayAsk、sayAnswer）、流式文字。
// 真实系统里新增的几种事件（原型里是 x_ 开头的名字）由翻译层按事件说明写话（translate/say.ts 的 fromLabel）。
const SILENT = ["model_stream_progress", "structure_accepted", "ask_started", "ask_answered",
  "user_input_received", "work_item_created", "deliverable_adopted", "baseline_adopted",
  "run_resumed", "run_continued", "product_decision_accepted", "decision_requested", "decision_answered"];
test("说话气泡：楼层翻成动作的事件都在说话目录里（不说话的几类除外）", () => {
  const missing = COVERAGE.floor.drawn.filter((k) => !SILENT.includes(k) && !sayCatalogTypes.includes(k));
  assert.deepEqual(missing, [], `说话目录缺少：${missing.join(",")}`);
});

test("说话气泡：楼层里经理提交交付说明时头顶说翻译层写好的话，做完以后不再显示", () => {
  const h = mountFloor(model());
  h.step(500);
  h.driver.play(act("submit", { room: "engineering", role: "e-mgr", item: "w1", say: say({ type: "proposal_submitted", department: "engineering", label: "工程经理代表部门提交交付说明", payload: {} }) ?? undefined }));
  h.step(100);
  const ch = h.driver.world.characters["e-mgr"];
  assert.equal(ch.bubble?.text, "现在提交交付说明");
  assert.equal(ch.bubble?.kind, "say");
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
  // 正在做的说话任务：头顶是说话气泡（任务声明里的话）
  ch.current = enqueue(world, "engineering", "think");
  ch.queue.shift();
  assert.equal(bubbleFor(ch)?.kind, "say");
  assert.equal(bubbleFor(ch)?.text, "打字");
  // 队列里的下一项：思考气泡（正在做的这一项还是优先）
  enqueue(world, "engineering", "explore");
  assert.equal(bubbleFor(ch)?.kind, "say");
  ch.current = null;
  assert.equal(bubbleFor(ch)?.kind, "think");
  assert.equal(bubbleFor(ch)?.text, "查资料");
});

test("减少动画：小人不走动，交接的两端仍然在原处说翻译层写好的话", () => {
  const h = mountFloor(model(), { reduced: true });
  h.step(200);
  const before = { ...h.scene.actors.find((a) => a.id === "ch-e-mgr")! };
  h.driver.play(act("handoff", { item: "w1", from: "engineering", to: "quality", artifact: "box", say: "现在把交付箱送给质检", sayTo: "收到交付箱，来自工程" }));
  h.step(200);
  const mgr = h.scene.actors.find((a) => a.id === "ch-e-mgr")!;
  assert.equal(mgr.x, before.x, "减少动画时小人走动了");
  assert.equal(h.driver.saidOf("e-mgr", h.scene.realT)?.text, "现在把交付箱送给质检");
  assert.equal(h.driver.saidOf("q-mgr", h.scene.realT)?.text, "收到交付箱，来自工程");
});

// ---------------------------------------------------------------------------
// 状态机

test("状态机：每个角色与每根管道各有一个，状态随推进改变", () => {
  const h = mountFloor(model());
  h.step(1500);
  const world = h.driver.world;
  assert.equal(h.scene.machines.size, Object.keys(world.characters).length + Object.keys(world.links).length);
  h.driver.play(act("explore", { room: "engineering", role: "e-arch" }));
  assert.ok(h.until(() => h.scene.characterState("e-arch")?.state === "working"), "角色没有进入工作状态");
  assert.ok(h.until(() => h.scene.characterState("e-arch")?.state === "choosing", 15000), "角色没有回到挑下一件事的状态");
  assert.equal(h.scene.pipeState("product>engineering")?.state, "flowing");
});

test("状态机：整层中断时角色不出发，管道停下", () => {
  const h = mountFloor(model({ interrupted: true }));
  h.step(1000);
  assert.equal(h.scene.frozen, true);
  assert.equal(h.scene.pipeState("product>engineering")?.state, "stopped");
  const before = { ...h.scene.actors.find((a) => a.id === "ch-e-mgr")! };
  h.driver.play(act("handoff", { item: "w1", from: "engineering", to: "quality", artifact: "box" }));
  h.step(2000);
  const mgr = h.scene.actors.find((a) => a.id === "ch-e-mgr")!;
  assert.equal(mgr.x, before.x);
});

// ---------------------------------------------------------------------------
// 推进系统的最小接口

test("系统：角色的队列不设上限，排队与丢弃交给播放时间线（工单 #953）", () => {
  const world = createWorld(catalog);
  declareRooms(world, catalog.roomDefs, { ops: false });
  declareLinks(world, catalog.linkDefs);
  const scene = createScene({ W: 640, H: 320, random: seeded(), reduced: false });
  syncCharacters(world, scene, [{ id: "engineering", department: "engineering", roleKind: "agent", name: "工程" }], (s) => `${s.department}.${s.roleKind}`);
  mountMachines(scene, Object.values(world.characters), Object.values(world.links));
  const ch = world.characters.engineering;
  for (const key of ["think", "gather", "explore", "review_pass", "compact"]) {
    enqueue(world, "engineering", key);
  }
  // 队列原样收下：上限与丢弃属于播放时间线，不属于世界
  assert.equal(ch.queue.length, 5, `队列里排了 ${ch.queue.length} 个`);
  // 时间线立刻结束一个动作时，按 actionId 把它的步骤清掉
  enqueue(world, "engineering", "explore", { actionId: 7 });
  assert.equal(ch.queue.filter((t) => t.actionId === 7).length, 1);
  dropAction(world, 7);
  assert.equal(ch.queue.filter((t) => t.actionId === 7).length, 0);
});

test("系统：包裹沿管道移动，到达终点以后执行回调", () => {
  const world = createWorld(catalog);
  declareRooms(world, catalog.roomDefs, { ops: false });
  declareLinks(world, catalog.linkDefs);
  const scene2 = createScene({ W: 640, H: 320, random: seeded(), reduced: false });
  const link = world.links["product>engineering"];
  let arrived = false;
  syncCharacters(world, scene2, [{ id: "product", department: "product", roleKind: "agent", name: "产品" }], (s) => `${s.department}.${s.roleKind}`);
  mountMachines(scene2, Object.values(world.characters), Object.values(world.links));
  const pk = { kind: "package" as const, id: "p1", workItemId: "w1", colorIndex: 0, artifact: "box", atRest: null, transit: { linkKey: link.id, pts: link.pts, t0: null, k: 0, ms: 700, onDone: () => { arrived = true; } } };
  world.packages["p1"] = pk;
  for (let i = 0; i < 40 && !arrived; i++) {
    scene2.stepScene(50);
    stepPackages(world, scene2);
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
  void stepCharacters;
});

// ---------------------------------------------------------------------------
// 决定单与大厅的板（工单 #179、#953）

const decisionFace = (id: string): DecisionFace => ({
  id, kind: "model_unavailable", version: 3, title: "模型引用无法使用", work_item_id: "w1", where: "项目 · 测试事项",
  waited: "已等待 1 分", blocks: "不挡住事项", rows: [{ term: "部门", value: "工程" }], links: [],
  options: [{ id: "continue", label: "继续执行" }],
});

test("决定单：一到大就把大厅的板贴上，不用等送出动作飞到（工单 #953）", () => {
  const h = mountFloor(model());
  h.step(300);
  h.driver.setDecisions([decisionFace("d1")]);
  const board = visibleDecisions(h.driver.model.decisions, h.driver.state.hidden, h.scene.realT);
  assert.equal(board.length, 1, "决定单一到就该贴在板上");
  // 送出的动作只演「送去」这一段，不再把板上的单子藏起来
  h.driver.play(act("decision_out", { room: "engineering", item: "w1", decision: "d1" }));
  h.step(200);
  assert.equal(h.driver.decisionHidden("d1", h.scene.realT), false);
  assert.equal(visibleDecisions(h.driver.model.decisions, h.driver.state.hidden, h.scene.realT).length, 1);
});

test("决定单：提出决定的部门的经理走到门口送单，决定单飞向大厅的板", () => {
  const h = mountFloor(model());
  h.step(300);
  h.driver.setDecisions([decisionFace("d1")]);
  const board = h.driver.boardRect();
  h.driver.play(act("decision_out", { room: "engineering", item: "w1", decision: "d1", say: "现在送出决定单" }));
  h.step(200);
  const post = roleTask(h, "e-mgr");
  assert.equal(post?.taskKey, "decision_give");
  assert.equal(post?.spot, "door");
  const flying = h.until(() => h.scene.flyers.length > 0);
  assert.ok(flying, "送单动作收尾以后决定单没有飞向板");
  assert.equal(h.scene.flyers[0].bmp, "decision");
  assert.deepEqual(h.scene.flyers[0].to, [board.x + board.w / 2, board.y + board.h / 2]);
  h.step(3000);
  assert.equal(h.scene.flyers.length, 0);
});

test("决定单：回答到达时正在展开的那张纸盖章，决定单从板上飞回提出决定的部门的门口", () => {
  const h = mountFloor(model());
  h.step(300);
  h.driver.setDecisions([decisionFace("d2")]);
  const stamped: { id: string; text: string }[] = [];
  h.scene.cardStamped = (id, text) => stamped.push({ id, text });
  h.driver.play(act("decision_back", { room: "engineering", item: "w1", decision: "d2", say: "收到你的回答" }));
  h.step(100);
  assert.deepEqual(stamped, [{ id: "d2", text: "已回答" }]);
  assert.equal(h.scene.flyers.length, 1);
  assert.equal(h.scene.flyers[0].bmp, "decision");
  // 飞回提出决定的部门的门口：终点是部门房间的门
  const room = h.driver.world.rooms.engineering;
  assert.equal(h.scene.flyers[0].to[0], room.door);
  const take = h.until(() => roleTask(h, "e-mgr")?.taskKey === "decision_take");
  assert.ok(take, "到达以后经理在门口收下");
});

test("决定单：没有部门的决定请求从大厅上方飞进来", () => {
  const h = mountFloor(model());
  h.step(300);
  h.driver.setDecisions([decisionFace("d3")]);
  h.driver.play(act("decision_out", { item: "w1", decision: "d3" }));
  const flying = h.until(() => h.scene.flyers.length > 0);
  assert.ok(flying);
  const board = h.driver.boardRect();
  assert.equal(h.scene.flyers[0].from[0], board.x + board.w / 2);
  assert.ok(h.scene.flyers[0].from[1] < board.y);
});

// ---------------------------------------------------------------------------
// 画面合同接线以后的行为（工单 #953 验收标准 1）

/** 一条楼层的样例事件（位置按调用顺序递增）。 */
const event = (type: string, extra: Partial<FloorEvent> = {}): FloorEvent => ({
  type, position: ++seq, work_item_id: "w1", department: "engineering", payload: {}, ...extra,
});

test("交付箱还在管道里走时，质检房间不提前显示收到（状态等动作）", () => {
  const h = mountFloor(model());
  h.step(1500);
  const [seal, transfer] = floorActions(event("delivery_accepted", { department: "engineering" }));
  assert.equal(seal.kind, "seal");
  assert.equal(transfer.kind, "handoff");
  h.driver.play(seal);
  h.driver.play(transfer);
  // 交接的包裹已经在管道里走
  const inTransit = h.until(() => Object.values(h.driver.world.packages).some((pk) => pk.transit));
  assert.ok(inTransit, "包裹没有进管道");
  // 新状态（事项到了质检）到达：位置比交接动作大，但动作还在演，状态不上画面
  h.driver.setState({ ...model(), position: transfer.position, items: [item("working", "quality")] });
  h.step(300);
  assert.equal(h.driver.model.items[0].department, "engineering", "动作还在演，状态就上了画面");
  assert.ok(h.driver.inspectTimeline().pending >= 1, "状态应当排着等动作演完");
  // 交接演完以后状态才上画面：质检的房间这时才显示收到
  const arrived = h.until(() => h.driver.model.items[0].department === "quality", 30000);
  assert.ok(arrived, "交接演完以后状态没有上画面");
});

test("PRD 被接纳翻成盖有效章加交接", () => {
  const h = mountFloor(model());
  h.step(1500);
  const actions = floorActions(event("spec_accepted", { department: "product" }));
  assert.deepEqual(actions.map((a) => a.kind), ["stamp_valid", "handoff"]);
  const transfer = actions[1];
  assert.equal(transfer.from, "product");
  assert.equal(transfer.to, "engineering");
  assert.equal(transfer.artifact, "prd");
  for (const action of actions) h.driver.play(action);
  h.step(300);
  assert.equal(roleTask(h, "p-arch")?.taskKey, "stamp_valid");
  // 包裹从产品送往工程：产品与工程的经理各有一段
  assert.equal(roleTask(h, "p-mgr")?.taskKey, "package_handoff_out");
  const arrived = h.until(() => roleTask(h, "e-mgr")?.taskKey === "package_handoff_in", 30000);
  assert.ok(arrived, "工程没有收到 PRD");
});

test("进行中的事项（服务端 in_progress 翻成 working）进房间、亮灯", () => {
  const h = mountFloor(model({ items: [item("working", "engineering")] }));
  h.step(1500);
  assert.ok(IN_ROOM.includes("working"), "working 不在房间里的状态里");
  assert.ok(ACTIVE.includes("working"), "working 不算活跃");
  const engineer = Object.values(h.driver.world.characters).filter((c) => c.department === "engineering");
  assert.ok(engineer.some((c) => c.item?.status === "working"), "进行中的事项没有进房间");
  const link = h.driver.world.links["product>engineering"];
  assert.equal(link.flow!.state, "flowing", "进行中的事项没有让管道流动");
  // 房间的屏幕在打字（ACTIVE 的取值经渲染层的 deskMode 读）
  assert.equal(engineer.find((c) => c.item)?.item?.status, "working");
});

test("跳到最新：打开、重新同步与回放拖动直接显示最新状态，不补播", () => {
  const h = mountFloor(model());
  h.step(1500);
  // 排一个要演一会儿的动作
  h.driver.play(act("handoff", { item: "w1", from: "engineering", to: "quality", artifact: "box" }));
  h.step(200);
  assert.ok(h.driver.inspectTimeline().playing.length > 0, "动作没有在演");
  // 跳到最新（打开画面、重新同步、标签页切回、回放拖动都走这里）
  h.driver.jump({ ...model(), position: 10000, items: [item("done", "quality")] });
  assert.equal(h.driver.inspectTimeline().playing.length, 0, "跳到最新以后还有动作在演");
  assert.equal(h.driver.inspectTimeline().pending, 0, "跳到最新以后还有状态排着");
  assert.equal(h.driver.model.position, 10000);
  assert.equal(h.driver.model.items[0].status, "done");
  // 不补播：跳过去以后没有新的动作开始
  const started = h.driver.inspectTimeline().stats.started;
  h.step(1000);
  assert.equal(h.driver.inspectTimeline().stats.started, started, "跳到最新以后补播了动作");
});

test("状态的取值按画面合同校验：服务端的说法（running）进不了画面", () => {
  const h = mountFloor(model());
  assert.throws(
    () => h.driver.setState({ ...model(), position: 5, items: [{ ...item("done", "quality"), status: "running" as never }] }),
    /画面合同/,
  );
});

test("事项的颜色按色板取，色板之外不越界", () => {
  assert.equal(itemColor({ color_index: 0 }), "#d9534f");
  assert.equal(itemColor({ color_index: 7 }), "#4a90d9");
});

// ---------------------------------------------------------------------------
// 导入方向（验收标准 4：pixel/floor 与 pixel/world 不导入 views/、api/、contract/）

/** 一个文件里的导入语句（from 的那一截与 import "x" 两种写法）。 */
function importPaths(code: string): string[] {
  const paths: string[] = [];
  for (const m of code.matchAll(/(?:^|\n)\s*(?:import|export)[^;\n]*?from\s+["']([^"']+)["']/g)) paths.push(m[1]);
  for (const m of code.matchAll(/(?:^|\n)\s*import\s+["']([^"']+)["']/g)) paths.push(m[1]);
  return paths;
}

test("导入：画面层（pixel/floor 与 pixel/world）不导入 views/、api/ 与 contract/", () => {
  const pixel = new URL("../../src/renderer/src/pixel/", import.meta.url);
  const offenders: string[] = [];
  for (const dir of ["floor", "world"]) {
    const base = new URL(dir + "/", pixel);
    for (const entry of readdirSync(base, { withFileTypes: true })) {
      if (!entry.isFile() || !/\.(ts|tsx)$/.test(entry.name)) continue;
      for (const path of importPaths(readFileSync(new URL(entry.name, base), "utf8"))) {
        if (/(^|\/)(views|api|contract)\//.test(path)) offenders.push(`${dir}/${entry.name} → ${path}`);
      }
    }
  }
  assert.deepEqual(offenders, [], `画面层不许导入页面、接口与命令接口：\n${offenders.join("\n")}`);
});
