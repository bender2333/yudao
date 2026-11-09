// 原文面板里的「看工作过程」（工单 #1658，项目的组织设计说明 4.14「项目页是循环图加对话」第 4 层、
// 工作过程的任务与动作标题设计说明「动作标记」「动作标题」「任务分组」的最后一条、
// 应用层与接口层设计说明 4.4「项目页四层读哪个查询」的 run.steps 一行）。
//
// 这里只做整理、折叠与时序图一行到激活的对应，不碰界面与网络：视图按这里给出的行、折起来的行、
// 原始数据的几格与每一步的调用尝试编号照画，单元测试直接核对。
//
// 读的事实只有 run.steps 一处：
//   - 每个动作的种类标记（读、写、运行、询问、提交）、一行标题与标题来源由服务端按同一份工具定义算出
//     （工单 #1657），页面不另算一份，所以行上不会出现整段命令；
//   - 只有文字、没有动作的一步由这段文字的开头作一行，没有种类标记，来源记作者；
//   - 原始数据取动作的回执（命令、参数）、event.detail 的输出工件（退出状态、输出）与这一步的推理与
//     模型文字；每一步的调用尝试编号（含被丢弃的）带着进请求详情页；
//   - 一轮没有计划时动作平铺，连续同一种类的动作由页面折成一行（如「读了 12 次」），点开看每一行。
//
// 一条时序图的行或图上的箭头看哪一次激活：成果看产生这一版的职能那一轮（project.flow 的第几轮对
// run.steps 激活的第几轮）；询问与回答看被询问职能那次回答（询问编号对激活的会话编号）——询问分支的
// 激活没有第几轮，所以两条各按各的键找。

import type {
  ActionView,
  ActivationView,
  RunStepView,
  RunStepsResult,
  StepText,
} from "../../api/generated/types.gen";
import { END, SOURCE, type LoopArrow } from "./loop-graph-model.ts";
import { YOU, type SequenceRow } from "./sequence-model.ts";

/** 折起来的那些动作点开以前的那把钥匙：每一组一个，展开状态按它记。 */
const GROUP_SEPARATOR = "+";

// ---------------------------------------------------------------------------
// 一次激活：时序图的一行或图上的箭头对到哪一次

/**
 * 看哪一次激活：`cycle` 按第几轮找（成果），`session` 按会话编号找（询问与回答）。
 *
 * `department` 是这次工作属于哪个职能：`run.steps` 按职能取，页面上还要写出它的显示名。
 */
export type WorkTarget =
  | { kind: "cycle"; department: string; cycle: number }
  | { kind: "session"; department: string; sessionId: string };

/** 一行或一条箭头的两端是不是一个真的职能：图外的来源与结束没有工作过程。 */
function isDepartment(id: string): boolean {
  return id !== "" && id !== SOURCE && id !== END && id !== YOU;
}

/**
 * 时序图的一行到激活的对应。
 *
 * 成果那一行看产生这一版的职能那一轮；询问与回答那一行看被询问职能那次回答（询问编号对激活的会话编号），
 * 还没有回答的询问没有对应的激活。决定、指导与你的输入没有入口。
 */
export function workTargetOfRow(row: SequenceRow): WorkTarget | null {
  if (row.kind === "outcome") {
    if (!isDepartment(row.from) || row.round < 1) {
      return null;
    }
    return { kind: "cycle", department: row.from, cycle: row.round };
  }
  if (row.kind === "ask" || row.kind === "answer") {
    if (row.kind === "ask" && row.open) {
      return null;
    }
    const sessionId = askIdOfRowKey(row.key);
    // 询问那一行问的是被询问的职能，回答那一行说话的是回答的职能；两处都指向同一个会话
    const department = row.kind === "ask" ? row.to[0] : row.from;
    if (sessionId === null || department === undefined || !isDepartment(department)) {
      return null;
    }
    return { kind: "session", department, sessionId };
  }
  return null;
}

/** 图上一条成果箭头到激活的对应：发出这一版的职能那一轮。 */
export function workTargetOfArrow(arrow: LoopArrow): WorkTarget | null {
  if (arrow.round === null || !isDepartment(arrow.from)) {
    return null;
  }
  return { kind: "cycle", department: arrow.from, cycle: arrow.round };
}

/**
 * 询问或回答的那一行说的是哪一次询问：行的身份是 `ask:<询问编号>`（回答那一行多一段 `:answer`）。
 * 不是询问那一行时为空。
 */
export function askIdOfRowKey(key: string): string | null {
  if (!key.startsWith("ask:")) {
    return null;
  }
  const rest = key.slice("ask:".length);
  return rest.endsWith(":answer") ? rest.slice(0, -":answer".length) : rest;
}

/**
 * 与目标对得上的全部激活，按开始时间升序（`run.steps` 给出的顺序）。
 *
 * 同一轮有几次激活时都列出来，页面默认用最后一次。按第几轮找（成果）时要排掉询问分支的激活：
 * 询问分支的会话编号就是 `run.asks` 的询问编号（接口设计说明 4.4 第 4 条），它和主线那一轮记着
 * 同一个第几轮，不排掉就会把「回答一次询问」当成「产生这一版的那一轮」。按会话编号找的（询问与回答）
 * 正好相反：找的就是那一次分支。
 */
export function activationsOf(
  activations: readonly ActivationView[],
  target: WorkTarget,
  branchSessions: readonly string[] = [],
): ActivationView[] {
  if (target.kind === "session") {
    return activations.filter((activation) => activation.session_id === target.sessionId);
  }
  const branches = new Set(branchSessions);
  return activations.filter((activation) => activation.cycle !== null && activation.cycle !== undefined
    && activation.cycle === target.cycle
    && !(activation.session_id !== null && activation.session_id !== undefined
      && branches.has(activation.session_id)));
}

/** 默认看的那一次激活：与目标对得上的最后一次；一次都对不上时为空。 */
export function activationOf(
  activations: readonly ActivationView[],
  target: WorkTarget,
  branchSessions: readonly string[] = [],
): ActivationView | null {
  return activationsOf(activations, target, branchSessions).at(-1) ?? null;
}

/** 入口旁边写的是哪一轮或哪一次回答：页面上认得出看的是哪一次工作。 */
export function targetText(target: WorkTarget): string {
  return target.kind === "cycle" ? `第 ${target.cycle} 轮` : "这次回答";
}

/** 一次都没对上的时候说的一句：不拿最近一次顶替，也不留一块空白。 */
export function noActivationText(target: WorkTarget): string {
  return target.kind === "cycle" ? "没有找到这一轮的工作过程" : "没有找到这次回答的工作过程";
}

// ---------------------------------------------------------------------------
// 行：每个动作一行标记加标题，只有文字的一步一行

/** 一行是哪一种：一个动作，或者只有文字的一步。 */
export type WorkLineKind = "action" | "text";

/**
 * 工作过程里的一行。
 *
 * `mark` 是种类标记（读、写、运行、询问、提交）：只有文字的一步与不认识的工具没有；
 * `facts` 是系统量到的事实（失败、超时、结果未知、被拒绝、改了文件）；
 * `titleSource` 是标题谁写的（系统算的，或角色写的那一句），页面上两种写法分得开。
 * 点开这一行时看的是这一步的推理与模型文字，以及这个动作的命令、参数、退出状态与输出。
 */
export interface WorkLine {
  key: string;
  kind: WorkLineKind;
  mark: string | null;
  facts: string[];
  title: string;
  titleSource: "系统" | "作者" | null;
  /** 这一步的请求时间 */
  at: string;
  /** 第几步；没有归到任何一步的动作（`run.steps` 的 unassigned_actions）为空 */
  stepId: number | null;
  action: ActionView | null;
  reasoning: StepText[];
  texts: StepText[];
  /** 这一步的调用尝试编号，含被丢弃的（每一步都带得回来，工单 #1657） */
  attemptIds: string[];
  /** 其中被丢弃的个数：排在 `attemptIds` 前面的那几个 */
  discardedAttempts: number;
}

/** 一步里的一个动作一行；一步有几个动作就是几行。 */
function lineOf(step: RunStepView, action: ActionView): WorkLine {
  return {
    key: `action:${action.action_id}`,
    kind: "action",
    mark: action.mark ?? null,
    facts: [...(action.facts ?? [])],
    title: action.title ?? "",
    titleSource: action.title_source ?? null,
    at: step.requested_at,
    stepId: step.step_id,
    action,
    reasoning: step.reasoning,
    texts: step.texts,
    attemptIds: step.attempt_ids ?? [],
    discardedAttempts: step.discarded_attempts,
  };
}

/** 只有文字、没有动作的一步：这段文字的开头作一行，没有种类标记，来源记作者。 */
function textLineOf(step: RunStepView): WorkLine {
  return {
    key: `step:${step.step_id}`,
    kind: "text",
    mark: null,
    facts: [],
    title: step.title ?? "",
    titleSource: step.title_source ?? "作者",
    at: step.requested_at,
    stepId: step.step_id,
    action: null,
    reasoning: step.reasoning,
    texts: step.texts,
    attemptIds: step.attempt_ids ?? [],
    discardedAttempts: step.discarded_attempts,
  };
}

/** 没有归到任何一步的动作：只有动作这一行，没有推理与模型文字，也没有尝试编号。 */
function unassignedLineOf(action: ActionView): WorkLine {
  return {
    key: `action:${action.action_id}`,
    kind: "action",
    mark: action.mark ?? null,
    facts: [...(action.facts ?? [])],
    title: action.title ?? "",
    titleSource: action.title_source ?? null,
    at: action.created_at,
    stepId: null,
    action,
    reasoning: [],
    texts: [],
    attemptIds: [],
    discardedAttempts: 0,
  };
}

/**
 * 一次激活的全部行：按步骤的先后，每步的动作各一行；只有文字的一步一行；
 * 没有归到步骤的动作照实列出，排在最后。
 *
 * 一步里有动作时不再单独出一行：那一步的推理与模型文字跟着它的动作行进原始数据。
 */
export function workLines(result: RunStepsResult | null): WorkLine[] {
  if (result === null) {
    return [];
  }
  const out: WorkLine[] = [];
  for (const step of result.steps) {
    if (step.actions.length === 0) {
      if ((step.title ?? "") !== "") {
        out.push(textLineOf(step));
      }
      continue;
    }
    for (const action of step.actions) {
      out.push(lineOf(step, action));
    }
  }
  for (const action of result.unassigned_actions) {
    out.push(unassignedLineOf(action));
  }
  return out;
}

// ---------------------------------------------------------------------------
// 折叠：连续同一种类的动作折成一行

/**
 * 折起来的一组行。
 *
 * 多于一个、而且同一种类连在一起时折成一行，`foldedTitle` 写数量（如「读了 3 次」）；
 * 其余情况 `foldedTitle` 为空，这一组就是那一行本身。
 */
export interface WorkGroup {
  key: string;
  foldedTitle: string;
  lines: WorkLine[];
}

/** 折起来的那一行写的字：五种种类的标记后面跟数量。 */
export function foldedLineText(mark: string, count: number): string {
  return `${mark}了 ${count} 次`;
}

/**
 * 把行按「连续同一种类的动作」折起来。
 *
 * 只有文字的一步不折，没有种类标记的动作（不认识的工具）也不折：数不出「读了几次」时不写那一句。
 */
export function workGroups(lines: readonly WorkLine[]): WorkGroup[] {
  const out: WorkGroup[] = [];
  let run: WorkLine[] = [];
  const flush = (): void => {
    if (run.length === 0) {
      return;
    }
    const mark = run[0].mark;
    out.push({
      key: run.map((line) => line.key).join(GROUP_SEPARATOR),
      foldedTitle: mark !== null && run.length > 1 ? foldedLineText(mark, run.length) : "",
      lines: run,
    });
    run = [];
  };
  for (const line of lines) {
    const current = run[0];
    const continues = current !== undefined && line.kind === "action" && line.mark !== null
      && current.mark === line.mark && current.kind === "action";
    if (!continues) {
      flush();
    }
    run.push(line);
  }
  flush();
  return out;
}

// ---------------------------------------------------------------------------
// 原始数据：命令、参数、退出状态、输出

/** 原始数据的一格：左上角的标签与内容（命令原文、参数、退出状态、输出、回执）。 */
export interface WorkRawField {
  label: string;
  value: string;
}

/** 原始数据的输入：这个动作、它的输出工件（event.detail 的 artifacts.output），以及回执的一行文字。 */
export interface WorkRawInput {
  action: ActionView | null;
  output?: unknown;
  /** 回执的一行文字（action-table 的 actionRow 给的 summaryText） */
  summary?: string;
}

/**
 * 一个动作的原始数据：命令原文、参数、退出状态、输出与回执。
 *
 * 没有的那一项不写（不拿空占位补）：读文件这类动作没有命令与退出状态。参数里去掉命令那一项，
 * 免得同一段命令写两遍；命令本身已经由服务端去掉凭据。
 */
export function rawFields(input: WorkRawInput): WorkRawField[] {
  const action = input.action;
  if (action === null) {
    return [];
  }
  const args: Record<string, unknown> = isRecord(action.receipt?.args) ? { ...action.receipt.args } : {};
  const out: WorkRawField[] = [];
  const command = args["command"];
  if (typeof command === "string" && command !== "") {
    out.push({ label: "命令", value: command });
    delete args["command"];
  }
  if (Object.keys(args).length > 0) {
    out.push({ label: "参数", value: JSON.stringify(args, null, 2) });
  }
  const exitCode = exitCodeOf(input.output);
  if (exitCode !== null) {
    out.push({ label: "退出状态", value: String(exitCode) });
  }
  const text = outputText(input.output);
  if (text !== "") {
    out.push({ label: "输出", value: text });
  }
  const summary = (input.summary ?? "").trim();
  if (summary !== "") {
    out.push({ label: "回执", value: summary });
  }
  return out;
}

/** 输出工件里的退出状态：不是数字时为空（超时是执行层给的 124，照样写出来）。 */
function exitCodeOf(output: unknown): number | null {
  if (!isRecord(output)) {
    return null;
  }
  const value = output["exit_code"];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * 输出工件里的原文：工件本身是字符串时就是它；是对象时先看 `output`、再 `content`、再 `text`；
 * 都没有可读的一段时按 JSON 写出来（搜索、读行范围这类工具的结果），不改写成摘要。
 */
export function outputText(output: unknown): string {
  if (typeof output === "string") {
    return output;
  }
  if (!isRecord(output)) {
    return "";
  }
  for (const key of ["output", "content", "text"]) {
    const value = output[key];
    if (typeof value === "string" && value !== "") {
      return value;
    }
  }
  return JSON.stringify(output, null, 2);
}

// ---------------------------------------------------------------------------
// 每一步的调用尝试编号：被丢弃的也能点

/** 这一步的一次调用尝试：进请求详情页的那一次的编号，以及它是不是被丢弃的那一次。 */
export interface WorkAttempt {
  id: string;
  discarded: boolean;
}

/**
 * 这一步的调用尝试：被丢弃的排在前面（`discarded_attempts` 是它们的个数），后面是留下结果的那一次。
 * 没有编号时为空：老事件只记得被丢弃的次数，不能凭次数编出编号。
 */
export function attemptLinks(line: WorkLine): WorkAttempt[] {
  return line.attemptIds.map((id, index) => ({ id, discarded: index < line.discardedAttempts }));
}

/** 「请求详情」那几个入口上的字：被丢弃的那几次照样能点，写清楚是哪一次。 */
export function attemptLinkText(attempt: WorkAttempt, index: number): string {
  return attempt.discarded ? `请求详情（被丢弃的第 ${index + 1} 次）` : "请求详情";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
