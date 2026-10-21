// 事件流的状态与状态迁移（工单 #653）。
// 三档由状态本身给出：还没连上（connecting）、连上了（connected）、连上以后断开（interrupted）。
// 「连接中断」只在这一档出现，断开的时间由状态带着；
// 界面分辨「还没连上过」与「连上以后断了」不靠「断开时间为空」猜。
//
// 这个模块没有依赖：页面、顶栏与客户端共用它，单元测试也直接调用它。

export type StreamState =
  | { kind: "connecting" }
  | { kind: "connected" }
  | { kind: "interrupted"; disconnectedAt: string };

// 状态迁移：连接中 → 已连接 → 连接中断 → 已连接。
// 建立之前的连接失败不改状态：流自己在退避重试，这时仍是「连接中」，
// 说成「刚刚断开」是不实描述。at 是这一次中断的时刻，由调用处给出。
// 状态没有变化时返回原来的那一个，调用处据此知道不用再通知界面。
export function nextStreamState(current: StreamState, connected: boolean, at: string): StreamState {
  if (connected) {
    return current.kind === "connected" ? current : { kind: "connected" };
  }
  if (current.kind === "connected") {
    return { kind: "interrupted", disconnectedAt: at };
  }
  return current;
}
