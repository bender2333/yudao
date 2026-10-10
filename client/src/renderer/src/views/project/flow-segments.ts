// 流转覆盖层的分段（工单 #379，来自 #366 的审查）：楼层画面的「流转」覆盖层把 project.flow 的行
// 聚成段，一段一条路径，段落上的「N 次」标签落在这条路径的中点。
// 分组键只含起点、终点与是否返工：同一对部门的全部非返工行并入同一段，否则同一条路径上的
// 多个标签互相遮挡（原型 v10 js/ui/scenes.js 的 overlayData）。

import type { FlowRecord } from "../../api/generated/types.gen";

export interface FlowSegment {
  from: string;
  to: string;
  count: number;
  last_at: string;
  kind: string;
}

export function flowSegmentsOf(records: FlowRecord[] | null): FlowSegment[] {
  const groups: Record<string, FlowSegment> = {};
  for (const record of records ?? []) {
    if (!record.direction_from || !record.direction_to) continue;
    const rework = record.kind === "返工";
    const key = `${record.direction_from}>${record.direction_to}>${rework ? "rework" : ""}`;
    const group = groups[key];
    if (group) {
      group.count += 1;
      if (record.created_at > group.last_at) group.last_at = record.created_at;
    } else {
      groups[key] = {
        from: record.direction_from,
        to: record.direction_to,
        count: 1,
        last_at: record.created_at,
        kind: rework ? "rework" : record.kind,
      };
    }
  }
  return Object.values(groups);
}
