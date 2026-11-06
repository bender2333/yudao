// 画面的端到端测试用的全局测试钩子声明（开发构建里由图鉴页的入口安装，画面自己的测试读取）。
// 画面是单独的应用，这份声明跟画面一起走；页面的那一份不从画面取（画面与播放 docs/design/visualization.md
// 「搬出：画面成为单独的应用」的测试一节）。

import type { DecisionAnswer, DecisionResult } from "./pixel/floor/card";
import type { PixelFloorTestMount } from "./pixel/floor/dev-mount";
import type { FloorTestHooks } from "./pixel/floor/view";
import type { FloorModel } from "./pixel/world/types";

declare global {
  interface Window {
    __floorViewForTest?: FloorTestHooks;
    /** 开发构建里的像素画面测试入口（只在 import.meta.env.DEV 下安装）。 */
    __pixelFloorTest?: { mount: (model: FloorModel, opts?: { answer?: (payload: DecisionAnswer) => DecisionResult }) => Promise<PixelFloorTestMount> };
  }
}

export {};
