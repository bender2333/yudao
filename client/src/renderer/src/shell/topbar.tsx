// 顶栏与项目标签（原型 v8 设计说明第 3.2 节）：路径、事项选择框、状态项、连接状态、项目菜单。
// 状态项取自 system.status 与 decisions.list 的等待数量，与托盘图标共用同一份数据（第 4.1 节）；
// 顶栏的状态项与标签栏的「待你决定」由 #175 扩展，这里保持 #79 的结构（工单 #80 留出位置）。
// 事项选择框的选项来自 project.overview 的事项列表；所选事项写在路径参数 ?w={事项} 中。

import { useState } from "react";
import type { ClientApp } from "../contract/client-app";
import type { DecisionView, ProjectOverviewResult, ProjectRow, Rejected } from "../api/generated/types.gen";
import { useCommand, useSnapshot } from "../views/project/use-snapshot";
import { WORK_ITEM_STATUS, formatTime, label } from "../views/project/labels";
import { list, text } from "../views/project/common";
import { DecisionCardList } from "../views/decisions/card";
import { sortByRequested } from "../views/decisions/card-logic";

export type TopbarProps = {
  app: ClientApp | null;
  projectId: string | null;
  workItemId: string | null;
  project: ProjectRow | null;
  path: string;
  pending: number;
  // 本项目的等待回答的决定请求（标签栏右侧的「待你决定」，v8 第 3.2 节）
  projectDecisions: DecisionView[];
  streamConnected: boolean;
  // 事件流断开的时间（ISO）：断开时顶栏写明断开的时间与正在重新连接（设计说明第 3.4 节、工单 #296）
  disconnectedAt: string | null;
  onPendingClick: () => void;
  onToggleDrawer: () => void;
  onNavigate: (hash: string) => void;
};

export function Topbar(props: TopbarProps) {
  const [decisionsOpen, setDecisionsOpen] = useState(false);
  const waiting = sortByRequested(props.projectDecisions);
  const now = Date.now();
  return (
    <header className="topbar">
      <button className="nav-item drawer-toggle" onClick={props.onToggleDrawer} aria-label="打开左侧栏">
        菜单
      </button>
      <span className="path">{props.path}</span>
      {props.projectId ? (
        <WorkItemPicker app={props.app} projectId={props.projectId} workItemId={props.workItemId} onNavigate={props.onNavigate} />
      ) : null}
      <div className="spacer" />
      {props.projectId && props.project && props.app ? (
        <ProjectMenu app={props.app} projectId={props.projectId} workItemId={props.workItemId} project={props.project} onNavigate={props.onNavigate} />
      ) : null}
      {/* 标签栏右侧的「待你决定」：只列出本项目的请求，点击展开决定卡片（第 3.2 节） */}
      {props.projectId !== null && waiting.length > 0 ? (
        <button
          className="status-item lit"
          aria-expanded={decisionsOpen}
          onClick={() => setDecisionsOpen(!decisionsOpen)}
          title="本项目等待回答的决定请求"
        >
          待你决定 · {waiting.length}
        </button>
      ) : null}
      <button
        className={`status-item${props.pending > 0 ? " lit" : ""}`}
        onClick={props.onPendingClick}
        title="跨项目等待回答的决定请求"
      >
        待你决定：{props.pending > 0 ? props.pending : "无"}
      </button>
      <span className={`connection${props.streamConnected ? "" : " interrupted"}`} role="status">
        {props.streamConnected ? "已连接" : `连接中断 · ${props.disconnectedAt === null ? "刚刚" : formatTime(props.disconnectedAt)}断开，正在重新连接`}
      </span>
      {decisionsOpen ? (
        <div className="dropdown decisions-dropdown">
          <DecisionCardList
            app={props.app}
            decisions={waiting}
            now={now}
            names={(decision) => ({
              projectName: props.project?.name ?? decision.project_id ?? "",
              workItemTitle: decision.work_item_id ?? "",
            })}
            onNavigate={props.onNavigate}
            emptyText="本项目没有等待回答的决定"
          />
        </div>
      ) : null}
    </header>
  );
}

// 事项选择框：「整个项目」或某个事项（标题与状态）；概览、部门工作间、资料、观测按所选范围显示
function WorkItemPicker(props: {
  app: ClientApp | null;
  projectId: string;
  workItemId: string | null;
  onNavigate: (hash: string) => void;
}) {
  const snapshot = useSnapshot<ProjectOverviewResult>(props.app, "topbar.overview", "project.overview", {
    project_id: props.projectId,
  });
  const items = snapshot.data === null ? [] : list(snapshot.data.work_items);

  return (
    <label className="field picker">
      <span>事项</span>
      <select
        value={props.workItemId ?? ""}
        onChange={(event) => {
          const base = `#/p/${props.projectId}/overview`;
          const chosen = event.target.value;
          props.onNavigate(chosen === "" ? base : `${base}?w=${chosen}`);
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
    <div className="project-menu-wrap">
      <button type="button" className="status-item" aria-expanded={open} onClick={() => setOpen(!open)}>
        项目菜单
      </button>
      {open ? (
        <div className="dropdown">
          <button type="button" onClick={() => { props.onNavigate(`#/p/${props.projectId}/settings${scope}`); setOpen(false); }}>
            项目设置
          </button>
          <button type="button" onClick={() => send("project.pin", { project_id: props.projectId, pinned: !props.project.pinned, base_version: props.project.version })}>
            {props.project.pinned ? "取消置顶" : "置顶"}
          </button>
          {props.project.archived ? (
            <button type="button" onClick={() => send("project.restore", { project_id: props.projectId, base_version: props.project.version })}>
              恢复项目
            </button>
          ) : (
            <button type="button" onClick={() => send("project.archive", { project_id: props.projectId, base_version: props.project.version })}>
              归档项目
            </button>
          )}
          <MenuFeedback submitted={command.submitted} rejection={command.rejection} />
        </div>
      ) : null}
    </div>
  );
}

function MenuFeedback(props: { submitted: boolean; rejection: Rejected | null }) {
  if (props.rejection) {
    return (
      <p className="error" role="status">
        {props.rejection.message}（原因 {props.rejection.reason}）
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
export function Tabbar(props: { tabs: Tab[]; activeHash: string; onNavigate: (hash: string) => void }) {
  if (props.tabs.length === 0) {
    return null;
  }
  const activePath = props.activeHash.split("?")[0];
  return (
    <nav className="tabbar" aria-label="项目页面">
      {props.tabs.map((tab) => (
        <button
          key={tab.hash}
          className="tab"
          aria-current={tab.hash === activePath ? "page" : undefined}
          onClick={() => props.onNavigate(tab.hash)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
