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
  scopeAtTick,
  secondsBetween,
  ticksInRefs,
  ticksOf,
} from "../../src/renderer/src/views/timeline/logic.ts";

function fact(overrides) {
  return {
    position: 1,
    at: "2026-10-03T10:00:00Z",
    type: "transition",
    kind: "ask",
    label: "运行状态发生变化",
    project_id: "p1",
    work_item_id: "w1",
    ...overrides,
  };
}


test("认识的刻度种类：交接不再是刻度，其余关键事实照旧（工单 #907）", () => {
  for (const kind of ["ask", "answer", "rework", "release", "adopt", "fault", "repair", "deploy", "wait", "decision"]) {
    assert.equal(isKeyKind(kind), true);
  }
  // 服务端不再产生 handoff（工单 #556 删掉阶段状态机），客户端也不认识这个种类
  assert.equal(isKeyKind("handoff"), false);
  assert.equal(isKeyKind("unknown"), false);
  assert.equal(isKeyKind(null), false);
  assert.equal(isKeyKind(undefined), false);
});

test("刻度保留关键事实，按位置排列、相同位置合并、不是刻度种类的不显示", () => {
  const ticks = ticksOf([
    fact({ position: 5, type: "model_requested", kind: null }),
    fact({ position: 3, type: "transition", kind: "ask" }),
    fact({ position: 7, type: "deliverable_adopted", kind: "adopt" }),
    fact({ position: 3, type: "transition", kind: "ask" }),
  ]);
  // kind 为空的不是刻度；相同位置 3 只出现一次
  assert.deepEqual(ticks.map((tick) => tick.position), [3, 7]);
  assert.equal(ticks[0].kind, "ask");
  assert.equal(ticks[1].kind, "adopt");
});

test("质检的放行与缺陷记录按应用层给出的种类区分，缺陷记录的显示名是「缺陷记录」（工单 #907）", () => {
  const ticks = ticksOf([
    fact({ position: 1, type: "qa_submitted", kind: "release", label: "质检提交了结论：release" }),
    fact({ position: 2, type: "qa_submitted", kind: "rework", label: "质检提交了结论：rework_engineering" }),
  ]);
  assert.deepEqual(ticks.map((tick) => tick.kind), ["release", "rework"]);
  // 取值仍是 rework（服务端 harness/app/home.py 的 _fact_kind 这样给），页面上叫「缺陷记录」
  assert.equal(KEY_KINDS.rework.label, "缺陷记录");
});

test("按项目筛选：只保留该项目的关键事实", () => {
  const ticks = ticksOf([
    fact({ position: 1, project_id: "p1" }),
    fact({ position: 2, project_id: "p2" }),
    fact({ position: 3, project_id: "p1" }),
  ], "p1");
  assert.deepEqual(ticks.map((tick) => tick.position), [1, 3]);
});

// 回放的位置与事项范围是两个参数（接口设计说明第 4.1 节「按位置读取」，工单 #1217）：
// 点一个属于另一个事项的刻度时，范围先换成那个事项；刻度属于当前事项或没有事项时维持现范围；
// 位置不在刻度列表里（例如回到现在）时也维持现范围。
test("点刻度时的事项范围：属于另一个事项的刻度换成它，属于当前事项或没有事项时不变（工单 #1217）", () => {
  const ticks = ticksOf([
    fact({ position: 20, work_item_id: "w1", kind: "decision" }),
    fact({ position: 31, work_item_id: "w2", kind: "ask" }),
    // 项目级的事实没有事项：点它时维持现范围
    fact({ position: 40, work_item_id: null, kind: "deploy" }),
  ]);
  // 当前范围是后一个事项，点的刻度属于前一个事项：换成前一个
  assert.equal(scopeAtTick(ticks, "w2", 20), "w1");
  // 刻度属于当前事项：不变
  assert.equal(scopeAtTick(ticks, "w2", 31), "w2");
  // 刻度没有事项：维持现范围
  assert.equal(scopeAtTick(ticks, "w2", 40), "w2");
  // 当前没有范围时，点的刻度有事项就换成它
  assert.equal(scopeAtTick(ticks, null, 20), "w1");
  // 回到现在（位置为 null）与位置不在刻度列表里：范围不动
  assert.equal(scopeAtTick(ticks, "w2", null), "w2");
  assert.equal(scopeAtTick(ticks, "w2", 999), "w2");
  // 没有刻度时也维持现范围
  assert.equal(scopeAtTick([], "w2", 20), "w2");
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
