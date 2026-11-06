// 「MCP 服务器」一节的纯计算（工单 #237，网络与 MCP docs/design/network-and-mcp.md「服务器设置」、「读取工具清单（探测）」、「项目设置的「MCP 服务器」一节」）。
// 这里只做取值、组装与判断，不触碰网络与界面：保存参数的组装、表单的必填与格式、
// 工具清单快照的保留、列表里的说法都由这里给出，页面组件只按它们渲染，单元测试直接核对。
//
// 保存参数按后端 `mcp_servers.save` 与 `tool_server.probe` 接受的形状组装：
// 一台服务器是 name、transport、departments、时限与输出上限，stdio 另有 command、args、env，
// HTTP 另有 url、headers；变量与请求头的值是「固定文本」或「凭据名称」（只写名称，不写值）。

import type {
  McpCredentialStatusView,
  McpProbeResultView,
  McpServerSettingView,
} from "../../api/generated/types.gen";
import { type CommandProblem, commandProblemText } from "../../contract/command-problem.ts";
import { intFromInput } from "../models/model-logic.ts";
import { departmentName } from "./labels.ts";

// 传输：本机进程（stdio）与 streamable HTTP。docs/design/network-and-mcp.md「服务器设置」明确不支持 SSE
export const MCP_TRANSPORTS = ["stdio", "http"] as const;
export type McpTransport = (typeof MCP_TRANSPORTS)[number];

// 默认的三个部门（docs/design/project-organization.md「项目上配的三层」「可以使用的部门」）不在这里写：可以使用的部门取自项目现在的组织
// （工单 #1457），组织还没有数据时由调用处按设置里已有的部门兜底

// 默认的时限与输出上限（后端 MCP_OUTPUT_LIMIT_DEFAULTS 是同一组值）：
// 表单留空时按这组默认，不把默认值写死在客户端提交的内容里
export const MCP_DEFAULTS = { startup_timeout_sec: 60, call_timeout_sec: 120, output_limit: 20000 } as const;

export function isTransport(value: string): value is McpTransport {
  return (MCP_TRANSPORTS as readonly string[]).includes(value);
}

// 传输在页面上的说法：不写内部取值，写明是本机进程还是 HTTP 服务
export function transportLabel(transport: string): string {
  switch (transport) {
    case "stdio":
      return "本机进程（stdio）";
    case "http":
      return "HTTP 服务（streamable HTTP）";
    default:
      return transport;
  }
}

// ---------------------------------------------------------------------------
// 表单草稿与保存参数
// ---------------------------------------------------------------------------

// 一个环境变量或请求头：名字、取值方式与值（凭据只写名称）
export type McpVariableDraft = {
  key: string;
  kind: "text" | "credential";
  value: string;
  credential_ref: string;
};

export type McpServerDraft = {
  name: string;
  transport: McpTransport;
  command: string;
  // 参数一行一个
  args: string;
  env: McpVariableDraft[];
  url: string;
  headers: McpVariableDraft[];
  departments: string[];
  startup_timeout_sec: string;
  call_timeout_sec: string;
  output_limit: string;
};

export function emptyDraft(departments: string[] = []): McpServerDraft {
  return {
    name: "",
    transport: "stdio",
    command: "",
    args: "",
    env: [],
    url: "",
    headers: [],
    departments: [...departments],
    startup_timeout_sec: "",
    call_timeout_sec: "",
    output_limit: "",
  };
}

// 已保存的一台服务器 → 表单草稿：改一项、其余照原样保存回去
export function draftOfServer(server: McpServerSettingView): McpServerDraft {
  const transport = isTransport(server.transport) ? server.transport : "stdio";
  return {
    name: server.name,
    transport,
    command: server.command ?? "",
    args: (server.args ?? []).join("\n"),
    env: variableDrafts(server.env),
    url: server.url ?? "",
    headers: variableDrafts(server.headers),
    departments: [...(server.departments ?? [])],
    startup_timeout_sec: numberText(server.startup_timeout_sec, MCP_DEFAULTS.startup_timeout_sec),
    call_timeout_sec: numberText(server.call_timeout_sec, MCP_DEFAULTS.call_timeout_sec),
    output_limit: numberText(server.output_limit, MCP_DEFAULTS.output_limit),
  };
}

// 设置里的默认值是同一组默认时不填出来：留空表示用默认，表单里不重复写一遍
function numberText(value: number | undefined, fallback: number): string {
  return value === undefined || value === fallback ? "" : String(value);
}

// 已保存的变量与请求头 → 表单的几行
export function variableDrafts(entries: Record<string, unknown> | undefined): McpVariableDraft[] {
  return Object.entries(entries ?? {}).map(([key, entry]) => {
    const value = (entry ?? {}) as Record<string, unknown>;
    const kind = value.kind === "credential" ? "credential" : "text";
    return {
      key,
      kind,
      value: kind === "text" ? String(value.value ?? "") : "",
      credential_ref: kind === "credential" ? String(value.credential_ref ?? "") : "",
    };
  });
}

// 参数文本：一行一个，去掉空行与两端的空白
export function splitLines(text: string): string[] {
  return text.split(/\r?\n/).map((line) => line.trim()).filter((line) => line !== "");
}

// 一行变量或请求头 → 保存时的取值：固定文本写值，凭据只写名称
export function variableEntry(draft: McpVariableDraft): Record<string, unknown> {
  if (draft.kind === "credential") {
    return { kind: "credential", credential_ref: draft.credential_ref.trim() };
  }
  return { kind: "text", value: draft.value };
}

// 几行变量或请求头 → 保存时的对象：没有名字的行不提交（表单里刚加的一行可能是空的）
export function variablesPayload(drafts: McpVariableDraft[]): Record<string, unknown> {
  const entries: Record<string, unknown> = {};
  for (const draft of drafts) {
    const key = draft.key.trim();
    if (key === "") {
      continue;
    }
    entries[key] = variableEntry(draft);
  }
  return entries;
}

// 一台服务器的保存参数：两种传输各自的字段，时限与输出上限留空时不提交（后端按默认值保存）
export function mcpServerPayload(draft: McpServerDraft): Record<string, unknown> {
  const server: Record<string, unknown> = {
    name: draft.name.trim(),
    transport: draft.transport,
    departments: [...draft.departments],
  };
  const numbers: [string, string][] = [
    ["startup_timeout_sec", draft.startup_timeout_sec],
    ["call_timeout_sec", draft.call_timeout_sec],
    ["output_limit", draft.output_limit],
  ];
  for (const [field, text] of numbers) {
    const value = intFromInput(text);
    if (value !== null) {
      server[field] = value;
    }
  }
  if (draft.transport === "stdio") {
    server.command = draft.command.trim();
    server.args = splitLines(draft.args);
    server.env = variablesPayload(draft.env);
  } else {
    server.url = draft.url.trim();
    server.headers = variablesPayload(draft.headers);
  }
  return server;
}

// 表单当时说的第一件要改的事：没有要改的就是空串，按钮据此可用。
// 说法是中文，不写字段名：页面不出现英文内部标识与开发者措辞（验收第 2 条）
export function draftIssue(draft: McpServerDraft): string {
  const name = draft.name.trim();
  if (name === "") {
    return "填写名称";
  }
  if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) {
    return "名称只能用小写字母、数字与连字符，并以字母或数字开头";
  }
  if (!isTransport(draft.transport)) {
    return "选择传输";
  }
  if (draft.transport === "stdio" && draft.command.trim() === "") {
    return "填写命令";
  }
  if (draft.transport === "http") {
    const url = draft.url.trim();
    if (url === "") {
      return "填写地址";
    }
    if (!url.startsWith("http://") && !url.startsWith("https://")) {
      return "地址要以 http:// 或 https:// 开头";
    }
  }
  if (draft.departments.length === 0) {
    return "选一个可以使用的部门";
  }
  const numbers: [string, string][] = [
    ["启动时限", draft.startup_timeout_sec],
    ["调用时限", draft.call_timeout_sec],
    ["输出上限", draft.output_limit],
  ];
  for (const [label, text] of numbers) {
    if (text.trim() === "") {
      continue;
    }
    const value = intFromInput(text);
    if (value === null || value < 1) {
      return `${label}要填不小于 1 的整数`;
    }
  }
  const variables = draft.transport === "stdio" ? draft.env : draft.headers;
  const where = draft.transport === "stdio" ? "环境变量" : "请求头";
  for (const entry of variables) {
    const key = entry.key.trim();
    if (key === "") {
      continue;
    }
    if (entry.kind === "credential") {
      const ref = entry.credential_ref.trim();
      if (ref === "") {
        return `填写${where}「${key}」的凭据名称`;
      }
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(ref)) {
        return `凭据「${ref}」只能用字母、数字与下划线，不能以数字开头`;
      }
      continue;
    }
    if (entry.value === "") {
      return `填写${where}「${key}」的值`;
    }
  }
  return "";
}

// ---------------------------------------------------------------------------
// 整份文档：保存与删除都按整份提交（mcp_servers.save 的既定形状）
// ---------------------------------------------------------------------------

// 一台设置的比较依据：默认值补齐以后，两种传输各自的字段都在，按名称顺序拼接。
// 配置没有改动时保留原来的工具清单快照；配置改过以后旧快照带的摘要对不上，不能继续用
// （docs/design/network-and-mcp.md「读取工具清单（探测）」：配置改变后旧快照失效）
export function configurationSignature(server: Record<string, unknown> | McpServerSettingView): string {
  const input = server as Record<string, unknown>;
  const defaults = MCP_DEFAULTS;
  const number = (field: keyof typeof defaults) => {
    const value = input[field];
    return typeof value === "number" ? value : (value === undefined || value === null ? defaults[field] : String(value));
  };
  const transport = String(input.transport ?? "stdio");
  const departments = [...((input.departments ?? []) as string[])].sort();
  const variables = (value: unknown): [string, string][] => Object.entries((value ?? {}) as Record<string, unknown>)
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([key, entry]) => {
      const item = (entry ?? {}) as Record<string, unknown>;
      return item.kind === "credential"
        ? [key, `credential:${String(item.credential_ref ?? "")}`]
        : [key, `text:${String(item.value ?? "")}`];
    });
  const parts: Record<string, unknown> = {
    name: String(input.name ?? ""),
    transport,
    departments,
    startup_timeout_sec: number("startup_timeout_sec"),
    call_timeout_sec: number("call_timeout_sec"),
    output_limit: number("output_limit"),
  };
  if (transport === "http") {
    parts.url = String(input.url ?? "");
    parts.headers = variables(input.headers);
  } else {
    parts.command = String(input.command ?? "");
    parts.args = ((input.args ?? []) as string[]).map((item) => String(item));
    parts.env = variables(input.env);
  }
  return JSON.stringify(parts);
}

export function draftChangesConfiguration(server: McpServerSettingView, draft: McpServerDraft): boolean {
  return configurationSignature(server) !== configurationSignature(mcpServerPayload(draft));
}

// 一台服务器在整份文档里的样子：配置没改时带上原来的工具清单快照
export function serverDocument(server: McpServerSettingView | null, draft: McpServerDraft): Record<string, unknown> {
  const payload = mcpServerPayload(draft);
  const snapshot = server !== null && !draftChangesConfiguration(server, draft) ? server.tool_snapshot : null;
  if (snapshot) {
    payload.tool_snapshot = snapshot;
  }
  return payload;
}

// 一份服务器文档：其余服务器照原样带回去，改动的这一台按草稿换掉（改名时去掉原来那个名称），
// previous_name 为 null 表示新增。删掉一台时 draft 传 null（整份设置一个版本）
export function mcpDocumentPayload(
  servers: Record<string, McpServerSettingView> | undefined,
  draft: McpServerDraft | null,
  options: { previous_name?: string | null } = {},
): Record<string, unknown> {
  const document: Record<string, unknown> = {};
  for (const [name, server] of Object.entries(servers ?? {})) {
    document[name] = { ...server };
  }
  const previous = options.previous_name ?? null;
  if (previous !== null) {
    delete document[previous];
  }
  if (draft === null) {
    return { servers: document };
  }
  const existing = previous !== null ? servers?.[previous] ?? null : null;
  const name = draft.name.trim();
  document[name] = serverDocument(existing, draft);
  return { servers: document };
}

// ---------------------------------------------------------------------------
// 凭据名称与它们的状态（后端 project.settings 给出的判断）
// ---------------------------------------------------------------------------

// 一份草稿里出现的凭据名称，按出现的先后各记一次
export function credentialNames(draft: McpServerDraft): string[] {
  const variables = draft.transport === "stdio" ? draft.env : draft.headers;
  const names: string[] = [];
  for (const entry of variables) {
    const ref = entry.credential_ref.trim();
    if (entry.kind === "credential" && ref !== "" && !names.includes(ref)) {
      names.push(ref);
    }
  }
  return names;
}

// 设置里出现过的全部凭据名称：已保存的设置与这一份草稿各出现一次都算
export function credentialNamesOfSettings(
  servers: Record<string, McpServerSettingView> | undefined,
  draft: McpServerDraft | null,
): string[] {
  const names: string[] = [];
  for (const server of Object.values(servers ?? {})) {
    for (const name of credentialNames(draftOfServer(server))) {
      if (!names.includes(name)) {
        names.push(name);
      }
    }
  }
  if (draft !== null) {
    for (const name of credentialNames(draft)) {
      if (!names.includes(name)) {
        names.push(name);
      }
    }
  }
  return names;
}

// 一个凭据名称此刻的状态：后端没有给出这一项时为空（页面写「还没有读到状态」，不自己猜）
export function credentialState(
  statuses: Record<string, McpCredentialStatusView> | undefined,
  ref: string,
): { configured: boolean; source: string } | null {
  const status = (statuses ?? {})[ref];
  return status === undefined ? null : { configured: status.configured, source: status.source };
}

// credential.set 的基准版本：后端没有给出这一项时为 0（第一次写入）
export function credentialVersion(statuses: Record<string, McpCredentialStatusView> | undefined, ref: string): number {
  return (statuses ?? {})[ref]?.version ?? 0;
}

// ---------------------------------------------------------------------------
// 工具清单（探测结果与保存的快照）
// ---------------------------------------------------------------------------

export type McpToolRow = { name: string; description: string; hints: string };

const HINT_LABELS: [string, string][] = [
  ["read_only_hint", "只读"],
  ["destructive_hint", "有破坏性"],
  ["idempotent_hint", "幂等"],
  ["open_world_hint", "访问外部"],
];

// 服务器自己标注的提示：只供参考，不参与判断（docs/design/network-and-mcp.md「服务器设置」「工具清单」）
export function hintText(hints: unknown): string {
  if (hints === null || typeof hints !== "object") {
    return "";
  }
  const item = hints as Record<string, unknown>;
  const parts = HINT_LABELS.filter(([field]) => item[field] === true).map(([, label]) => label);
  return parts.join("、");
}

// 工具清单快照（或探测结果）里的工具 → 表格的几行
export function toolRows(tools: unknown): McpToolRow[] {
  const rows: McpToolRow[] = [];
  for (const tool of Array.isArray(tools) ? tools : []) {
    const item = (tool ?? {}) as Record<string, unknown>;
    const name = String(item.name ?? "");
    if (name === "") {
      continue;
    }
    rows.push({ name, description: String(item.description ?? ""), hints: hintText(item.hints) });
  }
  return rows;
}

// 已保存设置的快照里的工具（这台服务器已经有可用的工具清单时）
export function snapshotTools(server: McpServerSettingView | null): McpToolRow[] {
  return server === null ? [] : toolRows((server.tool_snapshot ?? {}).tools);
}

// 一次探测结果的工具
export function probeTools(result: McpProbeResultView | null): McpToolRow[] {
  return result === null ? [] : toolRows(result.tools);
}

export function toolCountText(server: McpServerSettingView): string {
  const count = snapshotTools(server).length;
  return count === 0 ? "还没有读取工具清单" : `${count} 个工具`;
}

// 最近一次探测的结果从哪里来：这一次页面里收到的探测事件优先，其次是设置里带的那一次
export function probeOf(
  serverName: string,
  lastProbe: McpProbeResultView | null | undefined,
  localProbes: Record<string, McpProbeResultView>,
): McpProbeResultView | null {
  return localProbes[serverName] ?? (lastProbe && lastProbe.server_name === serverName ? lastProbe : null);
}

// 一台服务器最近一次连接结果的说法（没有探测过时如实写没有）
export function probeStateLabel(probe: McpProbeResultView | null): string {
  if (probe === null) {
    return "还没有探测过";
  }
  if (probe.status === "ok") {
    const count = probeTools(probe).length;
    return `成功 · ${count} 个工具`;
  }
  return "失败";
}

// 探测失败的说明：原因写在结果旁边（标准错误输出的末尾由后端附在原因里，凭据值已替换为星号）
export function probeFailureText(probe: McpProbeResultView | null): string {
  if (probe === null || probe.status === "ok") {
    return "";
  }
  return probe.error === undefined || probe.error === "" ? "这次探测没有成功，原因没有写明。" : probe.error;
}

// 探测成功时的服务器信息：名称、版本与协议版本（都是服务器自己报的）
export function serverInfoText(probe: McpProbeResultView | null): string {
  if (probe === null || probe.server_info === null || probe.server_info === undefined) {
    return "";
  }
  const info = probe.server_info as Record<string, unknown>;
  const parts: string[] = [];
  const name = String(info.name ?? "");
  const version = String(info.version ?? "");
  const protocol = String(info.protocol_version ?? "");
  if (name !== "") {
    parts.push(name + (version === "" ? "" : ` ${version}`));
  }
  if (protocol !== "") {
    parts.push(`协议 ${protocol}`);
  }
  return parts.join(" · ");
}

// 探测结果与当前配置是否还对得上：配置改过以后旧结果保留供查看，但不能再当可用快照
//。两个摘要都由后端给出，页面只比较，不自己算、也不显示摘要本身
export function probeIsStale(probe: McpProbeResultView | null, server: McpServerSettingView | null): boolean {
  if (probe === null || server === null || probe.status !== "ok") {
    return false;
  }
  const probed = String(probe.config_digest ?? "");
  const current = String(server.config_digest ?? "");
  return probed !== "" && current !== "" && probed !== current;
}

// ---------------------------------------------------------------------------
// 保存与删除以后的说法
// ---------------------------------------------------------------------------

// 保存被拒绝时页面上写的话：基准版本过期时明说重新读取（验收第 1 条），其余按服务端给的说明
export function saveNotice(problem: CommandProblem): string {
  if (problem.kind === "rejected" && problem.rejection.reason === "stale_base") {
    const version = problem.rejection.current_version ?? 0;
    return `MCP 服务器设置已经被修改，请重新读取以后再保存（服务端当前版本 ${version}）。`;
  }
  return commandProblemText(problem);
}

// 列表里那一节的说明：几台服务器、几台有可用的工具清单
export function sectionNote(servers: Record<string, McpServerSettingView> | undefined): string {
  const items = Object.values(servers ?? {});
  if (items.length === 0) {
    return "项目设置里写明的 MCP 服务器：部门经它们调用工具，工具在事项创建时固定";
  }
  const withTools = items.filter((item) => snapshotTools(item).length > 0).length;
  return `${items.length} 台服务器，其中 ${withTools} 台已经读到工具清单`;
}

// 可以使用的部门一列：部门的显示名，逗号分开。显示名取项目现在组织里的部门（工单 #1457），
// 组织里没有的旧部门才用页面上原来的写法
export function departmentsText(departments: string[] | undefined,
                                labels: Record<string, string> = {}): string {
  const names = (departments ?? []).map((item) => labels[item] ?? (departmentName(item) || item));
  return names.length === 0 ? "没有选部门" : names.join("、");
}
