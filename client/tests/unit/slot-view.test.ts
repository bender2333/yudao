// 执行槽位页上的槽位显示（工单 #727）：现在一次只执行一个事项，页面照实说。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import { slotView } from "../../src/renderer/src/views/system/slot-view.ts";

test("execution.slots 参数现值是 8 时，页面仍显示总数 1", () => {
  // 工单 #727：参数现值是 3 还是 8 都不改总数——现在一次只执行一个事项
  const view = slotView({ running_runs: 0, slot_parameter: 8 });
  assert.equal(view.total, 1);
  assert.equal(view.lamps.length, 1);
});

test("没有在跑的事项时，灯是灭的，占用是 0", () => {
  const view = slotView({ running_runs: 0, slot_parameter: null });
  assert.equal(view.used, 0);
  assert.deepEqual(view.lamps, [{ on: false, title: "空闲" }]);
});

test("有事项在跑时，那一盏灯亮着", () => {
  const view = slotView({ running_runs: 1, slot_parameter: null });
  assert.equal(view.used, 1);
  assert.deepEqual(view.lamps, [{ on: true, title: "已占用" }]);
});

test("副标题不再承诺并行", () => {
  const view = slotView({ running_runs: 0, slot_parameter: null });
  assert.equal(view.subtitle, "当前一次只执行一个事项；不同项目并行在多项目并行完成以后开放");
  assert.doesNotMatch(view.subtitle, /并行时按队列顺序/);
});
