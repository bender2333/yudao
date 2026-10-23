// 恢复观察状态的说法与标记（工单 #747）：正常完成并被采纳的事项不是「已终止」，
// 也不画成「已取消」的标记；被取消的事项一眼看得出是取消；说法里不出现英文内部标识。

import { test } from "node:test";
import assert from "node:assert/strict";
import { RECOVERY_STATE, RECOVERY_STATE_KIND } from "../../src/renderer/src/views/project/labels.ts";

test("七种恢复观察状态都有说法与标记", () => {
  assert.deepEqual(
    Object.keys(RECOVERY_STATE).sort(),
    ["cancelled", "completed", "interrupted", "paused", "running", "stopped", "waiting_resume"],
  );
  for (const state of Object.keys(RECOVERY_STATE)) {
    assert.ok(RECOVERY_STATE[state], `${state} 缺少说法`);
    assert.ok(RECOVERY_STATE_KIND[state], `${state} 缺少标记`);
  }
});

test("正常完成写「已完成」，画成功的标记", () => {
  assert.equal(RECOVERY_STATE.completed, "已完成");
  assert.equal(RECOVERY_STATE_KIND.completed, "succeeded");
  assert.notEqual(RECOVERY_STATE_KIND.completed, "cancelled");
});

test("被取消写「已取消」，标记也是已取消", () => {
  assert.equal(RECOVERY_STATE.cancelled, "已取消");
  assert.equal(RECOVERY_STATE_KIND.cancelled, "cancelled");
});

test("「已终止」不再用来表示完成并采纳", () => {
  assert.equal(RECOVERY_STATE.terminated, undefined);
  for (const text of Object.values(RECOVERY_STATE)) {
    assert.notEqual(text, "已终止");
  }
});

test("暂停与其它结束方式各有自己的说法", () => {
  assert.equal(RECOVERY_STATE.paused, "已暂停");
  assert.equal(RECOVERY_STATE_KIND.paused, "paused");
  assert.equal(RECOVERY_STATE.stopped, "已停止");
  assert.equal(RECOVERY_STATE_KIND.stopped, "failed");
});

test("说法里没有英文内部标识", () => {
  for (const [state, text] of Object.entries(RECOVERY_STATE)) {
    assert.ok(!/[A-Za-z_]/.test(text), `${state} 的说法里有英文：${text}`);
  }
  for (const [state, kind] of Object.entries(RECOVERY_STATE_KIND)) {
    assert.ok(/^[a-z_]+$/.test(kind), `${state} 的标记不是原型标记：${kind}`);
  }
});
