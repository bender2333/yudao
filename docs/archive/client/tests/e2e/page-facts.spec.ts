// 页面事实的端到端测试（工单 #1416）：原来只在画布上看得到的「首页 / 项目页 / 部门页」三节事实，
// 现在在页面上有对应的文字与详情。这里只读页面文字与结构，不读画布、不用画面的测试入口。
//
// 覆盖：
//   1. 首页项目一览：此刻在做什么、事项在哪个部门、有没有事项在等执行槽位、待回答的决定数量；
//   2. 项目页：各部门在等什么、等了多久（含大厅几条决定在等）、中断与待恢复、已用时间与上限、
//      流转按方向的汇总、事实元素的来源（点开按位置读原始事件、跳到时间轴上同一位置）、回放时跟着位置；
//   3. 部门页：实时的模型输出、手边的摘要与笔记的数量、等模型服务、远程结果未知。
//
// 后端由 FakeAdapter 驱动（client/tests/e2e/backend.py --script pending）：这个模式不预置项目，用例自己
// 建项目与事项；事项的工程部门会向产品发出询问，产品的回答分支分成 120 段、每段之间停 0.5 秒流式返回，
// 页面因此有一段约一分钟的「询问进行中 + 模型正在输出」的时间可以核对。默认预置（--script default）在
// main 上已知坏掉（事项全部停止），这里不依赖它。

import { expect, test, type Locator, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { collectConsoleErrors, startBackend, startClient, type Backend } from "./fixtures";

// 等待回答的事项（backend.py 的 PENDING_ASK_ITEM）：工程的轮次会向产品询问 PENDING_ASK_QUESTION
const WAITING_ITEM = "实现等待回答的事项";

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend({ script: "pending" });
});

test.afterAll(async () => {
  await backend?.stop();
});

type AcceptedEnvelope = { ok?: boolean; reason?: string; message?: string; refs?: Record<string, string> };

/** 发一条命令（与页面走同一个接口），被拒时抛错并带上原因。 */
async function command(name: string, body: Record<string, unknown>): Promise<AcceptedEnvelope> {
  const response = await fetch(`${backend.address}/api/commands/${name}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ command_id: randomUUID(), ...body }),
  });
  const raw = await response.text();
  if (response.status >= 400) {
    throw new Error(`命令 ${name} 被拒绝（${response.status}）：${raw.slice(0, 400)}`);
  }
  const envelope = JSON.parse(raw) as AcceptedEnvelope;
  if (envelope.ok === false) {
    throw new Error(`命令 ${name} 被拒绝：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope;
}

type QueryEnvelope<T> = { data?: T; reason?: string; message?: string };

/** 读一条查询（页面的数据来源就是这一份）。 */
async function query<T>(name: string, params: Record<string, unknown> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.append(key, String(value));
  }
  const qs = search.toString();
  const response = await fetch(`${backend.address}/api/queries/${name}${qs ? `?${qs}` : ""}`);
  const envelope = (await response.json()) as QueryEnvelope<T>;
  if (envelope.data === undefined) {
    throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data;
}

/** 等一个条件成立（页面按事件流自己重新查询，不刷新页面）。 */
async function waitUntil(check: () => Promise<boolean>, description: string, timeoutMs = 120_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) return;
    if (Date.now() > deadline) throw new Error(`等待超时：${description}`);
    await page_.waitForTimeout(200);
  }
}

/** waitUntil 用的页面：每次用例开始时换成自己的页（用例串行运行，workers 为 1）。 */
let page_: Page;

/** 页面上的一个区块（按标题取第一块）。 */
function section(page: Page, heading: string): Locator {
  return page.locator("section.card").filter({ has: page.getByRole("heading", { name: heading, exact: true }) }).first();
}

/** 页面上某一行的取值（KeyValue 的标签与取值一格）。 */
function line(card: Locator, term: string): Locator {
  return card.locator("div.line").filter({ hasText: term }).first().locator(".value");
}

type DepartmentStateView = { state: string; note?: string | null };
type LoopItem = {
  work_item_id: string;
  sign: string;
  status: string;
  department: string | null;
  run_id: string;
  elapsed_sec: number | null;
  time_limit_sec: number;
  departments?: Record<string, DepartmentStateView> | null;
  refs?: Record<string, { position: number; source: string }>;
  organization?: { roles: { id: string; label: string }[] } | null;
};
type LoopResult = { work_items: LoopItem[] };
type WorkspaceRoom = {
  summaries: number;
  pinned_notes: number;
  waiting_provider: boolean;
  remote_unknown: boolean;
};
type WorkspaceResult = { department: string; work_item_id: string | null; room: WorkspaceRoom };
type EventAtPosition = {
  position: number;
  status: "available" | "missing";
  reason?: string | null;
  type?: string | null;
  label?: string | null;
  actor_label?: string | null;
  department_label?: string | null;
  at?: string | null;
};

/** 部门状态词（页面上的说法）：三部门的循环结构 docs/design/department-loop.md「职能的状态」。 */
const DEPARTMENT_STATES: Record<string, string> = {
  waiting_user: "等用户", working: "一轮工作中", asking: "询问中", verifying: "核验中", waiting: "等待工作",
};

function departmentStateText(state: DepartmentStateView): string {
  const name = DEPARTMENT_STATES[state.state] ?? state.state;
  return state.note ? `${name}（${state.note}）` : name;
}

/** 等待时长的写法（与页面 formatDuration 相同）：用例自己算一遍，不借页面的函数。 */
function duration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} 秒`;
  if (total < 3600) return `${Math.floor(total / 60)} 分 ${total % 60} 秒`;
  return `${Math.floor(total / 3600)} 小时 ${Math.floor((total % 3600) / 60)} 分`;
}

test("页面事实：首页项目一览、项目页的部门、来源与回放、部门页的实时输出", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const page = client.page;
  page_ = page;
  const errors = collectConsoleErrors(page);
  try {
    // 建一个项目并开始事项：工程会向产品发出询问，产品的回答分支随后流式返回（约一分钟）。
    // 先建事项再打开部门页：部门页要有事项才有内容（没有事项时只有空态）。
    const created = await command("project.create", { name: "页面事实", goal: "把画布上的事实补到页面上" });
    const projectId = created.refs?.project_id;
    expect(projectId).toBeTruthy();
    const item = await command("work_item.create", { project_id: projectId, text: WAITING_ITEM });
    const workItemId = item.refs?.work_item_id;
    expect(workItemId).toBeTruthy();

    await test.step("首页项目一览：此刻在做什么、事项在哪个部门、执行槽位、待回答的决定", async () => {
      await page.evaluate(() => { window.location.hash = "#/home"; });
      const projects = section(page, "项目");
      await expect(projects).toBeVisible();
      const row = projects.locator("tbody tr").filter({ hasText: "页面事实" }).first();
      await expect(row).toBeVisible();
      // 此刻在做什么：进行中的部门与状态词；询问开始以后工程是「询问中」
      await waitUntil(async () => (await row.innerText()).includes("询问中"),
        "首页项目行的「此刻在做什么」出现询问中");
      const doing = await row.innerText();
      expect(doing).toContain("工程：询问中");
      expect(doing).toContain("产品：一轮工作中");
      // 事项在哪个部门：进行中的事项写标题与所在部门
      expect(doing).toContain(WAITING_ITEM);
      expect(doing).toMatch(/产品|工程|质检/);
      // 执行槽位：一个事项正在执行，没有在等的
      expect(doing).toContain("1 个事项正在执行");
      expect(doing).toContain("没有事项在等执行槽位");
      // 待回答的决定：这个项目没有
      expect(doing).toContain("无");
      // 状态项「待你决定」也没有亮起
      await expect(page.locator(".status-item.is-decisions .status-value")).toHaveText("无");
    });

    await test.step("部门页：实时的模型输出、摘要与笔记的数量、等模型服务、远程结果未知", async () => {
      const workspace = await query<WorkspaceResult>(
        "department.workspace", { project_id: projectId, department: "product", work_item: workItemId });
      await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${projectId}/dept/product`);
      await expect(page.locator("#ws-head-block")).toBeVisible();
      // 实时的模型输出：产品正在流式回答工程的询问，页面上是不断增长的文字
      const output = page.locator("[data-ws-output]");
      await expect(output).toBeVisible();
      await waitUntil(async () => (await output.innerText()).includes("正在核对需求第"),
        "部门页的实时模型输出出现流式文字");
      await expect(output.locator("[data-ws-output-text]")).toContainText("正在核对需求第");
      await expect(output.locator(".y10-ws-output-state")).toHaveText(/正在输出|最近一次输出/);
      // 手边的摘要与笔记的数量：与 department.workspace 的 room 一致
      const facts = page.locator("[data-ws-info] .y10-ws-page-facts");
      await expect(facts).toContainText(`摘要 ${workspace.room.summaries} 份、笔记 ${workspace.room.pinned_notes} 条`);
      // 等模型服务、远程结果未知：两处按查询的布尔值写中文
      await expect(facts).toContainText(workspace.room.waiting_provider ? "正在等待模型服务" : "没有在等待模型服务");
      await expect(facts).toContainText(workspace.room.remote_unknown ? "有结果未知的远程动作" : "没有结果未知的远程动作");
      const body = await page.locator("body").innerText();
      for (const word of ["waiting_provider", "remote_unknown", "summaries", "pinned_notes"]) {
        expect(body, `页面上不出现英文内部标识 ${word}`).not.toContain(word);
      }
    });

    await test.step("项目页：此刻、各部门在等什么与等了多久、中断与待恢复、已用时间与上限", async () => {
      await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${projectId}/overview`);
      await expect(section(page, "此刻")).toBeVisible();
      const loop = await query<LoopResult>("project.loop", { project_id: projectId });
      const running = loop.work_items.find((entry) => entry.status === "in_progress");
      expect(running, "事项应当在进行中").toBeDefined();
      const engineering = running!.departments?.["engineering"];
      expect(engineering?.state, "工程应当停在询问上").toBe("asking");

      const now = section(page, "此刻");
      await expect(line(now, "此刻在做什么")).toContainText("工程：询问中");
      await expect(line(now, "执行槽位")).toContainText("1 个事项正在执行");
      await expect(line(now, "大厅")).toHaveText("没有决定在等");
      // 已用时间与上限：上限部分与 project.loop 的 time_limit_sec 一致
      const elapsed = await line(now, "已用时间与上限").innerText();
      expect(elapsed).toContain(running!.sign);
      expect(elapsed).toContain(`/ ${duration(running!.time_limit_sec)}`);
      expect(elapsed).toMatch(/\d+ 秒|\d+ 分 \d+ 秒/);

      // 部门节：三个部门各一行，状态与原因照 project.loop 写；工程在等产品的回答，等了多久是一个真实时长
      const departments = section(page, "部门");
      await expect(departments).toBeVisible();
      // 行按部门名那一列按钮认（备注里也会出现别的部门名，不用整行文字认）
      const departmentRow = (name: string): Locator =>
        departments.locator("tbody tr").filter({ has: page.getByRole("button", { name, exact: true }) }).first();
      const engineeringRow = departmentRow("工程");
      await expect(engineeringRow).toContainText("询问中（在等待产品的回答）");
      await expect(engineeringRow).toContainText("在等待产品的回答");
      await expect(engineeringRow.locator("td").nth(4)).toHaveText(/^\d+ 秒$|^\d+ 分 \d+ 秒$|^\d+ 小时 \d+ 分$/);
      const qualityRow = departmentRow("质检");
      await expect(qualityRow).toContainText(departmentStateText(running!.departments?.["quality"] ?? { state: "waiting" }));
      // 点部门名进入部门页（v19：点名字进入部门页）
      await engineeringRow.getByRole("button", { name: "工程" }).click();
      await expect(page.locator("#ws-head-block")).toBeVisible();
      await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${projectId}/overview`);
      await expect(section(page, "此刻")).toBeVisible();

      // 中断与待恢复：项目里没有
      await expect(section(page, "中断与待恢复")).toContainText("没有中断，也没有待恢复的工作");
    });

    await test.step("项目页：流转按方向的次数与返工", async () => {
      const flow = section(page, "流转记录");
      await expect(flow).toBeVisible();
      // 产品接纳规格以后产生两条「PRD 新版本」：产品 → 工程、产品 → 质检
      await waitUntil(async () => (await flow.innerText()).includes("产品 → 工程"), "流转汇总出现产品 → 工程");
      const flowText = await flow.innerText();
      expect(flowText).toContain("按方向汇总");
      expect(flowText).toContain("产品 → 质检");
      expect(flowText).toContain("流转次数");
      // 汇总的次数与查询的逐条记录一致
      const records = await query<{ records: { direction_from: string | null; direction_to: string | null }[] }>(
        "project.flow", { project_id: projectId });
      const pairs = new Set(records.records.map((row) => `${row.direction_from}>${row.direction_to}`));
      expect(pairs.size).toBeGreaterThan(0);
      for (const pair of pairs) {
        const [from, to] = pair.split(">");
        if (from === "null" || to === "null") continue;
        expect(flowText).toContain("→");
      }
    });

    await test.step("项目页：事实元素的来源、点开按位置读原始事件、跳到时间轴同一位置", async () => {
      const facts = section(page, "事实与来源");
      await expect(facts).toBeVisible();
      // 等事项有了事实元素（门牌先有来源）
      await waitUntil(async () => (await facts.locator("tbody tr").count()) > 0, "事实与来源出现行");
      const loop = await query<LoopResult>("project.loop", { project_id: projectId });
      const refs = loop.work_items.flatMap((entry) => Object.entries(entry.refs ?? {}));
      expect(refs.length).toBeGreaterThan(0);
      const first = refs.map(([, ref]) => ref).sort((a, b) => a.position - b.position)[0]!;
      // 页面上有这一行：位置就是查询给的位置，来源种类是中文
      const row = facts.locator("tbody tr")
        .filter({ has: page.getByRole("cell", { name: String(first.position), exact: true }) }).first();
      await expect(row).toBeVisible();
      const rowText = await row.innerText();
      expect(rowText).toMatch(/规则|模型判断|角色陈述|主机测量|用户/);

      // 点开：按位置读原始事件（这条事件在页面打开以前就写下了）
      await row.getByRole("button", { name: "点开看原始事件" }).click();
      const detail = page.locator("[data-source-detail]");
      await expect(detail).toBeVisible();
      await expect(detail).toContainText(`位置 ${first.position} 上的原始事件`);
      const positions = await query<{ events: EventAtPosition[] }>(
        "event.positions", { project_id: projectId, positions: [first.position] });
      const event = positions.events.find((entry) => entry.position === first.position);
      expect(event?.status).toBe("available");
      // 说明、种类、提出者、时间四样来自原始事件；种类是中文，不写英文的事件标识
      await expect(detail).toContainText(event!.label ?? "");
      await expect(detail).toContainText("种类");
      const kindText = await detail.locator("div.line").filter({ hasText: "种类" }).first().locator(".value").innerText();
      expect(kindText, `种类写中文：${kindText}`).toMatch(/[\u4e00-\u9fa5]/);
      if ((event!.actor_label ?? "") !== "") {
        await expect(detail).toContainText(event!.actor_label!);
      }
      const body = await page.locator("body").innerText();
      for (const word of ["host_measurement", "role_statement", "decision_model", "work_item_created", "sign"]) {
        expect(body, `页面上不出现英文内部标识 ${word}`).not.toContain(word);
      }

      // 在时间轴上查看：回到那个位置的概览回放
      await detail.getByRole("button", { name: "在时间轴上查看" }).click();
      await expect(page).toHaveURL(new RegExp(`#/p/${projectId}/overview\\?at=${first.position}`));
      await expect(page.locator(".replay-banner")).toBeVisible();
    });

    await test.step("回放：事实与来源跟着所选位置（事项建立以前没有事实元素）", async () => {
      const loop = await query<LoopResult>("project.loop", { project_id: projectId });
      const positions = loop.work_items.flatMap((entry) => Object.values(entry.refs ?? {}).map((ref) => ref.position));
      const at = Math.max(1, Math.min(...positions) - 1);
      // 同一位置的项目状态：没有事项时页面写空态，有事项时列表跟着位置
      const before = await query<LoopResult>("project.loop", { project_id: projectId, at });
      await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${projectId}/overview?at=${at}`);
      await expect(page.locator(".replay-banner")).toBeVisible();
      await expect(page.locator(".replay-scope")).toBeVisible();
      if (before.work_items.length === 0) {
        await expect(section(page, "事实与来源")).toContainText("这个位置还没有事实元素");
        await expect(section(page, "部门")).toContainText("项目现在没有进行中的事项，没有部门在等");
      } else {
        const rows = await section(page, "事实与来源").locator("tbody tr").count();
        const refs = before.work_items.reduce((sum, entry) => sum + Object.keys(entry.refs ?? {}).length, 0);
        expect(rows).toBe(refs);
      }
    });

    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
