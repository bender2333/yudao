// 排空确认与提示的文案（工单 #663）：「开始排空」不可逆，确认里要说清后果与剩下的那条路；
// 排空期间新的事项只排队不开始，用户在别处也要能看出原因。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
DRAIN_CONFIRM_LINES,
DRAIN_CONFIRM_TITLE,
drainNoticeText
} from "../../src/renderer/src/views/system/drain-text.ts";

test("确认框写明后果：不再开始新事项、回不去、剩下的是强制升级", () => {
  const all = [DRAIN_CONFIRM_TITLE, ...DRAIN_CONFIRM_LINES].join("；");
  assert.match(all, /不再开始新的事项/);
  assert.match(all, /回不去/);
  assert.match(all, /强制升级/);
  assert.match(all, /运行与执行槽位/);
});

test("强制升级以后用项目的起点重新开始，不再说用已经采纳的成果（工单 #908）", () => {
  const all = DRAIN_CONFIRM_LINES.join("；");
  assert.match(all, /用项目的起点重新开始/);
  assert.match(all, /采纳成果/);
  assert.match(all, /起始文件夹/);
  assert.match(all, /空树/);
  assert.doesNotMatch(all, /用已经采纳的成果重新开始/);
});


test("排空期间给出提示，说明新的事项为什么没有开始", () => {
  const draining = drainNoticeText("draining");
  assert.notEqual(draining, null);
  assert.match(draining ?? "", /排队/);
  assert.match(draining ?? "", /停止开始新事项/);
  assert.notEqual(drainNoticeText("ready"), null);
});

test("提示写清下一步：装上新的版本重新启动，排空会解除（工单 #731）", () => {
  for (const state of ["draining", "ready"]) {
    const text = drainNoticeText(state) ?? "";
    assert.match(text, /新的版本/);
    assert.match(text, /重新启动/);
    assert.match(text, /重新开始新事项|排空会解除/);
  }
});

test("没有排空时不出现这句提示", () => {
  assert.equal(drainNoticeText("idle"), null);
  assert.equal(drainNoticeText(null), null);
  assert.equal(drainNoticeText(undefined), null);
});
