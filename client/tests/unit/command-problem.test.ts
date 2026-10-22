// 命令没有成功时页面上显示的那句话（工单 #740）：
// 服务端按 422 拒绝一条命令时，页面上要有一句能看懂的中文说明，不再是一个空的错误框
// （用户使用记录 U89：清空「部门 Prompt」保存以后，页面上只多出一个 <p class="error"></p>）。
//
// 这一张核对四件事：
// 1. 三种失败按响应体与状态码分得开：应用层拒绝、接口层校验错误、其余；
// 2. 422 的说明就是服务端给的那句话，页面上不出现字段错误明细、字段路径与英文机器短语；
// 3. 应用层拒绝仍然原样显示服务端的中文说明（工单 #319 第 5 项的约定不变）；
// 4. 反馈组件渲染出来的段落不是空的。
//
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import {
  classifyCommandFailure,
  commandProblemText,
  type CommandProblem,
} from "../../src/renderer/src/contract/command-problem.ts";
import type { Rejected } from "../../src/renderer/src/api/generated/types.gen.ts";

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
const { CommandFeedback } = require("../../src/renderer/src/views/project/common.tsx");

// 服务端按 422 拒绝一条命令时的响应体：字段错误明细与一句中文说明
const REJECTED_422 = {
  detail: [
    {
      type: "string_too_short",
      loc: ["body", "department_prompt"],
      msg: "String should have at least 1 character",
      input: "",
      ctx: { min_length: 1 },
    },
  ],
  error: "这次请求被拒绝：「部门 Prompt」不能为空，请修改以后再提交。",
};

function rejected(reason: string, message: string, currentVersion: number | null = null): Rejected {
  return {
    command_id: "cmd_1",
    reason: reason as Rejected["reason"],
    message,
    current_version: currentVersion,
  };
}

test("422 的响应体按接口层校验错误认，页面上显示服务端给的那句话", () => {
  const problem = classifyCommandFailure(REJECTED_422, 422);
  assert.equal(problem.kind, "invalid");
  const text = commandProblemText(problem);
  assert.equal(text, "这次请求被拒绝：「部门 Prompt」不能为空，请修改以后再提交。");
  // 页面上不出现字段错误明细、字段路径与英文机器短语
  assert.equal(text.includes("department_prompt"), false);
  assert.equal(text.includes("string_too_short"), false);
  assert.equal(text.includes("String should have"), false);
  assert.equal(text.includes("detail"), false);
  // 写明是这次请求被拒绝
  assert.match(text, /^这次请求被拒绝：/);
});

test("接口层校验错误仍带着响应体：按 JSON 编辑原始文档的地方要的是字段位置", () => {
  const problem = classifyCommandFailure(REJECTED_422, 422);
  assert.equal(problem.kind, "invalid");
  if (problem.kind !== "invalid") return;
  const detail = (problem.body as { detail?: { loc?: unknown[] }[] }).detail;
  assert.deepEqual(detail?.[0]?.loc, ["body", "department_prompt"]);
});

test("422 的响应体没有说明时写一句通用的，不把字段错误明细摆到页面上", () => {
  const problem = classifyCommandFailure({ detail: REJECTED_422.detail }, 422);
  assert.equal(problem.kind, "invalid");
  const text = commandProblemText(problem);
  assert.equal(text, "这次请求被拒绝：提交的内容没有通过服务端的检查，请修改以后再提交。");
  assert.equal(text.includes("loc"), false);
});

test("应用层拒绝按拒绝原样显示服务端的中文说明", () => {
  const problem = classifyCommandFailure(rejected("not_allowed", "现在不能重新开始建档"), 409);
  assert.equal(problem.kind, "rejected");
  assert.equal(commandProblemText(problem), "现在不能重新开始建档");
  // 基准版本过期仍然给出可操作的一句
  const stale = classifyCommandFailure(rejected("stale_base", "基准版本已经过期", 7), 409);
  assert.match(commandProblemText(stale), /^基准版本已经过期（服务端当前版本 7），请重新读取以后提交$/);
});

test("其余失败按状态码写一句中文：不是空框，也不出现英文机器短语", () => {
  const failed = classifyCommandFailure({ detail: "Internal Server Error" }, 500);
  assert.equal(failed.kind, "failed");
  const text = commandProblemText(failed);
  assert.match(text, /这次请求没有成功/);
  assert.equal(text.includes("Internal Server Error"), false);
  assert.equal(text.includes("500"), false);
  // 网络不通：没有响应，状态码是 0
  const offline = classifyCommandFailure(new TypeError("Failed to fetch"), 0);
  assert.equal(offline.kind, "failed");
  assert.match(commandProblemText(offline), /联系不上服务/);
});

test("反馈组件渲染出来的段落不是空的：页面上看得见那一句说明", () => {
  const problem: CommandProblem = classifyCommandFailure(REJECTED_422, 422);
  const html = renderToStaticMarkup(React.createElement(CommandFeedback, { submitted: false, problem }));
  assert.match(html, /class="error"/);
  assert.match(html, /role="status"/);
  // 早先这里是 <p class="error" role="status"></p>：元素在，内容是空的（用户使用记录 U89）
  assert.match(html, /这次请求被拒绝：「部门 Prompt」不能为空，请修改以后再提交。/);
  assert.equal(/<p class="error" role="status"><\/p>/.test(html), false);
});

test("没有失败时反馈组件不渲染任何东西", () => {
  const html = renderToStaticMarkup(React.createElement(CommandFeedback, { submitted: false, problem: null }));
  assert.equal(html, "");
});
