// 外壳：左侧栏、顶栏（路径、事项选择框、亮起的状态项、连接状态、项目菜单）、项目标签、状态项、托盘与系统通知、
// 连接断开与接口版本不同时的整窗提示（设计说明第 3、4.1、10 节）
(function () {
  'use strict';
  const Y12 = window.Y12;
  const esc = Y12.esc;

  let searchText = '';
  let menuOpen = false;
  let disconnectedAt = null;
  let lastSidebar = '';

  const SYSTEM_LINKS = [
    { id: 'models', label: '模型管理', icon: 'models', route: 'sys-models', query: 'catalog' },
    { id: 'machines', label: '机器', icon: 'machines', route: 'sys-machines', query: 'machines.list' },
    { id: 'runtime', label: '运行与执行槽位', icon: 'runtime', route: 'sys-runtime', query: 'runtime.slots' },
    { id: 'tools', label: '工具与扩展', icon: 'tools', route: 'sys-tools', query: 'tools.registry' }
  ];

  const RESERVED_LINKS = [
    { id: 'meta', label: '元观察', icon: 'meta', stage: 'Stage 6' },
    { id: 'evolution', label: '演化', icon: 'evolution', stage: 'Stage 6' },
    { id: 'lessons', label: '经验', icon: 'lessons', stage: '持续改进' }
  ];

  const PAGE_TITLES = {
    home: '首页', overview: '概览', dept: '部门工作间', recovery: '恢复与动作核实', materials: '资料', observe: '观测',
    'observe-detail': '请求详情', settings: '设置', 'sys-models': '模型管理', 'sys-machines': '机器', 'sys-runtime': '运行与执行槽位',
    'sys-tools': '工具与扩展', 'sys-reserved': '预留入口', connect: '连接设置', gallery: '动作图鉴（原型专用）', 'not-found': '找不到页面'
  };
  const DEPT_LABELS = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };

  const isSystemRoute = (name) => typeof name === 'string' && (name.startsWith('sys-') || name === 'connect' || name === 'gallery');

  function pageTitle(ctx) {
    const view = Y12.views.get(ctx.route.name);
    if (ctx.route.name === 'dept' && DEPT_LABELS[ctx.route.params.department]) return DEPT_LABELS[ctx.route.params.department] + '部门';
    if (ctx.route.name === 'sys-reserved') {
      const found = RESERVED_LINKS.find((item) => item.id === ctx.route.params.which);
      return found ? found.label : '预留入口';
    }
    if (view && typeof view.title === 'function') return view.title(ctx);
    return PAGE_TITLES[ctx.route.name] || ctx.route.name;
  }

  // ---------------------------------------------------------------------------
  // 状态项：首页的一排、顶栏亮起的项与托盘图标使用同一份数据（设计说明第 4.1 节）

  function statusItems() {
    const status = Y12.api.query('system.status', {}).data;
    const hs = status.home_status;
    const waiting = Y12.api.query('decisions.list', {}).data;
    const items = [{
      id: 'decisions', label: '待你决定', icon: 'decide', count: waiting.length, lit: waiting.length > 0,
      go: '#/home', anchor: 'home-decisions', query: 'decisions.list'
    }];
    const itemGo = (first, page) => {
      if (!first) return null;
      if (page === 'recovery') return Y12.paths.recovery(first.project_id, first.work_item_id);
      return Y12.paths.overview(first.project_id, first.work_item_id);
    };
    if (hs.unknown_actions) {
      items.push({ id: 'unknown_actions', label: '结果未知的动作', icon: 'unknown', count: hs.unknown_actions.count, lit: hs.unknown_actions.count > 0,
        go: itemGo(hs.unknown_actions.first, 'recovery'), query: 'system.status', tag: '3.1' });
    }
    if (hs.offline_machines) {
      items.push({ id: 'offline_machines', label: '离线的机器', icon: 'offline', count: hs.offline_machines.count, lit: hs.offline_machines.count > 0,
        go: '#/sys/machines', query: 'system.status', tag: '3.2C' });
    }
    if (hs.waiting_provider) {
      items.push({ id: 'waiting_provider', label: '等待模型服务', icon: 'waiting_provider', count: hs.waiting_provider.count, lit: hs.waiting_provider.count > 0,
        go: itemGo(hs.waiting_provider.first), query: 'system.status', tag: 'Stage 4' });
    }
    if (hs.disk) {
      items.push({ id: 'disk', label: '磁盘空间', icon: 'disk', count: null, lit: hs.disk.low,
        text: hs.disk.free_gb + ' GB 可用', go: '#/sys/runtime', anchor: 'runtime-retention', query: 'system.status', tag: 'Stage 4' });
    }
    if (hs.repairing_faults) {
      items.push({ id: 'repairing_faults', label: '正在修复的故障', icon: 'repair', count: hs.repairing_faults.count, lit: hs.repairing_faults.count > 0,
        go: itemGo(hs.repairing_faults.first), query: 'system.status', tag: 'Stage 4' });
    }
    return items;
  }

  function statusItemHtml(item, compact) {
    const value = item.lit ? (item.count !== null ? String(item.count) : item.text) : '无';
    const title = item.label + '：' + (item.lit ? value : '无') + (item.lit && item.go ? '，点击查看' : '');
    const attrs = item.lit && item.go ? ' data-act="shell.status" data-go-to="' + esc(item.go) + '"' + (item.anchor ? ' data-anchor="' + esc(item.anchor) + '"' : '') : ' disabled';
    return '<button type="button" class="y12-stat is-' + item.id + (item.lit ? ' is-lit' : '') + (compact ? ' is-compact' : '') + '"' + attrs + ' title="' + esc(title) + '">' +
      Y12.ui.icon(item.icon, 'y12-icon y12-stat-icon') + '<span class="y12-stat-label">' + esc(item.label) + '</span>' +
      '<span class="y12-stat-value">' + esc(value) + '</span></button>';
  }

  // ---------------------------------------------------------------------------
  // 左侧栏

  function projectRow(entry, ctx) {
    const selected = !isSystemRoute(ctx.route.name) && entry.id === ctx.projectId;
    const remembered = Y12.app.state.lastWorkItem[entry.id] || null;
    const marker = entry.marker && entry.marker.status !== 'idle' ? '<span class="y12-project-marker">' + Y12.ui.status(entry.marker.kind, entry.marker.text) + '</span>' : '';
    const decisions = entry.decisions_waiting ? '<span class="y12-count is-decide" title="待你决定">' + entry.decisions_waiting + '</span>' : '';
    const hidden = searchText && !entry.name.toLowerCase().includes(searchText.toLowerCase()) ? ' hidden' : '';
    return '<li' + hidden + ' data-project-name="' + esc(entry.name) + '"><button type="button" class="y12-project' + (selected ? ' is-selected' : '') + (entry.archived ? ' is-archived' : '') + '" data-go="' + Y12.paths.overview(entry.id, remembered) + '"' + (selected ? ' aria-current="page"' : '') + '>' +
      '<span class="y12-project-name">' + (entry.pinned ? '<span class="y12-pin" title="已置顶">★</span>' : '') + esc(entry.name) + decisions + '</span>' + marker + '</button></li>';
  }

  function sidebarHtml(ctx) {
    const projects = Y12.api.query('projects.list', {}).data;
    const homeActive = ctx.route.name === 'home';
    const systemLinks = SYSTEM_LINKS.filter((link) => Y12.cap.query(link.query)).map((link) => {
      const active = ctx.route.name === link.route;
      const tag = Y12.registry.tagOf('query', link.query);
      return '<li><button type="button" class="y12-side-link' + (active ? ' is-active' : '') + '" data-go="' + Y12.paths.sys(link.id) + '"' + (active ? ' aria-current="page"' : '') + '>' +
        Y12.ui.icon(link.icon) + '<span>' + esc(link.label) + '</span>' + (tag ? Y12.ui.tag(tag) : '') + '</button></li>';
    }).join('');
    const reserved = RESERVED_LINKS.map((link) => {
      const active = ctx.route.name === 'sys-reserved' && ctx.route.params.which === link.id;
      return '<li><button type="button" class="y12-side-link is-reserved' + (active ? ' is-active' : '') + '" data-go="' + Y12.paths.sys(link.id) + '" title="预留入口：' + esc(link.stage) + '">' +
        Y12.ui.icon(link.icon) + '<span>' + esc(link.label) + '</span><span class="y12-side-stage">' + esc(link.stage) + '</span></button></li>';
    }).join('');
    const onboard = Y12.cap.command('project.onboard')
      ? '<button type="button" class="y12-btn y12-onboard" data-act="shell.onboard">' + Y12.ui.icon('import') + '<span>接入已有项目</span>' + Y12.ui.tag('3.8') + '</button>'
      : '';
    return '<div class="y12-side-top">' +
        '<div class="y12-brand">' + Y12.ui.icon('brand', 'y12-icon y12-brand-icon') + '<span class="y12-brand-name">Yudao<small>枢道</small></span><span class="y12-proto-chip">v12 原型</span>' +
          '<button type="button" class="y12-icon-btn y12-drawer-close" data-act="shell.drawer" aria-label="收起左侧栏">' + Y12.ui.icon('close') + '</button></div>' +
        '<button type="button" class="y12-side-link y12-home-link' + (homeActive ? ' is-active' : '') + '" data-go="#/home"' + (homeActive ? ' aria-current="page"' : '') + '>' + Y12.ui.icon('home') + '<span>首页</span></button>' +
        '<div class="y12-side-actions"><button type="button" class="y12-btn primary y12-new-project" data-act="shell.newProject">' + Y12.ui.icon('plus') + '<span>从想法新建</span></button>' + onboard + '</div>' +
        '<label class="y12-search">' + Y12.ui.icon('search') + '<input type="search" placeholder="搜索项目" value="' + esc(searchText) + '" data-act="shell.search" aria-label="搜索项目"></label>' +
        '<div class="y12-side-label"><span>项目</span><span class="y12-count">' + projects.length + '</span></div>' +
        '<ul class="y12-project-list">' + projects.map((entry) => projectRow(entry, ctx)).join('') + '</ul>' +
      '</div>' +
      '<div class="y12-side-bottom">' +
        '<div class="y12-side-label"><span>系统</span></div>' +
        '<ul class="y12-side-links">' + systemLinks + '</ul>' +
        '<div class="y12-side-label is-sub"><span>预留入口</span></div>' +
        '<ul class="y12-side-links">' + reserved + '</ul>' +
        '<button type="button" class="y12-side-link y12-connect-link" data-go="#/connect">' + Y12.ui.icon('plug') + '<span>连接设置</span></button>' +
      '</div>';
  }

  // ---------------------------------------------------------------------------
  // 顶栏

  function connectionHtml() {
    const cap = Y12.cap.get();
    return '<span class="y12-service" title="与控制主机的连接"><span class="y12-dot"></span>已连接 · 接口版本 ' + esc(cap.deployment.api_version) + '</span>';
  }

  // project 为 projects.list 中的该项目；项目不在当前能力范围内时为 null，不查询项目内容
  function scopeSelect(ctx, project) {
    if (!project || isSystemRoute(ctx.route.name)) return '';
    const items = Y12.api.query('project.overview', { project: ctx.projectId }).data.work_items;
    const current = ctx.workItemId || '';
    const options = '<option value="">整个项目</option>' + items.map((item) =>
      '<option value="' + esc(item.id) + '"' + (item.id === current ? ' selected' : '') + '>' + esc(item.title) + (item.display ? ' · ' + esc(item.display.text) : '') + '</option>'
    ).join('');
    return '<label class="y12-scope"><span class="y12-scope-label">范围</span><select data-act="shell.scope" aria-label="事项范围">' + options + '</select></label>';
  }

  function projectMenu(ctx, project) {
    if (!project) return '';
    const items = [
      '<button type="button" role="menuitem" data-act="shell.rename">重命名</button>',
      '<button type="button" role="menuitem" data-cmd="project.pin" data-project="' + esc(project.id) + '" data-pinned="' + (project.pinned ? 'false' : 'true') + '" data-base-version="' + esc(project.version) + '">' + (project.pinned ? '取消置顶' : '置顶') + '</button>',
      project.archived
        ? '<button type="button" role="menuitem" data-cmd="project.restore" data-project="' + esc(project.id) + '" data-base-version="' + esc(project.version) + '">恢复项目</button>'
        : '<button type="button" role="menuitem" data-cmd="project.archive" data-project="' + esc(project.id) + '" data-base-version="' + esc(project.version) + '">归档</button>',
      '<button type="button" role="menuitem" data-go="' + Y12.paths.settings(project.id) + '">项目设置</button>'
    ];
    return '<div class="y12-menu-wrap y12-top-menu"><button type="button" class="y12-icon-btn" data-act="shell.menu" aria-haspopup="menu" aria-expanded="' + menuOpen + '" aria-label="项目菜单">' + Y12.ui.icon('more') + '</button>' +
      (menuOpen ? '<div class="y12-menu" role="menu">' + items.join('') + '</div>' : '') + '</div>';
  }

  function topbarHtml(ctx, project) {
    const drawerButton = '<button type="button" class="y12-icon-btn y12-drawer-open" data-act="shell.drawer" aria-label="打开左侧栏">' + Y12.ui.icon('menu') + '</button>';
    const lit = statusItems().filter((item) => item.lit).map((item) => statusItemHtml(item, true)).join('');
    const stats = lit ? '<div class="y12-top-stats" aria-label="亮起的状态项">' + lit + '</div>' : '';
    const name = ctx.route.name;
    if (isSystemRoute(name)) {
      return drawerButton +
        '<nav class="y12-crumbs" aria-label="路径"><strong>' + esc(pageTitle(ctx)) + '</strong>' + (name === 'gallery' ? '' : '<span class="y12-crumb-note">系统</span>') + '</nav>' +
        '<div class="y12-top-actions">' + stats + connectionHtml() +
        '<button type="button" class="y12-btn small" data-act="app.back">' + Y12.ui.icon('back') + '<span>返回原界面</span></button></div>';
    }
    const crumbs = ['<button type="button" class="y12-crumb" data-go="#/home">首页</button>'];
    if (project) {
      crumbs.push('<button type="button" class="y12-crumb" data-go="' + Y12.paths.overview(project.id, null) + '">' + esc(project.name) + '</button>');
      if (ctx.workItemId) {
        const item = Y12.api.query('project.overview', { project: project.id }).data.work_items.find((w) => w.id === ctx.workItemId);
        if (item) crumbs.push('<button type="button" class="y12-crumb" data-go="' + Y12.paths.overview(project.id, item.id) + '">' + esc(item.title) + '</button>');
      }
    }
    if (name !== 'home') crumbs.push('<strong>' + esc(pageTitle(ctx)) + '</strong>');
    return drawerButton +
      '<nav class="y12-crumbs" aria-label="路径">' + crumbs.join('<span class="y12-crumb-sep">/</span>') + '</nav>' +
      '<div class="y12-top-actions">' + scopeSelect(ctx, project) + stats + connectionHtml() + '</div>' + projectMenu(ctx, project);
  }

  // ---------------------------------------------------------------------------
  // 项目标签与右侧的事项状态

  function nextHtml(ctx) {
    if (!ctx.projectId || !ctx.workItemId) return '';
    const item = Y12.api.query('project.overview', { project: ctx.projectId }).data.work_items.find((w) => w.id === ctx.workItemId);
    if (!item) return '';
    const waiting = Y12.api.query('decisions.list', { work_item: item.id }).data;
    const parts = [];
    if (item.display && item.status !== 'in_progress') parts.push(Y12.ui.status(item.display.kind, item.display.text));
    if (waiting.length) {
      parts.push('<button type="button" class="y12-btn small primary" data-act="shell.decide" data-work-item="' + esc(item.id) + '">' + Y12.ui.icon('decide') + '<span>待你决定 · ' + waiting.length + '</span></button>');
    }
    return parts.length ? '<div class="y12-next" aria-label="所选事项的状态">' + parts.join('') + '</div>' : '';
  }

  function tabsHtml(ctx) {
    const name = ctx.route.name;
    if (isSystemRoute(name) || !ctx.projectId || name === 'home') return '';
    const pid = ctx.projectId;
    const w = ctx.workItemId;
    const dept = ctx.route.params.department;
    const tabs = [
      { id: 'overview', label: '概览', go: Y12.paths.overview(pid, w), active: name === 'overview' },
      { id: 'product', label: '产品', go: Y12.paths.dept(pid, 'product', w), active: name === 'dept' && dept === 'product' },
      { id: 'engineering', label: '工程', go: Y12.paths.dept(pid, 'engineering', w), active: name === 'dept' && dept === 'engineering' },
      { id: 'quality', label: '质检', go: Y12.paths.dept(pid, 'quality', w), active: name === 'dept' && dept === 'quality' },
      { id: 'operations', label: '运维', go: Y12.paths.dept(pid, 'operations', w), active: name === 'dept' && dept === 'operations', show: Y12.cap.query('ops.status'), tag: 'Stage 4' },
      { id: 'materials', label: '资料', go: Y12.paths.materials(pid, w), active: name === 'materials' },
      { id: 'observe', label: '观测', go: Y12.paths.observe(pid, w), active: name === 'observe' || name === 'observe-detail' },
      { id: 'settings', label: '设置', go: Y12.paths.settings(pid), active: name === 'settings' }
    ].filter((tab) => tab.show !== false);
    const links = tabs.map((tab) =>
      '<button type="button" class="y12-ptab' + (tab.active ? ' is-active' : '') + '" data-go="' + esc(tab.go) + '"' + (tab.active ? ' aria-current="page"' : '') + '>' + esc(tab.label) + (tab.tag ? Y12.ui.tag(tab.tag) : '') + '</button>'
    ).join('');
    return '<div class="y12-ptabs" role="navigation" aria-label="项目页面">' + links + '</div>' + nextHtml(ctx);
  }

  // ---------------------------------------------------------------------------
  // 整窗提示：接口版本不同、连接断开

  function versionMismatch() {
    return Y12.api.connected() && Y12.cap.get().deployment.api_version !== Y12.CLIENT_API_VERSION;
  }

  function windowNote() {
    const note = Y12.app.dom.window_note;
    document.body.classList.toggle('is-disconnected', !Y12.api.connected());
    document.body.classList.toggle('is-version-mismatch', versionMismatch());
    if (versionMismatch()) {
      note.hidden = false;
      note.className = 'y12-window-note is-version';
      note.innerHTML = '<div class="y12-update-card"><h1>请更新客户端</h1><p>控制主机的接口版本是 <b>' + esc(Y12.cap.get().deployment.api_version) + '</b>，这个客户端的接口版本是 <b>' + Y12.CLIENT_API_VERSION +
        '</b>。更新客户端之前不打开任何页面，也不执行命令。</p><p class="y12-muted">原型：在底部工具条的「模拟」中把控制主机的接口版本改回 ' + Y12.CLIENT_API_VERSION + '。</p></div>';
      return;
    }
    if (!Y12.api.connected()) {
      note.hidden = false;
      note.className = 'y12-window-note is-offline';
      note.innerHTML = Y12.ui.icon('offline') + '<span>与控制主机的连接已断开（' + esc(Y12.time.clock(disconnectedAt || Y12.app.now())) + ' 起），正在重新连接。界面保留最后一次的数据。</span>';
      return;
    }
    note.hidden = true;
    note.innerHTML = '';
  }

  // ---------------------------------------------------------------------------
  // 托盘与系统通知（设计说明第 10 节）：窗口关闭后仍保持一条不按项目筛选的事件流

  const NOTIFY_TYPES = ['x_decision_issued', 'project_decision_requested', 'x_provider_wait_entered'];

  function trayHtml() {
    const count = Y12.api.connected() ? Y12.api.query('decisions.list', {}).data.length : null;
    return '<button type="button" class="y12-tray" data-act="shell.tray" title="托盘图标（模拟）：等待回答的决定数">' +
      Y12.ui.icon('brand', 'y12-icon y12-tray-icon') + (count ? '<span class="y12-tray-badge">' + count + '</span>' : '') + '<span class="y12-tray-label">托盘</span></button>';
  }

  function notify(title, text, go, anchor) {
    let host = document.getElementById('y12-notify-root');
    if (!host) {
      host = document.createElement('div');
      host.id = 'y12-notify-root';
      host.className = 'y12-notify-root';
      document.body.appendChild(host);
    }
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'y12-notify';
    el.innerHTML = '<span class="y12-notify-app">' + Y12.ui.icon('brand') + 'Yudao · 系统通知（模拟）</span><strong>' + esc(title) + '</strong><span>' + esc(text) + '</span>';
    el.addEventListener('click', () => {
      el.remove();
      openAt(go, anchor);
    });
    host.appendChild(el);
    setTimeout(() => el.remove(), 9000);
  }

  function openAt(go, anchor) {
    if (!go) return;
    Y12.go(go);
    if (anchor) {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const target = document.getElementById(anchor);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }));
    }
  }

  function onStreamEvent(event) {
    const tray = document.getElementById('y12-tray-host');
    if (tray) tray.innerHTML = trayHtml();
    if (!NOTIFY_TYPES.includes(event.type)) return;
    if (event.type === 'x_decision_issued' || event.type === 'project_decision_requested') {
      const d = Y12.api.query('decisions.list', {}).data.find((item) => item.id === event.payload.decision_id);
      if (d) notify('新的决定请求：' + d.kind_label, d.project_name + (d.work_item_title ? ' · ' + d.work_item_title : ''), '#/home', 'decision-' + d.id);
    } else if (event.type === 'x_provider_wait_entered') {
      notify('进入等待模型服务', event.label, Y12.paths.overview(event.project_id, event.work_item_id));
    }
  }

  function ensureTray() {
    let tray = document.getElementById('y12-tray-host');
    if (!tray) {
      tray = document.createElement('div');
      tray.id = 'y12-tray-host';
      tray.className = 'y12-tray-host';
      document.body.appendChild(tray);
      Y12.api.subscribe(null, onStreamEvent);
    }
    tray.innerHTML = trayHtml();
  }

  // ---------------------------------------------------------------------------

  Y12.shell = {
    title: pageTitle,
    statusItems,
    statusItemHtml,
    blocking: versionMismatch,
    openAt,
    render(ctx) {
      const dom = Y12.app.dom;
      if (!Y12.api.connected()) {
        if (!disconnectedAt) disconnectedAt = Y12.app.now();
        windowNote();
        return;
      }
      disconnectedAt = null;
      windowNote();
      ensureTray();
      if (versionMismatch()) {
        dom.sidebar.innerHTML = '';
        dom.topbar.innerHTML = '';
        dom.tabs.hidden = true;
        return;
      }
      const project = ctx.projectId ? Y12.api.query('projects.list', {}).data.find((p) => p.id === ctx.projectId) || null : null;
      lastSidebar = sidebarHtml(ctx);
      dom.sidebar.innerHTML = lastSidebar;
      dom.topbar.innerHTML = topbarHtml(ctx, project);
      const tabs = project ? tabsHtml(ctx) : '';
      dom.tabs.innerHTML = tabs;
      dom.tabs.hidden = !tabs;
      document.title = pageTitle(ctx) + (project && !isSystemRoute(ctx.route.name) ? ' · ' + project.name : '') + ' · Yudao v12 原型';
      document.documentElement.dataset.level = Y12.level.current();
    },
    simulateNotification() {
      const d = Y12.api.query('decisions.list', {}).data[0];
      if (d) notify('新的决定请求：' + d.kind_label, d.project_name + (d.work_item_title ? ' · ' + d.work_item_title : ''), '#/home', 'decision-' + d.id);
      else notify('没有等待回答的决定', '托盘图标不显示数字', '#/home');
    }
  };

  // ---------------------------------------------------------------------------
  // 界面动作

  Y12.actions.register('shell.drawer', () => Y12.app.toggleDrawer());

  Y12.actions.register('shell.search', (el) => {
    searchText = el.value.trim();
    document.querySelectorAll('.y12-project-list li').forEach((li) => {
      li.hidden = Boolean(searchText) && !li.dataset.projectName.toLowerCase().includes(searchText.toLowerCase());
    });
  });

  Y12.actions.register('shell.scope', (el) => Y12.go(Y12.paths.withScope(Y12.route(), el.value || null)));

  Y12.actions.register('shell.status', (el) => openAt(el.dataset.goTo, el.dataset.anchor));

  Y12.actions.register('shell.tray', () => openAt('#/home', 'home-decisions'));

  Y12.actions.register('shell.decide', (el) => {
    const list = Y12.api.query('decisions.list', { work_item: el.dataset.workItem }).data;
    Y12.ui.modal({ title: '待你决定', wide: true, body: list.map((d) => Y12.cards.render(d, {})).join('') });
  });

  Y12.actions.register('shell.menu', () => {
    menuOpen = !menuOpen;
    Y12.app.renderShell();
  });

  document.addEventListener('click', (ev) => {
    if (!menuOpen) return;
    if (ev.target.closest('.y12-top-menu > .y12-icon-btn')) return;
    menuOpen = false;
    Y12.app.renderShell();
  });

  Y12.actions.register('shell.newProject', () => {
    Y12.ui.modal({
      title: '从想法新建项目',
      body: '<div class="y12-form">' +
        '<label class="y12-field"><span>项目名称</span><input type="text" class="y12-input" id="y12-new-name" data-draft="shell.newProject.name" placeholder="例如：门店排班"></label>' +
        '<label class="y12-field"><span>长期目标</span><textarea class="y12-textarea" id="y12-new-goal" rows="4" data-draft="shell.newProject.goal" placeholder="这个项目长期要达成什么"></textarea></label>' +
        '<p class="y12-muted y12-small">新建项目不调用模型；之后在概览中记录原文或作为新事项开始。</p></div>',
      actions: [{ label: '取消', close: true }, { label: '新建', kind: 'primary', act: 'shell.createProject' }]
    });
  });

  Y12.actions.register('shell.createProject', () => {
    const result = Y12.run('project.create', { name: document.getElementById('y12-new-name').value, goal: document.getElementById('y12-new-goal').value });
    if (!result.accepted) return;
    Y12.app.clearDraft('shell.newProject.name');
    Y12.app.clearDraft('shell.newProject.goal');
    Y12.ui.closeModal();
    setTimeout(() => Y12.go(Y12.paths.overview(result.refs.project_id, null)), Y12.backend.latency + 50);
  });

  Y12.actions.register('shell.onboard', () => {
    Y12.ui.modal({
      title: '接入已有项目',
      body: '<div class="y12-form">' +
        '<label class="y12-field"><span>项目名称</span><input type="text" class="y12-input" id="y12-onboard-name" data-draft="shell.onboard.name" placeholder="例如：openai-agents 增加功能"></label>' +
        '<label class="y12-field"><span>长期目标</span><textarea class="y12-textarea" id="y12-onboard-goal" rows="3" data-draft="shell.onboard.goal"></textarea></label>' +
        '<label class="y12-field"><span>源目录名称</span><input type="text" class="y12-input" id="y12-onboard-source" data-draft="shell.onboard.source" placeholder="例如：openai-agents"></label>' +
        '<label class="y12-field"><span>源目录路径（控制主机上的路径）</span><input type="text" class="y12-input" id="y12-onboard-dir" data-draft="shell.onboard.dir" placeholder="例如：D:\\code\\openai-agents-python"></label>' +
        '<p class="y12-muted y12-small">产品阅读已有代码与文档，写出描述现有行为的初始 PRD；工程写出现有结构说明。初始 PRD 由你确认以后成为当前有效的要求。</p></div>',
      actions: [{ label: '取消', close: true }, { label: '开始接入', kind: 'primary', act: 'shell.startOnboard' }]
    });
  });

  Y12.actions.register('shell.startOnboard', () => {
    const result = Y12.run('project.onboard', {
      name: document.getElementById('y12-onboard-name').value,
      goal: document.getElementById('y12-onboard-goal').value,
      source_name: document.getElementById('y12-onboard-source').value,
      source_path: document.getElementById('y12-onboard-dir').value
    });
    if (!result.accepted) return;
    ['name', 'goal', 'source', 'dir'].forEach((k) => Y12.app.clearDraft('shell.onboard.' + k));
    Y12.ui.closeModal();
    setTimeout(() => Y12.go(Y12.paths.overview(result.refs.project_id, null)), Y12.backend.latency + 50);
  });

  Y12.actions.register('shell.rename', () => {
    const project = Y12.api.query('projects.list', {}).data.find((p) => p.id === Y12.app.state.projectId);
    menuOpen = false;
    Y12.app.renderShell();
    Y12.ui.modal({
      title: '重命名项目',
      body: '<label class="y12-field"><span>项目名称</span><input type="text" class="y12-input" id="y12-rename" value="' + esc(project.name) + '"></label>' +
        (project.archived ? '<p class="y12-note is-warn">归档项目只读：写命令会被拒绝。</p>' : ''),
      actions: [{ label: '取消', close: true }, { label: '保存', kind: 'primary', act: 'shell.saveRename' }]
    });
  });

  Y12.actions.register('shell.saveRename', () => {
    const project = Y12.api.query('projects.list', {}).data.find((p) => p.id === Y12.app.state.projectId);
    const result = Y12.run('project.rename', { project: project.id, name: document.getElementById('y12-rename').value, base_version: project.version });
    if (result.accepted) Y12.ui.closeModal();
  });

  // 事件流推送的事件会改变状态项与左侧栏：外壳订阅全部事件并刷新
  let shellRefresh = null;
  Y12.bus.on('route-changed', () => {
    if (shellRefresh) return;
    shellRefresh = Y12.api.subscribe(null, () => {
      if (Y12.api.connected() && !versionMismatch()) Y12.app.renderShell();
    });
  });
})();
