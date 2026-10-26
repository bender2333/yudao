// 楼与机房的画面测试（工单 #178、#955）：楼的单元测试按原型 docs/prototypes/v13/checks/walkers.js 改写，
// 直接对楼的世界、角色实体、播放时间线与画面状态运行，用确定的时钟与随机数。
//
// 覆盖：每层一个小人的角色实体与 actor、走位与待机动画由 stepCharacters 与楼驱动推进、速度（门口 40、随机走动 22）、
// 朝向（门口站定向左）、门口的停靠位置、空闲层在多个随机位置之间走动、层数减少后旧的 actor 与角色实体一并清掉
// （v13 walkers.js 的六项）；楼的动作只有层闪光与撒彩带（开头就算演完），状态等动作演完再上画面，
// 跳到最新直接显示不补播；状态灯的词与配色覆盖画面合同的八个取值；画面层不导入页面、接口与命令接口。
//
// 楼层状态灯怎么由事项推出来（原来的 sceneStatus 与 floorStatus）在翻译层的测试里核对
// （tests/unit/translate-building.test.ts：状态由查询结果翻译，不再在画面层组装）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";

import { FLOOR_SIGNS } from "../../src/renderer/src/pixel/contract.ts";
import { BUILDING_KINDS } from "../../src/renderer/src/pixel/building/building-decl.ts";
import { BUILDING_STATUS } from "../../src/renderer/src/pixel/building/status-text.ts";
import { buildCatalog } from "../../src/renderer/src/pixel/world/floor-decl.ts";
import { createScene } from "../../src/renderer/src/pixel/world/scene.ts";
import {
  buildingWalkerState, createBuildingDriver, emptyBuildingModel, BUILDING_GEO, FLASH_COLOR_NAMES, SPEED_ROAM, SPEED_WORK, flashColorOf,
} from "../../src/renderer/src/pixel/world/building.ts";
import type { BuildingFloor, BuildingModel } from "../../src/renderer/src/pixel/world/building.ts";

// 与原型 walkers.js 一致：确定的随机数序列
function seeded(): () => number {
  let seed = 246813579;
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

const catalog = buildCatalog({});

function floor(pid: string, lit: Partial<BuildingFloor["lit"]> = {}): BuildingFloor {
  return {
    project_id: pid, name: pid, status: "working",
    lit: { product: false, engineering: false, quality: false, operations: false, ...lit },
    has_ops: false, flags: [], valve_closed: false, machine_ids: [], link_active: false, decisions: 0,
  };
}

function model(floors: BuildingFloor[], position = 0, showBasement = false): BuildingModel {
  return { position, floors, show_basement: showBasement };
}

interface Harness {
  driver: ReturnType<typeof createBuildingDriver>;
  scene: ReturnType<typeof createScene>;
  step: (ms: number) => void;
}

function mountBuilding(m: BuildingModel): Harness {
  const scene = createScene({ W: BUILDING_GEO.W, H: BUILDING_GEO.ROOF + BUILDING_GEO.FH + BUILDING_GEO.BASE, random: seeded(), reduced: false });
  const driver = createBuildingDriver({ model: emptyBuildingModel(), scene, catalog, random: seeded() });
  driver.jump(m);
  const step = (ms: number): void => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) {
      scene.stepScene(50);
      driver.step();
    }
  };
  return { driver, scene, step };
}

test("楼里的小人：每层一个角色实体与 actor，id 为 ch- + 项目标识", () => {
  const h = mountBuilding(model([floor("p-a"), floor("p-b", { engineering: true }), floor("p-c")]));
  h.step(900);
  const walkers = buildingWalkerState(h.driver.world, h.scene);
  assert.equal(walkers.length, 3);
  assert.deepEqual(walkers.map((w) => w.id), ["p-a", "p-b", "p-c"]);
  for (const w of walkers) {
    assert.ok(h.scene.actors.some((a) => a.id === `ch-${w.id}`));
  }
});

test("楼里的小人：层数减少后旧的 actor 与角色实体一并清掉", () => {
  const h = mountBuilding(model([floor("p-a"), floor("p-b", { engineering: true }), floor("p-c")]));
  h.step(900);
  assert.equal(buildingWalkerState(h.driver.world, h.scene).length, 3);
  h.driver.jump(model([floor("p-a")], 1));
  h.step(200);
  const walkers = buildingWalkerState(h.driver.world, h.scene);
  assert.deepEqual(walkers.map((w) => w.id), ["p-a"]);
  assert.deepEqual(h.scene.actors.filter((a) => a.data.walker).map((a) => a.id), ["ch-p-a"]);
});

test("楼里的小人：走位由系统推进，待机时 idle、走动时 walk，速度只有门口 40 与随机走动 22", () => {
  const h = mountBuilding(model([floor("p-a"), floor("p-b", { engineering: true }), floor("p-c")]));
  const before = buildingWalkerState(h.driver.world, h.scene).map((w) => w.x);
  const anims = new Set<string>();
  const speeds = new Set<number>();
  let moved = 0;
  for (let k = 0; k < 16; k++) {
    h.step(250);
    buildingWalkerState(h.driver.world, h.scene).forEach((w, i) => {
      if (Math.abs(w.x - before[i]) > 1) moved += 1;
      anims.add(w.anim);
      speeds.add(w.speed);
    });
  }
  assert.ok(moved > 0);
  assert.ok(anims.has("idle"));
  assert.ok(anims.has("walk"));
  assert.deepEqual([...speeds].sort((a, b) => a - b), [SPEED_ROAM, SPEED_WORK]);
});

test("楼里的小人：有部门工作时站到那个部门门口，向左停靠，姿势为 idle", () => {
  // quality 是四个部门房间的第三项（下标 2），门口的 x 与原型一致：150 + 2 * 96 + 40 = 382
  const h = mountBuilding(model([floor("p-a", { quality: true })]));
  let standing: { x: number; facing: number; anim: string; speed: number; moving: boolean } | null = null;
  for (let k = 0; k < 40; k++) {
    h.step(250);
    const w = buildingWalkerState(h.driver.world, h.scene)[0];
    if (w && !w.moving) standing = w;
  }
  assert.ok(standing);
  assert.equal(standing.x, 382);
  assert.equal(standing.facing, -1);
  assert.equal(standing.anim, "idle");
  assert.equal(standing.speed, SPEED_WORK);
});

test("楼里的小人：空闲层在多个随机位置之间走动", () => {
  const h = mountBuilding(model([floor("p-b", {})]));
  const xs = new Set<number>();
  for (let k = 0; k < 40; k++) {
    h.step(250);
    const w = buildingWalkerState(h.driver.world, h.scene)[0];
    if (w) xs.add(w.x);
  }
  assert.ok(xs.size >= 3, `空闲层的走位位置数应不少于 3，实际 ${xs.size}`);
});

test("楼里的小人：竖井管道随用着机器的楼层流动", () => {
  const withMachine = floor("p-a");
  withMachine.machine_ids = ["m1"];
  withMachine.link_active = true;
  const h = mountBuilding(model([withMachine]));
  h.step(800);
  const link = h.driver.world.links["floor:p-a>basement"];
  assert.ok(link, "用着机器的楼层应有通往机房的管线");
  assert.equal(h.scene.pipeState(link.id)?.state, "flowing");
  h.driver.jump(model([floor("p-a")], 1));
  h.step(1600);
  assert.equal(h.driver.world.links["floor:p-a>basement"], undefined, "去掉机器以后不再声明这根管线");
});

// ---------------------------------------------------------------------------
// 楼的动作：层闪光与撒彩带

test("动作：层闪光按声明的时长亮着，采纳撒彩带并闪绿光", () => {
  const h = mountBuilding(model([floor("p-a"), floor("p-b")]));
  h.driver.play({ kind: "floor_flash", position: 3, project: "p-a", color: "yellow" });
  h.step(50);
  assert.deepEqual(h.driver.flashOf("p-a"), { color: "yellow", until: 1250 });
  assert.equal(h.driver.flashOf("p-b"), null);
  h.step(1300);
  assert.equal(h.driver.flashOf("p-a"), null, "声明的 1200 毫秒以后不再闪光");

  // 采纳：撒彩带，同时闪绿光（颜色由楼的演法定，动作不带颜色）
  const before = h.scene.particles.length;
  h.driver.play({ kind: "celebrate", position: 6, project: "p-b" });
  h.step(50);
  assert.equal(h.driver.flashOf("p-b")?.color, "green");
  assert.ok(h.scene.particles.length > before, "采纳时这一层撒彩带");
});

test("动作：楼的声明表里没有的种类抛错，不静默地什么都不做", () => {
  const h = mountBuilding(model([floor("p-a")]));
  assert.throws(
    () => h.driver.play({ kind: "machine_flash", position: 7, project: "p-a", color: "green" }),
    /楼的声明表里没有这种动作/,
  );
});

test("动作：楼里的动作不占参与方（同一层可以连着演，不用等）", () => {
  const h = mountBuilding(model([floor("p-a")]));
  h.driver.play({ kind: "floor_flash", position: 1, project: "p-a", color: "white" });
  h.driver.play({ kind: "floor_flash", position: 2, project: "p-a", color: "yellow" });
  h.step(50);
  assert.deepEqual(h.driver.inspectTimeline().playing.map((p) => p.kind), ["floor_flash", "floor_flash"]);
  assert.deepEqual(h.driver.inspectTimeline().playing.map((p) => p.lanes), [[], []]);
});

// ---------------------------------------------------------------------------
// 播放时间线：状态等动作演完，跳到最新直接显示

test("状态：等位置不大于它的动作演完再上画面；跳到最新直接显示，不补播", () => {
  const h = mountBuilding(model([floor("p-a")]));
  h.driver.play({ kind: "floor_flash", position: 10, project: "p-a", color: "white" });
  h.step(50);
  assert.deepEqual(h.driver.inspectTimeline().playing.map((p) => p.kind), ["floor_flash"]);
  // 位置比动作大的状态：这一层的闪光还在演，状态先等着
  h.driver.setState(model([floor("p-a", { engineering: true })], 20));
  h.step(100);
  assert.equal(h.driver.model.floors[0].lit.engineering, false, "动作还在演，状态先不上画面");
  assert.equal(h.driver.inspectTimeline().pending, 1);
  h.step(1300);
  assert.equal(h.driver.model.floors[0].lit.engineering, true, "动作演完以后状态上画面");

  // 跳到最新：清空时间线，直接显示给出的状态，不补播
  h.driver.play({ kind: "floor_flash", position: 40, project: "p-a", color: "yellow" });
  h.driver.jump(model([floor("p-a")], 40));
  const info = h.driver.inspectTimeline();
  assert.deepEqual(info.playing, []);
  assert.equal(info.pending, 0);
  assert.equal(info.shown, 40);
  assert.equal(info.stats.started, 1, "只演过前面那一个动作");
  h.step(1000);
  assert.equal(h.driver.inspectTimeline().stats.started, 1, "jump 以后过去的时间不补播积下的动作");
});

// ---------------------------------------------------------------------------
// 状态灯的词与配色

test("状态灯：画面合同的每个取值都有状态词与配色，服务端的状态词一个也没有", () => {
  for (const sign of FLOOR_SIGNS) {
    assert.ok(BUILDING_STATUS[sign], `画面合同的状态灯 ${sign} 没有状态词`);
    assert.ok(BUILDING_STATUS[sign].text.length > 0, `${sign} 的状态词是空的`);
    assert.match(BUILDING_STATUS[sign].color, /^#/, `${sign} 的配色不是颜色`);
  }
  assert.deepEqual(Object.keys(BUILDING_STATUS).sort(), [...FLOOR_SIGNS].sort());
  for (const server of ["running", "held", "waiting_provider", "waiting_decision", "stopped"]) {
    assert.equal(Object.prototype.hasOwnProperty.call(BUILDING_STATUS, server), false, `状态灯里不该有服务端的 ${server}`);
  }
  // 楼只画两种动作（层闪光、撒彩带）；动作带的颜色名都能落到配色上，表里没有的按白光画
  assert.deepEqual(Object.keys(BUILDING_KINDS).sort(), ["celebrate", "floor_flash"]);
  for (const name of FLASH_COLOR_NAMES) assert.equal(flashColorOf(name), name);
  assert.equal(flashColorOf("purple"), "white");
});

// ---------------------------------------------------------------------------
// 导入方向：画面层只认画面合同

/** 一份文件里的所有模块路径（静态 import 与 export ... from）。 */
function importPaths(code: string): string[] {
  const paths: string[] = [];
  for (const m of code.matchAll(/(?:^|\n)\s*(?:import|export)[^;\n]*?from\s+["']([^"']+)["']/g)) paths.push(m[1]);
  for (const m of code.matchAll(/(?:^|\n)\s*import\s+["']([^"']+)["']/g)) paths.push(m[1]);
  return paths;
}

test("导入：pixel/building/ 不导入 views/、api/ 与 contract/", () => {
  const base = new URL("../../src/renderer/src/pixel/building/", import.meta.url);
  const offenders: string[] = [];
  for (const entry of readdirSync(base, { withFileTypes: true })) {
    if (!entry.isFile() || !/\.(ts|tsx)$/.test(entry.name)) continue;
    for (const path of importPaths(readFileSync(new URL(entry.name, base), "utf8"))) {
      // ../contract.ts 是画面合同（允许）；contract/ 是页面的命令接口（不许）
      if (/(^|\/)(views|api|contract)\//.test(path)) offenders.push(`pixel/building/${entry.name} → ${path}`);
    }
  }
  assert.deepEqual(offenders, [], `画面层不许导入页面、接口与命令接口：\n${offenders.join("\n")}`);
});


