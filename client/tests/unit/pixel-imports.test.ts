// H3 的导入方向测试（画面与播放设计说明第 8 节 H3、第 3 节的依赖方向；工单 #959）。
//
// 画面层（client/src/renderer/src/pixel/）是独立模块：它只认画面合同（pixel/contract.ts）与自己的声明表，
// 不导入页面组件（views/）、命令接口（contract/）、接口生成的类型（api/）、翻译层（translate/）与 React。
// 翻译层反过来只从画面合同与三张声明表取画面的东西，不导入画面层的实现。
//
// 测试按文件的导入语句逐个核对（用 TypeScript 的语法树取 import/export from 与动态 import，注释与字符串不参与），
// 并核对画面层的源码里没有出现事件种类夹具（client/tests/fixtures/event-types.json）里的任何一种事件名：
// 画面层认识事件种类就说明它还在读 Yudao 的说法，那是翻译层的事。
//
// generated/ 是按构建期脚本从原型导出的数据（floor-decl.json），不是手写源码，不在这一条的范围内：
// 它里面的 eventActions/sayCatalog 是没有被源码用的导出数据，改名与删除属于生成脚本那一侧（见交付说明）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { posix } from "node:path";
import ts from "typescript";

const here = dirname(fileURLToPath(import.meta.url));
/** 渲染进程的源码根：文件路径在这里面用 / 分隔写。 */
const rendererRoot = resolve(here, "..", "..", "src", "renderer", "src");
const pixelRoot = join(rendererRoot, "pixel");
const translateRoot = join(rendererRoot, "translate");
const fixturePath = resolve(here, "..", "fixtures", "event-types.json");

/** 一份源码：路径从渲染进程的源码根起，文本是文件内容。 */
interface Source {
  file: string;
  text: string;
}

/** 画面层的文件不许导入的目录（从渲染进程的源码根起算）。 */
const FORBIDDEN_DIRS = ["views/", "contract/", "api/", "translate/"] as const;

/** 翻译层可以从画面层取东西的文件：画面合同与三张声明表。 */
const TRANSLATE_ALLOWED = new Set([
  "pixel/contract.ts",
  "pixel/world/floor-decl.ts",
  "pixel/room/room-decl.ts",
  "pixel/building/building-decl.ts",
]);

/** 目录下的源文件（.ts、.tsx），路径从渲染进程的源码根起算；generated 是按脚本导出的数据，不算手写源码。 */
function sourcesUnder(root: string): Source[] {
  const out: Source[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir).sort()) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) {
        if (name === "generated") continue;
        walk(full);
        continue;
      }
      if (!/\.tsx?$/.test(name)) continue;
      out.push({ file: relative(rendererRoot, full).split(sep).join("/"), text: readFileSync(full, "utf8") });
    }
  };
  walk(root);
  return out;
}

/** 一个文件里的导入语句指向的模块（相对路径原样，裸名称原样）。 */
function specifiersOf(file: string, text: string): string[] {
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.ES2022, false);
  const out: string[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      const spec = node.moduleSpecifier;
      if (spec && ts.isStringLiteral(spec)) out.push(spec.text);
    }
    // 动态 import("…")：与静态导入一样算依赖
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      const arg = node.arguments[0];
      if (arg && ts.isStringLiteral(arg)) out.push(arg.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

/** 相对路径的导入解析成从渲染进程的源码根起的路径；裸名称原样返回（不以点开头）。 */
function targetOf(from: string, spec: string): string {
  if (!spec.startsWith(".")) return spec;
  return posix.normalize(posix.join(posix.dirname(from), spec));
}

/** 画面层导入了不许导入的东西（页面、命令接口、接口生成、翻译层、React）。 */
function pixelImportViolations(sources: Source[]): string[] {
  const out: string[] = [];
  for (const { file, text } of sources) {
    if (!file.startsWith("pixel/")) continue;
    for (const spec of specifiersOf(file, text)) {
      if (/^(react|react-dom)(\/|$)/.test(spec)) out.push(`${file} 导入了 React：${spec}`);
      if (!spec.startsWith(".")) continue;
      const target = targetOf(file, spec);
      const dir = FORBIDDEN_DIRS.find((d) => target.startsWith(d));
      if (dir) out.push(`${file} 导入了 ${dir}：${spec}（解析为 ${target}）`);
    }
  }
  return out;
}

/** 翻译层从画面层的实现里取东西（只许取画面合同与三张声明表）。 */
function translateImportViolations(sources: Source[]): string[] {
  const out: string[] = [];
  for (const { file, text } of sources) {
    if (!file.startsWith("translate/")) continue;
    for (const spec of specifiersOf(file, text)) {
      if (!spec.startsWith(".")) continue;
      const target = targetOf(file, spec);
      if (!target.startsWith("pixel/")) continue;
      if (!TRANSLATE_ALLOWED.has(target)) out.push(`${file} 导入了画面层的实现：${spec}（解析为 ${target}）`);
    }
  }
  return out;
}

function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 画面层的源码里出现的事件种类名（名字两侧不是标识符的字符，避免命中更长的名字）。 */
function eventNameHits(sources: Source[], names: readonly string[]): string[] {
  const out: string[] = [];
  for (const { file, text } of sources) {
    if (!file.startsWith("pixel/")) continue;
    for (const name of names) {
      if (new RegExp(`(?<![A-Za-z0-9_])${escapeRe(name)}(?![A-Za-z0-9_])`).test(text)) {
        out.push(`${file} 里出现了事件种类 ${name}`);
      }
    }
  }
  return out;
}

function eventTypes(): string[] {
  const list = JSON.parse(readFileSync(fixturePath, "utf8")) as string[];
  assert.ok(list.length > 0, "事件种类夹具是空的");
  return list;
}

const realSources = (): Source[] => [...sourcesUnder(pixelRoot), ...sourcesUnder(translateRoot)];

test("H3：画面层不导入页面、命令接口、接口生成的类型、翻译层与 React", () => {
  assert.deepEqual(pixelImportViolations(realSources()), []);
});

test("H3：翻译层只从画面合同与三张声明表取画面的东西，不导入画面层的实现", () => {
  assert.deepEqual(translateImportViolations(realSources()), []);
});

test("H3：画面层的源码里没有出现事件种类夹具里的任何一种事件名", () => {
  assert.deepEqual(eventNameHits(realSources(), eventTypes()), []);
});

// 反向核对（验收标准 1）：把违规的样子写成样例文件，上面那几条检查必须报出来。
test("H3 反向核对：导入了 views/、contract/、api/、translate/ 与 React 的样例文件都会报错", () => {
  const sample: Source[] = [{
    file: "pixel/floor/sample-bad.ts",
    text: [
      'import { FloorScreen } from "../../views/project/floor-screen.tsx";',
      'import { ClientApp } from "../../contract/client-app.ts";',
      'import type { WorkItemLoop } from "../../api/generated/types.gen.ts";',
      'import { floorActions } from "../../translate/floor.ts";',
      'import React from "react";',
      'export { say } from "../../translate/say.ts";',
      "const lazy = () => import(\"../../views/project/floor-screen.tsx\");",
      "export const ok = 1;",
    ].join("\n"),
  }];
  const violations = pixelImportViolations(sample);
  // 七条：静态导入五条、再导出一条、动态 import 一条（动态 import 与静态导入一样算依赖）
  assert.equal(violations.length, 7, violations.join("\n"));
  for (const zone of ["views/", "contract/", "api/", "translate/", "React"]) {
    assert.ok(violations.some((v) => v.includes(zone)), `没有报出 ${zone}：${violations.join("\n")}`);
  }
  // 合法的依赖不报错：画面合同在自己的目录里，不是顶层的 contract/ 目录
  assert.deepEqual(pixelImportViolations([{
    file: "pixel/timeline.ts",
    text: 'import type { PixelAction } from "./contract.ts";\nimport { createScene } from "./world/scene.ts";\nimport { animDuration } from "../anims.ts";',
  }]), []);
});

test("H3 反向核对：翻译层导入画面层的实现会被报出来", () => {
  const violations = translateImportViolations([{
    file: "translate/building.ts",
    text: 'import type { BuildingModel } from "../pixel/world/building.ts";',
  }]);
  assert.equal(violations.length, 1);
  assert.match(violations[0], /pixel\/world\/building\.ts/);
  // 画面合同与三张声明表是许取的
  assert.deepEqual(translateImportViolations([{
    file: "translate/floor.ts",
    text: [
      'import type { PixelAction } from "../pixel/contract.ts";',
      'import { BUILDING_KINDS } from "../pixel/building/building-decl.ts";',
      'import { ROOM_KINDS } from "../pixel/room/room-decl.ts";',
      'import { KINDS } from "../pixel/world/floor-decl.ts";',
    ].join("\n"),
  }]), []);
});

test("H3 反向核对：画面层的源码里出现事件种类名会被报出来", () => {
  const hits = eventNameHits([{
    file: "pixel/world/sample-bad.ts",
    text: 'const CATALOG = { delivery_accepted: () => "现在装箱封存" };\nexport const tool_started = "x";',
  }], ["delivery_accepted", "tool_started"]);
  assert.equal(hits.length, 2, hits.join("\n"));
  // 更长的事件名不算命中更短的那一个
  assert.deepEqual(eventNameHits([{ file: "pixel/a.ts", text: "const k = 'ask_started_extra';" }], ["ask_started"]), []);
});
