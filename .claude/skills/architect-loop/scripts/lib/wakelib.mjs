/** wake 的纯逻辑：挑选先后、next.json 的内容、锁。 */
import fs from 'node:fs';
import path from 'node:path';

export const JUDGE_ORDER = ['triage', 'unblocked', 'verify'];

/** 按 triage、unblocked、verify 的先后、同类编号小的先，挑一件证据有效的。valid: Set<编号>。 */
export function pickJudge(scanResult, valid) {
  for (const kind of JUDGE_ORDER) {
    const hit = [...scanResult[kind]].sort((a, b) => a.number - b.number).find((i) => valid.has(i.number));
    if (hit) return { kind, number: hit.number, title: hit.title };
  }
  return null;
}

const reason = (c) => {
  if (!c.exists) return c.problems[0] || '没有证据包';
  if (!c.valid) return c.problems.join('；');
  return `${c.mismatches} 行对不上，重做一次`;
};

/** 要取证的：证据包缺、过期、核对不过，或有对不上的行且没重做过的。已判过的不要。 */
export function evidenceTargets(scanResult, checks) {
  const seen = new Set();
  const out = [];
  for (const kind of ['verify', 'triage', 'unblocked']) {
    for (const i of scanResult[kind]) {
      const c = checks[i.number];
      if (seen.has(i.number) || !c || !c.needsRedo) continue;
      seen.add(i.number);
      out.push({ number: i.number, kind, reason: reason(c) });
    }
  }
  return out.sort((a, b) => a.number - b.number);
}

/** 写进 next.json 的内容。 */
export function buildNext(scanResult, checks, meta) {
  const valid = new Set(Object.entries(checks).filter(([, c]) => c.valid).map(([n]) => Number(n)));
  return {
    ...meta,
    evidence: evidenceTargets(scanResult, checks),
    judge: pickJudge(scanResult, valid),
    released: meta.released || [],
    warnings: scanResult.warnings,
    candidates: { verify: scanResult.verify, triage: scanResult.triage, unblocked: scanResult.unblocked },
  };
}

/** 没有取证也没有判断要做。 */
export const nothingToDo = (next) => !next.evidence.length && !next.judge;

/** 加锁。有没过期的锁返回 {ok:false}；锁文件内容是进程号与时间。 */
export function acquireLock(file, { pid, now = Date.now(), lockMinutes }) {
  try {
    const old = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (now - Date.parse(old.time) < lockMinutes * 60000) return { ok: false, holder: old };
  } catch { /* 没有锁或读不出来：当没有 */ }
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ pid, time: new Date(now).toISOString() }));
  return { ok: true };
}

/** pid 给了就只删自己的锁；不给（--finish 在另一个进程里）直接删。 */
export function releaseLock(file, pid) {
  try {
    if (pid === undefined || JSON.parse(fs.readFileSync(file, 'utf8')).pid === pid) fs.unlinkSync(file);
  } catch { /* 已经没了 */ }
}

/** 心跳内容：start 是 next.json，finish 是 --finish 的参数。 */
export function buildHeartbeat(next, fin, endedAt = new Date().toISOString()) {
  return {
    startedAt: next.startedAt, endedAt, mainSha: next.mainSha, released: next.released,
    evidence: fin.evidenced || [], judged: fin.judged ? { number: fin.judged, result: fin.result || '' } : null,
    warnings: next.warnings, note: fin.note || '',
  };
}
