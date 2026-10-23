// 决定卡片上的名字（工单 #802）：同一批决定请求在顶栏下拉与首页写同一件事——写项目名与事项标题，
// 不写 wi_ 这样的事项标识。事项标题由调用处按项目的事项列表解析（scopeName），
// 解析不到时是空串，卡片按空串显示（只写项目名）。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import type { DecisionView, WorkItemCard } from "../../src/renderer/src/api/generated/types.gen";
import { scopeName } from "../../src/renderer/src/views/project/scope-name.ts";
import { metaLine } from "../../src/renderer/src/views/decisions/card-logic.ts";

function decision(overrides: Partial<DecisionView> = {}): DecisionView {
  return {
    decision_id: "d1",
    project_id: "p1",
    work_item_id: "wi_87dbd75d55e04231",
    run_id: "r1",
    kind: "model_unavailable",
    blocks: "run",
    version: 3,
    status: "open",
    requested_at: "2026-10-02T10:00:00Z",
    blocked: { work_item_id: "wi_87dbd75d55e04231", queued_after: 0 },
    request: { kind: "model_unavailable", blocks: "run", options: [] },
    answer: null,
    ...overrides,
  } as DecisionView;
}

function workItem(workItemId: string, title: string): WorkItemCard {
  return {
    work_item_id: workItemId,
    kind: "feature",
    title,
    text: title,
    run_id: "r1",
    version: 1,
    created_at: "2026-10-02T09:00:00Z",
    status: "running",
    department: "engineering",
    progress: null,
    round: 1,
    stop_reason: null,
    human_action: null,
    pending_question: null,
    adoption_id: null,
    start_error: null,
  };
}

const items = [workItem("wi_87dbd75d55e04231", "实现逐行处理"), workItem("wi_1", "写交付说明")];

test("事项标题按事项列表解析：取得到写标题，取不到时是空串", () => {
  assert.equal(scopeName(items, "wi_87dbd75d55e04231"), "实现逐行处理");
  assert.equal(scopeName(items, "wi_1"), "写交付说明");
  // 列表里没有这一项、或者没有指定事项时都是空串，不回落到事项标识
  assert.equal(scopeName(items, "wi_not_here"), "");
  assert.equal(scopeName(items, null), "");
});

test("卡片头那一行写项目名与事项标题", () => {
  const line = metaLine(decision(), { projectName: "文本工具", workItemTitle: "实现逐行处理" });
  assert.equal(line, "文本工具 · 实现逐行处理");
});

test("事项标题取不到时卡片不写事项标识", () => {
  const line = metaLine(decision(), { projectName: "文本工具", workItemTitle: "" });
  assert.equal(line, "文本工具");
  assert.ok(!line.includes("wi_"), "页面上不出现事项标识");
});

test("项目名也取不到时写通用的说法", () => {
  const line = metaLine(decision({ project_id: null }), { projectName: "", workItemTitle: "" });
  assert.equal(line, "项目流");
});
