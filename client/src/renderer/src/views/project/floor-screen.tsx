// 概览页的循环画面：把查询结果（project.loop 加上部门角色列表与决定请求）交给楼层画面，
// 把事件流里本项目的事件变成动作，按能力清单显示覆盖层（工单 #82、设计说明第 5.2 至 5.7 节）。
//
// 状态以查询为准：每次查询结果到达都重新 setModel；事件只决定动作的起点。
// 断线重连或收到 resync 以后画面回到查询给出的状态，不补播已经播放过的动作。

import { useEffect, useMemo, useRef, useState } from "react";
import type { Capabilities, DecisionList, DecisionView, EventObject, ProjectFlowResult, ProjectLoopResult, WorkItemLoop } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { createRafClock } from "../../pixel/clock";
import { createFloorView, type FloorView } from "../../pixel/floor/view";
import type { FloorModel, LoopItem, PixelFloorEvent } from "../../pixel/world/types";
import { useSnapshot } from "./use-snapshot";

/** 画面里的事项：project.loop 的行加上队列位置与等待模型服务的时间。 */
type LoopRow = WorkItemLoop & { queue_pos?: number; waiting_provider_sec?: number };

export interface FloorScreenProps {
  app: ClientApp;
  projectId: string;
  workItemId: string | null;
}

/** 覆盖层的名称与中文标签（按能力清单显示）。 */
const OVERLAY_LABELS: [string, string][] = [
  ["flow", "流转"],
  ["waiting", "等待"],
  ["recovery", "恢复"],
  ["context_usage", "上下文用量"],
  ["semantic_records", "语义记录"],
];

/** 把查询结果组装成楼层画面数据：事项、角色列表、决定请求、执行槽位与运维数据。 */
export function floorModelOf(input: {
  loop: ProjectLoopResult | null;
  workspaces: Record<string, { roles?: { id: string; name: string; kind: string; status: string }[] }>;
  decisions: DecisionView[] | null;
  slots: { total: number; used: number } | null;
  ops: { version?: string; fault?: boolean; auto_repair_stopped?: boolean } | null;
  machines: { id: string; name: string; actions: number; unknown?: boolean; online?: boolean }[] | null;
  interrupted: boolean;
}): FloorModel {
  const items: LoopItem[] = (input.loop?.work_items ?? []).map((row, index) => ({
    ...(row as LoopRow),
    color_index: row.color_index ?? index + 1,
  }));
  const roles: Record<string, { id: string; name: string; kind: string; status: string }[]> = {};
  for (const [department, workspace] of Object.entries(input.workspaces)) {
    if (workspace.roles && workspace.roles.length) roles[department] = workspace.roles;
  }
  return {
    items,
    open_requests: [],
    shelves: { adopted: (input.loop?.adoptions ?? []).map((a) => a.work_item_id) },
    slots: input.slots,
    waiting_provider: [],
    machines: input.machines,
    ops: input.ops,
    interrupted: input.interrupted,
    roles: Object.keys(roles).length ? roles : null,
    decisions: (input.decisions ?? []).map((d) => ({
      id: d.decision_id, kind: d.kind, version: d.version, title: d.kind, work_item_id: d.work_item_id, status: d.status,
    })),
  };
}

/** 把事件流里的事件转成楼层画面的事件（只保留本项目的事件）。 */
export function floorEventOf(event: EventObject, projectId: string): PixelFloorEvent | null {
  // 事件的公共字段（ADR-0019 的事件信封）：项目、部门、角色、说明与载荷都是登记在接口合同里的。
  if (event.project_id !== null && event.project_id !== projectId) return null;
  const payload = event.payload as unknown as Record<string, unknown>;
  return {
    type: event.type,
    department: event.department,
    role: event.role,
    label: event.label,
    work_item_id: event.work_item_id,
    project_id: event.project_id,
    position: event.position,
    payload,
  };
}

/** 循环画面：画布、覆盖层切换、窄屏文字列表与决定卡片。 */
export function FloorScreen(props: FloorScreenProps): React.JSX.Element {
  const loop = useSnapshot<ProjectLoopResult>(props.app, "page.loop", "project.loop", {
    project_id: props.projectId,
    work_item: props.workItemId,
  });
  const decisions = useSnapshot<DecisionList>(props.app, "page.decisions", "decisions.list", {
    project_id: props.projectId, status: ["open"],
  });
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<FloorView | null>(null);
  const clockRef = useRef<ReturnType<typeof createRafClock> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<string | null>(null);
  const capabilities = props.app.currentCapabilities;

  // 建立画面：PixiJS 的 Application 挂在宿主元素上，时钟与事件流分别订阅
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    const clock = createRafClock(
      (cb: (t: number) => void) => requestAnimationFrame(cb),
      () => performance.now(),
      (h: number) => cancelAnimationFrame(h),
    );
    clockRef.current = clock;
    void (async () => {
      try {
        const view = await createFloorView({ host, clock });
        if (cancelled) {
          view.destroy();
          return;
        }
        viewRef.current = view;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      viewRef.current?.destroy();
      viewRef.current = null;
      clock.destroy();
      clockRef.current = null;
    };
  }, []);

  const model = useMemo(
    () => floorModelOf({
      loop: loop.data,
      workspaces: {},
      decisions: decisions.data?.decisions ?? null,
      slots: null,
      ops: null,
      machines: null,
      interrupted: false,
    }),
    [loop.data, decisions.data],
  );

  // 每次查询结果到达：状态以查询为准
  useEffect(() => {
    viewRef.current?.setModel(model);
  }, [model]);

  // 事件只决定动作的起点
  useEffect(() => {
    const off = props.app.subscribeEvents((event) => {
      const floorEvent = floorEventOf(event, props.projectId);
      if (floorEvent) viewRef.current?.playEvent(floorEvent);
    });
    return off;
  }, [props.app, props.projectId]);

  // 重新同步：画面回到查询给出的状态，不补播
  useEffect(() => {
    const off = props.app.subscribeResync(() => {
      viewRef.current?.setModel(model);
    });
    return off;
  }, [props.app, model]);

  useEffect(() => {
    viewRef.current?.focus(props.workItemId);
  }, [props.workItemId]);

  useEffect(() => {
    viewRef.current?.setOverlay(overlay, overlay === null ? null : overlayData(overlay, loop.data, decisions.data));
  }, [overlay, loop.data, decisions.data]);

  const overlays = (capabilities?.overlays ?? []).map((o) => o.name);
  const flow = useSnapshot<ProjectFlowResult>(props.app, "page.loop.flow", "project.flow", {
    project_id: props.projectId,
  });
  void flow;

  return (
    <div className="floor-screen">
      <div className="floor-overlay-tabs">
        {OVERLAY_LABELS.filter(([name]) => overlays.includes(name)).map(([name, labelText]) => (
          <button
            key={name}
            type="button"
            className={overlay === name ? "active" : ""}
            onClick={() => setOverlay(overlay === name ? null : name)}
          >
            {labelText}
          </button>
        ))}
      </div>
      <div className="floor-canvas" ref={hostRef} />
      {error !== null ? <p className="pixel-canvas-error">楼层画面加载失败：{error}</p> : null}
      <FloorTextList items={model.items} />
    </div>
  );
}

/** 覆盖层的数据：按能力清单里的覆盖层名称取对应查询的结果；没有登记时不给数据。 */
function overlayData(
  name: string,
  loop: ProjectLoopResult | null,
  decisions: DecisionList | null,
): Record<string, unknown> | null {
  if (name === "waiting") {
    const entries = (loop?.work_items ?? [])
      .filter((row) => row.status === "waiting_provider" || row.status === "asking")
      .map((row, i) => ({
        department: row.department ?? "",
        text: row.status === "waiting_provider" ? "等待模型服务" : "等待回答",
        waited_sec: row.elapsed_sec ?? 0,
        row: i,
      }));
    for (const _decision of decisions?.decisions ?? []) {
      entries.push({ department: "hall", text: "等待你的决定", waited_sec: 0, row: entries.length });
    }
    return { entries };
  }
  if (name === "flow") return { segments: [] };
  return null;
}

/** 宽度不足时的文字列表：事项、所在部门、第几轮、状态（设计说明第 5.7 节）。 */
function FloorTextList(props: { items: LoopItem[] }): React.JSX.Element {
  if (props.items.length === 0) return <p className="note">项目还没有事项</p>;
  return (
    <ul className="floor-text-list">
      {props.items.map((item) => (
        <li key={item.work_item_id}>
          <strong>{item.sign}</strong>
          <span>{item.department ?? "—"}</span>
          <span>第 {item.round} 轮</span>
          <span>{item.status}</span>
        </li>
      ))}
    </ul>
  );
}

export type { Capabilities };
