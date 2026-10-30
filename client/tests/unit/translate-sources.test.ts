// 楼层的事实来源翻译（工单 #398）：project.loop 的 refs（工单 #396）翻成画面合同的事项 refs，
// 以及事实元素的中文名。
//
// 覆盖：六个元素的位置与来源种类都翻过去；没有来源的元素不出现在结果里（画面按缺来源处理，覆盖层「来源」据它标出）；
// 元素名有中文名、页面不出现内部标识；翻出来的楼层状态通过画面合同的校验。

import { test } from "node:test";
import assert from "node:assert/strict";

import { FACT_LABELS, factRefs, floorState } from "../../src/renderer/src/translate/floor.ts";
import { floorState as checkFloorState } from "../../src/renderer/src/pixel/contract.ts";
import type { ProjectLoopResult } from "../../src/renderer/src/api/generated/types.gen.ts";

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
