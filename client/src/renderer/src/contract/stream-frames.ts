// 事件流的帧解析与位置核对（应用层与接口层设计说明第 5.4、5.5、5.6 节）。
// 从 eventsource 收到的 SSE 帧里解析出事件、检查点、片段与 resync，并核对 previous。
// 这里只做数据转换，不接触网络，便于用 node --test 直接核对。

import type { EventObject, OutputDelta } from "../api/generated/types.gen";

export type StreamMessage =
  | { kind: "event"; position: number; previous: number; event: EventObject }
  | { kind: "checkpoint"; position: number; previous: number }
  | { kind: "delta"; delta: OutputDelta }
  | { kind: "gap"; expected: number; got: number }
  | { kind: "resync"; reason: string; endPosition: number };

// 解析一条 SSE 帧；eventName 是 SSE 的 event 字段（event/checkpoint/delta/resync）
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
    // 片段不带 id，不改变续传位置（第 5.6 节）
    return { kind: "delta", delta: JSON.parse(data) as OutputDelta };
  }
  if (eventName === "resync") {
    const frame = JSON.parse(data) as { reason: string; end_position: number };
    return { kind: "resync", reason: frame.reason, endPosition: frame.end_position };
  }
  throw new Error(`未知的事件流帧：${eventName}`);
}

// 帧到达以后新的位置：事件与检查点推进位置，片段与 resync 不推进
export function nextPosition(message: StreamMessage, current: number): number {
  if (message.kind === "event" || message.kind === "checkpoint") {
    return message.position;
  }
  return current;
}

export function streamUrl(baseUrl: string, scope: StreamScope, after: number): string {
  const params = new URLSearchParams();
  params.set("after", String(after));
  for (const key of ["project", "work_item", "run", "department", "role", "type"] as const) {
    for (const value of scope[key] ?? []) {
      params.append(key, value);
    }
  }
  if (scope.live) {
    params.set("live", "1");
  }
  return `${baseUrl}/api/events?${params.toString()}`;
}

// 客户端订阅的筛选范围；省略的条件不限制（与服务端 GET /api/events 的参数一致）
export type StreamScope = {
  project?: string[];
  work_item?: string[];
  run?: string[];
  department?: string[];
  role?: string[];
  type?: string[];
  live?: boolean;
};
