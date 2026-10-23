// 事项范围在页面上的说明（工单 #746）：范围是项目级的一份作用域，
// 页面按事项的名字说明当前的范围，不显示事项标识这类内部标识。
// 名字取自 project.overview 的事项列表；还没有取到时返回空串，
// 调用处按自己那句话决定怎么写（不拿标识凑数）。

import type { WorkItemCard } from "../../api/generated/types.gen";

export function scopeName(items: WorkItemCard[], workItemId: string | null): string {
  if (workItemId === null) {
    return "";
  }
  return items.find((item) => item.work_item_id === workItemId)?.title ?? "";
}
