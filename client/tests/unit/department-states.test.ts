// 部门工作间的部门状态、三个部门一行与传信管（原型 v12 设计说明第 3.1、3.3 节、
// 三部门的循环结构第 2.1 节，工单 #905）：
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
  // 「等用户」：部门有一条没有回答、阻塞事项的决定请求（三部门的循环结构第 2.1 节）
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
