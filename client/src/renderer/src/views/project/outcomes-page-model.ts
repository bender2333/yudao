// 「成果库」一级标签页的纯视图模型（工单 #1810）
// 把 project.overview、project.loop、project.flow 与按需加载的 work_item.materials、acceptance.coverage、
// event.detail、run.trials、run.actions 整理为跨版本成果卡片、计数、筛选与展开详情。

import type {
  AcceptanceCoverageResult,
  EventDetailResult,
  FlowRecord,
  LaunchMethodView,
  ProjectFlowResult,
  ProjectLoopResult,
  ProjectOverviewResult,
  ReviewEntry,
  WorkItemCard,
  WorkItemLoop,
  WorkItemMaterialsResult,
  WorkItemOrganization,
} from "../../api/generated/types.gen.ts";
import { paths } from "../../shell/routing.ts";
import {
  MISSING_REVIEW_TEXT,
  NO_FILES_TEXT,
  OPEN_ENDED_TEXT,
  arrowPanelView,
  citedCasesOf,
  conclusionOf,
  diffFiles,
  openEndedOf,
  roundsView,
  versionOf,
  type CitedCasesView,
  type ConclusionView,
  type FileDiffView,
  type MaterialsLike,
  type PrdView,
  type RoundView,
  type VersionView,
} from "./arrow-panel-model.ts";
import {
  formatTime,
  isOpenLoopCompleted,
  workItemStatusText,
} from "./labels.ts";
import {
  arrowsOf,
  versionsOf,
  type FlowRecordLike,
  type FrozenOrganization,
  type LoopArrow,
  type LoopItemView,
} from "./loop-graph-model.ts";
import {
  departmentLabel,
  departmentLabels,
  type DepartmentView,
} from "./organization.ts";
import type { TrialsView } from "./trials.tsx";

export type OutcomeCategory = "all" | "final" | "mid";
export type OutcomeKind = "delivery" | "prd" | "defect" | "onboarding";

export interface OutcomeCategoryTab {
  id: OutcomeCategory;
  label: string;
  count: number;
}

export interface OutcomeVerdictBadge {
  kind: "release" | "open" | "reject" | "defect" | "flow";
  text: string;
  by: string;
}

export interface OutcomeCounts {
  total: number;
  final: number;
  mid: number;
  released: number;
  openLoop: number;
  rejected: number;
}

export interface OutcomeScopeOption {
  workItemId: string;
  title: string;
  count: number;
  colorIndex: number;
}

export interface DiffLineView {
  kind: "add" | "del" | "hunk" | "meta" | "context";
  text: string;
}

export interface OutcomeEntry {
  id: string;
  kind: OutcomeKind;
  kindLabel: string;
  version: number | null;
  round: number | null;
  workItemId: string;
  workItemTitle: string;
  workItemKind: string;
  workItemStatus: string;
  workItemColorIndex: number;
  runId: string;
  flowId: string | null;
  eventId: string | null;
  position: number;
  createdAt: string;
  timeText: string;
  fromLabel: string;
  toLabel: string;
  directionText: string;
  verdictBadge: OutcomeVerdictBadge;
  summary: string;
  files: string[];
  expectsFiles: boolean;
  isFinal: boolean;
  isOpenLoop: boolean;
  needsReviewDetails: boolean;
  locateHash: string;
  arrow: LoopArrow | null;
  hasOnboardingRounds: boolean;
  rejectIndex: number | null;
  allWorkItemFlows: FlowRecordLike[];
  workItemLoopView: LoopItemView;
  frozenOrganization: FrozenOrganization;
  receiverDepartment: string;
}

export interface OutcomesPageInput {
  projectId: string;
  overview: ProjectOverviewResult | null;
  loop: ProjectLoopResult | null;
  flow: ProjectFlowResult | null;
  departments: readonly DepartmentView[];
  materialsByWorkItem?: Readonly<Record<string, WorkItemMaterialsResult | null | undefined>>;
  workItemId?: string | null;
  category?: OutcomeCategory;
}

export interface OutcomesPageView {
  projectCounts: OutcomeCounts;
  scopedCounts: OutcomeCounts;
  categories: OutcomeCategoryTab[];
  scopeOptions: OutcomeScopeOption[];
  entries: OutcomeEntry[];
  allEntries: OutcomeEntry[];
  hasFilteredScope: boolean;
  selectedWorkItemTitle: string | null;
}

export interface OutcomeDetailInput {
  entry: OutcomeEntry;
  materials: WorkItemMaterialsResult | null;
  coverage: AcceptanceCoverageResult | null;
  trials: TrialsView | null;
  eventDetail: EventDetailResult | null;
  departments: readonly DepartmentView[];
}

export interface OnboardingRoundDetailView extends RoundView {
  overview: string;
  baselineReviewNote: string | null;
}

export interface OutcomeCardDetailView {
  kind: OutcomeKind;
  versionView: VersionView | null;
  prd: PrdView | null;
  rounds: OnboardingRoundDetailView[];
  launch: LaunchMethodView[];
  conclusion: ConclusionView | null;
  review: ReviewEntry | null;
  openEnded: string | null;
  fileDiff: FileDiffView | null;
  gitDiffLines: DiffLineView[];
  citedCases: CitedCasesView;
  defectText: string | null;
  missingReviewText: string | null;
}

const EMPTY_ORG: FrozenOrganization = {
  form: "",
  routing: "",
  roles: [],
  verifiers: [],
  completing: null,
  watched: [],
  asks: [],
};

const PRD_VERSION_RE = /第\s*(\d+)\s*版/;

function toFrozenOrg(org: WorkItemOrganization | null | undefined): FrozenOrganization {
  if (org == null) {
    return EMPTY_ORG;
  }
  return org;
}

function mainReceiverOf(org: FrozenOrganization): string {
  const roles = org.roles ?? [];
  const primary = roles.find((r) => !r.id.startsWith("verify")) ?? roles[0];
  return primary?.id ?? "";
}

function verifierLabelsOf(org: FrozenOrganization, labels: Record<string, string>): string {
  const names = (org.verifiers ?? []).map((v) => departmentLabel(v.role, labels));
  return names.join("、");
}

function isItemOpenLoop(
  item: { status: string; stop_reason?: string | null; progress?: { conclusion?: string | null } | null },
  hasVerifiers: boolean,
): boolean {
  if (isOpenLoopCompleted({ status: item.status, stop_reason: item.stop_reason ?? null })) {
    return true;
  }
  if (hasVerifiers) {
    return false;
  }
  if (item.progress?.conclusion === "release") {
    return false;
  }
  return item.stop_reason === "open_loop" || item.status === "released_unsettled" || item.status === "adopted";
}

function parseTimestamp(value: string | null | undefined): number {
  if (!value) {
    return Number.NaN;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? Number.NaN : parsed;
}

function compareEntriesDesc(a: OutcomeEntry, b: OutcomeEntry): number {
  const ta = parseTimestamp(a.createdAt);
  const tb = parseTimestamp(b.createdAt);
  const aValid = !Number.isNaN(ta);
  const bValid = !Number.isNaN(tb);
  if (aValid && bValid && ta !== tb) {
    return tb - ta;
  }
  if (aValid !== bValid) {
    return bValid ? 1 : -1;
  }
  if (a.position !== b.position) {
    return b.position - a.position;
  }
  return a.id.localeCompare(b.id);
}

function parsePrdVersionFromText(text: string): number | null {
  const match = PRD_VERSION_RE.exec(text);
  if (!match) {
    return null;
  }
  const parsed = Number.parseInt(match[1], 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function countEntries(entries: readonly OutcomeEntry[]): OutcomeCounts {
  let final = 0;
  let mid = 0;
  let released = 0;
  let openLoop = 0;
  let rejected = 0;
  for (const entry of entries) {
    if (entry.isFinal) {
      final += 1;
    } else {
      mid += 1;
    }
    if (entry.verdictBadge.kind === "release") {
      released += 1;
    } else if (entry.verdictBadge.kind === "open") {
      openLoop += 1;
    } else if (entry.verdictBadge.kind === "reject") {
      rejected += 1;
    }
  }
  return {
    total: entries.length,
    final,
    mid,
    released,
    openLoop,
    rejected,
  };
}

function kindLabelOf(kind: OutcomeKind, version: number | null): string {
  if (kind === "onboarding") {
    return "建档初始 PRD";
  }
  const base = kind === "delivery" ? "交付" : kind === "prd" ? "PRD" : "缺陷记录";
  return version != null ? `${base} v${version}` : base;
}

function toMaterialsLike(materials: WorkItemMaterialsResult | null | undefined): MaterialsLike | null {
  if (materials == null) {
    return null;
  }
  return materials as unknown as MaterialsLike;
}

/** 解析 git unified diff 字符串为逐行着色视图。 */
export function parseGitDiffLines(diffText: string | null | undefined): DiffLineView[] {
  if (!diffText) {
    return [];
  }
  const trimmed = diffText.replace(/\r\n/g, "\n").trimEnd();
  if (trimmed === "") {
    return [];
  }
  const rawLines = trimmed.split("\n");
  const lines: DiffLineView[] = [];
  for (const line of rawLines) {
    if (line.startsWith("@@")) {
      lines.push({ kind: "hunk", text: line });
    } else if (
      line.startsWith("diff --git") ||
      line.startsWith("index ") ||
      line.startsWith("--- ") ||
      line.startsWith("+++ ") ||
      line.startsWith("new file mode") ||
      line.startsWith("deleted file mode")
    ) {
      lines.push({ kind: "meta", text: line });
    } else if (line.startsWith("+")) {
      lines.push({ kind: "add", text: line });
    } else if (line.startsWith("-")) {
      lines.push({ kind: "del", text: line });
    } else {
      lines.push({ kind: "context", text: line });
    }
  }
  return lines;
}

function extractGitDiff(detail: EventDetailResult | null | undefined): string | null {
  const raw = detail?.artifacts?.git_version;
  if (raw == null || typeof raw !== "object") {
    return null;
  }
  const diff = (raw as { diff?: unknown }).diff;
  return typeof diff === "string" && diff.trim() !== "" ? diff : null;
}

/** 将项目概览、循环、流动与已加载资料整理为「成果库」页模型。 */
export function outcomesPageView(input: OutcomesPageInput): OutcomesPageView {
  const labels = departmentLabels(input.departments);
  const overviewCards = new Map<string, WorkItemCard>();
  for (const card of input.overview?.work_items ?? []) {
    overviewCards.set(card.work_item_id, card);
  }
  const loopItems = new Map<string, WorkItemLoop>();
  for (const item of input.loop?.work_items ?? []) {
    loopItems.set(item.work_item_id, item);
  }
  const flowsByItem = new Map<string, FlowRecord[]>();
  for (const rec of input.flow?.records ?? []) {
    if (!rec.work_item_id) {
      continue;
    }
    const list = flowsByItem.get(rec.work_item_id) ?? [];
    list.push(rec);
    flowsByItem.set(rec.work_item_id, list);
  }
  // 汇总全部出现过的事项编号（保持顺序：先概览，再循环，再流动记录）
  const allWorkItemIds: string[] = [];
  const seenWorkItemIds = new Set<string>();
  const pushItemId = (id: string) => {
    if (!seenWorkItemIds.has(id)) {
      seenWorkItemIds.add(id);
      allWorkItemIds.push(id);
    }
  };
  for (const card of input.overview?.work_items ?? []) {
    pushItemId(card.work_item_id);
  }
  for (const item of input.loop?.work_items ?? []) {
    pushItemId(item.work_item_id);
  }
  for (const id of flowsByItem.keys()) {
    pushItemId(id);
  }

  const allEntries: OutcomeEntry[] = [];
  const scopeCountsByItem = new Map<string, number>();

  for (const workItemId of allWorkItemIds) {
    const ov = overviewCards.get(workItemId);
    const lp = loopItems.get(workItemId);
    const itemTitle = ov?.title || lp?.sign || "未命名事项";
    const itemKind = lp?.kind ?? ov?.kind ?? "feature";
    const itemStatus = lp?.status ?? ov?.status ?? "";
    const stopReason = lp?.stop_reason ?? ov?.stop_reason ?? null;
    const colorIndex = lp?.color_index ?? 0;
    const defaultRunId = lp?.run_id || ov?.run_id || "";
    const frozenOrg = toFrozenOrg(lp?.organization);
    const hasVerifiers = (frozenOrg.verifiers?.length ?? 0) > 0;
    const verifierNames = verifierLabelsOf(frozenOrg, labels);
    const receiver = mainReceiverOf(frozenOrg);

    const loopView: LoopItemView = {
      work_item_id: workItemId,
      kind: itemKind,
      status: itemStatus,
      stop_reason: stopReason,
      round: lp?.round ?? ov?.round ?? 0,
      department: lp?.department ?? null,
      progress: lp?.progress ?? null,
      organization: frozenOrg,
    };

    const rawFlows = [...(flowsByItem.get(workItemId) ?? [])].sort((a, b) => a.position - b.position);
    const flowByKey = new Map<string, FlowRecord>();
    for (const rec of rawFlows) {
      flowByKey.set(rec.flow_id, rec);
    }

    const materials = input.materialsByWorkItem?.[workItemId] ?? null;
    const arrows = arrowsOf(
      loopView,
      frozenOrg,
      rawFlows,
      materials,
      labels,
      receiver,
    );

    // 针对直接交稿带核验模式中仅写回 progress.conclusion = "rework" 或 reviews.rework 的情形，
    // 在最后一条尚未挂结论的交付箭头上补齐打回结论。
    const reviews = materials?.reviews ?? [];
    const lastReview = reviews.length > 0 ? reviews[reviews.length - 1] : undefined;
    const isReworkConclusion =
      hasVerifiers &&
      (lp?.progress?.conclusion === "rework" ||
        (lp?.progress?.conclusion == null &&
          (lastReview?.verdict === "rework" || lastReview?.verdict === "rework_engineering")));
    if (isReworkConclusion) {
      const target = [...arrows].reverse().find((a) => a.outcome === "交付" && a.verdict === null);
      if (target !== undefined) {
        const by = verifierNames || "核验";
        target.verdict = { tone: "reject", by, text: `${by}打回` };
      }
    }

    // 识别该事项是否属于开环完成，并且标记最后一条未核验交付箭头
    const itemOpenLoop = isItemOpenLoop({ status: itemStatus, stop_reason: stopReason, progress: lp?.progress }, hasVerifiers);
    const deliveryArrows = arrows.filter((a) => a.outcome === "交付");
    const lastDeliveryKey = deliveryArrows.length > 0 ? deliveryArrows[deliveryArrows.length - 1].key : null;

    // PRD 新版本在事件流里会按关注方产生多条同 event_id 记录，按 event_id 合并为一张 PRD 卡片
    const outcomeArrows = arrows.filter(
      (a) => a.outcome === "PRD" || a.outcome === "交付" || a.outcome === "缺陷记录",
    );
    const prdGroups = new Map<
      string,
      { primary: LoopArrow; targets: string[]; primaryIsVerifier: boolean }
    >();
    const verifierRoleSet = new Set((frozenOrg.verifiers ?? []).map((v) => v.role));
    const mergedArrows: Array<{ arrow: LoopArrow; mergedTargets: string[] | null }> = [];

    for (const arrow of outcomeArrows) {
      if (arrow.outcome !== "PRD") {
        mergedArrows.push({ arrow, mergedTargets: null });
        continue;
      }
      const groupKey = arrow.eventId ? `prd:${arrow.eventId}` : `prd-key:${arrow.key}`;
      const existing = prdGroups.get(groupKey);
      const targetName = arrow.to ? departmentLabel(arrow.to, labels) : "";
      const rec = flowByKey.get(arrow.key);
      const isVerifierTarget = verifierRoleSet.has(rec?.direction_to ?? "");
      if (!existing) {
        const group = {
          primary: arrow,
          targets: targetName ? [targetName] : [],
          primaryIsVerifier: isVerifierTarget,
        };
        prdGroups.set(groupKey, group);
        mergedArrows.push({ arrow, mergedTargets: group.targets });
      } else {
        if (targetName && !existing.targets.includes(targetName)) {
          existing.targets.push(targetName);
        }
        // 优先把定位箭头指向核心交付（非核验）接收方，保持与循环图主线一致
        if (existing.primaryIsVerifier && !isVerifierTarget) {
          const idx = mergedArrows.findIndex((m) => m.arrow === existing.primary);
          existing.primary = arrow;
          existing.primaryIsVerifier = false;
          if (idx >= 0) {
            mergedArrows[idx].arrow = arrow;
          }
        }
      }
    }

    let prdSeq = 0;
    let deliverySeq = 0;
    let rejectDeliveryCount = 0;
    let defectSeq = 0;
    let hasPrdForItem = false;

    for (const { arrow, mergedTargets } of mergedArrows) {
      const rec = flowByKey.get(arrow.key);
      const kind: OutcomeKind =
        arrow.outcome === "交付" ? "delivery" : arrow.outcome === "PRD" ? "prd" : "defect";
      if (kind === "prd") {
        hasPrdForItem = true;
      }

      let version = arrow.version;
      if (kind === "prd") {
        prdSeq += 1;
        version = version ?? parsePrdVersionFromText(arrow.text) ?? prdSeq;
      } else if (kind === "delivery") {
        deliverySeq += 1;
        version = version ?? deliverySeq;
      }

      const fromLabel = arrow.from ? departmentLabel(arrow.from, labels) : "";
      const toLabel =
        mergedTargets && mergedTargets.length > 0
          ? mergedTargets.join("、")
          : arrow.to
            ? departmentLabel(arrow.to, labels)
            : "";
      const directionText = fromLabel && toLabel ? `${fromLabel} → ${toLabel}` : fromLabel || toLabel;

      const isFinal = kind === "delivery";
      const openLoopOnThisDelivery =
        isFinal &&
        itemOpenLoop &&
        arrow.verdict === null &&
        (arrow.key === lastDeliveryKey || !hasVerifiers);

      let verdictBadge: OutcomeVerdictBadge;
      let rejectIndex: number | null = null;
      if (arrow.verdict?.tone === "release") {
        verdictBadge = {
          kind: "release",
          text: arrow.verdict.by ? `✓ ${arrow.verdict.by}放行` : "✓ 独立放行",
          by: arrow.verdict.by,
        };
      } else if (arrow.verdict?.tone === "reject") {
        if (kind === "delivery") {
          rejectIndex = rejectDeliveryCount;
          rejectDeliveryCount += 1;
        } else if (kind === "defect") {
          rejectIndex = defectSeq;
          defectSeq += 1;
        }
        verdictBadge = {
          kind: "reject",
          text: arrow.verdict.by ? `✕ ${arrow.verdict.by}打回` : "✕ 打回",
          by: arrow.verdict.by,
        };
      } else if (openLoopOnThisDelivery) {
        verdictBadge = {
          kind: "open",
          text: `◌ ${OPEN_ENDED_TEXT}`,
          by: "",
        };
      } else if (kind === "defect") {
        rejectIndex = defectSeq;
        defectSeq += 1;
        verdictBadge = {
          kind: "defect",
          text: directionText || "问题反馈",
          by: fromLabel,
        };
      } else {
        verdictBadge = {
          kind: "flow",
          text: directionText || kindLabelOf(kind, version),
          by: fromLabel,
        };
      }

      const runId = rec?.run_id || defaultRunId;
      const createdAt = rec?.created_at ?? "";
      const isReviewed = verdictBadge.kind === "release" || verdictBadge.kind === "reject";

      const entry: OutcomeEntry = {
        id: `${workItemId}:${arrow.key}`,
        kind,
        kindLabel: kindLabelOf(kind, version),
        version,
        round: arrow.round ?? rec?.round ?? null,
        workItemId,
        workItemTitle: itemTitle,
        workItemKind: itemKind,
        workItemStatus: itemStatus,
        workItemColorIndex: colorIndex,
        runId,
        flowId: arrow.key,
        eventId: arrow.eventId ?? rec?.event_id ?? null,
        position: arrow.position,
        createdAt,
        timeText: formatTime(createdAt),
        fromLabel,
        toLabel,
        directionText,
        verdictBadge,
        summary: arrow.text || rec?.content || "",
        files: isFinal ? [...arrow.files] : [],
        expectsFiles: isFinal,
        isFinal,
        isOpenLoop: openLoopOnThisDelivery,
        needsReviewDetails: isReviewed || kind === "defect",
        locateHash: paths.conversation(input.projectId, { workItem: workItemId, arrow: arrow.key }),
        arrow,
        hasOnboardingRounds: itemKind === "onboarding",
        rejectIndex,
        allWorkItemFlows: rawFlows,
        workItemLoopView: loopView,
        frozenOrganization: frozenOrg,
        receiverDepartment: receiver,
      };
      allEntries.push(entry);
      scopeCountsByItem.set(workItemId, (scopeCountsByItem.get(workItemId) ?? 0) + 1);
    }

    // 建档事项尚未产生 PRD 新版本流动记录、但已有建档提案或已进入提案阶段时，补一张「建档初始 PRD」卡片
    const onboardingRounds = materials?.onboarding_rounds ?? [];
    const shouldAddOnboardingCard =
      itemKind === "onboarding" &&
      !hasPrdForItem &&
      (onboardingRounds.length > 0 || (materials === null && itemStatus !== "not_started"));
    if (shouldAddOnboardingCard) {
      const latestRound = onboardingRounds.length > 0 ? onboardingRounds[onboardingRounds.length - 1] : null;
      const createdAt = latestRound?.proposed_at ?? ov?.created_at ?? "";
      const summary =
        latestRound?.prd?.trim() ||
        ov?.text?.trim() ||
        workItemStatusText({ status: itemStatus, stop_reason: stopReason });
      const onboardingEntry: OutcomeEntry = {
        id: `onboarding:${workItemId}`,
        kind: "onboarding",
        kindLabel: "建档初始 PRD",
        version: latestRound?.round ?? null,
        round: latestRound?.round ?? (lp?.round || null),
        workItemId,
        workItemTitle: itemTitle,
        workItemKind: itemKind,
        workItemStatus: itemStatus,
        workItemColorIndex: colorIndex,
        runId: latestRound?.run_id || defaultRunId,
        flowId: null,
        eventId: latestRound?.candidate_event_id ?? null,
        position: 0,
        createdAt,
        timeText: formatTime(createdAt),
        fromLabel: receiver ? departmentLabel(receiver, labels) : "建档",
        toLabel: verifierNames || "",
        directionText: "建档初始提案",
        verdictBadge: { kind: "flow", text: "建档提案", by: "" },
        summary,
        files: [],
        expectsFiles: false,
        isFinal: false,
        isOpenLoop: false,
        needsReviewDetails: false,
        locateHash: paths.conversation(input.projectId, { workItem: workItemId }),
        arrow: null,
        hasOnboardingRounds: true,
        rejectIndex: null,
        allWorkItemFlows: rawFlows,
        workItemLoopView: loopView,
        frozenOrganization: frozenOrg,
        receiverDepartment: receiver,
      };
      allEntries.push(onboardingEntry);
      scopeCountsByItem.set(workItemId, (scopeCountsByItem.get(workItemId) ?? 0) + 1);
    }
  }

  allEntries.sort(compareEntriesDesc);

  const requestedWorkItemId = input.workItemId?.trim() || null;
  const scopedEntries =
    requestedWorkItemId !== null
      ? allEntries.filter((entry) => entry.workItemId === requestedWorkItemId)
      : allEntries;

  const projectCounts = countEntries(allEntries);
  const scopedCounts = countEntries(scopedEntries);
  const category = input.category ?? "all";
  const entries =
    category === "final"
      ? scopedEntries.filter((e) => e.isFinal)
      : category === "mid"
        ? scopedEntries.filter((e) => !e.isFinal)
        : scopedEntries;

  const categories: OutcomeCategoryTab[] = [
    { id: "all", label: "全部", count: scopedCounts.total },
    { id: "final", label: "交付与终态", count: scopedCounts.final },
    { id: "mid", label: "PRD 与缺陷记录", count: scopedCounts.mid },
  ];

  const scopeOptions: OutcomeScopeOption[] = allWorkItemIds.map((workItemId) => {
    const ov = overviewCards.get(workItemId);
    const lp = loopItems.get(workItemId);
    return {
      workItemId,
      title: ov?.title || lp?.sign || "未命名事项",
      count: scopeCountsByItem.get(workItemId) ?? 0,
      colorIndex: lp?.color_index ?? 0,
    };
  });

  const selectedWorkItemTitle =
    requestedWorkItemId !== null
      ? scopeOptions.find((o) => o.workItemId === requestedWorkItemId)?.title ?? null
      : null;

  return {
    projectCounts,
    scopedCounts,
    categories,
    scopeOptions,
    entries,
    allEntries,
    hasFilteredScope: requestedWorkItemId !== null,
    selectedWorkItemTitle,
  };
}

function selectReviewForEntry(entry: OutcomeEntry, materials: MaterialsLike | null): ReviewEntry | null {
  const reviews = (materials?.reviews ?? []) as unknown as ReviewEntry[];
  if (reviews.length === 0) {
    return null;
  }
  if (entry.verdictBadge.kind === "release") {
    for (let i = reviews.length - 1; i >= 0; i -= 1) {
      if (reviews[i].verdict === "release") {
        return reviews[i];
      }
    }
    return null;
  }
  if (entry.verdictBadge.kind === "reject" || entry.kind === "defect") {
    const rejects = reviews.filter((r) => r.verdict !== "release" && r.verdict !== "open_loop");
    if (rejects.length === 0) {
      return null;
    }
    if (entry.rejectIndex !== null && entry.rejectIndex >= 0 && entry.rejectIndex < rejects.length) {
      return rejects[entry.rejectIndex];
    }
    return rejects[rejects.length - 1];
  }
  return null;
}

/** 为展开中的成果卡片生成完整详情（版本、PRD 各节、建档各轮、文件与行级差异、核验结论、试用证据）。 */
export function outcomeCardDetail(input: OutcomeDetailInput): OutcomeCardDetailView {
  const { entry, materials, coverage, trials, eventDetail } = input;
  const matLike = toMaterialsLike(materials);
  const labels = departmentLabels(input.departments);

  // 用新加载的 materials 重新构造这一事项的箭头集合，以获得文件清单、摘要与结构化 PRD 绑定
  const arrows = arrowsOf(
    entry.workItemLoopView,
    entry.frozenOrganization,
    entry.allWorkItemFlows,
    materials,
    labels,
    entry.receiverDepartment,
  );

  // 针对只有 progress.conclusion 或 reviews 写回打回时的兜底结论同步
  const hasVerifiers = (entry.frozenOrganization.verifiers?.length ?? 0) > 0;
  const reviews = materials?.reviews ?? [];
  const lastReview = reviews.length > 0 ? reviews[reviews.length - 1] : undefined;
  const isReworkConclusion =
    hasVerifiers &&
    (entry.workItemLoopView.progress?.conclusion === "rework" ||
      (entry.workItemLoopView.progress?.conclusion == null &&
        (lastReview?.verdict === "rework" || lastReview?.verdict === "rework_engineering")));
  if (isReworkConclusion) {
    const target = [...arrows].reverse().find((a) => a.outcome === "交付" && a.verdict === null);
    if (target !== undefined) {
      const by = verifierLabelsOf(entry.frozenOrganization, labels) || "核验";
      target.verdict = { tone: "reject", by, text: `${by}打回` };
    }
  }

  const matchedArrow =
    entry.flowId !== null
      ? arrows.find((a) => a.key === entry.flowId) ?? entry.arrow
      : entry.arrow;

  const versions = matchedArrow !== null ? versionsOf(arrows, matchedArrow) : [];
  const rawOnboardingRounds = materials?.onboarding_rounds ?? [];
  const rounds: OnboardingRoundDetailView[] = entry.hasOnboardingRounds
    ? roundsView(matLike).map((r) => {
        const raw = rawOnboardingRounds.find((item) => item.round === r.round && item.run_id === r.runId) ??
          rawOnboardingRounds.find((item) => item.round === r.round);
        return {
          ...r,
          overview: raw?.overview ?? "",
          baselineReviewNote: raw?.baseline_review_note ?? null,
        };
      })
    : [];

  if (entry.kind === "onboarding") {
    const fallbackContract = (matLike?.contracts ?? []).at(-1);
    const prdFallbackArrow: LoopArrow | null =
      fallbackContract != null
        ? {
            key: `onboarding-prd:${entry.workItemId}`,
            outcome: "PRD",
            version: fallbackContract.prd?.spec_revision ?? null,
            round: entry.round,
            from: entry.receiverDepartment,
            to: "",
            back: false,
            position: 0,
            verdict: null,
            text: "",
            files: [],
            eventId: fallbackContract.event_id,
          }
        : null;
    const prdView = prdFallbackArrow ? versionOf(prdFallbackArrow, [prdFallbackArrow], matLike).prd : null;
    return {
      kind: entry.kind,
      versionView: null,
      prd: prdView,
      rounds,
      launch: [],
      conclusion: null,
      review: null,
      openEnded: null,
      fileDiff: null,
      gitDiffLines: [],
      citedCases: { rows: [], missing: [] },
      defectText: null,
      missingReviewText: null,
    };
  }

  if (entry.kind === "prd") {
    const versionView = matchedArrow !== null ? versionOf(matchedArrow, versions, matLike) : null;
    return {
      kind: entry.kind,
      versionView,
      prd: versionView?.prd ?? null,
      rounds,
      launch: [],
      conclusion: null,
      review: null,
      openEnded: null,
      fileDiff: null,
      gitDiffLines: [],
      citedCases: { rows: [], missing: [] },
      defectText: null,
      missingReviewText: null,
    };
  }

  if (entry.kind === "delivery") {
    const versionView = matchedArrow !== null ? versionOf(matchedArrow, versions, matLike) : null;
    const gitDiffLines = parseGitDiffLines(extractGitDiff(eventDetail));
    const idxInVersions = matchedArrow !== null ? versions.findIndex((v) => v.key === matchedArrow.key) : -1;
    const prevFiles = idxInVersions > 0 ? versions[idxInVersions - 1].files : null;
    const currentFiles = versionView?.files ?? matchedArrow?.files ?? entry.files;
    const fileDiff = versionView?.diff ?? diffFiles(currentFiles, prevFiles);
    const matchedDelivery =
      entry.eventId != null
        ? (materials?.deliveries ?? []).find((d) => d.event_id === entry.eventId)
        : undefined;
    const launch = matchedDelivery?.launch ?? [];

    if (entry.isOpenLoop) {
      const openEnded =
        matchedArrow !== null
          ? openEndedOf({
              arrow: matchedArrow,
              versions,
              verifier: hasVerifiers,
              ended: workItemStatusText({
                status: entry.workItemStatus,
                stop_reason: entry.workItemLoopView.stop_reason ?? null,
              }),
              conclusion: null,
            }) ?? OPEN_ENDED_TEXT
          : OPEN_ENDED_TEXT;
      return {
        kind: entry.kind,
        versionView,
        prd: null,
        rounds: [],
        launch,
        conclusion: null,
        review: null,
        openEnded,
        fileDiff,
        gitDiffLines,
        citedCases: { rows: [], missing: [] },
        defectText: null,
        missingReviewText: null,
      };
    }

    const matchedReview = selectReviewForEntry(entry, matLike);
    const scopedMaterials: MaterialsLike | null =
      matLike === null
        ? null
        : matchedReview !== null
          ? { ...matLike, reviews: [matchedReview] }
          : matLike;

    const arrowForConclusion: LoopArrow | null =
      matchedArrow === null
        ? null
        : matchedArrow.verdict !== null
          ? matchedArrow
          : entry.verdictBadge.kind === "release"
            ? {
                ...matchedArrow,
                verdict: { tone: "release", by: entry.verdictBadge.by, text: entry.verdictBadge.text },
              }
            : entry.verdictBadge.kind === "reject"
              ? {
                  ...matchedArrow,
                  verdict: { tone: "reject", by: entry.verdictBadge.by, text: entry.verdictBadge.text },
                }
              : matchedArrow;

    const conclusion =
      arrowForConclusion !== null && arrowForConclusion.verdict !== null
        ? conclusionOf(arrowForConclusion, scopedMaterials, coverage)
        : null;
    const panel =
      arrowForConclusion !== null && arrowForConclusion.verdict !== null
        ? arrowPanelView({
            arrow: arrowForConclusion,
            versions,
            materials: scopedMaterials,
            inputs: null,
            coverage,
            verifier: hasVerifiers,
            ended: "",
          })
        : null;

    const effectiveConclusion = panel?.conclusion ?? conclusion;
    const citedCases =
      effectiveConclusion !== null ? citedCasesOf(trials, effectiveConclusion.caseIds) : { rows: [], missing: [] };
    const missingReviewText =
      entry.needsReviewDetails && materials !== null && effectiveConclusion === null ? MISSING_REVIEW_TEXT : null;

    return {
      kind: entry.kind,
      versionView,
      prd: null,
      rounds: [],
      launch,
      conclusion: effectiveConclusion,
      review: matchedReview,
      openEnded: null,
      fileDiff,
      gitDiffLines,
      citedCases,
      defectText: null,
      missingReviewText,
    };
  }

  // defect（问题反馈 / 缺陷记录）
  const matchedReview = selectReviewForEntry(entry, matLike);
  const scopedMaterials: MaterialsLike | null =
    matLike === null
      ? null
      : matchedReview !== null
        ? { ...matLike, reviews: [matchedReview] }
        : matLike;
  const arrowForDefect: LoopArrow | null =
    matchedArrow === null
      ? null
      : matchedArrow.verdict !== null
        ? matchedArrow
        : {
            ...matchedArrow,
            verdict: { tone: "reject", by: entry.verdictBadge.by, text: entry.summary },
          };
  const conclusion = arrowForDefect !== null ? conclusionOf(arrowForDefect, scopedMaterials, coverage) : null;
  const citedCases = conclusion !== null ? citedCasesOf(trials, conclusion.caseIds) : { rows: [], missing: [] };

  return {
    kind: entry.kind,
    versionView: null,
    prd: null,
    rounds: [],
    launch: [],
    conclusion,
    review: matchedReview,
    openEnded: null,
    fileDiff: null,
    gitDiffLines: [],
    citedCases,
    defectText: entry.summary,
    missingReviewText: null,
  };
}

export { NO_FILES_TEXT, OPEN_ENDED_TEXT, MISSING_REVIEW_TEXT };
