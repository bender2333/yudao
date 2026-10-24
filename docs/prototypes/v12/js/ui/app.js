// 界面层的主体：路由、页面注册与渲染、能力核对、事件流分发、草稿、事件委托、标注与主题（BUILD.md 第 6 节）
(function () {
  'use strict';
  const Y12 = window.Y12;

  const state = {
    route: { name: null, params: {}, query: {}, hash: '' },
    projectId: null,
    workItemId: null,
    annotate: Y12.store.get('annotate', false),
    theme: Y12.store.get('theme', 'system', true),
    drafts: Y12.store.get('drafts', {}),
    source: Y12.store.get('source', null),
    lastWorkItem: Y12.store.get('lastWorkItem', {}),
    drawerOpen: false
  };

  // ---------------------------------------------------------------------------
  // 页面与界面动作的注册

  const views = {};
  Y12.views = {
    register(name, view) {
      if (views[name]) throw new Error('页面重复注册：' + name);
      if (!view || typeof view.render !== 'function') throw new Error('页面缺少 render：' + name);
      views[name] = view;
    },
    get: (name) => views[name] || null
  };

  const actions = {};
  Y12.actions = {
    register(name, fn) {
      if (actions[name]) throw new Error('界面动作重复注册：' + name);
      actions[name] = fn;
    },
    has: (name) => Boolean(actions[name]),
    run(name, el, ev) {
      const fn = actions[name];
      if (!fn) throw new Error('界面动作未注册：' + name);
      return fn(el, ev);
    }
  };

  // ---------------------------------------------------------------------------
  // 草稿

  function saveDrafts() { Y12.store.set('drafts', state.drafts); }
  function restoreDrafts(scope) {
    scope.querySelectorAll('[data-draft]').forEach((el) => {
      const key = el.dataset.draft;
      if (key in state.drafts) el.value = state.drafts[key];
    });
  }

  // ---------------------------------------------------------------------------
  // 路由

  const SYS_PAGES = { models: 'sys-models', machines: 'sys-machines', runtime: 'sys-runtime', tools: 'sys-tools' };
  const RESERVED = ['meta', 'evolution', 'lessons'];
  const PROJECT_PAGES = ['overview', 'materials', 'observe', 'settings'];

  function parseHash(hash) {
    const text = (hash || '').replace(/^#/, '');
    const questionMark = text.indexOf('?');
    const pathPart = questionMark >= 0 ? text.slice(0, questionMark) : text;
    const queryPart = questionMark >= 0 ? text.slice(questionMark + 1) : '';
    const query = Object.fromEntries(new URLSearchParams(queryPart));
    const seg = pathPart.split('/').filter(Boolean).map(decodeURIComponent);
    const route = { name: 'not-found', params: {}, query, hash: '#' + text };
    if (!seg.length || (seg[0] === 'home' && seg.length === 1)) {
      route.name = 'home';
    } else if (seg[0] === 'p' && seg[1]) {
      const projectId = seg[1];
      if (seg.length === 3 && PROJECT_PAGES.includes(seg[2])) {
        route.name = seg[2];
        route.params = { projectId };
      } else if (seg[2] === 'dept' && seg[3] && seg.length === 4) {
        route.name = 'dept';
        route.params = { projectId, department: seg[3] };
      } else if (seg[2] === 'w' && seg[3] && seg[4] === 'recovery' && seg.length === 5) {
        route.name = 'recovery';
        route.params = { projectId, workItemId: seg[3] };
      } else if (seg[2] === 'observe' && seg[3] && seg.length === 4) {
        route.name = 'observe-detail';
        route.params = { projectId, attemptId: seg[3] };
      }
    } else if (seg[0] === 'sys' && seg.length === 2) {
      if (SYS_PAGES[seg[1]]) route.name = SYS_PAGES[seg[1]];
      else if (RESERVED.includes(seg[1])) {
        route.name = 'sys-reserved';
        route.params = { which: seg[1] };
      }
    } else if (seg.length === 1 && (seg[0] === 'connect' || seg[0] === 'gallery')) {
      route.name = seg[0];
    }
    return route;
  }

  const scopeQuery = (workItemId) => (workItemId ? '?w=' + encodeURIComponent(workItemId) : '');

  Y12.paths = {
    home: () => '#/home',
    overview: (projectId, workItemId) => '#/p/' + projectId + '/overview' + scopeQuery(workItemId),
    dept: (projectId, department, workItemId) => '#/p/' + projectId + '/dept/' + department + scopeQuery(workItemId),
    recovery: (projectId, workItemId) => '#/p/' + projectId + '/w/' + workItemId + '/recovery',
    materials: (projectId, workItemId) => '#/p/' + projectId + '/materials' + scopeQuery(workItemId),
    observe: (projectId, workItemId) => '#/p/' + projectId + '/observe' + scopeQuery(workItemId),
    observeDetail: (projectId, attemptId, workItemId) => '#/p/' + projectId + '/observe/' + attemptId + scopeQuery(workItemId),
    settings: (projectId) => '#/p/' + projectId + '/settings',
    sys: (which) => '#/sys/' + which,
    connect: () => '#/connect',
    gallery: () => '#/gallery'
  };

  // 同一页面换一个事项范围
  Y12.paths.withScope = function withScope(route, workItemId) {
    const p = route.params;
    switch (route.name) {
      case 'overview': return Y12.paths.overview(p.projectId, workItemId);
      case 'dept': return Y12.paths.dept(p.projectId, p.department, workItemId);
      case 'recovery': return workItemId ? Y12.paths.recovery(p.projectId, workItemId) : Y12.paths.overview(p.projectId, null);
      case 'materials': return Y12.paths.materials(p.projectId, workItemId);
      case 'observe': case 'observe-detail': return Y12.paths.observe(p.projectId, workItemId);
      default: return Y12.paths.overview(state.projectId, workItemId);
    }
  };

  const isSystemRoute = (name) => typeof name === 'string' && (name.startsWith('sys-') || name === 'connect');

  Y12.go = function go(hash) {
    if (typeof hash !== 'string' || !hash.startsWith('#/')) throw new Error('跳转路径无效：' + hash);
    state.drawerOpen = false;
    if (location.hash === hash) handleRoute();
    else location.hash = hash;
  };

  Y12.back = function back() {
    Y12.go(state.source || Y12.paths.home());
  };

  Y12.route = () => state.route;

  // 只改写查询参数中的一项（回放位置），不重新渲染页面
  Y12.replaceQuery = function replaceQuery(key, value) {
    const route = state.route;
    const query = Object.assign({}, route.query);
    if (value === null || value === undefined || value === '') delete query[key];
    else query[key] = String(value);
    const base = route.hash.split('?')[0];
    const text = new URLSearchParams(query).toString();
    const hash = base + (text ? '?' + text : '');
    route.query = query;
    route.hash = hash;
    lastHash = hash;
    history.replaceState(null, '', hash);
  };

  let lastHash = null;

  function handleRoute() {
    const route = parseHash(location.hash);
    const previous = state.route;
    if (isSystemRoute(route.name) && previous.name && !isSystemRoute(previous.name) && lastHash) {
      state.source = lastHash;
      Y12.store.set('source', state.source);
    }
    if (route.params.projectId) {
      state.projectId = route.params.projectId;
      state.workItemId = route.params.workItemId || route.query.w || null;
      state.lastWorkItem[route.params.projectId] = state.workItemId;
      Y12.store.set('lastWorkItem', state.lastWorkItem);
    } else if (route.name === 'home') {
      state.projectId = null;
      state.workItemId = null;
    }
    const sameRoute = previous.hash === route.hash;
    state.route = route;
    lastHash = route.hash;
    state.drawerOpen = false;
    renderAll(sameRoute);
    Y12.bus.emit('route-changed', route);
  }

  // ---------------------------------------------------------------------------
  // 渲染

  const dom = {};
  let mounted = null;

  function buildCtx() {
    const route = state.route;
    return {
      route,
      projectId: state.projectId,
      workItemId: state.workItemId,
      department: route.params.department || null,
      capabilities: Y12.cap.get()
    };
  }

  function gateHtml(title, text, button) {
    return '<div class="y12-gate"><div class="y12-gate-card"><h1>' + Y12.esc(title) + '</h1><p>' + text + '</p>' +
      '<div class="y12-row">' + (button || '<button class="y12-btn" data-go="#/home">回到首页</button>') + '</div></div></div>';
  }

  function levelButton(level) {
    return '<button class="y12-btn primary" data-act="app.level" data-level="' + level + '">切换到「' + Y12.esc(Y12.LEVEL_LABELS[level]) + '」档</button>';
  }

  // 页面需要的查询没有部署、对象不存在时显示的说明；返回 null 表示可以渲染
  function gateFor(ctx) {
    const route = ctx.route;
    if (route.name === 'not-found') return gateHtml('找不到这个页面', '路径「' + Y12.esc(route.hash) + '」不对应任何页面。');
    const view = views[route.name];
    if (view && view.needs) {
      const missingQuery = (view.needs.queries || []).find((name) => !Y12.cap.query(name));
      const missingCommand = (view.needs.commands || []).find((name) => !Y12.cap.command(name));
      const missing = missingQuery ? ['query', missingQuery] : missingCommand ? ['command', missingCommand] : null;
      if (missing) {
        const level = Y12.registry.levelOf(missing[0], missing[1]);
        const title = typeof view.title === 'function' ? view.title(ctx) : route.name;
        return gateHtml('「' + title + '」属于「' + Y12.LEVEL_LABELS[level] + '」',
          '控制主机的能力清单中没有 <code>' + Y12.esc(missing[1]) + '</code>，这个页面不显示。', levelButton(level));
      }
    }
    if (route.params.projectId) {
      const list = Y12.api.query('projects.list', {}).data;
      if (!list.some((p) => p.id === route.params.projectId)) {
        return gateHtml('找不到项目', '控制主机上没有项目「' + Y12.esc(route.params.projectId) + '」，或者它属于还没有部署的工作包。');
      }
    }
    if (route.name === 'dept' && !['product', 'engineering', 'quality', 'operations'].includes(route.params.department)) {
      return gateHtml('找不到部门', '部门「' + Y12.esc(route.params.department) + '」不存在。');
    }
    return null;
  }

  function unmountCurrent() {
    if (mounted && mounted.view && mounted.view.unmount) mounted.view.unmount(mounted.ctx, dom.content);
    if (mounted && mounted.unsubscribe) mounted.unsubscribe();
    mounted = null;
  }

  function renderShell() {
    if (!Y12.shell || typeof Y12.shell.render !== 'function') throw new Error('外壳未注册：js/ui/shell.js 需要定义 Y12.shell.render');
    Y12.shell.render(buildCtx());
    document.body.classList.toggle('is-drawer-open', state.drawerOpen);
  }

  function renderContent(keepScroll) {
    // 连接断开时保留最后一次的页面，由外壳整体变灰
    if (!Y12.api.connected()) return;
    const scrollY = window.scrollY;
    unmountCurrent();
    if (Y12.shell.blocking()) {
      dom.content.innerHTML = '';
      return;
    }
    const ctx = buildCtx();
    const gate = gateFor(ctx);
    dom.content.dataset.view = ctx.route.name;
    if (gate) {
      dom.content.innerHTML = gate;
      mounted = { name: ctx.route.name, view: null, ctx };
      window.scrollTo(0, 0);
      return;
    }
    const view = views[ctx.route.name];
    if (!view) {
      dom.content.innerHTML = gateHtml('页面尚未注册', '页面「' + Y12.esc(ctx.route.name) + '」的文件还没有注册它。');
      mounted = { name: ctx.route.name, view: null, ctx };
      throw new Error('页面未注册：' + ctx.route.name);
    }
    dom.content.innerHTML = view.render(ctx);
    restoreDrafts(dom.content);
    mounted = { name: ctx.route.name, view, ctx };
    if (view.mount) view.mount(ctx, dom.content);
    const scope = view.scope ? view.scope(ctx) : null;
    const current = mounted;
    mounted.unsubscribe = Y12.api.subscribe(scope, (event) => onPageEvent(current, event));
    window.scrollTo(0, keepScroll ? scrollY : 0);
    Y12.bus.emit('content-rendered', ctx);
  }

  function onPageEvent(entry, event) {
    if (entry !== mounted) return;
    const ctx = buildCtx();
    entry.ctx = ctx;
    if (entry.view.update) {
      entry.view.update(ctx, dom.content, event);
      restoreDrafts(dom.content);
    } else {
      renderContent(true);
    }
    if (entry === mounted && entry.view.onEvent) entry.view.onEvent(ctx, dom.content, event);
  }

  function renderAll(keepScroll) {
    if (Y12.api.connected()) Y12.cap.refresh();
    renderShell();
    if (Y12.toolbar) Y12.toolbar.render();
    renderContent(keepScroll);
  }

  // ---------------------------------------------------------------------------
  // 事件委托

  function closestAction(target) {
    return target.closest('[data-go],[data-cmd],[data-act],[data-tab],[data-close-modal]');
  }

  const isFormControl = (el) => el.matches('select, input, textarea');
  const isTextual = (el) => el.matches('textarea, input:not([type]), input[type=text], input[type=search], input[type=number], input[type=password], input[type=url]');

  // data-* 读回的参数：键名转为 snake_case，去掉 cmd
  function paramsOf(el) {
    const out = {};
    Object.keys(el.dataset).forEach((key) => {
      if (key === 'cmd') return;
      out[Y12.snake(key)] = el.dataset[key];
    });
    return out;
  }

  // 执行命令并提示结果；返回 Y12.api.command 的结果
  Y12.run = function run(name, params) {
    const result = Y12.api.command(name, params || {});
    if (result.accepted) {
      if (result.message) Y12.ui.toast(result.message, 'ok');
    } else {
      Y12.ui.toast(result.message || '命令被拒绝：' + result.reason, 'warn');
    }
    return result;
  };

  function dispatch(el, ev) {
    if (el.dataset.tab && el.dataset.tabGroup) {
      Y12.ui.selectTab(el.dataset.tabGroup, el.dataset.tab);
      return;
    }
    if (el.dataset.go) {
      ev.preventDefault();
      Y12.go(el.dataset.go);
    }
    if (el.dataset.cmd) Y12.run(el.dataset.cmd, paramsOf(el));
    if (el.dataset.act) Y12.actions.run(el.dataset.act, el, ev);
    if (el.hasAttribute('data-close-modal')) Y12.ui.closeModal();
  }

  function onClick(ev) {
    if (ev.target.matches('[data-modal-backdrop]')) {
      Y12.ui.closeModal();
      return;
    }
    const el = closestAction(ev.target);
    if (!el || isFormControl(el) || el.disabled) return;
    dispatch(el, ev);
  }

  function onChange(ev) {
    const el = ev.target;
    if (!isFormControl(el) || isTextual(el)) return;
    if (el.dataset.act) Y12.actions.run(el.dataset.act, el, ev);
    if (el.dataset.go) Y12.go(el.dataset.go);
  }

  function onInput(ev) {
    const el = ev.target;
    if (!isFormControl(el)) return;
    if (el.dataset.draft) {
      if (el.value === '') delete state.drafts[el.dataset.draft];
      else state.drafts[el.dataset.draft] = el.value;
      saveDrafts();
    }
    if (isTextual(el) && el.dataset.act) Y12.actions.run(el.dataset.act, el, ev);
  }

  function onKeydown(ev) {
    if (ev.key !== 'Escape') return;
    if (Y12.ui.modalOpen()) Y12.ui.closeModal();
    else if (state.drawerOpen) {
      state.drawerOpen = false;
      document.body.classList.remove('is-drawer-open');
    }
  }

  function applyTheme() {
    const html = document.documentElement;
    if (state.theme === 'system') delete html.dataset.theme;
    else html.dataset.theme = state.theme;
  }

  // ---------------------------------------------------------------------------
  // 接口

  Y12.app = {
    state,
    dom,
    parseHash,
    renderAll,
    renderContent,
    renderShell,
    restoreDrafts,
    ctx: buildCtx,
    annotate: () => state.annotate,
    setAnnotate(on) {
      state.annotate = Boolean(on);
      Y12.store.set('annotate', state.annotate);
      document.documentElement.classList.toggle('is-annotate', state.annotate);
      renderAll(true);
    },
    theme: () => state.theme,
    setTheme(theme) {
      if (!['system', 'light', 'dark'].includes(theme)) throw new Error('未知主题：' + theme);
      state.theme = theme;
      Y12.store.set('theme', theme, true);
      applyTheme();
    },
    draft: (key) => (key in state.drafts ? state.drafts[key] : ''),
    clearDraft(key) {
      delete state.drafts[key];
      saveDrafts();
    },
    toggleDrawer(open) {
      state.drawerOpen = open === undefined ? !state.drawerOpen : Boolean(open);
      document.body.classList.toggle('is-drawer-open', state.drawerOpen);
    },
    // 控制主机的现在：取自 system.status 的 now；断开连接时保留最后一次读到的值
    now() {
      if (Y12.api.connected()) lastNow = Y12.api.query('system.status', {}).data.now;
      if (!lastNow) throw new Error('还没有读到控制主机的时间');
      return lastNow;
    },
    start() {
      ['y12-sidebar', 'y12-topbar', 'y12-tabs', 'y12-content', 'y12-toolbar', 'y12-modal-root', 'y12-toast-root', 'y12-window-note'].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) throw new Error('index.html 缺少外壳元素：' + id);
        dom[id.replace('y12-', '').replace('-', '_')] = el;
      });
      applyTheme();
      document.documentElement.classList.toggle('is-annotate', state.annotate);
      document.addEventListener('click', onClick);
      document.addEventListener('change', onChange);
      document.addEventListener('input', onInput);
      document.addEventListener('keydown', onKeydown);
      window.addEventListener('hashchange', handleRoute);
      Y12.bus.on('level-changed', () => renderAll(true));
      Y12.bus.on('connection-changed', () => renderAll(true));
      Y12.bus.on('api-version-changed', () => renderAll(true));
      Y12.bus.on('last-seen-changed', () => renderAll(true));
      if (!location.hash) history.replaceState(null, '', '#/home');
      handleRoute();
    }
  };

  let lastNow = null;

  Y12.actions.register('app.level', (el) => Y12.level.set(el.dataset.level));
  Y12.actions.register('app.back', () => Y12.back());
})();
