// 页面文件与服务不匹配时的处理（工单 #704）：重新加载有没有用、用户该做什么。

import { test } from "node:test";
import assert from "node:assert/strict";

import { mismatchAdvice, reloadHelps } from "../../src/renderer/src/contract/page-version.ts";

test("只有接口版本不同时重载没有用：服务那边的页面文件还是这一份", () => {
  const mismatch = { pageVersion: 6, serverVersion: 7, sameRelease: true };
  assert.equal(reloadHelps(mismatch), false);
  const advice = mismatchAdvice(mismatch);
  assert.equal(advice.reloadHelps, false);
  assert.match(advice.text, /页面文件的接口版本是 6/);
  assert.match(advice.text, /服务要的是 7/);
  assert.match(advice.text, /重新构建页面文件/);
  assert.match(advice.text, /harness\/release_assets/);
});

test("发布版本也不同时重载有用：服务那边换了一版页面文件", () => {
  const mismatch = { pageVersion: 6, serverVersion: 7, sameRelease: false };
  assert.equal(reloadHelps(mismatch), true);
  const advice = mismatchAdvice(mismatch);
  assert.equal(advice.reloadHelps, true);
  assert.match(advice.text, /重新加载可以取到与服务匹配的那一份/);
  assert.doesNotMatch(advice.text, /重新构建页面文件/);
});
