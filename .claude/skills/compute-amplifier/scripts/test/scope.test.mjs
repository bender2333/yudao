import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { additive, approved, checkScope, gitChanges } from '../scope.mjs';

test('R2：字段增加保留旧值，删除、类型变化和数组变化拒绝', () => {
  const before = { entry: { status: 'ready' }, enum: ['a'] };
  assert.equal(additive(before, { ...before, version: 2 }), true);
  assert.equal(additive(before, { enum: ['a'] }), false);
  assert.equal(additive(before, { ...before, enum: ['a', 'b'] }), false);
  assert.equal(additive(before, { ...before, entry: null }), false);
});

test('R1：内核加标要求可信批准者、事前时间和当前有效授权', () => {
  const event = { event: 'labeled', label: { name: 'kernel-approved' }, actor: { login: 'owner' }, created_at: '2026-10-29T00:00:00Z' };
  const created = '2026-10-30T00:00:00Z';
  assert.equal(approved([event], ['owner'], created), true);
  assert.equal(approved([event], ['worker'], created), false);
  assert.equal(approved([event], ['owner'], '2026-10-28T00:00:00Z'), false);
  assert.equal(approved([event, { ...event, event: 'unlabeled' }], ['owner'], created), false);
});

test('R1：只改清单、内核路径与冻结合同独立阻止越界', () => {
  const input = {
    changes: [{ status: 'M', path: 'harness/core.py' }, { status: 'M', path: 'contract.json' }, { status: 'A', path: 'outside.py' }],
    policy: { mode: 'implementation', allowed: ['harness/', 'contract.json'], middle: ['contract.json'], approvers: ['owner'], kernelApprovedPaths: [] },
    kernelPaths: ['harness/core.py'], readBefore: () => '{}', readAfter: () => '{}',
  };
  const errors = checkScope(input);
  assert.equal(errors.length, 3);
  assert.ok(errors.some(e => e.includes('内核')));
  assert.ok(errors.some(e => e.includes('冻结合同')));
  assert.ok(errors.some(e => e.includes('只改')));
});

test('R1：规则与评分器即使在只改清单内也需要精确的事前授权', () => {
  const input = { changes: [{ status: 'M', path: '.claude/skills/solo/SKILL.md' }],
    policy: { allowed: ['.claude/'], middle: [], approvers: ['owner'], kernelApprovedPaths: [] }, kernelPaths: [] };
  assert.equal(checkScope(input).length, 1);
  input.policy.kernelApprovedPaths = ['.claude/skills/solo/SKILL.md'];
  input.events = [{ event: 'labeled', label: { name: 'kernel-approved' }, actor: { login: 'owner' }, created_at: '2026-10-29T00:00:00Z' }];
  input.createdAt = '2026-10-30T00:00:00Z';
  assert.deepEqual(checkScope(input), []);
  input.changes = [{ status: 'A', path: 'harness/new_kernel.py' }];
  input.policy.allowed = ['harness/new_kernel.py'];
  input.policy.kernelApprovedPaths = ['harness/new_kernel.py'];
  input.events = [];
  assert.ok(checkScope(input).some(e => e.includes('内核授权')));
});

test('R2：WRAP 可以新增签名文件，旧签名、合同删除与目录相似名称均受阻', () => {
  const policy = { mode: 'wrap', allowed: ['contracts/'], middle: ['contracts/'], approvers: [] };
  assert.deepEqual(checkScope({ changes: [{ status: 'A', path: 'contracts/new.ts' }], policy, kernelPaths: [] }), []);
  assert.equal(checkScope({ changes: [{ status: 'M', path: 'contracts/old.ts' }], policy, kernelPaths: [] }).length, 1);
  assert.equal(checkScope({ changes: [{ status: 'D', path: 'contracts/old.ts' }], policy, kernelPaths: [] }).length, 1);
  assert.equal(checkScope({ changes: [{ status: 'A', path: 'contracts-other/new.ts' }], policy, kernelPaths: [] }).length, 1);
});

test('R1：内核授权不能使实现候选取得修改评价材料的权限', () => {
  const path = 'evals/scorer/scorer.py';
  const errors = checkScope({ changes: [{ status: 'M', path }], kernelPaths: [],
    policy: { allowed: [path], middle: [], approvers: ['owner'], kernelApprovedPaths: [path] },
    events: [{ event: 'labeled', label: { name: 'kernel-approved' }, actor: { login: 'owner' }, created_at: '2026-10-29T00:00:00Z' }], createdAt: '2026-10-30T00:00:00Z' });
  assert.ok(errors.some(e => e.includes('评价材料')));
});

test('测试基础设施：真实 Git 差异读取中文、空格和重命名两侧路径', () => {
  const folder = mkdtempSync(join(tmpdir(), 'yudao-scope-'));
  const git = (...args) => execFileSync('git', ['-C', folder, ...args], { encoding: 'utf8' }).trim();
  try {
    git('init', '--quiet'); git('config', 'user.name', 'scope-test'); git('config', 'user.email', 'scope-test@yudao.invalid');
    writeFileSync(join(folder, '合同 中文.json'), '{"value":1}');
    git('add', '.'); git('commit', '--quiet', '-m', 'base');
    const base = git('rev-parse', 'HEAD');
    git('mv', '合同 中文.json', 'new contract.json');
    git('commit', '--quiet', '-m', 'rename');
    const head = git('rev-parse', 'HEAD');
    const diff = gitChanges(folder, base, head);
    assert.ok(diff.changes.some(c => c.status === 'D' && c.path === '合同 中文.json'));
    assert.ok(diff.changes.some(c => c.status === 'A' && c.path === 'new contract.json'));
    assert.deepEqual(JSON.parse(diff.readBefore('合同 中文.json')), { value: 1 });
    assert.deepEqual(JSON.parse(diff.readAfter('new contract.json')), { value: 1 });
  } finally { rmSync(folder, { recursive: true, force: true }); }
});
