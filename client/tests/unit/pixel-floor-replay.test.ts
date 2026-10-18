// 楼层画面的回放核对（工单 #82 验收标准 2）：把原型录下的 19 个场景的调用序列送进客户端的画面，
// 在每个事件之后的固定时刻比较状态：每个角色的任务、姿势与头顶的话，每个包裹的去向，
// 每根管道的状态与各个信号。录下的调用与状态在 tests/fixtures/floor/recordings.json。
//
// 这个测试需要浏览器（客户端的画面用 PixiJS 画），用 Playwright 的 Chromium 与 Vite 的开发服务器；
// 只经 record-floor-calls.mjs --write 更新录制。

import { test } from "node:test";
import assert from "node:assert/strict";
import { loadRecordings, replayAll } from "../helpers/floor-replay.ts";

// ADR-0038 与 docs/prototypes/CHANGELOG.md 待办：v10 原型中录下的「待核实」状态在真实系统中不再实现，
// 回放测试里这些状态不再出现（sc-metro-ask、sc-metro-compact、sc-metro-unknown、sc-metro-offline、sc-metro-queue）
const PENDING_VERIFICATION_SCENARIOS = [
  "sc-metro-ask",
  "sc-metro-compact",
  "sc-metro-unknown",
  "sc-metro-offline",
  "sc-metro-queue",
];

test("回放：录下的调用序列送进客户端的画面零错误，状态与原型的记录相同", async () => {
  const recording = loadRecordings();
  assert.ok(recording.scenarios.length >= 18, `录下的场景 ${recording.scenarios.length} 个`);
  const results = await replayAll({ exclude: PENDING_VERIFICATION_SCENARIOS });
  const failed = results.filter((r) => r.mismatches.length > 0 || r.clientErrors.length > 0);
  const detail = failed.map((r) => `${r.scenario}：\n  ${[...r.mismatches.slice(0, 6), ...r.clientErrors.slice(0, 3)].join("\n  ")}`).join("\n");
  assert.deepEqual(failed.map((r) => r.scenario), [], `回放不一致：\n${detail}`);
});
