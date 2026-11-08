// 部门房间的端到端测试（接替 #1418 删掉的 client/tests/e2e/room.spec.ts 里画面这一侧；工单 #1574）。
//
// 旧用例在真实服务上起事项，核对房间里的流式文字、交接与询问时小人说的话、部门页签切换与页面信息条。
// 画面这一侧现在只认画面合同：部门工作间的查询结果（录下的 department.workspace）翻成房间状态，
// 事件流只翻成动作与流式文字。这里核对房间画出来的状态、角色、物件与位置，以及换部门的场景切换；
// 流式文字需要模型输出片段，录下的夹具里没有片段，房间的流式文字与说话气泡由画面单元测试守着
// （view/tests/unit/pixel-room.test.ts、translate-room.test.ts）；页面信息条与部门页签是页面的事，不在画面里。

import { expect, test } from "@playwright/test";
import { watchErrors, withViewServer } from "./fixtures.ts";
import { ViewPage } from "./room-screen-page.ts";

test("房间：录下的工作间画出部门状态、角色与物件，换部门时画面属于新部门", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();

    // 产品房间：录下的工作间是运行结束以后的那一刻（状态已完成，角色未工作，桌上三个卷轴）
    await view.openRoom("product");
    await view.waitForCanvas("room");
    const product = await view.room();
    expect(product.channels.position).toBe(289);
    expect(product.channels.status).toEqual({ value: "done", text: "已完成" });
    expect(product.channels.roles).toEqual([{ id: "product-agent", kind: "agent", status: "idle" }]);
    expect(product.channels.objects).toMatchObject({ mailbox: 0, scrolls: 3, letters_waiting: 0 });
    expect(product.timeline.shown).toBe(289);
    expect(await view.bodyText()).toContain("产品");
    // 画布按整数倍画出内容
    const productCanvas = await view.canvas("room");
    expect(productCanvas.width % 480).toBe(0);
    expect(productCanvas.height % 240).toBe(0);
    expect(productCanvas.colors).toBeGreaterThan(8);
    expect(productCanvas.inkRatio).toBeGreaterThan(0.02);

    // 回楼层再进工程房间：画面重建，读数换成工程那一份录下的查询结果
    await view.backToFloor("Demo 项目");
    await view.waitForFloorState();
    await view.openRoom("engineering");
    await view.waitForCanvas("room");
    const engineering = await view.room();
    expect(engineering.channels.status).toEqual({ value: "done", text: "已完成" });
    expect(engineering.channels.roles).toEqual([{ id: "engineering-agent", kind: "agent", status: "idle" }]);
    expect(engineering.channels.objects).toMatchObject({ scrolls: 0 });
    expect(engineering.timeline.shown).toBe(289);
    expect(await view.bodyText()).toContain("工程");

    if (process.env.YUDAO_SHOTS) await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/1574-room-engineering.png` });
    expect(errors).toEqual([]);
  });
});

test("房间：项目还没有工作过时画未工作，角色来自录下的工作间", async ({ page }) => {
  await withViewServer({ recording: "kernel", events: "none" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();

    await view.openRoom("quality");
    await view.waitForCanvas("room");
    const room = await view.room();
    expect(room.channels.position).toBe(90);
    expect(room.channels.status).toEqual({ value: "idle", text: "未工作" });
    expect(room.channels.roles).toEqual([{ id: "quality-agent", kind: "agent", status: "idle" }]);
    expect(room.channels.objects.scrolls).toBe(0);

    if (process.env.YUDAO_SHOTS) await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/1574-room-idle.png` });
    expect(errors).toEqual([]);
  });
});
