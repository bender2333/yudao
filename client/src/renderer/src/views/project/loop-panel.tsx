// 循环图与时序图共用的面板（工单 #1638、#1643，项目的组织设计说明 4.14）：
//   - 点节点：这个职能在做什么、它的状态与原因、它的标记（核验、只在旧组织里）；
//   - 点箭头：那一版与差异（改了的文件、那一版的一句话），同一种成果能逐版看；
//   - 点时序图上的一行：成果走同一条箭头（那一版与差异），问答与你的话是全文，
//     询问里又问的写明是回答哪一次时问的，工程回答质检的分事实与解释。
// 面板只有一种，只显示模型给出的事实与本页读到的成果材料，不另存一份；这一版不放「看工作过程」。

import type { LoopArrow, LoopGraph, LoopNode } from "./loop-graph-model";
import { versionsOf } from "./loop-graph-model";
import { arrowText, type LoopPanelPick } from "./loop-graph";
import { formatTime } from "./labels";
import type { SequenceDetail, SequenceRow } from "./sequence-model";

/** 面板打开的是哪一个：一个节点、一条箭头，或时序图上的一行（原文）。 */
export type LoopPanelTarget = Exclude<LoopPanelPick, null> | { kind: "row"; row: SequenceRow } | null;

/** 一版的方向写成人能读的一句：来源 → 职能、职能 → 职能、职能 → 结束。 */
function endsText(graph: LoopGraph, arrow: LoopArrow): string {
  const name = (id: string): string => {
    if (id === "src") {
      return graph.sourceText;
    }
    if (id === "end") {
      return graph.endText;
    }
    return graph.chain.find((node) => node.id === id)?.label
      ?? graph.side.find((part) => part.node.id === id)?.node.label
      ?? id;
  };
  return `${name(arrow.from)} → ${name(arrow.to)}`;
}

function ArrowPanel(props: {
  graph: LoopGraph;
  arrow: LoopArrow;
  arrows: readonly LoopArrow[];
  onPickArrow: (arrow: LoopArrow) => void;
  onClose: () => void;
}): React.JSX.Element {
  const { arrow } = props;
  // 同一种成果、同两端的几版：点箭头时逐版看
  const versions = versionsOf(props.arrows, arrow);
  const at = versions.findIndex((item) => item.key === arrow.key);
  return (
    <section className="y10-cv-panel" aria-label="这一版" data-testid="loop-panel-arrow">
      <button type="button" className="y10-icon-btn y10-cv-close" aria-label="收起" onClick={props.onClose}>×</button>
      <h3>
        {arrowText(arrow)}
        {arrow.round === null ? null : ` · 第 ${arrow.round} 轮`}
        <small> {endsText(props.graph, arrow)}</small>
      </h3>
      {versions.length > 1 ? (
        <p className="y10-cv-nav">
          {at > 0 ? (
            <button type="button" className="y10-link" onClick={() => props.onPickArrow(versions[at - 1])}>
              ‹ {arrowText(versions[at - 1])}
            </button>
          ) : null}
          <span className="y10-muted">第 {at + 1} / {versions.length} 版</span>
          {at < versions.length - 1 ? (
            <button type="button" className="y10-link" onClick={() => props.onPickArrow(versions[at + 1])}>
              {arrowText(versions[at + 1])} ›
            </button>
          ) : null}
        </p>
      ) : null}
      {arrow.verdict === null ? null : (
        <p className={`y10-cv-verdict-line is-${arrow.verdict.tone}`}>
          {arrow.verdict.tone === "reject" ? `${arrow.verdict.by}打回这一版` : `${arrow.verdict.by}放行这一版`}
        </p>
      )}
      {arrow.text === "" ? null : <p className="y10-cv-panel-text">{arrow.text}</p>}
      {arrow.files.length === 0 ? null : (
        <div className="y10-cv-files">
          <b>改了的文件</b>
          <ul className="y10-list">
            {arrow.files.map((file) => <li key={file}><span className="y10-pp-mono">{file}</span></li>)}
          </ul>
        </div>
      )}
    </section>
  );
}

function NodePanel(props: { graph: LoopGraph; node: LoopNode; onClose: () => void }): React.JSX.Element {
  const { node } = props;
  const partner = props.graph.side.find((part) => part.node.id === node.id)?.partner ?? null;
  return (
    <section className="y10-cv-panel" aria-label={node.label} data-testid="loop-panel-node">
      <button type="button" className="y10-icon-btn y10-cv-close" aria-label="收起" onClick={props.onClose}>×</button>
      <h3>{node.label}<small> {node.state === "" ? "现在没有状态" : node.state}</small></h3>
      <ul className="y10-list y10-cv-facts">
        <li>职能：{node.label}{node.state === "" ? "" : `，${node.state}`}</li>
        {node.verifier ? <li>它的角色是核验角色：核验交付的那一版，放行时写它的显示名</li> : null}
        {node.others > 0 ? <li>别的事项正在这个职能上的有 {node.others} 件</li> : null}
        {node.oldOnly ? <li>这个职能只在旧组织里：项目现在的组织里已经没有它，这件事项仍按它冻结的组织做完</li> : null}
        {partner === null ? null : <li>它在旁边接询问，与主线上「{props.graph.chain.find((item) => item.id === partner)?.label ?? partner}」往来</li>}
      </ul>
    </section>
  );
}

/** 时序图上的询问与回答：问题与回答的全文；又问的写明是回答哪一次时问的。 */
function AskPanel(props: {
  row: SequenceRow;
  detail: Extract<SequenceDetail, { kind: "ask" }>;
  onClose: () => void;
}): React.JSX.Element {
  const { detail } = props;
  return (
    <section className="y10-cv-panel" aria-label="询问" data-testid="loop-panel-ask">
      <button type="button" className="y10-icon-btn y10-cv-close" aria-label="收起" onClick={props.onClose}>×</button>
      <h3>
        询问<small> {detail.fromLabel} → {detail.toLabel} · {formatTime(props.row.at)}</small>
      </h3>
      {detail.parent === null ? null : <p className="y10-cv-note">回答「{detail.parent}」时又问的</p>}
      <p className="y10-cv-full">{detail.question}</p>
      {detail.status === "进行中" ? <p className="y10-cv-note">还没回答。</p> : null}
      {detail.status === "没能回答" ? (
        <p className="y10-cv-full">没能回答：{detail.reason === null || detail.reason === "" ? "没有写原因" : detail.reason}</p>
      ) : null}
      {detail.status !== "已回答" ? null : (
        <>
          {detail.answer === null || detail.answer === "" ? null : (
            <div className="y10-cv-block"><b>回答</b><p className="y10-cv-full">{detail.answer}</p></div>
          )}
          {detail.facts === null || detail.facts === "" ? null : (
            <div className="y10-cv-block"><b>事实</b><p className="y10-cv-full">{detail.facts}</p></div>
          )}
          {detail.explanation === null || detail.explanation === "" ? null : (
            <div className="y10-cv-block">
              <b>解释{detail.explanationNote === null ? "" : ` · ${detail.explanationNote}`}</b>
              <p className="y10-cv-full">{detail.explanation}</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** 你写的话、指导与决定：全文；附注另写一行（可选项、你当时的说明）。 */
function TextPanel(props: {
  heading: string;
  text: string;
  note: string | null;
  at: string;
  onClose: () => void;
}): React.JSX.Element {
  return (
    <section className="y10-cv-panel" aria-label={props.heading} data-testid="loop-panel-text">
      <button type="button" className="y10-icon-btn y10-cv-close" aria-label="收起" onClick={props.onClose}>×</button>
      <h3>{props.heading}<small> {formatTime(props.at)}</small></h3>
      {props.text === "" ? null : <p className="y10-cv-full">{props.text}</p>}
      {props.note === null || props.note === "" ? null : <p className="y10-cv-note">{props.note}</p>}
    </section>
  );
}

/** 时序图上的一行：成果走箭头那块面板，问答与你的话是全文。 */
function RowPanel(props: { row: SequenceRow; onClose: () => void }): React.JSX.Element {
  const detail = props.row.detail;
  if (detail.kind === "ask") {
    return <AskPanel row={props.row} detail={detail} onClose={props.onClose} />;
  }
  if (detail.kind === "text") {
    return (
      <TextPanel heading={detail.heading} text={detail.text} note={detail.note} at={props.row.at} onClose={props.onClose} />
    );
  }
  // 成果那一行：图上找得到对应的箭头时由调用处打开箭头面板；走到这里时仍把这版的原文写出来
  return <TextPanel heading={props.row.title} text={detail.text} note={null} at={props.row.at} onClose={props.onClose} />;
}

/** 同一个面板：打开的是哪一样就画哪一样。没有打开的东西时整块不出现。 */
export function LoopPanel(props: {
  graph: LoopGraph;
  arrows: readonly LoopArrow[];
  pick: LoopPanelTarget;
  onPickArrow: (arrow: LoopArrow) => void;
  onClose: () => void;
}): React.JSX.Element | null {
  if (props.pick === null) {
    return null;
  }
  if (props.pick.kind === "arrow") {
    return (
      <ArrowPanel graph={props.graph} arrow={props.pick.arrow} arrows={props.arrows}
                  onPickArrow={props.onPickArrow} onClose={props.onClose} />
    );
  }
  if (props.pick.kind === "row") {
    return <RowPanel row={props.pick.row} onClose={props.onClose} />;
  }
  const id = props.pick.id;
  const node = props.graph.nodes.find((item) => item.id === id);
  return node === undefined ? null : <NodePanel graph={props.graph} node={node} onClose={props.onClose} />;
}
