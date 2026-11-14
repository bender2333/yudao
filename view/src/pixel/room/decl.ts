// 房间的角色声明与工位排布（画面与播放 docs/design/visualization.md「推出的规则」「外观」，工单 #954、#1384）：
// 默认三职能与运维的专属外观、小人精灵前缀、中心角色、工作台与后墙陈设集中在此按角色标识查表；
// 未登记的角色使用通用房间外观回退；检验台只跟着房间状态的核验角色布尔标记出现。

import { DEPTS, PAL, ROLE_KINDS } from "../registry.ts";
import type { RoomRole } from "./layout.ts";

/** 房间外壳配色。 */
export interface RoomShellPaint {
  name: string;
  main: string;
  shade: string;
  light: string;
  wall: string;
  wall2: string;
  wall3?: string;
  trim: string;
  floor: string;
  floor2?: string;
  floor3?: string;
  rug: string;
  rug2: string;
}

export type RoomWallPattern = "wainscot_stripes" | "brick_pipe" | "dado_band" | "server_cables" | "plain_dado";
export type RoomFloorPattern = "parquet" | "steel_tile" | "small_tile" | "raised_floor";
export type RoomWallDecor = "idea_books" | "blueprint_tools" | "check_vials" | "waveform_vents" | "plain_frame";
export type RoomBackPiece = "scroll_rack" | "delivery_rack" | "sample_cabinet" | "monitor_wall" | "generic_shelf";

/** 非核验工作台的样式与名称。 */
export interface NonVerifierBenchSpec {
  style: "scroll_table" | "seal_table" | "work_table";
  top: string;
  face: string;
  label: string;
}

/** 一类房间角色的外观与能力声明。 */
export interface RoomAppearance {
  defaultLabel: string;
  shell: RoomShellPaint;
  spriteDept: string;
  defaultSingleKind: "agent" | "ops";
  centerKind: string;
  machineRoomStyle: boolean;
  hasBench: boolean;
  selfTestShot: boolean;
  wallPattern: RoomWallPattern;
  floorPattern: RoomFloorPattern;
  hasRug: boolean;
  wallDecor: RoomWallDecor;
  backPiece: RoomBackPiece;
  backPieceTitle: string;
  deskWood: [string, string, string, string] | null;
  nonVerifierBench: NonVerifierBenchSpec;
}

/** 核验角色房间里的检验台名称。 */
export const VERIFIER_BENCH_LABEL = "检验台";

/** 核验角色未单独登记中心工种时的中心角色种类。 */
export const VERIFIER_CENTER_KIND = "tester";

/** 未登记角色的通用灰米房间配色。 */
export const GENERIC_ROOM_SHELL: RoomShellPaint = {
  name: "",
  main: "#8b8578",
  shade: "#666055",
  light: "#dcd6c8",
  wall: "#e4dfd3",
  wall2: "#d6d0c2",
  wall3: "#c7c0b0",
  trim: "#6e685c",
  floor: "#c2b8a3",
  floor2: "#b3a892",
  floor3: "#a1957e",
  rug: "#b8ae99",
  rug2: "#9e947e",
};

/** 未登记角色的通用房间外观回退。 */
export const GENERIC_ROOM_APPEARANCE: RoomAppearance = {
  defaultLabel: "",
  shell: GENERIC_ROOM_SHELL,
  spriteDept: "engineering",
  defaultSingleKind: "agent",
  centerKind: "architect",
  machineRoomStyle: false,
  hasBench: true,
  selfTestShot: false,
  wallPattern: "plain_dado",
  floorPattern: "parquet",
  hasRug: true,
  wallDecor: "plain_frame",
  backPiece: "generic_shelf",
  backPieceTitle: "资料架",
  deskWood: null,
  nonVerifierBench: {
    style: "work_table",
    top: PAL.wood1,
    face: PAL.wood2,
    label: "工作台",
  },
};

/** 默认三职能与运维的房间外观声明表（按角色标识索引）。 */
export const ROOM_APPEARANCES: Readonly<Record<string, RoomAppearance>> = {
  product: {
    defaultLabel: "产品",
    shell: DEPTS.product,
    spriteDept: "product",
    defaultSingleKind: "agent",
    centerKind: "architect",
    machineRoomStyle: false,
    hasBench: true,
    selfTestShot: false,
    wallPattern: "wainscot_stripes",
    floorPattern: "parquet",
    hasRug: true,
    wallDecor: "idea_books",
    backPiece: "scroll_rack",
    backPieceTitle: "卷轴架",
    deskWood: null,
    nonVerifierBench: {
      style: "scroll_table",
      top: PAL.wood1,
      face: PAL.wood2,
      label: "卷轴台",
    },
  },
  engineering: {
    defaultLabel: "工程",
    shell: DEPTS.engineering,
    spriteDept: "engineering",
    defaultSingleKind: "agent",
    centerKind: "architect",
    machineRoomStyle: false,
    hasBench: true,
    selfTestShot: true,
    wallPattern: "brick_pipe",
    floorPattern: "steel_tile",
    hasRug: true,
    wallDecor: "blueprint_tools",
    backPiece: "delivery_rack",
    backPieceTitle: "交付存放",
    deskWood: null,
    nonVerifierBench: {
      style: "seal_table",
      top: PAL.metal1,
      face: PAL.metal3,
      label: "封存台",
    },
  },
  quality: {
    defaultLabel: "质检",
    shell: DEPTS.quality,
    spriteDept: "quality",
    defaultSingleKind: "agent",
    centerKind: "tester",
    machineRoomStyle: false,
    hasBench: true,
    selfTestShot: false,
    wallPattern: "dado_band",
    floorPattern: "small_tile",
    hasRug: true,
    wallDecor: "check_vials",
    backPiece: "sample_cabinet",
    backPieceTitle: "样本柜",
    deskWood: [PAL.white, PAL.white2, PAL.white3, PAL.grey3],
    nonVerifierBench: {
      style: "work_table",
      top: PAL.wood1,
      face: PAL.wood2,
      label: "工作台",
    },
  },
  operations: {
    defaultLabel: "运维",
    shell: DEPTS.operations,
    spriteDept: "operations",
    defaultSingleKind: "ops",
    centerKind: "ops",
    machineRoomStyle: true,
    hasBench: false,
    selfTestShot: false,
    wallPattern: "server_cables",
    floorPattern: "raised_floor",
    hasRug: false,
    wallDecor: "waveform_vents",
    backPiece: "monitor_wall",
    backPieceTitle: "备份",
    deskWood: [PAL.grey2, PAL.grey3, PAL.grey4, PAL.grey5],
    nonVerifierBench: {
      style: "work_table",
      top: PAL.wood1,
      face: PAL.wood2,
      label: "工作台",
    },
  },
};

/** 按角色标识查房间外观声明，未登记角色返回通用外观。 */
export function roomAppearanceOf(roleId: string): RoomAppearance {
  return Object.prototype.hasOwnProperty.call(ROOM_APPEARANCES, roleId)
    ? ROOM_APPEARANCES[roleId]
    : GENERIC_ROOM_APPEARANCE;
}

/** 中心角色的种类（原型 room.js 的 CENTER_KIND）。 */
export const CENTER_KIND: Record<string, string> = {
  product: "architect", engineering: "architect", quality: "tester", operations: "ops",
};

/** 按角色标识与是否核验角色取中心工种。 */
export function centerRoleKindOf(dept: string, verifier = false): string {
  if (Object.prototype.hasOwnProperty.call(ROOM_APPEARANCES, dept)) {
    return ROOM_APPEARANCES[dept].centerKind;
  }
  return verifier ? VERIFIER_CENTER_KIND : GENERIC_ROOM_APPEARANCE.centerKind;
}

/** Stage 5 的工位横向位置（原型 room.js 的 SLOT_X）。 */
export const SLOT_X = [16, 92, 168, 244, 320];
const TOOL_ORDER = ["lead", "explorer", "reviewer", "architect", "tester"];

/** 角色种类对应的精灵名（原型 spriteFor）：按声明的精灵前缀组装，未知种类抛出错误。 */
export function spriteForRole(dept: string, kind: string): string {
  const appearance = roomAppearanceOf(dept);
  let k = kind || "agent";
  if (appearance.defaultSingleKind === "ops" && (k === "agent" || k === "ops")) k = "ops";
  if (!(k in ROLE_KINDS)) throw new Error(`未知角色种类：${k}`);
  return `${appearance.spriteDept}.${k}`;
}

/** 房间里的角色列表：没有角色设置时一个房间一个默认 Agent。 */
export function rolesOf(model: { department: string; roles: RoomRole[] }): RoomRole[] {
  if (model.roles.length) return model.roles;
  const kind = roomAppearanceOf(model.department).defaultSingleKind;
  return [{ id: "agent", name: "", kind, status: "idle" }];
}

/** 一个角色有没有中心位置（原型 CENTER_KIND）。 */
export function isCenterRole(dept: string, role: RoomRole, verifier = false): boolean {
  return role.kind === centerRoleKindOf(dept, verifier);
}

/** 工位排布（原型 layoutDesks 的 S5 分支）：中心居中、经理靠右墙，工具角色在两侧。 */
export function layoutDesks(dept: string, roles: RoomRole[], level: string, verifier = false): { x: number; w: number }[] {
  const n = roles.length;
  if (n <= 1) return [{ x: 150, w: 64 }];
  const centerIdx = roles.findIndex((r) => isCenterRole(dept, r, verifier));
  const mgrIdx = roles.findIndex((r) => r.kind === "manager");
  const toolCount = Math.max(0, n - (centerIdx >= 0 ? 1 : 0) - (mgrIdx >= 0 ? 1 : 0));
  const TOOL_SLOTS: Record<number, number[]> = { 1: [1], 2: [0, 3], 3: [0, 1, 3], 4: [0, 1, 3, 4] };
  if (level === "S5") {
    const tools = (TOOL_SLOTS[toolCount] || [0, 1, 3, 4]).slice();
    return roles.map((_r, i) => {
      let slot: number | undefined;
      if (i === centerIdx) slot = 2;
      else if (i === mgrIdx) slot = 4;
      else slot = tools.shift();
      return { x: SLOT_X[slot === undefined ? 0 : slot], w: 56 };
    });
  }
  // Stage 5 之前：按角色数在白板宽度里均匀排开
  const w = n >= 5 ? 54 : 60;
  const gap = n >= 5 ? 6 : n === 4 ? 16 : 30;
  const total = n * w + (n - 1) * gap;
  const x0 = Math.round((296 - total) / 2) + 4;
  return roles.map((_r, i) => ({ x: x0 + i * (w + gap), w }));
}

export { TOOL_ORDER };
