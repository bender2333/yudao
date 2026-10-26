// 首页楼的画面对象：画布挂在宿主元素上，提供 setState、jump、play、resize、destroy、inspect
// （原型 v13 js/pixel/building.js 的 createBuildingScene 与画面与播放设计说明第 3 至 5 节，工单 #178、#955）。
//
// 画面的输入只有画面合同（pixel/contract.ts）：状态带位置、动作带位置与 kind（kind 取楼的声明表
// pixel/building/building-decl.ts）。打开画面、重新同步、标签页从后台切回都用 jump：清空时间线，
// 直接显示最新状态，不补播。
//
// 世界的推进（world/building.ts）与绘制（building/render.ts）都不依赖画布与 WebGL；这里只把画好的画布挂到页面上，
// 画布按设备分辨率绘制（surface.ts：像素尺寸为逻辑尺寸乘整数倍 k，先设缩放再按逻辑坐标绘制，工单 #365）。
// 楼层数变化时逻辑高度随之改变，重排画布。

import type { Clock } from "../clock.ts";
import { createPixelSurface } from "../surface.ts";
import { buildCatalog } from "./../world/floor-decl.ts";
import { createScene } from "../world/scene.ts";
import {
  BUILDING_GEO, buildingWalkerState, createBuildingDriver, emptyBuildingModel,
  type BuildingDriver, type BuildingModel,
} from "../world/building.ts";
import { BuildingRenderer } from "./render.ts";
import type { PixelAction } from "../contract.ts";
import type { SceneLike } from "../world/types.ts";

export type { BuildingFloor, BuildingModel } from "../world/building.ts";

/** 首页楼的画面对象：只认画面合同（状态、动作）。 */
export interface BuildingView {
  /** 一份状态：等它之前的动作演完再上画面（由播放时间线决定）。 */
  setState(state: BuildingModel): void;
  /** 跳到最新：清空时间线，正在演的立刻结束，直接显示给出的状态，不补播。 */
  jump(state: BuildingModel): void;
  /** 一个动作：进播放时间线，按声明演出。 */
  play(action: PixelAction): void;
  resize(): void;
  destroy(): void;
  /** 画面逻辑尺寸，供宿主与测试读取。 */
  readonly size: { W: number; H: number };
  /** 世界的当前状态、驱动、场景与绘制（测试与回放读取）。 */
  inspect(): { driver: BuildingDriver; scene: SceneLike; renderer: BuildingRenderer };
}

export interface BuildingViewOptions {
  host: HTMLElement;
  clock: Clock;
  /** 点击楼层进入项目概览。 */
  onFloorClick?: (projectId: string) => void;
}

/** 建立首页的楼画面：画布按设备分辨率绘制，整数倍铺满容器宽度。 */
export async function createBuildingView(opts: BuildingViewOptions): Promise<BuildingView> {
  let width = BUILDING_GEO.W;
  let height = BUILDING_GEO.ROOF + BUILDING_GEO.FH + BUILDING_GEO.BASE;
  // 画布按设备分辨率绘制：像素尺寸为逻辑尺寸乘整数倍 k，图形与文字都按设备分辨率光栅化
  const surface = createPixelSurface({ host: opts.host, W: width, H: height });
  const canvas = surface.canvas;

  const catalog = buildCatalog({});
  const scene = createScene({
    W: width,
    H: height,
    random: () => Math.random(),
    reduced: reducedMotion(),
    tween: (target, vars) => opts.clock.tween(target, vars),
    reapply: () => opts.clock.reapply(),
  });
  const driver = createBuildingDriver({ model: emptyBuildingModel(), scene, catalog, random: () => Math.random() });
  const renderer = new BuildingRenderer(driver, scene);

  let last = 0;

  function draw(): void {
    // 楼层数变化时逻辑高度随之改变：重排画布与场景尺寸以后重画
    applySize();
    renderer.draw(surface.frame());
  }

  /** 楼层数变化时逻辑高度随之改变：重排画布与场景尺寸。 */
  function applySize(): void {
    const next = renderer.height();
    if (next === height) return;
    height = next;
    scene.H = height;
    surface.resizeTo(width, height);
    surface.resize();
  }

  surface.resize();
  driver.jump(emptyBuildingModel());
  draw();
  const offTick = opts.clock.onTick((elapsed) => {
    const delta = Math.max(0, elapsed - last);
    last = elapsed;
    scene.stepScene(delta);
    driver.step();
    scene.reapply();
    draw();
  });

  const onResize = (): void => {
    surface.resize();
    draw();
  };
  window.addEventListener("resize", onResize);

  // 点击楼层进入项目概览：按行的 y 定位楼层（原型 floorAt）
  const floorAt = (ev: MouseEvent): string | null => {
    const rect = canvas.getBoundingClientRect();
    const y = ((ev.clientY - rect.top) / rect.height) * height;
    const i = Math.floor((y - BUILDING_GEO.ROOF) / BUILDING_GEO.FH);
    const floor = driver.model.floors[i];
    return floor ? floor.project_id : null;
  };
  const onClick = (ev: MouseEvent): void => {
    const pid = floorAt(ev);
    if (pid) opts.onFloorClick?.(pid);
  };
  const onMove = (ev: MouseEvent): void => {
    canvas.style.cursor = floorAt(ev) ? "pointer" : "default";
  };
  canvas.addEventListener("click", onClick);
  canvas.addEventListener("mousemove", onMove);

  return {
    get size() {
      return { W: width, H: height };
    },
    setState(state) {
      driver.setState(state);
      draw();
    },
    jump(state) {
      driver.jump(state);
      draw();
    },
    play(action) {
      driver.play(action);
      draw();
    },
    resize() {
      surface.resize();
      draw();
    },
    destroy() {
      offTick();
      window.removeEventListener("resize", onResize);
      canvas.removeEventListener("click", onClick);
      canvas.removeEventListener("mousemove", onMove);
      if (canvas.parentNode === opts.host) opts.host.removeChild(canvas);
    },
    inspect: () => ({ driver, scene, renderer }),
  };
}

/** 端到端测试的入口：按需要给出每层、每层小人与播放时间线的当前状态（含类型，测试不猜形状）。 */
export interface BuildingTestHooks {
  floors: () => { project_id: string; name: string; status: string; lit: Record<string, boolean>; valve_closed: boolean; decisions: number; flags: { work_item_id: string; department: string; color_index: number }[] }[];
  walkers: () => { id: string; x: number; y: number; anim: string }[];
  /** 时间线此刻的读数：画面上状态的位置、还排着几份状态、在演的动作（「直接显示最新状态」的核对）。 */
  timeline: () => { shown: number | null; pending: number; lag: number; queued: number; playing: string[] };
}

/** 建立给端到端测试用的读取入口：读的是画面里楼的当前状态。 */
export function buildingTestHooks(view: BuildingView): BuildingTestHooks {
  return {
    floors: () => view.inspect().driver.model.floors.map((f) => ({
      project_id: f.project_id, name: f.name, status: f.status, lit: { ...f.lit },
      valve_closed: f.valve_closed, decisions: f.decisions, flags: f.flags.map((fl) => ({ ...fl })),
    })),
    walkers: () => {
      const { driver, scene } = view.inspect();
      return buildingWalkerState(driver.world, scene).map((w) => ({ id: w.id, x: w.x, y: w.y, anim: w.anim }));
    },
    timeline: () => {
      const info = view.inspect().driver.inspectTimeline();
      return { shown: info.shown, pending: info.pending, lag: info.lag, queued: info.queued, playing: info.playing.map((p) => p.kind) };
    },
  };
}

/** 系统设置为减少动画。 */
function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
