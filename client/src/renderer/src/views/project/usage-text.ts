// 用量的显示（工单 #301）：请求记录表格的「用量」列与请求详情的「用量」行同一口径；
// 没有上报时写「未上报」。纯函数，单元测试直接调用。
export function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function formatTokens(value: number | null, suffix = ""): string {
  if (value === null || !Number.isFinite(value)) {
    return "未上报";
  }
  return `${value.toLocaleString("zh-CN")}${suffix}`;
}

export function usageText(usage: Record<string, unknown>): string {
  const total = numberValue(usage.total_tokens);
  const reported = usage.reported === true;
  if (!reported && total === null) {
    return "未上报";
  }
  return `${formatTokens(total, " token")}，输入 ${formatTokens(numberValue(usage.input_tokens))}，输出 ${formatTokens(numberValue(usage.output_tokens))}`;
}
