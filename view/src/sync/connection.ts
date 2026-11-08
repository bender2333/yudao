// 画面的连接与接口访问（画面与播放 docs/design/visualization.md「分层与边界」的同步层；
// 应用层与接口层 docs/design/app-and-interface.md「能力清单」「访问方式与认证」「接口路径」）。
//
// 画面由 Yudao 服务在同一来源下提供，查询、命令与事件流都不跨来源；地址就是画面自己的来源。
// 局域网访问方式下的访问令牌放在请求头里，与页面相同；本机访问方式不需要令牌。
// 接口版本只记录、不在这里拦：Yudao 比画面新时画面照常工作（新的事件进缺口清单），
// 比画面旧时由壳写明两边各是第几版、缺的那部分不画（画面与播放 docs/design/visualization.md「接口版本不一致」）。
//
// 查询与命令走接口合同里登记的两条路径（GET /api/queries/<名称>、POST /api/commands/<名称>），
// 形状由画面自己从接口描述生成的类型给出（src/api/generated/）；不导入 client/ 的任何文件。

import type { Capabilities } from "../api/generated/types.gen.ts";
import { VIEW_API_VERSION } from "../api/interface-version.ts";

/** 一次查询的结果：应用层给出的快照（位置与数据）。 */
export type Snapshot<T> = {
  /** 快照来自的全局位置：画面合同的状态带它（回链与重放都按位置读取）。 */
  position: number;
  data: T;
};

/** 按名称发出一次查询。同步层与壳都经这一份接口读事实。 */
export type QueryRunner = <T>(name: string, params?: Record<string, unknown>) => Promise<Snapshot<T>>;

/** 一条命令的结果：受理回执，或者服务拒绝时的一句话。 */
export type CommandOutcome =
  | {
    ok: true;
    accepted: {
      command_id?: string;
      position?: number;
      /** 同一个 command_id 之前已经受理过：服务返回原来的位置，只生效一次。 */
      duplicate?: boolean;
      refs?: Record<string, unknown>;
    };
  }
  | { ok: false; message: string };

/** 按名称发出一次命令；只发能力清单里列出的命令由壳保证。 */
export type CommandRunner = (name: string, body: Record<string, unknown>) => Promise<CommandOutcome>;

/** 一次连接可以用的接口与它带的身份。 */
export interface InterfaceAccess {
  baseUrl: string;
  /**
   * 连接带的身份：局域网访问方式的访问令牌，本机访问方式为空串。
   * 查询与命令都经这一份接口发出，事件流也用同一个身份（与页面相同）。
   */
  identity: string;
  query: QueryRunner;
  command: CommandRunner;
}

/** 连接的结果。 */
export type Connection =
  | {
    state: "connected";
    address: string;
    access: InterfaceAccess;
    capabilities: Capabilities;
    /** 画面生成类型时的接口版本与服务的接口版本（只记录，不拦）。 */
    versions: { view: number; server: number };
  }
  | { state: "unauthorized"; address: string }
  | { state: "failed"; address: string; message: string };

/** 取接口用的 fetch：单元测试可以换成替身。 */
export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface ConnectionDeps {
  fetch?: FetchLike;
  /** 事件流读到的地址（默认为空串：查询与命令用绝对地址，由服务自己给地址）。 */
  baseUrl?: string;
}

/** 请求头：局域网访问方式下的令牌放在 Authorization 里（不出现在地址里）。 */
function headersFor(token: string, json = false): Record<string, string> {
  return {
    ...(json ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

/** 查询的地址：名称就是注册表里的名称，参数按接口合同的写法带在查询串里。 */
export function queryUrl(baseUrl: string, name: string, params?: Record<string, unknown>): string {
  const url = new URL(`${baseUrl}/api/queries/${name}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const item of value) url.searchParams.append(key, String(item));
    } else {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** 命令被拒绝时的一句话：原因与说明取自拒绝的响应体（应用层与接口层 docs/design/app-and-interface.md「命令」）。 */
function rejectionText(name: string, payload: unknown): string {
  if (payload !== null && typeof payload === "object") {
    const rejected = payload as { reason?: unknown; message?: unknown; detail?: unknown };
    const parts = [rejected.message, rejected.detail]
      .filter((value): value is string => typeof value === "string" && value.trim() !== "");
    if (parts.length > 0) return parts.join("：");
    if (typeof rejected.reason === "string" && rejected.reason !== "") return rejected.reason;
  }
  return `命令 ${name} 被拒绝`;
}

/**
 * 一份接口访问对象：所有查询与命令都经它发出请求，地址与身份由连接给出。
 * 地址是画面自己的来源（服务在同一来源下提供画面），因此不需要跨来源的响应头，也不需要 CORS。
 */
export function interfaceFor(address: string, token = "", deps: ConnectionDeps = {}): InterfaceAccess {
  const doFetch: FetchLike = deps.fetch ?? ((input, init) => fetch(input, init));
  const query: QueryRunner = async <T>(name: string, params?: Record<string, unknown>): Promise<Snapshot<T>> => {
    const response = await doFetch(queryUrl(address, name, params), { headers: headersFor(token) });
    if (!response.ok) {
      throw new Error(`查询 ${name} 没有取到结果（HTTP ${response.status}）`);
    }
    const body = (await response.json()) as { position?: unknown; data?: unknown };
    if (typeof body.position !== "number" || !("data" in body)) {
      throw new Error(`查询 ${name} 的应答不是一份快照`);
    }
    return body as Snapshot<T>;
  };
  const command: CommandRunner = async (name: string, body: Record<string, unknown>): Promise<CommandOutcome> => {
    const response = await doFetch(`${address}/api/commands/${name}`, {
      method: "POST",
      headers: headersFor(token, true),
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      let payload: unknown = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      return { ok: false, message: rejectionText(name, payload) };
    }
    return { ok: true, accepted: (await response.json()) as Record<string, unknown> };
  };
  return { baseUrl: address, identity: token, query, command };
}

/**
 * 连上画面自己的来源：读取能力清单并核对它的形状。
 * 服务的接口版本与画面生成类型时的版本一起给出，由壳决定怎么写（不拦、不报错退出）。
 */
export async function connect(address: string, token = "", deps: ConnectionDeps = {}): Promise<Connection> {
  const doFetch: FetchLike = deps.fetch ?? ((input, init) => fetch(input, init));
  let response: Response;
  try {
    response = await doFetch(`${address}/api/capabilities`, { headers: headersFor(token) });
  } catch (error) {
    return { state: "failed", address, message: error instanceof Error ? error.message : String(error) };
  }
  if (response.status === 401) {
    // 局域网访问方式下没有令牌或令牌无效：服务回答 401，不附原因。画面据此显示填写令牌的入口
    return { state: "unauthorized", address };
  }
  if (!response.ok) {
    return { state: "failed", address, message: `没有取到能力清单（HTTP ${response.status}）` };
  }
  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    return { state: "failed", address, message: "没有取到能力清单" };
  }
  if (raw === null || typeof raw !== "object" || !("deployment" in raw)) {
    return { state: "failed", address, message: "没有取到能力清单" };
  }
  const deployment = (raw as { deployment: unknown }).deployment;
  if (typeof deployment !== "object" || deployment === null
      || !("api_version" in deployment) || typeof deployment.api_version !== "number"
      || !("boot_id" in deployment) || typeof deployment.boot_id !== "string"
      || !("version" in deployment) || typeof deployment.version !== "string") {
    return { state: "failed", address, message: "没有取到能力清单" };
  }
  return {
    state: "connected",
    address,
    access: interfaceFor(address, token, deps),
    capabilities: raw as Capabilities,
    versions: { view: VIEW_API_VERSION, server: deployment.api_version },
  };
}
