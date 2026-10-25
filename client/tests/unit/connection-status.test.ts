// 顶栏的连接状态三档（工单 #653）：连接中、已连接、连接中断。
// 三档由事件流的状态本身给出：还没连上过与连上以后断了不靠「断开时间为空」猜，
// 「连接中断」只在真的断开以后出现，断开的时间是那一刻的真实时刻。

import { test } from "node:test";
import assert from "node:assert/strict";
import { nextStreamState, type StreamState } from "../../src/renderer/src/contract/stream-state.ts";
import { connectionText } from "../../src/renderer/src/views/project/labels.ts";

const CONNECTING: StreamState = { kind: "connecting" };
const CONNECTED: StreamState = { kind: "connected" };
const INTERRUPTED: StreamState = { kind: "interrupted", disconnectedAt: "2026-10-22T08:30:00.000Z" };

test("还没连上：顶栏说连接中，不出现「连接中断」也不出现「刚刚断开」", () => {
  const text = connectionText(CONNECTING);
  assert.match(text, /连接中/);
  assert.equal(text.includes("连接中断"), false);
  assert.equal(text.includes("刚刚"), false);
});

test("连上了：顶栏说已连接", () => {
  assert.equal(connectionText(CONNECTED), "已连接");
});

test("连上以后断开：顶栏说连接中断并写明断开的时间，不用「刚刚」兜底", () => {
  const text = connectionText(INTERRUPTED);
  assert.match(text, /连接中断/);
  assert.match(text, /正在重新连接/);
  assert.equal(text.includes("刚刚"), false);
  // 写的是断开那一刻的时刻，不是别的时刻
  assert.equal(text.includes("2026"), false, text);
  assert.match(text, /\d{2}:\d{2}/, text);
});


test("连接中的失败不改状态：还在连接中，不产生连接中断", () => {
  const next = nextStreamState(CONNECTING, false, "2026-10-22T08:30:00.000Z");
  assert.equal(next.kind, "connecting");
  assert.equal(next, CONNECTING);
});

test("连上以后断开：状态变成连接中断并带上那一刻", () => {
  const at = "2026-10-22T08:30:00.000Z";
  const next = nextStreamState(CONNECTED, false, at);
  assert.equal(next.kind, "interrupted");
  assert.equal((next as { disconnectedAt: string }).disconnectedAt, at);
});

test("重连成功以后回到已连接", () => {
  const next = nextStreamState(INTERRUPTED, true, "2026-10-22T08:31:00.000Z");
  assert.equal(next.kind, "connected");
});

test("状态没有变化时不重新通知", () => {
  assert.equal(nextStreamState(CONNECTED, true, "2026-10-22T08:30:00.000Z"), CONNECTED);
  assert.equal(nextStreamState(CONNECTING, false, "2026-10-22T08:30:00.000Z"), CONNECTING);
});
