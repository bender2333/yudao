// 画面端到端测试的页面对象（工单 #1574）：打开 view/ 的构建结果，读画面自己的测试钩子，走真实的场景切换。
//
// 画面自己没有地址路由：入口是楼，点画布上的一层进入楼层；楼层的面包屑回到楼。
// 楼层进房间的入口还没有画出来（工单 #1573 的壳只有场景切换方法，没有点门牌的回调），
// 端到端测试经 __floorViewForTest.goRoom 走壳的同一个入口，不直接改画面状态。
//
// 这里只做操作与读数，不断言；断言在七个 spec 里。

import type { Page } from "@playwright/test";
import { readCanvas, responseOf, waitFor, type CanvasRead, type ViewServer } from "./fixtures.ts";

/** 画面自己的钩子与壳的读数（形状见 view/src/test-hooks.d.ts）。 */
interface BuildingRead {
  floors: {
    project_id: string;
    name: string;
    status: string;
    lit: Record<string, boolean>;
    valve_closed: boolean;
    decisions: number;
    flags: { work_item_id: string; department: string; color_index: number }[];
  }[];
  timeline: { shown: number | null; pending: number; playing: string[] };
}

interface FloorStateRead {
  items: { id: string; status: string; department: string | null }[];
  characters: { id: string; department: string | null; task: string | null; pose: string | null }[];
  interrupted: boolean;
  reduced: boolean;
}

interface RoomChannelsRead {
  position: number;
  department: string;
  label: string;
  verifier: boolean;
  exit_tray: boolean;
  stamp: { kind: "release" | "open_loop"; outsourced: boolean; text: string } | null;
  status: { value: string; text: string };
  pose: { role_id: string | null; anim: string } | null;
  roles: { id: string; kind: string; status: string | null }[];
  objects: { mailbox: number; scrolls: number; summaries: number; pinned_notes: number; semantic_cards: number; letters_waiting: number };
  stream: { role: string; text: string }[];
}

interface RoomTimelineRead {
  shown: number | null;
  pending: number;
}

const SELECTORS = {
  building: ".view-scene-building canvas",
  floor: ".view-scene-floor canvas",
  room: ".view-scene-room canvas",
} as const;

/** 楼的几何（view/src/pixel/world/building.ts 的 BUILDING_GEO）。 */
const ROOF = 34;
const FLOOR_HEIGHT = 66;

export class ViewPage {
  readonly page: Page;
  readonly server: ViewServer;

  constructor(page: Page, server: ViewServer) {
    this.page = page;
    this.server = server;
  }

  /** 打开画面的构建结果，等连上（能力清单与第一份查询都到了）。 */
  async open(options: { width: number; height: number }): Promise<void> {
    await this.page.setViewportSize({ width: options.width, height: options.height });
    await this.page.goto(this.server.url);
    await waitFor(() => this.page.locator('[aria-label="连接状态"]').innerText().then((text) => text.includes("已连接") || null),
      "画面连上回放的接口");
    await waitFor(async () => {
      const floors = await this.building().catch(() => null);
      return floors !== null && floors.floors.length > 0 ? floors : null;
    }, "楼里出现录下的那一层");
  }

  /** 楼的读数。 */
  async building(): Promise<BuildingRead> {
    return this.page.evaluate(() => {
      const hooks = window.__buildingViewForTest;
      if (!hooks) throw new Error("楼没有装上测试钩子");
      return { floors: hooks.floors(), timeline: hooks.timeline() };
    });
  }

  /** 点画布上第 index 层楼：进入那个项目的楼层。按画布的实际比例换算楼层的纵向位置。 */
  async clickFloor(index = 0): Promise<void> {
    const canvas = this.page.locator(SELECTORS.building);
    await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox();
    if (box === null) throw new Error("楼没有画布");
    const logicalHeight = (box.height / box.width) * 640;
    await canvas.click({ position: { x: box.width / 2, y: ((ROOF + index * FLOOR_HEIGHT + FLOOR_HEIGHT / 2) / logicalHeight) * box.height } });
    await this.waitForFloor();
  }

  /** 楼层画出的状态（事项、角色、中断与减少动画）。 */
  async floorState(): Promise<FloorStateRead> {
    return this.page.evaluate(() => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      return hooks.state();
    });
  }

  /** 楼层播放时间线的读数。 */
  async floorTimeline(): Promise<{ shown: number | null; pending: number; playing: string[] }> {
    return this.page.evaluate(() => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      return hooks.timeline();
    });
  }

  /** 大厅决定板与打开着的决定卡片。 */
  async floorDecisions(): Promise<{
    board: { x: number; y: number; w: number; h: number };
    faces: { id: string; kind: string; version: number; title: string }[];
    card: { openId: string | null; submitted: string[]; message: string | null; stamp: { id: string; text: string } | null };
  }> {
    return this.page.evaluate(() => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      return hooks.decisions();
    });
  }

  /** 当前画在画布上的覆盖层数据。 */
  async floorOverlay(): Promise<{ id: string | null; data: Record<string, unknown> | null }> {
    return this.page.evaluate(() => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      return hooks.overlay();
    });
  }

  /** 最近一帧画出的覆盖层标签（画面逻辑坐标）。 */
  async floorOverlayLabels(): Promise<{ x: number; y: number; w: number; h: number; key: string }[]> {
    return this.page.evaluate(() => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      return hooks.overlayLabels();
    });
  }

  /** 楼层上画出来的事实元素（覆盖层「来源」打开时）。 */
  async floorFacts(): Promise<{ work_item_id: string; element: string; x: number; y: number; w: number; h: number; drawn: boolean }[]> {
    return this.page.evaluate(() => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      return hooks.facts();
    });
  }

  /** 打开一张决定卡片（直接入口；点击画布上的板子是同一件事）。 */
  async openCard(id: string): Promise<void> {
    await this.page.evaluate((value) => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      hooks.openCard(value);
    }, id);
  }

  /** 回答打开着的决定卡片。 */
  async answer(option: string): Promise<void> {
    await this.page.evaluate((value) => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      return hooks.answer(value);
    }, option);
  }

  /** 等楼层画面的钩子挂上。 */
  async waitForFloor(): Promise<void> {
    await waitFor(() => this.page.evaluate(() => Boolean(window.__floorViewForTest)), "楼层画面挂上");
  }

  /** 等楼层拿到录下的那一份状态（事项出现了）。 */
  async waitForFloorState(): Promise<void> {
    await waitFor(async () => {
      const state = await this.floorState().catch(() => null);
      return state !== null && state.items.length > 0 ? state : null;
    }, "楼层收到录下的状态");
  }

  /** 打开一个覆盖层（画面还没有覆盖层的按钮，用录下的查询翻好的数据经钩子交给画面）。 */
  async setOverlay(id: string | null, data: unknown): Promise<void> {
    await this.page.evaluate(({ id: overlayId, data: overlayData }) => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      hooks.setOverlay(overlayId, overlayData);
    }, { id, data });
  }

  /** 从楼层进入一个部门房间（走壳的 goRoom 入口），等待初始工作间快照到达并完成房间状态渲染后返回。 */
  async openRoom(department: string): Promise<void> {
    const queryStart = this.server.queries.length;
    await this.page.evaluate((value) => {
      const hooks = window.__floorViewForTest;
      if (!hooks) throw new Error("楼层没有装上测试钩子");
      hooks.goRoom(value);
    }, department);
    await waitFor(() => this.page.evaluate(() => Boolean(window.__roomViewForTest)), "房间测试钩子挂载");
    await this.waitForCanvas("room");
    await this.waitForRoomState(department, queryStart);
  }

  /** 等待部门房间的初始工作间快照到达、反映到房间状态通道并完成动画帧绘制。 */
  async waitForRoomState(department: string, queryStart = 0): Promise<void> {
    const queriesCap = (this.server.fixtures.capabilities as { queries?: { name?: unknown }[] }).queries ?? [];
    const expectsLoopQuery = queriesCap.some((item) => item.name === "project.loop");
    await waitFor(async () => {
      const recentQueries = this.server.queries.slice(queryStart);
      const workspaceQueries = recentQueries.filter(
        (entry) => entry.name === "department.workspace" && entry.params.department?.[0] === department,
      );
      const latestWorkspaceQuery = workspaceQueries.at(-1);
      if (!latestWorkspaceQuery) return null;
      if (expectsLoopQuery && !recentQueries.some((entry) => entry.name === "project.loop")) {
        return null;
      }
      let expectedPosition: number | null = null;
      try {
        expectedPosition = responseOf(this.server.recording, "department.workspace", latestWorkspaceQuery.params).position;
      } catch {
        expectedPosition = null;
      }
      const ready = await this.page.evaluate(async ({ targetDepartment, targetPosition }) => {
        await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
        const hooks = window.__roomViewForTest;
        if (!hooks) return false;
        const channels = hooks.channels();
        const timeline = hooks.timeline();
        if (channels.department !== targetDepartment) return false;
        if (timeline.shown === null || timeline.pending > 0) return false;
        const positionMatched = targetPosition !== null
          ? channels.position === targetPosition
          : channels.position > 0;
        return positionMatched && timeline.shown === channels.position;
      }, { targetDepartment: department, targetPosition: expectedPosition }).catch(() => false);
      return ready ? true : null;
    }, `房间 ${department} 收到录下的工作间状态`);
  }

  /** 房间的读数（状态、角色、物件、流式文字与播放时间线）。 */
  async room(): Promise<{ channels: RoomChannelsRead; timeline: RoomTimelineRead }> {
    return this.page.evaluate(() => {
      const hooks = window.__roomViewForTest;
      if (!hooks) throw new Error("房间没有装上测试钩子");
      return { channels: hooks.channels(), timeline: hooks.timeline() };
    });
  }

  /** 面包屑里的一项（楼 / 项目名 / 部门名）：点它回到那一层。 */
  async crumb(label: string): Promise<void> {
    await this.page.locator('nav[aria-label="场景"] button', { hasText: label }).first().click();
  }

  /** 回到楼（等楼重新拿到状态，不只是钩子挂上）。 */
  async backToBuilding(): Promise<void> {
    await this.crumb("楼");
    await waitFor(async () => {
      const read = await this.building().catch(() => null);
      return read !== null && read.floors.length > 0 ? read : null;
    }, "回到楼");
  }

  /** 从房间回到楼层。 */
  async backToFloor(projectLabel: string): Promise<void> {
    await this.crumb(projectLabel);
    await this.waitForFloor();
  }

  /** 等一层场景的画布出现。 */
  async waitForCanvas(scene: keyof typeof SELECTORS): Promise<void> {
    await this.page.locator(SELECTORS[scene]).waitFor({ state: "visible" });
  }

  /** 读一张画布的像素。 */
  async canvas(scene: keyof typeof SELECTORS): Promise<CanvasRead> {
    return readCanvas(this.page, SELECTORS[scene]);
  }

  /** 页面上能读到的文字（核对画布以外的说法）。 */
  async bodyText(): Promise<string> {
    return this.page.locator("body").innerText();
  }
}
