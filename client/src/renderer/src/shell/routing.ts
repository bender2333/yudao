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
  // 资料页选中的建档轮次（工单 #573，设计第 3.4 节写在 ?round= 中）：进入资料页时滚到对应轮次
  round: number | null;
  /**
   * 设置页要滚到的那一节（工单 #1161，写在 ?section= 中）：决定卡片上的「前往本项目的部门设置」
   * 落到部门设置那一节，不停在设置页的顶部；没有指定时是 null。
   * 设置页底部「模型请求与用量」这一节的展开状态也用它（工单 #1710）：section=requests 表示展开。
   */
  settingsSection: string | null;
  /**
   * 「模型请求与用量」这一节的筛选条件（工单 #1710）：写在 ?dept=、?status=、?provider=、
   * ?model=、?model_returned=、?q= 中，页面从地址读回来、写回地址。
   * 观测页只用到其中的职能（?dept=，工单 #801）：其余几格按空值读回，不写进地址。
   */
  requestFilters: Filters;
  /**
   * 请求详情的来处（工单 #1710，写在 ?from= 中）：从设置页这一节、从对话页的工作过程点进来时
   * 返回对应的那一页；没有写或认不出时是 null，页面显示原来的「返回请求记录」。
   */
  attemptOrigin: "settings" | "conversation" | null;
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
  // 对话页是打开项目时的那一页（工单 #1638）：上面是循环图，线程与时序图由后面的工单接上
  conversation: "对话",
  overview: "概览",
  materials: "资料",
  observe: "观测",
  "observe-detail": "请求详情",
  // 职能详情（工单 #1713）：从节点面板的「职能详情」进，路径上写职能名，见 pathLabel
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
  const named = route.name === "dept" || route.name === "dept-detail";
  const page = named ? departmentName(route.department) : PAGE_LABELS[route.name] ?? "这个页面";
  const project = projects.find((item) => item.project_id === route.projectId);
  const name = project?.name ?? route.projectId ?? "";
  return `${name} / ${page}`;
}

// 打开一个项目时落在哪一页（工单 #1638，项目的组织设计说明 4.14）：项目页先是对话，
// 循环图在对话上面（工单 #1715：页签只剩对话与设置）。
export const DEFAULT_PROJECT_PAGE = "conversation";

// 收进对话页的旧页（工单 #1715，设计说明「项目页只有两页」）：概览、资料、观测与各职能页不再有页签，
// 旧地址打开时落到对话，保留地址里的事项；请求详情、恢复详情与职能详情是点进去的详情页，地址照旧可用。
const RETIRED_PAGES: ReadonlySet<string> = new Set(["overview", "materials", "observe", "dept"]);

export function parseRoute(hash: string): Route {
  const text = (hash || "").replace(/^#/, "");
  const [pathPart, queryPart] = text.split("?", 2);
  const query = new URLSearchParams(queryPart ?? "");
  const segments = pathPart.split("/").filter(Boolean);
  const route: Route = { name: "home", projectId: null, workItemId: null, department: null, departmentFilter: departmentFilter(query), systemPage: null, attemptId: null, runId: null, at: replayPosition(query), round: parseRound(query), settingsSection: sectionOf(query), requestFilters: filtersFromQuery(query), attemptOrigin: attemptOrigin(query) };
  if (segments.length === 0 || segments[0] === "home") {
    route.name = "home";
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
      // 职能详情（工单 #1713）：#/p/{项目}/dept-detail/{职能}；事项范围写在参数 w 中，
      // 关闭这一页时按它回到原来的事项
      route.name = "dept-detail";
      route.department = segments[3];
      return route;
    }
    if (segments[2] === "dept" && segments[3]) {
      // 职能页收进了对话（工单 #1715）：地址照读，写职能的那一段不再有页面，落到对话
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
    route.name = segments[2] ?? DEFAULT_PROJECT_PAGE;
    // 旧页的地址落到对话（工单 #1715）：保留地址里的事项（w），不带旧页的名字
    if (RETIRED_PAGES.has(route.name)) {
      route.name = "conversation";
    }
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

// 请求详情的来处（工单 #1710）：从设置页这一节、从对话页的工作过程点进来时写在 ?from= 中，
// 返回时回到那一页的那一节；认不出的取值按没有来处处理
function attemptOrigin(query: URLSearchParams): "settings" | "conversation" | null {
  const text = query.get("from");
  return text === "settings" || text === "conversation" ? text : null;
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

// 每个页面的路径（原型 v8 设计说明第 3.3 节）
//
// 页签收成对话与设置以后（工单 #1715，设计说明「项目页只有两页」），页面代码里只有下面这一节
// 与对话、设置、职能详情、请求详情、恢复详情、系统页的地址在用。overview、dept、materials、observe、
// overviewAt 这五个构造函数只剩工单 #1716 要删的旧页面（views/project/overview.tsx、department.tsx、
// materials.tsx、observe.tsx）在用：它们不再有页签，地址打开时由 parseRoute 落到对话。旧页面删掉时
// 一并删这五个构造函数。
export const paths = {
  home: () => "#/home",
  // 对话页（工单 #1638）：项目页先是对话，循环图在它上面；事项范围写在 ?w= 里
  conversation: (projectId: string, options: { workItem?: string | null } = {}) =>
    `#/p/${projectId}/conversation${scopeQuery(options.workItem)}`,
  // 首页的回放位置写在 ?at= 中（设计说明第 3.3 节）：刷新、后退与分享链接回到同一位置
  homeAt: (at: number | null) => (at === null ? "#/home" : `#/home?at=${at}`),
  // 只给工单 #1716 要删的概览页用（工单 #1715）
  overview: (projectId: string, options: { workItem?: string | null } = {}) =>
    `#/p/${projectId}/overview${scopeQuery(options.workItem)}`,
  // 只给工单 #1716 要删的职能页用（工单 #1715）
  dept: (projectId: string, department: string, options: { workItem?: string | null } = {}) =>
    `#/p/${projectId}/dept/${department}${scopeQuery(options.workItem)}`,
  // 职能详情（工单 #1713）：从节点面板的「职能详情」进来，关闭时按 ?w= 回到原来的事项
  departmentDetail: (projectId: string, department: string, options: { workItem?: string | null } = {}) =>
    `#/p/${projectId}/dept-detail/${department}${scopeQuery(options.workItem)}`,
  recovery: (projectId: string, workItemId: string) => `#/p/${projectId}/w/${workItemId}/recovery`,
  // 只给工单 #1716 要删的资料页用（工单 #1715）
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
  // 只给工单 #1716 要删的观测页用（工单 #1715）；请求原来的列表并进了设置页的「模型请求与用量」
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
  // 刷新、后退与直接输入路径都能读回。from 是来处（设置页这一节或对话页的工作过程，工单 #1710），
  // requests 是设置页这一节的筛选条件：返回时按它们回到原来的样子
  observeDetail: (projectId: string, attemptId: string, options: { workItem?: string | null; runId?: string | null; department?: string | null; from?: "settings" | "conversation" | null; requests?: Filters } = {}) => {
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
  // 只给工单 #1716 要删的概览页用（工单 #1715）。
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
  settings: (projectId: string, options: { workItem?: string | null; section?: string | null; requests?: Filters } = {}) => {
    const query = new URLSearchParams();
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    // 要滚到的那一节（工单 #1161）：「前往本项目的部门设置」直接落在部门设置那一节上
    if (options.section) {
      query.set("section", options.section);
    }
    // 「模型请求与用量」这一节的筛选条件（工单 #1710）：与展开状态一起写在地址里
    appendFilters(query, options.requests);
    const suffix = query.toString();
    return `#/p/${projectId}/settings${suffix ? `?${suffix}` : ""}`;
  },
  sys: (page: string) => `#/sys/${page}`,
};

// 项目页的页签（工单 #1715，设计说明「项目页只有两页」）：只有对话与设置两项，任何组织下都一样。
// 页签上带的那条查询由 app.tsx 按服务端能给的查询筛：取不到时这个页签不出现（与原来一样）。
export type ProjectTab = { label: string; hash: string; query: string };

export function projectTabs(projectId: string, workItemId: string | null): ProjectTab[] {
  const workItem = workItemId === "" ? null : workItemId;
  return [
    { label: "对话", hash: paths.conversation(projectId, { workItem }), query: "project.loop" },
    { label: "设置", hash: paths.settings(projectId, { workItem }), query: "project.settings" },
  ];
}

// 换一个事项范围，仍在当前页（原型 v10 的 Y10.paths.withScope，工单 #746）。
// 范围是项目级的一份，写在 ?w= 里；换范围只改这一个参数，页面本身不变。
// 页签收成对话与设置以后（工单 #1715），当前页只剩对话、设置与几个详情页：
//   - 收进对话的旧页（概览、资料、观测、职能页）换范围时落到对话；
//   - 请求详情换范围时回到请求所在的列表：设置页的「模型请求与用量」那一节（原来的观测页并进了它），
//     详情页的内容属于某一个请求，不随范围变化；
//   - 恢复页按新的事项打开，没有范围时回到对话页；
//   - 设置页的节与筛选条件跟着留着（工单 #1161、#1710）。
// defaultDepartment 是项目现在组织里的第一个部门（工单 #1457）：职能详情没写职能时用它，不写死 product
export function withScope(route: Route, workItemId: string | null, defaultDepartment = ""): string {
  const projectId = route.projectId ?? "";
  switch (route.name) {
    case "dept-detail": {
      // 职能详情（工单 #1713）跟着事项范围走：换范围留在同一个职能的这一页
      const department = route.department ?? defaultDepartment;
      return department === ""
        ? paths.conversation(projectId, { workItem: workItemId })
        : paths.departmentDetail(projectId, department, { workItem: workItemId });
    }
    case "observe-detail":
      return paths.settings(projectId, {
        workItem: workItemId,
        section: REQUESTS_SECTION,
        requests: route.requestFilters,
      });
    case "recovery":
      return workItemId === null ? paths.conversation(projectId) : paths.recovery(projectId, workItemId);
    case "settings":
      // 要滚到的那一节跟着留着：换范围不动这一页落在哪一节（工单 #1161）；
      // 「模型请求与用量」这一节的筛选条件也留着（工单 #1710）：换范围是换哪些事项的请求，
      // 不动职能、状态与模型这几格
      return paths.settings(projectId, { workItem: workItemId, section: route.settingsSection, requests: route.requestFilters });
    default:
      // 对话页，以及收进对话的旧页（overview、materials、observe、dept）
      return paths.conversation(projectId, { workItem: workItemId });
  }
}

// 请求详情的返回去处与文案（工单 #1710；收页签以后的去处见工单 #1715）：
// 从设置页这一节进来：回到这一节并保持展开（section=requests）与同一组筛选；
// 从对话页的工作过程进来：回到同一事项范围的对话页；
// 没有来处（直接输入地址、旧链接）：回到设置页的「模型请求与用量」——请求原来的列表页已经并进这一节。
export function attemptBackPath(route: Route): { label: string; hash: string } {
  const projectId = route.projectId ?? "";
  if (route.attemptOrigin === "conversation") {
    return { label: "返回对话", hash: paths.conversation(projectId, { workItem: route.workItemId }) };
  }
  return {
    label: "返回模型请求与用量",
    hash: paths.settings(projectId, { workItem: route.workItemId, section: REQUESTS_SECTION, requests: route.requestFilters }),
  };
}
