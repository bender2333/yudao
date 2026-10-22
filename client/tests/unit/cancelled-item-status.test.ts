// 事项状态行里的阶段名（工单 #657）：用户主动取消的事项不写「执行失败」。
// 后端把取消的终态记成 phase=FAILED 配 stop_reason=cancelled，真正失败时也是 FAILED，
// 区别只在停止原因上；取消是用户自己的决定，页面上不该说失败。

import { test } from "node:test";
import assert from "node:assert/strict";
import { phaseLabel } from "../../src/renderer/src/views/project/labels.ts";

test("取消过的事项不写「执行失败」", () => {
  assert.equal(phaseLabel("FAILED", "cancelled"), null);
});

test("用户放弃的建档也不写阶段名：run 跑完了，事项是被用户放弃的", () => {
  // 工单 #707：写「已完成」与「已停止」挨在一起读起来自相矛盾
  assert.equal(phaseLabel("DONE", "user_cancelled"), null);
});

test("真正的失败仍然写「执行失败」", () => {
  assert.equal(phaseLabel("FAILED", "provider_error"), "执行失败");
  assert.equal(phaseLabel("FAILED", "time_limit"), "执行失败");
  assert.equal(phaseLabel("FAILED", "provider_timeout"), "执行失败");
  assert.equal(phaseLabel("FAILED", null), "执行失败");
});

test("没有阶段名时不写阶段", () => {
  assert.equal(phaseLabel(null, "cancelled"), null);
  assert.equal(phaseLabel("", null), null);
  assert.equal(phaseLabel(undefined, undefined), null);
});

test("进行中的事项写自己的阶段名", () => {
  assert.equal(phaseLabel("ENGINEERING", null), "工程处理中");
  assert.equal(phaseLabel("PRODUCT_SPEC", null), "产品处理中");
});

test("取消以外的其他停止原因照旧写阶段名", () => {
  assert.equal(phaseLabel("FAILED", "max_cycles"), "执行失败");
  assert.equal(phaseLabel("QUALITY", "released"), "质检处理中");
});
