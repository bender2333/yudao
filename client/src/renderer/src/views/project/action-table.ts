// 动作与回执的文字（工单 #655、#658；工单 #1235 起由部门工作间的步骤时间线使用）。
// 「登记名」一列按 ADR-0038 删除命令登记以后恒为「没有回执」，不再有这一项；
// 「命令」一项按 ADR-0038 显示命令原文，凭据在后端已经换成名称，界面上没有密钥原文。
//
// 这个模块没有运行期依赖：步骤时间线按它的结果排版，客户端单元测试直接调用它核对文字。

import type { ActionView } from "../../api/generated/types.gen";
import { ACTION_STATUS, departmentName, label } from "./labels.ts";

// 一个动作的文字：工具、命令、部门、状态、结果与输出引用。
// 步骤时间线用其中的工具、命令、状态、结果与输出引用；部门在时间线里不写（整个页签就是本部门的）
export function actionCells(action: ActionView): string[] {
  const receipt = action.receipt;
  return [
    action.tool,
    commandOf(action),
    departmentName(action.department),
    label(ACTION_STATUS, action.status),
    receipt === null ? "没有回执" : (receipt.ok ? "成功" : (receipt.error || "失败")),
    receipt?.output_ref ? "有（见原始事件）" : "无",
  ];
}

// 动作实际执行的命令：bash 与 run_check 的参数里是命令原文；别的工具没有命令。
export function commandOf(action: ActionView): string {
  const command = action.receipt?.args?.command;
  return typeof command === "string" ? command : "";
}
