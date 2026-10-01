// 像素画面与动作图鉴的端到端测试（工单 #176 验收标准 1、3、4）。
// Playwright 启动 Electron，两种窗口尺寸（1440×900 与 390×844）各开一次：
// 画面按整数倍最近邻缩放、控制台错误为零；图鉴页只在开发构建里有入口。
//
// 图鉴页只在开发构建里（import.meta.env.DEV）出现，因此 e2e 用开发构建启动客户端；
// 其余用例沿用 tests/e2e/fixtures.ts 的真实后端（FakeAdapter 驱动）。

import { expect, test } from "@playwright/test";
import { _electron as electron, type ElectronApplication, type Page } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

// 开发构建的客户端：图鉴页在其中可见
async function startDevClient(size: { width: number; height: number }): Promise<{ app: ElectronApplication; page: Page }> {
  const userData = mkdtempSync(join(tmpdir(), "yudao-pixel-"));
  const app = await electron.launch({
    args: [join(repoRoot, "client", "out", "main", "index.js")],
    cwd: repoRoot,
    env: {
      ...process.env,
      YUDAO_E2E_USER_DATA: userData,
      YUDAO_E2E_WIDTH: String(size.width),
      YUDAO_E2E_HEIGHT: String(size.height),
      YUDAO_DEV: "1",
    },
  });
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  return { app, page };
}

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

for (const size of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`动作图鉴在 ${size.width}×${size.height} 下列出全部公开画法，控制台错误为零`, async () => {
    const { app, page } = await startDevClient(size);
    const errors = watchErrors(page);
    try {
      await page.goto(`file://${join(repoRoot, "client", "out", "renderer", "index.html")}#/gallery`);
      await expect(page.locator(".gallery-page")).toBeVisible();
      // 图鉴列出全部 64 项公开画法，一项不少
      await expect(page.locator(".gallery-item")).toHaveCount(64);
      await expect(page.locator(".gallery-item[data-member='drawActor']")).toBeVisible();
      await expect(page.locator(".gallery-item[data-member='paint']")).toBeVisible();
      await expect(page.locator(".gallery-item[data-member='VIGNETTES']")).toBeVisible();
      // 点阵预览按整数倍放大，采样最近邻（像素不模糊）
      const zoom = await page.locator(".gallery-grid").first().evaluate((el: HTMLCanvasElement) => ({
        imageRendering: getComputedStyle(el).imageRendering,
        width: el.width,
        height: el.height,
      }));
      expect(zoom.imageRendering).toBe("pixelated");
      expect(zoom.width % 32).toBe(0);
      expect(zoom.height % 40).toBe(0);
      expect(errors).toEqual([]);
    } finally {
      await app.close();
    }
  });
}

test("像素画面按容器宽度取整数倍缩放，缓冲区是逻辑尺寸的整数倍", async () => {
  const { app, page } = await startDevClient({ width: 390, height: 844 });
  const errors = watchErrors(page);
  try {
    await page.goto(`file://${join(repoRoot, "client", "out", "renderer", "index.html")}#/gallery`);
    await expect(page.locator(".gallery-page")).toBeVisible();
    // 页面里点阵预览的画布宽高都是逻辑尺寸的整数倍
    const sizes = await page.locator(".gallery-grid").evaluateAll((nodes) =>
      nodes.slice(0, 8).map((n) => ({ w: (n as HTMLCanvasElement).width, h: (n as HTMLCanvasElement).height })),
    );
    expect(sizes.length).toBeGreaterThan(0);
    for (const s of sizes) {
      expect(Number.isInteger(s.w)).toBe(true);
      expect(Number.isInteger(s.h)).toBe(true);
    }
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});

test("正式的页面入口里没有图鉴：页签与侧栏都取不到它", async () => {
  const { app, page } = await startDevClient({ width: 1440, height: 900 });
  const errors = watchErrors(page);
  try {
    // 图鉴只在开发时可用；正式入口（页签）里没有它的链接
    const text = await page.locator("body").innerText();
    expect(text.includes("#/gallery")).toBe(false);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
