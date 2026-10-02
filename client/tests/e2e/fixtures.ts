// 端到端测试的公共装置：启动真实后端（FakeAdapter 驱动的服务）与 Electron 客户端。
// 客户端经连接设置连到后端地址；窗口尺寸由测试设置（1440×900 与 390×844）。
// 后端与客户端都使用临时目录，不写入仓库（工单验收：模型回答由 FakeAdapter 给出，不使用 mock）。

import { _electron as electron, type ElectronApplication, type Page } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export type Backend = {
  port: number;
  address: string;
  dataDir: string;
  stop: () => Promise<void>;
};

export type ClientApp = {
  app: ElectronApplication;
  page: Page;
  close: () => Promise<void>;
};

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

// 启动真实后端：脚本在 client/tests/e2e/backend.py 中，用仓库项目的 Python 环境运行。
// apiVersion 让服务报告一个不同的接口版本，用于核对更新页
export async function startBackend(options: { apiVersion?: number; admitAndBind?: boolean } = {}): Promise<Backend> {
  const script = ["client/tests/e2e/backend.py", "--port", "0"];
  if (options.apiVersion !== undefined) {
    script.push("--api-version", String(options.apiVersion));
  }
  if (options.admitAndBind === true) {
    script.push("--admit-and-bind");
  }
  const child = spawn("uv", ["run", "python", ...script], {
    cwd: repoRoot,
    stdio: ["pipe", "pipe", "pipe"],
    shell: true,
  });
  const line = await readFirstLine(child);
  const parsed = JSON.parse(line) as { port: number; data_dir: string };
  return {
    port: parsed.port,
    address: `http://127.0.0.1:${parsed.port}`,
    dataDir: parsed.data_dir,
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
  const userData = mkdtempSync(join(tmpdir(), "yudao-client-"));
  const app = await electron.launch({
    args: [join(repoRoot, "client", "out", "main", "index.js")],
    cwd: repoRoot,
    env: {
      ...process.env,
      YUDAO_E2E_USER_DATA: userData,
      YUDAO_E2E_BACKEND: backend.address,
      YUDAO_E2E_WIDTH: String(size.width),
      YUDAO_E2E_HEIGHT: String(size.height),
    },
  });
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  if (options.colorScheme) {
    await page.emulateMedia({ colorScheme: options.colorScheme });
  }
  return {
    app,
    page,
    close: () => app.close(),
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
