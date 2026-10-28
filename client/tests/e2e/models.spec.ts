// 模型管理页的端到端测试（工单 #93 的验收）：Playwright 打开 Chromium 页面，页面由真实后端提供
// （client/tests/e2e/backend.py）。后端内启动真实的 HTTP 上游（Responses 协议的最小推理服务与模型列表服务），
// 候选、连接测试与模型测试都发真实请求。窗口尺寸 1440×900 与 1920×1080，控制台错误为零。

import { expect,test } from "@playwright/test";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { startBackend,startClient,type Backend,type ClientApp } from "./fixtures";

// 上游凭据：测试经命令设置在内存里，页面与网络响应都不应出现它
const KEY = "sk-e2e-opencode-go-8f3a1c";

// 每条用例各自启动一份后端与客户端：用例会修改目录（保存连接、部门默认、凭据），
// 共用一份后端会让用例之间互相影响。后端启动用时由 git 子进程与目录种子决定（#107 裁定，
// 见 docs/archive/architecture-issues-2026-09-10.md），这里单独放宽每条用例的时限
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

for (const size of [{ width: 1440, height: 900 }]) {
  const label = `${size.width}×${size.height}`;

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

  test(`${label}：勾「写入 .env」时不合规的凭据引用让保存不可用并写明原因`, async () => {
    test.setTimeout(300_000);
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      // 连接表单：勾「写入 .env」时凭据引用旁写出键名规则，不合规时「保存 Key」不可用并写明原因
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "展开" }).click();
      await client.page.getByTestId("provider-opencode-go").getByRole("button", { name: "编辑" }).click();
      const form = client.page.locator(".mm-form");
      const refInput = form.locator("label.mm-field").filter({ hasText: "凭据引用" }).locator("input");
      await refInput.fill("trial-model-key");
      await form.getByTestId("credential-secret").fill(KEY);
      await form.getByTestId("credential-persist").check();
      await expect(form.getByTestId("credential-ref-rule")).toContainText("字母、数字与下划线");
      await expect(form.getByTestId("credential-ref-issue")).toContainText("TRIAL_MODEL_KEY");
      await expect(form.getByTestId("save-credential")).toBeDisabled();
      await expect(form.getByTestId("save-credential-hint")).toContainText("不能写进 .env");

      // 换成合规的写法：原因消失，「保存 Key」可用
      await refInput.fill("TRIAL_MODEL_KEY");
      await expect(form.getByTestId("credential-ref-issue")).toHaveCount(0);
      await expect(form.getByTestId("save-credential")).toBeEnabled();
      await form.getByRole("button", { name: "取消" }).click();

      // 页面上「凭据」那一节：选「只在本进程有效」时写重启后要重新提供
      await client.page.getByTestId("page-cred-memory").check();
      await expect(client.page.getByTestId("page-cred-restart-hint")).toContainText("重启后需要重新提供");
      await client.page.getByTestId("page-cred-ref").fill("trial-model-key");
      await client.page.getByTestId("page-cred-secret").fill(KEY);
      // 只写内存时没有键名要求：可以保存
      await expect(client.page.getByTestId("page-cred-ref-rule")).toHaveCount(0);
      await expect(client.page.getByTestId("page-cred-save")).toBeEnabled();
      // 勾「写入 .env」：规则出现，不合规的引用让「保存凭据」不可用并写明原因
      await client.page.getByTestId("page-cred-dotenv").check();
      await expect(client.page.getByTestId("page-cred-restart-hint")).toHaveCount(0);
      await expect(client.page.getByTestId("page-cred-ref-rule")).toContainText("字母、数字与下划线");
      await expect(client.page.getByTestId("page-cred-save")).toBeDisabled();
      await expect(client.page.getByTestId("page-cred-ref-issue")).toContainText("TRIAL_MODEL_KEY");
      await expect(client.page.getByTestId("page-cred-save-hint")).toContainText("不能写进 .env");
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

  
  
  }





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

// 上游这次失败给出的错误原文（工单 #1209）：模型测试失败时界面写的是上游给的这一句，
// 断言与测试内的上游共用同一个变量，上游换一句话时用例跟着走，不必再改第二处
const UPSTREAM_ERROR_MESSAGE = "upstream internal failure";

// 工单 #385 / #563 验收第 2 条：手动添加模型保存后自动测试一次，失败留在候选，修正后通过
test("手动添加一个模型并保存自动测试一次；上游返回错误该行显示原因并留在候选，修正后测试通过", async () => {
  test.setTimeout(300_000);
  let failUpstream = true;
  const upstream = createServer((_request, response) => {
    if (failUpstream) {
      response.writeHead(500, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ error: { message: UPSTREAM_ERROR_MESSAGE, type: "server_error" } }));
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

    // 展开连接：保存后自动测试一次，上游返回错误，该行显示上游给出的原因并留在候选
    const card = client.page.getByTestId("provider-fail-test-p");
    await card.getByRole("button", { name: "展开" }).click();
    await expect(card.getByTestId("model-manual-fail")).toBeVisible();
    // 断言落在「这一行写的是上游原文」上，不钉死某一个英文字句（工单 #1209）：前缀与原文分开核对，
    // 界面以后在原文前后多写一句、或上游换一句原文，这条用例都不必改
    const result = card.getByTestId("model-result-manual-fail");
    await expect(result).toContainText("模型测试未通过");
    await expect(result).toContainText(UPSTREAM_ERROR_MESSAGE);
    // 反向：界面写死成状态码那句（不再写上游原文）时，上面一条会红，这里也再核对它没有退回那句
    await expect(result).not.toContainText("Model provider returned HTTP");
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
