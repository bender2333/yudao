// 请求详情里的失败取值（工单 #305）：一次模型调用失败的分类与流本身给出的结束原因。
// 只读取已登记的查询结果（run.attempt 的一条记录），不依赖界面零件，因此可以在 node --test 下直接核对。

export type AttemptFields = Record<string, unknown>;

export const NO_FAILURE = "没有";
export const NOT_REPORTED = "未上报";

// 可以显示的取值：文字、数字与开关；空文字按未给出处理
function display(value: unknown): string | null {
  if (typeof value === "string") {
    return value === "" ? null : value;
  }
  return typeof value === "number" || typeof value === "boolean" ? String(value) : null;
}

// 记录里的嵌套对象（诊断）：缺失或写成列表时按空对象处理
function record(value: unknown): AttemptFields {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as AttemptFields : {};
}

// 失败类型：内核记录的分类（空输出记 empty_output），其次诊断里的错误种类；没有失败时写明「没有」
export function failureType(attempt: AttemptFields): string {
  return display(attempt.error_class) ?? display(attempt.reason) ?? display(record(attempt.diagnostics).error_type)
    ?? NO_FAILURE;
}

// 结束原因：提供方在流结束处给出的取值（length、max_tokens、completed 等）；没有记录时写明「未上报」
export function finishReason(attempt: AttemptFields): string {
  return display(record(attempt.diagnostics).finish_reason) ?? NOT_REPORTED;
}

// 详情的两行取值，顺序即页面上的显示顺序
export function failureRows(attempt: AttemptFields): [string, string][] {
  return [["失败类型", failureType(attempt)], ["结束原因", finishReason(attempt)]];
}
