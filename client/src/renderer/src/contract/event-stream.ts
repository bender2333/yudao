// 事件流客户端（应用层与接口层设计说明第 5.4、5.5、5.6 节）。
// 用 npm eventsource 传入自定义 fetch（加入令牌以后在请求头中带令牌）；按位置续传；
// 核对 previous；处理 checkpoint、resync、delta；断线时报告「连接中断，数据可能过时」。
// 帧的解析与位置核对放在 stream-frames.ts，这里只负责连接、订阅与上报。

import { EventSource } from "eventsource";
import { ReconnectBackoff } from "./reconnect-backoff";
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

// 重连的递增间隔（工单 #301）与「连接站得住才清零」的规则放在 reconnect-backoff.ts（工单 #679）

export class EventStreamClient {
  private source: EventSource | null = null;
  private lastPosition = 0;
  private closed = false;
  private readonly backoff = new ReconnectBackoff();
  private timer: NodeJS.Timeout | null = null;
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
    this.closed = false;
    this.backoff.stoodUp();
    this.lastPosition = after;
    this.connect();
  }

  // 建一条连接：npm eventsource 自带的重连是固定 3 秒，服务停掉以后会连续报错；
  // 这里出错就关掉这一条，按 1、2、4……秒递增的间隔自己重建（30 秒封顶），中断只报告一次
  private connect(): void {
    if (this.closed) {
      return;
    }
    const source = new EventSource(streamUrl(this.baseUrl, this.scope, this.lastPosition), {
      fetch: (input: RequestInfo | URL, init?: RequestInit) =>
        fetch(input, {
          ...init,
          headers: { ...(init?.headers ?? {}), ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}) },
        }),
    });
    this.source = source;
    source.addEventListener("open", () => {
      if (this.source !== source || this.closed) {
        return;
      }
      // 打开不算站得住（工单 #679）：退避在收到帧以后才清零
      this.handlers.onConnected();
    });
    for (const name of ["event", "checkpoint", "delta", "resync"]) {
      source.addEventListener(name, (message) => this.onFrame(name, message as MessageEvent));
    }
    source.addEventListener("error", () => {
      if (this.closed || this.source !== source) {
        return;
      }
      source.close();
      this.source = null;
      if (this.backoff.count === 0) {
        this.handlers.onInterrupted();
      }
      const delay = this.backoff.nextDelayMs();
      this.timer = setTimeout(() => {
        this.timer = null;
        this.connect();
      }, delay);
    });
  }

  stop(): void {
    this.closed = true;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.source?.close();
    this.source = null;
  }


  get position(): number {
    return this.lastPosition;
  }

  private onFrame(name: string, message: MessageEvent): void {
    // 收到一帧：这条连接站住了（工单 #679），下一次断线重新从 1 秒算起
    this.backoff.stoodUp();
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
