// 页面的部门从事实来（工单 #1457；项目的组织设计说明「页面跟着级别伸缩」；形态与核验角色设计说明
// 「形态随事项冻结」）：
//   1. 默认三部门的项目：页签与看板与现在一样，三个部门都在；
//   2. 换成只有一个角色的组织以后：页签与看板只看得到那一个部门，部门页的默认部门是它；
//   3. 中途换了形态：老事项按它冻结的组织显示部门，新事项按新的；
//   4. 页面上没有写死的三个部门的名字（只在当前组织的部门里出现）。
//
// 后端种子（--script organization）给一个三部门的项目，没有事项；用例在页面上经命令建事项，
// 模型回答由假模型慢慢流式返回，部门状态因此在检查的这段时间里一直在进行中。
// 只读页面（与画面测试不同，不读画布）：页签、看板列、部门页的标题与部门状态行。

import { expect, test } from "@playwright/test";
import { startBackend, startClient, type Backend } from "./fixtures";

const PROJECT = "页面的部门";
const OLD_ITEM = "换形态之前的事项";
const NEW_ITEM = "换形态之后的事项";
const SINGLE_ROLE_FORM = "single_role";

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend({ script: "organization" });
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

type CommandResult = { status: number; body: { reason?: string; message?: string; refs?: Record<string, string> } };

async function sendCommand(page: import("@playwright/test").Page, name: string,
                           request: Record<string, unknown>): Promise<CommandResult> {
  return page.evaluate(
    async ({ address, command, payload }) => {
      const response = await fetch(`${address}/api/commands/${command}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command_id: crypto.randomUUID(), ...payload }),
      });
      return { status: response.status, body: (await response.json()) as Record<string, unknown> };
    },
    { address: backend.address, command: name, payload: request },
  ).then((result) => result as unknown as CommandResult);
}

async function expectAccepted(page: import("@playwright/test").Page, name: string,
                              request: Record<string, unknown>): Promise<void> {
  const result = await sendCommand(page, name, request);
  if (result.status !== 200) {
    throw new Error(`命令 ${name} 被服务端拒绝：HTTP ${result.status} ${result.body.reason ?? ""} ${result.body.message ?? ""}`);
  }
}

async function projectId(page: import("@playwright/test").Page, name: string): Promise<string> {
  const data = await fetchQuery<{ projects: { name: string; project_id: string }[] }>(page, "projects.list");
  const row = data.projects.find((project) => project.name === name);
  if (row === undefined) {
    throw new Error(`projects.list 里没有项目 ${name}`);
  }
  return row.project_id;
}

type Overview = { work_items: { work_item_id: string; text: string; status: string }[] };

async function itemOf(page: import("@playwright/test").Page, id: string, text: string) {
  const data = await fetchQuery<Overview>(page, "project.overview", { project_id: id });
  return data.work_items.find((item) => item.text === text) ?? null;
}

async function waitUntil(check: () => Promise<boolean>, description: string, timeoutMs = 90_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) {
      return;
    }
    if (Date.now() > deadline) {
      throw new Error(`等待超时：${description}`);
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}

async function goto(page: import("@playwright/test").Page, hash: string): Promise<void> {
  await page.evaluate((target) => {
    window.location.hash = target;
  }, hash);
  await expect(page.locator(".tabbar .tab").first()).toBeVisible();
}

async function tabTexts(page: import("@playwright/test").Page): Promise<string[]> {
  return page.locator(".tabbar .tab").allTextContents();
}

// 看板的部门列：固定四组（排队中、已放行、已采纳、已停止）之外的那些列，去掉计数
const FIXED_BOARD_TITLES = ["排队中", "已放行", "已采纳", "已停止"];

async function boardTitles(page: import("@playwright/test").Page): Promise<string[]> {
  const titles = await page.locator(".y10-ov-board-col h3").allTextContents();
  return titles.map((title) => title.replace(/（\d+）$/, ""))
    .filter((title) => !FIXED_BOARD_TITLES.includes(title));
}

async function bodyText(page: import("@playwright/test").Page): Promise<string> {
  return page.evaluate(() => document.body.innerText);
}

test("页面的部门取自事实：默认三部门照旧，换成一个角色直做只看得到工程，老事项按冻结的组织", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const page = client.page;
  try {
    await expect(page.locator(".brand .y10-brand-name")).toContainText("Yudao");
    await waitUntil(async () => (await page.locator(".project-entry").count()) >= 1, "侧栏出现预置项目");
    const id = await projectId(page, PROJECT);

    // —— 1. 默认三部门：页签、看板列与现在一样
    await goto(page, `#/p/${id}/overview`);
    await waitUntil(async () => (await tabTexts(page)).includes("产品"), "页签出现产品");
    expect(await tabTexts(page)).toEqual(["概览", "产品", "工程", "质检", "资料", "观测", "设置"]);
    expect(await boardTitles(page)).toEqual([]); // 还没有事项：看板显示空态

    // —— 2. 老事项按它冻结的组织显示部门（三部门）：产品慢慢流式返回，检查时事项还在进行中
    await expectAccepted(page, "work_item.create", { project_id: id, text: OLD_ITEM });
    await waitUntil(async () => (await itemOf(page, id, OLD_ITEM))?.status === "in_progress", "老事项开始工作");
    const oldItem = await itemOf(page, id, OLD_ITEM);
    expect(oldItem).not.toBeNull();
    await waitUntil(async () => (await boardTitles(page)).length === 3, "看板出现三个部门列");
    expect(await boardTitles(page)).toEqual(["产品", "工程", "质检"]);
    // 部门页的默认部门：地址里没有写部门时取现在组织里的第一个部门（产品）
    await goto(page, `#/p/${id}/dept`);
    await expect(page.locator("#ws-head-block h1")).toContainText("产品部门");
    await goto(page, `#/p/${id}/dept/product?w=${oldItem?.work_item_id ?? ""}`);
    await expect(page.locator("#ws-head-block h1")).toContainText("产品部门");
    const oldLine = await page.locator(".department-line").innerText();
    expect(oldLine).toContain("产品");
    expect(oldLine).toContain("工程");
    expect(oldLine).toContain("质检");

    // 等这一轮慢慢流式返回结束、事项停下（执行槽位空出来，才能换形态再建事项）
    await waitUntil(async () => (await itemOf(page, id, OLD_ITEM))?.status !== "in_progress", "老事项停下",
      120_000);

    // —— 3. 换成只有一个部门的组织：页签与看板只看得到工程，默认部门也是工程
    const organization = await fetchQuery<{ version: string | null }>(page, "project.organization", { project_id: id });
    await expectAccepted(page, "organization.adopt", {
      project_id: id, form: SINGLE_ROLE_FORM, changes: {}, reason: "一个角色直做",
      base_version: organization.version,
    });
    await goto(page, `#/p/${id}/overview`);
    await waitUntil(async () => (await tabTexts(page)).length === 5, "页签跟着现在的组织收成一个部门");
    expect(await tabTexts(page)).toEqual(["概览", "工程", "资料", "观测", "设置"]);
    await goto(page, `#/p/${id}/dept`);
    await expect(page.locator("#ws-head-block h1")).toContainText("工程部门");

    // —— 4. 新事项按新的组织显示部门：部门状态行只有工程，没有产品、质检
    await goto(page, `#/p/${id}/overview`);
    await expectAccepted(page, "work_item.create", { project_id: id, text: NEW_ITEM });
    await waitUntil(async () => (await itemOf(page, id, NEW_ITEM))?.status === "in_progress", "新事项开始工作");
    const newItem = await itemOf(page, id, NEW_ITEM);
    await waitUntil(async () => (await boardTitles(page)).length === 1, "看板只有一个部门列");
    expect(await boardTitles(page)).toEqual(["工程"]);
    await goto(page, `#/p/${id}/dept/engineering?w=${newItem?.work_item_id ?? ""}`);
    await expect(page.locator("#ws-head-block h1")).toContainText("工程部门");
    const newLine = await page.locator(".department-line").innerText();
    expect(newLine).toContain("工程");
    expect(newLine).not.toContain("产品");
    expect(newLine).not.toContain("质检");
    const text = await bodyText(page);
    // 页面上没有另外两个部门：不是出现「产品」「质检」这两个字（部门 Prompt 里会说「产品要求」），
    // 而是没有「产品部门」「质检部门」这样的部门入口与标题
    expect(text).not.toContain("产品部门");
    expect(text).not.toContain("质检部门");
  } finally {
    await client.close();
  }
});
