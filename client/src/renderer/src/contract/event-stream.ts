// 事件流客户端（应用层与接口层设计说明第 5.4、5.5、5.6 节）。
// 用 npm eventsource 传入自定义 fetch（加入令牌以后在请求头中带令牌）；按位置续传；
// 核对 previous；处理 checkpoint、resync、delta；断线时报告「连接中断，数据可能过时」。
// 帧的解析与位置核对放在 stream-frames.ts，这里只负责连接、订阅与上报。

import { EventSource } from "eventsource";
import { nextPosition, parseFrame, streamUrl, type StreamMessage, type StreamScope } from "./stream-frames";

export type { StreamMessage, StreamScope } from "./stream-frames";

export type StreamHandlers = {
  onConnected: () => void;
  onMessage: (message: StreamMessage) => void;
  // 发现缺口或收到 resync：客户端把已打开的视图标为「数据可能过时」并重新同步快照
  onResync: (reason: string) => void;
  // 断线：保留最后已知的状态，整体显示「连接中断，数据可能过时」（设计说明第 5.7 节）
  onInterrupted: () => void;
};

export class EventStreamClient {
  private source: EventSource | null = null;
  private lastPosition = 0;
  private closed = false;
  private readonly baseUrl: string;
  private readonly scope: StreamScope;
  private readonly handlers: StreamHandlers;
  private readonly token: string;

  constructor(baseUrl: string, scope: StreamScope, handlers: StreamHandlers, token = "") {
    this.baseUrl = baseUrl;
    this.scope = scope;
    this.handlers = handlers;
    this.token = token;
  }

  // 从 after 之后订阅；after 是客户端已经收到的最大位置（快照位置或最后收到的事件位置）
  start(after: number): void {
    this.stop();
    const source = new EventSource(streamUrl(this.baseUrl, this.scope, after), {
      fetch: (input: RequestInfo | URL, init?: RequestInit) =>
        fetch(input, {
          ...init,
          headers: { ...(init?.headers ?? {}), ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}) },
        }),
    });
    this.closed = false;
    this.lastPosition = after;
    this.source = source;
    source.addEventListener("open", () => this.handlers.onConnected());
    for (const name of ["event", "checkpoint", "delta", "resync"]) {
      source.addEventListener(name, (message) => this.onFrame(name, message as MessageEvent));
    }
    source.addEventListener("error", () => {
      // eventsource 会自动重连（带 Last-Event-ID）；这里只报告连接中断
      if (!this.closed) {
        this.handlers.onInterrupted();
      }
    });
  }

  stop(): void {
    this.closed = true;
    this.source?.close();
    this.source = null;
  }

  get position(): number {
    return this.lastPosition;
  }

  private onFrame(name: string, message: MessageEvent): void {
    const parsed = parseFrame(name, message.data, this.lastPosition);
    if (parsed.kind === "gap") {
      // previous 与本连接最后收到的不符：缺口，交给重新同步（第 5.5 节）
      this.handlers.onResync(`position gap: expected ${parsed.expected}, got ${parsed.got}`);
      return;
    }
    this.lastPosition = nextPosition(parsed, this.lastPosition);
    if (parsed.kind === "resync") {
      this.handlers.onResync(parsed.reason);
    }
    this.handlers.onMessage(parsed);
  }
}
