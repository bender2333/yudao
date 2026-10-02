// 主进程：注册 yudao:// 协议、创建窗口、常驻托盘、保存连接设置（设计说明第 4.5 节，
// 原型 v8 设计说明第 3.4 节）。本工单中服务已经运行时客户端直接连接；服务的启动与停止、
// 托盘菜单的「停止 Yudao」「退出客户端」与登录时启动由 #207 实现。

import { app, BrowserWindow } from "electron";
import { serveRendererProtocol } from "./protocol";
import { createMainWindow, registerIpc } from "./window";
import { createTray, notificationLog, trayCount, type TrayController } from "./tray";

// 端到端测试读取托盘数量与已发出的通知（与 decisions.list 中等待回答的数量核对）；
// 主进程把这两个只读入口挂到全局，不参与界面逻辑
(globalThis as { yudaoTrayCount?: () => number }).yudaoTrayCount = trayCount;
(globalThis as { yudaoNotifications?: () => unknown[] }).yudaoNotifications = notificationLog;

// 端到端测试：测试传入独立的用户数据目录，客户端不写用户已经安装的那一份（工单验收第 7 项同口径）
if (process.env.YUDAO_E2E_USER_DATA) {
  app.setPath("userData", process.env.YUDAO_E2E_USER_DATA);
}

// 客户端同一时刻只有一个进程：第二个实例交给已有实例处理并退出
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  let window: BrowserWindow | null = null;
  let tray: TrayController | null = null;
  let quitting = false;

  const windowSize = (): { width: number; height: number } => ({
    width: Number(process.env.YUDAO_E2E_WIDTH) || 1440,
    height: Number(process.env.YUDAO_E2E_HEIGHT) || 900,
  });

  const show = (): void => {
    if (window === null || window.isDestroyed()) {
      window = createMainWindow(windowSize());
      // 关闭窗口只隐藏窗口，保留托盘与事件流连接（设计说明第 4.5 节）
      window.on("close", (event) => {
        if (!quitting) {
          event.preventDefault();
          window?.hide();
        }
      });
    }
    window.show();
    window.focus();
  };

  app.on("second-instance", () => show());

  // 端到端测试用的隐藏窗口入口：与关闭按钮的效果一致（隐藏而不销毁，事件流连接保留）
  (globalThis as { yudaoHideWindow?: () => void }).yudaoHideWindow = () => window?.hide();

  void app.whenReady().then(() => {
    serveRendererProtocol();
    registerIpc();
    show();
    tray = createTray({ onOpen: show });
    tray.start();
  });

  // 常驻托盘：窗口全部关闭时不退出
  app.on("window-all-closed", () => undefined);

  app.on("before-quit", () => {
    quitting = true;
    tray?.stop();
  });

  app.on("activate", () => show());
}
