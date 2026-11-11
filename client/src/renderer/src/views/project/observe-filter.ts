// 观测页与设置页「模型请求与用量」这一节共用的一组筛选条件（工单 #801、#1710）：范围与筛选条件分开。
// 范围是作用域，写在 ?w=（工单 #746）：看的是哪些事项的请求，项目级的一份。
// 部门是筛选条件，写在 ?dept=：看的是哪个部门的请求。
// 职能选项取自项目现在的组织（工单 #1710）：不写死产品、工程、质检三个，项目里有哪些职能就列哪些。
// 设置页这一节的筛选条件也写在地址里（工单 #1710）：从地址读回来、写回地址，
// 刷新、后退与从请求详情返回都对得上；观测页与设置页用的是同一组函数。
//
// 这里只做取值与转换，不触碰网络与界面；单元测试直接调用（client/tests/unit/requests-filter.test.ts）。

import { departmentName } from "./labels.ts";

// 一组筛选条件（页面内的一组条件，点「按条件筛选」以后生效）
export type Filters = {
  department: string;
  status: string;
  provider: string;
  requestedModel: string;
  actualModel: string;
  q: string;
};

export const EMPTY_FILTERS: Filters = { department: "", status: "", provider: "", requestedModel: "", actualModel: "", q: "" };

// 六格的名字与顺序：地址读写的顺序、判断有没有变化都按它来
export const FILTER_FIELDS: readonly (keyof Filters)[] = ["department", "status", "provider", "requestedModel", "actualModel", "q"];

// 地址里的参数名（工单 #1710）：模型分请求的与返回的两格，各用各的参数名。
// 职能沿用 ?dept=（工单 #801）：观测页与设置页说的是同一件事，参数名不另起一个。
const FILTER_PARAMS: Record<keyof Filters, string> = {
  department: "dept",
  status: "status",
  provider: "provider",
  requestedModel: "model",
  actualModel: "model_returned",
  q: "q",
};

// 进入页面时的初值：地址里带了职能就用它（职能工作间带进来的），
// 其余条件按没有筛选处理
export function seedFilters(department: string | null): Filters {
  return { ...EMPTY_FILTERS, department: department ?? "" };
}

// 地址读出一组筛选条件（工单 #1710）：没有写的格按没有筛选处理，空串与空白也按没有；
// 职能按原样读出，认不认它由页面拿项目的职能清单去对，这里不按写死的三个拒绝
export function filtersFromQuery(query: URLSearchParams): Filters {
  const values: Filters = { ...EMPTY_FILTERS };
  for (const field of FILTER_FIELDS) {
    const raw = query.get(FILTER_PARAMS[field]);
    values[field] = raw === null ? "" : raw.trim();
  }
  return values;
}

// 一组筛选条件写成地址参数：只写有值的，地址里不留空的键
export function filtersQuery(filters: Filters): [string, string][] {
  const pairs: [string, string][] = [];
  for (const field of FILTER_FIELDS) {
    const value = filters[field].trim();
    if (value !== "") {
      pairs.push([FILTER_PARAMS[field], value]);
    }
  }
  return pairs;
}

function sameFilters(left: Filters, right: Filters): boolean {
  return FILTER_FIELDS.every((field) => left[field] === right[field]);
}

// 地址带来的筛选并进页面已经生效的筛选（工单 #1710）：只改地址这次变了的那几格，
// 页面上另有、地址里没有的几格（观测页只在页面内生效的状态与模型）留着不动。
// 地址与上一次没有不同时返回原来的对象，页面不用重新渲染。
export function mergeAddressFilters(applied: Filters, address: Filters, previous: Filters): Filters {
  if (sameFilters(address, previous)) {
    return applied;
  }
  const next: Filters = { ...applied };
  for (const field of FILTER_FIELDS) {
    if (address[field] !== previous[field]) {
      next[field] = address[field];
    }
  }
  return next;
}

// 职能选项取自项目现在的组织（工单 #1710）：项目里有哪些职能就列哪些；
// 组织还没有数据时没有选项，不拿默认的三个补位。
export function departmentOptions(departments: readonly { id: string; label: string }[]): { value: string; label: string }[] {
  return departments.map((department) => ({ value: department.id, label: department.label }));
}

// 页面上说明当前筛选的是哪个职能：用项目组织给的显示名，不出现内部标识；
// 没有职能筛选时不写这一句。组织还没有读到（labels 为空）时用页面原有的写法。
export function departmentFilterNote(department: string, labels: Record<string, string> = {}): string {
  if (department === "") {
    return "";
  }
  return `只看${labels[department] ?? departmentName(department)}的请求`;
}

// 用量分组的名称（工单 #1710）：后端按职能分组时给的是职能标识，页面换成项目组织里的显示名；
// 不在当前组织里的旧分组用后端给的名字，再没有就用标识。按模型分组时后端给的已经是模型名。
export function usageGroupName(group: { key: string; label?: string | null }, labels: Record<string, string>): string {
  const fromOrganization = labels[group.key];
  if (fromOrganization !== undefined && fromOrganization !== "") {
    return fromOrganization;
  }
  return group.label ? group.label : group.key;
}
