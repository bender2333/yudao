// 渲染进程的应用：连接状态、路由、外壳与页面（原型 v8 设计说明第 3 节，工单 #79）。
// 本工单建立外壳、连接设置、接口版本核对、事件流同步与视图同步；首页页面（#175）、
// 项目页面（#80）与像素画面（#176 至 #180）由各自的工单实现，这里只留出它们的位置。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Capabilities, DecisionList, ProjectList, ProjectRow, SystemStatus } from "./api/generated/types.gen";
import { ClientApp, type ClientState } from "./contract/client-app";
import { callQuery } from "./contract/invoke";
import type { ConnectionSettings } from "./contract/settings";
import { defaultSettings } from "./contract/settings";
import { Sidebar } from "./shell/sidebar";
import { Tabbar, Topbar, type Tab } from "./shell/topbar";
import { parseRoute, paths, type Route } from "./shell/routing";
import { ConnectPage, UpdatePage } from "./views/connect";
import { PlaceholderPage } from "./views/placeholder";

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

  // 启动：读取保存的连接设置并连接
  useEffect(() => {
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
  }, [app]);

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
  return (
    <div className={`app${drawerOpen ? " drawer-open" : ""}`}>
      <Sidebar
        capabilities={capabilities}
        projects={projects}
        activeProjectId={route.projectId}
        activeName={route.name}
        pendingByProject={pendingByProject}
        onNavigate={navigate}
      />
      <div className="main">
        <Topbar
          path={pathLabel(route, projects)}
          pending={pending}
          streamConnected={state.streamConnected}
          onPendingClick={() => navigate(paths.home())}
          onToggleDrawer={() => setDrawerOpen((open) => !open)}
        />
        <Tabbar tabs={tabs} activeHash={window.location.hash} onNavigate={navigate} />
        <main className="content">
          <PlaceholderPage route={route} systemStatus={systemStatus} />
        </main>
      </div>
    </div>
  );
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
    return route.systemPage ?? "系统";
  }
  const project = projects.find((item) => item.project_id === route.projectId);
  const name = project?.name ?? route.projectId ?? "";
  return `${name} / ${route.name}`;
}
