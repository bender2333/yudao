// 楼层画面的回放核对（工单 #957 验收标准 2）：把原型 v13 的页面上录下的调用送进客户端的画面，
// 静置到时间线放空（最后一个检查点），与 v13 的画面逐像素、逐个小人比较。
//
// 录下的调用序列与事件在 tests/fixtures/floor/recordings.json（由 client/scripts/record-floor-calls.mjs
// 从 docs/prototypes/v13 录制）。这个测试需要浏览器（客户端与原型两边的画面都画在画布上），
// 回放测试不进 CI：按 AGENTS.md「执行者」，用 `node --test tests/unit/pixel-floor-replay.test.ts` 单独运行。

import { test } from "node:test";
import assert from "node:assert/strict";
import { loadRecordings, replayAll } from "../helpers/floor-replay.ts";

test("录制来自原型 v13：不加 --write 时与提交的录制相同", () => {
  const recording = loadRecordings();
  assert.match(recording.generatedFrom, /docs\/prototypes\/v13/, `录制的来源：${recording.generatedFrom}`);
  assert.ok(recording.scenarios.length >= 18, `录下的场景 ${recording.scenarios.length} 个`);
});

test("回放：每段录制的最后一个检查点与原型 v13 逐像素、逐个小人相同", async () => {
  const results = await replayAll();
  const failed = results.filter((r) => r.mismatches.length > 0 || r.clientErrors.length > 0);
  const detail = failed.map((r) => `${r.scenario}：\n  ${[...r.mismatches.slice(0, 6), ...r.clientErrors.slice(0, 3)].join("\n  ")}`).join("\n");
  assert.deepEqual(failed.map((r) => r.scenario), [], `回放与原型 v13 不一致：\n${detail}`);
});
