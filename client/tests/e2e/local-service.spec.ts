// 客户端对本机 Yudao 服务的管理（工单 #207，设计说明第 4.3、4.4、4.5 节）。
// Playwright 启动真实运行的 Electron 客户端；服务是真实的服务进程（yudao 命令运行 backend.py 的
// `yudao api` 模式，模型回答由 FakeAdapter 给出），不使用 mock：客户端的找命令、启动独立后台进程、
// 存活性探测、写日志与发本机停止请求全部按生产代码的方式运行。
//
// 测试隔离：客户端的用户数据目录、服务的默认数据目录（由 LOCALAPPDATA 算出）与 yudao 命令目录
// 都在本次运行的临时目录内；「登录时启动」写入的注册表启动项用测试自己的应用标识，测试结束删除
// （工单验收第 7 项）。每个用例结束以后服务停止、端口空闲，下一个用例才真的需要启动服务。

import { expect, test } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { networkInterfaces, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { startLocalClient, type ClientApp } from "./fixtures";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const LOCAL_ADDRESS = "http://127.0.0.1:8765";
// 客户端启动服务以后最多等待 30 秒（设计说明第 4.3 节）；这里留出服务自身启动与预置事项的时间
const SERVICE_WAIT_MS = 90_000;
const STOP_WAIT_MS = 60_000;

type Workspace = {
  root: string;
  userData: string;
  serviceRoot: string;
  // 客户端搜索 yudao 命令的目录（测试把命令放这里，或留空表示「找不到命令」）
  commandBin: string;
};

const workspaces: Workspace[] = [];

// 本机模式的测试目录：客户端的用户数据目录、服务的用户数据根与命令目录都在临时目录内
function makeWorkspace(): Workspace {
  const root = mkdtempSync(join(tmpdir(), "yudao-local-"));
  const commandBin = join(root, "bin");
  mkdirSync(commandBin);
  return { root, userData: join(root, "client"), serviceRoot: join(root, "service-root"), commandBin };
}

// 放一个 yudao 命令：它把收到的参数原样交给 backend.py（客户端运行 `yudao api`，
// backend.py 收到 api 这个子命令就按 `yudao api` 的方式监听本机默认端口、接受本机停止请求），
// 命令行接口与退出行为和真正的 yudao 命令一致
function writeYudaoCommand(workspace: Workspace, python: string): string {
  const command = join(workspace.commandBin, "yudao.cmd");
  const script = join(repoRoot, "client", "tests", "e2e", "backend.py");
  writeFileSync(command, `@echo off\r\n"${python}" "${script}" %*\r\n`, "utf8");
  return command;
}

function repositoryPython(): string {
  const python = join(repoRoot, ".venv", "Scripts", "python.exe");
  if (!existsSync(python)) {
    throw new Error("仓库项目环境不存在：先在仓库根目录运行 uv sync --frozen");
  }
  return python;
}

// 服务是否在监听本机端口：拿到能力清单就是（设计说明第 4.3 节的存活性探测）
async function serviceAnswers(): Promise<boolean> {
  try {
    const response = await fetch(`${LOCAL_ADDRESS}/api/capabilities`, { signal: AbortSignal.timeout(2_000) });
    return response.ok;
  } catch {
    return false;
  }
}

async function waitForService(answer: boolean, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if ((await serviceAnswers()) === answer) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  return false;
}

// 本机的一个非回环 IPv4 地址：从另一台电脑访问这台电脑时用的就是它（设计说明第 4.3 节的验收）
function nonLoopbackAddress(): string | null {
  for (const addresses of Object.values(networkInterfaces())) {
    for (const info of addresses ?? []) {
      if (info.family === "IPv4" && !info.internal && !info.address.startsWith("169.254.")) {
        return info.address;
      }
    }
  }
  return null;
}

// 从非回环地址请求能力清单：局域网访问方式下能拿到响应，本机访问方式下连不上
async function lanServiceAnswers(): Promise<boolean> {
  const address = nonLoopbackAddress();
  if (address === null) {
    return false;
  }
  try {
    const response = await fetch(`http://${address}:8765/api/capabilities`, { signal: AbortSignal.timeout(2_000) });
    return response.ok;
  } catch {
    return false;
  }
}

async function waitForLanService(answer: boolean, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if ((await lanServiceAnswers()) === answer) {
      return true;
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 200);
    await promise;
  }
  return false;
}

// 读主进程当前的托盘菜单项与其可见性（主进程把只读入口挂在全局，见 index.ts）
async function trayMenuLabels(client: ClientApp): Promise<{ label: string; visible: boolean }[]> {
  return client.app.evaluate(
    () =>
      (globalThis as { yudaoTrayMenuLabels?: () => { label: string; visible: boolean }[] })
        .yudaoTrayMenuLabels?.() ?? [],
  );
}

// 当前服务的访问方式（能力清单的 deployment.access）
async function serviceAccess(): Promise<string | null> {
  try {
    const response = await fetch(`${LOCAL_ADDRESS}/api/capabilities`, { signal: AbortSignal.timeout(2_000) });
    if (!response.ok) {
      return null;
    }
    const payload = (await response.json()) as { deployment?: { access?: string } };
    return payload.deployment?.access ?? null;
  } catch {
    return null;
  }
}

// 正在运行的事项数：查询是 GET /api/queries/{名称}（应用层与接口层设计说明第 7.1 节）
async function runningRuns(): Promise<number> {
  const response = await fetch(`${LOCAL_ADDRESS}/api/queries/system.status`, { signal: AbortSignal.timeout(10_000) });
  const payload = (await response.json()) as { data?: { running_runs?: number } };
  return payload.data?.running_runs ?? -1;
}

// 停止确认的对话框是系统对话框：Playwright 看不见也点不到（实测只有主窗口可驱动）。
// 测试在主进程替换 dialog.showMessageBox 应答「停止 Yudao」并记下它收到的确认文字，
// 于是读事项数、判断要不要确认、发停止请求这三步都按生产代码运行
async function answerStopDialogs(client: ClientApp): Promise<void> {
  await client.app.evaluate(({ dialog }) => {
    const store = globalThis as { yudaoStopDialogs?: string[] };
    store.yudaoStopDialogs = [];
    // 记下对话框收到的确认文字并回答第一个按钮（停止 Yudao）
    dialog.showMessageBox = ((async (options: { message?: string }) => {
      (store.yudaoStopDialogs ??= []).push(options.message ?? "");
      return { response: 0 };
    }) as unknown as typeof dialog.showMessageBox);
  });
}

async function stopDialogTexts(client: ClientApp): Promise<string[]> {
  return client.app.evaluate(
    () => (globalThis as { yudaoStopDialogs?: string[] }).yudaoStopDialogs ?? [],
  );
}

// 收尾：测试自己发本机停止请求把服务停掉（与客户端的停止走同一条接口），
// 让下一个用例面对「服务没有运行」的开头条件
async function stopService(): Promise<void> {
  if (!(await serviceAnswers())) {
    return;
  }
  await fetch(`${LOCAL_ADDRESS}/api/system/stop`, { method: "POST", signal: AbortSignal.timeout(10_000) }).catch(
    () => undefined,
  );
  expect(await waitForService(false, STOP_WAIT_MS), "服务在测试收尾时没有停止").toBe(true);
}

// 客户端启动的服务把输出写入自己的日志（设计说明第 4.3 节）
function serviceLog(userData: string): string {
  return join(userData, "yudao-service.log");
}

// 读当前用户的注册表启动项：值名是客户端的应用标识（值数据是它的可执行文件）
function readRunEntry(valueName: string): string | null {
  const key = "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run";
  const query = spawnSync("reg.exe", ["query", key, "/v", valueName], { encoding: "utf8" });
  if (query.status !== 0) {
    return null;
  }
  const line = query.stdout.split("\n").find((item) => item.includes(valueName) && item.includes("REG_SZ"));
  return line ? line.slice(line.indexOf("REG_SZ") + "REG_SZ".length).trim() : null;
}

function removeRunEntry(valueName: string): void {
  spawnSync("reg.exe", ["delete", "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run", "/v", valueName, "/f"], {
    encoding: "utf8",
  });
}

// 启动项的值名取 Windows 的应用标识；端到端测试的标识由用户数据目录名算出（主进程里设定）
function testRunValueName(userData: string): string {
  return `com.yudao.client.e2e-${userData.split(/[\\/]/).pop()}`;
}

test.describe.configure({ mode: "serial", timeout: 300_000 });

test.beforeEach(async () => {
  // 本机模式连接固定地址 127.0.0.1:8765：这个端口上已经有服务时「客户端启动服务」无从证明，
  // 测试直接失败而不是通过
  if (!(await waitForService(false, 1_000))) {
    throw new Error(`${LOCAL_ADDRESS} 已经有服务在运行：请先停掉它再跑本机服务的端到端测试`);
  }
});

test.afterAll(() => {
  // 兜底清理：用例中途失败时也不把测试的启动项留在用户的注册表里
  for (const workspace of workspaces) {
    removeRunEntry(testRunValueName(workspace.userData));
    // Electron 与服务的文件句柄在进程退出以后 momentarily 仍占用目录（Windows 的 EPERM），
    // 带重试删除；删不掉时报告但不掩盖用例本身的结果
    try {
      rmSync(workspace.root, { recursive: true, force: true, maxRetries: 12, retryDelay: 500 });
    } catch (error) {
      console.warn(`测试目录没有删干净：${workspace.root} ${String(error)}`);
    }
  }
});

test("服务没有运行时客户端启动 yudao api 并完成连接；服务已经运行时直接连接；退出客户端不停止服务", async () => {
  const workspace = makeWorkspace();
  workspaces.push(workspace);
  writeYudaoCommand(workspace, repositoryPython());
  const client = await startLocalClient({ ...workspace, size: { width: 1440, height: 900 } });
  try {
    // 客户端找到命令、启动独立后台进程并连接：进入已连接的外壳（顶栏显示连接状态）
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: SERVICE_WAIT_MS });
    expect(await serviceAnswers()).toBe(true);
    // 服务输出写入客户端用户数据目录里的日志
    expect(existsSync(serviceLog(workspace.userData))).toBe(true);
    // 服务用的是默认数据目录（由 LOCALAPPDATA 算出，测试把它指到自己的临时目录）：
    // 数据目录里落下服务自己的文件，用户的真实目录没有被写（工单验收第 7 项）
    await expect
      .poll(() => existsSync(join(workspace.serviceRoot, "Yudao")), {
        timeout: SERVICE_WAIT_MS,
        message: "服务没有用默认数据目录",
      })
      .toBe(true);

    // 退出客户端不停止 Yudao 服务（ADR-0023）：客户端已经关闭，服务仍在监听
    await client.close();
    expect(await waitForService(true, 5_000), "客户端退出时服务被停止了").toBe(true);

    // 再次启动：服务已经在运行，客户端先请求存活性就直接连接，不再启动第二个服务进程
    const again = await startLocalClient({ ...workspace, size: { width: 1440, height: 900 } });
    try {
      await expect(again.page.locator(".connection")).toHaveText("已连接", { timeout: 30_000 });
      const starts = countStartLogLines(workspace.userData);
      expect(starts, "服务已经运行时客户端又启动了一次").toBe(1);
    } finally {
      await again.close();
    }
  } finally {
    await stopService();
  }
});

test("找不到 yudao 命令时显示安装命令与重新检测按钮", async () => {
  const workspace = makeWorkspace();
  workspaces.push(workspace);
  // 命令目录里没有 yudao 命令：客户端找不到命令，显示安装命令，不尝试连接
  const client = await startLocalClient({ ...workspace, size: { width: 1440, height: 900 } });
  try {
    await expect(client.page.getByRole("button", { name: "重新检测" })).toBeVisible({ timeout: 30_000 });
    await expect(client.page.locator("code.install")).toHaveText("uv tool install --python 3.12 <wheel>");
    await expect(client.page.getByText("没有找到 yudao 命令，用下面的命令安装 Yudao 服务：")).toBeVisible();
    expect(await serviceAnswers()).toBe(false);

    // 装上 yudao 命令以后点「重新检测」：客户端找到命令、启动服务并连接
    writeYudaoCommand(workspace, repositoryPython());
    await client.page.getByRole("button", { name: "重新检测" }).click();
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: SERVICE_WAIT_MS });
    expect(await serviceAnswers()).toBe(true);
  } finally {
    await client.close();
    await stopService();
  }
});

test("托盘的停止 Yudao 使服务退出，有事项正在运行时先确认", async () => {
  const workspace = makeWorkspace();
  workspaces.push(workspace);
  writeYudaoCommand(workspace, repositoryPython());
  const client = await startLocalClient({ ...workspace, size: { width: 1440, height: 900 } });
  try {
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: SERVICE_WAIT_MS });

    // 托盘菜单：「打开窗口」「停止 Yudao」「退出客户端」；停止只在连接本机时可见（设计说明第 4.5 节）
    await expect
      .poll(() => trayMenuLabels(client), { timeout: 30_000 })
      .toEqual([
        { label: "打开窗口", visible: true },
        { label: "停止 Yudao", visible: true },
        { label: "", visible: true },
        { label: "退出客户端", visible: true },
      ]);

    // 服务里有一个事项正在运行：预置的事项没有配置 Provider，停在等待用户决定，run 没有进终态
    await expect
      .poll(runningRuns, { timeout: SERVICE_WAIT_MS, message: "服务里没有正在运行的事项" })
      .toBeGreaterThan(0);
    await answerStopDialogs(client);

    // 点托盘菜单项（与用户点菜单是同一条路径：走真实菜单项的动作）
    const clicked = await client.app.evaluate(() => {
      const click = (globalThis as { yudaoTrayClick?: (label: string) => boolean }).yudaoTrayClick;
      if (click === undefined) {
        throw new Error("主进程没有提供托盘菜单入口");
      }
      return click("停止 Yudao");
    });
    expect(clicked).toBe(true);

    // 确认文字写明正在运行的事项数（设计说明第 4.4 节）
    await expect
      .poll(() => stopDialogTexts(client), { timeout: 30_000 })
      .toEqual([expect.stringMatching(/^有 [0-9]+ 个事项正在运行，停止以后下次启动时自动继续$/)]);

    // 本机停止请求使服务退出：进程结束，端口不再应答
    expect(await waitForService(false, STOP_WAIT_MS), "停止以后服务仍在运行").toBe(true);
    // 客户端跟着退出：同一个用户数据目录只允许一个客户端进程（设计说明第 4.5 节），
    // 退出以后才能再启动一个来核对「下次启动时自动继续」
    await client.close();

    // 「停止以后下次启动时自动继续」：下一次启动仍认得那个没有结束的事项（不是被停掉就算失败）
    const again = await startLocalClient({ ...workspace, size: { width: 1440, height: 900 } });
    try {
      await expect(again.page.locator(".connection")).toHaveText("已连接", { timeout: SERVICE_WAIT_MS });
      expect(await runningRuns()).toBeGreaterThan(0);
    } finally {
      await again.close();
    }
  } finally {
    await client.close();
    await stopService();
  }
});

test("设置页的停止 Yudao 与托盘走同一条停止路径", async () => {
  const workspace = makeWorkspace();
  workspaces.push(workspace);
  writeYudaoCommand(workspace, repositoryPython());
  const client = await startLocalClient({ ...workspace, size: { width: 1440, height: 900 } });
  try {
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: SERVICE_WAIT_MS });
    await answerStopDialogs(client);
    await client.page.goto("yudao://app/index.html#/settings");
    const stop = client.page.getByRole("button", { name: "停止 Yudao" });
    await expect(stop).toBeVisible();
    await stop.click();
    await expect
      .poll(() => stopDialogTexts(client), { timeout: 30_000 })
      .toEqual([expect.stringMatching(/^有 [0-9]+ 个事项正在运行，停止以后下次启动时自动继续$/)]);
    await expect(client.page.locator(".error")).toHaveText("Yudao 服务已经停止。连接它时客户端会重新启动。", {
      timeout: 30_000,
    });
    expect(await waitForService(false, STOP_WAIT_MS)).toBe(true);
  } finally {
    await client.close();
    await stopService();
  }
});

test("打开允许局域网访问并重新启动后服务以局域网方式运行，关闭后非回环地址不可连接", async () => {
  const workspace = makeWorkspace();
  workspaces.push(workspace);
  writeYudaoCommand(workspace, repositoryPython());
  const client = await startLocalClient({ ...workspace, size: { width: 1440, height: 900 } });
  try {
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: SERVICE_WAIT_MS });
    // 默认启动的服务是本机访问方式（服务在 8765 上，但只监听回环地址）
    expect(await serviceAccess()).toBe("local");
    expect(await lanServiceAnswers()).toBe(false);

    await client.page.goto("yudao://app/index.html#/settings");
    // 开关默认关闭（设计说明第 4.3 节）
    const toggle = client.page.getByRole("checkbox", { name: "允许局域网访问" });
    await expect(toggle).toBeVisible();
    await expect(toggle).not.toBeChecked();
    // 开关的说明文字写明局域网内不校验身份与防火墙的做法
    await expect(client.page.getByText("局域网内不校验身份", { exact: false })).toBeVisible();

    // 打开开关：服务正在运行且访问方式与开关不同，出现「重新启动服务后生效」（设计说明第 4.3 节）
    await toggle.check();
    await expect(client.page.getByText("重新启动服务后生效")).toBeVisible({ timeout: 30_000 });

    // 重新启动：有事项正在运行时先确认，文字写明正在运行的事项数（「重新启动以后自动继续」）
    await answerStopDialogs(client);
    await client.page.getByRole("button", { name: "重新启动" }).click();
    await expect
      .poll(() => stopDialogTexts(client), { timeout: 30_000 })
      .toEqual([expect.stringMatching(/^有 [0-9]+ 个事项正在运行，重新启动以后自动继续$/)]);

    // 服务以局域网方式重新启动：能力清单的访问方式为局域网，非回环地址可以请求能力清单
    await expect.poll(() => serviceAccess(), { timeout: SERVICE_WAIT_MS }).toBe("lan");
    expect(await waitForLanService(true, SERVICE_WAIT_MS), "局域网访问方式下非回环地址连不上").toBe(true);
    // 客户端重新连接（本机一项始终连接 127.0.0.1，两种访问方式下都能连接）：回到首页看到已连接
    await client.page.goto("yudao://app/index.html#/");
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: SERVICE_WAIT_MS });

    // 局域网访问方式下托盘的「停止 Yudao」仍然可用（设计说明第 4.5 节）
    await expect
      .poll(() => trayMenuLabels(client), { timeout: 30_000 })
      .toContainEqual({ label: "停止 Yudao", visible: true });

    // 关闭开关并重新启动：从非回环地址无法连接（服务回到本机访问方式）
    await client.page.goto("yudao://app/index.html#/settings");
    await toggle.uncheck();
    await expect(client.page.getByText("重新启动服务后生效")).toBeVisible({ timeout: 30_000 });
    await client.page.getByRole("button", { name: "重新启动" }).click();
    await expect.poll(() => serviceAccess(), { timeout: SERVICE_WAIT_MS }).toBe("local");
    expect(await waitForLanService(false, SERVICE_WAIT_MS), "关闭开关以后非回环地址仍然可以连接").toBe(true);
  } finally {
    await client.close();
    await stopService();
  }
});

test("登录时启动客户端读写当前用户的启动项，测试结束删除", async () => {
  const workspace = makeWorkspace();
  workspaces.push(workspace);
  // 这个用例不需要服务：命令目录里没有 yudao 命令，客户端显示设置页
  const client = await startLocalClient({ ...workspace, size: { width: 1440, height: 900 } });
  try {
    const toggle = client.page.getByRole("checkbox", { name: "登录时启动客户端" });
    await expect(toggle).toBeVisible({ timeout: 30_000 });
    // 默认关闭（设计说明第 4.5 节）
    await expect(toggle).not.toBeChecked();

    // 「登录时启动客户端」写当前用户的注册表启动项（HKCU 的 Run 键），不需要管理员权限；
    // 值名是测试自己的应用标识，用户的启动项与开发用的 Electron 不受影响
    const valueName = testRunValueName(workspace.userData);
    expect(readRunEntry(valueName)).toBeNull();
    await toggle.check();
    const entry = readRunEntry(valueName);
    expect(entry, "注册表启动项没有写入").not.toBeNull();
    expect(entry).toContain("electron.exe");

    // 读回以注册表里的实际值为准：重新载入界面仍显示打开
    await client.page.reload();
    await expect(client.page.getByRole("checkbox", { name: "登录时启动客户端" })).toBeChecked({ timeout: 30_000 });

    await client.page.getByRole("checkbox", { name: "登录时启动客户端" }).uncheck();
    expect(readRunEntry(valueName), "取消勾选以后启动项没有删除").toBeNull();
  } finally {
    await client.close();
  }
});

test("客户端已经运行时再次启动它，不产生第二个进程，已运行的客户端显示窗口", async () => {
  const workspace = makeWorkspace();
  workspaces.push(workspace);
  writeYudaoCommand(workspace, repositoryPython());
  const client = await startLocalClient({ ...workspace, size: { width: 1440, height: 900 } });
  try {
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: SERVICE_WAIT_MS });
    const visible = () =>
      client.app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows().some((window) => window.isVisible()),
      );

    // 关闭窗口只隐藏窗口（工单 #79 已实现）：隐藏以后没有可见窗口
    await client.app.evaluate(() => (globalThis as { yudaoHideWindow?: () => void }).yudaoHideWindow?.());
    await expect.poll(visible, { timeout: 30_000 }).toBe(false);

    // 第二次启动同一个客户端：单实例锁把这次启动交给已有实例，第二个进程自己退出
    // （设计说明第 4.5 节：客户端同一时刻只有一个进程）
    const second = spawn(
      process.execPath,
      [
        join(repoRoot, "client", "node_modules", "electron", "cli.js"),
        join(repoRoot, "client", "out", "main", "index.js"),
      ],
      {
        cwd: repoRoot,
        stdio: "ignore",
        env: {
          ...process.env,
          YUDAO_E2E_USER_DATA: workspace.userData,
          LOCALAPPDATA: workspace.serviceRoot,
          YUDAO_E2E_COMMAND_BIN: workspace.commandBin,
        },
      },
    );
    const exited = await Promise.race([
      new Promise<number | null>((resolve) => second.on("exit", (code) => resolve(code))),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 90_000)),
    ]);
    expect(exited, "第二次启动没有退出：出现了第二个客户端进程").not.toBeNull();

    // 已有实例把窗口显示出来
    await expect.poll(visible, { timeout: 60_000, message: "已有实例没有显示窗口" }).toBe(true);
  } finally {
    await client.close();
    await stopService();
  }
});

// 客户端写下的「启动 <命令> api」日志行数：服务已经运行时不该再启动一次
function countStartLogLines(userData: string): number {
  try {
    return readFileSync(serviceLog(userData), "utf8").split("\n").filter((line) => line.includes("] 启动 ")).length;
  } catch {
    return 0;
  }
}
