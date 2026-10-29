// 恢复页的文字与状态映射（工单 #181，原型 v13 `js/ui/views/recovery.js`，沿用 v12、v11、v10 的设计说明第 7.2 节）。
// 页面只按这里的结果显示：最后已确认的位置、自动继续的时间、结果未知的动作与它的处理方式、
// 各会话的用量。纯函数，客户端单元测试直接调用它核对文字；页面上因此不出现内部标识
// （handed_back、work、main 这些取值都在这里换成中文）。

import type {
  RecoveryOwner,
  RecoverySession,
} from "../../api/generated/types.gen.ts";
import {
  ACTION_HANDLING,
  ACTION_HANDLING_KIND,
  ACTION_PURPOSE,
  SESSION_KIND,
  departmentName,
  formatTime,
  label,
} from "./labels.ts";

// 四种结束方式（原型 rc-reason）：按状态给出不同的说明。
// 正常完成不是被中止（工单 #747），被取消是用户自己的决定。
export const TERMINAL_NOTE: Record<string, string> = {
  completed: "已完成的运行不再继续；未完成动作不由恢复处理。",
  paused: "运行暂停，等待处理；处理以后可以继续。",
  cancelled: "取消是用户自己的决定；未完成动作不由恢复处理。",
  stopped: "已停止的运行不再继续；未完成动作不由恢复处理。",
};

// 还没有处置的动作状态对应的原型标记与样式（原型 v10 views/recovery.js 的 ACTION_KIND 与 ACTION_CLASS）
export const UNFINISHED_KIND: Record<string, string> = {
  not_sent: "pending",
  unknown: "unknown",
};

export const UNFINISHED_CLASS: Record<string, string> = {
  not_sent: "is-not_sent",
  unknown: "is-unknown",
};

// 最后已确认的位置（设计说明第 4.3 节）：文字取自这条事件，页面据此写出这一步做完了什么；
// 事件还没有说明时写第几条事件，还没有事件时照实说没有
export function lastConfirmedText(data: {
  last_confirmed_text: string | null;
  last_confirmed_position: number;
}): string {
  if (data.last_confirmed_text) {
    return data.last_confirmed_text;
  }
  return data.last_confirmed_position > 0
    ? `第 ${data.last_confirmed_position} 条事件`
    : "还没有已确认的事件";
}

// 自动继续的时间：取得执行权的那一刻；还没有继续过时写「还没有自动继续」
export function autoResumeText(owner: RecoveryOwner | null): string {
  return owner === null || owner.since === "" ? "还没有自动继续" : formatTime(owner.since);
}

// 这次取得执行权所依据的中断位置：那次中断时最后一条已提交事件的文字
export function interruptedAtText(owner: RecoveryOwner | null): string {
  if (owner === null || !owner.interrupted_at_text) {
    return "没有记录";
  }
  return owner.interrupted_at_text;
}

// 一个动作的处理方式（核实确认或交还会话）
export function handlingText(handling: string): string {
  return label(ACTION_HANDLING, handling);
}

// 处理方式对应的原型标记：没有登记的处理方式按等待处置画
export function handlingKind(handling: string): string {
  return ACTION_HANDLING_KIND[handling] ?? "waiting";
}

// 处理方式的一句说明：核实确认以后动作没有再执行，交还会话由模型决定是否重新执行
export function handlingNote(handling: string): string {
  return handling === "returned"
    ? "结果作为工具结果交还发出它的会话，由模型检查以后决定是否重新执行；没有向你发出决定请求。"
    : "核实确认按核实方法得出结果，动作没有因此重新执行。";
}

// 还没有处置的动作：进程中断时它还没有回执，重新启动以后按核实方法核实，或者交还发出它的会话
export const PENDING_NOTE = "进程中断时这个动作还没有回执；重新启动以后按核实方法核实，核实不出确定结果时交还发出它的会话。";

// 动作的用途：工作中还是压缩上下文时的调用；没有登记时只写「工具调用」
export function purposeText(purpose: string | null | undefined): string {
  const text = (purpose ?? "").trim();
  return text === "" ? "工具调用" : (ACTION_PURPOSE[text] ?? "工具调用");
}

// 每个会话是同一部门的第几个分支：主线为 0，分支按顺序从 1 数
function branchOrdinals(sessions: RecoverySession[]): number[] {
  let branches = 0;
  return sessions.map((row) => (row.kind === "branch" ? (branches += 1) : 0));
}

// 一个会话在页面上的名字（原型 sessionsTable 的会话一列）：部门加部门主线或询问分支，
// 同一部门的分支再按顺序编号，免得两行重名
export function sessionLabel(row: RecoverySession, branchOrdinal: number): string {
  const department = departmentName(row.department) || "未知部门";
  const kind = label(SESSION_KIND, row.kind);
  return row.kind === "branch" ? `${department} · ${kind} ${branchOrdinal}` : `${department} · ${kind}`;
}

export interface SessionUsageRow {
  key: string;
  label: string;
  elapsedSec: number;
  activations: number;
  modelSteps: number;
}

// 各会话的用量表（原型 sessionsTable）：顺序照查询给出的部门顺序
export function sessionUsageRows(sessions: RecoverySession[]): SessionUsageRow[] {
  const ordinals = branchOrdinals(sessions);
  return sessions.map((row, index) => ({
    key: row.session_id,
    label: sessionLabel(row, ordinals[index]),
    elapsedSec: row.elapsed_sec,
    activations: row.activations,
    modelSteps: row.model_steps,
  }));
}

// 一个动作所在会话的名字：按会话的用量表解析；查不到时照实说未上报，页面上不写会话标识
export function actionSessionText(sessions: RecoverySession[], sessionId: string | null): string {
  const index = sessionId === null ? -1 : sessions.findIndex((entry) => entry.session_id === sessionId);
  if (index < 0) {
    return "未上报";
  }
  return sessionLabel(sessions[index], branchOrdinals(sessions)[index]);
}

// 恢复页要不要显示「这次中断」的记录（工单 #181）：自动继续过以后，运行中的页面仍显示这次中断
export function showsInterruptionRecord(data: { state: string; owner: RecoveryOwner | null }): boolean {
  if (data.owner === null || data.owner.interrupted_at_event_id === null) {
    return false;
  }
  return data.state === "running" || data.state === "interrupted";
}
