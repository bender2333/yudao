// 组织页纯视图模型测试（守 R2 组织形态合成显示与 R3 历史改回及版本冲突行为）。

import assert from "node:assert/strict";
import test from "node:test";
import type {
  Catalog,
  DraftOrganization,
  FormChoice,
  ProjectLoopResult,
  ProjectOrganizationResult,
  ProjectSettingsResult,
  WorkItemOrganization,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  departmentRows,
  departmentTableColumnTitle,
  flowSteps,
  formatOrgCommandProblem,
  oldOrgItems,
  orgBlueprint,
  orgFormSummary,
  orgHistoryRows,
  orgQuestions,
  pendingCandidates,
  previousItemDiffView,
  revertAdoptPayload,
  revertConfirmView,
  revertDraftParams,
  type ProjectOrganizationSnapshot,
} from "../../src/renderer/src/views/project/org-page-model.ts";

function makeThreeDeptOrg(overrides: Partial<DraftOrganization> = {}): DraftOrganization {
  return {
    version: "v3",
    form: "three_departments",
    routing: "watched_outputs",
    routing_label: "成果驱动",
    sources: { user_input: "product", onboarding: "product" },
    outcome_kinds: [
      { id: "product_spec", label: "PRD" },
      { id: "product_decision", label: "产品决定" },
      { id: "delivery_spec", label: "交付" },
      { id: "structure", label: "现有结构说明" },
      { id: "baseline_review", label: "基线审查" },
      { id: "independent_judgement", label: "独立判断" },
      { id: "qa_review", label: "核验结论" },
    ],
    departments: [
      {
        id: "product",
        label: "产品",
        target: "澄清需求并给出产品决定与 PRD",
        evidence: "PRD 与需求来源一致",
        work: "",
        watched: ["user_input", "guidance", "baseline_review"],
        outcomes: ["product_decision", "product_spec"],
        verifier: false,
        write_scope: "spec",
      },
      {
        id: "engineering",
        label: "工程",
        target: "完成代码实现与测试验证",
        evidence: "测试通过并提交交付说明",
        work: "",
        watched: ["product_spec", "defect_record", "guidance"],
        outcomes: ["delivery_spec", "structure"],
        verifier: false,
        write_scope: "code",
      },
      {
        id: "quality",
        label: "质检",
        target: "独立核验交付是否满足需求",
        evidence: "核验记录与独立结论",
        work: "",
        watched: ["delivery", "guidance", "structure", "product_spec"],
        outcomes: ["baseline_review", "independent_judgement", "qa_review"],
        verifier: true,
        write_scope: "review",
      },
    ],
    verification: [{ verifier: "quality", verified: "engineering", outcome: "delivery_spec" }],
    ...overrides,
  };
}

function makeDirectSingleOrg(overrides: Partial<DraftOrganization> = {}): DraftOrganization {
  return {
    version: "v1",
    form: "single_role_direct",
    routing: "direct",
    routing_label: "直做",
    sources: { user_input: "engineering", onboarding: "engineering" },
    outcome_kinds: [
      { id: "completion", label: "交完成" },
      { id: "product_spec", label: "初始 PRD" },
      { id: "structure", label: "现有结构说明" },
      { id: "completion_review", label: "核验结论" },
    ],
    departments: [
      {
        id: "engineering",
        label: "工程",
        target: "直接承接输入并交付结果",
        evidence: "交付说明与测试记录",
        work: "",
        watched: ["guidance"],
        outcomes: ["completion", "product_spec", "structure"],
        verifier: false,
        write_scope: "code",
      },
    ],
    verification: [],
    ...overrides,
  };
}

function makeFormChoice(org: DraftOrganization, label: string, description: string): FormChoice {
  const verifiers = org.departments.filter((d) => d.verifier).map((d) => d.label);
  return {
    form: org.form,
    label,
    description,
    version: org.version,
    verifier_roles: verifiers,
    open_loop: verifiers.length === 0,
    routing: org.routing,
    routing_label: org.routing_label,
    ending: verifiers.length === 0 ? "开环完成" : `${verifiers.join("、")}放行`,
    card_line: description,
    organization: org,
  };
}

function makeProjectOrgResult(
  draftOrg: DraftOrganization,
  overrides: Partial<ProjectOrganizationResult> = {},
): ProjectOrganizationResult {
  const twoDept = makeThreeDeptOrg({
    form: "two_departments",
    departments: makeThreeDeptOrg().departments.filter((d) => d.id !== "quality"),
    verification: [],
  });
  return {
    project_id: "proj-1",
    form: draftOrg.form,
    label: draftOrg.form === "three_departments" ? "产品 · 工程 · 质检" : "工程",
    version: draftOrg.version,
    form_in_release: true,
    departments: draftOrg.departments.map((d) => ({
      id: d.id,
      label: d.label,
      verifier: d.verifier,
      origin: "release",
      running_items: 0,
    })),
    forms: [
      makeFormChoice(makeThreeDeptOrg(), "产品 · 工程 · 质检", "三职能协作"),
      makeFormChoice(makeDirectSingleOrg(), "工程", "单职能直做"),
      makeFormChoice(twoDept, "产品 · 工程", "双职能"),
    ],
    history: [],
    changes: {},
    organization: draftOrg,
    rejections: [],
    previous_item: null,
    ...overrides,
  };
}

function makeWorkItemOrg(overrides: Partial<WorkItemOrganization>): WorkItemOrganization {
  return {
    form: "single_role_direct",
    routing: "direct",
    roles: [{ id: "engineering", label: "工程", ref: { position: 1, source: "rule" } }],
    verifiers: [],
    completing: { id: "engineering", label: "工程", ref: { position: 1, source: "rule" } },
    watched: [],
    asks: [],
    rejections: [],
    version: "v1",
    same_as_project: false,
    ...overrides,
  };
}

test("头部四问与成果流向在「产品 · 工程 · 质检」上准确反映独立放行条件", () => {
  const org = makeThreeDeptOrg();
  const q = orgQuestions(org);
  const steps = flowSteps(org);
  const blueprint = orgBlueprint(org);

  assert.match(q.fromWhere, /你的输入、建档 → 产品/);
  assert.match(q.whoDoes, /产品、工程/);
  assert.match(q.whoDoes, /质检/);
  assert.match(q.whoVerifies, /质检核验工程的交付/);
  assert.match(q.howEnds, /质检放行才算完成/);
  assert.equal(blueprint.isOpenLoop, false);
  assert.deepEqual(steps, [
    "你的输入、建档 → 产品",
    "产品 → PRD → 工程、质检",
    "工程 → 交付 → 质检",
    "质检 → 缺陷记录 → 工程",
    "质检 → 放行 → 事项完成",
  ]);
  assert.ok(blueprint.loopGraph.chain.length + blueprint.loopGraph.side.length >= 3);
});

test("「产品 · 工程」与「工程」按合成组织算出开环完成与精确流向", () => {
  const twoDept = makeThreeDeptOrg({
    form: "two_departments",
    departments: makeThreeDeptOrg().departments.filter((d) => d.id !== "quality"),
    verification: [],
  });
  const qTwo = orgQuestions(twoDept);
  assert.match(qTwo.whoVerifies, /没有人核验/);
  assert.match(qTwo.howEnds, /^开环完成：没有人核验/);
  assert.deepEqual(flowSteps(twoDept), [
    "你的输入、建档 → 产品",
    "产品 → PRD → 工程",
    "工程 → 交付 → 开环完成",
  ]);

  const single = makeDirectSingleOrg();
  const qSingle = orgQuestions(single);
  assert.match(qSingle.whoDoes, /工程/);
  assert.match(qSingle.whoVerifies, /没有人核验/);
  assert.match(qSingle.howEnds, /^开环完成：没有人核验/);
  assert.deepEqual(flowSteps(single), ["你的输入、建档 → 工程 → 交付 → 开环完成"]);
});

test("不按形态名分支：自定义增减核验角色与自定义名称实时改变四问和流向", () => {
  const singlePlusVerifier = makeDirectSingleOrg({
    departments: [
      ...makeDirectSingleOrg().departments,
      {
        id: "sec_audit",
        label: "安全审计",
        target: "审计上线前的合规性",
        evidence: "审计报告",
        work: "",
        watched: ["guidance"],
        outcomes: ["completion_review"],
        verifier: true,
        write_scope: "review",
      },
    ],
    verification: [{ verifier: "sec_audit", verified: "engineering", outcome: "completion" }],
  });
  const qAdded = orgQuestions(singlePlusVerifier);
  assert.match(qAdded.whoVerifies, /安全审计核验工程的交付/);
  assert.match(qAdded.howEnds, /安全审计放行才算完成/);
  assert.equal(orgBlueprint(singlePlusVerifier).isOpenLoop, false);
  assert.ok(flowSteps(singlePlusVerifier).includes("工程 → 交付 → 安全审计"));
  assert.ok(flowSteps(singlePlusVerifier).includes("安全审计 → 放行 → 事项完成"));

  const customThreeNameOpen = makeThreeDeptOrg({
    form: "totally_custom_form",
    sources: { user_input: "analyst", onboarding: "builder" },
    outcome_kinds: [{ id: "brief", label: "调研摘要" }],
    departments: [
      {
        id: "analyst",
        label: "调研员",
        target: "输出调研摘要",
        evidence: "调研记录",
        work: "",
        watched: ["user_input"],
        outcomes: ["brief"],
        verifier: false,
        write_scope: "spec",
      },
      {
        id: "builder",
        label: "构建员",
        target: "按调研摘要制作交付物",
        evidence: "构建结果",
        work: "",
        watched: ["brief"],
        outcomes: ["delivery_spec"],
        verifier: false,
        write_scope: "code",
      },
    ],
    verification: [],
  });
  const qRemoved = orgQuestions(customThreeNameOpen);
  assert.match(qRemoved.fromWhere, /你的输入 → 调研员/);
  assert.match(qRemoved.fromWhere, /建档 → 构建员/);
  assert.match(qRemoved.whoVerifies, /没有人核验/);
  assert.match(qRemoved.howEnds, /^开环完成：没有人核验/);
  assert.deepEqual(flowSteps(customThreeNameOpen), [
    "你的输入 → 调研员",
    "建档 → 构建员",
    "调研员 → 调研摘要 → 构建员",
    "构建员 → 交付 → 开环完成",
  ]);
});

test("只读职能表按轮转方式切换列、展示生效模型与来源标记", () => {
  const threeOrg = makeThreeDeptOrg();
  const projectOrg = makeProjectOrgResult(threeOrg, {
    departments: [
      { id: "product", label: "产品", verifier: false, origin: "release", running_items: 0 },
      { id: "engineering", label: "工程", verifier: false, origin: "changed", running_items: 0 },
      { id: "quality", label: "质检", verifier: true, origin: "added", running_items: 0 },
      { id: "ops_legacy", label: "旧运维", verifier: false, origin: "running_item", running_items: 2 },
    ],
  });
  const settings: ProjectSettingsResult = {
    project_id: "proj-1",
    name: "测试项目",
    goal: "测试目标",
    version: 1,
    pinned: false,
    archived: false,
    source_directories: {},
    mcp_servers: { version: 1, document_digest: "d" },
    departments: {
      engineering: {
        department: "engineering",
        version: 1,
        text: "",
        source: "configured",
        provider_id: "openai",
        model_id: "openai/gpt-5",
        requested_tier: "high",
        department_setting_configured: true,
      },
    },
    department_reminders: {},
  };
  const catalog: Catalog = {
    revision: 1,
    config_state: "ok",
    reload_error: null,
    default_timeout_sec: 120,
    presets: { revision: "1", source: "builtin", presets: [] },
    capability_table: { revision: "1", snapshot_date: "2026-11-15", source: "builtin", presets: {} },
    providers: [],
    models: [
      {
        id: "openai/gpt-5",
        provider_id: "openai",
        model: "gpt-5",
        protocol: "chat_completions",
        context_window: null,
        max_output_tokens: null,
        capability_source: "catalog",
        accepts_required_tool_call: true,
        input_modalities: ["text"],
        reasoning_levels: ["high"],
        default_reasoning_level: "high",
        reasoning_mode: "effort",
      },
      {
        id: "google/gemini-pro",
        provider_id: "google",
        model: "gemini-pro",
        protocol: "responses",
        context_window: null,
        max_output_tokens: null,
        capability_source: "catalog",
        accepts_required_tool_call: true,
        input_modalities: ["text"],
        reasoning_levels: ["high"],
        default_reasoning_level: "high",
        reasoning_mode: "effort",
      },
    ],
    admissions: [],
    bindings: {
      product: {
        provider_id: "google",
        model_id: "google/gemini-pro",
        requested_tier: "high",
      },
    },
    departments: [],
    department_reminders: {},
    model_reminders: {},
  };

  assert.equal(departmentTableColumnTitle(threeOrg), "谁核验它 · 它核验谁");
  const rows = departmentRows({ organization: projectOrg, settings, catalog });
  const productRow = rows.find((r) => r.id === "product");
  const engRow = rows.find((r) => r.id === "engineering");
  const qaRow = rows.find((r) => r.id === "quality");
  const legacyRow = rows.find((r) => r.id === "ops_legacy");

  assert.equal(productRow?.originLabel, "跟随发布");
  assert.equal(productRow?.modelText, "gemini-pro（google）");
  assert.equal(productRow?.modelSourceText, "跟随职能默认");
  assert.equal(engRow?.originLabel, "本项目改过");
  assert.equal(engRow?.modelText, "gpt-5（openai）");
  assert.equal(engRow?.modelSourceText, "本项目写入");
  assert.match(engRow?.relationText ?? "", /由 质检（交付） 核验/);
  assert.equal(qaRow?.verifier, true);
  assert.equal(qaRow?.originLabel, "本项目加的");
  assert.match(qaRow?.relationText ?? "", /核验 工程（交付）/);
  assert.equal(legacyRow?.clickable, false);
  assert.match(legacyRow?.originLabel ?? "", /只在旧组织里（2 个运行中事项）/);

  const directOrg = makeDirectSingleOrg();
  assert.equal(departmentTableColumnTitle(directOrg), "谁交完成");
  const directRows = departmentRows({
    organization: makeProjectOrgResult(directOrg),
    settings: null,
    catalog: null,
  });
  assert.equal(directRows[0]?.relationText, "本职能交完成");
});

test("摘要、旧组织未结束事项与上一条事项差异准确筛选", () => {
  const threeOrg = makeThreeDeptOrg();
  const projectOrg = makeProjectOrgResult(threeOrg, {
    changes: { departments: { engineering: { target: "自定义" } } },
    previous_item: {
      work_item_id: "WI-9",
      title: "上个需求",
      form: "single_role_direct",
      version: "v1",
      differences: [{ item: "核验", before: "无核验", after: "质检核验交付" }],
    },
  });

  const summary = orgFormSummary(projectOrg);
  assert.equal(summary.changeCount, 1);
  assert.equal(summary.formLabel, "产品 · 工程 · 质检");
  assert.equal(summary.version, "v3");

  const loop: ProjectLoopResult = {
    project_id: "proj-1",
    adoptions: [],
    work_items: [
      {
        work_item_id: "WI-1",
        kind: "feature",
        sign: "",
        color_index: 0,
        status: "in_progress",
        department: "engineering",
        progress: null,
        departments: { engineering: { state: "working", note: null } },
        round: 1,
        started_at: "2026-11-15T10:00:00Z",
        elapsed_sec: 10,
        time_limit_sec: 300,
        pending_question: null,
        run_id: "run-1",
        adoption_id: null,
        recovery_state: null,
        stop_reason: null,
        last_department: "engineering",
        version: 1,
        organization: makeWorkItemOrg({ same_as_project: false }),
      },
      {
        work_item_id: "WI-2",
        kind: "feature",
        sign: "",
        color_index: 1,
        status: "released_unsettled",
        department: "quality",
        progress: null,
        departments: { engineering: { state: "waiting", note: null } },
        round: 1,
        started_at: "2026-11-14T10:00:00Z",
        elapsed_sec: 10,
        time_limit_sec: 300,
        pending_question: null,
        run_id: "run-2",
        adoption_id: null,
        recovery_state: null,
        stop_reason: null,
        last_department: "quality",
        version: 1,
        organization: makeWorkItemOrg({ same_as_project: false }),
      },
      {
        work_item_id: "WI-3",
        kind: "feature",
        sign: "",
        color_index: 2,
        status: "held",
        department: "product",
        progress: null,
        departments: { product: { state: "waiting_user", note: null } },
        round: 1,
        started_at: "2026-11-15T11:00:00Z",
        elapsed_sec: 10,
        time_limit_sec: 300,
        pending_question: null,
        run_id: "run-3",
        adoption_id: null,
        recovery_state: null,
        stop_reason: null,
        last_department: "product",
        version: 1,
        organization: makeWorkItemOrg({
          form: "three_departments",
          routing: "watched_outputs",
          version: "v3",
          same_as_project: true,
        }),
      },
    ],
  };

  const oldItems = oldOrgItems(loop, projectOrg, "proj-1");
  assert.equal(oldItems.length, 1);
  assert.equal(oldItems[0]?.workItemId, "WI-1");
  assert.equal(oldItems[0]?.formLabel, "工程");
  assert.match(oldItems[0]?.href ?? "", /w=WI-1/);

  const prevDiff = previousItemDiffView(projectOrg.previous_item, projectOrg.forms);
  assert.equal(prevDiff?.workItemId, "WI-9");
  assert.equal(prevDiff?.differences.length, 1);
  assert.equal(previousItemDiffView(null, projectOrg.forms), null);
});

test("待采用候选仅在列表非空时输出结构化条目", () => {
  const emptyOrg = makeProjectOrgResult(makeThreeDeptOrg()) as ProjectOrganizationSnapshot;
  assert.deepEqual(pendingCandidates(emptyOrg), []);
  assert.deepEqual(pendingCandidates({ ...emptyOrg, candidates: [] }), []);

  const withCandidates: ProjectOrganizationSnapshot = {
    ...emptyOrg,
    candidates: [
      {
        id: "cand-1",
        title: "增加质量基线检查",
        summary: "连续两次退回，建议启用前置基线审查",
        diff: [{ item: "产品监听", before: "guidance", after: "guidance、baseline_review" }],
        evidence: [{ label: "退回记录", summary: "事项 #12 返工 2 次" }],
      },
    ],
  };
  const parsed = pendingCandidates(withCandidates);
  assert.equal(parsed.length, 1);
  assert.equal(parsed[0]?.diffLines[0], "产品监听：guidance → guidance、baseline_review");
  assert.equal(parsed[0]?.evidenceLines[0], "退回记录：事项 #12 返工 2 次");
});

test("采用历史倒序、「改回这一份」预览与 stale_base 冲突处理", () => {
  const threeOrg = makeThreeDeptOrg();
  const singleOrg = makeDirectSingleOrg();
  const projectOrg = makeProjectOrgResult(threeOrg, {
    history: [
      {
        event_id: "ev-1",
        previous_form: "",
        form: "single_role_direct",
        reason: "建项时选用单职能",
        at: "2026-11-10T08:00:00Z",
        actor: "human",
        previous_version: null,
        version: "v1",
        changes: { departments: { engineering: { target: "只管先做" } } },
        diff: [{ item: "形态", before: "空", after: "工程" }],
      },
      {
        event_id: "ev-2",
        previous_form: "single_role_direct",
        form: "three_departments",
        reason: "需要质检把关",
        at: "2026-11-12T09:30:00Z",
        actor: "human",
        previous_version: "v1",
        version: "v3",
        changes: {},
        diff: [{ item: "核验", before: "无核验", after: "质检放行" }],
      },
    ],
  });

  const rows = orgHistoryRows(projectOrg);
  assert.equal(rows.length, 2);
  assert.equal(rows[0]?.eventId, "ev-2");
  assert.equal(rows[0]?.isCurrent, true);
  assert.equal(rows[0]?.canRevert, false);
  assert.equal(rows[1]?.eventId, "ev-1");
  assert.equal(rows[1]?.isCurrent, false);
  assert.equal(rows[1]?.canRevert, true);

  const olderRow = rows[1]!;
  assert.deepEqual(revertDraftParams("proj-1", olderRow), {
    project_id: "proj-1",
    form: "single_role_direct",
    changes: JSON.stringify({ departments: { engineering: { target: "只管先做" } } }),
  });

  const preview = revertConfirmView({
    row: olderRow,
    currentOrganization: threeOrg,
    draft: {
      project_id: "proj-1",
      organization: singleOrg,
      rejections: [],
      reminders: [],
      finishes: "开环完成：没有人核验，工程交出成果即完成",
      open_loop: true,
      discarded: ["已丢弃不适用的职能覆盖"],
    },
  });
  assert.equal(preview.blocked, false);
  assert.equal(preview.isOpenLoop, true);
  assert.match(preview.finishesText, /开环完成/);
  assert.ok(preview.diffLines.some((line) => line.includes("three_departments → single_role_direct")));
  assert.ok(preview.discarded.length > 0);

  const payload = revertAdoptPayload({
    projectId: "proj-1",
    row: olderRow,
    baseVersion: "v3",
    reason: "",
  });
  assert.equal(payload.mode, "advanced");
  assert.equal(payload.form, "single_role_direct");
  assert.equal(payload.base_version, "v3");
  assert.ok(payload.reason.length > 0);

  const conflict = formatOrgCommandProblem({
    kind: "rejected",
    rejection: {
      command_id: "cmd-1",
      reason: "stale_base",
      current_version: "v4",
      message: "版本已更新",
    },
  });
  assert.equal(conflict.refreshed, true);
  assert.match(conflict.message, /v4/);
});
