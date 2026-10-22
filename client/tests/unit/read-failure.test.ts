// 读取失败的说明（工单 #728）：服务端给的说明按原文带出来，界面要能把它与「本来就没有内容」分开。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  emptyOrFailureText,
  queryFailureText,
  readFailureText,
} from "../../src/renderer/src/contract/read-failure.ts";

test("服务端给了说明就带上它的原文：404 的错误体是 {error: 说明}", () => {
  const text = queryFailureText("event.detail", { error: "找不到这个事件" });
  assert.equal(text, "查询 event.detail 没有返回数据：找不到这个事件");
});

test("服务端的错误体是文本时按原文带出", () => {
  assert.equal(
    queryFailureText("event.detail", "Internal Server Error"),
    "查询 event.detail 没有返回数据：Internal Server Error",
  );
});

test("错误体是对象但没有可读的字段时把整个原文写出来", () => {
  const text = queryFailureText("event.detail", { detail: [{ loc: ["query", "event_id"] }] });
  assert.equal(text, "查询 event.detail 没有返回数据：" + JSON.stringify({ detail: [{ loc: ["query", "event_id"] }] }));
});

test("没有说明时只说哪个查询没有返回数据，不猜原因", () => {
  assert.equal(queryFailureText("projects.list", undefined), "查询 projects.list 没有返回数据");
  assert.equal(queryFailureText("projects.list", null), "查询 projects.list 没有返回数据");
  assert.equal(queryFailureText("projects.list", ""), "查询 projects.list 没有返回数据");
});

test("读取失败时给一句「读取失败」与原因", () => {
  assert.equal(readFailureText("查询 projects.list 没有返回数据"), "读取失败：查询 projects.list 没有返回数据");
});

test("读不出来与本来就没有内容，说的是两句话", () => {
  // 工单 #728：失败与空在页面上不能是同一句陈述
  assert.equal(
    emptyOrFailureText("查询 projects.list 没有返回数据", "没有符合的项目"),
    "读取失败：查询 projects.list 没有返回数据",
  );
  assert.equal(emptyOrFailureText(null, "没有符合的项目"), "没有符合的项目");
  assert.equal(emptyOrFailureText("", "没有符合的项目"), "没有符合的项目");
});
