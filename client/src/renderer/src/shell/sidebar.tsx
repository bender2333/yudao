// 左侧栏（原型 v8 设计说明第 3.1 节）：品牌、首页、项目列表、「系统」分组。
// 每个入口按能力清单显示：能力清单缺少某个查询时，依赖它的入口不出现（工单验收）。
// 项目名称旁显示待回答的决定数量。

import type { Capabilities, ProjectRow } from "../api/generated/types.gen";

export type SidebarProps = {
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

export function Sidebar(props: SidebarProps) {
  const has = (name: string) => props.capabilities.queries.some((query) => query.name === name);
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
      </div>
      <div className="nav-group">
        <div className="nav-title">项目</div>
        {props.projects.length === 0 && <span className="nav-item" aria-disabled="true">没有项目</span>}
        {props.projects.map((project) => (
          <button
            key={project.project_id}
            className="nav-item"
            aria-current={project.project_id === props.activeProjectId ? "page" : undefined}
            onClick={() => props.onNavigate(`#/p/${project.project_id}/overview`)}
          >
            {project.name}
            {(props.pendingByProject[project.project_id] ?? 0) > 0 && (
              <span className="badge">{props.pendingByProject[project.project_id]}</span>
            )}
          </button>
        ))}
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
    </aside>
  );
}
