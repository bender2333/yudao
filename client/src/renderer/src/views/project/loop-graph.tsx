// 循环图（工单 #1638、#1640、#1642，项目的组织设计说明 4.14「项目页是循环图加对话」）：把 loop-graph-model 推出的事实
// 画成一张图——左边是事项的来源，中间是职能与它们之间的成果箭头，右边是结束；旁边的职能放在它对接的那个
// 职能上方。开着的询问画成写「询问」的虚线（不带版本），隔着职能的另起一行，旁边职能与主线之间的竖线也换成它；
// 答完的虚线消失。打开「累计往来」时画同一对职能合成的一条虚线，写问了几次（次数含开着的）；两种线都能点，
// 点下去只看这两个职能的时序图（工单 #1642）。窗口窄到 800px 以下时图收成一行（节点名、在等谁与当前箭头），
// 线程不被挤（样式里换，见 v10-project.css）。
//
// 这一层只画，不做判断：节点、箭头、询问与两端写什么全部由模型给出。

import { Fragment } from "react";
import type { LoopArrow, LoopAskLine, LoopGraph, LoopNode } from "./loop-graph-model";
import { END, SOURCE, nameOf } from "./loop-graph-model";

/** 面板现在打开的是哪一个：一个节点，或一条箭头。 */
export type LoopPanelPick = { kind: "node"; id: string } | { kind: "arrow"; arrow: LoopArrow } | null;

/** 箭头上的字：成果与版本（没有版本时只写成果，缺陷记录的第几版按出现的先后数）。 */
export function arrowText(arrow: LoopArrow): string {
  return arrow.version === null ? arrow.outcome : `${arrow.outcome} v${arrow.version}`;
}

/** 一行窄屏时写的那条「当前箭头」：最后一条不是来源的箭头。 */
export function currentArrow(graph: LoopGraph): LoopArrow | null {
  const all = [...graph.gaps.flat(), ...graph.skip, ...graph.side.flatMap((part) => part.arrows)]
    .filter((arrow) => arrow.from !== SOURCE)
    .sort((left, right) => left.position - right.position);
  return all.length === 0 ? null : all[all.length - 1];
}

function ArrowChip(props: { arrow: LoopArrow; on: boolean; onPick: (arrow: LoopArrow) => void }) {
  const { arrow } = props;
  return (
    <button type="button" className={`y10-cv-chip${props.on ? " is-on" : ""}${arrow.back ? " is-back" : ""}`}
            data-testid={`arrow-${arrow.key}`} title="看这一版与差异" onClick={() => props.onPick(arrow)}>
      <span className="y10-cv-dir">{arrow.back ? "←" : arrow.to === END ? "↗" : "→"}</span>
      <span className="y10-cv-kind">{arrowText(arrow)}</span>
      {arrow.round === null ? null : <small>第 {arrow.round} 轮</small>}
      {arrow.verdict === null ? null : (
        <span className={`y10-cv-verdict is-${arrow.verdict.tone}`}>{arrow.verdict.text}</span>
      )}
    </button>
  );
}

/**
 * 图上的一条虚线（项目的组织设计说明 4.14）。
 *
 * 不打开累计往来时是一条开着的询问：写「询问」，不带版本；打开以后是两个职能合成的一条：
 * 写问了几次，次数含开着的，还有开着的写「开着」。两种都点得开，点下去只看这两个职能的时序图（工单 #1642）。
 */
function AskChip(props: { line: LoopAskLine; direction: string; title: string; onPick: (from: string, to: string) => void }) {
  const { line } = props;
  return (
    <button type="button" className={`y10-cv-ask${line.kind === "pair" ? " is-accum" : ""}`}
            data-testid={line.kind === "pair" ? `accum-${line.key}` : `ask-${line.key}`}
            title={props.title} onClick={() => props.onPick(line.from, line.to)}>
      {line.kind === "ask" ? (
        <>
          <span className="y10-cv-dir">{props.direction}</span>
          <span className="y10-cv-kind">询问</span>
        </>
      ) : <span className="y10-cv-kind">{line.label}</span>}
    </button>
  );
}

function NodeCard(props: { node: LoopNode; on: boolean; onPick: (id: string) => void }) {
  const { node } = props;
  return (
    <button type="button" className={`y10-cv-node${node.verifier ? " is-ver" : ""}${node.working ? " is-working" : ""}${props.on ? " is-on" : ""}`}
            data-testid={`node-${node.id}`} aria-label={`${node.label}：看这个职能的状态`} onClick={() => props.onPick(node.id)}>
      <b>{node.label}</b>
      <span className="y10-cv-marks">
        {node.verifier ? <span className="y10-cv-badge is-ver">核验</span> : null}
        {node.oldOnly ? <span className="y10-cv-badge">只在旧组织里</span> : null}
        {node.others > 0 ? <span className="y10-cv-badge">另 {node.others} 件</span> : null}
      </span>
      {node.state === "" ? null : <small className="y10-cv-state">{node.state}</small>}
    </button>
  );
}

/**
 * 一张循环图。`pick` 是面板打开的那一个，用来把选中的节点或箭头标出来；
 * 点节点、点箭头都交给调用处打开同一个面板；点询问线（开着的或累计的）只看这两个职能的时序图。
 */
export function LoopGraphView(props: {
  graph: LoopGraph;
  pick: LoopPanelPick;
  onPickNode: (id: string) => void;
  onPickArrow: (arrow: LoopArrow) => void;
  onPickAsk: (from: string, to: string) => void;
}): React.JSX.Element {
  const { graph } = props;
  const count = graph.chain.length;
  // 有旁边的职能时多两行：一行放它们，一行放它们与主线之间的竖线
  const hasSide = graph.side.length > 0;
  const skipRow = hasSide ? 4 : 2;
  const sideAt = new Map<number, typeof graph.side>();
  for (const part of graph.side) {
    const index = graph.chain.findIndex((node) => node.id === part.partner);
    if (index < 0) {
      continue;
    }
    sideAt.set(index, [...(sideAt.get(index) ?? []), part]);
  }
  // 列：来源 | 缝 | 节点 | 缝 | 节点 | … | 缝 | 结束
  const template = ["auto"];
  for (let index = 0; index < count; index += 1) {
    template.push("minmax(56px, 1fr)", "auto");
  }
  template.push("minmax(56px, 1fr)", "auto");
  const nodeColumn = (index: number): number => 3 + 2 * index;
  const gapColumn = (index: number): number => 2 + 2 * index;
  const selectedNode = props.pick?.kind === "node" ? props.pick.id : null;
  const selectedArrow = props.pick?.kind === "arrow" ? props.pick.arrow.key : null;
  // 虚线：方向只给开着的询问（累计往来的字里已经写了谁问谁），按放置分组画
  const directions = (line: LoopAskLine): string => {
    if (line.kind === "pair") {
      return "";
    }
    if (line.place === "side") {
      // 旁边的职能在上面：主线问它朝上，它问主线朝下
      return line.from === line.partner ? "↑" : "↓";
    }
    return line.toIndex < line.fromIndex ? "←" : "→";
  };
  // 鼠标停上去：询问给问题（两端与问题），累计往来给一句「看这两个职能的时序图」
  const lineTitle = (line: LoopAskLine): string => {
    if (line.kind === "pair") {
      return `${line.label} · 看这两个职能的时序图`;
    }
    const pair = `${nameOf(graph, line.from)}问${nameOf(graph, line.to)}`;
    return `${line.question === "" ? pair : `${pair}：${line.question}`} · 看这两个职能的时序图`;
  };
  const lineChip = (line: LoopAskLine): React.JSX.Element => (
    <AskChip key={line.key} line={line} direction={directions(line)} title={lineTitle(line)} onPick={props.onPickAsk} />
  );
  const linesInGap = (index: number): LoopAskLine[] =>
    graph.lines.filter((line) => line.place === "gap" && line.gap === index);
  const cell = (content: React.ReactNode, column: number, row = hasSide ? 3 : 1): React.ReactNode => (
    <div key={`c-${column}-${row}`} style={{ gridColumn: column, gridRow: row }} className="y10-cv-cell">{content}</div>
  );
  const chain: React.ReactNode[] = [];
  graph.gaps.forEach((arrows, index) => {
    const asks = linesInGap(index);
    chain.push(cell(
      arrows.length === 0 && asks.length === 0
        ? <span className="y10-cv-line" aria-hidden="true" />
        : (
          <>
            {arrows.map((arrow) => (
              <ArrowChip key={arrow.key} arrow={arrow} on={arrow.key === selectedArrow} onPick={props.onPickArrow} />
            ))}
            {asks.map(lineChip)}
          </>
        ),
      gapColumn(index),
    ));
    const node = graph.chain[index];
    if (node === undefined) {
      return;
    }
    chain.push(cell(
      <NodeCard node={node} on={node.id === selectedNode} onPick={props.onPickNode} />,
      nodeColumn(index),
    ));
  });
  chain.unshift(cell(<span className="y10-cv-pill is-src">{graph.sourceText}</span>, 1));
  chain.push(cell(
    <span className={`y10-cv-pill is-end is-${graph.endTone}`}>{graph.endText}</span>,
    nodeColumn(count),
  ));
  const side: React.ReactNode[] = [];
  if (hasSide) {
    sideAt.forEach((parts, index) => {
      side.push(cell(
        <span className="y10-cv-side">{parts.map((part) => (
          <NodeCard key={part.node.id} node={part.node} on={part.node.id === selectedNode} onPick={props.onPickNode} />
        ))}</span>,
        nodeColumn(index), 1,
      ));
      side.push(cell(
        <span className="y10-cv-vasks">{parts.map((part) => (part.lines.length === 0 ? (
          <span key={part.node.id} className="y10-cv-vlink" aria-hidden="true" />
        ) : part.lines.map(lineChip)))}</span>,
        nodeColumn(index), 2,
      ));
    });
  }
  const skips = graph.skip.map((arrow, index) => {
    const from = graph.chain.findIndex((node) => node.id === arrow.from);
    const to = graph.chain.findIndex((node) => node.id === arrow.to);
    const low = Math.min(from, to);
    const high = Math.max(from, to);
    return (
      <div key={`skip-${arrow.key}`} className="y10-cv-skip"
           style={{ gridColumn: `${nodeColumn(low)} / ${nodeColumn(high) + 1}`, gridRow: skipRow + index }}>
        <span className="y10-cv-line" aria-hidden="true" />
        <ArrowChip arrow={arrow} on={arrow.key === selectedArrow} onPick={props.onPickArrow} />
        <span className="y10-cv-skip-to">给{graph.chain[high]?.label ?? ""}</span>
        <span className="y10-cv-line" aria-hidden="true" />
      </div>
    );
  });
  // 隔着职能的询问另起一行：与跨节点的成果箭头同一排，接在它们下面
  const skipAsks = graph.lines.filter((line) => line.place === "skip").map((line, index) => {
    const low = Math.min(line.fromIndex, line.toIndex);
    const high = Math.max(line.fromIndex, line.toIndex);
    return (
      <div key={`ask-skip-${line.key}`} className="y10-cv-skip is-q"
           style={{ gridColumn: `${nodeColumn(low)} / ${nodeColumn(high) + 1}`, gridRow: skipRow + graph.skip.length + index }}>
        <span className="y10-cv-line" aria-hidden="true" />
        {lineChip(line)}
        {/* 开着的询问另写两端；累计往来的字里已经写了谁问谁，不再重复 */}
        {line.kind === "ask" ? <span className="y10-cv-skip-to">{nameOf(graph, line.from)}问{nameOf(graph, line.to)}</span> : null}
        <span className="y10-cv-line" aria-hidden="true" />
      </div>
    );
  });
  const current = currentArrow(graph);
  return (
    <div className="y10-cv-graph" data-testid="loop-graph">
      <div className="y10-cv-wrap">
        <div className="y10-cv-grid" style={{ gridTemplateColumns: template.join(" ") }}>
          {side}
          {chain}
          {skips}
          {skipAsks}
        </div>
      </div>
      {/* 窄屏：图收成一行，节点名与当前箭头（样式里在 800px 以下显示这一行、收起上面那张图） */}
      <div className="y10-cv-oneline" data-testid="loop-oneline">
        {graph.chain.map((node, index) => (
          <Fragment key={node.id}>
            {index === 0 ? null : <span className="y10-cv-dir">→</span>}
            <button type="button" className="y10-link" onClick={() => props.onPickNode(node.id)}>
              {node.label}{node.verifier ? "（核验）" : ""}
            </button>
            {/* 窄屏不画线：在节点名旁写上它在等谁的回答（设计说明 4.14） */}
            {node.waiting.map((text) => <small key={text} className="y10-cv-qstate">{text}</small>)}
          </Fragment>
        ))}
        {current === null ? null : (
          <span className="y10-cv-oneline-cur">
            <button type="button" className="y10-link" onClick={() => props.onPickArrow(current)}>{arrowText(current)}</button>
            {current.round === null ? null : <small> · 第 {current.round} 轮</small>}
            <span> → {current.to === END ? graph.endText : graph.chain.find((node) => node.id === current.to)?.label ?? ""}</span>
          </span>
        )}
      </div>
    </div>
  );
}
