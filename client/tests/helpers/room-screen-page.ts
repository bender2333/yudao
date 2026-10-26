// 部门房间组件的部门切换测试支撑（工单 #300）：在渲染进程的页面上真实挂载 RoomScreen 组件，
// 依次把各部门的查询结果交给它，从页面读回错误提示与画面当前的部门。
//
// 房间画面用 PixiJS 画，需要浏览器；模块由 Vite 的模块服务器提供，与房间回放同一方式。
// 不注入替身：组件用的应用层对象是 client-app.ts 里真实的 ClientApp，它自己收下组件的三个订阅。

import { createServer } from "vite";
import { chromium } from "@playwright/test";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadRoomRecordings } from "./room-replay.ts";
import type { DepartmentWorkspaceResult } from "../../src/renderer/src/api/generated/types.gen.ts";
import type { RoomTestHooks } from "../../src/renderer/src/views/project/room-screen.tsx";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

// 部门工作间的查询结果：录下的数据只带房间模型，房间组件只读 department 与 room 两个字段。
// 房间模型在录制里是驱动收到的那份完整数据，与查询结果里的房间数据同一个类型
export type RoomWorkspaceFixture = DepartmentWorkspaceResult;

/** 页面读取入口的宿主窗口类型（组件把画面状态挂在 window 上）。 */
type RoomWindow = Window & { __roomViewForTest?: RoomTestHooks };

/** 一个部门上的房间状态：错误提示、画面当前的部门与画面里的角色。 */
export interface RoomTabState {
  department: string;
  errorText: string | null;
  viewDepartment: string | null;
  roleIds: string[];
}

/** 部门切换的观测结果：每一步读回的状态与页面本身的报错。 */
export interface RoomSwitchReport {
  states: RoomTabState[];
  pageErrors: string[];
}

/** 录下的部门房间数据里取这个部门的房间查询结果（真实录下的数据）。 */
export function roomWorkspaceFixture(department: string): RoomWorkspaceFixture {
  const recording = loadRoomRecordings();
  const scenario = recording.scenarios.find((s) => s.department === department);
  const room = scenario?.ops.find((op) => op.op === "setModel")?.arg;
  if (!scenario || !room) {
    throw new Error(`录下的场景里没有部门 ${department} 的房间模型`);
  }
  // 录下的是驱动收到的房间模型，与查询结果里的房间数据同一个类型；查询结果的其余字段
  // 房间组件不读，这里不填
  return { department, room } as unknown as DepartmentWorkspaceResult;
}

/** 数据从空到有的存活观测：挂载计数与画面容器节点在前后两步是否同一个 DOM 节点。 */
export interface RoomSurvivalReport {
  /** 每次 root.render 之后舞台里活着的房间画面容器个数。 */
  mountCounts: number[];
  /** 每次 root.render 之后舞台容器个数（应恒为 1）。 */
  stageCounts: number[];
  /** 每一步读到的舞台与画面容器节点是否与上一步是同一个（用节点标记判断）。 */
  sameHost: boolean;
  /** 画面加载失败提示。 */
  errorText: string | null;
  pageErrors: string[];
}

/** 在页面里运行的驱动：依次把各部门的查询结果交给房间组件，每步等画面建立并读回状态。 */
async function driver(input: { steps: { department: string; data: RoomWorkspaceFixture | null }[] }): Promise<{ states: RoomTabState[] }> {
  // 这段代码经字符串化以后在浏览器里求值，模块只能动态引入（房间回放同样做法）
  const React = (await import(/* @vite-ignore */ "/@id/react" as string)).default as typeof import("react");
  const ReactDOMClient = (await import(/* @vite-ignore */ "/@id/react-dom/client" as string)).default as typeof import("react-dom/client");
  const { RoomScreen } = await import(/* @vite-ignore */ "/src/views/project/room-screen.tsx" as string) as typeof import("../../src/renderer/src/views/project/room-screen.tsx");
  const { ClientApp } = await import(/* @vite-ignore */ "/src/contract/client-app.ts" as string) as typeof import("../../src/renderer/src/contract/client-app.ts");
  // 真实的 ClientApp：它自己收下组件的订阅；这个测试不发命令也不查询
  const app = new ClientApp(async () => {
    throw new Error("部门切换的单元测试不查询");
  }, { onState() {}, onPendingDecisions() {} });
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:480px;height:240px;z-index:9999";
  document.body.appendChild(host);
  const root = ReactDOMClient.createRoot(host);
  const readState = (department: string): RoomTabState => {
    const node = host.querySelector(".pixel-canvas-error");
    const hooks = (window as RoomWindow).__roomViewForTest;
    const state = hooks ? hooks.state() : null;
    return {
      department,
      errorText: node === null ? null : node.textContent,
      viewDepartment: state === null ? null : state.department,
      roleIds: state === null ? [] : state.characters.map((c) => c.id),
    };
  };
  // 等画面稳定：画面建立失败会渲染错误提示；画面建立以后读取入口挂上，
  // 这一步给了查询结果时还要等画面里出现该部门的角色（模型是渲染以后才应用到画面）
  const settle = async (department: string, roleIds: string[]): Promise<void> => {
    for (let i = 0; i < 400; i++) {
      if (host.querySelector(".pixel-canvas-error") !== null) return;
      const hooks = (window as RoomWindow).__roomViewForTest;
      if (hooks !== undefined && hooks.state().department === department) {
        const present = new Set(hooks.state().characters.map((c) => c.id));
        if (roleIds.every((id) => present.has(id))) return;
      }
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 25);
      await promise;
    }
  };
  const states: RoomTabState[] = [];
  for (const step of input.steps) {
    const roleIds = step.data === null ? [] : step.data.room.roles.map((r) => r.id);
    root.render(React.createElement(RoomScreen, { app, department: step.department, data: step.data }));
    await settle(step.department, roleIds);
    states.push(readState(step.department));
  }
  root.unmount();
  host.remove();
  return { states };
}

/** 起一个渲染进程的模块服务器，把一份部门切换的步骤送进房间组件，返回每一步读回的状态。 */
export async function runRoomSwitch(steps: { department: string; data: RoomWorkspaceFixture | null }[]): Promise<RoomSwitchReport> {
  const server = await createServer({
    root: join(clientRoot, "src", "renderer"),
    // 单元测试文件之间是并行运行的：房间回放等同样的浏览器测试也起一个模块服务器，
    // 依赖缓存目录与它们分开，避免两个服务器同时改写同一份缓存
    cacheDir: join(clientRoot, "node_modules", ".vite-room-screen"),
    plugins: [],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
    // 页面里要挂 React，依赖先优化好，避免打开页面以后再重新加载一次
    optimizeDeps: { include: ["react", "react/jsx-runtime", "react-dom/client"] },
  });
  await server.listen();
  const address = server.resolvedUrls?.local[0];
  if (!address) throw new Error("渲染进程的模块服务器没有给出地址");
  const browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
  const pageErrors: string[] = [];
  try {
    const page = await browser.newPage();
    page.on("pageerror", (e) => pageErrors.push(e.message));
    // 一张空白页面：客户端的入口会连接服务，与组件的部门切换无关
    await page.route(address + "room-screen.html", (route) => route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><html><head><meta charset=\"utf-8\"></head><body></body></html>",
    }));
    await page.goto(address + "room-screen.html");
    // 驱动的源码与步骤一次送进页面（page.evaluate 只收一个参数；驱动经字符串化以后在页面里求值）
    const result = await page.evaluate(async (input: { fnSource: string; steps: typeof steps }) => {
      try {
        const fn = (0, eval)(`(${input.fnSource})`) as (i: { steps: typeof steps }) => Promise<{ states: RoomTabState[] }>;
        return { ok: await fn({ steps: input.steps }) };
      } catch (e) {
        return { failed: String((e as Error)?.stack ?? e) };
      }
    }, { fnSource: driver.toString(), steps });
    if ("failed" in result) {
      throw new Error(`驱动失败：${String(result.failed)}`);
    }
    return { states: result.ok.states, pageErrors };
  } finally {
    await browser.close();
    await server.close();
  }
}

// 数据从空到有的存活驱动（工单 #381）：挂载 department.tsx 里真实的 RoomSection，
// 同一个 React root 先后传入空数据与真实录下的数据。每一步数舞台里活着的房间画面容器
// 个数（挂载计数），并给舞台容器与第一个看到的画面容器打标记，
// 读回数据到达前后是否还是同一个 DOM 节点。
async function survivalDriver(input: { department: string; datas: (RoomWorkspaceFixture | null)[] }): Promise<{ mountCounts: number[]; stageCounts: number[]; sameHost: boolean; errorText: string | null }> {
  const React = (await import(/* @vite-ignore */ "/@id/react" as string)).default as typeof import("react");
  const ReactDOMClient = (await import(/* @vite-ignore */ "/@id/react-dom/client" as string)).default as typeof import("react-dom/client");
  const { RoomSection } = await import(/* @vite-ignore */ "/src/views/project/department.tsx" as string) as typeof import("../../src/renderer/src/views/project/department.tsx");
  const { ClientApp } = await import(/* @vite-ignore */ "/src/contract/client-app.ts" as string) as typeof import("../../src/renderer/src/contract/client-app.ts");
  const app = new ClientApp(async () => {
    throw new Error("存活测试不查询");
  }, { onState() {}, onPendingDecisions() {} });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = ReactDOMClient.createRoot(host);
  const department = input.department;
  const mountCounts: number[] = [];
  const stageCounts: number[] = [];
  let sceneMark: string | null = null;
  let stageMark: string | null = null;
  let sameHost = true;
  let errorText: string | null = null;
  for (const data of input.datas) {
    root.render(React.createElement(RoomSection, { app, department, data }));
    // 等一帧与效果提交：画面建立或数据应用完成
    for (let i = 0; i < 80; i++) {
      const canvases = host.querySelectorAll(".y10-ws-stage .y10-scene");
      if (canvases.length > 0) break;
      await new Promise<void>((resolve) => setTimeout(resolve, 25));
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 300));
    const stages = host.querySelectorAll(".y10-ws-stage");
    const canvases = host.querySelectorAll(".y10-ws-stage .y10-scene");
    stageCounts.push(stages.length);
    mountCounts.push(canvases.length);
    const stage = stages[0] as HTMLElement | undefined;
    const first = canvases[0] as HTMLElement | undefined;
    const err = host.querySelector(".pixel-canvas-error");
    if (err !== null) errorText = err.textContent;
    if (stage !== undefined) {
      if (stageMark === null) {
        stageMark = "room-survival-stage";
        stage.dataset.survival = stageMark;
      } else {
        sameHost = sameHost && stage.dataset.survival === stageMark;
      }
    } else {
      sameHost = false;
    }
    if (first !== undefined) {
      if (sceneMark === null) {
        sceneMark = "room-survival-mark";
        first.dataset.survival = sceneMark;
      } else {
        sameHost = sameHost && first.dataset.survival === sceneMark;
      }
    } else {
      sameHost = false;
    }
  }
  root.unmount();
  host.remove();
  return { mountCounts, stageCounts, sameHost, errorText };
}

/** 在渲染进程页面运行存活驱动：挂载真实的 RoomSection，先空数据再真实数据，读回挂载计数与节点身份。 */
export async function runRoomSurvival(department: string, datas: (RoomWorkspaceFixture | null)[]): Promise<RoomSurvivalReport> {
  const server = await createServer({
    root: join(clientRoot, "src", "renderer"),
    cacheDir: join(clientRoot, "node_modules", ".vite-room-survival"),
    plugins: [],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
    optimizeDeps: { include: ["react", "react/jsx-runtime", "react-dom/client"] },
  });
  await server.listen();
  const address = server.resolvedUrls?.local[0];
  if (!address) throw new Error("渲染进程的模块服务器没有给出地址");
  const browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
  const pageErrors: string[] = [];
  try {
    const page = await browser.newPage();
    page.on("pageerror", (e) => pageErrors.push(e.message));
    await page.route(address + "room-survival.html", (route) => route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><html><head><meta charset=\"utf-8\"></head><body></body></html>",
    }));
    await page.goto(address + "room-survival.html");
    const result = await page.evaluate(async (input: { fnSource: string; department: string; datas: typeof datas }) => {
      try {
        const fn = (0, eval)(`(${input.fnSource})`) as (i: { department: string; datas: typeof datas }) => Promise<{ mountCounts: number[]; stageCounts: number[]; sameHost: boolean; errorText: string | null }>;
        return { ok: await fn({ department: input.department, datas: input.datas }) };
      } catch (e) {
        return { failed: String((e as Error)?.stack ?? e) };
      }
    }, { fnSource: survivalDriver.toString(), department, datas });
    if ("failed" in result) {
      throw new Error(`驱动失败：${String(result.failed)}`);
    }
    return { mountCounts: result.ok.mountCounts, stageCounts: result.ok.stageCounts, sameHost: result.ok.sameHost, errorText: result.ok.errorText, pageErrors };
  } finally {
    await browser.close();
    await server.close();
  }
}
