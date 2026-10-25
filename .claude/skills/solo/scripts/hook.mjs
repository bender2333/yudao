/**
 * solo — Hook 入口（无人值守）。
 *
 * 只做四件事：
 *   - SessionStart：告诉新会话这里有一个循环，账本在哪，还有几轮没跑完。
 *   - SubagentStart：告诉工人它这一轮的身份与三条边界。
 *   - PreToolUse：拒绝写 `.ralph/**`（账本只由命令改）、拒绝 task_append（会复用上下文），
 *     并发超了给出提醒。
 *   - Stop：循环还在跑、还有活、无人值守开着时，把会话叫回来接着做。
 *
 * 任何异常都 fail open：Hook 不能把宿主会话弄坏。
 * 每条事件的输出都只写 stdout，一行 JSON。
 */
import fs from 'node:fs';
import path from 'node:path';
import {
  LEDGER_DIR,
  readJson,
  writeJson,
  num,
  concurrencyOf,
  parseTasks,
  safeFileName,
} from './state.mjs';

/** 同一个会话最多被 Stop hook 叫回来这么多次，防止死循环。 */
const MAX_CONTINUES = 200;
/** 任务书超过这个长度就提醒精简。 */
const MAX_BRIEF_CHARS = 6000;

function resolveWorkspace(input) {
  const fromEnv = process.env.CODEBUDDY_PROJECT_DIR || process.env.CLAUDE_PROJECT_DIR || process.env.MINIMAX_PROJECT_DIR;
  if (typeof fromEnv === 'string' && fromEnv.trim()) return path.resolve(fromEnv.trim());
  if (input && typeof input.cwd === 'string' && input.cwd.trim()) return path.resolve(input.cwd.trim());
  return process.cwd();
}

function loadState(input) {
  const root = resolveWorkspace(input);
  const active = readJson(path.join(root, LEDGER_DIR, 'active.json'));
  const name = active && typeof active.loop === 'string' ? active.loop.trim() : '';
  if (!name) return null;
  const dir = path.join(root, LEDGER_DIR, name);
  const state = readJson(path.join(dir, 'state.json'));
  if (!state) return null;
  return {
    root,
    dir,
    name,
    state,
    status: typeof state.status === 'string' ? state.status : 'unknown',
    stateFile: path.join(dir, 'state.json'),
    tasksFile: path.join(dir, 'tasks.md'),
    progressFile: path.join(dir, 'progress.md'),
    workersDir: path.join(dir, 'workers'),
    guardFile: path.join(dir, '.stop-guard.json'),
  };
}

function isLive(loop) {
  return Boolean(loop && loop.state && loop.status === 'running');
}

function emit(payload) {
  process.stdout.write(JSON.stringify(payload) + '\n');
}

function readStdin() {
  return new Promise((resolve) => {
    let raw = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { raw += chunk; });
    process.stdin.on('end', () => resolve(raw));
    process.stdin.on('error', () => resolve(''));
  });
}

/* ----------------------------------------------------------------- events */

function onSessionStart(input) {
  const loop = loadState(input);
  if (!loop) return;
  if (loop.status !== 'running' && loop.status !== 'paused') return;
  const tasks = parseTasks(loop);
  const conc = concurrencyOf(loop);
  const done = tasks.filter((t) => t.status === 'done').length;
  const pending = tasks.filter((t) => t.status === 'pending').length;
  const forUser = Object.keys(loop.state.taskState || {})
    .filter((id) => loop.state.taskState[id] && loop.state.taskState[id].waitFor === 'user');
  const text = [
    '[solo] 本工作区有一个' + (loop.status === 'paused' ? '已暂停' : '进行中') + '的 solo 循环「' + loop.name + '」：第 '
      + num(loop.state.iteration, 0) + '/' + num(loop.state.maxIterations, 0) + ' 轮，完成 ' + done + '/' + tasks.length
      + ' 张，待办 ' + pending + ' 张，无人值守' + (loop.state.autoContinue === true ? '开' : '关') + '。',
    '账本：' + loop.stateFile + '；任务清单：' + loop.tasksFile + '；进度：' + loop.progressFile,
    '接着跑：node .claude/skills/solo/scripts/solo.mjs state，然后按 .claude/skills/solo/SKILL.md 的每轮步骤走。'
      + '有活动循环就不要重建账本。',
    ...(forUser.length ? ['有 ' + forUser.length + ' 张在等用户处理：' + forUser.join(', ') + '，收账时主动告诉用户缺什么。'] : []),
  ].join('\n');
  emit({ hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: text } });
}

function onSubagentStart(input) {
  const loop = loadState(input);
  if (!loop || !isLive(loop)) return;
  const conc = concurrencyOf(loop);
  const sessionId = typeof input.agent_id === 'string' ? input.agent_id : '';
  const mine = conc.active.find((a) => a.session && a.session === sessionId);
  const lines = [
    '[solo] 你是循环「' + loop.name + '」这一轮的子会话，上下文是全新的。只做任务书上的那一张工单，不要编排循环。',
  ];
  if (mine) {
    lines.push('你的任务是 ' + mine.task + (mine.issue ? '（工单 #' + mine.issue + '）' : '') + '，工作目录 ' + mine.worktree + '，分支 ' + mine.branch + '。');
  } else {
    lines.push('工作目录与分支写在任务书里；不要动主工作区。');
  }
  lines.push('不要改 .ralph/** 下的任何文件（账本只由编排者的命令改）；规则见 .claude/skills/solo/worker.md。');
  emit({ hookSpecificOutput: { hookEventName: 'SubagentStart', additionalContext: lines.join('\n') } });
}

function onPreToolUse(input) {
  const loop = loadState(input);
  if (!loop || !isLive(loop)) return;
  const tool = typeof input.tool_name === 'string' ? input.tool_name : '';
  const toolInput = input.tool_input && typeof input.tool_input === 'object' ? input.tool_input : {};
  const lower = tool.toLowerCase();

  if (lower === 'task_append') {
    emit({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: 'solo 循环正在运行：task_append 会复用上一轮子会话的上下文，破坏「每轮全新上下文」。请发起一次新的子代理调用。',
      },
    });
    return;
  }

  const target = [toolInput.file_path, toolInput.path, toolInput.notebook_path].filter((v) => typeof v === 'string').join(' ');
  const mutating = ['write', 'edit', 'multiedit', 'notebookedit', 'str_replace_editor'].includes(lower);
  if (mutating && /(^|[\\/])\.ralph[\\/]/.test(target)) {
    emit({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: '账本（.ralph/**）只能由 solo.mjs 的命令修改：手改 tasks.md 会丢任务行，手改 state.json 会让计数与失败次数对不上。',
      },
    });
    return;
  }

  if (lower === 'task' || lower === 'agent') {
    const conc = concurrencyOf(loop);
    const prompt = typeof toolInput.prompt === 'string' ? toolInput.prompt : toolInput.description || '';
    const notes = [];
    if (conc.active.length >= conc.max) {
      notes.push('并发位置已经满了（上限 ' + conc.max + '，在跑 ' + conc.active.map((a) => a.task).join(', ') + '）：先收账再派新的。');
    }
    if (typeof prompt === 'string' && prompt.length > MAX_BRIEF_CHARS) {
      notes.push('任务书 ' + prompt.length + ' 字符，偏长：只写目标、验收标准与文件路径，历史让工人自己去 ' + loop.progressFile + ' 读。');
    }
    if (!notes.length) return;
    emit({ hookSpecificOutput: { hookEventName: 'PreToolUse', additionalContext: notes.join('\n') } });
  }
}

function onSubagentStop(input) {
  const loop = loadState(input);
  if (!loop) return;
  const agentId = typeof input.agent_id === 'string' ? input.agent_id : '';
  const message = typeof input.last_assistant_message === 'string' ? input.last_assistant_message : '';
  if (!agentId || !message) return;
  try {
    fs.mkdirSync(loop.workersDir, { recursive: true });
    const header = [
      '# 第 ' + num(loop.state.iteration, 0) + ' 轮执行记录',
      '',
      '- 子会话：' + agentId,
      '- 循环：' + loop.name,
      '- 时间：' + new Date().toISOString(),
      '',
    ].join('\n');
    fs.writeFileSync(path.join(loop.workersDir, safeFileName(agentId) + '.md'), header + message + '\n', 'utf8');
  } catch {
    /* fail open */
  }
}

/**
 * 无人值守：循环还在 running、autoContinue 开着、还有活干时，把会话叫回来。
 * 不看 stop_hook_active（它会让每轮最多只续一次），用自己的计数器防止死循环。
 */
function onStop(input) {
  const loop = loadState(input);
  if (!loop || !isLive(loop)) return;
  if (loop.state.autoContinue !== true) return;

  const conc = concurrencyOf(loop);
  const iteration = num(loop.state.iteration, 0);
  const max = num(loop.state.maxIterations, 0);
  const pending = num(loop.state.pendingTasks, parseTasks(loop).filter((t) => t.status === 'pending').length);

  let phase = '';
  if (conc.active.length) {
    // 有工人交卷了才叫回来收账；都在跑就等它们的完成通知，不要空转。
    const finishedNow = conc.active.filter((a) => a.session && fs.existsSync(path.join(loop.workersDir, safeFileName(a.session) + '.md')));
    const allTracked = conc.active.every((a) => a.session);
    const guardAt = readJson(loop.guardFile);
    const sinceLast = guardAt && guardAt.at ? Date.now() - Date.parse(guardAt.at) : Infinity;
    // 有交卷的立刻叫回来；都在跑就等完成通知，最多 10 分钟看一眼（防止宿主不给完成通知时静默停住）。
    if (!finishedNow.length && allTracked && sinceLast < 10 * 60 * 1000) return;
    phase = 'collect';
  }
  else if (pending > 0 && iteration < max) phase = 'dispatch';
  if (!phase) return;

  const sessionId = typeof input.session_id === 'string' ? input.session_id : '';
  const guard = readJson(loop.guardFile) || {};
  const count = guard.sessionId === sessionId ? num(guard.count, 0) : 0;
  if (count >= MAX_CONTINUES) return;
  try {
    writeJson(loop.guardFile, { sessionId, count: count + 1, iteration, phase, at: new Date().toISOString() });
  } catch {
    return;
  }

  const forUser = Object.keys(loop.state.taskState || {})
    .filter((id) => loop.state.taskState[id] && loop.state.taskState[id].waitFor === 'user');
  const userNote = forUser.length ? '另外有 ' + forUser.length + ' 张在等用户处理（' + forUser.join(', ') + '），收账时转告用户。' : '';
  const reason = phase === 'collect'
    ? 'solo 循环「' + loop.name + '」还有 ' + conc.active.length + ' 个工人在跑（' + conc.active.map((a) => a.task).join(', ')
      + '）。用子会话的输出收账：先 node .claude/skills/solo/scripts/solo.mjs check --task <编号>，再 finish --task <编号> --status done|failed；'
      + '收一个立刻用 next 补一个空出的位置。全部收完再结束这一轮。' + userNote
    : 'solo 循环「' + loop.name + '」还没做完：第 ' + iteration + '/' + max + ' 轮，待办 ' + pending + ' 张。'
      + '接着做：先 refresh、再 sync，然后 next --max ' + conc.max + ' 挑活，建 worktree、claim、start、派活；'
      + '挑不到可派的就 solo.mjs pause 并把原因告诉用户。' + userNote;
  // CodeBuddy 读 continue:false，Claude Code 读 decision:block——两个都发。
  emit({ continue: false, decision: 'block', reason, stopReason: reason });
}

const HANDLERS = {
  SessionStart: onSessionStart,
  SubagentStart: onSubagentStart,
  PreToolUse: onPreToolUse,
  SubagentStop: onSubagentStop,
  Stop: onStop,
};

(async () => {
  const raw = await readStdin();
  let input = {};
  try {
    input = raw ? JSON.parse(raw.replace(/^\uFEFF/, '')) : {};
  } catch {
    input = {};
  }
  const handler = HANDLERS[typeof input.hook_event_name === 'string' ? input.hook_event_name : ''];
  if (!handler) return;
  try {
    handler(input);
  } catch (error) {
    if (process.env.SOLO_DEBUG) process.stderr.write('[solo] ' + error.stack + '\n');
  }
})();
