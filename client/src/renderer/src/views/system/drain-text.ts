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
  "剩下的那条路是「强制升级」：正在执行的事项记为因升级停止，用项目的起点重新开始（采纳成果；没有时是起始文件夹的快照，都没有时是空树）。",
  "以后可以在「系统 / 运行与执行槽位」这一页看到当前的状态。",
];

/** 确认框里那个真的做下去的按钮 */
export const DRAIN_CONFIRM_CONFIRM = "不再开始新事项";

/** 确认框里那个不做的按钮 */
export const DRAIN_CONFIRM_CANCEL = "先不开始";

/**
 * 排空状态的中文名（工单 #1187，原型 v13 `js/ui/views/sys-runtime.js` 的 DRAIN_LABELS）：
 * 未排空、排空中、已排空可以升级，以及强制升级以后的「已强制升级」。
 * 计划的界面文字在这里，页面上不出现 idle、draining 这类取值。
 */
export const DRAIN_STATE_TEXT: Record<string, string> = {
  idle: "未排空",
  draining: "排空中",
  ready: "已排空，可以升级",
  forced: "已强制升级",
};

/** 强制升级确认框的标题（工单 #1187）：与开始排空一样，点下去以前要说清后果 */
export const FORCE_UPGRADE_CONFIRM_TITLE = "让正在进行的 run 记为因升级停止？";

/** 强制升级确认框里逐条写的后果与下一步 */
export const FORCE_UPGRADE_CONFIRM_LINES: string[] = [
  "确认以后，正在进行的 run 记为因升级停止，不再继续。",
  "对应的事项用项目的起点重新开始（采纳成果；没有时是起始文件夹快照，都没有时是空树），并排在队列最前面。",
  "这一步以后，这个实例处于「已强制升级」；装上新的版本重新启动，排空会解除。",
];

/** 强制升级确认框里那个真的做下去的按钮 */
export const FORCE_UPGRADE_CONFIRM_CONFIRM = "确认强制升级";

/** 强制升级确认框里那个不做的按钮 */
export const FORCE_UPGRADE_CONFIRM_CANCEL = "先不升级";

/**
 * 排空期间给用户看的一句提示：新的事项为什么没有开始，下一步做什么。
 * 没有排空时是空（页面上不出现这句话）。
 */
export function drainNoticeText(state: string | null | undefined): string | null {
  if (state === "draining") {
    return "实例正在停止开始新事项：新的事项会排队，等正在执行的事项结束。"
      + "排空完以后装上新的版本重新启动，这个实例会重新开始新事项。";
  }
  if (state === "ready") {
    return "实例已经不再开始新事项：新的事项会排队，等升级。"
      + "装上新的版本以后重新启动，排空会解除，这个实例重新开始新事项。";
  }
  return null;
}
