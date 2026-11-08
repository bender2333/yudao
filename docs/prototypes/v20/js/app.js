// 外壳与路由：左侧栏、顶栏、项目标签、桌面会话条、版本不一致的整窗提示、场景菜单、点击委托
(function () {
  'use strict';
  const Y20 = window.Y20;
  const esc = Y20.esc;

  Y20.SYS = [{ id: 'models', label: '模型管理', icon: 'models' }, { id: 'machines', label: '机器', icon: 'machines' }, { id: 'runtime', label: '运行与执行槽位', icon: 'runtime' }, { id: 'tools', label: '工具与扩展', icon: 'tools' }];
  Y20.RESERVED = [{ id: 'meta', label: '元观察', stage: '阶段六', icon: 'meta' }, { id: 'evolution', label: '演化', stage: '阶段六', icon: 'evolution' }, { id: 'lessons', label: '经验', stage: '持续改进', icon: 'lessons' }];
  const S = { world: null, scenario: Y20.store.get('scenario', 'normal'), route: null, mismatchDir: 'page_old', drawer: false, search: '' };
  const views = {};
  const actions = {};
  Y20.views = { register: (name, v) => { views[name] = v; } };
  Y20.actions = { register: (name, fn) => { actions[name] = fn; } };
  Y20.W = () => S.world;
  // 项目一直使用同一套导航；高级配置只影响当前页的内容。
  Y20.leanViews = {};
  Y20.isLean = (p) => Boolean(p);
  Y20.state = S;

  // ---------------------------------------------------------------- 取数辅助

  const H = Y20.h = {};
  H.project = (id) => S.world.projects.find((p) => p.id === id) || null;
  H.item = (p, id) => p.items.find((i) => i.id === id) || null;
  // 职能显示名按项目的组织取：先看现在的组织，再看还在跑的事项冻结的。不给项目就用当前页面所在的项目
  H.ctxOverride = null;
  H.ctxId = () => H.ctxOverride || (S.route && S.route.params.project) || null;
  H.in = (p, fn) => { const prev = H.ctxOverride; H.ctxOverride = p ? (p.id || p) : null; try { return fn(); } finally { H.ctxOverride = prev; } };
  H.dept = (id, p) => {
    const pr = p ? (typeof p === 'string' ? H.project(p) : p) : (H.ctxId() ? H.project(H.ctxId()) : null);
    return Y20.org.deptName(pr, id);
  };
  H.t = (p, text) => H.in(p, () => Y20.esc(text));
  H.event = (k) => (typeof k === 'number' || /^\d+$/.test(String(k)) ? S.world.events.find((e) => e.pos === Number(k)) : S.world.byKey[k]) || null;
  H.decisions = (pid) => S.world.decisions.filter((d) => !pid || d.project === pid);
  H.dot = (item) => '<span class="y20-dot-color" style="--c:' + Y20.ITEM_COLORS[item.color % 6] + '"></span>';
  H.itemTag = (item) => H.dot(item) + ' <span class="y20-door">' + esc(item.door) + '</span> ' + esc(item.title);
  H.status = (item) => { const s = Y20.ITEM_STATUS[item.status]; return Y20.ui.status(s[1], s[0]); };
  H.dur = (sec) => Y20.ui.duration(sec);
  H.waited = (iso) => H.dur(Y20.ui.since(iso));
  H.link = (go, text) => '<button type="button" class="y20-link" data-go="' + esc(go) + '">' + esc(text) + '</button>';
  H.pid = () => (S.route && S.route.params.project) || null;
  // 来源：事实旁边的来源种类，点开按位置看那条事件
  H.src = (k) => {
    const e = H.event(k);
    if (!e) return '';
    return '<button type="button" class="y20-source-kind is-' + e.source + '" data-go="#/event/' + e.pos + '" title="来源：' + esc(Y20.SOURCE_KINDS[e.source][0]) + '，点开看这条事件">' + esc(Y20.SOURCE_KINDS[e.source][0]) + '</button>';
  };
  H.waitingProviderCount = () => S.world.projects.reduce((n, p) => n + p.provider_wait.length, 0);

  // ---------------------------------------------------------------- 路由

  function parse(hash) {
    const text = (hash || '').replace(/^#/, '');
    const qi = text.indexOf('?');
    const query = Object.fromEntries(new URLSearchParams(qi >= 0 ? text.slice(qi + 1) : ''));
    const seg = (qi >= 0 ? text.slice(0, qi) : text).split('/').filter(Boolean);
    const r = { name: 'not-found', params: {}, query, hash: '#' + text };
    if (!seg.length || seg[0] === 'home') r.name = 'home';
    else if (seg[0] === 'event' && seg[1]) { r.name = 'event'; r.params = { pos: seg[1] }; }
    else if (seg[0] === 'sys' && Y20.SYS.some((x) => x.id === seg[1])) r.name = 'sys-' + seg[1];
    else if (seg[0] === 'sys' && Y20.RESERVED.some((x) => x.id === seg[1])) { r.name = 'reserved'; r.params = { which: seg[1] }; }
    else if (seg[0] === 'p' && seg[1]) {
      r.params = { project: seg[1] };
      if (seg.length === 2) r.name = 'overview';
      else if (seg[2] === 'w' && seg[3] && seg[4] === 'recovery') { r.name = 'recovery'; r.params.item = seg[3]; }
      else if (seg[2] === 'w' && seg[3] && seg[4] === 'org') { r.name = 'item-org'; r.params.item = seg[3]; }
      else if (seg[2] === 'w' && seg[3]) { r.name = 'item'; r.params.item = seg[3]; }
      else if (seg[2] === 'org') {
        // 组织页：/org，/org/d/<职能>，/org/s/<路径>（子组织，路径是职能身份用点连起来），/org/s/<路径>/d/<角色>，/org/new，/org/s/<路径>/new
        r.name = 'org'; r.params.path = '';
        let i = 3;
        if (seg[i] === 's' && seg[i + 1]) { r.name = 'org-sub'; r.params.path = seg[i + 1]; i += 2; }
        if (seg[i] === 'd' && seg[i + 1]) { r.name = 'org-dept'; r.params.dept = seg[i + 1]; }
        else if (seg[i] === 'new') r.name = 'org-new';
      }
      else if (seg[2] === 'observe' && seg[3]) { r.name = 'observe-detail'; r.params.attempt = seg[3]; }
      else if (seg[2] === 'dept' && seg[3]) { r.name = 'dept'; r.params.dept = seg[3]; }
      else if (['outcomes', 'flow', 'timeline', 'materials', 'observe', 'settings'].includes(seg[2])) r.name = seg[2];    }
    return r;
  }

  Y20.go = function go(hash) {
    S.drawer = false;
    if (location.hash === hash) handle(); else location.hash = hash;
  };

  const dom = {};
  let mounted = null;

  function handle() {
    const route = parse(location.hash);
    if (S.adv && S.adv !== route.params.project) S.adv = null;
    if (S.route && S.route.hash === route.hash) { S.route = route; render(true); return; }
    S.route = route;
    if (!/^#\/(sys|connect)/.test(route.hash)) S.back = route.hash;
    render(false);
  }

  function render(keepScroll) {
    const y = window.scrollY;
    if (mounted && mounted.unmount) mounted.unmount();
    mounted = null;
    H.ctxOverride = null;
    const rp = S.route.params.project ? H.project(S.route.params.project) : null;
    if (Y20.isLean(rp) && !Y20.leanHas(rp, S.route.name)) { history.replaceState(null, '', '#/p/' + rp.id); S.route = parse(location.hash); }
    renderShell();
    if (S.world.versions.server !== S.world.versions.page) { dom.content.innerHTML = ''; return; }
    const ctx = { route: S.route, world: S.world };
    const p = S.route.params.project ? H.project(S.route.params.project) : null;
    const advanced = S.route.query.advanced === '1' || S.route.query.view === 'doc';
    const view = (!advanced && Y20.isLean(p) && Y20.leanViews[S.route.name]) || views[S.route.name];
    if (S.route.params.project && !p) dom.content.innerHTML = gate('找不到项目', '当前场景里没有项目「' + esc(S.route.params.project) + '」。');
    else if (S.route.name === 'not-found' || !view) dom.content.innerHTML = gate('找不到这个页面', '路径「' + esc(S.route.hash) + '」不对应任何页面。');
    else {
      dom.content.dataset.view = S.route.name;
      dom.content.innerHTML = view.render(ctx, p);
      if (view.mount) view.mount(ctx, dom.content, p);
      mounted = view;
    }
    if (advanced && p) dom.content.insertAdjacentHTML('afterbegin', '<div class="ws-advanced-return"><span>高级配置</span><button type="button" class="y20-link" data-act="ws.return">返回原页面</button><small>组织改动影响之后新建的事项；模型与 Prompt 影响下一次模型请求。</small></div>');
    window.scrollTo(0, keepScroll ? y : 0);
    const hit = dom.content.querySelector('.is-target');
    if (hit && hit.scrollIntoView) hit.scrollIntoView({ block: 'center' });
  }
  Y20.rerender = () => render(true);

  function gate(title, text) {
    return '<div class="y20-gate"><h1>' + esc(title) + '</h1><p class="y20-muted">' + text + '</p><div class="y20-row"><button class="y20-btn" data-go="#/home">回到首页</button></div></div>';
  }

  // ---------------------------------------------------------------- 外壳

  function statusItems() {
    const n = S.world.decisions.length;
    const m = H.waitingProviderCount();
    return [
      { id: 'decisions', label: '待你决定', icon: 'decide', n, lit: n > 0, go: '#/home', anchor: 'home-decisions' },
      { id: 'waiting_provider', label: '等待模型服务', icon: 'waiting_provider', n: m, lit: m > 0, go: '#/p/shop' }
    ];
  }
  function statItem(it, compact) {
    const attrs = it.lit ? ' data-act="status" data-to="' + esc(it.go) + '" data-anchor="' + esc(it.anchor || '') + '"' : ' disabled';
    return '<button type="button" class="y20-stat is-' + it.id + (it.lit ? ' is-lit' : '') + (compact ? ' is-compact' : '') + '"' + attrs + '>' +
      Y20.ui.icon(it.icon, 'y20-icon y20-stat-icon') + '<span class="y20-stat-label">' + esc(it.label) + '</span><span class="y20-stat-value">' + (it.lit ? it.n : '无') + '</span></button>';
  }
  Y20.statItem = statItem;
  Y20.statusItems = statusItems;

  function marker(p) {
    const waiting = p.items.some((i) => i.status === 'waiting_user' || i.status === 'waiting_resume');
    if (waiting) return Y20.ui.status('pending', '等你决定');
    if (p.items.some((i) => i.status === 'waiting_model')) return Y20.ui.status('waiting_provider', '等待模型服务');
    if (p.items.some((i) => i.status === 'working')) return Y20.ui.status('running', '进行中');
    return Y20.ui.status('idle', '空闲');
  }
  Y20.marker = marker;

  function sideBottom() {
    const r = S.route;
    const sys = Y20.SYS.map((l) => '<li><button type="button" class="y20-side-link' + (r.name === 'sys-' + l.id ? ' is-active' : '') + '" data-go="#/sys/' + l.id + '">' + Y20.ui.icon(l.icon) + '<span>' + l.label + '</span></button></li>').join('');
    const res = Y20.RESERVED.map((l) => '<li><button type="button" class="y20-side-link is-reserved' + (r.name === 'reserved' && r.params.which === l.id ? ' is-active' : '') + '" data-go="#/sys/' + l.id + '" title="预留入口：' + l.stage + '">' + Y20.ui.icon(l.icon) + '<span>' + l.label + '</span><span class="y20-side-stage">' + l.stage + '</span></button></li>').join('');
    return '<div class="y20-side-bottom"><div class="y20-side-label"><span>系统</span></div><ul class="y20-side-links">' + sys + '</ul><div class="y20-side-label is-sub"><span>预留入口</span></div><ul class="y20-side-links">' + res + '</ul></div>';
  }

  function sidebar() {
    const r = S.route;
    const list = S.world.projects.map((p) => {
      const sel = r.params.project === p.id;
      // 待你决定的数量：从两个职能起显示
      const dn = p.composed.depts.length >= 2 ? Y20.leanDecisions(p) : 0;
      const hidden = S.search && !p.name.includes(S.search) ? ' hidden' : '';
      return '<li' + hidden + '><button type="button" class="y20-project' + (sel ? ' is-selected' : '') + '" data-go="#/p/' + p.id + '"><span class="y20-project-name">' + esc(p.name) +
        (dn ? '<span class="y20-count is-decide" title="待你决定，点了跳到那条" data-act="ln.jump" data-p="' + p.id + '">' + dn + '</span>' : '') + '</span><span class="y20-project-marker">' + marker(p) + '</span></button></li>';
    }).join('');
    return '<div class="y20-side-top"><div class="y20-brand">' + Y20.ui.icon('brand', 'y20-icon y20-brand-icon') + '<span class="y20-brand-name">Yudao<small>枢道</small></span><span class="y20-proto-chip">v20 页面原型</span>' +
      '<button type="button" class="y20-icon-btn y20-drawer-close" data-act="drawer" aria-label="收起左侧栏">' + Y20.ui.icon('close') + '</button></div>' +
      '<button type="button" class="y20-side-link y20-home-link' + (r.name === 'home' ? ' is-active' : '') + '" data-go="#/home">' + Y20.ui.icon('home') + '<span>首页</span></button>' +
      '<div class="y20-side-new"><button type="button" class="y20-btn small primary" data-act="np.new">' + Y20.ui.icon('plus') + '<span>新建项目</span></button><button type="button" class="y20-btn small" data-act="np.attach">' + Y20.ui.icon('import') + '<span>接入已有项目</span></button></div>' +
      '<label class="y20-search">' + Y20.ui.icon('search') + '<input type="search" placeholder="搜索项目" value="' + esc(S.search) + '" data-act="search" aria-label="搜索项目"></label>' +
      '<div class="y20-side-label"><span>项目</span><span class="y20-count">' + S.world.projects.length + '</span></div><ul class="y20-project-list">' + list + '</ul></div>' + sideBottom();
  }

  const TITLES = { home: '首页', overview: '项目', item: '事项', outcomes: '成果库', flow: '流转', timeline: '时间轴', event: '按位置看一条事件', materials: '资料', observe: '观测', 'observe-detail': '请求详情', settings: '设置', recovery: '恢复与动作核实', org: '组织' };
  const sysTitle = (r) => (r.name === 'reserved' ? Y20.RESERVED.find((x) => x.id === r.params.which).label : (Y20.SYS.find((x) => 'sys-' + x.id === r.name) || {}).label);

  function topbar() {
    const r = S.route;
    const p = r.params.project ? H.project(r.params.project) : null;
    const crumbs = ['<button type="button" class="y20-crumb" data-go="#/home">首页</button>'];
    if (sysTitle(r)) { crumbs.length = 0; crumbs.push('<strong>' + sysTitle(r) + '</strong>', '<span class="y20-crumb-note">系统</span>'); }
    else if (p) {
      crumbs.push('<button type="button" class="y20-crumb" data-go="#/p/' + p.id + '">' + esc(p.name) + '</button>');
      if (r.name === 'item') { const it = H.item(p, r.params.item); if (it) crumbs.push('<strong>' + esc(it.title) + '</strong>'); }
      else if (r.name === 'recovery') { const it = H.item(p, r.params.item); if (it) crumbs.push('<button type="button" class="y20-crumb" data-go="#/p/' + p.id + '/w/' + it.id + '">' + esc(it.title) + '</button>'); crumbs.push('<strong>' + TITLES.recovery + '</strong>'); }
      else if (r.name === 'observe-detail') crumbs.push('<button type="button" class="y20-crumb" data-go="#/p/' + p.id + '/observe">观测</button>', '<strong>' + TITLES['observe-detail'] + '</strong>');
      else if (r.name === 'dept') crumbs.push('<strong>' + esc(H.dept(r.params.dept)) + '职能</strong>');
      else if (/^org/.test(r.name) || r.name === 'item-org') Y20.orgpage.crumbs(r, p).forEach((c) => crumbs.push(c));
      else if (r.name !== 'overview') crumbs.push('<strong>' + TITLES[r.name] + '</strong>');
    } else if (r.name === 'event') {
      const e = H.event(r.params.pos);
      if (e && e.project) { const ep = H.project(e.project); if (ep) crumbs.splice(1, 0, '<button type="button" class="y20-crumb" data-go="#/p/' + ep.id + '">' + esc(ep.name) + '</button>'); }
      crumbs.push('<strong>按位置看一条事件</strong>');
    } else if (r.name !== 'home' && !sysTitle(r)) crumbs.push('<strong>' + (TITLES[r.name] || '') + '</strong>');
    else if (!sysTitle(r)) crumbs.pop(), crumbs.push('<strong>首页</strong>');
    const lean = Y20.isLean(p);
    const stats = lean ? '' : statusItems().filter((i) => i.lit).map((i) => statItem(i, true)).join('');
    return desktopStrip() + '<button type="button" class="y20-icon-btn y20-drawer-open" data-act="drawer" aria-label="打开左侧栏">' + Y20.ui.icon('menu') + '</button>' +
      '<nav class="y20-crumbs" aria-label="路径">' + crumbs.join('<span class="y20-crumb-sep">/</span>') + '</nav>' +
      '<div class="y20-top-actions">' + (stats ? '<div class="y20-top-stats">' + stats + '</div>' : '') +
      (lean ? '' : '<span class="y20-service"><span class="y20-dot"></span>已连接 · 接口版本 第 ' + S.world.versions.server + ' 版</span>') + '</div>';
  }

  function tabs() {
    const r = S.route;
    const p = r.params.project ? H.project(r.params.project) : null;
    if (!p) return '';
    if (Y20.isLean(p)) return Y20.leanTabs(p, r);
    const sum = Y20.org.summary(p);
    const many = p.depts.length > 4; // 职能多到标签放不下，收进一个「职能」下拉
    const deptName = (d) => esc(H.dept(d, p)) + (p.onlyOld.includes(d) ? '（只在旧组织里）' : '');
    const onDept = r.name === 'dept';
    const head = [{ go: '#/p/' + p.id, label: '概览', on: r.name === 'overview' || r.name === 'item' || r.name === 'recovery' || r.name === 'item-org' }];
    const deptTabs = many ? [] : p.depts.map((d) => ({ go: '#/p/' + p.id + '/dept/' + d, label: deptName(d), on: onDept && r.params.dept === d }));
    const tail = [{ go: '#/p/' + p.id + '/outcomes', label: '成果库', on: r.name === 'outcomes' }]
      .concat(sum.multi ? [{ go: '#/p/' + p.id + '/flow', label: '流转', on: r.name === 'flow' }] : [])
      .concat([{ go: '#/p/' + p.id + '/timeline', label: '时间轴', on: r.name === 'timeline' }, { go: '#/p/' + p.id + '/materials', label: '资料', on: r.name === 'materials' },
        { go: '#/p/' + p.id + '/observe', label: '观测', on: r.name === 'observe' || r.name === 'observe-detail' },
        { go: '#/p/' + p.id + '/org', label: '组织', on: /^org/.test(r.name), tag: true }, { go: '#/p/' + p.id + '/settings', label: '设置', on: r.name === 'settings' }]);
    const btn = (x) => '<button type="button" class="y20-ptab' + (x.on ? ' is-active' : '') + '" data-go="' + x.go + '">' + x.label + '</button>';
    const dropdown = many ? '<select class="y20-ptab-select' + (onDept ? ' is-active' : '') + '" data-act="dept-jump" aria-label="职能"><option value="">职能</option>' +
      p.depts.map((d) => '<option value="' + esc(d) + '"' + (onDept && r.params.dept === d ? ' selected' : '') + '>' + deptName(d) + '</option>').join('') + '</select>' : '';
    const tags = Y20.org.tags(p).map((t) => '<span class="y20-ptag">' + esc(t) + '</span>').join('');
    return '<div class="y20-pheader"><button type="button" class="y20-pname" data-go="#/p/' + p.id + '">' + esc(p.name) + '</button><span class="y20-ptags">' + tags + '</span></div>' +
      '<div class="y20-ptabs" role="navigation" aria-label="项目页面">' + head.map(btn).join('') + deptTabs.map(btn).join('') + dropdown + tail.map(btn).join('') + '</div>';
  }

  // 桌面会话进行期间每一页顶部都有（这一条属于外壳，不属于某个页面）
  function desktopStrip() {
    const d = S.world.desktop;
    if (!d) return '';
    const p = H.project(d.project);
    const it = p && H.item(p, d.item);
    return '<div class="y20-desktop" role="alert">' + Y20.ui.icon('lock') + '<span><strong>' + esc(H.dept(d.dept, d.project)) + '正在使用桌面</strong> · ' + esc(d.what) + (p ? '（' + esc(p.name) + (it ? ' · ' + esc(it.title) : '') + '）' : '') +
      ' · 已用 ' + esc(H.waited(d.since)) + '</span><button type="button" class="y20-btn small danger" data-act="stop-desktop">停止使用</button></div>';
  }

  function versionCard() {
    const v = S.world.versions;
    const newer = S.mismatchDir === 'page_old';
    const head = newer ? '<h1>页面文件比服务旧</h1>' : '<h1>服务比页面旧</h1>';
    const a = newer ? v.server : v.page, b = newer ? v.page : v.server;
    const step = newer ? '页面已经自动重新加载过一次，服务提供的页面文件仍然较旧，说明页面文件没有跟着更新。下一步：重新构建页面文件，再刷新这一页。'
      : '服务还在运行旧的代码。下一步：重启 Yudao 服务，页面会自动重新连接。';
    return '<div class="y20-update-card">' + head + '<p>服务的接口版本是第 <b>' + (newer ? a : b) + '</b> 版，这个页面是第 <b>' + (newer ? b : a) + '</b> 版。两边一致之前不打开任何页面，也不执行命令。</p><p>' + step + '</p>' +
      '<p class="y20-muted y20-small">原型：<button type="button" class="y20-link" data-act="flip-mismatch">看另一个方向的提示</button>；右下角场景菜单选「正常运行」回到正常。</p></div>';
  }

  function renderShell() {
    const mismatch = S.world.versions.server !== S.world.versions.page;
    document.body.classList.toggle('is-version-mismatch', mismatch);
    dom.note.hidden = !mismatch;
    dom.note.className = mismatch ? 'y20-window-note is-version' : 'y20-window-note';
    dom.note.innerHTML = mismatch ? versionCard() : '';
    if (mismatch) return;
    dom.sidebar.innerHTML = sidebar();
    dom.topbar.innerHTML = topbar();
    const t = tabs();
    dom.tabs.innerHTML = t;
    dom.tabs.hidden = !t;
    document.body.classList.toggle('is-drawer-open', S.drawer);
    const n = S.world.decisions.length;
    document.title = (n ? '(' + n + ') ' : '') + 'Yudao v20 页面原型';
  }

  function toolbar() {
    dom.toolbar.className = 'y20-toolbar is-open';
    dom.toolbar.innerHTML = '<div class="y20-tb-bar"><span class="y20-tb-brand">场景</span>' +
      '<select class="y20-tb-select is-scenario" data-act="scenario" aria-label="场景">' + Y20.SCENARIOS.map((s) => '<option value="' + s.id + '"' + (s.id === S.scenario ? ' selected' : '') + '>' + esc(s.label) + '</option>').join('') + '</select>' +
      '<span class="y20-tb-sep"></span><select class="y20-tb-select is-theme" data-act="theme" aria-label="主题"><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select></div>';
    dom.toolbar.querySelector('[data-act=theme]').value = Y20.store.get('theme', 'system', true);
    document.documentElement.style.setProperty('--tb-space', '70px');
  }

  // ---------------------------------------------------------------- 动作

  function setScenario(id, navigate) {
    S.scenario = id;
    Y20.store.set('scenario', id);
    S.world = Y20.buildWorld(id);
    toolbar();
    const sc = Y20.SCENARIOS.find((s) => s.id === id);
    if (navigate && sc) { if (location.hash === sc.go) handle(); else location.hash = sc.go; } else handle();
  }

  Y20.actions.register('scenario', (el) => setScenario(el.value, true));
  Y20.actions.register('theme', (el) => {
    Y20.store.set('theme', el.value, true);
    if (el.value === 'system') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = el.value;
  });
  Y20.actions.register('drawer', () => { S.drawer = !S.drawer; document.body.classList.toggle('is-drawer-open', S.drawer); });
  Y20.actions.register('search', (el) => {
    S.search = el.value.trim();
    document.querySelectorAll('.y20-project-list li').forEach((li, i) => { li.hidden = Boolean(S.search) && !S.world.projects[i].name.includes(S.search); });
  });
  Y20.actions.register('dept-jump', (el) => { if (el.value) Y20.go('#/p/' + S.route.params.project + '/dept/' + el.value); });
  Y20.actions.register('flip-mismatch', () => { S.mismatchDir = S.mismatchDir === 'page_old' ? 'service_old' : 'page_old'; renderShell(); });
  Y20.actions.register('stop-desktop', () => {
    const d = S.world.desktop;
    S.world.desktop = null;
    const p = d && H.project(d.project);
    if (p) { p.deptState.quality.text = '核验订单列表分页（交付第 2 版）'; p.deptState.quality.reason = '一轮工作进行中，第 4 轮'; }
    Y20.ui.toast('已停止使用桌面，桌面交还给你。' + (d ? H.dept(d.dept, d.project) : '') + '这一轮的试用到此为止。', 'ok');
    render(true);
  });
  Y20.actions.register('status', (el) => {
    const to = el.dataset.to;
    const anchor = el.dataset.anchor;
    Y20.go(to);
    if (anchor) setTimeout(() => { const t = document.getElementById(anchor); if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 30);
  });

  document.addEventListener('click', (ev) => {
    if (ev.target.matches('[data-modal-backdrop]')) { Y20.ui.closeModal(); return; }
    const el = ev.target.closest('[data-go],[data-act],[data-tab],[data-close-modal]');
    if (!el || el.disabled || el.matches('select, input, textarea')) return;
    if (el.dataset.tab && el.dataset.tabGroup) { Y20.ui.selectTab(el.dataset.tabGroup, el.dataset.tab); return; }
    if (el.dataset.go) { ev.preventDefault(); Y20.go(el.dataset.go); }
    if (el.dataset.act) actions[el.dataset.act](el, ev);
    if (el.hasAttribute('data-close-modal')) Y20.ui.closeModal();
  });
  document.addEventListener('change', (ev) => { const el = ev.target; if (el.matches('select, input[type=checkbox], input[type=radio], textarea, input[type=text]') && el.dataset.act && !el.hasAttribute('data-live')) actions[el.dataset.act](el, ev); });
  document.addEventListener('input', (ev) => { const el = ev.target; if (el.matches('input[type=search], [data-live]') && el.dataset.act) actions[el.dataset.act](el, ev); });
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') Y20.ui.closeModal(); });

  Y20.app = {
    now: () => S.world.now,
    renderContent: () => render(true),
    restoreDrafts() {},
    start() {
      ['sidebar', 'topbar', 'tabs', 'content', 'toolbar', 'modal-root', 'toast-root', 'window-note'].forEach((id) => { dom[id.replace('-root', '').replace('window-', '')] = document.getElementById('y20-' + id); });
      const theme = Y20.store.get('theme', 'system', true);
      if (theme !== 'system') document.documentElement.dataset.theme = theme;
      Y20.org.draft.prune(['orders', 'shop', 'logclean', 'blog', 'dash', 'signup', 'firmware', 'pool-demo', 'ops-demo']);
      S.world = Y20.buildWorld(S.scenario);
      toolbar();
      window.addEventListener('hashchange', handle);
      if (!location.hash) history.replaceState(null, '', '#/home');
      handle();
    }
  };
})();
