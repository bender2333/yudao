import { isSelectable } from './select.mjs';

/** 开派多久算停住：reap --stale 的默认值，report 判「卡住」用同一份。 */
export const STALE_MINUTES = 90;

/** 最近一次提交超过这么久没动才算「没有新提交」：一直在写代码的工人不算卡住。 */
export const STALE_COMMIT_MINUTES = 30;

const asText = (v, fallback) => (typeof v === 'string' && v.trim() ? v.trim() : fallback);
const asNum = (v, fallback) => (typeof v === 'number' && Number.isFinite(v) ? v : fallback);

/** 账本里的范围内一句话：里程碑按编号与标题、标签、标题前缀，一条都没配就是全部开放工单。 */
export function scopeDisplay(scope) {
  const sc = scope || {};
  const ids = Array.isArray(sc.milestoneIds) ? sc.milestoneIds : sc.milestoneId ? [sc.milestoneId] : [];
  const titles = sc.milestoneTitles || {};
  const labels = Array.isArray(sc.labels) ? sc.labels : sc.label ? [sc.label] : [];
  const prefixes = Array.isArray(sc.prefixes) ? sc.prefixes : sc.prefix ? [sc.prefix] : [];
  const bits = [];
  if (ids.length) bits.push('里程碑 ' + ids.map((id) => '#' + id + (titles[id] ? '（' + titles[id] + '）' : '')).join(' '));
  if (labels.length) bits.push('标签 ' + labels.join('/'));
  if (prefixes.length) bits.push('标题前缀 ' + prefixes.join('/'));
  return bits.join('，') || '（全部开放工单）';
}

/** 心跳一行：写盘时刻按本机时间印出来，后面是距今多少分钟（now 是毫秒时刻，由调用方传）。 */
export function beatLine(state, now) {
  const beat = asText(state && state.beatAt, '');
  if (!beat) return '';
  const at = Date.parse(beat);
  if (!Number.isFinite(at)) return '心跳: ' + beat;
  const d = new Date(at);
  const pad = (n) => String(n).padStart(2, '0');
  const stamp = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
    + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  const minutes = Math.max(0, Math.round((now - at) / 60000));
  return '心跳: ' + stamp + '（距今 ' + minutes + ' 分钟）';
}

/**
 * 一屏给编排者与用户看的现状。state 是账本 state.json，附带 loop（循环名，取自 active.json）；
 * flight 是在跑的并发位置，由命令层现算：{ task, issue, branch, minutes, sinceCommitMin }；
 * openIssues 是这一次拉到的开放工单（与 next 用的是同一份），用来判「下一步」。
 */
export function summarize({ state, tasks, now, flight, openIssues }) {
  if (!Number.isFinite(now)) throw new Error('summarize 要一个毫秒时刻 now，不在里面读时钟');
  const s = state || {};
  const list = Array.isArray(tasks) ? tasks : [];
  const inFlight = Array.isArray(flight) ? flight : [];
  const conc = s.concurrency || {};
  const active = Array.isArray(conc.active) ? conc.active : [];
  const taskState = s.taskState && typeof s.taskState === 'object' ? s.taskState : {};
  const activeIds = new Set(active.map((a) => a.task));
  const doneIds = new Set(list.filter((t) => t.status === 'done').map((t) => t.id));
  const waitMode = asText(s.waitMode, '');
  const lines = [];

  lines.push('循环: ' + asText(s.loop, '') + '  状态: ' + asText(s.status, 'unknown')
    + '  第 ' + asNum(s.iteration, 0) + '/' + asNum(s.maxIterations, 0) + ' 轮'
    + '  无人值守 ' + (s.autoContinue === true ? '开' : '关')
    + (waitMode ? '（收账靠 ' + (waitMode === 'hook' ? 'Stop hook' : '宿主通知：派完就结束回合') + '）' : ''));
  lines.push('范围: ' + scopeDisplay(s.scope));

  if (inFlight.length) {
    lines.push('在跑 ' + inFlight.length + '/' + asNum(conc.max, 0) + ': ' + inFlight.map((f) => {
      const head = [f.task, f.issue ? '#' + f.issue : '', f.branch || ''].filter(Boolean).join(' ');
      const commit = typeof f.sinceCommitMin === 'number' ? '最近提交 ' + f.sinceCommitMin + ' 分钟前' : '看不到提交';
      return head + ' 已 ' + asNum(f.minutes, 0) + ' 分钟，' + commit;
    }).join('；'));
  }

  const stuck = inFlight.filter((f) => asNum(f.minutes, 0) >= STALE_MINUTES
    && typeof f.sinceCommitMin === 'number' && f.sinceCommitMin >= STALE_COMMIT_MINUTES);
  if (stuck.length) {
    lines.push('卡住: ' + stuck.map((f) => [f.task, f.issue ? '#' + f.issue : ''].filter(Boolean).join(' ')
      + ' 已 ' + asNum(f.minutes, 0) + ' 分钟没有新提交（reap 会回收）').join('；'));
  }

  const idOf = (t) => t.id + (t.issue ? ' #' + t.issue : '');

  const forUser = list.filter((t) => taskState[t.id] && taskState[t.id].waitFor === 'user');
  if (forUser.length) lines.push('等你: ' + forUser.map(idOf).join(' '));

  const escalated = list.filter((t) => taskState[t.id] && taskState[t.id].escalated);
  if (escalated.length) lines.push('交回: ' + escalated.map((t) => idOf(t) + ' 第 ' + asNum(taskState[t.id].fails, 0) + ' 次').join('；'));

  // 台账里记得住的阻塞：行内依赖（after）与 refresh 写下的外部阻塞方。
  const waitingOn = (t) => {
    const deps = (t.after || []).filter((id) => !doneIds.has(id));
    const external = ((taskState[t.id] && taskState[t.id].blockedBy) || []).map((n) => '#' + n);
    return deps.concat(external);
  };
  const blocked = list
    .filter((t) => t.status === 'pending' && !activeIds.has(t.id)
      && !String(t.text || '').includes('不在范围')
      && !(taskState[t.id] && (taskState[t.id].escalated || taskState[t.id].external)))
    .map((t) => ({ task: t, on: waitingOn(t) }))
    .filter((b) => b.on.length);
  if (blocked.length) lines.push('依赖挡着: ' + blocked.map((b) => idOf(b.task) + ' 等 ' + b.on.join(' ')).join('；'));

  // 下一步按这一次拉到的开放工单算：台账里记着 pending、GitHub 上已经关掉的单子不能当成下一步。
  // 没有传 openIssues 时不印这一行，宁可缺一行，也不给一个已经关掉的工单号。
  const byIssue = new Map((Array.isArray(openIssues) ? openIssues : []).map((i) => [i.number, i]));
  const next = byIssue.size
    ? list.find((t) => isSelectable(t, { activeIds, taskState, doneIds, issue: byIssue.get(t.issue) }))
    : null;
  if (next) {
    const ready = (next.after || []).length > 0 ? '（依赖已满足）' : '';
    lines.push('下一步: ' + idOf(next) + ready);
  }

  const beat = beatLine(s, now);
  if (beat) lines.push(beat);

  return { lines };
}
