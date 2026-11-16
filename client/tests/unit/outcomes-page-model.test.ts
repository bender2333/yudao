import assert from "node:assert/strict";
import test from "node:test";
import type {
  AcceptanceCoverageResult,
  EventDetailResult,
  FlowRecord,
  ProjectFlowResult,
  ProjectLoopResult,
  ProjectOverviewResult,
  WorkItemCard,
  WorkItemLoop,
  WorkItemMaterialsResult,
  WorkItemOrganization,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  MISSING_REVIEW_TEXT,
  NO_FILES_TEXT,
  OPEN_ENDED_TEXT,
  outcomeCardDetail,
  outcomesPageView,
  parseGitDiffLines,
} from "../../src/renderer/src/views/project/outcomes-page-model.ts";
import type { DepartmentView } from "../../src/renderer/src/views/project/organization.ts";

const DEPARTMENTS: DepartmentView[] = [
  { id: "product", label: "产品" },
  { id: "engineering", label: "工程" },
  { id: "quality", label: "质检" },
];

function ref(position: number) {
  return { position, source: "rule" as const };
}

function verifiedOrg(): WorkItemOrganization {
  return {
    form: "outcome_driven",
    routing: "loop",
    roles: [
      { id: "product", label: "产品", ref: ref(1) },
      { id: "engineering", label: "工程", ref: ref(2) },
      { id: "quality", label: "质检", ref: ref(3) },
    ],
    verifiers: [
      {
        role: "quality",
        verifies: [{ role: "engineering", outcomes: ["交付"] }],
        ref: ref(4),
      },
    ],
    completing: { id: "engineering", label: "工程", ref: ref(2) },
    watched: [
      { source: "product", recipient: "engineering", outcome: "PRD", ref: ref(5) },
      { source: "product", recipient: "quality", outcome: "PRD", ref: ref(6) },
      { source: "engineering", recipient: "quality", outcome: "交付", ref: ref(7) },
    ],
    asks: [],
    rejections: [],
  };
}

function openLoopOrg(): WorkItemOrganization {
  return {
    form: "direct",
    routing: "direct",
    roles: [{ id: "engineering", label: "工程", ref: ref(2) }],
    verifiers: [],
    completing: { id: "engineering", label: "工程", ref: ref(2) },
    watched: [],
    asks: [],
    rejections: [],
  };
}

function card(overrides: Partial<WorkItemCard> & { work_item_id: string; title: string }): WorkItemCard {
  return {
    kind: "feature",
    text: "实现核心功能",
    run_id: `run-${overrides.work_item_id}`,
    version: 1,
    created_at: "2026-11-16T01:00:00Z",
    round: 1,
    stop_reason: null,
    status: "in_progress",
    progress: {
      product_spec_revision: 1,
      delivery_revision: 1,
      delivery_product_spec_revision: 1,
      conclusion: null,
    },
    unread_events: 0,
    ...overrides,
  } as WorkItemCard;
}

function loopItem(overrides: Partial<WorkItemLoop> & { work_item_id: string }): WorkItemLoop {
  return {
    kind: "feature",
    sign: overrides.work_item_id,
    color_index: 0,
    status: "in_progress",
    department: "engineering",
    round: 1,
    run_id: `run-${overrides.work_item_id}`,
    stop_reason: null,
    progress: {
      product_spec_revision: 1,
      delivery_revision: 1,
      delivery_product_spec_revision: 1,
      conclusion: null,
    },
    organization: verifiedOrg(),
    ...overrides,
  } as WorkItemLoop;
}

function flowRec(overrides: Partial<FlowRecord> & { flow_id: string; kind: string; position: number }): FlowRecord {
  return {
    status: "recorded",
    content: "",
    direction_from: "engineering",
    direction_to: "quality",
    round: 1,
    run_id: "run-1",
    work_item_id: "w1",
    event_id: `ev-${overrides.flow_id}`,
    created_at: `2026-11-16T01:0${overrides.position}:00Z`,
    ...overrides,
  } as FlowRecord;
}

test("outcomesPageView：按时间倒序汇总、合并同事件 PRD 关注方、支持类别与事项筛选并保留项目总计", () => {
  // R1：成果库跨版本倒序呈现，同一 PRD 事件不因多关注方重复建卡，?w= 筛选同步并保留项目计数
  const overview: ProjectOverviewResult = {
    work_items: [
      card({ work_item_id: "w1", title: "用户登录功能", status: "released_unsettled" }),
      card({
        work_item_id: "w2",
        title: "快速修复样式",
        status: "released_unsettled",
        stop_reason: "open_loop",
      }),
    ],
  } as unknown as ProjectOverviewResult;

  const loop: ProjectLoopResult = {
    work_items: [
      loopItem({
        work_item_id: "w1",
        color_index: 1,
        status: "released_unsettled",
        progress: {
          product_spec_revision: 1,
          delivery_revision: 2,
          delivery_product_spec_revision: 1,
          conclusion: "release",
        },
        organization: verifiedOrg(),
      }),
      loopItem({
        work_item_id: "w2",
        color_index: 2,
        status: "released_unsettled",
        stop_reason: "open_loop",
        progress: {
          product_spec_revision: null,
          delivery_revision: 1,
          delivery_product_spec_revision: null,
          conclusion: null,
        },
        organization: openLoopOrg(),
      }),
    ],
  } as unknown as ProjectLoopResult;

  const flow: ProjectFlowResult = {
    records: [
      flowRec({
        flow_id: "ev-prd1:engineering",
        event_id: "ev-prd1",
        kind: "PRD 新版本",
        direction_from: "product",
        direction_to: "engineering",
        content: "第 1 版需求文档",
        round: 1,
        position: 1,
        created_at: "2026-11-16T01:01:00Z",
      }),
      flowRec({
        flow_id: "ev-prd1:quality",
        event_id: "ev-prd1",
        kind: "PRD 新版本",
        direction_from: "product",
        direction_to: "quality",
        content: "第 1 版需求文档",
        round: 1,
        position: 1,
        created_at: "2026-11-16T01:01:00Z",
      }),
      flowRec({
        flow_id: "ev-del1",
        event_id: "ev-del1",
        kind: "版本交付",
        direction_from: "engineering",
        direction_to: "quality",
        content: "初版登录页实现",
        round: 1,
        position: 2,
        created_at: "2026-11-16T01:02:00Z",
      }),
      flowRec({
        flow_id: "ev-def1",
        event_id: "ev-def1",
        kind: "问题反馈",
        direction_from: "quality",
        direction_to: "engineering",
        content: "密码错误缺少提示",
        round: 1,
        position: 3,
        created_at: "2026-11-16T01:03:00Z",
      }),
      flowRec({
        flow_id: "ev-del2",
        event_id: "ev-del2",
        kind: "版本交付",
        direction_from: "engineering",
        direction_to: "quality",
        content: "补全错误提示与校验",
        round: 2,
        position: 4,
        created_at: "2026-11-16T01:04:00Z",
      }),
      flowRec({
        flow_id: "ev-rel1",
        event_id: "ev-rel1",
        kind: "放行",
        direction_from: "quality",
        direction_to: null,
        content: "全部验收通过",
        round: 2,
        position: 5,
        created_at: "2026-11-16T01:05:00Z",
      }),
      flowRec({
        flow_id: "ev-w2-del",
        event_id: "ev-w2-del",
        work_item_id: "w2",
        run_id: "run-w2",
        kind: "版本交付",
        direction_from: "engineering",
        direction_to: null,
        content: "调整按钮留白",
        round: 1,
        position: 6,
        created_at: "2026-11-16T01:06:00Z",
      }),
    ],
  };

  const view = outcomesPageView({
    projectId: "proj-1",
    overview,
    loop,
    flow,
    departments: DEPARTMENTS,
  });

  // PRD 两个关注方合并成一张卡，总计：w2 交付 v1、w1 交付 v2、w1 缺陷记录 v1、w1 交付 v1、w1 PRD v1 -> 5 条
  assert.equal(view.projectCounts.total, 5);
  assert.equal(view.projectCounts.final, 3);
  assert.equal(view.projectCounts.mid, 2);
  // 严格区分放行、开环完成与打回，且打回不重复计数
  assert.equal(view.projectCounts.released, 1);
  assert.equal(view.projectCounts.openLoop, 1);
  assert.equal(view.projectCounts.rejected, 1);

  // 时间倒序
  assert.deepEqual(
    view.entries.map((e) => `${e.workItemId}:${e.kindLabel}`),
    ["w2:交付 v1", "w1:交付 v2", "w1:缺陷记录 v1", "w1:交付 v1", "w1:PRD v1"],
  );
  const prdEntry = view.entries[4];
  assert.equal(prdEntry.toLabel, "工程、质检");
  assert.equal(prdEntry.flowId, "ev-prd1:engineering");
  assert.equal(prdEntry.locateHash, "#/p/proj-1/conversation?w=w1&arrow=ev-prd1%3Aengineering");
  assert.equal(prdEntry.expectsFiles, false);

  // 类别筛选
  const finalOnly = outcomesPageView({
    projectId: "proj-1",
    overview,
    loop,
    flow,
    departments: DEPARTMENTS,
    category: "final",
  });
  assert.deepEqual(
    finalOnly.entries.map((e) => e.kindLabel),
    ["交付 v1", "交付 v2", "交付 v1"],
  );
  assert.equal(finalOnly.categories.find((c) => c.id === "mid")?.count, 2);

  // 按事项筛选保留全项目总计且只用事项标题
  const scoped = outcomesPageView({
    projectId: "proj-1",
    overview,
    loop,
    flow,
    departments: DEPARTMENTS,
    workItemId: "w2",
  });
  assert.equal(scoped.hasFilteredScope, true);
  assert.equal(scoped.selectedWorkItemTitle, "快速修复样式");
  assert.equal(scoped.scopedCounts.openLoop, 1);
  assert.equal(scoped.scopedCounts.released, 0);
  assert.equal(scoped.projectCounts.total, 5);
  assert.equal(scoped.projectCounts.released, 1);
  assert.equal(scoped.entries[0].verdictBadge.kind, "open");
  assert.equal(scoped.entries[0].verdictBadge.text, "◌ 开环完成：没有人核验");
});

test("outcomesPageView + outcomeCardDetail：直接交稿带核验打回与多轮打回逐轮对应", () => {
  // R2：直接交稿带核验只改 conclusion=rework 时标为打回；多轮打回对应各自轮次的 ReviewEntry
  const overview: ProjectOverviewResult = {
    work_items: [card({ work_item_id: "w-direct", title: "直接带核验任务" })],
  } as unknown as ProjectOverviewResult;
  const loop: ProjectLoopResult = {
    work_items: [
      loopItem({
        work_item_id: "w-direct",
        progress: {
          product_spec_revision: null,
          delivery_revision: 1,
          delivery_product_spec_revision: null,
          conclusion: "rework",
        },
        organization: verifiedOrg(),
      }),
    ],
  } as unknown as ProjectLoopResult;
  const flow: ProjectFlowResult = {
    records: [
      flowRec({
        flow_id: "d1",
        event_id: "ev-d1",
        work_item_id: "w-direct",
        kind: "版本交付",
        direction_from: "engineering",
        direction_to: "quality",
        content: "第一稿完成",
        round: 1,
        position: 1,
      }),
    ],
  };

  const view = outcomesPageView({
    projectId: "proj-1",
    overview,
    loop,
    flow,
    departments: DEPARTMENTS,
  });
  assert.equal(view.projectCounts.rejected, 1);
  assert.equal(view.projectCounts.released, 0);
  assert.equal(view.entries[0].verdictBadge.kind, "reject");
  assert.equal(view.entries[0].verdictBadge.text, "✕ 质检打回");

  // 多轮打回按轮次索引对应各自缺陷，每一轮各自读取对应的核验结论
  const multiView = outcomesPageView({
    projectId: "proj-1",
    overview: { work_items: [card({ work_item_id: "w-multi", title: "多轮打回" })] } as unknown as ProjectOverviewResult,
    loop: {
      work_items: [
        loopItem({
          work_item_id: "w-multi",
          status: "released_unsettled",
          progress: {
            product_spec_revision: 1,
            delivery_revision: 3,
            delivery_product_spec_revision: 1,
            conclusion: "release",
          },
          organization: verifiedOrg(),
        }),
      ],
    } as unknown as ProjectLoopResult,
    flow: {
      records: [
        flowRec({ flow_id: "m-d1", event_id: "ev-m-d1", work_item_id: "w-multi", kind: "版本交付", position: 1, round: 1 }),
        flowRec({
          flow_id: "m-f1",
          event_id: "ev-m-f1",
          work_item_id: "w-multi",
          kind: "问题反馈",
          direction_from: "quality",
          direction_to: "engineering",
          content: "第一轮缺空值校验",
          position: 2,
          round: 1,
        }),
        flowRec({ flow_id: "m-d2", event_id: "ev-m-d2", work_item_id: "w-multi", kind: "版本交付", position: 3, round: 2 }),
        flowRec({
          flow_id: "m-f2",
          event_id: "ev-m-f2",
          work_item_id: "w-multi",
          kind: "问题反馈",
          direction_from: "quality",
          direction_to: "engineering",
          content: "第二轮超时未提示",
          position: 4,
          round: 2,
        }),
        flowRec({ flow_id: "m-d3", event_id: "ev-m-d3", work_item_id: "w-multi", kind: "版本交付", position: 5, round: 3 }),
      ],
    },
    departments: DEPARTMENTS,
  });

  const materials: WorkItemMaterialsResult = {
    contracts: [],
    deliveries: [
      { event_id: "ev-m-d1", revision: 1, summary: "第一版", files: ["a.ts"], launch: [] },
      { event_id: "ev-m-d2", revision: 2, summary: "第二版", files: ["a.ts", "b.ts"], launch: [] },
      { event_id: "ev-m-d3", revision: 3, summary: "第三版", files: ["a.ts", "b.ts", "c.ts"], launch: [] },
    ],
    reviews: [
      { event_id: "ev-r1", verdict: "rework_engineering", rationale: "第1轮拒绝：空值崩溃", defects: [], checks: [], criteria: [] },
      { event_id: "ev-r2", verdict: "rework_engineering", rationale: "第2轮拒绝：缺少超时提示", defects: [], checks: [], criteria: [] },
      { event_id: "ev-r3", verdict: "release", rationale: "第3轮通过", defects: [], checks: [], criteria: [] },
    ],
    inputs: [],
    onboarding_rounds: [],
  } as unknown as WorkItemMaterialsResult;

  const firstDelivery = multiView.entries.find((e) => e.flowId === "m-d1")!;
  const secondDelivery = multiView.entries.find((e) => e.flowId === "m-d2")!;
  const thirdDelivery = multiView.entries.find((e) => e.flowId === "m-d3")!;

  assert.equal(
    outcomeCardDetail({
      entry: firstDelivery,
      materials,
      coverage: null,
      trials: null,
      eventDetail: null,
      departments: DEPARTMENTS,
    }).conclusion?.rationale,
    "第1轮拒绝：空值崩溃",
  );
  assert.equal(
    outcomeCardDetail({
      entry: secondDelivery,
      materials,
      coverage: null,
      trials: null,
      eventDetail: null,
      departments: DEPARTMENTS,
    }).conclusion?.rationale,
    "第2轮拒绝：缺少超时提示",
  );
  assert.equal(
    outcomeCardDetail({
      entry: thirdDelivery,
      materials,
      coverage: null,
      trials: null,
      eventDetail: null,
      departments: DEPARTMENTS,
    }).conclusion?.rationale,
    "第3轮通过",
  );
});

test("parseGitDiffLines：识别 hunk、文件头、增删与上下文行", () => {
  // R3：行级 diff 按 unified diff 规则着色拆分
  const diff = [
    "diff --git a/app.ts b/app.ts",
    "index 111..222 100644",
    "--- a/app.ts",
    "+++ b/app.ts",
    "@@ -1,3 +1,3 @@",
    " const keep = true;",
    "-const oldVal = 1;",
    "+const newVal = 2;",
  ].join("\n");

  const lines = parseGitDiffLines(diff);
  assert.deepEqual(
    lines.map((l) => l.kind),
    ["meta", "meta", "meta", "meta", "hunk", "context", "del", "add"],
  );
  assert.deepEqual(parseGitDiffLines(""), []);
  assert.deepEqual(parseGitDiffLines(null), []);
});

test("outcomeCardDetail + OutcomesPageContent SSR：渲染结构化 PRD（无缺失文件提示）、建档各轮、交付文件与 diff、逐条结论、开环完成与定位链接", async () => {
  // R1 + R2 + R3：组件端到端（SSR）渲染验证所有展示节、禁止词与定位路由
  const { createRequire } = await import("node:module");
  const fs = await import("node:fs");
  const req = createRequire(import.meta.url);
  const ts = req("typescript");
  const React = req("react");
  const { renderToStaticMarkup } = req("react-dom/server");
  (globalThis as Record<string, unknown>)["React"] = React;
  const register = (module: NodeModule, filename: string) => {
    const src = fs.readFileSync(filename, "utf8");
    const out = ts.transpileModule(src, {
      compilerOptions: {
        jsx: ts.JsxEmit.React,
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText;
    (module as unknown as { _compile(code: string, name: string): void })._compile(out, filename);
  };
  req.extensions[".tsx"] = register;
  req.extensions[".ts"] = register;
  req.extensions[".css"] = () => {};

  const {
    OutcomesPage,
    OutcomesPageContent,
    OutcomeExpandedContent,
  } = req("../../src/renderer/src/views/project/outcomes-page.tsx");
  const { trialView } = req("../../src/renderer/src/views/project/trials.tsx");

  const overview: ProjectOverviewResult = {
    work_items: [
      card({ work_item_id: "w1", title: "需求与交付事项", status: "released_unsettled" }),
      card({
        work_item_id: "w-open",
        title: "无核验直接完成事项",
        status: "released_unsettled",
        stop_reason: "open_loop",
      }),
      card({
        work_item_id: "w-ob",
        kind: "onboarding",
        title: "建档接手旧仓库",
        status: "awaiting_initial_prd",
      }),
    ],
  } as unknown as ProjectOverviewResult;

  const loop: ProjectLoopResult = {
    work_items: [
      loopItem({
        work_item_id: "w1",
        status: "released_unsettled",
        color_index: 0,
        progress: {
          product_spec_revision: 2,
          delivery_revision: 2,
          delivery_product_spec_revision: 2,
          conclusion: "release",
        },
        organization: verifiedOrg(),
      }),
      loopItem({
        work_item_id: "w-open",
        status: "released_unsettled",
        stop_reason: "open_loop",
        color_index: 1,
        progress: {
          product_spec_revision: null,
          delivery_revision: 1,
          delivery_product_spec_revision: null,
          conclusion: null,
        },
        organization: openLoopOrg(),
      }),
      loopItem({
        work_item_id: "w-ob",
        kind: "onboarding",
        status: "awaiting_initial_prd",
        color_index: 2,
        progress: {
          product_spec_revision: null,
          delivery_revision: null,
          delivery_product_spec_revision: null,
          conclusion: null,
        },
        organization: verifiedOrg(),
      }),
    ],
  } as unknown as ProjectLoopResult;

  const flow: ProjectFlowResult = {
    records: [
      flowRec({
        flow_id: "w1-prd1",
        event_id: "ev-w1-prd1",
        work_item_id: "w1",
        kind: "PRD 新版本",
        direction_from: "product",
        direction_to: "engineering",
        content: "第 1 版规格",
        position: 1,
        created_at: "2026-11-16T02:01:00Z",
      }),
      flowRec({
        flow_id: "w1-prd2",
        event_id: "ev-w1-prd2",
        work_item_id: "w1",
        kind: "PRD 新版本",
        direction_from: "product",
        direction_to: "engineering",
        content: "第 2 版规格",
        position: 2,
        round: 2,
        created_at: "2026-11-16T02:02:00Z",
      }),
      flowRec({
        flow_id: "w1-del1",
        event_id: "ev-w1-del1",
        work_item_id: "w1",
        kind: "版本交付",
        direction_from: "engineering",
        direction_to: "quality",
        content: "初版代码",
        position: 3,
        round: 1,
        created_at: "2026-11-16T02:03:00Z",
      }),
      flowRec({
        flow_id: "w1-del2",
        event_id: "ev-w1-del2",
        work_item_id: "w1",
        kind: "版本交付",
        direction_from: "engineering",
        direction_to: "quality",
        content: "正式交付代码",
        position: 4,
        round: 2,
        created_at: "2026-11-16T02:04:00Z",
      }),
      flowRec({
        flow_id: "w1-rel",
        event_id: "ev-w1-rel",
        work_item_id: "w1",
        kind: "放行",
        direction_from: "quality",
        direction_to: null,
        content: "放行",
        position: 5,
        round: 2,
        created_at: "2026-11-16T02:05:00Z",
      }),
      flowRec({
        flow_id: "wopen-del",
        event_id: "ev-wopen-del",
        work_item_id: "w-open",
        run_id: "run-w-open",
        kind: "版本交付",
        direction_from: "engineering",
        direction_to: null,
        content: "开环直出稿件",
        position: 6,
        round: 1,
        created_at: "2026-11-16T02:06:00Z",
      }),
    ],
  };

  // 1. 入口组件可安全挂载（签名与 #1809 一致）
  const shellHtml = renderToStaticMarkup(
    React.createElement(OutcomesPage, {
      app: { viewSync: null },
      route: { page: "outcomes", projectId: "proj-1", workItemId: null, at: null, arrow: null, trialCaseId: null, section: null },
      organization: null,
      departments: DEPARTMENTS,
      onNavigate: () => {},
    }),
  );
  assert.match(shellHtml, /成果库/);
  assert.match(shellHtml, /✓ 独立放行 0/);

  // 2. 完整页列表渲染：独立放行、开环完成、建档初始 PRD、事项标题、定位链接
  const pageHtml = renderToStaticMarkup(
    React.createElement(OutcomesPageContent, {
      app: {},
      projectId: "proj-1",
      workItemId: null,
      departments: DEPARTMENTS,
      overviewState: { data: overview, loading: false, error: null },
      loopState: { data: loop, loading: false, error: null },
      flowState: { data: flow, loading: false, error: null },
      onNavigate: () => {},
    }),
  );
  assert.match(pageHtml, /✓ 独立放行 1/);
  assert.match(pageHtml, /◌ 开环完成 1/);
  assert.match(pageHtml, /建档初始 PRD/);
  assert.match(pageHtml, /需求与交付事项/);
  assert.match(pageHtml, /无核验直接完成事项/);
  assert.match(pageHtml, /建档接手旧仓库/);
  assert.match(pageHtml, /在对话与循环图里定位/);
  assert.match(pageHtml, /#\/p\/proj-1\/conversation\?w=w1&amp;arrow=w1-del2/);
  // 不泄漏内部 raw work_item_id 作为显示名称（仅 value attribute 存在）
  assert.doesNotMatch(pageHtml, />w1</);

  const view = outcomesPageView({
    projectId: "proj-1",
    overview,
    loop,
    flow,
    departments: DEPARTMENTS,
  });

  // 3. 展开结构化 PRD v2（含差异且无「这一版没有附文件清单」）
  const w1Materials: WorkItemMaterialsResult = {
    contracts: [
      {
        event_id: "ev-w1-prd1",
        spec_event_id: "ev-w1-prd1",
        status: "superseded",
        prd: {
          spec_id: "spec-1",
          spec_revision: 1,
          spec_status: "superseded",
          spec_event_id: "ev-w1-prd1",
          spec_hash: "ph1",
          parent_hash: null,
          input_version: 1,
          accepted_inputs: [
            { version: 1, kind: "new_feature", text: "原始需求文字", created_event_id: "ev-in1" },
          ],
          goal: "初始目标",
          non_goals: ["不做后台"],
          boundaries: ["仅前端"],
          constraints: ["不改路由"],
          requirements: ["展示列表"],
          acceptance_criteria: ["AC-1 列表可用"],
          requirement_mapping: [{ requirement: 1, criteria: ["AC-1"], gap: null }],
          fatal_conditions: ["空白白屏"],
          decisions: [],
          decision_changes: [],
          change_record: null,
        },
      },
      {
        event_id: "ev-w1-prd2",
        spec_event_id: "ev-w1-prd2",
        status: "active",
        prd: {
          spec_id: "spec-1",
          spec_revision: 2,
          spec_status: "active",
          spec_event_id: "ev-w1-prd2",
          spec_hash: "ph2",
          parent_hash: "ph1",
          input_version: 1,
          accepted_inputs: [
            { version: 1, kind: "new_feature", text: "原始需求文字", created_event_id: "ev-in1" },
          ],
          goal: "补齐筛选与 diff 目标",
          non_goals: ["不做后台", "不改服务端"],
          boundaries: ["仅前端"],
          constraints: ["不改路由"],
          requirements: ["展示列表与筛选"],
          acceptance_criteria: ["AC-1 列表可用", "AC-2 筛选切换"],
          requirement_mapping: [{ requirement: 1, criteria: ["AC-1", "AC-2"], gap: "缺边界用例" }],
          fatal_conditions: ["空白白屏"],
          decisions: [
            {
              decision_id: "DEC-1",
              content_hash: "h1",
              statement: "单独卡片呈现每版",
              rationale: "方便回溯",
              product_spec_hash: "ph2",
              created_event_id: "ev-dec1",
            },
          ],
          decision_changes: [
            {
              decision_hash: "h1",
              disposition: "confirmed",
              rationale: "延续该原则",
            },
          ],
          change_record: {
            changed: ["新增筛选条"],
            retained: ["保留倒序"],
            retired: [],
            rationale: "用户需要筛选",
          },
        },
      },
    ],
    deliveries: [
      { event_id: "ev-w1-del1", revision: 1, summary: "第一版代码", files: ["src/a.ts"], launch: [] },
      {
        event_id: "ev-w1-del2",
        revision: 2,
        summary: "正式交付实现",
        files: ["src/a.ts", "src/b.ts"],
        launch: [{ name: "客户端构建", kind: "build", commands: { windows: ["npm run build"] } }],
      },
    ],
    reviews: [
      {
        event_id: "ev-w1-rev",
        verdict: "release",
        rationale: "所有条目标注均已核验通过",
        defects: [],
        checks: [{ command: "npm test", exit_code: 0, passed: true }],
        trial_cases: [{ case_id: "case-1", title: "打开页面验证列表", result: "passed" }],
        criteria: [
          {
            criterion: "AC-1 列表可用",
            method: "execute_run",
            result: "pass",
            summary: "页面能显示列表",
            check_names: ["npm test"],
            case_ids: ["case-1"],
          },
        ],
      },
    ],
    inputs: [],
    onboarding_rounds: [],
  } as unknown as WorkItemMaterialsResult;

  const prdEntry = view.entries.find((e) => e.flowId === "w1-prd2")!;
  const prdHtml = renderToStaticMarkup(
    React.createElement(OutcomeExpandedContent, {
      app: {},
      entry: prdEntry,
      departments: DEPARTMENTS,
      materials: w1Materials,
      eventDetail: null,
      coverage: null,
      trials: trialView(null, null),
    }),
  );
  for (const expected of [
    "结构化 PRD · 第 2 版",
    "已吸收的来源",
    "原始需求文字",
    "补齐筛选与 diff 目标",
    "不做后台",
    "仅前端",
    "不改路由",
    "展示列表与筛选",
    "缺边界用例",
    "AC-2 筛选切换",
    "空白白屏",
    "单独卡片呈现每版",
    "新增筛选条",
    "与上一版 PRD 差异",
  ]) {
    assert.ok(prdHtml.includes(expected), `PRD 展开内容缺少 ${expected}`);
  }
  assert.ok(!prdHtml.includes(NO_FILES_TEXT), "PRD 卡片不得显示「这一版没有附文件清单」");

  // 4. 展开交付 v2：文件清单、下载（含 git diff 着色）、逐条结论表、试用用例与覆盖
  const delEntry = view.entries.find((e) => e.flowId === "w1-del2")!;
  const eventDetail: EventDetailResult = {
    event: {},
    artifacts: {
      git_version: {
        diff: "diff --git a/src/b.ts b/src/b.ts\n@@ -0,0 +1,2 @@\n+export const ok = true;\n-export const old = false;",
      },
    },
  };
  const coverage: AcceptanceCoverageResult = {
    run_id: "run-w1",
    work_item_id: "w1",
    verdict: "release",
    review_event_id: "ev-w1-rev",
    revision: 2,
    numbers: {
      criteria_total: 1,
      executable: 1,
      covered: 1,
      coverage_ratio: 1,
    },
    criteria: [],
  } as unknown as AcceptanceCoverageResult;
  const trialData = trialView(
    {
      department: "quality",
      sessions: [
        {
          session_id: "ses-1",
          department: "quality",
          kind: "web",
          launch_name: "前端预览",
          tree_digest: "sha256:" + "b".repeat(64),
          source: "delivery_snapshot",
          delivery_snapshot_hash: "sha256:" + "b".repeat(64),
          matches_delivery_snapshot: true,
          started_at: "2026-11-16T02:04:10Z",
          ended_at: "2026-11-16T02:04:40Z",
          end_reason: "stopped",
          status: "ended",
        },
      ],
      cases: [
        {
          case_id: "case-1",
          department: "quality",
          session_id: "ses-1",
          trial_session_id: "ses-1",
          product_spec_hash: "sha256:" + "c".repeat(64),
          criteria: [{ criterion: "AC-1", text: "列表可用" }],
          title: "打开页面验证列表",
          plan: ["访问成果库页面"],
          expected: "列表中显示预期项",
          status: "concluded",
          result: "passed",
          observed: "列表中显示预期项",
          reason: "",
          evidence_steps: ["call-1"],
          steps: [
            {
              identity: "call-1",
              tool: "browser_snapshot",
              step_id: 1,
              activation_id: "act-1",
              status: "completed",
              ok: true,
              error: null,
              input: {},
              screenshots: [
                {
                  kind: "screenshot",
                  content_hash: "sha256:" + "a".repeat(64),
                  path: "artifacts/shot.png",
                  media_type: "image/png",
                },
              ],
              accessibility: "成果列表",
              request_had_images: true,
              evidence: true,
            },
          ],
        },
      ],
    },
    null,
  );

  const deliveryHtml = renderToStaticMarkup(
    React.createElement(OutcomeExpandedContent, {
      app: {},
      entry: delEntry,
      departments: DEPARTMENTS,
      materials: w1Materials,
      eventDetail,
      coverage,
      trials: trialData,
    }),
  );
  for (const expected of [
    "正式交付实现",
    "src/a.ts",
    "src/b.ts",
    "新增 1 个：src/b.ts",
    "@@ -0,0 +1,2 @@",
    "+export const ok = true;",
    "-export const old = false;",
    "质检放行这一版",
    "所有条目标注均已核验通过",
    "AC-1 列表可用",
    "打开页面验证列表",
  ]) {
    assert.ok(deliveryHtml.includes(expected), `交付展开内容缺少 ${expected}`);
  }
  assert.ok(!deliveryHtml.includes(MISSING_REVIEW_TEXT));

  // 5. 展开开环完成事项：只写「开环完成：没有人核验」，不渲染空核验表
  const openEntry = view.entries.find((e) => e.flowId === "wopen-del")!;
  const openMaterials: WorkItemMaterialsResult = {
    contracts: [],
    deliveries: [{ event_id: "ev-wopen-del", revision: 1, summary: "开环交付物", files: ["README.md"], launch: [] }],
    reviews: [],
    inputs: [],
    onboarding_rounds: [],
  } as unknown as WorkItemMaterialsResult;
  const openHtml = renderToStaticMarkup(
    React.createElement(OutcomeExpandedContent, {
      app: {},
      entry: openEntry,
      departments: DEPARTMENTS,
      materials: openMaterials,
      eventDetail: null,
      coverage: null,
      trials: trialView(null, null),
    }),
  );
  assert.ok(openHtml.includes(OPEN_ENDED_TEXT));
  assert.ok(!openHtml.includes("<table"));
  assert.ok(!openHtml.includes("放行"));

  // 6. 展开建档初始 PRD：各轮、结构、修订说明、基线核验提示（没有经过基线核验）与裁决记录
  const obEntry = view.entries.find((e) => e.kind === "onboarding")!;
  const obMaterials: WorkItemMaterialsResult = {
    contracts: [],
    deliveries: [],
    reviews: [],
    inputs: [],
    onboarding_rounds: [
      {
        round: 1,
        run_id: "run-ob-1",
        candidate_event_id: "ev-ob-1",
        proposed_at: "2026-11-16T02:00:00Z",
        prd: "建档初始 PRD 正文",
        structure: "client/ + harness/",
        overview: "已有前后端基础骨架",
        revision_note: "补充测试说明",
        baseline_review: { verified: false, missing_capabilities: [], baseline_checks: [], other_failures: [] },
        baseline_review_note: "没有经过基线核验",
        decisions: [{ outcome: "confirm", option: "通过首轮建档", note: "准许进入正式流程", decided_at: "2026-11-16T02:00:30Z" }],
      },
    ],
  } as unknown as WorkItemMaterialsResult;
  const obHtml = renderToStaticMarkup(
    React.createElement(OutcomeExpandedContent, {
      app: {},
      entry: obEntry,
      departments: DEPARTMENTS,
      materials: obMaterials,
      eventDetail: null,
      coverage: null,
      trials: trialView(null, null),
    }),
  );
  for (const expected of [
    "建档初始 PRD 各轮提案与确认",
    "第 1 轮",
    "没有经过基线核验",
    "建档初始 PRD 正文",
    "client/ + harness/",
    "已有前后端基础骨架",
    "补充测试说明",
    "准许进入正式流程",
  ]) {
    assert.ok(obHtml.includes(expected), `建档初始 PRD 展开内容缺少 ${expected}`);
  }
});
