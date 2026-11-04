// 页面的部门从事实来（工单 #1457；项目的组织设计说明「页面跟着级别伸缩」；形态与核验角色设计说明
// 「形态随事项冻结」）：项目现在的组织（project.organization 的 departments）给出部门页签、看板的列、
// 部门页的默认部门与部门显示名；事项按它冻结的组织（project.loop 的 organization.roles）给出每个事项的部门。
//
// 这里只做取值与判断，不触碰网络与界面；页面组件引用这些函数，单元测试直接核对。
// 部门的中文名也在这里取：组织里有这个部门时用组织给的显示名，旧数据里的部门不在组织里时才用
// labels.ts 原有的写法（那份映射不在这张工单的改动范围内，只作兜底）。

import type {
  ProjectLoopResult, ProjectOrganizationResult, WorkItemCard,
} from "../../api/generated/types.gen";
import { paths } from "../../shell/routing.ts";
import { departmentName } from "./labels.ts";

// 一个部门在页面上的样子：标识与显示名
export type DepartmentView = {
  id: string;
  label: string;
};

// 一组部门在页面上的名字：标识 → 显示名
export type DepartmentLabels = Record<string, string>;

// 项目现在这一份形态里的部门（按定义里的顺序）。
// 查询还没有数据、或者现在这一份已经不在发布里时为空：不拿别的形态的部门顶替。
export function projectDepartments(organization: ProjectOrganizationResult | null | undefined): DepartmentView[] {
  return (organization?.departments ?? []).map((department) => ({
    id: department.id,
    label: department.label,
  }));
}

// 部门标识到显示名（同名部门只留一个，后到的不会盖掉先到的）
export function departmentLabels(departments: readonly DepartmentView[]): DepartmentLabels {
  const labels: DepartmentLabels = {};
  for (const department of departments) {
    if (!(department.id in labels)) {
      labels[department.id] = department.label;
    }
  }
  return labels;
}

// 一个部门的显示名：组织里给出了就用它；旧数据里的部门不在组织里时用页面上原来的写法
export function departmentLabel(id: string | null | undefined, labels: DepartmentLabels): string {
  if (!id) {
    return "";
  }
  return labels[id] ?? departmentName(id);
}

// 部门页的默认部门：地址里写了就用它，没有时取项目现在组织里的第一个部门。
// 组织还没有数据、或者现在这一份不在发布里时为空，由调用处说清楚没有部门可看。
export function defaultDepartment(requested: string | null | undefined,
                                  departments: readonly DepartmentView[]): string {
  return requested ?? departments[0]?.id ?? "";
}

// 部门页签：每个部门一个页签，页签名与地址都取自事实，不写死三个
export function departmentTabs(projectId: string, departments: readonly DepartmentView[],
                               scope: { workItem: string | null }): {
  label: string;
  hash: string;
  query: string;
}[] {
  return departments.map((department) => ({
    label: department.label,
    hash: paths.dept(projectId, department.id, scope),
    query: "department.workspace",
  }));
}

// 每个事项冻结的组织里的部门（project.loop 的 organization.roles）；形态不在这一版发布里的事项没有
export function itemDepartments(loop: ProjectLoopResult | null | undefined): Record<string, DepartmentView[]> {
  const result: Record<string, DepartmentView[]> = {};
  for (const item of loop?.work_items ?? []) {
    result[item.work_item_id] = (item.organization?.roles ?? []).map((role) => ({
      id: role.id,
      label: role.label,
    }));
  }
  return result;
}

// 看板的部门列：项目现在组织里的部门在前，后面接还在跑的事项里旧组织的部门。
// 中途换了形态时，老事项按它冻结的组织显示部门，新事项按新的；已经结束的事项不往看板加列。
// 同一个部门只出现一次，列标题用先到的那一个（现在组织的名字优先）。
export function boardDepartments(props: {
  current: readonly DepartmentView[];
  items: readonly WorkItemCard[];
  itemDepartments: Record<string, readonly DepartmentView[]>;
}): DepartmentView[] {
  const departments: DepartmentView[] = [...props.current];
  const seen = new Set(departments.map((department) => department.id));
  for (const item of props.items) {
    if (item.status !== "in_progress") {
      continue;
    }
    for (const department of props.itemDepartments[item.work_item_id] ?? []) {
      if (seen.has(department.id)) {
        continue;
      }
      seen.add(department.id);
      departments.push(department);
    }
  }
  return departments;
}
