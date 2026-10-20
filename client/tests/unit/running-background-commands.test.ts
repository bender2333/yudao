// 部门页动作列表运行中后台命令的单元测试（工单 #550）：
// 正在运行的后台命令显示命令原文、开始时间与运行中状态；
// 结束以后不再显示为运行中。
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
const { RunningBackgroundCommands } = require("../../src/renderer/src/views/project/department.tsx");
import type { BackgroundCommandView } from "../../src/renderer/src/api/generated/types.gen";
test("运行中的后台命令在动作列表中显示命令原文与运行中状态", () => {
  const commands: BackgroundCommandView[] = [
    {
      command: "python -m http.server 8080",
      started_at: "2026-10-20T10:00:00Z",
      status: "running",
    },
  ];
  const html = renderToStaticMarkup(React.createElement(RunningBackgroundCommands, { commands }));
  assert.match(html, /正在运行的后台命令（1 条）/);
  assert.match(html, /python -m http\.server 8080/);
  assert.match(html, /运行中/);
  assert.match(html, /命令原文/);
  assert.match(html, /开始时间/);
});

test("后台命令结束以后不再显示为运行中", () => {
  const commands: BackgroundCommandView[] = [
    {
      command: "python -m http.server 8080",
      started_at: "2026-10-20T10:00:00Z",
      status: "ended",
    },
  ];
  const html = renderToStaticMarkup(React.createElement(RunningBackgroundCommands, { commands }));
  assert.equal(html, "");
  assert.doesNotMatch(html, /运行中/);
  assert.doesNotMatch(html, /正在运行的后台命令/);
});

test("混合状态下只显示运行中的后台命令", () => {
  const commands: BackgroundCommandView[] = [
    {
      command: "python background_worker.py",
      started_at: "2026-10-20T10:05:00Z",
      status: "running",
    },
    {
      command: "python old_server.py",
      started_at: "2026-10-20T09:00:00Z",
      status: "ended",
    },
  ];
  const html = renderToStaticMarkup(React.createElement(RunningBackgroundCommands, { commands }));
  assert.match(html, /正在运行的后台命令（1 条）/);
  assert.match(html, /background_worker\.py/);
  assert.doesNotMatch(html, /old_server\.py/);
});

test("没有后台命令时不渲染任何内容", () => {
  const html = renderToStaticMarkup(React.createElement(RunningBackgroundCommands, { commands: [] }));
  assert.equal(html, "");
});
