// 界面辅助函数：转义、图标、状态标记、区块、按钮、表格、页签、弹窗、提示条、键值列表、进度条、时间与数字
(function () {
  'use strict';
  const Y12 = window.Y12;

  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  Y12.esc = function esc(text) {
    if (text === null || text === undefined) return '';
    return String(text).replace(/[&<>"']/g, (ch) => ESC[ch]);
  };

  Y12.dataAttrs = function dataAttrs(data) {
    if (!data) return '';
    return Object.keys(data)
      .filter((key) => data[key] !== undefined && data[key] !== null)
      .map((key) => ' data-' + Y12.kebab(key) + '="' + Y12.esc(data[key]) + '"')
      .join('');
  };

  const ICON_PATHS = {
    running: '<circle cx="8" cy="8" r="3.6" fill="currentColor" stroke="none"/><circle cx="8" cy="8" r="6.2" opacity=".35"/>',
    succeeded: '<path d="M3.2 8.4l3 3 6.6-7"/>',
    queued: '<rect x="2" y="4" width="12" height="8" rx="1.5"/><path d="M6 4v8"/><path d="M8.6 7h3M8.6 9h2"/>',
    asking: '<path d="M1.8 7.6L14 2.4l-3.6 11.2-2.6-4.4z"/><path d="M7.8 9.2L14 2.4"/>',
    paused: '<path d="M5.5 3.5v9M10.5 3.5v9"/>',
    failed: '<circle cx="8" cy="8" r="6"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/>',
    done: '<path d="M4 14.2V2.4"/><path d="M4 2.8h7.6l-1.8 2.6 1.8 2.6H4"/>',
    cancelled: '<circle cx="8" cy="8" r="6"/><path d="M3.8 12.2l8.4-8.4"/>',
    interrupted: '<path d="M9.2 1.6L3.8 9h4l-1 5.4L12.2 7h-4z"/>',
    pending: '<circle cx="8" cy="8" r="6"/><path d="M6.2 6.2a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1v.5"/><path d="M8 11.4v.2"/>',
    waiting: '<path d="M5 2.2L8 4.4l3-2.2"/><rect x="2" y="4.4" width="12" height="7.4" rx="1"/><path d="M5 8.1h6"/>',
    waiting_slot: '<rect x="2" y="3" width="3.2" height="10" rx=".6"/><rect x="6.4" y="3" width="3.2" height="10" rx=".6"/><rect x="10.8" y="3" width="3.2" height="10" rx=".6"/><path d="M1.5 14.5h13"/>',
    waiting_provider: '<circle cx="8" cy="8" r="6"/><path d="M8 4.6V8l2.4 1.6"/>',
    offline: '<path d="M2.4 6.4a8 8 0 0 1 11.2 0"/><path d="M4.6 8.8a4.8 4.8 0 0 1 6.8 0"/><circle cx="8" cy="11.6" r=".9" fill="currentColor"/><path d="M2.6 2.6l10.8 10.8"/>',
    repair: '<path d="M10.4 2.2a3.2 3.2 0 0 0-3.6 4.4L2.6 10.8a1.3 1.3 0 0 0 1.8 1.8l4.2-4.2a3.2 3.2 0 0 0 4.4-3.6l-2 2-1.8-.4-.4-1.8z"/>',
    adopted: '<rect x="1.8" y="2.4" width="12.4" height="3.2" rx=".6"/><path d="M2.8 5.6v7.8h10.4V5.6"/><path d="M6.2 8.4h3.6"/>',
    released: '<path d="M6.2 2h3.6v3.8l2.4 1.6v2.2H3.8V7.4l2.4-1.6z"/><path d="M2.6 13.6h10.8"/>',
    candidate: '<circle cx="8" cy="8" r="5.6" stroke-dasharray="2.2 2"/>',
    admitted: '<path d="M8 1.6l5.2 2v4.2c0 3-2.2 5.3-5.2 6.6-3-1.3-5.2-3.6-5.2-6.6V3.6z"/><path d="M5.6 8l1.7 1.7 3.1-3.3"/>',
    unusable: '<path d="M8 1.8l6.6 11.6H1.4z"/><path d="M8 6.4v3.2"/><path d="M8 11.4v.2"/>',
    unknown: '<path d="M5.6 5.6a2.4 2.4 0 1 1 3.4 2.2c-.7.3-1 .8-1 1.5v.6"/><path d="M8 12.4v.2"/>',
    idle: '<circle cx="8" cy="8" r="5.6"/>'
  };
  Y12.STATUS_KINDS = Object.keys(ICON_PATHS);

  function svg(inner, className) {
    return '<svg class="' + (className || 'y12-icon') + '" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + '</svg>';
  }
  Y12.svg = svg;

  const GLYPHS = {
    brand: '<path d="M2.5 3.5h11v9h-11z"/><path d="M2.5 7.5h11M6.5 7.5v5M9.5 3.5v4"/>',
    home: '<path d="M2.2 7.6L8 2.6l5.8 5"/><path d="M3.8 6.4v7h8.4v-7"/><path d="M6.6 13.4V9.6h2.8v3.8"/>',
    menu: '<path d="M2.5 4h11M2.5 8h11M2.5 12h11"/>',
    close: '<path d="M4 4l8 8M12 4l-8 8"/>',
    plus: '<path d="M8 3v11M3 8h10"/>',
    search: '<circle cx="7" cy="7" r="4.3"/><path d="M10.2 10.2l3.3 3.3"/>',
    back: '<path d="M9.8 3.6L5.4 8l4.4 4.4"/>',
    link: '<path d="M6.6 9.4l2.8-2.8"/><path d="M7.2 4.6l1.2-1.2a2.6 2.6 0 0 1 3.7 3.7l-1.2 1.2"/><path d="M8.8 11.4l-1.2 1.2a2.6 2.6 0 0 1-3.7-3.7l1.2-1.2"/>',
    import: '<path d="M8 2.4v7.2"/><path d="M5 6.8L8 9.8l3-3"/><path d="M2.6 10.6v2.8h10.8v-2.8"/>',
    models: '<rect x="3.5" y="3.5" width="9" height="9" rx="1.5"/><path d="M6.2 1.5v2M9.8 1.5v2M6.2 12.5v2M9.8 12.5v2M1.5 6.2h2M1.5 9.8h2M12.5 6.2h2M12.5 9.8h2"/>',
    machines: '<rect x="2.5" y="2" width="11" height="4.6" rx="1"/><rect x="2.5" y="9.4" width="11" height="4.6" rx="1"/><path d="M5 4.3h.1M5 11.7h.1"/>',
    runtime: '<rect x="2" y="3" width="3.2" height="10" rx=".6"/><rect x="6.4" y="3" width="3.2" height="10" rx=".6"/><rect x="10.8" y="3" width="3.2" height="10" rx=".6"/>',
    tools: '<path d="M10.4 2.2a3.2 3.2 0 0 0-3.6 4.4L2.6 10.8a1.3 1.3 0 0 0 1.8 1.8l4.2-4.2a3.2 3.2 0 0 0 4.4-3.6l-2 2-1.8-.4-.4-1.8z"/>',
    meta: '<path d="M1.6 8s2.4-4.4 6.4-4.4S14.4 8 14.4 8 12 12.4 8 12.4 1.6 8 1.6 8z"/><circle cx="8" cy="8" r="2"/>',
    evolution: '<circle cx="4.5" cy="3.5" r="1.6"/><circle cx="4.5" cy="12.5" r="1.6"/><circle cx="11.5" cy="6" r="1.6"/><path d="M4.5 5.1v5.8M11.5 7.6c0 2.4-2.6 2.6-5.6 3.9"/>',
    lessons: '<path d="M2.5 3.2c2-.8 3.8-.6 5.5.6 1.7-1.2 3.5-1.4 5.5-.6v9.6c-2-.8-3.8-.6-5.5.6-1.7-1.2-3.5-1.4-5.5-.6z"/><path d="M8 3.8v9.6"/>',
    gallery: '<rect x="2.5" y="2.5" width="11" height="11" rx="1.5"/><circle cx="6" cy="6" r="1.3"/><path d="M13.5 10.5L10 7l-7 6.5"/>',
    more: '<circle cx="3.5" cy="8" r=".9" fill="currentColor"/><circle cx="8" cy="8" r=".9" fill="currentColor"/><circle cx="12.5" cy="8" r=".9" fill="currentColor"/>',
    chevron: '<path d="M4.5 6.2L8 9.8l3.5-3.6"/>',
    restart: '<path d="M13 8a5 5 0 1 1-1.5-3.6"/><path d="M13 2.6v2.6h-2.6"/>',
    lock: '<rect x="3.5" y="7" width="9" height="6.5" rx="1"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/>',
    play: '<path d="M5 3.2l7.6 4.8L5 12.8z" fill="currentColor"/>',
    pause: '<path d="M5.4 3.4v9.2M10.6 3.4v9.2"/>',
    step: '<path d="M4 3.4l6.4 4.6L4 12.6z"/><path d="M12.4 3.4v9.2"/>',
    reset: '<path d="M3 8a5 5 0 1 0 1.5-3.6"/><path d="M3 2.6v2.6h2.6"/>',
    tag: '<path d="M2.4 2.4h5.8l5.4 5.4-5.8 5.8-5.4-5.4z"/><circle cx="5.4" cy="5.4" r="1"/>',
    bell: '<path d="M4 11V7.4a4 4 0 0 1 8 0V11l1.2 1.4H2.8z"/><path d="M6.6 13.8a1.5 1.5 0 0 0 2.8 0"/>',
    disk: '<ellipse cx="8" cy="4" rx="5.5" ry="2"/><path d="M2.5 4v8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2V4"/><path d="M2.5 8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2"/>',
    decide: '<path d="M3 2.5h7l3 3v8H3z"/><path d="M10 2.5v3h3"/><path d="M5.5 9l1.6 1.6L10.6 7"/>',
    plug: '<path d="M6 2v3M10 2v3"/><path d="M4.4 5h7.2v2.6a3.6 3.6 0 0 1-7.2 0z"/><path d="M8 11.2V14"/>'
  };

  Y12.ui = {};

  Y12.ui.icon = function icon(name, className) {
    const inner = GLYPHS[name] || ICON_PATHS[name];
    if (!inner) throw new Error('未知图标：' + name);
    return svg(inner, className);
  };

  Y12.ui.tag = function tag(text, kind) {
    if (!text) return '';
    return '<span class="y12-tag' + (kind ? ' is-' + kind : '') + '">' + Y12.esc(text) + '</span>';
  };

  Y12.ui.status = function status(kind, text) {
    if (!ICON_PATHS[kind]) throw new Error('未知状态种类：' + kind);
    return '<span class="y12-status is-' + kind + '">' + svg(ICON_PATHS[kind], 'y12-status-icon') + '<span>' + Y12.esc(text) + '</span></span>';
  };

  // 区块的档位与能力：取 query 与 command 列出的名称
  function namesOf(opts) {
    const qs = [].concat(opts.query || []).map((name) => ['query', name]);
    const cs = [].concat(opts.command || []).map((name) => ['command', name]);
    return qs.concat(cs);
  }

  function blockAllowed(names) {
    return names.every(([kind, name]) => (kind === 'query' ? Y12.cap.query(name) : Y12.cap.command(name)));
  }

  function blockTag(names) {
    let best = null;
    names.forEach(([kind, name]) => {
      const level = Y12.registry.levelOf(kind, name);
      if (!best || Y12.level.compare(level, best) > 0) best = level;
    });
    return best ? Y12.LEVEL_TAGS[best] : null;
  }

  function annotationHtml(opts, names, tag) {
    const list = (kind) => {
      const items = names.filter((pair) => pair[0] === kind).map(([, name]) => Y12.esc(name));
      return items.length ? items.join('、') : '无';
    };
    return '<div class="y12-annot" role="note"><span><b>查询</b>' + list('query') + '</span><span><b>命令</b>' + list('command') +
      '</span><span><b>档位</b>' + Y12.esc(tag || '界面工作线') + '</span></div>';
  }

  Y12.ui.block = function block(opts) {
    if (!opts) throw new Error('block 需要参数');
    const names = namesOf(opts);
    if (!blockAllowed(names)) return '';
    const tag = opts.tag !== undefined ? opts.tag : blockTag(names);
    const head = opts.title || opts.actions
      ? '<header class="y12-block-head"><div class="y12-block-titles">' +
        (opts.title ? '<h2 class="y12-block-title">' + Y12.esc(opts.title) + '</h2>' : '') +
        Y12.ui.tag(tag) +
        (opts.subtitle ? '<p class="y12-block-sub">' + Y12.esc(opts.subtitle) + '</p>' : '') +
        '</div>' + (opts.actions ? '<div class="y12-block-actions">' + opts.actions + '</div>' : '') + '</header>'
      : '';
    return '<section class="y12-block' + (opts.className ? ' ' + opts.className : '') + '"' +
      (opts.id ? ' id="' + Y12.esc(opts.id) + '"' : '') +
      (opts.query ? ' data-query="' + Y12.esc([].concat(opts.query).join(' ')) + '"' : '') +
      (opts.command ? ' data-command="' + Y12.esc([].concat(opts.command).join(' ')) + '"' : '') + '>' +
      (Y12.app && Y12.app.annotate() ? annotationHtml(opts, names, tag) : '') +
      head + '<div class="y12-block-body">' + (opts.body || '') + '</div></section>';
  };

  Y12.ui.button = function button(opts) {
    const kind = opts.kind ? ' ' + opts.kind : '';
    const attrs = (opts.act ? ' data-act="' + Y12.esc(opts.act) + '"' : '') +
      (opts.cmd ? ' data-cmd="' + Y12.esc(opts.cmd) + '"' : '') +
      (opts.go ? ' data-go="' + Y12.esc(opts.go) + '"' : '') +
      (opts.close ? ' data-close-modal' : '') +
      (opts.title ? ' title="' + Y12.esc(opts.title) + '"' : '') +
      (opts.disabled ? ' disabled' : '') +
      Y12.dataAttrs(opts.data);
    return '<button type="button" class="y12-btn' + kind + '"' + attrs + '>' + (opts.icon ? Y12.ui.icon(opts.icon) : '') + '<span>' + Y12.esc(opts.label) + '</span></button>';
  };

  Y12.ui.table = function table(opts) {
    const columns = opts.columns || [];
    const rows = opts.rows || [];
    if (!rows.length) return Y12.ui.empty(opts.empty || '没有记录');
    const head = columns.map((col) => '<th' + (col.className ? ' class="' + col.className + '"' : '') + '>' + Y12.esc(col.label) + '</th>').join('');
    const body = rows.map((row) => {
      const cells = columns.map((col) => {
        const value = col.render ? col.render(row) : Y12.esc(row[col.key]);
        return '<td data-label="' + Y12.esc(col.label) + '"' + (col.className ? ' class="' + col.className + '"' : '') + '><div class="y12-td">' + (value === '' || value === undefined || value === null ? '<span class="y12-muted">—</span>' : value) + '</div></td>';
      }).join('');
      const attrs = opts.rowAttrs ? opts.rowAttrs(row) : '';
      return '<tr' + (attrs ? ' ' + attrs : '') + '>' + cells + '</tr>';
    }).join('');
    return '<div class="y12-table-wrap"><table class="y12-table' + (opts.className ? ' ' + opts.className : '') + '"><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
  };

  // 页签：items 为 { id, label, tag, count, show }；show 为 false 的页签不显示（按能力清单决定）
  const tabState = Y12.store.get('tabs', {});

  Y12.ui.activeTab = function activeTab(id, items, fallback) {
    const visible = (items || []).filter((item) => item.show !== false);
    const stored = tabState[id];
    if (visible.some((item) => item.id === stored)) return stored;
    if (fallback && visible.some((item) => item.id === fallback)) return fallback;
    return visible.length ? visible[0].id : null;
  };

  Y12.ui.tabs = function tabs(opts) {
    const items = (opts.items || []).filter((item) => item.show !== false);
    const active = Y12.ui.activeTab(opts.id, items, opts.active);
    return '<div class="y12-tabs" role="tablist" data-tab-group-root="' + Y12.esc(opts.id) + '">' + items.map((item) =>
      '<button type="button" role="tab" class="y12-tab' + (item.id === active ? ' is-active' : '') + '" aria-selected="' + (item.id === active) + '" data-tab-group="' + Y12.esc(opts.id) + '" data-tab="' + Y12.esc(item.id) + '">' +
      Y12.esc(item.label) + (item.tag ? Y12.ui.tag(item.tag) : '') + (item.count !== undefined ? '<span class="y12-count">' + Y12.esc(item.count) + '</span>' : '') + '</button>'
    ).join('') + '</div>';
  };

  Y12.ui.tabPanels = function tabPanels(group, active, panels) {
    return Object.keys(panels).map((id) =>
      '<div class="y12-tab-panel" role="tabpanel" data-tab-panel="' + Y12.esc(group) + '" data-tab-id="' + Y12.esc(id) + '"' + (id === active ? '' : ' hidden') + '>' + panels[id] + '</div>'
    ).join('');
  };

  Y12.ui.selectTab = function selectTab(group, tab) {
    tabState[group] = tab;
    Y12.store.set('tabs', tabState);
    const panels = document.querySelectorAll('[data-tab-panel="' + CSS.escape(group) + '"]');
    document.querySelectorAll('[data-tab-group="' + CSS.escape(group) + '"]').forEach((el) => {
      const on = el.dataset.tab === tab;
      el.classList.toggle('is-active', on);
      el.setAttribute('aria-selected', String(on));
    });
    if (panels.length) panels.forEach((el) => { el.hidden = el.dataset.tabId !== tab; });
    else Y12.app.renderContent(true);
    Y12.bus.emit('tab-changed', { group, tab });
  };

  function root(id) {
    const el = document.getElementById(id);
    if (!el) throw new Error('index.html 缺少元素：' + id);
    return el;
  }

  Y12.ui.modal = function modal(opts) {
    const actions = Array.isArray(opts.actions) ? opts.actions.map((item) => Y12.ui.button(item)).join('') : (opts.actions || '');
    const host = root('y12-modal-root');
    host.innerHTML = '<div class="y12-modal-backdrop" data-modal-backdrop>' +
      '<div class="y12-modal' + (opts.wide ? ' is-wide' : '') + (opts.className ? ' ' + opts.className : '') + '" role="dialog" aria-modal="true" aria-label="' + Y12.esc(opts.title) + '">' +
      '<header class="y12-modal-head"><h2>' + Y12.esc(opts.title) + '</h2>' +
      '<button type="button" class="y12-icon-btn" data-close-modal aria-label="关闭">' + Y12.ui.icon('close') + '</button></header>' +
      '<div class="y12-modal-body">' + (opts.body || '') + '</div>' +
      (actions ? '<footer class="y12-modal-foot">' + actions + '</footer>' : '') +
      '</div></div>';
    document.body.classList.add('has-modal');
    Y12.app.restoreDrafts(host);
    const card = host.querySelector('.y12-modal');
    const focusTarget = card.querySelector('textarea, input, select') || card.querySelector('.y12-modal-foot .y12-btn');
    if (focusTarget) focusTarget.focus();
    return card;
  };

  Y12.ui.closeModal = function closeModal() {
    root('y12-modal-root').innerHTML = '';
    document.body.classList.remove('has-modal');
  };

  Y12.ui.modalOpen = () => Boolean(root('y12-modal-root').firstChild);

  Y12.ui.toast = function toast(message, kind) {
    const el = document.createElement('div');
    el.className = 'y12-toast is-' + (kind || 'ok');
    el.setAttribute('role', 'status');
    el.textContent = message;
    root('y12-toast-root').appendChild(el);
    setTimeout(() => el.classList.add('is-leaving'), 3600);
    setTimeout(() => el.remove(), 4000);
  };

  Y12.ui.empty = (text) => '<div class="y12-empty">' + Y12.esc(text) + '</div>';
  Y12.ui.note = (html, kind) => '<div class="y12-note' + (kind ? ' is-' + kind : '') + '">' + html + '</div>';

  // 键值列表：pairs 为 [[名称, 已转义的 HTML], …]
  Y12.ui.kv = function kv(pairs, className) {
    return '<dl class="y12-kv' + (className ? ' ' + className : '') + '">' + pairs.filter(Boolean).map((pair) =>
      '<div><dt>' + Y12.esc(pair[0]) + '</dt><dd>' + (pair[1] === '' || pair[1] === null || pair[1] === undefined ? '<span class="y12-muted">—</span>' : pair[1]) + '</dd></div>'
    ).join('') + '</dl>';
  };

  Y12.ui.meter = function meter(value, max, opts) {
    const ratio = max ? Math.min(1, Math.max(0, value / max)) : 0;
    const warn = opts && opts.warnAt !== undefined ? ratio >= opts.warnAt : ratio >= 0.85;
    return '<div class="y12-meter' + (warn ? ' is-warn' : '') + '" role="meter" aria-valuemin="0" aria-valuemax="' + max + '" aria-valuenow="' + value + '"><span style="width:' + (ratio * 100).toFixed(1) + '%"></span></div>';
  };

  Y12.ui.code = (text) => '<code class="y12-code">' + Y12.esc(text) + '</code>';
  Y12.ui.pre = (text) => '<pre class="y12-pre">' + Y12.esc(text) + '</pre>';

  // 时间：相对于控制主机的现在（system.status 的时间来源为示例数据的 now）
  Y12.ui.time = (iso) => Y12.time.format(iso, Y12.app ? Y12.app.now() : null);
  Y12.ui.duration = (sec) => Y12.time.duration(sec);
  Y12.ui.since = (iso) => Math.max(0, Y12.time.between(iso, Y12.app.now()));
  Y12.ui.num = (value) => Y12.num(value);
})();
