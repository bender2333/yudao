// 楼里小人的运行时测试（工单 #178 验收标准 1）：把原型 docs/prototypes/v9/checks/walkers.js 的检查
// 改写为对客户端楼世界与系统的测试，直接对世界、角色实体与画面脚本运行，用确定的时钟与随机数。
//
// 覆盖：每层一个小人的角色实体与 actor、走位与待机动画由 stepCharacters 与楼驱动推进、速度（门口 40、随机走动 22）、
// 朝向（门口站定向左）、门口的停靠位置、空闲层在多个随机位置之间走动、层数减少后旧的 actor 与角色实体一并清掉。

import { test } from "node:test";
import assert from "node:assert/strict";

import { buildCatalog } from "../../src/renderer/src/pixel/world/floor-decl.ts";
import { createScene } from "../../src/renderer/src/pixel/world/scene.ts";
import { buildingWalkerState, createBuildingDriver, BUILDING_GEO, SPEED_ROAM, SPEED_WORK } from "../../src/renderer/src/pixel/world/building.ts";
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
    project_id: pid, name: pid, status: "running",
    lit: { product: false, engineering: false, quality: false, operations: false, ...lit },
    has_ops: false, flags: [], valve_closed: false, machine_ids: [], link_active: false, decisions: 0,
  };
}

function model(floors: BuildingFloor[], showBasement = false): BuildingModel {
  return { floors, show_basement: showBasement };
}

interface Harness {
  driver: ReturnType<typeof createBuildingDriver>;
  scene: ReturnType<typeof createScene>;
  step: (ms: number) => void;
}

function mountBuilding(m: BuildingModel): Harness {
  const scene = createScene({ W: BUILDING_GEO.W, H: BUILDING_GEO.ROOF + BUILDING_GEO.FH + BUILDING_GEO.BASE, random: seeded(), reduced: false });
  const driver = createBuildingDriver({ model: m, scene, catalog, random: seeded() });
  driver.setModel(m);
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
  h.driver.setModel(model([floor("p-a")]));
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
  h.driver.setModel(model([floor("p-a")]));
  h.step(1600);
  assert.equal(h.driver.world.links["floor:p-a>basement"], undefined, "去掉机器以后不再声明这根管线");
});
