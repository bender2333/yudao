// 视图同步（应用层与接口层设计说明第 5.7 节）。
// 每个视图保存快照与位置；位置不大于快照位置的事件不作用于这个视图；按能力清单中查询声明的事件种类
// 重新查询，200 毫秒内的多条事件合并为一次；切换项目或事项以后丢弃迟到的旧查询结果。

// 一次查询：名称与参数；转交应用层发出请求并返回快照（position 与 data）
export type QueryRunner = <T>(name: string, params: Record<string, unknown> | undefined) => Promise<{ position: number; data: T }>;

// 打开一个视图时登记的内容：查询名称与参数
export type ViewRequest = {
  query: string;
  params?: Record<string, unknown>;
};

type Entry = {
  query: string;
  params: Record<string, unknown> | undefined;
  changedBy: Set<string>;
  listeners: Set<(value: unknown) => void>;
  // 快照已经包含的最大全局位置；位置不大于它的事件不作用（设计说明第 5.7 节）
  position: number;
  active: boolean;
};

const COALESCE_MS = 200;

export class ViewSync {
  // 一个视图一个登记项（按视图标识区分，例如 "home"、"overview"）
  private readonly entries = new Map<string, Entry>();
  private readonly changedByQuery: Record<string, Set<string>> = {};
  private pending = new Set<string>();
  private timer: NodeJS.Timeout | null = null;
  private readonly runner: QueryRunner;

  constructor(runner: QueryRunner, capabilities: { queries: { name: string; changed_by: string[] }[] }) {
    this.runner = runner;
    for (const query of capabilities.queries) {
      this.changedByQuery[query.name] = new Set(query.changed_by);
    }
  }

  // 打开一个视图：立即查询一次并交给 listener，之后相关事件到达时重新查询。Data 由调用方的查询合同给出
  // 查询失败时（例如服务不可达）不通知、不抛出：调用处继续显示旧的或空的状态，由连接状态提示过时；
  // useSnapshot 另传 onError 把读取状态结束并带上失败的原因（工单 #728），避免「正在读取数据」一直不消失，
  // 也避免失败与「本来就没有内容」在界面上变成同一句话
  async open<Data>(viewId: string, request: ViewRequest, listener: (value: Data) => void,
                   onError?: (reason: string) => void): Promise<void> {
    this.close(viewId);
    const entry: Entry = {
      query: request.query,
      params: request.params,
      changedBy: this.changedByQuery[request.query] ?? new Set(),
      listeners: new Set([listener as (value: unknown) => void]),
      position: 0,
      active: true,
    };
    this.entries.set(viewId, entry);
    let snapshot: { position: number; data: Data } | null = null;
    let failure = "";
    try {
      snapshot = await this.runner<Data>(request.query, request.params);
    } catch (error) {
      snapshot = null;
      const message = error instanceof Error ? error.message : String(error);
      // 失败原因不能是空串：空串到了界面上与「没有失败」分不开
      failure = message === "" ? "这次读取没有成功" : message;
    }
    if (!entry.active || this.entries.get(viewId) !== entry) {
      // 迟到的结果：这个视图已经关闭或换了对象，丢弃（可观测性设计第 5 节）
      return;
    }
    if (snapshot === null) {
      onError?.(failure);
      return;
    }
    entry.position = snapshot.position;
    for (const target of entry.listeners) {
      target(snapshot.data);
    }
  }

  close(viewId: string): void {
    this.entries.delete(viewId);
  }

  closeAll(): void {
    this.entries.clear();
    this.pending.clear();
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  // 收到一条事件：位置不大于该视图快照位置的事件不作用；否则按种类排入合并队列
  applyEvent(type: string, position: number): void {
    for (const [viewId, entry] of this.entries) {
      if (!entry.active || position <= entry.position) {
        continue;
      }
      if (entry.changedBy.has(type)) {
        this.pending.add(viewId);
      }
    }
    if (this.pending.size > 0 && this.timer === null) {
      this.timer = setTimeout(() => {
        this.timer = null;
        const ids = [...this.pending];
        this.pending.clear();
        for (const viewId of ids) {
          void this.refresh(viewId);
        }
      }, COALESCE_MS);
    }
  }

  // 重新查询一个视图；视图期间关闭或换对象时丢弃迟到的结果。
  // 查询失败时保留旧快照与旧位置（服务恢复以后的事件会再触发重查），不抛出
  async refresh(viewId: string): Promise<void> {
    const entry = this.entries.get(viewId);
    if (!entry || !entry.active) {
      return;
    }
    let snapshot: { position: number; data: unknown } | null = null;
    try {
      snapshot = await this.runner(entry.query, entry.params);
    } catch {
      return;
    }
    if (!entry.active || this.entries.get(viewId) !== entry) {
      return;
    }
    entry.position = snapshot.position;
    for (const target of entry.listeners) {
      target(snapshot.data);
    }
  }

  // 重新查询全部已打开的视图，返回它们快照位置中最小的一个（重新订阅的起点，设计说明第 5.5 节）
  async refreshAll(): Promise<number> {
    const ids = [...this.entries.keys()];
    await Promise.all(ids.map((id) => this.refresh(id)));
    // 位置 0 表示「这个视图还没有快照」：不参与取最小值，
    // 否则一个刚打开或查询失败的视图会把重新订阅拖回 0（工单 #659）
    const positions = ids.map((id) => this.entries.get(id)?.position ?? 0).filter((value) => value > 0);
    return positions.length === 0 ? 0 : Math.min(...positions);
  }
}

/**
 * 重新订阅事件流的起点（工单 #659）。
 * 视图位置里 0 表示「还没有快照」，不算；也不能比事件流已经读到的位置更早——
 * 退回去会让服务重放整段历史，页面在重放期间拿不到稳定的数据，
 * 还会因为 previous 对不上再次重新同步，形成反复重订阅。
 */
export function resubscribePosition(viewPosition: number, streamPosition: number): number {
  const earliest = viewPosition > 0 ? viewPosition : 0;
  return Math.max(earliest, streamPosition);
}
