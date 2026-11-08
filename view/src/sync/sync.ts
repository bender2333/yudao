// 画面的同步层（画面与播放 docs/design/visualization.md「分层与边界」的同步层与「断线与切回」；
// 应用层与接口层 docs/design/app-and-interface.md「页面的同步规则」「补齐与实时」「缺口检测与重新同步」）。
//
// 打开一个视图时读一次快照，之后按能力清单里这条查询声明的事件种类重新查询（200 毫秒内的多条事件合并为一次）；
// 位置不大于快照位置的事件不作用于这个视图，切换对象以后迟到的旧结果丢弃；
// 发现缺口、收到 resync 或断线重新连上时重新查询已打开的视图，再从快照位置中最小的一个重新订阅；
// 本次启动的身份改变（服务重启）时重新读取能力清单并重新同步。
//
// 这一层只管数据是不是最新，不管怎么画：它不知道画面层与壳的存在，规则与页面的同步规则相同，
// 代码是画面自己的一份（不导入 client/ 的任何文件）。

import type { Capabilities, EventObject, OutputDelta } from "../api/generated/types.gen.ts";
import { connect, type CommandOutcome, type Connection, type InterfaceAccess, type QueryRunner } from "./connection.ts";
import { EventStream, type StreamHandle, type StreamHandlers, type StreamMessage } from "./stream.ts";

/** 一次查询的结果：位置与数据（应用层的快照）。 */
export type Snapshot<T> = { position: number; data: T };

/** 一份数据的监听者：拿到查询结果与它来自的快照的位置（画面合同的状态带位置）。 */
export type ViewListener<T> = (value: T, position: number) => void;

/** 打开一个视图时登记的内容：查询名称与参数。 */
export type ViewRequest = {
  query: string;
  params?: Record<string, unknown>;
};

/** 合并重新查询用的定时器：单元测试注入手动推进的替身，不真等 200 毫秒。 */
export interface Timers {
  set(fn: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

const realTimers: Timers = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** 200 毫秒内的多条事件合并为一次重新查询（与页面同一数值）。 */
export const COALESCE_MS = 200;

type Entry = {
  query: string;
  params: Record<string, unknown> | undefined;
  changedBy: Set<string>;
  listeners: Set<ViewListener<unknown>>;
  /** 快照已经包含的最大全局位置；位置不大于它的事件不作用。 */
  position: number;
  active: boolean;
};

/**
 * 视图同步：每个视图保存快照与位置，按查询声明的事件种类重新查询。
 * 查询失败时保留旧快照与旧位置，不抛出（服务恢复以后的事件会再触发重查）。
 */
export class ViewSync {
  private readonly entries = new Map<string, Entry>();
  private readonly changedByQuery: Record<string, Set<string>> = {};
  private readonly pending = new Set<string>();
  private timer: unknown = null;
  private readonly runner: QueryRunner;
  private readonly timers: Timers;

  constructor(runner: QueryRunner, capabilities: { queries: { name: string; changed_by: string[] }[] }, timers: Timers = realTimers) {
    this.runner = runner;
    this.timers = timers;
    for (const query of capabilities.queries) {
      this.changedByQuery[query.name] = new Set(query.changed_by);
    }
  }

  /** 打开的视图（测试与排查用）。 */
  get openViewIds(): string[] {
    return [...this.entries.keys()];
  }

  /**
   * 打开一个视图：立即查询一次并交给 listener，之后相关事件到达时重新查询。
   * 查询失败时不通知、不抛出：由调用处的连接状态说明数据可能过时；onError 把失败原因交给调用处。
   */
  async open<Data>(viewId: string, request: ViewRequest, listener: ViewListener<Data>,
                   onError?: (reason: string) => void): Promise<void> {
    this.close(viewId);
    const entry: Entry = {
      query: request.query,
      params: request.params,
      changedBy: this.changedByQuery[request.query] ?? new Set(),
      listeners: new Set([listener as ViewListener<unknown>]),
      position: 0,
      active: true,
    };
    this.entries.set(viewId, entry);
    let snapshot: { position: number; data: Data } | null = null;
    let failure = "";
    try {
      snapshot = await this.runner<Data>(request.query, request.params);
    } catch (error) {
      failure = error instanceof Error ? error.message : String(error);
    }
    if (!entry.active || this.entries.get(viewId) !== entry) {
      // 迟到的结果：这个视图已经关闭或换了对象，丢弃
      return;
    }
    if (snapshot === null) {
      onError?.(failure);
      return;
    }
    entry.position = snapshot.position;
    for (const target of entry.listeners) {
      target(snapshot.data, snapshot.position);
    }
  }

  close(viewId: string): void {
    this.entries.delete(viewId);
    this.pending.delete(viewId);
  }

  closeAll(): void {
    this.entries.clear();
    this.pending.clear();
    if (this.timer !== null) {
      this.timers.clear(this.timer);
      this.timer = null;
    }
  }

  /** 收到一条事件：位置不大于该视图快照位置的事件不作用；否则按种类排入合并队列。 */
  applyEvent(type: string, position: number): void {
    for (const [viewId, entry] of this.entries) {
      if (!entry.active || position <= entry.position) continue;
      if (entry.changedBy.has(type)) this.pending.add(viewId);
    }
    if (this.pending.size > 0 && this.timer === null) {
      this.timer = this.timers.set(() => {
        this.timer = null;
        const ids = [...this.pending];
        this.pending.clear();
        for (const viewId of ids) void this.refresh(viewId);
      }, COALESCE_MS);
    }
  }

  /** 重新查询一个视图；视图期间关闭或换对象时丢弃迟到的结果。 */
  async refresh(viewId: string): Promise<void> {
    const entry = this.entries.get(viewId);
    if (!entry || !entry.active) return;
    let snapshot: { position: number; data: unknown } | null = null;
    try {
      snapshot = await this.runner(entry.query, entry.params);
    } catch {
      return;
    }
    if (!entry.active || this.entries.get(viewId) !== entry) return;
    entry.position = snapshot.position;
    for (const target of entry.listeners) {
      target(snapshot.data, snapshot.position);
    }
  }

  /** 重新查询全部已打开的视图，返回它们快照位置中最小的一个（重新订阅的起点）。 */
  async refreshAll(): Promise<number> {
    const ids = [...this.entries.keys()];
    await Promise.all(ids.map((id) => this.refresh(id)));
    // 位置 0 表示「这个视图还没有快照」：不参与取最小值，否则一个刚打开的视图会把重新订阅拖回 0
    const positions = ids.map((id) => this.entries.get(id)?.position ?? 0).filter((value) => value > 0);
    return positions.length === 0 ? 0 : Math.min(...positions);
  }

  /** 还没到点的合并查询立刻执行（单元测试用手动定时器时推进一次）。 */
  async flush(): Promise<void> {
    if (this.timer !== null) {
      this.timers.clear(this.timer);
      this.timer = null;
    }
    const ids = [...this.pending];
    this.pending.clear();
    await Promise.all(ids.map((id) => this.refresh(id)));
  }
}

/**
 * 重新订阅事件流的起点：视图位置里 0 表示「还没有快照」，不算；也不能比事件流已经读到的位置更早——
 * 退回去会让服务重放整段历史，画面反复重新同步（与页面同一个规则）。
 */
export function resubscribePosition(viewPosition: number, streamPosition: number): number {
  const earliest = viewPosition > 0 ? viewPosition : 0;
  return Math.max(earliest, streamPosition);
}

/** 事件流的三种状态：还没连上、已连上、连上以后断开。 */
export type StreamStatus = "connecting" | "connected" | "interrupted";

/** 同步层的状态：壳上的连接状态与接口版本都从它来。 */
export type SyncState =
  | { kind: "connecting" }
  | {
    kind: "connected";
    address: string;
    capabilities: Capabilities;
    versions: { view: number; server: number };
    stream: StreamStatus;
  }
  | { kind: "unauthorized"; address: string }
  | { kind: "failed"; address: string; message: string };

/** 同步层对外的两次访问：读能力清单与打开事件流。单元测试注入替身，不连网络。 */
export type SyncDeps = {
  connect: (address: string, token?: string) => Promise<Connection>;
  openStream: (baseUrl: string, handlers: StreamHandlers, token: string) => StreamHandle;
  timers?: Timers;
};

const defaultDeps: SyncDeps = {
  connect,
  openStream: (baseUrl, handlers, token) => new EventStream(baseUrl, handlers, token),
};

/**
 * 断线以后重新连上时，本次启动的身份是否变了（应用层与接口层 docs/design/app-and-interface.md「能力清单」）。
 * 变了（服务重启）：重新读取能力清单并重新同步；没变：照旧从原位置续上。
 */
export function bootIdentityChanged(before: string | null, next: string | null): boolean {
  return before !== next;
}

/**
 * 画面的同步引擎：连接、事件流与视图同步的生命周期。
 * 对外只有状态、事件、重新同步和两条接口访问（查询与命令），不掺画面的说法。
 */
export class SyncEngine {
  private iface: InterfaceAccess | null = null;
  private stream: StreamHandle | null = null;
  private views: ViewSync | null = null;
  private capabilities: Capabilities | null = null;
  private versions: { view: number; server: number } = { view: 0, server: 0 };
  private boot: string | null = null;
  private address = "";
  private token = "";
  private state: SyncState = { kind: "connecting" };
  private streamStatus: StreamStatus = "connecting";
  private resyncing = false;
  /** 上一次重新同步的原因（缺口、resync 的原因；壳上可以显示「数据可能过时」）。 */
  lastResyncReason = "";
  private readonly deps: SyncDeps;
  private readonly stateListeners = new Set<(state: SyncState) => void>();
  private readonly eventListeners = new Set<(event: EventObject) => void>();
  private readonly deltaListeners = new Set<(delta: OutputDelta) => void>();
  private readonly resyncListeners = new Set<() => void>();

  constructor(deps: Partial<SyncDeps> = {}) {
    this.deps = { ...defaultDeps, ...deps };
  }

  get currentState(): SyncState {
    return this.state;
  }

  get currentCapabilities(): Capabilities | null {
    return this.capabilities;
  }

  get currentVersions(): { view: number; server: number } {
    return this.versions;
  }

  get currentAccess(): InterfaceAccess | null {
    return this.iface;
  }

  get viewSync(): ViewSync | null {
    return this.views;
  }

  /** 事件流已经读到的位置（重新订阅的起点用）。 */
  get position(): number {
    return this.stream?.position ?? 0;
  }

  subscribeState(listener: (state: SyncState) => void): () => void {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  }

  /** 订阅每一条到达的事件：画面据此演动作，翻译层不累加事实。 */
  subscribeEvents(listener: (event: EventObject) => void): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /** 订阅模型输出片段（实时内容；画面只把它当流式文字）。 */
  subscribeDeltas(listener: (delta: OutputDelta) => void): () => void {
    this.deltaListeners.add(listener);
    return () => this.deltaListeners.delete(listener);
  }

  /** 订阅重新同步：画面回到查询给出的状态，不补播已经演过的动作。 */
  subscribeResync(listener: () => void): () => void {
    this.resyncListeners.add(listener);
    return () => this.resyncListeners.delete(listener);
  }

  /** 连接画面自己的来源：读能力清单、建立视图同步、打开事件流。 */
  async open(address: string, token = ""): Promise<void> {
    this.closeStream();
    this.address = address;
    this.token = token;
    this.emit({ kind: "connecting" });
    let result: Connection;
    try {
      result = await this.deps.connect(address, token);
    } catch (error) {
      this.emit({ kind: "failed", address, message: error instanceof Error ? error.message : String(error) });
      return;
    }
    if (result.state === "unauthorized") {
      this.emit({ kind: "unauthorized", address });
      return;
    }
    if (result.state === "failed") {
      this.emit({ kind: "failed", address, message: result.message });
      return;
    }
    this.iface = result.access;
    this.capabilities = result.capabilities;
    this.versions = result.versions;
    this.boot = result.capabilities.deployment.boot_id;
    this.views = new ViewSync(result.access.query, result.capabilities, this.deps.timers);
    this.streamStatus = "connecting";
    this.emitConnected();
    this.startStream(0);
  }

  /** 按名称查询一次（不登记视图）：壳读取材料这类临时读取用它。 */
  queryOne<T>(name: string, params?: Record<string, unknown>): Promise<Snapshot<T>> {
    if (!this.iface) return Promise.reject(new Error("尚未连接"));
    return this.iface.query<T>(name, params);
  }

  /** 发出一条命令：身份与地址来自这次连接（与页面相同）。 */
  command(name: string, body: Record<string, unknown>): Promise<CommandOutcome> {
    if (!this.iface) return Promise.reject(new Error("尚未连接"));
    return this.iface.command(name, body);
  }

  close(): void {
    this.closeStream();
    this.views?.closeAll();
    this.views = null;
    this.iface = null;
    this.capabilities = null;
  }

  private emit(state: SyncState): void {
    this.state = state;
    for (const listener of [...this.stateListeners]) listener(state);
  }

  private emitConnected(): void {
    if (!this.capabilities) return;
    this.emit({
      kind: "connected",
      address: this.address,
      capabilities: this.capabilities,
      versions: this.versions,
      stream: this.streamStatus,
    });
  }

  private setStreamStatus(next: StreamStatus): void {
    if (this.streamStatus === next) return;
    this.streamStatus = next;
    this.emitConnected();
  }

  private startStream(after: number): void {
    const handlers: StreamHandlers = {
      onConnected: (info) => {
        this.setStreamStatus("connected");
        // 断开以后重新连上：核对一次本次启动的身份（服务重启时重新读能力清单并重新同步）
        if (info.reconnected) void this.checkBootIdentity();
      },
      onInterrupted: () => this.setStreamStatus("interrupted"),
      onResync: (reason) => void this.resync(reason),
      onMessage: (message) => this.onMessage(message),
      onUnauthorized: () => {
        this.setStreamStatus("interrupted");
        this.emit({ kind: "unauthorized", address: this.address });
      },
    };
    this.stream = this.deps.openStream(this.address, handlers, this.token);
    this.stream.start(after);
  }

  private onMessage(message: StreamMessage): void {
    if (message.kind === "event") {
      this.views?.applyEvent(message.event.type, message.event.position);
      for (const listener of [...this.eventListeners]) listener(message.event);
      return;
    }
    if (message.kind === "delta") {
      for (const listener of [...this.deltaListeners]) listener(message.delta);
    }
  }

  /** 缺口、resync 与断线重连：重新查询已打开的视图，再从快照位置里更晚的那个重新订阅，最后通知画面跳到最新。 */
  private async resync(reason: string): Promise<void> {
    if (this.resyncing || !this.iface || !this.views) return;
    this.resyncing = true;
    this.lastResyncReason = reason;
    try {
      const result = await this.deps.connect(this.address, this.token);
      if (result.state !== "connected") return;
      // 本次启动的身份改变：重新读取能力清单
      if (bootIdentityChanged(this.boot, result.capabilities.deployment.boot_id)) {
        this.adoptCapabilities(result.capabilities, result.versions);
      }
      const position = resubscribePosition(await this.views.refreshAll(), this.stream?.position ?? 0);
      this.closeStream();
      this.startStream(position);
      for (const listener of [...this.resyncListeners]) listener();
    } catch {
      // 服务不可达：保留旧状态，数据可能过时的提示由壳写
    } finally {
      this.resyncing = false;
    }
  }

  /** 断线以后重新连上：核对一次本次启动的身份；同一次启动照旧从原位置续上。 */
  private async checkBootIdentity(): Promise<void> {
    if (!this.iface || !this.views) return;
    let result: Connection;
    try {
      result = await this.deps.connect(this.address, this.token);
    } catch {
      return;
    }
    if (result.state !== "connected" || !bootIdentityChanged(this.boot, result.capabilities.deployment.boot_id)) {
      return;
    }
    this.adoptCapabilities(result.capabilities, result.versions);
    const position = resubscribePosition(await this.views.refreshAll(), this.stream?.position ?? 0);
    this.closeStream();
    this.startStream(position);
    for (const listener of [...this.resyncListeners]) listener();
  }

  /** 本次启动的身份变了（服务重启）：换上它的能力清单，并通知壳（能力清单决定显示哪些部分）。 */
  private adoptCapabilities(capabilities: Capabilities, versions: { view: number; server: number }): void {
    this.boot = capabilities.deployment.boot_id;
    this.capabilities = capabilities;
    this.versions = versions;
    this.emitConnected();
  }

  private closeStream(): void {
    this.stream?.stop();
    this.stream = null;
  }
}
