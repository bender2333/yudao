import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const HOOK = path.join(import.meta.dirname, '..', 'hook.mjs');

/**
 * 临时账本：完成的单子留着旧标记，没完成的也留着同样的标记。
 * hook 用 CODEBUDDY_PROJECT_DIR 指到临时根，真实账本不碰。
 */
function tempLedger({ waitMode = 'hook', active = [] } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'solo-hook-output-'));
  const dir = path.join(root, '.ralph', 'stage1');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(root, '.ralph', 'active.json'), JSON.stringify({ loop: 'stage1' }), 'utf8');
  fs.writeFileSync(path.join(dir, 'state.json'), JSON.stringify({
    loop: 'stage1',
    status: 'running',
    iteration: 11,
    maxIterations: 120,
    autoContinue: true,
    waitMode,
    concurrency: { max: 4, exclusiveLimit: 1, active },
    taskState: {
      'T-008': { waitFor: 'user' },
      'T-031': { fails: 1 },
      'T-012': { waitFor: 'user' },
      'T-013': { fails: 2 },
    },
  }, null, 2), 'utf8');
  fs.writeFileSync(path.join(dir, 'tasks.md'), [
    '- [x] T-008 #871 用户已决定取消（wontfix）',
    '- [x] T-031 #952 早已完成',
    '- [ ] T-012 #957 还没做完，在等用户回话',
    '- [ ] T-013 #958 还没做完',
    '',
  ].join('\n'), 'utf8');
  return root;
}

/** 临时账本用完删掉；删不掉也不该让用例失败。 */
function cleanup(root) {
  try {
    fs.rmSync(root, { recursive: true, force: true });
  } catch {
    /* 临时目录留在系统临时区，不影响仓库 */
  }
}

/** 事件 JSON 走 stdin，工作区用 CODEBUDDY_PROJECT_DIR 指到临时根。 */
const runHook = (root, payload) => {
  const r = spawnSync(process.execPath, [HOOK], {
    input: JSON.stringify(payload),
    env: Object.assign({}, process.env, { CODEBUDDY_PROJECT_DIR: root }),
    encoding: 'utf8',
  });
  assert.equal(r.status, 0, r.stderr);
  const out = r.stdout.trim();
  return out ? JSON.parse(out) : null;
};

test('hook SessionStart：注入的提示里，完成的等用户单子不出现，没完成的照旧出现', (t) => {
  const root = tempLedger();
  t.after(() => cleanup(root));
  const out = runHook(root, { hook_event_name: 'SessionStart', session_id: 'session-start-1315', cwd: root });
  const text = out.hookSpecificOutput.additionalContext;
  assert.match(text, /有 1 张在等用户处理：T-012/);
  assert.equal(text.includes('T-008'), false, '完成的 T-008 不该出现在注入的提示里');
});

test('hook Stop：拦停的提示里，完成的等用户单子不出现，没完成的照旧出现', (t) => {
  const root = tempLedger();
  t.after(() => cleanup(root));
  const out = runHook(root, { hook_event_name: 'Stop', session_id: 'session-stop-1315', cwd: root });
  assert.equal(out.decision, 'block');
  assert.match(out.reason, /另外有 1 张在等用户处理（T-012），收账时转告用户。/);
  assert.equal(out.reason.includes('T-008'), false, '完成的 T-008 不该出现在拦停提示里');
});

const fullConcurrency = ['T-001', 'T-002', 'T-003', 'T-004'].map((task) => ({ task }));
const ordinaryStart = { hook_event_name: 'SubagentStart', session_id: 'architect', agent_id: 'ordinary-agent' };
const ordinaryDispatch = { hook_event_name: 'PreToolUse', session_id: 'architect', tool_name: 'Agent', tool_input: { prompt: 'ordinary task' } };
const ordinaryStop = { hook_event_name: 'SubagentStop', session_id: 'architect', agent_id: 'ordinary-agent', last_assistant_message: 'ordinary result' };

test('notify：普通子代理不收到 solo 提示，也不写工人记录', (t) => {
  const root = tempLedger({ waitMode: 'notify', active: fullConcurrency });
  t.after(() => cleanup(root));
  assert.equal(runHook(root, ordinaryStart), null);
  assert.equal(runHook(root, ordinaryDispatch), null);
  assert.equal(runHook(root, { ...ordinaryDispatch, tool_name: 'task_append' }), null);
  assert.equal(runHook(root, ordinaryStop), null);
  assert.equal(fs.existsSync(path.join(root, '.ralph', 'stage1', 'workers', 'ordinary-agent.md')), false);
});

test('notify：账本写保护仍然生效', (t) => {
  const root = tempLedger({ waitMode: 'notify' });
  t.after(() => cleanup(root));
  const out = runHook(root, {
    hook_event_name: 'PreToolUse', session_id: 'architect', tool_name: 'Write',
    tool_input: { file_path: path.join(root, '.ralph', 'stage1', 'state.json') },
  });
  assert.equal(out.hookSpecificOutput.permissionDecision, 'deny');
});

test('hook：非所有者不收到 solo 提示，也不写工人记录', (t) => {
  const root = tempLedger({ active: fullConcurrency });
  t.after(() => cleanup(root));
  fs.writeFileSync(path.join(root, '.ralph', 'stage1', '.owner.json'), JSON.stringify({
    session: 'solo-owner', at: new Date().toISOString(),
  }), 'utf8');
  assert.equal(runHook(root, ordinaryStart), null);
  assert.equal(runHook(root, ordinaryDispatch), null);
  assert.equal(runHook(root, { ...ordinaryDispatch, tool_name: 'task_append' }), null);
  assert.equal(runHook(root, ordinaryStop), null);
  assert.equal(fs.existsSync(path.join(root, '.ralph', 'stage1', 'workers', 'ordinary-agent.md')), false);
});

test('hook：所有者仍收到并发提示与 solo 工人身份', (t) => {
  const root = tempLedger({ active: [...fullConcurrency.map((item) => ({ ...item })), { task: 'T-005', session: 'solo-worker' }] });
  t.after(() => cleanup(root));
  fs.writeFileSync(path.join(root, '.ralph', 'stage1', '.owner.json'), JSON.stringify({
    session: 'solo-owner', at: new Date().toISOString(),
  }), 'utf8');
  const dispatch = runHook(root, { ...ordinaryDispatch, session_id: 'solo-owner' });
  assert.match(dispatch.hookSpecificOutput.additionalContext, /并发位置已经满了/);
  const start = runHook(root, { ...ordinaryStart, session_id: 'solo-owner', agent_id: 'solo-worker' });
  assert.match(start.hookSpecificOutput.additionalContext, /你的任务是 T-005/);
  assert.equal(runHook(root, { ...ordinaryStop, session_id: 'solo-owner' }), null);
  assert.equal(fs.readFileSync(path.join(root, '.ralph', 'stage1', 'workers', 'ordinary-agent.md'), 'utf8').includes('ordinary result'), true);
});
