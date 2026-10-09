// 局域网访问方式的访问令牌（工单 #348，设计说明第 6.3 节）：页面由后端以局域网访问方式提供，
// 在 Playwright Chromium 中经局域网地址打开。页面文件不需要令牌，接口需要 Authorization: Bearer <令牌>：
// 没有令牌时页面显示填写令牌的表单，填写以后查询、命令与事件流照常工作，令牌只出现在请求头里；
// 令牌保存在这个浏览器里，刷新页面不用再次填写；输入错误的令牌被服务按 401 拒绝，页面回到表单。
import { expect, test } from "@playwright/test";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { openPage, repoRoot, startBackend, type Backend, type ClientApp } from "./fixtures";

const WRONG_TOKEN = "0".repeat(64);

test("局域网访问方式：填写令牌以后查询、命令与事件流照常工作，令牌只出现在请求头里", async () => {
  test.setTimeout(180_000);
  const backend: Backend = await startBackend({ tokenName: "客厅的电脑" });
  expect(backend.lanAddress).not.toBe("");
  const client: ClientApp = await openPage(`${backend.lanAddress}/`, { width: 1440, height: 900 });
  const page = client.page;
  const pageerrors: string[] = [];
  page.on("pageerror", (error) => pageerrors.push(error.message));
  // 记录每一个接口应答带的 Authorization 与状态：令牌只在请求头里，不在地址里
  const calls: { url: string; authorization: string; status: number }[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/")) {
      calls.push({ url: response.url(), status: response.status(),
        authorization: response.request().headers()["authorization"] ?? "" });
    }
  });
  try {
    // 没有令牌：页面文件打开，页面显示填写令牌的表单，这个浏览器里还没有令牌
    await expect(page.locator("#access-token")).toBeVisible();
    await expect(page.locator("h1")).toHaveText("填写访问令牌");
    expect(await page.evaluate(() => window.localStorage.getItem("yudao.access-token"))).toBeNull();

    // 填错令牌：令牌按第 6.3 节放在请求头里送出，服务拒绝它，页面回到表单，
    // 被拒绝的令牌不写进这个浏览器；令牌不出现在地址里
    await page.locator("#access-token").fill(WRONG_TOKEN);
    await page.locator("button[type=submit]").click();
    await expect(page.locator("#access-token")).toBeVisible();
    expect(calls.length).toBeGreaterThan(0);
    expect(calls.at(-1)!.authorization).toBe(`Bearer ${WRONG_TOKEN}`);
    expect(calls.at(-1)!.url).not.toContain(WRONG_TOKEN);
    expect(await page.evaluate(() => window.localStorage.getItem("yudao.access-token"))).toBeNull();

    // 填对令牌：页面按接口合同照常工作
    await page.locator("#access-token").fill(backend.token);
    await page.locator("button[type=submit]").click();
    await expect(page.locator(".brand .y9-brand-name")).toContainText("Yudao");
    await expect(page.locator(".connection")).toHaveText("已连接");
    await expect(page.locator("#access-token")).toHaveCount(0);

    // 命令通道也带令牌：从想法新建一个项目，走真实的命令通道
    await page.locator(".sidebar .nav-item", { hasText: "从想法新建" }).click();
    const form = page.locator("form.card").filter({ has: page.getByRole("heading", { name: "从想法新建项目" }) });
    await expect(form).toBeVisible();
    await form.getByLabel("项目名称").fill("局域网访问的项目");
    await form.getByLabel("长期目标").fill("经局域网地址访问服务");
    await form.getByRole("button", { name: "新建项目" }).click();
    await expect(page.locator(".project-entry").filter({ hasText: "局域网访问的项目" })).toBeVisible();
    await expect.poll(() => calls.filter((entry) => entry.authorization === `Bearer ${backend.token}`).length,
      { timeout: 30_000 }).toBeGreaterThanOrEqual(3);
    // 令牌在能力清单、查询、命令与事件流四条通道上都放到了请求头里
    const channels = new Set(calls.filter((entry) => entry.authorization === `Bearer ${backend.token}`)
      .map((entry) => entry.url.split("/api/")[1]!.split(/[/?]/)[0]));
    expect([...channels].sort()).toEqual(["capabilities", "commands", "events", "queries"]);
    for (const entry of calls) {
      expect(entry.url).not.toContain(backend.token);
    }

    // 令牌保存在这个浏览器里：刷新页面不再要令牌，也不显示表单
    await page.reload();
    await expect(page.locator(".brand .y9-brand-name")).toContainText("Yudao");
    await expect(page.locator("#access-token")).toHaveCount(0);
    expect(await page.evaluate(() => window.localStorage.getItem("yudao.access-token"))).toBe(backend.token);
    expect(pageerrors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});

test("撤销令牌以后，页面在下一次请求时被服务拒绝", async () => {
  test.setTimeout(180_000);
  const backend: Backend = await startBackend({ tokenName: "客厅的电脑" });
  const client: ClientApp = await openPage(`${backend.lanAddress}/`, { width: 1440, height: 900 });
  const page = client.page;
  const pageerrors: string[] = [];
  page.on("pageerror", (error) => pageerrors.push(error.message));
  try {
    await page.locator("#access-token").fill(backend.token);
    await page.locator("button[type=submit]").click();
    await expect(page.locator(".connection")).toHaveText("已连接");

    // 撤销以后刷新页面：令牌不再被接受，页面回到填写令牌的表单
    await revokeToken(backend);
    await page.reload();
    await expect(page.locator("#access-token")).toBeVisible();
    expect(pageerrors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});

async function revokeToken(backend: Backend): Promise<void> {
  // 经命令行撤销真实令牌：与建立令牌同一处在服务所在的机器上运行（第 6.3 节）
  await promisify(execFile)("uv", ["run", "python", "-m", "harness", "token", "revoke", "客厅的电脑",
    "--data-dir", backend.dataDir], { cwd: repoRoot });
}