// 渲染进程的应用：连接状态、路由、外壳与页面（原型 v8 设计说明第 3 节，工单 #79 与 #80）。
// #79 建立外壳、连接设置、接口版本核对、事件流同步与视图同步；#80 实现项目页面
// （左侧栏、顶栏与项目标签、概览、部门工作间、资料、观测、设置）与页面分派。
// 首页页面（#175）与像素画面（#176 至 #180）由各自的工单实现，这里只留出它们的位置。

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Capabilities, DecisionList, ProjectList, ProjectRow, SystemStatus } from "./api/generated/types.gen";
import { ClientApp, type ClientState } from "./contract/client-app";
import { callQuery } from "./contract/invoke";
import type { ConnectionSettings } from "./contract/settings";
import { defaultSettings } from "./contract/settings";
import { Sidebar } from "./shell/sidebar";
import { Tabbar, Topbar, type Tab } from "./shell/topbar";
import { parseRoute, paths, type Route } from "./shell/routing";
import { ConnectPage, UpdatePage } from "./views/connect";
import { ModelManagementPage } from "./views/models/page";
import { PlaceholderPage } from "./views/placeholder";
import { DepartmentPage } from "./views/project/department";
import { MaterialsPage } from "./views/project/materials";
import { ObserveDetailPage, ObservePage } from "./views/project/observe";
import { OverviewPage } from "./views/project/overview";
import { SettingsPage } from "./views/project/settings";

// 图鉴页只在开发时用到；用动态导入把它挡在正式包之外
const LazyGallery = lazy(async () => {
  const mod = await import("./views/pixel/gallery");
  return { default: mod.GalleryPage };
});

export function App() {
  const appRef = useRef<ClientApp | null>(null);
  const [settings, setSettings] = useState<ConnectionSettings | null>(null);
  const [state, setState] = useState<ClientState>({ kind: "connecting" });
  const [pending, setPending] = useState(0);
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [pendingByProject, setPendingByProject] = useState<Record<string, number>>({});
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

  // 客户端应用：查询经生成的调用发出，事件到达时更新状态与待决定数量
  const app = useMemo(() => {
    const instance = new ClientApp(callQuery, {
      onState: (next) => setState(next),
      onPendingDecisions: (count) => {
        setPending(count);
        void window.yudao?.setTrayCount(count);
      },
      // 出现新的决定请求时发出系统通知（设计说明第 5.7 节）；窗口关闭时事件流仍在，通知照常发出
      onEvent: (event) => {
        if (event.type === "decision_requested") {
          void window.yudao?.notify("Yudao：有新的决定请求", event.label);
        }
      },
    });
    appRef.current = instance;
    return instance;
  }, []);

  // 图鉴只在开发时可用（第 133 行那条分支）：直接开 #/gallery 看画法，不必先连上后端，
  // 也不在控制台留下一次注定失败的连接
  const galleryOnly = import.meta.env.DEV && route.name === "gallery";

  // 启动：读取保存的连接设置并连接
  useEffect(() => {
    if (galleryOnly) {
      return;
    }
    let cancelled = false;
    void (async () => {
      const stored = (await window.yudao?.getSettings()) ?? defaultSettings();
      if (cancelled) {
        return;
      }
      setSettings(stored);
      await app.open(stored);
    })();
    return () => {
      cancelled = true;
      app.close();
    };
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

  const navigate = useCallback((hash: string) => {
    window.location.hash = hash;
  }, []);

  const reconnect = useCallback(async () => {
    if (!settings) {
      return;
    }
    setConnectError(null);
    await app.open(settings);
  }, [app, settings]);

  const onSaveSettings = useCallback(async (next: ConnectionSettings) => {
    setSettings(next);
    await window.yudao?.saveSettings(next);
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
    return (
      <UpdatePage address={state.address} clientVersion={state.clientVersion} serverVersion={state.serverVersion} />
    );
  }
  if (state.kind === "failed") {
    return (
      <ConnectPage
        settings={settings ?? defaultSettings()}
        onChange={(next) => void onSaveSettings(next)}
        onConnect={() => void reconnect()}
        connecting={false}
        error={connectError ?? `连接失败：${state.message}`}
      />
    );
  }
  if (route.name === "connect") {
    return (
      <ConnectPage
        settings={settings ?? defaultSettings()}
        onChange={(next) => void onSaveSettings(next)}
        onConnect={() => void reconnect()}
        connecting={false}
        error={connectError}
      />
    );
  }

  const capabilities = state.capabilities;
  const tabs = buildTabs(route, capabilities);
  const project = projects.find((item) => item.project_id === route.projectId) ?? null;
  return (
    <div className={`app${drawerOpen ? " drawer-open" : ""}`}>
      <Sidebar
        app={app}
        capabilities={capabilities}
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
          streamConnected={state.streamConnected}
          onPendingClick={() => navigate(paths.home())}
          onToggleDrawer={() => setDrawerOpen((open) => !open)}
          onNavigate={navigate}
        />
        <Tabbar tabs={tabs} activeHash={window.location.hash} onNavigate={navigate} />
        <main className="content">
          {route.name === "sys-models" ? (
            <ModelManagementPage
              views={app.viewSync}
              command={(name, body) => app.command(name, body)}
              subscribeEvents={(listener) => app.subscribeEvents(listener)}
              onBack={() => navigate(paths.home())}
            />
          ) : (
            <ProjectRouter app={app} route={route} systemStatus={systemStatus} />
          )}
        </main>
      </div>
    </div>
  );
}

// 项目页面（原型 v8 设计说明第 3.3 节的路径，工单 #80）：按路径分派到具体页面。
// 概览、部门工作间、资料、观测与设置由本工单实现；恢复页（3.1）与系统页由所属工单实现，
// 未实现时显示占位，写明由哪个工单填入。
function ProjectRouter(props: { app: ClientApp; route: Route; systemStatus: SystemStatus | null }) {
  const { route } = props;
  if (route.projectId === null) {
    return <PlaceholderPage route={route} systemStatus={props.systemStatus} />;
  }
  switch (route.name) {
    case "overview":
      return <OverviewPage app={props.app} route={route} />;
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

function pathLabel(route: Route, projects: ProjectRow[]): string {
  if (route.name === "home" || route.name === "not-found") {
    return "首页";
  }
  if (route.name.startsWith("sys-")) {
    // 模型管理页的路径只显示「模型管理」，不显示在项目名之后（设计说明第 9.1 节）
    return route.name === "sys-models" ? "模型管理" : route.systemPage ?? "系统";
  }
  const project = projects.find((item) => item.project_id === route.projectId);
  const name = project?.name ?? route.projectId ?? "";
  return `${name} / ${route.name}`;
}
