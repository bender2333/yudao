// 房间的翻译层测试（工单 #954 验收标准 2）：把画面与播放设计说明第 6 节的核对落成客户端单元测试。
//
// 覆盖：department.workspace 的样例结果翻出的状态通过画面合同的校验（取值不合法时报错）；
// 覆盖核对里房间「翻成动作」的每种事件，用一条样例事件翻出至少一个动作，动作的 kind 在房间声明表里；
// 交接、询问、回答的几句；流式文字（实时内容）与声明表的检查。

import { test } from "node:test";
import assert from "node:assert/strict";

import { roomState } from "../../src/renderer/src/pixel/contract.ts";
import { ROOM_KINDS } from "../../src/renderer/src/pixel/room/room-decl.ts";
import { COVERAGE } from "../../src/renderer/src/translate/coverage.ts";
import {
  ROOM_ACTION_TYPES,
  ROOM_STREAM_TYPES,
  actions,
  quoted,
  state,
  streamOfEvent,
  streamOfText,
} from "../../src/renderer/src/translate/room.ts";
import type { RoomEvent } from "../../src/renderer/src/translate/room.ts";
import { say } from "../../src/renderer/src/translate/say.ts";

/** 一份录/查出来的房间（department.workspace 的 room 那一块）。 */
function roomSample(over: Record<string, unknown> = {}): { room: Record<string, unknown> } {
  return {
    room: {
      department: "engineering",
      level: "S5",
      status: "working",
      crt: { target: "为待办清单增加截止日期", model: "kimi-k2.6", protocol: "Responses", status: "进行中", cycle: 2 },
      roles: [
        { id: "eng-manager", name: "工程经理", kind: "manager", status: "idle", task: null },
        { id: "eng-architect", name: "工程架构师", kind: "architect", status: "working", task: null },
        { id: "eng-lead", name: "主程", kind: "lead", status: "idle", task: null },
      ],
      pose: { role_id: "eng-architect", action: "typing" },
      door: null,
      hold_card: null,
      mailbox: 1,
      summaries: 2,
      scrolls: 1,
      pinned_notes: 1,
      semantic_cards: 0,
      machine: null,
      remote_unknown: false,
      waiting_provider: false,
      pipes: { out: "idle", letters_waiting: 1 },
      existing_read: false,
      trial: null,
      tool_panel: null,
      self_test: null,
      ...over,
    },
  };
}

// ---------------------------------------------------------------------------
// 状态

test("翻译：department.workspace 的样例结果翻出的状态通过画面合同的校验", () => {
  const s = state({ position: 42, workspace: roomSample() });
  // 画面合同：带位置、房间状态、角色状态与姿势都是画面的词
  roomState(s);
  assert.equal(s.position, 42);
  assert.equal(s.status, "working");
  assert.deepEqual(s.pose, { role_id: "eng-architect", anim: "type" });
  assert.deepEqual((s.roles ?? []).map((r) => [r.id, r.status]), [
    ["eng-manager", "idle"], ["eng-architect", "working"], ["eng-lead", "idle"],
  ]);
  assert.equal((s.pipes as { letters_waiting?: number } | undefined)?.letters_waiting, 1);
});

test("翻译：状态取值不在对应表里时报错，写明是哪一张表、哪个值", () => {
  assert.throws(() => state({ position: 1, workspace: roomSample({ status: "pending_verification" }) }),
    /翻译层没有对应的房间状态：pending_verification/);
  assert.throws(() => state({ position: 1, workspace: roomSample({ pose: { role_id: null, action: "不存在的动作" } }) }),
    /翻译层没有对应的房间姿势：不存在的动作/);
  assert.throws(() => state({ position: 1, workspace: roomSample({ roles: [{ id: "a", name: "A", kind: "agent", status: "unknown" }] }) }),
    /翻译层没有对应的角色状态：unknown/);
});

// ---------------------------------------------------------------------------
// 动作：核对里房间「翻成动作」的每种事件

/** 每种事件的样例：一条事件与它在哪个部门房间里翻出动作。 */
const SAMPLES: [string, RoomEvent, string][] = [
  ["department_activated", { type: "department_activated", position: 1, department: "engineering", label: "工程部门开始工作" }, "engineering"],
  ["department_guidance_received", { type: "department_guidance_received", position: 2, department: "engineering", label: "收到用户的指导" }, "engineering"],
  ["department_guidance_applied", { type: "department_guidance_applied", position: 3, department: "engineering", label: "读了指导" }, "engineering"],
  ["department_guidance_responded", { type: "department_guidance_responded", position: 4, department: "engineering", label: "写了指导的回复" }, "engineering"],
  ["context_assembled", { type: "context_assembled", position: 5, department: "engineering", label: "工程整理资料" }, "engineering"],
  ["model_request_serialized", { type: "model_request_serialized", position: 6, department: "engineering", label: "工程思考" }, "engineering"],
  ["model_requested", { type: "model_requested", position: 7, department: "engineering", label: "工程思考" }, "engineering"],
  ["model_attempt_finished", { type: "model_attempt_finished", position: 8, department: "engineering", label: "工程想到办法" }, "engineering"],
  ["model_attempt_failed", { type: "model_attempt_failed", position: 9, department: "engineering", label: "工程请求失败" }, "engineering"],
  ["model_retry_scheduled", { type: "model_retry_scheduled", position: 10, department: "engineering", label: "等一会儿再试", payload: { n: 1, of: 3 } }, "engineering"],
  ["tool_started", { type: "tool_started", position: 11, department: "engineering", tool: "read_file", label: "工程读文件" }, "engineering"],
  ["tool_called", { type: "tool_called", position: 12, department: "engineering", tool: "bash", label: "工程跑命令", payload: { ok: true } }, "engineering"],
  ["tool_skipped", { type: "tool_skipped", position: 13, department: "engineering", label: "这个工具没有获准" }, "engineering"],
  ["proposal_submitted", { type: "proposal_submitted", position: 14, department: "engineering", label: "工程提交交付说明" }, "engineering"],
  ["proposal_rejected", { type: "proposal_rejected", position: 15, department: "engineering", label: "提案被退回" }, "engineering"],
  ["spec_accepted", { type: "spec_accepted", position: 16, department: "product", label: "PRD 被接纳" }, "product"],
  ["contract_accepted", { type: "contract_accepted", position: 17, department: "product", label: "PRD 被接纳" }, "product"],
  ["product_decision_accepted", { type: "product_decision_accepted", position: 18, department: "product", label: "产品决定被接纳" }, "product"],
  ["delivery_accepted", { type: "delivery_accepted", position: 19, department: "engineering", label: "交付被接纳" }, "engineering"],
  ["structure_accepted", { type: "structure_accepted", position: 20, department: "engineering", label: "结构说明被接纳" }, "engineering"],
  ["qa_submitted", { type: "qa_submitted", position: 21, department: "quality", label: "质检提交结论", payload: { verdict: "release" } }, "quality"],
  ["ask_started", { type: "ask_started", position: 22, department: "engineering", label: "工程向产品询问", payload: { requester: "engineering", recipient: "product", question: "线路偏好是否改变" } }, "engineering"],
  ["ask_answered", { type: "ask_answered", position: 23, department: "product", label: "产品回答工程", payload: { requester: "engineering", recipient: "product", answer: "不改变" } }, "product"],
  ["compaction_recorded", { type: "compaction_recorded", position: 24, department: "engineering", label: "工程整理成摘要" }, "engineering"],
  ["compaction_failed", { type: "compaction_failed", position: 25, department: "engineering", label: "整理没有生效" }, "engineering"],
  ["run_paused", { type: "run_paused", position: 26, department: "engineering", label: "先暂停一下" }, "engineering"],
  ["run_failed", { type: "run_failed", position: 27, department: "engineering", label: "运行失败", payload: { stop_reason: "time_limit", message: "运行时间已达上限" } }, "engineering"],
  ["run_done", { type: "run_done", position: 28, department: "engineering", label: "事项完成" }, "engineering"],
  ["run_resumed", { type: "run_resumed", position: 29, department: "engineering", label: "中断的运行自动继续" }, "engineering"],
  ["run_continued", { type: "run_continued", position: 30, department: "engineering", label: "运行从暂停位置继续" }, "engineering"],
  ["decision_requested", { type: "decision_requested", position: 31, department: "engineering", label: "提出等待回答的决定（model_unavailable）", payload: { kind: "model_unavailable", description: "模型引用用不了" } }, "engineering"],
];

test("翻译：覆盖核对里房间翻成动作的每种事件都翻出至少一个动作，kind 在房间声明表里", () => {
  const drawn = new Set(COVERAGE.room.drawn);
  // 样例与覆盖核对一一对应：覆盖核对里有的事件都要有样例
  assert.deepEqual(SAMPLES.map(([type]) => type).sort(), [...drawn].sort());
  for (const [type, ev, dept] of SAMPLES) {
    const list = actions(ev, dept);
    assert.ok(list.length >= 1, `${type} 没有翻出动作`);
    for (const a of list) {
      assert.ok(ROOM_KINDS[a.kind], `${type} 翻出了声明表里没有的动作 ${a.kind}`);
      assert.equal(a.position, ev.position, `${type} 的动作没有带位置`);
    }
  }
});

test("翻译：翻成动作的事件与声明表的种类和覆盖核对一致；流式文字的种类也一致", () => {
  assert.deepEqual([...ROOM_ACTION_TYPES].sort(), [...COVERAGE.room.drawn].sort());
  assert.deepEqual([...ROOM_STREAM_TYPES].sort(), [...COVERAGE.room.realtime].sort());
  // 动作表里给出的 kind 都在声明表里
  for (const [type, ev, dept] of SAMPLES) {
    for (const a of actions(ev, dept)) assert.ok(ROOM_KINDS[a.kind], `${type} → ${a.kind}`);
  }
});

test("翻译：一条事件可以翻成几个动作——PRD 被接纳是盖有效章加交接", () => {
  const ev: RoomEvent = { type: "spec_accepted", position: 7, department: "product", label: "PRD 被接纳" };
  assert.deepEqual(actions(ev, "product").map((a) => a.kind), ["stamp_valid", "handoff"]);
  const h = actions(ev, "product")[1];
  assert.equal(h.from, "product");
  assert.equal(h.to, "engineering");
  assert.equal(h.artifact, "prd");
  assert.equal(h.say, "现在把PRD送给工程");
  // 别的部门：产品盖完章以后包裹才送到，工程房间里只有收到的那一端
  assert.deepEqual(actions(ev, "engineering").map((a) => a.kind), ["handoff"]);
  assert.equal(actions(ev, "engineering")[0].sayTo, "收到PRD，来自产品");
  assert.deepEqual(actions(ev, "quality"), []);
});

test("翻译：交接的包裹是画面合同的四种之一，两端说的话不同", () => {
  const delivered: RoomEvent = { type: "delivery_accepted", position: 9, department: "engineering", label: "交付被接纳" };
  assert.deepEqual(actions(delivered, "engineering").map((a) => a.kind), ["seal", "handoff"]);
  const h = actions(delivered, "engineering")[1];
  assert.equal(h.artifact, "box");
  assert.equal(h.say, "现在把交付箱送给质检");
  // 缺陷记录经回流管道送回工程
  const rework: RoomEvent = { type: "qa_submitted", position: 11, department: "quality", label: "质检结论", payload: { verdict: "rework_engineering" } };
  assert.deepEqual(actions(rework, "quality").map((a) => a.kind), ["stamp_rework", "handoff"]);
  assert.equal(actions(rework, "quality")[1].artifact, "defect");
  assert.equal(actions(rework, "engineering")[0].sayTo, "收到返工单，来自质检");
});

test("翻译：询问与回答的两端各说一句，别的部门不画", () => {
  const ask: RoomEvent = {
    type: "ask_started", position: 13, department: "engineering",
    label: "工程向产品询问：线路偏好是否改变最短距离",
    payload: { requester: "engineering", recipient: "product", question: "线路偏好是否改变最短距离" },
  };
  assert.deepEqual(actions(ask, "engineering").map((a) => a.kind), ["send_letter"]);
  assert.equal(actions(ask, "engineering")[0].say, "现在向产品发出询问：线路偏好是否改变最短距离");
  assert.deepEqual(actions(ask, "product").map((a) => a.kind), ["answer_letter"]);
  assert.equal(actions(ask, "product")[0].reads, true);
  assert.equal(actions(ask, "product")[0].say, "收到工程的询问：线路偏好是否改变最短距离");
  assert.deepEqual(actions(ask, "quality"), []);

  const reply: RoomEvent = {
    type: "ask_answered", position: 14, department: "product",
    label: "产品回答工程：不改变",
    payload: { requester: "engineering", recipient: "product", answer: "不改变" },
  };
  assert.deepEqual(actions(reply, "product").map((a) => a.kind), ["answer_letter"]);
  assert.equal(actions(reply, "product")[0].reads, false);
  assert.equal(actions(reply, "product")[0].say, "现在回答工程的询问");
  assert.equal(actions(reply, "engineering")[0].say, "收到产品的回答：不改变");
});

test("翻译：工具的名称落到专门的动作，没有专门动作的工具是进度", () => {
  const tool = (name: string): string[] =>
    actions({ type: "tool_started", position: 20, department: "engineering", tool: name, label: "工程调用工具" }, "engineering").map((a) => a.kind);
  assert.deepEqual(tool("search"), ["search"]);
  assert.deepEqual(tool("read_file"), ["read"]);
  assert.deepEqual(tool("edit_range"), ["write"]);
  assert.deepEqual(tool("list_files"), ["tool_progress"]);
  assert.deepEqual(tool("delete_file"), ["tool_progress"]);
  assert.deepEqual(tool("move_file"), ["tool_progress"]);
  assert.deepEqual(tool("bash"), ["run_command"]);
  assert.deepEqual(tool("run_check"), ["inspect"]);
  assert.deepEqual(tool("browser_navigate"), ["self_test"]);
  assert.deepEqual(tool("some_new_tool"), ["tool_progress"]);
  // 工具结束：命令亮退出状态灯，其余工具结束时不画
  assert.deepEqual(actions({ type: "tool_called", position: 21, department: "engineering", tool: "bash", payload: { ok: false } }, "engineering").map((a) => a.kind), ["command_done"]);
  assert.deepEqual(actions({ type: "tool_called", position: 22, department: "engineering", tool: "read_file", payload: {} }, "engineering"), []);
});

test("翻译：结果未知的动作头顶黄色问号，模型不能用时举待恢复的牌子", () => {
  const unknown: RoomEvent = { type: "decision_requested", position: 30, department: "engineering", label: "决定", payload: { kind: "unknown_action" } };
  assert.deepEqual(actions(unknown, "engineering").map((a) => a.kind), ["puzzled"]);
  const unavailable: RoomEvent = {
    type: "decision_requested", position: 31, department: "engineering",
    label: "提出等待回答的决定（model_unavailable）",
    payload: { kind: "model_unavailable", description: "模型引用用不了" },
  };
  const held = actions(unavailable, "engineering");
  assert.deepEqual(held.map((a) => a.kind), ["hold_card"]);
  assert.equal(held[0].text, "模型引用用不了");
  // 其余的决定在楼层的大厅板上，房间里不画
  assert.deepEqual(actions({ type: "decision_requested", position: 32, department: "engineering", payload: { kind: "no_tool_call" } }, "engineering"), []);
});

// ---------------------------------------------------------------------------
// 说话与流式文字

test("翻译：说话的内容只来自事件已经带着的事实", () => {
  assert.equal(say({ type: "proposal_submitted", department: "engineering", label: "工程经理代表部门提交交付说明", payload: {} }), "现在提交交付说明");
  assert.equal(say({ type: "proposal_submitted", department: "quality", payload: { kind: "qa_review" } }), "现在提交质检结论");
  assert.equal(say({ type: "tool_started", department: "engineering", tool: "run_command", label: "工程部门走到终端执行命令 npm_test" }), "现在执行 npm_test");
  assert.equal(say({ type: "tool_started", department: "engineering", label: "工程部门执行命令", payload: { tool: "bash", command: "npm test" } }), "现在执行 npm test");
  // 动作上带着这句话：房间里的小人按动作说的话说
  const acted = actions({ type: "proposal_submitted", position: 40, department: "engineering", label: "工程经理代表部门提交交付说明" }, "engineering")[0];
  assert.equal(acted.say, "现在提交交付说明");
});

test("翻译：事件说明里「」括起的部分作为内容", () => {
  assert.equal(quoted("工程部门写「第 3 步」的说明"), "第 3 步");
  assert.equal(quoted(null), null);
});

test("翻译：模型输出片段作为流式文字交给画面，不进时间线", () => {
  const ev: RoomEvent = { type: "model_stream_progress", position: 50, department: "engineering", role: "eng-architect", payload: { text: "正在阅读需求" } };
  assert.deepEqual(streamOfEvent(ev), { who: { room: "engineering", role: "eng-architect" }, text: "正在阅读需求" });
  // 输出片段与 attempt.live 已收到的文字走同一个出口
  assert.deepEqual(streamOfText("engineering", null, "正在整理验收条件"), {
    who: { room: "engineering", role: null }, text: "正在整理验收条件",
  });
  assert.equal(streamOfEvent({ type: "tool_started", position: 51, department: "engineering" }), null);
});
