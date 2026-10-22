// 事项状态在界面上的说法（工单 #733）：not_started 是「已登记、还没开始运行」，
// 排队等开始时也是它；held 是「上一个采纳成果被挂起」（基线变更）——两件事在界面上是两句话。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import { WORK_ITEM_STATUS, label } from "../../src/renderer/src/views/project/labels.ts";
import { floorStatus, sceneStatus, type BuildingItemRow } from "../../src/renderer/src/pixel/building/model.ts";
import { BUILDING_STATUS } from "../../src/renderer/src/pixel/building/status-text.ts";

function item(status: string, index: number): BuildingItemRow {
  return {
    work_item_id: `w${index}`,
    status,
    department: null,
    color_index: index,
    recovery_state: null,
  };
}

test("not_started 与 held 在界面上是两个不同的说法", () => {
  assert.equal(label(WORK_ITEM_STATUS, "not_started"), "排队中");
  assert.equal(label(WORK_ITEM_STATUS, "held"), "成果已挂起");
});

test("楼层画面：排队中的事项写「排队中」，成果被挂起的写「成果已挂起」", () => {
  const queued = item("not_started", 1);
  const held = item("held", 2);
  assert.equal(sceneStatus(queued), "queued");
  assert.equal(BUILDING_STATUS[sceneStatus(queued) ?? ""]?.text, "排队中");
  assert.equal(sceneStatus(held), "held");
  assert.equal(BUILDING_STATUS[sceneStatus(held) ?? ""]?.text, "成果已挂起");
  assert.equal(floorStatus([held]), "held");
  assert.equal(floorStatus([queued]), "queued");
});

test("楼层的状态词表里，「排队中」只属于排队中的事项", () => {
  const queued = Object.entries(BUILDING_STATUS)
    .filter(([, value]) => value.text === "排队中")
    .map(([key]) => key);
  assert.deepEqual(queued, ["queued"]);
});
