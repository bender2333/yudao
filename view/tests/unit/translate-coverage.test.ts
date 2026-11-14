// 翻译覆盖与缺口清单的单元测试（工单 #952、#1419）：
// 事件种类取自接口描述 harness/tests/openapi/openapi.json（画面的作业在接口描述改了时运行），
// 不再读服务端为画面维护的夹具。接口描述里的每种事件在每个场景里要么翻成动作、要么写明不画与理由；
// 没有归属的列进缺口清单，测试不因缺口清单不为空而失败，只核对它和实际画出来的东西一致。
// 缺口清单也写在测试输出里（缺一种事件就多一行）。
// 守 docs/design/test-pyramid.md「测试按三环留」的 R2（各级之间交换的字段）：归属表是翻译层与三个场景之间的约定。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import type { AcceptanceCoverageResult } from "../../src/api/generated/types.gen.ts";
import { floorState as checkFloorState } from "../../src/pixel/contract.ts";
import {
  CHECK_METHODS,
  COVERAGE,
  OVERLAY_LABELS,
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
import {
  COVERAGE_RESULT_LABELS,
  FLOOR_EVENT_TYPES,
  FLOOR_STREAM_TYPES,
  checkMethodLabel,
  coverageOverlay,
  coverageResultLabel,
  floorState,
} from "../../src/translate/floor.ts";
import { verifyMapping } from "../../src/translate/mapping.ts";
import { ROOM_ACTION_TYPES, ROOM_STREAM_TYPES } from "../../src/translate/room.ts";
import { BUILDING_EVENT_TYPES } from "../../src/translate/building.ts";
import { eventTypesFromInterface } from "./interface-description.ts";
import { FakeServer, fakeClock, fakeHost, fakeSurface, loadFixtures, recordingOf, settle, shellFor, until } from "./session-harness.ts";

const here = dirname(fileURLToPath(import.meta.url));
const COVERAGE_FIXTURE_RAW = JSON.parse(
  readFileSync(join(here, "..", "fixtures", "e2e", "acceptance-coverage.json"), "utf8"),
) as { response: { position: number; data: AcceptanceCoverageResult } };

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

// ---------------------------------------------------------------------------
// 覆盖层「检验」（工单 #1420）：守 docs/design/test-pyramid.md「测试按三环留」的 R2（acceptance.coverage
// 查询结果到画面合同 CoverageOverlayData 的翻译约定）与 R3（覆盖层登记、按需查询、开环条件用语边界及 H1 回放不变式）。

test("覆盖层「检验」翻译：覆盖比例、开环条件条数与六种检验方式和三种结果与夹具一致，原样读取 numbers", () => {
  const sample = COVERAGE_FIXTURE_RAW.response.data;
  const overlay = coverageOverlay(sample);

  assert.equal(OVERLAY_LABELS.coverage, "检验");
  assert.equal(overlay.bar.coverage_ratio, 0.5);
  assert.equal(overlay.bar.covered, 3);
  assert.equal(overlay.bar.criteria_total, 6);
  assert.equal(overlay.bar.executable, 3);
  assert.equal(overlay.bar.open, 3);
  assert.equal(overlay.bar.model_reading, 1);
  assert.equal(overlay.bar.text, "检验覆盖 50%（3/6）· 开环条件 3 条（含模型阅读 1 条）");

  assert.equal(overlay.criteria.length, 6);
  for (const code of Object.keys(CHECK_METHODS)) {
    assert.ok(overlay.criteria.some((item) => item.method === code), `夹具缺少检验方式 ${code}`);
    assert.equal(checkMethodLabel(code), CHECK_METHODS[code]!.label);
  }
  for (const result of Object.keys(COVERAGE_RESULT_LABELS)) {
    assert.ok(overlay.criteria.some((item) => item.result === result), `夹具缺少核验结果 ${result}`);
    assert.equal(coverageResultLabel(result), COVERAGE_RESULT_LABELS[result as keyof typeof COVERAGE_RESULT_LABELS]);
  }
  assert.equal(overlay.criteria[0]?.text, "AC-1 · 命令检查 · 通过");
  assert.equal(overlay.criteria[3]?.text, "AC-4 · 带参照材料的判定点 · 不通过 · 开环条件");
  assert.equal(overlay.criteria[5]?.text, "AC-6 · 开环 · 未核验 · 开环条件");

  assert.deepEqual(overlay.legend, [
    { key: "passed", label: "通过", count: 3, text: "通过 3" },
    { key: "failed", label: "不通过", count: 1, text: "不通过 1" },
    { key: "unverified", label: "未核验", count: 2, text: "未核验 2" },
    { key: "open", label: "开环条件", count: 3, text: "开环 3 条" },
  ]);

  // 原样读取 numbers 与 open_criteria，翻译层不按 covered / criteria_total 重新计算（基线未失败或试用含模型阅读时由服务端算好）
  const custom: AcceptanceCoverageResult = {
    ...sample,
    numbers: {
      criteria_total: 6,
      executable: 2,
      covered: 1,
      coverage_ratio: 0.25,
      model_reading: 2,
      open: 4,
    },
    open_criteria: ["AC-2", "AC-4", "AC-5", "AC-6"],
  };
  const customOverlay = coverageOverlay(custom);
  assert.equal(customOverlay.bar.coverage_ratio, 0.25);
  assert.equal(customOverlay.bar.covered, 1);
  assert.equal(customOverlay.bar.open, 4);
  assert.equal(customOverlay.bar.text, "检验覆盖 25%（1/6）· 开环条件 4 条（含模型阅读 2 条）");
  assert.equal(customOverlay.criteria.find((item) => item.criterion === "AC-2")?.open, true);
  assert.equal(customOverlay.criteria.find((item) => item.criterion === "AC-2")?.text, "AC-2 · 试用用例 · 通过 · 开环条件");
  assert.equal(customOverlay.legend.find((row) => row.key === "open")?.text, "开环 4 条");

  // 尚未产生检验记录时的空状态
  const empty = coverageOverlay(null);
  assert.equal(empty.bar.text, "还没有检验覆盖记录");
  assert.deepEqual(empty.criteria, []);
  assert.equal(empty.legend.find((row) => row.key === "open")?.text, "开环 0 条");
});

test("覆盖层「检验」用语与回放合同：标签与图例不含事项结束章用词，回放遵守 H1 与画面合同校验", () => {
  const sample = COVERAGE_FIXTURE_RAW.response.data;
  const overlay = coverageOverlay(sample);
  const empty = coverageOverlay(null);
  const forbiddenTerm = "开环" + "完成";

  // 守 R3（docs/design/visualization.md「开环完成与放行」）：验收条件一级只写「开环条件 / 开环 N 条」
  const serialized = JSON.stringify({ overlay, empty });
  assert.ok(serialized.includes("开环条件"));
  assert.ok(serialized.includes("开环 3 条"));
  assert.equal(serialized.includes(forbiddenTerm), false, `覆盖层文字出现了事项结束记号用词：${serialized}`);

  // 守 R2 与 H1：同一快照两次翻译得到完全相同的楼层状态，并通过画面合同校验；非法结果取值被合同拒绝
  const first = floorState({ position: COVERAGE_FIXTURE_RAW.response.position, loop: null, coverage: sample });
  const second = floorState({ position: COVERAGE_FIXTURE_RAW.response.position, loop: null, coverage: sample });
  assert.deepEqual(second, first);
  assert.doesNotThrow(() => checkFloorState(first));
  assert.equal(JSON.stringify(first).includes(forbiddenTerm), false);

  assert.throws(
    () => checkFloorState({
      ...first,
      coverage: {
        ...overlay,
        criteria: [{ ...overlay.criteria[0]!, result: "unknown_status" as never }],
      },
    }),
    /画面合同：验收条件 AC-1 的结果/,
  );
});

test("壳按需读取 acceptance.coverage：默认进入楼层不发该查询，开启「检验」后拉取并消除覆盖层缺口", async () => {
  const baseFixtures = loadFixtures();
  const demo = recordingOf(baseFixtures, "demo");
  const fixtures = {
    ...baseFixtures,
    recordings: baseFixtures.recordings.map((rec) => rec.name === "demo"
      ? {
        ...rec,
        queries: [
          ...rec.queries,
          {
            name: "acceptance.coverage",
            params: { run_id: demo.ids.run_id },
            response: COVERAGE_FIXTURE_RAW.response,
          },
        ],
      }
      : rec),
  };
  const server = new FakeServer(fixtures, "demo");
  const shell = shellFor(server);
  const overlays: { id: string | null; data: unknown }[] = [];
  const surface = {
    ...fakeSurface(),
    setOverlay(id: string | null, data: unknown) {
      overlays.push({ id, data });
    },
  };
  await shell.open("http://view.test", "");
  shell.goFloor(demo.ids.project_id, demo.ids.work_item_id);
  const detach = shell.attachHost(fakeHost, fakeClock, async () => surface);
  try {
    await until(() => surface.jumped.length + surface.states.length > 0, "楼层初始状态");
    await settle();

    // 能力清单含 coverage 时，缺口清单与对照表均无 coverage 缺口
    const report = verifyMapping({
      eventTypes: fixtures.capabilities.event_types,
      overlays: (fixtures.capabilities.overlays ?? []).map((item) => item.name),
    });
    assert.equal(report.overlayGaps.includes("coverage"), false);
    assert.equal(shell.state.gap.some((line) => line.includes("coverage")), false);

    // 默认未开启覆盖层：不发 acceptance.coverage 查询
    assert.equal(server.queried.some((q) => q.name === "acceptance.coverage"), false);
    assert.equal(shell.overlay, null);

    // 开启「检验」覆盖层：按聚焦事项的 run_id 订阅 acceptance.coverage，并把翻译结果交给画面表面
    shell.setOverlay("coverage");
    await until(
      () => overlays.some((entry) => entry.id === "coverage"
        && (entry.data as { criteria?: unknown[] } | null)?.criteria?.length === 6),
      "检验覆盖层数据到达画面表面",
    );
    assert.equal(shell.overlay, "coverage");
    assert.ok(server.queried.some((q) => q.name === "acceptance.coverage" && q.params?.run_id === demo.ids.run_id));
    assert.equal(shell.sync.viewSync?.openViewIds.includes("floor.coverage"), true);

    // 关闭覆盖层：撤销 floor.coverage 视图订阅并通知画面表面清除覆盖层
    shell.setOverlay(null);
    await settle();
    assert.equal(shell.overlay, null);
    assert.equal(shell.sync.viewSync?.openViewIds.includes("floor.coverage"), false);
    assert.deepEqual(overlays.at(-1), { id: null, data: null });
  } finally {
    detach();
    shell.close();
  }
});
