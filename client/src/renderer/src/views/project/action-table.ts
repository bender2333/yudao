// 动作与回执的文字（工单 #655、#658；工单 #1235 起由部门工作间的步骤时间线使用）。
// 「登记名」一列按 ADR-0038 删除命令登记以后恒为「没有回执」，不再有这一项；
// 「命令」一项按 ADR-0038 显示命令原文，凭据在后端已经换成名称，界面上没有密钥原文。
//
// 取回与 MCP 调用各占一行（网络与 MCP docs/design/network-and-mcp.md「调用显示」，工单 #238）：
// 类型、目标（地址，或服务器与工具名）、状态（成功、失败、被拒绝、结果未知）、耗时、结果摘要与
// 外部来源工件的链接；结果未知时显示交还给模型的内容。行的文字都在这里算，页面只按结果排版。
// 这个模块没有运行期依赖：客户端单元测试直接调用它核对文字。

import type { ActionReceipt, ActionView, FetchReceipt } from "../../api/generated/types.gen";
import { ACTION_STATUS, ACTION_TYPE_NAMES, departmentName, label } from "./labels.ts";

// 一个动作的文字：工具、命令、部门、状态、结果与输出引用。
// 步骤时间线用其中的工具、命令、状态、结果与输出引用；部门在时间线里不写（整个页签就是本部门的）
export function actionCells(action: ActionView): string[] {
  const receipt = action.receipt;
  return [
    action.tool,
    commandOf(action),
    departmentName(action.department),
    label(ACTION_STATUS, action.status),
    receipt === null ? "没有回执" : (receipt.ok ? "成功" : (receipt.error || "失败")),
    receipt?.output_ref ? "有（见原始事件）" : "无",
  ];
}

// 动作实际执行的命令：bash 与 run_check 的参数里是命令原文；别的工具没有命令。
export function commandOf(action: ActionView): string {
  const command = action.receipt?.args?.command;
  return typeof command === "string" ? command : "";
}

// ---------------------------------------------------------------------------
// 取回与 MCP 调用的行（工单 #238）

// 动作的种类：取回、MCP 调用，或其余工具。种类只由工具名判断；
// MCP 工具名是带服务器范围的别名（mcp__服务器__工具），原名在校验时已经损失，页面上不写别名。
export type ActionKind = "fetch" | "mcp" | "other";

export function actionKind(action: ActionView): ActionKind {
  if (action.tool === "fetch_url") {
    return "fetch";
  }
  return action.tool.startsWith("mcp__") ? "mcp" : "other";
}

// 一份外部来源工件的引用：查询 evidence.external_source 时按这四项与所属事件的编号取内容
export interface ExternalSourceRefView {
  eventId: string;
  kind: string;
  contentHash: string;
  path: string;
  mediaType: string | null;
}

// 行的补充输入：交还给模型的内容取自 run.recovery，工具结果工件取自 event.detail
export interface ActionRowExtras {
  returned?: string | null;
  output?: Record<string, unknown> | null;
}

// 一行取回或 MCP 调用的全部文字。其余动作不用这一份（步骤时间线沿用 actionCells 的列）
export interface ActionRowView {
  kind: ActionKind;
  typeName: string;
  target: string;
  statusName: string;
  durationText: string;
  summaryText: string;
  external: ExternalSourceRefView | null;
  returnedText: string;
}

// 一行动作的文字：种类名、目标、状态、耗时、结果摘要与外部来源引用。
// extras.output 是这个动作的结果工件（event.detail 的 artifacts.output），取回与 MCP 的回执字段在它里面；
// extras.returned 是 run.recovery 里这个动作交还给模型的内容
export function actionRow(action: ActionView, extras: ActionRowExtras = {}): ActionRowView {
  const kind = actionKind(action);
  const receipt = action.receipt;
  const output = extras.output ?? null;
  const statusName = label(ACTION_STATUS, action.status);
  const external = externalSourceRefOf(action, kind, output);
  return {
    kind,
    typeName: kind === "other" ? "" : ACTION_TYPE_NAMES[kind],
    target: targetOf(action, kind, output),
    statusName,
    durationText: durationOf(receipt, output),
    summaryText: summaryOf(action, kind, output),
    external,
    returnedText: returnedText(extras.returned),
  };
}

// 目标：取回写地址；MCP 写服务器与工具名（工具结果工件里的原名），取不到时留空
function targetOf(action: ActionView, kind: ActionKind, output: Record<string, unknown> | null): string {
  if (kind === "fetch") {
    const url = action.receipt?.args?.["url"];
    if (typeof url === "string" && url !== "") {
      return url;
    }
    const finalUrl = action.receipt?.fetch?.final_url;
    return typeof finalUrl === "string" ? finalUrl : "";
  }
  if (kind === "mcp") {
    const server = textOf(output?.["server"]);
    const tool = textOf(output?.["tool"]);
    if (server !== "" && tool !== "") {
      return `${server} · ${tool}`;
    }
    if (server !== "") {
      return server;
    }
    return "名称未上报";
  }
  return "";
}

// 耗时：取回的回执里带着耗时；MCP 的耗时在结果工件里。没有上报时照实写
function durationOf(receipt: ActionReceipt | null, output: Record<string, unknown> | null): string {
  const milliseconds = receipt?.fetch?.duration_ms ?? numberOf(output?.["duration_ms"]);
  return milliseconds === null ? "未上报" : formatMilliseconds(milliseconds);
}

// 结果摘要：取回写 HTTP 状态码与字节数；MCP 写成功、失败原因或拒绝原因
function summaryOf(action: ActionView, kind: ActionKind, output: Record<string, unknown> | null): string {
  const receipt = action.receipt;
  if (receipt === null) {
    return "没有回执";
  }
  if (receipt.refused) {
    return receipt.refused_reason || receipt.error || "被拒绝";
  }
  if (kind === "fetch") {
    const fetch = receipt.fetch;
    if (fetch !== null && fetch !== undefined) {
      const truncated = fetch.download_truncated ? " · 已截断" : "";
      return `HTTP ${fetch.status_code} · ${fetch.bytes.toLocaleString("zh-CN")} 字节${truncated}`;
    }
    return receipt.ok ? "成功" : (receipt.error || "失败");
  }
  if (kind === "mcp") {
    if (output?.["is_error"] === true) {
      return receipt.error || "工具报告失败";
    }
    return receipt.ok ? "成功" : (receipt.error || "失败");
  }
  return receipt.ok ? "成功" : (receipt.error || "失败");
}

// 外部来源工件的引用：取回的回执带 ref；MCP 的结果工件带 ref。不是外部来源工件时不给链接
function externalSourceRefOf(action: ActionView, kind: ActionKind, output: Record<string, unknown> | null): ExternalSourceRefView | null {
  const receipt = action.receipt;
  if (receipt === null) {
    return null;
  }
  const fetch: FetchReceipt | null | undefined = receipt.fetch;
  const ref = kind === "fetch" ? fetch?.ref : kind === "mcp" ? output?.["ref"] : null;
  return externalSourceRef(ref, receipt.event_id);
}

// 交还给模型的内容：核实记录里写的是工具结果的原文。它是 JSON 时取出其中的原因或输出，
// 页面上写读得懂的那一句；解析不出 JSON 时原样显示
export function returnedText(value: string | null | undefined): string {
  const raw = (value ?? "").trim();
  if (raw === "") {
    return "";
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return raw;
  }
  if (!isRecord(parsed)) {
    return raw;
  }
  for (const key of ["error", "output", "text"]) {
    const text = textOf(parsed[key]).trim();
    if (text !== "") {
      return text;
    }
  }
  return "这次交还的结果里没有文字";
}

// 一份工件引用看着是外部来源时转成界面要的四项；所属事件为空或字段不全时不给
export function externalSourceRef(value: unknown, eventId: string): ExternalSourceRefView | null {
  if (eventId === "" || !isRecord(value)) {
    return null;
  }
  const kind = value["kind"];
  const contentHash = value["content_hash"];
  const path = value["path"];
  const mediaType = value["media_type"];
  if (kind !== "external_source" || typeof contentHash !== "string" || !/^sha256:[0-9a-f]{64}$/.test(contentHash)) {
    return null;
  }
  if (typeof path !== "string" || path === "") {
    return null;
  }
  return {
    eventId,
    kind,
    contentHash,
    path,
    mediaType: typeof mediaType === "string" ? mediaType : null,
  };
}

// 工具结果工件里的结果对象（event.detail 的 artifacts.output）；取不出来时为空
export function toolOutput(artifacts: unknown): Record<string, unknown> | null {
  if (!isRecord(artifacts)) {
    return null;
  }
  const output = artifacts["output"];
  return isRecord(output) ? output : null;
}

// 毫秒写成中文：不足一秒写毫秒，一分钟以内写一位小数的秒，再长写分钟
export function formatMilliseconds(value: number): string {
  if (!Number.isFinite(value) || value < 0) {
    return "未上报";
  }
  if (value < 1000) {
    return `${Math.round(value)} 毫秒`;
  }
  if (value < 60_000) {
    return `${(value / 1000).toFixed(1)} 秒`;
  }
  return `${Math.round(value / 60_000)} 分`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function textOf(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberOf(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
