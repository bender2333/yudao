// 首页楼的画面对象：PixiJS 挂在宿主元素上，提供 setModel、playEvent、resize、destroy
// （原型 v9 building.js 的对外接口，工单 #178）。
//
// 世界的推进（world/building.ts）与绘制（building/render.ts）都不依赖 PixiJS；这里只把画好的画布贴到舞台，
// 缩放用最近邻（layoutFor 的整数倍），每帧由共用的时钟驱动。楼层数变化时逻辑高度随之改变，重排画布与纹理。

import { Application, Sprite, Texture } from "pixi.js";
import type { Clock } from "../clock.ts";
import { layoutFor } from "../scale.ts";
import { buildCatalog } from "../world/floor-decl.ts";
import { createScene } from "../world/scene.ts";
import { BUILDING_GEO, buildingWalkerState, createBuildingDriver, type BuildingDriver, type BuildingModel } from "../world/building.ts";
import { BuildingRenderer } from "./render.ts";
import type { PixelFloorEvent, SceneLike } from "../world/types.ts";

export type { BuildingFloor, BuildingModel } from "../world/building.ts";

/** 首页楼的画面对象。 */
export interface BuildingView {
  setModel(model: BuildingModel): void;
  playEvent(event: PixelFloorEvent): void;
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

/** 建立首页的楼画面：画好的画布贴到 PixiJS 的舞台上，整数倍最近邻缩放到容器宽度。 */
export async function createBuildingView(opts: BuildingViewOptions): Promise<BuildingView> {
  const app = new Application();
  await app.init({ background: "#12101c", antialias: false, autoDensity: false, resolution: 1 });
  const canvas = app.canvas;
  canvas.style.imageRendering = "pixelated";
  canvas.style.display = "block";
  opts.host.appendChild(canvas);

  let width = BUILDING_GEO.W;
  let height = BUILDING_GEO.ROOF + BUILDING_GEO.FH + BUILDING_GEO.BASE;
  // 离屏画布：世界与楼层的画法都画在这里，再作为纹理贴到舞台
  let surface = document.createElement("canvas");
  let ctx = surface.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;
  let texture = Texture.from(surface);
  const sprite = new Sprite(texture);
  app.stage.addChild(sprite);

  const catalog = buildCatalog({});
  const scene = createScene({
    W: width,
    H: height,
    random: () => Math.random(),
    reduced: reducedMotion(),
    tween: (target, vars) => opts.clock.tween(target, vars),
    reapply: () => opts.clock.reapply(),
  });
  const empty: BuildingModel = { floors: [], show_basement: false };
  const driver = createBuildingDriver({ model: empty, scene, catalog, random: () => Math.random() });
  const renderer = new BuildingRenderer(driver, scene);

  let last = 0;

  function applyLayout(): void {
    const rect = opts.host.getBoundingClientRect();
    const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
    const lay = layoutFor(width, height, rect.width || width, rect.height || height, dpr);
    app.renderer.resize(lay.bufferW, lay.bufferH);
    canvas.style.width = `${lay.cssW}px`;
    canvas.style.height = `${lay.cssH}px`;
    sprite.scale.set(lay.k);
  }

  function draw(): void {
    ctx.clearRect(0, 0, width, height);
    renderer.draw(ctx);
    texture.source.update();
    app.renderer.render(app.stage);
  }

  /** 楼层数变化时逻辑高度随之改变：重排画布、场景尺寸与纹理。 */
  function applySize(): void {
    const next = renderer.height();
    if (next === height) return;
    height = next;
    surface = document.createElement("canvas");
    surface.width = width;
    surface.height = height;
    ctx = surface.getContext("2d")!;
    ctx.imageSmoothingEnabled = false;
    scene.H = height;
    sprite.texture = Texture.from(surface);
    texture.destroy(true);
    texture = sprite.texture;
    applyLayout();
  }

  applyLayout();
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
    applyLayout();
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
    setModel(model) {
      driver.setModel(model);
      applySize();
      draw();
    },
    playEvent(event) {
      playBuildingEvent(driver, event);
      draw();
    },
    resize() {
      applyLayout();
      draw();
    },
    destroy() {
      offTick();
      window.removeEventListener("resize", onResize);
      canvas.removeEventListener("click", onClick);
      canvas.removeEventListener("mousemove", onMove);
      if (canvas.parentNode === opts.host) opts.host.removeChild(canvas);
      texture.destroy(true);
      app.destroy(false, { children: true });
    },
    inspect: () => ({ driver, scene, renderer }),
  };
}

/** 事件变成楼上的动作（原型 building.js 的 playEvent）：远程动作与部署、回滚的包裹沿竖井管线走。 */
function playBuildingEvent(driver: BuildingDriver, event: PixelFloorEvent): void {
  if (!event || !event.project_id) return;
  if (event.type === "x_remote_action_started") driver.sendOnShaft(event.project_id, "folder", false);
  else if (event.type === "x_remote_action_finished") driver.sendOnShaft(event.project_id, "letter", true);
  else if (event.type === "x_deployed") driver.sendOnShaft(event.project_id, "box_sealed", false);
  else if (event.type === "x_rolled_back") driver.sendOnShaft(event.project_id, "box_sealed", true);
}

/** 端到端测试的入口：按需要给出每层与每层小人的当前状态（含类型，测试不猜形状）。 */
export interface BuildingTestHooks {
  floors: () => { project_id: string; name: string; status: string; lit: Record<string, boolean>; valve_closed: boolean; decisions: number; flags: { work_item_id: string; department: string; color_index: number }[] }[];
  walkers: () => { id: string; x: number; y: number; anim: string }[];
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
  };
}

/** 系统设置为减少动画。 */
function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
