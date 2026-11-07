#!/usr/bin/env node
/** 放回到期的 waiting 工单、把来回满两次的交给用户。node release.mjs [--dry-run] [--milestone X ...] */
import { fileURLToPath } from 'node:url';
import { gh } from './lib/proc.mjs';
import { milestonesFromArgs } from './lib/config.mjs';
import { scan } from './scan.mjs';

const SIGN = '— 架构师循环（脚本）';

export const releaseBody = (due) =>
  `WAITING: 已放回\n\n日期已到（${due.date}）。到期以后第一件要核对的事见上一条 WAITING: 评论。\n\n${SIGN}`;

export const handToUserBody = (h) =>
  `TRIAGE: 交给用户\n\n这张工单的 WAITING: 日期已到（${h.date}），但在 waiting 与 ready-for-agent 之间已经来回 ${h.count} 次，按工作方式第 7 节不再放回。\n要用户定：条件现在是否成立；不成立时还等什么、等到哪天，或者这张单是否还要做。\n\n${SIGN}`;

/** 改标签并留评论，返回做了什么；失败的记 error，不中断别的。 */
export function release(result, { dryRun = false, ghFn = gh } = {}) {
  const done = [];
  const act = (number, kind, add, body) => {
    const entry = { number, kind };
    if (!dryRun) {
      const e = ghFn(['issue', 'edit', String(number), '--remove-label', 'waiting', '--add-label', add]);
      const c = e.status === 0 ? ghFn(['issue', 'comment', String(number), '--body', body]) : e;
      if (e.status !== 0 || c.status !== 0) entry.error = (c.stderr || e.stderr || '').trim().slice(0, 200);
    }
    done.push(entry);
  };
  for (const d of result.due) act(d.number, 'released', 'ready-for-agent', releaseBody(d));
  for (const h of result.handToUser) act(h.number, 'handed-to-user', 'ready-for-human', handToUserBody(h));
  return done;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const dryRun = process.argv.includes('--dry-run');
  try {
    const done = release(scan(milestonesFromArgs(process.argv.slice(2))), { dryRun });
    console.log(JSON.stringify({ dryRun, done }, null, 2));
  } catch (e) {
    console.error(`release 失败：${e.message}`);
    process.exit(1);
  }
}
