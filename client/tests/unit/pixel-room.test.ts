// 部门房间的行为测试（工单 #177、#954）：把原型 v13 checks/behaviors.js 与 checks/playback.js 里
// 关于部门房间的检查改写为对客户端的测试，直接对房间驱动与场景运行，用确定的时钟与手写的数据。
//
// 覆盖：角色与工位、状态的姿势、工具名称到动作、说话气泡（提交、分派与交回、交接、询问与回答、工具）、
// 动作按播放时间线排队、状态等动作演完再上画面（状态变化不打断正在演的动作）、关键动作不丢、
// 流式文字、跳到最新、翻译层与说话目录的对应。

import { test } from "node:test";
import assert from "node:assert/strict";

import { createRoomDriver } from "../../src/renderer/src/pixel/room/driver.ts";
import { layoutDesks, spriteForRole } from "../../src/renderer/src/pixel/room/decl.ts";
import { ROOM_KINDS } from "../../src/renderer/src/pixel/room/room-decl.ts";
import { actions as roomActions, quoted, state as roomState } from "../../src/renderer/src/translate/room.ts";
import { say, sayCatalog, sayHandoff } from "../../src/renderer/src/translate/say.ts";
import { COVERAGE } from "../../src/renderer/src/translate/coverage.ts";
import { sayMs } from "../../src/renderer/src/pixel/world/say.ts";
import type { RoomActor } from "../../src/renderer/src/pixel/room/driver.ts";
import type { RoomRole } from "../../src/renderer/src/pixel/room/layout.ts";
import type { RoomEvent } from "../../src/renderer/src/translate/room.ts";
import type { PixelAction } from "../../src/renderer/src/pixel/contract.ts";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const req = createRequire(import.meta.url);
const ts = req("typescript");
function tsxLoader(module: NodeJS.Module, filename: string) {
  let code = fs.readFileSync(filename, "utf8");
  code = code.replaceAll("import.meta.env", "({ DEV: false })");
  const js = ts.transpileModule(code, {
    compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const fileReq = createRequire(filename);
  const fn = new Function("exports", "require", "module", "__filename", "__dirname", js);
  fn(module.exports, fileReq, module, filename, path.dirname(filename));
}
req.extensions[".tsx"] = tsxLoader;
req.extensions[".ts"] = tsxLoader;
const { roomEventOf } = req("../../src/renderer/src/views/project/room-screen.tsx");

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

/** 一份查询结果里的房间（department.workspace 的 room 那一块）。 */
function roomSample(department: string, roles: RoomRole[], over: Record<string, unknown> = {}): { room: Record<string, unknown> } {
  return {
    room: {
      department, level: "S5", status: "working", crt: {}, roles, pose: null, door: null, hold_card: null,
      mailbox: 0, summaries: 0, scrolls: 0, pinned_notes: 0, semantic_cards: 0, machine: null,
      remote_unknown: false, waiting_provider: false, pipes: null, existing_read: false, trial: null,
      tool_panel: null, self_test: null, ...over,
    },
  };
}

interface RoomHarness {
  driver: ReturnType<typeof createRoomDriver>;
  department: string;
  roles: RoomRole[];
  step: (ms: number) => void;
  actor: (id: string) => RoomActor | null;
  /** 一条事件经翻译层翻成动作（位置递增，与页面上的事件位置一样单调）。 */
  event: (ev: Omit<RoomEvent, "position">) => PixelAction[];
  /** 一份新的状态（位置递增）交给画面。 */
  state: (over?: Record<string, unknown>) => number;
  position: () => number;
}

let POS = 0;

function mountRoom(department: string, roles: RoomRole[], over: Record<string, unknown> = {}, reduced = false): RoomHarness {
  const driver = createRoomDriver({ department, sceneOptions: { W: 480, H: 240, random: seeded(), reduced } });
  const sample = (extra: Record<string, unknown>): { room: Record<string, unknown> } => roomSample(department, roles, { ...over, ...extra });
  driver.jump(roomState({ position: ++POS, workspace: sample({}) }));
  const step = (ms: number): void => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) driver.step(50);
  };
  const roleName = (id: string | null): string | null => {
    const hit = roles.find((r) => r.id === id || r.kind === id || r.name === id);
    return hit ? hit.name : null;
  };
  return {
    driver,
    department,
    roles,
    step,
    actor: (id) => driver.actorById(id),
    event(ev) {
      const list = roomActions({ ...ev, position: ++POS } as RoomEvent, department, { roleName });
      for (const a of list) driver.play(a);
      return list;
    },
    state(extra = {}) {
      const position = ++POS;
      driver.setState(roomState({ position, workspace: sample(extra) }));
      return position;
    },
    position: () => POS,
  };
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

test("房间：中心角色的动作姿势按状态里的 pose 摆放，无法对应时翻译层抛出错误", () => {
  const h = mountRoom("engineering", ENG, { pose: { role_id: "eng-architect", action: "typing" } });
  h.step(1500);
  assert.deepEqual(h.driver.model.pose, { role_id: "eng-architect", anim: "type" });
  assert.throws(() => roomState({ position: 1, workspace: roomSample("engineering", ENG, { pose: { role_id: null, action: "不存在的动作" } }) }),
    /翻译层没有对应的房间姿势/);
});

test("房间：工具名称翻成房间的动作，没有专门动作的工具是进度", () => {
  const tool = (name: string): string[] =>
    roomActions({ type: "tool_started", position: 90, department: "engineering", tool: name, label: "工程调用工具" }, "engineering").map((a) => a.kind);
  assert.deepEqual(tool("search"), ["search"]);
  assert.deepEqual(tool("read_file"), ["read"]);
  assert.deepEqual(tool("edit_range"), ["write"]);
  assert.deepEqual(tool("bash"), ["run_command"]);
  assert.deepEqual(tool("run_check"), ["inspect"]);
  assert.deepEqual(tool("some_new_tool"), ["tool_progress"]);
  for (const kinds of [tool("search"), tool("some_new_tool")]) {
    for (const kind of kinds) assert.ok(ROOM_KINDS[kind], kind);
  }
});

// ---------------------------------------------------------------------------
// 说话气泡（部门房间）

test("说话气泡：翻译层在房间里翻出的每种动作都有话（交接、询问与回答的话单独写）", () => {
  const special = new Set(["structure_accepted", "ask_started", "ask_answered"]);
  const missing = [...COVERAGE.room.drawn].filter((k) => !special.has(k) && !sayCatalog.includes(k));
  assert.deepEqual(missing, [], `说话目录缺少：${missing.join(",")}`);
  // 交接的两端说不同的话
  const hs = sayHandoff("box", "engineering", "quality");
  assert.deepEqual(hs, { say: "现在把交付箱送给质检", sayTo: "收到交付箱，来自工程" });
});

test("说话气泡：经理提交交付说明，头顶说「现在提交交付说明」，过几秒消失", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  h.event({ type: "proposal_submitted", department: "engineering", role: "eng-manager", work_item_id: "w1", label: "工程经理代表部门提交交付说明" });
  h.step(1200);
  assert.equal(h.actor("eng-manager")?.say?.text, "现在提交交付说明");
  const until = h.actor("eng-manager")?.say?.until ?? 0;
  h.step(7000);
  assert.ok((h.actor("eng-manager")?.say?.until ?? 0) < h.driver.scene.realT, `气泡应在 ${until} 毫秒后不再显示`);
});

test("说话气泡：减少动画时照样说话", () => {
  const h = mountRoom("engineering", ENG, {}, true);
  h.step(200);
  h.event({ type: "proposal_submitted", department: "engineering", role: "eng-manager", work_item_id: "w1", label: "工程经理代表部门提交交付说明" });
  h.step(200);
  assert.equal(h.actor("eng-manager")?.say?.text, "现在提交交付说明");
});

test("说话气泡：分派与交回的两端各说一句", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  // 分派：经理把任务卡递给主程，接任务的角色说收到什么
  h.driver.play({ kind: "assign", position: ++POS, role: "eng-lead", say: "现在把任务交给主程：起草 PLAN", sayTo: "收到任务：起草 PLAN" });
  h.step(1200);
  assert.equal(h.actor("eng-manager")?.say?.text, "现在把任务交给主程：起草 PLAN");
  h.step(9000);
  assert.equal(h.actor("eng-lead")?.say?.text, "收到任务：起草 PLAN");
  // 交回：主程把结果卡交回经理，收下结果的经理说收到结果
  h.driver.play({ kind: "hand_back", position: ++POS, role: "eng-lead", say: "现在把结果交回经理", sayTo: "收到结果" });
  h.step(1500);
  assert.equal(h.actor("eng-lead")?.say?.text, "现在把结果交回经理");
  h.step(9000);
  assert.equal(h.actor("eng-manager")?.say?.text, "收到结果");
});

test("说话气泡：模型请求时只有思考气泡，不重复说话", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  const before = h.actor("eng-architect")?.say?.text ?? null;
  h.event({ type: "model_requested", department: "engineering", role: "eng-architect", work_item_id: "w1", label: "工程思考" });
  h.step(1500);
  assert.equal(h.actor("eng-architect")?.say?.text ?? null, before);
  assert.equal(h.actor("eng-architect")?.persist?.icon?.kind, "think");
});

test("说话气泡：交接的两端各说一句", () => {
  const rm = mountRoom("engineering", ENG);
  rm.step(500);
  rm.event({ type: "delivery_accepted", work_item_id: "w1", department: "engineering", label: "交付被接纳" });
  rm.step(300);
  // 工程先封存交付箱，封存演完才把箱子送进管道：两句话按位置先后说
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在装箱封存");
  rm.step(9000);
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在把交付箱送给质检");
  const qr = mountRoom("quality", QUA);
  qr.step(500);
  qr.event({ type: "delivery_accepted", work_item_id: "w1", department: "engineering", label: "交付被接纳" });
  qr.step(300);
  assert.equal(qr.actor("q-test")?.say?.text, "收到交付箱，来自工程");
});

test("说话气泡：没有专门动作的工具事件也说话", () => {
  const qr = mountRoom("quality", QUA);
  qr.step(500);
  qr.event({ type: "tool_started", tool: "browser_navigate", department: "quality", role: "q-test", work_item_id: "w1", label: "质检打开页面" });
  qr.step(300);
  assert.equal(qr.actor("q-test")?.say?.text, "现在试用网页");
});

// 原型 v11 第 2 条（ADR-0043 之后）：状态等动作演完；两个动作按位置先后演，后一个开始说话时不打断前一个
test("说话气泡：盖章紧跟着完成时，盖章说明先显示，完成的话排在后面", () => {
  const h = mountRoom("quality", QUA);
  h.step(500);
  h.event({ type: "qa_submitted", department: "quality", role: "q-test", work_item_id: "w1", label: "质检提交结论", payload: { verdict: "release" } });
  h.event({ type: "run_done", department: "quality", role: "q-test", work_item_id: "w1", label: "事项完成" });
  h.step(200);
  assert.equal(h.actor("q-test")?.say?.text, "现在盖放行章");
  h.step(12000);
  assert.equal(h.actor("q-test")?.say?.text, "完成了！");
});

test("说话气泡：盖章紧接着交接时，交接的话在盖章演完之后说", () => {
  const h = mountRoom("quality", QUA);
  h.step(500);
  // 一次质检结论翻成两个关键动作：盖放行章，然后把放行单送回成果库
  const list = h.event({ type: "qa_submitted", department: "quality", role: "q-test", work_item_id: "w1", label: "质检提交结论", payload: { verdict: "release" } });
  assert.deepEqual(list.map((a) => a.kind), ["stamp_release", "handoff"]);
  h.step(200);
  assert.equal(h.actor("q-test")?.say?.text, "现在盖放行章");
  // 盖章演完以后才轮到交接：交接的话这时才说
  for (let i = 0; i < 400 && h.actor("q-test")?.doing !== "handoff"; i++) h.step(50);
  assert.equal(h.actor("q-test")?.doing, "handoff");
  h.step(200);
  assert.equal(h.actor("q-test")?.say?.text, "现在把放行单送给成果库");
});

// ---------------------------------------------------------------------------
// 询问与回答

test("询问：发问的部门说「现在向产品发出询问」，收到询问的部门走到传信管口取信", () => {
  const ask = { type: "ask_started" as const, department: "engineering", work_item_id: "w1", label: "工程询问产品：线路偏好是否改变最短距离", payload: { requester: "engineering", recipient: "product", question: "线路偏好是否改变最短距离" } };
  const rm = mountRoom("engineering", ENG);
  const pr = mountRoom("product", PRO);
  rm.step(500);
  pr.step(500);
  rm.event(ask);
  pr.event(ask);
  rm.step(1200);
  pr.step(1200);
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在向产品发出询问：线路偏好是否改变最短距离");
  assert.equal(pr.actor("p-arch")?.say?.text, "收到工程的询问：线路偏好是否改变最短距离");
  assert.equal(pr.actor("p-arch")?.doing, "answer_letter", "收到询问的一方应走到传信管口取信，而不是写信");
});

test("回答：回答的部门说「现在回答工程的询问」，发问的部门说「收到产品的回答」", () => {
  const reply = { type: "ask_answered" as const, department: "product", work_item_id: "w1", label: "产品回答：不改变", payload: { requester: "engineering", recipient: "product", answer: "不改变" } };
  const rm = mountRoom("engineering", ENG);
  const pr = mountRoom("product", PRO);
  rm.step(500);
  pr.step(500);
  rm.event(reply);
  pr.event(reply);
  pr.step(1500);
  rm.step(1500);
  assert.equal(pr.actor("p-arch")?.say?.text, "现在回答工程的询问");
  const got = rm.actor("eng-architect")?.say?.text ?? "";
  assert.ok(got.startsWith("收到产品的回答："), got);
});

test("询问信的两端：从事件载荷的 requester 与 recipient 读出，别的部门不画", () => {
  const ask: RoomEvent = { type: "ask_started", position: 70, department: "engineering", payload: { requester: "engineering", recipient: "product" } };
  assert.deepEqual(roomActions(ask, "engineering").map((a) => a.kind), ["send_letter"]);
  assert.deepEqual(roomActions(ask, "product").map((a) => a.kind), ["answer_letter"]);
  assert.deepEqual(roomActions(ask, "quality"), []);
  const reply: RoomEvent = { type: "ask_answered", position: 71, department: "product", payload: { requester: "engineering", recipient: "product" } };
  assert.deepEqual(roomActions(reply, "product").map((a) => a.kind), ["answer_letter"]);
  assert.deepEqual(roomActions(reply, "engineering").map((a) => a.kind), ["answer_letter"]);
  assert.deepEqual(roomActions(reply, "quality"), []);
});

test("询问的两端：真实事件经页面的适配函数交给翻译层，留下发信与回信两端", () => {
  const askStarted = {
    type: "ask_started", department: "engineering", role: null, label: "工程向产品询问：线路偏好是否改变最短距离",
    work_item_id: "w1", project_id: "p1", position: 10, event_id: "e10", actor: "department:engineering", command_id: null,
    payload: { requester: "engineering", recipient: "product", question: "线路偏好是否改变最短距离", branch_session_id: "s1" },
  } as never;
  const ev = roomEventOf(askStarted, 10);
  assert.equal(ev.type, "ask_started");
  assert.equal(ev.position, 10);
  assert.deepEqual(roomActions(ev, "engineering").map((a) => a.kind), ["send_letter"]);
  assert.deepEqual(roomActions(ev, "product").map((a) => a.kind), ["answer_letter"]);
  assert.deepEqual(roomActions(ev, "quality"), []);
  const askAnswered = {
    type: "ask_answered", department: "product", role: null, label: "产品回答工程：最短距离不乘 0.8",
    work_item_id: "w1", project_id: "p1", position: 20, event_id: "e20", actor: "department:product", command_id: null,
    payload: { requester: "engineering", recipient: "product", answer: "最短距离不乘 0.8", status: "answered" },
  } as never;
  const answered = roomEventOf(askAnswered, 20);
  assert.equal(answered.type, "ask_answered");
  assert.deepEqual(roomActions(answered, "product").map((a) => a.kind), ["answer_letter"]);
  assert.ok(String(roomActions(answered, "engineering")[0].say ?? "").startsWith("收到产品的回答："));
});

// ---------------------------------------------------------------------------
// 播放时间线：状态等动作、关键动作不丢、跳到最新

test("状态等动作：状态变化不打断正在演的动作，动作演完以后状态才上画面", () => {
  const h = mountRoom("quality", QUA);
  h.step(500);
  h.event({ type: "qa_submitted", department: "quality", role: "q-test", work_item_id: "w1", label: "质检提交结论", payload: { verdict: "release" } });
  h.step(300);
  assert.equal(h.actor("q-test")?.doing, "stamp_release");
  const before = h.driver.timeline().shown;
  const target = h.state({ status: "done" });
  h.step(200);
  const tl = h.driver.timeline();
  // 状态没有上画面，正在演的动作还在演
  assert.equal(tl.shown, before);
  assert.equal(tl.pending, 1);
  assert.equal(h.actor("q-test")?.doing, "stamp_release");
  h.step(12000);
  assert.equal(h.driver.timeline().shown, target, "动作演完以后状态上画面");
  assert.equal(h.driver.model.status, "done");
  assert.equal(h.actor("q-test")?.doing, "handoff", "演完的是最后一个动作，画面随后回到状态给出的样子");
});

test("状态等动作：没有要等的动作时下一帧就上画面", () => {
  const h = mountRoom("engineering", ENG);
  h.step(300);
  const target = h.state({ summaries: 3 });
  h.step(200);
  assert.equal(h.driver.timeline().shown, target);
  assert.equal(h.driver.model.summaries, 3);
});

test("状态等动作：普通动作还在演时，新的状态同样等它演完", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  h.event({ type: "tool_started", department: "engineering", role: "eng-architect", tool: "read_file", label: "工程读文件" });
  h.step(300);
  assert.equal(h.actor("eng-architect")?.doing, "read");
  const before = h.driver.timeline().shown;
  h.state({ summaries: 5 });
  h.step(100);
  assert.equal(h.driver.timeline().shown, before);
  h.step(4000);
  assert.equal(h.driver.model.summaries, 5);
});

test("事件成串到达时，普通动作按上限丢掉排得太长的那几条", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  for (let i = 0; i < 6; i++) {
    h.event({ type: "tool_started", department: "engineering", role: "eng-architect", tool: "read_file", label: "工程读文件" });
  }
  const tl = h.driver.timeline();
  assert.ok(tl.stats.pushed >= 6, `推入 ${tl.stats.pushed}`);
  assert.ok(tl.stats.dropped >= 1, `丢掉 ${tl.stats.dropped}`);
});

test("关键动作不丢：普通动作排在前面时，盖章与完成都演完", () => {
  const h = mountRoom("quality", QUA);
  h.step(500);
  h.event({ type: "tool_started", department: "quality", tool: "read_file", label: "质检读文件" });
  h.event({ type: "qa_submitted", department: "quality", label: "质检提交结论", payload: { verdict: "release" } });
  h.event({ type: "run_done", department: "quality", label: "事项完成" });
  h.step(14000);
  const stats = h.driver.timeline().stats;
  assert.equal(stats.droppedKey, 0, JSON.stringify(stats));
  assert.equal(stats.startedKey, stats.pushedKey, JSON.stringify(stats));
  assert.equal(h.actor("q-test")?.say?.text, "完成了！");
});

test("跳到最新：清空时间线，直接显示最新的状态，不补播", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  for (let i = 0; i < 6; i++) {
    h.event({ type: "tool_started", department: "engineering", role: "eng-architect", tool: "read_file", label: "工程读文件" });
  }
  const piled = h.driver.timeline();
  assert.ok(piled.queued + piled.playing.length > 0, "积下了动作");
  const latest = ++POS;
  h.driver.jump(roomState({ position: latest, workspace: roomSample("engineering", ENG, { status: "done" }) }));
  h.step(100);
  const tl = h.driver.timeline();
  assert.equal(tl.shown, latest);
  assert.equal(tl.queued, 0);
  assert.equal(tl.playing.length, 0);
  assert.equal(h.driver.model.status, "done");
});

// ---------------------------------------------------------------------------
// 流式文字（实时内容，不进时间线）

test("流式文字：一串动作还在演时也立刻出现在头顶", () => {
  const h = mountRoom("engineering", ENG);
  h.step(500);
  h.event({ type: "tool_started", department: "engineering", role: "eng-architect", tool: "read_file", label: "工程读文件" });
  h.event({ type: "tool_started", department: "engineering", role: "eng-architect", tool: "edit_range", label: "工程改文件" });
  h.step(100);
  h.driver.stream({ room: "engineering", role: "eng-architect" }, "正在阅读需求");
  assert.equal(h.actor("eng-architect")?.streamText, "正在阅读需求");
  assert.equal(h.actor("eng-architect")?.persist?.icon?.kind, "stream");
});

// ---------------------------------------------------------------------------
// 事件到动作的解析与说话目录

test("解析：事件类型、工具、结论与恢复状态各解析到对应动作", () => {
  const kind = (ev: Omit<RoomEvent, "position">, dept = "engineering"): string[] =>
    roomActions({ ...ev, position: 80 } as RoomEvent, dept).map((a) => a.kind);
  assert.deepEqual(kind({ type: "model_requested" }), ["type_think"]);
  assert.deepEqual(kind({ type: "tool_started", tool: "search" }), ["search"]);
  assert.deepEqual(kind({ type: "tool_started", tool: "edit_range" }), ["write"]);
  assert.deepEqual(kind({ type: "qa_submitted", department: "quality", payload: { verdict: "release" } }, "quality"), ["stamp_release", "handoff"]);
  assert.deepEqual(kind({ type: "qa_submitted", department: "quality", payload: { verdict: "rework_engineering" } }, "quality"), ["stamp_rework", "handoff"]);
  assert.deepEqual(kind({ type: "run_failed", payload: { stop_reason: "cancelled" } }), ["cancelled"]);
  assert.deepEqual(kind({ type: "run_failed", payload: { stop_reason: "time_limit" } }), ["failed"]);
  assert.deepEqual(kind({ type: "run_resumed" }), ["resume"]);
});

test("说话气泡：内容来自事件已经带着的事实", () => {
  assert.equal(say({ type: "proposal_submitted", department: "engineering", label: "工程经理代表部门提交交付说明", payload: {} }), "现在提交交付说明");
  assert.equal(say({ type: "proposal_submitted", department: "quality", payload: { kind: "qa_review" } }), "现在提交质检结论");
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

const real = (over: Partial<RoomEvent> & { payload: Record<string, unknown> }): RoomEvent => ({
  type: "tool_started", position: 100, work_item_id: "w1", department: "engineering", role: "eng-architect", ...over,
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
  assert.equal(say(real({ payload: { name: "submit_delivery", args: {} } })), "现在提交交付说明");
  assert.equal(say(real({ payload: { name: "ask", args: {} } })), "现在提交询问");
  assert.equal(say(real({ payload: { name: "answer", args: {} } })), "现在提交回答");
});

test("工具类：工具调用排在取信之后，事件成串时头顶显示最后演到的那一句", () => {
  const rm = mountRoom("engineering", ENG);
  rm.step(500);
  rm.event({ type: "spec_accepted", work_item_id: "w1", department: "product", label: "PRD 被接纳" });
  rm.step(4500);
  assert.equal(rm.actor("eng-architect")?.say?.text, "收到PRD，来自产品");
  // 采样收集这一轮里出现过的每一句：进度动作（工具、提交）不排队，关键动作排在后面
  const seen = new Set<string>();
  rm.event(real({ payload: { name: "list_files", args: {} } }));
  rm.event(real({ payload: { name: "submit_delivery", args: {} } }));
  rm.event({ type: "delivery_accepted", department: "engineering", work_item_id: "w1", label: "交付被接纳" });
  for (let i = 0; i < 600; i++) {
    rm.step(50);
    const said = rm.actor("eng-architect")?.say?.text;
    if (said) seen.add(said);
  }
  assert.ok(seen.has("现在装箱封存"), `封存的话应当出现：${[...seen].join(" / ")}`);
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在把交付箱送给质检");
});

test("工具类：bash 说出命令原文而不是工具名", () => {
  assert.equal(say(real({ payload: { name: "bash", args: { command: "pytest -q" } } })), "现在执行 pytest -q");
});

test("工具类：没有给出命令的 bash 只说明在跑命令，不把工具名说出来", () => {
  assert.equal(say(real({ payload: { name: "bash", args: {} } })), "现在执行命令");
});

test("工具类：bash 的结论按 ok 说成功或失败", () => {
  const done = (payload: Record<string, unknown>): RoomEvent =>
    ({ type: "tool_called", position: 101, work_item_id: "w1", department: "engineering", tool: "bash", payload });
  assert.equal(say(done({ name: "bash", ok: true })), "命令通过了");
  assert.equal(say(done({ name: "bash", ok: false, error: "命令不存在" })), "命令没有通过：命令不存在");
});

test("动作解析：有专门动作的工具按工具落，没有专门动作的工具是进度", () => {
  const kind = (name: string): string =>
    roomActions(real({ payload: { name } }), "engineering")[0].kind;
  assert.equal(kind("list_files"), "tool_progress");
  assert.equal(kind("delete_file"), "tool_progress");
  assert.equal(kind("move_file"), "tool_progress");
  assert.equal(kind("read_file"), "read");
  assert.equal(kind("bash"), "run_command");
});

test("询问：像素层按 requester 与 recipient 读出两端", () => {
  const req: RoomEvent = {
    type: "ask_started", position: 110, department: "engineering", work_item_id: "w1",
    payload: { requester: "engineering", recipient: "product", question: "线路偏好是否改变" },
  };
  assert.equal(roomActions(req, "engineering")[0].say, "现在向产品发出询问：线路偏好是否改变");
  assert.equal(roomActions(req, "product")[0].say, "收到工程的询问：线路偏好是否改变");
  const res: RoomEvent = {
    type: "ask_answered", position: 111, department: "product", work_item_id: "w1",
    payload: { requester: "engineering", recipient: "product", answer: "不改变" },
  };
  assert.equal(roomActions(res, "product")[0].say, "现在回答工程的询问");
  assert.equal(roomActions(res, "engineering")[0].say, "收到产品的回答：不改变");
});

test("工具类：真实载荷的事件在房间里说出那句话并播放动作", () => {
  const rm = mountRoom("engineering", ENG);
  rm.step(500);
  rm.event(real({ payload: { name: "read_file", args: { path: "src/echo.py" } } }));
  rm.step(300);
  assert.equal(rm.actor("eng-architect")?.say?.text, "现在阅读 echo.py");
  assert.equal(rm.actor("eng-architect")?.doing, "read");
});
