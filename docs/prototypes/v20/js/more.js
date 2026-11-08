// 项目里的其余页面：模型请求与用量的面板、请求详情、设置（高级里的四节）、恢复与动作核实
(function () {
  'use strict';
  const Y20 = window.Y20;
  const esc = Y20.esc;
  const ui = Y20.ui;
  const H = Y20.h;
  const X = Y20.EXTRA;
  const O = Y20.org;

  const stack = (...lines) => '<div class="y20-cell-stack">' + lines.join('') + '</div>';
  const head = (title, sub, actions) => '<div class="y20-page-head"><div class="y20-page-titles"><h1>' + title + '</h1>' + (sub ? '<p class="y20-muted">' + sub + '</p>' : '') + '</div>' + (actions ? '<div class="y20-page-actions">' + actions + '</div>' : '') + '</div>';

  // ================================================================ 观测

  const AST = { preparing: ['idle', '准备中'], requesting: ['running', '请求中'], running: ['running', '进行中'], succeeded: ['succeeded', '成功'], failed: ['failed', '失败'], cancelled: ['cancelled', '已取消'] };
  const AKIND = { work: '工作请求', compaction: '压缩请求', collaboration: '询问分支', review: '审查请求' };
  const fmtMs = (ms) => (ms === null ? '—' : ms < 1000 ? ms + ' 毫秒' : ui.duration(ms / 1000));
  const obs = { filters: {}, tab: {}, open: {} };
  const filtersOf = (pid) => (obs.filters[pid] = obs.filters[pid] || { dept: '', status: '', item: '', model: '' });
  const wiring = (a) => X.wiring[a.dept];
  const shortId = (id) => '请求 ' + id.replace('r-', '');

  function attemptsOf(p) {
    const f = filtersOf(p.id);
    return X.attempts.filter((a) => a.project === p.id && (!f.dept || a.dept === f.dept) && (!f.status || a.status === f.status) && (!f.item || a.item === f.item) && (!f.model || wiring(a).model === f.model));
  }

  function filterBar(p) {
    const f = filtersOf(p.id);
    const sel = (key, label, opts, all) => '<label class="y20-obs-filter"><span>' + label + '</span><select class="y20-select" data-act="obs.filter" data-key="' + key + '"><option value="">' + all + '</option>' +
      opts.map((o) => '<option value="' + esc(o[0]) + '"' + (f[key] === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('') + '</select></label>';
    const models = [...new Set(p.depts.map((d) => O.modelOf(p, d)).filter(Boolean))].map((m) => [m, m]);
    return '<div class="y20-obs-filters">' + sel('dept', '职能', p.depts.map((d) => [d, H.dept(d) + '职能']), '全部职能') + sel('item', '事项', p.items.map((i) => [i.id, i.title]), '全部事项') +
      sel('status', '状态', Object.keys(AST).map((s) => [s, AST[s][1]]), '全部状态') + sel('model', '模型', models, '全部模型') +
      (Object.values(f).some(Boolean) ? '<button type="button" class="y20-link" data-act="obs.reset">清除筛选</button>' : '') + '</div>';
  }

  function recordsPanel(p, list) {
    return '<p class="y20-muted y20-small">用量没有上报时显示「未知」，不填 0；请求的模型和返回的模型分开列出。</p>' + ui.table({
      columns: [
        { label: '开始', render: (a) => esc(ui.time(a.start)) },
        { label: '状态', render: (a) => ui.status(AST[a.status][0], AST[a.status][1]) },
        { label: '耗时', render: (a) => (a.ms === null ? '<span class="y20-muted">进行中</span>' : esc(fmtMs(a.ms))) },
        { label: '职能 · 角色', render: (a) => esc(H.dept(a.dept)) + '<small class="y20-muted y20-block-line">' + esc(a.role) + '</small>' },
        { label: '请求的模型', render: (a) => stack(ui ? ui.code(wiring(a).model) : '', '<small class="y20-muted">' + esc(wiring(a).provider) + '</small>') },
        { label: '返回的模型', render: (a) => (a.status === 'failed' ? '<span class="y20-muted">未知</span>' : ui.code(wiring(a).model)) },
        { label: '类型', render: (a) => esc(AKIND[a.kind]) },
        { label: '输入 / 输出', render: (a) => (a.status === 'failed' || a.output === null ? '<span class="y20-muted">未知</span>' : Y20.num(a.input) + ' / ' + Y20.num(a.output)) },
        { label: '详情', className: 'y20-col-actions', render: (a) => ui.button({ label: '查看', kind: 'small', go: '#/p/' + p.id + '/observe/' + a.id }) }
      ], rows: list, empty: '没有符合筛选条件的请求'
    });
  }

  function usagePanel(p, list) {
    const sum = (k, rows) => rows.reduce((n, a) => n + (a[k] || 0), 0);
    const tot = (rows) => ({ n: rows.length, input: sum('input', rows), output: sum('output', rows), cache: sum('cache', rows) });
    const t = tot(list);
    const totals = '<div class="y20-totals">' + [['请求', t.n], ['输入（含缓存）', t.input], ['输出', t.output], ['缓存读取（输入的一部分）', t.cache], ['合计', t.input + t.output]].map((c) => '<div><span>' + c[0] + '</span><strong>' + Y20.num(c[1]) + '</strong></div>').join('') + '</div>';
    const groups = p.depts.map((d) => ({ d, rows: list.filter((a) => a.dept === d) })).filter((g) => g.rows.length);
    const by = ui.table({
      columns: [{ label: '职能', render: (g) => esc(H.dept(g.d)) + '职能' }, { label: '请求', render: (g) => g.rows.length }, { label: '输入（含缓存）', render: (g) => Y20.num(tot(g.rows).input) }, { label: '输出', render: (g) => Y20.num(tot(g.rows).output) },
        { label: '缓存读取', render: (g) => Y20.num(tot(g.rows).cache) }, { label: '费用', render: () => '<span class="y20-muted">未上报</span>' }], rows: groups, empty: '范围内还没有请求'
    });
    const limits = ui.table({
      columns: [{ label: '事项', render: (i) => stack('<strong>' + H.dot(i) + ' ' + esc(i.title) + '</strong>', '<small class="y20-muted">' + esc(Y20.ITEM_STATUS[i.status][0]) + '</small>') },
        { label: '已用时间 / 上限', render: (i) => esc(H.dur(i.used)) + ' / ' + esc(H.dur(i.limit)) + ui.meter(i.used, i.limit) }, { label: '轮次', render: (i) => (i.round ? '第 ' + i.round + ' 轮 / 上限 ' + i.round_limit : '<span class="y20-muted">未开始</span>') }],
      rows: p.items.filter((i) => !['adopted', 'open_closed', 'stopped'].includes(i.status))
    });
    return '<h3 class="y20-h3">筛选后的合计</h3>' + totals + '<h3 class="y20-h3">按职能</h3>' + by + '<h3 class="y20-h3">各事项的上限</h3>' + limits +
      '<p class="y20-muted y20-small">「输入（含缓存）」已包含缓存读取，两者不重复相加；用量只读显示，不作为事项的预算。</p>';
  }

  let openLoop = null;
  const loopState = (s) => '<span class="y20-loop is-' + X.loopStates[s][1] + '">' + X.loopStates[s][0] + '</span>';
  const LOOP_LAYER = { run: '一次运行', activation: '一轮工作' };
  const loopRow = (id, indent, cols, basis) => '<tr class="y20-loop-row' + (openLoop === id ? ' is-open' : '') + '" data-act="obs.loop" data-id="' + id + '">' + cols.map((c, i) => '<td data-label="' + ['层', '实例', '轮次', '已用量与上限', '收敛状态', '停止原因'][i] + '"><div class="y20-td"' + (i === 1 ? ' style="padding-left:' + indent * 16 + 'px"' : '') + '>' + (c === '' ? '<span class="y20-muted">—</span>' : c) + '</div></td>').join('') + '</tr>' +
      (openLoop === id && basis ? '<tr class="y20-loop-detail"><td colspan="6"><b>判定依据</b> ' + esc(basis) + '</td></tr>' : '');
  // 设置页的「模型请求与用量」：请求记录与用量统计用同一组筛选
  Y20.observe = {
    isOpen: (pid) => Boolean(obs.open[pid]),
    panel(p) {
      const list = attemptsOf(p);
      const items = [{ id: 'records', label: '请求记录', count: list.length }, { id: 'usage', label: '用量统计' }];
      const active = ui.activeTab('y20-req', items, 'records');
      return '<p class="y20-muted y20-small">这个项目全部事项的请求；点「查看」进请求详情。</p>' + filterBar(p) + ui.tabs({ id: 'y20-req', items, active }) + ui.tabPanels('y20-req', active, { records: recordsPanel(p, list), usage: usagePanel(p, list) });
    },
    // 事项面板里的循环：这件事项各层的循环实例，点一行看判定依据
    loops(p, it) {
      const list = (X.loops[p.id] && X.loops[p.id].items[it.id]) || [];
      if (!list.length) return '<p class="y20-muted y20-small">这件事项还没有循环记录</p>';
      const rows = list.map((r, i) => loopRow(it.id + '-' + i, r[0] === 'run' ? 0 : 1, [LOOP_LAYER[r[0]], esc(r[1]), esc(r[2]), esc(r[3]), loopState(r[4]), esc(r[5])], r[6])).join('');
      return '<div class="y20-table-wrap"><table class="y20-table y20-loop-table"><thead><tr><th>层</th><th>实例</th><th>轮次</th><th>已用量与上限</th><th>收敛状态</th><th>停止原因</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
    }
  };
  Y20.actions.register('obs.filter', (el) => { const pid = Y20.h.pid(); filtersOf(pid)[el.dataset.key] = el.value; obs.open[pid] = true; Y20.rerender(); });
  Y20.actions.register('obs.reset', () => { const pid = Y20.h.pid(); obs.filters[pid] = null; obs.open[pid] = true; Y20.rerender(); });
  // 节点面板的「本职能的模型请求」：带着职能筛选进设置页这一节
  Y20.actions.register('obs.dept', (el) => { const pid = Y20.h.pid(); obs.filters[pid] = null; filtersOf(pid).dept = el.dataset.dept; obs.open[pid] = true; Y20.go('#/p/' + pid + '/settings?section=requests'); });
  Y20.actions.register('obs.loop', (el) => { openLoop = openLoop === el.dataset.id ? null : el.dataset.id; Y20.rerender(); });

  // 请求详情
  Y20.views.register('observe-detail', {
    render(ctx, p) {
      const a = X.attempts.find((x) => x.id === ctx.route.params.attempt);
      if (!a) return '<div class="y20-gate"><h1>找不到这条请求</h1></div>';
      const w = wiring(a);
      const it = H.item(p, a.item);
      const live = ['requesting', 'running'].includes(a.status);
      const diag = ui.kv([['开始', esc(ui.time(a.start))], ['耗时', live ? '<span class="y20-muted">进行中</span>' : esc(fmtMs(a.ms))], ['状态', ui.status(AST[a.status][0], AST[a.status][1])], ['类型', AKIND[a.kind]],
        ['事项', it ? H.dot(it) + ' ' + H.link('#/p/' + p.id + '?item=' + it.id, it.title) : ''], ['职能 · 角色', esc(H.dept(a.dept) + ' · ' + a.role)], ['模型服务', esc(w.provider)],
        ['请求 → 返回', esc(w.model + ' → ' + (a.status === 'failed' ? '未知' : w.model))]].concat(a.err ? [['失败的分类', esc(a.err.category)], ['错误代码', ui.code(a.err.code)]] : [])) + (a.err ? ui.note('错误原文：' + esc(a.err.text), 'warn') : '');
      const target = ui.kv([['连接', esc(w.conn)], ['协议', esc(w.proto)], ['请求地址', ui.code(w.base)], ['上游模型', esc(w.model)], ['容量（窗口 / 最大输出）', Y20.num(w.window) + ' / ' + Y20.num(w.out)],
        ['凭据引用 / 版本', ui.code(w.cred + ' 第 ' + w.cv + ' 版')], ['选择来源', esc(w.src)], ['请求档位 → 发送档位', esc(w.level + ' → ' + w.level)], ['职能提示的版本', '第 ' + (X.deptPrompt[a.dept].indexOf('2') >= 0 ? 2 : 1) + ' 版']]);
      const sections = ui.table({ columns: [{ label: '栏目', render: (r) => esc(r[0]) }, { label: '版本', render: (r) => (r[1] ? ui.tag(r[1]) : '') }, { label: '放进请求', render: (r) => ui.status(r[2] ? 'succeeded' : 'idle', r[2] ? '放进了' : '没放进') }, { label: '原因', render: (r) => esc(r[3]) }], rows: X.sectionsOf(a) });
      const sibs = X.attempts.filter((x) => a.group && x.group === a.group).sort((x, y) => x.start.localeCompare(y.start));
      const sib = sibs.length > 1 ? ui.block({ title: '同一次调用的各次尝试', body: '<div class="y20-sibs">' + sibs.map((s, i) => '<button type="button" class="y20-sib' + (s.id === a.id ? ' is-on' : '') + '" data-go="#/p/' + p.id + '/observe/' + s.id + '"><strong>第 ' + (i + 1) + ' / ' + sibs.length + ' 次</strong><small>' + AST[s.status][1] + ' · ' + esc(ui.time(s.start)) + '</small></button>').join('') + '</div>' }) : '';
      const out = live ? '<p class="y20-muted">还在进行，已经收到的文字：</p>' + ui.pre('读取现有实现，确定入口在 orders/export.ts……\n正在整理要改的文件清单……') : (X.outputOf(a) ? ui.pre(X.outputOf(a)) : '<p class="y20-muted">没有保存的输出。</p>');
      return '<div class="y20-page">' + head(esc(shortId(a.id)) + ' ' + ui.status(AST[a.status][0], AST[a.status][1]), '调用目标、各栏目的来源、用量与上限；输出按保存的内容原样列出', ui.button({ label: '返回模型请求与用量', icon: 'back', go: '#/p/' + p.id + '/settings?section=requests' })) +
        ui.block({ title: '诊断', body: diag }) + ui.block({ title: '调用目标', subtitle: '请求档位和实际发送的档位分开列出；凭据只显示引用和版本', body: target }) +
        ui.block({ title: '各栏目的来源', subtitle: '每一栏为什么放进请求、有没有放进', body: sections }) +
        ui.block({ title: '用量与上限', body: ui.kv([['输入（含缓存）', Y20.num(a.input)], ['输出', Y20.num(a.output)], ['缓存读取（输入的一部分）', Y20.num(a.cache)], ['费用', '未上报'], ['事项已用时间 / 上限', it ? esc(H.dur(it.used) + ' / ' + H.dur(it.limit)) : '']]) }) + sib +
        ui.block({ title: '输出', body: out }) + '</div>';
    }
  });

  // ================================================================ 设置

  const cfg = { goal: {}, pinned: {}, archived: {}, sources: {}, auth: {}, place: {} };

  function settingsPage(ctx, p) {
    const S = X.settings[p.id];
    const archived = Boolean(cfg.archived[p.id]);
    const pinned = p.id in cfg.pinned ? cfg.pinned[p.id] : S.pinned;
    const goal = p.id in cfg.goal ? cfg.goal[p.id] : p.goal;
    const basic = ui.block({ title: '基本信息', body: '<div class="y20-form"><div class="y20-field"><span>名称</span><strong>' + esc(p.name) + '</strong></div>' +
      '<label class="y20-field"><span>长期目标</span><textarea class="y20-textarea" id="set-goal" rows="2"' + (archived ? ' readonly' : '') + '>' + esc(goal) + '</textarea><small class="y20-muted">进行中的事项不受影响，之后开始的事项用新目标。</small></label>' +
      '<div class="y20-row">' + ui.button({ label: '保存长期目标', kind: 'small', act: 'set.goal', disabled: archived }) + '</div>' +
      '<div class="y20-field"><span>置顶</span><div class="y20-row">' + (pinned ? ui.status('done', '已置顶') : '<span class="y20-muted">未置顶</span>') + ui.button({ label: pinned ? '取消置顶' : '置顶', kind: 'small', act: 'set.pin' }) + '</div></div>' +
      '<div class="y20-field"><span>归档</span><div class="y20-row">' + (archived ? ui.status('cancelled', '已归档') : '<span class="y20-muted">未归档</span>') +
      ui.button({ label: archived ? '恢复项目' : '归档', kind: 'small' + (archived ? ' primary' : ' danger'), act: 'set.archive' }) + '</div></div></div>' + (archived ? ui.note('归档以后只读：能看，不能改。', 'warn') : '') });
    const srcs = (cfg.sources[p.id] || S.source.slice());
    const source = ui.block({ title: '源目录', subtitle: '登记在这台控制主机上的代码目录：接入已有项目时从这里取快照，采纳的成果可以写回这里。新事项都从项目的起点开始。', body:
      (srcs.length ? ui.table({ columns: [{ label: '名称', render: (r) => ui.code(r.name) }, { label: '路径', render: (r) => '<span class="y20-wrap">' + esc(r.path) + '</span>' },
        { label: '采纳写回', render: (r) => (r.writeback ? ui.status('succeeded', '打开') + ' ' + esc(r.writeback.remote + ' → ' + r.writeback.branch) : '<span class="y20-muted">没有打开</span>') },
        { label: '写回前的检查命令', render: (r) => (r.checks.length ? r.checks.map(ui.code).join(' ') : '<span class="y20-muted">没有</span>') }], rows: srcs }) : ui.empty('还没有登记源目录')) +
      '<h3 class="y20-h3">登记源目录</h3><div class="y20-form"><div class="y20-grid-2"><label class="y20-field"><span>名称</span><input class="y20-input" id="src-name" placeholder="例如 webapp"></label>' +
      '<label class="y20-field"><span>路径</span><input class="y20-input" id="src-path" placeholder="控制主机上的绝对路径"></label></div><div class="y20-row">' + ui.button({ label: '保存源目录', kind: 'primary', act: 'set.source', disabled: archived }) + '<small class="y20-muted">同名登记会覆盖原来的。</small></div></div>' });
    const W = S.writeback;
    const writeback = ui.block({ title: '成果写回', subtitle: '把采纳的成果写回登记的源目录。当前只在本地记录合并请求，还没有在代码托管平台上创建。', actions: ui.button({ label: '写回成果', icon: 'import', kind: 'small primary', act: 'set.writeback', disabled: archived || !W.enabled }),
      body: (W.enabled ? '<p>' + ui.status('succeeded', '采纳写回已打开') + ' <span class="y20-muted">写回到 ' + esc(W.source) + '，目标分支 ' + esc(W.branch) + '</span></p>' : ui.note('源目录还没有打开采纳写回：在上面登记源目录并写明远端与目标分支。', 'info')) +
        (W.records.length ? ui.table({ columns: [{ label: '采纳的成果', render: (r) => esc(r.adoption) }, { label: '结果', render: (r) => ui.status('succeeded', r.text) }, { label: '时间', render: (r) => esc(ui.time(r.at)) }, { label: '说明', render: (r) => esc(r.detail) },
          { label: '合并请求', render: (r) => esc(r.mr) + ' ' + ui.tag('还只是本地记录') }], rows: W.records }) : ui.empty('还没有写回记录')) });
    const ml = Y20.machineList ? Y20.machineList() : [];
    const authSet = cfg.auth[p.id] || ml.filter((m) => m.projects.includes(p.id)).map((m) => m.id);
    const machines = ui.block({ title: '机器授权', subtitle: '从「机器」页登记的机器里，选本项目可以用的；命令在登记的目录里原样执行，不逐条授权。', body: '<div class="y20-set-depts">' + ml.map((m) =>
      '<label class="y20-set-dept"><span class="y20-field is-inline"><input type="checkbox" data-act="set.auth" data-id="' + esc(m.id) + '"' + (authSet.includes(m.id) ? ' checked' : '') + (archived || m.fixed ? ' disabled' : '') + '><span><strong>' + esc(m.name) + '</strong></span></span><small class="y20-muted">' + esc(m.address) + ' · ' + esc(m.purpose) + (m.online ? '' : ' · 离线') + '</small></label>').join('') + '</div>' });
    const place = cfg.place[p.id] || S.place;
    const orgDepts = p.composed.depts;
    const where = (cur, extra) => '<option value="">' + extra + '</option><option value="local"' + (cur === 'local' ? ' selected' : '') + '>本机进程</option>' + ml.filter((m) => !m.fixed && authSet.includes(m.id)).map((m) => '<option value="' + esc(m.id) + '"' + (cur === m.id ? ' selected' : '') + '>' + esc(m.name) + '</option>').join('');
    const placement = ui.block({ title: '执行位置', subtitle: '运行工作区放在哪里，以及各职能做检查的地方：本机进程，或本项目已授权的机器。', body: '<div class="y20-grid-2">' +
      '<label class="y20-field"><span>运行工作区</span><select class="y20-select" data-act="set.place" data-k="workspace">' + where(place.workspace, '本机进程').replace('<option value="">本机进程</option>', '') + '</select></label>' +
      orgDepts.map((d) => '<label class="y20-field"><span>' + esc(d.name) + '做检查的地方</span><select class="y20-select" data-act="set.place" data-k="' + d.id + '">' + where(place.checks[d.id], '和运行工作区相同') + '</select></label>').join('') + '</div>' });
    const mcp = X.tools.mcp.filter((s) => s.project === p.id);
    const mcpBlock = ui.block({ title: 'MCP 服务器', subtitle: '本项目接入的 MCP 服务器和哪些职能可以用；职能的选项取自这份组织；全部项目的汇总在「工具与扩展」', body: mcp.length ? ui.table({ columns: [{ label: '名称', render: (s) => esc(s.name) }, { label: '连接方式', render: (s) => ui.code(s.transport) },
      { label: '可以使用的职能', render: (s) => '<div class="y20-checks">' + orgDepts.map((d) => '<label class="y20-check"><input type="checkbox" data-act="set.mcp" data-s="' + esc(s.name) + '" data-d="' + esc(d.id) + '"' + (s.depts.includes(d.id) ? ' checked' : '') + (archived ? ' disabled' : '') + '><span>' + esc(d.name) + '</span></label>').join('') + '</div>' },
      { label: '最近一次状态', render: (s) => ui.status(s.last.ok ? 'succeeded' : 'failed', s.last.text) }], rows: mcp }) : ui.empty('本项目没有接入 MCP 服务器') });
    const moved = ui.note('每个职能的模型、推理档位、Prompt 和每个角色的设置，已经并进「高级」里组织各职能的详情页。 ' + ui.button({ label: '去高级里的组织', kind: 'small', go: '#/p/' + p.id + '/org?advanced=1' }), 'info');
    return '<div class="y20-page">' + head('项目设置', esc(p.name) + ' · 基本信息、源目录、成果写回、机器授权、执行位置、MCP 服务器') + moved + basic + source + writeback + machines + placement + mcpBlock + '</div>';
  }
  Y20.views.register('settings', { render: settingsPage });

  const pidOf = () => Y20.h.pid();
  const A = (name, fn) => Y20.actions.register(name, fn);
  A('set.goal', () => { cfg.goal[pidOf()] = document.getElementById('set-goal').value; ui.toast('已保存长期目标；之后开始的事项使用新目标', 'ok'); });
  A('set.pin', () => { const p = pidOf(); cfg.pinned[p] = !(p in cfg.pinned ? cfg.pinned[p] : X.settings[p].pinned); Y20.rerender(); });
  A('set.archive', () => { const p = pidOf(); cfg.archived[p] = !cfg.archived[p]; Y20.rerender(); });
  A('set.source', () => {
    const p = pidOf(), name = document.getElementById('src-name').value.trim(), path = document.getElementById('src-path').value.trim();
    if (!name || !path) { ui.toast('名称和路径都要填', 'warn'); return; }
    const list = cfg.sources[p] || X.settings[p].source.slice();
    const at = list.findIndex((r) => r.name === name);
    const row = { name, path, writeback: null, checks: [] };
    if (at >= 0) list[at] = row; else list.push(row);
    cfg.sources[p] = list;
    Y20.rerender();
  });
  A('set.writeback', () => ui.toast('已发起写回：写回完成后，这里会多一条记录（演示）', 'ok'));
  A('set.auth', (el) => { const p = pidOf(); const cur = cfg.auth[p] || Y20.machineList().filter((m) => m.projects.includes(p)).map((m) => m.id); cfg.auth[p] = el.checked ? cur.concat(el.dataset.id) : cur.filter((x) => x !== el.dataset.id); Y20.rerender(); });
  A('set.place', (el) => { const p = pidOf(); const cur = cfg.place[p] || JSON.parse(JSON.stringify(X.settings[p].place)); if (el.dataset.k === 'workspace') cur.workspace = el.value || 'local'; else cur.checks[el.dataset.k] = el.value; cfg.place[p] = cur; ui.toast('已保存执行位置', 'ok'); });
  A('set.mcp', (el) => {
    const s = X.tools.mcp.find((x) => x.name === el.dataset.s && x.project === pidOf());
    s.depts = el.checked ? s.depts.concat(el.dataset.d) : s.depts.filter((d) => d !== el.dataset.d);
    ui.toast('已保存：' + s.name + ' 可以使用的职能已更新', 'ok');
  });

  // ================================================================ 恢复与动作核实

  const RSTATES = [['running', '运行中', 'running'], ['interrupted', '中断', 'interrupted'], ['waiting_resume', '待恢复', 'waiting'], ['completed', '已完成', 'done'], ['paused', '已暂停', 'paused'], ['cancelled', '已取消', 'cancelled'], ['stopped', '已停止', 'failed']];

  function recState(it, p) {
    const int = p.interruptions.find((x) => x.item === it.id);
    if (it.status === 'waiting_resume') return { s: 'waiting_resume', reason: int ? int.why + '，这一轮工作被打断，等你决定是否从中断位置继续' : it.reason };
    if (it.status === 'waiting_user') return { s: 'waiting_resume', reason: it.reason };
    if (it.status === 'adopted' || it.status === 'open_closed') return { s: 'completed', reason: it.reason };
    if (it.status === 'stopped') return { s: 'stopped', reason: it.reason };
    if (it.status === 'waiting_slot' || it.status === 'queued') return { s: 'paused', reason: '还没有开始：' + it.reason };
    return { s: 'running', reason: it.reason };
  }
  const HK = { confirmed: 'succeeded', returned: 'asking', waiting: 'waiting' };

  Y20.views.register('recovery', {
    render(ctx, p) {
      const it = H.item(p, ctx.route.params.item);
      if (!it) return '<div class="y20-gate"><h1>找不到事项</h1></div>';
      const st = recState(it, p);
      const int = p.interruptions.find((x) => x.item === it.id);
      const pills = '<ul class="y20-rc-states">' + RSTATES.map((r) => '<li class="y20-rc-state' + (r[0] === st.s ? ' is-on' : '') + '">' + (r[0] === st.s ? ui.status(r[2], r[1]) : esc(r[1])) + '</li>').join('') + '</ul>';
      const state = ui.block({ title: '恢复状态', subtitle: '事项：' + it.title, body: pills + '<p class="y20-rc-reason">' + esc(st.reason) + '</p>' + '<ul class="y20-rc-rules"><li>Yudao 启动时自动继续中断的运行，并写明最后确认的位置。</li><li>结果未知的动作先按核实方法自动核实；核实不出来的，作为工具结果交还给发出它的会话，由模型决定要不要重做。</li><li>等待模型服务、等待机器都有时长上限，超过以后会请你决定。</li><li>恢复不会清零已用的限额。</li></ul>' });
      const where = int ? ui.block({ title: '中断的位置', body: ui.kv([['被打断的工作', esc(int.what)], ['时间', esc(ui.time(int.at))], ['原因', esc(int.why)], ['现在', ui.status('interrupted', int.state)], ['自动继续', '<span class="y20-muted">还没有自动继续</span>']], 'is-rows') + '<p class="y20-small y20-muted">已开始但没有回执的动作，按核实方法核实；没有未完成的动作时直接自动继续。</p>' }) : '';
      const mine = H.decisions(p.id).filter((d) => d.item === it.id);
      const decide = ui.block({ title: '待你决定', subtitle: '需要你选版本、决定是否继续时，由这里的卡片交给你；结果未知的动作不在这里', body: mine.length ? '<div class="y20-cards">' + mine.map((d) => Y20.cards.one(d)).join('') + '</div>' : ui.empty('没有等你回答的决定') });
      const acts = X.unknownActions[it.id] || [];
      const unknown = ui.block({ title: '结果未知的动作', subtitle: '重新启动或失去联系时结果不明的动作：有核实方法的先自动核实，其余交还给发出它的会话；核实产生新的记录，不改原来的记录', body: acts.length ? '<div class="y20-rc-actions">' + acts.map((a) =>
        '<article class="y20-rc-action"><header>' + ui.status(HK[a.handling], a.handlingText) + ui.code(a.id) + ui.tag('结果未知') + '</header><p><strong>' + esc(a.label) + '</strong></p>' +
        ui.kv([['职能', esc(H.dept(a.dept))], ['发出它的会话', esc(a.session)], a.machine ? ['执行的机器', esc(a.machine)] : null, ['输入依据', esc(a.input)], ['执行前', esc(a.before)], ['执行后', esc(a.after)],
          a.basis ? ['依据', esc(a.basis)] : null, a.result ? ['核实的结果', esc(a.result)] : null, ['时间', esc(ui.time(a.at))]], 'is-rows') + (a.returned ? '<b>交还给会话的工具结果</b>' + ui.pre(a.returned) : '') + '</article>').join('') + '</div>' : ui.empty('没有结果未知的动作：所有动作都有回执') });
      const sess = X.sessionsOf(it);
      const limits = ui.block({ title: '限额与各会话的用量', body: '<div class="y20-rc-limits"><div class="y20-rc-limit is-wide"><span>已用时间 / 上限</span><strong>' + esc(H.dur(it.used)) + ' / ' + esc(H.dur(it.limit)) + '</strong>' + ui.meter(it.used, it.limit, { warnAt: 0.8 }) + '</div>' +
        '<div class="y20-rc-limit"><span>轮次</span><strong>' + it.round + ' / ' + it.round_limit + '</strong></div><div class="y20-rc-limit"><span>等待模型服务（不计入上限）</span><strong>' + (it.status === 'waiting_model' ? esc(H.waited(it.since)) : '无') + '</strong></div></div>' +
        (it.round ? '<h3 class="y20-h3">各会话的用量</h3>' + ui.table({ columns: [{ label: '会话', render: (s) => stack('<strong>' + esc(s.label) + '</strong>', '<small class="y20-muted">' + esc(s.note) + '</small>') }, { label: '已用时间', render: (s) => esc(H.dur(s.sec)) }, { label: '工作轮数', render: (s) => s.acts }, { label: '模型步骤', render: (s) => s.steps }], rows: sess }) : '') +
        '<p class="y20-small y20-muted">恢复不会清零；发出状态不明的请求仍然算在内；用量没有上报时写「未知」，不填零。</p>' });
      const holds = (X.slotHolders[p.id] || []).includes(it.id);
      const owner = ui.block({ title: '谁在执行', body: ui.kv([['当前执行者', it.dept ? '控制主机 · ' + esc(H.dept(it.dept)) : '<span class="y20-muted">没有</span>'], ['执行槽位', holds ? '占用一个执行槽位' : '<span class="y20-muted">没有占用执行槽位</span>']], 'is-rows') + '<p class="y20-small y20-muted">没有迟到的结果。旧执行者迟到的回执，只作为历史记下，不推进状态。</p>' });
      return '<div class="y20-page">' + head('恢复与动作核实 · ' + H.dot(it) + ' ' + esc(it.title), '这个事项的运行状态、中断、结果未知的动作和限额', ui.button({ label: '回到事项', icon: 'back', go: '#/p/' + p.id + '?item=' + it.id })) + state + where + decide + unknown + limits + owner + '</div>';
    }
  });
})();
