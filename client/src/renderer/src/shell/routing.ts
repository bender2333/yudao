// 页面路径（原型 v8 设计说明第 3.3 节）：首页 #/home、机器页 #/sys/machines 等。
// 本工单建立外壳与路径；首页、项目页面与像素画面由各自的工单实现。

import { departmentName } from "../views/project/labels.ts";
import { EMPTY_FILTERS, filtersFromQuery, filtersQuery, type Filters } from "../views/project/observe-filter.ts";

export type Route = {
  name: string;
  projectId: string | null;
  // 事项范围（作用域）：项目内的一份，写在路径参数 ?w= 中；null 表示整个项目（工单 #746）
  workItemId: string | null;
  department: string | null;
  // 观测页的部门筛选条件（筛选条件，不是范围）：写在路径参数 ?dept= 中；
  // null 表示这一格没有筛选（工单 #801）
  departmentFilter: string | null;
  systemPage: string | null;
  attemptId: string | null;
  runId: string | null;
  // 回放位置（全局位置，设计说明第 3.3 节写在 ?at= 中）：刷新、后退与分享链接都回到同一位置；
  // 为 null 时是实时画面
  at: number | null;
  /**
   * 设置页要滚到的那一节（工单 #1161，写在 ?section= 中）：决定卡片上的「前往本项目的部门设置」
   * 落到部门设置那一节，不停在设置页的顶部；没有指定时是 null。
   * 旧地址带 section=requests 时，由 parseRoute 转到「事项与用量」页的「模型请求与用量」子视图（工单 #1809）。
   */
  settingsSection: string | null;
  /**
   * 「模型请求与用量」的筛选条件（工单 #1710、#1809）：写在 ?dept=、?status=、?provider=、
   * ?model=、?model_returned=、?q= 中，页面从地址读回来、写回地址。
   */
  requestFilters: Filters;
  /** 「事项与用量」页的子视图（工单 #1809，写在 ?tab= 中）：默认事项列表（"items"），tab=requests 时为模型请求与用量 */
  itemsTab: "items" | "requests";
  /** 职能详情的来处（工单 #1809，写在 ?from= 中）：从「组织」页进为 "org"，从「对话」页进为 "conversation"，未写为 null */
  departmentOrigin: "conversation" | "org" | null;
  /** 对话页展开箭头的标识（工单 #1809，写在 ?arrow= 中） */
  arrowFlowId: string | null;
  /**
   * 请求详情的来处（工单 #1710、#1809，写在 ?from= 中）：从「事项与用量」页的请求列表或从对话页工作过程点进来时
   * 返回对应的那一页；旧参数 ?from=settings 兼容折算为 "items"；没有写或认不出时为 null。
   */
  attemptOrigin: "items" | "conversation" | null;
};

const SYSTEM_PAGES: Record<string, string> = {
  models: "sys-models",
  machines: "sys-machines",
  runtime: "sys-runtime",
  tools: "sys-tools",
  // 规则与参数页（工单 #1195，应用层与接口层设计说明「规则与参数在页面上的显示」）
  rules: "sys-rules",
};

// 顶栏的路径里的页名（设计说明第 3.4、9.1 节）：项目内页面写页名，系统页写它自己的页名。
// 系统页的页名与页面里的标题一致，不写路由里的英文段名（工单 #702）
const PAGE_LABELS: Record<string, string> = {
  // 独立新建与接入已有项目页（工单 #1806）
  "new-project": "从想法新建项目",
  "onboard-project": "接入已有项目",
  // 五个一级标签页（工单 #1809）：对话 · 成果库 · 组织 · 事项与用量 · 设置
  conversation: "对话",
  outcomes: "成果库",
  org: "组织",
  items: "事项与用量",
  "observe-detail": "请求详情",
  // 职能详情（工单 #1713）：从节点面板或组织页的「职能详情」进，路径上写职能名，见 pathLabel
  "dept-detail": "职能详情",
  settings: "设置",
  recovery: "恢复",
  "sys-models": "模型管理",
  "sys-machines": "机房",
  "sys-runtime": "执行槽位",
  "sys-tools": "工具登记",
  // 规则与参数页（工单 #1195）：页名与页面里的标题一致，写规则登记
  "sys-rules": "规则登记",
};

/**
 * 顶栏的路径：项目内页面写「项目名 / 页名」，系统页与新建/接入页只写页名（设计说明第 9.1 节）。
 * 部门页的页名就是部门名，与页签一致（产品、工程、质检）。
 */
export function pathLabel(route: Route, projects: { project_id: string; name: string }[]): string {
  if (route.name === "home" || route.name === "not-found") {
    return "首页";
  }
  if (route.name.startsWith("sys-")) {
    return PAGE_LABELS[route.name] ?? "系统";
  }
  if (route.name === "new-project" || route.name === "onboard-project") {
    return PAGE_LABELS[route.name];
  }
  const named = route.name === "dept" || route.name === "dept-detail";
  const page = named ? departmentName(route.department) : PAGE_LABELS[route.name] ?? "这个页面";
  const project = projects.find((item) => item.project_id === route.projectId);
  const name = project?.name ?? route.projectId ?? "";
  return `${name} / ${page}`;
}

// 打开一个项目时落在哪一页（工单 #1638、#1809）：项目页先是对话
export const DEFAULT_PROJECT_PAGE = "conversation";

export function parseRoute(hash: string): Route {
  const text = (hash || "").replace(/^#/, "");
  const [pathPart, queryPart] = text.split("?", 2);
  const query = new URLSearchParams(queryPart ?? "");
  const segments = pathPart.split("/").filter(Boolean);
  const route: Route = {
    name: "home",
    projectId: null,
    workItemId: null,
    department: null,
    departmentFilter: departmentFilter(query),
    systemPage: null,
    attemptId: null,
    runId: null,
    at: replayPosition(query),
    settingsSection: sectionOf(query),
    requestFilters: filtersFromQuery(query),
    itemsTab: itemsTabOf(query),
    departmentOrigin: departmentOriginOf(query),
    arrowFlowId: nonEmptyQuery(query, "arrow"),
    attemptOrigin: attemptOrigin(query),
  };
  if (segments.length === 0 || segments[0] === "home") {
    route.name = "home";
    return route;
  }
  // 独立新建与接入已有项目（工单 #1806）：规范路径为 #/projects/new 与 #/projects/onboard，
  // 同时兼容识别 #/new 与 #/onboard
  if ((segments[0] === "projects" && segments[1] === "new" && segments.length === 2)
    || (segments[0] === "new" && segments.length === 1)) {
    route.name = "new-project";
    return route;
  }
  if ((segments[0] === "projects" && segments[1] === "onboard" && segments.length === 2)
    || (segments[0] === "onboard" && segments.length === 1)) {
    route.name = "onboard-project";
    return route;
  }
  if (segments[0] === "sys" && segments.length === 2) {
    route.name = SYSTEM_PAGES[segments[1]] ?? "sys-reserved";
    route.systemPage = segments[1];
    return route;
  }
  if (segments[0] === "p" && segments[1]) {
    route.projectId = segments[1];
    // 事项范围：空值按没有范围处理（地址里不留空的 ?w=，工单 #746）
    route.workItemId = query.get("w") || null;
    if (segments[2] === "dept-detail" && segments[3]) {
      // 职能详情（工单 #1713）：#/p/{项目}/dept-detail/{职能}；事项范围写在参数 w 中
      route.name = "dept-detail";
      route.department = segments[3];
      return route;
    }
    if (segments[2] === "dept" && segments[3]) {
      // 职能页收进了对话（工单 #1715、#1809）：地址照读，写职能的那一段落到对话
      route.name = "conversation";
      route.department = segments[3];
      return route;
    }
    if (segments[2] === "w" && segments[3] && segments[4] === "recovery") {
      route.name = "recovery";
      route.workItemId = segments[3];
      return route;
    }
    if (segments[2] === "observe" && segments[3]) {
      // 观测详情：#/p/{项目}/observe/{请求标识}；run 标识写在参数 r 中，刷新与后退以后仍能直接读取
      route.name = "observe-detail";
      route.attemptId = segments[3];
      route.runId = query.get("r");
      return route;
    }
    const page = segments[2] ?? DEFAULT_PROJECT_PAGE;
    // 旧地址兼容（工单 #1809）：overview/dept -> conversation，materials -> outcomes，
    // observe（无请求标识）与 settings?section=requests -> items?tab=requests
    if (page === "overview" || page === "dept") {
      route.name = "conversation";
      return route;
    }
    if (page === "materials") {
      route.name = "outcomes";
      return route;
    }
    if (page === "observe") {
      route.name = "items";
      route.itemsTab = "requests";
      return route;
    }
    if (page === "settings" && route.settingsSection === REQUESTS_SECTION) {
      route.name = "items";
      route.itemsTab = "requests";
      route.settingsSection = null;
      return route;
    }
    route.name = page;
    return route;
  }
  route.name = "not-found";
  return route;
}

// 路径参数里的回放位置：非负整数才认，否则按实时画面处理（手改地址栏的输入不当作位置）
function replayPosition(query: URLSearchParams): number | null {
  const text = query.get("at");
  if (text === null || !/^\d+$/.test(text)) {
    return null;
  }
  return Number(text);
}

// 路径参数里的部门筛选条件（工单 #801）：按原样读出来，认不认它由页面拿项目的职能清单去对
// （工单 #1710：项目的职能清单可能与默认的三个不同，地址里不带白名单以外的一律丢掉就会被吃掉）。
// 空串按没有筛选处理，地址里不留空的 ?dept=
function departmentFilter(query: URLSearchParams): string | null {
  const text = query.get("dept");
  if (text === null || text.trim() === "") {
    return null;
  }
  return text.trim();
}

// 「事项与用量」页的子视图（工单 #1809）：默认事项列表，?tab=requests 时切到模型请求与用量
function itemsTabOf(query: URLSearchParams): "items" | "requests" {
  return query.get("tab") === "requests" ? "requests" : "items";
}

// 职能详情的来处（工单 #1809）：?from=org 或 ?from=conversation，其余取值按未写处理
function departmentOriginOf(query: URLSearchParams): "conversation" | "org" | null {
  const text = query.get("from");
  return text === "org" || text === "conversation" ? text : null;
}

// 读取非空查询参数：空值按 null 处理
function nonEmptyQuery(query: URLSearchParams, key: string): string | null {
  const text = query.get(key);
  return text === null || text.trim() === "" ? null : text.trim();
}

// 请求详情的来处（工单 #1710、#1809）：从「事项与用量」的请求列表或对话页的工作过程点进来时写在 ?from= 中，
// 旧地址里的 from=settings 兼容折算为 "items"；认不出的取值按没有来处处理
function attemptOrigin(query: URLSearchParams): "items" | "conversation" | null {
  const text = query.get("from");
  if (text === "conversation") {
    return "conversation";
  }
  if (text === "items" || text === "settings") {
    return "items";
  }
  return null;
}

// 路径参数里的设置页节名（工单 #1161）：按原样读出来，由设置页决定认不认它；
// 空串按没有指定处理，地址里不留空的 ?section=
function sectionOf(query: URLSearchParams): string | null {
  const text = query.get("section");
  return text === null || text.trim() === "" ? null : text.trim();
}

// 设置页底部「模型请求与用量」这一节的名字（工单 #1710）：地址里写 ?section=requests 时它是展开的，
// 请求详情的「返回模型请求与用量」也落回这一节
export const REQUESTS_SECTION = "requests";

// 一组筛选条件写进地址参数（工单 #1710）：先写的参数位置不变，值以后写的为准
function appendFilters(query: URLSearchParams, filters: Filters | undefined): void {
  for (const [name, value] of filtersQuery(filters ?? EMPTY_FILTERS)) {
    query.set(name, value);
  }
}

// 事项范围（作用域）：项目内的一份，写在路径参数 ?w= 中（原型第 3.3 节）。
// 没有范围（整个项目）时不带这个参数：地址里不留空的 ?w=，两种写法不并存。
function scopeQuery(workItem: string | null | undefined): string {
  if (!workItem) {
    return "";
  }
  const query = new URLSearchParams();
  query.set("w", workItem);
  return `?${query.toString()}`;
}

// 每个页面的路径（工单 #1809：五个一级标签页为对话、成果库、组织、事项与用量、设置）
export const paths = {
  home: () => "#/home",
  // 独立新建与接入已有项目页（工单 #1806）：规范路径，与项目组织设计及原型一致
  newProject: () => "#/projects/new",
  onboardProject: () => "#/projects/onboard",
  // 对话页（工单 #1638、#1745、#1809）：事项范围写入 ?w=，回放位置写入 ?at=，展开箭头写入 ?arrow=
  conversation: (projectId: string, options: { workItem?: string | null; at?: number | null; arrow?: string | null } = {}) => {
    const query = new URLSearchParams();
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    if (options.at !== undefined && options.at !== null && Number.isInteger(options.at) && options.at >= 0) {
      query.set("at", String(options.at));
    }
    if (options.arrow) {
      query.set("arrow", options.arrow);
    }
    const suffix = query.toString();
    return `#/p/${projectId}/conversation${suffix ? `?${suffix}` : ""}`;
  },
  // 成果库页（工单 #1809）
  outcomes: (projectId: string, options: { workItem?: string | null } = {}) =>
    `#/p/${projectId}/outcomes${scopeQuery(options.workItem)}`,
  // 组织页（工单 #1809）
  org: (projectId: string, options: { workItem?: string | null } = {}) =>
    `#/p/${projectId}/org${scopeQuery(options.workItem)}`,
  // 事项与用量页（工单 #1809）：tab 为 "requests" 时写入 ?tab=requests，默认事项列表省略 tab
  items: (projectId: string, options: { workItem?: string | null; tab?: "items" | "requests" | null; requests?: Filters } = {}) => {
    const query = new URLSearchParams();
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    if (options.tab === "requests") {
      query.set("tab", "requests");
    }
    appendFilters(query, options.requests);
    const suffix = query.toString();
    return `#/p/${projectId}/items${suffix ? `?${suffix}` : ""}`;
  },
  // 首页的回放位置写在 ?at= 中（设计说明第 3.3 节）：刷新、后退与分享链接回到同一位置
  homeAt: (at: number | null) => (at === null ? "#/home" : `#/home?at=${at}`),
  // 职能详情（工单 #1713、#1809）：从节点面板或组织页进来，写入 ?w= 与 ?from=
  departmentDetail: (projectId: string, department: string, options: { workItem?: string | null; from?: "conversation" | "org" | null } = {}) => {
    const query = new URLSearchParams();
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    if (options.from) {
      query.set("from", options.from);
    }
    const suffix = query.toString();
    return `#/p/${projectId}/dept-detail/${department}${suffix ? `?${suffix}` : ""}`;
  },
  recovery: (projectId: string, workItemId: string) => `#/p/${projectId}/w/${workItemId}/recovery`,
  // 请求详情：事项范围（w）、run 标识（r）与部门筛选条件（dept）都写在参数里，
  // from 是来处（"items" 或 "conversation"，工单 #1809），requests 是请求列表的筛选条件
  observeDetail: (projectId: string, attemptId: string, options: { workItem?: string | null; runId?: string | null; department?: string | null; from?: "items" | "conversation" | null; requests?: Filters } = {}) => {
    const query = new URLSearchParams();
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    if (options.runId) {
      query.set("r", options.runId);
    }
    if (options.department) {
      query.set("dept", options.department);
    }
    if (options.from) {
      query.set("from", options.from);
    }
    appendFilters(query, options.requests);
    const suffix = query.toString();
    return `#/p/${projectId}/observe/${attemptId}${suffix ? `?${suffix}` : ""}`;
  },
  settings: (projectId: string, options: { workItem?: string | null; section?: string | null; requests?: Filters } = {}) => {
    const query = new URLSearchParams();
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    // 要滚到的那一节（工单 #1161）：「前往本项目的部门设置」直接落在部门设置那一节上
    if (options.section) {
      query.set("section", options.section);
    }
    appendFilters(query, options.requests);
    const suffix = query.toString();
    return `#/p/${projectId}/settings${suffix ? `?${suffix}` : ""}`;
  },
  sys: (page: string) => `#/sys/${page}`,
};

// 项目页的一级标签页（工单 #1809）：五个一级标签页「对话 · 成果库 · 组织 · 事项与用量 · 设置」。
// 页签上带的那条查询由 app.tsx 按服务端能给的查询筛：取不到时这个页签不出现。
export type ProjectTab = { label: string; hash: string; query: string };

export function projectTabs(projectId: string, workItemId: string | null): ProjectTab[] {
  const workItem = workItemId === "" ? null : workItemId;
  return [
    { label: "对话", hash: paths.conversation(projectId, { workItem }), query: "project.loop" },
    { label: "成果库", hash: paths.outcomes(projectId, { workItem }), query: "project.overview" },
    { label: "组织", hash: paths.org(projectId, { workItem }), query: "project.organization" },
    { label: "事项与用量", hash: paths.items(projectId, { workItem }), query: "project.overview" },
    { label: "设置", hash: paths.settings(projectId, { workItem }), query: "project.settings" },
  ];
}

// 换一个事项范围，仍在当前页（原型 v10 的 Y10.paths.withScope，工单 #746、#1809）。
export function withScope(route: Route, workItemId: string | null, defaultDepartment = ""): string {
  const projectId = route.projectId ?? "";
  switch (route.name) {
    case "outcomes":
      return paths.outcomes(projectId, { workItem: workItemId });
    case "org":
      return paths.org(projectId, { workItem: workItemId });
    case "items":
      return paths.items(projectId, {
        workItem: workItemId,
        tab: route.itemsTab,
        requests: route.itemsTab === "requests" ? route.requestFilters : undefined,
      });
    case "dept-detail": {
      const department = route.department ?? defaultDepartment;
      return department === ""
        ? paths.conversation(projectId, { workItem: workItemId })
        : paths.departmentDetail(projectId, department, { workItem: workItemId, from: route.departmentOrigin });
    }
    case "observe-detail":
      return paths.items(projectId, {
        workItem: workItemId,
        tab: "requests",
        requests: route.requestFilters,
      });
    case "recovery":
      return workItemId === null ? paths.conversation(projectId) : paths.recovery(projectId, workItemId);
    case "settings":
      return paths.settings(projectId, { workItem: workItemId, section: route.settingsSection, requests: route.requestFilters });
    default:
      return paths.conversation(projectId, { workItem: workItemId });
  }
}

// 请求详情的返回去处与文案（工单 #1710、#1809）：
// 从「事项与用量」的请求列表或没有来处时回到「事项与用量」的「模型请求与用量」子视图并保留筛选；
// 从对话页的工作过程进来时回到同一事项范围的对话页。
export function attemptBackPath(route: Route): { label: string; hash: string } {
  const projectId = route.projectId ?? "";
  if (route.attemptOrigin === "conversation") {
    return { label: "返回对话", hash: paths.conversation(projectId, { workItem: route.workItemId }) };
  }
  return {
    label: "返回模型请求与用量",
    hash: paths.items(projectId, { workItem: route.workItemId, tab: "requests", requests: route.requestFilters }),
  };
}
