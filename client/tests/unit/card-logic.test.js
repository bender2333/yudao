// 决定卡片纯逻辑的单元测试（原型 v8 设计说明第 6 节，工单 #175）：
// 材料按决定种类整理、挡住的对象、等待时长、「在项目中查看」的目标、按发出时间排列，
// 以及给像素画面用的纯文字版本与页面卡片共用同一份材料。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  blockedText,
  decisionLinks,
  face,
  materialRows,
  missingNoteText,
  sortByRequested,
  viewHref,
  waitedSeconds,
} from "../../src/renderer/src/views/decisions/card-logic.ts";
import { DECISION_KIND, RECOVERY_STATE } from "../../src/renderer/src/views/project/labels.ts";

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
  assert.equal(map["部门"], "工程");
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
  // 「前往本项目的部门设置」落在设置页的部门设置那一节（工单 #1161）：路径带上节名
  assert.deepEqual(card.links.map((link) => link.href), ["#/sys/models", "#/p/p1/settings?section=departments"]);
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

test("界面不再包含已删除的 unknown_action 与 pending_verification", () => {
  assert.equal(DECISION_KIND.unknown_action, undefined);
  assert.equal(RECOVERY_STATE.pending_verification, undefined);
});
