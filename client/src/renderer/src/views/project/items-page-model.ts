// 「事项与用量」页（工单 #1809，docs/design/project-organization.md 4.10）：
//   1. 事项列表：读取 project.overview、project.loop、decisions.list 与（当能力清单包含时）runtime.slots，
//      展示统计条、状态筛选、事项卡片（严格区分「独立核验放行」与「开环完成」、标注「按旧组织跑」、
//      显示当前轮次/职能/耗时与上限/停止原因、提供「在对话与循环图里看」及按需「恢复与动作核实」入口）。
//   2. 槽位占位汇总严格受 capability 门控，不在缺失 runtime.slots 时捏造槽位占用数字。

import type {
  DecisionView,
  ProjectLoopResult,
  ProjectOverviewResult,
  StopDetail,
  WorkItemCard,
  WorkItemLoop,
} from "../../api/generated/types.gen";
import { paths } from "../../shell/routing.ts";
import { boardGroups, type BoardOrganization } from "./board.ts";
import { elapsedLimitText, projectSlotText } from "./floor-text.ts";
import { OPEN_LOOP_PANEL_TEXT, stopReasonText } from "./item-panel-model.ts";
import {
  WORK_ITEM_STATUS_KIND,
  isOpenLoopCompleted,
  stoppedCardLine,
  workItemStatusText,
} from "./labels.ts";
import { departmentLabel, departmentLabels, itemDepartments, type DepartmentLabels, type DepartmentView } from "./organization.ts";

export type ItemsStatusFilter =
  | "all"
  | "in_progress"
  | "waiting_decision"
  | "released"
  | "open_loop"
  | "adopted"
  | "stopped";

export interface ItemsFilterOption {
  key: ItemsStatusFilter;
  label: string;
  count: number;
}

export interface ItemsSummaryStats {
  total: number;
  inProgress: number;
  waitingDecision: number;
  released: number;
  openLoop: number;
  stopped: number;
}

export interface RuntimeSlotsSummary {
  used: number | null;
  total: number | null;
  waiting: number | null;
  text: string;
}

export interface ItemCardView {
  workItemId: string;
  title: string;
  statusText: string;
  statusKind: string;
  openLoop: boolean;
  openLoopNote: string | null;
  verifiedReleased: boolean;
  waitingDecision: boolean;
  oldOrganization: boolean;
  round: number;
  departmentText: string;
  elapsedText: string;
  stoppedIdentity: string;
  stopReasonText: string | null;
  stopNote: string | null;
  stopDetail: StopDetail | null;
  keptDelivery: WorkItemCard["kept_delivery"];
  startError: string | null;
  pendingQuestion: string | null;
  selected: boolean;
  conversationHash: string;
  recoveryHash: string | null;
}

export interface ItemsGroupView {
  key: string;
  title: string;
  count: number;
  cards: ItemCardView[];
}

export interface ItemsListView {
  stats: ItemsSummaryStats;
  filterOptions: ItemsFilterOption[];
  groups: ItemsGroupView[];
  emptyText: string | null;
  loopSlotText: string | null;
  runtimeSlots: RuntimeSlotsSummary | null;
}

export interface ItemsListInput {
  projectId: string;
  selectedWorkItemId: string | null;
  overview: ProjectOverviewResult | null;
  loop: ProjectLoopResult | null;
  decisions?: readonly DecisionView[] | null;
  departments: readonly DepartmentView[];
  filter: ItemsStatusFilter;
  runtimeSlots?: unknown;
  unknownActionsByItem?: Readonly<Record<string, number>>;
}

const UNFINISHED_ITEM_STATUSES: ReadonlySet<string> = new Set([
  "not_started",
  "held",
  "in_progress",
  "awaiting_initial_prd",
]);

const FILTER_LABELS: readonly { key: ItemsStatusFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "in_progress", label: "进行中" },
  { key: "waiting_decision", label: "待你决定" },
  { key: "released", label: "独立核验放行" },
  { key: "open_loop", label: "开环完成" },
  { key: "adopted", label: "已采纳" },
  { key: "stopped", label: "已停止" },
];

export function canQueryRuntimeSlots(
  capabilities: { queries?: readonly { name: string }[] } | null | undefined,
): boolean {
  return Boolean(capabilities?.queries?.some((query) => query.name === "runtime.slots"));
}

function finiteNonNegative(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

export function parseRuntimeSlots(data: unknown): RuntimeSlotsSummary | null {
  if (!data || typeof data !== "object") {
    return null;
  }
  const raw = data as Record<string, unknown>;
  const used = finiteNonNegative(raw.used ?? raw.occupied ?? raw.active_count ?? raw.running ?? raw.running_runs);
  const total = finiteNonNegative(raw.total ?? raw.capacity ?? raw.limit ?? raw.slot_limit);
  const waiting = finiteNonNegative(raw.waiting ?? raw.queued ?? raw.waiting_count);
  if (used === null && total === null && waiting === null) {
    return null;
  }
  const parts: string[] = [];
  if (used !== null && total !== null) {
    parts.push(`已占用 ${used} / ${total}`);
  } else if (used !== null) {
    parts.push(`正在执行 ${used}`);
  } else if (total !== null) {
    parts.push(`槽位总数 ${total}`);
  }
  if (waiting !== null) {
    parts.push(`等槽位 ${waiting}`);
  }
  return { used, total, waiting, text: parts.join(" · ") };
}

export function collectOpenDecisionWorkItemIds(decisions: readonly DecisionView[] | null | undefined): Set<string> {
  const ids = new Set<string>();
  for (const decision of decisions ?? []) {
    if (decision.status === "open" && decision.work_item_id) {
      ids.add(decision.work_item_id);
    }
  }
  return ids;
}

export function isWaitingDecision(
  card: WorkItemCard,
  openDecisionWorkItemIds: ReadonlySet<string> = new Set(),
): boolean {
  if (card.status === "awaiting_initial_prd") {
    return true;
  }
  if ((card.pending_question ?? "").trim() !== "" || (card.human_action ?? "").trim() !== "") {
    return true;
  }
  if (openDecisionWorkItemIds.has(card.work_item_id)) {
    return true;
  }
  return Object.values(card.departments ?? {}).some((dept) => dept.state === "waiting_user");
}

export function matchesStatusFilter(
  card: WorkItemCard,
  filter: ItemsStatusFilter,
  openDecisionWorkItemIds: ReadonlySet<string> = new Set(),
): boolean {
  switch (filter) {
    case "all":
      return true;
    case "in_progress":
      return card.status === "in_progress";
    case "waiting_decision":
      return isWaitingDecision(card, openDecisionWorkItemIds);
    case "released":
      return card.status === "released_unsettled" && !isOpenLoopCompleted(card);
    case "open_loop":
      return isOpenLoopCompleted(card);
    case "adopted":
      return card.status === "adopted";
    case "stopped":
      return card.status === "stopped";
  }
}

export function filterOptionsFor(
  cards: readonly WorkItemCard[],
  openDecisionWorkItemIds: ReadonlySet<string>,
): ItemsFilterOption[] {
  return FILTER_LABELS.map((entry) => ({
    key: entry.key,
    label: entry.label,
    count: cards.filter((card) => matchesStatusFilter(card, entry.key, openDecisionWorkItemIds)).length,
  }));
}

export function summaryStatsFor(
  overview: ProjectOverviewResult,
  openDecisionWorkItemIds: ReadonlySet<string>,
): ItemsSummaryStats {
  const cards = overview.work_items;
  return {
    total: overview.stats.total,
    inProgress: overview.stats.in_progress,
    waitingDecision: cards.filter((card) => isWaitingDecision(card, openDecisionWorkItemIds)).length,
    released: overview.stats.released_unsettled,
    openLoop: overview.stats.open_loop,
    stopped: overview.stats.stopped,
  };
}

function itemLabelsFor(base: DepartmentLabels, loopItem: WorkItemLoop | undefined): DepartmentLabels {
  const roles = loopItem?.organization?.roles;
  if (!roles || roles.length === 0) {
    return base;
  }
  const merged: DepartmentLabels = { ...base };
  for (const role of roles) {
    if (role.id && !(role.id in merged)) {
      merged[role.id] = role.label;
    }
  }
  return merged;
}

function statusKindFor(card: WorkItemCard, openLoop: boolean): string {
  if (openLoop) {
    return "done";
  }
  if (card.status === "stopped") {
    return card.stop_reason === "cancelled" ? "cancelled" : "failed";
  }
  if (card.status === "held") {
    return "held";
  }
  return WORK_ITEM_STATUS_KIND[card.status] ?? "idle";
}

function workingDepartmentsLabel(card: WorkItemCard, labels: DepartmentLabels): string {
  const departments = card.departments ?? null;
  if (departments !== null) {
    const active = Object.keys(departments).filter((dept) => {
      const state = departments[dept];
      return state !== undefined && (state.state === "working" || state.state === "asking");
    });
    if (active.length > 0) {
      return `${active.map((dept) => departmentLabel(dept, labels)).join("、")}在工作`;
    }
  }
  return card.department ? departmentLabel(card.department, labels) : "—";
}

function buildItemCardView(
  card: WorkItemCard,
  projectId: string,
  selectedWorkItemId: string | null,
  loopItem: WorkItemLoop | undefined,
  baseLabels: DepartmentLabels,
  openDecisionWorkItemIds: ReadonlySet<string>,
  unknownActionsByItem: Readonly<Record<string, number>> | undefined,
): ItemCardView {
  const openLoop = isOpenLoopCompleted(card);
  const verifiedReleased = card.status === "released_unsettled" && !openLoop;
  const labels = itemLabelsFor(baseLabels, loopItem);
  const unknownCount = unknownActionsByItem?.[card.work_item_id] ?? 0;
  const needsRecovery =
    loopItem?.recovery_state === "interrupted" ||
    loopItem?.recovery_state === "waiting_resume" ||
    unknownCount > 0;
  const oldOrganization =
    UNFINISHED_ITEM_STATUSES.has(card.status) && loopItem?.organization?.same_as_project === false;

  return {
    workItemId: card.work_item_id,
    title: card.title.trim() === "" ? "未命名事项" : card.title,
    statusText: workItemStatusText(card),
    statusKind: statusKindFor(card, openLoop),
    openLoop,
    openLoopNote: openLoop ? OPEN_LOOP_PANEL_TEXT : null,
    verifiedReleased,
    waitingDecision: isWaitingDecision(card, openDecisionWorkItemIds),
    oldOrganization,
    round: loopItem?.round ?? card.round,
    departmentText: workingDepartmentsLabel(card, labels),
    elapsedText: elapsedLimitText(loopItem ?? null),
    stoppedIdentity: card.status === "stopped" ? stoppedCardLine(card) : "",
    stopReasonText: card.status === "stopped" && card.stop_reason ? stopReasonText(card.stop_reason) : null,
    stopNote: card.stop_note ?? null,
    stopDetail: card.stop_detail ?? null,
    keptDelivery: card.kept_delivery,
    startError: card.start_error ?? null,
    pendingQuestion: card.pending_question ?? null,
    selected: selectedWorkItemId === card.work_item_id,
    conversationHash: paths.conversation(projectId, { workItem: card.work_item_id }),
    recoveryHash: needsRecovery ? paths.recovery(projectId, card.work_item_id) : null,
  };
}

export function itemsListView(input: ItemsListInput): ItemsListView | null {
  if (input.overview === null) {
    return null;
  }
  const cards = input.overview.work_items;
  const openDecisionWorkItemIds = collectOpenDecisionWorkItemIds(input.decisions);
  const loopById = new Map<string, WorkItemLoop>();
  for (const item of input.loop?.work_items ?? []) {
    loopById.set(item.work_item_id, item);
  }
  const baseLabels = departmentLabels(input.departments);
  const filtered = cards.filter((card) =>
    matchesStatusFilter(card, input.filter, openDecisionWorkItemIds),
  );
  const boardOrg: BoardOrganization = {
    departments: input.departments,
    itemDepartments: itemDepartments(input.loop),
  };
  const groups: ItemsGroupView[] = boardGroups(filtered, boardOrg)
    .filter((group) => group.items.length > 0)
    .map((group) => ({
      key: group.key,
      title: group.title,
      count: group.items.length,
      cards: group.items.map((card) =>
        buildItemCardView(
          card,
          input.projectId,
          input.selectedWorkItemId,
          loopById.get(card.work_item_id),
          baseLabels,
          openDecisionWorkItemIds,
          input.unknownActionsByItem,
        ),
      ),
    }));

  const emptyText =
    cards.length === 0
      ? "项目还没有事项"
      : groups.length === 0
        ? "当前筛选下没有事项"
        : null;

  return {
    stats: summaryStatsFor(input.overview, openDecisionWorkItemIds),
    filterOptions: filterOptionsFor(cards, openDecisionWorkItemIds),
    groups,
    emptyText,
    loopSlotText: input.loop ? projectSlotText(input.loop) : null,
    runtimeSlots: parseRuntimeSlots(input.runtimeSlots),
  };
}
