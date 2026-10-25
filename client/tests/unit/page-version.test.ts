// 页面文件与服务不匹配时的处理（工单 #704、#909）：按两个接口版本哪一边新说明该做什么。

import { test } from "node:test";
import assert from "node:assert/strict";

import { mismatchAdvice, reloadHelps } from "../../src/renderer/src/contract/page-version.ts";

test("服务比页面新：重新构建页面文件，重新加载有用", () => {
  const mismatch = { pageVersion: 6, serverVersion: 7 };
  assert.equal(reloadHelps(mismatch), true);
  const advice = mismatchAdvice(mismatch);
  assert.equal(advice.reloadHelps, true);
  assert.match(advice.text, /页面文件的接口版本是 6/);
  assert.match(advice.text, /服务要的是 7/);
  assert.match(advice.text, /重新构建页面文件/);
  assert.match(advice.text, /harness\/release_assets/);
});

test("页面比服务新：服务在跑旧的代码，重启服务，重新加载没有用", () => {
  const mismatch = { pageVersion: 7, serverVersion: 6 };
  assert.equal(reloadHelps(mismatch), false);
  const advice = mismatchAdvice(mismatch);
  assert.equal(advice.reloadHelps, false);
  assert.match(advice.text, /页面文件的接口版本是 7/);
  assert.match(advice.text, /服务要的是 6/);
  assert.match(advice.text, /重启 Yudao 服务/);
  assert.doesNotMatch(advice.text, /重新构建页面文件/);
});
