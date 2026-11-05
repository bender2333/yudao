// 工具与扩展页的纯计算（工单 #239，网络与 MCP 设计说明「系统「工具与扩展」页」）。
//
// 这一页是只读汇总：网络取回列各项目最近的取回记录，MCP 工具列各项目的服务器、最近一次状态与工具。
// 这里只把 tools.registry 的结果变成页面上要写的字与要显示的行，不触碰网络与界面；
// 页面组件按返回值渲染，单元测试直接核对。
//
// 页面上不写查询名、字段名与工作包编号：内部标识只出现在这个文件里，其余三块所属的阶段写成
// 用户看得懂的「阶段三」「阶段四」。

import type {
  ToolsRegistryFetchRecord,
  ToolsRegistryResult,
  ToolsRegistryServerView,
} from "../../api/generated/types.gen";
import { departmentName, formatTime } from "../project/labels.ts";
import { snapshotTools } from "../project/mcp-servers-logic.ts";

// 这一页的数据来源（能力清单里这一条查询的名字）；页面上不写出它
export const TOOLS_QUERY = "tools.registry";

// 页面上写出的固定说法。测试逐条核对它们不出现内部标识与开发者措辞
export const TOOLS_WORDING = {
  // 能力清单里没有这条查询时写在页首的那一句
  unavailable: "控制主机的能力清单中没有工具登记这一条查询，各部分的明细暂时不能列出。",
  // 查询失败时写在页首的那一句（前面接查询给出的原因）
  unreadable: "工具登记读不出来",
  // 网络取回：没有记录时的空态
  noFetchRecords: "还没有取回记录",
  // 一条取回记录的结果
  fetchSucceeded: "成功",
  fetchFailed: "失败",
  fetchUnknown: "结果未知",
  // MCP：没有项目写服务器时的空态；一台服务器还没有读取过工具清单时的说法
  noMcpServers: "还没有项目接入 MCP 服务器",
  toolsNotRead: "还没有读取工具清单",
  // 一台服务器最近一次状态：没有探测过、探测失败、探测成功（后面接工具数）
  neverProbed: "还没有探测过",
  probeFailed: "失败",
  probeSucceeded: "成功",
  // 探测以后设置又改过：那一次结果保留供查看，但已经不是这一份设置的可用清单
  probeStale: "服务器设置改过，这一次结果已过期",
  // 修改入口：跳到项目设置页
  settingsLink: "在项目设置中修改",
} as const;

export type FetchRow = {
  // 取回动作的时间（原样）与页面上的写法
  at: string;
  time: string;
  url: string;
  project: string;
  result: string;
};

// 一条取回记录的结果：成功、失败；查询没有给出结果时如实写结果未知，不猜成功
export function fetchResultText(record: ToolsRegistryFetchRecord): string {
  if (record.ok === true) {
    return TOOLS_WORDING.fetchSucceeded;
  }
  if (record.ok === false) {
    return TOOLS_WORDING.fetchFailed;
  }
  return TOOLS_WORDING.fetchUnknown;
}

// 各项目最近的取回记录合成一张表，最近的在前：每个项目各自最近的那些（由查询给出），
// 同一个项目里顺序保持查询给的样子；时间相同的按项目顺序，不重新打乱
export function fetchRows(result: ToolsRegistryResult | null): FetchRow[] {
  if (result === null) {
    return [];
  }
  const entries = result.projects.flatMap((project) =>
    (project.fetch_records ?? []).map((record) => ({ project: project.name, record })));
  const ordered = entries.map((entry, index) => ({ entry, index }));
  ordered.sort((left, right) => {
    const difference = timeValue(right.entry.record.at) - timeValue(left.entry.record.at);
    return difference === 0 ? left.index - right.index : difference;
  });
  return ordered.map(({ entry }) => ({
    at: entry.record.at ?? "",
    time: formatTime(entry.record.at),
    url: entry.record.url ?? "",
    project: entry.project,
    result: fetchResultText(entry.record),
  }));
}

function timeValue(at: string | undefined): number {
  const parsed = Date.parse(at ?? "");
  return Number.isNaN(parsed) ? 0 : parsed;
}

// 一台 MCP 服务器在页面上的一节
export type McpToolView = { name: string; description: string };

export type McpServerView = {
  name: string;
  // 可以使用的部门（部门的显示名，用顿号连起来）
  departments: string;
  // 最近一次状态的说法、那一次的时间与过期提示
  status: string;
  statusAt: string;
  staleNote: string;
  tools: McpToolView[];
  // 没有可用的工具清单时写在工具表位置的那一句
  toolsNote: string;
};

export type McpProjectView = {
  projectId: string;
  name: string;
  servers: McpServerView[];
  // 这一项目的「修改」入口：项目设置页（MCP 服务器那一节在设置页里）
  settingsHash: string;
};

// 各项目在设置里写明的 MCP 服务器，只列有服务器的项目：没有服务器的项目在这一块不出现
export function mcpProjects(result: ToolsRegistryResult | null): McpProjectView[] {
  if (result === null) {
    return [];
  }
  return result.projects
    .filter((project) => Object.keys(project.mcp_servers ?? {}).length > 0)
    .map((project) => ({
      projectId: project.project_id,
      name: project.name,
      servers: Object.entries(project.mcp_servers ?? {}).map(([name, server]) => serverView(name, server)),
      settingsHash: projectSettingsHash(project.project_id),
    }));
}

function serverView(name: string, server: ToolsRegistryServerView): McpServerView {
  const probe = server.probe ?? null;
  const tools = snapshotTools(server).map((tool) => ({ name: tool.name, description: tool.description }));
  return {
    name: server.name === "" ? name : server.name,
    departments: (server.departments ?? []).map((department) => departmentName(department)).filter((text) => text !== "").join("、"),
    status: probeStatusText(server),
    statusAt: probe === null || !probe.finished_at ? "" : formatTime(probe.finished_at),
    staleNote: probeStaleNote(server),
    tools,
    toolsNote: tools.length === 0 ? TOOLS_WORDING.toolsNotRead : "",
  };
}

// 一台服务器最近一次状态：还没有探测过、失败，或者成功（带这一次读到的工具数）
export function probeStatusText(server: ToolsRegistryServerView): string {
  const probe = server.probe ?? null;
  if (probe === null || !probe.finished_at) {
    return TOOLS_WORDING.neverProbed;
  }
  if (probe.ok !== true) {
    return TOOLS_WORDING.probeFailed;
  }
  return `${TOOLS_WORDING.probeSucceeded} · ${snapshotTools(server).length} 个工具`;
}

// 探测以后设置又改过：两个摘要都由后端给出，页面只比较，不显示摘要本身。
// 失败的结果不复用，没有摘要的也不说它过期，免得在没有依据时给一句提示
export function probeStaleNote(server: ToolsRegistryServerView): string {
  const probe = server.probe ?? null;
  if (probe === null || probe.ok !== true) {
    return "";
  }
  const probed = (probe.config_digest ?? "").trim();
  const current = (server.config_digest ?? "").trim();
  if (probed === "" || current === "" || probed === current) {
    return "";
  }
  return TOOLS_WORDING.probeStale;
}

// 一个项目的「修改」入口指向的地址：项目设置页
export function projectSettingsHash(projectId: string): string {
  return `#/p/${projectId}/settings`;
}

// 其余三块：还没有接入的内容，各自标出所属阶段（浏览器工具随这一阶段的界面工作接入，
// computer use 与只读观察者在阶段四）。id 只是页面上的锚点与测试用的标识，页面上不写出来
export type PendingSection = { id: string; title: string; subtitle: string; stage: string; note: string };

export const PENDING_SECTIONS: readonly PendingSection[] = [
  {
    id: "browser",
    title: "浏览器工具",
    // 浏览器工具的动作在浏览器里做（浏览器与 computer use 设计说明「概念与分层」）
    subtitle: "浏览器里的页面操作与截图",
    stage: "阶段三",
    note: "这一阶段随后接入；在那以前这一页不列浏览器工具。",
  },
  {
    id: "computer-use",
    title: "computer use",
    // 桌面操作在控制主机的桌面上进行（浏览器与 computer use 设计说明「computer use」）
    subtitle: "在控制主机的桌面上截图、点击与输入文字",
    stage: "阶段四",
    note: "桌面操作进入阶段四以后接入。",
  },
  {
    id: "observers",
    title: "只读观察者",
    subtitle: "已登记的观察者与各自的读取范围",
    stage: "阶段四",
    note: "观察者的只读订阅进入阶段四以后接入。",
  },
] as const;

// 一块的「所属阶段」那一行
export function stageText(section: PendingSection): string {
  return `所属阶段：${section.stage}`;
}

// 这一页会写出的全部固定说法与其余三块的说法（单元测试逐条核对这些字里没有内部标识与开发者措辞）
export function pageWording(): string[] {
  const texts: string[] = Object.values(TOOLS_WORDING);
  for (const section of PENDING_SECTIONS) {
    texts.push(section.title, section.subtitle, section.stage, section.note, stageText(section));
  }
  return texts;
}