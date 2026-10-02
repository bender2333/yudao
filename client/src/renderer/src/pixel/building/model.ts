// 首页的楼的数据组装（原型 v9 scenes.js 的 buildingModels，工单 #178 验收标准 3、4）。
//
// 数据来自 projects.list（项目行）与每个项目的 project.loop（事项）；组装是纯函数，
// 与查询结果的形状解耦，可以在 node --test 下核对，也供首页与端到端测试共用。
//
// 排列：置顶的项目在上，其余按最近活动时间排列，归档的项目不显示（原型 projects.list 的排序）。

import type { BuildingFloor, BuildingModel } from "../world/building.ts";

/** 组装用的项目行：projects.list 里与建楼有关的字段。 */
export interface BuildingProjectRow {
  project_id: string;
  name: string;
  pinned: boolean;
  archived: boolean;
  last_activity_at: string;
  decisions_waiting: number;
}

/** 组装用的事项行：project.loop 的 work_items 里与建楼有关的字段。 */
export interface BuildingItemRow {
  work_item_id: string;
  status: string;
  department: string | null;
  color_index: number;
  recovery_state: string | null;
  /** 停在某个问题上等待回答时为真（原型 sceneStatus 的 asking）。 */
  pending_question?: string | null;
}

const DEPARTMENTS = ["product", "engineering", "quality", "operations"] as const;
/** 会待在房间里的状态（原型 scenes.js 的 IN_ROOM）。 */
const IN_ROOM = ["running", "asking", "waiting_provider", "paused", "failed", "done", "cancelled", "interrupted", "pending_verification", "waiting_resume", "waiting_decision", "stopped_for_upgrade"];
/** 亮灯对应的活跃状态（原型 scenes.js 的 ROOM_STATUS）。 */
const ACTIVE = ["running", "asking", "pending_verification"];

/** 按「置顶在上，其余按最近活动，归档不显示」排列项目（原型 projects.list 的排序）。 */
export function sortBuildingProjects(rows: BuildingProjectRow[]): BuildingProjectRow[] {
  return rows
    .filter((p) => !p.archived)
    .slice()
    .sort((a, b) => Number(b.pinned) - Number(a.pinned) || (a.last_activity_at < b.last_activity_at ? 1 : a.last_activity_at > b.last_activity_at ? -1 : 0));
}

/** 一条事项在画面上的状态：与原型 sceneStatus 的口径一致（按客户端的状态词与恢复观察状态映射）。 */
export function sceneStatus(item: BuildingItemRow): string | null {
  if (item.recovery_state === "interrupted" || item.recovery_state === "pending_verification" || item.recovery_state === "waiting_resume") {
    return item.recovery_state;
  }
  switch (item.status) {
    case "in_progress":
      return item.pending_question ? "asking" : "running";
    // 等待用户决定的事项停在最后所在的房间等待；只有 held 才可能是等待决定，普通排队在大厅
    case "held":
      return item.pending_question ? "waiting_decision" : "waiting_slot";
    case "not_started":
      return "queued";
    case "stopped":
      return "interrupted";
    case "adopted":
    case "released_unsettled":
      return "done";
    default:
      return null;
  }
}

/** 楼层的状态灯：按原型 markerOf 的优先级取第一个命中（等待恢复、待核实、中断、等待你的决定、等待模型服务、等待执行槽位、运行中、排队中，否则空闲）。 */
export function floorStatus(items: BuildingItemRow[]): string {
  const statuses = items.map((it) => sceneStatus(it));
  const has = (s: string): boolean => statuses.includes(s);
  if (has("waiting_resume")) return "waiting_resume";
  if (has("pending_verification")) return "pending_verification";
  if (has("interrupted")) return "interrupted";
  if (has("waiting_decision")) return "waiting_decision";
  if (has("waiting_provider")) return "waiting_provider";
  if (has("waiting_slot")) return "waiting_slot";
  if (has("running") || has("asking")) return "running";
  if (has("queued")) return "queued";
  return "idle";
}

/** 把一行项目与它的事项组装成一层（原型 scenes.js 的 buildingModels 的每层计算）。 */
export function buildingFloorOf(project: BuildingProjectRow, items: BuildingItemRow[]): BuildingFloor {
  const lit = { product: false, engineering: false, quality: false, operations: false };
  for (const d of DEPARTMENTS) {
    lit[d] = items.some((it) => it.department === d && ACTIVE.includes(sceneStatus(it) ?? ""));
  }
  return {
    project_id: project.project_id,
    name: project.name,
    status: floorStatus(items),
    lit,
    has_ops: false,
    flags: items
      .filter((it) => it.department !== null && IN_ROOM.includes(sceneStatus(it) ?? ""))
      .map((it) => ({ work_item_id: it.work_item_id, color_index: it.color_index, department: it.department! })),
    valve_closed: items.some((it) => sceneStatus(it) === "waiting_slot"),
    machine_ids: [],
    link_active: false,
    decisions: project.decisions_waiting,
  };
}

/** 组装整栋楼：每行项目一层，按排列顺序排列；底部留出地下室的位置。 */
export function buildingModelOf(projects: BuildingProjectRow[], itemsOf: (projectId: string) => BuildingItemRow[], showBasement: boolean): BuildingModel {
  return {
    floors: sortBuildingProjects(projects).map((p) => buildingFloorOf(p, itemsOf(p.project_id))),
    show_basement: showBasement,
  };
}
