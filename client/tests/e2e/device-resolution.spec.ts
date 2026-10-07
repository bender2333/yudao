// 三个上线画面的实际绘制（工单 #365 验收标准 1、3）：
// 楼层、部门房间、首页的楼三张画布按设备分辨率绘制——像素尺寸是逻辑尺寸的整数倍，CSS 尺寸铺满容器宽度，
// 采样是最近邻；画面上的文字按设备分辨率光栅化（微软雅黑，不是逻辑尺寸的小字再插值放大）。
//
// 这里在 Chromium 里读画布真实的像素内容，检查
//  1) 画布的像素尺寸是逻辑尺寸的整数倍，且 CSS 宽度铺满容器；
//  2) 画面不是空白（贴图与线条画出来了，配色不止一种）；
//  3) 文字边缘有连续的灰阶层次（按设备分辨率光栅化的字才有；6 逻辑像素的字插值放大后，
//     过渡色只有少数几档）。

import { expect, test, type Locator, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend } from "./fixtures";

let backend: Backend;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

type QueryEnvelope<T> = { data?: T; reason?: string; message?: string };

async function query<T>(name: string, params: Record<string, unknown> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) search.append(key, String(value));
  const qs = search.toString();
  const response = await fetch(`${backend.address}/api/queries/${name}${qs ? `?${qs}` : ""}`);
  const envelope = (await response.json()) as QueryEnvelope<T>;
  if (envelope.data === undefined) {
    throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data;
}

async function projectId(name: string): Promise<string> {
  const data = await query<{ projects: { project_id: string; name: string }[] }>("projects.list");
  const row = data.projects.find((p) => p.name === name);
  if (!row) throw new Error(`没有项目 ${name}`);
  return row.project_id;
}

/** 画布的实际像素内容：尺寸、采样方式、配色数、非背景占比与灰阶层次。 */
interface CanvasPixels {
  width: number;
  height: number;
  cssWidth: number;
  hostWidth: number;
  imageRendering: string;
  /** 画面里有多少种颜色（每种颜色粗略折成 15 级灰度桶）。 */
  colors: number;
  /** 画面里的非背景像素占比（0 到 1）：画面画出了内容。 */
  inkRatio: number;
  /** 中间灰阶有多少种亮度：按设备分辨率光栅化的文字边缘有连续的灰阶。 */
  midLevels: number;
}

async function readCanvas(locator: Locator): Promise<CanvasPixels> {
  return locator.evaluate((el) => {
    const c = el as HTMLCanvasElement;
    const ctx = c.getContext("2d");
    if (!ctx) throw new Error("画面画布没有 2D 上下文");
    const data = ctx.getImageData(0, 0, c.width, c.height).data;
    const colors = new Set<number>();
    const mid = new Set<number>();
    let ink = 0;
    for (let i = 0; i < data.length; i += 4) {
      colors.add(((data[i] >> 3) << 10) | ((data[i + 1] >> 3) << 5) | (data[i + 2] >> 3));
      const lum = (data[i] * 30 + data[i + 1] * 59 + data[i + 2] * 11) / 100;
      if (lum < 240) ink += 1;
      if (lum > 90 && lum < 210) mid.add(Math.round(lum));
    }
    const host = c.parentElement;
    return {
      width: c.width,
      height: c.height,
      cssWidth: Math.round(c.getBoundingClientRect().width * 100) / 100,
      hostWidth: host ? Math.round(host.getBoundingClientRect().width * 100) / 100 : 0,
      imageRendering: getComputedStyle(c).imageRendering,
      colors: colors.size,
      inkRatio: ink / (data.length / 4),
      midLevels: mid.size,
    };
  });
}

async function goto(page: Page, hash: string): Promise<void> {
  await page.evaluate((h) => { window.location.hash = h; }, hash);
}

/** 检查一张画布：整数倍、铺满容器、最近邻、画面有内容。 */
async function checkSurface(
  locator: Locator,
  logicalW: number,
  logicalH: number | null,
  description: string,
): Promise<CanvasPixels> {
  const pixels = await readCanvas(locator);
  expect(pixels.width % logicalW, `${description} 的画布宽不是逻辑宽 ${logicalW} 的整数倍：${pixels.width}`).toBe(0);
  if (logicalH !== null) {
    expect(pixels.height % logicalH, `${description} 的画布高不是逻辑高 ${logicalH} 的整数倍：${pixels.height}`).toBe(0);
  }
  expect(pixels.width / logicalW).toBeGreaterThanOrEqual(1);
  expect(Math.abs(pixels.cssWidth - pixels.hostWidth), `${description} 的画布没有铺满容器`).toBeLessThanOrEqual(2);
  expect(pixels.imageRendering).toBe("pixelated");
  expect(pixels.colors, `${description} 的画面只有 ${pixels.colors} 种颜色`).toBeGreaterThan(8);
  expect(pixels.inkRatio, `${description} 的画面几乎没有内容`).toBeGreaterThan(0.02);
  return pixels;
}

test("楼层、部门房间、首页的楼按设备分辨率绘制：整数倍、最近邻、文字有灰阶层次", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors: string[] = [];
  client.page.on("console", (m) => {
    if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) errors.push(m.text());
  });
  client.page.on("pageerror", (e) => errors.push(e.message));
  const page = client.page;
  try {
    const id = await projectId("示例项目");

    // 首页的楼：逻辑宽 640，高随层数变化
    const building = page.locator(".building-canvas canvas");
    await expect(building).toHaveCount(1);
    await checkSurface(building, 640, null, "楼");

    // 项目概览的楼层：640×320
    await goto(page, `#/p/${id}/overview`);
    const floor = page.locator(".floor-screen canvas");
    await expect(floor).toHaveCount(1);
    const floorPixels = await checkSurface(floor, 640, 320, "楼层");
    expect(floorPixels.midLevels, "楼层画面的文字没有灰阶层次").toBeGreaterThan(12);

    // 部门工作间的房间：480×240
    await goto(page, `#/p/${id}/dept/product`);
    const room = page.locator(".room-canvas canvas");
    await expect(room).toHaveCount(1);
    const roomPixels = await checkSurface(room, 480, 240, "部门房间");
    expect(roomPixels.midLevels, "部门房间画面的文字没有灰阶层次").toBeGreaterThan(12);

    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

for (const size of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  test(`三张画面在 ${size.width}×${size.height} 下画布宽度是逻辑宽的整数倍，控制台错误为零`, async () => {
    const client = await startClient(backend, size);
    const errors: string[] = [];
    client.page.on("console", (m) => {
      if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) errors.push(m.text());
    });
    client.page.on("pageerror", (e) => errors.push(e.message));
    const page = client.page;
    try {
      const id = await projectId("示例项目");
      const building = page.locator(".building-canvas canvas");
      await expect(building).toHaveCount(1);
      const buildingWidth = await building.evaluate((el) => (el as HTMLCanvasElement).width);
      expect(buildingWidth % 640).toBe(0);
      expect(buildingWidth).toBeGreaterThan(640);

      await goto(page, `#/p/${id}/overview`);
      const floorWidth = await page.locator(".floor-screen canvas").evaluate((el) => (el as HTMLCanvasElement).width);
      expect(floorWidth % 640).toBe(0);
      expect(floorWidth).toBeGreaterThan(640);

      await goto(page, `#/p/${id}/dept/product`);
      const room = page.locator(".room-canvas canvas");
      await expect(room).toHaveCount(1);
      const roomWidth = await room.evaluate((el) => (el as HTMLCanvasElement).width);
      expect(roomWidth % 480).toBe(0);
      expect(roomWidth).toBeGreaterThan(480);

      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });
}