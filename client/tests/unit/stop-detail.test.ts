// 上游失败的提示要指名（工单 #1373）：停止原因是模型服务时，页面上写清哪个部门、请求的哪个模型、
// 服务返回的什么状态码，以及这次失败可不可重试。此前卡片只有一句原文
// 「Model provider returned HTTP 503」，用户分辨不出是上游挂了还是自己配错了。
//
// 同一项目里几张同名的失败卡片也要能分辨：写事项标识与停止的时间（哪张、什么时候停的）。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  formatTime,
  stopDetailText,
  stoppedCardLine,
} from "../../src/renderer/src/views/project/labels.ts";

const MODEL = "wb/cn:deepseek-v4.1-flash";

test("失败提示写出部门、请求的模型、状态码与不可重试", () => {
  assert.equal(
    stopDetailText({
      department: "engineering",
      requested_model: MODEL,
      status_code: 503,
      retryable: false,
    }),
    `工程部门请求的模型 ${MODEL}，服务返回 HTTP 503，不可重试`,
  );
});

test("失败提示里出现模型名与状态码", () => {
  const text = stopDetailText({
    department: "product", requested_model: MODEL, status_code: 401, retryable: false,
  });
  assert.ok(text !== null);
  assert.ok(text.includes(MODEL), text);
  assert.ok(text.includes("HTTP 401"), text);
  assert.ok(text.includes("产品部门"), text);
});

test("这次失败可重试时写「可重试」", () => {
  assert.equal(
    stopDetailText({ department: "quality", requested_model: MODEL, status_code: 429, retryable: true }),
    `质检部门请求的模型 ${MODEL}，服务返回 HTTP 429，可重试`,
  );
});

test("缺哪一项就不写哪一项，四项都没有时没有这一行", () => {
  assert.equal(stopDetailText({ status_code: 502 }), "服务返回 HTTP 502");
  assert.equal(stopDetailText({ requested_model: MODEL }), `请求的模型 ${MODEL}`);
  assert.equal(stopDetailText({ department: "engineering" }), "工程部门");
  assert.equal(stopDetailText({ retryable: true }), "可重试");
  assert.equal(stopDetailText(null), null);
  assert.equal(stopDetailText(undefined), null);
  assert.equal(stopDetailText({}), null);
});

test("同一项目里两张失败的卡片靠事项标识与停止时间分辨", () => {
  const first = { work_item_id: "wi_aa8b1fd2548f43f4", stopped_at: "2026-10-31T08:08:29Z" };
  const second = { work_item_id: "wi_bb8b1fd2548f43f4", stopped_at: "2026-10-31T08:11:03Z" };
  const firstLine = stoppedCardLine(first);
  const secondLine = stoppedCardLine(second);
  assert.notEqual(firstLine, secondLine);
  assert.equal(firstLine, `事项标识 ${first.work_item_id} · 停止于 ${formatTime(first.stopped_at)}`);
  assert.ok(secondLine.includes(second.work_item_id), secondLine);
  assert.ok(secondLine.includes(formatTime(second.stopped_at)), secondLine);
});

test("停止的时间缺失时照页面上其余时间的写法写未知时间", () => {
  assert.equal(stoppedCardLine({ work_item_id: "wi_1" }), "事项标识 wi_1 · 停止于 未知时间");
});
