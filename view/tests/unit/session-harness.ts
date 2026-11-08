// 画面单元测试的共用装置（工单 #1573）：把录下的接口响应与事件流接上画面的同步层与壳。
//
// 单元测试不启动 Yudao、不连网络：查询走录下的响应（tests/fixtures/session/queries.json），
// 事件流走录下的 SSE 帧（tests/fixtures/session/events.sse），经真正的 EventStream 解析；
// 需要核对重新同步时换成一个可以手动触发的流（manualStream）。
//
// 这不是产品代码：只在 tests/unit 下被三个测试文件共用。

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Capabilities } from "../../src/api/generated/types.gen.ts";
import type { CommandOutcome, Connection, InterfaceAccess } from "../../src/sync/connection.ts";
import { EventStream } from "../../src/sync/stream.ts";
import type { StreamHandlers, StreamHandle } from "../../src/sync/stream.ts";
import type { Timers } from "../../src/sync/sync.ts";
import { SyncEngine } from "../../src/sync/sync.ts";
import { Shell } from "../../src/shell.ts";
import type { DecisionFace, PixelAction, PixelState } from "../../src/pixel/contract.ts";
import type { SceneSurface } from "../../src/shell.ts";

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(here, "..", "fixtures", "session");

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
  capabilities: Capabilities;
  recordings: Recording[];
}

/** 读录下的接口响应（录下的能力清单与各查询的应答）。 */
export function loadFixtures(): Fixtures {
  const recorded = JSON.parse(readFileSync(join(FIXTURES, "queries.json"), "utf8")) as { recordings: Recording[] };
  return { capabilities: loadCapabilities(), recordings: recorded.recordings };
}

/** 能力清单也是录下的那一份（服务的查询、命令、事件种类与覆盖层都在里面）。 */
export function loadCapabilities(): Capabilities {
  return JSON.parse(readFileSync(join(FIXTURES, "capabilities.json"), "utf8")) as Capabilities;
}

/** 一段录下的 SSE 帧（连续的窗口，第一帧的 previous 是 0）。 */
export function loadEvents(name: string): string {
  return readFileSync(join(FIXTURES, name), "utf8");
}

export function recordingOf(fixtures: Fixtures, name: string): Recording {
  const found = fixtures.recordings.find((recording) => recording.name === name);
  if (!found) throw new Error(`夹具里没有 ${name}`);
  return found;
}

/** 录下的应答：查询名相同，且录下的参数是这次参数的一部分（壳可能多带一个空参数）。 */
export function responseOf(recording: Recording, name: string, params?: Record<string, unknown>): { position: number; data: unknown } {
  const entry = recording.queries.find((candidate) => candidate.name === name
    && Object.entries(candidate.params).every(([key, value]) => JSON.stringify(value) === JSON.stringify((params ?? {})[key])));
  if (!entry) {
    throw new Error(`夹具 ${recording.name} 里没有 ${name} 的应答：${JSON.stringify(params ?? {})}`);
  }
  return entry.response;
}

/** 自动推进的定时器：合并查询由测试用 flush() 推进，不让 200 毫秒真的过去。 */
export const manualTimers: Timers = { set: () => 0, clear: () => undefined };

/** 一次的连接与接口访问的替身：查询读夹具，命令记下来，事件流可以是录下的帧或手动的。 */
export class FakeServer {
  fixtures: Fixtures;
  readonly recording: Recording;
  /** 发出的命令（按顺序）：名称、请求体与这次连接的身份。 */
  readonly sent: { name: string; body: Record<string, unknown>; identity: string }[] = [];
  /** 发过的查询（按顺序）。 */
  readonly queried: { name: string; params?: Record<string, unknown> }[] = [];
  /** 查询失败的项目（按名称）：模拟服务不可达或这一项没有登记。 */
  readonly failures = new Set<string>();
  /** 下一次同名的查询先等一等，由测试放行：核对换场景时迟到的旧结果。 */
  private readonly deferred = new Set<string>();
  /** 正在等放行的查询。 */
  readonly waiting: { name: string }[] = [];
  private readonly waiters: (() => void)[] = [];
  /** 命令的应答；没有给时按受理回答（duplicate 为 false）。 */
  commandResult: ((name: string, body: Record<string, unknown>) => CommandOutcome) | null = null;
  /** 能力清单在这条连接上报告的接口版本（与画面不同的情况由测试改它）。 */
  versions = { view: 15, server: 15 };
  /** 手动流：记下事件流的回调，由测试触发 onResync / 断开。 */
  manual = false;
  handlers: StreamHandlers | null = null;
  streamStarts: number[] = [];
  streamStops = 0;
  identity = "";
  connectCount = 0;
  private controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  private readonly encoder = new TextEncoder();
  private readonly body: ReadableStream<Uint8Array>;

  constructor(fixtures: Fixtures, recording: string, capabilities?: Capabilities) {
    this.fixtures = fixtures;
    this.recording = recordingOf(fixtures, recording);
    if (capabilities) this.fixtures = { ...fixtures, capabilities };
    this.body = new ReadableStream<Uint8Array>({
      start: (controller) => {
        this.controller = controller;
      },
    });
  }

  get capabilities(): Capabilities {
    return this.fixtures.capabilities;
  }

  /** 换一份能力清单（缺命令、缺查询、接口版本不同的情况）。 */
  setCapabilities(capabilities: Capabilities): void {
    this.fixtures = { ...this.fixtures, capabilities };
  }

  /** 下一次同名的查询先等一等（只延后一次）：测试用 release() 放行。 */
  deferNext(name: string): void {
    this.deferred.add(name);
  }

  /** 放行所有正在等的查询（结果照录下的给）。 */
  release(): void {
    const waiters = this.waiters.splice(0);
    for (const resolve of waiters) resolve();
  }

  connect = async (address: string, token = ""): Promise<Connection> => {
    this.connectCount += 1;
    this.identity = token;
    const access: InterfaceAccess = {
      baseUrl: address,
      identity: token,
      query: async <T>(name: string, params?: Record<string, unknown>): Promise<{ position: number; data: T }> => {
        this.queried.push({ name, params });
        if (this.deferred.delete(name)) {
          this.waiting.push({ name });
          await new Promise<void>((resolve) => this.waiters.push(resolve));
        }
        if (this.failures.has(name)) throw new Error(`查询 ${name} 失败（测试）`);
        return responseOf(this.recording, name, params) as { position: number; data: T };
      },
      command: async (name: string, body: Record<string, unknown>): Promise<CommandOutcome> => {
        this.sent.push({ name, body, identity: token });
        if (this.commandResult) return this.commandResult(name, body);
        return { ok: true, accepted: { command_id: body.command_id as string, position: 1, duplicate: false } };
      },
    };
    return {
      state: "connected",
      address,
      access,
      capabilities: this.capabilities,
      versions: this.versions,
    };
  };

  /** 事件流：默认用真正的 EventStream 读录下的帧；manual 时只记下回调。 */
  openStream = (baseUrl: string, handlers: StreamHandlers, token: string): StreamHandle => {
    this.handlers = handlers;
    if (this.manual) {
      type Handle = { start(after: number): void; stop(): void; readonly position: number };
      let started = 0;
      const handle: Handle = {
        start: (after: number) => {
          started = after;
          this.streamStarts.push(after);
        },
        stop: () => {
          this.streamStops += 1;
        },
        get position() {
          return started;
        },
      };
      return handle;
    }
    return new EventStream(baseUrl, handlers, token, {
      fetch: async () => new Response(this.body, { status: 200, headers: { "content-type": "text/event-stream" } }),
      // 数据读完之后不重连（测试结束时 shell.close() 停下这一条流）
      setTimeout: () => 0,
    });
  };

  /** 把一段录下的 SSE 帧推进这条事件流。 */
  pushFrames(text: string): void {
    this.controller?.enqueue(this.encoder.encode(text));
  }
}

/** 等接口的响应落定：把微任务与几个回合的循环跑完。 */
export async function settle(): Promise<void> {
  for (let index = 0; index < 8; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

/** 等到条件成立（把微任务跑完，最多 400 个回合）。 */
export async function until(predicate: () => boolean, what: string): Promise<void> {
  for (let index = 0; index < 400; index += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setImmediate(resolve));
  }
  throw new Error(`等不到：${what}`);
}

/** 一个假的像素画面：记下壳交给它的状态、动作与实时内容。 */
export interface FakeSurface extends SceneSurface {
  readonly jumped: PixelState[];
  readonly states: PixelState[];
  readonly actions: PixelAction[];
  readonly decisions: DecisionFace[][];
  readonly streams: { who: { room: string | null; role: string | null }; text: string }[];
  destroyed: number;
}

export function fakeSurface(): FakeSurface {
  const surface: FakeSurface = {
    jumped: [],
    states: [],
    actions: [],
    decisions: [],
    streams: [],
    destroyed: 0,
    jump(state) {
      this.jumped.push(state);
    },
    setState(state) {
      this.states.push(state);
    },
    play(action) {
      this.actions.push(action);
    },
    setDecisions(faces) {
      this.decisions.push(faces);
    },
    stream(who, text) {
      this.streams.push({ who, text });
    },
    destroy() {
      this.destroyed += 1;
    },
  };
  return surface;
}

/** 场景组件挂载时的画布容器与时钟的替身（单元测试里没有 DOM，画面由假的工厂给出）。 */
export const fakeHost = {} as unknown as HTMLElement;
export const fakeClock = {} as never;

/** 用这个替身连接建一个壳：同步层走录下的响应与事件流，页面地址的打开方式可以注入。 */
export function shellFor(server: FakeServer, options: {
  openPage?: (url: string) => void;
  now?: () => number;
  newCommandId?: () => string;
} = {}): Shell {
  const engine = new SyncEngine({
    connect: server.connect,
    openStream: server.openStream,
    timers: manualTimers,
  });
  return new Shell({ engine, ...options });
}
