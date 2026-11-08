// Playwright 的配置：用 Chromium 打开后端提供的页面（client/out/renderer，由 npm run build:pages 构建），
// 连接真实运行的后端。两种视口尺寸（1440×900 与 1920×1080）在测试中各自设定；控制台错误必须为零（工单验收）。

import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts/,
  // 每个测试文件各自启动真实后端并占用端口、数据目录，串行运行避免互相干扰
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    browserName: "chromium",
    trace: "retain-on-failure",
  },
});
