// 部门房间的行为测试（工单 #177 验收标准 1）：把原型 checks/behaviors.js 里关于部门房间的检查
// 改写为对客户端的测试，直接对房间驱动与场景运行，用确定的时钟与手写的数据。
//
// 覆盖：角色与工位、持续状态、事件按角色找到人、交接与传信的两端各说一句、
// 收到询问的一方走到传信管口取信、模型请求时只有思考气泡、说话气泡停留与消失、
// 减少动画时照样说话、事件到动作的解析与说话目录。

import { test } from "node:test";
import assert from "node:assert/strict";

import { createRoomDriver } from "../../src/renderer/src/pixel/room/driver.ts";
import { emptyRoomModel, letterSides, quoted } from "../../src/renderer/src/pixel/room/room.ts";
import { collaborationSides, layoutDesks, poseAnim, resolveAction, spriteForRole, toolSpot } from "../../src/renderer/src/pixel/room/decl.ts";
import { say, sayMs } from "../../src/renderer/src/pixel/world/say.ts";
import { eventActionTypes, sayCatalogTypes } from "../../src/renderer/src/pixel/world/floor-decl.ts";
import type { RoomModel } from "../../src/renderer/src/pixel/room/room.ts";
import type { RoomRole } from "../../src/renderer/src/pixel/room/layout.ts";
import type { PixelFloorEvent } from "../../src/renderer/src/pixel/world/types.ts";

function seeded(): () => number {
  let seed = 246813579;
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

function role(id: string, kind: string, name: string, status = "idle"): RoomRole {
  return { id, kind, name, status, task: null };
}

interface RoomHarness {
  driver: ReturnType<typeof createRoomDriver>;
  step: (ms: number) => void;
  actor: (id: string) => ReturnType<ReturnType<typeof createRoomDriver>["actorById"]>;
}

function mountRoom(department: string, roles: RoomRole[], over: Partial<RoomModel> = {}, reduced = false): RoomHarness {
  const driver = createRoomDriver({ department, sceneOptions: { W: 480, H: 240, random: seeded(), reduced } });
  const model = { ...emptyRoomModel(department), status: "working", roles, ...over };
  driver.setModel(model);
  const step = (ms: number): void => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) {
      driver.scene.stepScene(50);
      driver.step();
    }
  };
  return { driver, step, actor: (id) => driver.actorById(id) };
}

const ENG = [role("eng-manager", "manager", "工程经理"), role("eng-architect", "architect", "工程架构师", "working"), role("eng-lead", "lead", "主程")];
const PRO = [role("p-mgr", "manager", "产品部门经理"), role("p-arch", "architect", "产品架构师", "working")];
const QUA = [role("q-mgr", "manager", "质检经理"), role("q-test", "tester", "测试工程师", "working")];

// ---------------------------------------------------------------------------
// 角色与工位

test("房间：角色按种类取精灵，工位各不相同", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  assert.equal(h.driver.actors().length, 3);
  assert.equal(spriteForRole("engineering", "architect"), "engineering.architect");
  assert.equal(spriteForRole("operations", "agent"), "operations.ops");
  const seatX = h.driver.actors().map((a) => a.desk.seatX);
  assert.equal(new Set(seatX).size, 3);
  // Stage 5 的排布：中心角色在中间，经理靠右墙
  const lay = layoutDesks("engineering", ENG, "S5");
  assert.ok(lay[1].x < lay[0].x, "经理应在中心角色右侧");
});

test("房间：中心角色的动作姿势按 roomModel.pose 摆放，无法对应时抛出错误", () => {
  const h = mountRoom("engineering", ENG, { pose: { role_id: "eng-architect", action: "typing" } });
  h.step(1500);
  assert.equal(poseAnim("typing"), "type");
  assert.throws(() => poseAnim("不存在的动作"), /无法对应到动作/);
});

test("房间：工具种类对应房间里的位置", () => {
  assert.equal(toolSpot("run_command"), "terminal");
  assert.equal(toolSpot("search"), "cabinet");
  assert.equal(toolSpot("run_check"), "bench");
  assert.equal(toolSpot("edit_range"), "desk");
});

// ---------------------------------------------------------------------------
// 说话气泡（部门房间）

test("说话气泡：目录里每个会引起动作的事件类型都在说话目录里", () => {
  const missing = eventActionTypes.filter((k) => !sayCatalogTypes.includes(k));
  assert.deepEqual(missing, [], `说话目录缺少：${missing.join(",")}`);
});

test("说话气泡：经理提交交付说明，头顶说「现在提交交付说明」，过几秒消失", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  h.driver.playEvent({ type: "proposal_submitted", department: "engineering", role: "eng-manager", work_item_id: "w1", label: "工程经理代表部门提交交付说明", payload: {} });
  h.step(1200);
  assert.equal(h.actor("eng-manager")?.say?.text, "现在提交交付说明");
  const until = h.actor("eng-manager")?.say?.until ?? 0;
  h.step(7000);
  assert.ok((h.actor("eng-manager")?.say?.until ?? 0) < h.driver.scene.realT, `气泡应在 ${until} 毫秒后不再显示`);
});

test("说话气泡：减少动画时照样说话", () => {
  const h = mountRoom("engineering", ENG, {}, true);
  h.step(200);
  h.driver.playEvent({ type: "proposal_submitted", department: "engineering", role: "eng-manager", work_item_id: "w1", label: "工程经理代表部门提交交付说明", payload: {} });
  h.step(200);
  assert.equal(h.actor("eng-manager")?.say?.text, "现在提交交付说明");
});

test("说话气泡：分派与交回的两端各说一句", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  h.driver.playEvent({ type: "x_role_task_assigned", department: "engineering", role: "eng-lead", work_item_id: "w1", payload: { to: "eng-lead", task: "起草 PLAN" } });
  h.step(1200);
  assert.equal(h.actor("eng-manager")?.say?.text, "现在把任务交给主程：起草 PLAN");
  h.step(9000);
  assert.equal(h.actor("eng-lead")?.say?.text, "收到任务：起草 PLAN");
  h.driver.playEvent({ type: "x_role_result_returned", department: "engineering", role: "eng-lead", work_item_id: "w1", payload: { to: "eng-lead" } });
  h.step(1500);
  assert.equal(h.actor("eng-lead")?.say?.text, "现在把结果交回经理");
  h.step(9000);
  assert.equal(h.actor("eng-manager")?.say?.text, "收到结果");
});

test("说话气泡：模型请求时只有思考气泡，不重复说话", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  const before = h.actor("eng-architect")?.say?.text ?? null;
  h.driver.playEvent({ type: "model_requested", department: "engineering", role: "eng-architect", work_item_id: "w1", payload: {} });
  h.step(1500);
  assert.equal(h.actor("eng-architect")?.say?.text ?? null, before);
  assert.equal(h.actor("eng-architect")?.persist?.icon?.kind, "think");
});

test("说话气泡：交接的两端各说一句", () => {
  const rm = mountRoom("engineering", ENG);
  rm.step(500);
  rm.driver.playEvent({ type: "transition", work_item_id: "w1", payload: { from: "engineering", to: "quality", artifact: "box" } });
  rm.step(100);
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在把交付箱送给质检");
  const qr = mountRoom("quality", QUA);
  qr.step(500);
  qr.driver.playEvent({ type: "transition", work_item_id: "w1", payload: { from: "engineering", to: "quality", artifact: "box" } });
  qr.step(6000);
  assert.equal(qr.actor("q-test")?.say?.text, "收到交付箱，来自工程");
});

test("说话气泡：没有专门动作的工具事件也说话", () => {
  const qr = mountRoom("quality", QUA);
  qr.step(500);
  qr.driver.playEvent({ type: "tool_started", tool: "browser_navigate", department: "quality", role: "q-test", work_item_id: "w1", label: "质检打开页面", payload: {} });
  qr.step(300);
  assert.equal(qr.actor("q-test")?.say?.text, "现在试用网页");
});

// ---------------------------------------------------------------------------
// 询问与回答

test("询问：发问的部门说「现在向产品发出询问」，收到询问的部门走到传信管口取信", () => {
  const ask: PixelFloorEvent = { type: "collaboration_requested", department: "engineering", work_item_id: "w1", label: "工程询问产品：线路偏好是否改变最短距离", payload: { from: "engineering", to: "product", request_id: "q1" } };
  const rm = mountRoom("engineering", ENG);
  const pr = mountRoom("product", PRO);
  rm.step(500);
  pr.step(500);
  rm.driver.playEvent(ask);
  pr.driver.playEvent(ask);
  rm.step(1200);
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在向产品发出询问：线路偏好是否改变最短距离");
  assert.equal(pr.actor("p-arch")?.say?.text, "收到工程的询问：线路偏好是否改变最短距离");
  assert.equal(pr.actor("p-arch")?.doing, "answer_letter", "收到询问的一方应走到传信管口取信，而不是写信");
});

test("回答：回答的部门说「现在回答工程的询问」，发问的部门说「收到产品的回答」", () => {
  const reply: PixelFloorEvent = { type: "collaboration_responded", department: "product", work_item_id: "w1", label: "产品回答：不改变", payload: { from: "product", to: "engineering", request_id: "q1" } };
  const rm = mountRoom("engineering", ENG);
  const pr = mountRoom("product", PRO);
  rm.step(500);
  pr.step(500);
  rm.driver.playEvent(reply);
  pr.driver.playEvent(reply);
  pr.step(1500);
  assert.equal(pr.actor("p-arch")?.say?.text, "现在回答工程的询问");
  const got = rm.actor("eng-architect")?.say?.text ?? "";
  assert.ok(got.startsWith("收到产品的回答："), got);
});

test("询问信的两端：从事件载荷读出，回答方是事件所在的部门", () => {
  const req: PixelFloorEvent = { type: "collaboration_requested", department: "engineering", payload: { from: "engineering", to: "product" } };
  assert.deepEqual(letterSides(req), { asker: "engineering", answerer: "product" });
  const res: PixelFloorEvent = { type: "collaboration_responded", department: "product", payload: { from: "product", to: "engineering" } };
  assert.deepEqual(letterSides(res), { asker: "engineering", answerer: "product" });
});

test("传信的两端：真实事件用 requester 与 recipient，旧事件按 request_id 回退查找", () => {
  const requests = new Map([["q1", { requester: "engineering", recipient: "product" }]]);
  const asked = collaborationSides("collaboration_requested", { requester: "engineering", recipient: "product", request_id: "q1" }, "engineering");
  assert.deepEqual(asked, { from: "engineering", to: "product" });
  // 旧事件没有 requester/recipient：从见过的请求补齐，回答方是事件所在的部门
  const oldReply = collaborationSides("collaboration_responded", { request_id: "q1" }, "product", requests);
  assert.deepEqual(oldReply, { from: "engineering", to: "product" });
  // 找不到对应请求时不给两端，调用方因此不显示这个事件
  assert.equal(collaborationSides("collaboration_responded", { request_id: "q9" }, "product", requests), null);
});

test("事项很快结束时，已经排队的传信动作不被停止态丢弃，两端照样说话", () => {
  const rm = mountRoom("engineering", ENG);
  rm.step(500);
  const scene = rm.driver.scene;
  const actor = scene.actors.find((a) => a.id === "ch-eng-architect")!;
  // 让发问的角色正在做一段长动作（关键步骤之后才可被接管），传信事件因此排入队列
  scene.run(actor, [{ t: "anim", name: "type", ms: 60000, key: true }, { t: "anim", name: "type", ms: 60000 }], { tail: 1 });
  rm.step(100);
  const ask: PixelFloorEvent = { type: "collaboration_requested", department: "engineering", work_item_id: "w1", label: "工程询问产品：线路偏好是否改变最短距离", payload: { from: "engineering", to: "product", request_id: "q1" } };
  rm.driver.playEvent(ask);
  assert.equal(rm.actor("eng-architect")?.queue.length, 1, "传信动作应排入队列");
  // 事项很快进入停止态（真实系统约 1 秒跑到 done）
  rm.driver.setModel({ ...emptyRoomModel("engineering"), status: "done", roles: ENG });
  assert.equal(rm.actor("eng-architect")?.queue.length, 1, "停止态应保留已排队的传信动作");
  rm.step(1500);
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在向产品发出询问：线路偏好是否改变最短距离");
  assert.equal(rm.actor("eng-architect")?.doing, "send_letter");
});

test("事项进入停止态时，不是传信与交接的排队动作被清除", () => {
  const rm = mountRoom("engineering", ENG);
  rm.step(500);
  const scene = rm.driver.scene;
  const actor = scene.actors.find((a) => a.id === "ch-eng-architect")!;
  scene.run(actor, [{ t: "anim", name: "type", ms: 60000, key: true }, { t: "anim", name: "type", ms: 60000 }], { tail: 1 });
  rm.step(100);
  // 读取文件这类普通动作排入队列
  rm.driver.playEvent({ type: "tool_started", department: "engineering", role: "eng-architect", tool: "read_file", payload: {} } as PixelFloorEvent);
  assert.ok((rm.actor("eng-architect")?.queue.length ?? 0) >= 1, "普通动作应排入队列");
  rm.driver.setModel({ ...emptyRoomModel("engineering"), status: "done", roles: ENG });
  assert.equal(rm.actor("eng-architect")?.queue.length, 0, "停止态应清除普通排队动作");
});

test("事件成串到达时，队满挤掉的是普通动作，传信动作留在队列里", () => {
  const rm = mountRoom("engineering", ENG);
  rm.step(500);
  const scene = rm.driver.scene;
  const actor = scene.actors.find((a) => a.id === "ch-eng-architect")!;
  scene.run(actor, [{ t: "anim", name: "type", ms: 60000, key: true }, { t: "anim", name: "type", ms: 60000 }], { tail: 1 });
  rm.step(100);
  rm.driver.playEvent({ type: "collaboration_requested", department: "engineering", label: "工程询问产品：线路偏好", payload: { from: "engineering", to: "product", request_id: "q1" } } as PixelFloorEvent);
  assert.equal(rm.actor("eng-architect")?.queue.length, 1);
  // 后面的普通动作连续到达，队满时只挤普通的那些
  for (const ev of ["model_requested", "model_attempt_finished", "proposal_submitted", "plan_accepted", "department_activated"]) {
    rm.driver.playEvent({ type: ev, department: "engineering", role: "eng-architect", payload: {} } as PixelFloorEvent);
  }
  const queued = rm.actor("eng-architect")!.queue.map((entry) => entry.from);
  assert.ok(queued.includes("collaboration_requested"), `传信动作不应被挤掉，实际队列：${queued.join("、")}`);
});

test("收到交接的一方立刻说话：后一个交接事件替换脚本时上一句还在", () => {
  const q = mountRoom("quality", QUA);
  q.step(500);
  // 先收到工程送来的交付箱，紧接着质检把放行单送走；两步之间没有停顿
  q.driver.playEvent({ type: "transition", department: "engineering", payload: { from: "engineering", to: "quality", artifact: "box" } } as PixelFloorEvent);
  const afterBox = q.actor("q-test")?.say?.text;
  q.driver.playEvent({ type: "transition", department: "quality", payload: { from: "quality", to: "adopted", artifact: "release" } } as PixelFloorEvent);
  assert.equal(afterBox, "收到交付箱，来自工程");
  assert.equal(q.actor("q-test")?.say?.text, "现在把放行单送给成果库");
});

// ---------------------------------------------------------------------------
// 事件到动作的解析

test("解析：事件类型、工具、结论与恢复状态各解析到对应动作", () => {
  assert.equal(resolveAction({ type: "model_requested" }), "type_think");
  assert.equal(resolveAction({ type: "model_stream_progress" }), "stream_text");
  assert.equal(resolveAction({ type: "tool_started", tool: "search" }), "search");
  assert.equal(resolveAction({ type: "tool_started", tool: "edit_range" }), "write");
  assert.equal(resolveAction({ type: "qa_submitted", payload: { verdict: "release" } }), "stamp_release");
  assert.equal(resolveAction({ type: "qa_submitted", payload: { verdict: "rework_engineering" } }), "stamp_rework");
  assert.equal(resolveAction({ type: "run_failed", payload: { reason: "cancelled" } }), "cancelled");
  assert.equal(resolveAction({ type: "run_failed", payload: {} }), "failed");
  assert.equal(resolveAction({ type: "x_explorer_fetch" }), "explore");
});

test("说话气泡：内容来自事件已经带着的事实", () => {
  assert.equal(say({ type: "proposal_submitted", department: "engineering", label: "工程经理代表部门提交交付说明", payload: {} }), "现在提交交付说明");
  assert.equal(say({ type: "proposal_submitted", department: "quality", payload: { kind: "qa_review" } }), "现在提交质检结论");
  const ev: PixelFloorEvent = { type: "transition", payload: { from: "engineering", to: "quality", artifact: "box" } };
  assert.equal(say(ev, { dept: "engineering" }), "现在把交付箱送给质检");
  assert.equal(say(ev, { dept: "quality" }), "收到交付箱，来自工程");
});

test("说话气泡：一句话停留的时间读得完，最长 4.6 秒", () => {
  assert.equal(sayMs("短"), 1800 + 170);
  assert.equal(sayMs("很长的句子".repeat(40)), 4600);
});

test("说话气泡：事件说明里「」括起的部分作为内容", () => {
  assert.equal(quoted("工程部门写「第 3 步」的说明"), "第 3 步");
  assert.equal(quoted(null), null);
});

// ---------------------------------------------------------------------------
// 真实载荷形状（工单 #319 第 3 项）
// 真实事件把工具名放在载荷的 name 上、参数放在 args 之下，工具结果只有 ok 与 error；
// 下面按 harness/app/payloads.py 的合同构造事件，头顶的话里要有工具名、文件名、命令名与结论。

const real = (over: Partial<PixelFloorEvent> & { payload: Record<string, unknown> }): PixelFloorEvent => ({
  type: "tool_started", work_item_id: "w1", department: "engineering", role: "eng-architect", ...over,
});
test("工具类：真实载荷的名字与参数说出是哪件事", () => {
  assert.equal(say(real({ payload: { name: "read_file", args: { path: "src/echo.py" } } })), "现在阅读 echo.py");
  assert.equal(say(real({ payload: { name: "search", args: { pattern: "def main" } } })), "现在翻找资料：def main");
  assert.equal(say(real({ payload: { name: "edit_range", args: { path: "src/echo.py" } } })), "现在编辑 echo.py");
  assert.equal(say(real({ payload: { name: "delete_file", args: { path: "src/old.py" } } })), "现在删除 old.py");
  assert.equal(say(real({ payload: { name: "move_file", args: { source: "src/a.py", destination: "src/b.py" } } })), "现在移动 a.py");
  assert.equal(say(real({ payload: { name: "list_files", args: { prefix: "src/" } } })), "现在看看有什么文件：src/");
  assert.equal(say(real({ payload: { name: "run_check", args: { name: "unit-tests" } } })), "现在检查交付：unit-tests");
});
test("工具类：交出类工具说出交的是哪一份，名称与提案事件一致", () => {
  assert.equal(say(real({ payload: { name: "submit_plan", args: {} } })), "现在提交工程计划");
  assert.equal(say(real({ payload: { name: "submit_delivery", args: {} } })), "现在提交交付说明");
  assert.equal(say(real({ payload: { name: "submit_request", args: {} } })), "现在提交询问");
});

test("工具类：工具调用的发生时刻就说话，不等走位动作做完；盖章类事件随后照样说出", () => {
  const rm = mountRoom("engineering", ENG);
  rm.step(500);
  rm.driver.playEvent({ type: "transition", work_item_id: "w1", payload: { from: "product", to: "engineering", artifact: "prd" } });
  rm.driver.playEvent(real({ payload: { name: "list_files", args: {} } }));
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在看看有什么文件");
  rm.driver.playEvent(real({ payload: { name: "submit_plan", args: {} } }));
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在提交工程计划");
  rm.driver.playEvent({ type: "plan_accepted", department: "engineering", work_item_id: "w1", payload: {} });
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在把计划贴上白板");
});

test("工具类：登记命令说出登记名而不是工具名", () => {
  assert.equal(say(real({ payload: { name: "run_command", registered_name: "unit-tests", args: { name: "unit-tests" } } })),
    "现在执行 unit-tests");
});

test("工具类：没有登记名的命令只说明在跑登记命令，不把工具名说出来", () => {
  assert.equal(say(real({ payload: { name: "run_command", args: { name: "lint" } } })), "现在执行 lint");
});

test("工具类：登记命令的结论按 ok 说成功或失败", () => {
  const done = (payload: Record<string, unknown>): PixelFloorEvent =>
    ({ type: "tool_called", work_item_id: "w1", department: "engineering", tool: "run_command", payload });
  assert.equal(say(done({ name: "run_command", ok: true })), "命令通过了");
  assert.equal(say(done({ name: "run_command", ok: false, error: "命令不存在" })), "命令没有通过：命令不存在");
});

test("动作解析：原型没登记的三个工具也解析到动作", () => {
  assert.equal(resolveAction(real({ payload: { name: "list_files" } })), "search");
  assert.equal(resolveAction(real({ payload: { name: "delete_file" } })), "write");
  assert.equal(resolveAction(real({ payload: { name: "move_file" } })), "write");
  assert.equal(resolveAction(real({ payload: { name: "read_file" } })), "read");
});

test("协作：真实载荷用 requester 与 recipient，两端各说一句", () => {
  const req: PixelFloorEvent = {
    type: "collaboration_requested", department: "engineering", work_item_id: "w1",
    payload: { requester: "engineering", recipient: "product", question: "线路偏好是否改变" },
  };
  assert.equal(say(req, { dept: "engineering" }), "现在向产品发出询问：线路偏好是否改变");
  assert.equal(say(req, { dept: "product" }), "收到工程的询问：线路偏好是否改变");
  const res: PixelFloorEvent = {
    type: "collaboration_responded", department: "product", work_item_id: "w1",
    payload: { requester: "engineering", recipient: "product", text: "不改变" },
  };
  assert.equal(say(res, { dept: "product" }), "现在回答工程的询问");
  assert.equal(say(res, { dept: "engineering" }), "收到产品的回答：不改变");
});

test("工具类：真实载荷的事件在房间里说出那句话并播放动作", () => {
  const rm = mountRoom("engineering", ENG);
  rm.step(500);
  rm.driver.playEvent(real({ payload: { name: "read_file", args: { path: "src/echo.py" } } }));
  rm.step(300);
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在阅读 echo.py");
  assert.equal(rm.actor("eng-architect")?.doing, "read");
});

