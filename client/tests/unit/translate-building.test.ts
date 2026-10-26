// 楼的翻译层的测试（工单 #955 验收标准 2）。
//
// 覆盖：覆盖核对里楼「翻成动作」的每种事件，用一条样例事件翻出至少一个动作，动作的 kind 都在楼的声明表里；
// 事件翻成动作时带上来源事件的位置（回链）；projects.list 与 project.loop 的样例翻出的状态通过画面合同的校验；
// 进行中的事项所在的层亮灯（原来 sceneStatus 的行为），楼层的状态灯与服务端的 held（#952 的结论）；
// 项目按置顶与最近活动排列、归档的不显示。

import { test } from "node:test";
import assert from "node:assert/strict";

import { FLOOR_SIGNS, buildingState as checkBuildingState } from "../../src/renderer/src/pixel/contract.ts";
import { BUILDING_KINDS } from "../../src/renderer/src/pixel/building/building-decl.ts";
import { COVERAGE, classOf } from "../../src/renderer/src/translate/coverage.ts";
import {
  BUILDING_EVENT_TYPES, buildingActions, buildingState, sortBuildingProjects, toBuildingEvent,
  type BuildingEvent,
} from "../../src/renderer/src/translate/building.ts";
import type { EventObject, ProjectLoopResult, ProjectRow, WorkItemLoop } from "../../src/renderer/src/api/generated/types.gen.ts";

// ---------------------------------------------------------------------------
// 每一条翻成动作的事件都有样例，每种动作都在声明表里

/**
 * 一种事件的样例：默认有位置、项目与事项；需要载荷的事件在这里补上。
 * 一份样例事件翻不出动作时测试失败，所以新增一种翻成动作的事件必须同时给出样例。
 */
const SAMPLE: Record<string, (base: BuildingEvent) => BuildingEvent> = {
  ask_started: (base) => ({ ...base, department: "engineering", payload: { requester: "engineering", recipient: "product" } }),
  ask_answered: (base) => ({ ...base, department: "product", payload: { requester: "engineering", recipient: "product" } }),
  qa_submitted: (base) => ({ ...base, department: "quality", payload: { verdict: "release" } }),
  department_activated: (base) => ({ ...base, department: "product", payload: {} }),
};

const drawn = COVERAGE.building.drawn;

test("事件：覆盖核对里楼翻成动作的每种事件都有一条样例与动作表里的对应", () => {
  const missing = drawn.filter((type) => !BUILDING_EVENT_TYPES.includes(type));
  assert.deepEqual(missing, [], `楼翻成动作的事件里没有对应的：${missing.join(",")}`);
  const extra = BUILDING_EVENT_TYPES.filter((type) => !drawn.includes(type));
  assert.deepEqual(extra, [], `动作表里有覆盖核对没有登记的事件：${extra.join(",")}`);
});

test("事件：每种翻成动作的事件都用一条样例翻出至少一个动作，动作的 kind 在楼的声明表里", () => {
  let position = 0;
  for (const type of drawn) {
    assert.equal(classOf(COVERAGE, "building", type), "drawn", `${type} 在覆盖核对里不是翻成动作`);
    position += 1;
    const base: BuildingEvent = {
      type, position, project_id: "p1", department: "engineering", work_item_id: "w1", payload: {},
    };
    const ev = SAMPLE[type] ? SAMPLE[type](base) : base;
    const actions = buildingActions(ev);
    assert.ok(actions.length >= 1, `事件 ${type} 没有翻出动作`);
    for (const action of actions) {
      assert.equal(action.position, position, `${type} 的动作没有带上来源事件的位置`);
      assert.equal(action.project, "p1", `${type} 的动作没有写在某层上`);
      assert.ok(
        Object.prototype.hasOwnProperty.call(BUILDING_KINDS, action.kind),
        `${type} 翻出的动作 ${action.kind} 不在楼的声明表里`,
      );
    }
  }
});

test("事件：采纳翻成撒彩带，放行与返工、决定请求与部门开始工作翻成不同颜色的闪光", () => {
  const celebrate = buildingActions({ type: "deliverable_adopted", position: 3, project_id: "p1", payload: {} });
  assert.deepEqual(celebrate.map((a) => a.kind), ["celebrate"]);
  assert.equal(celebrate[0].color, undefined, "撒彩带的颜色由楼的演法定，动作不带");

  const release = buildingActions({ type: "qa_submitted", position: 4, project_id: "p1", payload: { verdict: "release" } });
  assert.equal(release[0].kind, "floor_flash");
  assert.equal(release[0].color, "green");
  const rework = buildingActions({ type: "qa_submitted", position: 5, project_id: "p1", payload: { verdict: "rework" } });
  assert.equal(rework[0].color, "red");

  for (const type of ["decision_requested", "decision_answered", "project_decision_requested", "project_decision_answered"]) {
    const actions = buildingActions({ type, position: 6, project_id: "p1", payload: {} });
    assert.equal(actions[0].color, "yellow", `${type} 不是黄光`);
  }
  const activated = buildingActions({ type: "department_activated", position: 7, project_id: "p1", payload: {} });
  assert.equal(activated[0].color, "white");
});

test("事件：楼不画的事件翻不出动作；没有位置的事件抛错，没有项目的事件不画", () => {
  for (const type of ["project_renamed", "tool_started", "spec_accepted", "run_done", "model_stream_progress"]) {
    assert.deepEqual(buildingActions({ type, position: 1, project_id: "p1", payload: {} }), [], `${type} 在楼上不该有动作`);
  }
  assert.throws(() => buildingActions({ type: "ask_started", position: Number.NaN, project_id: "p1", payload: {} }), /没有位置/);
  assert.deepEqual(buildingActions({ type: "department_activated", position: 2, project_id: null, payload: {} }), []);
});

test("事件：事件信封里的事件转成楼事件的形状，位置原样带过来", () => {
  const event = {
    type: "department_activated", position: 17, event_id: "evt_1", project_id: "p1", work_item_id: "w1",
    department: "product", payload: { previous: 0 },
  } as unknown as EventObject;
  const ev = toBuildingEvent(event);
  assert.equal(ev.position, 17);
  assert.equal(ev.project_id, "p1");
  assert.equal(ev.department, "product");
  assert.deepEqual(ev.payload, { previous: 0 });
  assert.equal(buildingActions(ev)[0].kind, "floor_flash");
});

// ---------------------------------------------------------------------------
// projects.list 与 project.loop 的样例结果 → 画面合同的楼的状态

const projectRow = (over: Partial<ProjectRow> = {}): ProjectRow => ({
  project_id: "p1", name: "待办清单网页", goal: "记账", source: "", pinned: false, archived: false,
  created_at: "2026-10-26T09:00:00+08:00", updated_at: "2026-10-26T09:00:00+08:00", version: 1,
  work_item_count: 1, in_progress_count: 1, waiting_count: 0, decisions_waiting: 0,
  last_activity_at: "2026-10-26T09:00:00+08:00", active_work_item_id: null, current_adoption: null,
  onboarding_status: null, interrupted_count: 0, waiting_resume_count: 0,
  ...over,
});

const item = (over: Record<string, unknown> = {}): WorkItemLoop => ({
  work_item_id: "w1", kind: "change", sign: "增加导出", color_index: 0, status: "in_progress", department: "engineering",
  progress: null, departments: null, round: 1, started_at: "2026-10-26T09:00:00+08:00", elapsed_sec: 100,
  time_limit_sec: 7200, pending_question: null, run_id: "r1", adoption_id: null, recovery_state: null, version: 1,
  ...over,
} as unknown as WorkItemLoop);

const loop = (rows: WorkItemLoop[], projectId = "p1"): ProjectLoopResult => ({
  project_id: projectId, work_items: rows, adoptions: [],
});

test("状态：projects.list 与 project.loop 的样例翻出的状态通过画面合同的校验", () => {
  const state = buildingState({
    position: 42,
    projects: [projectRow({ decisions_waiting: 2 })],
    loops: {
      p1: loop([
        item(),
        item({ work_item_id: "w2", status: "awaiting_initial_prd", department: null }),
        item({ work_item_id: "w3", status: "adopted", department: "quality" }),
        item({ work_item_id: "w4", status: "in_progress", recovery_state: "interrupted", department: "product" }),
        item({ work_item_id: "w5", status: "stopped", department: null }),
        item({ work_item_id: "w6", status: "held", department: "quality" }),
        item({ work_item_id: "w7", status: "released_unsettled", department: "quality" }),
      ]),
    },
  });
  // 翻译层翻完已经按画面合同校验过，这里按验收标准再核一次：状态灯都是合同的取值
  assert.deepEqual(checkBuildingState(state), state);
  assert.equal(state.position, 42);
  const floor = state.floors[0];
  assert.ok(FLOOR_SIGNS.includes(floor.status));
  // 状态灯按 tables.ts 的优先顺序：待恢复、中断在前
  assert.equal(floor.status, "interrupted");
  // 进行中的事项所在的部门亮灯（服务端的 in_progress 翻成 working）
  assert.equal(floor.lit.engineering, true);
  assert.equal(floor.lit.product, false);
  assert.equal(floor.lit.quality, false);
  // 小旗：在房间里的事项；排队、采纳与用户停止的不在房间里
  assert.deepEqual(floor.flags.map((f) => [f.work_item_id, f.department]), [
    ["w1", "engineering"],
    ["w4", "product"],
    ["w6", "quality"],
    ["w7", "quality"],
  ]);
  assert.equal(floor.valve_closed, false);
  assert.equal(floor.decisions, 2);
  assert.equal(floor.has_ops, false);
  assert.equal(state.show_basement, false);
});

test("状态灯：几个部门同时工作时几个房间同时亮灯（部门的状态也认画面合同的取值）", () => {
  const state = buildingState({
    position: 1,
    projects: [projectRow()],
    loops: {
      p1: loop([item({
        department: "engineering",
        departments: { engineering: { state: "working" }, product: { state: "asking" } },
      })]),
    },
  });
  assert.equal(state.floors[0].lit.engineering, true);
  assert.equal(state.floors[0].lit.product, true);
  assert.equal(state.floors[0].lit.quality, false);
});

test("状态灯：事项停在工程、质检同时在预测性探索时这一层两个房间都亮灯，小旗只在工程", () => {
  // 工单 #958 验收标准 1 的楼那一半：几个部门同时工作时几个房间同时亮灯；小旗只在事项所在的房间
  const state = buildingState({
    position: 1,
    projects: [projectRow()],
    loops: {
      p1: loop([item({
        work_item_id: "w1",
        department: "engineering",
        departments: {
          engineering: { state: "working", note: null },
          quality: { state: "working", note: "预测性探索：按 PRD r1 起草测试用例" },
          product: { state: "waiting", note: null },
        },
      })]),
    },
  });
  const floor = state.floors[0];
  assert.equal(floor.lit.engineering, true);
  assert.equal(floor.lit.quality, true);
  assert.equal(floor.lit.product, false);
  assert.deepEqual(floor.flags.map((flag) => [flag.work_item_id, flag.department]), [["w1", "engineering"]]);
});

test("状态灯：进行中的事项所在的层亮灯，原来 sceneStatus 的行为不变", () => {
  // 服务端的 in_progress 翻成画面的 working：这一层亮灯、事项在房间里
  const working = buildingState({ position: 1, projects: [projectRow()], loops: { p1: loop([item()]) } });
  assert.equal(working.floors[0].status, "working");
  assert.equal(working.floors[0].lit.engineering, true);
  // 停在模型不可用（waiting_resume）的层：待恢复
  const resume = buildingState({
    position: 1, projects: [projectRow()],
    loops: { p1: loop([item({ recovery_state: "waiting_resume" })]) },
  });
  assert.equal(resume.floors[0].status, "waiting_resume");
  // 已登记还没开始的层：排队中（阀门在「等待执行槽位」时关闭，服务端还没有这个取值）
  const slot = buildingState({ position: 1, projects: [projectRow()], loops: { p1: loop([item({ status: "not_started" })]) } });
  assert.equal(slot.floors[0].status, "queued");
  assert.equal(slot.floors[0].valve_closed, false);
  // 恢复观察状态里的待核实不再是一种画面状态（#951 删了它）：按事项状态画
  const verified = buildingState({
    position: 1, projects: [projectRow()],
    loops: { p1: loop([item({ recovery_state: "pending_verification" })]) },
  });
  assert.equal(verified.floors[0].status, "working");
});

test("状态灯：只有已结束的事项时显示空闲", () => {
  const history = ["stopped", "adopted", "released_unsettled"].map((status, index) =>
    item({ work_item_id: `history-${index}`, status, department: null }));
  const state = buildingState({ position: 1, projects: [projectRow()], loops: { p1: loop(history) } });
  assert.equal(state.floors[0].status, "idle");
  assert.deepEqual(state.floors[0].lit, { product: false, engineering: false, quality: false, operations: false });
  assert.deepEqual(state.floors[0].flags, []);
});

test("状态灯：历史停止的事项与正在工作的事项同时出现时显示运行中", () => {
  const state = buildingState({
    position: 1,
    projects: [projectRow()],
    loops: {
      p1: loop([
        item({ work_item_id: "cancelled", status: "stopped", department: null, color_index: 0 }),
        item({ work_item_id: "working", status: "in_progress", department: "engineering", color_index: 1 }),
      ]),
    },
  });
  assert.equal(state.floors[0].status, "working");
  assert.equal(state.floors[0].lit.engineering, true);
  assert.deepEqual(state.floors[0].flags.map((flag) => flag.work_item_id), ["working"]);
});

test("状态灯：服务端的 held 翻成 paused，不决定灯；事项仍然留在房间里（#952 的结论）", () => {
  const state = buildingState({
    position: 1, projects: [projectRow()],
    loops: { p1: loop([item({ status: "held", department: "quality" })]) },
  });
  assert.equal(state.floors[0].status, "idle");
  assert.deepEqual(state.floors[0].flags.map((flag) => flag.work_item_id), ["w1"]);
});

test("状态灯：服务端没有对应表的状态抛错，错误写明是哪个值", () => {
  assert.throws(
    () => buildingState({ position: 1, projects: [projectRow()], loops: { p1: loop([item({ status: "unknown" })]) } }),
    /翻译层没有对应的事项状态：unknown/,
  );
});

test("状态：项目按置顶在上、其余按最近活动排列，归档的不显示", () => {
  const projects = [
    projectRow({ project_id: "p-a", name: "早的", last_activity_at: "2026-10-20T00:00:00+08:00" }),
    projectRow({ project_id: "p-b", name: "近的", last_activity_at: "2026-10-25T00:00:00+08:00" }),
    projectRow({ project_id: "p-c", name: "置顶的", pinned: true, last_activity_at: "2026-10-01T00:00:00+08:00" }),
    projectRow({ project_id: "p-d", name: "归档的", archived: true }),
  ];
  assert.deepEqual(sortBuildingProjects(projects).map((p) => p.name), ["置顶的", "近的", "早的"]);
  const state = buildingState({ position: 1, projects, loops: {} });
  assert.deepEqual(state.floors.map((f) => f.name), ["置顶的", "近的", "早的"]);
  // 还没有查到的项目那一层按空闲画，一层也不少
  assert.deepEqual(state.floors.map((f) => f.status), ["idle", "idle", "idle"]);
});
