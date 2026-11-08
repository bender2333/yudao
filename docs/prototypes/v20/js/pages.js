// 页面：首页（项目一览、待你决定、离开期间的报告）、按位置看一条事件
(function () {
  'use strict';
  const Y20 = window.Y20;
  const esc = Y20.esc;
  const H = Y20.h;
  const ui = Y20.ui;

  const timeAt = (iso) => esc(ui.time(iso));

  // ---------------------------------------------------------------- 首页

  let openItem = null;

  function nowDoing(p) {
    return H.in(p, () => {
      const lines = p.depts.map((d) => ({ s: p.deptState[d], d })).filter((x) => x.s.state !== 'idle');
      if (!lines.length) return '<span class="y20-muted">没有在做的事</span>';
      return '<div class="y20-cell-stack">' + lines.map((x) => '<span>' + (p.depts.length > 1 ? '<b>' + esc(H.dept(x.d, p)) + '</b>：' : '') + esc(x.s.text) + '</span>').join('') + '</div>';
    });
  }

  function whereItems(p) {
    const live = p.items.filter((i) => !['adopted', 'open_closed', 'stopped'].includes(i.status));
    if (!live.length) return '<span class="y20-muted">没有进行中的事项</span>';
    return '<div class="y20-cell-stack">' + live.map((i) => '<span>' + H.dot(i) + ' ' + esc(i.title) + ' <span class="y20-muted">· ' + esc(i.dept ? H.dept(i.dept, p) : '排队') + '</span></span>').join('') + '</div>';
  }

  function slotCell(p) {
    const w = p.items.filter((i) => i.status === 'waiting_slot');
    const base = '占用 ' + p.slots.used + ' / ' + p.slots.limit;
    return w.length
      ? '<div class="y20-cell-stack"><span class="y20-warn-text">有 ' + w.length + ' 个事项在等执行槽位</span><small class="y20-muted">' + base + '；' + esc(w.map((i) => i.title).join('、')) + ' 已等 ' + esc(H.waited(w[0].since)) + '</small></div>'
      : '<div class="y20-cell-stack"><span>没有事项在等</span><small class="y20-muted">' + base + '</small></div>';
  }

  function projectsBlock() {
    const table = ui.table({
      columns: [
        { label: '项目', render: (p) => H.link('#/p/' + p.id, p.name) + ' ' + ui.tag(Y20.formLabel(p).name + (Y20.formLabel(p).changed ? '（改过 ' + Y20.formLabel(p).changed + ' 处）' : '')) },
        { label: '此刻在做什么', render: nowDoing },
        { label: '事项在哪个职能', render: whereItems },
        { label: '执行槽位', render: slotCell },
        { label: '待你决定', render: (p) => { const n = Y20.leanDecisions(p); return n ? '<button type="button" class="y20-link" data-act="ln.jump" data-p="' + p.id + '">' + n + ' 条，去对话里</button>' : '<span class="y20-muted">无</span>'; } },
        { label: '状态', render: (p) => Y20.marker(p) }
      ],
      rows: Y20.W().projects, empty: '还没有项目'
    });
    return ui.block({ id: 'home-projects', title: '项目', subtitle: '每个项目一行；点项目名进入项目',
      actions: ui.button({ label: '新建项目', kind: 'small primary', act: 'np.new', icon: 'plus' }) + ui.button({ label: '接入已有项目', kind: 'small', act: 'np.attach', icon: 'import' }), body: table });
  }

  // 关键事实：询问与回答、返工、放行、采纳、故障与等待，按时间倒排；点一条跳到那件事项的时序图，不属于某件事项的点开看那条事件
  const KEY_FACTS = ['询问', '回答', '缺陷记录', '放行', '采纳', '开环完成', '模型服务失败', '动作结果未知'];
  function factsHtml() {
    const w = Y20.W();
    const facts = w.events.filter((e) => e.at >= w.report.last_seen && KEY_FACTS.includes(e.type)).sort((a, b) => b.at.localeCompare(a.at)).slice(0, 12);
    if (!facts.length) return '';
    const row = (e) => {
      const p = H.project(e.project), it = p && e.item && H.item(p, e.item);
      const text = '<span class="y20-muted">' + timeAt(e.at) + '</span> <b>' + esc(p ? p.name : '') + '</b> ' + H.t(e.project, e.label);
      return '<li>' + (it ? '<button type="button" class="y20-report-fact" data-go="#/p/' + p.id + '?item=' + it.id + '&seq=1">' + text + '</button>' : '<span class="y20-report-fact is-plain">' + text + ' ' + H.src(e.pos) + '</span>') + '</li>';
    };
    return '<h3 class="y20-h3">关键事实</h3><p class="y20-muted y20-small">点一条跳到那件事项的时序图；要回到某一刻看当时的样子用画面的回放。</p><ul class="y20-report-facts">' + facts.map(row).join('') + '</ul>';
  }

  function reportBlock() {
    const r = Y20.W().report;
    const items = r.summary.map((it) => {
      const open = openItem === it.id;
      let detail = '';
      if (open) {
        const evs = it.refs.map((pos) => H.event(pos)).filter(Boolean).map((e) =>
          '<li><span class="y20-muted">' + timeAt(e.at) + '</span> ' + H.t(e.project, e.label) + ' ' + H.src(e.pos) + '</li>').join('');
        detail = (it.rows ? '<ul class="y20-report-detail-list">' + it.rows.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul>' : '') +
          '<p class="y20-small y20-muted y20-report-from">来源事件：</p><ul class="y20-source-list">' + evs + '</ul>';
      }
      return '<div class="y20-report-item' + (open ? ' is-open' : '') + '"><button type="button" class="y20-report-head" data-act="report-item" data-id="' + it.id + '">' +
        '<span class="y20-report-label">' + esc(it.label) + '' + '</span>' +
        '<span class="y20-report-value">' + it.value + '<small>' + esc(it.unit) + '</small></span><span class="y20-report-detail">' + esc(it.detail) + '</span></button>' + detail + '</div>';
    }).join('');
    return ui.block({
      id: 'home-report', title: '离开期间的报告', subtitle: '上次查看：' + ui.time(r.last_seen) + '（' + H.waited(r.last_seen) + '以前）。点一项看明细和来源事件',
      actions: ui.button({ label: '已看过', kind: 'small primary', act: 'report-seen' }),
      body: '<div class="y20-report-items">' + items + '</div>' + factsHtml()
    });
  }

  Y20.views.register('home', {
    render() {
      return '<div class="y20-home">' +
        '<div class="y20-stats" aria-label="状态项">' + Y20.statusItems().map((i) => Y20.statItem(i, false)).join('') + '</div>' +
        ui.block({ id: 'home-decisions', title: '待你决定', subtitle: '跨项目，按发出时间排列', body: Y20.cards.list(null) }) +
        reportBlock() + projectsBlock() + '</div>';
    }
  });
  Y20.actions.register('report-item', (el) => { openItem = openItem === el.dataset.id ? null : el.dataset.id; Y20.rerender(); });
  Y20.actions.register('report-seen', () => ui.toast('已把现在记为上次查看的位置', 'ok'));

  // ---------------------------------------------------------------- 单条事件

  Y20.views.register('event', {
    render(ctx) {
      const e = H.event(ctx.route.params.pos);
      if (!e) return '<div class="y20-gate"><h1>找不到这条事件</h1><p class="y20-muted">位置 #' + esc(ctx.route.params.pos) + ' 不在当前场景里。</p></div>';
      const sk = Y20.SOURCE_KINDS[e.source];
      const p = e.project && H.project(e.project), it = p && e.item && H.item(p, e.item);
      H.ctxOverride = e.project || null;
      const d = e.detail;
      const diff = d ? '<h3 class="y20-h3">' + (d.type === 'diff' ? '差异' : '回执') + '</h3>' + ui.pre(d.lines.join('\n')) : '<h3 class="y20-h3">差异与回执</h3><p class="y20-muted">这条事件没有附带差异或回执。</p>';
      return '<div class="y20-page"><div class="y20-page-head"><div class="y20-page-titles"><h1>按位置看一条事件 <span class="y20-muted">#' + e.pos + '</span></h1></div>' +
        '<div class="y20-page-actions">' + ui.button({ label: '返回', act: 'back', icon: 'back' }) + '</div></div>' +
        ui.block({ body: ui.kv([
          ['说明', esc(e.label)], ['种类', ui.tag(e.type)],
          ['来源种类', '<span class="y20-source-kind is-' + e.source + '">' + esc(sk[0]) + '</span> <span class="y20-muted y20-small">' + esc(sk[1]) + '</span>'],
          ['提出者', esc(e.by)], ['时间', esc(ui.time(e.at))], ['位置', '#' + e.pos],
          ['项目 · 事项', p ? H.link('#/p/' + p.id, p.name) + (it ? ' · ' + H.link('#/p/' + p.id + '?item=' + it.id, it.title) : '') : '—']
        ], 'is-rows y20-ev-kv') + diff }) + '</div>';
    }
  });
  Y20.actions.register('back', () => history.back());
})();
