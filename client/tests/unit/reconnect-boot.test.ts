// 事件流断开以后重新连上时核对本次启动的身份（工单 #1159，应用层与接口层设计说明第 6.1 节）：
// 重连到 boot_id 不同的服务（服务重启）：重新读取能力清单，每个打开的查询都重新查询；
// 重连到 boot_id 相同的服务：不整页重读，照旧从原位置续上。
//
// 用例核对的是页面自己的连接生命周期（contract/client-app.ts）。不连网络、不起事件流：
// 读能力清单与打开事件流由测试注入的替身给出（ClientApp 的第三个构造参数）。
// 模块由 Vite 的模块服务器加载（与画面层的单元测试同一方式）：页面的合同模块按 Vite 的解析
// 写（省略扩展名、import.meta.env），node --test 自己的剥类型加载器读不了。

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer, type ViteDevServer } from "vite";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

type PageModule = {
  ClientApp: new (...args: unknown[]) => Page;
  bootIdentityChanged: (before: string | null, next: string | null) => boolean;
};

type Page = {
  open: (address: string, token?: string) => Promise<void>;
  viewSync: { open: (viewId: string, request: { query: string }, listener: () => void) => Promise<void> } | null;
  currentCapabilities: { deployment: { boot_id: string } } | null;
};

let server: ViteDevServer;
let page: PageModule;

before(async () => {
  server = await createServer({
    root: join(clientRoot, "src", "renderer"),
    // 单元测试文件之间并行运行：缓存目录与别的 Vite 测试分开，避免同时改写同一份缓存
    cacheDir: join(clientRoot, "node_modules", ".vite-reconnect-boot"),
    plugins: [],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
  });
  page = (await server.ssrLoadModule("/src/contract/client-app.ts")) as PageModule;
});

after(async () => {
  await server?.close();
});

/** 能力清单的替身：本工单用到 deployment.boot_id、queries（视图同步按它登记）与 decisions。 */
function capabilitiesWith(bootId: string) {
  return {
    deployment: { boot_id: bootId, log_id: "log-1", version: "0.1.1", api_version: 1, access: "local" },
    queries: [{ name: "catalog", changed_by: ["credential_changed"] }],
    commands: [],
    decisions: { event_types: [], kinds: [] },
    event_types: [],
    overlays: [],
    stream: { live: true, scopes: [] },
  };
}

/** 事件流替身：记下开始订阅的起点与被停掉的次数，并留着页面给的回调（测试据此模拟断开与重连）。 */
function fakeStream() {
  const handle = {
    starts: [] as number[],
    stops: 0,
    position: 0,
    handlers: null as null | {
      onConnected: (info: { reconnected: boolean }) => void;
      onInterrupted: () => void;
    },
    start(after: number) {
      handle.starts.push(after);
    },
    stop() {
      handle.stops += 1;
    },
  };
  return handle;
}

/**
 * 起一个页面：能力清单按 boots 依次给出（每次读取取下一个，用最后一个兜底），
 * 查询按名字计数，事件流用替身。
 */
async function pageWith(boots: string[]) {
  let reads = 0;
  const stream = fakeStream();
  const queries = new Map<string, number>();
  const addresses: string[] = [];
  const app = new page.ClientApp(
    async (_client: unknown, name: string) => {
      queries.set(name, (queries.get(name) ?? 0) + 1);
      return { position: 20, data: {} };
    },
    { onState() {}, onPendingDecisions() {} },
    {
      connect: async (address: string) => {
        addresses.push(address);
        const boot = boots[Math.min(reads, boots.length - 1)];
        reads += 1;
        return { state: "connected", address, capabilities: capabilitiesWith(boot) };
      },
      openStream: (_baseUrl: string, _scope: unknown, handlers: unknown) => {
        stream.handlers = handlers as typeof stream.handlers;
        return stream;
      },
    },
  );
  await app.open("http://127.0.0.1:9");
  return { app, stream, queries, addresses, reads: () => reads };
}

/** 页面打开一个视图：立刻查询一次并记下快照。 */
async function openView(app: Page): Promise<void> {
  await app.viewSync!.open("v", { query: "catalog" }, () => undefined);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test("重连到 boot_id 不同的服务：重新读取能力清单，每个打开的查询都重新查询", async () => {
  const { app, stream, queries, addresses, reads } = await pageWith(["boot-a", "boot-b"]);
  await openView(app);
  // 第一次连上不是重连：不做身份核对
  stream.handlers!.onConnected({ reconnected: false });
  await delay(20);
  assert.equal(reads(), 1);
  assert.equal(queries.get("catalog"), 1);

  // 断开以后重新连上：服务已经重启，启动身份不同
  stream.handlers!.onInterrupted();
  stream.handlers!.onConnected({ reconnected: true });
  await delay(50);

  // 能力清单重读了一次：页面上留着的是重启以后那一份
  assert.equal(reads(), 2);
  assert.equal(addresses[1], "http://127.0.0.1:9");
  assert.equal(app.currentCapabilities!.deployment.boot_id, "boot-b");
  // 每个打开的查询都重新读取（同一份视图重新查询）
  assert.equal(queries.get("catalog"), 2);
  // 从快照位置重新订阅：旧流停掉，新的从视图快照位置接上
  assert.equal(stream.stops, 1);
  assert.deepEqual(stream.starts, [0, 20]);
});

test("重连到 boot_id 相同的服务：不整页重读，照旧从原位置续上", async () => {
  const { app, stream, queries, reads } = await pageWith(["boot-a"]);
  await openView(app);
  stream.handlers!.onConnected({ reconnected: false });
  await delay(20);
  const before = app.currentCapabilities;

  stream.handlers!.onInterrupted();
  stream.handlers!.onConnected({ reconnected: true });
  await delay(50);

  // 同一次启动：能力清单照读一次（核对身份要读），但不换、不重新查询、不重新订阅（流自己按位置续传）
  assert.equal(reads(), 2);
  assert.equal(app.currentCapabilities, before);
  assert.equal(queries.get("catalog"), 1);
  assert.equal(stream.stops, 0);
  assert.deepEqual(stream.starts, [0]);
});

test("本次启动的身份是否变了：拿到的身份不同才算变", () => {
  assert.equal(page.bootIdentityChanged("boot-a", "boot-b"), true);
  assert.equal(page.bootIdentityChanged("boot-a", "boot-a"), false);
  // 还没有身份时按变了处理：重新读一次能力清单、刷新一遍视图，代价小，且不会漏掉重启
  assert.equal(page.bootIdentityChanged(null, "boot-a"), true);
});
