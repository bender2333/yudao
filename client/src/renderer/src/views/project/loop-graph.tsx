// 循环图（工单 #1638、#1640、#1642，项目的组织设计说明 4.14「项目页是循环图加对话」）：把 loop-graph-model 推出的事实
// 画成一张图——左边是事项的来源，中间是职能与它们之间的成果箭头，右边是结束；旁边的职能放在它对接的那个
// 职能上方。开着的询问画成写「询问」的虚线（不带版本），隔着职能的另起一行，旁边职能与主线之间的竖线也换成它；
// 答完的虚线消失。打开「累计往来」时画同一对职能合成的一条虚线，写问了几次（次数含开着的）；两种线都能点，
// 点下去只看这两个职能的时序图（工单 #1642）。窗口窄到 800px 以下时图收成一行（节点名、在等谁与当前箭头），
// 线程不被挤（样式里换，见 v10-project.css）。
//
// 这一层只画，不做判断：节点、箭头、询问与两端写什么全部由模型给出。

import { Fragment, useEffect, useLayoutEffect, useState } from "react";
import blueprintCss from "../../styles/v21-blueprint.css?raw";
import type {
  BlueprintEndView,
  BlueprintRailView,
  BlueprintTheme,
  LoopArrow,
  LoopAskLine,
  LoopGraph,
  LoopNode,
  NodeTelemetry,
} from "./loop-graph-model";
import { END, SOURCE, brailleFrameOf, nameOf } from "./loop-graph-model";

/** 在组件挂载前向文档头注入一次蓝图样式，避免 Vite SSR 测试在未执行 buildStart 时解析裸 .css 失败，也不改动 styles.css。 */
export function ensureBlueprintStyles(): void {
  if (typeof document === "undefined") {
    return;
  }
  if (document.getElementById("y21-blueprint-styles") !== null) {
    return;
  }
  const style = document.createElement("style");
  style.id = "y21-blueprint-styles";
  style.textContent = blueprintCss;
  document.head.appendChild(style);
}

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

function NodeCard(props: {
  node: LoopNode;
  on: boolean;
  telemetry?: NodeTelemetry | null;
  brailleFrame?: string;
  onPick: (id: string) => void;
}) {
  const { node, telemetry } = props;
  return (
    <button type="button" className={`y10-cv-node${node.verifier ? " is-ver" : ""}${node.working ? " is-working" : ""}${props.on ? " is-on" : ""}`}
            data-testid={`node-${node.id}`} aria-label={`${node.label}：看这个职能的状态`} onClick={() => props.onPick(node.id)}>
      {telemetry ? (
        <div className="y21-node-top">
          <span className={`y21-dot is-${telemetry.statusTone}`} aria-hidden="true" />
          <b>{node.label}</b>
          <span className={`y21-node-status is-${telemetry.statusTone}`} data-testid={`node-status-${node.id}`}>
            {telemetry.statusLabel}
          </span>
        </div>
      ) : (
        <b>{node.label}</b>
      )}
      <span className="y10-cv-marks">
        {node.verifier ? <span className="y10-cv-badge is-ver">核验</span> : null}
        {node.oldOnly ? <span className="y10-cv-badge">只在旧组织里</span> : null}
        {node.others > 0 ? <span className="y10-cv-badge">另 {node.others} 件</span> : null}
      </span>
      {telemetry ? (
        <>
          <small
            className={`y21-node-model${telemetry.modelUnset ? " is-unset" : ""}${telemetry.modelUnusable ? " is-unusable" : ""}`}
            title={telemetry.modelName}
            data-testid={`node-model-${node.id}`}
          >
            {telemetry.modelName}
          </small>
          <div className="y21-node-tele">
            <span className="y21-effort" title="推理档位">
              <span className="y21-squares" aria-hidden="true">{telemetry.effort.squares}</span>
              <span>{telemetry.effort.label}</span>
            </span>
            <span className="y21-tele-right">
              {telemetry.workingPulse && props.brailleFrame ? (
                <span className="y21-braille" aria-hidden="true" data-testid={`node-braille-${node.id}`}>
                  {props.brailleFrame}
                </span>
              ) : null}
              {telemetry.contextPercent === null ? null : (
                <span className="y21-ctx-bar" aria-hidden="true">
                  <i style={{ width: `${Math.min(100, telemetry.contextPercent)}%` }} />
                </span>
              )}
              <span className="y21-ctx-pct" data-testid={`node-ctx-${node.id}`}>{telemetry.contextText}</span>
            </span>
          </div>
        </>
      ) : null}
      {node.state === "" ? null : <small className="y10-cv-state">{node.state}</small>}
    </button>
  );
}

/** 循环图网格列模板：来源、节点与终点列采用 max-content 防止卡片被压窄重叠，缝列按 minmax(44px, 1fr) 弹性分布。 */
export function loopGridColumns(chainCount: number): string[] {
  const count = Math.max(0, Math.floor(chainCount));
  const template = ["max-content"];
  for (let index = 0; index < count; index += 1) {
    template.push("minmax(44px, 1fr)", "max-content");
  }
  template.push("minmax(44px, 1fr)", "max-content");
  return template;
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
  troupe?: boolean;
  blueprintTheme?: BlueprintTheme;
  rail?: BlueprintRailView | null;
  telemetry?: Readonly<Record<string, NodeTelemetry>>;
  endView?: BlueprintEndView | null;
  frozenOrganization?: { form: string; sameAsProject?: boolean | null } | null;
  selectedDepartmentId?: string | null;
}): React.JSX.Element {
  const { graph } = props;
  useLayoutEffect(() => {
    if (props.troupe) {
      ensureBlueprintStyles();
    }
  }, [props.troupe]);
  const anyWorking = Boolean(
    props.troupe && graph.nodes.some((n) => props.telemetry?.[n.id]?.workingPulse ?? n.working),
  );
  const [pulseTick, setPulseTick] = useState(0);
  useEffect(() => {
    if (!anyWorking) {
      return;
    }
    const timer = window.setInterval(() => {
      setPulseTick((value) => (value + 1) % 8);
    }, 150);
    return () => window.clearInterval(timer);
  }, [anyWorking]);
  const brailleFrame = brailleFrameOf(pulseTick);
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
  const template = loopGridColumns(count);
  const nodeColumn = (index: number): number => 3 + 2 * index;
  const gapColumn = (index: number): number => 2 + 2 * index;
  const selectedNode = props.pick?.kind === "node" ? props.pick.id : (props.selectedDepartmentId ?? null);
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
      <NodeCard
        node={node}
        on={node.id === selectedNode}
        telemetry={props.troupe ? (props.telemetry?.[node.id] ?? null) : null}
        brailleFrame={brailleFrame}
        onPick={props.onPickNode}
      />,
      nodeColumn(index),
    ));
  });
  chain.unshift(cell(<span className="y10-cv-pill is-src">{graph.sourceText}</span>, 1));
  chain.push(cell(
    props.troupe && props.endView ? (
      <span
        className={`y10-cv-pill is-end ${props.endView.kind === "verifier" ? "is-ver" : "is-open"}`}
        data-testid="blueprint-end"
      >
        {props.endView.text}
      </span>
    ) : (
      <span className={`y10-cv-pill is-end is-${graph.endTone}`}>{graph.endText}</span>
    ),
    nodeColumn(count),
  ));
  const side: React.ReactNode[] = [];
  if (hasSide) {
    sideAt.forEach((parts, index) => {
      side.push(cell(
        <span className="y10-cv-side">{parts.map((part) => (
          <NodeCard
            key={part.node.id}
            node={part.node}
            on={part.node.id === selectedNode}
            telemetry={props.troupe ? (props.telemetry?.[part.node.id] ?? null) : null}
            brailleFrame={brailleFrame}
            onPick={props.onPickNode}
          />
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
  const theme: BlueprintTheme = props.blueprintTheme ?? "dark";
  const stageMark = (state: "done" | "active" | "pending" | "stopped"): string => {
    if (state === "done") {
      return "✓";
    }
    if (state === "active") {
      return "▸";
    }
    if (state === "stopped") {
      return "■";
    }
    return "○";
  };
  const canvas = (
    <div className="y10-cv-wrap">
      {props.troupe ? (
        <div className="y21-bp-head">
          <div className="y21-bp-title">
            <span className="y21-bp-kicker">LOOP BLUEPRINT</span>
            {graph.rounds > 0 ? <span>第 {graph.rounds} 轮</span> : null}
            {props.frozenOrganization?.sameAsProject === false ? (
              <span className="y21-bp-frozen">按旧组织快照运行</span>
            ) : null}
          </div>
          <div className="y21-bp-legend" aria-label="终点图例">
            <span><i className="is-solid" aria-hidden="true" /> ✓ 核验放行</span>
            <span><i className="is-dashed" aria-hidden="true" /> ◌ 开环完成</span>
          </div>
        </div>
      ) : null}
      <div className="y10-cv-grid" style={{ gridTemplateColumns: template.join(" ") }}>
        {side}
        {chain}
        {skips}
        {skipAsks}
      </div>
    </div>
  );
  return (
    <div
      className={`y10-cv-graph${props.troupe ? " is-troupe" : ""}`}
      data-bp={props.troupe ? theme : undefined}
      data-testid="loop-graph"
    >
      {props.troupe && props.rail ? (
        <div className="y21-bp-shell">
          <aside className="y21-bp-rail" aria-label="蓝图状态栏" data-testid="blueprint-rail">
            <section className="y21-rail-sec">
              <h3 className="y21-rail-title">职能</h3>
              <ul className="y21-rail-depts">
                {props.rail.departments.map((dept) => (
                  <li key={dept.id}>
                    <button
                      type="button"
                      className={`y21-rail-dept-btn${dept.id === selectedNode ? " is-on" : ""}`}
                      onClick={() => props.onPickNode(dept.id)}
                    >
                      <span className={`y21-dot is-${dept.statusTone}`} aria-hidden="true" />
                      <span className="y21-rail-dept-name">{dept.label}</span>
                      <span className="y21-rail-ctx">{dept.contextText}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
            <section className="y21-rail-sec">
              <h3 className="y21-rail-title">阶段</h3>
              <ul className="y21-rail-stages">
                {props.rail.stages.map((stage) => (
                  <li key={stage.key} className={`y21-rail-stage is-${stage.state}`}>
                    <span className="y21-rail-mark" aria-hidden="true">{stageMark(stage.state)}</span>
                    <span>{stage.label}</span>
                  </li>
                ))}
              </ul>
            </section>
          </aside>
          {canvas}
        </div>
      ) : canvas}
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
