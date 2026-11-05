// 首页的楼的世界与系统（原型 v10 building.js 的 createBuildingScene、原型 v13 building.js 的楼、
// 设计说明第 7 节「楼」，工单 #178、#955）。
//
// 每个项目一层，画成缩小的项目楼层：部门房间的灯、事项的小旗、楼层入口的阀门与一盏状态灯；
// 楼里每层一个小人（角色实体，没有房间），走位与待机由 world/characters.ts 的 stepCharacters 推进；
// 每个用着机器的项目一根通往机房的管线（管道实体，沿右侧竖井下到地下室）。
//
// 楼的状态来自画面合同（pixel/contract.ts 的 BuildingState）加上画面上还要用的几个字段（名牌、灯、小旗、
// 阀门、决定计数）：世界与系统不导入 api/generated 里的服务端类型，服务端的说法只出现在翻译层
// （translate/building.ts，工单 #955）。
//
// 什么时候演由播放时间线决定（pixel/timeline.ts）：动作按级别与声明时长进来（pixel/building/building-decl.ts），
// 楼里的动作都是闪光与彩带、不占参与方，开始演的同时就算演完；状态等它之前的动作演完再上画面，
// jump 清空时间线直接显示（打开、重新同步、标签页切回）。
//
// 世界与系统不依赖渲染与 PixiJS，可以直接在 node --test 下驱动：#82 的角色、包裹与管道机制
// 在这里被复用，本模块只补「每层一个小人、每层一根竖井管道」的驱动与「楼层数据」的形状。

import {
  FLASH_COLORS, type BuildingFloor, type BuildingModel, type FlashColor, type PixelAction,
} from "../contract.ts";
import { create as createTimeline, type Timeline, type TimelineEntry, type TimelineInspect } from "../timeline.ts";
import { BUILDING_KINDS } from "../building/building-decl.ts";
import { stepCharacters, stepPipes } from "./characters.ts";
import { createWorld, declareLinks } from "./declare.ts";
import type { Catalog, Character, Pipe, SceneLike, World } from "./types.ts";

// 楼的一层（BuildingFloor）与楼的状态（BuildingModel）的形状在画面合同里（pixel/contract.ts）：
// 翻译层只从合同取状态形状，不导入画面层的实现。这里转发出去，画面与测试的入口不变。
export type { BuildingFloor, BuildingModel, FlashColor };

/** 没有数据时的空状态：带位置 0，一层也没有。 */
export function emptyBuildingModel(): BuildingModel {
  return { position: 0, floors: [], show_basement: false };
}

/** 楼里闪光的颜色名（画面合同 FLASH_COLORS 的别名，原型 v13 building.js 的用法）。 */
export const FLASH_COLOR_NAMES = FLASH_COLORS;


/** 动作里的颜色名；不在表里的按白光画（翻译层只给这几种）。 */
export function flashColorOf(value: unknown): FlashColor {
  return typeof value === "string" && (FLASH_COLOR_NAMES as readonly string[]).includes(value) ? (value as FlashColor) : "white";
}

/** 一层的闪光：颜色与持续到哪个时刻（楼里的动作只在这些地方看得见）。 */
export interface FloorFlash {
  color: FlashColor;
  until: number;
}

/** 楼的世界与系统：世界、场景、每层的走位驱动与播放时间线。 */
export interface BuildingDriver {
  world: World;
  model: BuildingModel;
  /** 一份状态：等它之前的动作演完再上画面（由播放时间线决定）。 */
  setState(state: BuildingModel): void;
  /** 跳到最新：清空时间线，正在演的立刻结束，直接显示给出的状态，不补播。 */
  jump(state: BuildingModel): void;
  /** 一个动作：进播放时间线，按声明演出。 */
  play(action: PixelAction): void;
  /** 推进一帧：时间线、每层小人的走位、竖井管道与包裹。 */
  step(): void;
  /** 时间线此刻的读数（状态的位置、排着的状态、在演的动作）。 */
  inspectTimeline(): TimelineInspect;
  /** 一层此刻的闪光；没有闪光时为 null。 */
  flashOf(projectId: string): FloorFlash | null;
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

/** 建立一个楼驱动：世界、走位与播放时间线都在这里维护，画面渲染只读这里给出的世界与模型。 */
export function createBuildingDriver(opts: BuildingDriverOptions): BuildingDriver {
  const world = createWorld(opts.catalog);
  const modelRef: { model: BuildingModel } = { model: opts.model };
  // 每层此刻的闪光（原型 building.js 的 flashes）：颜色名与持续到的时刻
  const flashes: Record<string, FloorFlash> = {};

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
      progress: null,
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
    // 不再显示的楼层，闪光也一并清掉
    for (const pid of Object.keys(flashes)) {
      if (!modelRef.model.floors.some((f) => f.project_id === pid)) delete flashes[pid];
    }
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

  /** 状态上画面：重新按快照配置世界（新增或去掉楼层、同步每层的小人、重声明竖井管道）。 */
  function applyModel(model: BuildingModel): void {
    modelRef.model = model;
    declareShafts();
    syncWalkers();
  }

  /** 楼的动作：这一层闪一下（颜色写在动作里），采纳时撒彩带（画面层按绿光画）。 */
  function perform(action: PixelAction, ms: number): void {
    const project = typeof action.project === "string" ? action.project : null;
    if (!project) return;
    if (action.kind === "floor_flash" || action.kind === "celebrate") {
      const color: FlashColor = action.kind === "celebrate" ? "green" : flashColorOf(action.color);
      flashes[project] = { color, until: opts.scene.realT + ms };
    }
    if (action.kind === "celebrate") {
      const i = modelRef.model.floors.findIndex((f) => f.project_id === project);
      if (i >= 0) opts.scene.emit("confetti", BUILDING_GEO.W / 2, floorY(i), 24, { spread: 400 });
    }
  }

  // 播放时间线：排队的规则只在 pixel/timeline.ts；楼里的动作不占参与方，开始演的同时就算演完
  const tl: Timeline = createTimeline({
    clock: () => opts.scene.realT,
    classify(action) {
      const decl = BUILDING_KINDS[action.kind];
      if (!decl) throw new Error("楼的声明表里没有这种动作：" + action.kind);
      return { tier: decl.tier, ms: decl.ms, lanes: [] };
    },
    begin(entry: TimelineEntry) {
      perform(entry.action, entry.ms);
      tl.done(entry.id);
    },
    cut() {
      // 楼里的动作一进来就演完，没有可以立刻结束的部分
    },
    apply(state) {
      applyModel(state as unknown as BuildingModel);
    },
    progress() {
      throw new Error("楼里没有进度一级的动作");
    },
  });

  function setState(state: BuildingModel): void {
    tl.state(state);
  }

  function jump(state: BuildingModel): void {
    tl.jump(state);
  }

  function play(action: PixelAction): void {
    tl.push(action);
  }

  const driver: BuildingDriver = {
    world,
    get model() {
      return modelRef.model;
    },
    setState,
    jump,
    play,
    step() {
      tl.tick();
      updateWalkers();
      // 楼里的小人没有房间，queue 恒为空，走位与待机由 stepCharacters 推进
      stepCharacters(world, opts.scene);
      stepPipes(world, opts.scene, shaftState);
    },
    inspectTimeline: () => tl.inspect(),
    flashOf: (projectId) => {
      const flash = flashes[projectId];
      return flash && flash.until > opts.scene.realT ? flash : null;
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


