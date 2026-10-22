// 项目页面端到端测试（工单 #80 的验收）：三个种子项目由 FakeAdapter 驱动的真实服务支撑（tests/e2e/backend.py）。
// 覆盖概览、部门工作间、资料、观测、设置各页面在 1440×900 与 1920×1080、浅色与深色下的渲染，
// 控制台错误为零，页面无横向溢出；数据全部来自查询或事件流（界面不刷新也能看到服务端写入的结果）。
//
// 本文件正在按页面逐节编写，节与节之间的公共函数在下面集中定义。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const SAMPLE = "示例项目";
const BLOCKED = "文本工具";
const LIVE = "实时项目";
// room 脚本预置的项目（client/tests/e2e/backend.py 的 seed_room）
const ROOM = "房间项目";

const SAMPLE_GOAL = "实现一个回声工具";
const SAMPLE_ITEM = "实现回声工具";
const ADOPTED_SUMMARY = "implemented echo CLI";
const DELIVERY_FILE = "src/echo.py";
const PRODUCT_PROMPT = "产品部门先写目标与验收标准，范围以外的要求先问用户。";
const SEEDED_MATERIAL = "回声工具要能在终端里逐行回显输入。";

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

// 用户主动停止的事项会改变服务端状态，这条用例用自己的一份后端，共用的那份不受影响
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

async function section(page: Page, heading: string) {
  return page.locator("section.card").filter({ has: page.getByRole("heading", { name: heading, exact: true }) }).first();
}

async function table(page: Page, caption: string) {
  return page.locator("table").filter({ has: page.locator("caption", { hasText: caption }) }).first();
}

// 配色变量写在 body 上（styles.css 的 body { background: var(--bg) }），因此取 body 的颜色
async function themeBackground(page: Page): Promise<string> {
  return page.evaluate(() => getComputedStyle(document.body).backgroundColor);
}

// 布局验收：文档与页面内每个可见容器都不出现横向溢出（滚动容器允许，溢出到窗口外不允许）
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

async function expectNoOverflow(page: Page, where: string): Promise<void> {
  expect.soft(await overflowReport(page), `${where}：不应出现横向溢出`).toEqual([]);
}

async function activeTabCount(page: Page): Promise<number> {
  return page.locator(".tabbar .tab").evaluateAll((tabs) => tabs.filter((tab) => tab.getAttribute("aria-current") === "page").length);
}

async function pathText(page: Page): Promise<string> {
  return (await page.locator(".topbar .path").innerText()).trim();
}

// 试用页面上不应出现的开发用语与英文内部提示（工单 #303 的验收）：接口名、工单编号、
// 内部词 run、英文停止原因与英文阶段名。`Yudao` 是产品名，先去掉再检查。
const FORBIDDEN = /(?<![A-Za-z])run(?![A-Za-z])|released|observe-detail|project\.(overview|flow|attempts|settings)|work_item\.(inputs|create|append_input|cancel|reorder)|material\.record|event\.detail|guidance\.send|department_settings\.save|run\.(actions|attempt)|[A-Z][A-Z_]{3,}|#\d+|设计说明|TODO/;

async function expectNoDeveloperText(page: Page, where: string): Promise<void> {
  const text = (await bodyText(page)).replaceAll("Yudao", "");
  const found = text.match(FORBIDDEN);
  expect.soft(found?.[0] ?? null, `${where}：页面文字不应出现开发用语与英文内部提示`).toBeNull();
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
async function settingsVersion(page: Page, id: string): Promise<number> {
  const data = await fetchQuery<{ version: number }>(page, "project.settings", { project_id: id });
  return data.version;
}

// ---------------------------------------------------------------------------
// 1440×900：每个页面一组用例；每条用例自己启动一次客户端（同一后端），
// 结束时核对控制台错误为零。改变服务端状态的用例排在后面（决定解答与实时事项放最后）。

test.describe("项目页面（1440×900）", () => {
  test("缺少部门默认时新事项被拒绝：提示是中文并带两个去处", async () => {
    // 工单 #319 第 6 项：质检的部门默认没有选模型时「作为新事项开始」被拒绝，
    // 页面给出中文说明与去模型管理页、在本项目设置页两个去处
    test.setTimeout(300_000);
    // 用 room 脚本：它只建一个项目并跑完它，没有停在等待回答决定请求的 run（那个 run 会占用执行槽位）
    const own = await startBackend({ room: true, catalogDriven: true, bindDepartments: ["product", "engineering"] });
    try {
      const client = await startClient(own, { width: 1440, height: 900 });
      const errors = watchErrors(client);
      const page = client.page;
      try {
        const id = own.roomProject;
        if (id === null) {
          throw new Error("后端没有报出房间项目的标识");
        }
        await gotoView(page, id, "overview");
        const block = await section(page, "当前事项");
        await expect(block).toContainText("项目没有进行中的事项");
        const stats = await (await section(page, "项目摘要")).getByText(/事项统计/).innerText();
        await block.getByLabel("新的要求").fill("再做一个回声工具");
        await block.getByRole("button", { name: "作为新事项开始" }).click();
        const error = block.locator("p.error");
        await expect(error).toContainText("质检部门还没有选择模型");
        // 提示是中文句子：没有内部字段名、部门内部标识与英文原因词
        await expect(error).not.toContainText("bindings.");
        await expect(error).not.toContainText("quality");
        await expect(error).not.toContainText("provider_unavailable");
        // 两个去处按钮：去模型管理页、在本项目的设置页
        const links = block.locator(".row-actions .link");
        await expect(links).toHaveText(["去模型管理页设置部门默认", "在本项目的设置页选择模型"]);
        // 第一个去处：去系统的模型管理页
        await links.nth(0).click();
        await expect(page.getByRole("heading", { name: "模型管理", exact: true })).toBeVisible();
        // 回到概览重新提交一次，第二个去处去本项目的设置页
        await gotoView(page, id, "overview");
        const again = await section(page, "当前事项");
        await again.getByLabel("新的要求").fill("再做一个回声工具");
        await again.getByRole("button", { name: "作为新事项开始" }).click();
        await again.locator(".row-actions .link").nth(1).click();
        await expect(page.getByRole("heading", { name: "基本信息", exact: true })).toBeVisible();
        expect(await pathText(page)).toBe(`${ROOM} / ${PATH_LABEL.settings}`);
        // 被拒绝的事项没有创建：概览的事项统计与点击前逐字相同
        await gotoView(page, id, "overview");
        await expect((await section(page, "项目摘要")).getByText(/事项统计/)).toHaveText(stats);
        expect(errors).toEqual([]);
      } finally {
        await client.close();
      }
    } finally {
      await own.stop();
    }
  });

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
      await expect(flow).toContainText("需求交接");
      await expect(flow).toContainText("版本交付");
      await expect(flow).toContainText("产品处理中 → 工程处理中");
      await expect(flow).toContainText("工程处理中 → 交付核验中");
      await expect(flow).toContainText("已完成");
      // 时间列是按钮：点开原始事件的详情弹窗（event.detail）
      const row = flow.locator("tbody tr").filter({ hasText: "需求交接" }).first();
      await row.locator("button.link").click();
      const modal = page.locator(".modal-backdrop");
      await expect(modal.locator(".modal-head h2")).toContainText("事件 evt_");
      const raw = modal.locator("pre.raw");
      await expect(raw).toContainText('"event"');
      await expect(raw).toContainText('"type"');
      await modal.getByRole("button", { name: "关闭" }).click();
      await expect(page.locator(".modal-backdrop")).toHaveCount(0);
      await expectNoDeveloperText(page, "概览");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("概览：没有进行中的事项时，记录原文写入事件流", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "overview");
      const current = await section(page, "当前事项");
      await expect(current).toContainText("项目没有进行中的事项");
      const text = `界面记录的项目材料 ${Date.now()}`;
      await current.getByLabel("记录原文（保存为本项目的材料）").fill(text);
      await current.getByRole("button", { name: "记录原文" }).click();
      await expect(current.locator('p.hint[role="status"]')).toHaveText("已提交，等待写入结果");
      console.log("STEP created");
      // work_item.materials 的 changed_by 含 MATERIAL_RECORDED：换到资料页直接读取，不需要刷新
      await gotoView(page, id, "materials");
      // 项目材料是资料页的一个小节（原型 mt-notes 的 ul 列表，不是带 caption 的表）；
      const materials = await section(page, "项目材料");
      await expect(materials).toContainText(text);
      await expect(materials).toContainText(SEEDED_MATERIAL);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
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

  // 工单 #672：勾上「显示归档的项目」以后，已归档的项目出现在侧栏里，能从它的菜单里恢复。
  // 这条用例改变服务端状态（归档与恢复项目），用自己的一份后端，共用的那份不受影响。
  test("侧栏：显示归档的项目以后能取回归档的项目", async () => {
    test.setTimeout(300_000);
    const own = await startBackend();
    try {
      const client = await startClient(own, { width: 1440, height: 900 });
      const errors = watchErrors(client);
      const page = client.page;
      try {
        const entry = page.locator("li.project-entry").filter({ hasText: SAMPLE }).first();
        await entry.getByRole("button", { name: `${SAMPLE} 的项目操作` }).click();
        await page.getByRole("button", { name: "归档项目" }).click();
        await waitUntil(
          async () => (await page.locator("li.project-entry").filter({ hasText: SAMPLE }).count()) === 0,
          page, "归档以后项目从列表里消失");

        // 勾上「显示归档的项目」：它重新出现，并带「已归档」标记
        await page.getByLabel("显示归档的项目").check();
        const archived = page.locator("li.project-entry").filter({ hasText: SAMPLE }).first();
        await expect(archived).toBeVisible();
        await expect(archived).toContainText("已归档");

        // 取消勾选以后已归档的项目重新消失
        await page.getByLabel("显示归档的项目").uncheck();
        await waitUntil(
          async () => (await page.locator("li.project-entry").filter({ hasText: SAMPLE }).count()) === 0,
          page, "取消勾选以后已归档的项目重新消失");

        // 再勾上，从它的菜单里恢复：项目回到列表里
        await page.getByLabel("显示归档的项目").check();
        const again = page.locator("li.project-entry").filter({ hasText: SAMPLE }).first();
        await expect(again).toBeVisible();
        await again.getByRole("button", { name: `${SAMPLE} 的项目操作` }).click();
        await page.getByRole("button", { name: "恢复项目" }).click();
        await waitUntil(
          async () => (await page.locator("li.project-entry").filter({ hasText: SAMPLE }).count()) === 1,
          page, "恢复以后项目回到列表里");
        expect(errors).toEqual([]);
      } finally {
        await client.close();
      }
    } finally {
      await own.stop();
    }
  });

  test("部门工作间：标题区、检查区页签、部门消息与部门设置弹窗", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "dept/product");
      expect(await pathText(page)).toBe(`${SAMPLE} / ${PATH_LABEL["dept/product"]}`);
      const title = await section(page, "产品部门");
      await expect(title.locator(".section-head .note")).toHaveText("把用户的要求整理成有效需求");
      await expect(title).toContainText("部门状态");
      await expect(title).toContainText("这次运行不在本部门 · 已完成");
      await expect(title).toContainText("最近一次请求实际使用的模型");
      await expect(title).toContainText("fake-script");
      await expect(title).toContainText("协议");
      await expect(title).toContainText("fake");
      await expect(title).toContainText("当前生效的模型及来源");
      await expect(title).toContainText("（来源 部门默认）");
      await expect(title).toContainText("工位：产品 Agent");
      await expect(title).toContainText("所选事项 wi_");
      // 部门设置弹窗：标题为「本项目 · 某部门设置」，模型、推理档位与部门 Prompt 三项（第 9.2 节）
      await title.getByRole("button", { name: "部门设置" }).click();
      const dialog = page.locator(".modal-backdrop");
      await expect(dialog.locator(".modal-head h2")).toHaveText("本项目 · 产品设置");
      await expect(dialog).toContainText("基准版本：第 1 版");
      await expect(dialog.getByLabel("模型")).toContainText("跟随部门默认（当前：fake-script）");
      await expect(dialog.getByLabel("推理档位")).toContainText("跟随");
      await expect(dialog.getByLabel("部门 Prompt")).toHaveValue(PRODUCT_PROMPT);
      await dialog.getByRole("button", { name: "关闭" }).click();
      await expect(page.locator(".modal-backdrop")).toHaveCount(0);
      // 部门房间：画布画出内容（工单 #177）
      const room = await section(page, "部门房间");
      await expect(room.locator(".room-canvas canvas")).toHaveCount(1);
      const roomWidth = await room.locator(".room-canvas canvas").evaluate((el) => (el as HTMLCanvasElement).width);
      expect(roomWidth % 480).toBe(0);
      const inspect = page.locator('section.card:has([role="tablist"])').first();
      const tabs = inspect.locator('[role="tab"]');
      await expect(tabs).toHaveCount(3);
      await expect(tabs.nth(0)).toHaveAttribute("aria-selected", "true");
      await expect(inspect.locator("table").first()).toContainText("submit_product_spec");
      await tabs.nth(1).click();
      await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
      await expect(inspect).toContainText("上下文清单");
      await tabs.nth(2).click();
      await expect(inspect.locator(".kv").first()).toContainText("第 1 版（来源 本项目写入）");
      await expect(inspect.locator("pre.raw")).toContainText(PRODUCT_PROMPT);
      const messages = await section(page, "部门消息");
      await expect(messages.locator("ul.message-list li").first()).toBeVisible();
      const guidance = await section(page, "部门指导");
      console.log("STEP dept");
      await expect(guidance).toContainText("这个部门还没有指导记录");
      await expect(guidance.getByLabel("向产品下达指导")).toBeVisible();
      await expectNoDeveloperText(page, "部门工作间");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("工程与质检部门：没有配置部门 Prompt 时用内置默认 Prompt", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "dept/engineering");
      expect(await pathText(page)).toBe(`${SAMPLE} / ${PATH_LABEL["dept/engineering"]}`);
      await expect(await section(page, "工程部门")).toContainText("按有效需求实现并封存交付");
      const engineering = page.locator('section.card:has([role="tablist"])').first();
      await engineering.locator('[role="tab"]').nth(2).click();
      await expect(engineering.locator(".kv").first()).toContainText("第 0 版（来源 跟随部门默认）");
      await gotoView(page, id, "dept/quality");
      expect(await pathText(page)).toBe(`${SAMPLE} / ${PATH_LABEL["dept/quality"]}`);
      await expect(await section(page, "质检部门")).toContainText("按验收条件核验并给出放行或返工");
      const quality = page.locator('section.card:has([role="tablist"])').first();
      await quality.locator('[role="tab"]').nth(2).click();
      await expect(quality.locator(".kv").first()).toContainText("第 0 版（来源 跟随部门默认）");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
  test("三个部门的页签切换：标题区的色条与强调色随部门变化，房间在深色舞台中", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "overview");
      await expect(page.locator(".tabbar .tab").first()).toBeVisible();

      // 产品部门
      await page.locator(".tabbar .tab").filter({ hasText: "产品" }).click();
      await expect(page.locator(".y10-ws")).toHaveAttribute("data-dept", "product");
      await expect(page.locator(".y10-ws-head-block")).toBeVisible();
      await expect(page.locator(".y10-ws-stage")).toBeVisible();
      const productAccent = await page.locator(".y10-ws").evaluate((el) => getComputedStyle(el).getPropertyValue("--ws-accent").trim());
      expect(productAccent).not.toBe("");

      // 工程部门
      await page.locator(".tabbar .tab").filter({ hasText: "工程" }).click();
      await expect(page.locator(".y10-ws")).toHaveAttribute("data-dept", "engineering");
      await expect(page.locator(".y10-ws-head-block")).toBeVisible();
      await expect(page.locator(".y10-ws-stage")).toBeVisible();
      const engAccent = await page.locator(".y10-ws").evaluate((el) => getComputedStyle(el).getPropertyValue("--ws-accent").trim());
      expect(engAccent).not.toBe(productAccent);

      // 质检部门
      await page.locator(".tabbar .tab").filter({ hasText: "质检" }).click();
      await expect(page.locator(".y10-ws")).toHaveAttribute("data-dept", "quality");
      await expect(page.locator(".y10-ws-head-block")).toBeVisible();
      await expect(page.locator(".y10-ws-stage")).toBeVisible();
      const qualityAccent = await page.locator(".y10-ws").evaluate((el) => getComputedStyle(el).getPropertyValue("--ws-accent").trim());
      expect(qualityAccent).not.toBe(engAccent);
      expect(qualityAccent).not.toBe(productAccent);

      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
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
      await expect(index.locator(".section-head .note")).toContainText("本页的事项 wi_");
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
      // 第一轮三部门各一次模型请求（#470 删工程计划以后没有 plan_turn）：共三条
      await expect(all.locator("tbody tr")).toHaveCount(3);
      await expect(all.locator("tbody tr").first()).toContainText("fake-script");
      await expect(all.locator("tbody tr").first()).toContainText("未上报");
      // 关键词筛选：命中三条（请求的模型都是 fake-script）
      const keyword = record.locator("label.field").filter({ hasText: "关键词" }).locator("input");
      await keyword.fill("fake");
      await record.getByRole("button", { name: "按条件筛选" }).click();
      await expect(page.locator("section.card table").first().locator("tbody tr")).toHaveCount(3);
      // 没有命中的关键词：写明这个范围没有请求记录
      await keyword.fill("不存在的关键词zzz");
      await record.getByRole("button", { name: "按条件筛选" }).click();
      await expect(record).toContainText("这个范围没有请求记录");
      await keyword.fill("");
      await record.getByRole("button", { name: "按条件筛选" }).click();
      await expect(page.locator("section.card table").first().locator("tbody tr")).toHaveCount(3);
      // Provider 配置筛选（第 7.4 节）：命中 0 条时写明没有请求记录，改回空条件以后恢复
      const providerFilter = record.locator("label.field").filter({ hasText: "Provider 配置" }).locator("input");
      await providerFilter.fill("no-such-provider");
      await record.getByRole("button", { name: "按条件筛选" }).click();
      await expect(record).toContainText("这个范围没有请求记录");
      await providerFilter.fill("");
      await record.getByRole("button", { name: "按条件筛选" }).click();
      await expect(page.locator("section.card table").first().locator("tbody tr")).toHaveCount(3);
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
      // 详情页的返回：回到观测页，页签回到请求记录
      await detail.getByRole("button", { name: "返回请求记录" }).click();
      await expect.poll(async () => pathText(page)).toBe(`${SAMPLE} / ${PATH_LABEL.observe}`);
      expect(await activeTabCount(page)).toBe(1);
      await record.getByRole("tab", { name: "用量统计" }).click();
      const usage = record.locator(".y10-usage");
      await expect(usage.locator("h3")).toHaveText("用量统计");
      await expect(usage.locator(".y10-usage-note")).toContainText("用量只读显示，不是事项的预算");
      await expect(usage).toContainText("请求数");
      await expect(usage).toContainText("3（上报 0）");
      await expect(await table(page, "按部门")).toContainText("product");
      await expect(await table(page, "按模型")).toContainText("fake · fake-script");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("设置页：基本信息、部门设置与源目录", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "settings");
      expect(await pathText(page)).toBe(`${SAMPLE} / ${PATH_LABEL.settings}`);
      const basics = await section(page, "基本信息");
      await expect(basics.locator(".section-head .note")).toContainText("当前项目版本 ");
      await expect(basics).toContainText("当前名称");
      await expect(basics).toContainText(SAMPLE);
      await expect(basics).toContainText(SAMPLE_GOAL);
      await expect(basics).toContainText("置顶");
      await expect(basics).toContainText("否");
      await expect(basics).toContainText("进行中");
      await expect(basics.getByRole("button", { name: "修改名称与长期目标" })).toBeVisible();
      await expect(basics.getByRole("button", { name: "置顶" })).toBeVisible();
      await expect(basics.getByRole("button", { name: "归档项目" })).toBeVisible();
      const departments = await section(page, "部门设置");
      await expect(departments).toContainText("产品（product）");
      await expect(departments).toContainText("1 版；来源 本项目写入");
      await expect(departments.locator("pre.department-setting-text").first()).toContainText(PRODUCT_PROMPT);
      await expect(departments).toContainText("工程（engineering）");
      await expect(departments).toContainText("0 版；来源 跟随部门默认");
      await expect(departments).toContainText("质检（quality）");
      // 修改部门设置：模型、推理档位与部门 Prompt 三项（第 9.2 节）
      await departments.getByRole("button", { name: "修改部门设置" }).first().click();
      await expect(departments.getByLabel("部门 Prompt")).toHaveValue(PRODUCT_PROMPT);
      await expect(departments.getByLabel("模型")).toContainText("跟随部门默认（当前：fake-script）");
      await departments.getByRole("button", { name: "取消" }).first().click();
      // 登记命令一节随 ADR-0038 删除：设置页上不再出现登记命令的列表与表单
      await expect(page.getByText("登记命令")).toHaveCount(0);
      const sources = await section(page, "源目录");
      await expect(sources).toContainText("没有登记源目录");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("设置页：改完部门设置并保存以后部门设置那一节自己更新（工单 #674）", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "settings");
      const departments = await section(page, "部门设置");
      const product = departments.locator(".y10-set-dept").filter({ hasText: "产品（product）" });
      await expect(product).toContainText("1 版；来源 本项目写入");
      // 改产品部门的 Prompt 并保存
      const text = "产品部门先写目标与验收标准，再问范围以外的要求。";
      await product.getByRole("button", { name: "修改部门设置" }).click();
      await product.getByLabel("部门 Prompt").fill(text);
      await product.getByRole("button", { name: "保存部门设置" }).click();
      // 那一节自己更新：事件到达以后按能力清单重新查询，不刷新页面
      await waitUntil(async () => (await product.innerText()).includes("2 版；来源 本项目写入"),
        page, "部门设置的版本与来源更新");
      await expect(product.locator("pre.department-setting-text")).toContainText(text);
      // 还原 Prompt，后面的用例按原文核对
      await product.getByRole("button", { name: "修改部门设置" }).click();
      await product.getByLabel("部门 Prompt").fill(PRODUCT_PROMPT);
      await product.getByRole("button", { name: "保存部门设置" }).click();
      await waitUntil(async () => (await product.innerText()).includes("3 版；来源 本项目写入"),
        page, "还原以后版本继续");
      await expect(product.locator("pre.department-setting-text")).toContainText(PRODUCT_PROMPT);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("设置页：基准版本过期时提示重新读取", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "settings");
      const version = await settingsVersion(page, id);
      const basics = await section(page, "基本信息");
      await basics.getByRole("button", { name: "修改名称与长期目标" }).click();
      await basics.getByLabel("名称").fill(`回声工具改名核对 ${Date.now()}`);
      // 界面之外记录一条项目材料：项目流的版本 +1，但 project.settings 不因为这件事重新查询
      await expectAccepted(page, "material.record", { project_id: id, text: "过期基准版本核对用的材料" });
      await basics.getByRole("button", { name: "保存名称" }).click();
      const error = basics.locator('p.error[role="status"]');
      await expect(error).toContainText("项目已经被修改，请重新读取以后提交");
      await expect(error).toContainText(`（服务端当前版本 ${version + 1}），请重新读取以后提交`);
      // 重新读取以后提交：草稿仍在，服务端版本已经跟上
      await page.reload({ waitUntil: "domcontentloaded" });
      const after = await section(page, "基本信息");
      await after.getByRole("button", { name: "修改名称与长期目标" }).click();
      await after.getByRole("button", { name: "保存名称" }).click();
      await expect(after.locator('p.hint[role="status"]')).toHaveText("已提交，等待写入结果");
      await expect(after).toContainText("回声工具改名核对");
      // 恢复项目名，后面的用例按名称取标识
      const restored = await settingsVersion(page, id);
      await expectAccepted(page, "project.rename", { project_id: id, name: SAMPLE, base_version: restored });
      await waitUntil(
        async () => (await fetchQuery<{ projects: { name: string }[] }>(page, "projects.list")).projects.some((row) => row.name === SAMPLE),
        page,
        "项目名恢复为示例项目",
      );
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("草稿：切换页面、刷新以后仍在，切换项目以后不串", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    const draft = `未提交的名称草稿 ${Date.now()}`;
    try {
      const id = await projectId(page, SAMPLE);
      const blockedId = await projectId(page, BLOCKED);
      console.log("STEP blockedId");
      const key = `yudao-draft/settings/${id}/name`;
      await gotoView(page, id, "settings");
      await (await section(page, "基本信息")).getByRole("button", { name: "修改名称与长期目标" }).click();
      await (await section(page, "基本信息")).getByLabel("名称").fill(draft);
      expect(await page.evaluate((name) => window.sessionStorage.getItem(name), key)).toBe(draft);
      await gotoView(page, id, "overview");
      await gotoView(page, id, "settings");
      await (await section(page, "基本信息")).getByRole("button", { name: "修改名称与长期目标" }).click();
      await expect((await section(page, "基本信息")).getByLabel("名称")).toHaveValue(draft);
      await page.reload({ waitUntil: "domcontentloaded" });
      await (await section(page, "基本信息")).getByRole("button", { name: "修改名称与长期目标" }).click();
      await expect((await section(page, "基本信息")).getByLabel("名称")).toHaveValue(draft);
      // 另一个项目的同一处草稿：按项目分开存放，互不影响
      await gotoView(page, blockedId, "settings");
      await (await section(page, "基本信息")).getByRole("button", { name: "修改名称与长期目标" }).click();
      await expect((await section(page, "基本信息")).getByLabel("名称")).toHaveValue(BLOCKED);
      await page.evaluate((name) => window.sessionStorage.removeItem(name), key);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("外壳：状态项、项目菜单、事项选择与侧栏跳转", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await expect(page.locator(".connection")).toHaveText("已连接");
      const waiting = (await openDecisions(page)).length;
      await expect(page.locator(".topbar .status-item").filter({ hasText: "待你决定：" })).toHaveText(`待你决定：${waiting}`);
      await expect(page.locator(".drawer-toggle")).toBeHidden();
      // 侧栏点项目条目 -> 概览
      await page.locator(".sidebar .project-entry").filter({ hasText: SAMPLE }).locator("button.nav-item").first().click();
      await expect.poll(async () => page.evaluate(() => window.location.hash)).toBe(`#/p/${id}/overview`);
      // 项目操作菜单：重命名、置顶、归档项目
      await page.locator(".sidebar .project-entry").filter({ hasText: SAMPLE }).getByRole("button", { name: "项目操作" }).click();
      const menu = page.locator(".sidebar .project-menu").first();
      await expect(menu.getByRole("button", { name: "重命名" })).toBeVisible();
      await expect(menu.getByRole("button", { name: "置顶" })).toBeVisible();
      await expect(menu.getByRole("button", { name: "归档项目" })).toBeVisible();
      await menu.getByRole("button", { name: "重命名" }).click();
      await expect(menu.locator(".rename-form").getByLabel("新的项目名称")).toHaveValue(SAMPLE);
      await expect(menu.locator(".rename-form").getByRole("button", { name: "保存名称" })).toBeVisible();
      await page.locator(".sidebar .project-entry").filter({ hasText: SAMPLE }).getByRole("button", { name: "项目操作" }).click();
      // 顶栏事项选择框：选中示例项目的事项，哈希带 ?w=，页签仍高亮
      const picker = page.locator("label.field.picker select");
      await picker.selectOption({ label: `${SAMPLE_ITEM}（已采纳）` });
      await expect.poll(async () => page.evaluate(() => window.location.hash)).toContain("?w=");
      expect(await activeTabCount(page)).toBe(1);
      const selected = await fetchQuery<{ work_items: { work_item_id: string }[] }>(page, "project.overview", { project_id: id });
      await page.evaluate((hash) => { window.location.hash = hash; }, `${navHash(id, "dept/product")}?w=${selected.work_items[0].work_item_id}`);
      await expect(await section(page, "产品部门")).toContainText("（顶栏选中）");
      // 状态项点击 -> 首页（没有 #/decisions 这个页面）
      await page.locator(".topbar .status-item").filter({ hasText: "待你决定：" }).click();
      await expect.poll(async () => page.evaluate(() => window.location.hash)).toBe("#/home");
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  test("深色配色：背景随系统偏好改变，页面内容照常渲染", async () => {
    const client = await openProjectClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "settings");
      await page.emulateMedia({ colorScheme: "light" });
      expect(await themeBackground(page)).toBe("rgb(247, 248, 247)");
      await page.emulateMedia({ colorScheme: "dark" });
      await expect.poll(async () => themeBackground(page)).toBe("rgb(23, 25, 24)");
      await expect(await section(page, "基本信息")).toContainText(SAMPLE);
      await page.emulateMedia({ colorScheme: "light" });
      await expect.poll(async () => themeBackground(page)).toBe("rgb(247, 248, 247)");
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
      await expect(await section(page, "产品部门")).toContainText("工程处理中");
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
  test("宽屏：每个页面无横向溢出、深色下同样成立", async () => {
    test.setTimeout(240_000);
    const client = await openProjectClient({ width: 1920, height: 1080 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const id = await projectId(page, SAMPLE);
      await gotoView(page, id, "overview");
      // 宽屏不显示抽屉按钮，左侧栏常驻
      await expect(page.locator(".drawer-toggle")).toBeHidden();
      await expect(page.locator("aside.sidebar")).toBeVisible();
      const markers: Record<View, string> = {
        overview: "项目摘要",
        "dept/product": "产品部门",
        "dept/engineering": "工程部门",
        "dept/quality": "质检部门",
        materials: "intend 原文",
        observe: "请求记录",
        settings: "基本信息",
      };
      for (const view of VIEWS) {
        await gotoView(page, id, view);
        expect(await pathText(page)).toBe(`${SAMPLE} / ${PATH_LABEL[view]}`);
        await expect(page.getByText(markers[view], { exact: false }).first()).toBeVisible();
        await expectNoOverflow(page, `${view} 页面`);
      }
      // 弹窗与详情页也各查一次
      await gotoView(page, id, "dept/product");
      await (await section(page, "产品部门")).getByRole("button", { name: "部门设置" }).click();
      await expect(page.locator(".modal-backdrop")).toBeVisible();
      await expectNoOverflow(page, "部门设置弹窗");
      await page.locator(".modal-backdrop").getByRole("button", { name: "关闭" }).click();
      await gotoView(page, id, "observe");
      await page.locator("section.card table").first().locator("tbody tr").first().getByRole("button", { name: "详情" }).click();
      await expect.poll(async () => pathText(page)).toBe(`${SAMPLE} / 请求详情`);
      await expectNoOverflow(page, "请求详情页面");
      // 深色配色下再查一遍
      await page.emulateMedia({ colorScheme: "dark" });
      await expect.poll(async () => themeBackground(page)).toBe("rgb(23, 25, 24)");
      for (const view of VIEWS) {
        await gotoView(page, id, view);
        await expectNoOverflow(page, `${view} 页面（深色）`);
      }
      await page.emulateMedia({ colorScheme: "light" });
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
});
