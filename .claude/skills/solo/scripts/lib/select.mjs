import { PARKED_LABELS } from './labels.mjs';

/** 范围标记：离开范围时追加在任务行尾。 */
const OUT_OF_SCOPE = '不在范围';

/**
 * 阻塞方里还开着的那些编号。只有明确 CLOSED 才算不挡：
 * 外部返回里缺 state 字段（拉不全、字段改名）时按还开着算，宁可少派一张。
 */
export function openBlockers(blockedBy) {
  const list = Array.isArray(blockedBy) ? blockedBy : [];
  return list
    .filter((b) => b && String(b.state || '').toUpperCase() !== 'CLOSED')
    .map((b) => b.number);
}

/**
 * 这张任务现在能不能派。
 * ctx = { activeIds, taskState, doneIds, issue }：issue 是这一次拉到的外部工单
 * （没有这张单时传 null）。
 */
export function isSelectable(task, ctx) {
  const { activeIds, taskState, doneIds, issue } = ctx || {};
  if (!task || task.status !== 'pending') return false;
  if (activeIds && activeIds.has(task.id)) return false;
  if (String(task.text || '').includes(OUT_OF_SCOPE)) return false;
  const entry = (taskState && taskState[task.id]) || {};
  if (entry.escalated) return false;
  if (entry.external) return false;
  if (!issue) return false;
  if ((issue.labels || []).some((l) => PARKED_LABELS.includes(l))) return false;
  if (openBlockers(issue.blockedBy).length) return false;
  const done = doneIds || new Set();
  return (task.after || []).every((id) => done.has(id));
}

/**
 * 按顺序挑活：取到 max 张为止，同一个 issue 只取一张，
 * 互斥的行占 exclusiveLimit 个名额，名额用完只跳过互斥的、非互斥照取。
 */
export function pickUpTo(candidates, opts) {
  const { max, exclusiveLimit, takenIssues } = opts || {};
  const picked = [];
  const taken = new Set(takenIssues || []);
  let exclusiveUsed = 0;
  for (const t of candidates || []) {
    if (picked.length >= max) break;
    if (t.issue && taken.has(t.issue)) continue;
    if (t.exclusive) {
      if (exclusiveUsed >= exclusiveLimit) continue;
      exclusiveUsed += 1;
    }
    if (t.issue) taken.add(t.issue);
    picked.push(t);
  }
  return picked;
}
