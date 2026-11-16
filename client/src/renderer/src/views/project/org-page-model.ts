// 「组织」标签页纯视图模型：从合成组织计算四问、蓝图、成果流向、只读职能表与历史改回预览。

import type {
  Catalog,
  DraftDepartment,
  DraftOrganization,
  DraftReminder,
  FormChange,
  FormChoice,
  FormDifference,
  ItemOrganization,
  OrganizationDepartment,
  OrganizationDraftResult,
  ProjectLoopResult,
  ProjectOrganizationResult,
  ProjectSettingsResult,
} from "../../api/generated/types.gen.ts";
import type { CommandProblem } from "../../contract/command-problem.ts";
import { paths } from "../../shell/routing.ts";
import { modelById, mergedModelId } from "../models/model-logic.ts";
import { frozenOrganizationOf } from "./form-cards-model.ts";
import {
  actorText,
  discardedLines,
  needsRefresh,
  reasonText,
} from "./form-section-logic.ts";
import { formatTime, workItemStatusText } from "./labels.ts";
import { graphOf, type LoopGraph, type LoopItemView } from "./loop-graph-model.ts";
import { projectHead, rotationText } from "./project-head-model.ts";

/** 一条候选形态或候选调整建议（后端扩展字段存在时展示）。 */
export interface OrganizationCandidate {
  id?: string;
  title?: string;
  summary?: string;
  reason?: string;
  source?: string;
  target?: string;
  diff?: FormDifference[];
  changes?: FormDifference[];
  evidence?: Array<string | { label?: string; summary?: string; detail?: string }>;
}

/** 扩展 `ProjectOrganizationResult`，兼容可选 `candidates` 列表。 */
export type ProjectOrganizationSnapshot = ProjectOrganizationResult & {
  candidates?: readonly OrganizationCandidate[];
};

export interface OrgQuestions {
  fromWhere: string;
  whoDoes: string;
  whoVerifies: string;
  howEnds: string;
}

export interface OrgBlueprintStageNode {
  id: string;
  title: string;
  detail: string;
  kind: "source" | "department" | "verifier" | "ending";
  verifier?: boolean;
}

export interface OrgBlueprintView {
  routingLabel: string;
  isOpenLoop: boolean;
  endingText: string;
  loopGraph: LoopGraph;
  flowSteps: string[];
  sources: OrgBlueprintStageNode[];
  executors: OrgBlueprintStageNode[];
  verifiers: OrgBlueprintStageNode[];
  endingNode: OrgBlueprintStageNode;
}

export interface OrgFormSummary {
  formId: string;
  formLabel: string;
  version: string;
  inRelease: boolean;
  routingText: string;
  endingText: string;
  isOpenLoop: boolean;
  changeCount: number;
}

export interface OldOrgItemView {
  workItemId: string;
  statusText: string;
  formLabel: string;
  version: string;
  href: string;
}

export interface PreviousItemDiffView {
  workItemId: string;
  title: string;
  formLabel: string;
  version: string;
  differences: FormDifference[];
}

export interface OrgDepartmentRow {
  id: string;
  label: string;
  verifier: boolean;
  target: string;
  whenToStart: string;
  outputs: string;
  relationText: string;
  modelText: string;
  modelSourceText: string;
  originKind: "release" | "changed" | "added" | "running_item";
  originLabel: string;
  runningItemsCount: number;
  clickable: boolean;
}

export interface OrgCandidateView {
  key: string;
  title: string;
  summary: string;
  diffLines: string[];
  evidenceLines: string[];
}

export interface OrgHistoryRow {
  eventId: string;
  atText: string;
  actorLabel: string;
  previousFormId: string;
  previousFormLabel: string;
  formId: string;
  formLabel: string;
  previousVersion: string;
  version: string;
  reason: string;
  diffLines: string[];
  changes: Record<string, unknown>;
  isCurrent: boolean;
  canRevert: boolean;
}

export interface OrgRevertPreview {
  targetFormLabel: string;
  targetVersion: string;
  diffLines: string[];
  discarded: string[];
  finishesText: string;
  isOpenLoop: boolean;
  rejections: string[];
  reminders: string[];
  blocked: boolean;
}

const SOURCE_LABELS: Record<string, string> = {
  user_input: "你的输入",
  onboarding: "建档",
};

const FALLBACK_OUTCOME_LABELS: Record<string, string> = {
  user_input: "你的输入",
  guidance: "指导",
  delivery: "交付",
  delivery_spec: "交付",
  defect_record: "缺陷记录",
  completion: "交完成",
  product_spec: "PRD",
  product_decision: "产品决定",
  structure: "现有结构说明",
  baseline_review: "基线审查",
  independent_judgement: "独立判断",
  qa_review: "核验结论",
  completion_review: "核验结论",
};

const AUXILIARY_FLOW_OUTCOMES = new Set([
  "product_decision",
  "independent_judgement",
  "qa_review",
  "completion_review",
  "structure",
  "baseline_review",
]);

const UNFINISHED_WORK_ITEM_STATUSES = new Set([
  "not_started",
  "held",
  "in_progress",
  "awaiting_initial_prd",
]);

const FINISHING_FLOW_OUTCOMES = new Set(["completion", "delivery_spec", "delivery"]);

const ORIGIN_LABELS: Record<NonNullable<OrganizationDepartment["origin"]>, string> = {
  release: "跟随发布",
  changed: "本项目改过",
  added: "本项目加的",
  running_item: "只在旧组织里",
};

function deptMap(org: DraftOrganization): Map<string, DraftDepartment> {
  return new Map(org.departments.map((dept) => [dept.id, dept]));
}

function deptLabel(org: DraftOrganization, deptId: string): string {
  return deptMap(org).get(deptId)?.label || deptId;
}

export function outcomeLabel(org: DraftOrganization, outcomeId: string): string {
  const fromKinds = org.outcome_kinds.find((item) => item.id === outcomeId)?.label;
  if (fromKinds) return fromKinds;
  return FALLBACK_OUTCOME_LABELS[outcomeId] ?? outcomeId;
}

function flowOutcomeLabel(org: DraftOrganization, outcomeId: string): string {
  if (outcomeId === "completion" || outcomeId === "delivery" || outcomeId === "delivery_spec") {
    const raw = org.outcome_kinds.find((item) => item.id === outcomeId)?.label;
    if (!raw || raw === "交完成") return "交付";
    return raw;
  }
  return outcomeLabel(org, outcomeId);
}

/** 判定监听项是否对应产出的成果（包含 delivery 与 delivery_spec 同义映射）。 */
export function watchedMatchesOutcome(watchedId: string, outcomeId: string): boolean {
  if (watchedId === outcomeId) return true;
  if (
    (watchedId === "delivery" && outcomeId === "delivery_spec") ||
    (watchedId === "delivery_spec" && outcomeId === "delivery")
  ) {
    return true;
  }
  return false;
}

function uniqueStrings(values: readonly string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const v of values) {
    if (!v || seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

function sourcesByDepartment(org: DraftOrganization): Map<string, string[]> {
  const grouped = new Map<string, string[]>();
  for (const [sourceKey, targetDeptId] of Object.entries(org.sources ?? {})) {
    if (!targetDeptId) continue;
    const label = SOURCE_LABELS[sourceKey] ?? outcomeLabel(org, sourceKey);
    const list = grouped.get(targetDeptId) ?? [];
    list.push(label);
    grouped.set(targetDeptId, list);
  }
  return grouped;
}

function primaryFlowOutcomes(org: DraftOrganization, dept: DraftDepartment): string[] {
  const verifiedSet = new Set(
    org.verification.filter((v) => v.verified === dept.id).map((v) => v.outcome),
  );
  const directMain = dept.outcomes.filter(
    (outId) => !AUXILIARY_FLOW_OUTCOMES.has(outId) || verifiedSet.has(outId),
  );
  if (directMain.length > 0) return directMain;
  if (dept.verifier) return [];
  return dept.outcomes;
}

/** 纯由合成组织计算头部四问：事项从哪来、谁做、谁核验、怎么结束。 */
export function orgQuestions(org: DraftOrganization): OrgQuestions {
  const byDept = sourcesByDepartment(org);
  const sourceParts: string[] = [];
  for (const [deptId, labels] of byDept.entries()) {
    sourceParts.push(`${uniqueStrings(labels).join("、")} → ${deptLabel(org, deptId)}`);
  }
  const fromWhere = sourceParts.length > 0 ? sourceParts.join("；") : "尚未声明事项入口";

  const executors = org.departments.filter((d) => !d.verifier).map((d) => d.label);
  const verifiers = org.departments.filter((d) => d.verifier).map((d) => d.label);
  let whoDoes = "尚未配置职能";
  if (executors.length > 0 && verifiers.length > 0) {
    whoDoes = `${executors.join("、")}推进与产出；${verifiers.join("、")}独立核验`;
  } else if (executors.length > 0) {
    whoDoes = `${executors.join("、")}负责推进与产出`;
  } else if (verifiers.length > 0) {
    whoDoes = verifiers.join("、");
  }

  let whoVerifies = "没有人核验";
  if (org.verification.length > 0) {
    whoVerifies = org.verification
      .map(
        (rule) =>
          `${deptLabel(org, rule.verifier)}核验${deptLabel(org, rule.verified)}的${flowOutcomeLabel(org, rule.outcome)}`,
      )
      .join("；");
  } else if (verifiers.length > 0) {
    whoVerifies = `${verifiers.join("、")}（尚未指定核验对象）`;
  }

  let howEnds = "开环完成：没有人核验";
  if (org.verification.length > 0) {
    const verifierNames = uniqueStrings(
      org.verification.map((rule) => deptLabel(org, rule.verifier)),
    ).join("、");
    const targetNames = uniqueStrings(
      org.verification.map(
        (rule) => `${deptLabel(org, rule.verified)}的${flowOutcomeLabel(org, rule.outcome)}`,
      ),
    ).join("、");
    howEnds = `${verifierNames}放行才算完成（核验${targetNames}）`;
  } else {
    const finishers = org.departments
      .filter((d) => !d.verifier && primaryFlowOutcomes(org, d).length > 0)
      .map((d) => d.label);
    if (finishers.length > 0) {
      howEnds = `开环完成：没有人核验，${finishers.join("、")}交出成果即完成`;
    }
  }

  return { fromWhere, whoDoes, whoVerifies, howEnds };
}

/** 纯由合成组织计算「成果怎么走」步骤列表，不按形态名分支。 */
export function flowSteps(org: DraftOrganization): string[] {
  const byDept = sourcesByDepartment(org);
  const sourceSteps: string[] = [];
  for (const [deptId, labels] of byDept.entries()) {
    sourceSteps.push(`${uniqueStrings(labels).join("、")} → ${deptLabel(org, deptId)}`);
  }

  const handoffSteps: string[] = [];
  const openLoopSteps: string[] = [];
  const hasVerification = org.verification.length > 0;
  const reachedDepts = new Set<string>(byDept.keys());

  for (const dept of org.departments) {
    const outIds = primaryFlowOutcomes(org, dept);
    const openCandidates: string[] = [];
    for (const outId of outIds) {
      const receivers: string[] = [];
      for (const other of org.departments) {
        if (other.id === dept.id) continue;
        if (other.watched.some((w) => watchedMatchesOutcome(w, outId))) {
          receivers.push(other.label);
          reachedDepts.add(other.id);
        }
      }
      for (const rule of org.verification) {
        if (rule.verified === dept.id && watchedMatchesOutcome(rule.outcome, outId)) {
          receivers.push(deptLabel(org, rule.verifier));
          reachedDepts.add(rule.verifier);
        }
      }
      const uniqueReceivers = uniqueStrings(receivers);
      const outLabel = flowOutcomeLabel(org, outId);
      if (uniqueReceivers.length > 0) {
        handoffSteps.push(`${dept.label} → ${outLabel} → ${uniqueReceivers.join("、")}`);
      } else if (!hasVerification && !dept.verifier) {
        openCandidates.push(outId);
      }
    }
    if (openCandidates.length > 0) {
      const terminal = openCandidates.filter((id) => FINISHING_FLOW_OUTCOMES.has(id));
      const pickedOpen = terminal.length > 0 ? terminal : openCandidates;
      for (const outId of pickedOpen) {
        openLoopSteps.push(`${dept.label} → ${flowOutcomeLabel(org, outId)} → 开环完成`);
      }
    }
  }

  if (org.routing === "direct") {
    const coordinators = uniqueStrings([...byDept.keys()].map((id) => deptLabel(org, id)));
    const directTargets = org.departments.filter(
      (d) => !d.verifier && !reachedDepts.has(d.id),
    );
    if (directTargets.length > 0 && coordinators.length > 0) {
      handoffSteps.unshift(
        `${coordinators.join("、")} → 询问、指导 → ${directTargets.map((d) => d.label).join("、")}`,
      );
    }
  }

  const verifierSteps: string[] = [];
  if (hasVerification) {
    for (const rule of org.verification) {
      const verifiedDept = deptMap(org).get(rule.verified);
      const verifierName = deptLabel(org, rule.verifier);
      if (verifiedDept?.watched.includes("defect_record")) {
        verifierSteps.push(
          `${verifierName} → ${outcomeLabel(org, "defect_record")} → ${verifiedDept.label}`,
        );
      }
    }
    const releasingVerifiers = uniqueStrings(
      org.verification.map((rule) => deptLabel(org, rule.verifier)),
    );
    verifierSteps.push(`${releasingVerifiers.join("、")} → 放行 → 事项完成`);
  }

  const bodySteps = [...handoffSteps, ...verifierSteps, ...openLoopSteps];
  // 只有单部门且首尾恰好衔接成一条直通路线时，合并为单行入口到结束路径。
  if (
    org.departments.length === 1 &&
    sourceSteps.length === 1 &&
    bodySteps.length === 1 &&
    openLoopSteps.length === 1
  ) {
    const prefix = sourceSteps[0];
    const targetPrefix = `${org.departments[0].label} → `;
    if (bodySteps[0].startsWith(targetPrefix)) {
      return [`${prefix}${bodySteps[0].slice(org.departments[0].label.length)}`];
    }
  }

  const combined = [...sourceSteps, ...bodySteps];
  if (combined.length > 0) return combined;
  return org.departments.length > 0
    ? [`${org.departments.map((d) => d.label).join("、")} → 开环完成`]
    : [];
}

/** 计算组织蓝图所需的各阶段节点、轮转画布数据与流向步骤。 */
export function orgBlueprint(org: DraftOrganization): OrgBlueprintView {
  const byDept = sourcesByDepartment(org);
  const questions = orgQuestions(org);
  const steps = flowSteps(org);
  const isOpenLoop = org.verification.length === 0;
  const routingLabel = rotationText(org.routing, org.routing_label);

  const sources: OrgBlueprintStageNode[] = Object.entries(org.sources ?? {}).map(
    ([sourceKey, deptId]) => ({
      id: `source:${sourceKey}`,
      title: SOURCE_LABELS[sourceKey] ?? outcomeLabel(org, sourceKey),
      detail: `交给 ${deptLabel(org, deptId)}`,
      kind: "source",
    }),
  );

  const executors: OrgBlueprintStageNode[] = org.departments
    .filter((d) => !d.verifier)
    .map((d) => {
      const outs = primaryFlowOutcomes(org, d).map((id) => flowOutcomeLabel(org, id));
      const inSources = uniqueStrings(byDept.get(d.id) ?? []);
      const parts: string[] = [];
      if (inSources.length > 0) parts.push(`接入：${inSources.join("、")}`);
      if (outs.length > 0) parts.push(`交出：${outs.join("、")}`);
      return {
        id: d.id,
        title: d.label,
        detail: parts.join(" · ") || "按分工推进",
        kind: "department",
        verifier: false,
      };
    });

  const verifiers: OrgBlueprintStageNode[] = org.departments
    .filter((d) => d.verifier)
    .map((d) => {
      const rules = org.verification
        .filter((v) => v.verifier === d.id)
        .map((v) => `${deptLabel(org, v.verified)}的${flowOutcomeLabel(org, v.outcome)}`);
      return {
        id: d.id,
        title: d.label,
        detail: rules.length > 0 ? `核验：${rules.join("、")}` : "独立核验角色",
        kind: "verifier",
        verifier: true,
      };
    });

  const endingNode: OrgBlueprintStageNode = {
    id: "ending",
    title: isOpenLoop ? "开环完成" : "放行完成",
    detail: questions.howEnds,
    kind: "ending",
  };

  const frozen = frozenOrganizationOf(org);
  const blueprintItem: LoopItemView = {
    work_item_id: "",
    status: "not_started",
    organization: frozen,
  };
  const loopGraph = graphOf({
    item: blueprintItem,
    flow: [],
    materials: null,
    current: { form: frozen.form, sources: org.sources },
    currentRoles: frozen.roles.map((role) => role.id),
  });

  return {
    routingLabel,
    isOpenLoop,
    endingText: endingNode.title,
    loopGraph,
    flowSteps: steps,
    sources,
    executors,
    verifiers,
    endingNode,
  };
}

/** 汇总顶部当前形态、轮转/结束标记、改过处数与版本信息。 */
export function orgFormSummary(organization: ProjectOrganizationResult): OrgFormSummary {
  const synth = organization.organization;
  const head = projectHead(organization);
  const routing = synth?.routing
    ? rotationText(synth.routing, synth.routing_label)
    : head?.rotation ?? "";
  const hasVerifier = synth
    ? synth.verification.length > 0
    : organization.departments.some((d) => d.verifier);
  const endingText = hasVerifier
    ? `${uniqueStrings(
        (synth?.verification ?? []).map((v) => (synth ? deptLabel(synth, v.verifier) : v.verifier)),
      )
        .concat(
          synth?.verification.length
            ? []
            : organization.departments.filter((d) => d.verifier).map((d) => d.label),
        )
        .join("、") || "核验角色"}放行完成`
    : "开环完成";

  return {
    formId: organization.form,
    formLabel: organization.label || head?.form || organization.form,
    version: organization.version || synth?.version || "—",
    inRelease: organization.form_in_release,
    routingText: routing || "—",
    endingText,
    isOpenLoop: !hasVerifier,
    changeCount: head?.changed ?? 0,
  };
}

function formLabelById(formId: string, forms: readonly FormChoice[], fallback?: string | null): string {
  const found = forms.find((item) => item.form === formId);
  return found?.label || fallback || formId;
}

/** 列出当前仍按建立时冻结的旧组织运行的未结束事项。 */
export function oldOrgItems(
  loop: ProjectLoopResult | null,
  organization: ProjectOrganizationResult,
  projectId: string,
): OldOrgItemView[] {
  if (!loop) return [];
  const items: OldOrgItemView[] = [];
  for (const item of loop.work_items) {
    if (!UNFINISHED_WORK_ITEM_STATUSES.has(item.status)) continue;
    if (item.organization?.same_as_project !== false) continue;
    const oldOrg = item.organization;
    const statusText = workItemStatusText({ status: item.status, stop_reason: item.stop_reason });
    items.push({
      workItemId: item.work_item_id,
      statusText,
      formLabel: formLabelById(oldOrg.form, organization.forms),
      version: oldOrg.version || "—",
      href: paths.conversation(projectId, { workItem: item.work_item_id }),
    });
  }
  return items;
}

/** 计算与上一条事项的组织差异提示；没有差异时返回 null。 */
export function previousItemDiffView(
  previousItem: ItemOrganization | null | undefined,
  forms: readonly FormChoice[],
): PreviousItemDiffView | null {
  if (!previousItem) return null;
  const differences = previousItem.differences ?? [];
  if (differences.length === 0) return null;
  return {
    workItemId: previousItem.work_item_id,
    title: previousItem.title || previousItem.work_item_id,
    formLabel: formLabelById(previousItem.form, forms),
    version: previousItem.version,
    differences,
  };
}

function formatWhenToStart(org: DraftOrganization, dept: DraftDepartment): string {
  const byDept = sourcesByDepartment(org);
  const incomingSources = uniqueStrings(byDept.get(dept.id) ?? []);
  const parts: string[] = [];
  if (incomingSources.length > 0) {
    parts.push(`收到${incomingSources.join("、")}`);
  }
  if (org.routing === "direct") {
    parts.push("收到指导、询问时");
    const extraWatched = dept.watched
      .filter((w) => w !== "guidance" && w !== "user_input")
      .map((w) => outcomeLabel(org, w));
    if (extraWatched.length > 0) {
      parts.push(`监听 ${uniqueStrings(extraWatched).join("、")}`);
    }
  } else {
    const watchedNames = dept.watched
      .filter((w) => w !== "user_input")
      .map((w) => outcomeLabel(org, w));
    if (watchedNames.length > 0) {
      parts.push(`监听 ${uniqueStrings(watchedNames).join("、")}`);
    }
  }
  return parts.join("；") || "按需触发";
}

function formatRelationColumn(org: DraftOrganization, dept: DraftDepartment): string {
  if (org.routing === "direct") {
    const completers = org.departments.filter((d) => d.outcomes.includes("completion"));
    if (dept.outcomes.includes("completion")) {
      const verifiers = org.verification
        .filter((v) => v.verified === dept.id)
        .map((v) => deptLabel(org, v.verifier));
      return verifiers.length > 0
        ? `本职能交完成（${uniqueStrings(verifiers).join("、")}核验）`
        : "本职能交完成";
    }
    if (dept.verifier) {
      const targets = org.verification
        .filter((v) => v.verifier === dept.id)
        .map((v) => deptLabel(org, v.verified));
      if (targets.length > 0) return `核验 ${uniqueStrings(targets).join("、")} 的完成`;
    }
    if (completers.length > 0) {
      return `由 ${completers.map((d) => d.label).join("、")} 交完成`;
    }
    return "—";
  }

  const verifiedBy = org.verification
    .filter((v) => v.verified === dept.id)
    .map((v) => `${deptLabel(org, v.verifier)}（${flowOutcomeLabel(org, v.outcome)}）`);
  const verifies = org.verification
    .filter((v) => v.verifier === dept.id)
    .map((v) => `${deptLabel(org, v.verified)}（${flowOutcomeLabel(org, v.outcome)}）`);
  const parts: string[] = [];
  if (verifiedBy.length > 0) parts.push(`由 ${uniqueStrings(verifiedBy).join("、")} 核验`);
  if (verifies.length > 0) parts.push(`核验 ${uniqueStrings(verifies).join("、")}`);
  return parts.join(" · ") || "无核验关系";
}

function resolveDepartmentModel(
  deptId: string,
  settings: ProjectSettingsResult | null,
  catalog: Catalog | null,
): { modelText: string; modelSourceText: string } {
  const projectModelId = settings?.departments?.[deptId]?.model_id ?? "";
  const bindings = catalog?.bindings ?? {};
  const defaultModelId = bindings[deptId]?.model_id ?? "";
  const effectiveId = mergedModelId(projectModelId, deptId, bindings);
  const modelInfo = modelById(catalog?.models ?? [], effectiveId);

  let modelSourceText = "尚未设置";
  if (projectModelId) {
    modelSourceText = "本项目写入";
  } else if (defaultModelId || modelInfo) {
    modelSourceText = "跟随职能默认";
  }

  const modelText = modelInfo
    ? `${modelInfo.model}（${modelInfo.provider_id}）`
    : effectiveId || "未设置";

  return { modelText, modelSourceText };
}

/** 为只读职能表返回按轮转方式组织好的行数据。 */
export function departmentTableColumnTitle(org: DraftOrganization | null | undefined): string {
  return org?.routing === "direct" ? "谁交完成" : "谁核验它 · 它核验谁";
}

export function departmentRows(input: {
  organization: ProjectOrganizationResult;
  settings: ProjectSettingsResult | null;
  catalog: Catalog | null;
}): OrgDepartmentRow[] {
  const { organization, settings, catalog } = input;
  const synth = organization.organization;
  const summaryById = new Map(organization.departments.map((d) => [d.id, d]));
  const rows: OrgDepartmentRow[] = [];
  const includedIds = new Set<string>();

  if (synth) {
    for (const dept of synth.departments) {
      includedIds.add(dept.id);
      const summary = summaryById.get(dept.id);
      const originKind = summary?.origin ?? "release";
      const { modelText, modelSourceText } = resolveDepartmentModel(dept.id, settings, catalog);
      const outputNames = uniqueStrings(dept.outcomes.map((id) => outcomeLabel(synth, id)));

      rows.push({
        id: dept.id,
        label: dept.label,
        verifier: Boolean(dept.verifier),
        target: dept.target || "未填写",
        whenToStart: formatWhenToStart(synth, dept),
        outputs: outputNames.join("、") || "—",
        relationText: formatRelationColumn(synth, dept),
        modelText,
        modelSourceText,
        originKind,
        originLabel: ORIGIN_LABELS[originKind],
        runningItemsCount: summary?.running_items ?? 0,
        clickable: true,
      });
    }
  }

  for (const summary of organization.departments) {
    if (includedIds.has(summary.id)) continue;
    const originKind = summary.origin ?? "release";
    const { modelText, modelSourceText } = resolveDepartmentModel(summary.id, settings, catalog);
    const suffix =
      originKind === "running_item" && (summary.running_items ?? 0) > 0
        ? `（${summary.running_items} 个运行中事项）`
        : "";
    rows.push({
      id: summary.id,
      label: summary.label,
      verifier: Boolean(summary.verifier),
      target: "只在冻结的旧组织里出现",
      whenToStart: "—",
      outputs: "—",
      relationText: "—",
      modelText,
      modelSourceText,
      originKind,
      originLabel: `${ORIGIN_LABELS[originKind]}${suffix}`,
      runningItemsCount: summary.running_items ?? 0,
      clickable: originKind !== "running_item",
    });
  }

  return rows;
}

function formatDiffItem(diff: FormDifference): string {
  const before = diff.before || "空";
  const after = diff.after || "空";
  return `${diff.item}：${before} → ${after}`;
}

type CandidateEvidenceEntry = string | { label?: string; summary?: string; detail?: string };

/** 解析可选待采用候选；未提供或为空时返回空数组。 */
export function pendingCandidates(
  organization: ProjectOrganizationSnapshot | null,
): OrgCandidateView[] {
  const list: readonly OrganizationCandidate[] | undefined = organization?.candidates;
  if (!Array.isArray(list) || list.length === 0) return [];
  return list.map((item: OrganizationCandidate, idx: number) => {
    const rawDiffs = item.diff ?? item.changes ?? [];
    const diffLines = rawDiffs.map(formatDiffItem);
    const evidence: readonly CandidateEvidenceEntry[] = item.evidence ?? [];
    const evidenceLines = evidence
      .map((entry: CandidateEvidenceEntry) => {
        if (typeof entry === "string") return entry;
        return [entry.label, entry.summary, entry.detail].filter(Boolean).join("：");
      })
      .filter(Boolean);
    return {
      key: item.id || `candidate-${idx}`,
      title: item.title || `候选 ${idx + 1}`,
      summary: item.summary || item.reason || "",
      diffLines,
      evidenceLines,
    };
  });
}

function historyEventSortMs(entry: FormChange): number {
  const parsed = Date.parse(entry.at);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** 按时间倒序排列采用历史；最新一条标「现在」，更早条目可「改回这一份」。 */
export function orgHistoryRows(organization: ProjectOrganizationResult): OrgHistoryRow[] {
  const indexed = organization.history.map((entry, idx) => ({ entry, idx }));
  indexed.sort((a, b) => {
    const diffMs = historyEventSortMs(b.entry) - historyEventSortMs(a.entry);
    if (diffMs !== 0) return diffMs;
    return b.idx - a.idx;
  });

  return indexed.map(({ entry }, pos) => {
    const isCurrent = pos === 0;
    const prevFormLabel = formLabelById(entry.previous_form, organization.forms);
    const currFormLabel = formLabelById(entry.form, organization.forms);
    return {
      eventId: entry.event_id,
      atText: formatTime(entry.at) || entry.at,
      actorLabel: actorText(entry.actor),
      previousFormId: entry.previous_form,
      previousFormLabel: prevFormLabel,
      formId: entry.form,
      formLabel: currFormLabel,
      previousVersion: entry.previous_version || "—",
      version: entry.version || "—",
      reason: entry.reason || "未填写原因",
      diffLines: (entry.diff ?? []).map(formatDiffItem),
      changes: entry.changes ?? {},
      isCurrent,
      canRevert: !isCurrent,
    };
  });
}

function compareDraftOrganizations(
  currentOrg: DraftOrganization | null | undefined,
  targetOrg: DraftOrganization | null | undefined,
): string[] {
  if (!currentOrg || !targetOrg) return [];
  const diffs: string[] = [];

  if (currentOrg.form !== targetOrg.form) {
    diffs.push(`形态：${currentOrg.form} → ${targetOrg.form}`);
  }
  const currRouting = rotationText(currentOrg.routing, currentOrg.routing_label);
  const nextRouting = rotationText(targetOrg.routing, targetOrg.routing_label);
  if (currRouting !== nextRouting) {
    diffs.push(`轮转方式：${currRouting} → ${nextRouting}`);
  }

  const currVer = orgQuestions(currentOrg).howEnds;
  const nextVer = orgQuestions(targetOrg).howEnds;
  if (currVer !== nextVer) {
    diffs.push(`结束条件：${currVer} → ${nextVer}`);
  }

  const currDepts = new Map(currentOrg.departments.map((d) => [d.id, d]));
  const nextDepts = new Map(targetOrg.departments.map((d) => [d.id, d]));
  for (const [id, nextDept] of nextDepts.entries()) {
    const prevDept = currDepts.get(id);
    if (!prevDept) {
      diffs.push(`职能新增：${nextDept.label}（${id}）`);
      continue;
    }
    if (prevDept.verifier !== nextDept.verifier) {
      diffs.push(
        `${nextDept.label} 核验标记：${prevDept.verifier ? "核验角色" : "普通职能"} → ${nextDept.verifier ? "核验角色" : "普通职能"}`,
      );
    }
    if (prevDept.target !== nextDept.target) {
      diffs.push(`${nextDept.label} 职责：${prevDept.target || "空"} → ${nextDept.target || "空"}`);
    }
    const prevWatched = prevDept.watched.join("、") || "无";
    const nextWatched = nextDept.watched.join("、") || "无";
    if (prevWatched !== nextWatched) {
      diffs.push(`${nextDept.label} 监听：${prevWatched} → ${nextWatched}`);
    }
  }
  for (const [id, prevDept] of currDepts.entries()) {
    if (!nextDepts.has(id)) {
      diffs.push(`职能移除：${prevDept.label}（${id}）`);
    }
  }

  const currSources = JSON.stringify(currentOrg.sources ?? {});
  const nextSources = JSON.stringify(targetOrg.sources ?? {});
  if (currSources !== nextSources) {
    diffs.push("事项入口分配变化");
  }

  return diffs;
}

function reminderText(reminder: DraftReminder): string {
  return reminder.message || reminder.kind;
}

/** 构造调用 `organization.draft` 的参数（用于历史改回预览，changes 序列化为 JSON 字符串）。 */
export function revertDraftParams(projectId: string, row: OrgHistoryRow): {
  project_id: string;
  form: string;
  changes: string;
} {
  return {
    project_id: projectId,
    form: row.formId,
    changes: JSON.stringify(row.changes ?? {}),
  };
}

/** 生成历史「改回这一份」确认弹窗所需差异、丢弃项与结束条件预览。 */
export function revertConfirmView(input: {
  row: OrgHistoryRow;
  currentOrganization: DraftOrganization | null | undefined;
  draft: OrganizationDraftResult | null;
}): OrgRevertPreview {
  const { row, currentOrganization, draft } = input;
  const targetOrg = draft?.organization ?? null;
  const computedDiffs = compareDraftOrganizations(currentOrganization, targetOrg);
  const diffLines =
    computedDiffs.length > 0
      ? computedDiffs
      : row.diffLines.length > 0
        ? row.diffLines.map((line) => `该历史记录曾变更：${line}`)
        : ["该历史份与当前结构一致，确认后会按该版本记录重新采用"];

  const rejections = (draft?.rejections ?? []).map((item) => item.message || item.item);
  const reminders = (draft?.reminders ?? []).map(reminderText);
  const isOpenLoop = draft?.open_loop ?? (targetOrg ? targetOrg.verification.length === 0 : false);
  const finishesText =
    draft?.finishes ||
    (targetOrg ? orgQuestions(targetOrg).howEnds : isOpenLoop ? "开环完成：没有人核验" : "核验放行后完成");

  return {
    targetFormLabel: row.formLabel,
    targetVersion: row.version,
    diffLines,
    discarded: discardedLines(draft?.discarded ?? []),
    finishesText,
    isOpenLoop,
    rejections,
    reminders,
    blocked: rejections.length > 0 || targetOrg === null,
  };
}

/** 构造历史「改回这一份」确认后直接提交给 `organization.adopt` 的请求体。 */
export function revertAdoptPayload(input: {
  projectId: string;
  row: OrgHistoryRow;
  baseVersion: string | null | undefined;
  reason?: string;
}): {
  project_id: string;
  form: string;
  changes: Record<string, unknown>;
  reason: string;
  base_version?: string;
  mode: "advanced";
} {
  const defaultReason = `从历史版本 ${input.row.version}（${input.row.formLabel}）改回`;
  const trimmed = (input.reason ?? "").trim() || defaultReason;
  return {
    project_id: input.projectId,
    form: input.row.formId,
    changes: input.row.changes,
    reason: trimmed,
    ...(input.baseVersion ? { base_version: input.baseVersion } : {}),
    mode: "advanced",
  };
}

/** 将命令冲突或失败转换为清晰中文反馈，并在 `stale_base` 时提示已刷新组织。 */
export function formatOrgCommandProblem(problem: CommandProblem): {
  message: string;
  refreshed: boolean;
} {
  if (needsRefresh(problem) && problem.kind === "rejected") {
    const versionHint = problem.rejection.current_version
      ? `（当前版本已变为 ${problem.rejection.current_version}）`
      : "";
    return {
      message: `${reasonText(problem.rejection.reason)}：${problem.rejection.message}${versionHint}。已自动刷新项目组织，请核对最新内容后再决定是否继续。`,
      refreshed: true,
    };
  }
  if (problem.kind === "rejected") {
    return {
      message: `${reasonText(problem.rejection.reason)}：${problem.rejection.message}`,
      refreshed: false,
    };
  }
  if (problem.kind === "invalid") {
    return {
      message: problem.note || "提交内容有误，请检查后重试",
      refreshed: false,
    };
  }
  return {
    message: problem.status > 0 ? `这次请求没有成功（状态码 ${problem.status}）` : "这次请求没有成功，请检查连接",
    refreshed: false,
  };
}
