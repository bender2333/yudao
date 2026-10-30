// 排空确认与提示的文案（工单 #663）：「开始排空」不可逆，确认里要说清后果与剩下的那条路；
// 排空期间新的事项只排队不开始，用户在别处也要能看出原因。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
DRAIN_CONFIRM_LINES,
DRAIN_CONFIRM_TITLE,
DRAIN_STATE_TEXT,
FORCE_UPGRADE_CONFIRM_CANCEL,
FORCE_UPGRADE_CONFIRM_CONFIRM,
FORCE_UPGRADE_CONFIRM_LINES,
FORCE_UPGRADE_CONFIRM_TITLE,
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

test("排空状态的中文名照原型：第四种是「已强制升级」（工单 #1187）", () => {
  // 期望值写成字面值，与原型 v13 js/ui/views/sys-runtime.js 的 DRAIN_LABELS 一致；页面上不出现 idle、forced 这些取值
  assert.equal(DRAIN_STATE_TEXT.idle, "未排空");
  assert.equal(DRAIN_STATE_TEXT.draining, "排空中");
  assert.equal(DRAIN_STATE_TEXT.ready, "已排空，可以升级");
  assert.equal(DRAIN_STATE_TEXT.forced, "已强制升级");
});

test("强制升级的确认框说明会让正在进行的 run 记为因升级停止，并写清起点（工单 #1187）", () => {
  const all = [FORCE_UPGRADE_CONFIRM_TITLE, ...FORCE_UPGRADE_CONFIRM_LINES].join("；");
  assert.match(all, /因升级停止/);
  assert.match(all, /正在进行的 run/);
  assert.match(all, /项目的起点/);
  assert.match(all, /采纳成果/);
  assert.match(all, /起始文件夹/);
  assert.match(all, /空树/);
  assert.match(all, /已强制升级/);
  // 确认与不做的按钮各一句
  assert.equal(FORCE_UPGRADE_CONFIRM_CONFIRM, "确认强制升级");
  assert.equal(FORCE_UPGRADE_CONFIRM_CANCEL, "先不升级");
});
