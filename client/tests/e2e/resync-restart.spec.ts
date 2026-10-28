// 服务重启以后页面自己重新同步（工单 #1159，应用层与接口层设计说明第 6.1 节）：
// 模型管理页开着，服务停掉以后用同一个端口与数据目录再起一次，页面不刷新。
// 事件流重连时核对本次启动的身份（boot_id）：换了服务就重新读取能力清单并重新查询已打开的视图，
// 于是页面显示的是重启以后的凭据状态（内存里的 Key 只在进程里，重启以后没有了）。
// 重启的做法与断线恢复的用例相同（shell.spec.ts）：同一个端口、同一个数据目录再起一次后端。

import { expect, test } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

// 上游凭据：测试经命令设置在内存里（persist=false），服务重启以后这份内存状态不存在
const KEY = "sk-e2e-restart-4c19d2";

// 模型管理页上这条凭据的引用：预置的「OpenCode Go」连接用它
const REF = "OPENCODE_GO_KEY";

// 凭据表里这一条引用所在的行（预置目录里只有一条用它）
function credentialRow(client: ClientApp) {
  return client.page.locator(".y10-grid-cred tbody tr", { hasText: REF });
}

// 给已经保存的连接设置内存里的 Key：走真实命令与真实凭据链，页面只看到状态
async function setKey(client: ClientApp, backend: Backend): Promise<void> {
  const status = await client.page.evaluate(async (payload: { address: string; ref: string; key: string }) => {
    const listed = await (await fetch(`${payload.address}/api/queries/catalog`)).json();
    // 凭据版本按引用分别记；找到引用这个凭据的连接，取它的版本
    const provider = listed.data.providers.find((item: { credential_ref: string }) => item.credential_ref === payload.ref);
    const response = await fetch(`${payload.address}/api/commands/credential.set`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command_id: crypto.randomUUID(),
        base_version: provider.credential.version,
        ref: payload.ref,
        secret: payload.key,
        persist: false,
      }),
    });
    return response.status;
  }, { address: backend.address, ref: REF, key: KEY });
  expect(status).toBe(200);
}

test("服务重启以后页面不刷新，凭据来源自己变成重启以后的值", async () => {
  test.setTimeout(300_000);
  // 这个用例自己起服务：重启要真的停掉它，再用同一端口与数据目录起回来
  const own = await startBackend();
  const client = await startClient(own, { width: 1440, height: 900 });
  let again: Backend | null = null;
  try {
    await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
    await client.page.getByRole("button", { name: "模型管理", exact: true }).click();
    await expect(client.page.locator(".path")).toHaveText("模型管理");
    // 预置时把内存里的 Key 清掉了：页面从「凭据缺失」开始
    await expect(credentialRow(client)).toContainText("缺失，请填写 API Key");

    // 设置内存里的 Key（不落盘）：页面跟着显示「来源 内存」
    await setKey(client, own);
    await expect(credentialRow(client)).toContainText("已配置，来源 内存");

    // 停服务：窗口整体变灰，页面留在模型管理页
    await own.stop();
    await expect(client.page.locator("body")).toHaveClass(/is-disconnected/, { timeout: 60_000 });
    await expect(client.page.locator(".path")).toHaveText("模型管理");

    // 同一个端口与数据目录再起一次服务：内存里的 Key 与新进程的凭据版本都没有了
    again = await startBackend({ port: own.port, dataDir: own.dataDir });
    // 页面自动重新连上（没有刷新）：事件流重连时核对启动身份，身份变了就重新查询已打开的视图
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: 120_000 });
    await expect(client.page.locator("body")).not.toHaveClass(/is-disconnected/);
    // 凭据表显示的是重启以后的来源，而不是重启以前那一份「来源 内存」
    await expect(credentialRow(client)).toContainText("缺失，请填写 API Key", { timeout: 60_000 });
  } finally {
    await client.close();
    await again?.stop();
    await own.stop();
  }
});
