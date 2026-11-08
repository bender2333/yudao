// 取消事项的确认（工单 #737）：取消不可逆——事项停下以后不能接着做，只能另建一个事项。
// 点「取消事项」时先出现确认，写明这条后果；点「先不取消」时命令没有发出、事项还在进行；
// 确认以后才真的取消，事项停在「运行已被取消」。
// 与开始排空、强制升级、移除模型访问定义同一套做法：确认按钮 danger、不做的那个普通样式。
// 事项由用例在接口上建（与 runtime.spec.ts 同一套装置：工程的命令等着放行，事项停在非终态），
// 等的是信号与查询结果，不用时长赌先后。

import { expect, test } from "@playwright/test";
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { repoRoot, startBackend, startClient, type Backend } from "./fixtures";

const GOAL = "核对取消事项的确认";
const ITEM = "取消时正在执行的事项";
// 确认框与页面状态的截图（工单 #737 的界面证据，文件名写清页面与状态）
const SHOT_DIR = join(repoRoot, ".tmp", "737-shots");

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
  work_item_id: string; run_id: string; status: string; stop_reason: string | null;
};

async function itemRow(backend: Backend, projectId: string, workItemId: string): Promise<LoopRow | undefined> {
  const loop = await query<{ work_items: LoopRow[] }>(backend, "project.loop", { project_id: projectId });
  return loop.work_items.find((row) => row.work_item_id === workItemId);
}

test("取消事项：点下去先确认，先不取消时事项还在进行，确认以后事项停在已取消", async () => {
  test.setTimeout(300_000);
  const backend = await startBackend({ script: "kill" });
  expect(backend.signals).not.toBeNull();
  const signals = backend.signals as string;
  const errors: string[] = [];
  const client = await startClient(backend, { width: 1440, height: 900 });
  client.page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  try {
    const project = await command(backend, "project.create", { name: "取消确认的核对", goal: GOAL });
    const projectId = (project.refs as { project_id: string }).project_id;
    const item = await command(backend, "work_item.create", { project_id: projectId, text: ITEM });
    const workItemId = (item.refs as { work_item_id: string }).work_item_id;
    // 工程执行那条等着放行的命令：事项停在非终态（进行中）
    await until(() => existsSync(join(signals, "started")), "工程的命令开始执行");

    // 概览页的当前事项：这一个事项在进行中，「取消事项」按钮在这里
    await client.page.evaluate((hash) => {
      window.location.hash = hash;
    }, `#/p/${projectId}/overview`);
    const current = client.page.locator("#ov-current");
    await expect(current).toContainText(ITEM, { timeout: 60_000 });
    // 不可逆的操作一律用 danger 样式（工单 #737）：从样式就能分出危险性
    await expect(client.page.getByTestId("cancel-item")).toHaveClass(/danger/);
    mkdirSync(SHOT_DIR, { recursive: true });
    // 按钮在概览页的下面一段：截「当前事项」这一节，证明它确实是红的那一个
    await client.page.locator("#ov-current").screenshot({ path: join(SHOT_DIR, "overview-cancel-item-1440.png") });

    // 点下去先出现确认，写明取消以后不能恢复、只能另建一个事项；命令没有发出，事项还在进行
    await client.page.getByTestId("cancel-item").click();
    const dialog = client.page.locator(".y10-modal");
    await expect(dialog).toContainText("取消以后不能恢复");
    await expect(dialog).toContainText("只能另建一个事项");
    mkdirSync(SHOT_DIR, { recursive: true });
    await client.page.screenshot({ path: join(SHOT_DIR, "cancel-item-confirm-1440.png") });
    expect((await itemRow(backend, projectId, workItemId))?.status).toBe("in_progress");

    // 先不取消：确认框收起，事项仍然进行中，命令始终没有发出
    await client.page.getByTestId("cancel-item-dismiss").click();
    await expect(dialog).toHaveCount(0);
    await expect(current).toContainText(ITEM);
    const stillRunning = await itemRow(backend, projectId, workItemId);
    expect(stillRunning?.status).toBe("in_progress");
    expect(stillRunning?.stop_reason).toBeNull();

    // 再来一次并确认：这一次真的取消，事项停在「运行已被取消」
    await client.page.getByTestId("cancel-item").click();
    await expect(dialog).toContainText("取消以后不能恢复");
    await client.page.getByTestId("cancel-item-confirm").click();
    await until(async () => {
      const row = await itemRow(backend, projectId, workItemId);
      return row !== undefined && row.status === "stopped" && row.stop_reason === "cancelled";
    }, "事项停在已取消");

    // 事项停下来以后概览的当前事项换成空态，按钮不再出现
    await expect(client.page.locator("body")).toContainText("项目没有进行中的事项");
    await expect(client.page.getByTestId("cancel-item")).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});
