/** 流程标签：同一时刻只带一个。流转时先全部摘掉，再加新的那个。 */
export const FLOW_LABELS = [
  'ready-for-agent',
  'in-progress',
  'needs-review',
  'needs-triage',
  'waiting',
  'ready-for-human',
];

/** 表示「这张单现在不派」的标签。in-progress / needs-review 不在这里：
 * 属于谁由 assignee 判断，见 solo.mjs 的 refresh。 */
export const PARKED_LABELS = ['needs-triage', 'waiting', 'ready-for-human'];

export const DEFAULT_BRANCH_PREFIX = 'issue-';

/**
 * 要摘掉的标签：当前挂着的流程标签里，除目标标签以外的那些。
 * 非流程标签（touches-core、bug 等）不在名单里，永远不动。
 */
export function labelsToDrop(present, target) {
  const has = Array.isArray(present) ? present : [];
  return FLOW_LABELS.filter((l) => has.includes(l) && l !== target);
}

/** 分支名：前缀来自台账的 worktrees.branchPrefix，没配就用 issue-。 */
export function branchFor(prefix, key) {
  const head = typeof prefix === 'string' && prefix.trim() ? prefix.trim() : DEFAULT_BRANCH_PREFIX;
  return head + String(key);
}
