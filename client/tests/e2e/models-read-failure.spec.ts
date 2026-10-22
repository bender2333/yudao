// 模型管理页读取失败时的说法（工单 #776）：把 catalog 与 catalog.document 拦成 500，
// 走的正是与真实失败同一条路径（view-sync 的 onError → setState，工单 #728）。
// 核对：目录读不出来时页面写失败提示，不停在「正在读取目录…」；
// 目录文档读不出来时编辑器说明读不出来，并且不让在空文档上按保存。
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），不使用 mock。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

let backend: Backend;

// 后端启动要等 git 子进程（#214），这个会合点单独放宽，与各条测试自己的时限无关
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

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
async function openWithFailingQueries(queries: string[]): Promise<ClientApp> {
  return startClient(backend, { width: 1440, height: 900 }, {
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

async function openModels(client: ClientApp): Promise<void> {
  await client.page.evaluate(() => {
    window.location.hash = "#/sys/models";
  });
}

test("目录读不出来时：页面写「读取失败」，不停在「正在读取目录…」", async () => {
  const client = await openWithFailingQueries(["catalog"]);
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await openModels(client);
    await expect(page.getByText("读取失败").first()).toBeVisible();
    // 服务端给的原文按原文带出
    await expect(page.getByText("Internal Server Error").first()).toBeVisible();
    await expect(page.locator("main.content")).not.toContainText("正在读取目录…");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("目录文档读不出来时：编辑器说明读不出来，并且不让保存空文档", async () => {
  const client = await openWithFailingQueries(["catalog.document"]);
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await openModels(client);
    // 目录本身读得出来：页面正常显示
    await expect(page.getByTestId("edit-json")).toBeVisible();
    await page.getByTestId("edit-json").click();
    const dialog = page.getByRole("dialog", { name: "编辑 JSON" });
    await expect(dialog).toBeVisible();
    // 编辑器说明读不出来，不是一份空文档
    await expect(dialog.getByText("读取失败").first()).toBeVisible();
    await expect(dialog.getByText("Internal Server Error").first()).toBeVisible();
    // 文本框是空的：按保存会把目录写成空的，所以不让保存
    await expect(dialog.locator("textarea.json-editor")).toHaveValue("");
    await expect(dialog.getByRole("button", { name: "保存" })).toBeDisabled();
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
