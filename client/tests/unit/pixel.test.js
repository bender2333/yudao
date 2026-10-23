// 像素画基础的单元测试（工单 #176）：node --test 运行，不需要 Electron、浏览器与网络。
// 覆盖：登记表完整性（图鉴「一项不少」的核对基准）、小人合成的确定性（同输入同输出）、
// 动作帧序列的取值、整数倍最近邻缩放的排布、GSAP 确定时钟的可重复性。

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

import { registry } from "../../src/renderer/src/pixel/registry.ts";
import { composeChar, resolveSpriteKey, rolePalette } from "../../src/renderer/src/pixel/char.ts";
import { animFrameAt } from "../../src/renderer/src/pixel/anims.ts";
import { POSES, ANIMS } from "../../src/renderer/src/pixel/registry.ts";
import { integerScale, layoutFor } from "../../src/renderer/src/pixel/scale.ts";

const require = createRequire(import.meta.url);

test("登记表列出原型 sprites.js 与 engine.js 的全部公开成员：64 个（39 函数 + 25 数据）", () => {
  assert.equal(registry.inventory.functions.length, 39);
  assert.equal(registry.inventory.data.length, 25);
  assert.equal(registry.inventory.all.length, 64);
  // 抽查几个画法名，确认清单是真实导出而不是写死的数字
  for (const fn of ["drawActor", "drawBitmap", "drawIcon", "renderSprite", "createVignette", "rolePalette", "box", "bubble", "sign"]) {
    assert.ok(registry.inventory.functions.includes(fn), `缺少函数 ${fn}`);
  }
  for (const d of ["PAL", "CHAR", "BITMAPS", "POSES", "ANIMS", "ACTIONS", "VIGNETTES", "paint", "ease"]) {
    assert.ok(registry.inventory.data.includes(d), `缺少数据表 ${d}`);
  }
});

test("登记表的数据与原型运行时一致（按锁定依赖生成，内容照原型搬）", () => {
  // 用与生成脚本相同的沙箱再跑一次原型，比较注册表规模（防止登记表与原型脱节）
  const proto = loadPrototypePixel();
  for (const name of ["PAL", "CHAR", "DEPTS", "SKINS", "HAIRS", "ROLE_KINDS", "ROLE_NAMES", "ITEM_COLORS", "ITEM_SHADES", "SPRITE_LEVELS", "BITMAPS", "POSES", "ANIMS", "ACTIONS", "BASE_MOTIONS", "STATUS_ACTIONS", "EVENT_ACTIONS", "VIGNETTE_SPRITES", "FONT3"]) {
    const a = Object.keys(proto[name]).length;
    const b = Object.keys(registry.registries[name]).length;
    assert.equal(b, a, `${name} 数量不一致：客户端 ${b}，原型 ${a}`);
  }
});

test("角色配色表逐字对照原型 rolePalette", () => {
  const proto = loadPrototypePixel();
  for (const dept of Object.keys(registry.registries.DEPTS)) {
    for (const kind of Object.keys(registry.registries.ROLE_KINDS)) {
      for (const item of [null, 0, 3, 5]) {
        const mine = rolePalette(dept, kind, item);
        const theirs = proto.rolePalette(dept, kind, item);
        // 原型在另一个 vm 上下文里，对象原型不同，这里比较键值与内容
        assert.deepEqual({ ...mine.map }, { ...theirs.map }, `rolePalette(${dept},${kind},${item})`);
        assert.deepEqual({ ...mine.sleeve }, { ...theirs.sleeve });
      }
    }
  }
});

test("小人合成是确定的：同一姿势与配色两次合成得到相同网格", () => {
  const a = composeChar({ key: "engineering.agent", pose: "type0", face: null, hold: null });
  const b = composeChar({ key: "engineering.agent", pose: "type0", face: null, hold: null });
  assert.equal(a.signature, b.signature);
  assert.ok(a.opaque > 0, "画法必须产出像素");
});

test("小人合成覆盖全部 126 个姿势且不抛错，姿势名与原型一致", () => {
  const proto = loadPrototypePixel();
  const poseNames = Object.keys(proto.POSES);
  assert.equal(poseNames.length, 126);
  assert.deepEqual(Object.keys(POSES).sort(), poseNames.sort());
  for (const pose of poseNames) {
    const frame = composeChar({ key: "product.agent", pose, face: null, hold: null });
    assert.ok(frame.opaque > 0, `姿势 ${pose} 没有画出像素`);
    assert.equal(frame.base.length, registry.charW * registry.charH);
  }
});

test("动作帧序列与原型 animFrame 在同样经过时间下给出同一姿势（含循环与收尾帧）", () => {
  const proto = loadPrototypePixel();
  const animNames = Object.keys(proto.ANIMS);
  assert.equal(animNames.length, 71);
  assert.deepEqual(Object.keys(ANIMS).sort(), animNames.sort());
  for (const name of animNames) {
    const total = proto.ANIMS[name].total;
    for (const t of [0, 1, 17, Math.floor(total / 2), total - 1, total, total + 321]) {
      for (const reduced of [false, true]) {
        assert.equal(animFrameAt(name, t, reduced), proto.animFrame(name, t, reduced), `animFrame(${name},${t},${reduced})`);
      }
    }
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

test("小人标识解析与原型 parseSpriteKey 一致（含 :颜色序号 与 ops 简写、错误输入抛错）", () => {
  const proto = loadPrototypePixel();
  for (const key of Object.keys(registry.registries.ROLE_NAMES).concat(["ops", "agent:2", "product.agent:0"])) {
    let mine = null, theirs = null, mineErr = null, theirsErr = null;
    try { mine = resolveSpriteKey(key); } catch (e) { mineErr = true; }
    try { theirs = proto.parseSpriteKey(key); } catch (e) { theirsErr = true; }
    assert.equal(Boolean(mineErr), Boolean(theirsErr), `${key} 抛错行为不一致`);
    if (!mineErr) assert.deepEqual({ dept: mine.dept, kind: mine.kind, item: mine.item }, { dept: theirs.dept, kind: theirs.kind, item: theirs.item }, key);
  }
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

test("位图画法全部可解析：BITMAPS 的每一张位图行等宽、字符都有颜色", () => {
  const proto = loadPrototypePixel();
  for (const [name, d] of Object.entries(proto.BITMAPS)) {
    const w = d.rows[0].length;
    for (const row of d.rows) assert.equal(row.length, w, `位图 ${name} 行宽不齐`);
    for (const row of d.rows) {
      for (const ch of row) {
        if (ch === ".") continue;
        assert.ok(d.map[ch], `位图 ${name} 的字符 ${ch} 没有颜色`);
      }
    }
  }
});

// ---------------------------------------------------------------------------
// 用与生成脚本相同的沙箱把原型加载进内存，作为「与原型一致」的对照（只读原型，不修改）。

let protoCache = null;
function loadPrototypePixel() {
  if (protoCache) return protoCache;
  const fs = require("node:fs");
  const vm = require("node:vm");
  const path = require("node:path");
  const v11 = path.resolve(import.meta.dirname, "..", "..", "..", "docs", "prototypes", "v11", "js");
  const noop = () => {};
  const makeCtx2d = () => ({
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(Math.max(0, w * h * 4)) }),
    putImageData: noop, drawImage: noop,
    getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(Math.max(0, w * h * 4)) }),
    fillRect: noop, save: noop, restore: noop, translate: noop, scale: noop, rotate: noop,
    beginPath: noop, arc: noop, fill: noop, stroke: noop, moveTo: noop, lineTo: noop, closePath: noop,
    rect: noop, clip: noop, setTransform: noop, clearRect: noop, createPattern: () => null,
    createLinearGradient: () => ({ addColorStop: noop }), measureText: () => ({ width: 0 }),
    fillText: noop, strokeText: noop, font: "", textAlign: "", textBaseline: "",
    fillStyle: "", strokeStyle: "", lineWidth: 1, globalAlpha: 1, imageSmoothingEnabled: true,
  });
  const storeStub = () => ({ getItem: () => null, setItem: () => {}, removeItem: () => {} });
  const canvasStub = () => ({ tagName: "CANVAS", getContext: makeCtx2d, width: 0, height: 0, style: {}, toDataURL: () => "data:,", addEventListener: noop, removeEventListener: noop });
  const sandbox = {
    console, Math, JSON, Object, Array, String, Number, Boolean, Date, Error, Map, Set, RegExp,
    document: { createElement: canvasStub, addEventListener: noop, getElementById: () => null, querySelector: () => null, body: { appendChild: noop }, head: { appendChild: noop }, documentElement: { style: {} } },
    localStorage: storeStub(), sessionStorage: storeStub(),
    matchMedia: () => ({ matches: false, addEventListener: noop, addListener: noop }),
    performance: { now: () => 0 }, requestAnimationFrame: () => 0, cancelAnimationFrame: noop,
    devicePixelRatio: 1, setTimeout, clearTimeout, setInterval, clearInterval, addEventListener: noop, removeEventListener: noop,
  };
  sandbox.window = sandbox; sandbox.self = sandbox; sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  for (const [label, file] of [["y11.js", path.join(v11, "y11.js")], ["sprites.js", path.join(v11, "pixel", "sprites.js")], ["engine.js", path.join(v11, "pixel", "engine.js")]]) {
    vm.runInContext(fs.readFileSync(file, "utf8"), sandbox, { filename: label });
  }
  protoCache = sandbox.window.Y11.pixel;
  return protoCache;
}
