// 来源覆盖层的端到端测试（接替 #1418 删掉的 client/tests/e2e/floor-sources.spec.ts；工单 #1574）。
//
// 旧用例在真实服务上点「来源」按钮、在画布上点门牌打开来源卡片。画面这一侧现在只保留覆盖层的画法：
// 事实元素按来源描边、缺来源的元件标出来、图例数五种来源；点开事实元素的回链改由壳打开 Yudao 页面
// （画面不画来源卡片，设计说明「回链的细内容在页面」）。覆盖层的数据由画面的翻译层从录下的 project.loop
// 翻出来（sourceOverlay），经画面自己的测试钩子交给画布；不启动 Yudao。

import { expect, test } from "@playwright/test";
import type { ProjectLoopResult } from "../../src/api/generated/types.gen.ts";
import { sourceOverlay } from "../../src/translate/floor.ts";
import { recordingOf, responseOf, watchErrors, withViewServer } from "./fixtures.ts";
import { ViewPage } from "./room-screen-page.ts";

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
