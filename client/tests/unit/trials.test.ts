// 部门工作间「试用记录」页签的纯函数与页面文字（工单 #153；浏览器与 computer use
// docs/design/browser-and-computer-use.md「查询」、「页面与画面」）。
//
// 查五件事：
// 1. 试用会话写成中文：种类、启动方式、试用副本与交付快照的比较、开始与结束、结束方式；进行中的会话照写；
// 2. 试用用例按用例列出引用的验收条件、计划、预期、结论与观察到的结果；步骤的操作写成中文，
//    输入的文字是这次试用的内容；作为证据的步骤有标记；
// 3. 截图取所属动作回执的事件标识；模型有没有看到这张截图按 request_had_images 写成三句；
// 4. 文本模型（收到结果的请求不含图像）时页签上写明「模型只读取文字」；都看到图像时没有这一句；
// 5. 页面上不出现英文内部标识：工具名、会话标识、树摘要与 passed 这类代码名都不出现，认不出的取值有中文说法。
//
// 守 docs/design/test-pyramid.md「测试按三环留」的 R3（路线图阶段二写明的试用记录与截图在页面上显示）：
// 只经查询结果的交换字段与页面文字检查，不看内部实现。用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";

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
const { TrialRecords, trialView } = require("../../src/renderer/src/views/project/trials.tsx");
const labels = require("../../src/renderer/src/views/project/labels.ts");
import type {
  RunActionsResult,
  TrialCaseView,
  TrialDepartmentView,
  TrialSessionView,
  TrialStepView,
} from "../../src/renderer/src/api/generated/types.gen.ts";

const HASH = "sha256:" + "a".repeat(64);
const TREE = "sha256:" + "b".repeat(64);

function shotRef(contentHash = HASH): Record<string, unknown> {
  return { kind: "screenshot", content_hash: contentHash, path: `artifacts/${contentHash}`, media_type: "image/png" };
}

function session(overrides: Partial<TrialSessionView> = {}): TrialSessionView {
  return {
    session_id: "ses_quality_1",
    department: "quality",
    kind: "web",
    launch_name: "待办清单网页",
    tree_digest: TREE,
    source: "delivery_snapshot",
    delivery_snapshot_hash: TREE,
    matches_delivery_snapshot: true,
    started_at: "2026-11-06T10:00:00Z",
    ended_at: "2026-11-06T10:20:00Z",
    end_reason: "stopped",
    status: "ended",
    ...overrides,
  };
}

function step(overrides: Partial<TrialStepView> = {}): TrialStepView {
  return {
    identity: "call-1",
    tool: "browser_type",
    step_id: 2,
    activation_id: "act_1",
    status: "completed",
    ok: true,
    error: null,
    input: { text: "买牛奶" },
    screenshots: [shotRef()],
    accessibility: "输入框「待办」",
    request_had_images: false,
    evidence: false,
    ...overrides,
  };
}

function trialCase(overrides: Partial<TrialCaseView> = {}): TrialCaseView {
  return {
    case_id: "case_1",
    department: "quality",
    session_id: "ses_quality_1",
    trial_session_id: "ses_quality_1",
    product_spec_hash: "sha256:" + "c".repeat(64),
    criteria: [{ criterion: "AC1", text: "列表显示一条待办" }],
    title: "添加一条待办",
    plan: ["打开列表页", "点添加"],
    expected: "列表里出现这条待办",
    status: "concluded",
    result: "passed",
    observed: "列表里出现了「买牛奶」",
    reason: "",
    evidence_steps: ["call-2"],
    steps: [
      step(),
      step({
        identity: "call-2", tool: "browser_verify_text_visible", step_id: 3,
        input: { text: "买牛奶" }, screenshots: [], accessibility: null, evidence: true,
      }),
    ],
    ...overrides,
  };
}

function group(overrides: Partial<TrialDepartmentView> = {}): TrialDepartmentView {
  return { department: "quality", sessions: [session()], cases: [trialCase()], ...overrides };
}

function actionResult(): RunActionsResult {
  return {
    background_commands: [],
    actions: [{
      action_id: "call-1",
      tool: "browser_type",
      department: "quality",
      status: "completed",
      activation_id: "act_1",
      step_id: 2,
      input_version: null,
      prompt_version: null,
      created_at: "2026-11-06T10:05:00Z",
      receipt: {
        args: { text: "买牛奶" },
        ok: true,
        error: null,
        output_ref: null,
        event_id: "evt_call_1",
        created_at: "2026-11-06T10:05:00Z",
      },
      before_snapshot_ref: null,
      after_snapshot_ref: null,
    }],
  };
}

test("试用会话写成中文：种类、启动方式、与交付快照的比较、结束方式", () => {
  const view = trialView(group(), null);
  assert.equal(view.sessions.length, 1);
  const row = view.sessions[0];
  assert.equal(row.kindName, "网页");
  assert.equal(row.launchName, "待办清单网页");
  assert.equal(row.copyText, "交付快照的副本，与交付快照相同");
  assert.equal(row.stateText, "已结束（已停止）");
  assert.ok(row.endedAt !== null);
});

test("进行中的会话与还在进行的用例照写，不编一个结束时间", () => {
  const running = session({
    ended_at: null, end_reason: null, status: "running", matches_delivery_snapshot: false,
  });
  const open = trialCase({ status: "open", result: null, observed: "" });
  const view = trialView(group({ sessions: [running], cases: [open] }), null);
  assert.equal(view.sessions[0].stateText, "进行中");
  assert.equal(view.sessions[0].endedAt, null);
  assert.equal(view.sessions[0].copyText, "交付快照的副本，与交付快照不同");
  assert.equal(view.cases[0].resultText, "进行中");
  assert.equal(view.cases[0].resultKind, "running");
});

test("试用用例列出验收条件、计划、预期、结论与观察到的结果", () => {
  const view = trialView(group(), null);
  const item = view.cases[0];
  assert.equal(item.title, "添加一条待办");
  assert.deepEqual(item.criteria, [{ name: "AC1", text: "列表显示一条待办" }]);
  assert.deepEqual(item.plan, ["打开列表页", "点添加"]);
  assert.equal(item.expected, "列表里出现这条待办");
  assert.equal(item.resultText, "通过");
  assert.equal(item.resultKind, "succeeded");
  assert.equal(item.observed, "列表里出现了「买牛奶」");
});

test("步骤的操作写成中文，输入的文字是这次试用的内容；作为证据的步骤有标记", () => {
  const view = trialView(group(), null);
  const [first, second] = view.cases[0].steps;
  assert.equal(first.operation, "输入文字「买牛奶」");
  assert.equal(first.statusText, "已完成");
  assert.equal(first.evidence, false);
  assert.equal(second.operation, "核对页面上出现「买牛奶」");
  assert.equal(second.evidence, true);
  assert.equal(second.accessibility, null);
  // 工具名不表示成操作
  assert.doesNotMatch(first.operation, /browser_/);
});

test("截图按所属动作回执取事件，模型有没有看到写成三句话之一", () => {
  const view = trialView(group(), actionResult());
  const [shot] = view.cases[0].steps[0].shots;
  assert.equal(shot.eventId, "evt_call_1");
  assert.equal(shot.ref.kind, "screenshot");
  assert.equal(shot.modelSaw, false);
  assert.equal(labels.trialShotModelText(false), "模型只读取文字");
  assert.equal(labels.trialShotModelText(true), "模型看到了这张截图");
  assert.equal(labels.trialShotModelText(null), "没有记录模型是否看到这张截图");
  // 没有回执的步骤：截图的所属事件为空，页面写读不出来
  const withoutReceipt = trialView(group(), null);
  assert.equal(withoutReceipt.cases[0].steps[0].shots[0].eventId, null);
});

test("收到结果的请求不含图像时页签写明模型只读取文字；都看到图像时没有这一句", () => {
  assert.equal(trialView(group(), null).textOnly, true);
  const seen = trialCase({
    steps: [step({ request_had_images: true }), step({ identity: "call-2", request_had_images: true, screenshots: [] })],
  });
  const view = trialView(group({ cases: [seen] }), null);
  assert.equal(view.textOnly, false);
});

test("没有试用记录时两个清单都是空的", () => {
  const view = trialView(null, null);
  assert.deepEqual(view.sessions, []);
  assert.deepEqual(view.cases, []);
  assert.equal(view.textOnly, false);
});

test("认不出的取值写中文，不把代码名写到页面上", () => {
  const unknown = session({ kind: "other", source: "elsewhere", end_reason: "vanished" });
  const view = trialView(group({ sessions: [unknown], cases: [trialCase({
    title: "", result: null, status: "concluded",
    criteria: [{ criterion: "", text: null }],
    steps: [step({ tool: "mystery_tool", status: "paused", screenshots: [], input: {} })],
  })] }), null);
  assert.equal(view.sessions[0].kindName, "其他种类");
  assert.equal(view.sessions[0].copyText, "其他副本来源");
  assert.equal(view.sessions[0].stateText, "已结束（其他结束方式）");
  assert.equal(view.cases[0].title, "未命名试用用例");
  assert.equal(view.cases[0].resultText, "未写明结果");
  assert.deepEqual(view.cases[0].criteria, [{ name: "未写编号的验收条件", text: null }]);
  assert.equal(view.cases[0].steps[0].operation, "其他试用操作");
  assert.equal(view.cases[0].steps[0].statusText, "其他结果状态");
});

test("页签的文字：会话与用例的中文、模型只读取文字，以及不出现英文内部标识", () => {
  const view = trialView(group(), actionResult());
  const html = renderToStaticMarkup(React.createElement(TrialRecords, { app: null, view }));
  assert.match(html, /试用会话（1 个）/);
  assert.match(html, /试用用例（1 个）/);
  assert.match(html, /AC1 列表显示一条待办/);
  assert.match(html, /输入文字「买牛奶」/);
  assert.match(html, /核对页面上出现「买牛奶」/);
  assert.match(html, /模型只读取文字/);
  assert.match(html, /模型只读取文字：这次试用里模型收到的内容只有文字/);
  assert.match(html, /证据/);
  // 内部标识与代码名不出现
  for (const word of ["browser_", "evt_call_1", "ses_quality_1", "case_1", "sha256", "delivery_snapshot",
    "stopped", "passed", "completed", "concluded", "request_had_images"]) {
    assert.doesNotMatch(html, new RegExp(word), `页面文字里出现了 ${word}`);
  }
});

test("模型看到图像时页签没有只读取文字的提示", () => {
  const seen = trialCase({
    steps: [step({ request_had_images: true }), step({ identity: "call-2", request_had_images: true })],
  });
  const view = trialView(group({ cases: [seen] }), actionResult());
  const html = renderToStaticMarkup(React.createElement(TrialRecords, { app: null, view }));
  assert.doesNotMatch(html, /模型只读取文字：/);
  assert.match(html, /模型看到了这张截图/);
});
