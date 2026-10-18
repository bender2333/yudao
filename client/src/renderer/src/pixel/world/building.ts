// 首页的楼的世界与系统（原型 v10 building.js 的 createBuildingScene、设计说明第 7 节「楼」，工单 #178）。
//
// 每个项目一层，画成缩小的项目楼层：部门房间的灯、事项的小旗、楼层入口的阀门与一盏状态灯；
// 楼里每层一个小人（角色实体，没有房间），走位与待机由 world/characters.ts 的 stepCharacters 推进；
// 每个用着机器的项目一根通往机房的管线（管道实体，沿右侧竖井下到地下室）。
//
// 世界与系统不依赖渲染与 PixiJS，可以直接在 node --test 下驱动：#82 的角色、包裹与管道机制
// 在这里被复用，本模块只补「每层一个小人、每层一根竖井管道」的驱动与「楼层数据」的形状。

import { sendPackage, spawnPackage, stepCharacters, stepPackages, stepPipes } from "./characters.ts";
import { createWorld, declareLinks, polyLength } from "./declare.ts";
import type { Catalog, Character, Pipe, SceneLike, World } from "./types.ts";

/** 楼的一层：一个项目的缩小楼层（原型 building.js 的 floor 数据与 scenes.js 的 buildingModels）。 */
export interface BuildingFloor {
  project_id: string;
  name: string;
  /** 楼层的状态灯：运行中、排队中、等待执行槽位、等待模型服务、待恢复、等待你的决定、中断、空闲。 */
  status: string;
  /** 四个部门房间的灯：亮灯表示该部门正在工作。 */
  lit: { product: boolean; engineering: boolean; quality: boolean; operations: boolean };
  /** 有没有运维（机房与运行环境）。 */
  has_ops: boolean;
  /** 事项的小旗：在本层房间里的事项，按部门挂在房门口。 */
  flags: { work_item_id: string; color_index: number; department: string }[];
  /** 入口阀门：等待执行槽位时关闭。 */
  valve_closed: boolean;
  /** 用着机器的设备编号：通往机房的管线按它画。 */
  machine_ids: string[];
  /** 通往机房的管线是否在流动。 */
  link_active: boolean;
  /** 本层等待回答的决定请求数（名牌右上角的计数）。 */
  decisions: number;
}

/** 楼的画面数据（原型 building.js 的 model）。 */
export interface BuildingModel {
  floors: BuildingFloor[];
  /** 底部是否留出地下室的位置（机房由 #117 实现）。 */
  show_basement: boolean;
}

/** 楼的世界与系统：世界、场景、每层的走位驱动与竖井管道的发送。 */
export interface BuildingDriver {
  world: World;
  model: BuildingModel;
  /** 重新按快照配置世界：新增或去掉楼层、同步每层的小人、重声明竖井管道。 */
  setModel(model: BuildingModel): void;
  /** 远程动作与部署、回滚的包裹沿这一层通往机房的管线走（出去往下，回滚与回执往上）。 */
  sendOnShaft(projectId: string, bmp: string, up: boolean): void;
  /** 推进一帧：每层小人的走位、竖井管道与包裹。 */
  step(): void;
}

/** 楼里小人的速度：走到门口 40 像素/秒、随机走动 22 像素/秒（原型 building.js 的 SPEED_WORK/SPEED_ROAM）。 */
export const SPEED_WORK = 40;
export const SPEED_ROAM = 22;
const ROAM_MIN = 3000;
const ROAM_SPAN = 5000;

/** 楼里的小人 actor 对应的角色 id 就是项目标识（actor 的 id 为 'ch-' + 项目标识）。 */
export const WALKER_ACTOR_PREFIX = "ch-";

/** 楼的几何（原型 building.js 第 24 至 26 行）。 */
export const BUILDING_GEO = { W: 640, ROOF: 34, FH: 66, BASE: 10 } as const;

/** 每层走位的状态：小人是留在本层（没有房间），散步的下一趟时间记在这里。 */
interface WalkerData {
  next: number;
}

interface BuildingDriverOptions {
  model: BuildingModel;
  scene: SceneLike;
  catalog: Catalog;
  /** 随机数：与原型一致由外部给出，测试可用确定的序列。 */
  random: () => number;
}

/** 建立一个楼驱动：世界与走位都在这里维护，画面渲染只读这里给出的世界与模型。 */
export function createBuildingDriver(opts: BuildingDriverOptions): BuildingDriver {
  const world = createWorld(opts.catalog);
  const modelRef: { model: BuildingModel } = { model: opts.model };

  const floorY = (i: number): number => BUILDING_GEO.ROOF + i * BUILDING_GEO.FH;
  const roomX = (k: number): number => 150 + k * 96;
  const walkerActor = (pid: string): NonNullable<SceneLike["actors"][number]> | null =>
    opts.scene.actors.find((x) => x.id === WALKER_ACTOR_PREFIX + pid) ?? null;

  // 每层的小人：角色实体没有房间，department 置 null；走位由本模块的 step 与 stepCharacters 推进
  function addWalker(f: BuildingFloor, i: number): void {
    const x = 130 + (i * 97) % 360;
    const y = floorY(i) + BUILDING_GEO.FH - 6;
    const ch: Character = {
      kind: "character",
      id: f.project_id,
      department: null,
      roleKind: "",
      name: f.name,
      seatIndex: 0,
      spot: { x, y },
      queue: [],
      current: null,
      rest: null,
      bubble: null,
      item: null,
      roleInfo: null,
      idleAt: null,
    };
    world.characters[f.project_id] = ch;
    const sprite = `${["product", "engineering", "quality"][i % 3]}.agent`;
    opts.scene.addActor({
      id: WALKER_ACTOR_PREFIX + f.project_id,
      sprite,
      x,
      y,
      anim: "idle",
      speed: SPEED_ROAM,
      data: { walker: true, next: 0 },
    });
  }

  /** 让每层都有一个小人，去掉不再显示楼层的小人与角色实体。 */
  function syncWalkers(): void {
    for (const actor of opts.scene.actors.filter((x) => x.data.walker)) {
      const pid = actor.id.slice(WALKER_ACTOR_PREFIX.length);
      if (!modelRef.model.floors.some((f) => f.project_id === pid)) {
        delete world.characters[pid];
        opts.scene.removeActor(actor);
      }
    }
    modelRef.model.floors.forEach((f, i) => {
      const actor = walkerActor(f.project_id);
      if (!actor || !world.characters[f.project_id]) {
        addWalker(f, i);
        return;
      }
      const y = floorY(i) + BUILDING_GEO.FH - 6;
      actor.y = y;
      world.characters[f.project_id].spot.y = y;
    });
  }

  /** 通往机房的竖井管道：从这一层的出口横着走到右侧竖井，再沿竖井下到地下室的位置。 */
  function shaftPts(f: BuildingFloor, i: number): [number, number][] {
    const y = floorY(i);
    const x0 = roomX(3) + (f.has_ops ? 82 : 0);
    const sx = BUILDING_GEO.W - 22 - (i % 6) * 3;
    const drop = (modelRef.model.floors.length - i) * BUILDING_GEO.FH - 30;
    return [[x0, y + 31], [sx + 1, y + 31], [sx + 1, y + 30 + drop + BUILDING_GEO.BASE]];
  }

  function declareShafts(): void {
    declareLinks(world, modelRef.model.floors
      .filter((f) => f.machine_ids.length > 0)
      .map((f) => ({
        from: `floor:${f.project_id}`,
        to: "basement",
        kind: "shaft" as const,
        valve: false,
        pts: shaftPts(f, modelRef.model.floors.indexOf(f)),
      })));
  }

  // 每层的走位（原型 building.js 的 update）：有部门工作时站到那个部门门口，空闲时随机走动
  function updateWalkers(): void {
    modelRef.model.floors.forEach((f) => {
      const ch = world.characters[f.project_id];
      if (!ch) return;
      const actor = walkerActor(f.project_id);
      if (!actor || actor.script) return;
      const working = (["product", "engineering", "quality", "operations"] as const).findIndex((d) => f.lit[d]);
      if (working >= 0) {
        const tx = roomX(working) + 40;
        actor.speed = SPEED_WORK;
        ch.spot.y = actor.y;
        if (Math.abs(actor.x - tx) > 2) ch.spot.x = tx;
        else if (actor.facing !== -1) actor.facing = -1;
      } else {
        actor.speed = SPEED_ROAM;
        ch.spot.y = actor.y;
        const data = actor.data as unknown as WalkerData;
        if (opts.scene.realT > data.next) {
          data.next = opts.scene.realT + ROAM_MIN + opts.random() * ROAM_SPAN;
          ch.spot.x = 130 + opts.random() * 400;
        }
      }
    });
  }

  const driver: BuildingDriver = {
    world,
    get model() {
      return modelRef.model;
    },
    setModel(model) {
      modelRef.model = model;
      declareShafts();
      syncWalkers();
    },
    sendOnShaft(projectId, bmp, up) {
      const link = world.links[`floor:${projectId}>basement`];
      if (!link || opts.scene.reduced) return;
      const id = `pk-${projectId}-${Math.round(opts.scene.realT)}-${up ? "up" : "down"}`;
      spawnPackage(world, id, null, null, null, null);
      const pk = world.packages[id];
      pk.bmp = bmp;
      const pts = up ? link.pts.slice().reverse() : link.pts;
      sendPackage(world, opts.scene, id, link.id, pts, Math.max(700, polyLength(pts) * 9), () => {
        delete world.packages[id];
      });
    },
    step() {
      updateWalkers();
      // 楼里的小人没有房间，queue 恒为空，走位与待机由 stepCharacters 推进
      stepCharacters(world, opts.scene);
      stepPipes(world, opts.scene, shaftState);
      stepPackages(world, opts.scene);
    },
  };

  /** 竖井管道的流动：本层用着机器（link_active）或管线上有包裹时流动，否则空闲。 */
  function shaftState(pipe: Pipe): "flowing" | "idle" {
    const pid = pipe.from.startsWith("floor:") ? pipe.from.slice("floor:".length) : pipe.from;
    const floor = modelRef.model.floors.find((f) => f.project_id === pid);
    const active = (floor?.link_active ?? false)
      || Object.values(world.packages).some((pk) => pk.transit?.linkKey === pipe.id);
    return active ? "flowing" : "idle";
  }

  return driver;
}

/** 楼里的小人在画面上的当前状态（测试与画面共用；只读世界与 actor）。 */
export function buildingWalkerState(world: World, scene: SceneLike): { id: string; x: number; y: number; anim: string; speed: number; facing: number; moving: boolean }[] {
  return Object.keys(world.characters).sort().map((id) => {
    const actor = scene.actors.find((a) => a.id === WALKER_ACTOR_PREFIX + id);
    return {
      id,
      x: actor ? Math.round(actor.x) : 0,
      y: actor ? Math.round(actor.y) : 0,
      anim: actor ? actor.anim : "idle",
      speed: actor ? actor.speed : 0,
      facing: actor ? actor.facing : 1,
      moving: Boolean(actor && actor.script),
    };
  });
}
