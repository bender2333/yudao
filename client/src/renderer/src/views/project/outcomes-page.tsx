// 「成果库」一级标签页（工单 #1810）
// 汇总跨事项、跨版本的交付、结构化 PRD、建档初始 PRD 与缺陷记录，严格区分独立放行、开环完成与打回。

import { useState } from "react";
import type {
  AcceptanceCoverageResult,
  DeliveryFileResult,
  EventDetailResult,
  ProjectFlowResult,
  ProjectLoopResult,
  ProjectOrganizationResult,
  ProjectOverviewResult,
  RunActionsResult,
  TrialDepartmentView,
  WorkItemMaterialsResult,
} from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { readFailureText } from "../../contract/read-failure";
import { Block, PageHead } from "../../shell/kit";
import { paths, type Route } from "../../shell/routing";
import { Empty, Loading, Tag } from "./common";
import { CoverageUnreadable, CriteriaTable, LaunchMethods } from "./criteria-table";
import { formatTime } from "./labels";
import { fileDownload } from "./materials-download";
import { readView } from "./materials-read";
import type { DepartmentView } from "./organization";
import {
  NO_FILES_TEXT,
  outcomeCardDetail,
  outcomesPageView,
  type OnboardingRoundDetailView,
  type OutcomeCategory,
  type OutcomeEntry,
} from "./outcomes-page-model.ts";
import { TrialRecords, trialView } from "./trials";
import { useSnapshot } from "./use-snapshot";
import type { PrdView } from "./arrow-panel-model.ts";

// 仅在浏览器环境加载样式：避免 Vite SSR 测试（ssrLoadModule("/src/app.tsx")）在未初始化客户端 CSS 缓存时触发 vite:css-post 报错
if (typeof document !== "undefined") {
  void import("../../styles/v21-outcomes.css");
}

export function OutcomesPage(props: {
  app: ClientApp;
  route: Route;
  organization: ProjectOrganizationResult | null;
  departments: DepartmentView[];
  onNavigate: (hash: string) => void;
}) {
  const projectId = props.route.projectId ?? "";
  const requestedWorkItemId = props.route.workItemId ?? null;

  const overviewState = useSnapshot<ProjectOverviewResult>(
    props.app,
    "page.oc.overview",
    "project.overview",
    { project_id: projectId },
    projectId === "",
  );
  const loopState = useSnapshot<ProjectLoopResult>(
    props.app,
    "page.oc.loop",
    "project.loop",
    { project_id: projectId },
    projectId === "",
  );
  const flowState = useSnapshot<ProjectFlowResult>(
    props.app,
    "page.oc.flow",
    "project.flow",
    { project_id: projectId },
    projectId === "",
  );
  const scopedMaterialsState = useSnapshot<WorkItemMaterialsResult>(
    props.app,
    `page.oc.scope.materials.${requestedWorkItemId ?? "none"}`,
    "work_item.materials",
    { work_item_id: requestedWorkItemId ?? "" },
    requestedWorkItemId === null || requestedWorkItemId === "",
  );

  return (
    <OutcomesPageContent
      app={props.app}
      projectId={projectId}
      workItemId={requestedWorkItemId}
      departments={props.departments}
      overviewState={overviewState}
      loopState={loopState}
      flowState={flowState}
      scopedMaterials={scopedMaterialsState.data}
      onNavigate={props.onNavigate}
    />
  );
}

export interface OutcomesPageContentProps {
  app: ClientApp;
  projectId: string;
  workItemId: string | null;
  departments: DepartmentView[];
  overviewState: { data: ProjectOverviewResult | null; loading: boolean; error: string | null };
  loopState: { data: ProjectLoopResult | null; loading: boolean; error: string | null };
  flowState: { data: ProjectFlowResult | null; loading: boolean; error: string | null };
  scopedMaterials?: WorkItemMaterialsResult | null;
  initialCategory?: OutcomeCategory;
  initialExpandedIds?: Record<string, boolean>;
  onNavigate: (hash: string) => void;
}

export function OutcomesPageContent(props: OutcomesPageContentProps) {
  const { projectId, workItemId: requestedWorkItemId, overviewState, loopState, flowState } = props;
  const [category, setCategory] = useState<OutcomeCategory>(props.initialCategory ?? "all");
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>(props.initialExpandedIds ?? {});

  const materialsByWorkItem =
    requestedWorkItemId && props.scopedMaterials != null
      ? { [requestedWorkItemId]: props.scopedMaterials }
      : undefined;

  const view = outcomesPageView({
    projectId,
    overview: overviewState.data,
    loop: loopState.data,
    flow: flowState.data,
    departments: props.departments,
    materialsByWorkItem,
    workItemId: requestedWorkItemId,
    category,
  });

  const conversationHash = paths.conversation(projectId, { workItem: requestedWorkItemId });
  const initialLoading =
    overviewState.data === null &&
    loopState.data === null &&
    flowState.data === null &&
    (overviewState.loading || loopState.loading || flowState.loading);
  const errors = [overviewState.error, loopState.error, flowState.error].filter(
    (err): err is string => err !== null,
  );
  const fatalError =
    overviewState.data === null &&
    loopState.data === null &&
    flowState.data === null &&
    errors.length > 0;

  const toggleExpanded = (id: string) => {
    setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="page v21-outcomes-page" data-testid="outcomes-page">
      <PageHead
        eyebrow="成果库"
        title="成果库"
        subtitle="按时间倒序汇总各事项的结构化 PRD、建档提案、交付文件与差异、逐条核验与开环完成。"
        actions={
          <div className="v21-oc-summary">
            <span
              className="v21-oc-pill is-release"
              data-testid="outcomes-count-released"
              title="经过核验角色独立核验并放行的版本"
            >
              ✓ 独立放行 {view.scopedCounts.released}
            </span>
            <span
              className="v21-oc-pill is-open"
              data-testid="outcomes-count-open"
              title="没有核验角色参与，直接开环完成的版本"
            >
              ◌ 开环完成 {view.scopedCounts.openLoop}
            </span>
            <span
              className="v21-oc-pill is-reject"
              data-testid="outcomes-count-rejected"
              title="核验角色打回或提出缺陷的版本"
            >
              ✕ 打回 {view.scopedCounts.rejected}
            </span>
            <a
              className="y10-btn is-small small"
              href={conversationHash}
              onClick={(event) => {
                event.preventDefault();
                props.onNavigate(conversationHash);
              }}
            >
              回到对话
            </a>
          </div>
        }
      />

      <div className="v21-oc-bar" role="region" aria-label="成果筛选与事项范围">
        <div className="v21-oc-filters" role="tablist" aria-label="成果类别筛选">
          {view.categories.map((tab) => {
            const active = category === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={active}
                className={`v21-oc-tab ${active ? "is-active" : ""}`}
                data-testid={`outcomes-cat-${tab.id}`}
                onClick={() => setCategory(tab.id)}
              >
                <span>{tab.label}</span>
                <span>({tab.count})</span>
              </button>
            );
          })}
        </div>

        <label className="v21-oc-scope">
          <span>事项范围</span>
          <select
            className="v21-oc-select"
            aria-label="按事项筛选成果"
            data-testid="outcomes-scope-select"
            value={requestedWorkItemId ?? ""}
            onChange={(event) => {
              const nextWorkItem = event.target.value || null;
              props.onNavigate(paths.outcomes(projectId, { workItem: nextWorkItem }));
            }}
          >
            <option value="">全部事项（共 {view.projectCounts.total} 条）</option>
            {view.scopeOptions.map((option) => (
              <option key={option.workItemId} value={option.workItemId}>
                {option.title}（{option.count}）
              </option>
            ))}
          </select>
        </label>
      </div>

      {view.hasFilteredScope && view.projectCounts.total !== view.scopedCounts.total ? (
        <p className="v21-oc-scope-note" data-testid="outcomes-scope-summary">
          当前筛选「{view.selectedWorkItemTitle ?? "当前事项"}」，项目总计 {view.projectCounts.total} 条成果（✓ 独立放行{" "}
          {view.projectCounts.released} · ◌ 开环完成 {view.projectCounts.openLoop} · ✕ 打回 {view.projectCounts.rejected}）。
        </p>
      ) : null}

      {errors.length > 0 && !fatalError ? (
        <p className="y10-note note" role="status">
          {readFailureText(errors[0])}
        </p>
      ) : null}

      {initialLoading ? (
        <Loading state={{ loading: true, data: null }} />
      ) : fatalError ? (
        <Block title="读取失败">
          <Empty text={readFailureText(errors[0])} />
        </Block>
      ) : view.entries.length === 0 ? (
        <Block title="暂无匹配成果">
          <Empty
            text={
              view.allEntries.length === 0
                ? "这个项目还没有产生 PRD、交付或核验成果。"
                : "当前筛选条件下没有对应的成果记录，可以切换类别或事项范围查看全部。"
            }
          />
        </Block>
      ) : (
        <div className="v21-oc-list" data-testid="outcomes-list">
          {view.entries.map((entry) => (
            <OutcomeCard
              key={entry.id}
              app={props.app}
              entry={entry}
              departments={props.departments}
              preloadedMaterials={
                requestedWorkItemId === entry.workItemId ? props.scopedMaterials ?? null : null
              }
              expanded={Boolean(expandedIds[entry.id])}
              onToggle={() => toggleExpanded(entry.id)}
              onNavigate={props.onNavigate}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function cardToneClass(entry: OutcomeEntry): string {
  if (entry.verdictBadge.kind === "release") {
    return "is-release";
  }
  if (entry.verdictBadge.kind === "open") {
    return "is-open";
  }
  if (entry.verdictBadge.kind === "reject") {
    return "is-reject";
  }
  return `is-${entry.kind}`;
}

function OutcomeCard(props: {
  app: ClientApp;
  entry: OutcomeEntry;
  departments: DepartmentView[];
  preloadedMaterials: WorkItemMaterialsResult | null;
  expanded: boolean;
  onToggle: () => void;
  onNavigate: (hash: string) => void;
}) {
  const { entry } = props;
  const dotClass = `v21-oc-dot v21-oc-dot-${Math.abs(entry.workItemColorIndex) % 6}`;

  return (
    <article
      className={`v21-oc-card ${cardToneClass(entry)}`}
      data-testid={`outcome-card-${entry.id}`}
    >
      <header className="v21-oc-head">
        <div className="v21-oc-title-group">
          <span className="v21-oc-kind">{entry.kindLabel}</span>
          {entry.round !== null && entry.round > 0 ? (
            <span className="v21-oc-round">第 {entry.round} 轮</span>
          ) : null}
          <span
            className={`v21-oc-pill is-${entry.verdictBadge.kind}`}
            data-testid={`outcome-badge-${entry.id}`}
          >
            {entry.verdictBadge.text}
          </span>
        </div>

        <div className="v21-oc-item-meta">
          <span className="v21-oc-item-chip">
            <span className={dotClass} aria-hidden="true" />
            <span>{entry.workItemTitle}</span>
          </span>
          {entry.timeText ? <time dateTime={entry.createdAt}>{entry.timeText}</time> : null}
        </div>
      </header>

      {entry.summary ? (
        <div className="v21-oc-body-summary">
          <p className="v21-oc-summary-text">{entry.summary}</p>
        </div>
      ) : null}

      <div className="v21-oc-actions">
        <div className="v21-oc-actions-left">
          <button
            type="button"
            className="y10-btn is-small small"
            aria-expanded={props.expanded}
            data-testid={`outcome-toggle-${entry.id}`}
            onClick={props.onToggle}
          >
            {props.expanded ? "收起详情" : "展开详情"}
          </button>
          {entry.expectsFiles && entry.files.length > 0 ? (
            <Tag tone="muted">{entry.files.length} 个文件</Tag>
          ) : null}
        </div>

        <div className="v21-oc-actions-right">
          <a
            className="y10-btn is-small small"
            href={entry.locateHash}
            data-testid={`outcome-locate-${entry.id}`}
            onClick={(event) => {
              event.preventDefault();
              props.onNavigate(entry.locateHash);
            }}
          >
            在对话与循环图里定位
          </a>
        </div>
      </div>

      {props.expanded ? (
        <OutcomeExpandedBody
          app={props.app}
          entry={entry}
          departments={props.departments}
          preloadedMaterials={props.preloadedMaterials}
        />
      ) : null}
    </article>
  );
}

function OutcomeExpandedBody(props: {
  app: ClientApp;
  entry: OutcomeEntry;
  departments: DepartmentView[];
  preloadedMaterials: WorkItemMaterialsResult | null;
}) {
  const { entry } = props;
  const skipMaterials = props.preloadedMaterials !== null || entry.workItemId === "";
  const materialsState = useSnapshot<WorkItemMaterialsResult>(
    props.app,
    `page.oc.card.materials.${entry.workItemId}`,
    "work_item.materials",
    { work_item_id: entry.workItemId },
    skipMaterials,
  );
  const materials = props.preloadedMaterials ?? materialsState.data;

  const eventDetailState = useSnapshot<EventDetailResult>(
    props.app,
    `page.oc.card.event.${entry.eventId ?? "none"}`,
    "event.detail",
    { event_id: entry.eventId ?? "" },
    entry.kind !== "delivery" || !entry.eventId,
  );

  const skipReview = !entry.needsReviewDetails || entry.runId === "";
  const coverageState = useSnapshot<AcceptanceCoverageResult>(
    props.app,
    `page.oc.card.coverage.${entry.runId}`,
    "acceptance.coverage",
    { run_id: entry.runId },
    skipReview,
  );
  const trialsState = useSnapshot<TrialDepartmentView>(
    props.app,
    `page.oc.card.trials.${entry.runId}`,
    "run.trials",
    { run_id: entry.runId },
    skipReview,
  );
  const actionsState = useSnapshot<RunActionsResult>(
    props.app,
    `page.oc.card.actions.${entry.runId}`,
    "run.actions",
    { run_id: entry.runId },
    skipReview,
  );

  const trial = trialView(trialsState.data, actionsState.data);
  return (
    <OutcomeExpandedContent
      app={props.app}
      entry={entry}
      departments={props.departments}
      materials={materials}
      materialsLoading={!skipMaterials && materialsState.loading && materials === null}
      materialsError={!skipMaterials ? materialsState.error : null}
      eventDetail={eventDetailState.data}
      eventDetailLoading={eventDetailState.loading}
      eventDetailError={eventDetailState.error}
      coverage={coverageState.data}
      coverageError={coverageState.error}
      trials={trial}
    />
  );
}

export interface OutcomeExpandedContentProps {
  app: ClientApp;
  entry: OutcomeEntry;
  departments: DepartmentView[];
  materials: WorkItemMaterialsResult | null;
  materialsLoading?: boolean;
  materialsError?: string | null;
  eventDetail: EventDetailResult | null;
  eventDetailLoading?: boolean;
  eventDetailError?: string | null;
  coverage: AcceptanceCoverageResult | null;
  coverageError?: string | null;
  trials: ReturnType<typeof trialView>;
}

export function OutcomeExpandedContent(props: OutcomeExpandedContentProps) {
  const { entry, materials, eventDetail, coverage, trials: trial } = props;
  const detail = outcomeCardDetail({
    entry,
    materials,
    coverage,
    trials: trial,
    eventDetail,
    departments: props.departments,
  });

  if (props.materialsLoading) {
    return (
      <div className="v21-oc-detail">
        <Loading state={{ loading: true, data: null }} />
      </div>
    );
  }

  return (
    <div className="v21-oc-detail" data-testid={`outcome-detail-${entry.id}`}>
      {props.materialsError ? (
        <p className="y10-note note" role="status">
          {readFailureText(props.materialsError)}
        </p>
      ) : null}

      {detail.rounds.length > 0 ? <OutcomeOnboardingRoundsSection rounds={detail.rounds} /> : null}

      {detail.prd !== null ? (
        <OutcomePrdSection prd={detail.prd} />
      ) : entry.kind === "prd" && materials !== null ? (
        <section className="v21-oc-section">
          <h4 className="v21-oc-section-title">产品规格内容</h4>
          <p className="v21-oc-summary-text">{detail.versionView?.summary || entry.summary || "暂无结构化节内容"}</p>
        </section>
      ) : null}

      {entry.kind === "delivery" ? (
        <>
          <section className="v21-oc-section" data-testid={`outcome-files-${entry.id}`}>
            <h4 className="v21-oc-section-title">交付内容与文件清单</h4>
            {detail.versionView?.summary ? (
              <p className="v21-oc-summary-text">{detail.versionView.summary}</p>
            ) : null}
            <LaunchMethods launch={detail.launch} />
            <OutcomeDeliveryFiles
              app={props.app}
              eventId={entry.eventId}
              files={detail.versionView?.files ?? entry.files}
            />
          </section>

          <section className="v21-oc-section" data-testid={`outcome-diff-${entry.id}`}>
            <h4 className="v21-oc-section-title">与上一版差异</h4>
            {detail.fileDiff !== null ? (
              <div className="v21-diff-summary">
                <span>{detail.fileDiff.text}</span>
                {detail.fileDiff.added.map((path) => (
                  <span key={`add:${path}`} className="v21-diff-tag-add">
                    + {path}
                  </span>
                ))}
                {detail.fileDiff.removed.map((path) => (
                  <span key={`del:${path}`} className="v21-diff-tag-del">
                    - {path}
                  </span>
                ))}
              </div>
            ) : null}
            {props.eventDetailError ? (
              <p className="y10-note note">{readFailureText(props.eventDetailError)}</p>
            ) : detail.gitDiffLines.length > 0 ? (
              <pre className="v21-diff" data-testid={`outcome-git-diff-${entry.id}`}>
                {detail.gitDiffLines.map((line, idx) => (
                  <div key={idx} className={`v21-diff-line is-${line.kind}`}>
                    {line.text}
                  </div>
                ))}
              </pre>
            ) : props.eventDetailLoading ? (
              <Loading state={{ loading: true, data: null }} />
            ) : detail.fileDiff === null ? (
              <p className="y10-note note">暂无与上一版可比的代码或文件差异。</p>
            ) : null}
          </section>

          <section className="v21-oc-section" data-testid={`outcome-review-${entry.id}`}>
            <h4 className="v21-oc-section-title">核验结论与验收证据</h4>
            {detail.openEnded !== null ? (
              <div className="v21-oc-open-notice" data-testid={`outcome-open-loop-${entry.id}`}>
                {detail.openEnded}
              </div>
            ) : (
              <>
                {detail.conclusion !== null ? (
                  <p
                    className={`v21-oc-verdict-summary is-${detail.conclusion.tone}`}
                  >
                    {detail.conclusion.headline}（{detail.conclusion.verdictName}）
                  </p>
                ) : null}
                {detail.conclusion?.rationale ? (
                  <p className="v21-oc-summary-text">{detail.conclusion.rationale}</p>
                ) : null}
                {detail.conclusion?.coverageText ? (
                  <p className="y10-note note">{detail.conclusion.coverageText}</p>
                ) : null}
                {props.coverageError ? <CoverageUnreadable /> : null}
                {detail.review !== null ? (
                  <CriteriaTable
                    app={props.app}
                    review={detail.review}
                    coverage={coverage}
                  />
                ) : null}
                {detail.conclusion && detail.conclusion.checks.length > 0 ? (
                  <p className="y10-note note">检查回执：{detail.conclusion.checks.join("；")}</p>
                ) : null}
                {detail.conclusion && detail.conclusion.defects.length > 0 ? (
                  <div className="v21-prd-sub">
                    <span className="v21-prd-label">发现的缺陷</span>
                    <ul className="v21-prd-list">
                      {detail.conclusion.defects.map((defect, idx) => (
                        <li key={idx}>{defect}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {detail.citedCases.rows.length > 0 ? (
                  <div className="v20-arrow-evidence" data-testid={`outcome-evidence-${entry.id}`}>
                    <span className="v21-prd-label">逐条结论的证据（试用用例与截图）</span>
                    <TrialRecords
                      app={props.app}
                      view={{
                        sessions: trial.sessions,
                        cases: detail.citedCases.rows,
                        textOnly: trial.textOnly,
                      }}
                    />
                  </div>
                ) : trial.cases.length > 0 || trial.sessions.length > 0 ? (
                  <div className="v20-arrow-evidence" data-testid={`outcome-evidence-${entry.id}`}>
                    <span className="v21-prd-label">试用证据（试用用例与截图）</span>
                    <TrialRecords app={props.app} view={trial} />
                  </div>
                ) : null}
                {detail.missingReviewText !== null ? (
                  <p className="y10-note note">{detail.missingReviewText}</p>
                ) : null}
              </>
            )}
          </section>
        </>
      ) : null}

      {entry.kind === "defect" ? (
        <section className="v21-oc-section" data-testid={`outcome-defect-${entry.id}`}>
          <h4 className="v21-oc-section-title">缺陷记录与核验详情</h4>
          {detail.defectText ? <p className="v21-oc-summary-text">{detail.defectText}</p> : null}
          {detail.conclusion?.rationale && detail.conclusion.rationale !== detail.defectText ? (
            <p className="y10-note note">{detail.conclusion.rationale}</p>
          ) : null}
          {props.coverageError ? <CoverageUnreadable /> : null}
          {detail.review !== null ? (
            <CriteriaTable
              app={props.app}
              review={detail.review}
              coverage={coverage}
            />
          ) : null}
          {detail.conclusion && detail.conclusion.defects.length > 0 ? (
            <ul className="v21-prd-list">
              {detail.conclusion.defects.map((d, idx) => (
                <li key={idx}>{d}</li>
              ))}
            </ul>
          ) : null}
          {detail.citedCases.rows.length > 0 ? (
            <TrialRecords
              app={props.app}
              view={{
                sessions: trial.sessions,
                cases: detail.citedCases.rows,
                textOnly: trial.textOnly,
              }}
            />
          ) : trial.cases.length > 0 || trial.sessions.length > 0 ? (
            <TrialRecords app={props.app} view={trial} />
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function OutcomePrdSection(props: { prd: PrdView }) {
  const { prd } = props;
  return (
    <section className="v21-oc-section v21-prd-grid" data-testid="outcome-prd-detail">
      <h4 className="v21-oc-section-title">
        <span>结构化 PRD · 第 {prd.revision} 版</span>
        <Tag tone="ok">{prd.statusName}</Tag>
        <Tag tone="muted">来源 v{prd.inputVersion}</Tag>
      </h4>

      {prd.acceptedInputs.length > 0 ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">已吸收的来源</span>
          <ul className="v21-prd-list">
            {prd.acceptedInputs.map((item) => (
              <li key={`${item.version}:${item.kindName}`}>
                <strong>
                  来源 v{item.version}（{item.kindName}）：
                </strong>
                {item.text}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {prd.goal ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">目标</span>
          <p className="v21-oc-summary-text">{prd.goal}</p>
        </div>
      ) : null}

      {prd.nonGoals.length > 0 ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">不做</span>
          <ul className="v21-prd-list">
            {prd.nonGoals.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {prd.boundaries.length > 0 ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">边界</span>
          <ul className="v21-prd-list">
            {prd.boundaries.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {prd.constraints.length > 0 ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">约束</span>
          <ul className="v21-prd-list">
            {prd.constraints.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {prd.requirements.length > 0 ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">需求条目与验收映射</span>
          <ul className="v21-prd-list">
            {prd.requirements.map((req) => (
              <li key={req.number}>
                <div>
                  <strong>R{req.number}. </strong>
                  {req.text}
                </div>
                {req.criteria.length > 0 ? (
                  <div className="v21-prd-req-meta">映射验收条件：{req.criteria.join("、")}</div>
                ) : null}
                {req.gap ? <div className="v21-prd-gap">缺口：{req.gap}</div> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {prd.acceptanceCriteria.length > 0 ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">验收条件</span>
          <ul className="v21-prd-list">
            {prd.acceptanceCriteria.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {prd.fatalConditions.length > 0 ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">致命条件</span>
          <ul className="v21-prd-list">
            {prd.fatalConditions.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {prd.decisions.length > 0 ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">有效裁决</span>
          <ul className="v21-prd-list">
            {prd.decisions.map((d) => (
              <li key={`${d.id}:${d.hash}`}>
                <strong>{d.id}：</strong>
                {d.statement}
                {d.rationale ? <span className="v21-prd-req-meta">（{d.rationale}）</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {prd.decisionChanges.length > 0 ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">裁决变化</span>
          <ul className="v21-prd-list">
            {prd.decisionChanges.map((dc, idx) => (
              <li key={idx}>
                <strong>{dc.dispositionName}：</strong>
                {dc.rationale}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {prd.changeRecord !== null ? (
        <div className="v21-prd-sub">
          <span className="v21-prd-label">变更记录</span>
          {prd.changeRecord.changed.length > 0 ? (
            <p className="y10-note note">变更：{prd.changeRecord.changed.join("；")}</p>
          ) : null}
          {prd.changeRecord.retained.length > 0 ? (
            <p className="y10-note note">保留：{prd.changeRecord.retained.join("；")}</p>
          ) : null}
          {prd.changeRecord.retired.length > 0 ? (
            <p className="y10-note note">移除：{prd.changeRecord.retired.join("；")}</p>
          ) : null}
          {prd.changeRecord.rationale ? (
            <p className="y10-note note">说明：{prd.changeRecord.rationale}</p>
          ) : null}
        </div>
      ) : null}

      {prd.diffFromPrevious !== null ? (
        <div className="v21-prd-diff-box" data-testid="outcome-prd-diff">
          <span className="v21-prd-label">与上一版 PRD 差异：{prd.diffFromPrevious.summary}</span>
          {prd.diffFromPrevious.goalChanged !== null ? (
            <div className="v21-prd-sub">
              <div className="v21-diff-line is-del">- 目标：{prd.diffFromPrevious.goalChanged.before}</div>
              <div className="v21-diff-line is-add">+ 目标：{prd.diffFromPrevious.goalChanged.after}</div>
            </div>
          ) : null}
          {prd.diffFromPrevious.sections.map((section) => (
            <div key={section.label} className="v21-prd-sub">
              <span className="v21-prd-label">{section.label}</span>
              {section.added.map((line, idx) => (
                <div key={`add:${idx}`} className="v21-diff-line is-add">
                  + {line}
                </div>
              ))}
              {section.removed.map((line, idx) => (
                <div key={`del:${idx}`} className="v21-diff-line is-del">
                  - {line}
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function OutcomeOnboardingRoundsSection(props: { rounds: OnboardingRoundDetailView[] }) {
  return (
    <section className="v21-oc-section" data-testid="outcome-onboarding-rounds">
      <h4 className="v21-oc-section-title">建档初始 PRD 各轮提案与确认</h4>
      {props.rounds.map((round) => (
        <div key={round.key} className="v21-round-card" data-testid={`outcome-round-${round.round}`}>
          <div className="v21-oc-title-group">
            <strong>第 {round.round} 轮</strong>
            {round.proposedAt ? <span className="y10-note note">{formatTime(round.proposedAt)}</span> : null}
            {round.baselineReviewNote ? <Tag tone="warn">{round.baselineReviewNote}</Tag> : null}
          </div>

          {round.revisionNote ? (
            <p className="y10-note note">修订说明：{round.revisionNote}</p>
          ) : null}

          {round.prd ? (
            <div className="v21-prd-sub">
              <span className="v21-prd-label">初始 PRD</span>
              <pre className="y10-pre pre">{round.prd}</pre>
            </div>
          ) : null}

          {round.structure ? (
            <div className="v21-prd-sub">
              <span className="v21-prd-label">现有结构</span>
              <pre className="y10-pre pre">{round.structure}</pre>
            </div>
          ) : null}

          {round.overview ? (
            <div className="v21-prd-sub">
              <span className="v21-prd-label">项目概览</span>
              <p className="v21-oc-summary-text">{round.overview}</p>
            </div>
          ) : null}

          {round.baseline.length > 0 ? (
            <div className="v21-prd-sub">
              <span className="v21-prd-label">基线核验</span>
              <ul className="v21-prd-list">
                {round.baseline.map((line, idx) => (
                  <li key={idx}>{line}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {round.decisions.length > 0 ? (
            <div className="v21-prd-sub">
              <span className="v21-prd-label">确认裁决记录</span>
              <ul className="v21-prd-list">
                {round.decisions.map((decision) => (
                  <li key={decision.key}>
                    <span>{decision.text}</span>
                    {decision.at ? (
                      <span className="v21-prd-req-meta">（{formatTime(decision.at)}）</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ))}
    </section>
  );
}

function OutcomeDeliveryFiles(props: {
  app: ClientApp;
  eventId: string | null;
  files: string[];
}) {
  const [openPath, setOpenPath] = useState<string | null>(null);
  const fileState = useSnapshot<DeliveryFileResult>(
    props.app,
    openPath === null ? "page.oc.file.none" : `page.oc.file.${props.eventId ?? "none"}.${openPath}`,
    "delivery.file",
    { event_id: props.eventId ?? "", path: openPath ?? "" },
    openPath === null || !props.eventId,
  );
  const fileView = readView(fileState);

  if (props.files.length === 0) {
    return <p className="y10-note note">{NO_FILES_TEXT}</p>;
  }

  return (
    <ul className="v21-oc-files">
      {props.files.map((path) => {
        const opened = openPath === path;
        const download =
          opened && fileView.kind === "ready" ? fileDownload(fileView.data) : null;
        return (
          <li key={path} className="v21-oc-file-item">
            <div className="v21-oc-file-row">
              <span className="v21-oc-file-path">{path}</span>
              <div className="v21-oc-actions-right">
                {props.eventId !== null ? (
                  <button
                    type="button"
                    className="y10-btn is-small small"
                    aria-expanded={opened}
                    onClick={() => setOpenPath(opened ? null : path)}
                  >
                    {opened ? "收起内容" : "查看与下载"}
                  </button>
                ) : null}
                {download !== null ? (
                  <a
                    className="y10-btn is-small small"
                    href={download.href}
                    download={download.name}
                    data-testid={`outcome-download-${path}`}
                  >
                    下载文件
                  </a>
                ) : null}
              </div>
            </div>
            {opened ? (
              <div className="v20-arrow-file">
                {fileView.kind === "loading" ? (
                  <Loading state={fileState} />
                ) : fileView.kind === "failed" ? (
                  <p className="y10-note note">{readFailureText(fileView.reason)}</p>
                ) : fileView.kind === "ready" ? (
                  fileView.data.content !== null && fileView.data.content !== undefined ? (
                    <pre className="y10-pre pre">{fileView.data.content}</pre>
                  ) : (
                    <p className="y10-note note">二进制文件，请使用上方「下载文件」保存。</p>
                  )
                ) : null}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
