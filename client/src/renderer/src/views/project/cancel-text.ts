// 取消事项／放弃本次建档的确认（工单 #737）：这两个操作不可逆——事项停下以后不能接着做，
// 只能另建一个事项，所以点下去以前先说清后果，并给一次反悔的机会。
// 与其他不可逆的操作（开始排空、强制升级、移除模型访问定义）同一套做法：点下去只换来一次确认，
// 命令要到确认以后才交给服务端；确认按钮用 danger 样式，不做的那个用普通样式。
// 可逆的操作（归档项目可以「恢复项目」）不加确认。
// 纯模块，单元测试直接调用。

/** 点下去以后待确认的那一份：事项与它这一刻的版本，确认以后照它提交 */
export type CancelRequest = {
  work_item_id: string;
  /** 用户按下按钮时看到的那个事项版本（base_version） */
  base_version: number;
  /** 事项状态：决定这个按钮是「取消事项」还是「放弃本次建档」 */
  status: string;
};

/** 按钮上的字：等用户确认初始 PRD 的建档事项说「放弃本次建档」，进行中的说「取消事项」 */
export function cancelItemLabel(status: string): string {
  return status === "awaiting_initial_prd" ? "放弃本次建档" : "取消事项";
}

/** 确认框的标题 */
export function cancelConfirmTitle(status: string): string {
  return status === "awaiting_initial_prd" ? "放弃本次建档？" : "取消这个事项？";
}

/** 确认框里逐条写的后果与出路：取消以后不能恢复，只能另建一个事项 */
export function cancelConfirmLines(status: string): string[] {
  if (status === "awaiting_initial_prd") {
    return [
      "放弃以后不能恢复：这一轮等待确认的建档到此结束，等着你确认的初始 PRD 一并撤回。",
      "要接着建档只能另建一个事项（建档事项）从头再来：放弃以后「重新开始建档」可以用。",
    ];
  }
  return [
    "取消以后不能恢复：事项停下以后不能接着做，只能另建一个事项从头开始。",
    "已经交回的交付与材料留在项目里；这个事项的停止原因记为「运行已被取消」。",
  ];
}

/** 确认框里那个真的做下去的按钮 */
export const CANCEL_CONFIRM_CONFIRM = "确认取消";

/** 确认框里那个不做的按钮 */
export const CANCEL_CONFIRM_CANCEL = "先不取消";

/**
 * 取消事项的命令参数：只有用户在确认框里点过「确认取消」以后才给出（工单 #737）。
 * 点「取消事项」本身只换来一次确认，不产生命令；没有待确认的那一份时也不产生。
 */
export function cancelItemCommand(
  pending: CancelRequest | null,
  confirmed: boolean,
): { work_item_id: string; base_version: number } | null {
  if (pending === null || !confirmed) {
    return null;
  }
  return { work_item_id: pending.work_item_id, base_version: pending.base_version };
}
