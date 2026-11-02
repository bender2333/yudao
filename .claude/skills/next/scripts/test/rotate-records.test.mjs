import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { rotate, LIMITS } from '../rotate-records.mjs';

function git(root, ...args) {
  return execFileSync('git', ['-c', 'core.quotepath=off', ...args], { cwd: root, encoding: 'utf8' });
}

function newRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rotate-records-'));
  git(root, 'init', '-q');
  git(root, 'config', 'user.name', 'test');
  git(root, 'config', 'user.email', 'test@example.com');
  return root;
}

function commit(root, rel, content = 'x\n') {
  const abs = path.join(root, rel);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, content);
  git(root, 'add', '--', rel);
  git(root, 'commit', '-q', '-m', rel);
}

const read = (root, rel) => fs.readFileSync(path.join(root, rel), 'utf8');
const names = (root, dir) => fs.readdirSync(path.join(root, dir)).sort();
const NONE = { movedFiles: 0, movedLines: 0, archives: [] };

/** 执行者日记上限用原来的 20/10，三份记录用 max/keep。 */
const limits = (max, keep) => ({
  agentsJour: { max: 20, keep: 10 },
  records: LIMITS.records.map((r) => ({ ...r, max, keep })),
});
const L600 = limits(600, 300);

test('都没超上限：文件和暂存区都不变', () => {
  const root = newRepo();
  for (let i = 1; i <= 20; i++) commit(root, `agents_jour/${i}.md`);
  commit(root, 'claude_jour.md', '2026-10-01 a\n'.repeat(600));
  const before = git(root, 'status', '--porcelain');
  assert.deepEqual(rotate(root, L600), NONE);
  assert.equal(git(root, 'status', '--porcelain'), before);
  assert.equal(names(root, 'agents_jour').length, 20);
});

test('默认上限写在 LIMITS 里', () => {
  assert.equal(LIMITS.agentsJour.max, 200);
  assert.deepEqual(LIMITS.records.map((r) => [r.file, r.max, r.keep]), [
    ['claude_jour.md', 2000, 300],
    ['docs/CHANGELOG.md', 1000, 300],
    ['docs/decision.md', 1000, 300],
  ]);
});

test('21 个执行者日记：留下最后提交的 10 个，其他.md 最后提交时留下', () => {
  const root = newRepo();
  for (let i = 1; i <= 20; i++) commit(root, `agents_jour/${i}.md`);
  commit(root, 'agents_jour/其他.md');
  const r = rotate(root, L600);
  assert.equal(r.movedFiles, 11);
  const expected = ['其他.md', ...Array.from({ length: 9 }, (_, i) => `${20 - i}.md`)].sort();
  assert.deepEqual(names(root, 'agents_jour'), expected);
  assert.equal(names(root, 'docs/archive/agents_jour').length, 11);
  assert.match(git(root, 'status', '--porcelain'), /^R/m);
});

test('没提交过的执行者日记算最新', () => {
  const root = newRepo();
  for (let i = 1; i <= 20; i++) commit(root, `agents_jour/${i}.md`);
  fs.writeFileSync(path.join(root, 'agents_jour', '656-fix.md'), 'new\n');
  rotate(root, L600);
  assert.ok(names(root, 'agents_jour').includes('656-fix.md'));
  assert.equal(names(root, 'agents_jour').length, 10);
});

test('目标已存在：内容接在归档文件末尾，原文件不在了', () => {
  const root = newRepo();
  commit(root, 'docs/archive/agents_jour/1.md', 'old\n');
  commit(root, 'agents_jour/1.md', 'new\n');
  for (let i = 2; i <= 21; i++) commit(root, `agents_jour/${i}.md`);
  rotate(root, L600);
  assert.equal(read(root, 'docs/archive/agents_jour/1.md'), 'old\nnew\n');
  assert.ok(!fs.existsSync(path.join(root, 'agents_jour/1.md')));
  assert.equal(git(root, 'status', '--porcelain', '--', 'docs/archive/agents_jour/1.md').trim()[0], 'M');
});

test('目标末尾没有换行：先补换行再接，换行符跟归档文件走', () => {
  for (const [oldText, newText, want] of [
    ['old', 'new\n', 'old\nnew\n'],
    ['a\r\nold', 'new\r\n', 'a\r\nold\r\nnew\r\n'],
  ]) {
    const root = newRepo();
    commit(root, 'docs/archive/agents_jour/1.md', oldText);
    commit(root, 'agents_jour/1.md', newText);
    for (let i = 2; i <= 21; i++) commit(root, `agents_jour/${i}.md`);
    rotate(root, L600);
    assert.equal(read(root, 'docs/archive/agents_jour/1.md'), want);
  }
});

test('架构师日记：CRLF、混合日记头、跨月，切在日记头上，内容一行不丢', () => {
  const root = newRepo();
  const head = ['# Claude 日记', '', '说明文字'];
  const lines = [...head];
  for (let i = 0; i < 160; i++) {
    const day = String((i % 28) + 1).padStart(2, '0');
    const month = i < 40 ? '10' : '11';
    lines.push(
      [
        `claude-opus-5-5 / 2026-${month}-${day} 11:34 / 标题${i}`,
        `## 2026-${month}-${day} 23:40 两份评审${i}`,
        `- claude-sonnet-5-5 / 2026-${month}-${day} 条目${i}`,
        `claude-opus-5-5 / 2026-${month}-${day} / 无时间${i}`,
        `claude-opus-5-5（画面线子架构师；页面由 claude-sonnet-5-5 子代理补） / 2026-${month}-${day} 09:00 / 括号${i}`,
      ][i % 5],
      '正文一行',
      '正文二行，日期出现在很后面 2025-01-01，不是日记头'.padStart(100, '字'),
      '',
    );
  }
  assert.ok(lines.length > 600);
  const original = lines.join('\r\n') + '\r\n';
  commit(root, 'claude_jour.md', original);

  const r = rotate(root, L600);
  assert.deepEqual(r.archives, ['docs/archive/claude_jour-2026-10.md', 'docs/archive/claude_jour-2026-11.md']);
  const kept = read(root, 'claude_jour.md');
  const a10 = read(root, r.archives[0]);
  const a11 = read(root, r.archives[1]);

  const title = (m) => `# Claude 执行日记（${m}）\r\n\r\n`;
  assert.ok(a10.startsWith(title('2026-10')));
  assert.ok(a11.startsWith(title('2026-11')));
  const headText = head.join('\r\n') + '\r\n';
  assert.ok(kept.startsWith(headText));
  const keptBody = kept.slice(headText.length);
  assert.match(keptBody.split('\r\n')[0], /2026-/);
  const keptLines = keptBody.split('\r\n').length - 1;
  assert.ok(keptLines <= 304 && keptLines >= 296, `留下 ${keptLines} 行`);
  const b10 = a10.slice(title('2026-10').length);
  const b11 = a11.slice(title('2026-11').length);
  assert.equal(headText + b10 + b11 + keptBody, original);
  assert.equal(r.movedLines, (b10 + b11).split('\r\n').length - 1);
  for (const s of [kept, a10, a11]) assert.ok(!/(?<!\r)\n/.test(s));
  const staged = git(root, 'diff', '--cached', '--name-only');
  assert.ok(staged.includes('claude_jour-2026-10.md') && staged.includes('claude_jour-2026-11.md'));
});

test('决策记录：切点落在 ## 标题上，正文里的日期不当切点，CRLF，文件头原样', () => {
  const root = newRepo();
  const headText = '# 决策记录\r\n\r\n';
  let original = headText;
  for (let i = 0; i < 12; i++) {
    original += `## 2026-10-0${(i % 9) + 1} 决策${i}\r\n- 背景：用户 2026-09-30 要求\r\n- 内容\r\n\r\n`;
  }
  commit(root, 'docs/decision.md', original);
  // 共 50 行，keep=11 时「总行数减 keep」正好落在某条的「背景」行上
  const r = rotate(root, limits(40, 11));
  assert.ok(r.movedLines > 0);
  const kept = read(root, 'docs/decision.md');
  assert.ok(kept.startsWith(headText + '## 2026-10-'));
  const archive = read(root, r.archives[0]);
  const title = '# 决策记录（2026-10）\r\n\r\n';
  assert.ok(archive.startsWith(title));
  assert.equal(headText + archive.slice(title.length) + kept.slice(headText.length), original);
  assert.ok(!/(?<!\r)\n/.test(kept + archive));
});

test('一批跨两个月：各进各月文件，正文里的旧日期不产生新月份', () => {
  const root = newRepo();
  const headText = '# 变更\n\n';
  const entry =(m, i) => `## 2026-${m}-0${i + 1} 条目
- 背景：用户 2026-09-30 要求
- 内容

`;
  const oct = Array.from({ length: 6 }, (_, i) => entry('10', i));
  const nov = Array.from({ length: 6 }, (_, i) => entry('11', i));
  const original = headText + [...oct, ...nov].join('');
  commit(root, 'docs/CHANGELOG.md', original);

  const r = rotate(root, limits(40, 12));
  assert.deepEqual(r.archives, ['docs/archive/CHANGELOG-2026-10.md', 'docs/archive/CHANGELOG-2026-11.md']);
  assert.ok(!fs.existsSync(path.join(root, 'docs/archive/CHANGELOG-2026-09.md')));
  const t = (m) => `# 文档变更记录（${m}）

`;
  const a10 = read(root, r.archives[0]).slice(t('2026-10').length);
  const a11 = read(root, r.archives[1]).slice(t('2026-11').length);
  assert.equal(a10, oct.join(''));
  assert.equal(a11, nov.slice(0, 3).join(''));
  assert.ok(a11.includes('2026-09-30'));
  const kept = read(root, 'docs/CHANGELOG.md');
  assert.equal(headText + a10 + a11 + kept.slice(headText.length), original);
});

test('文件开头倒序：每个记录头决定自己的月份，一行不多一行不少', () => {
  const root = newRepo();
  const headText = '# 变更\n\n';
  const dates =['11-01', '10-28', '10-21', '10-25', '10-29', '10-31', '11-02', '11-03', '11-04', '11-05', '11-06', '11-07'];
  const entries = dates.map((d, n) => `## 2026-${d} 条目${n}
- 背景：用户 2026-09-30 要求
- 内容${n}

`);
  const original = headText + entries.join('');
  commit(root, 'docs/CHANGELOG.md', original);

  const r = rotate(root, limits(40, 12));
  assert.deepEqual([...r.archives].sort(), ['docs/archive/CHANGELOG-2026-10.md', 'docs/archive/CHANGELOG-2026-11.md']);
  const body = (rel, m) => read(root, rel).slice(`# 文档变更记录（${m}）

`.length);
  const a10 = body('docs/archive/CHANGELOG-2026-10.md', '2026-10');
  const a11 = body('docs/archive/CHANGELOG-2026-11.md', '2026-11');
  assert.equal(a11, [0, 6, 7, 8].map((n) => entries[n]).join(''));
  assert.equal(a10, [1, 2, 3, 4, 5].map((n) => entries[n]).join(''));
  const kept = read(root, 'docs/CHANGELOG.md');
  assert.equal(kept, headText + entries.slice(9).join(''));
  const sorted = (t) => t.split('\n').sort();
  assert.deepEqual(sorted(a10 + a11 + kept), sorted(original));
});

test('三份记录：都超就都移走，只有一份超就只动那一份', () => {
  const log = (head) => head + Array.from({ length: 30 }, (_, i) => `## 2026-10-0${(i % 9) + 1} t${i}\n正文\n`).join('');
  const root = newRepo();
  commit(root, 'claude_jour.md', log('# 头\n'));
  commit(root, 'docs/CHANGELOG.md', log('# 变更\n'));
  commit(root, 'docs/decision.md', log('# 决策记录\n'));
  const r = rotate(root, limits(40, 10));
  assert.deepEqual(r.archives, [
    'docs/archive/claude_jour-2026-10.md',
    'docs/archive/CHANGELOG-2026-10.md',
    'docs/archive/decision-2026-10.md',
  ]);
  assert.ok(read(root, r.archives[1]).startsWith('# 文档变更记录（2026-10）\n\n'));

  const root2 = newRepo();
  commit(root2, 'claude_jour.md', log('# 头\n'));
  commit(root2, 'docs/CHANGELOG.md', '# 变更\n## 2026-10-01 a\n');
  const r2 = rotate(root2, limits(40, 10));
  assert.deepEqual(r2.archives, ['docs/archive/claude_jour-2026-10.md']);
  assert.equal(read(root2, 'docs/CHANGELOG.md'), '# 变更\n## 2026-10-01 a\n');
});

test('再运行一次什么也不动', () => {
  const root = newRepo();
  for (let i = 1; i <= 21; i++) commit(root, `agents_jour/${i}.md`);
  const body = Array.from({ length: 400 }, (_, i) => `claude-opus-5-5 / 2026-10-${String((i % 28) + 1).padStart(2, '0')} / t\nbody`).join('\n');
  commit(root, 'claude_jour.md', '# 头\n' + body + '\n');
  rotate(root, L600);
  const status = git(root, 'status', '--porcelain');
  const journal = read(root, 'claude_jour.md');
  assert.deepEqual(rotate(root, L600), NONE);
  assert.equal(git(root, 'status', '--porcelain'), status);
  assert.equal(read(root, 'claude_jour.md'), journal);
});
