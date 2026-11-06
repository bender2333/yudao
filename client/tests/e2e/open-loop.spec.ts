// 开环完成与放行在页面上分开写（工单 #1421；形态与核验角色设计说明「开环完成」；画面与播放设计说明
// docs/design/visualization.md「开环完成与放行」；应用层与接口层设计说明「事项看板在页面上的显示」）：
//   1. 一个事项以开环完成结束：事项卡/详情写「开环完成」，看板进「开环完成」一列，「已放行」一列里没有它；
//   2. 一个事项以放行结束：仍在「已放行」一组；事项统计把两处分开数（放行待采纳 1、开环完成 1）；
//   3. 离开期间的报告把它列在「开环完成」一项，「完成与放行的事项」里没有它，开环完成一项的文字里
//      没有「放行」二字，也没有 open_loop 这个内部标识；
//   4. 概览的「成果挂起」计数数进一件 held 事项（并入的 #1185）。
//
// 后端种子（--script openloop）给两个项目：「开环完成与放行」里两件事项都停在「放行待采纳」这一个状态上、
// 只有结束原因不同；「成果挂起」里后一件放行时基线已变，结算写成 adoption_held。
// 只读页面：统计行、看板列与卡片、当前事项的状态行、顶栏的范围选择与离开期间的报告。

import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { startBackend, startClient, type Backend } from "./fixtures";

const PROJECT = "开环完成与放行";
const HELD_PROJECT = "成果挂起";
const OPEN_LOOP_ITEM = "没有核验角色，交了完成就结束";
const RELEASED_ITEM = "经过质检放行";
const SHOTS = join(process.cwd(), "..", ".tmp", "1421-shots");

async function shot(page: import("@playwright/test").Page, name: string): Promise<void> {
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
}

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

type OverviewItem = {
  work_item_id: string;
  title: string;
  text: string;
  status: string;
  stop_reason: string | null;
};

type Overview = {
  work_items: OverviewItem[];
  stats: { total: number; released_unsettled: number; open_loop: number; held: number; adopted: number };
};

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend({ script: "openloop" });
});

test.afterAll(async () => {
  await backend?.stop();
});

async function fetchQuery<T>(page: import("@playwright/test").Page, name: string,
                             params: Record<string, string | number> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.set(key, String(value));
  }
  const suffix = search.toString();
  return page.evaluate(
    async ({ address, query, qs }) => {
      const response = await fetch(`${address}/api/queries/${query}${qs ? `?${qs}` : ""}`);
      return (await response.json()) as QueryEnvelope<unknown>;
    },
    { address: backend.address, query: name, qs: suffix },
  ).then((envelope) => {
    if (envelope.data === undefined) {
      throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
    }
    return envelope.data as T;
  });
}

async function projectId(page: import("@playwright/test").Page, name: string): Promise<string> {
  const data = await fetchQuery<{ projects: { name: string; project_id: string }[] }>(page, "projects.list");
  const row = data.projects.find((project) => project.name === name);
  if (row === undefined) {
    throw new Error(`projects.list 里没有项目 ${name}`);
  }
  return row.project_id;
}

function section(page: import("@playwright/test").Page, heading: string) {
  return page.locator("section.card").filter({ has: page.getByRole("heading", { name: heading, exact: true }) }).first();
}

async function gotoProject(page: import("@playwright/test").Page, id: string, workItem?: string): Promise<void> {
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, `#/p/${id}/overview${workItem === undefined ? "" : `?w=${workItem}`}`);
  await expect(page.locator(".tabbar .tab").first()).toBeVisible();
}

async function statsLine(page: import("@playwright/test").Page) {
  return (await section(page, "项目摘要")).locator(".line").filter({ hasText: "事项统计" }).first();
}

test("事项卡与看板：开环完成与已放行分开写，统计把两处分开数", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const page = client.page;
  try {
    const id = await projectId(page, PROJECT);
    // 两件事项在项目流里都停在「放行待采纳」这一个状态上：只有结束原因不同（工单 #1421 的现状）
    const overview = await fetchQuery<Overview>(page, "project.overview", { project_id: id });
    const openItem = overview.work_items.find((item) => item.text === OPEN_LOOP_ITEM);
    const releasedItem = overview.work_items.find((item) => item.text === RELEASED_ITEM);
    expect(openItem?.status).toBe("released_unsettled");
    expect(openItem?.stop_reason).toBe("open_loop");
    expect(releasedItem?.status).toBe("released_unsettled");
    expect(releasedItem?.stop_reason).toBe("released");

    await gotoProject(page, id);
    // 统计行：开环完成单列，放行待采纳不再包含它；两处各一件，加起来是「共 2」
    await expect(await statsLine(page)).toContainText(
      "共 2：进行中 0、排队中 0、已采纳 0、放行待采纳 1、开环完成 1、成果挂起 0、已停止 0");

    // 看板：「已放行」与「开环完成」各一列，两件事项各在一列里，互不混入
    const board = await section(page, "事项看板");
    const columns = board.locator(".y10-ov-board-col");
    const releasedColumn = columns.filter({ has: page.getByRole("heading", { name: /^已放行（1）$/ }) });
    const openLoopColumn = columns.filter({ has: page.getByRole("heading", { name: /^开环完成（1）$/ }) });
    await expect(releasedColumn.locator(".board-card")).toContainText(RELEASED_ITEM);
    await expect(releasedColumn).not.toContainText(OPEN_LOOP_ITEM);
    await expect(openLoopColumn.locator(".board-card")).toContainText(OPEN_LOOP_ITEM);
    await expect(openLoopColumn).not.toContainText(RELEASED_ITEM);
    // 开环完成的事项写「开环完成」，不写「已放行」，也没有英文内部标识
    await expect(openLoopColumn.locator(".board-card")).toContainText("开环完成");
    await expect(openLoopColumn.locator(".board-card")).not.toContainText("已放行");
    await expect(openLoopColumn.locator(".board-card")).not.toContainText("open_loop");
    await shot(page, "01-board-open-loop-and-released");

    // 事项详情（选中这一件）：状态行写「开环完成」；顶栏的范围选择里同一件事项也写这一句
    await gotoProject(page, id, openItem?.work_item_id ?? "");
    const current = await section(page, "当前事项");
    const statusRow = current.locator(".line").filter({ hasText: "状态" }).first();
    await expect(statusRow).toContainText("开环完成");
    await expect(statusRow).not.toContainText("已放行");
    await expect(page.locator(".y10-scope select option").filter({ hasText: OPEN_LOOP_ITEM })).toContainText("开环完成");
    await shot(page, "02-open-loop-item-detail");
  } finally {
    await client.close();
  }
});

test("离开期间的报告：开环完成单列一项，文字里没有放行与 open_loop", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const page = client.page;
  try {
    await page.evaluate(() => {
      window.location.hash = "#/home";
    });
    await expect(page.getByRole("heading", { name: "离开期间的报告", exact: true })).toBeVisible();
    const report = await section(page, "离开期间的报告");
    const openLoop = report.locator(".report-item").filter({
      has: page.locator(".report-label", { hasText: /^开环完成$/ }),
    }).first();
    await expect(openLoop.locator(".report-label")).toHaveText("开环完成");
    await expect(openLoop.locator(".report-value")).toContainText("1");
    // 开环完成一项的文字里没有「放行」二字，也没有内部标识 open_loop
    await expect(openLoop).not.toContainText("放行");
    await expect(openLoop).not.toContainText("open_loop");
    // 展开来源事件：来源是事项的结束事件，说明也写开环完成
    await openLoop.locator(".report-head").click();
    await expect(openLoop.locator(".source-list")).toBeVisible();
    await expect(openLoop.locator(".source-list")).toContainText("开环完成");
    await expect(openLoop.locator(".source-list")).not.toContainText("放行");

    // 「完成与放行的事项」是另一项：种子里的三件放行/采纳事项，开环完成的那一件不在其中
    const released = report.locator(".report-item").filter({
      has: page.locator(".report-label", { hasText: /^完成与放行的事项$/ }),
    }).first();
    await expect(released.locator(".report-value")).toContainText("3");
    await expect(released).not.toContainText("开环完成");
    await released.locator(".report-head").click();
    await expect(released.locator(".source-list")).toBeVisible();
    await expect(released.locator(".source-list")).not.toContainText("开环完成");
    await shot(page, "03-away-report-open-loop");
  } finally {
    await client.close();
  }
});

test("概览的「成果挂起」计数：一件基线变更以后放行的事项", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const page = client.page;
  try {
    const id = await projectId(page, HELD_PROJECT);
    await gotoProject(page, id);
    const stats = await statsLine(page);
    await expect(stats).toContainText("已采纳 1");
    await expect(stats).toContainText("成果挂起 1");
    // 看板上这件挂起的事项在排队中，卡片写它自己的状态
    const board = await section(page, "事项看板");
    const queue = board.locator(".y10-ov-board-col").filter({
      has: page.getByRole("heading", { name: /^排队中（1）$/ }),
    });
    await expect(queue).toContainText("成果已挂起");
    await shot(page, "04-held-stats");
  } finally {
    await client.close();
  }
});
