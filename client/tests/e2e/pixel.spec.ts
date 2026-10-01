// 像素画面与动作图鉴的端到端测试（工单 #176 验收标准 1、3、4）。
// Playwright 启动 Electron，两种窗口尺寸（1440×900 与 390×844）各开一次：
// 画面按整数倍最近邻缩放、控制台错误为零；图鉴页只在开发构建里有入口。
//
// 图鉴页只在开发构建里（import.meta.env.DEV）出现。electron-vite build 把 NODE_ENV 固定为
// production，构建产物里图鉴分支被整体消掉，因此这里用 Vite 开发服务器提供渲染进程
// （主进程经 ELECTRON_RENDERER_URL 加载它），图鉴页在其中可见；主进程与预加载脚本用
// 已构建的产物。其余用例沿用 tests/e2e/fixtures.ts 的真实后端（FakeAdapter 驱动）。

import { expect, test } from "@playwright/test";
import { _electron as electron, type ElectronApplication, type Page } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { createServer, type ViteDevServer } from "vite";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const rendererRoot = join(repoRoot, "client", "src", "renderer");

// 渲染进程的开发服务器：与 electron-vite dev 用同一套配置，import.meta.env.DEV 为真
async function startRendererServer(): Promise<ViteDevServer> {
  const server = await createServer({
    root: rendererRoot,
    configFile: false,
    plugins: [react()],
    server: { host: "127.0.0.1", port: 0 },
    logLevel: "error",
  });
  await server.listen();
  return server;
}

// 开发构建的客户端：图鉴页在其中可见
async function startDevClient(
  server: ViteDevServer,
  size: { width: number; height: number },
): Promise<{ app: ElectronApplication; page: Page }> {
  const userData = mkdtempSync(join(tmpdir(), "yudao-pixel-"));
  const address = server.resolvedUrls?.local[0];
  if (!address) {
    throw new Error("渲染进程的开发服务器没有给出地址");
  }
  const app = await electron.launch({
    args: [join(repoRoot, "client", "out", "main", "index.js")],
    cwd: repoRoot,
    env: {
      ...process.env,
      YUDAO_E2E_USER_DATA: userData,
      YUDAO_E2E_WIDTH: String(size.width),
      YUDAO_E2E_HEIGHT: String(size.height),
      ELECTRON_RENDERER_URL: address,
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
    const server = await startRendererServer();
    try {
      const { app, page } = await startDevClient(server, size);
      const errors = watchErrors(page);
      try {
        await page.goto(`${server.resolvedUrls?.local[0]}index.html#/gallery`);
        await expect(page.locator(".gallery-page")).toBeVisible();
        // 图鉴列出全部 64 项公开画法，一项不少
        await expect(page.locator(".gallery-item")).toHaveCount(64);
        await expect(page.locator(".gallery-item[data-member='drawActor']")).toBeVisible();
        await expect(page.locator(".gallery-item[data-member='paint']")).toBeVisible();
        await expect(page.locator(".gallery-item[data-member='VIGNETTES']")).toBeVisible();
        // 点阵预览按整数倍放大，采样最近邻（像素不模糊）。
        // 各项的取样点阵尺寸不同（小人帧 32×40、矩形 48×24 等），画布元素上带着各自的逻辑尺寸，
        // 据此逐项核对画布宽高是逻辑尺寸的整数倍，且倍数大于 1。
        const previews = await page.locator(".gallery-grid").evaluateAll((nodes) =>
          nodes.slice(0, 8).map((el) => {
            const c = el as HTMLCanvasElement;
            return {
              imageRendering: getComputedStyle(c).imageRendering,
              width: c.width,
              height: c.height,
              gridW: Number(c.dataset.gridW),
              gridH: Number(c.dataset.gridH),
            };
          }),
        );
        expect(previews.length).toBeGreaterThan(0);
        for (const p of previews) {
          expect(p.imageRendering).toBe("pixelated");
          expect(p.width % p.gridW).toBe(0);
          expect(p.height % p.gridH).toBe(0);
          expect(p.width / p.gridW).toBeGreaterThan(1);
          expect(p.height / p.gridH).toBeGreaterThan(1);
        }
        expect(errors).toEqual([]);
      } finally {
        await app.close();
      }
    } finally {
      await server.close();
    }
  });
}

test("像素画面按容器宽度取整数倍缩放，缓冲区是逻辑尺寸的整数倍", async () => {
  const server = await startRendererServer();
  try {
    const { app, page } = await startDevClient(server, { width: 390, height: 844 });
    const errors = watchErrors(page);
    try {
      await page.goto(`${server.resolvedUrls?.local[0]}index.html#/gallery`);
      await expect(page.locator(".gallery-page")).toBeVisible();
      // 页面里点阵预览的画布宽高都是各自逻辑尺寸的整数倍
      const sizes = await page.locator(".gallery-grid").evaluateAll((nodes) =>
        nodes.slice(0, 8).map((el) => {
          const c = el as HTMLCanvasElement;
          return { w: c.width, h: c.height, gridW: Number(c.dataset.gridW), gridH: Number(c.dataset.gridH) };
        }),
      );
      expect(sizes.length).toBeGreaterThan(0);
      for (const s of sizes) {
        expect(s.w % s.gridW).toBe(0);
        expect(s.h % s.gridH).toBe(0);
        expect(s.w / s.gridW).toBeGreaterThan(1);
        expect(s.h / s.gridH).toBeGreaterThan(1);
      }
      expect(errors).toEqual([]);
    } finally {
      await app.close();
    }
  } finally {
    await server.close();
  }
});

test("正式的页面入口里没有图鉴：页签与侧栏都取不到它", async () => {
  const server = await startRendererServer();
  try {
    const { app, page } = await startDevClient(server, { width: 1440, height: 900 });
    const errors = watchErrors(page);
    try {
      // 图鉴只在开发时可用；正式入口（页签）里没有它的链接
      const text = await page.locator("body").innerText();
      expect(text.includes("#/gallery")).toBe(false);
      expect(errors).toEqual([]);
    } finally {
      await app.close();
    }
  } finally {
    await server.close();
  }
});
