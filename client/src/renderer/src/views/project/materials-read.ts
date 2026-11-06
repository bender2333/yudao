// 资料页读到的内容：读不出来与「本来就没有内容」要分开说（工单 #714）。
// 读取层给出的是「这一处有没有读到」（工单 #728 带出来的失败信息）；读到以后内容为空是另一件事，
// 由调用处按内容自己说。两者在页面上是两句不同的话。

/** 一次读取的结果：读取中、读不出来、读成功但没有数据、读到了。 */
export type ReadView<T> =
  | { kind: "loading" }
  | { kind: "failed"; reason: string }
  | { kind: "empty" }
  | { kind: "ready"; data: T };

/** 一次读取的结果：失败与空分开。 */
export function readView<T>(state: { data: T | null; loading: boolean; error: string | null }): ReadView<T> {
  if (state.error !== null) {
    return { kind: "failed", reason: state.error };
  }
  if (state.data === null) {
    return state.loading ? { kind: "loading" } : { kind: "empty" };
  }
  return { kind: "ready", data: state.data };
}

/** 一段原文的显示：读取中、读不出来、没有原文、有原文。 */
export type OriginalView =
  | { kind: "loading" }
  | { kind: "failed"; reason: string }
  | { kind: "empty" }
  | { kind: "content"; text: string };

/**
 * 一段原文的显示：pick 从读到的数据里取出原文，取不出（空）时是「没有原文」，
 * 读不出来时是「读取失败」——两者不是同一句话（工单 #714）。
 */
export function originalView<T>(
  state: { data: T | null; loading: boolean; error: string | null },
  pick: (data: T) => string,
): OriginalView {
  const view = readView(state);
  if (view.kind !== "ready") {
    return view;
  }
  const content = pick(view.data);
  return content === "" ? { kind: "empty" } : { kind: "content", text: content };
}

// ---------------------------------------------------------------------------
// 质检一项的逐条结论表（工单 #154；浏览器与 computer use 设计说明第 7.3、8.3、8.4 节；
// 验证的独立性设计说明第 7.1 节）
//
// 每条验收条件一行：检验方式与结果写中文，证据是检查名称与试用用例，截图是试用用例各步骤上的
// 工件引用。开环的判定与表头的三个数取自 `acceptance.coverage`（放行记录里一次算好），页面不重算；
// 这也是为什么一条试用用例是不是模型阅读只看查询结果里的 open，不看检验方式。
// 没有放行记录的旧结论按检验方式判断开环：六种方式里只有判定点、人、开环不可执行，其余按可执行。

import type {
  AcceptanceCoverageResult,
  LaunchMethodView,
  ReviewEntry,
  TrialCaseEvidenceView,
} from "../../api/generated/types.gen";
import { CHECK_METHODS, checkMethodName, checkResultKind, checkResultName, launchKindName,
  launchSystemName, trialCaseResultName } from "./labels.ts";

/** 一张截图最多列出的缩略图张数；其余的写明还有多少张（一张用例图可能有几十步）。 */
export const SCREENSHOT_LIMIT = 6;

/** 一张截图的工件引用：查询 evidence.screenshot 时按这四项取内容。 */
export interface ScreenshotRefView {
  kind: string;
  contentHash: string;
  path: string;
  mediaType: string | null;
}

/** 一条逐条结论引用的试用用例：名称、结论（中文）与截图引用。 */
export interface CriterionCaseView {
  title: string;
  resultName: string;
  screenshots: ScreenshotRefView[];
}

/** 逐条结论表的一行。 */
export interface CriterionRowView {
  criterion: string;
  methodName: string;
  resultName: string;
  resultKind: string;
  open: boolean;
  note: string;
  checks: string[];
  cases: CriterionCaseView[];
  screenshots: ScreenshotRefView[];
  hiddenScreenshots: number;
}

/** 无法核验的一条：验收条件、检验方式（中文）与原因。 */
export interface UnverifiedView {
  criterion: string;
  methodName: string;
  note: string;
}

/** 交付说明里的一个启动方式：名称、种类（中文）、按系统的命令、就绪地址与时限。 */
export interface LaunchCommandView {
  system: string;
  argv: string[];
}

export interface LaunchRowView {
  key: string;
  name: string;
  kindName: string;
  commands: LaunchCommandView[];
  readyUrl: string | null;
  readyTimeoutSec: number | null;
}

const UNNAMED_CRITERION = "未编号的验收条件";
const UNNAMED_CASE = "未命名试用用例";
const MISSING_CASE = "试用用例的记录不在这一份结论里";
const UNNAMED_LAUNCH = "未命名启动方式";

function criterionName(value: unknown): string {
  const name = typeof value === "string" ? value.trim() : "";
  return name === "" ? UNNAMED_CRITERION : name;
}

// 截图引用：四项里取不出可核对的标识时不算一张截图（空引用不占一张的位置）
function screenshotRef(value: Record<string, unknown>): ScreenshotRefView | null {
  const kind = typeof value.kind === "string" ? value.kind.trim() : "";
  const contentHash = typeof value.content_hash === "string" ? value.content_hash.trim() : "";
  const path = typeof value.path === "string" ? value.path.trim() : "";
  if (kind === "" || contentHash === "" || path === "") {
    return null;
  }
  const mediaType = typeof value.media_type === "string" && value.media_type.trim() !== ""
    ? value.media_type.trim() : null;
  return { kind, contentHash, path, mediaType };
}

function screenshotRefs(values: readonly Record<string, unknown>[] | undefined): ScreenshotRefView[] {
  return (values ?? []).map(screenshotRef).filter((item): item is ScreenshotRefView => item !== null);
}

/**
 * 一份 QAReview 的逐条结论表。`coverage` 是 `acceptance.coverage` 的结果：
 * 与这份结论的 event_id 相同的那一份给出每行的开环判定；没有时按检验方式判断。
 */
export function criterionRows(review: ReviewEntry, coverage: AcceptanceCoverageResult | null): CriterionRowView[] {
  const verdicts = new Map((coverage?.criteria ?? []).map((item) => [item.criterion, item]));
  const cases = new Map((review.trial_cases ?? []).map((item) => [item.case_id, item]));
  return (review.criteria ?? []).map((item) => {
    const fromRecord = verdicts.get(item.criterion);
    // 没有放行记录里的判定时按方式判断：不可执行的方式算开环。
    // 试用用例是不是模型阅读要看它的步骤，这里没有那一份数，按可执行算（不猜）
    const open = fromRecord !== undefined ? fromRecord.open : CHECK_METHODS[item.method]?.executable === false;
    const referenced = (item.trial_cases ?? []).map((caseId) => caseEvidence(cases.get(caseId)));
    const screenshots = referenced.flatMap((entry) => entry.screenshots);
    return {
      criterion: criterionName(item.criterion),
      methodName: checkMethodName(item.method),
      resultName: checkResultName(item.result),
      resultKind: checkResultKind(item.result),
      open,
      note: typeof item.note === "string" ? item.note.trim() : "",
      checks: (item.checks ?? []).filter((name) => name.trim() !== ""),
      cases: referenced,
      screenshots: screenshots.slice(0, SCREENSHOT_LIMIT),
      hiddenScreenshots: Math.max(0, screenshots.length - SCREENSHOT_LIMIT),
    };
  });
}

// 一条被引用的试用用例：用例不在这个 run 的投影里时仍然列出引用，标题写明没有记录
function caseEvidence(found: TrialCaseEvidenceView | undefined): CriterionCaseView {
  if (found === undefined) {
    return { title: MISSING_CASE, resultName: "", screenshots: [] };
  }
  const title = typeof found.title === "string" && found.title.trim() !== "" ? found.title.trim() : UNNAMED_CASE;
  return {
    title,
    resultName: trialCaseResultName(found.result),
    screenshots: screenshotRefs(found.screenshots),
  };
}

/**
 * 表头上的那一行：检验覆盖比例、模型阅读与开环的条数，全部取放行记录里的数。
 * 比例按记录里的 coverage_ratio 写，不按 covered ÷ criteria_total 重算。
 */
export function coverageSummary(numbers: AcceptanceCoverageResult["numbers"]): string {
  const ratio = Number.isFinite(numbers.coverage_ratio) ? Math.round(numbers.coverage_ratio * 100) : 0;
  return `检验覆盖 ${ratio}%（${numbers.covered}/${numbers.criteria_total}）· 开环条件 ${numbers.open} 条（其中模型阅读 ${numbers.model_reading} 条）`;
}

/** 无法核验的条目与原因：方法写中文，原因没有写时写明没有写。 */
export function unverifiedViews(review: ReviewEntry): UnverifiedView[] {
  return (review.unverified ?? []).map((item) => ({
    criterion: criterionName(item.criterion),
    methodName: checkMethodName(item.method),
    note: item.note.trim() === "" ? "没有写明原因" : item.note.trim(),
  }));
}

const SYSTEM_ORDER = ["windows", "linux"];

function systemRank(system: string): number {
  const index = SYSTEM_ORDER.indexOf(system);
  return index === -1 ? SYSTEM_ORDER.length : index;
}

/**
 * 交付一项的启动方式。`commands` 是按系统给出的 argv；Windows 在 Linux 前面列出，
 * 其余系统的键不认识时排在后、名字写「其他系统」。
 */
export function launchViews(launch: readonly LaunchMethodView[] | undefined): LaunchRowView[] {
  return (launch ?? []).map((item, index) => {
    const commands = Object.entries(item.commands ?? {})
      .map(([system, argv]) => ({
        system,
        argv: (Array.isArray(argv) ? argv : []).filter((part): part is string => typeof part === "string" && part !== ""),
      }))
      .filter((entry) => entry.argv.length > 0)
      .sort((left, right) => systemRank(left.system) - systemRank(right.system));
    const name = item.name.trim() === "" ? UNNAMED_LAUNCH : item.name.trim();
    return {
      key: `${index}-${name}`,
      name,
      kindName: launchKindName(item.kind),
      commands: commands.map((entry) => ({ system: launchSystemName(entry.system), argv: entry.argv })),
      readyUrl: typeof item.ready_url === "string" && item.ready_url.trim() !== "" ? item.ready_url.trim() : null,
      readyTimeoutSec: typeof item.ready_timeout_sec === "number" && Number.isFinite(item.ready_timeout_sec)
        ? item.ready_timeout_sec : null,
    };
  });
}
