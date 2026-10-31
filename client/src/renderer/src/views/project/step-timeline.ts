// 部门工作间检查区的步骤时间线（工单 #1235，应用层与接口层设计说明第 4.3 节 run.steps）：
// 把 run.steps 的结果整理成块的纯函数——块的顺序、标题与标记的文字、折叠时的预览行。
// 这个模块没有运行期依赖：页面只按它的结果排版，客户端单元测试直接调用它核对文字与顺序。

import type {
  ActionView,
  ActivationView,
  RunStepView,
  RunStepsResult,
  StepText,
} from "../../api/generated/types.gen";
import { actionCells } from "./action-table.ts";
import { formatTime } from "./labels.ts";

// 推理读不出来时的说法：上游只返回了加密内容（Responses 的 encrypted_content）
export const ENCRYPTED_REASONING = "上游只返回了加密的推理，看不到内容";

// 这个部门在这次运行里还没有工作记录（没有激活）
export const NO_ACTIVATION = "这个部门在这次运行里还没有工作记录";

// 没有运行时的空状态，沿用原来这一页的说法
export const NO_RUN = "这个范围没有运行，动作列表为空";

// 未归到步骤的动作那块的标题
export const UNASSIGNED_TITLE = "未归到步骤的动作";

// 各小块的标题：思考、话、动作（块的顺序按这个顺序排）
export const BLOCK_TITLES = {
  thinking: "模型的思考",
  saying: "模型说的话",
  actions: "动作与回执",
} as const;

export type StepBlock =
  | { kind: "thinking"; items: StepText[] }
  | { kind: "saying"; items: StepText[] }
  | { kind: "actions"; actions: ActionView[] };

// 一步里的块与它们的顺序：思考、话、动作；没有的那一类不出块。
// 失败与取消的尝试不进推理与文字（服务端已按这条规则给出），只在标题上留一个标记
export function stepBlocks(step: RunStepView): StepBlock[] {
  const blocks: StepBlock[] = [];
  if (step.reasoning.length > 0) {
    blocks.push({ kind: "thinking", items: step.reasoning });
  }
  if (step.texts.length > 0) {
    blocks.push({ kind: "saying", items: step.texts });
  }
  if (step.actions.length > 0) {
    blocks.push({ kind: "actions", actions: step.actions });
  }
  return blocks;
}

// 一步的标题：「第 N 步」
export function stepTitle(step: RunStepView): string {
  return `第 ${step.step_id} 步`;
}

// 被丢弃的调用尝试的标记：有失败或取消的尝试时写出来，读者不会以为那一次没发生过
export function discardedMark(step: RunStepView): string | null {
  if (step.discarded_attempts <= 0) {
    return null;
  }
  const times = step.discarded_attempts === 1 ? "一次" : `${step.discarded_attempts} 次`;
  return `调用失败 ${times}，已重试`;
}

// 折叠时显示预览的前两行
export function previewLines(value: StepText): string[] {
  return value.preview.split(/\r?\n/).slice(0, 2);
}

// 折叠时的正文：预览的前两行
export function foldedText(value: StepText): string {
  return previewLines(value).join("\n");
}

// 全文的字数
export function lengthLabel(value: StepText): string {
  return `共 ${value.length} 字`;
}

// 全文比预览长时才有「展开全文」
export function hasMoreText(value: StepText): boolean {
  return value.readable && value.length > value.preview.length;
}

// 激活的一格：「第 N 次工作 · 开始时间 · 共 M 步 · 进行中或已结束」
export function activationLabel(activation: ActivationView, index: number): string {
  const state = activation.finished_at === null ? "进行中" : "已结束";
  return `第 ${index + 1} 次工作 · ${formatTime(activation.started_at)} · 共 ${activation.step_count} 步 · ${state}`;
}

// 选中的激活：给定的编号在列表里时用它，否则用最近一次（列表按开始时间升序，最后一个最新）
export function selectedActivation(result: RunStepsResult, chosen: string | null): ActivationView | null {
  if (result.activations.length === 0) {
    return null;
  }
  if (chosen !== null) {
    const found = result.activations.find((item) => item.activation_id === chosen);
    if (found !== undefined) {
      return found;
    }
  }
  return result.activations[result.activations.length - 1];
}

// 一步里动作的两行文字：第一行是工具、命令原文与状态词，第二行是主机回执。
// 回执的文字沿用 action-table 的 actionCells（工具、命令、部门、状态、结果、输出引用），
// 部门这一格在步骤里不写（整个页签就是本部门的）
export interface ActionLines {
  tool: string;
  command: string;
  status: string;
  receipt: string;
  output: string;
  time: string;
}

export function actionLines(action: ActionView): ActionLines {
  const [tool, command, _department, status, receipt, output] = actionCells(action);
  return { tool, command, status, receipt, output, time: formatTime(action.created_at) };
}

// 时间线上的动作：每一步的动作按时间排（服务端已按时间给出），未归到步骤的动作另放一块
export function stepActions(step: RunStepView): ActionView[] {
  return step.actions;
}
