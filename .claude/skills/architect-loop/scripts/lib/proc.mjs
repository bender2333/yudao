/** 子进程与 gh：参数数组，不经 shell。 */
import { spawnSync } from 'node:child_process';

export const REPO = process.env.ARCHITECT_LOOP_REPO || 'bender2333/yudao';

export function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {
    encoding: 'utf8', cwd: opts.cwd, input: opts.input, env: opts.env, maxBuffer: 128 * 1024 * 1024,
  });
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '', error: r.error };
}
export const gh = (args, opts) => run('gh', args, opts);
export const git = (cwd, args) => run('git', args, { cwd });

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** GraphQL 查询，失败重试三次；任何错误都抛出，不返回半份数据。 */
export function graphql(query) {
  let last = '';
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const r = gh(['api', 'graphql', '-f', `query=${query}`]);
    if (r.status === 0) {
      let payload;
      try { payload = JSON.parse(r.stdout); } catch (e) { throw new Error(`GraphQL 输出不是 JSON：${e.message}`); }
      if (payload.errors) throw new Error(`GraphQL 报错：${JSON.stringify(payload.errors).slice(0, 400)}`);
      return payload.data;
    }
    last = (r.stderr || r.stdout || `退出码 ${r.status}`).trim().slice(0, 400);
    sleepSync(2000 * (attempt + 1));
  }
  throw new Error(`gh api graphql 失败：${last}`);
}

export function localDate(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
