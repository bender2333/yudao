/** evidence.mjs 要的 git 与 gh 查询，真实实现。 */
import { gh, git } from './proc.mjs';

export function makeDeps(cwd) {
  return {
    isAncestor: (a, b) => git(cwd, ['merge-base', '--is-ancestor', a, b]).status === 0,
    commitExists: (sha) => /^[0-9a-fA-F]{7,40}$/.test(sha) && git(cwd, ['cat-file', '-e', `${sha}^{commit}`]).status === 0,
    fileAt: (sha, p) => {
      const r = git(cwd, ['show', `${sha}:${p}`]);
      return r.status === 0 ? r.stdout : null;
    },
    ciRun: (id) => {
      const r = gh(['run', 'view', String(id), '--json', 'conclusion,headSha']);
      if (r.status !== 0) return null;
      try { return JSON.parse(r.stdout); } catch { return null; }
    },
    mainCommitBefore: (iso) => git(cwd, ['rev-list', '-1', '--first-parent', `--before=${iso}`, 'origin/main']).stdout.trim(),
  };
}
