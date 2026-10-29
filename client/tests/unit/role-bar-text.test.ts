// 房间角色条的文字（工单 #1230）：角色的 task 只在有事实说明它此刻做什么时才填；
// 没有时显示房间状态词表里的中文状态（工作中、未工作、等待回答……），
// 不显示 working、idle 这样的原始标识。这里只核对「状态 → 文字」的映射，页面由端到端用例核对。

import { test } from "node:test";
import assert from "node:assert/strict";
import { roleBarText } from "../../src/renderer/src/views/project/labels.ts";

test("角色没有当前任务时显示中文状态词，不显示原始标识", () => {
  assert.equal(roleBarText({ status: "working", task: null }), "工作中");
  assert.equal(roleBarText({ status: "idle", task: null }), "未工作");
  assert.equal(roleBarText({ status: "asking", task: null }), "等待回答");
  assert.equal(roleBarText({ status: "paused", task: null }), "已暂停");
  for (const status of ["working", "idle", "asking", "paused", "failed", "done"]) {
    const text = roleBarText({ status, task: null });
    assert.notEqual(text, status, `${status} 原样显示了原始标识`);
  }
});

test("task 缺失或只有空白时同样显示中文状态词", () => {
  assert.equal(roleBarText({ status: "working" }), "工作中");
  assert.equal(roleBarText({ status: "idle", task: "" }), "未工作");
  assert.equal(roleBarText({ status: "idle", task: "   " }), "未工作");
});

test("有了说明角色此刻做什么的事实以后，task 照原样显示", () => {
  assert.equal(roleBarText({ status: "working", task: "按 PRD r2 核验验收条件" }), "按 PRD r2 核验验收条件");
});

test("词表里没有的状态原样显示，不猜", () => {
  assert.equal(roleBarText({ status: "unknown_state", task: null }), "unknown_state");
});
