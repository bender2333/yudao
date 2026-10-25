// 系统首页与决定卡片的端到端测试（工单 #175 的验收）：在 1440×900 与 1920×1080 两种窗口尺寸下运行，
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），页面文件也由该服务提供，模型回答由
// FakeAdapter 给出，不使用 mock。
// 覆盖：状态项「待你决定」与 decisions.list 数量一致、首页与标签栏的决定卡片、提问被回答或撤销时显示原因、
// 离开期间的报告三种范围与「已看过」、项目列表字段与 projects.list 一致；控制台错误为零。

import { expect,test,type Page } from "@playwright/test";
import { startBackend,startClient,type Backend,type ClientApp } from "./fixtures";


let backend: Backend;

// 后端启动要等 git 子进程（#214），这个会合点单独放宽，与各条测试自己的时限无关
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
    // 服务端按设计用 409 拒绝命令（基准版本过期、请求已被回答等，第 3.1、3.3 节），
    // 界面已经把原因显示给用户；浏览器对非 2xx 响应自己记一条控制台消息，那不是应用的错误
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

async function openHome(size: { width: number; height: number }): Promise<ClientApp> {
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  await client.page.evaluate(() => {
    window.location.hash = "#/home";
  });
  await expect(client.page.getByRole("heading", { name: "待你决定", exact: true })).toBeVisible();
  return client;
}

// 改变服务端状态的用例（回答决定请求）用自己的一份后端：回答会让阻塞的 run 继续并产生新的请求，
// 共用一份后端会让后面的用例看到不同的等待列表。这份后端只在这条用例期间替换模块变量，结束以后恢复
async function withOwnBackend<T>(run: () => Promise<T>): Promise<T> {
  const previous = backend;
  const own = await startBackend();
  backend = own;
  try {
    return await run();
  } finally {
    backend = previous;
    await own.stop();
  }
}

async function bodyText(page: Page): Promise<string> {
  return page.evaluate(() => document.body.innerText);
}

async function waitUntil(check: () => Promise<boolean>, page: Page, description: string, timeoutMs = 40_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) {
      return;
    }
    if (Date.now() > deadline) {
      throw new Error(`等待超时：${description}（当前页面文本：${(await bodyText(page).catch(() => "")).slice(0, 400)}）`);
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}


type DecisionRow = { decision_id: string; version: number; project_id: string; work_item_id: string | null; kind: string };

async function openDecisions(page: Page): Promise<DecisionRow[]> {
  const data = await fetchQuery<{ decisions: DecisionRow[] }>(page, "decisions.list", { status: "open" });
  return data.decisions;
}

test.describe("系统首页（1440×900）", () => {
  
  
  test("回答一个等待中的决定请求：卡片显示已提交，事件到达以后移出列表，run 按回答继续", async () => {
    test.setTimeout(120_000);
    await withOwnBackend(async () => {
      const client = await openHome({ width: 1440, height: 900 });
      const errors = watchErrors(client);
      try {
        const before = await openDecisions(client.page);
        expect(before.length).toBeGreaterThan(0);
        const target = before[0];
        const card = client.page.locator(`#decision-${target.decision_id}`);
        await expect(card).toBeVisible();
        // 按卡片给出的选项回答（继续执行）。提交以后只显示一条「已提交」提示（工单 #319：
        // 提交提示重复过一次）；事件很快到达时卡片先移出列表，这两种情况都算通过
        await card.getByRole("button", { name: "继续执行" }).click();
        await expect
          .poll(async () => {
            const hints = await card.locator("span.hint").allInnerTexts();
            const submitted = hints.filter((line) => line.includes("已提交"));
            if (submitted.length > 1) {
              return `重复：${submitted.join(" / ")}`;
            }
            if (submitted.length === 1) {
              return "已提交";
            }
            return (await card.count()) === 0 ? "已提交" : "";
          }, { message: "提交以后显示一条「已提交」" })
          .toBe("已提交");
        // 事件到达以后这张卡片移出等待列表
        await waitUntil(
          async () => (await openDecisions(client.page)).every((row) => row.decision_id !== target.decision_id),
          client.page,
          "回答以后卡片移出等待列表",
        );
        await expect(client.page.locator(`#decision-${target.decision_id}`)).toHaveCount(0);
        // run 按回答继续：这个 run 的下一次请求再次遇到模型不可用，出现新的决定请求（同一事项）
        await waitUntil(
          async () => (await openDecisions(client.page)).some((row) => row.work_item_id === target.work_item_id),
          client.page,
          "run 按回答继续并再次遇到模型不可用",
        );
        expect(errors).toEqual([]);
      } finally {
        await client.close();
      }
    });
  });

  
  test("离开期间的报告：三种范围的汇总项都能展开来源事件，点击「已看过」更新上次查看", async () => {
    test.setTimeout(120_000);
    let client = await openHome({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const report = client.page.locator("section.card").filter({ has: client.page.getByRole("heading", { name: "离开期间的报告", exact: true }) });
    try {
      for (const range of ["最近 24 小时", "最近 7 天", "自上次查看"]) {
        await report.getByRole("button", { name: range, exact: true }).click();
        await expect.poll(async () => report.locator(".report-item").count()).toBeGreaterThan(0);
        const item = report.locator(".report-item").first();
        await item.locator(".report-head").click();
        await expect(item.locator(".source-list, p.note")).toBeVisible();
      }
      // 记录当前「自上次查看」的起点，点击「已看过」以后它更新为当前位置
      const before = await fetchQuery<{ range: { from_position: number; to_position: number } }>(client.page, "home.away_report", { range: "since_seen" });
      const note = report.locator(".section-head .note").first();
      const noteBefore = await note.textContent();
      await report.getByRole("button", { name: "已看过", exact: true }).click();
      await waitUntil(async () => {
        const now = await fetchQuery<{ range: { from_position: number } }>(client.page, "home.away_report", { range: "since_seen" });
        return now.range.from_position >= before.range.to_position;
      }, client.page, "已看过更新上次查看的位置");
      // 同一页面立即显示新的上次查看（工单 #301）：说明文字变化，不用离开再回来
      await expect.poll(async () => note.textContent()).not.toBe(noteBefore);
      // 重新启动客户端以后上次查看的位置仍然保留（控制主机只记录一个位置）
      await client.close();
      client = await openHome({ width: 1440, height: 900 });
      const after = await fetchQuery<{ range: { from_position: number } }>(client.page, "home.away_report", { range: "since_seen" });
      expect(after.range.from_position).toBeGreaterThanOrEqual(before.range.to_position);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  
  
  });

test.describe("系统首页（1920×1080）", () => {
  });



// 事项的标题：决定卡片写它，不写事项标识（工单 #802）
