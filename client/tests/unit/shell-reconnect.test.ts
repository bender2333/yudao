// 外壳视图在事件流状态切换与服务重启重连期间的保持与恢复（工单 #1781，应用层与接口层 docs/design/app-and-interface.md「页面的同步规则」与「能力清单」）。
// 守护三环里的 R2（接口与页面外壳的同步合同）：连接建立以后，事件流在连接中、已连接、已中断之间切换或重启更新能力清单时，
// 外壳的四个视图保持登记，断连期间保留已读到的项目列表与顶栏路径，服务恢复执行 refreshAll 后送达最新列表并清空错误状态。

import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import react from "@vitejs/plugin-react";
import { createServer, type ViteDevServer } from "vite";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ClientState } from "../../src/renderer/src/contract/client-app";
import type { ViewSync } from "../../src/renderer/src/contract/view-sync";
import type { Route } from "../../src/renderer/src/shell/routing";
import type { DecisionView, ProjectRow, SystemStatus } from "../../src/renderer/src/api/generated/types.gen";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

type ClientAppModule = {
  ClientApp: new (...args: unknown[]) => TestClientApp;
};

type RoutingModule = {
  parseRoute: (hash: string) => Route;
  pathLabel: (route: Route, projects: { project_id: string; name: string }[]) => string;
};

type AppShellModule = {
  isShellConnected: (state: ClientState) => boolean;
  openShellProjects: (
    views: ViewSync,
    includeArchived: boolean,
    onData: (projects: ProjectRow[]) => void,
    onError: (reason: string) => void,
  ) => () => void;
  openShellGlobalViews: (
    views: ViewSync,
    onDecisions: (decisions: DecisionView[], pendingByProject: Record<string, number>) => void,
    onStatus: (status: SystemStatus) => void,
  ) => () => void;
  openShellProjectDecisions: (
    views: ViewSync,
    projectId: string,
    onDecisions: (decisions: DecisionView[]) => void,
  ) => () => void;
};

type TestClientApp = {
  open: (address: string, token?: string) => Promise<void>;
  close: () => void;
  viewSync: ViewSync | null;
  currentCapabilities: { deployment: { boot_id: string } } | null;
};

let server: ViteDevServer;
let clientMod: ClientAppModule;
let routingMod: RoutingModule;
let shellMod: AppShellModule;

before(async () => {
  server = await createServer({
    root: join(clientRoot, "src", "renderer"),
    cacheDir: join(clientRoot, "node_modules", ".vite-shell-reconnect"),
    plugins: [react()],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
  });
  clientMod = (await server.ssrLoadModule("/src/contract/client-app.ts")) as ClientAppModule;
  routingMod = (await server.ssrLoadModule("/src/shell/routing.ts")) as RoutingModule;
  shellMod = (await server.ssrLoadModule("/src/app.tsx")) as AppShellModule;
});

after(async () => {
  await server?.close();
});

function capabilitiesWith(bootId: string) {
  return {
    deployment: { boot_id: bootId, log_id: "log-1", version: "0.2.0", api_version: 1, access: "local" },
    queries: [
      { name: "projects.list", changed_by: ["project_registered"] },
      { name: "decisions.list", changed_by: ["decision_requested"] },
      { name: "system.status", changed_by: [] },
    ],
    commands: [],
    decisions: { event_types: ["decision_requested"], kinds: [] },
    event_types: [],
    overlays: [],
    stream: { live: true, scopes: [] },
  };
}

function projectRow(id: string, name: string): ProjectRow {
  return {
    project_id: id,
    name,
    goal: "做一件事",
    source: "blank",
    pinned: false,
    archived: false,
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
    version: 1,
    work_item_count: 0,
    in_progress_count: 0,
    waiting_count: 0,
    decisions_waiting: 0,
    last_activity_at: "2026-11-14T10:00:00Z",
    active_work_item_id: null,
    current_adoption: null,
    onboarding_status: null,
    interrupted_count: 0,
    waiting_resume_count: 0,
    department_count: 3,
  };
}

function fakeStream() {
  const handle = {
    starts: [] as number[],
    stops: 0,
    position: 10,
    handlers: null as null | {
      onConnected: (info: { reconnected: boolean }) => void;
      onInterrupted: () => void;
    },
    start(after: number) {
      handle.starts.push(after);
    },
    stop() {
      handle.stops += 1;
    },
  };
  return handle;
}

function sameDeps(prev: readonly unknown[] | null, next: readonly unknown[]): boolean {
  if (prev === null || prev.length !== next.length) {
    return false;
  }
  return prev.every((item, index) => Object.is(item, next[index]));
}

function createEffectSlot() {
  let deps: readonly unknown[] | null = null;
  let cleanup: (() => void) | undefined;
  return {
    sync(nextDeps: readonly unknown[], effect: () => (() => void) | void) {
      if (sameDeps(deps, nextDeps)) {
        return;
      }
      cleanup?.();
      deps = nextDeps;
      const nextCleanup = effect();
      cleanup = typeof nextCleanup === "function" ? nextCleanup : undefined;
    },
    dispose() {
      cleanup?.();
      cleanup = undefined;
      deps = null;
    },
  };
}

async function flushMicrotasks(turns = 8): Promise<void> {
  for (let index = 0; index < turns; index += 1) {
    await Promise.resolve();
  }
}

async function waitUntil(predicate: () => boolean, timeoutMs = 2000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    await flushMicrotasks();
    if (predicate()) {
      return;
    }
    if (Date.now() >= deadline) {
      assert.fail("等待异步状态就绪超时");
    }
    await new Promise((resolveTick) => setImmediate(resolveTick));
  }
}

test("连接建立后流状态切换与能力清单更新期间外壳视图保持打开，断连保留项目列表且恢复后更新", async () => {
  const stream = fakeStream();
  let serverDown = false;
  let bootIndex = 0;
  const boots = ["boot-a", "boot-b"];
  let currentProjects: ProjectRow[] = [projectRow("proj_alpha", "阿尔法项目")];
  const queryCounts = new Map<string, number>();
  const closedViews: string[] = [];
  const openedViews: string[] = [];

  let state: ClientState = { kind: "connecting" };
  let projects: ProjectRow[] = [];
  let projectsError: string | null = null;
  let decisions: DecisionView[] = [];
  let projectDecisions: DecisionView[] = [];
  const includeArchived = false;
  const route = routingMod.parseRoute("#/p/proj_alpha/conversation");

  const projectsEffect = createEffectSlot();
  const globalEffect = createEffectSlot();
  const projectDecisionsEffect = createEffectSlot();
  let wrappedViews: ViewSync | null = null;

  let app!: TestClientApp;
  const syncEffects = () => {
    const views = app?.viewSync ?? null;
    if (views !== null && views !== wrappedViews) {
      wrappedViews = views;
      const rawOpen = views.open.bind(views);
      const rawClose = views.close.bind(views);
      views.open = ((viewId: string, ...rest: [ never, never, never ]) => {
        openedViews.push(viewId);
        return rawOpen(viewId, ...rest);
      }) as typeof views.open;
      views.close = (viewId: string) => {
        closedViews.push(viewId);
        rawClose(viewId);
      };
    }
    const connected = shellMod.isShellConnected(state);
    projectsEffect.sync([app, connected, includeArchived], () => {
      if (!connected || !views) {
        return;
      }
      return shellMod.openShellProjects(
        views,
        includeArchived,
        (next) => {
          projects = next;
          projectsError = null;
        },
        (reason) => {
          projects = [];
          projectsError = reason;
        },
      );
    });
    globalEffect.sync([app, connected], () => {
      if (!connected || !views) {
        return;
      }
      return shellMod.openShellGlobalViews(
        views,
        (nextDecisions) => {
          decisions = nextDecisions;
        },
        () => undefined,
      );
    });
    projectDecisionsEffect.sync([app, connected, route.projectId], () => {
      if (!connected || !views || route.projectId === null) {
        projectDecisions = [];
        return;
      }
      return shellMod.openShellProjectDecisions(views, route.projectId, (nextDecisions) => {
        projectDecisions = nextDecisions;
      });
    });
  };

  app = new clientMod.ClientApp(
    async (_client: unknown, name: string) => {
      queryCounts.set(name, (queryCounts.get(name) ?? 0) + 1);
      if (serverDown) {
        throw new TypeError("Failed to fetch");
      }
      if (name === "projects.list") {
        return { position: 12 + bootIndex, data: { projects: currentProjects } };
      }
      if (name === "decisions.list") {
        return { position: 12 + bootIndex, data: { decisions: [] } };
      }
      return { position: 12 + bootIndex, data: { drain: { state: "idle" }, provider: null } };
    },
    {
      onState(next: ClientState) {
        state = next;
        syncEffects();
      },
      onPendingDecisions() {},
    },
    {
      connect: async (address: string) => {
        if (serverDown) {
          throw new TypeError("Failed to fetch");
        }
        const boot = boots[Math.min(bootIndex, boots.length - 1)];
        return { state: "connected", address, capabilities: capabilitiesWith(boot) };
      },
      openStream: (_baseUrl: string, _scope: unknown, handlers: unknown) => {
        stream.handlers = handlers as typeof stream.handlers;
        return stream;
      },
    },
  );

  await app.open("http://127.0.0.1:9");
  await waitUntil(() => projects.length === 1);
  assert.deepEqual(openedViews, [
    "shell.projects",
    "shell.decisions",
    "shell.status",
    "shell.project.decisions",
  ]);
  assert.deepEqual(projects.map((row) => row.name), ["阿尔法项目"]);
  assert.equal(projectsError, null);
  assert.equal(routingMod.pathLabel(route, projects), "阿尔法项目 / 对话");
  assert.equal(queryCounts.get("projects.list"), 1);

  openedViews.length = 0;
  closedViews.length = 0;

  stream.handlers!.onConnected({ reconnected: false });
  await flushMicrotasks();
  assert.deepEqual(openedViews, []);
  assert.deepEqual(closedViews, []);
  assert.equal(queryCounts.get("projects.list"), 1);

  serverDown = true;
  stream.handlers!.onInterrupted();
  await flushMicrotasks();
  assert.deepEqual(openedViews, []);
  assert.deepEqual(closedViews, []);
  assert.deepEqual(projects.map((row) => row.name), ["阿尔法项目"]);
  assert.equal(projectsError, null);
  assert.equal(routingMod.pathLabel(route, projects), "阿尔法项目 / 对话");

  serverDown = false;
  bootIndex = 1;
  currentProjects = [projectRow("proj_alpha", "阿尔法项目"), projectRow("proj_beta", "贝塔项目")];
  stream.handlers!.onConnected({ reconnected: true });
  await waitUntil(() => projects.length === 2);

  assert.equal(app.currentCapabilities!.deployment.boot_id, "boot-b");
  assert.deepEqual(openedViews, []);
  assert.deepEqual(closedViews, []);
  assert.deepEqual(projects.map((row) => row.name), ["阿尔法项目", "贝塔项目"]);
  assert.equal(projectsError, null);
  assert.equal(routingMod.pathLabel(route, projects), "阿尔法项目 / 对话");
  assert.deepEqual(decisions, []);
  assert.deepEqual(projectDecisions, []);

  projectsEffect.dispose();
  globalEffect.dispose();
  projectDecisionsEffect.dispose();
  app.close();
});

test("外壳项目列表读取失败记录错误原因后，服务恢复执行 refreshAll 送达新列表并清空错误", async () => {
  let failProjects = true;
  const stream = fakeStream();
  let projects: ProjectRow[] = [];
  let projectsError: string | null = null;

  const app = new clientMod.ClientApp(
    async (_client: unknown, name: string) => {
      if (name === "projects.list") {
        if (failProjects) {
          throw new TypeError("Failed to fetch");
        }
        return { position: 25, data: { projects: [projectRow("proj_alpha", "阿尔法项目")] } };
      }
      return { position: 25, data: { decisions: [] } };
    },
    { onState() {}, onPendingDecisions() {} },
    {
      connect: async (address: string) => ({
        state: "connected",
        address,
        capabilities: capabilitiesWith("boot-a"),
      }),
      openStream: (_baseUrl: string, _scope: unknown, handlers: unknown) => {
        stream.handlers = handlers as typeof stream.handlers;
        return stream;
      },
    },
  );

  await app.open("http://127.0.0.1:9");
  const dispose = shellMod.openShellProjects(
    app.viewSync!,
    false,
    (next) => {
      projects = next;
      projectsError = null;
    },
    (reason) => {
      projects = [];
      projectsError = reason;
    },
  );
  await waitUntil(() => projectsError !== null);
  assert.deepEqual(projects.map((row) => row.name), []);
  assert.equal(projectsError, "Failed to fetch");

  failProjects = false;
  await app.viewSync!.refreshAll();
  assert.deepEqual(projects.map((row) => row.name), ["阿尔法项目"]);
  assert.equal(projectsError, null);

  dispose();
  app.close();
});
