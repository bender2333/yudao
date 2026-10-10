// 画面按设备分辨率绘制（工单 #365 验收标准 1、3）：
// 画面文字的字体是微软雅黑（ADR-0021 第 4 条），画布的像素尺寸是逻辑尺寸的整数倍
// （scale.ts 的 layoutFor：像素缓冲与整数倍 k）。
//
// 这里只验证纯计算：字号、字体栈与整数倍排布。真实页面上的画布尺寸与实际绘制出的文字、贴图
// 由端到端用例在 Chromium 里检查（tests/e2e/device-resolution.spec.ts），这里不重复。

import { test } from "node:test";
import assert from "node:assert/strict";

import { integerScale, layoutFor } from "../../src/renderer/src/pixel/scale.ts";
import { PIXEL_FONT_STACK, PROTOTYPE_FONT } from "../../src/renderer/src/pixel/registry.ts";

// 三个上线画面的逻辑尺寸：楼层 640×320、部门房间 480×240、首页的楼 640 宽（高度随层数变化）
const VIEWS = [
  { name: "楼层", W: 640, H: 320 },
  { name: "部门房间", W: 480, H: 240 },
  { name: "楼", W: 640, H: 240 },
];

const WINDOWS = [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
];
const DPRS = [1, 1.25, 1.5];

test("画面文字的字体栈是微软雅黑（ADR-0021 第 4 条）", () => {
  assert.ok(PIXEL_FONT_STACK.includes("Microsoft YaHei"), `字体栈没有微软雅黑：${PIXEL_FONT_STACK}`);
  // 与原型 v10 engine.js 的 P.FONT 相同（生成的登记表里存着原型的那一串）
  assert.equal(PIXEL_FONT_STACK, PROTOTYPE_FONT);
});

test("整数倍缩放：三个画面在两种窗口与三种设备像素比下，画布像素尺寸都是逻辑尺寸的整数倍", () => {
  for (const view of VIEWS) {
    for (const size of WINDOWS) {
      for (const dpr of DPRS) {
        const avail = size.width - 40;
        const k = integerScale(avail, dpr, view.W);
        assert.ok(Number.isInteger(k) && k >= 1, `${view.name} 在 ${size.width}×${size.height} DPR ${dpr} 下倍数不是正整数：${k}`);
        const lay = layoutFor(view.W, view.H, avail, size.height, dpr);
        assert.equal(lay.k, k);
        assert.equal(lay.bufferW, view.W * k, `${view.name} 的缓冲宽不是逻辑宽的整数倍`);
        assert.equal(lay.bufferH, view.H * k, `${view.name} 的缓冲高不是逻辑高的整数倍`);
        // 设备像素不小于缓冲：缓冲按设备分辨率绘制，不欠分辨率
        assert.ok(lay.bufferW >= avail * dpr - 1e-6, `${view.name} 的缓冲宽度小于设备像素宽度`);
        assert.equal(lay.cssW, avail);
      }
    }
  }
});

test("容器变窄时倍数仍是正整数（宽度 640 的画面在 390×844 与 1280 宽下都成立）", () => {
  for (const view of VIEWS) {
    for (const avail of [1280, 1281, 1288, 1240, 640, 480, 390, 41, 40]) {
      for (const dpr of DPRS) {
        const lay = layoutFor(view.W, view.H, avail, 900, dpr);
        assert.ok(Number.isInteger(lay.k) && lay.k >= 1, `${view.name} 在宽度 ${avail} 下倍数不是正整数：${lay.k}`);
        assert.equal(lay.bufferW % view.W, 0);
        assert.equal(lay.bufferH % view.H, 0);
      }
    }
  }
});