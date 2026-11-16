// 内嵌「现场窗口 · live」的纯计算模型（工单 #1811，docs/design/project-organization.md
// 「项目页是循环图加对话」「项目页上的内容在哪里看」「节点面板与箭头面板接住的内容」）。
//
// 这里只算选区切换、遥测摘要、触及文件、待决摘要与往来筛选，不碰网络与界面；
// 视图 live-window.tsx 按它画，单元测试 live-window-model.test.ts 直接核对。
// 相对导入全部带 .ts 扩展名，供 node --test 直接运行。

import type {
  AskView,
  DecisionView,
  DepartmentWorkspaceResult,
  DraftOrganization,
  RunStepsResult,
  AttemptView,
} from "../../api/generated/types.gen";
import { paths } from "../../shell/routing.ts";
import { draftDepartment, writeScopeText } from "./department-detail-model.ts";
import { DECISION_KIND, label } from "./labels.ts";
import {
  decisionMatchesDepartment,
  nodeTelemetryOf,
  outcomeOf,
  type FlowRecordLike,
  type LoopArrow,
  type LoopAsk,
  type LoopGraph,
  type LoopItemView,
  type LoopNode,
  type MaterialsView,
  type NodeTelemetry,
  type TelemetryCatalog,
  type TelemetrySettings,
} from "./loop-graph-model.ts";
import {
  NO_LAST_CALL_TEXT,
  NOT_REPORTED_TEXT,
  guidanceItems,
  lastRequestDetail,
  nodePanelView,
  workshopRecoveryNeeded,
  type GuidanceItemView,
  type LastRequestDetail,
  type NodePanelView,
} from "./node-panel-model.ts";
import { threadDecisionView, type ThreadDecision } from "./thread-model.ts";
import { formatTokens } from "./usage-text.ts";
import { doingText, nodeDoing } from "./work-process-model.ts";

/** 选中的职能默认策略：显式点选 > 正在工作的职能 > 事项当前负责职能 > 冻结组织首个职能。 */
export function pickLiveDepartment(
  item: LoopItemView | null,
  roles: readonly { id: string }[],
  explicitDept: string | null | undefined,
): string {
  const ids = roles.map((role) => role.id);
  if (ids.length === 0) {
    return "";
  }
  if (explicitDept && ids.includes(explicitDept)) {
    return explicitDept;
  }
  const activeRole = ids.find((id) => {
    const state = item?.departments?.[id]?.state ?? "";
    return state === "working" || state === "verifying" || state === "asking" || state === "waiting_user";
  });
  if (activeRole !== undefined) {
    return activeRole;
  }
  if (item?.department && ids.includes(item.department)) {
    return item.department;
  }
  return ids[0];
}

/** 根据地址参数 ?arrow= 找到图上的对应箭头。 */
export function arrowMatchesQuery(
  arrows: readonly LoopArrow[],
  arrowParam: string | null | undefined,
): LoopArrow | null {
  if (!arrowParam) {
    return null;
  }
  return arrows.find((arrow) => arrow.key === arrowParam)
    ?? arrows.find((arrow) => arrow.eventId === arrowParam)
    ?? null;
}

/** 触及文件或写入范围：已交出的交付按事件对应 work_item.materials，尚无交付时写职能写入范围。 */
export type TouchedMaterialsView =
  | { kind: "files"; files: string[]; deliveryCount: number }
  | { kind: "scope"; scopeText: string };

export function touchedMaterialsOf(input: {
  department: string;
  materials: MaterialsView | null | undefined;
  flow: readonly FlowRecordLike[];
  organization: DraftOrganization | null | undefined;
}): TouchedMaterialsView {
  const deliveryEventIds = new Set(
    input.flow
      .filter((record) => record.direction_from === input.department && outcomeOf(record.kind) === "交付")
      .map((record) => record.event_id),
  );
  const matchedDeliveries = (input.materials?.deliveries ?? []).filter(
    (entry) => deliveryEventIds.has(entry.event_id),
  );
  const files: string[] = [];
  const seen = new Set<string>();
  for (const delivery of [...matchedDeliveries].reverse()) {
    for (const file of delivery.files ?? []) {
      const clean = file.trim();
      if (clean !== "" && !seen.has(clean)) {
        seen.add(clean);
        files.push(clean);
      }
    }
  }
  if (files.length > 0) {
    return { kind: "files", files, deliveryCount: matchedDeliveries.length };
  }
  const deptDef = draftDepartment(input.organization ?? null, input.department);
  return { kind: "scope", scopeText: writeScopeText(deptDef?.write_scope ?? "") };
}

export interface LiveDecisionQuestionPreview {
  id: string;
  question: string;
  recommendedLabel: string | null;
  rationale: string;
}

export interface LiveDecisionSummary {
  decisionId: string;
  kind: string;
  kindLabel: string;
  roundLabel: string;
  blocksText: string;
  roleNote: string;
  description: string;
  questions: LiveDecisionQuestionPreview[];
}

/** 属于当前所选职能的待回答决定摘要（含多题题干与推荐项预览）。 */
export function livePendingDecisions(input: {
  decisions: readonly DecisionView[];
  item: LoopItemView | null;
  department: string;
}): LiveDecisionSummary[] {
  const itemId = input.item?.work_item_id ?? "";
  return input.decisions
    .filter((decision) =>
      decision.status === "open"
      && (itemId === "" || decision.work_item_id === itemId)
      && decisionMatchesDepartment(decision, input.department, input.item),
    )
    .map((decision) => {
      const view = threadDecisionView(decision as unknown as ThreadDecision);
      const req = (decision.request ?? {}) as Record<string, unknown>;
      const description = typeof req["description"] === "string" ? req["description"].trim() : "";
      const questions: LiveDecisionQuestionPreview[] = view.questions.map((q) => {
        const recOpt = q.options.find((opt) => opt.id === q.recommended);
        return {
          id: q.id,
          question: q.question,
          recommendedLabel: recOpt ? recOpt.label : (q.recommended === "" ? null : q.recommended),
          rationale: q.rationale,
        };
      });
      return {
        decisionId: decision.decision_id,
        kind: decision.kind,
        kindLabel: label(DECISION_KIND, decision.kind),
        roundLabel: view.roundLabel,
        blocksText: view.blocksText,
        roleNote: view.roleNote,
        description,
        questions,
      };
    });
}

/** 与当前职能相关的成果箭头（发出方或接收方为该职能，按最近发生排前）。 */
export function liveRelatedArrows(arrows: readonly LoopArrow[], department: string): LoopArrow[] {
  return [...arrows]
    .filter((arrow) => arrow.from === department || arrow.to === department)
    .sort((left, right) => right.position - left.position);
}

export interface LiveRecentRequestView {
  attemptId: string | null;
  href: string | null;
  tokensText: string;
  contextText: string;
  contextPercent: number | null;
  modelText: string;
}

export interface LiveWindowView {
  department: string;
  node: LoopNode;
  telemetry: NodeTelemetry;
  panelView: NodePanelView;
  goalText: string;
  lastCall: LastRequestDetail | null;
  recentRequest: LiveRecentRequestView | null;
  recoveryHref: string | null;
  touches: TouchedMaterialsView;
  guidance: GuidanceItemView[];
  exchanges: LoopAsk[];
  pendingDecisions: LiveDecisionSummary[];
  relatedArrows: LoopArrow[];
  partner: string | null;
}

export function liveWindowView(input: {
  projectId: string;
  workItemId: string;
  runId: string;
  department: string;
  item: LoopItemView | null;
  graph: LoopGraph;
  arrows: readonly LoopArrow[];
  flow: readonly FlowRecordLike[];
  materials: MaterialsView | null | undefined;
  workspace: DepartmentWorkspaceResult | null;
  steps: RunStepsResult | null;
  asks: readonly AskView[] | null | undefined;
  decisions: readonly DecisionView[];
  settings: TelemetrySettings | null | undefined;
  catalog: TelemetryCatalog | null | undefined;
  attempts: readonly AttemptView[];
  organization: DraftOrganization | null | undefined;
  now?: number;
}): LiveWindowView | null {
  const node = input.graph.nodes.find((candidate) => candidate.id === input.department);
  if (node === undefined) {
    return null;
  }
  const telemetry = nodeTelemetryOf({
    node,
    item: input.item,
    workspace: input.workspace,
    settings: input.settings,
    catalog: input.catalog,
    attempts: input.attempts,
    decisions: input.decisions,
  });
  const panelView = nodePanelView(
    node,
    input.workspace,
    input.projectId,
    input.workItemId,
    input.asks,
    input.now,
  );
  const doing = nodeDoing(input.steps, node.working);
  const goalText = doing !== null ? doingText(doing) : panelView.state;
  const lastCall = lastRequestDetail(input.workspace);

  let recentRequest: LiveRecentRequestView | null = null;
  if (telemetry.latestAttempt !== null) {
    const attempt = telemetry.latestAttempt;
    const usage = telemetry.latestUsage;
    const tokensText = usage === null || !usage.reported
      ? NOT_REPORTED_TEXT
      : `输入 ${formatTokens(usage.input)} · 输出 ${formatTokens(usage.output)} · 总 ${formatTokens(usage.total)}`;
    const modelText = attempt.actual_model ?? attempt.requested_model ?? (telemetry.modelUnset ? NOT_REPORTED_TEXT : telemetry.modelName);
    recentRequest = {
      attemptId: attempt.attempt_id,
      href: paths.observeDetail(input.projectId, attempt.attempt_id, {
        workItem: input.workItemId === "" ? null : input.workItemId,
        runId: input.runId === "" ? null : input.runId,
        department: node.id,
        from: "conversation",
      }),
      tokensText,
      contextText: telemetry.contextText,
      contextPercent: telemetry.contextPercent,
      modelText,
    };
  } else if (lastCall !== null && lastCall.hasCall) {
    recentRequest = {
      attemptId: null,
      href: null,
      tokensText: NOT_REPORTED_TEXT,
      contextText: telemetry.contextText,
      contextPercent: telemetry.contextPercent,
      modelText: lastCall.model,
    };
  }

  const recoveryHref = workshopRecoveryNeeded(input.workspace) && input.workItemId !== ""
    ? paths.recovery(input.projectId, input.workItemId)
    : null;

  const touches = touchedMaterialsOf({
    department: node.id,
    materials: input.materials,
    flow: input.flow,
    organization: input.organization,
  });

  const guidance = guidanceItems(input.workspace);
  const exchanges = input.graph.asks.filter((ask) => ask.from === node.id || ask.to === node.id);
  const pendingDecisions = livePendingDecisions({
    decisions: input.decisions,
    item: input.item,
    department: node.id,
  });
  const relatedArrows = liveRelatedArrows(input.arrows, node.id);
  const partner = input.graph.side.find((part) => part.node.id === node.id)?.partner ?? null;

  return {
    department: node.id,
    node,
    telemetry,
    panelView,
    goalText,
    lastCall,
    recentRequest,
    recoveryHref,
    touches,
    guidance,
    exchanges,
    pendingDecisions,
    relatedArrows,
    partner,
  };
}

export { NO_LAST_CALL_TEXT };
