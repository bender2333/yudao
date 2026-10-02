// 客户端的连接生命周期（应用层与接口层设计说明第 5.7、6.1 节，原型 v8 设计说明第 3.4 节）。
// 状态：连接中 / 已连接 / 接口版本不同（更新页）/ 连接失败。
// 已连接以后：保持一条不按项目筛选的事件流连接；收到事件按视图同步规则重新查询；
// 发现缺口或收到 resync 时重新查询已打开的视图，再按快照位置中最小的一个重新订阅；
// 本次启动的身份改变（服务重启）时重新读取能力清单并重新同步。

import type { Capabilities, DecisionList, EventObject } from "../api/generated/types.gen";
import { connect, interfaceFor, type Interface } from "./connection";
import type { ConnectionSettings } from "./settings";
import { EventStreamClient } from "./event-stream";
import { callCommand, type CommandOutcome } from "./invoke";
import { ViewSync } from "./view-sync";

export type ClientState =
  | { kind: "connecting" }
  | { kind: "outdated"; address: string; clientVersion: number; serverVersion: number }
  | { kind: "failed"; address: string; message: string }
  | { kind: "connected"; address: string; capabilities: Capabilities; streamConnected: boolean };

export type ClientListeners = {
  onState: (state: ClientState) => void;
  // 待决定的数量（跨项目等待回答的决定请求）：托盘图标与顶栏共用
  onPendingDecisions: (count: number) => void;
  onEvent: (event: EventObject) => void;
};

// 把查询与命令交给生成的应用层接口；外壳提供它们，以便单元测试注入替身
export type QueryRunner = <T>(client: Interface["client"], name: string, params: Record<string, unknown> | undefined) => Promise<{ position: number; data: T }>;

export class ClientApp {
  private iface: Interface | null = null;
  private settings: ConnectionSettings | null = null;
  private stream: EventStreamClient | null = null;
  private views: ViewSync | null = null;
  private boot: string | null = null;
  private capabilities: Capabilities | null = null;
  // 页面级的事件订阅：视图同步之外，页面还需要测试与候选等事件的结果内容（工单 #93），
  // 项目楼层这类按事件播放动作的画面也用它（工单 #82）
  private readonly pageListeners = new Set<(event: EventObject) => void>();
  // 项目楼层的重新同步订阅：缺口、断线重连、resync 时画面回到查询给出的状态
  private readonly resyncSubscribers = new Set<() => void>();

  constructor(
    private readonly runQuery: QueryRunner,
    private readonly listeners: ClientListeners,
  ) {}

  /** 订阅重新同步：收到时画面回到查询给出的状态，不补播已经播放过的动作。 */
  subscribeResync(fn: () => void): () => void {
    this.resyncSubscribers.add(fn);
    return () => this.resyncSubscribers.delete(fn);
  }

  get viewSync(): ViewSync | null {
    return this.views;
  }

  get currentCapabilities(): Capabilities | null {
    return this.capabilities;
  }

  get currentAddress(): string {
    return this.iface?.baseUrl ?? "";
  }

  // 提交一条命令：接受时返回受理回执，409 拒绝时返回 Rejected 供界面显示原因；
  // 网络错误与非预期状态码直接抛出，不静默吞掉（fast-fail）
  async command(name: string, body: Record<string, unknown>): Promise<CommandOutcome> {
    if (!this.iface) {
      throw new Error("尚未连接控制主机");
    }
    return callCommand(this.iface.client, name, body);
  }

  // 连接一个部署：读取能力清单并核对接口版本
  async open(settings: ConnectionSettings): Promise<void> {
    this.closeStream();
    this.listeners.onState({ kind: "connecting" });
    const result = await connect(settings);
    if (result.state === "outdated") {
      this.listeners.onState({
        kind: "outdated", address: result.address, clientVersion: result.clientVersion, serverVersion: result.serverVersion,
      });
      return;
    }
    if (result.state === "failed") {
      this.listeners.onState({ kind: "failed", address: result.address, message: result.message });
      return;
    }
    this.settings = settings;
    this.iface = interfaceFor(result.address);
    this.capabilities = result.capabilities;
    this.boot = result.capabilities.deployment.boot_id;
    this.views = new ViewSync((name, params) => this.query(name, params), result.capabilities);
    this.listeners.onState({
      kind: "connected", address: result.address, capabilities: result.capabilities, streamConnected: false,
    });
    await this.refreshPendingDecisions();
    this.startStream(0);
  }

  private query<T>(name: string, params: Record<string, unknown> | undefined): Promise<{ position: number; data: T }> {
    if (!this.iface) {
      return Promise.reject(new Error("尚未连接"));
    }
    return this.runQuery<T>(this.iface.client, name, params);
  }

  // 不按项目筛选的事件流：窗口关闭时也保持（设计说明第 5.7 节）
  private startStream(after: number): void {
    this.stream = new EventStreamClient(this.iface!.baseUrl, {}, {
      onConnected: () => this.setStreamConnected(true),
      onInterrupted: () => this.setStreamConnected(false),
      onResync: () => void this.resync(),
      onMessage: (message) => {
        if (message.kind === "event") {
          this.onEvent(message.event);
        }
      },
    }, this.settings?.token ?? "");
    this.stream.start(after);
  }

  private setStreamConnected(connected: boolean): void {
    if (this.capabilities) {
      this.listeners.onState({
        kind: "connected", address: this.iface!.baseUrl, capabilities: this.capabilities, streamConnected: connected,
      });
    }
  }

  private onEvent(event: EventObject): void {
    this.views?.applyEvent(event.type, event.position);
    this.listeners.onEvent(event);
    for (const listener of [...this.pageListeners]) {
      listener(event);
    }
    if (event.type === "decision_requested" || event.type === "decision_answered" || event.type === "decision_withdrawn") {
      void this.refreshPendingDecisions();
    }
  }

  // 订阅每一条到达的事件，返回取消订阅的函数；页面用它接收测试结果与候选采集的结果内容
  subscribeEvents(listener: (event: EventObject) => void): () => void {
    this.pageListeners.add(listener);
    return () => {
      this.pageListeners.delete(listener);
    };
  }

  // 缺口或 resync：把视图标为「数据可能过时」，重新查询它们的快照，再从快照位置中最小的一个重新订阅
  private async resync(): Promise<void> {
    if (!this.iface) {
      return;
    }
    const before = this.boot;
    const result = await connect(this.settings!);
    if (result.state !== "connected") {
      return;
    }
    // 本次启动的身份改变：重新读取能力清单（设计说明第 6.1 节）
    if (result.capabilities.deployment.boot_id !== before) {
      this.boot = result.capabilities.deployment.boot_id;
      this.capabilities = result.capabilities;
    }
    const position = await this.views!.refreshAll();
    this.closeStream();
    this.startStream(position);
    // 画面回到查询给出的状态，不补播已经播放过的动作
    for (const fn of [...this.resyncSubscribers]) fn();
  }

  async refreshPendingDecisions(): Promise<void> {
    if (!this.iface) {
      return;
    }
    const snapshot = await this.query<DecisionList>("decisions.list", { status: ["open"] });
    this.listeners.onPendingDecisions(snapshot.data.decisions.length);
  }

  private closeStream(): void {
    this.stream?.stop();
    this.stream = null;
  }

  close(): void {
    this.closeStream();
    this.views?.closeAll();
    this.iface = null;
  }
}
