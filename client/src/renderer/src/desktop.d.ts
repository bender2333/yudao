// 预加载脚本经 contextBridge 暴露的接口的渲染进程声明（src/preload/index.ts 的 DesktopApi）。

export type ConnectionSettings = {
  kind: "local" | "lan";
  address: string;
  token: string;
  // 「允许局域网访问」（设计说明第 4.3 节）：只对「本机」一项有意义
  allowLan: boolean;
};

export type LocalServiceStart = {
  started: boolean;
  message: string;
};

export type LocalServiceStop = {
  stopped: boolean;
  runningRuns: number;
  message: string;
};

export type LoginItemSettings = {
  openAtLogin: boolean;
};

// 更新页的进度（设计说明第 5.2 节）：与 src/preload/index.ts 的 UpdateProgress 相同
export type UpdateProgress = {
  phase: "checking" | "downloading" | "downloaded" | "installing" | "none" | "failed";
  percent?: number;
  version?: string;
  message?: string;
};

export type UpdateRun = {
  phase: string;
  version: string;
  message: string;
};

export type DesktopApi = {
  getSettings: () => Promise<ConnectionSettings>;
  saveSettings: (settings: ConnectionSettings) => Promise<boolean>;
  notify: (title: string, body: string) => Promise<boolean>;
  setTrayCount: (count: number) => Promise<boolean>;
  // 托盘「停止 Yudao」只在连接本机时出现：连接状态由渲染进程告知主进程
  setConnectedLocal: (local: boolean) => Promise<boolean>;
  startLocalService: (allowLan: boolean) => Promise<LocalServiceStart>;
  stopLocalService: () => Promise<LocalServiceStop>;
  restartLocalService: (allowLan: boolean) => Promise<LocalServiceStop>;
  getLoginItem: () => Promise<LoginItemSettings>;
  setLoginItem: (openAtLogin: boolean) => Promise<LoginItemSettings>;
  // 客户端的发布版本号：更新页写明两边的发布版本号
  getClientVersion: () => Promise<string>;
  // 更新（设计说明第 5.2 节）：地址为更新页当前连接的地址，每一步经 onUpdateProgress 回调报告
  startUpdate: (address: string) => Promise<UpdateRun>;
  onUpdateProgress: (listener: (progress: UpdateProgress) => void) => () => void;
};

import type { FloorTestHooks } from "./pixel/floor/view";

declare global {
  interface Window {
    yudao: DesktopApi;
    __floorViewForTest?: FloorTestHooks;
  }
}
