// 项目头部一行与对话上方的时间条：由查询给出的事实推出页面写什么（工单 #1653；项目的组织设计说明
// 4.12「形态一键选用」、4.15「循环图跟着组织长」的「其余规矩」；形态与核验角色设计说明「开环完成」）。
//
// 这里只取值与判断，不碰界面与网络，单元测试直接调用（project-head-model.test.ts）：
//   - 头部一行读项目现在的组织（project.organization）：形态名用服务端给的 label（不显示发布带里的标识），
//     改过几处按本项目的改动数，轮转方式与有核验或开环由合成结果得出。读的是项目现在的这一份，
//     不读选中事项冻结的那一份：在跑的事项照它自己冻结的组织跑，头部仍写现在用的组织。
//   - 时间条读选中事项在 project.loop 里的已用时间与上限，另有「停止」时给出待确认的那一份
//     （事项与它这一刻的版本）。停止走现有的取消事项：确认框的标题、后果与两个按钮照 cancel-text.ts，
//     这里只把它接起来，不另写一套话。
//
// 页面上的文字按设计说明的两个词写：轮转方式是「直做」「按成果」；结束是有核验角色时写核验角色的显示名，
// 没有时写开环完成。

import type { ProjectOrganizationResult } from "../../api/generated/types.gen";
import {
  CANCEL_CONFIRM_CANCEL, CANCEL_CONFIRM_CONFIRM, cancelConfirmLines, cancelConfirmTitle,
  type CancelRequest,
} from "./cancel-text.ts";
import { formatDuration, OPEN_LOOP_STATUS_TEXT } from "./labels.ts";

/** 这一份不在这一版发布里（取不到形态名与合成结果）：照实写明，不拿发布带里的标识顶替。 */
export const OUT_OF_RELEASE = "这一份不在这一版发布里";

/** 有核验角色时那一项的开头，后面接核验角色的显示名（原型 v20 的 tags()：核验：质检）。 */
const VERIFIED = "核验：";

/**
 * 轮转方式的两个词（项目的组织设计说明 4.12 的表：直做 / 按成果）。
 *
 * 服务端的 routing_label 是定义里写的名字（发布里那一份写「成果驱动」），页面上按设计说明的词写；
 * 认不出的轮转用服务端给的 label，仍不显示标识。
 */
const ROTATION_TEXT: Record<string, string> = { direct: "直做", watched_outputs: "按成果" };

/** 形态名后面那一句的写法（项目的组织设计说明 4.15 的「其余规矩」：改过时写改过几处）。 */
function changedSuffix(changed: number): string {
  return changed === 0 ? "" : `（改过 ${changed} 处）`;
}

/** 头部一行的几项：形态名、改过几处、轮转方式、核验角色的显示名，以及那一行标签（按显示的先后）。 */
export type ProjectHead = {
  /** 形态名（服务端给的 label）；这一份不在发布里时为空 */
  form: string;
  /** 本项目改过几处（不算加独立核验、由谁做与观察者） */
  changed: number;
  /** 轮转方式：直做、按成果，或服务端给的名字 */
  rotation: string;
  /** 核验角色的显示名；为空表示没有核验角色，事项以开环完成结束 */
  verifiers: string[];
  /** 一行标签：形态名（改过几处）、轮转方式、有核验或开环 */
  tags: string[];
};

/** 头部一行：查询还没有数据时没有这一行（不写一行假的）。 */
export function projectHead(
  organization: ProjectOrganizationResult | null | undefined,
): ProjectHead | null {
  if (organization === null || organization === undefined) {
    return null;
  }
  const roster = organization.departments ?? [];
  const verifiers = roster.filter((department) => department.verifier === true).map((department) => department.label);
  // 加独立核验那一次点击带进来的是「本项目加的」核验职能：它不在「改过几处」里（设计说明 4.15 的「其余规矩」）
  const addedVerifiers = new Set(roster
    .filter((department) => department.verifier === true && department.origin === "added")
    .map((department) => department.id));
  const changed = changedCount(organization.changes, addedVerifiers);
  const composed = organization.organization ?? null;
  if (organization.label === null || organization.label === undefined || composed === null) {
    return { form: "", changed, rotation: "", verifiers, tags: [OUT_OF_RELEASE] };
  }
  const rotation = rotationText(composed.routing, composed.routing_label);
  const ending = verifiers.length === 0 ? OPEN_LOOP_STATUS_TEXT : `${VERIFIED}${verifiers.join("、")}`;
  return {
    form: organization.label,
    changed,
    rotation,
    verifiers,
    tags: [`「${organization.label}」${changedSuffix(changed)}`, rotation, ending].filter((tag) => tag !== ""),
  };
}

/** 轮转方式在页面上的写法：设计说明的两个词先用，认不出的轮转用服务端给的 label。 */
export function rotationText(routing: string, label: string): string {
  return ROTATION_TEXT[routing] ?? label;
}

/**
 * 本项目改过几处（项目的组织设计说明 4.15 的「其余规矩」）：按改动文档逐项数，一处算一处。
 *
 * 不算加独立核验（那一次点击带进来的核验职能与它的核验声明）、由谁做与观察者：前三样不走高级，
 * 一步生效（设计说明 4.12 的最后一段）。由谁做与观察者现在还没有进改动文档（`OrganizationChanges`
 * 的字段只增），这里因此只认改动文档里有的项：轮转方式、事项的来源、职能、加与去掉的职能、
 * 成果种类的增加与去掉、核验声明。
 */
export function changedCount(
  changes: Record<string, unknown> | undefined,
  addedVerifiers: ReadonlySet<string>,
): number {
  const document = record(changes);
  let count = document.routing === undefined || document.routing === null ? 0 : 1;
  count += Object.keys(record(document.sources)).length;
  count += Object.keys(record(document.departments)).length;
  for (const added of entries(document.add_departments)) {
    // 加独立核验带进来的那个核验职能不算；本项目自己加的职能各处算一处
    if (!addedVerifiers.has(named(record(added).id))) {
      count += 1;
    }
  }
  count += entries(document.remove_departments).length;
  const kinds = record(document.outcome_kinds);
  count += entries(kinds.add).length + entries(kinds.remove).length;
  if (document.verification !== undefined && document.verification !== null
    && !onlyAddedVerifiers(record(document.verification), addedVerifiers)) {
    count += 1;
  }
  return count;
}

/** 一条核验声明只写了加独立核验带进来的那几个核验角色：它属于那一次点击，不算一处改动。 */
function onlyAddedVerifiers(
  declaration: Record<string, unknown>,
  addedVerifiers: ReadonlySet<string>,
): boolean {
  const roles = entries(declaration.verifiers).map((item) => named(record(item).role)).filter((role) => role !== "");
  const scopes = Object.keys(record(declaration.write_scopes));
  const written = [...roles, ...scopes];
  return written.length === 0 || written.every((role) => addedVerifiers.has(role));
}

// ---------------------------------------------------------------- 时间条

/**
 * 时间条读的那几栏：选中事项在 project.loop 里的状态、已用时间与上限，以及停下它时要带的事项版本。
 * 只列用到的几项，与查询结果同名，调用处直接交 project.loop 的 work_items。
 */
export type TimeItem = {
  work_item_id: string;
  status: string;
  elapsed_sec: number | null;
  time_limit_sec: number;
  version: number;
};

/**
 * 还在做、可以停下的事项：与事项面板的「取消事项」同一个条件（概览页的取消入口）。
 * 事项结束以后没有「停止」；还在排队的事项还没有开始，也没有「停止」。
 */
const STOPPABLE: ReadonlySet<string> = new Set(["in_progress", "awaiting_initial_prd"]);

/** 正在处理的那一行开头（原型 v20 的时间条）：停下以后只写已用与上限。 */
const RUNNING = "正在处理 · ";

/** 「停止」按钮上的字（设计说明 4.15：时间条旁边一个「停止」）。 */
export const STOP_LABEL = "停止";

/** 对话上方的时间条：已用时间与上限，另有「停止」时待确认的那一份。 */
export type TimeBar = {
  workItemId: string;
  /** 「正在处理 · 已用 … / 上限 …」，没有在跑时只有已用与上限 */
  text: string;
  used: number | null;
  limit: number;
  /** 时间条画多满（0 到 1）：已用时间未知或上限不是正数时为空，不画 */
  ratio: number | null;
  /** 有「停止」时的那一份待确认；事项结束以后为空 */
  stop: CancelRequest | null;
};

/** 选中的那件事项的时间条：没有选中、或者地址里那件事项不在清单里时为空（不拿别的事项顶替）。 */
export function timeBar(items: readonly TimeItem[], selected: string | null | undefined): TimeBar | null {
  const item = selected === null || selected === undefined || selected === ""
    ? null
    : items.find((candidate) => candidate.work_item_id === selected) ?? null;
  if (item === null) {
    return null;
  }
  const stoppable = STOPPABLE.has(item.status);
  return {
    workItemId: item.work_item_id,
    text: `${stoppable ? RUNNING : ""}已用 ${formatDuration(item.elapsed_sec)} / 上限 ${formatDuration(item.time_limit_sec)}`,
    used: item.elapsed_sec,
    limit: item.time_limit_sec,
    ratio: item.elapsed_sec === null || !(item.time_limit_sec > 0)
      ? null
      : Math.min(1, Math.max(0, item.elapsed_sec / item.time_limit_sec)),
    stop: stoppable
      ? { work_item_id: item.work_item_id, base_version: item.version, status: item.status }
      : null,
  };
}

/** 「停止」的确认框：标题、后果与两个按钮照取消事项的那一份（cancel-text.ts），确认以后才提交。 */
export type StopConfirm = {
  title: string;
  lines: string[];
  confirm: string;
  cancel: string;
};

export function stopConfirm(request: CancelRequest): StopConfirm {
  return {
    title: cancelConfirmTitle(request.status),
    lines: cancelConfirmLines(request.status),
    confirm: CANCEL_CONFIRM_CONFIRM,
    cancel: CANCEL_CONFIRM_CANCEL,
  };
}

// ---------------------------------------------------------------- 取值

// 改动文档是服务端给的 JSON（project.organization 的 changes）：这几项可能是任何形状，
// 不是对象或不是清单时按没有读，不用它去猜一项改动。

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function entries(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function named(value: unknown): string {
  return typeof value === "string" ? value : "";
}
