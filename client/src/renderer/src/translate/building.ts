// 首页的楼的翻译层（画面与播放设计说明第 6 节、原型 v13 js/translate/translate.js 的 T.building 与
// js/ui/scenes.js 的 buildingStates，工单 #955）。
//
// 这一层是唯一同时认识 Yudao 的说法与画面的说法的地方：
//   - buildingState：projects.list 加上每个项目的 project.loop（带位置）→ 画面合同的楼的状态
//     （每层的状态灯、亮灯的房间、小旗、阀门、决定计数）。服务端的状态值只经 translate/tables.ts 的对应表翻好；
//   - buildingActions：一条事件 → 零个或一个楼的动作（kind 取楼的声明表 pixel/building/building-decl.ts）。
//
// 事实只来自查询：状态由查询结果翻译，翻译层不把事件累加成事实（设计说明第 6 节）。
// 原来写在画面层里的组装（pixel/building/model.ts 的 buildingModelOf、sceneStatus、floorStatus、IN_ROOM、ACTIVE）
// 搬到这里：服务端的说法到画面的说法的对应只剩 tables.ts 一处。
//
// 哪些事件在楼上翻成动作、哪些不画，写在 translate/coverage.ts；这个文件只实现其中楼「翻成动作」的那一组。

import type { EventObject, ProjectLoopResult, ProjectRow, WorkItemLoop } from "../api/generated/types.gen.ts";
import type { BuildingFloor, BuildingModel, FlashColor, ItemState, PixelAction } from "../pixel/contract.ts";
import { buildingState as checkBuildingState } from "../pixel/contract.ts";
import { busyOf } from "./floor.ts";
import { floorSignOf, itemStateOf } from "./tables.ts";

// ---------------------------------------------------------------------------
// 状态

/** 楼里画房间的四个部门（与画面上的房间顺序一致）。 */
const DEPARTMENTS = ["product", "engineering", "quality", "operations"] as const;

/** 亮灯的状态：这个事项在某个部门做着（原型 scenes.js 的 ACTIVE：running、asking）。 */
const ACTIVE: readonly ItemState[] = ["working", "asking"];

/**
 * 会待在房间里的状态（原型 scenes.js 的 IN_ROOM）：
 * 排队与等待执行槽位的事项还在大厅，采纳的不再回房间，用户停止的事项不再待在房间里（工单 #319）。
 * held 按 #952 的结论翻成 paused，因此停在房间里（原来只有带等待回答的 held 才在房间里，
 * 与「成果已挂起」不再是单独一句话一起，是 #952 已被接受的可见变化）。
 */
const IN_ROOM: readonly ItemState[] = [
  "working", "asking", "waiting_model", "waiting_user", "waiting_resume", "interrupted", "paused", "failed", "done", "upgrade_stopped",
];

/** 项目的排列：置顶的在上，其余按最近活动时间，归档的不显示（原型 projects.list 的排序）。 */
export function sortBuildingProjects(rows: readonly ProjectRow[]): ProjectRow[] {
  return rows
    .filter((p) => !p.archived)
    .slice()
    .sort((a, b) => Number(b.pinned) - Number(a.pinned)
      || (a.last_activity_at < b.last_activity_at ? 1 : a.last_activity_at > b.last_activity_at ? -1 : 0));
}

/** 一份楼的状态的输入：projects.list 的行、每个项目的 project.loop（带位置）与位置本身。 */
export interface BuildingStateInput {
  /** 来自的查询快照的位置（projects.list 与各项目的 project.loop 里最新的一个）。 */
  position: number;
  projects: readonly ProjectRow[];
  /** 项目标识 → project.loop 的结果；还没有查到的项目不传，那一层按空闲画。 */
  loops: Readonly<Record<string, ProjectLoopResult | null | undefined>>;
  /** 底部是否留出地下室的位置（机房属于 3.2C，客户端现在不画）。 */
  show_basement?: boolean;
}

/** 一个事项在画面上的状态（服务端的状态经 tables.ts 的对应表翻好）。 */
const stateOf = (row: WorkItemLoop): ItemState => itemStateOf(row);

/** 这个部门在这个事项上正做着（部门的状态也取画面合同的取值，对应与楼层共用 translate/floor.ts 的 busyOf）。 */
function busyOn(row: WorkItemLoop, department: string): boolean {
  const raw = row.departments?.[department]?.state;
  if (!raw) return false;
  const busy = busyOf(raw);
  return busy === "working" || busy === "answering";
}

/** 一层：一个项目的缩小楼层。 */
function floorOf(project: ProjectRow, items: readonly WorkItemLoop[]): BuildingFloor {
  const lit = { product: false, engineering: false, quality: false, operations: false };
  for (const department of DEPARTMENTS) {
    // 几个部门同时工作时（回答询问、预测性探索）几个房间同时亮灯
    lit[department] = items.some((row) => ACTIVE.includes(stateOf(row))
      && (row.department === department || busyOn(row, department)));
  }
  const flags = items
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => row.department !== null && IN_ROOM.includes(stateOf(row)))
    .map(({ row, index }) => ({
      work_item_id: row.work_item_id,
      color_index: row.color_index ?? index + 1,
      department: row.department as string,
    }));
  return {
    project_id: project.project_id,
    name: project.name,
    // 每层的状态灯由这一层的事项推出来（tables.ts 的 floorSignOf，原来的 sceneStatus 与 floorStatus）
    status: floorSignOf(items),
    lit,
    // 客户端没有运维（机房与运行环境属于 3.2C）
    has_ops: false,
    flags,
    valve_closed: items.some((row) => stateOf(row) === "waiting_slot"),
    // 用着机器时通往机房的管线在流动：机房不画，管线也不画
    machine_ids: [],
    link_active: false,
    // 本层等待回答的决定请求数（名牌右上角的计数），来自 projects.list
    decisions: project.decisions_waiting,
  };
}

/**
 * projects.list 与各项目的 project.loop → 画面合同的楼的状态。
 * 翻完按画面合同校验：状态灯不在合同里时抛错，错误写明是哪一层。
 */
export function buildingState(input: BuildingStateInput): BuildingModel {
  const model: BuildingModel = {
    position: input.position,
    floors: sortBuildingProjects(input.projects).map((project) => floorOf(project, input.loops[project.project_id]?.work_items ?? [])),
    show_basement: Boolean(input.show_basement),
  };
  return checkBuildingState(model) as unknown as BuildingModel;
}

// ---------------------------------------------------------------------------
// 动作

/** 一条楼事件的形状（事件信封里画面上用到的那几个字段）。 */
export interface BuildingEvent {
  type: string;
  /** 来源事件的位置（动作的回链）；没有位置时抛错，不猜一个。 */
  position: number;
  project_id?: string | null;
  department?: string | null;
  work_item_id?: string | null;
  payload?: Record<string, unknown> | null;
}

const pl = (ev: BuildingEvent): Record<string, unknown> => ev.payload ?? {};

/** 一条事件在画面上的位置（动作的回链）；事件没有位置时抛错，不猜一个。 */
function posOf(ev: BuildingEvent): number {
  if (!Number.isFinite(ev.position)) throw new Error("翻译层收到的" + ev.type + "事件没有位置");
  return ev.position;
}

/** 楼里的动作都画在某个项目的那一层上：没有项目的事件不翻。 */
function flash(ev: BuildingEvent, color: FlashColor): PixelAction[] {
  if (!ev.project_id) return [];
  return [{ kind: "floor_flash", position: posOf(ev), project: ev.project_id, color }];
}

/** 质检的结论是放行还是缺陷记录（放行绿、返工红）。 */
const released = (ev: BuildingEvent): boolean => pl(ev).verdict === "release";

/**
 * 一种事件 → 楼的动作（原型 v13 的 BUILDING 表）。
 * 楼里每层只画状态灯、亮灯的房间、小旗与阀门，只在关键事实上闪一下；采纳时撒彩带。
 * 原型里 x_ 前缀的远程动作、部署与故障事件（机房与运维，3.2C）在真实系统的能力清单里没有，不搬。
 */
const BUILDING: Readonly<Record<string, (ev: BuildingEvent) => PixelAction[]>> = {
  // 部门开始工作：这一层闪一下白光
  department_activated: (ev) => flash(ev, "white"),
  // 询问的开始与结束：关键事实，闪一下白光
  ask_started: (ev) => flash(ev, "white"),
  ask_answered: (ev) => flash(ev, "white"),
  // 质检的结论：放行绿、缺陷记录红
  qa_submitted: (ev) => flash(ev, released(ev) ? "green" : "red"),
  // 采纳：这一层撒彩带（画面层同时闪绿光）；基线采纳只闪绿光
  deliverable_adopted: (ev) => (ev.project_id
    ? [{ kind: "celebrate", position: posOf(ev), project: ev.project_id }]
    : []),
  baseline_adopted: (ev) => flash(ev, "green"),
  // 决定请求的送出、收到与撤回：黄光
  decision_requested: (ev) => flash(ev, "yellow"),
  decision_answered: (ev) => flash(ev, "yellow"),
  project_decision_requested: (ev) => flash(ev, "yellow"),
  project_decision_answered: (ev) => flash(ev, "yellow"),
};

/** 楼翻成动作的事件种类（动作表的键；测试按它核对每种事件都有样例）。 */
export const BUILDING_EVENT_TYPES: readonly string[] = Object.keys(BUILDING).sort();

/** 一条事件 → 楼的动作；这个场景不画的事件返回空表（归属见 translate/coverage.ts）。 */
export function buildingActions(ev: BuildingEvent): PixelAction[] {
  const rule = BUILDING[ev.type];
  if (!rule) return [];
  return rule(ev).filter((action) => action.kind && Number.isFinite(action.position));
}

// ---------------------------------------------------------------------------
// 事件信封 → 楼事件的形状

/** 事件流里的事件 → 楼事件的形状（画面上用到的字段；位置原样带过来）。 */
export function toBuildingEvent(event: EventObject): BuildingEvent {
  const raw = event as unknown as Record<string, unknown>;
  const payload = raw.payload;
  return {
    type: event.type,
    position: typeof raw.position === "number" ? raw.position : Number.NaN,
    project_id: typeof event.project_id === "string" ? event.project_id : null,
    department: typeof event.department === "string" ? event.department : null,
    work_item_id: typeof event.work_item_id === "string" ? event.work_item_id : null,
    payload: payload && typeof payload === "object" ? (payload as Record<string, unknown>) : null,
  };
}

