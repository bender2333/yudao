// 事项看板的分组（docs/design/app-and-interface.md「事项看板在页面上的显示」）：纯函数，界面与单元测试都直接调用。
//
// 口径（工单 #1372 按代码与设计说明查清）：
//   - 排队中、已放行、已采纳、已停止按事项的状态分；停止的事项不再属于任何部门，单独一组，不并进部门列。
//   - 部门列按各部门在这个事项上的状态分：部门手上有这个事项（等用户、一轮工作中、询问中、核验中）时，
//     事项就在它的列里；部门在等待工作（等关注的成果出新版本）时不在。几个部门同时工作时同一事项出现在
//     几列里——「当前事项」的部门状态行说一个部门在一轮工作中，它的列里就一定有这个事项（工单 #1372）。
//   - 部门列的组成与顺序取自事项的部门（事项冻结的定义给出，见事项卡片的 departments），
//     不写死产品、工程、质检三栏；换了部门名的定义，部门列跟着换。

import type { WorkItemCard } from "../../api/generated/types.gen";
import { departmentName } from "./labels.ts";
import { boardDepartments, type DepartmentView } from "./organization.ts";

// 按状态分的四组，与事项的部门无关
export type FixedBoardGroup = "queue" | "released" | "adopted" | "stopped";

// 看板上的部门从事实来（工单 #1457）：项目现在组织里的部门与每个事项冻结的组织里的部门。
// 两样都没有时（旧服务、查询还没有数据）按事项卡片上的 departments 推导，与原来的做法一样
export interface BoardOrganization {
  /** 项目现在组织里的部门，按定义里的顺序 */
  departments?: readonly DepartmentView[];
  /** 每个事项冻结的组织里的部门（project.loop 的 organization.roles） */
  itemDepartments?: Record<string, readonly DepartmentView[]>;
}

export const BOARD_TITLES: [FixedBoardGroup, string][] = [
  ["queue", "排队中"], ["released", "已放行"], ["adopted", "已采纳"], ["stopped", "已停止"],
];

// 一个部门列：部门取自事项的定义，标题是页面上的部门名
export interface BoardDepartmentColumn {
  department: string;
  title: string;
  items: WorkItemCard[];
}

export interface BoardColumns {
  queue: WorkItemCard[];
  departments: BoardDepartmentColumn[];
  released: WorkItemCard[];
  adopted: WorkItemCard[];
  stopped: WorkItemCard[];
}

// 看板上的一组，按显示顺序排：排队中、各部门（定义里的顺序）、已放行、已采纳、已停止
export interface BoardGroup {
  key: string;
  title: string;
  items: WorkItemCard[];
}

function fixedTitle(key: FixedBoardGroup): string {
  return BOARD_TITLES.find(([name]) => name === key)?.[1] ?? key;
}

// 事项按状态落进固定的一组；进行中的事项由部门列决定，这里返回 null
function fixedGroupOf(item: WorkItemCard): FixedBoardGroup | null {
  if (item.status === "adopted") return "adopted";
  if (item.status === "released_unsettled") return "released";
  if (item.status === "stopped") return "stopped";
  if (item.status === "not_started" || item.status === "held") return "queue";
  return null;
}

// 部门列的部门与顺序：事项的 departments 键序就是定义里的顺序（服务端按事项的定义给出）。
// 旧数据没有 departments 时用所在部门；两处都没有的部门不出现。
function definitionDepartments(items: WorkItemCard[]): string[] {
  const order: string[] = [];
  const seen = new Set<string>();
  const add = (department: string | null | undefined): void => {
    if (!department || seen.has(department)) return;
    seen.add(department);
    order.push(department);
  };
  for (const item of items) {
    for (const department of Object.keys(item.departments ?? {})) add(department);
    add(item.department);
  }
  return order;
}

// 部门在「等待工作」以外的状态下都算手上有这个事项（三部门的循环结构第 2.1 节）
const IDLE_DEPARTMENT_STATE = "waiting";

// 这个事项要出现在哪些部门的列里
function departmentsOf(item: WorkItemCard): string[] {
  const departments = item.departments;
  if (departments !== null && departments !== undefined) {
    const inHand = Object.keys(departments).filter(
      (department) => departments[department].state !== IDLE_DEPARTMENT_STATE,
    );
    if (inHand.length > 0) return inHand;
  }
  // 没有部门状态（旧数据、没有进行中的 run），或者所有部门都在等成果：按所在部门放
  return item.department ? [item.department] : [];
}

// 部门列标题用的显示名：项目现在组织里的部门与事项冻结的组织里的部门都算；都没有时用页面上原来的写法
function departmentTitles(organization: BoardOrganization): Record<string, string> {
  const titles: Record<string, string> = {};
  for (const department of organization.departments ?? []) {
    if (!(department.id in titles)) {
      titles[department.id] = department.label;
    }
  }
  for (const departments of Object.values(organization.itemDepartments ?? {})) {
    for (const department of departments) {
      if (!(department.id in titles)) {
        titles[department.id] = department.label;
      }
    }
  }
  return titles;
}

export function boardColumns(items: WorkItemCard[], organization: BoardOrganization = {}): BoardColumns {
  const columns: BoardColumns = { queue: [], departments: [], released: [], adopted: [], stopped: [] };
  // 部门列的部门：组织里有数据时取项目现在组织里的部门 + 还在跑的事项里旧组织的部门（工单 #1457）；
  // 没有时按事项卡片上的 departments 推导（旧服务、查询还没有数据）
  const columnDepartments = organization.departments === undefined
    ? definitionDepartments(items)
    : boardDepartments({
      current: organization.departments,
      items,
      itemDepartments: organization.itemDepartments ?? {},
    }).map((department) => department.id);
  const titles = departmentTitles(organization);
  const byDepartment = new Map<string, WorkItemCard[]>(columnDepartments.map((department) => [department, []]));
  for (const item of items) {
    const fixed = fixedGroupOf(item);
    if (fixed !== null) {
      columns[fixed].push(item);
      continue;
    }
    const departments = departmentsOf(item);
    if (departments.length === 0) {
      // 还没有交给任何部门的事项（例如等待确认初始 PRD）在排队中
      columns.queue.push(item);
      continue;
    }
    for (const department of departments) {
      const bucket = byDepartment.get(department);
      if (bucket === undefined) {
        byDepartment.set(department, [item]);
      } else {
        bucket.push(item);
      }
    }
  }
  columns.departments = [...byDepartment.entries()].map(([department, groupItems]) => ({
    department, title: titles[department] ?? departmentName(department), items: groupItems,
  }));
  return columns;
}

// 界面按显示顺序用的一组一组（排队中、各部门、已放行、已采纳、已停止）
export function boardGroups(items: WorkItemCard[], organization: BoardOrganization = {}): BoardGroup[] {
  const columns = boardColumns(items, organization);
  return [
    { key: "queue", title: fixedTitle("queue"), items: columns.queue },
    ...columns.departments.map((column) => ({
      key: `department:${column.department}`, title: column.title, items: column.items,
    })),
    { key: "released", title: fixedTitle("released"), items: columns.released },
    { key: "adopted", title: fixedTitle("adopted"), items: columns.adopted },
    { key: "stopped", title: fixedTitle("stopped"), items: columns.stopped },
  ];
}
