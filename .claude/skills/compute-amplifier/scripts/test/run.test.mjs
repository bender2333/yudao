import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const runner = fileURLToPath(new URL('../run.mjs', import.meta.url));

test('测试基础设施：真实命令验证配置，不启动执行器或创建账本', () => {
  const root = mkdtempSync(join(tmpdir(), 'yudao-run-'));
  try {
    const runDir = join(root, 'control');
    const worktree = join(root, 'candidate');
    mkdirSync(runDir); mkdirSync(worktree);
    const approval = join(runDir, 'approval.txt');
    writeFileSync(approval, '用户批准记录');
    // --validate 仅检查真实可执行文件是否存在，不把 node --version 当作 agent。
    const adapter = { executable: process.execPath, args: ['--version'], timeoutMs: 1000 };
    const config = { runDir, worktrees: [worktree], approval, issue: 123, repository: 'bender2333/yudao',
      budget: { totalTokens: 10000, planning: 0.3, implementation: 0.4, trial: 0.3 },
      adapters: { preflight: adapter, solo: adapter, trial: adapter, architect: adapter } };
    const path = join(runDir, 'config.json');
    writeFileSync(path, JSON.stringify(config));
    const result = spawnSync(process.execPath, [runner, '--validate', path], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(JSON.parse(result.stdout).preflight, 'not-run');
    assert.equal(existsSync(join(runDir, 'state.json')), false);
    assert.equal(existsSync(join(runDir, 'coordinator.lock')), false);

    writeFileSync(path, JSON.stringify({ ...config, worktrees: [root] }));
    const overlap = spawnSync(process.execPath, [runner, '--validate', path], { encoding: 'utf8' });
    assert.notEqual(overlap.status, 0);
    assert.match(overlap.stderr, /彼此独立/);

    writeFileSync(path, JSON.stringify(config));
    const lock = join(runDir, 'coordinator.lock');
    writeFileSync(lock, '已有协调者');
    const locked = spawnSync(process.execPath, [runner, path], { encoding: 'utf8' });
    assert.notEqual(locked.status, 0);
    assert.match(locked.stderr, /EEXIST/);
    assert.equal(readFileSync(lock, 'utf8'), '已有协调者');
    assert.equal(existsSync(join(runDir, 'state.json')), false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
