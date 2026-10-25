// 画面合同（画面与播放设计说明第 4 节、原型 v13 js/pixel/contract.js、工单 #951）：画面层唯一认的输入。
// 翻译层照这里写的形状与取值给出状态、动作与实时内容，画面层收到别的取值就抛错。
// 这里只用画面的说法：服务端的事件种类、查询名与状态值只出现在翻译层的对照表里。
//
// 状态（setState / jump）：一个场景此刻应该画出的事实，带 position（来自的查询快照的位置）。
// 动作（play）：发生了什么，用来演，带 position（来源事件的位置）；kind 取自场景的声明表
//   （floor-decl、room-decl、building-decl），级别与时长写在声明表里，动作本身不带。
// 实时内容（决定卡片、流式文字、覆盖层）到了就显示、不进时间线，由页面直接交给场景，不在这里校验。
//
// 纯逻辑：这个文件不导入任何别的代码；播放时间线（timeline.ts）只按类型引用它。
// 机房的状态不移植（工单 #951 的范围）。

/** 事项在楼层上的状态：在大厅排队、在房间里工作或等待、结束，以及采纳。 */
export const ITEM_STATES = [
  "queued", "waiting_slot", "working", "asking", "waiting_model", "waiting_resume", "waiting_user", "paused",
  "interrupted", "failed", "done", "cancelled", "upgrade_stopped", "adopted",
] as const;
export type ItemState = (typeof ITEM_STATES)[number];

/** 一个部门同时在做什么（事项停在别的房间时这个房间也亮灯）。 */
export const BUSY_STATES = ["working", "answering", "waiting_user"] as const;
export type BusyState = (typeof BUSY_STATES)[number];

/** 楼里每一层的状态灯。 */
export const FLOOR_SIGNS = [
  "working", "queued", "waiting_slot", "waiting_model", "waiting_resume", "waiting_user", "interrupted", "idle",
] as const;
export type FloorSign = (typeof FLOOR_SIGNS)[number];

/** 部门房间的状态。 */
export const ROOM_STATES = [
  "idle", "working", "asking", "paused", "failed", "done", "cancelled", "interrupted", "waiting_resume",
] as const;
export type RoomStatus = (typeof ROOM_STATES)[number];

/** 部门里一个角色的状态。 */
export const ROLE_STATES = ["idle", "assigned", "working", "returned", "failed", "away"] as const;
export type RoleState = (typeof ROLE_STATES)[number];

/** 事实元素的来源种类（覆盖层「来源」与来源卡片）。 */
export const SOURCES = ["rule", "host_measurement", "user", "role_statement", "decision_model"] as const;
export type Source = (typeof SOURCES)[number];

/** 收敛状态（覆盖层「循环」）。原型 v13 只有取值表，没有校验入口：覆盖层的数据由翻译层写好。 */
export const LOOP_STATES = ["converging", "stalled", "oscillating", "drifting", "at_bound", "not_judged"] as const;
export type LoopState = (typeof LOOP_STATES)[number];

/** 交接的包裹。 */
export const ARTIFACTS = ["prd", "box", "defect", "release"] as const;
export type Artifact = (typeof ARTIFACTS)[number];

/** 房间里状态的姿势（roomState.pose.anim）。 */
export const POSES = ["type", "read_sit", "write", "think", "rummage", "sit_wait", "tea", "sit", "inspect"] as const;
export type Pose = (typeof POSES)[number];

/** 一份状态的最小形状：一个场景此刻应该画出的事实，带位置（来自的查询快照的位置）。 */
export interface PixelState {
  /** 来自的查询快照的位置。 */
  position: number;
  [key: string]: unknown;
}

/** 一个动作的最小形状：发生了什么，用来演，带位置（来源事件的位置）。 */
export interface PixelAction {
  /** 动作种类，取自已加载场景的声明表。 */
  kind: string;
  /** 来源事件的位置。 */
  position: number;
  /** 参与方（通常是角色）；时间线用它判断同一个参与方一次只演一件。由声明表给出。 */
  lanes?: string[];
  /** 交接的包裹：prd、box、defect、release。 */
  artifact?: Artifact;
  [key: string]: unknown;
}

/** 事实元素带来源：来源种类取 SOURCES 里的一种（没有来源时不给）。 */
export interface SourceRef {
  source?: Source | null;
  [key: string]: unknown;
}

/** 楼层上的一个事项。 */
export interface FloorItem {
  id: string;
  status: ItemState;
  /** 部门 → 这个部门在这个事项上正在做什么。 */
  departments?: Record<string, BusyState>;
  /** 这个事项的事实元素的来源。 */
  refs?: Record<string, SourceRef | null | undefined>;
  [key: string]: unknown;
}

/** 部门里的一个角色（楼层与房间都用来源 ROLE_STATES）。 */
export interface RoleEntry {
  id: string;
  status: RoleState;
  [key: string]: unknown;
}

/** 楼层的盖章（原型 v13 的 stamp）。 */
export interface Stamp {
  ref?: SourceRef | null;
  [key: string]: unknown;
}

/** 楼层（事项、部门房间的状态与原因、管道、成果库）的状态。 */
export interface FloorState extends PixelState {
  items: FloorItem[];
  /** 部门 → 角色。 */
  roles?: Record<string, RoleEntry[]>;
  stamp?: Stamp;
}

/** 楼里一层（楼的状态里的一项）。 */
export interface BuildingFloor {
  project_id: string;
  status: FloorSign;
  [key: string]: unknown;
}

/** 楼（项目与它们的楼层）的状态。 */
export interface BuildingState extends PixelState {
  floors: BuildingFloor[];
}

/** 房间里状态的姿势。 */
export interface RoomPose {
  anim: Pose;
  [key: string]: unknown;
}

/** 房间（角色、姿势、桌面物件、等待原因）的状态。 */
export interface RoomState extends PixelState {
  status: RoomStatus;
  roles?: RoleEntry[];
  pose?: RoomPose;
}

/** 一个场景的声明表：动作种类 → 级别与时长等（这里只用来核对 kind 在不在表里）。 */
export type KindTable = Readonly<Record<string, unknown>>;

const fail = (what: string, value: unknown): never => {
  throw new Error("画面合同：" + what + "：" + JSON.stringify(value));
};

type Loose = Record<string, unknown>;

/** 取值必须是 list 里的一种；否则抛错，错误写明是哪一项、什么值。 */
function oneOf<T extends string>(list: readonly T[], value: unknown, what: string): T {
  if (!list.includes(value as T)) fail(what, value);
  return value as T;
}

/** 状态与动作都带位置（回链到它依据的那一刻的事实）；没有位置就抛错。 */
function positionOf(s: unknown, what: string): number {
  const value = s ? (s as Loose).position : s;
  if (!s || !Number.isFinite(value)) fail(what + "没有位置", value);
  return value as number;
}

/** 一条事实元素的来源：给了来源就必须是 SOURCES 里的一种。 */
function ref(r: unknown, what: string): void {
  if (!r) return;
  const source = (r as Loose).source;
  if (source !== undefined && source !== null) oneOf(SOURCES, source, what + "的来源");
}

/** 一组事实元素的来源。 */
function refs(o: unknown, what: string): void {
  if (!o) return;
  Object.keys(o as Loose).forEach((k) => ref((o as Loose)[k], what + "." + k));
}

/** 楼层状态的校验（原型 v13 floorState）：事项、部门、角色、来源、盖章。 */
export function floorState(s: unknown): FloorState {
  positionOf(s, "楼层的状态");
  const state = s as Loose;
  if (!Array.isArray(state.items)) fail("楼层的状态缺少 items", state.items);
  (state.items as unknown[]).forEach((raw) => {
    const it = raw as Loose;
    oneOf(ITEM_STATES, it.status, "事项 " + String(it.id) + " 的状态");
    const departments = it.departments;
    if (departments) {
      Object.keys(departments as Loose).forEach((d) =>
        oneOf(BUSY_STATES, (departments as Loose)[d], "事项 " + String(it.id) + " 里 " + d + " 的状态"));
    }
    refs(it.refs, "事项 " + String(it.id));
  });
  const roles = state.roles;
  if (roles) {
    Object.keys(roles as Loose).forEach((d) => {
      ((roles as Loose)[d] as unknown[]).forEach((raw) => {
        const r = raw as Loose;
        oneOf(ROLE_STATES, r.status, "角色 " + String(r.id) + " 的状态");
      });
    });
  }
  const stamp = state.stamp;
  if (stamp) ref((stamp as Loose).ref, "盖章");
  return s as FloorState;
}

/** 楼的状态的校验（原型 v13 buildingState）：每层的状态灯。 */
export function buildingState(s: unknown): BuildingState {
  positionOf(s, "楼的状态");
  const state = s as Loose;
  if (!Array.isArray(state.floors)) fail("楼的状态缺少 floors", state.floors);
  (state.floors as unknown[]).forEach((raw) => {
    const f = raw as Loose;
    oneOf(FLOOR_SIGNS, f.status, "楼层 " + String(f.project_id) + " 的状态灯");
  });
  return s as BuildingState;
}

/** 房间状态的校验（原型 v13 roomState）：房间状态、角色、姿势。 */
export function roomState(s: unknown): RoomState {
  positionOf(s, "房间的状态");
  const state = s as Loose;
  oneOf(ROOM_STATES, state.status, "房间的状态");
  const roles = state.roles;
  if (roles) {
    (roles as unknown[]).forEach((raw) => {
      const r = raw as Loose;
      oneOf(ROLE_STATES, r.status, "角色 " + String(r.id) + " 的状态");
    });
  }
  const pose = state.pose;
  if (pose) oneOf(POSES, (pose as Loose).anim, "房间的姿势");
  return s as RoomState;
}

/** 动作的校验（原型 v13 action）：带位置，kind 在这个场景的声明表里，交接的包裹是四种之一。 */
export function action<T extends PixelAction>(scene: string, a: T, kinds: KindTable): T {
  positionOf(a, scene + "的动作");
  if (!kinds[a.kind]) fail(scene + "的声明表里没有这种动作", a.kind);
  if (a.artifact !== undefined) oneOf(ARTIFACTS, a.artifact, "交接的包裹");
  return a;
}
