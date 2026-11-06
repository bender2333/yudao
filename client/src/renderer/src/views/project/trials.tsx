// 部门工作间的「试用记录」页签（工单 #153；浏览器与 computer use docs/design/browser-and-computer-use.md「查询」、
// 「页面与画面」；数据来自工单 #152 的 run.trials 与 evidence.screenshot）。
//
// 页签读这个 run 的试用记录，只显示本部门的那一份：试用会话（种类、启动方式、试用副本与交付快照的比较、开始
// 与结束），试用用例（引用的验收条件与原文、计划的操作、预期结果、结论与观察到的结果），以及每一步的操作与
// 截图缩略图。截图按工件引用经 evidence.screenshot 取内容，所属事件是产出这张截图的那条动作回执（run.actions
// 的回执带事件位置）。点开缩略图看原尺寸，旁边列出同一步的页面结构摘录。
//
// 模型只读到文字时，页签上写明「模型只读取文字」：请求的图像输入方式取自查询给出的
// request_had_images，截图照常显示，每张旁边标明模型有没有看到它。页面上不写英文内部标识与开发者措辞：
// 会话种类、副本来源、结束方式、步骤状态与工具名都在 labels.ts 里换成中文，树摘要与标识不显示。

import { useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  RunActionsResult,
  RunTrialsResult,
  ScreenshotEvidenceResult,
  TrialCaseView,
  TrialDepartmentView,
  TrialSessionView,
  TrialStepView,
} from "../../api/generated/types.gen";
import { StatusMark } from "../../shell/kit";
import { readFailureText } from "../../contract/read-failure";
import { Empty, Modal, Table, Tag } from "./common";
import {
  SCREENSHOT_READING,
  SCREENSHOT_UNREADABLE,
  TRIAL_EVIDENCE_TAG,
  TRIAL_NO_CASE,
  TRIAL_NO_SESSION,
  TRIAL_TEXT_ONLY_NOTICE,
  TRIAL_UNNAMED_CASE,
  TRIAL_UNNAMED_CRITERION,
  TRIAL_UNNAMED_LAUNCH,
  formatTime,
  trialCaseResultView,
  trialOperationText,
  trialSessionKindName,
  trialSessionStateName,
  trialShotModelText,
  trialSnapshotText,
  trialStepStatusName,
} from "./labels";
import { useSnapshot } from "./use-snapshot";

// 缩略图的尺寸（浏览器截图 1280×800，界面等比缩小）：与资料页的逐条结论表同一大小
const SHOT_STYLE: CSSProperties = {
  maxHeight: 64,
  maxWidth: 96,
  padding: 0,
  border: "1px solid var(--line, #d0d0d0)",
  borderRadius: 4,
  background: "var(--surface, #fff)",
  cursor: "zoom-in",
};

// 一张截图的工件引用：查询 evidence.screenshot 时按这四项取内容
export interface TrialShotRef {
  kind: string;
  contentHash: string;
  path: string;
  mediaType: string | null;
}

export interface TrialShotRow {
  key: string;
  // 产出这张截图的那条动作回执的事件标识；动作还没有回执时为空，这一张读不出来
  eventId: string | null;
  ref: TrialShotRef;
  // 收到这个结果的请求是否包含图像：真、假与没有记录三种
  modelSaw: boolean | null;
}

export interface TrialStepRow {
  key: string;
  operation: string;
  statusText: string;
  evidence: boolean;
  accessibility: string | null;
  shots: TrialShotRow[];
}

export interface TrialCriterionRow {
  name: string;
  text: string | null;
}

export interface TrialCaseRow {
  key: string;
  title: string;
  criteria: TrialCriterionRow[];
  plan: string[];
  expected: string;
  resultText: string;
  resultKind: string;
  observed: string;
  reason: string;
  steps: TrialStepRow[];
}

export interface TrialSessionRow {
  key: string;
  kindName: string;
  launchName: string;
  copyText: string;
  startedAt: string;
  endedAt: string | null;
  stateText: string;
}

export interface TrialsView {
  sessions: TrialSessionRow[];
  cases: TrialCaseRow[];
  // 这次试用里至少一步之后的那次请求不含图像：页签上写明模型只读取文字
  textOnly: boolean;
}

function trimmed(value: string | null | undefined): string {
  return (value ?? "").trim();
}

function named(value: string | null | undefined, fallback: string): string {
  const got = trimmed(value);
  return got === "" ? fallback : got;
}

// 动作的身份与查询试用的步骤是同一组：激活、步骤与模型给出的调用编号
function actionKey(activationId: string | null | undefined, stepId: number | null | undefined,
                   identity: string): string {
  return `${activationId ?? ""}\u0000${stepId ?? ""}\u0000${identity}`;
}

// 动作身份到回执事件的对照：截图按所属事件经 evidence.screenshot 取内容
function actionEventIds(actions: RunActionsResult | null): Map<string, string> {
  const out = new Map<string, string>();
  for (const action of actions?.actions ?? []) {
    if (action.receipt === null) {
      continue;
    }
    out.set(actionKey(action.activation_id, action.step_id, action.action_id), action.receipt.event_id);
  }
  return out;
}

// 截图的工件引用：四项里取不出可核对的标识时不算一张截图（空引用不画一个空框）
function shotRef(value: Record<string, unknown>): TrialShotRef | null {
  const kind = typeof value.kind === "string" ? value.kind.trim() : "";
  const contentHash = typeof value.content_hash === "string" ? value.content_hash.trim() : "";
  const path = typeof value.path === "string" ? value.path.trim() : "";
  if (kind === "" || contentHash === "" || path === "") {
    return null;
  }
  const mediaType = typeof value.media_type === "string" && value.media_type.trim() !== ""
    ? value.media_type.trim() : null;
  return { kind, contentHash, path, mediaType };
}

function shotRows(step: TrialStepView, eventId: string | null): TrialShotRow[] {
  return (step.screenshots ?? []).map((raw, index) => {
    const ref = shotRef(raw);
    return ref === null ? null : {
      key: `${index}-${ref.contentHash}`,
      eventId,
      ref,
      modelSaw: step.request_had_images ?? null,
    };
  }).filter((item): item is TrialShotRow => item !== null);
}

function stepRow(step: TrialStepView, index: number, eventIds: Map<string, string>): TrialStepRow {
  const accessibility = trimmed(step.accessibility);
  return {
    key: `${index}-${step.identity}`,
    operation: trialOperationText(step.tool, step.input),
    statusText: trialStepStatusName(step.status),
    evidence: step.evidence === true,
    accessibility: accessibility === "" ? null : accessibility,
    shots: shotRows(step, eventIds.get(actionKey(step.activation_id, step.step_id, step.identity)) ?? null),
  };
}

function caseRow(item: TrialCaseView, index: number, eventIds: Map<string, string>): TrialCaseRow {
  const result = trialCaseResultView(item);
  return {
    key: `${index}-${item.case_id}`,
    title: named(item.title, TRIAL_UNNAMED_CASE),
    criteria: item.criteria.map((criterion) => ({
      name: named(criterion.criterion, TRIAL_UNNAMED_CRITERION),
      text: trimmed(criterion.text) === "" ? null : trimmed(criterion.text),
    })),
    plan: item.plan.map((line) => line.trim()).filter((line) => line !== ""),
    expected: trimmed(item.expected),
    resultText: result.text,
    resultKind: result.kind,
    observed: trimmed(item.observed),
    reason: trimmed(item.reason),
    steps: item.steps.map((step, position) => stepRow(step, position, eventIds)),
  };
}

function sessionRow(item: TrialSessionView, index: number): TrialSessionRow {
  return {
    key: `${index}-${item.session_id}`,
    kindName: trialSessionKindName(item.kind),
    launchName: named(item.launch_name, TRIAL_UNNAMED_LAUNCH),
    copyText: trialSnapshotText(item),
    startedAt: item.started_at,
    endedAt: item.status === "ended" ? item.ended_at ?? null : null,
    stateText: trialSessionStateName(item),
  };
}

/**
 * 页签要画的内容：只取本部门那一组试用记录；截图所属的事件取自 run.actions 的回执。
 * `group` 为空（这个部门没有试用记录）时两个清单都是空的。
 */
export function trialView(group: TrialDepartmentView | null, actions: RunActionsResult | null): TrialsView {
  const eventIds = actionEventIds(actions);
  return {
    sessions: (group?.sessions ?? []).map(sessionRow),
    cases: (group?.cases ?? []).map((item, index) => caseRow(item, index, eventIds)),
    textOnly: (group?.cases ?? []).some((item) => item.steps.some((step) => step.request_had_images === false)),
  };
}

// 页签：读 run.trials 与 run.actions，取出本部门的那一份交给 TrialRecords 画
export function TrialsPanel(props: { app: ClientApp; runId: string | null; department: string }) {
  const skip = props.runId === null;
  const runId = props.runId ?? "";
  const trials = useSnapshot<RunTrialsResult>(
    props.app, "page.dept.trials", "run.trials", { run_id: runId }, skip);
  // 截图按所属事件读取：回执的事件标识在 run.actions 的结果里
  const actions = useSnapshot<RunActionsResult>(
    props.app, "page.dept.trials.actions", "run.actions", { run_id: runId }, skip);
  if (skip) {
    return <Empty text="这次运行没有试用记录" />;
  }
  if (trials.error !== null) {
    return <p className="y10-note note" role="status">{readFailureText(trials.error)}</p>;
  }
  if (trials.data === null) {
    return <p className="y10-note note">正在读取试用记录</p>;
  }
  const group = trials.data.departments.find((item) => item.department === props.department) ?? null;
  const view = trialView(group, actions.data);
  if (view.sessions.length === 0 && view.cases.length === 0) {
    return <Empty text="这个部门这次运行没有试用记录" />;
  }
  return <TrialRecords app={props.app} view={view} />;
}

// 试用记录的正文：会话一张表，用例逐个列出（纯渲染，单元测试直接给视图）
export function TrialRecords(props: { app: ClientApp | null; view: TrialsView }) {
  const view = props.view;
  return (
    <div className="y10-trials">
      {view.textOnly ? <p className="y10-note note" role="status">{TRIAL_TEXT_ONLY_NOTICE}</p> : null}
      <h3 className="y10-h3 sub">试用会话（{view.sessions.length} 个）</h3>
      {view.sessions.length === 0 ? <Empty text={TRIAL_NO_SESSION} /> : (
        <Table
          head={["种类", "启动方式", "试用副本", "开始", "结束"]}
          rows={view.sessions.map((row) => [
            row.kindName,
            row.launchName,
            row.copyText,
            formatTime(row.startedAt),
            row.endedAt === null ? row.stateText : `${row.stateText} · ${formatTime(row.endedAt)}`,
          ])}
        />
      )}
      <h3 className="y10-h3 sub">试用用例（{view.cases.length} 个）</h3>
      {view.cases.length === 0 ? <Empty text={TRIAL_NO_CASE} /> : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 10 }}>
          {view.cases.map((item) => (
            <li key={item.key}>
              <TrialCaseCard app={props.app} item={item} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TrialCaseCard(props: { app: ClientApp | null; item: TrialCaseRow }) {
  const item = props.item;
  return (
    <article className="y10-mt-doc">
      <header className="y10-mt-doc-head">
        <strong>{item.title}</strong>
        <StatusMark kind={item.resultKind} text={item.resultText} />
      </header>
      {item.criteria.length === 0 ? null : (
        <p className="y10-note note">
          验收条件：
          {item.criteria.map((criterion) => (criterion.text === null
            ? criterion.name
            : `${criterion.name} ${criterion.text}`)).join("；")}
        </p>
      )}
      {item.plan.length === 0 ? null : (
        <>
          <h4 className="y10-mt-sub">计划的操作</h4>
          <ol>
            {item.plan.map((line, index) => <li key={index}>{line}</li>)}
          </ol>
        </>
      )}
      {item.expected === "" ? null : <p className="y10-note note">预期结果：{item.expected}</p>}
      {item.observed === "" ? null : <p className="y10-note note">观察到的结果：{item.observed}</p>}
      {item.reason === "" ? null : <p className="y10-note note">原因：{item.reason}</p>}
      <h4 className="y10-mt-sub">步骤（{item.steps.length} 步）</h4>
      {item.steps.length === 0 ? <Empty text="这个用例没有步骤" /> : (
        <ol className="y10-mt-receipts">
          {item.steps.map((step) => (
            <li key={step.key}>
              <TrialStepItem app={props.app} item={step} viewPrefix={`page.dept.trials.${item.key}`} />
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

function TrialStepItem(props: { app: ClientApp | null; item: TrialStepRow; viewPrefix: string }) {
  const item = props.item;
  return (
    <>
      <span>{item.operation}</span>
      <span className="y10-muted">{item.statusText}</span>
      {item.evidence ? <Tag tone="ok">{TRIAL_EVIDENCE_TAG}</Tag> : null}
      {item.shots.length === 0 ? null : (
        <div className="y10-mt-shots">
          {item.shots.map((shot, index) => (
            <ShotThumb
              key={shot.key}
              app={props.app}
              viewId={`${props.viewPrefix}.shot.${item.key}.${index}`}
              shot={shot}
              label={`${item.operation} 的截图 ${index + 1}`}
              accessibility={item.accessibility}
            />
          ))}
        </div>
      )}
    </>
  );
}

// 一张截图：按工件引用读内容，读到以后画缩略图；点开看原尺寸，旁边列出同一步的页面结构摘录。
// 读不出来时写下这一句，不画一个空框。模型有没有看到它写在缩略图下面
function ShotThumb(props: {
  app: ClientApp | null;
  viewId: string;
  shot: TrialShotRow;
  label: string;
  accessibility: string | null;
}) {
  const state = useSnapshot<ScreenshotEvidenceResult>(props.app, props.viewId, "evidence.screenshot", {
    event_id: props.shot.eventId ?? "",
    kind: props.shot.ref.kind,
    content_hash: props.shot.ref.contentHash,
    path: props.shot.ref.path,
    media_type: props.shot.ref.mediaType,
  }, props.shot.eventId === null);
  const [open, setOpen] = useState(false);
  const modelSaw = <span className="y10-muted">{trialShotModelText(props.shot.modelSaw)}</span>;
  const wrap = (content: ReactNode) => (
    <div className="y10-trials-shot" style={{ display: "grid", gap: 4 }}>{content}</div>
  );
  if (props.shot.eventId === null || state.error !== null) {
    return wrap(<>{modelSaw}<span className="y10-muted">{SCREENSHOT_UNREADABLE}</span></>);
  }
  const data = state.data;
  if (data === null) {
    return wrap(<>{modelSaw}<span className="y10-muted">{SCREENSHOT_READING}</span></>);
  }
  if (!data.media_type.startsWith("image/") || data.base64 === "") {
    return wrap(<>{modelSaw}<span className="y10-muted">{SCREENSHOT_UNREADABLE}</span></>);
  }
  const src = `data:${data.media_type};base64,${data.base64}`;
  return wrap(
    <>
      <button
        type="button"
        className="y10-mt-shot"
        style={SHOT_STYLE}
        aria-label={`${props.label}，点击查看原尺寸`}
        onClick={() => setOpen(true)}
      >
        <img src={src} alt={props.label} />
      </button>
      {modelSaw}
      {open ? (
        <Modal title="试用步骤的截图" onClose={() => setOpen(false)}>
          <p className="y10-note note">{props.label}</p>
          <img
            src={src}
            alt={props.label}
            style={{
              display: "block",
              maxWidth: "100%",
              height: "auto",
              border: "1px solid var(--line, #d0d0d0)",
              borderRadius: 6,
            }}
          />
          <h3 className="y10-h3 sub">这一步的页面结构</h3>
          {props.accessibility === null
            ? <p className="y10-note note">这一步没有记录页面结构</p>
            : <pre className="y10-pre raw">{props.accessibility}</pre>}
        </Modal>
      ) : null}
    </>,
  );
}
