// 楼的端到端测试（接替 #1418 删掉的 client/tests/e2e/building.spec.ts；工单 #1574）。
//
// 画面自己打开 view/ 的构建结果，装置按路径回放录下的接口响应与事件流（fixtures.ts），不启动 Yudao。
// 原来读页面文字列表（project.loop）的断言改成读画面自己的钩子（__buildingViewForTest：每层的状态灯、
// 亮灯的房间、小旗、决定计数与时间线）；原来靠服务端命令（置顶、停止事项）改变状态的场景不再适用，
// 排序与停止的对应表由画面的单元测试守着（交付说明逐条列了接替关系）。

import { expect, test } from "@playwright/test";
import { watchErrors, withViewServer } from "./fixtures.ts";
import { ViewPage } from "./room-screen-page.ts";

test("楼：录下的项目与事项画出这一层，状态灯与亮灯的房间来自 project.loop", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });

    const read = await view.building();
    expect(read.floors).toHaveLength(1);
    const floor = read.floors[0]!;
    // 项目名与标识来自录下的 projects.list
    expect(floor.name).toBe("Demo 项目");
    expect(floor.project_id).toBe("proj_9a0b137677f34a69");
    // 事项在质量部门进行中、工程与质量同时工作（录下的 project.loop 位置 120）：这一层是「运行中」，
    // 工程与质量的房间亮灯，产品在等待工作
    expect(floor.status).toBe("working");
    expect(floor.lit).toEqual({ product: false, engineering: true, quality: true, operations: false });
    // 门口的小旗是事项所在的部门（质量）
    expect(floor.flags.map((flag) => [flag.department, flag.work_item_id]))
      .toEqual([["quality", "wi_8e740804ca1e45c4"]]);
    expect(floor.decisions).toBe(0);
    expect(floor.valve_closed).toBe(false);
    // 打开画面直接显示查询给出的位置，不补播
    expect(read.timeline.shown).toBe(120);

    // 画布真的画出了内容：配色不止一种、非背景像素占一定比例
    const canvas = await view.canvas("building");
    expect(canvas.width % 640).toBe(0);
    expect(canvas.width).toBeGreaterThan(640);
    expect(canvas.colors).toBeGreaterThan(8);
    expect(canvas.inkRatio).toBeGreaterThan(0.02);

    // 截图只在本机留证据时写（环境变量 YUDAO_SHOTS 给出目录）
    if (process.env.YUDAO_SHOTS) await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/1574-building.png` });
    expect(errors).toEqual([]);
  });
});

test("点一层楼进入项目的楼层，面包屑回到楼；楼层的读数属于那个项目", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });

    await view.clickFloor(0);
    await view.waitForCanvas("floor");
    await view.waitForFloorState();
    // 楼层从录下的 project.loop 画出同一个事项
    const state = await view.floorState();
    expect(state.items).toHaveLength(1);
    expect(state.items[0]!.id).toBe("wi_8e740804ca1e45c4");
    expect(state.items[0]!.status).toBe("working");
    expect(state.items[0]!.department).toBe("quality");
    // 面包屑写项目名：回到楼以后楼照样按录下的查询画
    await expect(page.locator('nav[aria-label="场景"] button', { hasText: "Demo 项目" })).toHaveCount(1);
    await view.backToBuilding();
    const building = await view.building();
    expect(building.floors).toHaveLength(1);

    if (process.env.YUDAO_SHOTS) await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/1574-floor-from-building.png` });
    expect(errors).toEqual([]);
  });
});

test("打开楼与重新打开页面：直接显示查询给出的最新状态，不补播", async ({ page }) => {
  // kernel 项目没有录下的事件流：打开画面时的状态就是查询给出的那一刻，时间线没有排着的动作
  await withViewServer({ recording: "kernel", events: "none" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    const opened = await view.building();
    expect(opened.floors[0]!.project_id).toBe("proj_6861a95d0e1c4037");
    expect(opened.floors[0]!.name).toBe("内核改动");
    expect(opened.timeline.shown).toBe(90);
    expect(opened.timeline.pending).toBe(0);
    expect(opened.timeline.playing).toEqual([]);

    await page.reload();
    await view.open({ width: 1440, height: 900 });
    const reopened = await view.building();
    expect(reopened.timeline.shown).toBe(90);
    expect(reopened.timeline.pending).toBe(0);

    // 正式入口里没有图鉴（图鉴只在开发构建的 #/gallery）
    expect(await view.bodyText()).not.toContain("动作图鉴");
    expect(errors).toEqual([]);
  });
});
