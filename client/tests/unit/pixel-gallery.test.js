// 动作图鉴与确定时钟的单元测试（工单 #176 验收标准 1、2）。
// 图鉴「一项不少」：列出原型 sprites.js 与 engine.js 的全部公开画法，与生成脚本导出的登记表逐一对照。
// 时钟：GSAP 与 PixiJS 共用一个时钟，换成手动时钟后推进同样的时间必得同样的补间位置。

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

import { galleryGaps, GALLERY_MEMBERS } from "../../src/renderer/src/pixel/gallery-data.ts";
import { PAINT_NAMES } from "../../src/renderer/src/pixel/paint.ts";
import { PUBLIC_MEMBERS, registry } from "../../src/renderer/src/pixel/registry.ts";
import { createManualClock } from "../../src/renderer/src/pixel/clock.ts";

const require = createRequire(import.meta.url);

test("动作图鉴列出全部公开画法，一项不少：与原型成员表完全一致", () => {
  const gaps = galleryGaps();
  assert.deepEqual(gaps.missing, [], `图鉴缺少：${gaps.missing.join("、")}`);
  assert.deepEqual(gaps.extra, [], `图鉴多出：${gaps.extra.join("、")}`);
  assert.equal(GALLERY_MEMBERS.length, PUBLIC_MEMBERS.all.length);
  assert.equal(GALLERY_MEMBERS.length, 64);
});

test("动作图鉴的每一项都有说明与可渲染的取样（点阵、数据或数值）", () => {
  for (const m of GALLERY_MEMBERS) {
    assert.ok(m.note.length > 0, `${m.name} 没有说明`);
    assert.ok(["grid", "data", "value"].includes(m.sample.type), `${m.name} 取样类型未知`);
    if (m.sample.type === "grid") {
      assert.ok(m.sample.grid.length === m.sample.w * m.sample.h, `${m.name} 点阵尺寸不符`);
      assert.ok(m.sample.grid.some((c) => c), `${m.name} 是空点阵，画法必须产出像素`);
    }
    if (m.sample.type === "data") assert.ok(m.sample.count > 0 && m.sample.entries.length > 0, `${m.name} 没有条目`);
    if (m.sample.type === "value") assert.ok(m.sample.value.length > 0, `${m.name} 没有数值`);
  }
});

test("陈设画法一项不少：paint 表列出原型第 8 节的全部方法", () => {
  const expected = ["screen", "scanlines", "desk", "deskItems", "chair", "cabinet", "blinkFrame", "terminal", "door", "whiteboard", "corkboard", "crt", "window", "clock", "lamp", "lightCone", "glow", "tray", "bin", "archive", "mailbox", "scrollRack", "table", "rack", "shelf", "beacon", "beaconLight", "cardCabinet", "cart", "plant", "rug", "poster", "shot", "pipe", "tube", "postbox", "backup", "machineDoor", "monitor", "toolPanel"];
  const have = new Set(PAINT_NAMES);
  const missing = expected.filter((n) => !have.has(n));
  assert.deepEqual(missing, [], `陈设画法缺少：${missing.join("、")}`);
  assert.equal(expected.length, 40);
});

test("登记表里的每一档位、状态与事件都有对应动作，没有指向不存在的动作", () => {
  const anims = new Set(Object.keys(registry.registries.ANIMS));
  for (const [k, v] of Object.entries(registry.registries.BASE_MOTIONS)) assert.ok(anims.has(v.anim), `基础动作 ${k} 指向不存在的动作 ${v.anim}`);
  for (const [k, v] of Object.entries(registry.registries.ACTIONS)) assert.ok(anims.has(v.anim), `动作说明 ${k} 指向不存在的动作 ${v.anim}`);
});

test("确定的手动时钟：推进同样的时间，GSAP 补间每次都得到同样的位置", () => {
  const { gsap } = require("gsap");
  // 同一个时钟反复回放：每次都先 reset，再推进同样的时间序列
  const clock = createManualClock();
  const replay = () => {
    clock.reset();
    const samples = [];
    const p = { x: 0, y: 0 };
    const tw = clock.tween(p, { x: 240, y: 96, duration: 2, ease: "power2.out" });
    for (let ms = 100; ms <= 2000; ms += 100) {
      clock.advance(ms);
      samples.push([Math.round(p.x * 1000) / 1000, Math.round(p.y * 1000) / 1000]);
    }
    tw.kill();
    return samples;
  };
  const a = replay();
  const b = replay();
  const c = replay();
  clock.destroy();
  assert.deepEqual(b, a, "两次回放的补间位置不同");
  assert.deepEqual(c, a, "第三次回放与第一次不同");
  const last = a[a.length - 1];
  assert.ok(Math.abs(last[0] - 240) < 1e-3 && Math.abs(last[1] - 96) < 1e-3, `终点应落在目标位置，实际 ${last.join(",")}`);
});

test("确定的手动时钟：订阅者拿到的时间与补间位置一一对应，PixiJS 与 GSAP 看到同一个时间", () => {
  const { gsap } = require("gsap");
  const clock = createManualClock();
  clock.reset(); // 补间在复位之后建立，起点才落在时钟零点
  const seen = [];
  const p = { x: 0 };
  const tw = clock.tween(p, { x: 100, duration: 1, ease: "none" });
  clock.onTick((elapsed, delta) => seen.push([elapsed, p.x, delta]));
  clock.advance(250);
  clock.advance(500);
  clock.advance(1000);
  assert.equal(seen.length, 3);
  // 线性补间：位置 = 经过时间 / 总时长 × 距离；回调里看到的 GSAP 位置必须与经过时间对得上
  for (const [elapsed, pos, delta] of seen) {
    assert.ok(Math.abs(pos - (elapsed / 1000) * 100) < 1e-3, `经过 ${elapsed}ms 时补间位置为 ${pos}，与经过时间不符`);
  }
  assert.deepEqual(seen.map((r) => [r[0], r[2]]), [[250, 250], [500, 250], [1000, 500]]);
  assert.equal(clock.now(), 1000);
  tw.kill();
  clock.destroy();
});

test("确定的手动时钟：重置后从零点开始，位置与第一次回放相同", () => {
  const { gsap } = require("gsap");
  const clock = createManualClock();
  const p = { x: 0 };
  const tw = clock.tween(p, { x: 80, duration: 1, ease: "none" });
  clock.advance(400);
  const first = p.x;
  tw.kill();
  clock.reset();
  assert.equal(clock.now(), 0);
  const q = { x: 0 };
  clock.tween(q, { x: 80, duration: 1, ease: "none" });
  clock.advance(400);
  assert.ok(Math.abs(q.x - first) < 1e-3, `重置后回放的位置 ${q.x} 与第一次 ${first} 不同`);
  clock.destroy();
});

test("确定的手动时钟：不能倒退，释放后不能再推进", () => {
  const clock = createManualClock();
  clock.advance(100);
  assert.throws(() => clock.advance(50), /不能倒退/);
  clock.destroy();
  assert.throws(() => clock.advance(200), /已释放/);
});
