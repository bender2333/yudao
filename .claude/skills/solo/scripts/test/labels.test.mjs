import test from 'node:test';
import assert from 'node:assert/strict';
import { labelsToDrop, branchFor } from '../lib/labels.mjs';

test('补标签：目标标签占着，别的流程标签全摘掉', () => {
  assert.deepEqual(
    labelsToDrop(['in-progress', 'needs-review', 'ready-for-agent'], 'in-progress'),
    ['ready-for-agent', 'needs-review'],
  );
});

test('补标签：非流程标签（touches-core、bug）不摘', () => {
  assert.deepEqual(labelsToDrop(['touches-core', 'bug', 'needs-triage'], 'in-progress'), ['needs-triage']);
});

test('补标签：目标标签已经在时既不重复加也不在摘除名单里', () => {
  assert.deepEqual(labelsToDrop(['needs-review', 'ready-for-agent'], 'needs-review'), ['ready-for-agent']);
});

test('补标签：只挂非流程标签时什么也不摘', () => {
  assert.deepEqual(labelsToDrop(['bug', 'enhancement'], 'needs-review'), []);
  assert.deepEqual(labelsToDrop(undefined, 'needs-review'), []);
});

test('分支名：没配前缀时用 issue-', () => {
  assert.equal(branchFor('', 561), 'issue-561');
  assert.equal(branchFor(undefined, 561), 'issue-561');
});

test('分支名：前缀取自台账的 branchPrefix，改前缀分支名跟着变', () => {
  assert.equal(branchFor('solo-', 561), 'solo-561');
  assert.equal(branchFor('feat/issue-', 87), 'feat/issue-87');
});

test('分支名：没有工单号时用任务号', () => {
  assert.equal(branchFor(undefined, 'T-004'), 'issue-T-004');
});
