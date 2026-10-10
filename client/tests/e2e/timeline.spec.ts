// 时间轴与回放的端到端测试（工单 #180 的验收）：Playwright 启动 Chromium 页面，页面文件由
// FakeAdapter 驱动的真实后端提供（client/tests/e2e/backend.py），模型回答由 FakeAdapter 给出。
// 预置的第一个事项包含交接、返工、询问与回答、采纳，因此首页与概览的时间轴刻度与 home.away_report 的
// 关键事实一一对应；拖到某个刻度时画面与带 at 的查询结果一致；「回到现在」恢复实时画面，回放期间到达的事件不丢失。
//
// 观测方式：时间轴的刻度（.tick 的 data-position 与 data-kind）与查询结果逐项比较；
// 回放位置用「回放中」横幅、楼层的文字列表与带 at 的查询结果核对。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const SAMPLE = "交付历史";
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

interface Fact {
  position: number;
  at: string;
  type: string;
  /** 应用层给出的刻度种类（handoff、ask、answer、rework、release、adopt、decision 等）。 */
  kind: string | null;
  label: string;
  project_id: string | null;
  work_item_id: string | null;
}

/** 关键事实里作为刻度的部分：位置与种类（没有种类的事实不是刻度）。 */
function tickRows(facts: Fact[]): { position: number; kind: string }[] {
  const rows: { position: number; kind: string }[] = [];
  for (const fact of facts) {
    if (typeof fact.kind === "string" && fact.kind !== "") {
      rows.push({ position: fact.position, kind: fact.kind });
    }
  }
  return rows;
}

async function projectId(name: string): Promise<string> {
  const data = await query<{ projects: { name: string; project_id: string }[] }>("projects.list");
  const row = data.projects.find((project) => project.name === name);
  if (!row) throw new Error(`projects.list 里没有项目 ${name}`);
  return row.project_id;
}

/** 时间轴上的刻度：位置与种类。 */
async function ticks(page: Page, region: string): Promise<{ position: number; kind: string }[]> {
  return page.locator(`${region} .tick`).evaluateAll((nodes) => nodes.map((node) => ({
    position: Number((node as HTMLElement).dataset.position),
    kind: (node as HTMLElement).dataset.kind ?? "",
  })));
}

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

test("首页时间轴的刻度与 home.away_report 的关键事实一一对应，刻度按种类着色", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.evaluate(() => { window.location.hash = "#/home"; });
    await expect(page.getByRole("heading", { name: "离开期间的报告", exact: true })).toBeVisible();

    const report = await query<{ facts: Fact[] }>("home.away_report", { range: "7d" });
    const expected = tickRows(report.facts);

    // 运行包含交接、返工、询问与回答、采纳，覆盖验收要求的关键事实
    const kinds = new Set(expected.map((row) => row.kind));
    for (const kind of ["handoff", "ask", "answer", "rework", "release", "adopt"]) {
      expect(kinds.has(kind), `关键事实里应当有 ${kind}`).toBe(true);
    }

    await waitUntil(async () => (await ticks(page, ".card .timeline")).length === expected.length, "首页时间轴的刻度数与关键事实一致");
    expect(await ticks(page, ".card .timeline")).toEqual(expected);

    // 每类的刻度按种类着色：同一种类的刻度着色相同，不同种类不同
    const colorOf = await page.locator(".card .timeline .tick").evaluateAll((nodes) =>
      nodes.map((node) => ({ kind: (node as HTMLElement).dataset.kind ?? "", color: getComputedStyle(node.firstElementChild as Element).backgroundColor })));
    const byKind = new Map<string, string>();
    for (const row of colorOf) {
      if (byKind.has(row.kind)) {
        expect(row.color).toBe(byKind.get(row.kind));
      } else {
        byKind.set(row.kind, row.color);
      }
    }
    expect(new Set(byKind.values()).size).toBe(byKind.size);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("首页拖动刻度回到过去：楼层的状态与带 at 的查询结果一致，报告项与刻度互相高亮", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.evaluate(() => { window.location.hash = "#/home"; });
    const report = await query<{ facts: Fact[] }>("home.away_report", { range: "7d" });
    const expected = tickRows(report.facts);
    const handle = page.locator("section.card").filter({ has: page.getByRole("heading", { name: "离开期间的报告", exact: true }) });
    await expect(handle.locator(".timeline .tick").first()).toBeVisible();

    // 点第一个刻度：回放中，画面按该位置的快照显示
    const first = expected[0];
    await handle.locator(`.timeline .tick[data-position="${first.position}"]`).click();
    await expect(handle.locator(".replay-status")).toContainText("回放中");
    await expect(page.locator(".replay-banner")).toContainText("回放中");

    // 楼层的状态与带 at 的 projects.list 一致（每个项目一层的名称来自该位置的快照）
    const atProjects = await query<{ projects: { project_id: string; name: string }[] }>("projects.list", { at: first.position });
    const floorNames = await page.locator(".building-list li button").evaluateAll((nodes) => nodes.map((node) => node.textContent?.trim() ?? ""));
    expect(floorNames.slice().sort()).toEqual(atProjects.projects.map((project) => project.name).slice().sort());

    // 报告项与刻度互相高亮：展开报告的第一个汇总项，它的来源事件对应的刻度高亮
    const summary = await query<{ summary: { id: string; refs: number[] }[] }>("home.away_report", { range: "7d" });
    const tickPositions = new Set(expected.map((row) => row.position));
    const itemIndex = summary.summary.findIndex((row) => row.refs.some((position) => tickPositions.has(position)));
    expect(itemIndex).toBeGreaterThanOrEqual(0);
    const refsInTicks = summary.summary[itemIndex].refs.filter((position) => tickPositions.has(position));
    await handle.locator(".report-item").nth(itemIndex).locator(".report-head").click();
    await waitUntil(async () => (await page.locator(".card .timeline .tick.highlight").count()) === refsInTicks.length, "报告项展开以后对应的刻度高亮");
    // 反向：点击刻度时对应的报告项高亮（回到现在的实时画面）
    await handle.getByRole("button", { name: "回到现在" }).click();
    const highlightTick = refsInTicks[0];
    await handle.locator(`.timeline .tick[data-position="${highlightTick}"]`).click();
    await expect(handle.locator(".report-item").nth(itemIndex)).toHaveClass(/highlight/);

    // 「回到现在」恢复实时画面
    await handle.getByRole("button", { name: "回到现在" }).click();
    await expect(handle.locator(".replay-status")).toHaveCount(0);
    await expect(page.locator(".replay-banner")).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("概览时间轴的刻度只含本项目的关键事实，拖动刻度时画面显示该时刻的状态", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const pid = await projectId(SAMPLE);
    await page.evaluate((id: string) => { window.location.hash = `#/p/${id}/overview`; }, pid);
    await expect(page.getByRole("heading", { name: "循环画面", exact: true })).toBeVisible();

    const report = await query<{ facts: Fact[] }>("home.away_report", { range: "7d", project: pid });
    const expected = tickRows(report.facts);
    await waitUntil(async () => (await ticks(page, ".timeline")).length === expected.length, "概览时间轴的刻度数与本项目关键事实一致");
    expect(await ticks(page, ".timeline")).toEqual(expected);

    // 拖到运行结束之前的某个刻度：事项处于进行中；回到现在时为已采纳
    const beforeDone = expected[0];
    await page.locator(`.timeline .tick[data-position="${beforeDone.position}"]`).click();
    await expect(page.locator(".replay-banner")).toContainText("回放中");
    const atLoop = await query<{ work_items: { status: string }[] }>("project.loop", { project_id: pid, at: beforeDone.position });
    // 文字列表默认折叠：先展开再读行；状态写中文（工单 #379）
    const textList = page.locator("details.floor-text-list");
    await textList.locator("summary").click();
    await expect(textList.locator("li").first()).toContainText(atLoop.work_items[0].status === "adopted" ? "已采纳" : "进行中");

    // 回放期间不显示决定请求（概览的等待回答列表不出现）
    await expect(page.locator(".decision-card")).toHaveCount(0);

    await page.getByRole("button", { name: "回到现在" }).click();
    await expect(page.locator(".replay-banner")).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("回放期间到达的事件没有丢失：回到现在以后画面与实时的查询结果一致", async () => {
  test.setTimeout(180_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const pid = await projectId(RUNNING);
    // 回放「文本工具」项目：这个项目停在模型不可用，有等待回答的决定请求
    await page.evaluate((id: string) => { window.location.hash = `#/p/${id}/overview`; }, pid);
    await expect(page.getByRole("heading", { name: "循环画面", exact: true })).toBeVisible();
    const report = await query<{ facts: Fact[] }>("home.away_report", { range: "7d", project: pid });
    const first = tickRows(report.facts)[0];
    expect(first).toBeTruthy();

    // 进入回放，回答一个等待中的决定请求（在回放期间事件到达）
    await page.locator(`.timeline .tick[data-position="${first.position}"]`).click();
    await expect(page.locator(".replay-banner")).toContainText("回放中");
    const decisions = await query<{ decisions: { decision_id: string; version: number }[] }>("decisions.list", { project_id: pid, status: ["open"] });
    if (decisions.decisions.length > 0) {
      await fetch(`${backend.address}/api/commands/decision.answer`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ command_id: crypto.randomUUID(), decision_id: decisions.decisions[0].decision_id, option: "continue", base_version: decisions.decisions[0].version }),
      });
    }

    // 回到现在：重新查询不带 at 的快照，回放期间到达的事件都在（等待列表为空或已变化）
    await page.getByRole("button", { name: "回到现在" }).click();
    await expect(page.locator(".replay-banner")).toHaveCount(0);
    await waitUntil(async () => {
      const now = await query<{ decisions: { decision_id: string }[] }>("decisions.list", { project_id: pid, status: ["open"] });
      return now.decisions.every((row) => row.decision_id !== decisions.decisions[0]?.decision_id);
    }, "回到现在以后等待列表反映回放期间到达的回答事件", 60_000);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

// 回放位置写在路径的 ?at= 中（设计说明第 3.3 节，工单 #296）：刷新与后退都回到同一位置
test("回放位置写在路径的 at 参数里：刷新以后回到同一位置，回到现在清除参数", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.evaluate(() => { window.location.hash = "#/home"; });
    await expect(page.getByRole("heading", { name: "离开期间的报告", exact: true })).toBeVisible();
    await waitUntil(async () => (await ticks(page, ".timeline")).length > 0, "首页时间轴有刻度");

    const tick = (await ticks(page, ".timeline"))[0];
    await page.locator(`.timeline .tick[data-position="${tick.position}"]`).click();
    await expect(page.locator(".replay-banner")).toContainText("回放中");
    expect(new URLSearchParams(page.url().split("?")[1] ?? "").get("at")).toBe(String(tick.position));

    // 刷新：路径上的 at 让界面回到同一位置
    await page.reload();
    await expect(page.locator(".replay-banner")).toContainText("回放中", { timeout: 60_000 });
    await waitUntil(async () =>
      (await page.locator(`.timeline .tick[data-position="${tick.position}"].current`).count()) > 0,
    "刷新以后时间轴上的位置仍然是同一个刻度", 60_000);

    // 回到现在：路径上的 at 清除
    await page.getByRole("button", { name: "回到现在" }).click();
    await expect(page.locator(".replay-banner")).toHaveCount(0);
    expect(new URLSearchParams(page.url().split("?")[1] ?? "").get("at")).toBeNull();
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

// 概览页的回放位置同样写在路径里（工单 #379 验收）：刷新以后回到同一位置
test("概览页的回放位置写在路径的 at 参数里：刷新以后回到同一位置", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const pid = await projectId(SAMPLE);
    await page.evaluate((id: string) => { window.location.hash = `#/p/${id}/overview`; }, pid);
    await expect(page.getByRole("heading", { name: "循环画面", exact: true })).toBeVisible();
    const report = await query<{ facts: Fact[] }>("home.away_report", { range: "7d", project: pid });
    const expected = tickRows(report.facts);
    await waitUntil(async () => (await ticks(page, ".timeline")).length === expected.length, "概览时间轴有刻度");

    const tick = expected[0];
    await page.locator(`.timeline .tick[data-position="${tick.position}"]`).click();
    await expect(page.locator(".replay-banner")).toContainText("回放中");
    expect(new URLSearchParams(page.url().split("?")[1] ?? "").get("at")).toBe(String(tick.position));

    // 刷新：路径上的 at 让概览页回到同一位置，画面仍是回放中的状态
    await page.reload();
    await expect(page.locator(".replay-banner")).toContainText("回放中", { timeout: 60_000 });
    await waitUntil(async () =>
      (await page.locator(`.timeline .tick[data-position="${tick.position}"].current`).count()) > 0,
    "刷新以后概览时间轴上的位置仍然是同一个刻度", 60_000);

    await page.getByRole("button", { name: "回到现在" }).click();
    await expect(page.locator(".replay-banner")).toHaveCount(0);
    expect(new URLSearchParams(page.url().split("?")[1] ?? "").get("at")).toBeNull();
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test.describe("宽屏（1920×1080）", () => {
  test("1920×1080 下时间轴不溢出、控制台错误为零", async () => {
    const client = await startClient(backend, { width: 1920, height: 1080 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      await page.evaluate(() => { window.location.hash = "#/home"; });
      await expect(page.getByRole("heading", { name: "离开期间的报告", exact: true })).toBeVisible();
      await expect(page.locator(".card .timeline .tick").first()).toBeVisible();
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
