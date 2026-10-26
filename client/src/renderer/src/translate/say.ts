// 翻译层：小人头顶说的话（画面与播放设计说明第 6 节、原型 v13 js/translate/say.js，工单 #952）。
//
// 内容只来自事件已经带着的事实（事件种类、载荷里的字段、事件说明），翻译层把它写进动作的 say（做事的一方）
// 与 sayTo（收东西的一方），画面层只管画（画面层的说话目录 pixel/world/say.ts 已由画面 9 删除，工单 #959；
// 一句话在头顶停留多久由画面层的 world/characters.ts 决定）。
//
// 目录里的事件种类与服务端的 EVENT_TYPES 同名（见 client/tests/fixtures/event-types.json）；
// 原型 v13 里只存在于原型的 x_ 前缀事件没有搬，它们在真实系统里没有对应的事件。
// 目录里没有的事件按事件说明去掉开头的主语，当作这个小人在做的事（与原型相同）。

/** 说一句话要用到的事件字段（接口合同的事件信封里与说话有关的那几个）。 */
export interface SayEvent {
  type: string;
  label?: string | null;
  department?: string | null;
  role?: string | null;
  tool?: string | null;
  payload?: Record<string, unknown> | null;
}

/** 说话时的上下文：side 为 "to" 表示这个小人是收东西的一方，roleName 给出角色名称。 */
export interface SayContext {
  side?: "to" | null;
  roleName?: (role: string | null) => string | null;
}

/** 事件载荷是按种类不同的字段集合，取值时先收窄。 */
type Payload = Record<string, unknown>;

const text = (value: unknown): string => (value === undefined || value === null ? "" : String(value));
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const flag = (value: unknown): boolean => value === true;

export const DEPT_NAMES: Readonly<Record<string, string>> = {
  product: "产品",
  engineering: "工程",
  quality: "质检",
  operations: "运维",
  library: "成果库",
};
const deptName = (id: unknown): string => DEPT_NAMES[text(id)] ?? text(id);

/** 把一句话截到 n 个字以内，超出部分用省略号（与原型相同的写法）。 */
export const cut = (value: unknown, n: number): string => {
  const t = text(value).replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
};

const baseName = (value: unknown): string => text(value).split(/[\\/]/).pop() ?? "";

/** 事件说明里冒号后面的部分（询问与回答的具体内容）。 */
const afterColon = (label: unknown): string => {
  const m = /[：:]\s*(.+)$/.exec(text(label));
  return m ? m[1] : "";
};

// 提案的种类（真实系统 proposal 的 kind 字段）；没有种类时取事件说明里「提交」后面的部分，再没有就按部门
const PROPOSAL: Readonly<Record<string, string>> = {
  product_spec: "产品规格",
  product_decision: "产品决定",
  engineering_plan: "工程计划",
  delivery_spec: "交付说明",
  qa_review: "质检结论",
  collaboration_request: "询问",
  collaboration_response: "回答",
  department_guidance_response: "指导回复",
};
const DEFAULT_PROPOSAL: Readonly<Record<string, string>> = {
  product: "产品规格",
  engineering: "交付说明",
  quality: "质检结论",
  operations: "运维记录",
};
const ARTIFACT: Readonly<Record<string, string>> = { prd: "PRD", box: "交付箱", defect: "返工单", release: "放行单" };

function proposalName(ev: SayEvent, pl: Payload): string {
  const kind = PROPOSAL[text(pl.kind)];
  if (kind) return kind;
  const m = /提交(.+?)(?:[，。：:（(]|$)/.exec(text(ev.label));
  return (m && m[1]) || DEFAULT_PROPOSAL[text(ev.department)] || "提案";
}

const FILE_RE = /([\w\-./]+\.[A-Za-z0-9]{1,5})(?![A-Za-z0-9])/;
// 真实系统把工具名与参数放在载荷里：工具名是 name，参数在 args 之下（harness/app/payloads.py 的 ToolStartedPayload）。
// args 以下的键按工具各自的要求取：读取与修改类用 path，翻找用 pattern，bash 用 command。
const argsOf = (pl: Payload): Payload => (pl.args as Payload | undefined) ?? {};
const argOf = (pl: Payload, key: string): string | null => {
  const value = argsOf(pl)[key] ?? pl[key];
  return typeof value === "string" && value !== "" ? value : null;
};
const fileOf = (ev: SayEvent, pl: Payload): string | null =>
  argOf(pl, "path") ?? argOf(pl, "source") ?? (typeof pl.file === "string" ? pl.file : null)
  ?? (FILE_RE.exec(text(ev.label)) ?? [])[1] ?? null;
// 翻找的查询词：真实载荷在 args.pattern，原型事件的载荷直接给 query
const searchQuery = (pl: Payload): string | null => argOf(pl, "pattern") ?? argOf(pl, "query");
// 命令：真实载荷给 args.command（顶层 command 也认），原型事件把命令名写在说明的末尾。
// 不回退 name：真实载荷的顶层 name 是工具名，回退会把工具名当命令说出来。
const commandOf = (ev: SayEvent, pl: Payload): string | null =>
  argOf(pl, "command") || (/([A-Za-z][\w.\-]*)\s*$/.exec(text(ev.label)) ?? [])[1] || null;

// 交出类工具的说话：真实系统的 submit_* 与提案事件的 kind 共用一套名字（harness 的提案合同）
const SUBMIT_NAME: Readonly<Record<string, string>> = {
  submit_product_spec: "产品规格",
  submit_product_decision: "产品决定",
  submit_delivery: "交付说明",
  submit_review: "质检结论",
  ask: "询问",
  answer: "回答",
  submit_guidance_response: "指导回复",
};

function toolText(ev: SayEvent, pl: Payload): string | null {
  const tool = text(ev.tool ?? pl.tool ?? pl.name);
  const file = fileOf(ev, pl);
  const named = (prefix: string, fallback: string): string =>
    "现在" + prefix + (file ? " " + cut(baseName(file), 16) : fallback);
  if (tool === "search") {
    const q = searchQuery(pl);
    return "现在翻找资料" + (q ? "：" + cut(q, 12) : "");
  }
  if (/^read/.test(tool)) return named("阅读", "资料");
  if (/^(edit|write)/.test(tool)) return named("编辑", "文件");
  if (tool === "delete_file") return named("删除", "文件");
  if (tool === "move_file") return named("移动", "文件");
  if (tool === "list_files") return "现在看看有什么文件" + (argOf(pl, "prefix") ? "：" + cut(argOf(pl, "prefix") ?? "", 12) : "");
  // 交出类工具（真实系统的 submit_*）：提案事件随后还会说一次提交了什么，这里先说正在交出哪一份
  const submit = SUBMIT_NAME[tool];
  if (submit !== undefined) return "现在提交" + submit;
  if (/^submit_/.test(tool)) return "现在提交";
  if (tool === "run_command" || tool === "bash") {
    const name = commandOf(ev, pl);
    return "现在执行" + (name ? " " + cut(name, 14) : "命令");
  }
  if (tool === "run_check") {
    const name = argOf(pl, "name");
    return "现在检查交付" + (name ? "：" + cut(name, 12) : "");
  }
  if (/^browser/.test(tool)) return ev.department === "quality" ? "现在试用网页" : "现在自测网页";
  if (/^(fetch|http|net|url)/.test(tool)) return "现在取回网络资料";
  if (/^mcp/.test(tool)) return "现在调用工具";
  return null;
}

// 没有登记在目录里的事件：拿事件说明去掉开头的主语，就是这个小人在做的事
function fromLabel(ev: SayEvent): string | null {
  const label = text(ev.label);
  if (!label) return null;
  const t = label.replace(/^[^，。：:、]{0,8}?(?:部门|经理|架构师|测试工程师|探索者|审查者|主程|Agent|系统|用户)(?:代表部门)?/, "");
  return cut(t || label, 26);
}

/** 目录里的一句话：返回 null 表示这件事没有小人说话，返回 undefined 表示按事件说明写。 */
type SayText = (ev: SayEvent, pl: Payload, x: Required<Pick<SayContext, "side">> & { roleName: (role: string | null) => string | null }) => string | null | undefined;

// 目录：事件种类 → 一句话（与原型 v13 say.js 的 TEXT 相同；x_ 前缀的原型事件没有搬）
const TEXT: Readonly<Record<string, SayText>> = {
  department_activated: () => "现在开始工作",
  context_assembled: () => "现在整理资料",
  model_requested: () => "现在思考",
  model_request_serialized: () => "现在思考",
  model_attempt_finished: () => "想到办法了",
  model_retry_scheduled: (_ev, pl) => {
    const n = num(pl.n) ?? num(pl.attempt) ?? num(pl.attempt_no);
    const of = num(pl.of) ?? num(pl.max) ?? num(pl.max_attempts);
    return "等一会儿再试" + (n !== null && of !== null ? "（第 " + n + "/" + of + " 次）" : "");
  },
  model_attempt_failed: () => "请求失败了",
  tool_started: toolText,
  tool_called: (ev, pl) => {
    const tool = text(ev.tool ?? pl.tool ?? pl.name);
    if (!["run_command", "bash"].includes(tool)) return null;
    if (flag(pl.timed_out)) return "命令超时了";
    // 真实载荷只有 ok 与 error（退出码在工件里，事件上读不到）；原型事件带 exit_code
    const ok = typeof pl.exit_code === "number" ? pl.exit_code === 0 : pl.ok !== false;
    if (ok) return "命令通过了";
    return "命令没有通过" + (text(pl.error) ? "：" + cut(pl.error, 12) : "");
  },
  tool_skipped: () => "这个工具没有获准，换个办法",
  proposal_submitted: (ev, pl) => "现在提交" + proposalName(ev, pl),
  proposal_rejected: () => "提案被退回，重新修改",
  spec_accepted: () => "现在盖上有效章",
  contract_accepted: () => "现在盖上有效章",
  product_decision_accepted: () => "现在盖上有效章",
  spec_superseded: () => "现在换用新版本的规格",
  delivery_accepted: () => "现在装箱封存",
  qa_submitted: (_ev, pl) => (pl.verdict === "release" ? "现在盖放行章" : "现在盖返工章"),
  qa_tests_saved: () => "现在写下测试用例",
  department_guidance_received: () => "收到用户的指导",
  department_guidance_applied: () => "现在阅读指导",
  department_guidance_responded: () => "现在写指导的回复",
  compaction_recorded: () => "现在把资料整理成摘要",
  compaction_failed: () => "整理没有生效，重新整理",
  run_paused: () => "先暂停一下",
  run_failed: (_ev, pl) => {
    const reason = text(pl.reason || pl.stopReason);
    return reason === "cancelled" ? "事项取消了，收拾桌面" : "失败了" + (reason ? "：" + cut(reason, 12) : "");
  },
  run_done: () => "完成了！",
  run_resumed: () => "继续工作",
  run_continued: () => "收到你的回答，继续工作",
  decision_requested: (_ev, pl) => (
    pl.kind === "model_unavailable" ? "模型引用用不了，等你决定"
      : pl.kind === "unknown_action" ? "这个动作的结果不确定"
        : "现在送出决定单"
  ),
  decision_answered: () => "收到你的回答",
  project_decision_requested: () => "现在送出决定单",
  project_decision_answered: () => "收到你的回答",
  deliverable_adopted: () => "现在采纳成果",
  baseline_adopted: () => "现在盖下基线",
  work_item_start_failed: () => "事项没能开始",
  lesson_candidate_recorded: () => "记下一条经验",
};

/** 一件事的一句话。x：{ side（"to" 为收东西的一方）, roleName(角色 id) → 角色名称 }。 */
export function say(ev: SayEvent, x?: SayContext): string | null {
  const ctx = {
    side: x?.side ?? null,
    roleName: (role: string | null): string | null => (x?.roleName ? x.roleName(role) : null),
  };
  const f = TEXT[ev.type];
  if (!f) return fromLabel(ev);
  const spoken = f(ev, ev.payload ?? {}, ctx);
  return spoken === undefined ? fromLabel(ev) : spoken;
}

/** 说话目录（画面 3、4 的动作表按它核对每种动作有没有话）。 */
export const sayCatalog: readonly string[] = Object.keys(TEXT);

/** 交接的两端：交出方说把什么送给谁，接收方说收到什么。 */
export function sayHandoff(artifact: string, from: string, to: string): { say: string; sayTo: string } {
  return {
    say: "现在把" + (ARTIFACT[artifact] ?? artifact) + "送给" + deptName(to),
    sayTo: "收到" + (ARTIFACT[artifact] ?? artifact) + "，来自" + deptName(from),
  };
}

/** 询问的两端：发信的一方与收信的一方。 */
export function sayAsk(ev: SayEvent): { say: string; sayTo: string } {
  const pl = ev.payload ?? {};
  const q = typeof pl.question === "string" && pl.question ? pl.question : afterColon(ev.label);
  const tail = q ? "：" + cut(q, 14) : "";
  return { say: "现在向" + deptName(pl.recipient) + "发出询问" + tail, sayTo: "收到" + deptName(pl.requester) + "的询问" + tail };
}

/** 回答的两端：回答的一方与收到回答的一方。 */
export function sayAnswer(ev: SayEvent): { say: string; sayTo: string } {
  const pl = ev.payload ?? {};
  const a = typeof pl.answer === "string" && pl.answer ? pl.answer : afterColon(ev.label);
  const tail = a ? "：" + cut(a, 14) : "";
  return { say: "现在回答" + deptName(pl.requester) + "的询问", sayTo: "收到" + deptName(pl.recipient) + "的回答" + tail };
}
