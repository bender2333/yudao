// 用量的显示口径（工单 #301、#744）：请求记录表格的「用量」列、请求详情的「用量」行
// 与用量统计页签说的是同一件事——这一次请求有没有上报用量、上报了哪几项。
// 三处共用这里的函数：同一份数据得出同一句话（工单 #744：同一页三处说法不同）。
// 纯函数，单元测试直接调用。

export const NOT_REPORTED = "未上报";

export function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function formatTokens(value: number | null, suffix = ""): string {
  if (value === null || !Number.isFinite(value)) {
    return NOT_REPORTED;
  }
  return `${value.toLocaleString("zh-CN")}${suffix}`;
}

// 服务端逐项说明的覆盖情况（coverage）：哪一项报了、哪一项没报
function coverageStates(usage: Record<string, unknown>): Record<string, string> {
  const raw = usage.coverage;
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return {};
  }
  const states: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value === "string") {
      states[key] = value;
    }
  }
  return states;
}

// 一项有没有上报：服务端逐项说明过就按它说；没有说明就看有没有数值
function itemReported(value: number | null, state: string | undefined): boolean {
  if (state !== undefined) {
    return state !== "missing" && value !== null;
  }
  return value !== null;
}

// 一次请求的用量：有没有上报、总量、输入、输出
export type UsageView = {
  /** 这一次请求有没有上报用量（任何一项） */
  reported: boolean;
  /** 总 token */
  total: number | null;
  /** 输入 token */
  input: number | null;
  /** 输出 token */
  output: number | null;
};

// 有没有上报用量：服务端说上报了就是上报了（工单 #744）。
// 服务端明确说没有上报时不写数值——用量统计的「上报用量的请求」与总 Token 只数上报了的那些，
// 两处必须对得上。服务端没有这个标记时（有旧记录或只有摘要），按数据本身判断。
export function usageView(usage: Record<string, unknown>): UsageView {
  const total = numberValue(usage.total_tokens);
  const input = numberValue(usage.input_tokens);
  const output = numberValue(usage.output_tokens);
  const states = coverageStates(usage);
  const covered = Object.values(states).some((state) => state === "reported");
  const flag = usage.reported;
  const reported = flag === false
    ? false
    : flag === true
      ? true
      : usage.source === "reported"
        || covered
        || itemReported(total, states.total_tokens)
        || itemReported(input, states.input_tokens)
        || itemReported(output, states.output_tokens);
  return {
    reported,
    total: itemReported(total, states.total_tokens) ? total : null,
    input: itemReported(input, states.input_tokens) ? input : null,
    output: itemReported(output, states.output_tokens) ? output : null,
  };
}

// 这个范围里上报了用量的请求数（工单 #744）：一个都没有时写「未上报」，
// 与请求记录表里的「未上报」是同一句话；三处说的是同一件事
export function reportedCountText(value: unknown): string {
  const count = numberValue(value);
  if (count === null || count === 0) {
    return NOT_REPORTED;
  }
  return `${count} 个`;
}

// 一次请求的用量显示（表格列与详情行共用）：报了哪几项写哪几项，没报的那几项写「未上报」，
// 一次都没有上报时只写「未上报」
export function usageText(usage: Record<string, unknown>): string {
  const view = usageView(usage);
  if (!view.reported) {
    return NOT_REPORTED;
  }
  if (view.total === null && view.input === null && view.output === null) {
    // 报了用量但没有 token 数值（例如只报了成本或缓存明细）
    return "上报了用量，没有 token 数值";
  }
  return [
    `总 ${view.total === null ? NOT_REPORTED : formatTokens(view.total, " token")}`,
    `输入 ${view.input === null ? NOT_REPORTED : formatTokens(view.input)}`,
    `输出 ${view.output === null ? NOT_REPORTED : formatTokens(view.output)}`,
  ].join("，");
}
