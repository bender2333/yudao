// 建档状态（3.8，docs/design/existing-project-onboarding.md 第 3.1、3.3、3.4 节）：接入已有项目的
// 拒绝原因、建档状态标记，以及由 tool_started 事件驱动的「阅读已有项目」动作。取值全部来自应用层的
// 命令结果与查询，没有对应数据时没有标记，界面不猜。

import type { ActionView, DecisionView, EventObject, ProjectRow, Rejected } from "../../api/generated/types.gen";

// 源目录无效时服务端把各条相对路径与处理方法写进 message，用分号连接（harness/public_tree.py 的
// UnrepresentableWorkspace、harness/snapshot.py 的 TreeError）。界面按分号分行显示，路径原样给出。
export function sourceInvalidLines(rejection: Rejected): string[] {
  return rejection.message.split(";").map((line) => line.trim()).filter((line) => line !== "");
}

// 建档状态标记的中文名：按 onboarding_status 与是否有等待确认的初始 PRD 决定
export const ONBOARDING_MARKS: Record<string, string> = {
  onboarding: "建档中",
  awaiting_initial_prd: "等待确认初始 PRD",
  awaiting_onboarding: "等待建档",
};

// 驱动「阅读已有项目」动作的读取工具（设计第 3.3 节：读取、搜索与区间阅读工具的 tool_started）
export const READ_EXISTING_TOOLS = ["read_file", "search", "read_range"] as const;

// 接入命令的拒绝原因的中文说明。界面同时给出原因名、服务端的原因说明与其中列出的相对路径，
// 用户按相对路径处理以后重新提交（设计第 3.1 节 source_invalid 的 message 列出相对路径与处理方法）
export const ONBOARDING_REJECTION_REASONS: Record<string, string> = {
  source_invalid: "源目录不能作为代码快照的来源",
  not_allowed: "现在不能重新开始建档",
  not_found: "找不到这个项目",
  project_archived: "项目已经归档",
  busy: "前面还有事项在执行",
  provider_unavailable: "模型服务现在不可用",
};

/**
 * 接入与建档被拒绝时的中文说明：按拒绝原因给出中文说法与服务端列出的路径。
 * 内部原因标识不写进页面（工单 #319 第 5 项、工单 #671）。
 */
export function onboardingRejectionText(rejection: Rejected): string {
  return ONBOARDING_REJECTION_REASONS[rejection.reason] ?? "命令被拒绝";
}

/** 项目行里的建档标记：状态取自 projects.list，等待确认初始 PRD 由本项目的决定请求给出。 */
export function projectOnboardingMark(
  project: Pick<ProjectRow, "onboarding_status" | "project_id">,
  decisions: DecisionView[],
): string | null {
  const status = project.onboarding_status;
  if (status === null || status === undefined || status === "") {
    return null;
  }
  const awaiting = decisions.some((decision) => decision.kind === "initial_prd"
    && decision.status === "open"
    && (decision.project_id === project.project_id || decision.project_id === null));
  // 建档事项停下、run 已结束而项目在等用户回答时，标记写「等待确认初始 PRD」
  if (awaiting && status === "awaiting_onboarding") {
    return ONBOARDING_MARKS.awaiting_initial_prd;
  }
  return ONBOARDING_MARKS[status] ?? null;
}

/** 事件流里的一条事件是否是「阅读已有项目」的工具开始（设计第 3.3 节），返回工具名，不是则为空。 */
export function readExistingAction(event: EventObject): string | null {
  if (event.type !== "tool_started") {
    return null;
  }
  // 工具名在载荷的 name 上（harness/app/payloads.py 的 ToolStartedPayload）
  return (READ_EXISTING_TOOLS as readonly string[]).includes(event.payload.name)
    ? event.payload.name
    : null;
}

/** 已结束的读取动作（run.actions 的动作行）：返回最近一次读取的工具、部门与开始时间，不是读取工具时为空。
 *
 * 部门房间的页面可能在读取发生以后才打开，事件订阅只收到订阅之后的事件，
 * 已发生的读取按 run.actions 的动作列表读出（设计第 3.4 节：状态以查询为准）。
 */
export function lastReadExistingAction(
  actions: readonly Pick<ActionView, "tool" | "department" | "created_at">[],
): ReadAction | null {
  let latest: ReadAction | null = null;
  for (const action of actions) {
    if (!(READ_EXISTING_TOOLS as readonly string[]).includes(action.tool)) continue;
    if (latest !== null && action.created_at <= latest.at) continue;
    latest = { tool: action.tool, department: action.department, at: action.created_at };
  }
  return latest;
}

/** 一次读取动作的观察：工具、部门与开始时间（事件与动作列表两种来源给出同一个形状）。 */
export type ReadAction = {
  tool: string;
  department: string | null;
  at: string;
};
