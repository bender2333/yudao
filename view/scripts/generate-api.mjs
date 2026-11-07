// 画面的接口类型生成（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」）：
// 从仓库中的 OpenAPI 快照生成画面自己的 TypeScript 类型与调用函数，并把这份快照的接口版本写进
// src/api/interface-version.ts。画面不导入 client/ 的任何文件，接口描述改了而类型没重新生成时
// 画面的作业失败（.github/workflows/ci.yml 的画面作业）。
//
// 快照与后端由 harness/tests/test_openapi_snapshot.py 核对一致：画面读的是同一份接口描述。

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const viewRoot = join(here, "..");
const repoRoot = join(viewRoot, "..");

// 生成类型所用的 OpenAPI 快照：接口层的快照，由后端的快照测试保持在合同变化时更新
const snapshot = join(repoRoot, "harness", "tests", "openapi", "openapi.json");
const document = JSON.parse(readFileSync(snapshot, "utf8"));
const field = document?.components?.schemas?.Deployment?.properties?.api_version;
if (!field || field.type !== "integer" || typeof field.example !== "number") {
  throw new Error("OpenAPI 快照的 Deployment 缺少带 example 的整数 api_version，无法确定接口版本");
}
const apiVersion = field.example;

const output = join(viewRoot, "src", "api", "generated");
mkdirSync(dirname(output), { recursive: true });
// 用本地安装的 openapi-ts 可执行文件，Windows 上是 .cmd，直接执行会失败，交给外壳执行
const bin = join(viewRoot, "node_modules", ".bin", "openapi-ts");
execFileSync(bin, ["-i", snapshot, "-o", output], { cwd: viewRoot, stdio: "inherit", shell: true });

// 记录生成类型所用的接口版本：interface-version.ts 与生成的类型一起提交，画面与它的构建一致
const versionFile = join(viewRoot, "src", "api", "interface-version.ts");
const body = `// 由 scripts/generate-api.mjs 生成，不要手工修改。
// 生成这份接口类型时后端能力清单的 deployment.api_version。
export const VIEW_API_VERSION = ${apiVersion};
`;
writeFileSync(versionFile, body, "utf8");
console.log(`接口类型生成完成，接口版本 ${apiVersion}`);
