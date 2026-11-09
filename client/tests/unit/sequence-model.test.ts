// 时序图的事实推出（工单 #1641、#1643，项目的组织设计说明 4.14「项目页是循环图加对话」的「时序图（经过）」
// 一节、4.15「循环图跟着组织长」的时序图一行；应用层与接口层设计说明 4.4「项目页四层读哪个查询」）。
//
// 守的是三环里的 R1（事实照实说）：图上的每一行、每个结论、每段等待、点开以后的原文都是从 project.flow、
// run.asks 与 decisions.list 三条事实推出的，测试直接喂这三样，核对界面上会出现的字与结构，不经过界面。
//
// 覆盖工单验收要的：行的排序、同一版同时给几个职能合成一行、轮的归属与摘要、询问里又问的缩进、
// 等待色条的起止（问到回答、问到「现在」、等你决定）、停在下交付之后的那一版没有放行标记、只有一个职能时没有时序图；
// 点一行看原文时给什么（成果是那一版与差异，问答与你的话是全文；又问的写明是回答哪一次时问的；
// 工程回答质检的分事实与解释），以及只看这两个职能时的列与行。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  YOU, hasSequence, sequenceOf,
  type AskLike, type DecisionLike, type FlowRowLike, type SequenceDetail, type SequenceRole, type SequenceRow,
  type SequenceView,
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
    answer: null, answer_facts: null, answer_explanation: null, reason: null, ended_at: null, ...fields,
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

/** 一行点开看原文时给的东西：找不到时报出这一行是哪一种，省得只看到一句 undefined。 */
function detailOf(view: SequenceView, key: string): SequenceDetail {
  return rowOf(view, key).detail;
}

/** 点开的那一行是询问：核对问题、回答与追问的来处。 */
function askDetail(view: SequenceView, key: string): Extract<SequenceDetail, { kind: "ask" }> {
  const detail = detailOf(view, key);
  assert.equal(detail.kind, "ask", `${key} 应该是询问那一行`);
  return detail as Extract<SequenceDetail, { kind: "ask" }>;
}

/** 点开的那一行是你的话或决定：核对写的是谁、全文是哪一句。 */
function textDetail(view: SequenceView, key: string): Extract<SequenceDetail, { kind: "text" }> {
  const detail = detailOf(view, key);
  assert.equal(detail.kind, "text", `${key} 应该是你的话或决定`);
  return detail as Extract<SequenceDetail, { kind: "text" }>;
}

/** 产品 · 工程 · 质检的两轮：第一轮打回、第二轮放行，另外你决定过一次，还有两段开着的等待。 */
function fullRun(openRounds?: readonly number[], pair?: readonly string[]): SequenceView {
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
    pair: pair ?? null,
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

test("同一版交给两个核验角色：仍是一行，结论按各自的来往标在同一版上", () => {
  const view = sequenceOf({
    roles: [...ROLES, { id: "audit", label: "审计" }],
    flow: [
      flow({ flow_id: "f-del:q", event_id: "e-del", kind: "版本交付", position: 6, direction_from: "engineering", direction_to: "quality", content: "第 1 版交付", round: 1, created_at: "2026-11-01T09:20:00Z" }),
      flow({ flow_id: "f-del:a", event_id: "e-del", kind: "版本交付", position: 6, direction_from: "engineering", direction_to: "audit", content: "第 1 版交付", round: 1, created_at: "2026-11-01T09:20:00Z" }),
      flow({ flow_id: "f-rel", event_id: "e-rel", kind: "放行", position: 14, direction_from: "audit", direction_to: "engineering", content: "核验了交付第 1 版", round: 1, created_at: "2026-11-01T09:40:00Z" }),
    ],
    materials: { deliveries: [{ event_id: "e-del", revision: 1 }] },
  });
  const delivery = rowOf(view, "flow:e-del");
  assert.deepEqual(delivery.to, ["quality", "audit"]);
  assert.deepEqual(delivery.verdict, { tone: "release", text: "审计放行" });
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

test("点一行看原文：成果给那一版与差异（同图上的箭头），你的输入与决定给全文", () => {
  const view = fullRun();
  // 成果那一行：点开是图上那条箭头（那一版与差异），所以带上这条事实的标识
  const delivery = detailOf(view, "flow:e-del1");
  assert.equal(delivery.kind, "outcome");
  assert.deepEqual(delivery.kind === "outcome" ? delivery.flowIds : [], ["f-del1"]);
  assert.equal(delivery.kind === "outcome" ? delivery.text : "", "第 1 版交付");
  // 同一版同时给两个职能的那一行：两条流转记录都在，点开的是同一版
  const prd = detailOf(view, "flow:e-prd");
  assert.deepEqual(prd.kind === "outcome" ? prd.flowIds : [], ["f-prd:eng", "f-prd:qua"]);
  // 你的输入与要你决定：全文
  assert.deepEqual(textDetail(view, "flow:e-in"), {
    kind: "text", heading: "你的输入", text: "做一个订单系统的重构", note: null,
  });
  assert.equal(textDetail(view, "dec:d1").heading, "要你决定");
  assert.equal(textDetail(view, "dec:d1").text, "这一版要不要打回重做");
  assert.equal(textDetail(view, "dec:d1").note, "选项：打回重做、放过");
  assert.deepEqual(textDetail(view, "dec:d1:answer"), {
    kind: "text", heading: "你决定", text: "打回重做", note: null,
  });
});

test("点询问或回答那一行看全文：图上只有一句标题，面板给问题与回答的整段", () => {
  const view = sequenceOf({
    roles: ROLES,
    flow: [],
    asks: [ask({
      id: "a1", requester: "engineering", recipient: "quality",
      question: "取消订单的判定标准是什么？\n第 2 版交付里没写清楚。",
      started_at: "2026-11-01T09:10:00Z", status: "已回答",
      answer: "以支付前取消为准。\n之后取消的都算已支付。",
      ended_at: "2026-11-01T09:15:00Z",
    })],
    decisions: [],
    now: "2026-11-01T09:30:00Z",
  });
  const question = askDetail(view, "ask:a1");
  assert.equal(question.question, "取消订单的判定标准是什么？\n第 2 版交付里没写清楚。");
  assert.equal(question.answer, "以支付前取消为准。\n之后取消的都算已支付。");
  assert.equal(question.fromLabel, "工程");
  assert.equal(question.toLabel, "质检");
  assert.equal(question.parent, null);
  // 点回答那一行打开的是同一个面板：问题与回答都在
  assert.deepEqual(askDetail(view, "ask:a1:answer"), question);
  // 图上那一行只有一句标题
  assert.equal(rowOf(view, "ask:a1").title.includes("\n"), false);
});

test("询问里又问的那一次，面板写明是回答哪一次询问时问的", () => {
  const view = fullRun();
  // a3 是回答 a2 时又问工程的那一次
  assert.equal(askDetail(view, "ask:a3").parent, "取消订单的判定标准是什么？");
  // 最外层那一次不写「又问的」
  assert.equal(askDetail(view, "ask:a2").parent, null);
  assert.equal(askDetail(view, "ask:a2").question, "取消订单的判定标准是什么？");
});

test("工程回答质检时回答分事实与解释，解释旁写明质检对哪一版下了结论以后才看到", () => {
  const view = sequenceOf({
    roles: ROLES,
    flow: [
      flow({ flow_id: "f-del", event_id: "e-del", kind: "版本交付", position: 2, direction_from: "engineering", direction_to: "quality", content: "第 1 版交付", round: 1, created_at: "2026-11-01T09:00:00Z" }),
    ],
    asks: [ask({
      id: "a1", requester: "quality", recipient: "engineering", question: "取消为什么不留记录？",
      started_at: "2026-11-01T09:10:00Z", start_position: 3, status: "已回答",
      answer: "记录写在 orders/log.ts", answer_facts: "取消的写入在 orders/log.ts 第 20 行",
      answer_explanation: "按交付 v1 的设计只留一条记录", ended_at: "2026-11-01T09:20:00Z",
    })],
    decisions: [],
    verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["交付"] }] }],
    materials: { deliveries: [{ event_id: "e-del", revision: 1 }] },
    now: "2026-11-01T09:30:00Z",
  });
  const detail = askDetail(view, "ask:a1");
  assert.equal(detail.facts, "取消的写入在 orders/log.ts 第 20 行");
  assert.equal(detail.explanation, "按交付 v1 的设计只留一条记录");
  assert.equal(detail.explanationNote, "质检对交付第 1 版下结论以后才看到");
});

test("不是核验角色问的，或者还没有解释时，解释旁不写那句话", () => {
  const view = sequenceOf({
    roles: ROLES,
    flow: [],
    asks: [ask({
      id: "a1", requester: "engineering", recipient: "product", question: "验收标准按哪一版？",
      started_at: "2026-11-01T09:10:00Z", status: "已回答",
      answer: "按 PRD v1", answer_facts: "PRD v1 第 3 节", answer_explanation: "PRD v1 就是最新一版",
      ended_at: "2026-11-01T09:20:00Z",
    })],
    decisions: [],
    verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["交付"] }] }],
  });
  const detail = askDetail(view, "ask:a1");
  assert.equal(detail.facts, "PRD v1 第 3 节");
  assert.equal(detail.explanation, "PRD v1 就是最新一版");
  assert.equal(detail.explanationNote, null);
});

test("没能回答的那一次，面板写原因全文", () => {
  const view = sequenceOf({
    roles: ROLES,
    flow: [],
    asks: [ask({
      id: "a1", requester: "engineering", recipient: "quality", question: "这一版的检查回执在哪？",
      started_at: "2026-11-01T09:10:00Z", status: "没能回答", reason: "这一版没有跑检查", ended_at: "2026-11-01T09:12:00Z",
    })],
    decisions: [],
  });
  const detail = askDetail(view, "ask:a1");
  assert.equal(detail.status, "没能回答");
  assert.equal(detail.answer, null);
  assert.equal(detail.reason, "这一版没有跑检查");
  assert.equal(askDetail(view, "ask:a1:answer").status, "没能回答");
});

test("指导那一行也是全文：面板写发给谁与那句原话", () => {
  const view = sequenceOf({
    roles: ROLES,
    flow: [flow({
      flow_id: "f-g", event_id: "e-g", kind: "指导", position: 2, direction_to: "engineering",
      content: "取消的判定标准按支付前算\n其余照旧", round: 1, created_at: "2026-11-01T09:00:00Z",
    })],
    asks: [],
    decisions: [],
  });
  const detail = textDetail(view, "flow:e-g");
  assert.equal(detail.heading, "给工程的指导");
  assert.equal(detail.text, "取消的判定标准按支付前算\n其余照旧");
  // 图上那一行只有一句标题，全文在面板里
  assert.equal(rowOf(view, "flow:e-g").title.includes("\n"), false);
});

test("只看这两个职能：列只留它们两列，行只留它们之间的往来，来回的问答与交付都在", () => {
  const scoped = fullRun(undefined, ["engineering", "quality"]);
  assert.equal(scoped.scoped, true);
  assert.deepEqual(scoped.columns.map((column) => column.label), ["工程", "质检"]);
  // 你、产品与别人的往来都不在这张图里；询问、回答与交付照旧
  assert.deepEqual(scoped.rounds.flatMap((round) => round.rows.map((row) => row.key)),
    ["ask:a1", "ask:a1:answer", "flow:e-del1", "flow:e-del2"]);
  // 窄屏那一行仍写谁到谁
  assert.equal(rowOf(scoped, "ask:a1").who, "工程 → 质检");
  // 色条只画在留着的列上：工程等质检那一段在，等你决定的那一段不在
  assert.deepEqual(barOf(rowOf(scoped, "ask:a1"), "engineering"), ["ask"]);
  assert.equal(scoped.now, null);
  // 看整件事时是你加三个职能
  assert.equal(fullRun().scoped, false);
  assert.deepEqual(fullRun().columns.map((column) => column.label), ["你", "产品", "工程", "质检"]);
});

test("只看这两个职能时不含别的职能的问法（标识对不上）按整件事画，不留空图", () => {
  // 两个标识里有一个不是这份组织里的职能：不拿它顶替，退回看整件事
  const view = fullRun(undefined, ["engineering", "audit"]);
  assert.equal(view.scoped, false);
  assert.deepEqual(view.columns.map((column) => column.label), ["你", "产品", "工程", "质检"]);
});

test("只看这两个职能时它们之间还没有往来：图是空的，页面另写一句", () => {
  const view = sequenceOf({
    roles: ROLES,
    flow: [], asks: [], decisions: [], pair: ["product", "quality"],
  });
  assert.equal(view.scoped, true);
  assert.equal(view.empty, true);
  assert.deepEqual(view.columns.map((column) => column.label), ["产品", "质检"]);
});

test("只有一个职能时没有时序图（「看经过」也不出现）", () => {
  assert.equal(hasSequence([{ id: "engineering" }]), false);
  assert.equal(hasSequence([]), false);
  assert.equal(hasSequence([{ id: "product" }, { id: "engineering" }]), true);
  assert.equal(hasSequence(ROLES), true);
});
