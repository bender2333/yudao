// 翻译覆盖与缺口清单的单元测试（工单 #952、#1419）：
// 事件种类取自接口描述 harness/tests/openapi/openapi.json（画面的作业在接口描述改了时运行），
// 不再读服务端为画面维护的夹具。接口描述里的每种事件在每个场景里要么翻成动作、要么写明不画与理由；
// 没有归属的列进缺口清单，测试不因缺口清单不为空而失败，只核对它和实际画出来的东西一致。
// 缺口清单也写在测试输出里（缺一种事件就多一行）。
// 守 docs/design/test-pyramid.md「测试按三环留」的 R2（各级之间交换的字段）：归属表是翻译层与三个场景之间的约定。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  COVERAGE,
  SCENES,
  classOf,
  declarationProblems,
  eventGaps,
  gapLines,
  gapProblems,
  type PaintedEventTypes,
  type SceneCoverage,
  type TranslationCoverage,
} from "../../src/translate/coverage.ts";
import { FLOOR_EVENT_TYPES, FLOOR_STREAM_TYPES } from "../../src/translate/floor.ts";
import { ROOM_ACTION_TYPES, ROOM_STREAM_TYPES } from "../../src/translate/room.ts";
import { BUILDING_EVENT_TYPES } from "../../src/translate/building.ts";
import { eventTypesFromInterface } from "./interface-description.ts";

/** 接口描述里的每种事件。 */
const EVENT_TYPES = eventTypesFromInterface();

/** 三个场景实际画出来的东西：动作表与流式文字表（楼没有流式文字）。 */
const PAINTED: PaintedEventTypes = {
  actions: { floor: FLOOR_EVENT_TYPES, room: ROOM_ACTION_TYPES, building: BUILDING_EVENT_TYPES },
  streams: { floor: FLOOR_STREAM_TYPES, room: ROOM_STREAM_TYPES, building: [] },
};

/** 把一种事件从三个场景的「不画」清单里去掉（模拟一种还没归类的事件）。 */
function dropEverywhere(type: string): TranslationCoverage {
  const scene = (coverage: SceneCoverage): SceneCoverage => ({
    ...coverage,
    none: Object.fromEntries(Object.entries(coverage.none).filter(([key]) => key !== type)),
  });
  return { floor: scene(COVERAGE.floor), room: scene(COVERAGE.room), building: scene(COVERAGE.building) };
}

test("缺口清单：接口描述里的每种事件在三个场景里要么有归属、要么列在缺口清单里，测试不因它为空而失败", (t) => {
  assert.ok(EVENT_TYPES.length > 0, "接口描述里没有事件种类");
  const gaps = eventGaps(EVENT_TYPES);
  t.diagnostic(gaps.length === 0
    ? `缺口清单：无（接口描述里的 ${EVENT_TYPES.length} 种事件在三个场景里都有归属）`
    : gapLines(gaps).join("\n"));
  // 清单与实际画出来的东西一致：有归属的照归属画，没归属的确实没画
  assert.deepEqual(gapProblems(EVENT_TYPES, PAINTED), []);
  // 归属表自身的问题：同一种事件归到两类、写明不画却没写理由
  assert.deepEqual(declarationProblems(), []);
  // 缺口清单的每一行就是「在某个场景里没有归属」的那些种类
  for (const scene of SCENES) {
    for (const type of EVENT_TYPES) {
      const cls = classOf(COVERAGE, scene, type);
      const inGap = gaps.some((gap) => gap.type === type && gap.scenes.includes(scene));
      assert.equal(inGap, cls === null, `${scene} 里的事件 ${type} 的缺口与归属对不上`);
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

test("接口描述里多了一种没有归属的事件：测试照过，缺口清单多一行，测试输出里写出它", (t) => {
  const name = "test_only_unmapped_event";
  const extra = [...EVENT_TYPES, name];
  const before = eventGaps(EVENT_TYPES);
  const after = eventGaps(extra);
  assert.equal(after.length, before.length + 1, "缺口清单没有多一行");
  assert.deepEqual(after.find((gap) => gap.type === name), { type: name, scenes: [...SCENES] });
  // 缺口清单不为空不让测试失败：一种还没画的事件确实没有动作，也没有流式文字
  assert.deepEqual(gapProblems(extra, PAINTED), [], "多了一种没有归属的事件不该让测试失败");
  const printed = gapLines(after).join("\n");
  assert.ok(printed.includes(name), `测试输出里没有写出缺口：${printed}`);
  t.diagnostic(printed);
  // 补上归属（三个场景都写明不画与理由）以后缺口清单少一行
  const reason = "测试用的事件，画面里没有对应物";
  const assigned: TranslationCoverage = {
    floor: { ...COVERAGE.floor, none: { ...COVERAGE.floor.none, [name]: reason } },
    room: { ...COVERAGE.room, none: { ...COVERAGE.room.none, [name]: reason } },
    building: { ...COVERAGE.building, none: { ...COVERAGE.building.none, [name]: reason } },
  };
  assert.equal(eventGaps(extra, assigned).length, before.length, "补上归属以后缺口清单没有少一行");
});

test("缺口清单与实际没画的东西一致：从归属表里去掉一种不画的，清单多出它；列了其实已画的，测试失败", () => {
  // 一种写明不画、动作表里也没有的种类（设置类，工单 #236）：去掉归属以后进缺口清单，与实际的画法仍然一致
  const dropped = dropEverywhere("home_seen");
  const gaps = eventGaps(EVENT_TYPES, dropped);
  assert.ok(gaps.some((gap) => gap.type === "home_seen" && gap.scenes.length === SCENES.length),
    "去掉归属以后缺口清单里没有它");
  assert.deepEqual(gapProblems(EVENT_TYPES, PAINTED, dropped), [], "不画的种类进缺口清单不算问题");

  // 一种真的画在楼上的种类（询问的开始）：从楼的归属表里去掉，但楼的动作表照旧画它——清单说的与实际对不上
  const mismatch: TranslationCoverage = {
    ...COVERAGE,
    building: { ...COVERAGE.building, drawn: COVERAGE.building.drawn.filter((type) => type !== "ask_started") },
  };
  assert.ok(eventGaps(EVENT_TYPES, mismatch).some((gap) => gap.type === "ask_started" && gap.scenes.includes("building")));
  assert.ok(gapProblems(EVENT_TYPES, PAINTED, mismatch).some((problem) => problem.includes("ask_started")
    && problem.includes("列在缺口清单里，实际画了")), "清单里列了其实已画的种类，测试应当失败");
});

test("归属表自己的问题：同一种事件被归到两类、或列为不画但没写理由时，测试失败", () => {
  const doubled: TranslationCoverage = {
    ...COVERAGE,
    floor: { ...COVERAGE.floor, drawn: [...COVERAGE.floor.drawn, "run_created"] },
  };
  assert.ok(declarationProblems(doubled).some((problem) => problem.includes("run_created") && problem.includes("同时属于")));

  const noReason: TranslationCoverage = {
    ...COVERAGE,
    room: { ...COVERAGE.room, none: { ...COVERAGE.room.none, run_created: "  " } },
  };
  assert.ok(declarationProblems(noReason).some((problem) => problem.includes("run_created") && problem.includes("没有写理由")));
});
