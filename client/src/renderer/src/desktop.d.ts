// 预加载脚本经 contextBridge 暴露的接口的渲染进程声明（src/preload/index.ts 的 DesktopApi）。

export type ConnectionSettings = {
  kind: "local" | "lan";
  address: string;
  token: string;
};

export type DesktopApi = {
  getSettings: () => Promise<ConnectionSettings>;
  saveSettings: (value: ConnectionSettings) => Promise<boolean>;
  notify: (title: string, body: string) => Promise<boolean>;
  setTrayCount: (count: number) => Promise<boolean>;
};

import type { FloorTestHooks } from "./pixel/floor/view";

declare global {
  interface Window {
    yudao: DesktopApi;
    __floorViewForTest?: FloorTestHooks;
  }
}
