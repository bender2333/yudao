// 楼层的事实来源翻译（工单 #398、#1382）：project.loop 的 refs（工单 #396）翻成画面合同的事项 refs，
// 事实元素与来源种类、覆盖层的中文名，以及覆盖层「来源」的数据。
//
// 覆盖：六个元素的位置与来源种类都翻过去；没有来源的元素不出现在结果里（画面按缺来源处理，覆盖层「来源」据它标出）；
// 元素名有中文名、页面不出现内部标识；翻出来的楼层状态通过画面合同的校验；
// 覆盖层「来源」列出画出来的元素、标出缺来源的元素并给出图例计数。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DRAWN_FACT_ELEMENTS, FACT_LABELS, SOURCE_LABELS, factRefs, floorState, sourceOverlay,
} from "../../src/translate/floor.ts";
import { OVERLAY_LABELS, checkMethodProblems, overlayProblems } from "../../src/translate/coverage.ts";
import { floorState as checkFloorState, SOURCES } from "../../src/pixel/contract.ts";
import type { ProjectLoopResult } from "../../src/api/generated/types.gen.ts";

const ELEMENTS = ["sign", "round", "elapsed", "parcel", "stamp", "box"] as const;

const row = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  work_item_id: "w1", kind: "request", sign: "测试事项", color_index: 0, status: "in_progress", department: "engineering",
  progress: null, round: 1, started_at: "2026-10-30T09:00:00+08:00", elapsed_sec: 100, time_limit_sec: 7200,
  pending_question: null, run_id: "r1", adoption_id: null, recovery_state: null, version: 1, ...over,
});

const refOf = (position: number, source: string) => ({ position, source });

test("来源：六个事实元素的位置与来源种类都翻成画面合同的回链", () => {
  const refs = factRefs(row({
    refs: {
      sign: refOf(2, "user"), round: refOf(3, "user"), elapsed: refOf(66, "rule"),
      parcel: refOf(49, "rule"), stamp: refOf(64, "role_statement"), box: refOf(67, "rule"),
    },
  }) as never);
  assert.deepEqual(Object.keys(refs).sort(), [...ELEMENTS].sort());
  assert.deepEqual(refs.sign, { position: 2, source: "user" });
  assert.deepEqual(refs.stamp, { position: 64, source: "role_statement" });
  assert.deepEqual(refs.box, { position: 67, source: "rule" });
});

test("来源：没有来源的元素不进结果，画面据此标出缺来源", () => {
  // 事项刚建立：只有门牌与轮次有来源，包裹、盖章与成果库的箱子还没有
  const refs = factRefs(row({ refs: { sign: refOf(2, "user"), round: refOf(3, "user") } }) as never);
  assert.deepEqual(Object.keys(refs).sort(), ["round", "sign"]);
  // 一条来源都没有：结果为空，楼层状态里不带 refs（画面的 noSource 因此把它算作缺来源）
  assert.deepEqual(factRefs(row() as never), {});
});

test("来源：事实元素的名字是中文，页面不出现内部标识", () => {
  assert.deepEqual(Object.keys(FACT_LABELS).sort(), [...ELEMENTS].sort());
  for (const [key, label] of Object.entries(FACT_LABELS)) {
    assert.match(label, /[\u4e00-\u9fa5]/, `${key} 的名字要有中文`);
    assert.doesNotMatch(label, /[A-Za-z]/, `${key} 的名字不出现英文内部标识`);
  }
});

test("来源：带来源的楼层状态通过画面合同的校验", () => {
  const loop = {
    project_id: "p1",
    work_items: [row({
      refs: {
        sign: refOf(2, "user"), round: refOf(3, "user"), elapsed: refOf(66, "rule"),
        parcel: refOf(49, "rule"), stamp: refOf(64, "role_statement"), box: refOf(67, "rule"),
      },
    })],
    adoptions: [],
  } as unknown as ProjectLoopResult;
  const state = floorState({ position: 67, loop });
  assert.doesNotThrow(() => checkFloorState(state));
  assert.deepEqual(state.items[0].refs?.sign, { position: 2, source: "user" });
});

test("来源：五种来源都有中文名，页面不出现内部标识", () => {
  // 五种来源各有一行中文名（覆盖层的图例按它显示）
  assert.deepEqual(Object.keys(SOURCE_LABELS).sort(), [...SOURCES].sort());
  for (const [key, label] of Object.entries(SOURCE_LABELS)) {
    assert.match(label, /[\u4e00-\u9fa5]/, `${key} 的来源名要有中文`);
    assert.doesNotMatch(label, /[A-Za-z]/, `${key} 的来源名不出现英文内部标识`);
  }
});

test("来源：每个覆盖层都有中文名，缺一行就失败", () => {
  // 服务端能力清单里的覆盖层（harness/app/registry.py 的 OVERLAYS），页面按名字取这一份里的中文名
  const server = ["flow", "waiting", "recovery", "context_usage", "semantic_records", "sources", "loops", "coverage"];
  assert.deepEqual(overlayProblems(server), []);
  assert.deepEqual(overlayProblems(["sources", "no_such_overlay"]), ["覆盖层 no_such_overlay 在翻译层没有中文名"]);
  assert.equal(OVERLAY_LABELS.sources, "来源");
  assert.equal(OVERLAY_LABELS.coverage, "检验");
  // 检验方式的核对仍在（同一份覆盖核对的另一半，工单 #151）
  assert.equal(typeof checkMethodProblems, "function");
});

test("覆盖层「来源」：画出来的元素各一行，缺来源的单独列出，图例数五种来源", () => {
  const loop = {
    project_id: "p1",
    work_items: [row({
      refs: {
        sign: refOf(2, "user"), round: refOf(3, "rule"), elapsed: refOf(66, "host_measurement"),
        stamp: refOf(64, "role_statement"),
      },
    })],
    adoptions: [],
  } as unknown as ProjectLoopResult;
  const overlay = sourceOverlay(loop);
  // 覆盖层描边与查缺的五个元素：门牌、包裹、成果库的箱子、轮次与已用时间
  assert.deepEqual(DRAWN_FACT_ELEMENTS, ["sign", "parcel", "box", "round", "elapsed"]);
  assert.deepEqual(overlay.entries.map((entry) => entry.element).sort(), ["elapsed", "round", "sign"]);
  assert.deepEqual(overlay.entries.find((entry) => entry.element === "elapsed"),
    { work_item_id: "w1", element: "elapsed", label: "已用时间", source: "host_measurement", position: 66 });
  // refs 在、包裹与箱子没有：这两个元素缺来源，覆盖层标出
  assert.deepEqual(overlay.missing.map((item) => item.element).sort(), ["box", "parcel"]);
  assert.deepEqual(overlay.missing.find((item) => item.element === "box")?.label, "成果库的箱子");
  // 图例：五种来源各一行，数是画面上有它的元素的个数
  assert.deepEqual(overlay.legend.map((item) => item.source), [...SOURCES]);
  assert.deepEqual(overlay.legend.map((item) => item.count), [1, 1, 1, 0, 0]);
  // 一条 refs 都没有的旧数据：不算缺来源（画面照常画，见 render.ts 的 noSource）
  const old = sourceOverlay({ project_id: "p1", work_items: [row()], adoptions: [] } as unknown as ProjectLoopResult);
  assert.deepEqual(old.entries, []);
  assert.deepEqual(old.missing, []);
});
