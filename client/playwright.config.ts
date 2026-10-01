// Playwright 的配置：用 Electron 启动客户端（ADR-0015），连接真实运行的后端。
// 两种窗口尺寸（1440×900 与 390×844）在测试中各自设定；控制台错误必须为零（工单验收）。

import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts/,
  // Electron 应用不能在多个 worker 中并行启动同一份用户数据目录
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    trace: "retain-on-failure",
  },
});
