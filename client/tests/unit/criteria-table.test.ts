// 资料页质检一项的逐条结论表与交付一项的启动方式（工单 #154；浏览器与 computer use 设计说明
// docs/design/browser-and-computer-use.md「页面与画面」、「QAReview 的逐条结论与放行」、「无法核验」；验证的独立性 docs/design/independent-verification.md「检验覆盖与开环」、「口径」）。
//
// 页面上要写的三样东西在这里先按查询结果的形状核对：
//   - 六种检验方式的中文名：夹具 client/tests/fixtures/check-methods.json 的每个代码名都有一行，
//     页面上的表与它相同（页面不导入翻译层，自己留一份，两个文件按同一份夹具核对）；
//   - 三种结果与结论的中文名：不把 passed、unverified、rework_engineering 这类代码写进页面；
//   - 表头的检验覆盖比例、模型阅读与开环的条数，以及每行的证据、试用用例截图与无法核验的原因：
//     数字与开环判定取 acceptance.coverage 里放行记录算好的那一份，页面不按逐条结论重算。
//
// 用 node --test 运行，不依赖服务与网络。守 R2（查询交换的字段与两端的词表是合同）与
// R3（检验覆盖与开环在页面上看得到，与放行记录一致）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import type { AcceptanceCoverageResult, QaCriterionView, ReviewEntry } from "../../src/renderer/src/api/generated/types.gen";
import {
  CHECK_METHODS,
  CHECK_RESULT_KIND,
  checkMethodName,
  checkResultKind,
  checkResultName,
  launchKindName,
  launchSystemName,
  trialCaseResultName,
  verdictName,
  versionStatusName,
} from "../../src/renderer/src/views/project/labels.ts";
import {
  SCREENSHOT_LIMIT,
  coverageSummary,
  criterionRows,
  launchViews,
  unverifiedViews,
  type LaunchRowView,
} from "../../src/renderer/src/views/project/materials-read.ts";

interface FixtureMethod {
  code: string;
  label: string;
  executable: boolean;
}

const METHODS: FixtureMethod[] = (
  JSON.parse(readFileSync(new URL("../fixtures/check-methods.json", import.meta.url), "utf8")) as {
    methods: FixtureMethod[];
  }
).methods;

// 一条逐条结论：查询结果里的六项（验收条件、检验方式、结果、检查、试用用例、原因）
function criterion(over: Partial<QaCriterionView> = {}): QaCriterionView {
  return {
    criterion: "AC1",
    method: "check",
    result: "passed",
    checks: [] as string[],
    trial_cases: [] as string[],
    note: "",
    ...over,
  };
}

// 一份 QAReview 在资料页上的条目：结论、理由、检查回执、缺陷与这三处增加
function reviewEntry(over: Partial<ReviewEntry> = {}): ReviewEntry {
  return {
    event_id: "ev_review",
    verdict: "release",
    rationale: "交付符合合同",
    defects: [],
    checks: [],
    criteria: [criterion()],
    trial_cases: [],
    unverified: [],
    ...over,
  };
}

function screenshotRef(name: string) {
  return {
    kind: "screenshot",
    content_hash: `sha256:${name}`,
    path: `run_1/${name}`,
    media_type: "image/png",
  };
}

// acceptance.coverage 的结果：放行记录里一次算好的数与逐条判定
function coverageResult(over: Partial<AcceptanceCoverageResult> = {}): AcceptanceCoverageResult {
  return {
    run_id: "run_1",
    work_item_id: "wi_1",
    verdict: "release",
    review_event_id: "ev_review",
    revision: 1,
    numbers: {
      criteria_total: 3,
      executable: 2,
      covered: 2,
      coverage_ratio: 2 / 3,
      model_reading: 1,
      open: 1,
    },
    criteria: [
      { criterion: "AC1", method: "trial", result: "passed", executable: true, open: false },
      { criterion: "AC2", method: "judgement", result: "unverified", executable: false, open: true },
      { criterion: "AC3", method: "check", result: "passed", executable: true, open: false },
    ],
    open_criteria: ["AC2"],
    ...over,
  };
}

test("六种检验方式的中文名与夹具一致，页面上不写代码名", () => {
  assert.equal(METHODS.length, 6, "夹具里的检验方式不是六种");
  assert.deepEqual(Object.keys(CHECK_METHODS).sort(), METHODS.map((item) => item.code).sort());
  for (const item of METHODS) {
    assert.equal(checkMethodName(item.code), item.label, item.code);
    assert.equal(CHECK_METHODS[item.code]?.label, item.label, item.code);
    assert.equal(CHECK_METHODS[item.code]?.executable, item.executable, item.code);
  }
  // 没有登记的方式与空值各有自己的说法，原样的代码名不写到页面上
  assert.equal(checkMethodName(""), "未写明检验方式");
  assert.equal(checkMethodName("probe"), "其他检验方式");
  assert.ok(!/probe|check|trial|measure|judgement|human|open/.test(checkMethodName("probe")));
});

test("三种结果写成通过、不通过、未核验，未登记的结果不写代码名", () => {
  assert.equal(checkResultName("passed"), "通过");
  assert.equal(checkResultName("failed"), "不通过");
  assert.equal(checkResultName("unverified"), "未核验");
  assert.equal(checkResultName(""), "未写明结果");
  assert.equal(checkResultName("blocked"), "其他结果");
  assert.equal(checkResultKind("passed"), "succeeded");
  assert.equal(checkResultKind("failed"), "failed");
  assert.equal(checkResultKind("unverified"), "idle");
  assert.equal(checkResultKind("blocked"), "idle");
  assert.equal(CHECK_RESULT_KIND.passed, "succeeded");
  // 试用用例的结论多一个中断；页面同样不写代码名
  assert.equal(trialCaseResultName("interrupted"), "中断");
  assert.equal(trialCaseResultName("unverified"), "未核验");
  assert.equal(trialCaseResultName("blocked"), "其他结果");
  // 质检结论的三种词
  assert.equal(verdictName("release"), "放行");
  assert.equal(verdictName("rework_engineering"), "缺陷记录");
  assert.equal(verdictName("cannot_verify"), "无法核验");
  assert.equal(verdictName(""), "未写明结论");
  assert.equal(verdictName("other"), "其他结论");
});

test("交付与合同的版本状态写中文，不写 active、superseded 这样的代码名", () => {
  assert.equal(versionStatusName("active"), "当前版本");
  assert.equal(versionStatusName("superseded"), "已被取代");
  assert.equal(versionStatusName(""), "未写明状态");
  assert.equal(versionStatusName("archived"), "其他状态");
});

test("表头写检验覆盖比例、模型阅读与开环的条数，数字取自放行记录", () => {
  assert.equal(
    coverageSummary({ criteria_total: 4, executable: 2, covered: 2, coverage_ratio: 0.5, model_reading: 1, open: 2 }),
    "检验覆盖 50%（2/4）· 开环条件 2 条（其中模型阅读 1 条）",
  );
  assert.equal(
    coverageSummary({ criteria_total: 4, executable: 3, covered: 3, coverage_ratio: 0.75, model_reading: 0, open: 2 }),
    "检验覆盖 75%（3/4）· 开环条件 2 条（其中模型阅读 0 条）",
  );
  // 比例照记录里的那个数写，不由页面拿 covered ÷ criteria_total 重算
  assert.equal(
    coverageSummary({ criteria_total: 4, executable: 1, covered: 3, coverage_ratio: 0.25, model_reading: 2, open: 2 }),
    "检验覆盖 25%（3/4）· 开环条件 2 条（其中模型阅读 2 条）",
  );
});

test("逐条结论一行一条：方法、结果写成中文，开环标记取放行记录里的判定", () => {
  const review = reviewEntry({
    criteria: [
      criterion({ criterion: "AC1", method: "trial", result: "passed", trial_cases: ["case_1"] }),
      criterion({ criterion: "AC2", method: "judgement", result: "unverified", note: "参照材料里没有写清楚" }),
      criterion({ criterion: "AC3", method: "check", result: "passed", checks: ["smoke"] }),
    ],
  });
  // AC1 在放行记录里是「模型阅读」的试用用例（可执行是 false、开环是 true）：
  // 开环标记按记录写，页面不按检验方式重算成「可执行」
  const rows = criterionRows(review, coverageResult({
    criteria: [
      { criterion: "AC1", method: "trial", result: "passed", executable: false, open: true },
      { criterion: "AC2", method: "judgement", result: "unverified", executable: false, open: true },
      { criterion: "AC3", method: "check", result: "passed", executable: true, open: false },
    ],
  }));
  assert.deepEqual(rows.map((row) => [row.criterion, row.methodName, row.resultName, row.open]), [
    ["AC1", "试用用例", "通过", true],
    ["AC2", "带参照材料的判定点", "未核验", true],
    ["AC3", "命令检查", "通过", false],
  ]);
  // 旧结论没有放行记录里的逐条判定：按检验方式判断，判定点算开环
  assert.deepEqual(criterionRows(review, null).map((row) => row.open), [false, true, false]);
  // 页面上没有英文代码名
  const shown = rows.map((row) => `${row.methodName}${row.resultName}`).join("");
  for (const word of ["trial", "judgement", "passed", "unverified"]) {
    assert.ok(!shown.includes(word), shown);
  }
});

test("证据与截图：检查名称、试用用例的名称、结论与截图引用都从查询结果来", () => {
  const review = reviewEntry({
    criteria: [
      criterion({ criterion: "AC1", method: "trial", result: "passed", trial_cases: ["case_1", "case_missing"] }),
      criterion({ criterion: "AC2", method: "check", result: "passed", checks: ["smoke", "lint"] }),
    ],
    trial_cases: [
      { case_id: "case_1", title: "添加一条待办", result: "passed",
        screenshots: [screenshotRef("a"), screenshotRef("b")] },
    ],
  });
  const [first, second] = criterionRows(review, null);
  assert.deepEqual(first.cases.map((item) => [item.title, item.resultName]), [
    ["添加一条待办", "通过"],
    ["试用用例的记录不在这一份结论里", ""],
  ]);
  assert.deepEqual(first.screenshots.map((item) => item.contentHash), ["sha256:a", "sha256:b"]);
  assert.equal(first.hiddenScreenshots, 0);
  assert.deepEqual(second.checks, ["smoke", "lint"]);
  assert.deepEqual(second.screenshots, []);
});

test("一条条件引用的截图很多时只列前几张，其余的写明还有多少张", () => {
  const screenshots = Array.from({ length: SCREENSHOT_LIMIT + 2 }, (_, index) => screenshotRef(String(index)));
  const review = reviewEntry({
    criteria: [criterion({ criterion: "AC1", method: "trial", result: "passed", trial_cases: ["case_1"] })],
    trial_cases: [{ case_id: "case_1", title: "添加一条待办", result: "passed", screenshots }],
  });
  const [row] = criterionRows(review, null);
  assert.equal(row.screenshots.length, SCREENSHOT_LIMIT);
  assert.equal(row.hiddenScreenshots, 2);
});

test("无法核验的条目与原因逐条写出，方法用中文、没有写原因时写明", () => {
  const review = reviewEntry({
    unverified: [
      { criterion: "AC2", method: "judgement", note: "参照材料里没有写清楚" },
      { criterion: "AC4", method: "open", note: "" },
    ],
  });
  assert.deepEqual(unverifiedViews(review), [
    { criterion: "AC2", methodName: "带参照材料的判定点", note: "参照材料里没有写清楚" },
    { criterion: "AC4", methodName: "开环", note: "没有写明原因" },
  ]);
  assert.deepEqual(unverifiedViews(reviewEntry({ unverified: [] })), []);
});

test("交付一项的启动方式按种类、系统与命令列出；没有写启动方式时是空表", () => {
  const rows: LaunchRowView[] = launchViews([
    {
      name: "待办清单网页",
      kind: "web",
      commands: {
        linux: ["python3", "-m", "http.server", "{port}"],
        windows: ["python", "-m", "http.server", "{port}"],
      },
      ready_url: "http://127.0.0.1:{port}/",
      ready_timeout_sec: 30,
    },
    { name: "", kind: "desktop", commands: { windows: ["todo.exe"] } },
  ]);
  assert.deepEqual(rows.map((row) => [row.name, row.kindName, row.readyUrl, row.readyTimeoutSec]), [
    ["待办清单网页", "网页", "http://127.0.0.1:{port}/", 30],
    ["未命名启动方式", "桌面", null, null],
  ]);
  // Windows 在 Linux 前面列出，与命令表里写的先后无关
  assert.deepEqual(rows[0].commands.map((item) => [item.system, item.argv]), [
    ["Windows", ["python", "-m", "http.server", "{port}"]],
    ["Linux", ["python3", "-m", "http.server", "{port}"]],
  ]);
  assert.equal(launchKindName(""), "未注明种类");
  assert.equal(launchKindName("service"), "其他种类");
  assert.equal(launchSystemName("windows"), "Windows");
  assert.equal(launchSystemName("linux"), "Linux");
  assert.equal(launchSystemName("plan9"), "其他系统");
  assert.deepEqual(launchViews([]), []);
  assert.deepEqual(launchViews(undefined), []);
});
