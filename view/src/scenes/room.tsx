// 房间的场景（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」「分层与边界」；工单 #177、#954、#1573）。
//
// 画面自己的组件：建立部门房间的像素画面（pixel/room/view.ts），把画布容器与时钟交给壳。
// 状态只来自 department.workspace 的查询结果（经翻译层翻好交给画面），事件只翻成动作与流式文字。
// 换部门时画面重建（上一个部门的模型不交给新的房间）；同一部门的重新查询不重建画面（数据短暂为空时沿用上一份）。
//
// 页面上的实时模型输出不进画面：房间头顶的流式文字来自事件流里的模型输出（画面合同「实时内容」），
// 页面侧的那一份留在页面上。

import { useEffect, useRef } from "react";
import { createRafClock } from "../pixel/clock.ts";
import { createRoomView } from "../pixel/room/view.ts";
import type { RoomState } from "../pixel/contract.ts";
import type { Shell, SceneSurface } from "../shell.ts";

export function RoomScene(props: { shell: Shell; projectId: string; department: string }): React.JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null);
  // 场景对象的标识：换部门才重建画面
  const key = `${props.projectId}\u0000${props.department}`;
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const clock = createRafClock(
      (callback: (time: number) => void) => requestAnimationFrame(callback),
      () => performance.now(),
      (handle: number) => cancelAnimationFrame(handle),
    );
    const detach = props.shell.attachHost(host, clock, async (options): Promise<SceneSurface> => {
      const view = await createRoomView({
        host: options.host,
        clock: options.clock,
        department: props.department,
      });
      return {
        jump: (state) => view.jump(state as RoomState),
        setState: (state) => view.setState(state as RoomState),
        play: (action) => view.play(action),
        stream: (who, text) => view.stream({ room: who.room, role: who.role }, text),
        destroy: () => view.destroy(),
      };
    });
    return () => {
      detach();
      clock.destroy();
    };
  }, [props.shell, key, props.department, props.projectId]);
  return <div className="view-scene view-scene-room" ref={hostRef} />;
}
