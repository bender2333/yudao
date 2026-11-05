// 恢复页 4 的端到端（工单 #1188）：工程执行命令时硬杀服务进程，用同一个端口与数据目录重新起服务，
// 页面重新连接以后事项自动继续、恢复页显示最后已确认位置与动作的处理方式，画面恢复。
// 服务进程是真的结束、真的重启（fixtures 的 kill：Windows 上 taskkill /T /F 结束进程树），
// 不用「模拟断开」代替。等的是信号与事件（命令写下的 started 文件、页面的连接状态、查询结果），
// 不用时长赌先后（测试分层设计说明第 10 节第 7 条）；每条等待都有自己的上限，到了上限以写明原因的错误结束。
// 控制台错误：服务不可达期间浏览器自己报的连接失败是这次用例造成的（整层变暗正是要观察的），
// 其余控制台错误一律记为失败。

import { expect, test, type Page } from "@playwright/test";
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { repoRoot, startBackend, startClient, type Backend } from "./fixtures";

// 识图自检的截图（工单 #1188 的验收：识图自检过；缺凭据时交付说明写「未识图」）
const SHOT_DIR = join(repoRoot, ".tmp", "e2e-1188");

async function shot(page: Page, name: string): Promise<void> {
  mkdirSync(SHOT_DIR, { recursive: true });
  await page.screenshot({ path: join(SHOT_DIR, `${name}.png`) });
}

const GOAL = "硬杀以后从最后确认的位置接着做";
const ITEM = "实现回声工具";

async function command(backend: Backend, name: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(`${backend.address}/api/commands/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command_id: crypto.randomUUID(), ...body }),
  });
  const payload = (await response.json()) as { refs?: Record<string, unknown>; reason?: string; message?: string };
  if (!response.ok) {
    throw new Error(`命令 ${name} 被拒绝：${payload.reason ?? ""} ${payload.message ?? ""}`);
  }
  return payload;
}

async function query<T>(backend: Backend, name: string, params: Record<string, unknown> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.append(key, String(value));
  }
  const suffix = search.toString() === "" ? "" : `?${search}`;
  const response = await fetch(`${backend.address}/api/queries/${name}${suffix}`);
  const envelope = (await response.json()) as { data?: T; reason?: string; message?: string };
  if (envelope.data === undefined) {
    throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data;
}

// 等到信号或事件出现（轮询的是状态，不是时长）；到上限以写明在等什么的错误结束
async function until(check: () => boolean | Promise<boolean>, what: string, timeoutMs = 120_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await check()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`等不到：${what}`);
}

// 整层是否在中断里：读画面给端到端测试的只读入口（工单 #1188）
async function floorInterrupted(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const hooks = (window as unknown as { __floorViewForTest?: { state: () => { interrupted: boolean } } }).__floorViewForTest;
    if (!hooks) {
      throw new Error("页面没有画面的读取入口");
    }
    return hooks.state().interrupted;
  });
}

async function openOverview(page: Page, projectId: string): Promise<void> {
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, `#/p/${projectId}/overview`);
  await expect(page.locator(".floor-screen canvas")).toHaveCount(1);
}

type LoopRow = { work_item_id: string; run_id: string; status: string; sign: string };
type LoopResult = { work_items: LoopRow[] };

async function runKillRestart(size: { width: number; height: number }): Promise<void> {
  test.setTimeout(420_000);
  const own = await startBackend({ script: "kill" });
  expect(own.signals).not.toBeNull();
  const signals = own.signals as string;
  const errors: string[] = [];
  // 服务不可达期间浏览器自己报的连接失败不算页面错误（用例造成的那一段）
  let offline = false;
  const client = await startClient(own, size);
  client.page.on("console", (message) => {
    if (message.type() !== "error") {
      return;
    }
    const text = message.text();
    if (offline && /ERR_CONNECTION|net::ERR_|Failed to load resource/i.test(text)) {
      return;
    }
    errors.push(text);
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  let again: Backend | null = null;
  try {
    const project = await command(own, "project.create", { name: "硬杀恢复", goal: GOAL });
    const projectId = (project.refs as { project_id: string }).project_id;
    const item = await command(own, "work_item.create", { project_id: projectId, text: ITEM });
    const refs = item.refs as { work_item_id: string; run_id: string };
    // 工程执行那条等着放行的命令：命令自己写下 started 信号（不是等时长）
    await until(() => existsSync(join(signals, "started")), "工程的命令开始执行");
    await openOverview(client.page, projectId);
    await expect.poll(() => floorInterrupted(client.page)).toBe(false);

    // 硬杀：结束 python 服务与它起的命令（按进程树结束，真的结束进程）
    offline = true;
    await own.kill();
    await expect(client.page.locator("body")).toHaveClass(/is-disconnected/, { timeout: 90_000 });
    await expect.poll(() => floorInterrupted(client.page), { timeout: 90_000 }).toBe(true);
    await shot(client.page, `offline-${size.width}`);

    // 同一个端口与数据目录重新起服务：启动恢复在这个进程起服务之前跑完（--hold-resume）
    again = await startBackend({ script: "kill", holdResume: true, port: own.port, dataDir: own.dataDir });
    offline = false;
    await expect(client.page.locator(".connection")).toHaveText("已连接", { timeout: 120_000 });
    await expect(client.page.locator("body")).not.toHaveClass(/is-disconnected/);

    // 事项自动继续到结束：恢复以后读到交还的那条工具结果，接着交付、质检放行、采纳
    await until(async () => {
      const loop = await query<LoopResult>(again as Backend, "project.loop", { project_id: projectId });
      return loop.work_items.some((row) => row.run_id === refs.run_id && row.status === "adopted");
    }, "事项恢复以后走到采纳");

    // 画面恢复：整层不再变暗；恢复页显示最后已确认位置、交还会话与交还给模型的内容，没有决定卡片
    await expect.poll(() => floorInterrupted(client.page), { timeout: 60_000 }).toBe(false);
    await shot(client.page, `restored-${size.width}`);
    await client.page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${projectId}/w/${refs.work_item_id}/recovery`);
    await expect(client.page.locator("#rc-reason")).toContainText("最后已确认");
    await expect(client.page.locator("#rc-verify")).toContainText("交还会话");
    await expect(client.page.locator("#rc-verify")).toContainText("执行被中断");
    await expect(client.page.locator("#rc-decide")).toContainText("没有等待你回答的决定");
    await shot(client.page, `recovery-${size.width}`);

    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await again?.stop();
    await own.stop();
  }
}

test("1440×900：工程执行命令时硬杀服务进程，重启以后事项自动继续、画面恢复", async () => {
  await runKillRestart({ width: 1440, height: 900 });
});

test("1920×1080：同一个硬杀与重启流程，控制台错误为零", async () => {
  await runKillRestart({ width: 1920, height: 1080 });
});
