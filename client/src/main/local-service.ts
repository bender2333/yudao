// 本机 Yudao 服务的发现、启动、探测与停止（设计说明第 4.3、4.4 节）。
// 连接「本机」时先请求服务；没有运行时在 PATH 与 uv 的可执行文件目录中寻找 yudao 命令，
// 找到就启动 `yudao api`（默认数据目录）作为独立后台进程，输出写入日志，最多等待 30 秒。
// 找不到命令时由界面显示安装命令；停止经 #206 的 POST /api/system/stop。

import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { appendFileSync, closeSync, existsSync, openSync } from "node:fs";
import { join } from "node:path";
import { app, dialog } from "electron";
import { DEFAULT_LOCAL_ADDRESS } from "./settings";
// 本机服务的地址来自连接设置（http://127.0.0.1:8765，与 harness/__main__.py 的默认端口相同，
// 设计说明第 3.4、4.3 节）；探测、读状态与停止都请求这个地址

// 找不到 yudao 命令时界面显示的安装命令（设计说明第 4.3 节）
export const INSTALL_COMMAND = "uv tool install --python 3.12";

// 启动以后等待服务可用的上限与轮询间隔（设计说明第 4.3 节：最多等待 30 秒）
const WAIT_LIMIT_MS = 30_000;
const POLL_INTERVAL_MS = 200;
const PROBE_TIMEOUT_MS = 2_000;
// 读运行中的事项数与发本机停止请求的超时：服务卡住时让托盘动作与界面尽快得到失败原因
const REQUEST_TIMEOUT_MS = 10_000;
// 重新启动前等待旧服务退出的上限（服务收到停止请求后要等待进行中的写入完成、释放进程锁）
const STOP_WAIT_MS = 30_000;
// 重新启动时旧进程对日志文件的句柄释放较慢，写日志头的有限重试
const LOG_OPEN_RETRIES = 50;
const LOG_OPEN_RETRY_MS = 100;

export type YudaoCommand = {
  // 可执行文件的绝对路径
  command: string;
  // 命令所在目录（uv tool install 的目录等）：启动子进程时补进 PATH
  extraPaths: string[];
};

// 停止服务的结果：是否已发出停止请求、停止前运行中的事项数与给用户看的一句话
export type LocalServiceStop = {
  stopped: boolean;
  runningRuns: number;
  message: string;
};

// 服务日志的位置：客户端用户数据目录下的 yudao-service.log（设计说明第 4.3 节：输出写入日志）
export function serviceLogPath(): string {
  return join(app.getPath("userData"), "yudao-service.log");
}

// 请求服务的能力清单：拿到 HTTP 响应就说明服务在运行；连接被拒与超时是「没有运行」这一
// 正常结果，解析与其它异常就地抛出。设计说明第 4.3 节所说的 health 在接口层第 7.1 节
// 迁移为 system.status；这里用能力清单做存活性探测，不新增与第 7.1 节冲突的旧路由
export async function probeService(base = DEFAULT_LOCAL_ADDRESS): Promise<boolean> {
  let response: Response;
  try {
    response = await fetch(`${base}/api/capabilities`, { signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) });
  } catch (error) {
    const name = error instanceof Error ? error.name : "";
    if (name === "TypeError" || name === "TimeoutError" || name === "AbortError") {
      return false;
    }
    throw error;
  }
  return response.status < 500;
}

// 找 yudao 命令的目录顺序：端到端测试给的目录（测试把 yudao 命令放在那里，客户端的找命令、
// 启动与探测按生产代码的方式运行；它排在 PATH 之前，测试才不会被机器上已装的 yudao 顶掉）；
// PATH 的每个目录；uv tool install 默认的用户主目录 .local/bin；uv 自身可执行文件所在目录
// （环境变量指定的目录，以及 PATH 里含 uv.exe 的目录）
export function findYudaoCommand(): YudaoCommand | null {
  const pathDirs = (process.env.PATH ?? "").split(";").filter((entry) => entry.length > 0);
  const uvDirs: string[] = [];
  for (const name of ["UV_TOOL_BIN_DIR", "UV_BIN_DIR", "UV_INSTALL_DIR"]) {
    const value = process.env[name];
    if (value && value.length > 0) {
      uvDirs.push(value);
    }
  }
  uvDirs.push(...pathDirs.filter((dir) => existsSync(join(dir, "uv.exe")) || existsSync(join(dir, "uv"))));
  const home = process.env.USERPROFILE ?? process.env.HOME ?? "";
  const testBin = process.env.YUDAO_E2E_COMMAND_BIN;
  const extraPaths = [
    ...(testBin ? [testBin] : []),
    ...(home.length > 0 ? [join(home, ".local", "bin")] : []),
    ...uvDirs,
  ];
  const dirs = [...(testBin ? [testBin] : []), ...pathDirs, ...extraPaths];
  const names = ["yudao.exe", "yudao.cmd", "yudao.bat", "yudao"];
  for (const dir of dirs) {
    for (const name of names) {
      const candidate = join(dir, name);
      if (existsSync(candidate)) {
        return { command: candidate, extraPaths };
      }
    }
  }
  return null;
}

// 启动 `yudao api`：独立的后台进程，没有窗口，输出写入日志，不随客户端退出。
// 打开「允许局域网访问」时带上 `--access lan --host 0.0.0.0`（设计说明第 4.3 节）；
// 服务已经在运行时直接返回 true；找到不到命令时返回 false，由界面显示安装命令
export async function startYudaoService(allowLan: boolean): Promise<boolean> {
  if (await probeService()) {
    return true;
  }
  const found = findYudaoCommand();
  if (found === null) {
    return false;
  }
  const args = allowLan ? ["api", "--access", "lan", "--host", "0.0.0.0"] : ["api"];
  const logPath = serviceLogPath();
  const env = { ...process.env, PATH: [...found.extraPaths, process.env.PATH ?? ""].join(";") };
  const launch = async (): Promise<boolean> => {
    // 服务刚停止时（重新启动的场景）旧进程对日志文件的句柄在 Windows 上释放得比进程退出晚，
    // 打开会短暂返回 EBUSY：有限重试，其它错误就地抛出
    for (let attempt = 0; ; attempt += 1) {
      try {
        appendFileSync(logPath, `\n[${new Date().toISOString()}] 启动 ${found.command} ${args.join(" ")}\n`);
        break;
      } catch (error) {
        const code = (error as NodeJS.ErrnoException).code;
        if (code !== "EBUSY" || attempt >= LOG_OPEN_RETRIES) {
          throw error;
        }
        const { promise, resolve } = Promise.withResolvers<void>();
        setTimeout(resolve, LOG_OPEN_RETRY_MS);
        await promise;
      }
    }
    let child: ChildProcess;
    if (process.platform === "win32") {
      // uv 与 pip 安装的 yudao 在 Windows 上是 .cmd 批处理，Node 直接以文件启动会 EINVAL，
      // 因此经 cmd.exe 启动。服务的输出接到我们打开好的日志文件句柄（与 POSIX 分支同一做法）：
      // 子进程不继承客户端的任何管道句柄，成为独立的进程（设计说明第 4.3 节：没有窗口，
      // 输出写入日志，不随客户端退出；ADR-0023）。日志文件的句柄在重试之后打开，避免与
      // 刚停止的旧进程抢同一个文件
      const fd = openSync(logPath, "a");
      child = spawn("cmd.exe", ["/d", "/s", "/c", found.command, ...args], {
        env,
        detached: true,
        windowsHide: true,
        stdio: ["ignore", fd, fd],
      });
      closeSync(fd);
    } else {
      const fd = openSync(logPath, "a");
      child = spawn(found.command, args, { env, detached: true, stdio: ["ignore", fd, fd] });
      closeSync(fd);
    }
    child.unref();
    const deadline = Date.now() + WAIT_LIMIT_MS;
    while (Date.now() < deadline) {
      if (await probeService()) {
        return true;
      }
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, POLL_INTERVAL_MS);
      await promise;
    }
    return false;
  };
  // 刚被停止的服务对日志文件的句柄释放得比进程退出晚：子进程用 shell 重定向打开日志时可能失败而
  // 立刻退出，这次启动就没有服务可用。等一小段再整体重试一次；两次都起不来才返回 false
  if (await launch()) {
    return true;
  }
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, POLL_INTERVAL_MS);
  await promise;
  return launch();
}

// 读取 system.status 的正在运行的 run 数（设计说明第 4.4 节：客户端在停止之前用它显示确认）。
// 查询接口是 GET /api/queries/{名称}（应用层与接口层设计说明第 7.1 节）；回答的形状按快照
// 生成的 SystemStatus 核对，不符合就地抛出：读不到数量就不能判断是否需要确认
export async function readRunningRuns(base = DEFAULT_LOCAL_ADDRESS): Promise<number> {
  const response = await fetch(`${base}/api/queries/system.status`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  if (!response.ok) {
    throw new Error(`system.status 返回 ${response.status}`);
  }
  const payload: unknown = await response.json();
  if (typeof payload !== "object" || payload === null || !("data" in payload)) {
    throw new Error("system.status 的回答没有 data");
  }
  const data: unknown = payload.data;
  if (typeof data !== "object" || data === null || !("running_runs" in data)) {
    throw new Error("system.status 的回答没有 running_runs");
  }
  const running: unknown = data.running_runs;
  if (typeof running !== "number") {
    throw new Error("system.status 的 running_runs 不是数字");
  }
  return running;
}

// 本机停止请求（设计说明第 4.4 节）：只在本机访问方式下被服务接受，接受时返回 202。
// 其它状态码说明这次请求没有生效，就地抛出由界面显示原因
export async function requestStop(base = DEFAULT_LOCAL_ADDRESS): Promise<void> {
  const response = await fetch(`${base}/api/system/stop`, { method: "POST", signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  if (response.status !== 202) {
    throw new Error(`本机停止请求返回 ${response.status}`);
  }
}

// 停止前的确认内容：没有事项正在运行时返回 null（直接停）；有时返回给用户看的
// 「有 N 个事项正在运行，停止以后下次启动时自动继续」（设计说明第 4.4 节）
export function stopConfirmMessage(runningRuns: number): string | null {
  if (runningRuns <= 0) {
    return null;
  }
  return `有 ${runningRuns} 个事项正在运行，停止以后下次启动时自动继续`;
}

// 重新启动前的确认内容：与停止同一口径，文字换成「重新启动以后自动继续」（设计说明第 4.3 节）
export function restartConfirmMessage(runningRuns: number): string | null {
  if (runningRuns <= 0) {
    return null;
  }
  return `有 ${runningRuns} 个事项正在运行，重新启动以后自动继续`;
}

// 停止服务：先读 system.status 的运行中事项数，大于 0 时显示确认对话框，确认后发本机停止请求
// （设计说明第 4.4、4.5 节）。托盘菜单与设置页的「停止 Yudao」都调用它。
export async function stopLocalServiceConfirming(): Promise<LocalServiceStop> {
  const runningRuns = await readRunningRuns();
  const prompt = stopConfirmMessage(runningRuns);
  if (prompt !== null && !(await confirmStopWithDialog(prompt, "进行中的事项会在下次启动 Yudao 服务时自动继续。"))) {
    return { stopped: false, runningRuns, message: "已取消停止，Yudao 服务继续运行。" };
  }
  await requestStop();
  return { stopped: true, runningRuns, message: "已请求停止 Yudao 服务，进行中的事项下次启动时继续。" };
}

// 重新启动服务（设计说明第 4.3 节）：访问方式与开关不同时让改动生效。先用本机停止请求停止服务，
// 有事项正在运行时先确认（「有 N 个事项正在运行，重新启动以后自动继续」），再按开关启动
export async function restartLocalServiceConfirming(allowLan: boolean): Promise<LocalServiceStop> {
  const runningRuns = await readRunningRuns();
  const prompt = restartConfirmMessage(runningRuns);
  if (prompt !== null && !(await confirmStopWithDialog(prompt, "进行中的事项会在重新启动 Yudao 服务以后自动继续。"))) {
    return { stopped: false, runningRuns, message: "已取消重新启动，Yudao 服务继续运行。" };
  }
  await requestStop();
  // 停止请求返回 202 时服务仍在收尾（等待写入完成、释放数据目录的进程锁）：等它真的退出，
  // 否则 startYudaoService 的存活性探测会命中还没退出完的旧服务而跳过启动
  const deadline = Date.now() + STOP_WAIT_MS;
  while (Date.now() < deadline && (await probeService())) {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, POLL_INTERVAL_MS);
    await promise;
  }
  const started = await startYudaoService(allowLan);
  return started
    ? { stopped: true, runningRuns, message: "已重新启动 Yudao 服务。" }
    : { stopped: true, runningRuns, message: "Yudao 服务已经停止，没有找到 yudao 命令。" };
}

// 确认用的系统对话框：默认按钮是「继续运行」，避免误按就停掉服务
async function confirmStopWithDialog(message: string, detail: string): Promise<boolean> {
  const { response } = await dialog.showMessageBox({
    type: "warning",
    buttons: ["停止 Yudao", "继续运行"],
    defaultId: 1,
    cancelId: 1,
    title: "停止 Yudao",
    message,
    detail,
  });
  return response === 0;
}
