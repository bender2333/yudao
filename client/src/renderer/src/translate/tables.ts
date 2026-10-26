// 状态对应表（画面与播放设计说明第 6 节、原型 v13 js/translate/translate.js 开头的 table(...)，工单 #952）。
//
// 服务端状态值到画面状态值的对应只写在这里，只写一次。画面的取值来自画面合同（pixel/contract.ts）：
// 对应表里的每个服务端值都翻成合同取值表里的值，表里没有的值抛错、不原样透传，错误写明是哪张表、哪个值。
//
// 翻译层导入画面合同的类型与取值表，不导入画面层的实现（设计说明第 3 节）。
// 这里只放对应关系，不放事件：把查询结果翻成状态、把事件翻成动作由各场景的翻译模块（画面 3 至 5）做。

import {
  type FloorSign,
  type ItemState,
  type Pose,
  type RoleState,
  type RoomStatus,
} from "../pixel/contract.ts";

/**
 * 一张对应表：给一个服务端的值，给出画面的值。
 * 表里没有的值抛错，错误里写明表名与那个值（画面与播放设计说明第 4.1 节：对应只写一次，不原样透传）。
 */
export function table<T>(name: string, map: Readonly<Record<string, T>>): (value: string) => T {
  return (value: string): T => {
    if (!Object.prototype.hasOwnProperty.call(map, value)) {
      throw new Error("翻译层没有对应的" + name + "：" + value);
    }
    return map[value];
  };
}

// ---------------------------------------------------------------------------
// 事项的状态（project.loop 的 work_items[].status）→ 画面的事项状态
//
// 服务端的状态词见 harness/models.py 与 harness/projects.py：not_started（已登记、还没开始）、
// in_progress（在跑）、awaiting_initial_prd（建档结束、等待确认初始 PRD）、adopted（已采纳）、
// released_unsettled（已放行、还没有新的采纳）、stopped（用户停止）、held（上一个采纳成果被挂起）。
// 画面合同没有 held 与 released_unsettled 这两个值：held 按「暂停」画，released_unsettled 按「完成」画。

/** 事项状态：服务端的事项状态 → 画面合同的事项状态。 */
export const itemStatus = table<ItemState>("事项状态", {
  not_started: "queued",
  in_progress: "working",
  awaiting_initial_prd: "asking",
  adopted: "adopted",
  released_unsettled: "done",
  stopped: "cancelled",
  held: "paused",
});

/** 恢复观察状态里会改变画面的事项状态（工单 #900 的对应搬到这里）：中断、待恢复、暂停按它画，其余按事项状态。 */
const RECOVERY_STATUS: Readonly<Record<string, ItemState>> = {
  interrupted: "interrupted",
  waiting_resume: "waiting_resume",
  paused: "paused",
};

/** 一条事项在画面上的状态：事项还在进行时按恢复观察状态分开，其余按事项状态。 */
export function itemStateOf(row: { status: string; recovery_state?: string | null }): ItemState {
  if (row.status === "in_progress") {
    const recovery = row.recovery_state ?? null;
    if (recovery !== null && Object.prototype.hasOwnProperty.call(RECOVERY_STATUS, recovery)) {
      return RECOVERY_STATUS[recovery];
    }
  }
  return itemStatus(row.status);
}

// ---------------------------------------------------------------------------
// 楼的每层状态灯：事项的状态 → 那一层的灯
//
// 原型 v13 的 floorSign 表把项目状态标记翻成灯；客户端没有项目状态标记，
// 每层的灯由这一层未结束的事项推出来（pixel/building/model.ts 的 floorStatus，工单 #178、#734）。
// 所以这张表的输入是画面的事项状态（已经过 itemStatus 翻好），输出是画面合同的状态灯。
// 不参与灯的状态给 null：结束的、暂停的与不亮的层一个样。

const SIGN_OF_ITEM: Readonly<Record<ItemState, FloorSign | null>> = {
  queued: "queued",
  waiting_slot: "waiting_slot",
  working: "working",
  asking: "working",
  waiting_model: "waiting_model",
  waiting_resume: "waiting_resume",
  waiting_user: "waiting_user",
  paused: null,
  interrupted: "interrupted",
  failed: null,
  done: null,
  cancelled: null,
  upgrade_stopped: null,
  adopted: null,
};

/** 事项状态 → 状态灯；这一种事项不决定灯时为 null。 */
export const floorSign = table<FloorSign | null>("楼层状态灯", SIGN_OF_ITEM);

/** 状态灯的优先顺序：同时有几个事项时按这个顺序取第一个（与工单 #734 的口径一致）。 */
export const FLOOR_SIGN_ORDER: readonly ItemState[] = [
  "waiting_resume",
  "interrupted",
  "waiting_user",
  "waiting_model",
  "waiting_slot",
  "working",
  "queued",
];

/** 一层的状态灯：这一层的事项按优先顺序取第一个能决定灯的状态，都不决定时为空闲。 */
export function floorSignOf(items: readonly { status: string; recovery_state?: string | null }[]): FloorSign {
  const states = items.map(itemStateOf);
  for (const state of FLOOR_SIGN_ORDER) {
    if (states.includes(state)) {
      const sign = floorSign(state);
      if (sign !== null) return sign;
    }
  }
  return "idle";
}

// ---------------------------------------------------------------------------
// 部门房间的状态（department.workspace 的 room.status）→ 画面的房间状态
//
// 服务端只会给出这几个值（harness/app/project_queries.py 的 _room_status 与 ROOM_STATUS_TEXT），
// 画面合同的房间状态与它们一一对应。

/** 房间状态：服务端的房间状态 → 画面合同的房间状态。 */
export const roomStatus = table<RoomStatus>("房间状态", {
  idle: "idle",
  working: "working",
  asking: "asking",
  paused: "paused",
  failed: "failed",
  done: "done",
  cancelled: "cancelled",
  interrupted: "interrupted",
  waiting_resume: "waiting_resume",
});

// ---------------------------------------------------------------------------
// 房间里的姿势（department.workspace 的 room.pose.action）→ 画面的姿势
//
// 照原型 v13 的 roomPose 表；服务端现在只给出 typing，其余几种是表里为后续动作预留的名字
// （原型 v11 的动作图鉴里各有一处演出）。表里没有的动作抛错。

/** 房间姿势：服务端的姿势名 → 画面合同的姿势。 */
export const roomPose = table<Pose>("房间姿势", {
  typing: "type",
  reading: "read_sit",
  writing: "write",
  thinking: "think",
  searching: "rummage",
  waiting: "sit_wait",
  tea: "tea",
  idle: "sit",
  inspecting: "inspect",
});

// ---------------------------------------------------------------------------
// 角色的状态 → 画面的角色状态
//
// 服务端现在给出 idle 与 working（harness/app/project_queries.py 的 role_status），
// 其余几个是原型 v13 的 roleStatus 表里已有的名字。

/** 角色状态：服务端的角色状态 → 画面合同的角色状态。 */
export const roleStatus = table<RoleState>("角色状态", {
  idle: "idle",
  assigned: "assigned",
  working: "working",
  returned: "returned",
  failed: "failed",
  away: "away",
});
