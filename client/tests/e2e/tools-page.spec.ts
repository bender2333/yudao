// 系统「工具与扩展」页（工单 #239 的验收）：Playwright 打开 Chromium 页面，页面由真实后端提供
// （client/tests/e2e/backend.py --script tools：两个项目各有不同的 MCP 服务器，各有一事项里
// 工程真的取回一次本机地址）。模型回答由 FakeAdapter 给出，服务器与取回都是真实的。
//
// 覆盖：网络取回与 MCP 两块的内容与 tools.registry 一致；「修改」入口跳到项目设置页；
// 其余三块标出所属阶段，computer use 不再写「虚拟屏幕上的动作」；页面上没有英文内部标识与
// 开发者措辞；控制台错误为零。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(600_000);
  backend = await startBackend({ script: "tools" });
});

test.afterAll(async () => {
  await backend?.stop();
});

type Registry = {
  projects: {
    project_id: string;
    name: string;
    mcp_servers: Record<
      string,
      {
        name: string;
        departments?: string[];
        tool_snapshot?: { tools?: { name?: string }[] } | null;
        probe?: { finished_at?: string | null; ok?: boolean | null } | null;
      }
    >;
    fetch_records?: { at?: string; url?: string; ok?: boolean | null }[];
  }[];
};

// 页面读的那一条查询：页面上显示什么，以它返回的内容为准
async function fetchRegistry(page: Page): Promise<Registry> {
  const envelope = await page.evaluate(async (address: string) => {
    const response = await fetch(`${address}/api/queries/tools.registry`);
    return (await response.json()) as { data?: unknown };
  }, backend.address);
  if (envelope.data === undefined) {
    throw new Error("tools.registry 没有返回数据");
  }
  return envelope.data as Registry;
}

async function openTools(client: ClientApp): Promise<void> {
  await client.page.evaluate(() => {
    window.location.hash = "#/sys/tools";
  });
  await expect(client.page.getByTestId("tools-fetch")).toBeVisible();
  await expect(client.page.getByTestId("tools-mcp")).toBeVisible();
}

function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

// 部门在页面上的写法：与页面其余地方一样的显示名
const DEPARTMENTS: Record<string, string> = { product: "产品", engineering: "工程", quality: "质检" };

test("取回记录与 MCP 服务器的内容与 tools.registry 一致", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const page = client.page;
    await openTools(client);
    const registry = await fetchRegistry(page);
    expect(registry.projects.length).toBe(2);

    // 网络取回：两个项目的取回记录各一行，地址、项目与结果都取自查询
    const fetchBlock = page.getByTestId("tools-fetch");
    const records = registry.projects.flatMap((project) =>
      (project.fetch_records ?? []).map((record) => ({ project: project.name, record })));
    expect(records.length).toBe(2);
    const fetchRows = fetchBlock.locator("tbody tr");
    await expect(fetchRows).toHaveCount(records.length);
    for (const { project, record } of records) {
      const row = fetchRows.filter({ hasText: record.url ?? "" });
      await expect(row).toContainText(record.url ?? "");
      await expect(row).toContainText(project);
      await expect(row).toContainText(record.ok === true ? "成功" : "失败");
    }

    // MCP 工具：每个项目一台不同的服务器；可以使用的部门、最近一次状态与工具都与查询一致
    const mcpBlock = page.getByTestId("tools-mcp");
    for (const project of registry.projects) {
      const section = mcpBlock.getByTestId(`tools-mcp-project-${project.project_id}`);
      await expect(section).toBeVisible();
      await expect(section).toContainText(project.name);
      const names = Object.keys(project.mcp_servers);
      expect(names.length).toBe(1);
      for (const name of names) {
        const server = project.mcp_servers[name];
        const serverSection = mcpBlock.getByTestId(`tools-mcp-server-${project.project_id}-${name}`);
        await expect(serverSection).toBeVisible();
        const departments = (server.departments ?? []).map((department) => DEPARTMENTS[department] ?? department);
        for (const department of departments) {
          await expect(serverSection).toContainText(department);
        }
        const tools = (server.tool_snapshot?.tools ?? []).map((tool) => tool.name ?? "").filter((tool) => tool !== "");
        if (server.probe?.finished_at) {
          expect(server.probe.ok).toBe(true);
          await expect(serverSection).toContainText(`成功 · ${tools.length} 个工具`);
          for (const tool of tools) {
            await expect(serverSection).toContainText(tool);
          }
        } else {
          // 没有探测过的服务器：状态与工具表的位置都如实写没有
          await expect(serverSection).toContainText("还没有探测过");
          await expect(serverSection).toContainText("还没有读取工具清单");
        }
      }
    }

    // 修改入口跳到项目设置页：MCP 服务器那一节在设置页里
    const first = registry.projects[0];
    await page.getByTestId(`tools-mcp-settings-${first.project_id}`).click();
    await expect(page).toHaveURL(new RegExp(`#/p/${first.project_id}/settings`));
    await expect(page.locator("#mcp-servers").getByRole("heading", { name: "MCP 服务器", exact: true }))
      .toBeVisible();

    expect(errors, `控制台错误：${errors.join(" | ")}`).toEqual([]);
  } finally {
    await client.close();
  }
});

test("其余三块标出所属阶段，页面上没有开发者措辞", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const page = client.page;
    await openTools(client);

    // 三块都在，各自写所属阶段：浏览器工具在阶段三，computer use 与只读观察者在阶段四
    for (const [id, stage] of [["browser", "阶段三"], ["computer-use", "阶段四"], ["observers", "阶段四"]] as const) {
      await expect(page.getByTestId(`tools-${id}`)).toBeVisible();
      await expect(page.getByTestId(`tools-stage-${id}`)).toHaveText(`所属阶段：${stage}`);
    }
    // computer use 块里过期的说法不再出现，也不再是「虚拟屏幕上的动作」
    const computerUse = page.getByTestId("tools-computer-use");
    await expect(computerUse).not.toContainText("虚拟屏幕");
    await expect(computerUse).toContainText("桌面");
    // 浏览器工具块也不再是「等待所属工作包加入查询」这种开发者说法
    await expect(page.getByTestId("tools-browser")).not.toContainText("工作包");

    // 两种窗口尺寸下页面都写着这几块，控制台错误为零
    for (const size of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
      await page.setViewportSize(size);
      await expect(page.getByTestId("tools-stage-computer-use")).toBeVisible();
      await expect(page.getByTestId("tools-stage-observers")).toBeVisible();
    }

    // 页面上不出现英文内部标识与开发者措辞
    const body = await page.evaluate(() => document.body.innerText);
    for (const internal of [
      "tools.registry", "config_digest", "tool_snapshot", "fetch_records", "mcp_servers", "server_info",
      "tool_server_probe_finished", "mcp_servers.save", "tool_server.probe", "stdio", "streamable",
      "工作包", "TODO",
    ]) {
      expect(body.includes(internal), `页面上出现了内部标识 ${internal}`).toBe(false);
    }

    expect(errors, `控制台错误：${errors.join(" | ")}`).toEqual([]);
  } finally {
    await client.close();
  }
});
