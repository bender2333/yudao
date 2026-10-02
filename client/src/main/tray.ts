// 托盘：客户端常驻系统托盘，窗口关闭时保留（设计说明第 4.5、5.7 节）。
// 托盘图标显示待决定的数量；出现新的决定请求等事件时发出系统通知。
// 托盘菜单的「停止 Yudao」「退出客户端」与登录时启动由 #207 实现，本工单只建立「打开窗口」。
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

export type NotificationRecord = { title: string; body: string; at: number };

const notifications: NotificationRecord[] = [];

export function notificationLog(): NotificationRecord[] {
  return notifications;
}

export function notify(title: string, body: string): void {
  notifications.push({ title, body, at: Date.now() });
  if (!Notification.isSupported()) {
    return;
  }
  new Notification({ title, body }).show();
}

export function createTray(options: { onOpen: () => void }): TrayController {
  return {
    start: () => {
      tray = new Tray(iconFor(0));
      tray.setToolTip("Yudao");
      tray.setContextMenu(Menu.buildFromTemplate([{ label: "打开窗口", click: options.onOpen }]));
      tray.on("click", options.onOpen);
    },
    stop: () => {
      tray?.destroy();
      tray = null;
    },
  };
}
