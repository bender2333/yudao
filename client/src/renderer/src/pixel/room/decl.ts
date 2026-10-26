// 部门房间的工位排布（原型 v13 room.js 的 spriteFor、rolesOf、layoutDesks，工单 #954）：
// 角色与精灵、中心角色、工位位置。
//
// 这里只留工位排布：事件到动作由翻译层（translate/room.ts）翻，级别与时长在 room-decl.ts，
// 状态值到画面值的对应在 translate/tables.ts。

import { ROLE_KINDS } from "../registry.ts";
import type { RoomRole } from "./layout.ts";

/** 中心角色的种类（原型 room.js 的 CENTER_KIND）。 */
export const CENTER_KIND: Record<string, string> = {
  product: "architect", engineering: "architect", quality: "tester", operations: "ops",
};

/** Stage 5 的工位横向位置（原型 room.js 的 SLOT_X）。 */
export const SLOT_X = [16, 92, 168, 244, 320];
const TOOL_ORDER = ["lead", "explorer", "reviewer", "architect", "tester"];

/** 角色种类对应的精灵名（原型 spriteFor）：运维部门的操作与 Agent 都取 ops。 */
export function spriteForRole(dept: string, kind: string): string {
  let k = kind || "agent";
  if (dept === "operations" && (k === "agent" || k === "ops")) k = "ops";
  if (!(k in ROLE_KINDS)) throw new Error(`未知角色种类：${k}`);
  return `${dept}.${k}`;
}

/** 房间里的角色列表：没有角色设置时一个部门一个 Agent。 */
export function rolesOf(model: { department: string; roles: RoomRole[] }): RoomRole[] {
  const dept = model.department;
  if (model.roles.length) return model.roles;
  const kind = dept === "operations" ? "ops" : "agent";
  return [{ id: "agent", name: "", kind, status: "idle" }];
}

/** 一个角色有没有中心位置（原型 CENTER_KIND）。 */
export function isCenterRole(dept: string, role: RoomRole): boolean {
  return role.kind === CENTER_KIND[dept];
}

/** 工位排布（原型 layoutDesks 的 S5 分支）：中心居中、经理靠右墙，工具角色在两侧。 */
export function layoutDesks(dept: string, roles: RoomRole[], level: string): { x: number; w: number }[] {
  const n = roles.length;
  if (n <= 1) return [{ x: 150, w: 64 }];
  const centerIdx = roles.findIndex((r) => isCenterRole(dept, r));
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
