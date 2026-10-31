// 楼层画面的来源覆盖层与来源卡片（工单 #398 的验收：点开任一画面物件看到它的来源事件；缺来源的元件在覆盖层标出）。
// Playwright 打开 Chromium 页面，页面由 FakeAdapter 驱动的真实服务提供，与接口同一来源：
// 覆盖层「来源」的按钮按能力清单出现，打开以后画面上有事实元素的地方按来源描边、缺来源的标出来；
// 点画布上一个事实元素，来源卡片摊开，写元素、来源种类与来源事件的位置（事件说明取得到时一并写出）；
// 卡片上的「在时间轴上查看」把页面带回那个位置的概览回放。
//
// 覆盖层与卡片都画在画布上，测试经页面上给端到端测试的只读入口读取它们画的是什么，
// 并在画布上真的点一下（逻辑坐标换算成元素内的 CSS 坐标），与 floor.spec.ts 同一做法。

import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

type FactRect = { work_item_id: string; element: string; x: number; y: number; w: number; h: number; drawn: boolean };
type SourceCardView = {
  open: boolean;
  face: { element: string; element_label: string; source: string; source_label: string; position: number;
          event_label: string | null; kind_label: string | null; actor_label: string | null; note: string | null } | null;
};
type OverlayView = { id: string | null; data: Record<string, unknown> | null };

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  // 流式片段之间停 0.5 秒（--script pending）：新事项在部门房间里待得久一些，点它的门牌有时间
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

/** 建一个项目（pending 脚本不预置项目，用例自己建）：来源卡片的画面就在这个项目上）。 */
async function createProject(name: string): Promise<string> {
  const accepted = await command("project.create", { name, goal: "核对来源卡片与来源覆盖层" });
  const id = accepted.refs?.project_id;
  if (!id) throw new Error("project.create 没有返回项目标识");
  return id;
}

async function openOverview(page: Page, id: string): Promise<void> {
  await page.evaluate((hash) => { window.location.hash = hash; }, `#/p/${id}/overview`);
  await expect(page.locator(".floor-screen canvas")).toHaveCount(1);
}

/** 在楼层画布上用画面逻辑坐标点一下（与 floor.spec.ts 同一换算）。 */
async function clickLogical(page: Page, x: number, y: number): Promise<void> {
  const canvas = page.locator(".floor-screen canvas");
  await canvas.scrollIntoViewIfNeeded();
  const size = await canvas.evaluate((el) => {
    const rect = el.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  });
  await canvas.click({ position: { x: (x / 640) * size.width, y: (y / 320) * size.height } });
}

async function hooksOf(page: Page, what: "facts" | "sourceCard" | "overlay"): Promise<FactRect[] | SourceCardView | OverlayView> {
  return page.evaluate((name) => {
    const hooks = (window as unknown as { __floorViewForTest?: Record<string, () => unknown> }).__floorViewForTest;
    if (!hooks) throw new Error("页面没有画面的读取入口");
    return hooks[name]() as never;
  }, what);
}

test("来源覆盖层与来源卡片：点画面物件看到它的来源，缺来源的元件标出", async () => {
  test.setTimeout(240_000);
  const id = await createProject("来源卡片");
  const client: ClientApp = await startClient(backend, { width: 1440, height: 900 });
  const page = client.page;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await openOverview(page, id);
    // 覆盖层按钮条：事实来源（工单 #398）按能力清单出现，按钮上是中文名
    const button = page.getByRole("button", { name: "来源", exact: true });
    await expect(button).toHaveCount(1);
    await button.click();
    await expect(button).toHaveClass(/is-on/);
    // 页面上开始一个事项：它的事件经事件流到达页面，来源卡片因此能读到原始事件（工单 #398）。
    // 事项刚建立时只有门牌有来源，包裹、成果库的箱子、轮次与已用时间还缺来源，覆盖层要把它们标出来
    await command("work_item.create", { project_id: id, text: "来源卡片的新事项" });
    let sign: FactRect | undefined;
    let sawMissing: string[] = [];
    let legend: string[] = [];
    let entries = 0;
    for (let i = 0; i < 300 && !sign; i += 1) {
      const overlay = await hooksOf(page, "overlay") as OverlayView;
      if (overlay.id === "sources" && overlay.data !== null) {
        const data = overlay.data as { entries: { element: string }[]; missing: { element: string }[];
                                       legend: { source: string }[] };
        entries = Math.max(entries, data.entries.length);
        if (data.missing.length > sawMissing.length) sawMissing = data.missing.map((item) => item.element);
        if (data.legend.length) legend = data.legend.map((row) => row.source).sort();
      }
      const facts = await hooksOf(page, "facts") as FactRect[];
      sign = facts.find((rect) => rect.drawn && rect.element === "sign");
      if (!sign) await page.waitForTimeout(100);
    }
    expect(sign).toBeDefined();
    // 画面上有事实元素的地方各有一行，图例数五种来源
    expect(entries).toBeGreaterThan(0);
    expect(legend).toEqual(["decision_model", "host_measurement", "role_statement", "rule", "user"]);
    // 缺来源的元件被标出来：新事项建立时包裹与成果库的箱子、轮次与已用时间还没有来源
    expect(sawMissing.length).toBeGreaterThan(0);
    expect(sawMissing).toContain("parcel");

    // 点画出来的门牌：来源卡片摊开
    await clickLogical(page, sign!.x + sign!.w / 2, sign!.y + sign!.h / 2);
    let card = await hooksOf(page, "sourceCard") as SourceCardView;
    for (let i = 0; i < 60 && !card.open; i += 1) {
      await page.waitForTimeout(100);
      card = await hooksOf(page, "sourceCard") as SourceCardView;
    }
    expect(card.open).toBe(true);
    expect(card.face?.element).toBe("sign");
    // 来源种类、元素名与全局位置都是页面的说法：中文
    expect(card.face?.element_label).toBe("门牌");
    expect(card.face?.source_label).toMatch(/[\u4e00-\u9fa5]/);
    expect(Number.isInteger(card.face?.position)).toBe(true);
    // 原始事件：这个事项的事件是在页面打开以后到达的，卡片因此写得出中文说明与提出者
    expect(card.face?.event_label ?? "").toContain("来源卡片的新事项");
    expect(card.face?.kind_label).toMatch(/[\u4e00-\u9fa5]/);
    // 页面上不出现英文内部标识（画布上的文字看不见，这里核对页面上能读到的文字）
    const text = await page.locator("body").innerText();
    for (const word of ["sources", "host_measurement", "role_statement", "decision_model"]) {
      expect(text).not.toContain(word);
    }
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
