// 观测页的筛选条件（工单 #801）：范围与筛选条件分开。
// 范围是作用域，写在 ?w=（工单 #746）：看的是哪些事项的请求，项目级的一份。
// 部门是筛选条件，写在 ?dept=：看的是哪个部门的请求。
// 部门工作间的「本部门的模型请求」把部门带进观测页；观测页自己换筛选条件时，
// 地址里的部门跟着改，页面上写的与生效的始终是同一件事。

import { departmentName } from "./labels.ts";

// 观测页的一组筛选条件（页面内的一组条件，点「按条件筛选」以后生效）
export type Filters = {
  department: string;
  status: string;
  provider: string;
  requestedModel: string;
  actualModel: string;
  q: string;
};

export const EMPTY_FILTERS: Filters = { department: "", status: "", provider: "", requestedModel: "", actualModel: "", q: "" };

// 进入页面时的初值：地址里带了部门就用它（部门工作间带进来的），
// 其余条件按没有筛选处理
export function seedFilters(department: string | null): Filters {
  return { ...EMPTY_FILTERS, department: department ?? "" };
}

// 页面上说明当前筛选的是哪个部门：中文名，不出现内部标识；
// 没有部门筛选时不写这一句
export function departmentFilterNote(department: string): string {
  if (department === "") {
    return "";
  }
  return `只看${departmentName(department)}的请求`;
}
