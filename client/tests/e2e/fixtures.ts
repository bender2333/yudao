// 端到端测试的公共装置：启动真实后端（FakeAdapter 驱动的服务）与 Electron 客户端。
// 客户端经连接设置连到后端地址；窗口尺寸由测试设置（1440×900 与 390×844）。
// 后端与客户端都使用临时目录，不写入仓库（工单验收：模型回答由 FakeAdapter 给出，不使用 mock）。

import { _electron as electron, type ElectronApplication, type Page } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { mkdtempSync, readdirSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export type Backend = {
  port: number;
  address: string;
  dataDir: string;
  /** 部门房间的端到端验收预置的项目标识（--room 模式）；其他模式为空。 */
  roomProject: string | null;
  // 建档脚本（工单 #137）与起始文件夹脚本（工单 #323）下后端建好的真实目录：
  // 前者填进接入对话框的源目录路径，后者填进从想法新建的起始文件夹
  sourceDir: string | null;
  stop: () => Promise<void>;
};

export type ClientApp = {
  app: ElectronApplication;
  page: Page;
  // 客户端进程结束的 Promise：更新时客户端退出并静默安装，测试用它等旧进程结束
  exited: Promise<void>;
  close: () => Promise<void>;
};

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

// 端到端用例启动的是构建产物 client/out/main/index.js。它不存在或比 client/src 旧时，
// 用例对着旧界面报错，看不出界面已经改过（工单 #303 的执行者、#177 的验证都遇到）：
// 此时就地报错并写明先构建
function assertClientBuildIsCurrent(): void {
  const entry = join(repoRoot, "client", "out", "main", "index.js");
  let built: number;
  try {
    built = statSync(entry).mtimeMs;
  } catch {
    throw new Error(`没有客户端构建产物 ${entry}，先运行 npm run build 再运行端到端用例`);
  }
  if (built < newestModification(join(repoRoot, "client", "src"))) {
    throw new Error(`客户端构建产物 ${entry} 比 client/src 旧，先运行 npm run build 再运行端到端用例`);
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

// 启动真实后端：脚本在 client/tests/e2e/backend.py 中，用仓库项目的 Python 环境运行。
// apiVersion 让服务报告一个不同的接口版本，用于核对更新页；releaseAssets 给出更新源目录
// （工单 #208：服务从它提供 /client-update/latest.yml 与安装程序）；port 固定端口，
// 更新地址里的端口要与它一致，客户端才会从同一个服务下载安装程序；room 用流式慢模型跑
// 一个项目，供部门房间在请求进行中观察（工单 #177）
export async function startBackend(
  options: { apiVersion?: number; room?: boolean; admitAndBind?: boolean; releaseAssets?: string; port?: number; script?: "default" | "onboarding" | "initial"; rejectUpstream?: boolean } = {},
): Promise<Backend> {
  const script = ["client/tests/e2e/backend.py", "--port", String(options.port ?? 0)];
  if (options.apiVersion !== undefined) {
    script.push("--api-version", String(options.apiVersion));
  }
  if (options.room) {
    script.push("--room");
  }
  if (options.releaseAssets !== undefined) {
    script.push("--release-assets", options.releaseAssets);
  }
  if (options.admitAndBind === true) {
    script.push("--admit-and-bind");
  }
  if (options.script !== undefined) {
    script.push("--script", options.script);
  }
  if (options.rejectUpstream === true) {
    script.push("--reject-upstream");
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
  };
  return {
    port: parsed.port,
    address: `http://127.0.0.1:${parsed.port}`,
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

// 启动 Electron 客户端：主进程读取测试环境变量（用户数据目录、后端地址与窗口尺寸），预置连接设置后启动。
// scheme 切换页面的配色（浅色与深色），在窗口内用 emulateMedia 生效
export async function startClient(
  backend: Backend,
  size: { width: number; height: number },
  options: { colorScheme?: "light" | "dark" } = {},
): Promise<ClientApp> {
  return launchClient({
    address: backend.address,
    userData: mkdtempSync(join(tmpdir(), "yudao-client-")),
    size,
    colorScheme: options.colorScheme,
  });
}

// 本机模式的客户端：连接设置是「本机」（地址 http://127.0.0.1:8765），服务没有运行，
// 客户端按设计说明第 4.3 节在 PATH 中找到 yudao 命令并启动 `yudao api`。
// commandBin 给出 yudao 命令所在目录（测试放一个把参数原样交给 backend.py 的替身命令，
// backend.py 的 api 模式与 `yudao api` 同样的方式监听本机默认端口；
// 客户端的找命令、启动后台进程、探测与写日志全部按生产方式运行）。
// serviceRoot 作为 LOCALAPPDATA 传给客户端：它启动的服务的默认数据目录由它算出
// （harness/data_directory.py 的 user_data_root），因此服务的数据目录落在测试目录内
export type LocalLaunch = {
  userData: string;
  serviceRoot: string;
  commandBin: string;
  size: { width: number; height: number };
};

export async function startLocalClient(launch: LocalLaunch): Promise<ClientApp> {
  return launchClient({
    address: null,
    userData: launch.userData,
    size: launch.size,
    env: {
      LOCALAPPDATA: launch.serviceRoot,
      YUDAO_E2E_COMMAND_BIN: launch.commandBin,
    },
  });
}

async function launchClient(options: {
  address: string | null;
  userData: string;
  size: { width: number; height: number };
  colorScheme?: "light" | "dark";
  env?: Record<string, string>;
}): Promise<ClientApp> {
  const local = options.address === null;
  assertClientBuildIsCurrent();
  const app = await electron.launch({
    args: [join(repoRoot, "client", "out", "main", "index.js")],
    cwd: repoRoot,
    env: {
      ...process.env,
      YUDAO_E2E_USER_DATA: options.userData,
      YUDAO_E2E_WIDTH: String(options.size.width),
      YUDAO_E2E_HEIGHT: String(options.size.height),
      // 本机模式不设置 YUDAO_E2E_BACKEND：客户端按连接设置里的「本机」连接
      ...(options.address === null ? {} : { YUDAO_E2E_BACKEND: options.address }),
      ...options.env,
    },
  });
  const child = app.process();
  const exited = new Promise<void>((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve();
    } else {
      child.on("exit", () => resolve());
    }
  });
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  // 重复调用与进程已经退出时不再动作（用例的收尾写在 finally 里）
  let closed = false;
  if (options.colorScheme) {
    await page.emulateMedia({ colorScheme: options.colorScheme });
  }
  return {
    app,
    page,
    exited,
    // 本机模式的收尾走生产的退出入口：托盘「退出客户端」（设计说明第 4.5 节）。
    // 退出以后客户端进程结束而服务仍在运行（ADR-0023），所以只能等进程退出事件：
    // Playwright 的 app.close() 还要等它的启动管道关闭，而本机服务是客户端拉起的独立
    // 后台进程，它继承了这条管道（Playwright 用 --remote-debugging-pipe 驱动 Electron），
    // 服务不停止管道就不闭 —— 打包运行的客户端没有这条管道，这是测试驱动方式带来的
    // 现象，因此测试按用户的方式退出客户端并等进程结束，随后宽容地关闭连接
    close: async () => {
      if (!local) {
        if (closed) {
          return;
        }
        closed = true;
        await app.close();
        return;
      }
      if (closed) {
        await exited;
        return;
      }
      closed = true;
      await app
        .evaluate(() => {
          const click = (globalThis as { yudaoTrayClick?: (label: string) => unknown }).yudaoTrayClick;
          if (click === undefined || !click("退出客户端")) {
            throw new Error("托盘里没有可点的「退出客户端」");
          }
        })
        .catch(() => undefined);
      await exited;
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 5_000);
      await Promise.race([app.close().catch(() => undefined), promise]);
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

// 启动已经安装的客户端（工单 #208）：安装目录里的可执行文件是真实的打包版本，app.isPackaged
// 为真，更新时读取安装目录中的 app-update.yml，检查、下载与安装都按生产路径运行。
// 与开发目录启动的 launchClient 分开：这里启动的是安装出来的 exe，可执行文件与用户那一份同名不同目录
export async function launchInstalledClient(options: {
  executablePath: string;
  userData: string;
  backendAddress: string;
  env?: Record<string, string>;
}): Promise<ClientApp> {
  const app = await electron.launch({
    executablePath: options.executablePath,
    env: {
      ...process.env,
      YUDAO_E2E_USER_DATA: options.userData,
      YUDAO_E2E_BACKEND: options.backendAddress,
      ...options.env,
    },
  });
  const child = app.process();
  const exited = new Promise<void>((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve();
    } else {
      child.on("exit", () => resolve());
    }
  });
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  let closed = false;
  return {
    app,
    page,
    exited,
    close: async () => {
      if (closed) {
        return;
      }
      closed = true;
      await app.close().catch(() => undefined);
      await exited;
    },
  };
}
