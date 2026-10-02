// 连接设置保存在 Electron 的用户数据目录（应用层与接口层设计说明第 4.5 节：客户端只保存自己的设置）。
// 卸载不删除 Yudao 服务的数据；这里只读写客户端自己的 connection.json。

import { app } from "electron";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export type ConnectionKind = "local" | "lan";

export type ConnectionSettings = {
  kind: ConnectionKind;
  address: string;
  // 访问令牌：保留位置，当前不发送（TODO：令牌与 TLS，设计说明第 6.3 节）
  token: string;
  // 「允许局域网访问」（设计说明第 4.3 节）：只对「本机」一项有意义，默认关闭，
  // 保存在客户端的设置中；打开时启动服务带 --access lan --host 0.0.0.0
  allowLan: boolean;
};

export const DEFAULT_LOCAL_ADDRESS = "http://127.0.0.1:8765";

export function defaultSettings(): ConnectionSettings {
  return { kind: "local", address: DEFAULT_LOCAL_ADDRESS, token: "", allowLan: false };
}

function settingsPath(): string {
  return join(app.getPath("userData"), "connection.json");
}

// 端到端测试用的预置连接设置：测试把后端地址放进环境变量，客户端启动时直接连过去（工单验收）
export function e2eBackendAddress(): string | null {
  const value = process.env.YUDAO_E2E_BACKEND;
  return value && value.length > 0 ? value : null;
}

export function loadSettings(): ConnectionSettings {
  const override = e2eBackendAddress();
  if (override !== null) {
    // 端到端测试连接的是另一台部署：不是「本机」，局域网开关不适用
    return { kind: "lan", address: override, token: "", allowLan: false };
  }
  try {
    const parsed = JSON.parse(readFileSync(settingsPath(), "utf8")) as Partial<ConnectionSettings>;
    return {
      kind: parsed.kind === "lan" ? "lan" : "local",
      address: typeof parsed.address === "string" ? parsed.address : DEFAULT_LOCAL_ADDRESS,
      token: typeof parsed.token === "string" ? parsed.token : "",
      allowLan: parsed.allowLan === true,
    };
  } catch {
    // 文件不存在或内容损坏：回到默认设置（本机）
    return defaultSettings();
  }
}

export function saveSettings(value: ConnectionSettings): void {
  writeFileSync(settingsPath(), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}
