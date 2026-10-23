// 写回在页面上怎么写（工单 #709）：写回结果与写回设置的中文说明。
// 页面上不出现英文内部标识与开发者措辞：状态与停止原因按中文写，
// 合并请求还只是本地记录这件事照实写明。

import type { WritebackRecordView } from "../../api/generated/types.gen";

// 写回结果的中文名。写回停止原因与 harness/app/labels.py 的 WRITEBACK_REASON_NAMES 是同一份取值，
// 事件说明与页面上的说明用同一个名字。
export const WRITEBACK_STATUS: Record<string, string> = {
  completed: "已经写回仓库",
  verified: "写回已核实",
  stopped: "写回停止",
  held: "写回等待",
  not_needed: "无需写回",
};

export const WRITEBACK_REASON: Record<string, string> = {
  conflict: "合并出现冲突",
  verification_failed: "最终树核验没有通过",
  target_changed: "目标分支已经推进",
  unrepresentable_path: "路径无法表示",
  missing_source_reference: "缺少事项起点依据",
  changes_already_present: "变更已经在目标分支上",
  waiting_previous_adoption: "前一次采纳还没有合入目标分支",
};

// 一次写回的结果的中文说明
export function writebackText(record: WritebackRecordView): string {
  const branch = record.branch === null || record.branch === "" ? "" : `分支 ${record.branch}`;
  const target = record.target_branch === null || record.target_branch === "" ? "" : `，目标分支 ${record.target_branch}`;
  if (record.status === "completed") {
    const request = record.pull_request_title === null || record.pull_request_title === ""
      ? ""
      : `；合并请求：${record.pull_request_title}`;
    // 合并请求还只是本地记录：照实写明，不说已经创建
    const local = record.pull_request_local_only ? "（合并请求目前只记录在本地，还没有在代码托管平台上创建）" : "";
    return `成果已经写回仓库：${branch}${target}${request}${local}`;
  }
  if (record.status === "verified") {
    return `写回已核实：${branch}${target}`;
  }
  if (record.status === "stopped") {
    const reason = WRITEBACK_REASON[record.reason ?? ""] ?? "写回没有完成";
    const conflicts = record.conflicts ?? [];
    const files = conflicts.length > 0 ? `；冲突的文件：${conflicts.join("、")}` : "";
    return `写回停止：${reason}${files}`;
  }
  if (record.status === "held") {
    return `写回等待：${WRITEBACK_REASON[record.reason ?? ""] ?? "前一次采纳还没有合入目标分支"}`;
  }
  if (record.status === "not_needed") {
    return `无需写回：${WRITEBACK_REASON[record.reason ?? ""] ?? "变更已经在目标分支上"}`;
  }
  return WRITEBACK_STATUS[record.status] ?? "写回没有完成";
}

// 源目录的写回设置（界面上写给用户看的一句话）
export function sourceWritebackText(setting: {
  writeback_enabled?: boolean;
  target_branch?: string;
  remote?: string;
}): string {
  if (setting.writeback_enabled !== true) {
    return "未打开";
  }
  const target = setting.target_branch ?? "";
  if (target === "") {
    return "已打开，没有填目标分支";
  }
  const remote = setting.remote ?? "";
  return remote === ""
    ? `已打开，目标分支 ${target}`
    : `已打开，目标分支 ${target}，远端 ${remote}`;
}
