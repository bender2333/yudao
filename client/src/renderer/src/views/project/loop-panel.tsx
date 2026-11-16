// 循环图与时序图共用的面板（工单 #1638、#1640、#1643，项目的组织设计说明 4.14）：
//   - 点节点：这个职能在做什么、它的状态与原因、它的标记（核验、只在旧组织里），以及它的往来
//     （开着的询问在前，标「还没回答」；答完的排在后面，和节点上的字出自同一份状态与事实）；
//   - 点箭头：那一版与差异（改了的文件、那一版的一句话），同一种成果能逐版看；面板里的各段
//     （结论与逐条结论、文件下载、输入各版与进度、建档各轮、开环完成）见 arrow-panel.tsx（工单 #1711）；
//   - 点时序图上的一行：成果走同一条箭头（那一版与差异），问答与你的话是全文，
//     询问里又问的写明是回答哪一次时问的，工程回答质检的分事实与解释。
// 面板只有一种，只显示模型给出的事实与本页读到的成果材料，不另存一份。
//
// 「看工作过程」（工单 #1658）在原文面板里就地展开：成果那一行与询问、回答那一行有入口，
// 决定、指导、你的输入那一行没有，还没有对应激活的询问也没有。看哪一次工作由 work-process-model
// 给出（成果按第几轮，询问与回答按询问编号对激活的会话编号）。

import type { ClientApp } from "../../contract/client-app";
import type { LoopArrow, LoopGraph } from "./loop-graph-model";
import { nameOf, versionsOf } from "./loop-graph-model";
import { arrowText, type LoopPanelPick } from "./loop-graph";
import { ArrowSections } from "./arrow-panel.tsx";
import { formatTime } from "./labels";
import { LiveWindow, type LiveWindowProps } from "./live-window.tsx";
import type { SequenceDetail, SequenceRow } from "./sequence-model";
import { WorkProcess } from "./work-process.tsx";
import { workTargetOfArrow, workTargetOfRow, type WorkTarget } from "./work-process-model.ts";

/** 面板打开的是哪一个：一个节点、一条箭头，或时序图上的一行（原文）。 */
export type LoopPanelTarget = Exclude<LoopPanelPick, null> | { kind: "row"; row: SequenceRow } | null;

/** 看工作过程要的几样：从哪个页面读、进请求详情时带哪一项范围，以及这个事项的询问编号。 */
interface WorkSource {
  app: ClientApp;
  projectId: string;
  workItemId: string;
  runId: string;
  /** 图上的询问编号：询问分支的激活带着它，按第几轮找激活时排掉（接口设计说明 4.4 第 4 条） */
  branchSessions: readonly string[];
}

/** 这一行对应的工作：哪一次激活（或哪一次回答），以及它属于哪个职能的显示名。 */
interface WorkPick {
  target: WorkTarget;
  departmentLabel: string;
}

/**
 * 原文面板里的「看工作过程」：有对应的那一次工作时才有这条入口，点开就地展开。
 *
 * 换了面板上的那样东西（别的箭头、别的行）就收起：入口用那一样东西的身份做键。
 */
function WorkEntry(props: WorkSource & { work: WorkPick | null; sourceKey: string }) {
  if (props.work === null) {
    return null;
  }
  return (
    <WorkProcess
      key={props.sourceKey}
      app={props.app}
      projectId={props.projectId}
      workItemId={props.workItemId}
      runId={props.runId}
      target={props.work.target}
      departmentLabel={props.work.departmentLabel}
      branchSessions={props.branchSessions}
    />
  );
}

/** 一版的方向写成人能读的一句：来源 → 职能、职能 → 职能、职能 → 结束。 */
function endsText(graph: LoopGraph, arrow: LoopArrow): string {
  return `${nameOf(graph, arrow.from)} → ${nameOf(graph, arrow.to)}`;
}

function ArrowPanel(props: WorkSource & {
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
  // 产生这一版的那个职能那一轮（工单 #1658）：来源那一端（你的输入）与没有轮次时没有入口
  const work = workTargetOfArrow(arrow);
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
      {/* 面板里的各段（工单 #1711）：结论、逐条结论与证据、这一版与文件下载、输入各版、建档各轮、
          开环完成一句。各段按箭头是哪一种成果出现，由 arrow-panel-model.ts 给。 */}
      <ArrowSections
        app={props.app}
        projectId={props.projectId}
        workItemId={props.workItemId}
        runId={props.runId}
        graph={props.graph}
        arrow={arrow}
        versions={versions}
      />
      <WorkEntry app={props.app} projectId={props.projectId} workItemId={props.workItemId} runId={props.runId}
                 branchSessions={props.branchSessions}
                 sourceKey={arrow.key}
                 work={work === null ? null : { target: work, departmentLabel: nameOf(props.graph, arrow.from) }} />
    </section>
  );
}

/** 节点现场窗口上下文：点图上节点或默认展开现场窗口时传给 LiveWindow 的页面事实。 */
export type LoopPanelLiveContext = Omit<
  LiveWindowProps,
  "app" | "projectId" | "workItemId" | "runId" | "graph" | "arrows" | "department" | "onPickArrow" | "onClose"
>;

/** 时序图上的询问与回答：问题与回答的全文；又问的写明是回答哪一次时问的。 */
function AskPanel(props: WorkSource & {
  row: SequenceRow;
  detail: Extract<SequenceDetail, { kind: "ask" }>;
  onClose: () => void;
}): React.JSX.Element {
  const { detail } = props;
  // 看工作过程：被询问职能那一次回答的经过（工单 #1658）；还没回答的询问没有对应的激活
  const work = workTargetOfRow(props.row);
  const departmentLabel = props.row.kind === "answer" ? detail.fromLabel : detail.toLabel;
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
      <WorkEntry app={props.app} projectId={props.projectId} workItemId={props.workItemId} runId={props.runId}
                 branchSessions={props.branchSessions}
                 sourceKey={props.row.key}
                 work={work === null ? null : { target: work, departmentLabel }} />
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
  children?: React.ReactNode;
}): React.JSX.Element {
  return (
    <section className="y10-cv-panel" aria-label={props.heading} data-testid="loop-panel-text">
      <button type="button" className="y10-icon-btn y10-cv-close" aria-label="收起" onClick={props.onClose}>×</button>
      <h3>{props.heading}<small> {formatTime(props.at)}</small></h3>
      {props.text === "" ? null : <p className="y10-cv-full">{props.text}</p>}
      {props.note === null || props.note === "" ? null : <p className="y10-cv-note">{props.note}</p>}
      {props.children}
    </section>
  );
}

/** 时序图上的一行：成果走箭头那块面板，问答与你的话是全文。 */
function RowPanel(props: WorkSource & { graph: LoopGraph; row: SequenceRow; onClose: () => void }): React.JSX.Element {
  const detail = props.row.detail;
  if (detail.kind === "ask") {
    return (
      <AskPanel row={props.row} detail={detail} onClose={props.onClose}
                app={props.app} projectId={props.projectId} workItemId={props.workItemId} runId={props.runId}
                branchSessions={props.branchSessions} />
    );
  }
  if (detail.kind === "text") {
    return (
      <TextPanel heading={detail.heading} text={detail.text} note={detail.note} at={props.row.at} onClose={props.onClose} />
    );
  }
  // 成果那一行：图上找得到对应的箭头时由调用处打开箭头面板；走到这里时仍把这版的原文写出来，
  // 「看工作过程」照样有入口（这一行仍是成果那一行）
  const work = workTargetOfRow(props.row);
  return (
    <TextPanel heading={props.row.title} text={detail.text} note={null} at={props.row.at} onClose={props.onClose}>
      <WorkEntry app={props.app} projectId={props.projectId} workItemId={props.workItemId} runId={props.runId}
                 branchSessions={props.branchSessions}
                 sourceKey={props.row.key}
                 work={work === null ? null : { target: work, departmentLabel: nameOf(props.graph, work.department) }} />
    </TextPanel>
  );
}

/** 同一个面板：打开的是哪一样就画哪一样。没有打开的东西时整块不出现。 */
export function LoopPanel(props: WorkSource & {
  graph: LoopGraph;
  arrows: readonly LoopArrow[];
  pick: LoopPanelTarget;
  liveContext?: LoopPanelLiveContext;
  onPickArrow: (arrow: LoopArrow) => void;
  onClose: () => void;
}): React.JSX.Element | null {
  if (props.pick === null) {
    return null;
  }
  if (props.pick.kind === "arrow") {
    return (
      <ArrowPanel graph={props.graph} arrow={props.pick.arrow} arrows={props.arrows}
                  onPickArrow={props.onPickArrow} onClose={props.onClose}
                  app={props.app} projectId={props.projectId} workItemId={props.workItemId} runId={props.runId}
                  branchSessions={props.branchSessions} />
    );
  }
  if (props.pick.kind === "row") {
    return (
      <RowPanel graph={props.graph} row={props.pick.row} onClose={props.onClose}
                app={props.app} projectId={props.projectId} workItemId={props.workItemId} runId={props.runId}
                branchSessions={props.branchSessions} />
    );
  }
  const id = props.pick.id;
  const node = props.graph.nodes.find((item) => item.id === id);
  if (node === undefined) {
    return null;
  }
  const ctx = props.liveContext;
  return (
    <LiveWindow
      app={props.app}
      projectId={props.projectId}
      workItemId={props.workItemId}
      runId={props.runId}
      item={ctx?.item ?? null}
      graph={props.graph}
      arrows={props.arrows}
      flow={ctx?.flow ?? []}
      materials={ctx?.materials ?? null}
      decisions={ctx?.decisions ?? []}
      asks={ctx?.asks ?? []}
      department={id}
      roles={ctx?.roles ?? props.graph.nodes.map((n) => ({ id: n.id, label: n.label }))}
      workspaces={ctx?.workspaces}
      settings={ctx?.settings ?? null}
      catalog={ctx?.catalog ?? null}
      attempts={ctx?.attempts ?? []}
      organization={ctx?.organization ?? null}
      blueprintTheme={ctx?.blueprintTheme}
      onSelectDepartment={ctx?.onSelectDepartment ?? (() => undefined)}
      onPickArrow={props.onPickArrow}
      onFocusGuidance={ctx?.onFocusGuidance ?? (() => undefined)}
      onScrollToDecision={ctx?.onScrollToDecision ?? (() => undefined)}
      onClose={props.onClose}
    />
  );
}
