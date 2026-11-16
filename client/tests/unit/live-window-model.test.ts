// 内嵌「现场窗口 · live」纯模型测试（工单 #1811，docs/design/project-organization.md
// 「项目页是循环图加对话」「节点面板与箭头面板接住的内容」「项目页上的内容在哪里看」）。
//
// 验证默认职能选择、?arrow= 地址解析、触及文件清单与写入范围兜底、多题待决预览、
// 工作间边界提示及「职能详情」「本职能的模型请求」入口地址。

import { test } from "node:test";
import assert from "node:assert/strict";

import type {
  AttemptView,
  DecisionView,
  DepartmentWorkspaceResult,
  DraftOrganization,
  RunStepsResult,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import { parseRoute } from "../../src/renderer/src/shell/routing.ts";
import {
  graphOf,
  type FlowRecordLike,
  type FrozenOrganization,
  type LoopItemView,
  type TelemetryCatalog,
  type TelemetrySettings,
} from "../../src/renderer/src/views/project/loop-graph-model.ts";
import {
  NO_LAST_CALL_TEXT,
  arrowMatchesQuery,
  livePendingDecisions,
  liveRelatedArrows,
  liveWindowView,
  pickLiveDepartment,
  touchedMaterialsOf,
} from "../../src/renderer/src/views/project/live-window-model.ts";

function threeOrg(): FrozenOrganization {
  return {
    form: "three",
    routing: "watched_outputs",
    roles: [
      { id: "product", label: "产品" },
      { id: "engineering", label: "工程" },
      { id: "quality", label: "质检" },
    ],
    verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["delivery_spec"] }] }],
    completing: null,
    watched: [
      { source: "product", recipient: "engineering", outcome: "product_spec" },
      { source: "engineering", recipient: "quality", outcome: "delivery_spec" },
    ],
  };
}

function draftOrg(): DraftOrganization {
  return {
    form: "three",
    form_title: "三职能",
    routing: "watched_outputs",
    departments: [
      {
        id: "product",
        label: "产品",
        target: "PRD",
        evidence: "对话",
        work: "定目标",
        watched: [],
        outcomes: ["product_spec"],
        write_scope: "check_materials",
      },
      {
        id: "engineering",
        label: "工程",
        target: "代码交付",
        evidence: "测试",
        work: "实现",
        watched: ["product_spec"],
        outcomes: ["delivery_spec"],
        write_scope: "workspace",
      },
      {
        id: "quality",
        label: "质检",
        target: "核验放行",
        evidence: "试运行",
        work: "核验",
        watched: ["delivery_spec"],
        outcomes: [],
        write_scope: "check_materials",
      },
    ],
    verification: [{ verifier: "quality", verified: "engineering", outcome: "delivery_spec" }],
    completing: null,
  } as unknown as DraftOrganization;
}

test("默认职能优先取显式点选，其次取正在工作的职能，再退到组织首项", () => {
  // R3：现场窗口打开时先落在用户点选节点；未点过时自动落到正在工作的职能或首个职能
  const org = threeOrg();
  const roles = org.roles;
  const item: LoopItemView = {
    work_item_id: "w1",
    status: "in_progress",
    department: "product",
    organization: org,
    departments: {
      product: { state: "waiting" },
      engineering: { state: "working", note: "写代码" },
      quality: { state: "waiting" },
    },
  };
  assert.equal(pickLiveDepartment(item, roles, null), "engineering");
  assert.equal(pickLiveDepartment(item, roles, "quality"), "quality");
  assert.equal(pickLiveDepartment(item, roles, "nonexistent"), "engineering");

  const idleItem: LoopItemView = {
    work_item_id: "w2",
    status: "not_started",
    department: null,
    organization: org,
    departments: { product: { state: "waiting" }, engineering: { state: "waiting" } },
  };
  assert.equal(pickLiveDepartment(idleItem, roles, null), "product");
  assert.equal(pickLiveDepartment(idleItem, [], null), "");
});

test("地址参数 ?arrow= 按 flow_id 或 event_id 定位箭头面板", () => {
  // R3：从成果库跳回对话页带 ?arrow= 时准确命中对应箭头
  const org = threeOrg();
  const item: LoopItemView = { work_item_id: "w1", status: "in_progress", organization: org };
  const flow: FlowRecordLike[] = [
    {
      flow_id: "flow-prd-1",
      event_id: "ev-prd-1",
      kind: "PRD 新版本",
      content: "需求说明",
      direction_from: "product",
      direction_to: "engineering",
      position: 2,
      round: 1,
    },
    {
      flow_id: "flow-del-1",
      event_id: "ev-del-1",
      kind: "版本交付",
      content: "实现交付",
      direction_from: "engineering",
      direction_to: "quality",
      position: 5,
      round: 1,
    },
  ];
  const graph = graphOf({ item, flow, materials: null });
  const arrows = [...graph.gaps.flat(), ...graph.skip, ...graph.side.flatMap((s) => s.arrows)];

  assert.equal(arrowMatchesQuery(arrows, "flow-del-1")?.key, "flow-del-1");
  assert.equal(arrowMatchesQuery(arrows, "ev-prd-1")?.key, "flow-prd-1");
  assert.equal(arrowMatchesQuery(arrows, "missing-arrow"), null);
  assert.deepEqual(liveRelatedArrows(arrows, "quality").map((a) => a.key), ["flow-del-1"]);
});

test("触及文件取自该职能交付材料，尚无交付时如实退回写入范围", () => {
  // R1：交出文件取自 work_item.materials，未交付时不空白或猜文件，写明写入范围
  const flow: FlowRecordLike[] = [
    {
      flow_id: "f-del-1",
      event_id: "ev-del-1",
      kind: "版本交付",
      content: "首次交付",
      direction_from: "engineering",
      direction_to: "quality",
      position: 3,
      round: 1,
    },
  ];
  const materials = {
    deliveries: [
      { event_id: "ev-del-1", revision: 1, files: ["client/a.ts", "client/b.ts"] },
    ],
  };
  const engTouched = touchedMaterialsOf({
    department: "engineering",
    materials,
    flow,
    organization: draftOrg(),
  });
  assert.deepEqual(engTouched, { kind: "files", files: ["client/a.ts", "client/b.ts"], deliveryCount: 1 });

  const prodTouched = touchedMaterialsOf({
    department: "product",
    materials,
    flow,
    organization: draftOrg(),
  });
  assert.deepEqual(prodTouched, { kind: "scope", scopeText: "只写检查材料" });
});

test("属于当前职能的 role_choice 多题待决生成题干与推荐项预览", () => {
  // R1/R2：多题待决只筛给归属职能，预览包含每题题干与推荐选项名
  const org = threeOrg();
  const item: LoopItemView = { work_item_id: "w1", status: "in_progress", department: "engineering", organization: org };
  const decisions: DecisionView[] = [
    {
      decision_id: "d-eng",
      project_id: "p1",
      work_item_id: "w1",
      run_id: "r1",
      kind: "role_choice",
      blocks: "round",
      version: 1,
      status: "open",
      requested_at: "2026-01-01T00:00:00Z",
      blocked: null,
      request: {
        kind: "role_choice",
        blocks: "round",
        department: "engineering",
        round: 2,
        note: "需要确认接口风格",
        options: [],
        questions: [
          {
            id: "q1",
            question: "如何保存蓝图主题？",
            recommended: "local",
            rationale: "浏览器本地记住即可",
            options: [
              { id: "local", label: "存在本地存储", description: null, recommended: true },
              { id: "session", label: "只记当前标签", description: null, recommended: false },
            ],
          },
        ],
      } as unknown as DecisionView["request"],
      answer: null,
    },
    {
      decision_id: "d-other-dept",
      project_id: "p1",
      work_item_id: "w1",
      run_id: "r1",
      kind: "role_choice",
      blocks: "round",
      version: 1,
      status: "open",
      requested_at: "2026-01-01T00:00:00Z",
      blocked: null,
      request: {
        kind: "role_choice",
        blocks: "round",
        department: "product",
        options: [],
        questions: [],
      } as unknown as DecisionView["request"],
      answer: null,
    },
  ];
  const pendingEng = livePendingDecisions({ decisions, item, department: "engineering" });
  assert.equal(pendingEng.length, 1);
  assert.equal(pendingEng[0].decisionId, "d-eng");
  assert.equal(pendingEng[0].roundLabel, "第 2 轮");
  assert.equal(pendingEng[0].questions[0].question, "如何保存蓝图主题？");
  assert.equal(pendingEng[0].questions[0].recommendedLabel, "存在本地存储");

  assert.equal(livePendingDecisions({ decisions, item, department: "quality" }).length, 0);
});

test("整份现场窗口视图串联工作间、最近请求链接、结果未知恢复入口与详情跳转地址", () => {
  // R1/R2/R3：验证遥测摘要、真实 token、remote_unknown 动作核实、无请求诚实文案及入口路由
  const org = threeOrg();
  const item: LoopItemView = {
    work_item_id: "w1",
    status: "in_progress",
    department: "engineering",
    organization: org,
    departments: {
      product: { state: "waiting" },
      engineering: { state: "working", note: "检查构建" },
      quality: { state: "waiting" },
    },
  };
  const flow: FlowRecordLike[] = [];
  const graph = graphOf({ item, flow, materials: null });
  const workspace = {
    project_id: "p1",
    department: "engineering",
    work_item_id: "w1",
    run_id: "r1",
    run_status: "running",
    status: "in_progress",
    stop_reason: null,
    active: true,
    department_setting: { department: "engineering", configured_version: 1, configured_text: "", source: "default", used_version: 1 },
    setting: { department: "engineering", version: 1, text: "", source: "default", model_id: "m1", requested_tier: "high" },
    effective: { state: "effective", model_id: "m1", model: "claude-sonnet-4-6", protocol: "messages", requested_tier: "high", sent_tier: "high" },
    guidance: [
      {
        guidance_id: "g1",
        version: 1,
        text: "保留全部测试",
        status: "applied",
        applied_activation_id: "act-1",
        answered_activation_id: null,
        outcome: null,
        created_event_id: "ev-g1",
      },
    ],
    messages: [],
    context: {},
    last_call: { requested_model: "claude-sonnet-4-6", requested_protocol: "messages", requested_tier: "high", sent_tier: "high" },
    reminders: [],
    room: {
      machine: "win-runner",
      waiting_provider: false,
      remote_unknown: true,
      mailbox: 1,
      summaries: 2,
      pinned_notes: 1,
      pipes: { out: "flowing", letters_waiting: 0 },
      roles: [{ id: "coder", name: "实现", kind: "doer", status: "working", task: "npm test" }],
    },
  } as unknown as DepartmentWorkspaceResult;
  const catalog: TelemetryCatalog = {
    models: [
      {
        id: "m1",
        provider_id: "p-ant",
        model: "claude-sonnet-4-6",
        protocol: "messages",
        context_window: 100000,
        max_output_tokens: 8192,
        capability_source: "declared",
        accepts_required_tool_call: true,
        input_modalities: ["text"],
        reasoning_levels: ["medium", "high"],
        default_reasoning_level: "medium",
        reasoning_mode: "adaptive",
      },
    ],
    bindings: {},
  };
  const settings: TelemetrySettings = {
    departments: {},
  };
  const attempts: AttemptView[] = [
    {
      attempt_id: "att-9",
      run_id: "r1",
      work_item_id: "w1",
      department: "engineering",
      status: "success",
      stage: "work",
      purpose: "work",
      prompt_version: 1,
      requested_provider: "p-ant",
      requested_model: "claude-sonnet-4-6",
      actual_provider: "p-ant",
      actual_model: "claude-sonnet-4-6",
      started_at: "2026-01-01T00:00:00Z",
      finished_at: "2026-01-01T00:00:02Z",
      duration_ms: 2000,
      usage: { reported: true, input_tokens: 20000, output_tokens: 1500, total_tokens: 21500 },
      position: 9,
    },
  ];
  const steps = {
    run_id: "r1",
    department: "engineering",
    activation_id: "act-1",
    activations: [],
    steps: [],
    unassigned_actions: [],
    tasks: [],
    background_commands: [],
  } as unknown as RunStepsResult;

  const view = liveWindowView({
    projectId: "p1",
    workItemId: "w1",
    runId: "r1",
    department: "engineering",
    item,
    graph,
    arrows: [],
    flow,
    materials: null,
    workspace,
    steps,
    asks: [],
    decisions: [],
    settings,
    catalog,
    attempts,
    organization: draftOrg(),
  });
  assert.ok(view !== null);
  assert.equal(view.recentRequest?.contextText, "20%");
  assert.match(view.recentRequest?.tokensText ?? "", /20,000/);
  assert.match(view.recentRequest?.href ?? "", /observe\/att-9/);
  assert.match(view.recoveryHref ?? "", /recovery/);
  assert.equal(view.guidance[0].text, "保留全部测试");

  const reqRoute = parseRoute(view.panelView.links.requests);
  assert.equal(reqRoute.name, "items");
  assert.equal(reqRoute.itemsTab, "requests");
  assert.equal(reqRoute.requestFilters.department, "engineering");

  const detRoute = parseRoute(view.panelView.links.detail);
  assert.equal(detRoute.name, "dept-detail");
  assert.equal(detRoute.department, "engineering");
  assert.equal(detRoute.departmentOrigin, "conversation");

  // 尚无请求的职能，不造最近请求数值
  const idleView = liveWindowView({
    projectId: "p1",
    workItemId: "w1",
    runId: "r1",
    department: "product",
    item,
    graph,
    arrows: [],
    flow,
    materials: null,
    workspace: { ...workspace, department: "product", last_call: null, guidance: [] },
    steps: null,
    asks: [],
    decisions: [],
    settings,
    catalog,
    attempts,
    organization: draftOrg(),
  });
  assert.equal(idleView?.recentRequest, null);
  assert.equal(idleView?.lastCall?.summary, NO_LAST_CALL_TEXT);
});
