// 页面与翻译层互不导入对方的文件（画面与播放设计说明「先补页面」、「测试」；工单 #1415）。
//
// 搬家的第一刀只切断导入方向，不改可见行为：
//   - 页面自己的文字与颜色在页面里各留一份（views/project/floor-text.ts、views/project/labels.ts），
//     页面的文字部分不导入 pixel/ 与 translate/；
//   - 画面要用的文字自己留一份（translate/face.ts），翻译层不导入 views/ 下的任何文件。
//
// 挂画布的那几行是例外：把画布接起来的三个组件仍要导入画面与翻译层，按文件逐条列在下面
// （搬画布留给后面的工单）。图鉴 views/pixel/gallery.tsx 整页是按登记表画元件的画布页，同样留给那个工单。
//
// 测试按文件的导入语句逐个核对（用 TypeScript 的语法树取 import/export from 与动态 import，注释与字符串不参与）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, posix, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const here = dirname(fileURLToPath(import.meta.url));
/** 渲染进程的源码根：文件路径在这里面用 / 分隔写。 */
const rendererRoot = resolve(here, "..", "..", "src", "renderer", "src");

/** 一份源码：路径从渲染进程的源码根起，文本是文件内容。 */
interface Source {
  file: string;
  text: string;
}

/**
 * 挂画布的几行：这三个组件把画布接起来，允许它们导入的画面与翻译层模块。
 * 名单逐条写出，多导一个就报错——文字与颜色不许再从画面取。
 */
const CANVAS_MOUNTS: Readonly<Record<string, readonly string[]>> = Object.freeze({
  "views/home/building-section.tsx": ["pixel/clock", "pixel/building/view", "translate/building"],
  "views/project/floor-screen.tsx": [
    "pixel/clock", "pixel/contract", "pixel/floor/card", "pixel/floor/view", "pixel/world/types", "translate/floor",
  ],
  "views/project/room-screen.tsx": [
    "pixel/clock", "pixel/contract", "pixel/room/stream", "pixel/room/view", "translate/room",
  ],
});

/** 整页都是画布、不在这一条范围内的页面（按登记表画元件的图鉴）。 */
const CANVAS_ONLY_PAGES = new Set(["views/pixel/gallery.tsx"]);

/** 目录下的源文件（.ts、.tsx），路径从渲染进程的源码根起算。 */
function sourcesUnder(root: string): Source[] {
  const out: Source[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir).sort()) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) {
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

/** 相对路径的导入解析成从渲染进程的源码根起的路径，去掉 .ts/.tsx；裸名称原样返回。 */
function targetOf(from: string, spec: string): string {
  if (!spec.startsWith(".")) return spec;
  return posix.normalize(posix.join(posix.dirname(from), spec)).replace(/\.tsx?$/, "");
}

/** 一个模块名（或它下面的文件）是不是名单里那一个。 */
function under(target: string, allowed: string): boolean {
  return target === allowed || target.startsWith(`${allowed}/`);
}

/** 页面的文字部分导入的画面与翻译层模块（挂画布的那几行按名单放行）。 */
function pageImportViolations(sources: Source[]): string[] {
  const out: string[] = [];
  for (const { file, text } of sources) {
    if (!file.startsWith("views/") || CANVAS_ONLY_PAGES.has(file)) continue;
    const allowed = CANVAS_MOUNTS[file] ?? [];
    for (const spec of specifiersOf(file, text)) {
      if (!spec.startsWith(".")) continue;
      const target = targetOf(file, spec);
      if (!target.startsWith("pixel/") && !target.startsWith("translate/")) continue;
      if (allowed.some((name) => under(target, name))) continue;
      out.push(`${file} 导入了 ${target}：${spec}`);
    }
  }
  return out;
}

/** 翻译层从页面取东西（一条都不许）。 */
function translateImportViolations(sources: Source[]): string[] {
  const out: string[] = [];
  for (const { file, text } of sources) {
    if (!file.startsWith("translate/")) continue;
    for (const spec of specifiersOf(file, text)) {
      if (!spec.startsWith(".")) continue;
      const target = targetOf(file, spec);
      if (target.startsWith("views/")) out.push(`${file} 导入了页面：${spec}（解析为 ${target}）`);
    }
  }
  return out;
}

const pageSources = (): Source[] => [...sourcesUnder(join(rendererRoot, "views")), ...sourcesUnder(join(rendererRoot, "translate"))];

test("页面的文字部分不导入像素画面（pixel/）与翻译层（translate/）", () => {
  assert.deepEqual(pageImportViolations(pageSources()), []);
});

test("翻译层不导入页面（views/ 下的任何文件）", () => {
  assert.deepEqual(translateImportViolations(pageSources()), []);
});

// 反向核对：把违规的样子写成样例文件，上面那几条检查必须报出来。
test("反向核对：页面的文字文件导入 pixel/ 与 translate/ 会被报出来", () => {
  const sample: Source[] = [
    {
      file: "views/project/sample-bad.tsx",
      text: [
        'import { STATUS_TEXT } from "../../pixel/room/layout.ts";',
        'import { OVERLAY_LABELS } from "../../translate/coverage.ts";',
        "export { loopRows } from \"../../translate/floor.ts\";",
        'const lazy = () => import("../../pixel/registry.ts");',
        "export const ok = 1;",
      ].join("\n"),
    },
    {
      // 挂画布的组件也不能顺手多导一个：名单里没有的模块照样报错
      file: "views/project/floor-screen.tsx",
      text: 'import { itemColor } from "../../pixel/world/floor.ts";\nimport { createFloorView } from "../../pixel/floor/view";',
    },
  ];
  const violations = pageImportViolations(sample);
  // 四条：静态导入三条、动态 import 一条；floor-screen 的 pixel/world/floor 一条
  assert.equal(violations.length, 5, violations.join("\n"));
  for (const target of ["pixel/room/layout", "translate/coverage", "translate/floor", "pixel/registry", "pixel/world/floor"]) {
    assert.ok(violations.some((v) => v.includes(target)), `没有报出 ${target}：${violations.join("\n")}`);
  }
});

test("反向核对：挂画布的名单里的模块不报错，名单外的页面导入才报错", () => {
  // 名单里写明的画布接线不报错
  assert.deepEqual(pageImportViolations([{
    file: "views/project/room-screen.tsx",
    text: [
      'import { createRafClock } from "../../pixel/clock";',
      'import { createRoomView } from "../../pixel/room/view";',
      'import * as room from "../../translate/room";',
    ].join("\n"),
  }]), []);
  // 同样的导入出现在别的页面里就报错
  const violations = pageImportViolations([{
    file: "views/project/loops-block.tsx",
    text: 'import { createRafClock } from "../../pixel/clock";',
  }]);
  assert.equal(violations.length, 1, violations.join("\n"));
  assert.match(violations[0], /pixel\/clock/);
  // 图鉴整页是画布，不在这一条范围内
  assert.deepEqual(pageImportViolations([{
    file: "views/pixel/gallery.tsx",
    text: 'import { ACTIONS } from "../../pixel/registry";',
  }]), []);
});

test("反向核对：翻译层导入页面会被报出来", () => {
  const violations = translateImportViolations([{
    file: "translate/floor.ts",
    text: [
      'import { face } from "../views/decisions/card-logic.ts";',
      'import { label } from "../views/project/labels.ts";',
      'export type { LoopRow } from "../views/project/floor-text.ts";',
      'const lazy = () => import("../views/project/labels.ts");',
    ].join("\n"),
  }]);
  assert.equal(violations.length, 4, violations.join("\n"));
  assert.ok(violations.every((v) => v.includes("translate/floor.ts")));
  // 页面自己的文件、画面合同与接口类型都不在这一条里
  assert.deepEqual(translateImportViolations([{
    file: "translate/face.ts",
    text: 'import type { DecisionView } from "../api/generated/types.gen.ts";\nimport type { DecisionFace } from "../pixel/contract.ts";',
  }]), []);
});
