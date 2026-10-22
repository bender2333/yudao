// 项目页面的读取失败与空态是两句话（工单 #775）：
// 读不出来时给失败提示与服务端给的原文；读出来且为空时给原来的空态文案。
// 页面各处按这个口径写（overview、department、observe、settings、recovery）。

import { test } from "node:test";
import assert from "node:assert/strict";

import { emptyOrFailureText, readFailureText } from "../../src/renderer/src/contract/read-failure.ts";
import { attemptsSummary } from "../../src/renderer/src/views/project/attempts-summary.ts";

test("读不出来：写「读取失败」与服务端给的原文", () => {
  const reason = "查询 project.overview 没有返回数据：Internal Server Error";
  assert.equal(readFailureText(reason), `读取失败：${reason}`);
  assert.equal(
    emptyOrFailureText(reason, "项目还没有流转记录"),
    `读取失败：${reason}`,
  );
});

test("读出来且为空：写原来的空态文案", () => {
  assert.equal(emptyOrFailureText(null, "项目还没有流转记录"), "项目还没有流转记录");
  assert.equal(emptyOrFailureText("", "项目还没有流转记录"), "项目还没有流转记录");
});

test("观测页：总数读不出来时说明读不出来，不安静地少一句数字", () => {
  const text = attemptsSummary({
    inFlight: 0,
    total: null,
    totalError: "查询 project.usage 没有返回数据：Internal Server Error",
    loaded: 50,
    more: false,
  });
  assert.match(text, /总数读不出来/);
  assert.match(text, /已显示 50 条/);
  // 不猜总数
  assert.equal(text.includes("共 "), false);
});
