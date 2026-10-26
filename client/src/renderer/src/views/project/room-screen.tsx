// 部门工作间的部门房间画面（工单 #177、#954）：把 department.workspace 的查询结果经翻译层交给画面，
// 把事件流里本部门的事件翻成动作。
//
// 状态以查询为准：每次查询结果到达都经 translate/room.ts 翻成房间的状态交给画面（setState）；
// 打开画面、重新同步、切换部门与标签页从后台切回时用 jump：清空时间线，直接显示最新的状态，不补播。
// 事件只翻成动作；流式文字是实时内容，到了就显示，不进时间线。

import { useEffect, useRef, useState } from "react";
import type { EventObject } from "../../api/generated/types.gen";
import type { DepartmentWorkspaceResult } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { createRafClock, type Clock } from "../../pixel/clock";
import { createRoomView, type RoomView } from "../../pixel/room/view";
import { StreamBubble } from "../../pixel/room/stream";
import type { PixelState } from "../../pixel/contract";
import * as room from "../../translate/room";

/** 房间的状态：查询结果（还是录制下来的同一形状）经翻译层翻成画面合同的状态。 */
export function roomStateOf(workspace: DepartmentWorkspaceResult, position: number): PixelState {
  return room.state({ position, workspace: { room: workspace.room } });
}

/** 一条事件流里的事件 → 翻译层要的字段（只挑房间用到的几项）。 */
export function roomEventOf(event: EventObject, position: number): room.RoomEvent {
  const pl = event.payload as unknown as Record<string, unknown>;
  return {
    type: event.type,
    position: event.position ?? position,
    department: event.department,
    role: event.role,
    // 工具名：事件信封的 tool，或者载荷上的 name（真实系统的 tool_started 把工具名写在 name 上）
    tool: (event as { tool?: string | null }).tool ?? (typeof pl.name === "string" ? pl.name : null),
    label: event.label,
    work_item_id: event.work_item_id,
    payload: pl,
  };
}

/** 部门房间画面对象。 */
export interface RoomTestHooks {
  state: () => {
    department: string;
    status: string | null;
    characters: { id: string; kind: string; doing: string | null; pose: string | null; say: string | null; stream: string | null }[];
    letters: number;
  };
  /** 画面时间线的读数：在演与排着的动作、落后的时间与计数（端到端核对「不补播」「关键动作不丢」用）。 */
  timeline: () => {
    shown: number | null;
    pending: number;
    lag: number;
    queued: number;
    playing: string[];
    stats: Record<string, number>;
  };
}

/** 给端到端测试用的读取入口：读的是画面里世界的当前状态。 */
export function roomTestHooks(view: RoomView): RoomTestHooks {
  return {
    state: () => {
      const { driver, scene } = view.inspect();
      return {
        department: driver.model.department,
        status: driver.model.status,
        characters: driver.actors().map((c) => {
          const a = scene.actors.find((x) => x.id === `ch-${c.id}`);
          return { id: c.id, kind: c.role.kind, doing: c.doing, pose: a ? a.anim : null, say: c.say ? c.say.text : null, stream: c.streamText };
        }),
        letters: driver.model.pipes?.letters_waiting ?? 0,
      };
    },
    timeline: () => {
      const tl = view.inspect().driver.timeline();
      return {
        shown: tl.shown,
        pending: tl.pending,
        lag: tl.lag,
        queued: tl.queued,
        playing: tl.playing.map((p) => p.kind),
        stats: { ...tl.stats } as unknown as Record<string, number>,
      };
    },
  };
}

/** 部门房间：画布与事件订阅；状态来自 department.workspace 的查询结果。
 *  部门由页面按路由给出：查询结果到达之前也要按同一个部门订阅事件。
 *  重新查询期间数据短暂为空时画面保持挂载（换事项不重建画面），用最近一次的查询结果继续显示。 */
export function RoomScreen(props: { app: ClientApp; department: string; data: DepartmentWorkspaceResult | null }): React.JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<RoomView | null>(null);
  const clockRef = useRef<Clock | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 最近一次的查询结果：数据为空时沿用，避免重新查询期间重建画面；换部门时清空
  const lastDataRef = useRef<{ department: string; data: DepartmentWorkspaceResult } | null>(null);
  if (lastDataRef.current !== null && lastDataRef.current.department !== props.department) {
    lastDataRef.current = null;
  }
  if (props.data !== null && props.data.department === props.department) {
    lastDataRef.current = { department: props.department, data: props.data };
  }
  const last = lastDataRef.current;
  const department = props.department;
  const data: DepartmentWorkspaceResult | null = last?.data ?? null;
  // 思考气泡：查询 attempt.live 与按偏移接上片段的规则，跨效果重建保持同一份状态
  const bubbleRef = useRef(new StreamBubble());
  // 最近一次的查询结果：数据为空时沿用上一次的状态
  const dataRef = useRef<DepartmentWorkspaceResult | null>(data);
  // 页面上能拿到的最大全局位置（事件流读到的位置）：状态的位置取它。
  // 查询结果的快照位置经 useSnapshot 拿到，但部门页只把查询结果交给这个组件（department.tsx 不在本工单的范围内），
  // 所以这里取事件流读到的位置作为下界：状态不会比快照新，最多少等一个动作。
  const positionRef = useRef(0);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    // 工单 #300：换部门时丢掉上一个部门留下的状态。新部门的查询结果到达以前数据为空，
    // 沿用的数据因此还是上一个部门的，交给新建的画面会被画面拒绝（部门不一致）。
    // 思考气泡里是上一个部门那次调用尝试的文字，错误提示属于上一个部门的画面，一起清掉。
    dataRef.current = null;
    bubbleRef.current.clear();
    positionRef.current = 0;
    setError(null);
    let cancelled = false;
    const clock = createRafClock(
      (cb: (t: number) => void) => requestAnimationFrame(cb),
      () => performance.now(),
      (h: number) => cancelAnimationFrame(h),
    );
    clockRef.current = clock;
    void (async () => {
      try {
        const view = await createRoomView({ host, clock, department });
        if (cancelled) {
          view.destroy();
          return;
        }
        viewRef.current = view;
        // 画面建立时立即跳到当前查询结果：打开画面不补播（设计说明第 5.2 节「跳到最新」）
        if (dataRef.current !== null) view.jump(roomStateOf(dataRef.current, positionRef.current));
        // 端到端测试经这个入口读取画面的当前状态（只读的检查入口）
        (window as unknown as { __roomViewForTest?: RoomTestHooks }).__roomViewForTest = roomTestHooks(view);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      viewRef.current?.destroy();
      viewRef.current = null;
      // 工单 #300：读取入口一起撤掉，画面换了部门以后不让测试读到上一个部门的旧画面
      delete (window as unknown as { __roomViewForTest?: RoomTestHooks }).__roomViewForTest;
      clock.destroy();
      clockRef.current = null;
    };
  }, [department]);

  // 查询结果到达：经翻译层翻成状态交给画面（状态等它之前的动作演完再上画面）
  useEffect(() => {
    if (data === null) return;
    dataRef.current = data;
    try {
      viewRef.current?.setState(roomStateOf(data, positionRef.current));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [data]);

  useEffect(() => {
    const bubble = bubbleRef.current;
    const showStream = (): void => {
      const stream = room.streamOfText(department, null, bubble.current);
      viewRef.current?.stream(stream.who, stream.text);
    };
    const off = props.app.subscribeEvents((event) => {
      // 这个页面上能拿到的最大全局位置：下一次查询结果的状态带它
      positionRef.current = Math.max(positionRef.current, event.position);
      // 别的项目的事件不属于这个画面
      const project = dataRef.current?.project_id;
      if (event.project_id !== null && project !== undefined && event.project_id !== project) return;
      const ev = roomEventOf(event, positionRef.current);
      // 动作：一条事件可以翻成零个、一个或几个动作
      const roles = dataRef.current?.room.roles;
      const ctx = {
        roleName: (id: string | null): string | null => {
          const hit = (roles ?? []).find((r) => r.id === id || r.kind === id || r.name === id);
          return hit ? hit.name : null;
        },
      };
      for (const action of room.actions(ev, department, ctx)) viewRef.current?.play(action);
      // 流式输出：模型请求开始时先查询 attempt.live 得到已收到的文字，之后再按 offset 接上片段
      const payload = event.payload as unknown as Record<string, unknown>;
      const attemptId = typeof payload.attempt_id === "string" ? payload.attempt_id : null;
      // 工单 #300：其他部门的流式输出不属于这个画面
      if (event.department !== null && event.department !== department) return;
      if (event.type === "model_stream_progress" && attemptId !== null) {
        // 先观察这次调用尝试：attempt.live 查询未及时返回时，片段仍能按 offset 接上
        bubble.observe(attemptId);
        const viewSync = props.app.viewSync;
        if (!viewSync) return;
        void viewSync.open<{ live: boolean; channels: Record<string, string> }>(
          `room.attempt.live.${attemptId}`,
          { query: "attempt.live", params: { attempt_id: attemptId } },
          (live) => {
            if (!live.live) return;
            bubble.seed(attemptId, live.channels.output ?? "");
            showStream();
          },
        );
      }
    });
    // 事件流里的模型输出片段：offset 不小于已有字数的片段接上，逐字出现在思考气泡里
    const offDelta = props.app.subscribeDeltas((delta) => {
      // 工单 #300：片段带着发出部门的名字，其他部门的文字不进这个画面
      if (delta.department !== department) return;
      if (bubble.absorb({ attemptId: delta.attempt_id, channel: delta.channel, offset: delta.offset, text: delta.text })) {
        showStream();
      }
    });
    return () => {
      off();
      offDelta();
    };
  }, [props.app, department]);

  // 重新同步：画面跳到查询给出的最新状态，不补播
  useEffect(() => {
    const jump = (): void => {
      if (dataRef.current !== null) viewRef.current?.jump(roomStateOf(dataRef.current, positionRef.current));
    };
    const off = props.app.subscribeResync(jump);
    // 标签页从后台切回：清空时间线，直接显示最新的状态（设计说明第 5.2 节）
    const onVisible = (): void => {
      if (document.visibilityState === "visible") jump();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      off();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [props.app]);

  return (
    <>
      <div className="y10-scene room-canvas" ref={hostRef} />
      {error !== null ? <p className="pixel-canvas-error">部门房间加载失败：{error}</p> : null}
    </>
  );
}
