// 项目设置页的「MCP 服务器」一节（工单 #237 的验收）：Playwright 打开 Chromium 页面，
// 页面由真实后端提供（client/tests/e2e/backend.py，模型回答由 FakeAdapter 给出，不用 mock）。
// 预置里有一台真的 stdio MCP 服务器（harness/tests/mcp_servers/stdio_server.py，官方 SDK 写的），
// 探测时控制主机真的启动它、读出工具清单；两个凭据名称一个在数据目录的 .env 里有值、一个没有。
//
// 覆盖：保存与修改服务器设置；探测显示工具清单（先在页面里写「测试中」）；
// 凭据名称旁的状态与后端一致（并在页面上设置值以后跟着变）；过期保存时提示重新读取，重新读取以后可以保存；
// 页面上不出现英文内部标识与开发者措辞，也不显示凭据值；控制台错误为零。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const PROJECT = "示例项目";
const SERVER = "time";
const KEY = "MCP_E2E_KEY";
const MISSING_KEY = "MCP_MISSING_KEY";
const SECRET = "mcp-e2e-secret-237";
const NEW_SECRET = "mcp-e2e-secret-237-new";

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

type SettingsView = {
  version: number;
  mcp_servers: {
    version: number;
    servers: Record<string, { name: string; transport: string; departments?: string[];
      command?: string; args?: string[]; tool_snapshot?: { tools?: unknown[] } | null }>;
    credentials?: Record<string, { ref: string; configured: boolean; source: string; version?: number }>;
  };
};

async function fetchQuery<T>(page: Page, name: string, params: Record<string, string | number> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.set(key, String(value));
  }
  const suffix = search.toString();
  return page.evaluate(
    async ({ address, query, qs }) => {
      const response = await fetch(`${address}/api/queries/${query}${qs ? `?${qs}` : ""}`);
      return (await response.json()) as QueryEnvelope<unknown>;
    },
    { address: backend.address, query: name, qs: suffix },
  ).then((envelope) => {
    if (envelope.data === undefined) {
      throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
    }
    return envelope.data as T;
  });
}

async function sendCommand(page: Page, name: string, request: Record<string, unknown>): Promise<void> {
  const result = await page.evaluate(
    async ({ address, command, payload }) => {
      const response = await fetch(`${address}/api/commands/${command}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command_id: crypto.randomUUID(), ...payload }),
      });
      return { status: response.status, body: (await response.json()) as Record<string, unknown> };
    },
    { address: backend.address, command: name, payload: request },
  );
  if (result.status !== 200) {
    throw new Error(`命令 ${name} 被服务端拒绝：HTTP ${result.status} ${result.body.reason ?? ""} ${result.body.message ?? ""}`);
  }
}

async function projectId(page: Page): Promise<string> {
  const listed = await fetchQuery<{ projects: { name: string; project_id: string }[] }>(page, "projects.list");
  const row = listed.projects.find((item) => item.name === PROJECT);
  if (row === undefined) {
    throw new Error(`projects.list 里没有项目 ${PROJECT}（现有：${listed.projects.map((item) => item.name).join("、")}）`);
  }
  return row.project_id;
}

async function settingsOf(page: Page): Promise<SettingsView> {
  return fetchQuery<SettingsView>(page, "project.settings", { project_id: await projectId(page) });
}

async function openSettings(client: ClientApp): Promise<string> {
  const page = client.page;
  const id = await projectId(page);
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, `#/p/${id}/settings`);
  await expect(page.locator("#mcp-servers").getByRole("heading", { name: "MCP 服务器", exact: true }))
    .toBeVisible();
  return id;
}

// 收集页面的控制台错误；这一节的验收要求控制台错误为零。
// 服务端按设计用 409 拒绝基准版本过期的保存（这一节核对的就是那条提示），浏览器会把这次响应记成一条资源错误
function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    if (message.type() === "error"
        && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test("保存与修改服务器设置，探测显示工具清单", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const page = client.page;
    const section = page.locator("#mcp-servers");
    await openSettings(client);

    // 预置的两台服务器在列表里：名称、传输与可以使用的部门（部门的显示名，不写内部取值）
    const timeRow = section.locator("tr").filter({ hasText: SERVER }).first();
    const searchRow = section.locator("tr").filter({ hasText: "search" }).first();
    await expect(timeRow).toContainText(SERVER);
    await expect(timeRow).toContainText("本机进程（stdio）");
    await expect(timeRow).toContainText("产品、工程、质检");
    await expect(timeRow).toContainText("还没有读取工具清单");
    await expect(searchRow).toContainText("HTTP 服务（streamable HTTP）");
    await expect(searchRow).toContainText("产品");

    // 编辑：表单带出已保存的设置
    await page.getByTestId(`mcp-edit-${SERVER}`).click();
    const form = page.getByTestId("mcp-server-form");
    await expect(form).toBeVisible();
    await expect(form).toContainText(`修改服务器「${SERVER}」`);
    await expect(page.getByTestId("mcp-transport")).toHaveValue("stdio");

    // 探测：先在页面里写「测试中」，事件到达以后列出服务器信息与每个工具
    await form.getByRole("button", { name: "连接并读取工具清单" }).click();
    await expect(page.getByTestId("mcp-probing")).toBeVisible();
    await expect(page.getByTestId("mcp-probe-result")).toBeVisible({ timeout: 120_000 });
    await expect(page.getByTestId("mcp-probing")).toBeHidden();
    await expect(page.getByTestId("mcp-probe-result")).toContainText("yudao-test-stdio");
    await expect(page.getByTestId("mcp-probe-result")).toContainText("echo");
    await expect(page.getByTestId("mcp-probe-result")).toContainText("big");

    // 保存：表单收起，列表上这台服务器的工具数不再是「还没有读取工具清单」
    await form.getByRole("button", { name: "保存修改" }).click();
    await expect(page.getByTestId("mcp-server-form")).toBeHidden();
    await expect(timeRow).not.toContainText("还没有读取工具清单");
    await expect(timeRow).toContainText(/成功 · \d+ 个工具/);
    const saved = await settingsOf(page);
    expect(saved.mcp_servers.servers[SERVER].tool_snapshot?.tools?.length ?? 0).toBeGreaterThan(0);

    // 修改：改输出上限以后旧快照不再当可用清单（配置变了），这一行回到「还没有读取工具清单」
    await page.getByTestId(`mcp-edit-${SERVER}`).click();
    await form.locator("summary").filter({ hasText: "时限与输出上限" }).click();
    await form.getByLabel("输出上限（字符）").fill("5000");
    await form.getByRole("button", { name: "保存修改" }).click();
    await expect(page.getByTestId("mcp-server-form")).toBeHidden();
    await expect(timeRow).toContainText("还没有读取工具清单");
    expect((await settingsOf(page)).mcp_servers.servers[SERVER].tool_snapshot ?? null).toBeNull();

    // 再探测一次并保存：配置没再变，快照按同一摘要写回，这一行重新显示工具数
    await page.getByTestId(`mcp-edit-${SERVER}`).click();
    await form.getByRole("button", { name: "连接并读取工具清单" }).click();
    await expect(page.getByTestId("mcp-probe-result")).toBeVisible({ timeout: 120_000 });
    await form.getByRole("button", { name: "保存修改" }).click();
    await expect(page.getByTestId("mcp-server-form")).toBeHidden();
    await expect(timeRow).not.toContainText("还没有读取工具清单");

    expect(errors, `控制台错误：${errors.join(" | ")}`).toEqual([]);
  } finally {
    await client.close();
  }
});

test("凭据名称旁的状态与后端一致，过期保存时提示重新读取", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1920, height: 1080 }, { colorScheme: "dark" });
  const errors = watchErrors(client);
  try {
    const page = client.page;
    const section = page.locator("#mcp-servers");
    const id = await openSettings(client);

    // 凭据名称旁的状态与后端一致：一个有值（写在数据目录的 .env 里）、一个没有值
    await page.getByTestId(`mcp-edit-${SERVER}`).click();
    const form = page.getByTestId("mcp-server-form");
    await expect(form).toBeVisible();
    const before = await settingsOf(page);
    expect(before.mcp_servers.credentials?.[KEY].configured).toBe(true);
    expect(before.mcp_servers.credentials?.[KEY].source).toBe("dotenv");
    expect(before.mcp_servers.credentials?.[MISSING_KEY].configured).toBe(false);
    await expect(page.getByTestId(`mcp-credential-${KEY}-status`)).toContainText("已保存 · 来源：.env");
    await expect(page.getByTestId(`mcp-credential-${MISSING_KEY}-status`)).toContainText("缺失");

    // 在页面上给缺失的那个设置值：输入框始终为空，状态按后端更新成已设置
    await page.getByTestId(`mcp-credential-${MISSING_KEY}-input`).fill(NEW_SECRET);
    await page.getByTestId(`mcp-credential-${MISSING_KEY}-submit`).click();
    await expect(page.getByTestId(`mcp-credential-${MISSING_KEY}-status`)).toContainText("已保存", { timeout: 30_000 });
    await expect(page.getByTestId(`mcp-credential-${MISSING_KEY}-input`)).toHaveValue("");
    const after = await settingsOf(page);
    expect(after.mcp_servers.credentials?.[MISSING_KEY].configured).toBe(true);
    expect(after.mcp_servers.credentials?.[MISSING_KEY].source).toBe("dotenv");

    // 页面上不出现凭据值，也不出现英文内部标识与开发者措辞
    const body = await page.evaluate(() => document.body.innerText);
    for (const secret of [SECRET, NEW_SECRET]) {
      expect(body.includes(secret), `页面上出现了凭据值 ${secret}`).toBe(false);
    }
    for (const internal of ["credential_ref", "config_digest", "tool_snapshot", "startup_timeout_sec",
      "call_timeout_sec", "output_limit", "mcp_servers.save", "tool_server.probe", "server_info",
      "protocol_version", "tool_server_probe_finished"]) {
      expect(body.includes(internal), `页面上出现了内部标识 ${internal}`).toBe(false);
    }

    // 过期保存：页面开着表单时在界面之外改一次设置，再点保存 → 拒绝并提示重新读取
    const current = await settingsOf(page);
    await sendCommand(page, "mcp_servers.save", {
      project_id: id,
      base_version: current.mcp_servers.version,
      servers: {
        ...current.mcp_servers.servers,
        other: { name: "other", transport: "http", url: "https://other.example.com/mcp", departments: ["product"] },
      },
    });
    // 页面按事件重新读取，列表里出现新的那一台；表单的基准版本仍是打开表单时的那一个
    await expect(section).toContainText("other", { timeout: 30_000 });
    await form.getByRole("button", { name: "保存修改" }).click();
    await expect(page.getByTestId("mcp-save-notice")).toContainText("请重新读取", { timeout: 30_000 });
    await expect(page.getByTestId("mcp-save-notice")).not.toContainText("stale_base");

    // 提示里给出去处：重新读取以后基准版本换到最新的那一个，再保存就能通过
    await page.getByTestId("mcp-reload").click();
    await expect(page.getByTestId("mcp-save-notice")).toBeHidden({ timeout: 30_000 });
    await form.getByRole("button", { name: "保存修改" }).click();
    await expect(page.getByTestId("mcp-server-form")).toBeHidden({ timeout: 30_000 });
    const settled = await settingsOf(page);
    expect(Object.keys(settled.mcp_servers.servers).sort()).toEqual(["other", "search", SERVER]);

    expect(errors, `控制台错误：${errors.join(" | ")}`).toEqual([]);
  } finally {
    await client.close();
  }
});
