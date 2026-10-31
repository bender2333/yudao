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
function tempLedger() {
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
    waitMode: 'hook',
    concurrency: { max: 4, exclusiveLimit: 1, active: [] },
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
