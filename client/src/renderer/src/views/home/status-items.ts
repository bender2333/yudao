// 状态项（原型 v8 设计说明第 4.1 节，工单 #175）：首页的一排与顶栏的亮起项共用一份数据。
// 正常时显示灰色的「无」，异常时亮起并显示数量，点击进入对应的页面。
// 本工单建立状态项的结构并实现「待你决定」一项；结果未知的动作数、离线的机器数、等待模型服务的 run 数、
// 磁盘可用空间与正在修复的故障数由所属工作包的界面工单按这里的结构加入。

export type StatusItem = {
  id: string;
  label: string;
  count: number | null;
  text: string | null;
  lit: boolean;
  href: string | null;
};

// 状态项的一排：「待你决定」的数量取自 decisions.list 中等待回答的数量，与托盘使用同一份数据
export function statusItems(pendingCount: number): StatusItem[] {
  return [
    {
      id: "decisions",
      label: "待你决定",
      count: pendingCount,
      text: null,
      lit: pendingCount > 0,
      href: "#/home",
    },
  ];
}
