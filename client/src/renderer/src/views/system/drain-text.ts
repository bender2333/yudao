// 排空确认与提示的文案（工单 #663）。
// 「开始排空」这一步在当前版本里回不去，点下去以前要说清楚后果与剩下的那条路；
// 排空期间新事项只排队不开始，用户在别处也要能看出原因。
// 纯模块，单元测试直接调用。

/** 确认框的标题 */
export const DRAIN_CONFIRM_TITLE = "让这个实例不再开始新事项？";

/** 确认框里逐条写的后果与出路 */
export const DRAIN_CONFIRM_LINES: string[] = [
  "点了以后，这个实例不再开始新的事项：排着队的事项要等正在执行的事项结束。",
  "这一步在当前版本里回不去，没有取消的办法。",
  "剩下的那条路是「强制升级」：正在执行的事项记为因升级停止，用已经采纳的成果重新开始。",
  "以后可以在「系统 / 运行与执行槽位」这一页看到当前的状态。",
];

/** 确认框里那个真的做下去的按钮 */
export const DRAIN_CONFIRM_CONFIRM = "不再开始新事项";

/** 确认框里那个不做的按钮 */
export const DRAIN_CONFIRM_CANCEL = "先不开始";

/**
 * 排空期间给用户看的一句提示：新的事项为什么没有开始。
 * 没有排空时是空（页面上不出现这句话）。
 */
export function drainNoticeText(state: string | null | undefined): string | null {
  if (state === "draining") {
    return "实例正在停止开始新事项：新的事项会排队，等正在执行的事项结束。";
  }
  if (state === "ready") {
    return "实例已经不再开始新事项：新的事项会排队，等升级。";
  }
  return null;
}
