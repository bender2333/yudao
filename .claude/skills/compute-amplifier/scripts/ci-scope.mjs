import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { checkScope, gitChanges } from './scope.mjs';

const branch = process.env.PR_BRANCH;
if (!branch) throw new Error('缺少 PR 身份');
if (!branch.startsWith('experiment/')) {
  process.stdout.write('普通开发范围，实验护栏不适用。\n');
} else {
  const match = /^experiment\/([a-z0-9]+(?:-[a-z0-9]+)*)\/([1-9][0-9]*)-(a|b|c|wrap)$/.exec(branch);
  if (!match) throw new Error('实验分支名称无效');
  const [, stage, issue] = match;
  const registry = JSON.parse(readFileSync(`.claude/skills/compute-amplifier/policies/${stage}.json`, 'utf8'));
  if (registry.stage !== stage || !registry.issues?.[issue]) throw new Error('基线没有该工单的批准策略');
  const repository = process.env.GITHUB_REPOSITORY;
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository)) throw new Error('仓库身份无效');
  for (const key of ['PR_BASE', 'PR_HEAD']) if (!/^[a-f0-9]{40}$/.test(process.env[key])) throw new Error('提交身份无效');
  if (!/^[1-9][0-9]*$/.test(process.env.PR_NUMBER)) throw new Error('PR 编号无效');
  const gh = (...args) => execFileSync('gh', args, { encoding: 'utf8', timeout: 60000, maxBuffer: 16 * 1024 * 1024 });
  const events = JSON.parse(gh('api', '--paginate', '--slurp', `repos/${repository}/issues/${issue}/events`)).flat();
  // gh 通过自己的凭据读取 PR；git remote 不保存令牌。
  const auth = Buffer.from(`x-access-token:${process.env.GH_TOKEN}`).toString('base64');
  execFileSync('git', ['fetch', '--no-tags', 'origin', `pull/${process.env.PR_NUMBER}/head`], {
    stdio: 'pipe', timeout: 60000,
    env: { ...process.env, GIT_CONFIG_COUNT: '1', GIT_CONFIG_KEY_0: 'http.extraheader', GIT_CONFIG_VALUE_0: `AUTHORIZATION: basic ${auth}` },
  });
  const manifest = JSON.parse(readFileSync('harness/definitions/kernel-manifest.json', 'utf8'));
  const policy = { ...registry.issues[issue], approvers: registry.approvers };
  const errors = checkScope({ ...gitChanges('.', process.env.PR_BASE, process.env.PR_HEAD), policy, kernelPaths: manifest.paths.map(p => p.path), events, createdAt: process.env.PR_CREATED });
  process.stdout.write(JSON.stringify({ stage, issue, base: process.env.PR_BASE, head: process.env.PR_HEAD, errors }, null, 2) + '\n');
  if (errors.length) process.exitCode = 1;
}
