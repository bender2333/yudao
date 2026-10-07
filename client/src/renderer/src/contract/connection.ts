// 连接：读取能力清单并核对接口版本（应用层与接口层设计说明第 6.1 节）。地址是页面自己的来源
// （网页界面的提供与发布设计说明第 5.1 节）。相同时返回能力清单；不同时返回两份版本，不打开任何页面、不执行命令。

import { type Client, type ClientOptions, createClient, createConfig } from "../api/generated/client";
import { capabilities as fetchCapabilities } from "../api/generated/sdk.gen";
import type { Capabilities } from "../api/generated/types.gen";
import { CLIENT_API_VERSION } from "../api/interface-version";

export type Connection =
  | { state: "connected"; address: string; capabilities: Capabilities }
  | { state: "outdated"; address: string; clientVersion: number; serverVersion: number; serverRelease: string }
  | { state: "failed"; address: string; message: string };

// 一次连接建立的接口访问对象：所有查询与命令都经它发出请求，baseUrl 由地址决定
export type Interface = {
  baseUrl: string;
  client: Client;
};

export function interfaceFor(address: string): Interface {
  return { baseUrl: address, client: createClient(createConfig<ClientOptions>({ baseUrl: address })) };
}

export async function connect(address: string): Promise<Connection> {
  const { client } = interfaceFor(address);
  let raw: unknown;
  try {
    raw = (await fetchCapabilities({ client })).data;
  } catch (error) {
    return { state: "failed", address, message: error instanceof Error ? error.message : String(error) };
  }
  if (raw === undefined || typeof raw !== "object" || raw === null || !("deployment" in raw)) {
    // 请求没有得到能力清单（地址不通、被跨源策略拦下、或应答不是能力清单）：
    // 按连接失败报告，不把其他形状的应答当成能力清单用
    return { state: "failed", address, message: "没有取到能力清单" };
  }
  const deployment = raw.deployment;
  if (typeof deployment !== "object" || deployment === null || !("api_version" in deployment)
      || typeof deployment.api_version !== "number" || !("version" in deployment)
      || typeof deployment.version !== "string") {
    return { state: "failed", address, message: "没有取到能力清单" };
  }
  // 进入已连接只用了 deployment 的两个字段（上面已核对类型）；完整合同由服务端保证
  const capabilities = raw as Capabilities;
  const serverVersion = deployment.api_version;
  if (serverVersion !== CLIENT_API_VERSION) {
    return { state: "outdated", address, clientVersion: CLIENT_API_VERSION, serverVersion,
             serverRelease: deployment.version };
  }
  return { state: "connected", address, capabilities };
}
