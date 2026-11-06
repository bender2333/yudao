// 取回与 MCP 调用的显示（工单 #238 的验收）：Playwright 打开 Chromium，连接真实运行的后端
// （tests/e2e/backend.py 的 --script fetch，FakeAdapter 驱动；事件日志、工件与 MCP 服务器都是真实实现）。
//
// 种子：一个项目里一个走完三部门的事项。产品的第一轮同时取回本机 HTTP 服务上的一页（250 行纯文本）
// 并调用真实 stdio MCP 服务器（mcp__time__echo）；事项结束以后补写两条只看显示的动作：被拒绝的取回、
// 结果未知的 MCP 调用（写事件，理由见 backend.py 的 FETCH_DISPLAY_*）。
//
// 验收：部门工作间的步骤时间线里，取回与 MCP 调用各占一行，写类型、目标、状态（含被拒绝与结果未知）、
// 耗时与外部来源的入口；结果未知的一行写交还给模型的内容；点开外部来源按页阅读，来源、最终地址、
// 状态码与摘要值都在，翻页以后看到第二页；页面上没有英文内部标识；控制台错误为零。

import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { collectConsoleErrors, startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const PROJECT = "取回显示";
const EXPECTED_LINES = 250;

let backend: Backend;

test.beforeAll(async () => {
  // 真实 MCP 服务器要启动，启动到首行输出的用时在并发负载下可能较慢（同 step-timeline.spec.ts 的处理）
  test.setTimeout(300_000);
  backend = await startBackend({ script: "fetch" });
});

test.afterAll(async () => {
  await backend?.stop();
});

type ProjectRow = { name: string; project_id: string };

async function projectId(page: Page, name: string): Promise<string> {
  const rows = await page.evaluate(async (address) => {
    const response = await fetch(`${address}/api/queries/projects.list?include_archived=true`);
    const envelope = (await response.json()) as { data?: { projects: ProjectRow[] } };
    return envelope.data?.projects ?? [];
  }, backend.address);
  const found = rows.find((row) => row.name === name);
  if (found === undefined) {
    throw new Error(`projects.list 里没有项目 ${name}（现有：${rows.map((row) => row.name).join("、")}）`);
  }
  return found.project_id;
}

// 检查区（动作与回执那个页签所在的那张卡）里的动作行
function actionRows(page: Page) {
  return page.locator("section.card").filter({ has: page.getByRole("tab", { name: "动作与回执" }) })
    .locator(".y10-ws-act");
}

test("取回与 MCP 调用的显示：动作行、被拒绝与结果未知、外部来源按页阅读（1440×900）", async () => {
  test.setTimeout(300_000);
  const client: ClientApp = await startClient(backend, { width: 1440, height: 900 });
  const errors = collectConsoleErrors(client.page);
  const page = client.page;
  try {
    await expect(page.locator(".brand .y10-brand-name")).toContainText("Yudao");
    const id = await projectId(page, PROJECT);
    await page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${id}/dept/product`);
    await expect(page.locator(".tabbar .tab").first()).toBeVisible();

    // 产品的第一步里有四个动作行：取回成功、MCP 调用成功、取回被拒绝、MCP 调用结果未知
    await expect(actionRows(page)).toHaveCount(4, { timeout: 120_000 });

    // 取回与 MCP 调用各一行：类型、目标与状态；取回的目标是本机服务上的那一页
    const fetchRows = actionRows(page).filter({ hasText: "网络取回" });
    await expect(fetchRows).toHaveCount(2);
    const fetchDone = fetchRows.filter({ hasText: "已完成" });
    await expect(fetchDone).toHaveCount(1);
    await expect(fetchDone).toContainText("/fetch-display");
    await expect(fetchDone).toContainText("耗时");
    await expect(fetchDone.getByRole("button", { name: "查看外部来源" })).toBeVisible();

    const mcpRows = actionRows(page).filter({ hasText: "MCP 调用" });
    await expect(mcpRows).toHaveCount(2);
    const mcpDone = mcpRows.filter({ hasText: "已完成" });
    await expect(mcpDone).toHaveCount(1);
    await expect(mcpDone).toContainText("time · echo");
    await expect(mcpDone.getByRole("button", { name: "查看外部来源" })).toBeVisible();

    // 被拒绝的取回：状态词是「被拒绝」，写拒绝原因，没有外部来源可看
    const refused = fetchRows.filter({ hasText: "被拒绝" });
    await expect(refused).toHaveCount(1);
    await expect(refused).toContainText("拒绝原因");
    await expect(refused).toContainText("地址指向 Yudao 自己的服务，拒绝取回");
    await expect(refused.getByRole("button", { name: "查看外部来源" })).toHaveCount(0);

    // 结果未知的 MCP 调用：写「结果未知」与交还给模型的内容
    const unknown = mcpRows.filter({ hasText: "结果未知" });
    await expect(unknown).toHaveCount(1);
    await expect(unknown).toContainText("交还给模型的内容");
    await expect(unknown).toContainText("执行被中断，结果未知");

    // 外部来源按页阅读：来源、最终地址、状态码与摘要值，第一页 200 行，翻页以后是第 201 至 250 行
    await fetchDone.getByRole("button", { name: "查看外部来源" }).click();
    const sourceDialog = page.locator(".y10-modal").filter({ hasText: "外部来源" });
    await expect(sourceDialog).toBeVisible();
    await expect(sourceDialog).toContainText("来源");
    await expect(sourceDialog).toContainText("最终地址");
    await expect(sourceDialog).toContainText("状态码");
    await expect(sourceDialog).toContainText("200");
    await expect(sourceDialog).toContainText("摘要值");
    await expect(sourceDialog).toContainText("sha256:");
    await expect(sourceDialog).toContainText("第 1 行：取回显示的证据");
    await expect(sourceDialog).toContainText(`第 1–200 行，共 ${EXPECTED_LINES} 行（第 1/2 页）`);
    await expect(sourceDialog).not.toContainText("第 201 行：取回显示的证据");
    await sourceDialog.getByRole("button", { name: "下一页" }).click();
    await expect(sourceDialog).toContainText("第 201 行：取回显示的证据");
    await expect(sourceDialog).toContainText(`第 201–${EXPECTED_LINES} 行，共 ${EXPECTED_LINES} 行（第 2/2 页）`);
    await expect(sourceDialog.getByRole("button", { name: "下一页" })).toBeDisabled();
    const shots = process.env.FETCH_DISPLAY_SHOT;
    if (shots) {
      mkdirSync(shots, { recursive: true });
      await page.screenshot({ path: join(shots, "fetch-display-external-source.png"), fullPage: true });
    }
    await sourceDialog.getByRole("button", { name: "关闭" }).click();
    await expect(sourceDialog).toHaveCount(0);

    // MCP 的结果也是外部来源：来源写服务器与工具名，没有最终地址与状态码
    await mcpDone.getByRole("button", { name: "查看外部来源" }).click();
    const mcpDialog = page.locator(".y10-modal").filter({ hasText: "外部来源" });
    await expect(mcpDialog).toContainText("服务器 time · 工具 echo");
    await expect(mcpDialog).toContainText("未上报");
    await expect(mcpDialog).toContainText("取回显示");
    await mcpDialog.getByRole("button", { name: "关闭" }).click();

    // 这一处动作行与外部来源的阅读里没有英文内部标识与开发者措辞（页面其他区块沿用原来的说法）
    const shown = await page.locator("section.card").filter({ has: page.getByRole("tab", { name: "动作与回执" }) })
      .innerText();
    for (const word of ["fetch_url", "mcp__", "refused", "duration_ms", "status_code", "external_source", "completed", "unknown"]) {
      expect(shown.includes(word), `动作行里出现了 ${word}`).toBe(false);
    }
    if (shots) {
      await page.screenshot({ path: join(shots, "fetch-display-department.png"), fullPage: true });
    }
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
