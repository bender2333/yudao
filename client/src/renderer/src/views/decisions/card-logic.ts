// 决定卡片的材料整理（原型 v8 设计说明第 6 节，原型 v10 的 Y10.cards.materialRows 与 Y10.cards.face）。
// 首页与项目页面共用一份整理逻辑：卡片显示的材料与给像素画面用的纯文字版本由同一个函数产出，
// 材料按决定种类从决定请求携带的事实里读出。这里是纯函数，界面与单元测试都直接调用。

import type { DecisionView } from "../../api/generated/types.gen";
import { paths } from "../../shell/routing.ts";
import { DECISION_KIND, DECISION_REASON, STOP_REASON, label } from "../project/labels.ts";

export type MaterialRow = { term: string; value: string };
export type MaterialLink = { label: string; href: string };

export type DecisionLike = {
  decision_id: string;
  kind: string;
  blocks?: string;
  status: string;
  version: number;
  requested_at: string;
  blocked?: { work_item_id: string | null; queued_after: number } | null;
  request?: unknown;
  answer?: {
    option?: string | null;
    note?: string | null;
    answers?: Record<string, string> | null;
    answered_at?: string | null;
  } | null;
};

export interface RoleChoiceOptionView {
  id: string;
  label: string;
  description: string | null;
  recommended: boolean;
}

export interface RoleChoiceQuestionView {
  id: string;
  question: string;
  options: RoleChoiceOptionView[];
  recommended: string;
  rationale: string;
}

export interface RoleChoiceActions {
  submitLabel: string;
  recommendedLabel: string;
  submitNoteRequired: boolean;
  recommendedNoteRequired: boolean;
}

export type RoleChoiceAnswerArgs = {
  decision_id: string;
  option: "submit" | "recommended";
  base_version: number;
  answers?: Record<string, string>;
  note?: string;
};

export interface RoleChoiceAnsweredItem {
  questionId: string;
  question: string;
  optionId: string;
  optionLabel: string;
  optionDescription: string | null;
  recommended: boolean;
}

export interface RoleChoiceAnsweredView {
  actionLabel: string;
  items: RoleChoiceAnsweredItem[];
  note: string;
  summaryText: string;
}

// 决定请求的载荷：决定请求携带的材料与选项（类型由生成的合同给出，未知种类按原样显示）
type Payload = Record<string, unknown>;

const DEPARTMENT_NAMES: Record<string, string> = { product: "产品", engineering: "工程", quality: "质检", operations: "运维" };

/** 解析多题 role_choice 决定请求中的有效题目列表；非 role_choice 或题表为空时返回空数组。 */
export function roleChoiceQuestions(
  decision: Pick<DecisionLike, "kind" | "request">,
): RoleChoiceQuestionView[] {
  if (decision.kind !== "role_choice") {
    return [];
  }
  const request = (decision.request ?? {}) as Payload;
  if (!Array.isArray(request.questions) || request.questions.length === 0) {
    return [];
  }
  const questions: RoleChoiceQuestionView[] = [];
  for (const raw of request.questions) {
    if (raw === null || typeof raw !== "object") {
      continue;
    }
    const entry = raw as Payload;
    const id = typeof entry.id === "string" ? entry.id.trim() : "";
    const question = typeof entry.question === "string" ? entry.question.trim() : "";
    const recommended = typeof entry.recommended === "string" ? entry.recommended.trim() : "";
    const rationale = typeof entry.rationale === "string" ? entry.rationale.trim() : "";
    if (id === "" || question === "" || !Array.isArray(entry.options)) {
      continue;
    }
    const options: RoleChoiceOptionView[] = [];
    for (const rawOption of entry.options) {
      if (rawOption === null || typeof rawOption !== "object") {
        continue;
      }
      const opt = rawOption as Payload;
      const optId = typeof opt.id === "string" ? opt.id.trim() : "";
      const optLabel = typeof opt.label === "string" ? opt.label.trim() : "";
      if (optId === "" || optLabel === "") {
        continue;
      }
      const description = typeof opt.description === "string" && opt.description.trim() !== ""
        ? opt.description.trim()
        : null;
      options.push({
        id: optId,
        label: optLabel,
        description,
        recommended: optId === recommended,
      });
    }
    if (options.length === 0) {
      continue;
    }
    questions.push({ id, question, options, recommended, rationale });
  }
  return questions;
}

/** 从 role_choice 决定请求提取提交动作按钮文案与说明必填标记。 */
export function roleChoiceActions(decision: Pick<DecisionLike, "request">): RoleChoiceActions {
  const request = (decision.request ?? {}) as Payload;
  const rawOptions = Array.isArray(request.options) ? request.options : [];
  const find = (id: string, fallback: string): { label: string; noteRequired: boolean } => {
    for (const raw of rawOptions) {
      if (raw !== null && typeof raw === "object") {
        const entry = raw as Payload;
        if (entry.id === id) {
          const textValue = typeof entry.label === "string" && entry.label.trim() !== ""
            ? entry.label.trim()
            : fallback;
          return { label: textValue, noteRequired: Boolean(entry.note_required) };
        }
      }
    }
    return { label: fallback, noteRequired: false };
  };
  const submit = find("submit", "提交回答");
  const recommended = find("recommended", "全部采用推荐");
  return {
    submitLabel: submit.label,
    recommendedLabel: recommended.label,
    submitNoteRequired: submit.noteRequired,
    recommendedNoteRequired: recommended.noteRequired,
  };
}

/** 按每题 recommended 生成默认逐题预选映射。 */
export function defaultRoleChoiceAnswers(questions: readonly RoleChoiceQuestionView[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const item of questions) {
    const valid = item.options.some((opt) => opt.id === item.recommended)
      ? item.recommended
      : item.options[0]?.id ?? "";
    if (valid !== "") {
      result[item.id] = valid;
    }
  }
  return result;
}

/** 题表刷新时保留仍有效的已选答案，缺省题目回落到默认推荐选项。 */
export function reconcileRoleChoiceAnswers(
  questions: readonly RoleChoiceQuestionView[],
  current: Record<string, string>,
): Record<string, string> {
  const defaults = defaultRoleChoiceAnswers(questions);
  const next: Record<string, string> = {};
  for (const item of questions) {
    const picked = current[item.id];
    if (typeof picked === "string" && item.options.some((opt) => opt.id === picked)) {
      next[item.id] = picked;
    } else if (defaults[item.id] !== undefined) {
      next[item.id] = defaults[item.id];
    }
  }
  return next;
}

/** 组装 role_choice 的 decision.answer 提交参数：提交回答带逐题 answers，全部采用推荐不附带 answers。 */
export function buildRoleChoiceAnswerArgs(
  decision: Pick<DecisionLike, "decision_id" | "kind" | "version" | "request">,
  action: "submit" | "recommended",
  selected: Record<string, string>,
  note: string,
): RoleChoiceAnswerArgs {
  const questions = roleChoiceQuestions(decision);
  const trimmed = note.trim();
  if (action === "recommended") {
    return {
      decision_id: decision.decision_id,
      option: "recommended",
      ...(trimmed === "" ? {} : { note: trimmed }),
      base_version: decision.version,
    };
  }
  return {
    decision_id: decision.decision_id,
    option: "submit",
    answers: reconcileRoleChoiceAnswers(questions, selected),
    ...(trimmed === "" ? {} : { note: trimmed }),
    base_version: decision.version,
  };
}

/** 校验并组装 role_choice 提交参数，供决定卡片与对话线程气泡共用。 */
export function prepareRoleChoiceSubmit(
  decision: Pick<DecisionLike, "decision_id" | "kind" | "version" | "request">,
  actions: RoleChoiceActions,
  action: "submit" | "recommended",
  selected: Record<string, string>,
  note: string,
): { missing: string; payload: RoleChoiceAnswerArgs | null } {
  const missing = missingNoteText(
    action === "submit"
      ? { label: actions.submitLabel, note_required: actions.submitNoteRequired }
      : { label: actions.recommendedLabel, note_required: actions.recommendedNoteRequired },
    note,
  );
  if (missing !== "") {
    return { missing, payload: null };
  }
  return { missing: "", payload: buildRoleChoiceAnswerArgs(decision, action, selected, note) };
}

/** 对照 answer.answers 与 request.questions 生成已回答多题的逐题选项名称与补充说明。 */
export function answeredRoleChoiceSummary(
  decision: Pick<DecisionLike, "kind" | "request" | "answer">,
): RoleChoiceAnsweredView | null {
  const questions = roleChoiceQuestions(decision);
  if (questions.length === 0) {
    return null;
  }
  const answer = decision.answer ?? null;
  const rawAnswers = answer?.answers ?? null;
  const usedRecommendedAll = answer?.option === "recommended";
  const items: RoleChoiceAnsweredItem[] = questions.map((item) => {
    const rawChoice = rawAnswers && typeof rawAnswers[item.id] === "string" ? rawAnswers[item.id] : "";
    const chosenId = rawChoice !== "" ? rawChoice : (usedRecommendedAll ? item.recommended : "");
    const chosenOption = item.options.find((opt) => opt.id === chosenId) ?? null;
    const optionLabel = chosenOption?.label ?? (chosenId !== "" ? chosenId : "未写明选择");
    return {
      questionId: item.id,
      question: item.question,
      optionId: chosenId,
      optionLabel,
      optionDescription: chosenOption?.description ?? null,
      recommended: chosenId !== "" && chosenId === item.recommended,
    };
  });
  const note = typeof answer?.note === "string" ? answer.note.trim() : "";
  const actionLabel = usedRecommendedAll ? "全部采用推荐" : "逐题回答";
  const summaryText = items.map((entry) => `${entry.question}：${entry.optionLabel}`).join("；");
  return { actionLabel, items, note, summaryText };
}

// 等待时长：从发出时间到现在，按秒向上取整（界面不自行推进状态，取的是当前时间与发出时间的差）
export function waitedSeconds(requestedAt: string, now: number): number {
  const requested = new Date(requestedAt).getTime();
  if (Number.isNaN(requested)) {
    return 0;
  }
  return Math.max(0, Math.round((now - requested) / 1000));
}

// 初始 PRD 的材料（第 138 号工单，设计第 3.2 节）：PRD 摘要与工件引用、现有结构说明、
// 基线核验汇总、快照来源与轮次。上一轮的修改意见原文由卡片按事项补一行（工单 #138），
// 修改意见的工件路径是内部引用，不显示给用户。
// 载荷由 InitialPrdRequested 给出，每一项都按接口合同的原样显示，没有上报的项目写「未上报」。
function initialPrdRows(request: Payload, push: (term: string, value: unknown) => void): void {
  const prd = (request.prd ?? {}) as Payload;
  const structure = (request.structure ?? {}) as Payload;
  const review = (request.baseline_review ?? {}) as Payload;
  const snapshot = (request.snapshot ?? {}) as Payload;
  push("轮次", `第 ${typeof request.round === "number" ? request.round : "?"} 轮`);
  push("初始 PRD 摘要", showText(prd.summary, "没有摘要"));
  push("PRD.md 工件", refPath(prd.prd_ref));
  push("PRD 指纹", fingerprint(prd.content_hash));
  // 要求与验收标准的对应声明（工单 #1349）：每条要求一行，值是对应的 AC 位置，写不出验收标准的写 gap 原因
  for (const row of requirementRows(prd)) {
    push(row.term, row.value);
  }
  push("现有结构说明", refPath(structure.structure_ref));
  push("结构说明指纹", fingerprint(structure.code_tree_digest));
  push("基线核验汇总", baselineSummary(review));
  push("快照来源", showText(snapshot.source, "未上报"));
  push("快照提交", provenanceText(snapshot.provenance));
  push("快照规模", `文件 ${countText(snapshot.files)} 项，目录 ${countText(snapshot.directories)} 项，共 ${bytesText(snapshot.bytes)} 字节`);
}

// 初始 PRD 的要求与验收标准的对应声明（工单 #1349）：逐条要求一行，值是对应的 AC 位置；
// 写不出验收标准的要求写它标明的 gap 原因；旧事件的 prd 没有这三项时不出这些行
function requirementRows(prd: Payload): MaterialRow[] {
  const requirements = Array.isArray(prd.requirements) ? prd.requirements : [];
  const mapping = Array.isArray(prd.requirement_mapping) ? prd.requirement_mapping : [];
  const rows: MaterialRow[] = [];
  for (const item of mapping) {
    const entry = (item ?? {}) as Payload;
    const position = typeof entry.requirement === "number" ? entry.requirement : 0;
    if (position <= 0) {
      continue;
    }
    const refs = Array.isArray(entry.criteria) ? entry.criteria.map((ref) => String(ref)) : [];
    const gap = showText(entry.gap, "");
    const value = refs.length > 0 ? refs.join("、") : gap !== "" ? `未写验收标准：${gap}` : "没有对应声明";
    const requirement = showText(requirements[position - 1], "");
    rows.push({ term: `要求 ${position}`, value: requirement === "" ? value : `${value}（${requirement}）` });
  }
  return rows;
}

// 工件引用给出的路径：引用的 path 就是工件的相对路径（PRD.md 与 STRUCTURE.md 按它显示）
function refPath(value: unknown): string {
  const ref = (value ?? {}) as Payload;
  return showText(ref.path, "未上报");
}

// 指纹只显示前 12 位：完整值由资料页按轮的原始材料给出
function fingerprint(value: unknown): string {
  const shown = showText(value, "");
  return shown === "" ? "未上报" : shown.slice(0, 12);
}

// 空值与空串写成给定的占位文字：界面不补造内容
function showText(value: unknown, empty: string): string {
  return typeof value === "string" && value.trim() !== "" ? value : empty;
}

// 快照的 git 来源（harness/projects.py 给项目上下文的同一份文案）：没有仓库时写明采集时的目录内容
function provenanceText(value: unknown): string {
  const provenance = (value ?? {}) as Payload;
  const commit = showText(provenance.commit, "");
  if (commit === "") {
    return "没有 git 仓库，快照采集时的目录内容";
  }
  const branch = showText(provenance.branch, "未知");
  return `git 提交 ${commit}（分支 ${branch}，${provenance.dirty ? "有未提交的修改" : "没有未提交的修改"}）`;
}

// 基线核验汇总（设计第 3.2 节）：按核实结果分组的条数、现有缺陷、遗漏的能力与其他失败
function baselineSummary(review: Payload): string {
  const conclusions = listOf(review.conclusions);
  const counts: Record<string, number> = {};
  for (const item of conclusions) {
    const status = text(item.status);
    if (status !== "") {
      counts[status] = (counts[status] ?? 0) + 1;
    }
  }
  const names: Record<string, string> = {
    verified: "已核实", read_only: "只读", existing_defect: "现有缺陷", unsupported: "不支持",
  };
  const parts = [`核验 ${conclusions.length} 条要求`];
  for (const status of Object.keys(names)) {
    const count = counts[status];
    if (count !== undefined) {
      parts.push(`${names[status]} ${count} 条`);
    }
  }
  parts.push(`遗漏的能力 ${listOf(review.omissions).length} 条`);
  parts.push(`其他失败 ${listOf(review.other_failures).length} 条`);
  return parts.join("；");
}

function listOf(value: unknown): Payload[] {
  return Array.isArray(value) ? value.filter((item): item is Payload => item !== null && typeof item === "object") : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function countText(value: unknown): string {
  return Array.isArray(value) ? String(value.length) : "未上报";
}

function bytesText(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN") : "未上报";
}

// 每种决定请求需要的材料：来源是决定请求的载荷（原型 v8 设计说明第 6 节的表）。
// 种类在合同里以后增加时，把它的材料写在这里；未知种类返回空表，不伪造内容。
export function materialRows(decision: DecisionView): MaterialRow[] {
  const request = (decision.request ?? {}) as Payload;
  const rows: MaterialRow[] = [];
  const push = (term: string, value: unknown) => {
    const shown = typeof value === "number" ? String(value) : typeof value === "string" ? value : "";
    if (shown !== "") {
      rows.push({ term, value: shown });
    }
  };
  const dept = (value: unknown) => {
    const key = typeof value === "string" ? value : "";
    return key === "" ? "" : DEPARTMENT_NAMES[key] ?? key;
  };
  switch (decision.kind) {
    case "model_unavailable":
      push("职能", dept(request.department));
      push("模型", (request.target as Payload | null | undefined)?.model_id);
      push("具体问题", request.message);
      // 原因按中文写（工单 #181）：provider_unavailable 这样的机器标识不写进页面
      push("原因", typeof request.reason === "string" && request.reason !== ""
        ? label(DECISION_REASON, request.reason) : "");
      break;
    case "no_tool_call":
    case "workspace_unrepresentable":
      push("职能", dept(request.department));
      push("停止原因", typeof request.stop_reason === "string" && request.stop_reason !== ""
        ? label(STOP_REASON, request.stop_reason) : "");
      break;
    case "kernel_modification":
      push("改动的内核路径", Array.isArray(request.kernel_paths) ? request.kernel_paths.join("\n") : "");
      push("差异", request.diff);
      break;
    case "qa_cannot_verify":
      // 质检无法核验（浏览器与 computer use docs/design/browser-and-computer-use.md「无法核验」，工单 #1179）：逐条列出无法核验的
      // 验收条件与原因，再列出「重新核验」「停止事项」两个选项的说明
      push("职能", dept(request.department));
      for (const row of Array.isArray(request.criteria) ? request.criteria : []) {
        const entry = row as Payload;
        push(String(entry.criterion ?? ""), String(entry.note ?? "没有写原因"));
      }
      break;
    case "initial_prd":
      initialPrdRows(request, push);
      break;
    case "role_choice":
      push("职能", dept(request.department));
      if (typeof request.round === "number" && Number.isFinite(request.round)) {
        push("轮次", `第 ${request.round} 轮`);
      }
      if (typeof request.note === "string" && request.note.trim() !== "") {
        push("补充提示", request.note.trim());
      }
      break;
    default:
      break;
  }
  // 决定请求自带的说明按行列出，保证任何种类都能看到请求给出的说明
  push("说明", request.description);
  return rows;
}

// 「在项目中查看」与材料里的跳转：决定请求给出目标页面，没有时按种类落到对应页面
export function decisionLinks(decision: DecisionView): MaterialLink[] {
  const request = (decision.request ?? {}) as Payload;
  const links: MaterialLink[] = [];
  // 待恢复的决定：前往模型管理与本项目的职能详情（工单 #1161、#1713）。
  // #1713 起「职能设置」一节不再在设置页上，模型与 Prompt 在职能详情页改：
  // 请求给出了部门就落到那个部门的详情页，没有部门时落到对话页（这一页始终有）
  if (decision.kind === "model_unavailable") {
    links.push({ label: "前往模型管理", href: "#/sys/models" });
    if (decision.project_id) {
      const department = typeof request.department === "string" ? request.department : "";
      const href = department === ""
        ? paths.conversation(decision.project_id, { workItem: decision.work_item_id })
        : paths.departmentDetail(decision.project_id, department, { workItem: decision.work_item_id });
      links.push({ label: "前往本项目的职能详情", href });
    }
  }
  // 初始 PRD 的两个工件：资料页收进对话以后（工单 #1715），PRD.md 与 STRUCTURE.md 落在建档事项的对话页——
  // 建档各轮的初始 PRD 与结构说明在「建档事项的初始 PRD」那条箭头的面板里逐轮看
  const prd = decision.kind === "initial_prd" ? initialPrdHref(decision) : null;
  if (prd !== null) {
    for (const fileName of ["PRD.md", "STRUCTURE.md"]) {
      links.push({ label: fileName, href: prd });
    }
  }
  // 请求显式给出的页面（合同以后增加时也生效）
  const target = typeof request.view === "string" ? request.view : "";
  if (target !== "") {
    links.push({ label: "在项目中查看", href: target });
  }
  return links;
}

// 初始 PRD 决定所属事项的对话页（工单 #1715）：资料页并进对话以后，建档的工件在箭头面板里看，
// 链接落到事项范围的对话页；请求里写了事项就用它，没有时用决定自己的事项。
function initialPrdHref(decision: DecisionView): string | null {
  const request = (decision.request ?? {}) as Payload;
  if (decision.project_id === null) {
    return null;
  }
  const workItem = typeof request.work_item_id === "string" ? request.work_item_id : decision.work_item_id;
  return paths.conversation(decision.project_id, { workItem: workItem === "" ? null : workItem });
}

// 「在项目中查看」的目标：请求给出 view 时用它；结果未知的动作落到恢复页；其余落到那件事项的对话页
// （工单 #1715：概览页收进对话，没有事项时落到项目的对话页）
export function viewHref(decision: DecisionView): string | null {
  const request = (decision.request ?? {}) as Payload;
  if (typeof request.view === "string" && request.view !== "") {
    return request.view;
  }
  if (decision.project_id === null) {
    return null;
  }
  // 初始 PRD 的确认：各轮的初始 PRD 与确认记录在建档事项的对话页、那条箭头的面板里（工单 #138、#1715）
  if (decision.kind === "initial_prd") {
    return initialPrdHref(decision);
  }
  if (decision.kind === "role_choice") {
    return paths.conversation(decision.project_id, { workItem: decision.work_item_id });
  }
  if (decision.work_item_id !== null) {
    return `#/p/${decision.project_id}/w/${decision.work_item_id}/recovery`;
  }
  return paths.conversation(decision.project_id);
}

// 挡住了什么：被阻塞的事项，以及同一项目中排在它后面的事项数量（v8 第 6 节）。
// 不挡住任何事项的请求按 muted 显示（例如不阻塞的已阅通知）。
// 阻塞范围为 round（role_choice）时只暂停发出方的本轮工作，其余职能与事项照常推进。
// 被挡住的事项写标题，不写事项标识（工单 #802，原型 v11 的 Y11.ui.cards.blocksText 同一写法）：
// 标题由调用处按项目的事项列表解析；挡住的事项就是决定请求所属的事项
// （服务端按这个事项给出挡住的对象，harness/app/decision_queries.py 的 _blocked），
// 取不到标题时写「挡住本事项」，不拿标识凑数。
export function blockedText(
  decision: Pick<DecisionLike, "blocks" | "blocked" | "request">,
  workItemTitle = "",
): { text: string; muted: boolean } {
  if (decision.blocks === "") {
    return { text: "不挡住事项", muted: true };
  }
  if (decision.blocks === "round") {
    const request = (decision.request ?? {}) as Payload;
    const rawDept = typeof request.department === "string" ? request.department.trim() : "";
    const deptLabel = rawDept === "" ? "" : (DEPARTMENT_NAMES[rawDept] ?? rawDept);
    const title = workItemTitle.trim();
    const scope = title === ""
      ? (deptLabel === "" ? "发起方的本轮工作" : `${deptLabel}的本轮工作`)
      : (deptLabel === "" ? `「${title}」中发起方的本轮工作` : `「${title}」中${deptLabel}的本轮工作`);
    return { text: `仅暂停${scope}，其余职能与事项照常推进`, muted: false };
  }
  if (decision.blocked === null || decision.blocked === undefined) {
    return { text: "不挡住事项", muted: true };
  }
  const parts: string[] = [];
  const title = workItemTitle.trim();
  if (title !== "") {
    parts.push(`挡住「${title}」`);
  }
  if (decision.blocked.queued_after > 0) {
    parts.push(`同一项目中排在它后面的事项 ${decision.blocked.queued_after} 个`);
  }
  return { text: parts.length === 0 ? "挡住本事项" : parts.join("，"), muted: false };
}

// 决定卡片头的一行：项目名与事项标题（工单 #802，原型 v11 的 Y11.ui.cards.render 同一写法）。
// 事项标题由调用处按项目的事项列表解析；取不到时只写项目名，不写事项标识——
// 页面上不出现内部标识（事项范围那一处的做法一样，views/project/scope-name.ts）。
export function metaLine(
  decision: DecisionView,
  names: { projectName: string; workItemTitle: string },
): string {
  const project = names.projectName || decision.project_id || "项目流";
  const item = names.workItemTitle.trim();
  return item === "" ? project : `${project} · ${item}`;
}

// 给像素画面用的纯文字版本（原型 v10 的 Y10.cards.face）：与页面卡片同一份材料，不含界面元素。
// where 是「项目 · 事项」，由调用处按快照把标识解析成名称；解析不到时不写标识（工单 #802）。
// options 保留 note_required（原型选项的标记）：为真时，没有写说明就不提交。
export function face(
  decision: DecisionView,
  now: number,
  names?: { projectName: string; workItemTitle: string },
): {
  id: string;
  kind: string;
  version: number;
  title: string;
  work_item_id: string | null;
  where: string;
  waited: string;
  blocks: string;
  rows: MaterialRow[];
  links: MaterialLink[];
  options: { id: string; label: string; note_required: boolean }[];
} {
  const request = (decision.request ?? {}) as Record<string, unknown>;
  const options = (request.options ?? []) as { id: string; label: string; note_required?: boolean }[];
  return {
    id: decision.decision_id,
    kind: decision.kind,
    version: decision.version,
    title: label(DECISION_KIND, decision.kind),
    work_item_id: decision.work_item_id,
    where: metaLine(decision, { projectName: names?.projectName ?? "", workItemTitle: names?.workItemTitle ?? "" }),
    waited: `已等待 ${waitedSeconds(decision.requested_at, now)} 秒`,
    blocks: blockedText(decision, names?.workItemTitle ?? "").text,
    rows: materialRows(decision),
    links: decisionLinks(decision),
    options: options.map((option) => ({ id: option.id, label: option.label, note_required: Boolean(option.note_required) })),
  };
}

// 选项要求写说明时，没有说明的回答不提交：返回要显示的提示，可以提交时返回空串。
// 像素画面（pixel/floor/card.ts）与页面卡片（views/decisions/card.tsx）都按这条规则处理，
// 提示由同一个函数给出，两处的文字不会分叉。
export function missingNoteText(option: { label: string; note_required?: boolean }, note: string): string {
  if (option.note_required && note.trim() === "") {
    return `「${option.label}」需要在说明里写明修改意见`;
  }
  return "";
}

// 等待回答的请求按发出时间排列（v8 第 4.3 节：跨项目，按发出时间）
export function sortByRequested(decisions: DecisionView[]): DecisionView[] {
  return [...decisions].sort((a, b) => {
    const left = new Date(a.requested_at).getTime();
    const right = new Date(b.requested_at).getTime();
    return (Number.isNaN(left) ? 0 : left) - (Number.isNaN(right) ? 0 : right);
  });
}
