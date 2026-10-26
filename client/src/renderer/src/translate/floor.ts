// 楼层的翻译层（画面与播放设计说明第 6 节、原型 v13 js/translate/translate.js 的楼层部分，工单 #953）。
//
// 这一层是唯一同时认识 Yudao 的说法与画面的说法的地方：
//   - floorState：project.loop（带位置）加上各部门的角色 → 画面合同的楼层状态（事项、部门在事项上的状态、
//     角色、成果库），状态值经 translate/tables.ts 的对应表翻好（服务端 in_progress → 画面的 working）；
//   - floorActions：一条事件（带位置）→ 零个、一个或几个楼层的动作（kind 取画面合同的楼层声明表，
//     client/src/renderer/src/pixel/generated/floor-decl.json 的 kinds）；
//   - floorCards：决定请求 → 大厅板上贴着的卡片，卡片上的文字在这里写好；
//   - streamText：输出片段 → 流式文字（实时内容，不进播放时间线）。
//
// 事实只来自查询：状态由查询结果翻译，翻译层不把事件累加成事实（设计说明第 6 节）。
// 说话的话术用 translate/say.ts（画面 2 的成果）。

import type { DecisionView, EventObject, ProjectLoopResult, WorkItemLoop } from "../api/generated/types.gen.ts";
import type { Artifact, BusyState, ItemState, PixelAction } from "../pixel/contract.ts";
import { floorState as checkFloorState } from "../pixel/contract.ts";
import type { DecisionFace, FloorModel, LoopItem, MachineView, OpsView, RoleInfo, WaitingProvider } from "../pixel/world/types.ts";
import { face } from "../views/decisions/card-logic.ts";
import { cut, say, sayAnswer, sayAsk, sayHandoff } from "./say.ts";
import { itemStateOf, roleStatus } from "./tables.ts";

// ---------------------------------------------------------------------------
// 状态

/** 一个部门在事项上的状态（服务端的 DepartmentState.state）→ 画面合同的部门状态。 */
const DEPT_BUSY: Readonly<Record<string, BusyState>> = {
  working: "working",
  // 回答别的部门的询问：部门在做这件事（服务端同样记作 working，只是原因不同）
  asking: "working",
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

function itemOf(row: WorkItemLoop, index: number): LoopItem {
  const departments: Record<string, BusyState> = {};
  for (const [dept, state] of Object.entries(row.departments ?? {})) {
    const busy = busyOf(state.state);
    if (busy) departments[dept] = busy;
  }
  return {
    id: row.work_item_id,
    work_item_id: row.work_item_id,
    status: itemStateOf(row) as ItemState,
    kind: row.kind,
    sign: row.sign,
    color_index: row.color_index ?? index + 1,
    department: row.department,
    round: row.round,
    started_at: row.started_at,
    elapsed_sec: row.elapsed_sec,
    time_limit_sec: row.time_limit_sec,
    queue_pos: undefined,
    waiting_provider_sec: undefined,
    ...(Object.keys(departments).length ? { departments } : {}),
  };
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
    open_requests: [],
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
