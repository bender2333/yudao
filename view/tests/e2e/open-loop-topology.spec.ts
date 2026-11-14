// 「工程」单职能直做开环完成、同层两份定义并集与未声明角色通用外观缺口清单的端到端测试（工单 #1385）。
//
// 守 docs/design/test-pyramid.md「测试按三环留」的 R1（用户从楼进入单屋楼层、点击出口托盘虚线开环完成章打开页面回链、
// 进入直做房间查看出口托盘与虚线章）与 R3（同层并存「产品 · 工程 · 质检」与「工程」两份定义时各自盖实心放行章与虚线开环完成章，
// 未在场景声明登记专属外观的角色在壳顶栏缺口清单写明角色标识并以通用外观在楼、楼层与房间正常显示）。

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { clickLogical, watchErrors, withViewServer, type RecordedQuery } from "./fixtures.ts";
import { ViewPage } from "./room-screen-page.ts";

declare global {
  interface Window {
    __openedOpenLoopBacklinks?: string[];
  }
}

interface TopologyFixtureFile {
  scenarios: Record<
    "solo_open_loop" | "union_and_generic",
    {
      ids: { project_id: string; work_item_id: string; run_id: string };
      queries: RecordedQuery[];
    }
  >;
}

const here = dirname(fileURLToPath(import.meta.url));
const TOPOLOGY_FIXTURES = JSON.parse(
  readFileSync(join(here, "..", "fixtures", "e2e", "open-loop-topology.json"), "utf8"),
) as TopologyFixtureFile;

test("单屋开环完成：「工程」只有一个职能时楼层只画一间屋设出口托盘，虚线章可点击回链，房间与成果库箱子均保留虚线章", async ({ page }) => {
  await page.addInitScript(() => {
    window.__openedOpenLoopBacklinks = [];
    window.open = ((url?: string | URL): Window | null => {
      window.__openedOpenLoopBacklinks?.push(String(url ?? ""));
      return null;
    }) as typeof window.open;
  });

  await withViewServer({ recording: "demo", events: "none" }, async (server) => {
    const scenario = TOPOLOGY_FIXTURES.scenarios.solo_open_loop;
    Object.assign(server.recording.ids, scenario.ids);
    server.recording.queries.splice(0, server.recording.queries.length, ...structuredClone(scenario.queries));

    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });
    expect(await view.bodyText()).not.toContain("缺口清单");

    // 楼场景：单职能项目只画「工程」一格，结束章种类为 open_loop，不含实心 release 章
    const buildingFloors = await page.evaluate(() => window.__buildingViewForTest!.floors());
    expect(buildingFloors).toHaveLength(1);
    expect(buildingFloors[0]!.rooms).toEqual([{ id: "engineering", label: "工程", lit: false }]);
    expect(buildingFloors[0]!.stamps).toEqual([
      { work_item_id: "wi_open_solo", kind: "open_loop", outsourced: false },
    ]);

    // 点击进入单屋楼层：大厅与成果库之间只有「工程」一间屋，设出口托盘、无盖章台，出口托盘与成果库箱子均盖虚线章
    await view.clickFloor(0);
    await view.waitForFloorState();
    const floorChannels = await page.evaluate(() => window.__floorViewForTest!.channels());
    expect(Object.keys(floorChannels.rooms)).toEqual(["engineering"]);
    expect(floorChannels.rooms.engineering).toMatchObject({
      label: "工程",
      verifier: false,
      exit_tray: true,
    });
    expect(floorChannels.links).toEqual({
      handoffs: ["engineering>library", "hall>engineering"],
      tubes: [],
      returns: [],
    });
    expect(floorChannels.stamps).toEqual([
      { work_item_id: "wi_open_solo", room: "engineering", kind: "open_loop", outsourced: false, text: "开环完成" },
    ]);
    expect(floorChannels.shelf.boxes).toEqual([
      { work_item_id: "wi_open_solo", stamp_kind: "open_loop", outsourced: false },
    ]);

    // 真实点击画布上的出口托盘虚线章：画布高亮该章并打开指向事件位置 18 的页面回链
    const facts = await view.floorFacts();
    const stampFact = facts.find((f) => f.element === "stamp" && f.work_item_id === "wi_open_solo");
    expect(stampFact?.drawn).toBe(true);
    const size = await page.evaluate(() => window.__floorViewForTest!.size());
    await clickLogical(
      page,
      ".view-scene-floor canvas",
      size.W,
      size.H,
      stampFact!.x + stampFact!.w / 2,
      stampFact!.y + stampFact!.h / 2,
    );
    await expect.poll(() => page.evaluate(() => window.__openedOpenLoopBacklinks?.length ?? 0)).toBe(1);
    const openedHref = await page.evaluate(() => window.__openedOpenLoopBacklinks![0]!);
    expect(openedHref).toBe("/#/p/proj_open_solo/overview?at=18&w=wi_open_solo");
    const selected = await page.evaluate(() => window.__floorViewForTest!.selectedFact());
    expect(selected).toEqual({ work_item_id: "wi_open_solo", element: "stamp" });
    if (process.env.YUDAO_SHOTS) {
      await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/01-solo-open-loop-floor.png` });
    }

    // 进入「工程」房间：设有出口托盘、无检验台，结束章为虚线的「开环完成」
    await view.openRoom("engineering");
    await view.waitForCanvas("room");
    const room = await view.room();
    expect(room.channels).toMatchObject({
      department: "engineering",
      label: "工程",
      verifier: false,
      exit_tray: true,
      stamp: { kind: "open_loop", outsourced: false, text: "开环完成" },
    });
    const roomCanvas = await view.canvas("room");
    expect(roomCanvas.width % 480).toBe(0);
    expect(roomCanvas.colors).toBeGreaterThan(8);
    if (process.env.YUDAO_SHOTS) {
      await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/02-solo-open-loop-room.png` });
    }
    expect(errors).toEqual([]);
  });
});

test("同层两份定义并集与未声明专属外观角色：各事项按自身冻结定义盖章，顶栏缺口清单列出通用外观角色且三个场景正常显示", async ({ page }) => {
  await withViewServer({ recording: "demo", events: "none" }, async (server) => {
    const scenario = TOPOLOGY_FIXTURES.scenarios.union_and_generic;
    Object.assign(server.recording.ids, scenario.ids);
    server.recording.queries.splice(0, server.recording.queries.length, ...structuredClone(scenario.queries));

    const errors = watchErrors(page);
    const view = new ViewPage(page, server);
    await view.open({ width: 1440, height: 900 });

    // 壳顶栏出现缺口清单，展开后指明未声明专属外观的角色标识 security（安全审校）
    const gapDetails = page.locator("details", { hasText: "缺口清单" });
    await expect(gapDetails).toBeVisible();
    await gapDetails.locator("summary").click();
    await expect(gapDetails).toContainText("场景声明里没有角色 security（安全审校） 的专属外观：使用通用外观");

    // 楼场景：第 0 层为同层并集项目（同时带 release 与 open_loop），第 1 层为含 security 的项目
    const buildingFloors = await page.evaluate(() => window.__buildingViewForTest!.floors());
    expect(buildingFloors).toHaveLength(2);
    expect(buildingFloors[0]!.stamps).toEqual([
      { work_item_id: "wi_union_tri", kind: "release", outsourced: false },
      { work_item_id: "wi_union_solo", kind: "open_loop", outsourced: false },
    ]);
    expect(buildingFloors[1]!.rooms).toEqual([
      { id: "engineering", label: "工程", lit: false },
      { id: "security", label: "安全审校", lit: true },
    ]);

    // 点击进入第 0 层（同层并集项目）：engineering 设出口托盘盖虚线开环完成章，quality 设盖章台盖实心放行章
    await view.clickFloor(0);
    await view.waitForFloorState();
    const unionChannels = await page.evaluate(() => window.__floorViewForTest!.channels());
    expect(Object.keys(unionChannels.rooms)).toEqual(["product", "engineering", "quality"]);
    expect(unionChannels.rooms.engineering).toMatchObject({ verifier: false, exit_tray: true });
    expect(unionChannels.rooms.quality).toMatchObject({ verifier: true, exit_tray: false });
    expect(unionChannels.stamps).toEqual([
      { work_item_id: "wi_union_tri", room: "quality", kind: "release", outsourced: false, text: "放行" },
      { work_item_id: "wi_union_solo", room: "engineering", kind: "open_loop", outsourced: false, text: "开环完成" },
    ]);
    expect(unionChannels.shelf.boxes).toEqual([
      { work_item_id: "wi_union_tri", stamp_kind: "release", outsourced: false },
      { work_item_id: "wi_union_solo", stamp_kind: "open_loop", outsourced: false },
    ]);
    if (process.env.YUDAO_SHOTS) {
      await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/03-union-floor.png` });
    }

    // 回到楼，点击进入第 1 层（安全审校项目），再进入未声明角色 security 的通用外观房间
    await page.getByRole("button", { name: "楼" }).click();
    await view.clickFloor(1);
    await view.waitForFloorState();
    const secFloorChannels = await page.evaluate(() => window.__floorViewForTest!.channels());
    expect(secFloorChannels.rooms.security).toMatchObject({
      label: "安全审校",
      verifier: true,
      exit_tray: false,
    });

    await view.openRoom("security");
    await view.waitForCanvas("room");
    const secRoom = await view.room();
    expect(secRoom.channels).toMatchObject({
      department: "security",
      label: "安全审校",
      verifier: true,
      exit_tray: false,
    });
    expect(await view.bodyText()).toContain("安全审校");
    const secCanvas = await view.canvas("room");
    expect(secCanvas.width % 480).toBe(0);
    expect(secCanvas.colors).toBeGreaterThan(8);
    if (process.env.YUDAO_SHOTS) {
      const isOpen = await gapDetails.evaluate((el) => (el as HTMLDetailsElement).open);
      if (!isOpen) await gapDetails.locator("summary").click();
      await page.screenshot({ path: `${process.env.YUDAO_SHOTS}/04-generic-security-shell.png` });
    }
    expect(errors).toEqual([]);
  });
});
