// 对话线程（工单 #1639，项目的组织设计说明 4.14「项目页是循环图加对话」的交互骨架第 1 至 3 条）。
//
// 一条线程跨多个事项：事项之间一条细线写标题与结果，点标题选事项；已结束的事项默认收起，只露细线与
// 交完成或放行那一条，细线旁「展开对话」看完整的。线程默认只显示你写的、要你决定的、交完成或放行；
// 角色之间的往来折成一行（「工程与产品往来 N 条」），点开才展开，问答里工程回答质检的那一条分事实与解释。
//
// 这里只画，不做判断：每个事项的行由 thread-model 从 project.flow、run.asks 与 decisions.list 推出
// （run.asks 按事项的 run 各读一次；已经收起的事项不读）。要你决定的气泡就地回答，走 decision.answer。

import { useEffect, useMemo, useRef, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { DecisionView, RunAsksResult } from "../../api/generated/types.gen";
import { decisionLinks, missingNoteText } from "../decisions/card-logic";
import { CommandFeedback, hasCommand } from "./common";
import { DECISION_KIND, formatTime, label } from "./labels";
import {
  isEnded, isLongText, itemThread, projectDecisions, shortText,
  type ThreadDecision, type ThreadEntry, type ThreadFlowRecord, type ThreadItemView, type ThreadMessage,
  type ThreadOrganizationChange,
} from "./thread-model";
import { useCommand, useSnapshot } from "./use-snapshot";

/** 线程：一件事项一段，最后放不属于任何事项的决定请求。 */
export function ThreadView(props: {
  app: ClientApp | null;
  items: readonly ThreadItemView[];
  titles: Record<string, string>;
  flow: readonly ThreadFlowRecord[];
  decisions: readonly ThreadDecision[];
  labels: Record<string, string>;
  /** 项目现在的组织改过的历史：事项跑的时候改过，线程里写一句（工单 #1649） */
  organizationChanges?: readonly ThreadOrganizationChange[];
  selected: string;
  /** 已经展开对话的那几件结束事项 */
  opened: Record<string, boolean>;
  onToggleItem: (workItem: string) => void;
  onSelectItem: (workItem: string) => void;
  /** 交完成或放行那一条的「看这一版」：在循环图上打开那条箭头 */
  onLook: (workItem: string, flowId: string) => void;
  /** 折叠行末尾的「在时序图里看」：只看这两个职能的时序图 */
  onSequence: (workItem: string, roles: readonly string[]) => void;
  onNavigate: (hash: string) => void;
  /** 发送一条以后加一：线程滚到最新一条；别的时候不动滚动位置 */
  scrollSignal: number;
}) {
  const boxRef = useRef<HTMLElement | null>(null);
  const scrolled = useRef(false);
  useEffect(() => {
    if (scrolled.current || props.items.length === 0) {
      return;
    }
    const box = boxRef.current;
    if (box !== null) {
      box.scrollTop = box.scrollHeight;
      scrolled.current = true;
    }
  }, [props.items.length]);
  useEffect(() => {
    const box = boxRef.current;
    if (box !== null) {
      box.scrollTop = box.scrollHeight;
    }
  }, [props.scrollSignal]);

  const runnable = props.items.find((item) => item.status === "in_progress" || item.status === "awaiting_initial_prd") ?? null;
  const projectLevel = projectDecisions(props.decisions);
  // 按事项分组一次：线程里每个事项各读自己的那几条，不在每次重画时重新分
  const flowByItem = useMemo(() => {
    const grouped = new Map<string, ThreadFlowRecord[]>();
    for (const record of props.flow) {
      const id = record.work_item_id ?? "";
      grouped.set(id, [...(grouped.get(id) ?? []), record]);
    }
    return grouped;
  }, [props.flow]);
  const decisionsByItem = useMemo(() => {
    const grouped = new Map<string, ThreadDecision[]>();
    for (const decision of props.decisions) {
      const id = decision.work_item_id ?? "";
      grouped.set(id, [...(grouped.get(id) ?? []), decision]);
    }
    return grouped;
  }, [props.decisions]);
  return (
    <section className="y10-th" aria-label="对话线程" data-testid="thread" ref={boxRef}>
      {props.items.length === 0 ? (
        <p className="y10-note">还没有事项。在下面写一句，就开始做。</p>
      ) : props.items.map((item) => (
        <ThreadItem
          key={item.work_item_id}
          app={props.app}
          item={item}
          selected={item.work_item_id === props.selected}
          expanded={isEnded(item) ? props.opened[item.work_item_id] === true : true}
          flow={flowByItem.get(item.work_item_id) ?? []}
          decisions={decisionsByItem.get(item.work_item_id) ?? []}
          titles={props.titles}
          labels={props.labels}
          organizationChanges={props.organizationChanges}
          queuedBehind={item.status === "not_started" && runnable !== null && runnable.work_item_id !== item.work_item_id
            ? props.titles[runnable.work_item_id] ?? "另一件事项" : null}
          onToggle={() => props.onToggleItem(item.work_item_id)}
          onSelect={() => props.onSelectItem(item.work_item_id)}
          onLook={(flowId) => props.onLook(item.work_item_id, flowId)}
          onSequence={(roles) => props.onSequence(item.work_item_id, roles)}
          onNavigate={props.onNavigate}
        />
      ))}
      {projectLevel.length === 0 ? null : (
        <div className="y10-th-project">
          <p className="y10-th-note">不属于某一件事项的决定请求</p>
          {projectLevel.map((decision) => (
            <DecisionBubble key={decision.decision_id} app={props.app} decision={decision} onNavigate={props.onNavigate} />
          ))}
        </div>
      )}
    </section>
  );
}

function ThreadItem(props: {
  app: ClientApp | null;
  item: ThreadItemView;
  selected: boolean;
  expanded: boolean;
  flow: readonly ThreadFlowRecord[];
  decisions: readonly ThreadDecision[];
  titles: Record<string, string>;
  labels: Record<string, string>;
  organizationChanges?: readonly ThreadOrganizationChange[];
  queuedBehind: string | null;
  onToggle: () => void;
  onSelect: () => void;
  onLook: (flowId: string) => void;
  onSequence: (roles: readonly string[]) => void;
  onNavigate: (hash: string) => void;
}) {
  const runId = props.item.run_id ?? "";
  // 答完的询问只在展开时读：收起的事项只露细线与交完成或放行那一条
  const asks = useSnapshot<RunAsksResult>(
    props.app, `page.conversation.asks.${props.item.work_item_id}`, "run.asks", { run_id: runId },
    runId === "" || !props.expanded,
  );
  const entries = useMemo(() => itemThread({
    item: props.item,
    flow: props.flow,
    asks: asks.data?.asks ?? [],
    decisions: props.decisions,
    titles: props.titles,
    labels: props.labels,
    organizationChanges: props.organizationChanges,
    queuedBehind: props.queuedBehind,
    expanded: props.expanded,
  }), [props.item, props.flow, props.decisions, props.titles, props.labels, props.organizationChanges,
    props.queuedBehind, props.expanded, asks.data]);

  return (
    <div className="y10-th-item" data-testid={`thread-item-${props.item.work_item_id}`}>
      {entries.map((entry) => (
        <ThreadRow
          key={entry.key}
          entry={entry}
          selected={props.selected}
          expanded={props.expanded}
          onToggle={props.onToggle}
          onSelect={props.onSelect}
          onLook={props.onLook}
          onSequence={props.onSequence}
          app={props.app}
          onNavigate={props.onNavigate}
        />
      ))}
    </div>
  );
}

function ThreadRow(props: {
  entry: ThreadEntry;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
  onSelect: () => void;
  onLook: (flowId: string) => void;
  onSequence: (roles: readonly string[]) => void;
  app: ClientApp | null;
  onNavigate: (hash: string) => void;
}) {
  const { entry } = props;
  switch (entry.kind) {
    case "sep":
      return (
        <div className={`y10-th-sep${props.selected ? " is-sel" : ""}`}>
          <button type="button" className="y10-th-sep-btn" title="在循环图上画这件" onClick={props.onSelect}>
            {entry.title} · {entry.result}
          </button>
          {entry.ended && entry.expandable ? (
            <button type="button" className="y10-link" onClick={props.onToggle}>
              {props.expanded ? "收起对话" : "展开对话"}
            </button>
          ) : null}
        </div>
      );
    case "you":
      return <YouLine entry={entry} />;
    case "fold":
      return <FoldRow entry={entry} onSequence={props.onSequence} />;
    case "done":
      return <DoneLine entry={entry} onLook={props.onLook} />;
    case "decision":
      return <DecisionBubble app={props.app} decision={entry.decision} onNavigate={props.onNavigate} />;
    case "notice":
      return <p className="y10-th-notice">{entry.text}</p>;
    default:
      return null;
  }
}

/** 你写的话（或给它人的指导）：太长时先折起来，点开看全文。 */
function YouLine(props: { entry: Extract<ThreadEntry, { kind: "you" }> }) {
  const [open, setOpen] = useState(false);
  const folded = isLongText(props.entry.text);
  const text = folded && !open ? shortText(props.entry.text) : props.entry.text;
  return (
    <div className="y10-th-msg is-you">
      <div className="y10-th-meta">
        你 · {formatTime(props.entry.at)}
        <span className="y10-th-tag">{props.entry.tag}</span>
      </div>
      <p className="y10-th-bubble">{text}</p>
      {folded ? (
        <button type="button" className="y10-link" onClick={() => setOpen(!open)}>{open ? "收起" : "展开全文"}</button>
      ) : null}
    </div>
  );
}

/** 角色之间的往来折成的一行：点开才展开；末尾「在时序图里看」只看这两个职能。 */
function FoldRow(props: {
  entry: Extract<ThreadEntry, { kind: "fold" }>;
  onSequence: (roles: readonly string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="y10-th-fold">
      <button
        type="button"
        className="y10-th-fold-head"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {props.entry.label} {props.entry.messages.length} 条
      </button>
      {open ? (
        <ul className="y10-th-fold-body">
          {props.entry.messages.map((message) => <li key={message.key}><FoldMessage message={message} /></li>)}
          {/* 折叠行是读内容的地方：展开以后末尾「在时序图里看」，点开只看这两个职能（设计说明 4.14 交互骨架第 3 条） */}
          {props.entry.roles.length === 2 ? (
            <li className="y10-th-fold-more">
              <button type="button" className="y10-link" onClick={() => props.onSequence(props.entry.roles)}>
                在时序图里看
              </button>
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}

function FoldMessage(props: { message: ThreadMessage }) {
  const prefix = props.message.role === "question" ? `问${props.message.toLabel ?? ""}：`
    : props.message.role === "answer" ? "答：" : "";
  return (
    <div className="y10-th-fold-msg">
      <p><b>{props.message.whoLabel}</b> {prefix}{props.message.text}</p>
      {props.message.facts ? (
        <div className="y10-th-facts">
          <small>事实</small>
          <p>{props.message.facts}</p>
        </div>
      ) : null}
      {props.message.explanation ? (
        <div className="y10-th-why">
          <small>{props.message.explanationNote === null ? "解释" : `解释 · ${props.message.explanationNote}`}</small>
          <p>{props.message.explanation}</p>
        </div>
      ) : null}
    </div>
  );
}

/** 交完成或放行那一条：有「看这一版」，在循环图上打开那条箭头，不另开页面。 */
function DoneLine(props: { entry: Extract<ThreadEntry, { kind: "done" }>; onLook: (flowId: string) => void }) {
  const flowId = props.entry.flowId;
  return (
    <div className={`y10-th-msg ${props.entry.release ? "is-release" : "is-done"}`}>
      <div className="y10-th-meta">{props.entry.whoLabel} · {props.entry.label} · {formatTime(props.entry.at)}</div>
      <p className="y10-th-bubble">
        {props.entry.text}
        {flowId === null ? null : (
          <button type="button" className="y10-link" onClick={() => props.onLook(flowId)}>看这一版</button>
        )}
      </p>
    </div>
  );
}

/** 要你决定的气泡：按钮在气泡里，回答走 decision.answer，回答以后变成已回答。 */
function DecisionBubble(props: {
  app: ClientApp | null;
  decision: ThreadDecision;
  onNavigate: (hash: string) => void;
}) {
  const [note, setNote] = useState("");
  const [noteMissing, setNoteMissing] = useState("");
  const command = useCommand(props.app, `${props.decision.version}/${props.decision.status}`);
  const request = (props.decision.request ?? {}) as Record<string, unknown>;
  const options = (Array.isArray(request.options) ? request.options : [])
    .filter((item): item is { id: string; label: string; note_required?: boolean } =>
      item !== null && typeof item === "object" && typeof (item as { id?: unknown }).id === "string");
  const description = typeof request.description === "string" ? request.description : "";
  const answered = props.decision.status !== "open";
  // 决定请求自己的跳转链接（模型不可用时去模型管理、初始 PRD 的两个工件等），与决定卡片同一份
  const links = decisionLinks(props.decision as unknown as DecisionView);

  const submit = (optionId: string): void => {
    const option = options.find((item) => item.id === optionId);
    if (option === undefined) {
      return;
    }
    const missing = missingNoteText(option, note);
    if (missing !== "") {
      setNoteMissing(missing);
      return;
    }
    setNoteMissing("");
    const trimmed = note.trim();
    void command.submit("decision.answer", {
      decision_id: props.decision.decision_id,
      option: optionId,
      ...(trimmed === "" ? {} : { note: trimmed }),
      base_version: props.decision.version,
    }).then((ok) => {
      if (ok) {
        setNote("");
      }
    });
  };

  return (
    <div className={`y10-th-decide${answered ? " is-answered" : ""}`} data-testid={`thread-decision-${props.decision.decision_id}`}>
      <div className="y10-th-meta">
        {label(DECISION_KIND, props.decision.kind)} · {answered ? "已回答" : "要你决定"} · {formatTime(props.decision.requested_at)}
      </div>
      {description === "" ? null : <p className="y10-th-ask">{description}</p>}
      {answered ? (
        <p className="y10-th-answered" role="status">已回答：{answeredLabel(props.decision, options)}</p>
      ) : (
        <>
          <textarea
            className="y10-textarea"
            aria-label="说明（可选）"
            rows={2}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <div className="y10-th-opts">
            {options.map((option) => (
              <button
                key={option.id}
                type="button"
                className="y10-btn small primary"
                disabled={command.busy || !hasCommand(props.app, "decision.answer")}
                title={option.note_required ? "需要在说明中写明修改意见" : undefined}
                onClick={() => submit(option.id)}
              >
                {option.label}
              </button>
            ))}
          </div>
          {noteMissing === "" ? null : <span className="hint" role="status">{noteMissing}</span>}
          <CommandFeedback submitted={command.submitted} problem={command.problem} />
        </>
      )}
      {links.length === 0 ? null : (
        <div className="y10-th-links">
          {links.map((link) => (
            <button key={link.label} type="button" className="y10-link" onClick={() => props.onNavigate(link.href)}>
              {link.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** 已回答时写选的选项名：取值来自请求给出的选项，不把内部标识写到页面上。 */
function answeredLabel(decision: ThreadDecision, options: readonly { id: string; label: string }[]): string {
  const chosen = decision.answer?.option ?? "";
  return options.find((option) => option.id === chosen)?.label ?? "已回答";
}
