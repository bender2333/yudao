import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, validateConfig, startRound, suspend, recordSolo, recordTrial, recordArchitect } from '../state.mjs';

const completed = { status: 'completed', issues: [{ number: 123, status: 'passed' }] };
const fixed = { status: 'ready', issues: [124], unresolved: [] };

test('R1：第三轮失败后停止，不会启动第四轮或继续拆单', () => {
  let state = initialState('identity');
  for (let n = 1; n <= 3; n++) {
    state = startRound(state);
    assert.equal(state.rounds, n);
    state = recordSolo(state, completed);
    state = recordTrial(state, { status: 'failed' });
    if (n < 3) state = recordArchitect(state, fixed);
  }
  assert.equal(state.status, 'ready-for-human');
  assert.equal(state.notificationPending, true);
  assert.throws(() => startRound(state));
  assert.throws(() => recordArchitect(state, fixed));
});

test('R1：同单失败跨序列化连续累计，第三次立即停止', () => {
  let state = initialState('identity');
  for (let n = 1; n <= 3; n++) {
    state = startRound(JSON.parse(JSON.stringify(state)));
    state = recordSolo(state, { status: 'failed', issues: [{ number: 123, status: 'failed' }] });
    assert.equal(state.failures[123], n);
    if (n < 3) state = recordArchitect(state, fixed);
  }
  assert.match(state.reason, /同一工单/);
  assert.equal(state.status, 'ready-for-human');
});

test('R1：成功清零连续失败，未尝试的工单保留计数', () => {
  let state = { ...initialState('identity'), failures: { 123: 2, 124: 1 } };
  state = recordSolo(startRound(state), completed);
  assert.deepEqual(state.failures, { 123: 0, 124: 1 });
});

test('R1：执行环境受阻立即挂起并保留已花费轮次', () => {
  const state = recordSolo(startRound(initialState('identity')), { status: 'blocked', issues: [] });
  assert.equal(state.status, 'ready-for-human');
  assert.equal(state.rounds, 1);
});

test('R2：矛盾、重复和不完整的阶段结果均拒绝', () => {
  const state = startRound(initialState('identity'));
  assert.throws(() => recordSolo(state, { status: 'completed', issues: [{ number: 123, status: 'failed' }] }));
  assert.throws(() => recordSolo(state, { status: 'failed', issues: [{ number: 123, status: 'failed' }, { number: 123, status: 'failed' }] }));
  assert.throws(() => recordTrial(recordSolo(state, completed), { status: 'passed' }));
  assert.throws(() => recordArchitect(state, fixed));
});

test('R2：通过结论必须绑定精确提交与 wheel，没有未解决项', () => {
  const state = recordSolo(startRound(initialState('identity')), completed);
  const result = { status: 'passed', commit: 'a'.repeat(40), wheel_sha256: 'b'.repeat(64), unresolved: [] };
  assert.equal(recordTrial(state, result).status, 'passed');
  assert.throws(() => recordTrial(state, { ...result, unresolved: ['尚未验证恢复'] }));
});

test('R1：中断与挂起状态通过重新启动不能继续执行', () => {
  const state = suspend(startRound(initialState('identity')), '中断');
  assert.throws(() => startRound(JSON.parse(JSON.stringify(state))));
  assert.equal(state.rounds, 1);
});

test('R1：配置缺少硬预算、批准记录或执行器时不能启动', () => {
  const config = { worktrees: ['candidate'], approval: 'approval.json', budget: { totalTokens: 10000, planning: 0.3, implementation: 0.4, trial: 0.3 }, adapters: { preflight: {}, solo: {}, trial: {}, architect: {} } };
  assert.doesNotThrow(() => validateConfig(config));
  assert.throws(() => validateConfig({ ...config, budget: { ...config.budget, totalTokens: 0 } }));
  assert.throws(() => validateConfig({ ...config, approval: '' }));
  assert.throws(() => validateConfig({ ...config, adapters: {} }));
});
