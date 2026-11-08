// 楼层的场景（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」「分层与边界」；工单 #82、#953、#1573）。
//
// 画面自己的组件：建立项目楼层的像素画面（pixel/floor/view.ts），把画布容器与时钟交给壳；
// 画面交出的回调在这里接到壳上：回答决定（变成现有的命令）、点开回链（变成 Yudao 页面的地址，
// 在新的标签页打开）、决定卡片上的页面链接与「在时间轴上查看」。点一间屋进入房间（画面自己的场景切换）。
//
// 页面上的文字列表、决定卡片与实时模型输出不进画面：大厅板上的是画面自己的决定卡片（画面合同「实时内容」），
// 选项经壳发出回答决定的命令；画布以外的文字由壳写在画布外。

import { useEffect, useRef } from "react";
import { createRafClock } from "../pixel/clock.ts";
import { createFloorView } from "../pixel/floor/view.ts";
import type { DecisionAnswer } from "../pixel/floor/card.ts";
import type { DecisionFace, FactElement, FloorModel } from "../pixel/contract.ts";
import type { Shell, SceneSurface } from "../shell.ts";

export function FloorScene(props: { shell: Shell; projectId: string; workItemId: string | null }): React.JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null);
  // 场景对象的标识：换项目或换事项才重建画面，数据变化不重建
  const key = `${props.projectId}\u0000${props.workItemId ?? ""}`;
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const shell = props.shell;
    const clock = createRafClock(
      (callback: (time: number) => void) => requestAnimationFrame(callback),
      () => performance.now(),
      (handle: number) => cancelAnimationFrame(handle),
    );
    const detach = shell.attachHost(host, clock, async (options): Promise<SceneSurface> => {
      const view = await createFloorView({
        host: options.host,
        clock: options.clock,
        cardHost: options.host,
        // 大厅板上选择决定选项：壳发出回答决定的命令（能力清单里没有这条命令时选项不可操作）
        onDecide: shell.decisionsOperable
          ? (payload: DecisionAnswer) => shell.decide(payload)
          : undefined,
        // 决定卡片上的页面链接（页面现有的 # 写法）：壳在新的标签页打开 Yudao 的页面
        onGo: (target: string) => shell.openPageTarget(target),
        // 点开回链：画面只交出哪个元件、哪个事项，壳从当前状态取位置并打开页面的地址
        onOpenSource: (workItemId: string, element: FactElement) => {
          shell.openFactLink(workItemId, element);
        },
        // 来源卡片上的「在时间轴上查看」：按位置打开页面概览
        onGoTimeline: (position: number) => shell.openTimelineLink(position),
      });
      return {
        jump: (state) => {
          view.jump(state as FloorModel);
          view.focus(props.workItemId);
        },
        setState: (state) => view.setState(state as FloorModel),
        play: (action) => view.play(action),
        setDecisions: (faces: DecisionFace[]) => view.setDecisions(faces),
        stream: (who, text) => view.stream({ room: who.room, role: who.role }, text),
        destroy: () => view.destroy(),
      };
    });
    return () => {
      detach();
      clock.destroy();
    };
  }, [props.shell, key, props.workItemId, props.projectId]);
  return <div className="view-scene view-scene-floor" ref={hostRef} />;
}
