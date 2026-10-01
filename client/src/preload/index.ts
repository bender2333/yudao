// 预加载脚本：对渲染进程暴露受限的接口（连接设置、系统通知与托盘数量），
// 不暴露 Node 能力（window.ts 的 contextIsolation 与 sandbox 已开启）。

import { contextBridge, ipcRenderer } from "electron";

export type ConnectionSettings = {
  kind: "local" | "lan";
  address: string;
  token: string;
};

const api = {
  getSettings: (): Promise<ConnectionSettings> => ipcRenderer.invoke("yudao:settings:get"),
  saveSettings: (value: ConnectionSettings): Promise<boolean> => ipcRenderer.invoke("yudao:settings:set", value),
  notify: (title: string, body: string): Promise<boolean> => ipcRenderer.invoke("yudao:notify", title, body),
  setTrayCount: (count: number): Promise<boolean> => ipcRenderer.invoke("yudao:tray-count", count),
};

contextBridge.exposeInMainWorld("yudao", api);

export type DesktopApi = typeof api;
