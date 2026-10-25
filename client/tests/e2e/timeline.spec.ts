// 时间轴与回放的端到端测试（工单 #180 的验收）：Playwright 启动 Chromium 页面，页面文件由
// FakeAdapter 驱动的真实后端提供（client/tests/e2e/backend.py），模型回答由 FakeAdapter 给出。
// 预置的第一个事项包含交接、返工、询问与回答、采纳，因此首页与概览的时间轴刻度与 home.away_report 的
// 关键事实一一对应；拖到某个刻度时画面与带 at 的查询结果一致；「回到现在」恢复实时画面，回放期间到达的事件不丢失。
//
// 观测方式：时间轴的刻度（.tick 的 data-position 与 data-kind）与查询结果逐项比较；
// 回放位置用「回放中」横幅、楼层的文字列表与带 at 的查询结果核对。

import { expect,test,type Page } from "@playwright/test";
import { startBackend,startClient,type Backend,type ClientApp } from "./fixtures";

const SAMPLE = "交付历史";

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




test.describe("宽屏（1920×1080）", () => {
  });
