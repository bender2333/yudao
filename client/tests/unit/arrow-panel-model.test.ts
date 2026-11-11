// 箭头面板的模型（工单 #1711）：面板按箭头是哪一种成果分段，每一段给出哪几句话与哪几个数。
// 设计说明 docs/design/project-organization.md「节点面板与箭头面板接住的内容」、
// 「项目页上的内容在哪里看」；页面的四条验收见 #1707 的补充条第 15 条。
//
// 断言落在模型给出的文字与结构上：面板怎么摆、按钮长什么样由页面负责，真实页面交给发布以后的走查与试用。

import { test } from "node:test";
import assert from "node:assert/strict";

import type { AcceptanceCoverageResult, ReviewEntry } from "../../src/renderer/src/api/generated/types.gen";
import type { LoopArrow } from "../../src/renderer/src/views/project/loop-graph-model.ts";
import {
  MISSING_REVIEW_TEXT,
  NO_FILES_TEXT,
  OPEN_ENDED_TEXT,
  arrowKindOf,
  arrowPanelView,
  citedCasesOf,
  conclusionOf,
  diffFiles,
  inputsView,
  roundsView,
  versionNavOf,
  versionOf,
  type MaterialsLike,
} from "../../src/renderer/src/views/project/arrow-panel-model.ts";

// ---------------------------------------------------------------------------
// 夹具

function arrow(overrides: Partial<LoopArrow> = {}): LoopArrow {
  return {
    key: "flow-1",
    outcome: "交付",
    version: 2,
    round: 3,
    from: "engineering",
    to: "quality",
    back: false,
    position: 12,
    verdict: null,
    text: "分页交付第 2 版",
    files: [],
    ...overrides,
  };
}

// 一份 QAReview：结论、理由、检查回执、缺陷、逐条结论与引用的试用用例
function review(overrides: Partial<ReviewEntry> = {}): ReviewEntry {
  return {
    event_id: "ev-review-1",
    verdict: "release",
    rationale: "逐条都过了",
    defects: [],
    checks: [],
    criteria: [
      { criterion: "AC1", method: "check", result: "passed", checks: ["npm test"], trial_cases: ["c1"], note: "" },
    ],
    trial_cases: [{ case_id: "c1", title: "分页浏览", result: "passed", screenshots: [] }],
    ...overrides,
  };
}

// 一份放行记录：检验覆盖的数由它给出，页面不重算
function coverage(overrides: Partial<AcceptanceCoverageResult> = {}): AcceptanceCoverageResult {
  return {
    run_id: "run-1",
    work_item_id: "w1",
    verdict: "release",
    review_event_id: "ev-review-1",
    revision: 1,
    numbers: { criteria_total: 2, executable: 2, covered: 2, coverage_ratio: 1, model_reading: 1, open: 0 },
    criteria: [],
    open_criteria: [],
    ...overrides,
  };
}

function materials(overrides: Partial<MaterialsLike> = {}): MaterialsLike {
  return {
    contracts: [{ event_id: "ev-prd-1", revision: 1 }],
    deliveries: [
      { event_id: "ev-delivery-1", revision: 1, summary: "第一版分页", files: ["a.ts", "b.ts"] },
      { event_id: "ev-delivery-2", revision: 2, summary: "第二版分页", files: ["a.ts", "c.ts"] },
    ],
    reviews: [review()],
    onboarding_rounds: [],
    ...overrides,
  };
}

// 一条试用用例在页签模型里的样子（trials.tsx 的 TrialCaseRow）
function caseRow(caseId: string, title: string) {
  return {
    key: `0-${caseId}`,
    title,
    criteria: [],
    plan: [] as string[],
    expected: "",
    resultText: "通过",
    resultKind: "ok",
    observed: "",
    reason: "",
    steps: [],
  };
}

// ---------------------------------------------------------------------------
// 标着放行或打回的那一版

test("放行的那一版给出结论、逐条结论与检验覆盖", () => {
  // R3：验收第 15 条「放行或打回的那一版看得到逐条结论与证据」
  const delivered = arrow({
    eventId: "ev-delivery-2",
    verdict: { tone: "release", by: "质检", text: "放行 · 质检" },
  });
  const view = arrowPanelView({
    arrow: delivered,
    versions: [delivered],
    materials: materials(),
    inputs: null,
    coverage: coverage(),
    verifier: true,
    ended: "完成 · 质检放行",
  });
  assert.equal(view.kind, "reviewed");
  assert.equal(view.conclusion?.headline, "质检放行这一版");
  assert.equal(view.conclusion?.verdictName, "放行");
  assert.equal(view.conclusion?.rationale, "逐条都过了");
  assert.equal(view.conclusion?.criteriaCount, 1);
  assert.equal(view.conclusion?.coverageText, "检验覆盖 100%（2/2）· 开环条件 0 条（其中模型阅读 1 条）");
  assert.deepEqual(view.conclusion?.caseIds, ["c1"]);
  assert.equal(view.openEnded, null);
});

test("打回的那一版给出缺陷与检查回执，检验覆盖不借用别的一份结论", () => {
  // R3：同一句「缺陷」那半：打回的理由里要写得出是哪一条缺陷
  const rejected = arrow({ key: "flow-defect", verdict: { tone: "reject", by: "质检", text: "质检打回" } });
  const view = arrowPanelView({
    arrow: rejected,
    versions: [rejected],
    materials: materials({
      reviews: [
        review({
          event_id: "ev-review-2",
          verdict: "rework_engineering",
          rationale: "第二页没有分页",
          defects: [{ name: "分页", summary: "第二页一屏到底" }],
          checks: [{ name: "npm test", result: "passed", summary: "全过" }],
          criteria: [],
        }),
      ],
    }),
    inputs: null,
    coverage: coverage(),
    verifier: true,
    ended: "质检放行才结束",
  });
  assert.equal(view.conclusion?.headline, "质检打回这一版");
  assert.equal(view.conclusion?.verdictName, "缺陷记录");
  assert.deepEqual(view.conclusion?.defects, ["分页 · 第二页一屏到底"]);
  assert.deepEqual(view.conclusion?.checks, ["npm test · passed · 全过"]);
  assert.equal(view.conclusion?.criteriaCount, 0);
  // 放行记录的 review_event_id 不是这一份结论的，不带过来
  assert.equal(view.conclusion?.coverageText, null);
});

test("材料里没有这一份结论时写明没有，不写成没有缺陷", () => {
  // R3：读不出来与「没有」分开写（资料页与逐条结论同一条规矩）
  const rejected = arrow({ verdict: { tone: "reject", by: "质检", text: "质检打回" } });
  const view = arrowPanelView({
    arrow: rejected,
    versions: [rejected],
    materials: materials({ reviews: [] }),
    inputs: null,
    coverage: null,
    verifier: true,
    ended: "质检放行才结束",
  });
  assert.equal(view.conclusion?.missing, true);
  assert.deepEqual(view.conclusion?.defects, []);
});

// ---------------------------------------------------------------------------
// 没有核验角色的完成

test("没有核验角色的交完成那版写开环完成，没有结论段", () => {
  // R3：验收第 15 条「直做交完成的那一版有箭头，面板写开环完成：没有人核验」
  const done = arrow({ key: "flow-done", verdict: null });
  const view = arrowPanelView({
    arrow: done,
    versions: [done],
    materials: materials(),
    inputs: null,
    coverage: null,
    verifier: false,
    ended: OPEN_ENDED_TEXT,
  });
  assert.equal(view.kind, "outcome");
  assert.equal(view.openEnded, OPEN_ENDED_TEXT);
  assert.equal(view.conclusion, null);
});

test("开环完成那一句只写在最后交完成的那一版上", () => {
  // R3：中途那几版没有交完成，不写这一句
  const first = arrow({ key: "flow-1", version: 1, position: 1 });
  const last = arrow({ key: "flow-2", version: 2, position: 2 });
  const ended = { verifier: false, ended: OPEN_ENDED_TEXT, conclusion: null };
  assert.equal(
    arrowPanelView({ arrow: first, versions: [first, last], materials: materials(), inputs: null, coverage: null, ...ended }).openEnded,
    null,
  );
  assert.equal(
    arrowPanelView({ arrow: last, versions: [first, last], materials: materials(), inputs: null, coverage: null, ...ended }).openEnded,
    OPEN_ENDED_TEXT,
  );
});

// ---------------------------------------------------------------------------
// 建档事项的初始 PRD 箭头

test("建档的初始 PRD 箭头给出各轮与确认记录", () => {
  // R3：设计说明「建档各轮的初始 PRD、现有结构说明、基线核验、确认记录」写在初始 PRD 箭头的面板上
  const prd = arrow({ key: "flow-prd", outcome: "PRD", version: 1, eventId: "ev-prd-1" });
  const view = arrowPanelView({
    arrow: prd,
    versions: [prd],
    materials: materials({
      onboarding_rounds: [
        {
          round: 2,
          run_id: "run-2",
          proposed_at: "2026-11-09T03:00:00Z",
          prd: "# PRD 第二版",
          structure: "src 下按模块分",
          revision_note: "加上分页",
          baseline_review: { conclusions: [], omissions: [], checks: [], other_failures: [] },
          decisions: [{ outcome: "answered", option: "confirm", note: "就按这一版", decided_at: "2026-11-09T04:00:00Z" }],
        },
        {
          round: 1,
          run_id: "run-1",
          proposed_at: "2026-11-09T01:00:00Z",
          prd: "# PRD 第一版",
          structure: "src 下按模块分",
          revision_note: "",
          baseline_review: {
            conclusions: [{ requirement: "已登录用户看得见分页", status: "verified", evidence: "抓包" }],
            omissions: [{ capability: "分页", location: "src/paging" }],
            checks: [{ name: "npm test", result: "passed", summary: "全过" }],
            other_failures: [],
          },
          decisions: [
            { outcome: "answered", option: "revise", note: "带上分页", decided_at: "2026-11-09T02:00:00Z" },
            { outcome: "withdrawn", option: "confirm", reason: "改主意了", decided_at: "2026-11-09T02:30:00Z" },
          ],
        },
      ],
    }),
    inputs: null,
    coverage: null,
    verifier: true,
    ended: "质检放行才结束",
  });
  assert.equal(view.kind, "onboarding");
  assert.deepEqual(view.rounds.map((round) => round.round), [1, 2]);
  assert.equal(view.rounds[1]?.prd, "# PRD 第二版");
  assert.equal(view.rounds[0]?.baseline.length, 3);
  assert.equal(view.rounds[0]?.baseline[0], "已核实：已登录用户看得见分页");
  assert.equal(view.rounds[0]?.baseline[1], "遗漏的能力：分页（src/paging）");
  assert.deepEqual(view.rounds[0]?.decisions.map((item) => item.text), [
    "回答：提出修改 · 带上分页",
    "撤销 · 改主意了",
  ]);
  assert.deepEqual(view.rounds[1]?.decisions.map((item) => item.text), ["回答：确认 · 就按这一版"]);
  // PRD 的版本号与摘要取材料里的那一版
  assert.equal(view.version.revision, 1);
});

test("没有建档各轮的事项不画建档那一段", () => {
  // R1：分段的依据只有材料，箭头本身看不出是建档事项
  const prd = arrow({ key: "flow-prd", outcome: "PRD", version: 1 });
  const view = arrowPanelView({
    arrow: prd, versions: [prd], materials: materials(), inputs: null, coverage: null,
    verifier: true, ended: "",
  });
  assert.equal(view.kind, "outcome");
  assert.deepEqual(view.rounds, []);
  assert.deepEqual(roundsView(null), []);
});

// ---------------------------------------------------------------------------
// 同一种成果逐版切

test("同一种成果几版按先后排，逐版切给出前后版", () => {
  // R2：逐版看是面板与查询之间的合同（箭头带的事件与版本号决定这一版）
  const first = arrow({ key: "flow-1", version: 1, position: 1 });
  const second = arrow({ key: "flow-2", version: 2, position: 2 });
  const third = arrow({ key: "flow-3", version: 3, position: 3 });
  const versions = [first, second, third];
  const nav = versionNavOf(versions, second);
  assert.equal(nav?.index, 2);
  assert.equal(nav?.total, 3);
  assert.equal(nav?.label, "第 2 / 3 版");
  assert.equal(nav?.prev?.key, "flow-1");
  assert.equal(nav?.next?.key, "flow-3");
  assert.equal(versionNavOf([first], first), null);
});

test("与上一版的差异写新增、减少与没变的文件", () => {
  // R3：设计说明「交付各版本的文件清单、摘要、差异」
  assert.deepEqual(diffFiles(["a.ts", "c.ts"], ["a.ts", "b.ts"]), {
    added: ["c.ts"],
    removed: ["b.ts"],
    kept: 1,
    text: "与上一版相比 新增 1 个：c.ts；减少 1 个：b.ts；没变 1 个",
  });
  assert.equal(diffFiles(["a.ts"], ["a.ts"])?.text, "与上一版相比文件没有变化（1 个）");
  assert.equal(diffFiles(["a.ts"], null), null);
});

test("那一版的文件清单取材料的，材料里没有时退回箭头自带的", () => {
  // R2：文件清单与单个文件下载都按箭头带的那条事实取
  const second = arrow({ key: "flow-2", version: 2, eventId: "ev-delivery-2" });
  const first = arrow({ key: "flow-1", version: 1, eventId: "ev-delivery-1" });
  const loaded = versionOf(second, [first, second], materials());
  assert.equal(loaded.loaded, true);
  assert.equal(loaded.revision, 2);
  assert.equal(loaded.summary, "第二版分页");
  assert.deepEqual(loaded.files, ["a.ts", "c.ts"]);
  assert.equal(loaded.diff?.text, "与上一版相比 新增 1 个：c.ts；减少 1 个：b.ts；没变 1 个");
  const fallback = versionOf(arrow({ files: ["x.ts"] }), [], null);
  assert.equal(fallback.loaded, false);
  assert.deepEqual(fallback.files, ["x.ts"]);
  assert.equal(fallback.diff, null);
});

// ---------------------------------------------------------------------------
// 从图外进来的箭头

test("从图外进来的箭头给出输入各版本与处理进度", () => {
  // R3：验收第 15 条之外的那一条（设计说明「你的输入各版本与处理进度」）
  const latest = arrow({ key: "src:3", outcome: "原文", from: "src", version: 3, eventId: "ev-in-3" });
  const view = arrowPanelView({
    arrow: latest,
    versions: [latest],
    materials: null,
    inputs: {
      input_version: 3,
      processed_input_version: 2,
      inputs: [
        { version: 1, text: "做一个分页", kind: "text", byte_start: 0, byte_end: 12, created_event_id: "ev-in-1" },
        { version: 3, text: "第二页也要", kind: "text", byte_start: 13, byte_end: 20, created_event_id: "ev-in-3" },
        { version: 2, text: "npm test", kind: "command", byte_start: 21, byte_end: 29, created_event_id: "ev-in-2" },
      ],
    },
    coverage: null,
    verifier: true,
    ended: "",
  });
  assert.equal(view.kind, "input");
  assert.equal(view.inputs?.headline, "最新第 3 版，已处理到第 2 版，第 3 版起 1 版还没处理");
  assert.deepEqual(view.inputs?.rows.map((row) => row.version), [1, 2, 3]);
  assert.deepEqual(view.inputs?.rows.map((row) => row.stateText), ["已处理", "已处理", "还没处理"]);
  assert.equal(view.inputs?.rows[1]?.kindName, "命令");
  assert.equal(view.inputs?.rows[0]?.range, "0–12 字节");
  assert.equal(view.inputs?.rows[2]?.eventId, "ev-in-3");
  assert.equal(view.conclusion, null);
});

test("输入都处理完了时那一句写都处理了", () => {
  // R1：处理进度只有「已处理到第几版」一个来源，不另算
  const inputs = inputsView({
    input_version: 1,
    processed_input_version: 1,
    inputs: [{ version: 1, text: "做一个分页", kind: "text", byte_start: 0, byte_end: 12, created_event_id: "ev-in-1" }],
  });
  assert.equal(inputs?.headline, "最新第 1 版，已处理到第 1 版，都处理了");
  assert.equal(inputsView(null), null);
});

// ---------------------------------------------------------------------------
// 逐条结论引用的试用用例

test("结论引用的试用用例按引用先后给，缺的写进 missing", () => {
  // R3：证据里点得开试用用例与截图（截图与步骤由 trials.tsx 的模型给出）
  const view = { sessions: [], cases: [caseRow("c1", "分页浏览"), caseRow("c3", "翻到第三页")], textOnly: false };
  const cited = citedCasesOf(view, ["c3", "c2", "c1"]);
  assert.deepEqual(cited.rows.map((row) => row.title), ["翻到第三页", "分页浏览"]);
  assert.deepEqual(cited.missing, ["c2"]);
  assert.deepEqual(citedCasesOf(null, ["c1"]).missing, ["c1"]);
});

// ---------------------------------------------------------------------------
// 分段的依据

test("箭头是哪一种成果：来源、建档 PRD、标着结论的、其余成果", () => {
  // R1：分段的依据只有箭头本身与材料的建档各轮
  assert.equal(arrowKindOf(arrow({ from: "src", outcome: "原文" }), 0), "input");
  assert.equal(arrowKindOf(arrow({ outcome: "PRD" }), 2), "onboarding");
  assert.equal(arrowKindOf(arrow({ outcome: "PRD" }), 0), "outcome");
  assert.equal(
    arrowKindOf(arrow({ verdict: { tone: "release", by: "质检", text: "放行 · 质检" } }), 0),
    "reviewed",
  );
  assert.equal(arrowKindOf(arrow({ outcome: "缺陷记录" }), 0), "outcome");
});

test("没有对应结论的一版不给结论段", () => {
  // R1：没标结论的版不画结论段，也不写「开环完成」
  assert.equal(conclusionOf(arrow(), materials(), coverage()), null);
  const marked = arrow({ verdict: { tone: "release", by: "质检", text: "放行 · 质检" } });
  assert.equal(conclusionOf(marked, materials({ reviews: [] }), null)?.missing, true);
  assert.equal(MISSING_REVIEW_TEXT, "材料里没有这一份结论");
  assert.equal(NO_FILES_TEXT, "这一版没有附文件清单");
});
