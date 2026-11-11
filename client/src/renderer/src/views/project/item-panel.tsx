/**
 * 事项面板（工单 #1708，docs/design/project-organization.md 4.14「事项面板与全部事项」）。
 *
 * 与节点面板、箭头面板同一个位置，一次只开一个：点选事项一行里选中那件事项的标题开它，点节点或箭头换成那个面板。
 * 面板从上到下一共五段，每段写的都是查询给的事实（模型在 item-panel-model.ts）：
 *   1. 状态、第几轮、已用时间与上限、待你决定的问题，每条事实旁有「来源」，点开按位置读那条原始事件；
 *   2. 停了的事项：停止原因、停止说明、上游失败、未能开始的原因、已收下的交付，以及用量到上限的那几项；
 *   3. 循环的每一层一行，点开看这一层凭什么这么判；缺事实的层写「不判定」与缺哪条事实；
 *   4. 等执行槽位时写在等；
 *   5. 三个操作：恢复与动作核实（只在有中断或结果未知的动作时出现）、导出这次运行（一直有）、
 *      取消事项（事项结束以后没有，与时间条上的「停止」是同一条命令 work_item.cancel）。
 * 页面不自己判、不另存一份事实：读的是本页已有的 project.loop、project.overview，再加上 run.loops 与 run.recovery。
 */

import { useMemo, useState, type ReactNode } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  EventAtPosition,
  EventDetailResult,
  EventPositionsResult,
  ProjectLoopResult,
  ProjectOverviewResult,
  RunLoopsResult,
  RunRecoveryResult,
} from "../../api/generated/types.gen";
import { paths } from "../../shell/routing";
import { CommandFeedback, EventDetail, hasCommand, KeyValue, Modal, StopNote, Tag } from "./common";
import { EVENT_POSITION_REASONS, eventKindLabel } from "./floor-text";
import { formatTime } from "./labels";
import {
  CANCEL_CONFIRM_CANCEL,
  CANCEL_CONFIRM_CONFIRM,
  cancelConfirmLines,
  cancelConfirmTitle,
  cancelItemCommand,
  type CancelRequest,
} from "./cancel-text";
import { downloadRunExport, type RunExportOutcome } from "./run-export";
import { itemPanel, type FactSourceView } from "./item-panel-model";
import { type SnapshotState, useCommand, useSnapshot } from "./use-snapshot";

/** 面板打开的是事项本身：与节点、箭头、时序行一起放在同一个开关里，一次只开一个。 */
export const ITEM_PANEL_PICK = "item";
export type ItemPanelPick = typeof ITEM_PANEL_PICK;

/** 点了一条事实的「来源」：这一条来源本身，加上按位置读回来的那条原始事件。 */
interface SourceRead {
  fact: FactSourceView;
  loading: boolean;
  failure: string | null;
  event: EventAtPosition | null;
}

/** 面板里一层一行：层名、实例、已用量与上限、收敛状态，点开看判定依据。 */
const STATE_TONE: Readonly<Record<string, "ok" | "warn" | "danger" | "muted">> = Object.freeze({
  converging: "ok",
  stalled: "warn",
  oscillating: "warn",
  drifting: "warn",
  boundary: "danger",
  undetermined: "muted",
});

export function ItemPanel(props: {
  app: ClientApp;
  projectId: string;
  workItemId: string;
  /** project.loop：状态、第几轮、已用时间与上限 */
  loop: SnapshotState<ProjectLoopResult>;
  /** project.overview：停止说明、上游失败、已收下的交付、标题 */
  overview: SnapshotState<ProjectOverviewResult>;
  onClose: () => void;
  onNavigate: (hash: string) => void;
}) {
  const item = props.loop.data?.work_items.find((row) => row.work_item_id === props.workItemId) ?? null;
  const runId = item?.run_id ?? "";
  // 循环停在哪一层、凭什么判：run.loops 按运行读；有没有中断与结果未知的动作：run.recovery 同一个运行
  const loops = useSnapshot<RunLoopsResult>(
    props.app,
    `page.conversation.item.loops.${props.workItemId}.${runId}`,
    "run.loops",
    { run_id: runId },
    runId === "",
  );
  const recovery = useSnapshot<RunRecoveryResult>(
    props.app,
    `page.conversation.item.recovery.${props.workItemId}.${runId}`,
    "run.recovery",
    { run_id: runId },
    runId === "",
  );
  const panel = useMemo(
    () => itemPanel({
      workItemId: props.workItemId,
      loop: props.loop.data,
      overview: props.overview.data,
      loops: loops.data,
      recovery: recovery.data,
    }),
    [props.workItemId, props.loop.data, props.overview.data, loops.data, recovery.data],
  );
  // 取消：与时间条上的「停止」同一条命令、同一个基准版本，提交以后这一次的提示随状态收起
  const cancel: CancelRequest | null = panel?.actions.cancel ?? null;
  const command = useCommand(props.app, cancel === null ? "" : `${cancel.work_item_id}:${cancel.status}`);
  const [pending, setPending] = useState<CancelRequest | null>(null);
  const [outcome, setOutcome] = useState<RunExportOutcome | null>(null);
  const [exporting, setExporting] = useState(false);
  const [source, setSource] = useState<SourceRead | null>(null);
  const [eventId, setEventId] = useState<string | null>(null);
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    `page.conversation.item.event.${eventId ?? ""}`,
    "event.detail",
    { event_id: eventId ?? "" },
    eventId === null,
  );

  const readSource = (fact: FactSourceView): void => {
    setSource({ fact, loading: true, failure: null, event: null });
    const params: Record<string, unknown> = { project_id: props.projectId, positions: [fact.position] };
    if (runId !== "") {
      params.run_id = runId;
    }
    void props.app
      .queryOne<EventPositionsResult>("event.positions", params)
      .then((result) => {
        const event = (result.data.events ?? []).find((row) => row.position === fact.position) ?? null;
        setSource((current) => (current === null || current.fact.position !== fact.position
          ? current
          : { ...current, event, loading: false }));
      })
      .catch((reason: unknown) => {
        const failure = reason instanceof Error ? reason.message : String(reason);
        setSource((current) => (current === null || current.fact.position !== fact.position
          ? current
          : { ...current, failure, loading: false }));
      });
  };

  const exportRun = (): void => {
    if (runId === "" || panel === null) {
      return;
    }
    setExporting(true);
    void downloadRunExport(props.app, runId, panel.title)
      .then((result) => setOutcome(result))
      .finally(() => setExporting(false));
  };

  if (panel === null) {
    return null;
  }
  const confirm = pending === null ? null : {
    title: cancelConfirmTitle(pending.status),
    lines: cancelConfirmLines(pending.status),
  };
  const card = (props.overview.data?.work_items ?? []).find((row) => row.work_item_id === props.workItemId) ?? null;
  return (
    <section className="y10-cv-panel v20-item-panel" aria-label="事项面板" data-testid="item-panel">
      <button type="button" className="y10-icon-btn y10-cv-close" aria-label="收起" onClick={props.onClose}>
        ×
      </button>
      <h3>
        {panel.title}
        <small> {panel.statusText}</small>
      </h3>
      <KeyValue
        items={panel.head.map((fact) => [
          fact.term,
          <span key={fact.key} className="v20-item-fact">
            {fact.text}
            {fact.source === null ? null : (
              <button
                type="button"
                className="y10-link link v20-item-source"
                data-testid={`item-source-${fact.key}`}
                onClick={() => readSource(fact.source as FactSourceView)}
              >
                来源
              </button>
            )}
          </span>,
        ])}
      />
      {source === null ? null : (
        <div className="y10-source-detail v20-item-source-detail" data-testid="item-source-detail">
          <h4 className="y10-h3 sub">
            位置 {source.fact.position} 上的原始事件（{source.fact.elementLabel} · 来源：{source.fact.sourceLabel}）
          </h4>
          {source.loading ? <p className="y10-note note">正在按位置读取</p> : null}
          {source.failure === null ? null : (
            <p className="y10-note note" role="status">读不出来：{source.failure}</p>
          )}
          {source.event === null ? null : source.event.status !== "available" ? (
            <p className="y10-note note" role="status">
              {EVENT_POSITION_REASONS[source.event.reason ?? ""] ?? "这个位置上没有事件"}
            </p>
          ) : (
            <KeyValue
              items={[
                ["说明", source.event.label ?? "未上报"],
                ["种类", eventKindLabel(source.event.type)],
                ["提出者", source.event.actor_label ?? source.event.department_label ?? "未上报"],
                ["时间", formatTime(source.event.at)],
              ]}
            />
          )}
          {source.event?.event_id === undefined ? null : (
            <button
              type="button"
              className="y10-link link"
              data-testid="item-source-full"
              onClick={() => setEventId(source.event?.event_id ?? null)}
            >
              展开全文
            </button>
          )}
          <button type="button" className="y10-link link" onClick={() => setSource(null)}>收起</button>
        </div>
      )}
      {panel.stop === null ? null : (
        <div className="y10-cv-block v20-item-stop" data-testid="item-stop">
          <KeyValue
            items={[
              ["停止原因", panel.stop.reason === "" ? "没有" : panel.stop.reason],
              [
                "停止说明",
                <StopNote
                  key="stop-note"
                  note={panel.stop.note}
                  kept={card?.kept_delivery ?? null}
                  detail={panel.stop.detail === "" ? null : (card?.stop_detail ?? null)}
                  empty="没有"
                />,
              ],
              ...(panel.stop.startError === "" ? [] : [["未能开始", panel.stop.startError] as [string, ReactNode]]),
              ...(panel.stop.humanAction === "" ? [] : [["可以做的", panel.stop.humanAction] as [string, ReactNode]]),
            ]}
          />
        </div>
      )}
      {panel.limitLines.length === 0 ? null : (
        <div className="y10-cv-block v20-item-limits" data-testid="item-limits">
          <h4 className="y10-h3 sub">用量到了上限</h4>
          <ul className="y10-list">
            {panel.limitLines.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </div>
      )}
      <div className="y10-cv-block v20-item-layers" data-testid="item-layers">
        <h4 className="y10-h3 sub">循环停在哪一层</h4>
        {panel.layers.length === 0 ? <p className="y10-note note">这个事项还没有循环的层。</p> : (
          <ul className="y10-list v20-item-layer-list">
            {panel.layers.map((layer) => (
              <li key={layer.key}>
                <details className="y10-details v20-item-layer" data-testid={`item-layer-${layer.key}`}>
                  <summary>
                    <span className="v20-item-layer-name">{layer.layerLabel} · {layer.instance}</span>
                    <Tag tone={STATE_TONE[layer.state]}>{layer.stateLabel}</Tag>
                    <span className="y10-muted v20-item-layer-used">{layer.used}</span>
                  </summary>
                  <ul className="y10-list">
                    {layer.basis.map((line) => <li key={line}>{line}</li>)}
                  </ul>
                </details>
              </li>
            ))}
          </ul>
        )}
      </div>
      {panel.slots.length === 0 ? null : (
        <ul className="y10-list v20-item-slots" data-testid="item-slots">
          {panel.slots.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}
      <div className="y10-row row-actions v20-item-actions">
        {panel.actions.recovery === null ? null : (
          <button
            type="button"
            className="y10-btn"
            data-testid="item-recovery"
            onClick={() => props.onNavigate(paths.recovery(props.projectId, props.workItemId))}
          >
            {panel.actions.recovery.label}
          </button>
        )}
        <button
          type="button"
          className="y10-btn"
          data-testid="item-export"
          disabled={runId === "" || exporting}
          onClick={exportRun}
        >
          {panel.actions.exportLabel}
        </button>
        {panel.actions.cancel === null || !hasCommand(props.app, "work_item.cancel") ? null : (
          <button
            type="button"
            className="y10-btn danger"
            data-testid="item-cancel"
            disabled={command.busy}
            onClick={() => setPending(panel.actions.cancel)}
          >
            {panel.actions.cancelLabel}
          </button>
        )}
      </div>
      {outcome === null ? null : (
        <p className="y10-note note" role="status" data-testid="item-export-outcome">
          {outcome.ok ? `已导出 ${outcome.fileName}` : `导出失败：${outcome.reason}`}
        </p>
      )}
      <CommandFeedback submitted={command.submitted} problem={command.problem} />
      {confirm === null || pending === null ? null : (
        <Modal title={confirm.title} onClose={() => setPending(null)}>
          {confirm.lines.map((line) => <p key={line} className="y10-note note">{line}</p>)}
          <p className="y10-row">
            <button
              type="button"
              className="y10-btn danger"
              data-testid="item-cancel-confirm"
              disabled={command.busy}
              onClick={() => {
                const body = cancelItemCommand(pending, true);
                setPending(null);
                if (body !== null) {
                  void command.submit("work_item.cancel", body);
                }
              }}
            >
              {CANCEL_CONFIRM_CONFIRM}
            </button>
            <button type="button" className="y10-btn" data-testid="item-cancel-dismiss" onClick={() => setPending(null)}>
              {CANCEL_CONFIRM_CANCEL}
            </button>
          </p>
        </Modal>
      )}
      {eventId === null ? null : detail.error !== null ? (
        <Modal title={`事件 ${eventId}`} onClose={() => setEventId(null)}>
          <p className="y10-note note" role="status">读不出来：{detail.error}</p>
        </Modal>
      ) : (
        <EventDetail eventId={eventId} onClose={() => setEventId(null)} snapshot={detail} />
      )}
    </section>
  );
}
