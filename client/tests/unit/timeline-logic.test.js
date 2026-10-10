// 时间轴与回放纯逻辑的单元测试（原型 v8 设计说明第 5.5 节、原型 v10 的 ui/replay.js，工单 #180）：
// 关键事实到刻度（按种类、按项目筛选）、刻度着色、折断符号、时长写法、报告项与刻度的高亮对应。
// 刻度种类由应用层给出（home.away_report 的 kind），这里核对客户端按它着色与筛选。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BASE_MS,
  GAP_SEC,
  KEY_KINDS,
  SPEEDS,
  durationText,
  isKeyKind,
  partsOf,
  secondsBetween,
  ticksInRefs,
  ticksOf,
} from "../../src/renderer/src/views/timeline/logic.ts";

function fact(overrides) {
  return {
    position: 1,
    at: "2026-10-03T10:00:00Z",
    type: "transition",
    kind: "handoff",
    label: "运行状态发生变化",
    project_id: "p1",
    work_item_id: "w1",
    ...overrides,
  };
}

test("三档速度与基准时长与原型 v10 的 replay.js 一致", () => {
  assert.deepEqual([...SPEEDS], [1, 2, 4]);
  assert.equal(BASE_MS, 1600);
  assert.equal(GAP_SEC, 2 * 3600);
});

test("认识的刻度种类：与原型 v10 的 KEY_KINDS 一一对应", () => {
  for (const kind of ["handoff", "ask", "answer", "rework", "release", "adopt", "fault", "repair", "deploy", "wait", "decision"]) {
    assert.equal(isKeyKind(kind), true);
  }
  assert.equal(isKeyKind("unknown"), false);
  assert.equal(isKeyKind(null), false);
  assert.equal(isKeyKind(undefined), false);
});

test("刻度保留关键事实，按位置排列、相同位置合并、不是刻度种类的不显示", () => {
  const ticks = ticksOf([
    fact({ position: 5, type: "model_requested", kind: null }),
    fact({ position: 3, type: "transition", kind: "handoff" }),
    fact({ position: 7, type: "deliverable_adopted", kind: "adopt" }),
    fact({ position: 3, type: "transition", kind: "handoff" }),
  ]);
  // kind 为空的不是刻度；相同位置 3 只出现一次
  assert.deepEqual(ticks.map((tick) => tick.position), [3, 7]);
  assert.equal(ticks[0].kind, "handoff");
  assert.equal(ticks[1].kind, "adopt");
});

test("质检的放行与返工按应用层给出的种类区分", () => {
  const ticks = ticksOf([
    fact({ position: 1, type: "qa_submitted", kind: "release", label: "质检提交了结论：release" }),
    fact({ position: 2, type: "qa_submitted", kind: "rework", label: "质检提交了结论：rework_engineering" }),
  ]);
  assert.deepEqual(ticks.map((tick) => tick.kind), ["release", "rework"]);
});

test("按项目筛选：只保留该项目的关键事实", () => {
  const ticks = ticksOf([
    fact({ position: 1, project_id: "p1" }),
    fact({ position: 2, project_id: "p2" }),
    fact({ position: 3, project_id: "p1" }),
  ], "p1");
  assert.deepEqual(ticks.map((tick) => tick.position), [1, 3]);
});

test("刻度之间的折断符号：相隔超过阈值时插入一段", () => {
  const ticks = ticksOf([
    fact({ position: 1, at: "2026-10-03T10:00:00Z" }),
    fact({ position: 2, at: "2026-10-03T10:01:00Z" }),
    fact({ position: 3, at: "2026-10-03T20:00:00Z" }),
  ]);
  const parts = partsOf(ticks);
  // 三个刻度，第二与第三个之间相隔约 10 小时，插入一段折断
  assert.deepEqual(parts.map((part) => part.kind), ["tick", "tick", "break", "tick"]);
  const broken = parts.find((part) => part.kind === "break");
  assert.ok(broken.gapSec > GAP_SEC);
});

test("相邻刻度相隔不超过阈值时不插入折断符号", () => {
  const ticks = ticksOf([
    fact({ position: 1, at: "2026-10-03T10:00:00Z" }),
    fact({ position: 2, at: "2026-10-03T10:00:30Z" }),
  ]);
  assert.deepEqual(partsOf(ticks).map((part) => part.kind), ["tick", "tick"]);
});

test("时长写法按秒、分、小时、天给出", () => {
  assert.equal(durationText(30), "30 秒");
  assert.equal(durationText(120), "2 分");
  assert.equal(durationText(7200), "2 小时");
  assert.equal(durationText(2 * 24 * 3600), "2 天");
});

test("时间差：无法解析的时间返回零", () => {
  assert.equal(secondsBetween("2026-10-03T10:00:00Z", "2026-10-03T10:01:00Z"), 60);
  assert.equal(secondsBetween("bad", "2026-10-03T10:01:00Z"), 0);
  assert.equal(secondsBetween("2026-10-03T10:01:00Z", "2026-10-03T10:00:00Z"), 0);
});

test("刻度按种类着色：着色值与原型 v10 的 KEY_KINDS 相同", () => {
  assert.equal(KEY_KINDS.handoff.color, "#4f8fd6");
  assert.equal(KEY_KINDS.ask.color, "#7c6bd6");
  assert.equal(KEY_KINDS.answer.color, "#9d8ff0");
  assert.equal(KEY_KINDS.rework.color, "#d64f4f");
  assert.equal(KEY_KINDS.release.color, "#3fa76a");
  assert.equal(KEY_KINDS.adopt.color, "#1f7a4a");
  assert.equal(KEY_KINDS.deploy.color, "#2f8f9d");
  assert.equal(KEY_KINDS.decision.color, "#d4a017");
});

test("报告项与刻度的高亮对应：来源事件位置与刻度位置相同即高亮", () => {
  const ticks = ticksOf([
    fact({ position: 1 }),
    fact({ position: 2 }),
    fact({ position: 3 }),
  ]);
  assert.deepEqual(ticksInRefs([2, 9], ticks), [2]);
  assert.deepEqual(ticksInRefs([], ticks), []);
});
