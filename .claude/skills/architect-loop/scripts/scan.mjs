#!/usr/bin/env node
/** 扫状态：读范围内的打开工单，按规则分类，输出 JSON。 */
import { fileURLToPath } from 'node:url';
import { fetchOpenIssues, fetchComments, fetchMeta } from './lib/github.mjs';
import { classify, needsComments, triageMentions } from './lib/classify.mjs';
import { localDate } from './lib/proc.mjs';
import { milestonesFromArgs } from './lib/config.mjs';

export function scan(scope, today = localDate()) {
  if (!scope.length) throw new Error('没有范围：用 --milestone <标题或编号>，或在配置的 scope.milestones 里写');
  const issues = fetchOpenIssues();
  for (const i of issues) if (needsComments(i, scope)) i.comments = fetchComments(i.number);
  const refs = {};
  for (const i of issues) {
    if (!i.comments || !i.labels.includes('ready-for-human')) continue;
    for (const n of triageMentions(i)) {
      if (refs[n]) continue;
      try { refs[n] = fetchMeta(n); } catch { /* 点名的不是工单 */ }
    }
  }
  return { generatedAt: new Date().toISOString(), today, scope, ...classify(issues, { today, scope, refs }) };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    console.log(JSON.stringify(scan(milestonesFromArgs(process.argv.slice(2))), null, 2));
  } catch (e) {
    console.error(`scan 失败：${e.message}`);
    process.exit(1);
  }
}
