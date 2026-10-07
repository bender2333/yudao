// 部门设置弹窗与部门工作间的端到端测试（工单 #95 的验收）：Playwright 打开 Chromium 页面，
// 页面由真实后端提供（client/tests/e2e/backend.py，模型回答由 FakeAdapter 给出）。覆盖：
// 在弹窗中为本项目的一个部门另选模型并保存以后，工作间的生效模型与来源随事件更新；
// 选择「跟随部门默认」以后来源回到部门默认；版本冲突时弹窗提示重新读取；
// 运行中更换模型以后「最近一次请求」显示新的模型、协议与发送的档位；
// 两种窗口尺寸（1440×900 与 1920×1080）、浅色与深色，控制台错误为零。
//
// 后端预置了已准入模型 glm-4.6（Responses 协议，声明 low、high 档位，默认 low），
// 三个部门的部门默认指向 FakeAdapter 的 fake 模型；因此弹窗的模型下拉里既有跟随项，也有可另选的定义。

import { expect, test, type Locator, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const SAMPLE = "示例项目";
const BLOCKED = "文本工具";

const VIEW = "dept/product";

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    // 服务端按设计用 409 拒绝命令（基准版本过期等），界面已经把原因显示给用户
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

async function openClient(size: { width: number; height: number }, colorScheme: "light" | "dark" = "light"): Promise<ClientApp> {
  const client = await startClient(backend, size, { colorScheme });
  await expect(client.page.locator(".brand")).toHaveText("Yudao");
  return client;
}

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

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
    { address: backend.address, query: name, qs: suffix }
  ).then((envelope) => {
    if (envelope.data === undefined) {
      throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
    }
    return envelope.data as T;
  });
}

async function sendCommand<T>(page: Page, name: string, request: Record<string, unknown>): Promise<T> {
  return page.evaluate(
    async ({ address, command, payload }) => {
      const response = await fetch(`${address}/api/commands/${command}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command_id: crypto.randomUUID(), ...payload }),
      });
      return { status: response.status, body: (await response.json()) as Record<string, unknown> };
    },
    { address: backend.address, command: name, payload: request }
  ).then((result) => result as unknown as T);
}

async function expectAccepted(page: Page, name: string, request: Record<string, unknown>): Promise<Record<string, unknown>> {
  const result = await sendCommand<{ status: number; body: { reason?: string; message?: string } }>(page, name, request);
  if (result.status !== 200) {
    throw new Error(`命令 ${name} 被服务端拒绝：HTTP ${result.status} ${result.body.reason ?? ""} ${result.body.message ?? ""}`);
  }
  return result.body as Record<string, unknown>;
}

// 给已保存的连接设置在内存里的 Key：走真实命令与真实凭据链（与模型管理页的用例同一做法）。
// 生效模型要求凭据可用（设计说明第 5.5 节），因此验收生效模型的用例先设置它
async function setKey(page: Page, ref: string): Promise<void> {
  const status = await page.evaluate(async (payload: { address: string; ref: string }) => {
    const listed = await (await fetch(`${payload.address}/api/queries/catalog`)).json();
    const provider = listed.data.providers.find((item: { credential_ref: string }) => item.credential_ref === payload.ref);
    const response = await fetch(`${payload.address}/api/commands/credential.set`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command_id: crypto.randomUUID(),
        base_version: provider.credential.version,
        ref: payload.ref,
        secret: "sk-e2e-department-settings",
        persist: false,
      }),
    });
    return response.status;
  }, { address: backend.address, ref });
  expect(status).toBe(200);
}

async function projectId(page: Page, name: string): Promise<string> {
  const data = await fetchQuery<{ projects: { name: string; project_id: string }[] }>(page, "projects.list");
  const row = data.projects.find((project) => project.name === name);
  if (row === undefined) {
    throw new Error(`projects.list 里没有项目 ${name}`);
  }
  return row.project_id;
}

async function gotoView(page: Page, id: string, view: string): Promise<void> {
  await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${id}/${view}`);
  await expect(page.locator(".tabbar .tab").first()).toBeVisible();
}

async function section(page: Page, heading: string) {
  return page.locator("section.card").filter({ has: page.getByRole("heading", { name: heading, exact: true }) }).first();
}

async function waitUntil(check: () => Promise<boolean>, page: Page, description: string, timeoutMs = 40_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) {
      return;
    }
    if (Date.now() > deadline) {
      const text = await page.evaluate(() => document.body.innerText).catch(() => "");
      throw new Error(`等待超时：${description}（当前页面文本：${text.slice(0, 400)}）`);
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}

async function settingsVersion(page: Page, id: string, department: string): Promise<number> {
  const data = await fetchQuery<{ departments: Record<string, { version: number }> }>(
    page, "project.settings", { project_id: id });
  return data.departments[department].version;
}

// 部门工作间的生效模型与来源：读 project 的部门设置与部门默认（catalog 的 bindings）
async function workshopModelText(title: Locator): Promise<string> {
  return title.locator(".kv .line").filter({ hasText: "当前生效的模型及来源" }).innerText();
}

test.describe("部门设置弹窗与部门工作间（1440×900）", () => {
  test("另选模型以后工作间随事件更新，改回跟随部门默认以后来源回到部门默认", async () => {
    const client = await openClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await setKey(page, "OPENCODE_GO_KEY");
      await gotoView(page, id, VIEW);
      const title = await section(page, "产品工作间");
      await expect(title).toContainText("（来源 部门默认）");

      // 打开弹窗：标题为「本项目 · 产品设置」；模型第一项是跟随部门默认，其后是已准入定义
      await title.getByRole("button", { name: "部门设置" }).click();
      const dialog = page.locator(".modal-backdrop");
      await expect(dialog.locator(".modal-head h2")).toHaveText("本项目 · 产品设置");
      const model = dialog.getByTestId("department-model-product");
      await expect(model.locator("option").first()).toHaveText(/^跟随部门默认（当前：/);
      const glm = model.locator("option", { hasText: "glm-4.6" });
      await expect(glm).toHaveCount(1);

      // 选择 glm-4.6 与 high 档位并保存：提示「从本部门下一次模型请求起生效」
      const value = await glm.getAttribute("value");
      expect(value).not.toBeNull();
      await model.selectOption(value as string);
      await dialog.getByTestId("department-tier-product").selectOption("high");
      await expect(dialog).toContainText("从本部门下一次模型请求起生效");
      await dialog.getByRole("button", { name: "保存部门设置" }).click();
      await expect(page.locator(".modal-backdrop")).toHaveCount(0);

      // 工作间随事件流更新：生效模型与来源变为 glm-4.6（来源 项目设置）
      await waitUntil(async () => (await workshopModelText(title)).includes("glm-4.6"), page, "工作间生效模型更新为 glm-4.6");
      await expect(title).toContainText("（来源 项目设置）");

      // 重新打开：模型选中 glm-4.6，档位选中 high
      await title.getByRole("button", { name: "部门设置" }).click();
      const dialog2 = page.locator(".modal-backdrop");
      await expect(dialog2.getByTestId("department-model-product")).toHaveValue(value as string);
      await expect(dialog2.getByTestId("department-tier-product")).toHaveValue("high");

      // 选择「跟随部门默认」并保存：来源回到部门默认
      await dialog2.getByTestId("department-model-product").selectOption("");
      await dialog2.getByRole("button", { name: "保存部门设置" }).click();
      await expect(page.locator(".modal-backdrop")).toHaveCount(0);
      await waitUntil(async () => (await workshopModelText(title)).includes("（来源 部门默认）"), page, "来源回到部门默认");
      await expect(title).not.toContainText("glm-4.6");

      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("版本冲突时弹窗提示重新读取，不覆盖别人的修改", async () => {
    const client = await openClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "dept/engineering");
      const title = await section(page, "工程工作间");
      await title.getByRole("button", { name: "部门设置" }).click();
      const dialog = page.locator(".modal-backdrop");
      const prompt = dialog.getByLabel("部门 Prompt");
      await prompt.fill("工程部门先读有效需求，再写实现计划。");

      // 界面之外修改同一个部门设置：设置版本 +1，弹窗手里的基准版本因此过期
      const version = await settingsVersion(page, id, "engineering");
      await expectAccepted(page, "department_settings.save", {
        project_id: id, department: "engineering", base_version: version,
        department_prompt: "界面之外写入的部门 Prompt。",
      });

      await dialog.getByRole("button", { name: "保存部门设置" }).click();
      const error = dialog.locator('p.error[role="status"]');
      await expect(error).toContainText("部门设置已经被修改，请重新读取以后提交");
      // 不覆盖别人的修改：服务端仍是界面之外写入的内容
      const after = await fetchQuery<{ departments: Record<string, { text: string; version: number }> }>(
        page, "project.settings", { project_id: id });
      expect(after.departments.engineering.text).toBe("界面之外写入的部门 Prompt。");
      expect(after.departments.engineering.version).toBe(version + 1);
      await dialog.getByRole("button", { name: "关闭" }).click();
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("运行中更换模型以后，最近一次请求显示新的模型、协议与发送的档位", async () => {
    test.setTimeout(180_000);
    const client = await openClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, BLOCKED);
      await setKey(page, "OPENCODE_GO_KEY");
      // 待恢复的决定请求写明是哪个部门的下一次请求不发送（第 5.5 节）
      const decisions = await fetchQuery<{ decisions: { decision_id: string; version: number;
        request: { department: string | null } }[] }>(
        page, "decisions.list", { status: "open", project_id: id });
      const decision = decisions.decisions[0];
      expect(decision).toBeDefined();
      const department = decision.request.department;
      expect(department).not.toBeNull();

      // 运行中把该部门另选为 glm-4.6、档位 high 并保存，随后回答决定请求让下一次请求按新模型发送（第 5.4 节）
      const version = await settingsVersion(page, id, department as string);
      await expectAccepted(page, "department_settings.save", {
        project_id: id, department, base_version: version,
        provider_id: "opencode-go", model_id: "glm-4.6", requested_tier: "high",
        department_prompt: null,
      });
      const name = { product: "产品", engineering: "工程", quality: "质检" }[department as string] ?? "";
      await gotoView(page, id, `dept/${department}`);
      const title = await section(page, `${name}工作间`);
      await expectAccepted(page, "decision.answer", {
        decision_id: decision.decision_id, base_version: decision.version, option: "continue",
      });

      // 工作间的最近一次请求显示新的模型、协议与发送的档位（由事件流更新）
      const lastModel = title.locator(".kv .line").filter({ hasText: "最近一次请求实际使用的模型" });
      await waitUntil(async () => (await lastModel.innerText()).includes("glm-4.6"), page, "最近一次请求显示 glm-4.6");
      await expect(lastModel).toContainText("glm-4.6");
      const protocol = title.locator(".kv .line").filter({ hasText: "协议" });
      await expect(protocol).toContainText("responses");
      const tier = title.locator(".kv .line").filter({ hasText: "发送的档位" });
      await expect(tier).toContainText("high");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("所选模型准入作废时工作间显示「无法使用」与原因", async () => {
    const client = await openClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await setKey(page, "OPENCODE_GO_KEY");
      // 让产品部门引用 glm-4.6，再作废它的准入：修改连接的地址（第 4.4 节，该连接下全部定义回到候选）
      const version = await settingsVersion(page, id, "product");
      await expectAccepted(page, "department_settings.save", {
        project_id: id, department: "product", base_version: version,
        provider_id: "opencode-go", model_id: "glm-4.6", requested_tier: "high", department_prompt: null,
      });
      const catalog = await fetchQuery<{ revision: number; providers: { id: string; name: string; protocol: string;
        base_url: string; credential_ref: string; timeout_sec: number; preset_id: string; models_url: string }[] }>(
        page, "catalog");
      const provider = catalog.providers.find((item) => item.id === "opencode-go");
      expect(provider).toBeDefined();
      // 只取连接保存命令的字段（第 4.6 节：未知字段拒绝），改地址让它的准入作废；
      // 模型访问定义按原样带上，因此引用保留、显示「准入已作废」而不是「定义不存在」
      const models = await fetchQuery<{ models: { id: string; provider_id: string; model: string;
        context_window: number | null; max_output_tokens: number; capability_source: string;
        accepts_required_tool_call: boolean; input_modalities: string[]; reasoning_levels: string[];
        default_reasoning_level: string | null; reasoning_mode: string }[] }>(page, "catalog");
      const definition = models.models.find((item) => item.id === "glm-4.6");
      expect(definition).toBeDefined();
      await expectAccepted(page, "catalog.connection.save", {
        base_version: catalog.revision,
        provider: {
          id: provider!.id, name: provider!.name, protocol: provider!.protocol,
          base_url: "https://invalid.example/v1", credential_ref: provider!.credential_ref,
          timeout_sec: provider!.timeout_sec, preset_id: provider!.preset_id, models_url: provider!.models_url,
        },
        models: [{
          id: definition!.id, model: definition!.model, context_window: definition!.context_window,
          max_output_tokens: definition!.max_output_tokens, capability_source: definition!.capability_source,
          capacity_confirmed: true, accepts_required_tool_call: definition!.accepts_required_tool_call,
          input_modalities: definition!.input_modalities, reasoning_levels: definition!.reasoning_levels,
          default_reasoning_level: definition!.default_reasoning_level, reasoning_mode: definition!.reasoning_mode,
        }],
      });

      await gotoView(page, id, VIEW);
      const title = await section(page, "产品工作间");
      await waitUntil(async () => (await workshopModelText(title)).includes("无法使用"), page, "工作间显示无法使用");
      await expect(title).toContainText("无法使用");
      // 无法使用时只说明原因与所引用的模型，不显示其他连接或模型（不改成解析顺序中的下一层）
      expect(await workshopModelText(title)).not.toContain("fake-script");
      expect(await workshopModelText(title)).toContain("准入已作废");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});

test.describe("部门设置弹窗与部门工作间（1920×1080，深色）", () => {
  test("1920×1080 与深色下弹窗与工作间照常渲染，无横向滚动", async () => {
    test.setTimeout(180_000);
    const client = await openClient({ width: 1920, height: 1080 }, "dark");
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, VIEW);
      const title = await section(page, "产品工作间");
      await expect(title).toContainText("工位：产品 Agent");
      await title.getByRole("button", { name: "部门设置" }).click();
      const dialog = page.locator(".modal-backdrop");
      await expect(dialog.locator(".modal-head h2")).toHaveText("本项目 · 产品设置");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);
      await expect(dialog.getByTestId("department-model-product")).toBeVisible();
      await dialog.getByRole("button", { name: "关闭" }).click();
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});
