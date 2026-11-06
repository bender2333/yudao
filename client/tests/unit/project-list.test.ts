// 项目列表的查询参数与可见性（工单 #672）：侧栏的「显示归档的项目」开关要真的作用到查询上，
// 勾上时用 include_archived=true 取数，已归档的项目才出现在列表里、菜单里才有「恢复项目」。
//
// 工单 #1416 起，这个文件也核对首页项目一览的三样事实（此刻在做什么、事项在哪个部门、执行槽位）与
// 项目页的流转汇总、事实元素来源的行：它们原来只在画布上，现在由页面按查询结果写出来。
// 行由 floor-text.ts 的纯函数给出，用例直接调用，不渲染页面、不碰画布。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { projectsListParams, visibleProjects } from "../../src/renderer/src/views/project/project-list.ts";
import type { FactRef, FlowRecord, ProjectLoopResult, ProjectRow, WorkItemLoop } from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  EVENT_KIND_LABELS, factElementRows, flowPairRows, projectDoingText, projectItemsByDepartmentText, projectSlotText,
} from "../../src/renderer/src/views/project/floor-text.ts";

function project(overrides: Partial<ProjectRow> & { project_id: string }): ProjectRow {
  return {
    name: "项目",
    goal: "做一件事",
    status: "",
    archived: false,
    pinned: false,
    ...overrides,
  } as ProjectRow;
}

/** 一条事项：只写用例关心的字段，其余按进行中的样子补齐。 */
function item(overrides: Partial<WorkItemLoop> & { work_item_id: string }): WorkItemLoop {
  return {
    kind: "normal",
    sign: "事项",
    color_index: 1,
    status: "in_progress",
    department: "engineering",
    progress: null,
    round: 1,
    started_at: "2026-01-01T00:00:00Z",
    elapsed_sec: 90,
    time_limit_sec: 7200,
    pending_question: null,
    run_id: "run_1",
    adoption_id: null,
    recovery_state: null,
    stop_reason: null,
    last_department: null,
    version: 1,
    ...overrides,
  };
}

function loop(items: WorkItemLoop[]): ProjectLoopResult {
  return { project_id: "p1", work_items: items, adoptions: [] };
}

/** 一条流转记录：只写用例关心的字段。 */
function flow(overrides: Partial<FlowRecord>): FlowRecord {
  return {
    flow_id: "f1",
    kind: "PRD 新版本",
    status: "已完成",
    content: "",
    direction_from: "product",
    direction_to: "engineering",
    run_id: "run_1",
    work_item_id: "w1",
    position: 1,
    seq: 1,
    event_id: "ev_1",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as FlowRecord;
}

test("勾上开关时项目列表的查询带上 include_archived", () => {
  assert.deepEqual(projectsListParams(true), { include_archived: true });
  assert.deepEqual(projectsListParams(false), { include_archived: false });
});

test("开关关闭时已归档的项目不列出", () => {
  const projects = [project({ project_id: "p1" }), project({ project_id: "p2", archived: true })];
  const visible = visibleProjects(projects, { search: "", includeArchived: false });
  assert.deepEqual(visible.map((row) => row.project_id), ["p1"]);
});

test("开关打开时已归档的项目出现在列表里", () => {
  const projects = [project({ project_id: "p1" }), project({ project_id: "p2", archived: true })];
  const visible = visibleProjects(projects, { search: "", includeArchived: true });
  assert.deepEqual(visible.map((row) => row.project_id), ["p1", "p2"]);
});

// ---------------------------------------------------------------------------
// 首页项目一览（工单 #1416）

test("此刻在做什么：只写在工作的部门与状态词，等待工作的部门不算在做", () => {
  const doing = projectDoingText(loop([item({
    work_item_id: "w1",
    departments: {
      product: { state: "working", note: "回答工程的询问" },
      engineering: { state: "asking", note: "在等待产品的回答" },
      quality: { state: "waiting" },
    },
  })]));
  assert.equal(doing, "产品：一轮工作中（回答工程的询问）；工程：询问中（在等待产品的回答）");
  // 同一部门在两个事项上都在工作时只写一次
  const repeated = projectDoingText(loop([
    item({ work_item_id: "w1", departments: { engineering: { state: "working" } } }),
    item({ work_item_id: "w2", departments: { engineering: { state: "working" } } }),
  ]));
  assert.equal(repeated, "工程：一轮工作中");
  // 没有部门在工作
  assert.equal(projectDoingText(loop([item({ work_item_id: "w1" })])), "没有在做的事");
  assert.equal(projectDoingText(null), "没有在做的事");
});

test("事项在哪个部门：还没结束的事项一行一个，没有部门的写排队，结束的不写", () => {
  const text = projectItemsByDepartmentText(loop([
    item({ work_item_id: "w1", sign: "实现回声工具", department: "engineering" }),
    item({ work_item_id: "w2", sign: "等执行槽位的事项", department: null, status: "not_started" }),
    item({ work_item_id: "w3", sign: "已经采纳的事项", department: "quality", status: "adopted" }),
    item({ work_item_id: "w4", sign: "已停止的事项", department: "engineering", status: "stopped" }),
  ]));
  assert.equal(text, "实现回声工具 · 工程；等执行槽位的事项 · 排队");
  assert.equal(projectItemsByDepartmentText(loop([])), "没有进行中的事项");
});

test("执行槽位：正在执行几个、几个在等", () => {
  assert.equal(
    projectSlotText(loop([
      item({ work_item_id: "w1" }),
      item({ work_item_id: "w2", status: "not_started", department: null }),
    ])),
    "1 个事项正在执行，1 个事项在等执行槽位",
  );
  // 成果挂起的也排在队里（与 projects.list 的 waiting_count 同一口径）
  assert.equal(
    projectSlotText(loop([item({ work_item_id: "w1", status: "held" })])),
    "没有事项正在执行，1 个事项在等执行槽位",
  );
  assert.equal(projectSlotText(loop([])), "没有事项正在执行，没有事项在等执行槽位");
});

// ---------------------------------------------------------------------------
// 项目页的流转汇总（工单 #1416）

test("流转汇总：每对部门的次数、其中返工几次、都是些什么", () => {
  const rows = flowPairRows([
    flow({ flow_id: "f1", direction_from: "product", direction_to: "engineering" }),
    flow({ flow_id: "f2", direction_from: "product", direction_to: "quality" }),
    flow({ flow_id: "f3", kind: "版本交付", direction_from: "product", direction_to: "quality" }),
    flow({ flow_id: "f4", kind: "问题反馈", status: "已退回", direction_from: "quality", direction_to: "engineering" }),
  ]);
  assert.deepEqual(rows, [
    { from: "产品", to: "工程", count: 1, rework: 0, kinds: "PRD 新版本 1" },
    { from: "产品", to: "质检", count: 2, rework: 0, kinds: "PRD 新版本 1、版本交付 1" },
    { from: "质检", to: "工程", count: 1, rework: 1, kinds: "问题反馈 1" },
  ]);
  // 没有去向的交付（没有核验角色）不写成某个部门
  assert.deepEqual(flowPairRows([flow({ direction_to: null })]), [
    { from: "产品", to: "没有", count: 1, rework: 0, kinds: "PRD 新版本 1" },
  ]);
  assert.deepEqual(flowPairRows(null), []);
});

// ---------------------------------------------------------------------------
// 项目页的事实元素与来源（工单 #1416）

test("事实元素：按门牌、包裹、章、箱子、轮次、已用时间的顺序，来源种类写中文", () => {
  const refs: Record<string, FactRef> = {
    box: { position: 12, source: "host_measurement" },
    round: { position: 11, source: "decision_model" },
    sign: { position: 10, source: "rule" },
    stamp: { position: 13, source: "user" },
  };
  const rows = factElementRows(loop([
    item({ work_item_id: "w1", sign: "实现回声工具", refs }),
    item({ work_item_id: "w2", sign: "没有来源的事项" }),
  ]));
  assert.deepEqual(rows.map((row) => [row.itemTitle, row.element, row.elementLabel, row.sourceLabel, row.position]), [
    ["实现回声工具", "sign", "门牌", "规则", 10],
    ["实现回声工具", "stamp", "盖章", "用户", 13],
    ["实现回声工具", "box", "成果库的箱子", "主机测量", 12],
    ["实现回声工具", "round", "轮次", "模型判断", 11],
  ]);
  // 没有来源元素的事项不写行
  assert.deepEqual(factElementRows(loop([item({ work_item_id: "w2" })])), []);
});

// 来源详情写「种类」用页面自己的那份中文名（工单 #1416）：事件种类的清单在
// client/tests/fixtures/event-types.json，缺一种或写成英文都可能把内部标识写到页面上。
test("事件种类的中文名覆盖事件种类清单，每一行都是中文", () => {
  const types = JSON.parse(
    readFileSync(new URL("../fixtures/event-types.json", import.meta.url), "utf8"),
  ) as string[];
  assert.deepEqual(types.filter((type) => !(type in EVENT_KIND_LABELS)), []);
  for (const [type, value] of Object.entries(EVENT_KIND_LABELS)) {
    assert.match(value, /[\u4e00-\u9fa5]/, `${type} 的中文名里没有汉字：${value}`);
  }
});
