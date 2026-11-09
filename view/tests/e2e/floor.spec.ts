// 楼层的端到端测试（接替 #1418 删掉的 client/tests/e2e/floor.spec.ts 里画面这一侧的用例；工单 #1574）。
//
// 画面打开 view/ 的构建结果，装置回放录下的 project.loop、decisions.list、run.asks 与事件流，不启动 Yudao。
// 原来读页面事实（覆盖层按钮条、展开的文字列表、时间轴 ?at= 回放、页面上的决定卡片）的断言分成两类：
//   - 画面这一侧：事项的状态与所在部门、询问链的查询、断线重连、决定板上的卡片、盖章、被拒绝的原因、减少动画；
//   - 页面这一侧（文字列表、覆盖层按钮条、时间轴回放）：留在页面的测试里，画面已经不再画它们。
// 流转覆盖层（旧文件里的两个用例）不在本单：画面这一侧没有把 project.flow 翻成分段的翻译层，见交付说明的逐条对照。

import { expect, test } from "@playwright/test";
import { responseOf, recordingOf, watchErrors, withViewServer } from "./fixtures.ts";
import { ViewPage } from "./room-screen-page.ts";

test("楼层：录下的项目画出事项，状态与所在部门来自 project.loop", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    expect(await view.bodyText()).not.toContain("动作图鉴");
    await view.clickFloor(0);
    await view.waitForFloorState();

    const state = await view.floorState();
    expect(state.items).toHaveLength(1);
    expect(state.items[0]).toEqual({
      id: "wi_8e740804ca1e45c4",
      status: "working",
      department: "quality",
    });
    // 上画面的状态来自位置 289 的快照：打开画面是 jump，不补播
    expect(await view.floorTimeline()).toMatchObject({ shown: 289, pending: 0 });
    expect(state.interrupted).toBe(false);
    // 楼层按当前事项那次运行读询问链（run_id 来自 project.loop）
    expect(server.queries.some((query) => query.name === "run.asks"
      && query.params?.run_id?.[0] === "run_ec54042741a24a78")).toBe(true);
    // 这一刻没有等待回答的决定请求：大厅板上是空的
    expect((await view.floorDecisions()).faces).toEqual([]);

    // 画布按整数倍画出内容
    const canvas = await view.canvas("floor");
    expect(canvas.width % 640).toBe(0);
    expect(canvas.height % 320).toBe(0);
    expect(canvas.colors).toBeGreaterThan(8);
    expect(canvas.inkRatio).toBeGreaterThan(0.02);

    if (process.env.YUDAO_SHOTS) await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/1574-floor.png` });
    expect(errors).toEqual([]);
  });
});

test("断线重连：画面回到查询给出的状态，不补播，控制台错误为零", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();
    const before = await view.floorState();
    expect(before.items[0]!.status).toBe("working");

    // 断开事件流：画面按退避重连，重新订阅（after 是读到的最大位置）
    server.dropStreams();
    await expect(page.locator('[aria-label="连接状态"]')).toContainText("连接中断", { timeout: 10_000 });
    await expect(page.locator('[aria-label="连接状态"]')).toContainText("已连接", { timeout: 15_000 });
    expect(server.streamOpens).toBeGreaterThanOrEqual(2);

    // 重新订阅以后画面仍按查询给出的状态画，没有把已经演过的动作补播出来
    const after = await view.floorState();
    expect(after.items).toEqual(before.items);
    expect(await view.floorTimeline()).toMatchObject({ shown: 289, pending: 0 });
    expect(errors).toEqual([]);
  });
});

test("决定板：录下的决定请求打开卡片回答，命令带决定的版本发出，盖完章收起", async ({ page }) => {
  await withViewServer({ recording: "kernel", events: "none" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();

    const faces = (await view.floorDecisions()).faces;
    expect(faces).toHaveLength(1);
    expect(faces[0]!.kind).toBe("kernel_modification");
    expect(faces[0]!.version).toBe(1);
    expect(faces[0]!.title.length).toBeGreaterThan(0);

    // 打开决定卡片，点「批准采纳」：画面经壳发回答决定的命令
    await view.openCard(faces[0]!.id);
    await view.answer("approve");
    await expect.poll(() => server.commands.length).toBe(1);
    const command = server.commands[0]!;
    expect(command.name).toBe("decision.answer");
    expect(command.body).toMatchObject({
      decision_id: faces[0]!.id,
      option: "approve",
      base_version: 1,
    });
    expect(typeof command.body?.command_id).toBe("string");
    // 受理以后纸上盖章「已回答：批准采纳」，1.2 秒以后收起
    const stamped = await view.floorDecisions();
    expect(stamped.card.stamp?.text).toBe("已回答：批准采纳");
    await expect.poll(async () => (await view.floorDecisions()).card.openId).toBeNull();

    expect(errors).toEqual([]);
  });
});

test("决定被拒绝时：卡片显示原因并留着让人再试", async ({ page }) => {
  await withViewServer({ recording: "kernel", events: "none" }, async (server) => {
    server.commandReply = () => ({
      status: 409,
      body: { reason: "stale_base", message: "决定请求已经回答，不能再次回答" },
    });
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();

    const id = (await view.floorDecisions()).faces[0]!.id;
    await view.openCard(id);
    await view.answer("approve");
    await expect.poll(() => server.commands.length).toBe(1);
    const after = await view.floorDecisions();
    expect(after.card.openId).toBe(id);
    expect(after.card.message).toBe("决定请求已经回答，不能再次回答");
    expect(after.card.stamp).toBeNull();

    expect(errors).toEqual([]);
  });
});

test("系统设置为减少动画时，楼层照常画出查询给出的内容", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();

    expect((await view.floorState()).reduced).toBe(true);
    expect((await view.floorState()).items[0]!.status).toBe("working");
    const canvas = await view.canvas("floor");
    expect(canvas.inkRatio).toBeGreaterThan(0.02);
    expect(errors).toEqual([]);
  });
});

test("楼层只读它要用的四项查询，录下的响应都对得上（没有多余的请求）", async ({ page }) => {
  await withViewServer({ recording: "demo" }, async (server) => {
    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    await view.clickFloor(0);
    await view.waitForFloorState();
    const names = new Set(server.queries.map((query) => query.name));
    expect([...names].sort()).toEqual(["decisions.list", "project.loop", "projects.list", "run.asks"]);
    // 录下的应答都找得到（找不到时装置回答 404，画面上的状态就不会出现）
    for (const query of server.queries) {
      expect(() => responseOf(recordingOf(server.fixtures, "demo"), query.name, query.params)).not.toThrow();
    }
    expect(errors).toEqual([]);
  });
});
