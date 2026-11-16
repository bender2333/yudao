// 「事项与用量」页（工单 #1809，docs/design/project-organization.md 4.10）：
// 顶部子视图切换「事项列表」与「模型请求与用量」，子视图与筛选条件同步写入地址参数。
// 「模型请求与用量」复用 RequestsPanel，不含循环层与收敛状态。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  DecisionList,
  ProjectLoopResult,
  ProjectOverviewResult,
} from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import { PageHead, StatusMark } from "../../shell/kit";
import { paths, type Route } from "../../shell/routing";
import { Empty, Loading, StopNote, Tag, show } from "./common";
import {
  canQueryRuntimeSlots,
  itemsListView,
  type ItemCardView,
  type ItemsStatusFilter,
  type ItemsSummaryStats,
} from "./items-page-model";
import type { Filters } from "./observe-filter";
import type { DepartmentView } from "./organization";
import { RequestsPanel } from "./requests-section";
import { useSnapshot } from "./use-snapshot";

export function ItemsAndUsagePage(props: {
  app: ClientApp;
  route: Route;
  departments: DepartmentView[];
  onNavigate: (hash: string) => void;
}) {
  const projectId = props.route.projectId ?? "";
  const activeTab = props.route.itemsTab;
  const itemsHref = paths.items(projectId, { workItem: props.route.workItemId });
  const requestsHref = paths.items(projectId, {
    workItem: props.route.workItemId,
    tab: "requests",
    requests: props.route.requestFilters,
  });

  return (
    <div className="page v20-items-page">
      <PageHead
        eyebrow="事项与用量"
        title="事项与用量"
        subtitle="按子视图切换「事项列表」与「模型请求与用量」，范围与筛选写在地址里。"
      />
      <nav className="v20-it-subtabs" role="tablist" aria-label="事项与用量视图">
        <a
          role="tab"
          aria-selected={activeTab === "items"}
          className={`v20-it-subtab${activeTab === "items" ? " is-active" : ""}`}
          href={itemsHref}
        >
          事项列表
        </a>
        <a
          role="tab"
          aria-selected={activeTab === "requests"}
          className={`v20-it-subtab${activeTab === "requests" ? " is-active" : ""}`}
          href={requestsHref}
        >
          模型请求与用量
        </a>
      </nav>
      {activeTab === "requests" ? (
        <ItemsRequestsView
          app={props.app}
          route={props.route}
          departments={props.departments}
          onNavigate={props.onNavigate}
        />
      ) : (
        <ItemsListSubView
          app={props.app}
          route={props.route}
          departments={props.departments}
        />
      )}
    </div>
  );
}

function ItemsRequestsView(props: {
  app: ClientApp;
  route: Route;
  departments: DepartmentView[];
  onNavigate: (hash: string) => void;
}) {
  const projectId = props.route.projectId ?? "";
  const write = (workItem: string | null, filters: Filters): void => {
    const target = paths.items(projectId, {
      workItem,
      tab: "requests",
      requests: filters,
    });
    if (window.location.hash !== target) {
      props.onNavigate(target);
    }
  };

  return (
    <section className="y10-block card v20-req" data-testid="items-requests-view">
      <div className="y10-block-body">
        <RequestsPanel
          app={props.app}
          projectId={projectId}
          workItem={props.route.workItemId}
          departments={props.departments}
          addressFilters={props.route.requestFilters}
          onFiltersChange={(filters) => write(props.route.workItemId, filters)}
          onScopeChange={(workItem, filters) => write(workItem, filters)}
          attemptHash={(item, filters) => paths.observeDetail(projectId, item.attempt_id, {
            workItem: props.route.workItemId,
            runId: item.run_id,
            department: filters.department || null,
            from: "items",
            requests: filters,
          })}
          scopeSelect
        />
      </div>
    </section>
  );
}

function ItemsListSubView(props: {
  app: ClientApp;
  route: Route;
  departments: DepartmentView[];
}) {
  const projectId = props.route.projectId ?? "";
  const [filter, setFilter] = useState<ItemsStatusFilter>("all");
  const overview = useSnapshot<ProjectOverviewResult>(
    props.app,
    "page.items.overview",
    "project.overview",
    { project_id: projectId },
    projectId === "",
  );
  const loop = useSnapshot<ProjectLoopResult>(
    props.app,
    "page.items.loop",
    "project.loop",
    { project_id: projectId },
    projectId === "",
  );
  const decisions = useSnapshot<DecisionList>(
    props.app,
    "page.items.decisions",
    "decisions.list",
    { project_id: projectId, status: ["open"] },
    projectId === "",
  );
  const hasSlotsQuery = canQueryRuntimeSlots(props.app.currentCapabilities);
  const slots = useSnapshot<unknown>(
    props.app,
    "page.items.slots",
    "runtime.slots",
    { project_id: projectId },
    projectId === "" || !hasSlotsQuery,
  );

  const view = itemsListView({
    projectId,
    selectedWorkItemId: props.route.workItemId,
    overview: overview.data,
    loop: loop.data,
    decisions: decisions.data?.decisions ?? null,
    departments: props.departments,
    filter,
    runtimeSlots: hasSlotsQuery ? slots.data : null,
  });

  return (
    <div className="v20-it-body" data-testid="items-list-view">
      <Loading state={overview} />
      {overview.error ? (
        <p className="y10-note note" role="status">{readFailureText(overview.error)}</p>
      ) : null}
      {view !== null ? (
        <>
          <StatsRow stats={view.stats} />
          {view.runtimeSlots !== null || view.loopSlotText !== null ? (
            <div className="v20-it-slotbar" data-testid="items-slots-summary">
              <span className="v20-it-slotlabel">槽位与执行</span>
              {view.runtimeSlots !== null ? (
                <span className="v20-it-slotval">{view.runtimeSlots.text}</span>
              ) : null}
              {view.loopSlotText !== null ? (
                <span className="y10-note note">{view.loopSlotText}</span>
              ) : null}
            </div>
          ) : null}
          <div className="v20-it-filters" role="group" aria-label="按事项状态筛选">
            {view.filterOptions.map((option) => (
              <button
                key={option.key}
                type="button"
                aria-pressed={filter === option.key}
                className={`v20-it-filter${filter === option.key ? " is-active" : ""}`}
                onClick={() => setFilter(option.key)}
              >
                <span>{option.label}</span>
                <span className="v20-it-count">{option.count}</span>
              </button>
            ))}
          </div>
          {view.emptyText !== null ? (
            <Empty text={view.emptyText} />
          ) : (
            <div className="v20-it-groups">
              {view.groups.map((group) => (
                <section key={group.key} className="v20-it-group" data-group-key={group.key}>
                  <header className="v20-it-group-head">
                    <h3 className="v20-it-group-title">{group.title}</h3>
                    <span className="v20-it-count">{group.count}</span>
                  </header>
                  <div className="v20-it-list">
                    {group.cards.map((card) => (
                      <ItemCardRow key={`${group.key}:${card.workItemId}`} card={card} />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

function StatsRow(props: { stats: ItemsSummaryStats }) {
  const entries = [
    { key: "total", label: "总计", value: props.stats.total, tone: "" },
    { key: "in_progress", label: "进行中", value: props.stats.inProgress, tone: "is-progress" },
    { key: "waiting_decision", label: "待你决定", value: props.stats.waitingDecision, tone: "is-warn" },
    { key: "released", label: "独立核验放行", value: props.stats.released, tone: "is-released" },
    { key: "open_loop", label: "开环完成", value: props.stats.openLoop, tone: "is-open-loop" },
    { key: "stopped", label: "已停止", value: props.stats.stopped, tone: "is-stopped" },
  ];
  return (
    <div className="v20-it-stats" data-testid="items-stats-row">
      {entries.map((entry) => (
        <div key={entry.key} className={`v20-it-stat ${entry.tone}`}>
          <span className="v20-it-stat-label">{entry.label}</span>
          <strong className="v20-it-stat-value">{entry.value}</strong>
        </div>
      ))}
    </div>
  );
}

function ItemCardRow(props: { card: ItemCardView }) {
  const { card } = props;
  return (
    <article
      className={`v20-it-card${card.selected ? " is-selected" : ""}`}
      data-work-item-id={card.workItemId}
    >
      <div className="v20-it-head">
        <div className="v20-it-title-wrap">
          <StatusMark kind={card.statusKind} text={card.statusText} />
          <strong className="v20-it-title">{card.title}</strong>
          <span className="v20-it-id">{card.workItemId}</span>
        </div>
        <div className="v20-it-tags">
          {card.verifiedReleased ? <Tag tone="ok">独立核验放行</Tag> : null}
          {card.openLoop && card.openLoopNote ? <Tag tone="muted">{card.openLoopNote}</Tag> : null}
          {card.waitingDecision ? <Tag tone="warn">待你决定</Tag> : null}
          {card.oldOrganization ? <Tag tone="warn">按旧组织跑</Tag> : null}
        </div>
      </div>

      <div className="v20-it-meta">
        <span>第 {card.round} 轮</span>
        <span>当前职能：{card.departmentText}</span>
        <span>耗时与上限：{card.elapsedText}</span>
      </div>

      {card.stoppedIdentity !== "" || card.stopReasonText !== null ? (
        <div className="v20-it-stop">
          {card.stoppedIdentity !== "" ? (
            <span className="y10-note note">{card.stoppedIdentity}</span>
          ) : null}
          {card.stopReasonText !== null ? (
            <span className="v20-it-stop-reason">停止原因：{card.stopReasonText}</span>
          ) : null}
          {card.stopNote || card.keptDelivery || card.stopDetail ? (
            <StopNote
              note={card.stopNote}
              kept={card.keptDelivery}
              detail={card.stopDetail}
            />
          ) : null}
        </div>
      ) : null}

      {card.startError ? (
        <p className="v20-it-warn" role="status">无法继续：{show(card.startError)}</p>
      ) : null}
      {card.pendingQuestion ? (
        <p className="v20-it-question">等待回答：{show(card.pendingQuestion)}</p>
      ) : null}

      <div className="v20-it-actions">
        <a className="y10-btn is-small small" href={card.conversationHash}>
          在对话与循环图里看
        </a>
        {card.recoveryHash !== null ? (
          <a className="y10-btn is-small small primary" href={card.recoveryHash}>
            恢复与动作核实
          </a>
        ) : null}
      </div>
    </article>
  );
}
