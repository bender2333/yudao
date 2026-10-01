// 接口类型的生成：从仓库中的 OpenAPI 快照生成 TypeScript 类型与调用函数，
// 并把这份快照的接口版本写入 src/renderer/src/api/interface-version.ts。
// 客户端在连接时读取能力清单的 deployment.api_version，与这里记录的版本不同时只显示更新页
// （应用层与接口层设计说明第 6.1 节）。快照与后端由 harness/tests/test_openapi_snapshot.py 核对一致。

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = join(here, "..");
const repoRoot = join(clientRoot, "..");

// 生成类型所用的 OpenAPI 快照：接口层的快照，由后端的快照测试保持在合同变化时更新
const snapshot = join(repoRoot, "harness", "tests", "openapi", "openapi.json");
const document = JSON.parse(readFileSync(snapshot, "utf8"));
const field = document?.components?.schemas?.Deployment?.properties?.api_version;
if (!field || field.type !== "integer" || typeof field.example !== "number") {
  throw new Error("OpenAPI 快照的 Deployment 缺少带 example 的整数 api_version，无法确定接口版本");
}
const apiVersion = field.example;

const output = join(clientRoot, "src", "renderer", "src", "api", "generated");
mkdirSync(dirname(output), { recursive: true });
// 用本地安装的 openapi-ts 可执行文件，Windows 上是 .cmd，直接执行会失败，交给外壳执行
const bin = join(clientRoot, "node_modules", ".bin", "openapi-ts");
execFileSync(bin, ["-i", snapshot, "-o", output], { cwd: clientRoot, stdio: "inherit", shell: true });

// 记录生成类型所用的接口版本：interface-version.ts 与生成的类型一起提交，客户端与它的构建一致
const versionFile = join(clientRoot, "src", "renderer", "src", "api", "interface-version.ts");
const body = `// 由 scripts/generate-api.mjs 生成，不要手工修改。
// 生成这份接口类型时后端能力清单的 deployment.api_version。
export const CLIENT_API_VERSION = ${apiVersion};
`;
writeFileSync(versionFile, body, "utf8");
console.log(`接口类型生成完成，接口版本 ${apiVersion}`);
