// 页面的应用：连接状态、路由、外壳与页面（原型 v8 设计说明第 3 节，工单 #79 与 #80）。
// 页面由 Yudao 服务提供，接口地址就是页面自己的来源，页面内的导航写在地址 # 之后
// （网页界面的提供与发布设计说明第 5.1 节）。

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Capabilities, DecisionList, DecisionView, EventObject, ProjectList, ProjectOverviewResult, ProjectRow, SystemStatus } from "./api/generated/types.gen";
import { rememberToken, storedToken } from "./contract/access-token";
import { ClientApp, type ClientState } from "./contract/client-app";
import { callQuery } from "./contract/invoke";
import { SystemNotifier, noticeForEvent, pageTitle, type NoticeNames } from "./shell/notifications";
import { Sidebar } from "./shell/sidebar";
import { Tabbar, Topbar, type Tab } from "./shell/topbar";
import { parseRoute, paths, type Route } from "./shell/routing";
import { HomePage } from "./views/home/page";
import { ModelManagementPage } from "./views/models/page";
import { PlaceholderPage } from "./views/placeholder";
import { MachinesPage } from "./views/system/machines";
import { ReservedPage } from "./views/system/reserved";
import { RuntimePage } from "./views/system/runtime";
import { ToolsPage } from "./views/system/tools";
import { DepartmentPage } from "./views/project/department";
import { MaterialsPage } from "./views/project/materials";
import { ObserveDetailPage, ObservePage } from "./views/project/observe";
import { OverviewPage } from "./views/project/overview";
import { RecoveryPage } from "./views/project/recovery";
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
  // 局域网访问方式的访问令牌（第 6.3 节）：在这个浏览器里保存，刷新以后不用再次填写
  const [token, setToken] = useState<string>(() => storedToken());
  // 系统通知点击后要打开的决定卡片（工单 #375，设计说明第 5.3 节）
  const [targetDecision, setTargetDecision] = useState<string | null>(null);

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
    void app.open(window.location.origin, token);
    return () => app.close();
  }, [app, galleryOnly, token]);

  // 用户在页面上填写令牌：先按它连接，服务接受以后才写进这个浏览器（第 6.3 节）。
  // 被拒绝的令牌不保存，否则刷新以后浏览器里留着服务已经拒绝的令牌
  const submitToken = useCallback((value: string) => {
    setToken(value.trim());
  }, []);

  // 服务接受以后才保存：刷新页面不用再次填写，令牌也不进入查询参数
  useEffect(() => {
    if (state.kind === "connected" && token !== "") {
      rememberToken(token);
    }
  }, [state.kind, token]);

  // 路由：监听 hash 变化
  useEffect(() => {
    const onHash = () => {
      setRoute(parseRoute(window.location.hash));
      setDrawerOpen(false);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  // 抽屉打开与否写 body.is-drawer-open：窄屏时左侧栏由原型样式挪进抽屉，遮罩也由它控制
  useEffect(() => {
    document.body.classList.toggle("is-drawer-open", drawerOpen);
    return () => {
      document.body.classList.remove("is-drawer-open");
    };
  }, [drawerOpen]);
  // 连接断开时窗口整体变灰（工单 #296）：原型样式按 body.is-disconnected 给 .y10-app 加灰度，
  // 数据保留最后一次的
  const disconnected = state.kind === "connected" && state.stream.kind === "interrupted";
  useEffect(() => {
    document.body.classList.toggle("is-disconnected", disconnected);
    return () => {
      document.body.classList.remove("is-disconnected");
    };
  }, [disconnected]);
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

  // 系统通知与标签页标题（工单 #375，网页界面的提供与发布设计说明第 5.3 节）：
  // 页面打开期间由不按项目筛选的事件流连接给出决定请求与等待模型服务（提醒只依据事件流与查询，
  // 不另设通知接口，应用层与接口层设计说明第 5.7 节）
  const notifier = useMemo(() => new SystemNotifier(), []);
  // 标签页的标题：待决定的数量，没有待决定的事时不显示数字（标题的基础部分是页面自己的标题）
  const baseTitle = useRef(document.title);
  useEffect(() => {
    document.title = pageTitle(pending, baseTitle.current);
  }, [pending]);
  // 点击决定请求的通知：回到首页并打开对应的决定卡片
  const openDecision = useCallback((decisionId: string) => {
    window.focus();
    navigate(paths.home());
    setTargetDecision(decisionId);
  }, [navigate]);
  // 通知的正文需要项目名与事项标题：项目名来自 projects.list 或 project.overview，事项标题来自
  // project.overview（与首页的决定卡片同一份解析，views/home/page.tsx 的 useWorkItemTitles）
  // 事件常常先于 projects.list 的重新查询到达，名称还没取到时先取到再发通知
  const namesRef = useRef<NoticeNames>({ projectName: () => "", workItemTitle: () => "" });
  const projectNamesRef = useRef<Map<string, string>>(new Map());
  const itemsRef = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    namesRef.current = {
      projectName: (id) => (id === null ? "" : (projectNamesRef.current.get(id)
        ?? projects.find((row) => row.project_id === id)?.name ?? id)),
      workItemTitle: (id) => (id === null ? "" : (itemsRef.current.get(id) ?? id)),
    };
  }, [projects]);
  useEffect(() => {
    const views = app.viewSync;
    if (!connected || !views) {
      return;
    }
    return app.subscribeEvents((event: EventObject) => {
      const notice = noticeForEvent(event, namesRef.current);
      if (notice === null) {
        return;
      }
      // 名称还没有取到：先取到再发通知，正文写明的是哪个项目、哪件事
      const projectId = event.project_id;
      const workItemId = event.work_item_id;
      const known = (projectId === null || projectNamesRef.current.has(projectId)
        || projects.some((row) => row.project_id === projectId))
        && (workItemId === null || itemsRef.current.has(workItemId));
      if (projectId !== null && workItemId !== null && !known) {
        void app.queryOne<ProjectOverviewResult>("project.overview", { project_id: projectId }).then((snapshot) => {
          projectNamesRef.current.set(projectId, snapshot.data.name);
          for (const item of snapshot.data.work_items) {
            itemsRef.current.set(item.work_item_id, item.title);
          }
          notifier.notify(noticeForEvent(event, namesRef.current) ?? notice, openDecision);
        });
        return;
      }
      notifier.notify(notice, openDecision);
    });
  }, [app, connected, notifier, openDecision]);

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
      <Suspense fallback={<div className="y10-gate gate"><div className="y10-gate-card card"><h1>正在载入图鉴…</h1></div></div>}>
        <LazyGallery />
      </Suspense>
    );
  }
  if (state.kind === "connecting") {
    return <div className="y10-gate gate"><div className="y10-gate-card card"><h1>连接中…</h1></div></div>;
  }
  if (state.kind === "outdated") {
    // 页面与服务出自同一个发布，接口版本不同时页面不能使用这个服务
    return (
      <div className="y10-gate gate"><div className="y10-gate-card card">
        <h1>页面与服务的接口版本不同</h1>
        <p className="error">页面的接口版本是 {state.clientVersion}，服务 {state.serverRelease} 的接口版本是 {state.serverVersion}。重新加载页面以取得同一版本的页面文件。</p>
        <button className="y10-btn primary" type="button" onClick={() => window.location.reload()}>重新加载</button>
      </div></div>
    );
  }
  if (state.kind === "unauthorized") {
    // 局域网访问方式：服务按第 6.3 节要求访问令牌，页面文件不需要令牌，所以这里能打开页面。
    // 用户在这个浏览器里填写一次，令牌随后保存在这个浏览器里
    return <TokenGate onSubmit={submitToken} />;
  }
  if (state.kind === "failed") {
    return (
      <div className="y10-gate gate"><div className="y10-gate-card card">
        <h1>没有连上 Yudao 服务</h1>
        <p className="error">连接失败：{state.message}</p>
        <button className="y10-btn primary" type="button" onClick={() => void app.open(window.location.origin, token)}>重新连接</button>
      </div></div>
    );
  }

  const capabilities = state.capabilities;
  const tabs = buildTabs(route, capabilities);
  const project = projects.find((item) => item.project_id === route.projectId) ?? null;

  return (
    <div className="y10-app app">
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
        <button type="button" className="y10-scrim drawer-scrim" aria-label="关闭左侧栏" onClick={() => setDrawerOpen(false)} />
      ) : null}
      <div className="y10-main main">
        <Topbar
          app={app}
          projectId={route.projectId}
          workItemId={route.workItemId}
          project={project}
          path={pathLabel(route, projects)}
          pending={pending}
          projectDecisions={projectDecisions}
          stream={state.stream}
          onPendingClick={() => navigate(paths.home())}
          onToggleDrawer={() => setDrawerOpen((open) => !open)}
          onNavigate={navigate}
        />
        <Tabbar tabs={tabs} activeHash={window.location.hash} onNavigate={navigate} />
        <main className="y10-content content">
          {route.name === "home" ? (
            <HomePage app={app} onNavigate={navigate} at={route.at} targetDecision={targetDecision} />
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
          ) : route.name === "sys-machines" ? (
            <MachinesPage capabilities={capabilities} />
          ) : route.name === "sys-runtime" ? (
            <RuntimePage app={app} systemStatus={systemStatus} />
          ) : route.name === "sys-tools" ? (
            <ToolsPage capabilities={capabilities} />
          ) : route.name === "sys-reserved" ? (
            <ReservedPage which={route.systemPage} />
          ) : (
            <ProjectRouter app={app} route={route} systemStatus={systemStatus} onNavigate={navigate} />
          )}
        </main>
      </div>
    </div>
  );
}

// 填写访问令牌的表单（应用层与接口层设计说明第 6.3 节）：局域网访问方式下服务对全部接口路径
// 要求 Authorization: Bearer <令牌>，页面文件不需要令牌，因此页面能打开而接口返回 401。
// 令牌由用户在控制主机上用 token create 建立，在这里的浏览器中填写一次并保存在这个浏览器里；
// 输入框用密码类型，页面不回显填过的令牌。
function TokenGate(props: { onSubmit: (token: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="y10-gate"><div className="y10-gate-card">
      <h1>填写访问令牌</h1>
      <p>Yudao 服务以局域网访问方式运行，接口需要访问令牌。在控制主机上用 token create 建立令牌并复制它。</p>
      <form
        className="y10-form y10-gate-form"
        onSubmit={(event) => {
          event.preventDefault();
          const token = value.trim();
          if (token !== "") {
            props.onSubmit(token);
          }
        }}
      >
        <label className="y10-field" htmlFor="access-token">
          <span>访问令牌</span>
          <input
            id="access-token"
            data-testid="access-token"
            className="y10-input"
            type="password"
            autoComplete="off"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </label>
        <div className="y10-row">
          <button className="y10-btn primary" type="submit">连接</button>
        </div>
      </form>
    </div></div>
  );
}

// 项目页面（原型 v8 设计说明第 3.3 节的路径，工单 #80）：按路径分派到具体页面。
// 概览、部门工作间、资料、观测、设置与恢复由本工单实现；未实现的系统页显示占位，写明由哪个工单填入。
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
      return <MaterialsPage app={props.app} route={route} onNavigate={props.onNavigate} />;
    case "observe":
      return <ObservePage app={props.app} route={route} />;
    case "observe-detail":
      return <ObserveDetailPage app={props.app} route={route} />;
    case "settings":
      return <SettingsPage app={props.app} route={route} />;
    case "recovery":
      return <RecoveryPage app={props.app} route={route} onNavigate={props.onNavigate} />;
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
