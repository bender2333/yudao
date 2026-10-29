import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

// 输入由独立裁判生成，候选工人没有写权限。
export function select(candidates) {
  if (!Array.isArray(candidates) || candidates.length !== 3) throw new Error('需要三个候选结果');
  const bases = new Set(candidates.map(c => c.base));
  if (bases.size !== 1 || !/^[a-f0-9]{40}$/.test(candidates[0].base)) throw new Error('候选基准不一致');
  if (new Set(candidates.map(c => c.head)).size !== 3) throw new Error('候选提交必须不同');
  for (const c of candidates) {
    if (!/^[a-f0-9]{40}$/.test(c.head) || !Number.isSafeInteger(c.pr) || c.pr < 1) throw new Error('候选身份无效');
    if (!Number.isSafeInteger(c.changedLines) || c.changedLines < 0 || !Number.isFinite(c.complexity) || c.complexity < 0) throw new Error('缺少真实的行数或圈复杂度');
    if (typeof c.evidence !== 'string' || !c.evidence.trim()) throw new Error('缺少裁判证据');
    if (!Array.isArray(c.checks) || c.checks.length === 0) throw new Error('缺少必需检查');
    if (!['check', 'experiment-scope', 'independent-contract'].every(name => c.checks.some(x => x.name === name))) throw new Error('缺少 CI、范围或独立契约检查');
    if (!Array.isArray(c.outOfScope)) throw new Error('缺少只改清单检查');
  }
  const eligible = candidates.filter(c => c.outOfScope.length === 0 && c.checks.every(x => x.head === c.head && x.conclusion === 'SUCCESS'));
  eligible.sort((a, b) => a.changedLines - b.changedLines || a.complexity - b.complexity || a.head.localeCompare(b.head));
  return { winner: eligible[0] ?? null, eligible: eligible.map(c => c.head), rejected: candidates.filter(c => !eligible.includes(c)).map(c => c.head) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = select(JSON.parse(readFileSync(process.argv[2], 'utf8')));
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  if (!result.winner) process.exitCode = 2;
}
