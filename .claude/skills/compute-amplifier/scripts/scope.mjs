import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export const protectedPaths = [
  'AGENTS.md', 'CLAUDE.md', '.github/', '.claude/', 'docs/agents/',
  'docs/architecture.html', 'docs/foundation-rules.md', 'docs/trial/',
  'harness/definitions/kernel-manifest.json', 'harness/tests/kernel/',
  'evals/', 'scripts/release.py', 'harness/release_check.py',
];

const evaluationPaths = ['evals/scorer/', 'evals/scenarios/', 'docs/trial/'];
const evaluationBaselines = ['harness/tests/kernel/', 'harness/tests/event_sequences/', 'harness/tests/prompt_snapshot.json'];

export function within(path, prefix) {
  return prefix.endsWith('/') ? path.startsWith(prefix) : path === prefix;
}

// 普通 JSON 数据只能增加对象字段，旧值与数组完整保留。
// schema 的语义由独立兼容检查核对，不把 JSON 包含关系当成 OpenAPI 兼容性。
export function additive(before, after) {
  if (before === null || typeof before !== 'object') return before === after;
  if (Array.isArray(before)) return JSON.stringify(before) === JSON.stringify(after);
  return after !== null && typeof after === 'object' && !Array.isArray(after)
    && Object.entries(before).every(([key, value]) => Object.hasOwn(after, key) && additive(value, after[key]));
}

export function approved(events, approvers, createdAt) {
  const labels = events.filter(e => ['labeled', 'unlabeled'].includes(e.event) && e.label?.name === 'kernel-approved');
  const latest = labels.at(-1);
  return latest?.event === 'labeled' && approvers.includes(latest.actor?.login)
    && Number.isFinite(Date.parse(latest.created_at)) && Date.parse(latest.created_at) <= Date.parse(createdAt);
}

export function checkScope({ changes, policy, kernelPaths, events = [], createdAt, readBefore, readAfter }) {
  if (!Array.isArray(policy.allowed) || !policy.allowed.length || !Array.isArray(policy.middle) || !Array.isArray(policy.approvers)) throw new Error('可信策略不完整');
  const errors = [];
  for (const { status, path } of changes) {
    if (evaluationPaths.some(prefix => within(path, prefix)) || (status !== 'A' && evaluationBaselines.some(prefix => within(path, prefix)))) errors.push(`候选不能修改评价材料: ${path}`);
    if (!policy.allowed.some(prefix => within(path, prefix))) errors.push(`超出只改清单: ${path}`);
    const inner = [...protectedPaths, ...kernelPaths, ...(policy.kernelApprovedPaths ?? [])].some(prefix => within(path, prefix));
    if (inner && (!policy.kernelApprovedPaths?.includes(path) || !approved(events, policy.approvers, createdAt))) errors.push(`缺少事前内核授权: ${path}`);
    if (policy.middle.some(prefix => within(path, prefix))) {
      if (status === 'D') errors.push(`删除合同: ${path}`);
      else if (status !== 'A') {
        if (policy.mode !== 'wrap') errors.push(`实现阶段修改冻结合同: ${path}`);
        else if (!path.endsWith('.json') || !additive(JSON.parse(readBefore(path)), JSON.parse(readAfter(path)))) errors.push(`合同旧内容发生变化: ${path}`);
      }
    }
  }
  return errors;
}

export function gitChanges(repo, base, head) {
  const git = (...args) => execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
  for (const ref of [base, head]) if (!/^[a-f0-9]{40}$/.test(ref)) throw new Error('需要完整 Git 提交');
  const tokens = git('diff', '--no-renames', '--name-status', '-z', base, head).split('\0');
  const changes = [];
  for (let i = 0; i < tokens.length - 1; i += 2) changes.push({ status: tokens[i], path: tokens[i + 1] });
  return { changes, readBefore: p => git('show', `${base}:${p}`), readAfter: p => git('show', `${head}:${p}`) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [repo, base, head, policyFile, eventsFile, createdAt] = process.argv.slice(2);
  const diff = gitChanges(repo, base, head);
  const manifest = JSON.parse(execFileSync('git', ['-C', repo, 'show', `${base}:harness/definitions/kernel-manifest.json`], { encoding: 'utf8' }));
  const policy = JSON.parse(readFileSync(policyFile, 'utf8'));
  const errors = checkScope({ ...diff, policy, kernelPaths: manifest.paths.map(p => p.path), events: JSON.parse(readFileSync(eventsFile, 'utf8')).flat(), createdAt });
  process.stdout.write(JSON.stringify({ base, head, files: diff.changes, errors }, null, 2) + '\n');
  if (errors.length) process.exitCode = 1;
}
