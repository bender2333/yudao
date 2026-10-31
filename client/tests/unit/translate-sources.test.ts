// 楼层的事实来源翻译（工单 #398）：project.loop 的 refs（工单 #396）翻成画面合同的事项 refs，
// 事实元素与来源种类、事件种类、覆盖层的中文名，覆盖层「来源」的数据与来源卡片的内容。
//
// 覆盖：六个元素的位置与来源种类都翻过去；没有来源的元素不出现在结果里（画面按缺来源处理，覆盖层「来源」据它标出）；
// 元素名有中文名、页面不出现内部标识；翻出来的楼层状态通过画面合同的校验；
// 覆盖层「来源」列出画出来的元素、标出缺来源的元素并给出图例计数；来源卡片写原件事件的说明、种类、提出者与摘要。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  DRAWN_FACT_ELEMENTS, EVENT_KIND_LABELS, FACT_LABELS, SOURCE_LABELS, actorLabel, eventKindLabel, factRefs, floorState,
  sourceCard, sourceEventOf, sourceOverlay,
} from "../../src/renderer/src/translate/floor.ts";
import { OVERLAY_LABELS, checkMethodProblems, overlayProblems } from "../../src/renderer/src/translate/coverage.ts";
import { floorState as checkFloorState, SOURCES } from "../../src/renderer/src/pixel/contract.ts";
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

test("来源：五种来源与每种事件种类都有中文名，缺一行就失败", () => {
  // 五种来源各有一行中文名（覆盖层的图例与来源卡片按它显示）
  assert.deepEqual(Object.keys(SOURCE_LABELS).sort(), [...SOURCES].sort());
  for (const [key, label] of Object.entries(SOURCE_LABELS)) {
    assert.match(label, /[\u4e00-\u9fa5]/, `${key} 的来源名要有中文`);
    assert.doesNotMatch(label, /[A-Za-z]/, `${key} 的来源名不出现英文内部标识`);
  }
  // 能力清单里的每种事件都有一行中文名（夹具与服务端的 contracts.py 由服务端测试核对）
  const types = JSON.parse(readFileSync(new URL("../fixtures/event-types.json", import.meta.url), "utf8")) as string[];
  assert.deepEqual(types.filter((type) => eventKindLabel(type) === null), []);
  // 术语表里的拉丁字母词（部门 Prompt、初始 PRD、MCP）是产品的说法；其余出现拉丁字母的算内部标识
  const TERMS = /^(Prompt|PRD|MCP)$/;
  for (const type of types) {
    const label = EVENT_KIND_LABELS[type];
    assert.match(label, /[\u4e00-\u9fa5]/, `${type} 的种类名要有中文`);
    for (const word of label.match(/[A-Za-z]+/g) ?? []) {
      assert.match(word, TERMS, `${type} 的种类名里出现内部标识：${word}`);
    }
  }
});

test("来源：每个覆盖层都有中文名，缺一行就失败", () => {
  // 服务端能力清单里的覆盖层（harness/app/registry.py 的 OVERLAYS），页面按名字取这一份里的中文名
  const server = ["flow", "waiting", "recovery", "context_usage", "semantic_records", "sources"];
  assert.deepEqual(overlayProblems(server), []);
  assert.deepEqual(overlayProblems(["sources", "no_such_overlay"]), ["覆盖层 no_such_overlay 在翻译层没有中文名"]);
  assert.equal(OVERLAY_LABELS.sources, "来源");
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
  // 画面上有对应物的元素：门牌、包裹、成果库的箱子、轮次与已用时间（盖章还没有画出来的位置）
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

test("来源卡片：写原始事件的说明、种类、时间、提出者与上下文摘要", () => {
  const target = row({ refs: { sign: refOf(2, "user") } }) as never;
  const face = sourceCard(target, "sign", { position: 2, source: "user" }, {
    type: "work_item_created", label: "在项目中建立了事项：测试事项", at: "2026-10-30T01:00:00+00:00",
    actor: "department:product", position: 2, payload: { summary: "建立事项" },
  });
  assert.equal(face.element_label, "门牌");
  assert.equal(face.source_label, "用户");
  assert.equal(face.kind_label, "建立事项");
  assert.equal(face.actor_label, "产品部门");
  assert.equal(face.position, 2);
  assert.equal(face.note, null);
  assert.deepEqual(face.detail.slice(0, 2), [{ term: "事项", value: "测试事项" }, { term: "轮次", value: "第 1 轮" }]);
  assert.deepEqual(face.detail.find((item) => item.term === "摘要"), { term: "摘要", value: "建立事项" });
  // 原始事件取不到（这一页打开以前的事件）：写明它在时间轴上的位置，页面不出现英文内部标识
  const missing = sourceCard(target, "sign", { position: 2, source: "user" }, null);
  assert.equal(missing.event_label, null);
  assert.match(missing.note ?? "", /第 2 位/);
  assert.doesNotMatch(missing.note ?? "", /[A-Za-z]/);
  // 提出者的三种写法
  assert.equal(actorLabel("user:local"), "你");
  assert.equal(actorLabel("system"), "系统");
  assert.equal(actorLabel(null), null);
});
test("按位置取事件的结果：取得到时翻成来源卡片要的形状，取不到时为空", () => {
  // 工单 #1342：来源卡片优先用 event.positions 的答案，不再只靠页面缓存
  const items = [
    { position: 2, status: "available" as const, type: "work_item_created", label: "在项目中建立了事项：测试事项",
      at: "2026-10-30T01:00:00+00:00", actor: "department:product", actor_label: "产品部门",
      payload: { summary: "建立事项" } },
    { position: 5, status: "missing" as const, reason: "archived" },
  ];
  const event = sourceEventOf(items, 2);
  assert.equal(event?.type, "work_item_created");
  assert.equal(event?.label, "在项目中建立了事项：测试事项");
  assert.equal(event?.actor_label, "产品部门");
  assert.deepEqual(event?.payload, { summary: "建立事项" });
  // 取不到（已归档、已压缩、越界、位置上是别的流的事件）与不在结果里：都为空，卡片按「取不到」写
  assert.equal(sourceEventOf(items, 5), null);
  assert.equal(sourceEventOf(items, 99), null);
  // 查询给出的提出者可读名优先于按 actor 自己翻（「产品部门」不是按 department:product 翻出来的写法）
  const face = sourceCard(row() as never, "sign", { position: 2, source: "user" },
    event ?? null);
  assert.equal(face.actor_label, "产品部门");
});