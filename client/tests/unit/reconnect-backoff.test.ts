// 断线以后的退避（工单 #679）：计数只在连接站得住以后清零。
// 收到过至少一帧才算站得住；仅仅「打开」不算——服务端在流中途抛异常时，
// 客户端先收到 open 再收到 error，一打开就清零会让退避永远停在 1 秒。

import { test } from "node:test";
import assert from "node:assert/strict";
import { ReconnectBackoff } from "../../src/renderer/src/contract/reconnect-backoff.ts";

test("连不上：等待时间按 1、2、4……秒递增，30 秒封顶", () => {
  const backoff = new ReconnectBackoff();
  assert.equal(backoff.nextDelayMs(), 1000);
  assert.equal(backoff.nextDelayMs(), 2000);
  assert.equal(backoff.nextDelayMs(), 4000);
  assert.equal(backoff.nextDelayMs(), 8000);
  for (let index = 0; index < 10; index += 1) {
    backoff.nextDelayMs();
  }
  assert.equal(backoff.nextDelayMs(), 30000);
});

test("打开以后立刻断开：还没收到帧，退避照样递增（不回到 1 秒）", () => {
  // 工单 #679 的现象：服务端在流中途抛异常，客户端先收到 open 再收到 error；
  // 打开不算站得住，退避不能被清零
  const backoff = new ReconnectBackoff();
  assert.equal(backoff.nextDelayMs(), 1000);
  assert.equal(backoff.nextDelayMs(), 2000);
  // 打开连接（不算站得住）
  assert.equal(backoff.count, 2);
});

test("收到帧以后断开：连接站住了，下一次从 1 秒重新算", () => {
  const backoff = new ReconnectBackoff();
  assert.equal(backoff.nextDelayMs(), 1000);
  assert.equal(backoff.nextDelayMs(), 2000);
  backoff.stoodUp();
  assert.equal(backoff.count, 0);
  assert.equal(backoff.nextDelayMs(), 1000);
});

test("上界与基数可以按需要给定", () => {
  const backoff = new ReconnectBackoff(100, 1000);
  assert.equal(backoff.nextDelayMs(), 100);
  assert.equal(backoff.nextDelayMs(), 200);
  assert.equal(backoff.nextDelayMs(), 400);
  for (let index = 0; index < 10; index += 1) {
    backoff.nextDelayMs();
  }
  assert.equal(backoff.nextDelayMs(), 1000);
});
