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
    // 开发构建的客户端连不上后端时，浏览器自己对失败的请求记一条控制台消息（跨源策略、ERR_FAILED）；
    // 那不是图鉴或像素画面自己的错误，这里只记录应用自身的错误与未捕获的异常
    const text = m.text();
    const connectionNoise = text.includes("blocked by CORS policy") || text.includes("net::ERR_FAILED");
    if (m.type() === "error" && !connectionNoise) errors.push(text);
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

// 决定板与世界里的决定卡片（工单 #179 验收标准 1）：把原型 checks/behaviors.js 第 217 至 283 行关于卡片与
// 回答的检查改写过来，在真实浏览器里用给定的数据挂载楼层画面，直接驱动卡片与点击。板与飞行的检查由 #82
// 的客户端测试覆盖，这里只覆盖卡片的点开、翻页、回答、说明必填、被拒显示与盖章收起。
// 两种窗口尺寸各跑一遍，控制台错误为零（验收标准 4）。
for (const size of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`世界里的决定卡片在 ${size.width}×${size.height} 下：点板子打开、点选项回答、需要说明不提交、被拒显示原因、盖章与翻页关闭`, async () => {
    const server = await startRendererServer();
    try {
      const { app, page } = await startDevClient(server, size);
      const errors = watchErrors(page);
      try {
        await page.goto(`${server.resolvedUrls?.local[0]}index.html#/gallery`);
        await expect(page.locator(".gallery-page")).toBeVisible();

      const result = await page.evaluate(async () => {
        const { mount } = (window as unknown as {
          __pixelFloorTest: { mount: (model: unknown, opts?: { answer?: (p: unknown) => unknown }) => Promise<{
            view: { card(): { isOpen(): boolean; openId(): string | null }; destroy(): void };
            hooks: {
              decisions(): { board: { x: number; y: number; w: number; h: number }; card: { openId: string | null; message: string | null; stamp: { id: string; text: string } | null } };
              openCard(id: string): void;
              answer(option: string): Promise<void>;
            };
            setModel(model: unknown): void;
            step(ms: number): void;
            click(x: number, y: number): void;
            answers: { decision_id: string; option: string; base_version: number; note: string }[];
            destroy(): void;
          }> };
        }).__pixelFloorTest;
        const out: Record<string, unknown> = {};
        const role = (id: string, kind: string, name: string) => ({ id, kind, name, status: "idle", task: null });
        const roles = {
          product: [role("p-mgr", "manager", "产品部门经理")],
          engineering: [role("e-mgr", "manager", "工程经理")],
          quality: [role("q-mgr", "manager", "质检经理")],
        };
        const item = { work_item_id: "w1", kind: "request", sign: "测试事项", color_index: 0, status: "running", department: "engineering", round: 1, elapsed_sec: 100, time_limit_sec: 7200, version: 1, phase: null, started_at: null, pending_question: null, run_id: "r1", adoption_id: null, recovery_state: null };
        const face = (id: string, over: Record<string, unknown> = {}) => Object.assign({
          id, kind: "model_unavailable", version: 3, title: "模型引用无法使用", work_item_id: "w1", where: "项目 · 测试事项", waited: "已等待 1 分", blocks: "不挡住事项",
          rows: [{ term: "部门", value: "工程" }], links: [],
          options: [{ id: "go", label: "继续执行", kind: "primary" }, { id: "stop", label: "停止事项", kind: "danger" }],
        }, over);
        const model = (over: Record<string, unknown> = {}) => Object.assign({
          items: [item], open_requests: [], shelves: { adopted: [] }, slots: { total: 3, used: 1 }, waiting_provider: [],
          machines: null, ops: null, interrupted: false, roles, decisions: [],
        }, over);
        const tick = async () => {
          const { promise, resolve } = Promise.withResolvers<void>();
          setTimeout(resolve, 0);
          await promise;
        };

        // 点板子打开卡片，点选项调用回答命令（带决定的版本）
        let m = await mount(model({ decisions: [face("d1")] }));
        m.step(200);
        out.closedBefore = !m.view.card().isOpen();
        const b = m.hooks.decisions().board;
        m.click(b.x + b.w / 2, b.y + b.h / 2);
        out.openedByBoard = m.view.card().isOpen() && m.view.card().openId() === "d1";
        // 卡片打开以后画一帧，章的可点击区域才被收集
        m.step(0);
        m.click(110, 270);
        await tick();
        out.answerCalled = m.answers.length === 1 && m.answers[0].decision_id === "d1" && m.answers[0].option === "go" && m.answers[0].base_version === 3;
        out.stamped = m.hooks.decisions().card.stamp;
        m.step(1500);
        out.closedAfterStamp = !m.view.card().isOpen();
        m.destroy();

        // 需要说明的选项：没写说明不提交，纸上给出提示
        m = await mount(model({ decisions: [face("d2", { options: [{ id: "revise", label: "提出修改", note_required: true }] })] }));
        m.step(200);
        m.hooks.openCard("d2");
        m.hooks.answer("revise");
        await tick();
        out.needNoteBlocked = m.answers.length === 0 && m.view.card().isOpen() && (m.hooks.decisions().card.message ?? "").includes("说明");
        m.destroy();

        // 命令被拒绝时纸上显示原因
        m = await mount(model({ decisions: [face("d4")] }), { answer: () => ({ accepted: false, message: "这个决定请求已经回答，不能再次回答" }) });
        m.step(200);
        m.hooks.openCard("d4");
        m.hooks.answer("go");
        await tick();
        out.rejectedReason = m.hooks.decisions().card.message;
        m.destroy();

        // 回答以后事件流带来的新列表里已经没有这个决定：纸留到盖章结束，说明栏的文字也留着
        m = await mount(model({ decisions: [face("d5")] }));
        m.step(200);
        m.hooks.openCard("d5");
        m.step(0);
        const noteBox = document.querySelector('textarea[aria-label="决定的说明"]') as HTMLTextAreaElement | null;
        if (!noteBox) throw new Error("卡片打开以后没有出现说明的输入框");
        noteBox.value = "照旧继续";
        noteBox.dispatchEvent(new Event("input", { bubbles: true }));
        m.hooks.answer("go");
        await tick();
        m.setModel(model({ decisions: [] }));
        m.step(300);
        out.ghostKeptPaper = m.view.card().isOpen();
        out.ghostKeptNote = noteBox.value === "照旧继续";
        m.step(1500);
        out.closedAfterGhost = !m.view.card().isOpen();
        m.destroy();

        // 翻页与关闭：点翻页翻到下一张；别处文本框里的方向键不翻页；方向键翻页；点关闭关上
        m = await mount(model({ decisions: [face("d6"), face("d7")] }));
        m.step(200);
        m.hooks.openCard("d6");
        m.step(0);
        m.click(506, 38);
        out.flipNext = m.view.card().openId() === "d7";
        const other = document.createElement("input");
        document.body.appendChild(other);
        other.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
        out.otherInputNoFlip = m.view.card().openId() === "d7";
        other.remove();
        document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
        out.keyFlip = m.view.card().openId() === "d6";
        m.step(0);
        m.click(536, 38);
        out.closeButton = !m.view.card().isOpen();
        m.destroy();

        return out;
      });

      expect(result.closedBefore).toBe(true);
      expect(result.openedByBoard).toBe(true);
      expect(result.answerCalled).toBe(true);
      expect(result.closedAfterStamp).toBe(true);
      expect(result.needNoteBlocked).toBe(true);
      expect(result.rejectedReason).toBe("这个决定请求已经回答，不能再次回答");
      expect(result.ghostKeptPaper).toBe(true);
      expect(result.ghostKeptNote).toBe(true);
      expect(result.closedAfterGhost).toBe(true);
      expect(result.flipNext).toBe(true);
      expect(result.otherInputNoFlip).toBe(true);
      expect(result.keyFlip).toBe(true);
      expect(result.closeButton).toBe(true);
      expect(errors).toEqual([]);
    } finally {
      await app.close();
    }
  } finally {
    await server.close();
  }
  });
}

