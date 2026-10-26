// 楼层翻译层的测试（工单 #953 验收标准 2）。
//
// 覆盖：覆盖核对里楼层「翻成动作」的每种事件，用一条样例事件翻出至少一个动作，动作的 kind 都在楼层的声明表里；
// 事件翻成动作时带上来源事件的位置（回链）；project.loop 的样例结果翻出的状态通过画面合同的校验；
// 决定请求翻成大厅板上的卡片（文字在这里写好）；输出片段翻成流式文字。

import { test } from "node:test";
import assert from "node:assert/strict";

import { COVERAGE, classOf } from "../../src/renderer/src/translate/coverage.ts";
import { FLOOR_EVENT_TYPES, floorActions, floorCards, floorState, streamText, type FloorEvent } from "../../src/renderer/src/translate/floor.ts";
import { KINDS } from "../../src/renderer/src/pixel/world/floor-decl.ts";
import { floorState as checkFloorState } from "../../src/renderer/src/pixel/contract.ts";
import type { DecisionView, ProjectLoopResult } from "../../src/renderer/src/api/generated/types.gen.ts";

// ---------------------------------------------------------------------------
// 每一条翻成动作的事件都有样例，每种动作都在声明表里

/**
 * 一种事件的样例：默认有位置、部门与事项；需要载荷或工具的事件在这里补上。
 * 一份样例事件翻不出动作时测试失败，所以新增一种翻成动作的事件必须同时给出样例。
 */
const SAMPLE: Record<string, (base: FloorEvent) => FloorEvent> = {
  ask_started: (base) => ({ ...base, department: "engineering", payload: { requester: "engineering", recipient: "product" } }),
  ask_answered: (base) => ({ ...base, department: "product", payload: { requester: "engineering", recipient: "product" } }),
  tool_started: (base) => ({ ...base, tool: "read_file", payload: { name: "a.py" } }),
  tool_skipped: (base) => ({ ...base, tool: "bash", payload: {} }),
  qa_submitted: (base) => ({ ...base, department: "quality", payload: { verdict: "release" } }),
  department_activated: (base) => ({ ...base, department: "product", payload: {} }),
  decision_requested: (base) => ({ ...base, event_id: "evt_d1", payload: { decision_id: "d1", kind: "model_unavailable" } }),
  decision_answered: (base) => ({ ...base, payload: { decision_id: "d1", option: "continue" } }),
  project_decision_requested: (base) => ({ ...base, department: null, event_id: "evt_d2", payload: { kind: "initial_prd" } }),
  project_decision_answered: (base) => ({ ...base, department: null, payload: { decision_id: "d2", option: "accept" } }),
  model_retry_scheduled: (base) => ({ ...base, payload: { n: 2, of: 3 } }),
};

const drawn = COVERAGE.floor.drawn;

test("事件：覆盖核对里楼层翻成动作的每种事件都有一条样例与动作表里的对应", () => {
  const missing = drawn.filter((type) => !FLOOR_EVENT_TYPES.includes(type));
  assert.deepEqual(missing, [], `楼层翻成动作的事件里没有对应的：${missing.join(",")}`);
  const extra = FLOOR_EVENT_TYPES.filter((type) => !drawn.includes(type));
  assert.deepEqual(extra, [], `动作表里有覆盖核对没有登记的事件：${extra.join(",")}`);
});

test("事件：每种翻成动作的事件都用一条样例翻出至少一个动作，动作的 kind 在楼层的声明表里", () => {
  let position = 0;
  for (const type of drawn) {
    assert.equal(classOf(COVERAGE, "floor", type), "drawn", `${type} 在覆盖核对里不是翻成动作`);
    position += 1;
    const base: FloorEvent = {
      type, position, event_id: "evt_sample", project_id: "p1", department: "engineering", role: null,
      tool: null, label: "样例事件", work_item_id: "w1", payload: {},
    };
    const ev = SAMPLE[type] ? SAMPLE[type](base) : base;
    const actions = floorActions(ev);
    assert.ok(actions.length >= 1, `事件 ${type} 没有翻出动作`);
    for (const action of actions) {
      assert.equal(action.position, position, `${type} 的动作没有带上来源事件的位置`);
      assert.ok(
        Object.prototype.hasOwnProperty.call(KINDS, action.kind),
        `${type} 翻出的动作 ${action.kind} 不在楼层的声明表里`,
      );
    }
  }
});

test("事件：PRD 被接纳翻成盖有效章加交接（一条事件翻出两个动作）", () => {
  const actions = floorActions({ type: "spec_accepted", position: 7, department: "product", work_item_id: "w1", label: "产品接纳 PRD", payload: {} });
  assert.deepEqual(actions.map((a) => a.kind), ["stamp_valid", "handoff"]);
  const handoff = actions[1];
  assert.equal(handoff.from, "product");
  assert.equal(handoff.to, "engineering");
  assert.equal(handoff.artifact, "prd");
  assert.ok(typeof handoff.say === "string" && (handoff.say as string).length > 0, "交接没有写下做事一方的话");
  assert.ok(typeof handoff.sayTo === "string" && (handoff.sayTo as string).length > 0, "交接没有写下收东西一方的话");
});

test("事件：质检的放行与返工翻成不同的盖章与包裹去向", () => {
  const release = floorActions({ type: "qa_submitted", position: 9, department: "quality", work_item_id: "w1", label: "质检放行", payload: { verdict: "release" } });
  assert.deepEqual(release.map((a) => a.kind), ["stamp_release", "handoff"]);
  assert.equal(release[1].to, "library");
  assert.equal(release[1].artifact, "release");
  const defect = floorActions({ type: "qa_submitted", position: 10, department: "quality", work_item_id: "w1", label: "质检返工", payload: { verdict: "rework" } });
  assert.deepEqual(defect.map((a) => a.kind), ["stamp_defect", "handoff"]);
  assert.equal(defect[1].to, "engineering");
  assert.equal(defect[1].artifact, "defect");
});

test("事件：询问与回答翻成传信，两端各说一句话", () => {
  const ask = floorActions({ type: "ask_started", position: 3, department: "engineering", work_item_id: "w1", payload: { requester: "engineering", recipient: "product", question: "线路偏好是否改变最短距离" } });
  assert.equal(ask.length, 1);
  assert.equal(ask[0].kind, "letter");
  assert.equal(ask[0].from, "engineering");
  assert.equal(ask[0].to, "product");
  assert.equal((ask[0].say as string).startsWith("现在向产品发出询问"), true);
  const answer = floorActions({ type: "ask_answered", position: 4, department: "product", work_item_id: "w1", payload: { requester: "engineering", recipient: "product", answer: "不改变" } });
  assert.equal(answer[0].kind, "letter");
  assert.equal(answer[0].from, "product");
  assert.equal(answer[0].to, "engineering");
  assert.equal(answer[0].answer, true);
});

test("事件：不在楼层画的种类翻不出动作", () => {
  assert.deepEqual(floorActions({ type: "project_renamed", position: 1, payload: {} }), []);
  assert.deepEqual(floorActions({ type: "catalog_revised", position: 2, payload: {} }), []);
});

test("事件：没有位置的事件抛错，不猜一个位置", () => {
  assert.throws(() => floorActions({ type: "run_done", position: Number.NaN, payload: {} }), /没有位置/);
});

// ---------------------------------------------------------------------------
// project.loop 的样例结果 → 画面合同的楼层状态

const loopRow = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  work_item_id: "w1", kind: "request", sign: "测试事项", color_index: 0, status: "in_progress", department: "engineering",
  progress: null, round: 1, started_at: "2026-10-26T09:00:00+08:00", elapsed_sec: 100, time_limit_sec: 7200,
  pending_question: null, run_id: "r1", adoption_id: null, recovery_state: null, version: 1, ...over,
});

const loopResult = (rows: Record<string, unknown>[]): ProjectLoopResult => ({
  project_id: "p1",
  work_items: rows as never,
  adoptions: [{ adoption_id: "a1", work_item_id: "w1", run_id: "r1" } as never],
});

test("状态：project.loop 的样例结果翻出的状态通过画面合同的校验", () => {
  const state = floorState({
    position: 42,
    loop: loopResult([
      loopRow(),
      loopRow({ work_item_id: "w2", status: "awaiting_initial_prd", department: null }),
      loopRow({ work_item_id: "w3", status: "adopted", department: "quality" }),
      loopRow({ work_item_id: "w4", status: "in_progress", recovery_state: "interrupted", department: "product" }),
      loopRow({ work_item_id: "w5", status: "stopped", department: null }),
      loopRow({ work_item_id: "w6", status: "held", department: "quality" }),
      loopRow({ work_item_id: "w7", status: "released_unsettled", department: "quality" }),
    ]),
    roles: { engineering: [{ id: "e-mgr", name: "工程经理", kind: "manager", status: "working" }] },
    focus: "w1",
  });
  // 合同校验通过（不抛错），并且位置原样带过来
  checkFloorState(state);
  assert.equal(state.position, 42);
  assert.equal(state.items.length, 7);
  // 服务端的说法换成了画面的说法
  assert.deepEqual(state.items.map((it) => it.status), ["working", "asking", "adopted", "interrupted", "cancelled", "paused", "done"]);
  assert.equal(state.items[0].id, "w1");
  assert.equal(state.items[0].work_item_id, "w1");
  assert.equal(state.roles?.engineering[0].status, "working");
  assert.deepEqual(state.shelves.adopted, ["w1"]);
  assert.equal(state.focus_id, "w1");
});

test("状态：部门的忙碌状态经对应表翻成画面的取值，空闲的部门不写进事项", () => {
  const state = floorState({
    position: 5,
    loop: loopResult([
      loopRow({
        departments: {
          engineering: { state: "working", note: null },
          product: { state: "waiting", note: null },
          quality: { state: "waiting_user", note: null },
        },
      }),
    ]),
  });
  assert.deepEqual(state.items[0].departments, { engineering: "working", quality: "waiting_user" });
});

test("状态：没有查角色时 roles 为空，没有查询结果时事项为空", () => {
  const empty = floorState({ position: 1, loop: null });
  checkFloorState(empty);
  assert.deepEqual(empty.items, []);
  assert.equal(empty.roles, null);
});

test("状态：角色的状态经对应表翻好，表里没有的状态抛错", () => {
  const state = floorState({
    position: 1,
    loop: loopResult([loopRow()]),
    roles: { engineering: [{ id: "e-mgr", name: "工程经理", kind: "manager", status: "returned" }] },
  });
  assert.equal(state.roles?.engineering[0].status, "returned");
  assert.throws(
    () => floorState({
      position: 1,
      loop: loopResult([loopRow()]),
      roles: { engineering: [{ id: "e-mgr", name: "工程经理", kind: "manager", status: "在跑" }] },
    }),
    /角色状态/,
  );
});

// ---------------------------------------------------------------------------
// 决定卡片

const decision = (over: Partial<DecisionView> = {}): DecisionView => ({
  decision_id: "d1", project_id: "p1", work_item_id: "w1", kind: "model_unavailable", version: 3,
  status: "open", requested_at: "2026-10-26T09:00:00+08:00", request: {}, blocks: "", blocked: null,
  ...over,
} as DecisionView);

test("卡片：还是等待回答的决定翻成一张卡片，文字在这里写好，需要说明的选项带着提示", () => {
  const cards = floorCards(
    [decision({ request: { options: [{ id: "revise", label: "提出修改", note_required: true }] } as never })],
    () => ({ projectName: "测试项目", workItemTitle: "测试事项" }),
    Date.parse("2026-10-26T09:00:30+08:00"),
  );
  assert.equal(cards.length, 1);
  assert.equal(cards[0].id, "d1");
  assert.equal(cards[0].version, 3);
  assert.ok(cards[0].title.length > 0, "卡片没有标题");
  assert.equal(cards[0].options.length, 1);
  assert.equal(cards[0].options[0].note_missing_text, "「提出修改」需要在说明里写明修改意见");
});

test("卡片：回答完的决定与别的项目的决定不贴到板上", () => {
  const cards = floorCards(
    [decision({ decision_id: "d1", status: "answered" }), decision({ decision_id: "d2", status: "open" })],
    () => ({ projectName: "", workItemTitle: "" }),
    Date.now(),
  );
  assert.deepEqual(cards.map((c) => c.id), ["d2"]);
});

// ---------------------------------------------------------------------------
// 流式文字

test("流式文字：输出片段翻成一句话，别的种类没有", () => {
  const stream = streamText({ type: "model_stream_progress", position: 8, department: "engineering", role: "e-arch", payload: { text: "正在写导出逻辑" } });
  assert.deepEqual(stream, { room: "engineering", role: "e-arch", text: "正在写导出逻辑" });
  assert.equal(streamText({ type: "run_done", position: 9, payload: {} }), null);
});
