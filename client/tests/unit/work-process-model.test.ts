// 原文面板里「看工作过程」的纯函数（工单 #1658）：行的整理、连续同一种类的折叠、原始数据的几格、
// 每一步的调用尝试编号，以及时序图一行到激活的对应。期望值写成字面值，不复用实现的公式。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  NO_ACTIVATION_TEXT,
  activationsOf,
  activationOf,
  askIdOfRowKey,
  attemptLinks,
  foldedLineText,
  rawFields,
  targetText,
  workGroups,
  workLines,
  workTargetOfArrow,
  workTargetOfRow,
} from "../../src/renderer/src/views/project/work-process-model.ts";
import type {
  ActionView,
  ActivationView,
  RunStepView,
  RunStepsResult,
  StepText,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import type { LoopArrow } from "../../src/renderer/src/views/project/loop-graph-model.ts";
import type { SequenceRow } from "../../src/renderer/src/views/project/sequence-model.ts";

function action(overrides: Partial<ActionView> = {}): ActionView {
  return {
    action_id: "a_1",
    tool: "read_file",
    department: "engineering",
    status: "completed",
    activation_id: "act-1",
    step_id: 1,
    input_version: 1,
    prompt_version: 0,
    created_at: "2026-11-09T02:00:00Z",
    receipt: {
      args: { path: "orders/list.ts" },
      ok: true,
      error: null,
      output_ref: null,
      event_id: "evt_called",
      created_at: "2026-11-09T02:00:01Z",
    },
    mark: "读",
    title: "读取 orders/list.ts",
    title_source: "系统",
    facts: [],
    ...overrides,
  };
}

function text(overrides: Partial<StepText> = {}): StepText {
  return {
    event_id: "evt_text",
    readable: true,
    length: 12,
    preview: "先看分页实现。",
    ...overrides,
  };
}

function step(overrides: Partial<RunStepView> = {}): RunStepView {
  return {
    step_id: 1,
    requested_at: "2026-11-09T02:00:00Z",
    discarded_attempts: 0,
    reasoning: [],
    texts: [],
    actions: [],
    attempt_ids: ["att-1"],
    title: null,
    title_source: null,
    ...overrides,
  };
}

function result(overrides: Partial<RunStepsResult> = {}): RunStepsResult {
  return {
    activation_id: "act-1",
    activations: [],
    steps: [],
    unassigned_actions: [],
    background_commands: [],
    ...overrides,
  };
}

function activation(overrides: Partial<ActivationView> = {}): ActivationView {
  return {
    activation_id: "act-1",
    started_at: "2026-11-09T02:00:00Z",
    finished_at: "2026-11-09T02:10:00Z",
    step_count: 2,
    session_id: "sess-engineering",
    cycle: 1,
    ...overrides,
  };
}

function arrow(overrides: Partial<LoopArrow> = {}): LoopArrow {
  return {
    key: "flow-1",
    outcome: "交付",
    version: 2,
    round: 3,
    from: "engineering",
    to: "quality",
    back: false,
    position: 12,
    verdict: null,
    text: "分页交付第 2 版",
    files: [],
    ...overrides,
  };
}

function row(overrides: Partial<SequenceRow> = {}): SequenceRow {
  return {
    key: "flow:evt-1",
    kind: "outcome",
    dashed: false,
    from: "engineering",
    to: ["quality"],
    who: "工程 → 质检",
    at: "2026-11-09T02:00:00Z",
    title: "交付 v2",
    depth: 0,
    round: 3,
    verdict: null,
    open: false,
    bars: [],
    detail: { kind: "text", heading: "交付", text: "分页交付第 2 版", note: null },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// 行：每个动作一行，标记加标题；只有文字的一步一行

test("每个动作一行：标记与标题照服务端从同一份工具定义算出来的那一行，行里没有整段命令", () => {
  // R3：工作过程读得懂（设计说明「动作标记」「动作标题」）
  const lines = workLines(result({
    steps: [step({
      actions: [
        action({ action_id: "a_1", mark: "运行", title: "运行命令：npm test", title_source: "系统" }),
        action({ action_id: "a_2", tool: "bash", mark: "运行", title: "补一条空列表的用例", title_source: "作者" }),
      ],
    })],
  }));
  assert.deepEqual(lines.map((line) => [line.mark, line.title, line.titleSource]), [
    ["运行", "运行命令：npm test", "系统"],
    ["运行", "补一条空列表的用例", "作者"],
  ]);
  // 行上的字就是标题本身：那一步的命令原文只出现在原始数据里
  assert.equal(lines[0].kind, "action");
  assert.equal(lines[0].action?.action_id, "a_1");
  assert.equal(lines[0].stepId, 1);
});

test("只有文字、没有动作的一步一行：没有种类标记，来源记作者", () => {
  // R3：工作过程读得懂（设计说明「动作标题」的最后一条）
  const lines = workLines(result({
    steps: [
      step({ step_id: 1, title: "先看分页实现，再决定问谁", title_source: "作者", texts: [text()] }),
      step({ step_id: 2, actions: [action()] }),
    ],
  }));
  assert.deepEqual(lines.map((line) => [line.kind, line.mark, line.title, line.titleSource]), [
    ["text", null, "先看分页实现，再决定问谁", "作者"],
    ["action", "读", "读取 orders/list.ts", "系统"],
  ]);
});

test("一步里有动作时不多出一行：行数就是动作数", () => {
  // R3：工作过程读得懂
  const lines = workLines(result({
    steps: [step({
      texts: [text()],
      reasoning: [text({ event_id: "evt_reasoning" })],
      actions: [action({ action_id: "a_1" }), action({ action_id: "a_2", title: "搜索「pageCount」" })],
    })],
  }));
  assert.equal(lines.length, 2);
  // 这一步的推理与模型文字跟着行，点开时在原始数据里
  assert.deepEqual(lines[0].reasoning.map((item) => item.event_id), ["evt_reasoning"]);
  assert.deepEqual(lines[0].texts.map((item) => item.event_id), ["evt_text"]);
});

test("没有归到步骤的动作照实列出，排在最后，也不丢掉", () => {
  // R3：工作过程读得懂（run.steps 的 unassigned_actions）
  const lines = workLines(result({
    steps: [step({ actions: [action({ action_id: "a_1" })] })],
    unassigned_actions: [action({ action_id: "a_9", step_id: null, title: "停止后台命令" })],
  }));
  assert.deepEqual(lines.map((line) => line.key), ["action:a_1", "action:a_9"]);
  assert.equal(lines[1].reasoning.length, 0);
  assert.deepEqual(lines[1].attemptIds, []);
});

// ---------------------------------------------------------------------------
// 折叠：连续同一种类折成一行并写数量

test("连续同一种类的动作折成一行并写数量，点开才是每一行", () => {
  // R3：工作过程读得懂（设计说明「任务分组」的最后一条）
  const lines = workLines(result({
    steps: [step({
      actions: [
        action({ action_id: "a_1", mark: "读", title: "读取 a.ts" }),
        action({ action_id: "a_2", mark: "读", title: "读取 b.ts" }),
        action({ action_id: "a_3", mark: "读", title: "读取 c.ts" }),
        action({ action_id: "a_4", mark: "运行", title: "运行命令：npm test" }),
      ],
    })],
  }));
  const groups = workGroups(lines);
  assert.deepEqual(groups.map((group) => [group.foldedTitle, group.lines.length]), [
    [foldedLineText("读", 3), 3],
    ["", 1],
  ]);
  assert.equal(groups[0].foldedTitle, "读了 3 次");
  assert.deepEqual(groups[0].lines.map((line) => line.title), ["读取 a.ts", "读取 b.ts", "读取 c.ts"]);
});

test("中间夹着别的种类时不合并；一种只出现一次时也不折", () => {
  // R3：工作过程读得懂
  const lines = workLines(result({
    steps: [step({
      actions: [
        action({ action_id: "a_1", mark: "读" }),
        action({ action_id: "a_2", mark: "写", title: "写入 orders/list.ts" }),
        action({ action_id: "a_3", mark: "读" }),
      ],
    })],
  }));
  assert.deepEqual(workGroups(lines).map((group) => group.lines.length), [1, 1, 1]);
  assert.deepEqual(workGroups(lines).map((group) => group.foldedTitle), ["", "", ""]);
});

test("只有文字的一步不折，也不与相邻的动作合并", () => {
  // R3：工作过程读得懂
  const lines = workLines(result({
    steps: [
      step({ step_id: 1, actions: [action({ action_id: "a_1", mark: "读" })] }),
      step({ step_id: 2, title: "写完了，检查一遍", title_source: "作者" }),
      step({ step_id: 3, actions: [action({ action_id: "a_2", mark: "读", title: "读取 b.ts" })] }),
    ],
  }));
  assert.deepEqual(workGroups(lines).map((group) => [group.foldedTitle, group.lines.length]), [
    ["", 1],
    ["", 1],
    ["", 1],
  ]);
});

test("没有种类标记的动作不折：数不出「读了几个」的时候不写那一句", () => {
  // R3：工作过程读得懂（不认识的工具写工具名，没有种类）
  const lines = workLines(result({
    steps: [step({
      actions: [
        action({ action_id: "a_1", tool: "some_tool", mark: null, title: "some_tool", title_source: "系统" }),
        action({ action_id: "a_2", tool: "some_tool", mark: null, title: "some_tool", title_source: "系统" }),
      ],
    })],
  }));
  assert.deepEqual(workGroups(lines).map((group) => [group.foldedTitle, group.lines.length]), [["", 1], ["", 1]]);
});

// ---------------------------------------------------------------------------
// 原始数据：命令、参数、退出状态、输出

test("原始数据：命令、参数（不含命令那一项）、退出状态与输出", () => {
  // R3：点一行看到命令原文、参数、退出状态、输出（设计说明 4.4 与工单验收）
  const fields = rawFields({
    action: action({
      tool: "bash",
      mark: "运行",
      title: "补一条空列表的用例",
      receipt: {
        args: { command: "npm test -- order-list", cwd: "client" },
        ok: true,
        error: null,
        output_ref: null,
        event_id: "evt_called",
        created_at: "2026-11-09T02:00:01Z",
      },
    }),
    output: { status: "ok", exit_code: 0, output: "Tests: 9 passed, 9 total" },
    summary: "成功",
  });
  assert.deepEqual(fields, [
    { label: "命令", value: "npm test -- order-list" },
    { label: "参数", value: JSON.stringify({ cwd: "client" }, null, 2) },
    { label: "退出状态", value: "0" },
    { label: "输出", value: "Tests: 9 passed, 9 total" },
    { label: "回执", value: "成功" },
  ]);
});

test("原始数据：输出工件是字符串时原样写（读文件这类工具），没有退出状态就不写那一格", () => {
  // R3：点一行看到输出
  const fields = rawFields({ action: action(), output: "export function pageCount(total) {}", summary: "成功" });
  assert.deepEqual(fields, [
    { label: "参数", value: JSON.stringify({ path: "orders/list.ts" }, null, 2) },
    { label: "输出", value: "export function pageCount(total) {}" },
    { label: "回执", value: "成功" },
  ]);
});

test("原始数据：取不到输出工件时只写参数与回执，不拿空占位补", () => {
  // R3：事实照实说（不补假内容）
  const fields = rawFields({ action: action(), output: null, summary: "没有回执" });
  assert.deepEqual(fields.map((field) => field.label), ["参数", "回执"]);
});

test("原始数据：没有回执的动作没有命令与参数，输出取工件里的那一层", () => {
  // R3：事实照实说
  const fields = rawFields({ action: action({ receipt: null }), output: { output: "还在运行" } });
  assert.deepEqual(fields, [{ label: "输出", value: "还在运行" }]);
});

test("原始数据：输出工件里没有文字时按 JSON 写出来（搜索这类工具的结果）", () => {
  // R3：点一行看到输出（原样，不改写成摘要）
  const output = { pattern: "pageCount", total_matches: 2, matches: [{ path: "orders/list.ts", line: 3 }] };
  const fields = rawFields({ action: action(), output, summary: "成功" });
  assert.deepEqual(fields.at(-2), { label: "输出", value: JSON.stringify(output, null, 2) });
});

// ---------------------------------------------------------------------------
// 每一步的调用尝试编号：被丢弃的也能点

test("每一步的调用尝试编号都列出来，被丢弃的排在前面并标出来", () => {
  // R2：run.steps 的 attempt_ids（含被丢弃的）进请求详情页（工单 #1657 的字段）
  const lines = workLines(result({
    steps: [
      step({ step_id: 1, attempt_ids: ["att-1"], actions: [action()] }),
      step({ step_id: 3, attempt_ids: ["att-3a", "att-3b"], discarded_attempts: 1,
             actions: [action({ action_id: "a_3", step_id: 3 })] }),
    ],
  }));
  assert.deepEqual(attemptLinks(lines[1]), [{ id: "att-3a", discarded: true }, { id: "att-3b", discarded: false }]);
  assert.deepEqual(attemptLinks(lines[0]), [{ id: "att-1", discarded: false }]);
});

// ---------------------------------------------------------------------------
// 时序图一行到激活的对应

test("成果那一行看产生这一版的职能那一轮", () => {
  // R3：点交付那一行看到产生这一版的那一轮
  assert.deepEqual(workTargetOfRow(row()), { kind: "cycle", department: "engineering", cycle: 3 });
  assert.deepEqual(workTargetOfArrow(arrow()), { kind: "cycle", department: "engineering", cycle: 3 });
});

test("询问与回答那一行看被询问职能那次回答的会话", () => {
  // R3：点询问或回答那一行看到被询问职能那次回答的经过
  const asked = row({ key: "ask:ask-1", kind: "ask", open: false, from: "quality", to: ["engineering"], round: 2 });
  const answered = row({ key: "ask:ask-1:answer", kind: "answer", open: false, from: "engineering", to: ["quality"] });
  assert.deepEqual(workTargetOfRow(asked), { kind: "session", department: "engineering", sessionId: "ask-1" });
  assert.deepEqual(workTargetOfRow(answered), { kind: "session", department: "engineering", sessionId: "ask-1" });
  assert.equal(askIdOfRowKey("ask:ask-1:answer"), "ask-1");
  assert.equal(askIdOfRowKey("flow:evt-1"), null);
});

test("还没有对应激活的询问、决定、指导与你的输入都没有入口", () => {
  // R3：设计说明 4.14「工作过程」只在成果与问答那一行有入口
  assert.equal(workTargetOfRow(row({ key: "ask:ask-2", kind: "ask", open: true })), null);
  assert.equal(workTargetOfRow(row({ kind: "decide" })), null);
  assert.equal(workTargetOfRow(row({ kind: "decided" })), null);
  assert.equal(workTargetOfRow(row({ kind: "guidance", from: "you", to: ["engineering"] })), null);
  assert.equal(workTargetOfRow(row({ kind: "input", from: "you", to: ["product"] })), null);
  // 图外进来的那一端（你的输入）与没有轮次的箭头也没有入口
  assert.equal(workTargetOfArrow(arrow({ from: "src", round: null })), null);
  assert.equal(workTargetOfArrow(arrow({ round: null })), null);
});

test("同一轮有几次激活时都列出来，默认最后一次", () => {
  // R3：同一轮有几次激活时都列出来，默认最后一次（工单正文）
  const activations = [
    activation({ activation_id: "act-1", cycle: 3, started_at: "2026-11-09T02:00:00Z" }),
    activation({ activation_id: "act-2", cycle: 3, started_at: "2026-11-09T02:20:00Z" }),
    activation({ activation_id: "act-3", cycle: 4, started_at: "2026-11-09T03:00:00Z" }),
  ];
  const target = { kind: "cycle" as const, department: "engineering", cycle: 3 };
  assert.deepEqual(activationsOf(activations, target).map((item) => item.activation_id), ["act-1", "act-2"]);
  assert.equal(activationOf(activations, target)?.activation_id, "act-2");
});

test("询问分支的激活按会话编号找：它的第几轮可能是空的", () => {
  // R3：询问与回答看被询问职能那次回答（询问编号对激活的会话编号）
  const activations = [
    activation({ activation_id: "act-main", session_id: "sess-engineering", cycle: 2 }),
    activation({ activation_id: "act-branch", session_id: "ask-1", cycle: null }),
  ];
  const target = { kind: "session" as const, department: "engineering", sessionId: "ask-1" };
  assert.equal(activationOf(activations, target)?.activation_id, "act-branch");
  assert.deepEqual(activationsOf(activations, { kind: "cycle", department: "engineering", cycle: 2 })
    .map((item) => item.activation_id), ["act-main"]);
});

test("找不到对应激活时为空：页面照实说没有读到，不拿最近一次顶替", () => {
  // R3：事实照实说
  const activations = [activation({ activation_id: "act-1", cycle: 4 })];
  assert.equal(activationOf(activations, { kind: "cycle", department: "engineering", cycle: 3 }), null);
  assert.equal(NO_ACTIVATION_TEXT, "没有找到这一轮的工作过程");
});

test("入口旁边写的是哪一轮或哪一次回答", () => {
  // R3：用户在面板上认得出看的是哪一轮
  assert.equal(targetText({ kind: "cycle", department: "engineering", cycle: 2 }), "第 2 轮");
  assert.equal(targetText({ kind: "session", department: "engineering", sessionId: "ask-1" }), "这次回答");
});
