import test from 'node:test';
import assert from 'node:assert/strict';
import { checkRollup, checkLabels } from '../lib/check-rules.mjs';

test('收账核对：全部 SUCCESS / NEUTRAL / SKIPPED 才算全绿', () => {
  const rollup = checkRollup([
    { name: 'check', conclusion: 'SUCCESS' },
    { name: 'lint', conclusion: 'NEUTRAL' },
    { name: 'docs', conclusion: 'SKIPPED' },
  ]);
  assert.equal(rollup.green, true);
  assert.equal(rollup.total, 3);
  assert.deepEqual(rollup.bad, []);
});

test('收账核对：有一条没通过就不算全绿，并指出是哪一条', () => {
  const rollup = checkRollup([
    { name: 'check', conclusion: 'SUCCESS' },
    { name: 'integration', conclusion: 'FAILURE' },
  ]);
  assert.equal(rollup.green, false);
  assert.deepEqual(rollup.bad.map((c) => c.conclusion), ['FAILURE']);
  assert.equal(checkLabels(rollup.bad), 'integration:FAILURE');
});

test('收账核对：一条检查结果都没有时不算全绿（看不到结果就是没证据）', () => {
  assert.equal(checkRollup([]).green, false);
  assert.equal(checkRollup(undefined).green, false);
});

test('收账核对：还在跑、没有 conclusion 的检查项不算数，也不拖累判绿', () => {
  const rollup = checkRollup([
    { name: 'check', conclusion: 'SUCCESS' },
    { name: 'integration', status: 'IN_PROGRESS' },
  ]);
  assert.equal(rollup.total, 1);
  assert.equal(rollup.green, true);
});

test('收账核对：没写名字的检查项在提示里也有个称呼', () => {
  assert.equal(checkLabels([{ context: 'ci/build', conclusion: 'CANCELLED' }]), 'ci/build:CANCELLED');
  assert.equal(checkLabels([{ conclusion: 'TIMED_OUT' }]), '检查:TIMED_OUT');
});
