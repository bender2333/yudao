// 事项看板分列与页面名称的单元测试（工单 #303）：取消的事项不再落进部门列；
// run 状态与停止原因的中文名与控制核心一致，停止事项没有部门时页面省略这一格（工单 #556）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { BOARD_TITLES, boardColumns } from "../../src/renderer/src/views/project/board.ts";
import { DECISION_BLOCKS, RUN_STATUS_LABELS, STOP_REASON, departmentName, label,
  workingDepartmentsText } from "../../src/renderer/src/views/project/labels.ts";
import type { WorkItemCard } from "../../src/renderer/src/api/generated/types.gen.ts";

const RUN_STATUSES = ["running", "done", "failed", "paused"];

const STOP_REASONS = [
  "released", "baseline_verified", "max_cycles", "model_steps_exhausted", "no_tool_call",
  "workspace_unrepresentable", "time_limit", "cancelled", "user_cancelled", "provider_error", "provider_timeout",
  "provider_protocol", "unsupported_protocol", "retry_after_too_long", "context_overflow",
  "compaction_failed", "host_commit_error", "run_event_version_changed",
];

function item(overrides: Partial<WorkItemCard> & { work_item_id: string }): WorkItemCard {
  const base: Omit<WorkItemCard, "work_item_id"> = {
    kind: "request",
    title: "事项",
    text: "",
    run_id: "run_1",
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    status: "in_progress",
    department: null,
    progress: null,
    round: 1,
    stop_reason: null,
    human_action: null,
    pending_question: null,
    adoption_id: null,
    start_error: null,
  };
  return { ...base, ...overrides };
}

test("取消的事项进已停止列，不落进任何部门列", () => {
  const stopped = item({ work_item_id: "w3", status: "stopped", department: null, stop_reason: "cancelled" });
  const columns = boardColumns([stopped]);
  assert.deepEqual(columns.stopped.map((entry) => entry.work_item_id), ["w3"]);
  assert.deepEqual(columns.product, []);
  assert.deepEqual(columns.engineering, []);
  assert.deepEqual(columns.quality, []);
});

test("部门列按部门分列，已放行与已采纳各自一列", () => {
  const columns = boardColumns([
    item({ work_item_id: "w1", status: "not_started" }),
    item({ work_item_id: "w2", status: "in_progress", department: "engineering" }),
    item({ work_item_id: "w3", status: "in_progress", department: "quality" }),
    item({ work_item_id: "w4", status: "in_progress", department: "product" }),
    item({ work_item_id: "w5", status: "released_unsettled", department: null }),
    item({ work_item_id: "w6", status: "adopted", department: null }),
  ]);
  assert.deepEqual(columns.queue.map((entry) => entry.work_item_id), ["w1"]);
  assert.deepEqual(columns.engineering.map((entry) => entry.work_item_id), ["w2"]);
  assert.deepEqual(columns.quality.map((entry) => entry.work_item_id), ["w3"]);
  assert.deepEqual(columns.product.map((entry) => entry.work_item_id), ["w4"]);
  assert.deepEqual(columns.released.map((entry) => entry.work_item_id), ["w5"]);
  assert.deepEqual(columns.adopted.map((entry) => entry.work_item_id), ["w6"]);
});

test("看板列名与状态词表一致，run 状态只有进行中与三个终态", () => {
  assert.deepEqual(BOARD_TITLES.map(([, title]) => title),
    ["排队中", "产品", "工程", "质检", "已放行", "已采纳", "已停止"]);
  assert.equal(RUN_STATUS_LABELS.running, "进行中");
  assert.deepEqual(Object.keys(RUN_STATUS_LABELS).sort(), [...RUN_STATUSES].sort());
});

test("停止原因与 run 状态的中文名只覆盖控制核心与定义里的取值", () => {
  assert.deepEqual(Object.keys(STOP_REASON).sort(), [...STOP_REASONS].sort());
  assert.equal(label(STOP_REASON, "released"), "已完成并放行");
  assert.equal(label(STOP_REASON, "cancelled"), "运行已被取消");
  for (const name of [...Object.values(RUN_STATUS_LABELS), ...Object.values(STOP_REASON)]) {
    assert.equal(/[A-Za-z]/.test(name.replace("Yudao", "")), false, name);
  }
});

test("决定卡片的阻塞范围标记是中文：不出现内部词 run 与 action", () => {
  assert.deepEqual(Object.keys(DECISION_BLOCKS).sort(), ["action", "run"]);
  assert.equal(label(DECISION_BLOCKS, "run"), "整次运行");
  assert.equal(label(DECISION_BLOCKS, "action"), "单个动作");
  for (const name of Object.values(DECISION_BLOCKS)) {
    assert.equal(/[A-Za-z]/.test(name), false, name);
  }
});

test("停止的事项没有部门时不写「未知部门」，页面自己决定省略还是写「没有」", () => {
  assert.equal(departmentName(null), "");
  assert.equal(departmentName(""), "");
  assert.equal(departmentName("engineering"), "工程");
});

// 看板卡片上正在工作的部门（三部门的循环结构第 3.1 节，工单 #904）：
// 状态是一轮工作中或询问中的部门，按产品、工程、质检的顺序；没有这样的部门时不写这一格。
test("看板卡片写正在工作的部门，按产品、工程、质检的顺序", () => {
  assert.equal(
    workingDepartmentsText({
      department: "product",
      departments: {
        product: { state: "waiting", note: null },
        engineering: { state: "asking", note: "在等待产品的回答" },
        quality: { state: "working", note: "预测性探索：按 PRD r1 起草测试用例" },
      },
    }),
    "工程、质检在工作",
  );
  assert.equal(
    workingDepartmentsText({
      department: null,
      departments: {
        product: { state: "waiting" },
        engineering: { state: "working" },
        quality: { state: "waiting" },
      },
    }),
    "工程在工作",
  );
});

test("没有部门在工作时看板卡片不写这一格", () => {
  assert.equal(
    workingDepartmentsText({
      department: "engineering",
      departments: {
        product: { state: "waiting" },
        engineering: { state: "waiting_user", note: null },
        quality: { state: "verifying", note: "等质检核验交付 r1" },
      },
    }),
    "",
  );
});

test("查询结果里没有 departments 时看板卡片照旧写事项所在的部门（工单 #842）", () => {
  assert.equal(workingDepartmentsText({ department: "engineering" }), "工程");
  assert.equal(workingDepartmentsText({ department: null }), "");
});