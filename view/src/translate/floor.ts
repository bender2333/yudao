// 楼层的翻译层（画面与播放 docs/design/visualization.md「翻译层」、原型 v13 js/translate/translate.js 的楼层部分，工单 #953）。
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
// 事实只来自查询：状态由查询结果翻译，翻译层不把事件累加成事实（docs/design/visualization.md「翻译层」）。
// 说话的话术用 translate/say.ts（画面 2 的成果）。

import type {
  AcceptanceCoverageResult, AskView, DecisionView, EventObject, LoopActivation, LoopLayer, ProjectLoopResult,
  RunLoopsResult, WorkItemLoop, WorkItemOrganization,
} from "../api/generated/types.gen.ts";
import type {
  Artifact, BusyState, CoverageLegendRow, CoverageOverlayCriterion, CoverageOverlayData, CoverageResult,
  DecisionFace, FactElement, FloorModel, FloorTopology, FloorTopologyAsk, FloorTopologyHandoff,
  FloorTopologyRejection, FloorTopologyRoom, ItemState, LoopItem, LoopsOverlayData, MachineView,
  OpenRequest, OpsView, PixelAction, RoleInfo, ShelfBox, Source, SourceOverlayData, SourceRef, StampKind, WaitingProvider,
} from "../pixel/contract.ts";
import { COVERAGE_RESULTS, floorState as checkFloorState, SOURCES } from "../pixel/contract.ts";
import { CHECK_METHODS } from "./coverage.ts";
import { face, label, STOP_REASON } from "./face.ts";
import { cut, say, sayAnswer, sayAsk, sayHandoff } from "./say.ts";
import { completingRoleOf, itemStateOf, resolveWorkItemStamp, roleStatus } from "./tables.ts";

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
  /** 当前运行或聚焦事项的检验覆盖结果（查询 acceptance.coverage；未打开「检验」覆盖层时不传）。 */
  coverage?: AcceptanceCoverageResult | null;
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
 * 楼层事实元素的中文名（工单 #398）：覆盖层「来源」按它显示。页面不出现内部标识，
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
  const org = row.organization ?? DEFAULT_ORGANIZATION;
  const stampInfo = resolveWorkItemStamp(row as never, org);
  return {
    id: row.work_item_id,
    work_item_id: row.work_item_id,
    title: row.sign,
    status,
    kind: row.kind,
    sign: row.sign,
    color_index: row.color_index ?? index + 1,
    // 因升级停止的事项没有当前部门（project.loop 的 department 为空）：门口牌子立在最后工作的那个部门
    // （工单 #1186，docs/design/app-and-interface.md「查询清单」 2026-10-29 补充）
    department: row.department ?? (status === "upgrade_stopped" ? row.last_department : null),
    ...(stampInfo.entry_room ? { entry_room: stampInfo.entry_room } : {}),
    ...(stampInfo.stamp_room ? { stamp_room: stampInfo.stamp_room } : {}),
    ...(stampInfo.stamp_kind ? { stamp_kind: stampInfo.stamp_kind } : {}),
    ...(stampInfo.outsourced ? { outsourced: true } : {}),
    round: row.round,
    started_at: row.started_at,
    elapsed_sec: row.elapsed_sec,
    time_limit_sec: row.time_limit_sec,
    queue_pos: undefined,
    waiting_provider_sec: undefined,
    ...(Object.keys(departments).length ? { departments } : {}),
    // 事实元素与它们的来源（工单 #398、#1382）：覆盖层「来源」与点开回链读它；没有来源的元素不在这里
    ...(Object.keys(refs).length ? { refs } : {}),
  };
}

// ---------------------------------------------------------------------------
// 事实来源（工单 #396 的数据、工单 #398 与 #1382 的画面）：来源种类的中文名与覆盖层「来源」的数据

/** 五种来源的中文名：覆盖层「来源」的图例按它显示。 */
export const SOURCE_LABELS: Readonly<Record<Source, string>> = {
  rule: "确定规则",
  host_measurement: "主机测量",
  user: "用户",
  role_statement: "角色陈述",
  decision_model: "决策模型",
};

/**
 * 覆盖层「来源」要描边与查缺的五个元素（门牌、包裹、成果库的箱子、信息条上的轮次与已用时间）。
 * 放行章随放行到来，未放行的事项上还没有这一项，覆盖层的描边与图例维持这五项不变（工单 #1382）。
 */
export const DRAWN_FACT_ELEMENTS: readonly FactElement[] = ["sign", "parcel", "box", "round", "elapsed"];

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

const FALLBACK_REF = { position: 0, source: "rule" as const };

/**
 * 旧夹具或单元测试手工行未带 organization 时的集中兜底默认组织（工单 #1383）：
 * 仅在翻译层这一处保留默认三职能关系，画面层代码零出现职能名。
 */
export const DEFAULT_ORGANIZATION: WorkItemOrganization = {
  form: "three_departments",
  routing: "watched_outputs",
  roles: [
    { id: "product", label: "产品", ref: FALLBACK_REF },
    { id: "engineering", label: "工程", ref: FALLBACK_REF },
    { id: "quality", label: "质检", ref: FALLBACK_REF },
  ],
  entry: { id: "product", label: "产品", ref: FALLBACK_REF },
  verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["delivery_spec"] }], ref: FALLBACK_REF }],
  completing: null,
  watched: [
    { source: "product", recipient: "engineering", outcome: "product_spec", ref: FALLBACK_REF },
    { source: "product", recipient: "quality", outcome: "product_spec", ref: FALLBACK_REF },
    { source: "engineering", recipient: "quality", outcome: "delivery_spec", ref: FALLBACK_REF },
  ],
  asks: [
    { requester: "product", recipient: "engineering", ref: FALLBACK_REF },
    { requester: "product", recipient: "quality", ref: FALLBACK_REF },
    { requester: "engineering", recipient: "quality", ref: FALLBACK_REF },
    { requester: "engineering", recipient: "product", ref: FALLBACK_REF },
    { requester: "quality", recipient: "product", ref: FALLBACK_REF },
    { requester: "quality", recipient: "engineering", ref: FALLBACK_REF },
  ],
  rejections: [{ verifier: "quality", role: "engineering", outcome: "delivery_spec", ref: FALLBACK_REF }],
};

/** 推出一个组织的入口角色标识：有 entry 字段时直接取，早期录制快照无 entry 时取未作为关注接收方的首个角色。 */
function inferEntryIds(org: WorkItemOrganization): string[] {
  if (org.entry?.id) return [org.entry.id];
  if (org.roles.length === 0) return [];
  const recipients = new Set(org.watched.map((w) => w.recipient));
  const roots = org.roles.filter((r) => !recipients.has(r.id)).map((r) => r.id);
  return [roots[0] ?? org.roles[0].id];
}

/**
 * 从楼层事项冻结定义的组织推出这一层的拓扑（工单 #1383，docs/design/visualization.md「画面跟着定义伸缩」）：
 * 房间是各事项定义里角色的并集；任一定义里是核验角色的带盖章台，任一定义里是交完成角色的带出口托盘；
 * 交接管道、传信管与回流管是各定义里对应关系的并集；运维屋只在定义包含运维或传入 ops 状态时出现。
 */
export function deriveFloorTopology(
  workItems: readonly WorkItemLoop[],
  ops: OpsView | null | undefined = null,
): FloorTopology {
  const orgs = workItems.map((row) => row.organization ?? DEFAULT_ORGANIZATION);
  const roomsMap = new Map<string, FloorTopologyRoom>();
  for (const org of orgs) {
    const verifiers = new Set(org.verifiers.map((v) => v.role));
    const completingId = completingRoleOf(org);
    for (const role of org.roles) {
      const existing = roomsMap.get(role.id);
      if (existing) {
        existing.verifier = existing.verifier || verifiers.has(role.id);
        existing.exit_tray = existing.exit_tray || completingId === role.id;
      } else {
        roomsMap.set(role.id, {
          id: role.id,
          label: role.label,
          verifier: verifiers.has(role.id),
          exit_tray: completingId === role.id,
        });
      }
    }
  }
  if (ops && !roomsMap.has("operations")) {
    roomsMap.set("operations", { id: "operations", label: "运维", verifier: false, exit_tray: false });
  }

  const handoffMap = new Map<string, FloorTopologyHandoff>();
  const addHandoff = (from: string, to: string, extra: Omit<FloorTopologyHandoff, "from" | "to"> = {}): void => {
    const key = `${from}>${to}`;
    if (!handoffMap.has(key)) handoffMap.set(key, { from, to, ...extra });
  };

  for (const org of orgs) {
    for (const entryId of inferEntryIds(org)) {
      addHandoff("hall", entryId);
    }
    for (const w of org.watched) {
      if (w.source && w.recipient && w.source !== w.recipient) {
        addHandoff(w.source, w.recipient, { valve: true });
      }
    }
    for (const v of org.verifiers) {
      if (v.role) addHandoff(v.role, "library", { valve: true });
    }
    const completingId = completingRoleOf(org);
    if (completingId) {
      addHandoff(completingId, "library", { valve: true });
    }
  }
  if (roomsMap.has("operations")) {
    addHandoff("library", "operations", { optional: true });
    addHandoff("operations", "machine_room", { optional: true });
  }

  const roomOrder = Array.from(roomsMap.keys());
  const orderOf = (id: string): number => {
    const idx = roomOrder.indexOf(id);
    return idx >= 0 ? idx : Number.MAX_SAFE_INTEGER;
  };

  const askMap = new Map<string, FloorTopologyAsk>();
  for (const org of orgs) {
    for (const ask of org.asks) {
      if (!ask.requester || !ask.recipient || ask.requester === ask.recipient) continue;
      const [from, to] = orderOf(ask.requester) <= orderOf(ask.recipient)
        ? [ask.requester, ask.recipient]
        : [ask.recipient, ask.requester];
      const key = `${from}~${to}`;
      if (!askMap.has(key)) askMap.set(key, { from, to });
    }
  }

  const rejectionMap = new Map<string, FloorTopologyRejection>();
  for (const org of orgs) {
    for (const rej of org.rejections) {
      if (!rej.verifier || !rej.role || rej.verifier === rej.role) continue;
      const key = `${rej.verifier}>${rej.role}`;
      if (!rejectionMap.has(key)) rejectionMap.set(key, { from: rej.verifier, to: rej.role });
    }
  }
  if (roomsMap.has("operations")) {
    rejectionMap.set("operations>hall", { from: "operations", to: "hall", via: "under", optional: true });
  }

  return {
    rooms: Array.from(roomsMap.values()),
    handoffs: Array.from(handoffMap.values()),
    asks: Array.from(askMap.values()),
    rejections: Array.from(rejectionMap.values()),
  };
}

/**
 * 查询结果 → 画面合同的楼层状态。服务端的说法只在这里换成画面的说法（状态经 tables.ts 的对应表）。
 * 翻完按画面合同校验：取值不在合同里时抛错，错误写明是哪一项。
 */
export function floorState(input: FloorStateInput): FloorModel {
  const loop = input.loop;
  const workItems = loop?.work_items ?? [];
  const items = workItems.map(itemOf);
  const itemByWorkItemId = new Map(items.map((it) => [it.work_item_id, it]));
  const adoptions = loop?.adoptions ?? [];
  const boxes: ShelfBox[] = adoptions.map((a) => {
    const raw = a as unknown as Record<string, unknown>;
    const matched = itemByWorkItemId.get(a.work_item_id);
    const stamp_kind: StampKind = matched?.stamp_kind
      ?? (raw.stop_reason === "open_loop" ? "open_loop" : "release");
    const outsourced = Boolean(matched?.outsourced)
      || raw.outsourced === true
      || raw.verified_external === true;
    return {
      work_item_id: a.work_item_id,
      stamp_kind,
      ...(outsourced ? { outsourced: true } : {}),
    };
  });
  const model: FloorModel = {
    position: input.position,
    items,
    open_requests: openRequestsOf(loop, input.asks),
    shelves: boxes.length > 0
      ? { adopted: adoptions.map((a) => a.work_item_id), boxes }
      : { adopted: adoptions.map((a) => a.work_item_id) },
    slots: input.slots ?? null,
    waiting_provider: input.waiting_provider ?? [],
    machines: input.machines ?? null,
    ops: input.ops ?? null,
    interrupted: Boolean(input.interrupted),
    roles: rolesOf(input),
    decisions: [],
    topology: deriveFloorTopology(workItems, input.ops),
    ...(input.focus ? { focus_id: input.focus } : {}),
    ...(input.coverage !== undefined ? { coverage: coverageOverlay(input.coverage) } : {}),
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
 * 整层「中断」的取值（工单 #1188，docs/design/visualization.md「实时内容」 2026-10-29 补充）：事件流断开，或者任一事项的
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

/** 翻动作时的上下文：角色名称与当前事项冻结定义的组织（工单 #1383）。 */
export interface ActionContext {
  roleName?: (role: string | null) => string | null;
  organization?: WorkItemOrganization | null;
}

type Payload = Record<string, unknown>;

const pl = (ev: FloorEvent): Payload => ev.payload ?? {};
const text = (value: unknown): string => (value === undefined || value === null ? "" : String(value));
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

function orgOf(ctx?: ActionContext): WorkItemOrganization {
  return ctx?.organization ?? DEFAULT_ORGANIZATION;
}

function deptLabelOf(org: WorkItemOrganization): (department: string) => string | null {
  return (department: string): string | null => org.roles.find((r) => r.id === department)?.label ?? null;
}

function isVerifierInOrg(org: WorkItemOrganization, department: string | null | undefined): boolean {
  return Boolean(department && org.verifiers.some((v) => v.role === department));
}

function specTargetPair(ev: FloorEvent, org: WorkItemOrganization): { from: string; to: string } {
  const from = ev.department || inferEntryIds(org)[0] || "product";
  const to = org.watched.find((w) => w.source === from && w.outcome === "product_spec")?.recipient
    ?? org.watched.find((w) => w.source === from)?.recipient
    ?? org.roles[1]?.id
    ?? "engineering";
  return { from, to };
}

function deliveryTargetPair(ev: FloorEvent, org: WorkItemOrganization): { from: string; to: string } {
  const from = ev.department
    || org.watched.find((w) => w.outcome === "delivery_spec")?.source
    || org.roles[1]?.id
    || "engineering";
  const to = org.watched.find((w) => w.source === from && w.outcome === "delivery_spec")?.recipient
    ?? org.verifiers[0]?.role
    ?? (org.completing?.id === from ? "library" : "quality");
  return { from, to };
}

function qaReworkPair(ev: FloorEvent, org: WorkItemOrganization): { from: string; to: string } {
  const from = ev.department || org.verifiers[0]?.role || "quality";
  const to = text(pl(ev).target_department || pl(ev).to)
    || org.rejections.find((r) => r.verifier === from)?.role
    || org.rejections[0]?.role
    || "engineering";
  return { from, to };
}

/** 一条事件在画面上的位置（动作的回链）；事件没有位置时抛错，不猜一个。 */
function posOf(ev: FloorEvent): number {
  if (!Number.isFinite(ev.position)) throw new Error("翻译层收到的" + ev.type + "事件没有位置");
  return ev.position;
}

/** 一个职能屋里的一个角色做的事。 */
function one(kind: string, ev: FloorEvent, ctx: ActionContext, extra?: Record<string, unknown> | null): PixelAction {
  const org = orgOf(ctx);
  return {
    kind,
    position: posOf(ev),
    item: ev.work_item_id ?? null,
    room: ev.department ?? null,
    role: ev.role ?? null,
    say: say(ev, {
      roleName: ctx.roleName,
      deptLabel: deptLabelOf(org),
      isVerifier: (dept) => isVerifierInOrg(org, dept),
      hasVerifiers: org.verifiers.length > 0,
    }),
    ...(extra ?? {}),
  };
}

/** 一份成果从一个职能送到另一个职能：包裹沿管道走，两端各说一句话。 */
function handoff(ev: FloorEvent, from: string, to: string, artifact: Artifact, ctx?: ActionContext): PixelAction {
  const spoken = sayHandoff(artifact, from, to, deptLabelOf(orgOf(ctx)));
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
export function floorTool(ev: FloorEvent, ctx?: ActionContext): string {
  const tool = text(ev.tool ?? pl(ev).tool);
  if (tool === "search") return "search";
  if (tool === "run_command" || tool === "bash") return "command";
  if (tool === "run_check") return "inspect";
  if (/write|edit/.test(tool)) return "write";
  if (/fetch|http|net|url/.test(tool)) return "fetch";
  if (/mcp/.test(tool)) return "tool";
  if (/browser|computer/.test(tool)) return isVerifierInOrg(orgOf(ctx), ev.department) ? "browse" : "self_test";
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
  tool_started: (ev, ctx) => [one(floorTool(ev, ctx), ev, ctx)],
  tool_skipped: (ev, ctx) => [one("tool_denied", ev, ctx)],
  proposal_submitted: (ev, ctx) => [one("submit", ev, ctx)],
  proposal_rejected: (ev, ctx) => [one("rejected", ev, ctx)],
  // 规格或决定被接纳：所在职能盖上有效章，包裹送往关注该成果的下游职能
  spec_accepted: (ev, ctx) => {
    const pair = specTargetPair(ev, orgOf(ctx));
    return [one("stamp_valid", ev, ctx), handoff(ev, pair.from, pair.to, "prd", ctx)];
  },
  contract_accepted: (ev, ctx) => {
    const pair = specTargetPair(ev, orgOf(ctx));
    return [one("stamp_valid", ev, ctx), handoff(ev, pair.from, pair.to, "prd", ctx)];
  },
  product_decision_accepted: (ev, ctx) => {
    const pair = specTargetPair(ev, orgOf(ctx));
    return [one("stamp_valid", ev, ctx), handoff(ev, pair.from, pair.to, "prd", ctx)];
  },
  delivery_accepted: (ev, ctx) => {
    const pair = deliveryTargetPair(ev, orgOf(ctx));
    return [one("seal", ev, ctx), handoff(ev, pair.from, pair.to, "box", ctx)];
  },
  structure_accepted: (ev, ctx) => {
    const pair = deliveryTargetPair(ev, orgOf(ctx));
    return [handoff(ev, pair.from, pair.to, "box", ctx)];
  },
  // 通用成果接纳：无核验角色交完成时在出口托盘盖虚线的开环完成章并送成果库；有核验角色交完成只封存送核验屋；独立核验结论按放行或打回走
  artifact_accepted: (ev, ctx) => {
    const org = orgOf(ctx);
    const p = pl(ev);
    const kind = text(p.artifact_kind);
    const issuer = ev.department || text(p.artifact_issuer) || completingRoleOf(org) || inferEntryIds(org)[0] || "engineering";
    const evWithDept: FloorEvent = { ...ev, department: issuer };
    if (kind === "completion") {
      if (org.verifiers.length === 0) {
        const outsourced = p.outsourced === true || p.verified_external === true;
        return [
          one("stamp_open_loop", evWithDept, ctx, outsourced ? { outsourced: true } : null),
          handoff(evWithDept, issuer, "library", "box", ctx),
        ];
      }
      const target = org.watched.find((w) => w.source === issuer && w.outcome === "completion")?.recipient
        ?? org.verifiers[0]!.role;
      return [one("seal", evWithDept, ctx), handoff(evWithDept, issuer, target, "box", ctx)];
    }
    if (kind === "completion_review") {
      if (p.verdict === "release") {
        return [one("stamp_release", evWithDept, ctx), handoff(evWithDept, issuer, text(p.release_to) || "library", "release", ctx)];
      }
      const pair = qaReworkPair(evWithDept, org);
      return [one("stamp_defect", evWithDept, ctx), handoff(evWithDept, pair.from, pair.to, "defect", ctx)];
    }
    const target = org.watched.find((w) => w.source === issuer && w.outcome === kind)?.recipient
      ?? org.watched.find((w) => w.source === issuer)?.recipient
      ?? "";
    return target
      ? [one("stamp_valid", evWithDept, ctx), handoff(evWithDept, issuer, target, "prd", ctx)]
      : [one("stamp_valid", evWithDept, ctx)];
  },
  // 放行：放行单送往成果库，载荷写明 release_to 时送往那个职能；缺陷记录经回流管道送回打回目标职能
  qa_submitted: (ev, ctx) => {
    const org = orgOf(ctx);
    if (pl(ev).verdict === "release") {
      const from = ev.department || org.verifiers[0]?.role || "quality";
      return [one("stamp_release", ev, ctx), handoff(ev, from, text(pl(ev).release_to) || "library", "release", ctx)];
    }
    const pair = qaReworkPair(ev, org);
    return [one("stamp_defect", ev, ctx), handoff(ev, pair.from, pair.to, "defect", ctx)];
  },
  // 独立判断：核验角色交上自己的判断（先判断后看解释，工单 #358）
  independent_judgement_committed: (ev, ctx) => [one("submit", ev, ctx)],
  ask_started: (ev, ctx) => {
    const spoken = sayAsk(ev, deptLabelOf(orgOf(ctx)));
    return [{
      kind: "letter", position: posOf(ev), item: ev.work_item_id ?? null,
      from: pl(ev).requester ?? null, to: pl(ev).recipient ?? null, answer: false, ...spoken,
    }];
  },
  ask_answered: (ev, ctx) => {
    const spoken = sayAnswer(ev, deptLabelOf(orgOf(ctx)));
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

/** 楼层转交实时内容的事件种类（与 translate/coverage.ts 里楼层的 realtime 是同一组，测试核对两边一致）。 */
export const FLOOR_STREAM_TYPES: readonly string[] = ["model_stream_progress"];

/** 输出片段 → 流式文字；不是输出片段的事件返回 null。 */
export function streamText(ev: FloorEvent): { room: string | null; role: string | null; text: string } | null {
  if (!FLOOR_STREAM_TYPES.includes(ev.type)) return null;
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
// 循环与收敛（工单 #400，原型 v10 设计说明第 3、4 节）：把 run.loops 的结果翻成覆盖层「循环」的数据。
// 判定不在这一层：状态与「缺少的事实」都照着查询结果写。
// 观测页「循环」区块的那些行是页面文字，归页面（views/project/floor-text.ts，工单 #1415）；
// 这里只留画面覆盖层要用的一份状态词。

/** 收敛状态的中文名：五种状态与「不判定」；文字与颜色同时给出，不只靠颜色区分。 */
export const LOOP_STATE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  converging: "收敛中",
  stalled: "停滞",
  oscillating: "震荡",
  drifting: "漂移",
  boundary: "达到边界",
  undetermined: "不判定",
});

export function loopStateLabel(state: string): string {
  return LOOP_STATE_LABELS[state] ?? state;
}

function loopLayer(loops: RunLoopsResult, name: string): LoopLayer | undefined {
  return loops.layers.find((layer) => layer.name === name);
}

function workSteps(activation: LoopActivation): number {
  // 工作步：压缩步不是工作步（与步骤层的判定口径一致）
  return activation.steps.filter((step) => step.purpose !== "compaction").length;
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

// ---------------------------------------------------------------------------
// 检验覆盖（工单 #1420，画面与播放 docs/design/visualization.md「七种元件与对照表」「开环完成与放行」、
// 验证的独立性 docs/design/independent-verification.md「口径」）：
// 把 acceptance.coverage 的结果翻成覆盖层「检验」的数据。
// 覆盖比例、可执行条数、已覆盖条数、模型阅读条数与开环条件条数原样读取查询的 numbers，翻译层不重新计算。
// 验收条件一级的未核验项写「开环条件」与「开环 N 条」，与事项结束方式的记号分开。

/** 单条验收条件核验结果的中文名。 */
export const COVERAGE_RESULT_LABELS: Readonly<Record<CoverageResult, string>> = Object.freeze({
  passed: "通过",
  failed: "不通过",
  unverified: "未核验",
});

export function coverageResultLabel(result: string): string {
  return (COVERAGE_RESULT_LABELS as Readonly<Record<string, string>>)[result] ?? result;
}

export function checkMethodLabel(method: string): string {
  return CHECK_METHODS[method]?.label ?? method;
}

/** 覆盖层「检验」的数据：顶部横幅写检验覆盖比例与开环条件条数，逐条写检验方式与结果，右上角写计数图例。 */
export function coverageOverlay(coverage: AcceptanceCoverageResult | null): CoverageOverlayData {
  if (coverage === null) {
    const legend: CoverageLegendRow[] = [
      ...COVERAGE_RESULTS.map((result) => ({
        key: result,
        label: COVERAGE_RESULT_LABELS[result],
        count: 0,
        text: `${COVERAGE_RESULT_LABELS[result]} 0`,
      })),
      { key: "open", label: "开环条件", count: 0, text: "开环 0 条" },
    ];
    return {
      bar: {
        text: "还没有检验覆盖记录",
        coverage_ratio: 0,
        covered: 0,
        criteria_total: 0,
        executable: 0,
        open: 0,
        model_reading: 0,
      },
      criteria: [],
      legend,
    };
  }
  const numbers = coverage.numbers;
  const pct = Math.round(numbers.coverage_ratio * 100);
  const modelReadingNote = numbers.model_reading > 0 ? `（含模型阅读 ${numbers.model_reading} 条）` : "";
  const barText = `检验覆盖 ${pct}%（${numbers.covered}/${numbers.criteria_total}）· 开环条件 ${numbers.open} 条${modelReadingNote}`;
  const openSet = new Set(coverage.open_criteria ?? []);
  const criteria: CoverageOverlayCriterion[] = coverage.criteria.map((row) => {
    const methodLabel = checkMethodLabel(row.method);
    const resultLabel = coverageResultLabel(row.result);
    const isOpen = row.open || openSet.has(row.criterion);
    const openSuffix = isOpen ? " · 开环条件" : "";
    return {
      criterion: row.criterion,
      method: row.method,
      method_label: methodLabel,
      result: row.result,
      result_label: resultLabel,
      executable: row.executable && !openSet.has(row.criterion),
      open: isOpen,
      text: `${row.criterion} · ${methodLabel} · ${resultLabel}${openSuffix}`,
    };
  });
  const legend: CoverageLegendRow[] = [
    ...COVERAGE_RESULTS.map((result) => {
      const labelText = COVERAGE_RESULT_LABELS[result];
      const count = criteria.filter((item) => item.result === result).length;
      return { key: result, label: labelText, count, text: `${labelText} ${count}` };
    }),
    {
      key: "open",
      label: "开环条件",
      count: numbers.open,
      text: `开环 ${numbers.open} 条`,
    },
  ];
  return {
    bar: {
      text: barText,
      coverage_ratio: numbers.coverage_ratio,
      covered: numbers.covered,
      criteria_total: numbers.criteria_total,
      executable: numbers.executable,
      open: numbers.open,
      model_reading: numbers.model_reading,
    },
    criteria,
    legend,
  };
}
