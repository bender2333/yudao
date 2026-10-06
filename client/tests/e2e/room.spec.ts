// 部门房间的端到端测试（工单 #177 验收标准 4）：Playwright 启动 Electron，连接由 FakeAdapter
// 驱动的真实服务；先打开部门房间，再经由命令开始事项，让产品的模型请求在房间打开期间分三段
// 流式返回。核对思考气泡里的文字与 attempt.live 及随后的片段拼接一致；交接与询问时两端的小人各说一句。
//
// 观测方式：从查询与事件流取真实数据，从画面读取入口（__roomViewForTest）取房间的当前状态；
// 不做伪造。渲染进程用构建产物（与 shell.spec.ts 相同）。

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
