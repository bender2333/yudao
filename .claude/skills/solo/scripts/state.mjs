/**
 * solo — 账本（.ralph/<loop>/）的读写与解析。
 *
 * 账本只有两个可写位置：
 *   - 工作区里的 <root>/.ralph/active.json 与 <root>/.ralph/<loop>/
 *   - 没有别的地方。技能与脚本本身不写工作区的其它文件。
 *
 * 账本格式（v3，兼容 v2）：concurrency / taskState / escalation / worktrees /
 * scope / signature，v3 增加 self（本机 gh 登录名，用来区分「我刚开过工的单子」
 * 与「别人在做」）。
 */
import fs from 'node:fs';
import path from 'node:path';

export const LEDGER_DIR = '.ralph';

export const DEFAULT_CONCURRENCY = 4;
export const DEFAULT_EXCLUSIVE_LIMIT = 1;
export const DEFAULT_MAX_FAILS = 3;
export const DEFAULT_BRANCH_PREFIX = 'issue-';

/** 流程标签：同一时刻只带一个。流转时先全部摘掉，再加新的那个。 */
export const FLOW_LABELS = [
  'ready-for-agent',
  'in-progress',
  'needs-review',
  'needs-triage',
  'waiting',
  'ready-for-human',
];

/** 表示「这张单现在不派」的标签。in-progress / needs-review 不在这里：
 * 属于谁由 assignee 判断，见 solo.mjs 的 refresh。 */
export const PARKED_LABELS = ['needs-triage', 'waiting', 'ready-for-human'];

const CHECKBOX = /^[ \t]*[-*][ \t]*\[( |x|X|~|-)\][ \t]*(.*)$/;
const TABLE_ROW = /^[ \t]*\|[ \t]*([A-Za-z0-9._-]+)[ \t]*\|/;

export function readJson(file) {
  try {
    const raw = fs.readFileSync(file, 'utf8');
    const value = JSON.parse(raw.replace(/^\uFEFF/, ''));
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

export function num(value, fallback) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

export function str(value, fallback) {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

/**
 * 工作区解析：显式的 --workspace 优先，其次环境变量，最后当前目录。
 * （旧版把环境变量放在最前面，--workspace 写了也不生效。）
 */
export function resolveWorkspace(explicit) {
  if (explicit !== undefined && explicit !== null && String(explicit).trim()) {
    return path.resolve(String(explicit).trim());
  }
  const fromEnv = process.env.MINIMAX_PROJECT_DIR;
  if (typeof fromEnv === 'string' && fromEnv.trim()) return path.resolve(fromEnv.trim());
  return process.cwd();
}

/** 读出当前活动循环的全部路径。没有活动循环时返回 null。 */
export function loadLoop(workspace, forcedName) {
  const root = resolveWorkspace(workspace);
  const active = readJson(path.join(root, LEDGER_DIR, 'active.json'));
  const name = str(forcedName, '') || (active && typeof active.loop === 'string' ? active.loop.trim() : '');
  if (!name) return null;
  const dir = path.join(root, LEDGER_DIR, name);
  const state = readJson(path.join(dir, 'state.json'));
  return {
    root,
    dir,
    name,
    state,
    status: state && typeof state.status === 'string' ? state.status : 'unknown',
    stateFile: path.join(dir, 'state.json'),
    tasksFile: path.join(dir, 'tasks.md'),
    progressFile: path.join(dir, 'progress.md'),
    goalFile: path.join(dir, 'goal.md'),
    handoffFile: path.join(dir, 'handoff.md'),
    escalationDir: path.join(dir, 'escalations'),
    workersDir: path.join(dir, 'workers'),
    lockFile: path.join(dir, '.lock'),
  };
}

export function concurrencyOf(loop) {
  const c = (loop && loop.state && loop.state.concurrency) || {};
  return {
    max: Math.max(1, num(c.max, DEFAULT_CONCURRENCY)),
    exclusiveLimit: Math.max(0, num(c.exclusiveLimit, DEFAULT_EXCLUSIVE_LIMIT)),
    active: Array.isArray(c.active) ? c.active : [],
  };
}

export function escalationOf(loop) {
  const e = (loop && loop.state && loop.state.escalation) || {};
  return {
    maxFails: Math.max(1, num(e.maxFails, DEFAULT_MAX_FAILS)),
    label: str(e.label, 'needs-triage'),
    dropLabel: str(e.dropLabel, ''),
  };
}

export function worktreeOf(loop) {
  const w = (loop && loop.state && loop.state.worktrees) || {};
  return {
    root: str(w.root, ''),
    branchPrefix: str(w.branchPrefix, DEFAULT_BRANCH_PREFIX),
    base: str(w.base, 'origin/main'),
  };
}

export function taskStateOf(loop) {
  const s = (loop && loop.state && loop.state.taskState) || {};
  return s && typeof s === 'object' && !Array.isArray(s) ? s : {};
}

/** 解析 tasks.md：一条复选框一行；旧的表格行按已完成算。 */
export function parseTasksText(text) {
  const tasks = [];
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = raw.replace(/\s+$/, '');
    const box = CHECKBOX.exec(line);
    if (box) {
      const marker = box[1].toLowerCase();
      const body = box[2];
      const idMatch = /^([A-Za-z0-9._-]+)/.exec(body);
      const issueMatch = /#(\d+)/.exec(body);
      const waiting = /[（(][^）)]*(\bwaiting\b|等用户|等前提条件|中断)[^）)]*[)）]/i.test(body);
      const status = marker === 'x' ? 'done'
        : marker === '~' ? 'escalated'
          : waiting ? 'waiting'
            : 'pending';
      tasks.push({
        id: idMatch ? idMatch[1] : '',
        issue: issueMatch ? Number(issueMatch[1]) : null,
        status,
        blocked: waiting,
        exclusive: /touches-core|@exclusive/i.test(body),
        after: parseAfter(body),
        text: body,
        lineNo: index + 1,
        raw: line,
      });
      return;
    }
    const row = TABLE_ROW.exec(line);
    if (row && !/^[-.]+$/.test(row[1])) {
      tasks.push({
        id: row[1],
        issue: null,
        status: 'done',
        blocked: false,
        exclusive: false,
        after: [],
        text: line.trim(),
        lineNo: index + 1,
        raw: line,
      });
    }
  });
  return tasks;
}

export function parseTasks(loop) {
  try {
    return parseTasksText(fs.readFileSync(loop.tasksFile, 'utf8'));
  } catch {
    return [];
  }
}

/** 任务行里认得的依赖写法：(after T-030)、依赖 T-030、blocked by #42。 */
function parseAfter(body) {
  const ids = new Set();
  const patterns = [
    /\(\s*after\s+([^)]+)\)/gi,
    /（\s*after\s+([^)）]+)）/gi,
    /\bdepends on\s+([^)]+)/gi,
    /\bblocked by\s+([^,;)\]]+)/gi,
    /依赖\s+([^，,；;）)]+)/g,
  ];
  for (const re of patterns) {
    let m;
    while ((m = re.exec(body)) !== null) {
      for (const token of m[1].split(/[\s,;、]+/)) {
        const id = token.trim();
        if (/^[A-Za-z0-9._-]+$/.test(id)) ids.add(id);
      }
    }
  }
  return [...ids];
}

export function countPendingTasks(loop) {
  return parseTasks(loop).filter((t) => t.status === 'pending').length;
}

export function safeFileName(value) {
  const cleaned = String(value ?? '')
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^[.-]+/, '')
    .slice(0, 80);
  return cleaned || 'unknown';
}
