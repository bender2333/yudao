// 页面路径（原型 v8 设计说明第 3.3 节）：首页 #/home、机器页 #/sys/machines 等。
// 本工单建立外壳与路径；首页、项目页面与像素画面由各自的工单实现。

export type Route = {
  name: string;
  projectId: string | null;
  workItemId: string | null;
  department: string | null;
  systemPage: string | null;
  attemptId: string | null;
  runId: string | null;
  // 回放位置（全局位置，设计说明第 3.3 节写在 ?at= 中）：刷新、后退与分享链接都回到同一位置；
  // 为 null 时是实时画面
  at: number | null;
};

const SYSTEM_PAGES: Record<string, string> = {
  models: "sys-models",
  machines: "sys-machines",
  runtime: "sys-runtime",
  tools: "sys-tools",
};

export function parseRoute(hash: string): Route {
  const text = (hash || "").replace(/^#/, "");
  const [pathPart, queryPart] = text.split("?", 2);
  const query = new URLSearchParams(queryPart ?? "");
  const segments = pathPart.split("/").filter(Boolean);
  const route: Route = { name: "home", projectId: null, workItemId: null, department: null, systemPage: null, attemptId: null, runId: null, at: replayPosition(query) };
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
    route.workItemId = query.get("w");
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

// 每个页面的路径（原型 v8 设计说明第 3.3 节）
export const paths = {
  home: () => "#/home",
  // 首页的回放位置写在 ?at= 中（设计说明第 3.3 节）：刷新、后退与分享链接回到同一位置
  homeAt: (at: number | null) => (at === null ? "#/home" : `#/home?at=${at}`),
  overview: (projectId: string) => `#/p/${projectId}/overview`,
  dept: (projectId: string, department: string) => `#/p/${projectId}/dept/${department}`,
  recovery: (projectId: string, workItemId: string) => `#/p/${projectId}/w/${workItemId}/recovery`,
  materials: (projectId: string) => `#/p/${projectId}/materials`,
  observe: (projectId: string) => `#/p/${projectId}/observe`,
  // 请求详情：事项范围（w）与 run 标识（r）都写在参数里，刷新、后退与直接输入路径都能读回
  observeDetail: (projectId: string, attemptId: string, options: { workItem?: string | null; runId?: string | null } = {}) => {
    const query = new URLSearchParams();
    if (options.workItem) {
      query.set("w", options.workItem);
    }
    if (options.runId) {
      query.set("r", options.runId);
    }
    const suffix = query.toString();
    return `#/p/${projectId}/observe/${attemptId}${suffix ? `?${suffix}` : ""}`;
  },
  // 概览页的回放位置写在 ?at= 中，与首页共用同一个参数名；回到现在时路径不带 at
  overviewAt: (projectId: string, at: number | null) =>
    at === null ? `#/p/${projectId}/overview` : `#/p/${projectId}/overview?at=${at}`,
  settings: (projectId: string) => `#/p/${projectId}/settings`,
  sys: (page: string) => `#/sys/${page}`,
};
