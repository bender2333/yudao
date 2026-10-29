// 部门房间的端到端测试（工单 #177 验收标准 4）：Playwright 打开 Chromium 页面，连接由 FakeAdapter
// 驱动的真实服务；先打开部门房间，再经由命令开始事项，让产品的模型请求在房间打开期间分三段
// 流式返回。核对思考气泡里的文字与 attempt.live 及随后的片段拼接一致；交接与询问时两端的小人各说一句。
//
// 观测方式：从查询与事件流取真实数据，从画面读取入口（__roomViewForTest）取房间的当前状态；
// 不做伪造。页面用后端提供的构建产物（与 shell.spec.ts 相同）。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

interface RoomViewState {
  department: string;
  status: string | null;
  characters: { id: string; kind: string; doing: string | null; pose: string | null; say: string | null; stream: string | null }[];
  letters: number;
}

let backend: Backend;

function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

async function query<T>(name: string, params: Record<string, unknown> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) search.append(key, String(value));
  const qs = search.toString();
  const response = await fetch(`${backend.address}/api/queries/${name}${qs ? `?${qs}` : ""}`);
  const envelope = (await response.json()) as QueryEnvelope<T>;
  if (envelope.data === undefined) {
    throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data;
}

/** 直发命令（服务端真实登记事件，不是测试替身）；已有事项在跑时等它结束再重试。 */
async function command(name: string, payload: Record<string, unknown>): Promise<void> {
  const deadline = Date.now() + 120_000;
  for (;;) {
    const response = await fetch(`${backend.address}/api/commands/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command_id: crypto.randomUUID(), ...payload }),
    });
    if (response.status === 200) return;
    const text = await response.text();
    if (response.status === 409 && text.includes("busy") && Date.now() < deadline) {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 400);
      await promise;
      continue;
    }
    throw new Error(`命令 ${name} 被拒绝：HTTP ${response.status} ${text}`);
  }
}

/** 等某个条件成立（页面按事件流自动重查询，不刷新页面）。 */
async function waitUntil(check: () => Promise<boolean>, description: string, timeoutMs = 240_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) return;
    if (Date.now() > deadline) throw new Error(`等待超时：${description}`);
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 250);
    await promise;
  }
}

/** 房间画面的当前状态（经读取入口）。 */
async function roomState(page: Page): Promise<RoomViewState | null> {
  return page.evaluate(() => {
    const hooks = (window as unknown as { __roomViewForTest?: { state: () => RoomViewState } }).__roomViewForTest;
    return hooks ? hooks.state() : null;
  });
}

async function openRoom(page: Page, projectId: string, department: string): Promise<void> {
  await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${projectId}/dept/${department}`);
  await expect(page.locator(".room-canvas canvas")).toHaveCount(1);
}

test("产品房间：模型请求进行中，思考气泡里的文字与 attempt.live 及随后的片段拼接一致", async () => {
  test.setTimeout(600_000);
  backend = await startBackend({ room: true });
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const projectId = backend.roomProject;
    expect(projectId).not.toBeNull();
    await openRoom(page, projectId!, "product");
    // 房间打开以后才开始事项：模型的流式输出在房间打开期间分段到达
    await command("work_item.create", { project_id: projectId, text: "为待办清单增加截止日期" });
    // 第一段到达时查询 attempt.live：此时调用仍在进行，拿到的是房间打开以后已经收到的文字
    await waitUntil(async () => {
      const bubble = (await roomState(page))?.characters.map((c) => c.stream).find((s) => s !== null) ?? "";
      return bubble.includes("正在阅读需求");
    }, "思考气泡里出现第一段流式文字");
    const attempts = await query<{ attempts: { attempt_id: string; status: string; department: string | null }[] }>(
      "project.attempts", { project_id: projectId, limit: 5 });
    const running = attempts.attempts.find((a) => a.department === "product" && a.status === "running");
    expect(running).toBeDefined();
    const live = await query<{ live: boolean; channels: Record<string, string> }>("attempt.live", { attempt_id: running!.attempt_id });
    expect(live.live).toBe(true);
    const liveText = live.channels.output ?? "";
    expect(liveText.length).toBeGreaterThan(0);
    // 气泡继续随片段增长：三段拼接全部出现
    await waitUntil(async () => {
      const bubble = (await roomState(page))?.characters.map((c) => c.stream).find((s) => s !== null) ?? "";
      return bubble.includes("正在写出 PRD 的要点");
    }, "思考气泡里出现三段拼接的流式文字");
    const bubble = (await roomState(page))?.characters.map((c) => c.stream).find((s) => s !== null) ?? "";
    // 与 attempt.live 及随后的片段拼接一致：气泡以查询到的文字开头，再依次接上三段片段
    expect(bubble.startsWith(liveText)).toBe(true);
    expect(bubble).toContain("正在阅读需求");
    expect(bubble).toContain("正在整理验收条件");
    expect(bubble).toContain("正在写出 PRD 的要点");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});

test("交接：交出方与接收方各说一句", async () => {
  test.setTimeout(600_000);
  // 交出方：工程把交付箱送给质检的那一刻，工程房间里的小人头顶说出这句话
  {
    backend = await startBackend({ room: true });
    const client = await startClient(backend, { width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const projectId = backend.roomProject;
      expect(projectId).not.toBeNull();
      await openRoom(page, projectId!, "engineering");
      await command("work_item.create", { project_id: projectId, text: "为待办清单增加截止日期" });
      await waitUntil(async () => {
        const state = await roomState(page);
        return (state?.characters.some((c) => (c.say ?? "").includes("交付箱"))) ?? false;
      }, "交出方说出交付箱");
      const given = (await roomState(page))?.characters.find((c) => (c.say ?? "").includes("交付箱"));
      expect(given?.say).toMatch(/现在把交付箱送给质检/);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  }
  // 接收方：同一时刻质检房间里的小人头顶说收到交付箱
  {
    backend = await startBackend({ room: true });
    const client = await startClient(backend, { width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const projectId = backend.roomProject;
      await openRoom(page, projectId!, "quality");
      await command("work_item.create", { project_id: projectId, text: "为待办清单增加截止日期" });
      await waitUntil(async () => {
        const state = await roomState(page);
        return (state?.characters.some((c) => (c.say ?? "").includes("收到交付箱"))) ?? false;
      }, "接收方说出收到交付箱");
      const got = (await roomState(page))?.characters.find((c) => (c.say ?? "").includes("收到交付箱"));
      expect(got?.say).toMatch(/收到交付箱，来自工程/);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  }
});

test("询问与回答：两端的小人各说一句", async () => {
  test.setTimeout(600_000);
  // 发问方：工程向质检发出询问
  {
    backend = await startBackend({ room: true });
    const client = await startClient(backend, { width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const projectId = backend.roomProject;
      expect(projectId).not.toBeNull();
      await openRoom(page, projectId!, "engineering");
      await command("work_item.create", { project_id: projectId, text: "为待办清单增加截止日期" });
      await waitUntil(async () => {
        const state = await roomState(page);
        return (state?.characters.some((c) => (c.say ?? "").includes("发出询问"))) ?? false;
      }, "发问方说出询问");
      const asker = (await roomState(page))?.characters.find((c) => (c.say ?? "").includes("发出询问"));
      expect(asker?.say).toMatch(/现在向质检发出询问/);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  }
  // 回答方：质检房间的小人头顶说收到工程的询问
  {
    backend = await startBackend({ room: true });
    const client = await startClient(backend, { width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const projectId = backend.roomProject;
      await openRoom(page, projectId!, "quality");
      await command("work_item.create", { project_id: projectId, text: "为待办清单增加截止日期" });
      await waitUntil(async () => {
        const state = await roomState(page);
        return (state?.characters.some((c) => (c.say ?? "").includes("收到工程的询问"))) ?? false;
      }, "回答方说出收到询问");
      const answerer = (await roomState(page))?.characters.find((c) => (c.say ?? "").includes("收到工程的询问"));
      expect(answerer?.say).toMatch(/收到工程的询问/);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
      await backend.stop();
    }
  }
});

test("工具类与盖章类的说明：小人头顶说出目录里对应的那句话", async () => {
  test.setTimeout(600_000);
  // 工单 #319 第 3 项、工单 #954 按画面合同改写：房间按播放时间线演动作——关键一级（交接、盖章、询问与回答）
  // 一定演，普通一级（读文件、跑命令、改文件）在画面落后时按设计丢掉（H8），头顶的进度只保留最近一项。
  // 所以端到端能稳定核对的是：关键一级的说明就是说话目录里那句；堆积时关键动作一个也不丢、也不被截断。
  // 工具类那句话的内容（工具名、文件名、命令名）由 tests/unit/pixel-room.test.ts 与
  // tests/unit/translate-room.test.ts 用真实载荷核对，不在端到端里强制它出现。
  const collected = async (department: string, pattern: RegExp, description: string): Promise<{ hits: string[]; stats: Record<string, number> }> => {
    backend = await startBackend({ room: true });
    const client = await startClient(backend, { width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const projectId = backend.roomProject;
      expect(projectId).not.toBeNull();
      await openRoom(page, projectId!, department);
      const seen = new Set<string>();
      await command("work_item.create", { project_id: projectId, text: "为待办清单增加截止日期" });
      const deadline = Date.now() + 240_000;
      while (Date.now() < deadline) {
        for (const c of (await roomState(page))?.characters ?? []) {
          if (c.say) seen.add(c.say);
        }
        if ([...seen].some((line) => pattern.test(line))) break;
        await page.waitForTimeout(200);
      }
      expect(errors).toEqual([]);
      const hits = [...seen].filter((line) => pattern.test(line));
      if (hits.length === 0) {
        throw new Error(`${description}：房间里出现过的说明是 ${[...seen].join(" / ") || "（一句也没有）"}`);
      }
      const timeline = await page.evaluate(() => {
        const hooks = (window as unknown as { __roomViewForTest?: { timeline: () => { stats: Record<string, number> } } }).__roomViewForTest;
        return hooks ? hooks.timeline().stats : null;
      });
      expect(timeline).not.toBeNull();
      return { hits, stats: timeline! };
    } finally {
      await client.close();
      await backend.stop();
    }
  };

  // 工程房间：交接的两端与装箱封存都是关键一级，说的话是目录里那句
  const engineeringRun = await collected("engineering", /^(现在装箱封存|现在把交付箱送给质检|收到PRD，来自产品)/,
                                        "工程房间的交接口令");
  for (const line of engineeringRun.hits) {
    expect(line).toMatch(/^(现在装箱封存|现在把交付箱送给质检|收到PRD，来自产品)$/);
  }
  // 堆积时普通一级的动作被丢掉，关键一级一个也不丢、正在演的不截断（H9）
  expect(engineeringRun.stats.droppedKey).toBe(0);
  expect(engineeringRun.stats.cutKey).toBe(0);
  // 质检房间：盖章类的事件说出盖的是哪一章
  const qualityRun = await collected("quality", /^现在盖/, "质检房间的盖章类说明");
  for (const line of qualityRun.hits) {
    expect(line).toMatch(/^现在盖(上有效章|放行章|返工章)/);
  }
  expect(qualityRun.stats.droppedKey).toBe(0);
});

test("部门页签之间直接切换：每个页签的房间画面属于该部门，页面不出现加载失败", async () => {
  test.setTimeout(600_000);
  backend = await startBackend({ room: true });
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const projectId = backend.roomProject;
    expect(projectId).not.toBeNull();
    // 从概览进入，然后依次直接点部门页签（工单 #300：中途不回概览也不刷新页面）
    await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${projectId}/overview`);
    await expect(page.locator(".tabbar .tab").first()).toBeVisible();
    const tabs: { label: string; department: string }[] = [
      { label: "产品", department: "product" },
      { label: "工程", department: "engineering" },
      { label: "质检", department: "quality" },
      { label: "产品", department: "product" },
    ];
    for (const tab of tabs) {
      const failed = page.locator(".pixel-canvas-error");
      await page.locator(".tabbar .tab").filter({ hasText: tab.label }).click();
      // 画面属于该部门：等读取入口报告这个部门（换部门时画面重建，入口随新画面挂上）。
      // 页面出现「部门房间加载失败」立刻停下，失败信息里带上那行红字（工单 #300 的现象）
      await waitUntil(async () => {
        if (await failed.count() > 0) {
          throw new Error(`${tab.label}页签出现加载失败：${await failed.innerText()}`);
        }
        return (await roomState(page))?.department === tab.department;
      }, `${tab.label}部门的画面建立`, 60_000);
      await expect(failed).toHaveCount(0);
      const state = await roomState(page);
      expect(state?.department).toBe(tab.department);
      // 房间数据来自该部门的查询结果：角色属于该部门
      const workspace = await query<{ room: { roles: { id: string }[] } }>(
        "department.workspace", { project_id: projectId, department: tab.department });
      const roleIds = workspace.room.roles.map((r) => r.id).sort();
      // 画面建立早于查询结果到达，角色是数据到了以后才装进画面：等它们出现再断言（工单 #300）
      await waitUntil(async () => {
        if (await failed.count() > 0) {
          throw new Error(`${tab.label}页签出现加载失败：${await failed.innerText()}`);
        }
        const present = new Set((await roomState(page))?.characters.map((c) => c.id) ?? []);
        return roleIds.every((id) => present.has(id));
      }, `${tab.label}部门的角色装进画面`, 60_000);
      const loaded = await roomState(page);
      expect(loaded?.characters.map((c) => c.id).filter((id) => roleIds.includes(id)).sort()).toEqual(roleIds);
    }
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});


// 部门工作间的部门状态、三个部门一行与询问（原型 v12 设计说明第 3.1、3.3 节、三部门的循环结构第 2.1 节，
// 工单 #905）：用种子里的两个项目核对真后端下的页面。
// 「交付历史」的事项已经结束：工程部门页的询问一节列出本部门发出与收到的两次询问，其中一次是收到的
// （质检 → 工程）与它的回答；没有部门状态，标题区按事项的结束方式写；传信管上没有等待回答的询问，这一行不写。
// 「文本工具」的事项停在模型不可用：被模型挡住的工程部门标题区是「等用户」，三个部门一行里本部门加粗。
// 两页都不出现「正在工作 · …」「这次运行不在本部门」这两种旧写法，也没有阶段名称与协作请求。
test("部门页：三个部门的状态、本部门的询问与传信管", async () => {
  test.setTimeout(600_000);
  backend = await startBackend();
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    const projects = await query<{ projects: { name: string; project_id: string }[] }>("projects.list");
    const projectOf = (name: string): string => {
      const row = projects.projects.find((project) => project.name === name);
      if (row === undefined) {
        throw new Error(`projects.list 里没有项目 ${name}（现有：${projects.projects.map((project) => project.name).join("、")}）`);
      }
      return row.project_id;
    };
    const head = (title: string) =>
      page.locator("section.card").filter({ has: page.getByRole("heading", { name: title, exact: true }) }).first();
    const asksSection = () =>
      page.locator("section.card").filter({ has: page.getByRole("heading", { name: "询问", exact: true }) }).first();
    const openDepartment = async (project: string, department: string): Promise<void> => {
      await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${project}/dept/${department}`);
    };

    // 交付历史：工程部门页的询问一节列出本部门发出与收到的询问，收到的那次有回答
    await openDepartment(projectOf("交付历史"), "engineering");
    const historyAsks = asksSection();
    await expect(historyAsks).toBeVisible();
    await expect(historyAsks).toContainText("质检 → 工程");
    await expect(historyAsks).toContainText("Which acceptance line governs the rework?");
    await expect(historyAsks).toContainText("回答：Follow the acceptance line recorded in the requirement.");
    // 本部门发出的那次也在这张页上（工程 → 产品）
    await expect(historyAsks).toContainText("工程 → 产品");
    // 事项已经结束：没有三个部门一行，标题区按结束方式写（放行）
    const historyHead = head("工程部门");
    await expect(historyHead).toContainText("已完成并放行");
    await expect(historyHead.locator(".department-line")).toHaveCount(0);
    // 传信管上没有等待本部门回答的询问：这一行不写
    await expect(page.locator("[data-ws-tube]")).toHaveCount(0);
    const historyText = await page.locator(".page").innerText();
    expect(historyText).not.toContain("正在工作 ·");
    expect(historyText).not.toContain("这次运行不在本部门");
    expect(historyText).not.toContain("阶段");
    expect(historyText).not.toContain("协作请求");

    // 文本工具：被模型挡住的工程部门标题区状态是「等用户」
    await openDepartment(projectOf("文本工具"), "engineering");
    const blockedHead = head("工程部门");
    await expect(blockedHead).toBeVisible();
    await expect(blockedHead.locator(".y10-status").first()).toHaveText("等用户");
    // 三个部门一行：本部门那一段加粗，其余部门不加粗
    const states = blockedHead.locator(".department-line");
    await expect(states).toContainText("三个部门");
    await expect(states).toContainText("产品 等待工作");
    await expect(states).toContainText("质检 等待工作");
    await expect(states.locator("strong")).toHaveText("工程 等用户");
    // 这个事项还没有询问：询问一节写没有询问，传信管那一行不写
    await expect(asksSection()).toContainText("这个事项里本部门还没有发出或收到询问");
    await expect(page.locator("[data-ws-tube]")).toHaveCount(0);
    const blockedText = await page.locator(".page").innerText();
    expect(blockedText).not.toContain("正在工作 ·");
    expect(blockedText).not.toContain("这次运行不在本部门");
    expect(blockedText).not.toContain("阶段");
    expect(blockedText).not.toContain("协作请求");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});

// 「房间里的角色」那一行的文字（工单 #1230）：角色的当前任务只在有事实说明它此刻做什么时才填，
// 现在没有这样的事实，所以这一格是中文状态词（工作中、未工作），不是 working、idle 这样的原始标识，
// 也不再拿事项标题顶上；事项标题只留在房间屏幕的目标行。
test("房间角色条：事项进行中显示中文状态词，不显示事项标题与原始标识", async () => {
  test.setTimeout(600_000);
  backend = await startBackend({ room: true });
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  // 事项标题取自用户输入的原文，与页面上的「所选事项」一致
  const title = "为待办清单增加截止日期";
  try {
    const projectId = backend.roomProject;
    expect(projectId).not.toBeNull();
    await openRoom(page, projectId!, "product");
    // 房间打开以后才开始事项：角色的状态在页面不刷新的情况下随事件流更新
    await command("work_item.create", { project_id: projectId, text: title });
    // 页面已经换成这个事项：标题区与角色条由同一份 department.workspace 的查询结果驱动
    const itemLine = page.locator(".y10-ws-item", { hasText: "所选事项" }).first();
    await expect(itemLine).toContainText(title);
    // 事项标题留在房间屏幕的目标行（同一份查询结果的 crt.target）
    const overview = await query<{ work_items: { work_item_id: string; title: string }[] }>(
      "project.overview", { project_id: projectId });
    const started = overview.work_items.find((item) => item.title === title);
    expect(started).toBeDefined();
    await waitUntil(async () => {
      const workspace = await query<{ room: { crt: { target: string } } }>(
        "department.workspace",
        { project_id: projectId, department: "product", work_item: started!.work_item_id });
      return workspace.room.crt.target === title;
    }, "房间屏幕的目标行是事项标题");
    const roles = page.locator(".y10-ws-roles");
    await expect(roles).toBeVisible();
    const text = await roles.innerText();
    expect(text).toContain("产品部门 Agent");
    // 中文状态词：事项进行中是「工作中」，结束以后是「未工作」
    expect(text).toMatch(/工作中|未工作/);
    // 不出现 working、idle 这样的原始标识
    expect(text).not.toMatch(/\b(working|idle)\b/);
    // 事项标题不出现在角色条上（它的任何一段文字都不出现）
    expect(text).not.toContain(title);
    expect(text).not.toContain("待办清单");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});
