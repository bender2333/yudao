// 待决决定（顶栏的数量）：重查按能力清单里 decisions.list 声明的事件种类（工单 #701）。
// 决定请求可能写在 run 流、项目流或目录流里（run 里的决定、接入已有项目时的初始 PRD 决定、
// 实例升级的决定），客户端写死三种会漏掉后两种：项目流里的决定回答以后顶栏的数字不更新，
// 页面上的两个数字对不上。
// 口径与视图同步一致：都取能力清单里这一条查询的 changed_by，服务端登记了什么就跟着什么。

/** 能力清单里与本文件有关的部分：查询的名称与它声明的事件种类。 */
export type QueryCapabilities = {
  queries: { name: string; changed_by: string[] }[];
};

/**
 * 会引起待决数量重查的事件种类：能力清单里 decisions.list 这一条查询声明的那些。
 * 能力清单里没有这一条查询时按空集处理（不重查），与视图同步的兜底一致。
 */
export function pendingDecisionEventTypes(capabilities: QueryCapabilities | null): Set<string> {
  const query = capabilities?.queries.find((item) => item.name === "decisions.list");
  return new Set(query?.changed_by ?? []);
}
