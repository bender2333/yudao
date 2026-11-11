// 箭头面板里的各段（工单 #1711）。
//
// 设计说明 docs/design/project-organization.md「节点面板与箭头面板接住的内容」把面板按箭头是哪一种
// 成果分成几段，「项目页上的内容在哪里看」给出每一段读哪一条查询；验收见 #1707 的补充条第 15 条。
//
//   从图外进来的箭头      你的输入各版本与处理进度                work_item.inputs
//   成果箭头              那一版、与上一版的差异、文件清单与下载    work_item.materials、delivery.file
//   标着放行或打回的那版  结论、逐条结论、检查回执、缺陷、检验覆盖   work_item.materials、acceptance.coverage
//   建档的初始 PRD 箭头   建档各轮与确认记录                      work_item.materials 的 onboarding_rounds
//   没有核验角色的完成    写「开环完成：没有人核验」，没有结论段
//
// 这里只算文字与结构，arrow-panel.tsx 只按它画。逐条结论的表复用 criteria-table.tsx 的 CriteriaTable，
// 试用用例的细节复用 trials.tsx 的 trialView，两处都不在这里重写。
//
// 引用的模块写成带 .ts 的名字：单元测试用 node --test 直接跑 TypeScript，不带扩展名找不到模块。

import type { AcceptanceCoverageResult, ReviewEntry } from "../../api/generated/types.gen";
import type { LoopArrow } from "./loop-graph-model.ts";
import { SOURCE } from "./loop-graph-model.ts";
import { INPUT_KIND, formatTime, label, verdictName } from "./labels.ts";
import { coverageSummary, criterionRows } from "./materials-read.ts";
import type { TrialCaseRow, TrialsView } from "./trials";

/** 没有核验角色、事项已交完成的那一版写这一句（设计说明「节点面板与箭头面板接住的内容」）。 */
export const OPEN_ENDED_TEXT = "开环完成：没有人核验";
/** 那一版没有附文件清单时写这一句，不写空白。 */
export const NO_FILES_TEXT = "这一版没有附文件清单";
/** 材料里没有这一份结论时写这一句：读不出来与「没有结论」分开写。 */
export const MISSING_REVIEW_TEXT = "材料里没有这一份结论";
/** 逐条结论一条都没有时写这一句（与 CriteriaTable 的表下说明同一句）。 */
export const NO_CRITERIA_TEXT = "这份结论没有逐条结论";

/**
 * 这条箭头是哪一种成果，决定面板里有哪几段。
 * `rounds` 是 materials.onboarding_rounds 的条数：只有建档事项才有建档各轮。
 */
export type ArrowKind = "input" | "onboarding" | "reviewed" | "outcome";

export function arrowKindOf(arrow: LoopArrow, rounds: number): ArrowKind {
  if (arrow.from === SOURCE) {
    return "input";
  }
  if (rounds > 0 && arrow.outcome === "PRD") {
    return "onboarding";
  }
  if (arrow.verdict !== null) {
    return "reviewed";
  }
  return "outcome";
}

// ---------------------------------------------------------------------------
// 同一种成果逐版切

export interface VersionNavView {
  /** 这一版在同一种成果里的第几版，从 1 起 */
  index: number;
  total: number;
  /** 「第 2 / 3 版」 */
  label: string;
  prev: LoopArrow | null;
  next: LoopArrow | null;
}

/** 同一种成果的几版按先后排（versionsOf 已经排好），这里给前后版与「第几版」。 */
export function versionNavOf(versions: readonly LoopArrow[], arrow: LoopArrow): VersionNavView | null {
  if (versions.length < 2) {
    return null;
  }
  const at = versions.findIndex((item) => item.key === arrow.key);
  if (at === -1) {
    return null;
  }
  return {
    index: at + 1,
    total: versions.length,
    label: `第 ${at + 1} / ${versions.length} 版`,
    prev: versions[at - 1] ?? null,
    next: versions[at + 1] ?? null,
  };
}

// ---------------------------------------------------------------------------
// 那一版：文件清单与与上一版的差异

export interface FileDiffView {
  added: string[];
  removed: string[];
  kept: number;
  /** 一句话：与上一版相比新增、减少、没变各几个 */
  text: string;
}

/** 这一版的文件与上一版比：新增哪些、减少哪些、几个没变；第一版没有可比的一版。 */
export function diffFiles(current: readonly string[], previous: readonly string[] | null): FileDiffView | null {
  if (previous === null) {
    return null;
  }
  const was = new Set(previous);
  const now = new Set(current);
  const added = current.filter((path) => !was.has(path));
  const removed = previous.filter((path) => !now.has(path));
  const kept = current.filter((path) => was.has(path)).length;
  if (added.length === 0 && removed.length === 0) {
    return { added, removed, kept, text: `与上一版相比文件没有变化（${kept} 个）` };
  }
  const parts: string[] = [];
  if (added.length > 0) {
    parts.push(`新增 ${added.length} 个：${added.join("、")}`);
  }
  if (removed.length > 0) {
    parts.push(`减少 ${removed.length} 个：${removed.join("、")}`);
  }
  if (kept > 0) {
    parts.push(`没变 ${kept} 个`);
  }
  return { added, removed, kept, text: `与上一版相比 ${parts.join("；")}` };
}

export interface VersionView {
  /** 那一版的版本号：PRD 与交付取材料里的 revision，缺陷记录没有 */
  revision: number | null;
  /** 那一版的一句话：交付的摘要、PRD 的改动说明、缺陷记录的内容 */
  summary: string;
  files: string[];
  /** 与上一版的差异；第一版或没有上一版时为 null */
  diff: FileDiffView | null;
  /** 材料里有这一版（查询读到了）；没有时文件清单退回箭头自带的那几个 */
  loaded: boolean;
}

export interface EntryLike {
  event_id: string;
  revision: number | null;
  summary?: string | null;
  files?: readonly string[];
}

/** work_item.materials 里循环图与面板都用到的那几项（与 loop-graph-model 的 MaterialsView 同形）。 */
export interface MaterialsLike {
  contracts?: readonly EntryLike[];
  deliveries?: readonly EntryLike[];
  reviews?: readonly ReviewEntry[];
  onboarding_rounds?: readonly RoundLike[];
}

/** 材料里这一版那一条：按箭头带的事件编号找，找不到时为空（不按版本号猜，宁可退回箭头自带的）。 */
function entryOf(materials: MaterialsLike | null, arrow: LoopArrow): EntryLike | null {
  if (materials === null || arrow.eventId === null || arrow.eventId === undefined) {
    return null;
  }
  const rows = arrow.outcome === "PRD" ? materials.contracts ?? [] : materials.deliveries ?? [];
  return rows.find((entry) => entry.event_id === arrow.eventId) ?? null;
}

function filesOf(materials: MaterialsLike | null, arrow: LoopArrow): string[] {
  const entry = entryOf(materials, arrow);
  if (entry !== null && entry.files !== undefined && entry.files !== null) {
    return [...entry.files];
  }
  return [...arrow.files];
}

/** 面板上「这一版」一段：版本号、那一版的一句话、文件清单与与上一版的差异。 */
export function versionOf(arrow: LoopArrow, versions: readonly LoopArrow[], materials: MaterialsLike | null): VersionView {
  const entry = entryOf(materials, arrow);
  const files = filesOf(materials, arrow);
  const at = versions.findIndex((item) => item.key === arrow.key);
  const before = at > 0 ? versions[at - 1] ?? null : null;
  const summary = (entry?.summary ?? "").trim();
  return {
    revision: entry?.revision ?? arrow.version,
    summary: summary === "" ? arrow.text : summary,
    files,
    diff: before === null ? null : diffFiles(files, filesOf(materials, before)),
    loaded: entry !== null,
  };
}

// ---------------------------------------------------------------------------
// 从图外进来的箭头：你的输入各版本与处理进度

export interface InputRowView {
  key: string;
  version: number;
  text: string;
  /** 文字 / 命令 */
  kindName: string;
  /** 「12–48 字节」 */
  range: string;
  stateText: string;
  /** 这一版还没处理（版本号大于已处理到的版本） */
  waiting: boolean;
  eventId: string;
}

export interface InputsView {
  /** 一句话：最新第几版、已处理到第几版、还有几版没处理 */
  headline: string;
  rows: InputRowView[];
}

export interface InputsLike {
  input_version: number;
  processed_input_version: number;
  inputs: readonly {
    version: number;
    text: string;
    kind: string;
    byte_start: number;
    byte_end: number;
    created_event_id: string;
  }[];
}

/** 你的输入各版与处理进度，按版本先后排；没有输入时为空（面板不画这一段）。 */
export function inputsView(inputs: InputsLike | null): InputsView | null {
  if (inputs === null || inputs.inputs.length === 0) {
    return null;
  }
  const rows = [...inputs.inputs]
    .sort((left, right) => left.version - right.version)
    .map((item) => {
      const waiting = item.version > inputs.processed_input_version;
      return {
        key: `input-${item.version}`,
        version: item.version,
        text: item.text,
        kindName: label(INPUT_KIND, item.kind),
        range: `${item.byte_start}–${item.byte_end} 字节`,
        stateText: waiting ? "还没处理" : "已处理",
        waiting,
        eventId: item.created_event_id,
      };
    });
  const waiting = rows.filter((row) => row.waiting).length;
  const done = inputs.processed_input_version;
  const headline = waiting === 0
    ? `最新第 ${inputs.input_version} 版，已处理到第 ${done} 版，都处理了`
    : `最新第 ${inputs.input_version} 版，已处理到第 ${done} 版，第 ${done + 1} 版起 ${waiting} 版还没处理`;
  return { headline, rows };
}

// ---------------------------------------------------------------------------
// 标着放行或打回的那一版：结论、逐条结论、检查回执、缺陷、检验覆盖

/** 建档一轮里的确认记录：一条问题回答了什么，或者撤销。 */
export interface RoundDecisionView {
  key: string;
  text: string;
  at: string;
}

export interface RoundView {
  key: string;
  round: number;
  proposedAt: string;
  runId: string;
  prd: string;
  /** 现有结构说明 */
  structure: string;
  revisionNote: string;
  /** 基线核验的几行：核实结果、遗漏的能力、基线检查、其他失败 */
  baseline: string[];
  decisions: RoundDecisionView[];
}

/** 建档一轮里的一条确认记录（onboarding_rounds 的 decisions 的一项）。 */
export interface DecisionLike {
  outcome?: string;
  option?: string;
  note?: string | null;
  reason?: string | null;
  decided_at?: string;
}

export interface RoundLike {
  round: number;
  run_id?: string;
  proposed_at?: string;
  prd?: string;
  structure?: string;
  revision_note?: string | null;
  baseline_review?: {
    conclusions?: readonly { requirement?: string; status?: string; evidence?: string }[];
    omissions?: readonly { capability?: string; location?: string }[];
    checks?: readonly Record<string, unknown>[];
    other_failures?: readonly Record<string, unknown>[];
  } | null;
  decisions?: readonly DecisionLike[];
}

// 与 materials.tsx 的 CONCLUSION_NAMES、ONBOARDING_DECISION_OPTIONS 同一组词：旧资料页不删不改，
// 这两张表在两处各留一份
const BASELINE_CONCLUSION_NAMES: Record<string, string> = {
  verified: "已核实",
  read_only: "只读",
  existing_defect: "现有缺陷",
  unsupported: "不支持",
};

const DECISION_OPTION_NAMES: Record<string, string> = {
  confirm: "确认",
  revise: "提出修改",
};

function words(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** 一条记录写成一行：名字、结果、说明各取第一个有字的字段。 */
function describeRecord(value: Record<string, unknown>): string {
  const parts = [
    words(value["name"]) || words(value["id"]) || words(value["check_id"]),
    words(value["result"]) || words(value["status"]) || words(value["verdict"]),
    words(value["summary"]) || words(value["message"]) || words(value["reason"]),
  ].filter((part) => part !== "");
  return parts.length === 0 ? "没有写明" : parts.join(" · ");
}

function baselineLines(round: RoundLike): string[] {
  const baseline = round.baseline_review ?? null;
  if (baseline === null) {
    return [];
  }
  const lines: string[] = [];
  for (const item of baseline.conclusions ?? []) {
    const status = (item.status ?? "").trim();
    const name = BASELINE_CONCLUSION_NAMES[status] ?? status;
    lines.push(`${name === "" ? "核实结果" : name}：${(item.requirement ?? "").trim()}`);
  }
  for (const item of baseline.omissions ?? []) {
    const location = (item.location ?? "").trim();
    lines.push(`遗漏的能力：${(item.capability ?? "").trim()}${location === "" ? "" : `（${location}）`}`);
  }
  for (const item of baseline.checks ?? []) {
    lines.push(`基线检查 ${describeRecord(item)}`);
  }
  for (const item of baseline.other_failures ?? []) {
    lines.push(`其他失败 ${describeRecord(item)}`);
  }
  return lines;
}

function decisionText(record: DecisionLike): string {
  const option = (record.option ?? "").trim();
  const answer = record.outcome === "withdrawn" ? "撤销" : `回答：${DECISION_OPTION_NAMES[option] ?? option}`;
  const note = (record.note ?? "").trim();
  const reason = (record.reason ?? "").trim();
  const tail = note !== "" ? note : reason;
  return tail === "" ? answer : `${answer} · ${tail}`;
}

/** 建档各轮与确认记录，按轮次先后排；不是建档事项时为空（面板不画这一段）。 */
export function roundsView(materials: MaterialsLike | null): RoundView[] {
  return [...(materials?.onboarding_rounds ?? [])]
    .sort((left, right) => left.round - right.round)
    .map((round) => ({
      key: `round-${round.round}`,
      round: round.round,
      proposedAt: round.proposed_at ?? "",
      runId: round.run_id ?? "",
      prd: round.prd ?? "",
      structure: round.structure ?? "",
      revisionNote: (round.revision_note ?? "").trim(),
      baseline: baselineLines(round),
      decisions: (round.decisions ?? []).map((record, index) => ({
        key: `decision-${round.round}-${index}`,
        text: decisionText(record),
        at: formatTime(record.decided_at ?? ""),
      })),
    }));
}

export interface ConclusionView {
  tone: "release" | "reject";
  /** 「质检放行这一版」/「质检打回这一版」 */
  headline: string;
  /** 结论那一个词：放行 / 缺陷记录 / 无法核验 */
  verdictName: string;
  rationale: string;
  /** 逐条结论的条数 */
  criteriaCount: number;
  /** 检验覆盖那一行；没有对应的放行记录时为 null */
  coverageText: string | null;
  /** 检查回执与缺陷各写成一行 */
  checks: string[];
  defects: string[];
  /** 这一份结论引用的试用用例编号 */
  caseIds: string[];
  reviewEventId: string | null;
  /** 材料里没有这一份结论 */
  missing: boolean;
}

/** 材料里与这一版的语气对得上的那份结论：放行取最后一份放行，打回取最后一份不是放行的。 */
function reviewOf(materials: MaterialsLike | null, tone: "release" | "reject"): ReviewEntry | null {
  const rows = materials?.reviews ?? [];
  const matched = rows.filter((item) => (tone === "release" ? item.verdict === "release" : item.verdict !== "release"));
  return matched.length === 0 ? null : matched[matched.length - 1] ?? null;
}

/**
 * 「标着放行或打回的那一版」一段：结论、逐条结论、检查回执、缺陷与检验覆盖。
 * 箭头没有结论（还没人核验）时为空，面板不画结论段。
 */
export function conclusionOf(
  arrow: LoopArrow,
  materials: MaterialsLike | null,
  coverage: AcceptanceCoverageResult | null,
): ConclusionView | null {
  if (arrow.verdict === null) {
    return null;
  }
  const tone = arrow.verdict.tone;
  const by = arrow.verdict.by;
  const headline = tone === "reject" ? `${by}打回这一版` : `${by}放行这一版`;
  const review = reviewOf(materials, tone);
  if (review === null) {
    return {
      tone, headline, verdictName: "", rationale: "", criteriaCount: 0, coverageText: null,
      checks: [], defects: [], caseIds: [], reviewEventId: null, missing: true,
    };
  }
  // 检验覆盖只与它对应的那一份结论放在一起；旧的缺陷记录不借用最近一份的数
  const matched = coverage !== null && coverage.review_event_id === review.event_id ? coverage : null;
  const rationale = review.rationale.trim();
  return {
    tone,
    headline,
    verdictName: verdictName(review.verdict),
    rationale: rationale === "" ? "没有写明理由" : rationale,
    criteriaCount: criterionRows(review, matched).length,
    coverageText: matched === null ? null : coverageSummary(matched.numbers),
    checks: review.checks.map(describeRecord),
    defects: review.defects.map(describeRecord),
    caseIds: (review.trial_cases ?? []).map((item) => item.case_id),
    reviewEventId: review.event_id,
    missing: false,
  };
}

// ---------------------------------------------------------------------------
// 没有核验角色的完成

export interface OpenEndedInput {
  arrow: LoopArrow;
  versions: readonly LoopArrow[];
  /** 这件事项有没有核验角色（循环图上 verifier 为真的节点） */
  verifier: boolean;
  /** 循环图结束那一端写什么（graph.endText） */
  ended: string;
  conclusion: ConclusionView | null;
}

/**
 * 没有核验角色、事项已交完成的那一版：写「开环完成：没有人核验」，没有结论段。
 * 只看同一种成果的最后一版，中途那几版不算交完成。
 */
export function openEndedOf(input: OpenEndedInput): string | null {
  if (input.verifier || input.conclusion !== null || input.arrow.verdict !== null) {
    return null;
  }
  if (!input.ended.trim().startsWith("开环完成")) {
    return null;
  }
  const last = input.versions[input.versions.length - 1];
  return last !== undefined && last.key === input.arrow.key ? OPEN_ENDED_TEXT : null;
}

// ---------------------------------------------------------------------------
// 逐条结论引用的试用用例：细节从 run.trials 里取，标题与截图点得开

function caseIdOf(row: TrialCaseRow): string {
  // trials.tsx 的行标识是「序号-用例编号」，用例编号里也可能有短横，只切第一个
  const cut = row.key.indexOf("-");
  return cut === -1 ? row.key : row.key.slice(cut + 1);
}

export interface CitedCasesView {
  rows: TrialCaseRow[];
  /** 结论里引用了、这次运行的试用记录里没有的用例编号 */
  missing: string[];
}

/** 结论引用的试用用例，按引用的先后排；用例不在这次运行里时写进 missing。 */
export function citedCasesOf(view: TrialsView | null, caseIds: readonly string[]): CitedCasesView {
  const rows: TrialCaseRow[] = [];
  const missing: string[] = [];
  for (const caseId of caseIds) {
    const found = view === null ? undefined : view.cases.find((item) => caseIdOf(item) === caseId);
    if (found === undefined) {
      missing.push(caseId);
    } else {
      rows.push(found);
    }
  }
  return { rows, missing };
}

// ---------------------------------------------------------------------------
// 一次算完：视图按这份结果画

export interface ArrowPanelInput {
  arrow: LoopArrow;
  /** 同一种成果的几版，按先后（versionsOf 的结果） */
  versions: readonly LoopArrow[];
  materials: MaterialsLike | null;
  inputs: InputsLike | null;
  coverage: AcceptanceCoverageResult | null;
  verifier: boolean;
  ended: string;
}

export interface ArrowPanelView {
  kind: ArrowKind;
  nav: VersionNavView | null;
  version: VersionView;
  /** 「你的输入各版本与处理进度」一段，只有从图外进来的箭头有 */
  inputs: InputsView | null;
  /** 结论一段，只有标着放行或打回的那一版有 */
  conclusion: ConclusionView | null;
  /** 「开环完成：没有人核验」一句，只有没有核验角色的交完成那版有 */
  openEnded: string | null;
  /** 建档各轮，只有建档事项的初始 PRD 箭头有 */
  rounds: RoundView[];
  /** 结论引用的试用用例编号 */
  caseIds: string[];
}

export function arrowPanelView(input: ArrowPanelInput): ArrowPanelView {
  const rounds = roundsView(input.materials);
  const kind = arrowKindOf(input.arrow, rounds.length);
  const conclusion = kind === "reviewed" ? conclusionOf(input.arrow, input.materials, input.coverage) : null;
  return {
    kind,
    nav: versionNavOf(input.versions, input.arrow),
    version: versionOf(input.arrow, input.versions, input.materials),
    inputs: kind === "input" ? inputsView(input.inputs) : null,
    conclusion,
    openEnded: openEndedOf({
      arrow: input.arrow,
      versions: input.versions,
      verifier: input.verifier,
      ended: input.ended,
      conclusion,
    }),
    rounds: kind === "onboarding" ? rounds : [],
    caseIds: conclusion === null ? [] : conclusion.caseIds,
  };
}
