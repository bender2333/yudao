// 页面自己的状态文字、颜色、覆盖层名、循环行与页面事实的行（画面与播放设计说明「搬出：画面成为单独的应用」的
// 「先补页面」：页面自己用的文字与颜色归页面，不从画面取；工单 #1415、#1416）。
//
// 页面在页面上看的这几样各留一份，不从画面（pixel/）与翻译层（translate/）取；画面那边要用的文字自己
// 留一份（translate/face.ts），两份文字不互相引用：改这里不动画面，改画面也不动这里。
//
// 部门状态的文字（角色条上那一格用的 STATUS_TEXT）在 ./labels.ts：roleBarText 在那里，与本文件同属
// 页面的文字，本文件按页面内部的方向引用它，不反向引用，免得两份页面文字互相导入。
//
// 挂画布的几个组件（project/floor-screen.tsx、project/room-screen.tsx、home/building-section.tsx）里的
// 画布接线仍要导入画面与翻译层，那几行留给搬画布的工单；本文件只放页面文字与颜色。
//
// 工单 #1416 起，首页项目一览与项目页的部门、中断、流转汇总、事实来源各节的行也从这里取：原来只在画布上
// 看得到的事实，先在页面上有对应的列表与详情。这些行只读查询结果，不碰画布与翻译层。

import type {
  AskView, DecisionView, FlowRecord, LoopActivation, LoopAmount, LoopLayer, ProjectLoopResult, RunLoopsResult,
} from "../../api/generated/types.gen.ts";
import { DEPARTMENT_STATE, RECOVERY_STATE, departmentName, formatDuration, label, STOP_REASON } from "./labels.ts";

// ---------------------------------------------------------------------------
// 颜色

/**
 * 资料页事项卡片的颜色（原来取自 pixel/registry.ts 的 ITEM_COLORS）：六种，按事项序号轮换，
 * 卡片左侧的色条与画面上的成果同一个颜色。画面上另一份色板（pixel/world/floor.ts）是画布用的，
 * 两者取值不同，页面上这份照原样留。
 */
export const ITEM_COLORS: readonly string[] = Object.freeze([
  "#e8505b", "#f7c948", "#3fc1e8", "#f27ec2", "#8fd14f", "#b98558",
]);

/** 事项列表色点用的色板（原来取自 pixel/world/floor.ts 的 ITEM_COLORS）：与门口小旗、包裹同一种颜色。 */
const DOT_COLORS: readonly string[] = Object.freeze([
  "#d9534f", "#4a90d9", "#5cb85c", "#f0ad4e", "#9b59b6", "#e67e22",
]);

/** 事项的颜色序号到色点：序号超出色板时轮换（原来取自 pixel/world/floor.ts 的 itemColor）。 */
export function itemColor(item: { color_index?: number }): string {
  return DOT_COLORS[(Number(item.color_index) || 0) % DOT_COLORS.length];
}

/**
 * 首页楼下列表的楼层状态词与配色（原来取自 pixel/building/status-text.ts 的 BUILDING_STATUS）：
 * 状态灯的取值就是画面合同 FLOOR_SIGNS 的八个，取值不在表里时调用处按原样写。
 */
export const BUILDING_STATUS: Readonly<Record<string, { text: string; color: string }>> = Object.freeze({
  working: { text: "运行中", color: "#3fbf66" },
  queued: { text: "排队中", color: "#9aa2b0" },
  waiting_slot: { text: "等待执行槽位", color: "#f08a3c" },
  waiting_model: { text: "等待模型服务", color: "#6b7382" },
  waiting_resume: { text: "待恢复", color: "#f7cb46" },
  waiting_user: { text: "等待你的决定", color: "#f7cb46" },
  interrupted: { text: "中断", color: "#474d5a" },
  idle: { text: "空闲", color: "#9aa2b0" },
});

// ---------------------------------------------------------------------------
// 覆盖层

/**
 * 覆盖层按钮上的中文名（原来取自 translate/coverage.ts 的 OVERLAY_LABELS）：页面按能力清单的
 * overlays 挑出按钮条上出现哪几个，没有中文名的覆盖层不出现按钮。
 */
export const OVERLAY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  flow: "流转",
  waiting: "等待",
  recovery: "恢复",
  context_usage: "上下文用量",
  semantic_records: "语义记录",
  sources: "来源",
  loops: "循环",
});

// ---------------------------------------------------------------------------
// 循环与收敛的行（工单 #400）：观测页的「循环」区块用这里的函数把 run.loops 的结果写成表。
// 判定不在页面这一层：状态、已用量与「缺少的事实」都照着查询结果写。

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

/** 一个已用量与上限的文字：不设上限时写「不设上限」，数值照写（docs/design/loops-and-convergence.md「收敛的检测」末）。 */
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

// ---------------------------------------------------------------------------
// 事项的已用时间与上限（原来只有进行中的事项与部门页的单个事项）
//
// 读 project.loop 的 elapsed_sec 与 time_limit_sec，与恢复页「已用时间与时间上限」同一个查询、同一对字段、
// 同一种写法；没有进行中的事项或者查询还没有数据时是「—」。工单 #1416 把它挪到这里，项目页与部门页共用。

export function elapsedLimitText(item: {
  status: string;
  elapsed_sec: number | null;
  time_limit_sec: number;
} | null): string {
  if (item === null || item.status !== "in_progress" || item.elapsed_sec === null) {
    return "—";
  }
  return `${formatDuration(item.elapsed_sec)} / ${formatDuration(item.time_limit_sec)}`;
}

// ---------------------------------------------------------------------------
// 首页项目一览（工单 #1416）：原来只在楼的画布上看到的三样事实。
//
// 每个项目一行，写「此刻在做什么」「事项在哪个部门」「执行槽位」。数据只来自 projects.list 与
// project.loop 的 work_items；部门名取项目组织给出的显示名，旧数据里的部门用页面上原来的写法。

/** 还没有结束的事项（与看板的固定分组同一口径）。 */
const FINISHED_ITEM_STATUSES: ReadonlySet<string> = new Set(["adopted", "released_unsettled", "stopped"]);

function departmentLabelOf(department: string, labels: Record<string, string>): string {
  return labels[department] ?? departmentName(department);
}

/**
 * 一个事项的部门显示名：事项冻结的组织里的角色名优先（工单 #1457 的口径），没有时用调用处给的
 * 项目现在的组织，最后退回页面上原来的写法。这样换了部门名的定义时页面也不写部门标识。
 */
function labelsOfItem(item: { organization?: { roles: { id: string; label: string }[] } | null },
                      labels: Record<string, string>): Record<string, string> {
  const merged = { ...labels };
  for (const role of item.organization?.roles ?? []) {
    if (!(role.id in merged)) {
      merged[role.id] = role.label;
    }
  }
  return merged;
}

/**
 * 此刻在做什么：正在工作的部门与它们的状态词（等待工作不算在做），一个部门一行，部门之间用「；」分开。
 * 几个事项同时有部门在工作时同一部门只写一次。没有部门在工作时写「没有在做的事」。
 */
export function projectDoingText(loop: ProjectLoopResult | null, labels: Record<string, string> = {}): string {
  const lines: string[] = [];
  for (const item of loop?.work_items ?? []) {
    const itemLabels = labelsOfItem(item, labels);
    for (const [department, state] of Object.entries(item.departments ?? {})) {
      if (state.state === "waiting") {
        continue;
      }
      const text = DEPARTMENT_STATE[state.state] ?? state.state;
      const note = state.note ? `（${state.note}）` : "";
      lines.push(`${departmentLabelOf(department, itemLabels)}：${text}${note}`);
    }
  }
  const unique = [...new Set(lines)];
  return unique.length === 0 ? "没有在做的事" : unique.join("；");
}

/**
 * 事项在哪个部门：还没有结束的事项一行一个，写事项标题与所在部门；还没有交给部门的事项写「排队」。
 * 没有进行中的事项时写「没有进行中的事项」。
 */
export function projectItemsByDepartmentText(loop: ProjectLoopResult | null, labels: Record<string, string> = {}): string {
  const live = (loop?.work_items ?? []).filter((item) => !FINISHED_ITEM_STATUSES.has(item.status));
  if (live.length === 0) {
    return "没有进行中的事项";
  }
  return live.map((item) => `${item.sign} · ${item.department === null || item.department === ""
    ? "排队"
    : departmentLabelOf(item.department, labelsOfItem(item, labels))}`).join("；");
}

/**
 * 执行槽位：正在执行几个事项、几个在等。现在一次只执行一个事项（并行要等 #19），排队中的事项
 * 就是在等执行槽位；两类各写一个数，都不写「已等」的时长（查询没有记排队的时间）。
 */
export function projectSlotText(loop: ProjectLoopResult | null): string {
  const items = loop?.work_items ?? [];
  const running = items.filter((item) => item.status === "in_progress").length;
  const waiting = items.filter((item) => item.status === "not_started" || item.status === "held").length;
  const head = running === 0 ? "没有事项正在执行" : `${running} 个事项正在执行`;
  const tail = waiting === 0 ? "没有事项在等执行槽位" : `${waiting} 个事项在等执行槽位`;
  return `${head}，${tail}`;
}

// ---------------------------------------------------------------------------
// 项目页：各部门在等什么、等了多久（工单 #1416）
//
// 行来自 project.loop 的 departments（事项所用的定义给出的部门、状态与原因），「等了多久」取两处精确的
// 事实：询问进行中时取这次询问的开始时间（run.asks 的 started_at），等用户时取决定请求的发出时间
// （decisions.list 的 requested_at）；其余状态查询没有记等待的起点，这一格留空（页面写「—」），由这一节的
// 说明写清口径。已用时间与上限另取本事项的 elapsed_sec 与 time_limit_sec。

export interface DepartmentFactView {
  itemId: string;
  itemTitle: string;
  /** 部门的标识：点部门名去部门页用 */
  departmentId: string;
  /** 部门的显示名 */
  department: string;
  /** 状态词（不含原因） */
  state: string;
  /** 原因：状态词后面的那一句，没有时为空串 */
  note: string;
  /** 在等什么；不在等或者没有说明时为空串 */
  waiting: string;
  /** 等了多久；没有可以算起点的事实时为空串 */
  waited: string;
  /** 本事项的已用时间与上限 */
  elapsed: string;
}

/** 从现在到一条事实的时间，写成页面的时长；事实的时间缺失或读不出来时返回空串。 */
export function waitedText(since: string | null | undefined, now: number): string {
  if (!since) {
    return "";
  }
  const started = new Date(since).getTime();
  if (Number.isNaN(started)) {
    return "";
  }
  return formatDuration(Math.max(0, Math.round((now - started) / 1000)));
}

/** 一个部门在这种状态下在等什么（没有原因时按状态给出页面上的说法；工作中没有在等）。 */
function waitingOf(state: string, note: string): string {
  if (note !== "") {
    return note;
  }
  if (state === "asking") {
    return "等对方回答";
  }
  if (state === "waiting_user") {
    return "等你回答决定请求";
  }
  if (state === "verifying") {
    return "等核验结论";
  }
  if (state === "waiting") {
    return "等关注的成果出新版本";
  }
  return "";
}

/** 部门等待的起点：这个部门发出、还在进行的询问，或者这个事项上等待回答的决定请求。 */
function waitingSince(input: {
  itemId: string;
  department: string;
  state: string;
  asks: AskView[] | null | undefined;
  decisions: DecisionView[] | null | undefined;
}): string | null {
  if (input.state === "asking") {
    // 询问中的部门是发出询问、在等对方回答的那一方
    const ask = (input.asks ?? []).find(
      (row) => row.status === "进行中" && row.requester === input.department);
    return ask?.started_at ?? null;
  }
  if (input.state === "waiting_user") {
    const pending = (input.decisions ?? [])
      .filter((row) => row.status === "open" && row.work_item_id === input.itemId)
      .map((row) => row.requested_at)
      .sort();
    return pending[0] ?? null;
  }
  return null;
}

/**
 * 各部门在等什么、等了多久：每个进行中的事项的每个部门一行（定义里的部门顺序）。
 * asks 是当前这次运行的询问（run.asks），decisions 是等待回答的决定请求（decisions.list）；
 * 两处没有给时只写状态与原因。
 */
export function departmentFactRows(input: {
  loop: ProjectLoopResult | null;
  asks?: AskView[] | null;
  decisions?: DecisionView[] | null;
  labels?: Record<string, string>;
  now: number;
}): DepartmentFactView[] {
  const labels = input.labels ?? {};
  const rows: DepartmentFactView[] = [];
  for (const item of input.loop?.work_items ?? []) {
    if (item.status !== "in_progress") {
      continue;
    }
    const itemLabels = labelsOfItem(item, labels);
    for (const [department, state] of Object.entries(item.departments ?? {})) {
      const since = waitingSince({
        itemId: item.work_item_id, department, state: state.state,
        asks: input.asks, decisions: input.decisions,
      });
      rows.push({
        itemId: item.work_item_id,
        itemTitle: item.sign,
        departmentId: department,
        department: departmentLabelOf(department, itemLabels),
        state: DEPARTMENT_STATE[state.state] ?? state.state,
        note: state.note ?? "",
        waiting: waitingOf(state.state, state.note ?? ""),
        waited: since === null ? "" : waitedText(since, input.now),
        elapsed: elapsedLimitText(item),
      });
    }
  }
  return rows;
}

// ---------------------------------------------------------------------------
// 项目页：中断与待恢复（工单 #1416）
//
// 一整个项目里被打断、等待恢复的事项，一行一个；恢复页按事项看细节，这一节给出有哪些、属于谁。

export interface InterruptionFactView {
  itemId: string;
  itemTitle: string;
  department: string;
  /** 中断或者待恢复 */
  state: string;
  elapsed: string;
}

export function interruptionFactRows(loop: ProjectLoopResult | null, labels: Record<string, string> = {}): InterruptionFactView[] {
  const rows: InterruptionFactView[] = [];
  for (const item of loop?.work_items ?? []) {
    const recovery = item.recovery_state ?? null;
    if (recovery !== "interrupted" && recovery !== "waiting_resume") {
      continue;
    }
    rows.push({
      itemId: item.work_item_id,
      itemTitle: item.sign,
      department: item.department === null || item.department === ""
        ? "大厅"
        : departmentLabelOf(item.department, labelsOfItem(item, labels)),
      state: RECOVERY_STATE[recovery] ?? recovery,
      elapsed: elapsedLimitText(item),
    });
  }
  return rows;
}

// ---------------------------------------------------------------------------
// 项目页：流转汇总（每对部门的次数与返工；工单 #1416）
//
// 逐条记录在「流转记录」里；这里按方向汇总：从哪个部门到哪个部门几次、其中几次是返工（质检退回的
// 「问题反馈」，状态是「已退回」）、都是些什么。种类按成果命名，记录里已经是中文。

export interface FlowPairView {
  from: string;
  to: string;
  count: number;
  rework: number;
  kinds: string;
}

export function flowPairRows(records: FlowRecord[] | null | undefined, labels: Record<string, string> = {}): FlowPairView[] {
  const order: string[] = [];
  const pairs = new Map<string, FlowPairView & { kindsOf: Map<string, number> }>();
  for (const record of records ?? []) {
    const from = record.direction_from === null || record.direction_from === ""
      ? "没有"
      : departmentLabelOf(record.direction_from, labels);
    const to = record.direction_to === null || record.direction_to === ""
      ? "没有"
      : departmentLabelOf(record.direction_to, labels);
    const key = `${from}>${to}`;
    let pair = pairs.get(key);
    if (pair === undefined) {
      pair = { from, to, count: 0, rework: 0, kinds: "", kindsOf: new Map<string, number>() };
      pairs.set(key, pair);
      order.push(key);
    }
    pair.count += 1;
    if (record.status === "已退回") {
      pair.rework += 1;
    }
    pair.kindsOf.set(record.kind, (pair.kindsOf.get(record.kind) ?? 0) + 1);
  }
  return order.map((key) => {
    const pair = pairs.get(key)!;
    return {
      from: pair.from,
      to: pair.to,
      count: pair.count,
      rework: pair.rework,
      kinds: [...pair.kindsOf.entries()].map(([kind, count]) => `${kind} ${count}`).join("、"),
    };
  });
}

// ---------------------------------------------------------------------------
// 项目页：事实元素与它们的来源（工单 #1416）
//
// 门牌、轮次、已用时间、包裹、盖章、成果库的箱子各是一样事实元素，查询（project.loop 的 refs）给出它的
// 全局位置与来源种类。页面上每样一行，写来源种类；点开按位置读那条原始事件（event.positions），并回到
// 时间轴上同一个位置。元素名与来源种类是页面自己的说法，不从画面取。

/** 事实元素的页面名称；顺序就是页面上的顺序。 */
export const FACT_ELEMENT_LABELS: Readonly<Record<string, string>> = Object.freeze({
  sign: "门牌",
  round: "轮次",
  elapsed: "已用时间",
  parcel: "包裹",
  stamp: "盖章",
  box: "成果库的箱子",
});

/** 事实元素的页面顺序：门牌、包裹、章、箱子、轮次、已用时间；没有登记的元素排在后面（按查询给的键排序）。 */
export const FACT_ELEMENT_ORDER: readonly string[] = Object.freeze([
  "sign", "parcel", "stamp", "box", "round", "elapsed",
]);

/** 来源种类的页面名称（画面合同与接口合同的五种取值）。 */
export const SOURCE_KIND_LABELS: Readonly<Record<string, string>> = Object.freeze({
  rule: "规则",
  decision_model: "模型判断",
  role_statement: "角色陈述",
  host_measurement: "主机测量",
  user: "用户",
});

/**
 * 事件种类的中文名（来源详情写「种类」一行，页面不出现英文内部标识）。页面自己的一份：画面那边
 * （translate/floor.ts）也有一份，两份不互相引用。覆盖 client/tests/fixtures/event-types.json 里的
 * 每一种事件，缺一行由单元测试报出。
 */
export const EVENT_KIND_LABELS: Readonly<Record<string, string>> = Object.freeze({
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
  dispatch_number_acquired: "取得派发编号",
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
  mcp_server_closed: "关闭 MCP 服务器",
  mcp_server_failed: "MCP 服务器启动失败",
  mcp_server_started: "启动 MCP 服务器",
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
  project_form_set: "修改项目的形态",
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
  independent_judgement_committed: "提交独立判断",
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
  trial_case_concluded: "结束试用用例",
  trial_case_opened: "打开试用用例",
  trial_session_ended: "结束试用会话",
  trial_session_started: "开始试用会话",
  user_input_received: "收到用户输入",
  work_item_created: "建立事项",
  work_item_start_failed: "事项未能开始",
  writeback_completed: "写回完成",
  writeback_held: "写回等待前项",
  writeback_not_needed: "无需写回",
  writeback_stopped: "写回停止",
  writeback_verified: "写回已核实",
});

/** 一种事件的中文名：没有登记的种类写「其他事件」，不把英文内部标识写到页面上。 */
export function eventKindLabel(type: string | null | undefined): string {
  return EVENT_KIND_LABELS[(type ?? "").trim()] ?? "其他事件";
}

/** 按位置取事件失败的原因（接口合同的四种），页面上写中文。 */
export const EVENT_POSITION_REASONS: Readonly<Record<string, string>> = Object.freeze({
  not_in_stream: "这个位置上是另一个流的事件",
  out_of_range: "位置超出事件日志的范围",
  archived: "更早的事件已经搬走",
  compacted: "这个位置上没有事件",
});

export interface FactElementView {
  workItemId: string;
  itemTitle: string;
  /** 事项的这一次运行：按位置读事件时带上它，run 流里的位置才取得到 */
  runId: string;
  element: string;
  elementLabel: string;
  source: string;
  sourceLabel: string;
  position: number;
}

export function factElementRows(loop: ProjectLoopResult | null): FactElementView[] {
  const rows: FactElementView[] = [];
  for (const item of loop?.work_items ?? []) {
    const refs = item.refs ?? {};
    const keys = Object.keys(refs);
    const ordered = [
      ...FACT_ELEMENT_ORDER.filter((element) => keys.includes(element)),
      ...keys.filter((element) => !FACT_ELEMENT_ORDER.includes(element)).sort(),
    ];
    for (const element of ordered) {
      const ref = refs[element];
      rows.push({
        workItemId: item.work_item_id,
        itemTitle: item.sign,
        runId: item.run_id,
        element,
        elementLabel: FACT_ELEMENT_LABELS[element] ?? element,
        source: ref.source,
        sourceLabel: SOURCE_KIND_LABELS[ref.source] ?? ref.source,
        position: ref.position,
      });
    }
  }
  return rows;
}

// ---------------------------------------------------------------------------
// 部门页：实时的模型输出（工单 #1416）
//
// 与部门房间的思考气泡同一条规则（画面与播放设计说明「实时内容」）：同一个通道只收 output；同一个偏移只接
// 一次，与已经接上的文字重叠的片段丢弃；换一次调用尝试时从空字符串开始。查询 attempt.live 给出的已有文字
// 作为起点，已经接上的片段更长时保留。
//
// 这里只做拼接规则，不接触网络：部门页订阅事件流与片段，把结果交给它。

export interface LiveOutputView {
  attemptId: string;
  text: string;
}

/** 开始观察一次调用尝试：换了尝试就从空字符串开始。 */
export function liveOutputObserve(current: LiveOutputView | null, attemptId: string): LiveOutputView {
  if (current !== null && current.attemptId === attemptId) {
    return current;
  }
  return { attemptId, text: "" };
}

/** 以 attempt.live 已收到的文字作为起点：已经接上的片段更长时保留。 */
export function liveOutputSeed(current: LiveOutputView | null, attemptId: string, live: string): LiveOutputView {
  const observed = liveOutputObserve(current, attemptId);
  return live.length >= observed.text.length ? { attemptId, text: live } : observed;
}

/**
 * 收下一条模型输出片段：只有 output 通道、offset 不小于已有字数的片段才接上。
 * 返回 null 表示这条片段不接（重叠、别的通道、别的尝试）。
 */
export function liveOutputAbsorb(
  current: LiveOutputView | null,
  delta: { attemptId: string; channel: string; offset: number; text: string },
): LiveOutputView | null {
  if (delta.channel !== "output") {
    return null;
  }
  const observed = current === null ? { attemptId: delta.attemptId, text: "" } : current;
  if (observed.attemptId !== delta.attemptId) {
    return null;
  }
  if (delta.offset < observed.text.length) {
    return null;
  }
  return { attemptId: observed.attemptId, text: observed.text + delta.text };
}
