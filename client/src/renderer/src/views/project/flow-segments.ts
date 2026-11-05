// 流转覆盖层的分段（工单 #379，来自 #366 的审查）：楼层画面的「流转」覆盖层把 project.flow 的行
// 聚成段，一段一条路径，段落上的「N 次」标签落在这条路径的中点。
// 分组键只含起点、终点与是否返工：同一对部门的全部非返工行并入同一段，否则同一条路径上的
// 多个标签互相遮挡（原型 v10 js/ui/scenes.js 的 overlayData）。
//
// 返工按流转种类「问题反馈」判断（工单 #866）：质检提交缺陷记录让工程返工，这一类流转就是
// 返工那条（设计说明 department-loop 第 2 节）。阶段状态机删掉以后（工单 #556）流转种类只剩
// 版本交付、询问与问题反馈三种，没有单独的「返工」种类。

import type { FlowRecord } from "../../api/generated/types.gen";

/** 返工那条流转的种类：质检提交缺陷记录，质检→工程。 */
const REWORK_KIND = "问题反馈";

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
    const rework = record.kind === REWORK_KIND;
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
