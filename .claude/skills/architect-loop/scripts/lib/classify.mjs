/**
 * 分类：纯函数，不碰网络。
 * issue: {number,title,milestone,milestoneNumber,labels,blockedBy,subIssues,comments?}
 * refs:  {<编号>: {state,closedAt,labels}}，ready-for-human 的 TRIAGE: 评论点名的工单
 */
const T = (s) => Date.parse(s);

export const inScope = (issue, scope) =>
  scope.some((s) => String(s) === issue.milestone || String(s) === String(issue.milestoneNumber));

export const startsWithPrefix = (c, prefix) => c.body.trimStart().startsWith(prefix);
export const lastWith = (comments, prefix) => {
  for (let i = (comments || []).length - 1; i >= 0; i -= 1) if (startsWithPrefix(comments[i], prefix)) return comments[i];
  return null;
};

/** `WAITING: 日期 2026-11-01` 与 `WAITING: 2026-11-01` 两种写法；不带日期的（放回时那条）返回 null。 */
export function parseWaitingDate(body) {
  const first = body.trimStart().split('\n')[0];
  const m = /^WAITING[:：]\s*(?:日期[:：]?\s*)?(\d{4}-\d{2}-\d{2})/.exec(first);
  return m ? m[1] : null;
}

export function allChildrenClosed(issue) {
  return issue.subIssues.length > 0 && issue.subIssues.every((s) => s.state === 'CLOSED');
}
export function lastChildClosedAt(issue) {
  return issue.subIssues.reduce((a, s) => (!a || T(s.closedAt) > T(a) ? s.closedAt : a), null);
}

const KIND = ['stage', 'trial', 'parent'];
export const isVerifyCandidate = (i) =>
  i.labels.includes('parent') && !i.title.includes('工作线跟踪') && allChildrenClosed(i);

/** 哪些范围内的工单要再读评论。 */
export const needsComments = (i, scope) => inScope(i, scope) && (
  i.labels.includes('waiting') || i.labels.includes('ready-for-human') || isVerifyCandidate(i));

const issueNumbers = (body) => [...body.matchAll(/#(\d+)/g)].map((m) => Number(m[1]));
export const triageMentions = (issue) => {
  const c = lastWith(issue.comments, 'TRIAGE:');
  return c ? issueNumbers(c.body) : [];
};

export function classify(issues, { today, scope, refs = {} }) {
  const r = { due: [], handToUser: [], verify: [], triage: [], unblocked: [], warnings: [] };
  const byNumber = new Map(issues.map((i) => [i.number, i]));
  for (const i of issues.filter((x) => inScope(x, scope)).sort((a, b) => a.number - b.number)) {
    const base = { number: i.number, title: i.title };
    const comments = i.comments || [];
    const L = i.labels;

    if (isVerifyCandidate(i)) {
      const closed = lastChildClosedAt(i);
      const verdict = comments.some((c) => startsWithPrefix(c, 'VERDICT:') && T(c.createdAt) > T(closed));
      if (!verdict) r.verify.push({ ...base, lastChildClosedAt: closed });
    }

    if (L.includes('needs-triage')) {
      const latest = comments.filter((c) => ['ARCHITECT:', 'HANDOFF:', 'TRIAGE:', 'WAITING:'].some((p) => startsWithPrefix(c, p))).at(-1);
      if (latest && startsWithPrefix(latest, 'TRIAGE:')) {
        r.warnings.push({ type: 'triage-label-stale', ...base, note: '最近一条交回类评论是 TRIAGE:，标签仍是 needs-triage，没有分诊' });
      } else r.triage.push(base);
    }

    if (L.includes('waiting') && !KIND.some((k) => L.includes(k))) {
      const w = lastWith(comments, 'WAITING:');
      const date = w && parseWaitingDate(w.body);
      if (date && date <= today) {
        const count = comments.filter((c) => startsWithPrefix(c, 'WAITING: 已放回')).length;
        if (count >= 2) r.handToUser.push({ ...base, date, count, reason: `waiting 与 ready-for-agent 之间已来回 ${count} 次` });
        else r.due.push({ ...base, date });
      }
    }

    if (L.includes('ready-for-human') && !KIND.some((k) => L.includes(k))) {
      const t = lastWith(comments, 'TRIAGE:');
      if (t) {
        const hit = issueNumbers(t.body).find((n) => {
          const ref = refs[n];
          return ref && ref.state === 'CLOSED' && ref.labels.includes('architecture') && T(t.createdAt) < T(ref.closedAt);
        });
        if (hit) r.unblocked.push({ ...base, architecture: hit, closedAt: refs[hit].closedAt });
      }
    }

    for (const b of i.blockedBy.filter((x) => x.state === 'OPEN')) {
      const other = byNumber.get(b.number);
      if (!other || !inScope(other, scope)) {
        r.warnings.push({ type: 'blocked-outside-scope', ...base, blocker: b.number, blockerMilestone: other ? other.milestone || '-' : '未知' });
      }
    }
  }
  for (const i of issues.filter((x) => x.labels.includes('ready-for-agent') && !inScope(x, scope))) {
    r.warnings.push({ type: 'ready-outside-scope', number: i.number, title: i.title, milestone: i.milestone || '-' });
  }
  return r;
}
