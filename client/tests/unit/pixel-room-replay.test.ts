// 部门房间的回放核对（工单 #1069 验收标准 2）：把原型 v13 的页面上录下的调用送进客户端的房间画面，
// 静置到时间线放空（最后一个检查点），与 v13 的画面逐像素、逐个小人比较。
//
// 录下的调用序列在 tests/fixtures/room/recordings.json（由 client/scripts/record-room-calls.mjs
// 从 docs/prototypes/v13 录制）。这个测试需要浏览器；回放测试不进 CI：
// 用 `node --test tests/unit/pixel-room-replay.test.ts` 单独运行。

import { test } from "node:test";
import assert from "node:assert/strict";
import { loadRoomRecordings, replayAllRooms } from "../helpers/room-replay.ts";

test("录制来自原型 v13：不加 --write 时与提交的录制相同", () => {
  const recording = loadRoomRecordings();
  assert.match(recording.generatedFrom, /docs\/prototypes\/v13/, `录制的来源：${recording.generatedFrom}`);
  assert.ok(recording.scenarios.length >= 50, `录下的场景 ${recording.scenarios.length} 个`);
});

test("回放：每段录制的最后一个检查点小人逐个字段与原型 v13 相同，像素差为 0", async () => {
  const results = await replayAllRooms();
  for (const r of results) {
    const diffInfo = r.pixelDiff.count === 0 ? "0" : `${r.pixelDiff.count}（外接矩形 ${JSON.stringify(r.pixelDiff.bbox)}）`;
    console.log(`[房间场景 ${r.scenario}] 像素差：${diffInfo}`);
  }
  const failed = results.filter((r) => r.mismatches.length > 0 || r.clientErrors.length > 0 || r.pixelDiff.count !== 0);
  const detail = failed.map((r) => `${r.scenario}：\n  ${[...r.mismatches.slice(0, 6), ...r.clientErrors.slice(0, 3)].join("\n  ")}`).join("\n");
  assert.deepEqual(failed.map((r) => r.scenario), [], `回放与原型 v13 不一致：\n${detail}`);
});
