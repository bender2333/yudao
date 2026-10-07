// 托盘：客户端常驻系统托盘，窗口关闭时保留（设计说明第 4.5、5.7 节）。
// 托盘图标显示待决定的数量；出现新的决定请求等事件时发出系统通知。
// 托盘菜单：「打开窗口」「停止 Yudao」（只在连接本机时出现）「退出客户端」。
// 图标由 scripts/make-tray-icons.mjs 生成到 resources/，数量为 0 时用基础图标。

import { app, Menu, nativeImage, Notification, Tray } from "electron";
import { join } from "node:path";

export type TrayController = {
  start: () => void;
  stop: () => void;
};

let tray: Tray | null = null;
// 最近一次设置的数量：供端到端测试核对托盘图标与 decisions.list 一致（不参与界面逻辑）
let lastCount = 0;

export function trayCount(): number {
  return lastCount;
}

function iconFor(count: number): Electron.NativeImage {
  const name = count > 0 ? `tray-${Math.min(9, count)}.png` : "tray.png";
  return nativeImage.createFromPath(join(app.getAppPath(), "resources", name));
}

// 托盘图标显示待决定的数量；数量为 0 时只用基础图标（原型 v8 设计说明第 4.1 节）
export function setTrayCount(count: number): void {
  lastCount = count;
  if (tray === null) {
    return;
  }
  tray.setToolTip(count > 0 ? `Yudao：${count} 项待你决定` : "Yudao");
  tray.setImage(iconFor(count));
}

export type NotificationRecord = { title: string; body: string; at: number; decisionId: string | null };

const notifications: NotificationRecord[] = [];

export function notificationLog(): NotificationRecord[] {
  return notifications;
}

// 系统通知（设计说明第 5.7 节）：决定请求带决定标识，点击通知时恢复窗口并定位到首页的
// 对应决定卡片（工单 #296）；其它通知只恢复窗口。动作由 index.ts 装入（与托盘菜单同一做法）
export function notify(title: string, body: string, decisionId: string | null = null): void {
  notifications.push({ title, body, at: Date.now(), decisionId });
  if (!Notification.isSupported()) {
    return;
  }
  const notification = new Notification({ title, body });
  notification.on("click", () => menuActions.onNotificationClick(decisionId));
  notification.show();
}


// 端到端测试点击系统通知：与用户点击走同一条路径（恢复窗口、定位决定卡片）。
// 系统通知在测试环境里可能不可显示，通知记录仍然保留
export function clickNotification(index: number): string | null {
  const record = notifications[index];
  if (record === undefined) {
    return null;
  }
  menuActions.onNotificationClick(record.decisionId);
  return record.decisionId;
}

// 连接本机与否由渲染进程连接后经 IPC 告知，切换连接时重新构建菜单（设计说明第 4.5 节）
let connectedLocal = false;
// 最近构建的托盘菜单：端到端测试按标签点真实菜单项
let currentMenu: Menu | null = null;

export function setTrayConnectedLocal(local: boolean): void {
  if (local === connectedLocal) {
    return;
  }
  connectedLocal = local;
  if (tray === null) {
    return;
  }
  tray.setContextMenu(buildMenu());
}



function buildMenu(): Menu {
  const menu = Menu.buildFromTemplate([
    { label: "打开窗口", click: () => menuActions.onOpen() },
    { label: "停止 Yudao", visible: connectedLocal, click: () => menuActions.onStop() },
    { type: "separator" },
    { label: "退出客户端", click: () => menuActions.onQuit() },
  ]);
  currentMenu = menu;
  return menu;
}

// 端到端测试按标签点真实菜单项：与用户点托盘菜单走同一条路径（不另开动作入口）
export function trayMenuLabels(): { label: string; visible: boolean }[] {
  if (currentMenu === null) {
    return [];
  }
  return currentMenu.items.map((item) => ({ label: item.label, visible: item.visible }));
}

export function clickTrayMenu(label: string): boolean {
  const item = currentMenu?.items.find((entry) => entry.label === label);
  if (item === undefined || !item.visible) {
    return false;
  }
  item.click();
  return true;
}

// 托盘与通知的动作由 index.ts 装入：托盘模块只管菜单与通知本身，不直接操作窗口
const menuActions: {
  onOpen: () => void;
  onStop: () => void;
  onQuit: () => void;
  onNotificationClick: (decisionId: string | null) => void;
} = { onOpen: () => undefined, onStop: () => undefined, onQuit: () => undefined, onNotificationClick: () => undefined };

export function createTray(actions: {
  onOpen: () => void;
  onStop: () => void;
  onQuit: () => void;
  onNotificationClick: (decisionId: string | null) => void;
}): TrayController {
  menuActions.onOpen = actions.onOpen;
  menuActions.onStop = actions.onStop;
  menuActions.onQuit = actions.onQuit;
  menuActions.onNotificationClick = actions.onNotificationClick;
  return {
    start: () => {
      tray = new Tray(iconFor(0));
      tray.setToolTip("Yudao");
      tray.setContextMenu(buildMenu());
      tray.on("click", actions.onOpen);
    },
    stop: () => {
      tray?.destroy();
      tray = null;
    },
  };
}
