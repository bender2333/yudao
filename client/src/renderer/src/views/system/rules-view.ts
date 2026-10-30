// 规则与参数页的辅助逻辑（工单 #1195，应用层与接口层设计说明「规则与参数在页面上的显示」）。
// 页面只显示 rules.registry 返回的条目：按领域分组，不自行解释规则、补造默认值或推断未登记的范围。
// 这一份是纯函数与文案，单元测试直接调用；页面的读写状态见 rules.tsx。

import type { ParameterChangeEntry, RuleEntry } from "../../api/generated/types.gen";

/** 一个领域分组：条目名前缀（第一个点之前的部分）与它下面的条目 */
export type RulesGroup = {
  domain: string;
  rules: RuleEntry[];
};

/**
 * 按领域分组（设计说明「每行按领域分组」）：领域取条目名的第一个点之前的部分，
 * 点号之间按原有顺序排列，同一领域内的条目保持登记给出的顺序（登记本身按名称排列）。
 * 没有点号的条目归入「其他」。
 */
export function groupRules(rules: RuleEntry[]): RulesGroup[] {
  const groups: RulesGroup[] = [];
  const index = new Map<string, RulesGroup>();
  for (const rule of rules) {
    const domain = domainOf(rule.name);
    let group = index.get(domain);
    if (!group) {
      group = { domain, rules: [] };
      index.set(domain, group);
      groups.push(group);
    }
    group.rules.push(rule);
  }
  return groups;
}

function domainOf(name: string): string {
  const dot = name.indexOf(".");
  return dot === -1 ? "其他" : name.slice(0, dot);
}

/** 数值界限：登记的 bounds 是二元数组，两端都是数时才是可显示的界限 */
export type RuleBounds = { min: number; max: number } | null;

export function numericBounds(entry: RuleEntry): RuleBounds {
  if (entry.bounds.length !== 2) {
    return null;
  }
  const min = entry.bounds[0];
  const max = entry.bounds[1];
  if (typeof min !== "number" || typeof max !== "number" || !Number.isFinite(min) || !Number.isFinite(max)) {
    return null;
  }
  return { min, max };
}

/**
 * 这一条能不能在页面上修改（设计说明第 563 至 565 行）：
 * 只有接入了行为（wired）的数值型参数条目（kind 为 parameter）提供修改控件；
 * 结构条目只读并提示结构修改走候选流程；字符串与列表参数只读（登记还没有提供候选约束）；
 * 未接入的条目显示登记提供的未接入原因并禁用修改。
 */
export function editable(entry: RuleEntry): boolean {
  return entry.kind === "parameter" && entry.wired && isNumeric(entry.value) && isNumeric(entry.default_value);
}

export function isNumeric(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** 种类与形式的中文（设计说明第 2 节）：kind 与 form 都是登记封闭清单里的取值 */
export const RULE_KIND_TEXT: Record<string, string> = {
  parameter: "参数",
  structure: "结构",
};

export const RULE_FORM_TEXT: Record<string, string> = {
  permission: "许可",
  boundary: "边界",
  admission: "接纳条件",
};

/** 值的显示：数按原样，字符串加引号以外的原样，布尔、数组与对象按 JSON 写出；未知形状写「未上报」 */
export function valueText(value: unknown): string {
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "boolean" || value === null) {
    return JSON.stringify(value);
  }
  if (Array.isArray(value) || typeof value === "object") {
    return JSON.stringify(value);
  }
  return "未上报";
}

/** 值是否相等（撤回核对「现值仍等于该记录的新值」）：数按数值比，其余按 JSON 文本比 */
export function sameValue(a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number") {
    return a === b;
  }
  return JSON.stringify(a) === JSON.stringify(b);
}

/** 最近一次修改记录：历史按登记给出的顺序（最旧在前），撤回看最后一条 */
export function latestChange(entry: RuleEntry): ParameterChangeEntry | null {
  const changes = entry.changes ?? [];
  return changes.length > 0 ? changes[changes.length - 1] ?? null : null;
}

/** 修改历史按时间倒序显示（设计说明第 563 行）：登记里最旧在前，这里反过来 */
export function recentChanges(entry: RuleEntry): ParameterChangeEntry[] {
  return [...(entry.changes ?? [])].reverse();
}

/**
 * 撤回能不能进行（设计说明第 569 行）：重新读取登记以后，
 * 只有最近修改记录的稳定身份与用户选中的记录一致、且现值仍等于该记录的新值时，撤回才能提交。
 * 现值经历修改后又变回相同数值时，记录身份改变，同样放弃（ABA 防护）。
 */
export function withdrawCheck(
  entry: RuleEntry,
  selectedChangeId: string,
): { ok: true; change: ParameterChangeEntry } | { ok: false; reason: WithdrawBlockReason } {
  const latest = latestChange(entry);
  if (latest === null) {
    return { ok: false, reason: "no_change" };
  }
  if (latest.event_id !== selectedChangeId) {
    return { ok: false, reason: "record_moved" };
  }
  if (!sameValue(entry.value, latest.new_value)) {
    return { ok: false, reason: "value_changed" };
  }
  return { ok: true, change: latest };
}

export type WithdrawBlockReason = "no_change" | "record_moved" | "value_changed";

/** 撤回被放弃时确认框位置给出的一句中文（服务不拒绝时页面先拦下） */
export const WITHDRAW_BLOCK_TEXT: Record<WithdrawBlockReason, string> = {
  no_change: "这个参数还没有修改记录，没有可撤回的修改。",
  record_moved: "这个参数的最近一次修改已经不是你选中的那条：现值经历过新的修改（数值相同时记录身份也变了），这次撤回放弃。",
  value_changed: "这个参数的现值已经不等于选中记录的新值：后面又有过修改，这次撤回放弃。",
};

/** 撤回确认按钮提交的理由：按设计说明写成「撤回：」与原理由 */
export function withdrawReason(originalReason: string): string {
  return `撤回：${originalReason}`;
}

/** 修改历史里一条记录的一句显示：谁在什么时候把它从什么改成什么，理由是什么 */
export function changeLine(change: ParameterChangeEntry): string {
  return `${change.modified_by}：${valueText(change.old_value)} → ${valueText(change.new_value)}，理由：${change.reason}`;
}

/** 页面顶部的说明（设计说明第 567 行末句）：修改只作用于之后创建的 run */
export const RULES_PAGE_NOTE =
  "这里的修改与撤回只作用于之后创建的 run：正在运行的 run 按自己冻结的值结束。结构条目只读，结构修改走候选流程；字符串与列表参数只读，等登记提供候选约束。";

/** 未接入条目在行内的说明前缀（登记提供的原因原样显示，页面不自行书写拒绝原因） */
export function notWiredText(entry: RuleEntry): string {
  return entry.not_wired_reason === "" ? "" : `未接入运行：${entry.not_wired_reason}`;
}

/** 界限的显示文案：「允许范围 600 至 86400」；没有界限时不显示 */
export function boundsText(bounds: RuleBounds): string {
  if (bounds === null) {
    return "";
  }
  return `允许范围 ${valueText(bounds.min)} 至 ${valueText(bounds.max)}`;
}

/** 页面每行显示的四项记录（设计说明第 563 行）：guards、cost、relax_when、tighten_when */
export const RECORD_FIELD_LABELS: [keyof Pick<RuleEntry, "guards" | "cost" | "relax_when" | "tighten_when">, string][] = [
  ["guards", "拦截什么"],
  ["cost", "花费多少"],
  ["relax_when", "放松的证据"],
  ["tighten_when", "收紧的证据"],
];
