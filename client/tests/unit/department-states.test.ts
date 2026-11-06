// 部门工作间的部门状态、三个部门一行与传信管（原型 v12 设计说明第 3.1、3.3 节、
// 三部门的循环结构 docs/design/department-loop.md「部门的状态」，工单 #905）：
// 标题区写本部门的状态与原因，另起一行列出三个部门（本部门加粗），没有部门状态时按事项的结束方式写；
// 房间信息写传信管上等待本部门回答的询问数，为 0 时不写这一行。
// 用 node --test 运行，不依赖 Electron 与网络；三个部门一行按组件渲染成静态标记，
// 「本部门加粗」核对的是真的 <strong>，不看实现里怎么写的。

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import { departmentStateText, departmentStatusView, departmentsLineParts, lettersWaitingText } from "../../src/renderer/src/views/project/labels.ts";
import type { DepartmentStateView } from "../../src/renderer/src/views/project/labels.ts";
import {
  departmentFactRows, elapsedLimitText, interruptionFactRows, liveOutputAbsorb, liveOutputObserve, liveOutputSeed,
} from "../../src/renderer/src/views/project/floor-text.ts";
import type {
  AskView, DecisionView, ProjectLoopResult, WorkItemLoop,
} from "../../src/renderer/src/api/generated/types.gen.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
interface NodeModuleInternal {
  _compile(content: string, filename: string): void;
}

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

const { renderToStaticMarkup } = require("react-dom/server");
const { DepartmentsLine } = require("../../src/renderer/src/views/project/department.tsx");

const THREE: Record<string, DepartmentStateView> = {
  product: { state: "working", note: "回答工程的询问" },
  engineering: { state: "asking", note: "在等待产品的回答" },
  quality: { state: "waiting" },
};

// 部门页标题区拿到的查询结果里与状态有关的那几项（department.workspace）
function workspace(over: Record<string, unknown> = {}) {
  return {
    department: "engineering",
    run_id: "run_1",
    run_status: "running",
    status: "in_progress",
    stop_reason: null,
    departments: THREE,
    ...over,
  };
}

test("标题区写本部门的状态与原因：状态词是 departments 里的词，原因单独给出一句", () => {
  assert.deepEqual(departmentStatusView(workspace()), {
    text: "询问中", note: "在等待产品的回答", kind: "asking",
  });
  // 没有原因时不写括号里的那一句
  assert.deepEqual(
    departmentStatusView(workspace({ department: "quality" })),
    { text: "等待工作", note: "", kind: "idle" },
  );
  // 在询问分支里回答别人的部门是「一轮工作中」，原因是回答谁的询问
  assert.deepEqual(
    departmentStatusView(workspace({ department: "product" })),
    { text: "一轮工作中", note: "回答工程的询问", kind: "running" },
  );
  // 「等用户」：部门有一条没有回答、阻塞事项的决定请求（三部门的循环结构 docs/design/department-loop.md「部门的状态」）
  assert.deepEqual(
    departmentStatusView(workspace({
      department: "engineering",
      departments: { ...THREE, engineering: { state: "waiting_user" } },
    })),
    { text: "等用户", note: "", kind: "waiting" },
  );
});

test("一个部门的状态与原因写成一段：有原因时写在括号里", () => {
  assert.equal(departmentStateText({ state: "verifying", note: "等质检核验交付 r1" }), "核验中（等质检核验交付 r1）");
  assert.equal(departmentStateText({ state: "waiting" }), "等待工作");
  assert.equal(departmentStateText({ state: "waiting", note: null }), "等待工作");
});

test("departments 为空时按事项的结束方式写，不再写「正在工作」与「这次运行不在本部门」", () => {
  // 没有运行（项目没有事项、事项没有 run）
  assert.deepEqual(
    departmentStatusView(workspace({ run_id: null, run_status: null, status: null, departments: null })),
    { text: "空闲（这个范围里没有运行）", note: "", kind: "idle" },
  );
  // 用户停止的事项写「已停止」，与概览看板一致（工单 #319）
  assert.deepEqual(
    departmentStatusView(workspace({ run_status: "done", status: "stopped", stop_reason: "cancelled", departments: null })),
    { text: "已停止", note: "", kind: "cancelled" },
  );
  // 已经结束的事项写结束方式（停止原因），例如放行
  assert.deepEqual(
    departmentStatusView(workspace({ run_status: "done", status: "adopted", stop_reason: "released", departments: null })),
    { text: "已完成并放行", note: "", kind: "succeeded" },
  );
  // 暂停是终态，没有部门状态，写「已暂停」
  assert.deepEqual(
    departmentStatusView(workspace({ run_status: "paused", status: "in_progress", stop_reason: "cancelled", departments: null })),
    { text: "已暂停", note: "", kind: "paused" },
  );
  // 进程中断以后还没有继续：run 还在进行中，但没有部门状态
  assert.deepEqual(
    departmentStatusView(workspace({ run_status: "running", status: "in_progress", departments: null })),
    { text: "中断", note: "", kind: "cancelled" },
  );
  // 执行失败：有停止原因时写原因，没有时写 run 的状态
  assert.deepEqual(
    departmentStatusView(workspace({ run_status: "failed", status: "in_progress", stop_reason: "provider_error", departments: null })),
    { text: "模型服务失败", note: "", kind: "failed" },
  );
  assert.deepEqual(
    departmentStatusView(workspace({ run_status: "failed", status: "in_progress", stop_reason: null, departments: null })),
    { text: "执行失败", note: "", kind: "failed" },
  );
  // 有部门状态时这一行不写事项的结束方式
  assert.equal(departmentStatusView(workspace()).text, "询问中");
});

test("三个部门一行：按产品、工程、质检的顺序，本部门那一段标为当前部门", () => {
  assert.deepEqual(departmentsLineParts(THREE, "engineering"), [
    { text: "产品 一轮工作中（回答工程的询问）", current: false },
    { text: "工程 询问中（在等待产品的回答）", current: true },
    { text: "质检 等待工作", current: false },
  ]);
  // 没有部门状态时不写这一行
  assert.equal(departmentsLineParts(null, "engineering"), null);
  assert.equal(departmentsLineParts(undefined, "engineering"), null);
  assert.equal(departmentsLineParts({}, "engineering"), null);
});

test("三个部门一行渲染成本部门加粗：本部门那一段是 <strong>，其他部门不是", () => {
  const html = renderToStaticMarkup(React.createElement(DepartmentsLine, { departments: THREE, department: "engineering" }));
  assert.match(html, /三个部门/);
  assert.match(html, /<strong>工程 询问中（在等待产品的回答）<\/strong>/);
  assert.doesNotMatch(html, /<strong>产品/);
  assert.doesNotMatch(html, /<strong>质检/);
  // 顺序与分隔符：产品、工程、质检之间是「 · 」，开头与「三个部门」之间空一格
  assert.match(html, /<span>产品 一轮工作中（回答工程的询问）<\/span> · <strong>工程 询问中（在等待产品的回答）<\/strong> · <span>质检 等待工作<\/span>/);
  // departments 为空时不渲染这一行
  assert.equal(renderToStaticMarkup(React.createElement(DepartmentsLine, { departments: null, department: "engineering" })), "");
});

test("传信管一行：N 为 0 时不写，不为 0 时写 N 封询问等待本部门回答", () => {
  assert.equal(lettersWaitingText(0), null);
  assert.equal(lettersWaitingText(null), null);
  assert.equal(lettersWaitingText(undefined), null);
  assert.equal(lettersWaitingText(3), "传信管：3 封询问等待本部门回答");
  assert.equal(lettersWaitingText(1), "传信管：1 封询问等待本部门回答");
});

// ---------------------------------------------------------------------------
// 项目页的部门节与部门页的实时输出（工单 #1416）：原来只在画布上看得到的事实，页面按查询结果写出来。
// 行由 floor-text.ts 的纯函数给出，用例直接调用，不渲染画布。

const NOW = Date.parse("2026-01-01T00:02:30Z");

/** 一条询问：只写用例关心的字段。 */
function ask(overrides: Partial<AskView> & { id: string }): AskView {
  return {
    requester: "engineering",
    recipient: "product",
    question: "未知参数怎么处理？",
    status: "进行中",
    chain: ["engineering", "product"],
    depth: 0,
    start_position: 1,
    started_at: "2026-01-01T00:00:30Z",
    ...overrides,
  } as AskView;
}

/** 一条决定请求：只写用例关心的字段。 */
function decision(overrides: Partial<DecisionView> & { decision_id: string }): DecisionView {
  return {
    project_id: "p1",
    work_item_id: "w1",
    run_id: "run_1",
    kind: "model_unavailable",
    blocks: "run",
    version: 1,
    status: "open",
    requested_at: "2026-01-01T00:01:00Z",
    blocked: null,
    request: {} as DecisionView["request"],
    answer: null,
    ...overrides,
  } as DecisionView;
}

/** 一个事项：只写用例关心的字段。 */
function loopItem(overrides: Partial<WorkItemLoop> & { work_item_id: string }): WorkItemLoop {
  return {
    kind: "normal",
    sign: "实现回声工具",
    color_index: 1,
    status: "in_progress",
    department: "engineering",
    progress: null,
    round: 1,
    started_at: "2026-01-01T00:00:00Z",
    elapsed_sec: 90,
    time_limit_sec: 7200,
    pending_question: null,
    run_id: "run_1",
    adoption_id: null,
    recovery_state: null,
    stop_reason: null,
    last_department: null,
    version: 1,
    ...overrides,
  };
}

function loopOf(items: WorkItemLoop[]): ProjectLoopResult {
  return { project_id: "p1", work_items: items, adoptions: [] };
}

test("部门节：每个部门一行，写状态与原因、在等什么；等了多久只取两处精确的事实", () => {
  const rows = departmentFactRows({
    loop: loopOf([loopItem({
      work_item_id: "w1",
      departments: {
        product: { state: "working", note: "回答工程的询问" },
        engineering: { state: "asking", note: "在等待产品的回答" },
        quality: { state: "waiting" },
      },
    })]),
    asks: [ask({ id: "a1", requester: "engineering", recipient: "product" })],
    decisions: [],
    now: NOW,
  });
  assert.deepEqual(rows.map((row) => [row.department, row.state, row.waiting, row.waited, row.elapsed]), [
    // 询问的开始到这一刻：2 分整
    ["产品", "一轮工作中", "回答工程的询问", "", "1 分 30 秒 / 2 小时 0 分"],
    ["工程", "询问中", "在等待产品的回答", "2 分 0 秒", "1 分 30 秒 / 2 小时 0 分"],
    ["质检", "等待工作", "等关注的成果出新版本", "", "1 分 30 秒 / 2 小时 0 分"],
  ]);
  // 结束的事项没有部门状态：不写行
  assert.deepEqual(departmentFactRows({
    loop: loopOf([loopItem({ work_item_id: "w1", status: "adopted", departments: null })]),
    now: NOW,
  }), []);
});

test("部门节：等用户时按决定请求的发出时间算等待，别的部门的请求不算", () => {
  const rows = departmentFactRows({
    loop: loopOf([loopItem({
      work_item_id: "w1",
      departments: { engineering: { state: "waiting_user" } },
    })]),
    decisions: [
      decision({ decision_id: "d1", work_item_id: "w1", requested_at: "2026-01-01T00:01:30Z" }),
      decision({ decision_id: "d2", work_item_id: "w9", requested_at: "2026-01-01T00:00:01Z" }),
    ],
    now: NOW,
  });
  assert.deepEqual(rows.map((row) => [row.state, row.waiting, row.waited]), [
    ["等用户", "等你回答决定请求", "1 分 0 秒"],
  ]);
});

test("中断与待恢复：项目里被打断、等待恢复的事项一行一个", () => {
  const rows = interruptionFactRows(loopOf([
    loopItem({ work_item_id: "w1", recovery_state: "interrupted", department: "engineering" }),
    loopItem({ work_item_id: "w2", recovery_state: "waiting_resume", sign: "另一个事项", department: "quality" }),
    loopItem({ work_item_id: "w3", recovery_state: "running" }),
  ]));
  assert.deepEqual(rows.map((row) => [row.itemTitle, row.department, row.state, row.elapsed]), [
    ["实现回声工具", "工程", "中断", "1 分 30 秒 / 2 小时 0 分"],
    ["另一个事项", "质检", "待恢复", "1 分 30 秒 / 2 小时 0 分"],
  ]);
  assert.deepEqual(interruptionFactRows(null), []);
});

test("事项的已用时间与上限：进行中写两个时长，其余写「—」", () => {
  assert.equal(elapsedLimitText(loopItem({ work_item_id: "w1" })), "1 分 30 秒 / 2 小时 0 分");
  assert.equal(elapsedLimitText(loopItem({ work_item_id: "w1", status: "adopted" })), "—");
  assert.equal(elapsedLimitText(loopItem({ work_item_id: "w1", elapsed_sec: null })), "—");
  assert.equal(elapsedLimitText(null), "—");
});

test("实时的模型输出：只接 output 通道、同一个偏移只接一次、换了尝试从空字符串开始", () => {
  // 开始观察一次尝试
  let live = liveOutputObserve(null, "a1");
  assert.deepEqual(live, { attemptId: "a1", text: "" });
  // attempt.live 已有的文字作为起点
  live = liveOutputSeed(live, "a1", "正在阅读需求");
  assert.deepEqual(live, { attemptId: "a1", text: "正在阅读需求" });
  // 接着到达的片段按 offset 拼上
  const next = liveOutputAbsorb(live, { attemptId: "a1", channel: "output", offset: 6, text: "，整理验收条件" });
  assert.deepEqual(next, { attemptId: "a1", text: "正在阅读需求，整理验收条件" });
  // 与已经接上的文字重叠的片段、别的通道、别的尝试都不接
  assert.equal(liveOutputAbsorb(next, { attemptId: "a1", channel: "output", offset: 3, text: "重复" }), null);
  assert.equal(liveOutputAbsorb(next, { attemptId: "a1", channel: "reasoning", offset: 12, text: "推理" }), null);
  assert.equal(liveOutputAbsorb(next, { attemptId: "a2", channel: "output", offset: 12, text: "别的尝试" }), null);
  // 查询回来的文字更短时，保留已经接上的更长的那一份
  assert.deepEqual(liveOutputSeed(next, "a1", "正在阅读"), next);
  // 换了尝试：从空字符串开始
  assert.deepEqual(liveOutputObserve(next, "a2"), { attemptId: "a2", text: "" });
});
