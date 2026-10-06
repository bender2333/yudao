// 事项看板的分列（原型 v8 设计说明第 5.1 节）：纯函数，界面与单元测试都直接调用。
// 停止的事项不再属于任何部门，单独一列，不并进部门列。

import type { WorkItemCard } from "../../api/generated/types.gen";

export type BoardColumns = {
  queue: WorkItemCard[];
  product: WorkItemCard[];
  engineering: WorkItemCard[];
  quality: WorkItemCard[];
  released: WorkItemCard[];
  adopted: WorkItemCard[];
  stopped: WorkItemCard[];
};

export const BOARD_TITLES: [keyof BoardColumns, string][] = [
  ["queue", "排队中"], ["product", "产品"], ["engineering", "工程"], ["quality", "质检"],
  ["released", "已放行"], ["adopted", "已采纳"], ["stopped", "已停止"],
];

export function boardColumns(items: WorkItemCard[]): BoardColumns {
  const columns: BoardColumns = {
    queue: [], product: [], engineering: [], quality: [], released: [], adopted: [], stopped: [],
  };
  for (const item of items) {
    if (item.status === "adopted") {
      columns.adopted.push(item);
    } else if (item.status === "released_unsettled") {
      columns.released.push(item);
    } else if (item.status === "stopped") {
      columns.stopped.push(item);
    } else if (item.status === "not_started" || item.status === "held") {
      columns.queue.push(item);
    } else if (item.department === "engineering") {
      columns.engineering.push(item);
    } else if (item.department === "quality") {
      columns.quality.push(item);
    } else {
      columns.product.push(item);
    }
  }
  return columns;
}
