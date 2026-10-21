// 项目列表的查询参数与可见性（工单 #672）：侧栏的「显示归档的项目」开关要真的作用到查询上，
// 勾上时用 include_archived=true 取数，已归档的项目才会出现在列表里、菜单里才有「恢复项目」。
// 纯函数，单元测试直接调用。

import type { ProjectRow } from "../../api/generated/types.gen";

/** 项目列表的查询参数：按「显示归档的项目」开关给出。 */
export function projectsListParams(includeArchived: boolean): Record<string, unknown> {
  return { include_archived: includeArchived };
}

/** 侧栏里显示的项目：按开关与搜索词过滤（开关关闭时已归档的项目不列出）。 */
export function visibleProjects(
  projects: ProjectRow[],
  options: { search: string; includeArchived: boolean },
): ProjectRow[] {
  const needle = options.search.trim().toLowerCase();
  return projects.filter((project) => {
    if (!options.includeArchived && project.archived) {
      return false;
    }
    if (needle === "") {
      return true;
    }
    return project.name.toLowerCase().includes(needle) || project.goal.toLowerCase().includes(needle);
  });
}
