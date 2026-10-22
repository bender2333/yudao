// 执行槽位页的端到端测试（工单 #727）：侧栏「系统」分组下有通往这一页的入口，
// 点它能到那一页；这一页显示 1 个槽位，副标题不再承诺并行。
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），不使用 mock。

import { expect, test } from "@playwright/test";
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

async function openClient(size: { width: number; height: number }): Promise<ClientApp> {
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  return client;
}

test("侧栏「系统」分组下有执行槽位这一页的入口，点它能到那一页", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  try {
    const system = client.page.locator(".y10-side-bottom.nav-group");
    const entry = system.getByRole("button", { name: "运行与执行槽位" });
    await expect(entry).toBeVisible();
    await entry.click();
    const page = client.page.locator(".y10-sys-runtime");
    await expect(page).toBeVisible();
    await expect(page.getByText("执行槽位", { exact: true })).toBeVisible();
  } finally {
    await client.close();
  }
});

test("这一页显示 1 个槽位，副标题不再承诺并行", async () => {
  const client = await openClient({ width: 1440, height: 900 });
  try {
    await client.page.locator(".y10-side-bottom.nav-group")
      .getByRole("button", { name: "运行与执行槽位" }).click();
    const slots = client.page.locator(".y10-slot-count");
    // 总数是 1（占用数按 system.status 的 running_runs，这里有几件事在跑就写几）
    await expect(slots).toContainText(/^\d+ \/ 1/);
    await expect(client.page.locator(".y10-sys-runtime"))
      .toContainText("当前一次只执行一个事项；不同项目并行在多项目并行完成以后开放");
    await expect(client.page.locator(".y10-sys-runtime"))
      .not.toContainText("不同项目并行时按队列顺序取得槽位");
  } finally {
    await client.close();
  }
});
