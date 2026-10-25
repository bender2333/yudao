// 事项状态在界面上的说法（工单 #733）：not_started 是「已登记、还没开始运行」，
// 排队等开始时也是它；held 是「上一个采纳成果被挂起」（基线变更）——两件事在界面上是两句话。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import { WORK_ITEM_STATUS,label } from "../../src/renderer/src/views/project/labels.ts";


test("not_started 与 held 在界面上是两个不同的说法", () => {
  assert.equal(label(WORK_ITEM_STATUS, "not_started"), "排队中");
  assert.equal(label(WORK_ITEM_STATUS, "held"), "成果已挂起");
});


