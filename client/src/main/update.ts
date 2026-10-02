// 客户端的更新（设计说明第 5.2、5.3、7 节，工单 #208，ADR-0023）：
// 客户端跟随它连接的 Yudao 服务，接口版本不同时由用户在更新页启动一次更新。
//
// electron-updater 6 系列的 generic 提供方，地址是已连接的地址加 /client-update/（第 5.1 节）：
//   - autoDownload 关闭：检查到新版本后不自动下载，用户点「更新客户端」才下载（第 5.2 节第 1 步）。
//   - allowDowngrade 开启：客户端比服务新时同样更新，降到服务提供的版本（第 5.2 节）。
//   - 读取 latest.yml，发布版本号与客户端不同才继续（第 5.2 节第 2 步）：版本相同
//     electron-updater 的 isUpdateAvailable 返回 false，这里按「没有可更新的版本」报告。
//   - 下载按 blockmap 差分，失败时 electron-updater 内部改为完整下载；下载后校验 latest.yml
//     中的 SHA-512（第 5.2 节第 3 步、第 5.3 节），校验不通过以错误结束。
//   - 安装：退出客户端，静默运行安装程序，安装完成以后启动新版本（第 5.2 节第 4 步），
//     由 quitAndInstall(true, true) 完成；安装不改变 Yudao 服务，服务继续运行。
//
// 更新失败（下载中断、校验失败）与 Yudao 服务没有提供安装包（/client-update/ 返回 404）
// 都交给更新页显示原因与「重试」（第 5.2 节）。

import { NsisUpdater } from "electron-updater";
import { appendFileSync } from "node:fs";

// Yudao 服务没有提供安装包（/client-update/ 返回 404，或打包内缺少更新配置）时给用户看的原因（第 5.2 节）
export const NO_INSTALLER_MESSAGE = "控制主机没有提供客户端安装包";
// latest.yml 与安装程序地址在已连接的地址之下（设计说明第 5.2 节第 1 步）
export const UPDATE_PATH = "/client-update/";

export type UpdatePhase = "checking" | "downloading" | "downloaded" | "installing" | "none" | "failed";

export type UpdateProgress = {
  phase: UpdatePhase;
  // 下载进度百分比（0 至 100），仅在 downloading 时给出
  percent?: number;
  // 目标发布版本号（latest.yml 中的版本），检查到以后给出
  version?: string;
  // 失败原因（phase 为 failed 时给出）
  message?: string;
};

export type UpdateRun = {
  phase: UpdatePhase;
  version: string;
  message: string;
};

export type UpdateReporter = (progress: UpdateProgress) => void;

// 更新地址：已连接的地址加 /client-update/（设计说明第 5.2 节第 1 步）。
// 去掉地址末尾的斜杠，避免出现两条斜杠
export function updateFeedUrl(address: string): string {
  return `${address.replace(/\/+$/, "")}${UPDATE_PATH}`;
}

// 把 electron-updater 抛出的错误转成给用户看的一句话。下载被中断、校验失败与没有安装包
// （404）都要写明原因（设计说明第 5.2 节）；其余错误保留原始信息，便于排查
export function describeUpdateError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  // latest.yml 请求得到 404 时 electron-updater 报 HttpError（状态码在错误对象上），
  // 或包成 ERR_UPDATER_CHANNEL_FILE_NOT_FOUND（状态码丢失，见 GenericProvider.getLatestVersion）；
  // 打包缺少更新配置时 app-update.yml 读不到，同样按「没有提供安装包」报告
  // （第 5.1 节：从源码运行返回 404）
  const code = (error as { code?: unknown } | null)?.code;
  const statusCode = (error as { statusCode?: unknown } | null)?.statusCode;
  if (statusCode === 404 || code === "ERR_UPDATER_CHANNEL_FILE_NOT_FOUND" || code === "HTTP_ERROR_404") {
    return NO_INSTALLER_MESSAGE;
  }
  if (/ENOENT|app-update\.yml|Cannot find channel/i.test(message)) {
    return NO_INSTALLER_MESSAGE;
  }
  return message;
}

// 配置 electron-updater（过程第 5.2 节）：generic 提供方、地址跟随当前连接、关闭自动下载、
// 开启降级。更新的每一步由 runUpdate 触发，不使用 electron-updater 的自动流程
export function configureUpdater(feedUrl: string): NsisUpdater {
  const updater = new NsisUpdater();
  updater.setFeedURL({ provider: "generic", url: feedUrl, channel: "latest" });
  updater.autoDownload = false;
  updater.allowDowngrade = true;
  updater.allowPrerelease = false;
  // 端到端测试从安装目录之外运行未打包的客户端：让 electron-updater 读取我们写好的
  // app-update.yml 并运行完整的检查与下载流程。打包运行的客户端不需要它
  if (process.env.YUDAO_UPDATE_DEV_CONFIG) {
    updater.forceDevUpdateConfig = true;
  }
  // 测试用日志：把 electron-updater 的每一步写到文件，便于核对检查、差分下载与校验
  if (process.env.YUDAO_UPDATE_LOG) {
    const logPath = process.env.YUDAO_UPDATE_LOG;
    const write = (level: string) => (message?: unknown) =>
      appendFileSync(logPath, `${level} ${String(message)}\n`);
    updater.logger = { info: write("INFO"), warn: write("WARN"), error: write("ERROR"), debug: write("DEBUG") };
  }
  return updater;
}

// 执行一次更新（设计说明第 5.2 节）：检查、下载（差分失败改完整下载、校验 SHA-512）、
// 退出客户端并静默安装、安装完成后启动新版本。每一步经 report 报告给界面
export async function runUpdate(feedUrl: string, report: UpdateReporter): Promise<UpdateRun> {
  report({ phase: "checking" });
  const updater = configureUpdater(feedUrl);
  updater.on("download-progress", (progress) => {
    report({ phase: "downloading", percent: Math.round(progress.percent) });
  });
  let result;
  try {
    result = await updater.checkForUpdates();
  } catch (error) {
    const message = describeUpdateError(error);
    report({ phase: "failed", message });
    return { phase: "failed", version: "", message };
  }
  if (result === null) {
    // 打包运行的检查被跳过（开发目录且没有更新配置）：按没有可更新的版本报告
    report({ phase: "none" });
    return { phase: "none", version: "", message: "" };
  }
  const version = result.updateInfo.version;
  // latest.yml 的发布版本号与客户端相同：没有要更新的版本（设计说明第 5.2 节第 2 步）
  if (!result.isUpdateAvailable) {
    report({ phase: "none", version });
    return { phase: "none", version, message: "" };
  }
  try {
    report({ phase: "downloading", percent: 0, version });
    // autoDownload 关闭，checkForUpdates 不开始下载（downloadPromise 为 null，设计说明第 5.2 节第 1 步）；
    // 用户点「更新客户端」以后在这里开始下载。差分失败时 electron-updater 内部改为完整下载，
    // 下载后校验 latest.yml 中的 SHA-512
    await updater.downloadUpdate();
  } catch (error) {
    const message = describeUpdateError(error);
    report({ phase: "failed", version, message });
    return { phase: "failed", version, message };
  }
  report({ phase: "downloaded", version });
  // 下载完成以后退出客户端，静默运行安装程序，安装完成以后启动新版本并重新连接（第 5.2 节第 4 步）。
  // 服务的进程与客户端无关（ADR-0023），安装不改变 Yudao 服务
  report({ phase: "installing", version });
  setImmediate(() => {
    updater.quitAndInstall(true, true);
  });
  return { phase: "installing", version, message: "" };
}
