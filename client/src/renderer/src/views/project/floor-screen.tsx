// 概览页的循环画面：把查询结果（project.loop 加上部门角色列表与决定请求）交给楼层画面，
// 把事件流里本项目的事件变成动作，按能力清单显示覆盖层（工单 #82、设计说明第 5.2 至 5.7 节）。
//
// 状态以查询为准：每次查询结果到达都重新 setModel；事件只决定动作的起点。
// 断线重连或收到 resync 以后画面回到查询给出的状态，不补播已经播放过的动作。

import { useEffect, useMemo, useRef, useState } from "react";
import type { Capabilities, DecisionList, DecisionView, EventObject, ProjectFlowResult, ProjectLoopResult, WorkItemLoop } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { newCommandId } from "../../contract/command-id.ts";
import { commandProblemText } from "../../contract/command-problem.ts";
import { createRafClock, type Clock } from "../../pixel/clock";
import { createFloorView, floorTestHooks, type FloorTestHooks, type FloorView } from "../../pixel/floor/view";
import type { DecisionAnswer, DecisionResult } from "../../pixel/floor/card";
import type { FloorModel, LoopItem, PixelFloorEvent } from "../../pixel/world/types";
import { LETTER_ANSWERED_TYPE, LETTER_ASKED_TYPE } from "../../pixel/world/types";
import { itemColor } from "../../pixel/world/floor.ts";
import { face, sortByRequested } from "../decisions/card-logic";
import { DecisionCardList } from "../decisions/card.tsx";
import { flowSegmentsOf, type FlowSegment } from "./flow-segments";
import { WORK_ITEM_STATUS, departmentName, label } from "./labels";
import { useSnapshot } from "./use-snapshot";

/** 画面里的事项：project.loop 的行加上队列位置与等待模型服务的时间。 */
type LoopRow = WorkItemLoop & { queue_pos?: number; waiting_provider_sec?: number };

export interface FloorScreenProps {
  app: ClientApp;
  projectId: string;
  workItemId: string | null;
  /** 回放位置（全局位置）：不为 null 时 project.loop 按位置带 at 读取；回放期间按一个部门一个角色画，不显示决定请求。 */
  at?: number | null;
}

/** 覆盖层的名称与中文标签（按能力清单显示）。 */
const OVERLAY_LABELS: [string, string][] = [
  ["flow", "流转"],
  ["waiting", "等待"],
  ["recovery", "恢复"],
  ["context_usage", "上下文用量"],
  ["semantic_records", "语义记录"],
];

/** 把查询结果组装成楼层画面数据：事项、角色列表、决定请求（纯文字版本）、执行槽位与运维数据。 */
export function floorModelOf(input: {
  loop: ProjectLoopResult | null;
  workspaces: Record<string, { roles?: { id: string; name: string; kind: string; status: string }[] }>;
  decisions: DecisionView[] | null;
  slots: { total: number; used: number } | null;
  ops: { version?: string; fault?: boolean; auto_repair_stopped?: boolean } | null;
  machines: { id: string; name: string; actions: number; unknown?: boolean; online?: boolean }[] | null;
  interrupted: boolean;
  now?: number;
}): FloorModel {
  const items: LoopItem[] = (input.loop?.work_items ?? []).map((row, index) => ({
    ...(row as LoopRow),
    color_index: row.color_index ?? index + 1,
  }));
  const roles: Record<string, { id: string; name: string; kind: string; status: string }[]> = {};
  for (const [department, workspace] of Object.entries(input.workspaces)) {
    if (workspace.roles && workspace.roles.length) roles[department] = workspace.roles;
  }
  const now = input.now ?? Date.now();
  // 决定请求的画面内容（纯文字版本，与页面卡片同一份材料）：事项标题取本项目事项表的 sign，
  // 取不到时不写事项标识（工单 #802）
  const titleOf = (workItemId: string | null): string =>
    workItemId ? items.find((it) => it.work_item_id === workItemId)?.sign ?? "" : "";
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
    decisions: (input.decisions ?? [])
      .filter((d) => d.status === "open")
      .map((d) => face(d, now, { projectName: d.project_id ?? "", workItemTitle: titleOf(d.work_item_id) })),
  };
}

/** 把事件流里的事件转成楼层画面的事件（只保留本项目的事件）。 */
export function floorEventOf(event: EventObject, projectId: string): PixelFloorEvent | null {
  // 事件的公共字段（ADR-0019 的事件信封）：项目、部门、角色、说明与载荷都是登记在接口合同里的。
  if (event.project_id !== null && event.project_id !== projectId) return null;
  const raw = event.payload as unknown as Record<string, unknown>;
  let type: string = event.type;
  let payload = raw;
  let eventDept: string | null = event.department;
  if (event.type === "ask_started") {
    const requester = typeof raw?.requester === "string" ? raw.requester : null;
    const recipient = typeof raw?.recipient === "string" ? raw.recipient : null;
    if (!requester || !recipient) return null;
    type = LETTER_ASKED_TYPE;
    payload = { ...raw, from: requester, to: recipient };
    if (!eventDept) eventDept = requester;
  } else if (event.type === "ask_answered") {
    const requester = typeof raw?.requester === "string" ? raw.requester : null;
    const recipient = typeof raw?.recipient === "string" ? raw.recipient : null;
    if (!requester || !recipient) return null;
    type = LETTER_ANSWERED_TYPE;
    payload = { ...raw, from: recipient, to: requester };
    if (!eventDept) eventDept = recipient;
  }
  const toolVal = typeof payload?.tool === "string" ? payload.tool : typeof payload?.name === "string" ? payload.name : null;
  return {
    type,
    event_id: event.event_id,
    department: eventDept,
    role: event.role,
    // 工具类事件的工具名写在载荷的 name 字段（真实系统的 tool_started/tool_called），说话目录按 tool 取
    tool: toolVal,
    label: event.label,
    work_item_id: event.work_item_id,
    project_id: event.project_id,
    position: event.position,
    payload,
  };
}

/** 循环画面：画布、覆盖层切换、窄屏文字列表与决定卡片。 */
export function FloorScreen(props: FloorScreenProps): React.JSX.Element {
  const at = props.at ?? null;
  const replaying = at !== null;
  const loop = useSnapshot<ProjectLoopResult>(props.app, "page.loop", "project.loop", {
    project_id: props.projectId,
    work_item: props.workItemId,
    ...(at === null ? {} : { at }),
  });
  // 回放到过去的时间点时不显示决定请求（设计说明第 5.5 节、原型 v10 第 8 节）
  const decisions = useSnapshot<DecisionList>(props.app, "page.decisions", "decisions.list", {
    project_id: props.projectId, status: ["open"],
  }, replaying);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<FloorView | null>(null);
  const modelRef = useRef<FloorModel | null>(null);
  const clockRef = useRef<Clock | null>(null);
  const resyncRef = useRef<(() => void) | null>(null);
  const decideRef = useRef<((payload: DecisionAnswer) => Promise<DecisionResult>) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<string | null>(null);
  const capabilities = props.app.currentCapabilities;

  // 画面内的回答：走与页面卡片同一条命令 decision.answer，带上决定的版本与说明；拒绝时把原因交给卡片
  decideRef.current = async (payload) => {
    const outcome = await props.app.command("decision.answer", {
      command_id: newCommandId(),
      decision_id: payload.decision_id,
      option: payload.option,
      ...(payload.note === "" ? {} : { note: payload.note }),
      base_version: payload.base_version,
    });
    if (outcome.ok) return { accepted: true, message: "" };
    return { accepted: false, message: commandProblemText(outcome.problem) };
  };

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
        const view = await createFloorView({
          host,
          clock,
          // 说明栏的输入框加在画布所在的容器里（画面里的横线纸上叠一个透明的输入框）
          cardHost: host,
          onDecide: async (payload) => {
            const decide = decideRef.current;
            if (!decide) throw new Error("画面还没有接上回答命令");
            return decide(payload);
          },
          onGo: (target) => {
            window.location.hash = target.startsWith("#") ? target.slice(1) : target;
          },
        });
        if (cancelled) {
          view.destroy();
          return;
        }
        viewRef.current = view;
        // 画面建立以后立刻用当前的数据配置它：查询可能早于画面就绪，之后数据不再变化时不会再有 setModel
        if (modelRef.current) view.setModel(modelRef.current);
        // 端到端测试经这个入口读取画面的当前状态（只读的检查入口）
        (window as unknown as { __floorViewForTest?: FloorTestHooks }).__floorViewForTest = floorTestHooks(view, () => resyncRef.current?.());
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
      // 回放期间不显示决定请求，部门按一个部门一个角色画（设计说明第 5.5 节）
      decisions: replaying ? null : decisions.data?.decisions ?? null,
      slots: null,
      ops: null,
      machines: null,
      interrupted: false,
    }),
    [loop.data, decisions.data, replaying],
  );

  // 每次查询结果到达：状态以查询为准
  useEffect(() => {
    modelRef.current = model;
    viewRef.current?.setModel(model);
  }, [model]);

  // 事件只决定动作的起点；回放期间不按事件流更新画面（设计说明第 4.1 节）
  useEffect(() => {
    if (replaying) return;
    const off = props.app.subscribeEvents((event) => {
      const floorEvent = floorEventOf(event, props.projectId);
      if (floorEvent) viewRef.current?.playEvent(floorEvent);
    });
    return off;
  }, [props.app, props.projectId, replaying]);

  // 重新同步：画面回到查询给出的状态，不补播
  useEffect(() => {
    const off = props.app.subscribeResync(() => {
      viewRef.current?.setModel(model);
    });
    // 端到端测试触发一次重新同步（只在开发构建里暴露）
    if (import.meta.env.DEV) {
      resyncRef.current = () => viewRef.current?.setModel(model);
    }
    return off;
  }, [props.app, model]);

  useEffect(() => {
    viewRef.current?.focus(props.workItemId);
  }, [props.workItemId]);

  // 流转查询：覆盖层按其 segments 渲染，画面与下方文字列表共用同一份查询结果
  const flow = useSnapshot<ProjectFlowResult>(props.app, "page.loop.flow", "project.flow", {
    project_id: props.projectId,
  });
  const flowSegments = useMemo(() => flowSegmentsOf(flow.data?.records ?? null), [flow.data]);
  useEffect(() => {
    viewRef.current?.setOverlay(overlay, overlay === null ? null : overlayData(overlay, loop.data, decisions.data, flowSegments));
  }, [overlay, loop.data, decisions.data, flowSegments]);

  const overlays = (capabilities?.overlays ?? []).map((o) => o.name);
  // 文字列表里的决定请求：与画面同源的查询结果，按发出时间排列
  const openDecisions = useMemo(
    () => sortByRequested((decisions.data?.decisions ?? []).filter((d) => d.status === "open")),
    [decisions.data],
  );

  return (
    // 覆盖层按钮条是画面上方一条独立的深色条（原型 v10 scenes.js mountFloor）：不压在画面上
    <div className="floor-screen">
      <div className="y10-scene y10-floor-wrap">
        <div className="y10-overlay-bar floor-overlay-tabs" role="group" aria-label="覆盖层">
          {OVERLAY_LABELS.filter(([name]) => overlays.includes(name)).map(([name, labelText]) => (
            <button
              key={name}
              type="button"
              className={`y10-seg-btn${overlay === name ? " is-on active" : ""}`}
              onClick={() => setOverlay(overlay === name ? null : name)}
            >
              {labelText}
            </button>
          ))}
        </div>
        <div className="floor-canvas" ref={hostRef} />
      </div>
      {error !== null ? <p className="pixel-canvas-error">楼层画面加载失败：{error}</p> : null}
      <FloorTextList items={model.items} decisions={openDecisions} app={props.app} />
    </div>
  );
}

/** 覆盖层的数据：按能力清单里的覆盖层名称取对应查询的结果；没有登记时不给数据。 */
function overlayData(
  name: string,
  loop: ProjectLoopResult | null,
  decisions: DecisionList | null,
  flowSegments: FlowSegment[],
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
  if (name === "flow") return { segments: flowSegments };
  return null;
}

/** 画面下方的文字列表：默认折叠（原型 v10 scenes.js floorList），每一行是事项的色点、
 *  标题、中文部门名、轮次与中文状态；等待回答的决定请求在列表里用页面卡片回答。 */
function FloorTextList(props: {
  items: LoopItem[];
  decisions: DecisionView[];
  app: ClientApp;
}): React.JSX.Element {
  const now = Date.now();
  const titleOf = (workItemId: string | null): string =>
    workItemId ? props.items.find((it) => it.work_item_id === workItemId)?.sign ?? "" : "";
  return (
    <>
      <details className="y10-scene-list floor-text-list">
        <summary>文字列表</summary>
        {props.items.length === 0 ? <p className="y10-note note">项目还没有事项</p> : (
          <ul>
            {props.items.map((item) => (
              <li key={item.work_item_id}>
                <span className="y10-dot-color" style={{ "--c": itemColor(item) } as React.CSSProperties} />
                <strong>{item.sign}</strong>
                <span>{item.department === null || item.department === "" ? "大厅" : departmentName(item.department)}</span>
                <span>第 {item.round} 轮</span>
                <span>{label(WORK_ITEM_STATUS, item.status)}</span>
                {item.kind === "onboarding" ? <span className="y10-tag tag">建档</span> : null}
              </li>
            ))}
          </ul>
        )}
        {/* 等待回答的决定请求：与大厅的板同源，用页面卡片，可以同样回答（设计说明第 9 节） */}
        <DecisionCardList
          app={props.app}
          decisions={props.decisions}
          now={now}
          names={(decision) => ({ projectName: decision.project_id ?? "", workItemTitle: titleOf(decision.work_item_id) })}
          onNavigate={(hash) => {
            window.location.hash = hash.startsWith("#") ? hash.slice(1) : hash;
          }}
          viewId="floor.decisions"
          emptyText="没有等待回答的决定请求"
        />
      </details>
    </>
  );
}

export type { Capabilities };
