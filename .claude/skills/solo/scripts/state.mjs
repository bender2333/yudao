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
import { FLOW_LABELS, PARKED_LABELS, DEFAULT_BRANCH_PREFIX } from './lib/labels.mjs';
import { parseTasksText } from './lib/tasks-format.mjs';

export const LEDGER_DIR = '.ralph';

export const DEFAULT_CONCURRENCY = 4;
export const DEFAULT_EXCLUSIVE_LIMIT = 1;
export const DEFAULT_MAX_FAILS = 3;

// 标签与默认分支前缀归 lib/labels.mjs，这里只重新导出，外部的导入写法不变。
export { FLOW_LABELS, PARKED_LABELS, DEFAULT_BRANCH_PREFIX };
export { parseTasksText, parseAfter } from './lib/tasks-format.mjs';

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

export function parseTasks(loop) {
  try {
    return parseTasksText(fs.readFileSync(loop.tasksFile, 'utf8'));
  } catch {
    return [];
  }
}

export function countPendingTasks(loop) {
  return parseTasks(loop).filter((t) => t.status === 'pending').length;
}

/** 台账里还在的活：已经完成的单子不算（做法与 lib/report.mjs 的 live 过滤同一条）。 */
function liveTasks(tasks) {
  return (Array.isArray(tasks) ? tasks : []).filter((t) => t.status !== 'done');
}

function stateOf(taskState) {
  return taskState && typeof taskState === 'object' && !Array.isArray(taskState) ? taskState : {};
}

/**
 * 台账里等用户的单子：已经完成的单子不再算进去。
 * 台账里留着 waitFor=user 的旧标记（人早就把单子关了），印出来会让人以为还要处理。
 */
export function waitingOnUser(tasks, taskState) {
  const state = stateOf(taskState);
  return liveTasks(tasks)
    .filter((t) => state[t.id] && state[t.id].waitFor === 'user')
    .map((t) => t.id);
}

/** 失败中的单子：同样的口径，已经完成的单子不再算进去。 */
export function failingTasks(tasks, taskState) {
  const state = stateOf(taskState);
  return liveTasks(tasks)
    .filter((t) => state[t.id] && state[t.id].fails > 0)
    .map((t) => t.id + 'x' + state[t.id].fails);
}

export function safeFileName(value) {
  const cleaned = String(value ?? '')
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^[.-]+/, '')
    .slice(0, 80);
  return cleaned || 'unknown';
}
