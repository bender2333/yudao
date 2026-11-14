// 七种元件对照表与承载事实的视觉通道清单（画面与播放 docs/design/visualization.md「七种元件与对照表」「视觉通道表」「画面诚实性的不变式」，工单 #1380）。
//
// 系统的每个概念归入七种元件之一（地点、物、连接、流、规则、操作、仪表），纯装饰概念属于表演层，不进入对照表。
// 核对函数读取四份清单：
//   1. 事件种类（接口描述与能力清单）：对照表与归属清单里缺少的行列入缺口清单，单元测试照常通过；
//   2. 覆盖层（能力清单）：缺少的行列入缺口清单，单元测试照常通过；
//   3. 画面合同里的事实元素（pixel/contract.ts 的 FACT_ELEMENTS）：缺一行立即抛出错误，写明清单名与缺项；
//   4. 承载事实的视觉通道（本文件导出的 VISUAL_CHANNELS）：缺一行立即抛出错误，写明清单名与缺项。

import { FACT_ELEMENTS, type FactElement } from "../pixel/contract.ts";
import {
  COVERAGE,
  OVERLAY_LABELS,
  SCENES,
  declarationProblems,
  eventGaps,
  gapLines as formatEventGaps,
  overlayProblems,
  type EventGap,
  type Scene,
  type TranslationCoverage,
} from "./coverage.ts";

/** 画面的七种元件（画面总图第一节「七种元件」）。 */
export const ELEMENT_KINDS = ["地点", "物", "连接", "流", "规则", "操作", "仪表"] as const;
export type ElementKind = (typeof ELEMENT_KINDS)[number];

/** 两份画面自有清单的正式名称（报错提示写明清单名与缺项）。 */
export const FACT_ELEMENTS_LIST_NAME = "画面合同里的事实元素";
export const VISUAL_CHANNELS_LIST_NAME = "承载事实的视觉通道";

/** 视觉通道表里承载事实的一条通道（docs/design/visualization.md「视觉通道表」）。 */
export interface VisualChannel {
  /** 通道唯一标识（`${scene}.${name}`）。 */
  readonly id: string;
  /** 所属场景：floor、room、building。 */
  readonly scene: Scene;
  /** 该场景 `inspect().channels()` 返回对象上的顶层字段名。 */
  readonly key: string;
  /** 通道承载的事实内容说明。 */
  readonly label: string;
  /** 从 `inspect().channels()` 的返回对象读取该通道承载的事实切片。 */
  readonly read: (channels: Readonly<Record<string, unknown>>) => unknown;
}

type RoomChannelEntry = {
  readonly label: string;
  readonly lit: boolean;
  readonly screen: string;
  readonly flags: unknown[];
};

type BuildingFloorChannelEntry = {
  readonly project_id: string;
  readonly name: string;
  readonly status: string;
  readonly lit: Record<string, boolean>;
  readonly valve_closed: boolean;
  readonly decisions: number;
  readonly flags: unknown[];
};

/** 三个场景承载事实的视觉通道清单（H2 测试与对照表共用同一份导出清单）。 */
export const VISUAL_CHANNELS: readonly VisualChannel[] = Object.freeze([
  {
    id: "floor.rooms.topology",
    scene: "floor",
    key: "rooms",
    label: "楼层有哪些房间与各屋标识",
    read: (channels) => Object.keys((channels.rooms ?? {}) as Record<string, RoomChannelEntry>).sort(),
  },
  {
    id: "floor.items",
    scene: "floor",
    key: "items",
    label: "事项在哪个房间或在大厅、事项的颜色",
    read: (channels) => channels.items,
  },
  {
    id: "floor.rooms.activity",
    scene: "floor",
    key: "rooms",
    label: "房间亮灯与屏幕滚动",
    read: (channels) => {
      const rooms = (channels.rooms ?? {}) as Record<string, RoomChannelEntry>;
      return Object.fromEntries(Object.entries(rooms).map(([id, room]) => [id, { lit: room.lit, screen: room.screen }]));
    },
  },
  {
    id: "floor.rooms.door",
    scene: "floor",
    key: "rooms",
    label: "门口的小旗与牌子文字",
    read: (channels) => {
      const rooms = (channels.rooms ?? {}) as Record<string, RoomChannelEntry>;
      return Object.fromEntries(Object.entries(rooms).map(([id, room]) => [id, { label: room.label, flags: room.flags }]));
    },
  },
  {
    id: "floor.board",
    scene: "floor",
    key: "board",
    label: "大厅板上的决定单",
    read: (channels) => channels.board,
  },
  {
    id: "floor.shelf",
    scene: "floor",
    key: "shelf",
    label: "成果库里的成果",
    read: (channels) => channels.shelf,
  },
  {
    id: "floor.tubes",
    scene: "floor",
    key: "tubes",
    label: "传信管里等待回答的询问数",
    read: (channels) => channels.tubes,
  },
  {
    id: "floor.waiting",
    scene: "floor",
    key: "waiting",
    label: "等待模型服务的文字",
    read: (channels) => channels.waiting,
  },
  {
    id: "floor.roles",
    scene: "floor",
    key: "roles",
    label: "各房间的角色与角色的状态",
    read: (channels) => channels.roles,
  },
  {
    id: "floor.coverage",
    scene: "floor",
    key: "coverage",
    label: "覆盖层「检验」的覆盖比例、开环条件条数与逐条检验方式和结果",
    read: (channels) => channels.coverage,
  },
  {
    id: "room.status",
    scene: "room",
    key: "status",
    label: "房间状态与状态文字",
    read: (channels) => channels.status,
  },
  {
    id: "room.pose",
    scene: "room",
    key: "pose",
    label: "状态给出的姿势",
    read: (channels) => channels.pose,
  },
  {
    id: "room.roles",
    scene: "room",
    key: "roles",
    label: "角色与角色的状态",
    read: (channels) => channels.roles,
  },
  {
    id: "room.objects",
    scene: "room",
    key: "objects",
    label: "信箱、卷轴等物件的数量",
    read: (channels) => channels.objects,
  },
  {
    id: "room.stream",
    scene: "room",
    key: "stream",
    label: "头顶的流式文字",
    read: (channels) => channels.stream,
  },
  {
    id: "building.status",
    scene: "building",
    key: "floors",
    label: "每层的状态灯、名牌、入口阀门与决定计数",
    read: (channels) => ((channels.floors ?? []) as BuildingFloorChannelEntry[]).map((floor) => ({
      project_id: floor.project_id,
      name: floor.name,
      status: floor.status,
      valve_closed: floor.valve_closed,
      decisions: floor.decisions,
    })),
  },
  {
    id: "building.lit",
    scene: "building",
    key: "floors",
    label: "这一层有几间屋与哪几间亮灯",
    read: (channels) => ((channels.floors ?? []) as BuildingFloorChannelEntry[]).map((floor) => ({
      project_id: floor.project_id,
      lit: floor.lit,
    })),
  },
  {
    id: "building.flags",
    scene: "building",
    key: "floors",
    label: "每层门口的小旗",
    read: (channels) => ((channels.floors ?? []) as BuildingFloorChannelEntry[]).map((floor) => ({
      project_id: floor.project_id,
      flags: floor.flags,
    })),
  },
]);

/** 承载事实的视觉通道标识清单。 */
export const VISUAL_CHANNEL_IDS: readonly string[] = Object.freeze(VISUAL_CHANNELS.map((channel) => channel.id));

/** 按场景读取承载事实的视觉通道清单（供 H2 单元测试逐项核对）。 */
export function visualChannelsOf(scene: Scene, channels: readonly VisualChannel[] = VISUAL_CHANNELS): readonly VisualChannel[] {
  return channels.filter((channel) => channel.scene === scene);
}

/** 七种元件对照表的一行（docs/design/visualization.md「七种元件与对照表」）。 */
export interface MappingRow {
  /** 概念名（使用 CONTEXT.md 的领域词汇）。 */
  readonly concept: string;
  /** 所属元件：只能取 ELEMENT_KINDS 里的七种之一。 */
  readonly element: ElementKind;
  /** 来源：查询、定义或事件。 */
  readonly source: string;
  /** 状态与变化。 */
  readonly stateAndChange: string;
  /** 所在空间与场景。 */
  readonly spaceAndScene: string;
  /** 对应的操作：现有命令或回调，无操作写「无」。 */
  readonly operation: string;
  /** 仪表读数，无读数写「无」。 */
  readonly meter: string;
  /** 不画的部分与理由。 */
  readonly unpainted: string;
  /** 覆盖的画面合同事实元素。 */
  readonly factElements?: readonly FactElement[];
  /** 覆盖的承载事实视觉通道标识。 */
  readonly visualChannels?: readonly string[];
  /** 覆盖的能力清单覆盖层标识。 */
  readonly overlays?: readonly string[];
  /** 承接的动作与实时内容事件种类。 */
  readonly eventTypes?: readonly string[];
}

const row = (entry: MappingRow): MappingRow => Object.freeze({ ...entry });

/** 七种元件对照表：系统的每个概念一行，纯装饰概念不进入本表。 */
export const MAPPING_TABLE: readonly MappingRow[] = Object.freeze([
  // 地点
  row({
    concept: "楼",
    element: "地点",
    source: "查询 projects.list 与各项目的 project.loop",
    stateAndChange: "每个未归档项目占一层，陈列各层房间格、状态灯、入口阀门与决定计数；随查询快照更新",
    spaceAndScene: "空间：楼；场景：楼",
    operation: "点击楼层切换到该项目的楼层场景",
    meter: "各层的状态灯、亮灯房间格与待回答决定计数",
    unpainted: "归档项目列表与全局参数编辑留在页面",
  }),
  row({
    concept: "楼层",
    element: "地点",
    source: "查询 project.loop、decisions.list、run.asks",
    stateAndChange: "承载单个项目的大厅、各职能房间、连接管道与成果库；随查询快照位置刷新",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "点击职能房间进入房间场景，点击顶栏面包屑返回楼",
    meter: "楼层信息条上的轮次、已用时间与覆盖层按钮",
    unpainted: "项目的源目录、参数与 MCP 服务器明细留在页面",
  }),
  row({
    concept: "职能",
    element: "地点",
    source: "查询 project.loop 与 department.workspace；事件 department_activated、run_paused、run_failed、run_done、run_resumed、run_continued",
    stateAndChange: "定义里的每个职能对应一间屋；存在进行中的一轮工作或回答时房间亮灯、屏幕滚动，进入房间场景后呈现房间状态与状态文字",
    spaceAndScene: "空间：楼；场景：楼、楼层、房间",
    operation: "楼层上点击职能房间推近查看房间场景",
    meter: "房间亮灯、屏幕状态与房间 CRT 状态文字",
    unpainted: "职能 Prompt 全文与完整历史记录留在页面，画布不排长篇文字",
    visualChannels: ["floor.rooms.topology", "floor.rooms.activity", "room.status", "building.lit"],
    eventTypes: ["department_activated", "run_paused", "run_failed", "run_done", "run_resumed", "run_continued"],
  }),
  row({
    concept: "大厅",
    element: "地点",
    source: "查询 project.loop（排队与待开始事项）与 decisions.list（待回答决定请求）",
    stateAndChange: "位于楼层入口侧，停放排队或等待执行槽位的事项并悬挂决定板",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "在决定板上回答决定请求，点击事项触发点开回链",
    meter: "排队序号与等待执行槽位提示",
    unpainted: "用户输入全文与对话线程留在页面",
  }),
  row({
    concept: "成果库",
    element: "地点",
    source: "查询 project.loop 的 adoptions",
    stateAndChange: "位于楼层出口侧，按采纳顺序陈列已采纳成果的箱子",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "点击成果库箱子触发点开回链",
    meter: "已采纳成果总数与货架陈列数",
    unpainted: "交付快照的完整目录树与采纳写回分支记录留在页面",
  }),

  // 物
  row({
    concept: "事项",
    element: "物",
    source: "查询 project.loop 的 work_items；事件 user_input_received、work_item_created",
    stateAndChange: "按事项状态停在大厅或所在职能房间，带固定颜色，并在楼与楼层房门口悬挂同色小旗",
    spaceAndScene: "空间：楼；场景：楼、楼层",
    operation: "点击事项或小旗聚焦并触发点开回链",
    meter: "事项状态与房门口小旗",
    unpainted: "需求原文与逐条验收条件正文留在页面",
    visualChannels: ["floor.items", "building.flags"],
    eventTypes: ["user_input_received", "work_item_created"],
  }),
  row({
    concept: "门牌",
    element: "物",
    source: "查询 project.loop 的 work_items[].sign、refs.sign 与各职能房间的显示名",
    stateAndChange: "呈现事项简称门牌与各职能门口的牌子文字，携带事实来源位置",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "点击门牌触发点开回链，在页面查看来源事件",
    meter: "覆盖层「来源」下显示门牌的事实来源描边",
    unpainted: "事项标题变更历史与附加说明留在页面",
    factElements: ["sign"],
    visualChannels: ["floor.rooms.door"],
  }),
  row({
    concept: "包裹",
    element: "物",
    source: "查询 project.loop 的 refs.parcel；事件 proposal_submitted",
    stateAndChange: "代表 PRD、交付快照、缺陷记录或放行结论的一版正式成果，携带事实来源位置",
    spaceAndScene: "空间：楼；场景：楼层、房间",
    operation: "点击包裹触发点开回链，在页面查看该版成果与差异",
    meter: "覆盖层「来源」下显示包裹的事实来源描边",
    unpainted: "成果全文与代码差异留在页面，画布只画包裹与成果种类配色",
    factElements: ["parcel"],
    eventTypes: ["proposal_submitted"],
  }),
  row({
    concept: "章",
    element: "物",
    source: "查询 project.loop 的 stamp 与 refs.stamp；事件 qa_submitted、independent_judgement_committed",
    stateAndChange: "核验角色提交独立判断与放行结论时盖在成果及入库箱子上的印章，携带事实来源位置",
    spaceAndScene: "空间：楼；场景：楼、楼层、房间",
    operation: "点击印章触发点开回链，在页面查看核验事件与检查回执",
    meter: "覆盖层「来源」下显示章的事实来源描边",
    unpainted: "逐条独立判断文字与检查回执终端输出留在页面",
    factElements: ["stamp"],
    eventTypes: ["qa_submitted", "independent_judgement_committed"],
  }),
  row({
    concept: "成果库的箱子",
    element: "物",
    source: "查询 project.loop 的 adoptions 与 refs.box；事件 deliverable_adopted、baseline_adopted",
    stateAndChange: "成果采纳或建档基线采纳后放入成果库货架保存，携带事实来源位置",
    spaceAndScene: "空间：楼；场景：楼、楼层",
    operation: "点击箱子触发点开回链，在页面查看采纳事件",
    meter: "成果库已采纳箱子数与覆盖层「来源」描边",
    unpainted: "箱内具体文件内容与提交差异留在页面",
    factElements: ["box"],
    visualChannels: ["floor.shelf"],
    eventTypes: ["deliverable_adopted", "baseline_adopted"],
  }),
  row({
    concept: "决定请求",
    element: "物",
    source: "查询 decisions.list；事件 decision_requested、project_decision_requested",
    stateAndChange: "待用户回答的决定请求作为决定单挂在楼层大厅决定板上，回答或撤回后移除",
    spaceAndScene: "空间：楼；场景：楼、楼层、房间",
    operation: "在决定单上选择选项并填写说明，经壳发出 decision.answer 命令",
    meter: "楼与楼层上的待回答决定计数",
    unpainted: "已回答历史决定的完整列表留在页面",
    visualChannels: ["floor.board"],
    eventTypes: ["decision_requested", "project_decision_requested"],
  }),
  row({
    concept: "角色",
    element: "物",
    source: "查询 project.loop 的 roles 与 department.workspace 的 room.roles、room.pose；事件 context_assembled、compaction_recorded、compaction_failed、model_request_serialized、model_requested、model_attempt_finished、model_attempt_failed、tool_started、tool_called、tool_skipped",
    stateAndChange: "在所属职能房间内呈现各角色状态（空闲、已分派、工作中、已交回、失败、离开）及状态给出的工位姿势",
    spaceAndScene: "空间：楼；场景：楼层、房间",
    operation: "无",
    meter: "角色状态与头顶实时流式文字",
    unpainted: "走位路径、待机喝茶闲逛、眨眼与说话气泡属于表演层装饰；完整工具参数与回执留在页面工作过程",
    visualChannels: ["floor.roles", "room.roles", "room.pose"],
    eventTypes: [
      "context_assembled",
      "compaction_recorded",
      "compaction_failed",
      "model_request_serialized",
      "model_requested",
      "model_attempt_finished",
      "model_attempt_failed",
      "tool_started",
      "tool_called",
      "tool_skipped",
    ],
  }),
  row({
    concept: "卷轴与信箱",
    element: "物",
    source: "查询 department.workspace 的 mailbox、scrolls、summaries、pinned_notes、semantic_cards、pipes.letters_waiting",
    stateAndChange: "房间桌面与架子按查询数量摆放信箱信件、卷轴、轨迹节录、常驻便签与图谱卡片",
    spaceAndScene: "空间：楼；场景：房间",
    operation: "无",
    meter: "房间内各类物件的数量读数",
    unpainted: "卷轴正文、轨迹节录原文与图谱条目内容留在页面",
    visualChannels: ["room.objects"],
  }),

  // 连接
  row({
    concept: "关注管道",
    element: "连接",
    source: "事项冻结定义的关注关系与查询 project.loop",
    stateAndChange: "连接大厅入口、产出成果的职能房间、接收关注的成果的职能房间与成果库",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "无",
    meter: "覆盖层「流转」下显示管道经过次数",
    unpainted: "关注的成果的触发细则留在定义与页面",
  }),
  row({
    concept: "传信管",
    element: "连接",
    source: "事项冻结定义的询问关系与查询 run.asks",
    stateAndChange: "连接提问职能与被询问职能房间，管口按未回答询问数显示等待信件计数",
    spaceAndScene: "空间：楼；场景：楼层、房间",
    operation: "无",
    meter: "传信管口等待回答的询问封数",
    unpainted: "询问链层数参数留在定义与页面",
    visualChannels: ["floor.tubes"],
  }),
  row({
    concept: "回流管",
    element: "连接",
    source: "事项冻结定义的打回关系",
    stateAndChange: "从核验角色的房间连回被打回角色的红色回流管道",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "无",
    meter: "覆盖层「流转」下显示打回返工次数",
    unpainted: "缺陷记录条文留在页面",
  }),

  // 流
  row({
    concept: "关注的成果送达与返工",
    element: "流",
    source: "事件 spec_accepted、contract_accepted、product_decision_accepted、delivery_accepted、structure_accepted、department_guidance_received、department_guidance_applied、department_guidance_responded",
    stateAndChange: "正式成果接纳或指导到达时沿关注管道送达目标职能房间，核验打回时沿回流管返回",
    spaceAndScene: "空间：楼；场景：楼层、房间",
    operation: "无",
    meter: "覆盖层「流转」累计送达与返工次数",
    unpainted: "管道途中的飞行插值属于表演层，送达后的所在职能由状态给出",
    eventTypes: [
      "spec_accepted",
      "contract_accepted",
      "product_decision_accepted",
      "delivery_accepted",
      "structure_accepted",
      "department_guidance_received",
      "department_guidance_applied",
      "department_guidance_responded",
    ],
  }),
  row({
    concept: "询问与回答",
    element: "流",
    source: "查询 run.asks；事件 ask_started、ask_answered",
    stateAndChange: "职能发起询问时信件经传信管送往被询问职能，回答提交后沿传信管返回提问方",
    spaceAndScene: "空间：楼；场景：楼、楼层、房间",
    operation: "无",
    meter: "传信管口未回答询问封数",
    unpainted: "问题原文、询问分支内部过程与回答全文留在页面时序图",
    eventTypes: ["ask_started", "ask_answered"],
  }),
  row({
    concept: "决定请求的回答与收回",
    element: "流",
    source: "事件 decision_answered、project_decision_answered",
    stateAndChange: "用户提交回答后决定单从大厅决定板收回，解除对应阻塞",
    spaceAndScene: "空间：楼；场景：楼、楼层",
    operation: "经壳发出 decision.answer 命令",
    meter: "待回答决定计数更新",
    unpainted: "撤回的决定直接从实时卡片移除，不播飞行轨迹",
    eventTypes: ["decision_answered", "project_decision_answered"],
  }),

  // 规则
  row({
    concept: "盖章台与交出检查",
    element: "规则",
    source: "事项冻结定义的核验角色声明与控制核心裁决；事件 proposal_rejected",
    stateAndChange: "核验角色的房间内设盖章台作为独立核验裁决点；提案未通过交出检查时在裁决边界被退回",
    spaceAndScene: "空间：楼；场景：楼层、房间",
    operation: "无",
    meter: "无",
    unpainted: "交出检查细则与拒绝理由全文留在页面",
    eventTypes: ["proposal_rejected"],
  }),

  // 操作
  row({
    concept: "回答决定",
    element: "操作",
    source: "能力清单命令 decision.answer 与查询 decisions.list",
    stateAndChange: "能力清单包含 decision.answer 时决定板可操作，经壳携带连接身份与 command_id 发送命令；缺少该命令时禁用并列入缺口清单",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "现有命令 decision.answer",
    meter: "无",
    unpainted: "低频配置操作由页面或进程外运维代理完成",
  }),
  row({
    concept: "点开回链",
    element: "操作",
    source: "画面合同状态与动作携带的全局位置 position",
    stateAndChange: "点击画布事实元素或卡片链接时高亮元件并触发回调，壳在新标签页打开同源页面带位置的地址",
    spaceAndScene: "空间：楼；场景：楼、楼层、房间",
    operation: "回调 openFactLink、openTimelineLink、openPageTarget",
    meter: "无",
    unpainted: "原始事件说明、上下文摘要、代码差异与回执在打开的页面阅读，画布不画细内容",
  }),
  row({
    concept: "聚焦与跳转",
    element: "操作",
    source: "壳的场景状态（楼、楼层、房间）",
    stateAndChange: "在楼、项目楼层与职能房间之间切换场景，调用 jump 直接呈现最新快照状态",
    spaceAndScene: "空间：楼；场景：楼、楼层、房间",
    operation: "回调 goBuilding、goFloor、goRoom",
    meter: "顶栏面包屑",
    unpainted: "切换场景不补播错过的事件，离开期间的变化由页面离开期间的报告交代",
  }),

  // 仪表
  row({
    concept: "状态灯与入口阀门",
    element: "仪表",
    source: "查询 projects.list 与 project.loop",
    stateAndChange: "首页楼上每层显示项目状态灯、项目名牌、等待槽位时的入口阀门状态与待回答决定计数",
    spaceAndScene: "空间：楼；场景：楼",
    operation: "点击该层进入对应项目的楼层场景",
    meter: "八态楼层状态灯、入口阀门开闭与决定计数",
    unpainted: "项目累计模型用量与费用明细留在页面",
    visualChannels: ["building.status"],
  }),
  row({
    concept: "轮次",
    element: "仪表",
    source: "查询 project.loop 的 work_items[].round 与 refs.round",
    stateAndChange: "楼层信息条显示事项当前循环轮次，随轮次推进递增并携带事实来源位置",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "点击轮次触发点开回链",
    meter: "循环轮次读数",
    unpainted: "过往各轮的详细往来折叠在页面时序图",
    factElements: ["round"],
  }),
  row({
    concept: "已用时间",
    element: "仪表",
    source: "查询 project.loop 的 work_items[].elapsed_sec、time_limit_sec 与 refs.elapsed",
    stateAndChange: "楼层信息条显示事项已用时间与上限读数，携带事实来源位置",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "点击已用时间触发点开回链",
    meter: "已用时间与时间上限读数",
    unpainted: "分阶段耗时明细留在事件日志与页面",
    factElements: ["elapsed"],
  }),
  row({
    concept: "等待模型服务",
    element: "仪表",
    source: "查询 project.loop 的 waiting_provider；事件 model_retry_scheduled",
    stateAndChange: "职能进入等待模型服务状态时在管道口挂出提示牌与重试时间文字，服务恢复后收起",
    spaceAndScene: "空间：楼；场景：楼层、房间",
    operation: "无",
    meter: "等待模型服务的管道口提示文字",
    unpainted: "上游错误报文与连接测试记录留在页面",
    visualChannels: ["floor.waiting"],
    eventTypes: ["model_retry_scheduled"],
  }),
  row({
    concept: "实时流式输出",
    element: "仪表",
    source: "实时事件 model_stream_progress",
    stateAndChange: "角色调用模型输出期间在头顶实时刷新最近的文字片段，直达画面层，不进入播放时间线",
    spaceAndScene: "空间：楼；场景：楼层、房间",
    operation: "无",
    meter: "角色头顶实时流式文字",
    unpainted: "完整模型回复与推理全文留在页面工作过程",
    visualChannels: ["room.stream"],
    eventTypes: ["model_stream_progress"],
  }),
  row({
    concept: "覆盖层：流转",
    element: "仪表",
    source: "能力清单覆盖层 flow 与查询 project.flow",
    stateAndChange: "开启后在楼层管道上显示各职能之间的成果送达与打回次数",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "切换顶栏「流转」覆盖层按钮",
    meter: "各管道送达与返工计数",
    unpainted: "每次流转的原文与时间戳留在页面",
    overlays: ["flow"],
  }),
  row({
    concept: "覆盖层：等待",
    element: "仪表",
    source: "能力清单覆盖层 waiting 与查询 project.loop、decisions.list",
    stateAndChange: "开启后在楼层标出等待用户决定、等待回答、等待槽位与等待模型服务的位置及时长",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "切换顶栏「等待」覆盖层按钮",
    meter: "等待原因与时长标记",
    unpainted: "历史等待记录列表留在页面",
    overlays: ["waiting"],
  }),
  row({
    concept: "覆盖层：恢复",
    element: "仪表",
    source: "能力清单覆盖层 recovery 与查询 run.recovery",
    stateAndChange: "开启后在楼层标出中断恢复状态与待恢复事项位置",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "切换顶栏「恢复」覆盖层按钮",
    meter: "中断与恢复状态标记",
    unpainted: "动作核实证据与回执细节留在页面",
    overlays: ["recovery"],
  }),
  row({
    concept: "覆盖层：上下文用量",
    element: "仪表",
    source: "能力清单覆盖层 context_usage 与上下文清单统计",
    stateAndChange: "开启后在楼层各职能房间显示当前上下文已用量与工作上限刻度",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "切换顶栏「上下文用量」覆盖层按钮",
    meter: "上下文已用量与工作上限比例刻度",
    unpainted: "上下文清单各栏目的逐条内容留在页面",
    overlays: ["context_usage"],
  }),
  row({
    concept: "覆盖层：语义记录",
    element: "仪表",
    source: "能力清单覆盖层 semantic_records 与图谱统计",
    stateAndChange: "开启后在楼层显示各职能产出的证据、事实、决定与要求计数",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "切换顶栏「语义记录」覆盖层按钮",
    meter: "图谱条目计数标签",
    unpainted: "图谱全文与实体画像留在页面",
    overlays: ["semantic_records"],
  }),
  row({
    concept: "覆盖层：来源",
    element: "仪表",
    source: "能力清单覆盖层 sources 与查询 project.loop 的 refs",
    stateAndChange: "开启后按五种事实来源为楼层事实元素描边、标出缺来源元素并显示来源计数图例",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "切换顶栏「来源」覆盖层按钮，点击事实元素打开回链",
    meter: "五种事实来源计数图例与缺来源标记",
    unpainted: "原始事件全文与差异留在页面",
    overlays: ["sources"],
  }),
  row({
    concept: "覆盖层：循环",
    element: "仪表",
    source: "能力清单覆盖层 loops 与查询 run.loops",
    stateAndChange: "开启后在楼层信息条与各职能房间显示循环实例轮次、已用步数及收敛状态图例",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "切换顶栏「循环」覆盖层按钮",
    meter: "收敛中、停滞、震荡、漂移、达到边界与不判定图例",
    unpainted: "振荡信号的依据事件明细留在页面",
    overlays: ["loops"],
  }),
  row({
    concept: "覆盖层：检验",
    element: "仪表",
    source: "能力清单覆盖层 coverage 与查询 acceptance.coverage",
    stateAndChange: "开启后在楼层顶部横幅显示检验覆盖比例与开环条件条数，在核验角色房间列出每条验收条件的检验方式与结果，并在右上角显示结果与开环条件计数图例",
    spaceAndScene: "空间：楼；场景：楼层",
    operation: "切换顶栏「检验」覆盖层按钮",
    meter: "检验覆盖比例、开环条件条数及通过、不通过、未核验计数图例",
    unpainted: "逐条命令输出、试用步骤明细与判定参照材料原文留在页面",
    visualChannels: ["floor.coverage"],
    overlays: ["coverage"],
  }),
]);

/** 对照表核对函数的输入：默认读取本文件的对照表、画面合同事实元素、视觉通道与 coverage.ts 的归属清单。 */
export interface VerifyMappingInput {
  readonly rows?: readonly MappingRow[];
  readonly eventTypes?: readonly string[];
  readonly overlays?: readonly string[];
  readonly factElements?: readonly string[];
  readonly visualChannels?: readonly (string | VisualChannel)[];
  readonly coverage?: TranslationCoverage;
  readonly overlayLabels?: Readonly<Record<string, string>>;
}

/** 对照表核对结果：事件与覆盖层的缺口清单（不触发测试失败，在测试输出与壳顶栏写出）。 */
export interface MappingReport {
  readonly eventGaps: EventGap[];
  readonly overlayGaps: string[];
  readonly gapLines: string[];
}

const REQUIRED_TEXT_COLUMNS: readonly (keyof Pick<
  MappingRow,
  "concept" | "source" | "stateAndChange" | "spaceAndScene" | "operation" | "meter" | "unpainted"
>)[] = ["concept", "source", "stateAndChange", "spaceAndScene", "operation", "meter", "unpainted"];

function requireNonEmpty(rowEntry: MappingRow, field: (typeof REQUIRED_TEXT_COLUMNS)[number]): void {
  const value = rowEntry[field];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`七种元件对照表：行「${String(rowEntry.concept || "<未命名>")}」缺少必填列「${field}」`);
  }
}

/**
 * 核对七种元件对照表与四份清单：
 *   - 每行元件只属于七种元件之一，必填列非空，概念名不重复；
 *   - 画面合同事实元素与承载事实的视觉通道缺一行立即抛出错误，写明清单名与缺项；
 *   - 事件种类与覆盖层缺少的行归入缺口清单返回（口径与 view/src/shell.ts 的 gapText 一致）。
 */
export function verifyMapping(input: VerifyMappingInput = {}): MappingReport {
  const rows = input.rows ?? MAPPING_TABLE;
  const eventTypes = input.eventTypes ?? [];
  const overlays = input.overlays ?? [];
  const factElements = input.factElements ?? FACT_ELEMENTS;
  const rawVisualChannels = input.visualChannels ?? VISUAL_CHANNELS;
  const coverage = input.coverage ?? COVERAGE;
  const overlayLabels = input.overlayLabels ?? OVERLAY_LABELS;

  if (rows.length === 0) {
    throw new Error("七种元件对照表：对照表不能为空");
  }

  const concepts = new Set<string>();
  const coveredFactElements = new Set<string>();
  const coveredVisualChannels = new Set<string>();
  const coveredOverlays = new Set<string>();
  const coveredEvents = new Set<string>();

  for (const entry of rows) {
    for (const column of REQUIRED_TEXT_COLUMNS) requireNonEmpty(entry, column);
    if (!ELEMENT_KINDS.includes(entry.element)) {
      throw new Error(
        `七种元件对照表：行「${entry.concept}」的元件取值「${String(entry.element)}」不在七种元件（${ELEMENT_KINDS.join("、")}）之内；纯装饰概念不进表`,
      );
    }
    if (concepts.has(entry.concept)) {
      throw new Error(`七种元件对照表：概念「${entry.concept}」重复出现`);
    }
    concepts.add(entry.concept);

    for (const item of entry.factElements ?? []) coveredFactElements.add(item);
    for (const channel of entry.visualChannels ?? []) coveredVisualChannels.add(channel);
    for (const overlay of entry.overlays ?? []) coveredOverlays.add(overlay);
    for (const type of entry.eventTypes ?? []) coveredEvents.add(type);
  }

  // 清单 3：画面合同里的事实元素——缺一行立即失败，写明清单名与缺项
  for (const element of factElements) {
    if (!coveredFactElements.has(element)) {
      throw new Error(`清单「${FACT_ELEMENTS_LIST_NAME}」缺少对照表行：${element}`);
    }
  }

  // 清单 4：视觉通道表里承载事实的每个通道——缺一行立即失败，写明清单名与缺项
  for (const item of rawVisualChannels) {
    const channelId = typeof item === "string" ? item : item.id;
    if (!coveredVisualChannels.has(channelId)) {
      throw new Error(`清单「${VISUAL_CHANNELS_LIST_NAME}」缺少对照表行：${channelId}`);
    }
  }

  // 引用 coverage.ts 的归属清单：归属表自身不能自相矛盾，且翻成动作或转交实时内容的事件在对照表里有对应概念
  const covProblems = declarationProblems(coverage);
  if (covProblems.length > 0) {
    throw new Error(`七种元件对照表引用的事件归属清单存在问题：${covProblems.join("；")}`);
  }
  for (const scene of SCENES) {
    for (const type of [...coverage[scene].drawn, ...coverage[scene].realtime]) {
      if (!coveredEvents.has(type)) {
        throw new Error(`七种元件对照表：${scene} 场景已绘制或转交实时内容的事件 ${type} 在对照表里没有对应行`);
      }
    }
  }

  // 清单 1：事件种类——对照表与归属清单里没有行的列进缺口清单，单元测试照常通过
  const missingEvents = eventGaps(eventTypes, coverage);

  // 清单 2：覆盖层——没有对照表行或翻译层没有中文名的列进缺口清单，单元测试照常通过
  const overlayGapNames: string[] = [];
  const overlayGapLines: string[] = [];
  for (const name of new Set(overlays)) {
    const labelProblems = overlayProblems([name], overlayLabels);
    if (labelProblems.length > 0) {
      overlayGapNames.push(name);
      for (const problem of labelProblems) {
        overlayGapLines.push(`${problem}，这个覆盖层不画`);
      }
      continue;
    }
    if (!coveredOverlays.has(name)) {
      overlayGapNames.push(name);
      overlayGapLines.push(`覆盖层 ${name} 在对照表里没有行，这个覆盖层不画`);
    }
  }

  const lines = [...formatEventGaps(missingEvents), ...overlayGapLines];
  return {
    eventGaps: missingEvents,
    overlayGaps: overlayGapNames,
    gapLines: lines,
  };
}
