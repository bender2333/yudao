// 事项卡上「所在部门」的单元测试（工单 #842）：
// 询问被回答以后，服务端报出的部门是实际在工作的那个部门，页面照它写中文名；
// 页面上不出现英文的内部标识（服务端报出的内部标识不直接写到页面上）。
//
// 页面在渲染进程里真实挂载概览页的事项看板（overview.tsx 的 Board）：
// 用真实浏览器读回每一列的标题与卡片上的文字。

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer, type ViteDevServer } from "vite";
import { chromium, type Browser, type Page } from "@playwright/test";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

// 页面里运行的驱动：挂载真实的看板，按场景读回页面上的文字。
// 这段代码经字符串化以后在浏览器里求值，模块只能动态引入。
async function driver(): Promise<Record<string, unknown>> {
  const React = (await import(/* @vite-ignore */ "/@id/react" as string)).default as typeof import("react");
  const ReactDOMClient = (await import(/* @vite-ignore */ "/@id/react-dom/client" as string)).default as typeof import("react-dom/client");
  const { Board } = await import(/* @vite-ignore */ "/src/views/project/overview.tsx" as string) as typeof import("../../src/renderer/src/views/project/overview.tsx");

  const card = (over: Record<string, unknown>) => ({
    work_item_id: "w0",
    kind: "request",
    title: "回声工具",
    text: "",
    run_id: "run_1",
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    status: "in_progress",
    department: "engineering",
    progress: null,
    round: 4,
    stop_reason: null,
    human_action: null,
    pending_question: null,
    adoption_id: null,
    start_error: null,
    ...over,
  });

  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = ReactDOMClient.createRoot(container);
  root.render(React.createElement(Board, {
    items: [
      // 询问被回答以后，工程继续工作：服务端报出的部门是工程
      card({ work_item_id: "w1", department: "engineering" }),
      card({ work_item_id: "w2", title: "另一个事项", department: "product", round: 2 }),
      // 没有部门的事项：不写这一格
      card({ work_item_id: "w3", title: "已停止的事项", department: null, status: "stopped", stop_reason: "cancelled" }),
    ],
  }));
  await new Promise<void>((r) => setTimeout(r, 80));

  const columns: Record<string, { title: string; cards: string[] }> = {};
  for (const col of Array.from(container.querySelectorAll(".board-col"))) {
    const heading = col.querySelector("h3");
    const title = heading?.textContent ?? "";
    const cards = Array.from(col.querySelectorAll(".board-card")).map((item) => item.textContent ?? "");
    columns[title] = { title, cards };
  }
  const text = container.textContent ?? "";
  root.unmount();
  container.remove();
  return { columns, text };
}

let server: ViteDevServer | null = null;
let browser: Browser | null = null;
let page: Page | null = null;

before(async () => {
  server = await createServer({
    root: join(clientRoot, "src", "renderer"),
    // 单元测试文件之间是并行运行的：缓存目录与其他测试分开，避免同时改写同一份缓存
    cacheDir: join(clientRoot, "node_modules", ".vite-item-department"),
    plugins: [],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
    optimizeDeps: { include: ["react", "react/jsx-runtime", "react-dom/client", "pixi.js"] },
  });
  await server.listen();
  const address = server.resolvedUrls?.local[0];
  if (!address) throw new Error("渲染进程的模块服务器没有给出地址");
  browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
  page = await browser.newPage();
  await page.route(address + "overview.html", (route) => route.fulfill({
    contentType: "text/html",
    body: "<!doctype html><html><head><meta charset=\"utf-8\"></head><body></body></html>",
  }));
  await page.goto(address + "overview.html");
});

after(async () => {
  await browser?.close();
  await server?.close();
});

async function read(): Promise<{ columns: Record<string, { title: string; cards: string[] }>; text: string }> {
  if (page === null) throw new Error("页面没有打开");
  const outcome = await page.evaluate(async (input: { fnSource: string }) => {
    try {
      const fn = (0, eval)(`(${input.fnSource})`) as () => Promise<Record<string, unknown>>;
      return { ok: await fn() };
    } catch (e) {
      return { failed: String((e as Error)?.stack ?? e) };
    }
  }, { fnSource: driver.toString() });
  if ("failed" in outcome) {
    throw new Error(`驱动失败：${String(outcome.failed)}`);
  }
  return outcome.ok as { columns: Record<string, { title: string; cards: string[] }>; text: string };
}

test("事项卡按服务端报出的部门分列，卡片上写中文的部门名", async () => {
  const report = await read();
  const columns = report.columns;
  // 询问被回答以后工程在继续工作：卡片在工程列
  const engineering = columns["工程（1）"];
  assert.ok(engineering, "看板上有工程列");
  assert.equal(engineering.cards.length, 1);
  assert.match(engineering.cards[0], /工程/);
  assert.match(engineering.cards[0], /第 4 轮/);
  // 产品列里是服务端报出产品的那一张
  const product = columns["产品（1）"];
  assert.ok(product, "看板上有产品列");
  assert.match(product.cards[0], /另一个事项/);
  // 没有部门的事项在已停止列，卡片上没有部门
  const stopped = columns["已停止（1）"];
  assert.ok(stopped, "看板上有已停止列");
  assert.doesNotMatch(stopped.cards[0], /产品|工程|质检/);
});

test("页面上不出现英文的内部标识：部门写中文名", async () => {
  const report = await read();
  // 看板这一段全是中文：没有服务端内部的部门标识
  assert.doesNotMatch(report.text, /[A-Za-z]/);
});
