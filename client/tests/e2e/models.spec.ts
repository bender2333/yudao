// 模型管理页的端到端测试（工单 #1297）：Playwright 打开 Chromium 页面，页面由真实后端提供
// （client/tests/e2e/backend.py）。用例在测试内启动真实的 HTTP 上游：模型列表与 Chat Completions
// 推理都按真实协议应答（写法照 harness/tests/protocol_helpers.py），不用假对象。
//
// 主路径：填写地址与 Key → 获取 → 搜索筛选 → 勾选两个模型 → 补全参数与验证 → 已启用 →
// 三个部门自动使用第一个启用的模型 → 刷新页面以后状态仍在。
// 失败路径：Key 被拒绝、地址不可达、空列表、单个模型验证失败、容量未知后手填继续、搜索无结果；
// 原因都写在被操作的对象旁边，同一个视口里看得到。
// 取消勾选：被部门使用的模型取消不了并写明引用方；进行中的模型取消以后迟到的结果不启用它。

import { expect, test } from "@playwright/test";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

// 上游的凭据：页面填的 Key 必须与它一致，否则上游按真实服务的方式拒绝
const UPSTREAM_KEY = "sk-e2e-models-2f8c41";

// 上游给的模型列表：容量、图像输入与推理由这里给出，页面按服务端的值显示
const UPSTREAM_MODELS = [
  { id: "trial-alpha", limit: { context: 200000, output: 32000 } },
  { id: "trial-beta", limit: { context: 128000, output: 16000 } },
  { id: "trial-vision", limit: { context: 128000, output: 16000 }, modalities: ["text", "image"] },
  // 上游没有给容量：这一条要手填窗口与输出上限才能继续
  { id: "trial-unknown" },
];

// 这个前缀下的模型：上游拒绝推理（HTTP 403），模型测试因此不通过
const DENIED_MODELS = [{ id: "trial-denied", limit: { context: 64000, output: 8000 } }];

// 这个前缀下的模型：推理慢，用例在测试进行中取消选用
const SLOW_MODELS = [{ id: "trial-slow", limit: { context: 200000, output: 32000 } }];

// 推理慢时的停顿（毫秒）：够用例在测试进行中取消，又不至于让用例等太久
const SLOW_DELAY_MS = 4000;

type ChatRequest = {
  model?: string;
  messages?: { role?: string }[];
  tools?: { function?: { name?: string } }[];
};

type Upstream = {
  base: string;
  close: () => Promise<void>;
};

// 测试内启动的真实 HTTP 上游（工单 #1297）：
// GET {前缀}/v1/models 给模型列表；POST {前缀}/v1/chat/completions 按 Chat Completions 的 SSE 回答。
// 前缀决定这一份上游的行为：empty 是空列表，denied 的推理被上游拒绝，slow 的推理慢。
async function startUpstream(): Promise<Upstream> {
  const server = createServer((request, response) => {
    void handleUpstream(request, response);
  });
  const port = await new Promise<number>((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve((server.address() as AddressInfo).port));
  });
  return {
    base: `http://127.0.0.1:${port}`,
    close: () => new Promise<void>((resolve) => {
      server.close(() => resolve());
    }),
  };
}

async function handleUpstream(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const parts = (request.url ?? "/").split("/").filter((part) => part !== "");
  const scenario = parts[0] === "v1" ? "" : parts[0] ?? "";
  if ((request.url ?? "").endsWith("/models")) {
    if (!authorized(request)) {
      response.writeHead(401, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ error: { message: "invalid api key", type: "authentication_error" } }));
      return;
    }
    const models = scenario === "empty" ? []
      : scenario === "denied" ? DENIED_MODELS
        : scenario === "slow" ? SLOW_MODELS
          : UPSTREAM_MODELS;
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ data: models }));
    return;
  }
  if ((request.url ?? "").endsWith("/chat/completions")) {
    const payload = JSON.parse(await readBody(request)) as ChatRequest;
    if (scenario === "denied") {
      response.writeHead(403, { "Content-Type": "application/json" });
      response.end(JSON.stringify({
        error: { message: "当前 Key 没有调用这个模型的权限", type: "permission_error" },
      }));
      return;
    }
    if (scenario === "slow") {
      await new Promise((resolve) => setTimeout(resolve, SLOW_DELAY_MS));
    }
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    response.end(chatStream(payload));
    return;
  }
  response.writeHead(404, { "Content-Type": "application/json" });
  response.end("{}");
}

// 自定义服务按 Bearer 带凭据（模型管理设计说明第 4.2 节）
function authorized(request: IncomingMessage): boolean {
  return request.headers.authorization === `Bearer ${UPSTREAM_KEY}`;
}

function readBody(request: IncomingMessage): Promise<string> {
  return new Promise<string>((resolve) => {
    let body = "";
    request.on("data", (chunk: Buffer) => {
      body += chunk.toString("utf8");
    });
    request.on("end", () => resolve(body));
  });
}

// Chat Completions 的流式回答（真实 SSE）：请求带工具时给一次完整的工具调用，
// 收到工具结果以后再回答一段文字——模型测试的工具往返因此真的走一遍
function chatStream(payload: ChatRequest): string {
  const hasToolResult = (payload.messages ?? []).some((message) => message.role === "tool");
  const tool = hasToolResult ? null : payload.tools?.[0];
  const delta = tool
    ? {
      tool_calls: [{
        index: 0,
        id: "probe-call",
        type: "function",
        function: { name: tool.function?.name ?? "yudao_model_test", arguments: "{}" },
      }],
    }
    : { content: "pong" };
  const chunk = {
    id: "chat-1",
    object: "chat.completion.chunk",
    created: 1,
    model: payload.model ?? "trial-model",
    choices: [{ index: 0, delta, finish_reason: tool ? "tool_calls" : "stop" }],
    usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 },
  };
  return `data: ${JSON.stringify(chunk)}\n\ndata: [DONE]\n\n`;
}

// 每条用例各自启动一份后端与客户端：用例会修改目录（连接、选用、部门默认），
// 共用一份后端会让用例之间互相影响
async function openModels(size: { width: number; height: number }): Promise<{ backend: Backend; client: ClientApp }> {
  const backend = await startBackend();
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

// 服务端按设计用 409 拒绝命令时浏览器自己记的那一条不算应用错误：
// 界面已经把原因显示给用户（与 building、home 等用例同一个处理）
function watchErrorsAllowingRejectedCommands(client: ClientApp): string[] {
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

// 填地址与 Key，点「获取模型」：连接、Key 与候选一步做完
async function connectService(client: ClientApp, address: string, key: string): Promise<void> {
  await client.page.getByTestId("connection-add").click();
  await client.page.getByTestId("connect-address").fill(address);
  await client.page.getByTestId("connect-key").fill(key);
  await client.page.getByTestId("connect-submit").click();
}

// 这一份连接对应的卡片：按地址找，不用连接标识（标识由服务端按主机生成）
function connectionCard(client: ClientApp, address: string) {
  return client.page.getByTestId("connection-card").filter({ hasText: address });
}

// 部门当前选中的模型（选项上的文字）
async function departmentChoice(client: ClientApp, department: string): Promise<string> {
  return client.page.getByTestId(`department-model-${department}`).evaluate(
    (element) => (element as HTMLSelectElement).selectedOptions[0]?.textContent ?? "",
  );
}

// 端到端后端预置的部门默认指向测试用的假模型（测试装置的产物，真实部署里没有）：
// 先在页面上把三个部门改成「未设置」，接着第一个启用的模型才会自动成为它们的默认
async function clearDepartmentDefaults(client: ClientApp): Promise<void> {
  for (const department of ["product", "engineering", "quality"]) {
    await client.page.getByTestId(`department-model-${department}`).selectOption("");
    // 部门默认是整份保存的：上一次保存写完以后再改下一个，
    // 否则两次改动叠在一起会被服务端按版本过期拒绝
    await expect(client.page.getByTestId(`department-status-${department}`))
      .toContainText("已取消这个部门的模型");
  }
}

for (const size of [{ width: 1440, height: 900 }]) {
  const label = `${size.width}×${size.height}`;

  test(`${label}：填地址与 Key → 获取 → 搜索筛选 → 勾选两个模型 → 已启用 → 三个部门自动使用 → 刷新后仍在`, async () => {
    test.setTimeout(300_000);
    const upstream = await startUpstream();
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      const address = `${upstream.base}/v1`;
      // 三个部门先没有默认模型，第一个启用的模型才会自动填上
      await clearDepartmentDefaults(client);
      await connectService(client, address, UPSTREAM_KEY);

      // 候选到了：连接卡片上写明最近一次获取的结果与时间
      const card = connectionCard(client, address);
      await expect(card.getByTestId("connection-fetch")).toContainText("已获取 4 个模型", { timeout: 60_000 });

      // 筛选：容量未知的候选只在「全部模型」里
      await client.page.getByTestId("candidate-filter-all").click();
      await expect(client.page.getByTestId("candidate-count")).toContainText("找到 4 个模型");
      await expect(client.page.getByTestId("candidate-trial-unknown")).toBeVisible();

      // 搜索：按上游模型 ID 找
      await client.page.getByTestId("candidate-search").fill("trial-");
      await expect(client.page.getByTestId("candidate-count")).toContainText("找到 4 个模型");
      await client.page.getByTestId("candidate-search").fill("trial-alpha");
      await expect(client.page.getByTestId("candidate-count")).toContainText("找到 1 个模型");
      await expect(client.page.getByTestId("candidate-trial-alpha")).toBeVisible();
      await expect(client.page.getByTestId("candidate-trial-beta")).toHaveCount(0);
      await client.page.getByTestId("candidate-search").fill("");

      // 「可自动配置」只留容量已知的候选
      await client.page.getByTestId("candidate-filter-auto").click();
      await expect(client.page.getByTestId("candidate-trial-unknown")).toHaveCount(0);
      await client.page.getByTestId("candidate-filter-all").click();
      await expect(client.page.getByTestId("candidate-trial-unknown")).toBeVisible();

      // 勾选第一个模型：补全参数与验证通过以后启用
      await client.page.getByTestId("candidate-check-trial-alpha").check();
      await expect(client.page.getByTestId("selected-status-trial-alpha")).toContainText("已启用", { timeout: 120_000 });
      // 第一个启用的模型自动供三个部门使用
      expect(await departmentChoice(client, "product")).toContain("trial-alpha");
      expect(await departmentChoice(client, "engineering")).toContain("trial-alpha");
      expect(await departmentChoice(client, "quality")).toContain("trial-alpha");

      // 再勾选一个：同样启用，部门默认不变
      await client.page.getByTestId("candidate-check-trial-beta").check();
      await expect(client.page.getByTestId("selected-status-trial-beta")).toContainText("已启用", { timeout: 120_000 });
      expect(await departmentChoice(client, "product")).toContain("trial-alpha");

      // 刷新页面以后状态仍在
      await client.page.reload();
      await expect(client.page.locator(".path")).toHaveText("模型管理");
      await expect(client.page.getByTestId("selected-status-trial-alpha")).toContainText("已启用");
      await expect(client.page.getByTestId("selected-status-trial-beta")).toContainText("已启用");
      expect(await departmentChoice(client, "quality")).toContain("trial-alpha");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
      await upstream.close();
    }
  });

  test(`${label}：Key 被拒绝、地址不可达、空列表，原因写在各自的连接卡片旁`, async () => {
    test.setTimeout(300_000);
    const upstream = await startUpstream();
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      // Key 被拒绝：上游按真实的认证方式拒绝
      const rejectAddress = `${upstream.base}/v1`;
      await connectService(client, rejectAddress, "sk-wrong-key");
      const rejectCard = connectionCard(client, rejectAddress);
      await expect(rejectCard.getByTestId("connection-fetch")).toContainText("HTTP 401", { timeout: 60_000 });
      await expect(rejectCard.getByTestId("connection-fetch")).toContainText("服务拒绝了这个 API Key");

      // 空列表：服务连上了，但没有返回任何模型
      const emptyAddress = `${upstream.base}/empty/v1`;
      await connectService(client, emptyAddress, UPSTREAM_KEY);
      const emptyCard = connectionCard(client, emptyAddress);
      await expect(emptyCard.getByTestId("connection-fetch")).toContainText("已连接，但服务没有返回任何模型", { timeout: 60_000 });

      // 地址不可达：连不上那个地址
      const deadAddress = "http://127.0.0.1:1/v1";
      await connectService(client, deadAddress, UPSTREAM_KEY);
      const deadCard = connectionCard(client, deadAddress);
      await expect(deadCard.getByTestId("connection-fetch")).toContainText("连接失败", { timeout: 60_000 });
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
      await upstream.close();
    }
  });

  test(`${label}：单个模型验证失败、容量未知后手填继续、搜索无结果，原因写在模型行旁`, async () => {
    test.setTimeout(300_000);
    const upstream = await startUpstream();
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      // 单个模型验证失败：上游拒绝这个模型的推理
      const deniedAddress = `${upstream.base}/denied/v1`;
      await connectService(client, deniedAddress, UPSTREAM_KEY);
      await expect(client.page.getByTestId("candidate-trial-denied")).toBeVisible({ timeout: 60_000 });
      await client.page.getByTestId("candidate-check-trial-denied").check();
      await expect(client.page.getByTestId("selected-status-trial-denied")).toContainText("验证失败", { timeout: 120_000 });
      await expect(client.page.getByTestId("selected-error-trial-denied")).toContainText("HTTP 403");
      // 失败以后这一行还在，可以重新验证或取消选用
      await expect(client.page.getByTestId("selected-retry-trial-denied")).toBeVisible();

      // 容量未知：上游没有给容量，缺哪一项写在这一行
      const address = `${upstream.base}/v1`;
      await connectService(client, address, UPSTREAM_KEY);
      await client.page.getByTestId("candidate-filter-all").click();
      await expect(client.page.getByTestId("candidate-trial-unknown")).toBeVisible({ timeout: 60_000 });
      await client.page.getByTestId("candidate-check-trial-unknown").check();
      await expect(client.page.getByTestId("selected-status-trial-unknown")).toContainText("容量未知", { timeout: 60_000 });
      await expect(client.page.getByTestId("selected-capacity-trial-unknown")).toContainText("缺少窗口与输出上限");

      // 手填窗口与输出上限以后继续：补全参数与验证通过，模型启用
      await client.page.getByTestId("capacity-window-trial-unknown").fill("200000");
      await client.page.getByTestId("capacity-output-trial-unknown").fill("32000");
      await client.page.getByTestId("selected-continue-trial-unknown").click();
      await expect(client.page.getByTestId("selected-status-trial-unknown")).toContainText("已启用", { timeout: 120_000 });

      // 搜索无结果：写明没有匹配
      await client.page.getByTestId("candidate-search").fill("没有这个模型");
      await expect(client.page.getByTestId("candidate-empty")).toContainText("没有符合条件的模型");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
      await upstream.close();
    }
  });

  test(`${label}：取消勾选被部门使用的模型被拒绝并写明引用方`, async () => {
    test.setTimeout(300_000);
    const upstream = await startUpstream();
    const { backend, client } = await openModels(size);
    const errors = watchErrorsAllowingRejectedCommands(client);
    try {
      const address = `${upstream.base}/v1`;
      // 三个部门先没有默认模型，第一个启用的模型才会自动填上
      await clearDepartmentDefaults(client);
      await connectService(client, address, UPSTREAM_KEY);
      await client.page.getByTestId("candidate-check-trial-alpha").check();
      await expect(client.page.getByTestId("selected-status-trial-alpha")).toContainText("已启用", { timeout: 120_000 });
      // 三个部门都在用它
      expect(await departmentChoice(client, "product")).toContain("trial-alpha");

      // 取消勾选：被部门引用，服务端拒绝，引用方写在模型行旁
      await client.page.getByTestId("selected-remove-trial-alpha").click();
      await expect(client.page.getByTestId("selected-status-text-trial-alpha")).toContainText("仍被引用，无法移除");
      await expect(client.page.getByTestId("selected-status-text-trial-alpha")).toContainText("部门默认：产品");
      // 它仍然启用着，部门仍然用它
      await expect(client.page.getByTestId("selected-status-trial-alpha")).toContainText("已启用");
      expect(await departmentChoice(client, "engineering")).toContain("trial-alpha");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
      await upstream.close();
    }
  });

  test(`${label}：取消勾选进行中的模型，迟到的结果不启用它`, async () => {
    test.setTimeout(300_000);
    const upstream = await startUpstream();
    const { backend, client } = await openModels(size);
    const errors = watchErrors(client);
    try {
      const address = `${upstream.base}/slow/v1`;
      // 三个部门先没有默认模型：迟到的结果如果启用了这个模型，这里会看得到
      await clearDepartmentDefaults(client);
      await connectService(client, address, UPSTREAM_KEY);
      await expect(client.page.getByTestId("candidate-trial-slow")).toBeVisible({ timeout: 60_000 });

      // 勾选以后模型测试在进行中（上游的推理慢）
      await client.page.getByTestId("candidate-check-trial-slow").check();
      await expect(client.page.getByTestId("selected-trial-slow")).toBeVisible({ timeout: 60_000 });

      // 取消勾选：定义被移除，进行中的测试取消
      await client.page.getByTestId("selected-remove-trial-slow").click();
      await expect(client.page.getByTestId("selected-trial-slow")).toHaveCount(0, { timeout: 60_000 });

      // 等上游把迟到的结果送回来：它没有启用这个模型，也没有写进部门默认
      await client.page.waitForTimeout(SLOW_DELAY_MS + 4000);
      await expect(client.page.getByTestId("selected-trial-slow")).toHaveCount(0);
      await expect(client.page.getByTestId("selected-status-trial-slow")).toHaveCount(0);
      expect(await departmentChoice(client, "product")).toBe("未设置");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
      await upstream.close();
    }
  });
}
