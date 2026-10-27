// 端到端测试的公共装置：启动真实后端（FakeAdapter 驱动的服务）与 Playwright Chromium 页面。
// 后端同时提供构建好的页面文件（client/out/renderer），页面从后端地址打开，接口与页面同一来源；
// 视口尺寸由测试设置（1440×900 与 1920×1080）。
// 后端使用临时目录，不写入仓库（工单验收：模型回答由 FakeAdapter 给出，不使用 mock）。

import { chromium, type Browser, type Page } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export type Backend = {
  port: number;
  address: string;
  dataDir: string;
  // 局域网访问方式（工单 #348）下的局域网地址；本机访问方式时为空串
  lanAddress: string;
  // 局域网访问方式下后端建立的访问令牌明文；本机访问方式时为空串。页面在令牌表单里填写它
  token: string;
  /** 部门房间的端到端验收预置的项目标识（--room 模式）；其他模式为空。 */
  roomProject: string | null;
  // 建档脚本（工单 #137）与起始文件夹脚本（工单 #323）下后端建好的真实目录：
  // 前者填进接入对话框的源目录路径，后者填进从想法新建的起始文件夹
  sourceDir: string | null;
  stop: () => Promise<void>;
};

export type ClientApp = {
  browser: Browser;
  page: Page;
  close: () => Promise<void>;
};

// 浏览器上下文的设置
export type PageOptions = {
  colorScheme?: "light" | "dark";
  // 浏览器缩放（工单 #377）：deviceScaleFactor 大于 1 时按倍率放大，用于核对缩放后没有横向滚动条
  deviceScaleFactor?: number;
  // 系统通知的端到端核对（工单 #375）：permissions 授予浏览器通知权限；
  // initScript 在页面装载前包装 window.Notification 以记录调用（包装仍然调用真实构造函数）
  permissions?: string[];
  initScript?: () => void;
  // 页面装载前拦截请求（工单 #728）：把某个接口拦成失败，走的是与真实失败同一条路径。
  // 在 page.goto 之前注册，否则页面已经连上服务、请求已经发出。
  intercept?: (page: Page) => Promise<void>;
};

export const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

// 端到端用例打开的是后端提供的页面构建产物 client/out/renderer。它不存在或比渲染进程源码旧时，
// 用例对着旧界面报错，看不出界面已经改过（工单 #303 的执行者、#177 的验证都遇到）：
// 此时就地报错并写明先构建
function assertPagesBuildIsCurrent(): void {
  const entry = join(repoRoot, "client", "out", "renderer", "index.html");
  let built: number;
  try {
    built = statSync(entry).mtimeMs;
  } catch {
    throw new Error(`没有页面构建产物 ${entry}，先运行 npm run build:pages 再运行端到端用例`);
  }
  if (built < newestModification(join(repoRoot, "client", "src", "renderer"))) {
    throw new Error(`页面构建产物 ${entry} 比 client/src/renderer 旧，先运行 npm run build:pages 再运行端到端用例`);
  }
}

function newestModification(directory: string): number {
  let newest = 0;
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    newest = Math.max(newest,
                      entry.isDirectory() ? newestModification(path) : statSync(path).mtimeMs);
  }
  return newest;
}

// 启动真实后端：脚本在 client/tests/e2e/backend.py 中，用仓库项目的 Python 环境运行；
// 后端提供 client/out/renderer 里的页面文件。apiVersion 让服务报告一个不同的接口版本，
// releaseVersion 让服务一直报告一个与页面构建时不同的发布版本，releaseVersionOnce 只在第一次
// 读取能力清单时报告（页面重新加载以后读到服务自己的版本，一次重新加载因此可观察），
// port 固定端口（断线恢复的用例在同一端口再起一次）；room 用流式慢模型跑
// 一个项目，供部门房间在请求进行中观察（工单 #177）
export async function startBackend(
  options: { apiVersion?: number; releaseVersion?: string; releaseVersionOnce?: string; room?: boolean; admitAndBind?: boolean; port?: number; script?: "default" | "onboarding" | "initial" | "waiting" | "kernel" | "pending"; rejectUpstream?: boolean; dataDir?: string; bindDepartments?: string[]; catalogDriven?: boolean; tokenName?: string } = {},
): Promise<Backend> {
  const script = ["client/tests/e2e/backend.py", "--port", String(options.port ?? 0)];
  if (options.apiVersion !== undefined) {
    script.push("--api-version", String(options.apiVersion));
  }
  // 页面与服务同出一个发布：报告一个与页面构建时不同的版本，页面据此自动重新加载（工单 #374）
  if (options.releaseVersion !== undefined) {
    script.push("--release-version", options.releaseVersion);
  }
  if (options.releaseVersionOnce !== undefined) {
    script.push("--release-version-once", options.releaseVersionOnce);
  }
  // 固定数据目录：断线以后用同一端口与数据目录再起一次服务（设计说明第 3.4 节的恢复）
  if (options.dataDir !== undefined) {
    script.push("--data-dir", options.dataDir);
  }
  if (options.room) {
    script.push("--room");
  }
  if (options.admitAndBind === true) {
    script.push("--admit-and-bind");
  }
  // 工单 #319 第 6 项：只给这些部门默认绑定模型，其余部门保持「未设置」；
  // 空数组表示一个部门都不绑定，用例据此核对缺少部门默认时新事项被拒绝的提示
  if (options.bindDepartments !== undefined) {
    script.push("--bind-departments", options.bindDepartments.join(","));
  }
  // 工单 #319 第 6 项：按工厂装配系统，让就绪检查走目录里的部门默认而不是 FakeAdapter 的可用性
  if (options.catalogDriven === true) {
    script.push("--catalog-driven");
  }
  if (options.script !== undefined) {
    script.push("--script", options.script);
  }
  if (options.rejectUpstream === true) {
    script.push("--reject-upstream");
  }
  // 局域网访问方式（工单 #348）：以 lan 方式起服务，后端建立一个访问令牌并把明文报回来
  if (options.tokenName !== undefined) {
    script.push("--token-name", options.tokenName);
  }
  const child = spawn("uv", ["run", "python", ...script], {
    cwd: repoRoot,
    stdio: ["pipe", "pipe", "pipe"],
    shell: true,
  });
  const line = await readFirstLine(child);
  const parsed = JSON.parse(line) as {
    port: number;
    data_dir: string;
    room_project?: string | null;
    source_dir?: string | null;
    access?: string;
    address?: string | null;
    token?: string | null;
  };
  return {
    port: parsed.port,
    address: `http://127.0.0.1:${parsed.port}`,
    lanAddress: parsed.address ?? "",
    token: parsed.token ?? "",
    dataDir: parsed.data_dir,
    roomProject: parsed.room_project ?? null,
    sourceDir: parsed.source_dir ?? null,
    stop: () => stopProcess(child),
  };
}

function readFirstLine(child: ChildProcessWithoutNullStreams): Promise<string> {
  const { promise, resolve, reject } = Promise.withResolvers<string>();
  let buffer = "";
  child.stdout.on("data", (chunk: Buffer) => {
    buffer += chunk.toString("utf8");
    const newline = buffer.indexOf("\n");
    if (newline >= 0) {
      resolve(buffer.slice(0, newline).trim());
    }
  });
  child.on("error", reject);
  child.on("exit", (code) => reject(new Error(`后端提前退出，状态码 ${code}`)));
  return promise;
}

async function stopProcess(child: ChildProcessWithoutNullStreams): Promise<void> {
  const exited = new Promise<void>((resolve) => {
    child.on("exit", () => resolve());
    setTimeout(() => {
      child.kill();
      resolve();
    }, 3000);
  });
  child.stdin.end();
  await exited;
}

// 打开页面：启动 Chromium，按给定视口与配色新建浏览器上下文，从后端地址打开页面。
// 每个客户端一个浏览器进程，用例之间不共享存储（草稿等 localStorage 数据互不影响）
export async function startClient(
  backend: Backend,
  size: { width: number; height: number },
  options: PageOptions = {},
): Promise<ClientApp> {
  assertPagesBuildIsCurrent();
  return openPage(`${backend.address}/`, size, options);
}

// 打开任意地址的页面（像素用例打开 Vite 开发服务器）；关闭时连同浏览器一起结束
export async function openPage(
  url: string,
  size: { width: number; height: number },
  options: PageOptions = {},
): Promise<ClientApp> {
  // 授予浏览器权限的用例用 Chromium 的新无头模式（channel: "chromium"）：旧的无头模式里
  // Notification.permission 恒为 denied，grantPermissions 改不了它，通知的用例无法核对（工单 #375）
  const browser = await chromium.launch(options.permissions === undefined ? {} : { channel: "chromium" });
  const context = await browser.newContext({
    viewport: size,
    colorScheme: options.colorScheme ?? "light",
    deviceScaleFactor: options.deviceScaleFactor ?? 1,
  });
  if (options.initScript !== undefined) {
    await context.addInitScript(options.initScript);
  }
  if (options.permissions !== undefined) {
    await context.grantPermissions(options.permissions, { origin: new URL(url).origin });
  }
  const page = await context.newPage();
  if (options.intercept !== undefined) {
    await options.intercept(page);
  }
  await page.goto(url);
  await page.waitForLoadState("domcontentloaded");
  // 重复调用时不再动作（用例的收尾写在 finally 里）
  let closed = false;
  return {
    browser,
    page,
    close: async () => {
      if (closed) {
        return;
      }
      closed = true;
      await browser.close();
    },
  };
}

// 收集页面的控制台错误；工单要求控制台错误为零
export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}
