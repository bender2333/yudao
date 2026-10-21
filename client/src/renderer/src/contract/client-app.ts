// 页面的连接生命周期（应用层与接口层设计说明第 5.7、6.1 节，原型 v8 设计说明第 3.4 节）。
// 状态：连接中 / 已连接 / 接口版本不同 / 连接失败。
// 已连接以后：保持一条不按项目筛选的事件流连接；收到事件按视图同步规则重新查询；
// 发现缺口或收到 resync 时重新查询已打开的视图，再按快照位置中最小的一个重新订阅；
// 本次启动的身份改变（服务重启）时重新读取能力清单并重新同步。

import type { Capabilities, DecisionList, EventObject, OutputDelta } from "../api/generated/types.gen";
import { connect, interfaceFor, type Interface } from "./connection";
import { EventStreamClient } from "./event-stream";
import { callCommand, type CommandOutcome } from "./invoke";
import { nextStreamState, type StreamState } from "./stream-state";
import { ViewSync, resubscribePosition } from "./view-sync";

export type ClientState =
  | { kind: "connecting" }
  | { kind: "outdated"; address: string; clientVersion: number; serverVersion: number; serverRelease: string }
  | { kind: "failed"; address: string; message: string }
  // connected 是服务已经连上；事件流本身有三种状态（工单 #653）：
  // connecting 是还没连上（正在建立），connected 是连上了，interrupted 是连上以后断开的。
  // interrupted 自己带着断开的时间：界面分「还没连上过」与「连上以后断了」不靠猜。
  | { kind: "connected"; address: string; capabilities: Capabilities; stream: StreamState }
  // unauthorized 是局域网访问方式下没有令牌或令牌无效（第 6.3 节）：页面显示填写令牌的表单
  | { kind: "unauthorized"; address: string };

export type ClientListeners = {
  onState: (state: ClientState) => void;
  // 待决定的数量（跨项目等待回答的决定请求）：顶栏显示
  onPendingDecisions: (count: number) => void;
};

// 把查询与命令交给生成的应用层接口；外壳提供它们，以便单元测试注入替身
export type QueryRunner = <T>(client: Interface["client"], name: string, params: Record<string, unknown> | undefined) => Promise<{ position: number; data: T }>;

export class ClientApp {
  private iface: Interface | null = null;
  private stream: EventStreamClient | null = null;
  private views: ViewSync | null = null;
  private boot: string | null = null;
  private capabilities: Capabilities | null = null;
  // 事件流的状态：连接中、已连接、连上以后断开（工单 #653）
  private streamState: StreamState = { kind: "connecting" };
  // 局域网访问方式的访问令牌（第 6.3 节）：查询、命令与事件流都在请求头里带上它
  private token = "";
  // 页面级的事件订阅：视图同步之外，页面还需要测试与候选等事件的结果内容（工单 #93），
  // 项目楼层这类按事件播放动作的画面也用它（工单 #82）
  private readonly pageListeners = new Set<(event: EventObject) => void>();
  // 项目楼层的重新同步订阅：缺口、断线重连、resync 时画面回到查询给出的状态
  private readonly resyncSubscribers = new Set<() => void>();
  // 输出片段订阅：部门房间的思考气泡按 offset 拼接模型输出（工单 #177）。片段不写入事件日志，只经流送达
  private readonly deltaListeners = new Set<(delta: OutputDelta) => void>();

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

  // 连接页面自己的来源：读取能力清单并核对接口版本。
  // token 是局域网访问方式的访问令牌（第 6.3 节）：本机访问方式为空串
  async open(address: string, token = ""): Promise<void> {
    this.closeStream();
    this.token = token;
    this.listeners.onState({ kind: "connecting" });
    const result = await connect(address, token);
    if (result.state === "outdated") {
      this.listeners.onState({
        kind: "outdated", address: result.address, clientVersion: result.clientVersion,
        serverVersion: result.serverVersion, serverRelease: result.serverRelease,
      });
      return;
    }
    if (result.state === "unauthorized") {
      this.listeners.onState({ kind: "unauthorized", address: result.address });
      return;
    }
    if (result.state === "failed") {
      this.listeners.onState({ kind: "failed", address: result.address, message: result.message });
      return;
    }
    this.iface = interfaceFor(result.address, token);
    this.capabilities = result.capabilities;
    this.boot = result.capabilities.deployment.boot_id;
    this.views = new ViewSync((name, params) => this.query(name, params), result.capabilities);
    // 事件流还没有开始：这一段是「连接中」，不是「刚刚断开」（工单 #653）
    this.streamState = { kind: "connecting" };
    this.listeners.onState({
      kind: "connected", address: result.address, capabilities: result.capabilities, stream: this.streamState,
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

  // 页面按需查询一次（设计说明第 5.7 节）：与视图同步走同一条查询通道，
  // 结果不进入视图缓存。删除与保存前取回影响列表（工单 #94）使用这个入口
  queryOne<T>(name: string, params: Record<string, unknown> | undefined): Promise<{ position: number; data: T }> {
    return this.query<T>(name, params);
  }

  // 不按项目筛选的事件流：窗口关闭时也保持（设计说明第 5.7 节）。
  // live=1：连接接收模型输出片段（delta 帧），部门房间的思考气泡据此逐字显示（工单 #177）
  private startStream(after: number): void {
    this.stream = new EventStreamClient(this.iface!.baseUrl, { live: true }, {
      onConnected: () => this.setStreamConnected(true),
      onInterrupted: () => this.setStreamConnected(false),
      onResync: () => void this.resync(),
      onMessage: (message) => {
        if (message.kind === "event") {
          this.onEvent(message.event);
        } else if (message.kind === "delta") {
          for (const listener of [...this.deltaListeners]) {
            listener(message.delta);
          }
        }
      },
    }, this.token);
    this.stream.start(after);
  }

  private setStreamConnected(connected: boolean): void {
    if (!this.capabilities) {
      return;
    }
    const next = nextStreamState(this.streamState, connected, new Date().toISOString());
    if (next === this.streamState) {
      return;
    }
    this.streamState = next;
    this.listeners.onState({
      kind: "connected", address: this.iface!.baseUrl, capabilities: this.capabilities, stream: this.streamState,
    });
  }

  private onEvent(event: EventObject): void {
    this.views?.applyEvent(event.type, event.position);
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

  // 订阅模型输出片段：部门房间的思考气泡按 offset 把片段接在 attempt.live 之后（工单 #177）。
  // 片段不写入事件日志，只经事件流的 delta 帧送达
  subscribeDeltas(listener: (delta: OutputDelta) => void): () => void {
    this.deltaListeners.add(listener);
    return () => {
      this.deltaListeners.delete(listener);
    };
  }

  // 缺口或 resync：把视图标为「数据可能过时」，重新查询它们的快照，再从快照位置中最小的一个重新订阅。
  // 查询失败（服务不可达）时保留旧流：流自身的退避重连会继续尝试，服务恢复以后自动恢复
  private async resync(): Promise<void> {
    if (!this.iface) {
      return;
    }
    try {
      const before = this.boot;
      const result = await connect(this.iface.baseUrl, this.token);
      if (result.state !== "connected") {
        return;
      }
      // 本次启动的身份改变：重新读取能力清单（设计说明第 6.1 节）
      if (result.capabilities.deployment.boot_id !== before) {
        this.boot = result.capabilities.deployment.boot_id;
        this.capabilities = result.capabilities;
      }
      // 重新订阅的起点：视图位置与事件流已读到的位置里更晚的那个（工单 #659），
      // 不往回退——退回去会重放整段历史，页面反复重新同步
      const position = resubscribePosition(await this.views!.refreshAll(), this.stream?.position ?? 0);
      this.closeStream();
      this.startStream(position);
      // 画面回到查询给出的状态，不补播已经播放过的动作
      for (const fn of [...this.resyncSubscribers]) fn();
    } catch {
      return;
    }
  }

  async refreshPendingDecisions(): Promise<void> {
    if (!this.iface) {
      return;
    }
    try {
      const snapshot = await this.query<DecisionList>("decisions.list", { status: ["open"] });
      this.listeners.onPendingDecisions(snapshot.data.decisions.length);
    } catch {
      // 服务不可达：保留旧的数量，不写控制台错误
    }
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
