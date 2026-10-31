// 覆盖层「循环」与观测页「循环」区块（工单 #400 的验收：两处显示实例树的层、已用边界与收敛状态，
// 数据与 run.loops 一致）。Playwright 打开 Chromium，页面由 FakeAdapter 驱动的真实服务提供：
// 覆盖层按钮按能力清单出现，打开以后画布上写 run 层的收敛状态与各部门这次激活、步骤循环；
// 观测页在「请求记录与用量」之后多出「循环」区块，按事项列出五层与每次激活的步骤循环。
//
// 覆盖层画在画布上，测试经页面上给端到端测试的只读入口读它画的是什么（与 floor.sources 同一做法）；
// 期望值取同一次运行上的 run.loops 查询结果，核对两处与查询一致。

import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

type OverlayView = { id: string | null; data: Record<string, unknown> | null };
type LoopsOverlay = {
  bar: { text: string; state: string };
  rooms: { department: string; state: string; text: string; step_text: string }[];
  legend: { state: string; label: string }[];
};
type LoopAmount = { used: number; limit: number; unlimited: boolean };
type LoopLayerView = { name: string; state: string; missing: string | null; amounts: Record<string, LoopAmount> };
type LoopActivationView = { activation_id: string; department: string | null; state: string; missing: string; steps: { purpose: string }[] };
type RunLoopsView = {
  run_id: string; status: string; stop_reason: string | null; parameters: Record<string, number>;
  method: Record<string, number>; layers: LoopLayerView[]; activations: LoopActivationView[]; rounds: number;
};

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  // 流式片段之间停 0.5 秒（--script pending）：新事项在部门房间里待得久一些，覆盖层有时间读到一次激活
  backend = await startBackend({ script: "pending" });
});

test.afterAll(async () => {
  await backend?.stop();
});

type AcceptedEnvelope = { ok?: boolean; reason?: string; message?: string };

/** 发一条命令（与页面走同一个接口），返回受理回执（新建对象的命令带 refs）。 */
async function command(name: string, body: Record<string, unknown>): Promise<{ refs?: Record<string, string> }> {
  const response = await fetch(`${backend.address}/api/commands/${name}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ command_id: randomUUID(), ...body }),
  });
  const raw = await response.text();
  const envelope = JSON.parse(raw) as AcceptedEnvelope & { refs?: Record<string, string> };
  if (response.status >= 400 || envelope.ok === false) {
    throw new Error(`命令 ${name} 被拒绝（${response.status}）：${raw.slice(0, 400)}`);
  }
  return envelope;
}

/** 读一个查询（与页面同一条接口）：返回查询结果的数据部分。 */
async function query<T>(name: string, params: Record<string, string>): Promise<T> {
  const search = new URLSearchParams(params).toString();
  const response = await fetch(`${backend.address}/api/queries/${name}?${search}`);
  const raw = await response.text();
  if (response.status >= 400) throw new Error(`查询 ${name} 失败（${response.status}）：${raw.slice(0, 400)}`);
  return (JSON.parse(raw) as { data: T }).data;
}

async function createProject(name: string): Promise<string> {
  const accepted = await command("project.create", { name, goal: "核对循环的层、已用边界与收敛状态" });
  const id = accepted.refs?.project_id;
  if (!id) throw new Error("project.create 没有返回项目标识");
  return id;
}

/** 项目当前那次运行的标识（project.overview 的事项卡片带 run_id）。 */
async function currentRun(projectId: string): Promise<string> {
  const overview = await query<{ work_items: { run_id: string }[] }>("project.overview", { project_id: projectId });
  const runId = overview.work_items.map((item) => item.run_id).find((value) => value !== "");
  if (!runId) throw new Error("项目还没有运行");
  return runId;
}

async function hooksOf(page: Page, what: "overlay"): Promise<OverlayView> {
  return page.evaluate((name) => {
    const hooks = (window as unknown as { __floorViewForTest?: Record<string, () => unknown> }).__floorViewForTest;
    if (!hooks) throw new Error("页面没有画面的读取入口");
    return hooks[name]() as never;
  }, what);
}

test("覆盖层「循环」与观测页「循环」区块：层、已用边界与收敛状态来自 run.loops", async () => {
  test.setTimeout(240_000);
  const id = await createProject("循环覆盖层");
  const client: ClientApp = await startClient(backend, { width: 1440, height: 900 });
  const page = client.page;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${id}/overview`);
    await expect(page.locator(".floor-screen canvas")).toHaveCount(1);
    // 覆盖层按钮「循环」按能力清单出现（能力清单里登记了 loops → run.loops），点开以后画布上开始有标签
    const button = page.getByRole("button", { name: "循环", exact: true });
    await expect(button).toHaveCount(1);
    // 页面上开始一个事项：这次运行有激活与步骤，覆盖层才有东西可写
    await command("work_item.create", { project_id: id, text: "循环覆盖层的新事项" });
    await button.click();
    await expect(button).toHaveClass(/is-on/);
    let overlay: LoopsOverlay | null = null;
    for (let i = 0; i < 300 && overlay === null; i += 1) {
      const view = await hooksOf(page, "overlay");
      if (view.id === "loops" && view.data !== null) {
        const data = view.data as unknown as LoopsOverlay;
        if (data.bar && data.bar.text !== "还没有运行" && data.rooms.length > 0) overlay = data;
      }
      if (overlay === null) await page.waitForTimeout(100);
    }
    expect(overlay).not.toBeNull();
    // 图例写五种状态与「不判定」，文字是中文
    expect(overlay!.legend.map((row) => row.label)).toEqual(["收敛中", "停滞", "震荡", "漂移", "达到边界", "不判定"]);
    // 信息条写 run 层，房间写这次激活与步骤循环，部门是中文名
    expect(overlay!.bar.text).toContain("运行 · ");
    expect(overlay!.rooms.length).toBeGreaterThan(0);
    expect(overlay!.rooms[0].text).toMatch(/第 \d+ 次激活 · /);
    expect(overlay!.rooms[0].step_text).toContain("步骤");
    // 与查询一致：同一次运行上的 run.loops 给出同样的状态与步骤数
    const runId = await currentRun(id);
    const loops = await query<RunLoopsView>("run.loops", { run_id: runId });
    const runLayer = loops.layers.find((layer) => layer.name === "run")!;
    const stepLayer = loops.layers.find((layer) => layer.name === "step")!;
    expect(overlay!.bar.state).toBe(runLayer.state);
    const workSteps = loops.activations[0].steps.filter((step) => step.purpose !== "compaction").length;
    expect(overlay!.rooms[0].step_text).toBe(`步骤 ${workSteps} 步 · ${
      stepLayer.state === "converging" ? "收敛中" : stepLayer.state === "stalled" ? "停滞"
      : stepLayer.state === "oscillating" ? "震荡" : stepLayer.state === "boundary" ? "达到边界" : "不判定"}`);
    // 页面上不出现英文内部标识（画布上的字看不见，这里核对页面上能读到的文字）
    const text = await page.locator("body").innerText();
    for (const word of ["converging", "undetermined", "project_loop", "run.loops"]) {
      expect(text).not.toContain(word);
    }

    // 页面证据（验收要求交付说明附截图）：给出手稿路径时各截一张整页图，
    // 一张覆盖层「循环」，一张观测页的「循环」区块
    if (process.env.YUDAO_LOOPS_SHOT_DIR) {
      await page.screenshot({ path: `${process.env.YUDAO_LOOPS_SHOT_DIR}/floor-loops-overlay.png` });
    }

    // 转观测页：「循环」区块在「请求记录与用量」之后，列出五层与每次激活的步骤循环
    await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${id}/observe`);
    const block = page.locator("#observe-loops");
    await expect(block).toHaveCount(1);
    await expect(block).toContainText("循环");
    const table = block.locator("table");
    await expect(table).toHaveCount(1);
    await expect(table).toContainText("项目循环");
    await expect(table).toContainText("事项");
    await expect(table).toContainText("运行");
    await expect(table).toContainText("激活");
    await expect(table).toContainText("步骤");
    await expect(table).toContainText("不判定");
    // 不设上限的那一项写「不设上限」，同时保留数值
    await expect(table).toContainText("不设上限");
    // 判定依据：冻结的三项参数与方法常量
    await expect(block).toContainText("收敛判定看最近几轮");
    await expect(block).toContainText("轮数达到 8 改用趋势检验");
    // 缺什么事实也写在页面上
    await expect(block).toContainText("核验结论");
    // 页面文字里没有英文内部标识
    const observeText = await page.locator("body").innerText();
    for (const word of ["converging", "undetermined", "step_window", "flip_threshold"]) {
      expect(observeText).not.toContain(word);
    }
    if (process.env.YUDAO_LOOPS_SHOT_DIR) {
      await page.screenshot({ path: `${process.env.YUDAO_LOOPS_SHOT_DIR}/observe-loops.png`, fullPage: true });
    }
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
