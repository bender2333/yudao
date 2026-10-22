// 命令没有成功时的三种形状与它们的判别（工单 #740）。
// 判别只看两样东西：响应的状态码与响应体的形状。
//
// 应用层拒绝（409）：响应体是 Rejected，有拒绝原因与中文说明两个字段，页面原样显示服务端的话；
// 接口层校验错误（422）：响应体是字段错误明细（detail 数组）加服务端给的一句中文说明（error 字段），
// 页面显示服务端的那句话——字段错误明细不直接摆给用户；
// 其余（网络不通、5xx、404）：响应体不是上面两种形状，页面写一句「这次请求没有成功」。
//
// 早先的做法是把任何 response.error 都当成 Rejected，于是 422 的字段错误明细被当成拒绝，
// 页面读到的是一个没有 message 的对象，渲染出一个空的错误框（工单 #740）。

import type { Rejected } from "../api/generated/types.gen";

// 命令没有成功时页面上要显示的那句话的来源
export type CommandProblem =
  | { kind: "rejected"; rejection: Rejected }
  // invalid 带两样东西：服务端给的那句中文说明（note）与响应体本身（body）。
  // 页面显示 note；按 JSON 编辑原始文档的地方（模型管理页）要的是字段位置，从 body 里取
  | { kind: "invalid"; note: string; body: unknown }
  | { kind: "failed"; status: number };

// 响应体是不是应用层的拒绝：拒绝原因与中文说明两个字段都在才算
export function isRejectedBody(value: unknown): value is Rejected {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const body = value as { reason?: unknown; message?: unknown };
  return typeof body.reason === "string" && typeof body.message === "string";
}

// 服务端给的说明：422 的响应体里有一句中文说明（error 字段），页面直接显示它
export function serverNote(error: unknown): string {
  if (error === null || typeof error !== "object") {
    return "";
  }
  const note = (error as { error?: unknown }).error;
  return typeof note === "string" ? note.trim() : "";
}

// 按状态码与响应体判别命令失败属于哪一种。
// error 是响应体（生成客户端把失败时的响应体放在 error 字段），status 是 HTTP 状态码；
// 没有响应时（网络不通）状态码是 0
export function classifyCommandFailure(error: unknown, status: number): CommandProblem {
  if (isRejectedBody(error)) {
    return { kind: "rejected", rejection: error };
  }
  if (status === 422) {
    return { kind: "invalid", note: serverNote(error), body: error };
  }
  return { kind: "failed", status };
}

// 命令被拒绝时的说明：基准版本过期时提示重新读取（工单验收第 3 条）。
// 原因标识是内部词，不写进页面（工单 #319 第 5 项）；服务端的消息本身已经是中文说明
export function rejectionLabel(rejection: Rejected): string {
  if (rejection.reason === "stale_base") {
    const version = rejection.current_version === null || rejection.current_version === undefined
      ? "未知"
      : rejection.current_version;
    return `${rejection.message}（服务端当前版本 ${version}），请重新读取以后提交`;
  }
  return rejection.message;
}

// 命令没有成功时页面上显示的那句话（工单 #740）：
// - 应用层拒绝：服务端给了中文说明，原样显示；
// - 接口层校验错误：服务端给了中文说明（哪个字段、要求是什么），原样显示；
//   服务端没有给说明时写一句通用的，不把字段错误明细摆到页面上；
// - 其余（网络不通、5xx、404）：一句中文，写明这次请求没有成功。
export function commandProblemText(problem: CommandProblem): string {
  if (problem.kind === "rejected") {
    return rejectionLabel(problem.rejection);
  }
  if (problem.kind === "invalid") {
    return problem.note === ""
      ? "这次请求被拒绝：提交的内容没有通过服务端的检查，请修改以后再提交。"
      : problem.note;
  }
  return failedRequestText(problem.status);
}

// 其余失败按状态码写一句中文：说清这次请求没有成功，不写状态码与英文机器短语
function failedRequestText(status: number): string {
  if (status === 0) {
    return "这次请求没有送到服务端：联系不上服务，请确认服务还在运行以后再提交。";
  }
  if (status === 401) {
    return "这次请求没有成功：身份校验没有通过，请重新填写访问令牌以后再提交。";
  }
  if (status === 404) {
    return "这次请求没有成功：服务端没有这个命令。";
  }
  if (status >= 500) {
    return "这次请求没有成功：服务处理时出错了，请过一会儿再提交。";
  }
  return "这次请求没有成功：服务没有接受这次请求，请过一会儿再提交。";
}
