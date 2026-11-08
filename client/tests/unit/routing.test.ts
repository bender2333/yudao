// 页面的路由（工单 #176 验收标准 3、#1418）：地址解析成页面名与参数，路径表里没有图鉴。
// 图鉴随画面搬出（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」）：
// 它是画面自己的整页（view/ 的入口），页面的路径不再解析它。

import { test } from "node:test";
import assert from "node:assert/strict";

import { parseRoute, paths } from "../../src/renderer/src/shell/routing.ts";

test("正式路径照旧解析：home、sys、项目页面；图鉴与已删除的连接页都落到未找到", () => {
  assert.equal(parseRoute("").name, "home");
  assert.equal(parseRoute("#/home").name, "home");
  assert.equal(parseRoute("#/connect").name, "not-found");
  assert.equal(parseRoute("#/gallery").name, "not-found");
  assert.equal(parseRoute("#/sys/machines").name, "sys-machines");
  assert.equal(parseRoute("#/p/demo/overview").name, "overview");
  assert.equal(parseRoute("#/p/demo/dept/product").name, "dept");
  assert.equal(parseRoute("#/nope").name, "not-found");
});

test("路径表里没有图鉴：页签与侧栏取不到它", () => {
  assert.ok(!Object.keys(paths).includes("gallery"), "图鉴不应出现在正式路径表里");
  assert.ok(!Object.values(paths).some((p) => String(p).includes("gallery")), "正式路径不应指向图鉴");
});

// 工单 #1638：项目页先是对话（上面带循环图），打开项目时落在这一页；概览等页先留着
test("打开项目落在对话页，事项范围写在 ?w= 里", () => {
  assert.equal(parseRoute("#/p/demo").name, "conversation");
  assert.equal(parseRoute("#/p/demo/conversation").name, "conversation");
  assert.equal(parseRoute("#/p/demo/conversation?w=w1").workItemId, "w1");
  assert.equal(parseRoute("#/p/demo/conversation?w=").workItemId, null);
  assert.equal(paths.conversation("demo"), "#/p/demo/conversation");
  assert.equal(paths.conversation("demo", { workItem: "w1" }), "#/p/demo/conversation?w=w1");
  // 已有的页面照旧
  assert.equal(parseRoute("#/p/demo/overview").name, "overview");
  assert.equal(paths.overview("demo"), "#/p/demo/overview");
});
