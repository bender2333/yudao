// 部门房间的回放核对（工单 #177 验收标准 2）：把原型录下的部门房间调用序列送进客户端的房间画面，
// 在每个事件之后的固定时刻比较状态：每个角色的任务与姿势、头顶的话、房间状态与传信管口。
// 录下的调用与状态在 tests/fixtures/room/recordings.json。只经 record-room-calls.mjs --write 更新。

import { test } from "node:test";
import assert from "node:assert/strict";
import { loadRoomRecordings, replayAllRooms } from "../helpers/room-replay.ts";

test("回放：录下的部门房间调用序列送进客户端的画面零错误，状态与原型的记录相同", async () => {
  const recording = loadRoomRecordings();
  assert.ok(recording.scenarios.length >= 12, `录下的场景 ${recording.scenarios.length} 份`);
  const results = await replayAllRooms();
  const failed = results.filter((r) => r.mismatches.length > 0 || r.clientErrors.length > 0);
  const detail = failed.map((r) => `${r.scenario}：\n  ${[...r.mismatches.slice(0, 6), ...r.clientErrors.slice(0, 3)].join("\n  ")}`).join("\n");
  assert.deepEqual(failed.map((r) => r.scenario), [], `回放不一致：\n${detail}`);
});
