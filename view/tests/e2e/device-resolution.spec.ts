// 整数倍缩放的端到端测试（接替 #1418 删掉的 client/tests/e2e/device-resolution.spec.ts；工单 #1574）。
//
// 画面按设备分辨率绘制：画布的像素尺寸是逻辑尺寸的整数倍，CSS 尺寸铺满容器宽度，采样是最近邻，
// 画面上的文字按设备分辨率光栅化（灰阶层次不止几档）。三种画面（楼 640×？、楼层 640×320、
// 房间 480×240）在 1440×900 与 1920×1080 两种视口下各量一次，控制台错误为零。
// 页面不出现横向滚动条（工单 #365、#1228 的验收）。旧用例在页面上按 hash 切场景；画面没有地址路由，
// 这里走真实的场景切换：点楼的一层，再从楼层进房间。

import { expect, test } from "@playwright/test";
import { readCanvas, watchErrors, withViewServer } from "./fixtures.ts";
import { ViewPage } from "./room-screen-page.ts";

/** 一张画布：整数倍、铺满容器、最近邻、画面有内容。 */
async function checkSurface(view: ViewPage, scene: "building" | "floor" | "room",
                            logicalW: number, logicalH: number | null, description: string): Promise<void> {
  const canvas = await view.canvas(scene);
  expect(canvas.width % logicalW, `${description}的画布宽不是逻辑宽 ${logicalW} 的整数倍：${canvas.width}`).toBe(0);
  if (logicalH !== null) {
    expect(canvas.height % logicalH, `${description}的画布高不是逻辑高 ${logicalH} 的整数倍：${canvas.height}`).toBe(0);
  }
  expect(canvas.width / logicalW).toBeGreaterThanOrEqual(1);
  expect(Math.abs(canvas.cssWidth - canvas.hostWidth),
    `${description}的画布没有铺满容器：画布 ${canvas.cssWidth}，容器 ${canvas.hostWidth}`).toBeLessThanOrEqual(2);
  expect(canvas.imageRendering).toBe("pixelated");
  expect(canvas.colors, `${description}的画面只有 ${canvas.colors} 种颜色`).toBeGreaterThan(8);
  expect(canvas.inkRatio, `${description}的画面几乎没有内容`).toBeGreaterThan(0.02);
}

for (const size of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  test(`楼、楼层与房间在 ${size.width}×${size.height} 下按整数倍缩放，控制台错误为零`, async ({ page }) => {
    await withViewServer({ recording: "demo" }, async (server) => {
      const errors = watchErrors(page);
      const view = new ViewPage(page, server);
      await view.open(size);
      await view.waitForCanvas("building");

      // 楼：逻辑宽 640，高随层数变化
      await checkSurface(view, "building", 640, null, "楼");
      const building = await readCanvas(page, ".view-scene-building canvas");
      expect(building.width).toBeGreaterThan(640);
      expect(building.midLevels, "楼画面的文字没有灰阶层次").toBeGreaterThan(12);

      // 楼层：640×320
      await view.clickFloor(0);
      await view.waitForCanvas("floor");
      await view.waitForFloorState();
      await checkSurface(view, "floor", 640, 320, "楼层");
      const floor = await readCanvas(page, ".view-scene-floor canvas");
      expect(floor.midLevels, "楼层画面的文字没有灰阶层次").toBeGreaterThan(12);

      // 部门房间：480×240
      await view.openRoom("product");
      await view.waitForCanvas("room");
      await checkSurface(view, "room", 480, 240, "部门房间");
      const room = await readCanvas(page, ".view-scene-room canvas");
      expect(room.midLevels, "部门房间画面的文字没有灰阶层次").toBeGreaterThan(12);

      // 页面没有横向滚动条
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);

      if (process.env.YUDAO_SHOTS) {
        await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/1574-room-${size.width}x${size.height}.png` });
      }
      expect(errors).toEqual([]);
    });
  });
}

// 800×600 的窄窗：房间画布不超过容器宽，页面没有横向滚动条（工单 #1228 的验收）
test("800×600 下房间画布不超过容器宽，页面没有横向滚动条", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 800, height: 600 });
    await view.clickFloor(0);
    await view.waitForFloorState();
    await view.openRoom("product");
    await view.waitForCanvas("room");
    const room = await readCanvas(page, ".view-scene-room canvas");
    expect(room.width % 480).toBe(0);
    expect(room.cssWidth).toBeLessThanOrEqual(room.hostWidth + 2);
    const read = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(read.scrollWidth).toBeLessThanOrEqual(read.clientWidth);
    expect(errors).toEqual([]);
  });
});

