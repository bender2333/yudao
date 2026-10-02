// 左侧栏（原型 v8 设计说明第 3.1 节，工单 #80）：品牌、首页、「从想法新建」、「接入已有项目」、
// 项目搜索、项目列表（名称、状态标记、待回答的决定数）与每项的重命名、置顶、归档、恢复；
// 底部「系统」分组的入口按能力清单显示。新建项目用命令 project.create / project.onboard，
// 项目列表本身由外壳的视图同步给出，命令被接受以后由事件到达时重新查询。

import { useMemo, useState } from "react";
import type { Capabilities, ProjectRow, Rejected } from "../api/generated/types.gen";
import type { ClientApp } from "../contract/client-app";
import { useCommand } from "../views/project/use-snapshot";

export type SidebarProps = {
  app: ClientApp;
  capabilities: Capabilities;
  projects: ProjectRow[];
  activeProjectId: string | null;
  activeName: string;
  pendingByProject: Record<string, number>;
  onNavigate: (hash: string) => void;
};

const SYSTEM_ENTRIES: { page: string; label: string; query: string }[] = [
  { page: "models", label: "模型管理", query: "catalog" },
  { page: "machines", label: "机器", query: "machines.list" },
  { page: "runtime", label: "运行与执行槽位", query: "runtime.slots" },
  { page: "tools", label: "工具与扩展", query: "tools.registry" },
];

// 项目状态标记：只用项目列表里已有的计数与标记，取值为真的才显示
function statusMarks(project: ProjectRow): string[] {
  const marks: string[] = [];
  if (project.in_progress_count > 0) {
    marks.push("运行中");
  }
  if (project.interrupted_count > 0) {
    marks.push(`中断 ${project.interrupted_count}`);
  }
  if (project.pending_verification_count > 0) {
    marks.push(`待核实 ${project.pending_verification_count}`);
  }
  if (project.waiting_resume_count > 0) {
    marks.push(`待恢复 ${project.waiting_resume_count}`);
  }
  if (project.onboarding_status === "onboarding") {
    marks.push("建档中");
  }
  if (project.onboarding_status === "awaiting_onboarding") {
    marks.push("待建档");
  }
  if (project.archived) {
    marks.push("已归档");
  }
  return marks;
}

export function Sidebar(props: SidebarProps) {
  const has = (name: string) => props.capabilities.queries.some((query) => query.name === name);
  const can = (name: string) => props.capabilities.commands.some((command) => command.name === name);
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [creating, setCreating] = useState<null | "idea" | "existing">(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);

  // 项目列表由外壳打开（viewId "shell.projects"）：命令被接受以后事件到达，列表按事件种类重新查询
  const command = useCommand(props.app, JSON.stringify(props.projects));
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return props.projects.filter((project) => {
      if (!includeArchived && project.archived) {
        return false;
      }
      if (needle === "") {
        return true;
      }
      return project.name.toLowerCase().includes(needle) || project.goal.toLowerCase().includes(needle);
    });
  }, [props.projects, search, includeArchived]);

  const send = (name: string, body: Record<string, unknown>) => {
    void command.submit(name, body).then((ok) => {
      if (ok) {
        setMenuFor(null);
      }
    });
  };

  return (
    <aside className="sidebar" aria-label="首页、项目与系统">
      <div className="brand">Yudao</div>
      <div className="nav-group">
        <button
          className="nav-item"
          aria-current={props.activeName === "home" ? "page" : undefined}
          onClick={() => props.onNavigate("#/home")}
        >
          首页
        </button>
        {can("project.create") ? (
          <button className="nav-item" onClick={() => setCreating(creating === "idea" ? null : "idea")}>
            从想法新建
          </button>
        ) : null}
        {can("project.onboard") ? (
          <button className="nav-item" onClick={() => setCreating(creating === "existing" ? null : "existing")}>
            接入已有项目
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
          onSubmit={(name, body) => void command.submit(name, body)}
        />
      ) : null}
      <div className="nav-group">
        <div className="nav-title">项目</div>
        <label className="field">
          <span>搜索项目</span>
          <input type="search" value={search} placeholder="名称或长期目标" onChange={(event) => setSearch(event.target.value)} />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} />
          <span>显示归档的项目</span>
        </label>
        <p className="note" role="status">
          {includeArchived ? "正在显示归档的项目" : "已归档的项目不列出，可用「恢复项目」取回"}
        </p>
        {visible.length === 0 && <span className="nav-item" aria-disabled="true">没有符合的项目</span>}
        {visible.map((project) => {
          const marks = statusMarks(project);
          const pending = props.pendingByProject[project.project_id] ?? 0;
          return (
            <div key={project.project_id} className="project-entry">
              <button
                className="nav-item"
                aria-current={project.project_id === props.activeProjectId ? "page" : undefined}
                onClick={() => props.onNavigate(`#/p/${project.project_id}/overview`)}
              >
                <span className="project-name">{project.name}</span>
                {pending > 0 ? <span className="badge">{pending}</span> : null}
              </button>
              {marks.length > 0 ? (
                <div className="project-marks">
                  {marks.map((mark) => (
                    <span key={mark} className={`mark${mark === "已归档" ? " muted" : ""}`}>
                      {mark}
                    </span>
                  ))}
                </div>
              ) : null}
              <button className="nav-item menu-toggle" onClick={() => setMenuFor(menuFor === project.project_id ? null : project.project_id)}>
                项目操作
              </button>
              {menuFor === project.project_id ? (
                <ProjectMenu project={project} can={can} busy={command.busy} onSend={send} onNavigate={props.onNavigate} />
              ) : null}
            </div>
          );
        })}
      </div>
      <div className="nav-group">
        <div className="nav-title">系统</div>
        {SYSTEM_ENTRIES.filter((entry) => has(entry.query)).map((entry) => (
          <button key={entry.page} className="nav-item" onClick={() => props.onNavigate(`#/sys/${entry.page}`)}>
            {entry.label}
          </button>
        ))}
      </div>
      <button className="nav-item" onClick={() => props.onNavigate("#/connect")}>
        连接设置
      </button>
      <button className="nav-item" onClick={() => props.onNavigate("#/settings")}>
        设置
      </button>
    </aside>
  );
}

// 新建项目：名称与长期目标必填；接入已有项目另登记源目录的名称与路径
function NewProject(props: {
  mode: "idea" | "existing";
  busy: boolean;
  submitted: boolean;
  rejection: Rejected | null;
  onClose: () => void;
  onSubmit: (name: string, body: Record<string, unknown>) => void;
}) {
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const ready = name.trim() !== "" && goal.trim() !== "" && (props.mode === "idea" || (sourceName.trim() !== "" && sourcePath.trim() !== ""));
  const commandName = props.mode === "idea" ? "project.create" : "project.onboard";

  return (
    <form
      className="card inline-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready) {
          return;
        }
        props.onSubmit(commandName, props.mode === "idea"
          ? { name: name.trim(), goal: goal.trim() }
          : { name: name.trim(), goal: goal.trim(), source_name: sourceName.trim(), source_path: sourcePath.trim() });
      }}
    >
      <div className="form-head">
        <h2>{props.mode === "idea" ? "从想法新建项目" : "接入已有项目"}</h2>
        <button type="button" onClick={props.onClose}>
          取消
        </button>
      </div>
      <label className="field">
        <span>项目名称</span>
        <input type="text" value={name} onChange={(event) => setName(event.target.value)} required />
      </label>
      <label className="field">
        <span>长期目标</span>
        <textarea rows={3} value={goal} onChange={(event) => setGoal(event.target.value)} required />
      </label>
      {props.mode === "existing" ? (
        <>
          <label className="field">
            <span>源目录名称</span>
            <input type="text" value={sourceName} onChange={(event) => setSourceName(event.target.value)} required />
          </label>
          <label className="field">
            <span>源目录路径</span>
            <input type="text" value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} required />
          </label>
          <p className="note">接入以后会登记源目录、采集代码快照并开始建档事项（3.8）。</p>
        </>
      ) : null}
      <button type="submit" className="primary" disabled={props.busy || !ready}>
        {props.busy ? "正在提交" : props.mode === "idea" ? "新建项目" : "接入项目"}
      </button>
      {props.rejection ? <p className="error" role="status">{props.rejection.message}（原因 {props.rejection.reason}）</p> : null}
      {props.submitted ? <p className="hint" role="status">已提交，等待写入结果</p> : null}
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
    <div className="project-menu">
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
          <label className="field">
            <span>新的项目名称</span>
            <input type="text" value={nextName} onChange={(event) => setNextName(event.target.value)} />
          </label>
          <button type="submit" className="primary" disabled={props.busy}>
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
