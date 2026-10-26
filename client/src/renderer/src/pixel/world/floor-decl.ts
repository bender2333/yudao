// 项目楼层的声明（原型 v13 floor-decl.js，设计说明第 3 节，工单 #82、#953）。
//
// 世界与系统只用数据与规则：房间与管道的结构、任务目录、动作种类（带级别与声明时长）、待机活动由构建期脚本
// 从原型导出（generated/floor-decl.json）；持续状态的规则（deptRest、roleRest）是纯函数，按原型逐行改写。
// 房间自己的陈设画法（props、lit、tint）需要画布原语，放在渲染层 render-decl.ts 里，与这里的声明一一对应。
//
// 任务的键就是画面的动作种类（原型 v13 的 TASKS 以动作为键）：翻译层翻出来的动作按 kind 落在任务目录上，
// 事件种类与任务键之间不再有对照表（工单 #953 删掉了 keyOf）。

import decl from "../generated/floor-decl.json" with { type: "json" };
import type { Catalog, DeclContext, IdleDef, LinkDef, RestFn, RestState, RoleRestFn, RoomDef, RoomVisual, TaskDef } from "./types.ts";

/** 任务目录（数据来自原型 v13 floor-decl.js 的 TASKS）。 */
export const TASKS = decl.tasks as unknown as Record<string, TaskDef>;

/** 待机活动（数据来自原型 v13 floor-decl.js 的 IDLE）。 */
export const IDLE = decl.idle as unknown as IdleDef[];

/** 不是角色一件事的动作（交接、传信、决定单、闪光……）的级别与时长（原型 v13 floor-decl.js 的 EFFECTS）。 */
export const EFFECTS = decl.effects as unknown as Record<string, { tier: "key" | "normal" | "progress"; ms: number }>;

/** 画面上认的动作种类：级别与声明时长（原型 v13 floor-decl.js 的 KINDS）。 */
export const KINDS = decl.kinds as unknown as Record<string, { tier: "key" | "normal" | "progress"; ms: number }>;

export const DEPT_PORTS = ["in", "out", "tubeIn", "tubeOut"];

/** 房间的声明：结构与字段函数都在这里；props、lit、tint 由渲染层按 id 取。 */
export const ROOMS: RoomDef[] = [
  { id: "hall", label: "大厅", roomKind: "hall", w: 100, pipeOutX: 22 },
  {
    id: "product", label: "产品", roomKind: "dept", w: 110, agentKind: "agent", ports: DEPT_PORTS,
    spots: { cabinet: (r) => r.x + r.w - 25, terminal: (r) => r.x + r.w - 25 },
  },
  {
    id: "engineering", label: "工程", roomKind: "dept", w: 110, agentKind: "agent", ports: DEPT_PORTS,
    spots: { cabinet: (r) => r.x + r.w - 25, terminal: (r) => r.x + r.w - 25 },
  },
  {
    id: "quality", label: "质检", roomKind: "dept", w: 110, agentKind: "agent", ports: DEPT_PORTS,
    spots: { cabinet: (r) => r.x + r.w - 25, terminal: (r) => r.x + r.w - 25 },
  },
  { id: "library", label: "成果库", roomKind: "shelf", w: (fl) => (fl.ops ? 82 : 136), ports: ["in"] },
  {
    id: "operations", label: "运维", roomKind: "dept", w: 88, when: "ops", agentKind: "ops", ports: ["in", "out"],
    spots: { cabinet: (r) => r.x + 17 },
    // 有故障时盯着监控屏，否则在工位上工作（快照里没有运维数据时是待机）
    rest(ctx) {
      const ops = ctx.model.ops;
      if (ops && ops.fault) return { spot: "monitor", pose: "watch_r", icon: "exclaim", facing: 1 };
      return { spot: "desk", pose: ops ? "type" : "tea" };
    },
  },
];

/** 管道声明（数据来自原型 v13 floor-decl.js 的 LINKS）。 */
export const LINKS = decl.links as unknown as LinkDef[];

/**
 * 快照对应的持续状态（原型 v13 floor-decl.js 的 deptRest）：按事项在画面上的状态给姿势。
 * 状态是画面合同的取值（翻译层已经翻好）；事项停在别的房间、这个部门同时在为它做事时也坐在桌前打字。
 */
export const deptRest: RestFn = (ctx, d, it) => {
  const seat = (pose: string, icon?: string | null, iconText?: string | null): RestState => ({
    spot: "desk", pose, icon: icon ?? null, iconText: iconText ?? null,
  });
  if (!it) return seat("tea");
  // 事项停在别的房间，这个部门同时在工作中或回答询问：坐在桌前打字
  if (it.department !== d && it.departments && it.departments[d]) return seat("type");
  const openFrom = ctx.model.open_requests.find((q) => q.from === d && q.work_item_id === it.work_item_id);
  switch (it.status) {
    case "working":
      return seat("type");
    case "asking": {
      const target = openFrom ? openFrom.to : null;
      const right = target ? ctx.order.indexOf(target) > ctx.order.indexOf(d) : false;
      return { spot: right ? "port_out" : "port_in", pose: "wait", facing: right ? 1 : -1 };
    }
    case "waiting_model": {
      const w = ctx.waitingDept(d);
      return seat("sit_wait", "hourglass", w && w.retry_text ? w.retry_text : "等待");
    }
    case "paused":
      return seat("sit_relax", "zzz");
    case "failed":
      return seat("slump");
    case "done":
      return { spot: "stand", pose: "cheer" };
    case "cancelled":
      return { spot: "stand", pose: "idle" };
    case "waiting_resume":
      return seat("sit_wait", "text", "待恢复");
    case "waiting_user":
      return seat("sit_wait", "text", "待你决定");
    case "upgrade_stopped":
      return { spot: "stand", pose: "idle" };
    default:
      return seat("sit");
  }
};

/** 部门里每个角色的持续状态（Stage 5，与部门房间画面的规则一致）。 */
export const roleRest: RoleRestFn = (ctx, d, it, role, isPrimary, roomRest) => {
  const base = roomRest(ctx, d, it);
  if (!role || role.kind === "agent" || role.kind === "ops") return base;
  if (role.status === "away") return { away: true };
  const seat = (pose: string, extra?: Partial<RestState>): RestState => ({ spot: "desk", pose, ...(extra ?? {}) });
  const st = it && it.status;
  if (st && st !== "working") {
    if (isPrimary) return base;
    if (st === "paused") return seat("sit_relax");
    if (st === "failed") return seat("slump");
    if (st === "done") return { spot: "stand", pose: "idle_happy" };
    if (st === "cancelled" || st === "upgrade_stopped") return { spot: "stand", pose: "idle" };
  }
  if (!it) return seat("tea");
  switch (role.status) {
    case "idle":
      return seat("tea");
    case "assigned":
      return seat("sit_card", { hold: "card_task" });
    case "returned":
      return seat("sit_happy");
    case "failed":
      return seat("slump");
    default:
      return seat("type");
  }
};

/** 项目楼层的任务目录（世界与系统共用）。 */
export function buildCatalog(visuals: Record<string, RoomVisual>): Catalog {
  const rooms = ROOMS.map((room) => (visuals[room.id] ? { ...room, ...visuals[room.id] } : room));
  return {
    tasks: TASKS,
    idle: IDLE,
    kinds: KINDS,
    roomDefs: rooms,
    linkDefs: LINKS,
    flags: decl.flags,
    deptRest,
    roleRest,
    geo: decl.geo,
  };
}

/** 原型 translate/say.js 的说话目录登记的事件类型（画面 3 的动作表按它核对每种动作有没有话）。 */
export const sayCatalogTypes: string[] = decl.sayCatalog;
/** 原型 translate/translate.js 的覆盖里翻成动作的事件类型（三个场景的并集）。 */
export const eventActionTypes: string[] = decl.eventActions;
export type { DeclContext };
