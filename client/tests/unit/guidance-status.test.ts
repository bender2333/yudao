// 部门指导的三种状态（原型 v12 设计说明第 3.4 节，main 上现存的路径是
// docs/archive/prototypes/v12/design.md；部门指导的处理设计第 3 节；工单 #906）：
// 指导只有已接收、已进入模型输入、已回答三种状态，没有「正式回应」；
// 部门工作间那一节的说明是「部门正在工作时，指导在它的下一步作为通知加入；部门在等待工作时，以这段指导开始一轮工作」，
// 页面上没有「部门的回应」一行，也没有「已接收的指导在下一次安全激活……」的旧说明。
//
// 用 node --test 运行，不依赖 Electron 与网络。状态词按组件渲染成静态标记核对（「这条指导现在显示哪几个字」
// 看的是真的 <strong>，不看实现里怎么写的）；指导记录用 #1039 合并以后的接口夹具（GuidanceRecord：
// guidance_id、version、text、status、applied_activation_id、answered_activation_id、outcome、created_event_id），
// 同一条指导依次取 received、in_input、answered，对应页面上依次显示三个状态词。

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import { GUIDANCE_STATUS } from "../../src/renderer/src/views/project/labels.ts";

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
const { GuidanceSection } = require("../../src/renderer/src/views/project/department.tsx");

// 接口里的三种状态（#1039）：查询 department.workspace 的 guidance 一项，同一条指导随着工作推进换状态
const STATUS_IN_ORDER = ["received", "in_input", "answered"];

// #1039 的接口夹具：一条指导在某一刻的样子。applied_activation_id 从已进入模型输入起有值，
// answered_activation_id 与 outcome 只在已回答时有值（主机在收到它的那一轮正常结束时写）
function guidance(status: string, over: Record<string, unknown> = {}) {
  return {
    guidance_id: "gdn_1",
    version: 1,
    text: "先写迁移脚本，再改接口",
    status,
    applied_activation_id: status === "received" ? null : "act_1",
    answered_activation_id: status === "answered" ? "act_1" : null,
    outcome: status === "answered" ? "text_reply" : null,
    created_event_id: "evt_1",
    ...over,
  };
}

function render(records: unknown[], onOpenEvent: (eventId: string) => void = () => {}) {
  return renderToStaticMarkup(React.createElement(GuidanceSection, { guidance: records, onOpenEvent }));
}

// 渲染出来的那一节里，此刻写着哪几个状态词（只认 <strong> 里的那个，指导原文不参与）
function shownStatus(html: string): string[] {
  return STATUS_IN_ORDER
    .map((status) => GUIDANCE_STATUS[status])
    .filter((word) => html.includes(`<strong>${word}</strong>`));
}

test("指导只有三种状态：已接收、已进入模型输入、已回答", () => {
  assert.deepEqual(GUIDANCE_STATUS, {
    received: "已接收",
    in_input: "已进入模型输入",
    answered: "已回答",
  });
  // 原来的四种（正式回应那一套）删掉了，不留其中一个（工单 #906）
  for (const gone of ["explained", "completed", "declined", "needs_work"]) {
    assert.equal(Object.hasOwn(GUIDANCE_STATUS, gone), false, `${gone} 不该再出现在指导状态里`);
  }
  // 界面上不出现「正式回应」「回应」：三种状态的中文名里没有这两个字
  for (const word of Object.values(GUIDANCE_STATUS)) {
    assert.equal(word.includes("回应"), false, `${word} 里不该有「回应」`);
  }
});

test("同一条指导依次显示已接收、已进入模型输入、已回答，每次只写一个状态词", () => {
  const seen = STATUS_IN_ORDER.map((status) => shownStatus(render([guidance(status)])));
  assert.deepEqual(seen, [["已接收"], ["已进入模型输入"], ["已回答"]]);
  // 原文与版本照旧写出来
  const html = render([guidance("in_input")]);
  assert.match(html, /先写迁移脚本，再改接口/);
  assert.match(html, /第 1 版/);
});

test("指导一节的说明改成「下一步作为通知加入 / 以这段指导开始一轮工作」", () => {
  const html = render([guidance("received")]);
  assert.match(html, /部门正在工作时，指导在它的下一步作为通知加入；部门在等待工作时，以这段指导开始一轮工作/);
  // 旧说明「已接收的指导在下一次安全激活进入模型输入」没有了
  assert.doesNotMatch(html, /下一次安全激活/);
  assert.doesNotMatch(html, /安全激活/);
});

test("没有「部门的回应」一行：已回答的指导也只写状态、版本与原文", () => {
  const html = render([guidance("answered", { outcome: "proposal_accepted" })]);
  assert.doesNotMatch(html, /部门的回应/);
  assert.doesNotMatch(html, /正式回应/);
  assert.doesNotMatch(html, /回应/);
  // 已回答的指导仍然显示为一条记录，不是被藏起来
  assert.match(html, /<strong>已回答<\/strong>/);
});

test("没有指导记录时写空态，不写一条假记录", () => {
  const html = render([]);
  assert.match(html, /这个部门还没有指导记录/);
  assert.equal(shownStatus(html).length, 0);
});
