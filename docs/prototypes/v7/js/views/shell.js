// 外壳：左侧栏（项目列表、系统分组、服务重启提示）、顶栏（路径、事项选择框、服务状态、项目菜单）、项目标签
(function () {
  'use strict';

  const Y7 = window.Y7;
  const esc = Y7.esc;

  let searchText = '';
  let menuOpen = false;

  const SYSTEM_LINKS = [
    { id: 'models', label: '模型管理', icon: 'models', route: 'sys-models', tag: 'D24', tagLevel: 's3' },
    { id: 'runtime', label: '运行与执行槽位', icon: 'runtime', route: 'sys-runtime', tag: '3.4A', level: 's3' },
    { id: 'tools', label: '工具与扩展', icon: 'tools', route: 'sys-tools', tag: '3.2B · 3.7', level: 's3' },
    { id: 'meta', label: '元观察', icon: 'meta', route: 'sys-meta', tag: 'Stage 5', level: 's5' }
  ];

  const RESERVED_LINKS = [
    { id: 'nodes', label: '节点', icon: 'nodes', stage: 'Stage 6' },
    { id: 'evolution', label: '演化', icon: 'evolution', stage: 'Stage 7' },
    { id: 'lessons', label: '经验', icon: 'lessons', stage: '持续改进' }
  ];

  const PAGE_TITLES = {
    overview: '概览', dept: '部门工作间', recovery: '恢复与动作核实', materials: '资料', observe: '观测',
    'observe-detail': '请求详情', settings: '设置', 'sys-models': '模型管理', 'sys-runtime': '运行与执行槽位',
    'sys-tools': '工具与扩展', 'sys-meta': '元观察', 'sys-reserved': '预留入口', gallery: '动作图鉴（原型专用）', 'not-found': '找不到页面'
  };

  function pageTitle(ctx) {
    const view = Y7.views.get(ctx.route.name);
    if (view && typeof view.title === 'function' && !view.level) return view.title(ctx);
    if (view && typeof view.title === 'function' && view.level && Y7.atLeast(view.level)) return view.title(ctx);
    if (ctx.route.name === 'dept' && ctx.route.params.department in Y7.DEPT_LABELS) return Y7.deptLabel(ctx.route.params.department) + '部门';
    if (ctx.route.name === 'sys-reserved') {
      const found = RESERVED_LINKS.find((item) => item.id === ctx.route.params.which);
      return found ? found.label : '预留入口';
    }
    return PAGE_TITLES[ctx.route.name] || ctx.route.name;
  }

  // 待恢复事项：s3 起，恢复观察状态为中断、待核实或待恢复的事项
  function recoveryItems() {
    if (!Y7.atLeast('s3')) return [];
    const list = [];
    Y7.resolve(Y7.data.workItems).forEach((item) => {
      const project = Y7.project(item.projectId);
      if (!project) return;
      const run = item.runId ? Y7.run(item.runId) : null;
      if (run && run.recovery && ['interrupted', 'pending_verification', 'waiting_resume'].includes(run.recovery.state)) {
        list.push({ item, project, state: run.recovery.state });
      }
    });
    return list;
  }

  // ---------------------------------------------------------------------------
  // 左侧栏

  function projectRow(entry, ctx) {
    const selected = !Y7.isSystemRoute(ctx.route.name) && ctx.route.name !== 'gallery' && entry.id === Y7.state.projectId;
    const remembered = Y7.state.lastWorkItem[entry.id] || null;
    const marker = entry.marker
      ? '<span class="y7-project-marker">' + Y7.ui.status(entry.marker.kind, entry.marker.text) +
        (entry.marker.count > 1 ? '<span class="y7-count" title="同时进行的事项">' + entry.marker.count + '</span>' : '') + '</span>'
      : '';
    const hidden = searchText && !entry.name.toLowerCase().includes(searchText.toLowerCase()) ? ' hidden' : '';
    return '<li' + hidden + ' data-project-name="' + esc(entry.name) + '"><button type="button" class="y7-project' + (selected ? ' is-selected' : '') + (entry.archived ? ' is-archived' : '') + '" data-go="' + Y7.paths.overview(entry.id, remembered) + '"' + (selected ? ' aria-current="page"' : '') + '>' +
      '<span class="y7-project-name">' + (entry.pinned ? '<span class="y7-pin" title="已置顶">★</span>' : '') + esc(entry.name) + '</span>' + marker + '</button></li>';
  }

  function sidebarHtml(ctx) {
    const projects = Y7.query('projects.list');
    const pending = recoveryItems();
    const restarted = Y7.atLeast('s3') && Y7.data.service && Y7.data.service.restartedAt;
    const restartNotice = restarted && pending.length
      ? '<button type="button" class="y7-restart" data-go="' + Y7.paths.recovery(pending[0].project.id, pending[0].item.id) + '">' +
        Y7.ui.icon('restart') + '<span><strong>服务已重启，' + pending.length + ' 个事项待恢复</strong><small>' + esc(Y7.ui.time(Y7.data.service.restartedAt)) + ' 重启 · 点击进入「' + esc(pending[0].item.title) + '」的恢复页 ' + Y7.ui.tag('3.1') + '</small></span></button>'
      : '';
    const systemLinks = SYSTEM_LINKS.filter((link) => Y7.atLeast(link.level)).map((link) => {
      const active = ctx.route.name === link.route;
      const tag = link.tagLevel ? (Y7.atLeast(link.tagLevel) ? link.tag : '') : link.tag;
      return '<li><button type="button" class="y7-side-link' + (active ? ' is-active' : '') + '" data-go="' + Y7.paths.sys(link.id) + '"' + (active ? ' aria-current="page"' : '') + '>' +
        Y7.ui.icon(link.icon) + '<span>' + esc(link.label) + '</span>' + (tag ? Y7.ui.tag(tag) : '') + '</button></li>';
    }).join('');
    const reserved = RESERVED_LINKS.map((link) => {
      const active = ctx.route.name === 'sys-reserved' && ctx.route.params.which === link.id;
      return '<li><button type="button" class="y7-side-link is-reserved' + (active ? ' is-active' : '') + '" data-go="' + Y7.paths.sys(link.id) + '" title="预留入口：' + esc(link.stage) + '">' +
        Y7.ui.icon(link.icon) + '<span>' + esc(link.label) + '</span><span class="y7-side-stage">' + esc(link.stage) + '</span></button></li>';
    }).join('');
    return '<div class="y7-side-top">' +
        '<div class="y7-brand">' + Y7.ui.icon('brand', 'y7-icon y7-brand-icon') + '<span class="y7-brand-name">Yudao<small>枢道</small></span><span class="y7-proto-chip">v7 原型</span>' +
          '<button type="button" class="y7-icon-btn y7-drawer-close" data-act="shell.drawer" aria-label="收起项目列表">' + Y7.ui.icon('close') + '</button></div>' +
        '<button type="button" class="y7-btn primary y7-new-project" data-act="shell.newProject">' + Y7.ui.icon('plus') + '<span>从想法新建</span></button>' +
        '<label class="y7-search">' + Y7.ui.icon('search') + '<input type="search" placeholder="搜索项目" value="' + esc(searchText) + '" data-act="shell.search" aria-label="搜索项目"></label>' +
        '<div class="y7-side-label"><span>项目</span><span class="y7-count">' + projects.length + '</span></div>' +
        '<ul class="y7-project-list">' + projects.map((entry) => projectRow(entry, ctx)).join('') + '</ul>' +
      '</div>' +
      '<div class="y7-side-bottom">' + restartNotice +
        '<div class="y7-side-label"><span>系统</span></div>' +
        '<ul class="y7-side-links">' + systemLinks + '</ul>' +
        '<div class="y7-side-label is-sub"><span>预留入口</span></div>' +
        '<ul class="y7-side-links">' + reserved + '</ul>' +
      '</div>';
  }

  // ---------------------------------------------------------------------------
  // 顶栏

  function serviceStatus() {
    if (Y7.atLeast('s3') && Y7.data.service && Y7.data.service.restartedAt) {
      return '<span class="y7-service" title="服务状态">' + '<span class="y7-dot"></span>服务运行中 · ' + esc(Y7.ui.time(Y7.data.service.restartedAt)) + ' 重启</span>';
    }
    return '<span class="y7-service" title="服务状态"><span class="y7-dot"></span>服务运行中 · 实时</span>';
  }

  function scopeSelect(ctx) {
    if (!ctx.project) return '';
    const items = Y7.query('project.overview', { projectId: ctx.project.id }).workItems;
    const current = ctx.workItem ? ctx.workItem.id : '';
    const options = '<option value="">整个项目</option>' + items.map((item) =>
      '<option value="' + esc(item.id) + '"' + (item.id === current ? ' selected' : '') + '>' + esc(item.title) + ' · ' + esc(item.display.text) + '</option>'
    ).join('');
    return '<label class="y7-scope"><span class="y7-scope-label">范围</span><select data-act="shell.scope" aria-label="事项范围">' + options + '</select></label>';
  }

  function projectMenu(ctx) {
    if (!ctx.project) return '';
    const p = ctx.project;
    const items = [
      '<button type="button" role="menuitem" data-act="shell.rename">重命名</button>',
      '<button type="button" role="menuitem" data-cmd="pinProject" data-project-id="' + esc(p.id) + '">' + (p.pinned ? '取消置顶' : '置顶') + '</button>',
      p.archived
        ? '<button type="button" role="menuitem" data-cmd="restoreProject" data-project-id="' + esc(p.id) + '">恢复项目</button>'
        : '<button type="button" role="menuitem" data-cmd="archiveProject" data-project-id="' + esc(p.id) + '">归档</button>',
      '<button type="button" role="menuitem" data-go="' + Y7.paths.settings(p.id) + '">项目设置</button>'
    ];
    return '<div class="y7-menu-wrap"><button type="button" class="y7-icon-btn" data-act="shell.menu" aria-haspopup="menu" aria-expanded="' + menuOpen + '" aria-label="项目菜单">' + Y7.ui.icon('more') + '</button>' +
      (menuOpen ? '<div class="y7-menu" role="menu">' + items.join('') + '</div>' : '') + '</div>';
  }

  function topbarHtml(ctx) {
    const drawerButton = '<button type="button" class="y7-icon-btn y7-drawer-open" data-act="shell.drawer" aria-label="打开项目列表">' + Y7.ui.icon('menu') + '</button>';
    const name = ctx.route.name;
    if (Y7.isSystemRoute(name) || name === 'gallery') {
      return drawerButton +
        '<nav class="y7-crumbs" aria-label="路径"><strong>' + esc(pageTitle(ctx)) + '</strong>' + (name === 'gallery' ? '' : '<span class="y7-crumb-note">系统</span>') + '</nav>' +
        '<div class="y7-top-actions">' + serviceStatus() +
        '<button type="button" class="y7-btn small" data-act="core.back">' + Y7.ui.icon('back') + '<span>返回原界面</span></button></div>';
    }
    const crumbs = ['<span class="y7-crumb-root">项目</span>'];
    if (ctx.project) {
      crumbs.push('<button type="button" class="y7-crumb" data-go="' + Y7.paths.overview(ctx.project.id, null) + '">' + esc(ctx.project.name) + '</button>');
      if (ctx.workItem) crumbs.push('<button type="button" class="y7-crumb" data-go="' + Y7.paths.overview(ctx.project.id, ctx.workItem.id) + '">' + esc(ctx.workItem.title) + '</button>');
    }
    crumbs.push('<strong>' + esc(pageTitle(ctx)) + '</strong>');
    return drawerButton +
      '<nav class="y7-crumbs" aria-label="路径">' + crumbs.join('<span class="y7-crumb-sep">/</span>') + '</nav>' +
      '<div class="y7-top-actions">' + scopeSelect(ctx) + serviceStatus() + projectMenu(ctx) + '</div>';
  }

  // ---------------------------------------------------------------------------
  // 项目标签与右侧的事项状态

  function nextActionHtml(ctx) {
    if (!Y7.atLeast('s3') || !ctx.workItem || !ctx.project) return '';
    const item = Y7.query('project.overview', { projectId: ctx.project.id }).workItems.find((entry) => entry.id === ctx.workItem.id);
    const run = ctx.run;
    const recovery = run && run.recovery ? run.recovery : null;
    const status = Y7.ui.status(item.display.kind, item.display.text);
    const pid = ctx.project.id;
    let action = '';
    if (recovery && recovery.state === 'waiting_resume') {
      action = Y7.ui.button({ label: '继续执行', kind: 'small primary', go: Y7.paths.recovery(pid, item.id), title: recovery.canResume ? '可以继续执行' : '先修复原因：' + (recovery.resumeBlockedReason || '') });
    } else if (recovery && recovery.state === 'pending_verification') {
      action = Y7.ui.button({ label: '查看核实', kind: 'small primary', go: Y7.paths.recovery(pid, item.id) });
    } else if (recovery && recovery.state === 'interrupted') {
      action = Y7.ui.button({ label: '查看恢复', kind: 'small primary', go: Y7.paths.recovery(pid, item.id) });
    } else if (item.status === 'queued') {
      action = Y7.ui.button({ label: '取消排队', kind: 'small', cmd: 'cancelQueued', data: { workItemId: item.id } });
    } else if (item.status === 'held') {
      action = Y7.ui.button({ label: '查看候选', kind: 'small', go: Y7.paths.overview(pid, item.id) });
    } else if (item.status === 'adopted' || item.status === 'released_unsettled') {
      action = Y7.ui.button({ label: '查看资料', kind: 'small', go: Y7.paths.materials(pid, item.id) });
    } else if (item.status === 'stopped') {
      action = Y7.ui.button({ label: '查看恢复记录', kind: 'small', go: Y7.paths.recovery(pid, item.id) });
    } else if (item.status === 'not_started') {
      action = '';
    } else {
      return '';
    }
    return '<div class="y7-next" aria-label="所选事项的状态与下一项操作">' + status + action + Y7.ui.tag('3.1') + '</div>';
  }

  function tabsHtml(ctx) {
    const name = ctx.route.name;
    if (Y7.isSystemRoute(name) || name === 'gallery' || !ctx.project) return '';
    const pid = ctx.project.id;
    const w = ctx.workItem ? ctx.workItem.id : null;
    const tabs = [
      { id: 'overview', label: '概览', go: Y7.paths.overview(pid, w), active: name === 'overview' },
      { id: 'product', label: '产品', go: Y7.paths.dept(pid, 'product', w), active: name === 'dept' && ctx.route.params.department === 'product' },
      { id: 'engineering', label: '工程', go: Y7.paths.dept(pid, 'engineering', w), active: name === 'dept' && ctx.route.params.department === 'engineering' },
      { id: 'quality', label: '质检', go: Y7.paths.dept(pid, 'quality', w), active: name === 'dept' && ctx.route.params.department === 'quality' },
      { id: 'operations', label: '运维', go: Y7.paths.dept(pid, 'operations', w), active: name === 'dept' && ctx.route.params.department === 'operations', level: 's5', tag: 'Stage 5' },
      { id: 'materials', label: '资料', go: Y7.paths.materials(pid, w), active: name === 'materials' },
      { id: 'observe', label: '观测', go: Y7.paths.observe(pid, w), active: name === 'observe' || name === 'observe-detail' },
      { id: 'settings', label: '设置', go: Y7.paths.settings(pid), active: name === 'settings' }
    ].filter((tab) => Y7.atLeast(tab.level));
    const links = tabs.map((tab) =>
      '<button type="button" class="y7-ptab' + (tab.active ? ' is-active' : '') + '" data-go="' + esc(tab.go) + '"' + (tab.active ? ' aria-current="page"' : '') + '>' + esc(tab.label) + (tab.tag ? Y7.ui.tag(tab.tag) : '') + '</button>'
    ).join('');
    return '<div class="y7-ptabs" role="navigation" aria-label="项目页面">' + links + '</div>' + nextActionHtml(ctx);
  }

  // ---------------------------------------------------------------------------

  Y7.shell = {
    title: pageTitle,
    render(ctx) {
      const dom = Y7.dom;
      dom.sidebar.innerHTML = sidebarHtml(ctx);
      dom.topbar.innerHTML = topbarHtml(ctx);
      const tabs = tabsHtml(ctx);
      dom.tabs.innerHTML = tabs;
      dom.tabs.hidden = !tabs;
      document.title = pageTitle(ctx) + (ctx.project && !Y7.isSystemRoute(ctx.route.name) && ctx.route.name !== 'gallery' ? ' · ' + ctx.project.name : '') + ' · Yudao v7 原型';
      document.documentElement.dataset.level = Y7.state.level;
    }
  };

  // ---------------------------------------------------------------------------
  // 界面动作

  Y7.actions.register('shell.drawer', () => {
    Y7.state.drawerOpen = !Y7.state.drawerOpen;
    document.body.classList.toggle('is-drawer-open', Y7.state.drawerOpen);
  });

  Y7.actions.register('shell.search', (el) => {
    searchText = el.value.trim();
    document.querySelectorAll('.y7-project-list li').forEach((li) => {
      li.hidden = Boolean(searchText) && !li.dataset.projectName.toLowerCase().includes(searchText.toLowerCase());
    });
  });

  Y7.actions.register('shell.scope', (el) => {
    Y7.go(Y7.withScope(Y7.state.route, el.value || null));
  });

  Y7.actions.register('shell.menu', () => {
    menuOpen = !menuOpen;
    Y7.renderShell();
  });

  document.addEventListener('click', (ev) => {
    if (!menuOpen) return;
    if (ev.target.closest('.y7-menu-wrap > .y7-icon-btn')) return;
    menuOpen = false;
    Y7.renderShell();
  });

  Y7.actions.register('shell.newProject', () => {
    Y7.ui.modal({
      title: '从想法新建项目',
      body: '<div class="y7-form">' +
        '<label class="y7-field"><span>项目名称</span><input type="text" class="y7-input" id="y7-new-name" data-draft="shell.newProject.name" placeholder="例如：门店排班"></label>' +
        '<label class="y7-field"><span>长期目标</span><textarea class="y7-textarea" id="y7-new-goal" rows="4" data-draft="shell.newProject.goal" placeholder="这个项目长期要达成什么"></textarea></label>' +
        '<p class="y7-muted y7-small">新建项目不调用模型；之后在概览中记录原文或作为新事项开始。</p></div>',
      actions: [
        { label: '取消', close: true },
        { label: '新建', kind: 'primary', act: 'shell.createProject' }
      ]
    });
  });

  Y7.actions.register('shell.createProject', () => {
    const name = document.getElementById('y7-new-name').value;
    const goal = document.getElementById('y7-new-goal').value;
    const result = Y7.command('createProject', { name, goal });
    if (!result.ok) return;
    Y7.clearDraft('shell.newProject.name');
    Y7.clearDraft('shell.newProject.goal');
    Y7.ui.closeModal();
    Y7.go(Y7.paths.overview(result.projectId, null));
  });

  Y7.actions.register('shell.rename', () => {
    const project = Y7.project(Y7.state.projectId);
    menuOpen = false;
    Y7.renderShell();
    Y7.ui.modal({
      title: '重命名项目',
      body: '<label class="y7-field"><span>项目名称</span><input type="text" class="y7-input" id="y7-rename" value="' + esc(project.name) + '"></label>' +
        (project.archived ? '<p class="y7-note is-warn">归档项目只读：写命令会返回冲突。</p>' : ''),
      actions: [
        { label: '取消', close: true },
        { label: '保存', kind: 'primary', act: 'shell.saveRename' }
      ]
    });
  });

  Y7.actions.register('shell.saveRename', () => {
    const result = Y7.command('renameProject', { projectId: Y7.state.projectId, name: document.getElementById('y7-rename').value });
    if (result.ok) Y7.ui.closeModal();
  });
})();
