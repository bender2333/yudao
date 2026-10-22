// 连接：读取能力清单并核对接口版本（应用层与接口层设计说明第 6.1 节）。地址是页面自己的来源
// （网页界面的提供与发布设计说明第 5.1 节）。相同时返回能力清单；不同时返回两份版本，不打开任何页面、不执行命令。

import { type Client, type ClientOptions, createClient, createConfig } from "../api/generated/client";
import { capabilities as fetchCapabilities } from "../api/generated/sdk.gen";
import type { Capabilities } from "../api/generated/types.gen";
import { CLIENT_API_VERSION } from "../api/interface-version";
import { PAGE_RELEASE } from "./page-release";

export type Connection =
  | { state: "connected"; address: string; capabilities: Capabilities }
  | { state: "outdated"; address: string; clientVersion: number; serverVersion: number; serverRelease: string }
  | { state: "unauthorized"; address: string }
  | { state: "failed"; address: string; message: string };

// 同一会话里已经重载过（工单 #704）：服务与页面一直不匹配时不再反复重载，
// 而是给出该做什么的说明
const RELOAD_MARK = "yudao.page-reloaded";

function reloadedThisSession(): boolean {
  try {
    return window.sessionStorage.getItem(RELOAD_MARK) === "1";
  } catch {
    // 浏览器不给用会话存储时按没重载过处理（重载一次无害）
    return false;
  }
}

function markReloadedThisSession(): void {
  try {
    window.sessionStorage.setItem(RELOAD_MARK, "1");
  } catch {
    // 存不进去就当没记住：这一轮只会多重载一次
  }
}

// 一次连接建立的接口访问对象：所有查询与命令都经它发出请求，baseUrl 由地址决定
export type Interface = {
  baseUrl: string;
  client: Client;
};

export function interfaceFor(address: string, token = ""): Interface {
  // 局域网访问方式下每个请求都在请求头里带令牌（第 6.3 节）；令牌不出现在地址里
  const client = createClient(createConfig<ClientOptions>({
    baseUrl: address,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  }));
  return { baseUrl: address, client };
}

export async function connect(address: string, token = ""): Promise<Connection> {
  const { client } = interfaceFor(address, token);
  let raw: unknown;
  let response: Response | undefined;
  try {
    const fetched = await fetchCapabilities({ client });
    raw = fetched.data;
    response = fetched.response;
  } catch (error) {
    return { state: "failed", address, message: error instanceof Error ? error.message : String(error) };
  }
  // 局域网访问方式下没有令牌或令牌无效：服务按第 6.3 节回答 401，不附原因。
  // 页面据此显示填写令牌的表单；本机访问方式不会走到这里
  if (response !== undefined && response.status === 401) {
    return { state: "unauthorized", address };
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
  // 页面与服务同出一个发布（网页界面的提供与发布设计说明第 5.1 节）：服务的发布版本与页面构建时的
  // 版本不同时重新加载页面，取到与服务同一个版本的页面文件。每次连接都核对，包括服务重启以后的重新连接。
  // 接口版本不同时也重载一次（工单 #704）：接口一变，页面文件多半要重新构建过；重载取到新文件就用新的。
  // 同一会话只重载一次：页面与服务一直不匹配时（例如页面文件还没重建），不停重载只会一直闪。
  if (deployment.version !== PAGE_RELEASE || deployment.api_version !== CLIENT_API_VERSION) {
    if (!reloadedThisSession()) {
      markReloadedThisSession();
      window.location.reload();
    }
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


