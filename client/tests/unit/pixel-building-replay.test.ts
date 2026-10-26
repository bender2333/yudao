// 首页楼的回放核对（工单 #957 验收标准 2）：把原型 v13 的页面上录下的 sc-return-home 调用送进客户端的楼画面，
// 静置到时间线放空（最后一个检查点），小人逐个字段与 v13 相同，打印每个场景的像素差。
//
// 录下的调用序列在 tests/fixtures/building/recordings.json（由 client/scripts/record-building-calls.mjs
// 从 docs/prototypes/v13 录制）。这个测试需要浏览器；回放测试不进 CI：
// 用 `npx tsx --test tests/unit/pixel-building-replay.test.ts` 单独运行。

import { test } from "node:test";
import assert from "node:assert/strict";

import { loadBuildingRecordings, replayBuildingAll } from "../helpers/building-replay.ts";

test("录制来自原型 v13：不加 --write 时与提交的录制相同", () => {
  const recording = loadBuildingRecordings();
  assert.match(recording.generatedFrom, /docs\/prototypes\/v13/, `录制的来源：${recording.generatedFrom}`);
  assert.ok(recording.scenarios.length >= 1, "录制里应有首页楼的场景");
});

test("首页的楼：最后一个检查点小人逐个字段与原型 v13 相同，打印像素差", async () => {
  const results = await replayBuildingAll();
  for (const r of results) {
    const diffInfo = r.pixelDiff.count === 0 ? "0" : `${r.pixelDiff.count}（外接矩形 ${JSON.stringify(r.pixelDiff.bbox)}）`;
    console.log(`[首页楼场景 ${r.scenario}] 像素差：${diffInfo}`);
  }
  const failed = results.filter((r) => r.mismatches.length > 0 || r.clientErrors.length > 0);
  assert.deepEqual(
    failed.map((r) => ({ scenario: r.scenario, mismatches: r.mismatches.slice(0, 6), clientErrors: r.clientErrors.slice(0, 3) })),
    [],
  );
});
