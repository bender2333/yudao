/**
 * 日记轮转：把旧日记移到 docs/archive/，规则固定，不靠模型判断。
 *
 * - agents_jour/：文件数超过 JOUR_MAX_FILES 时，只留最近提交的 JOUR_KEEP_FILES 个。
 * - claude_jour.md：行数超过 JOURNAL_MAX_LINES 时，只留最后约 JOURNAL_KEEP_LINES 行（从日记头切）。
 *
 * 只暂存，不提交；出错直接抛出。
 */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const JOUR_MAX_FILES = 20;
const JOUR_KEEP_FILES = 10;
const JOURNAL_MAX_LINES = 600;
const JOURNAL_KEEP_LINES = 300;

const HEADER = /^.{0,60}?\b(20\d\d-\d\d)-\d\d\b/;

function git(root, ...args) {
  return execFileSync('git', ['-c', 'core.quotepath=off', ...args], { cwd: root, encoding: 'utf8' });
}

/** agents_jour 下的文件名，从新到旧：没提交过的最新，其余按最后一次提交的先后。 */
function filesNewestFirst(root, files) {
  const logged = git(root, 'log', '--format=', '--name-only', '--', 'agents_jour')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((p) => path.posix.basename(p));
  const rank = new Map();
  for (const name of logged) if (!rank.has(name)) rank.set(name, rank.size);
  return [
    ...files.filter((n) => !rank.has(n)),
    ...files.filter((n) => rank.has(n)).sort((a, b) => rank.get(a) - rank.get(b)),
  ];
}

function rotateAgentsJour(root) {
  const dir = path.join(root, 'agents_jour');
  if (!fs.existsSync(dir)) return 0;
  const files = fs.readdirSync(dir, { withFileTypes: true }).filter((e) => e.isFile()).map((e) => e.name);
  if (files.length <= JOUR_MAX_FILES) return 0;

  const moving = filesNewestFirst(root, files).slice(JOUR_KEEP_FILES);
  fs.mkdirSync(path.join(root, 'docs', 'archive', 'agents_jour'), { recursive: true });
  for (const name of moving) {
    const src = `agents_jour/${name}`;
    const dst = `docs/archive/agents_jour/${name}`;
    if (fs.existsSync(path.join(root, dst))) {
      const old = fs.readFileSync(path.join(root, dst), 'utf8');
      const sep = old === '' || old.endsWith('\n') ? '' : old.includes('\r\n') ? '\r\n' : '\n';
      fs.appendFileSync(path.join(root, dst), sep + fs.readFileSync(path.join(root, src), 'utf8'));
      git(root, 'rm', '-f', '--', src);
      git(root, 'add', '--', dst);
    } else {
      git(root, 'mv', '--', src, dst);
    }
  }
  return moving.length;
}

function rotateClaudeJour(root) {
  const file = path.join(root, 'claude_jour.md');
  if (!fs.existsSync(file)) return { lines: 0, archive: null };
  const text = fs.readFileSync(file, 'utf8');
  // 每行连换行符一起保留，拼回去与原文逐字节相同
  const lines = text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  if (lines.length <= JOURNAL_MAX_LINES) return { lines: 0, archive: null };

  const bare = (l) => l.replace(/\r?\n$/, '');
  const isHeader = (l) => HEADER.test(bare(l));
  const head = lines.findIndex(isHeader);
  let cut = -1;
  for (let i = lines.length - JOURNAL_KEEP_LINES; i < lines.length; i++) {
    if (isHeader(lines[i])) { cut = i; break; }
  }
  if (head < 0 || cut <= head) throw new Error('claude_jour.md 找不到可切的日记头');

  const moved = lines.slice(head, cut);
  const month = HEADER.exec(bare(moved.findLast(isHeader)))[1];
  const eol = text.includes('\r\n') ? '\r\n' : '\n';

  const archive = `docs/archive/claude_jour-${month}.md`;
  const archiveFile = path.join(root, archive);
  fs.mkdirSync(path.dirname(archiveFile), { recursive: true });
  if (!fs.existsSync(archiveFile)) fs.writeFileSync(archiveFile, `# Claude 执行日记（${month}）${eol}${eol}`);
  fs.appendFileSync(archiveFile, moved.join(''));
  fs.writeFileSync(file, lines.slice(0, head).concat(lines.slice(cut)).join(''));
  git(root, 'add', '--', 'claude_jour.md', archive);
  return { lines: moved.length, archive };
}

export function rotate(root) {
  const movedFiles = rotateAgentsJour(root);
  const { lines: movedLines, archive } = rotateClaudeJour(root);
  return { movedFiles, movedLines, archive };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const r = rotate(path.resolve(process.argv[2] ?? '.'));
  console.log(
    r.movedFiles || r.movedLines
      ? `日记归档：移走 ${r.movedFiles} 个执行者日记，${r.movedLines} 行架构师日记到 ${r.archive ?? '（无）'}`
      : '日记没有超过上限',
  );
}
