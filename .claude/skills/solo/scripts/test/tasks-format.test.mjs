import test from 'node:test';
import assert from 'node:assert/strict';
import { parseTasksText, parseAfter } from '../lib/tasks-format.mjs';

test('tasks 解析：空格待办、x 完成、~ 已交回是三种状态', () => {
  const tasks = parseTasksText([
    '- [ ] T-001 #11 待办的事',
    '- [x] T-002 #12 做完的事',
    '- [~] T-003 #13 交回的事',
  ].join('\n'));
  assert.deepEqual(tasks.map((t) => t.status), ['pending', 'done', 'escalated']);
  assert.deepEqual(tasks.map((t) => t.id), ['T-001', 'T-002', 'T-003']);
});

test('tasks 解析：行尾（waiting）与（等用户）标成等条件，不是待办', () => {
  const tasks = parseTasksText([
    '- [ ] T-001 #11 等前提条件的事 （waiting）',
    '- [ ] T-002 #12 缺凭据的事 （等用户）',
  ].join('\n'));
  assert.deepEqual(tasks.map((t) => t.status), ['waiting', 'waiting']);
  assert.deepEqual(tasks.map((t) => t.blocked), [true, true]);
});

test('tasks 解析：（不在范围）不改变勾选，行留在台账里仍可读', () => {
  const [t] = parseTasksText('- [ ] T-001 #11 已经离开范围的事 （不在范围）');
  assert.equal(t.status, 'pending');
  assert.match(t.text, /不在范围/);
});

test('tasks 解析：行内 #编号、@exclusive 与 (after T-030) 都认出来', () => {
  const [t] = parseTasksText('- [ ] T-031 #952 翻译层的底座（touches-core） @exclusive (after T-030)');
  assert.equal(t.id, 'T-031');
  assert.equal(t.issue, 952);
  assert.equal(t.exclusive, true);
  assert.deepEqual(t.after, ['T-030']);
});

test('tasks 解析：中文的「依赖 T-030」也算依赖', () => {
  const [t] = parseTasksText('- [ ] T-032 #953 楼层的事 依赖 T-030');
  assert.deepEqual(t.after, ['T-030']);
});

test('tasks 解析：几个依赖写在一起时都认', () => {
  const [t] = parseTasksText('- [ ] T-033 #954 房间的事 (after T-030, T-031) 依赖 T-020');
  assert.deepEqual(t.after.slice().sort(), ['T-020', 'T-030', 'T-031']);
});

test('tasks 解析：旧的表格行按已完成算，分隔行不算任务', () => {
  const tasks = parseTasksText([
    '| T-001 | 早点做完的事 |',
    '| --- | --- |',
  ].join('\n'));
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].id, 'T-001');
  assert.equal(tasks[0].status, 'done');
});

test('依赖解析：blocked by 与 depends on 也认，带井号的工单号去掉井号，重复的只留一份', () => {
  assert.deepEqual(parseAfter('blocked by T-030'), ['T-030']);
  assert.deepEqual(parseAfter('blocked by #42'), ['42']);
  assert.deepEqual(parseAfter('depends on T-030'), ['T-030']);
  assert.deepEqual(parseAfter('(after T-030) 依赖 T-030'), ['T-030']);
});

test('tasks 解析：空文本没有任务', () => {
  assert.deepEqual(parseTasksText(''), []);
});
