// 画面自己的画法行为（原来在 pixel.test.js 里，与原型 v13 的对照无关，工单 #1414 把这几条留下来重写在
// 这里）：小人合成是确定的、登记表的每个姿势都能合成、手持物件与表情参与合成、缩放取整数倍且缓冲不小于
// 设备像素。守的是 R3（路线图已走到阶段写明的行为：画面按画面合同与诚实性验收），不经原型、不比较像素。

import { test } from "node:test";
import assert from "node:assert/strict";

import { composeChar } from "../../src/pixel/char.ts";
import { POSES, registry } from "../../src/pixel/registry.ts";
import { integerScale, layoutFor } from "../../src/pixel/scale.ts";

test("小人合成是确定的：同一姿势与配色两次合成得到相同网格", () => {
  const a = composeChar({ key: "engineering.agent", pose: "type0", face: null, hold: null });
  const b = composeChar({ key: "engineering.agent", pose: "type0", face: null, hold: null });
  assert.equal(a.signature, b.signature);
  assert.ok(a.opaque > 0, "画法必须产出像素");
});

test("小人合成覆盖登记表的全部 126 个姿势：每个姿势都画出像素，网格尺寸是角色格", () => {
  const poseNames = Object.keys(POSES);
  assert.equal(poseNames.length, 126);
  for (const pose of poseNames) {
    const frame = composeChar({ key: "product.agent", pose, face: null, hold: null });
    assert.ok(frame.opaque > 0, `姿势 ${pose} 没有画出像素`);
    assert.equal(frame.base.length, registry.charW * registry.charH);
  }
});

test("手持物件与表情参与合成：不同 hold/face 得到不同网格", () => {
  const plain = composeChar({ key: "quality.tester", pose: "magnify", face: null, hold: null });
  const happy = composeChar({ key: "quality.tester", pose: "magnify", face: "happy", hold: null });
  assert.notEqual(plain.signature, happy.signature);
  const carry0 = composeChar({ key: "engineering.lead", pose: "carry_f", face: null, hold: null });
  const carry1 = composeChar({ key: "engineering.lead", pose: "carry_f", face: null, hold: "box_sealed" });
  assert.notEqual(carry0.signature, carry1.signature, "$hold 物件应随 hold 变化");
});

test("缩放取整数倍且不小于显示尺寸：1440×900 与 390×844 下都是整数倍、像素不模糊", () => {
  // 画布逻辑宽 W，容器 avail，dpr：取 k=ceil(avail*dpr/W)，渲染 W*k×H*k，CSS 缩放到容器宽度
  assert.equal(integerScale(1440, 1, 320), 5); // 5×320=1600 ≥ 1440
  assert.equal(integerScale(390, 1, 320), 2); // 2×320=640 ≥ 390
  assert.equal(integerScale(390, 2, 320), 3);
  assert.equal(integerScale(1440, 2, 320), 9);
  for (const [w, h, dpr] of [[1440, 900, 1], [1440, 900, 2], [390, 844, 1], [390, 844, 2]]) {
    for (const view of [{ W: 320, H: 200 }, { W: 640, H: 400 }, { W: 240, H: 150 }]) {
      const lay = layoutFor(view.W, view.H, w, h, dpr);
      assert.ok(Number.isInteger(lay.k) && lay.k >= 1, "缩放必须是正整数倍");
      assert.ok(lay.bufferW % view.W === 0 && lay.bufferH % view.H === 0, "缓冲尺寸必须是逻辑尺寸的整数倍");
      assert.ok(lay.bufferW >= w * dpr - 1e-6, "缓冲必须不小于设备像素宽度（最近邻放大不模糊的前提）");
    }
  }
});
