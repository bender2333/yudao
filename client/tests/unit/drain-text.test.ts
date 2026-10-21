// 排空确认与提示的文案（工单 #663）：「开始排空」不可逆，确认里要说清后果与剩下的那条路；
// 排空期间新的事项只排队不开始，用户在别处也要能看出原因。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DRAIN_CONFIRM_CANCEL,
  DRAIN_CONFIRM_CONFIRM,
  DRAIN_CONFIRM_LINES,
  DRAIN_CONFIRM_TITLE,
  drainNoticeText,
} from "../../src/renderer/src/views/system/drain-text.ts";

test("确认框写明后果：不再开始新事项、回不去、剩下的是强制升级", () => {
  const all = [DRAIN_CONFIRM_TITLE, ...DRAIN_CONFIRM_LINES].join("；");
  assert.match(all, /不再开始新的事项/);
  assert.match(all, /回不去/);
  assert.match(all, /强制升级/);
  assert.match(all, /运行与执行槽位/);
});

test("确认与取消两个按钮的措辞是用户看得懂的话", () => {
  assert.equal(DRAIN_CONFIRM_CONFIRM, "不再开始新事项");
  assert.equal(DRAIN_CONFIRM_CANCEL, "先不开始");
  assert.equal(DRAIN_CONFIRM_LINES.length >= 3, true);
});

test("排空期间给出提示，说明新的事项为什么没有开始", () => {
  const draining = drainNoticeText("draining");
  assert.notEqual(draining, null);
  assert.match(draining ?? "", /排队/);
  assert.match(draining ?? "", /停止开始新事项/);
  assert.notEqual(drainNoticeText("ready"), null);
});

test("没有排空时不出现这句提示", () => {
  assert.equal(drainNoticeText("idle"), null);
  assert.equal(drainNoticeText(null), null);
  assert.equal(drainNoticeText(undefined), null);
});
