// 事件流帧解析与位置核对的单元测试（应用层与接口层设计说明第 5.4、5.5、5.6 节）。
// 用真实运行的服务返回的帧形状（见工单核对时抓取的 SSE 帧）；不需要 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { nextPosition, parseFrame, streamUrl } from "../../src/renderer/src/contract/stream-frames.ts";

const EVENT = JSON.stringify({
  position: 3,
  previous: 2,
  event_id: "pevt_1",
  at: "2026-09-30T10:00:00Z",
  stream: "project:proj_1",
  stream_version: 1,
  project_id: "proj_1",
  work_item_id: null,
  run_id: null,
  department: null,
  role: null,
  actor: "user:local",
  command_id: null,
  label: "项目登记",
  type: "project_registered",
  payload: {},
});

test("previous 等于已收到的位置时接受事件并推进位置", () => {
  const parsed = parseFrame("event", EVENT, 2);
  assert.equal(parsed.kind, "event");
  assert.equal(parsed.position, 3);
  assert.equal(nextPosition(parsed, 2), 3);
});

test("previous 与已收到的位置不符时报告缺口，不推进位置", () => {
  const parsed = parseFrame("event", EVENT, 5);
  assert.deepEqual(parsed, { kind: "gap", expected: 5, got: 2 });
  assert.equal(nextPosition(parsed, 5), 5);
});

test("检查点核对 previous 并推进位置", () => {
  const parsed = parseFrame("checkpoint", JSON.stringify({ position: 7, previous: 3 }), 3);
  assert.equal(parsed.kind, "checkpoint");
  assert.equal(nextPosition(parsed, 3), 7);
});

test("片段不推进位置", () => {
  const parsed = parseFrame("delta", JSON.stringify({ attempt_id: "a", channel: "output", offset: 0, text: "好" }), 3);
  assert.equal(parsed.kind, "delta");
  assert.equal(nextPosition(parsed, 3), 3);
});

test("resync 带原因与末尾位置", () => {
  const parsed = parseFrame("resync", JSON.stringify({ reason: "queue_overflow", end_position: 9 }), 3);
  assert.deepEqual(parsed, { kind: "resync", reason: "queue_overflow", endPosition: 9 });
});

test("订阅地址带上范围参数与续传位置", () => {
  const url = streamUrl("http://127.0.0.1:8765", { project: ["p1"], type: ["transition", "qa_submitted"], live: true }, 12);
  const parsed = new URL(url);
  assert.equal(parsed.pathname, "/api/events");
  assert.equal(parsed.searchParams.get("after"), "12");
  assert.deepEqual(parsed.searchParams.getAll("project"), ["p1"]);
  assert.deepEqual(parsed.searchParams.getAll("type"), ["transition", "qa_submitted"]);
  assert.equal(parsed.searchParams.get("live"), "1");
});

test("不按项目筛选时不带范围参数", () => {
  const parsed = new URL(streamUrl("http://127.0.0.1:8765", {}, 0));
  assert.equal(parsed.searchParams.has("project"), false);
  assert.equal(parsed.searchParams.get("after"), "0");
});
