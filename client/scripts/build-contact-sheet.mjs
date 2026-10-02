// 动作图鉴联系表（工单 #176 验收标准 1）：把全部公开画法渲染成一张对照图，交给用户查看画风。
// 用 Playwright 的 Chromium 加载客户端的图鉴页（开发构建），逐项截取预览，拼成一张大图。
// 原型侧的对应画法用原型自带的图鉴页（docs/prototypes/v9/index.html#/gallery）截取，两列并排。
//
// 用法：node scripts/build-contact-sheet.mjs [输出目录]
// 依赖：@playwright/test 自带的 Chromium（npx playwright install chromium）。

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium } from "@playwright/test";
import { GALLERY_MEMBERS } from "../src/renderer/src/pixel/gallery-data.ts";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");
const repoRoot = resolve(clientRoot, "..");
const outDir = resolve(process.argv[2] ?? join(clientRoot, ".tmp", "contact-sheet"));
mkdirSync(outDir, { recursive: true });

const COLUMNS = 8;
const CELL = 132;
const PAD = 8;
const HEADER = 34;

// 允许用 CHROMIUM_EXE 指定浏览器可执行文件（本机 Playwright 版本与已装 Chromium 不一致时用）
// 图鉴只在开发构建里出现，所以这里用 Vite 的开发服务打开渲染页面（DEV 为真）
const server = await createServer({ root: join(clientRoot, "src", "renderer"), server: { host: "127.0.0.1", port: 0, strictPort: false }, logLevel: "error", appType: "spa" });
await server.listen();
const address = server.httpServer.address();
const port = typeof address === "object" && address ? address.port : 0;

const browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
try {
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const galleryUrl = `http://127.0.0.1:${port}/index.html#/gallery`;
  await page.goto(galleryUrl);
  await page.waitForSelector(".gallery-item");
  // 等像素字体就位，联系表里的中文才不会缺字
  await page.evaluate(async () => {
    await document.fonts.load("10px 'Fusion Pixel 10px Proportional SC'");
    await document.fonts.ready;
  });

  // 逐项截取客户端画法的预览
  const shots = [];
  for (const m of GALLERY_MEMBERS) {
    const item = page.locator(`.gallery-item[data-member="${m.name}"]`);
    const shot = (await item.count()) > 0 ? await item.screenshot() : null;
    shots.push({ name: m.name, note: m.note, png: shot });
  }

  // 拼一张联系表：每一项一格，标题是画法名，格子是它的预览
  const rows = Math.ceil(shots.length / COLUMNS);
  const width = COLUMNS * CELL + PAD * 2;
  const height = rows * CELL + HEADER + PAD * 2;
  const sheetPage = await browser.newPage({ viewport: { width, height } });
  await sheetPage.setContent(`
    <html><body style="margin:0;background:#14161e;color:#e8e6f0;font:11px/1.3 'Fusion Pixel 10px Proportional SC',sans-serif">
    <div style="padding:8px 8px 0"><b>动作图鉴 · 联系表</b> · 共 ${shots.length} 项公开画法（原型 sprites.js 与 engine.js）</div>
    <div style="display:grid;grid-template-columns:repeat(${COLUMNS},${CELL}px);gap:0;padding:8px">
      ${shots
        .map(
          (s) => `<div style="width:${CELL - 6}px;height:${CELL - 6}px;border:1px solid #ffffff22;padding:3px;overflow:hidden">
            <div style="font-size:10px;color:#ffd66b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${s.name}</div>
            ${s.png ? `<img src="data:image/png;base64,${s.png.toString("base64")}" style="max-width:100%;max-height:${CELL - 30}px;image-rendering:pixelated" />` : ""}
          </div>`,
        )
        .join("")}
    </div></body></html>`);
  const sheetPath = join(outDir, "contact-sheet.png");
  await sheetPage.screenshot({ path: sheetPath, fullPage: true });
  await sheetPage.close();

  // 顺带把每一项的预览单独落盘，便于逐项核对
  const itemsDir = join(outDir, "items");
  mkdirSync(itemsDir, { recursive: true });
  const index = [];
  for (const s of shots) {
    if (!s.png) continue;
    const file = join(itemsDir, `${s.name}.png`);
    writeFileSync(file, s.png);
    index.push({ name: s.name, note: s.note, file });
  }
  writeFileSync(join(outDir, "index.json"), JSON.stringify({ sheet: sheetPath, items: index }, null, 1));
  console.log(`联系表已生成：${sheetPath}（${shots.length} 项，其中 ${index.length} 项有像素预览）`);
} finally {
  await browser.close();
  await server.close();
}
