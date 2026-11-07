#!/usr/bin/env node
/**
 * 唤醒入口，只做脚本层，不起模型。
 *   node wake.mjs [--dry-run] [--config <文件>] [--root <目录>] [--milestone X ...]
 *   node wake.mjs --pick                      取证以后重新核对，更新 next.json 的 judge
 *   node wake.mjs --finish [--judged <号> --result <一句话>] [--evidenced <号,号>]
 * 配置默认读 <root>/.ralph/architect/config.json；--dry-run 没有配置时用示例配置。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { git } from './lib/proc.mjs';
import { readConfig, EXAMPLE_CONFIG } from './lib/config.mjs';
import { makeDeps } from './lib/gitdeps.mjs';
import { scan } from './scan.mjs';
import { release } from './release.mjs';
import { checkIssue } from './check-evidence.mjs';
import { acquireLock, releaseLock, buildNext, nothingToDo, buildHeartbeat } from './lib/wakelib.mjs';

const argv = process.argv.slice(2);
const arg = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };
const dryRun = argv.includes('--dry-run');
const root = path.resolve(arg('--root') || git(process.cwd(), ['rev-parse', '--show-toplevel']).stdout.trim() || process.cwd());
const dir = path.join(root, '.ralph/architect');
const nextFile = path.join(dir, 'next.json');
const lockFile = path.join(dir, 'lock');
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const logFile = path.join(dir, 'runs', `${stamp}.log`);
const write = (file, text, append) => {
  if (dryRun) return;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  (append ? fs.appendFileSync : fs.writeFileSync)(file, text);
};
const writeJson = (file, v) => write(file, JSON.stringify(v, null, 2));
const readJson = (file) => readConfig(file);
const print = (lines) => console.log(lines.slice(0, 10).join('\n'));

function finish() {
  const next = readJson(nextFile);
  if (!next) { print(['没有 next.json，没有可收尾的运行']); releaseLock(lockFile); return; }
  const evidenced = (arg('--evidenced') || '').split(',').filter(Boolean).map(Number);
  const hb = buildHeartbeat(next, { judged: arg('--judged') ? Number(arg('--judged')) : null, result: arg('--result'), evidenced });
  const logLines = [`收尾 ${hb.endedAt}`, JSON.stringify(hb)];
  const prev = next.logFile || logFile;
  write(prev, `${logLines.join('\n')}\n`, true);
  writeJson(path.join(dir, 'heartbeat.json'), hb);
  releaseLock(lockFile);
  print([`收尾：取证 ${evidenced.length} 件，判断 ${hb.judged ? `#${hb.judged.number}` : '无'}，已写心跳并解锁`]);
}

function pick(cwd) {
  const next = readJson(nextFile);
  if (!next) { print(['没有 next.json，先跑 wake.mjs']); process.exit(1); }
  const deps = makeDeps(cwd);
  const nums = Object.values(next.candidates).flat().map((c) => c.number);
  const checks = {};
  for (const n of nums) checks[n] = checkIssue(n, cwd, deps);
  const upd = buildNext({ ...next.candidates, warnings: next.warnings }, checks, next);
  writeJson(nextFile, upd);
  print([`取证以后：还要取证 ${upd.evidence.map((e) => `#${e.number}`).join(' ') || '无'}；判断 ${upd.judge ? `#${upd.judge.number}(${upd.judge.kind})` : '无'}`]);
}

function main() {
  let cfg = readJson(path.join(dir, 'config.json'));
  if (arg('--config')) cfg = readJson(arg('--config'));
  if (!cfg && dryRun) cfg = { ...readJson(EXAMPLE_CONFIG), enabled: true, worktree: root };
  if (!cfg || !cfg.enabled) {
    writeJson(path.join(dir, 'heartbeat.json'), { startedAt: new Date().toISOString(), endedAt: new Date().toISOString(), note: '没有配置或 enabled 为假' });
    print(['架构师循环：没有配置或 enabled 为假，只写心跳']);
    return;
  }
  const ms = [];
  for (let i = 0; i < argv.length; i += 1) if (argv[i] === '--milestone') ms.push(argv[++i]);
  const scope = ms.length ? ms : cfg.scope?.milestones || [];
  const cwd = dryRun ? root : cfg.worktree;

  if (!dryRun) {
    const lock = acquireLock(lockFile, { pid: process.pid, lockMinutes: cfg.lockMinutes || 120 });
    if (!lock.ok) { print([`已有运行在锁里（进程 ${lock.holder.pid}，${lock.holder.time}），退出`]); return; }
  }
  let keepLock = false;
  try {
    const startedAt = new Date().toISOString();
    if (!dryRun) {
      for (const a of [['fetch', 'origin'], ['checkout', '--detach', 'origin/main']]) {
        const r = git(cwd, a);
        if (r.status !== 0) throw new Error(`git ${a.join(' ')} 失败：${r.stderr.trim()}`);
      }
    }
    const mainSha = git(cwd, ['rev-parse', '--short', 'origin/main']).stdout.trim();
    const s = scan(scope);
    const released = release(s, { dryRun });
    const deps = makeDeps(cwd);
    const checks = {};
    for (const c of [...s.verify, ...s.triage, ...s.unblocked]) checks[c.number] = checkIssue(c.number, cwd, deps);
    const next = buildNext(s, checks, { startedAt, mainSha, released, logFile });
    writeJson(nextFile, next);
    write(logFile, `${startedAt} main ${mainSha}\n${JSON.stringify(next)}\n`, true);

    const lines = [
      `main ${mainSha}；到期 ${s.due.length} 交用户 ${s.handToUser.length} 验收 ${s.verify.length} 分诊 ${s.triage.length} 解挡 ${s.unblocked.length} 提醒 ${s.warnings.length}`,
      released.length ? `${dryRun ? '会放回' : '放回'}：${released.map((r) => `#${r.number}${r.kind === 'handed-to-user' ? '(交用户)' : ''}`).join(' ')}` : '放回：无',
      `要取证：${next.evidence.map((e) => `#${e.number}(${e.kind})`).join(' ') || '无'}`,
      `要判断：${next.judge ? `#${next.judge.number}(${next.judge.kind})` : '无'}`,
    ];
    if (nothingToDo(next)) {
      writeJson(path.join(dir, 'heartbeat.json'), buildHeartbeat(next, { note: '没有要取证或判断的' }));
      lines.push('没有要做的，已写心跳并解锁');
    } else {
      keepLock = true;
      lines.push(`锁留着，next.json 在 ${nextFile}；做完跑 wake.mjs --finish`);
    }
    print(lines);
  } finally {
    if (!dryRun && !keepLock) releaseLock(lockFile, process.pid);
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    if (argv.includes('--finish')) finish();
    else if (argv.includes('--pick')) pick(readJson(path.join(dir, 'config.json'))?.worktree || root);
    else main();
  } catch (e) {
    console.error(`wake 失败：${e.message}`);
    process.exit(1);
  }
}
