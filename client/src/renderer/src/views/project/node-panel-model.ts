// 节点面板里的各段（工单 #1712；设计说明「项目页上的内容在哪里看」的缺口在 #1715 补齐）。
//
// 设计说明 docs/design/project-organization.md「节点面板与箭头面板接住的内容」把节点面板从上到下分成几段：
//   这个职能的状态与原因、在等什么、等了多久                        project.loop（图的节点）、run.asks
//   正在工作时写当前任务与最近一个动作，下面是实时输出与后台命令      run.steps、attempt.live
//   执行机器、等模型服务、结果未知、未读指导数、等它回答的询问数、
//   手边的摘要与笔记数、角色、最近一次请求的模型与协议、档位          department.workspace
//   指导与处理状态                                                department.workspace 的 guidance
//   它的往来                                                      run.asks（图的询问）
//   底部两个入口：「职能详情」「本职能的模型请求」                    设置页的两节
// 「项目页上的内容在哪里看」给出每一段读哪一条查询；验收见 #1707 的补充条第 15 条。
//
// 这里只算文字与结构，loop-panel.tsx 只按它画。实时输出那一段的开关也在这里定：不在工作的职能没有这一段。
// 面板里的职能名都取自图上这个节点的 label 与工作间的角色，不写死任何职能清单。
//
// 引用的模块写成带 .ts 的名字：单元测试用 node --test 直接跑 TypeScript，不带扩展名找不到模块。

import type { AskView, DepartmentWorkspaceResult } from "../../api/generated/types.gen.ts";
import { EMPTY_FILTERS } from "./observe-filter.ts";
import { REQUESTS_SECTION, paths } from "../../shell/routing.ts";
import { GUIDANCE_STATUS, roleBarText } from "./labels.ts";
import { waitedText } from "./floor-text.ts";
import type { LoopNode } from "./loop-graph-model.ts";

/** 面板里的一行事实：左边一项名，右边一句话。 */
export interface PanelFact {
  label: string;
  value: string;
}

/** 面板上从上到下的那几段（画由 loop-panel.tsx 负责）。 */
export interface NodePanelView {
  /** 状态与原因：图上的节点给出的那一句 */
  state: string;
  /** 在等什么：节点上开着的询问，每一句一行 */
  waiting: string[];
  /** 等了多久：它发出、还没答的询问最早那一封等了多久（没有在等时写 NO_WAIT_TEXT） */
  waited: string;
  /** 实时的模型输出与后台命令这一段只在正在工作的节点上有 */
  live: boolean;
  /** 工作间的事实、最近一次请求的模型与协议、档位，以及它的指导与处理状态 */
  facts: PanelFact[];
  /** 底部两个入口：职能详情、本职能的模型请求（带职能筛选） */
  links: { detail: string; requests: string };
}

/** 图上这个节点还没有状态时写这一句（与设计说明「状态与原因」一条同一句）。 */
export const NO_STATE_TEXT = "现在没有状态";
/** 工作间没有上报执行机器时写这一句。 */
export const NO_MACHINE_TEXT = "没有上报执行机器";
/** 这个职能还没有过模型请求时写这一句。 */
export const NO_LAST_CALL_TEXT = "这个职能还没有模型请求";
/** 服务端没给这一项时写的字（与页面其他地方同一句）。 */
export const NOT_REPORTED_TEXT = "未上报";
/** 没有询问在等这个职能回答时写这一句。 */
export const NO_ASK_TEXT = "没有询问在等它回答";
/** 这个职能还没有收到过指导时写这一句。 */
export const NO_GUIDANCE_TEXT = "还没有收到指导";
/** 没有在等什么（或问不出来）时，等了多久写这一句。 */
export const NO_WAIT_TEXT = "没有在等什么";

function stringOf(value: unknown): string | null {
  if (typeof value === "string") {
    return value === "" ? null : value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return null;
}

/** 状态与原因：节点上已经拼好（状态词，有原因时括号里写原因），这里只补没有状态时的那一句。 */
export function stateText(node: LoopNode): string {
  return node.state === "" ? NO_STATE_TEXT : node.state;
}

/**
 * 实时的模型输出与后台命令这一段出不出现：只有正在工作的职能有这一段的开关。
 * 不在工作的职能没有实时输出那一段（设计说明「节点面板与箭头面板接住的内容」）。
 */
export function liveOutputShown(node: LoopNode): boolean {
  return node.working;
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** 工作间里与面板有关的那几行：执行机器、等模型服务、结果未知、未读指导、等它回答的询问、手边的摘要与笔记、角色。 */
export function workshopFacts(data: DepartmentWorkspaceResult | null): PanelFact[] {
  if (data === null) {
    return [];
  }
  const room = data.room;
  const asks = numberOr((room.pipes as Record<string, unknown> | null | undefined)?.letters_waiting, 0);
  const facts: PanelFact[] = [
    { label: "执行机器", value: stringOf(room.machine) ?? NO_MACHINE_TEXT },
    { label: "等模型服务", value: room.waiting_provider ? "正在等待模型服务" : "没有在等待模型服务" },
    { label: "结果未知", value: room.remote_unknown ? "有结果未知的远程动作" : "没有结果未知的远程动作" },
    { label: "未读指导", value: `${room.mailbox} 封未读指导` },
    { label: "等它回答的询问", value: asks <= 0 ? NO_ASK_TEXT : `${asks} 封询问在等它回答` },
    {
      label: "手边的摘要与笔记",
      value: `摘要 ${numberOr(room.summaries, 0)} 份、笔记 ${numberOr(room.pinned_notes, 0)} 条`,
    },
  ];
  for (const role of room.roles) {
    facts.push({ label: "角色", value: `${role.name}：${roleBarText(role)}` });
  }
  return facts;
}

/**
 * 最近一次请求实际使用的模型、协议与发送的档位（取自工作间的 last_call）：
 * 模型先看请求的模型、没有就写实际使用的；协议照请求时给的那一份；档位写请求的与真正发送的。
 */
export function lastRequestFacts(data: DepartmentWorkspaceResult | null): PanelFact[] {
  if (data === null) {
    return [];
  }
  if (data.last_call === null) {
    return [{ label: "最近一次请求", value: NO_LAST_CALL_TEXT }];
  }
  const lastCall = data.last_call as Record<string, unknown>;
  const model = stringOf(lastCall["requested_model"]) ?? stringOf(lastCall["actual_model"]) ?? NOT_REPORTED_TEXT;
  const protocol = stringOf(lastCall["requested_protocol"]) ?? NOT_REPORTED_TEXT;
  const requested = stringOf(lastCall["requested_tier"]) ?? NOT_REPORTED_TEXT;
  const sent = stringOf(lastCall["sent_tier"]) ?? NOT_REPORTED_TEXT;
  return [{ label: "最近一次请求", value: `${model}（协议 ${protocol}，请求 ${requested}，实际发送 ${sent}）` }];
}

/**
 * 指导与处理状态（设计说明「项目页上的内容在哪里看」里那一格）：
 * 每个职能收到的指导一行，写第几版与它看到了哪一步（未接收、已进入模型输入、已回答）。
 *
 * 为什么放在节点面板而不是时序图：时序图与线程都只读 project.flow，那里没有处理状态；
 * 要在时序图里补，得把 department.workspace 的指导与 flow 的行按事件对起来（跨两处查询对行，容易错位），
 * 而节点面板已经读 department.workspace，状态就在同一份数据里。
 */
export function guidanceFacts(data: DepartmentWorkspaceResult | null): PanelFact[] {
  if (data === null) {
    return [];
  }
  const guidance = data.guidance ?? [];
  if (guidance.length === 0) {
    return [{ label: "指导", value: NO_GUIDANCE_TEXT }];
  }
  return guidance.map((record) => ({
    label: `指导（第 ${record.version} 版）`,
    value: GUIDANCE_STATUS[record.status] ?? record.status,
  }));
}

/**
 * 等了多久：这个职能发出、还没有回答的询问里最早的那一封，从它开始等到现在多久。
 *
 * 口径与概览页那一行「最久等了 …」相同（floor-text.ts 的 waitedText）：取最早的时间再按时长写；
 * 没有在读的询问、或没有开始时间时写 NO_WAIT_TEXT，不写一个假数。
 */
export function waitedTextFor(
  node: LoopNode,
  asks: readonly AskView[] | null | undefined,
  now: number,
): string {
  const started = (asks ?? [])
    .filter((ask) => ask.status === "进行中" && ask.requester === node.id)
    .map((ask) => ask.started_at)
    .sort()[0];
  const text = waitedText(started, now);
  return text === "" ? NO_WAIT_TEXT : `已等 ${text}`;
}

/** 底部两个入口的地址：「职能详情」到节点所在职能的详情页（工单 #1713）。 */
export function entryLinks(projectId: string, workItemId: string, department: string): { detail: string; requests: string } {
  const workItem = workItemId === "" ? null : workItemId;
  return {
    detail: paths.departmentDetail(projectId, department, { workItem }),
    // 带着职能筛选去「模型请求与用量」：地址里写 dept，到那一节筛选立即生效（工单 #1710）
    requests: paths.settings(projectId, {
      workItem,
      section: REQUESTS_SECTION,
      requests: { ...EMPTY_FILTERS, department },
    }),
  };
}

/** 面板的正文：从上到下那几段。 */
export function nodePanelView(
  node: LoopNode,
  data: DepartmentWorkspaceResult | null,
  projectId: string,
  workItemId: string,
  asks: readonly AskView[] | null | undefined = null,
  now: number = Date.now(),
): NodePanelView {
  return {
    state: stateText(node),
    waiting: [...node.waiting],
    waited: waitedTextFor(node, asks, now),
    live: liveOutputShown(node),
    facts: [...workshopFacts(data), ...lastRequestFacts(data), ...guidanceFacts(data)],
    links: entryLinks(projectId, workItemId, node.id),
  };
}
