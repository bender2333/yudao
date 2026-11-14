// 覆盖层「检验」的端到端测试（工单 #1420，画面与播放 docs/design/visualization.md「七种元件与对照表」「开环完成与放行」）。
//
// 守 docs/design/test-pyramid.md「测试按三环留」的 R3：
//   - 默认打开楼层时不请求 acceptance.coverage；
//   - 开启覆盖层「检验」（coverage）时经壳按聚焦事项的 run_id 请求 acceptance.coverage；
//   - 楼层画布把检验覆盖比例、开环条件条数、逐条验收条件的检验方式与结果及四种计数图例全部画出，
//     各块牌子落在信息条下方且互不重叠，文字使用「开环条件 / 开环 N 条」。

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import type { AcceptanceCoverageResult } from "../../src/api/generated/types.gen.ts";
import { watchErrors, withViewServer } from "./fixtures.ts";
import { ViewPage } from "./room-screen-page.ts";

const here = dirname(fileURLToPath(import.meta.url));
const COVERAGE_FIXTURE = JSON.parse(
  readFileSync(join(here, "..", "fixtures", "e2e", "acceptance-coverage.json"), "utf8"),
) as { response: { position: number; data: AcceptanceCoverageResult } };

test("覆盖层「检验」：开启后按需读取 acceptance.coverage，画出覆盖比例、开环条件条数、逐条检验方式与结果及图例", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    server.recording.queries.push({
      name: "acceptance.coverage",
      params: { run_id: server.recording.ids.run_id },
      response: COVERAGE_FIXTURE.response,
    });

    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    expect(await view.bodyText()).not.toContain("缺口清单");
    await view.clickFloor(0);
    await view.waitForFloorState();

    // 默认打开楼层时不发 acceptance.coverage
    expect(server.queries.some((query) => query.name === "acceptance.coverage")).toBe(false);

    // 经壳开启覆盖层「检验」：按当前事项的运行标识拉取 acceptance.coverage 并把翻译后的数据交到画布
    await page.evaluate(() => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      hooks.selectOverlay("coverage");
    });

    await expect.poll(() => server.queries.some(
      (query) => query.name === "acceptance.coverage" && query.params.run_id?.[0] === "run_ec54042741a24a78",
    )).toBe(true);
    await expect.poll(async () => (await view.floorOverlay()).id).toBe("coverage");
    await expect.poll(async () => (await view.floorOverlayLabels()).length).toBe(11);

    const overlay = await view.floorOverlay();
    const forbiddenTerm = "开环" + "完成";
    expect(JSON.stringify(overlay)).not.toContain(forbiddenTerm);
    expect(await view.bodyText()).not.toContain(forbiddenTerm);

    const labels = await view.floorOverlayLabels();
    expect(labels.some((item) => item.key === "coverage:summary")).toBe(true);
    for (const row of COVERAGE_FIXTURE.response.data.criteria) {
      expect(labels.some((item) => item.key === `coverage:criterion:${row.criterion}`)).toBe(true);
    }
    for (const legendKey of ["passed", "failed", "unverified", "open"]) {
      expect(labels.some((item) => item.key === `coverage:legend:${legendKey}`)).toBe(true);
    }

    // 所有牌子都在画布内、位于顶部信息条（y=0..18）下方，且任意两块牌子互不重叠
    for (const rect of labels) {
      expect(rect.x).toBeGreaterThanOrEqual(0);
      expect(rect.y).toBeGreaterThanOrEqual(18);
      expect(rect.x + rect.w).toBeLessThanOrEqual(640);
      expect(rect.y + rect.h).toBeLessThanOrEqual(320);
    }
    for (let i = 0; i < labels.length; i += 1) {
      for (let j = i + 1; j < labels.length; j += 1) {
        const a = labels[i]!;
        const b = labels[j]!;
        const overlaps = a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
        expect(overlaps, `覆盖层牌子 ${a.key} 与 ${b.key} 发生重叠`).toBe(false);
      }
    }

    const canvas = await view.canvas("floor");
    expect(canvas.width % 640).toBe(0);
    expect(canvas.colors).toBeGreaterThan(8);

    if (process.env.YUDAO_SHOTS) {
      await page.locator(".view-scene-floor canvas").screenshot({
        path: `${process.env.YUDAO_SHOTS}/1420-floor-coverage.png`,
      });
    }
    expect(errors).toEqual([]);
  });
});
