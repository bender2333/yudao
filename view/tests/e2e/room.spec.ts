// 部门房间的端到端测试（接替 #1418 删掉的 client/tests/e2e/room.spec.ts 里画面这一侧；工单 #1574）。
//
// 旧用例在真实服务上起事项，核对房间里的流式文字、交接与询问时小人说的话、部门页签切换与页面信息条。
// 画面这一侧现在只认画面合同：部门工作间的查询结果（录下的 department.workspace）翻成房间状态，
// 事件流只翻成动作与流式文字。这里核对房间画出来的状态、角色、物件与位置，以及换部门的场景切换；
// 流式文字需要模型输出片段，录下的夹具里没有片段，房间的流式文字与说话气泡由画面单元测试守着
// （view/tests/unit/pixel-room.test.ts、translate-room.test.ts）；页面信息条与部门页签是页面的事，不在画面里。

import { expect, test } from "@playwright/test";
import { waitFor, watchErrors, withViewServer } from "./fixtures.ts";
import { ViewPage } from "./room-screen-page.ts";

/** 创建一个一次性门控信号，用于控制异步查询何时放行（无固定时长等待）。 */
function createGate(): { promise: Promise<void>; open: () => void } {
  let open = (): void => {};
  const promise = new Promise<void>((resolve) => {
    open = resolve;
  });
  return { promise, open };
}

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
    expect(product.channels.department).toBe("product");
    expect(product.channels.label).toBe("产品");
    expect(product.channels.position).toBe(289);
    expect(product.channels.status).toEqual({ value: "done", text: "已完成" });
    expect(product.channels.roles).toEqual([{ id: "product-agent", kind: "agent", status: "idle" }]);
    expect(product.channels.objects).toMatchObject({ mailbox: 0, scrolls: 3, letters_waiting: 0 });
    expect(product.timeline.shown).toBe(289);
    expect(product.timeline.pending).toBe(0);
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
    expect(engineering.channels.department).toBe("engineering");
    expect(engineering.channels.label).toBe("工程");
    expect(engineering.channels.position).toBe(289);
    expect(engineering.channels.status).toEqual({ value: "done", text: "已完成" });
    expect(engineering.channels.roles).toEqual([{ id: "engineering-agent", kind: "agent", status: "idle" }]);
    expect(engineering.channels.objects).toMatchObject({ scrolls: 0 });
    expect(engineering.timeline.shown).toBe(289);
    expect(engineering.timeline.pending).toBe(0);
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
    expect(room.channels.department).toBe("quality");
    expect(room.channels.label).toBe("质检");
    expect(room.channels.verifier).toBe(true);
    expect(room.channels.position).toBe(90);
    expect(room.channels.status).toEqual({ value: "idle", text: "未工作" });
    expect(room.channels.roles).toEqual([{ id: "quality-agent", kind: "agent", status: "idle" }]);
    expect(room.channels.objects.scrolls).toBe(0);
    expect(room.timeline.shown).toBe(90);
    expect(room.timeline.pending).toBe(0);

    if (process.env.YUDAO_SHOTS) await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/1574-room-idle.png` });
    expect(errors).toEqual([]);
  });
});

test("房间：openRoom 等待工作间初始快照到达并完成状态渲染后才返回", async ({ page }) => {
  await withViewServer({ recording: "demo", events: "none" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();

    // 门控首次进入产品房间的工作间查询：测试钩子与画布已挂载时，openRoom 仍须等待工作间快照返回并上画面
    const productRequested = createGate();
    const releaseProduct = createGate();
    const routePattern = "**/api/queries/department.workspace*";
    await page.route(routePattern, async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("department") === "product") {
        productRequested.open();
        await releaseProduct.promise;
      }
      await route.continue();
    });

    let productOpened = false;
    const openingProduct = view.openRoom("product").then(() => {
      productOpened = true;
    });

    await productRequested.promise;
    await waitFor(
      () => page.evaluate(() => Boolean(window.__roomViewForTest)),
      "产品房间测试钩子先行挂载",
    );
    await view.waitForCanvas("room");
    expect(productOpened).toBe(false);

    releaseProduct.open();
    await openingProduct;
    await page.unroute(routePattern);

    const product = await view.room();
    expect(product.channels.department).toBe("product");
    expect(product.channels.position).toBe(289);
    expect(product.channels.status).toEqual({ value: "done", text: "已完成" });
    expect(product.channels.objects.scrolls).toBe(3);
    expect(product.timeline.shown).toBe(289);
    expect(product.timeline.pending).toBe(0);
    const productCanvas = await view.canvas("room");
    expect(productCanvas.colors).toBeGreaterThan(8);
    expect(productCanvas.inkRatio).toBeGreaterThan(0.02);

    // 换部门进入工程房间时同样等待新部门的工作间快照到达并完成状态渲染
    await view.backToFloor("Demo 项目");
    await view.waitForFloorState();

    const engineeringRequested = createGate();
    const releaseEngineering = createGate();
    await page.route(routePattern, async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("department") === "engineering") {
        engineeringRequested.open();
        await releaseEngineering.promise;
      }
      await route.continue();
    });

    let engineeringOpened = false;
    const openingEngineering = view.openRoom("engineering").then(() => {
      engineeringOpened = true;
    });

    await engineeringRequested.promise;
    await waitFor(
      () => page.evaluate(() => Boolean(window.__roomViewForTest)),
      "工程房间测试钩子先行挂载",
    );
    await view.waitForCanvas("room");
    expect(engineeringOpened).toBe(false);

    releaseEngineering.open();
    await openingEngineering;
    await page.unroute(routePattern);

    const engineering = await view.room();
    expect(engineering.channels.department).toBe("engineering");
    expect(engineering.channels.position).toBe(289);
    expect(engineering.channels.status).toEqual({ value: "done", text: "已完成" });
    expect(engineering.channels.objects.scrolls).toBe(0);
    expect(engineering.timeline.shown).toBe(289);
    expect(engineering.timeline.pending).toBe(0);
    const engineeringCanvas = await view.canvas("room");
    expect(engineeringCanvas.colors).toBeGreaterThan(8);
    expect(engineeringCanvas.inkRatio).toBeGreaterThan(0.02);
    expect(errors).toEqual([]);
  });
});
