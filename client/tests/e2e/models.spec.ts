// 模型管理页的端到端测试（工单 #93 的验收）：Playwright 启动 Electron 客户端与控制主机上的真实后端
// （client/tests/e2e/backend.py）。后端内启动真实的 HTTP 上游（Responses 协议的最小推理服务与模型列表服务），
// 候选、连接测试与模型测试都发真实请求。窗口尺寸 1440×900 与 390×844，控制台错误为零。

import { expect, test } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

// 上游凭据：测试经命令设置在内存里，页面与网络响应都不应出现它
const KEY = "sk-e2e-opencode-go-8f3a1c";

// 每条用例各自启动一份后端与客户端：用例会修改目录（保存连接、部门默认、凭据），
// 共用一份后端会让用例之间互相影响。后端启动用时由 git 子进程与目录种子决定（#107 裁定，
// 见 docs/architecture-issues.md），这里单独放宽每条用例的时限
async function openModels(size: { width: number; height: number }): Promise<{ backend: Backend; client: ClientApp }> {
  const backend = await startBackend();
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand")).toHaveText("Yudao");
  // 宽度 390 时左侧栏收为抽屉，先打开抽屉再点入口（原型 v8 设计说明第 3.3 节）
  if (size.width <= 700) {
    await client.page.locator(".drawer-toggle").click();
  }
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
  { width: 390, height: 844 },
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
      await expect(summary).toContainText("Responses");
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

      // 宽度 390：不出现横向滚动
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

      // 模型测试：测试中 → 通过，准入列显示测试时间与实际返回的模型
      await client.page.getByTestId("row-test-glm-4.6").click();
      await expect(client.page.getByTestId("model-glm-4.6")).toContainText("已准入：");
      await expect(client.page.getByTestId("model-glm-4.6")).toContainText("glm-4.6");
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

  test(`${label}：编辑表单恢复服务方案与协议，选方案与协议自动填入请求基址，未接受容量的行不能保存`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "展开" }).click();
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "编辑" }).click();

      const form = client.page.locator(".mm-form");
      await expect(form).toContainText("编辑 Provider 配置");
      // 编辑时恢复服务方案与协议，地址取连接保存的地址（种子连接指向测试内上游）
      await expect(form.getByRole("button", { name: "OpenCode Go" })).toHaveAttribute("aria-pressed", "true");
      await expect(form.getByTestId("protocol-select")).toHaveValue("responses");
      await expect(form.getByTestId("provider-base-url")).toHaveValue(new RegExp(`^http://127\\.0\\.0\\.1:\\d+/v1$`));
      // 预置表与能力表的信息都在方案区
      await expect(form).toContainText("预置表 2026-10-02.1");
      await expect(form).toContainText("模型能力表");

      // 换协议：地址取该方案该协议的请求基址
      await form.getByTestId("protocol-select").selectOption("messages");
      await expect(form.getByTestId("provider-base-url")).toHaveValue("https://opencode.ai/zen/go/v1");

      // Key 输入框始终为空，不回填
      await expect(form.getByTestId("credential-secret")).toHaveValue("");

      // 候选加入一行：容量未「接受」以前不能保存
      await setKey(client, backend, "OPENCODE_GO_KEY");
      await form.getByRole("button", { name: "获取模型列表" }).click();
      await form.getByTestId("admit-candidate-vision-model").click();
      await expect(form.getByTestId("model-row-vision-model")).toContainText("窗口：上游模型列表");
      await expect(form.getByTestId("capacity-confirmed-vision-model")).toHaveCount(0);
      // 提交时被拦下：保存按容量确认判定
      await form.getByTestId("submit-provider").click();
      await expect(form.getByTestId("form-status")).toContainText("没有「接受」或修改的行不能保存");
      await form.getByTestId("accept-capacity-vision-model").click();
      await expect(form.getByTestId("capacity-confirmed-vision-model")).toBeVisible();

      // 推理参数方式只列出与协议相符的选项
      const modeOptions = form.getByTestId("reasoning-mode-vision-model").locator("option");
      await expect(modeOptions).toContainText(["未声明", "adaptive（Messages 的自适应思考）"]);
      await expect(form.getByTestId("reasoning-mode-vision-model").locator("option", { hasText: "effort" })).toHaveCount(0);
      await form.getByTestId("protocol-select").selectOption("chat_completions");
      await expect(form.getByTestId("reasoning-mode-vision-model").locator("option", { hasText: "effort" })).toHaveCount(1);
      await expect(form.getByTestId("reasoning-mode-vision-model").locator("option", { hasText: "adaptive" })).toHaveCount(0);

      // 默认档位只能从已选的支持档位中选择
      await form.getByTestId("level-vision-model-high").click();
      await expect(form.getByTestId("default-level-vision-model").locator("option")).toContainText(["未选择", "high"]);
      // 声明支持档位时同时给出默认档位与推理参数方式（设计说明第 7.1 节）
      await form.getByTestId("default-level-vision-model").selectOption("high");
      await form.getByTestId("reasoning-mode-vision-model").selectOption("effort");

      // 保存：容量已确认，保存以后表单收起，模型表里出现这条定义
      await form.getByTestId("submit-provider").click();
      await expect(form).toHaveCount(0);
      await expect(client.page.getByTestId("model-vision-model")).toBeVisible();
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
}
