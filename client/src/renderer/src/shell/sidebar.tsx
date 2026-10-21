// 左侧栏（原型 v10 外壳，工单 #377）：品牌、首页、「从想法新建」、「接入已有项目」、
// 项目搜索、项目列表（名称、状态标记、待回答的决定数）与每项的重命名、置顶、归档、恢复；
// 底部「系统」分组的入口按能力清单显示。新建项目用命令 project.create / project.onboard，
// 项目列表本身由外壳的视图同步给出，命令被接受以后由事件到达时重新查询。

import { useEffect, useMemo, useState } from "react";
import type { Capabilities, DecisionView, ProjectRow, Rejected } from "../api/generated/types.gen";
import type { ClientApp } from "../contract/client-app";
import { useCommand } from "../views/project/use-snapshot";
import { visibleProjects } from "../views/project/project-list";
import { Icon, StatusMark } from "./kit";
import { onboardingRejectionText, projectOnboardingMark, sourceInvalidLines } from "../views/project/onboarding";

export type SidebarProps = {
  app: ClientApp;
  capabilities: Capabilities;
  decisions: DecisionView[];
  projects: ProjectRow[];
  activeProjectId: string | null;
  activeName: string;
  pendingByProject: Record<string, number>;
  // 侧栏「显示归档的项目」开关：项目列表的查询按它取数（工单 #672）
  includeArchived: boolean;
  onIncludeArchivedChange: (value: boolean) => void;
  onNavigate: (hash: string) => void;
};

// 系统分组的入口与图标（原型 v10 shell.js 的 SYSTEM_LINKS）；查询不在能力清单里时不出现
const SYSTEM_ENTRIES: { page: string; label: string; query: string; icon: string }[] = [
  { page: "models", label: "模型管理", query: "catalog", icon: "models" },
  { page: "machines", label: "机器", query: "machines.list", icon: "machines" },
  { page: "runtime", label: "运行与执行槽位", query: "runtime.slots", icon: "runtime" },
  { page: "tools", label: "工具与扩展", query: "tools.registry", icon: "tools" },
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
  const [creating, setCreating] = useState<null | "idea" | "existing">(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);

  // 项目列表由外壳打开（viewId "shell.projects"）：命令被接受以后事件到达，列表按事件种类重新查询
  const markKey = useMemo(() => JSON.stringify(props.decisions.map((decision) => [decision.decision_id, decision.status])), [props.decisions]);
  const command = useCommand(props.app, JSON.stringify(props.projects) + markKey);
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
        <div className="y10-side-actions">
          {can("project.create") ? (
            <button type="button" className="y10-btn primary y10-new-project nav-item" onClick={() => setCreating(creating === "idea" ? null : "idea")}>
              <Icon name="plus" />
              <span>从想法新建</span>
            </button>
          ) : null}
          {can("project.onboard") ? (
            <button type="button" className="y10-btn y10-onboard nav-item" onClick={() => setCreating(creating === "existing" ? null : "existing")}>
              <Icon name="import" />
              <span>接入已有项目</span>
            </button>
          ) : null}
        </div>
        {creating ? (
          <NewProject
            mode={creating}
            busy={command.busy}
            submitted={command.submitted}
            rejection={command.rejection}
            onClose={() => setCreating(null)}
            onSubmit={(name, body) => command.submit(name, body)}
          />
        ) : null}
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
        <ul className="y10-project-list nav-group">
          {visible.map((project) => {
            const marks = statusMarks(project, props.decisions);
            const pending = props.pendingByProject[project.project_id] ?? 0;
            const selected = project.project_id === props.activeProjectId;
            return (
              <li key={project.project_id} className="project-entry">
                <button
                  type="button"
                  className={`y10-project nav-item${selected ? " is-selected" : ""}${project.archived ? " is-archived" : ""}`}
                  aria-current={selected ? "page" : undefined}
                  onClick={() => props.onNavigate(`#/p/${project.project_id}/overview`)}
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
        {visible.length === 0 ? <p className="y10-note note" role="status">没有符合的项目</p> : null}
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

// 新建项目：名称与长期目标必填；从想法新建可以另填一个起始文件夹（留空则从空项目开始），
// 接入已有项目另登记源目录的名称与路径
function NewProject(props: {
  mode: "idea" | "existing";
  busy: boolean;
  submitted: boolean;
  rejection: Rejected | null;
  onClose: () => void;
  onSubmit: (name: string, body: Record<string, unknown>) => Promise<boolean>;
}) {
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [initialDirectory, setInitialDirectory] = useState("");
  const ready = name.trim() !== "" && goal.trim() !== "" && (props.mode === "idea" || (sourceName.trim() !== "" && sourcePath.trim() !== ""));
  const commandName = props.mode === "idea" ? "project.create" : "project.onboard";

  // 本次提交被接受以后等事件到达：项目列表由事件到达时重新查询，列表出现新内容以后「已提交」消失，
  // 这时关闭表单，各字段随表单一起清空（工单 #295 第 1 项）。
  // 被拒绝时 submit 返回假，表单保留已填字段并显示原因；等待只记在这一次挂载上，
  // 取消以后重新打开的表单不会因为上一次提交的余波自己关闭
  const [waitingWrite, setWaitingWrite] = useState(false);
  useEffect(() => {
    if (waitingWrite && !props.submitted) {
      props.onClose();
    }
  }, [waitingWrite, props.submitted]);

  return (
    <form
      className="y10-block is-compact card inline-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready) {
          return;
        }
        const directory = initialDirectory.trim();
        void props.onSubmit(commandName, props.mode === "idea"
          ? { name: name.trim(), goal: goal.trim(), ...(directory === "" ? {} : { initial_directory: directory }) }
          : { name: name.trim(), goal: goal.trim(), source_name: sourceName.trim(), source_path: sourcePath.trim() })
          .then((ok) => setWaitingWrite(ok));
      }}
    >
      <header className="y10-block-head form-head">
        <div className="y10-block-titles">
          <h2 className="y10-block-title">{props.mode === "idea" ? "从想法新建项目" : "接入已有项目"}</h2>
        </div>
        <div className="y10-block-actions">
          <button type="button" className="y10-btn small" onClick={props.onClose}>
            取消
          </button>
        </div>
      </header>
      <div className="y10-block-body form">
        <label className="y10-field field">
          <span>项目名称</span>
          <input className="y10-input" type="text" value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label className="y10-field field">
          <span>长期目标</span>
          <textarea className="y10-textarea" rows={3} value={goal} onChange={(event) => setGoal(event.target.value)} required />
        </label>
        {props.mode === "idea" ? (
          <label className="y10-field field">
            <span>起始文件夹</span>
            <input
              className="y10-input"
              type="text"
              value={initialDirectory}
              placeholder="控制主机上的文件夹路径，留空则从空项目开始"
              onChange={(event) => setInitialDirectory(event.target.value)}
            />
          </label>
        ) : null}
        {props.mode === "existing" ? (
          <>
            <label className="y10-field field">
              <span>源目录名称</span>
              <input className="y10-input" type="text" value={sourceName} onChange={(event) => setSourceName(event.target.value)} required />
            </label>
            <label className="y10-field field">
              <span>源目录路径</span>
              <input className="y10-input" type="text" value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} required />
            </label>
            <p className="y10-note note">接入以后会登记源目录、采集代码快照并开始建档事项（3.8）。</p>
          </>
        ) : null}
        <div className="y10-row">
          <button type="submit" className="y10-btn primary" disabled={props.busy || !ready}>
            {props.busy ? "正在提交" : props.mode === "idea" ? "新建项目" : "接入项目"}
          </button>
        </div>
        {props.rejection ? (
          <div className="rejection" role="status">
            <p className="error">
              {onboardingRejectionText(props.rejection)}
            </p>
            <ul className="rejection-paths y10-list">
              {sourceInvalidLines(props.rejection).map((line) => <li key={line}>{line}</li>)}
            </ul>
          </div>
        ) : null}
        {props.submitted ? <p className="y10-muted hint" role="status">已提交，等待写入结果</p> : null}
      </div>
    </form>
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
