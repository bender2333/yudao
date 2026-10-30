// 概览页的循环画面：把查询结果交给翻译层，把翻译层给出的状态与动作交给楼层画面（工单 #82、#953）。
//
// 这个组件只做连接（画面与播放设计说明第 3 节）：
//   - 同步层的数据（project.loop、decisions.list）与当前事项那次运行的询问链（run.asks）经 translate/floor.ts
//     翻成画面合同的状态与卡片；
//   - 事件流里本项目的事件经翻译层翻成动作，回放期间不播动作；
//   - 打开画面、重新同步、标签页从后台切回与回放拖动都用 jump：直接显示最新状态，不补播；
//   - 画面的回调（回答决定、点击跳转）变成命令。
//
// 页面文字（下方的文字列表、覆盖层按钮条）不属于画面，照旧按查询结果显示。

import { useEffect, useMemo, useRef, useState } from "react";
import type {
  Capabilities, DecisionList, DecisionView, EventObject, ProjectFlowResult, ProjectLoopResult, RunAsksResult,
} from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { newCommandId } from "../../contract/command-id.ts";
import { commandProblemText } from "../../contract/command-problem.ts";
import { createRafClock, type Clock } from "../../pixel/clock";
import { createFloorView, floorTestHooks, type FloorTestHooks, type FloorView } from "../../pixel/floor/view";
import type { DecisionAnswer, DecisionResult } from "../../pixel/floor/card";
import type { FloorModel } from "../../pixel/world/types";
import { LETTER_ANSWERED_TYPE, LETTER_ASKED_TYPE } from "../../pixel/world/types";
import { itemColor } from "../../pixel/world/floor";
import { sortByRequested } from "../decisions/card-logic";
import { DecisionCardList } from "../decisions/card.tsx";
import { floorActions, floorCards, floorState, recoveryOverlay, streamText, toFloorEvent, type FloorEvent } from "../../translate/floor";
import { flowSegmentsOf, type FlowSegment } from "./flow-segments";
import { WORK_ITEM_STATUS, departmentName, label } from "./labels";
import { useSnapshot } from "./use-snapshot";

/** 文字列表里的一行：按查询结果原样写（页面文字不属于画面）。 */
export interface FloorTextRow {
  work_item_id: string;
  sign: string;
  kind: string;
  color_index: number;
  department: string | null;
  round: number;
  status: string;
}

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

/**
 * 楼层画面要读询问链的那次运行：聚焦的事项优先，否则进行中的一项（与概览页「当前事项」同一口径）。
 * 没有这样的运行时为空串，页面据此不发查询。
 */
export function asksRunId(loop: ProjectLoopResult | null, focus: string | null): string {
  const rows = loop?.work_items ?? [];
  const picked = (focus === null ? undefined : rows.find((row) => row.work_item_id === focus))
    ?? rows.find((row) => row.status === "in_progress" || row.status === "awaiting_initial_prd");
  return picked?.run_id ?? "";
}

/** 文字列表里的行：事项本身的状态，不是画面的状态名（工单 #900）。 */
export function floorTextRows(loop: ProjectLoopResult | null): FloorTextRow[] {
  return (loop?.work_items ?? []).map((row, index) => ({
    work_item_id: row.work_item_id,
    sign: row.sign,
    kind: row.kind,
    color_index: row.color_index ?? index + 1,
    department: row.department,
    round: row.round,
    status: row.status,
  }));
}

/**
 * 把事件流里的事件转成像素层的事件形状（只保留本项目的事件）。
 * 楼与部门房间的画面（画面 4、5）还在用 v10 的形状，由它们各取所需；楼层自己不再经过这里，
 * 它把同一份事件交给翻译层（translate/floor.ts）。
 */
export function floorEventOf(event: EventObject, projectId: string): PixelFloorEventBridge | null {
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

/** 转移给像素层的旧形状（楼与房间的画面用；楼层自己用翻译层的形状）。 */
export interface PixelFloorEventBridge {
  type: string;
  event_id?: string | null;
  department?: string | null;
  role?: string | null;
  tool?: string | null;
  label?: string | null;
  work_item_id?: string | null;
  project_id?: string | null;
  position?: number;
  payload?: Record<string, unknown>;
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
  // 回放到过去的时间点时不显示决定请求（设计说明第 5.5 节、原型 v13 第 1 节）
  const decisions = useSnapshot<DecisionList>(props.app, "page.decisions", "decisions.list", {
    project_id: props.projectId, status: ["open"],
  }, replaying);
  // 当前事项那次运行的询问链（run.asks，工单 #903）：未回答的询问画在传信管的出口。
  // 回放不查：这个查询不带位置，把最新的询问画到过去的画面上会讲反（画面诚实性 H7）
  const runId = useMemo(() => asksRunId(loop.data, props.workItemId), [loop.data, props.workItemId]);
  const asks = useSnapshot<RunAsksResult>(props.app, "page.loop.asks", "run.asks", { run_id: runId },
    replaying || runId === "");
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

  // 建立画面：画布挂在宿主元素上，时钟与事件流分别订阅
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
        // 打开画面：直接显示最新的状态，不补播（查询可能早于画面就绪）
        if (modelRef.current) view.jump(modelRef.current);
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

  // 查询结果经翻译层翻成楼层状态（回到过去的时间点时不显示决定请求，部门按一个部门一个角色画）。
  // 询问链是另一处查询：状态的位置取两处快照里新的一个（与楼的翻译层同一做法）
  const model = useMemo(
    () => floorState({
      position: Math.max(loop.position, asks.position),
      loop: loop.data,
      asks: asks.data === null ? null : { [runId]: asks.data.asks },
      roles: null,
      slots: null,
      ops: null,
      machines: null,
      interrupted: false,
      focus: props.workItemId,
    }),
    [loop.position, asks.position, loop.data, asks.data, runId, props.workItemId],
  );

  // 决定卡片是实时内容：到了就贴上大厅的板（回放期间不显示）
  const cards = useMemo(
    () => floorCards(replaying ? null : decisions.data?.decisions ?? null, (decision) => ({
      projectName: decision.project_id ?? "",
      workItemTitle: titleOf(model, decision.work_item_id),
    }), Date.now()),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [decisions.data, replaying, model],
  );

  // 每次查询结果到达：交给播放时间线（状态等它之前的动作演完再上画面）
  useEffect(() => {
    modelRef.current = model;
    // 直播交给播放时间线（状态等它之前的动作演完再上画面），回放直接显示那个位置的状态（不播动作）
    if (replaying) viewRef.current?.jump(model);
    else viewRef.current?.setState(model);
  }, [model, replaying]);

  // 回放拖动时间轴：直接显示那个位置的状态，不播动作（设计说明第 5.2 节）
  const atKey = at === null ? "live" : String(at);
  useEffect(() => {
    if (modelRef.current) viewRef.current?.jump(modelRef.current);
  }, [atKey]);

  // 决定卡片：实时内容，到了就显示
  useEffect(() => {
    viewRef.current?.setDecisions(cards);
  }, [cards]);

  // 事件只决定动作：翻译层把事件翻成楼层的动作，时间线按声明演出；回放期间不播动作
  useEffect(() => {
    if (replaying) return;
    const off = props.app.subscribeEvents((event) => {
      const floorEvent = toFloorEvent(event);
      if (floorEvent.project_id !== null && floorEvent.project_id !== props.projectId) return;
      const stream = streamText(floorEvent);
      if (stream) {
        viewRef.current?.stream({ room: stream.room, role: stream.role }, stream.text);
        return;
      }
      for (const action of floorActions(floorEvent)) viewRef.current?.play(action);
    });
    return off;
  }, [props.app, props.projectId, replaying]);

  // 重新同步：画面直接回到查询给出的状态，不补播
  useEffect(() => {
    const jumpLatest = (): void => {
      if (modelRef.current) viewRef.current?.jump(modelRef.current);
    };
    const off = props.app.subscribeResync(jumpLatest);
    // 标签页从后台切回：浏览器在后台暂停了动画，队里可能积了几分钟的事件，直接跳到最新（设计说明第 5.2 节）
    const onVisible = (): void => {
      if (document.visibilityState === "visible") jumpLatest();
    };
    document.addEventListener("visibilitychange", onVisible);
    if (import.meta.env.DEV) {
      resyncRef.current = jumpLatest;
    }
    return () => {
      off();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [props.app]);

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
  const rows = useMemo(() => floorTextRows(loop.data), [loop.data]);

  return (
    // 覆盖层按钮条是画面上方一条独立的深色条（原型 v13 ui/scenes.js mountFloor）：不压在画面上
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
      <FloorTextList rows={rows} decisions={openDecisions} app={props.app} />
    </div>
  );
}

/** 事项的标题（决定卡片里的「事项」一栏用）。 */
function titleOf(model: FloorModel, workItemId: string | null): string {
  if (!workItemId) return "";
  return model.items.find((it) => it.work_item_id === workItemId)?.sign ?? "";
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
  // 「恢复」覆盖层的数据在翻译层写好（工单 #1186）：这里只把查询结果交过去，不在这里写事项与状态的对应
  if (name === "recovery") return recoveryOverlay(loop);
  return null;
}

/** 画面下方的文字列表：默认折叠（原型 v13 ui/scenes.js 的 floorList），每一行是事项的色点、
 *  标题、中文部门名、轮次与中文状态；等待回答的决定请求在列表里用页面卡片回答。 */
function FloorTextList(props: {
  rows: FloorTextRow[];
  decisions: DecisionView[];
  app: ClientApp;
}): React.JSX.Element {
  const now = Date.now();
  const titleOfItem = (workItemId: string | null): string =>
    workItemId ? props.rows.find((it) => it.work_item_id === workItemId)?.sign ?? "" : "";
  return (
    <>
      <details className="y10-scene-list floor-text-list">
        <summary>文字列表</summary>
        {props.rows.length === 0 ? <p className="y10-note note">项目还没有事项</p> : (
          <ul>
            {props.rows.map((item) => (
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
          names={(decision) => ({ projectName: decision.project_id ?? "", workItemTitle: titleOfItem(decision.work_item_id) })}
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

export type { Capabilities, FloorEvent };
