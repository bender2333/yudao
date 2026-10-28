// 翻译覆盖核对（画面与播放设计说明第 6 节与第 8 节最后一行、原型 v13 js/translate/translate.js 的 T.coverage，工单 #952）。
//
// 能力清单里的每种事件，在楼、楼层、房间三个场景里各属于一类：
//   drawn    —— 翻成这个场景的动作；
//   realtime —— 作为实时内容转交（决定卡片、流式文字），不进播放时间线；
//   none     —— 这个场景不画，写一句理由。
// 客户端单元测试读不了 Python，事件种类的来源是夹具 client/tests/fixtures/event-types.json；
// 服务端测试 harness/tests/test_event_type_fixture.py 核对它与 harness/app/contracts.py 的 EVENT_TYPES 相同。
// 服务端新增事件种类时，服务端测试先失败并提示重新生成夹具；夹具更新以后，这里的覆盖核对失败，提示补上归属。
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

/**
 * 覆盖核对：给出的每种事件在三个场景里各有一个归属，每个「不画」有一句理由。
 * 返回问题清单（空表示通过）；提示写明是哪个场景、哪种事件、缺什么。
 */
export function coverageProblems(types: readonly string[], coverage: TranslationCoverage = COVERAGE): string[] {
  const problems: string[] = [];
  for (const scene of SCENES) {
    const c = coverage[scene];
    for (const type of types) {
      const classes = [
        c.drawn.includes(type) ? "翻成动作" : null,
        c.realtime.includes(type) ? "转交实时内容" : null,
        Object.prototype.hasOwnProperty.call(c.none, type) ? "不画" : null,
      ].filter((value): value is string => value !== null);
      if (classes.length === 0) {
        problems.push(`${scene}：事件 ${type} 没有归属（翻成动作、转交实时内容、不画）`);
      } else if (classes.length > 1) {
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

/** 覆盖核对，不过时抛错（错误里带整份问题清单，逐条写明场景、事件与缺什么）。 */
export function checkCoverage(types: readonly string[], coverage: TranslationCoverage = COVERAGE): void {
  const problems = coverageProblems(types, coverage);
  if (problems.length > 0) {
    throw new Error("翻译覆盖核对没有通过：\n" + problems.join("\n"));
  }
}
