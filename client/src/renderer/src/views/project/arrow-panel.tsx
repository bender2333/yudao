// 箭头面板里的各段（工单 #1711）。
//
// 设计说明 docs/design/project-organization.md「节点面板与箭头面板接住的内容」按箭头是哪一种成果分段，
// 「项目页上的内容在哪里看」给出每段读哪一条查询；验收见 #1707 的补充条第 15 条：
// 交付的箭头面板里能下载单个文件；放行或打回的那一版看得到逐条结论与证据；
// 直做交完成的那一版有箭头，面板写「开环完成：没有人核验」。
//
// 各段的文字与结构由 arrow-panel-model.ts 算，这里只按它画。复用的三处：逐条结论的表与截图缩略图
// 在 criteria-table.tsx，试用用例的步骤与截图（点开看原尺寸）在 trials.tsx，下载用的 data URL
// 在 materials-download.ts。旧资料页已随工单 #1716 删掉，这三处只由这里与逐条结论表面板用。
//
// 外部来源的原文沿用同一块面板下面工作过程里那一步的「查看外部来源」（work-process.tsx）：设计说明
// 「项目页上的内容在哪里看」把外部来源的原文放在工作过程那一步的原始数据里。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  AcceptanceCoverageResult,
  DeliveryFileResult,
  ReviewEntry,
  RunActionsResult,
  RunTrialsResult,
  WorkItemInputsResult,
  WorkItemMaterialsResult,
} from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import {
  MISSING_REVIEW_TEXT,
  NO_FILES_TEXT,
  arrowPanelView,
  citedCasesOf,
  type CitedCasesView,
  type ConclusionView,
  type InputsView,
  type MaterialsLike,
  type RoundView,
  type VersionView,
} from "./arrow-panel-model";
import { CriteriaTable } from "./criteria-table";
import { Tag } from "./common";
import { formatTime } from "./labels";
import { fileDownload } from "./materials-download";
import { readView } from "./materials-read";
import { SOURCE, type LoopArrow, type LoopGraph } from "./loop-graph-model.ts";
import { TrialRecords, trialView, type TrialsView } from "./trials";
import { useSnapshot, type SnapshotState } from "./use-snapshot";

export interface ArrowSectionsProps {
  app: ClientApp;
  projectId: string;
  workItemId: string;
  runId: string;
  graph: LoopGraph;
  arrow: LoopArrow;
  /** 同一种成果的几版，按先后 */
  versions: readonly LoopArrow[];
}

/**
 * 箭头面板的正文：结论、逐条结论与证据、这一版（摘要、差异、文件清单与下载）、
 * 你的输入各版与进度、建档各轮、开环完成一句。哪几段出现由模型按箭头的种类给。
 */
export function ArrowSections(props: ArrowSectionsProps) {
  const key = props.arrow.key;
  // 这一版在材料里的那一条：文件清单、摘要与单个文件都按它取
  const materials = useSnapshot<WorkItemMaterialsResult>(
    props.app, `page.cv.arrow.materials.${key}`, "work_item.materials",
    { project_id: props.projectId, work_item: props.workItemId }, props.workItemId === "");
  // 从图外进来的箭头才有输入各版与处理进度
  const fromOutside = props.arrow.from === SOURCE;
  const inputs = useSnapshot<WorkItemInputsResult>(
    props.app, "page.cv.arrow.inputs", "work_item.inputs",
    { project_id: props.projectId, work_item: props.workItemId }, props.workItemId === "" || !fromOutside);
  // 检验覆盖与试用用例只给标着结论的那一版：放行取这一版所在那次运行的放行记录（可回放）
  const reviewed = props.arrow.verdict !== null;
  const coverage = useSnapshot<AcceptanceCoverageResult>(
    props.app, "page.cv.arrow.coverage", "acceptance.coverage",
    { run_id: props.runId }, props.runId === "" || !reviewed);
  // 逐条结论引用的试用用例：步骤与截图在 run.trials 里，截图所属事件取自 run.actions
  const trials = useSnapshot<RunTrialsResult>(
    props.app, "page.cv.arrow.trials", "run.trials", { run_id: props.runId }, props.runId === "" || !reviewed);
  const actions = useSnapshot<RunActionsResult>(
    props.app, "page.cv.arrow.actions", "run.actions", { run_id: props.runId }, props.runId === "" || !reviewed);

  const materialsData = materials.data as MaterialsLike | null;
  const view = arrowPanelView({
    arrow: props.arrow,
    versions: props.versions,
    materials: materialsData,
    inputs: inputs.data,
    coverage: coverage.data,
    verifier: props.graph.nodes.some((node) => node.verifier),
    ended: props.graph.endText,
  });
  const review = view.conclusion === null ? null : reviewOf(materials.data, view.conclusion.reviewEventId);
  const trial = trialOf(trials.data, actions.data, view.caseIds);
  const cited = citedCasesOf(trial, view.caseIds);
  const downloadEventId = view.version.loaded ? props.arrow.eventId ?? null : null;

  return (
    <div className="v20-arrow-panel" data-testid="arrow-panel-sections">
      {materials.error === null ? null : (
        <p className="y10-note note" role="status">{readFailureText(materials.error)}</p>
      )}
      {view.openEnded === null ? null : (
        <p className="y10-cv-verdict-line is-open" data-testid="arrow-panel-open-ended">{view.openEnded}</p>
      )}
      {view.conclusion === null ? null : (
        <ConclusionSection
          app={props.app}
          conclusion={view.conclusion}
          review={review}
          coverage={coverage.data}
          cited={cited}
          sessions={trial === null ? [] : trial.sessions}
          textOnly={trial === null ? false : trial.textOnly}
        />
      )}
      {view.kind === "input" ? null : <VersionSection app={props.app} version={view.version} eventId={downloadEventId} />}
      {view.inputs === null ? null : <InputsSection inputs={view.inputs} />}
      {view.rounds.length === 0 ? null : <RoundsSection rounds={view.rounds} />}
    </div>
  );
}

/** 材料里这一份结论那一条：逐条结论的表要整份结论，模型只给编号。 */
function reviewOf(data: WorkItemMaterialsResult | null, eventId: string | null): ReviewEntry | null {
  if (data === null || eventId === null) {
    return null;
  }
  return data.reviews.find((item) => item.event_id === eventId) ?? null;
}

/** 引用的试用用例落在哪个职能那一组：一组里有一个引用到的用例就是它。 */
function trialOf(data: RunTrialsResult | null, actions: RunActionsResult | null,
                 caseIds: readonly string[]): TrialsView | null {
  if (data === null || caseIds.length === 0) {
    return null;
  }
  const group = data.departments.find((item) => item.cases.some((row) => caseIds.includes(row.case_id))) ?? null;
  return group === null ? null : trialView(group, actions);
}

// ---------------------------------------------------------------------------
// 标着放行或打回的那一版：结论、逐条结论、检查回执、缺陷、检验覆盖，证据里点得开试用用例

function ConclusionSection(props: {
  app: ClientApp;
  conclusion: ConclusionView;
  review: ReviewEntry | null;
  coverage: AcceptanceCoverageResult | null;
  cited: CitedCasesView;
  sessions: TrialsView["sessions"];
  textOnly: boolean;
}) {
  const conclusion = props.conclusion;
  return (
    <div className="v20-arrow-conclusion" data-testid="arrow-panel-conclusion">
      <p className={`y10-cv-verdict-line is-${conclusion.tone}`}>{conclusion.headline}</p>
      {conclusion.missing ? (
        <p className="y10-note note">{MISSING_REVIEW_TEXT}</p>
      ) : (
        <>
          <p className="y10-note note">
            结论：<Tag tone={conclusion.tone === "release" ? "ok" : "danger"}>{conclusion.verdictName}</Tag>
            {` · ${conclusion.rationale}`}
          </p>
          {conclusion.coverageText === null ? null : (
            <p className="y10-note note" data-testid="arrow-panel-coverage">{conclusion.coverageText}</p>
          )}
          {props.review === null ? null : (
            <CriteriaTable app={props.app} review={props.review} coverage={props.coverage} />
          )}
          {conclusion.checks.length === 0 ? null : (
            <p className="y10-note note">检查回执：{conclusion.checks.join("；")}</p>
          )}
          {conclusion.defects.length === 0 ? null : (
            <p className="y10-note note" data-testid="arrow-panel-defects">缺陷：{conclusion.defects.join("；")}</p>
          )}
        </>
      )}
      {props.cited.rows.length === 0 ? null : (
        <div className="v20-arrow-evidence" aria-label="逐条结论的证据" data-testid="arrow-panel-evidence">
          <h4 className="y10-mt-sub">逐条结论的证据（试用用例与截图）</h4>
          <TrialRecords
            app={props.app}
            view={{ sessions: props.sessions, cases: props.cited.rows, textOnly: props.textOnly }}
          />
          {/* 外部来源的原文在下面工作过程那一步的「查看外部来源」里（设计说明「项目页上的内容在哪里看」） */}
          <p className="y10-note note">外部来源的原文在工作过程那一步的「查看外部来源」里。</p>
        </div>
      )}
      {props.cited.missing.length === 0 ? null : (
        <p className="y10-note note">
          结论引用的试用用例，记录不在这件事项的这次运行里：{props.cited.missing.join("、")}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 这一版：那一版的一句话、与上一版的差异、文件清单与单个文件下载

function VersionSection(props: { app: ClientApp; version: VersionView; eventId: string | null }) {
  const version = props.version;
  return (
    <div className="v20-arrow-version" data-testid="arrow-panel-version">
      {version.summary === "" ? null : <p className="y10-cv-panel-text">{version.summary}</p>}
      {version.diff === null ? null : (
        <p className="y10-note note" data-testid="arrow-panel-diff">{version.diff.text}</p>
      )}
      {version.files.length === 0 ? <p className="y10-note note">{NO_FILES_TEXT}</p> : (
        <div className="y10-cv-files">
          <b>这一版的文件（{version.files.length} 个）</b>
          <ArrowFileList app={props.app} eventId={props.eventId} files={version.files} />
        </div>
      )}
    </div>
  );
}

/** 一个文件一行：路径与「查看与下载」；展开时取 delivery.file 给下载链接与正文。 */
function ArrowFileList(props: { app: ClientApp; eventId: string | null; files: readonly string[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const eventId = props.eventId ?? "";
  const file = useSnapshot<DeliveryFileResult>(
    props.app,
    open === null ? "page.cv.arrow.file.none" : `page.cv.arrow.file.${eventId}.${open}`,
    "delivery.file",
    { event_id: eventId, path: open ?? "" },
    open === null || eventId === "",
  );
  return (
    <ul className="y10-list v20-arrow-files">
      {props.files.map((path) => (
        <li key={path}>
          <code className="y10-code file-path">{path}</code>
          {eventId === "" ? null : (
            <button
              type="button"
              className="y10-link"
              aria-expanded={open === path}
              onClick={() => setOpen(open === path ? null : path)}
            >
              {open === path ? "收起" : "查看与下载"}
            </button>
          )}
          {open === path ? <FileBody state={file} /> : null}
        </li>
      ))}
    </ul>
  );
}

/** 一份文件的内容：下载链接 + 正文；读不出来与没有内容分开写。 */
function FileBody(props: { state: SnapshotState<DeliveryFileResult> }) {
  const view = readView(props.state);
  if (view.kind === "loading") {
    return <p className="y10-note note">正在读取这一份</p>;
  }
  if (view.kind === "failed") {
    return <p className="y10-note note">{readFailureText(view.reason)}</p>;
  }
  if (view.kind === "empty") {
    return <p className="y10-note note">这一份没有内容</p>;
  }
  const download = fileDownload(view.data);
  const content = view.data.content ?? "";
  return (
    <div className="v20-arrow-file">
      {download === null ? <p className="y10-note note">这一份没有可下载的内容</p> : (
        <a className="y10-btn primary" href={download.href} download={download.name}>下载文件</a>
      )}
      {content === "" ? null : <pre className="y10-pre raw">{content}</pre>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 从图外进来的箭头：你的输入各版本与处理进度

function InputsSection(props: { inputs: InputsView }) {
  return (
    <div className="v20-arrow-inputs" data-testid="arrow-panel-inputs">
      <p className="y10-note note" data-testid="arrow-panel-inputs-headline">{props.inputs.headline}</p>
      <ul className="y10-list">
        {props.inputs.rows.map((row) => (
          <li key={row.key}>
            <Tag tone={row.waiting ? "warn" : "ok"}>{row.stateText}</Tag>
            <b> 第 {row.version} 版</b>
            <span className="y10-muted"> · {row.kindName} · {row.range}</span>
            <p className="y10-clamp">{row.text}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 建档事项的初始 PRD 箭头：建档各轮与确认记录

function RoundsSection(props: { rounds: readonly RoundView[] }) {
  return (
    <div className="v20-arrow-rounds" data-testid="arrow-panel-rounds">
      <h4 className="y10-mt-sub">建档各轮（{props.rounds.length} 轮）</h4>
      <ol className="y10-list">
        {props.rounds.map((round) => (
          <li key={round.key} id={round.key}>
            <b>第 {round.round} 轮</b>
            <span className="y10-muted">
              {round.proposedAt === "" ? "" : ` · 提出于 ${formatTime(round.proposedAt)}`}
              {round.runId === "" ? "" : ` · run ${round.runId}`}
            </span>
            {round.revisionNote === "" ? null : <blockquote className="y10-mt-quote">{round.revisionNote}</blockquote>}
            <pre className="y10-pre raw">{round.prd}</pre>
            {round.structure === "" ? null : <p className="y10-note note">现有结构：{round.structure}</p>}
            {round.baseline.length === 0 ? null : (
              <ul className="y10-list">
                {round.baseline.map((line, index) => <li key={index}>{line}</li>)}
              </ul>
            )}
            {round.decisions.length === 0 ? null : (
              <ul className="y10-list">
                {round.decisions.map((item) => (
                  <li key={item.key}>{item.text}<span className="y10-muted"> · {item.at}</span></li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
