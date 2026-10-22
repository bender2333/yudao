// 执行槽位页上的槽位显示（工单 #727）。
// 现在一次只执行一个事项：总数是 1，不看 execution.slots 参数的现值。
// 参数留着是为了 #19（多项目并行）做完以后只改这一处。
// 纯模块，单元测试直接调用。

export type SlotInput = {
  /** 正在执行的事项数（system.status 的 running_runs）。 */
  running_runs: number;
  /** execution.slots 参数的现值：现在不读它。 */
  slot_parameter: number | null;
};

export type SlotView = {
  /** 槽位总数：现在一次只执行一个事项，是 1。 */
  total: number;
  /** 已占用的槽位数。 */
  used: number;
  /** 画出来的灯：现在只有一盏。 */
  lamps: { on: boolean; title: string }[];
  /** 这一节的副标题。 */
  subtitle: string;
};

/**
 * 执行槽位的显示。
 * ponytail: #19（多项目并行）做完以后改回按 slot_parameter 显示总数与盏数。
 */
export function slotView(input: SlotInput): SlotView {
  const total = 1;
  const used = input.running_runs > 0 ? 1 : 0;
  return {
    total,
    used,
    lamps: [{ on: used > 0, title: used > 0 ? "已占用" : "空闲" }],
    subtitle: "当前一次只执行一个事项；不同项目并行在多项目并行完成以后开放",
  };
}
