// 项目楼层声明的陈设画法（原型 v10 floor-decl.js 的房间 props、lit、tint，工单 #82）。
//
// 这些函数需要画布原语，因此放在渲染层；世界与系统只读声明里的数据与规则。
// 每个函数按房间 id 与 floor-decl.js 逐行对应。

import { paint } from "../paint.ts";
import { drawBitmap, drawSign, drawText } from "../shapes.ts";
import { PAL } from "../registry.ts";
import { GEO } from "../world/declare.ts";
import type { RoomVisual } from "../world/types.ts";

const R = (c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, col: string): void => {
  c.fillStyle = col;
  c.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
};
const RB = (c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, col: string): void => {
  R(c, x - 1, y - 1, w + 2, h + 2, PAL.ink);
  R(c, x, y, w, h, col);
};

/** 房间的陈设画法：与 floor-decl.js 的 ROOMS 一一对应。 */
export const ROOM_VISUALS: Record<string, RoomVisual> = {
  product: {
    props(c, r) {
      RB(c, r.x + r.w - 34, GEO.FLOOR_LINE + 8, 20, 30, PAL.wood3);
      for (let i = 0; i < 3; i++) R(c, r.x + r.w - 31, GEO.FLOOR_LINE + 12 + i * 9, 14, 5, PAL.paper2);
    },
  },
  engineering: {
    props(c, r) {
      RB(c, r.x + r.w - 36, GEO.FLOOR_LINE + 22, 22, 16, PAL.metal3);
      drawBitmap(c, "box_sealed", r.x + r.w - 31, GEO.FLOOR_LINE + 12);
    },
  },
  quality: {
    props(c, r) {
      RB(c, r.x + r.w - 36, GEO.FLOOR_LINE + 24, 22, 12, PAL.white2);
      drawBitmap(c, "magnifier", r.x + r.w - 29, GEO.FLOOR_LINE + 14);
    },
  },
  operations: {
    // 有运维数据的项目里这个房间始终亮着
    lit: (ctx) => Boolean(ctx.model.ops),
    // 监控屏出现故障时整个房间泛红光
    tint(c, r, t, ctx) {
      if (!((ctx.model.ops && ctx.model.ops.fault) || ctx.sig("monitor"))) return;
      const k = ctx.reduced ? 0.12 : 0.08 + 0.07 * Math.max(0, Math.sin(t / 160));
      c.fillStyle = `rgba(255,50,50,${k.toFixed(3)})`;
      c.fillRect(r.x, GEO.TOP, r.w, GEO.ROOM_B - GEO.TOP);
    },
    props(c, r, t, ctx) {
      const ops = ctx.model.ops;
      const fault = (ops && ops.fault) || ctx.sig("monitor");
      // 监控屏
      const mx = r.x + r.w - 44;
      const my = GEO.TOP + 16;
      RB(c, mx - 2, my - 2, 40, 26, PAL.grey5);
      paint.screen(c, mx, my, { w: 36, h: 22, mode: fault ? "error" : "ok", seed: 3 }, t);
      drawText(c, ops && ops.version ? `运行 ${ops.version}` : "监控屏", mx + 18, my + 30, { size: 5.5, weight: 700, align: "center", color: PAL.white });
      // 备份柜与小推车
      RB(c, r.x + 8, GEO.FLOOR_LINE + 4, 18, 34, PAL.metal3);
      for (let i = 0; i < 3; i++) RB(c, r.x + 10, GEO.FLOOR_LINE + 7 + i * 10, 14, 7, i === 0 ? PAL.green2 : PAL.metal2);
      paint.cart(c, r.x + 30, GEO.ROOM_B - 6, {});
      if (ops && ops.auto_repair_stopped) {
        drawSign(c, r.x + r.w / 2, GEO.ROOM_B + 26, "停止自动修复", { size: 6, bg: PAL.red2, fg: PAL.white, stripe: PAL.red3, maxW: r.w + 10, nail: GEO.ROOM_B + 3 });
      }
    },
  },
};
