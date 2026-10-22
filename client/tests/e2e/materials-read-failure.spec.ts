// 资料页读原文与交付文件：读不出来与「本来就没有」分开说（工单 #714）。
// 把 event.detail 与 delivery.file 拦成 500，走的是与真实失败同一条路径
// （view-sync 的 onError → setState，工单 #728）。
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），不使用 mock。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const SAMPLE = "示例项目";
const DELIVERY_FILE = "src/echo.py";

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

async function fetchQuery<T>(page: Page, name: string): Promise<T> {
  return page.evaluate(
    async ({ address, query }) => {
      const response = await fetch(`${address}/api/queries/${query}`);
      return (await response.json()) as QueryEnvelope<unknown>;
    },
    { address: backend.address, query: name },
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

async function openMaterialsWithFailingReads(size: { width: number; height: number }): Promise<ClientApp> {
  return startClient(backend, size, {
    intercept: async (page: Page) => {
      for (const query of ["event.detail", "delivery.file"]) {
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

test("读原文与交付文件失败时：页面写「读取失败」，不写「这一版没有留下原文」", async () => {
  const client = await openMaterialsWithFailingReads({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const id = await projectId(page, SAMPLE);
    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${id}/materials`);
    await expect(page.locator(".tabbar .tab").first()).toBeVisible();

    // PRD 的「查看原文」：读不出来时写「读取失败」
    const prd = page.locator("section.card")
      .filter({ has: page.getByRole("heading", { name: "PRD", exact: true }) }).first();
    await prd.getByRole("button", { name: "查看原文" }).first().click();
    const original = page.locator("div.card").filter({ has: page.getByRole("heading", { name: "合同原文", exact: true }) });
    await expect(original.getByText("读取失败")).toBeVisible();
    await expect(original).not.toContainText("这一版没有留下原文");

    // 交付文件的「查看内容」：读不出来时写「读取失败」，展开框不再是空白
    const delivery = page.locator("section.card")
      .filter({ has: page.getByRole("heading", { name: "交付", exact: true }) }).first();
    await delivery.getByRole("button", { name: "查看内容" }).first().click();
    const viewer = page.locator("div.card").filter({ has: page.getByRole("heading", { name: `交付文件 ${DELIVERY_FILE}`, exact: true }) });
    await expect(viewer.getByText("读取失败")).toBeVisible();
    await expect(viewer.locator("pre.raw")).toHaveCount(0);

    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
