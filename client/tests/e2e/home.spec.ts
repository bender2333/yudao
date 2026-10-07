// 系统首页与决定卡片的端到端测试（工单 #175 的验收）：在 1440×900 与 390×844 两种窗口尺寸下运行，
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），模型回答由 FakeAdapter 给出，不使用 mock。
// 覆盖：状态项「待你决定」与 decisions.list 数量一致、首页与标签栏的决定卡片、提问被回答或撤销时显示原因、
// 离开期间的报告三种范围与「已看过」、项目列表字段与 projects.list 一致；控制台错误为零。

import { expect, test, type Locator, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const BLOCKED = "文本工具";

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
  await expect(client.page.locator(".brand")).toHaveText("Yudao");
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

async function overflowReport(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const offenders: string[] = [];
    const root = document.documentElement;
    if (root.scrollWidth - root.clientWidth > 1) {
      offenders.push(`document +${root.scrollWidth - root.clientWidth}`);
    }
    for (const node of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const over = node.scrollWidth - node.clientWidth;
      if (over <= 1 || node.offsetParent === null) {
        continue;
      }
      const style = getComputedStyle(node);
      if (style.overflowX === "auto" || style.overflowX === "scroll") {
        continue;
      }
      const classes = typeof node.className === "string" && node.className.trim() !== "" ? `.${node.className.trim().split(/\s+/).join(".")}` : "";
      const region = node.closest("section");
      const heading = region?.querySelector("h2,h3")?.textContent?.slice(0, 16) ?? "";
      offenders.push(`${node.tagName.toLowerCase()}${classes} +${over} <${heading}>`);
    }
    return offenders;
  });
}

// 决定卡片上的文字不应出现开发用语与英文内部提示（工单 #303 的验收）：内部词 run、
// 英文停止原因、接口名与英文阶段名。`Yudao` 是产品名，先去掉再检查。
const FORBIDDEN = /(?<![A-Za-z])run(?![A-Za-z])|released|decisions\.list|decision\.answer|work_item\.[a-z_]+|run\.[a-z_]+|project\.[a-z_]+|[A-Z][A-Z_]{3,}|#\d+/;

async function expectNoDeveloperText(scope: Locator, where: string): Promise<void> {
  const text = (await scope.innerText()).replaceAll("Yudao", "");
  const found = text.match(FORBIDDEN);
  expect.soft(found?.[0] ?? null, `${where}：卡片文字不应出现开发用语与英文内部提示`).toBeNull();
}

type DecisionRow = { decision_id: string; version: number; project_id: string; work_item_id: string | null };

async function openDecisions(page: Page): Promise<DecisionRow[]> {
  const data = await fetchQuery<{ decisions: DecisionRow[] }>(page, "decisions.list", { status: "open" });
  return data.decisions;
}

test.describe("系统首页（1440×900）", () => {
  test("状态项「待你决定」的数量与 decisions.list 中等待回答的数量一致", async () => {
    const client = await openHome({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    try {
      const waiting = await openDecisions(client.page);
      expect(waiting.length).toBeGreaterThan(0);
      const stat = client.page.locator(".status-row .status-item").filter({ hasText: "待你决定" });
      await expect(stat).toHaveText(`待你决定${waiting.length}`);
      // 顶栏与托盘使用同一份数据
      await expect(client.page.locator(".topbar .status-item").filter({ hasText: "待你决定：" })).toHaveText(`待你决定：${waiting.length}`);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("首页「待你决定」列出等待回答的决定卡片，卡片头写明种类、项目与挡住的对象", async () => {
    const client = await openHome({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    try {
      const waiting = await openDecisions(client.page);
      const block = client.page.locator("section.card").filter({ has: client.page.getByRole("heading", { name: "待你决定", exact: true }) });
      await expect(block.locator(".decision-card")).toHaveCount(waiting.length);
      const first = block.locator(".decision-card").first();
      await expect(first.locator(".decision-title")).toContainText("模型引用无法使用");
      const resolvedName = await projectName(client.page, waiting[0].project_id ?? "");
      await expect.poll(async () => first.locator(".decision-meta").innerText()).toContain(resolvedName);
      await expect(first.locator(".decision-meta")).toContainText("已等待");
      await expect(first.locator(".decision-meta")).toContainText("挡住");
      // 材料按决定种类整理：待恢复显示部门与具体问题
      await expect(first.locator("details")).toContainText("部门");
      for (const card of await block.locator(".decision-card").all()) {
        await expectNoDeveloperText(card, "决定卡片");
      }
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

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

  test("回答一个已经回答过的决定请求时，卡片显示原因并刷新", async () => {
    test.setTimeout(120_000);
    await withOwnBackend(async () => {
      const client = await openHome({ width: 1440, height: 900 });
      const errors = watchErrors(client);
      try {
        const [decision] = await openDecisions(client.page);
        const card = client.page.locator(`#decision-${decision.decision_id}`);
        await expect(card).toBeVisible();
        // 在界面之外把这条请求回答掉，然后在同一次脚本里点击卡片中的选项：服务端以 decision_closed 拒绝，
        // 卡片显示原因。用同一次 evaluate 里的 DOM 点击避免事件流先一步把卡片移走（真实运行里，
        // 请求被另一个客户端或另一次回答关闭时就是这个过程）
        const shown = await client.page.evaluate(
          async ({ address, id, version }) => {
            await fetch(`${address}/api/commands/decision.answer`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ command_id: crypto.randomUUID(), decision_id: id, option: "continue", base_version: version }),
            });
            const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>(`#decision-${id} .decision-answer button`));
            if (buttons.length === 0) {
              return "没有找到回答按钮";
            }
            buttons[buttons.length - 1].click();
            const deadline = Date.now() + 5000;
            while (Date.now() < deadline) {
              const error = document.querySelector(`#decision-${id} p.error`);
              if (error) {
                return error.textContent ?? "";
              }
              const { promise, resolve } = Promise.withResolvers<void>();
              setTimeout(resolve, 20);
              await promise;
            }
            return "没有显示原因";
          },
          { address: backend.address, id: decision.decision_id, version: decision.version },
        );
        expect(shown).toContain("已经回答");
        // 卡片随后按事件刷新：这条请求移出等待列表
        await waitUntil(
          async () => (await openDecisions(client.page)).every((row) => row.decision_id !== decision.decision_id),
          client.page,
          "已回答的请求移出等待列表",
        );
        await expect(client.page.locator(`#decision-${decision.decision_id}`)).toHaveCount(0);
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

  test("首页两个区块的说明与报告项不出现开发用语", async () => {
    // 工单 #319 第 5 项：首页「项目」区块的说明与离开期间报告的说明原来写着接口名
    const client = await openHome({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    try {
      const projects = client.page.locator("section.card")
        .filter({ has: client.page.getByRole("heading", { name: "项目", exact: true }) });
      const report = client.page.locator("section.card")
        .filter({ has: client.page.getByRole("heading", { name: "离开期间的报告", exact: true }) });
      await expect(projects.locator(".note, header .note").first()).not.toContainText("数据来自");
      await expectNoDeveloperText(projects, "首页项目区块");
      await expectNoDeveloperText(report, "离开期间的报告");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("项目列表的每个字段与 projects.list 一致", async () => {
    const client = await openHome({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    try {
      const data = await fetchQuery<{
        projects: {
          project_id: string; name: string; goal: string; archived: boolean; current_adoption: string | null;
          in_progress_count: number; waiting_count: number; decisions_waiting: number;
        }[];
      }>(client.page, "projects.list");
      const rows = data.projects.filter((project) => !project.archived);
      const table = client.page.locator("section.card").filter({ has: client.page.getByRole("heading", { name: "项目", exact: true }) }).locator("table");
      await expect(table.locator("tbody tr")).toHaveCount(rows.length);
      for (const project of rows) {
        const row = table.locator("tbody tr").filter({ has: client.page.getByRole("button", { name: project.name, exact: true }) });
        await expect(row).toContainText(project.goal === "" ? "没有填写" : project.goal);
        await expect(row).toContainText(`${project.in_progress_count} · ${project.waiting_count}`);
        await expect(row).toContainText(project.current_adoption === null ? "尚未采纳" : project.current_adoption);
        await expect(row).toContainText(project.decisions_waiting > 0 ? String(project.decisions_waiting) : "无");
      }
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("项目标签栏的「待你决定」只列出本项目的决定请求，点击展开卡片", async () => {
    const client = await openHome({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    try {
      const blockedId = await projectId(client.page, BLOCKED);
      await client.page.evaluate((id: string) => {
        window.location.hash = `#/p/${id}/overview`;
      }, blockedId);
      await expect(client.page.locator(".tabbar .tab").first()).toBeVisible();
      const tabbarButton = client.page.locator(".topbar .status-item").filter({ hasText: "待你决定 · " });
      const projectWaiting = (await openDecisions(client.page)).filter((row) => row.project_id === blockedId);
      await expect(tabbarButton).toHaveText(`待你决定 · ${projectWaiting.length}`);
      // 展开：只含本项目的请求
      await tabbarButton.click();
      const dropdown = client.page.locator(".decisions-dropdown");
      await expect(dropdown.locator(".decision-card")).toHaveCount(projectWaiting.length);
      for (const decision of projectWaiting) {
        await expect(dropdown.locator(`#decision-${decision.decision_id}`)).toBeVisible();
      }
      const otherProject = (await openDecisions(client.page)).find((row) => row.project_id !== blockedId);
      if (otherProject) {
        await expect(dropdown.locator(`#decision-${otherProject.decision_id}`)).toHaveCount(0);
      }
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});

test.describe("系统首页（390×844）", () => {
  test("窄屏：首页各区块单列，不出现横向滚动；控制台错误为零", async () => {
    test.setTimeout(120_000);
    const client = await openHome({ width: 390, height: 844 });
    const errors = watchErrors(client);
    try {
      await expect(client.page.getByRole("heading", { name: "待你决定", exact: true })).toBeVisible();
      await expect(client.page.getByRole("heading", { name: "离开期间的报告", exact: true })).toBeVisible();
      await expect(client.page.getByRole("heading", { name: "项目", exact: true })).toBeVisible();
      expect(await overflowReport(client.page), "首页：窄屏不应出现横向溢出").toEqual([]);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});

async function projectId(page: Page, name: string): Promise<string> {
  return fetchQuery<{ projects: { name: string; project_id: string }[] }>(page, "projects.list").then((data) => {
    const row = data.projects.find((project) => project.name === name);
    if (row === undefined) {
      throw new Error(`projects.list 里没有项目 ${name}`);
    }
    return row.project_id;
  });
}

async function projectName(page: Page, projectIdValue: string): Promise<string> {
  return fetchQuery<{ projects: { name: string; project_id: string }[] }>(page, "projects.list").then((data) => {
    return data.projects.find((project) => project.project_id === projectIdValue)?.name ?? "";
  });
}
