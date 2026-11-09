// 时序图的事实推出（工单 #1641，项目的组织设计说明 4.14「项目页是循环图加对话」的「时序图（经过）」一节、
// 4.15「循环图跟着组织长」的时序图一行；应用层与接口层设计说明 4.4「项目页四层读哪个查询」）。
//
// 守的是三环里的 R1（事实照实说）：图上的每一行、每个结论、每段等待都是从 project.flow、run.asks 与
// decisions.list 三条事实推出的，测试直接喂这三样，核对界面上会出现的字与结构，不经过界面。
//
// 覆盖工单验收要的：行的排序、同一版同时给几个职能合成一行、轮的归属与摘要、询问里又问的缩进、
// 等待色条的起止（问到回答、问到「现在」、等你决定）、停在下交付之后的那一版没有放行标记、只有一个职能时没有时序图。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  YOU, hasSequence, sequenceOf,
  type AskLike, type DecisionLike, type FlowRowLike, type SequenceRole, type SequenceRow, type SequenceView,
} from "../../src/renderer/src/views/project/sequence-model.ts";

/** 产品 · 工程 · 质检（与事项冻结的组织同一份结构）。 */
const ROLES: SequenceRole[] = [
  { id: "product", label: "产品" },
  { id: "engineering", label: "工程" },
  { id: "quality", label: "质检" },
];

function flow(fields: Partial<FlowRowLike> & Pick<FlowRowLike, "flow_id" | "kind" | "position" | "created_at">): FlowRowLike {
  return { event_id: `evt-${fields.flow_id}`, content: "", direction_from: null, direction_to: null, round: 1, ...fields };
}

function ask(fields: Partial<AskLike> & Pick<AskLike, "id" | "requester" | "recipient" | "question" | "started_at">): AskLike {
  return {
    status: "进行中", parent: null, chain: [fields.requester], depth: 1, start_position: 0,
    answer: null, answer_facts: null, reason: null, ended_at: null, ...fields,
  };
}

function decision(fields: Partial<DecisionLike> & Pick<DecisionLike, "decision_id" | "requested_at">): DecisionLike {
  return {
    work_item_id: "w1", status: "open", request: { department: "quality", description: "要不要继续" }, answer: null, ...fields,
  };
}

/** 一个视图里的一行：按标识找，找不到时报出这个视图里都有哪些行，省得只看到一句 undefined。 */
function rowOf(view: SequenceView, key: string): SequenceRow {
  for (const round of view.rounds) {
    const hit = round.rows.find((row) => row.key === key);
    if (hit !== undefined) {
      return hit;
    }
  }
  assert.fail(`没有这一行：${key}；视图里有 ${view.rounds.flatMap((r) => r.rows.map((x) => x.key)).join("、")}`);
}

/** 一行上等着的色条：按列找，给出这一段等待的种类。 */
function barOf(row: SequenceRow, column: string): string[] {
  return row.bars.filter((bar) => bar.column === column).map((bar) => bar.kind);
}

/** 产品 · 工程 · 质检的两轮：第一轮打回、第二轮放行，另外你决定过一次，还有两段开着的等待。 */
function fullRun(openRounds?: readonly number[]): SequenceView {
  const flowRows: FlowRowLike[] = [
    flow({ flow_id: "f-in", event_id: "e-in", kind: "你的输入", position: 1, direction_to: "product", content: "做一个订单系统的重构", round: 0, created_at: "2026-11-01T09:00:00Z" }),
    flow({ flow_id: "f-prd:eng", event_id: "e-prd", kind: "PRD 新版本", position: 3, direction_from: "product", direction_to: "engineering", content: "第 1 版；改动：状态机", round: 1, created_at: "2026-11-01T09:05:00Z" }),
    flow({ flow_id: "f-prd:qua", event_id: "e-prd", kind: "PRD 新版本", position: 3, direction_from: "product", direction_to: "quality", content: "第 1 版；改动：状态机", round: 1, created_at: "2026-11-01T09:05:00Z" }),
    flow({ flow_id: "f-del1", event_id: "e-del1", kind: "版本交付", position: 6, direction_from: "engineering", direction_to: "quality", content: "第 1 版交付", round: 1, created_at: "2026-11-01T09:20:00Z" }),
    flow({ flow_id: "f-rej", event_id: "e-rej", kind: "问题反馈", position: 8, direction_from: "quality", direction_to: "engineering", content: "已取消的订单还能被标记为已支付", round: 1, created_at: "2026-11-01T09:40:00Z" }),
    flow({ flow_id: "f-del2", event_id: "e-del2", kind: "版本交付", position: 12, direction_from: "engineering", direction_to: "quality", content: "第 2 版交付", round: 2, created_at: "2026-11-01T10:00:00Z" }),
    flow({ flow_id: "f-rel", event_id: "e-rel", kind: "放行", position: 14, direction_from: "quality", direction_to: "engineering", content: "核验了交付第 2 版", round: 2, created_at: "2026-11-01T10:10:00Z" }),
  ];
  const asks: AskLike[] = [
    ask({ id: "a1", requester: "engineering", recipient: "quality", question: "交付里的状态机怎么处理取消？", started_at: "2026-11-01T09:10:00Z", status: "已回答", answer: "取消要留一条记录", ended_at: "2026-11-01T09:15:00Z" }),
    ask({ id: "a2", requester: "quality", recipient: "product", question: "取消订单的判定标准是什么？", started_at: "2026-11-01T09:30:00Z", status: "已回答", answer: "以支付前取消为准", ended_at: "2026-11-01T09:36:00Z" }),
    ask({ id: "a3", requester: "product", recipient: "engineering", question: "第 1 版的取消逻辑写在哪？", started_at: "2026-11-01T09:32:00Z", status: "已回答", parent: "a2", chain: ["quality", "product"], depth: 2, answer: "在 orders/state.ts", ended_at: "2026-11-01T09:35:00Z" }),
    ask({ id: "a4", requester: "product", recipient: "engineering", question: "取消的退款要不要写进 PRD？", started_at: "2026-11-01T09:45:00Z", status: "进行中" }),
  ];
  const decisions: DecisionLike[] = [
    decision({
      decision_id: "d1", requested_at: "2026-11-01T09:25:00Z",
      request: { department: "quality", description: "这一版要不要打回重做", options: [{ id: "rework", label: "打回重做" }, { id: "pass", label: "放过" }] },
      status: "answered", answer: { option: "rework", answered_at: "2026-11-01T09:28:00Z" },
    }),
    decision({ decision_id: "d2", requested_at: "2026-11-01T09:50:00Z", request: { department: "engineering", description: "退款要不要现在做" } }),
  ];
  return sequenceOf({
    roles: ROLES,
    flow: flowRows,
    asks,
    decisions,
    materials: {
      contracts: [{ event_id: "e-prd", revision: 1 }],
      deliveries: [{ event_id: "e-del1", revision: 1 }, { event_id: "e-del2", revision: 2 }],
    },
    now: "2026-11-01T10:20:00Z",
    openRounds: openRounds ?? null,
  });
}

test("列是你与三个职能：你排在头里，后面按事项冻结的组织里的职能顺序", () => {
  const view = fullRun();
  assert.deepEqual(view.columns.map((column) => column.label), ["你", "产品", "工程", "质检"]);
  assert.equal(view.columns[0].id, YOU);
});

test("行按时间排：你的输入、PRD、询问、交付、要你决定、你的回答、询问里又问的都各在它的时刻上", () => {
  const round1 = fullRun().rounds.find((round) => round.round === 1);
  assert.ok(round1 !== undefined);
  assert.deepEqual(round1.rows.map((row) => row.key), [
    "flow:e-in", "flow:e-prd", "ask:a1", "ask:a1:answer", "flow:e-del1",
    "dec:d1", "dec:d1:answer", "ask:a2", "ask:a3", "ask:a3:answer", "ask:a2:answer", "ask:a4", "dec:d2",
  ]);
});

test("同一版同时给工程与质检是一行：两个去向，一条消息", () => {
  const prd = rowOf(fullRun(), "flow:e-prd");
  assert.equal(prd.kind, "outcome");
  assert.equal(prd.title, "PRD v1");
  assert.equal(prd.from, "product");
  assert.deepEqual(prd.to, ["engineering", "quality"]);
  assert.equal(prd.who, "产品 → 工程、质检");
  // 流转记录里有两条（一条给工程、一条给质检），图上只有一行
  const prdRows = fullRun().rounds.flatMap((round) => round.rows).filter((row) => row.key.startsWith("flow:e-prd"));
  assert.equal(prdRows.length, 1);
});

test("打回与放行标在那一版那一行上，不单独占一行", () => {
  const view = fullRun();
  const first = rowOf(view, "flow:e-del1");
  assert.equal(first.title, "交付 v1");
  assert.deepEqual(first.verdict, { tone: "reject", text: "质检打回" });
  const second = rowOf(view, "flow:e-del2");
  assert.deepEqual(second.verdict, { tone: "release", text: "质检放行" });
  // 没有一条专门写打回或放行的行
  const keys = view.rounds.flatMap((round) => round.rows.map((row) => row.key));
  assert.deepEqual(keys.filter((key) => key.includes("e-rej") || key.includes("e-rel")), []);
});

test("询问与回答是虚线，其余（成果、你的输入、决定）是实线", () => {
  const view = fullRun();
  assert.equal(rowOf(view, "ask:a1").dashed, true);
  assert.equal(rowOf(view, "ask:a1:answer").dashed, true);
  for (const key of ["flow:e-in", "flow:e-prd", "flow:e-del1", "dec:d1", "dec:d1:answer"]) {
    assert.equal(rowOf(view, key).dashed, false, `${key} 应该是实线`);
  }
});

test("询问读 run.asks，不读流转记录里那一行询问：同一件事不会出现两行", () => {
  const view = sequenceOf({
    roles: ROLES,
    flow: [
      flow({ flow_id: "f-ask", event_id: "e-ask", kind: "询问", position: 4, direction_from: "engineering", direction_to: "product", content: "取消订单怎么判定？", round: 1, created_at: "2026-11-01T09:10:00Z" }),
    ],
    asks: [ask({ id: "a1", requester: "engineering", recipient: "product", question: "取消订单怎么判定？", started_at: "2026-11-01T09:10:00Z", status: "已回答", answer: "以支付前取消为准", ended_at: "2026-11-01T09:15:00Z" })],
    decisions: [],
  });
  assert.deepEqual(view.rounds.flatMap((round) => round.rows.map((row) => row.key)), ["ask:a1", "ask:a1:answer"]);
});

test("你的决定那一行写选项的名字，不发回选项的标识", () => {
  const view = fullRun();
  assert.equal(rowOf(view, "dec:d1").title, "要你决定：这一版要不要打回重做");
  assert.equal(rowOf(view, "dec:d1:answer").title, "你决定：打回重做");
  assert.equal(rowOf(view, "dec:d1").who, "质检 → 你");
  assert.equal(rowOf(view, "dec:d1:answer").who, "你 → 质检");
});

test("轮按事实归属：你的输入（第 0 轮）并在第 1 轮；询问与决定按发生的时间归到当时那一轮", () => {
  const view = fullRun();
  assert.deepEqual(view.rounds.map((round) => round.round), [1, 2]);
  // 第 2 轮的只有第 2 版的交付（放行标在它上面，不另起一行）
  assert.deepEqual(view.rounds[1].rows.map((row) => row.key), ["flow:e-del2"]);
  // 第 1 轮里的询问与决定
  for (const key of ["ask:a1", "ask:a2", "ask:a3", "ask:a4", "dec:d1"]) {
    assert.ok(view.rounds[0].rows.some((row) => row.key === key), `${key} 应该在第 1 轮`);
  }
});

test("折起来的一行写这一轮的摘要：只展开最新一轮，前面几轮折成一行", () => {
  const view = fullRun();
  const [first, latest] = view.rounds;
  assert.equal(first.open, false);
  assert.equal(latest.open, true);
  assert.equal(first.summary, "PRD v1 → 交付 v1 → 质检打回 · 询问 4 次");
  assert.equal(latest.summary, "交付 v2 → 质检放行");
  // 点开前面那一轮：两轮都展开
  const opened = fullRun([1, 2]);
  assert.deepEqual(opened.rounds.map((round) => round.open), [true, true]);
});

test("询问里又问的缩进：最外层不缩，回问缩一层", () => {
  const view = fullRun();
  assert.equal(rowOf(view, "ask:a2").depth, 0);
  assert.equal(rowOf(view, "ask:a3").depth, 1);
  // 回答跟着它那一次询问缩进
  assert.equal(rowOf(view, "ask:a3:answer").depth, 1);
});

test("色条从询问画到回答：那一段在提问方那一列上，回答以后不再有", () => {
  const view = fullRun();
  assert.deepEqual(barOf(rowOf(view, "ask:a1"), "engineering"), ["ask"]);
  assert.deepEqual(barOf(rowOf(view, "ask:a1:answer"), "engineering"), ["ask"]);
  // 回答之后的交付那一行不再有这一段等待
  assert.deepEqual(barOf(rowOf(view, "flow:e-del1"), "engineering"), []);
  // 色条只在提问方那一列
  assert.deepEqual(barOf(rowOf(view, "ask:a1"), "quality"), []);
});

test("还没等到的色条画到「现在」：两段等待同时存在时都看得到", () => {
  const view = fullRun();
  // a4（产品问工程，还没回答）与 d2（工程等你决定）同时开着，一起画到最后一行
  const last = rowOf(view, "flow:e-del2");
  assert.deepEqual(barOf(last, "product"), ["ask"]);
  assert.deepEqual(barOf(last, "engineering"), ["user"]);
  assert.equal(view.now, "2026-11-01T10:20:00Z");
  // 等你决定的那一段从要你决定画到「现在」
  assert.deepEqual(barOf(rowOf(view, "dec:d1"), "quality"), ["user"]);
  assert.deepEqual(barOf(rowOf(view, "dec:d1:answer"), "quality"), ["user"]);
});

test("停在下交付之后的那一版没有放行标记：没有放行那条事实就不写放行", () => {
  const view = sequenceOf({
    roles: ROLES,
    flow: [
      flow({ flow_id: "f-del1", event_id: "e-del1", kind: "版本交付", position: 6, direction_from: "engineering", direction_to: "quality", content: "第 1 版交付", round: 1, created_at: "2026-11-01T09:20:00Z" }),
    ],
    asks: [],
    decisions: [],
    materials: { deliveries: [{ event_id: "e-del1", revision: 1 }] },
    now: "2026-11-01T09:30:00Z",
  });
  const delivery = rowOf(view, "flow:e-del1");
  assert.equal(delivery.verdict, null);
  // 没有开着的等待时也没有「现在」这一行
  assert.equal(view.now, null);
});

test("只有一个职能时没有时序图（「看经过」也不出现）", () => {
  assert.equal(hasSequence([{ id: "engineering" }]), false);
  assert.equal(hasSequence([]), false);
  assert.equal(hasSequence([{ id: "product" }, { id: "engineering" }]), true);
  assert.equal(hasSequence(ROLES), true);
});
