import test from 'node:test';
import assert from 'node:assert/strict';
import { summarize, beatLine, scopeDisplay, STALE_MINUTES } from '../lib/report.mjs';

const NOW = Date.parse('2026-10-29T09:10:00Z');
const BEAT_AT = '2026-10-29T09:04:00.000Z';

/** 心跳印的是本机时间，期望值按本机时间拼，跑在哪个时区都对得上。 */
const localStamp = (iso) => {
  const d = new Date(Date.parse(iso));
  const pad = (n) => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
    + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
};

const ledgerState = (over) => Object.assign({
  loop: 'stage1',
  status: 'running',
  iteration: 11,
  maxIterations: 120,
  autoContinue: true,
  waitMode: 'notify',
  scope: {
    milestoneIds: [5, 7],
    labels: [],
    prefixes: [],
    milestoneTitles: { 5: '阶段一 · 1 核心打通', 7: '阶段一 · 2 换骨架不变差' },
  },
  concurrency: { max: 4, exclusiveLimit: 1, active: [{ task: 'T-004' }, { task: 'T-031' }] },
  taskState: {
    'T-008': { waitFor: 'user' },
    'T-012': { escalated: true, fails: 2 },
  },
  beatAt: BEAT_AT,
}, over);

const tasksOf = () => [
  { id: 'T-004', issue: 561, status: 'pending', after: [], text: 'T-004 #561 在跑的' },
  { id: 'T-031', issue: 952, status: 'pending', after: [], text: 'T-031 #952 在跑的' },
  { id: 'T-008', issue: 871, status: 'waiting', after: [], text: 'T-008 #871 等用户' },
  { id: 'T-012', issue: 957, status: 'escalated', after: [], text: 'T-012 #957 交回' },
  { id: 'T-020', issue: 1098, status: 'pending', after: ['T-011'], text: 'T-020 #1098 等依赖' },
  { id: 'T-011', issue: 1126, status: 'pending', after: [], text: 'T-011 #1126 可以派' },
];

const flightOf = () => [
  { task: 'T-004', issue: 561, branch: 'issue-561', minutes: 42, sinceCommitMin: 3 },
  { task: 'T-031', issue: 952, branch: 'issue-952', minutes: 95, sinceCommitMin: 40 },
];

/** 这一次拉到的开放工单：默认把台账里的工单都当成在 GitHub 上开着。 */
const openIssuesOf = (tasks) => tasks.filter((t) => t.issue).map((t) => ({ number: t.issue, labels: ['ready-for-agent'], blockedBy: [] }));

test('report 一屏：在跑、卡住、等你、交回、依赖挡着、下一步、心跳各一行', () => {
  const tasks = tasksOf();
  const { lines } = summarize({ state: ledgerState(), tasks, now: NOW, flight: flightOf(), openIssues: openIssuesOf(tasks) });
  assert.deepEqual(lines, [
    '循环: stage1  状态: running  第 11/120 轮  无人值守 开（收账靠 宿主通知：派完就结束回合）',
    '范围: 里程碑 #5（阶段一 · 1 核心打通） #7（阶段一 · 2 换骨架不变差）',
    '在跑 2/4: T-004 #561 issue-561 已 42 分钟，最近提交 3 分钟前；T-031 #952 issue-952 已 95 分钟，最近提交 40 分钟前',
    '卡住: T-031 #952 已 95 分钟没有新提交（reap 会回收）',
    '等你: T-008 #871',
    '交回: T-012 #957 第 2 次',
    '依赖挡着: T-020 #1098 等 T-011',
    '下一步: T-011 #1126',
    '心跳: ' + localStamp(BEAT_AT) + '（距今 6 分钟）',
  ]);
});

test('report 一屏：没有在跑的人时「在跑」「卡住」两行都不打印', () => {
  const { lines } = summarize({ state: ledgerState({ concurrency: { max: 4, exclusiveLimit: 1, active: [] } }), tasks: tasksOf(), now: NOW, flight: [] });
  assert.equal(lines.some((l) => l.startsWith('在跑')), false);
  assert.equal(lines.some((l) => l.startsWith('卡住')), false);
});

test('report 卡住的判据：开派满 reap 的 90 分钟，且最近一次提交超过 30 分钟', () => {
  assert.equal(STALE_MINUTES, 90);
  const state = ledgerState({ concurrency: { max: 4, exclusiveLimit: 1, active: [{ task: 'T-004' }] } });
  const stuckOf = (minutes, sinceCommitMin) => summarize({
    state,
    tasks: tasksOf(),
    now: NOW,
    flight: [{ task: 'T-004', issue: 561, branch: 'issue-561', minutes, sinceCommitMin }],
  }).lines.some((l) => l.startsWith('卡住'));

  assert.equal(stuckOf(89, 60), false, '还没到 90 分钟不算卡住');
  assert.equal(stuckOf(95, 29), false, '一分钟前刚提交过不算卡住');
  assert.equal(stuckOf(90, 30), true);
  assert.equal(stuckOf(95, null), false, '看不到提交时刻时不说它卡住');
});

test('report 下一步：排到依赖已经满足的那张，并说明依赖已满足', () => {
  const tasks = [
    { id: 'T-011', issue: 1126, status: 'pending', after: ['T-004'], text: 'T-011 #1126 依赖写好以后才能做' },
    { id: 'T-004', issue: 561, status: 'done', after: [], text: 'T-004 #561 已经做完' },
  ];
  const { lines } = summarize({
    state: ledgerState({ concurrency: { max: 4, exclusiveLimit: 1, active: [] } }),
    tasks,
    now: NOW,
    flight: [],
    openIssues: openIssuesOf(tasks),
  });
  assert.equal(lines.find((l) => l.startsWith('下一步')), '下一步: T-011 #1126（依赖已满足）');
});

test('report 等你与交回：已经完成的单子不印，台账里留着的旧标记不算还要处理', () => {
  const tasks = tasksOf().map((t) => (t.id === 'T-008' || t.id === 'T-012' ? Object.assign(t, { status: 'done' }) : t));
  const { lines } = summarize({ state: ledgerState(), tasks, now: NOW, flight: [], openIssues: openIssuesOf(tasks) });
  assert.equal(lines.some((l) => l.startsWith('等你')), false, '已完成的那张还带着 waitFor=user，也不能印');
  assert.equal(lines.some((l) => l.startsWith('交回')), false, '已完成的那张还带着 escalated，也不能印');
});

test('report 下一步：台账里 pending 但 GitHub 上已经关掉的单子不当成下一步', () => {
  const tasks = [
    { id: 'T-024', issue: 477, status: 'pending', after: [], text: 'T-024 #477 台账里还开着' },
  ];
  const state = ledgerState({ concurrency: { max: 4, exclusiveLimit: 1, active: [] } });
  const open = summarize({ state, tasks, now: NOW, flight: [], openIssues: openIssuesOf(tasks) });
  assert.equal(open.lines.some((l) => l.startsWith('下一步')), true, '开着时算下一步');

  const closed = summarize({ state, tasks, now: NOW, flight: [], openIssues: [] });
  assert.equal(closed.lines.some((l) => l.startsWith('下一步')), false, '关掉以后不能印出来');

  const noFetch = summarize({ state, tasks, now: NOW, flight: [] });
  assert.equal(noFetch.lines.some((l) => l.startsWith('下一步')), false, '没有拉到开放工单时宁可缺这一行');
});

test('report 一屏：台账里没有可派的单子时「下一步」这一行不打印', () => {
  const tasks = tasksOf().map((t) => (t.id === 'T-011' ? Object.assign(t, { status: 'waiting' }) : t));
  const { lines } = summarize({ state: ledgerState(), tasks, now: NOW, flight: [], openIssues: openIssuesOf(tasks) });
  assert.equal(lines.some((l) => l.startsWith('下一步')), false);
});

test('report 心跳：账本里没有 beatAt 时不打印，也不报错', () => {
  const state = ledgerState();
  delete state.beatAt;
  assert.equal(beatLine(state, NOW), '');
  const { lines } = summarize({ state, tasks: tasksOf(), now: NOW, flight: [] });
  assert.equal(lines.some((l) => l.startsWith('心跳')), false);
});

test('report 心跳：时刻按写盘时间印成本机时间，距今按入参的 now 算（不读时钟）', () => {
  const beat = { beatAt: '2026-10-29T09:04:30.000Z' };
  assert.equal(beatLine(beat, NOW), '心跳: ' + localStamp(beat.beatAt) + '（距今 6 分钟）');
  assert.equal(beatLine(beat, Date.parse('2026-10-29T09:34:30Z')), '心跳: ' + localStamp(beat.beatAt) + '（距今 30 分钟）');
  assert.equal(beatLine({ beatAt: '不是时刻' }, NOW), '心跳: 不是时刻');
});

test('report 一屏：不给 now 就报错，不在里面读时钟', () => {
  assert.throws(() => summarize({ state: ledgerState(), tasks: tasksOf(), flight: [] }), /now/);
});

test('report 一屏：不改传进来的账本与任务清单', () => {
  const state = ledgerState();
  const tasks = tasksOf();
  const beforeState = JSON.stringify(state);
  const beforeTasks = JSON.stringify(tasks);
  summarize({ state, tasks, now: NOW, flight: flightOf() });
  assert.equal(JSON.stringify(state), beforeState);
  assert.equal(JSON.stringify(tasks), beforeTasks);
});

test('report 范围一行：没配范围时说全部开放工单，标签与前缀也能拼', () => {
  assert.equal(scopeDisplay({}), '（全部开放工单）');
  assert.equal(scopeDisplay({ labels: ['bug'], prefixes: ['[界面'] }), '标签 bug，标题前缀 [界面');
  assert.equal(scopeDisplay({ milestoneId: 5, milestoneTitles: {} }), '里程碑 #5');
});
