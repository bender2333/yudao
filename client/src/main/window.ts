// 主窗口：经 yudao://app/ 加载界面（来源固定为 yudao://app），初始化尺寸 1440×900，
// 宽度不足时界面自行适配（原型 v8 设计说明第 3 节、工单验收的 390×844）。
// 预加载脚本对渲染进程暴露受限的接口：连接设置的读写、系统通知与托盘数量（不暴露 Node 能力）。

import { BrowserWindow, ipcMain } from "electron";
import { join } from "node:path";
import { RENDERER_ORIGIN } from "./protocol";
import { defaultSettings, loadSettings, saveSettings, type ConnectionSettings } from "./settings";
import { notify, setTrayCount } from "./tray";

export const SETTINGS_GET = "yudao:settings:get";
export const SETTINGS_SET = "yudao:settings:set";
export const NOTIFY = "yudao:notify";
export const TRAY_COUNT = "yudao:tray-count";

export function createMainWindow(size: { width: number; height: number }): BrowserWindow {
  const window = new BrowserWindow({
    width: size.width,
    height: size.height,
    minWidth: 390,
    minHeight: 640,
    show: false,
    title: "Yudao",
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  // 开发时 electron-vite 把渲染进程的 Vite 开发服务器地址放在这个变量里，界面从它加载
  // （参照 OpenCode 0027387 packages/desktop/src/main/windows.ts:334-343）；没有这个变量时
  // 界面走注册过的 yudao://app 协议，来源固定为 yudao://app（接口层只放行这一个来源）
  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (devUrl) {
    void window.loadURL(new URL("index.html", devUrl).toString());
  } else {
    void window.loadURL(`${RENDERER_ORIGIN}/index.html`);
  }
  return window;
}

// 渲染进程与主进程之间只有这三件事：连接设置、系统通知、托盘图标的数量（设计说明第 4.5、5.7 节）
export function registerIpc(): void {
  ipcMain.handle(SETTINGS_GET, () => loadSettings());
  ipcMain.handle(SETTINGS_SET, (_event, value: ConnectionSettings) => {
    saveSettings(value ?? defaultSettings());
    return true;
  });
  ipcMain.handle(NOTIFY, (_event, title: string, body: string) => {
    notify(title, body);
    return true;
  });
  ipcMain.handle(TRAY_COUNT, (_event, count: number) => {
    setTrayCount(count);
    return true;
  });
}
