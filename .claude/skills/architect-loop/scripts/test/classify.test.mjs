import test from 'node:test';
import assert from 'node:assert/strict';
import { classify, parseWaitingDate } from '../lib/classify.mjs';

const scope = ['M'];
const issue = (o) => ({ number: 1, title: 't', milestone: 'M', milestoneNumber: 8, labels: [], blockedBy: [], subIssues: [], comments: [], ...o });
const c = (body, createdAt = '2026-11-01T00:00:00Z') => ({ body, createdAt, author: 'x' });
const sub = (n, closedAt, state = 'CLOSED') => ({ number: n, state, closedAt });
const run = (issues, refs) => classify(issues, { today: '2026-11-07', scope, refs });

test('验收：子工单全关、没有 VERDICT 才进', () => {
  const p = issue({ number: 10, labels: ['parent'], subIssues: [sub(11, '2026-11-02T00:00:00Z'), sub(12, '2026-11-03T00:00:00Z')] });
  assert.deepEqual(run([p]).verify.map((x) => x.number), [10]);
  assert.equal(run([p]).verify[0].lastChildClosedAt, '2026-11-03T00:00:00Z');
});
test('验收：还有打开的子工单、没有子工单、工作线跟踪都不进', () => {
  const open = issue({ labels: ['parent'], subIssues: [sub(11, '2026-11-02T00:00:00Z'), sub(12, null, 'OPEN')] });
  const none = issue({ number: 2, labels: ['parent'] });
  const track = issue({ number: 3, title: '[x] 工作线跟踪', labels: ['parent'], subIssues: [sub(13, '2026-11-02T00:00:00Z')] });
  assert.equal(run([open, none, track]).verify.length, 0);
});
test('验收：VERDICT 早于最后一张子工单关闭仍进，晚于则不进', () => {
  const mk = (t) => issue({ labels: ['parent'], subIssues: [sub(11, '2026-11-03T00:00:00Z')], comments: [c('VERDICT: 1 条没过 @ abc', t)] });
  assert.equal(run([mk('2026-11-02T00:00:00Z')]).verify.length, 1);
  assert.equal(run([mk('2026-11-04T00:00:00Z')]).verify.length, 0);
});
test('分诊：needs-triage 进；最近一条交回类评论是 TRIAGE 的变提醒', () => {
  const a = issue({ number: 5, labels: ['needs-triage'], comments: [c('ARCHITECT: 卡住了')] });
  const b = issue({ number: 6, labels: ['needs-triage'], comments: [c('ARCHITECT: x', '2026-11-01T00:00:00Z'), c('TRIAGE: 补设计', '2026-11-02T00:00:00Z')] });
  const r = run([a, b]);
  assert.deepEqual(r.triage.map((x) => x.number), [5]);
  assert.equal(r.warnings.find((w) => w.type === 'triage-label-stale').number, 6);
});
test('WAITING 日期：两种写法，不带日期的不算', () => {
  assert.equal(parseWaitingDate('WAITING: 日期 2026-11-01\n等别的'), '2026-11-01');
  assert.equal(parseWaitingDate('WAITING: 2026-11-01'), '2026-11-01');
  assert.equal(parseWaitingDate('WAITING: 已放回\n日期已到'), null);
});
test('到期：今天与更早进，晚于今天不进，parent/stage/trial 不进，最后一条是已放回不进', () => {
  const w = (n, body, labels = []) => issue({ number: n, labels: ['waiting', ...labels], comments: [c(body)] });
  const r = run([w(1, 'WAITING: 日期 2026-11-07'), w(2, 'WAITING: 2026-10-01'), w(3, 'WAITING: 日期 2026-11-08'),
    w(4, 'WAITING: 日期 2026-10-01', ['parent']), w(5, 'WAITING: 日期 2026-10-01', ['trial']), w(6, 'WAITING: 日期 2026-10-01', ['stage']),
    issue({ number: 7, labels: ['waiting'], comments: [c('WAITING: 日期 2026-10-01'), c('WAITING: 已放回\n日期已到')] })]);
  assert.deepEqual(r.due.map((x) => x.number), [1, 2]);
  assert.equal(r.handToUser.length, 0);
});
test('到期：已放回满两次交给用户，一次仍放回', () => {
  const mk = (n, times) => issue({ number: n, labels: ['waiting'], comments: [
    ...Array.from({ length: times }, () => c('WAITING: 已放回\n日期已到')), c('WAITING: 日期 2026-11-01')] });
  const r = run([mk(1, 2), mk(2, 1)]);
  assert.deepEqual(r.handToUser.map((x) => x.number), [1]);
  assert.deepEqual(r.due.map((x) => x.number), [2]);
});
test('解挡：TRIAGE 点名的 architecture 工单已关闭且在 TRIAGE 之后才关', () => {
  const h = (comments) => issue({ number: 9, labels: ['ready-for-human'], comments });
  const refs = { 100: { state: 'CLOSED', closedAt: '2026-11-05T00:00:00Z', labels: ['architecture'] }, 101: { state: 'OPEN', closedAt: null, labels: ['architecture'] }, 102: { state: 'CLOSED', closedAt: '2026-11-05T00:00:00Z', labels: ['bug'] } };
  const t = (txt, at = '2026-11-02T00:00:00Z') => [c(txt, at)];
  assert.equal(run([h(t('TRIAGE: 交给用户，见 #100'))], refs).unblocked[0].architecture, 100);
  assert.equal(run([h(t('TRIAGE: 见 #101'))], refs).unblocked.length, 0);
  assert.equal(run([h(t('TRIAGE: 见 #102'))], refs).unblocked.length, 0);
  assert.equal(run([h(t('TRIAGE: 见 #100', '2026-11-06T00:00:00Z'))], refs).unblocked.length, 0, '关闭以后又有新 TRIAGE');
  assert.equal(run([h([c('TRIAGE: 见 #100', '2026-11-02T00:00:00Z'), c('TRIAGE: 补设计', '2026-11-06T00:00:00Z')])], refs).unblocked.length, 0);
});
test('提醒：范围外的 ready-for-agent；被范围外挡着', () => {
  const out = issue({ number: 20, milestone: 'Other', milestoneNumber: 3, labels: ['ready-for-agent'] });
  const noMs = issue({ number: 21, milestone: '', milestoneNumber: 0, labels: ['ready-for-agent'] });
  const inn = issue({ number: 22, blockedBy: [{ number: 20, state: 'OPEN' }, { number: 99, state: 'CLOSED' }, { number: 23, state: 'OPEN' }] });
  const inn2 = issue({ number: 23 });
  const w = run([out, noMs, inn, inn2]).warnings;
  assert.deepEqual(w.filter((x) => x.type === 'ready-outside-scope').map((x) => x.number), [20, 21]);
  assert.deepEqual(w.filter((x) => x.type === 'blocked-outside-scope').map((x) => [x.number, x.blocker]), [[22, 20]]);
});
test('范围可以写里程碑编号', () => {
  const r = classify([issue({ labels: ['needs-triage'] })], { today: '2026-11-07', scope: [8] });
  assert.equal(r.triage.length, 1);
});
