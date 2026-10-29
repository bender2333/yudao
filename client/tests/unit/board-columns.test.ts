// 事项看板分列与页面名称的单元测试（工单 #303）：取消的事项不再落进部门列；
// run 状态与停止原因的中文名与控制核心一致，停止事项没有部门时页面省略这一格（工单 #556）。
// 工单 #904 在这里核对概览与看板的文字：所在部门一行写三个部门各自的状态与原因、按成果写的进度行、
// 看板卡片上正在工作的部门。期望值写成字面值，不复用实现的公式。

import { test } from "node:test";
import assert from "node:assert/strict";
import { boardColumns } from "../../src/renderer/src/views/project/board.ts";
import { DECISION_BLOCKS,DEPARTMENT_STATE,RUN_STATUS_LABELS,STOP_NOTE_INLINE_LIMIT,STOP_REASON,departmentLine,departmentName,departmentsText,formatTime,label,progressLabel,stopNoteView,workingDepartmentsText } from "../../src/renderer/src/views/project/labels.ts";
import type { WorkItemCard } from "../../src/renderer/src/api/generated/types.gen.ts";


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
    stop_note: null,
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

// ---------------------------------------------------------------------------
// 概览「当前事项」的两行与看板卡片（工单 #904）：所在部门一行写三个部门各自的状态与原因，
// 进度行按成果写，看板卡片写正在工作的部门。期望值是字面值。

test("所在部门一行写三个部门各自的状态与原因，按产品、工程、质检的顺序", () => {
  assert.equal(
    departmentLine({
      product: { state: "waiting" },
      engineering: { state: "working" },
      quality: { state: "working", note: "预测性探索：按 PRD r1 起草测试用例" },
    }, "quality"),
    "产品 等待工作 · 工程 一轮工作中 · 质检 一轮工作中（预测性探索：按 PRD r1 起草测试用例）",
  );
  // 只有一个部门有状态时只写它（查询给几个部门就写几个）
  assert.equal(
    departmentsText({ engineering: { state: "verifying", note: "等质检核验交付 r1" } }),
    "工程 核验中（等质检核验交付 r1）",
  );
});

test("没有 departments 时照旧写所在部门，没有部门时写大厅", () => {
  assert.equal(departmentLine(null, "engineering"), "所在部门：工程");
  assert.equal(departmentLine(undefined, null), "所在部门：大厅");
  assert.equal(departmentsText(null), null);
  assert.equal(departmentLine({}, "product"), "所在部门：产品");
});

test("部门状态的中文名用总图外环的五个词，只写这一处", () => {
  assert.deepEqual(Object.keys(DEPARTMENT_STATE).sort(), ["asking", "verifying", "waiting", "waiting_user", "working"]);
  assert.equal(DEPARTMENT_STATE.waiting_user, "等用户");
  assert.equal(DEPARTMENT_STATE.working, "一轮工作中");
  assert.equal(DEPARTMENT_STATE.asking, "询问中");
  assert.equal(DEPARTMENT_STATE.verifying, "核验中");
  assert.equal(DEPARTMENT_STATE.waiting, "等待工作");
});

test("进度行的三种写法：有交付、没有交付、没有结论", () => {
  // 有交付：当前 PRD 版本、交付版本与它依据的 PRD、对最新交付的结论
  assert.equal(
    progressLabel({
      product_spec_revision: 2,
      delivery_revision: 1,
      delivery_product_spec_revision: 2,
      conclusion: "release",
    }),
    "PRD r2 · 交付 r1（依据 PRD r2）· 结论：放行",
  );
  // 没有交付
  assert.equal(
    progressLabel({ product_spec_revision: 2, delivery_revision: null, delivery_product_spec_revision: null, conclusion: null }),
    "PRD r2 · 还没有交付",
  );
  // 没有结论：这一项不写
  assert.equal(
    progressLabel({ product_spec_revision: 1, delivery_revision: 1, delivery_product_spec_revision: 1, conclusion: null }),
    "PRD r1 · 交付 r1（依据 PRD r1）",
  );
  // 还没有成果时不写这一行
  assert.equal(
    progressLabel({ product_spec_revision: null, delivery_revision: null, delivery_product_spec_revision: null, conclusion: null }),
    null,
  );
});

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

test("查询结果里没有 departments 时看板卡片照旧写事项所在的部门", () => {
  assert.equal(workingDepartmentsText({ department: "engineering" }), "工程");
  assert.equal(workingDepartmentsText({ department: null }), "");
});

// ---------------------------------------------------------------------------
// 停止说明（工单 #1162）：停止原因下面写让事项停下的那条错误的原文，原样显示；
// 空白当作没有这一项；太长时折起来。期望值写成字面值。

test("停止说明原样写错误原文，不改写也不截断", () => {
  const stopped = item({
    work_item_id: "w1",
    status: "stopped",
    stop_reason: "provider_error",
    stop_note: "模型服务返回 HTTP 400：input length 131072 exceeds the maximum",
  });
  assert.deepEqual(stopNoteView(stopped.stop_note), {
    kind: "inline",
    text: "模型服务返回 HTTP 400：input length 131072 exceeds the maximum",
  });
});

test("没有停止说明时不写这一项：放行完成、用户自己停下、字段缺失与空白都一样", () => {
  assert.deepEqual(stopNoteView(item({ work_item_id: "w1", status: "released_unsettled" }).stop_note), { kind: "none" });
  assert.deepEqual(stopNoteView(item({ work_item_id: "w2", status: "stopped", stop_reason: "cancelled" }).stop_note), { kind: "none" });
  assert.deepEqual(stopNoteView(null), { kind: "none" });
  assert.deepEqual(stopNoteView(undefined), { kind: "none" });
  assert.deepEqual(stopNoteView("   "), { kind: "none" });
});

test("停止说明太长时折起来，全文照旧保留", () => {
  const long = `上游返回 400：${"x".repeat(200)}`;
  assert.deepEqual(stopNoteView(long), { kind: "folded", text: long });
  // 恰好到那一个字数的仍然一行写完
  assert.equal(stopNoteView("x".repeat(STOP_NOTE_INLINE_LIMIT)).kind, "inline");
  assert.equal(stopNoteView("x".repeat(STOP_NOTE_INLINE_LIMIT + 1)).kind, "folded");
});

// ---------------------------------------------------------------------------
// 已收下的交付（工单 #1239）：事项停止时，交付已经收下这件事写在停止说明下面一行，
// 带交付的版本与收下的时间；没有这一项时停止说明照旧（上面三条用例已经核对）。

test("停止说明下面多写一行：交付的版本与收下的时间", () => {
  const stopped = item({
    work_item_id: "w1",
    status: "stopped",
    stop_reason: "provider_error",
    stop_note: "模型服务返回 HTTP 400：input length 131072 exceeds the maximum",
    kept_delivery: { version: 2, accepted_at: "2026-01-02T03:04:05Z" },
  });
  const view = stopNoteView(stopped.stop_note, stopped.kept_delivery);
  assert.equal(view.kind, "inline");
  // 时间按页面统一的那一种写法（共用的 formatTime），句中其余是字面值
  assert.equal(view.keptDelivery, `交付 r2 已于 ${formatTime("2026-01-02T03:04:05Z")} 收下，尚未经质检放行`);
});

test("收下的时间缺失时写未知时间，整句照旧写出", () => {
  assert.equal(stopNoteView(null, { version: 3 }).keptDelivery, "交付 r3 已于 未知时间 收下，尚未经质检放行");
});

test("用户自己取消时没有停止说明，已收下的交付照旧写出来", () => {
  // 取消说的是用户的这次决定，交付仍然在：停止说明不写，已收下的交付照旧写
  const view = stopNoteView(null, { version: 1, accepted_at: "2026-01-02T03:04:05Z" });
  assert.equal(view.kind, "none");
  assert.equal(view.keptDelivery, `交付 r1 已于 ${formatTime("2026-01-02T03:04:05Z")} 收下，尚未经质检放行`);
});

test("没有已收下的交付时停止说明不变", () => {
  assert.equal(stopNoteView("出错了").keptDelivery, undefined);
  assert.equal(stopNoteView("出错了", null).keptDelivery, undefined);
  assert.equal(stopNoteView(null).keptDelivery, undefined);
  assert.deepEqual(stopNoteView(null, null), { kind: "none" });
});
