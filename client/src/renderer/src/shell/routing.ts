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
};
