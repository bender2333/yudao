// 循环图的面板（工单 #1638，项目的组织设计说明 4.14）：点节点与点箭头打开同一个面板。
//   - 点节点：这个职能在做什么、它的状态与原因、它的标记（核验、只在旧组织里）；
//   - 点箭头：那一版与差异（改了的文件、那一版的一句话），同一种成果能逐版看。
// 面板只显示模型给出的事实与本页读到的成果材料，不另存一份。

import type { LoopArrow, LoopGraph, LoopNode } from "./loop-graph-model";
import { versionsOf } from "./loop-graph-model";
import { arrowText, type LoopPanelPick } from "./loop-graph";

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

/** 同一个面板：打开的是哪一样就画哪一样。没有打开的东西时整块不出现。 */
export function LoopPanel(props: {
  graph: LoopGraph;
  arrows: readonly LoopArrow[];
  pick: LoopPanelPick;
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
  const id = props.pick.id;
  const node = props.graph.nodes.find((item) => item.id === id);
  return node === undefined ? null : <NodePanel graph={props.graph} node={node} onClose={props.onClose} />;
}
