// 查询与命令的名称到生成的调用函数的映射（应用层与接口层设计说明第 7.1 节：客户端用的路径是
// /api/queries/{名称} 与 /api/commands/{名称}，名称就是注册表里的名称）。
// 查询与命令函数由 @hey-api/openapi-ts 生成；这里按名称查找它们，避免为每个页面各写一遍调用。
// 生成函数的返回类型由合同给出，因此这里的返回保留原始类型；只有按名称查找这一步是运行时的。

import type { Client } from "../api/generated/client";
import * as sdk from "../api/generated/sdk.gen";

type QueryFunction = (options: { client: Client; query?: Record<string, unknown> }) => Promise<{ data: unknown }>;
type CommandFunction = (options: { client: Client; body: unknown }) => Promise<{ data: unknown; error: unknown }>;

// 生成的函数名：querySystemStatus、commandProjectCreate 等；名称中的点与下划线都是分隔符，
// 每段首字母大写后拼接（例如 work_item.inputs 对应 queryWorkItemInputs，catalog.department_defaults.save
// 对应 commandCatalogDepartmentDefaultsSave）
function functionName(prefix: "query" | "command", name: string): string {
  return prefix + name.split(/[._]/).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join("");
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
  return response.data as { position: number; data: T };
}

// 命令的结果：200 是 Accepted（放在 data），409 是 Rejected（reason 与 message，放在 error）。
// 界面按这两种情况分别显示接受后的位置与拒绝原因，所以两种都交回。
export type CommandOutcome = { data?: unknown; error?: unknown };

export async function callCommand(client: Client, name: string, body: unknown): Promise<CommandOutcome> {
  const fn = functions[functionName("command", name)];
  if (typeof fn !== "function") {
    throw new Error(`能力清单中的命令 ${name} 没有生成的调用函数`);
  }
  const result = await (fn as CommandFunction)({ client, body });
  return { data: result.data, error: result.error };
}
