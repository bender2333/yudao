// 首页与顶栏共用的状态项（工单 #1013）：statusItems 是纯函数，只读决定列表的长度。
// 没有等待回答的决定时，这一项显示为零且不亮起；有决定时显示数量、亮起，点击进入首页的决定区块。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import type { DecisionView, SystemStatus } from "../../src/renderer/src/api/generated/types.gen";
import { statusItems } from "../../src/renderer/src/views/home/status-items.ts";

function decision(decisionId: string): DecisionView {
  return { decision_id: decisionId } as DecisionView;
}

test("没有等待回答的决定时只有一项「待你决定」，显示 0 且不亮起", () => {
  const items = statusItems(null, []);
  assert.equal(items.length, 1);
  assert.equal(items[0].id, "decisions");
  assert.equal(items[0].count, 0);
  assert.equal(items[0].lit, false);
});

test("有两条决定时显示 2、亮起，并给出标签、去向与区块", () => {
  const items = statusItems(null, [decision("d1"), decision("d2")]);
  assert.equal(items.length, 1);
  assert.equal(items[0].count, 2);
  assert.equal(items[0].lit, true);
  assert.equal(items[0].label, "待你决定");
  assert.equal(items[0].href, "#/home");
  assert.equal(items[0].anchor, "home-decisions");
});

test("第一个参数传 null 与传一个对象，结果相同", () => {
  const decisions = [decision("d1")];
  assert.deepEqual(statusItems({} as SystemStatus, decisions), statusItems(null, decisions));
});
