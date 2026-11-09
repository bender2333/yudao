// 各协作方式共用的项目线程、新建项目与成果库。
// 假进展使用事项冻结的组织；数据存在项目的 p.lean 里，刷新恢复示例。
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
  const SENT = { three: '产品、工程、质检按成果协作，可在组织中增减部门', one_out: '交给外部 agent，交付后以开环完成结束', one_own: '直接说要求，一个角色负责完成', several: '一个角色主要执行，其他角色按需协助', pool_preview: '发布工作单元，由角色认领并逐项核验', ops_preview: '按成果协作，增加运行环境、故障与部署' };
  const ORDER = ['one_own', 'several', 'three', 'pool_preview', 'ops_preview', 'one_out'];
  const cards = (act, data) => ORDER.map((id) => {
    return '<button type="button" class="ln-card" data-act="' + act + '" data-form="' + id + '"' + (data || '') + '><strong>' + esc(id === 'three' ? '按成果协作' : O.formName(id)) + (id.endsWith('_preview') ? ui.tag('设计预览') : '') + '</strong><small>' + esc(SENT[id]) + '</small></button>';
  }).join('');

  // ---------------------------------------------------------------- 级别：页面跟着合成结果伸缩（角色数、有无核验角色、是否按成果轮转）

  const lv = (p) => { const c = p.composed; return { n: c.depts.length, ver: O.verifiers(c).length > 0, three: c.rotation === 'by_outcome', pool: c.rotation === 'pool' }; };
  const recv = (p) => O.firstReceivers(p.composed)[0] || { id: 'engineering', name: '工程' };
  const nm = (p, id) => O.deptName(p, id);

  // ---------------------------------------------------------------- 数据

  function seed(p) {
    if (p.demoThread) return clone(p.demoThread);
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
    const item = p.items.find((it) => it.status === 'working');
    return { vers: [], phase: null, note: '', model: '', cur: item ? item.id : null, stage: null, queue: [], to: null, manual: false, only: false, openV: {}, msgs: item ? [{ t: 'sep', item: item.id }, { t: 'you', item: item.id, text: item.title, tag: '新事项', at: item.created }, { t: 'fold', item: item.id, key: 'prog', lab: '工作进展', roles: [item.dept], open: false, kids: [{ who: item.dept, text: item.reason || '正在工作。' }] }] : [] };
  }
  const st = (p) => p.lean || (p.lean = seed(p));
  Y19.thread = { state: st, templates: cards };
  const active = (p) => { const it = st(p).cur && H.item(p, st(p).cur); return it && it.status === 'working' ? it : null; };
  const vname = (p) => (O.verifiers(p.composed)[0] || {}).name || '';
  const eng = (p) => nm(p, 'engineering');
  const here = (p) => Y19.state.route.params.project === p.id && $('ln-thread');
  const push = (p, m) => { m.at = m.at || T(++seq); st(p).msgs.push(m); };
  function readGuidance(p, ids, item) {
    st(p).msgs.filter((m) => ids.includes(m.target) && !m.readAt && (!m.item || m.item === item)).forEach((m) => { m.readAt = T(++seq); });
  }
  // 折叠行：同一个事项同一种往来只有一行，往来都进去
  function fold(p, it, key, lab, roles, who, text) {
    const ms = st(p).msgs;
    let f = ms.slice().reverse().find((m) => m.t === 'fold' && m.item === (it ? it.id : '') && m.key === key);
    if (!f) ms.push(f = { t: 'fold', item: it ? it.id : '', key, lab, roles, open: false, kids: [] });
    f.kids.push({ who, text, at: T(++seq) });
  }
  Y19.leanDecisions = (p) => st(p).msgs.filter((m) => m.t === 'ask' && !m.answer && p.items.some((it) => it.id === m.item && !['adopted', 'open_closed', 'stopped'].includes(it.status))).length + H.decisions(p.id).length;

  // ---------------------------------------------------------------- 收件人

  function options(p) {
    const it = active(p), c = it ? it.org.composed : p.composed, L = { three: c.rotation === 'by_outcome', pool: c.rotation === 'pool' }, r = O.firstReceivers(c)[0], o = [{ k: 'new', label: '开始新事项' }];
    if (L.three && it) o.push({ k: 'append', label: '追加输入（' + r.name + '接，重新验收）' });
    c.depts.forEach((d) => o.push({ k: 'g:' + d.id, label: '指导' + nm(p, d.id) }));
    return o;
  }
  // 默认收件人跟随当前事项实际正在工作的角色。
  function working(p) { const it = active(p); return it ? it.dept : recv(p).id; }
  const dflt = (p) => (active(p) ? 'g:' + working(p) : 'new');
  const cur = (p) => { const s = st(p); return s.manual && options(p).some((o) => o.k === s.to) ? s.to : dflt(p); };
  function hintText(p, k) {
    const it = active(p), r = k === 'append' && it ? O.firstReceivers(it.org.composed)[0] : recv(p);
    if (k === 'new') return it ? '排在「' + it.title + '」后面，它做完才开始' : r.name + '接，马上开始';
    if (k === 'append') return r.name + '接，已有的交付要重新验收';
    const target = k.slice(2), scoped = Y19.collaboration && Y19.collaboration.guidanceItem(p, target);
    return '发给' + nm(p, target) + (scoped ? ' · 当前事项「' + scoped.title + '」' : ' · 部门指导') + '，下一轮读取';
  }
  function toHtml(p) {
    const k = cur(p);
    const target = k.startsWith('g:') ? k : 'g:' + (Y19.collaboration ? Y19.collaboration.selected(p) : working(p));
    const visible = options(p).filter((o) => !o.k.startsWith('g:') || o.k === target);
    return '<div class="ln-pills" role="radiogroup" aria-label="发送用途"><span class="ln-to-label">发送用途</span>' + visible.map((o) => '<button type="button" role="radio" aria-checked="' + (o.k === k) + '" class="ln-pill' + (o.k === k ? ' is-on' : '') + '" data-act="ln.to" data-k="' + esc(o.k) + '">' + esc(o.label) + '</button>').join('') + '</div>' +
      '<div id="ln-hint" class="ln-hint">' + esc(hintText(p, k)) + '</div>';
  }
  A('ln.to', (el) => { const p = H.project(H.pid()), s = st(p); s.to = el.dataset.k; s.manual = true; if (s.to.startsWith('g:')) s.focusDept = s.to.slice(2); refresh(p); });
  document.addEventListener('keydown', (ev) => {
    if (!ev.target.matches('.ln-pill') || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(ev.key)) return;
    const choices = Array.from(document.querySelectorAll('.ln-pill')), at = choices.indexOf(ev.target);
    const index = ev.key === 'Home' ? 0 : ev.key === 'End' ? choices.length - 1 : (at + (ev.key === 'ArrowRight' ? 1 : -1) + choices.length) % choices.length;
    ev.preventDefault(); const key = choices[index].dataset.k; choices[index].click();
    Array.from(document.querySelectorAll('.ln-pill')).find((el) => el.dataset.k === key).focus();
  });

  // ---------------------------------------------------------------- 对话

  function threadHtml(p) {
    const s = st(p), L = lv(p);
    const archived = new Set();
    let section = null;
    s.msgs.forEach((m) => {
      if (m.t === 'sep') section = m.item;
      if ((m.t === 'done' || m.t === 'rel') && section && !s.only && !(s.openItems || {})[section]) archived.add(section);
    });
    let currentSection = null;
    const link = (m) => (L.n > 1 ? '<button type="button" class="y19-link" data-go="#/p/' + p.id + '/outcomes?v=' + m.vno + '">看这一版</button>'
      : '<button type="button" class="y19-link" data-act="ln.ver" data-v="' + m.vno + '">看这一版</button>');
    const vdiff = (m) => { const v = s.vers.find((x) => x.n === m.vno); return L.n === 1 && s.openV[m.vno] && v ? '<div class="ln-diff"><b>改了的文件</b><ul>' + v.files.map((f) => '<li>' + esc(f) + '</li>').join('') + '</ul>' + ui.pre(v.diff.join('\n')) + '</div>' : ''; };
    return s.msgs.map((m, i) => {
      if (m.t === 'sep') currentSection = m.item;
      if (archived.has(currentSection) && !['sep', 'done', 'rel'].includes(m.t) && !(m.target && !m.item)) return '';
      if (s.only && m.t !== 'done' && m.t !== 'rel') return '';
      const who = (name, cls, body, tag) => '<div class="ln-msg ' + cls + '"><div class="ln-meta">' + esc(name) + ' · ' + esc(ui.time(m.at)) + '</div>' + (tag ? '<div class="ln-tag">' + esc(tag) + '</div>' : '') + '<div class="ln-bubble">' + body + '</div></div>';
      switch (m.t) {
        case 'sep': { const it = H.item(p, m.item); if (!it) throw new Error('线程引用了不存在的事项：' + m.item); const res = { working: '进行中', open_closed: '开环完成', adopted: '放行', stopped: '已停止' }[it.status] || Y19.ITEM_STATUS[it.status][0]; return '<div class="ln-sep"><span>' + esc(it.title) + ' · ' + res + '</span>' + (['adopted', 'open_closed'].includes(it.status) ? '<button class="y19-link" type="button" data-act="ln.item-toggle" data-item="' + esc(it.id) + '">' + (archived.has(it.id) ? '展开对话' : '收起对话') + '</button>' : '') + '</div>'; }
        case 'you': return who('你', 'is-you', esc(m.text), m.tag);
        case 'ans': return who('你的回答', 'is-you', esc(m.text));
        case 'queue': return '<div class="ln-sep"><span>' + esc(m.text) + '</span></div>';
        case 'fold': return '<div class="ln-fold" id="ln-fold-' + i + '"><button type="button" class="ln-fold-head" aria-expanded="' + m.open + '" data-act="ln.fold" data-i="' + i + '">' + esc(m.lab) + ' ' + m.kids.length + ' 条</button>' +
          (m.open ? '<ul class="ln-fold-body">' + m.kids.map((k) => '<li><b>' + esc(nm(p, k.who)) + '</b> ' + esc(k.text) + '</li>').join('') + '</ul>' : '') + '</div>';
        case 'ask': return who(nm(p, m.who) + '要你决定', 'is-ask' + (m.answer ? ' is-answered' : ''), '<b>' + esc(m.text) + '</b><div class="ln-opts">' + m.options.map((o) => '<button type="button" class="y19-btn small' + (m.answer === o ? ' primary' : '') + '"' + (m.answer ? ' disabled' : ' data-act="ln.answer" data-i="' + i + '" data-o="' + esc(o) + '"') + '>' + esc(o) + '</button>').join('') + '</div>' + (m.answer ? '<small class="y19-muted">已回答：' + esc(m.answer) + '</small>' : ''));
        case 'notice': case 'stop': return '<div class="ln-notice">' + esc(m.text) + '</div>';
        case 'done': return who(m.who || eng(p), 'is-done', esc(m.text) + ' ' + link(m)) .replace(/<\/div><\/div>$/, vdiff(m) + '</div></div>');
        case 'rel': return who(m.who || vname(p), 'is-done', esc(m.text) + ' ' + link(m)).replace(/<\/div><\/div>$/, vdiff(m) + '</div></div>');
        default: return who('你', '', esc(m.text));
      }
    }).join('') || ui.empty(s.only ? '还没有交完成的事项。' : '还没有事项。在下面写一句，就开始做。');
  }
  const barHtml = (p) => {
    const e = p.elapsed;
    return '<div class="ln-time-row"><span>' + (active(p) ? '正在处理 · ' : '') + '已用 ' + esc(ui.duration(e.used)) + ' / 上限 ' + esc(ui.duration(e.limit)) + '</span>' + (lv(p).n === 1 ? '<label class="ln-only"><input type="checkbox" data-act="ln.only"' + (st(p).only ? ' checked' : '') + '> 只看交付</label>' : '') +
      (active(p) ? '<button type="button" class="y19-btn small danger" data-act="ln.stop">停止</button>' : '') + '</div>' + ui.meter(e.used, e.limit);
  };
  const sideHtml = (p) => Y19.collaboration.render(p);
  function inputLabel(p) {
    const k = cur(p), input = $('ln-text');
    if (!input) return;
    input.setAttribute('aria-label', k.startsWith('g:') ? '指导' + nm(p, k.slice(2)) : k === 'append' ? '追加当前事项的输入' : '开始新事项');
    input.placeholder = k.startsWith('g:') ? '给' + nm(p, k.slice(2)) + '的指导……' : k === 'append' ? '补充当前事项的要求……' : '说说你想做什么……';
  }
  function refresh(p, scroll) {
    if (!here(p)) return;
    const panel = $('ln-who'), panelScroll = panel.scrollTop;
    const focused = document.activeElement, focusKey = focused && focused.dataset && focused.dataset.act ? { act: focused.dataset.act, dept: focused.dataset.dept, k: focused.dataset.k } : null;
    $('ln-thread').innerHTML = threadHtml(p); $('ln-bar').innerHTML = barHtml(p); $('ln-to').innerHTML = toHtml(p); $('ln-who').innerHTML = sideHtml(p);
    panel.scrollTop = panelScroll; inputLabel(p);
    if (focusKey && !focused.isConnected) {
      const replacement = Array.from(document.querySelectorAll('[data-act]')).find((el) => el.dataset.act === focusKey.act && el.dataset.dept === focusKey.dept && el.dataset.k === focusKey.k);
      if (replacement) replacement.focus({ preventScroll: true });
    }
    if (scroll) $('ln-thread').scrollTop = 1e9;
  }

  function conversation(ctx, p) {
    const ds = H.decisions(p.id), extra = p.items.filter((it) => it.id !== st(p).cur && !['adopted', 'open_closed', 'stopped'].includes(it.status));
    const decisions = ds.length ? '<details class="ws-project-decisions"><summary>待你决定 · ' + ds.length + '</summary>' + Y19.cards.list(p.id) + '</details>' : '';
    const other = extra.length || p.provider_wait.length || p.interruptions.length ? '<details class="ws-other-work"><summary>其他事项与运行情况 · ' + extra.length + ' 项</summary><div class="ws-detail-body">' + extra.map((it) => '<a href="#/p/' + p.id + '/w/' + it.id + '">' + esc(it.title) + ' · ' + esc(Y19.ITEM_STATUS[it.status][0]) + '</a>').join('') + (p.provider_wait.length ? '<p>等待模型服务：' + p.provider_wait.length + ' 项</p>' : '') + (p.interruptions.length ? '<p>中断待恢复：' + p.interruptions.length + ' 项，请处理上面的决定请求。</p>' : '') + '<button type="button" class="y19-link" data-act="ws.advanced" data-to="#/p/' + p.id + '">查看完整运行详情</button></div></details>' : '';
    const multi = (active(p) ? active(p).org.composed : p.composed).depts.length > 1;
    return '<div class="ln' + (multi ? ' is-collaborative' : ' is-single') + '">' + (p.designPreview ? '<p class="ws-preview">设计预览 · 所有操作仅使用本页示例数据</p>' : '') + '<div id="ln-bar" class="ln-time">' + barHtml(p) + '</div><div class="ws-workspace"><div class="ws-conversation">' +
      decisions + other + '<div id="ln-thread" class="ln-thread">' + threadHtml(p) + '</div>' +
      '<form id="ln-form" class="ln-input" autocomplete="off"><div id="ln-to">' + toHtml(p) + '</div><div class="ln-row"><input type="text" class="y19-input" id="ln-text" placeholder="说说你想做什么……"><button type="submit" class="y19-btn primary">发送</button></div></form></div><aside id="ln-who" class="ws-collaboration" aria-label="部门结构与运行状态">' + sideHtml(p) + '</aside></div></div>';
  }
  function convMount(ctx, el, p) { inputLabel(p); const i = $('ln-text'); if (i) i.focus(); setTimeout(() => { const t = $('ln-thread'); if (t) t.scrollTop = 1e9; }, 0); }

  // 新事项的假进展：根据冻结定义确定执行者与核验者，约 3.5 秒交付或 5 秒放行。
  function run(p, it, seeded) {
    it.ran = true;
    const c = it.org.composed, s = st(p), open = O.ending(c).open;
    if (c.rotation === 'pool') { Y19.pool.start(p, it); refresh(p); return; }
    const first = c.depts.find((d) => d.id === it.dept) || O.firstReceivers(c)[0];
    const maker = c.rotation === 'direct' ? O.completer(c) : c.depts.find((d) => d.produces.includes(c.adopt));
    const verifiers = O.verifiers(c), names = verifiers.map((v) => v.name).join('、');
    const at = (ms, fn) => (timers[p.id] = timers[p.id] || []).push(setTimeout(() => { if (it.status !== 'working') return; fn(); refresh(p, true); }, ms));
    const progress = (d, text) => {
      it.dept = d.id;
      readGuidance(p, [d.id], it.id);
      fold(p, it, 'progress', '工作进展', [first.id, maker.id], d.id, text);
    };
    const deliver = () => {
      const n = s.vers.length + 1;
      s.vers.push({ n, item: it.id, at: T(++seq), text: '「' + it.title + '」的交付', concl: open ? '开环完成' : '等待核验', files: ['workspace/result.md'], diff: ['@@ workspace/result.md', '+ ' + (it.text || it.title).slice(0, 80)] });
      p.elapsed.used += 300;
      progress(maker, '已交回结果。');
      if (open) { push(p, { t: 'done', who: maker.name, item: it.id, text: '做完了。开环完成：最终成果没有独立核验。', vno: n }); finish(p, it, 'open_closed'); }
      else {
        it.dept = verifiers[0].id; s.phase = { item: it.id, state: 'verify' };
        readGuidance(p, verifiers.map((v) => v.id), it.id);
      }
    };
    at(500, () => progress(first, c.rotation === 'direct' ? '接到输入，开始工作。' : '接到输入，准备' + first.produces.map((k) => O.kindName(c, k)).join('、') + '。'));
    at(1800, () => progress(maker, c.rotation === 'direct' ? '正在制作结果并自检。' : '根据关注的成果，制作' + O.kindName(c, c.adopt) + '。'));
    at(3500, deliver);
    if (!open) at(5000, () => {
      const version = s.vers.find((v) => v.item === it.id && v.concl === '等待核验');
      version.concl = '放行';
      fold(p, it, 'verify', names + '的核验', verifiers.map((v) => v.id), verifiers[0].id, '独立核验通过。');
      push(p, { t: 'rel', who: names, item: it.id, text: '放行：' + names + '核验通过', vno: version.n });
      finish(p, it, 'adopted');
    });
  }
  function startItem(p, text, said, source) {
    const res = Y19.newItem(p, { title: text.replace(/\s+/g, ' ').slice(0, 16), text, source });
    if (!res.ok) { ui.toast('现在不能开始：' + res.rejects.join('；'), 'warn'); return false; }
    const s = st(p);
    s.cur = res.item.id; s.stage = 0; s.phase = null;
    push(p, { t: 'sep', item: res.item.id }); push(p, { t: 'you', item: res.item.id, text, tag: '新事项' });
    run(p, res.item); return true;
  }
  function finish(p, it, status) {
    const s = st(p);
    it.status = status; s.phase = null; s.stage = null;
    X.slotHolders[p.id] = (X.slotHolders[p.id] || []).filter((x) => x !== it.id); p.slots.used = Math.max(0, p.slots.used - 1);
    Object.keys(p.deptState).forEach((id) => {
      const d = p.deptState[id];
      if (!(d.items || []).includes(it.id) && id !== it.dept) return;
      const remaining = (d.items || []).filter((key) => key !== it.id && p.items.some((other) => other.id === key && !['adopted', 'open_closed', 'stopped'].includes(other.status)));
      p.deptState[id] = remaining.length ? Object.assign({}, d, { state: remaining.some((key) => H.item(p, key).status === 'working') ? 'running' : 'waiting_work', items: remaining, waits: (d.waits || []).filter((w) => w.item !== it.id), text: remaining.map((key) => H.item(p, key).title).join('、'), reason: '仍在处理：' + remaining.map((key) => H.item(p, key).title).join('、') }) : O.idleState(p, id);
    });
    if (s.queue.length) { const next = s.queue[0]; if (startItem(p, typeof next === 'string' ? next : next.text, true, next.source)) s.queue.shift(); } // 排着的新事项接着开始
  }

  function enqueue(p, text, source) {
    const it = active(p);
    if (!it) return startItem(p, text, false, source);
    st(p).queue.push({ text, source });
    push(p, { t: 'notice', text: '「' + text.slice(0, 28) + '」排在「' + it.title + '」之后。' });
    if (!it.ran) run(p, it, true);
    return true;
  }
  Object.assign(Y19.thread, { active, start: startItem, finish, refresh, run, enqueue, readGuidance });

  document.addEventListener('submit', (ev) => {
    if (ev.target.id !== 'ln-form') return;
    ev.preventDefault();
    const p = H.project(H.pid()), input = $('ln-text'), text = input.value.trim(), s = st(p);
    if (!text) return;
    const k = cur(p), it = active(p), tag = k === 'new' ? '新事项' : k === 'append' ? '追加输入' : '给' + nm(p, k.slice(2)) + '的指导';
    input.value = '';
    // 部门指导保持收件人，连续发送时仍发给用户选中的部门。
    if (!k.startsWith('g:')) { s.manual = false; s.to = null; s.focusDept = null; }
    if (k === 'new' && !it) { if (!startItem(p, text, false)) return; }
    else {
      const guided = k.startsWith('g:') && Y19.collaboration.guidanceItem(p, k.slice(2));
      push(p, Object.assign({ t: 'you', text, tag }, k.startsWith('g:') ? { target: k.slice(2), item: guided ? guided.id : null } : {}));
      if (k === 'new') { s.queue.push(text); push(p, { t: 'queue', text: '排在「' + it.title + '」后面，它做完才开始' }); if (!it.ran) run(p, it, true); }
      else if (k === 'append' && it) {
        (timers[p.id] || []).forEach(clearTimeout); timers[p.id] = [];
        s.vers.filter((v) => v.item === it.id && v.concl === '等待核验').forEach((v) => { v.concl = '已被追加输入替代'; });
        s.phase = null; it.text = (it.text || it.title) + '\n追加输入：' + text;
        it.dept = O.firstReceivers(it.org.composed)[0].id;
        push(p, { t: 'notice', item: it.id, text: '追加输入已交给' + nm(p, it.dept) + '，交付将重新制作并验收。' });
        run(p, it);
      }
    }
    refresh(p, true);
  });
  A('ln.stop', () => {
    const p = H.project(H.pid()), it = active(p);
    (timers[p.id] || []).forEach(clearTimeout); timers[p.id] = [];
    if (it.org.composed.rotation === 'pool') Y19.pool.stop(p);
    push(p, { t: 'stop', text: '你停止了这个事项' }); finish(p, it, 'stopped'); refresh(p, true);
  });
  A('ln.answer', (el) => {
    const p = H.project(H.pid()), m = st(p).msgs[Number(el.dataset.i)];
    m.answer = el.dataset.o; push(p, { t: 'ans', item: m.item, text: el.dataset.o });
    const it = active(p);
    if (it && !it.ran && !st(p).msgs.some((x) => x.t === 'ask' && x.item === it.id && !x.answer)) run(p, it, true);
    Y19.rerender();
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
  A('ln.item-toggle', (el) => { const p = H.project(H.pid()), s = st(p); s.openItems = s.openItems || {}; s.openItems[el.dataset.item] = !s.openItems[el.dataset.item]; refresh(p); });
  // 左侧栏的数字：跳到第一条没回答的决定，亮一下
  A('ln.jump', (el) => {
    Y19.go('#/p/' + el.dataset.p);
    setTimeout(() => { const b = document.querySelector('.ln-msg.is-ask:not(.is-answered)'); if (!b) { const list = document.querySelector('.ws-project-decisions'); if (list) { list.open = true; list.scrollIntoView({ block: 'center' }); } return; } b.scrollIntoView({ block: 'center' }); b.classList.add('is-flash'); setTimeout(() => b.classList.remove('is-flash'), 2000); }, 120);
  });

  // ---------------------------------------------------------------- 成果库

  function outcomes(ctx, p) {
    const vs = st(p).vers.slice().reverse(), concl = vs.some((v) => v.concl), open = Number(Y19.state.route.query.v);
    const cols = '<div class="ln-vrow is-head' + (concl ? ' has-concl' : '') + '"><span>第几版</span><span>事项</span><span>时间</span><span>一句话</span>' + (concl ? '<span>结论</span>' : '') + '</div>';
    return '<div class="ln-vers"><h1>成果库</h1><p class="y19-muted">每一版一行，点开看差异。</p>' + (vs.length ? cols : '') + (vs.map((v) => {
      const it = H.item(p, v.item);
      return '<details class="ln-ver"' + (v.n === open ? ' open' : '') + '><summary class="ln-vrow' + (concl ? ' has-concl' : '') + '"><span>第 ' + v.n + ' 版</span><span>' + esc(it ? it.title : '') + '</span><span>' + esc(ui.time(v.at)) + '</span><span>' + esc(v.text) + '</span>' + (concl ? '<span>' + esc(v.concl) + '</span>' : '') + '</summary>' +
        '<div class="ln-diff"><b>改了的文件</b><ul>' + v.files.map((f) => '<li>' + esc(f) + '</li>').join('') + '</ul>' + ui.pre(v.diff.join('\n')) + '</div></details>';
    }).join('') || ui.empty('还没有成果。')) + '</div>';
  }

  // ---------------------------------------------------------------- 设置

  A('ln.name', (el) => { const p = H.project(H.pid()); if (el.value.trim()) { p.name = el.value.trim(); Y19.rerender(); } });
  A('ln.goal', (el) => { H.project(H.pid()).goal = el.value.trim(); });
  A('ln.dir', (el) => { H.project(H.pid()).dir = el.value.trim(); });
  // ---------------------------------------------------------------- 外壳：单角色保留对话，多个角色共用三个主要入口。

  Y19.leanHas = (p, name) => Boolean(Y19.leanViews[name]) || /^(dept|org|item|recovery)/.test(name);
  Y19.leanTabs = (p, r) => {
    const L = lv(p);
    const b = (on, label, tail) => '<button type="button" class="y19-ptab' + (on ? ' is-active' : '') + '" data-go="#/p/' + p.id + tail + '">' + esc(label) + '</button>';
    const tabs = [b(r.name === 'overview', '对话', '')].concat(L.n > 1 ? [b(r.name === 'outcomes', '成果库', '/outcomes'), b(/^org/.test(r.name), '组织', '/org')] : []);
    return '<div class="y19-pheader"><button type="button" class="y19-pname" data-go="#/p/' + p.id + '">' + esc(p.name) + '</button>' + (L.n > 1 ? '<span class="ws-mode-label">' + esc(O.ROTATIONS[p.composed.rotation]) + ' · ' + L.n + ' 个部门或角色</span>' : '') + (L.n === 1 ? '<button type="button" class="y19-link" data-go="#/p/' + p.id + '/outcomes">查看交付</button>' : '') + '<button type="button" class="y19-link ws-project-settings' + (r.name === 'settings' ? ' is-current' : '') + '" data-go="#/p/' + p.id + '/settings">项目设置</button></div>' + (L.n > 1 ? '<div class="y19-ptabs" role="navigation" aria-label="项目页面">' + tabs.join('') + '</div>' : '');
  };
  Y19.leanViews.overview = { render: conversation, mount: convMount };
  Y19.leanViews.outcomes = { render: outcomes };

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
