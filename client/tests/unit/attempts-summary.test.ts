// 观测页副标题的计数说法（工单 #665）：范围里的模型请求总数与已经加载出来的行数
// 是两个数，不混在一起说；口径与「用量统计」页签一致。

import { test } from "node:test";
import assert from "node:assert/strict";
import { attemptsSummary } from "../../src/renderer/src/views/project/attempts-summary.ts";

test("总数与已显示的行数分开说，不把已加载的行数说成总数", () => {
  const text = attemptsSummary({ inFlight: 0, total: 115, loaded: 50, more: true });
  assert.match(text, /共 115 次模型请求/);
  assert.match(text, /已显示 50 条/);
  assert.equal(text.includes("共 50 条记录"), false);
  assert.equal(text.includes("条记录"), false);
});


test("总数还没有读到时只说已显示的行数", () => {
  const text = attemptsSummary({ inFlight: 2, total: null, loaded: 20, more: false });
  assert.equal(text.includes("共 "), false);
  assert.match(text, /已显示 20 条/);
  assert.match(text, /2 个请求进行中/);
});

