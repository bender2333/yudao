// 页面显示用的名称（原型 v8 设计说明第 14 节用词；取值来自应用层的查询结果，未知值原样显示，不做猜测）。
// 单一来源：harness/app/labels.py 里的部门、阶段与状态名称，客户端按生成的合同取值对应显示。

import type { StreamState } from "../../contract/stream-state";
// 角色条在角色没有当前任务时显示房间状态词表里的中文状态（工单 #1230）
import { STATUS_TEXT } from "../../pixel/room/layout.ts";

export const DEPARTMENTS: Record<string, { name: string; role: string }> = {
  product: { name: "产品", role: "把用户的要求整理成有效需求" },
  engineering: { name: "工程", role: "按有效需求实现并封存交付" },
  quality: { name: "质检", role: "按验收条件核验并给出放行或缺陷记录" },
};

// 部门状态的中文名（三部门的循环结构第 2.1 节，工单 #904）：总图第三节外环的五个词，页面上只写这一处。
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

// 页面上列部门的顺序：产品、工程、质检（部门表本身的顺序，工单 #904）
const DEPARTMENT_ORDER = Object.keys(DEPARTMENTS);

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
  unknown: "结果未知",
};

// 决定请求里写的原因（model_unavailable 一类请求的 reason 取值，工单 #181）：与停止原因同一套词，
// 缺的一个是模型或凭据不可用。页面上按中文写，不写 provider_unavailable 这样的机器标识
export const DECISION_REASON: Record<string, string> = {
  ...STOP_REASON,
  provider_unavailable: "模型或凭据不可用",
};

// 结果未知的动作的处理方式（工单 #181，恢复契约第 4 节）：核实确认是自动核实，或者用户选择按当前
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

// 会话是部门主线还是询问分支（三部门的循环结构第 9 节，工单 #181）：用量各自累计，页面上分开写
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

// 指导的状态只有三种（原型 v12 设计说明第 3.4 节、部门指导的处理设计第 3 节，工单 #906）：
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

// 进度行（三部门的循环结构第 2 节，工单 #904 按原型 v12 第 3.2 节改写）：
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
// 「询问中（在等待产品的回答）」。原因只有四种，见三部门的循环结构第 2.1 节。
export function departmentStateText(state: DepartmentStateView): string {
  const name = DEPARTMENT_STATE[state.state] ?? state.state;
  return state.note ? `${name}（${state.note}）` : name;
}

// 部门页标题区的部门状态（原型 v12 第 3.1 节、三部门的循环结构第 2.1 节，工单 #905）：
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

// 三个部门各自的状态与原因拆成一段段（三部门的循环结构第 2.1 节，工单 #904）：
// 「产品 一轮工作中（回答工程的询问） · 工程 询问中（在等待产品的回答） · 质检 等待工作」。
// 只写查询结果里有的部门，按产品、工程、质检的顺序；current 标出本部门那一段，
// 部门工作间把它加粗（工单 #905）。没有 departments（事项没有进行中的 run）时返回 null。
export interface DepartmentsLinePart {
  text: string;
  current: boolean;
}

export function departmentsLineParts(
  departments: Record<string, DepartmentStateView> | null | undefined,
  current: string | null,
): DepartmentsLinePart[] | null {
  if (!departments || Object.keys(departments).length === 0) {
    return null;
  }
  const order = [
    ...DEPARTMENT_ORDER.filter((department) => department in departments),
    ...Object.keys(departments).filter((department) => !DEPARTMENT_ORDER.includes(department)),
  ];
  return order.map((department) => ({
    text: `${departmentName(department)} ${departmentStateText(departments[department])}`,
    current: department === current,
  }));
}

// 三个部门各自的状态写成一行（概览「当前事项」的那一行，工单 #904）。
// 没有 departments（事项没有进行中的 run）时返回 null，由调用处照旧写「所在部门：X」。
export function departmentsText(
  departments: Record<string, DepartmentStateView> | null | undefined,
): string | null {
  return departmentsLineParts(departments, null)?.map((part) => part.text).join(" · ") ?? null;
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

// 看板卡片上写正在工作的部门（三部门的循环结构第 3.1 节，工单 #904）：状态是一轮工作中或询问中的部门，
// 按产品、工程、质检的顺序写成「工程、质检在工作」。有这样的部门时写它；没有时不写这句话
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
  const working = DEPARTMENT_ORDER.filter((department) => {
    const state = departments[department];
    return state !== undefined && (state.state === "working" || state.state === "asking");
  });
  if (working.length === 0) {
    return "";
  }
  return `${working.map((department) => departmentName(department)).join("、")}在工作`;
}

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
