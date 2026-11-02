import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { rotate } from '../rotate-journals.mjs';

function git(root, ...args) {
  return execFileSync('git', ['-c', 'core.quotepath=off', ...args], { cwd: root, encoding: 'utf8' });
}

function newRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rotate-journals-'));
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

const names = (root, dir) => fs.readdirSync(path.join(root, dir)).sort();

test('都没超上限：文件和暂存区都不变', () => {
  const root = newRepo();
  for (let i = 1; i <= 20; i++) commit(root, `agents_jour/${i}.md`);
  commit(root, 'claude_jour.md', '2026-10-01 a\n'.repeat(600));
  const before = git(root, 'status', '--porcelain');
  assert.deepEqual(rotate(root), { movedFiles: 0, movedLines: 0, archive: null });
  assert.equal(git(root, 'status', '--porcelain'), before);
  assert.equal(names(root, 'agents_jour').length, 20);
});

test('21 个执行者日记：留下最后提交的 10 个，其他.md 最后提交时留下', () => {
  const root = newRepo();
  for (let i = 1; i <= 20; i++) commit(root, `agents_jour/${i}.md`);
  commit(root, 'agents_jour/其他.md');
  const r = rotate(root);
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
  rotate(root);
  assert.ok(names(root, 'agents_jour').includes('656-fix.md'));
  assert.equal(names(root, 'agents_jour').length, 10);
});

test('目标已存在：内容接在归档文件末尾，原文件不在了', () => {
  const root = newRepo();
  commit(root, 'docs/archive/agents_jour/1.md', 'old\n');
  commit(root, 'agents_jour/1.md', 'new\n');
  for (let i = 2; i <= 21; i++) commit(root, `agents_jour/${i}.md`);
  rotate(root);
  assert.equal(fs.readFileSync(path.join(root, 'docs/archive/agents_jour/1.md'), 'utf8'), 'old\nnew\n');
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
    rotate(root);
    assert.equal(fs.readFileSync(path.join(root, 'docs/archive/agents_jour/1.md'), 'utf8'), want);
  }
});

test('架构师日记：CRLF、混合日记头，切在日记头上，内容一行不丢', () => {
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
      ][i % 4],
      '正文一行',
      '正文二行，日期出现在很后面 2025-01-01，不是日记头'.padStart(100, '字'),
      '',
    );
  }
  assert.ok(lines.length > 600);
  const original = lines.join('\r\n') + '\r\n';
  commit(root, 'claude_jour.md', original);

  const r = rotate(root);
  assert.equal(r.archive, 'docs/archive/claude_jour-2026-11.md');
  const kept = fs.readFileSync(path.join(root, 'claude_jour.md'), 'utf8');
  const archived = fs.readFileSync(path.join(root, r.archive), 'utf8');

  const title = '# Claude 执行日记（2026-11）\r\n\r\n';
  assert.ok(archived.startsWith(title));
  const headText = head.join('\r\n') + '\r\n';
  assert.ok(kept.startsWith(headText));
  const keptBody = kept.slice(headText.length);
  assert.match(keptBody.split('\r\n')[0], /2026-/);
  const keptLines = keptBody.split('\r\n').length - 1;
  assert.ok(keptLines <= 304 && keptLines >= 296, `留下 ${keptLines} 行`);
  assert.equal(headText + archived.slice(title.length) + keptBody, original);
  assert.equal(r.movedLines, archived.slice(title.length).split('\r\n').length - 1);
  for (const s of [kept, archived]) assert.ok(!/(?<!\r)\n/.test(s));
  assert.ok(git(root, 'diff', '--cached', '--name-only').includes('docs/archive/claude_jour-2026-11.md'));
});

test('再运行一次什么也不动', () => {
  const root = newRepo();
  for (let i = 1; i <= 21; i++) commit(root, `agents_jour/${i}.md`);
  const body = Array.from({ length: 400 }, (_, i) => `claude-opus-5-5 / 2026-10-${String((i % 28) + 1).padStart(2, '0')} / t\nbody`).join('\n');
  commit(root, 'claude_jour.md', '# 头\n' + body + '\n');
  rotate(root);
  const status = git(root, 'status', '--porcelain');
  const journal = fs.readFileSync(path.join(root, 'claude_jour.md'), 'utf8');
  assert.deepEqual(rotate(root), { movedFiles: 0, movedLines: 0, archive: null });
  assert.equal(git(root, 'status', '--porcelain'), status);
  assert.equal(fs.readFileSync(path.join(root, 'claude_jour.md'), 'utf8'), journal);
});
