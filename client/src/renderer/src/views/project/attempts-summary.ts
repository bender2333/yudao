// 观测页副标题的计数说法（工单 #665）：范围里的模型请求总数与已经加载出来的行数
// 是两个数，不混在一起说。总数来自 project.usage（与请求记录同一组筛选），
// 已显示的是当前翻到的页累加起来的行数。纯函数，单元测试直接调用。

export function attemptsSummary(input: {
  /** 仍在进行的请求数 */
  inFlight: number;
  /** 范围里的模型请求总数；没有读到时是 null */
  total: number | null;
  /**
   * 总数读不出来时的原因（project.usage 失败）；有它时说明总数读不出来，
   * 不安静地少一句数字（工单 #775）。没有它时只说已显示的行数。
   */
  totalError?: string | null;
  /** 已经加载出来的行数 */
  loaded: number;
  /** 还有下一页 */
  more: boolean;
}): string {
  const parts: string[] = [`${input.inFlight} 个请求进行中`];
  if (input.total === null) {
    parts.push(input.totalError === null || input.totalError === undefined
      ? `已显示 ${input.loaded} 条`
      : `总数读不出来：${input.totalError}，已显示 ${input.loaded} 条`);
  } else {
    parts.push(`共 ${input.total} 次模型请求，已显示 ${input.loaded} 条`);
  }
  if (input.more) {
    parts.push("点「加载更多」继续");
  }
  return `${parts.join(" · ")}。调用目标、按栏目的来源与用量都在这里；用量只读显示。`;
}
