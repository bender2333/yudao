// 页面路径（原型 v8 设计说明第 3.3 节）：首页 #/home、机器页 #/sys/machines 等。
// 本工单建立外壳与路径；首页、项目页面与像素画面由各自的工单实现。

export type Route = {
  name: string;
  projectId: string | null;
  workItemId: string | null;
  department: string | null;
  systemPage: string | null;
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
  const route: Route = { name: "home", projectId: null, workItemId: null, department: null, systemPage: null };
  if (segments.length === 0 || segments[0] === "home") {
    route.name = "home";
    return route;
  }
  if (segments[0] === "connect") {
    route.name = "connect";
    return route;
  }
  // 客户端自己的设置页：连接设置、本机服务与登录时启动（设计说明第 4.3、4.5 节）。
  // 名字与项目设置页（#/p/<项目>/settings）分开，两个页面不互相顶替
  if (segments[0] === "settings") {
    route.name = "client-settings";
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
      route.name = "observe-detail";
      return route;
    }
    route.name = segments[2] ?? "overview";
    return route;
  }
  route.name = "not-found";
  return route;
}

// 每个页面的路径（原型 v8 设计说明第 3.3 节）
export const paths = {
  home: () => "#/home",
  connect: () => "#/connect",
  overview: (projectId: string) => `#/p/${projectId}/overview`,
  dept: (projectId: string, department: string) => `#/p/${projectId}/dept/${department}`,
  recovery: (projectId: string, workItemId: string) => `#/p/${projectId}/w/${workItemId}/recovery`,
  materials: (projectId: string) => `#/p/${projectId}/materials`,
  observe: (projectId: string) => `#/p/${projectId}/observe`,
  settings: (projectId: string) => `#/p/${projectId}/settings`,
  sys: (page: string) => `#/sys/${page}`,
  // 客户端自己的设置页（与项目设置不同：连接设置、本机服务与登录时启动）
  clientSettings: () => "#/settings",
};
