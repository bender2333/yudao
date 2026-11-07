// 画法取样：把 shapes.ts 与 paint.ts 里的画法在离屏画布上画一遍，再读回点阵。
// 图鉴页与联系表用它给每个画法生成一致的小样；读回的点阵按整数倍最近邻放大，像素不模糊。
// 浏览器里用真实的 2D 画布；纯逻辑测试不依赖这里（那些走 char.ts / grid.ts 的点阵路径）。

import { PAL } from "./registry.ts";
import type { Grid } from "./grid.ts";
import {
  drawArrow,
  drawBox,
  drawBubble,
  drawHourglass,
  drawPixelText,
  drawShadow,
  drawSign,
  drawStampMark,
  fillPixelOutlined,
} from "./shapes.ts";
import { paint } from "./paint.ts";

export interface SampledGrid {
  grid: Grid;
  w: number;
  h: number;
}

/** 取一张离屏画布并清空；底色用画面的暗色，方便看清浅色画法。 */
function offscreen(w: number, h: number, bg: string): CanvasRenderingContext2D {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d");
  if (!ctx) throw new Error("画法取样需要 2D 画布");
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);
  return ctx;
}

/** 把画布读回点阵（与原型 gridCanvas 同一条路径的逆过程）。 */
function readGrid(ctx: CanvasRenderingContext2D, w: number, h: number): SampledGrid {
  const img = ctx.getImageData(0, 0, w, h);
  const grid: Grid = new Array<string | null>(w * h).fill(null);
  for (let i = 0; i < w * h; i++) {
    const a = img.data[i * 4 + 3];
    if (a === 0) continue;
    const r = img.data[i * 4];
    const g = img.data[i * 4 + 1];
    const b = img.data[i * 4 + 2];
    grid[i] = `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
  }
  return { grid, w, h };
}

const BG = "#1b1d27";

/** 逐个画法的取样：在图鉴里各画一遍，读回点阵。 */
export const DRAWING_SAMPLERS: Record<string, () => SampledGrid> = {
  drawShadow: () => {
    const ctx = offscreen(48, 24, BG);
    drawShadow(ctx, 24, 14, 20);
    return readGrid(ctx, 48, 24);
  },
  box: () => {
    const ctx = offscreen(56, 26, BG);
    drawBox(ctx, 4, 4, 48, 18, PAL.paper, { hi: PAL.white, lo: PAL.paper3 });
    return readGrid(ctx, 56, 26);
  },
  bubble: () => {
    const ctx = offscreen(56, 34, BG);
    drawBubble(ctx, 3, 3, 46, 18, { kind: "say", tx: 26 });
    drawBubble(ctx, 8, 22, 40, 10, { kind: "think", tx: 14 });
    return readGrid(ctx, 56, 34);
  },
  sign: () => {
    const ctx = offscreen(60, 46, BG);
    drawSign(ctx, 30, 40, "暂停", { size: 7, pole: 8, bg: PAL.blue1, stripe: PAL.blue2 });
    return readGrid(ctx, 60, 46);
  },
  stampMark: () => {
    const ctx = offscreen(48, 28, BG);
    drawStampMark(ctx, 24, 14, "有效", PAL.red2, { size: 7 });
    return readGrid(ctx, 48, 28);
  },
  arrow: () => {
    const ctx = offscreen(64, 28, BG);
    drawArrow(ctx, [[4, 20], [30, 20], [46, 8]], PAL.yellow2);
    return readGrid(ctx, 64, 28);
  },
  hourglass: () => {
    const ctx = offscreen(24, 24, BG);
    drawHourglass(ctx, 8, 4, 600);
    return readGrid(ctx, 24, 24);
  },
  pixText: () => {
    const ctx = offscreen(64, 16, BG);
    drawPixelText(ctx, "3.2C-9", 2, 4, PAL.screen3);
    return readGrid(ctx, 64, 16);
  },
  RB: () => {
    const ctx = offscreen(48, 24, BG);
    fillPixelOutlined(ctx, 8, 6, 30, 12, PAL.wood2);
    return readGrid(ctx, 48, 24);
  },
  // 陈设画法：每一项各画一遍（坐标足够容纳该画法）
  ...Object.fromEntries(
    Object.entries(paint).map(([name, fn]) => [
      `paint.${name}`,
      () => {
        const w = 120;
        const h = 96;
        const ctx = offscreen(w, h, BG);
        // 用统一的入参让画法自己决定画在哪：多数画法以 (x, y) 为左下或左上角
        fn(ctx, 24, 80, {}, 600);
        return readGrid(ctx, w, h);
      },
    ]),
  ),
};

/** 取某个画法的小样；没有对应取样时返回 null（图鉴只列说明）。 */
export function sampleDrawing(name: string): SampledGrid | null {
  const fn = DRAWING_SAMPLERS[name];
  return fn ? fn() : null;
}
