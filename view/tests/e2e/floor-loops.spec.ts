// 覆盖层「循环」的端到端测试（接替 #1418 删掉的 client/tests/e2e/floor-loops.spec.ts 里画面这一侧；工单 #1574）。
//
// 旧用例在真实服务上开一个事项、点覆盖层「循环」，核对画布上写的 run 层、各部门这次激活与步骤循环，
// 以及观测页的「循环」区块。画面这一侧现在只保留覆盖层的画法：run 层写在信息条上、每个部门写激活与步骤、
// 右上角写五种状态与「不判定」的图例。数据来自录下的 run.loops（view/tests/fixtures/e2e/run-loops.json，
// 录自 harness.demo），经画面的翻译层翻好交给画布；不启动 Yudao。观测页的「循环」区块属于页面，不在画面里。

import { expect, test } from "@playwright/test";
import type { RunLoopsResult } from "../../src/api/generated/types.gen.ts";
import { loopStateLabel, loopsOverlay } from "../../src/translate/floor.ts";
import { loadRunLoops, watchErrors, withViewServer } from "./fixtures.ts";
import { ViewPage } from "./room-screen-page.ts";

test("覆盖层「循环」：run 层的收敛状态、各部门的激活与步骤循环、五种状态的图例来自 run.loops", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();

    // 录下的 run.loops（harness.demo 跑完一轮以后的一次运行）→ 覆盖层的数据
    const loops = loadRunLoops() as RunLoopsResult;
    const data = loopsOverlay(loops);
    expect(data.bar.state).toBe("stalled");
    expect(data.bar.text).toMatch(/^运行 · /);
    // run.loops 有几条激活，画面上就有几个房间写「第 N 次激活」与步骤循环
    expect(data.rooms).toHaveLength(loops.activations.length);
    expect(data.rooms.length).toBeGreaterThan(0);
    expect(data.rooms[0]!.text).toMatch(/^第 \d+ 次激活 · /);
    expect(data.rooms[0]!.step_text).toMatch(/^步骤 \d+ 步 · /);
    // 图例写五种状态与「不判定」，文字是中文
    expect(data.legend.map((row) => row.label)).toEqual(["收敛中", "停滞", "震荡", "漂移", "达到边界", "不判定"]);
    expect(data.legend.map((row) => loopStateLabel(row.state))).toEqual(data.legend.map((row) => row.label));

    await view.setOverlay("loops", data);
    const overlay = await view.floorOverlay();
    expect(overlay.id).toBe("loops");

    // 画面真的把标签画出来了：run 层一块、每个部门两块（激活与步骤）、图例六块，都落在画面里
    const labels = await view.floorOverlayLabels();
    expect(labels.some((label) => label.key === "loops:run")).toBe(true);
    for (const room of data.rooms) {
      expect(labels.some((label) => label.key === room.department)).toBe(true);
      expect(labels.some((label) => label.key === `${room.department}:steps`)).toBe(true);
    }
    for (const row of data.legend) {
      expect(labels.some((label) => label.key === `loops:legend:${row.state}`)).toBe(true);
    }
    for (const label of labels) {
      // 牌子的锚点在文字基线：允许画法按 6 像素的字高向上长出一点（run 层写在信息条 y=10 处）
      expect(label.x).toBeGreaterThanOrEqual(0);
      expect(label.y).toBeGreaterThanOrEqual(-8);
      expect(label.x + label.w).toBeLessThanOrEqual(640);
      expect(label.y + label.h).toBeLessThanOrEqual(330);
    }
    // 画布仍按整数倍画出内容、控制台没有错误
    const canvas = await view.canvas("floor");
    expect(canvas.width % 640).toBe(0);
    expect(canvas.colors).toBeGreaterThan(8);

    if (process.env.YUDAO_SHOTS) await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/1574-floor-loops.png` });
    expect(errors).toEqual([]);
  });
});
