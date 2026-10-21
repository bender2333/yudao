// 动作与回执表格的列与内容（工单 #655）：「登记名」一列按 ADR-0038 删除命令登记以后
// 恒为「没有回执」，表里不再有这一列；动作的内容来自工具、部门、状态、回执与输出引用。

import { test } from "node:test";
import assert from "node:assert/strict";
import { ACTION_TABLE_HEAD, actionCells } from "../../src/renderer/src/views/project/action-table.ts";
import type { ActionReceipt, ActionView } from "../../src/renderer/src/api/generated/types.gen.ts";

function receipt(overrides: Partial<ActionReceipt> = {}): ActionReceipt {
  return {
    registered_name: null,
    registered_argv: null,
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

test("表格没有「登记名」一列", () => {
  assert.deepEqual(ACTION_TABLE_HEAD, ["工具", "部门", "状态", "结果", "输出引用", "时间"]);
  assert.equal(ACTION_TABLE_HEAD.includes("登记名"), false);
});

test("回执里带着登记名时也不显示它", () => {
  const cells = actionCells(action({ receipt: receipt({ registered_name: "登记过的命令" }) }));
  assert.equal(cells.includes("登记过的命令"), false);
  assert.equal(cells.some((cell) => cell.includes("登记")), false);
});

test("每一行的内容是工具、部门、状态、结果与输出引用", () => {
  const cells = actionCells(action());
  assert.deepEqual(cells, ["bash", "工程", "已完成", "成功", "无"]);
  assert.equal(cells.length, ACTION_TABLE_HEAD.length - 1);
});

test("结果按回执写：成功、失败与没有回执", () => {
  assert.equal(actionCells(action({ receipt: receipt({ ok: true }) }))[3], "成功");
  assert.equal(actionCells(action({ receipt: receipt({ ok: false, error: "命令没有成功" }) }))[3], "命令没有成功");
  assert.equal(actionCells(action({ receipt: receipt({ ok: false, error: "" }) }))[3], "失败");
  assert.equal(actionCells(action({ receipt: null }))[3], "没有回执");
});

test("输出引用有的时候写「有（见原始事件）」", () => {
  assert.equal(actionCells(action({ receipt: receipt({ output_ref: { path: "out.txt" } }) }))[4], "有（见原始事件）");
  assert.equal(actionCells(action({ receipt: receipt() }))[4], "无");
});

test("没有部门的动作不写「未知部门」", () => {
  assert.equal(actionCells(action({ department: null }))[1], "");
});
