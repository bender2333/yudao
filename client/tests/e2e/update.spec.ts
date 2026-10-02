// 客户端的安装包与更新页（工单 #208，设计说明第 3.3、5.2、5.3、7 节）。
// 全部使用真实运行的系统：用 scripts/build-installer.mjs 构建两个测试版本（版本 1 与版本 2，
// 测试用的 appId 与产品名 Yudao-e2e），把它们放进更新源目录（服务从 /client-update/ 提供，
// 工单 #206 的更新源），用 /S /D= 在临时目录安装版本 1，再启动安装出来的客户端。
// 更新走 electron-updater 的真实流程：读取 latest.yml、按 blockmap 差分下载、校验 SHA-512、
// 退出客户端、静默运行安装程序、安装完成以后启动新版本。不使用任何 mock。
//
// 隔离：appId、产品名、安装目录与用户数据目录都在本次运行的临时目录内；用户已经安装的
// 客户端与 Yudao 服务在测试前后不变（工单验收第 7 项）。

import { expect, test } from "@playwright/test";
import { extractFile as extractAsarFile } from "@electron/asar";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { launchInstalledClient, startBackend, type Backend, type ClientApp } from "./fixtures";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const clientRoot = join(repoRoot, "client");
// 测试构建的缓存目录：两个测试版本的安装包在这里构建一次，之后的运行复用（构建一次约 1 分钟，
// 每次端到端运行都重建代价太大；目录被 git 忽略）。安装程序本身每次运行都真实安装与更新
const buildRoot = join(clientRoot, "tests", "e2e", ".update-build");
// 测试用的 appId、产品名与安装包文件名前缀：与用户已经安装的那一份不同（工单验收第 7 项）
const APP_ID = "com.yudao.client.e2e-update";
const PRODUCT_NAME = "Yudao-e2e";
const SETUP_BASENAME = "Yudao-Setup-e2e";
const EXE_NAME = `${PRODUCT_NAME}.exe`;
// 客户端构建时记录的接口版本按服务报告的版本改写：版本 1 的客户端记录接口版本 1，
// 版本 2 的客户端记录接口版本 2（测试构建时改写客户端记录的接口版本，工单验收第 1 项）
const SERVICE_API_VERSION = 2;

type Build = { dir: string; setup: string; version: string };

type Workspace = {
  root: string;
  v1: Build;
  v2: Build;
  assets: string;
  installDir: string;
};

let workspace: Workspace;

// 用发布脚本构建一个测试版本（测试用的 appId、产品名与安装包文件名），输出到构建缓存目录。
// 已经构建过就复用（按 setup 与 latest.yml 是否存在判断）。构建在非管理员、没有开发者模式的
// 账户下进行（工单验收第 7 项）
function buildVersion(version: string, apiVersion: number, outDir: string): Build {
  const setup = join(outDir, `${SETUP_BASENAME}-${version}.exe`);
  if (!existsSync(setup) || !existsSync(join(outDir, "latest.yml"))) {
    const result = spawnSync("node", ["scripts/build-installer.mjs"], {
      cwd: clientRoot,
      shell: true,
      encoding: "utf8",
      env: {
        ...process.env,
        YUDAO_APP_ID: APP_ID,
        YUDAO_PRODUCT_NAME: PRODUCT_NAME,
        YUDAO_SETUP_BASENAME: SETUP_BASENAME,
        YUDAO_OUTPUT_DIR: outDir,
        YUDAO_VERSION: version,
        YUDAO_API_VERSION: String(apiVersion),
      },
    });
    if (result.status !== 0) {
      throw new Error(`构建版本 ${version} 失败：\n${result.stdout}\n${result.stderr}`);
    }
  }
  return { dir: outDir, setup, version };
}

// 更新源目录：把两个版本的安装程序、blockmap 与各自的 latest.yml 放在一起。
// 客户端按已连接的地址加 /client-update/ 读取 latest.yml（服务从这里返回），
// 因此同一时刻只有一份 latest.yml 生效；测试用 swapAssets 切换服务提供哪个版本
function prepareAssets(root: string): string {
  const assets = join(root, "assets");
  mkdirSync(assets, { recursive: true });
  return assets;
}

// 让更新源提供某个版本：把它的安装程序、blockmap 与 latest.yml 放进更新源目录。
// 服务每次请求都从磁盘读取，因此替换文件以后下一次检查就看到新的版本
function serveVersion(assets: string, build: Build): void {
  const setupName = `${SETUP_BASENAME}-${build.version}.exe`;
  for (const name of [setupName, `${setupName}.blockmap`, "latest.yml"]) {
    cpSync(join(build.dir, name), join(assets, name));
  }
}

// 用量产安装程序静默安装一个版本到指定目录（/S 静默、/D= 指定目录，按用户安装不需要管理员权限）
function installVersion(setup: string, targetDir: string): void {
  rmSync(targetDir, { recursive: true, force: true });
  mkdirSync(targetDir, { recursive: true });
  const result = spawnSync(setup, ["/S", `/D=${targetDir}`], { encoding: "utf8", shell: false });
  if (result.status !== 0) {
    throw new Error(`安装失败：${result.status} ${result.stdout} ${result.stderr}`);
  }
}

// 读安装目录里客户端记录的发布版本号（asar 中的 package.json）。
// 安装程序替换文件期间 asar 可能暂时不存在，这时返回 null，由等待版本的一方继续轮询
function installedVersion(installDir: string): string | null {
  const asarPath = join(installDir, "resources", "app.asar");
  if (!existsSync(asarPath)) {
    return null;
  }
  let text: string;
  try {
    text = extractAsarFile(asarPath, "package.json").toString("utf8");
  } catch {
    // 文件正在被替换：这一轮读不到，下一轮再读
    return null;
  }
  const parsed: unknown = JSON.parse(text);
  if (typeof parsed !== "object" || parsed === null || !("version" in parsed) || typeof parsed.version !== "string") {
    throw new Error("安装目录里的客户端 package.json 没有版本号");
  }
  return parsed.version;
}

// 安装出来的客户端的用户数据目录：每个用例一个，互不影响
function newUserData(root: string, name: string): string {
  const dir = join(root, "userdata", name);
  mkdirSync(dir, { recursive: true });
  return dir;
}

// 触发一次更新并等安装完成：点「更新客户端」，等客户端退出（退出后静默运行安装程序），
// 再等安装目录里的客户端变为目标版本。安装程序替换文件需要一点时间，之后才读到新版本
async function triggerUpdate(client: ClientApp, installDir: string, expectedVersion: string): Promise<void> {
  await client.page.getByRole("button", { name: "更新客户端" }).click();
  await client.exited;
  await waitForInstalledVersion(installDir, expectedVersion, 180_000);
}

test.describe.configure({ mode: "serial", timeout: 900_000 });

test.beforeAll(() => {
  const root = mkdtempSync(join(tmpdir(), "yudao-update-"));
  workspace = {
    root,
    v1: buildVersion("0.0.1", 1, join(buildRoot, "v1")),
    v2: buildVersion("0.0.2", SERVICE_API_VERSION, join(buildRoot, "v2")),
    assets: prepareAssets(root),
    installDir: join(root, "install"),
  };
});

test.afterAll(async () => {
  // beforeAll 失败时 workspace 还没有建立，不做收尾
  if (workspace === undefined) {
    return;
  }
  // 安装出来的客户端可能被安装程序的 --force-run 启动着，占住安装目录的文件；
  // 结束后按可执行文件路径结束本次测试所有安装目录里的进程，不按进程名结束，
  // 也不动用户已经安装的那一份。文件句柄释放需要一点时间，重试几次
  for (let attempt = 0; attempt < 10; attempt += 1) {
    stopInstalledProcesses(workspace.root);
    try {
      rmSync(workspace.root, { recursive: true, force: true });
      return;
    } catch {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 1_000);
      await promise;
    }
  }
});

test("接口版本不同时出现更新页，更新以后客户端变为新版本并重新连接，不再出现更新页", async () => {
  // 服务报告接口版本 2，更新源提供版本 2；安装的版本 1 客户端记录接口版本 1，因此显示更新页
  serveVersion(workspace.assets, workspace.v2);
  const backend: Backend = await startBackend({
    apiVersion: SERVICE_API_VERSION, releaseAssets: workspace.assets, port: 0,
  });
  try {
    installVersion(workspace.v1.setup, workspace.installDir);
    expect(installedVersion(workspace.installDir)).toBe("0.0.1");
    const userData = newUserData(workspace.root, "update-up");
    const client = await launchInstalledClient({
      executablePath: join(workspace.installDir, EXE_NAME),
      userData,
      backendAddress: backend.address,
      env: { YUDAO_UPDATE_LOG: join(userData, "update.log") },
    });
    // 更新页写明客户端与 Yudao 服务两边的发布版本号与接口版本
    await expect(client.page.getByRole("heading", { name: "请更新客户端" })).toBeVisible();
    await expect(client.page.locator("text=客户端发布版本：0.0.1")).toBeVisible();
    await expect(client.page.locator("text=Yudao 服务发布版本：0.1.0")).toBeVisible();
    await expect(client.page.locator("text=客户端接口版本：1")).toBeVisible();
    await expect(client.page.locator("text=Yudao 服务接口版本：2")).toBeVisible();
    // 更新页不打开其他页面
    await expect(client.page.locator(".sidebar")).toHaveCount(0);
    // 更新：下载版本 2、退出客户端、静默安装，安装完成以后启动新版本
    await triggerUpdate(client, workspace.installDir, "0.0.2");
    // 更新过程没有 SmartScreen 警告：electron-updater 下载的安装程序不带浏览器写入的
    // 「来自网络」标记（设计说明第 7 节）。这里核对下载缓存里的安装程序没有 Zone.Identifier
    // 数据流 —— 有它才会触发 SmartScreen
    expect(installerStreams(workspace.v2.version)).toEqual([":$DATA"]);
    // 安装程序 --force-run 启动的那一份用默认用户数据目录，测试不用它；结束它以免占住安装目录
    stopInstalledProcesses(workspace.installDir);
    // 重新启动新版本：连接服务（接口版本 2）以后接口版本相同，不再出现更新页
    const relaunched = await launchInstalledClient({
      executablePath: join(workspace.installDir, EXE_NAME),
      userData: newUserData(workspace.root, "update-up-after"),
      backendAddress: backend.address,
    });
    try {
      await expect(relaunched.page.locator(".sidebar")).toBeVisible({ timeout: 60_000 });
      await expect(relaunched.page.getByRole("heading", { name: "请更新客户端" })).toHaveCount(0);
    } finally {
      await relaunched.close();
    }
  } finally {
    await backend.stop();
  }
});

test("客户端比服务新时降到服务提供的版本", async () => {
  // 更新源提供版本 1，安装的客户端是版本 2：客户端比服务新，同样更新，降到版本 1
  serveVersion(workspace.assets, workspace.v1);
  const backend = await startBackend({ apiVersion: 1, releaseAssets: workspace.assets, port: 0 });
  try {
    const installDir = join(workspace.root, "install-downgrade");
    installVersion(workspace.v2.setup, installDir);
    // 服务报告接口版本 1，而安装的版本 2 客户端记录接口版本 2：显示更新页（接口版本不同）
    const client = await launchInstalledClient({
      executablePath: join(installDir, EXE_NAME),
      userData: newUserData(workspace.root, "downgrade"),
      backendAddress: backend.address,
    });
    await expect(client.page.getByRole("heading", { name: "请更新客户端" })).toBeVisible();
    await triggerUpdate(client, installDir, "0.0.1");
    stopInstalledProcesses(installDir);
  } finally {
    await backend.stop();
  }
});

test("校验失败时更新页显示原因与重试，旧版本保持", async () => {
  // 篡改更新源里的安装程序：latest.yml 中的 SHA-512 与文件不再一致，下载以后校验失败
  serveVersion(workspace.assets, workspace.v2);
  const installerName = `${SETUP_BASENAME}-0.0.2.exe`;
  writeFileSync(join(workspace.assets, installerName), "tampered installer");
  const backend = await startBackend({ apiVersion: SERVICE_API_VERSION, releaseAssets: workspace.assets, port: 0 });
  try {
    const installDir = join(workspace.root, "install-tampered");
    installVersion(workspace.v1.setup, installDir);
    const client = await launchInstalledClient({
      executablePath: join(installDir, EXE_NAME),
      userData: newUserData(workspace.root, "tampered"),
      backendAddress: backend.address,
    });
    try {
      await expect(client.page.getByRole("heading", { name: "请更新客户端" })).toBeVisible();
      await client.page.getByRole("button", { name: "更新客户端" }).click();
      // 更新页显示失败原因与「重试」
      await expect(client.page.locator("text=sha512")).toBeVisible({ timeout: 120_000 });
      await expect(client.page.getByRole("button", { name: "重试" })).toBeVisible();
      // 旧版本保持：客户端进程仍在运行，安装目录里的版本仍是 0.0.1
      expect(installedVersion(installDir)).toBe("0.0.1");
    } finally {
      await client.close().catch(() => undefined);
    }
  } finally {
    await backend.stop();
    // 还原被篡改的安装程序，供后面的用例使用
    cpSync(join(workspace.v2.dir, `${SETUP_BASENAME}-0.0.2.exe`), join(workspace.assets, `${SETUP_BASENAME}-0.0.2.exe`));
  }
});

test("Yudao 服务没有提供安装包时更新页显示控制主机没有提供客户端安装包", async () => {
  // 服务的发布资源目录不存在（从源码运行），/client-update/latest.yml 返回 404
  const backend = await startBackend({ apiVersion: SERVICE_API_VERSION, port: 0 });
  try {
    const installDir = join(workspace.root, "install-no-assets");
    installVersion(workspace.v1.setup, installDir);
    const client = await launchInstalledClient({
      executablePath: join(installDir, EXE_NAME),
      userData: newUserData(workspace.root, "no-assets"),
      backendAddress: backend.address,
    });
    try {
      await expect(client.page.getByRole("heading", { name: "请更新客户端" })).toBeVisible();
      await client.page.getByRole("button", { name: "更新客户端" }).click();
      await expect(client.page.locator("text=控制主机没有提供客户端安装包")).toBeVisible({ timeout: 60_000 });
      await expect(client.page.getByRole("button", { name: "重试" })).toBeVisible();
    } finally {
      await client.close().catch(() => undefined);
    }
  } finally {
    await backend.stop();
  }
});

test("更新期间与更新以后本机的 Yudao 服务保持运行", async () => {
  serveVersion(workspace.assets, workspace.v2);
  // 用同一个数据目录与端口启动服务，客户端连接它以后更新；更新只替换客户端，服务进程不受影响
  const backend = await startBackend({ apiVersion: SERVICE_API_VERSION, releaseAssets: workspace.assets, port: 0 });
  try {
    const installDir = join(workspace.root, "install-service");
    installVersion(workspace.v1.setup, installDir);
    const client = await launchInstalledClient({
      executablePath: join(installDir, EXE_NAME),
      userData: newUserData(workspace.root, "service"),
      backendAddress: backend.address,
    });
    await expect(client.page.getByRole("heading", { name: "请更新客户端" })).toBeVisible();
    await triggerUpdate(client, installDir, "0.0.2");
    stopInstalledProcesses(installDir);
    // 更新完成以后服务仍在运行：能力清单仍能取到
    const response = await fetch(`${backend.address}/api/capabilities`);
    expect(response.status).toBe(200);
  } finally {
    await backend.stop();
  }
});

// 等安装目录里的客户端变为指定版本：安装程序替换文件需要一点时间，之后才读到新版本
async function waitForInstalledVersion(installDir: string, version: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let last: string | null = "";
  while (Date.now() < deadline) {
    last = installedVersion(installDir);
    if (last === version) {
      return;
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 1_000);
    await promise;
  }
  throw new Error(`等待安装版本 ${version} 超时，当前 ${last}`);
}

// 结束可执行文件路径在给定前缀下的客户端进程：安装程序 --force-run 启动的那一份占住安装目录的
// 文件。传本次测试的临时根目录就覆盖它的全部安装目录；只按可执行文件路径匹配，不按进程名结束，
// 也不动用户已经安装的那一份
function stopInstalledProcesses(pathPrefix: string): void {
  const query = `Get-CimInstance Win32_Process -Filter "name='${PRODUCT_NAME}.exe'" | ` +
    `Where-Object { $_.ExecutablePath -like '${pathPrefix.replaceAll("'", "''")}*' } | ` +
    `ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`;
  spawnSync("powershell", ["-NoProfile", "-Command", query], { encoding: "utf8" });
}

// electron-updater 下载到缓存的安装程序的 NTFS 数据流（设计说明第 7 节：不带 Zone.Identifier
// 才不出现 SmartScreen）。缓存目录由 app-update.yml 的 updaterCacheDirName 给出
function installerStreams(version: string): string[] {
  const cache = join(process.env.LOCALAPPDATA ?? "", "yudao-client-updater", "pending");
  const installer = join(cache, `${SETUP_BASENAME}-${version}.exe`);
  const result = spawnSync("powershell",
    ["-NoProfile", "-Command", `(Get-Item -LiteralPath '${installer}' -Stream *).Stream`],
    { encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(`读取安装程序数据流失败：${result.stderr}`);
  }
  return result.stdout.trim().split(/\r?\n/).map((line) => line.trim()).filter((line) => line.length > 0);
}
