// 状态项（原型 v8 设计说明第 4.1 节，原型 v9 的 ui/shell.js 的 statusItems，工单 #175、#378）：
// 首页的一排与顶栏的亮起项共用一份数据。正常时显示灰色的「无」，异常时亮起并显示数量，
// 点击进入对应的页面。每一项只在有数据来源时出现：来源的字段还没有加入 system.status 时
// （离线的机器、等待模型服务、正在修复的故障、磁盘空间的提示阈值），这一项不显示，不写成零。

import type { DecisionView, SystemStatus } from "../../api/generated/types.gen";

export type StatusItem = {
  id: string;
  label: string;
  icon: string;
  count: number | null;
  text: string | null;
  lit: boolean;
  href: string | null;
  // 点开以后滚到哪一个区块：页面上的区块标识（原型 shell.js 的 anchor）
  anchor: string | null;
};

// 状态项的一排（设计说明第 4.1 节的表格）：
// 「待你决定」的数量取自 decisions.list 中等待回答的数量，与托盘使用同一份数据；
// 「结果未知的动作」的个数取自 system.status 的恢复汇总，点击打开第一个这类动作所属事项的恢复页
export function statusItems(status: SystemStatus | null, decisions: DecisionView[]): StatusItem[] {
  const items: StatusItem[] = [
    {
      id: "decisions",
      label: "待你决定",
      icon: "decide",
      count: decisions.length,
      text: null,
      lit: decisions.length > 0,
      href: "#/home",
      anchor: "home-decisions",
    },
  ];
  if (status === null) {
    return items;
  }
  const unknown = status.recovery.unknown_actions;
  if (unknown > 0) {
    items.push({
      id: "unknown_actions",
      label: "结果未知的动作",
      icon: "unknown",
      count: unknown,
      text: null,
      lit: true,
      href: recoveryPath(decisions),
      anchor: null,
    });
  }
  return items;
}

// 第一个结果未知的动作所属事项的恢复页：system.status 只给出汇总数量，
// 具体位置由等待中的决定请求解析；解析不到时状态项亮起但不可点击
function recoveryPath(decisions: DecisionView[]): string | null {
  const first = decisions.find((decision) => decision.kind === "unknown_action");
  if (first === undefined || first.project_id === null) {
    return null;
  }
  return first.work_item_id === null
    ? `#/p/${first.project_id}/overview`
    : `#/p/${first.project_id}/w/${first.work_item_id}/recovery`;
}
