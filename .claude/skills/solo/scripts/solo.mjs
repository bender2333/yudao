#!/usr/bin/env node
/**
 * solo — solo 模式的账本命令（技能正文见 ../SKILL.md，工人契约见 ../worker.md）。
 *
 * 账本是 .ralph/<loop>/ 下的五个文件：goal.md、tasks.md、progress.md、
 * handoff.md、state.json。所有改动都走这里的命令，不手改 JSON。
 *
 * 用法：
 *   node .claude/skills/solo/scripts/solo.mjs <命令> [选项]
 *
 *   state                                      一行摘要（轮次、计数、并发位置、失败中的任务）
 *   tasks [--json]                             任务清单
 *   next [--max N] [--dry-run]                 挑出可以派的任务
 *   refresh [--dry-run]                        按外部工单的真实状态刷新台账
 *   sync [--apply]                             按范围对账，报出台账漏掉的工单
 *   claim --task T-004 [--issue 41]            领取：assignee + 流程标签换成 in-progress
 *   worktree --task T-004 [--remove] [--force] 建 / 删这张任务的 worktree
 *   start --task T-004 [--session mvs_x]       记账：这张任务开始做了
 *   finish --task T-004 --status done|failed|blocked [--summary "..."] [--raw-file <文件>]
 *                                              收账；done 会先核对 PR 已合并、单子已关、检查全绿
 *   check --task T-004                         合并前的核对清单（工作区、推送、检查、交付说明、标签）
 *   escalate --task T-004 [--reason "..."] [--run]   连续三次没过：交回架构师
 *   question --task T-004 --comment-file <文件> [--run]  设计问题：提给架构师
 *   askhuman --task T-004 --comment-file <文件> [--run]  执行环境挡住：转给用户
 *   handover --task T-004                      重派前：上一次做到哪
 *   reap [--task T-004] [--stale 90]           回收停住的并发位置（子会话已经不在的那种）
 *   pause | resume                             停 / 开这个循环
 *   summary [--json]                           可以直接转给用户的总结
 *   note --text "..."                          本轮的补充说明（落到 notes/round-<n>.md）
 *   concurrency --max 4 --exclusive 1          并发上限
 *
 * 通用选项：--loop <名称>  --workspace <路径>  --json
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  LEDGER_DIR,
  FLOW_LABELS,
  PARKED_LABELS,
  readJson,
  writeJson,
  num,
  str,
  resolveWorkspace,
  loadLoop,
  concurrencyOf,
  escalationOf,
  worktreeOf,
  taskStateOf,
  parseTasks,
  parseTasksText,
  safeFileName,
} from './state.mjs';

const NOW = () => new Date().toISOString();
const CHECKBOX_LINE = /^([ \t]*[-*][ \t]*\[)( |x|X|~|-)(\])(.*)$/;

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      args._.push(token);
      continue;
    }
    const key = token.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) {
      args[key] = true;
    } else {
      args[key] = next;
      i += 1;
    }
  }
  return args;
}

/** 同步睡一会儿：GitHub 偶尔 TLS 握手超时，重试前等一等。 */
function sleepSync(ms) {
  try {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
  } catch {
    /* 不能睡就立刻重试 */
  }
}

function fail(message) {
  process.stderr.write(message + '\n');
  process.exit(1);
}

/* ------------------------------------------------------------------ ledger */

function openLedger(args) {
  const loop = loadLoop(args.workspace, args.loop);
  if (!loop) fail('没有活动的循环：' + path.join(resolveWorkspace(args.workspace), LEDGER_DIR, 'active.json') + ' 不存在或没有 loop 字段');
  if (!loop.state) fail('读不到账本：' + loop.stateFile);
  return loop;
}

function ensureSchema(loop) {
  const s = loop.state;
  const conc = concurrencyOf(loop);
  s.concurrency = { max: conc.max, exclusiveLimit: conc.exclusiveLimit, active: conc.active };
  const esc = escalationOf(loop);
  s.escalation = { maxFails: esc.maxFails, label: esc.label, dropLabel: esc.dropLabel };
  if (!s.taskState || typeof s.taskState !== 'object') s.taskState = {};
  const wt = worktreeOf(loop);
  s.worktrees = { root: wt.root, branchPrefix: wt.branchPrefix, base: wt.base };
  if (typeof s.signature !== 'string') s.signature = '';
  if (typeof s.self !== 'string') s.self = '';
  if (typeof s.autoContinue !== 'boolean') s.autoContinue = false;
  return s;
}

function saveLedger(loop) {
  ensureSchema(loop);
  loop.state.updatedAt = NOW();
  writeJson(loop.stateFile, loop.state);
}

/**
 * 账本锁：两个会话同时改同一个账本会把任务行写丢（历史上丢过 28 条）。
 * 用 .lock 的独占创建当锁，超过 10 分钟当成上一个进程已经死了。
 */
function acquireLock(loop) {
  try {
    fs.writeFileSync(loop.lockFile, JSON.stringify({ pid: process.pid, at: NOW() }), { flag: 'wx' });
    // fail() 走 process.exit，finally 不会执行：退出时一定把锁放掉，
    // 否则下一次调用会被自己的上一个进程挡住 10 分钟。
    process.on('exit', () => {
      try {
        fs.unlinkSync(loop.lockFile);
      } catch {
        /* 已经不在了 */
      }
    });
    return true;
  } catch (error) {
    if (error.code !== 'EEXIST') return false;
    const info = readJson(loop.lockFile);
    const at = info && info.at ? Date.parse(info.at) : 0;
    if (!at || Date.now() - at > 10 * 60 * 1000) {
      try {
        fs.unlinkSync(loop.lockFile);
      } catch {
        /* ignore */
      }
      try {
        fs.writeFileSync(loop.lockFile, JSON.stringify({ pid: process.pid, at: NOW() }), { flag: 'wx' });
        return true;
      } catch {
        /* fallthrough */
      }
    }
    fail('账本正被另一个会话写入（' + loop.lockFile + ' 还在）。等一会儿再试；确认没人在写就删掉这个文件。');
  }
}

function releaseLock(loop) {
  try {
    fs.unlinkSync(loop.lockFile);
  } catch {
    /* ignore */
  }
}

function withLock(loop, fn) {
  acquireLock(loop);
  try {
    return fn();
  } finally {
    releaseLock(loop);
  }
}

function repoRoot(loop) {
  const result = git(loop.root, ['rev-parse', '--show-toplevel']);
  if (result.status !== 0) fail('不是 git 仓库：' + loop.root);
  return result.stdout.trim();
}

function git(cwd, args) {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8', shell: false });
  return {
    status: result.status === null ? 1 : result.status,
    stdout: result.stdout || '',
    stderr: result.stderr || '',
  };
}

function gh(args, cwd) {
  const result = spawnSync('gh', args, { cwd, encoding: 'utf8', shell: false });
  return {
    status: result.status === null ? 1 : result.status,
    stdout: result.stdout || '',
    stderr: result.stderr || '',
  };
}

function ghJson(args, fallback, cwd) {
  const result = gh(args, cwd);
  if (result.status !== 0) return fallback;
  try {
    return JSON.parse(result.stdout || 'null') ?? fallback;
  } catch {
    return fallback;
  }
}

function detectRepo(loop) {
  const result = git(loop.root, ['remote', 'get-url', 'origin']);
  if (result.status !== 0) return '';
  const match = /github\.com[/:]([^/]+)\/([^/]+?)(?:\.git)?$/.exec(result.stdout.trim());
  return match ? match[1] + '/' + match[2] : '';
}

/** 本机的 gh 登录名。用来区分「我刚开过工的单子」与「别人在做」。 */
function selfLogin(loop) {
  const cached = str(loop.state.self, '');
  if (cached) return cached;
  const result = gh(['api', 'user', '--jq', '.login'], loop.root);
  if (result.status !== 0) return '';
  const login = result.stdout.trim();
  if (login) {
    loop.state.self = login;
    saveLedger(loop);
  }
  return login;
}
/* ------------------------------------------------------------ external data */

const ISSUE_FIELDS = `
  number
  state
  title
  updatedAt
  milestone { number title }
  labels(first: 30) { nodes { name } }
  assignees(first: 5) { nodes { login } }
  blockedBy(first: 20) { nodes { number state } }`;

/**
 * 仓库的全部开放工单（含标签、里程碑、负责人与原生 blockedBy）。
 * 一页 100 张；拉不全时返回 complete=false——把「没拉到」当成
 * 「外部已关」会悄悄缩短队列，所以调用方必须停下来。
 */
function fetchIssues(repo, maxPages = 8) {
  const parts = String(repo).split('/');
  const owner = parts[0];
  const name = parts[1];
  if (!owner || !name) return { issues: [], complete: false, pages: 0, lastError: '仓库名不对' };
  const issues = [];
  let cursor = null;
  let pages = 0;
  let complete = true;
  let lastError = '';
  for (let page = 0; page < maxPages; page += 1) {
    const after = cursor ? `, after: "${cursor}"` : '';
    const query = `query { repository(owner: "${owner}", name: "${name}") { issues(first: 100${after}, states: OPEN, orderBy: {field: UPDATED_AT, direction: DESC}) { pageInfo { hasNextPage endCursor } nodes {${ISSUE_FIELDS} } } } }`;
    let result;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      result = gh(['api', 'graphql', '-f', 'query=' + query], undefined);
      if (result.status === 0) break;
      if (attempt < 2) sleepSync(2000 * (attempt + 1));
    }
    if (result.status !== 0) {
      lastError = (result.stderr || result.stdout || '退出码 ' + result.status).trim().slice(0, 400);
      complete = false;
      break;
    }
    let payload;
    try {
      payload = JSON.parse(result.stdout || '{}');
    } catch (error) {
      lastError = '输出不是 JSON：' + error.message;
      complete = false;
      break;
    }
    if (payload.errors) {
      lastError = JSON.stringify(payload.errors).slice(0, 400);
      complete = false;
      break;
    }
    const block = payload && payload.data && payload.data.repository && payload.data.repository.issues;
    if (!block) {
      complete = false;
      lastError = '返回里没有 issues';
      break;
    }
    pages += 1;
    for (const node of block.nodes || []) {
      issues.push({
        number: node.number,
        state: node.state,
        title: node.title,
        updatedAt: node.updatedAt,
        milestone: node.milestone ? node.milestone.title : '',
        milestoneNumber: node.milestone ? node.milestone.number : 0,
        labels: ((node.labels && node.labels.nodes) || []).map((l) => l.name),
        assignees: ((node.assignees && node.assignees.nodes) || []).map((a) => a.login),
        blockedBy: ((node.blockedBy && node.blockedBy.nodes) || []).map((b) => ({ number: b.number, state: b.state })),
      });
    }
    if (!block.pageInfo || !block.pageInfo.hasNextPage) break;
    cursor = block.pageInfo.endCursor;
    if (page === maxPages - 1) {
      complete = false;
      lastError = '开放工单超过 ' + maxPages * 100 + ' 张，分页没有拉完';
    }
  }
  return { issues, complete, pages, lastError };
}

function openBlockers(issue) {
  return (issue.blockedBy || []).filter((b) => b.state === 'OPEN').map((b) => b.number);
}

/* ------------------------------------------------------------------- scope */

/** 里程碑：编号 → 标题。标题会改，编号不会；范围里只存编号。 */
function milestoneTitles(repo, ids) {
  if (!ids.length) return {};
  const list = ghJson(['api', 'repos/' + repo + '/milestones?state=all&per_page=100'], []);
  const map = {};
  for (const m of Array.isArray(list) ? list : []) map[m.number] = m.title;
  return map;
}

function splitList(value) {
  return String(value).split(',').map((s) => s.trim()).filter(Boolean);
}

/**
 * 范围是每轮重算的规则，不是拷进台账的一份名单：
 *   - 里程碑按编号认（改名不影响）；
 *   - 标签、标题前缀按并集算；
 *   - 一条都没配就是「所有开放工单」。
 * 用户说的里程碑标题在这里换成编号存下来；范围在下一轮还会重算，
 * 因为工单会进出里程碑。
 */
function scopeConfig(loop, args) {
  const repo = detectRepo(loop);
  const saved = loop.state.scope || {};
  let milestoneIds = Array.isArray(saved.milestoneIds) ? saved.milestoneIds.slice() : saved.milestoneId ? [saved.milestoneId] : [];
  let labels = Array.isArray(saved.labels) ? saved.labels.slice() : saved.label ? [saved.label] : [];
  let prefixes = Array.isArray(saved.prefixes) ? saved.prefixes.slice() : saved.prefix ? [saved.prefix] : [];
  let changed = false;

  if (args.all) {
    milestoneIds = [];
    labels = [];
    prefixes = [];
    changed = true;
  }
  if (args.milestone !== undefined) {
    milestoneIds = [];
    changed = true;
    for (const token of splitList(args.milestone)) {
      if (/^\d+$/.test(token)) {
        milestoneIds.push(Number(token));
        continue;
      }
      const list = ghJson(['api', 'repos/' + repo + '/milestones?state=all&per_page=100'], []);
      const all = Array.isArray(list) ? list : [];
      const exact = all.filter((m) => m.title === token);
      const loose = exact.length ? exact : all.filter((m) => m.title.includes(token));
      if (!loose.length) fail('找不到里程碑「' + token + '」。现有的：' + all.map((m) => m.number + ' ' + m.title).join(' / '));
      if (loose.length > 1) fail('里程碑「' + token + '」有多个候选：' + loose.map((m) => m.number + ' ' + m.title).join(' / ') + '，用编号指定');
      milestoneIds.push(loose[0].number);
    }
  }
  if (args.label !== undefined) {
    labels = splitList(args.label);
    changed = true;
  }
  if (args.prefix !== undefined) {
    prefixes = splitList(args.prefix);
    changed = true;
  }

  const titles = milestoneTitles(repo, milestoneIds);
  const scope = { milestoneIds, labels, prefixes, milestoneTitles: titles };
  if (changed) {
    loop.state.scope = scope;
    saveLedger(loop);
  }
  return scope;
}

function scopeLabel(scope) {
  const bits = [];
  if (scope.milestoneIds.length) {
    bits.push('里程碑 ' + scope.milestoneIds.map((id) => '#' + id + (scope.milestoneTitles[id] ? '（' + scope.milestoneTitles[id] + '）' : '')).join(' '));
  }
  if (scope.labels.length) bits.push('标签 ' + scope.labels.join('/'));
  if (scope.prefixes.length) bits.push('标题前缀 ' + scope.prefixes.join('/'));
  return bits.join('，') || '（全部开放工单）';
}

function inScopeOf(issue, scope) {
  if (!scope.milestoneIds.length && !scope.labels.length && !scope.prefixes.length) return true;
  if (scope.labels.some((l) => issue.labels.includes(l))) return true;
  if (scope.milestoneIds.includes(issue.milestoneNumber)) return true;
  if (scope.prefixes.some((p) => issue.title.startsWith(p))) return true;
  return false;
}

/** 台账行上的范围标记：离开范围时加上，回来时去掉，行本身保留。 */
const OUT_OF_SCOPE = '（不在范围）';

function inScopeAnnotated(task) {
  return /不在范围/.test(task.text);
}

/* -------------------------------------------------------------- tasks file */

/**
 * 改任务清单的唯一入口：整文件读、改、写，写之前比条数。
 * 条数变少说明有别的东西把行吃掉了——拒绝写入，留 .bak。
 */
function withTasksFile(loop, transform, force) {
  let before;
  try {
    before = fs.readFileSync(loop.tasksFile, 'utf8');
  } catch {
    return false;
  }
  const after = transform(before);
  if (after === before) return false;
  const beforeCount = parseTasksText(before).length;
  const afterCount = parseTasksText(after).length;
  if (afterCount < beforeCount && !force) {
    fail('拒绝写 tasks.md：任务条数从 ' + beforeCount + ' 降到 ' + afterCount + '（账本被截断的样子）。确认要缩短就加 --force。');
  }
  try {
    fs.writeFileSync(loop.tasksFile + '.bak', before, 'utf8');
  } catch {
    /* 备份失败不挡写入 */
  }
  fs.writeFileSync(loop.tasksFile, after, 'utf8');
  return true;
}

function mapTaskLine(text, id, fn) {
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i += 1) {
    const m = CHECKBOX_LINE.exec(lines[i]);
    if (!m) continue;
    const idMatch = /^([A-Za-z0-9._-]+)/.exec(m[4].trim());
    if (!idMatch || idMatch[1] !== id) continue;
    lines[i] = fn(m, lines[i]);
    return lines.join('\n');
  }
  return text;
}

function markTask(loop, id, marker, force) {
  return withTasksFile(loop, (text) => mapTaskLine(text, id, (m) => m[1] + marker + m[3] + m[4]), force);
}

function annotateTask(loop, id, marker, force) {
  return withTasksFile(loop, (text) => mapTaskLine(text, id, (m, line) => {
    if (line.includes(marker)) return line;
    if (marker.includes('waiting') && /[（(][^）)]*waiting[^）)]*[)）]/i.test(line)) return line;
    if (marker.includes('不在范围') && /不在范围/.test(line)) return line;
    return line + ' ' + marker;
  }), force);
}

function stripAnnotation(loop, id, marker, force) {
  return withTasksFile(loop, (text) => mapTaskLine(text, id, (m, line) => line.split(marker).join('').replace(/\s+$/, '')), force);
}

function recount(loop) {
  const tasks = parseTasks(loop);
  loop.state.pendingTasks = tasks.filter((t) => t.status === 'pending').length;
  loop.state.doneTasks = tasks.filter((t) => t.status === 'done').length;
  loop.state.totalTasks = tasks.length;
  return tasks;
}

function taskById(tasks, id) {
  return tasks.find((t) => t.id === id) || null;
}

function nextTaskId(tasks) {
  let max = 0;
  for (const t of tasks) {
    const m = /^T-(\d+)$/.exec(t.id);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return max + 1;
}

/** 新工单插到「互斥」或「并行」那一节的末尾；没有这两节就追加到文件末尾。 */
function insertTaskLine(loop, id, issue, exclusive, force) {
  return withTasksFile(loop, (text) => {
    const lines = text.split(/\r?\n/);
    const want = exclusive ? /互斥/ : /并行/;
    let start = -1;
    let end = lines.length;
    for (let i = 0; i < lines.length; i += 1) {
      if (!/^#{2,3}\s+/.test(lines[i])) continue;
      if (start === -1) {
        if (want.test(lines[i])) start = i;
        continue;
      }
      end = i;
      break;
    }
    const line = '- [ ] ' + id + ' #' + issue.number + ' ' + issue.title + (exclusive ? '（touches-core）' : '');
    if (start === -1) {
      while (lines.length && lines[lines.length - 1].trim() === '') lines.pop();
      lines.push('', line);
    } else {
      let at = end;
      while (at > start + 1 && lines[at - 1].trim() === '') at -= 1;
      lines.splice(at, 0, line);
    }
    return lines.join('\n');
  }, force);
}

/**
 * 范围对账：把新进入范围的外部工单收进台账，把离开范围的标出来。
 * 离开范围的工单不删行——它可能正在做；做完才算完。
 */
function reconcile(loop, scope, issues, args) {
  const activeIds = new Set(concurrencyOf(loop).active.map((a) => a.task));
  const byIssue = new Map();
  for (const task of parseTasks(loop)) {
    if (task.issue && !byIssue.has(task.issue)) byIssue.set(task.issue, task);
  }
  const added = [];
  let seq = nextTaskId(parseTasks(loop));
  for (const issue of issues) {
    if (!inScopeOf(issue, scope)) continue;
    if (byIssue.has(issue.number)) continue;
    const id = 'T-' + String(seq).padStart(3, '0');
    seq += 1;
    const exclusive = issue.labels.includes('touches-core');
    insertTaskLine(loop, id, issue, exclusive, args.force);
    added.push({ id, issue: issue.number, title: issue.title, exclusive });
    byIssue.set(issue.number, { id, status: 'pending', text: '' });
  }

  const left = [];
  const back = [];
  const openByNumber = new Map(issues.map((i) => [i.number, i]));
  for (const task of parseTasks(loop)) {
    if (!task.issue || task.status === 'done') continue;
    const issue = openByNumber.get(task.issue);
    if (!issue) continue;
    const inside = inScopeOf(issue, scope);
    const marked = inScopeAnnotated(task);
    if (!inside && !marked && !activeIds.has(task.id)) {
      annotateTask(loop, task.id, OUT_OF_SCOPE, args.force);
      left.push({ task: task.id, issue: task.issue });
    } else if (inside && marked) {
      stripAnnotation(loop, task.id, OUT_OF_SCOPE, args.force);
      back.push({ task: task.id, issue: task.issue });
    }
  }

  if (added.length || left.length || back.length) {
    recount(loop);
    saveLedger(loop);
    const lines = ['## 范围重算（编排者）', ''];
    for (const a of added) lines.push('- 收进台账 ' + a.id + '（#' + a.issue + '）' + (a.exclusive ? ' [互斥]' : '') + '：' + a.title);
    for (const l of left) lines.push('- 离开范围 ' + l.task + '（#' + l.issue + '）：不再派，台账保留');
    for (const b of back) lines.push('- 回到范围 ' + b.task + '（#' + b.issue + '）：重新可以派');
    appendText(loop, lines.join('\n'));
  }
  return { added, left, back };
}
/* ------------------------------------------------------------------ report */

function commandState(args) {
  const loop = openLedger(args);
  const tasks = parseTasks(loop);
  const conc = concurrencyOf(loop);
  const esc = escalationOf(loop);
  const state = taskStateOf(loop);
  const saved = loop.state.scope || {};
  const scope = {
    milestoneIds: saved.milestoneIds || (saved.milestoneId ? [saved.milestoneId] : []),
    labels: saved.labels || (saved.label ? [saved.label] : []),
    prefixes: saved.prefixes || (saved.prefix ? [saved.prefix] : []),
    milestoneTitles: saved.milestoneTitles || {},
  };
  const now = Date.now();
  const stalled = conc.active
    .map((a) => ({ task: a.task, issue: a.issue, minutes: Math.round((now - Date.parse(a.startedAt || 0)) / 60000) }))
    .filter((a) => a.minutes >= 90);
  const summary = {
    loop: loop.name,
    status: loop.state.status,
    iteration: num(loop.state.iteration, 0),
    maxIterations: num(loop.state.maxIterations, 0),
    doneTasks: tasks.filter((t) => t.status === 'done').length,
    pendingTasks: tasks.filter((t) => t.status === 'pending').length,
    waiting: tasks.filter((t) => t.status === 'waiting').length,
    escalated: tasks.filter((t) => t.status === 'escalated').length,
    outOfScope: tasks.filter((t) => t.status !== 'done' && inScopeAnnotated(t)).length,
    scope: Object.assign({ display: scopeLabel(scope) }, scope),
    concurrency: { max: conc.max, exclusiveLimit: conc.exclusiveLimit, active: conc.active.map((a) => a.task) },
    escalation: { maxFails: esc.maxFails, label: esc.label },
    autoContinue: loop.state.autoContinue === true,
    signature: str(loop.state.signature, ''),
    self: str(loop.state.self, ''),
    forUser: Object.keys(state).filter((id) => state[id] && state[id].waitFor === 'user'),
    failing: Object.keys(state).filter((id) => state[id] && state[id].fails > 0).map((id) => id + 'x' + state[id].fails),
    stalled,
  };
  if (args.json) return emit(args, summary);
  const lines = [
    'loop: ' + summary.loop + '   status: ' + summary.status + '   第 ' + summary.iteration + '/' + summary.maxIterations + ' 轮'
      + '   无人值守 ' + (summary.autoContinue ? '开' : '关'),
    '范围: ' + summary.scope.display,
    '任务: ' + summary.doneTasks + ' 完成 / ' + summary.pendingTasks + ' 待办 / ' + summary.waiting + ' 等条件 / ' + summary.escalated + ' 已交回'
      + (summary.outOfScope ? ' / ' + summary.outOfScope + ' 不在范围' : ''),
    '并发: 上限 ' + conc.max + '，互斥 ' + conc.exclusiveLimit + '，在跑 ' + (summary.concurrency.active.join(', ') || '-'),
    '通道: 连续 ' + esc.maxFails + ' 次没过 → ' + esc.label + '；署名 ' + (summary.signature || '(未设置)'),
  ];
  if (summary.self) lines.push('本机 gh: ' + summary.self);
  if (summary.forUser.length) lines.push('等用户: ' + summary.forUser.join(', '));
  if (summary.failing.length) lines.push('失败中: ' + summary.failing.join(', '));
  if (stalled.length) lines.push('可能停住的并发位置（先跑 reap）: ' + stalled.map((a) => a.task + ' ' + a.minutes + ' 分钟').join(', '));
  process.stdout.write(lines.join('\n') + '\n');
}

function commandTasks(args) {
  const loop = openLedger(args);
  const tasks = parseTasks(loop);
  if (args.json) return emit(args, tasks);
  const mark = { done: '[x]', escalated: '[~]', waiting: '[ ]', pending: '[ ]' };
  for (const t of tasks) {
    process.stdout.write(mark[t.status] + ' ' + t.id + ' ' + (t.issue ? '#' + t.issue + ' ' : '') + (t.exclusive ? '[互斥] ' : '')
      + (inScopeAnnotated(t) ? '[不在范围] ' : '') + t.text.replace(/^[A-Za-z0-9._-]+\s*/, '') + '\n');
  }
}

/* -------------------------------------------------------------------- next */

/** 并发上限是参数，不是手改的字段；用户可以在 /solo 里直接指定。 */
function applyConcurrency(loop, args) {
  const conc = concurrencyOf(loop);
  const max = args.concurrency !== undefined ? Math.max(1, num(args.concurrency, conc.max)) : conc.max;
  const exclusiveLimit = args.exclusive !== undefined ? Math.max(0, num(args.exclusive, conc.exclusiveLimit)) : conc.exclusiveLimit;
  const changed = max !== conc.max || exclusiveLimit !== conc.exclusiveLimit;
  if (changed) loop.state.concurrency = { max, exclusiveLimit, active: conc.active };
  return { max, exclusiveLimit, active: conc.active, changed };
}

function commandNext(args) {
  const loop = openLedger(args);
  return withLock(loop, () => {
    const repo = detectRepo(loop);
    if (!repo) fail('找不到外部仓库：origin 不是 GitHub 仓库');
    const scope = scopeConfig(loop, args);
    const conc = applyConcurrency(loop, args);
    if (conc.changed && !args['dry-run']) saveLedger(loop);
    const { issues, complete, lastError } = fetchIssues(repo);
    if (!complete) fail('外部工单没有拉全，这一轮先别派活：' + (lastError || '分页中断'));

    const reconciled = args['dry-run'] ? { added: [], left: [], back: [] } : reconcile(loop, scope, issues, args);
    const tasks = parseTasks(loop);
    const state = taskStateOf(loop);
    const activeIds = new Set(conc.active.map((a) => a.task));
    const doneIds = new Set(tasks.filter((t) => t.status === 'done').map((t) => t.id));
    const byIssue = new Map(issues.map((i) => [i.number, i]));
    const max = Math.max(0, num(args.max, conc.max));

    const candidates = tasks.filter((t) => {
      if (t.status !== 'pending') return false;
      if (activeIds.has(t.id)) return false;
      if (inScopeAnnotated(t)) return false;
      if (state[t.id] && state[t.id].escalated) return false;
      if (state[t.id] && state[t.id].external) return false;
      if (state[t.id] && state[t.id].blockedBy && state[t.id].blockedBy.length) return false;
      const issue = byIssue.get(t.issue);
      if (!issue) return false;
      if (issue.labels.some((l) => PARKED_LABELS.includes(l))) return false;
      return t.after.every((id) => doneIds.has(id));
    });

    const activeExclusive = conc.active.filter((a) => {
      const t = taskById(tasks, a.task);
      return t && t.exclusive;
    }).length;

    const picked = [];
    const pickedIssues = new Set();
    let exclusiveUsed = activeExclusive;
    for (const t of candidates) {
      if (picked.length >= max) break;
      if (t.issue && pickedIssues.has(t.issue)) continue;
      if (t.exclusive) {
        if (exclusiveUsed >= conc.exclusiveLimit) continue;
        exclusiveUsed += 1;
      }
      const target = worktreeTarget(loop, t);
      if (t.issue) pickedIssues.add(t.issue);
      picked.push({
        task: t.id,
        issue: t.issue,
        exclusive: t.exclusive,
        after: t.after,
        worktree: target.dir,
        branch: target.branch,
        text: t.text,
      });
    }

    if (args.json) return emit(args, { scope: scopeLabel(scope), reconciled, picked, concurrency: conc, remaining: candidates.length - picked.length });
    const lines = [
      '范围：' + scopeLabel(scope),
      '并发：上限 ' + conc.max + '，互斥 ' + conc.exclusiveLimit + '，在跑 ' + (conc.active.map((a) => a.task).join(', ') || '-'),
    ];
    if (reconciled.added.length) lines.push('收进台账 ' + reconciled.added.length + ' 张：' + reconciled.added.map((a) => a.id + '(#' + a.issue + ')').join(' '));
    if (reconciled.left.length) lines.push('离开范围 ' + reconciled.left.length + ' 张：' + reconciled.left.map((l) => l.task + '(#' + l.issue + ')').join(' '));
    if (reconciled.back.length) lines.push('回到范围 ' + reconciled.back.length + ' 张：' + reconciled.back.map((b) => b.task + '(#' + b.issue + ')').join(' '));
    if (!picked.length) {
      lines.push('没有可派的任务（依赖没满足、互斥已满、或者都做完了）');
    } else {
      for (const p of picked) {
        lines.push(p.task + '  ' + (p.issue ? '#' + p.issue : '') + '  ' + (p.exclusive ? '[互斥] ' : '') + p.worktree + '  '
          + p.text.replace(/^[A-Za-z0-9._-]+\s*/, '').replace(/^#\d+\s*/, ''));
      }
    }
    process.stdout.write(lines.join('\n') + '\n');
  });
}
/* ---------------------------------------------------------------- worktree */

function worktreeTarget(loop, task) {
  const cfg = worktreeOf(loop);
  const prefix = cfg.branchPrefix || 'issue-';
  const key = task.issue ? String(task.issue) : task.id;
  const branch = prefix + key;
  const root = cfg.root || defaultWorktreeRoot(loop);
  return { root, branch, dir: path.join(root, branch), base: cfg.base || 'origin/main' };
}

function defaultWorktreeRoot(loop) {
  const root = repoRoot(loop);
  return path.join(path.dirname(root), path.basename(root) + '-worktrees');
}

/** 删之前先看有没有没提交、没推送的东西：强删会把这些一起丢掉。 */
function worktreeResidue(dir, branch, base) {
  if (!fs.existsSync(dir)) return { dirty: 0, unpushed: 0 };
  const dirty = git(dir, ['status', '--porcelain']).stdout.split(/\r?\n/).filter(Boolean).length;
  const hasRemote = git(dir, ['rev-parse', '--verify', 'origin/' + branch]).status === 0;
  const range = (hasRemote ? 'origin/' + branch : base) + '..HEAD';
  const unpushed = num(git(dir, ['rev-list', '--count', range]).stdout.trim(), 0);
  return { dirty, unpushed };
}

function commandWorktree(args) {
  const loop = openLedger(args);
  const task = taskById(parseTasks(loop), args.task);
  if (!task) fail('任务清单里没有 ' + args.task);
  const target = worktreeTarget(loop, task);
  const root = repoRoot(loop);

  if (args.remove) {
    const residue = worktreeResidue(target.dir, target.branch, target.base);
    if ((residue.dirty || residue.unpushed) && !args.force) {
      fail('这张的 worktree 里还有未提交 ' + residue.dirty + ' 处、未推送 ' + residue.unpushed + ' 个提交。先跑 handover 看清楚，确认这些不要了再加 --force。');
    }
    git(root, ['worktree', 'remove', '--force', target.dir]);
    try {
      fs.rmSync(target.dir, { recursive: true, force: true });
    } catch {
      /* 目录被占用：下一次再删 */
    }
    git(root, ['worktree', 'prune']);
    const payload = { task: task.id, removed: target.dir, branch: target.branch, discarded: residue };
    return emit(args, payload, '删掉 worktree ' + target.dir + (residue.dirty || residue.unpushed ? '（丢弃未提交 ' + residue.dirty + ' 处、未推送 ' + residue.unpushed + ' 个提交）' : ''));
  }

  const listed = git(root, ['worktree', 'list', '--porcelain']).stdout;
  if (listed.split(/\r?\n/).some((line) => line.trim() === 'worktree ' + target.dir)) {
    return emit(args, { task: task.id, worktree: target.dir, branch: target.branch, created: false }, 'worktree 已经在：' + target.dir);
  }

  // main 一直在动：起点必须用最新的。
  const fetched = git(root, ['fetch', '--prune', 'origin']);
  if (fetched.status !== 0) process.stderr.write('fetch origin 失败（仍然用本地的 ' + target.base + '）：' + fetched.stderr.trim() + '\n');

  fs.mkdirSync(path.dirname(target.dir), { recursive: true });
  if (fs.existsSync(target.dir) && fs.readdirSync(target.dir).length === 0) fs.rmdirSync(target.dir);

  const localBranch = git(root, ['rev-parse', '--verify', 'refs/heads/' + target.branch]).status === 0;
  const remoteBranch = git(root, ['rev-parse', '--verify', 'refs/remotes/origin/' + target.branch]).status === 0;
  let addArgs;
  if (localBranch) addArgs = ['worktree', 'add', target.dir, target.branch];
  else if (remoteBranch) addArgs = ['worktree', 'add', target.dir, '-b', target.branch, 'origin/' + target.branch];
  else addArgs = ['worktree', 'add', target.dir, '-b', target.branch, target.base];
  const added = git(root, addArgs);
  if (added.status !== 0) fail('建 worktree 失败：' + (added.stderr.trim() || added.stdout.trim()));
  const payload = { task: task.id, worktree: target.dir, branch: target.branch, created: true, fromRemote: remoteBranch && !localBranch };
  return emit(args, payload, 'worktree ' + target.dir + '（分支 ' + target.branch + '）');
}

/* ------------------------------------------------------------------- claim */

/** 领取：assignee 归我，流程标签换成 in-progress（别的流程标签先摘掉）。 */
function commandClaim(args) {
  const loop = openLedger(args);
  const task = taskById(parseTasks(loop), args.task);
  if (!task) fail('任务清单里没有 ' + args.task);
  const issue = num(args.issue, task.issue || 0);
  if (!issue) fail('这张任务没有对应的工单号：加 --issue <编号>');

  const current = ghJson(['issue', 'view', String(issue), '--json', 'labels'], { labels: [] }, loop.root);
  const present = ((current && current.labels) || []).map((l) => l.name);
  const drop = FLOW_LABELS.filter((l) => present.includes(l) && l !== 'in-progress');
  const ghArgs = ['issue', 'edit', String(issue), '--add-assignee', '@me', '--add-label', 'in-progress'];
  if (drop.length) ghArgs.push('--remove-label', drop.join(','));
  const result = gh(ghArgs, loop.root);

  const state = taskStateOf(loop);
  state[task.id] = Object.assign({}, state[task.id] || {}, { claimedAt: NOW() });
  delete state[task.id].external;
  loop.state.taskState = state;
  saveLedger(loop);

  const warning = result.status === 0 ? '' : '领取没成功（台账记了，外部没变）：' + (result.stderr.trim() || result.stdout.trim());
  if (warning) process.stderr.write(warning + '\n');
  const payload = { task: task.id, issue, assigned: result.status === 0, dropped: drop, warning };
  return emit(args, payload, '#' + issue + ' 领取：' + (result.status === 0 ? '负责人 @me，标签 in-progress' : '失败，见上面的错误') + (drop.length ? '，摘掉 ' + drop.join(',') : ''));
}

/** 把子会话号记到正在跑的那张任务上：hook 靠它判断谁交卷了。 */
function commandAttach(args) {
  const loop = openLedger(args);
  return withLock(loop, () => {
    const session = str(args.session, '');
    if (!session) fail('要给子会话号：--session <id>');
    const conc = concurrencyOf(loop);
    const entry = conc.active.find((a) => a.task === args.task);
    if (!entry) fail(args.task + ' 不在并发位置上（先 start）');
    entry.session = session;
    loop.state.concurrency = { max: conc.max, exclusiveLimit: conc.exclusiveLimit, active: conc.active };
    saveLedger(loop);
    return emit(args, entry, entry.task + ' 记下子会话 ' + session);
  });
}

/* ------------------------------------------------------------------- start */

function commandStart(args) {
  const loop = openLedger(args);
  return withLock(loop, () => {
    const task = taskById(parseTasks(loop), args.task);
    if (!task) fail('任务清单里没有 ' + args.task);
    const conc = concurrencyOf(loop);
    if (conc.active.some((a) => a.task === task.id) && !args.force) {
      fail(task.id + ' 已经在并发位置上。要重派先 reap，或者加 --force 覆盖。');
    }
    if (!conc.active.length) {
      loop.state.iteration = num(loop.state.iteration, 0) + 1;
      loop.state.batchStartedAt = NOW();
      appendText(loop, '## 第 ' + loop.state.iteration + ' 轮（' + NOW().slice(0, 16).replace('T', ' ') + '）');
    }
    const target = worktreeTarget(loop, task);
    const entry = {
      task: task.id,
      issue: task.issue,
      session: str(args.session, ''),
      worktree: str(args.worktree, target.dir),
      branch: str(args.branch, target.branch),
      startedAt: NOW(),
      iteration: loop.state.iteration,
    };
    const body = fetchIssueBody(loop, task.issue);
    if (body !== null) entry.bodyHash = hashText(body);

    const state = taskStateOf(loop);
    state[task.id] = Object.assign({}, state[task.id] || {});
    delete state[task.id].interrupted;
    loop.state.taskState = state;

    conc.active = conc.active.filter((a) => a.task !== task.id);
    conc.active.push(entry);
    loop.state.concurrency = { max: conc.max, exclusiveLimit: conc.exclusiveLimit, active: conc.active };
    saveLedger(loop);
    appendText(loop, '- ' + task.id + (task.issue ? ' #' + task.issue : '') + ' 开派：' + entry.worktree + '（' + entry.branch + '）');
    return emit(args, entry, task.id + ' 开派：' + entry.worktree);
  });
}

function fetchIssueBody(loop, issueNumber) {
  if (!issueNumber) return null;
  const repo = detectRepo(loop);
  if (!repo) return null;
  const result = gh(['issue', 'view', String(issueNumber), '--repo', repo, '--json', 'body'], loop.root);
  if (result.status !== 0) return null;
  try {
    const parsed = JSON.parse(result.stdout || '{}');
    return typeof parsed.body === 'string' ? parsed.body : null;
  } catch {
    return null;
  }
}

function hashText(text) {
  return createHash('sha256').update(String(text || '')).digest('hex');
}

/* ------------------------------------------------------------------ finish */

/**
 * done 只能由证据产生：工单已关、PR 已合并、检查全绿。
 * 任何一条不成立就退出，不写 [x]——「工人说 done」不算完成。
 */
function verifyDone(loop, task) {
  const problems = [];
  const active = concurrencyOf(loop).active.find((a) => a.task === task.id);
  const branch = active && active.branch ? active.branch : 'issue-' + task.issue;

  const issue = ghJson(['issue', 'view', String(task.issue), '--json', 'state'], {}, loop.root);
  if (!issue || !issue.state) problems.push('读不到工单 #' + task.issue);
  else if (issue.state !== 'CLOSED') problems.push('工单 #' + task.issue + ' 还开着（' + issue.state + '）——Closes 没生效，或者还没合并');

  const prs = ghJson(['pr', 'list', '--head', branch, '--state', 'all', '--json', 'number,state,mergedAt'], [], loop.root);
  const list = Array.isArray(prs) ? prs : [];
  let pr = list.find((p) => p.state === 'MERGED') || list[0];
  if (!pr) {
    // 合并以后远端分支会被删掉，按 head 查就查不到了：改按正文里的 Closes 找。
    const found = ghJson(['pr', 'list', '--state', 'merged', '--search', '#' + task.issue + ' in:title,body', '--limit', '10', '--json', 'number,state,mergedAt,body'], [], loop.root);
    pr = (Array.isArray(found) ? found : []).find((p) => String(p.body || '').includes('Closes #' + task.issue));
  }
  if (!pr) {
    problems.push('分支 ' + branch + ' 没有 PR');
  } else if (pr.state !== 'MERGED') {
    problems.push('PR #' + pr.number + ' 还没合并（' + pr.state + '）');
  } else {
    const detail = ghJson(['pr', 'view', String(pr.number), '--json', 'statusCheckRollup'], {}, loop.root);
    const checks = ((detail && detail.statusCheckRollup) || []).filter((c) => c && c.conclusion);
    const bad = checks.filter((c) => !['SUCCESS', 'NEUTRAL', 'SKIPPED'].includes(c.conclusion));
    if (!checks.length) problems.push('PR #' + pr.number + ' 上没看到检查结果');
    else if (bad.length) problems.push('PR #' + pr.number + ' 的检查没全绿：' + bad.map((c) => (c.name || c.context || '检查') + ':' + c.conclusion).join(' '));
  }
  return problems;
}

function commandFinish(args) {
  const loop = openLedger(args);
  return withLock(loop, () => {
    const task = taskById(parseTasks(loop), args.task);
    if (!task) fail('任务清单里没有 ' + args.task);
    const status = str(args.status, 'failed');
    const raw = readRaw(args);
    const summary = str(args.summary, raw.summary);
    const files = str(args.files, raw.files || 'none');
    const next = str(args.next, raw.next || 'none');

    if (status === 'done' && task.issue && !args['no-verify']) {
      const problems = verifyDone(loop, task);
      if (problems.length) {
        process.stderr.write('这张还不能记完成：\n');
        for (const p of problems) process.stderr.write('  - ' + p + '\n');
        process.stderr.write('修好再收账。确实要跳过核对加 --no-verify（会在台账里留痕）。\n');
        process.exit(1);
      }
    }

    const state = taskStateOf(loop);
    const entry = state[task.id] || { fails: 0, escalated: false };
    entry.history = Array.isArray(entry.history) ? entry.history : [];
    entry.history.push({ at: NOW(), iteration: loop.state.iteration, status, summary: summary.slice(0, 400) });
    if (status === 'done') {
      entry.fails = 0;
      entry.done = true;
      entry.doneAt = NOW();
      if (args['no-verify']) entry.verified = false;
      markTask(loop, task.id, 'x', args.force);
    } else {
      entry.fails = num(entry.fails, 0) + 1;
      entry.lastStatus = status;
    }
    delete entry.interrupted;
    state[task.id] = entry;
    loop.state.taskState = state;

    const conc = concurrencyOf(loop);
    conc.active = conc.active.filter((a) => a.task !== task.id);
    loop.state.concurrency = { max: conc.max, exclusiveLimit: conc.exclusiveLimit, active: conc.active };
    loop.state.currentTask = task.id;

    recount(loop);
    saveLedger(loop);
    appendText(loop, [
      '### ' + task.id + (task.issue ? ' #' + task.issue : '') + ' — ' + status,
      '',
      '- 摘要：' + (summary || '（没写）'),
      '- 改动：' + files,
      '- 下一步：' + next,
    ].join('\n'));

    const esc = escalationOf(loop);
    const escalationRequired = status !== 'done' && entry.fails >= esc.maxFails && !entry.escalated;
    const payload = {
      task: task.id,
      status,
      fails: entry.fails,
      doneTasks: loop.state.doneTasks,
      pendingTasks: loop.state.pendingTasks,
      active: conc.active.map((a) => a.task),
      escalationRequired,
      escalation: escalationRequired ? { maxFails: esc.maxFails, label: esc.label, issue: task.issue } : null,
    };
    return emit(args, payload, task.id + ' 记 ' + status + '（失败 ' + entry.fails + ' 次，剩 ' + loop.state.pendingTasks + ' 张待办）'
      + (escalationRequired ? '\n连续 ' + esc.maxFails + ' 次没过：跑 escalate 交回架构师，别再试第四次。' : ''));
  });
}

function readRaw(args) {
  const out = { summary: '', files: '', next: '' };
  const file = str(args['raw-file'], '');
  if (!file) return out;
  let text;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch {
    return out;
  }
  const grab = (key) => {
    const m = new RegExp('^' + key + ':[ \\t]*(.*)$', 'mi').exec(text);
    return m ? m[1].trim() : '';
  };
  out.summary = grab('SUMMARY');
  out.files = grab('FILES');
  out.next = grab('NEXT');
  return out;
}
/* ------------------------------------------------------------------- check */

/** 合并前的核对：每条都要 ✓，有一条 ✗ 就不许合并。 */
function commandCheck(args) {
  const loop = openLedger(args);
  const task = taskById(parseTasks(loop), args.task);
  if (!task) fail('任务清单里没有 ' + args.task);
  const conc = concurrencyOf(loop);
  const active = conc.active.find((a) => a.task === task.id);
  const target = worktreeTarget(loop, task);
  const dir = active && active.worktree ? active.worktree : target.dir;
  const branch = active && active.branch ? active.branch : target.branch;
  if (!fs.existsSync(dir)) fail('worktree 不在：' + dir);

  const lines = [];
  const problems = [];
  const ok = (cond, text) => {
    lines.push((cond ? '✓ ' : '✗ ') + text);
    if (!cond) problems.push(text);
  };

  git(dir, ['fetch', 'origin', 'main']);
  ok(git(dir, ['status', '--porcelain']).stdout.trim() === '', '工作区没有未提交的改动');
  const hasRemote = git(dir, ['rev-parse', '--verify', 'origin/' + branch]).status === 0;
  const ahead = num(git(dir, ['rev-list', '--count', (hasRemote ? 'origin/' + branch : 'origin/main') + '..HEAD']).stdout.trim(), 0);
  ok(ahead === 0, '没有未推送的提交' + (ahead ? '（还有 ' + ahead + ' 个）' : ''));
  ok(git(dir, ['merge-base', '--is-ancestor', 'origin/main', 'HEAD']).status === 0, '分支已经包含 origin/main');

  const prs = ghJson(['pr', 'list', '--head', branch, '--state', 'all', '--json', 'number,state,mergeable,statusCheckRollup'], [], loop.root);
  const pr = (Array.isArray(prs) ? prs : []).find((p) => p.state === 'OPEN');
  ok(Boolean(pr), pr ? 'PR #' + pr.number + ' 开着' : '没有开着的 PR');
  if (pr) {
    ok(pr.mergeable !== 'CONFLICTING', 'PR 没有冲突' + (pr.mergeable ? '（' + pr.mergeable + '）' : ''));
    const checks = (pr.statusCheckRollup || []).filter((c) => c && c.conclusion);
    const bad = checks.filter((c) => !['SUCCESS', 'NEUTRAL', 'SKIPPED'].includes(c.conclusion));
    ok(checks.length > 0 && bad.length === 0, 'PR 的检查全绿' + (bad.length ? '（' + bad.map((c) => (c.name || c.context || '检查') + ':' + c.conclusion).join(' ') + '）' : ''));
    const detail = ghJson(['pr', 'view', String(pr.number), '--json', 'comments'], { comments: [] }, loop.root);
    const delivery = ((detail && detail.comments) || []).filter((c) => (c.body || '').trim().startsWith('DELIVERY:'));
    ok(delivery.length > 0, 'PR 上有 DELIVERY 交付说明');
    if (delivery.length) {
      const signature = str(loop.state.signature, '');
      const body = delivery[delivery.length - 1].body || '';
      ok(!signature || body.includes(signature), '交付说明最后一行有署名 ' + (signature || '(未设置)'));
    }
  }
  const signature = str(loop.state.signature, '');
  const headLines = git(dir, ['log', '-1', '--format=%B']).stdout.split(/\r?\n/).map((l) => l.trimEnd()).filter((l) => l.trim());
  const headTail = headLines.length ? headLines[headLines.length - 1].trim() : '';
  ok(!signature || headTail === '— ' + signature, '提交信息最后一行是署名' + (headTail ? '（实际：' + headTail + '）' : ''));
  if (task.issue) {
    const jour = path.join(dir, 'agents_jour', String(task.issue) + '.md');
    ok(fs.existsSync(jour), '有日记 agents_jour/' + task.issue + '.md');
    if (fs.existsSync(jour)) {
      const text = fs.readFileSync(jour, 'utf8');
      ok(!signature || text.includes(signature), '日记里有署名');
    }
    const issue = ghJson(['issue', 'view', String(task.issue), '--json', 'labels'], { labels: [] }, loop.root);
    ok(((issue && issue.labels) || []).some((l) => l.name === 'needs-review'), '工单标签是 needs-review');
  }
  if (pr) {
    const prDetail = ghJson(['pr', 'view', String(pr.number), '--json', 'body,number'], {}, loop.root);
    const prBody = (prDetail && prDetail.body) || '';
    ok(/Closes #\d+/.test(prBody), 'PR 正文有 Closes #<编号>');
    ok(prBody.includes('Solo:'), 'PR 正文有 Solo 那一行');
    ok(!signature || prBody.includes(signature), 'PR 正文有署名');
    if (task.text.includes('touches-core')) {
      const runs = ghJson(['run', 'list', '--workflow', 'CI', '--branch', branch, '--limit', '5', '--json', 'databaseId,conclusion,headSha'], [], loop.root);
      const green = (Array.isArray(runs) ? runs : []).filter((r) => r.conclusion === 'success');
      ok(green.length > 0, 'touches-core：分支上跑过集成层');
      const deliveryBody = (detail && detail.comments || []).filter((c) => (c.body || '').trim().startsWith('DELIVERY:')).pop();
      const linked = green.some((r) => deliveryBody && String(deliveryBody.body).includes(String(r.databaseId)));
      if (green.length) ok(linked, '交付说明里有集成层运行的链接');
    }
  }

  if (args.json) return emit(args, { task: task.id, ok: problems.length === 0, lines, problems });
  process.stdout.write(lines.join('\n') + '\n');
  if (problems.length) {
    process.stderr.write('还有 ' + problems.length + ' 条不满足，先别合并。\n');
    process.exit(1);
  }
}

/* --------------------------------------------------------------- channels */

function readBody(args, what) {
  let body = str(args.text, '');
  const file = str(args['comment-file'], '');
  if (!body && file) {
    try {
      body = fs.readFileSync(file, 'utf8').trim();
    } catch {
      fail('读不到评论文件：' + file);
    }
  }
  if (!body) fail('要写清' + what + '：--comment-file <文件> 或 --text "..."');
  return body;
}

function signedBody(loop, body) {
  const signature = str(loop.state.signature, '');
  return signature ? body + '\n\n— ' + signature + '\n' : body + '\n';
}

/** 流程标签同一时刻只带一个：先摘掉其它流程标签，再加目标标签。 */
function relabel(loop, issue, addLabel) {
  const current = ghJson(['issue', 'view', String(issue), '--json', 'labels'], { labels: [] }, loop.root);
  const present = ((current && current.labels) || []).map((l) => l.name);
  const drop = FLOW_LABELS.filter((l) => present.includes(l) && l !== addLabel);
  const ghArgs = ['issue', 'edit', String(issue), '--add-label', addLabel];
  if (drop.length) ghArgs.push('--remove-label', drop.join(','));
  const result = gh(ghArgs, loop.root);
  return { ok: result.status === 0, dropped: drop, error: result.stderr.trim() };
}

function writeEscalationFile(loop, task, kind, text) {
  fs.mkdirSync(loop.escalationDir, { recursive: true });
  const file = path.join(loop.escalationDir, task.id + '-' + kind + '.md');
  fs.writeFileSync(file, text, 'utf8');
  return file;
}

function clearActive(loop, taskId) {
  const conc = concurrencyOf(loop);
  conc.active = conc.active.filter((a) => a.task !== taskId);
  loop.state.concurrency = { max: conc.max, exclusiveLimit: conc.exclusiveLimit, active: conc.active };
}

/** 三条通道共用：把任务从候选里拿掉、摘牌换牌、把说明发到工单上。 */
function handOff(args, kind) {
  const loop = openLedger(args);
  return withLock(loop, () => {
    const task = taskById(parseTasks(loop), args.task);
    if (!task) fail('任务清单里没有 ' + args.task);
    const issue = num(args.issue, task.issue || 0);
    const state = taskStateOf(loop);
    const entry = state[task.id] || { fails: 0 };
    const label = kind === 'askhuman' ? 'ready-for-human' : escalationOf(loop).label;

    let body;
    if (kind === 'escalate') {
      const reason = str(args.reason, '要架构师定下一步怎么做');
      const history = (entry.history || []).filter((h) => h.status !== 'done').slice(-3);
      const lines = [
        '## 需要架构师接手：' + task.id + (issue ? ' #' + issue : ''),
        '',
        '这张单连续 ' + (entry.fails || 0) + ' 次没有通过，循环停止自动重试。',
        '',
        '**卡在哪**：' + reason,
        '',
        '**这几次的结果**：',
      ];
      for (const h of history) lines.push('- 第 ' + h.iteration + ' 轮 ' + h.status + '：' + h.summary);
      lines.push('', '**需要谁决定**：架构师（拆工单、改写规格，或者给出下一步做法）');
      body = lines.join('\n');
    } else {
      body = readBody(args, kind === 'askhuman' ? '被挡住的是哪一步、需要什么' : '要架构师定什么');
    }
    const text = signedBody(loop, body);
    const file = writeEscalationFile(loop, task, kind, text);

    if (kind === 'askhuman') {
      entry.waitFor = 'user';
      entry.askedAt = NOW();
      annotateTask(loop, task.id, '（等用户）', args.force);
    } else {
      entry.escalated = true;
      entry.escalatedAt = NOW();
      entry.kind = kind;
      entry.reason = body.slice(0, 400);
      markTask(loop, task.id, '~', args.force);
    }
    state[task.id] = entry;
    loop.state.taskState = state;
    clearActive(loop, task.id);
    recount(loop);
    saveLedger(loop);

    const relabeled = { ok: false, dropped: [], error: '没有工单号' };
    if (issue) {
      const result = relabel(loop, issue, label);
      relabeled.ok = result.ok;
      relabeled.dropped = result.dropped;
      relabeled.error = result.error;
      const posted = gh(['issue', 'comment', String(issue), '--body-file', file], loop.root);
      if (posted.status !== 0) process.stderr.write('评论没发上去：' + posted.stderr.trim() + '\n');
    }

    const head = kind === 'escalate' ? '连续失败交回架构师' : kind === 'question' ? '设计问题提给架构师' : '执行环境挡住，转给用户';
    const signature = str(loop.state.signature, '');
    appendText(loop, ['### ' + task.id + (issue ? ' #' + issue : '') + ' — ' + head, '', body, signature ? '— ' + signature : ''].join('\n'));

    const payload = { task: task.id, issue: issue || null, label, commentFile: file, relabeled, signature };
    return emit(args, payload, task.id + (issue ? ' #' + issue : '') + ' → ' + label + (relabeled.ok ? '（标签已换）' : '（标签没换成，见上面的错误）'));
  });
}
/* ----------------------------------------------------------------- refresh */

/**
 * 台账跟外部工单对齐：关掉的标完成，交回的标 [~]，等条件的标 waiting，
 * 别人领走的记成 external。
 *
 * 关键一条：solo 里没有「别人」，只有「别人领走」和「我们自己的单子」。
 * 工单带 in-progress / needs-review、负责人是我或者没人——这是我们自己
 * 上一轮没来得及收账的单子，下一轮要能重新派它，不能当成别人的。
 */
function commandRefresh(args) {
  const loop = openLedger(args);
  return withLock(loop, () => {
    const repo = detectRepo(loop);
    if (!repo) fail('找不到外部仓库：origin 不是 GitHub 仓库');
    const self = selfLogin(loop);
    const { issues, complete, lastError } = fetchIssues(repo);
    if (!complete) fail('外部工单没有拉全，这一轮不动台账：' + (lastError || '分页中断'));

    const byNumber = new Map(issues.map((i) => [i.number, i]));
    const state = taskStateOf(loop);
    const conc = concurrencyOf(loop);
    const activeByTask = new Map(conc.active.map((a) => [a.task, a]));
    const changes = [];
    let ready = 0;

    for (const task of parseTasks(loop)) {
      if (!task.issue || task.status === 'done') continue;
      const issue = byNumber.get(task.issue);
      if (!issue) {
        changes.push({ task: task.id, issue: task.issue, to: 'missing', note: '外部找不到这张单（关了或者转走了）' });
        continue;
      }
      if (issue.state === 'CLOSED') {
        markTask(loop, task.id, 'x', args.force);
        state[task.id] = Object.assign({}, state[task.id] || {}, { done: true, closedOutside: true, doneAt: NOW() });
        changes.push({ task: task.id, issue: task.issue, to: 'done', note: '外部已关闭，台账标完成' });
        continue;
      }

      const active = activeByTask.get(task.id);
      if (active && active.bodyHash) {
        const body = fetchIssueBody(loop, task.issue);
        if (body !== null && hashText(body) !== active.bodyHash) {
          changes.push({ task: task.id, issue: task.issue, to: 'changed', note: '工单正文在工作中被改过——让工人按新正文重核' });
        }
      }

      if (task.status === 'escalated' || task.status === 'waiting') {
        if (issue.labels.includes('ready-for-agent')) {
          markTask(loop, task.id, ' ', args.force);
          stripAnnotation(loop, task.id, '（等用户）', args.force);
          stripAnnotation(loop, task.id, '（waiting）', args.force);
          state[task.id] = Object.assign({}, state[task.id] || {}, { fails: 0 });
          delete state[task.id].escalated;
          delete state[task.id].waitFor;
          delete state[task.id].kind;
          changes.push({ task: task.id, issue: task.issue, to: 'free', note: '外部处理完，放回可派' });
          ready += 1;
        } else {
          changes.push({
            task: task.id,
            issue: task.issue,
            to: task.status,
            note: task.status === 'escalated' ? '仍等架构师' : '仍等前提条件',
          });
        }
        continue;
      }

      const owner = (issue.assignees || [])[0] || '';
      const ours = !owner || (Boolean(self) && owner === self);
      if (issue.labels.includes('in-progress') || issue.labels.includes('needs-review')) {
        const label = issue.labels.includes('in-progress') ? 'in-progress' : 'needs-review';
        if (active) {
          changes.push({ task: task.id, issue: task.issue, to: 'running', note: '本轮在跑（' + label + '）' });
          continue;
        }
        if (!ours) {
          state[task.id] = Object.assign({}, state[task.id] || {}, { external: { label, owner, at: NOW() } });
          changes.push({ task: task.id, issue: task.issue, to: 'claimed', note: '别人在做（' + label + '，' + owner + '）' });
          continue;
        }
        if (state[task.id]) delete state[task.id].external;
        changes.push({ task: task.id, issue: task.issue, to: 'resume', note: '我们自己的单子停在 ' + label + '（上一轮被中断或没收账），可以接着做' });
        ready += 1;
        continue;
      }

      if (issue.labels.includes('needs-triage')) {
        markTask(loop, task.id, '~', args.force);
        state[task.id] = Object.assign({}, state[task.id] || {}, { escalated: true, escalatedAt: NOW() });
        changes.push({ task: task.id, issue: task.issue, to: 'escalated', note: '已交回架构师' });
        continue;
      }
      if (issue.labels.includes('ready-for-human')) {
        annotateTask(loop, task.id, '（等用户）', args.force);
        state[task.id] = Object.assign({}, state[task.id] || {}, { waitFor: 'user' });
        changes.push({ task: task.id, issue: task.issue, to: 'waiting', note: '等用户处理' });
        continue;
      }
      if (issue.labels.includes('waiting')) {
        annotateTask(loop, task.id, '（waiting）', args.force);
        changes.push({ task: task.id, issue: task.issue, to: 'waiting', note: '等前提条件' });
        continue;
      }
      if (issue.labels.includes('ready-for-agent')) {
        if (state[task.id]) delete state[task.id].external;
        const blockers = openBlockers(issue);
        if (blockers.length) {
          state[task.id] = Object.assign({}, state[task.id] || {}, { blockedBy: blockers });
          changes.push({ task: task.id, issue: task.issue, to: 'blocked', note: '被 #' + blockers.join(' #') + ' 挡着' });
          continue;
        }
        if (state[task.id] && state[task.id].blockedBy) {
          delete state[task.id].blockedBy;
          changes.push({ task: task.id, issue: task.issue, to: 'free', note: '外部依赖已完成' });
        }
        ready += 1;
        continue;
      }
      changes.push({ task: task.id, issue: task.issue, to: 'unknown', note: '标签不在可派范围：' + (issue.labels.join(',') || '无') });
    }

    loop.state.taskState = state;
    recount(loop);
    saveLedger(loop);

    const notable = changes.filter((c) => ['done', 'claimed', 'resume', 'changed', 'missing', 'unknown', 'free'].includes(c.to));
    if (notable.length) appendText(loop, ['## 刷新外部状态（编排者）', ''].concat(notable.map((c) => '- ' + c.task + ' #' + c.issue + '：' + c.note)).join('\n'));
    const summary = {
      checked: changes.length,
      ready,
      done: changes.filter((c) => c.to === 'done').length,
      escalated: changes.filter((c) => c.to === 'escalated').length,
      waiting: changes.filter((c) => c.to === 'waiting').length,
      claimed: changes.filter((c) => c.to === 'claimed').length,
      resume: changes.filter((c) => c.to === 'resume').length,
      free: changes.filter((c) => c.to === 'free').length,
      changed: changes.filter((c) => c.to === 'changed').length,
      missing: changes.filter((c) => c.to === 'missing').length,
      unknown: changes.filter((c) => c.to === 'unknown').length,
      changes,
    };
    if (args.json) return emit(args, summary);
    const lines = [
      '刷新 ' + summary.checked + ' 张：可派 ' + summary.ready + '、关闭 ' + summary.done + '、别人在做 ' + summary.claimed
        + '、我们待续 ' + summary.resume + '、等条件 ' + summary.waiting + '、正文被改 ' + summary.changed
        + '、找不到 ' + summary.missing + '、标签不认识 ' + summary.unknown,
    ];
    for (const c of changes) lines.push(c.task + ' #' + c.issue + '  ' + c.note);
    process.stdout.write(lines.join('\n') + '\n');
    return summary;
  });
}

/* -------------------------------------------------------------------- sync */

/** 只报告：范围里有什么是台账没有的、台账里有什么已经不成立。 */
function commandSync(args) {
  const loop = openLedger(args);
  return withLock(loop, () => {
    const repo = detectRepo(loop);
    if (!repo) fail('找不到外部仓库：origin 不是 GitHub 仓库');
    const scope = scopeConfig(loop, args);
    const { issues, complete, lastError } = fetchIssues(repo);
    if (!complete) fail('外部工单没有拉全，先别对账：' + (lastError || '分页中断'));

    const inScope = issues.filter((i) => inScopeOf(i, scope));
    const tasks = parseTasks(loop);
    const byIssue = new Map();
    for (const t of tasks) {
      if (!t.issue) continue;
      if (!byIssue.has(t.issue)) byIssue.set(t.issue, []);
      byIssue.get(t.issue).push(t);
    }

    const missing = [];
    const stale = [];
    const mismatched = [];
    const outOfScope = [];
    const closedOutside = [];
    for (const issue of inScope) {
      const rows = byIssue.get(issue.number);
      if (!rows || !rows.length) {
        missing.push(issue);
        continue;
      }
      const open = rows.filter((t) => t.status !== 'done');
      if (!open.length) {
        stale.push({ number: issue.number, note: '台账标着完成，外部还开着' });
        continue;
      }
      const triage = issue.labels.find((l) => ['needs-triage', 'needs-review', 'in-progress', 'waiting', 'ready-for-human'].includes(l));
      if (!triage) continue;
      const consistent = open.some((t) => {
        if (t.status === 'escalated') return triage === 'needs-triage';
        if (t.status === 'waiting') return triage === 'waiting' || triage === 'ready-for-human';
        return triage === 'in-progress' || triage === 'needs-review';
      });
      if (!consistent) mismatched.push({ number: issue.number, label: triage });
    }
    for (const t of tasks) {
      if (!t.issue || t.status === 'done') continue;
      const issue = issues.find((i) => i.number === t.issue);
      if (!issue) {
        closedOutside.push({ task: t.id, issue: t.issue });
        continue;
      }
      if (!inScopeOf(issue, scope) && !inScopeAnnotated(t)) outOfScope.push({ task: t.id, issue: t.issue });
    }

    const summary = {
      scope: scopeLabel(scope),
      external: inScope.length,
      inLedger: inScope.filter((i) => byIssue.has(i.number)).length,
      missing: missing.map((i) => ({ number: i.number, title: i.title })),
      stale,
      mismatched,
      outOfScope,
      closedOutside,
    };
    if (args.apply) summary.applied = reconcile(loop, scope, issues, args);
    if (args.json) return emit(args, summary);

    const lines = [
      '范围：' + summary.scope,
      '外部 ' + summary.external + ' 张，台账里有 ' + summary.inLedger + ' 张（工单会进出范围，每轮都要重新对）',
    ];
    if (missing.length) {
      lines.push('① 台账里没有的 ' + missing.length + ' 张（下一轮 next 会收进台账）：');
      for (const m of missing) lines.push('   #' + m.number + ' ' + m.title);
    }
    if (stale.length) lines.push('② 台账标着完成、外部还开着 ' + stale.length + ' 张：' + stale.map((s) => '#' + s.number).join(' '));
    if (mismatched.length) lines.push('③ 标签与台账不一致 ' + mismatched.length + ' 张：' + mismatched.map((m) => '#' + m.number + '(' + m.label + ')').join(' '));
    if (outOfScope.length) lines.push('④ 台账里有、已经在范围外 ' + outOfScope.length + ' 张：' + outOfScope.map((o) => o.task + '(#' + o.issue + ')').join(' '));
    if (closedOutside.length) lines.push('⑤ 外部已关、台账还开着 ' + closedOutside.length + ' 张：' + closedOutside.map((c) => c.task + '(#' + c.issue + ')').join(' '));
    if (!missing.length && !stale.length && !mismatched.length && !outOfScope.length && !closedOutside.length) lines.push('台账与外部一致 ✓');
    process.stdout.write(lines.join('\n') + '\n');
    return summary;
  });
}

/* ---------------------------------------------------------------- handover */

function commandHandover(args) {
  const loop = openLedger(args);
  const task = taskById(parseTasks(loop), args.task);
  if (!task) fail('任务清单里没有 ' + args.task);
  const repo = detectRepo(loop);
  const conc = concurrencyOf(loop);
  const active = conc.active.find((a) => a.task === task.id);
  const branch = active && active.branch ? active.branch : 'issue-' + task.issue;
  const root = repoRoot(loop);
  const state = taskStateOf(loop)[task.id] || {};
  const lines = ['任务 ' + task.id + (task.issue ? '（工单 #' + task.issue + '）' : '') + '：' + task.text];
  lines.push('台账：' + (task.status === 'done' ? '已完成' : task.status === 'escalated' ? '已交回' : '待办')
    + '，失败 ' + (state.fails || 0) + ' 次' + (state.interrupted ? '，上一轮被中断（' + state.interrupted.at + '）' : ''));

  git(root, ['fetch', '--prune', 'origin']);
  const commits = git(root, ['log', '--oneline', 'origin/main..origin/' + branch]);
  if (commits.status === 0 && commits.stdout.trim()) {
    const list = commits.stdout.split(/\r?\n/).filter(Boolean);
    lines.push('远端分支 ' + branch + '：比 main 多 ' + list.length + ' 个提交');
    for (const c of list.slice(0, 8)) lines.push('   ' + c);
  } else {
    lines.push('远端分支 ' + branch + '：还没有');
  }

  const dir = active && active.worktree ? active.worktree : worktreeTarget(loop, task).dir;
  if (fs.existsSync(dir)) {
    const dirty = git(dir, ['status', '--porcelain']).stdout.split(/\r?\n/).filter(Boolean);
    lines.push('worktree ' + dir + '：未提交 ' + dirty.length + ' 处' + (dirty.length ? '（' + dirty.slice(0, 5).join('、') + '）' : ''));
    const gitDir = git(dir, ['rev-parse', '--absolute-git-dir']).stdout.trim();
    if (gitDir && fs.existsSync(path.join(gitDir, 'MERGE_HEAD'))) lines.push('⚠ 这个 worktree 里有一次没解决的 merge');
  } else {
    lines.push('worktree ' + dir + '：不在了');
  }

  if (task.issue && repo) {
    const prs = ghJson(['pr', 'list', '--repo', repo, '--head', branch, '--state', 'all', '--json', 'number,state,mergeable,statusCheckRollup'], [], loop.root);
    if (Array.isArray(prs) && prs.length) {
      for (const p of prs) {
        const checks = (p.statusCheckRollup || []).filter((c) => c.conclusion).map((c) => (c.name || c.context) + ':' + c.conclusion);
        lines.push('PR #' + p.number + ' ' + p.state + (p.mergeable && p.mergeable !== 'UNKNOWN' ? '（' + p.mergeable + '）' : '') + (checks.length ? ' 检查：' + checks.join(' ') : ''));
      }
    } else {
      lines.push('PR：没有');
    }
    const issue = ghJson(['issue', 'view', String(task.issue), '--repo', repo, '--json', 'state,labels,assignees'], null, loop.root);
    if (issue) {
      lines.push('工单 #' + task.issue + '：' + issue.state + '，标签 [' + ((issue.labels || []).map((l) => l.name).join(',')) + ']，负责人 '
        + (((issue.assignees || []).map((a) => a.login).join(',')) || '无'));
    }
  }
  lines.push('（把这段贴进新工人的任务书：上一轮做到哪、还差什么）');
  if (args.json) return emit(args, { task: task.id, lines });
  process.stdout.write(lines.join('\n') + '\n');
}

/* -------------------------------------------------------------------- reap */

/**
 * 回收停住的并发位置：子会话已经不在了，账本上还占着名额。
 * 回收不丢信息——handover 仍然能看到分支与 worktree 的状态。
 */
function commandReap(args) {
  const loop = openLedger(args);
  return withLock(loop, () => {
    const conc = concurrencyOf(loop);
    const staleMin = Math.max(1, num(args.stale, 90));
    const state = taskStateOf(loop);
    const reaped = [];
    for (const entry of conc.active.slice()) {
      if (args.task && args.task !== entry.task) continue;
      const minutes = Math.round((Date.now() - Date.parse(entry.startedAt || 0)) / 60000);
      if (!args.task && !(minutes >= staleMin)) continue;
      state[entry.task] = Object.assign({}, state[entry.task] || {}, {
        interrupted: { at: NOW(), session: entry.session || '', startedAt: entry.startedAt || '', minutes },
      });
      reaped.push({ task: entry.task, issue: entry.issue, session: entry.session || '', minutes });
    }
    loop.state.taskState = state;
    const remaining = conc.active.filter((a) => !reaped.some((r) => r.task === a.task));
    loop.state.concurrency = { max: conc.max, exclusiveLimit: conc.exclusiveLimit, active: remaining };
    saveLedger(loop);

    if (!reaped.length) {
      if (args.json) return emit(args, { reaped: [] });
      process.stdout.write('没有需要回收的并发位置。\n');
      return { reaped: [] };
    }
    appendText(loop, ['## 回收停住的并发位置（编排者）', ''].concat(reaped.map((r) => '- ' + r.task + (r.issue ? ' #' + r.issue : '')
      + '：开派后 ' + r.minutes + ' 分钟，子会话 ' + (r.session || '(未记)') + ' 已经不在了')).join('\n'));
    if (args.json) return emit(args, { reaped });
    process.stdout.write('回收 ' + reaped.length + ' 个位置：' + reaped.map((r) => r.task).join(', ') + '\n');
    process.stdout.write('重派以前先跑 handover --task <编号>，把「上一次做到哪」写进新任务书。\n');
    return { reaped };
  });
}

/* --------------------------------------------------------- pause and resume */

function commandPause(args) {
  const loop = openLedger(args);
  loop.state.status = 'paused';
  loop.state.autoContinue = false;
  saveLedger(loop);
  appendText(loop, '## 循环暂停（编排者，' + NOW().slice(0, 16).replace('T', ' ') + '）');
  return emit(args, { loop: loop.name, status: 'paused', autoContinue: false }, '循环 ' + loop.name + ' 已暂停（无人值守也停了）。');
}

function commandResume(args) {
  const loop = openLedger(args);
  loop.state.status = 'running';
  loop.state.autoContinue = !args['no-auto'];
  saveLedger(loop);
  appendText(loop, '## 循环恢复（编排者，' + NOW().slice(0, 16).replace('T', ' ') + '）\n\n- 无人值守：' + (loop.state.autoContinue ? '开' : '关'));
  return emit(args, { loop: loop.name, status: 'running', autoContinue: loop.state.autoContinue },
    '循环 ' + loop.name + ' 恢复（无人值守' + (loop.state.autoContinue ? '开' : '关') + '）。先跑 refresh 与 sync 再看台账。');
}

/** 署名：六处产出都用它（提交末行、PR 正文末行、每条评论末行、交付说明末行、日记行首、变更记录行首）。 */
function commandSignature(args) {
  const loop = openLedger(args);
  const before = str(loop.state.signature, '');
  const value = str(args.value, '');
  if (!value) {
    if (args.json) return emit(args, { signature: before });
    process.stdout.write('当前署名：' + (before || '(未设置)') + '\n');
    return before;
  }
  if (!/^solo-[A-Za-z0-9._-]+$/.test(value)) fail('署名要是 solo-<模型 ID> 的形式（例如 solo-deepseek-v4.1-flash）');
  loop.state.signature = value;
  saveLedger(loop);
  appendText(loop, '## 署名（编排者）\n\n- ' + (before || '(空)') + ' → ' + value);
  return emit(args, { signature: value }, '署名：' + before + ' → ' + value);
}

/** 预算：无人值守跑多少轮以内。用完就停，这是唯一的花钱闸。 */
function commandBudget(args) {
  const loop = openLedger(args);
  const current = num(loop.state.maxIterations, 0);
  const target = args.iterations !== undefined ? Math.max(1, num(args.iterations, current)) : current;
  loop.state.maxIterations = target;
  saveLedger(loop);
  appendText(loop, '## 预算（编排者）\n\n- maxIterations ' + current + ' → ' + target);
  return emit(args, { maxIterations: target }, '预算：最多 ' + target + ' 轮（已跑 ' + num(loop.state.iteration, 0) + ' 轮）');
}

/** 无人值守开关：开的时候 Stop hook 会在轮次结束时把会话叫回来接着跑。 */
function commandAuto(args) {
  const loop = openLedger(args);
  const value = str(args._[1], 'on');
  loop.state.autoContinue = value !== 'off' && value !== 'false';
  if (loop.state.autoContinue) loop.state.status = 'running';
  saveLedger(loop);
  appendText(loop, '## 无人值守（编排者）\n\n- 改为 ' + (loop.state.autoContinue ? '开' : '关') + '，循环状态 ' + loop.state.status);
  return emit(args, { autoContinue: loop.state.autoContinue, status: loop.state.status },
    '无人值守 ' + (loop.state.autoContinue ? '开：一轮跑完 hook 会接着叫下一轮' : '关：跑完当前这轮就停'));
}

function commandConcurrency(args) {
  const loop = openLedger(args);
  const conc = concurrencyOf(loop);
  const max = args.max !== undefined ? Math.max(1, num(args.max, conc.max)) : conc.max;
  const exclusiveLimit = args.exclusive !== undefined ? Math.max(0, num(args.exclusive, conc.exclusiveLimit)) : conc.exclusiveLimit;
  loop.state.concurrency = { max, exclusiveLimit, active: conc.active };
  saveLedger(loop);
  appendText(loop, '## 并发上限调整（编排者）\n\n- 上限 ' + conc.max + ' → ' + max + '，互斥 ' + conc.exclusiveLimit + ' → ' + exclusiveLimit);
  return emit(args, { max, exclusiveLimit }, '并发上限 ' + max + '，互斥名额 ' + exclusiveLimit);
}

/* ---------------------------------------------------------------- summary */

function commandSummary(args) {
  const loop = openLedger(args);
  const tasks = parseTasks(loop);
  const state = taskStateOf(loop);
  const conc = concurrencyOf(loop);
  const group = (filter) => tasks.filter(filter).map((t) => (t.issue ? '#' + t.issue : t.id));
  const summary = {
    loop: loop.name,
    status: loop.state.status,
    iteration: num(loop.state.iteration, 0),
    maxIterations: num(loop.state.maxIterations, 0),
    slots: { used: conc.active.length, max: conc.max },
    done: group((t) => t.status === 'done'),
    escalated: group((t) => t.status === 'escalated'),
    waiting: group((t) => t.status === 'waiting'),
    forUser: Object.keys(state).filter((id) => state[id] && state[id].waitFor === 'user'),
    running: conc.active.map((a) => (a.issue ? '#' + a.issue : a.task)),
    free: group((t) => t.status === 'pending' && !inScopeAnnotated(t)
      && !conc.active.some((a) => a.task === t.id)
      && !(state[t.id] && (state[t.id].external || state[t.id].escalated || (state[t.id].blockedBy || []).length))),
  };
  if (args.json) return emit(args, summary);
  const lines = [
    '循环 ' + summary.loop + '（' + summary.status + '）第 ' + summary.iteration + '/' + summary.maxIterations + ' 轮，并发 ' + summary.slots.used + '/' + summary.slots.max,
    '完成 ' + summary.done.length + ' 张' + (summary.done.length ? '：' + summary.done.join(' ') : ''),
  ];
  if (summary.running.length) lines.push('在跑：' + summary.running.join(' '));
  if (summary.escalated.length) lines.push('等架构师：' + summary.escalated.join(' '));
  if (summary.waiting.length) lines.push('等前提条件：' + summary.waiting.join(' '));
  if (summary.forUser.length) lines.push('等用户：' + summary.forUser.join(' '));
  lines.push('还可以派 ' + summary.free.length + ' 张：' + (summary.free.join(' ') || '（没有）'));
  process.stdout.write(lines.join('\n') + '\n');
}

function commandNote(args) {
  const loop = openLedger(args);
  const text = str(args.text, '');
  if (!text) fail('要写什么：--text "..."');
  const iteration = num(loop.state.iteration, 0);
  const dir = path.join(loop.dir, 'notes');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'round-' + iteration + '.md');
  let current = '';
  try {
    current = fs.readFileSync(file, 'utf8');
  } catch {
    current = '# 第 ' + iteration + ' 轮的补充说明\n';
  }
  fs.writeFileSync(file, current + (current.endsWith('\n') ? '\n' : '\n\n') + text + '\n', 'utf8');
  return emit(args, { iteration, file }, '补充说明写进 ' + file);
}

/* ------------------------------------------------------------------- utils */

function appendText(loop, text) {
  let current = '';
  try {
    current = fs.readFileSync(loop.progressFile, 'utf8');
  } catch {
    current = '# 进度日志\n';
  }
  const sep = current.endsWith('\n\n') ? '' : current.endsWith('\n') ? '\n' : '\n\n';
  fs.mkdirSync(path.dirname(loop.progressFile), { recursive: true });
  fs.writeFileSync(loop.progressFile, current + sep + text.replace(/\s+$/, '') + '\n', 'utf8');
}

function emit(args, value, text) {
  if (args.json) {
    process.stdout.write(JSON.stringify(value) + '\n');
    return value;
  }
  if (text) process.stdout.write(text + '\n');
  return value;
}

const USAGE = [
  'solo — solo 模式的账本命令（完整说明见 ../SKILL.md）',
  '',
  '  state | tasks | summary | note --text "..."',
  '  refresh | sync [--apply] | next [--max N] [--concurrency N] [--dry-run]',
  '  claim --task T-004 | worktree --task T-004 [--remove] | start --task T-004 | attach --task T-004 --session <id>',
  '  finish --task T-004 --status done|failed|blocked | check --task T-004',
  '  escalate|question|askhuman --task T-004 | handover --task T-004 | reap [--stale 90]',
  '  pause | resume [--no-auto] | auto on|off | budget --iterations 120 | signature --value solo-<模型 ID>',
  '  concurrency --max 4 --exclusive 1',
  '',
  '通用选项：--loop <名称>  --workspace <路径>  --json',
].join('\n');

const args = parseArgs(process.argv.slice(2));
const command = args._[0];

switch (command) {
  case 'state': commandState(args); break;
  case 'tasks': commandTasks(args); break;
  case 'next': commandNext(args); break;
  case 'refresh': commandRefresh(args); break;
  case 'sync': commandSync(args); break;
  case 'claim': commandClaim(args); break;
  case 'worktree': commandWorktree(args); break;
  case 'start': commandStart(args); break;
  case 'attach': commandAttach(args); break;
  case 'finish': commandFinish(args); break;
  case 'check': commandCheck(args); break;
  case 'escalate': handOff(args, 'escalate'); break;
  case 'question': handOff(args, 'question'); break;
  case 'askhuman': handOff(args, 'askhuman'); break;
  case 'handover': commandHandover(args); break;
  case 'reap': commandReap(args); break;
  case 'pause': commandPause(args); break;
  case 'resume': commandResume(args); break;
  case 'summary': commandSummary(args); break;
  case 'note': commandNote(args); break;
  case 'concurrency': commandConcurrency(args); break;
  case 'auto': commandAuto(args); break;
  case 'budget': commandBudget(args); break;
  case 'signature': commandSignature(args); break;
  case undefined:
  case 'help':
    process.stdout.write(USAGE + '\n');
    break;
  default:
    fail('不认识的命令：' + command + '\n\n' + USAGE);
}
