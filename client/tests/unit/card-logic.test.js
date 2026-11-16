// 决定卡片纯逻辑的单元测试（原型 v8 设计说明第 6 节，工单 #175）：
// 材料按决定种类整理、挡住的对象、等待时长、「在项目中查看」的目标、按发出时间排列，
// 以及给像素画面用的纯文字版本与页面卡片共用同一份材料。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import {
  answeredRoleChoiceSummary,
  blockedText,
  buildRoleChoiceAnswerArgs,
  decisionLinks,
  defaultRoleChoiceAnswers,
  face,
  materialRows,
  missingNoteText,
  prepareRoleChoiceSubmit,
  reconcileRoleChoiceAnswers,
  roleChoiceActions,
  roleChoiceQuestions,
  sortByRequested,
  viewHref,
  waitedSeconds,
} from "../../src/renderer/src/views/decisions/card-logic.ts";
import { DECISION_BLOCKS, DECISION_KIND, RECOVERY_STATE } from "../../src/renderer/src/views/project/labels.ts";
import { itemThread, threadDecisionView } from "../../src/renderer/src/views/project/thread-model.ts";

function decision(overrides) {
  return {
    decision_id: "d1",
    project_id: "p1",
    work_item_id: "w1",
    run_id: "r1",
    kind: "model_unavailable",
    blocks: "run",
    version: 3,
    status: "open",
    requested_at: "2026-10-02T10:00:00Z",
    blocked: { work_item_id: "w1", queued_after: 2 },
    request: {
      kind: "model_unavailable",
      blocks: "run",
      options: [
        { id: "continue", label: "继续执行" },
        { id: "stop", label: "停止事项" },
      ],
      description: "工程部门的模型引用无法使用",
      facts: [],
      department: "engineering",
      target: { model_id: "glm-4.6" },
      reason: "provider_unavailable",
      message: "Missing configuration: provider credential",
    },
    answer: null,
    ...overrides,
  };
}

test("待恢复的决定：材料列出部门、模型与具体问题", () => {
  const rows = materialRows(decision());
  const map = Object.fromEntries(rows.map((row) => [row.term, row.value]));
  assert.equal(map["职能"], "工程");
  assert.equal(map["模型"], "glm-4.6");
  assert.equal(map["具体问题"], "Missing configuration: provider credential");
  assert.equal(map["说明"], "工程部门的模型引用无法使用");
});


test("挡住的对象：写明被阻塞的事项与排在后面的事项数量，事项写标题不写标识", () => {
  assert.deepEqual(blockedText(decision(), "实现逐行处理"), { text: "挡住「实现逐行处理」，同一项目中排在它后面的事项 2 个", muted: false });
  const idle = decision({ blocks: "", blocked: null });
  assert.deepEqual(blockedText(idle, "实现逐行处理"), { text: "不挡住事项", muted: true });
  // 事项标题取不到时不拿事项标识凑数（工单 #802，原型 v11 的 blocksText 同一写法）
  assert.deepEqual(blockedText(decision(), ""), { text: "同一项目中排在它后面的事项 2 个", muted: false });
  const alone = decision({ blocked: { work_item_id: "w1", queued_after: 0 } });
  assert.deepEqual(blockedText(alone, ""), { text: "挡住本事项", muted: false });
});





test("给像素画面用的纯文字版本与页面卡片共用同一份材料", () => {
  const now = new Date("2026-10-02T10:01:00Z").getTime();
  const card = face(decision(), now, { projectName: "文本工具", workItemTitle: "实现逐行处理" });
  assert.equal(card.id, "d1");
  assert.equal(card.title, "模型引用无法使用，等待恢复");
  assert.equal(card.blocks, "挡住「实现逐行处理」，同一项目中排在它后面的事项 2 个");
  assert.deepEqual(card.rows, materialRows(decision()));
  assert.deepEqual(card.options.map((option) => option.id), ["continue", "stop"]);
});

test("给画面用的卡片内容带上决定版本、项目与事项、链接与选项的说明标记", () => {
  const now = new Date("2026-10-02T10:01:00Z").getTime();
  const card = face(decision({ request: { ...decision().request, options: [{ id: "revise", label: "提出修改", note_required: true }] } }), now, {
    projectName: "文本工具",
    workItemTitle: "实现逐行处理",
  });
  assert.equal(card.version, 3);
  assert.equal(card.work_item_id, "w1");
  assert.equal(card.where, "文本工具 · 实现逐行处理");
  assert.equal(card.waited, "已等待 60 秒");
  // 「前往本项目的职能详情」落在那个部门的详情页上（工单 #1161、#1713）：
  // 设置页不再有「职能设置」一节，模型与 Prompt 在职能详情页改
  assert.deepEqual(card.links.map((link) => link.href), [
    "#/sys/models",
    "#/p/p1/dept-detail/engineering?w=w1",
  ]);
  assert.deepEqual(card.links.map((link) => link.label), ["前往模型管理", "前往本项目的职能详情"]);
  assert.equal(card.options[0].note_required, true);
  // 没有给出名称时只写项目名，不写事项标识（工单 #802）
  const bare = face(decision(), now);
  assert.equal(bare.where, "p1");
  assert.ok(!bare.where.includes("w1"), "页面上不出现事项标识");
  assert.equal(bare.blocks, "同一项目中排在它后面的事项 2 个");
});

test("要求写说明的选项在说明为空时不提交，有说明时通过", () => {
  // 「提出修改」要求写明修改意见（工单 #136 的决定选项标记 note_required）：说明为空时给出提示，
  // 页面卡片与像素画面都用这一条规则，写了说明才提交。空白字符不算说明。
  const revise = { label: "提出修改", note_required: true };
  const confirm = { label: "确认", note_required: false };
  assert.equal(missingNoteText(revise, ""), "「提出修改」需要在说明里写明修改意见");
  assert.equal(missingNoteText(revise, "   \n "), "「提出修改」需要在说明里写明修改意见");
  assert.equal(missingNoteText(revise, "第三条要求缺少异常处理"), "");
  // 标记缺省（旧的决定请求）与标记为假时不阻止提交
  assert.equal(missingNoteText({ label: "确认" }, ""), "");
  assert.equal(missingNoteText(confirm, ""), "");
  assert.equal(missingNoteText(confirm, "补充说明"), "");
});

// 初始 PRD 的决定卡片（工单 #138，设计第 3.2 节）：轮次、PRD 与结构说明的工件引用、
// 基线核验汇总、快照来源；两个链接都指向资料页
function initialPrd(overrides) {
  const request = {
    kind: "initial_prd",
    blocks: "work_item",
    options: [
      { id: "confirm", label: "确认" },
      { id: "revise", label: "提出修改", note_required: true },
    ],
    description: "确认第 2 轮建档的初始 PRD",
    work_item_id: "w1",
    round: 2,
    prd: {
      event_id: "ev1",
      content_hash: "0123456789abcdef",
      prd_ref: { kind: "prd", content_hash: "0123456789abcdef", path: "PRD.md", media_type: "text/markdown" },
      summary: null,
    },
    structure: {
      event_id: "ev2",
      content_hash: "abcdef0123456789",
      structure_ref: { kind: "structure", content_hash: "abcdef0123456789", path: "STRUCTURE.md", media_type: "text/markdown" },
      code_tree_digest: "fedcba9876543210",
    },
    baseline_review: {
      event_id: "ev3",
      content_hash: "5f5f5f5f5f5f5f5f",
      conclusions: [
        { requirement: "read the project layout", status: "verified", evidence: "smoke" },
        { requirement: "name the command", status: "existing_defect", evidence: "README 没有写" },
        { requirement: "tests run", status: "read_only", evidence: "没有跑" },
      ],
      omissions: [{ capability: "logging", location: "src/echo.py" }],
      checks: [{ name: "smoke", command: "python -m pytest", exit_code: 0, summary: "通过", snapshot_hash: "1f1f1f1f1f1f1f1f" }],
      other_failures: [],
    },
    overview_ref: { kind: "overview", content_hash: "9e9e9e9e9e9e9e9e", path: "OVERVIEW.md", media_type: "text/markdown" },
    snapshot: {
      source: "D:/source/echo",
      tree_digest: "2a2a2a2a2a2a2a2a",
      files: ["README.md", "src/echo.py", "tests/test_echo.py"],
      directories: ["src", "tests"],
      tree_ref: { kind: "tree", content_hash: "2a2a2a2a2a2a2a2a", path: "tree.json", media_type: "application/json" },
      provenance: { commit: "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d", branch: "main", dirty: true },
      bytes: 1024,
    },
    revision_note_ref: { kind: "revision_note", content_hash: "3c3c3c3c3c3c3c3c", path: "REVISION_NOTE.md", media_type: "text/markdown" },
    ...overrides,
  };
  return decision({ kind: "initial_prd", request, work_item_id: "w1" });
}

test("初始 PRD 的材料列出轮次、两个工件引用、基线核验汇总与快照来源", () => {
  const rows = materialRows(initialPrd());
  const map = Object.fromEntries(rows.map((row) => [row.term, row.value]));
  assert.equal(map["轮次"], "第 2 轮");
  // PRD 摘要在合同里可为空（后端当前不上报摘要）：界面不伪造摘要文字
  assert.equal(map["初始 PRD 摘要"], "没有摘要");
  assert.equal(map["PRD.md 工件"], "PRD.md");
  assert.equal(map["PRD 指纹"], "0123456789ab");
  assert.equal(map["现有结构说明"], "STRUCTURE.md");
  assert.equal(map["结构说明指纹"], "fedcba987654");
  assert.equal(map["基线核验汇总"], "核验 3 条要求；已核实 1 条；只读 1 条；现有缺陷 1 条；遗漏的能力 1 条；其他失败 0 条");
  assert.equal(map["快照来源"], "D:/source/echo");
  assert.equal(map["快照提交"], "git 提交 1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d（分支 main，有未提交的修改）");
  assert.equal(map["快照规模"], "文件 3 项，目录 2 项，共 1,024 字节");
  assert.equal(map["说明"], "确认第 2 轮建档的初始 PRD");
  // 修改意见的工件路径是内部引用，不显示给用户；原文由卡片按事项补一行（第 138 号工单）
  assert.equal(map["修改意见工件"], undefined);
});

test("初始 PRD 的快照没有 git 仓库时写明采集时的目录内容", () => {
  const rows = materialRows(initialPrd({
    snapshot: { source: "D:/source/echo", files: ["README.md"], directories: [], provenance: null, bytes: 12 },
  }));
  const map = Object.fromEntries(rows.map((row) => [row.term, row.value]));
  assert.equal(map["快照提交"], "没有 git 仓库，快照采集时的目录内容");
  assert.equal(map["快照规模"], "文件 1 项，目录 0 项，共 12 字节");
});


test("初始 PRD 的卡片材料与给像素画面的纯文字版本共用", () => {
  const now = new Date("2026-10-02T10:01:00Z").getTime();
  const card = face(initialPrd(), now);
  assert.deepEqual(card.rows, materialRows(initialPrd()));
  assert.deepEqual(card.links.map((link) => link.label), ["PRD.md", "STRUCTURE.md"]);
});

// 工单 #1715：资料页收进对话页，决定卡片上不再生成资料页的地址。
// 建档的工件在「建档事项的初始 PRD」那条箭头的面板里看，链接落到建档事项的对话页。
test("初始 PRD 的两个工件链接落在建档事项的对话页，不再指向资料页", () => {
  const card = face(initialPrd(), new Date("2026-10-02T10:01:00Z").getTime());
  assert.deepEqual(card.links.map((link) => link.href), [
    "#/p/p1/conversation?w=w1",
    "#/p/p1/conversation?w=w1",
  ]);
  // 卡片自己的「在项目中查看」同样落到对话页（初始 PRD 按建档的轮次看）
  assert.equal(viewHref(initialPrd()), "#/p/p1/conversation?w=w1");
  assert.ok(!card.links.some((link) => link.href.includes("/materials")), "卡片上不应再有资料页的地址");
});

// 工单 #1715：没有事项的决定落到项目的对话页（概览页已收进对话）
test("没有事项的决定落到项目的对话页", () => {
  const projectWide = decision({ kind: "release_check_failed", work_item_id: null, request: { kind: "release_check_failed", blocks: "", options: [], description: "有检查没通过" } });
  assert.equal(viewHref(projectWide), "#/p/p1/conversation");
  assert.ok(!viewHref(projectWide).includes("/overview"), "卡片上不应再生成概览页的地址");
});

test("界面不再包含已删除的 unknown_action 与 pending_verification", () => {
  assert.equal(DECISION_KIND.unknown_action, undefined);
  assert.equal(RECOVERY_STATE.pending_verification, undefined);
});

test("质检无法核验的决定卡片逐条列出无法核验的条件与原因", () => {
  // 浏览器与 computer use docs/design/browser-and-computer-use.md「无法核验」（工单 #1179）：说明列出每条无法核验的验收条件与原因
  const rows = materialRows(decision({
    kind: "qa_cannot_verify",
    request: {
      kind: "qa_cannot_verify",
      blocks: "run",
      options: [{ id: "re_verify", label: "重新核验" }, { id: "stop", label: "停止事项" }],
      description: "质检无法核验这些验收条件：AC1（质检的模型不支持图像输入）。",
      facts: ["AC1"],
      department: "quality",
      criteria: [{ criterion: "AC1", note: "质检的模型不支持图像输入" },
                 { criterion: "AC2", note: "执行位置没有安装浏览器" }],
    },
  }));
  const map = Object.fromEntries(rows.map((row) => [row.term, row.value]));
  assert.equal(map["职能"], "质检");
  assert.equal(map["AC1"], "质检的模型不支持图像输入");
  assert.equal(map["AC2"], "执行位置没有安装浏览器");
  assert.equal(map["说明"], "质检无法核验这些验收条件：AC1（质检的模型不支持图像输入）。");
});


test("初始 PRD 的材料逐条列出要求与验收标准的对应声明", () => {
  // 工单 #1349：决定卡片要让人看到哪条要求对应哪条验收标准、哪条标了 gap 原因
  const request = {
    kind: "initial_prd",
    blocks: "work_item",
    options: [{ id: "confirm", label: "确认" }],
    description: "确认第 1 轮建档的初始 PRD",
    work_item_id: "w1",
    round: 1,
    prd: {
      event_id: "ev1",
      content_hash: "0123456789abcdef",
      prd_ref: { kind: "prd", content_hash: "0123456789abcdef", path: "PRD.md", media_type: "text/markdown" },
      summary: "目标：接入已有项目",
      requirements: ["print the argument", "explain the usage"],
      acceptance_criteria: ["prints the argument", "prints help"],
      requirement_mapping: [
        { requirement: 1, criteria: ["AC1", "AC2"], gap: null },
        { requirement: 2, criteria: [], gap: "no host check yet" },
      ],
    },
    structure: {},
    baseline_review: {},
    snapshot: {},
  };
  const rows = materialRows(decision({ kind: "initial_prd", request, work_item_id: "w1" }));
  const map = Object.fromEntries(rows.map((row) => [row.term, row.value]));
  assert.equal(map["要求 1"], "AC1、AC2（print the argument）");
  assert.equal(map["要求 2"], "未写验收标准：no host check yet（explain the usage）");
});

test("旧事件的初始 PRD 没有对应声明时不出要求行", () => {
  const rows = materialRows(initialPrd());
  assert.equal(rows.some((row) => row.term.startsWith("要求 ")), false);
});

// ---------------------------------------------------------------------------
// role_choice 多题前沿决定请求（工单 #1802）

function roleChoiceDecision(overrides = {}) {
  const baseRequest = {
    kind: "role_choice",
    blocks: "round",
    options: [
      { id: "submit", label: "提交回答" },
      { id: "recommended", label: "全部采用推荐" },
    ],
    description: "请确认两项前置配置选择",
    facts: [],
    department: "product",
    input_version: 1,
    round: 1,
    note: "默认采用推荐项即可直接运行",
    questions: [
      {
        id: "q1",
        question: "配置格式采用哪一种？",
        options: [
          { id: "json", label: "JSON 文件", description: "零额外依赖" },
          { id: "toml", label: "TOML 文件", description: null },
        ],
        recommended: "json",
        rationale: "标准库可直接读写",
      },
      {
        id: "q2",
        question: "默认端口选哪个？",
        options: [
          { id: "8080", label: "8080 端口" },
          { id: "9000", label: "9000 端口" },
        ],
        recommended: "8080",
        rationale: "本地调试常用端口",
      },
    ],
  };
  const { request: requestOverrides, ...restOverrides } = overrides;
  return decision({
    decision_id: "dec_rc_1",
    kind: "role_choice",
    blocks: "round",
    request: { ...baseRequest, ...(requestOverrides ?? {}) },
    ...restOverrides,
  });
}

test("role_choice 阻塞范围为 round 时提示仅暂停当前职能本轮工作，不变更原有 run 提示", () => {
  assert.deepEqual(blockedText(roleChoiceDecision(), "导出报表"), {
    text: "仅暂停「导出报表」中产品的本轮工作，其余职能与事项照常推进",
    muted: false,
  });
  assert.deepEqual(blockedText(roleChoiceDecision({ blocked: null }), ""), {
    text: "仅暂停产品的本轮工作，其余职能与事项照常推进",
    muted: false,
  });
  assert.equal(DECISION_BLOCKS.round, "本轮工作");
  assert.equal(DECISION_KIND.role_choice, "角色向你提问，等待选择");
  // 原有 run 阻塞文案保持不变
  assert.deepEqual(blockedText(decision(), "实现逐行处理"), {
    text: "挡住「实现逐行处理」，同一项目中排在它后面的事项 2 个",
    muted: false,
  });
});

test("role_choice 解析题目、推荐预选、改选合并与两类提交载荷", () => {
  const dec = roleChoiceDecision();
  const questions = roleChoiceQuestions(dec);
  assert.equal(questions.length, 2);
  assert.equal(questions[0].question, "配置格式采用哪一种？");
  assert.equal(questions[0].rationale, "标准库可直接读写");
  assert.deepEqual(questions[0].options, [
    { id: "json", label: "JSON 文件", description: "零额外依赖", recommended: true },
    { id: "toml", label: "TOML 文件", description: null, recommended: false },
  ]);

  // 默认按每题 recommended 预选
  const defaults = defaultRoleChoiceAnswers(questions);
  assert.deepEqual(defaults, { q1: "json", q2: "8080" });

  // 改选第一题后，刷新题目仍保留第一题有效改选并补全未选题目
  const merged = reconcileRoleChoiceAnswers(questions, { q1: "toml", q_old: "x" });
  assert.deepEqual(merged, { q1: "toml", q2: "8080" });

  // 「提交回答」携带逐题 answers 与可选 note
  assert.deepEqual(buildRoleChoiceAnswerArgs(dec, "submit", merged, "  按项目需求选择  "), {
    decision_id: "dec_rc_1",
    option: "submit",
    answers: { q1: "toml", q2: "8080" },
    note: "按项目需求选择",
    base_version: 3,
  });

  // 「全部采用推荐」发送 option="recommended"，省略空 note 与 answers
  assert.deepEqual(buildRoleChoiceAnswerArgs(dec, "recommended", merged, "   "), {
    decision_id: "dec_rc_1",
    option: "recommended",
    base_version: 3,
  });

  const actions = roleChoiceActions(dec);
  assert.equal(actions.submitLabel, "提交回答");
  assert.equal(actions.recommendedLabel, "全部采用推荐");
  assert.deepEqual(prepareRoleChoiceSubmit(dec, actions, "submit", merged, "  说明  "), {
    missing: "",
    payload: {
      decision_id: "dec_rc_1",
      option: "submit",
      answers: { q1: "toml", q2: "8080" },
      note: "说明",
      base_version: 3,
    },
  });
  assert.deepEqual(
    prepareRoleChoiceSubmit(dec, { ...actions, submitNoteRequired: true }, "submit", merged, " "),
    { missing: "「提交回答」需要在说明里写明修改意见", payload: null },
  );

  // questions 为空或非 role_choice 种类不进入多题模式
  assert.deepEqual(roleChoiceQuestions(roleChoiceDecision({ request: { questions: [] } })), []);
  assert.deepEqual(roleChoiceQuestions(decision()), []);
});

test("role_choice 已回答时对照 answers 与 questions 解析逐题选定文字与补充说明", () => {
  const answered = roleChoiceDecision({
    status: "answered",
    answer: {
      event_id: "evt_ans_1",
      option: "submit",
      answers: { q1: "toml", q2: "8080" },
      note: "配置用 TOML，端口保留默认",
      base_version: 3,
      actor: "user:local",
      command_id: "cmd_1",
      answered_at: "2026-10-02T10:02:00Z",
    },
  });
  const summary = answeredRoleChoiceSummary(answered);
  assert.ok(summary !== null);
  assert.equal(summary.actionLabel, "逐题回答");
  assert.equal(summary.note, "配置用 TOML，端口保留默认");
  assert.deepEqual(summary.items, [
    {
      questionId: "q1",
      question: "配置格式采用哪一种？",
      optionId: "toml",
      optionLabel: "TOML 文件",
      optionDescription: null,
      recommended: false,
    },
    {
      questionId: "q2",
      question: "默认端口选哪个？",
      optionId: "8080",
      optionLabel: "8080 端口",
      optionDescription: null,
      recommended: true,
    },
  ]);
  assert.ok(summary.summaryText.includes("TOML 文件"));
  assert.ok(summary.summaryText.includes("8080 端口"));
  assert.equal(summary.summaryText.includes("提交回答"), false);

  // option="recommended" 且旧记录缺少 answers 时按每题 recommended 解析
  const recAnswered = roleChoiceDecision({
    status: "answered",
    answer: {
      event_id: "evt_ans_2",
      option: "recommended",
      answers: null,
      note: null,
      base_version: 3,
      actor: "user:local",
      command_id: "cmd_2",
      answered_at: "2026-10-02T10:03:00Z",
    },
  });
  const recSummary = answeredRoleChoiceSummary(recAnswered);
  assert.ok(recSummary !== null);
  assert.equal(recSummary.actionLabel, "全部采用推荐");
  assert.deepEqual(recSummary.items.map((item) => item.optionLabel), ["JSON 文件", "8080 端口"]);

  // role_choice 材料行与跳转落到对话页
  const rows = materialRows(answered);
  const map = Object.fromEntries(rows.map((row) => [row.term, row.value]));
  assert.equal(map["职能"], "产品");
  assert.equal(map["轮次"], "第 1 轮");
  assert.equal(map["补充提示"], "默认采用推荐项即可直接运行");
  assert.equal(map["说明"], "请确认两项前置配置选择");
  assert.equal(viewHref(answered), "#/p/p1/conversation?w=w1");
  assert.equal(face(answered, new Date("2026-10-02T10:01:00Z").getTime()).title, "角色向你提问，等待选择");
});

test("对话线程模型保留 role_choice 气泡的多题题目、本轮阻塞提示与逐题已回答结果", () => {
  const openDecision = roleChoiceDecision();
  const answeredDecision = roleChoiceDecision({
    decision_id: "dec_rc_2",
    status: "answered",
    answer: {
      option: "submit",
      answers: { q1: "toml", q2: "9000" },
      note: "已确认改选两项",
      answered_at: "2026-10-02T10:05:00Z",
    },
  });
  const openView = threadDecisionView(openDecision);
  assert.equal(openView.questions.length, 2);
  assert.equal(openView.roundLabel, "第 1 轮");
  assert.equal(openView.blocksText, "仅暂停产品的本轮工作，其余职能与事项照常推进");
  assert.equal(openView.answeredSummary, null);

  const answeredView = threadDecisionView(answeredDecision);
  assert.ok(answeredView.answeredSummary !== null);
  assert.deepEqual(answeredView.answeredSummary.items.map((item) => item.optionLabel), ["TOML 文件", "9000 端口"]);
  assert.equal(answeredView.answeredSummary.note, "已确认改选两项");

  const entries = itemThread({
    item: { work_item_id: "w1", kind: "change", status: "in_progress" },
    flow: [],
    asks: [],
    decisions: [openDecision, answeredDecision],
    titles: { w1: "配置系统" },
    expanded: true,
  });
  const decisionEntries = entries.filter((entry) => entry.kind === "decision");
  assert.equal(decisionEntries.length, 2);
  assert.equal(decisionEntries[1].decision.answer?.answers?.q1, "toml");
});

function loadTsxModule(relativePath) {
  const require = createRequire(import.meta.url);
  const ts = require("typescript");
  const React = require("react");
  globalThis.React = React;
  const loader = (module, filename) => {
    const code = fs.readFileSync(filename, "utf8");
    const js = ts.transpileModule(code, {
      compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    module._compile(js, filename);
  };
  require.extensions[".tsx"] = loader;
  require.extensions[".ts"] = loader;
  const { renderToStaticMarkup } = require("react-dom/server");
  const mod = require(relativePath);
  return { React, renderToStaticMarkup, mod };
}

test("决定卡片与对话线程决定气泡渲染 role_choice 多题交互、已回答逐题展示及原有单选决定", () => {
  const { React, renderToStaticMarkup, mod: cardMod } = loadTsxModule("../../src/renderer/src/views/decisions/card.tsx");
  const { mod: threadMod } = loadTsxModule("../../src/renderer/src/views/project/thread.tsx");
  const now = new Date("2026-10-02T10:01:00Z").getTime();

  const appWithAnswer = { currentCapabilities: { commands: [{ name: "decision.answer" }] } };

  // 1. 待回答 role_choice：卡片与气泡均展示题干、选项、说明、推荐标记、推荐理由、补充说明框与两个提交按钮
  const openRc = roleChoiceDecision();
  const cardOpenHtml = renderToStaticMarkup(React.createElement(cardMod.DecisionCard, {
    app: appWithAnswer,
    decision: openRc,
    now,
    projectName: "配置工具",
    workItemTitle: "初始化配置",
    onNavigate: () => {},
  }));
  for (const snippet of [
    "角色向你提问，等待选择",
    "阻塞范围：本轮工作",
    "仅暂停「初始化配置」中产品的本轮工作，其余职能与事项照常推进",
    "1. 配置格式采用哪一种？",
    "JSON 文件",
    "零额外依赖",
    "TOML 文件",
    "推荐",
    "推荐理由：标准库可直接读写",
    "2. 默认端口选哪个？",
    "8080 端口",
    "9000 端口",
    "推荐理由：本地调试常用端口",
    "补充说明（可选）",
    ">提交回答</button>",
    ">全部采用推荐</button>",
  ]) {
    assert.ok(cardOpenHtml.includes(snippet), `决定卡片缺少：${snippet}`);
  }
  // 默认按 recommended 预选（json 与 8080 处于 checked 状态，toml 与 9000 未选中）
  assert.match(cardOpenHtml, /<input[^>]*checked=""[^>]*value="json"/);
  assert.match(cardOpenHtml, /<input[^>]*checked=""[^>]*value="8080"/);
  assert.equal(/<input[^>]*checked=""[^>]*value="toml"/.test(cardOpenHtml), false);
  assert.equal(/<input[^>]*checked=""[^>]*value="9000"/.test(cardOpenHtml), false);

  const threadOpenHtml = renderToStaticMarkup(React.createElement(threadMod.ThreadView, {
    app: appWithAnswer,
    items: [{ work_item_id: "w1", kind: "change", status: "in_progress" }],
    titles: { w1: "初始化配置" },
    flow: [],
    decisions: [openRc],
    labels: {},
    selected: "w1",
    opened: {},
    onToggleItem: () => {},
    onSelectItem: () => {},
    onLook: () => {},
    onSequence: () => {},
    onNavigate: () => {},
    scrollSignal: 0,
  }));
  for (const snippet of [
    "角色向你提问，等待选择",
    "阻塞范围：本轮工作",
    "1. 配置格式采用哪一种？",
    "TOML 文件",
    "推荐理由：标准库可直接读写",
    "补充说明（可选）",
    ">提交回答</button>",
    ">全部采用推荐</button>",
  ]) {
    assert.ok(threadOpenHtml.includes(snippet), `线程气泡缺少：${snippet}`);
  }
  assert.match(threadOpenHtml, /<input[^>]*checked=""[^>]*value="json"/);
  assert.match(threadOpenHtml, /<input[^>]*checked=""[^>]*value="8080"/);

  // 2. 已回答 role_choice：显示逐题选定文字与补充说明，不退化为仅显示顶层「提交回答」
  const answeredRc = roleChoiceDecision({
    status: "answered",
    answer: {
      event_id: "evt_a1",
      option: "submit",
      answers: { q1: "toml", q2: "8080" },
      note: "优先兼容现有 TOML",
      base_version: 3,
      actor: "user:local",
      command_id: "cmd_a1",
      answered_at: "2026-10-02T10:02:00Z",
    },
  });
  const cardAnsweredHtml = renderToStaticMarkup(React.createElement(cardMod.DecisionCard, {
    app: null,
    decision: answeredRc,
    now,
    projectName: "配置工具",
    workItemTitle: "初始化配置",
    onNavigate: () => {},
  }));
  for (const snippet of ["配置格式采用哪一种？", "TOML 文件", "默认端口选哪个？", "8080 端口", "补充说明：优先兼容现有 TOML"]) {
    assert.ok(cardAnsweredHtml.includes(snippet), `已回答决定卡片缺少：${snippet}`);
  }
  assert.equal(cardAnsweredHtml.includes("已提交：提交回答"), false);

  const threadAnsweredHtml = renderToStaticMarkup(React.createElement(threadMod.ThreadView, {
    app: null,
    items: [{ work_item_id: "w1", kind: "change", status: "in_progress" }],
    titles: { w1: "初始化配置" },
    flow: [],
    decisions: [answeredRc],
    labels: {},
    selected: "w1",
    opened: {},
    onToggleItem: () => {},
    onSelectItem: () => {},
    onLook: () => {},
    onSequence: () => {},
    onNavigate: () => {},
    scrollSignal: 0,
  }));
  for (const snippet of ["配置格式采用哪一种？", "TOML 文件", "默认端口选哪个？", "8080 端口", "补充说明：优先兼容现有 TOML"]) {
    assert.ok(threadAnsweredHtml.includes(snippet), `已回答线程气泡缺少：${snippet}`);
  }
  assert.equal(threadAnsweredHtml.includes("已回答：提交回答"), false);

  // 3. 原有单选决定种类行为与显示保持不变
  const singleOpen = decision();
  const singleCardOpen = renderToStaticMarkup(React.createElement(cardMod.DecisionCard, {
    app: null,
    decision: singleOpen,
    now,
    projectName: "文本工具",
    workItemTitle: "实现逐行处理",
    onNavigate: () => {},
  }));
  assert.ok(singleCardOpen.includes("阻塞范围：整次运行"));
  assert.ok(singleCardOpen.includes("继续执行"));
  assert.ok(singleCardOpen.includes("停止事项"));
  assert.equal(singleCardOpen.includes("全部采用推荐"), false);

  const singleAnswered = decision({
    status: "answered",
    answer: {
      event_id: "evt_s1",
      option: "continue",
      note: null,
      base_version: 3,
      actor: "user:local",
      command_id: "cmd_s1",
      answered_at: "2026-10-02T10:02:00Z",
    },
  });
  const singleCardAnswered = renderToStaticMarkup(React.createElement(cardMod.DecisionCard, {
    app: null,
    decision: singleAnswered,
    now,
    projectName: "文本工具",
    workItemTitle: "实现逐行处理",
    onNavigate: () => {},
  }));
  assert.ok(singleCardAnswered.includes("已提交：继续执行"));
});
