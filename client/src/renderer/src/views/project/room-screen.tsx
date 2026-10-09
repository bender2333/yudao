// 部门工作间的部门房间画面（工单 #177）：把 department.workspace 的 room 数据交给部门房间画面，
// 把事件流里本部门的事件变成动作。状态以查询为准：每次查询结果到达都重新 setModel；事件只决定动作的起点。

import { useEffect, useRef, useState } from "react";
import type { EventObject } from "../../api/generated/types.gen";
import type { DepartmentWorkspaceResult } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { createRafClock, type Clock } from "../../pixel/clock";
import { createRoomView, type RoomModel, type RoomView } from "../../pixel/room/view";
import { collaborationSides, handoffOf } from "../../pixel/room/decl";
import { StreamBubble } from "../../pixel/room/stream";
import type { PixelFloorEvent } from "../../pixel/world/types";

/** 把 department.workspace 的 room 结果组装成房间画面数据（字段与原型 roomModel 一一对应）。 */
export function roomModelOf(workspace: DepartmentWorkspaceResult): RoomModel {
  const room = workspace.room;
  const pose = room.pose as { role_id?: string | null; action: string } | null;
  return {
    department: room.department,
    level: room.level,
    status: room.status,
    crt: room.crt,
    roles: room.roles.map((r) => ({ id: r.id, name: r.name, kind: r.kind, status: r.status, task: r.task })),
    pose: pose === null ? null : { role_id: pose.role_id ?? null, action: String(pose.action) },
    door: room.door,
    hold_card: room.hold_card,
    pending_tool: room.pending_tool,
    mailbox: room.mailbox,
    summaries: room.summaries,
    scrolls: room.scrolls,
    pinned_notes: room.pinned_notes,
    semantic_cards: room.semantic_cards,
    machine: room.machine,
    remote_unknown: room.remote_unknown,
    waiting_provider: room.waiting_provider,
    pipes: room.pipes,
    existing_read: room.existing_read,
    trial: room.trial,
    tool_panel: room.tool_panel,
    self_test: room.self_test,
  };
}

/** 把事件流里的事件转成部门房间的事件（只保留本部门相关的事件）。
 *  交接与传信的载荷在真实系统里不是部门（交接是工作阶段，传信写 requester/recipient），
 *  这里统一补成原型的 from/to 形状，画面与说话目录按同一份数据工作。 */
export function roomEventOf(event: EventObject, department: string,
                            requests?: Map<string, { requester: string; recipient: string }>): PixelFloorEvent | null {
  const raw = event.payload as unknown as Record<string, unknown>;
  let payload = raw;
  if (event.type === "transition") {
    const handoff = handoffOf(raw);
    if (!handoff) return null;
    if (handoff.from !== department && handoff.to !== department) return null;
    payload = { ...raw, from: handoff.from, to: handoff.to, artifact: handoff.artifact };
  } else if (event.type === "collaboration_requested" || event.type === "collaboration_responded") {
    const sides = collaborationSides(event.type, raw, event.department, requests);
    if (!sides) return null;
    if (sides.from !== department && sides.to !== department) return null;
    payload = { ...raw, from: sides.from, to: sides.to };
  } else {
    const from = raw?.from as string | undefined;
    const to = raw?.to as string | undefined;
    const related = event.department === null || event.department === department
      || from === department || to === department;
    if (!related) return null;
  }
  return {
    type: event.type,
    department: event.department,
    role: event.role,
    tool: (payload.tool as string | null) ?? (payload.name as string | null) ?? null,
    label: event.label,
    work_item_id: event.work_item_id,
    project_id: event.project_id,
    position: event.position,
    payload,
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
  };
}

/** 部门房间：画布与事件订阅；状态来自 department.workspace 的 room 数据。
 *  部门由页面按路由给出：查询结果到达之前也要按同一个部门订阅事件。
 *  重新查询期间数据短暂为空时画面保持挂载（换事项不重建画面），用最近一次的查询结果继续显示。 */
export function RoomScreen(props: { app: ClientApp; department: string; data: DepartmentWorkspaceResult | null }): React.JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<RoomView | null>(null);
  const clockRef = useRef<Clock | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 最近一次的查询结果：数据为空时沿用，避免重新查询期间重建画面；换部门时清空
  const lastDataRef = useRef<{ department: string; data: DepartmentWorkspaceResult; model: RoomModel } | null>(null);
  if (lastDataRef.current !== null && lastDataRef.current.department !== props.department) {
    lastDataRef.current = null;
  }
  if (props.data !== null && props.data.department === props.department) {
    lastDataRef.current = { department: props.department, data: props.data, model: roomModelOf(props.data) };
  }
  const last = lastDataRef.current;
  const department = props.department;
  const model: RoomModel | null = last?.model ?? null;
  // 思考气泡：查询 attempt.live 与按偏移接上片段的规则，跨效果重建保持同一份状态
  const bubbleRef = useRef(new StreamBubble());
  // 最近一次的查询结果：数据为空时沿用上一次的模型
  const modelRef = useRef<RoomModel | null>(model);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    // 工单 #300：换部门时丢掉上一个部门留下的状态。新部门的查询结果到达以前数据为空，
    // 沿用的模型因此还是上一个部门的，交给新建的画面会被画面拒绝（部门不一致）。
    // 思考气泡里是上一个部门那次调用尝试的文字，错误提示属于上一个部门的画面，一起清掉。
    modelRef.current = null;
    bubbleRef.current.clear();
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
        // 画面建立时立即应用当前查询结果：模型效果在首次渲染时视图还不存在
        if (modelRef.current !== null) viewRef.current.setModel(modelRef.current);
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

  useEffect(() => {
    if (model === null) return;
    modelRef.current = model;
    viewRef.current?.setModel(model);
  }, [model]);

  useEffect(() => {
    const bubble = bubbleRef.current;
    // 本次连接内见过的询问：旧事件的回答里没有两端时按 request_id 回退查找
    const requests = new Map<string, { requester: string; recipient: string }>();
    const off = props.app.subscribeEvents((event) => {
      const seen = event.payload as unknown as Record<string, unknown>;
      if (event.type === "collaboration_requested") {
        const id = typeof seen.request_id === "string" ? seen.request_id : null;
        const requester = typeof seen.requester === "string" ? seen.requester : null;
        const recipient = typeof seen.recipient === "string" ? seen.recipient : null;
        if (id && requester && recipient) requests.set(id, { requester, recipient });
      }
      const roomEvent = roomEventOf(event, department, requests);
      if (roomEvent) viewRef.current?.playEvent(roomEvent);
      // 流式输出：模型请求开始时先查询 attempt.live 得到已收到的文字，之后再按 offset 接上片段
      const payload = event.payload as unknown as Record<string, unknown>;
      const attemptId = typeof payload.attempt_id === "string" ? payload.attempt_id : null;
      // 工单 #300：其他部门的流式输出不属于这个画面（判断方式与 roomEventOf 一致）
      if (event.department !== null && event.department !== department) return;
      if (event.type === "model_stream_progress" && attemptId !== null) {
        // 先观察这次调用尝试：attempt.live 查询未及时返回时，片段仍能按 offset 接上
        bubble.observe(attemptId);
        const viewSync = props.app.viewSync;
        if (!viewSync) return;
        void viewSync.open<{ live: boolean; channels: Record<string, string> }>(
          `room.attempt.live.${attemptId}`,
          { query: "attempt.live", params: { attempt_id: attemptId } },
          (data) => {
            if (!data.live) return;
            bubble.seed(attemptId, data.channels.output ?? "");
            viewRef.current?.setStreamText(bubble.current);
          },
        );
      }
    });
    // 事件流里的模型输出片段：offset 不小于已有字数的片段接上，逐字出现在思考气泡里
    const offDelta = props.app.subscribeDeltas((delta) => {
      // 工单 #300：片段带着发出部门的名字，其他部门的文字不进这个画面
      if (delta.department !== department) return;
      if (bubble.absorb({ attemptId: delta.attempt_id, channel: delta.channel, offset: delta.offset, text: delta.text })) {
        viewRef.current?.setStreamText(bubble.current);
      }
    });
    return () => {
      off();
      offDelta();
    };
  }, [props.app, department]);

  useEffect(() => {
    const off = props.app.subscribeResync(() => {
      if (modelRef.current !== null) viewRef.current?.setModel(modelRef.current);
    });
    return off;
  }, [props.app]);

  return (
    <>
      <div className="y9-scene room-canvas" ref={hostRef} />
      {error !== null ? <p className="pixel-canvas-error">部门房间加载失败：{error}</p> : null}
    </>
  );
}
