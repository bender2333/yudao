// 首页楼的端到端测试（工单 #178 验收标准 3、4，工单 #955 验收标准 3、5）：
// Playwright 打开 Chromium 页面，页面由 FakeAdapter 驱动的真实服务提供（页面是构建产物）。
// 覆盖：两个项目（一个运行中、一个空闲）各画一层，楼层的灯与状态灯随查询变化；状态词只出现画面合同的八个取值；
// 置顶以后楼层顺序改变；点击楼层进入对应项目的概览；打开画面与标签页从后台切回时画面直接显示最新状态、
// 不补播（与重新同步同一条 jump）；1440×900 与 1920×1080 两种窗口尺寸下控制台错误为零。
//
// 观测方式：楼层的文字列表（与画面同一份数据）读每层的名称、状态与亮灯部门；画面自己的读数经
// __buildingViewForTest（每层、每层小人与播放时间线）读；导航读页面的 hash 与概览页的标题。
// 截图只在本机留证据时写（环境变量 YUDAO_SHOTS 给出目录），CI 里不写文件。

import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const IDLE = "示例项目";
const RUNNING = "文本工具";

/** 画面合同的八个状态灯（像素 5 只出现这几个词；服务端的说法不上海画面）。 */
const FLOOR_SIGN_TEXT = ["运行中", "排队中", "等待执行槽位", "等待模型服务", "待恢复", "等待你的决定", "中断", "空闲"];

/** 本机留证据时的截图目录（交付说明里列路径）；CI 里不设，不写文件。 */
const SHOTS = process.env.YUDAO_SHOTS ?? "";

async function shot(page: Page, name: string): Promise<void> {
  if (!SHOTS) return;
  await page.screenshot({ path: join(SHOTS, name) });
}

interface BuildingTimeline {
  shown: number | null;
  pending: number;
  lag: number;
  queued: number;
  playing: string[];
}

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

/** 画面自己的读数：播放时间线此刻的位置、排着的状态与在演的动作。 */
async function timeline(page: Page): Promise<BuildingTimeline> {
  return page.evaluate(() => {
    const hooks = (window as unknown as { __buildingViewForTest?: { timeline: () => BuildingTimeline } }).__buildingViewForTest;
    if (!hooks) throw new Error("页面没有楼画面的读取入口");
    return hooks.timeline();
  });
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

// 用户主动停止的事项：部门页写「已停止」，首页楼层写「空闲」（工单 #734：楼层只由未结束的事项决定，
// 被停止、已采纳与放行未定的事项不参与）。停止会改变服务端状态（run 以 cancelled 结束），
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

test("用户停止的事项：部门页写「已停止」，首页楼层写「空闲」，都不写「执行失败」「中断」", async () => {
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
      // 首页楼层：这一层的状态灯写「空闲」（工单 #734：楼层说的是这个项目此刻怎么样，
      // 停止是过去发生的事；被停止的事项不参与楼层的状态）
      await page.evaluate(() => { window.location.hash = "#/home"; });
      await expect(page.getByRole("heading", { name: "全部项目与机器", exact: true })).toBeVisible();
      await waitUntil(
        async () => (await floors(page)).find((f) => f.name === RUNNING)?.status === "空闲",
        "这一层的状态灯显示「空闲」",
      );
      const floor = (await floors(page)).find((f) => f.name === RUNNING);
      expect(floor?.status).toBe("空闲");
      expect(floor?.status).not.toContain("已停止");
      expect(floor?.status).not.toContain("执行失败");
      expect(floor?.status).not.toContain("中断");
      // 空闲的一层：此刻没有部门在工作
      expect(floor?.lit).toBe("没有部门在工作");
      await shot(page, "955-home-stopped.png");
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
    // 楼层状态来自每个项目的 project.loop：查询到达以前每层都是「空闲」，先等状态到位再核对
    await waitUntil(
      async () => (await floors(page)).find((f) => f.name === RUNNING)?.status !== "空闲",
      "「文本工具」这一层的状态灯不是空闲",
    );

    // 至少两层，且每层的项目名来自 projects.list 的项目集合
    const list = await floors(page);
    const names = list.map((f) => f.name);
    expect(names).toContain(IDLE);
    expect(names).toContain(RUNNING);

    // 状态词只出现画面合同的八个（翻译层翻好的取值，服务端的 in_progress、waiting_provider 这类说法不上画面）
    for (const floor of list) {
      expect(FLOOR_SIGN_TEXT).toContain(floor.status);
    }

    // 空闲的一层：状态为空闲，没有部门在工作
    const idle = list.find((f) => f.name === IDLE);
    expect(idle?.status).toBe("空闲");
    expect(idle?.lit).toBe("没有部门在工作");

    // 运行中的一层：状态不是空闲，至少有一个部门在工作（灯的部门来自事项的所在部门）
    const running = list.find((f) => f.name === RUNNING);
    expect(running?.status).not.toBe("空闲");
    expect(running?.lit).toMatch(/在工作$/);

    // 画布确实画出了楼：取画布上的像素，颜色不止一种（空白画布只有一种颜色）。
    // 不用 toHaveScreenshot 基线：跨机器字体会让它变成不稳定测试。
    const colors = await page.locator(".building-canvas canvas").evaluate((el) => {
      const canvas = el as HTMLCanvasElement;
      const ctx = canvas.getContext("2d");
      if (!ctx) return 0;
      const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      const seen = new Set<string>();
      for (let i = 0; i < data.length; i += 4 * 97) seen.add(`${data[i]},${data[i + 1]},${data[i + 2]}`);
      return seen.size;
    });
    expect(colors).toBeGreaterThan(8);
    await shot(page, "955-home-building.png");

    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("打开画面与标签页从后台切回：直接显示最新状态，不补播", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.evaluate(() => { window.location.hash = "#/home"; });
    await waitUntil(async () => (await floors(page)).length >= 2, "楼里出现至少两层");
    // 打开画面时状态直接显示（jump）：时间线上的位置就是查询给出的位置，没有排着的状态。
    // 建立画面以后到达的事件照演（设计说明第 5.2 节「迟到的动作」），所以这里不要求此刻没有在演的动作。
    await waitUntil(async () => {
      const info = await timeline(page);
      return (info.shown ?? 0) > 0 && info.pending === 0;
    }, "画面显示了一份状态，没有排着的状态");
    const opened = await timeline(page);
    expect(opened.pending).toBe(0);
    // 积下的动作演完以后时间线放空，一层状态的画面不再被动作挡住
    await waitUntil(async () => (await timeline(page)).playing.length === 0, "积下的动作演完");

    // 标签页从后台切回：清空时间线，直接显示最新状态，不补播（与打开画面、重新同步走同一个 jump）。
    // 在页面里同一步里派发事件再读，读到的是 jump 之后、下一帧之前的时间线。
    const afterVisible = await page.evaluate(() => {
      const hooks = (window as unknown as { __buildingViewForTest?: { timeline: () => BuildingTimeline } }).__buildingViewForTest;
      if (!hooks) throw new Error("页面没有楼画面的读取入口");
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
      document.dispatchEvent(new Event("visibilitychange"));
      return hooks.timeline();
    });
    expect(afterVisible.pending).toBe(0);
    expect(afterVisible.playing).toEqual([]);
    expect(afterVisible.shown).not.toBeNull();

    // 重新打开页面（重新同步与打开画面是同一条 jump）：楼的层次与状态再次按查询给出
    await page.reload();
    await expect(page.getByRole("heading", { name: "全部项目与机器", exact: true })).toBeVisible();
    await waitUntil(async () => (await floors(page)).length >= 2, "重新打开以后楼里仍有至少两层");
    await waitUntil(async () => {
      const info = await timeline(page);
      return (info.shown ?? 0) > 0 && info.pending === 0;
    }, "重新打开以后画面显示了一份状态");
    const reopened = await timeline(page);
    expect(reopened.pending).toBe(0);
    await shot(page, "955-home-reopened.png");
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
      await shot(page, "955-home-wide-1920x1080.png");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});
