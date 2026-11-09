// 动作图鉴的回归（接替 #1418 删掉的 client/tests/e2e/pixel.spec.ts 里图鉴这一侧；工单 #1574）。
//
// 图鉴只在开发构建里（入口 #/gallery，import.meta.env.DEV），因此这个 spec 用 Vite 开发服务器打开 view/，
// 不启动 Yudao、不请求接口。核对：图鉴列出全部公开画法（62 项）、点阵预览按整数倍最近邻放大、
// 两种视口下控制台没有应用错误。旧文件里的决定卡片用例由画面单元测试守着
// （view/tests/unit/pixel-floor.test.ts 与 floor.spec.ts 的决定板），不在图鉴这一条里重复。

import { expect, test, type Page } from "@playwright/test";
import react from "@vitejs/plugin-react";
import { createServer, type ViteDevServer } from "vite";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const viewRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** 起一个画面的开发服务器（图鉴只在开发构建里）。 */
async function startGalleryServer(): Promise<ViteDevServer> {
  const server = await createServer({
    root: viewRoot,
    configFile: false,
    plugins: [react()],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    optimizeDeps: { include: ["react", "react/jsx-runtime", "react-dom/client"] },
  });
  await server.listen();
  return server;
}

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    // 开发服务器的 favicon 404 是网络噪音，不是应用错误
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

for (const size of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  test(`动作图鉴在 ${size.width}×${size.height} 下列出全部公开画法，预览按整数倍放大`, async ({ page }) => {
    const server = await startGalleryServer();
    try {
      const errors = watchErrors(page);
      await page.setViewportSize(size);
      await page.goto(`${server.resolvedUrls?.local[0] ?? ""}#/gallery`);
      await expect(page.locator(".gallery-page")).toBeVisible();
      // 图鉴列出全部 62 项公开画法（原型 v13 的 38 个函数与 24 个数据），一项不少
      await expect(page.locator(".gallery-item")).toHaveCount(62);
      await expect(page.locator(".gallery-item[data-member='drawActor']")).toBeVisible();
      await expect(page.locator(".gallery-item[data-member='paint']")).toBeVisible();
      await expect(page.locator(".gallery-item[data-member='VIGNETTES']")).toBeVisible();
      // 点阵预览按整数倍放大，采样最近邻（像素不模糊）
      const previews = await page.locator(".gallery-grid").evaluateAll((nodes) =>
        nodes.slice(0, 8).map((el) => {
          const canvas = el as HTMLCanvasElement;
          return {
            imageRendering: getComputedStyle(canvas).imageRendering,
            width: canvas.width,
            height: canvas.height,
            gridW: Number(canvas.dataset.gridW),
            gridH: Number(canvas.dataset.gridH),
          };
        }));
      expect(previews.length).toBeGreaterThan(0);
      for (const preview of previews) {
        expect(preview.imageRendering).toBe("pixelated");
        expect(preview.width % preview.gridW).toBe(0);
        expect(preview.height % preview.gridH).toBe(0);
        expect(preview.width / preview.gridW).toBeGreaterThan(1);
        expect(preview.height / preview.gridH).toBeGreaterThan(1);
      }
      expect(errors).toEqual([]);
    } finally {
      await server.close();
    }
  });
}
