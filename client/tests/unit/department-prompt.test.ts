// 项目级部门 Prompt 的来源与恢复（工单 #741）：
// 一个项目改过自己的部门 Prompt 以后，界面上要能回到内置默认；
// 「来源」按项说（本项目写入 / 内置默认），不按设置记录说；
// 按钮的名字要说它做的事：撤销本次修改是撤销本次修改，恢复默认是恢复默认。
//
// 这一张核对五件事：
// 1. 草稿分得出「这一段由本项目写入」与「这一段不写入」；
// 2. 清空文本框以后保存发的是「不写入」，不是一个会被 422 挡下的空串；
// 3. 「使用内置默认 Prompt」这个入口存在，撤销本次修改只撤销本次编辑；
// 4. 来源按项说：写入了是「本项目写入」，没写入是这一项自己的默认；
// 5. 页面上不出现英文内部标识与开发者措辞。
//
// 用 node --test 运行，不依赖 Electron 与网络。

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
const form = require("../../src/renderer/src/views/project/department-settings-form.tsx");
const { itemSource } = require("../../src/renderer/src/views/project/labels.ts");
import type { DepartmentSetting } from "../../src/renderer/src/api/generated/types.gen";

const { draftFromSetting, promptWritten, promptDraftOnInput, promptDraftRevert, promptDraftUseDefault,
  departmentSettingsPayload, DepartmentSettingsFields } = form;

const TEXT = "质检部门先核产品要求，再核实际结果，两样都要有证据。";

function setting(overrides: Partial<DepartmentSetting> = {}): DepartmentSetting {
  return {
    department: "quality",
    version: 2,
    text: TEXT,
    source: "configured",
    provider_id: null,
    model_id: null,
    requested_tier: null,
    department_setting_configured: true,
    ...overrides,
  } as DepartmentSetting;
}

test("草稿分得出「这一段由本项目写入」与「这一段不写入」", () => {
  // 本项目写过这一段：文本框里是这一段，保存时写入
  const written = draftFromSetting(setting());
  assert.equal(written.text, TEXT);
  assert.equal(written.writePrompt, true);
  // 这一段没有写入：文本框是空的，保存时不发这一项（服务端按没有写入处理）
  const blank = draftFromSetting(setting({ department_setting_configured: false }));
  assert.equal(blank.text, "");
  assert.equal(blank.writePrompt, false);
  // 旧服务端没有 department_setting_configured 这个字段：按已写入处理，
  // 不因为缺一个字段就把用户写的那一段丢掉
  const older = draftFromSetting(setting({ department_setting_configured: undefined }));
  assert.equal(older.text, TEXT);
  assert.equal(older.writePrompt, true);
});

test("来源按项说：写入了是本项目写入，没写入是这一项自己的默认", () => {
  assert.equal(itemSource(true, "内置默认"), "本项目写入");
  assert.equal(itemSource(false, "内置默认"), "内置默认");
  assert.equal(itemSource(false, "跟随部门默认"), "跟随部门默认");
  assert.equal(itemSource(false, "跟随"), "跟随");
  // 服务端明确说没有写入时才是内置默认；字段缺失时按已写入处理
  assert.equal(promptWritten(false, TEXT), false);
  assert.equal(promptWritten(true, TEXT), true);
  assert.equal(promptWritten(undefined, TEXT), true);
  assert.equal(promptWritten(false, ""), false);
});

test("清空文本框以后这一段按「不写入」处理，不再是一个会被 422 挡下的空串", () => {
  const draft = draftFromSetting(setting());
  const cleared = promptDraftOnInput(draft, "");
  assert.equal(cleared.text, "");
  assert.equal(cleared.writePrompt, false);
  // 只有空白字符同样是「没有内容」
  assert.equal(promptDraftOnInput(draft, "   \n ").writePrompt, false);
  // 输入文字以后又变回「由本项目写入」
  const typed = promptDraftOnInput(cleared, "新的质检要求");
  assert.equal(typed.text, "新的质检要求");
  assert.equal(typed.writePrompt, true);
});

test("两个动作各做各的事：撤销本次修改只撤销本次编辑，使用内置默认才是不写入", () => {
  const saved = draftFromSetting(setting());
  const edited = promptDraftOnInput(saved, "改了一半的文字");
  // 撤销本次修改：还原成已保存的那一份（不是恢复默认）
  const reverted = promptDraftRevert(edited, saved);
  assert.equal(reverted.text, TEXT);
  assert.equal(reverted.writePrompt, true);
  // 使用内置默认 Prompt：这一段不再由本项目写入
  const fallback = promptDraftUseDefault(edited);
  assert.equal(fallback.text, "");
  assert.equal(fallback.writePrompt, false);
});

test("保存时这一段不写入就发 null，基准版本取设置的版本", () => {
  const saved = draftFromSetting(setting());
  const payload = departmentSettingsPayload({
    projectId: "proj_1",
    department: "quality",
    setting: setting(),
    draft: promptDraftUseDefault(saved),
  });
  assert.equal(payload["department_prompt"], null);
  assert.equal(payload["base_version"], 2);
  assert.equal(payload["project_id"], "proj_1");
  assert.equal(payload["department"], "quality");
  // 写入时发的是这一段的文字
  const written = departmentSettingsPayload({
    projectId: "proj_1",
    department: "quality",
    setting: setting(),
    draft: saved,
  });
  assert.equal(written["department_prompt"], TEXT);
});

test("表单里有一行中文说明说清这一段写不写，两个按钮的名字说它们做的事", () => {
  const saved = draftFromSetting(setting());
  const html = renderToStaticMarkup(React.createElement(DepartmentSettingsFields, {
    app: null,
    projectId: "proj_1",
    department: "quality",
    draft: saved,
    onDraft: () => undefined,
    effective: null,
    reminders: [],
    saved,
  }));
  // 这一段由本项目写入时，说明与两个按钮都在
  assert.match(html, /这一段由本项目写入，保存以后按这里的内容生效。/);
  assert.match(html, /撤销本次修改/);
  assert.match(html, /使用内置默认 Prompt/);
  // 名字不副实的那个按钮没有了
  assert.equal(html.includes("恢复默认</button>"), false);
  // 页面上不出现英文内部标识与开发者措辞
  assert.equal(html.includes("department_prompt"), false);
  assert.equal(html.includes("writePrompt"), false);
  assert.equal(html.includes("configured"), false);
  assert.equal(html.includes("Prompt</span>"), true);
});

test("这一段不写入时说明写明用内置默认，文本框是空的", () => {
  const saved = draftFromSetting(setting({ department_setting_configured: false }));
  const html = renderToStaticMarkup(React.createElement(DepartmentSettingsFields, {
    app: null,
    projectId: "proj_1",
    department: "quality",
    draft: saved,
    onDraft: () => undefined,
    effective: null,
    reminders: [],
    saved,
  }));
  assert.match(html, /这一段不写入本项目，部门使用内置默认 Prompt。/);
  // 文本框里没有内容：这一段不由本项目写入
  assert.match(html, /<textarea[^>]*><\/textarea>/);
});
