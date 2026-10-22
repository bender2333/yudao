// 服务端以 422 拒绝一条命令时，页面上有一句能看懂的中文说明（工单 #740）：
// 清空「长期目标」保存以后，页面上看得见「这次请求被拒绝：「长期目标」不能为空……」，
// 不再是一个空的错误框（用户使用记录 U89：保存前页面上只有两个 [role=status]，
// 保存后多出第三个，class="error"，textContent 是空串）。
//
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），不使用 mock。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const SAMPLE = "示例项目";

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

// 浏览器为失败的资源请求自己记一条控制台消息：这一次命令被 422 拒绝就是这样的消息，
// 它不是应用的错误（应用的错误是 pageerror 与页面自己写的错误）
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

async function section(page: Page, heading: string) {
  return page.locator("section.card").filter({ has: page.getByRole("heading", { name: heading, exact: true }) }).first();
}

test("服务端以 422 拒绝一条命令时，页面上写明是哪个字段、要求是什么（工单 #740）", async () => {
  test.setTimeout(180_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await expect(page.locator(".brand .y10-brand-name")).toContainText("Yudao");
    const project = await page.evaluate(async (name) => {
      const response = await fetch("/api/queries/projects.list");
      const envelope = await response.json() as { data?: { projects: { name: string; project_id: string }[] } };
      return envelope.data?.projects.find((item) => item.name === name)?.project_id ?? "";
    }, SAMPLE);
    expect(project).not.toBe("");
    await page.evaluate((id) => {
      window.location.hash = `#/p/${id}/settings`;
    }, project);
    await expect(page.locator(".tabbar .tab").first()).toBeVisible();

    const basics = await section(page, "基本信息");
    await basics.getByRole("button", { name: "修改名称与长期目标" }).click();
    // 清空长期目标：合同的 Text 要求至少一个非空白字符，服务端按 422 拒绝
    await basics.getByLabel("长期目标").fill("");
    await basics.getByRole("button", { name: "保存长期目标" }).click();

    // 页面上有一句中文说明，写明是哪个字段、要求是什么
    const feedback = basics.locator('p.error[role="status"]');
    await expect(feedback).toContainText("这次请求被拒绝");
    await expect(feedback).toContainText("长期目标");
    await expect(feedback).toContainText("不能为空");
    // 不出现字段路径与英文机器短语
    await expect(feedback).not.toContainText("goal");
    await expect(feedback).not.toContainText("String should have");
    // 那一段不是空的：早先这里是 <p class="error" role="status"></p>
    const text = (await feedback.innerText()).trim();
    expect(text.length).toBeGreaterThan(0);
    expect(text).not.toBe("：");
    // 页面没有脚本错误
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
