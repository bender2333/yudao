// 排空区的端到端（工单 #1187 的页面流程；工单 #1188 把它并入整层中断与硬杀的一组端到端）：
// 开始排空以后新建的事项排队；强制升级以后进行中的 run 显示「因升级停止」，对应的事项重新开始一个新的 run。
// 占住一个正在进行的 run 用的是真实的工程命令（等放行的子进程，与硬杀重启用例同一套装置），不是假的延迟。
// 等的是信号与事件（命令写下的 started 文件、查询结果、页面的状态），不用时长赌先后。

import { expect, test } from "@playwright/test";
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { repoRoot, startBackend, startClient, type Backend } from "./fixtures";

const GOAL = "核对排空与强制升级";
const ITEM = "排空时正在执行的事项";
const QUEUED = "排空期间新提的事项";
// 识图自检的截图（工单 #1188）
const SHOT_DIR = join(repoRoot, ".tmp", "e2e-1188");

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

type LoopRow = {
  work_item_id: string; run_id: string; status: string; sign: string; stop_reason: string | null;
};

test("排空区：开始排空以后新建事项排队，强制升级以后旧 run 因升级停止、新的 run 开始", async () => {
  test.setTimeout(300_000);
  const own = await startBackend({ script: "kill" });
  expect(own.signals).not.toBeNull();
  const signals = own.signals as string;
  const errors: string[] = [];
  const client = await startClient(own, { width: 1440, height: 900 });
  client.page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  try {
    const project = await command(own, "project.create", { name: "排空区", goal: GOAL });
    const projectId = (project.refs as { project_id: string }).project_id;
    const item = await command(own, "work_item.create", { project_id: projectId, text: ITEM });
    const runId = (item.refs as { run_id: string }).run_id;
    // 工程执行那条等着放行的命令：占住执行槽位，run 停在非终态
    await until(() => existsSync(join(signals, "started")), "工程的命令开始执行");

    // 运行与执行槽位页：开始排空（先确认，确认框写明不再开始新事项）
    await client.page.getByRole("button", { name: "运行与执行槽位", exact: true }).click();
    await expect(client.page.locator(".path")).toHaveText("执行槽位");
    await client.page.getByRole("button", { name: "开始排空", exact: true }).click();
    await expect(client.page.locator(".y10-modal")).toContainText("不再开始新事项");
    await client.page.getByRole("button", { name: "不再开始新事项", exact: true }).click();
    await expect(client.page.locator(".y10-sys-runtime")).toContainText("排空中");
    await expect(client.page.locator(".y10-sys-runtime")).toContainText("开始时间");
    await expect(client.page.locator(".y10-sys-runtime")).toContainText(ITEM);

    // 排空期间新建的事项排队、不开始（系统状态里的排队数为 1，页面上也写这一行）
    await command(own, "work_item.create", { project_id: projectId, text: QUEUED });
    await until(async () => {
      const status = await query<{ drain: { state: string; queued_work_items: number } }>(own, "system.status");
      return status.drain.state === "draining" && status.drain.queued_work_items === 1;
    }, "排空期间新建的事项排进队列");
    await expect(client.page.locator(".y10-sys-runtime")).toContainText("排队中的事项");

    // 强制升级（先确认，确认框写明会让正在进行的 run 记为因升级停止）
    await client.page.getByRole("button", { name: "强制升级", exact: true }).click();
    await expect(client.page.locator(".y10-modal")).toContainText("因升级停止");
    await client.page.getByRole("button", { name: "确认强制升级", exact: true }).click();
    await expect(client.page.locator(".y10-sys-runtime")).toContainText("已强制升级", { timeout: 30_000 });
    mkdirSync(SHOT_DIR, { recursive: true });
    await client.page.screenshot({ path: join(SHOT_DIR, "forced-1440.png") });

    // 旧的 run 因升级停止：恢复观察状态是「已停止」，停止原因是因升级停止
    await until(async () => {
      const loop = await query<{ work_items: LoopRow[] }>(own, "project.loop", { project_id: projectId });
      const old = loop.work_items.find((row) => row.run_id === runId);
      return old !== undefined && old.status === "stopped" && old.stop_reason === "run_event_version_changed";
    }, "旧的 run 因升级停止");

    // 对应的事项重新开始一个新的 run（标题相同、run 标识不同，停在非终态表示它在进行中）
    const loop = await query<{ work_items: LoopRow[] }>(own, "project.loop", { project_id: projectId });
    const restarted = loop.work_items.filter((row) => row.sign === ITEM && row.run_id !== runId);
    expect(restarted.length).toBe(1);
    expect(restarted[0].status).toBe("in_progress");

    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await own.stop();
  }
});
