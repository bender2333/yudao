// 主窗口：经 yudao://app/ 加载界面（来源固定为 yudao://app），初始化尺寸 1440×900，
// 宽度不足时界面自行适配（原型 v8 设计说明第 3 节、工单验收的 390×844）。
// 预加载脚本对渲染进程暴露受限的接口：连接设置的读写、本机服务的启动与停止、系统通知、
// 托盘数量与登录时启动（不暴露 Node 能力）。

import { app, BrowserWindow, ipcMain } from "electron";
import { join } from "node:path";
import { RENDERER_ORIGIN } from "./protocol";
import { restartLocalServiceConfirming, startYudaoService, stopLocalServiceConfirming } from "./local-service";
import { defaultSettings, loadSettings, saveSettings, type ConnectionSettings } from "./settings";
import { setTrayConnectedLocal, notify, setTrayCount } from "./tray";

export const SETTINGS_GET = "yudao:settings:get";
export const SETTINGS_SET = "yudao:settings:set";
export const NOTIFY = "yudao:notify";
export const TRAY_COUNT = "yudao:tray-count";
export const CONNECTED_LOCAL = "yudao:connected-local";
export const LOCAL_SERVICE_START = "yudao:local-service:start";
export const LOCAL_SERVICE_STOP = "yudao:local-service:stop";
export const LOCAL_SERVICE_RESTART = "yudao:local-service:restart";
export const LOGIN_ITEM_GET = "yudao:login-item:get";
export const LOGIN_ITEM_SET = "yudao:login-item:set";

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

// 渲染进程与主进程之间的接口：连接设置、本机服务的启动与停止、系统通知、托盘图标的数量
// 与登录时启动（设计说明第 4.3、4.5、5.7 节）
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
  ipcMain.handle(CONNECTED_LOCAL, (_event, local: boolean) => {
    setTrayConnectedLocal(local === true);
    return true;
  });
  ipcMain.handle(LOCAL_SERVICE_START, async (_event, allowLan: boolean) => {
    const started = await startYudaoService(allowLan === true);
    return started
      ? { started: true, message: "" }
      : { started: false, message: "没有找到 yudao 命令，用下面的命令安装 Yudao 服务：" };
  });
  // 界面里的「停止 Yudao」与托盘菜单的「停止 Yudao」走同一段代码：读运行中的事项数，
  // 大于 0 时先确认，再发本机停止请求（设计说明第 4.4、4.5 节）
  ipcMain.handle(LOCAL_SERVICE_STOP, () => stopLocalServiceConfirming());
  // 「重新启动」：访问方式与「允许局域网访问」开关不同时使用；先停止再按开关启动
  // （设计说明第 4.3 节）。有事项正在运行时先确认
  ipcMain.handle(LOCAL_SERVICE_RESTART, (_event, allowLan: boolean) => restartLocalServiceConfirming(allowLan === true));
  // 「登录时启动客户端」：写入当前用户的注册表启动项（HKCU 的 Run 键），不需要管理员权限。
  // 值名取 Windows 的应用标识（AppUserModelId），值数据是这个客户端的可执行文件；
  // 读回按同一标识查询，界面显示的始终是注册表里的实际状态
  ipcMain.handle(LOGIN_ITEM_GET, () => ({ openAtLogin: app.getLoginItemSettings().openAtLogin }));
  ipcMain.handle(LOGIN_ITEM_SET, (_event, openAtLogin: boolean) => {
    app.setLoginItemSettings({ openAtLogin: openAtLogin === true });
    return { openAtLogin: app.getLoginItemSettings().openAtLogin };
  });
}
