// 画面的导入方向（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」的测试一节、
// docs/design/test-pyramid.md「前端与浏览器测试」；工单 #1418）：
//
// 画面是系统外面的单独应用：它的源码、测试与夹具都在 view/ 里，一个文件都不导入 client/ 与 harness/，
// 也不导入 view/ 以外的相对路径。接口的描述与类型是画面自己从 OpenAPI 快照生成的一份（src/api/generated/）。
// 页面那一侧的另一半在同一次改动里：client/tests/unit/page-imports.test.ts 核对 client/ 不导入 view/。
//
// 测试按文件的导入语句逐个核对（用 TypeScript 的语法树取 import/export from 与动态 import，注释与字符串不参与）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, posix, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const here = dirname(fileURLToPath(import.meta.url));
/** 画面的根：view/。 */
const viewRoot = resolve(here, "..", "..");

/** 一份源码：路径从 view/ 起用 / 分隔写，文本是文件内容。 */
interface Source {
  file: string;
  text: string;
}

/** 目录下的源文件（.ts、.tsx、.js、.mjs），路径从 view/ 起算。 */
function sourcesUnder(root: string): Source[] {
  const out: Source[] = [];
  if (!statSync(root, { throwIfNoEntry: false })) return out;
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir).sort()) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) {
        if (name === "node_modules" || name === "out") continue;
        walk(full);
        continue;
      }
      if (!/\.(tsx?|mjs|js)$/.test(name)) continue;
      out.push({ file: relative(viewRoot, full).split(sep).join("/"), text: readFileSync(full, "utf8") });
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

/** 相对路径的导入解析成从 view/ 起的路径；裸名称原样返回（不以点开头）。 */
function targetOf(from: string, spec: string): string {
  if (!spec.startsWith(".")) return spec;
  return posix.normalize(posix.join(posix.dirname(from), spec));
}

/** 画面里导入了 view/ 以外的东西：client/、harness/、越出 view/ 的相对路径。 */
function outsideViolations(sources: Source[]): string[] {
  const out: string[] = [];
  for (const { file, text } of sources) {
    for (const spec of specifiersOf(file, text)) {
      if (spec.startsWith("client/") || spec.startsWith("harness/")) {
        out.push(`${file} 导入了 ${spec}`);
        continue;
      }
      if (!spec.startsWith(".")) continue;
      const target = targetOf(file, spec);
      if (target.startsWith("..") || target.startsWith("client/") || target.startsWith("harness/")) {
        out.push(`${file} 导入了 view/ 以外的文件：${spec}（解析为 ${target}）`);
      }
    }
  }
  return out;
}

const realSources = (): Source[] => [...sourcesUnder(join(viewRoot, "src")), ...sourcesUnder(join(viewRoot, "tests"))];

test("画面不导入 client/ 与 harness/，也不导入 view/ 以外的相对路径", () => {
  assert.deepEqual(outsideViolations(realSources()), []);
});

// 反向核对：把违规的样子写成样例文件，上面那条检查必须报出来。
test("反向核对：导入 client/、harness/ 与 view/ 以外文件的样例都会被报出来", () => {
  const violations = outsideViolations([{
    file: "src/sample-bad.ts",
    text: [
      'import { ClientApp } from "../../client/src/renderer/src/contract/client-app.ts";',
      'import { EVENT_TYPES } from "harness/app/contracts.ts";',
      'export { floorActions } from "../client/src/renderer/src/translate/floor.ts";',
      "const lazy = () => import(\"../harness/app/contracts.ts\");",
      "export const ok = 1;",
    ].join("\n"),
  }]);
  // 四条：相对路径两条越出 view/、裸名称两条指向 client/ 与 harness/
  assert.equal(violations.length, 4, violations.join("\n"));
  for (const zone of ["client/", "harness/"]) {
    assert.ok(violations.some((v) => v.includes(zone)), `没有报出 ${zone}：${violations.join("\n")}`);
  }
  // 画面自己的文件与三张声明表不报错
  assert.deepEqual(outsideViolations([{
    file: "src/pixel/timeline.ts",
    text: 'import type { PixelAction } from "./contract.ts";\nimport { createScene } from "./world/scene.ts";',
  }]), []);
});
