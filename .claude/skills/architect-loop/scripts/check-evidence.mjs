#!/usr/bin/env node
/** 核对一张工单最后一条 EVIDENCE: 评论：node check-evidence.mjs <工单号> [--json] */
import { fileURLToPath } from 'node:url';
import { fetchComments, fetchIssue, fetchMeta } from './lib/github.mjs';
import { checkComments } from './lib/evidence.mjs';
import { lastChildClosedAt, lastWith } from './lib/classify.mjs';
import { makeDeps } from './lib/gitdeps.mjs';

/** 读 GitHub 与 git，返回核对结果（含工单号）。 */
export function checkIssue(number, cwd = process.cwd(), deps = makeDeps(cwd)) {
  const comments = fetchComments(number);
  const ctx = {};
  const issue = fetchIssue(number);
  if (issue.labels.includes('parent') && issue.subIssues.length) ctx.lastChildClosedAt = lastChildClosedAt(issue);
  const t = lastWith(comments, 'TRIAGE:');
  if (t && issue.labels.includes('ready-for-human')) {
    for (const m of t.body.matchAll(/#(\d+)/g)) {
      try {
        const ref = fetchMeta(Number(m[1]));
        if (ref.state === 'CLOSED' && ref.labels.includes('architecture')) { ctx.notBefore = ref.closedAt; break; }
      } catch { /* 不是工单 */ }
    }
  }
  return { issue: number, ...checkComments(comments, ctx, deps) };
}

export function format(r) {
  const out = [`#${r.issue} 证据包：${!r.exists ? '没有' : `${r.kind} @ ${r.head}${r.redo ? '（重做）' : ''}`}  有效=${r.valid}  过期=${r.stale}  对不上=${r.mismatches}  未核对=${r.unchecked}`];
  for (const p of r.problems) out.push(`  问题：${p}`);
  for (const i of r.items) out.push(`  [${i.status}] ${i.entry} | ${i.type}: ${i.value}${i.note ? `（${i.note}）` : ''}`);
  return out.join('\n');
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const n = Number(process.argv[2]);
  if (!Number.isInteger(n)) { console.error('用法：check-evidence.mjs <工单号> [--json]'); process.exit(2); }
  try {
    const r = checkIssue(n);
    console.log(process.argv.includes('--json') ? JSON.stringify(r, null, 2) : format(r));
    process.exit(r.valid ? 0 : 1);
  } catch (e) {
    console.error(`check-evidence 失败：${e.message}`);
    process.exit(2);
  }
}
