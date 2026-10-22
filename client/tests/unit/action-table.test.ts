// 动作与回执表格的列与内容（工单 #655、#658）：「登记名」一列按 ADR-0038 删除命令登记以后
// 恒为「没有回执」，表里不再有这一列；「命令」一列显示动作实际执行的命令原文。

import { test } from "node:test";
import assert from "node:assert/strict";
import { ACTION_TABLE_HEAD, actionCells } from "../../src/renderer/src/views/project/action-table.ts";
import type { ActionReceipt, ActionView } from "../../src/renderer/src/api/generated/types.gen.ts";

function receipt(overrides: Partial<ActionReceipt> = {}): ActionReceipt {
  return {
    args: {},
    ok: true,
    error: null,
    output_ref: null,
    event_id: "evt_1",
    created_at: "2026-10-22T00:00:00Z",
    ...overrides,
  };
}

function action(overrides: Partial<ActionView> = {}): ActionView {
  return {
    action_id: "a_1",
    tool: "bash",
    department: "engineering",
    status: "completed",
    activation_id: null,
    step_id: null,
    input_version: null,
    prompt_version: null,
    created_at: "2026-10-22T00:00:00Z",
    receipt: receipt(),
    ...overrides,
  };
}

test("表格没有「登记名」一列，有「命令」一列", () => {
  assert.deepEqual(ACTION_TABLE_HEAD, ["工具", "命令", "部门", "状态", "结果", "输出引用", "时间"]);
  assert.equal(ACTION_TABLE_HEAD.includes("登记名"), false);
});

test("每一行的内容是工具、命令、部门、状态、结果与输出引用", () => {
  const cells = actionCells(action());
  assert.deepEqual(cells, ["bash", "", "工程", "已完成", "成功", "无"]);
  assert.equal(cells.length, ACTION_TABLE_HEAD.length - 1);
});

test("命令一列显示动作实际执行的命令原文", () => {
  const cells = actionCells(action({
    receipt: receipt({ args: { command: "python -m pytest" } }),
  }));
  assert.equal(cells[1], "python -m pytest");
});

test("没有命令的动作在命令一列留空", () => {
  const cells = actionCells(action({ tool: "read_file", receipt: receipt({ args: { path: "a.py" } }) }));
  assert.equal(cells[1], "");
  assert.equal(actionCells(action({ receipt: null }))[1], "");
});

test("结果按回执写：成功、失败与没有回执", () => {
  assert.equal(actionCells(action({ receipt: receipt({ ok: true }) }))[4], "成功");
  assert.equal(actionCells(action({ receipt: receipt({ ok: false, error: "命令没有成功" }) }))[4], "命令没有成功");
  assert.equal(actionCells(action({ receipt: receipt({ ok: false, error: "" }) }))[4], "失败");
  assert.equal(actionCells(action({ receipt: null }))[4], "没有回执");
});

test("输出引用有的时候写「有（见原始事件）」", () => {
  assert.equal(actionCells(action({ receipt: receipt({ output_ref: { path: "out.txt" } }) }))[5], "有（见原始事件）");
  assert.equal(actionCells(action({ receipt: receipt() }))[5], "无");
});

test("没有部门的动作不写「未知部门」", () => {
  assert.equal(actionCells(action({ department: null }))[2], "");
});
