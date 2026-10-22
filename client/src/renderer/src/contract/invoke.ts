// 查询与命令的名称到生成的调用函数的映射（应用层与接口层设计说明第 7.1 节：客户端用的路径是
// /api/queries/{名称} 与 /api/commands/{名称}，名称就是注册表里的名称）。
// 查询与命令函数由 @hey-api/openapi-ts 生成；这里按名称查找它们，避免为每个页面各写一遍调用。
// 生成函数的返回类型由合同给出，因此这里的返回保留原始类型；只有按名称查找这一步是运行时的。

import type { Client } from "../api/generated/client";
import * as sdk from "../api/generated/sdk.gen";
import { classifyCommandFailure, type CommandProblem } from "./command-problem.ts";
import { queryFailureText } from "./read-failure";

type QueryFunction = (options: { client: Client; query?: Record<string, unknown> }) => Promise<{ data: unknown; error?: unknown }>;
type CommandFunction = (options: { client: Client; body: unknown }) => Promise<{ data: unknown; error?: unknown; response?: Response }>;

// 一条命令的结果：接受返回应用层的受理回执（command_id、position、refs），
// 没有成功时给出失败的三种形状（contract/command-problem.ts）
export type CommandOutcome =
  | { ok: true; accepted: Record<string, unknown> }
  | { ok: false; problem: CommandProblem };

// 生成的函数名：querySystemStatus、commandProjectCreate、queryWorkItemMaterials 等。
// 名称里的点与下划线都是分词：每一段的首字母大写以后直接拼起来（work_item.materials -> WorkItemMaterials）
function functionName(prefix: "query" | "command", name: string): string {
  const pascal = name
    .split(".")
    .flatMap((part) => part.split("_"))
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join("");
  return prefix + pascal;
}

const functions = sdk as unknown as Record<string, QueryFunction | CommandFunction>;

// 调用一个查询：返回应用层给出的快照。生成函数的返回类型由合同保证，这里的 unknown 只是按名称查找的边界
export async function callQuery<T>(
  client: Client,
  name: string,
  params: Record<string, unknown> | undefined,
): Promise<{ position: number; data: T }> {
  const fn = functions[functionName("query", name)];
  if (typeof fn !== "function") {
    throw new Error(`能力清单中的查询 ${name} 没有生成的调用函数`);
  }
  const response = await (fn as QueryFunction)({ client, query: params });
  if (response.data === undefined) {
    // 服务不可达或查询失败时生成客户端返回空 data：直接抛出，不把 undefined 当快照用。
    // 服务端给的说明带在错误里（工单 #728）：界面要能把它与「本来就没有内容」分开。
    throw new Error(queryFailureText(name, response.error));
  }
  return response.data as { position: number; data: T };
}

// 提交一条命令：200 返回受理回执；409 的响应体是 Rejected，生成的客户端把它放在 error 字段。
// 失败按响应体的形状与状态码分三种（contract/command-problem.ts）：应用层拒绝、接口层校验错误、其余。
// 网络错误与其他非预期状态码不再直接抛出，由这里给出一句能显示的话（工单 #740）
export async function callCommand(
  client: Client,
  name: string,
  body: Record<string, unknown>,
): Promise<CommandOutcome> {
  const fn = functions[functionName("command", name)];
  if (typeof fn !== "function") {
    throw new Error(`能力清单中的命令 ${name} 没有生成的调用函数`);
  }
  const response = await (fn as CommandFunction)({ client, body });
  if (response.error !== undefined && response.error !== null) {
    return { ok: false, problem: classifyCommandFailure(response.error, response.response?.status ?? 0) };
  }
  return { ok: true, accepted: (response.data ?? {}) as Record<string, unknown> };
}
