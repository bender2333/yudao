// 楼层的翻译层（画面与播放设计说明第 6 节、原型 v13 js/translate/translate.js 的楼层部分，工单 #953）。
//
// 这一层是唯一同时认识 Yudao 的说法与画面的说法的地方：
//   - floorState：project.loop（带位置）加上各部门的角色与运行的询问链 → 画面合同的楼层状态
//     （事项、部门在事项上的状态、未回答的询问、角色、成果库），状态值经 translate/tables.ts 的对应表翻好
//     （服务端 in_progress → 画面的 working）；
//   - floorActions：一条事件（带位置）→ 零个、一个或几个楼层的动作（kind 取画面合同的楼层声明表，
//     client/src/renderer/src/pixel/generated/floor-decl.json 的 kinds）；
//   - floorCards：决定请求 → 大厅板上贴着的卡片，卡片上的文字在这里写好；
//   - streamText：输出片段 → 流式文字（实时内容，不进播放时间线）。
//
// 事实只来自查询：状态由查询结果翻译，翻译层不把事件累加成事实（设计说明第 6 节）。
// 说话的话术用 translate/say.ts（画面 2 的成果）。

import type {
  AskView, DecisionView, EventObject, LoopActivation, LoopAmount, LoopLayer, ProjectLoopResult, RunLoopsResult,
  WorkItemLoop,
} from "../api/generated/types.gen.ts";
import type {
  Artifact, BusyState, DecisionFace, FactElement, FloorModel, ItemState, LoopItem, LoopsOverlayData, MachineView,
  OpenRequest, OpsView, PixelAction, RoleInfo, Source, SourceCardFace, SourceOverlayData, SourceRef, WaitingProvider,
} from "../pixel/contract.ts";
import { floorState as checkFloorState, SOURCES } from "../pixel/contract.ts";
import { face } from "../views/decisions/card-logic.ts";
import { DEPARTMENTS, departmentName, label, STOP_REASON } from "../views/project/labels.ts";
import { cut, say, sayAnswer, sayAsk, sayHandoff } from "./say.ts";
import { itemStateOf, roleStatus } from "./tables.ts";

// ---------------------------------------------------------------------------
// 状态

/** 一个部门在事项上的状态（服务端的 DepartmentState.state）→ 画面合同的部门状态。 */
const DEPT_BUSY: Readonly<Record<string, BusyState>> = {
  working: "working",
  // 这个部门停在自己发出、还没有回答的询问上：部门本身没有停手，事项在画面上是询问中
  // （原型 v13 core.js 的 deptStatesOf 把提问方写成 working，等待写在原因里；画面合同的部门状态没有「询问中」）
  asking: "working",
  // 在等下游核验交付：手上还有这一轮的事
  verifying: "working",
  waiting_user: "waiting_user",
  // waiting：这个部门此刻没有在做这件事，不写进事项的部门状态
};

/** 部门在事项上的状态；空闲（waiting）与表里没有的值不给。 */
export function busyOf(state: string): BusyState | null {
  return DEPT_BUSY[state] ?? null;
}

/** 一份楼层状态的输入：查询结果（带位置）与页面已经查好的其余材料。 */
export interface FloorStateInput {
  /** 来自的查询快照的位置。 */
  position: number;
  loop: ProjectLoopResult | null;
  /**
   * 运行标识 → 这个运行的询问链（查询 run.asks；没有查时不传）。
   * 只有未回答的询问进楼层状态：信件停在被询问部门的传信管出口，传信管按它有没有信判断流动。
   * run.asks 不带位置，回放（画在过去的位置上）不传它。
   */
  asks?: Readonly<Record<string, readonly AskView[] | null>> | null;
  /** 部门 → 角色（department.workspace 的 room.roles；没有查时不传）。 */
  roles?: Record<string, { id: string; name: string; kind: string; status: string }[]> | null;
  /** 聚焦的事项。 */
  focus?: string | null;
  slots?: { total: number; used: number } | null;
  ops?: OpsView | null;
  machines?: MachineView[] | null;
  waiting_provider?: WaitingProvider[] | null;
  interrupted?: boolean;
}

/**
 * 事项在画面上的状态：所在部门停在自己发出的询问上时是询问中（原型 v13 core.js 的 sceneStatus）。
 * 服务端把这件事记在部门状态上（DepartmentState 的 asking），画面合同记在事项的状态上。
 */
function itemState(row: WorkItemLoop): ItemState {
  const base = itemStateOf(row);
  const own = row.department ? row.departments?.[row.department]?.state : null;
  return base === "working" && own === "asking" ? "asking" : base;
}

/**
 * 楼层事实元素的中文名（工单 #398）：来源卡片与覆盖层「来源」按它显示。页面不出现内部标识，
 * 六个元素与 project.loop 的 refs 的键一一对应（工单 #396）。
 */
export const FACT_LABELS: Readonly<Record<string, string>> = {
  sign: "门牌",
  round: "轮次",
  elapsed: "已用时间",
  parcel: "包裹",
  stamp: "盖章",
  box: "成果库的箱子",
};

/**
 * 事项的事实元素与它们的来源（工单 #396 的 project.loop refs → 画面合同，工单 #398）：
 * 每个元素给出它的事件位置与来源种类。没有来源的元素不出现在结果里，画面按缺来源处理
 * （pixel/floor/render.ts 的 noSource），覆盖层「来源」据此标出。
 */
export function factRefs(row: WorkItemLoop): Record<string, SourceRef> {
  const refs: Record<string, SourceRef> = {};
  for (const key of Object.keys(FACT_LABELS)) {
    const ref = row.refs?.[key];
    if (ref) refs[key] = { position: ref.position, source: ref.source };
  }
  return refs;
}

function itemOf(row: WorkItemLoop, index: number): LoopItem {
  const departments: Record<string, BusyState> = {};
  for (const [dept, state] of Object.entries(row.departments ?? {})) {
    const busy = busyOf(state.state);
    if (busy) departments[dept] = busy;
  }
  const status = itemState(row);
  const refs = factRefs(row);
  return {
    id: row.work_item_id,
    work_item_id: row.work_item_id,
    title: row.sign,
    status,
    kind: row.kind,
    sign: row.sign,
    color_index: row.color_index ?? index + 1,
    // 因升级停止的事项没有当前部门（project.loop 的 department 为空）：门口牌子立在最后工作的那个部门
    // （工单 #1186，设计说明第 4.3 节 2026-10-29 补充）
    department: row.department ?? (status === "upgrade_stopped" ? row.last_department : null),
    round: row.round,
    started_at: row.started_at,
    elapsed_sec: row.elapsed_sec,
    time_limit_sec: row.time_limit_sec,
    queue_pos: undefined,
    waiting_provider_sec: undefined,
    ...(Object.keys(departments).length ? { departments } : {}),
    // 事实元素与它们的来源（工单 #398）：来源卡片与覆盖层「来源」读它；没有来源的元素不在这里
    ...(Object.keys(refs).length ? { refs } : {}),
  };
}

// ---------------------------------------------------------------------------
// 事实来源（工单 #396 的数据、工单 #398 的画面）：来源种类与事件种类的中文名、覆盖层「来源」的数据与来源卡片

/** 五种来源的中文名：覆盖层「来源」的图例与来源卡片按它显示。 */
export const SOURCE_LABELS: Readonly<Record<Source, string>> = {
  rule: "确定规则",
  host_measurement: "主机测量",
  user: "用户",
  role_statement: "角色陈述",
  decision_model: "决策模型",
};

/**
 * 画面上有对应物的事实元素（门牌、包裹、成果库的箱子、信息条上的轮次与已用时间）。
 * 盖章随质检的放行到来，画面上还没有对应物，所以覆盖层不为它标位置，只让它出现在数据里。
 */
export const DRAWN_FACT_ELEMENTS: readonly FactElement[] = ["sign", "parcel", "box", "round", "elapsed"];

/**
 * 事件种类的中文名：来源卡片写「事件种类」一行，页面不出现英文内部标识。
 * 覆盖 client/tests/fixtures/event-types.json 里的每一种事件，缺一行由单元测试报出（工单 #398）。
 */
export const EVENT_KIND_LABELS: Readonly<Record<string, string>> = {
  action_verified: "动作核实",
  activation_finished: "激活结束",
  adoption_held: "暂缓采纳",
  artifact_accepted: "成果被采纳",
  artifact_invalidated: "成果失效",
  ask_answered: "询问有回答",
  ask_started: "发出询问",
  baseline_adopted: "建档基线被采纳",
  baseline_review_accepted: "基线核验被采纳",
  catalog_candidates_collected: "模型候选已收集",
  catalog_revised: "模型目录修订",
  catalog_test_finished: "模型测试结束",
  compaction_recorded: "上下文压缩",
  context_assembled: "装配上下文",
  contract_accepted: "有效合同被采纳",
  credential_changed: "凭据变化",
  decision_answered: "决定有回答",
  decision_requested: "提出决定",
  decision_withdrawn: "撤回决定",
  deliverable_adopted: "交付物被采纳",
  delivery_accepted: "交付被采纳",
  department_activated: "部门开始一轮工作",
  department_guidance_applied: "定向指导被采用",
  department_guidance_received: "收到定向指导",
  department_guidance_responded: "回答定向指导",
  department_input: "把材料交给部门",
  department_prompt_configured: "部门 Prompt 已配置",
  home_seen: "记下查看位置",
  initial_prd_proposed: "初始 PRD 等待确认",
  instance_upgrade_answered: "实例升级有回答",
  instance_upgrade_requested: "请求实例升级",
  instance_upgrade_withdrawn: "撤回实例升级",
  lesson_candidate_recorded: "记下经验候选",
  material_recorded: "登记材料",
  mcp_servers_configured: "MCP 服务器设置已保存",
  model_attempt_failed: "模型调用失败",
  model_attempt_finished: "模型调用完成",
  model_message: "模型回复",
  model_reasoning: "模型思考",
  model_request_serialized: "记录模型请求",
  model_requested: "向模型发出请求",
  model_retry_scheduled: "安排模型重试",
  model_stream_progress: "模型流式输出",
  onboarding_revision_started: "开始新一轮建档",
  parameter_set: "修改参数",
  product_decision_accepted: "产品决策被采纳",
  product_input_assigned: "用户输入分派给产品",
  project_archived: "项目被归档",
  project_decision_answered: "项目决定有回答",
  project_decision_requested: "请求用户决定",
  project_decision_withdrawn: "撤回项目决定",
  project_goal_changed: "修改项目长期目标",
  project_parameter_set: "修改项目参数",
  project_pinned: "固定项目",
  project_registered: "建立项目",
  project_renamed: "项目改名",
  project_restored: "恢复项目",
  proposal_rejected: "提案被拒绝",
  proposal_submitted: "提交提案",
  qa_submitted: "质检提交结论",
  qa_tests_saved: "保存质检测试材料",
  run_continued: "运行继续",
  run_created: "建立事项",
  run_done: "运行结束",
  run_failed: "运行失败",
  run_paused: "运行暂停",
  run_resumed: "运行自动继续",
  runtime_drain_finished: "排空结束",
  runtime_drain_started: "开始排空",
  runtime_force_upgrade_requested: "请求强制升级",
  source_directory_configured: "登记源目录",
  spec_accepted: "产品规格被采纳",
  spec_superseded: "产品规格被取代",
  structure_accepted: "结构说明被采纳",
  tool_call_required: "主机提示调用工具",
  tool_called: "工具执行完成",
  tool_server_probe_finished: "读取 MCP 服务器工具清单",
  tool_skipped: "跳过工具",
  tool_started: "开始执行工具",
  user_input_received: "收到用户输入",
  work_item_created: "建立事项",
  work_item_start_failed: "事项未能开始",
  writeback_completed: "写回完成",
  writeback_held: "写回等待前项",
  writeback_not_needed: "无需写回",
  writeback_stopped: "写回停止",
  writeback_verified: "写回已核实",
};

/** 一种事件的中文种类名；没有登记时为空（卡片不显示英文的内部标识，改为不写这一行）。 */
export function eventKindLabel(type: string | null | undefined): string | null {
  if (!type) return null;
  return EVENT_KIND_LABELS[type] ?? null;
}

/** 一条事件的提出者写成页面的说法：部门名、你、系统。 */
export function actorLabel(actor: string | null | undefined): string | null {
  if (!actor) return null;
  const [kind, value] = actor.split(":", 2);
  if (kind === "department") return `${DEPARTMENTS[value]?.name ?? value}部门`;
  if (kind === "user") return "你";
  if (kind === "system") return "系统";
  if (kind === "model") return "模型";
  return null;
}

/**
 * 覆盖层「来源」的数据（工单 #398）：每个事项的每个画出来的事实元素一行，写来源种类与来源事件的位置；
 * `project.loop` 给了 refs、这个元素却没有的算缺来源（画面按 noSource 标出）。
 * 图例数五种来源各在画面上有几个事实元素（缺来源的不计）。
 */
export function sourceOverlay(loop: ProjectLoopResult | null): SourceOverlayData {
  const entries: SourceOverlayData["entries"] = [];
  const missing: SourceOverlayData["missing"] = [];
  for (const row of loop?.work_items ?? []) {
    const refs = row.refs ?? {};
    for (const element of DRAWN_FACT_ELEMENTS) {
      const label = FACT_LABELS[element];
      const ref = refs[element];
      if (ref) {
        entries.push({ work_item_id: row.work_item_id, element, label, source: ref.source, position: ref.position });
      } else if (Object.keys(refs).length > 0) {
        // refs 在、这个元素不在：这个元素缺来源（没有 refs 的旧数据照常画，不算缺来源，见 render.ts 的 noSource）
        missing.push({ work_item_id: row.work_item_id, element, label });
      }
    }
  }
  const legend: SourceOverlayData["legend"] = SOURCES.map((source) => ({
    source,
    label: SOURCE_LABELS[source],
    count: entries.filter((entry) => entry.source === source).length,
  }));
  return { entries, missing, legend };
}

/** 来源卡片要读的原始事件：`event.detail` 或事件流给出的事件对象里用到的那几个字段。 */
export interface SourceEvent {
  type?: string | null;
  label?: string | null;
  at?: string | null;
  actor?: string | null;
  position?: number | null;
  payload?: Record<string, unknown> | null;
}

/**
 * 来源卡片的内容（工单 #398，原型 v10 设计说明第 5.1 节）：事实元素、来源种类、原始事件（说明、种类、
 * 时间、提出者与位置）与一段上下文摘要。原始事件取不到时写明原因，卡片仍指向它在时间轴上的位置。
 */
export function sourceCard(
  row: WorkItemLoop,
  element: FactElement,
  ref: { position: number; source: Source },
  event: SourceEvent | null,
): SourceCardFace {
  const payload = event?.payload ?? null;
  return {
    work_item_id: row.work_item_id,
    element,
    element_label: FACT_LABELS[element],
    source: ref.source,
    source_label: SOURCE_LABELS[ref.source],
    position: ref.position,
    event_label: event?.label ?? null,
    kind_label: eventKindLabel(event?.type),
    at: event?.at ?? null,
    actor_label: actorLabel(event?.actor),
    detail: detailRows(row, payload),
    note: event === null
      ? `原始事件的说明没有取到；在时间轴上回到第 ${ref.position} 位，可以看到它影响的那一刻`
      : null,
  };
}

/** 上下文摘要：事项本身的两项事实与原始事件载荷里能当成文字读的几项。 */
function detailRows(row: WorkItemLoop, payload: Record<string, unknown> | null): { term: string; value: string }[] {
  const rows: { term: string; value: string }[] = [
    { term: "事项", value: row.sign },
    { term: "轮次", value: `第 ${row.round} 轮` },
  ];
  const text = (value: unknown): string | null =>
    (typeof value === "string" && value.trim() !== "" ? value.trim() : null);
  const summary = text(payload?.summary);
  if (summary) rows.push({ term: "摘要", value: summary });
  const description = text(payload?.description);
  if (description) rows.push({ term: "说明", value: description });
  const question = text(payload?.question);
  if (question) rows.push({ term: "问题", value: question });
  const path = text(payload?.path);
  if (path) rows.push({ term: "文件", value: path });
  return rows;
}

/** 未回答的询问：信件停在被询问部门的传信管出口（原型 v13 core.js 的 openRequests）。 */
export function openRequestsOf(
  loop: ProjectLoopResult | null,
  asks: FloorStateInput["asks"],
): OpenRequest[] {
  const out: OpenRequest[] = [];
  for (const row of loop?.work_items ?? []) {
    const chain = asks?.[row.run_id] ?? [];
    for (const ask of chain) {
      // 已回答与没能回答都算这次询问结束了，提问方不再在管口等待
      if (ask.status !== "进行中") continue;
      out.push({ from: ask.requester, to: ask.recipient, work_item_id: row.work_item_id });
    }
  }
  return out;
}

function rolesOf(input: FloorStateInput): Record<string, RoleInfo[]> | null {
  if (!input.roles) return null;
  const out: Record<string, RoleInfo[]> = {};
  for (const [department, list] of Object.entries(input.roles)) {
    if (!list.length) continue;
    out[department] = list.map((r) => ({ id: r.id, name: r.name, kind: r.kind, status: roleStatus(r.status), task: null }));
  }
  return Object.keys(out).length ? out : null;
}

/**
 * 查询结果 → 画面合同的楼层状态。服务端的说法只在这里换成画面的说法（状态经 tables.ts 的对应表）。
 * 翻完按画面合同校验：取值不在合同里时抛错，错误写明是哪一项。
 */
export function floorState(input: FloorStateInput): FloorModel {
  const loop = input.loop;
  const model: FloorModel = {
    position: input.position,
    items: (loop?.work_items ?? []).map(itemOf),
    open_requests: openRequestsOf(loop, input.asks),
    shelves: { adopted: (loop?.adoptions ?? []).map((a) => a.work_item_id) },
    slots: input.slots ?? null,
    waiting_provider: input.waiting_provider ?? [],
    machines: input.machines ?? null,
    ops: input.ops ?? null,
    interrupted: Boolean(input.interrupted),
    roles: rolesOf(input),
    decisions: [],
    ...(input.focus ? { focus_id: input.focus } : {}),
  };
  return checkFloorState(model) as unknown as FloorModel;
}

// ---------------------------------------------------------------------------
// 覆盖层

/** 「恢复」覆盖层里两种状态的文字（原型 v13 js/translate/translate.js 的 RECOVERY_TEXT）。 */
const RECOVERY_OVERLAY_TEXT: Readonly<Record<"interrupted" | "waiting_resume", string>> = {
  interrupted: "中断",
  waiting_resume: "待恢复",
};

/**
 * 整层「中断」的取值（工单 #1188，设计说明第 4.3 节 2026-10-29 补充）：事件流断开，或者任一事项的
 * 恢复观察状态是 interrupted。整层变暗、时钟停住，不是弹窗也不是空白；画面本身照旧画着最后一份状态。
 * 服务进程被强行结束时读不到 interrupted（未结束的激活在 finally 才结束），所以以事件流断开为准；
 * 服务回来、页面重新连接并看到自动继续以后恢复。
 * 待恢复（waiting_resume）不使整层变暗：那是等用户处理，画面照常显示。
 */
export function floorInterrupted(loop: ProjectLoopResult | null, streamDisconnected: boolean): boolean {
  if (streamDisconnected) {
    return true;
  }
  return (loop?.work_items ?? []).some((row) => row.recovery_state === "interrupted");
}

/**
 * 「恢复」覆盖层的数据（工单 #1186，原型 v13 js/translate/translate.js 的 floorOverlay 恢复一项）：
 * 中断与待恢复的事项各在自己所在的部门挂一块牌子，牌子写状态与事项标题。
 * 数据在这里由查询结果写好，画面层只照着画；事项的范围与画面合同的状态同 itemStateOf 的对应。
 */
export function recoveryOverlay(loop: ProjectLoopResult | null): {
  entries: { department: string; text: string; state: ItemState }[];
} {
  const entries: { department: string; text: string; state: ItemState }[] = [];
  for (const row of loop?.work_items ?? []) {
    const state = itemStateOf(row);
    if ((state !== "interrupted" && state !== "waiting_resume") || !row.department) continue;
    entries.push({ department: row.department, text: `${RECOVERY_OVERLAY_TEXT[state]}：${row.sign}`, state });
  }
  return { entries };
}

// ---------------------------------------------------------------------------
// 动作

/** 一条楼层事件的形状（事件信封里画面上用到的那几个字段）。 */
export interface FloorEvent {
  type: string;
  /** 来源事件的位置（动作的回链）。 */
  position: number;
  event_id?: string | null;
  project_id?: string | null;
  department?: string | null;
  role?: string | null;
  tool?: string | null;
  label?: string | null;
  work_item_id?: string | null;
  payload?: Record<string, unknown> | null;
}

/** 翻动作时的上下文：角色名称（「把任务交给主程」这类话要用）。 */
export interface ActionContext {
  roleName?: (role: string | null) => string | null;
}

type Payload = Record<string, unknown>;

const pl = (ev: FloorEvent): Payload => ev.payload ?? {};
const text = (value: unknown): string => (value === undefined || value === null ? "" : String(value));
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

/** 一条事件在画面上的位置（动作的回链）；事件没有位置时抛错，不猜一个。 */
function posOf(ev: FloorEvent): number {
  if (!Number.isFinite(ev.position)) throw new Error("翻译层收到的" + ev.type + "事件没有位置");
  return ev.position;
}

/** 一个部门里的一个角色做的事。 */
function one(kind: string, ev: FloorEvent, ctx: ActionContext, extra?: Record<string, unknown> | null): PixelAction {
  return {
    kind,
    position: posOf(ev),
    item: ev.work_item_id ?? null,
    room: ev.department ?? null,
    role: ev.role ?? null,
    say: say(ev, { roleName: ctx.roleName }),
    ...(extra ?? {}),
  };
}

/** 一份成果从一个部门送到另一个部门：包裹沿管道走，两端的经理各说一句话。 */
function handoff(ev: FloorEvent, from: string, to: string, artifact: Artifact): PixelAction {
  const spoken = sayHandoff(artifact, from, to);
  return {
    kind: "handoff",
    position: posOf(ev),
    item: ev.work_item_id ?? null,
    from,
    to,
    artifact,
    say: spoken.say,
    sayTo: spoken.sayTo,
  };
}

/** 只发生在画面上的一件事（投信、房间亮一下、决定单、包裹、成果库）。 */
function at(kind: string, ev: FloorEvent, extra?: Record<string, unknown> | null): PixelAction {
  return { kind, position: posOf(ev), item: ev.work_item_id ?? null, room: ev.department ?? null, ...(extra ?? {}) };
}

/** 楼层上按工具名称落在哪件事上（原型 v13 translate.js 的 floorTool）。 */
export function floorTool(ev: FloorEvent): string {
  const tool = text(ev.tool ?? pl(ev).tool);
  if (tool === "search") return "search";
  if (tool === "run_command" || tool === "bash") return "command";
  if (tool === "run_check") return "inspect";
  if (/write|edit/.test(tool)) return "write";
  if (/fetch|http|net|url/.test(tool)) return "fetch";
  if (/mcp/.test(tool)) return "tool";
  if (/browser|computer/.test(tool)) return ev.department === "quality" ? "browse" : "self_test";
  if (/scan|legacy|repo/.test(tool)) return "scan";
  return "read";
}

/** 重试的次数（第 n/m 次）：事件载荷里带的时候写在头顶。 */
function countOf(ev: FloorEvent): string | null {
  const p = pl(ev);
  const n = num(p.n) ?? num(p.attempt) ?? num(p.attempt_no);
  const of = num(p.of) ?? num(p.max) ?? num(p.max_attempts);
  return n !== null && of !== null ? String(n) + "/" + String(of) : null;
}

/** 决定的身份：投影按 event_id 登记决定请求，载荷里的 decision_id 优先。 */
function decisionOf(ev: FloorEvent): string | null {
  const id = pl(ev).decision_id;
  return typeof id === "string" && id ? id : (ev.event_id ?? null);
}

/** 一种事件 → 楼层的动作（画面 3 的动作表；每种翻成动作的事件都要在这里有一条）。 */
type Rule = (ev: FloorEvent, ctx: ActionContext) => PixelAction[];

const FLOOR: Readonly<Record<string, Rule>> = {
  user_input_received: (ev) => [at("mail", ev)],
  work_item_created: (ev) => [at("mail", ev)],
  department_activated: (ev) => (ev.department ? [at("room_light", ev)] : []),
  context_assembled: (ev, ctx) => [one("gather", ev, ctx)],
  model_requested: (ev, ctx) => [one("think", ev, ctx)],
  model_request_serialized: (ev, ctx) => [one("think", ev, ctx)],
  model_attempt_finished: (ev, ctx) => [one("idea", ev, ctx)],
  model_attempt_failed: (ev, ctx) => [one("request_failed", ev, ctx)],
  model_retry_scheduled: (ev, ctx) => [one("retry", ev, ctx, { count: countOf(ev) })],
  tool_started: (ev, ctx) => [one(floorTool(ev), ev, ctx)],
  tool_skipped: (ev, ctx) => [one("tool_denied", ev, ctx)],
  proposal_submitted: (ev, ctx) => [one("submit", ev, ctx)],
  proposal_rejected: (ev, ctx) => [one("rejected", ev, ctx)],
  // PRD 被接纳：产品盖上有效章，包裹从产品送往工程（一条事件翻出两个动作）
  spec_accepted: (ev, ctx) => [one("stamp_valid", ev, ctx), handoff(ev, "product", "engineering", "prd")],
  contract_accepted: (ev, ctx) => [one("stamp_valid", ev, ctx), handoff(ev, "product", "engineering", "prd")],
  product_decision_accepted: (ev, ctx) => [one("stamp_valid", ev, ctx), handoff(ev, "product", "engineering", "prd")],
  delivery_accepted: (ev, ctx) => [one("seal", ev, ctx), handoff(ev, "engineering", "quality", "box")],
  structure_accepted: (ev) => [handoff(ev, "engineering", "quality", "box")],
  // 放行：放行单送往成果库，载荷写明 release_to 时送往那个部门；缺陷记录经回流管道送回工程
  qa_submitted: (ev, ctx) => (pl(ev).verdict === "release"
    ? [one("stamp_release", ev, ctx), handoff(ev, "quality", text(pl(ev).release_to) || "library", "release")]
    : [one("stamp_defect", ev, ctx), handoff(ev, "quality", "engineering", "defect")]),
  // 独立判断：核验角色交上自己的判断（先判断后看解释，工单 #358）
  independent_judgement_committed: (ev, ctx) => [one("submit", ev, ctx)],
  ask_started: (ev) => {
    const spoken = sayAsk(ev);
    return [{
      kind: "letter", position: posOf(ev), item: ev.work_item_id ?? null,
      from: pl(ev).requester ?? null, to: pl(ev).recipient ?? null, answer: false, ...spoken,
    }];
  },
  ask_answered: (ev) => {
    const spoken = sayAnswer(ev);
    return [{
      kind: "letter", position: posOf(ev), item: ev.work_item_id ?? null,
      from: pl(ev).recipient ?? null, to: pl(ev).requester ?? null, answer: true, ...spoken,
    }];
  },
  department_guidance_received: (ev, ctx) => [one("note_in", ev, ctx)],
  department_guidance_applied: (ev, ctx) => [one("note_read", ev, ctx)],
  department_guidance_responded: (ev, ctx) => [one("note_reply", ev, ctx)],
  compaction_recorded: (ev, ctx) => [one("compact", ev, ctx)],
  compaction_failed: (ev, ctx) => [one("compact_fail", ev, ctx)],
  run_paused: (ev, ctx) => [one("paused", ev, ctx)],
  run_failed: (ev, ctx) => [one("failed", ev, ctx)],
  run_done: (ev, ctx) => [one("done", ev, ctx)],
  // 继续工作：画面重新动起来（每个角色伸个懒腰、部门房间亮一下）
  run_resumed: (ev) => [at("resume", ev)],
  run_continued: (ev) => [at("resume", ev)],
  deliverable_adopted: (ev) => [at("adopt", ev)],
  baseline_adopted: (ev) => [at("adopt", ev)],
  decision_requested: (ev) => [at("decision_out", ev, { decision: decisionOf(ev), say: say(ev) })],
  project_decision_requested: (ev) => [at("decision_out", ev, { decision: decisionOf(ev), say: say(ev) })],
  decision_answered: (ev) => [at("decision_back", ev, { decision: decisionOf(ev), say: say(ev) })],
  project_decision_answered: (ev) => [at("decision_back", ev, { decision: decisionOf(ev), say: say(ev) })],
};

/** 楼层翻成动作的事件种类（动作表的键；测试按它核对每种事件都有样例）。 */
export const FLOOR_EVENT_TYPES: readonly string[] = Object.keys(FLOOR).sort();

/** 一条事件 → 楼层的动作；这个场景不画的事件返回空表（归属见 translate/coverage.ts）。 */
export function floorActions(ev: FloorEvent, ctx: ActionContext = {}): PixelAction[] {
  const rule = FLOOR[ev.type];
  if (!rule) return [];
  return rule(ev, ctx).filter((action) => action.kind && Number.isFinite(action.position));
}

// ---------------------------------------------------------------------------
// 决定卡片（实时内容）

/** 决定请求 → 大厅板上贴着的卡片（只取还在等待回答的；文字在这里写好）。 */
export function floorCards(
  decisions: readonly DecisionView[] | null,
  names: (decision: DecisionView) => { projectName: string; workItemTitle: string },
  now: number,
): DecisionFace[] {
  return (decisions ?? [])
    .filter((d) => d.status === "open")
    .map((d) => {
      const card = face(d, now, names(d));
      return {
        ...card,
        options: card.options.map((op) => ({
          ...op,
          note_missing_text: op.note_required ? `「${op.label}」需要在说明里写明修改意见` : null,
        })),
      };
    });
}

// ---------------------------------------------------------------------------
// 流式文字（实时内容）

/** 输出片段 → 流式文字；不是输出片段的事件返回 null。 */
export function streamText(ev: FloorEvent): { room: string | null; role: string | null; text: string } | null {
  if (ev.type !== "model_stream_progress") return null;
  const p = pl(ev);
  const body = text(p.text ?? p.delta ?? p.chunk);
  if (!body) return null;
  return { room: ev.department ?? null, role: ev.role ?? null, text: cut(body, 60) };
}

// ---------------------------------------------------------------------------
// 事件信封 → 楼层事件的形状

/** 事件流里的事件 → 楼层事件的形状（画面上用到的字段；位置原样带过来）。 */
export function toFloorEvent(event: EventObject): FloorEvent {
  const raw = event as unknown as Record<string, unknown>;
  const payload = raw.payload;
  return {
    type: event.type,
    position: typeof raw.position === "number" ? raw.position : Number.NaN,
    event_id: typeof raw.event_id === "string" ? raw.event_id : null,
    project_id: typeof raw.project_id === "string" ? raw.project_id : null,
    department: typeof raw.department === "string" ? raw.department : null,
    role: typeof raw.role === "string" ? raw.role : null,
    tool: typeof raw.tool === "string" ? raw.tool : null,
    label: typeof raw.label === "string" ? raw.label : null,
    work_item_id: typeof raw.work_item_id === "string" ? raw.work_item_id : null,
    payload: payload && typeof payload === "object" ? (payload as Payload) : null,
  };
}

/** 测试与页面共用：一个事件是不是这个项目的（没有项目的事件算这个项目的）。 */
export function belongsTo(ev: FloorEvent, projectId: string): boolean {
  return ev.project_id === null || ev.project_id === projectId;
}

// ---------------------------------------------------------------------------
// 循环与收敛（工单 #400，原型 v10 设计说明第 3、4 节）：把 run.loops 的结果翻成画面标签与观测页的行。
// 判定不在这一层：状态、已用量与「缺少的事实」都照着查询结果写。

/** 循环树的层的中文名。 */
export const LOOP_LAYER_LABELS: Readonly<Record<string, string>> = Object.freeze({
  project_loop: "项目循环",
  work_item: "事项",
  run: "运行",
  activation: "激活",
  step: "步骤",
});

/** 收敛状态的中文名：五种状态与「不判定」；文字与颜色同时给出，不只靠颜色区分。 */
export const LOOP_STATE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  converging: "收敛中",
  stalled: "停滞",
  oscillating: "震荡",
  drifting: "漂移",
  boundary: "达到边界",
  undetermined: "不判定",
});

/** 三项判定参数的中文名（观测页写出判定用的规则与轮数）。 */
export const LOOP_PARAMETER_LABELS: Readonly<Record<string, string>> = Object.freeze({
  "convergence.rounds": "收敛判定看最近几轮",
  "convergence.step_window": "步骤停滞看连续几步",
  "convergence.step_repeat": "同一次调用重复几次算震荡",
});

export function loopStateLabel(state: string): string {
  return LOOP_STATE_LABELS[state] ?? state;
}

export function loopLayerLabel(layer: string): string {
  return LOOP_LAYER_LABELS[layer] ?? layer;
}

/** 一个已用量与上限的文字：不设上限时写「不设上限」，数值照写（设计第 5 节末）。 */
export function amountText(amount: LoopAmount | undefined, unit: string): string {
  if (!amount) return "—";
  return `${amount.used}${unit} / ${amount.unlimited ? "不设上限" : `${amount.limit}${unit}`}`;
}

export interface LoopRow {
  key: string;
  layer: string;
  layerLabel: string;
  instance: string;
  rounds: number | null;
  used: string;
  state: string;
  stateLabel: string;
  stopReason: string;
  missing: string;
}

function loopLayer(loops: RunLoopsResult, name: string): LoopLayer | undefined {
  return loops.layers.find((layer) => layer.name === name);
}

function workSteps(activation: LoopActivation): number {
  // 工作步：压缩步不是工作步（与步骤层的判定口径一致）
  return activation.steps.filter((step) => step.purpose !== "compaction").length;
}

/** 观测页「循环」区块的行：项目循环 → 事项 → run → 各部门的激活 → 每次激活中的步骤循环。 */
export function loopRows(loops: RunLoopsResult | null): LoopRow[] {
  if (loops === null) return [];
  const project = loopLayer(loops, "project_loop");
  const item = loopLayer(loops, "work_item");
  const run = loopLayer(loops, "run");
  const stepLayer = loopLayer(loops, "step");
  const row = (layer: string, instance: string, rounds: number | null, used: string, state: string,
               missing: string | null | undefined): LoopRow => ({
    key: `${layer}|${instance}`,
    layer,
    layerLabel: loopLayerLabel(layer),
    instance,
    rounds,
    used,
    state,
    stateLabel: loopStateLabel(state),
    stopReason: "",
    missing: missing ?? "",
  });
  const rows: LoopRow[] = [
    row("project_loop", "本事项", loops.rounds, amountText(run?.amounts["model_steps"], " 步"),
        project?.state ?? "undetermined", project?.missing),
    row("work_item", "事项树根", loops.rounds, amountText(run?.amounts["elapsed_ms"], " 毫秒"),
        item?.state ?? "undetermined", item?.missing),
  ];
  const runRow = row("run", "运行", loops.rounds,
                     `${amountText(run?.amounts["elapsed_ms"], " 毫秒")}；${amountText(run?.amounts["model_steps"], " 步")}`,
                     run?.state ?? "undetermined", run?.missing);
  runRow.stopReason = loops.stop_reason ? label(STOP_REASON, loops.stop_reason) : "";
  rows.push(runRow);
  loops.activations.forEach((activation, index) => {
    const name = departmentName(activation.department);
    rows.push(row("activation", `${name} · 第 ${index + 1} 次激活`, index + 1, `${workSteps(activation)} 步`,
                  activation.state, activation.missing));
    rows.push(row("step", `${name} · 第 ${index + 1} 次激活 · 步骤循环`, index + 1, `${workSteps(activation)} 步`,
                  stepLayer?.state ?? "undetermined", stepLayer?.missing));
  });
  return rows;
}

/** 观测页写出判定用的规则与轮数：三项冻结值与两个方法常量。 */
export function loopRuleText(loops: RunLoopsResult | null): string {
  if (loops === null) return "";
  const parts = Object.entries(LOOP_PARAMETER_LABELS)
    .filter(([name]) => loops.parameters[name] !== undefined)
    .map(([name, caption]) => `${caption} ${loops.parameters[name]}`);
  parts.push(`轮数达到 ${loops.method["trend_switch_rounds"]} 改用趋势检验，同一条件翻转 ${loops.method["flip_threshold"]} 次算震荡`);
  return parts.join("；");
}

/** 覆盖层「循环」的数据：楼层信息条写 run 层，各部门房间写激活层与步骤循环，右上角写图例。 */
export function loopsOverlay(loops: RunLoopsResult | null): LoopsOverlayData {
  const legend = ["converging", "stalled", "oscillating", "drifting", "boundary", "undetermined"]
    .map((state) => ({ state, label: loopStateLabel(state) }));
  if (loops === null) {
    return { bar: { text: "还没有运行", state: "undetermined" }, rooms: [], legend };
  }
  const run = loopLayer(loops, "run");
  const stepLayer = loopLayer(loops, "step");
  const state = run?.state ?? "undetermined";
  const stopped = loops.stop_reason ? ` · 停止：${label(STOP_REASON, loops.stop_reason)}` : "";
  const rooms = loops.activations.map((activation, index) => ({
    department: activation.department ?? "",
    state: activation.state,
    text: `第 ${index + 1} 次激活 · ${loopStateLabel(activation.state)}`,
    step_text: `步骤 ${workSteps(activation)} 步 · ${loopStateLabel(stepLayer?.state ?? "undetermined")}`,
  }));
  return { bar: { text: `运行 · ${loopStateLabel(state)}${stopped}`, state }, rooms, legend };
}
