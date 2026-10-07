// 首页楼的端到端测试（工单 #178 验收标准 3、4）：Playwright 打开 Chromium 页面，页面由 FakeAdapter 驱动的真实服务提供。
// 覆盖：两个项目（一个运行中、一个空闲）各画一层，楼层的灯与状态灯随事件变化；置顶以后楼层顺序改变；
// 点击楼层进入对应项目的概览；1440×900 与 1920×1080 两种窗口尺寸下控制台错误为零。
//
// 观测方式：楼层的文字列表（与画面同一份数据）读每层的名称、状态与亮灯部门；导航读页面的 hash 与概览页的标题。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const IDLE = "示例项目";
const RUNNING = "文本工具";

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    // 服务端按设计用 409 拒绝命令，界面已把原因显示给用户，浏览器自己记的那条不算应用错误
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

async function query<T>(name: string, params: Record<string, unknown> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.append(key, String(value));
  }
  const qs = search.toString();
  const response = await fetch(`${backend.address}/api/queries/${name}${qs ? `?${qs}` : ""}`);
  const envelope = (await response.json()) as QueryEnvelope<T>;
  if (envelope.data === undefined) {
    throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data;
}

interface ProjectRow {
  project_id: string;
  name: string;
  pinned: boolean;
  version: number;
}

async function projectRow(name: string): Promise<ProjectRow> {
  const data = await query<{ projects: ProjectRow[] }>("projects.list");
  const row = data.projects.find((project) => project.name === name);
  if (!row) throw new Error(`projects.list 里没有项目 ${name}`);
  return row;
}

/** 从 Node 提交一条命令（服务本身是真实的，命令走真实的接口层）。 */
async function command(name: string, body: Record<string, unknown>): Promise<void> {
  const response = await fetch(`${backend.address}/api/commands/${name}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ command_id: crypto.randomUUID(), ...body }),
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`命令 ${name} 被拒绝（${response.status}）：${text}`);
}

/** 楼层的文字列表：每行的项目名、状态与亮灯部门。 */
async function floors(page: Page): Promise<{ name: string; status: string; lit: string }[]> {
  return page.locator(".building-list li").evaluateAll((items) => items.map((li) => {
    const spans = Array.from(li.querySelectorAll("span"));
    const button = li.querySelector("button");
    return { name: button?.textContent?.trim() ?? "", status: spans[0]?.textContent?.trim() ?? "", lit: spans[1]?.textContent?.trim() ?? "" };
  }));
}

/** 等某个条件成立（页面按事件流自动重查询，不刷新页面）。 */

async function waitUntil(check: () => Promise<boolean>, description: string, timeoutMs = 60_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) return;
    if (Date.now() > deadline) throw new Error(`等待超时：${description}`);
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}
// 用户主动停止的事项要在楼层写「已停止」。停止会改变服务端状态（run 以 cancelled 结束），
// 因此这条用例用自己的一份后端，结束以后停掉，共用的那份不受影响
async function withOwnBackend<T>(run: () => Promise<T>): Promise<T> {
  const previous = backend;
  const own = await startBackend();
  backend = own;
  try {
    return await run();
  } finally {
    backend = previous;
    await own.stop();
  }
}

test("用户停止的事项：楼层与部门页都写「已停止」，不含「执行失败」「中断」", async () => {
  test.setTimeout(300_000);
  await withOwnBackend(async () => {
    const client = await startClient(backend, { width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      // 共用种子里「文本工具」的事项停在模型不可用，有一个等待回答的决定请求；选「停止事项」以后运行结束
      const [decision] = (await query<{ decisions: { decision_id: string; version: number }[] }>(
        "decisions.list", { status: ["open"] })).decisions;
      if (!decision) throw new Error("没有等待回答的决定请求，停止不了事项");
      await command("decision.answer", {
        decision_id: decision.decision_id, option: "stop", base_version: decision.version,
      });
      const stopped = (await projectRow(RUNNING)).project_id;
      // 部门页：被停止的事项所在部门的「部门状态」
      await page.evaluate((id) => { window.location.hash = `/p/${id}/dept/engineering`; }, stopped);
      const status = page.locator(".line").filter({ hasText: "部门状态" }).first();
      await expect(status).toContainText("已停止");
      await expect(status).not.toContainText("执行失败");
      await expect(status).not.toContainText("中断");
      // 首页楼层：这一层的状态灯写「已停止」
      await page.evaluate(() => { window.location.hash = "#/home"; });
      await expect(page.getByRole("heading", { name: "全部项目与机器", exact: true })).toBeVisible();
      await waitUntil(
        async () => (await floors(page)).find((f) => f.name === RUNNING)?.status === "已停止",
        "这一层的状态灯显示「已停止」",
      );
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});

test("楼里每个项目一层，运行中的一层亮起工作部门，空闲的一层没有部门在工作", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.evaluate(() => { window.location.hash = "#/home"; });
    await expect(page.getByRole("heading", { name: "全部项目与机器", exact: true })).toBeVisible();
    await waitUntil(async () => (await floors(page)).length >= 2, "楼里出现至少两层");

    // 至少两层，且每层的项目名来自 projects.list 的项目集合
    const list = await floors(page);
    const names = list.map((f) => f.name);
    expect(names).toContain(IDLE);
    expect(names).toContain(RUNNING);

    // 空闲的一层：状态为空闲，没有部门在工作
    const idle = list.find((f) => f.name === IDLE);
    expect(idle?.status).toBe("空闲");
    expect(idle?.lit).toBe("没有部门在工作");

    // 运行中的一层：状态不是空闲，至少有一个部门在工作（灯的部门来自事项的所在部门）
    const running = list.find((f) => f.name === RUNNING);
    expect(running?.status).not.toBe("空闲");
    expect(running?.lit).toMatch(/在工作$/);

    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("置顶以后楼层顺序改变：置顶的项目排到最上面", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.evaluate(() => { window.location.hash = "#/home"; });
    await waitUntil(async () => (await floors(page)).length >= 2, "楼里出现至少两层");

    // 置顶「文本工具」：事件流到达以后页面自动重新查询（不刷新）
    const target = await projectRow(RUNNING);
    await command("project.pin", { project_id: target.project_id, pinned: true, base_version: target.version });
    await waitUntil(async () => (await floors(page))[0]?.name === RUNNING, "置顶的项目排到最上面");

    const order = (await floors(page)).map((f) => f.name);
    expect(order[0]).toBe(RUNNING);
    expect(errors).toEqual([]);

    // 复位：取消置顶，回到原来的排列
    const after = await projectRow(RUNNING);
    await command("project.pin", { project_id: after.project_id, pinned: false, base_version: after.version });
    await waitUntil(async () => (await floors(page)).find((f) => f.name === RUNNING)?.status !== undefined, "取消置顶以后仍在楼里");
  } finally {
    await client.close();
  }
});

test("点击楼层进入对应项目的概览", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.evaluate(() => { window.location.hash = "#/home"; });
    await waitUntil(async () => (await floors(page)).some((f) => f.name === IDLE), "楼里出现示例项目一层");
    const id = (await projectRow(IDLE)).project_id;
    await page.locator(".building-list li").filter({ hasText: IDLE }).locator("button").click();
    await expect(page).toHaveURL(new RegExp(`#/p/${id}/overview`));
    await expect(page.locator(".tabbar .tab[aria-current='page']")).toContainText("概览");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test.describe("宽屏", () => {
  test("1920×1080 下楼的画布不溢出、控制台错误为零", async () => {
    const client = await startClient(backend, { width: 1920, height: 1080 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      await page.evaluate(() => { window.location.hash = "#/home"; });
      await expect(page.getByRole("heading", { name: "全部项目与机器", exact: true })).toBeVisible();
      await waitUntil(async () => (await floors(page)).length >= 2, "楼里出现至少两层");

      // 楼层的画布按整数倍（逻辑宽 640 的整数倍），且宽屏下不横向溢出
      const canvas = page.locator(".building-canvas canvas");
      await expect(canvas).toHaveCount(1);
      const width = await canvas.evaluate((el) => (el as HTMLCanvasElement).width);
      expect(width % 640).toBe(0);
      const overflow = await page.evaluate(() => {
        const root = document.documentElement;
        return root.scrollWidth - root.clientWidth;
      });
      expect(overflow).toBeLessThanOrEqual(1);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});
