/**
 * 记录轮转：把旧记录移到 docs/archive/，规则固定，不靠模型判断。
 *
 * - agents_jour/：文件数超过上限时，只留最近提交的若干个。
 * - 三份按日期写的记录（claude_jour.md、docs/CHANGELOG.md、docs/decision.md）：
 *   行数超过上限时，只留最后约 keep 行（从记录头切），移走的行按月份进 docs/archive/<前缀>-<年-月>.md。
 *
 * 只暂存，不提交；出错直接抛出。
 */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const ANY_DATE = /^.{0,60}?\b(20\d\d-\d\d)-\d\d\b/;
// decision.md 的正文常带日期，只认 `## ` 标题
const H2_DATE = /^## (20\d\d-\d\d)-\d\d/;

export const LIMITS = {
  agentsJour: { max: 200, keep: 10 },
  records: [
    { file: 'claude_jour.md', prefix: 'claude_jour', title: 'Claude 执行日记', header: ANY_DATE, max: 2000, keep: 300 },
    { file: 'docs/CHANGELOG.md', prefix: 'CHANGELOG', title: '文档变更记录', header: ANY_DATE, max: 1000, keep: 300 },
    { file: 'docs/decision.md', prefix: 'decision', title: '决策记录', header: H2_DATE, max: 1000, keep: 300 },
  ],
};

function git(root, ...args) {
  return execFileSync('git', ['-c', 'core.quotepath=off', ...args], { cwd: root, encoding: 'utf8' });
}

/** 接在文件末尾；原文件末尾缺换行时先补一个，换行符跟原文件走。 */
function appendTo(file, text) {
  const old = fs.readFileSync(file, 'utf8');
  const sep = old === '' || old.endsWith('\n') ? '' : old.includes('\r\n') ? '\r\n' : '\n';
  fs.appendFileSync(file, sep + text);
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

function rotateAgentsJour(root, { max, keep }) {
  const dir = path.join(root, 'agents_jour');
  if (!fs.existsSync(dir)) return 0;
  const files = fs.readdirSync(dir, { withFileTypes: true }).filter((e) => e.isFile()).map((e) => e.name);
  if (files.length <= max) return 0;

  const moving = filesNewestFirst(root, files).slice(keep);
  fs.mkdirSync(path.join(root, 'docs', 'archive', 'agents_jour'), { recursive: true });
  for (const name of moving) {
    const src = `agents_jour/${name}`;
    const dst = `docs/archive/agents_jour/${name}`;
    if (fs.existsSync(path.join(root, dst))) {
      appendTo(path.join(root, dst), fs.readFileSync(path.join(root, src), 'utf8'));
      git(root, 'rm', '-f', '--', src);
      git(root, 'add', '--', dst);
    } else {
      git(root, 'mv', '--', src, dst);
    }
  }
  return moving.length;
}

function rotateRecord(root, spec) {
  const file = path.join(root, spec.file);
  if (!fs.existsSync(file)) return { lines: 0, archives: [] };
  const text = fs.readFileSync(file, 'utf8');
  // 每行连换行符一起保留，拼回去与原文逐字节相同
  const lines = text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  if (lines.length <= spec.max) return { lines: 0, archives: [] };

  const match = (l) => spec.header.exec(l.replace(/\r?\n$/, ''));
  const head = lines.findIndex((l) => match(l));
  let cut = -1;
  for (let i = lines.length - spec.keep; i < lines.length; i++) {
    if (match(lines[i])) { cut = i; break; }
  }
  if (head < 0 || cut <= head) throw new Error(`${spec.file} 找不到可切的记录头`);

  // 当前月份只往后走：正文里提到旧日期的行不改变它
  const byMonth = new Map();
  let month = match(lines[head])[1];
  for (const line of lines.slice(head, cut)) {
    const m = match(line);
    if (m && m[1] > month) month = m[1];
    if (!byMonth.has(month)) byMonth.set(month, []);
    byMonth.get(month).push(line);
  }

  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  const archives = [];
  for (const [m, moved] of byMonth) {
    const rel = `docs/archive/${spec.prefix}-${m}.md`;
    const abs = path.join(root, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    if (fs.existsSync(abs)) appendTo(abs, moved.join(''));
    else fs.writeFileSync(abs, `# ${spec.title}（${m}）${eol}${eol}${moved.join('')}`);
    archives.push(rel);
  }
  fs.writeFileSync(file, lines.slice(0, head).concat(lines.slice(cut)).join(''));
  git(root, 'add', '--', spec.file, ...archives);
  return { lines: cut - head, archives };
}

export function rotate(root, limits = LIMITS) {
  const movedFiles = rotateAgentsJour(root, limits.agentsJour);
  let movedLines = 0;
  const archives = [];
  for (const spec of limits.records) {
    const r = rotateRecord(root, spec);
    movedLines += r.lines;
    archives.push(...r.archives);
  }
  return { movedFiles, movedLines, archives };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const r = rotate(path.resolve(process.argv[2] ?? '.'));
  console.log(
    r.movedFiles || r.movedLines
      ? `记录归档：移走 ${r.movedFiles} 个执行者日记，${r.movedLines} 行记录到 ${r.archives.join('、') || '（无）'}`
      : '记录都没有超过上限',
  );
}
