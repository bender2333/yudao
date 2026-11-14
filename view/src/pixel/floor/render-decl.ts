// 项目楼层声明的陈设画法与房间外壳配色（原型 v10 floor-decl.js 的房间 props、lit、tint，工单 #82、#1383）。
//
// 这些函数需要画布原语，因此放在渲染层场景声明；世界与系统只读声明里的数据与规则。
// 默认三职能与运维的外观集中在本声明按角色标识查表；未知角色使用通用灰米外观，盖章台只画在核验角色屋里。

import { paint } from "../paint.ts";
import { drawBitmap, drawSign, drawText } from "../shapes.ts";
import { DEPTS, PAL } from "../registry.ts";
import { GEO } from "../world/declare.ts";
import type { Room, RoomVisual } from "../world/types.ts";

const R = (c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, col: string): void => {
  c.fillStyle = col;
  c.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
};
const RB = (c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, col: string): void => {
  R(c, x - 1, y - 1, w + 2, h + 2, PAL.ink);
  R(c, x, y, w, h, col);
};

/** 房间外壳的画法配色。 */
export interface ShellPaint {
  wall: string;
  wall2: string;
  trim: string;
  floor: string;
  floor2?: string;
}

/** 职能屋配色（默认三职能与运维在场景声明查表，未知角色取通用灰米配色）。 */
export interface RoomShell extends ShellPaint {
  name: string;
  main: string;
  shade: string;
  light: string;
}

const DECLARED_ROOM_SHELLS: Readonly<Record<string, RoomShell>> = {
  product: DEPTS.product,
  engineering: DEPTS.engineering,
  quality: DEPTS.quality,
  operations: DEPTS.operations,
};

/** 未在场景声明登记的职能使用的通用灰米外壳配色。 */
export const GENERIC_ROOM_SHELL: RoomShell = {
  name: "",
  main: "#8b8578",
  shade: "#666055",
  light: "#dcd6c8",
  wall: "#e4dfd3",
  wall2: "#d6d0c2",
  trim: "#6e685c",
  floor: "#c2b8a3",
  floor2: "#b3a892",
};

/** 按角色标识查房间外壳配色。 */
export function roomShellOf(roomId: string): RoomShell {
  return DECLARED_ROOM_SHELLS[roomId] ?? GENERIC_ROOM_SHELL;
}

/** 判断角色标识在楼层渲染声明里是否有专属外壳与陈设外观。 */
export function hasDeclaredRoomVisual(roomId: string): boolean {
  return Object.prototype.hasOwnProperty.call(DECLARED_ROOM_SHELLS, roomId);
}

function drawStampStation(c: CanvasRenderingContext2D, r: Room): void {
  RB(c, r.x + r.w - 36, GEO.FLOOR_LINE + 24, 22, 12, PAL.white2);
  drawBitmap(c, "magnifier", r.x + r.w - 29, GEO.FLOOR_LINE + 14);
}

function drawExitTray(c: CanvasRenderingContext2D, r: Room): void {
  const tx = r.x + r.w - 36;
  const ty = GEO.FLOOR_LINE + 25;
  RB(c, tx, ty, 22, 11, PAL.wood3);
  R(c, tx + 2, ty + 2, 18, 7, PAL.paper);
  R(c, tx + 4, ty - 2, 14, 4, PAL.paper2);
}

function drawGenericCabinet(c: CanvasRenderingContext2D, r: Room): void {
  RB(c, r.x + r.w - 34, GEO.FLOOR_LINE + 16, 18, 22, PAL.metal2);
  R(c, r.x + r.w - 31, GEO.FLOOR_LINE + 20, 12, 4, PAL.paper2);
}

/** 房间的陈设画法：与 floor-decl.ts 的声明对应；盖章台只在核验角色屋里画出，出口托盘在交完成角色屋里画出。 */
export const ROOM_VISUALS: Record<string, RoomVisual> = {
  product: {
    props(c, r) {
      if (r.def.verifier) {
        drawStampStation(c, r);
        return;
      }
      if (r.def.exitTray) {
        drawExitTray(c, r);
        return;
      }
      RB(c, r.x + r.w - 34, GEO.FLOOR_LINE + 8, 20, 30, PAL.wood3);
      for (let i = 0; i < 3; i++) R(c, r.x + r.w - 31, GEO.FLOOR_LINE + 12 + i * 9, 14, 5, PAL.paper2);
    },
  },
  engineering: {
    props(c, r) {
      if (r.def.verifier) {
        drawStampStation(c, r);
        return;
      }
      if (r.def.exitTray) {
        drawExitTray(c, r);
        return;
      }
      RB(c, r.x + r.w - 36, GEO.FLOOR_LINE + 22, 22, 16, PAL.metal3);
      drawBitmap(c, "box_sealed", r.x + r.w - 31, GEO.FLOOR_LINE + 12);
    },
  },
  quality: {
    props(c, r) {
      if (r.def.verifier === false) {
        if (r.def.exitTray) drawExitTray(c, r);
        else drawGenericCabinet(c, r);
        return;
      }
      drawStampStation(c, r);
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
      if (r.def.verifier) drawStampStation(c, r);
      if (ops && ops.auto_repair_stopped) {
        drawSign(c, r.x + r.w / 2, GEO.ROOM_B + 26, "停止自动修复", { size: 6, bg: PAL.red2, fg: PAL.white, stripe: PAL.red3, maxW: r.w + 10, nail: GEO.ROOM_B + 3 });
      }
    },
  },
};

/** 按角色标识与拓扑标记取陈设画法：核验角色画盖章台，交完成角色画出口托盘，其余角色画通用陈设。 */
export function roomVisualOf(roomId: string, flags: { verifier: boolean; exitTray: boolean }): RoomVisual {
  const declared = ROOM_VISUALS[roomId];
  if (declared) return declared;
  return {
    props(c, r) {
      if (flags.verifier) {
        drawStampStation(c, r);
      } else if (flags.exitTray) {
        drawExitTray(c, r);
      } else {
        drawGenericCabinet(c, r);
      }
    },
  };
}
