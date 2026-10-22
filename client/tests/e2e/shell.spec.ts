// 页面外壳的端到端测试（工单 #79 的验收）：Playwright 打开 Chromium 页面，连接真实运行的后端
// （FakeAdapter 驱动的服务，见 tests/e2e/backend.py）。视口尺寸 1440×900 与 1920×1080，控制台错误为零。

import { expect, test } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";
import { CLIENT_API_VERSION } from "../../src/renderer/src/api/interface-version";

let backend: Backend;

// 启动后端（FakeAdapter 驱动的服务）到首行输出的用时由后端的 git 子进程决定：本机空闲时 18 至 25 秒，
// 并发负载下 60 至 75 秒（#214）。这个界限只用来防止后端不输出时一直等待，按 #107 的裁定
// （docs/architecture-issues.md，架构师 2026-09-27 16:55）设为远大于正常用时的值。Playwright 的
// beforeAll 默认沿用配置里的测试时限（client/playwright.config.ts 的 60 秒），在这里单独放宽这一个会合点，
// 各条测试自己的时限不变。
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

async function openClient(size: { width: number; height: number }): Promise<ClientApp> {
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  return client;
}

// 控制台错误：在每个用例里收集，结束时核对为零
function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test("页面打开以后直接读取能力清单并进入外壳", async () => {
  // 网页里没有连接设置：页面从自己来源的服务读取能力清单；两种视口各核对一次
  // （首条验收：能力清单可读、外壳打开）
  for (const size of [
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ]) {
    const client = await openClient(size);
    const errors = watchErrors(client);
    try {
      await expect(client.page.locator(".sidebar")).toBeVisible();
      await expect(client.page.locator("text=页面与服务的接口版本不同")).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  }
});

test("页面连接以后直接显示状态项与离开期间的报告", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    await expect(client.page.locator(".connection")).toHaveText("已连接");
    // 首页已经由 #175 实现：外壳连上以后直接显示状态项与离开期间的报告，不再是占位页
    await expect(client.page.locator(".status-row .status-item")).not.toHaveCount(0);
    await expect(client.page.getByRole("heading", { name: "离开期间的报告", exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("能力清单缺少某个查询时，依赖它的页面入口不出现", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    // 当前部署的注册表没有 machines.list、tools.registry 等查询
    await expect(client.page.getByRole("button", { name: "机器" })).toHaveCount(0);
    await expect(client.page.getByRole("button", { name: "工具与扩展" })).toHaveCount(0);
    // 执行槽位这一页的数据来自 system.status（工单 #727），所以它的入口在
    await expect(client.page.getByRole("button", { name: "运行与执行槽位" })).toHaveCount(1);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("顶栏的待你决定数量与 decisions.list 中等待回答的数量一致", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const waiting = await client.page.evaluate(async (address: string) => {
      const result = await fetch(`${address}/api/queries/decisions.list?status=open`);
      const body = (await result.json()) as { data: { decisions: unknown[] } };
      return body.data.decisions.length;
    }, backend.address);
    expect(waiting).toBeGreaterThan(0);
    await expect(client.page.locator(".topbar .status-item").filter({ hasText: "待你决定：" })).toHaveText(`待你决定：${waiting}`);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});


test("事件流驱动视图刷新：经命令新建项目以后，左侧栏无需刷新即出现新项目", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const before = await client.page.locator(".sidebar .nav-group button").count();
    const created = await client.page.evaluate(async (address: string) => {
      const response = await fetch(`${address}/api/commands/project.create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command_id: crypto.randomUUID(), name: "流驱动的新项目", goal: "验证事件流" }),
      });
      return response.status;
    }, backend.address);
    expect(created).toBe(200);
    // 视图同步按能力清单声明的 changed_by 重新查询 projects.list
    await expect(client.page.locator(".sidebar", { hasText: "流驱动的新项目" })).toBeVisible();
    const after = await client.page.locator(".sidebar .nav-group button").count();
    expect(after).toBeGreaterThan(before);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("从想法新建：提交成功、项目出现在列表以后表单关闭，重新打开时字段为空", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const page = client.page;
    const name = `表单关闭的项目 ${Date.now()}`;
    await page.locator(".sidebar .nav-item", { hasText: "从想法新建" }).click();
    const form = page.locator("form.card").filter({ has: page.getByRole("heading", { name: "从想法新建项目" }) });
    await expect(form).toBeVisible();
    await form.getByLabel("项目名称").fill(name);
    await form.getByLabel("长期目标").fill("核对新建表单的关闭与清空");
    await form.getByRole("button", { name: "新建项目" }).click();
    // 事件到达、项目出现在列表里：表单随之关闭
    await expect(page.locator(".project-entry").filter({ hasText: name })).toBeVisible();
    await expect(form).toHaveCount(0);
    // 重新打开表单：名称、长期目标与起始文件夹都是空的（字段随表单一起清空）
    await page.locator(".sidebar .nav-item", { hasText: "从想法新建" }).click();
    const reopened = page.locator("form.card").filter({ has: page.getByRole("heading", { name: "从想法新建项目" }) });
    await expect(reopened.getByLabel("项目名称")).toHaveValue("");
    await expect(reopened.getByLabel("长期目标")).toHaveValue("");
    await expect(reopened.getByLabel("起始文件夹")).toHaveValue("");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("接口版本相同而能力清单多出查询时，客户端正常使用（新增查询不要求更新客户端）", async () => {
  // 当前部署的接口版本与服务端构建版本相同；服务端的能力清单包含项目与决定相关的查询，
  // 客户端按能力清单打开外壳与项目标签，不出现更新页
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    await client.page.evaluate((hash: string) => {
      window.location.hash = hash;
    }, "#/home");
    await expect(client.page.locator(".sidebar")).toBeVisible();
    await expect(client.page.locator("text=页面与服务的接口版本不同")).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("接口版本不同时页面只显示版本不同的提示（写明两边的版本），不打开页面、不执行命令", async () => {
  const other = await startBackend({ apiVersion: CLIENT_API_VERSION + 1 });
  try {
    const client = await startClient(other, { width: 1440, height: 900 });
    const errors = watchErrors(client);
    try {
      await expect(client.page.getByRole("heading", { name: "页面与服务的接口版本不同" })).toBeVisible();
      // 页面上的措辞按工单 #704 改过：写清这一份页面文件与服务各是哪个版本（原来写「页面的接口版本是 7」）
      await expect(client.page.locator(".gate .error")).toContainText(`这一份页面文件的接口版本是 ${CLIENT_API_VERSION}`);
      await expect(client.page.locator(".gate .error")).toContainText(`服务要的是 ${CLIENT_API_VERSION + 1}`);
      // 不打开任何页面：外壳与左侧栏都不出现
      await expect(client.page.locator(".sidebar")).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  } finally {
    await other.stop();
  }
});

test("视口 1920×1080 下外壳可用，没有横向滚动条，控制台错误为零", async () => {
  const client = await startClient(backend, { width: 1920, height: 1080 });
  const errors = watchErrors(client);
  try {
    await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
    const overflow = await client.page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

// 连接断开时窗口整体变灰、顶栏写明断开的时间，重新连上以后恢复（设计说明第 3.4 节，工单 #296）
test("事件流断开时窗口整体变灰并写明断开的时间，重新连上以后恢复", async () => {
  test.setTimeout(240_000);
  // 这个用例自己起服务：断线要真的停掉它，再用同一端口与数据目录起回来
  const own = await startBackend();
  const client = await startClient(own, { width: 1440, height: 900 });
  try {
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: 90_000 });

    await own.stop();
    await expect(client.page.locator("body")).toHaveClass(/is-disconnected/, { timeout: 60_000 });
    // 顶栏写明断开的时间与正在重新连接（不是「连接中断，数据可能过时」这一句旧文案）
    await expect(client.page.locator(".connection.interrupted")).toContainText("断开，正在重新连接");
    const stamp = await client.page.locator(".connection.interrupted").innerText();
    expect(stamp).toMatch(/\d{2}:\d{2}/);
    // 数据保留最后一次的：首页仍然显示
    await expect(client.page.locator(".page.home")).toBeVisible();

    const again = await startBackend({ port: own.port, dataDir: own.dataDir });
    try {
      await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: 90_000 });
      await expect(client.page.locator("body")).not.toHaveClass(/is-disconnected/);
    } finally {
      await again.stop();
    }
  } finally {
    await client.close();
    await own.stop();
  }
});

// 初次连接期间顶栏写「连接中」，不写「连接中断」与「刚刚断开」（工单 #653）
test("初次连接期间顶栏写连接中，事件流连上以后写已连接", async () => {
  test.setTimeout(240_000);
  // 这个用例自己起服务：事件流的请求要在页面里延后，别的用例的时序不受影响
  const own = await startBackend();
  const client = await startClient(own, { width: 1440, height: 900 });
  try {
    // 事件流的请求延后几秒：能力清单读完到事件流连上之间这一段，页面处于「连接中」
    await client.page.route("**/api/events**", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 5000));
      await route.continue();
    });
    await client.page.reload();
    await expect(client.page.locator(".connection")).toHaveText(/连接中/, { timeout: 60_000 });
    await expect(client.page.locator(".connection")).not.toContainText("连接中断");
    await expect(client.page.locator(".connection")).not.toContainText("刚刚");
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: 90_000 });
  } finally {
    await client.close();
    await own.stop();
  }
});

test("订阅位置超过日志末尾时服务端发送 resync，客户端据此重新同步快照", async () => {
  // 事件流的缺口与 resync 是「断线以后恢复」的触发条件（设计说明第 5.5 节）：
  // 客户端按位置续传，位置超过日志末尾时服务端发送 resync 并关闭连接，客户端重新查询快照再订阅。
  // 这里经真实的 SSE 连接核对服务端的这一行为；客户端一侧的缺口核对与重新查询由 tests/unit 覆盖。
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const frame = await client.page.evaluate(async (address: string) => {
      const end = await (await fetch(`${address}/api/queries/system.status`)).json();
      const response = await fetch(`${address}/api/events?after=${end.position + 1000}`, {
        headers: { Accept: "text/event-stream" },
      });
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let text = "";
      const deadline = Date.now() + 10000;
      while (Date.now() < deadline) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        text += decoder.decode(value, { stream: true });
        if (text.includes("resync")) {
          break;
        }
      }
      reader.cancel();
      return text;
    }, backend.address);
    expect(frame).toContain("event: resync");
    expect(frame).toContain("position_unknown");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

// 内容区最宽 1280 像素并在主区居中（工单 #377 验收第 2 条）：窗口 1920 时主区比 1280 宽，
// 左右留白相同；窗口再大时也不再变宽，多出来的宽度留在两侧
test("1920×1080 下内容区宽 1280 并在主区居中", async () => {
  const client = await openClient({ width: 1920, height: 1080 });
  const errors = watchErrors(client);
  try {
    const box = await client.page.evaluate(() => {
      const mainEl = document.querySelector<HTMLElement>(".y10-main");
      const content = document.querySelector<HTMLElement>(".y10-content");
      if (mainEl === null || content === null) throw new Error("找不到内容区");
      const main = mainEl.getBoundingClientRect();
      const box = content.getBoundingClientRect();
      return { mainWidth: main.width, width: box.width, left: box.left - main.left, right: main.right - box.right };
    });
    expect(box.mainWidth).toBeGreaterThan(1280);
    expect(Math.round(box.width)).toBe(1280);
    expect(Math.abs(box.left - box.right)).toBeLessThanOrEqual(1);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

// 缩放 150%（工单 #377 验收第 2 条）：浏览器整体放大以后按缩放后的尺寸排布，
// 1920 的物理窗口在 150% 下给页面 1280×720 的排版尺寸，页面仍不出现横向滚动条
test("浏览器缩放 150% 时页面没有横向滚动条", async () => {
  const client = await startClient(backend, { width: 1280, height: 720 }, { deviceScaleFactor: 1.5 });
  const errors = watchErrors(client);
  try {
    await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
    await expect(client.page.locator(".sidebar")).toBeVisible();
    const overflow = await client.page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

// 主题的选择记在浏览器里（工单 #377 验收第 2 条）：手动选择浅色或深色以后刷新页面，
// 选择保持；顶栏的三档按钮里选中的那一档带 aria-pressed
test("切换浅色与深色主题以后刷新页面，主题保持", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const themeOf = () => client.page.evaluate(() => document.documentElement.dataset.theme ?? "system");
    expect(await themeOf()).toBe("system");
    for (const choice of ["浅色", "深色"]) {
      await client.page.getByRole("button", { name: choice }).click();
      await expect.poll(themeOf).toBe(choice === "浅色" ? "light" : "dark");
      await client.page.reload();
      await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
      expect(await themeOf()).toBe(choice === "浅色" ? "light" : "dark");
      await expect(client.page.getByRole("button", { name: choice })).toHaveAttribute("aria-pressed", "true");
    }
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
