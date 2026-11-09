// 系统通知与标签页标题的端到端测试（工单 #375）：
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），页面文件由该服务提供，模型回答由
// FakeAdapter 给出，不使用 mock。
// 覆盖：决定请求发出通知（正文写明项目与事项，两个页面各一条、标记相同）、点击通知打开对应的决定卡片、
// 等待模型服务发出通知、标签页的标题随待决定的数量变化、没有通知权限时页面照常工作且控制台无错误。
//
// 记录通知的方法：在页面装载前包装 window.Notification（fixtures 的 initScript）。包装调用真实的
// 构造函数，页面的通知逻辑原样运行；包装只把每次调用的标题、正文与标记记在 window.notifications 上。
// 无头浏览器里没有系统的通知中心，点击由页面自己挂在通知上的 onclick 处理器执行。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const SIZE = { width: 1440, height: 900 };

// 记录 window.Notification 的调用：包装仍然调用真实的构造函数，页面拿到的类型与原来一致，
// 页面的通知逻辑原样运行；包装只把每次调用的标题、正文与标记记在 window.notifications 上
declare global {
  interface Window {
    notifications: { title: string; body: string; tag: string; notification: Notification }[];
  }
}

function recordNotifications(): void {
  const Real = window.Notification;
  const recorded: Window["notifications"] = [];
  window.notifications = recorded;
  const Recorded = function (this: Notification, title: string, options?: NotificationOptions) {
    const notification = new Real(title, options);
    recorded.push({ title, body: options?.body ?? "", tag: options?.tag ?? "", notification });
    return notification;
  } as unknown as typeof Notification;
  Object.defineProperty(Recorded, "permission", { get: () => Real.permission });
  Recorded.requestPermission = Real.requestPermission.bind(Real);
  window.Notification = Recorded;
}

type Recorded = { title: string; body: string; tag: string };

function record(client: ClientApp): () => Promise<Recorded[]> {
  return () => client.page.evaluate(() => window.notifications.map(({ title, body, tag }) => ({ title, body, tag })));
}

function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    // 浏览器为失败的资源请求自己记一条控制台消息：服务端按设计拒绝命令时是 409，
    // 服务没有图标文件时是 404。页面把拒绝的原因显示给用户，这些不是应用的错误
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

type DecisionRow = {
  decision_id: string;
  version: number;
  project_id: string | null;
  work_item_id: string | null;
  request: { options: { id: string; label: string }[] };
};

async function fetchQuery<T>(page: Page, address: string, name: string, params: Record<string, string> = {}): Promise<T> {
  const search = new URLSearchParams(params);
  const envelope = await page.evaluate(async ({ base, query, qs }) => {
    const response = await fetch(`${base}/api/queries/${query}?${qs}`);
    return (await response.json()) as { data?: unknown; reason?: string; message?: string };
  }, { base: address, query: name, qs: search.toString() });
  if (envelope.data === undefined) {
    throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data as T;
}

async function openDecisions(page: Page, address: string): Promise<DecisionRow[]> {
  const data = await fetchQuery<{ decisions: DecisionRow[] }>(page, address, "decisions.list", { status: "open" });
  return data.decisions;
}

async function answer(page: Page, address: string, decisionId: string, version: number, option: string): Promise<number> {
  return page.evaluate(async ({ base, id, ver, picked }) => {
    const response = await fetch(`${base}/api/commands/decision.answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command_id: crypto.randomUUID(), decision_id: id, option: picked, base_version: ver }),
    });
    return response.status;
  }, { base: address, id: decisionId, ver: version, picked: option });
}

async function waitUntil(check: () => Promise<boolean>, description: string, timeoutMs = 60_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) {
      return;
    }
    if (Date.now() > deadline) {
      throw new Error(`等待超时：${description}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
}

test("决定请求、等待模型服务、标签页标题与没有通知权限时的页面（工单 #375）", async () => {
  test.setTimeout(300_000);
  let own: Backend | null = null;
  try {
    own = await startBackend();
    const backend = own;
    // 两个页面：几件事同时打开时，同一件事只显示一条通知（以决定请求的身份作为标记）
    const first = await startClient(backend, SIZE, { permissions: ["notifications"], initScript: recordNotifications });
    const second = await startClient(backend, SIZE, { permissions: ["notifications"], initScript: recordNotifications });
    const errors = [...watchErrors(first), ...watchErrors(second)];
    try {
      await expect(first.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
      await first.page.evaluate(() => {
        window.location.hash = "#/home";
      });
      const seeded = await openDecisions(first.page, backend.address);
      expect(seeded.length).toBeGreaterThan(0);

      // 页面打开以后到达的决定请求：预置的那条在页面装载时已经发出，通知由补齐的历史事件发出。
      // 回答它以后这个 run 继续，再次遇到模型不可用，出现一条新的决定请求
      const target = seeded[0];
      expect(await answer(first.page, backend.address, target.decision_id, target.version, "continue")).toBe(200);
      await waitUntil(async () => {
        const rows = await openDecisions(first.page, backend.address);
        return rows.length > 0 && rows[0].decision_id !== target.decision_id;
      }, "回答以后出现新的决定请求");
      const fresh = (await openDecisions(first.page, backend.address))[0];

      // 两个页面都收到同一条决定请求，各自发出一条通知，标记相同
      await waitUntil(async () => (await record(first)()).some((item) => item.tag === fresh.decision_id),
        "第一个页面发出这条决定请求的通知");
      await waitUntil(async () => (await record(second)()).some((item) => item.tag === fresh.decision_id),
        "第二个页面发出这条决定请求的通知");
      const shown = (await record(first)()).filter((item) => item.tag === fresh.decision_id);
      expect(shown).toHaveLength(1);
      // 标记相同：浏览器按标记合并，两个页面打开时同一件事只显示一条
      expect(shown[0].tag).toBe(fresh.decision_id);
      expect(shown[0].title).toBe("等待模型服务，需要你决定");
      // 正文写明是哪个项目、哪件事
      expect(shown[0].body).toContain("文本工具");
      expect(shown[0].body).toContain("实现逐行处理");
      // 同一件事不会因为重新同步而再发一条
      const repeated = (await record(second)()).filter((item) => item.tag === fresh.decision_id);
      expect(repeated).toHaveLength(1);

      // 点击通知：页面回到首页并打开对应的决定卡片
      await first.page.evaluate((id: string) => {
        const target = window.notifications.filter((item) => item.tag === id).pop();
        if (target === undefined) {
          throw new Error(`没有记录到标记为 ${id} 的通知`);
        }
        target.notification.onclick?.(new Event("click"));
      }, fresh.decision_id);
      const card = first.page.locator(`#decision-${fresh.decision_id}`);
      await expect(card).toBeVisible();
      await expect(card).toHaveClass(/is-targeted/);
      expect(await first.page.evaluate(() => window.location.hash)).toBe("#/home");

      // 标签页的标题：有待决定的事时显示数量
      await expect.poll(async () => first.page.title()).toMatch(/^\(\d+\) Yudao$/);
      expect(errors).toEqual([]);
    } finally {
      await first.close();
      await second.close();
    }
  } finally {
    await own?.stop();
  }
});



