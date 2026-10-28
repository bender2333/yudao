import test from 'node:test';
import assert from 'node:assert/strict';
import { openBlockers, isSelectable, pickUpTo } from '../lib/select.mjs';
import { parseTasksText } from '../lib/tasks-format.mjs';

const task = (over) => Object.assign({
  id: 'T-001',
  issue: 11,
  status: 'pending',
  text: 'T-001 #11 做点事',
  after: [],
  exclusive: false,
}, over);

const ctx = (over) => Object.assign({
  activeIds: new Set(),
  taskState: {},
  doneIds: new Set(),
  issue: { number: 11, labels: [], blockedBy: [] },
}, over);

test('阻塞解析：阻塞方全都开着时逐个列出', () => {
  assert.deepEqual(openBlockers([{ number: 1, state: 'OPEN' }, { number: 2, state: 'OPEN' }]), [1, 2]);
});

test('阻塞解析：全部 CLOSED 时一张都不挡', () => {
  assert.deepEqual(openBlockers([{ number: 1, state: 'CLOSED' }, { number: 2, state: 'CLOSED' }]), []);
});

test('阻塞解析：混合时只算还开着的那些', () => {
  assert.deepEqual(openBlockers([
    { number: 1, state: 'CLOSED' },
    { number: 2, state: 'OPEN' },
    { number: 3, state: 'CLOSED' },
  ]), [2]);
});

test('阻塞解析：缺 state 字段时按还开着算（拉不全宁可少派一张）', () => {
  assert.deepEqual(openBlockers([{ number: 7 }]), [7]);
});

test('阻塞解析：空数组或没有这个字段时不算挡', () => {
  assert.deepEqual(openBlockers([]), []);
  assert.deepEqual(openBlockers(undefined), []);
});

test('选活：行内依赖都 done 了才可选', () => {
  const t = task({ after: ['T-002', 'T-003'] });
  assert.equal(isSelectable(t, ctx({ doneIds: new Set(['T-002', 'T-003']) })), true);
  assert.equal(isSelectable(t, ctx({ doneIds: new Set(['T-002']) })), false);
});

test('选活：有一个 OPEN 的阻塞方就不可选，全关以后又能选', () => {
  const t = task();
  const blocked = ctx({ issue: { number: 11, labels: [], blockedBy: [{ number: 9, state: 'OPEN' }] } });
  const free = ctx({ issue: { number: 11, labels: [], blockedBy: [{ number: 9, state: 'CLOSED' }] } });
  assert.equal(isSelectable(t, blocked), false);
  assert.equal(isSelectable(t, free), true);
});

test('选活：status 不是 pending 就不可选（做完、交回、等条件）', () => {
  for (const status of ['done', 'escalated', 'waiting']) {
    assert.equal(isSelectable(task({ status }), ctx()), false, status);
  }
});

test('选活：行内标了（waiting）或（等用户）的行解析成 waiting，选不到', () => {
  const [waiting] = parseTasksText('- [ ] T-008 #871 做点事 （waiting）');
  const [forUser] = parseTasksText('- [ ] T-008 #871 做点事 （等用户）');
  assert.equal(waiting.status, 'waiting');
  assert.equal(forUser.status, 'waiting');
  assert.equal(isSelectable(waiting, ctx()), false);
  assert.equal(isSelectable(forUser, ctx()), false);
});

test('选活：行内标了（不在范围）的不可选', () => {
  assert.equal(isSelectable(task({ text: 'T-001 #11 做点事 （不在范围）' }), ctx()), false);
});

test('选活：账本里记成别人在做（external）的不可选', () => {
  assert.equal(isSelectable(task(), ctx({ taskState: { 'T-001': { external: { label: 'in-progress' } } } })), false);
});

test('选活：账本里标了交回（[~] 之后又被记成 escalated）的不可选', () => {
  assert.equal(isSelectable(task(), ctx({ taskState: { 'T-001': { escalated: true } } })), false);
});

test('选活：已经在并发位置上的不重复派', () => {
  assert.equal(isSelectable(task(), ctx({ activeIds: new Set(['T-001']) })), false);
});

test('选活：挂着 needs-triage / waiting / ready-for-human 的单子不派', () => {
  for (const label of ['needs-triage', 'waiting', 'ready-for-human']) {
    assert.equal(isSelectable(task(), ctx({ issue: { number: 11, labels: [label], blockedBy: [] } })), false, label);
  }
});

test('选活：in-progress 标签本身不是「停着」，挡不挡由负责人判断', () => {
  assert.equal(isSelectable(task(), ctx({ issue: { number: 11, labels: ['in-progress', 'bug'], blockedBy: [] } })), true);
});

test('选活：外部没有这张工单时不派（关掉了或转走了）', () => {
  assert.equal(isSelectable(task(), ctx({ issue: null })), false);
});

test('选活：什么都不挡时可选', () => {
  assert.equal(isSelectable(task(), ctx()), true);
});

const cand = (id, over) => Object.assign({ id, issue: null, exclusive: false }, over);

test('挑选：max=2 时按顺序取两张', () => {
  const picked = pickUpTo([cand('T-001'), cand('T-002'), cand('T-003')], { max: 2, exclusiveLimit: 1, takenIssues: new Set() });
  assert.deepEqual(picked.map((t) => t.id), ['T-001', 'T-002']);
});

test('挑选：同一个 issue 的两行只取一张', () => {
  const picked = pickUpTo(
    [cand('T-001', { issue: 42 }), cand('T-002', { issue: 42 }), cand('T-003', { issue: 43 })],
    { max: 4, exclusiveLimit: 1, takenIssues: new Set() },
  );
  assert.deepEqual(picked.map((t) => t.id), ['T-001', 'T-003']);
});

test('挑选：max=0 时一张都不取', () => {
  assert.deepEqual(pickUpTo([cand('T-001'), cand('T-002')], { max: 0, exclusiveLimit: 4, takenIssues: new Set() }), []);
});

test('挑选：互斥名额只有 1 时 @exclusive 的行只取一张，非互斥的照取', () => {
  const picked = pickUpTo(
    [cand('T-001', { exclusive: true }), cand('T-002', { exclusive: true }), cand('T-003')],
    { max: 4, exclusiveLimit: 1, takenIssues: new Set() },
  );
  assert.deepEqual(picked.map((t) => t.id), ['T-001', 'T-003']);
});

test('挑选：touches-core 只是标签，行不因它占用互斥名额', () => {
  const picked = pickUpTo(
    [cand('T-001', { text: '（touches-core）' }), cand('T-002', { text: '（touches-core）' })],
    { max: 4, exclusiveLimit: 1, takenIssues: new Set() },
  );
  assert.deepEqual(picked.map((t) => t.id), ['T-001', 'T-002']);
});

test('挑选：takenIssues 里已有的 issue 不再取（在跑的人已经占着）', () => {
  const picked = pickUpTo(
    [cand('T-001', { issue: 42 }), cand('T-002', { issue: 43 })],
    { max: 4, exclusiveLimit: 1, takenIssues: new Set([42]) },
  );
  assert.deepEqual(picked.map((t) => t.id), ['T-002']);
});

test('挑选：互斥名额 0 时一张互斥都不取', () => {
  const picked = pickUpTo(
    [cand('T-001', { exclusive: true }), cand('T-002')],
    { max: 4, exclusiveLimit: 0, takenIssues: new Set() },
  );
  assert.deepEqual(picked.map((t) => t.id), ['T-002']);
});
