// 首页楼的回放核对（工单 #178 验收标准 2）：把原型录下的 sc-return-home 调用序列送进客户端的楼画面，
// 按录下的固定时刻取状态，与原型录下的状态逐项比较：每层的灯、小旗、阀门、状态灯与决定计数，以及每层小人的位置、姿势与朝向。
//
// 录下的调用与状态记录在 tests/fixtures/building/recordings.json，只经
// client/scripts/record-building-calls.mjs --write 更新。

import { test } from "node:test";
import assert from "node:assert/strict";

import { loadBuildingRecordings, replayBuildingAll } from "../helpers/building-replay.ts";

test("首页的楼：录下的 sc-return-home 调用序列送进客户端，状态与原型的记录逐项相同，控制台零错误", async () => {
  const recording = loadBuildingRecordings();
  assert.ok(recording.scenarios.length >= 1, "录制里应有首页楼的场景");
  const results = await replayBuildingAll();
  const failed = results.filter((r) => r.mismatches.length > 0 || r.clientErrors.length > 0);
  assert.deepEqual(
    failed.map((r) => ({ scenario: r.scenario, mismatches: r.mismatches.slice(0, 6), clientErrors: r.clientErrors.slice(0, 3) })),
    [],
  );
});
