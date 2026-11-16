// 建档状态的纯逻辑单元测试（工单 #137，docs/design/existing-project-onboarding.md docs/design/existing-project-onboarding.md「命令」、「领域事件」、「查询的变化」）：
// 接入拒绝说明的分行、建档状态标记的三种取值，以及由 tool_started 事件驱动的「阅读已有项目」动作。
// 判定全部来自应用层给出的项目行与事件，测试用真实形状的数据驱动这些纯函数。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ONBOARDING_REJECTION_REASONS,
  lastReadExistingAction,
  onboardingProblemText,
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

// 命令失败的形状（工单 #740）：应用层拒绝、接口层校验错误、其余
function problem(rejectionBody) {
  return { kind: "rejected", rejection: rejectionBody };
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



function action(overrides) {
  return { tool: "read_file", department: "product", created_at: "2026-10-07T01:00:00+00:00", ...overrides };
}

// 工单 #1806（保护 R3）：接入失败与校验错误时的中文说明及路径明细保留给独立页面显示
test("接入命令失败时给出中文说明并拆出非法路径条目", () => {
  const rejected = problem(rejection());
  assert.equal(onboardingProblemText(rejected), ONBOARDING_REJECTION_REASONS.source_invalid);
  assert.deepEqual(sourceInvalidLines(rejected), [
    "Links and reparse points are not supported: docs/alpha",
    "Links and reparse points are not supported: docs/beta",
    "Add these paths to the project's ignore rules or delete them.",
  ]);
  const invalid = { kind: "invalid", note: "目录路径格式不对", body: {} };
  assert.equal(onboardingProblemText(invalid), "目录路径格式不对");
  assert.deepEqual(sourceInvalidLines(invalid), []);

  const failed = { kind: "failed", status: 500 };
  assert.match(onboardingProblemText(failed), /没有成功/);
  assert.deepEqual(sourceInvalidLines(failed), []);
});

// 工单 #1806（保护 R2）：左侧栏不保留内联新建/接入表单，独立页面接入统一校验、失败说明与对话跳转
test("左侧栏不再内联渲染新建表单，表单与形态卡由独立页承担", () => {
  const sidebarCode = readFileSync(new URL("../../src/renderer/src/shell/sidebar.tsx", import.meta.url), "utf8");
  assert.equal(sidebarCode.includes("function NewProject"), false);
  assert.equal(sidebarCode.includes("setCreating"), false);
  assert.equal(sidebarCode.includes("v20-new-project"), false);
  assert.equal(sidebarCode.includes("sidebarEntryItems"), true);

  const pageCode = readFileSync(new URL("../../src/renderer/src/views/home/new-project-page.tsx", import.meta.url), "utf8");
  assert.equal(pageCode.includes("FormCards"), true);
  assert.equal(pageCode.includes("cardPickProblem"), true);
  assert.equal(pageCode.includes("projectEntryBody"), true);
  assert.equal(pageCode.includes("onboardingProblemText"), true);
  assert.equal(pageCode.includes("paths.conversation"), true);
});


