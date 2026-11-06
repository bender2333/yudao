// 离开期间的报告里的开环明细（工单 #401；验证的独立性设计说明「检验覆盖与开环」、「口径」；应用层与接口层设计说明
// 「查询清单」 `home.away_report` 与 `acceptance.coverage`）：
// 报告里「带开环条件的放行」一项逐条列出每个放行的开环条件，条数与明细取自 `acceptance.coverage`
// （放行记录里一次算好，页面读这个数，不重新计算）；事项的名称取自 project.overview；
// 「跳到逐条结论表」的链接在逐条结论表交付以后（#154）出现；页面文字里没有英文内部标识，
// 也不写事项一级的「开环完成」。
//
// 用 node --test 运行，不依赖服务与网络：输入是查询结果的形状（与 api/generated/types.gen 的
// ReportItem、ReportFact 与 AcceptanceCoverageResult 相同），断言的是页面上的那几行字。
// 守 R2（查询交换的字段：条数与开环明细取自 acceptance.coverage 的 numbers.open 与 open_criteria，
// 位置取自报告项的 refs）与 R3（检验覆盖与开环在页面上看得到，与放行记录一致）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import type { AcceptanceCoverageResult, ReportFact, ReportItem } from "../../src/renderer/src/api/generated/types.gen";
import { CRITERIA_TABLE_READY, openCriteriaText } from "../../src/renderer/src/views/project/labels.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
interface NodeModuleInternal {
  _compile(content: string, filename: string): void;
}

// TSX 的组件文件按 CommonJS 转译以后加载：与 views/project 里几个组件用例的做法相同，
// 这样纯函数可以直接调用，不用渲染整页
const React = require("react");
const globalScope = globalThis as Record<string, unknown>;
globalScope["React"] = React;

function loader(module: NodeJS.Module, filename: string) {
  const code = fs.readFileSync(filename, "utf8");
  const js = ts.transpileModule(code, {
    compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const internalModule = module as unknown as NodeModuleInternal;
  internalModule._compile(js, filename);
}
require.extensions[".tsx"] = loader;
require.extensions[".ts"] = loader;

const { openReleaseRows, openReleaseTargets } = require(
  "../../src/renderer/src/views/home/away-report.tsx",
) as {
  openReleaseRows: (lookup: {
    targets: readonly OpenReleaseTarget[];
    titles: Readonly<Record<string, string>>;
    coverage: Readonly<Record<string, AcceptanceCoverageResult | null | undefined>>;
    projectNames: Readonly<Record<string, string>>;
    criteriaTableReady?: boolean;
  }) => OpenReleaseRow[];
  openReleaseTargets: (item: ReportItem | null | undefined, facts: readonly ReportFact[]) => OpenReleaseTarget[];
};

interface OpenReleaseTarget {
  position: number;
  projectId: string;
  workItemId: string;
  at: string | null;
}

interface OpenReleaseRow {
  position: number;
  at: string | null;
  where: string;
  text: string;
  state: "ready" | "reading" | "unreadable";
  href: string | null;
}

const PROJECT = "proj_echo";
const ITEM = "wi_echo";
// 报告里的一项：放行事件的位置在 refs 里，明细是服务端拼好的那句（页面不写这一句，逐条列在下面）
const OPEN_RELEASE: ReportItem = {
  id: "open_release",
  label: "带开环条件的放行",
  value: 1,
  unit: "次",
  refs: [42],
  detail: `${ITEM}：AC2、AC3`,
};

function fact(over: Partial<ReportFact> = {}): ReportFact {
  return {
    position: 42,
    at: "2026-11-03T09:30:00Z",
    type: "qa_submitted",
    kind: "release",
    label: "质检提交了结论：release",
    project_id: PROJECT,
    work_item_id: ITEM,
    ...over,
  };
}

// acceptance.coverage 的结果：三条验收条件，一条命令检查通过，一条判定点、一条开环（放行记录里
// numbers.open 是 2，open_criteria 是 AC2、AC3）
function coverage(over: Partial<AcceptanceCoverageResult> = {}): AcceptanceCoverageResult {
  return {
    run_id: "run_echo",
    work_item_id: ITEM,
    verdict: "release",
    review_event_id: "ev_review",
    revision: 1,
    numbers: {
      criteria_total: 3,
      executable: 1,
      covered: 1,
      coverage_ratio: 1 / 3,
      model_reading: 1,
      open: 2,
    },
    criteria: [
      { criterion: "AC1", method: "check", result: "passed", executable: true, open: false },
      { criterion: "AC2", method: "judgement", result: "unverified", executable: false, open: true },
      { criterion: "AC3", method: "open", result: "unverified", executable: false, open: true },
    ],
    open_criteria: ["AC2", "AC3"],
    ...over,
  };
}

function lookup(over: {
  targets?: readonly OpenReleaseTarget[];
  titles?: Readonly<Record<string, string>>;
  coverage?: Readonly<Record<string, AcceptanceCoverageResult | null | undefined>>;
  projectNames?: Readonly<Record<string, string>>;
  criteriaTableReady?: boolean;
} = {}) {
  return {
    targets: over.targets ?? openReleaseTargets(OPEN_RELEASE, [fact()]),
    titles: over.titles ?? { [ITEM]: "实现回声工具" },
    coverage: over.coverage ?? { [ITEM]: coverage() },
    projectNames: over.projectNames ?? { [PROJECT]: "示例项目" },
    ...(over.criteriaTableReady === undefined ? {} : { criteriaTableReady: over.criteriaTableReady }),
  };
}

test("报告项指向的位置换成放行：项目与事项取自同一份报告的关键事实", () => {
  const targets = openReleaseTargets(OPEN_RELEASE, [fact()]);
  assert.deepEqual(targets, [{
    position: 42, projectId: PROJECT, workItemId: ITEM, at: "2026-11-03T09:30:00Z",
  }]);
  // 不是这一项的报告项、没有事实的位置都不列：位置没有对应事实时不编一个事项出来
  assert.deepEqual(openReleaseTargets({ ...OPEN_RELEASE, id: "released" }, [fact()]), []);
  assert.deepEqual(openReleaseTargets({ ...OPEN_RELEASE, refs: [7] }, [fact()]), []);
  assert.deepEqual(openReleaseTargets(null, [fact()]), []);
});

test("每个放行列出它的开环条件，条数与明细取自 acceptance.coverage", () => {
  const rows = openReleaseRows(lookup());
  assert.equal(rows.length, 1);
  const [row] = rows;
  assert.equal(row.position, 42);
  // 条数是 numbers.open（2），明细是 open_criteria（AC2、AC3）：页面不重新数一遍逐条结论
  assert.equal(row.text, "开环条件 2 条：AC2、AC3");
  assert.equal(row.state, "ready");
  // 页面写项目名与事项标题，不写 wi_ 这样的事项标识
  assert.equal(row.where, "示例项目 / 实现回声工具");
  assert.ok(!row.text.includes(ITEM), row.text);
  assert.ok(!row.where.includes(ITEM), row.where);
});

test("条数与明细跟着查询走：放行记录里是几条就写几条，页面不自己算", () => {
  const rows = openReleaseRows(lookup({
    coverage: {
      [ITEM]: coverage({
        numbers: { criteria_total: 4, executable: 3, covered: 3, coverage_ratio: 0.75, model_reading: 0, open: 1 },
        open_criteria: ["AC4"],
      }),
    },
  }));
  assert.equal(rows[0].text, "开环条件 1 条：AC4");
});

test("还没有读到与读不出来是两句话：不把「正在读取」当成「没有开环条件」", () => {
  const reading = openReleaseRows(lookup({ coverage: {} }));
  assert.equal(reading[0].state, "reading");
  assert.equal(reading[0].text, "正在读取开环明细");
  const unreadable = openReleaseRows(lookup({ coverage: { [ITEM]: null } }));
  assert.equal(unreadable[0].state, "unreadable");
  assert.equal(unreadable[0].text, "开环明细读不出来");
});

test("事项标题取不到时写「未记事项」，不把事项标识写进页面", () => {
  const rows = openReleaseRows(lookup({ titles: {} }));
  assert.equal(rows[0].where, "示例项目 / 未记事项");
  assert.ok(!rows[0].where.includes("wi_"), rows[0].where);
});

test("「跳到逐条结论表」的链接在逐条结论表交付以后出现（#154）", () => {
  // 资料页已经有这张表：默认就给出链接，落到这个事项的资料页
  assert.equal(CRITERIA_TABLE_READY, true);
  assert.equal(openReleaseRows(lookup())[0].href, `#/p/${PROJECT}/materials?w=${ITEM}`);
  // 读不出检验覆盖的那一行不给链接：没有条数可对照的表不看
  const unreadable = openReleaseRows(lookup({ criteriaTableReady: true, coverage: { [ITEM]: null } }));
  assert.equal(unreadable[0].href, null);
});

test("明细的文字里没有英文内部标识，也没有事项一级的开环完成", () => {
  const text = openReleaseRows(lookup()).map((row) => `${row.where}${row.text}`).join("\n")
    + openCriteriaText(2, ["AC2", "AC3"]);
  for (const word of ["judgement", "open_criteria", "coverage", "unverified", "passed", "wi_", "run_", "release"]) {
    assert.ok(!text.includes(word), `页面文字里出现了 ${word}：${text}`);
  }
  // 「开环完成」是事项一级的记号（定义里没有核验角色），本页写的是验收条件一级的开环明细
  assert.ok(!text.includes("开环完成"), text);
});
