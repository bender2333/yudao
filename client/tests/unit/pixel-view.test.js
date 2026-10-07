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

test("整数倍缩放：1440×900 与 390×844 下都是整数倍，缓冲不小于设备像素", () => {
  const windows = [
    [1440, 900],
    [390, 844],
  ];
  const views = [
    { W: 320, H: 200 },
    { W: 240, H: 150 },
    { W: 640, H: 400 },
  ];
  for (const [w, h] of windows) {
    for (const dpr of [1, 1.5, 2]) {
      for (const v of views) {
        const lay = layoutFor(v.W, v.H, w, h, dpr);
        assert.ok(Number.isInteger(lay.k) && lay.k >= 1, `k 必须是正整数：${lay.k}`);
        assert.equal(lay.bufferW % v.W, 0, "缓冲宽必须是逻辑宽的整数倍");
        assert.equal(lay.bufferH % v.H, 0, "缓冲高必须是逻辑高的整数倍");
        assert.ok(lay.bufferW >= w * dpr - 1e-6, "缓冲必须覆盖设备像素宽（放大不模糊）");
        // 放大倍数不取过度：少一倍就会小于显示尺寸
        assert.ok((lay.k - 1) * v.W < w * dpr + 1e-6, "缩放倍数不应大于必要值");
      }
    }
  }
});

test("缩放随视图尺寸改变：窗口变窄时倍数下降，变宽时上升，始终是整数", () => {
  const W = 240;
  const wide = integerScale(1440, 1, W);
  const narrow = integerScale(390, 1, W);
  assert.ok(narrow < wide, "窄窗口的倍数应小于宽窗口");
  assert.equal(narrow, 2); // 2×240=480 ≥ 390
  assert.equal(wide, 6); // 6×240=1440
  for (const avail of [320, 375, 414, 768, 1024, 1440, 1920, 2560]) {
    assert.ok(Number.isInteger(integerScale(avail, 1, W)));
  }
});

test("画面对象的状态机与原型一致：setModel、playEvent、focus、resize、destroy 的入参与效果", () => {
  // PixiJS 的渲染要在浏览器里跑（e2e 覆盖）；这里验证画面对象的状态与入参校验，
  // 它们是五个方法里与渲染无关、但决定行为正确与否的部分。
  const view = createPixelViewState({ W: 240, H: 150, now: () => 0 });
  for (const m of ["setModel", "playEvent", "focus", "resize", "destroy"]) {
    assert.equal(typeof view[m], "function", `缺少方法 ${m}`);
  }
  view.setModel({ items: [{ id: "a", sprite: "product.agent", x: 100, y: 120 }] });
  assert.deepEqual(view.positionOf("a"), { x: 100, y: 120 });
  // idle 动作的第一帧姿势是 stand（动作名与姿势名不同）
  assert.equal(view.poseOf("a"), "stand");
  assert.throws(() => view.setModel(null), /setModel 需要含 items 数组/);
  assert.throws(() => view.playEvent(null), /playEvent 需要事件对象/);
  assert.throws(() => view.focus("missing"), /没有这个小人/);
  // playEvent 换动作并可以回放：同样经过时间必得同样的姿势
  view.playEvent({ type: "action", actorId: "a", action: "walk", at: 0 });
  view.advance(0);
  const p0 = view.poseOf("a");
  view.advance(100);
  const p100 = view.poseOf("a");
  assert.equal(p0, "walk0");
  assert.equal(p100, "walk1");
  // 回到同一时刻重放：动作起点对齐后，经过同样时间必得同样的姿势
  view.advance(0);
  view.playEvent({ type: "action", actorId: "a", action: "walk", at: 0 });
  view.advance(100);
  assert.equal(view.poseOf("a"), p100, "回放同样的时间应得同样的姿势");
  view.focus("a");
  assert.equal(view.focused(), "a");
  view.resize();
  assert.equal(view.size.W, 240);
  view.destroy();
});
