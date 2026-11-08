// 楼的场景（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」「分层与边界」；工单 #178、#1573）。
//
// 画面自己的组件：建立楼的像素画面（pixel/building/view.ts），把画布容器与时钟交给壳；
// 点一层楼上时在画面自己的场景之间切换（楼 → 楼层），不经页面。画面上的状态与动作由壳经同步层与翻译层给出，
// 这个组件不读查询、也不认识服务端的说法。
//
// 数据变化不让画面重建：场景对象（同一个楼）只挂载一次，状态变化由壳交给像素画面（setState/jump）。

import { useEffect, useRef } from "react";
import { createRafClock } from "../pixel/clock.ts";
import { buildingTestHooks, createBuildingView, type BuildingTestHooks } from "../pixel/building/view.ts";
import type { BuildingModel } from "../pixel/contract.ts";
import type { Shell, SceneSurface } from "../shell.ts";

export function BuildingScene(props: { shell: Shell }): React.JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const clock = createRafClock(
      (callback: (time: number) => void) => requestAnimationFrame(callback),
      () => performance.now(),
      (handle: number) => cancelAnimationFrame(handle),
    );
    const detach = props.shell.attachHost(host, clock, async (options): Promise<SceneSurface> => {
      const view = await createBuildingView({
        host: options.host,
        clock: options.clock,
        // 点一层楼：进入这个项目的楼层（画面自己的场景切换，地址不变）
        onFloorClick: (projectId) => props.shell.goFloor(projectId),
      });
      // 端到端测试经这个入口读取楼画出的当前状态（画面自己的钩子，声明见 src/test-hooks.d.ts）
      const testWindow = window as unknown as { __buildingViewForTest?: BuildingTestHooks };
      testWindow.__buildingViewForTest = buildingTestHooks(view);
      return {
        jump: (state) => view.jump(state as BuildingModel),
        setState: (state) => view.setState(state as BuildingModel),
        play: (action) => view.play(action),
        destroy: () => view.destroy(),
      };
    });
    return () => {
      detach();
      // 场景被卸下（换场景）：读取入口一起撤掉，测试不会读到已经销毁的画面
      delete (window as unknown as { __buildingViewForTest?: BuildingTestHooks }).__buildingViewForTest;
      clock.destroy();
    };
  }, [props.shell]);
  return <div className="view-scene view-scene-building" ref={hostRef} />;
}
