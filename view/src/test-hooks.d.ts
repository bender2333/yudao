// 画面的端到端测试用的全局测试钩子声明（画面自己的测试读取；三个场景挂上画面时安装）。
// 画面是单独的应用，这份声明跟画面一起走；页面的那一份不从画面取（画面与播放 docs/design/visualization.md
// 「搬出：画面成为单独的应用」的测试一节）。
//
// 钩子只读画面画出来的事实，不替测试改状态；例外是两个测试入口：__pixelFloorTest 在开发构建里把楼层画面
// 挂到独立容器上（图鉴页的入口安装），__floorViewForTest 的 setOverlay 让测试按录下的查询翻出的数据打开
// 覆盖层（画面还没有覆盖层的按钮，见工单 #1574 的交付说明）。

import type { BuildingTestHooks } from "./pixel/building/view";
import type { DecisionAnswer, DecisionResult } from "./pixel/floor/card";
import type { PixelFloorTestMount } from "./pixel/floor/dev-mount";
import type { FloorTestHooks } from "./pixel/floor/view";
import type { RoomChannels } from "./pixel/room/view";
import type { FloorModel } from "./pixel/world/types";
import type { TimelineInspect } from "./pixel/timeline";

declare global {
  interface Window {
    /** 楼场景的读数：每层的状态灯、亮灯的房间、小旗与时间线。 */
    __buildingViewForTest?: BuildingTestHooks;
    /**
     * 楼层场景的读数与两个驱动入口：setOverlay 按录下的查询翻好的数据打开覆盖层，
     * goRoom 从楼层进入一个部门（画面还没有点门牌进房间的入口，测试用这个入口走真实的场景切换）。
     */
    __floorViewForTest?: FloorTestHooks & {
      setOverlay: (id: string | null, data: unknown) => void;
      goRoom: (department: string) => void;
    };
    /** 房间场景的读数：状态、角色、物件与流式文字，以及播放时间线。 */
    __roomViewForTest?: {
      channels: () => RoomChannels;
      timeline: () => TimelineInspect;
    };
    /** 开发构建里的像素画面测试入口（只在 import.meta.env.DEV 下安装）。 */
    __pixelFloorTest?: { mount: (model: FloorModel, opts?: { answer?: (payload: DecisionAnswer) => DecisionResult }) => Promise<PixelFloorTestMount> };
  }
}

export {};
