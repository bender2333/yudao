// 一次按需读取的失败处理（工单 #777）：读不出来时失败有去处，不产生未处理的拒绝。
// 「读不出来」与「本来就没有内容」在页面上是两句话。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  emptyOrFailureText,
  failureReason,
  optionalRead,
  readFailureText,
} from "../../src/renderer/src/contract/read-failure.ts";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test("读成了就把结果交给调用处", async () => {
  const values: string[] = [];
  const reasons: string[] = [];
  optionalRead(
    Promise.resolve("读到了"),
    (value) => values.push(value),
    (reason) => reasons.push(reason),
  );
  await delay(0);
  assert.deepEqual(values, ["读到了"]);
  assert.deepEqual(reasons, []);
});

test("读不出来时失败原因交给调用处，不产生未处理的拒绝", async () => {
  const values: string[] = [];
  const reasons: string[] = [];
  optionalRead(
    Promise.reject(new Error("查询 project.overview 没有返回数据：Failed to fetch")),
    (value) => values.push(value),
    (reason) => reasons.push(reason),
  );
  await delay(0);
  assert.deepEqual(values, []);
  // 服务端给的原文按原文带出（2026-10-22 的决定）
  assert.deepEqual(reasons, ["查询 project.overview 没有返回数据：Failed to fetch"]);
});

test("失败没有原文时写清这次读取没有成功，不写空串", () => {
  assert.equal(failureReason(new Error("")), "这次读取没有成功");
  assert.equal(failureReason(undefined), "这次读取没有成功");
  assert.equal(failureReason(""), "这次读取没有成功");
  // 服务端给了原文就按原文带出
  assert.equal(failureReason("Internal Server Error"), "Internal Server Error");
  assert.equal(failureReason({ error: "找不到这个事件" }), "找不到这个事件");
});

test("读不出来与本来就没有内容，说的是两句话", () => {
  assert.equal(
    readFailureText(failureReason(new Error("查询 projects.list 没有返回数据"))),
    "读取失败：查询 projects.list 没有返回数据",
  );
  assert.equal(emptyOrFailureText(null, "没有符合的项目"), "没有符合的项目");
});
