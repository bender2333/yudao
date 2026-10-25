// 项目页面的读取失败与空态是两句话（工单 #775）：
// 读不出来时给失败提示与服务端给的原文；读出来且为空时给原来的空态文案。
// 页面各处按这个口径写（overview、department、observe、settings、recovery）。

import { test } from "node:test";
import assert from "node:assert/strict";

import { attemptsSummary } from "../../src/renderer/src/views/project/attempts-summary.ts";



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
