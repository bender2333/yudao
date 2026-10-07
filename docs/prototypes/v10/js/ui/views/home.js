// 首页（设计说明第 4 节）：状态项、楼与地下室机房、待你决定、离开期间的报告与时间轴、项目列表
(function () {
  'use strict';
  const Y10 = window.Y10;
  const esc = Y10.esc;

  let panel = null;
  let range = Y10.store.get('home.range', 'since_seen');
  let openItem = null;   // 展开来源事件的报告项
  let selected = null;   // 时间轴上选中的刻度位置

  function statusRow() {
    const items = Y10.shell.statusItems();
    return Y10.ui.block({
      query: ['system.status', 'decisions.list'], className: 'y10-home-status',
      body: '<div class="y10-stats" aria-label="状态项">' + items.map((it) => Y10.shell.statusItemHtml(it, false)).join('') + '</div>'
    });
  }

  function decisionsBlock() {
    return Y10.ui.block({
      id: 'home-decisions', title: '待你决定', query: 'decisions.list', command: 'decision.answer',
      subtitle: '跨项目，按发出时间排列', body: Y10.cards.list({})
    });
  }

  function sourceEvents(item, facts) {
    if (!item.refs.length) return '<p class="y10-muted y10-small">' + esc(item.detail || '') + '（来源：范围内的调用尝试记录）</p>';
    const rows = item.refs.map((pos) => {
      const f = facts.find((x) => x.position === pos);
      const ev = f ? f.event : Y10.api.query('event.detail', { position: pos }).data.event;
      return '<li><span class="y10-muted">' + esc(Y10.ui.time(ev.at)) + '</span> ' + esc(ev.label) + ' <code class="y10-code">' + esc(ev.type) + '</code></li>';
    }).join('');
    return '<ul class="y10-source-list">' + rows + '</ul>';
  }

  function reportBlock() {
    const report = Y10.api.query('home.away_report', { range }).data;
    const ranges = report.ranges.map((r) => '<button type="button" class="y10-seg-btn' + (r.id === range ? ' is-on' : '') + '" data-act="home.range" data-range="' + r.id + '">' + esc(r.label) + '</button>').join('');
    const summary = report.summary.length
      ? '<div class="y10-report-items">' + report.summary.map((item) => {
        const hl = selected !== null && item.refs.includes(selected);
        const open = openItem === item.id;
        return '<div class="y10-report-item' + (hl ? ' is-highlight' : '') + (open ? ' is-open' : '') + '">' +
          '<button type="button" class="y10-report-head" data-act="home.item" data-item="' + esc(item.id) + '">' +
            '<span class="y10-report-label">' + esc(item.label) + '</span>' +
            '<span class="y10-report-value">' + esc(Y10.num(item.value)) + '<small>' + esc(item.unit) + '</small></span>' +
            (item.detail ? '<span class="y10-report-detail">' + esc(item.detail) + '</span>' : '') +
          '</button>' + (open ? sourceEvents(item, report.facts) : '') + '</div>';
      }).join('') + '</div>'
      : Y10.ui.empty('这段时间没有完成、放行或其他需要报告的事');
    const lastSeen = '上次查看：' + esc(Y10.ui.time(report.last_seen.at)) + '（' + esc(Y10.ui.duration(Y10.ui.since(report.last_seen.at))) + '以前）';
    return Y10.ui.block({
      id: 'home-report', title: '离开期间的报告', query: 'home.away_report', command: 'home.mark_seen',
      subtitle: lastSeen,
      actions: '<span class="y10-seg">' + ranges + '</span>' + Y10.ui.button({ label: '已看过', kind: 'small primary', act: 'home.seen', data: { position: report.range.to_position } }),
      body: summary + '<div class="y10-home-timeline" id="home-timeline"></div>'
    });
  }

  function projectsBlock() {
    const list = Y10.api.query('projects.list', {}).data.filter((p) => !p.archived);
    const table = Y10.ui.table({
      columns: [
        { label: '项目', render: (p) => '<button type="button" class="y10-link" data-go="' + esc(Y10.paths.overview(p.id, null)) + '">' + esc(p.name) + '</button>' + (p.source === 'existing' ? Y10.ui.tag('已有项目') : '') },
        { label: '长期目标', render: (p) => '<span class="y10-clamp">' + esc(p.goal) + '</span>' },
        { label: '当前成果', render: (p) => (p.adoption ? Y10.ui.status('adopted', p.adoption.version) : '<span class="y10-muted">尚未采纳</span>') },
        { label: '进行中 · 排队中', render: (p) => esc(p.active_count + ' · ' + p.queued_count) },
        { label: '待回答的决定', render: (p) => (p.decisions_waiting ? '<span class="y10-count is-decide">' + p.decisions_waiting + '</span>' : '<span class="y10-muted">无</span>') },
        { label: '状态', render: (p) => Y10.ui.status(p.marker.kind, p.marker.text) },
        { label: '最近活动', render: (p) => esc(Y10.ui.time(p.last_activity_at)) }
      ],
      rows: list,
      empty: '还没有项目'
    });
    return Y10.ui.block({ id: 'home-projects', title: '项目', query: 'projects.list', body: table });
  }

  function render() {
    return '<div class="y10-home">' +
      statusRow() +
      Y10.ui.block({ title: '全部项目与机器', query: ['projects.list', 'project.loop'], className: 'y10-home-building', subtitle: '每个项目一层；点击楼层进入项目概览', body: '<div id="home-building"></div>' }) +
      decisionsBlock() +
      reportBlock() +
      projectsBlock() +
    '</div>';
  }

  function mount(ctx, root) {
    const host = root.querySelector('#home-building');
    const timeline = root.querySelector('#home-timeline');
    panel = Y10.scenes.mountBuilding(host, {
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
    refreshSection(root, '.y10-home-status', statusRow());
    refreshSection(root, '#home-decisions', decisionsBlock());
    refreshReport(root);
    refreshSection(root, '#home-projects', projectsBlock());
    if (panel) panel.update();
  }

  Y10.views.register('home', {
    title: () => '首页',
    needs: { queries: ['system.status', 'projects.list', 'decisions.list', 'home.away_report', 'project.loop'] },
    render,
    mount,
    update,
    onEvent: (ctx, root, ev) => { if (panel) panel.onEvent(ev); },
    unmount: () => { if (panel) panel.destroy(); panel = null; },
    highlightMachines: (ids) => { if (panel) panel.highlightMachines(ids); }
  });

  Y10.actions.register('home.range', (el) => {
    range = el.dataset.range;
    Y10.store.set('home.range', range);
    openItem = null;
    selected = null;
    const root = Y10.app.dom.content;
    refreshReport(root);
    if (panel && panel.replay) panel.replay.setRange(range);
  });

  Y10.actions.register('home.item', (el) => {
    const id = el.dataset.item;
    openItem = openItem === id ? null : id;
    const report = Y10.api.query('home.away_report', { range }).data;
    const item = report.summary.find((s) => s.id === id);
    if (panel && panel.replay) panel.replay.highlight(openItem && item ? item.refs : []);
    refreshReport(Y10.app.dom.content);
  });

  Y10.actions.register('home.seen', (el) => {
    Y10.run('home.mark_seen', { position: Number(el.dataset.position) });
  });
})();
