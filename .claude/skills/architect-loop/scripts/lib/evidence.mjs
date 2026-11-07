/**
 * 证据包：解析与核对。纯函数，git 与 gh 通过 deps 注入。
 * deps: { isAncestor(a,b), commitExists(sha), fileAt(sha,path)->string|null,
 *         ciRun(id)->{conclusion,headSha}|null, mainCommitBefore(iso)->sha|'' }
 */
import { startsWithPrefix } from './classify.mjs';

const T = (s) => Date.parse(s);

export function parseEvidence(body) {
  const lines = body.replace(/\r/g, '').trimStart().split('\n');
  const m = /^EVIDENCE:\s*(验收|分诊)\s*@\s*([0-9a-fA-F]{7,40})(.*)$/.exec(lines[0].trim());
  if (!m) return null;
  const parsed = { kind: m[1], head: m[2], redo: /重做/.test(m[3]), ci: null, entries: [] };
  let cur = null;
  const start = (e) => { cur = { text: '', lines: [], ...e }; parsed.entries.push(cur); };
  for (const line of lines.slice(1)) {
    let x;
    if ((x = /^CI[:：]\s*(.*)$/.exec(line.trim()))) {
      const id = /(\d{5,})\s*$/.exec(x[1].trim());
      parsed.ci = id ? id[1] : x[1].trim();
    } else if ((x = /^\s*(\d+)\.\s+(.*)$/.exec(line))) {
      start({ n: Number(x[1]), text: x[2].trim() });
    } else if ((x = /^\s*-\s*前提[:：]\s*(.*?)\s*(?:→|->)\s*(还成立|已经变了)\s*$/.exec(line))) {
      start({ text: x[1], verdict: x[2] });
    } else if ((x = /^\s*-\s*前提[:：]\s*(.*)$/.exec(line))) {
      start({ text: x[1], verdict: null });
    } else if ((x = /^\s*-\s*(test|commit|local|none)[:：]\s*(.*)$/.exec(line))) {
      if (!cur) start({ text: '（没有归属的证据行）' });
      cur.lines.push({ type: x[1], value: x[2].trim() });
    } else if (/^\s*-\s*\S/.test(line)) {
      // 像证据行但格式不对（例如 tests:）：留着，核对时标对不上
      if (!cur) start({ text: '（没有归属的证据行）' });
      cur.lines.push({ type: '?', value: line.replace(/^\s*-\s*/, '').trim() });
    }
  }
  return parsed;
}

/** test 行：`<路径>::<用例名>（<层>）` */
export function parseTestRef(value) {
  const v = value.replace(/[（(][^（()）]*[）)]\s*$/, '').trim();
  const i = v.indexOf('::');
  return i < 0 ? null : { file: v.slice(0, i).trim(), name: v.slice(i + 2).trim() };
}

export function checkLine(line, head, deps) {
  if (line.type === '?') return { status: '对不上', note: '证据行格式不对，只认 test: / commit: / local: / none:' };
  if (line.type === 'local' || line.type === 'none') return { status: '未核对', note: '未经脚本核对' };
  if (line.type === 'commit') {
    const sha = line.value.split(/\s+/)[0];
    if (!deps.commitExists(sha)) return { status: '对不上', note: `提交 ${sha} 不存在` };
    return deps.isAncestor(sha, 'origin/main') ? { status: 'ok' } : { status: '对不上', note: `提交 ${sha} 不在 origin/main 上` };
  }
  const ref = parseTestRef(line.value);
  if (!ref) return { status: '对不上', note: 'test 行不是 <路径>::<用例名>' };
  const text = deps.fileAt(head, ref.file);
  if (text == null) return { status: '对不上', note: `${ref.file} 在 ${head} 上不存在` };
  const bare = ref.name.replace(/\[.*$/, '').split('::').pop().trim();
  const esc = bare.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return bare && new RegExp(`(?<!\\w)${esc}(?!\\w)`).test(text) ? { status: 'ok' } : { status: '对不上', note: `${ref.file} 里没有 ${bare}` };
}

/** 对解析结果逐行核对；problems 是整包的硬伤（头部提交、CI、空包）。 */
export function checkParsed(parsed, deps) {
  const problems = [];
  if (!deps.isAncestor(parsed.head, 'origin/main')) problems.push(`头部提交 ${parsed.head} 不是 origin/main 的祖先`);
  if (!parsed.entries.length) problems.push('没有任何条目');
  const ciItem = { entry: 'CI', type: 'CI', value: parsed.ci || '' };
  if (parsed.kind === '验收') {
    if (!parsed.ci) { problems.push('验收证据包没有 CI: 行'); ciItem.status = '对不上'; ciItem.note = '没有 CI 运行号'; }
    else {
      const run = deps.ciRun(parsed.ci);
      if (!run) problems.push(`CI 运行 ${parsed.ci} 读不到`);
      else if (run.conclusion !== 'success') problems.push(`CI 运行 ${parsed.ci} 结论是 ${run.conclusion || '未结束'}`);
      else if (!deps.isAncestor(run.headSha, parsed.head)) problems.push(`CI 运行 ${parsed.ci} 的提交不是头部提交或其祖先`);
      ciItem.status = problems.some((p) => p.startsWith('CI')) ? '对不上' : 'ok';
    }
  }
  const items = [];
  if (parsed.kind === '验收') items.push(ciItem);
  for (const e of parsed.entries) {
    const label = e.n ? `${e.n}. ${e.text}` : e.text;
    if (!e.lines.length) items.push({ entry: label, type: '-', value: '', status: '对不上', note: '没有证据行' });
    const checked = e.lines.map((l) => ({ entry: label, type: l.type, value: l.value, ...checkLine(l, parsed.head, deps) }));
    items.push(...checked);
    if (e.verdict === null) items.push({ entry: label, type: '前提', value: '', status: '对不上', note: '前提行没有「→ 还成立 | 已经变了」' });
    if (e.verdict === '还成立' && !checked.some((i) => i.status === 'ok')) items.push({ entry: label, type: '前提', value: '', status: '对不上', note: '写了「还成立」，却没有一行核对过的证据' });
  }
  return { problems, items };
}

const RETURN_PREFIXES = ['ARCHITECT:', 'TRIAGE:', 'WAITING:', 'HANDOFF:'];

/**
 * 整张工单的证据判定。
 * ctx: { lastChildClosedAt?, notBefore? }
 */
export function checkComments(comments, ctx, deps) {
  const ev = [...comments].reverse().find((c) => startsWithPrefix(c, 'EVIDENCE:'));
  const out = { exists: false, valid: false, needsRedo: true, judged: false, stale: false, problems: [], items: [], mismatches: 0, unchecked: 0 };
  if (!ev) return { ...out, problems: ['没有证据包'] };
  out.exists = true;
  const parsed = parseEvidence(ev.body);
  if (!parsed) return { ...out, problems: ['EVIDENCE: 第一行格式不对'] };
  Object.assign(out, { kind: parsed.kind, head: parsed.head, redo: parsed.redo, createdAt: ev.createdAt });

  const { problems, items } = checkParsed(parsed, deps);
  out.problems = problems;
  out.items = items;
  out.mismatches = items.filter((i) => i.status === '对不上').length;
  out.unchecked = items.filter((i) => i.status === '未核对').length;

  if (comments.some((c) => (startsWithPrefix(c, 'VERDICT:') || startsWithPrefix(c, 'TRIAGE:')) && T(c.createdAt) > T(ev.createdAt))) {
    out.judged = true;
    out.problems.push('证据包之后已经有 VERDICT:/TRIAGE:');
  }
  if (parsed.kind === '验收' && ctx.lastChildClosedAt) {
    const x = deps.mainCommitBefore(ctx.lastChildClosedAt);
    if (x && !deps.isAncestor(x, parsed.head)) out.stale = true;
  }
  if (parsed.kind === '分诊') {
    const newest = comments.filter((c) => RETURN_PREFIXES.some((p) => startsWithPrefix(c, p))).at(-1);
    if (newest && T(newest.createdAt) > T(ev.createdAt)) out.stale = true;
    if (ctx.notBefore && T(ev.createdAt) < T(ctx.notBefore)) out.stale = true;
  }
  if (out.stale) out.problems.push('证据包过期：比最近一次变化早');
  out.valid = !out.judged && !out.stale && !problems.length;
  // 对不上的行：重做一次（带「重做」标记的包不再重做），重做后判断层当没找到
  out.needsRedo = !out.judged && (!out.valid || (out.mismatches > 0 && !parsed.redo));
  return out;
}
