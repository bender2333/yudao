// 开发与端到端测试用的全局测试钩子声明（像素画面由 main.tsx 在开发构建里安装）。
// 桌面桥接的 DesktopApi 声明已随 #372 删除，这里只保留画面测试入口。

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
