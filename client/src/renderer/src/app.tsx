// 渲染进程的应用：连接状态、路由、外壳与页面（原型 v8 设计说明第 3 节，工单 #79 与 #80）。
// #79 建立外壳、连接设置、接口版本核对、事件流同步与视图同步；#80 实现项目页面
// （左侧栏、顶栏与项目标签、概览、部门工作间、资料、观测、设置）与页面分派。
// 首页页面（#175）与像素画面（#176 至 #180）由各自的工单实现，这里只留出它们的位置。

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Capabilities, DecisionList, DecisionView, ProjectList, ProjectRow, SystemStatus } from "./api/generated/types.gen";
import type { LocalServiceIssue } from "./desktop";
import { ClientApp, type ClientState } from "./contract/client-app";
import { callQuery } from "./contract/invoke";
import type { ConnectionSettings } from "./contract/settings";
import { defaultSettings, DEFAULT_LOCAL_ADDRESS } from "./contract/settings";
import { Sidebar } from "./shell/sidebar";
import { Tabbar, Topbar, type Tab } from "./shell/topbar";
import { parseRoute, paths, type Route } from "./shell/routing";
import { ConnectPage } from "./views/connect";
import { UpdatePage } from "./views/update";
import { HomePage } from "./views/home/page";
import { SettingsPage as ClientSettingsPage } from "./views/settings";
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
  const appRef = useRef<ClientApp | null>(null);
  const [settings, setSettings] = useState<ConnectionSettings | null>(null);
  const [state, setState] = useState<ClientState>({ kind: "connecting" });
  const [pending, setPending] = useState(0);
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [pendingByProject, setPendingByProject] = useState<Record<string, number>>({});
  const [decisions, setDecisions] = useState<DecisionView[]>([]);
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [loginAtStartup, setLoginAtStartup] = useState(false);
  // 本机服务没有可用的两种情况（设计说明第 4.3 节、工单 #296）：没有找到 yudao 命令时设置页给
  // 安装命令，命令找到了但服务没有起来时给原因与服务日志的位置
  const [localIssue, setLocalIssue] = useState<LocalServiceIssue | null>(null);
  // 系统通知被点击后要定位的决定标识：跳到首页再滚动高亮对应的卡片（设计说明第 5.7 节）
  const [focusDecisionId, setFocusDecisionId] = useState<string | null>(null);

  // 客户端应用：查询经生成的调用发出，事件到达时更新状态与待决定数量
  const app = useMemo(() => {
    const instance = new ClientApp(callQuery, {
      onState: (next) => setState(next),
      onPendingDecisions: (count) => {
        setPending(count);
        void window.yudao?.setTrayCount(count);
      },
      // 出现新的决定请求时发出系统通知（设计说明第 5.7 节）；通知带决定标识，点击时定位到
      // 首页的对应决定卡片（工单 #296）。窗口关闭时事件流仍在，通知照常发出
      onEvent: (event) => {
        if (event.type === "decision_requested") {
          void window.yudao?.notify("Yudao：有新的决定请求", event.label, event.event_id);
        }
      },
    });
    appRef.current = instance;
    return instance;
  }, []);

  // 图鉴只在开发时可用（第 133 行那条分支）：直接开 #/gallery 看画法，不必先连上后端，
  // 也不在控制台留下一次注定失败的连接
  const galleryOnly = import.meta.env.DEV && route.name === "gallery";

  // 启动：读取保存的连接设置并连接。连接设置是「本机」时先让主进程启动本机服务
  // （设计说明第 4.3 节：服务已经运行就直接连接，没有运行就启动它，最多等待 30 秒）
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
      if (stored.kind === "local") {
        const start = await window.yudao?.startLocalService(stored.allowLan);
        if (cancelled) {
          return;
        }
        if (start && start.kind !== "started") {
          // 没有找到 yudao 命令，或者命令找到了但服务 30 秒内没有起来：不尝试连接，设置页
          // 分别给安装命令或原因与服务日志的位置（设计说明第 4.3 节）。只在还停在默认首页时
          // 切到设置页；用户或测试已经打开了别的页面就不抢走他们的导航
          setLocalIssue(start);
          setConnectError(start.kind === "no-command"
            ? "本机没有运行 Yudao 服务，也没有找到 yudao 命令。"
            : "本机没有运行 Yudao 服务。");
          if (parseRoute(window.location.hash).name === "home") {
            window.location.hash = paths.clientSettings();
          }
          return;
        }
        setLocalIssue(null);
      }
      await app.open(stored);
    })();
    return () => {
      cancelled = true;
      app.close();
    };
  }, [app, galleryOnly]);

  // 登录时启动客户端（设计说明第 4.5 节）：以注册表里的实际值为准
  useEffect(() => {
    void (async () => {
      const item = await window.yudao?.getLoginItem();
      if (item) {
        setLoginAtStartup(item.openAtLogin);
      }
    })();
  }, []);

  // 托盘菜单的「停止 Yudao」只在连接本机时出现（设计说明第 4.5 节）
  useEffect(() => {
    void window.yudao?.setConnectedLocal(state.kind === "connected" && state.address === DEFAULT_LOCAL_ADDRESS);
  }, [state]);

  // 路由：监听 hash 变化
  useEffect(() => {
    const onHash = () => {
      setRoute(parseRoute(window.location.hash));
      setDrawerOpen(false);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);


  // 系统通知点击后定位到对应的决定卡片：滚动过去并加高亮标记，等待列表到达以后再试一次
  useEffect(() => {
    if (focusDecisionId === null) {
      return;
    }
    const card = document.getElementById(`decision-${focusDecisionId}`);
    if (card === null) {
      return;
    }
    card.scrollIntoView({ block: "center" });
    // 高亮由样式给出（.decision-card.is-targeted），事件到达重画以后卡片会换掉，标记随之消失
    card.classList.add("is-targeted");
    setFocusDecisionId(null);
  }, [focusDecisionId, decisions]);

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

  // 系统通知被点击：主进程恢复窗口后发出决定标识，跳到首页并定位到对应的决定卡片
  // （设计说明第 5.7 节、工单 #296）
  useEffect(() => {
    const off = window.yudao?.onNotifyClick((decisionId) => {
      if (decisionId === null) {
        return;
      }
      setFocusDecisionId(decisionId);
      navigate(paths.home());
    });
    return () => off?.();
  }, [navigate]);

  const reconnect = useCallback(async () => {
    if (!settings) {
      return;
    }
    setConnectError(null);
    await app.open(settings);
  }, [app, settings]);

  // 连接「本机」时（设计说明第 4.3 节）：先请求服务，没有运行就启动它，最多等待 30 秒。
  // 没有找到 yudao 命令时设置页给安装命令，命令找到了但服务没有起来时给原因与服务日志的位置
  const connectTo = useCallback(
    async (next: ConnectionSettings) => {
      if (next.kind === "local") {
        const start = await window.yudao?.startLocalService(next.allowLan);
        if (start && start.kind !== "started") {
          setLocalIssue(start);
          setSettings(next);
          await window.yudao?.saveSettings(next);
          setConnectError(start.kind === "no-command"
            ? "本机没有安装 Yudao 服务，用设置页里的命令安装以后再连接。"
            : "本机没有运行 Yudao 服务，设置页里写明了原因与服务日志的位置。");
          return;
        }
        setLocalIssue(null);
      }
      setSettings(next);
      await window.yudao?.saveSettings(next);
      await app.open(next);
    },
    [app],
  );

  const onSaveSettings = useCallback(async (next: ConnectionSettings) => {
    setSettings(next);
    await window.yudao?.saveSettings(next);
  }, []);

  // 「允许局域网访问」开关（设计说明第 4.3 节）：保存在客户端设置；改动不影响正在运行的服务，
  // 访问方式与开关不同时设置页显示「重新启动服务后生效」
  const onAllowLan = useCallback(
    async (allowLan: boolean) => {
      const next = { ...(settings ?? defaultSettings()), allowLan };
      setSettings(next);
      await window.yudao?.saveSettings(next);
    },
    [settings],
  );

  // 「重新启动」：访问方式与开关不同时使用；读运行中的事项数（大于 0 时主进程先确认），
  // 用本机停止请求停止服务，再按开关启动（设计说明第 4.3 节）
  const onRestartLocal = useCallback(async () => {
    const allowLan = settings?.allowLan ?? false;
    const result = await window.yudao?.restartLocalService(allowLan);
    if (!result) {
      return;
    }
    if (result.stopped) {
      setConnectError(null);
      await reconnect();
    } else {
      setConnectError(result.message);
    }
  }, [settings, reconnect]);

  const stopLocalService = useCallback(async () => {
    const result = await window.yudao?.stopLocalService();
    if (!result) {
      return;
    }
    if (result.stopped) {
      setLocalIssue(null);
      setConnectError("Yudao 服务已经停止。连接它时客户端会重新启动。");
    } else {
      setConnectError(result.message);
    }
  }, []);

  // 登录时启动客户端（设计说明第 4.5 节）：写入当前用户的启动项；写成功以后再显示为打开
  const onLoginAtStartup = useCallback(async (enabled: boolean) => {
    const result = await window.yudao?.setLoginItem(enabled);
    if (result) {
      setLoginAtStartup(result.openAtLogin);
    }
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
  // 设置页在连接与否都显示：连接「本机」而找不到 yudao 命令时客户端没有连上，
  // 这时安装命令与「重新检测」正是要给用户看的内容（设计说明第 4.3 节）
  // 服务正在运行且访问方式与「允许局域网访问」开关不同（从能力清单的 deployment.access 读出）
  // 时显示「重新启动服务后生效」（设计说明第 4.3 节）
  const localConnected = state.kind === "connected" && state.address === DEFAULT_LOCAL_ADDRESS;
  const wantAccess = (settings ?? defaultSettings()).allowLan ? "lan" : "local";
  const lanRestartNeeded = localConnected && state.capabilities.deployment.access !== wantAccess;
  // 没有连接时，设置页单独显示：连接「本机」而找不到 yudao 命令时客户端没有连上，
  // 这时安装命令与「重新检测」正是要给用户看的内容（设计说明第 4.3 节）。
  // 已经连接时设置页显示在外壳里（下面），顶栏的连接状态与托盘入口保持可见
  if (route.name === "client-settings" && state.kind !== "connected") {
    return (
      <ClientSettingsPage
        settings={settings ?? defaultSettings()}
        loginAtStartup={loginAtStartup}
        localConnected={localConnected}
        localIssue={localIssue}
        lanRestartNeeded={lanRestartNeeded}
        onChange={(next) => void onSaveSettings(next)}
        onConnect={(next) => void connectTo(next)}
        onStopLocal={() => void stopLocalService()}
        onRestartLocal={() => void onRestartLocal()}
        onAllowLan={(allowLan) => void onAllowLan(allowLan)}
        onLoginAtStartup={(enabled) => void onLoginAtStartup(enabled)}
        connecting={state.kind === "connecting"}
        error={connectError}
      />
    );
  }
  if (state.kind === "connecting") {
    return <div className="gate"><div className="card"><h1>连接中…</h1></div></div>;
  }
  if (state.kind === "outdated") {
    return (
      <UpdatePage address={state.address} clientVersion={state.clientVersion}
                  serverVersion={state.serverVersion} serverRelease={state.serverRelease} />
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
          ) : route.name === "client-settings" ? (
            <ClientSettingsPage
              settings={settings ?? defaultSettings()}
              loginAtStartup={loginAtStartup}
              localConnected={localConnected}
              localIssue={localIssue}
              lanRestartNeeded={lanRestartNeeded}
              onChange={(next) => void onSaveSettings(next)}
              onConnect={(next) => void connectTo(next)}
              onStopLocal={() => void stopLocalService()}
              onRestartLocal={() => void onRestartLocal()}
              onAllowLan={(allowLan) => void onAllowLan(allowLan)}
              onLoginAtStartup={(enabled) => void onLoginAtStartup(enabled)}
              connecting={false}
              error={connectError}
            />
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
  connect: "连接设置",
  "client-settings": "设置",
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
