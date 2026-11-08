// 画面端到端测试的装置（工单 #1574）：静态伺服 `view/out/`，按路径回放录下的接口响应与事件流。
//
// 不启动 Yudao、不连网络、不导入 client/ 或 harness/ 的任何文件：
//   - 静态文件是 `npm run build` 的构建结果（基路径 /view/，与发布时服务地址下的那一段相同）；
//   - /api/capabilities、/api/queries/<名称>、/api/events 由这个进程按录下的响应回答，
//     事件流是录下的 SSE 帧（从 after 之后重放），连接保持打开，与真实服务的读法相同；
//   - /api/commands/<名称> 只记下请求并回答受理（或按用例给的拒绝），不改变任何事实。
//
// 录下的响应在 view/tests/fixtures/session/（工单 #1573 录自 harness.demo 与一个核验决定请求的项目），
// 覆盖层「循环」的 run.loops 在 view/tests/fixtures/e2e/run-loops.json（工单 #1574 录自 harness.demo）。
// 录制的脚本是 view/scripts/record-fixtures.mjs，只在人手动更新夹具时运行，不进测试。

import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const VIEW_ROOT = resolve(here, "..", "..");
const FIXTURES = join(VIEW_ROOT, "tests", "fixtures");
const BUILD_ROOT = join(VIEW_ROOT, "out");

/** 一份录下的查询应答。 */
export interface RecordedQuery {
  name: string;
  params: Record<string, unknown>;
  response: { position: number; data: unknown };
}

/** 一个录下的场景：项目、事项与运行的标识，以及各查询的应答。 */
export interface Recording {
  name: string;
  ids: { project_id: string; work_item_id: string; run_id: string };
  queries: RecordedQuery[];
}

export interface Fixtures {
  capabilities: Record<string, unknown>;
  recordings: Recording[];
}

/** 读录下的接口响应与能力清单（画面的单元测试用同一份）。 */
export function loadFixtures(): Fixtures {
  const recorded = JSON.parse(readFileSync(join(FIXTURES, "session", "queries.json"), "utf8")) as { recordings: Recording[] };
  return {
    capabilities: JSON.parse(readFileSync(join(FIXTURES, "session", "capabilities.json"), "utf8")) as Record<string, unknown>,
    recordings: recorded.recordings,
  };
}

export function recordingOf(fixtures: Fixtures, name: string): Recording {
  const found = fixtures.recordings.find((recording) => recording.name === name);
  if (!found) throw new Error(`夹具里没有 ${name}`);
  return found;
}

/** 录下的查询应答：按查询名与参数取（录下的参数是这次参数的一部分，壳可能多带一个空参数）。 */
export function responseOf(recording: Recording, name: string, params: Record<string, string[]> = {}): { position: number; data: unknown } {
  const found = findRecorded(recording, name, params);
  if (!found) throw new Error(`夹具 ${recording.name} 里没有 ${name} 的应答：${JSON.stringify(params)}`);
  return found.response;
}

function findRecorded(recording: Recording, name: string, params: Record<string, string[]>): RecordedQuery | undefined {
  return recording.queries.find((candidate) => candidate.name === name
    && Object.entries(candidate.params).every(([key, value]) => sameParam(value, params[key] ?? [])));
}

function sameParam(recorded: unknown, incoming: string[]): boolean {
  if (Array.isArray(recorded)) {
    return recorded.length === incoming.length && recorded.every((value, index) => String(value) === incoming[index]);
  }
  return recorded !== undefined && String(recorded) === incoming[0];
}

/** 录下的 run.loops（覆盖层「循环」的场景）。 */
export function loadRunLoops(): unknown {
  const recorded = JSON.parse(readFileSync(join(FIXTURES, "e2e", "run-loops.json"), "utf8")) as { response: { data: unknown } };
  return recorded.response.data;
}

/** 录下的事件流：连续的 SSE 帧，按空行切开。 */
export function loadEventBlocks(): string[] {
  const text = readFileSync(join(FIXTURES, "session", "events.sse"), "utf8");
  return text.split(/\r?\n\r?\n/).filter((block) => block.trim() !== "");
}

/** 一帧的位置（event 与 checkpoint 的 data 带 position；其余帧为 null）。 */
export function framePosition(block: string): number | null {
  const match = /^data: (.*)$/m.exec(block);
  if (!match?.[1]) return null;
  try {
    const data = JSON.parse(match[1]) as { position?: unknown };
    return typeof data.position === "number" ? data.position : null;
  } catch {
    return null;
  }
}

/** 一次被装置记下的请求。 */
export interface RecordedRequest {
  name: string;
  params: Record<string, string[]>;
  body?: Record<string, unknown>;
}

export type CommandReply = { status?: number; body: unknown };

/**
 * 一个静态伺服 + 回放的服务器：
 * - `/view/…` 读构建结果；`/api/capabilities`、`/api/queries/…`、`/api/events` 按夹具回答；
 * - `/api/commands/…` 记下请求并回答受理（用例可以给一个拒绝的答案）；
 * - `dropStreams()` 断开当前事件流，用来核对断线重连。
 */
export class ViewServer {
  readonly fixtures: Fixtures;
  readonly recording: Recording;
  readonly queries: RecordedRequest[] = [];
  readonly commands: RecordedRequest[] = [];
  /** 打开过几次事件流（断线重连以后会多一次）。 */
  streamOpens = 0;
  /** 命令的应答；没有给时按受理回答。 */
  commandReply: ((name: string, body: Record<string, unknown>) => CommandReply) | null = null;
  /** 当前打开着的事件流（断线重连时断开它们）。 */
  readonly streams = new Set<ServerResponse>();
  readonly timers = new Set<NodeJS.Timeout>();
  readonly eventBlocks: string[];
  private readonly server: Server;

  constructor(options: { fixtures: Fixtures; recording: Recording; eventBlocks: string[]; server: Server }) {
    this.fixtures = options.fixtures;
    this.recording = options.recording;
    this.eventBlocks = options.eventBlocks;
    this.server = options.server;
  }

  get address(): string {
    const address = this.server.address();
    if (address === null || typeof address === "string") throw new Error("装置还没有监听");
    return `http://127.0.0.1:${address.port}`;
  }

  /** 画面的地址：与发布时一样在服务地址下的 /view/。 */
  get url(): string {
    return `${this.address}/view/`;
  }

  async close(): Promise<void> {
    for (const timer of this.timers) clearInterval(timer);
    this.timers.clear();
    for (const stream of this.streams) stream.end();
    this.streams.clear();
    this.server.closeAllConnections();
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
  }

  /** 断开当前的事件流（不关服务）：画面按退避重连，重新订阅。 */
  dropStreams(): void {
    for (const stream of [...this.streams]) {
      this.streams.delete(stream);
      stream.end();
    }
  }
}

/** 起一个装置：静态伺服构建结果，接口按录下的场景回答。 */
export async function startViewServer(options: { recording: string; events?: "demo" | "none" }): Promise<ViewServer> {
  if (!existsSync(join(BUILD_ROOT, "index.html"))) {
    throw new Error(`没有构建结果：${BUILD_ROOT}。先运行 npm run build（npm run test:e2e 会先构建）`);
  }
  const fixtures = loadFixtures();
  const recording = recordingOf(fixtures, options.recording);
  let instance: ViewServer | null = null;
  const api = createServer((request, response) => {
    if (instance === null) {
      response.writeHead(503).end("装置还没有准备好");
      return;
    }
    void handle(instance, request, response);
  });
  instance = new ViewServer({
    fixtures,
    recording,
    eventBlocks: options.events === "none" ? [] : loadEventBlocks(),
    server: api,
  });
  await listenOnSafePort(api);
  return instance;
}

/**
 * Chromium 拒绝访问一部分端口（ERR_UNSAFE_PORT：SIP、X11 等）。系统给的临时端口偶尔落在这些端口上，
 * 换一个端口重新监听。这份名单与 Chromium 的 restricted ports 一致（1 到 1023 只放行 80 与 443）。
 */
const UNSAFE_PORTS = new Set([
  2049, 3659, 4045, 5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080,
]);

function isUnsafePort(port: number): boolean {
  if (port >= 1 && port <= 1023) return port !== 80 && port !== 443;
  return UNSAFE_PORTS.has(port);
}

async function listenOnSafePort(server: Server): Promise<void> {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", () => resolve());
    });
    const address = server.address();
    const port = address !== null && typeof address !== "string" ? address.port : 0;
    if (!isUnsafePort(port)) return;
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
  throw new Error("试了 25 次没有拿到 Chromium 能访问的端口");
}

/** 起一个装置跑一段用例，结束时关掉它（即使用例失败）。 */
export async function withViewServer<T>(
  options: { recording: string; events?: "demo" | "none" },
  run: (server: ViewServer) => Promise<T>,
): Promise<T> {
  const server = await startViewServer(options);
  try {
    return await run(server);
  } finally {
    await server.close();
  }
}

async function handle(instance: ViewServer, request: IncomingMessage, response: ServerResponse): Promise<void> {
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  try {
    if (url.pathname === "/api/capabilities") {
      sendJson(response, 200, instance.fixtures.capabilities);
      return;
    }
    if (url.pathname.startsWith("/api/queries/")) {
      const name = decodeURIComponent(url.pathname.slice("/api/queries/".length));
      const params = collectParams(url.searchParams);
      instance.queries.push({ name, params });
      const found = findRecorded(instance.recording, name, params);
      if (!found) {
        sendJson(response, 404, { error: `query not recorded: ${name}` });
        return;
      }
      sendJson(response, 200, found.response);
      return;
    }
    if (url.pathname === "/api/events") {
      openEvents(instance, url, response);
      return;
    }
    if (url.pathname.startsWith("/api/commands/")) {
      const name = decodeURIComponent(url.pathname.slice("/api/commands/".length));
      const body = await readJsonBody(request);
      instance.commands.push({ name, params: {}, body });
      const reply = instance.commandReply?.(name, body) ?? {
        body: { command_id: body.command_id, position: 1, duplicate: false },
      };
      sendJson(response, reply.status ?? 200, reply.body);
      return;
    }
    if (url.pathname === "/" || url.pathname === "/view") {
      response.writeHead(302, { location: "/view/" }).end();
      return;
    }
    if (url.pathname.startsWith("/view/")) {
      serveStatic(url.pathname.slice("/view/".length), response);
      return;
    }
    sendJson(response, 404, { error: "not found" });
  } catch (error) {
    sendJson(response, 500, { error: error instanceof Error ? error.message : String(error) });
  }
}

function collectParams(search: URLSearchParams): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [key, value] of search.entries()) {
    (out[key] ??= []).push(value);
  }
  return out;
}

function openEvents(instance: ViewServer, url: URL, response: ServerResponse): void {
  instance.streamOpens += 1;
  const after = Number(url.searchParams.get("after") ?? "0");
  response.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache, no-transform",
    connection: "keep-alive",
  });
  // 先发一帧注释：浏览器要等第一段响应体才把 fetch 的 Promise 交出来，
  // 没有这一帧时重连以后的「已连接」要等到 15 秒的保活注释才出现
  response.write(": connected\n\n");
  instance.streams.add(response);
  for (const block of instance.eventBlocks) {
    const position = framePosition(block);
    if (position !== null && position <= after) continue;
    response.write(`${block}\n\n`);
  }
  // 连接保持打开：真实服务在两次事件之间也保持打开（每 15 秒发一次保活注释）
  const timer = setInterval(() => response.write(": keep-alive\n\n"), 15_000);
  timer.unref?.();
  instance.timers.add(timer);
  response.on("close", () => {
    clearInterval(timer);
    instance.timers.delete(timer);
    instance.streams.delete(response);
  });
}

function serveStatic(relativePath: string, response: ServerResponse): void {
  let decoded: string;
  try {
    decoded = decodeURIComponent(relativePath);
  } catch {
    sendJson(response, 400, { error: "bad path" });
    return;
  }
  const target = resolve(BUILD_ROOT, decoded === "" ? "index.html" : decoded);
  if (target !== BUILD_ROOT && !target.startsWith(BUILD_ROOT + sep)) {
    sendJson(response, 403, { error: "forbidden" });
    return;
  }
  const file = existsSync(target) && statSync(target).isFile() ? target : join(BUILD_ROOT, "index.html");
  const type = MIME[extname(file)] ?? "application/octet-stream";
  response.writeHead(200, { "content-type": type, "cache-control": "no-store" });
  response.end(readFileSync(file));
}

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
};

function sendJson(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  response.end(JSON.stringify(body));
}

async function readJsonBody(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  const text = Buffer.concat(chunks).toString("utf8");
  return text === "" ? {} : (JSON.parse(text) as Record<string, unknown>);
}

// ---------------------------------------------------------------------------
// 页面这一侧的读数与操作

/** 收集页面的控制台错误与未捕获异常（断言最后为空）。 */
export function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    // 命令被拒绝时服务按设计回答 409，画面已经把原因显示给用户；浏览器自己记的那条不算应用错误
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

/** 等到一个条件成立（画面按录下的帧与查询自动更新，不刷新页面）；超时以写明在等什么的失败结束。 */
export async function waitFor<T>(read: () => Promise<T | null> | T | null, what: string, timeoutMs = 30_000): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await read();
    if (value !== null && value !== undefined && value !== false) return value as T;
    if (Date.now() > deadline) throw new Error(`等待超时：${what}`);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

/** 画面逻辑坐标上的一点点：换算成画布元素内的 CSS 坐标再点。 */
export async function clickLogical(page: Page, selector: string, W: number, H: number, x: number, y: number): Promise<void> {
  const canvas = page.locator(selector);
  await canvas.scrollIntoViewIfNeeded();
  const size = await canvas.evaluate((element) => {
    const rect = (element as HTMLCanvasElement).getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  });
  await canvas.click({ position: { x: (x / W) * size.width, y: (y / H) * size.height } });
}

export interface CanvasRead {
  width: number;
  height: number;
  cssWidth: number;
  hostWidth: number;
  imageRendering: string;
  colors: number;
  inkRatio: number;
  midLevels: number;
  signature: number;
}

/** 读一张画布的真实像素：尺寸、采样方式、配色数、非背景占比、灰阶层次与内容签名。 */
export async function readCanvas(page: Page, selector: string): Promise<CanvasRead> {
  return page.locator(selector).evaluate((element) => {
    const canvas = element as HTMLCanvasElement;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("画面画布没有 2D 上下文");
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const colors = new Set<number>();
    const mid = new Set<number>();
    let ink = 0;
    let signature = 0;
    for (let index = 0; index < data.length; index += 4) {
      colors.add(((data[index]! >> 3) << 10) | ((data[index + 1]! >> 3) << 5) | (data[index + 2]! >> 3));
      const lum = (data[index]! * 30 + data[index + 1]! * 59 + data[index + 2]! * 11) / 100;
      if (lum < 240) ink += 1;
      if (lum > 90 && lum < 210) mid.add(Math.round(lum));
      if (index % 28 === 0) signature = (signature * 31 + data[index]!) >>> 0;
    }
    const host = canvas.parentElement;
    return {
      width: canvas.width,
      height: canvas.height,
      cssWidth: Math.round(canvas.getBoundingClientRect().width * 100) / 100,
      hostWidth: host ? Math.round(host.getBoundingClientRect().width * 100) / 100 : 0,
      imageRendering: getComputedStyle(canvas).imageRendering,
      colors: colors.size,
      inkRatio: ink / (data.length / 4),
      midLevels: mid.size,
      signature,
    };
  });
}
