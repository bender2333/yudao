// 页面与服务同出一个发布（工单 #374，网页界面的提供与发布设计说明第 5.1 节）：
// 页面每次连接读取能力清单里的服务版本，与页面构建时的版本不同时自动重新加载。
// 用例用真实的 Playwright Chromium 与真实的后端：服务第一次被读取能力清单时报告一个与页面构建时
// 不同的发布版本，页面重新加载以后读到服务自己的版本（重新加载一次即可观察，不会反复重新加载）；
// 服务一直报告同一个版本时页面不重新加载。
// 页面构建时的版本取自 client/package.json，与 Vite 构建页面时写入 import.meta.env.VITE_YUDAO_RELEASE
// 的是同一处（client/vite.pages.config.ts）。

import { chromium, expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { startBackend, type Backend } from "./fixtures";

const clientRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const packageJson = JSON.parse(readFileSync(join(clientRoot, "package.json"), "utf8")) as { version: string };
const PAGE_RELEASE = packageJson.version;
// 浏览器里上一次发布的入口页面文件：构建产物原样给出（引用同样的脚本与样式），
// 页面重新加载以后换成后端现在提供的这一个
const STALE_ENTRY = readFileSync(join(clientRoot, "out", "renderer", "index.html"));

test("服务报告的发布版本与页面不同时，页面重新加载并取到服务现在的入口页面文件", async () => {
  test.setTimeout(300_000);
  // 升级以后服务重启的情形：页面打开时读到的是一个与自身不同的发布版本，
  // 重新加载以后取到服务现在提供的入口页面文件，并进入外壳
  const backend: Backend = await startBackend({ releaseVersionOnce: `${PAGE_RELEASE}-upgrade` });
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    // 第一次给出上一次发布的入口页面文件，其余放行到后端：页面重新加载以后换到后端现在提供的这一个
    let served = 0;
    await context.route(`${backend.address}/`, async (route) => {
      served += 1;
      if (served === 1) {
        await route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: STALE_ENTRY });
        return;
      }
      await route.continue();
    });
    const page = await context.newPage();
    const pageerrors: string[] = [];
    page.on("pageerror", (error) => pageerrors.push(error.message));
    await page.goto(`${backend.address}/`);
    await page.waitForLoadState("domcontentloaded");
    await expect(page.locator(".brand .y9-brand-name")).toContainText("Yudao", { timeout: 60_000 });
    // 入口页面文件被取过两次：页面读到不同的服务版本以后重新加载了一次
    expect(served).toBe(2);
    expect(pageerrors).toEqual([]);
  } finally {
    await browser.close();
    await backend.stop();
  }
});

test("服务报告同一个发布版本：页面不重新加载", async () => {
  test.setTimeout(300_000);
  const backend: Backend = await startBackend({ releaseVersion: PAGE_RELEASE });
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    // 每次取入口页面文件与能力清单都记一次：自动重新加载会再取一次入口页面文件
    let documents = 0;
    let capabilityReads = 0;
    await context.route(`${backend.address}/`, async (route) => {
      documents += 1;
      await route.continue();
    });
    await context.route(`${backend.address}/api/capabilities`, async (route) => {
      capabilityReads += 1;
      await route.continue();
    });
    const page = await context.newPage();
    await page.goto(`${backend.address}/`);
    await expect(page.locator(".brand .y9-brand-name")).toContainText("Yudao", { timeout: 60_000 });
    await page.waitForTimeout(15_000);
    // 入口页面文件只取过一次：版本相同时不重新加载
    expect(documents).toBe(1);
    expect(capabilityReads).toBeGreaterThanOrEqual(1);
  } finally {
    await browser.close();
    await backend.stop();
  }
});
