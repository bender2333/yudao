// 像素画面的路由与接口测试（工单 #176 验收标准 3、4 与「图鉴不进正式页面入口」）。
// 路由与缩放是纯计算，不需要 Electron 与网络；画面对象的行为用替身宿主元素验证。

import { test } from "node:test";
import assert from "node:assert/strict";

import { parseRoute, paths } from "../../src/renderer/src/shell/routing.ts";
import { integerScale, layoutFor } from "../../src/renderer/src/pixel/scale.ts";
import { createPixelViewState } from "../../src/renderer/src/pixel/view-state.ts";

test("动作图鉴只在开发路径上可达：#/gallery 解析为 gallery，正式路径表里没有它", () => {
  assert.equal(parseRoute("#/gallery").name, "gallery");
  // 正式的页面入口（paths）里没有图鉴：页签与侧栏都取不到它
  assert.ok(!Object.keys(paths).includes("gallery"), "图鉴不应出现在正式路径表里");
  assert.ok(!Object.values(paths).some((p) => String(p).includes("gallery")), "正式路径不应指向图鉴");
});

test("图鉴不影响既有路由：home、sys、项目页面照旧解析，已删除的连接页回到未找到", () => {
  assert.equal(parseRoute("").name, "home");
  assert.equal(parseRoute("#/home").name, "home");
  assert.equal(parseRoute("#/connect").name, "not-found");
  assert.equal(parseRoute("#/sys/machines").name, "sys-machines");
  assert.equal(parseRoute("#/p/demo/overview").name, "overview");
  assert.equal(parseRoute("#/p/demo/dept/product").name, "dept");
  assert.equal(parseRoute("#/nope").name, "not-found");
});



