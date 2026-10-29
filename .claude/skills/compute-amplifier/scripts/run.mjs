import { readFileSync, writeFileSync, renameSync, mkdirSync, openSync, closeSync, unlinkSync, realpathSync, statSync } from 'node:fs';
import { resolve, relative, isAbsolute, sep } from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync, execFileSync } from 'node:child_process';
import { initialState, validateConfig, startRound, suspend, recordSolo, recordTrial, recordArchitect } from './state.mjs';

const validateOnly = process.argv[2] === '--validate';
const configFile = resolve(process.argv[validateOnly ? 3 : 2]);
const bytes = readFileSync(configFile);
const config = JSON.parse(bytes);
validateConfig(config);
if (!isAbsolute(config.runDir) || !Number.isSafeInteger(config.issue) || config.issue < 1 || !/^[\w.-]+\/[\w.-]+$/.test(config.repository)) throw new Error('运行目录、工单或仓库身份无效');
const runDir = realpathSync(config.runDir);
if (!isAbsolute(config.approval)) throw new Error('批准记录需要绝对路径');
statSync(config.approval);
for (const worktree of config.worktrees ?? []) {
  const root = realpathSync(worktree);
  for (const rel of [relative(root, runDir), relative(runDir, root)]) {
    if (!rel || (rel !== '..' && !rel.startsWith('..' + sep) && !isAbsolute(rel))) throw new Error('运行目录与候选工作区必须彼此独立');
  }
}
for (const [role, adapter] of Object.entries(config.adapters)) {
  if (!isAbsolute(adapter.executable) || !Array.isArray(adapter.args) || !adapter.args.every(value => typeof value === 'string') || !Number.isSafeInteger(adapter.timeoutMs) || adapter.timeoutMs < 1) throw new Error(`执行器配置无效: ${role}`);
  if (!statSync(adapter.executable).isFile()) throw new Error(`执行器文件无效: ${role}`);
}
const identity = createHash('sha256').update(bytes).digest('hex');
if (validateOnly) {
  process.stdout.write(JSON.stringify({ identity, configuration: 'valid', preflight: 'not-run' }) + '\n');
  process.exit(0);
}
const stateFile = resolve(runDir, 'state.json');
const lock = resolve(runDir, 'coordinator.lock');
const lockFd = openSync(lock, 'wx');
writeFileSync(lockFd, JSON.stringify({ pid: process.pid, startedAt: new Date().toISOString(), identity }) + '\n');
const save = value => {
  writeFileSync(stateFile + '.next', JSON.stringify(value, null, 2) + '\n', { flag: 'w' });
  renameSync(stateFile + '.next', stateFile);
};
let state;
function readState() {
  try { return JSON.parse(readFileSync(stateFile, 'utf8')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; return initialState(identity); }
}
function invoke(role) {
  const adapter = config.adapters?.[role];
  if (!adapter || !isAbsolute(adapter.executable) || !Array.isArray(adapter.args) || !Number.isSafeInteger(adapter.timeoutMs) || adapter.timeoutMs < 1) throw new Error(`缺少受控执行器: ${role}`);
  const folder = resolve(runDir, `round-${state.rounds}`, role);
  mkdirSync(folder, { recursive: true });
  const resultFile = resolve(folder, 'result.json');
  // 每段结果只接受本次新建的文件，恢复时不会把旧结果当成本次完成。
  try { statSync(resultFile); throw new Error(`已有阶段结果，需要人工核对: ${resultFile}`); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const request = { version: 1, role, identity, round: state.rounds, config: configFile, resultFile };
  const stdout = openSync(resolve(folder, 'stdout.log'), 'w');
  const stderr = openSync(resolve(folder, 'stderr.log'), 'w');
  let result;
  try {
    result = spawnSync(adapter.executable, adapter.args, {
      cwd: runDir, shell: false, input: JSON.stringify(request), encoding: 'utf8', timeout: adapter.timeoutMs,
      stdio: ['pipe', stdout, stderr],
    });
  } finally { closeSync(stdout); closeSync(stderr); }
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${role} 执行器失败，退出码 ${result.status}`);
  const output = JSON.parse(readFileSync(resultFile, 'utf8'));
  if (output.identity !== identity || output.round !== state.rounds || typeof output.evidence !== 'string' || !isAbsolute(output.evidence)) throw new Error(`${role} 结果身份或证据不完整`);
  statSync(output.evidence);
  return output;
}
function notify() {
  if (!state.notificationPending) return;
  const body = resolve(runDir, 'human.md');
  writeFileSync(body, `实验已挂起：${state.reason}\n\n运行身份：${identity}\n已计入轮次：${state.rounds}/3\n证据：协调者保存的运行清单和各轮结果。\n`, 'utf8');
  const gh = (...args) => execFileSync('gh', args, { cwd: runDir, stdio: 'pipe', timeout: 60000 });
  const issue = JSON.parse(gh('issue', 'view', String(config.issue), '--repo', config.repository, '--json', 'labels,comments').toString());
  const flows = ['waiting', 'ready-for-agent', 'in-progress', 'needs-review', 'needs-triage', 'needs-architect'];
  const args = ['issue', 'edit', String(config.issue), '--repo', config.repository, '--add-label', 'ready-for-human'];
  for (const label of issue.labels.filter(l => flows.includes(l.name))) args.push('--remove-label', label.name);
  gh(...args);
  if (!issue.comments.some(c => c.body.includes(`运行身份：${identity}`))) gh('issue', 'comment', String(config.issue), '--repo', config.repository, '--body-file', body);
  state = { ...state, notificationPending: false };
  save(state);
}
try {
  state = readState();
  if (state.identity !== identity || state.version !== 1) throw new Error('配置身份变化，必须重新批准并建立新运行');
  if (!Number.isSafeInteger(state.rounds) || state.rounds < 0 || state.rounds > 3 || !['ready', 'running', 'ready-for-human', 'passed'].includes(state.status)) throw new Error('账本状态无效，需要人工核对');
  if (state.status === 'running') { state = suspend(state, '上次执行中断，保留已计轮次与产物等待核对'); save(state); }
  if (state.status === 'ready-for-human') { notify(); process.exitCode = 2; }
  else if (state.status !== 'passed') {
    const proof = invoke('preflight');
    if (proof.status !== 'passed') throw new Error('权限隔离、可信 CI 或硬预算检查未通过');
    while (state.status === 'ready') {
      state = startRound(state); save(state);
      if (state.status !== 'running') break;
      state = recordSolo(state, invoke('solo')); save(state);
      if (state.phase === 'trial') { state = recordTrial(state, invoke('trial')); save(state); }
      if (state.phase === 'architect' && state.status === 'running') { state = recordArchitect(state, invoke('architect')); save(state); }
    }
    notify();
    if (state.status !== 'passed') process.exitCode = 2;
  }
} catch (error) {
  if (state && state.identity === identity) {
    state = suspend(state, error.message); save(state);
    try { notify(); } catch { process.stderr.write('GitHub 通知未完成，待办已保留。\n'); }
  }
  // 通知失败仍保留待办，由下次恢复重试。
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 2;
} finally {
  closeSync(lockFd);
  unlinkSync(lock);
}
