import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const SOLO = path.join(import.meta.dirname, '..', 'solo.mjs');

/**
 * 临时账本：完成的单子留着旧标记，没完成的也留着同样的标记。
 * 滤不掉（完成的还印出来）与滤过头（真的等用户的单子也不印）都能被这份账本看出来。
 * 真实账本在 .ralph/ 下，是编排者的账本，测试不碰它。
 */
function tempLedger() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'solo-state-output-'));
  const dir = path.join(root, '.ralph', 'stage1');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(root, '.ralph', 'active.json'), JSON.stringify({ loop: 'stage1' }), 'utf8');
  fs.writeFileSync(path.join(dir, 'state.json'), JSON.stringify({
    loop: 'stage1',
    status: 'running',
    iteration: 11,
    maxIterations: 120,
    autoContinue: true,
    waitMode: 'hook',
    concurrency: { max: 4, exclusiveLimit: 1, active: [] },
    taskState: {
      'T-008': { waitFor: 'user' },
      'T-031': { fails: 1 },
      'T-012': { waitFor: 'user' },
      'T-013': { fails: 2 },
    },
  }, null, 2), 'utf8');
  fs.writeFileSync(path.join(dir, 'tasks.md'), [
    '- [x] T-008 #871 用户已决定取消（wontfix）',
    '- [x] T-031 #952 早已完成',
    '- [ ] T-012 #957 还没做完，在等用户回话',
    '- [ ] T-013 #958 还没做完',
    '',
  ].join('\n'), 'utf8');
  return root;
}

/** 临时账本用完删掉；删不掉也不该让用例失败。 */
function cleanup(root) {
  try {
    fs.rmSync(root, { recursive: true, force: true });
  } catch {
    /* 临时目录留在系统临时区，不影响仓库 */
  }
}

const run = (root, args) => {
  const r = spawnSync(process.execPath, [SOLO].concat(args, ['--workspace', root, '--loop', 'stage1']), { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  return r.stdout;
};

const lineOf = (text, prefix) => text.split(/\r?\n/).find((l) => l.startsWith(prefix)) || '';

test('state 文本：完成的单子不再印进「等用户」与「失败中」，没完成的照旧印', (t) => {
  const root = tempLedger();
  t.after(() => cleanup(root));
  const out = run(root, ['state']);
  assert.equal(lineOf(out, '等用户:'), '等用户: T-012', '完成的 T-008 不能印出来，没完成的 T-012 要印');
  assert.equal(lineOf(out, '失败中:'), '失败中: T-013x2', '完成的 T-031 不能印出来，没完成的 T-013 要印');
});

test('state --json：forUser 与 failing 跟文本输出一个口径', (t) => {
  const root = tempLedger();
  t.after(() => cleanup(root));
  const json = JSON.parse(run(root, ['state', '--json']));
  assert.deepEqual(json.forUser, ['T-012']);
  assert.deepEqual(json.failing, ['T-013x2']);
});

test('summary：等用户的清单里没有完成的单子，没完成的照旧在', (t) => {
  const root = tempLedger();
  t.after(() => cleanup(root));
  assert.equal(lineOf(run(root, ['summary']), '等用户：'), '等用户：T-012');
  assert.deepEqual(JSON.parse(run(root, ['summary', '--json'])).forUser, ['T-012']);
});

test('state 与 summary：台账里没有等用户的单子时，两处都不印那一行', (t) => {
  const root = tempLedger();
  t.after(() => cleanup(root));
  const stateFile = path.join(root, '.ralph', 'stage1', 'state.json');
  const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  state.taskState = { 'T-013': { fails: 1 } };
  fs.writeFileSync(stateFile, JSON.stringify(state, null, 2), 'utf8');

  assert.equal(lineOf(run(root, ['state']), '等用户:'), '');
  assert.equal(lineOf(run(root, ['summary']), '等用户：'), '');
});
