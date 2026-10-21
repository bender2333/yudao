// 重新订阅事件流的起点（工单 #659）：不能被视图的 0 位置拖回 0，
// 也不能比事件流已经读到的位置更早——退回去会重放整段历史，页面反复重新同步。

import { test } from "node:test";
import assert from "node:assert/strict";
import { resubscribePosition } from "../../src/renderer/src/contract/view-sync.ts";

test("视图位置为 0 时不会把重新订阅拖回 0", () => {
  assert.equal(resubscribePosition(0, 120), 120);
});

test("不会比事件流已经读到的位置更早", () => {
  assert.equal(resubscribePosition(50, 120), 120);
});

test("视图需要更早的事件时按视图的位置来", () => {
  assert.equal(resubscribePosition(200, 120), 200);
});

test("两边都没有位置时从 0 开始", () => {
  assert.equal(resubscribePosition(0, 0), 0);
});
