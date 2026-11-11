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
import type { DepartmentWorkspaceResult, RunStepsResult } from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import type { LoopArrow, LoopGraph, LoopNode } from "./loop-graph-model";
import { askStateText, nameOf, versionsOf } from "./loop-graph-model";
import { arrowText, type LoopPanelPick } from "./loop-graph";
import { ArrowSections } from "./arrow-panel.tsx";
import { RunningBackgroundCommands } from "./department-parts.tsx";
import { formatTime } from "./labels";
import { RoomLiveOutput } from "./live-output";
import { nodePanelView } from "./node-panel-model.ts";
import type { SequenceDetail, SequenceRow } from "./sequence-model";
import { useSnapshot } from "./use-snapshot";
import { WorkProcess } from "./work-process.tsx";
import { doingText, nodeDoing, workTargetOfArrow, workTargetOfRow, type WorkTarget } from "./work-process-model.ts";

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

function NodePanel(props: {
  app: ClientApp;
  projectId: string;
  workItemId: string;
  runId: string;
  graph: LoopGraph;
  node: LoopNode;
  onClose: () => void;
}): React.JSX.Element {
  const { node } = props;
  const partner = props.graph.side.find((part) => part.node.id === node.id)?.partner ?? null;
  // 它的往来：开着的询问在前，标「还没回答」；和节点上的字出自同一份事实（run.asks）
  const exchanges = props.graph.asks.filter((ask) => ask.from === node.id || ask.to === node.id);
  // 「在做什么」（工单 #1662）：这个职能正在工作时读同一个 run.steps，写当前任务加最近一个动作的标题；
  // 不在工作时不读也不写（外部 agent 的状态条不在这里）
  const steps = useSnapshot<RunStepsResult>(
    props.app,
    `page.cv.node.steps.${node.id}`,
    "run.steps",
    { run_id: props.runId, department: node.id },
    !node.working || props.runId === "",
  );
  // 工作间（工单 #1712）：执行机器、等模型服务、结果未知、未读指导、角色、最近一次请求的模型与档位
  // 与部门页读同一条查询（department.workspace），不新增查询
  const workspace = useSnapshot<DepartmentWorkspaceResult>(
    props.app,
    `page.cv.node.workspace.${node.id}`,
    "department.workspace",
    { project_id: props.projectId, department: node.id, work_item: props.workItemId === "" ? null : props.workItemId },
    props.projectId === "",
  );
  const doing = nodeDoing(steps.data, node.working);
  const view = nodePanelView(node, workspace.data, props.projectId, props.workItemId);
  return (
    <section className="y10-cv-panel v20-node-panel" aria-label={node.label} data-testid="loop-panel-node">
      <button type="button" className="y10-icon-btn y10-cv-close" aria-label="收起" onClick={props.onClose}>×</button>
      <h3>{node.label}<small> {view.state}</small></h3>
      {view.waiting.length === 0 ? null : (
        <ul className="y10-list v20-node-waiting" data-testid="node-waiting">
          {view.waiting.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}
      {doing === null ? null : (
        <p className="y10-cv-doing" data-testid="node-doing">
          <b>在做什么</b>
          <span>{doingText(doing)}</span>
        </p>
      )}
      {steps.error === null ? null : <p className="y10-cv-note">{readFailureText(steps.error)}</p>}
      {view.live ? (
        <div className="v20-node-live" data-testid="node-live">
          <RoomLiveOutput app={props.app} department={node.id} />
          <RunningBackgroundCommands commands={steps.data?.background_commands ?? []} />
        </div>
      ) : null}
      {workspace.error === null ? null : <p className="y10-cv-note">{readFailureText(workspace.error)}</p>}
      <ul className="y10-list y10-cv-facts v20-node-facts">
        {view.facts.map((fact) => <li key={fact.label}>{fact.label}：{fact.value}</li>)}
        {node.verifier ? <li>它的角色是核验角色：核验交付的那一版，放行时写它的显示名</li> : null}
        {node.others > 0 ? <li>别的事项正在这个职能上的有 {node.others} 件</li> : null}
        {node.oldOnly ? <li>这个职能只在旧组织里：项目现在的组织里已经没有它，这件事项仍按它冻结的组织做完</li> : null}
        {partner === null ? null : <li>它在旁边接询问，与主线上「{nameOf(props.graph, partner)}」往来</li>}
      </ul>
      {exchanges.length === 0 ? null : (
        <div className="y10-cv-exchanges">
          <b>它的往来</b>
          <ul className="y10-list">
            {exchanges.map((ask) => (
              <li key={ask.key} data-testid={`exchange-${ask.key}`}>
                {nameOf(props.graph, ask.from)} → {nameOf(props.graph, ask.to)}：{ask.question}
                <span className={`y10-cv-ask-state${ask.open ? " is-open" : ""}`}>{askStateText(ask)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="v20-node-entries">
        <a className="y10-btn is-small small" href={view.links.detail} data-testid="node-detail-link">职能详情</a>
        <a className="y10-btn is-small small" href={view.links.requests} data-testid="node-requests-link">本职能的模型请求</a>
      </div>
    </section>
  );
}

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
  return node === undefined
    ? null
    : <NodePanel graph={props.graph} node={node} onClose={props.onClose}
                 app={props.app} projectId={props.projectId} workItemId={props.workItemId} runId={props.runId} />;
}
