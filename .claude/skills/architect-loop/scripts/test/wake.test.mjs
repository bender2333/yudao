import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pickJudge, evidenceTargets, buildNext, nothingToDo, buildHeartbeat, acquireLock, releaseLock } from '../lib/wakelib.mjs';
import { resolveEnv } from '../lib/config.mjs';
import { release } from '../release.mjs';

const s = (o) => ({ verify: [], triage: [], unblocked: [], warnings: [], ...o });
const n = (...xs) => xs.map((number) => ({ number, title: `t${number}` }));
const ok = { exists: true, valid: true, needsRedo: false, mismatches: 0, problems: [] };

test('挑选先后：triage、unblocked、verify，同类编号小的先', () => {
  const r = s({ verify: n(1), unblocked: n(9), triage: n(30, 20) });
  assert.equal(pickJudge(r, new Set([1, 9, 20, 30])).number, 20);
  assert.equal(pickJudge(r, new Set([1, 9, 30])).number, 30);
  assert.equal(pickJudge(r, new Set([1, 9])).kind, 'unblocked');
  assert.equal(pickJudge(r, new Set([1])).kind, 'verify');
  assert.equal(pickJudge(r, new Set()), null);
});
test('取证对象：有效或已判过的跳过；没有证据包、过期、对不上要进，各带一句原因', () => {
  const r = s({ verify: n(1, 2, 3, 4), triage: n(5) });
  const checks = {
    1: ok,
    2: { exists: true, valid: false, needsRedo: false, judged: true, problems: ['已判'] },
    3: { exists: true, valid: false, needsRedo: true, problems: ['证据包过期：比最近一次变化早'] },
    4: { exists: false, valid: false, needsRedo: true, problems: ['没有证据包'] },
    5: { ...ok, needsRedo: true, mismatches: 2 },
  };
  const t = evidenceTargets(r, checks);
  assert.deepEqual(t.map((x) => x.number), [3, 4, 5]);
  assert.match(t[0].reason, /过期/); assert.match(t[1].reason, /没有证据包/); assert.match(t[2].reason, /2 行对不上/);
});
test('next.json：evidence、judge、released、warnings 都在；有效件里挑一件', () => {
  const r = s({ verify: n(1, 2), triage: n(5), warnings: [{ type: 'x' }] });
  const checks = { 1: ok, 2: { exists: false, valid: false, needsRedo: true, problems: ['没有证据包'] }, 5: ok };
  const next = buildNext(r, checks, { startedAt: 'a', mainSha: 'abc', released: [{ number: 7 }] });
  assert.deepEqual(next.evidence.map((e) => e.number), [2]);
  assert.deepEqual([next.judge.kind, next.judge.number], ['triage', 5]);
  assert.deepEqual(next.released, [{ number: 7 }]);
  assert.equal(next.warnings.length, 1);
  assert.equal(nothingToDo(next), false);
});
test('没事可做：evidence 与 judge 都空', () => {
  const next = buildNext(s({ verify: n(1) }), { 1: { exists: true, valid: false, needsRedo: false, judged: true, problems: [] } }, { startedAt: 'a', mainSha: 'abc' });
  assert.equal(nothingToDo(next), true);
  assert.equal(nothingToDo(buildNext(s(), {}, {})), true);
});
test('心跳：起止、main、放回、取证、判了哪件与结果、提醒', () => {
  const hb = buildHeartbeat({ startedAt: 'a', mainSha: 'abc', released: [{ number: 7 }], warnings: [1] }, { judged: 5, result: '放出', evidenced: [2] }, 'b');
  assert.deepEqual(hb, { startedAt: 'a', endedAt: 'b', mainSha: 'abc', released: [{ number: 7 }], evidence: [2], judged: { number: 5, result: '放出' }, warnings: [1], note: '' });
});
test('锁：活锁挡住，过期的接管；--finish 不给进程号时直接解锁，给了只删自己的', () => {
  const f = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'al-')), 'lock');
  const t0 = Date.parse('2026-11-07T00:00:00Z');
  assert.equal(acquireLock(f, { pid: 1, now: t0, lockMinutes: 60 }).ok, true);
  assert.equal(acquireLock(f, { pid: 2, now: t0 + 59 * 60000, lockMinutes: 60 }).ok, false);
  assert.equal(acquireLock(f, { pid: 2, now: t0 + 61 * 60000, lockMinutes: 60 }).ok, true);
  releaseLock(f, 1);
  assert.equal(fs.existsSync(f), true);
  releaseLock(f, 2);
  assert.equal(fs.existsSync(f), false);
  acquireLock(f, { pid: 3, now: t0, lockMinutes: 60 });
  releaseLock(f);
  assert.equal(fs.existsSync(f), false);
});
test('环境变量："$VAR" 取进程里的同名变量', () => {
  assert.deepEqual(resolveEnv({ A: '$X', B: 'lit', C: '$NOPE' }, { X: 'v' }), { A: 'v', B: 'lit', C: '' });
});
test('release：到期放回、满两次交用户；dry-run 不调 gh', () => {
  const calls = [];
  const ghFn = (a) => { calls.push(a); return { status: 0, stdout: '', stderr: '' }; };
  const res = { due: [{ number: 1, date: '2026-11-01' }], handToUser: [{ number: 2, date: '2026-11-01', count: 2 }] };
  assert.equal(release(res, { dryRun: true, ghFn }).length, 2);
  assert.equal(calls.length, 0);
  release(res, { ghFn });
  assert.deepEqual(calls[0], ['issue', 'edit', '1', '--remove-label', 'waiting', '--add-label', 'ready-for-agent']);
  assert.match(calls[1][4], /^WAITING: 已放回\n/);
  assert.equal(calls[2][6], 'ready-for-human');
  assert.match(calls[3][4], /^TRIAGE: 交给用户\n/);
});
