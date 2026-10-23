// 顶栏与项目标签（原型 v10 外壳，工单 #377）：面包屑路径、事项范围、亮起的状态项、
// 版本与连接状态、项目菜单与主题切换。状态项取自 system.status 与 decisions.list 的等待数量；
// 事项范围的选择写在路径参数 ?w={事项} 中；换一个范围时留在当前页（工单 #746）。

import { useState } from "react";
import type { ClientApp } from "../contract/client-app";
import type { StreamState } from "../contract/stream-state";
import type { DecisionView, ProjectOverviewResult, ProjectRow, WorkItemCard } from "../api/generated/types.gen";
import { PAGE_RELEASE } from "../contract/page-release";
import { type CommandProblem, commandProblemText } from "../contract/command-problem.ts";
import { useCommand, useSnapshot } from "../views/project/use-snapshot";
import { Icon } from "./kit";
import { providerNotice, type ProviderReadiness } from "./provider-status";
import { useTheme, type ThemeChoice } from "./theme";
import { WORK_ITEM_STATUS, connectionText, label } from "../views/project/labels";
import { list, text } from "../views/project/common";
import { scopeName } from "../views/project/scope-name";
import { DecisionCardList } from "../views/decisions/card";
import { sortByRequested } from "../views/decisions/card-logic";
import { type Route, withScope } from "./routing";

export type TopbarProps = {
  app: ClientApp | null;
  projectId: string | null;
  // 当前页面（含路径参数）：顶栏的事项范围按它决定换范围以后去哪一个页面（工单 #746）
  route: Route;
  project: ProjectRow | null;
  path: string;
  pending: number;
  // 本项目的等待回答的决定请求（标签栏右侧的「待你决定」）
  projectDecisions: DecisionView[];
  // 事件流的三种状态（工单 #653）：顶栏按它显示连接中、已连接或连接中断
  stream: StreamState;
  // 模型服务是否可用（工单 #718）：不可用时顶栏给出一处提示，点一下进模型管理页
  provider: ProviderReadiness | null;
  onPendingClick: () => void;
  onToggleDrawer: () => void;
  onNavigate: (hash: string) => void;
};

export function Topbar(props: TopbarProps) {
  const [decisionsOpen, setDecisionsOpen] = useState(false);
  const waiting = sortByRequested(props.projectDecisions);
  const now = Date.now();
  // 模型服务不可用时的提示（工单 #718）：可用时不显示
  const provider = providerNotice(props.provider);
  // 本项目的事项表：范围选择框与下拉里的决定卡片共用这一份（工单 #802）。
  // 事项标题就在这份数据里（work_items 的 title），决定卡片写标题，不写事项标识。
  const projectId = props.route.projectId;
  const overview = useSnapshot<ProjectOverviewResult>(props.app, "topbar.overview", "project.overview", {
    project_id: projectId ?? "",
  }, projectId === null);
  const workItems = overview.data?.work_items ?? [];
  return (
    <header className="y10-topbar topbar">
      <button type="button" className="y10-icon-btn y10-drawer-open drawer-toggle" onClick={props.onToggleDrawer} aria-label="打开左侧栏">
        <Icon name="menu" />
      </button>
      <nav className="y10-crumbs" aria-label="路径">
        <span className="y10-crumb path">{props.path}</span>
      </nav>
      <div className="y10-top-actions">
        {props.projectId ? (
          <WorkItemPicker route={props.route} items={workItems} onNavigate={props.onNavigate} />
        ) : null}
        {/* 顶栏的状态项：跨项目与本项目的等待回答的决定请求，亮起时可以直接点开 */}
        <div className="y10-top-stats">
          {props.projectId !== null && waiting.length > 0 ? (
            <button
              type="button"
              className="y10-stat is-compact is-lit is-decisions status-item lit"
              aria-expanded={decisionsOpen}
              onClick={() => setDecisionsOpen(!decisionsOpen)}
              title="本项目等待回答的决定请求"
            >
              <Icon name="decide" className="y10-icon y10-stat-icon" />
              <span className="y10-stat-value">{`待你决定 · ${waiting.length}`}</span>
            </button>
          ) : null}
          <button
            type="button"
            className={`y10-stat is-compact${props.pending > 0 ? " is-lit is-decisions" : ""} status-item${props.pending > 0 ? " lit" : ""}`}
            onClick={props.onPendingClick}
            title="跨项目等待回答的决定请求"
          >
            <Icon name="bell" className="y10-icon y10-stat-icon" />
            <span className="y10-stat-value">{`待你决定：${props.pending > 0 ? props.pending : "无"}`}</span>
          </button>
          <ThemeSwitch />
          <span className="y10-service note" title="页面版本">{PAGE_RELEASE}</span>
          {provider ? (
            <button
              type="button"
              className="y10-service connection interrupted provider status-item"
              role="status"
              onClick={() => props.onNavigate("#/sys/models")}
              title={provider.detail === "" ? provider.label : `${provider.label}：${provider.detail}`}
            >
              <span className="y10-dot" />
              {provider.label}
            </button>
          ) : null}
          <span className={`y10-service connection${props.stream.kind === "interrupted" ? " interrupted" : ""}`} role="status">
            <span className="y10-dot" />
            {connectionText(props.stream)}
          </span>
        </div>
      </div>
      {props.projectId && props.project && props.app ? (
        <ProjectMenu app={props.app} projectId={props.projectId} workItemId={props.route.workItemId} project={props.project} onNavigate={props.onNavigate} />
      ) : null}
      {decisionsOpen ? (
        <div className="dropdown decisions-dropdown">
          <DecisionCardList
            app={props.app}
            decisions={waiting}
            now={now}
            names={(decision) => ({
              projectName: props.project?.name ?? decision.project_id ?? "",
              workItemTitle: scopeName(workItems, decision.work_item_id),
            })}
            onNavigate={props.onNavigate}
            viewId="topbar.decisions"
            emptyText="本项目没有等待回答的决定"
          />
        </div>
      ) : null}
    </header>
  );
}

// 主题切换：浅色、深色、跟随系统（工单 #377 验收第 2 条）。选择记在浏览器里，刷新以后保持
const THEME_LABELS: Record<ThemeChoice, string> = { system: "跟随系统", light: "浅色", dark: "深色" };

function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  return (
    <span className="y10-seg" role="group" aria-label="主题">
      {(Object.keys(THEME_LABELS) as ThemeChoice[]).map((choice) => (
        <button
          key={choice}
          type="button"
          className={`y10-seg-btn${theme === choice ? " is-on" : ""}`}
          aria-pressed={theme === choice}
          onClick={() => setTheme(choice)}
        >
          {THEME_LABELS[choice]}
        </button>
      ))}
    </span>
  );
}

// 事项选择框：「整个项目」或某个事项（标题与状态）；概览、部门工作间、资料、观测按所选范围显示。
// 换一个范围时留在当前页（工单 #746）：范围是项目级的一份，写在路径参数 ?w= 中，
// 选完以后当前的页面与筛选条件都还在，只有范围变了。
// 事项表由顶栏这一层给出（project.overview）：下拉里的决定卡片用它写事项标题（工单 #802）。
function WorkItemPicker(props: {
  route: Route;
  items: WorkItemCard[];
  onNavigate: (hash: string) => void;
}) {
  const items = list(props.items);

  return (
    <label className="y10-scope field picker">
      <span className="y10-scope-label">范围</span>
      <select
        className="y10-select"
        value={props.route.workItemId ?? ""}
        aria-label="事项范围"
        onChange={(event) => {
          const chosen = event.target.value;
          props.onNavigate(withScope(props.route, chosen === "" ? null : chosen));
        }}
      >
        <option value="">整个项目</option>
        {items.map((item) => {
          const id = text(item.work_item_id);
          return (
            <option key={id} value={id}>
              {text(item.title)}（{label(WORK_ITEM_STATUS, text(item.status))}）
            </option>
          );
        })}
      </select>
    </label>
  );
}

// 项目菜单：置顶、归档或恢复；基准版本取项目列表里的 version，拒绝时显示原因
function ProjectMenu(props: {
  app: ClientApp;
  projectId: string;
  workItemId: string | null;
  project: ProjectRow;
  onNavigate: (hash: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const command = useCommand(props.app, String(props.project.version));

  const send = (name: string, body: Record<string, unknown>) => {
    void command.submit(name, body).then(() => setOpen(false));
  };
  const scope = props.workItemId ? `?w=${props.workItemId}` : "";

  return (
    <div className="y10-menu-wrap y10-top-menu project-menu-wrap">
      <button type="button" className="y10-icon-btn status-item" aria-haspopup="menu" aria-expanded={open} aria-label="项目菜单" onClick={() => setOpen(!open)}>
        <Icon name="more" />
      </button>
      {open ? (
        <div className="y10-menu dropdown" role="menu">
          <button type="button" role="menuitem" onClick={() => { props.onNavigate(`#/p/${props.projectId}/settings${scope}`); setOpen(false); }}>
            项目设置
          </button>
          <button type="button" role="menuitem" onClick={() => send("project.pin", { project_id: props.projectId, pinned: !props.project.pinned, base_version: props.project.version })}>
            {props.project.pinned ? "取消置顶" : "置顶"}
          </button>
          {props.project.archived ? (
            <button type="button" role="menuitem" onClick={() => send("project.restore", { project_id: props.projectId, base_version: props.project.version })}>
              恢复项目
            </button>
          ) : (
            <button type="button" role="menuitem" onClick={() => send("project.archive", { project_id: props.projectId, base_version: props.project.version })}>
              归档项目
            </button>
          )}
          <MenuFeedback submitted={command.submitted} problem={command.problem} />
        </div>
      ) : null}
    </div>
  );
}

function MenuFeedback(props: { submitted: boolean; problem: CommandProblem | null }) {
  if (props.problem) {
    return (
      <p className="error" role="status">
        {commandProblemText(props.problem)}
      </p>
    );
  }
  if (props.submitted) {
    return (
      <p className="hint" role="status">
        已提交，等待写入结果
      </p>
    );
  }
  return null;
}

export type Tab = { label: string; hash: string };

// 项目标签：active 比较 hash 的路径部分，带 ?w= 时仍高亮当前页
// 页签的地址带着当前范围（工单 #746），因此高亮只看路径部分，参数不参与比较
export function Tabbar(props: { tabs: Tab[]; activeHash: string; onNavigate: (hash: string) => void }) {
  if (props.tabs.length === 0) {
    return null;
  }
  const activePath = props.activeHash.split("?")[0];
  return (
    <nav className="y10-tabbar tabbar" aria-label="项目页面">
      <div className="y10-ptabs">
        {props.tabs.map((tab) => {
          const tabPath = tab.hash.split("?")[0];
          return (
            <button
              key={tab.hash}
              className={`y10-ptab tab${tabPath === activePath ? " is-active" : ""}`}
              aria-current={tabPath === activePath ? "page" : undefined}
              onClick={() => props.onNavigate(tab.hash)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
