// 职能详情页的正文（工单 #1713）：项目的组织设计说明 4.9「职能详情」里「发布带的那一版」，
// 以及模型与 Prompt 那一组的来源写法（模型管理设计说明 9.2）。
//
// 一页点进去的职能详情：职责与写入范围只读，取自项目现在的组织（project.organization 的 organization）；
// 模型与 Prompt 写入本项目的职能设置（project.settings），每项写明跟随发布还是本项目写入。
// 工具许可、可见范围与位置这一版不显示：组织的查询还没有给出它们。
//
// 这里只算文字与地址，不碰网络与界面；页面照它画，单元测试直接核对。
// 引用的模块写成带 .ts 的名字：单元测试用 node --test 直接跑 TypeScript，不带扩展名找不到模块。

import type {
  DepartmentSetting, DraftOrganization,
} from "../../api/generated/types.gen";
import { EMPTY_FILTERS } from "./observe-filter.ts";
import { paths, REQUESTS_SECTION } from "../../shell/routing.ts";

// 一行只读的文字：左边是项名，右边是值
export interface DetailRow {
  label: string;
  value: string;
}

// 写入范围的中文（服务端的取值只有这两种，见定义里的 WriteScopeKind）
export const WRITE_SCOPE_TEXT: Record<string, string> = {
  workspace: "运行工作区",
  check_materials: "只写检查材料",
};

// 来源的两个说法（工单验收第 1 条）：本项目的职能设置写了这一项，就是「本项目写入」；
// 没写就跟随发布里的职能默认
export const FOLLOW_SOURCE = "跟随发布";
export const OWN_SOURCE = "本项目写入";

// 这一版不显示的几项：组织的查询还没有给出它们
export const NOT_SHOWN_NOTE = "工具许可、可见范围与位置这一版不显示：组织的查询还没有给出它们。";

// 写入范围只读：取值不在表里时照原样写出来，不猜
export function writeScopeText(scope: string): string {
  return WRITE_SCOPE_TEXT[scope] ?? (scope === "" ? "未上报" : scope);
}

// 来源文字：写了这一项就是本项目写入，没写就跟随发布
export function sourceText(written: boolean): string {
  return written ? OWN_SOURCE : FOLLOW_SOURCE;
}

// 一个职能在组织里的那一份（按标识取；组织还没有数据时没有）
export function draftDepartment(organization: DraftOrganization | null,
                                department: string): DraftOrganization["departments"][number] | null {
  return (organization?.departments ?? []).find((item) => item.id === department) ?? null;
}

// 成果种类的名字（关注的成果与交出的成果都按标识列出）
function outcomeLabel(organization: DraftOrganization | null, id: string): string {
  return (organization?.outcome_kinds ?? []).find((item) => item.id === id)?.label ?? id;
}

// 部门的显示名：组织里有就用组织的写法，没有就照标识写
function departmentLabel(organization: DraftOrganization | null, id: string): string {
  return (organization?.departments ?? []).find((item) => item.id === id)?.label ?? id;
}

// 核验声明（设计说明 4.9 的职责一组）：不核验，或写明核验哪个职能的哪种成果
export function verificationText(organization: DraftOrganization | null, department: string): string {
  const edges = (organization?.verification ?? []).filter((edge) => edge.verifier === department);
  if (edges.length === 0) {
    return "不核验";
  }
  return edges
    .map((edge) => `核验「${departmentLabel(organization, edge.verified)}」的「${outcomeLabel(organization, edge.outcome)}」`)
    .join("、");
}

// 可以询问谁：默认写「其余职能」；只有一个职能时这一行不出现（工单验收第 1 条）
export function askingText(organization: DraftOrganization | null): string | null {
  const others = (organization?.departments ?? []).length;
  return others > 1 ? "其余职能" : null;
}

// 职责的一组行，按设计说明 4.9 的顺序（只读，取自项目现在的组织）
export function dutyRows(organization: DraftOrganization | null, department: string): DetailRow[] {
  const item = draftDepartment(organization, department);
  const watched = (item?.watched ?? []).map((id) => outcomeLabel(organization, id));
  const outcomes = (item?.outcomes ?? []).map((id) => outcomeLabel(organization, id));
  const rows: DetailRow[] = [
    { label: "显示名", value: item?.label ?? department },
    { label: "它对什么负责", value: item?.target || "未上报" },
    { label: "凭什么判断", value: item?.evidence || "未上报" },
    { label: "怎么工作", value: item?.work || "未上报" },
    { label: "关注的成果", value: watched.length === 0 ? "无" : watched.join("、") },
    { label: "交出的成果", value: outcomes.length === 0 ? "不交出成果，只回答询问" : outcomes.join("、") },
  ];
  const asking = askingText(organization);
  if (asking !== null) {
    rows.push({ label: "可以询问谁", value: asking });
  }
  rows.push({ label: "核验声明", value: verificationText(organization, department) });
  return rows;
}

// 写入范围的一行（只读）
export function scopeRows(organization: DraftOrganization | null, department: string): DetailRow[] {
  const item = draftDepartment(organization, department);
  return [{ label: "写入范围", value: writeScopeText(item?.write_scope ?? "") }];
}

// 模型与 Prompt 三項的来源（工单验收第 1 条）：按这一项有没有写入判断，不按设置记录有没有判断
export function settingSourceRows(setting: DepartmentSetting | null): DetailRow[] {
  return [
    { label: "模型", value: sourceText(Boolean(setting?.model_id)) },
    { label: "推理档位", value: sourceText(Boolean(setting?.requested_tier)) },
    { label: "职能 Prompt", value: sourceText(Boolean(setting?.text)) },
  ];
}

// 「本职能的模型请求」的去处：设置页的「模型请求与用量」这一节，带着职能筛选，进来就生效
export function requestsPath(projectId: string, workItemId: string | null, department: string): string {
  return paths.settings(projectId, {
    workItem: workItemId === "" ? null : workItemId,
    section: REQUESTS_SECTION,
    requests: { ...EMPTY_FILTERS, department },
  });
}
