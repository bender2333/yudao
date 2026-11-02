// 系统页：机器、运行与执行槽位、工具与扩展、预留入口。机器、排空等只在内存里改，刷新页面回到原样
(function () {
  'use strict';
  const Y15 = window.Y15;
  const esc = Y15.esc;
  const ui = Y15.ui;
  const H = Y15.h;
  const X = Y15.EXTRA;

  const stack = (...lines) => '<div class="y15-cell-stack">' + lines.join('') + '</div>';
  const pname = (id) => { const p = H.project(id); return p ? p.name : id; };

  // ---------------------------------------------------------------- 机器

  let machines = X.machines();
  Y15.machineList = () => machines;
  let editing = null;

  function runningActions(m) {
    const out = [];
    const rp = H.project('report');
    if (m.id === 'test-01' && rp && rp.remote) rp.remote.engineering.forEach((r) => out.push({ unknown: true, text: pname('report') + ' · 工程 · ' + r.action }));
    const d = Y15.W().desktop;
    if (m.id === 'desk-01' && d) out.push({ unknown: false, text: pname(d.project) + ' · 质检 · ' + d.what });
    return out;
  }

  Y15.views.register('sys-machines', {
    render() {
      const table = ui.table({
        columns: [
          { label: '名称', render: (m) => stack('<strong>' + esc(m.name) + '</strong>', '<small class="y15-muted">' + esc(m.kind) + '</small>') },
          { label: '地址', render: (m) => ui.code(m.address) },
          { label: '用途', render: (m) => esc(m.purpose) },
          { label: '状态', render: (m) => stack(m.online ? ui.status('running', '在线') : ui.status('offline', '离线'), '<small class="y15-muted">最近心跳 ' + esc(ui.time(m.beat)) + '</small>') },
          { label: '正在执行的动作', render: (m) => { const a = runningActions(m); return a.length ? stack.apply(null, a.map((x) => ui.status(x.unknown ? 'unknown' : 'running', x.unknown ? '结果未知' : '执行中') + '<span>' + esc(x.text) + '</span>')) : '<span class="y15-muted">没有动作</span>'; } },
          { label: '授权使用它的项目', render: (m) => (m.projects.length ? esc(m.projects.map(pname).join('、')) : '<span class="y15-muted">没有授权的项目</span>') },
          { label: '操作', className: 'y15-col-actions', render: (m) => ui.button({ label: '修改', kind: 'small', act: 'machines.edit', data: { id: m.id } }) }
        ],
        rows: machines
      });
      return '<div class="y15-page"><div class="y15-page-head"><div class="y15-page-titles"><h1>机器</h1><p class="y15-muted">登记以后由执行代理报到；心跳超时的机器上，动作的结果是未知的</p></div></div>' +
        ui.block({ title: '机器', subtitle: '每个项目单独授权使用哪台机器，在项目的设置里', actions: ui.button({ label: '登记机器', kind: 'small primary', act: 'machines.new' }), body: table }) +
        form() + '</div>';
    }
  });

  function form() {
    if (!editing) return '';
    const m = editing === 'new' ? null : machines.find((x) => x.id === editing);
    return ui.block({
      id: 'machine-form', title: m ? '修改「' + m.name + '」' : '登记机器',
      body: '<div class="y15-form"><label class="y15-field"><span>名称</span><input class="y15-input" id="mc-name" value="' + esc(m ? m.name : '') + '"></label>' +
        '<label class="y15-field"><span>地址</span><input class="y15-input" id="mc-address" value="' + esc(m ? m.address : '') + '" placeholder="例如 192.168.1.50:8800"></label>' +
        '<label class="y15-field"><span>用途</span><input class="y15-input" id="mc-purpose" value="' + esc(m ? m.purpose : '') + '"></label>' +
        '<label class="y15-field"><span>认证</span><input class="y15-input" value="执行代理的认证方式还没有设计" disabled></label>' +
        '<div class="y15-row">' + ui.button({ label: m ? '保存' : '登记', kind: 'primary', act: 'machines.save' }) + ui.button({ label: '取消', act: 'machines.cancel' }) + '</div></div>'
    });
  }

  Y15.actions.register('machines.new', () => { editing = 'new'; Y15.rerender(); });
  Y15.actions.register('machines.edit', (el) => { editing = el.dataset.id; Y15.rerender(); });
  Y15.actions.register('machines.cancel', () => { editing = null; Y15.rerender(); });
  Y15.actions.register('machines.save', () => {
    const v = (id) => document.getElementById(id).value.trim();
    if (!v('mc-name') || !v('mc-address')) { ui.toast('名称和地址都要填', 'warn'); return; }
    if (editing === 'new') machines.push({ id: 'm-' + (machines.length + 1), name: v('mc-name'), kind: '电脑', address: v('mc-address'), purpose: v('mc-purpose'), online: false, beat: null, projects: [] });
    else { const m = machines.find((x) => x.id === editing); Object.assign(m, { name: v('mc-name'), address: v('mc-address'), purpose: v('mc-purpose') }); }
    editing = null;
    ui.toast('已保存', 'ok');
    Y15.rerender();
  });

  // ---------------------------------------------------------------- 运行与执行槽位

  let drain = { state: 'none', since: null };

  function slotsBlock() {
    const projects = Y15.W().projects;
    const table = ui.table({
      columns: [
        { label: '项目', render: (p) => H.link('#/p/' + p.id, p.name) },
        { label: '占用 / 上限', render: (p) => '<span class="y15-lamps">' + Array.from({ length: p.slots.limit }, (_, i) => '<span class="y15-lamp' + (i < p.slots.used ? ' is-on' : '') + '" title="' + (i < p.slots.used ? '已占用' : '空闲') + '"></span>').join('') + '</span> <b>' + p.slots.used + ' / ' + p.slots.limit + '</b>' },
        { label: '正在占用的事项', render: (p) => { const ids = X.slotHolders[p.id] || []; return ids.length ? stack.apply(null, ids.map((id) => { const it = H.item(p, id); return '<span>' + H.dot(it) + ' ' + esc(it.title) + ' <small class="y15-muted">· ' + esc(it.dept ? H.dept(it.dept) : '') + ' · 已用 ' + esc(H.dur(it.used)) + ' / ' + esc(H.dur(it.limit)) + '</small></span>'; })) : '<span class="y15-muted">没有</span>'; } },
        { label: '槽位数', render: (p) => '<select class="y15-select" id="slots-' + p.id + '">' + [1, 2, 3, 4, 5, 6].map((n) => '<option' + (n === p.slots.limit ? ' selected' : '') + '>' + n + '</option>').join('') + '</select> ' + ui.button({ label: '设置', kind: 'small', act: 'runtime.setSlots', data: { id: p.id } }) }
      ],
      rows: projects
    });
    const queue = [];
    projects.forEach((p) => p.items.filter((i) => i.status === 'waiting_slot').forEach((i) => queue.push({ p, i })));
    const qt = ui.table({
      columns: [
        { label: '位置', render: (r) => '<span class="y15-ticket">' + (queue.indexOf(r) + 1) + '</span>' },
        { label: '等待中的事项', render: (r) => stack('<strong>' + H.dot(r.i) + ' ' + esc(r.i.title) + '</strong>', '<small class="y15-muted">' + esc(r.p.name) + '</small>') },
        { label: '等待', render: (r) => esc(ui.time(r.i.since)) + '<small class="y15-muted y15-block-line">已等 ' + esc(H.waited(r.i.since)) + '</small>' },
        { label: '为什么在排队', render: () => ui.tag('等执行槽位') },
        { label: '操作', className: 'y15-col-actions', render: (r) => ui.button({ label: '取消排队', kind: 'small danger', act: 'runtime.cancelQueue', data: { p: r.p.id, i: r.i.id } }) }
      ],
      rows: queue, empty: '队列是空的'
    });
    return ui.block({
      title: '执行槽位', subtitle: '同时能有几个事项在执行；占满以后，新的事项排队，空出一个就按顺序开始',
      body: table + '<h3 class="y15-h3">排队中的事项</h3>' + qt + ui.note('服务重启以后，排队中的事项按原来的顺序重新排队。')
    });
  }

  function drainBlock() {
    const running = [];
    Y15.W().projects.forEach((p) => p.items.filter((i) => i.status === 'working').forEach((i) => running.push({ p, i })));
    const label = { none: '没有排空', draining: '排空中', forced: '已强制升级' }[drain.state];
    const actions = (drain.state === 'none' ? ui.button({ label: '开始排空', kind: 'primary', act: 'runtime.drain' }) : '') +
      (drain.state === 'draining' ? ui.button({ label: '强制升级', kind: 'danger', act: 'runtime.force' }) : '') + (drain.state !== 'none' ? ui.button({ label: '撤销', act: 'runtime.undrain' }) : '');
    return ui.block({
      title: '排空', subtitle: '升级之前先排空：不再开始新的事项，等正在进行的运行结束。强制升级时，正在进行的运行记为「因升级停止」，对应的事项从项目的起点重新开始，排在队列最前面。',
      body: ui.kv([['状态', esc(label)], ['开始时间', drain.since ? esc(ui.time(drain.since)) : ''], ['正在进行的运行', running.length + ' 个']]) +
        (running.length ? '<ul class="y15-list">' + running.map((r) => '<li>' + H.dot(r.i) + ' ' + esc(r.i.title) + ' <small class="y15-muted">' + esc(r.p.name) + '</small> ' + ui.status('running', '进行中') + '</li>').join('') + '</ul>' : '<p class="y15-muted">没有正在进行的运行。</p>') +
        '<div class="y15-row">' + actions + '</div>'
    });
  }

  function retentionBlock() {
    const d = X.disk;
    const total = d.free_gb + d.snapshots_gb + d.workspaces_gb;
    const used = d.snapshots_gb + d.workspaces_gb;
    return ui.block({
      id: 'runtime-retention', title: '数据保留', subtitle: '可用空间低于提示阈值时，首页的状态项「磁盘空间」会亮起',
      body: ui.kv([['磁盘可用空间', Y15.num(d.free_gb) + ' GB' + (d.free_gb < d.threshold_gb ? ui.status('failed', '低于提示阈值') : '')], ['提示阈值', d.threshold_gb + ' GB'], ['交付快照占用', d.snapshots_gb + ' GB'], ['工作区占用', d.workspaces_gb + ' GB'],
        ['占用比例', ui.meter(used, total, { warnAt: (total - d.threshold_gb) / total }) + '<small class="y15-muted">快照与工作区合计 ' + used.toFixed(1) + ' / ' + total.toFixed(1) + ' GB</small>']])
    });
  }

  Y15.views.register('sys-runtime', {
    render() { return '<div class="y15-page"><div class="y15-page-head"><div class="y15-page-titles"><h1>运行与执行槽位</h1><p class="y15-muted">槽位占用、排队、升级前的排空与磁盘</p></div></div>' + slotsBlock() + drainBlock() + retentionBlock() + '</div>'; }
  });
  Y15.actions.register('runtime.setSlots', (el) => {
    const p = H.project(el.dataset.id);
    p.slots.limit = Number(document.getElementById('slots-' + p.id).value);
    ui.toast(p.name + ' 的执行槽位数设为 ' + p.slots.limit, 'ok');
    Y15.rerender();
  });
  Y15.actions.register('runtime.cancelQueue', (el) => {
    const p = H.project(el.dataset.p), it = H.item(p, el.dataset.i);
    Object.assign(it, { status: 'stopped', dept: null, reason: '排队时被你取消' });
    p.slots.waiting = Math.max(0, p.slots.waiting - 1);
    ui.toast('已取消排队：' + it.title, 'ok');
    Y15.rerender();
  });
  Y15.actions.register('runtime.drain', () => { drain = { state: 'draining', since: Y15.app.now() }; Y15.rerender(); });
  Y15.actions.register('runtime.force', () => { drain = { state: 'forced', since: drain.since }; ui.toast('正在进行的运行记为因升级停止，事项会从项目的起点重新开始', 'ok'); Y15.rerender(); });
  Y15.actions.register('runtime.undrain', () => { drain = { state: 'none', since: null }; Y15.rerender(); });

  // ---------------------------------------------------------------- 工具与扩展

  function toolTable(list) { return ui.table({ columns: [{ label: '工具', render: (t) => ui.code(t[0]) }, { label: '说明', render: (t) => esc(t[1]) }], rows: list }); }

  Y15.views.register('sys-tools', {
    render() {
      const T = X.tools;
      const recent = ui.table({
        columns: [{ label: '时间', render: (r) => esc(ui.time(r.at)) }, { label: '地址', render: (r) => ui.code(r.url) }, { label: '项目', render: (r) => esc(pname(r.project)) }, { label: '结果', render: (r) => esc(r.result) }],
        rows: T.network.recent
      });
      const dn = { product: '产品', engineering: '工程', quality: '质检' };
      const mcp = T.mcp.map((s) => '<section class="y15-mcp"><h3 class="y15-h3">' + esc(s.name) + ' ' + ui.tag(pname(s.project)) + '</h3>' +
        ui.kv([['连接方式', ui.code(s.transport)], ['可以使用的部门', esc(s.depts.map((d) => dn[d]).join('、'))],
          ['最近一次状态', ui.status(s.last.ok ? 'succeeded' : 'failed', s.last.text) + ' <span class="y15-muted">' + esc(ui.time(s.last.at)) + '</span>']], 'is-rows') +
        toolTable(s.tools) + '<div class="y15-row">' + ui.button({ label: '在项目设置中修改', kind: 'small', go: '#/p/' + s.project + '/settings' }) + '</div></section>').join('');
      return '<div class="y15-page"><div class="y15-page-head"><div class="y15-page-titles"><h1>工具与扩展</h1><p class="y15-muted">只读汇总；修改 MCP 服务器在各项目的设置里</p></div></div>' +
        ui.block({ title: '网络取回', subtitle: T.network.scope, body: '<h3 class="y15-h3">最近的取回记录</h3>' + recent }) +
        ui.block({ title: 'MCP 工具', subtitle: '各项目在设置里写明的 MCP 服务器：怎样连接、哪些部门可以用；服务器提供的工具全部直接给这些部门', body: mcp }) +
        ui.block({ title: '浏览器工具', subtitle: T.browser.note, body: toolTable(T.browser.tools) }) +
        ui.block({ title: '桌面操作', subtitle: T.computer.note + '（虚拟屏幕 ' + T.computer.screen + '）', body: toolTable(T.computer.tools) }) +
        ui.block({ title: '只读观察者', subtitle: '在控制核心外面订阅事件的模块，不能改任何事实', body: ui.table({ columns: [{ label: '观察者', key: 'name' }, { label: '订阅范围', key: 'scope' }], rows: T.observers }) }) + '</div>';
    }
  });

  // ---------------------------------------------------------------- 预留入口

  Y15.views.register('reserved', {
    render(ctx) {
      const r = X.reserved[ctx.route.params.which];
      return '<div class="y15-page"><div class="y15-page-head"><div class="y15-page-titles"><h1>' + esc(r.title) + ' ' + ui.tag('预留入口') + '</h1></div></div>' +
        ui.block({ body: ui.kv([['所属阶段', esc(r.stage)], ['做出来以后', esc(r.outcome)]]) + ui.note('进入这个阶段时再设计。') }) + '</div>';
    }
  });
})();
