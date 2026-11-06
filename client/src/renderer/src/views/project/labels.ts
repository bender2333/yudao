// 页面显示用的名称（原型 v8 设计说明第 14 节用词；取值来自应用层的查询结果，未知值原样显示，不做猜测）。
// 单一来源：harness/app/labels.py 里的部门、阶段与状态名称，客户端按生成的合同取值对应显示。

import type { StreamState } from "../../contract/stream-state";

export const DEPARTMENTS: Record<string, { name: string; role: string }> = {
  product: { name: "产品", role: "把用户的要求整理成有效需求" },
  engineering: { name: "工程", role: "按有效需求实现并封存交付" },
  quality: { name: "质检", role: "按验收条件核验并给出放行或缺陷记录" },
};

// 部门状态的中文名（三部门的循环结构 docs/design/department-loop.md「部门的状态」，工单 #904）：总图第三节外环的五个词，页面上只写这一处。
// 外环另外四个词（接纳、返工、排空中、停止）在成果驱动下不作为部门的持续状态显示，这里不列。
export const DEPARTMENT_STATE: Record<string, string> = {
  waiting_user: "等用户",
  working: "一轮工作中",
  asking: "询问中",
  verifying: "核验中",
  waiting: "等待工作",
};

// 一个部门在这个事项上的状态与原因（work_item.departments 的取值）：state 是上面五个词之一，
// note 是一句原因，没有原因时不存在（工单 #903 的查询结果就是这个形状）
export interface DepartmentStateView {
  state: string;
  note?: string | null;
}

export const WORK_ITEM_STATUS: Record<string, string> = {
  // not_started 是「已登记、还没开始运行」——排队等开始时也是它，页面上叫「排队中」（工单 #733）
  not_started: "排队中",
  in_progress: "进行中",
  adopted: "已采纳",
  released_unsettled: "已放行",
  awaiting_initial_prd: "等待确认初始 PRD",
  stopped: "已停止",
  // held 是「上一个采纳成果被挂起」（基线变更），与排队是两件事，页面上不叫「排队中」（工单 #733）
  held: "成果已挂起",
};

// 开环完成（工单 #1421）：没有核验角色的事项交了完成就结束，项目流里 status 仍是 released_unsettled、
// stop_reason 是 open_loop。它不是放行（形态与核验角色设计说明「开环完成」），页面与报告都写「开环完成」
export const OPEN_LOOP_STATUS_TEXT = "开环完成";

// 事项状态在页面上的说法只按事项卡上的这两个字段判断（工单 #1421）：结束原因是 open_loop 的写在
// released_unsettled 上，不是另一个状态。判断只在这一处，看板分组、事项卡、详情与顶栏共用，
// 页面因此不会一处写「已放行」、另一处写「开环完成」
export interface WorkItemStatusFields {
  status: string;
  stop_reason?: string | null;
}

export function isOpenLoopCompleted(item: WorkItemStatusFields): boolean {
  return item.status === "released_unsettled" && item.stop_reason === "open_loop";
}

export function workItemStatusText(item: WorkItemStatusFields): string {
  return isOpenLoopCompleted(item) ? OPEN_LOOP_STATUS_TEXT : label(WORK_ITEM_STATUS, item.status);
}
// 事项状态对应的原型标记（原型 v10 handlers/project.js 的 displayOf）：
// held 与 stopped 在原型图标里没有对应（held 无图标），这两项保留纯文字，界面不猜
export const WORK_ITEM_STATUS_KIND: Record<string, string> = {
  not_started: "idle",
  in_progress: "running",
  adopted: "adopted",
  released_unsettled: "released",
  awaiting_initial_prd: "asking",
};

// 恢复观察状态（工单 #747）：结束的方式分开，正常完成不是「已终止」。
// 用词跟着项目里已有的词表走：楼层与房间的状态词表里 done 是「已完成」、cancelled 是「已取消」、
// paused 是「已暂停」；事项状态表里 stopped 是「已停止」。
export const RECOVERY_STATE: Record<string, string> = {
  running: "运行中",
  interrupted: "中断",
  waiting_resume: "待恢复",
  completed: "已完成",
  paused: "已暂停",
  cancelled: "已取消",
  stopped: "已停止",
};

// 恢复观察状态对应的原型标记：与状态一致（工单 #747）。
// 正常完成画成功的标记，被取消画已取消的标记，其余结束方式画失败的标记。
export const RECOVERY_STATE_KIND: Record<string, string> = {
  running: "running",
  interrupted: "interrupted",
  waiting_resume: "waiting",
  completed: "succeeded",
  paused: "paused",
  cancelled: "cancelled",
  stopped: "failed",
};

// run 状态的中文名（工单 #556）：阶段状态机删掉以后，run 的状态只有进行中与三个终态
export const RUN_STATUS_LABELS: Record<string, string> = {
  running: "进行中",
  done: "已完成",
  paused: "已暂停",
  failed: "执行失败",
};

// 停止原因的中文名（harness/definitions/stop_reasons.json 的取值与 done 的两种一致）
export const STOP_REASON: Record<string, string> = {
  released: "已完成并放行",
  // 开环完成也是「完成」的一种结束原因，但不是放行（工单 #1421）：文字与事项状态共用一处
  open_loop: OPEN_LOOP_STATUS_TEXT,
  baseline_verified: "已完成基线核验",
  max_cycles: "循环次数已达上限",
  model_steps_exhausted: "部门步数已达上限",
  no_tool_call: "部门连续多次没有调用工具",
  workspace_unrepresentable: "工作区有无法表示的条目",
  time_limit: "运行时间已达上限",
  cancelled: "运行已被取消",
  user_cancelled: "用户已取消",
  provider_error: "模型服务失败",
  provider_timeout: "模型服务请求超时",
  provider_protocol: "模型服务协议不符",
  unsupported_protocol: "不支持的协议",
  retry_after_too_long: "要求等待的时间过长",
  context_overflow: "上下文超过窗口",
  compaction_failed: "上下文压缩失败",
  host_commit_error: "主机保存失败",
  run_event_version_changed: "因 Yudao 升级停止",
};

export const ACTION_STATUS: Record<string, string> = {
  not_sent: "未发送",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
  // 动作被拒绝（网络与 MCP docs/design/network-and-mcp.md「调用显示」，工单 #238）：回执照常带结果与拒绝原因
  refused: "被拒绝",
  unknown: "结果未知",
};

// 取回与 MCP 调用在动作行里的类型词（网络与 MCP docs/design/network-and-mcp.md「调用显示」，工单 #238）：
// 页面写这两个词，不写 fetch_url 与 mcp__服务器__工具 这类内部标识
export const ACTION_TYPE_NAMES: Record<string, string> = {
  fetch: "网络取回",
  mcp: "MCP 调用",
};

// 决定请求里写的原因（model_unavailable 一类请求的 reason 取值，工单 #181）：与停止原因同一套词，
// 缺的一个是模型或凭据不可用。页面上按中文写，不写 provider_unavailable 这样的机器标识
export const DECISION_REASON: Record<string, string> = {
  ...STOP_REASON,
  provider_unavailable: "模型或凭据不可用",
};

// 结果未知的动作的处理方式（工单 #181，恢复契约 docs/design/recovery-contract-and-fault-matrix.md「动作分类与处置」）：核实确认是自动核实，或者用户选择按当前
// 实际状态接受；交还会话是把结果作为工具结果交给发出它的会话，由模型决定是否重新执行。
// 页面上写这两个词，不写 handed_back 这类取值
export const ACTION_HANDLING: Record<string, string> = {
  confirmed: "核实确认",
  returned: "交还会话",
};

// 处理方式对应的原型标记：核实确认已经结束，交还会话在等模型处置
export const ACTION_HANDLING_KIND: Record<string, string> = {
  confirmed: "succeeded",
  returned: "asking",
};

// 动作的用途（tool_started 的 purpose 取值）：一轮工作里的工具调用，或者压缩上下文时的调用
export const ACTION_PURPOSE: Record<string, string> = {
  work: "工作中的工具调用",
  compaction: "压缩上下文时的调用",
};

// 会话是部门主线还是询问分支（三部门的循环结构 docs/design/department-loop.md「停止与恢复」，工单 #181）：用量各自累计，页面上分开写
export const SESSION_KIND: Record<string, string> = {
  main: "部门主线",
  branch: "询问分支",
};

export const ATTEMPT_STATUS: Record<string, string> = {
  prepared: "准备中",
  requesting: "请求中",
  success: "成功",
  failed: "失败",
  running: "进行中",
  cancelled: "已取消",
};

// 指导的状态只有三种（原型 v12 设计说明第 3.4 节、部门指导的处理 docs/design/department-guidance.md「处理结果与来源」，工单 #906）：
// 已接收、已进入模型输入、已回答，没有别的状态。第三种状态的「已回答」由主机在收到指导的那一轮
// 正常结束时写，部门不提交（工单 #1039）。状态值取查询 department.workspace 的 guidance 一项。
export const GUIDANCE_STATUS: Record<string, string> = {
  received: "已接收",
  in_input: "已进入模型输入",
  answered: "已回答",
};

export const DECISION_KIND: Record<string, string> = {
  model_unavailable: "模型引用无法使用，等待恢复",
  no_tool_call: "已暂停（模型没有调用工具），等待继续",
  workspace_unrepresentable: "已暂停（工作区无法表示），等待继续",
  definitions_changed: "定义版本不同，等待选择",
  initial_prd: "接入已有项目的初始需求文档等待确认",
  kernel_modification: "交付改动了内核路径，等待批准",
  qa_cannot_verify: "质检无法核验，等待回答",
};

// 决定请求的阻塞范围（DecisionView 的 blocks 取值）：卡片头的标记按中文写，不出现内部词 run
export const DECISION_BLOCKS: Record<string, string> = {
  run: "整次运行",
  action: "单个动作",
};

export const INPUT_PROGRESS: Record<string, string> = {
  received: "已接收",
  assigned: "已交给产品处理",
  accepted: "已由有效需求接纳",
};

// 项目部门设置里每一项的来源（工单 #741）：写入了就是「本项目写入」，
// 没写入就是这一项自己的默认：模型跟随部门默认、档位跟随、部门 Prompt 用内置默认。
// 按项判断，不按设置记录判断（有设置记录但没写这一项时，这一项仍然用默认）
export function itemSource(written: boolean, fallback: string): string {
  return written ? "本项目写入" : fallback;
}

// 输入种类的中文名（work_item.inputs 的 kind 取值：文字，或用户在输入框里发出的命令）
export const INPUT_KIND: Record<string, string> = {
  text: "文字",
  command: "命令",
};

export function label(map: Record<string, string>, value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "未知";
  }
  return map[value] ?? value;
}

// 事项的进度（工单 #556）：从成果推算，不记阶段。
// 当前有效的 PRD 是第几版、最新一份交付是第几版、它依据的 PRD 版本，以及对最新交付的结论。
export interface WorkItemProgressView {
  product_spec_revision: number | null;
  delivery_revision: number | null;
  delivery_product_spec_revision: number | null;
  conclusion: string | null;
}

const CONCLUSION_LABELS: Record<string, string> = {
  rework_engineering: "缺陷记录",
  release: "放行",
};

// 进度行（三部门的循环结构 docs/design/department-loop.md「部门按关注的成果开始工作」，工单 #904 按原型 v12 第 3.2 节改写）：
// 「PRD r2 · 交付 r1（依据 PRD r2）· 结论：放行」；还没有交付时写「PRD r2 · 还没有交付」；没有结论不写。
// 什么都不写时不写这一行（还没有成果）。
export function progressLabel(progress: WorkItemProgressView | null | undefined): string | null {
  if (!progress) {
    return null;
  }
  const parts: string[] = [];
  if (progress.product_spec_revision !== null) {
    parts.push(`PRD r${progress.product_spec_revision}`);
  }
  if (progress.delivery_revision !== null) {
    const basis = progress.delivery_product_spec_revision !== null
      ? `（依据 PRD r${progress.delivery_product_spec_revision}）`
      : "";
    parts.push(`交付 r${progress.delivery_revision}${basis}`);
  } else if (parts.length > 0) {
    parts.push("还没有交付");
  }
  const head = parts.join(" · ");
  if (progress.conclusion) {
    // 结论紧接在前一项后面，与原型 v12 第 3.2 节的写法一致（「…（依据 PRD r2）· 结论：放行」）
    const conclusion = `结论：${CONCLUSION_LABELS[progress.conclusion] ?? progress.conclusion}`;
    return head === "" ? conclusion : `${head}· ${conclusion}`;
  }
  return head === "" ? null : head;
}

// 部门状态对应的状态标记（原型 v12 第 3.1 节、工单 #905）：等用户要用户处理，一轮工作中在转，
// 询问中在等对方的回答，核验中等下游的结论，等待工作在等成果
export const DEPARTMENT_STATE_KIND: Record<string, string> = {
  waiting_user: "waiting",
  working: "running",
  asking: "asking",
  verifying: "queued",
  waiting: "idle",
};

// 一个部门的状态与原因（原型 v12 第 3.1 节）：状态词，有原因时写在括号里，例如
// 「询问中（在等待产品的回答）」。原因只有四种，见三部门的循环结构 docs/design/department-loop.md「部门的状态」。
export function departmentStateText(state: DepartmentStateView): string {
  const name = DEPARTMENT_STATE[state.state] ?? state.state;
  return state.note ? `${name}（${state.note}）` : name;
}

// 部门页标题区的部门状态（原型 v12 第 3.1 节、三部门的循环结构 docs/design/department-loop.md「部门的状态」，工单 #905）：
// 事项进行中时用 departments[本部门]，写状态与原因；没有部门状态（事项还没有开始、已经结束，
// 或者进程中断以后还没有继续）时按事项的结束方式写，不再写「正在工作」与「这次运行不在本部门」。
// text 是状态词，note 是原因（没有时为空串），kind 是页面上那个状态标记的样式。
export interface DepartmentStatusView {
  text: string;
  note: string;
  kind: string;
}

export function departmentStatusView(data: {
  department: string;
  run_id: string | null;
  run_status: string | null;
  status: string | null;
  stop_reason?: string | null;
  departments?: Record<string, DepartmentStateView> | null;
}): DepartmentStatusView {
  const own = data.departments?.[data.department];
  if (own) {
    return {
      text: DEPARTMENT_STATE[own.state] ?? own.state,
      note: own.note ?? "",
      kind: DEPARTMENT_STATE_KIND[own.state] ?? "idle",
    };
  }
  if (data.run_id === null) {
    return { text: "空闲（这个范围里没有运行）", note: "", kind: "idle" };
  }
  // 用户停止的事项写「已停止」，与概览看板一致（工单 #319）
  if (data.status === "stopped") {
    return { text: "已停止", note: "", kind: "cancelled" };
  }
  // 暂停是终态，没有部门状态；写「已暂停」，不猜具体原因
  if (data.run_status === "paused") {
    return { text: "已暂停", note: "", kind: "paused" };
  }
  // run 还在进行中而没有部门状态：进程中断以后还没有继续（第 2.1 节最后一段的「中断」）
  if (data.run_status === "running") {
    return { text: "中断", note: "", kind: "cancelled" };
  }
  // 已经结束的事项按结束方式写：有停止原因时写原因（例如「已完成并放行」），没有时写 run 的状态
  if (data.stop_reason) {
    return {
      text: label(STOP_REASON, data.stop_reason),
      note: "",
      kind: data.run_status === "failed" ? "failed" : "succeeded",
    };
  }
  return {
    text: label(RUN_STATUS_LABELS, data.run_status),
    note: "",
    kind: data.run_status === "failed" ? "failed" : "succeeded",
  };
}

// 三个部门各自的状态与原因拆成一段段（三部门的循环结构 docs/design/department-loop.md「部门的状态」，工单 #904）：
// 「产品 一轮工作中（回答工程的询问） · 工程 询问中（在等待产品的回答） · 质检 等待工作」。
// 顺序取查询给出的那个（事项所用的定义里的部门顺序，工单 #1372）；current 标出本部门那一段，
// 部门工作间把它加粗（工单 #905）。没有 departments（事项没有进行中的 run）时返回 null。
export interface DepartmentsLinePart {
  text: string;
  current: boolean;
}

export function departmentsLineParts(
  departments: Record<string, DepartmentStateView> | null | undefined,
  current: string | null,
  // 部门显示名（工单 #1457）：组织给出了就用它，没有时按页面上原来的写法
  labels: Record<string, string> = {},
): DepartmentsLinePart[] | null {
  if (!departments || Object.keys(departments).length === 0) {
    return null;
  }
  return Object.keys(departments).map((department) => ({
    text: `${labels[department] ?? departmentName(department)} ${departmentStateText(departments[department])}`,
    current: department === current,
  }));
}

// 三个部门各自的状态写成一行（概览「当前事项」的那一行，工单 #904）。
// 没有 departments（事项没有进行中的 run）时返回 null，由调用处照旧写「所在部门：X」。
export function departmentsText(
  departments: Record<string, DepartmentStateView> | null | undefined,
  labels: Record<string, string> = {},
): string | null {
  return departmentsLineParts(departments, null, labels)?.map((part) => part.text).join(" · ") ?? null;
}

// 房间信息里的传信管一行（原型 v12 第 3.3 节、工单 #905）：N 封询问等待本部门回答，
// N 取房间里管道状态的 letters_waiting；为 0 时不写这一行（返回 null）。
export function lettersWaitingText(letters: number | null | undefined): string | null {
  const count = letters === null || letters === undefined || !Number.isFinite(letters)
    ? 0
    : Math.max(0, Math.trunc(letters));
  return count === 0 ? null : `传信管：${count} 封询问等待本部门回答`;
}

// 概览「当前事项」里写部门状态的那一行（工单 #904）：有 departments 时写三个部门各自的状态与原因，
// 没有时照旧写「所在部门：X」，X 取 department，没有时写「大厅」。
export function departmentLine(
  departments: Record<string, DepartmentStateView> | null | undefined,
  department: string | null | undefined,
): string {
  return departmentsText(departments) ?? `所在部门：${departmentName(department) || "大厅"}`;
}

// 看板卡片上写正在工作的部门（三部门的循环结构 docs/design/department-loop.md「各部门在什么时候工作」，工单 #904）：状态是一轮工作中或询问中的部门，
// 按查询给出的部门顺序写成「工程、质检在工作」（工单 #1372）。有这样的部门时写它；没有时不写这句话
// （返回空串，调用处这一格不出现）；查询结果里没有 departments（旧数据、没有进行中的 run）时
// 退回事项所在的部门（工单 #842 的行为：没有部门的事项，这一格不写）。
export function workingDepartmentsText(item: {
  departments?: Record<string, DepartmentStateView> | null;
  department?: string | null;
}): string {
  const departments = item.departments ?? null;
  if (departments === null) {
    return departmentName(item.department ?? null);
  }
  const working = Object.keys(departments).filter((department) => {
    const state = departments[department];
    return state !== undefined && (state.state === "working" || state.state === "asking");
  });
  if (working.length === 0) {
    return "";
  }
  return `${working.map((department) => departmentName(department)).join("、")}在工作`;
}

// 角色条在角色没有当前任务时显示的房间状态词（工单 #1230）。页面自己的一份（工单 #1415）：
// 页面上的文字归页面，不从画面取；画面那边自己的那一份在 pixel/room/layout.ts，两份不互相引用。
export const STATUS_TEXT: Record<string, string> = {
  idle: "未工作", working: "工作中", asking: "等待回答", paused: "已暂停", failed: "失败", done: "已完成",
  cancelled: "已取消", interrupted: "中断", waiting_resume: "待恢复",
};

// 房间角色条上那一格的文字（工单 #1230）：角色的 task 只在有事实说明它此刻做什么时才填。
// 现在系统里没有这样的事实（一个部门只有一个角色，没有哪一项记录写着它此刻手上的事），
// 所以这一格显示房间状态词表里的中文状态（工作中、未工作、等待回答……），不显示 working、idle
// 这样的原始标识；事项标题不当作角色的当前任务，它只留在房间屏幕的目标行。
export function roleBarText(role: { task?: string | null; status: string }): string {
  const task = (role.task ?? "").trim();
  if (task !== "") {
    return task;
  }
  return STATUS_TEXT[role.status] ?? role.status;
}

export function departmentName(value: string | null | undefined): string {
  if (!value) {
    // 事项停止后没有在处理的部门；调用处按位置决定写「没有」还是省略这一格
    return "";
  }
  return DEPARTMENTS[value]?.name ?? value;
}

// 停止说明（工单 #1162）：让事项停下的那条错误的原文，取自事项结束的事件，页面原样写出，不改写。
// 服务端只给停止的事项这一项，询问分支的失败原因不在其中；空白的当没有。
// 短的一行写完，长的折起来（原样保留全文，点开看），免得一条 400 的应答把卡片撑满。
export const STOP_NOTE_INLINE_LIMIT = 120;

export type StopNoteView =
  | { kind: "none"; keptDelivery?: string }
  | { kind: "inline"; text: string; keptDelivery?: string }
  | { kind: "folded"; text: string; keptDelivery?: string };

// 已收下的交付（工单 #1239）：事项停止时这个 run 里已经收下的一版交付，写在停止说明下面一行。
// 用户自己取消时也写，交付仍然在；没有已收下的交付（或者事项没有停止）时没有这一项。
export type KeptDeliveryView = { version?: number | null; accepted_at?: string | null } | null | undefined;

export function keptDeliveryLine(kept: KeptDeliveryView): string | undefined {
  const version = kept?.version;
  if (version === null || version === undefined) {
    return undefined;
  }
  return `交付 r${version} 已于 ${formatTime(kept?.accepted_at)} 收下，尚未经质检放行`;
}

export function stopNoteView(note: string | null | undefined, kept?: KeptDeliveryView): StopNoteView {
  const text = note ?? "";
  const keptDelivery = keptDeliveryLine(kept);
  const extra = keptDelivery === undefined ? {} : { keptDelivery };
  if (text.trim() === "") {
    return { kind: "none", ...extra };
  }
  return text.length <= STOP_NOTE_INLINE_LIMIT
    ? { kind: "inline", text, ...extra }
    : { kind: "folded", text, ...extra };
}

// 上游失败的细节（工单 #1373）：停止原因是模型服务时，事件里本来就有发起这次请求的部门、
// 请求的模型、服务返回的状态码与这次失败可不可重试，此前页面只写停下的那句原文
// 「Model provider returned HTTP 503」，用户分辨不出是上游挂了还是自己配错了。
// 四项都有时写成一句「工程部门请求的模型 wb/cn:deepseek-v4.1-flash，服务返回 HTTP 503，不可重试」；
// 缺哪一项就不写哪一项，四项都没有时没有这一行（返回 null）。
export interface StopDetailView {
  department?: string | null;
  requested_model?: string | null;
  status_code?: number | null;
  retryable?: boolean | null;
}

export function stopDetailText(detail: StopDetailView | null | undefined): string | null {
  if (!detail) {
    return null;
  }
  const parts: string[] = [];
  const department = departmentName(detail.department ?? null);
  const model = (detail.requested_model ?? "").trim();
  if (department !== "" && model !== "") {
    parts.push(`${department}部门请求的模型 ${model}`);
  } else if (department !== "") {
    parts.push(`${department}部门`);
  } else if (model !== "") {
    parts.push(`请求的模型 ${model}`);
  }
  const status = detail.status_code;
  if (typeof status === "number" && Number.isFinite(status)) {
    parts.push(`服务返回 HTTP ${status}`);
  }
  if (detail.retryable === true) {
    parts.push("可重试");
  } else if (detail.retryable === false) {
    parts.push("不可重试");
  }
  return parts.length === 0 ? null : parts.join("，");
}

// 停止的卡片上认事项的那一行（工单 #1373）：同一项目里几张同名的失败卡片要能分辨——
// 哪一张（事项标识，与「当前事项」那一处的写法一致）与什么时候停的（事项结束的那条事件的时间）。
// 时间缺失时照页面上其余时间的写法写「未知时间」。
export function stoppedCardLine(item: { work_item_id: string; stopped_at?: string | null }): string {
  return `事项标识 ${item.work_item_id} · 停止于 ${formatTime(item.stopped_at)}`;
}

// 离开期间的报告里的开环明细（工单 #401；验证的独立性 docs/design/independent-verification.md「检验覆盖与开环」、「口径」）：每个带开环条件的放行
// 列出它的验收条件，条数取 `acceptance.coverage` 的数——放行记录里一次算好，查询与页面读这个数，
// 不重新计算。条件编号是产品合同里的验收条件编号（AC2 这类），不是内部标识。
export function openCriteriaText(count: number, criteria: readonly string[]): string {
  const names = criteria.filter((name) => name.trim() !== "").join("、");
  return names === "" ? `开环条件 ${count} 条` : `开环条件 ${count} 条：${names}`;
}

// 开环明细还没有读到与读不出来（工单 #401）：两句话分开，与页面其余地方一样，
// 「正在读取」不当成「没有开环条件」，「读不出来」也不当成「本来就没有」
export const OPEN_CRITERIA_READING = "正在读取开环明细";
export const OPEN_CRITERIA_UNREADABLE = "开环明细读不出来";

// 事项标题取不到时的写法：与离开期间的报告原来的说法一致，不写事项标识（工单 #401）
export const WORK_ITEM_UNNAMED = "未记事项";

// 「跳到逐条结论表」的链接（工单 #401）：逐条结论表在资料页（工单 #154）。软依赖，不等 #154——
// 那张表还没有的时候链接不出现（点不到一张不存在的表）。#154 合并以后这一行是 true，
// 链接跟着出现在每条开环明细后面；链接的地址与页名由调用处按 paths.materials 给出。
export const CRITERIA_TABLE_READY = true;
export const CRITERIA_TABLE_LINK = "跳到逐条结论表";

// 检验方式与结果的中文名（验证的独立性 docs/design/independent-verification.md「口径」，工单 #154）：质检逐条结论里保存的是
// 六个代码名与三个结果词，页面上写中文。页面不导入翻译层（页面与翻译层的导入方向，工单 #1415），
// 所以这里留一份；它与 client/tests/fixtures/check-methods.json 由单元测试逐行核对，
// 与服务端那一份相同。
export interface CheckMethodRow {
  readonly label: string;
  readonly executable: boolean;
}

export const CHECK_METHODS: Readonly<Record<string, CheckMethodRow>> = Object.freeze({
  check: { label: "命令检查", executable: true },
  trial: { label: "试用用例", executable: true },
  measure: { label: "主机测量", executable: true },
  judgement: { label: "带参照材料的判定点", executable: false },
  human: { label: "人", executable: false },
  open: { label: "开环", executable: false },
});

// 一种检验方式的中文名：没写方式与没登记的方式各有说法，代码名不写到页面上
export function checkMethodName(value: string | null | undefined): string {
  const method = (value ?? "").trim();
  if (method === "") {
    return "未写明检验方式";
  }
  return CHECK_METHODS[method]?.label ?? "其他检验方式";
}

// 逐条结论的三种结果（docs/design/independent-verification.md「口径」第 2 点）：通过、不通过、未核验
export const CHECK_RESULT_LABELS: Readonly<Record<string, string>> = Object.freeze({
  passed: "通过",
  failed: "不通过",
  unverified: "未核验",
});

export const CHECK_RESULT_KIND: Readonly<Record<string, string>> = Object.freeze({
  passed: "succeeded",
  failed: "failed",
  unverified: "idle",
});

export function checkResultName(value: string | null | undefined): string {
  const result = (value ?? "").trim();
  if (result === "") {
    return "未写明结果";
  }
  return CHECK_RESULT_LABELS[result] ?? "其他结果";
}

export function checkResultKind(value: string | null | undefined): string {
  return CHECK_RESULT_KIND[(value ?? "").trim()] ?? "idle";
}

// 试用用例的结论多一个中断（会话结束或中断时主机记下的，不能作为证据）
export function trialCaseResultName(value: string | null | undefined): string {
  const result = (value ?? "").trim();
  if (result === "") {
    return "";
  }
  return result === "interrupted" ? "中断" : checkResultName(result);
}

// 试用记录页签（工单 #153；浏览器与 computer use docs/design/browser-and-computer-use.md「查询」、「页面与画面」）：
// 会话、用例与步骤的取值在页面上写中文。web、delivery_snapshot、completed 与 browser_click 这类代码名不写到
// 页面上，认不出的取值各有一句说法。
export const TRIAL_SESSION_KIND: Readonly<Record<string, string>> = Object.freeze({
  web: "网页",
  desktop: "桌面",
});

// 试用副本的来源：质检从交付快照建立副本，其余部门从运行工作区的封存建立
export const TRIAL_COPY_SOURCE: Readonly<Record<string, string>> = Object.freeze({
  delivery_snapshot: "交付快照的副本",
  workspace_seal: "运行工作区的副本",
});

// 试用会话的结束方式（试用的恢复契约 docs/design/browser-and-computer-use.md「恢复契约」的 trial_stop 一行）
export const TRIAL_END_REASON: Readonly<Record<string, string>> = Object.freeze({
  stopped: "已停止",
  replaced: "被新会话替换",
  interrupted: "中断",
  user_stopped: "用户停止",
  run_ended: "运行结束",
});

// 试用用例里一步的结果状态（docs/design/browser-and-computer-use.md「试用用例」）：有回执、核实过、结果未知
export const TRIAL_STEP_STATUS: Readonly<Record<string, string>> = Object.freeze({
  completed: "已完成",
  verified: "已核实",
  unknown: "结果未知",
});

// 一个步骤的操作名称（docs/design/browser-and-computer-use.md「提供的工具」、「动作集合」）：模型给的调用参数不外露，
// 输入的文字是这次试用自己的内容，写在操作后面
export const TRIAL_TOOL_NAMES: Readonly<Record<string, string>> = Object.freeze({
  browser_navigate: "打开页面",
  browser_navigate_back: "回到上一页",
  browser_click: "点击页面上的元素",
  browser_hover: "在页面元素上悬停",
  browser_drag: "在页面上拖动",
  browser_type: "输入文字",
  browser_fill_form: "填写表单",
  browser_select_option: "选择下拉选项",
  browser_press_key: "按键",
  browser_file_upload: "上传文件",
  browser_handle_dialog: "处理页面弹窗",
  browser_drop: "把文件拖到页面里",
  browser_wait_for: "等待页面变化",
  browser_tabs: "切换页面标签",
  browser_resize: "调整页面窗口大小",
  browser_emulate_media: "模拟媒体样式",
  browser_close: "关闭页面",
  browser_snapshot: "读取页面结构",
  browser_find: "在页面里查找",
  browser_console_messages: "读取页面控制台消息",
  browser_network_requests: "读取页面的网络请求",
  browser_network_request: "读取一条网络请求",
  browser_verify_element_visible: "核对页面上的元素可见",
  browser_verify_text_visible: "核对页面上出现指定的文字",
  browser_verify_list_visible: "核对页面上的列表",
  browser_verify_value: "核对页面上的取值",
  browser_generate_locator: "生成页面元素的位置",
  browser_take_screenshot: "截取页面截图",
  screen_click: "点击屏幕",
  screen_drag: "在屏幕上拖动",
  screen_key: "在屏幕上按键",
  screen_move: "移动屏幕指针",
  screen_screenshot: "截取屏幕截图",
  screen_scroll: "滚动屏幕",
  screen_type: "在屏幕上输入文字",
  screen_wait: "等待屏幕变化",
  run_check: "运行检查",
});

// 未知的取值写一句自己的说法，不把代码名写到页面上
export function trialSessionKindName(value: string | null | undefined): string {
  const kind = (value ?? "").trim();
  if (kind === "") {
    return "未注明种类";
  }
  return TRIAL_SESSION_KIND[kind] ?? "其他种类";
}

export function trialCopySourceName(value: string | null | undefined): string {
  const source = (value ?? "").trim();
  if (source === "") {
    return "未注明副本来源";
  }
  return TRIAL_COPY_SOURCE[source] ?? "其他副本来源";
}

export function trialEndReasonName(value: string | null | undefined): string | null {
  const reason = (value ?? "").trim();
  if (reason === "") {
    return null;
  }
  return TRIAL_END_REASON[reason] ?? "其他结束方式";
}

export function trialStepStatusName(value: string | null | undefined): string {
  const status = (value ?? "").trim();
  if (status === "") {
    return "未写明结果状态";
  }
  return TRIAL_STEP_STATUS[status] ?? "其他结果状态";
}

// 质检的会话标明试用副本是否等于交付快照（查询给出的是、否与没有可比较的一份三种）：
// 页面写这个结论，不写树摘要原文——那是内部的标识
export function trialSnapshotText(session: {
  source?: string | null;
  matches_delivery_snapshot?: boolean | null;
}): string {
  const copy = trialCopySourceName(session.source);
  // 只有从交付快照建立的会话才有这个比较；其余来源（运行工作区的副本）与旧数据不写这一句
  if ((session.source ?? "").trim() !== "delivery_snapshot") {
    return copy;
  }
  if (session.matches_delivery_snapshot === true) {
    return `${copy}，与交付快照相同`;
  }
  if (session.matches_delivery_snapshot === false) {
    return `${copy}，与交付快照不同`;
  }
  return `${copy}，没有可比较的交付快照`;
}

export function trialSessionStateName(session: {
  status: string;
  end_reason?: string | null;
}): string {
  if (session.status === "running") {
    return "进行中";
  }
  const reason = trialEndReasonName(session.end_reason);
  return reason === null ? "已结束" : `已结束（${reason}）`;
}

// 一个步骤的操作：工具名与输入里人读得懂的几项组合成一句话，代码名与调用参数不出现
export function trialOperationText(
  tool: string | null | undefined,
  input: Record<string, unknown> | null | undefined,
): string {
  const name = (tool ?? "").trim();
  const detail = typeof input?.text === "string" ? input.text.trim() : "";
  if (name === "browser_type" || name === "screen_type") {
    return detail === "" ? "输入文字" : `输入文字「${detail}」`;
  }
  if (name === "browser_verify_text_visible") {
    return detail === "" ? "核对页面上出现指定的文字" : `核对页面上出现「${detail}」`;
  }
  if (name === "browser_find") {
    return detail === "" ? "在页面里查找" : `在页面里查找「${detail}」`;
  }
  return TRIAL_TOOL_NAMES[name] ?? "其他试用操作";
}

// 一张截图旁边写模型有没有看到它（docs/design/browser-and-computer-use.md「页面与画面」）：
// 收到这一结果的请求不含图像时写「模型只读取文字」，截图照常显示；没有下一次请求记录时照实写不知道
export const TRIAL_TEXT_ONLY_NOTICE = "模型只读取文字：这次试用里模型收到的内容只有文字，截图照常保存为证据、模型没有看到图像。";
export const TRIAL_SHOT_SEEN = "模型看到了这张截图";
export const TRIAL_SHOT_UNSEEN = "模型只读取文字";
export const TRIAL_SHOT_UNKNOWN = "没有记录模型是否看到这张截图";

export function trialShotModelText(modelSaw: boolean | null): string {
  if (modelSaw === true) {
    return TRIAL_SHOT_SEEN;
  }
  if (modelSaw === false) {
    return TRIAL_SHOT_UNSEEN;
  }
  return TRIAL_SHOT_UNKNOWN;
}

// 用例的结论：还没有结论时写进行中；四种结论与逐条结论的三种结果共用同一组词，中断单独一种
export function trialCaseResultView(item: {
  status: string;
  result?: string | null;
}): { text: string; kind: string } {
  if (item.status === "open") {
    return { text: "进行中", kind: "running" };
  }
  const result = (item.result ?? "").trim();
  if (result === "interrupted") {
    return { text: "中断", kind: "cancelled" };
  }
  const text = trialCaseResultName(result);
  return { text: text === "" ? "未写明结果" : text, kind: checkResultKind(result) };
}

export const TRIAL_EVIDENCE_TAG = "证据";
export const TRIAL_NO_SESSION = "这个部门这次运行没有试用会话";
export const TRIAL_NO_CASE = "这个部门这次运行没有试用用例";
export const TRIAL_UNNAMED_CASE = "未命名试用用例";
export const TRIAL_UNNAMED_LAUNCH = "未命名启动方式";
export const TRIAL_UNNAMED_CRITERION = "未写编号的验收条件";

// 交付说明里的启动方式（浏览器与 computer use docs/design/browser-and-computer-use.md「启动方式」，工单 #154）：种类与命令表按系统写中文
export const LAUNCH_KIND_LABELS: Readonly<Record<string, string>> = Object.freeze({
  web: "网页",
  desktop: "桌面",
});

export const LAUNCH_SYSTEM_LABELS: Readonly<Record<string, string>> = Object.freeze({
  windows: "Windows",
  linux: "Linux",
});

export function launchKindName(value: string | null | undefined): string {
  const kind = (value ?? "").trim();
  if (kind === "") {
    return "未注明种类";
  }
  return LAUNCH_KIND_LABELS[kind] ?? "其他种类";
}

export function launchSystemName(value: string | null | undefined): string {
  const system = (value ?? "").trim();
  return LAUNCH_SYSTEM_LABELS[system] ?? "其他系统";
}

// 质检结论（QAReview 的 verdict）：三种词，与逐条结论的三种结果不是同一组
export const VERDICT_LABELS: Readonly<Record<string, string>> = Object.freeze({
  release: "放行",
  rework_engineering: "缺陷记录",
  cannot_verify: "无法核验",
});

export function verdictName(value: string | null | undefined): string {
  const verdict = (value ?? "").trim();
  if (verdict === "") {
    return "未写明结论";
  }
  return VERDICT_LABELS[verdict] ?? "其他结论";
}

// 检验覆盖的读取状态与截图的读取状态（工单 #154）：读不出来与正在读分开写，不把读不出来写成没有
export const COVERAGE_UNREADABLE = "检验覆盖的数读不出来";
export const SCREENSHOT_READING = "正在读取截图";
export const SCREENSHOT_UNREADABLE = "截图读不出来";

// 交付与合同的版本状态（work_item.materials 的 VersionEntry.status，工单 #154）：页面上写中文，
// 不把 active、superseded 这类代码名写到页面
export const VERSION_STATUS_LABELS: Readonly<Record<string, string>> = Object.freeze({
  active: "当前版本",
  superseded: "已被取代",
});

export function versionStatusName(value: string | null | undefined): string {
  const status = (value ?? "").trim();
  if (status === "") {
    return "未写明状态";
  }
  return VERSION_STATUS_LABELS[status] ?? "其他状态";
}

export function formatTime(value: string | null | undefined): string {
  if (!value) {
    return "未知时间";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "未上报";
  }
  return value.toLocaleString("zh-CN");
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return "未知";
  }
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) {
    return `${total} 秒`;
  }
  if (total < 3600) {
    return `${Math.floor(total / 60)} 分 ${total % 60} 秒`;
  }
  return `${Math.floor(total / 3600)} 小时 ${Math.floor((total % 3600) / 60)} 分`;
}

// 顶栏的连接状态文字（工单 #653）：三档由事件流的状态本身给出。
// 「连接中断」只在事件流建立过以后断开时出现，断开的时间是那一刻的真实时刻，
// 不用「刚刚」兜底；初次连接期间说「连接中」，不声称断开过。
export function connectionText(stream: StreamState): string {
  if (stream.kind === "connecting") {
    return "连接中 · 正在建立事件流";
  }
  if (stream.kind === "connected") {
    return "已连接";
  }
  return `连接中断 · ${formatTime(stream.disconnectedAt)}断开，正在重新连接`;
}
