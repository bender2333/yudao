// 建档状态的纯逻辑单元测试（工单 #137，docs/design/existing-project-onboarding.md 第 3.1、3.3、3.4 节）：
// 接入拒绝说明的分行、建档状态标记的三种取值，以及由 tool_started 事件驱动的「阅读已有项目」动作。
// 判定全部来自应用层给出的项目行与事件，测试用真实形状的数据驱动这些纯函数。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ONBOARDING_REJECTION_REASONS,
  lastReadExistingAction,
  projectOnboardingMark,
  readExistingAction,
  sourceInvalidLines,
} from "../../src/renderer/src/views/project/onboarding.ts";

function rejection(overrides) {
  return {
    reason: "source_invalid",
    message: "Links and reparse points are not supported: docs/alpha; "
      + "Links and reparse points are not supported: docs/beta; "
      + "Add these paths to the project's ignore rules or delete them.",
    current_version: null,
    ...overrides,
  };
}

function project(overrides) {
  return { project_id: "p1", onboarding_status: null, ...overrides };
}

function decision(overrides) {
  return { decision_id: "d1", project_id: "p1", kind: "initial_prd", status: "open", ...overrides };
}

function toolStarted(overrides) {
  return {
    type: "tool_started",
    position: 12,
    at: "2026-10-06T09:00:00Z",
    run_id: "run_1",
    department: "engineering",
    payload: { name: "read_file" },
    ...overrides,
  };
}

test("拒绝说明按分号分行，每条相对路径各占一行", () => {
  assert.deepEqual(sourceInvalidLines(rejection()), [
    "Links and reparse points are not supported: docs/alpha",
    "Links and reparse points are not supported: docs/beta",
    "Add these paths to the project's ignore rules or delete them.",
  ]);
});

test("只有一条原因时分行给出这一条，空段落不出现", () => {
  assert.deepEqual(
    sourceInvalidLines(rejection({ message: "宿主私有路径不能进入公开快照：.checks" })),
    ["宿主私有路径不能进入公开快照：.checks"],
  );
});

test("接入的每个拒绝原因都有中文说明", () => {
  for (const reason of ["source_invalid", "not_allowed", "not_found", "project_archived", "busy", "provider_unavailable"]) {
    assert.equal(typeof ONBOARDING_REJECTION_REASONS[reason], "string");
    assert.notEqual(ONBOARDING_REJECTION_REASONS[reason], "");
  }
});

test("建档中的项目标记为建档中", () => {
  assert.equal(projectOnboardingMark(project({ onboarding_status: "onboarding" }), []), "建档中");
});

test("停下而没有等待回答的决定请求时标记为等待建档", () => {
  assert.equal(projectOnboardingMark(project({ onboarding_status: "awaiting_onboarding" }), []), "等待建档");
});

test("本项目有等待回答的初始 PRD 决定请求时标记为等待确认初始 PRD", () => {
  const mark = projectOnboardingMark(project({ onboarding_status: "awaiting_onboarding" }), [decision()]);
  assert.equal(mark, "等待确认初始 PRD");
});

test("决定请求已经回答或属于别的项目时不覆盖建档标记", () => {
  assert.equal(
    projectOnboardingMark(project({ onboarding_status: "awaiting_onboarding" }), [decision({ status: "answered" })]),
    "等待建档",
  );
  assert.equal(
    projectOnboardingMark(project({ onboarding_status: "awaiting_onboarding" }), [decision({ project_id: "p2" })]),
    "等待建档",
  );
});

test("没有建档状态的项目没有标记", () => {
  assert.equal(projectOnboardingMark(project(), []), null);
  assert.equal(projectOnboardingMark(project({ onboarding_status: "" }), []), null);
});

test("读取、搜索与区间阅读三种工具驱动阅读已有项目，其他工具不驱动", () => {
  for (const name of ["read_file", "search", "read_range"]) {
    assert.equal(readExistingAction(toolStarted({ payload: { name } })), name);
  }
  for (const name of ["write_file", "run_check", "submit_structure", "list_files"]) {
    assert.equal(readExistingAction(toolStarted({ payload: { name } })), null);
  }
});

test("只有 tool_started 事件驱动阅读已有项目，其他事件不驱动", () => {
  assert.equal(readExistingAction(toolStarted({ type: "tool_called", payload: { name: "read_file" } })), null);
  assert.equal(readExistingAction(toolStarted({ type: "model_message", payload: {} })), null);
});

function action(overrides) {
  return { tool: "read_file", department: "product", created_at: "2026-10-07T01:00:00+00:00", ...overrides };
}

test("页面打开以前已经发生的读取按动作列表读出最近一次", () => {
  const last = lastReadExistingAction([
    action({}),
    action({ tool: "run_check", created_at: "2026-10-07T02:00:00+00:00" }),
    action({ tool: "read_range", department: "quality", created_at: "2026-10-07T03:00:00+00:00" }),
  ]);
  assert.deepEqual(last, { tool: "read_range", department: "quality", at: "2026-10-07T03:00:00+00:00" });
});

test("动作列表里没有读取时没有已发生的读取", () => {
  assert.equal(lastReadExistingAction([]), null);
  assert.equal(lastReadExistingAction([action({ tool: "submit_structure" })]), null);
});