// 事项范围的路径（工单 #746）：范围是项目内的一份作用域，写在路径参数 ?w= 中；
// 换一个范围时留在当前页（withScope），没有范围时地址里不留空的 ?w=。
// 用 node --test 运行。

import { test } from "node:test";
import assert from "node:assert/strict";
import { parseRoute, paths, withScope } from "../../src/renderer/src/shell/routing.ts";

test("范围写在 ?w= 里；没有范围时地址里没有这个参数", () => {
  assert.equal(paths.overview("p1"), "#/p/p1/overview");
  assert.equal(paths.overview("p1", { workItem: "w1" }), "#/p/p1/overview?w=w1");
  assert.equal(paths.dept("p1", "quality"), "#/p/p1/dept/quality");
  assert.equal(paths.dept("p1", "quality", { workItem: "w1" }), "#/p/p1/dept/quality?w=w1");
  assert.equal(paths.observe("p1"), "#/p/p1/observe");
  assert.equal(paths.observe("p1", { workItem: "w1" }), "#/p/p1/observe?w=w1");
  assert.equal(paths.materials("p1", { workItem: "w1" }), "#/p/p1/materials?w=w1");
  assert.equal(paths.settings("p1", { workItem: "w1" }), "#/p/p1/settings?w=w1");
});

test("范围清空时地址里不留空的 ?w=", () => {
  assert.equal(paths.overview("p1", { workItem: null }), "#/p/p1/overview");
  assert.equal(paths.observe("p1", { workItem: "" }), "#/p/p1/observe");
  assert.equal(parseRoute("#/p/p1/observe?w=").workItemId, null);
  assert.equal(parseRoute("#/p/p1/observe").workItemId, null);
});

test("地址里的范围读得回来（写进去再读出来是同一件事项）", () => {
  assert.equal(parseRoute(paths.observe("p1", { workItem: "w1" })).workItemId, "w1");
  assert.equal(parseRoute(paths.dept("p1", "quality", { workItem: "w1" })).workItemId, "w1");
  assert.equal(parseRoute(paths.materials("p1", { workItem: "w1" })).workItemId, "w1");
});

test("换一个范围时留在当前页", () => {
  assert.equal(withScope(parseRoute("#/p/p1/observe"), "w1"), "#/p/p1/observe?w=w1");
  assert.equal(withScope(parseRoute("#/p/p1/materials"), "w1"), "#/p/p1/materials?w=w1");
  assert.equal(withScope(parseRoute("#/p/p1/dept/quality"), "w1"), "#/p/p1/dept/quality?w=w1");
  assert.equal(withScope(parseRoute("#/p/p1/overview"), "w1"), "#/p/p1/overview?w=w1");
  assert.equal(withScope(parseRoute("#/p/p1/settings"), "w1"), "#/p/p1/settings?w=w1");
});

test("清空范围时留在当前页，回到整个项目", () => {
  assert.equal(withScope(parseRoute("#/p/p1/observe?w=w1"), null), "#/p/p1/observe");
  assert.equal(withScope(parseRoute("#/p/p1/dept/quality?w=w1"), null), "#/p/p1/dept/quality");
  assert.equal(withScope(parseRoute("#/p/p1/materials?w=w1"), null), "#/p/p1/materials");
});

test("请求详情页换范围时回到请求记录页；恢复页按新的事项打开", () => {
  assert.equal(withScope(parseRoute("#/p/p1/observe/act_1"), "w1"), "#/p/p1/observe?w=w1");
  assert.equal(withScope(parseRoute("#/p/p1/w/w1/recovery"), "w2"), "#/p/p1/w/w2/recovery");
  assert.equal(withScope(parseRoute("#/p/p1/w/w1/recovery"), null), "#/p/p1/overview");
});

test("回放位置与范围一起带着：换回放位置不丢掉所选范围", () => {
  assert.equal(paths.overviewAt("p1", 7), "#/p/p1/overview?at=7");
  assert.equal(paths.overviewAt("p1", 7, { workItem: "w1" }), "#/p/p1/overview?at=7&w=w1");
  assert.equal(paths.overviewAt("p1", null, { workItem: "w1" }), "#/p/p1/overview?w=w1");
});
