// 预加载脚本：对渲染进程暴露受限的接口（连接设置、连接本机时的本机服务管理、系统通知、
// 托盘数量与登录时启动），不暴露 Node 能力（window.ts 的 contextIsolation 与 sandbox 已开启）。

import { contextBridge, ipcRenderer } from "electron";

export type ConnectionSettings = {
  kind: "local" | "lan";
  address: string;
  token: string;
  allowLan: boolean;
};

export type LoginItemSettings = {
  openAtLogin: boolean;
};

// 更新页的进度（设计说明第 5.2 节）：主进程每走一步经 IPC 报告一次
export type UpdateProgress = {
  phase: "checking" | "downloading" | "downloaded" | "installing" | "none" | "failed";
  percent?: number;
  version?: string;
  message?: string;
};

// 本机服务的启动结果（设计说明第 4.3 节、工单 #296）：三种情况分开，界面分别给安装命令、
// 失败原因与服务日志的位置
export type LocalServiceStart = {
  kind: "started" | "no-command" | "failed";
  reason: string;
  logPath: string;
};

const api = {
  getSettings: (): Promise<ConnectionSettings> => ipcRenderer.invoke("yudao:settings:get"),
  saveSettings: (value: ConnectionSettings): Promise<boolean> => ipcRenderer.invoke("yudao:settings:set", value),
  notify: (title: string, body: string, decisionId?: string | null): Promise<boolean> =>
    ipcRenderer.invoke("yudao:notify", title, body, decisionId ?? null),
  setTrayCount: (count: number): Promise<boolean> => ipcRenderer.invoke("yudao:tray-count", count),
  setConnectedLocal: (local: boolean): Promise<boolean> => ipcRenderer.invoke("yudao:connected-local", local),
  // 本机服务管理（设计说明第 4.3 节）：没有运行时启动它，最多等待 30 秒；allowLan 为真时带上
  // `--access lan --host 0.0.0.0`。kind 为 started 表示服务可用；no-command 表示没有找到 yudao 命令，
  // 界面显示安装命令；failed 表示命令找到了但服务没有起来，界面显示原因与服务日志的位置
  startLocalService: (allowLan: boolean): Promise<LocalServiceStart> =>
    ipcRenderer.invoke("yudao:local-service:start", allowLan),
  stopLocalService: (): Promise<{ stopped: boolean; runningRuns: number; message: string }> =>
    ipcRenderer.invoke("yudao:local-service:stop"),
  // 访问方式与「允许局域网访问」开关不同时使用：先停止再按开关启动（设计说明第 4.3 节）
  restartLocalService: (allowLan: boolean): Promise<{ stopped: boolean; runningRuns: number; message: string }> =>
    ipcRenderer.invoke("yudao:local-service:restart", allowLan),
  getLoginItem: (): Promise<LoginItemSettings> => ipcRenderer.invoke("yudao:login-item:get"),
  setLoginItem: (openAtLogin: boolean): Promise<LoginItemSettings> =>
    ipcRenderer.invoke("yudao:login-item:set", openAtLogin),
  // 客户端的发布版本号：更新页写明两边的发布版本号
  getClientVersion: (): Promise<string> => ipcRenderer.invoke("yudao:client-version"),
  // 更新（设计说明第 5.2 节）：传入更新页当前连接的地址，主进程按地址加 /client-update/ 更新。
  // 每一步经 onProgress 回调报告（检查、下载百分比、下载完成、安装、失败原因）
  startUpdate: (address: string): Promise<{ phase: string; version: string; message: string }> =>
    ipcRenderer.invoke("yudao:update:start", address),
  onUpdateProgress: (listener: (progress: UpdateProgress) => void): (() => void) => {
    const handler = (_event: unknown, progress: UpdateProgress): void => listener(progress);
    ipcRenderer.on("yudao:update:progress", handler);
    return () => ipcRenderer.removeListener("yudao:update:progress", handler);
  },
  // 系统通知被点击：主进程恢复窗口后发出。决定标识不为空时界面跳到首页并定位到对应的决定卡片
  // （设计说明第 5.7 节、工单 #296）
  onNotifyClick: (listener: (decisionId: string | null) => void): (() => void) => {
    const handler = (_event: unknown, decisionId: string | null): void => listener(decisionId);
    ipcRenderer.on("yudao:notify-click", handler);
    return () => ipcRenderer.removeListener("yudao:notify-click", handler);
  },
};

contextBridge.exposeInMainWorld("yudao", api);

export type DesktopApi = typeof api;
