// 客户端与它连接的 Yudao 服务的配置：地址、访问方式与访问令牌（令牌为 TODO，见设计说明第 6.3 节，
// 当前不发送）。保存在 Electron 的用户数据目录，由主进程经 IPC 提供读写；渲染进程不直接访问磁盘。

export type ConnectionKind = "local" | "lan";

export type ConnectionSettings = {
  // 「本机」时地址固定为 http://127.0.0.1:8765；「局域网」时是用户填写的控制主机地址
  kind: ConnectionKind;
  address: string;
  // 访问令牌：保留位置，当前不发送（TODO：令牌与 TLS）
  token: string;
  // 「允许局域网访问」（设计说明第 4.3 节）：只对「本机」一项有意义，默认关闭；打开时
  // 客户端启动服务带上 --access lan --host 0.0.0.0
  allowLan: boolean;
};

export const DEFAULT_LOCAL_ADDRESS = "http://127.0.0.1:8765";

export function defaultSettings(): ConnectionSettings {
  return { kind: "local", address: DEFAULT_LOCAL_ADDRESS, token: "", allowLan: false };
}

// 地址规范化：去掉末尾的斜杠，留下协议、主机与端口。地址不合法时就地抛出，由调用方显示原因
export function normalizeAddress(address: string): string {
  const trimmed = address.trim().replace(/\/+$/, "");
  if (trimmed.length === 0) {
    throw new Error("地址不能为空");
  }
  const parsed = new URL(trimmed);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("地址必须以 http:// 或 https:// 开头");
  }
  return parsed.origin;
}

// 客户端实际连接的地址：本机时固定回环地址，局域网时用规范化后的用户地址
export function effectiveAddress(settings: ConnectionSettings): string {
  if (settings.kind === "local") {
    return DEFAULT_LOCAL_ADDRESS;
  }
  return normalizeAddress(settings.address);
}
