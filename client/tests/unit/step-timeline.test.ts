// 部门工作间步骤时间线的纯函数（工单 #1235）：块的顺序、标题与标记的文字、折叠时的预览行、
// 激活选择的文字。期望值写成字面值，不复用实现的公式。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BLOCK_TITLES,
  ENCRYPTED_REASONING,
  NO_ACTIVATION,
  UNASSIGNED_TITLE,
  actionLines,
  activationLabel,
  discardedMark,
  foldedText,
  hasMoreText,
  lengthLabel,
  previewLines,
  selectedActivation,
  stepBlocks,
  stepTitle,
} from "../../src/renderer/src/views/project/step-timeline.ts";
import type {
  ActionView,
  ActivationView,
  RunStepView,
  RunStepsResult,
  StepText,
} from "../../src/renderer/src/api/generated/types.gen.ts";

function text(overrides: Partial<StepText> = {}): StepText {
  return {
    event_id: "evt_reasoning",
    readable: true,
    length: 240,
    preview: "先看代码。\n再看测试。\n第三行不显示。",
    ...overrides,
  };
}

function action(overrides: Partial<ActionView> = {}): ActionView {
  return {
    action_id: "a_1",
    tool: "list_files",
    department: "product",
    status: "completed",
    activation_id: "act-1",
    step_id: 1,
    input_version: 1,
    prompt_version: 0,
    created_at: "2026-10-30T00:00:00Z",
    receipt: {
      args: { command: "ls" },
      ok: true,
      error: null,
      output_ref: null,
      event_id: "evt_called",
      created_at: "2026-10-30T00:00:00Z",
    },
    ...overrides,
  };
}

function step(overrides: Partial<RunStepView> = {}): RunStepView {
  return {
    step_id: 1,
    requested_at: "2026-10-30T00:00:00Z",
    discarded_attempts: 0,
    reasoning: [],
    texts: [],
    actions: [],
    ...overrides,
  };
}

function activation(overrides: Partial<ActivationView> = {}): ActivationView {
  return {
    activation_id: "act-1",
    started_at: "2026-10-30T08:30:00Z",
    finished_at: "2026-10-30T08:40:00Z",
    step_count: 2,
    ...overrides,
  };
}

function result(overrides: Partial<RunStepsResult> = {}): RunStepsResult {
  return {
    activation_id: "act-1",
    activations: [activation()],
    steps: [],
    unassigned_actions: [],
    background_commands: [],
    ...overrides,
  };
}

test("有思考、话与两个动作的步骤：块的顺序是思考、话、动作", () => {
  const blocks = stepBlocks(step({
    reasoning: [text()],
    texts: [text({ event_id: "evt_text", length: 8, preview: "我先看一下。" })],
    actions: [action(), action({ action_id: "a_2", tool: "read_file" })],
  }));
  assert.deepEqual(blocks.map((block) => block.kind), ["thinking", "saying", "actions"]);
  assert.equal(BLOCK_TITLES.thinking, "模型的思考");
  assert.equal(BLOCK_TITLES.saying, "模型说的话");
  assert.equal(BLOCK_TITLES.actions, "动作与回执");
  const actions = blocks[2];
  assert.equal(actions.kind, "actions");
  assert.equal(actions.kind === "actions" ? actions.actions.length : 0, 2);
});

test("只有动作的步骤没有思考块与话块", () => {
  const blocks = stepBlocks(step({ actions: [action()] }));
  assert.deepEqual(blocks.map((block) => block.kind), ["actions"]);
});

test("什么都没有的步骤没有块（标题行照写）", () => {
  assert.deepEqual(stepBlocks(step()), []);
  assert.equal(stepTitle(step({ step_id: 7 })), "第 7 步");
});

test("读不出来的思考写固定的说法", () => {
  assert.equal(ENCRYPTED_REASONING, "上游只返回了加密的推理，看不到内容");
  const encrypted = text({ readable: false, length: 0, preview: "" });
  assert.equal(encrypted.readable, false);
  assert.equal(foldedText(encrypted), "");
});

test("被丢弃的尝试在标题上有标记", () => {
  assert.equal(discardedMark(step({ discarded_attempts: 0 })), null);
  assert.equal(discardedMark(step({ discarded_attempts: 1 })), "调用失败 一次，已重试");
  assert.equal(discardedMark(step({ discarded_attempts: 2 })), "调用失败 2 次，已重试");
});

test("折叠时只显示预览的前两行与字数", () => {
  const value = text();
  assert.deepEqual(previewLines(value), ["先看代码。", "再看测试。"]);
  assert.equal(foldedText(value), "先看代码。\n再看测试。");
  assert.equal(lengthLabel(value), "共 240 字");
  assert.equal(hasMoreText(value), true);
  // 全文与预览一样长时没有「展开全文」
  assert.equal(hasMoreText(text({ length: 3, preview: "三字。" })), false);
  assert.equal(hasMoreText(text({ readable: false, length: 0, preview: "" })), false);
});

test("激活一格的文字写第几次、开始时间、步数与进行中或已结束", () => {
  const finished = activationLabel(activation(), 0);
  assert.match(finished, /^第 1 次工作 · /);
  assert.match(finished, /共 2 步 · 已结束$/);
  const running = activationLabel(activation({ finished_at: null, step_count: 0 }), 2);
  assert.match(running, /^第 3 次工作 · /);
  assert.match(running, /共 0 步 · 进行中$/);
});

test("选中的激活：给定时用给定的，给的不在列表里时用最近一次", () => {
  const earlier = activation({ activation_id: "act-0" });
  const latest = activation({ activation_id: "act-1" });
  const value = result({ activations: [earlier, latest] });
  assert.equal(selectedActivation(value, null)?.activation_id, "act-1");
  assert.equal(selectedActivation(value, "act-0")?.activation_id, "act-0");
  assert.equal(selectedActivation(value, "act-missing")?.activation_id, "act-1");
  assert.equal(selectedActivation(result({ activations: [] }), null), null);
});

test("动作的两行文字：工具、命令、状态与主机回执", () => {
  const lines = actionLines(action());
  assert.equal(lines.tool, "list_files");
  assert.equal(lines.command, "ls");
  assert.equal(lines.status, "已完成");
  assert.equal(lines.receipt, "成功");
  assert.equal(lines.output, "无");
  const failed = actionLines(action({
    status: "failed",
    receipt: {
      args: {}, ok: false, error: "命令没有成功", output_ref: { path: "out.txt" },
      event_id: "evt_failed", created_at: "2026-10-30T00:00:00Z",
    },
  }));
  assert.equal(failed.status, "失败");
  assert.equal(failed.receipt, "命令没有成功");
  assert.equal(failed.output, "有（见原始事件）");
  const missing = actionLines(action({ receipt: null, status: "unknown" }));
  assert.equal(missing.receipt, "没有回执");
  assert.equal(missing.status, "结果未知");
});

test("没有激活时的空状态说法", () => {
  assert.equal(NO_ACTIVATION, "这个部门在这次运行里还没有工作记录");
  assert.equal(UNASSIGNED_TITLE, "未归到步骤的动作");
});
