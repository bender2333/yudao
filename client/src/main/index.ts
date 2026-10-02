// 主进程：注册 yudao:// 协议、创建窗口、常驻托盘、保存连接设置、登录时启动、管理本机
// Yudao 服务（设计说明第 4.3、4.5 节，原型 v8 设计说明第 3.4 节）。
// 退出客户端不停止 Yudao 服务（ADR-0023）：只有托盘菜单的「停止 Yudao」发本机停止请求。

import { app, BrowserWindow } from "electron";
import { stopLocalServiceConfirming } from "./local-service";
import { serveRendererProtocol } from "./protocol";
import { createMainWindow, registerIpc } from "./window";
import { clickTrayMenu, createTray, notificationLog, trayMenuLabels, trayCount, type TrayController } from "./tray";

// 端到端测试读取托盘数量与已发出的通知（与 decisions.list 中等待回答的数量核对）；
// 主进程把这两个只读入口挂到全局，不参与界面逻辑
(globalThis as { yudaoTrayCount?: () => number }).yudaoTrayCount = trayCount;
(globalThis as { yudaoNotifications?: () => unknown[] }).yudaoNotifications = notificationLog;

// Windows 的应用标识（AppUserModelId）决定「登录时启动客户端」写入注册表启动项时的值名，
// 也决定任务栏与通知的归属（设计说明第 4.5 节）；不设时 Electron 用 electron.app.Electron，
// 开发时同一台机器上的多个 Electron 应用会共用一条启动项并互相覆盖
app.setAppUserModelId("com.yudao.client");

// 端到端测试：测试传入独立的用户数据目录，客户端不写用户已经安装的那一份（工单验收第 7 项同口径）
if (process.env.YUDAO_E2E_USER_DATA) {
  const testName = process.env.YUDAO_E2E_USER_DATA.split(/[\\/]/).pop();
  // 测试用自己的应用标识与应用名：写入、读回与删除的启动项都只碰测试那一条
  app.setAppUserModelId(`com.yudao.client.e2e-${testName}`);
  app.setName(`Yudao-e2e-${testName}`);
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
  // 端到端测试按标签点托盘菜单项：菜单项不可见（连接的不是本机）时不动作，可见时执行它自己的动作
  // （与用户点菜单是同一条路径）。确认对话框由测试在主进程里替换 dialog.showMessageBox 应答，
  // 因此停止流程的读数量、确认与发停止请求都按真实代码运行
  (globalThis as { yudaoTrayClick?: (label: string) => unknown }).yudaoTrayClick = (label: string) => clickTrayMenu(label);
  (globalThis as { yudaoTrayMenuLabels?: () => { label: string; visible: boolean }[] }).yudaoTrayMenuLabels = trayMenuLabels;

  void app.whenReady().then(() => {
    serveRendererProtocol();
    registerIpc();
    show();
    tray = createTray({
      onOpen: show,
      onStop: () => void stopLocalServiceConfirming(),
      // 退出客户端不停止 Yudao 服务（ADR-0023）
      onQuit: () => app.quit(),
    });
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
