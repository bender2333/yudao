// 部门工作间检查区的步骤时间线（工单 #1235，应用层与接口层 docs/design/app-and-interface.md「查询清单」 run.steps）：
// 一个激活一个格，每一步一块；块里按「模型的思考」「模型说的话」「动作与回执」的顺序排，
// 回执单独一行、底色与前面几块不同。每一步的标题与标记、折叠时的预览来自 step-timeline.ts
// 的纯函数；这个文件只做排版与取数（run.steps 与展开全文时的 event.detail）。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  ActionView,
  EventDetailResult,
  RunRecoveryResult,
  RunStepView,
  RunStepsResult,
  StepText,
} from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import { actionKind, actionRow, toolOutput, type ActionRowView, type ExternalSourceRefView } from "./action-table.ts";
import { Empty, EventDetail, Modal, Tag } from "./common";
import { RunningBackgroundCommands } from "./department.tsx";
import { ExternalSource } from "./external-source.tsx";
import { formatTime } from "./labels";
import { useSnapshot } from "./use-snapshot";
import {
  BLOCK_TITLES,
  ENCRYPTED_REASONING,
  NO_ACTIVATION,
  NO_RUN,
  actionLines,
  activationLabel,
  discardedMark,
  foldedText,
  hasMoreText,
  lengthLabel,
  selectedActivation,
  stepBlocks,
  stepTitle,
  unassignedBlock,
} from "./step-timeline.ts";

// 一个事项下本部门的步骤时间线：页签最上面是正在运行的后台命令，下面依次是激活选择、步骤与
// 未归到步骤的动作。展开与折叠的状态以事件编号为键存在组件里，数据刷新（新事件到达）时保持；
// 离开页面以后不保留（组件卸载，状态一起丢掉）
export function StepTimeline(props: { app: ClientApp; runId: string | null; department: string }) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [openEvent, setOpenEvent] = useState<string | null>(null);
  const params: Record<string, unknown> = { run_id: props.runId ?? "", department: props.department };
  if (chosen !== null) {
    params["activation_id"] = chosen;
  }
  const steps = useSnapshot<RunStepsResult>(
    props.app,
    chosen === null ? "page.dept.steps" : `page.dept.steps.${chosen}`,
    "run.steps",
    params,
    props.runId === null,
  );
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    openEvent ? `page.dept.steps.event.${openEvent}` : "page.dept.steps.event.none",
    "event.detail",
    { event_id: openEvent ?? "" },
    openEvent === null,
  );
  // 结果未知的动作交还给模型的内容（工单 #238）：恢复查询里每个动作一条，按动作编号对到动作行上
  const recovery = useSnapshot<RunRecoveryResult>(
    props.app,
    "page.dept.steps.recovery",
    "run.recovery",
    { run_id: props.runId ?? "" },
    props.runId === null,
  );
  const returned = new Map<string, string>();
  for (const entry of recovery.data?.unknown_actions ?? []) {
    if (entry.returned !== null && entry.returned !== "") {
      returned.set(entry.action_id, entry.returned);
    }
  }
  const toggle = (eventId: string) => {
    setExpanded((current) => ({ ...current, [eventId]: current[eventId] !== true }));
  };

  if (props.runId === null) {
    return <Empty text={NO_RUN} />;
  }
  if (steps.data === null) {
    if (steps.loading) {
      return <p className="y10-note note">正在读取这一轮的步骤</p>;
    }
    return <Empty text={steps.error === null ? NO_RUN : readFailureText(steps.error)} />;
  }
  const data = steps.data;
  const selected = selectedActivation(data, chosen);
  const unassigned = unassignedBlock(data);
  return (
    <>
      <RunningBackgroundCommands commands={data.background_commands} />
      {selected === null ? <Empty text={NO_ACTIVATION} /> : (
        <>
          <ActivationStrip result={data} selected={selected.activation_id} onSelect={setChosen} />
          <ol className="y10-ws-steps">
            {data.steps.map((step) => (
              <li key={step.step_id} className="y10-ws-step">
                <StepHeader step={step} />
                {stepBlocks(step).map((block) => block.kind === "actions" ? (
                  <ActionList key="actions" app={props.app} actions={block.actions} returned={returned}
                              onOpenEvent={setOpenEvent} />
                ) : (
                  <section key={block.kind} className={`y10-ws-step-block is-${block.kind}`}>
                    <h3 className="y10-h3 sub">{BLOCK_TITLES[block.kind]}</h3>
                    {block.items.map((item) => (
                      <TextItem
                        key={item.event_id}
                        app={props.app}
                        kind={block.kind}
                        item={item}
                        expanded={expanded[item.event_id] === true}
                        onToggle={() => toggle(item.event_id)}
                      />
                    ))}
                  </section>
                ))}
              </li>
            ))}
          </ol>
          {unassigned === null ? null : (
            <section className="y10-ws-step-block is-unassigned">
              <h3 className="y10-h3 sub">{unassigned.title}</h3>
              <ActionList app={props.app} actions={unassigned.actions} returned={returned}
                          onOpenEvent={setOpenEvent} />
            </section>
          )}
        </>
      )}
      {openEvent ? (
        <EventDetail eventId={openEvent} onClose={() => setOpenEvent(null)} snapshot={detail} />
      ) : null}
    </>
  );
}

// 一步的标题行：「第 N 步」、请求时间，以及被丢弃的调用尝试的标记
function StepHeader(props: { step: RunStepView }) {
  const mark = discardedMark(props.step);
  return (
    <header className="y10-ws-step-head">
      <strong>{stepTitle(props.step)}</strong>
      <span className="y10-muted">{formatTime(props.step.requested_at)}</span>
      {mark === null ? null : <Tag>{mark}</Tag>}
    </header>
  );
}

// 激活选择：每个激活一格，默认选中最近一次；点其他格用那个编号重新取步骤
function ActivationStrip(props: {
  result: RunStepsResult;
  selected: string;
  onSelect: (activationId: string) => void;
}) {
  return (
    <div className="y10-ws-activations" role="tablist" aria-label="这一轮的激活">
      {props.result.activations.map((activation, index) => {
        const active = activation.activation_id === props.selected;
        return (
          <button
            key={activation.activation_id}
            type="button"
            role="tab"
            aria-selected={active}
            className={`y10-ws-activation${active ? " is-active active" : ""}`}
            onClick={() => props.onSelect(activation.activation_id)}
          >
            {activationLabel(activation, index)}
          </button>
        );
      })}
    </div>
  );
}

// 一段可读文字：思考默认折叠（预览前两行与字数），点开以后读取全文；读不出来时照实说明，不能展开
function TextItem(props: {
  app: ClientApp;
  kind: "thinking" | "saying";
  item: StepText;
  expanded: boolean;
  onToggle: () => void;
}) {
  if (!props.item.readable) {
    return <p className="y10-ws-step-text y10-muted">{ENCRYPTED_REASONING}</p>;
  }
  const collapsed = props.kind === "thinking" && !props.expanded;
  return (
    <div className="y10-ws-step-text">
      {collapsed ? <p className="y10-ws-folded">{foldedText(props.item)}</p> : (
        <FullText
          app={props.app}
          eventId={props.item.event_id}
          field={props.kind === "thinking" ? "reasoning_text" : "message_text"}
          fallback={foldedText(props.item)}
        />
      )}
      <div className="y10-ws-step-text-foot">
        <span className="y10-muted">{lengthLabel(props.item)}</span>
        {props.kind === "thinking" || hasMoreText(props.item) ? (
          <button type="button" className="y10-link link" onClick={props.onToggle}>
            {collapsed ? "展开全文" : "收起"}
          </button>
        ) : null}
      </div>
    </div>
  );
}

// 展开时才请求这条事件的全文（一个块一次），取不到时先显示预览
function FullText(props: {
  app: ClientApp;
  eventId: string;
  field: "reasoning_text" | "message_text";
  fallback: string;
}) {
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    `page.dept.steps.full.${props.eventId}.${props.field}`,
    "event.detail",
    { event_id: props.eventId },
    false,
  );
  const value = detail.data === null ? null : detail.data.artifacts[props.field];
  if (detail.error !== null) {
    return <p className="y10-note note">{readFailureText(detail.error)}</p>;
  }
  if (typeof value !== "string" || value === "") {
    return <p className="y10-ws-folded">{props.fallback}</p>;
  }
  return <div className="y10-ws-fulltext">{value}</div>;
}

// 动作列表：每个动作两行。其余工具的第一行是工具名、命令原文与状态词，第二行是主机回执
// （结果、输出引用、时间）；取回与 MCP 调用的第一行是类型、目标与状态，第二行是结果、耗时、
// 外部来源的链接与时间，结果未知时写交还给模型的内容（工单 #238）
function ActionList(props: {
  app: ClientApp;
  actions: ActionView[];
  returned: ReadonlyMap<string, string>;
  onOpenEvent: (eventId: string) => void;
}) {
  return (
    <ul className="y10-ws-acts">
      {props.actions.map((action) => (
        <ActionItem
          key={action.action_id}
          app={props.app}
          action={action}
          returned={props.returned.get(action.action_id) ?? ""}
          onOpenEvent={props.onOpenEvent}
        />
      ))}
    </ul>
  );
}

// 一个动作两行。取回与 MCP 调用的结果工件只对 MCP 读一次（event.detail 的 artifacts.output）：
// 服务器与工具的原名、耗时与外部来源的引用在它里面；取回的回执自带这些字段，不用再读
function ActionItem(props: {
  app: ClientApp;
  action: ActionView;
  returned: string;
  onOpenEvent: (eventId: string) => void;
}) {
  const kind = actionKind(props.action);
  const eventId = props.action.receipt === null ? "" : props.action.receipt.event_id;
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    `page.dept.steps.tool.${props.action.action_id}`,
    "event.detail",
    { event_id: eventId },
    eventId === "" || kind !== "mcp",
  );
  const [source, setSource] = useState<ExternalSourceRefView | null>(null);
  if (kind !== "other") {
    const row = actionRow(props.action, {
      returned: props.returned,
      output: kind === "mcp" ? toolOutput(detail.data?.artifacts) : null,
    });
    return (
      <li className={`y10-ws-act is-${props.action.status} is-${kind}`}>
        <div className="y10-ws-act-line">
          <strong className="y10-ws-act-tool">{row.typeName}</strong>
          {row.target === "" ? null : (
            <code className="y10-code y10-ws-act-target">{row.target}</code>
          )}
          <span className="y10-ws-act-status">{row.statusName}</span>
        </div>
        <div className="y10-ws-receipt">
          <span className="y10-ws-receipt-label">{receiptLabel(row)}</span>
          <span className="y10-ws-receipt-text">
            {row.returnedText === "" ? row.summaryText : row.returnedText}
          </span>
          <span className="y10-muted">耗时：{row.durationText}</span>
          {row.external === null ? null : (
            <button
              type="button"
              className="y10-link link"
              onClick={() => setSource(row.external)}
            >
              查看外部来源
            </button>
          )}
          <button
            type="button"
            className="y10-link link"
            disabled={eventId === ""}
            onClick={() => props.onOpenEvent(eventId)}
          >
            {formatTime(props.action.created_at)}
          </button>
        </div>
        {source === null ? null : (
          <Modal title="外部来源" onClose={() => setSource(null)}>
            <ExternalSource app={props.app} source={source} />
          </Modal>
        )}
      </li>
    );
  }
  const lines = actionLines(props.action);
  return (
    <li className={`y10-ws-act is-${props.action.status}`}>
      <div className="y10-ws-act-line">
        <strong className="y10-ws-act-tool">{lines.tool}</strong>
        {lines.command === "" ? null : (
          <code className="y10-code y10-ws-act-command">{lines.command}</code>
        )}
        <span className="y10-ws-act-status">{lines.status}</span>
      </div>
      <div className="y10-ws-receipt">
        <span className="y10-ws-receipt-label">主机回执</span>
        <span className="y10-ws-receipt-text">{lines.receipt}</span>
        <span className="y10-muted">输出引用：{lines.output}</span>
        <button
          type="button"
          className="y10-link link"
          disabled={eventId === ""}
          onClick={() => props.onOpenEvent(eventId)}
        >
          {lines.time}
        </button>
      </div>
    </li>
  );
}

// 第二行的标题：交还的内容、拒绝原因与主机回执三选一
function receiptLabel(row: ActionRowView): string {
  if (row.returnedText !== "") {
    return "交还给模型的内容";
  }
  return row.statusName === "被拒绝" ? "拒绝原因" : "主机回执";
}
