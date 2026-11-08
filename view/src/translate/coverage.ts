// 翻译覆盖与缺口清单（画面与播放 docs/design/visualization.md「翻译层」「缺口清单」与「画面诚实性的不变式」最后一行、原型 v13 js/translate/translate.js 的 T.coverage，工单 #952、#1419）。
//
// 能力清单里的每种事件，在楼、楼层、房间三个场景里各属于一类：
//   drawn    —— 翻成这个场景的动作；
//   realtime —— 作为实时内容转交（决定卡片、流式文字），不进播放时间线；
//   none     —— 这个场景不画，写一句理由。
// 事件种类取自接口：运行时是能力清单的 event_types（view/src/shell.ts），测试里是同一份接口描述
// （harness/tests/openapi/openapi.json）；服务端不为画面维护事件种类的清单或夹具。
// 还没归类的事件不画，列进缺口清单：新增一种事件只让缺口清单多一行，不让测试失败；缺口清单可以不为空，
// 测试只核对它和实际画出来的东西一致（docs/design/visualization.md「缺口清单」）。
//
// 事件种类与原型 v13 的 translate.js 用的是同一套服务端的词（真实系统的事件在 harness/models.py）。
// 原型里只有原型才有的 x_ 前缀事件没有搬；真实系统新增、原型没有的事件按同样的口径归类（见每条的理由）。
// 画面 3 至 5 把这里的 drawn 落成各场景的动作表，realTime 落成流式文字；改了归属要同时改这里。

/** 一个场景里的一种归属。 */
export type CoverageClass = "drawn" | "realtime" | "none";

/** 一个场景的覆盖：翻成动作的、转交实时内容的、不画的（每种「不画」写一句理由）。 */
export interface SceneCoverage {
  readonly drawn: readonly string[];
  readonly realtime: readonly string[];
  readonly none: Readonly<Record<string, string>>;
}

/** 三个场景的覆盖。 */
export interface TranslationCoverage {
  readonly floor: SceneCoverage;
  readonly room: SceneCoverage;
  readonly building: SceneCoverage;
}

export const SCENES = ["floor", "room", "building"] as const;
export type Scene = (typeof SCENES)[number];

// 「不画」的理由：同一类事件用同一句话（与原型 v13 的四类理由一致，另加真实系统里新出现的几类）
const STATE_ONLY = "由状态表示，没有一次性的动作";
const HALL = "发生在大厅、成果库或运维的修复流程里，部门房间里没有对应物（楼层上画）";
const DEPT_DETAIL = "部门内部的细节只在部门房间里演，楼层上没有这些陈设";
const TOO_SMALL = "部门里的进度与细节：楼太小，只看哪个房间亮灯";
const PAGE_ONLY = "只在页面文字里（资料、恢复、设置与动作回执），画面里没有对应物";
const SETTINGS = "设置与登记的修改，画面里没有对应物；改变了的事实由下一份状态给出";
const CATALOG = "模型目录的变化，不属于项目的画面";
const PROJECT_LIST = "项目的登记、改名、置顶、归档与恢复：楼的层数、名牌与顺序由状态给出";
const DECISIONS = "决定单在楼层大厅的板上来回，房间里不画";
const WITHDRAWN = "撤回的决定请求从实时的决定卡片里去掉";
const INTERNAL = "部门对话与模型输入的记录，画面里没有一次性的动作";
const MODEL_IO = "模型读入写出的记录，由下一份状态与流式文字给出";
const QA_TESTS = "测试用例的保存由房间的卷轴与下一份状态给出，没有一次性的动作";

const none = (reasons: Record<string, string>): Record<string, string> => Object.freeze({ ...reasons });

/** 三个场景共同的「不画」理由：项目登记、设置、目录与实例级的事实。 */
const COMMON: Readonly<Record<string, string>> = none({
  project_registered: PROJECT_LIST,
  project_renamed: PROJECT_LIST,
  project_goal_changed: PROJECT_LIST,
  project_pinned: PROJECT_LIST,
  project_archived: PROJECT_LIST,
  project_restored: PROJECT_LIST,
  department_prompt_configured: SETTINGS,
  material_recorded: SETTINGS,
  source_directory_configured: SETTINGS,
  // 项目设置里的 MCP 服务器（工单 #236）：与源目录登记同一类设置修改
  mcp_servers_configured: SETTINGS,
  // 探测 MCP 服务器（工单 #1174）：结果由 project.settings 的探测一节与工具快照给出
  tool_server_probe_finished: SETTINGS,
  // MCP 服务器的生命周期（工单 #1176）：启动、关闭与启动失败由工具页与动作回执给出，画面里没有对应物
  mcp_server_started: PAGE_ONLY,
  mcp_server_closed: PAGE_ONLY,
  mcp_server_failed: PAGE_ONLY,
  // 试用会话的开始与结束（工单 #1183）：会话与试用副本由动作回执与试用记录给出，画面里没有对应物
  trial_session_started: PAGE_ONLY,
  trial_session_ended: PAGE_ONLY,
  // 试用用例的开始与结束（工单 #1180）：用例、步骤与结论由试用记录与放行记录给出，画面里没有对应物
  trial_case_opened: PAGE_ONLY,
  trial_case_concluded: PAGE_ONLY,
  project_parameter_set: SETTINGS,
  home_seen: SETTINGS,
  parameter_set: SETTINGS,
  catalog_revised: CATALOG,
  catalog_candidates_collected: CATALOG,
  catalog_test_finished: CATALOG,
  credential_changed: CATALOG,
  writeback_completed: PAGE_ONLY,
  writeback_stopped: PAGE_ONLY,
  writeback_not_needed: PAGE_ONLY,
  writeback_held: PAGE_ONLY,
  writeback_verified: PAGE_ONLY,
  onboarding_revision_started: PAGE_ONLY,
  runtime_drain_started: PAGE_ONLY,
  runtime_drain_finished: PAGE_ONLY,
  runtime_force_upgrade_requested: PAGE_ONLY,
  instance_upgrade_requested: PAGE_ONLY,
  instance_upgrade_answered: PAGE_ONLY,
  instance_upgrade_withdrawn: PAGE_ONLY,
  // 项目的形态（工单 #1392）：与项目参数同一类设置修改，画面里没有对应物
  project_form_set: SETTINGS,
  decision_withdrawn: WITHDRAWN,
  project_decision_withdrawn: WITHDRAWN,
});

/** 楼层：翻成动作的事件种类（画面 3 按 v13 的 FLOOR 表落成动作）。 */
const FLOOR_DRAWN: readonly string[] = [
  "user_input_received",
  "work_item_created",
  "department_activated",
  "department_guidance_received",
  "department_guidance_applied",
  "department_guidance_responded",
  "context_assembled",
  "model_request_serialized",
  "model_requested",
  "model_attempt_finished",
  "model_attempt_failed",
  "model_retry_scheduled",
  "tool_started",
  "tool_skipped",
  "proposal_submitted",
  "proposal_rejected",
  "spec_accepted",
  "contract_accepted",
  "product_decision_accepted",
  "delivery_accepted",
  "structure_accepted",
  "qa_submitted",
  "independent_judgement_committed",
  "ask_started",
  "ask_answered",
  "compaction_recorded",
  "compaction_failed",
  "run_paused",
  "run_failed",
  "run_done",
  "run_resumed",
  "run_continued",
  "decision_requested",
  "decision_answered",
  "project_decision_requested",
  "project_decision_answered",
  "deliverable_adopted",
  "baseline_adopted",
];

/** 楼层：转交实时内容的事件种类（流式文字）。 */
const FLOOR_REALTIME: readonly string[] = ["model_stream_progress"];

const FLOOR_NONE: Readonly<Record<string, string>> = none({
  ...COMMON,
  run_created: STATE_ONLY,
  product_input_assigned: STATE_ONLY,
  department_input: INTERNAL,
  tool_call_required: INTERNAL,
  activation_finished: STATE_ONLY,
  // 派发编号（骨架事件，工单 #1397）：一轮工作开始时的编号，由下一份状态表示，没有一次性的动作
  dispatch_number_acquired: STATE_ONLY,
  model_reasoning: MODEL_IO,
  model_message: MODEL_IO,
  action_verified: PAGE_ONLY,
  spec_superseded: STATE_ONLY,
  qa_tests_saved: DEPT_DETAIL,
  baseline_review_accepted: STATE_ONLY,
  lesson_candidate_recorded: STATE_ONLY,
  work_item_start_failed: STATE_ONLY,
  adoption_held: STATE_ONLY,
  initial_prd_proposed: STATE_ONLY,
  tool_called: STATE_ONLY,
  // 成果失效（骨架事件，S1b，工单 #858）：失效以后「当前交付」由下一份状态给出，没有一次性的动作
  artifact_invalidated: STATE_ONLY,
  // 通用的成果接纳（骨架事件，S2c，工单 #1098）：新种类的成果由下一份状态给出，没有一次性的动作
  artifact_accepted: STATE_ONLY,
});

/** 房间：翻成动作的事件种类（画面 4 按 v13 的 ROOM 表落成动作）。 */
const ROOM_DRAWN: readonly string[] = [
  "department_activated",
  "department_guidance_received",
  "department_guidance_applied",
  "department_guidance_responded",
  "context_assembled",
  "model_request_serialized",
  "model_requested",
  "model_attempt_finished",
  "model_attempt_failed",
  "model_retry_scheduled",
  "tool_started",
  "tool_called",
  "tool_skipped",
  "proposal_submitted",
  "proposal_rejected",
  "spec_accepted",
  "contract_accepted",
  "product_decision_accepted",
  "delivery_accepted",
  "structure_accepted",
  "qa_submitted",
  "independent_judgement_committed",
  "ask_started",
  "ask_answered",
  "compaction_recorded",
  "compaction_failed",
  "run_paused",
  "run_failed",
  "run_done",
  "run_resumed",
  "run_continued",
  "decision_requested",
];

/** 房间：转交实时内容的事件种类（流式文字）。 */
const ROOM_REALTIME: readonly string[] = ["model_stream_progress"];

const ROOM_NONE: Readonly<Record<string, string>> = none({
  ...COMMON,
  run_created: STATE_ONLY,
  product_input_assigned: HALL,
  department_input: INTERNAL,
  tool_call_required: INTERNAL,
  activation_finished: STATE_ONLY,
  // 派发编号（骨架事件，工单 #1397）：一轮工作开始时的编号，由下一份状态表示，没有一次性的动作
  dispatch_number_acquired: STATE_ONLY,
  model_reasoning: MODEL_IO,
  model_message: MODEL_IO,
  action_verified: PAGE_ONLY,
  spec_superseded: STATE_ONLY,
  qa_tests_saved: QA_TESTS,
  baseline_review_accepted: STATE_ONLY,
  lesson_candidate_recorded: STATE_ONLY,
  user_input_received: HALL,
  work_item_created: HALL,
  work_item_start_failed: HALL,
  deliverable_adopted: HALL,
  adoption_held: HALL,
  initial_prd_proposed: HALL,
  baseline_adopted: HALL,
  decision_answered: STATE_ONLY,
  project_decision_requested: DECISIONS,
  project_decision_answered: STATE_ONLY,
  // 成果失效（骨架事件，S1b，工单 #858）：房间里挂着的交付换成失效状态，由状态表示
  artifact_invalidated: STATE_ONLY,
  // 通用的成果接纳（骨架事件，S2c，工单 #1098）：新种类的成果由下一份状态给出，没有一次性的动作
  artifact_accepted: STATE_ONLY,
});

/** 楼：翻成动作的事件种类（画面 5 按 v13 的 BUILDING 表落成闪光与包裹）。 */
const BUILDING_DRAWN: readonly string[] = [
  "department_activated",
  "ask_started",
  "ask_answered",
  "qa_submitted",
  "independent_judgement_committed",
  "deliverable_adopted",
  "baseline_adopted",
  "decision_requested",
  "decision_answered",
  "project_decision_requested",
  "project_decision_answered",
];

/** 楼：转交实时内容的事件种类（楼没有实时内容）。 */
const BUILDING_REALTIME: readonly string[] = [];

const BUILDING_NONE: Readonly<Record<string, string>> = none({
  ...COMMON,
  run_created: STATE_ONLY,
  user_input_received: STATE_ONLY,
  product_input_assigned: STATE_ONLY,
  department_guidance_received: TOO_SMALL,
  department_guidance_applied: TOO_SMALL,
  department_guidance_responded: TOO_SMALL,
  department_input: INTERNAL,
  tool_call_required: INTERNAL,
  activation_finished: STATE_ONLY,
  // 派发编号（骨架事件，工单 #1397）：楼上看不出一次性的动作，由下一份状态表示
  dispatch_number_acquired: STATE_ONLY,
  context_assembled: TOO_SMALL,
  model_request_serialized: TOO_SMALL,
  model_reasoning: MODEL_IO,
  model_message: MODEL_IO,
  model_requested: TOO_SMALL,
  model_stream_progress: TOO_SMALL,
  model_attempt_finished: TOO_SMALL,
  model_attempt_failed: TOO_SMALL,
  model_retry_scheduled: TOO_SMALL,
  compaction_recorded: TOO_SMALL,
  compaction_failed: TOO_SMALL,
  tool_called: TOO_SMALL,
  tool_started: TOO_SMALL,
  tool_skipped: TOO_SMALL,
  action_verified: PAGE_ONLY,
  proposal_submitted: TOO_SMALL,
  proposal_rejected: TOO_SMALL,
  spec_accepted: STATE_ONLY,
  spec_superseded: STATE_ONLY,
  contract_accepted: STATE_ONLY,
  product_decision_accepted: TOO_SMALL,
  delivery_accepted: STATE_ONLY,
  // 成果失效（骨架事件，S1b，工单 #858）：楼上看不出一次性的动作，失效由下一份状态表示
  artifact_invalidated: STATE_ONLY,
  // 通用的成果接纳（骨架事件，S2c，工单 #1098）：新种类的成果由下一份状态给出，没有一次性的动作
  artifact_accepted: STATE_ONLY,
  qa_tests_saved: TOO_SMALL,
  structure_accepted: STATE_ONLY,
  baseline_review_accepted: STATE_ONLY,
  lesson_candidate_recorded: STATE_ONLY,
  run_done: STATE_ONLY,
  run_paused: STATE_ONLY,
  run_failed: STATE_ONLY,
  run_resumed: STATE_ONLY,
  run_continued: STATE_ONLY,
  work_item_created: STATE_ONLY,
  work_item_start_failed: STATE_ONLY,
  adoption_held: STATE_ONLY,
  initial_prd_proposed: STATE_ONLY,
});

/** 翻译覆盖：三个场景里每种事件的归属。 */
export const COVERAGE: TranslationCoverage = {
  floor: { drawn: FLOOR_DRAWN, realtime: FLOOR_REALTIME, none: FLOOR_NONE },
  room: { drawn: ROOM_DRAWN, realtime: ROOM_REALTIME, none: ROOM_NONE },
  building: { drawn: BUILDING_DRAWN, realtime: BUILDING_REALTIME, none: BUILDING_NONE },
};

/** 一种事件在一个场景里的归属；没有归属时为 null。 */
export function classOf(coverage: TranslationCoverage, scene: Scene, type: string): CoverageClass | null {
  const c = coverage[scene];
  const inNone = Object.prototype.hasOwnProperty.call(c.none, type);
  if (c.drawn.includes(type)) return "drawn";
  if (c.realtime.includes(type)) return "realtime";
  if (inNone) return "none";
  return null;
}

/** 场景的中文名（缺口清单写给人看）。 */
export function sceneName(scene: Scene): string {
  return scene === "building" ? "楼" : scene === "floor" ? "楼层" : "房间";
}

/** 缺口清单的一行：一种事件在哪些场景里还没有归属。 */
export interface EventGap {
  readonly type: string;
  readonly scenes: readonly Scene[];
}

/**
 * 缺口清单：给出的每种事件，凡是在某个场景里既没翻成动作、也没写明不画，按种类各占一行。
 * 清单可以不为空：服务端新增一种事件时它多一行，测试不因它失败（docs/design/visualization.md「缺口清单」）。
 */
export function eventGaps(types: readonly string[], coverage: TranslationCoverage = COVERAGE): EventGap[] {
  const gaps: EventGap[] = [];
  for (const type of new Set(types)) {
    const scenes = SCENES.filter((scene) => classOf(coverage, scene, type) === null);
    if (scenes.length > 0) gaps.push({ type, scenes });
  }
  return gaps;
}

/** 缺口清单写成测试输出与壳上能读的句子：每行一种事件，写明它在哪些场景里没有归属、因此不画。 */
export function gapLines(gaps: readonly EventGap[]): string[] {
  return gaps.map((gap) => `${gap.type}：${gap.scenes.map(sceneName).join("、")}里没有归属，不画`);
}

/** 三个场景实际画出来的东西：动作表与流式文字表（画面的实现，不是归属表）。 */
export interface PaintedEventTypes {
  readonly actions: Readonly<Record<Scene, readonly string[]>>;
  readonly streams: Readonly<Record<Scene, readonly string[]>>;
}

/**
 * 缺口清单与实际画出来的东西一致（docs/design/visualization.md「画面诚实性的不变式」的「缺口清单说真话」）：
 * 清单里的种类在它没有归属的场景里确实没有动作、也没有流式文字；有归属的种类与实际画法一致
 * （翻成动作的出现在动作表里，写明不画的不出现在动作表里，转交实时内容的出现在流式文字表里）。
 * 返回问题清单（空表示一致）。缺口清单不为空不算问题。
 */
export function gapProblems(
  types: readonly string[], painted: PaintedEventTypes, coverage: TranslationCoverage = COVERAGE,
): string[] {
  const problems: string[] = [];
  const gaps = new Map(eventGaps(types, coverage).map((gap) => [gap.type, new Set(gap.scenes)]));
  for (const scene of SCENES) {
    const actions = new Set(painted.actions[scene]);
    const streams = new Set(painted.streams[scene]);
    for (const type of types) {
      const cls = classOf(coverage, scene, type);
      if ((gaps.get(type)?.has(scene) ?? false) && (actions.has(type) || streams.has(type))) {
        problems.push(`${scene}：事件 ${type} 列在缺口清单里，实际画了`);
        continue;
      }
      if (cls === "drawn" && !actions.has(type)) {
        problems.push(`${scene}：事件 ${type} 标为翻成动作，动作表里没有它`);
      }
      if (cls === "none" && actions.has(type)) {
        problems.push(`${scene}：事件 ${type} 标为不画，动作表里却有它`);
      }
      if (cls === "realtime" && !streams.has(type)) {
        problems.push(`${scene}：事件 ${type} 标为转交实时内容，流式文字表里没有它`);
      }
      if (cls !== "realtime" && streams.has(type)) {
        problems.push(`${scene}：事件 ${type} 有流式文字，归属表里没有标为转交实时内容`);
      }
    }
  }
  return problems;
}

/**
 * 归属表自己的问题：一种事件在一个场景里同时归到两类，或写明不画却没写理由。
 * 缺归属不是问题，进缺口清单（不再「缺一行就失败」，工单 #1419）。
 */
export function declarationProblems(coverage: TranslationCoverage = COVERAGE): string[] {
  const problems: string[] = [];
  for (const scene of SCENES) {
    const c = coverage[scene];
    for (const type of new Set([...c.drawn, ...c.realtime, ...Object.keys(c.none)])) {
      const classes = [
        c.drawn.includes(type) ? "翻成动作" : null,
        c.realtime.includes(type) ? "转交实时内容" : null,
        Object.prototype.hasOwnProperty.call(c.none, type) ? "不画" : null,
      ].filter((value): value is string => value !== null);
      if (classes.length > 1) {
        problems.push(`${scene}：事件 ${type} 同时属于 ${classes.join("、")}`);
      }
    }
    for (const [type, reason] of Object.entries(c.none)) {
      if (typeof reason !== "string" || reason.trim() === "") {
        problems.push(`${scene}：事件 ${type} 列为不画，但没有写理由`);
      }
    }
  }
  return problems;
}

// ---------------------------------------------------------------------------
// 楼层画面的覆盖层（工单 #398）：每个覆盖层在翻译层有一行中文名
//
// 覆盖层的清单由服务的接口层给出（能力清单的 overlays，harness/app/registry.py 的 OVERLAYS），
// 页面按能力清单决定按钮条上出现哪几个；按钮上的中文名写在这一份里，页面不自己拼。
// 每个覆盖层都有一行，缺一行由单元测试报出（工单 #398 的验收：事件种类、术语与覆盖层各有一行）。

/** 覆盖层标识 → 按钮上的中文名。 */
export const OVERLAY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  flow: "流转",
  waiting: "等待",
  recovery: "恢复",
  context_usage: "上下文用量",
  semantic_records: "语义记录",
  // 事实来源（工单 #396 的事件对象 source、工单 #398 的画面）：五种来源的描边与图例
  sources: "来源",
  // 循环与收敛（工单 #400）：循环树的层、已用边界与收敛状态
  loops: "循环",
});

/**
 * 覆盖层名字的覆盖核对：页面按能力清单列出覆盖层时，每个名字都要有一行中文名。
 * 返回问题清单（空表示通过）；提示写明缺哪个覆盖层的名字，由单元测试与页面构建两处共用。
 */
export function overlayProblems(names: readonly string[], labels: Readonly<Record<string, string>> = OVERLAY_LABELS): string[] {
  const problems: string[] = [];
  for (const name of names) {
    const label = labels[name];
    if (typeof label !== "string" || label.trim() === "") {
      problems.push(`覆盖层 ${name} 在翻译层没有中文名`);
    }
  }
  return problems;
}

// ---------------------------------------------------------------------------
// 检验方式的名称（验证的独立性 docs/design/independent-verification.md「口径」，工单 #151）
//
// 质检的逐条结论里每种检验方式用代码名保存：check（命令检查）、trial（试用用例）、measure（主机测量）、
// judgement（带参照材料的判定点）、human（人）、open（开环）；前三种是可执行的检验，后三种不可执行。
// 页面上显示中文名。两端各读自己那一份夹具：客户端是 client/tests/fixtures/check-methods.json，
// 服务端是 harness/tests/fixtures/check_methods.json（服务端测试核对两份相同，也核对服务端的封闭取值
// 与它那份一致）。这里缺一行时客户端单元测试失败并写明缺哪个代码名。

/** 一种检验方式：页面上显示的名字与它是不是可执行的检验。 */
export interface CheckMethodRow {
  readonly label: string;
  readonly executable: boolean;
}

/** 夹具里的一行：代码名、名字与是否可执行。 */
export interface CheckMethodFixtureRow extends CheckMethodRow {
  readonly code: string;
}

/** 检验方式的声明表：六个代码名各一行。 */
export const CHECK_METHODS: Readonly<Record<string, CheckMethodRow>> = Object.freeze({
  check: { label: "命令检查", executable: true },
  trial: { label: "试用用例", executable: true },
  measure: { label: "主机测量", executable: true },
  judgement: { label: "带参照材料的判定点", executable: false },
  human: { label: "人", executable: false },
  open: { label: "开环", executable: false },
});

/**
 * 声明表覆盖夹具的核对：夹具里的每个代码名都有一行且名字与可执行相同，
 * 声明表里也没有夹具以外的代码名。返回问题清单（空表示通过）。
 */
export function checkMethodProblems(
  methods: readonly CheckMethodFixtureRow[],
  table: Readonly<Record<string, CheckMethodRow>> = CHECK_METHODS,
): string[] {
  const problems: string[] = [];
  for (const item of methods) {
    const row = table[item.code];
    if (row === undefined) {
      problems.push(`检验方式 ${item.code} 在声明表里没有一行`);
      continue;
    }
    if (row.label !== item.label) {
      problems.push(`检验方式 ${item.code} 的名字与夹具不同：${row.label} 与 ${item.label}`);
    }
    if (row.executable !== item.executable) {
      problems.push(`检验方式 ${item.code} 的可执行与夹具不同`);
    }
  }
  const codes = new Set(methods.map((item) => item.code));
  for (const code of Object.keys(table)) {
    if (!codes.has(code)) {
      problems.push(`声明表里的 ${code} 不在夹具里`);
    }
  }
  return problems;
}
