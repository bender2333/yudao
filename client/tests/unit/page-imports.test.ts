// 页面与画面的导入方向（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」的测试一节、
// docs/design/test-pyramid.md「前端与浏览器测试」；工单 #1415、#1418）。
//
// 画面搬进 view/ 以后两边各自构建、各自测试，互不导入：这一条核对 client/ 里没有一个文件导入 view/，
// 画面那一侧的另一半是 view/tests/unit/view-imports.test.ts（画面不导入 client/ 与 harness/）。
// 原来按文件逐条列出的挂画布例外名单随画布搬出清空：页面上不再挂画布。
//
// 测试按文件的导入语句逐个核对（用 TypeScript 的语法树取 import/export from 与动态 import，注释与字符串不参与）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, posix, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const here = dirname(fileURLToPath(import.meta.url));
/** 客户端目录的根：client/。 */
const clientRoot = resolve(here, "..", "..");

/** 一份源码：路径从 client/ 起用 / 分隔写，文本是文件内容。 */
interface Source {
  file: string;
  text: string;
}

/** 目录下的源文件（.ts、.tsx、.js、.mjs），路径从 client/ 起算。 */
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
      out.push({ file: relative(clientRoot, full).split(sep).join("/"), text: readFileSync(full, "utf8") });
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

/** 相对路径的导入解析成从 client/ 起的路径；裸名称原样返回（不以点开头）。 */
function targetOf(from: string, spec: string): string {
  if (!spec.startsWith(".")) return spec;
  return posix.normalize(posix.join(posix.dirname(from), spec));
}

/** client/ 里导入了画面的文件（view/）。 */
function viewImportViolations(sources: Source[]): string[] {
  const out: string[] = [];
  for (const { file, text } of sources) {
    for (const spec of specifiersOf(file, text)) {
      const target = targetOf(file, spec);
      if (target === "view" || target.startsWith("view/") || target.startsWith("../view/")) {
        out.push(`${file} 导入了画面：${spec}（解析为 ${target}）`);
      }
    }
  }
  return out;
}

const realSources = (): Source[] => [...sourcesUnder(join(clientRoot, "src")), ...sourcesUnder(join(clientRoot, "tests"))];

test("页面与客户端测试不导入画面（view/）", () => {
  assert.deepEqual(viewImportViolations(realSources()), []);
});

// 反向核对：把违规的样子写成样例文件，上面那条检查必须报出来。
test("反向核对：导入 view/ 的样例文件会被报出来", () => {
  const violations = viewImportViolations([{
    file: "src/renderer/src/views/sample-bad.tsx",
    text: [
      'import { GalleryPage } from "../../../../../view/src/gallery.tsx";',
      'export { floorActions } from "../../../../../view/src/translate/floor.ts";',
      "const lazy = () => import(\"../../../../../view/src/pixel/floor/view.ts\");",
      "export const ok = 1;",
    ].join("\n"),
  }]);
  assert.equal(violations.length, 3, violations.join("\n"));
  assert.ok(violations.every((v) => v.includes("view/")), violations.join("\n"));
  // 页面自己的文件、接口类型与页面文字不报错
  assert.deepEqual(viewImportViolations([{
    file: "src/renderer/src/views/project/sample-ok.ts",
    text: 'import type { ProjectLoopResult } from "../../api/generated/types.gen.ts";\nimport { amountText } from "./floor-text.ts";',
  }]), []);
});
