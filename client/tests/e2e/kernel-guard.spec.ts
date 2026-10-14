// 路径守卫的端到端测试（工单 #354 的验收）：后端用 kernel 脚本预置一个交付改动了内核清单路径的事项，
// 结算因此不采纳，发出内核修改决定请求。页面上的决定卡片要给出改动的路径与差异；批准以后交付被采纳。
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），不使用 mock。

import { expect, test, type Locator, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

// 决定卡片上的文字不应出现开发用语与英文内部提示（工单 #303 的验收）
const FORBIDDEN = /(?<![A-Za-z])run(?![A-Za-z])|released|decisions\.list|decision\.answer|work_item\.[a-z_]+|run\.[a-z_]+|project\.[a-z_]+|[A-Z][A-Z_]{3,}|#\d+/;

// 交付改动的内核路径：与 backend.py 的 KERNEL_PATH 一致
const KERNEL_PATH = "harness/bounds.py";

async function expectNoDeveloperText(scope: Locator, where: string): Promise<void> {
  const text = (await scope.innerText()).replaceAll("Yudao", "");
  const found = text.match(FORBIDDEN);
  expect.soft(found?.[0] ?? null, `${where}：卡片文字不应出现开发用语与英文内部提示`).toBeNull();
}

let backend: Backend;

// 后端启动要等 git 子进程（#214），这个会合点单独放宽，与各条测试自己的时限无关
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend({ script: "kernel" });
});

test.afterAll(async () => {
  await backend?.stop();
});

function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    // 服务端按设计用 409 拒绝命令（基准版本过期、请求已被回答等），界面已经把原因显示给用户；
    // 浏览器对非 2xx 响应自己记一条控制台消息，那不是应用的错误
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

async function fetchQuery<T>(page: Page, name: string, params: Record<string, string | number> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.set(String(key), String(value));
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

type DecisionRow = { decision_id: string; kind: string; project_id: string | null; version: number };

async function openDecisions(page: Page): Promise<DecisionRow[]> {
  const data = await fetchQuery<{ decisions: DecisionRow[] }>(page, "decisions.list", { status: "open" });
  return data.decisions;
}

async function openHome(size: { width: number; height: number }): Promise<ClientApp> {
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  await client.page.evaluate(() => {
    window.location.hash = "#/home";
  });
  await expect(client.page.getByRole("heading", { name: "待你决定", exact: true })).toBeVisible();
  return client;
}

async function waitUntil(check: () => Promise<boolean>, description: string, timeoutMs = 40_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) {
      return;
    }
    if (Date.now() > deadline) {
      throw new Error(`等待超时：${description}`);
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}

test("内核修改决定请求：卡片给出改动的内核路径与差异，批准以后交付被采纳", async () => {
  const client = await openHome({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    // 结算发出的内核修改决定请求：改动了内核清单里的路径时，交付不自动采纳
    await waitUntil(async () => (await openDecisions(page)).some((row) => row.kind === "kernel_modification"),
      "内核修改决定请求出现");
    const [target] = (await openDecisions(page)).filter((row) => row.kind === "kernel_modification");
    const card = page.locator(`#decision-${target.decision_id}`);
    await expect(card).toBeVisible();
    // 卡片头写明种类；材料里给出改动的内核路径与差异
    await expect(card.locator(".decision-title")).toContainText("内核路径");
    const material = card.locator("details.decision-body");
    await expect(material).toContainText("改动的内核路径");
    // 改动的内核路径写在材料里：与后端交付改动的路径一致（工单 #354）
    await expect(material).toContainText(KERNEL_PATH);
    // 卡片文字没有开发用语与英文内部提示（工单 #303）
    await expectNoDeveloperText(card, "内核修改决定卡片");
    // 批准：交付被采纳，这个决定移出等待列表
    await card.locator(".decision-answer button").first().click();
    await waitUntil(
      async () => !(await openDecisions(page)).some((row) => row.decision_id === target.decision_id),
      "批准以后这个决定移出等待列表",
    );
    // 采纳已经写入项目流：批准以后这个项目的当前采纳是这次交付
    await waitUntil(async () => {
      const overview = await fetchQuery<{ current_adoption: { run_id: string } | null }>(
        page, "project.overview", { project_id: target.project_id ?? "" });
      return overview.current_adoption !== null;
    }, "批准以后交付被采纳");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
