import test from 'node:test';
import assert from 'node:assert/strict';
import { select } from '../select.mjs';

function candidates() {
  return [1, 2, 3].map(n => {
    const head = String(n).repeat(40);
    return { base: 'a'.repeat(40), head, pr: n, changedLines: 30 - n, complexity: n, outOfScope: [], evidence: 'judge/record',
      checks: ['check', 'experiment-scope', 'independent-contract'].map(name => ({ name, head, conclusion: 'SUCCESS' })) };
  });
}

test('R2：先验证合格条件，再按行数与复杂度排名', () => {
  const values = candidates();
  values[2].outOfScope = ['unauthorized.py'];
  assert.equal(select(values).winner.pr, 2);
  values[1].checks[0].conclusion = 'FAILURE';
  assert.equal(select(values).winner.pr, 1);
});

test('R2：待运行、跳过和过期提交的结果都不能入选', () => {
  const values = candidates();
  values[0].checks[0].conclusion = 'IN_PROGRESS';
  values[1].checks[0].conclusion = 'SKIPPED';
  values[2].checks[0].head = 'f'.repeat(40);
  assert.equal(select(values).winner, null);
});

test('R2：相同指标按完整提交号决定，输入顺序不影响结果', () => {
  const values = candidates().map(c => ({ ...c, changedLines: 20, complexity: 4 }));
  assert.equal(select(values).winner.head, select(values.toReversed()).winner.head);
  values[0].complexity = 5;
  assert.equal(select(values).winner.pr, 2);
});

test('R2：缺少独立契约、度量或共同基准时拒绝选择', () => {
  let values = candidates();
  values[0].checks.pop();
  assert.throws(() => select(values));
  values = candidates(); values[0].base = 'b'.repeat(40);
  assert.throws(() => select(values));
  values = candidates(); delete values[0].complexity;
  assert.throws(() => select(values));
  assert.throws(() => select([]));
});
