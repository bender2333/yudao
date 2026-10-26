// 翻译层：部门房间（画面与播放设计说明第 6 节、原型 v13 js/translate/translate.js 的 T.room，工单 #954）。
//
// 唯一同时认识 Yudao 的说法与画面的说法的地方：
//   state   —— department.workspace（带位置）→ 房间的状态（画面合同 pixel/contract.ts 的 RoomState）；
//   actions —— 一条事件与这个部门 → 房间的动作（kind 取自 pixel/room/room-decl.ts 的声明表）；
//   stream  —— 输出片段与 attempt.live 已收到的文字 → 流式文字（实时内容，不进时间线）。
// 事实只来自查询：状态由查询结果翻译，翻译层不把事件累加成事实；事件只翻成动作。
// 说话的内容由 translate/say.ts 写在动作的 say 与 sayTo 上，画面只管画。
//
// 哪些事件在房间里翻成动作、哪些作为实时内容、哪些不画，写在 translate/coverage.ts；
// 这个文件只实现其中房间「翻成动作」的那一组与流式文字。

import { roomState as contractRoomState } from "../pixel/contract.ts";
import type { Artifact, PixelAction, RoomState } from "../pixel/contract.ts";
import { roomPose, roomStatus, roleStatus } from "./tables.ts";
import { say, sayAnswer, sayAsk, sayHandoff } from "./say.ts";

/** 一条事件里房间用到的字段（接口合同的事件信封）。 */
export interface RoomEvent {
  type: string;
  /** 来源事件的全局位置（动作带位置）。 */
  position: number;
  department?: string | null;
  role?: string | null;
  tool?: string | null;
  label?: string | null;
  work_item_id?: string | null;
  payload?: Record<string, unknown> | null;
}

/** 翻译时的上下文：roleName 把角色 id 写成页面上的名称（动作里的话要用）。 */
export interface RoomContext {
  roleName?: (role: string | null) => string | null;
}

/** 流式文字：接在哪个房间的哪个角色头上，与显示的文字。 */
export interface RoomStream {
  who: { room: string | null; role: string | null };
  text: string;
}

/** 事件载荷是按种类不同的字段集合，取值时先收窄。 */
type Payload = Record<string, unknown>;

const str = (value: unknown): string => (typeof value === "string" ? value : "");
const num = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);
const flag = (value: unknown): boolean => value === true;
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const rec = (value: unknown): Payload => (value !== null && typeof value === "object" ? (value as Payload) : {});
const pl = (ev: RoomEvent): Payload => ev.payload ?? {};

/** 事件说明里「」括起的部分（真实系统的说明用「」标出具体的值）。 */
export function quoted(label: string | null | undefined): string | null {
  const m = /「([^」]+)」/.exec(str(label));
  return m ? m[1] : (str(label) || null);
}

// ---------------------------------------------------------------------------
// department.workspace 的房间 → 房间的状态

/** 查询结果里房间的那一块（字段按需取，缺的按空值）。 */
function roomOf(workspace: { room: unknown }): Payload {
  return rec(workspace.room);
}

/** 房间的一个角色：服务端的角色状态经对应表翻成画面的词。 */
function roleOf(raw: unknown): { id: string; name: string; kind: string; status: string; task: string | null } {
  const r = rec(raw);
  return {
    id: str(r.id),
    name: str(r.name),
    kind: str(r.kind),
    status: roleStatus(str(r.status)),
    task: r.task === undefined || r.task === null ? null : str(r.task),
  };
}

/**
 * 部门工作间的查询（department.workspace，带位置）→ 房间的状态。
 * 画面合同的状态带位置：位置来自查询快照（translate 只传递它，不解读它）。
 */
export function state(o: { position: number; workspace: { room: unknown } }): RoomState {
  const r = roomOf(o.workspace);
  const pose = r.pose;
  const pipes = r.pipes;
  const s: Record<string, unknown> = {
    position: o.position,
    department: str(r.department),
    level: str(r.level) || "ui",
    status: roomStatus(str(r.status)),
    crt: rec(r.crt),
    roles: list(r.roles).map(roleOf),
    pose: pose === null || pose === undefined
      ? null
      : { role_id: str(rec(pose).role_id) || null, anim: roomPose(str(rec(pose).action)) },
    door: r.door === null || r.door === undefined ? null : str(r.door),
    hold_card: r.hold_card === null || r.hold_card === undefined ? null : str(r.hold_card),
    mailbox: num(r.mailbox),
    summaries: num(r.summaries),
    scrolls: num(r.scrolls),
    pinned_notes: num(r.pinned_notes),
    semantic_cards: num(r.semantic_cards),
    machine: r.machine === null || r.machine === undefined ? null : str(r.machine),
    remote_unknown: flag(r.remote_unknown),
    waiting_provider: flag(r.waiting_provider),
    pipes: pipes === null || pipes === undefined
      ? null
      : { out: str(rec(pipes).out), letters_waiting: num(rec(pipes).letters_waiting) },
    existing_read: flag(r.existing_read),
    trial: r.trial === null || r.trial === undefined ? null : rec(r.trial),
    tool_panel: r.tool_panel === null || r.tool_panel === undefined ? null : rec(r.tool_panel),
    self_test: r.self_test === null || r.self_test === undefined ? null : rec(r.self_test),
  };
  // 状态是画面层唯一认的输入：取值不合法就在这里报错，错误写明是哪一项
  return contractRoomState(s);
}

// ---------------------------------------------------------------------------
// 事件 → 房间的动作

/**
 * 房间的工具：按工具的名称落到专门动作；没有专门动作的工具调用是进度
 * （真实系统的工具名见 harness/tools.py；原型 v13 的对照表按 v12 的动作图鉴）。
 * 看目录、删文件、移动文件在原型 v12 的动作图鉴里没有单独的动作，按 v13 的口径归入进度：
 * 不排队，头顶换成最近的一项，说出来的是「现在看看有什么文件」这样的话。
 */
const ROOM_TOOL: Readonly<Record<string, string>> = {
  search: "search",
  read_range: "read",
  read_file: "read",
  edit_range: "write",
  write_file: "write",
  bash: "run_command",
  run_command: "run_command",
  run_check: "inspect",
  browser: "self_test",
  browser_navigate: "self_test",
};

/** 事件与这个房间有关：事件没有部门（整个事项的事），或者就是这个部门的事。 */
const mine = (ev: RoomEvent, dept: string): boolean => !ev.department || ev.department === dept;

/** 一个部门里的一个角色做的一件事：画面上的一次动作。 */
function one(kind: string, ev: RoomEvent, ctx: RoomContext, extra?: Record<string, unknown>): PixelAction {
  return {
    kind,
    position: ev.position,
    item: ev.work_item_id ?? null,
    room: ev.department ?? null,
    role: ev.role ?? null,
    say: say(ev, { roleName: ctx.roleName }),
    ...(extra ?? {}),
  };
}

/** 只与这个部门有关时给出一个动作，否则为空。 */
const own = (kind: string, extra?: (ev: RoomEvent) => Record<string, unknown>) =>
  (ev: RoomEvent, dept: string, ctx: RoomContext): PixelAction[] =>
    (mine(ev, dept) ? [one(kind, ev, ctx, extra ? extra(ev) : undefined)] : []);

/** 交接的一端：交出的部门是 from 一侧，收到的部门是 to 一侧（说的话按这一侧）。 */
function handoffIn(ev: RoomEvent, dept: string, from: string, to: string, artifact: string): PixelAction[] {
  if (dept !== from && dept !== to) return [];
  return [{
    kind: "handoff",
    position: ev.position,
    item: ev.work_item_id ?? null,
    room: dept,
    from,
    to,
    artifact: artifact as Artifact,
    ...sayHandoff(artifact, from, to),
  }];
}

/** 重新尝试的次数写成「第 n/of 次」。 */
function retryCount(ev: RoomEvent): string {
  const p = pl(ev);
  const n = p.n ?? p.attempt ?? p.attempt_no ?? 2;
  const of = p.of ?? p.max ?? p.max_attempts ?? 3;
  return `${String(n)}/${String(of)}`;
}

/** 质检结论是放行还是缺陷记录。 */
const released = (ev: RoomEvent): boolean => pl(ev).verdict === "release";

/** 决定请求的种类：模型不能用时举「待恢复」的牌子，结果未知时头顶黄色问号。 */
function decisionAction(ev: RoomEvent, dept: string, ctx: RoomContext): PixelAction[] {
  if (!mine(ev, dept)) return [];
  const p = pl(ev);
  const kind = str(p.kind);
  if (kind === "model_unavailable") {
    return [one("hold_card", ev, ctx, { text: str(p.description) || str(p.message) || quoted(ev.label) || "待恢复" })];
  }
  if (kind === "unknown_action") return [one("puzzled", ev, ctx)];
  return [];
}

/** 房间的动作表：事件种类 → 与这个部门有关的动作（原型 v13 的 ROOM 表，按真实事件种类）。 */
const ROOM: Readonly<Record<string, (ev: RoomEvent, dept: string, ctx: RoomContext) => PixelAction[]>> = {
  department_activated: own("activate"),
  context_assembled: own("fetch_folder"),
  model_requested: own("type_think"),
  model_request_serialized: own("type_think"),
  model_attempt_finished: own("idea"),
  model_attempt_failed: own("slump"),
  model_retry_scheduled: own("retry_wait", (ev) => ({ count: retryCount(ev) })),
  tool_started: (ev, dept, ctx) => {
    if (!mine(ev, dept)) return [];
    const tool = str(ev.tool ?? pl(ev).tool ?? pl(ev).name);
    return [one(ROOM_TOOL[tool] ?? "tool_progress", ev, ctx)];
  },
  // 工具结束：命令亮出退出状态灯，浏览器自测看截图；其余工具结束时房间里没有变化
  tool_called: (ev, dept, ctx) => {
    if (!mine(ev, dept)) return [];
    const tool = str(ev.tool ?? pl(ev).tool ?? pl(ev).name);
    if (tool === "bash" || tool === "run_command") {
      return [one("command_done", ev, ctx, { ok: pl(ev).ok !== false, timed_out: Boolean(pl(ev).timed_out) })];
    }
    if (/^browser/.test(tool)) return [one("self_test", ev, ctx)];
    return [];
  },
  tool_skipped: own("toss"),
  proposal_submitted: own("submit"),
  proposal_rejected: own("returned"),
  // PRD 与产品决定被接纳：产品房间里盖有效章，同时包裹从产品送往工程
  spec_accepted: (ev, dept, ctx) => stampThenHandoff(ev, dept, ctx, "product", "engineering", "prd"),
  contract_accepted: (ev, dept, ctx) => stampThenHandoff(ev, dept, ctx, "product", "engineering", "prd"),
  product_decision_accepted: (ev, dept, ctx) => stampThenHandoff(ev, dept, ctx, "product", "engineering", "prd"),
  // 交付被接纳：工程房间里封存交付箱，同时交付箱从工程送往质检
  delivery_accepted: (ev, dept, ctx) => sealThenHandoff(ev, dept, ctx, "engineering", "quality", "box"),
  structure_accepted: (ev, dept) => handoffIn(ev, dept, "engineering", "quality", "box"),
  // 质检结论：放行单送回成果库（或载荷指定的部门），缺陷记录经回流管道送回工程
  qa_submitted: (ev, dept, ctx) => {
    const release = released(ev);
    const stamp = ev.department === dept ? [one(release ? "stamp_release" : "stamp_rework", ev, ctx)] : [];
    return stamp.concat(release
      ? handoffIn(ev, dept, "quality", str(pl(ev).release_to) || "library", "release")
      : handoffIn(ev, dept, "quality", "engineering", "defect"));
  },
  // 询问：发问的部门写纸条塞进传信管口；被询问的部门取出来读
  ask_started: (ev, dept) => {
    const p = pl(ev);
    const s = sayAsk(ev);
    const base = { position: ev.position, item: ev.work_item_id ?? null, room: dept, role: null };
    if (dept === str(p.requester)) return [{ kind: "send_letter", say: s.say, ...base }];
    if (dept === str(p.recipient)) return [{ kind: "answer_letter", reads: true, say: s.sayTo, ...base }];
    return [];
  },
  // 回答：被询问的部门写回答塞回；发问的部门在管道口接住回答读
  ask_answered: (ev, dept) => {
    const p = pl(ev);
    const s = sayAnswer(ev);
    const base = { position: ev.position, item: ev.work_item_id ?? null, room: dept, role: null };
    if (dept === str(p.recipient)) return [{ kind: "answer_letter", reads: false, say: s.say, ...base }];
    if (dept === str(p.requester)) return [{ kind: "answer_letter", reads: true, say: s.sayTo, ...base }];
    return [];
  },
  department_guidance_received: own("guidance_in"),
  department_guidance_applied: own("guidance_read"),
  department_guidance_responded: own("guidance_reply"),
  compaction_recorded: own("compact"),
  compaction_failed: own("compact_fail"),
  run_paused: own("paused"),
  run_failed: (ev, dept, ctx) => {
    const reason = str(pl(ev).stop_reason ?? pl(ev).reason);
    const kind = reason === "cancelled" || reason === "user_cancelled" ? "cancelled" : "failed";
    return own(kind, () => ({ text: str(pl(ev).message) || reason || null }))(ev, dept, ctx);
  },
  run_done: own("done"),
  run_resumed: own("resume"),
  run_continued: own("resume"),
  decision_requested: decisionAction,
};

/** 产品房间里盖章，接着把包裹送到下一个部门。 */
function stampThenHandoff(ev: RoomEvent, dept: string, ctx: RoomContext, from: string, to: string, artifact: string): PixelAction[] {
  const stamp = ev.department === dept ? [one("stamp_valid", ev, ctx)] : [];
  return stamp.concat(handoffIn(ev, dept, from, to, artifact));
}

/** 工程房间里封存交付箱，接着把交付箱送到质检。 */
function sealThenHandoff(ev: RoomEvent, dept: string, ctx: RoomContext, from: string, to: string, artifact: string): PixelAction[] {
  const seal = ev.department === dept ? [one("seal", ev, ctx)] : [];
  return seal.concat(handoffIn(ev, dept, from, to, artifact));
}

/**
 * 一条事件在这个部门房间里翻成的动作；没有对应时为空。
 * 一条事件可以翻成零个、一个或几个动作。
 */
export function actions(ev: RoomEvent, dept: string, ctx: RoomContext = {}): PixelAction[] {
  const f = ROOM[ev.type];
  if (!f) return [];
  return f(ev, dept, ctx).filter(Boolean);
}

/** 翻成动作的事件种类（与 translate/coverage.ts 里房间的 drawn 是同一组，测试核对两边一致）。 */
export const ROOM_ACTION_TYPES: readonly string[] = Object.keys(ROOM);

// ---------------------------------------------------------------------------
// 实时内容：流式文字

/** 一条事件是不是流式文字（模型输出片段）；是的话给出要显示的文字。 */
const STREAM_TEXT: Readonly<Record<string, (ev: RoomEvent) => string | null>> = {
  model_stream_progress: (ev) => {
    const p = pl(ev);
    return str(p.text) || str(p.delta) || str(p.chunk) || quoted(ev.label) || "……";
  },
};

/** 一条事件作为流式文字交给画面（不进时间线）；不是流式文字时为 null。 */
export function streamOfEvent(ev: RoomEvent): RoomStream | null {
  const f = STREAM_TEXT[ev.type];
  if (!f) return null;
  const text = f(ev);
  if (text === null) return null;
  return { who: { room: ev.department ?? null, role: ev.role ?? null }, text };
}

/**
 * 输出片段与 attempt.live 已收到的文字 → 流式文字。
 * 页面把片段按 offset 拼成一整段（pixel/room/stream.ts 的 StreamBubble），再经这里交给画面。
 */
export function streamOfText(room: string, role: string | null, text: string): RoomStream {
  return { who: { room, role }, text };
}

/** 流式文字的事件种类（与 translate/coverage.ts 里房间的 realtime 一致）。 */
export const ROOM_STREAM_TYPES: readonly string[] = Object.keys(STREAM_TEXT);
