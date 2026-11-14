/**
 * 事项面板的模型（工单 #1708，docs/design/project-organization.md「事项面板与全部事项」）。
 *
 * 面板回答三件事：这件事走到哪、为什么停、接下来能做什么。三样都照查询给的事实写，页面不自己判：
 * 状态、第几轮、已用时间取 project.loop；停止原因与说明取 project.overview；循环停在哪一层、凭什么判取
 * run.loops（行由 floor-text 的 loopRows 给，与观测页同一个口径）；有没有恢复入口取 run.recovery。
 * 这里只把事实翻成页面上的话，不读 React、不读窗口，所以页面的行为可以用单元测试看。
 *
 * 取消与对话上方时间条上的「停止」是同一个动作、同一条命令（work_item.cancel）、同一个基准版本
 * （见 project-head-model.ts 的 timeBar 与 cancel-text.ts），两处的条件在这里对齐。
 */

import type {
  LoopAmount,
  ProjectLoopResult,
  ProjectOverviewResult,
  RunLoopsResult,
  RunRecoveryResult,
  WorkItemCard,
  WorkItemLoop,
} from "../../api/generated/types.gen";
import { type CancelRequest, cancelItemLabel } from "./cancel-text.ts";
import {
  amountText,
  FACT_ELEMENT_LABELS,
  FACT_ELEMENT_ORDER,
  loopRuleText,
  loopRows,
  projectSlotText,
  SOURCE_KIND_LABELS,
  type LoopRow,
} from "./floor-text.ts";
import {
  formatDuration,
  formatTime,
  isOpenLoopCompleted,
  STOP_REASON,
  stopDetailText,
  workItemStatusText,
} from "./labels.ts";

/**
 * 以开环完成结束的事项在面板上的状态那句：没有核验角色，没有人放行过它（设计说明「事项面板与全部事项」）。
 * 与 labels.ts 的 OPEN_LOOP_STATUS_TEXT（「开环完成」）是同一件事的两种写法：面板与选事项一行写全这一句，
 * 别处（看板分组、概览卡片）仍然只写「开环完成」。
 */
export const OPEN_LOOP_PANEL_TEXT = "开环完成：没有人核验";

/**
 * 停止原因清单里页面还缺的那一条（工单 #1708）：清单的正本是 harness/definitions/stop_reasons.json，
 * 页面的文字表在 labels.ts 的 STOP_REASON；这一版清单有 cannot_verify，文字表还没有，而文字表由
 * 别的工单维护（tests/unit/board-columns.test.ts 按 19 条逐项核对）这里不补进那份表，只补这一句，
 * 让清单里每一项在面板上都有一句话。清单加了新的一条时，tests/unit/item-panel-model.test.ts 会失败。
 */
export const EXTRA_STOP_REASON: Readonly<Record<string, string>> = Object.freeze({
  cannot_verify: "质检无法核验，交付未采纳",
});

/**
 * 一个停止原因在页面上的一句话；清单里没有这一条时是空字符串（页面不写机器标识，也不编一句话）。
 * labels.ts 的 label() 在查不到时把机器标识原样返回，这里不用它。
 */
export function stopReasonText(reason: string | null | undefined): string {
  const key = (reason ?? "").trim();
  if (key === "") {
    return "";
  }
  return EXTRA_STOP_REASON[key] ?? STOP_REASON[key] ?? "";
}

/** 选事项一行在状态旁写的那一句：停了的写停止原因，以开环完成结束的写没有人核验。 */
export function pickStatusText(item: { status: string; stop_reason?: string | null }): string {
  if (isOpenLoopCompleted(item)) {
    return OPEN_LOOP_PANEL_TEXT;
  }
  const status = workItemStatusText(item);
  const reason = stopReasonText(item.stop_reason ?? null);
  return reason === "" ? status : `${status} · ${reason}`;
}

/** 一条事实的来源：给出它的事件在事件日志里的位置与这条事件的来源种类。 */
export interface FactSourceView {
  element: string;
  elementLabel: string;
  source: string;
  sourceLabel: string;
  position: number;
}

/** 面板第一段的一行：名目、页面上的一句话、有来源时的来源。 */
export interface PanelFact {
  key: string;
  term: string;
  text: string;
  source: FactSourceView | null;
}

/** 停了的事项那一段：为什么停，以及清单给的下一步。 */
export interface StopBlock {
  /** 停止原因，照清单的说法 */
  reason: string;
  /** 以开环完成结束（没有核验角色，没有人放行） */
  openLoop: boolean;
  /** 停止说明的原文 */
  note: string;
  /** 上游失败的那一句（部门、模型、状态码、能不能重试） */
  detail: string;
  /** 未能开始的原因 */
  startError: string;
  /** 已收下的交付是哪一版 */
  kept: string;
  /** 清单给的下一步 */
  humanAction: string;
}

/** 循环的一层一行：层名、实例、已用量与上限、收敛状态，点开看判定依据。 */
export interface LayerView {
  key: string;
  layer: string;
  layerLabel: string;
  instance: string;
  rounds: string;
  used: string;
  state: string;
  stateLabel: string;
  stopReason: string;
  /** 缺哪条事实，不缺时是空字符串 */
  missing: string;
  /** 这一层的判定依据：用量、停止原因、缺的事实与判定方式 */
  basis: string[];
}

/** 面板的操作：与整个项目页同一批命令。 */
export interface PanelActions {
  /** 恢复与动作核实：只在有中断或结果未知的动作时才有 */
  recovery: { label: string } | null;
  exportLabel: string;
  /** 取消：条件与时间条上的「停止」一样 */
  cancel: CancelRequest | null;
  cancelLabel: string;
}

export interface ItemPanel {
  workItemId: string;
  title: string;
  status: string;
  /** 状态的中文说法，开环完成时是「开环完成：没有人核验」 */
  statusText: string;
  /** 以开环完成结束：状态与停止那一段都写没有人核验 */
  openLoop: boolean;
  head: PanelFact[];
  stop: StopBlock | null;
  layers: LayerView[];
  /** 判定用的规则与轮数（三项冻结值与两个方法常量） */
  ruleText: string;
  /** 用量到上限的那几项 */
  limitLines: string[];
  /** 执行槽位：这件事在等，以及整个项目在等几个 */
  slots: string[];
  actions: PanelActions;
}

export interface ItemPanelFacts {
  workItemId: string;
  /** project.loop 的结果 */
  loop: ProjectLoopResult | null;
  /** project.overview 的结果 */
  overview: ProjectOverviewResult | null;
  /** run.loops 的结果 */
  loops: RunLoopsResult | null;
  /** run.recovery 的结果 */
  recovery: RunRecoveryResult | null;
}

/** 还能取消的状态：与 project-head-model.ts 的 timeBar 同一套。 */
const CANCELABLE: ReadonlySet<string> = new Set(["in_progress", "awaiting_initial_prd"]);

/** 在等执行槽位的状态（排队中、成果已挂起）。 */
const WAITING_SLOT: ReadonlySet<string> = new Set(["not_started", "held"]);

/** 有没有恢复入口的两种观察状态。 */
const INTERRUPTED: ReadonlySet<string> = new Set(["interrupted", "waiting_resume"]);

/** 已用量与上限的三种用量各叫什么、按什么单位写（run.loops 的 layers 只给这三种）。 */
const AMOUNT_LABELS: Readonly<Record<string, string>> = Object.freeze({
  elapsed_ms: "已用时间",
  model_steps: "职能步数",
  activations: "激活次数",
});

const AMOUNT_UNITS: Readonly<Record<string, string>> = Object.freeze({
  elapsed_ms: " 毫秒",
  model_steps: " 步",
  activations: " 次",
});

const EXPORT_LABEL = "导出这次运行";

/**
 * 一个事项的面板。事项不在查询结果里时没有面板（返回 null）：图上画的是别的项目或别的事项时，
 * 页面不拿空面板顶替。
 */
export function itemPanel(facts: ItemPanelFacts): ItemPanel | null {
  const item = (facts.loop?.work_items ?? []).find((row) => row.work_item_id === facts.workItemId) ?? null;
  if (item === null) {
    return null;
  }
  const card = (facts.overview?.work_items ?? []).find((row) => row.work_item_id === facts.workItemId) ?? null;
  const openLoop = isOpenLoopCompleted(item) || (card !== null && isOpenLoopCompleted(card));
  const ruleText = loopRuleText(facts.loops);
  return {
    workItemId: item.work_item_id,
    title: card?.title ?? item.sign,
    status: item.status,
    statusText: statusTextOf(item, openLoop),
    openLoop,
    head: headFacts(item, card, openLoop),
    stop: stopBlock(item, card, openLoop),
    layers: loopRows(facts.loops).map((row) => layerView(row, ruleText)),
    ruleText,
    limitLines: limitLines(item, facts.loops),
    slots: slotLines(item, facts.loop),
    actions: actionsOf(item, facts.recovery),
  };
}

function statusTextOf(item: WorkItemLoop, openLoop: boolean): string {
  return openLoop ? OPEN_LOOP_PANEL_TEXT : workItemStatusText(item);
}

function headFacts(item: WorkItemLoop, card: WorkItemCard | null, openLoop: boolean): PanelFact[] {
  const question = item.pending_question ?? card?.pending_question ?? "";
  return [
    { key: "status", term: "状态", text: statusTextOf(item, openLoop), source: null },
    { key: "round", term: "第几轮", text: `第 ${item.round} 轮`, source: sourceOf(item, "round") },
    { key: "elapsed", term: "已用时间与上限", text: elapsedText(item), source: sourceOf(item, "elapsed") },
    { key: "pending", term: "待你决定的问题", text: question.trim() === "" ? "没有" : question, source: null },
  ];
}

/**
 * 已用时间与上限：照查询给的两个数写。与时间条上那一格（project-head-model.ts 的 timeBar）不同，
 * 结束的事项也照实写——时间条只给正在跑的这段时间计时，面板要看的是这一次运行用了多久。
 */
function elapsedText(item: WorkItemLoop): string {
  if (item.elapsed_sec === null) {
    return "—";
  }
  return `已用 ${formatDuration(item.elapsed_sec)} / 上限 ${formatDuration(item.time_limit_sec)}`;
}

function sourceOf(item: WorkItemLoop, element: string): FactSourceView | null {
  const ref = item.refs?.[element];
  if (ref === undefined) {
    return null;
  }
  return {
    element,
    elementLabel: FACT_ELEMENT_LABELS[element] ?? element,
    source: ref.source,
    sourceLabel: SOURCE_KIND_LABELS[ref.source] ?? ref.source,
    position: ref.position,
  };
}

/**
 * 按全局事件位置查找事项事实来源（工单 #1745）：命中事项的事实引用时返回对应的中文元素名与来源种类名，
 * 未命中或事项为空时返回同一位置的读取目标，元素名与来源种类名为空字符串。
 */
export function sourceAtPosition(item: WorkItemLoop | null, position: number): FactSourceView {
  const refs = item?.refs ?? {};
  const keys = Object.keys(refs);
  const ordered = [
    ...FACT_ELEMENT_ORDER.filter((element) => keys.includes(element)),
    ...keys.filter((element) => !FACT_ELEMENT_ORDER.includes(element)).sort(),
  ];
  for (const element of ordered) {
    const ref = refs[element];
    if (ref !== undefined && ref.position === position) {
      return {
        element,
        elementLabel: FACT_ELEMENT_LABELS[element] ?? element,
        source: ref.source,
        sourceLabel: SOURCE_KIND_LABELS[ref.source] ?? ref.source,
        position: ref.position,
      };
    }
  }
  return {
    element: "",
    elementLabel: "",
    source: "",
    sourceLabel: "",
    position,
  };
}

/** 来源详情区块的标题：包含元素名与来源种类名时一并显示，为空时显示事件位置。 */
export function sourceHeadingText(fact: FactSourceView): string {
  if (fact.elementLabel !== "" && fact.sourceLabel !== "") {
    return `位置 ${fact.position} 上的原始事件（${fact.elementLabel} · 来源：${fact.sourceLabel}）`;
  }
  return `位置 ${fact.position} 上的原始事件`;
}

function stopBlock(item: WorkItemLoop, card: WorkItemCard | null, openLoop: boolean): StopBlock | null {
  const reason = stopReasonText(item.stop_reason ?? card?.stop_reason ?? null);
  if (!openLoop && reason === "" && item.status !== "stopped") {
    return null;
  }
  const kept = card?.kept_delivery ?? null;
  return {
    reason,
    openLoop,
    note: card?.stop_note ?? "",
    detail: stopDetailText(card?.stop_detail ?? null) ?? "",
    startError: card?.start_error ?? "",
    kept: kept === null ? "" : `第 ${kept.version} 版 · ${formatTime(kept.accepted_at)}`,
    humanAction: card?.human_action ?? "",
  };
}

function layerView(row: LoopRow, ruleText: string): LayerView {
  const basis: string[] = [];
  if (row.used !== "") {
    basis.push(`已用量与上限：${row.used}`);
  }
  if (row.stopReason !== "") {
    basis.push(`停止原因：${row.stopReason}`);
  }
  if (row.missing !== "") {
    basis.push(`缺的事实：${row.missing}`);
  }
  if (ruleText !== "") {
    basis.push(`判定方式：${ruleText}`);
  }
  return {
    key: row.key,
    layer: row.layer,
    layerLabel: row.layerLabel,
    instance: row.instance,
    rounds: row.rounds === null ? "—" : `第 ${row.rounds} 轮`,
    used: row.used,
    state: row.state,
    stateLabel: row.stateLabel,
    stopReason: row.stopReason,
    missing: row.missing,
    basis,
  };
}

/**
 * 用量到上限的那几项：事项自己记的已用时间与上限，加上 run.loops 每一层每个用量的数与上限。
 * 不设上限的用量不算到上限；同一个用量在几层各记一次时只写一行（页面读的是一件事，不写重复的话）。
 */
function limitLines(item: WorkItemLoop, loops: RunLoopsResult | null): string[] {
  const lines: string[] = [];
  const seen = new Set<string>();
  if (item.elapsed_sec !== null && item.time_limit_sec > 0 && item.elapsed_sec >= item.time_limit_sec) {
    lines.push(`已用时间：已用 ${formatDuration(item.elapsed_sec)} / 上限 ${formatDuration(item.time_limit_sec)}，到上限`);
    seen.add("elapsed_ms");
  }
  for (const layer of loops?.layers ?? []) {
    for (const [name, value] of Object.entries(layer.amounts ?? {})) {
      if (seen.has(name) || atLimit(value) === false) {
        continue;
      }
      lines.push(amountLimitLine(name, value));
      seen.add(name);
    }
  }
  return lines;
}

function atLimit(value: LoopAmount): boolean {
  if (value.unlimited) {
    return false;
  }
  return value.limit > 0 && value.used >= value.limit;
}

function amountLimitLine(name: string, value: LoopAmount): string {
  const caption = AMOUNT_LABELS[name] ?? name;
  if (name === "elapsed_ms") {
    return `${caption}：已用 ${formatDuration(Math.round(value.used / 1000))} / 上限 ${formatDuration(Math.round(value.limit / 1000))}，到上限`;
  }
  return `${caption}：${amountText(value, AMOUNT_UNITS[name] ?? "")}，到上限`;
}

function slotLines(item: WorkItemLoop, loop: ProjectLoopResult | null): string[] {
  const lines: string[] = [];
  if (WAITING_SLOT.has(item.status)) {
    lines.push(`这件事项在等执行槽位（${workItemStatusText(item)}）`);
  }
  const project = projectSlotText(loop);
  if (project !== "") {
    lines.push(project);
  }
  return lines;
}

function actionsOf(item: WorkItemLoop, recovery: RunRecoveryResult | null): PanelActions {
  const cancel: CancelRequest | null = CANCELABLE.has(item.status)
    ? { work_item_id: item.work_item_id, base_version: item.version, status: item.status }
    : null;
  const unknown = recovery?.unknown_actions?.length ?? 0;
  const interrupted = INTERRUPTED.has(recovery?.state ?? "") || INTERRUPTED.has(item.recovery_state ?? "");
  const entry = !interrupted && unknown === 0
    ? null
    : { label: unknown === 0 ? "恢复与动作核实" : `恢复与动作核实（有 ${unknown} 个结果未知的动作）` };
  return {
    recovery: entry,
    exportLabel: EXPORT_LABEL,
    cancel,
    cancelLabel: cancelItemLabel(item.status),
  };
}
