// 部门房间的布局常量与位置表（原型 v10 room.js 的 W、H、BASE、L、SPOT、STATUS_TEXT、POSE_ALIAS、
// BENCH_LABEL、S，工单 #177）。这些是数据与坐标，渲染层按它们画、驱动器按它们走位。

import { LEVELS, PAL } from "../registry.ts";

export const W = 480;
export const H = 240;
export const BASE = 130;
export const AISLE = 140;
export const ROW_A = 176;
export const ROW_B = 216;

/** 房间里的陈设位置（原型 room.js 的 L）。 */
export const L = {
  window: { x: 12, y: 16, w: 46, h: 40 },
  clock: { x: 64, y: 12 },
  crt: { x: 82, y: 10, w: 128, h: 70 },
  wb: { x: 222, y: 72, w: 84, h: 42, floor: 132 },
  back: { x: 316 },
  door: { x: 390, base: 120, w: 36, h: 60 },
  cork: { x: 434, y: 74, w: 30, h: 28 },
  mailbox: { x: 430, base: 132 },
  plant: { x: 464, base: 134 },
  cabinet: { x: 12, base: 130 },
  cards: { x: 46, base: 130 },
  terminal: { x: 100, base: 130 },
  tray: { x: 170, base: 132 },
  bench: { x: 300, w: 86, y: ROW_A },
  lamps: [140, 270, 380],
  beacon: { x: 405, y: 44 },
  pipe: { x: 428, base: 176 },
  tube: { x: 428, base: 150 },
  post: { x: 76, base: 182 },
  tool: { x: 330, y: 30, w: 46, h: 26 },
  trial: { x: 216, w: 76, y: ROW_A },
  monitor: { x: 314, y: 44, w: 48, h: 30 },
  backup: { x: 316, base: BASE },
  mdoor: { x: 34, base: 182, w: 26, h: 40 },
};

/** 命名位置：任务的目标点（原型 room.js 的 SPOT；第三项是到达后的朝向）。 */
export const SPOT: Record<string, [number, number] | [number, number, number]> = {
  cabinet: [52, 132, -1], archive: [52, 132, -1], cards: [82, 134, -1], terminal: [84, 132, 1],
  tray: [157, 134, 1], wb: [264, 134], rack: [346, 134], bench: [343, ROW_A], benchSide: [290, ROW_A, 1],
  door: [408, 136], doorIn: [408, 122], mailbox: [440, 139, 1], cork: [451, 136], crtLook: [146, 140],
  center: [262, 142], pipe: [420, 186, -1], tube: [418, 152, -1], post: [66, 186, 1],
  mdoor: [28, 186, 1], monitor: [352, 92, 1], tool: [350, 150, 1], trial: [254, ROW_A, 1],
};

/** 部门状态的文字（原型 room.js 的 STATUS_TEXT）。 */
export const STATUS_TEXT: Record<string, string> = {
  idle: "未工作", working: "工作中", asking: "等待回答", paused: "已暂停", failed: "失败", done: "已完成",
  cancelled: "已取消", interrupted: "中断", waiting_resume: "待恢复",
};

/** 部门状态的颜色（原型 room.js 的 STATUS_COLOR；未登记的取屏幕暗色）。 */
export const STATUS_COLOR: Record<string, string> = {
  working: PAL.screen3, asking: PAL.blue1, paused: PAL.blue1, failed: PAL.red1, done: PAL.green1,
  cancelled: PAL.grey1, interrupted: PAL.grey2, waiting_resume: PAL.yellow2,
  idle: PAL.screen2,
};

/** 档位比较（原型 engine.js 的 levelAtLeast）：ui ≤ 3.1 ≤ 3.2C ≤ … ≤ S5。陈设与试用的有无按档位决定。 */
export function levelAtLeast(level: string | undefined, min: string): boolean {
  const a = LEVELS.indexOf(level || "ui");
  const b = LEVELS.indexOf(min);
  if (a < 0 || b < 0) throw new Error(`未知档位：${level} / ${min}`);
  return a >= b;
}

/** 各部门工作台的名字（原型 room.js 的 BENCH_LABEL）。 */
export const BENCH_LABEL: Record<string, string> = {
  product: "卷轴台", engineering: "封存台", quality: "检验台",
};

/** 走路与动作的脚本步骤（原型 room.js 的 S）。 */
export type RoomStep =
  | { t: "go"; x: number; y: number; gait?: string; speed?: number }
  | { t: "anim"; name: string; ms?: number; key?: boolean; facing?: number }
  | { t: "wait"; ms: number; key?: boolean }
  | { t: "call"; fn: () => void }
  | { t: "hold"; item: string | null }
  | { t: "turn"; facing: number }
  | { t: "icon"; icon: { kind: string; text?: string } | null }
  | { t: "seat"; seat: RoomSeat | null }
  | { t: "fade"; to: number; ms: number };

/** 工位（渲染与坐姿用）。 */
export interface RoomSeat {
  i?: number;
  x: number;
  w: number;
  seatX: number;
  seatY: number;
  roleId: string;
  role: RoomRole;
  trial?: boolean;
}

/** 房间声明的角色（一份 roomModel.roles 或一个部门的唯一 Agent）。 */
export interface RoomRole {
  id: string;
  name: string;
  kind: string;
  status: string;
  task?: string | null;
}

export const S = {
  go: (x: number, y: number, gait?: string, speed?: number): RoomStep => ({ t: "go", x, y, gait, speed }),
  anim: (name: string, ms?: number, key?: boolean, facing?: number): RoomStep => ({ t: "anim", name, ms, key, facing }),
  wait: (ms: number, key?: boolean): RoomStep => ({ t: "wait", ms, key }),
  call: (fn: () => void): RoomStep => ({ t: "call", fn }),
  hold: (item: string | null): RoomStep => ({ t: "hold", item }),
  turn: (facing: number): RoomStep => ({ t: "turn", facing }),
  icon: (icon: { kind: string; text?: string } | null): RoomStep => ({ t: "icon", icon }),
  seat: (seat: RoomSeat | null): RoomStep => ({ t: "seat", seat }),
  fade: (to: number, ms: number): RoomStep => ({ t: "fade", to, ms }),
};

/** 房间里的部门（原型支持 product、engineering、quality、operations）。 */
export const ROOM_DEPTS = ["product", "engineering", "quality", "operations"] as const;
export type RoomDept = (typeof ROOM_DEPTS)[number];
