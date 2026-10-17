// 模型管理页的端到端测试（工单 #93 的验收）：Playwright 打开 Chromium 页面，页面由真实后端提供
// （client/tests/e2e/backend.py）。后端内启动真实的 HTTP 上游（Responses 协议的最小推理服务与模型列表服务），
// 候选、连接测试与模型测试都发真实请求。窗口尺寸 1440×900 与 1920×1080，控制台错误为零。

import { expect, test } from "@playwright/test";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { once } from "node:events";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

// 上游凭据：测试经命令设置在内存里，页面与网络响应都不应出现它
const KEY = "sk-e2e-opencode-go-8f3a1c";

// 每条用例各自启动一份后端与客户端：用例会修改目录（保存连接、部门默认、凭据），
// 共用一份后端会让用例之间互相影响。后端启动用时由 git 子进程与目录种子决定（#107 裁定，
// 见 docs/architecture-issues.md），这里单独放宽每条用例的时限
async function openModels(
  size: { width: number; height: number },
  options: { admitAndBind?: boolean; rejectUpstream?: boolean } = {},
): Promise<{ backend: Backend; client: ClientApp }> {
  const backend = await startBackend({ admitAndBind: options.admitAndBind === true, rejectUpstream: options.rejectUpstream === true });
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  await client.page.getByRole("button", { name: "模型管理", exact: true }).click();
  await expect(client.page.locator(".path")).toHaveText("模型管理");
  return { backend, client };
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

// 给已经保存的连接设置内存里的 Key：走真实命令与真实凭据链，页面只看到状态
async function setKey(client: ClientApp, backend: Backend, ref: string): Promise<void> {
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
  }, { address: backend.address, ref, key: KEY });
  expect(status).toBe(200);
}

// 网络响应里没有任何 API Key：记录所有响应体，逐条断言不含这个值
function watchBodies(client: ClientApp): string[] {
  const bodies: string[] = [];
  client.page.on("response", (response) => {
    const url = response.url();
    if (!url.includes("/api/")) {
      return;
    }
    void response.text().then((text) => bodies.push(text)).catch(() => undefined);
  });
  return bodies;
}

for (const size of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  const label = `${size.width}×${size.height}`;

  test(`${label}：页面显示连接摘要、模型表与部门默认，且没有横向滚动`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      await expect(client.page.getByTestId("provider-opencode-go")).toBeVisible();
      const summary = client.page.getByTestId("provider-opencode-go").locator(".mm-summary");
      await expect(summary).toContainText("OpenCode Go");
      await expect(summary).not.toContainText("Responses");
      await expect(summary).toContainText("凭据：");
      // 摘要按连接统计「已准入 x · 候选 y」；同一连接下的两条数之和等于它的模型数（与其他测试的先后无关）
      const summaryText = await summary.innerText();
      const counts = summaryText.match(/已准入 (\d+) · 候选 (\d+)/);
      expect(counts).not.toBeNull();
      expect(Number(counts![1]) + Number(counts![2])).toBe(1);

      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "展开" }).click();
      const model = client.page.getByTestId("model-glm-4.6");
      await expect(model).toContainText("glm-4.6");
      await expect(model).toContainText("low、high");
      await expect(model).toContainText("文本");
      // 准入列只读：显示测试时间与实际返回的模型，或者显示候选
      await expect(model).toContainText(/已准入：|候选/);

      await expect(client.page.getByTestId("department-defaults")).toBeVisible();
      await expect(client.page.getByTestId("default-product")).toBeVisible();
      await expect(client.page.getByTestId("default-engineering")).toBeVisible();
      await expect(client.page.getByTestId("default-quality")).toBeVisible();

      // 不出现横向滚动
      const overflow = await client.page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：候选真实取自测试内上游，模型测试通过以后准入列显示测试时间与实际返回的模型`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      await setKey(client, backend, "OPENCODE_GO_KEY");
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "展开" }).click();

      // 连接测试：测试中 → 通过
      await client.page.getByTestId("test-connection-opencode-go").click();
      await expect(client.page.getByTestId("connection-result-opencode-go")).toContainText("连接测试通过");

      // 候选：来源地址与采集时间来自真实的上游模型列表
      await client.page.getByTestId("collect-opencode-go").click();
      const candidates = client.page.getByTestId("candidates-opencode-go");
      await expect(candidates).toContainText("来源 http://127.0.0.1:");
      await expect(candidates).toContainText("采集时间");
      await expect(candidates).toContainText("vision-model");

      // 模型测试：测试中 → 通过，模型行显示通过与用时，准入列显示测试时间与实际返回的模型
      await client.page.getByTestId("row-test-glm-4.6").click();
      await expect(client.page.getByTestId("model-result-glm-4.6")).toContainText("模型测试通过");
      await expect(client.page.getByTestId("model-result-glm-4.6")).toContainText(/\d+ 毫秒/);
      await expect(client.page.getByTestId("model-glm-4.6")).toContainText("已准入：");
      await expect(client.page.getByTestId("provider-opencode-go").locator(".mm-summary"))
        .toContainText("已准入 1 · 候选 0");

      // 准入列只读：模型表里没有可编辑准入的控件
      await expect(client.page.getByTestId("model-glm-4.6").locator("input")).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：模型测试的真实上游返回 401，模型行显示未通过与原因`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size, { rejectUpstream: true });
    const errors = watchErrors(client);
    try {
      // 这条连接指向测试内的真实 HTTP 上游，那个上游对任何请求都返回 401
      await client.page.getByTestId("provider-rejected-go").getByRole("button", { name: "展开" }).click();
      await setKey(client, backend, "REJECTED_GO_KEY");
      await client.page.getByTestId("row-test-glm-rejected").click();
      // 失败时模型行写明未通过，并把上游给出的原因带上（工单 #294）
      const line = client.page.getByTestId("model-result-glm-rejected");
      await expect(line).toContainText("模型测试未通过");
      await expect(line).toContainText("HTTP 401");
      // 失败不写准入：这一行的准入列仍是候选
      await expect(client.page.getByTestId("model-glm-rejected")).toContainText("候选");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：新建连接表单的超时默认值与后端一致`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      // 目录合同的 default_timeout_sec：客户端的默认值取自它，不在客户端写死（工单 #294）
      const listed = await client.page.evaluate(async (address: string) => {
        const response = await fetch(`${address}/api/queries/catalog`);
        return (await response.json()) as { data: { default_timeout_sec: number } };
      }, backend.address);
      await client.page.getByRole("button", { name: "添加 Provider 配置" }).click();
      await client.page.locator(".mm-form details.mm-advanced > summary").click();
      await expect(client.page.getByTestId("provider-timeout"))
        .toHaveValue(String(listed.data.default_timeout_sec));
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：编辑表单恢复服务方案与协议，选方案与协议自动填入请求基址，缺少容量的行不能保存`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "展开" }).click();
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "编辑" }).click();

      const form = client.page.locator(".mm-form");
      await expect(form).toContainText("编辑 Provider 配置");
      // 编辑时恢复服务方案，地址取连接保存的地址（种子连接指向测试内上游）；
      // 调用协议属于每一条访问定义（ADR-0033），这一条连接下的定义用 Responses
      await expect(form.getByRole("button", { name: "OpenCode Go" })).toHaveAttribute("aria-pressed", "true");
      await expect(form.getByTestId("row-protocol-glm-4.6")).toHaveValue("responses");
      await expect(form.getByTestId("provider-base-url")).toHaveValue(new RegExp(`^http://127\\.0\\.0\\.1:\\d+/v1$`));
      // 预置表与能力表的信息都在方案区
      await expect(form).toContainText("预置表 2026-10-11.1");
      await expect(form).toContainText("模型能力表");

      // 换这一条定义的协议：内置方案的地址取该方案该协议的请求基址，端到端里三种协议的基址
      // 分别是三个本机上游（协议不同则地址不同）
      const byProtocols = await client.page.evaluate(async (address: string) => {
        const listed = await (await fetch(`${address}/api/queries/catalog`)).json();
        const preset = (listed.data.presets.presets as { id: string; base_urls: Record<string, string> }[])
          .find((item) => item.id === "opencode-go");
        return preset!.base_urls;
      }, backend.address);
      expect(byProtocols.responses).not.toBe(byProtocols.messages);
      await form.getByTestId("row-protocol-glm-4.6").selectOption("messages");
      await expect(form.getByTestId("provider-base-url")).toHaveValue(byProtocols.messages);
      await form.getByTestId("row-protocol-glm-4.6").selectOption("responses");
      await expect(form.getByTestId("provider-base-url")).toHaveValue(byProtocols.responses);

      // Key 输入框始终为空，不回填
      await expect(form.getByTestId("credential-secret")).toHaveValue("");

      // 候选加入一行：预填容量直接采用，来源标明
      await setKey(client, backend, "OPENCODE_GO_KEY");
      await form.getByRole("button", { name: "获取模型列表" }).click();
      await form.getByTestId("admit-candidate-vision-model").click();
      await expect(form.getByTestId("model-row-vision-model")).toContainText("窗口：上游模型列表");
      // 加入时预填调用协议并标明来源：这个模型不在能力表里，预填服务方案的默认协议（工单 #383）
      await expect(form.getByTestId("model-row-vision-model")).toContainText("协议：服务方案默认");
      await expect(form.getByTestId("row-protocol-vision-model")).toHaveValue("chat_completions");
      // 手动添加的一行两项容量都空着：界面写明缺哪两项（工单 #294）
      await form.getByTestId("add-model-row").click();
      await expect(form.locator('[data-testid^="capacity-issue-"]').last()).toHaveText("缺少窗口与输出上限");
      // 已保存的行清空窗口：界面写明「缺少窗口」，提交按同一份判断被拦下（与目录文档校验一致）
      await form.getByTestId("row-window-glm-4.6").fill("");
      await expect(form.getByTestId("capacity-issue-glm-4.6")).toHaveText("缺少窗口");
      // 去掉那一行空白的手工行：ID 与上游模型 ID 是必填项，原生校验会先拦下提交，与容量判断无关
      await form.locator('button[data-testid^="remove-model-"]').last().click();
      await form.getByTestId("submit-provider").click();
      await expect(form.getByTestId("form-status")).toContainText("不能保存");
      await form.getByTestId("row-window-glm-4.6").fill("200000");
      await expect(form.getByTestId("capacity-issue-glm-4.6")).toHaveCount(0);

      // 推理参数方式只列出与该行协议相符的选项：新建的行预填 Chat Completions，
      // 换到 Anthropic Messages 只列出 Messages 的两种方式，换回来才有 effort（第 7.4 节）
      await expect(form.getByTestId("row-protocol-vision-model")).toHaveValue("chat_completions");
      const modeOptions = form.getByTestId("reasoning-mode-vision-model").locator("option");
      await expect(modeOptions).toContainText(["未声明", "effort（请求带档位名）"]);
      await expect(form.getByTestId("reasoning-mode-vision-model").locator("option", { hasText: "adaptive" })).toHaveCount(0);
      await form.getByTestId("row-protocol-vision-model").selectOption("messages");
      await expect(form.getByTestId("reasoning-mode-vision-model").locator("option", { hasText: "effort" })).toHaveCount(0);
      await expect(form.getByTestId("reasoning-mode-vision-model").locator("option", { hasText: "adaptive" })).toHaveCount(1);
      await form.getByTestId("row-protocol-vision-model").selectOption("chat_completions");
      await expect(form.getByTestId("reasoning-mode-vision-model").locator("option", { hasText: "effort" })).toHaveCount(1);

      // 默认档位只能从已选的支持档位中选择
      await form.getByTestId("level-vision-model-high").click();
      await expect(form.getByTestId("default-level-vision-model").locator("option")).toContainText(["未选择", "high"]);
      // 声明支持档位时同时给出默认档位与推理参数方式（设计说明第 7.1 节）
      await form.getByTestId("default-level-vision-model").selectOption("high");
      await form.getByTestId("reasoning-mode-vision-model").selectOption("effort");

      // 保存：这条连接的准入未作废（没有引用方），保存以后表单收起，模型表里出现这条定义
      await form.getByTestId("submit-provider").click();
      await expect(form).toHaveCount(0);
      await expect(client.page.getByTestId("model-vision-model")).toBeVisible();
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  // 工单 #382 第 4 项验收：新建自定义连接、加入一个模型并测试通过，改它的协议并保存以后回到候选
  test(`${label}：新建自定义连接、模型测试通过后改协议保存，这条定义回到候选`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      // 地址取测试内真实上游的地址（端口由系统分配，不在测试里写死）
      const baseUrl = await client.page.evaluate(async (address: string) => {
        const listed = await (await fetch(`${address}/api/queries/catalog`)).json();
        const provider = (listed.data.providers as { id: string; base_url: string }[])
          .find((item) => item.id === "opencode-go");
        return provider!.base_url;
      }, backend.address);
      await setKey(client, backend, "OPENCODE_GO_KEY");

      await client.page.getByRole("button", { name: "添加 Provider 配置" }).click();
      const form = client.page.locator(".mm-form");
      await form.getByTestId("provider-base-url").fill(baseUrl);
      await form.locator("label.mm-field").filter({ hasText: "ID" }).first().locator("input").fill("local-upstream");
      await form.locator("label.mm-field").filter({ hasText: "名称" }).first().locator("input").fill("本机上游");
      await form.locator("label.mm-field").filter({ hasText: "凭据引用" }).locator("input").fill("OPENCODE_GO_KEY");
      // 手动添加的一行：默认预填 Chat Completions
      await form.getByTestId("add-model-row").click();
      const rowKey = await form.locator('[data-testid^="row-id-"]').first().inputValue();
      await expect(form.getByTestId(`row-protocol-${rowKey}`)).toHaveValue("chat_completions");
      // 端到端的上游按 Responses 协议回答：这条定义要在模型测试里真实通过，就选 Responses
      await form.getByTestId(`row-protocol-${rowKey}`).selectOption("responses");
      await form.getByTestId(`row-model-${rowKey}`).fill("glm-4.6");
      await form.getByTestId(`row-window-${rowKey}`).fill("200000");
      await form.getByTestId(`row-output-${rowKey}`).fill("32000");
      await form.getByTestId("submit-provider").click();
      await expect(form).toHaveCount(0);

      // 模型测试通过：这一条进入已准入，模型表的调用协议列显示 Responses
      const provider = client.page.getByTestId("provider-local-upstream");
      await provider.getByRole("button", { name: "展开" }).click();
      await client.page.getByTestId(`row-test-${rowKey}`).click();
      await expect(client.page.getByTestId(`model-${rowKey}`)).toContainText("已准入：");
      await expect(client.page.getByTestId(`model-${rowKey}`)).toContainText("Responses");

      // 把协议改成 Chat Completions 并保存：这条定义回到候选，协议列跟着改
      await provider.getByRole("button", { name: "编辑" }).click();
      const edit = client.page.locator(".mm-form");
      await edit.getByTestId(`row-protocol-${rowKey}`).selectOption("chat_completions");
      await edit.getByTestId("submit-provider").click();
      await expect(edit).toHaveCount(0);
      await expect(client.page.getByTestId(`model-${rowKey}`)).toContainText("候选（准入已作废）");
      await expect(client.page.getByTestId(`model-${rowKey}`)).toContainText("Chat Completions");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：Key 输入框不回填，页面与网络响应中都没有 API Key`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    const bodies = watchBodies(client);
    try {
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "展开" }).click();
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "编辑" }).click();
      const form = client.page.locator(".mm-form");
      // 还没有设置 Key 时，凭据状态显示缺失；Key 输入框始终为空，不回填
      await expect(form.getByTestId("credential-status")).toContainText("缺失");
      await expect(form.getByTestId("credential-secret")).toHaveValue("");
      // 输入一个 Key 并保存：输入框随之清空，凭据来源变为内存
      await form.getByTestId("credential-secret").fill(KEY);
      await form.getByRole("button", { name: "保存 Key" }).click();
      await expect(form.getByTestId("credential-secret")).toHaveValue("");
      await expect(form.getByTestId("credential-status")).toContainText("已配置，来源 内存");
      // 重新打开表单仍然为空
      await form.getByRole("button", { name: "取消" }).click();
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "编辑" }).click();
      await expect(client.page.locator(".mm-form").getByTestId("credential-secret")).toHaveValue("");

      const pageText = await client.page.locator("body").innerText();
      expect(pageText).not.toContain(KEY);
      expect(pageText).not.toContain("sk-");
      await client.page.waitForTimeout(500);
      for (const body of bodies) {
        expect(body).not.toContain(KEY);
      }
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：部门默认只列出已准入的定义，保存以后生效`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      await setKey(client, backend, "OPENCODE_GO_KEY");
      // 先做模型测试，让定义进入已准入
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "展开" }).click();
      await client.page.getByTestId("row-test-glm-4.6").click();
      await expect(client.page.getByTestId("model-glm-4.6")).toContainText("已准入：");

      // 未准入时选项只有「未设置」
      const options = await client.page.getByTestId("default-model-product").locator("option").allTextContents();
      expect(options).toContain("glm-4.6");

      await client.page.getByTestId("default-model-product").selectOption("glm-4.6");
      const tiers = await client.page.getByTestId("default-tier-product").locator("option").allTextContents();
      expect(tiers).toContain("low");
      expect(tiers).toContain("high");
      await client.page.getByTestId("default-tier-product").selectOption("low");
      await client.page.getByTestId("save-defaults").click();
      await expect(client.page.getByTestId("defaults-status")).toContainText("已保存部门默认");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：编辑 JSON 打开目录文档，格式化与保存走真实校验`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      await client.page.getByTestId("edit-json").click();
      const dialog = client.page.locator(".modal");
      await expect(dialog).toBeVisible();
      const editor = dialog.getByLabel("目录文档 JSON");
      await expect(editor).toHaveValue(/"providers"/);
      // 不含 Key
      expect(await editor.inputValue()).not.toContain("secret");
      // 非法 JSON：界面拒绝，不发命令
      await editor.fill("{ 不是 JSON");
      await dialog.getByRole("button", { name: "格式化" }).click();
      await expect(dialog.getByRole("status")).toContainText("JSON 无法解析");
      await dialog.getByRole("button", { name: "重置" }).click();
      await expect(editor).toHaveValue(/"providers"/);
      await expect(dialog.getByRole("status")).toHaveCount(0);
      await dialog.getByRole("button", { name: "关闭" }).click();
      await expect(dialog).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：编辑 JSON 带准入字段或引用候选时保存被拒绝，页面指出字段位置`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size, { admitAndBind: true });
    const errors = watchErrors(client);
    try {
      await client.page.getByTestId("edit-json").click();
      const dialog = client.page.locator(".modal");
      const editor = dialog.getByLabel("目录文档 JSON");
      const document = JSON.parse(await editor.inputValue()) as {
        providers: Record<string, unknown>[]; models: Record<string, unknown>[]; bindings: Record<string, Record<string, unknown>>;
      };

      // 带准入字段：合同层拒绝，页面指出字段位置（models.0.admitted_at）
      const withAdmission = JSON.parse(JSON.stringify(document)) as typeof document;
      withAdmission.models[0].admitted_at = "2026-10-02T00:00:00Z";
      await editor.fill(JSON.stringify(withAdmission, null, 2));
      await dialog.getByRole("button", { name: "保存" }).click();
      await expect(dialog.getByRole("status")).toContainText("models.0.admitted_at");
      // 拒绝以后整份不写入：重新打开仍是原文档
      await dialog.getByRole("button", { name: "重置" }).click();
      await expect(editor).not.toHaveValue(/admitted_at/);

      // 部门默认引用候选（未准入的定义）：领域校验拒绝并指出 bindings.<部门> 位置
      const referencingCandidate = JSON.parse(JSON.stringify(document)) as typeof document;
      referencingCandidate.bindings = {
        product: { provider_id: "opencode-go", model_id: "not-admitted" },
      };
      await editor.fill(JSON.stringify(referencingCandidate, null, 2));
      await dialog.getByRole("button", { name: "保存" }).click();
      await expect(dialog.getByRole("status")).toContainText("bindings.product");
      // 关闭以后目录不变：部门默认仍绑定 glm-4.6
      await dialog.getByRole("button", { name: "关闭" }).click();
      await expect(client.page.getByTestId("default-model-product")).toHaveValue("glm-4.6");
      // 两次保存都被拒绝：浏览器会记录这两条被拒绝的响应，页面本身没有脚本错误
      expect(errors).toEqual([
        "Failed to load resource: the server responded with a status of 422 (Unprocessable Content)",
        "Failed to load resource: the server responded with a status of 409 (Conflict)",
      ]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：改地址保存前显示影响列表，取消以后目录不变，确认以后准入作废`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size, { admitAndBind: true });
    const errors = watchErrors(client);
    try {
      // 三个部门默认都绑定了 glm-4.6，准入有效
      await expect(client.page.getByTestId("provider-opencode-go").locator(".mm-summary")).toContainText("已准入 1 · 候选 0");

      // 编辑连接，改地址：影响列表由 catalog.change_impact 算出，保存前弹确认框
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "展开" }).click();
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "编辑" }).click();
      const form = client.page.locator(".mm-form");
      await expect(form.getByTestId("impact-notice")).toHaveCount(0);
      await form.getByTestId("provider-base-url").fill("https://changed.example/v1");
      await expect(form.getByTestId("impact-notice")).toContainText("准入作废");
      await expect(form.getByTestId("impact-notice")).toContainText("产品");

      // 取消：目录不变，连接地址仍是种子地址，准入仍然有效
      await form.getByTestId("submit-provider").click();
      const confirm = client.page.getByTestId("confirm-save");
      await expect(confirm).toBeVisible();
      await expect(confirm.getByTestId("confirm-save-list")).toContainText("glm-4.6");
      await confirm.getByTestId("confirm-save-no").click();
      await expect(confirm).toHaveCount(0);
      await expect(form.getByTestId("impact-notice")).toContainText("准入作废");
      await form.getByRole("button", { name: "取消" }).click();
      const summary = client.page.getByTestId("provider-opencode-go").locator(".mm-summary");
      await expect(summary).toContainText(/127\.0\.0\.1/);
      await expect(summary).toContainText("已准入 1 · 候选 0");

      // 再次改地址并确认：保存成功，准入作废
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "编辑" }).click();
      await client.page.locator(".mm-form").getByTestId("provider-base-url").fill("https://changed.example/v1");
      await client.page.locator(".mm-form").getByTestId("submit-provider").click();
      await client.page.getByTestId("confirm-save").getByTestId("confirm-save-yes").click();
      await expect(client.page.locator(".mm-form")).toHaveCount(0);
      await expect(client.page.getByTestId("provider-opencode-go").locator(".mm-summary")).toContainText("已准入 0 · 候选 1");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：删除被引用的连接时显示引用方并拒绝，删除没有引用的连接时确认框列出将一并删除的定义`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size, { admitAndBind: true });
    const errors = watchErrors(client);
    try {
      // 被三个部门默认引用：确认框列出引用方，确认按钮不可用
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "展开" }).click();
      await client.page.getByTestId("delete-opencode-go").click();
      const confirm = client.page.getByTestId("confirm-delete");
      await expect(confirm.getByTestId("confirm-delete-list")).toContainText("仍被引用，不能删除");
      await expect(confirm.getByTestId("confirm-delete-list")).toContainText("部门默认：产品");
      await expect(confirm.getByTestId("confirm-delete-yes")).toBeDisabled();
      await confirm.getByTestId("confirm-delete-no").click();
      await expect(confirm).toHaveCount(0);
      // 取消以后连接还在
      await expect(client.page.getByTestId("provider-opencode-go")).toBeVisible();

      // 清空部门默认：通过界面把三个部门都设为「未设置」并保存，连接不再被引用
      for (const department of ["product", "engineering", "quality"]) {
        await client.page.getByTestId(`default-model-${department}`).selectOption("");
      }
      await client.page.getByTestId("save-defaults").click();
      await expect(client.page.getByTestId("defaults-status")).toContainText("已保存部门默认");

      // 删除：确认框列出将一并删除的定义，确认以后连接消失（卡片已展开，直接点删除）
      await client.page.getByTestId("delete-opencode-go").click();
      await expect(confirm.getByTestId("confirm-delete-list")).toContainText("一并删除");
      await expect(confirm.getByTestId("confirm-delete-list")).toContainText("glm-4.6");
      await confirm.getByTestId("confirm-delete-yes").click();
      await expect(client.page.getByTestId("page-notice")).toContainText("已删除");
      await expect(client.page.getByTestId("provider-opencode-go")).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  test(`${label}：引用作废的定义时下拉框显示「无法使用：准入已作废」，所选模型未声明档位时禁用档位`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size, { admitAndBind: true });
    const errors = watchErrors(client);
    try {
      // 经界面改地址并确认：准入作废，三个部门默认的引用保留
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "展开" }).click();
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "编辑" }).click();
      await client.page.locator(".mm-form").getByTestId("provider-base-url").fill("https://changed.example/v1");
      await client.page.locator(".mm-form").getByTestId("submit-provider").click();
      await client.page.getByTestId("confirm-save").getByTestId("confirm-save-yes").click();
      await expect(client.page.locator(".mm-form")).toHaveCount(0);

      // 引用保留并显示「无法使用：准入已作废」
      await expect(client.page.getByTestId("unavailable-product")).toContainText("无法使用：准入已作废");
      await expect(client.page.getByTestId("unavailable-quality")).toContainText("无法使用：准入已作废");
      // 准入作废的定义不在下拉框的已准入选项里，但已保存的引用作为一项保留并选中
      await expect(client.page.getByTestId("default-model-product")).toHaveValue("glm-4.6");
      const options = await client.page.getByTestId("default-model-product").locator("option").allTextContents();
      expect(options).toEqual(["未设置", "glm-4.6"]);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });

  // 工单 #302 的验收：第一次配置「自定义」服务方案的完整路径。候选取自测试内的真实 HTTP 上游，
  // 其中一条上游模型 ID 带「/」（走查里真实遇到的写法），上游只给窗口不给输出上限
  test(`${label}：自定义方案添加连接、获取候选、预填的 ID 保存成功；缺一项容量写明缺少且不能保存；添加与保存都有成功提示`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      // 模型列表地址取自已保存连接的真实字段：测试内上游的端口由系统分配，不在测试里写死
      const modelsUrl = await client.page.evaluate(async (address: string) => {
        const listed = await (await fetch(`${address}/api/queries/catalog`)).json();
        const provider = (listed.data.providers as { id: string; models_url: string }[])
          .find((item) => item.id === "opencode-go");
        return provider!.models_url;
      }, backend.address);
      const baseUrl = modelsUrl.slice(0, -"/models".length);

      // 新建表单默认就是「自定义」：模型列表地址直接显示在表单上，不放在折叠的高级选项里（工单 #384）
      await client.page.getByRole("button", { name: "添加 Provider 配置" }).click();
      const form = client.page.locator(".mm-form");
      await expect(form.getByRole("button", { name: "自定义" })).toHaveAttribute("aria-pressed", "true");
      await expect(form.getByTestId("models-url-hint")).toBeVisible();

      // 填上模型列表地址：提示消失（设计规定地址由连接填写或取自服务方案，这条只改提示）
      await form.getByTestId("provider-models-url").fill(modelsUrl);
      await expect(form.getByTestId("models-url-hint")).toHaveCount(0);
      await form.getByTestId("provider-base-url").fill(baseUrl);
      await form.locator("label.mm-field").filter({ hasText: "ID" }).first().locator("input").fill("custom-go");
      await form.locator("label.mm-field").filter({ hasText: "名称" }).first().locator("input").fill("自定义上游");
      await form.locator("label.mm-field").filter({ hasText: "凭据引用" }).locator("input").fill("CUSTOM_GO_KEY");

      // 添加：表单收起的同时页面给出「已添加」
      await form.getByTestId("submit-provider").click();
      await expect(form).toHaveCount(0);
      await expect(client.page.getByTestId("page-notice")).toHaveText("已添加 Provider 配置。");

      // 配凭据：候选采集与连接测试都按真实凭据链请求测试内的上游
      await setKey(client, backend, "CUSTOM_GO_KEY");

      // 获取候选并建立访问定义：预填的 ID 是合法写法，上游模型 ID 保持带斜杠的原值，界面写明两者的区别。
      // 连接保存以后才能取候选：后端按连接的标识取地址与凭据，表单里填的内容还没进目录
      await client.page.getByTestId("provider-custom-go").getByRole("button", { name: "展开" }).click();
      await client.page.getByTestId("collect-custom-go").click();
      const candidates = client.page.getByTestId("candidates-custom-go");
      await expect(candidates).toContainText("cbcn/deepseek-v4.1-flash");
      await client.page.getByTestId("add-candidate-custom-go-cbcn/deepseek-v4.1-flash").click();
      const rowKey = "cbcn-deepseek-v4.1-flash";
      const row = client.page.locator(".mm-form");
      await expect(row.getByTestId(`row-id-${rowKey}`)).toHaveValue(rowKey);
      await expect(row.getByTestId(`row-model-${rowKey}`)).toHaveValue("cbcn/deepseek-v4.1-flash");
      await expect(row.getByTestId(`id-differs-${rowKey}`))
        .toHaveText(`发给上游的是「cbcn/deepseek-v4.1-flash」，ID「${rowKey}」只在本系统内使用。`);

      // 只预填到窗口：显示「缺少输出上限」，缺容量不能保存
      await expect(row.getByTestId(`capacity-issue-${rowKey}`)).toHaveText("缺少输出上限");
      await row.getByTestId("submit-provider").click();
      await expect(row.getByTestId("form-status")).toContainText("不能保存");

      // 补上输出上限：问题提示消失
      await row.getByTestId(`row-output-${rowKey}`).fill("16000");
      await expect(row.getByTestId(`capacity-issue-${rowKey}`)).toHaveCount(0);

      // 保存：预填的 ID 被后端接受（带斜杠的写法会被拒为「必须是非空简单标识符」），
      // 表单收起的同时页面给出「已保存」，模型表里出现这条定义
      await row.getByTestId("submit-provider").click();
      await expect(row).toHaveCount(0);
      await expect(client.page.getByTestId("page-notice")).toHaveText("已保存 Provider 配置。");
      await expect(client.page.getByTestId(`model-${rowKey}`)).toContainText("cbcn/deepseek-v4.1-flash");
      // 工单 #301：保存成功以后页头显示中文的已加载，不再是英文的 deleted
      await expect(client.page.locator(".mm-meta").first()).toContainText("配置状态 已加载");

      // 连接测试的结果文字写明读取的是哪个模型列表地址（工单 #302）
      await client.page.getByTestId("test-connection-custom-go").click();
      await expect(client.page.getByTestId("connection-result-custom-go"))
        .toContainText(`已读取模型列表地址 ${modelsUrl}：连接测试通过`);

      // 质检的图像输入提醒跟上下拉里当前选中的定义，不必保存部门默认（工单 #302）。
      // 预置的三部门默认绑定 fake-model：质检在选任何东西以前已有它的一条提醒；
      // 改选已准入的纯文本定义 glm-4.6，提醒同时换成这条定义的文字
      await expect(client.page.getByTestId("reminder-quality")).toContainText("当前模型 fake-model");
      await client.page.getByTestId("default-model-quality").selectOption("glm-4.6");
      await expect(client.page.getByTestId("reminder-quality")).toContainText("当前模型 glm-4.6");
      await expect(client.page.getByTestId("reminder-quality")).not.toContainText("fake-model");
      await expect(client.page.getByTestId("reminder-quality")).toContainText("图像输入");
      // 产品与工程没有建议能力：选中同一条定义没有提醒
      await client.page.getByTestId("default-model-product").selectOption("glm-4.6");
      await expect(client.page.getByTestId("reminder-product")).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  });
}

test("新建表单选择 OpenCode Go 与无协议头自定义地址自动填写字段", async () => {
  test.setTimeout(300_000);
  const { backend, client } = await openModels({ width: 1440, height: 900 });
  try {
    await client.page.getByRole("button", { name: "添加 Provider 配置" }).click();
    const form = client.page.locator(".mm-form");
    await form.getByRole("button", { name: "OpenCode Go" }).click();
    await expect(form.getByLabel("ID", { exact: true })).toHaveValue("opencode-go");
    await expect(form.getByLabel("名称", { exact: true })).toHaveValue("OpenCode Go");
    await expect(form.getByLabel("凭据引用")).toHaveValue("OPENCODE_GO_KEY");
    // 内置方案的模型列表地址只读显示在表单上（工单 #384），地址栏只读
    await expect(form.getByTestId("preset-models-url")).toContainText("模型列表地址");
    await expect(form.getByTestId("provider-base-url")).not.toBeEditable();
    await form.getByRole("button", { name: "自定义" }).click();
    await form.getByTestId("provider-base-url").fill("9router.huiju.asia/v1");
    await form.getByLabel("名称", { exact: true }).click();
    await expect(form.getByTestId("provider-base-url")).toHaveValue("https://9router.huiju.asia/v1");
    await expect(form.getByLabel("ID", { exact: true })).toHaveValue("9router.huiju.asia");
    await expect(form.getByLabel("凭据引用")).toHaveValue("HOST_9ROUTER_HUIJU_ASIA_KEY");
    await expect(form.getByTestId("provider-models-url")).toHaveValue("https://9router.huiju.asia/v1/models");
  } finally {
    await client.close();
    await backend.stop();
  }
});

test("获取模型列表失败时页面显示请求的地址与状态码（工单 #384）", async () => {
  test.setTimeout(300_000);
  const failing = createServer((_request, response) => {
    response.writeHead(404, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ error: { message: "not found" } }));
  });
  failing.listen(0, "127.0.0.1");
  await once(failing, "listening");
  const failingAddress = failing.address();
  if (failingAddress === null || typeof failingAddress === "string") throw new Error("HTTP 上游未启动");
  const { backend, client } = await openModels({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    // 真实返回 404 的上游：采集失败时页面写明请求的地址与状态码
    const modelsUrl = `http://127.0.0.1:${failingAddress.port}/v1/models`;
    await client.page.getByRole("button", { name: "添加 Provider 配置" }).click();
    const form = client.page.locator(".mm-form");
    await form.getByTestId("provider-base-url").fill(`http://127.0.0.1:${failingAddress.port}/v1`);
    await form.getByTestId("provider-models-url").fill(modelsUrl);
    await form.locator("label.mm-field").filter({ hasText: "ID" }).first().locator("input").fill("failing-up");
    await form.locator("label.mm-field").filter({ hasText: "名称" }).first().locator("input").fill("失败的上游");
    await form.locator("label.mm-field").filter({ hasText: "凭据引用" }).locator("input").fill("FAILING_UP_KEY");
    await form.getByTestId("credential-secret").fill(KEY);
    await form.getByTestId("submit-provider").click();
    await expect(form).toHaveCount(0);
    const provider = client.page.getByTestId("provider-failing-up");
    await provider.getByRole("button", { name: "展开" }).click();
    await provider.getByTestId("collect-failing-up").click();
    const candidates = provider.getByTestId("candidates-failing-up");
    await expect(candidates).toContainText(modelsUrl);
    await expect(candidates).toContainText("404");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
    failing.close();
  }
});

test("新建自定义连接保存 Key 后直接获取模型列表并测试空连接", async () => {
  test.setTimeout(300_000);
  const received: string[] = [];
  const upstream = createServer((request, response) => {
    received.push(request.headers.authorization ?? "");
    response.writeHead(request.headers.authorization === `Bearer ${KEY}` ? 200 : 401,
      { "Content-Type": "application/json" });
    response.end(JSON.stringify({ data: [{ id: "new-model" }] }));
  });
  upstream.listen(0, "127.0.0.1");
  await once(upstream, "listening");
  const address = upstream.address();
  if (address === null || typeof address === "string") throw new Error("HTTP 上游未启动");
  const { backend, client } = await openModels({ width: 1440, height: 900 });
  try {
    await client.page.getByRole("button", { name: "添加 Provider 配置" }).click();
    const form = client.page.locator(".mm-form");
    const base = `http://127.0.0.1:${address.port}/v1`;
    await form.getByTestId("provider-base-url").fill(base);
    await form.getByTestId("credential-secret").fill(KEY);
    await form.getByTestId("submit-provider").click();
    await expect(form).toHaveCount(0);
    const provider = client.page.getByTestId("provider-127.0.0.1");
    await provider.getByRole("button", { name: "展开" }).click();
    await provider.getByTestId("collect-127.0.0.1").click();
    await expect(provider.getByTestId("candidates-127.0.0.1")).toContainText("new-model");
    await provider.getByTestId("test-connection-127.0.0.1").click();
    await expect(provider.getByTestId("connection-result-127.0.0.1")).toContainText("连接测试通过");
    expect(received).toEqual([`Bearer ${KEY}`, `Bearer ${KEY}`]);
  } finally {
    await client.close();
    await backend.stop();
    upstream.close();
  }
});

// 从系统页返回时回到进入前的页面（设计说明第 3.3 节第 108 行，工单 #296）
test("从项目页进入模型管理，点「返回原界面」回到项目页", async () => {
  test.setTimeout(300_000);
  const { backend, client } = await openModels({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    await client.page.locator(".sidebar .nav-item", { hasText: "交付历史" }).first().click();
    await expect(client.page.locator(".path")).toContainText("交付历史");

    // 打开左侧栏进模型管理（宽屏下左侧栏常驻，直接点入口）
    await client.page.getByRole("button", { name: "模型管理", exact: true }).click();
    await expect(client.page.locator(".path")).toHaveText("模型管理");

    await client.page.getByRole("button", { name: "返回原界面" }).click();
    await expect(client.page.locator(".path")).toContainText("交付历史");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});
// 工单 #385 / #563 验收第 1 条：勾选两个模型加入后自动测试通过并进入部门默认
test("新建自定义连接，获取候选，勾选两个模型（带容量与就地填写）点加入，自动测试通过并进入部门默认", async () => {
  test.setTimeout(300_000);
  const { backend, client } = await openModels({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const { chatBaseUrl, modelsUrl } = await client.page.evaluate(async (address: string) => {
      const listed = await (await fetch(`${address}/api/queries/catalog`)).json();
      const preset = (listed.data.presets.presets as { id: string; base_urls: Record<string, string> }[])
        .find((item) => item.id === "opencode-go");
      const provider = (listed.data.providers as { id: string; models_url: string }[])
        .find((item) => item.id === "opencode-go");
      return { chatBaseUrl: preset!.base_urls.chat_completions, modelsUrl: provider!.models_url };
    }, backend.address);

    // 新建自定义连接，只粘贴 Key、填基址与模型列表地址，点「添加」
    await client.page.getByRole("button", { name: "添加 Provider 配置" }).click();
    const form = client.page.locator(".mm-form");
    await form.getByTestId("provider-models-url").fill(modelsUrl);
    await form.getByTestId("provider-base-url").fill(chatBaseUrl);
    await form.locator("label.mm-field").filter({ hasText: "ID" }).first().locator("input").fill("custom-p");
    await form.locator("label.mm-field").filter({ hasText: "名称" }).first().locator("input").fill("自定义测试");
    await form.locator("label.mm-field").filter({ hasText: "凭据引用" }).locator("input").fill("CUSTOM_P_KEY");
    await form.getByTestId("credential-secret").fill("custom-secret-key");
    await form.getByTestId("submit-provider").click();
    await expect(form).toHaveCount(0);
    await expect(client.page.getByTestId("page-notice")).toHaveText("已添加 Provider 配置。");

    // 展开连接，获取模型列表
    const providerCard = client.page.getByTestId("provider-custom-p");
    await providerCard.getByRole("button", { name: "展开" }).click();
    await providerCard.getByTestId("collect-custom-p").click();
    const candidates = providerCard.getByTestId("candidates-custom-p");
    await expect(candidates).toBeVisible();

    // 勾选两个模型：vision-model（列表带容量）与 cbcn/deepseek-v4.1-flash（缺少容量并在就地填写）
    await candidates.getByTestId("candidate-check-vision-model").check();
    await candidates.getByTestId("candidate-check-cbcn/deepseek-v4.1-flash").check();

    // 未补齐容量前，「加入」按钮不可用，并提示缺少输出上限
    await expect(candidates.getByTestId("candidates-issue-custom-p")).toHaveText("缺少输出上限");
    await expect(candidates.getByTestId("join-candidates-custom-p")).toBeDisabled();

    // 就地填写缺少的输出上限
    await candidates.getByTestId("candidate-output-cbcn/deepseek-v4.1-flash").fill("16000");
    await expect(candidates.getByTestId("candidates-issue-custom-p")).toHaveCount(0);
    await expect(candidates.getByTestId("join-candidates-custom-p")).toBeEnabled();

    // 点一次「加入」：保存后自动执行模型测试并通过
    await candidates.getByTestId("join-candidates-custom-p").click();

    // 两个模型在模型表中出现，且自动模型测试通过
    await expect(providerCard.getByTestId("model-vision-model")).toBeVisible();
    await expect(providerCard.getByTestId("model-cbcn-deepseek-v4.1-flash")).toBeVisible();
    await expect(providerCard.getByTestId("model-result-vision-model")).toContainText("模型测试通过");
    await expect(providerCard.getByTestId("model-result-cbcn-deepseek-v4.1-flash")).toContainText("模型测试通过");

    // 两个模型均已准入并出现在部门默认的下拉选项中
    await expect(client.page.getByTestId("default-model-product").locator('option[value="vision-model"]')).toBeAttached();
    await expect(client.page.getByTestId("default-model-product").locator('option[value="cbcn-deepseek-v4.1-flash"]')).toBeAttached();
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});

// 工单 #385 / #563 验收第 2 条：手动添加模型保存后自动测试一次，失败留在候选，修正后通过
test("手动添加一个模型并保存自动测试一次；上游返回错误该行显示原因并留在候选，修正后测试通过", async () => {
  test.setTimeout(300_000);
  let failUpstream = true;
  const upstream = createServer((_request, response) => {
    if (failUpstream) {
      response.writeHead(500, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ error: { message: "upstream internal failure", type: "server_error" } }));
    } else {
      response.writeHead(200, { "Content-Type": "text/event-stream" });
      const chunk = `data: ${JSON.stringify({
        id: "chat-1",
        object: "chat.completion.chunk",
        created: 1,
        model: "manual-failing-model",
        choices: [{ index: 0, delta: { content: "pong" }, finish_reason: "stop" }],
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
      })}\n\n`;
      const done = "data: [DONE]\n\n";
      response.end(chunk + done);
    }
  });

  const address = await new Promise<string>((resolve) => {
    upstream.listen(0, "127.0.0.1", () => {
      const port = (upstream.address() as AddressInfo).port;
      resolve(`http://127.0.0.1:${port}/v1`);
    });
  });

  const { backend, client } = await openModels({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    // 新建连接指向测试内可控上游
    await client.page.getByRole("button", { name: "添加 Provider 配置" }).click();
    const form = client.page.locator(".mm-form");
    await form.getByTestId("provider-base-url").fill(address);
    await form.locator("label.mm-field").filter({ hasText: "ID" }).first().locator("input").fill("fail-test-p");
    await form.locator("label.mm-field").filter({ hasText: "名称" }).first().locator("input").fill("可控上游连接");
    await form.locator("label.mm-field").filter({ hasText: "凭据引用" }).locator("input").fill("FAIL_TEST_KEY");
    await form.getByTestId("credential-secret").fill("secret");

    // 手动添加一个模型定义并保存
    await form.getByTestId("add-model-row").click();
    await form.getByTestId("row-id-model-1").fill("manual-fail");
    await form.getByTestId("row-model-manual-fail").fill("manual-failing-model");
    await form.getByTestId("row-window-manual-fail").fill("100000");
    await form.getByTestId("row-output-manual-fail").fill("4096");
    await form.getByTestId("submit-provider").click();
    await expect(form).toHaveCount(0);
    await expect(client.page.getByTestId("page-notice")).toHaveText("已添加 Provider 配置。");

    // 展开连接：保存后自动测试一次，上游返回错误，该行显示原因并留在候选
    const card = client.page.getByTestId("provider-fail-test-p");
    await card.getByRole("button", { name: "展开" }).click();
    await expect(card.getByTestId("model-manual-fail")).toBeVisible();
    await expect(card.getByTestId("model-result-manual-fail")).toContainText("模型测试未通过：Model provider returned HTTP 500");
    await expect(card.getByTestId("model-manual-fail")).toContainText("候选");
    // 未准入的模型不在部门默认下拉中
    await expect(client.page.getByTestId("default-model-product").locator("option", { hasText: "manual-fail" })).toHaveCount(0);

    // 修正上游错误，再次测试通过
    failUpstream = false;
    await card.getByTestId("row-test-manual-fail").click();
    await expect(card.getByTestId("model-result-manual-fail")).toContainText("模型测试通过");
    await expect(card.getByTestId("model-manual-fail")).toContainText("已准入");
    // 准入后出现在部门默认选项中
    await expect(client.page.getByTestId("default-model-product").locator("option", { hasText: "manual-fail" })).toBeAttached();
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
    upstream.close();
  }
});
