// 时间轴与回放的端到端测试（工单 #180 的验收）：Playwright 启动 Chromium 页面，页面文件由
// FakeAdapter 驱动的真实后端提供（client/tests/e2e/backend.py），模型回答由 FakeAdapter 给出。
// 预置的第一个事项包含交接、返工、询问与回答、采纳，因此首页与概览的时间轴刻度与 home.away_report 的
// 关键事实一一对应；拖到某个刻度时画面与带 at 的查询结果一致；「回到现在」恢复实时画面，回放期间到达的事件不丢失。
//
// 观测方式：时间轴的刻度（.tick 的 data-position 与 data-kind）与查询结果逐项比较；
// 回放位置用「回放中」横幅、楼层的文字列表与带 at 的查询结果核对。

import { expect,test,type Page } from "@playwright/test";
import { join } from "node:path";
import { startBackend,startClient,type Backend,type ClientApp } from "./fixtures";

const SAMPLE = "交付历史";

// 回放范围（工单 #1217）：同一项目里先后两个事项，前一个结束以后才有后一个。
// 由 --script replay 预置（client/tests/e2e/backend.py 的 seed），其余用例不用这个项目
const TWO_ITEMS = "回放范围";

// 观测窗口（工单 #1217 的验收第 2 条）：在回放位置上停留 90 秒，这段时间里客户端收到事件就按
// 当时的参数重查 project.loop，页面不该发出「那一刻还没有这个事项」的组合
const REPLAY_WINDOW_MS = 90_000;

/** 本机留证据时的截图目录（交付说明里列路径）；CI 里不设，不写文件（与 building.spec.ts 同一做法）。 */
const SHOTS = process.env.YUDAO_SHOTS ?? "";

async function shot(page: Page, name: string): Promise<void> {
  if (!SHOTS) return;
  await page.screenshot({ path: join(SHOTS, name) });
}

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  // 回放范围的预置只在这个模式里建（工单 #1217）：默认脚本再加同一项目里两个走完一轮的事项
  backend = await startBackend({ script: "replay" });
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

/** 页面发出的每一次查询与它的状态码（工单 #1217：只读，不改被测代码）。 */
function watchQueries(page: Page): { url: string; status: number }[] {
  const rows: { url: string; status: number }[] = [];
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/api/queries/")) {
      rows.push({ url, status: response.status() });
    }
  });
  return rows;
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
  /** 应用层给出的刻度种类（ask、answer、rework、release、adopt、decision 等；交接已经不再产生）。 */
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

async function waitUntil(check: () => Promise<boolean>, description: string, timeoutMs = 60_000): Promise<void> {  const deadline = Date.now() + timeoutMs;
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

    // 运行包含返工、询问与回答、放行与采纳，覆盖验收要求的关键事实
    // （交接已经随阶段状态机一起删除，部门按关注的成果开始工作，循环结构第 2 节）
    const kinds = new Set(expected.map((row) => row.kind));
    for (const kind of ["ask", "answer", "rework", "release", "adopt"]) {
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


// 工单 #1217：同一项目里先后两个事项、前一个已经结束。按后一个事项的范围打开概览，点前一个事项的
// 刻度：那一刻的位置与事项范围是两个参数（接口设计说明第 4.1 节「按位置读取」），页面先把 ?w= 换成
// 那个事项，再按位置读取，画面显示那一刻的那个事项；服务端对「那一刻还不存在的 work_item」照旧 404，
// 页面因此不再发出这种组合——观测窗口里没有 4xx。
test("点属于另一个事项的刻度：先换事项范围再按位置读取，画面显示那一刻的那个事项，窗口内没有 4xx", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  const requests = watchQueries(page);
  try {
    const pid = await projectId(TWO_ITEMS);
    const overview = await query<{ work_items: { work_item_id: string; title: string; status: string }[] }>(
      "project.overview", { project_id: pid });
    expect(overview.work_items.length, "回放范围项目里应当有两个事项").toBe(2);
    const report = await query<{ facts: Fact[] }>("home.away_report", { range: "7d", project: pid });
    // 两个事项的先后按各自最早的关键事实位置排，不靠工单标识或列表顺序
    const firstAt = (id: string): number =>
      Math.min(...report.facts.filter((fact) => fact.work_item_id === id).map((fact) => fact.position));
    const ordered = [...overview.work_items].sort((a, b) => firstAt(a.work_item_id) - firstAt(b.work_item_id));
    const former = ordered[0];
    const latter = ordered[1];
    if (former === undefined || latter === undefined) {
      throw new Error("回放范围项目里没有两个事项");
    }
    // 前一个事项的第一个刻度：那一刻后一个事项还没有创建（服务端对它的答案是 404）
    const formerTicks = report.facts.filter((fact) =>
      fact.work_item_id === former.work_item_id && typeof fact.kind === "string" && fact.kind !== "");
    expect(formerTicks.length, "前一个事项应当有关键事实作为刻度").toBeGreaterThan(0);
    const target = formerTicks[0];
    if (target === undefined) {
      throw new Error("前一个事项没有刻度");
    }
    expect(firstAt(latter.work_item_id), "后一个事项应当在前一个事项的刻度之后才开始").toBeGreaterThan(target.position);

    // 按后一个事项的范围打开概览
    await page.evaluate((hash: string) => { window.location.hash = hash; }, `#/p/${pid}/overview?w=${latter.work_item_id}`);
    await expect(page.getByRole("heading", { name: "循环画面", exact: true })).toBeVisible();
    await expect(page.locator(`.timeline .tick[data-position="${target.position}"]`)).toBeVisible();
    await shot(page, "1217-01-概览-后一个事项的范围-点刻度之前.png");

    // 点前一个事项的刻度
    requests.length = 0;
    await page.locator(`.timeline .tick[data-position="${target.position}"]`).click();
    // 等这次导航的查询与画面落地，留一张截图（修前这一张是「没有进行中的事项」，修后是那一刻的事项）
    await page.waitForTimeout(1500);
    await shot(page, "1217-02-回放-点前一个事项的刻度.png");

    // 换范围与换位置在同一次导航里：地址里 ?w= 与 ?at= 一起变
    await expect.poll(async () => page.evaluate(() => window.location.hash), { message: "地址里换成前一个事项的范围" })
      .toContain(`w=${former.work_item_id}`);
    const hash = await page.evaluate(() => window.location.hash);
    expect(hash, "地址里带着回放位置").toContain(`at=${target.position}`);

    // 画面显示那一刻的那个事项：回放横幅、当前事项与画面的文字列表都是前一个事项
    await expect(page.locator(".replay-banner")).toContainText("回放中");
    const current = page.locator("#ov-current");
    await expect(current).toContainText(former.title);
    await expect(current).not.toContainText("项目没有进行中的事项");
    const textList = page.locator("details.floor-text-list");
    await textList.locator("summary").click();
    await expect(textList.locator("li").first()).toContainText(former.title);
    await expect(page.locator(".decision-card")).toHaveCount(0);

    // 画面横幅与时间轴上的回放说明是同一个时刻（报告区间的起点不再被当成刻度的时间）
    const banner = (await page.locator(".replay-banner").innerText()).replace(/\s+/g, "");
    const status = (await page.locator(".timeline .replay-status").innerText()).replace(/\s+/g, "");
    expect(status, "时间轴上的回放说明与画面横幅是同一个时刻").toBe(banner);

    // 那一次读取是按前一个事项的范围、那个位置发出的，并且读到了
    const loopAt = requests.filter((row) => row.url.includes("/api/queries/project.loop")
      && row.url.includes(`work_item=${former.work_item_id}`)
      && row.url.includes(`at=${target.position}`));
    expect(loopAt.length, "按前一个事项的范围读那一刻").toBeGreaterThan(0);
    expect(loopAt.filter((row) => row.status !== 200), "那一刻读得到").toEqual([]);

    // 观测窗口：停留在回放位置上，页面期间不发出 4xx
    await page.waitForTimeout(REPLAY_WINDOW_MS);
    expect(requests.filter((row) => row.status >= 400 && row.status < 500), "窗口内没有 4xx")
      .toEqual([]);
    expect(await page.evaluate(() => window.location.hash)).toContain(`w=${former.work_item_id}`);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test.describe("宽屏（1920×1080）", () => {
  });
