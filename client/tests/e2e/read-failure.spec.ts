// 读取失败在页面上要说「读不出来」，不说「本来就没有内容」（工单 #728）：
// 把 projects.list 拦成 500，走的是与真实失败同一条路径（view-sync 的 onError → setState）。
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），不使用 mock；
// 拦的是浏览器这一侧的请求，不是替身接口。

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

async function openWithFailingProjects(size: { width: number; height: number }): Promise<ClientApp> {
  return startClient(backend, size, {
    intercept: async (page: Page) => {
      await page.route("**/api/queries/projects.list*", async (route) => {
        await route.fulfill({
          status: 500,
          contentType: "text/plain",
          body: "Internal Server Error",
        });
      });
    },
  });
}

test("项目列表读不出来时：侧栏与首页写「读取失败」，不写「没有符合的项目」与「还没有项目」", async () => {
  const client = await openWithFailingProjects({ width: 1440, height: 900 });
  try {
    const sidebar = client.page.locator(".y10-sidebar");
    await expect(sidebar.getByText("读取失败")).toBeVisible();
    await expect(sidebar).not.toContainText("没有符合的项目");

    const building = client.page.locator("section.card")
      .filter({ has: client.page.getByRole("heading", { name: "全部项目与机器", exact: true }) });
    await expect(building.getByText("读取失败")).toBeVisible();
    await expect(building).not.toContainText("还没有项目");

    const projects = client.page.locator("section.card")
      .filter({ has: client.page.getByRole("heading", { name: "项目", exact: true }) });
    await expect(projects.getByText("读取失败")).toBeVisible();
  } finally {
    await client.close();
  }
});

test("项目列表读得出来时：侧栏照常列出项目，不写「读取失败」", async () => {
  const client = await startClient(backend, { width: 1440, height: 900 });
  try {
    // 后端预置了四个项目：列表读得出来
    const sidebar = client.page.locator(".y10-sidebar");
    await expect(sidebar.getByText("示例项目")).toBeVisible();
    await expect(sidebar).not.toContainText("读取失败");
  } finally {
    await client.close();
  }
});
