// 首页（设计说明第 4 节）：状态项、楼与地下室机房、待你决定、离开期间的报告与时间轴、项目列表
(function () {
  'use strict';
  const Y8 = window.Y8;
  const esc = Y8.esc;

  let panel = null;
  let range = Y8.store.get('home.range', 'since_seen');
  let openItem = null;   // 展开来源事件的报告项
  let selected = null;   // 时间轴上选中的刻度位置

  function statusRow() {
    const items = Y8.shell.statusItems();
    return Y8.ui.block({
      query: ['system.status', 'decisions.list'], className: 'y8-home-status',
      body: '<div class="y8-stats" aria-label="状态项">' + items.map((it) => Y8.shell.statusItemHtml(it, false)).join('') + '</div>'
    });
  }

  function decisionsBlock() {
    return Y8.ui.block({
      id: 'home-decisions', title: '待你决定', query: 'decisions.list', command: 'decision.answer',
      subtitle: '跨项目，按发出时间排列', body: Y8.cards.list({})
    });
  }

  function sourceEvents(item, facts) {
    if (!item.refs.length) return '<p class="y8-muted y8-small">' + esc(item.detail || '') + '（来源：范围内的调用尝试记录）</p>';
    const rows = item.refs.map((pos) => {
      const f = facts.find((x) => x.position === pos);
      const ev = f ? f.event : Y8.api.query('event.detail', { position: pos }).data.event;
      return '<li><span class="y8-muted">' + esc(Y8.ui.time(ev.at)) + '</span> ' + esc(ev.label) + ' <code class="y8-code">' + esc(ev.type) + '</code></li>';
    }).join('');
    return '<ul class="y8-source-list">' + rows + '</ul>';
  }

  function reportBlock() {
    const report = Y8.api.query('home.away_report', { range }).data;
    const ranges = report.ranges.map((r) => '<button type="button" class="y8-seg-btn' + (r.id === range ? ' is-on' : '') + '" data-act="home.range" data-range="' + r.id + '">' + esc(r.label) + '</button>').join('');
    const summary = report.summary.length
      ? '<div class="y8-report-items">' + report.summary.map((item) => {
        const hl = selected !== null && item.refs.includes(selected);
        const open = openItem === item.id;
        return '<div class="y8-report-item' + (hl ? ' is-highlight' : '') + (open ? ' is-open' : '') + '">' +
          '<button type="button" class="y8-report-head" data-act="home.item" data-item="' + esc(item.id) + '">' +
            '<span class="y8-report-label">' + esc(item.label) + '</span>' +
            '<span class="y8-report-value">' + esc(Y8.num(item.value)) + '<small>' + esc(item.unit) + '</small></span>' +
            (item.detail ? '<span class="y8-report-detail">' + esc(item.detail) + '</span>' : '') +
          '</button>' + (open ? sourceEvents(item, report.facts) : '') + '</div>';
      }).join('') + '</div>'
      : Y8.ui.empty('这段时间没有完成、放行或其他需要报告的事');
    const lastSeen = '上次查看：' + esc(Y8.ui.time(report.last_seen.at)) + '（' + esc(Y8.ui.duration(Y8.ui.since(report.last_seen.at))) + '以前）';
    return Y8.ui.block({
      id: 'home-report', title: '离开期间的报告', query: 'home.away_report', command: 'home.mark_seen',
      subtitle: lastSeen,
      actions: '<span class="y8-seg">' + ranges + '</span>' + Y8.ui.button({ label: '已看过', kind: 'small primary', act: 'home.seen', data: { position: report.range.to_position } }),
      body: summary + '<div class="y8-home-timeline" id="home-timeline"></div>'
    });
  }

  function projectsBlock() {
    const list = Y8.api.query('projects.list', {}).data.filter((p) => !p.archived);
    const table = Y8.ui.table({
      columns: [
        { label: '项目', render: (p) => '<button type="button" class="y8-link" data-go="' + esc(Y8.paths.overview(p.id, null)) + '">' + esc(p.name) + '</button>' + (p.source === 'existing' ? Y8.ui.tag('已有项目') : '') },
        { label: '长期目标', render: (p) => '<span class="y8-clamp">' + esc(p.goal) + '</span>' },
        { label: '当前成果', render: (p) => (p.adoption ? Y8.ui.status('adopted', p.adoption.version) : '<span class="y8-muted">尚未采纳</span>') },
        { label: '进行中 · 排队中', render: (p) => esc(p.active_count + ' · ' + p.queued_count) },
        { label: '待回答的决定', render: (p) => (p.decisions_waiting ? '<span class="y8-count is-decide">' + p.decisions_waiting + '</span>' : '<span class="y8-muted">无</span>') },
        { label: '状态', render: (p) => Y8.ui.status(p.marker.kind, p.marker.text) },
        { label: '最近活动', render: (p) => esc(Y8.ui.time(p.last_activity_at)) }
      ],
      rows: list,
      empty: '还没有项目'
    });
    return Y8.ui.block({ id: 'home-projects', title: '项目', query: 'projects.list', body: table });
  }

  function render() {
    return '<div class="y8-home">' +
      statusRow() +
      Y8.ui.block({ title: '全部项目与机器', query: ['projects.list', 'project.loop'], className: 'y8-home-building', subtitle: '每个项目一层；点击楼层进入项目概览', body: '<div id="home-building"></div>' }) +
      decisionsBlock() +
      reportBlock() +
      projectsBlock() +
    '</div>';
  }

  function mount(ctx, root) {
    const host = root.querySelector('#home-building');
    const timeline = root.querySelector('#home-timeline');
    panel = Y8.scenes.mountBuilding(host, {
      timelineEl: timeline, range,
      onSelect(pos) { selected = pos; refreshReport(root); }
    });
  }

  function refreshSection(root, selector, html) {
    const el = root.querySelector(selector);
    if (!el) return;
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const next = tmp.firstElementChild;
    if (next) el.replaceWith(next);
  }

  // 报告区域重绘时保留时间轴（回放状态在时间轴中）
  function refreshReport(root) {
    const timeline = root.querySelector('#home-timeline');
    const report = root.querySelector('#home-report');
    if (!report || !timeline) return;
    const tmp = document.createElement('div');
    tmp.innerHTML = reportBlock();
    const next = tmp.firstElementChild;
    next.querySelector('#home-timeline').replaceWith(timeline);
    report.replaceWith(next);
  }

  function update(ctx, root) {
    refreshSection(root, '.y8-home-status', statusRow());
    refreshSection(root, '#home-decisions', decisionsBlock());
    refreshReport(root);
    refreshSection(root, '#home-projects', projectsBlock());
    if (panel) panel.update();
  }

  Y8.views.register('home', {
    title: () => '首页',
    needs: { queries: ['system.status', 'projects.list', 'decisions.list', 'home.away_report', 'project.loop'] },
    render,
    mount,
    update,
    onEvent: (ctx, root, ev) => { if (panel) panel.onEvent(ev); },
    unmount: () => { if (panel) panel.destroy(); panel = null; },
    highlightMachines: (ids) => { if (panel) panel.highlightMachines(ids); }
  });

  Y8.actions.register('home.range', (el) => {
    range = el.dataset.range;
    Y8.store.set('home.range', range);
    openItem = null;
    selected = null;
    const root = Y8.app.dom.content;
    refreshReport(root);
    if (panel && panel.replay) panel.replay.setRange(range);
  });

  Y8.actions.register('home.item', (el) => {
    const id = el.dataset.item;
    openItem = openItem === id ? null : id;
    const report = Y8.api.query('home.away_report', { range }).data;
    const item = report.summary.find((s) => s.id === id);
    if (panel && panel.replay) panel.replay.highlight(openItem && item ? item.refs : []);
    refreshReport(Y8.app.dom.content);
  });

  Y8.actions.register('home.seen', (el) => {
    Y8.run('home.mark_seen', { position: Number(el.dataset.position) });
  });
})();
