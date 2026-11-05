// 翻译覆盖核对的单元测试（工单 #952 验收标准 4）：
// 夹具里的每种事件在楼层、房间、楼三个场景里都有归属（翻成动作、转交实时内容、不画），
// 每个「不画」写了一句理由；用一份多加了一种事件的清单核对时，核对失败。
// 夹具 client/tests/fixtures/event-types.json 由服务端测试 harness/tests/test_event_type_fixture.py
// 核对与服务端的 EVENT_TYPES 相同。
// 守第 13 节的 R2（各级之间交换的字段）：覆盖表是翻译层与三个场景之间的约定。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  COVERAGE,
  SCENES,
  checkCoverage,
  classOf,
  coverageProblems,
  type TranslationCoverage,
} from "../../src/renderer/src/translate/coverage.ts";

const EVENT_TYPES: string[] = JSON.parse(
  readFileSync(new URL("../fixtures/event-types.json", import.meta.url), "utf8"),
) as string[];

test("夹具里的每种事件在三个场景里都有归属，每个「不画」都有理由", () => {
  assert.ok(EVENT_TYPES.length > 0, "夹具里没有事件种类");
  assert.deepEqual(coverageProblems(EVENT_TYPES), []);
  checkCoverage(EVENT_TYPES);
  for (const scene of SCENES) {
    for (const type of EVENT_TYPES) {
      const cls = classOf(COVERAGE, scene, type);
      assert.ok(cls !== null, `${scene} 里的事件 ${type} 没有归属`);
      if (cls === "none") {
        assert.ok(COVERAGE[scene].none[type].trim() !== "", `${scene} 里的事件 ${type} 列为不画但没有理由`);
      }
    }
  }
});

test("三个场景都有一批翻成动作的事件，流式文字只在楼层与房间", () => {
  for (const scene of SCENES) {
    const drawn = EVENT_TYPES.filter((type) => classOf(COVERAGE, scene, type) === "drawn");
    assert.ok(drawn.length > 0, `${scene} 里没有翻成动作的事件`);
  }
  assert.ok(classOf(COVERAGE, "floor", "model_stream_progress") === "realtime");
  assert.ok(classOf(COVERAGE, "room", "model_stream_progress") === "realtime");
  assert.ok(classOf(COVERAGE, "building", "model_stream_progress") === "none");
});

test("一份多加了一种事件的清单核对时失败，提示写明场景与事件", () => {
  // 服务端新增事件种类、夹具与覆盖表都没有跟上时，核对失败并指出是什么事件
  const extra = [...EVENT_TYPES, "a_brand_new_event"];
  assert.throws(() => checkCoverage(extra), (error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    for (const scene of SCENES) {
      assert.ok(message.includes(`${scene}：事件 a_brand_new_event 没有归属`), `提示里没有 ${scene} 的缺行`);
    }
    return true;
  });
});

test("同一种事件被归到两类、或列为不画但没写理由时，核对失败", () => {
  const doubled: TranslationCoverage = {
    ...COVERAGE,
    floor: {
      drawn: [...COVERAGE.floor.drawn, "run_created"],
      realtime: COVERAGE.floor.realtime,
      none: COVERAGE.floor.none,
    },
  };
  assert.ok(coverageProblems(EVENT_TYPES, doubled).some((problem) => problem.includes("run_created") && problem.includes("同时属于")));

  const noReason: TranslationCoverage = {
    ...COVERAGE,
    room: {
      drawn: COVERAGE.room.drawn,
      realtime: COVERAGE.room.realtime,
      none: { ...COVERAGE.room.none, run_created: "  " },
    },
  };
  assert.ok(coverageProblems(EVENT_TYPES, noReason).some((problem) => problem.includes("run_created") && problem.includes("没有写理由")));

  const missing: TranslationCoverage = {
    ...COVERAGE,
    building: {
      drawn: COVERAGE.building.drawn.filter((type) => type !== "ask_started"),
      realtime: COVERAGE.building.realtime,
      none: COVERAGE.building.none,
    },
  };
  assert.ok(coverageProblems(EVENT_TYPES, missing).some((problem) => problem.includes("ask_started") && problem.includes("没有归属")));
});
