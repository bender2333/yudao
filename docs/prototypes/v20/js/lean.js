// 项目页：对话（上面带循环图）与设置两页；新建项目的形态卡。
// 线程与循环图的数据存在项目的 p.lean 里，刷新恢复示例。循环图读事项冻结的组织，不按形态名判断。
(function () {
  'use strict';
  const Y20 = window.Y20;
  const O = Y20.org;
  const H = Y20.h;
  const ui = Y20.ui;
  const esc = Y20.esc;
  const X = Y20.EXTRA;
  const A = Y20.actions.register;
  const $ = (id) => document.getElementById(id);
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const T = (min) => Y20.time.add(Y20.app.now(), Math.round(min * 60));
  const DONE = ['adopted', 'open_closed', 'stopped'];
  const unfinished = (it) => it && !DONE.includes(it.status);
  const timers = {};
  let seq = 0;

  // ---------------------------------------------------------------- 形态卡（设计说明 4.12 的表）

  const CARDS = [
    { id: 'three', rot: '按成果', end: '独立核验放行', line: '产品写需求、工程做、质检核验，放行才算完成', dflt: true },
    { id: 'one_own', rot: '直做', end: '开环完成', line: '工程一个角色做完就结束，没有人核验' },
    { id: 'several', rot: '直做', end: '开环完成', line: '工程做并交付，要求不清就问产品，没有人核验' },
    { id: 'ops_preview', name: '产品 · 工程 · 质检 · 运维', rot: '—', end: '—', line: '发布带还没有', off: true }
  ];
  function cards(act, current) {
    return CARDS.map((k) => {
      const c = O.compose({ form: k.id, changes: {} });
      const name = k.name || c.formName;
      const marks = '<span class="lp-marks"><span class="lp-mark">轮转：' + esc(k.rot) + '</span><span class="lp-mark' + (k.end === '独立核验放行' ? ' is-ver' : '') + '">结束：' + esc(k.end) + '</span></span>';
      return '<button type="button" class="ln-card lp-card' + (k.off ? ' is-off' : '') + (current === k.id ? ' is-current' : '') + '"' + (k.off ? ' disabled aria-disabled="true"' : ' data-act="' + act + '" data-form="' + k.id + '"') + '>' +
        '<strong>' + esc(name) + (k.dflt ? ui.tag('默认') : '') + (current === k.id ? ui.tag('现在用的') : '') + '</strong>' + marks + '<small>' + esc(k.line) + '</small>' +
        '<div class="lp-mini" aria-hidden="true">' + graphBody(c, [], { mini: true }) +
        (c.sources.some((x) => x.id === 'fault') ? '<div class="lp-mini-fault"><span class="lp-pill">图外</span> → 故障记录 → ' + esc(nm(null, c.sources.find((x) => x.id === 'fault').to)) + '，开一件新事项</div>' : '') + '</div></button>';
    }).join('');
  }

  // ---------------------------------------------------------------- 组织读出来的几样：名字、标签、一行说明

  const recv = (c) => O.firstReceivers(c)[0] || c.depts[0];
  const nm = (p, id) => O.deptName(p, id);
  const isOut = (d) => d && d.who && d.who.type === 'outsourced';
  const isSub = (d) => d && d.who && d.who.type === 'suborg';
  const indep = (p) => { const q = ((p.org.changes || {}).depts || {}).quality; return Boolean(q && q.added && q.verifies); };
  // 形态名：发布带的名字；加了独立核验时在后面加「· 质检」
  function formLabel(p) {
    const c = p.composed;
    let name = c.formName;
    const added = c.depts.filter((d) => d.src === 'added' && d.verifies);
    if (added.length) name += added.map((d) => ' · ' + d.name).join('');
    // 改过几处：不算加独立核验、由谁做与观察者（它们不经高级，一步生效）
    const ch = Object.assign({}, p.org.changes); delete ch.observers;
    const n = O.count(ch) - added.length - c.depts.filter((d) => d.src !== 'added' && d.who && d.who.type !== 'own').length;
    return { name, changed: Math.max(0, n) };
  }
  Y20.formLabel = formLabel;
  function tags(p) {
    const c = p.composed, f = formLabel(p), e = O.ending(c), vs = O.verifiers(c);
    return ['「' + f.name + '」' + (f.changed ? '（改过 ' + f.changed + ' 处）' : ''), O.ROTATIONS[c.rotation] || c.rotation, vs.length ? '核验：' + vs.map((v) => v.name).join('、') : '开环完成' + (e.outsourced ? ' · 外包' : '')];
  }
  function orgLine(p) {
    const c = p.composed, f = formLabel(p), vs = O.verifiers(c), cp = O.completer(c);
    const outs = c.depts.filter(isOut).map((d) => d.name + '由外部 agent（' + (d.who.agent || '未选') + '）做');
    const subs = c.depts.filter(isSub).map((d) => d.name + '由一个小组做');
    const who = c.depts.length === 1 ? '只有一个职能' : c.rotation === 'direct' ? (cp ? cp.name + '交付' : '') + c.depts.filter((d) => !d.produces.length && !d.verifies).map((d) => '、' + d.name + '接询问').join('') : '按成果轮转';
    const ver = vs.length ? vs.map((v) => v.name).join('、') + '核验后放行' + (c.rotation === 'direct' ? '，轮转仍是直做' : '') : '没有人核验';
    const tail = !vs.length && c.depts.length > 1 ? '；加独立核验就会等它放行' : '';
    return '「' + f.name + '」，' + [who].concat(outs, subs).filter(Boolean).join('，') + '，' + ver + tail;
  }

  // ---------------------------------------------------------------- 循环图的布局：主线与旁边的职能

  function layout(c) {
    const r = recv(c), ds = c.depts;
    if (!r) return { chain: [], side: [] };
    const chain = [r];
    const maker = c.rotation === 'direct' ? O.completer(c) : ds.find((d) => d.produces.includes(c.adopt));
    if (maker && maker !== r) {
      // 从接来源的职能沿「交出 → 关注」走到交出最后采纳成果的职能
      const prev = new Map([[r.id, null]]), q = [r];
      while (q.length) {
        const a = q.shift();
        ds.forEach((b) => { if (!prev.has(b.id) && a.produces.some((k) => b.watches.includes(k))) { prev.set(b.id, a); q.push(b); } });
      }
      const path = [];
      for (let x = prev.has(maker.id) ? maker : null; x && x !== r; x = prev.get(x.id)) path.unshift(x);
      if (!path.length) path.push(maker);
      path.forEach((d) => { if (!chain.includes(d)) chain.push(d); });
    }
    O.verifiers(c).forEach((v) => { if (!chain.includes(v)) chain.push(v); });
    const side = ds.filter((d) => !chain.includes(d)).map((d) => {
      const out = chain.find((x) => d.produces.some((k) => x.watches.includes(k)));
      const into = chain.find((x) => x.produces.some((k) => d.watches.includes(k)));
      const ver = chain.find((x) => x.verifies && d.watches.includes(x.verifies.kind)); // 关注被核验的那种成果：放在核验角色旁边
      const partner = out || ver || into || maker || chain[0];
      return { d, partner, ask: !d.produces.length && !d.verifies && c.rotation === 'direct' };
    });
    return { chain, side, maker };
  }

  // 没有事项时（形态卡、空项目）按组织推出的箭头：只写成果种类，不写版本
  function structArrows(c, L) {
    const out = [], ix = (d) => L.chain.indexOf(d);
    const vs = O.verifiers(c);
    out.push({ from: 'src', to: L.chain[0] ? L.chain[0].id : 'end', name: c.depth > 0 ? '任务' : '原文' });
    L.chain.forEach((d, i) => {
      d.produces.forEach((k) => {
        const next = L.chain[i + 1], back = L.chain.slice(0, i).reverse().find((x) => x.watches.includes(k));
        if (next && (next.watches.includes(k) || (next.verifies && next.verifies.kind === k))) out.push({ from: d.id, to: next.id, name: O.kindName(c, k) });
        else if (back && ix(back) === i - 1) out.push({ from: d.id, to: back.id, name: O.kindName(c, k) });
        else if (i === L.chain.length - 1 && !vs.length) out.push({ from: d.id, to: 'end', name: O.kindName(c, k) });
      });
    });
    L.side.forEach((s) => s.d.produces.forEach((k) => out.push({ from: s.d.id, to: s.partner.id, name: O.kindName(c, k) })));
    return out;
  }

  // ---------------------------------------------------------------- 循环图：画一个事项（或一份组织）

  function chip(a, opts) {
    const back = opts.back;
    const v = a.v ? ' v' + a.v : '';
    const round = a.round ? '<small>第 ' + a.round + ' 轮</small>' : '';
    const verdict = a.verdict ? '<span class="lp-verdict is-' + a.verdict.t + '">' + esc(a.verdict.t === 'reject' ? a.verdict.by + '打回' : a.verdict.t === 'pass' ? a.verdict.by + '通过' : '放行 · ' + a.verdict.by) + '</span>' : '';
    const body = '<span class="lp-dir">' + (back ? '←' : opts.out ? '↗' : opts.up ? '↑' : opts.down ? '↓' : '→') + '</span><span class="lp-kind">' + esc(a.name + v) + '</span>' + round + verdict;
    if (opts.mini || a.i === undefined) return '<span class="lp-chip is-struct' + (back ? ' is-back' : '') + '">' + body + '</span>';
    return '<button type="button" class="lp-chip' + (back ? ' is-back' : '') + (a.cur ? ' is-cur' : '') + (opts.on ? ' is-on' : '') + '" data-act="lp.arrow" data-i="' + a.i + '" title="看这一版与差异">' + body + '</button>';
  }

  function nodeHtml(c, d, ctx) {
    const marks = (d.verifies ? '<span class="lp-badge is-ver" title="做核验的节点：它的角色是核验角色">核验</span>' : '') +
      (isOut(d) ? '<span class="lp-badge is-out">' + esc(d.who.agent || '外部 agent') + '</span>' : '') +
      (isSub(d) ? '<span class="lp-badge is-sub" title="由子组织做，能点进去看内部的循环图">子组织</span>' : '') +
      (ctx.oldOnly && ctx.oldOnly.includes(d.id) ? '<span class="lp-badge">只在旧组织里</span>' : '');
    const outNote = isOut(d) ? '<small class="lp-note">推理档位由它定</small>' : '';
    if (ctx.mini) return '<span class="lp-node is-mini' + (d.verifies ? ' is-ver' : '') + '"><b>' + esc(d.name) + '</b>' + marks + '</span>';
    const st = ctx.state && ctx.state(d) || '';
    const asks = ctx.asks ? ctx.asks(d) : 0, others = ctx.others ? ctx.others(d) : 0;
    const flags = (asks ? '<span class="lp-flag is-ask" data-act="lp.jump" data-who="' + esc(d.id) + '" title="跳到对话里要你决定的那条">要你决定 ' + asks + '</span>' : '') +
      (others ? '<span class="lp-flag" title="别的事项正在这个职能">另 ' + others + ' 件</span>' : '');
    return '<div class="lp-node' + (d.verifies ? ' is-ver' : '') + (ctx.working === d.id ? ' is-working' : '') + (ctx.sel === d.id ? ' is-on' : '') + '" role="button" tabindex="0" data-act="lp.node" data-dept="' + esc(d.id) + '" aria-label="' + esc(d.name) + '：看在做什么、给它发指导">' +
      '<b>' + esc(d.name) + '</b><span class="lp-node-marks">' + marks + '</span>' + outNote + (st ? '<small class="lp-state">' + esc(st) + '</small>' : '') +
      (isSub(d) && ctx.inner ? '<button type="button" class="y20-link lp-in" data-act="lp.inner" data-dept="' + esc(d.id) + '">看内部 ›</button>' : '') + (flags ? '<span class="lp-flags">' + flags + '</span>' : '') + '</div>';
  }

  // c：冻结的组织；arrows：这个事项的箭头（空时按组织推出）；opts：mini / item / end / src / ctx
  function graphBody(c, arrows, opts) {
    const L = layout(c), mini = Boolean(opts.mini);
    const ctx = Object.assign({ mini }, opts.ctx || {});
    const list = arrows.length ? arrows : structArrows(c, L);
    const col = (d) => L.chain.indexOf(d);
    const at = (id) => { const k = col(c.depts.find((d) => d.id === id)); return k < 0 ? NaN : k; }; // 旁边的职能不在主线上
    const between = (i) => list.filter((a) => {
      const f = a.from === 'src' ? -1 : at(a.from);
      const t = a.to === 'end' ? L.chain.length : at(a.to);
      return (f === i - 1 && t === i) || (t === i - 1 && f === i);
    });
    const edge = (i) => {
      const as = between(i);
      return '<div class="lp-edge">' + (as.map((a) => chip(a, { mini, back: a.from !== 'src' && a.to !== 'end' && col(c.depts.find((d) => d.id === a.to)) < col(c.depts.find((d) => d.id === a.from)), on: opts.arrow === a.i })).join('') || '<span class="lp-line" aria-hidden="true"></span>') + '</div>';
    };
    // 运维发现的故障不算这一圈的来源：它开一件新事项，在图外另画
    const srcs = c.sources.filter((s) => s.to === (L.chain[0] || {}).id && s.id !== 'fault').map((s) => s.name);
    const src = opts.src || (c.depth > 0 ? '上一层交来的任务' : mini ? srcs[0] : srcs.join('、'));
    const end = opts.end || (mini ? (O.verifiers(c).length ? O.verifiers(c).map((v) => v.name).join('、') + '放行' : '开环完成') : endText(c, null));
    const cells = ['<div class="lp-pill is-src">' + esc(src) + '</div>'];
    L.chain.forEach((d, i) => { cells.push(edge(i)); cells.push(nodeHtml(c, d, ctx)); });
    cells.push(edge(L.chain.length));
    cells.push('<div class="lp-pill is-end' + (opts.endCls ? ' ' + opts.endCls : '') + '">' + esc(end) + '</div>');
    const n = cells.length;
    // 旁边的职能：放在它对接的那个主线职能的上方，中间一格写它们之间的往来
    const sideBy = {};
    L.side.forEach((s) => { (sideBy[col(s.partner)] = sideBy[col(s.partner)] || []).push(s); });
    let top = '';
    if (L.side.length) {
      const sideCells = [], linkCells = [];
      for (let k = 0; k < n; k++) {
        const ci = (k - 2) / 2; // 节点所在的格：2、4、6……
        const group = Number.isInteger(ci) && ci >= 0 ? sideBy[ci] : null;
        if (!group) { sideCells.push('<div></div>'); linkCells.push('<div></div>'); continue; }
        sideCells.push('<div class="lp-side">' + group.map((s) => nodeHtml(c, s.d, ctx)).join('') + '</div>');
        linkCells.push('<div class="lp-vlink">' + group.map((s) => {
          if (s.ask) return '<span class="lp-chip is-ask' + (mini ? ' is-struct' : '') + '"' + (mini ? '' : ' data-act="lp.node" data-dept="' + esc(s.d.id) + '" role="button" tabindex="0"') + '><span class="lp-dir">⇅</span><span class="lp-kind">询问与回答' + (ctx.askCount ? ' ' + ctx.askCount(s.d) + ' 条' : '') + '</span></span>';
          const as = list.filter((a) => (a.from === s.d.id && (a.to === s.partner.id || a.to === 'end')) || (a.to === s.d.id && a.from === s.partner.id));
          return as.map((a) => chip(a, { mini, out: a.to === 'end', down: a.from === s.d.id, up: a.to === s.d.id, on: opts.arrow === a.i })).join('') || '<span class="lp-vline" aria-hidden="true"></span>';
        }).join('') + '</div>');
      }
      top = sideCells.join('') + linkCells.join('');
    }
    const tpl = cells.map((x, k) => (k % 2 === 1 ? 'minmax(max-content, 1fr)' : 'auto')).join(' ');
    return '<div class="lp-grid' + (mini ? ' is-mini' : '') + (L.side.length ? ' has-side' : '') + '" style="grid-template-columns:' + tpl + '">' + top + cells.join('') + '</div>';
  }

  // 结束：有核验角色时写放行与核验角色的显示名；没有时写开环完成（外包时注明）
  function endText(c, it) {
    const vs = O.verifiers(c), e = O.ending(c), names = vs.map((v) => v.name).join('、');
    const up = c.depth > 0 ? '交回' + (c.parentName || '上一层') : '';
    if (c.depth > 0) return it && DONE.includes(it.status) ? up : '还没' + up;
    if (it && it.status === 'adopted') return '完成 · ' + names + '放行';
    if (it && it.status === 'open_closed') return '开环完成：没有人核验' + (e.outsourced ? ' · 外包' : '');
    if (it && it.status === 'stopped') return '已停止';
    return vs.length ? names + '放行才结束' : '开环完成' + (e.outsourced ? ' · 外包' : '');
  }

  // 窄屏：一行，节点名与当前箭头
  function lineHtml(c, arrows, it) {
    const L = layout(c);
    const cur = arrows.slice().reverse().find((a) => a.from !== 'src') || arrows[arrows.length - 1];
    const toName = (id) => (id === 'end' ? endText(c, it) : (c.depts.find((d) => d.id === id) || {}).name || '');
    return '<div class="lp-oneline">' + L.chain.map((d) => '<button type="button" class="y20-link" data-act="lp.node" data-dept="' + esc(d.id) + '">' + esc(d.name) + (d.verifies ? '（核验）' : '') + (isOut(d) ? '（' + esc(d.who.agent) + '）' : '') + (isSub(d) ? '（子组织）' : '') + '</button>').join(' → ') +
      (cur ? '<span class="lp-oneline-cur">' + (cur.i !== undefined ? '<button type="button" class="y20-link" data-act="lp.arrow" data-i="' + cur.i + '">' : '<span>') + esc(cur.name + (cur.v ? ' v' + cur.v : '') + (cur.round ? ' · 第 ' + cur.round + ' 轮' : '') + ' → ' + toName(cur.to)) + (cur.verdict ? ' · ' + (cur.verdict.t === 'reject' ? cur.verdict.by + '打回' : '放行') : '') + (cur.i !== undefined ? '</button>' : '</span>') + '</span>' : '') + '</div>';
  }

  // ---------------------------------------------------------------- 线程的数据

  function seed(p) {
    if (p.demoThread) return Object.assign(base(), clone(p.demoThread));
    const s = base();
    const you = (item, text, tag, m) => ({ t: 'you', item, text, tag, at: T(m) });
    const fold = (item, key, lab, roles, kids, m) => ({ t: 'fold', item, key, lab, roles, open: false, kids: kids.map((k, i) => ({ who: k[0], text: k[1], at: T(m + i) })) });
    const ask = (item, who, text, m, options) => ({ t: 'ask', item, who, text, options: options || ['要', '不要'], answer: '', at: T(m) });
    const ar = (item, from, to, name, v, round, extra) => Object.assign({ item, from, to, name, v, round, at: T(-1) }, extra || {});
    const d = (file, a, b) => ['@@ ' + file, '- ' + a, '+ ' + b];
    if (p.id === 'blog') {
      s.cur = 'w14';
      s.arrows = [ar('w13', 'src', 'engineering', '原文', 1, 1, { text: '把旧站点的 128 篇文章迁到新站点' }),
        ar('w13', 'engineering', 'end', '交付', 1, 1, { text: '128 篇文章已转成新格式，链接保持', files: ['content/posts/（128 个文件）', 'content/_index.md'], diff: ['@@ content/_index.md', '- 共 128 篇，旧站点格式', '+ 共 128 篇，新站点格式', '@@ content/posts/2024/05/hello.md', '- <!-- more -->', '+ {{< more >}}'] }),
        ar('w14', 'src', 'engineering', '原文', 1, 1, { text: '把首页的文案改成新站点的介绍' })];
      s.msgs = [{ t: 'sep', item: 'w13' }, you('w13', '把旧站点的 128 篇文章迁到新站点', '开始一个新事项', -270),
        fold('w13', 'prog', '工程的进展', ['engineering'], [['engineering', '开始做了。先读旧站点的文章清单。'], ['engineering', '128 篇已转成新格式，正在检查链接。']], -268),
        { t: 'done', who: 'engineering', item: 'w13', text: '做完了：128 篇已转成新格式，链接保持。开环完成：没有人核验', ai: 1, at: T(-200) },
        { t: 'sep', item: 'w14' }, you('w14', '把首页的文案改成新站点的介绍', '开始一个新事项', -9), you('w14', '保留三个栏目', '给工程的指导', -6),
        fold('w14', 'prog', '工程的进展', ['engineering'], [['engineering', '在改首页文案，三个栏目都保留了。']], -4),
        ask('w14', 'engineering', '首页要不要保留旧的访问计数？', -3)];
      return s;
    }
    if (p.id === 'logclean') {
      s.cur = 'w8';
      s.arrows = [ar('w7', 'src', 'engineering', '原文', 1, 1, { text: '把服务器上 30 天前的日志清掉，只留最近的' }),
        ar('w7', 'engineering', 'end', '交付', 1, 1, { text: 'OpenCode 交回的快照与差异：清掉 30 天前的日志 412 个文件，最近 7 天的没有动', files: ['scripts/clean_logs.sh', 'scripts/clean_logs_test.sh'], diff: d('scripts/clean_logs.sh', 'find /var/log -mtime +7 -delete', 'find /var/log -type f -mtime +30 -delete') }),
        ar('w8', 'src', 'engineering', '原文', 1, 1, { text: '加一个按目录大小清理的开关' })];
      s.msgs = [{ t: 'sep', item: 'w7' }, you('w7', '把服务器上 30 天前的日志清掉，只留最近的', '开始一个新事项', -270),
        fold('w7', 'prog', 'OpenCode 的进展', ['engineering'], [['engineering', '快照进，OpenCode 开始在工作区里做。'], ['engineering', 'OpenCode 交回快照与差异，经写入口成为提案。']], -260),
        { t: 'done', who: 'engineering', item: 'w7', text: '做完了：清掉 412 个文件，最近 7 天的没有动。开环完成：没有人核验 · 外包（OpenCode）', ai: 1, at: T(-200) },
        { t: 'sep', item: 'w8' }, you('w8', '加一个按目录大小清理的开关', '开始一个新事项', -50),
        fold('w8', 'prog', 'OpenCode 的进展', ['engineering'], [['engineering', '快照进，OpenCode 在写按目录大小清理的开关。']], -48)];
      return s;
    }
    if (p.id === 'signup') {
      s.cur = 'w17';
      s.arrows = [ar('w18', 'src', 'engineering', '原文', 1, 1, { text: '活动页上写清楚时间、地点、报名截止日' }),
        ar('w18', 'engineering', 'end', '交付', 1, 1, { text: '活动页文案已改，三处时间保持一致', files: ['pages/event.md'], diff: d('pages/event.md', '活动时间待定', '活动时间：周六 14:00，地点与截止日同页') }),
        ar('w17', 'src', 'engineering', '原文', 1, 1, { text: '做报名表单：姓名、手机号、参加人数，人数到上限就不能再报' })];
      s.msgs = [{ t: 'sep', item: 'w18' }, you('w18', '活动页上写清楚时间、地点、报名截止日', '开始一个新事项', -330),
        { t: 'done', who: 'engineering', item: 'w18', text: '做完了：活动页文案已改，三处时间保持一致。开环完成：没有人核验', ai: 1, at: T(-300) },
        { t: 'sep', item: 'w17' }, you('w17', '做报名表单：姓名、手机号、参加人数，人数到上限就不能再报', '开始一个新事项', -40),
        fold('w17', 'pe', '工程与产品往来', ['engineering', 'product'], [['engineering', '报名要不要限人数？'], ['product', '每场 200 人。'], ['engineering', '满了怎么提示？']], -36),
        ask('w17', 'engineering', '满员后要候补名单吗？', -30)];
      return s;
    }
    if (p.id === 'orders') {
      s.cur = 'w1';
      const files = ['orders/export.ts', 'orders/export.test.ts'];
      s.arrows = [
        ar('w0', 'src', 'product', '原文', 1, 1, { text: '把订单状态改成明确的状态机，不再用散落的 if' }),
        ar('w0', 'product', 'engineering', 'PRD', 1, 1, { text: '状态机的 PRD：6 个状态、9 条转换' }),
        ar('w0', 'engineering', 'quality', '交付', 1, 1, { verdict: { t: 'reject', by: '质检' }, text: '状态机第 1 版', files: ['orders/state.ts'], diff: d('orders/state.ts', 'if (o.paid && !o.cancelled) {', 'transition(o, "paid") // 已取消时没有拦住') }),
        ar('w0', 'quality', 'engineering', '缺陷记录', 1, 1, { text: '已取消的订单还能被标记为已支付；转换表缺「发货中 → 已取消」' }),
        ar('w0', 'engineering', 'quality', '交付', 2, 2, { verdict: { t: 'release', by: '质检' }, text: '状态机第 2 版：6 个状态、9 条转换，12 条用例通过', files: ['orders/state.ts', 'orders/state.test.ts'], diff: d('orders/state.ts', 'transition(o, "paid") // 已取消时没有拦住', 'if (o.state !== "cancelled") transition(o, "paid")') }),
        ar('w2', 'src', 'product', '原文', 1, 1, { text: '订单列表要能分页，每页 50 条' }),
        ar('w2', 'product', 'engineering', 'PRD', 1, 1, { text: '订单列表分页：每页 50 条，按创建时间倒序' }),
        ar('w2', 'engineering', 'quality', '交付', 1, 1, { verdict: { t: 'reject', by: '质检' }, text: '分页第 1 版', files: ['orders/list.ts'], diff: d('orders/list.ts', 'offset = page * 50', 'offset = (page - 1) * 50 // 第 1 页从 0 开始') }),
        ar('w2', 'quality', 'engineering', '缺陷记录', 1, 1, { text: '最后一页少一条：总数正好是 50 的倍数时多出一页空页' }),
        ar('w2', 'engineering', 'quality', '交付', 2, 2, { text: '分页第 2 版：最后一页与空页都改了（质检在核验）', files: ['orders/list.ts'], diff: d('orders/list.ts', 'pages = Math.floor(total / 50) + 1', 'pages = Math.ceil(total / 50)') }),
        ar('w1', 'src', 'product', '原文', 1, 1, { text: '把订单导出成 CSV 文件' }),
        ar('w1', 'product', 'engineering', 'PRD', 1, 1, { text: '导出订单为 CSV：按创建时间倒序，最多 5 万行；orders-日期.csv，UTF-8 带 BOM' }),
        ar('w1', 'engineering', 'quality', '交付', 1, 1, { verdict: { t: 'reject', by: '质检' }, text: '导出第 1 版', files, diff: d('orders/export.ts', 'amount.toFixed(2)', 'Math.round(amount * 100) / 100') }),
        ar('w1', 'quality', 'engineering', '缺陷记录', 1, 1, { text: '金额列四舍五入错一分：19.995 导出成 19.99' }),
        ar('w1', 'engineering', 'quality', '交付', 2, 2, { verdict: { t: 'reject', by: '质检' }, text: '导出第 2 版：金额改用分计算', files, diff: d('orders/export.ts', 'rows = await db.all(query)', 'for await (const row of db.stream(query))') }),
        ar('w1', 'quality', 'engineering', '缺陷记录', 2, 2, { text: '5 万行时导出超时（62 秒，上限 30 秒）' })
      ];
      s.msgs = [
        { t: 'sep', item: 'w0' }, you('w0', '把订单状态改成明确的状态机，不再用散落的 if', '开始一个新事项', -700),
        fold('w0', 'pe', '产品与工程往来', ['product', 'engineering'], [['product', '状态机的 PRD 第 1 版：6 个状态、9 条转换。'], ['engineering', '已取消的订单还能退款吗？'], ['product', '不能，已取消只能终止。']], -690),
        fold('w0', 'eq', '工程与质检往来', ['engineering', 'quality'], [['engineering', '交付 v1，请核验。'], ['quality', '交付 v1 打回：已取消的订单还能被标记为已支付。'], ['engineering', '交付 v2 已改，请核验。'], ['quality', '12 条用例全部通过。']], -640),
        { t: 'rel', who: 'quality', item: 'w0', text: '放行：质检核验交付 v2 通过', ai: 4, at: T(-600) },
        { t: 'sep', item: 'w2' }, you('w2', '订单列表要能分页，每页 50 条', '开始一个新事项', -320),
        fold('w2', 'eq', '工程与质检往来', ['engineering', 'quality'], [['quality', '交付 v1 打回：总数是 50 的倍数时多出一页空页。'], ['engineering', '交付 v2 已改，请核验。']], -300),
        { t: 'sep', item: 'w1' }, you('w1', '把订单导出成 CSV 文件', '开始一个新事项', -180),
        fold('w1', 'pe', '产品与工程往来', ['product', 'engineering'], [['product', 'PRD v1：按创建时间倒序，最多 5 万行。'], ['engineering', '文件名与编码怎么定？'], ['product', 'orders-日期.csv，UTF-8 带 BOM。']], -176),
        fold('w1', 'eq', '工程与质检往来', ['engineering', 'quality'], [['quality', '交付 v1 打回：金额列四舍五入错一分。'], ['engineering', '交付 v2 改用分计算。'], ['quality', '交付 v2 打回：5 万行时导出超时。'], ['engineering', '在写交付 v3：改成流式写出。']], -120),
        ask('w1', 'product', '金额列要不要带货币符号？', -20, ['不带，只写数字', '带 ¥'])
      ];
      return s;
    }
    if (p.id === 'dash') {
      s.cur = 'w15';
      s.arrows = [ar('w16', 'src', 'engineering', '原文', 1, 1, { text: '做一个月度汇总查询' }),
        ar('w16', 'engineering', 'end', '交付', 1, 1, { text: '月度汇总查询：按月份、按区域', files: ['queries/monthly.sql'], diff: d('queries/monthly.sql', 'GROUP BY day', 'GROUP BY month, region') }),
        ar('w15', 'src', 'engineering', '原文', 1, 1, { text: '销售报表能导出成表格' }),
        ar('w15', 'engineering', 'end', '交付', 1, 1, { text: '导出第 1 版（工程自己发现列宽不对，正在做第 2 轮）', files: ['report/export.ts'], diff: d('report/export.ts', 'width: auto', 'width: 18') })];
      s.msgs = [{ t: 'sep', item: 'w16' }, you('w16', '做一个月度汇总查询', '开始一个新事项', -1400),
        { t: 'done', who: 'engineering', item: 'w16', text: '做完了：按月份、按区域汇总。开环完成：没有人核验', ai: 1, at: T(-1300) },
        { t: 'sep', item: 'w15' }, you('w15', '销售报表能导出成表格', '开始一个新事项', -220),
        fold('w15', 'prog', '工程的进展', ['engineering'], [['engineering', '第 1 轮：导出能用，列宽不对。'], ['engineering', '第 2 轮：在改列宽，又碰到了第 1 轮改过的那段。']], -200),
        Object.assign(ask('w15', 'observer', '振荡检测发现「销售报表导出」第 2 轮和第 1 轮在改同一段代码，可能在来回打转。要停下来看看吗？', -12, ['先停下，我来看', '继续做']), { by: '观察者 · 振荡检测' })];
      return s;
    }
    if (p.id === 'firmware') {
      s.cur = 'w11';
      s.arrows = [ar('w12', 'src', 'product', '原文', 1, 1, { text: '升级失败时设备要自动回到上一个版本' }),
        ar('w12', 'product', 'engineering', 'PRD', 1, 1, { text: '升级失败自动回滚：双分区，启动三次失败就切回旧分区' }),
        ar('w12', 'engineering', 'quality', '交付', 1, 1, { verdict: { t: 'release', by: '质检' }, text: '回滚交付第 1 版：5 条检验全部通过', files: ['boot/rollback.c'], diff: d('boot/rollback.c', 'boot(active)', 'if (fails >= 3) boot(previous); else boot(active);') }),
        ar('w12', 'n2', 'end', '升级说明', 1, 1, { text: '回滚的现场升级说明：双分区的切换步骤与三次启动失败后的处理' }),
        ar('w11', 'src', 'product', '原文', 1, 1, { text: '升级包要校验签名，签名不对就不升级' }),
        ar('w11', 'product', 'engineering', 'PRD', 1, 1, { text: '升级包签名校验：公钥烧在只读区，升级前先验签' }),
        ar('w11', 'n1', 'engineering', '适配包', 1, 1, { text: '3 块板子的验签适配包，启动冒烟通过 2 块，1 块待查' })];
      // 工程的子组织：一轮工作开一个子事项，内部的箭头单独记
      s.innerArrows = { 'w11:engineering': [ar('w11', 'src', 'architect', '任务', 1, 1, { text: '上一层交来的任务：按 PRD v1 做签名校验' }),
        ar('w11', 'architect', 'lead', '计划', 1, 1, { text: '计划 v1：先读公钥、再验签、失败不写入' }),
        ar('w11', 'explorer', 'architect', '调研结论', 1, 1, { text: '三块板子的只读区地址不同，要按型号取' }),
        ar('w11', 'lead', 'reviewer', '改动', 1, 1, { verdict: { t: 'reject', by: '审查者' }, text: '改动 v1', files: ['ota/verify.c'], diff: d('ota/verify.c', 'key = read_rom(0x1000)', 'key = read_rom(rom_base(board))') }),
        ar('w11', 'reviewer', 'lead', '审查意见', 1, 1, { text: '验签失败时没有清掉已写入的半包' }),
        ar('w11', 'lead', 'reviewer', '改动', 2, 2, { text: '改动 v2：验签失败先清半包（审查者在审）', files: ['ota/verify.c'], diff: d('ota/verify.c', 'return -1;', 'erase(staging); return -1;') })],
      'w12:engineering': [ar('w12', 'src', 'architect', '任务', 1, 1, { text: '上一层交来的任务：按 PRD v1 做回滚' }),
        ar('w12', 'architect', 'lead', '计划', 1, 1, { text: '计划 v1：双分区与启动计数' }),
        ar('w12', 'lead', 'reviewer', '改动', 1, 1, { verdict: { t: 'pass', by: '审查者' }, text: '改动 v1' })] };
      s.msgs = [{ t: 'sep', item: 'w12' }, you('w12', '升级失败时设备要自动回到上一个版本', '开始一个新事项', -1300),
        fold('w12', 'eq', '工程与质检往来', ['engineering', 'quality'], [['engineering', '交付 v1（内部小组交回的改动），请核验。'], ['quality', '5 条检验全部通过。']], -1260),
        { t: 'rel', who: 'quality', item: 'w12', text: '放行：质检核验交付 v1 通过', ai: 2, at: T(-1250) },
        { t: 'sep', item: 'w11' }, you('w11', '升级包要校验签名，签名不对就不升级', '开始一个新事项', -230),
        fold('w11', 'pe', '产品与工程往来', ['product', 'engineering'], [['product', 'PRD v1：公钥烧在只读区，升级前先验签。']], -220),
        fold('w11', 'in', '工程的内部小组往来', ['engineering'], [['engineering', '子事项 D-1.1：工程架构师拆了计划，主程在写改动 v2，审查者打回过一次。']], -100)];
      return s;
    }
    // 其余项目：每个还没结束的事项一条原文箭头
    const items = p.items.filter(unfinished);
    s.cur = items.length ? (items.find((it) => it.status === 'working') || items[0]).id : null;
    p.items.slice().reverse().forEach((it) => {
      const c = it.org ? it.org.composed : p.composed, r = O.firstReceivers(c)[0];
      s.arrows.push(ar(it.id, 'src', r ? r.id : 'end', '原文', 1, 1, { text: it.title }));
      if (it.status === 'adopted') { const L = layout(c); const v = O.verifiers(c)[0]; if (L.maker && v) s.arrows.push(ar(it.id, L.maker.id, v.id, O.kindName(c, c.adopt || L.maker.produces[0]), 1, it.round || 1, { verdict: { t: 'release', by: v.name }, text: it.reason })); }
      s.msgs.push({ t: 'sep', item: it.id }, { t: 'you', item: it.id, text: it.title, tag: '开始一个新事项', at: it.created });
      if (unfinished(it)) s.msgs.push({ t: 'fold', item: it.id, key: 'prog', lab: '工作进展', roles: [it.dept || 'engineering'], open: false, kids: [{ who: it.dept || 'engineering', text: it.reason || '正在工作。' }] });
    });
    return s;
  }
  function base() { return { arrows: [], innerArrows: {}, msgs: [], cur: null, sel: null, queue: [], to: null, manual: false, openItems: {}, panel: null, inner: null }; }
  const st = (p) => p.lean || (p.lean = seed(p));
  Y20.thread = { state: st, templates: cards };
  const active = (p) => { const it = st(p).cur && H.item(p, st(p).cur); return unfinished(it) ? it : null; };
  const here = (p) => Y20.state.route.params.project === p.id && $('ln-thread');
  const push = (p, m) => { m.at = m.at || T(++seq); st(p).msgs.push(m); };
  const pushArrow = (p, a) => { a.at = T(++seq); st(p).arrows.push(a); return st(p).arrows.length - 1; };
  function readGuidance(p, ids, item) { st(p).msgs.filter((m) => ids.includes(m.target) && !m.readAt && (!m.item || m.item === item)).forEach((m) => { m.readAt = T(++seq); }); }
  function fold(p, it, key, lab, roles, who, text) {
    const ms = st(p).msgs;
    let f = ms.slice().reverse().find((m) => m.t === 'fold' && m.item === (it ? it.id : '') && m.key === key);
    if (!f) ms.push(f = { t: 'fold', item: it ? it.id : '', key, lab, roles, open: false, kids: [] });
    f.kids.push({ who, text, at: T(++seq) });
  }
  const openAsks = (p) => st(p).msgs.filter((m) => m.t === 'ask' && !m.answer && p.items.some((it) => it.id === m.item && unfinished(it)));
  Y20.leanDecisions = (p) => openAsks(p).length + H.decisions(p.id).length;

  // ---------------------------------------------------------------- 选中的事项与它冻结的组织

  function shown(p) {
    const s = st(p);
    const last = s.msgs.filter((m) => m.t === 'sep').map((m) => m.item).pop();
    const id = s.sel && H.item(p, s.sel) ? s.sel : (active(p) || {}).id || s.cur || last;
    return id ? H.item(p, id) : null;
  }
  const orgOf = (p, it) => (it && it.org ? it.org.composed : p.composed);
  function arrowsOf(p, it) { return it ? st(p).arrows.map((a, i) => Object.assign({ i }, a)).filter((a) => a.item === it.id) : []; }

  // ---------------------------------------------------------------- 收件人

  function options(p) {
    const it = active(p), c = orgOf(p, it), s = st(p), r = recv(c), o = [{ k: 'new', label: '开始一个新事项' }];
    if (c.rotation !== 'direct' && it) o.push({ k: 'append', label: '追加输入（' + r.name + '接，重新验收）' });
    const ids = c.rotation === 'direct' ? [r.id] : c.depts.map((d) => d.id);
    if (s.focusDept && !ids.includes(s.focusDept) && c.depts.some((d) => d.id === s.focusDept)) ids.push(s.focusDept);
    ids.forEach((id) => o.push({ k: 'g:' + id, label: '给' + nm(p, id) + '的指导' }));
    return o;
  }
  const dflt = (p) => { const it = active(p); return it ? 'g:' + (it.dept && orgOf(p, it).depts.some((d) => d.id === it.dept) ? it.dept : recv(orgOf(p, it)).id) : 'new'; };
  const cur = (p) => { const s = st(p); return s.manual && options(p).some((o) => o.k === s.to) ? s.to : dflt(p); };
  function hintText(p, k) {
    const it = active(p), c = it ? orgOf(p, it) : p.composed, r = recv(c), e = O.ending(p.composed);
    if (k === 'new') return it ? '排在「' + it.title + '」后面，它做完才开始' : recv(p.composed).name + '接，马上开始' + (e.open ? '；没有人核验，以开环完成结束' + (e.outsourced ? '（外包）' : '') : '；' + O.verifiers(p.composed).map((v) => v.name).join('、') + '放行才结束');
    if (k === 'append') return r.name + '接，已有的交付要重新验收';
    const d = c.depts.find((x) => x.id === k.slice(2));
    return '发给' + nm(p, k.slice(2)) + (it ? '，用在「' + it.title + '」' : '') + '，下一轮读到' + (isOut(d) ? '（' + d.who.agent + '在跑，中途怎么收由它定）' : '');
  }
  function toHtml(p) {
    const k = cur(p);
    return '<div class="ln-pills" role="radiogroup" aria-label="收件人"><span class="ln-to-label">收件人</span>' + options(p).map((o) => '<button type="button" role="radio" aria-checked="' + (o.k === k) + '" class="ln-pill' + (o.k === k ? ' is-on' : '') + '" data-act="ln.to" data-k="' + esc(o.k) + '">' + esc(o.label) + '</button>').join('') + '</div>' +
      '<div id="ln-hint" class="ln-hint">' + esc(hintText(p, k)) + '</div>';
  }
  function setTo(p, k) { const s = st(p); s.to = k; s.manual = true; s.focusDept = k.startsWith('g:') ? k.slice(2) : s.focusDept; }
  A('ln.to', (el) => { const p = H.project(H.pid()); setTo(p, el.dataset.k); refresh(p); });
  document.addEventListener('keydown', (ev) => {
    if (ev.target.matches('[data-act="lp.node"]') && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); ev.target.click(); return; }
    if (!ev.target.matches('.ln-pill') || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(ev.key)) return;
    const choices = Array.from(document.querySelectorAll('.ln-pill')), at = choices.indexOf(ev.target);
    const index = ev.key === 'Home' ? 0 : ev.key === 'End' ? choices.length - 1 : (at + (ev.key === 'ArrowRight' ? 1 : -1) + choices.length) % choices.length;
    ev.preventDefault(); const key = choices[index].dataset.k; choices[index].click();
    Array.from(document.querySelectorAll('.ln-pill')).find((el) => el.dataset.k === key).focus();
  });

  // ---------------------------------------------------------------- 循环图区：选事项、图、窄屏一行、点开的面板

  function graphArea(p) {
    const s = st(p), it = shown(p);
    if (s.inner && it) return innerArea(p, it);
    const c = orgOf(p, it), arrows = arrowsOf(p, it);
    const others = p.items.filter((x) => unfinished(x) && (!it || x.id !== it.id));
    const asks = openAsks(p).filter((m) => it && m.item === it.id);
    const ctx = {
      sel: s.panel && s.panel.type === 'node' ? s.panel.id : null, inner: true,
      working: it && unfinished(it) ? it.dept : null,
      oldOnly: p.onlyOld,
      state: (d) => nodeState(p, it, d),
      asks: (d) => asks.filter((m) => m.who === d.id).length,
      others: (d) => others.filter((x) => x.dept === d.id).length,
      askCount: (d) => st(p).msgs.filter((m) => m.t === 'fold' && it && m.item === it.id && m.roles.includes(d.id)).reduce((n, m) => n + m.kids.length, 0)
    };
    const fault = it && it.source === 'fault';
    const g = graphBody(c, arrows, { ctx, end: endText(c, it), endCls: it && it.status === 'adopted' ? 'is-ok' : it && it.status === 'open_closed' ? 'is-open' : '', arrow: s.panel && s.panel.type === 'arrow' ? s.panel.i : undefined, src: fault ? '运维发现的故障' : undefined });
    const opsNode = c.depts.find((d) => d.id === 'operations');
    const faultLane = opsNode ? '<div class="lp-fault"><span class="lp-pill is-src">图外</span><span class="lp-chip is-fault"><span class="lp-dir">→</span><span class="lp-kind">故障记录</span></span><span>运维发现的故障从图外进来，' + esc(nm(p, (c.sources.find((x) => x.id === 'fault') || {}).to || 'product')) + '接，开一件新事项；和打回分开，不回到这一件</span>' + (p.faultItems && p.faultItems.length ? '<span class="lp-flag">已开 ' + p.faultItems.length + ' 件</span>' : '') + '</div>' : '';
    const pick = itemPicker(p, it);
    const pool = c.rotation === 'pool' && Y20.pool ? Y20.pool.summary(p) : '';
    // 选中的事项按它冻结的组织画；项目现在的组织不同时（例如刚加了独立核验），下面给出之后新建的事项怎么走
    const next = it && it.org && it.org.core !== O.coreDigest(p.composed) ? '<div class="lp-next"><span class="ln-to-label">之后新建的事项按现在的组织「' + esc(formLabel(p).name) + '」走：</span><div class="lp-mini">' + graphBody(p.composed, [], { mini: true }) + '</div></div>' : '';
    return pick + '<div class="lp-wrap">' + (p.designPreview ? '<span class="lp-preview">设计预览</span>' : '') + g + '</div>' + lineHtml(c, arrows, it) + next + faultLane + pool + panelHtml(p, it, c, arrows);
  }
  function itemPicker(p, it) {
    const s = st(p), seen = s.msgs.filter((m) => m.t === 'sep').map((m) => m.item);
    const list = p.items.filter((x) => unfinished(x)).concat(seen.map((id) => H.item(p, id)).filter((x) => x && !unfinished(x)).reverse().slice(0, 2));
    if (list.length < 2) return '';
    const res = (x) => ({ working: '进行中', open_closed: '开环完成', adopted: '放行', stopped: '已停止' }[x.status] || Y20.ITEM_STATUS[x.status][0]);
    return '<div class="lp-pick" role="tablist" aria-label="选事项"><span class="ln-to-label">图上画</span>' + list.map((x) => '<button type="button" role="tab" aria-selected="' + (it && x.id === it.id) + '" class="lp-pick-btn' + (it && x.id === it.id ? ' is-on' : '') + '" data-act="lp.pick" data-item="' + esc(x.id) + '">' + esc(x.title) + ' <small>' + esc(res(x)) + '</small></button>').join('') + '</div>';
  }
  function nodeState(p, it, d) {
    if (!it) return '空闲';
    const s = st(p);
    if (it.status === 'adopted' || it.status === 'open_closed') return '';
    if (openAsks(p).some((m) => m.item === it.id && m.who === d.id)) return '等你决定';
    const ds = p.deptState[d.id];
    if (ds && ds.items && ds.items.includes(it.id) && ds.state !== 'idle') return ds.text;
    if (it.dept === d.id) return '在做';
    if (!d.produces.length && !d.verifies) return '在旁边接询问';
    if (s.msgs.some((m) => m.t === 'fold' && m.item === it.id && m.roles.includes(d.id))) return '等别的职能';
    return '';
  }
  function innerArea(p, it) {
    const s = st(p), parent = orgOf(p, it).depts.find((d) => d.id === s.inner);
    if (!parent || !parent.sub) { s.inner = null; return graphArea(p); }
    const c = Object.assign({}, parent.sub, { parentName: parent.name });
    const raw = (s.innerArrows[it.id + ':' + parent.id] || []).map((a, i) => Object.assign({ i: 'in' + i }, a));
    const ctx = { sel: null, inner: false, state: () => '' };
    const g = graphBody(c, raw, { ctx, end: endText(c, it), src: '上一层交来的任务', arrow: s.panel && s.panel.type === 'arrow' ? s.panel.i : undefined });
    return '<div class="lp-crumb"><button type="button" class="y20-link" data-act="lp.inner-out">' + esc(p.name) + '</button> › <b>' + esc(parent.name) + ' › 内部</b><span class="y20-muted"> · ' + esc(parent.sub.formName) + ' · 子事项 ' + esc(it.door) + '.1 · ' + esc(it.title) + '</span><button type="button" class="y20-btn small" data-act="lp.inner-out">回到上一层</button></div>' +
      '<div class="lp-wrap is-inner">' + g + '</div>' + lineHtml(c, raw, it) +
      '<p class="lp-note-row">子事项的结果作为' + esc(parent.name) + '的提案回到上一层，照常过裁决；内部的核验只说明子组织自己核验过，放行只留给事项自己那一圈。</p>' + panelHtml(p, it, c, raw);
  }

  function panelHtml(p, it, c, arrows) {
    const s = st(p), pn = s.panel;
    if (!pn) return '';
    const close = '<button type="button" class="y20-icon-btn lp-close" data-act="lp.close" aria-label="收起">' + ui.icon('close') + '</button>';
    if (pn.type === 'arrow') {
      const a = arrows.find((x) => x.i === pn.i);
      if (!a) return '';
      const same = arrows.filter((x) => x.name === a.name && x.from === a.from), at = same.indexOf(a);
      const who = (id) => (id === 'src' ? '你' : id === 'end' ? endText(c, it) : (c.depts.find((d) => d.id === id) || {}).name || id);
      const nav = same.length > 1 ? '<span class="lp-nav">' + (at > 0 ? '<button type="button" class="y20-link" data-act="lp.arrow" data-i="' + same[at - 1].i + '">‹ ' + esc(a.name + ' v' + same[at - 1].v) + '</button>' : '') + '<span class="y20-muted">第 ' + (at + 1) + ' / ' + same.length + ' 版</span>' + (at < same.length - 1 ? '<button type="button" class="y20-link" data-act="lp.arrow" data-i="' + same[at + 1].i + '">' + esc(a.name + ' v' + same[at + 1].v) + ' ›</button>' : '') + '</span>' : '';
      const verdict = a.verdict ? '<p class="lp-verdict-line is-' + a.verdict.t + '">' + esc(a.verdict.t === 'reject' ? a.verdict.by + '打回这一版' : a.verdict.t === 'pass' ? a.verdict.by + '审过这一版，交回上一层' : a.verdict.by + '放行这一版') + '</p>' : '';
      return '<section class="lp-panel" aria-label="这一版">' + close + '<h3>' + esc(a.name + (a.v ? ' v' + a.v : '')) + (a.round ? ' · 第 ' + a.round + ' 轮' : '') + '<small> ' + esc(who(a.from) + ' → ' + who(a.to)) + '</small></h3>' + nav + verdict + '<p>' + esc(a.text || '') + '</p>' +
        (a.files ? '<div class="ln-diff"><b>改了的文件</b><ul>' + a.files.map((f) => '<li>' + esc(f) + '</li>').join('') + '</ul>' + (a.diff ? ui.pre(a.diff.join('\n')) : '') + '</div>' : '') + '</section>';
    }
    const d = c.depts.find((x) => x.id === pn.id);
    if (!d) return '';
    const kids = [];
    s.msgs.forEach((m) => { if (m.t === 'fold' && (!it || m.item === it.id) && m.roles.includes(d.id)) m.kids.forEach((k) => kids.push(k)); });
    const guidance = s.msgs.filter((m) => m.t === 'you' && m.target === d.id).slice(-2);
    const ds = p.deptState[d.id];
    const doing = it && unfinished(it) ? (nodeState(p, it, d) || '这个事项里暂时没有它的事') : it ? '这个事项已结束' : '空闲';
    const extra = (d.who.type === 'outsourced' ? '<p class="y20-small">由外部 agent（' + esc(d.who.agent) + '）做：模型经受控入口由本项目定；推理档位由它自己定。</p>' : '') +
      (d.verifies ? '<p class="y20-small">它的角色是核验角色：核验' + esc((c.depts.find((x) => x.id === d.verifies.dept) || {}).name || '') + '交的' + esc(O.kindName(c, d.verifies.kind)) + '，只写检查材料。</p>' : '') +
      (isSub(d) ? '<p class="y20-small">由一个小组做（' + esc(d.sub ? d.sub.formName : '') + '）：这个职能的一轮工作开一个子事项。</p>' : '');
    const ops = d.id === 'operations' ? '<button type="button" class="y20-btn small" data-act="ops.open">运行环境 · 设计预览</button><button type="button" class="y20-btn small" data-act="ops.fault-quick">模拟发现故障</button>' : '';
    return '<section class="lp-panel" aria-label="' + esc(d.name) + '">' + close + '<h3>' + esc(d.name) + '<small> ' + esc(doing) + (ds && ds.role ? ' · ' + esc(ds.role) : '') + '</small></h3>' + extra +
      '<div class="lp-panel-cols"><div><b class="y20-small">它的往来</b>' + (kids.length ? '<ul class="ln-fold-body">' + kids.slice(-6).map((k) => '<li><b>' + esc(nm(p, k.who)) + '</b> ' + esc(k.text) + '</li>').join('') + '</ul>' : '<p class="y20-muted y20-small">这个事项里还没有往来</p>') +
      (guidance.length ? '<p class="y20-small y20-muted">你给它的指导：' + guidance.map((m) => esc(m.text) + (m.readAt ? '（已读到）' : '（还没读到）')).join('；') + '</p>' : '') + '</div></div>' +
      '<div class="lp-actions"><button type="button" class="y20-btn small primary" data-act="lp.guide" data-dept="' + esc(d.id) + '">给' + esc(d.name) + '发指导</button>' + (isSub(d) ? '<button type="button" class="y20-btn small" data-act="lp.inner" data-dept="' + esc(d.id) + '">看内部的循环图 ›</button>' : '') + ops +
      '<button type="button" class="y20-link" data-go="#/p/' + esc(p.id) + '/org/d/' + esc(d.id) + '">职能详情 ›</button></div></section>';
  }

  A('lp.pick', (el) => { const p = H.project(H.pid()), s = st(p); s.sel = el.dataset.item; s.panel = null; s.inner = null; refresh(p); });
  A('lp.node', (el, ev) => {
    if (ev && ev.target.closest('[data-act="lp.jump"],[data-act="lp.inner"]') && ev.target.closest('[data-act="lp.jump"],[data-act="lp.inner"]') !== el) return;
    const p = H.project(H.pid()), s = st(p), id = el.dataset.dept;
    const same = s.panel && s.panel.type === 'node' && s.panel.id === id;
    s.panel = same ? null : { type: 'node', id };
    if (!same && !s.inner) setTo(p, 'g:' + id);
    refresh(p);
  });
  A('lp.arrow', (el) => { const p = H.project(H.pid()), s = st(p), i = /^in/.test(el.dataset.i) ? el.dataset.i : Number(el.dataset.i); s.panel = s.panel && s.panel.type === 'arrow' && s.panel.i === i ? null : { type: 'arrow', i }; refresh(p); });
  A('lp.close', () => { const p = H.project(H.pid()); st(p).panel = null; refresh(p); });
  A('lp.guide', (el) => { const p = H.project(H.pid()); setTo(p, 'g:' + el.dataset.dept); refresh(p); const i = $('ln-text'); if (i) i.focus(); });
  A('lp.inner', (el) => { const p = H.project(H.pid()), s = st(p); s.inner = el.dataset.dept; s.panel = null; refresh(p); });
  A('lp.inner-out', () => { const p = H.project(H.pid()), s = st(p); s.inner = null; s.panel = null; refresh(p); });
  A('lp.jump', (el) => { const p = H.project(H.pid()); jumpAsk(p, el.dataset.who); });
  A('ln.sep', (el) => { const p = H.project(H.pid()), s = st(p); s.sel = el.dataset.item; s.panel = null; s.inner = null; refresh(p); const g = $('lp-graph'); if (g && g.scrollIntoView) g.scrollIntoView({ block: 'nearest' }); });
  function jumpAsk(p, who) {
    const b = Array.from(document.querySelectorAll('.ln-msg.is-ask:not(.is-answered)')).find((x) => !who || x.dataset.who === who) || document.querySelector('.ln-msg.is-ask:not(.is-answered)');
    if (!b) return;
    b.scrollIntoView({ block: 'center' }); b.classList.add('is-flash'); setTimeout(() => b.classList.remove('is-flash'), 2000);
  }

  // ---------------------------------------------------------------- 对话

  function threadHtml(p) {
    const s = st(p);
    const archived = new Set();
    let section = null;
    s.msgs.forEach((m) => {
      if (m.t === 'sep') section = m.item;
      if ((m.t === 'done' || m.t === 'rel') && section && !s.openItems[section]) archived.add(section);
    });
    let currentSection = null;
    const sel = (shown(p) || {}).id;
    const look = (m) => (m.ai !== undefined ? ' <button type="button" class="y20-link" data-act="ln.look" data-item="' + esc(m.item) + '" data-i="' + m.ai + '">看这一版</button>' : '');
    const rows = s.msgs.map((m, i) => {
      if (m.t === 'sep') currentSection = m.item;
      if (archived.has(currentSection) && !['sep', 'done', 'rel'].includes(m.t)) return '';
      const who = (name, cls, body, tag, extra) => '<div class="ln-msg ' + cls + '"' + (extra || '') + '><div class="ln-meta">' + esc(name) + ' · ' + esc(ui.time(m.at)) + '</div>' + (tag ? '<div class="ln-tag">' + esc(tag) + '</div>' : '') + '<div class="ln-bubble">' + body + '</div></div>';
      switch (m.t) {
        case 'sep': {
          const it = H.item(p, m.item); if (!it) throw new Error('线程引用了不存在的事项：' + m.item);
          const res = { working: '进行中', open_closed: '开环完成', adopted: '放行', stopped: '已停止' }[it.status] || Y20.ITEM_STATUS[it.status][0];
          return '<div class="ln-sep' + (sel === it.id ? ' is-sel' : '') + '"><button type="button" class="ln-sep-btn" data-act="ln.sep" data-item="' + esc(it.id) + '" title="在循环图上画这件">' + esc(it.title) + ' · ' + esc(res) + '</button>' + (DONE.includes(it.status) && it.status !== 'stopped' ? '<button class="y20-link" type="button" data-act="ln.item-toggle" data-item="' + esc(it.id) + '">' + (archived.has(it.id) ? '展开对话' : '收起对话') + '</button>' : '') + '</div>';
        }
        case 'you': return who('你', 'is-you', esc(m.text), m.tag);
        case 'ans': return who('你的回答', 'is-you', esc(m.text));
        case 'queue': return '<div class="ln-notice">' + esc(m.text) + '</div>';
        case 'fold': return '<div class="ln-fold" id="ln-fold-' + i + '"><button type="button" class="ln-fold-head" aria-expanded="' + m.open + '" data-act="ln.fold" data-i="' + i + '">' + esc(m.lab) + ' ' + m.kids.length + ' 条</button>' +
          (m.open ? '<ul class="ln-fold-body">' + m.kids.map((k) => '<li><b>' + esc(nm(p, k.who)) + '</b> ' + esc(k.text) + '</li>').join('') + '</ul>' : '') + '</div>';
        case 'ask': return who((m.by || nm(p, m.who)) + ' · 要你决定', 'is-ask' + (m.answer ? ' is-answered' : ''), '<b>' + esc(m.text) + '</b><div class="ln-opts">' + m.options.map((o) => '<button type="button" class="y20-btn small' + (m.answer === o ? ' primary' : '') + '"' + (m.answer ? ' disabled' : ' data-act="ln.answer" data-i="' + i + '" data-o="' + esc(o) + '"') + '>' + esc(o) + '</button>').join('') + '</div>' + (m.answer ? '<small class="y20-muted">已回答：' + esc(m.answer) + '</small>' : ''), '', ' data-who="' + esc(m.who || '') + '"');
        case 'notice': case 'stop': return '<div class="ln-notice">' + esc(m.text) + '</div>';
        case 'done': return who(nm(p, m.who || 'engineering') + ' · 交完成', 'is-done', esc(m.text) + look(m));
        case 'rel': return who(nm(p, m.who || 'quality') + ' · 放行', 'is-done is-rel', esc(m.text) + look(m));
        default: return '';
      }
    }).join('');
    const cards = H.decisions(p.id).map((d) => '<div class="ln-msg is-ask" data-who=""><div class="ln-meta">' + esc(d.label) + ' · 要你决定</div><div class="ln-bubble">' + Y20.cards.one(d) + '</div></div>').join('');
    return (rows + cards) || ui.empty('还没有事项。在下面写一句，就开始做。');
  }
  function statusStrip(p) {
    const it = active(p);
    if (!it) return '';
    const d = orgOf(p, it).depts.find((x) => x.id === it.dept);
    return isOut(d) ? '<div class="ln-strip">' + ui.icon('running') + '<span><b>' + esc(d.who.agent) + '</b> 在跑「' + esc(it.title) + '」 · 推理档位由它定 · 交回的快照与差异经写入口成为提案</span></div>' : '';
  }
  const barHtml = (p) => {
    const e = p.elapsed;
    return '<div class="ln-time-row"><span>' + (active(p) ? '正在处理 · ' : '') + '已用 ' + esc(ui.duration(e.used)) + ' / 上限 ' + esc(ui.duration(e.limit)) + '</span>' +
      (active(p) ? '<button type="button" class="y20-btn small danger" data-act="ln.stop">停止</button>' : '') + '</div>' + ui.meter(e.used, e.limit);
  };
  function inputLabel(p) {
    const k = cur(p), input = $('ln-text');
    if (!input) return;
    input.setAttribute('aria-label', k.startsWith('g:') ? '给' + nm(p, k.slice(2)) + '的指导' : k === 'append' ? '追加输入' : '开始一个新事项');
    input.placeholder = k.startsWith('g:') ? '给' + nm(p, k.slice(2)) + '的指导……' : k === 'append' ? '补充这个事项的要求……' : '说说你想做什么……';
  }
  function refresh(p, scroll) {
    if (!here(p)) return;
    $('lp-graph').innerHTML = graphArea(p);
    $('ln-thread').innerHTML = threadHtml(p); $('ln-bar').innerHTML = barHtml(p); $('ln-to').innerHTML = toHtml(p); $('ln-strip').innerHTML = statusStrip(p);
    inputLabel(p);
    if (scroll) $('ln-thread').scrollTop = 1e9;
  }

  function conversation(ctx, p) {
    return '<div class="ln lp-page">' + (p.designPreview ? '<p class="ws-preview">设计预览 · 所有操作仅使用本页示例数据</p>' : '') +
      '<div id="ln-bar" class="ln-time">' + barHtml(p) + '</div>' +
      '<section id="lp-graph" class="lp-graph" aria-label="循环图">' + graphArea(p) + '</section>' +
      '<div id="ln-thread" class="ln-thread">' + threadHtml(p) + '</div><div id="ln-strip">' + statusStrip(p) + '</div>' +
      '<form id="ln-form" class="ln-input" autocomplete="off"><div id="ln-to">' + toHtml(p) + '</div><div class="ln-row"><input type="text" class="y20-input" id="ln-text" placeholder="说说你想做什么……"><button type="submit" class="y20-btn primary">发送</button></div></form></div>';
  }
  function convMount(ctx, el, p) {
    inputLabel(p);
    setTimeout(() => { const t = $('ln-thread'); if (t) t.scrollTop = 1e9; }, 0);
    const q = Y20.state.route.query;
    if (q.jump) setTimeout(() => jumpAsk(p, q.who || ''), 60);
  }

  // ---------------------------------------------------------------- 新事项的假进展：按冻结的组织走，约 3.5 秒交付、5 秒放行

  function run(p, it) {
    it.ran = true;
    const c = it.org.composed, s = st(p), open = O.ending(c).open;
    if (c.rotation === 'pool') { Y20.pool.start(p, it); refresh(p); return; }
    const L = layout(c), first = c.depts.find((d) => d.id === it.dept) || L.chain[0], maker = L.maker || first;
    const verifiers = O.verifiers(c), names = verifiers.map((v) => v.name).join('、');
    const at = (ms, fn) => (timers[p.id] = timers[p.id] || []).push(setTimeout(() => { if (it.status !== 'working') return; fn(); refresh(p, true); }, ms));
    const progress = (d, text) => { it.dept = d.id; readGuidance(p, [d.id], it.id); fold(p, it, 'prog', (d.who.type === 'outsourced' ? d.who.agent : '') + '工作进展', [first.id, maker.id], d.id, text); };
    const kindOf = (d) => O.kindName(c, d.produces[0] || '');
    const vOf = (name) => s.arrows.filter((a) => a.item === it.id && a.name === name).length + 1;
    at(500, () => progress(first, '接到输入，开始工作。'));
    if (first !== maker) at(1800, () => { const k = kindOf(first); pushArrow(p, { item: it.id, from: first.id, to: maker.id, name: k, v: vOf(k), round: 1, text: '「' + it.title + '」的' + k }); progress(maker, '照着' + k + '在做。'); });
    else at(1800, () => {
      progress(maker, '正在做，并自己检查。');
      // 直做里旁边接询问的职能：工程拿不准时问它，往来折成一行
      L.side.filter((x) => x.ask).forEach((x) => { fold(p, it, 'ask-' + x.d.id, maker.name + '与' + x.d.name + '往来', [maker.id, x.d.id], maker.id, '这一句要求的边界拿不准，问一下。'); fold(p, it, 'ask-' + x.d.id, '', [], x.d.id, '按你的输入原文做，不要扩出去。'); });
    });
    at(3500, () => {
      const k = kindOf(maker) || '交付', to = verifiers.length ? verifiers[0].id : 'end';
      const ai = pushArrow(p, { item: it.id, from: maker.id, to, name: k, v: vOf(k), round: 1, text: '「' + it.title + '」的' + k, files: ['workspace/result.md'], diff: ['@@ workspace/result.md', '+ ' + (it.text || it.title).slice(0, 80)] });
      p.elapsed.used += 300;
      if (open) { push(p, { t: 'done', who: maker.id, item: it.id, text: '做完了。开环完成：没有人核验' + (isOut(maker) ? ' · 外包（' + maker.who.agent + '）' : ''), ai }); finish(p, it, 'open_closed'); }
      else { progress(maker, '交了' + k + ' v1，等' + names + '核验。'); it.dept = verifiers[0].id; }
    });
    if (!open) at(5000, () => {
      const a = s.arrows.slice().reverse().find((x) => x.item === it.id && x.to === verifiers[0].id);
      a.verdict = { t: 'release', by: names };
      fold(p, it, 'verify', maker.name + '与' + names + '往来', [maker.id].concat(verifiers.map((v) => v.id)), verifiers[0].id, '独立核验通过。');
      push(p, { t: 'rel', who: verifiers[0].id, item: it.id, text: '放行：' + names + '核验' + a.name + ' v' + a.v + ' 通过', ai: s.arrows.indexOf(a) });
      finish(p, it, 'adopted');
    });
  }
  function startItem(p, text, source) {
    const res = Y20.newItem(p, { title: text.replace(/\s+/g, ' ').slice(0, 16), text, source });
    if (!res.ok) { ui.toast('现在不能开始：' + res.rejects.join('；'), 'warn'); return false; }
    const s = st(p);
    s.cur = res.item.id; s.sel = null; s.panel = null; s.inner = null;
    push(p, { t: 'sep', item: res.item.id }); push(p, { t: 'you', item: res.item.id, text, tag: source === 'fault' ? '运维发现的故障' : '开始一个新事项' });
    pushArrow(p, { item: res.item.id, from: 'src', to: res.item.dept, name: source === 'fault' ? '故障记录' : '原文', v: 1, round: 1, text });
    if (O.ending(res.item.org.composed).open) push(p, { t: 'notice', item: res.item.id, text: '这个事项没有人核验，交完成就以开环完成结束' + (O.ending(res.item.org.composed).outsourced ? '（外包）' : '') + '。' });
    run(p, res.item); return true;
  }
  function finish(p, it, status) {
    const s = st(p);
    it.status = status;
    X.slotHolders[p.id] = (X.slotHolders[p.id] || []).filter((x) => x !== it.id); p.slots.used = Math.max(0, p.slots.used - 1);
    Object.keys(p.deptState).forEach((id) => {
      const d = p.deptState[id];
      if (!(d.items || []).includes(it.id) && id !== it.dept) return;
      const remaining = (d.items || []).filter((key) => key !== it.id && p.items.some((other) => other.id === key && unfinished(other)));
      p.deptState[id] = remaining.length ? Object.assign({}, d, { items: remaining, text: remaining.map((key) => H.item(p, key).title).join('、') }) : O.idleState(p, id);
    });
    if (s.queue.length) { const next = s.queue.shift(); startItem(p, typeof next === 'string' ? next : next.text, next.source); }
  }
  function enqueue(p, text, source) {
    const it = active(p);
    if (!it) return startItem(p, text, source);
    st(p).queue.push({ text, source });
    push(p, { t: 'queue', text: '「' + text.slice(0, 28) + '」排在「' + it.title + '」后面，它做完才开始' });
    if (!it.ran) run(p, it);
    return true;
  }
  Object.assign(Y20.thread, { active, start: startItem, finish, refresh, run, enqueue, readGuidance, layout, graphBody });

  document.addEventListener('submit', (ev) => {
    if (ev.target.id !== 'ln-form') return;
    ev.preventDefault();
    const p = H.project(H.pid()), input = $('ln-text'), text = input.value.trim(), s = st(p);
    if (!text) return;
    const k = cur(p), it = active(p), tag = k === 'new' ? '开始一个新事项' : k === 'append' ? '追加输入' : '给' + nm(p, k.slice(2)) + '的指导';
    input.value = '';
    if (!k.startsWith('g:')) { s.manual = false; s.to = null; s.focusDept = null; }
    if (k === 'new' && !it) { if (!startItem(p, text)) return; }
    else {
      push(p, Object.assign({ t: 'you', text, tag }, k.startsWith('g:') ? { target: k.slice(2), item: it ? it.id : null } : { item: it ? it.id : null }));
      if (k === 'new') { s.queue.push({ text }); push(p, { t: 'queue', text: '排在「' + it.title + '」后面，它做完才开始' }); if (!it.ran) run(p, it); }
      else if (k === 'append' && it) {
        (timers[p.id] || []).forEach(clearTimeout); timers[p.id] = [];
        it.text = (it.text || it.title) + '\n追加输入：' + text;
        it.dept = recv(it.org.composed).id;
        pushArrow(p, { item: it.id, from: 'src', to: it.dept, name: '原文', v: s.arrows.filter((a) => a.item === it.id && a.from === 'src').length + 1, round: (it.round || 1) + 1, text });
        push(p, { t: 'notice', item: it.id, text: '追加输入交给' + nm(p, it.dept) + '，已有的交付要重新验收。' });
        run(p, it);
      } else if (it && !it.ran) run(p, it);
    }
    refresh(p, true);
  });
  A('ln.stop', () => {
    const p = H.project(H.pid()), it = active(p);
    (timers[p.id] || []).forEach(clearTimeout); timers[p.id] = [];
    if (it.org.composed.rotation === 'pool') Y20.pool.stop(p);
    push(p, { t: 'stop', text: '你停止了「' + it.title + '」' }); finish(p, it, 'stopped'); refresh(p, true);
  });
  A('ln.answer', (el) => {
    const p = H.project(H.pid()), m = st(p).msgs[Number(el.dataset.i)];
    m.answer = el.dataset.o; push(p, { t: 'ans', item: m.item, text: el.dataset.o });
    const it = active(p);
    if (it && !it.ran && !openAsks(p).some((x) => x.item === it.id)) run(p, it);
    Y20.rerender();
  });
  A('ln.fold', (el) => { const p = H.project(H.pid()), m = st(p).msgs[Number(el.dataset.i)]; m.open = !m.open; refresh(p); });
  A('ln.look', (el) => { const p = H.project(H.pid()), s = st(p); s.sel = el.dataset.item; s.inner = null; s.panel = { type: 'arrow', i: Number(el.dataset.i) }; refresh(p); const g = $('lp-graph'); if (g && g.scrollIntoView) g.scrollIntoView({ block: 'nearest' }); });
  A('ln.item-toggle', (el) => { const p = H.project(H.pid()), s = st(p); s.openItems[el.dataset.item] = !s.openItems[el.dataset.item]; refresh(p); });
  // 左侧栏的数字：跳到第一条没回答的决定，亮一下
  A('ln.jump', (el, ev) => { if (ev) ev.stopPropagation(); Y20.go('#/p/' + el.dataset.p + '?jump=1'); });

  // ---------------------------------------------------------------- 设置

  A('ln.name', (el) => { const p = H.project(H.pid()); if (el.value.trim()) { p.name = el.value.trim(); Y20.rerender(); } });
  A('ln.goal', (el) => { H.project(H.pid()).goal = el.value.trim(); });
  A('ln.dir', (el) => { H.project(H.pid()).dir = el.value.trim(); });

  function adoptNow(p, changes, reason, form) {
    const res = O.adopt(p, { form: form || p.org.form, changes, reason, base: p.version, key: 'k' + (++seq), pending: changes.depts && changes.depts.quality && changes.depts.quality.added ? { quality: { model: (X.wiring.quality || {}).model } } : {} });
    if (!res.ok) { ui.toast(res.error + (res.rejects ? '：' + res.rejects.map((r) => r.text).join('；') : ''), 'warn'); return false; }
    return true;
  }
  function settings(ctx, p) {
    const c = p.composed, f = formLabel(p), running = p.items.filter(unfinished);
    const field = (label, control, note) => '<div class="ln-set"><label>' + esc(label) + '</label><div>' + control + (note ? '<small class="y20-muted">' + note + '</small>' : '') + '</div></div>';
    const models = c.depts.map((d) => esc(d.name) + ' ' + (isOut(d) ? esc(O.modelOf(p, d.id) || '未选') + '（推理档位由 ' + esc(d.who.agent) + ' 定）' : esc(O.modelOf(p, d.id) || '未选'))).join(' · ');
    const canAdd = c.rotation === 'direct' && !O.verifiers(c).length;
    const verBtn = indep(p) ? '<button type="button" class="y20-btn" data-act="lp.unverify">去掉独立核验</button>' : canAdd ? '<button type="button" class="y20-btn primary" data-act="lp.verify">加独立核验</button>' : '';
    const obs = c.observers.map((o) => '<label class="y20-check"><input type="checkbox" data-act="lp.observer" data-id="' + esc(o.id) + '"' + (o.on ? ' checked' : '') + '><span>' + esc(o.name) + '<small class="y20-muted"> · 产出' + esc(o.makes) + ' · 读' + esc(o.scope) + '</small></span></label>').join('');
    return '<div class="ln-settings lp-settings"><h1>设置</h1>' +
      field('名字', '<input type="text" class="y20-input" data-act="ln.name" value="' + esc(p.name) + '">') +
      field('长期目标', '<textarea class="y20-textarea" rows="2" data-act="ln.goal" placeholder="可选；不写时项目上下文里没有这一项">' + esc(/^（还没有/.test(p.goal) ? '' : p.goal) + '</textarea>') +
      field('起始文件夹', '<input type="text" class="y20-input" data-act="ln.dir" value="' + esc(p.dir || '') + '" placeholder="可选；接入已有项目时是源目录">') +
      field('模型', '<span>' + models + '</span>', '在职能详情里改（点循环图上的节点）；模型清单在<button type="button" class="y20-link" data-go="#/sys/models">模型管理</button>') +
      field('组织', '<p class="lp-org-line">' + esc(orgLine(p)) + '</p><div class="lp-actions">' + verBtn + '<button type="button" class="y20-btn" data-act="lp.forms">换形态</button></div>',
        '只对之后新建的事项生效' + (running.length ? '；在跑的 ' + running.length + ' 件按原来的组织做完' : '')) +
      field('观察者', obs ? '<div class="lp-obs">' + obs + '</div>' : '<span class="y20-muted">这一份形态没有观察者</span>', '在事项外面读事实，发现问题会变成对话里「要你决定」的气泡；开了就生效，不进草稿，不改事项怎么结束') +
      '<details class="ln-adv lp-adv"><summary>高级</summary><div class="lp-adv-body">' +
      '<p class="y20-muted y20-small">形态里没有的东西才用这里：改名、加职能、三样说明、编辑定义、草稿与校验、版本与历史、和某项目一样、接来源的职能改给谁。走这里的采用要写理由。</p>' +
      '<div class="lp-adv-links"><button type="button" class="y20-btn" data-go="#/p/' + esc(p.id) + '/org?advanced=1">组织：四问、职能表、加职能、编辑定义、版本与历史</button>' +
      '<button type="button" class="y20-btn" data-go="#/p/' + esc(p.id) + '/settings?advanced=1">成果写回、机器授权、执行位置、MCP 服务器</button>' +
      '<button type="button" class="y20-btn" data-act="lp.same">和某项目一样</button></div>' +
      '<p class="y20-small y20-muted">现在用「' + esc(f.name) + '」' + (f.changed ? '，改过 ' + f.changed + ' 处' : '，全部跟随发布') + ' · 版本 ' + esc(p.version) + ' · 历史 ' + p.org.history.length + ' 条</p></div></details></div>';
  }
  A('lp.verify', () => {
    const p = H.project(H.pid()), c = p.composed, q = O.publishedDept(c, 'quality'), ch = clone(p.org.changes);
    ch.depts = ch.depts || {}; ch.depts.quality = Object.assign({ added: true }, q);
    const running = p.items.filter(unfinished);
    if (!adoptNow(p, ch, '加独立核验')) return;
    push(p, { t: 'notice', text: '加了独立核验：之后新建的事项由质检核验交完成的那一版，放行才结束；轮转仍是直做' + (running.length ? '。在跑的「' + running.map((x) => x.title).join('」「') + '」按原来的做完' : '') + '。' });
    ui.toast('已生效：形态名变成「' + formLabel(p).name + '」', 'ok'); Y20.rerender();
  });
  A('lp.unverify', () => {
    const p = H.project(H.pid()), ch = clone(p.org.changes);
    delete ch.depts.quality; if (!Object.keys(ch.depts).length) delete ch.depts;
    if (!adoptNow(p, ch, '去掉独立核验')) return;
    push(p, { t: 'notice', text: '去掉了独立核验：之后新建的事项交完成就以开环完成结束；在跑的按原来的做完。' });
    ui.toast('已生效：形态名变回「' + formLabel(p).name + '」', 'ok'); Y20.rerender();
  });
  A('lp.observer', (el) => {
    const p = H.project(H.pid()), ch = clone(p.org.changes);
    ch.observers = ch.observers || {}; ch.observers[el.dataset.id] = Object.assign({}, ch.observers[el.dataset.id], { on: el.checked });
    const name = O.OBSERVERS[el.dataset.id].name;
    if (!adoptNow(p, ch, (el.checked ? '打开' : '关掉') + '观察者「' + name + '」')) return;
    ui.toast((el.checked ? '已打开' : '已关掉') + '「' + name + '」，马上生效', 'ok'); Y20.rerender();
  });
  A('lp.forms', () => {
    const p = H.project(H.pid());
    ui.modal({ title: '换形态', wide: true, body: '<p class="y20-muted y20-small">点一张卡，一步生效；只对之后新建的事项生效，历史里记一条，以后能改回。</p><div class="ln-cards lp-cards">' + cards('lp.form', O.count(p.org.changes) ? '' : p.org.form) + '</div>', actions: [{ label: '取消', close: true }] });
  });
  A('lp.form', (el) => {
    const p = H.project(H.pid()), form = el.dataset.form, n = O.count(p.org.changes);
    const go = () => {
      if (!adoptNow(p, {}, '换形态：「' + O.formName(form) + '」', form)) return;
      ui.closeModal();
      push(p, { t: 'notice', text: '换成「' + O.formName(form) + '」：只对之后新建的事项生效；在跑的按原来的做完。' });
      ui.toast('已换成「' + O.formName(form) + '」', 'ok'); Y20.rerender();
    };
    if (form === p.org.form && !n) { ui.closeModal(); return; }
    if (!n) { go(); return; }
    const lost = O.diff(O.compose({ form: p.org.form, changes: {} }), p.composed);
    ui.modal({ title: '换形态会丢掉本项目的改动', body: '<p>本项目改过 ' + n + ' 处，换成「' + esc(O.formName(form)) + '」以后这些不再生效（历史里还在，改回能找回）：</p><ul>' + lost.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul>',
      actions: [{ label: '取消', close: true }, { label: '换', kind: 'primary', act: 'lp.form-do', data: { form } }] });
  });
  A('lp.form-do', (el) => {
    const p = H.project(H.pid()), form = el.dataset.form;
    if (!adoptNow(p, {}, '换形态：「' + O.formName(form) + '」', form)) return;
    ui.closeModal(); push(p, { t: 'notice', text: '换成「' + O.formName(form) + '」：只对之后新建的事项生效；在跑的按原来的做完。' }); Y20.rerender();
  });
  A('lp.same', () => {
    const p = H.project(H.pid());
    ui.modal({ title: '和某项目一样（高级）', body: '<p class="y20-small">复制一次形态名、本项目的改动、项目职能设置与项目角色设置；机器授权、执行位置、源目录、MCP 服务器不复制；之后两边各改各的。</p><select class="y20-select" id="lp-same">' + Y20.W().projects.filter((x) => x !== p).map((x) => '<option value="' + x.id + '">' + esc(x.name) + '</option>').join('') + '</select>',
      actions: [{ label: '取消', close: true }, { label: '复制', kind: 'primary', act: 'lp.same-do' }] });
  });
  A('lp.same-do', () => {
    const p = H.project(H.pid()), src = H.project($('lp-same').value);
    p.settings = clone(src.settings);
    if (!adoptNow(p, clone(src.org.changes), '和「' + src.name + '」一样', src.org.form)) return;
    ui.closeModal(); ui.toast('已和「' + src.name + '」一样', 'ok'); Y20.rerender();
  });

  // ---------------------------------------------------------------- 外壳：项目页只有对话与设置

  Y20.leanHas = (p, name) => Boolean(Y20.leanViews[name]) || /^(org|item|recovery|advanced)/.test(name);
  Y20.leanTabs = (p, r) => {
    const b = (on, label, tail) => '<button type="button" class="y20-ptab' + (on ? ' is-active' : '') + '" data-go="#/p/' + p.id + tail + '">' + esc(label) + '</button>';
    const onSet = r.name === 'settings' || /^org/.test(r.name);
    return '<div class="y20-pheader"><button type="button" class="y20-pname" data-go="#/p/' + p.id + '">' + esc(p.name) + '</button><span class="y20-ptags">' + tags(p).map((t) => '<span class="y20-ptag">' + esc(t) + '</span>').join('') + '</span></div>' +
      '<div class="y20-ptabs" role="navigation" aria-label="项目页面">' + b(r.name === 'overview', '对话', '') + b(onSet, '设置', '/settings') + '</div>';
  };
  Y20.leanViews.overview = { render: conversation, mount: convMount };
  Y20.leanViews.settings = { render: settings };

  // ---------------------------------------------------------------- 新建项目、接入已有项目：名字加一张形态卡

  function dialog(attach) {
    const px = attach ? 'pa' : 'pn';
    const projects = Y20.W().projects.map((p) => '<option value="' + p.id + '">' + esc(p.name) + '</option>').join('');
    const body = '<div class="ln-new" data-np="' + px + '"><input type="text" class="y20-input" id="ln-name" aria-label="项目名字" placeholder="项目名字" data-live data-act="ln.clear">' +
      '<div class="ln-warn" id="ln-warn"></div>' +
      (attach ? '<input type="text" class="y20-input" id="ln-dir" placeholder="源目录：控制主机上已有项目的绝对路径" data-live data-act="ln.clear">' : '') +
      '<p class="y20-muted y20-small">点一张形态卡，项目就建好了。</p><div class="ln-cards lp-cards">' + cards('ln.create') + '</div>' +
      '<input type="radio" name="' + px + '-org" id="' + px + '-radio" value="three" checked hidden><input type="checkbox" id="' + px + '-obs" hidden><input type="checkbox" id="' + px + '-sub" hidden>' +
      '<div class="ln-more">' + (attach ? '' : '<button type="button" class="y20-link" data-act="ln.toggle" data-t="ln-dirbox">选起始文件夹</button> ') + '<button type="button" class="y20-link" data-act="ln.toggle" data-t="ln-advbox">高级</button></div>' +
      '<div id="ln-dirbox" hidden><input type="text" class="y20-input" id="pn-dir" placeholder="控制主机上的路径，可以不填"></div>' +
      '<div id="ln-advbox" class="ln-advbox" hidden><label class="y20-field"><span>和某项目一样</span><select class="y20-select" id="' + px + '-same"><option value="">不用</option>' + projects + '</select><small class="y20-muted">选了以后，点任意一张卡都按那个项目的组织建。</small></label></div></div>';
    ui.modal({ title: attach ? '接入已有项目' : '新建项目', wide: true, body, actions: [] });
  }
  A('np.new', () => dialog(false));
  A('np.attach', () => dialog(true));
  A('ln.clear', () => { $('ln-warn').textContent = ''; });
  A('ln.toggle', (el) => { $(el.dataset.t).hidden = !$(el.dataset.t).hidden; });
  A('ln.create', (el) => {
    const px = el.closest('[data-np]').dataset.np, name = $('ln-name').value.trim(), dir = px === 'pa' ? $('ln-dir').value.trim() : $('pn-dir').value.trim();
    const need = !name ? ['ln-name', '先写名字'] : px === 'pa' && !dir ? ['ln-dir', '先写源目录'] : null;
    if (need) { $('ln-warn').textContent = need[1]; $(need[0]).focus(); return; }
    const radio = $(px + '-radio'), same = $(px + '-same').value;
    radio.value = same ? 'same' : el.dataset.form;
    const spec = { name, goal: '', dir, org: Y20.np.pickedOrg(px) };
    if (px === 'pa') { Y20.np.attachDo(spec); return; }
    const p = Y20.np.createProject(spec);
    ui.closeModal();
    Y20.go('#/p/' + p.id);
  });
})();
