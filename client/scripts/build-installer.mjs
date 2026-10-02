// 客户端安装包的构建（设计说明第 3.3、7 节，工单 #208）。
//
// 生成 NSIS 按用户安装包 Yudao-Setup-<版本>.exe、差分下载用的 .blockmap 与更新清单 latest.yml
// （electron-builder 26 系列的 NSIS 目标自带）。
//
// 参数都可以用环境变量改写，测试构建因此使用不同的 appId、产品名与安装目录，不影响用户已经安装的那一份：
//   YUDAO_APP_ID         应用标识（默认 com.yudao.client）
//   YUDAO_PRODUCT_NAME   产品名与安装目录名（默认 Yudao）
//   YUDAO_SETUP_BASENAME 安装包文件名前缀（默认 Yudao-Setup）
//   YUDAO_OUTPUT_DIR     electron-builder 的输出目录（默认 dist）
//   YUDAO_PUBLISH_URL    更新地址（写进 app-update.yml，客户端更新时读取）
//   YUDAO_VERSION        发布版本号的覆盖（默认取 package.json；测试构建用它做出版本 1 与版本 2）
//   YUDAO_API_VERSION    客户端记录的接口版本的覆盖（默认取 src/renderer/src/api/interface-version.ts；
//                        测试构建用它做出一个比服务低的接口版本，核对更新页）
//
// 构建以后打印一行 JSON，写明安装包、blockmap 与 latest.yml 的位置，供发布脚本与测试读取。
// 非管理员、没有开发者模式的账户下可以运行（NSIS 按用户安装，不需要管理员权限）。

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const clientRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

const appId = process.env.YUDAO_APP_ID ?? "com.yudao.client";
const productName = process.env.YUDAO_PRODUCT_NAME ?? "Yudao";
const setupBasename = process.env.YUDAO_SETUP_BASENAME ?? "Yudao-Setup";
const outputDir = resolve(clientRoot, process.env.YUDAO_OUTPUT_DIR ?? "dist");
const publishUrl = process.env.YUDAO_PUBLISH_URL ?? "";
const apiVersionOverride = process.env.YUDAO_API_VERSION;

const packageVersion = JSON.parse(readFileSync(join(clientRoot, "package.json"), "utf8")).version;
const version = process.env.YUDAO_VERSION ?? packageVersion;
if (typeof version !== "string" || version.length === 0) {
  throw new Error("package.json 缺少版本号，YUDAO_VERSION 也没有给出");
}

// 接口版本的覆盖：改写客户端记录的接口版本，构建完成以后按原内容还原。
// 只有测试构建会用到（服务报告的接口版本与客户端构建时的版本不同时显示更新页）
const versionFile = join(clientRoot, "src", "renderer", "src", "api", "interface-version.ts");
const versionFileBefore = readFileSync(versionFile, "utf8");
if (apiVersionOverride !== undefined) {
  writeFileSync(versionFile,
    versionFileBefore.replace(/CLIENT_API_VERSION = \d+/, `CLIENT_API_VERSION = ${apiVersionOverride}`), "utf8");
}
const restoreVersionFile = () => writeFileSync(versionFile, versionFileBefore, "utf8");

try {
  // electron-vite 构建主进程、预加载与渲染进程到 out/，electron-builder 再把它打成安装包
  execFileSync("npm", ["run", "build"], { cwd: clientRoot, stdio: "inherit", shell: true });

  const args = ["--win", "nsis", "--x64", "--config", "electron-builder.config.mjs", "--publish", "never",
                `--config.extraMetadata.version=${version}`,
                // 产品名写进打包内的 package.json：app.getName() 与用户数据目录按它取值，
                // 测试构建与用户安装的那一份因此用不同的目录（工单验收第 7 项）
                `--config.extraMetadata.productName=${productName}`];
  if (publishUrl.length > 0) {
    args.push(`--config.publish.url=${publishUrl}`);
  }
  execFileSync(join(clientRoot, "node_modules", ".bin", "electron-builder"), args, {
    cwd: clientRoot,
    stdio: "inherit",
    shell: true,
    env: { ...process.env, YUDAO_APP_ID: appId, YUDAO_PRODUCT_NAME: productName,
           YUDAO_SETUP_BASENAME: setupBasename, YUDAO_OUTPUT_DIR: outputDir },
  });
} finally {
  restoreVersionFile();
}

const setup = join(outputDir, `${setupBasename}-${version}.exe`);
const blockmap = `${setup}.blockmap`;
const manifest = join(outputDir, "latest.yml");
for (const path of [setup, blockmap, manifest]) {
  if (!existsSync(path)) {
    throw new Error(`构建没有生成 ${path}`);
  }
}
console.log(JSON.stringify({ version, setup, blockmap, manifest, appId, productName }));
