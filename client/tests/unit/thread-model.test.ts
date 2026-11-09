// 对话线程的事实推出（工单 #1639，项目的组织设计说明 4.14「项目页是循环图加对话」的交互骨架第 1 至 3 条）。
//
// 守的是三环里的 R1（事实照实说）：线程里出现的每一条话都从已经发生过的事实推出——
// 你写的与指导取 project.flow，角色之间的往来与问答取 run.asks，要你决定的取 decisions.list，
// 交完成、放行与事项的结果取事项状态与流转记录；不另存一份，也不在页面上编内容。
//
// 覆盖工单验收要的：三种默认消息（你写的、要你决定的、交完成或放行）、折叠行的合并与打断、
// 答完的询问进折叠行而进行中的不进、工程回答质检的事实与解释、收件人默认值与连续发送、
// 以及换了形态以后按在跑事项冻结的组织给选项。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  LONG_TEXT_LIMIT, afterSend, chosenRecipient, decisionsForItem, defaultRecipient, draftChanged,
  isLongText, itemThread, projectDecisions, receiverOf, recipientHint, recipientOptions, shortText,
  type ComposerInput, type ComposerState, type ThreadAsk, type ThreadDecision, type ThreadFlowRecord,
  type ThreadItemView, type ThreadOrganization,
} from "../../src/renderer/src/views/project/thread-model.ts";

/** 产品 · 工程 · 质检（与发布里的三部门形态同一个结构）。 */
function three(): ThreadOrganization {
  return {
    form: "three",
    routing: "watched_outputs",
    roles: [
      { id: "product", label: "产品" },
      { id: "engineering", label: "工程" },
      { id: "quality", label: "质检" },
    ],
    verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["delivery_spec"] }] }],
    completing: null,
    watched: [
      { source: "product", recipient: "engineering", outcome: "product_spec" },
      { source: "engineering", recipient: "quality", outcome: "delivery_spec" },
      { source: "quality", recipient: "engineering", outcome: "defect_record" },
      { source: "product", recipient: "quality", outcome: "product_spec" },
    ],
    asks: [],
    rejections: [{ verifier: "quality", role: "engineering", outcome: "delivery_spec" }],
  };
}

/** 产品 · 工程（直做，工程接来源）。 */
function directTwo(): ThreadOrganization {
  return {
    form: "several",
    routing: "direct",
    roles: [{ id: "product", label: "产品" }, { id: "engineering", label: "工程" }],
    verifiers: [],
    completing: null,
    watched: [],
    asks: [],
    rejections: [],
  };
}

/** 工程（一个职能直做）。 */
function directOne(): ThreadOrganization {
  return {
    form: "single",
    routing: "direct",
    roles: [{ id: "engineering", label: "工程" }],
    verifiers: [],
    completing: { id: "engineering", label: "工程" },
    watched: [],
    asks: [],
    rejections: [],
  };
}

function at(minute: number): string {
  return new Date(Date.UTC(2026, 10, 1, 9, minute, 0)).toISOString();
}

function item(fields: Partial<ThreadItemView> & Pick<ThreadItemView, "work_item_id">): ThreadItemView {
  return {
    kind: "change", status: "in_progress", round: 1, started_at: at(0), stop_reason: null,
    department: "engineering", departments: null, organization: three(), ...fields,
  };
}

function rec(fields: Partial<ThreadFlowRecord> & Pick<ThreadFlowRecord, "flow_id" | "kind" | "position">): ThreadFlowRecord {
  return {
    content: "", direction_from: null, direction_to: null, round: 1, created_at: at(fields.position), ...fields,
  };
}

function ask(fields: Partial<ThreadAsk> & Pick<ThreadAsk, "id" | "requester" | "recipient" | "question" | "started_at">): ThreadAsk {
  return {
    status: "已回答", answer: "答完了", answer_facts: null, answer_explanation: null,
    ended_at: fields.started_at, start_position: 0, ...fields,
  };
}

function decision(fields: Partial<ThreadDecision> & Pick<ThreadDecision, "decision_id" | "status" | "requested_at">): ThreadDecision {
  return {
    kind: "qa_cannot_verify", work_item_id: "w1", version: 1,
    request: { options: [{ id: "ok", label: "继续" }], description: "要你决定" }, answer: null, ...fields,
  };
}

/** 一条时间线：`entries` 里能看见的那些话按时间不倒流（测试里多处核对这一条）。 */
function times(entries: ReturnType<typeof itemThread>): number[] {
  return entries
    .filter((entry) => entry.kind !== "sep")
    .map((entry) => Date.parse((entry as { at: string }).at));
}

test("三种默认消息：你写的、要你决定的、交完成或放行；角色之间的往来只折成一行，不另露原话", () => {
  const organization = three();
  const flow = [
    rec({ flow_id: "in1", kind: "你的输入", position: 0, round: 0, content: "把订单导出成 CSV" }),
    rec({ flow_id: "prd1", kind: "PRD 新版本", position: 1, direction_from: "product", direction_to: "engineering", content: "PRD 第 1 版：按创建时间倒序" }),
    rec({ flow_id: "del1", kind: "版本交付", position: 2, direction_from: "engineering", direction_to: "quality", content: "导出第 1 版" }),
    rec({ flow_id: "def1", kind: "问题反馈", position: 3, direction_from: "quality", direction_to: "engineering", content: "金额列四舍五入错一分" }),
  ];
  const asks = [ask({
    id: "a1", requester: "engineering", recipient: "product", question: "已取消的订单还能退款吗？",
    answer: "不能，已取消只能终止。", started_at: at(2), ended_at: at(3), start_position: 2,
  })];
  const decisions = [decision({ decision_id: "d1", status: "open", requested_at: at(4) })];

  const entries = itemThread({
    item: item({ work_item_id: "w1", organization }), flow, asks, decisions,
    titles: { w1: "导出订单为 CSV" }, expanded: true,
  });

  // 默认露出的三种话加上事项之间的细线；其余都是折叠行
  const kinds = entries.map((entry) => entry.kind);
  assert.equal(kinds[0], "sep");
  for (const entry of entries.slice(1)) {
    assert.ok(["you", "decision", "done", "fold"].includes(entry.kind), `多出了 ${entry.kind}`);
  }
  // 角色之间的话不在顶层：它们只出现在折叠行的 messages 里
  const topText = entries.flatMap((entry) => (entry.kind === "you" ? [entry.text] : []));
  assert.deepEqual(topText, ["把订单导出成 CSV"]);
  const folds = entries.filter((entry) => entry.kind === "fold");
  // 产品 → 工程、工程与质检（交付与退回同一对，连续着折成一行）、工程 → 产品（那次问答）
  assert.equal(folds.length, 3);
  const foldedTexts = folds.flatMap((fold) => fold.messages.map((message) => message.text));
  assert.ok(foldedTexts.includes("PRD 第 1 版：按创建时间倒序"));
  assert.ok(foldedTexts.includes("导出第 1 版"));
  assert.ok(foldedTexts.includes("金额列四舍五入错一分"));
  // 你写的这一条带「开始一个新事项」的标签，长文本另标出来
  const you = entries.find((entry) => entry.kind === "you");
  assert.equal(you?.kind === "you" ? you.tag : "", "开始一个新事项");
});

test("折叠行只合并连续的往来：你写的话打断以后另起一行，时间不倒流", () => {
  const flow = [
    rec({ flow_id: "in1", kind: "你的输入", position: 0, round: 0, content: "开始做" }),
    rec({ flow_id: "in2", kind: "你的输入", position: 4, round: 2, content: "再补一句" }),
  ];
  const asks = [
    ask({ id: "a1", requester: "engineering", recipient: "product", question: "问一", answer: "答一", started_at: at(1), ended_at: at(2) }),
    ask({ id: "a2", requester: "engineering", recipient: "product", question: "问二", answer: "答二", started_at: at(2), ended_at: at(3) }),
    ask({ id: "a3", requester: "engineering", recipient: "product", question: "问三", answer: "答三", started_at: at(5), ended_at: at(6) }),
  ];
  const entries = itemThread({
    item: item({ work_item_id: "w1", organization: three() }), flow, asks, decisions: [],
    titles: { w1: "做导出" }, expanded: true,
  });

  assert.deepEqual(entries.map((entry) => entry.kind), ["sep", "you", "fold", "you", "fold"]);
  const folds = entries.filter((entry) => entry.kind === "fold");
  // 第一条折叠行是两次连续的往来，四个消息；被打断以后第三条另起一行
  assert.deepEqual(folds.map((fold) => fold.messages.length), [4, 2]);
  assert.equal(folds[0]?.kind === "fold" ? folds[0].label : "", "工程与产品往来");
  assert.deepEqual(folds[0]?.kind === "fold" ? folds[0].messages.map((message) => message.text) : [],
    ["问一", "答一", "问二", "答二"]);
  const readed = times(entries);
  assert.deepEqual(readed, [...readed].sort((left, right) => left - right));
});

test("答完的询问收进折叠行，进行中的询问不进线程", () => {
  const asks = [
    ask({ id: "a1", requester: "quality", recipient: "engineering", question: "交付 v1 的金额怎么算的？", answer: "按分计算", started_at: at(1), ended_at: at(2) }),
    ask({ id: "a2", requester: "engineering", recipient: "quality", question: "这条验收标准指哪一版？", status: "进行中", answer: null, started_at: at(3) }),
  ];
  const entries = itemThread({
    item: item({ work_item_id: "w1", organization: three() }), flow: [], asks, decisions: [],
    titles: { w1: "做导出" }, expanded: true,
  });
  const folds = entries.filter((entry) => entry.kind === "fold");
  assert.equal(folds.length, 1);
  if (folds[0]?.kind !== "fold") {
    return;
  }
  assert.deepEqual(folds[0].messages.map((message) => message.role), ["question", "answer"]);
  assert.equal(folds[0].messages[0]?.text, "交付 v1 的金额怎么算的？");
  assert.equal(folds[0].messages[1]?.text, "按分计算");
  // 进行中的那一条一个字都没有进线程
  assert.ok(!JSON.stringify(entries).includes("这条验收标准指哪一版？"));
});

test("工程回答质检：回答分事实与解释，解释旁写明质检对哪一版下了结论以后才看到", () => {
  const flow = [
    rec({ flow_id: "del1", kind: "版本交付", position: 1, direction_from: "engineering", direction_to: "quality", content: "导出第 1 版" }),
    rec({ flow_id: "def1", kind: "问题反馈", position: 2, direction_from: "quality", direction_to: "engineering", content: "金额错一分" }),
    rec({ flow_id: "del2", kind: "版本交付", position: 3, direction_from: "engineering", direction_to: "quality", content: "导出第 2 版：金额改用分计算" }),
  ];
  const asks = [ask({
    id: "a1", requester: "quality", recipient: "engineering",
    question: "金额为什么改成按分算？", answer: "金额改成按分计算",
    answer_facts: "金额改成按分计算，19.995 导出成 20.00",
    answer_explanation: "先改金额，是因为四舍五入的偏差只出现在小数上",
    started_at: at(5), ended_at: at(6), start_position: 4,
  })];
  const entries = itemThread({
    item: item({ work_item_id: "w1", organization: three() }), flow, asks, decisions: [],
    titles: { w1: "做导出" }, expanded: true,
  });
  const fold = entries.filter((entry) => entry.kind === "fold")
    .find((entry) => entry.messages.some((message) => message.role === "answer"));
  assert.ok(fold !== undefined);
  if (fold === undefined) {
    return;
  }
  const answerAt = fold.messages.findIndex((message) => message.role === "answer");
  assert.ok(answerAt > 0);
  const answer = fold.messages[answerAt];
  assert.equal(answer?.role, "answer");
  assert.equal(answer?.facts, "金额改成按分计算，19.995 导出成 20.00");
  assert.equal(answer?.explanation, "先改金额，是因为四舍五入的偏差只出现在小数上");
  // 质检问、工程答：问的那一条写清问的是谁
  const question = fold.messages.find((message) => message.role === "question");
  assert.equal(question?.toLabel, "工程");
  assert.equal(answer?.explanationNote, "质检对交付第 2 版下结论以后才看到");
});

test("已结束的事项默认收起：只露细线与交完成那一条，展开才看完整的", () => {
  const flow = [
    rec({ flow_id: "in1", kind: "你的输入", position: 0, round: 0, content: "把日志清掉" }),
    rec({ flow_id: "del1", kind: "版本交付", position: 3, direction_from: "engineering", direction_to: null, content: "清掉 412 个文件" }),
  ];
  const ended = item({
    work_item_id: "w1", status: "released_unsettled", stop_reason: "open_loop", organization: directOne(),
  });
  const collapsed = itemThread({
    item: ended, flow, asks: [], decisions: [], titles: { w1: "清理日志" }, expanded: false,
  });
  assert.deepEqual(collapsed.map((entry) => entry.kind), ["sep", "done"]);
  const sep = collapsed[0];
  assert.equal(sep?.kind === "sep" ? sep.result : "", "开环完成");
  assert.equal(sep?.kind === "sep" ? sep.expandable : false, true);
  const done = collapsed[1];
  assert.equal(done?.kind === "done" ? done.label : "", "交完成");
  assert.match(done?.kind === "done" ? done.text : "", /开环完成：没有人核验/);
  assert.equal(done?.kind === "done" ? done.flowId : "", "del1");
  assert.equal(done?.kind === "done" ? done.whoLabel : "", "工程");

  const expanded = itemThread({
    item: ended, flow, asks: [], decisions: [], titles: { w1: "清理日志" }, expanded: true,
  });
  assert.deepEqual(expanded.map((entry) => entry.kind), ["sep", "you", "done"]);
});

test("放行那一条写核验角色的显示名与那一版；看这一版指向交完成的那一版交付", () => {
  const flow = [
    rec({ flow_id: "del1", kind: "版本交付", position: 2, direction_from: "engineering", direction_to: "quality", content: "导出第 1 版" }),
    rec({ flow_id: "del2", kind: "版本交付", position: 4, direction_from: "engineering", direction_to: "quality", content: "导出第 2 版" }),
    rec({ flow_id: "rel1", kind: "放行", position: 5, direction_from: "quality", direction_to: "engineering", content: "核验了交付第 2 版：12 条用例通过" }),
  ];
  const adopted = item({ work_item_id: "w1", status: "adopted", organization: three() });
  const collapsed = itemThread({
    item: adopted, flow, asks: [], decisions: [], titles: { w1: "做导出" }, expanded: false,
  });
  assert.deepEqual(collapsed.map((entry) => entry.kind), ["sep", "done"]);
  const done = collapsed[1];
  assert.equal(done?.kind === "done" ? done.label : "", "放行");
  assert.equal(done?.kind === "done" ? done.whoLabel : "", "质检");
  assert.equal(done?.kind === "done" ? done.release : false, true);
  assert.match(done?.kind === "done" ? done.text : "", /核验了交付第 2 版/);
  assert.equal(done?.kind === "done" ? done.flowId : "", "del2");

  const expanded = itemThread({
    item: adopted, flow, asks: [], decisions: [], titles: { w1: "做导出" }, expanded: true,
  });
  // 放行与最后那一版交付是那一条结论；前面那一版交付仍在折叠行里
  const folds = expanded.filter((entry) => entry.kind === "fold");
  assert.deepEqual(folds.flatMap((fold) => fold.messages.map((message) => message.text)), ["导出第 1 版"]);
});

test("收件人默认值：没有事项在做时是开始一个新事项，有事项在做时给正在工作的职能", () => {
  const organization = three();
  const input: ComposerInput = {
    frozen: organization, roles: organization.roles, routing: organization.routing,
    receiver: "product", working: "engineering", focus: null, active: true,
  };
  assert.equal(defaultRecipient(input), "guide:engineering");
  assert.equal(defaultRecipient({ ...input, active: false }), "new");
  // 正在工作的职能读不到时回落到接输入的职能
  assert.equal(defaultRecipient({ ...input, working: null }), "guide:product");
  // 没有在跑的事项时，冻结的组织为空，用项目现在的组织
  const idle: ComposerInput = {
    frozen: null, roles: organization.roles, routing: organization.routing,
    receiver: "product", working: null, focus: null, active: false,
  };
  assert.equal(defaultRecipient(idle), "new");
});

test("收件人选项：直做只列接输入的职能，点了别的节点再多出它的一项；按成果每个职能一项并多出追加输入", () => {
  const direct = directTwo();
  const base: ComposerInput = {
    frozen: direct, roles: direct.roles, routing: direct.routing,
    receiver: "engineering", working: "engineering", focus: null, active: true,
  };
  assert.deepEqual(recipientOptions(base).map((option) => option.id), ["new", "guide:engineering"]);
  assert.equal(recipientOptions(base)[1]?.label, "给工程的指导");
  assert.deepEqual(recipientOptions({ ...base, focus: "product" }).map((option) => option.id),
    ["new", "guide:engineering", "guide:product"]);

  const watched = three();
  const rotation: ComposerInput = {
    frozen: watched, roles: watched.roles, routing: watched.routing,
    receiver: "product", working: "engineering", focus: null, active: true,
  };
  assert.deepEqual(recipientOptions(rotation).map((option) => option.id),
    ["new", "append", "guide:product", "guide:engineering", "guide:quality"]);
  assert.equal(recipientOptions(rotation)[1]?.label, "追加输入（产品接，重新验收）");
  // 没有事项在做时没有追加输入
  assert.deepEqual(recipientOptions({ ...rotation, active: false }).map((option) => option.id),
    ["new", "guide:product", "guide:engineering", "guide:quality"]);
  // 有事项在做时切到开始一个新事项，收件人一行写明排在谁后面
  assert.equal(recipientHint(rotation, "new", "做导出"), "排在「做导出」后面，它做完才开始");
});

test("选中的指导对象连续发送时保持不变；发送新事项或追加输入以后回到按状态选的默认；输入框里有字以后收件人不再随状态变", () => {
  const organization = three();
  const input: ComposerInput = {
    frozen: organization, roles: organization.roles, routing: organization.routing,
    receiver: "product", working: "engineering", focus: null, active: true,
  };
  let state: ComposerState = { manual: null, hold: null };
  assert.equal(chosenRecipient(input, state), "guide:engineering");
  // 发一条给质检的指导以后，再发时仍是给质检
  state = afterSend(state, "guide:quality");
  assert.equal(chosenRecipient(input, state), "guide:quality");
  assert.equal(chosenRecipient({ ...input, working: "product" }, state), "guide:quality");
  // 发一个新事项以后回到按状态选的默认
  state = afterSend(state, "new");
  assert.equal(chosenRecipient(input, state), "guide:engineering");
  assert.equal(chosenRecipient({ ...input, active: false }, state), "new");

  // 输入框里有字以后收件人不再随状态变，清空以后恢复
  let typed: ComposerState = { manual: null, hold: null };
  const current = chosenRecipient(input, typed);
  typed = draftChanged(typed, "把导出改成流式写出", current);
  assert.equal(chosenRecipient({ ...input, working: "quality" }, typed), "guide:engineering");
  typed = draftChanged(typed, "   ", current);
  assert.equal(chosenRecipient({ ...input, working: "quality" }, typed), "guide:quality");
});

test("项目换了形态以后，在跑事项的收件人选项仍按它冻结的组织", () => {
  const frozen = directTwo();
  const input: ComposerInput = {
    frozen, roles: [{ id: "quality", label: "质检" }], routing: "watched_outputs",
    receiver: "engineering", working: "engineering", focus: null, active: true,
  };
  assert.deepEqual(recipientOptions(input).map((option) => option.id), ["new", "guide:engineering"]);
  assert.deepEqual(recipientOptions(input).map((option) => option.label), ["开始一个新事项", "给工程的指导"]);

  // 接来源的职能：项目现在的组织与冻结的是同一份形态时照它的来源取，换过形态就不拿现在的顶替
  const flow = [rec({ flow_id: "del1", kind: "版本交付", position: 1, direction_from: "engineering" })];
  assert.equal(receiverOf(frozen, flow, { form: "several", sources: { user_input: "product" } }), "product");
  assert.equal(receiverOf(frozen, flow, { form: "other", sources: { user_input: "quality" } }), "engineering");
});

test("你写的话太长时折叠：标出长文本并给短的写法，短话原样", () => {
  const long = "把订单导出成 CSV，".repeat(20);
  assert.ok(long.length > LONG_TEXT_LIMIT);
  assert.equal(isLongText(long), true);
  const short = shortText(long);
  assert.ok(short.length <= LONG_TEXT_LIMIT + 1);
  assert.ok(short.endsWith("…"));
  assert.equal(isLongText("把首页文案改一下"), false);
  assert.equal(shortText("把首页文案改一下"), "把首页文案改一下");
});

test("要你决定的气泡按事项取；项目层面的那条不在任何事项下，另放在线程末尾", () => {
  const decisions = [
    decision({ decision_id: "d1", status: "open", requested_at: at(1) }),
    decision({ decision_id: "d2", status: "answered", requested_at: at(2), work_item_id: null }),
    decision({ decision_id: "d3", status: "withdrawn", requested_at: at(3) }),
  ];
  assert.deepEqual(decisionsForItem(decisions, "w1").map((entry) => entry.decision_id), ["d1"]);
  assert.deepEqual(projectDecisions(decisions).map((entry) => entry.decision_id), ["d2"]);
});
