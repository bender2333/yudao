// 页面：首页（项目一览、待你决定、离开期间的报告）、项目概览、事项、成果库、流转、时间轴、按位置看一条事件
(function () {
  'use strict';
  const Y15 = window.Y15;
  const esc = Y15.esc;
  const H = Y15.h;
  const ui = Y15.ui;

  const who = (id) => (id === 'user' ? '你' : id === 'output' ? '成果库' : H.dept(id));
  const kindName = (k) => Y15.OUTCOME_KINDS[k];
  const conclStatus = (c) => {
    if (!c) return '';
    const map = { release: 'released', defect: 'failed', open: 'held', waiting: 'running' };
    return ui.status(map[c.kind], c.text);
  };
  const timeAt = (iso) => esc(ui.time(iso));

  // ---------------------------------------------------------------- 首页

  let openItem = null;

  function nowDoing(p) {
    const lines = p.depts.map((d) => ({ s: p.deptState[d], d })).filter((x) => x.s.state !== 'idle');
    if (!lines.length) return '<span class="y15-muted">没有在做的事</span>';
    return '<div class="y15-cell-stack">' + lines.map((x) => '<span>' + (p.depts.length > 1 ? '<b>' + esc(H.dept(x.d)) + '</b>：' : '') + esc(x.s.text) + '</span>').join('') + '</div>';
  }

  function whereItems(p) {
    const live = p.items.filter((i) => !['adopted', 'open_closed', 'stopped'].includes(i.status));
    if (!live.length) return '<span class="y15-muted">没有进行中的事项</span>';
    return '<div class="y15-cell-stack">' + live.map((i) => '<span>' + H.dot(i) + ' ' + esc(i.title) + ' <span class="y15-muted">· ' + esc(i.dept ? H.dept(i.dept) : '排队') + '</span></span>').join('') + '</div>';
  }

  function slotCell(p) {
    const w = p.items.filter((i) => i.status === 'waiting_slot');
    const base = '占用 ' + p.slots.used + ' / ' + p.slots.limit;
    return w.length
      ? '<div class="y15-cell-stack"><span class="y15-warn-text">有 ' + w.length + ' 个事项在等执行槽位</span><small class="y15-muted">' + base + '；' + esc(w.map((i) => i.title).join('、')) + ' 已等 ' + esc(H.waited(w[0].since)) + '</small></div>'
      : '<div class="y15-cell-stack"><span>没有事项在等</span><small class="y15-muted">' + base + '</small></div>';
  }

  function projectsBlock() {
    const table = ui.table({
      columns: [
        { label: '项目', render: (p) => H.link('#/p/' + p.id, p.name) + ' ' + ui.tag(p.mode) },
        { label: '此刻在做什么', render: nowDoing },
        { label: '事项在哪个部门', render: whereItems },
        { label: '执行槽位', render: slotCell },
        { label: '待你决定', render: (p) => { const n = H.decisions(p.id).length; return n ? '<span class="y15-count is-decide">' + n + '</span>' : '<span class="y15-muted">无</span>'; } },
        { label: '状态', render: (p) => Y15.marker(p) }
      ],
      rows: Y15.W().projects, empty: '还没有项目'
    });
    return ui.block({ id: 'home-projects', title: '项目', subtitle: '每个项目一行；点项目名进入项目', body: table });
  }

  function reportBlock() {
    const r = Y15.W().report;
    const items = r.summary.map((it) => {
      const open = openItem === it.id;
      let detail = '';
      if (open) {
        const evs = it.refs.map((pos) => H.event(pos)).filter(Boolean).map((e) =>
          '<li><span class="y15-muted">' + timeAt(e.at) + '</span> ' + esc(e.label) + ' ' + H.src(e.pos) + '</li>').join('');
        detail = (it.rows ? '<ul class="y15-report-detail-list">' + it.rows.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul>' : '') +
          '<p class="y15-small y15-muted y15-report-from">来源事件：</p><ul class="y15-source-list">' + evs + '</ul>';
      }
      return '<div class="y15-report-item' + (open ? ' is-open' : '') + '"><button type="button" class="y15-report-head" data-act="report-item" data-id="' + it.id + '">' +
        '<span class="y15-report-label">' + esc(it.label) + (it.isNew ? ' ' + ui.tag('新增', 'new') : '') + '</span>' +
        '<span class="y15-report-value">' + it.value + '<small>' + esc(it.unit) + '</small></span><span class="y15-report-detail">' + esc(it.detail) + '</span></button>' + detail + '</div>';
    }).join('');
    return ui.block({
      id: 'home-report', title: '离开期间的报告', subtitle: '上次查看：' + ui.time(r.last_seen) + '（' + H.waited(r.last_seen) + '以前）。点一项看明细和来源事件',
      actions: ui.button({ label: '已看过', kind: 'small primary', act: 'report-seen' }),
      body: '<div class="y15-report-items">' + items + '</div>'
    });
  }

  Y15.views.register('home', {
    render() {
      return '<div class="y15-home">' +
        '<div class="y15-stats" aria-label="状态项">' + Y15.statusItems().map((i) => Y15.statItem(i, false)).join('') + '</div>' +
        ui.block({ id: 'home-decisions', title: '待你决定', subtitle: '跨项目，按发出时间排列', body: Y15.cards.list(null) }) +
        projectsBlock() + reportBlock() + '</div>';
    }
  });
  Y15.actions.register('report-item', (el) => { openItem = openItem === el.dataset.id ? null : el.dataset.id; Y15.rerender(); });
  Y15.actions.register('report-seen', () => ui.toast('已把现在记为上次查看的位置', 'ok'));

  // ---------------------------------------------------------------- 项目概览

  function itemsTable(p) {
    return ui.table({
      columns: [
        { label: '事项', render: (i) => H.dot(i) + ' <span class="y15-door">' + esc(i.door) + '</span> ' + H.src('door-' + i.id) + '<br>' + H.link('#/p/' + p.id + '/w/' + i.id, i.title) },
        { label: '所在部门', render: (i) => (i.dept ? esc(H.dept(i.dept)) : '<span class="y15-muted">' + (i.status === 'adopted' || i.status === 'open_closed' ? '已结束' : '排队，还没有部门') + '</span>') },
        { label: '状态与原因', render: (i) => '<div class="y15-cell-stack">' + H.status(i) + '<small class="y15-muted">' + esc(i.reason) + '</small>' + (i.progress ? '<small>' + esc(i.progress) + '</small>' : '') + '</div>' + H.src('status-' + i.id) },
        { label: '轮次', render: (i) => (i.round ? '第 ' + i.round + ' 轮 / 上限 ' + i.round_limit + ' ' + H.src('round-' + i.id) : '<span class="y15-muted">还没开始</span>') },
        { label: '已用 / 上限', render: (i) => esc(H.dur(i.used)) + ' / ' + esc(H.dur(i.limit)) + ui.meter(i.used, i.limit) }
      ],
      rows: p.items, empty: '这个项目还没有事项'
    });
  }

  function deptTable(p) {
    const rows = p.depts.map((d) => Object.assign({ id: d }, p.deptState[d]));
    const iconOf = { running: 'running', idle: 'idle', waiting_provider: 'waiting_provider', interrupted: 'interrupted', waiting_work: 'waiting' };
    const label = { running: '工作中', idle: '空闲', waiting_provider: '等待模型服务', interrupted: '中断', waiting_work: '等待工作' };
    return ui.table({
      columns: [
        { label: '部门', render: (r) => H.link('#/p/' + p.id + '/dept/' + r.id, H.dept(r.id)) + '<br><small class="y15-muted">' + esc(r.role) + '</small>' },
        { label: '状态', render: (r) => ui.status(iconOf[r.state], label[r.state]) },
        { label: '在做什么', render: (r) => esc(r.text) + ' ' + H.src('dept-' + p.id + '-' + r.id) },
        { label: '原因', render: (r) => esc(r.reason) + (r.progress ? '<br><small class="y15-muted">' + esc(r.progress) + '</small>' : '') },
        { label: '在等什么 · 等了多久', render: (r) => (r.waits.length ? '<div class="y15-cell-stack">' + r.waits.map((w) => {
          const it = H.item(p, w.item);
          return '<span>' + (it ? H.dot(it) + ' ' : '') + esc(w.on) + ' <span class="y15-warn-text">' + esc(H.waited(w.since)) + '</span></span>';
        }).join('') + '</div>' : '<span class="y15-muted">不在等</span>') }
      ],
      rows
    });
  }

  function asksTable(p, asks) {
    return ui.table({
      columns: [
        { label: '谁问谁', render: (a) => esc(H.dept(a.from)) + ' → ' + esc(H.dept(a.to)) },
        { label: '事项', render: (a) => { const it = H.item(p, a.item); return it ? H.dot(it) + ' ' + esc(it.title) : ''; } },
        { label: '问题', render: (a) => esc(a.text) + ' ' + H.src(a.key) },
        { label: '已等待', render: (a) => esc(H.waited(a.at)) }
      ],
      rows: asks, empty: '没有进行中的询问'
    });
  }

  function interruptTable(p, rows) {
    return ui.table({
      columns: [
        { label: '事项', render: (r) => { const it = H.item(p, r.item); return H.dot(it) + ' ' + esc(it.title); } },
        { label: '被打断的工作', render: (r) => esc(r.what) },
        { label: '什么时候 · 为什么', render: (r) => esc(ui.time(r.at)) + '，' + esc(r.why) + ' ' + H.src(r.key) },
        { label: '现在', render: (r) => ui.status('interrupted', r.state) }
      ],
      rows, empty: '没有中断，也没有待恢复的工作'
    });
  }

  function providerBlock(p) {
    return p.provider_wait.length
      ? ui.table({
        columns: [
          { label: '部门 · 事项', render: (w) => { const it = H.item(p, w.item); return esc(H.dept(w.dept)) + ' · ' + H.dot(it) + ' ' + esc(it.title); } },
          { label: '模型', render: (w) => ui.code(w.model) },
          { label: '失败的分类', render: (w) => esc(w.category) + ' ' + H.src('provider-' + w.item) },
          { label: '重试', render: (w) => '第 ' + w.attempt + ' 次，共 ' + w.of + ' 次；下一次 ' + esc(ui.time(w.next)) },
          { label: '已等', render: (w) => esc(H.waited(w.since)) }
        ],
        rows: p.provider_wait
      })
      : ui.empty('没有在等待模型服务');
  }

  function pairs(p) {
    const m = {};
    p.outcomes.forEach((o) => {
      if (o.from === o.to) return;
      const k = o.from + '>' + o.to;
      m[k] = m[k] || { from: o.from, to: o.to, n: 0, rework: 0, kinds: {} };
      m[k].n += 1;
      if (o.kind === 'defect') m[k].rework += 1;
      m[k].kinds[kindName(o.kind)] = (m[k].kinds[kindName(o.kind)] || 0) + 1;
    });
    return Object.values(m);
  }
  function pairsTable(p) {
    return ui.table({
      columns: [
        { label: '从 → 到', render: (r) => esc(who(r.from)) + ' → ' + esc(who(r.to)) },
        { label: '流转次数', render: (r) => r.n },
        { label: '其中返工', render: (r) => (r.rework ? '<span class="y15-warn-text">' + r.rework + '（缺陷记录退回）</span>' : '<span class="y15-muted">0</span>') },
        { label: '都是些什么', render: (r) => esc(Object.keys(r.kinds).map((k) => k + ' ' + r.kinds[k]).join('、')) }
      ],
      rows: pairs(p), empty: '还没有流转'
    });
  }

  function summaryKv(p) {
    const doing = p.depts.map((d) => p.deptState[d]).filter((s) => s.state !== 'idle');
    const w = p.items.filter((i) => i.status === 'waiting_slot');
    return ui.kv([
      ['此刻在做什么', doing.length ? doing.map((s) => esc(s.text)).join('；') : '没有在做的事'],
      ['项目已用时间 / 上限', esc(H.dur(p.elapsed.used)) + ' / ' + esc(H.dur(p.elapsed.limit)) + ' ' + H.src(p.elapsed.key) + ui.meter(p.elapsed.used, p.elapsed.limit)],
      ['执行槽位', '占用 ' + p.slots.used + ' / ' + p.slots.limit + (w.length ? '，<span class="y15-warn-text">' + w.length + ' 个事项在等</span>' : '，没有事项在等')],
      ['定义', esc(p.mode) + (p.verifier ? '，有核验角色（质检）' : '，没有核验角色：事项以开环完成结束')]
    ], 'y15-card-kv');
  }

  Y15.views.register('overview', {
    render(ctx, p) {
      const dn = H.decisions(p.id).length;
      return '<div class="y15-page"><div class="y15-page-head"><div class="y15-page-titles"><h1>' + esc(p.name) + '</h1><p class="y15-muted">' + esc(p.goal) + '</p></div></div>' +
        ui.block({ title: '此刻', body: summaryKv(p) }) +
        (dn ? ui.block({ id: 'home-decisions', title: '待你决定', body: Y15.cards.list(p.id) }) : '') +
        ui.block({ title: '事项', subtitle: '点事项名看这个事项在各部门的情况', body: itemsTable(p) }) +
        ui.block({ title: '部门', subtitle: '各部门的状态、原因、在等什么、等了多久；点部门名进入部门', body: deptTable(p) }) +
        ui.block({ title: '进行中的询问', body: asksTable(p, p.asks) }) +
        ui.block({ title: '中断与待恢复', subtitle: '整个项目里被打断、等待恢复的工作', body: interruptTable(p, p.interruptions) }) +
        ui.block({ title: '等待模型服务', body: providerBlock(p) }) +
        ui.block({ title: '流转汇总', subtitle: '每对部门之间流转了几次，其中多少次是返工；逐条记录在「流转」页', body: pairsTable(p) }) + '</div>';
    }
  });

  // ---------------------------------------------------------------- 事项

  Y15.views.register('item', {
    render(ctx, p) {
      const it = H.item(p, ctx.route.params.item);
      if (!it) return '<div class="y15-gate"><h1>找不到事项</h1></div>';
      const depts = p.depts.map((d) => {
        const s = p.deptState[d];
        return { d, mine: s.items.includes(it.id), wait: s.waits.find((w) => w.item === it.id) };
      });
      const deptsTable = ui.table({
        columns: [
          { label: '部门', render: (r) => H.link('#/p/' + p.id + '/dept/' + r.d, H.dept(r.d)) },
          { label: '和这个事项的关系', render: (r) => (r.mine ? (it.dept === r.d ? '事项现在在这个部门' : '参与中') : '<span class="y15-muted">不在手上</span>') },
          { label: '在等什么 · 等了多久', render: (r) => (r.wait ? esc(r.wait.on) + ' <span class="y15-warn-text">' + esc(H.waited(r.wait.since)) + '</span>' : '<span class="y15-muted">不在等</span>') }
        ], rows: depts
      });
      const mine = H.decisions(p.id).filter((d) => d.item === it.id);
      return '<div class="y15-page"><div class="y15-page-head"><div class="y15-page-titles"><h1>' + H.dot(it) + ' ' + esc(it.title) + '</h1><p class="y15-muted">门牌 ' + esc(it.door) + ' ' + H.src('door-' + it.id) + '</p></div><div class="y15-page-actions">' + ui.button({ label: '恢复与动作核实', kind: 'small', go: '#/p/' + p.id + '/w/' + it.id + '/recovery' }) + ui.button({ label: '资料', kind: 'small', go: '#/p/' + p.id + '/materials?w=' + it.id }) + '</div></div>' +
        ui.block({ title: '此刻', body: ui.kv([
          ['状态', H.status(it) + ' ' + H.src('status-' + it.id)], ['原因', esc(it.reason)], it.progress ? ['进度', esc(it.progress)] : null, ['所在部门', esc(it.dept ? H.dept(it.dept) : '—')],
          ['轮次', it.round ? '第 ' + it.round + ' 轮 / 上限 ' + it.round_limit + ' ' + H.src('round-' + it.id) : '还没开始'],
          ['已用 / 上限', esc(H.dur(it.used)) + ' / ' + esc(H.dur(it.limit)) + ui.meter(it.used, it.limit)]
        ], 'y15-card-kv') }) +
        (mine.length ? ui.block({ title: '待你决定', body: '<div class="y15-cards">' + mine.map((d) => Y15.cards.one(d)).join('') + '</div>' }) : '') +
        ui.block({ title: '各部门', body: deptsTable }) +
        ui.block({ title: '这个事项的询问', body: asksTable(p, p.asks.filter((a) => a.item === it.id)) }) +
        ui.block({ title: '中断', body: interruptTable(p, p.interruptions.filter((r) => r.item === it.id)) }) +
        ui.block({ title: '成果与结论', body: outcomesTable(p.outcomes.filter((o) => o.item === it.id)) }) + '</div>';
    }
  });

  // ---------------------------------------------------------------- 成果库与流转

  function outcomesTable(rows) {
    return ui.table({
      columns: [
        { label: '种类', render: (o) => '<span class="y15-okind is-' + o.kind + '">' + esc(kindName(o.kind)) + '</span>' + (o.version ? ' <small class="y15-muted">第 ' + o.version + ' 版</small>' : '') },
        { label: '内容', render: (o) => esc(o.text) },
        { label: '谁提出', render: (o) => esc(o.from === 'output' ? '系统' : who(o.from)) },
        { label: '时间', render: (o) => timeAt(o.at) },
        { label: '结论', render: (o) => conclStatus(o.concl) || '<span class="y15-muted">—</span>' },
        { label: '来源', render: (o) => H.src(o.id) }
      ],
      rows, empty: '成果库里还没有成果'
    });
  }

  Y15.views.register('outcomes', {
    render(ctx, p) {
      const n = (k) => p.outcomes.filter((o) => o.concl && o.concl.kind === k).length;
      const groups = p.items.map((it) => {
        const rows = p.outcomes.filter((o) => o.item === it.id);
        return rows.length ? '<h3 class="y15-h3">' + H.dot(it) + ' ' + esc(it.title) + ' ' + H.status(it) + '</h3>' + outcomesTable(rows) : '';
      }).join('');
      return '<div class="y15-page"><div class="y15-page-head"><div class="y15-page-titles"><h1>成果库</h1><p class="y15-muted">这个项目里所有成果，和每份交付得到的结论</p></div></div>' +
        ui.block({ title: '结论分开看', body: '<div class="y15-concl-row">' +
          '<div class="y15-concl">' + ui.status('released', '放行') + '<b>' + n('release') + '</b><small>独立核验过的交付</small></div>' +
          '<div class="y15-concl">' + ui.status('failed', '缺陷记录') + '<b>' + n('defect') + '</b><small>核验没过，退回去返工</small></div>' +
          '<div class="y15-concl">' + ui.status('held', '开环完成') + '<b>' + n('open') + '</b><small>没有核验角色，直接采纳，不是放行</small></div></div>' +
          (p.verifier ? '' : ui.note('这个项目的定义里没有核验角色，所以交付都以开环完成结束，不会出现放行。', 'info')) }) +
        ui.block({ title: '成果与结论', body: groups || ui.empty('成果库里还没有成果') }) + '</div>';
    }
  });

  Y15.views.register('flow', {
    render(ctx, p) {
      const rows = p.outcomes.slice().sort((a, b) => b.at.localeCompare(a.at));
      return '<div class="y15-page"><div class="y15-page-head"><div class="y15-page-titles"><h1>流转</h1><p class="y15-muted">成果在部门之间的流转：每种成果一条记录</p></div></div>' +
        ui.block({ title: '汇总', body: pairsTable(p) }) +
        ui.block({ title: '流转记录', subtitle: '用户输入、PRD、交付、缺陷记录、询问、回答、放行、采纳；没有核验角色的项目是开环完成', body: ui.table({
          columns: [
            { label: '时间', render: (o) => timeAt(o.at) },
            { label: '种类', render: (o) => '<span class="y15-okind is-' + o.kind + '">' + esc(kindName(o.kind)) + '</span>' },
            { label: '从 → 到', render: (o) => esc(who(o.from)) + ' → ' + esc(who(o.to)) },
            { label: '事项', render: (o) => { const it = H.item(p, o.item); return H.dot(it) + ' ' + esc(it.title); } },
            { label: '内容', render: (o) => esc(o.text) },
            { label: '来源', render: (o) => H.src(o.id) }
          ], rows }) }) + '</div>';
    }
  });

  // ---------------------------------------------------------------- 时间轴与单条事件

  Y15.views.register('timeline', {
    render(ctx, p) {
      const at = ctx.route.query.at ? Number(ctx.route.query.at) : null;
      const evs = Y15.W().events.filter((e) => e.project === p.id).sort((a, b) => a.pos - b.pos);
      const rows = evs.map((e) => {
        const it = e.item && H.item(p, e.item);
        return '<li class="y15-tl-row' + (e.pos === at ? ' is-target' : '') + '"><span class="y15-tl-pos">#' + e.pos + '</span><span class="y15-tl-time">' + timeAt(e.at) + '</span>' +
          '<span class="y15-tl-main">' + (it ? H.dot(it) + ' ' : '') + ui.tag(e.type) + ' ' + esc(e.label) + '</span>' + H.src(e.pos) +
          '<button type="button" class="y15-link y15-small" data-go="#/event/' + e.pos + '">详情</button></li>';
      }).join('');
      return '<div class="y15-page"><div class="y15-page-head"><div class="y15-page-titles"><h1>时间轴</h1><p class="y15-muted">这个项目的全部事件，按位置排列。' + (at ? '已定位到 #' + at + '。' : '') + '</p></div></div>' +
        ui.block({ body: '<ol class="y15-tl">' + rows + '</ol>' }) + '</div>';
    }
  });

  Y15.views.register('event', {
    render(ctx) {
      const e = H.event(ctx.route.params.pos);
      if (!e) return '<div class="y15-gate"><h1>找不到这条事件</h1><p class="y15-muted">位置 #' + esc(ctx.route.params.pos) + ' 不在当前场景里。</p></div>';
      const sk = Y15.SOURCE_KINDS[e.source];
      const p = e.project && H.project(e.project), it = p && e.item && H.item(p, e.item);
      const d = e.detail;
      const diff = d ? '<h3 class="y15-h3">' + (d.type === 'diff' ? '差异' : '回执') + '</h3>' + ui.pre(d.lines.join('\n')) : '<h3 class="y15-h3">差异与回执</h3><p class="y15-muted">这条事件没有附带差异或回执。</p>';
      return '<div class="y15-page"><div class="y15-page-head"><div class="y15-page-titles"><h1>按位置看一条事件 <span class="y15-muted">#' + e.pos + '</span></h1></div>' +
        '<div class="y15-page-actions">' + (p ? ui.button({ label: '在时间轴上查看', kind: 'primary', go: '#/p/' + p.id + '/timeline?at=' + e.pos, icon: 'step' }) : '') +
        ui.button({ label: '返回', act: 'back', icon: 'back' }) + '</div></div>' +
        ui.block({ body: ui.kv([
          ['说明', esc(e.label)], ['种类', ui.tag(e.type)],
          ['来源种类', '<span class="y15-source-kind is-' + e.source + '">' + esc(sk[0]) + '</span> <span class="y15-muted y15-small">' + esc(sk[1]) + '</span>'],
          ['提出者', esc(e.by)], ['时间', esc(ui.time(e.at))], ['位置', '#' + e.pos],
          ['项目 · 事项', p ? H.link('#/p/' + p.id, p.name) + (it ? ' · ' + H.link('#/p/' + p.id + '/w/' + it.id, it.title) : '') : '—']
        ], 'is-rows y15-ev-kv') + diff }) + '</div>';
    }
  });
  Y15.actions.register('back', () => history.back());
})();
