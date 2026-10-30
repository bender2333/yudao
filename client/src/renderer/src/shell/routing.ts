// 页面路径（原型 v8 设计说明第 3.3 节）：首页 #/home、机器页 #/sys/machines 等。
// 本工单建立外壳与路径；首页、项目页面与像素画面由各自的工单实现。

import { DEPARTMENTS, departmentName } from "../views/project/labels.ts";

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
  // 资料页选中的建档轮次（工单 #573，设计第 3.4 节写在 ?round= 中）：进入资料页时滚到对应轮次
  round: number | null;
  /**
   * 设置页要滚到的那一节（工单 #1161，写在 ?section= 中）：决定卡片上的「前往本项目的部门设置」
   * 落到部门设置那一节，不停在设置页的顶部；没有指定时是 null。
   */
  settingsSection: string | null;
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
  overview: "概览",
  materials: "资料",
  observe: "观测",
  "observe-detail": "请求详情",
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
 * 顶栏的路径：项目内页面写「项目名 / 页名」，系统页只写页名（设计说明第 9.1 节）。
 * 部门页的页名就是部门名，与页签一致（产品、工程、质检）。
 */
export function pathLabel(route: Route, projects: { project_id: string; name: string }[]): string {
  if (route.name === "home" || route.name === "not-found") {
    return "首页";
  }
  if (route.name.startsWith("sys-")) {
    return PAGE_LABELS[route.name] ?? "系统";
  }
  const page = route.name === "dept" ? departmentName(route.department) : PAGE_LABELS[route.name] ?? "这个页面";
  const project = projects.find((item) => item.project_id === route.projectId);
  const name = project?.name ?? route.projectId ?? "";
  return `${name} / ${page}`;
}

export function parseRoute(hash: string): Route {
  const text = (hash || "").replace(/^#/, "");
  const [pathPart, queryPart] = text.split("?", 2);
  const query = new URLSearchParams(queryPart ?? "");
  const segments = pathPart.split("/").filter(Boolean);
  const route: Route = { name: "home", projectId: null, workItemId: null, department: null, departmentFilter: departmentFilter(query), systemPage: null, attemptId: null, runId: null, at: replayPosition(query), round: parseRound(query), settingsSection: sectionOf(query) };
  if (segments.length === 0 || segments[0] === "home") {
    route.name = "home";
    return route;
  }
  // 动作图鉴：只在开发时使用，不进入正式的页面入口（页签、侧栏与 paths 里都没有它）
  if (segments[0] === "gallery") {
    route.name = "gallery";
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
    if (segments[2] === "dept" && segments[3]) {
      route.name = "dept";
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
    route.name = segments[2] ?? "overview";
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

// 路径参数里的建档轮次：正整数才认
function parseRound(query: URLSearchParams): number | null {
  const text = query.get("round");
  if (text === null || !/^[1-9]\d*$/.test(text)) {
    return null;
  }
  return Number(text);
}

// 路径参数里的部门筛选条件（工单 #801）：只有已知的部门才认，
// 未知取值按没有筛选处理，不把无效的部门发给服务端
function departmentFilter(query: URLSearchParams): string | null {
  const text = query.get("dept");
  if (text === null || !Object.keys(DEPARTMENTS).includes(text)) {
    return null;
  }
  return text;
}

// 路径参数里的设置页节名（工单 #1161）：按原样读出来，由设置页决定认不认它；
// 空串按没有指定处理，地址里不留空的 ?section=
function sectionOf(query: URLSearchParams): string | null {
  const text = query.get("section");
  return text === null || text.trim() === "" ? null : text.trim();
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

// 每个页面的路径（原型 v8 设计说明第 3.3 节）
export const paths = {
  home: () => "#/home",
  // 首页的回放位置写在 ?at= 中（设计说明第 3.3 节）：刷新、后退与分享链接回到同一位置
  homeAt: (at: number | null) => (at === null ? "#/home" : `#/home?at=${at}`),
  overview: (projectId: string, options: { workItem?: string | null } = {}) =>
    `#/p/${projectId}/overview${scopeQuery(options.workItem)}`,
  dept: (projectId: string, department: string, options: { workItem?: string | null } = {}) =>
    `#/p/${projectId}/dept/${department}${scopeQuery(options.workItem)}`,
  recovery: (projectId: string, workItemId: string) => `#/p/${projectId}/w/${workItemId}/recovery`,
  materials: (projectId: string, options: { workItem?: string | null; round?: number | null } = {}) => {
    const query = new URLSearchParams();
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    if (options.round) {
      query.set("round", String(options.round));
    }
    const suffix = query.toString();
    return `#/p/${projectId}/materials${suffix ? `?${suffix}` : ""}`;
  },
  // 观测页：事项范围（w）与部门筛选条件（dept）都写在参数里。
  // 范围是作用域，部门是筛选条件：两者各写各的，不混在一处（工单 #801）
  observe: (projectId: string, options: { workItem?: string | null; department?: string | null } = {}) => {
    const query = new URLSearchParams();
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    if (options.department) {
      query.set("dept", options.department);
    }
    const suffix = query.toString();
    return `#/p/${projectId}/observe${suffix ? `?${suffix}` : ""}`;
  },
  // 请求详情：事项范围（w）、run 标识（r）与部门筛选条件（dept）都写在参数里，
  // 刷新、后退与直接输入路径都能读回
  observeDetail: (projectId: string, attemptId: string, options: { workItem?: string | null; runId?: string | null; department?: string | null } = {}) => {
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
    const suffix = query.toString();
    return `#/p/${projectId}/observe/${attemptId}${suffix ? `?${suffix}` : ""}`;
  },
  // 概览页的回放位置写在 ?at= 中，与首页共用同一个参数名；回到现在时路径不带 at。
  // 事项范围（w）与回放位置一起带着：换回放位置不丢掉所选范围。
  overviewAt: (projectId: string, at: number | null, options: { workItem?: string | null } = {}) => {
    const query = new URLSearchParams();
    if (at !== null) {
      query.set("at", String(at));
    }
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    const suffix = query.toString();
    return `#/p/${projectId}/overview${suffix ? `?${suffix}` : ""}`;
  },
  settings: (projectId: string, options: { workItem?: string | null; section?: string | null } = {}) => {
    const query = new URLSearchParams();
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    // 要滚到的那一节（工单 #1161）：「前往本项目的部门设置」直接落在部门设置那一节上
    if (options.section) {
      query.set("section", options.section);
    }
    const suffix = query.toString();
    return `#/p/${projectId}/settings${suffix ? `?${suffix}` : ""}`;
  },
  sys: (page: string) => `#/sys/${page}`,
};

// 换一个事项范围，仍在当前页（原型 v10 的 Y10.paths.withScope，工单 #746）。
// 范围是项目级的一份，写在 ?w= 里；换范围只改这一个参数，页面本身不变。
// 请求详情页回到请求记录页（详情页的内容属于某一个请求，不随范围变化）；
// 恢复页按新的事项打开，没有范围时回到概览页（恢复页按事项看，没有事项就没有内容）。
// 观测页的部门筛选条件（?dept=）跟着留着：换范围是换「哪些事项的请求」，
// 不动「哪个部门的请求」（工单 #801）
export function withScope(route: Route, workItemId: string | null): string {
  const projectId = route.projectId ?? "";
  switch (route.name) {
    case "dept":
      return paths.dept(projectId, route.department ?? "product", { workItem: workItemId });
    case "materials":
      return paths.materials(projectId, { workItem: workItemId });
    case "observe":
      return paths.observe(projectId, { workItem: workItemId, department: route.departmentFilter });
    case "observe-detail":
      return paths.observe(projectId, { workItem: workItemId, department: route.departmentFilter });
    case "recovery":
      return workItemId === null ? paths.overview(projectId) : paths.recovery(projectId, workItemId);
    case "settings":
      // 要滚到的那一节跟着留着：换范围不动这一页落在哪一节（工单 #1161）
      return paths.settings(projectId, { workItem: workItemId, section: route.settingsSection });
    default:
      return paths.overview(projectId, { workItem: workItemId });
  }
}
