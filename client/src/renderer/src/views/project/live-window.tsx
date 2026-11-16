// 内嵌「现场窗口 · live」（工单 #1811，docs/design/project-organization.md
// 「项目页是循环图加对话」「节点面板与箭头面板接住的内容」）。
//
// 紧贴循环蓝图下方、时序图上方渲染：展示当前选中或活跃职能的遥测摘要带、实时流式输出、
// 按任务归组的步骤标题与就地原始详情展开，以及右栏的指导、询问、多题待决预览与入口链接。

import { useLayoutEffect, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  AskView,
  AttemptView,
  Catalog,
  DecisionView,
  DepartmentWorkspaceResult,
  DraftOrganization,
  ProjectSettingsResult,
  RunStepsResult,
  WorkItemMaterialsResult,
} from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import { Empty, Tag } from "./common";
import { RunningBackgroundCommands } from "./department-parts";
import { RoomLiveOutput } from "./live-output";
import { arrowText, ensureBlueprintStyles } from "./loop-graph";
import {
  askStateText,
  nameOf,
  type BlueprintTheme,
  type FlowRecordLike,
  type LoopArrow,
  type LoopGraph,
  type LoopItemView,
} from "./loop-graph-model";
import {
  NO_GUIDANCE_TEXT,
  NO_LAST_CALL_TEXT,
  NO_WAIT_TEXT,
  workshopFacts,
} from "./node-panel-model";
import {
  liveWindowView,
  type LiveWindowView,
} from "./live-window-model";
import { activationLabel } from "./step-timeline";
import { useSnapshot, type SnapshotState } from "./use-snapshot";
import { WorkLineItem } from "./work-process";
import { workBlocks, workLines, type WorkLine } from "./work-process-model";

export interface LiveWindowProps {
  app: ClientApp;
  projectId: string;
  workItemId: string;
  runId: string;
  item: LoopItemView | null;
  graph: LoopGraph;
  arrows: readonly LoopArrow[];
  flow: readonly FlowRecordLike[];
  materials: WorkItemMaterialsResult | null;
  decisions: readonly DecisionView[];
  asks: readonly AskView[];
  department: string;
  roles: readonly { id: string; label: string }[];
  workspaces?: Readonly<Record<string, SnapshotState<DepartmentWorkspaceResult>>>;
  settings?: ProjectSettingsResult | null;
  catalog?: Catalog | null;
  attempts?: readonly AttemptView[];
  organization?: DraftOrganization | null;
  blueprintTheme?: BlueprintTheme;
  onSelectDepartment: (department: string) => void;
  onPickArrow: (arrow: LoopArrow) => void;
  onFocusGuidance: (department: string) => void;
  onScrollToDecision: (decisionId: string) => void;
  onClose: () => void;
}

function taskTone(status: "待做" | "进行中" | "完成" | "已从计划里去掉"): "ok" | "muted" | undefined {
  return status === "完成" ? "ok" : status === "进行中" ? undefined : "muted";
}

function roleDotTone(item: LoopItemView | null, roleId: string, openDecisions: readonly DecisionView[]): string {
  const workItemId = item?.work_item_id ?? "";
  const hasDecision = openDecisions.some((d) => {
    if (d.status !== "open" || (workItemId !== "" && d.work_item_id !== workItemId)) {
      return false;
    }
    const req = (d.request ?? {}) as Record<string, unknown>;
    return req["department"] === roleId;
  });
  if (hasDecision) {
    return "warn";
  }
  const st = item?.departments?.[roleId]?.state ?? "";
  if (st === "working" || st === "verifying") {
    return "work";
  }
  if (st === "asking") {
    return "ask";
  }
  if (st === "waiting_user") {
    return "warn";
  }
  return "done";
}

export function LiveWindow(props: LiveWindowProps): React.JSX.Element | null {
  useLayoutEffect(() => {
    ensureBlueprintStyles();
  }, []);
  const [activationPick, setActivationPick] = useState<{
    runId: string;
    department: string;
    activationId: string;
  } | null>(null);
  const [openLines, setOpenLines] = useState<Record<string, boolean>>({});

  const externalWorkspace = props.workspaces?.[props.department];
  const fallbackWorkspace = useSnapshot<DepartmentWorkspaceResult>(
    props.app,
    `page.cv.node.workspace.${props.department}`,
    "department.workspace",
    {
      project_id: props.projectId,
      department: props.department,
      work_item: props.workItemId === "" ? null : props.workItemId,
    },
    externalWorkspace !== undefined || props.projectId === "" || props.department === "",
  );
  const workspaceState = externalWorkspace ?? fallbackWorkspace;

  const stepsBase = useSnapshot<RunStepsResult>(
    props.app,
    `page.cv.node.steps.${props.department}`,
    "run.steps",
    { run_id: props.runId, department: props.department },
    props.runId === "" || props.department === "",
  );

  const chosenActivationId = activationPick !== null
    && activationPick.runId === props.runId
    && activationPick.department === props.department
    ? activationPick.activationId
    : null;
  const sameAsBase = chosenActivationId !== null && stepsBase.data?.activation_id === chosenActivationId;
  const stepsPicked = useSnapshot<RunStepsResult>(
    props.app,
    `page.cv.node.steps.${props.department}.${chosenActivationId ?? ""}`,
    "run.steps",
    {
      run_id: props.runId,
      department: props.department,
      activation_id: chosenActivationId ?? "",
    },
    props.runId === "" || props.department === "" || chosenActivationId === null || sameAsBase,
  );
  const stepsData = chosenActivationId === null || sameAsBase
    ? stepsBase.data
    : (stepsPicked.data ?? stepsBase.data);
  const stepsError = stepsBase.error ?? stepsPicked.error;
  const stepsLoading = (chosenActivationId === null ? stepsBase.loading : stepsPicked.loading) && stepsData === null;

  const view: LiveWindowView | null = liveWindowView({
    projectId: props.projectId,
    workItemId: props.workItemId,
    runId: props.runId,
    department: props.department,
    item: props.item,
    graph: props.graph,
    arrows: props.arrows,
    flow: props.flow,
    materials: props.materials,
    workspace: workspaceState.data,
    steps: stepsData,
    asks: props.asks,
    decisions: props.decisions,
    settings: props.settings,
    catalog: props.catalog,
    attempts: props.attempts ?? [],
    organization: props.organization,
  });

  if (view === null) {
    return null;
  }

  const toggleLine = (key: string): void => {
    setOpenLines((current) => ({ ...current, [key]: current[key] !== true }));
  };

  const blocks = workBlocks(workLines(stepsData), stepsData?.tasks ?? []);
  const activations = stepsBase.data?.activations ?? [];
  const activeActivationId = stepsData?.activation_id ?? "";
  const workshop = workshopFacts(workspaceState.data);
  const runningBg = (stepsData?.background_commands ?? []).filter((cmd) => cmd.status === "running");
  const showStreamBox = view.panelView.live || runningBg.length > 0;
  const theme: BlueprintTheme = props.blueprintTheme ?? "dark";

  return (
    <section
      className="y21-live"
      data-bp={theme}
      aria-label={`现场窗口：${view.node.label}`}
      data-testid="live-window"
    >
      <header className="y21-live-head">
        <div className="y21-live-title">
          <span className={`y21-live-kicker${view.telemetry.workingPulse ? "" : " is-idle"}`}>
            {view.telemetry.workingPulse ? "LIVE · 运行中" : view.telemetry.statusLabel}
          </span>
          <h3>现场窗口 · {view.node.label}</h3>
        </div>
        {props.roles.length > 1 ? (
          <div className="y21-live-roles" role="tablist" aria-label="切换检视职能">
            {props.roles.map((role) => {
              const active = role.id === props.department;
              return (
                <button
                  key={role.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={`y21-live-tab${active ? " is-on" : ""}`}
                  data-testid={`live-tab-${role.id}`}
                  onClick={() => props.onSelectDepartment(role.id)}
                >
                  <span className={`y21-dot is-${roleDotTone(props.item, role.id, props.decisions)}`} aria-hidden="true" />
                  <span>{role.label}</span>
                </button>
              );
            })}
          </div>
        ) : null}
        <button
          type="button"
          className="y21-live-close"
          aria-label="收起现场窗口"
          data-testid="live-window-close"
          onClick={props.onClose}
        >
          ×
        </button>
      </header>

      <div className="y21-live-kv">
        <div className="y21-live-row">
          <span className="y21-live-k">当前目标</span>
          <span className="y21-live-v" data-testid={view.node.working ? "node-doing" : undefined}>
            <span>{view.goalText}</span>
            {view.panelView.waiting.length === 0 ? null : (
              <span className="y21-warn-txt" data-testid="node-waiting">
                {view.panelView.waiting.join(" · ")}
              </span>
            )}
            {view.panelView.waited === NO_WAIT_TEXT ? null : (
              <span className="y21-live-dim" data-testid="node-waited">{view.panelView.waited}</span>
            )}
          </span>
        </div>

        <div className="y21-live-row">
          <span className="y21-live-k">生效模型</span>
          <span className="y21-live-v">
            <code>{view.telemetry.modelName}</code>
            {view.telemetry.modelUnusable ? <span className="y21-warn-txt">当前不可用</span> : null}
            {view.telemetry.protocol ? <span className="y21-live-dim">{view.telemetry.protocol}</span> : null}
            <span className="y21-live-dim" title="推理档位">
              {view.telemetry.effort.squares} {view.telemetry.effort.label}
            </span>
          </span>
        </div>

        <div className="y21-live-row">
          <span className="y21-live-k">最近请求</span>
          <span className="y21-live-v">
            {view.recentRequest === null ? (
              <span className="y21-live-dim">{NO_LAST_CALL_TEXT}</span>
            ) : (
              <>
                {view.recentRequest.contextPercent === null ? null : (
                  <span className="y21-live-bar" aria-hidden="true">
                    <i style={{ width: `${Math.min(100, view.recentRequest.contextPercent)}%` }} />
                  </span>
                )}
                <span>上下文：{view.recentRequest.contextText}</span>
                <span className="y21-live-dim">{view.recentRequest.tokensText}</span>
                {view.recentRequest.href ? (
                  <a href={view.recentRequest.href} data-testid="live-recent-request-link">
                    查看这次请求
                  </a>
                ) : null}
              </>
            )}
          </span>
        </div>

        <div className="y21-live-row">
          <span className="y21-live-k">触及</span>
          <span className="y21-live-v">
            {view.touches.kind === "files" ? (
              view.touches.files.map((file) => <code key={file}>{file}</code>)
            ) : (
              <span className="y21-live-dim">写入范围：{view.touches.scopeText}</span>
            )}
          </span>
        </div>

        <div className="y21-live-row is-wide">
          <span className="y21-live-k">工作间</span>
          <span className="y21-live-v">
            {workspaceState.error ? (
              <span className="y21-warn-txt">{readFailureText(workspaceState.error)}</span>
            ) : workshop.length === 0 ? (
              <span className="y21-live-dim">暂无工作间状态</span>
            ) : (
              workshop.map((fact) => (
                <span key={fact.label} className="y21-live-dim">
                  {fact.label}：{fact.value}
                </span>
              ))
            )}
            {view.lastCall && view.lastCall.hasCall ? (
              <span className="y21-live-dim">上次发送：{view.lastCall.summary}</span>
            ) : null}
            {view.recoveryHref ? (
              <a href={view.recoveryHref} className="y21-warn-txt" data-testid="live-recovery-link">
                动作核实
              </a>
            ) : null}
            {view.node.verifier ? (
              <span className="y21-ok-txt">核验角色（放行写它的显示名）</span>
            ) : null}
            {view.node.others > 0 ? (
              <span className="y21-live-dim">另 {view.node.others} 件事项占用</span>
            ) : null}
            {view.node.oldOnly ? (
              <span className="y21-warn-txt">仅存在于旧组织快照</span>
            ) : null}
            {view.partner === null ? null : (
              <span className="y21-live-dim">旁线对接：{nameOf(props.graph, view.partner)}</span>
            )}
          </span>
        </div>
      </div>

      {showStreamBox ? (
        <div className="y21-live-stream" data-testid="node-live">
          {view.panelView.live ? <RoomLiveOutput app={props.app} department={props.department} /> : null}
          <RunningBackgroundCommands commands={stepsData?.background_commands ?? []} />
        </div>
      ) : null}

      <div className="y21-live-cols">
        <div className="y21-live-col" data-testid="live-steps-col">
          <h4>实时工作步骤</h4>
          {activations.length > 1 ? (
            <div className="y21-live-acts" role="tablist" aria-label="这个职能的各次激活">
              {activations.map((activation, index) => {
                const selected = activation.activation_id === activeActivationId;
                return (
                  <button
                    key={activation.activation_id}
                    type="button"
                    role="tab"
                    aria-selected={selected}
                    className={`y21-live-act-btn${selected ? " is-on" : ""}`}
                    onClick={() => setActivationPick({
                      runId: props.runId,
                      department: props.department,
                      activationId: activation.activation_id,
                    })}
                  >
                    {activationLabel(activation, index)}
                  </button>
                );
              })}
            </div>
          ) : null}
          {stepsError ? <Empty text={readFailureText(stepsError)} /> : null}
          {props.runId === "" ? (
            <Empty text="这件事项还没有运行工作步骤" />
          ) : stepsLoading ? (
            <p className="y21-live-dim">正在读取工作步骤…</p>
          ) : blocks.length === 0 ? (
            <Empty text="这个职能这次还没有留下工作步骤" />
          ) : (
            <ol className="y10-wp-tasks">
              {blocks.map((block) => {
                const blockLines: WorkLine[] = block.groups.flatMap((group) => group.lines);
                return (
                  <li key={block.key} className="y10-wp-task">
                    {block.kind === "task" ? (
                      <p className="y10-wp-task-head" data-testid={`work-task-${block.task.number}`}>
                        <b className="y10-wp-task-number">任务 {block.task.number}</b>
                        <span className="y10-wp-task-content">{block.task.content}</span>
                        <Tag tone={taskTone(block.task.status)}>{block.task.status}</Tag>
                      </p>
                    ) : null}
                    <ol className="y10-wp-lines">
                      {blockLines.map((line) => (
                        <WorkLineItem
                          key={line.key}
                          app={props.app}
                          projectId={props.projectId}
                          workItemId={props.workItemId}
                          runId={props.runId}
                          department={props.department}
                          line={line}
                          open={openLines[line.key] === true}
                          onToggle={() => toggleLine(line.key)}
                        />
                      ))}
                    </ol>
                  </li>
                );
              })}
            </ol>
          )}
        </div>

        <div className="y21-live-col" data-testid="live-right-col">
          <h4>往来、指导与待决</h4>

          {view.pendingDecisions.length === 0 ? null : (
            <div className="y21-live-ask" data-testid="live-pending-decisions">
              <strong>等你决定的事项（{view.pendingDecisions.length}）</strong>
              {view.pendingDecisions.map((decision) => (
                <div key={decision.decisionId}>
                  <p>
                    <b>{decision.kindLabel}</b>
                    {decision.roundLabel === "" ? "" : ` · ${decision.roundLabel}`}
                    {decision.blocksText === "" ? "" : ` · ${decision.blocksText}`}
                  </p>
                  {decision.roleNote ? <p className="y21-live-dim">{decision.roleNote}</p> : null}
                  {decision.description ? <p className="y21-live-dim">{decision.description}</p> : null}
                  {decision.questions.length === 0 ? null : (
                    <ol className="y21-live-ask-qs">
                      {decision.questions.map((q) => (
                        <li key={q.id}>
                          <span>{q.question}</span>
                          {q.recommendedLabel ? (
                            <span className="y21-ok-txt">（推荐：{q.recommendedLabel}）</span>
                          ) : null}
                        </li>
                      ))}
                    </ol>
                  )}
                  <p>
                    <button
                      type="button"
                      className="y10-link"
                      data-testid={`live-decision-jump-${decision.decisionId}`}
                      onClick={() => props.onScrollToDecision(decision.decisionId)}
                    >
                      到对话里拍板
                    </button>
                  </p>
                </div>
              ))}
            </div>
          )}

          <div className="y21-live-sub">
            <h5 className="y21-live-sub-title">指导与处理状态</h5>
            {view.guidance.length === 0 ? (
              <span className="y21-live-dim">{NO_GUIDANCE_TEXT}</span>
            ) : (
              <ul className="y21-live-list">
                {view.guidance.map((g) => (
                  <li key={g.id}>
                    <span>
                      <b>第 {g.version} 版</b> · {g.statusLabel}
                      {g.appliedActivationId ? ` · 激活 ${g.appliedActivationId}` : ""}
                    </span>
                    <small className="y21-live-dim">{g.text}</small>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="y21-live-sub">
            <h5 className="y21-live-sub-title">询问往来</h5>
            {view.exchanges.length === 0 ? (
              <span className="y21-live-dim">这个职能还没有询问往来</span>
            ) : (
              <ul className="y21-live-list">
                {view.exchanges.map((ask) => {
                  const detail = props.asks.find((entry) => entry.id === ask.key);
                  const reply = detail?.answer ?? detail?.answer_facts ?? null;
                  return (
                    <li key={ask.key} data-testid={`exchange-${ask.key}`}>
                      <span>
                        {nameOf(props.graph, ask.from)} → {nameOf(props.graph, ask.to)}：{ask.question}
                      </span>
                      <small className={ask.open ? "y21-warn-txt" : "y21-live-dim"}>
                        {askStateText(ask)}
                        {reply ? ` · 答复：${reply}` : ""}
                      </small>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {view.relatedArrows.length === 0 ? null : (
            <div className="y21-live-sub">
              <h5 className="y21-live-sub-title">相关成果箭头</h5>
              <div className="y21-live-arrows">
                {view.relatedArrows.map((arrow) => (
                  <button
                    key={arrow.key}
                    type="button"
                    className="y21-live-arrow-btn"
                    onClick={() => props.onPickArrow(arrow)}
                  >
                    {nameOf(props.graph, arrow.from)} → {nameOf(props.graph, arrow.to)} · {arrowText(arrow)}
                    {arrow.verdict ? `（${arrow.verdict.text}）` : ""}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="y21-live-foot">
            <button
              type="button"
              className="y21-live-btn is-primary"
              data-testid="live-focus-guidance"
              onClick={() => props.onFocusGuidance(props.department)}
            >
              给{view.node.label}发指导
            </button>
            <a className="y21-live-btn" href={view.panelView.links.detail} data-testid="node-detail-link">
              职能详情
            </a>
            <a className="y21-live-btn" href={view.panelView.links.requests} data-testid="node-requests-link">
              本职能的模型请求
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
