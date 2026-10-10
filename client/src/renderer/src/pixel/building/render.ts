// 首页的楼的画法：把每层的缩小楼层画到 2D 画布上（原型 v10 building.js 的 draw 与 drawFloor、设计说明第 7 节，工单 #178）。
//
// 每层为四个部门房间留了固定的位置：部门房间的灯、房门口的事项小旗、楼层入口的阀门与一盏状态灯；
// 名牌与状态灯在左侧，通往机房的管线沿右侧竖井下到地下室的位置；楼里每层一个小人。
// 画法复用已有的画布原语（shapes、char、grid 与 registry），与原型逐行对应。

import { bitmapGrid } from "../char.ts";
import { mix, rgba } from "../grid.ts";
import { DEPTS, ITEM_COLORS, ITEM_SHADES, PAL } from "../registry.ts";
import { drawActor, drawBitmap, drawPixelText, drawSign, drawText, fillPixel, fillPixelOutlined } from "../shapes.ts";
import type { SceneLike } from "../world/types.ts";
import { BUILDING_GEO, type BuildingDriver, type BuildingFloor } from "../world/building.ts";

const { W, ROOF, FH, BASE } = BUILDING_GEO;
const ROOMS = ["product", "engineering", "quality", "operations"] as const;

/** 状态灯与状态文字的配色（原型 building.js 的 STATUS，颜色取 PAL 的子集）。 */
export const BUILDING_STATUS: Record<string, { text: string; color: string }> = {
  running: { text: "运行中", color: PAL.green2 },
  queued: { text: "排队中", color: PAL.grey2 },
  waiting_slot: { text: "等待执行槽位", color: PAL.orange2 },
  waiting_provider: { text: "等待模型服务", color: PAL.grey3 },
  pending_verification: { text: "待核实", color: PAL.yellow2 },
  waiting_resume: { text: "待恢复", color: PAL.yellow2 },
  waiting_decision: { text: "等待你的决定", color: PAL.yellow2 },
  interrupted: { text: "中断", color: PAL.grey4 },
  stopped: { text: "已停止", color: PAL.grey4 },
  idle: { text: "空闲", color: PAL.grey2 },
};

/** 每分钟闪烁的状态灯（原型 drawFloor 的判据）。 */
const BLINK = ["running", "waiting_slot", "pending_verification", "waiting_resume"];

/** 楼的绘制：屋顶、每层的楼层、通往机房的管线、包裹与小人。 */
export class BuildingRenderer {
  private bg: HTMLCanvasElement | null = null;
  private bgKey = "";

  constructor(private readonly driver: BuildingDriver, private readonly scene: SceneLike) {}

  /** 楼的逻辑高度：屋顶加每层的高度加底部留出的地下室位置。 */
  height(): number {
    return ROOF + Math.max(1, this.driver.model.floors.length) * FH + BASE;
  }

  /** 画一帧。 */
  draw(c: CanvasRenderingContext2D): void {
    const t = this.scene.animT;
    c.imageSmoothingEnabled = false;
    c.drawImage(this.background(), 0, 0);
    this.driver.model.floors.forEach((f, i) => this.floor(c, f, i, t));
    this.shafts(c);
    this.packages(c);
    const walkers = this.scene.actors.filter((a) => a.data.walker).sort((p, q) => p.y - q.y);
    for (const a of walkers) drawActor(c, this.scene, a);
    this.particles(c);
    fillPixel(c, 0, this.height() - BASE, W, BASE, "#5a6070");
    if (this.driver.model.show_basement) {
      drawText(c, "▼ 地下室：机房", W / 2, this.height() - BASE / 2, { size: 6, weight: 700, align: "center", color: PAL.white });
    }
  }

  /** 屋顶与天空：楼层随数量变化的部分每次重画（原型 draw 的前半）。 */
  private background(): HTMLCanvasElement {
    const key = String(this.driver.model.floors.length);
    if (this.bg && this.bgKey === key) return this.bg;
    this.bgKey = key;
    const h = this.height();
    const cv = document.createElement("canvas");
    cv.width = W;
    cv.height = h;
    const c = cv.getContext("2d")!;
    c.imageSmoothingEnabled = false;
    fillPixel(c, 0, 0, W, h, "#9fd0ee");
    for (const [x, y] of [[40, 10], [300, 6], [520, 14]]) {
      fillPixel(c, x, y, 26, 5, PAL.white);
      fillPixel(c, x + 6, y - 3, 14, 3, PAL.white);
    }
    fillPixel(c, 6, ROOF - 10, W - 12, 10, "#6f7a8c");
    fillPixel(c, 6, ROOF - 10, W - 12, 1, "#8e98a9");
    drawSign(c, W / 2, ROOF - 12, "Yudao 枢道", { size: 7, bg: PAL.paper, stripe: PAL.wood3 });
    fillPixel(c, 6, ROOF, 6, h - ROOF, "#4d5466");
    fillPixel(c, W - 12, ROOF, 6, h - ROOF, "#4d5466");
    if (!this.driver.model.floors.length) {
      drawText(c, "还没有项目", W / 2, ROOF + 30, { size: 8, align: "center", color: PAL.ink2 });
    }
    this.bg = cv;
    return cv;
  }

  /** 一层：地板、名牌与状态灯、入口阀门、部门房间的灯与小旗（原型 drawFloor）。 */
  private floor(c: CanvasRenderingContext2D, f: BuildingFloor, i: number, t: number): void {
    const y = ROOF + i * FH;
    const st = BUILDING_STATUS[f.status] ?? BUILDING_STATUS.idle;
    fillPixel(c, 12, y, W - 24, FH, "#e8e0cc");
    fillPixel(c, 12, y + FH - 14, W - 24, 14, "#c9a77a");
    for (let x = 12; x < W - 12; x += 10) fillPixel(c, x, y + FH - 14, 1, 14, "#b8966a");
    fillPixel(c, 12, y, W - 24, 2, "#4d5466");
    // 名牌与状态灯
    fillPixelOutlined(c, 18, y + 8, 104, 20, PAL.paper);
    drawText(c, f.name, 22, y + 15, { size: 7, weight: 700, color: PAL.ink, max: 96 });
    fillPixelOutlined(c, 22, y + 22, 6, 6, st.color);
    if (!this.scene.reduced && BLINK.includes(f.status) && Math.floor(t / 500) % 2) {
      fillPixel(c, 23, y + 23, 2, 2, PAL.white);
    }
    drawText(c, st.text, 32, y + 25.5, { size: 5.5, weight: 700, color: PAL.ink2, max: 88 });
    if (f.decisions) {
      fillPixelOutlined(c, 106, y + 5, 14, 9, PAL.yellow2);
      drawPixelText(c, String(f.decisions), 113, y + 9.5, PAL.ink, "center");
    }
    // 入口阀门：等待执行槽位时关闭
    fillPixelOutlined(c, 128, y + 32, 14, 6, PAL.metal3);
    fillPixelOutlined(c, 131, y + 26, 8, 3, f.valve_closed ? PAL.red2 : PAL.green2);
    if (f.valve_closed) {
      drawSign(c, 70, y + 50, "等待执行槽位", { size: 5.5, bg: PAL.yellow1, stripe: PAL.orange2, maxW: 100 });
    }
    // 部门房间的灯
    ROOMS.forEach((d, k) => {
      if (d === "operations" && !f.has_ops) return;
      const x = 150 + k * 96;
      const D = DEPTS[d];
      const lit = f.lit[d];
      fillPixelOutlined(c, x, y + 8, 80, 36, lit ? D.wall : mix(D.wall, PAL.ink, 0.45));
      fillPixel(c, x + 2, y + 10, 76, 3, D.main);
      if (lit) {
        c.fillStyle = rgba(PAL.yellow1, this.scene.reduced ? 0.45 : 0.35 + 0.1 * Math.sin(t / 400 + k));
        c.fillRect(x + 2, y + 13, 76, 29);
      }
      drawText(c, D.name, x + 40, y + 20, { size: 6, weight: 700, align: "center", color: lit ? PAL.ink : PAL.grey1 });
      // 房门口的事项小旗：按部门挂，颜色取事项的颜色序号
      const flags = f.flags.filter((fl) => fl.department === d);
      flags.forEach((fl, j) => {
        const name = (Math.floor(t / 320) + j) % 2 && !this.scene.reduced ? "flag2" : "flag";
        drawBitmap(c, name, x + 6 + j * 9, y + 28, {
          recolor: { X: ITEM_COLORS[fl.color_index % 6], x: ITEM_SHADES[fl.color_index % 6] },
        });
      });
      if (k < 3 && (!f.has_ops ? k < 2 : true)) fillPixel(c, x + 80, y + 26, 16, 3, PAL.glass2);
    });
  }

  /** 通往机房的管线：从这一层的出口横着走到右侧竖井，再沿竖井下到地下室的位置（原型 drawFloor 的管线出口）。 */
  private shafts(c: CanvasRenderingContext2D): void {
    for (const pipe of Object.values(this.driver.world.links)) {
      const i = this.driver.model.floors.findIndex((f) => pipe.from === `floor:${f.project_id}`);
      if (i < 0) continue;
      const floor = this.driver.model.floors[i];
      const y = ROOF + i * FH;
      const x0 = 150 + 3 * 96 + (floor.has_ops ? 82 : 0);
      const sx = W - 22 - (i % 6) * 3;
      const drop = (this.driver.model.floors.length - i) * FH - 30;
      const col = LINK_COLORS[i % LINK_COLORS.length];
      fillPixel(c, x0, y + 30, sx - x0, 2, col);
      fillPixel(c, sx, y + 30, 2, drop + BASE, col);
      const flow = pipe.flow;
      if (this.scene.reduced || !flow || flow.load <= 0.02) continue;
      const k = (flow.phase / 900 + i * 0.3) % 1;
      c.globalAlpha = flow.load;
      fillPixel(c, sx - 1, y + 30 + k * drop, 4, 3, PAL.yellow2);
      c.globalAlpha = 1;
    }
  }

  /** 包裹沿管线走（原型 drawPackages）。 */
  private packages(c: CanvasRenderingContext2D): void {
    for (const pk of Object.values(this.driver.world.packages)) {
      const pos = pk.transit?.pos;
      if (!pos) continue;
      const name = pk.bmp ?? "box_sealed";
      const b = bitmapGrid(name);
      drawBitmap(c, name, Math.round(pos[0] - b.w / 2), Math.round(pos[1] - b.h / 2));
    }
  }

  private particles(c: CanvasRenderingContext2D): void {
    for (const p of this.scene.particles) {
      const k = 1 - p.age / p.life;
      if (p.kind === "smoke") {
        const r = 2 + Math.floor((p.age / p.life) * 5);
        c.fillStyle = `rgba(92,96,107,${(0.75 * k).toFixed(3)})`;
        c.fillRect(Math.round(p.x) - r, Math.round(p.y) - r + 1, r * 2, r * 2 - 2);
        continue;
      }
      c.globalAlpha = p.kind === "confetti" ? Math.min(1, k * 3) : k;
      c.fillStyle = p.color;
      c.fillRect(Math.round(p.x), Math.round(p.y), p.size, p.size);
      c.globalAlpha = 1;
    }
  }
}

/** 每个项目的管线颜色：取项目在楼中的序号（原型 building.js 的 LINK_COLORS）。 */
export const LINK_COLORS = ["#e8505b", "#3fc1e8", "#8fd14f", "#f7c948", "#f27ec2", "#b98558"];
