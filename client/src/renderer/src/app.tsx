// 页面的应用：连接状态、路由、外壳与页面（原型 v8 设计说明第 3 节，工单 #79 与 #80）。
// 页面由 Yudao 服务提供，接口地址就是页面自己的来源，页面内的导航写在地址 # 之后
// （网页界面的提供与发布设计说明第 5.1 节）。

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Capabilities, DecisionList, DecisionView, ProjectList, ProjectRow, SystemStatus } from "./api/generated/types.gen";
import { ClientApp, type ClientState } from "./contract/client-app";
import { callQuery } from "./contract/invoke";
import { Sidebar } from "./shell/sidebar";
import { Tabbar, Topbar, type Tab } from "./shell/topbar";
import { parseRoute, paths, type Route } from "./shell/routing";
import { HomePage } from "./views/home/page";
import { ModelManagementPage } from "./views/models/page";
import { PlaceholderPage } from "./views/placeholder";
import { DepartmentPage } from "./views/project/department";
import { MaterialsPage } from "./views/project/materials";
import { ObserveDetailPage, ObservePage } from "./views/project/observe";
import { OverviewPage } from "./views/project/overview";
import { SettingsPage } from "./views/project/settings";
import { departmentName } from "./views/project/labels";

// 图鉴页只在开发时用到；用动态导入把它挡在正式包之外
const LazyGallery = lazy(async () => {
  const mod = await import("./views/pixel/gallery");
  return { default: mod.GalleryPage };
});

export function App() {
  const [state, setState] = useState<ClientState>({ kind: "connecting" });
  const [pending, setPending] = useState(0);
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [pendingByProject, setPendingByProject] = useState<Record<string, number>>({});
  const [decisions, setDecisions] = useState<DecisionView[]>([]);
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

  // 页面应用：查询经生成的调用发出，事件到达时更新状态与待决定数量
  const app = useMemo(() => {
    const instance = new ClientApp(callQuery, {
      onState: (next) => setState(next),
      onPendingDecisions: (count) => setPending(count),
    });
    return instance;
  }, []);

  // 图鉴只在开发时可用：直接开 #/gallery 看画法，不连接服务
  const galleryOnly = import.meta.env.DEV && route.name === "gallery";

  useEffect(() => {
    if (galleryOnly) return;
    void app.open(window.location.origin);
    return () => app.close();
  }, [app, galleryOnly]);

  // 路由：监听 hash 变化
  useEffect(() => {
    const onHash = () => {
      setRoute(parseRoute(window.location.hash));
      setDrawerOpen(false);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  // 已连接以后读取项目列表与系统状态；这些视图按事件种类重新查询
  const connected = state.kind === "connected" ? state : null;
  useEffect(() => {
    const views = app.viewSync;
    if (!connected || !views) {
      return;
    }
    void views.open<ProjectList>("shell.projects", { query: "projects.list", params: {} }, (data) => {
      setProjects(data.projects);
    });
    void views.open<DecisionList>("shell.decisions", { query: "decisions.list", params: { status: ["open"] } }, (data) => {
      const grouped: Record<string, number> = {};
      for (const decision of data.decisions) {
        if (decision.project_id) {
          grouped[decision.project_id] = (grouped[decision.project_id] ?? 0) + 1;
        }
      }
      setPendingByProject(grouped);
      setDecisions(data.decisions);
    });
    void views.open<SystemStatus>("shell.status", { query: "system.status", params: undefined }, (data) => {
      setSystemStatus(data);
    });
    return () => {
      views.close("shell.projects");
      views.close("shell.decisions");
      views.close("shell.status");
    };
  }, [app, connected]);

  // 项目标签栏右侧的「待你决定」（原型 v8 设计说明第 3.2 节）：本项目的等待回答的决定请求；
  // 与首页共用一份数据来源（decisions.list），只是筛选到当前项目
  const [projectDecisions, setProjectDecisions] = useState<DecisionView[]>([]);
  useEffect(() => {
    const views = app.viewSync;
    if (!connected || !views || route.projectId === null) {
      setProjectDecisions([]);
      return;
    }
    const viewId = "shell.project.decisions";
    void views.open<DecisionList>(
      viewId,
      { query: "decisions.list", params: { project_id: route.projectId, status: ["open"] } },
      (data) => setProjectDecisions(data.decisions),
    );
    return () => {
      views.close(viewId);
    };
  }, [app, connected, route.projectId]);

  const navigate = useCallback((hash: string) => {
    window.location.hash = hash;
  }, []);

  // 进入模型管理（系统页）之前的路径：点「返回原界面」时回到进入前的页面（设计说明第 3.3 节
  // 第 108 行、工单 #296）。只有从别的页面进入模型管理时才记录；直接输入地址进来没有记录，
  // 回落首页
  const beforeModelsRef = useRef<string | null>(null);
  const prevRouteRef = useRef<string>(window.location.hash);
  useEffect(() => {
    if (route.name === "sys-models" && parseRoute(prevRouteRef.current).name !== "sys-models") {
      beforeModelsRef.current = prevRouteRef.current;
    }
    prevRouteRef.current = window.location.hash;
  }, [route]);

  const backHash = useCallback(() => {
    const back = beforeModelsRef.current;
    return back === null || back === "" ? paths.home() : back;
  }, []);
  // 动作图鉴只在开发时可用：直接开 #/gallery 就能看画法，不必先连上后端。
  // 用动态导入：正式构建里这段分支被整体消掉，图鉴的代码不进正式包，也就没有正式的页面入口。
  if (import.meta.env.DEV && route.name === "gallery") {
    return (
      <Suspense fallback={<div className="gate"><div className="card"><h1>正在载入图鉴…</h1></div></div>}>
        <LazyGallery />
      </Suspense>
    );
  }
  if (state.kind === "connecting") {
    return <div className="gate"><div className="card"><h1>连接中…</h1></div></div>;
  }
  if (state.kind === "outdated") {
    // 页面与服务出自同一个发布，接口版本不同时页面不能使用这个服务
    return (
      <div className="gate"><div className="card">
        <h1>页面与服务的接口版本不同</h1>
        <p className="error">页面的接口版本是 {state.clientVersion}，服务 {state.serverRelease} 的接口版本是 {state.serverVersion}。重新加载页面以取得同一版本的页面文件。</p>
        <button className="primary" type="button" onClick={() => window.location.reload()}>重新加载</button>
      </div></div>
    );
  }
  if (state.kind === "failed") {
    return (
      <div className="gate"><div className="card">
        <h1>没有连上 Yudao 服务</h1>
        <p className="error">连接失败：{state.message}</p>
        <button className="primary" type="button" onClick={() => void app.open(window.location.origin)}>重新连接</button>
      </div></div>
    );
  }

  const capabilities = state.capabilities;
  const tabs = buildTabs(route, capabilities);
  const project = projects.find((item) => item.project_id === route.projectId) ?? null;
  // 连接断开时窗口整体变灰（设计说明第 3.4 节）：根节点带 is-disconnected，数据保留最后一次的
  const disconnected = state.streamConnected === false;
  return (
    <div className={`app${drawerOpen ? " drawer-open" : ""}${disconnected ? " is-disconnected" : ""}`}>
      <Sidebar
        app={app}
        capabilities={capabilities}
        decisions={decisions}
        projects={projects}
        activeProjectId={route.projectId}
        activeName={route.name}
        pendingByProject={pendingByProject}
        onNavigate={navigate}
      />
      {drawerOpen ? (
        <button type="button" className="drawer-scrim" aria-label="关闭左侧栏" onClick={() => setDrawerOpen(false)} />
      ) : null}
      <div className="main">
        <Topbar
          app={app}
          projectId={route.projectId}
          workItemId={route.workItemId}
          project={project}
          path={pathLabel(route, projects)}
          pending={pending}
          projectDecisions={projectDecisions}
          streamConnected={state.streamConnected}
          disconnectedAt={state.disconnectedAt}
          onPendingClick={() => navigate(paths.home())}
          onToggleDrawer={() => setDrawerOpen((open) => !open)}
          onNavigate={navigate}
        />
        <Tabbar tabs={tabs} activeHash={window.location.hash} onNavigate={navigate} />
        <main className="content">
          {route.name === "home" ? (
            <HomePage app={app} onNavigate={navigate} at={route.at} />
          ) : route.name === "sys-models" ? (
            <ModelManagementPage
              views={app.viewSync}
              query={(name, params) => app.queryOne(name, params)}
              command={(name, body) => app.command(name, body)}
              subscribeEvents={(listener) => app.subscribeEvents(listener)}
              // 从系统页返回时回到进入前的页面（设计说明第 3.3 节第 108 行）：进入模型管理前
              // 的路径记在 ref 里，无记录（直接输入地址进来）才回落到首页
              onBack={() => navigate(backHash())}
            />
          ) : (
            <ProjectRouter app={app} route={route} systemStatus={systemStatus} onNavigate={navigate} />
          )}
        </main>
      </div>
    </div>
  );
}

// 项目页面（原型 v8 设计说明第 3.3 节的路径，工单 #80）：按路径分派到具体页面。
// 概览、部门工作间、资料、观测与设置由本工单实现；恢复页（3.1）与系统页由所属工单实现，
// 未实现时显示占位，写明由哪个工单填入。
function ProjectRouter(props: { app: ClientApp; route: Route; systemStatus: SystemStatus | null; onNavigate: (hash: string) => void }) {
  const { route } = props;
  if (route.projectId === null) {
    return <PlaceholderPage route={route} systemStatus={props.systemStatus} />;
  }
  switch (route.name) {
    case "overview":
      return <OverviewPage app={props.app} route={route} onNavigate={props.onNavigate} />;
    case "dept":
      return <DepartmentPage app={props.app} route={route} />;
    case "materials":
      return <MaterialsPage app={props.app} route={route} />;
    case "observe":
      return <ObservePage app={props.app} route={route} />;
    case "observe-detail":
      return <ObserveDetailPage app={props.app} route={route} />;
    case "settings":
      return <SettingsPage app={props.app} route={route} />;
    default:
      return <PlaceholderPage route={route} systemStatus={props.systemStatus} />;
  }
}

// 项目标签（原型 v8 设计说明第 3.2 节）：按能力清单显示，缺少查询的标签不出现
function buildTabs(route: Route, capabilities: Capabilities): Tab[] {
  if (!route.projectId) {
    return [];
  }
  const has = (name: string) => capabilities.queries.some((query) => query.name === name);
  const projectId = route.projectId;
  const candidates: { label: string; hash: string; query: string }[] = [
    { label: "概览", hash: paths.overview(projectId), query: "project.overview" },
    { label: "产品", hash: paths.dept(projectId, "product"), query: "department.workspace" },
    { label: "工程", hash: paths.dept(projectId, "engineering"), query: "department.workspace" },
    { label: "质检", hash: paths.dept(projectId, "quality"), query: "department.workspace" },
    { label: "资料", hash: paths.materials(projectId), query: "work_item.materials" },
    { label: "观测", hash: paths.observe(projectId), query: "project.attempts" },
    { label: "设置", hash: paths.settings(projectId), query: "project.settings" },
  ];
  return candidates.filter((tab) => has(tab.query)).map((tab) => ({ label: tab.label, hash: tab.hash }));
}

// 页面路径（工单 #303：不用路由名）：项目内的页名与页签一致，
// 请求详情与部门恢复页另有页名，其余没有登记页名的页面写「这个页面」
const PAGE_LABELS: Record<string, string> = {
  overview: "概览",
  materials: "资料",
  observe: "观测",
  "observe-detail": "请求详情",
  settings: "设置",
  recovery: "恢复",
};

function pathLabel(route: Route, projects: ProjectRow[]): string {
  if (route.name === "home" || route.name === "not-found") {
    return "首页";
  }
  if (route.name.startsWith("sys-")) {
    // 模型管理页的路径只显示「模型管理」，不显示在项目名之后（设计说明第 9.1 节）
    return route.name === "sys-models" ? "模型管理" : route.systemPage ?? "系统";
  }
  // 部门页的页名就是部门名，与页签一致（产品、工程、质检）
  const page = route.name === "dept" ? departmentName(route.department) : PAGE_LABELS[route.name] ?? "这个页面";
  const project = projects.find((item) => item.project_id === route.projectId);
  const name = project?.name ?? route.projectId ?? "";
  return `${name} / ${page}`;
}
