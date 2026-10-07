// 路径里的回放位置（设计说明第 3.3 节第 108 行，工单 #296）：位置写在 ?at= 中，
// 非负整数才认；paths 构造时保留参数，回到现在时路径不带 at。

import { test } from "node:test";
import assert from "node:assert/strict";

import { parseRoute, paths } from "../../src/renderer/src/shell/routing.ts";

test("回放位置从 at 参数读出，缺省与非法输入按实时画面", () => {
  assert.equal(parseRoute("#/home").at, null);
  assert.equal(parseRoute("#/home?at=42").at, 42);
  assert.equal(parseRoute("#/p/p1/overview?at=0").at, 0);
  assert.equal(parseRoute("#/p/p1/overview?at=abc").at, null);
  assert.equal(parseRoute("#/home?at=-3").at, null);
  assert.equal(parseRoute("#/home?at=1.5").at, null);
});

test("回放位置与其它参数共存：读回 at 也不丢掉 w", () => {
  const route = parseRoute("#/p/p1/dept/product?w=w1&at=17");
  assert.equal(route.at, 17);
  assert.equal(route.workItemId, "w1");
  assert.equal(route.name, "dept");
});

test("构造首页与概览的路径：带回放位置时带 at，回到现在时不带", () => {
  assert.equal(paths.homeAt(42), "#/home?at=42");
  assert.equal(paths.homeAt(null), "#/home");
  assert.equal(paths.overviewAt("p1", 7), "#/p/p1/overview?at=7");
  assert.equal(paths.overviewAt("p1", null), "#/p/p1/overview");
});