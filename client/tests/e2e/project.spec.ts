// 项目页面端到端测试（工单 #80 的验收）：三个种子项目由 FakeAdapter 驱动的真实服务支撑（tests/e2e/backend.py）。
// 覆盖概览、部门工作间、资料、观测、设置各页面在 1440×900 与 1920×1080、浅色与深色下的渲染，
// 控制台错误为零，页面无横向溢出；数据全部来自查询或事件流（界面不刷新也能看到服务端写入的结果）。
//
// 本文件正在按页面逐节编写，节与节之间的公共函数在下面集中定义。

import { expect,test,type Page } from "@playwright/test";
import { startBackend,startClient,type Backend,type ClientApp } from "./fixtures";

const SAMPLE = "示例项目";
const BLOCKED = "文本工具";
const LIVE = "实时项目";
// room 脚本预置的项目（client/tests/e2e/backend.py 的 seed_room）

const SAMPLE_GOAL = "实现一个回声工具";
const SAMPLE_ITEM = "实现回声工具";
const ADOPTED_SUMMARY = "implemented echo CLI";
const DELIVERY_FILE = "src/echo.py";
const SEEDED_MATERIAL = "回声工具要能在终端里逐行回显输入。";
// 进行中的询问（工单 #477 的验收第 2 条）：与 backend.py 的 PENDING_ASK_ITEM、PENDING_ASK_QUESTION 一致，
// 后端脚本按事项原文认出这个项目，工程问产品以后产品的回答分支流式返回一分钟
const PENDING_PROJECT = "进行中的询问";
const PENDING_ITEM = "实现等待回答的事项";
const PENDING_QUESTION = "未知参数怎么处理？";

const VIEWS = ["overview", "dept/product", "dept/engineering", "dept/quality", "materials", "observe", "settings"] as const;
type View = (typeof VIEWS)[number];

// 顶栏路径把项目名与页名拼在一起（app.tsx 的 pathLabel）：页名与页签一致
const PATH_LABEL: Record<View, string> = {
  overview: "概览",
  "dept/product": "产品",
  "dept/engineering": "工程",
  "dept/quality": "质检",
  materials: "资料",
  observe: "观测",
  settings: "设置",
};

let backend: Backend;

// 后端启动要等 git 子进程（#214：并发负载下 60 至 75 秒），这个会合点单独放宽，
// 与各条测试自己的时限无关（同 shell.spec.ts 的处理）。
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

// 每个尺寸只启动一次客户端：页面顺序访问，浅色与深色在同一会话里用 emulateMedia 切换。
// 决定解答与实时事项这两类改变服务端状态的用例只在 1440 尺寸里跑一遍，1920 尺寸只看渲染。
async function openProjectClient(size: { width: number; height: number }): Promise<ClientApp> {
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  await waitUntil(
    async () => (await client.page.locator(".project-entry").count()) >= 3,
    client.page,
    "侧栏出现三个种子项目",
  );
  return client;
}

function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    // 服务端按设计用 409 拒绝命令（基准版本过期等，第 3.1 节），界面已经把原因显示给用户；
    // 浏览器对非 2xx 响应自己记一条控制台消息，那不是应用的错误
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

// 项目标识经 projects.list 读取：项目名可能被前面的用例改过，恢复步骤也在服务端留下版本，
// 因此每次按当前名称取标识，不写死。
async function projectId(page: Page, name: string): Promise<string> {
  return fetchQuery<{ projects: { name: string; project_id: string }[] }>(page, "projects.list")
    .then((data) => {
      const row = data.projects.find((project) => project.name === name);
      if (row === undefined) {
        throw new Error(`projects.list 里没有项目 ${name}（现有：${data.projects.map((p) => p.name).join("、")}）`);
      }
      return row.project_id;
    });
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

// 直发命令：页面同一来源调用接口，服务端真实登记事件（不是测试替身）。
// 请求体的字段就是命令的公共字段加命令自身的字段（command_id 由客户端生成，基准版本由调用处给出）
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

type CommandResult = { status: number; body: { reason?: string; message?: string } };

// 命令被接受时 HTTP 是 200，响应体是应用层的受理回执（没有 status 字段）；被拒绝时 HTTP 是 409，响应体是拒绝原因
async function expectAccepted(page: Page, name: string, request: Record<string, unknown>): Promise<void> {
  const result = await sendCommand<CommandResult>(page, name, request);
  if (result.status !== 200) {
    throw new Error(`命令 ${name} 被服务端拒绝：HTTP ${result.status} ${result.body.reason ?? ""} ${result.body.message ?? ""}`);
  }
}

function navHash(id: string, view: View): string {
  return `#/p/${id}/${view}`;
}

async function gotoView(page: Page, id: string, view: View): Promise<void> {
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, navHash(id, view));
  await expect(page.locator(".tabbar .tab").first()).toBeVisible();
}

async function bodyText(page: Page): Promise<string> {
  return page.evaluate(() => document.body.innerText);
}

// 等待某个条件成立：界面按事件流自动重查询，这里轮询的是页面文本，不刷新页面
async function waitUntil(check: () => Promise<boolean>, page: Page, description: string, timeoutMs = 40_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) {
      return;
    }
    if (Date.now() > deadline) {
      const text = await bodyText(page).catch(() => "");
      throw new Error(`等待超时：${description}（当前页面文本：${text.slice(0, 400)}）`);
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}

// 用户主动停止的事项会改变服务端状态，这条用例用自己的一份后端，共用的那份不受影响。
// options 给这条用例自己的后端选项（工单 #477 的验收第 2 条用 pending 脚本起一份不预置项目的后端）
async function withOwnBackend<T>(run: () => Promise<T>, options: Parameters<typeof startBackend>[0] = {}): Promise<T> {
  const previous = backend;
  const own = await startBackend(options);
  backend = own;
  try {
    return await run();
  } finally {
    backend = previous;
    await own.stop();
  }
}

async function section(page: Page, heading: string) {
  return page.locator("section.card").filter({ has: page.getByRole("heading", { name: heading, exact: true }) }).first();
}

async function table(page: Page, caption: string) {
  return page.locator("table").filter({ has: page.locator("caption", { hasText: caption }) }).first();
}

// 配色变量写在 body 上（styles.css 的 body { background: var(--bg) }），因此取 body 的颜色

// 布局验收：文档与页面内每个可见容器都不出现横向溢出（滚动容器允许，溢出到窗口外不允许）


async function activeTabCount(page: Page): Promise<number> {
  return page.locator(".tabbar .tab").evaluateAll((tabs) => tabs.filter((tab) => tab.getAttribute("aria-current") === "page").length);
}

async function pathText(page: Page): Promise<string> {
  return (await page.locator(".topbar .path").innerText()).trim();
}

async function openDecisions(page: Page): Promise<{ decision_id: string; version: number; project_id: string }[]> {
  const data = await fetchQuery<{ decisions: { decision_id: string; version: number; project_id: string; status: string }[] }>(
    page,
    "decisions.list",
    { status: "open" }
  );
  return data.decisions.map((row) => ({ decision_id: row.decision_id, version: row.version, project_id: row.project_id }));
}

// 服务端当前项目版本（project.settings 的 version）：基准版本过期用例要在界面之外改动它

// ---------------------------------------------------------------------------
// 1440×900：每个页面一组用例；每条用例自己启动一次客户端（同一后端），
// 结束时核对控制台错误为零。改变服务端状态的用例排在后面（决定解答与实时事项放最后）。

test.describe("项目页面（1440×900）", () => {
  
  test("概览：摘要、循环画面、看板与流转记录都来自查询", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "overview");
      expect(await pathText(page)).toBe(`${SAMPLE} / ${PATH_LABEL.overview}`);
      const summary = await section(page, "项目摘要");
      await expect(summary).toContainText("名称");
      await expect(summary).toContainText(SAMPLE);
      await expect(summary).toContainText(SAMPLE_GOAL);
      await expect(summary).toContainText("当前成果");
      await expect(summary).toContainText(ADOPTED_SUMMARY);
      await expect(summary).toContainText("共 1");
      // 循环画面由工单 #82 填入：像素楼层画在画布上，画布之外还有文字列表
      const floor = await section(page, "循环画面");
      await expect(floor.locator(".floor-screen canvas")).toHaveCount(1);
      const board = await section(page, "事项看板");
      await expect(board.locator(".board-col")).toHaveCount(7);
      await expect(board.locator("h3").filter({ hasText: "已采纳" })).toContainText("（1）");
      await expect(board.locator(".board-card strong")).toHaveText(SAMPLE_ITEM);
      const flow = await section(page, "流转记录");
      // 工单 #556：阶段迁移事件没有了，流转记录里的「版本交付」由交付到达给出
      await expect(flow).toContainText("版本交付");
      await expect(flow).toContainText("工程 → 质检");
      await expect(flow).toContainText("已完成");
      // 时间列是按钮：点开原始事件的详情弹窗（event.detail）
      const row = flow.locator("tbody tr").filter({ hasText: "版本交付" }).first();
      await row.locator("button.link").click();
      const modal = page.locator(".modal-backdrop");
      await expect(modal.locator(".modal-head h2")).toContainText("事件 evt_");
      const raw = modal.locator("pre.raw");
      await expect(raw).toContainText('"event"');
      await expect(raw).toContainText('"type"');
      await modal.getByRole("button", { name: "关闭" }).click();
      await expect(page.locator(".modal-backdrop")).toHaveCount(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  // 工单 #904：概览写三个部门各自的状态、按成果写的进度与这个事项里的询问。
  // 用种子里的项目，不靠时序：「交付历史」那个事项走完了一轮、留下了询问与回答；
  // 「文本工具」那个事项停在模型不可用（工程等用户）。
  test("概览：三个部门各自的状态、按成果写的进度与询问", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      // 交付历史：选中那个事项，概览列出它的两次询问，状态与回答都来自 run.asks
      const history = await projectId(page, "交付历史");
      const historyItems = await fetchQuery<{ work_items: { work_item_id: string }[] }>(
        page, "project.overview", { project_id: history });
      const historyItem = historyItems.work_items[0];
      if (historyItem === undefined) {
        throw new Error("交付历史项目里没有事项");
      }
      await page.evaluate((hash) => { window.location.hash = hash; },
        `${navHash(history, "overview")}?w=${historyItem.work_item_id}`);
      const asks = await section(page, "询问");
      await expect(asks).toBeVisible();
      const rows = asks.locator("li");
      await expect(rows).toHaveCount(2);
      // 工程问产品（询问链、已回答、回答）
      await expect(rows.nth(0)).toContainText("已回答");
      await expect(rows.nth(0)).toContainText("工程 → 产品");
      await expect(rows.nth(0)).toContainText("How should unknown flags be handled?");
      await expect(rows.nth(0)).toContainText("回答：Print the argument as defined in the current requirement.");
      // 质检问工程
      await expect(rows.nth(1)).toContainText("已回答");
      await expect(rows.nth(1)).toContainText("质检 → 工程");
      await expect(rows.nth(1)).toContainText("回答：Follow the acceptance line recorded in the requirement.");
      // 这个事项已经结束：没有部门状态，所在部门一行照旧写所在部门
      const historyCurrent = await section(page, "当前事项");
      await expect(historyCurrent.locator(".department-line")).toContainText("所在部门：");
      // 进度按成果写：当前的 PRD、最新的交付与它依据的 PRD、对最新交付的结论
      await expect(historyCurrent).toContainText("PRD r1 · 交付 r2（依据 PRD r1）· 结论：放行");

      // 文本工具：停在模型不可用的事项，对应的部门显示「等用户」，其他部门等待工作
      const blocked = await projectId(page, BLOCKED);
      await gotoView(page, blocked, "overview");
      const blockedCurrent = await section(page, "当前事项");
      const blockedStates = blockedCurrent.locator(".department-line");
      await expect(blockedStates).toContainText("工程 等用户");
      await expect(blockedStates).toContainText("产品 等待工作");
      // 还没有交付：进度行写「PRD r1 · 还没有交付」
      await expect(blockedCurrent).toContainText("PRD r1 · 还没有交付");
      // 这个事项还没有询问：询问一节不出现
      await expect(page.locator("section.card").filter({ has: page.getByRole("heading", { name: "询问", exact: true }) })).toHaveCount(0);
      // 概览与看板上没有阶段名称、工程计划与协作请求
      const overviewText = await bodyText(page);
      expect(overviewText).not.toContain("阶段");
      expect(overviewText).not.toContain("协作请求");
      expect(overviewText).not.toContain("计划");
      const board = await section(page, "事项看板");
      const boardText = await board.innerText();
      expect(boardText).not.toContain("阶段");
      expect(boardText).not.toContain("协作请求");
      expect(boardText).not.toContain("计划");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  // 工单 #477 的验收第 2 条：工程询问产品、询问还没有回答时，项目页与部门页显示这次询问与等待原因；
  // 「回答以后显示回答」由上面那条用例用种子里的「交付历史」核对。这里用一份自己的后端让这次询问停在
  // 进行中：pending 脚本不预置项目（执行槽位空着），产品的回答分支流式返回一分钟、片段之间停 0.5 秒
  // （client/tests/e2e/backend.py 的 pending_ask_script）。两个页面的文字都来自 run.asks 与部门状态。
  test("概览与工程部门页：询问进行中时显示这次询问与等待原因", async () => {
    test.setTimeout(300_000);
    await withOwnBackend(async () => {
      const client = await startClient(backend, { width: 1440, height: 900 });
      const errors = watchErrors(client);
      const page = client.page;
      try {
        await expect(page.locator(".brand .y10-brand-name")).toContainText("Yudao");
        // 这个后端不预置项目：自己建一个项目与一个事项，事项随即开始，工程问产品
        await expectAccepted(page, "project.create", { name: PENDING_PROJECT, goal: "确认询问进行中时两个页面显示什么" });
        const id = await projectId(page, PENDING_PROJECT);
        await expectAccepted(page, "work_item.create", { project_id: id, text: PENDING_ITEM });
        // 概览：部门一行写状态与等待原因，询问一节列出这次询问（进行中、没有回答）
        await gotoView(page, id, "overview");
        const current = await section(page, "当前事项");
        await waitUntil(async () => (await current.innerText()).includes("在等待产品的回答"), page,
          "概览显示工程在等待产品的回答");
        const states = current.locator(".department-line");
        await expect(states).toContainText("工程 询问中（在等待产品的回答）");
        await expect(states).toContainText("产品 一轮工作中（回答工程的询问）");
        const asks = await section(page, "询问");
        const rows = asks.locator("li");
        await expect(rows).toHaveCount(1);
        await expect(rows.first()).toContainText("进行中");
        await expect(rows.first()).toContainText("工程 → 产品");
        await expect(rows.first()).toContainText(PENDING_QUESTION);
        await expect(rows.first()).not.toContainText("回答：");
        // 部门页：标题区的状态词与原因、检查区的部门状态，本部门的询问一节列出这次询问
        await gotoView(page, id, "dept/engineering");
        const titleRow = page.locator("#ws-head-block .y10-ws-title-row");
        await expect(titleRow.locator(".y10-status")).toHaveText("询问中");
        await expect(titleRow.locator("small.y10-muted")).toHaveText("在等待产品的回答");
        const check = page.locator("#ws-head-block .y10-ws-model");
        await expect(check).toContainText("部门状态");
        await expect(check).toContainText("询问中（在等待产品的回答）");
        const ownAsks = await section(page, "询问");
        await expect(ownAsks.locator("li").first()).toContainText("进行中");
        await expect(ownAsks.locator("li").first()).toContainText("工程 → 产品");
        await expect(ownAsks.locator("li").first()).toContainText(PENDING_QUESTION);
        // 两个页面都不写单一阶段、工程计划与协作请求
        const text = await bodyText(page);
        expect(text).not.toContain("阶段");
        expect(text).not.toContain("协作请求");
        expect(text).not.toContain("计划");
        expect(errors).toEqual([]);
      } finally {
        await client.close();
      }
    }, { script: "pending" });
  });


  // 工单 #652：「记录原文」与「新的要求」各有各的状态与草稿。
  // 这条用例新建事项（改变服务端状态），用自己的一份后端，共用的那份不受影响。
  test("概览：记录原文与新的要求各有各的状态，提交记录原文不影响新的要求", async () => {
    test.setTimeout(300_000);
    await withOwnBackend(async () => {
      const client = await startClient(backend, { width: 1440, height: 900 });
      const errors = watchErrors(client);
      const page = client.page;
      try {
        const id = await projectId(page, SAMPLE);
        // 执行槽位只有一个：「文本工具」项目里那个等待回答的事项占着它，
        // 槽位空出来以后才能新建事项（应用层「已有事项正在执行」一条）
        const blocked = await projectId(page, BLOCKED);
        const decisions = await openDecisions(page);
        if (decisions.length > 0) {
          await expectAccepted(page, "decision.answer", {
            decision_id: decisions[0].decision_id, option: "stop", base_version: decisions[0].version,
          });
          await waitUntil(async () => {
            const data = await fetchQuery<{ work_items: { status: string }[] }>(page, "project.overview", { project_id: blocked });
            return data.work_items.every((item) => item.status !== "in_progress");
          }, page, "执行槽位空出来");
        }
        await gotoView(page, id, "overview");
        const current = await section(page, "当前事项");
        await expect(current).toContainText("项目没有进行中的事项");

        const material = "概览里记录的材料文字";
        const requirement = "概览里写下的新要求";
        const recordBox = current.getByLabel("记录原文（保存为本项目的材料）");
        const requirementBox = current.getByLabel("新的要求");
        await recordBox.fill(material);
        await requirementBox.fill(requirement);
        // 两个框各自装各自的内容：一个框里的文字不出现在另一个框里
        expect(await recordBox.inputValue()).toBe(material);
        expect(await requirementBox.inputValue()).toBe(requirement);

        // 提交「记录原文」：只清它自己那个框，「新的要求」里的文字留着
        await current.getByRole("button", { name: "记录原文" }).click();
        await waitUntil(async () => (await recordBox.inputValue()) === "", page, "记录原文提交以后那个框清空");
        expect(await requirementBox.inputValue()).toBe(requirement);

        // 提交「作为新事项开始」：新事项真的建起来了
        // 事项统计在摘要的「事项统计」那一行里，标题本身不变，要看整行的文字
        const statsLine = (await section(page, "项目摘要")).locator(".line").filter({ hasText: "事项统计" }).first();
        const stats = await statsLine.innerText();
        await current.getByRole("button", { name: "作为新事项开始" }).click();
        await waitUntil(
          async () => (await statsLine.innerText()) !== stats,
          page,
          "新事项建起来以后事项统计改变",
        );
        expect(errors).toEqual([]);
      } finally {
        await client.close();
      }
    });
  });

  
  
    

  test("资料页：intend 原文、PRD、交付文件与项目材料", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "materials");
      expect(await pathText(page)).toBe(`${SAMPLE} / ${PATH_LABEL.materials}`);
      const index = await section(page, "按事项查看");
      await expect(index.locator(".section-head .note")).toContainText(`本页的事项 ${SAMPLE_ITEM}`);
      await expect(index.locator(".section-head .note")).toContainText("（未选中事项，取当前事项）");
      const intend = await section(page, "intend 原文");
      await expect(intend).toContainText("第 1 版");
      await expect(intend).toContainText("text");
      await expect(intend).toContainText("0–18");
      await expect(await section(page, "PRD")).toContainText("第 1 版");
      const delivery = page.locator(".delivery-block").first();
      await expect(delivery.locator(".y10-mt-doc-head strong")).toContainText("交付 第 1 版");
      await expect(delivery).toContainText(ADOPTED_SUMMARY);
      await expect(delivery.locator(".file-list")).toContainText(DELIVERY_FILE);
      await expect(await section(page, "项目材料")).toContainText(SEEDED_MATERIAL);
      // 文件内容由 delivery.file 取回
      await delivery.locator("button.link", { hasText: "查看内容" }).click();
      const viewer = page.locator("div.card").filter({ has: page.getByRole("heading", { name: `交付文件 ${DELIVERY_FILE}` }) });
      await expect(viewer.locator("pre.raw")).toContainText("import sys");
      // 文本交付文件也有下载入口（工单 #748）：下载到的内容与展开框里看到的逐字相同
      const link = viewer.locator("a", { hasText: "下载文件" });
      await expect(link).toHaveAttribute("download", DELIVERY_FILE);
      const shown = await viewer.locator("pre.raw").innerText();
      const href = await link.getAttribute("href");
      expect(href).not.toBeNull();
      const encoded = (href as string).split(",")[1];
      expect(decodeURIComponent(encoded)).toBe(shown);
      await viewer.getByRole("button", { name: "收起" }).click();
      await expect(page.getByRole("heading", { name: `交付文件 ${DELIVERY_FILE}` })).toHaveCount(0);
      // 没有事项的项目：资料页显示空态，没有一直转的「正在读取数据」（工单 #295 第 3 项）
      const liveId = await projectId(page, LIVE);
      await gotoView(page, liveId, "materials");
      await expect(await section(page, "按事项查看")).toContainText("项目还没有事项，没有资料可看");
      await expect(await section(page, "按事项查看")).not.toContainText("正在读取数据");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("观测页：关键词筛选、请求详情与用量统计", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "observe");
      expect(await pathText(page)).toBe(`${SAMPLE} / ${PATH_LABEL.observe}`);
      const record = await section(page, "请求记录与用量");
      await expect(record.locator(".section-head .note")).toContainText("范围：整个项目");
      const all = page.locator("section.card table").first();
      // 第一轮：产品、工程各一次模型请求，质检两次（PRD 被接纳以后先做一轮预测性探索，
      // 交付到达以后核验，循环结构第 3.1 节）：共四条
      await expect(all.locator("tbody tr")).toHaveCount(4);
      await expect(all.locator("tbody tr").first()).toContainText("fake-script");
      // 用量列（工单 #744）：列名是「用量」，与请求详情同一口径；预置项目的模型回答没有上报用量，写「未上报」
      await expect(all.locator("thead th").nth(7)).toHaveText("用量");
      await expect(all.locator("tbody tr").first().locator("td").nth(7)).toHaveText("未上报");
      // 关键词筛选：命中四条（请求的模型都是 fake-script）
      const keyword = record.locator("label.field").filter({ hasText: "关键词" }).locator("input");
      await keyword.fill("fake");
      await record.getByRole("button", { name: "按条件筛选" }).click();
      await expect(page.locator("section.card table").first().locator("tbody tr")).toHaveCount(4);
      // 没有命中的关键词：写明这个范围没有请求记录
      await keyword.fill("不存在的关键词zzz");
      await record.getByRole("button", { name: "按条件筛选" }).click();
      await expect(record).toContainText("这个范围没有请求记录");
      await keyword.fill("");
      await record.getByRole("button", { name: "按条件筛选" }).click();
      await expect(page.locator("section.card table").first().locator("tbody tr")).toHaveCount(4);
      // Provider 配置筛选（第 7.4 节）：命中 0 条时写明没有请求记录，改回空条件以后恢复
      const providerFilter = record.locator("label.field").filter({ hasText: "Provider 配置" }).locator("input");
      await providerFilter.fill("no-such-provider");
      await record.getByRole("button", { name: "按条件筛选" }).click();
      await expect(record).toContainText("这个范围没有请求记录");
      await providerFilter.fill("");
      await record.getByRole("button", { name: "按条件筛选" }).click();
      await expect(page.locator("section.card table").first().locator("tbody tr")).toHaveCount(4);
      // 请求详情：点第一行的「详情」，顶栏路径换成请求详情
      await page.locator("section.card table").first().locator("tbody tr").first().getByRole("button", { name: "详情" }).click();
      await expect.poll(async () => pathText(page)).toBe(`${SAMPLE} / 请求详情`);
      expect(await activeTabCount(page)).toBe(0);
      const detail = await section(page, "请求详情");
      await expect(detail.locator(".section-head .note")).toContainText("请求标识 act_");
      await expect(detail).toContainText("模型");
      await expect(detail).toContainText("请求 fake-script，实际 fake-script");
      await expect(detail).toContainText("调用目标");
      // 调用目标与选择来源（第 7.4 节）：连接、协议、地址与来源层都写在这里
      await expect(detail).toContainText("选择来源");
      await expect(detail).toContainText("部门默认");
      await expect(detail).toContainText("是否可重试");
      // 失败类型与结束原因（工单 #305）：详情里给出这两行；这一次请求成功，因此没有失败类型、结束原因未上报
      await expect(detail).toContainText("失败类型");
      await expect(detail.locator(".line", { hasText: "失败类型" }).locator(".value")).toHaveText("没有");
      await expect(detail).toContainText("结束原因");
      await expect(detail.locator(".line", { hasText: "结束原因" }).locator(".value")).toHaveText("未上报");
      // 用量（工单 #744）：请求详情与请求记录表说的是同一件事，同样没有上报用量时都写「未上报」
      await expect(detail.locator('.line:has(.term:text-is("用量")) .value')).toHaveText("未上报");
      // 工件引用（工单 #745）：这一行按项说，缺哪一项写哪一项没有，不是一句「未上报」盖住四项。
      // 预置项目的模型回答来自 FakeAdapter，没有留下工件，因此四项都是「未上报」；
      // 四项都在时的显示由客户端单元测试核对（那里给出的是工件引用的对象形状）。
      const refs = detail.locator('.line:has(.term:text-is("引用")) .value');
      await expect(refs).toHaveText("请求 未上报，响应 未上报，原始流 未上报，用量 未上报");
      // 页面上不出现英文内部标识与开发者措辞
      await expect(refs).not.toContainText("sdk_");
      await expect(refs).not.toContainText("sha256");
      // 详情页的返回：回到观测页，页签回到请求记录
      await detail.getByRole("button", { name: "返回请求记录" }).click();
      await expect.poll(async () => pathText(page)).toBe(`${SAMPLE} / ${PATH_LABEL.observe}`);
      expect(await activeTabCount(page)).toBe(1);
      await record.getByRole("tab", { name: "用量统计" }).click();
      const usage = record.locator(".y10-usage");
      await expect(usage.locator("h3")).toHaveText("用量统计");
      await expect(usage.locator(".y10-usage-note")).toContainText("用量只读显示，不是事项的预算");
      await expect(usage).toContainText("请求数");
      // 「上报用量的请求」（工单 #744）：这个范围里上报了用量的请求数，一个都没有时写「未上报」
      await expect(usage.locator('.line:has(.term:text-is("请求数")) .value')).toHaveText("4");
      await expect(usage.locator('.line:has(.term:text-is("上报用量的请求")) .value')).toHaveText("未上报");
      // 分组表同样给出这个数，页面上「上报了多少个」与请求记录里的显示对得上
      await expect(await table(page, "按部门")).toContainText("上报用量的请求");
      await expect(await table(page, "按模型")).toContainText("上报用量的请求");
      await expect(await table(page, "按部门")).toContainText("product");
      await expect(await table(page, "按模型")).toContainText("fake · fake-script");
      // 另一个项目里那一次请求上报了用量（预置脚本给了它 100 输入与 20 输出）：
      // 请求记录表与请求详情写出同一句话，用量统计说这个范围里有 1 个请求上报了用量（工单 #744）
      const used = await projectId(page, "文本工具");
      await gotoView(page, used, "observe");
      const usedRecord = await section(page, "请求记录与用量");
      await usedRecord.getByRole("tab", { name: "请求记录" }).click();
      const usedTable = usedRecord.locator("table").first();
      await expect(usedTable.locator("tbody tr").first().locator("td").nth(7)).toHaveText("总 120 token，输入 100，输出 20");
      await usedTable.locator("tbody tr").first().getByRole("button", { name: "详情" }).click();
      await expect.poll(async () => pathText(page)).toBe("文本工具 / 请求详情");
      const usedDetail = await section(page, "请求详情");
      await expect(usedDetail.locator('.line:has(.term:text-is("用量")) .value')).toHaveText("总 120 token，输入 100，输出 20");
      await usedDetail.getByRole("button", { name: "返回请求记录" }).click();
      await expect.poll(async () => pathText(page)).toBe("文本工具 / 观测");
      await usedRecord.getByRole("tab", { name: "用量统计" }).click();
      await expect(usedRecord.locator('.line:has(.term:text-is("上报用量的请求")) .value')).toHaveText("1 个");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  
  
  
  // 工单 #709：采纳以后页面上有写回的入口，写回的结果在页面上看得见
  test("设置页：成果写回一节能发起写回，概览页的当前成果里有一行写回状态", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "settings");
      const writeback = await section(page, "成果写回");
      await expect(writeback).toContainText("把采纳的成果写回登记的源目录");
      await expect(writeback.getByRole("button", { name: "写回成果" })).toBeVisible();
      await expect(writeback).toContainText("还没有写回记录");
      // 这个项目没有登记源目录：命令被拒绝，页面给出服务端的中文理由（不是 500 内部错误）
      await writeback.getByRole("button", { name: "写回成果" }).click();
      await expect(writeback.locator("p.error")).toContainText("没有可写回的东西");
      // 概览页的「当前成果」里有一行写回状态，没有写回时给出到设置页的入口
      await gotoView(page, id, "overview");
      const summary = await section(page, "项目摘要");
      await expect(summary).toContainText("写回");
      await expect(summary.getByRole("button", { name: "去项目设置页写回" })).toBeVisible();
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  
  
  
  
  
  test("界面上的命令写入事件流：部门指导", async () => {
    test.setTimeout(180_000);
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const liveId = await projectId(page, LIVE);
      const blockedId = await projectId(page, BLOCKED);
      // 没有事项的项目：概览写明没有进行中的事项，看板为空
      await gotoView(page, liveId, "overview");
      await expect(await section(page, "当前事项")).toContainText("项目没有进行中的事项");
      await expect(await section(page, "事项看板")).toContainText("项目还没有事项");
      await expect(await section(page, "项目摘要")).toContainText("尚未采纳");
      // 没有事项的项目打开部门页：显示空态，没有一直转的「正在读取数据」（工单 #295 第 3 项）
      await gotoView(page, liveId, "dept/product");
      await expect(page.locator(".page")).toContainText("项目还没有事项，部门工作间没有内容可显示");
      await expect(page.locator(".page")).not.toContainText("正在读取数据");
      // 文本工具：给产品部门发一条指导，指导列表由事件流更新
      await gotoView(page, blockedId, "dept/product");
      // 工单 #905：部门页写三个部门各自的状态，本部门那一段加粗；「这次运行不在本部门」的旧写法没有了
      const productHead = await section(page, "产品部门");
      await expect(productHead.locator(".department-line")).toContainText("三个部门");
      await expect(productHead.locator(".department-line")).toContainText("等待工作");
      await expect(page.locator(".page")).not.toContainText("这次运行不在本部门");
      await expect(page.locator(".page")).not.toContainText("正在工作 ·");
      const guidance = await section(page, "部门指导");
      const note = `界面发出的指导 ${Date.now()}`;
      await guidance.getByLabel("向产品下达指导").fill(note);
      await guidance.getByRole("button", { name: "发送指导" }).click();
      await expect(guidance.locator('p.hint[role="status"]')).toHaveText("已提交，等待写入结果");
      await expect(guidance).toContainText(note);
      await expect(guidance).toContainText("已接收");
      // 等待回答的决定请求仍在（这条用例不回答它，另外的项目因此没有开始新的运行）
      expect((await openDecisions(page)).length).toBeGreaterThan(0);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});

// ---------------------------------------------------------------------------
// 1920×1080：一次启动客户端，逐个页面核对没有横向溢出，控制台错误为零；
// 弹窗与详情页也一样；深色配色下再查一遍。

test.describe("项目页面（1920×1080）", () => {
  });
