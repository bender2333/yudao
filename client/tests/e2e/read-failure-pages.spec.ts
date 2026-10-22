// 项目页面读取失败时说「读不出来」（工单 #775）：逐页把查询拦成 500，
// 走的正是与真实失败同一条路径（view-sync 的 onError → setState，工单 #728）。
// 核对每一页看得出这次读取失败了：不写「没有内容」，也不留一片空白。
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），不使用 mock。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const SAMPLE = "示例项目";

let backend: Backend;

// 后端启动要等 git 子进程（#214），这个会合点单独放宽，与各条测试自己的时限无关
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

type QueryEnvelope<T> = { data?: T };

async function fetchQuery<T>(page: Page, name: string, params: Record<string, string> = {}): Promise<T> {
  const search = new URLSearchParams(params);
  return page.evaluate(
    async ({ address, query, qs }) => {
      const response = await fetch(`${address}/api/queries/${query}?${qs}`);
      return (await response.json()) as QueryEnvelope<unknown>;
    },
    { address: backend.address, query: name, qs: search.toString() },
  ).then((envelope) => {
    if (envelope.data === undefined) {
      throw new Error(`查询 ${name} 没有返回数据`);
    }
    return envelope.data as T;
  });
}

// 项目标识按名称取，不写死：前面的用例可能改过项目名
async function projectId(page: Page, name: string): Promise<string> {
  const data = await fetchQuery<{ projects: { name: string; project_id: string }[] }>(page, "projects.list");
  const row = data.projects.find((project) => project.name === name);
  if (row === undefined) {
    throw new Error(`projects.list 里没有项目 ${name}`);
  }
  return row.project_id;
}

// 事项标识：恢复页与部门工作间都要事项
async function workItemId(page: Page, project: string): Promise<string> {
  const data = await fetchQuery<{ work_items: { work_item_id: string }[] }>(
    page, "project.overview", { project_id: project },
  );
  const row = data.work_items[0];
  if (row === undefined) {
    throw new Error(`project.overview 里没有事项（项目 ${project}）`);
  }
  return row.work_item_id;
}

// 失败是这一条用例故意造出来的，浏览器对非 2xx 响应自己记的那条控制台消息不算应用的错误
function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

// 把给定的查询拦成 500；走的正是与真实失败同一条路径
async function openWithFailingQueries(
  queries: string[],
  size: { width: number; height: number } = { width: 1440, height: 900 },
): Promise<ClientApp> {
  return startClient(backend, size, {
    intercept: async (page: Page) => {
      for (const query of queries) {
        await page.route(`**/api/queries/${query}*`, async (route) => {
          await route.fulfill({
            status: 500,
            contentType: "text/plain",
            body: "Internal Server Error",
          });
        });
      }
    },
  });
}

// 页面正文：读不出来时不能是一片空白
async function bodyText(page: Page): Promise<string> {
  return page.locator("main.content").innerText();
}

test("概览页读不出来时：写「读取失败」，不留一片空白", async () => {
  const client = await openWithFailingQueries(["project.overview"]);
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(page, SAMPLE);
    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${id}/overview`);
    await expect(page.getByText("读取失败").first()).toBeVisible();
    // 服务端给的原文按原文带出
    await expect(page.getByText("Internal Server Error").first()).toBeVisible();
    const text = await bodyText(page);
    expect(text.trim().length).toBeGreaterThan(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("概览页的输入记录与流转记录读不出来时：写「读取失败」，不写「没有输入记录」与「项目还没有流转记录」", async () => {
  const client = await openWithFailingQueries(["work_item.inputs", "project.flow"]);
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(page, SAMPLE);
    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${id}/overview`);
    await expect(page.getByText("读取失败").first()).toBeVisible();
    await expect(page.locator("main.content")).not.toContainText("没有输入记录");
    await expect(page.locator("main.content")).not.toContainText("项目还没有流转记录");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("部门工作间读不出来时：写「读取失败」，不留一片空白", async () => {
  const client = await openWithFailingQueries(["department.workspace"]);
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(page, SAMPLE);
    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${id}/dept/engineering`);
    await expect(page.getByText("读取失败").first()).toBeVisible();
    const text = await bodyText(page);
    expect(text.trim().length).toBeGreaterThan(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("部门工作间的动作与回执读不出来时：写「读取失败」，不写「这次运行没有记录动作」", async () => {
  const client = await openWithFailingQueries(["run.actions"]);
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(page, SAMPLE);
    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${id}/dept/engineering`);
    await expect(page.getByText("读取失败").first()).toBeVisible();
    await expect(page.locator("main.content")).not.toContainText("这次运行没有记录动作");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("观测页的用量统计读不出来时：写「读取失败」，不安静地少一句数字", async () => {
  const client = await openWithFailingQueries(["project.usage"]);
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(page, SAMPLE);
    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${id}/observe`);
    // 用量统计在第二个页签上：先切过去
    await page.getByRole("tab", { name: "用量统计" }).click();
    await expect(page.getByText("读取失败").first()).toBeVisible();
    // 总数读不出来时说读不出来，不安静地少一句「共 N 次模型请求」
    await expect(page.getByText(/总数读不出来/).first()).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("设置页读不出来时：写「读取失败」，不留一片空白", async () => {
  const client = await openWithFailingQueries(["project.settings"]);
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(page, SAMPLE);
    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${id}/settings`);
    await expect(page.getByText("读取失败").first()).toBeVisible();
    const text = await bodyText(page);
    expect(text.trim().length).toBeGreaterThan(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("恢复页读不出来时：写「读取失败」，不写「这个项目里没有这个事项」", async () => {
  const client = await openWithFailingQueries(["project.loop", "run.recovery"]);
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(page, SAMPLE);
    const item = await workItemId(page, id);
    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${id}/w/${item}/recovery`);
    await expect(page.getByText("读取失败").first()).toBeVisible();
    await expect(page.locator("main.content")).not.toContainText("这个项目里没有这个事项");
    const text = await bodyText(page);
    expect(text.trim().length).toBeGreaterThan(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
