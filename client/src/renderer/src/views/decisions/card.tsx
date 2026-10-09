// 决定卡片（原型 v8 设计说明第 6 节，工单 #175）：首页与项目页面共用。
// 卡片头写明种类、所属的项目与事项、已经等待的时长、挡住的对象；材料按决定种类整理；
// 回答使用决定请求给出的选项与一段说明，经 decision.answer 提交并带上决定的版本；
// 提交以后显示「已提交」，事件到达以后按事件显示结果并移出等待列表；已经被回答或撤销时显示原因；
// 「在项目中查看」跳到项目中的对应页面。界面只解释已经存在的事实，不自行推进状态。

import { useEffect, useRef, useState } from "react";
import type { DecisionView } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { Icon } from "../../shell/kit";
import { CommandFeedback, KeyValue, Tag, TextArea, hasCommand } from "../project/common";
import { DECISION_BLOCKS, DECISION_KIND, formatDuration, formatTime, label } from "../project/labels";
import { useCommand } from "../project/use-snapshot";
import { blockedText, decisionLinks, materialRows, missingNoteText, viewHref, waitedSeconds } from "./card-logic";

export type DecisionCardProps = {
  app: ClientApp | null;
  decision: DecisionView;
  // 现在的时间：等待时长按发出时间到现在的差显示；由调用处给出，卡片不自行计时
  now: number;
  // 所属的项目名与事项标题：由调用处的快照解析（决定请求只带标识）
  projectName: string;
  workItemTitle: string;
  // 系统通知点击后要打开并标出的决定卡片（工单 #375，设计说明第 5.3 节）
  targetDecision?: string | null;
  onNavigate: (hash: string) => void;
};

// 一条决定请求的提交状态在卡片之外也要跨刷新保留（首页重新查询以后同一张卡片仍显示「已提交」）：
// 按决定标识记在会话里，事件到达、卡片移出等待列表或状态改变以后清除。
const submitted = new Set<string>();

export function DecisionCard(props: DecisionCardProps) {
  const { decision } = props;
  const [note, setNote] = useState("");
  // 选项要求写说明而说明为空时，提示放在这里并阻止提交（像素画面用同一个函数给同样的提示）
  const [noteMissing, setNoteMissing] = useState("");
  const command = useCommand(props.app, `${decision.version}/${decision.status}`);
  const answered = decision.status !== "open";
  const waiting = decision.status === "open";
  const isSubmitted = waiting && submitted.has(decision.decision_id);

  // 系统通知点进来的这张卡片：滚到视口里并描边标出（styles.css 的 .decision-card.is-targeted）
  const cardRef = useRef<HTMLElement | null>(null);
  const targeted = props.targetDecision === decision.decision_id;
  useEffect(() => {
    if (targeted) {
      cardRef.current?.scrollIntoView({ block: "center" });
    }
  }, [targeted]);

  // 事件到达以后卡片按新状态显示结果；已经被回答或撤销时把「已提交」清除
  useEffect(() => {
    if (!waiting) {
      submitted.delete(decision.decision_id);
    }
  }, [decision.decision_id, waiting]);

  const rows = materialRows(decision);
  const blocks = blockedText(decision);
  const links = decisionLinks(decision);
  const target = viewHref(decision);
  const options = decision.request?.options ?? [];

  const answer = (optionId: string) => {
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
    void command
      .submit("decision.answer", {
        decision_id: decision.decision_id,
        option: optionId,
        ...(trimmed === "" ? {} : { note: trimmed }),
        base_version: decision.version,
      })
      .then((ok) => {
        if (ok) {
          submitted.add(decision.decision_id);
          setNote("");
        }
      });
  };

  return (
    <article ref={cardRef} className={`y9-card decision-card${answered ? " answered" : ""}${isSubmitted ? " submitted" : ""}${targeted ? " is-targeted" : ""}`} id={`decision-${decision.decision_id}`}>
      <header className="decision-head">
        <div className="y9-card-title decision-title">
          <Icon name="decide" />
          <strong>{label(DECISION_KIND, decision.kind)}</strong>
          <Tag>{decision.blocks === "" ? "不阻塞" : `阻塞范围：${label(DECISION_BLOCKS, decision.blocks)}`}</Tag>
        </div>
        <div className="y9-card-meta decision-meta">
          <span>
            {props.projectName || decision.project_id || "项目流"}
            {props.workItemTitle || decision.work_item_id ? ` · ${props.workItemTitle || decision.work_item_id}` : ""}
          </span>
          <span>已等待 {formatDuration(waitedSeconds(decision.requested_at, props.now))}</span>
          <span className={blocks.muted ? "muted" : ""}>{blocks.text}</span>
        </div>
      </header>

      {rows.length > 0 ? (
        <details className="y9-card-body decision-body" open>
          <summary>材料</summary>
          <KeyValue items={rows.map((row) => [row.term, row.value] as [string, string])} />
          {links.length > 0 ? (
            <div className="y9-row row-actions">
              {links.map((link) => (
                <button key={link.href} type="button" className="y9-link link" onClick={() => props.onNavigate(link.href)}>
                  {link.label}
                </button>
              ))}
            </div>
          ) : null}
        </details>
      ) : null}

      {answered ? (
        <p className="y9-card-result decision-result" role="status">
          {decision.status === "answered"
            ? `已提交：${answeredLabel(decision)}（${formatTime(decision.answer?.answered_at ?? null)}）`
            : "决定请求已经撤销，卡片不再等待回答"}
        </p>
      ) : (
        <div className="y9-card-answer decision-answer">
          <TextArea label="说明（可选）" value={note} rows={2} disabled={isSubmitted} onInput={(value) => setNote(value)} />
          <div className="y9-row row-actions">
            {options.map((option) => (
              <button
                key={option.id}
                type="button"
                className="y9-btn primary"
                disabled={command.busy || isSubmitted || !hasCommand(props.app, "decision.answer")}
                onClick={() => answer(option.id)}
              >
                {option.label}
              </button>
            ))}
          </div>
          {noteMissing === "" ? null : (
            <span className="hint" role="status">
              {noteMissing}
            </span>
          )}
          {/* 已提交提示挂在选项行末尾（原型 v9 卡片同样位置）。命令反馈在卡片里只留拒绝提示：
              两条「已提交」同时出现会让提示重复（工单 #319） */}
          {isSubmitted ? <span className="y9-card-submitted">已提交，等待控制主机确认</span> : null}
          <CommandFeedback submitted={command.submitted && !isSubmitted} rejection={command.rejection} />
        </div>
      )}
      {target !== null ? (
        <footer className="y9-card-foot decision-foot">
          <button type="button" className="y9-link link" onClick={() => props.onNavigate(target)}>
            在项目中查看
          </button>
        </footer>
      ) : null}
    </article>
  );
}

// 已回答时的显示：优先用回答记录的选项标识，没有时回落到记录的选项名
function answeredLabel(decision: DecisionView): string {
  const answer = decision.answer;
  if (answer === null) {
    return "已回答";
  }
  const option = decision.request?.options.find((item) => item.id === answer.option);
  return option?.label ?? answer.option;
}

// 决定卡片列表：按发出时间排列，空列表写明没有等待回答的决定。
// names 把决定请求里的项目与事项标识解析成名称（由调用处的快照给出），解析不到时回落到标识
export function DecisionCardList(props: {
  app: ClientApp | null;
  decisions: DecisionView[];
  now: number;
  names: (decision: DecisionView) => { projectName: string; workItemTitle: string };
  onNavigate: (hash: string) => void;
  // 系统通知点击后要打开并标出的决定卡片（工单 #375，设计说明第 5.3 节）
  targetDecision?: string | null;
  emptyText: string;
}) {
  if (props.decisions.length === 0) {
    return <p className="y9-note note">{props.emptyText}</p>;
  }
  return (
    <div className="y9-cards decision-cards">
      {props.decisions.map((decision) => {
        const resolved = props.names(decision);
        return (
          <DecisionCard
            key={decision.decision_id}
            app={props.app}
            decision={decision}
            now={props.now}
            projectName={resolved.projectName}
            workItemTitle={resolved.workItemTitle}
            targetDecision={props.targetDecision}
            onNavigate={props.onNavigate}
          />
        );
      })}
    </div>
  );
}
