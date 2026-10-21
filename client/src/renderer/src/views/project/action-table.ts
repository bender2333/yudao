// 动作与回执表格的表头与每一行的文字（工单 #655）。
// 「登记名」一列按 ADR-0038 删除命令登记以后恒为「没有回执」，从表里去掉；
// 显示命令原文与后端清掉登记名字段是另一张工单（#658），那里才改接口合同。
//
// 这个模块没有运行期依赖：客户端单元测试直接调用它核对表格的列与内容。

import type { ActionView } from "../../api/generated/types.gen";
import { ACTION_STATUS, departmentName, label } from "./labels.ts";

// 表格的列：工具、部门、状态、结果、输出引用与时间
export const ACTION_TABLE_HEAD = ["工具", "部门", "状态", "结果", "输出引用", "时间"];

// 动作这一行的文字：工具、部门、状态、结果与输出引用。
// 时间那一格是打开原始事件的按钮，由组件补上。
export function actionCells(action: ActionView): string[] {
  const receipt = action.receipt;
  return [
    action.tool,
    departmentName(action.department),
    label(ACTION_STATUS, action.status),
    receipt === null ? "没有回执" : (receipt.ok ? "成功" : (receipt.error || "失败")),
    receipt?.output_ref ? "有（见原始事件）" : "无",
  ];
}
