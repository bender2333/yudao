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

const api = {
  getSettings: (): Promise<ConnectionSettings> => ipcRenderer.invoke("yudao:settings:get"),
  saveSettings: (value: ConnectionSettings): Promise<boolean> => ipcRenderer.invoke("yudao:settings:set", value),
  notify: (title: string, body: string): Promise<boolean> => ipcRenderer.invoke("yudao:notify", title, body),
  setTrayCount: (count: number): Promise<boolean> => ipcRenderer.invoke("yudao:tray-count", count),
  setConnectedLocal: (local: boolean): Promise<boolean> => ipcRenderer.invoke("yudao:connected-local", local),
  // 本机服务管理（设计说明第 4.3 节）：没有运行时启动它，最多等待 30 秒；allowLan 为真时带上
  // `--access lan --host 0.0.0.0`。返回 started 为 true 表示服务可用，false 表示没有找到
  // yudao 命令，界面显示安装命令
  startLocalService: (allowLan: boolean): Promise<{ started: boolean; message: string }> =>
    ipcRenderer.invoke("yudao:local-service:start", allowLan),
  stopLocalService: (): Promise<{ stopped: boolean; runningRuns: number; message: string }> =>
    ipcRenderer.invoke("yudao:local-service:stop"),
  // 访问方式与「允许局域网访问」开关不同时使用：先停止再按开关启动（设计说明第 4.3 节）
  restartLocalService: (allowLan: boolean): Promise<{ stopped: boolean; runningRuns: number; message: string }> =>
    ipcRenderer.invoke("yudao:local-service:restart", allowLan),
  getLoginItem: (): Promise<LoginItemSettings> => ipcRenderer.invoke("yudao:login-item:get"),
  setLoginItem: (openAtLogin: boolean): Promise<LoginItemSettings> =>
    ipcRenderer.invoke("yudao:login-item:set", openAtLogin),
};

contextBridge.exposeInMainWorld("yudao", api);

export type DesktopApi = typeof api;
