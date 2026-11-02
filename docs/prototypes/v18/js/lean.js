// 简洁的项目页（最低一级：一个角色直做，可加一个核验角色）：对话、成果库、设置，加新建项目的模板卡与换模板。
// 判断用 org.js 的 O.lean(p)；假进展用定时器，数据存在项目的 p.lean 里（内存，刷新就回原样）。
(function () {
  'use strict';
  const Y18 = window.Y18;
  const O = Y18.org;
  const H = Y18.h;
  const ui = Y18.ui;
  const esc = Y18.esc;
  const X = Y18.EXTRA;
  const A = Y18.actions.register;
  const $ = (id) => document.getElementById(id);
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const T = (min) => Y18.time.add(Y18.app.now(), Math.round(min * 60));
  const timers = {};
  let seq = 0;

  // 设计说明 4.12 的表
  const SENT = { three: '产品写需求、工程做、质检核验，放行才算完成', one_out: '交给一个外部 agent 做，做完就结束，没有人核验', one_own: '一个人做，做完就结束，没有人核验', several: '几个人商量着做，一个人交完成，没有人核验', three_ops: '发布带还没有' };
  const ORDER = ['three', 'one_out', 'one_own', 'several', 'three_ops'];
  const cards = (act, data) => ORDER.map((id) => {
    const ok = id !== 'three_ops';
    return '<button type="button" class="ln-card' + (ok ? '' : ' is-off') + '"' + (ok ? ' data-act="' + act + '" data-form="' + id + '"' : ' disabled') + (data || '') + '><strong>' + esc(ok ? O.formName(id) : '三部门加运维') + (id === 'three' ? ui.tag('默认') : '') + '</strong><small>' + esc(SENT[id]) + '</small></button>';
  }).join('');

  // ---------------------------------------------------------------- 数据

  function seed(p) {
    const you = (item, text, m) => ({ t: 'you', item, text, at: T(m) });
    return { vers: [{ n: 1, item: 'w13', at: T(-200), text: '128 篇文章已转成新格式，链接保持', concl: '开环完成', files: ['content/posts/（128 个文件）', 'content/_index.md'],
      diff: ['@@ content/_index.md', '- 共 128 篇，旧站点格式', '+ 共 128 篇，新站点格式', '@@ content/posts/2024/05/hello.md', '- <!-- more -->', '+ {{< more >}}'] }],
    phase: null, note: '', model: '',
    msgs: [
      { t: 'sep', item: 'w13' }, you('w13', '把旧站点的 128 篇文章迁到新站点', -270),
      { t: 'prog', text: '工程开始做了。先读旧站点的文章清单。', at: T(-268) }, { t: 'prog', text: '128 篇已转成新格式，正在检查链接。', at: T(-230) },
      { t: 'ask', item: 'w13', text: '旧站点的评论要不要迁？', options: ['要', '不要'], answer: '不要', at: T(-225) }, { t: 'ans', text: '不要', at: T(-224) },
      { t: 'done', text: '做完了：128 篇已转成新格式，链接保持。开环完成：没有人核验', vno: 1, at: T(-200) },
      { t: 'sep', item: 'w14' }, you('w14', '把首页的文案改成新站点的介绍', -9),
      { t: 'guide', text: '保留三个栏目', at: T(-6) }, { t: 'prog', text: '工程在改首页文案，三个栏目都保留了。', at: T(-4) }
    ] };
  }
  const st = (p) => p.lean || (p.lean = p.id === 'blog' ? seed(p) : { vers: [], phase: null, note: '', model: '', msgs: [] });
  const active = (p) => p.items.find((i) => i.status === 'working') || null;
  const isOpen = (it) => !it.org || O.ending(it.org.composed).open;
  const vname = (p) => (O.verifiers(p.composed)[0] || {}).name || '';
  const eng = (p) => O.deptName(p, 'engineering');
  const here = (p) => Y18.state.route.params.project === p.id && $('ln-thread');
  const push = (p, m) => { m.at = m.at || T(++seq); st(p).msgs.push(m); };

  // ---------------------------------------------------------------- 对话

  function threadHtml(p) {
    return st(p).msgs.map((m) => {
      const who = (name, cls, body) => '<div class="ln-msg ' + cls + '"><div class="ln-meta">' + esc(name) + ' · ' + esc(ui.time(m.at)) + '</div><div class="ln-bubble">' + body + '</div></div>';
      switch (m.t) {
        case 'sep': { const it = H.item(p, m.item); const res = { working: '进行中', open_closed: '开环完成', adopted: '放行', stopped: '已停止' }[it.status]; return '<div class="ln-sep"><span>' + esc(it.title) + ' · ' + res + '</span></div>'; }
        case 'you': return who('你', 'is-you', esc(m.text));
        case 'guide': return who('你的指导', 'is-you', esc(m.text));
        case 'ans': return who('你的回答', 'is-you', esc(m.text));
        case 'prog': return who(eng(p), '', esc(m.text));
        case 'ask': return who(eng(p) + '要你决定', '', '<b>' + esc(m.text) + '</b><div class="ln-opts">' + m.options.map((o) => '<button type="button" class="y18-btn small' + (m.answer === o ? ' primary' : '') + '"' + (m.answer ? ' disabled' : ' data-act="ln.answer" data-i="' + st(p).msgs.indexOf(m) + '" data-o="' + esc(o) + '"') + '>' + esc(o) + '</button>').join('') + '</div>' + (m.answer ? '<small class="y18-muted">已回答：' + esc(m.answer) + '</small>' : ''));
        case 'done': return who(eng(p), 'is-done', esc(m.text) + ' <button type="button" class="y18-link" data-go="#/p/' + p.id + '/outcomes?v=' + m.vno + '">看这一版</button>');
        case 'rel': return who(vname(p), 'is-done', esc(m.text) + ' <button type="button" class="y18-link" data-go="#/p/' + p.id + '/outcomes?v=' + m.vno + '">看这一版</button>');
        default: return who(m.t === 'stop' ? '你' : vname(p), '', esc(m.text));
      }
    }).join('') || ui.empty('还没有事项。在下面写一句，就开始做。');
  }
  const barHtml = (p) => {
    const e = p.elapsed;
    return '<div class="ln-time-row"><span>已用 ' + esc(ui.duration(e.used)) + ' / 上限 ' + esc(ui.duration(e.limit)) + '</span>' + (active(p) ? '<button type="button" class="y18-btn small danger" data-act="ln.stop">停止</button>' : '') + '</div>' + ui.meter(e.used, e.limit);
  };
  const hintText = (p) => (active(p) ? '写一句给' + eng(p) + '的指导' : '写一句就开始一个新事项');
  function whoHtml(p) {
    if (!O.verifiers(p.composed).length) return '';
    const it = active(p), ph = st(p).phase;
    const row = (n, t) => '<div class="ln-who-row"><strong>' + esc(n) + '</strong><span>' + esc(t) + '</span></div>';
    return '<section class="ln-who"><h3>谁在做什么</h3>' + row(eng(p), it && (!ph || ph.state === 'work') ? '在做「' + it.title + '」' : it ? '已交完成，等' + vname(p) + '核验' : '空闲') +
      row(vname(p), ph && ph.state === 'verify' ? '在核验「' + it.title + '」' : '等' + eng(p) + '交完成') + '</section>';
  }
  function refresh(p, scroll) {
    if (!here(p)) return;
    $('ln-thread').innerHTML = threadHtml(p); $('ln-bar').innerHTML = barHtml(p); $('ln-hint').textContent = hintText(p); $('ln-who').innerHTML = whoHtml(p);
    if (scroll) $('ln-thread').scrollTop = 1e9;
  }

  function conversation(ctx, p) {
    const s = st(p);
    return '<div class="ln"><div id="ln-bar" class="ln-time">' + barHtml(p) + '</div><div id="ln-who">' + whoHtml(p) + '</div>' +
      '<div id="ln-thread" class="ln-thread">' + threadHtml(p) + '</div>' +
      '<form id="ln-form" class="ln-input" autocomplete="off"><div id="ln-hint" class="ln-hint">' + esc(hintText(p)) + '</div><div class="ln-row"><input type="text" class="y18-input" id="ln-text" aria-label="写给' + esc(eng(p)) + '" placeholder="在这里写"><button type="submit" class="y18-btn primary">发送</button></div></form></div>';
  }
  function convMount(ctx, el, p) { const i = $('ln-text'); if (i) i.focus(); setTimeout(() => { const t = $('ln-thread'); if (t) t.scrollTop = 1e9; }, 0); }

  // 新事项的假进展：约 1 秒、3 秒出现进展，5 秒交完成；有核验角色时再 1.5 秒质检在核验、再 1.5 秒放行
  function run(p, it) {
    const open = isOpen(it), s = st(p);
    const at = (ms, fn) => (timers[p.id] = timers[p.id] || []).push(setTimeout(() => { if (it.status !== 'working') return; fn(); refresh(p, true); }, ms));
    at(1000, () => push(p, { t: 'prog', text: '工程开始做了。' }));
    at(3000, () => push(p, { t: 'prog', text: '写好了一版，正在自己检查。' }));
    at(5000, () => {
      const n = s.vers.length + 1, res = '「' + it.title + '」已做好，成果库多了第 ' + n + ' 版';
      s.vers.push({ n, item: it.id, at: T(++seq), text: res, concl: open ? '开环完成' : '放行', files: ['content/_index.md', 'content/about.md'],
        diff: ['@@ content/_index.md', '- 欢迎来到我的旧站点', '+ ' + it.text.slice(0, 30), '@@ content/about.md', '- 旧的介绍', '+ 新站点的介绍'] });
      p.elapsed.used += 300;
      if (open) { push(p, { t: 'done', text: '做完了：' + res + '。开环完成：没有人核验', vno: n }); finish(p, it, 'open_closed'); } else { push(p, { t: 'done', text: '工程交完成：' + res, vno: n }); s.phase = { item: it.id, state: 'verify' }; }
    });
    if (!open) {
      at(6500, () => push(p, { t: 'check', text: '质检在核验。' }));
      at(8000, () => { push(p, { t: 'rel', text: '放行：质检核验通过', vno: s.vers.length }); finish(p, it, 'adopted'); });
    }
  }
  function finish(p, it, status) {
    it.status = status; st(p).phase = null;
    X.slotHolders[p.id] = (X.slotHolders[p.id] || []).filter((x) => x !== it.id); p.slots.used = Math.max(0, p.slots.used - 1);
    p.deptState[it.dept] = O.idleState(p, it.dept);
  }

  document.addEventListener('submit', (ev) => {
    if (ev.target.id !== 'ln-form') return;
    ev.preventDefault();
    const p = H.project(H.pid()), input = $('ln-text'), text = input.value.trim();
    if (!text) return;
    input.value = '';
    if (active(p)) push(p, { t: 'guide', text });
    else {
      const res = Y18.newItem(p, { title: text.replace(/\s+/g, ' ').slice(0, 16), text });
      if (!res.ok) { ui.toast('现在不能开始：' + res.rejects.join('；'), 'warn'); return; }
      push(p, { t: 'sep', item: res.item.id }); push(p, { t: 'you', text }); run(p, res.item);
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
    m.answer = el.dataset.o; push(p, { t: 'ans', text: el.dataset.o }); refresh(p, true);
  });

  // ---------------------------------------------------------------- 成果库

  function outcomes(ctx, p) {
    const vs = st(p).vers.slice().reverse(), concl = O.verifiers(p.composed).length > 0, open = Number(Y18.state.route.query.v);
    const cols = '<div class="ln-vrow is-head' + (concl ? ' has-concl' : '') + '"><span>第几版</span><span>事项</span><span>时间</span><span>一句话</span>' + (concl ? '<span>结论</span>' : '') + '</div>';
    return '<div class="ln-vers"><h1>成果库</h1><p class="y18-muted">每一版一行，点开看差异。</p>' + (vs.length ? cols : '') + (vs.map((v) => {
      const it = H.item(p, v.item);
      return '<details class="ln-ver"' + (v.n === open ? ' open' : '') + '><summary class="ln-vrow' + (concl ? ' has-concl' : '') + '"><span>第 ' + v.n + ' 版</span><span>' + esc(it ? it.title : '') + '</span><span>' + esc(ui.time(v.at)) + '</span><span>' + esc(v.text) + '</span>' + (concl ? '<span>' + esc(v.concl) + '</span>' : '') + '</summary>' +
        '<div class="ln-diff"><b>改了的文件</b><ul>' + v.files.map((f) => '<li>' + esc(f) + '</li>').join('') + '</ul>' + ui.pre(v.diff.join('\n')) + '</div></details>';
    }).join('') || ui.empty('还没有成果。')) + '</div>';
  }

  // ---------------------------------------------------------------- 设置

  function settings(ctx, p) {
    const s = st(p), vn = vname(p), models = O.modelChoices();
    const goal = p.goal && p.goal.indexOf('（还没有') !== 0 ? p.goal : '';
    const row = (k, v) => '<div class="ln-set"><label>' + k + '</label><div>' + v + '</div></div>';
    return '<div class="ln-settings"><h1>设置</h1>' + (s.note ? '<div class="y18-note is-info" id="ln-note">' + esc(s.note) + '</div>' : '') +
      row('名字', '<input type="text" class="y18-input" id="ln-set-name" value="' + esc(p.name) + '" data-act="ln.name">') +
      row('长期目标（可选）', '<textarea class="y18-textarea" rows="2" data-act="ln.goal" placeholder="这个项目长期要做成什么样，可以不写">' + esc(goal) + '</textarea>') +
      row('起始文件夹', '<input type="text" class="y18-input" data-act="ln.dir" value="' + esc(p.dir || '') + '" placeholder="控制主机上的路径，可以不填">') +
      row('模型', '<select class="y18-select" data-act="ln.model"><option value="">跟随全局</option>' + models.map((m) => '<option' + (s.model === m ? ' selected' : '') + '>' + esc(m) + '</option>').join('') + '</select>') +
      row('组织', '<span id="ln-org">' + (vn ? '一个人做，' + esc(vn) + '核验' : '一个人做，没有人核验') + '</span> <button type="button" class="y18-btn small" data-act="ln.verifier">' + (vn ? '去掉核验角色' : '加一个核验角色') + '</button> <button type="button" class="y18-btn small" data-act="ln.swap">换模板</button>') +
      '<details class="ln-adv"><summary>高级</summary><p>改名、加部门、编辑定义、成果写回、机器授权、执行位置、MCP 服务器都在这里。</p>' +
      '<button type="button" class="y18-link" data-act="ln.adv" data-to="#/p/' + p.id + '/org">组织页</button> · <button type="button" class="y18-link" data-act="ln.adv" data-to="#/p/' + p.id + '/settings">完整的设置页</button></details></div>';
  }
  A('ln.name', (el) => { const p = H.project(H.pid()); if (el.value.trim()) { p.name = el.value.trim(); Y18.rerender(); } });
  A('ln.goal', (el) => { H.project(H.pid()).goal = el.value.trim(); });
  A('ln.dir', (el) => { H.project(H.pid()).dir = el.value.trim(); });
  A('ln.model', (el) => { st(H.project(H.pid())).model = el.value; });
  A('ln.adv', (el) => { Y18.setAdv(H.pid()); Y18.go(el.dataset.to); });

  // 加 / 去掉核验角色：改合成结果，写一条历史；只对之后新建的事项生效
  A('ln.verifier', () => {
    const p = H.project(H.pid()), ch = clone(p.org.changes), has = Boolean(vname(p));
    if (has) O.removeDept(ch, p.org.form, [], 'quality');
    else { const d = O.publishedDept(p.composed, 'quality'); ch.depts = ch.depts || {}; ch.depts.quality = { added: true, name: d.name, goal: d.goal, judge: d.judge, how: d.how, watches: d.watches, produces: d.produces, tools: d.tools, write: d.write, who: { type: 'own' }, verifies: d.verifies, completes: false }; }
    const res = O.adopt(p, { base: p.version, form: p.org.form, changes: ch, pending: {}, reason: has ? '去掉核验角色' : '加一个核验角色：' + d0(p) + '核验' + eng(p) + '交的完成' });
    if (!res.ok) { ui.toast(res.error + (res.rejects ? '：' + res.rejects.map((x) => x.text).join('；') : ''), 'warn'); return; }
    st(p).note = has ? '已去掉核验角色。在跑的事项按原来的做完，之后新建的事项做完就以开环完成结束' : '在跑的事项按原来的做完，之后新建的事项等' + vname(p) + '放行才结束';
    Y18.rerender();
  });
  const d0 = () => O.releaseDeptName('quality');

  // 换模板：点卡一步生效；有改动时确认一次
  A('ln.swap', () => ui.modal({ title: '换模板', wide: true, body: '<div class="ln-cards">' + cards('ln.pick') + '</div>', actions: [{ label: '取消', close: true }] }));
  A('ln.pick', (el) => {
    const p = H.project(H.pid()), id = el.dataset.form;
    if (O.count(p.org.changes) && !el.dataset.sure) {
      const lost = O.diff(O.compose({ form: p.org.form, changes: {} }), p.composed);
      ui.modal({ title: '换成「' + O.formName(id) + '」？', body: '<p>现在的改动会丢掉：</p><ul class="y18-org-diff">' + lost.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul><p class="y18-small y18-muted">记录里还在，改回能找回。</p>', actions: [{ label: '换', kind: 'primary', act: 'ln.pick', data: { form: id, sure: '1' } }, { label: '取消', close: true }] });
      return;
    }
    const res = O.adopt(p, { base: p.version, form: id, changes: {}, pending: {}, reason: '换模板：' + O.formName(id) });
    ui.closeModal();
    if (!res.ok) { ui.toast(res.error, 'warn'); return; }
    st(p).note = '';
    Y18.go('#/p/' + p.id);
    Y18.rerender();
  });

  // ---------------------------------------------------------------- 外壳：标签

  Y18.leanTabs = (p, r) => {
    const b = (name, label, tail) => '<button type="button" class="y18-ptab' + (r.name === name ? ' is-active' : '') + '" data-go="#/p/' + p.id + tail + '">' + label + '</button>';
    return '<div class="y18-pheader"><button type="button" class="y18-pname" data-go="#/p/' + p.id + '">' + esc(p.name) + '</button>' + ui.tag('新增', 'new') + '</div><div class="y18-ptabs" role="navigation" aria-label="项目页面">' + b('overview', '对话', '') + b('outcomes', '成果库', '/outcomes') + b('settings', '设置', '/settings') + '</div>';
  };
  Y18.leanViews.overview = { render: conversation, mount: convMount };
  Y18.leanViews.outcomes = { render: outcomes };
  Y18.leanViews.settings = { render: settings };

  // ---------------------------------------------------------------- 新建项目、接入已有项目：名字加一张模板卡

  function dialog(attach) {
    const px = attach ? 'pa' : 'pn';
    const projects = Y18.W().projects.map((p) => '<option value="' + p.id + '">' + esc(p.name) + '</option>').join('');
    const body = '<div class="ln-new" data-np="' + px + '"><input type="text" class="y18-input" id="ln-name" aria-label="项目名字" placeholder="项目名字" data-live data-act="ln.clear">' +
      '<div class="ln-warn" id="ln-warn"></div>' +
      (attach ? '<input type="text" class="y18-input" id="ln-dir" placeholder="源目录：控制主机上已有项目的绝对路径" data-live data-act="ln.clear">' : '') +
      '<p class="y18-muted y18-small">点一张模板卡，项目就建好了。</p><div class="ln-cards">' + cards('ln.create') + '</div>' +
      '<input type="radio" name="' + px + '-org" id="' + px + '-radio" value="three" checked hidden><input type="checkbox" id="' + px + '-obs" hidden><input type="checkbox" id="' + px + '-sub" hidden>' +
      '<div class="ln-more">' + (attach ? '' : '<button type="button" class="y18-link" data-act="ln.toggle" data-t="ln-dirbox">选起始文件夹</button> ') + '<button type="button" class="y18-link" data-act="ln.toggle" data-t="ln-advbox">高级</button></div>' +
      '<div id="ln-dirbox" hidden><input type="text" class="y18-input" id="pn-dir" placeholder="控制主机上的路径，可以不填"></div>' +
      '<div id="ln-advbox" class="ln-advbox" hidden><label class="y18-field"><span>和某项目一样</span><select class="y18-select" id="' + px + '-same"><option value="">不用</option>' + projects + '</select><small class="y18-muted">选了以后，点任意一张卡都按那个项目的组织建。</small></label>' +
      '<label class="y18-check"><input type="checkbox" data-act="ln.layer" data-id="' + px + '-obs"><span>加观察者</span></label><label class="y18-check"><input type="checkbox" data-act="ln.layer" data-id="' + px + '-sub"><span>工程内部用子组织（中心型小组）</span></label></div></div>';
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
    const spec = { name, goal: '', dir, org: Y18.np.pickedOrg(px) };
    if (px === 'pa') { Y18.np.attachDo(spec); return; }
    const p = Y18.np.createProject(spec);
    ui.closeModal();
    Y18.go('#/p/' + p.id);
  });
  const attach_dir = (px) => (px === 'pa' ? $('ln-dir').value.trim() : $('pn-dir').value.trim());
})();
