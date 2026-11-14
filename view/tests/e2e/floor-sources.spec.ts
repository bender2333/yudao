// 来源覆盖层与点开回链的端到端测试（工单 #1574、#1382）。
//
// 画面这一侧保留覆盖层「来源」的描边、缺来源虚线框与五种来源图例；
// 点画布上的六个事实元件（门牌、包裹、放行章、成果库箱子、轮次、已用时间）时，
// 画布高亮被点元件并交出带元件、事件位置与事项标识的回调，由壳打开 Yudao 页面对应位置的地址，
// 画布不叠来源卡片、不显示事件原文、不发取原始事件的网络请求（设计说明「回链的细内容在页面」）。

import { expect, test } from "@playwright/test";
import type { ProjectLoopResult } from "../../src/api/generated/types.gen.ts";
import { FACT_ELEMENTS, type FactElement } from "../../src/pixel/contract.ts";
import { sourceOverlay } from "../../src/translate/floor.ts";
import { recordingOf, responseOf, watchErrors, withViewServer } from "./fixtures.ts";
import { ViewPage } from "./room-screen-page.ts";

declare global {
  interface Window {
    __openedBacklinks?: { url: string; target: string; features: string }[];
  }
}

test("来源覆盖层：事实元素按来源描边，缺来源的元件标出来，图例数五种来源", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();

    // 录下的 project.loop（位置 120 的回放快照）→ 覆盖层的数据
    const recording = recordingOf(server.fixtures, "demo");
    const loop = responseOf(recording, "project.loop", { project_id: [recording.ids.project_id] }).data as ProjectLoopResult;
    const data = sourceOverlay(loop);
    // 事实元素：门牌、轮次与已用时间有来源；包裹与成果库的箱子在这个事项上缺来源
    expect(data.entries.map((entry) => entry.element).sort()).toEqual(["elapsed", "round", "sign"]);
    expect(data.missing.map((entry) => entry.element).sort()).toEqual(["box", "parcel"]);
    // 图例：五种来源各一行，计数是画面上有几个事实元素（录下的 refs：用户两条、确定规则一条）
    expect(data.legend.map((row) => row.source)).toEqual(["rule", "host_measurement", "user", "role_statement", "decision_model"]);
    expect(data.legend.map((row) => row.count)).toEqual([1, 0, 2, 0, 0]);

    await view.setOverlay("sources", data);
    const overlay = await view.floorOverlay();
    expect(overlay.id).toBe("sources");
    expect((overlay.data as { entries: unknown[] }).entries).toHaveLength(3);

    // 画布上每个事实元素的位置都在画面里；缺来源的包裹画出了一个虚线框的位置（drawn=false）
    const facts = await view.floorFacts();
    const of = (element: string) => facts.find((fact) => fact.element === element);
    expect(of("sign")?.drawn).toBe(true);
    expect(of("round")?.drawn).toBe(true);
    expect(of("elapsed")?.drawn).toBe(true);
    expect(of("parcel")?.drawn).toBe(false);
    for (const fact of facts) {
      expect(fact.x).toBeGreaterThanOrEqual(0);
      expect(fact.y).toBeGreaterThanOrEqual(0);
      expect(fact.x + fact.w).toBeLessThanOrEqual(640);
    }
    // 覆盖层画在画布上（不通过页面的文字）：画布仍按整数倍画出内容、控制台没有错误
    const canvas = await view.canvas("floor");
    expect(canvas.width % 640).toBe(0);
    expect(canvas.colors).toBeGreaterThan(8);

    if (process.env.YUDAO_SHOTS) await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/1574-floor-sources.png` });
    expect(errors).toEqual([]);
  });
});

// 守 R1（用户走完从楼层点选六个事实元件打开页面回链并看到高亮的完整路径，工单 #1382）
test("点开回链（R1）：点击门牌、包裹、章、箱子、轮次、已用时间六个事实元件，画布高亮被点元件并交出回链，不画来源卡片", async ({ page }) => {
  await page.addInitScript(() => {
    window.__openedBacklinks = [];
    window.open = ((url?: string | URL, target?: string, features?: string): Window | null => {
      window.__openedBacklinks?.push({
        url: String(url ?? ""),
        target: String(target ?? ""),
        features: String(features ?? ""),
      });
      return null;
    }) as typeof window.open;
  });

  await withViewServer({ recording: "demo" }, async (server) => {
    const errors = watchErrors(page);
    const projectId = server.recording.ids.project_id;
    const workItemId = server.recording.ids.work_item_id;
    const expectedPositions: Record<FactElement, number> = {
      sign: 2,
      round: 3,
      parcel: 49,
      stamp: 64,
      box: 67,
      elapsed: 288,
    };

    // 在本次装置加载的内存夹具快照上补齐六个事实元素来源与已采纳箱子，让六个事实元件同时出现在楼层画布上
    const loopIndex = server.recording.queries.findIndex((entry) => entry.name === "project.loop");
    expect(loopIndex).toBeGreaterThanOrEqual(0);
    const loopEntry = server.recording.queries[loopIndex];
    const clonedLoop = structuredClone(loopEntry.response.data) as ProjectLoopResult;
    clonedLoop.work_items[0].refs = {
      sign: { position: expectedPositions.sign, source: "user" },
      round: { position: expectedPositions.round, source: "rule" },
      parcel: { position: expectedPositions.parcel, source: "rule" },
      stamp: { position: expectedPositions.stamp, source: "role_statement" },
      box: { position: expectedPositions.box, source: "rule" },
      elapsed: { position: expectedPositions.elapsed, source: "host_measurement" },
    };
    clonedLoop.adoptions = [
      {
        adoption_id: "adp_1382",
        work_item_id: workItemId,
        run_id: clonedLoop.work_items[0].run_id,
        summary: "已采纳成果",
        files: [],
        check_names: [],
        known_risks: [],
        existing_defect_count: 0,
        code_tree_digest: "sha256:0000",
        adopted_at: "2026-10-30T10:00:00+08:00",
        event_id: "evt_1382",
        previous_adoption_id: null,
        onboarding_baseline: false,
        snapshot_source: null,
        snapshot_provenance: null,
      },
    ];
    server.recording.queries[loopIndex] = {
      ...loopEntry,
      response: { ...loopEntry.response, data: clonedLoop },
    };

    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();

    // 核对六个事实元件全部登记在命中矩形里且已画出，带各自的事件位置与事项标识
    const facts = await page.evaluate(() => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      return hooks.facts();
    });
    expect(facts.filter((fact) => fact.drawn).map((fact) => fact.element).sort()).toEqual([...FACT_ELEMENTS].sort());

    const canvasLocator = page.locator(".view-scene-floor canvas");
    await canvasLocator.scrollIntoViewIfNeeded();
    const box = await canvasLocator.boundingBox();
    expect(box).not.toBeNull();

    // 读取某个逻辑矩形外扩高亮框区域内的亮黄高亮像素数（PAL.yellow2 = #f7cb46 = rgb(247, 203, 70)）与中心纸面遮罩像素数
    const readCanvasRegion = async (rect: { x: number; y: number; w: number; h: number }) =>
      page.evaluate((r) => {
        const cv = document.querySelector(".view-scene-floor canvas") as HTMLCanvasElement | null;
        if (!cv) throw new Error("楼层没有画布");
        const ctx = cv.getContext("2d");
        if (!ctx) throw new Error("取不到 2D 上下文");
        const scale = cv.width / 640;
        const sx = Math.max(0, Math.floor((r.x - 3) * scale));
        const sy = Math.max(0, Math.floor((r.y - 3) * scale));
        const sw = Math.min(cv.width - sx, Math.ceil((r.w + 6) * scale));
        const sh = Math.min(cv.height - sy, Math.ceil((r.h + 6) * scale));
        const data = ctx.getImageData(sx, sy, sw, sh).data;
        let yellow = 0;
        for (let i = 0; i < data.length; i += 4) {
          if (data[i] === 247 && data[i + 1] === 203 && data[i + 2] === 70 && data[i + 3] > 200) yellow += 1;
        }
        // 旧来源卡片在逻辑坐标 (120, 34, 400, 224) 铺一整张纸色 PAL.paper = #f6eed8 = rgb(246, 238, 216)
        const cardData = ctx.getImageData(
          Math.floor(140 * scale),
          Math.floor(50 * scale),
          Math.floor(360 * scale),
          Math.floor(180 * scale),
        ).data;
        let paperPixels = 0;
        const totalCardPixels = cardData.length / 4;
        for (let i = 0; i < cardData.length; i += 4) {
          if (cardData[i] === 246 && cardData[i + 1] === 238 && cardData[i + 2] === 216) paperPixels += 1;
        }
        return { yellow, paperRatio: paperPixels / Math.max(1, totalCardPixels) };
      }, rect);

    const queryCountBeforeClicks = server.queries.length;

    // 逐个真实点击六个事实元件：门牌、包裹、放行章、成果库箱子、轮次、已用时间
    for (let i = 0; i < FACT_ELEMENTS.length; i++) {
      const element = FACT_ELEMENTS[i];
      const target = facts.find((fact) => fact.element === element && fact.drawn);
      expect(target, `缺少画出来的事实元件 ${element}`).toBeDefined();
      expect(target!.work_item_id).toBe(workItemId);
      expect(target!.position).toBe(expectedPositions[element]);

      const beforeRegion = await readCanvasRegion(target!);
      const clickX = ((target!.x + target!.w / 2) / 640) * box!.width;
      const clickY = ((target!.y + target!.h / 2) / 320) * box!.height;
      await canvasLocator.click({ position: { x: clickX, y: clickY } });

      // 1. 选中元件记入画面状态并在画布上画出外围高亮框像素
      const selected = await page.evaluate(() => window.__floorViewForTest?.selectedFact() ?? null);
      expect(selected).toEqual({ work_item_id: workItemId, element });
      const afterRegion = await readCanvasRegion(target!);
      expect(afterRegion.yellow).toBeGreaterThan(beforeRegion.yellow);

      // 2. 画布中间没有铺开来源卡片纸面，页面 DOM 里也不出现旧来源卡片或事件原文词条
      expect(afterRegion.paperRatio).toBeLessThan(0.25);
      const bodyText = await view.bodyText();
      expect(bodyText).not.toContain("在时间轴上查看");
      expect(bodyText).not.toContain("事件种类");

      // 3. 交出点开回链回调并由壳打开带位置与事项标识的页面路径
      const opened = await page.evaluate(() => window.__openedBacklinks ?? []);
      expect(opened).toHaveLength(i + 1);
      expect(opened[i]).toEqual({
        url: `/#/p/${projectId}/overview?at=${expectedPositions[element]}&w=${workItemId}`,
        target: "_blank",
        features: "noopener",
      });
      if (process.env.YUDAO_SHOTS && element === "sign") {
        await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/1382-floor-highlight.png` });
      }
    }

    // 4. 点选六个元件全程零额外查询（不请求 event.positions 或 event.detail）
    expect(server.queries.length).toBe(queryCountBeforeClicks);
    expect(server.queries.some((q) => q.name.startsWith("event."))).toBe(false);
    expect(errors).toEqual([]);
  });
});
