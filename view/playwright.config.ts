// 画面端到端测试的 Playwright 配置（工单 #1574）。
//
// 画面是系统外面的单独应用（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」的测试一节）：
// 每个 spec 自己起一个静态伺服 + 回放的装置（view/tests/e2e/fixtures.ts），不启动 Yudao。
// 装置占的是随机端口，因此串行运行，避免多个 spec 同时抢同一份构建结果与浏览器资源。

import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts/,
  // 一个 spec 一个装置：串行运行，不并行抢端口与构建结果
  workers: 1,
  fullyParallel: false,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    browserName: "chromium",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
});
