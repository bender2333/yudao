// 左侧栏（原型 v10 外壳，工单 #377）：品牌、首页、「从想法新建」、「接入已有项目」导航入口、
// 项目搜索、项目列表（名称、状态标记、待回答的决定数）与每项的重命名、置顶、归档、恢复；
// 底部「系统」分组的入口按能力清单显示。新建与接入独立页面在 views/home/new-project-page.tsx，
// 项目列表本身由外壳的视图同步给出，命令被接受以后由事件到达时重新查询。

import { useMemo, useState } from "react";
import type { Capabilities, DecisionView, ProjectRow } from "../api/generated/types.gen";
import type { ClientApp } from "../contract/client-app";
import { useCommand } from "../views/project/use-snapshot";
import { visibleProjects } from "../views/project/project-list";
import { drainNoticeText } from "../views/system/drain-text";
import { emptyOrFailureText } from "../contract/read-failure";
import { Icon, StatusMark } from "./kit";
import { sidebarEntryItems } from "./new-project-text";
import { projectOnboardingMark } from "../views/project/onboarding";

export type SidebarProps = {
  app: ClientApp;
  capabilities: Capabilities;
  decisions: DecisionView[];
  projects: ProjectRow[];
  // 项目列表读取失败时的原因（工单 #728）：有它时不说「没有符合的项目」，说「读不出来」
  projectsError: string | null;
  activeProjectId: string | null;
  activeName: string;
  pendingByProject: Record<string, number>;
  // 侧栏「显示归档的项目」开关：项目列表的查询按它取数（工单 #672）
  includeArchived: boolean;
  onIncludeArchivedChange: (value: boolean) => void;
  // 排空状态：排空期间新的事项只排队不开始，侧栏给出提示（工单 #663）
  drainState: string | null;
  onNavigate: (hash: string) => void;
};

// 系统分组的入口与图标（原型 v10 shell.js 的 SYSTEM_LINKS）；查询不在能力清单里时不出现。
// 执行槽位这一页的数据来自 system.status（排空、强制升级、正在执行的事项都在那里），
// 所以入口按 system.status 出现，不必等 runtime.slots 那条查询（工单 #727）。
const SYSTEM_ENTRIES: { page: string; label: string; query: string; icon: string }[] = [
  { page: "models", label: "模型管理", query: "catalog", icon: "models" },
  { page: "machines", label: "机器", query: "machines.list", icon: "machines" },
  { page: "runtime", label: "运行与执行槽位", query: "system.status", icon: "runtime" },
  { page: "tools", label: "工具与扩展", query: "tools.registry", icon: "tools" },
  // 规则与参数页（工单 #1195）：入口按 rules.registry 出现；图标用现有的 tag（登记条目），
  // 不为这一页改 kit.tsx 的图标清单
  { page: "rules", label: "规则与参数", query: "rules.registry", icon: "tag" },
];

// 项目状态标记（原型 v10 左侧栏的项目行）：每种自带图标与颜色，计数取自项目列表，
// 取值不为真的不显示。kind 取自 kit.tsx 的图标名单，写错会在画图标时就地报错。
function statusMarks(project: ProjectRow, decisions: DecisionView[]): { kind: string; text: string }[] {
  const marks: { kind: string; text: string }[] = [];
  if (project.in_progress_count > 0) {
    marks.push({ kind: "running", text: "运行中" });
  }
  const onboarding = projectOnboardingMark(project, decisions);
  if (onboarding !== null) {
    marks.push({ kind: "pending", text: onboarding });
  }
  if (project.interrupted_count > 0) {
    marks.push({ kind: "interrupted", text: `中断 ${project.interrupted_count}` });
  }
  if (project.waiting_resume_count > 0) {
    marks.push({ kind: "waiting", text: `待恢复 ${project.waiting_resume_count}` });
  }
  if (project.archived) {
    marks.push({ kind: "cancelled", text: "已归档" });
  }
  return marks;
}

export function Sidebar(props: SidebarProps) {
  const has = (name: string) => props.capabilities.queries.some((query) => query.name === name);
  const can = (name: string) => props.capabilities.commands.some((command) => command.name === name);
  const [search, setSearch] = useState("");
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const entryItems = sidebarEntryItems({
    activeName: props.activeName,
    canCreate: can("project.create"),
    canOnboard: can("project.onboard"),
  });

  // 项目列表由外壳打开（viewId "shell.projects"）：命令被接受以后事件到达，列表按事件种类重新查询
  const markKey = useMemo(() => JSON.stringify(props.decisions.map((decision) => [decision.decision_id, decision.status])), [props.decisions]);
  const command = useCommand(props.app, JSON.stringify(props.projects) + markKey);
  // 排空期间新的事项只排队不开始：用户在这里就能看出原因（工单 #663）
  const drainNotice = drainNoticeText(props.drainState);
  const visible = useMemo(
    () => visibleProjects(props.projects, { search, includeArchived: props.includeArchived }),
    [props.projects, search, props.includeArchived],
  );

  const send = (name: string, body: Record<string, unknown>) => {
    void command.submit(name, body).then((ok) => {
      if (ok) {
        setMenuFor(null);
      }
    });
  };

  return (
    <aside className="y10-sidebar sidebar" aria-label="首页、项目与系统">
      <div className="y10-side-top">
        <div className="y10-brand brand">
          <Icon name="brand" className="y10-icon y10-brand-icon" />
          <span className="y10-brand-name">Yudao<small>枢道</small></span>
        </div>
        <button
          type="button"
          className={`y10-side-link y10-home-link nav-item${props.activeName === "home" ? " is-active" : ""}`}
          aria-current={props.activeName === "home" ? "page" : undefined}
          onClick={() => props.onNavigate("#/home")}
        >
          <Icon name="home" />
          <span>首页</span>
        </button>
        {/* 两个新建入口只留跳转与当前页高亮（工单 #1806）：完整表单与形态卡迁往右侧主工作区独立页面 */}
        <div className="y10-side-actions">
          {entryItems.map((item) => (
            <div className="y10-side-action" key={item.mode}>
              <button
                type="button"
                className={
                  item.mode === "idea"
                    ? `y10-btn primary y10-new-project nav-item${item.active ? " is-active" : ""}`
                    : `y10-btn y10-onboard nav-item${item.active ? " is-active" : ""}`
                }
                aria-current={item.active ? "page" : undefined}
                data-testid={`sidebar-entry-${item.mode}`}
                onClick={() => props.onNavigate(item.hash)}
              >
                <Icon name={item.mode === "idea" ? "plus" : "import"} />
                <span>{item.label}</span>
              </button>
              {/* 入口旁的场景说明（工单 #1240）：哪个入口从材料开始、哪个从已有代码目录开始 */}
              <small className="y10-entry-note">{item.note}</small>
            </div>
          ))}
        </div>
        <label className="y10-search">
          <Icon name="search" />
          <input
            type="search"
            value={search}
            placeholder="搜索项目"
            aria-label="搜索项目"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <div className="y10-side-label nav-title">
          <span>项目</span>
          <span className="y10-count count">{props.projects.length}</span>
        </div>
        {drainNotice === null ? null : (
          <p className="y10-note note" role="status">{drainNotice}</p>
        )}
        <ul className="y10-project-list nav-group">
          {visible.map((project) => {
            const marks = statusMarks(project, props.decisions);
            // 待你决定的数量从两个职能起显示（项目的组织设计说明「项目页是循环图加对话」）：
            // 一个职能直做的项目没有别人要你决定，数字不显示。职能数由 projects.list 随每一行给出
            const pending = project.department_count >= 2 ? (props.pendingByProject[project.project_id] ?? 0) : 0;
            const selected = project.project_id === props.activeProjectId;
            return (
              <li key={project.project_id} className="project-entry">
                <button
                  type="button"
                  className={`y10-project nav-item${selected ? " is-selected" : ""}${project.archived ? " is-archived" : ""}`}
                  aria-current={selected ? "page" : undefined}
                  onClick={() => props.onNavigate(`#/p/${project.project_id}/conversation`)}
                >
                  <span className="y10-project-name project-name">{project.name}</span>
                  <span className="y10-project-marker">
                    {pending > 0 ? <span className="y10-count is-decide count">{pending}</span> : null}
                    {marks.map((mark) => (
                      <StatusMark key={mark.kind} kind={mark.kind} text={mark.text} />
                    ))}
                  </span>
                </button>
                <button
                  type="button"
                  className="y10-btn small menu-toggle"
                  aria-label={`${project.name} 的项目操作`}
                  onClick={() => setMenuFor(menuFor === project.project_id ? null : project.project_id)}
                >
                  <Icon name="more" />
                </button>
                {menuFor === project.project_id ? (
                  <ProjectMenu project={project} can={can} busy={command.busy} onSend={send} onNavigate={props.onNavigate} />
                ) : null}
              </li>
            );
          })}
        </ul>
        {visible.length === 0 ? <p className="y10-note note" role="status">{emptyOrFailureText(props.projectsError, "没有符合的项目")}</p> : null}
        <label className="y10-check checkbox">
          <input type="checkbox" checked={props.includeArchived} onChange={(event) => props.onIncludeArchivedChange(event.target.checked)} />
          <span>显示归档的项目</span>
        </label>
        <p className="y10-note note" role="status">
          {props.includeArchived ? "正在显示归档的项目" : "已归档的项目不列出，可用「恢复项目」取回"}
        </p>
      </div>
      <div className="y10-side-bottom nav-group">
        <div className="y10-side-label nav-title">
          <span>系统</span>
        </div>
        <ul className="y10-side-links">
          {SYSTEM_ENTRIES.filter((entry) => has(entry.query)).map((entry) => (
            <li key={entry.page}>
              <button
                type="button"
                className="y10-side-link nav-item"
                onClick={() => props.onNavigate(`#/sys/${entry.page}`)}
              >
                <Icon name={entry.icon} />
                <span>{entry.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}

// 项目操作：重命名、置顶、归档或恢复；基准版本取项目列表里的 version，过期时提示重新读取
function ProjectMenu(props: {
  project: ProjectRow;
  can: (name: string) => boolean;
  busy: boolean;
  onSend: (name: string, body: Record<string, unknown>) => void;
  onNavigate: (hash: string) => void;
}) {
  const project = props.project;
  const [renaming, setRenaming] = useState(false);
  const [nextName, setNextName] = useState(project.name);

  return (
    <div className="y10-menu project-menu">
      {renaming ? (
        <form
          className="rename-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (nextName.trim() === "") {
              return;
            }
            props.onSend("project.rename", { project_id: project.project_id, name: nextName.trim(), base_version: project.version });
            setRenaming(false);
          }}
        >
          <label className="y10-field field">
            <span>新的项目名称</span>
            <input className="y10-input" type="text" value={nextName} onChange={(event) => setNextName(event.target.value)} />
          </label>
          <button type="submit" className="y10-btn small primary" disabled={props.busy}>
            保存名称
          </button>
        </form>
      ) : (
        <div className="menu-buttons">
          {props.can("project.rename") ? (
            <button type="button" onClick={() => { setNextName(project.name); setRenaming(true); }}>
              重命名
            </button>
          ) : null}
          {props.can("project.pin") ? (
            <button type="button" onClick={() => props.onSend("project.pin", { project_id: project.project_id, pinned: !project.pinned, base_version: project.version })}>
              {project.pinned ? "取消置顶" : "置顶"}
            </button>
          ) : null}
          {project.archived
            ? props.can("project.restore")
              ? (
                <button type="button" onClick={() => props.onSend("project.restore", { project_id: project.project_id, base_version: project.version })}>
                  恢复项目
                </button>
              )
              : null
            : props.can("project.archive")
              ? (
                <button type="button" onClick={() => props.onSend("project.archive", { project_id: project.project_id, base_version: project.version })}>
                  归档项目
                </button>
              )
              : null}
          {project.archived ? null : (
            <button type="button" onClick={() => props.onNavigate(`#/p/${project.project_id}/settings`)}>
              项目设置
            </button>
          )}
        </div>
      )}
    </div>
  );
}
