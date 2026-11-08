// 画面的同步层：事件流（画面与播放 docs/design/visualization.md「分层与边界」的同步层；
// 应用层与接口层 docs/design/app-and-interface.md「补齐与实时」「缺口检测与重新同步」「模型输出片段」）。
//
// 画面与页面同一来源：事件流用 fetch 读 SSE，局域网访问方式下在请求头里带令牌（与页面相同），
// 按位置续传；核对 previous 发现缺口时交给上层重新同步，收到 resync 帧同样重新同步；
// 断开以后按 1、2、4……秒的间隔重连，30 秒封顶，收到过至少一帧才把退避清零。
// 帧的解析不接触网络，便于单元测试直接核对。
//
// 画面的单元测试用录下的 SSE 内容驱动这一层（不启动 Yudao）：读流与解析因此都在测试里执行到。

import type { EventObject, OutputDelta } from "../api/generated/types.gen.ts";

/** 事件流的一帧解析以后的结果。 */
export type StreamMessage =
  | { kind: "event"; position: number; previous: number; event: EventObject }
  | { kind: "checkpoint"; position: number; previous: number }
  | { kind: "delta"; delta: OutputDelta }
  | { kind: "gap"; expected: number; got: number }
  | { kind: "resync"; reason: string; endPosition: number };

/** 解析一条 SSE 帧；eventName 是 SSE 的 event 字段（event/checkpoint/delta/resync）。 */
export function parseFrame(eventName: string, data: string, lastPosition: number): StreamMessage {
  if (eventName === "event") {
    const event = JSON.parse(data) as EventObject;
    return event.previous === lastPosition
      ? { kind: "event", position: event.position, previous: event.previous, event }
      : { kind: "gap", expected: lastPosition, got: event.previous };
  }
  if (eventName === "checkpoint") {
    const frame = JSON.parse(data) as { position: number; previous: number };
    return frame.previous === lastPosition
      ? { kind: "checkpoint", position: frame.position, previous: frame.previous }
      : { kind: "gap", expected: lastPosition, got: frame.previous };
  }
  if (eventName === "delta") {
    // 片段不带位置，不改变续传位置
    return { kind: "delta", delta: JSON.parse(data) as OutputDelta };
  }
  if (eventName === "resync") {
    const frame = JSON.parse(data) as { reason: string; end_position: number };
    return { kind: "resync", reason: frame.reason, endPosition: frame.end_position };
  }
  throw new Error(`未知的事件流帧：${eventName}`);
}

/** 一帧到达以后新的续传位置：事件与检查点推进位置，片段与 resync 不推进。 */
export function nextPosition(message: StreamMessage, current: number): number {
  if (message.kind === "event" || message.kind === "checkpoint") {
    return message.position;
  }
  return current;
}

/**
 * 订阅地址：从 after 之后读起。画面订阅整条流（与页面相同，不按项目筛选），
 * live=1 表示接收模型输出片段（画面里只作实时内容，不进播放时间线）。
 */
export function streamUrl(baseUrl: string, after: number): string {
  const params = new URLSearchParams();
  params.set("after", String(after));
  params.set("live", "1");
  return `${baseUrl}/api/events?${params.toString()}`;
}

/** 断线以后的等待时间：第一次 1 秒，以后每次翻倍，30 秒封顶；收到过至少一帧才算站得住。 */
export class ReconnectBackoff {
  private failures = 0;
  private readonly baseMs: number;
  private readonly maxMs: number;

  constructor(baseMs = 1000, maxMs = 30000) {
    this.baseMs = baseMs;
    this.maxMs = maxMs;
  }

  nextDelayMs(): number {
    this.failures += 1;
    return Math.min(this.maxMs, this.baseMs * 2 ** (this.failures - 1));
  }

  stoodUp(): void {
    this.failures = 0;
  }

  get count(): number {
    return this.failures;
  }
}

/** 事件流回调：连上、收到一帧、缺口或 resync、断开、需要访问令牌。 */
export interface StreamHandlers {
  /** reconnected 表示这是断开以后的重新连接：上层据此核对一次本次启动的身份。 */
  onConnected: (info: { reconnected: boolean }) => void;
  onMessage: (message: StreamMessage) => void;
  /** 发现缺口或收到 resync：把已打开的视图标为「数据可能过时」并重新同步。 */
  onResync: (reason: string) => void;
  /** 断开：保留最后已知的状态，壳上写「连接中断，数据可能过时」。 */
  onInterrupted: () => void;
  /** 服务要求访问令牌（局域网访问方式下没有令牌或令牌无效）。 */
  onUnauthorized?: () => void;
}

/** 事件流需要的外部能力：取流、定时器。单元测试注入替身，不连网络。 */
export interface StreamDeps {
  fetch?: typeof fetch;
  setTimeout?: (fn: () => void, ms: number) => unknown;
  clearTimeout?: (handle: unknown) => void;
}

/** 一条事件流连接能做的事：从现在的位置起订阅、停止、读已收到的位置。 */
export interface StreamHandle {
  start(after: number): void;
  stop(): void;
  readonly position: number;
}

/** 画面的事件流客户端：fetch 读 SSE，断线按退避重连。 */
export class EventStream implements StreamHandle {
  private controller: AbortController | null = null;
  private lastPosition = 0;
  private closed = false;
  private retried = false;
  private started = false;
  private readonly backoff = new ReconnectBackoff();
  private timer: unknown = null;
  private readonly baseUrl: string;
  private readonly handlers: StreamHandlers;
  private readonly token: string;
  private readonly deps: StreamDeps;

  constructor(baseUrl: string, handlers: StreamHandlers, token = "", deps: StreamDeps = {}) {
    this.baseUrl = baseUrl;
    this.handlers = handlers;
    this.token = token;
    this.deps = deps;
  }

  /** 从 after 之后订阅；after 是已经收到的最大位置（快照位置或最后收到的事件位置）。 */
  start(after: number): void {
    this.stop();
    this.closed = false;
    this.started = true;
    this.retried = false;
    this.backoff.stoodUp();
    this.lastPosition = after;
    void this.connect();
  }

  get position(): number {
    return this.lastPosition;
  }

  get running(): boolean {
    return this.started && !this.closed;
  }

  private async connect(): Promise<void> {
    if (this.closed) return;
    const controller = new AbortController();
    this.controller = controller;
    const fetchImpl = this.deps.fetch ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));
    let response: Response;
    try {
      response = await fetchImpl(streamUrl(this.baseUrl, this.lastPosition), {
        signal: controller.signal,
        headers: {
          Accept: "text/event-stream",
          ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        },
      });
    } catch {
      this.onDrop();
      return;
    }
    if (this.closed || this.controller !== controller) {
      return;
    }
    if (response.status === 401 || response.status === 403) {
      // 服务要求访问令牌：这一次不再重连，由壳显示填写令牌的入口
      this.closed = true;
      this.controller = null;
      this.handlers.onUnauthorized?.();
      return;
    }
    if (!response.ok || response.body === null) {
      this.onDrop();
      return;
    }
    this.handlers.onConnected({ reconnected: this.retried });
    try {
      await this.read(response.body, controller);
    } catch {
      // 读流出错（断线、被中止）：下面按断开处理
    }
    this.onDrop();
  }

  /** 逐块读出 SSE 文本，按空行切开一帧一帧交给解析。 */
  private async read(body: ReadableStream<Uint8Array>, controller: AbortController): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (!this.closed && this.controller === controller) {
        const { done, value } = await reader.read();
        if (done) return;
        buffer += decoder.decode(value, { stream: true });
        // 帧之间以空行分隔；兼容 CRLF
        let split = buffer.search(/\r?\n\r?\n/);
        while (split >= 0) {
          const block = buffer.slice(0, split);
          const separator = /\r?\n\r?\n/.exec(buffer.slice(split))?.[0] ?? "\n\n";
          buffer = buffer.slice(split + separator.length);
          this.onBlock(block);
          split = buffer.search(/\r?\n\r?\n/);
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  /** 一帧的文本：event 行给出帧名，data 行给出载荷（多行 data 按 SSE 的规则用换行拼起来）。 */
  private onBlock(block: string): void {
    let name = "";
    const data: string[] = [];
    for (const raw of block.split(/\r?\n/)) {
      if (raw === "" || raw.startsWith(":")) continue;
      const index = raw.indexOf(":");
      const field = index < 0 ? raw : raw.slice(0, index);
      let value = index < 0 ? "" : raw.slice(index + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") name = value;
      else if (field === "data") data.push(value);
    }
    if (name === "" || data.length === 0) return;
    // 收到一帧：这条连接站住了，下一次断线重新从 1 秒算起
    this.backoff.stoodUp();
    let parsed: StreamMessage;
    try {
      parsed = parseFrame(name, data.join("\n"), this.lastPosition);
    } catch {
      // 画面还不认识的帧（服务端以后加的种类）：不画，不影响其余事件
      return;
    }
    if (parsed.kind === "gap") {
      this.handlers.onResync(`position gap: expected ${parsed.expected}, got ${parsed.got}`);
      return;
    }
    this.lastPosition = nextPosition(parsed, this.lastPosition);
    if (parsed.kind === "resync") {
      this.handlers.onResync(parsed.reason);
    }
    this.handlers.onMessage(parsed);
  }

  /** 断开：报告一次，按退避重连（这次重连是「重新连上」，上层据此核对本次启动的身份）。 */
  private onDrop(): void {
    if (this.closed) return;
    this.controller = null;
    this.retried = true;
    if (this.backoff.count === 0) {
      this.handlers.onInterrupted();
    }
    const delay = this.backoff.nextDelayMs();
    const schedule = this.deps.setTimeout ?? ((fn: () => void, ms: number) => setTimeout(fn, ms));
    this.timer = schedule(() => {
      this.timer = null;
      void this.connect();
    }, delay);
  }

  stop(): void {
    this.closed = true;
    this.started = false;
    if (this.timer !== null) {
      const cancel = this.deps.clearTimeout ?? ((handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>));
      cancel(this.timer);
      this.timer = null;
    }
    this.controller?.abort();
    this.controller = null;
  }
}
