// 简洁的项目页（最低一级：一个角色直做，可加一个核验角色）：对话、成果库、设置，加新建项目的模板卡与换模板。
// 判断用 org.js 的 O.lean(p)；假进展用定时器，数据存在项目的 p.lean 里（内存，刷新就回原样）。
(function () {
  'use strict';
  const Y19 = window.Y19;
  const O = Y19.org;
  const H = Y19.h;
  const ui = Y19.ui;
  const esc = Y19.esc;
  const X = Y19.EXTRA;
  const A = Y19.actions.register;
  const $ = (id) => document.getElementById(id);
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const T = (min) => Y19.time.add(Y19.app.now(), Math.round(min * 60));
  const timers = {};
  let seq = 0;

  // 设计说明 4.12 的表
  const SENT = { three: '产品写需求、工程做、质检核验，放行才算完成', one_out: '交给一个外部 agent 做，做完就结束，没有人核验', one_own: '一个人做，做完就结束，没有人核验', several: '几个人商量着做，一个人交完成，没有人核验', three_ops: '发布带还没有' };
  const ORDER = ['three', 'one_out', 'one_own', 'several', 'three_ops'];
  const cards = (act, data) => ORDER.map((id) => {
    const ok = id !== 'three_ops';
    return '<button type="button" class="ln-card' + (ok ? '' : ' is-off') + '"' + (ok ? ' data-act="' + act + '" data-form="' + id + '"' : ' disabled') + (data || '') + '><strong>' + esc(ok ? O.formName(id) : '三部门加运维') + (id === 'three' ? ui.tag('默认') : '') + '</strong><small>' + esc(SENT[id]) + '</small></button>';
  }).join('');

  // ---------------------------------------------------------------- 级别：页面跟着合成结果伸缩（角色数、有无核验角色、是否按成果轮转）

  const lv = (p) => { const c = p.composed; return { n: c.depts.length, ver: O.verifiers(c).length > 0, three: c.rotation !== 'direct' }; };
  const recv = (p) => O.firstReceivers(p.composed)[0] || { id: 'engineering', name: '工程' };
  const nm = (p, id) => O.deptName(p, id);
  const vid = (p) => (O.verifiers(p.composed)[0] || {}).id;
  const partner = (p) => p.composed.depts.find((d) => !d.verifies && d.id !== recv(p).id) || null; // 直做里的另一个做事角色（几个角色）

  // ---------------------------------------------------------------- 数据

  function seed(p) {
    const you = (item, text, tag, m) => ({ t: 'you', item, text, tag, at: T(m) });
    const fold = (item, key, lab, roles, kids, m) => ({ t: 'fold', item, key, lab, roles, open: false, kids: kids.map((k, i) => ({ who: k[0], text: k[1], at: T(m + i) })) });
    const ask = (item, who, text, m) => ({ t: 'ask', item, who, text, options: ['要', '不要'], answer: '', at: T(m) });
    const diff = (a, b) => ['@@ content/_index.md', '- ' + a, '+ ' + b];
    if (p.id === 'blog') return { vers: [{ n: 1, item: 'w13', at: T(-200), text: '128 篇文章已转成新格式，链接保持', concl: '开环完成', files: ['content/posts/（128 个文件）', 'content/_index.md'],
      diff: ['@@ content/_index.md', '- 共 128 篇，旧站点格式', '+ 共 128 篇，新站点格式', '@@ content/posts/2024/05/hello.md', '- <!-- more -->', '+ {{< more >}}'] }],
    phase: null, note: '', model: '', cur: 'w14', stage: null, queue: [], to: null, manual: false, only: false, openV: {},
    msgs: [
      { t: 'sep', item: 'w13' }, you('w13', '把旧站点的 128 篇文章迁到新站点', '新事项', -270),
      fold('w13', 'prog', '工程的进展', ['engineering'], [['engineering', '开始做了。先读旧站点的文章清单。'], ['engineering', '128 篇已转成新格式，正在检查链接。']], -268),
      { t: 'done', text: '做完了：128 篇已转成新格式，链接保持。开环完成：没有人核验', vno: 1, at: T(-200) },
      { t: 'sep', item: 'w14' }, you('w14', '把首页的文案改成新站点的介绍', '新事项', -9), you('w14', '保留三个栏目', '给工程的指导', -6),
      fold('w14', 'prog', '工程的进展', ['engineering'], [['engineering', '在改首页文案，三个栏目都保留了。']], -4),
      ask('w14', 'engineering', '首页要不要保留旧的访问计数？', -3)
    ] };
    if (p.id === 'signup') return { vers: [{ n: 1, item: 'w18', at: T(-300), text: '活动页文案已改，三处时间保持一致', concl: '开环完成', files: ['pages/event.md'], diff: diff('活动时间待定', '活动时间：周六 14:00，地点与截止日同页') }],
    phase: null, note: '', model: '', cur: 'w17', stage: null, queue: [], to: null, manual: false, only: false, openV: {},
    msgs: [
      { t: 'sep', item: 'w18' }, you('w18', '活动页上写清楚时间、地点、报名截止日', '新事项', -330),
      { t: 'done', text: '做完了：活动页文案已改，三处时间保持一致。开环完成：没有人核验', vno: 1, at: T(-300) },
      { t: 'sep', item: 'w17' }, you('w17', '做报名表单：姓名、手机号、参加人数，人数到上限就不能再报', '新事项', -40),
      fold('w17', 'pe', '工程与产品往来', ['engineering', 'product'], [['engineering', '报名要不要限人数？'], ['product', '每场 200 人。'], ['engineering', '满了怎么提示？']], -36),
      ask('w17', 'engineering', '满员后要候补名单吗？', -30)
    ] };
    if (p.id === 'orders') return { vers: [{ n: 1, item: 'w0', at: T(-600), text: '订单状态机：6 个状态、9 条转换', concl: '放行 · 检验覆盖 6/6', files: ['orders/state.ts', 'orders/state.test.ts'], diff: ['@@ orders/state.ts', '- if (o.paid && !o.cancelled) {', '+ transition(o, "paid")'] }],
    phase: null, note: '', model: '', cur: 'w1', stage: 2, queue: [], to: null, manual: false, only: false, openV: {},
    msgs: [
      { t: 'sep', item: 'w0' }, you('w0', '把订单状态改成明确的状态机，不再用散落的 if', '新事项', -700),
      fold('w0', 'pe', '产品与工程往来', ['product', 'engineering'], [['product', '状态机的 PRD 第 1 版：6 个状态、9 条转换。'], ['engineering', '已取消的订单还能退款吗？'], ['product', '不能，已取消只能终止。'], ['engineering', '按这个写，交付第 1 版。']], -690),
      fold('w0', 'eq', '工程与质检往来', ['engineering', 'quality'], [['quality', '第 1 版缺陷 2 条：已取消的订单还能被标记为已支付；转换表缺「发货中 → 已取消」。'], ['engineering', '第 2 版已改，请核验。'], ['quality', '12 条用例全部通过，可以放行。']], -640),
      { t: 'rel', text: '放行：质检核验通过', vno: 1, at: T(-600) },
      { t: 'sep', item: 'w1' }, you('w1', '把订单导出成 CSV 文件', '新事项', -60),
      fold('w1', 'pe', '产品与工程往来', ['product', 'engineering'], [['product', '导出订单为 CSV：按创建时间倒序，最多 5 万行。'], ['engineering', '文件名与编码怎么定？'], ['product', 'orders-日期.csv，UTF-8 带 BOM。']], -56),
      ask('w1', 'product', '金额列要不要带货币符号？', -20)
    ] };
    return { vers: [], phase: null, note: '', model: '', cur: null, stage: null, queue: [], to: null, manual: false, only: false, openV: {}, msgs: [] };
  }
  const st = (p) => p.lean || (p.lean = seed(p));
  const active = (p) => { const it = st(p).cur && H.item(p, st(p).cur); return it && it.status === 'working' ? it : null; };
  const isOpen = (it) => !it.org || O.ending(it.org.composed).open;
  const vname = (p) => (O.verifiers(p.composed)[0] || {}).name || '';
  const eng = (p) => nm(p, 'engineering');
  const here = (p) => Y19.state.route.params.project === p.id && $('ln-thread');
  const push = (p, m) => { m.at = m.at || T(++seq); st(p).msgs.push(m); };
  // 折叠行：同一个事项同一种往来只有一行，往来都进去
  function fold(p, it, key, lab, roles, who, text) {
    const ms = st(p).msgs;
    let f = ms.slice().reverse().find((m) => m.t === 'fold' && m.item === (it ? it.id : '') && m.key === key);
    if (!f) ms.push(f = { t: 'fold', item: it ? it.id : '', key, lab, roles, open: false, kids: [] });
    f.kids.push({ who, text, at: T(++seq) });
  }
  Y19.leanDecisions = (p) => (lv(p).n > 1 ? st(p).msgs.filter((m) => m.t === 'ask' && !m.answer).length : 0);

  // ---------------------------------------------------------------- 收件人

  function options(p) {
    const L = lv(p), r = recv(p), o = [{ k: 'new', label: '开始一个新事项' }];
    if (L.three) o.push({ k: 'append', label: '追加输入（' + r.name + '接，重新验收）' });
    (L.three ? p.composed.depts : [r]).forEach((d) => o.push({ k: 'g:' + d.id, label: '给' + nm(p, d.id) + '的指导' }));
    return o;
  }
  // 正在工作的部门或角色：三部门跟着事项走到哪一步
  function working(p) {
    const L = lv(p), s = st(p);
    if (!L.three) return recv(p).id;
    return s.phase && s.phase.state === 'verify' ? vid(p) : s.stage <= 1 ? recv(p).id : 'engineering';
  }
  const dflt = (p) => (active(p) ? 'g:' + working(p) : 'new');
  const cur = (p) => { const s = st(p); return s.manual && options(p).some((o) => o.k === s.to) ? s.to : dflt(p); };
  function hintText(p, k) {
    const r = recv(p), it = active(p);
    if (k === 'new') return it ? '排在「' + it.title + '」后面，它做完才开始' : r.name + '接，马上开始';
    if (k === 'append') return r.name + '接，已有的交付要重新验收';
    return '发给' + nm(p, k.slice(2)) + '，它下一轮读到';
  }
  function toHtml(p) {
    const k = cur(p);
    return '<div class="ln-pills" role="radiogroup" aria-label="收件人"><span class="ln-to-label">发给</span>' + options(p).map((o) => '<button type="button" role="radio" aria-checked="' + (o.k === k) + '" class="ln-pill' + (o.k === k ? ' is-on' : '') + '" data-act="ln.to" data-k="' + esc(o.k) + '">' + esc(o.label) + '</button>').join('') + '</div>' +
      '<div id="ln-hint" class="ln-hint">' + esc(hintText(p, k)) + '</div>';
  }
  A('ln.to', (el) => { const p = H.project(H.pid()), s = st(p); s.to = el.dataset.k; s.manual = true; $('ln-to').innerHTML = toHtml(p); });

  // ---------------------------------------------------------------- 对话

  function threadHtml(p) {
    const s = st(p), L = lv(p);
    const link = (m) => (L.n > 1 ? '<button type="button" class="y19-link" data-go="#/p/' + p.id + '/outcomes?v=' + m.vno + '">看这一版</button>'
      : '<button type="button" class="y19-link" data-act="ln.ver" data-v="' + m.vno + '">看这一版</button>');
    const vdiff = (m) => { const v = s.vers.find((x) => x.n === m.vno); return L.n === 1 && s.openV[m.vno] && v ? '<div class="ln-diff"><b>改了的文件</b><ul>' + v.files.map((f) => '<li>' + esc(f) + '</li>').join('') + '</ul>' + ui.pre(v.diff.join('\n')) + '</div>' : ''; };
    return s.msgs.map((m, i) => {
      if (s.only && m.t !== 'done' && m.t !== 'rel') return '';
      const who = (name, cls, body, tag) => '<div class="ln-msg ' + cls + '"><div class="ln-meta">' + esc(name) + ' · ' + esc(ui.time(m.at)) + '</div>' + (tag ? '<div class="ln-tag">' + esc(tag) + '</div>' : '') + '<div class="ln-bubble">' + body + '</div></div>';
      switch (m.t) {
        case 'sep': { const it = H.item(p, m.item); const res = { working: '进行中', open_closed: '开环完成', adopted: '放行', stopped: '已停止' }[it.status]; return '<div class="ln-sep"><span>' + esc(it.title) + ' · ' + res + '</span></div>'; }
        case 'you': return who('你', 'is-you', esc(m.text), m.tag);
        case 'ans': return who('你的回答', 'is-you', esc(m.text));
        case 'queue': return '<div class="ln-sep"><span>' + esc(m.text) + '</span></div>';
        case 'fold': return '<div class="ln-fold" id="ln-fold-' + i + '"><button type="button" class="ln-fold-head" aria-expanded="' + m.open + '" data-act="ln.fold" data-i="' + i + '">' + esc(m.lab) + ' ' + m.kids.length + ' 条</button>' +
          (m.open ? '<ul class="ln-fold-body">' + m.kids.map((k) => '<li><b>' + esc(nm(p, k.who)) + '</b> ' + esc(k.text) + '</li>').join('') + '</ul>' : '') + '</div>';
        case 'ask': return who(nm(p, m.who) + '要你决定', 'is-ask' + (m.answer ? ' is-answered' : ''), '<b>' + esc(m.text) + '</b><div class="ln-opts">' + m.options.map((o) => '<button type="button" class="y19-btn small' + (m.answer === o ? ' primary' : '') + '"' + (m.answer ? ' disabled' : ' data-act="ln.answer" data-i="' + i + '" data-o="' + esc(o) + '"') + '>' + esc(o) + '</button>').join('') + '</div>' + (m.answer ? '<small class="y19-muted">已回答：' + esc(m.answer) + '</small>' : ''));
        case 'done': return who(eng(p), 'is-done', esc(m.text) + ' ' + link(m)) .replace(/<\/div><\/div>$/, vdiff(m) + '</div></div>');
        case 'rel': return who(vname(p), 'is-done', esc(m.text) + ' ' + link(m)).replace(/<\/div><\/div>$/, vdiff(m) + '</div></div>');
        default: return who('你', '', esc(m.text));
      }
    }).join('') || ui.empty(s.only ? '还没有交完成的事项。' : '还没有事项。在下面写一句，就开始做。');
  }
  const barHtml = (p) => {
    const e = p.elapsed;
    return '<div class="ln-time-row"><span>已用 ' + esc(ui.duration(e.used)) + ' / 上限 ' + esc(ui.duration(e.limit)) + '</span>' + (lv(p).n === 1 ? '<label class="ln-only"><input type="checkbox" data-act="ln.only"' + (st(p).only ? ' checked' : '') + '> 只看交付</label>' : '') +
      (active(p) ? '<button type="button" class="y19-btn small danger" data-act="ln.stop">停止</button>' : '') + '</div>' + ui.meter(e.used, e.limit);
  };
  // 线程旁：几个角色是「谁在做什么」，三部门是窄带
  function sideHtml(p) {
    const L = lv(p), it = active(p), s = st(p), ph = s.phase;
    if (L.three) return '<div class="ln-band" aria-label="走到哪一步">' + ['输入', '需求', '交付', '放行'].map((n, i) => '<span class="ln-step' + (it && i === s.stage ? ' is-on' : it && i < s.stage ? ' is-past' : '') + '">' + n + '</span>').join('<i>→</i>') + (it ? '' : '<small class="y19-muted">没有事项在做</small>') + '</div>';
    if (L.n < 2) return '';
    const r = recv(p).id;
    return '<section class="ln-who"><h3>谁在做什么</h3>' + p.composed.depts.map((d) => {
      const t = d.verifies ? (ph && ph.state === 'verify' ? '在核验「' + it.title + '」' : '等' + eng(p) + '交完成')
        : d.id === r ? (it ? (ph ? '已交完成，等' + vname(p) + '核验' : '在做「' + it.title + '」') : '空闲') : '空闲，等' + eng(p) + '的询问';
      return '<button type="button" class="ln-who-row" data-act="ln.who" data-r="' + esc(d.id) + '"><strong>' + esc(d.name) + '</strong><span>' + esc(t) + '</span></button>';
    }).join('') + '</section>';
  }
  function refresh(p, scroll) {
    if (!here(p)) return;
    $('ln-thread').innerHTML = threadHtml(p); $('ln-bar').innerHTML = barHtml(p); $('ln-to').innerHTML = toHtml(p); $('ln-who').innerHTML = sideHtml(p);
    if (scroll) $('ln-thread').scrollTop = 1e9;
  }

  function conversation(ctx, p) {
    return '<div class="ln"><div id="ln-bar" class="ln-time">' + barHtml(p) + '</div><div id="ln-who">' + sideHtml(p) + '</div>' +
      '<div id="ln-thread" class="ln-thread">' + threadHtml(p) + '</div>' +
      '<form id="ln-form" class="ln-input" autocomplete="off"><div id="ln-to">' + toHtml(p) + '</div><div class="ln-row"><input type="text" class="y19-input" id="ln-text" aria-label="写给' + esc(recv(p).name) + '" placeholder="在这里写"><button type="submit" class="y19-btn primary">发送</button></div></form></div>';
  }
  function convMount(ctx, el, p) { const i = $('ln-text'); if (i) i.focus(); setTimeout(() => { const t = $('ln-thread'); if (t) t.scrollTop = 1e9; }, 0); }

  // 新事项的假进展，约 6 秒走完：
  // 三部门 产品→工程→质检→放行；直做 工程交完成（有核验角色时再质检核验、放行）。进展都进折叠行。
  // seeded：示例里本来就在做的事项排了后面的事项时，从中途接着走
  function run(p, it, seeded) {
    it.ran = true;
    const L = lv(p), s = st(p), open = L.three ? false : isOpen(it), e = 'engineering', pt = partner(p), v = vid(p), pn = nm(p, recv(p).id);
    const at = (ms, fn) => (timers[p.id] = timers[p.id] || []).push(setTimeout(() => { if (it.status !== 'working') return; fn(); refresh(p, true); }, ms));
    const prog = (who, text) => (L.three ? fold(p, it, 'pe', pn + '与' + eng(p) + '往来', [recv(p).id, e], who, text)
      : fold(p, it, 'prog', pt ? eng(p) + '与' + nm(p, pt.id) + '往来' : eng(p) + '的进展', [e, pt && pt.id].filter(Boolean), who, text));
    const check = (who, text) => fold(p, it, 'eq', eng(p) + '与' + vname(p) + '往来', [e, v], who, text);
    const make = () => {
      const n = s.vers.length + 1, res = '「' + it.title + '」已做好，第 ' + n + ' 版';
      s.vers.push({ n, item: it.id, at: T(++seq), text: res, concl: open ? '开环完成' : '放行', files: ['content/_index.md', 'content/about.md'],
        diff: ['@@ content/_index.md', '- 欢迎来到我的旧站点', '+ ' + (it.text || it.title).slice(0, 30), '@@ content/about.md', '- 旧的介绍', '+ 新站点的介绍'] });
      p.elapsed.used += 300;
      return { n, res };
    };
    const deliver = () => { const d = make(); check(e, '交付第 ' + d.n + ' 版，请核验。'); s.phase = { item: it.id, state: 'verify' }; };
    const release = () => { push(p, { t: 'rel', text: '放行：' + vname(p) + '核验通过', vno: s.vers.length }); s.stage = 3; finish(p, it, 'adopted'); };
    let steps;
    if (L.three) steps = [[300, () => { s.stage = 1; prog(recv(p).id, '接到输入，开始写需求。'); }], [1800, () => { s.stage = 2; prog(recv(p).id, '需求定了，交给' + eng(p) + '。'); prog(e, '开始做。'); }],
      [3200, () => prog(e, '写好了一版，正在自己检查。')], [4000, deliver], [5000, () => check(v, '在核验。')], [6000, release]];
    else {
      steps = [[1000, () => prog(e, '开始做了。')]].concat(pt ? [[2000, () => prog(pt.id, '先按现有的规则做。')]] : [], [[3000, () => prog(e, '写好了一版，正在自己检查。')]]);
      steps.push(open ? [5000, () => { const d = make(); push(p, { t: 'done', text: '做完了：' + d.res + '。开环完成：没有人核验', vno: d.n }); finish(p, it, 'open_closed'); }] : [5000, deliver]);
      if (!open) steps.push([6500, () => check(v, '在核验。')], [8000, release]);
    }
    const base = seeded ? 2500 : 0;
    steps.filter((x) => x[0] >= base + 500).forEach((x) => at(x[0] - base, x[1]));
  }
  function startItem(p, text, said) {
    const res = Y19.newItem(p, { title: text.replace(/\s+/g, ' ').slice(0, 16), text });
    if (!res.ok) { ui.toast('现在不能开始：' + res.rejects.join('；'), 'warn'); return false; }
    const s = st(p);
    s.cur = res.item.id; s.stage = 0; s.phase = null;
    push(p, { t: 'sep', item: res.item.id }); if (!said) push(p, { t: 'you', text, tag: '新事项' });
    run(p, res.item); return true;
  }
  function finish(p, it, status) {
    const s = st(p);
    it.status = status; s.phase = null; s.stage = null;
    X.slotHolders[p.id] = (X.slotHolders[p.id] || []).filter((x) => x !== it.id); p.slots.used = Math.max(0, p.slots.used - 1);
    p.deptState[it.dept] = O.idleState(p, it.dept);
    if (s.queue.length) startItem(p, s.queue.shift(), true); // 排着的新事项接着开始
  }

  document.addEventListener('submit', (ev) => {
    if (ev.target.id !== 'ln-form') return;
    ev.preventDefault();
    const p = H.project(H.pid()), input = $('ln-text'), text = input.value.trim(), s = st(p);
    if (!text) return;
    const k = cur(p), it = active(p), tag = k === 'new' ? '新事项' : k === 'append' ? '追加输入' : '给' + nm(p, k.slice(2)) + '的指导';
    input.value = ''; s.manual = false; s.to = null; // 发送后收件人回到默认
    if (k === 'new' && !it) { if (!startItem(p, text, false)) return; }
    else {
      push(p, { t: 'you', text, tag });
      if (k === 'new') { s.queue.push(text); push(p, { t: 'queue', text: '排在「' + it.title + '」后面，它做完才开始' }); if (!it.ran) run(p, it, true); }
      else if (k === 'append') fold(p, it, 'pe', nm(p, recv(p).id) + '与' + eng(p) + '往来', [recv(p).id, 'engineering'], recv(p).id, '收到追加输入，已有的交付要重新验收。');
    }
    refresh(p, true);
  });
  A('ln.stop', () => {
    const p = H.project(H.pid()), it = active(p);
    (timers[p.id] || []).forEach(clearTimeout); timers[p.id] = [];
    push(p, { t: 'stop', text: '你停止了这个事项' }); finish(p, it, 'stopped'); refresh(p, true);
  });
  A('ln.answer', (el) => {
    const p = H.project(H.pid()), m = st(p).msgs[Number(el.dataset.i)];
    m.answer = el.dataset.o; push(p, { t: 'ans', text: el.dataset.o }); Y19.rerender();
  });
  A('ln.fold', (el) => { const p = H.project(H.pid()), m = st(p).msgs[Number(el.dataset.i)]; m.open = !m.open; refresh(p); });
  A('ln.only', (el) => { const p = H.project(H.pid()); st(p).only = el.checked; refresh(p, true); });
  A('ln.ver', (el) => { const p = H.project(H.pid()), o = st(p).openV; o[el.dataset.v] = !o[el.dataset.v]; refresh(p); });
  // 「谁在做什么」点一行，展开线程里这个角色最近的那一行往来
  A('ln.who', (el) => {
    const p = H.project(H.pid()), ms = st(p).msgs;
    let i = -1; ms.forEach((m, n) => { if (m.t === 'fold' && m.roles.includes(el.dataset.r)) i = n; });
    if (i < 0) { ui.toast('这个角色还没有往来', 'info'); return; }
    ms[i].open = !ms[i].open; refresh(p);
    const f = $('ln-fold-' + i); if (f && f.scrollIntoView) f.scrollIntoView({ block: 'nearest' });
  });
  // 左侧栏的数字：跳到第一条没回答的决定，亮一下
  A('ln.jump', (el) => {
    Y19.go('#/p/' + el.dataset.p);
    setTimeout(() => { const b = document.querySelector('.ln-msg.is-ask:not(.is-answered)'); if (!b) return; b.scrollIntoView({ block: 'center' }); b.classList.add('is-flash'); setTimeout(() => b.classList.remove('is-flash'), 2000); }, 120);
  });

  // ---------------------------------------------------------------- 成果库

  function outcomes(ctx, p) {
    const vs = st(p).vers.slice().reverse(), concl = O.verifiers(p.composed).length > 0, open = Number(Y19.state.route.query.v);
    const cols = '<div class="ln-vrow is-head' + (concl ? ' has-concl' : '') + '"><span>第几版</span><span>事项</span><span>时间</span><span>一句话</span>' + (concl ? '<span>结论</span>' : '') + '</div>';
    return '<div class="ln-vers"><h1>成果库</h1><p class="y19-muted">每一版一行，点开看差异。</p>' + (vs.length ? cols : '') + (vs.map((v) => {
      const it = H.item(p, v.item);
      return '<details class="ln-ver"' + (v.n === open ? ' open' : '') + '><summary class="ln-vrow' + (concl ? ' has-concl' : '') + '"><span>第 ' + v.n + ' 版</span><span>' + esc(it ? it.title : '') + '</span><span>' + esc(ui.time(v.at)) + '</span><span>' + esc(v.text) + '</span>' + (concl ? '<span>' + esc(v.concl) + '</span>' : '') + '</summary>' +
        '<div class="ln-diff"><b>改了的文件</b><ul>' + v.files.map((f) => '<li>' + esc(f) + '</li>').join('') + '</ul>' + ui.pre(v.diff.join('\n')) + '</div></details>';
    }).join('') || ui.empty('还没有成果。')) + '</div>';
  }

  // ---------------------------------------------------------------- 设置

  function orgText(p) {
    const L = lv(p), c = p.composed, vs = O.verifiers(c).map((v) => v.name), ws = c.depts.filter((d) => !d.verifies).map((d) => d.name);
    if (L.three) return ws.concat(vs).join('、') + '，' + (vs[0] || '质检') + '放行才算完成';
    return (ws.length > 1 ? ws.join('、') + '商量着做' : '一个人做') + '，' + (vs.length ? vs[0] + '核验' : '没有人核验');
  }
  function settings(ctx, p) {
    const s = st(p), vn = vname(p), models = O.modelChoices(), L = lv(p);
    const goal = p.goal && p.goal.indexOf('（还没有') !== 0 ? p.goal : '';
    const row = (k, v) => '<div class="ln-set"><label>' + k + '</label><div>' + v + '</div></div>';
    return '<div class="ln-settings"><h1>设置</h1>' + (s.note ? '<div class="y19-note is-info" id="ln-note">' + esc(s.note) + '</div>' : '') +
      row('名字', '<input type="text" class="y19-input" id="ln-set-name" value="' + esc(p.name) + '" data-act="ln.name">') +
      row('长期目标（可选）', '<textarea class="y19-textarea" rows="2" data-act="ln.goal" placeholder="这个项目长期要做成什么样，可以不写">' + esc(goal) + '</textarea>') +
      row('起始文件夹', '<input type="text" class="y19-input" data-act="ln.dir" value="' + esc(p.dir || '') + '" placeholder="控制主机上的路径，可以不填">') +
      row('模型', '<select class="y19-select" data-act="ln.model"><option value="">跟随全局</option>' + models.map((m) => '<option' + (s.model === m ? ' selected' : '') + '>' + esc(m) + '</option>').join('') + '</select>') +
      row('组织', '<span id="ln-org">' + esc(orgText(p)) + '</span> ' + (L.three ? '' : '<button type="button" class="y19-btn small" data-act="ln.verifier">' + (vn ? '去掉核验角色' : '加一个核验角色') + '</button> ') + '<button type="button" class="y19-btn small" data-act="ln.swap">换模板</button>') +
      '<details class="ln-adv"><summary>高级</summary><p>改名、加部门、编辑定义、成果写回、机器授权、执行位置、MCP 服务器都在这里。</p>' +
      (L.three ? '<button type="button" class="y19-link" data-go="#/p/' + p.id + '/org">组织页</button>' : '<button type="button" class="y19-link" data-act="ln.adv" data-to="#/p/' + p.id + '/org">组织页</button>') + ' · <button type="button" class="y19-link" data-act="ln.adv" data-to="#/p/' + p.id + '/settings">完整的设置页</button></details></div>';
  }
  A('ln.name', (el) => { const p = H.project(H.pid()); if (el.value.trim()) { p.name = el.value.trim(); Y19.rerender(); } });
  A('ln.goal', (el) => { H.project(H.pid()).goal = el.value.trim(); });
  A('ln.dir', (el) => { H.project(H.pid()).dir = el.value.trim(); });
  A('ln.model', (el) => { st(H.project(H.pid())).model = el.value; });
  A('ln.adv', (el) => { Y19.setAdv(H.pid()); Y19.go(el.dataset.to); });

  // 加 / 去掉核验角色：改合成结果，写一条历史；只对之后新建的事项生效
  A('ln.verifier', () => {
    const p = H.project(H.pid()), ch = clone(p.org.changes), has = Boolean(vname(p));
    if (has) O.removeDept(ch, p.org.form, [], 'quality');
    else { const d = O.publishedDept(p.composed, 'quality'); ch.depts = ch.depts || {}; ch.depts.quality = { added: true, name: d.name, goal: d.goal, judge: d.judge, how: d.how, watches: d.watches, produces: d.produces, tools: d.tools, write: d.write, who: { type: 'own' }, verifies: d.verifies, completes: false }; }
    const res = O.adopt(p, { base: p.version, form: p.org.form, changes: ch, pending: {}, reason: has ? '去掉核验角色' : '加一个核验角色：' + d0(p) + '核验' + eng(p) + '交的完成' });
    if (!res.ok) { ui.toast(res.error + (res.rejects ? '：' + res.rejects.map((x) => x.text).join('；') : ''), 'warn'); return; }
    st(p).note = has ? '已去掉核验角色。在跑的事项按原来的做完，之后新建的事项做完就以开环完成结束' : '在跑的事项按原来的做完，之后新建的事项等' + vname(p) + '放行才结束';
    push(p, { t: 'queue', text: st(p).note });
    Y19.rerender();
  });
  const d0 = () => O.releaseDeptName('quality');

  // 换模板：点卡一步生效；有改动时确认一次
  A('ln.swap', () => ui.modal({ title: '换模板', wide: true, body: '<div class="ln-cards">' + cards('ln.pick') + '</div>', actions: [{ label: '取消', close: true }] }));
  A('ln.pick', (el) => {
    const p = H.project(H.pid()), id = el.dataset.form;
    if (O.count(p.org.changes) && !el.dataset.sure) {
      const lost = O.diff(O.compose({ form: p.org.form, changes: {} }), p.composed);
      ui.modal({ title: '换成「' + O.formName(id) + '」？', body: '<p>现在的改动会丢掉：</p><ul class="y19-org-diff">' + lost.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul><p class="y19-small y19-muted">记录里还在，改回能找回。</p>', actions: [{ label: '换', kind: 'primary', act: 'ln.pick', data: { form: id, sure: '1' } }, { label: '取消', close: true }] });
      return;
    }
    const res = O.adopt(p, { base: p.version, form: id, changes: {}, pending: {}, reason: '换模板：' + O.formName(id) });
    ui.closeModal();
    if (!res.ok) { ui.toast(res.error, 'warn'); return; }
    st(p).note = '';
    Y19.go('#/p/' + p.id);
    Y19.rerender();
  });

  // ---------------------------------------------------------------- 外壳：标签（跟着级别：几个角色加成果库，三部门再加部门页与组织页）

  Y19.leanHas = (p, name) => Boolean(Y19.leanViews[name]) || (lv(p).three && /^(dept|org)/.test(name));
  Y19.leanTabs = (p, r) => {
    const L = lv(p);
    const b = (on, label, tail) => '<button type="button" class="y19-ptab' + (on ? ' is-active' : '') + '" data-go="#/p/' + p.id + tail + '">' + esc(label) + '</button>';
    const tabs = [b(r.name === 'overview', '对话', '')].concat(L.n > 1 ? [b(r.name === 'outcomes', '成果库', '/outcomes')] : [],
      L.three ? p.composed.depts.map((d) => b(r.name === 'dept' && r.params.dept === d.id, nm(p, d.id), '/dept/' + d.id)).concat([b(/^org/.test(r.name), '组织', '/org')]) : [], [b(r.name === 'settings', '设置', '/settings')]);
    return '<div class="y19-pheader"><button type="button" class="y19-pname" data-go="#/p/' + p.id + '">' + esc(p.name) + '</button></div><div class="y19-ptabs" role="navigation" aria-label="项目页面">' + tabs.join('') + '</div>';
  };
  Y19.leanViews.overview = { render: conversation, mount: convMount };
  Y19.leanViews.outcomes = { render: outcomes };
  Y19.leanViews.settings = { render: settings };

  // ---------------------------------------------------------------- 新建项目、接入已有项目：名字加一张模板卡

  function dialog(attach) {
    const px = attach ? 'pa' : 'pn';
    const projects = Y19.W().projects.map((p) => '<option value="' + p.id + '">' + esc(p.name) + '</option>').join('');
    const body = '<div class="ln-new" data-np="' + px + '"><input type="text" class="y19-input" id="ln-name" aria-label="项目名字" placeholder="项目名字" data-live data-act="ln.clear">' +
      '<div class="ln-warn" id="ln-warn"></div>' +
      (attach ? '<input type="text" class="y19-input" id="ln-dir" placeholder="源目录：控制主机上已有项目的绝对路径" data-live data-act="ln.clear">' : '') +
      '<p class="y19-muted y19-small">点一张模板卡，项目就建好了。</p><div class="ln-cards">' + cards('ln.create') + '</div>' +
      '<input type="radio" name="' + px + '-org" id="' + px + '-radio" value="three" checked hidden><input type="checkbox" id="' + px + '-obs" hidden><input type="checkbox" id="' + px + '-sub" hidden>' +
      '<div class="ln-more">' + (attach ? '' : '<button type="button" class="y19-link" data-act="ln.toggle" data-t="ln-dirbox">选起始文件夹</button> ') + '<button type="button" class="y19-link" data-act="ln.toggle" data-t="ln-advbox">高级</button></div>' +
      '<div id="ln-dirbox" hidden><input type="text" class="y19-input" id="pn-dir" placeholder="控制主机上的路径，可以不填"></div>' +
      '<div id="ln-advbox" class="ln-advbox" hidden><label class="y19-field"><span>和某项目一样</span><select class="y19-select" id="' + px + '-same"><option value="">不用</option>' + projects + '</select><small class="y19-muted">选了以后，点任意一张卡都按那个项目的组织建。</small></label>' +
      '<label class="y19-check"><input type="checkbox" data-act="ln.layer" data-id="' + px + '-obs"><span>加观察者</span></label><label class="y19-check"><input type="checkbox" data-act="ln.layer" data-id="' + px + '-sub"><span>工程内部用子组织（中心型小组）</span></label></div></div>';
    ui.modal({ title: attach ? '接入已有项目' : '新建项目', wide: true, body, actions: [] });
  }
  A('np.new', () => dialog(false));
  A('np.attach', () => dialog(true));
  A('ln.clear', () => { $('ln-warn').textContent = ''; });
  A('ln.toggle', (el) => { $(el.dataset.t).hidden = !$(el.dataset.t).hidden; });
  A('ln.layer', (el) => { $(el.dataset.id).checked = el.checked; });
  A('ln.create', (el) => {
    const px = el.closest('[data-np]').dataset.np, name = $('ln-name').value.trim(), dir = attach_dir(px);
    const need = !name ? ['ln-name', '先写名字'] : px === 'pa' && !dir ? ['ln-dir', '先写源目录'] : null;
    if (need) { $('ln-warn').textContent = need[1]; $(need[0]).focus(); return; }
    const radio = $(px + '-radio'), same = $(px + '-same').value;
    radio.value = same ? 'same' : el.dataset.form;
    const spec = { name, goal: '', dir, org: Y19.np.pickedOrg(px) };
    if (px === 'pa') { Y19.np.attachDo(spec); return; }
    const p = Y19.np.createProject(spec);
    ui.closeModal();
    Y19.go('#/p/' + p.id);
  });
  const attach_dir = (px) => (px === 'pa' ? $('ln-dir').value.trim() : $('pn-dir').value.trim());
})();
