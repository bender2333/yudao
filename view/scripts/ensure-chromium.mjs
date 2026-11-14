// 画面单元测试的浏览器准备（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」）：
// pixel-floor.test.ts 与 pixel-honesty.test.ts 需要启动 Chromium 画布渲染 PixiJS。
// 指定了存在的 CHROMIUM_EXE 或 Playwright 管理的 Chromium 已就绪时直接退出；
// 缺少浏览器可执行文件时调用本地安装的 @playwright/test 安装 Chromium。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const customExecutable = process.env.CHROMIUM_EXE;
if (customExecutable && existsSync(customExecutable)) {
  process.exit(0);
}
if (existsSync(chromium.executablePath())) {
  process.exit(0);
}

const here = dirname(fileURLToPath(import.meta.url));
const viewRoot = join(here, "..");
const cli = fileURLToPath(import.meta.resolve("@playwright/test/cli"));
execFileSync(process.execPath, [cli, "install", "chromium"], { cwd: viewRoot, stdio: "inherit" });
