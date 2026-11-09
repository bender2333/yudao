// 原文面板里的「看工作过程」（工单 #1658，项目的组织设计说明 4.14「项目页是循环图加对话」第 4 层、
// 工作过程的任务与动作标题设计说明「动作标记」「动作标题」「任务分组」的最后一条）。
//
// 就地展开在原文面板里：每个动作一行标记加标题，连续同一种类的动作折成一行；点一行是原始数据
// （命令、参数、退出状态、输出、这一步的推理与模型文字），原始数据后面用这一步的调用尝试编号
// 进请求详情页（被丢弃的那几次也能点）。行、折叠、原始数据的几格与时序图一行到激活的对应都在
// work-process-model.ts 里，这个文件只做取数与排版。
//
// 读的事实只有 run.steps：先按职能取这个职能的激活，找出与这一行对得上的那一次（成果按第几轮，
// 询问与回答按会话编号）；同一轮有几次激活时都列出来，默认最后一次，点别的格用那个编号重取。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { EventDetailResult, RunStepsResult, StepText } from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import { paths } from "../../shell/routing";
import { actionRow, toolOutput, type ExternalSourceRefView } from "./action-table.ts";
import { Empty, Modal, Tag } from "./common";
import { ExternalSource } from "./external-source.tsx";
import { formatTime } from "./labels";
import { activationLabel } from "./step-timeline.ts";
import { StepTextItem } from "./step-timeline.tsx";
import { useSnapshot } from "./use-snapshot";
import {
  activationsOf,
  attemptLinkText,
  attemptLinks,
  noActivationText,
  rawFields,
  targetText,
  workGroups,
  workLines,
  type WorkGroup,
  type WorkLine,
  type WorkTarget,
} from "./work-process-model.ts";

/**
 * 看工作过程：一个「看工作过程」的入口，展开以后是那一轮或那次回答的经过。
 *
 * `departmentLabel` 是这个职能的显示名（从图上取），写在展开后的第一行，用户认得出看的是谁的那一次。
 */
export function WorkProcess(props: {
  app: ClientApp;
  projectId: string;
  workItemId: string;
  runId: string;
  target: WorkTarget;
  departmentLabel: string;
  /** 这个事项的询问编号（图上的询问）：按第几轮找激活时排掉询问分支的那几次 */
  branchSessions: readonly string[];
}) {
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  const department = props.target.department;
  const ready = open && props.runId !== "";
  // 这个职能的激活列表：拿到以后按这一行的键找出对得上的那几次
  const list = useSnapshot<RunStepsResult>(
    props.app,
    `page.cv.work.activations.${department}`,
    "run.steps",
    { run_id: props.runId, department },
    !ready,
  );
  const matches = activationsOf(list.data?.activations ?? [], props.target, props.branchSessions);
  const picked = (chosen === null ? undefined : matches.find((item) => item.activation_id === chosen))
    ?? matches[matches.length - 1]
    ?? null;
  // 列表那一份恰好是选中的这一次时不再重取（默认看最后一次，通常就是它）
  const same = picked !== null && list.data !== null && list.data.activation_id === picked.activation_id;
  const steps = useSnapshot<RunStepsResult>(
    props.app,
    `page.cv.work.steps.${department}.${picked === null ? "" : picked.activation_id}`,
    "run.steps",
    { run_id: props.runId, department, activation_id: picked === null ? "" : picked.activation_id },
    !ready || picked === null || same,
  );
  const data = same ? list.data : steps.data;
  const error = list.error ?? steps.error;
  return (
    <div className="y10-wp">
      <button
        type="button"
        className="y10-link y10-wp-toggle"
        aria-expanded={open}
        data-testid="work-process-toggle"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "收起工作过程" : "看工作过程"}
      </button>
      {open ? (
        <div className="y10-wp-body" data-testid="work-process">
          <p className="y10-wp-head">
            工作过程
            <small> {props.departmentLabel === "" ? "" : `${props.departmentLabel} · `}{targetText(props.target)}</small>
          </p>
          {error === null ? null : <Empty text={readFailureText(error)} />}
          {ready && data === null && error === null ? (
            <p className="y10-note note">正在读取这一轮的工作过程</p>
          ) : null}
          {ready && list.data !== null && matches.length === 0 ? <Empty text={noActivationText(props.target)} /> : null}
          {matches.length > 1 ? (
            <div className="y10-wp-activations" role="tablist" aria-label="这一轮的几次工作">
              {matches.map((activation, index) => (
                <button
                  key={activation.activation_id}
                  type="button"
                  role="tab"
                  aria-selected={picked !== null && activation.activation_id === picked.activation_id}
                  className={`y10-wp-activation${picked !== null && activation.activation_id === picked.activation_id ? " is-active" : ""}`}
                  onClick={() => setChosen(activation.activation_id)}
                >
                  {activationLabel(activation, index)}
                </button>
              ))}
            </div>
          ) : null}
          {data === null ? null : (
            <WorkLineList
              app={props.app}
              projectId={props.projectId}
              workItemId={props.workItemId}
              runId={props.runId}
              department={department}
              groups={workGroups(workLines(data))}
            />
          )}
        </div>
      ) : null}
    </div>
  );
}

/** 一次激活的全部行：折起来的组一行，其余每个动作一行；点一行展开原始数据。 */
function WorkLineList(props: {
  app: ClientApp;
  projectId: string;
  workItemId: string;
  runId: string;
  department: string;
  groups: WorkGroup[];
}) {
  const [openLines, setOpenLines] = useState<Record<string, boolean>>({});
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const toggleLine = (key: string): void => {
    setOpenLines((current) => ({ ...current, [key]: current[key] !== true }));
  };
  const toggleGroup = (key: string): void => {
    setOpenGroups((current) => ({ ...current, [key]: current[key] !== true }));
  };
  const item = (line: WorkLine) => (
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
  );
  if (props.groups.length === 0) {
    return <Empty text="这次工作没有留下步骤" />;
  }
  return (
    <ol className="y10-wp-lines">
      {props.groups.map((group) => group.foldedTitle === "" ? group.lines.map(item) : (
        <li key={group.key} className="y10-wp-group">
          <button
            type="button"
            className="y10-wp-line"
            aria-expanded={openGroups[group.key] === true}
            onClick={() => toggleGroup(group.key)}
          >
            <span className="y10-wp-mark">{group.lines[0].mark ?? ""}</span>
            <span className="y10-wp-title">{group.foldedTitle}</span>
          </button>
          {openGroups[group.key] === true ? <ol className="y10-wp-sublines">{group.lines.map(item)}</ol> : null}
        </li>
      ))}
    </ol>
  );
}

/**
 * 一行：标记、标题、系统量到的事实与标题来源。点这一行展开原始数据：
 * 命令、参数、退出状态、输出、这一步的推理与模型文字、外部来源，以及进请求详情页的那几个入口。
 */
function WorkLineItem(props: {
  app: ClientApp;
  projectId: string;
  workItemId: string;
  runId: string;
  department: string;
  line: WorkLine;
  open: boolean;
  onToggle: () => void;
}) {
  const [source, setSource] = useState<ExternalSourceRefView | null>(null);
  const [openTexts, setOpenTexts] = useState<Record<string, boolean>>({});
  const action = props.line.action;
  // 原始数据里的输出与回执要读这条动作的回执事件的工件；没有回执时没有可读的
  const eventId = action === null || action.receipt === null ? "" : action.receipt.event_id;
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    `page.cv.work.raw.${props.line.key}`,
    "event.detail",
    { event_id: eventId },
    !props.open || eventId === "",
  );
  const artifacts = detail.data === null ? null : detail.data.artifacts;
  const output = artifacts === null ? null : artifacts["output"];
  const row = action === null ? null : actionRow(action, { output: toolOutput(artifacts) });
  const fields = rawFields({ action, output, summary: row === null ? "" : row.summaryText });
  const toggleText = (id: string): void => {
    setOpenTexts((current) => ({ ...current, [id]: current[id] !== true }));
  };
  return (
    <li className="y10-wp-item">
      <button type="button" className="y10-wp-line" aria-expanded={props.open} onClick={props.onToggle}>
        {props.line.mark === null ? null : <span className="y10-wp-mark">{props.line.mark}</span>}
        <span className="y10-wp-title">{props.line.title}</span>
        {props.line.titleSource === "作者" ? <Tag tone="muted">作者写的</Tag> : null}
        {props.line.facts.map((fact) => (
          <Tag key={fact} tone={fact === "改了文件" ? "warn" : "danger"}>{fact}</Tag>
        ))}
      </button>
      {props.open ? (
        <div className="y10-wp-raw">
          {detail.error === null ? null : <p className="y10-wp-raw-row">{readFailureText(detail.error)}</p>}
          {fields.length === 0 ? null : (
            <dl className="y10-wp-fields">
              {fields.map((field) => (
                <div key={field.label} className="y10-wp-field">
                  <dt>{field.label}</dt>
                  <dd className="y10-code">{field.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {row !== null && row.external !== null ? (
            <p className="y10-wp-raw-row">
              <button type="button" className="y10-link" onClick={() => setSource(row.external)}>查看外部来源</button>
            </p>
          ) : null}
          <StepTexts app={props.app} kind="thinking" items={props.line.reasoning}
                     open={openTexts} onToggle={toggleText} />
          <StepTexts app={props.app} kind="saying" items={props.line.texts}
                     open={openTexts} onToggle={toggleText} />
          <p className="y10-wp-raw-row y10-muted">
            {props.line.stepId === null ? "没有归到某一步" : `第 ${props.line.stepId} 步`} · {formatTime(props.line.at)}
          </p>
          {attemptLinks(props.line).length === 0 ? null : (
            <p className="y10-wp-raw-row y10-wp-attempts">
              {attemptLinks(props.line).map((attempt, index) => (
                <button
                  key={attempt.id}
                  type="button"
                  className="y10-link"
                  onClick={() => {
                    window.location.hash = paths.observeDetail(props.projectId, attempt.id, {
                      workItem: props.workItemId, runId: props.runId, department: props.department,
                    });
                  }}
                >
                  {attemptLinkText(attempt, index)}
                </button>
              ))}
            </p>
          )}
        </div>
      ) : null}
      {source === null ? null : (
        <Modal title="外部来源" onClose={() => setSource(null)}>
          <ExternalSource app={props.app} source={source} />
        </Modal>
      )}
    </li>
  );
}

/** 这一步的推理或模型文字：与部门工作间的步骤时间线用同一份（展开全文、读不出来时照实说明）。 */
function StepTexts(props: {
  app: ClientApp;
  kind: "thinking" | "saying";
  items: StepText[];
  open: Record<string, boolean>;
  onToggle: (eventId: string) => void;
}) {
  if (props.items.length === 0) {
    return null;
  }
  return (
    <div className="y10-wp-texts">
      <b className="y10-wp-texts-title">{props.kind === "thinking" ? "这一步的推理" : "这一步的模型文字"}</b>
      {props.items.map((item) => (
        <StepTextItem
          key={item.event_id}
          app={props.app}
          kind={props.kind}
          item={item}
          expanded={props.open[item.event_id] === true}
          onToggle={() => props.onToggle(item.event_id)}
        />
      ))}
    </div>
  );
}
