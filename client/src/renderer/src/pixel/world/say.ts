// 小人头顶的说话气泡的内容目录（原型 v10 say.js 与设计说明第 6 节，工单 #82）。
//
// 内容只来自事件已经带着的事实（事件类型、载荷里的字段、事件说明）：事件类型到一句话的规则按原型逐行改写；
// 目录里没有登记的事件类型，用事件说明去掉开头的主语以后的部分。
// 项目楼层与部门房间使用同一份目录（部门房间由 #177 接入）。

import { DEPTS } from "../registry.ts";
import type { PixelFloorEvent } from "./types.ts";

/** 说话时画面给出的上下文。 */
export interface SayContext {
  /** 说话的小人所在的部门。 */
  dept?: string | null;
  /** 'to' 表示这个小人是事件里收东西的一方。 */
  side?: "to" | "from" | null;
  /** 角色 id 到角色名称。 */
  roleName?: (key: string | null | undefined) => string | null;
}

const cut = (s: unknown, n: number): string => {
  const t = String(s === undefined || s === null ? "" : s).replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};

const baseName = (p: unknown): string => String(p || "").split(/[\\/]/).pop() ?? "";

const deptName = (id: string | null | undefined): string =>
  id && (DEPTS as Record<string, { name: string }>)[id] ? (DEPTS as Record<string, { name: string }>)[id].name : id || "";

/** 事件说明里冒号后面的部分（询问与回答的具体内容）。 */
const afterColon = (label: unknown): string => {
  const m = /[：:]\s*(.+)$/.exec(String(label || ""));
  return m ? m[1] : "";
};

/** 提案的种类（真实系统的 proposal 字段）。 */
const PROPOSAL: Record<string, string> = {
  product_spec: "产品规格", product_decision: "产品决定", delivery_spec: "交付说明",
  qa_review: "质检结论", ask: "询问", answer: "回答", department_guidance_response: "指导回复",
};
const DEFAULT_PROPOSAL: Record<string, string> = { product: "产品规格", engineering: "交付说明", quality: "质检结论", operations: "运维记录" };
const ARTIFACT: Record<string, string> = { prd: "PRD", box: "交付箱", defect: "返工单", release: "放行单", letter: "信件" };
// 交出类工具的说话：真实系统的 submit_* 与提案事件的 kind 共用一套名字（harness 的提案合同）
const SUBMIT_NAME: Record<string, string> = {
  submit_product_spec: "产品规格", submit_product_decision: "产品决定",
  submit_delivery: "交付说明", submit_review: "质检结论", ask: "询问",
  answer: "回答", submit_guidance_response: "指导回复",
};
function proposalName(ev: PixelFloorEvent, pl: Record<string, unknown>): string {
  if (PROPOSAL[pl.kind as string]) return PROPOSAL[pl.kind as string];
  const m = /提交(.+?)(?:[，。：:（(]|$)/.exec(String(ev.label || ""));
  return (m && m[1]) || DEFAULT_PROPOSAL[ev.department ?? ""] || "提案";
}

// 真实系统把工具名与参数放在载荷里：工具名是 name，参数在 args 之下（harness/app/payloads.py 的 ToolStartedPayload）。
// args 以下的键按工具各自的要求取：读取与修改类用 path，翻找用 pattern，bash 用 command。
const argsOf = (pl: Record<string, unknown>): Record<string, unknown> =>
  (pl.args as Record<string, unknown> | undefined) ?? {};

const argOf = (pl: Record<string, unknown>, key: string): string | null => {
  const value = argsOf(pl)[key] ?? pl[key];
  return typeof value === "string" && value !== "" ? value : null;
};

// bash 的命令原文：真实载荷给 args.command（顶层 command 也认）；原型事件把命令名写在说明的末尾，按它取。
// 注意不回退 name：真实载荷的顶层 name 是工具名（ToolStartedPayload），回退会把工具名当命令说出来。
const commandOf = (ev: PixelFloorEvent, pl: Record<string, unknown>): string | null =>
  argOf(pl, "command")
  ?? (/([A-Za-z][\w.\-]*)\s*$/.exec(String(ev.label || "")) || [])[1]
  ?? null;

// 文件名：真实载荷里在 args.path（移动取 args.source）；原型事件的说明里带文件名，按它取
const FILE_RE = /([\w\-./]+\.[A-Za-z0-9]{1,5})(?![A-Za-z0-9])/;
const fileOf = (ev: PixelFloorEvent, pl: Record<string, unknown>): string | null =>
  argOf(pl, "path") ?? argOf(pl, "source") ?? (pl.file as string) ?? (FILE_RE.exec(String(ev.label || "")) || [])[1] ?? null;
// 翻找的查询词：真实载荷在 args.pattern，原型事件的载荷直接给 query（与原型 say.js 的 pl.query 同口径）
const searchQuery = (pl: Record<string, unknown>): string | null =>
  argOf(pl, "pattern") ?? argOf(pl, "query") ?? null;

function toolText(ev: PixelFloorEvent, pl: Record<string, unknown>): string | null {
  const tool = String(ev.tool ?? pl.tool ?? pl.name ?? "");
  const file = fileOf(ev, pl);
  const named = (prefix: string, fallback: string): string =>
    `现在${prefix}${file ? ` ${cut(baseName(file), 16)}` : fallback}`;
  if (tool === "search") return `现在翻找资料${searchQuery(pl) ? `：${cut(searchQuery(pl) ?? "", 12)}` : ""}`;
  if (/^read/.test(tool)) return named("阅读", "资料");
  if (/^(edit|write)/.test(tool)) return named("编辑", "文件");
  if (tool === "delete_file") return `现在删除${file ? ` ${cut(baseName(file), 16)}` : "文件"}`;
  if (tool === "move_file") return `现在移动${file ? ` ${cut(baseName(file), 16)}` : "文件"}`;
  if (tool === "list_files") return `现在看看有什么文件${argOf(pl, "prefix") ? `：${cut(argOf(pl, "prefix"), 12)}` : ""}`;
  // 交出类工具（真实系统的 submit_*）：提案事件随后还会说一次提交了什么，这里先说正在交出哪一份
  const submit = SUBMIT_NAME[tool];
  if (submit !== undefined) return `现在提交${submit}`;
  if (/^submit_/.test(tool)) return "现在提交";
  if (tool === "bash") {
    const command = commandOf(ev, pl);
    return `现在执行${command ? ` ${cut(command, 14)}` : "命令"}`;
  }
  if (tool === "run_check") {
    const name = argOf(pl, "name");
    return `现在检查交付${name ? `：${cut(name, 12)}` : ""}`;
  }
  if (/^browser/.test(tool)) return ev.department === "quality" ? "现在试用网页" : "现在自测网页";
  if (/^(fetch|http|net|url)/.test(tool)) return "现在取回网络资料";
  if (/^mcp/.test(tool)) return "现在调用工具";
  return null;
}

/** 工具执行的结果：载荷上的 ok 决定这句话（退出码只出现在工件里，事件上读不到）。 */
function commandResultText(pl: Record<string, unknown>): string {
  if (pl.ok === false) return pl.error ? `命令没有通过：${cut(pl.error, 12)}` : "命令没有通过";
  return "命令通过了";
}

/** 没有登记在目录里的事件：拿事件说明去掉开头的主语。 */
function fromLabel(ev: PixelFloorEvent): string | null {
  const label = String(ev.label || "");
  if (!label) return null;
  const t = label.replace(/^[^，。：:、]{0,8}?(?:部门|经理|架构师|测试工程师|探索者|审查者|主程|Agent|系统|用户)(?:代表部门)?/, "");
  return cut(t || label, 26);
}

type SayRule = (ev: PixelFloorEvent, pl: Record<string, unknown>, ctx: Required<SayContext>) => string | null | undefined;

/** 事件类型 → 一句话；返回 null 表示这件事没有小人说话。 */
export const SAY_CATALOG: Record<string, SayRule> = {
  department_activated: () => "现在开始工作",
  context_assembled: () => "现在整理资料",
  model_requested: () => "现在思考",
  model_request_serialized: () => "现在思考",
  model_stream_progress: () => null,
  model_attempt_finished: () => "想到办法了",
  model_retry_scheduled: (_ev, pl) => {
    const n = pl.n || pl.attempt || pl.attempt_no;
    const of = pl.of || pl.max || pl.max_attempts;
    return `等一会儿再试${n && of ? `（第 ${n}/${of} 次）` : ""}`;
  },
  model_attempt_failed: () => "请求失败了",
  tool_started: toolText,
  tool_called: (ev, pl) => {
    // 真实载荷只有 ok 与 error：退出码在工件里，事件上读不到（harness/app/payloads.py 的 ToolCallResult）
    if (String(ev.tool ?? pl.tool ?? pl.name ?? "") !== "bash") return null;
    return commandResultText(pl);
  },
  tool_skipped: () => "这个工具没有获准，换个办法",
  proposal_submitted: (ev, pl) => `现在提交${proposalName(ev, pl)}`,
  proposal_rejected: () => "提案被退回，重新修改",
  spec_accepted: () => "现在盖上有效章",
  contract_accepted: () => "现在盖上有效章",
  delivery_accepted: () => "现在装箱封存",
  qa_started: () => "现在开始检查",
  qa_submitted: (_ev, pl) => (pl.verdict === "release" ? "现在盖放行章" : "现在盖返工章"),
  collaboration_requested: (ev, pl, x) => {
    const fromStr = typeof pl.from === "string" ? pl.from : null;
    const asker = fromStr || ev.department;
    const qStr = typeof pl.question === "string" ? pl.question : null;
    const q = qStr || afterColon(ev.label);
    const tail = q ? `：${cut(q, 14)}` : "";
    if (x.side === "to" || (x.dept && x.dept !== asker)) return `收到${deptName(asker)}的询问${tail}`;
    const toStr = typeof pl.to === "string" ? pl.to : null;
    return `现在向${deptName(toStr)}发出询问${tail}`;
  },
  collaboration_responded: (ev, pl, x) => {
    const fromStr = typeof pl.from === "string" ? pl.from : null;
    const toStr = typeof pl.to === "string" ? pl.to : null;
    const answerer = fromStr || ev.department;
    const asker = toStr;
    const aStr = typeof pl.answer === "string" ? pl.answer : typeof pl.text === "string" ? pl.text : null;
    const a = aStr || afterColon(ev.label);
    const tail = a ? `：${cut(a, 14)}` : "";
    if (x.side === "to" || (x.dept && x.dept !== answerer)) return `收到${deptName(answerer)}的回答${tail}`;
    return `现在回答${deptName(asker)}的询问`;
  },
  department_guidance_received: () => "收到用户的指导",
  department_guidance_applied: () => "现在阅读指导",
  department_guidance_responded: () => "现在写指导的回复",
  compaction_recorded: () => "现在把资料整理成摘要",
  compaction_failed: () => "整理没有生效，重新整理",
  run_paused: () => "先暂停一下",
  run_failed: (_ev, pl) => {
    const reason = (pl.reason as string) || (pl.stopReason as string);
    return reason === "cancelled" ? "事项取消了，收拾桌面" : `失败了${reason ? `：${cut(reason, 12)}` : ""}`;
  },
  run_done: () => "完成了！",
  x_run_interrupted: () => null,
  x_run_auto_resumed: () => "继续工作",
  x_run_stopped_for_upgrade: () => "因为升级停下，收拾桌面",
  x_action_unknown: () => "这个动作的结果不确定",
  x_decision_issued: (_ev, pl) =>
    pl.kind === "external_action" ? "举着申请单等待授权" : pl.kind === "waiting_resume" ? "模型引用用不了，等你决定" : "现在送出决定单",
  project_decision_requested: () => "现在送出决定单",
  x_decision_answered: () => "收到你的回答",
  project_decision_answered: () => "收到你的回答",
  x_remote_action_started: (_ev, pl) => `现在在${cut(pl.machine_name || "远程机器", 10)}上执行`,
  x_machine_offline: (_ev, pl) => `${cut(pl.machine_name || "机器", 10)}没有回应`,
  x_network_fetch: () => "现在取回网络资料",
  x_mcp_called: (_ev, pl) => `现在调用${cut(pl.tool || pl.name || "工具", 12)}`,
  x_trial_step: () => "现在试用网页",
  x_deployed: (_ev, pl) => `现在部署${pl.version ? ` ${pl.version}` : ""}`,
  x_rolled_back: (_ev, pl) => `现在回滚${pl.to_version ? `到 ${pl.to_version}` : ""}`,
  x_fault_recorded: (_ev, pl) => `发现故障${pl.fault_id ? ` ${pl.fault_id}` : ""}`,
  x_backup_taken: () => "现在备份数据",
  x_provider_wait_entered: () => "模型服务不可用，先等一等",
  x_provider_wait_left: () => "模型服务恢复了",
  x_role_task_assigned: (ev, pl, x) => {
    const task = pl.task ? `：${cut(pl.task, 16)}` : "";
    return x.side === "to" ? `收到任务${task}` : `现在把任务交给${x.roleName((pl.to as string) || ev.role) || "同事"}${task}`;
  },
  x_role_result_returned: (_ev, _pl, x) => (x.side === "to" ? "收到结果" : "现在把结果交回经理"),
  x_review_recorded: (_ev, pl) =>
    pl.verdict === "passed" || pl.verdict === "pass" ? "审查通过" : `审查退回${pl.text ? `：${cut(pl.text, 14)}` : ""}`,
  x_explorer_fetch: () => "现在出门查资料",
  x_replanned: () => "现在重新规划",
  x_semantic_recorded: () => "现在整理一张语义卡片",
  // 交接：交出方说把什么送给谁，接收方说收到什么
  transition: (_ev, pl, x) => {
    const art = ARTIFACT[pl.artifact as string] || "成果";
    const receives = x.side ? x.side === "to" : Boolean(x.dept && x.dept === pl.to && x.dept !== pl.from);
    if (receives) return `收到${art}，来自${deptName(pl.from as string)}`;
    return `现在把${art}送给${pl.to === "adopted" || pl.to === "adoption" ? "成果库" : deptName(pl.to as string)}`;
  },
};

/** 给出一个小人此刻该说的话；事件没有登记时用事件说明去掉主语的部分。 */
export function say(ev: PixelFloorEvent, x?: SayContext): string | null {
  if (!ev || !ev.type) return null;
  const o = x ?? {};
  const ctx = { dept: o.dept ?? ev.department ?? null, side: o.side ?? null, roleName: o.roleName ?? (() => null) };
  const rule = SAY_CATALOG[ev.type];
  if (!rule) return fromLabel(ev);
  const text = rule(ev, (ev.payload ?? {}) as Record<string, unknown>, ctx);
  return text === undefined ? fromLabel(ev) : text;
}

/** 一句话在头顶停留的毫秒数：读得完一句话，最长 4.6 秒。 */
export function sayMs(text: string): number {
  return Math.min(4600, 1800 + String(text).length * 170);
}
