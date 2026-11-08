// 时序图：一件事项的经过。输入是这个事项已经有的事实（成果箭头、询问记录、你的输入与决定），不另存一份。
(function () {
  'use strict';
  const Y20 = window.Y20;
  const esc = Y20.esc;
  const ms = (iso) => Date.parse(iso);
  const iso = (t) => new Date(t).toISOString();
  const VERDICT = { reject: '打回', release: '放行', pass: '审过' };
  const verdictText = (a) => a.by + VERDICT[a.t];

  function build(v) {
    const rows = [];
    let carry = ms(v.start);
    v.arrows.forEach((a) => {
      if (a.at) carry = ms(a.at);
      const last = rows[rows.length - 1], from = a.from === 'src' ? 'you' : a.from, to = a.to === 'end' ? 'you' : a.to;
      // 同一版同时给几个职能（PRD 给工程与质检）是一条消息
      if (last && last.kind === 'outcome' && last.from === from && last.name === a.name && last.v === a.v) { last.to.push(to); return; }
      rows.push({ ref: 'a:' + a.i, kind: 'outcome', t: carry, from, to: [to], round: a.round, name: a.name, v: a.v, title: a.name + (a.v ? ' v' + a.v : ''), verdict: a.verdict });
    });
    const byId = {};
    v.asks.forEach((q) => { byId[q.id] = q; });
    const depth = (q) => (q.parent && byId[q.parent] ? 1 + depth(byId[q.parent]) : 0);
    v.asks.forEach((q) => {
      const ref = 'q:' + q.id, d = depth(q);
      rows.push({ ref, kind: 'ask', t: ms(q.at), from: q.from, to: [q.to], round: q.round, depth: d, title: q.text, open: !q.done, bar: { col: q.from, kind: 'ask', tip: '在等待' + v.name(q.to) + '的回答' } });
      if (q.done) rows.push({ ref, kind: 'answer', closes: ref, t: q.answered ? ms(q.answered) : ms(q.at) + 180000, from: q.to, to: [q.from], round: q.round, depth: d, title: '答：' + q.answer });
    });
    v.msgs.forEach((m) => {
      const ref = 'm:' + m.idx;
      if (m.t === 'you' && m.tag !== '开始一个新事项' && m.tag !== '运维发现的故障') rows.push({ ref, kind: 'you', t: ms(m.at), from: 'you', to: [m.target || v.cols[1]], title: (m.tag || '你的输入') + '：' + m.text });
      if (m.t === 'ask') {
        rows.push({ ref, kind: 'decide', t: ms(m.at), from: m.who, to: ['you'], title: '要你决定：' + m.text, bar: { col: m.who, kind: 'user', tip: '等你决定' } });
        if (m.answer) rows.push({ ref, kind: 'decided', closes: ref, t: ms(m.answeredAt || iso(ms(m.at) + 60000)), from: 'you', to: [m.who], title: '你决定：' + m.answer });
      }
    });
    rows.sort((a, b) => a.t - b.t);
    let round = 1;
    rows.forEach((r) => { r.round = r.round || round; round = r.round; });
    return rows;
  }

  function barsOf(rows) {
    const bars = [];
    rows.forEach((r, i) => {
      if (!r.bar) return;
      const end = rows.findIndex((x, j) => j > i && x.closes === r.ref);
      bars.push(Object.assign({ from: i, to: end < 0 ? Infinity : end }, r.bar));
    });
    return bars;
  }

  function summary(rows) {
    const parts = [];
    rows.filter((r) => r.kind === 'outcome' && r.from !== 'you').forEach((r) => {
      if (r.name !== '缺陷记录') parts.push(r.title);
      if (r.verdict) parts.push(verdictText(r.verdict));
    });
    const asks = rows.filter((r) => r.kind === 'ask').length;
    return parts.join(' → ') + (asks ? (parts.length ? ' · ' : '') + '询问 ' + asks + ' 次' : '');
  }

  function html(v) {
    const pair = v.pair;
    const rows = (pair
      ? build(v).filter((r) => pair.includes(r.from) && r.to.some((t) => pair.includes(t))).map((r) => Object.assign({}, r, { to: r.to.filter((t) => pair.includes(t)) }))
      : build(v));
    const cols = pair ? v.cols.filter((c) => pair.includes(c)) : v.cols;
    const bars = barsOf(rows);
    const x = (c) => ((cols.indexOf(c) + 0.5) / cols.length) * 100;
    const lives = cols.map((c) => '<i class="sq-life" style="left:' + x(c) + '%"></i>').join('');
    const barsAt = (i) => bars.filter((b) => b.from <= i && i <= b.to).map((b) => '<i class="sq-bar is-' + b.kind + '" style="left:' + x(b.col) + '%" title="' + esc(b.tip) + '"></i>').join('');
    const groups = [];
    rows.forEach((r, i) => {
      let g = groups.find((y) => y.n === r.round);
      if (!g) groups.push(g = { n: r.round, rows: [] });
      g.rows.push(Object.assign({ i }, r));
    });
    groups.sort((a, b) => a.n - b.n);
    const latest = groups.length ? groups[groups.length - 1].n : 0;
    const isOpen = (n) => (v.rounds[n] === undefined ? n === latest : v.rounds[n]);
    const label = (r) => (r.depth ? '↳ ' : '') + r.title;

    function rowHtml(r) {
      const points = [r.from].concat(r.to).map(x), lo = Math.min(...points), hi = Math.max(...points);
      const far = r.to.reduce((f, t) => (Math.abs(x(t) - x(r.from)) > Math.abs(x(f) - x(r.from)) ? t : f), r.to[0]);
      const dash = r.kind === 'ask' || r.kind === 'answer';
      const dots = r.to.filter((t) => t !== far).map((t) => '<i class="sq-dot" style="left:' + x(t) + '%"></i>').join('');
      const place = lo < 50 ? 'left:' + lo + '%;right:0' : 'left:0;right:' + (100 - hi) + '%;text-align:right';
      const tag = r.verdict ? ' <span class="lp-verdict is-' + r.verdict.t + '">' + esc(verdictText(r.verdict)) + '</span>' : '';
      return '<button type="button" class="sq-row' + (v.sel === r.ref ? ' is-on' : '') + '" data-act="sq.row" data-r="' + esc(r.ref) + '">' +
        '<span class="sq-time">' + esc(v.time(iso(r.t))) + '</span><span class="sq-track">' + lives + barsAt(r.i) +
        '<span class="sq-text" style="' + place + (r.depth ? ';padding-left:' + 14 * r.depth + 'px' : '') + '"><span>' + esc(label(r)) + tag + '</span></span>' +
        '<i class="sq-line' + (dash ? ' is-dash' : '') + (x(far) > x(r.from) ? ' is-r' : ' is-l') + '" style="left:' + lo + '%;width:' + (hi - lo) + '%"></i>' + dots + '</span></button>';
    }
    const head = (g, cls) => '<button type="button" class="sq-round ' + cls + '" data-act="sq.round" data-n="' + g.n + '" aria-expanded="' + isOpen(g.n) + '"><span aria-hidden="true">' + (isOpen(g.n) ? '▾' : '▸') + '</span> 第 ' + g.n + ' 轮' + (isOpen(g.n) ? '' : ' · ' + esc(summary(g.rows))) + '</button>';
    const hasOpen = bars.some((b) => b.to === Infinity);
    const nowRow = '<div class="sq-row is-now"><span class="sq-time">现在</span><span class="sq-track">' + lives + barsAt(rows.length) + '</span></div>';
    const wide = groups.map((g) => head(g, '') + (isOpen(g.n) ? g.rows.map(rowHtml).join('') + (g.n === latest && hasOpen ? nowRow : '') : '')).join('');
    const who = (r) => v.name(r.from) + ' → ' + r.to.map(v.name).join('、');
    const list = groups.map((g) => '<li>' + head(g, '') + (isOpen(g.n) ? '<ol>' + g.rows.map((r) => '<li><button type="button" class="sq-item' + (v.sel === r.ref ? ' is-on' : '') + (r.kind === 'ask' || r.kind === 'answer' ? ' is-dash' : '') + '" data-act="sq.row" data-r="' + esc(r.ref) + '"><small>' + esc(v.time(iso(r.t))) + ' · ' + esc(who(r)) + (r.open ? ' · 还没回答' : '') + '</small><span>' + esc(label(r)) + (r.verdict ? ' · ' + esc(verdictText(r.verdict)) : '') + '</span></button></li>').join('') + '</ol>' : '') + '</li>').join('');
    const scope = pair ? '只看 ' + esc(pair.map(v.name).join(' 与 ')) + ' · <button type="button" class="y20-link" data-act="sq.all">看全部</button>' : '整件事';
    const legend = '<span class="sq-legend"><i class="sq-key is-dash"></i>询问与回答<i class="sq-key is-ask"></i>在等回答' + (pair ? '' : '<i class="sq-key is-user"></i>等你决定') + '</span>';
    return '<section class="sq" id="lp-seq" aria-label="时序图"><div class="sq-head"><b>经过</b><span class="y20-small">' + scope + '</span>' + legend + '<button type="button" class="y20-icon-btn" data-act="sq.close" aria-label="收起时序图">' + Y20.ui.icon('close') + '</button></div>' +
      (rows.length ? '<div class="sq-wide"><div class="sq-row is-cols"><span class="sq-time"></span><span class="sq-track">' + cols.map((c) => '<b style="left:' + x(c) + '%">' + esc(v.name(c)) + '</b>').join('') + '</span></div>' + wide + '</div><ol class="sq-list">' + list + '</ol>' : '<p class="y20-muted y20-small">这两个职能之间还没有往来</p>') + '</section>';
  }

  Y20.sequence = { html };
}());
