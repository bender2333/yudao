// 部门房间的声明：角色与工位的排布、事件到动作的解析（原型 v10 room.js 的 spriteFor、layoutDesks、
// 以及 engine.js 的 EVENT_ACTIONS 与 resolveAction，工单 #177）。
//
// 动作表 EVENT_ACTIONS、动作定义 ACTIONS 与状态到动作的映射 STATUS_ACTIONS 已在注册表里生成
// （scripts/generate_model_capabilities.py，与原型 engine.js 一致），这里只做解析。

import { ACTIONS, ANIMS, EVENT_ACTIONS, LEVELS, ROLE_KINDS, STATUS_ACTIONS } from "../registry.ts";
import type { PixelFloorEvent } from "../world/types.ts";
import { POSE_ALIAS } from "./layout.ts";
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

/** roomModel.pose.action 解析成动画名；无法对应时抛出错误（原型 room.js 的 restFor 检查）。 */
export function poseAnim(action: string): string {
  if (action in ANIMS) return action;
  if (action in POSE_ALIAS) return POSE_ALIAS[action];
  if (action in ACTIONS) return ACTIONS[action].anim;
  throw new Error(`roomModel.pose.action 无法对应到动作：${action}`);
}

// 真实系统有四个工具在原型里没有单独的动作：看目录、删文件、移动文件，以及取代登记命令的 bash。
// 它们的动作按同一类工作取：看目录是翻找，删文件是改，移动文件是改（画面上都是动手改文件）；
// bash 沿用原来 run_command 的终端拉杆动作。
const TOOL_ACTIONS: Record<string, string> = {
  list_files: "search",
  delete_file: "write",
  move_file: "write",
  bash: "run_command",
};

/** 事件到动作（原型 engine.js 的 resolveAction）。 */
export function resolveAction(ev: PixelFloorEvent): string | null {
  if (!ev || !ev.type) throw new Error("事件缺少 type");
  const entry = (EVENT_ACTIONS as Record<string, string | { by: string; map: Record<string, string>; default?: string | null }>)[ev.type];
  if (!entry) return null;
  if (typeof entry === "string") return entry;
  const pl = (ev.payload ?? {}) as Record<string, unknown>;
  // 真实系统把工具名写在载荷的 name 上（登记命令与读取工具都如此），没有映射字段时按它取
  const tool = ev.tool ?? (pl.tool as string) ?? (pl.name as string);
  const key = entry.by === "tool" ? tool
    : entry.by === "reason" ? ((pl.reason as string) ?? (pl.stopReason as string))
      : entry.by === "kind" ? (pl.kind as string)
        : (pl.verdict as string);
  if (entry.by === "tool" && typeof tool === "string" && !(key in entry.map)) {
    return TOOL_ACTIONS[tool] ?? entry.default ?? null;
  }
  return entry.map[key as string] || entry.default || null;
}

/** 档位比较（原型 engine.js 的 levelAtLeast）：ui ≤ 3.1 ≤ 3.2C ≤ … ≤ S5。 */
export function levelAtLeast(level: string | undefined, min: string): boolean {
  const a = LEVELS.indexOf(level || "ui");
  const b = LEVELS.indexOf(min);
  if (a < 0 || b < 0) throw new Error(`未知档位：${level} / ${min}`);
  return a >= b;
}

/** 状态到动作（原型 STATUS_ACTIONS）。 */
export function statusAction(status: string): string | null {
  return (STATUS_ACTIONS as Record<string, string>)[status] ?? null;
}

/** 工具种类对应的房间位置（原型 room.js 的 toolSpot）。 */
export function toolSpot(tool: string | null | undefined): string {
  if (tool === "bash") return "terminal";
  if (tool === "search") return "cabinet";
  if (tool === "run_check") return "bench";
  return "desk";
}

/** 一次跨部门的交接：交出方、接收方与交接的成果（原型 transition 事件载荷的三个字段）。 */
export interface Handoff {
  from: string;
  to: string;
  artifact: string;
}

// 真实系统的 transition 事件的 from/to 是工作阶段（控制核心的阶段迁移），不是部门；
// 这里按阶段归属把跨部门的迁移翻译成原型 transition 的形状（交出方、接收方、成果），
// 哪些迁移是跨部门交接、交接什么，与原型 v8 设计说明第 8.3 节的交接一处一致。
const DEPARTMENTS: Record<string, true> = { product: true, engineering: true, quality: true, operations: true };
// 交接的去处：部门，或成果库（原型录制写 library，真实系统写 adopted）；出处必须是部门。
const HANDOFF_SINKS: Record<string, true> = { library: true, adopted: true, adoption: true };
const PHASE_DEPARTMENT: Record<string, string> = {
  PRODUCT_SPEC: "product", PRODUCT_REVIEW: "product",
  ENGINEERING: "engineering", DELIVERY: "engineering",
  QUALITY: "quality", QUALITY_REVIEW: "quality",
};

/** 把真实 transition 事件翻译成一次交接；不是跨部门交接时为空（同部门内的阶段推进）。 */
export function handoffOf(pl: Record<string, unknown>): Handoff | null {
  // 原型形状（录制数据）：from/to 已经是部门，artifact 直接给出
  const prototypeFrom = typeof pl.from === "string" ? pl.from : null;
  const prototypeTo = typeof pl.to === "string" ? pl.to : null;
  const artifact = typeof pl.artifact === "string" ? pl.artifact : null;
  if (artifact && prototypeFrom && prototypeTo
      && DEPARTMENTS[prototypeFrom] && (DEPARTMENTS[prototypeTo] || HANDOFF_SINKS[prototypeTo])) {
    return { from: prototypeFrom, to: prototypeTo, artifact };
  }
  const route = typeof pl.route === "string" ? pl.route : null;
  if (route === "PRODUCT_SPEC->ENGINEERING") return { from: "product", to: "engineering", artifact: "prd" };
  if (route === "DELIVERY->QUALITY") return { from: "engineering", to: "quality", artifact: "box" };
  if (route === "QUALITY->DONE") return { from: "quality", to: "adopted", artifact: "release" };
  // 其他路由按两端阶段所属的部门判断：部门不同才算交接，成果按交出方给出
  const from = PHASE_DEPARTMENT[String(pl.from)] ?? null;
  const to = PHASE_DEPARTMENT[String(pl.to)] ?? null;
  if (!from || !to || from === to) return null;
  return { from, to, artifact: from === "product" ? "prd" : from === "engineering" ? "box" : "release" };
}

/** 一次跨部门的传信：发问方与收信方（原型 collaboration 事件载荷的 from/to 两个字段）。
 *  `requests` 是本次连接内见过的询问（`request_id` 到两端），用于旧事件缺少 requester/recipient 时补齐；
 *  查不到就不给出两端，调用方因此不显示这个事件。 */
export function collaborationSides(evType: string, pl: Record<string, unknown>,
                                  department: string | null,
                                  requests?: Map<string, { requester: string; recipient: string }>):
                                  { from: string; to: string } | null {
  // 真实系统的载荷写的是 requester 与 recipient；回答方是事件所在的部门，发问方是 requester
  const requestId = typeof pl.request_id === "string" ? pl.request_id : null;
  const seen = requestId && requests ? requests.get(requestId) ?? null : null;
  const requester = (pl.requester as string) ?? seen?.requester ?? null;
  const recipient = (pl.recipient as string) ?? seen?.recipient ?? null;
  if (evType === "collaboration_requested") {
    if (requester && recipient) return { from: requester, to: recipient };
  }
  if (evType === "collaboration_responded") {
    const answerer = department ?? recipient ?? (pl.to as string) ?? null;
    if (requester && answerer) return { from: requester, to: answerer };
  }
  // 原型形状（录制数据）：from/to 已经是部门
  const from = typeof pl.from === "string" ? pl.from : null;
  const to = typeof pl.to === "string" ? pl.to : null;
  return from && to ? { from, to } : null;
}

export { TOOL_ORDER };
