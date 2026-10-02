// 连接：读取能力清单并核对接口版本（应用层与接口层设计说明第 6.1 节）。
// 相同时返回能力清单；不同时返回更新页需要的两份版本，不打开任何页面、不执行命令。

import { type Client, type ClientOptions, createClient, createConfig } from "../api/generated/client";
import { capabilities as fetchCapabilities } from "../api/generated/sdk.gen";
import type { Capabilities } from "../api/generated/types.gen";
import { CLIENT_API_VERSION } from "../api/interface-version";
import type { ConnectionSettings } from "./settings";
import { effectiveAddress } from "./settings";

export type Connection =
  | { state: "connected"; address: string; capabilities: Capabilities }
  | { state: "outdated"; address: string; clientVersion: number; serverVersion: number }
  | { state: "failed"; address: string; message: string };

// 一次连接建立的接口访问对象：所有查询与命令都经它发出请求，baseUrl 由地址决定
export type Interface = {
  baseUrl: string;
  client: Client;
};

export function interfaceFor(address: string): Interface {
  return { baseUrl: address, client: createClient(createConfig<ClientOptions>({ baseUrl: address })) };
}

export async function connect(settings: ConnectionSettings): Promise<Connection> {
  const address = effectiveAddress(settings);
  const { client } = interfaceFor(address);
  let capabilities: Capabilities | undefined;
  try {
    capabilities = (await fetchCapabilities({ client })).data as Capabilities | undefined;
  } catch (error) {
    return { state: "failed", address, message: error instanceof Error ? error.message : String(error) };
  }
  if (capabilities === undefined) {
    // 请求没有得到能力清单（地址不通、被跨源策略拦下等）：按连接失败报告，不把 undefined 当成能力清单用
    return { state: "failed", address, message: "没有取到能力清单" };
  }
  const serverVersion = capabilities.deployment.api_version;
  if (serverVersion !== CLIENT_API_VERSION) {
    return { state: "outdated", address, clientVersion: CLIENT_API_VERSION, serverVersion };
  }
  return { state: "connected", address, capabilities };
}
