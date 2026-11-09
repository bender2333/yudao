// 项目里的其余页面：资料、观测（请求记录、用量、循环）与请求详情、设置、恢复与动作核实
(function () {
  'use strict';
  const Y15 = window.Y15;
  const esc = Y15.esc;
  const ui = Y15.ui;
  const H = Y15.h;
  const X = Y15.EXTRA;

  const stack = (...lines) => '<div class="y15-cell-stack">' + lines.join('') + '</div>';
  const who = (id) => (id === 'user' ? '你' : id === 'output' ? '系统' : H.dept(id));
  const head = (title, sub, actions) => '<div class="y15-page-head"><div class="y15-page-titles"><h1>' + title + '</h1>' + (sub ? '<p class="y15-muted">' + sub + '</p>' : '') + '</div>' + (actions ? '<div class="y15-page-actions">' + actions + '</div>' : '') + '</div>';
  const kindName = (k) => Y15.OUTCOME_KINDS[k];

  // ================================================================ 资料

  function docHead(o, extra) {
    return '<header class="y15-mt-head"><strong>' + esc(kindName(o.kind)) + '</strong>' + (o.version ? ui.tag('第 ' + o.version + ' 版') : '') + (extra || '') +
      '<span class="y15-muted">' + esc(ui.time(o.at)) + ' · ' + esc(who(o.from)) + '</span> ' + H.src(o.id) + '</header>';
  }
  const viewBtn = (o, label) => ui.button({ label: label || '查看原文', kind: 'small', act: 'mt.view', data: { id: o.id } });

  function materialsPage(ctx, p) {
    const w = ctx.route.query.w || '';
    const it = w ? H.item(p, w) : null;
    const outs = p.outcomes.filter((o) => !it || o.item === it.id);
    const cards = p.items.map((i) => {
      const n = (k) => p.outcomes.filter((o) => o.item === i.id && (Array.isArray(k) ? k.includes(o.kind) : o.kind === k)).length;
      const chips = [['你的输入', n('input')], ['PRD', n('prd')], ['交付', n('delivery')], ['质检', n(['release', 'defect'])]].map((c) => '<span class="' + (c[1] ? '' : 'is-zero') + '">' + c[0] + ' ' + c[1] + '</span>').join('');
      return '<article class="y15-mt-card' + (it && it.id === i.id ? ' is-current' : '') + '"><button type="button" class="y15-link" data-go="#/p/' + p.id + '/materials?w=' + i.id + '">' + H.dot(i) + ' ' + esc(i.title) + '</button><div>' + H.status(i) + '</div><div class="y15-mt-counts">' + chips + '</div></article>';
    }).join('');
    let body = ui.block({ title: '按事项查看', subtitle: '资料按事项保存；点事项看它的输入、PRD、交付、质检。' + (it ? '现在看的是「' + it.title + '」。' : ''), body: '<div class="y15-mt-index">' + cards + '</div>' + (it ? '<div class="y15-row">' + ui.button({ label: '看整个项目', kind: 'small', go: '#/p/' + p.id + '/materials' }) + '</div>' : '') });
    if (it) {
      const part = (id, title, sub, list, render) => ui.block({ id, title, subtitle: sub, body: list.length ? '<ol class="y15-mt-list">' + list.slice().reverse().map(render).join('') + '</ol>' : ui.empty('还没有') });
      body += part('mt-input', '你的输入', '按收到的顺序保存的原文', outs.filter((o) => o.kind === 'input'), (o) => '<li class="y15-mt-doc">' + docHead(o) + '<p>' + esc(o.text) + '</p>' + viewBtn(o) + '</li>');
      body += part('mt-prd', 'PRD', '产品提交并被接纳的各版本', outs.filter((o) => o.kind === 'prd'), (o) => '<li class="y15-mt-doc">' + docHead(o) + '<p>' + esc(o.text) + '</p>' + viewBtn(o) + '</li>');
      body += part('mt-delivery', '交付', '各版本的封存快照：文件清单由控制主机从快照得出，不是工程自己写的', outs.filter((o) => o.kind === 'delivery'), (o) => {
        const x = X.delivery[o.id] || {};
        const files = (x.files || []).map((f) => '<li>' + ui.code(f[0]) + ' <span class="y15-muted">' + Y15.num(f[1]) + ' 字节</span> ' + ui.button({ label: '下载', kind: 'small', act: 'mt.download', data: { id: o.id, path: f[0] } }) + '</li>').join('');
        return '<li class="y15-mt-doc">' + docHead(o) + '<p>' + esc(x.summary || o.text) + '</p>' + (o.concl ? '<p>结论：' + ui.status({ release: 'released', defect: 'failed', open: 'held', waiting: 'running' }[o.concl.kind], o.concl.text) + '</p>' : '') +
          (files ? '<ul class="y15-mt-files">' + files + '</ul>' : '') +
          (x.git ? '<p>' + ui.icon('link') + ' 提交 ' + ui.code(x.git.commit) + ' <span class="y15-muted">父提交 ' + esc(x.git.parent) + ' · ' + esc(x.git.stat) + '</span> ' + ui.button({ label: '看代码差异', kind: 'small', act: 'mt.diff', data: { id: o.id } }) + '</p>' : '') + viewBtn(o, '查看交付说明') + '</li>';
      });
      body += part('mt-qa', '质检', '结论、理由与逐条检验结果', outs.filter((o) => o.kind === 'release' || o.kind === 'defect'), (o) => {
        const c = X.criteria[o.id];
        let table = '';
        if (c) {
          const exec = c.rows.filter((r) => r[2] === 'run');
          const cov = { covered: exec.filter((r) => r[3] !== 'not_run').length, total: c.rows.length, model_read: c.rows.filter((r) => r[2] === 'model').length, open_count: c.rows.filter((r) => r[2] !== 'run').length };
          table = '<p class="y15-small">交付快照 ' + ui.code(c.snapshot) + ' · ' + esc(Y15.coverageText(cov)) + '</p>' + ui.table({
            columns: [
              { label: '验收条件', render: (r) => '<strong>' + esc(r[0]) + '</strong> ' + esc(r[1]) + (r[2] === 'run' ? '' : ' ' + ui.tag('开环', 'new')) },
              { label: '检验方式', render: (r) => ({ run: '运行检查', model: '模型阅读', human: '只能由人判断' })[r[2]] },
              { label: '结果', render: (r) => ui.status(r[3] === 'pass' ? 'succeeded' : r[3] === 'fail' ? 'failed' : 'idle', r[3] === 'pass' ? '通过' : r[3] === 'fail' ? '没通过' : '没有运行') },
              { label: '证据', render: (r) => esc(r[4]) }
            ], rows: c.rows
          });
        }
        const lines = o.detail ? ui.pre(o.detail.lines.join('\n')) : '';
        return '<li class="y15-mt-doc">' + docHead(o, ui.status(o.kind === 'release' ? 'released' : 'failed', o.kind === 'release' ? '放行' : '缺陷记录')) + '<p>' + esc(o.text) + '</p>' + table + lines + '</li>';
      });
    }
    const notes = (X.notes[p.id] || []);
    body += ui.block({ title: '项目材料', subtitle: '「记录原文」保存的材料；只记录原文，不放进后面事项的请求', body: notes.length ? '<ul class="y15-mt-notes">' + notes.map((n) =>
      '<li><header class="y15-mt-head"><strong>' + esc(n.title) + '</strong>' + ui.tag(H.dept(n.dept) + '部门') + '<span class="y15-muted">' + esc(ui.time(n.at)) + ' 记录</span></header><blockquote class="y15-quote">' + esc(n.text) + '</blockquote></li>').join('') + '</ul>' : ui.empty('项目还没有项目材料') });
    const old = X.oldRuns[p.id] || [];
    if (old.length && (!it || old.some((r) => r.item === it.id))) {
      body += ui.block({ title: '旧版本的运行', subtitle: 'Yudao 版本和现在不同的运行，只读', body: '<ol class="y15-mt-list">' + old.filter((r) => !it || r.item === it.id).map((r) => '<li class="y15-mt-doc"><header class="y15-mt-head"><strong>旧运行 ' + esc(r.id) + '</strong>' + ui.tag('只读') + ui.tag('Yudao ' + r.ver) + '<span class="y15-muted">' + esc(r.state) + '</span></header><ul class="y15-list">' +
        r.events.map((e) => '<li><span class="y15-muted">' + esc(ui.time(e[0])) + '</span> ' + ui.tag(e[1]) + ' ' + esc(e[2]) + '</li>').join('') + '</ul></li>').join('') + '</ol>' });
    }
    return '<div class="y15-page">' + head('资料', esc(p.name) + ' · 全部只读') + body + '</div>';
  }
  Y15.views.register('materials', { render: materialsPage });

  const outOf = (id) => { for (const p of Y15.W().projects) { const o = p.outcomes.find((x) => x.id === id); if (o) return { p, o }; } return null; };
  Y15.actions.register('mt.view', (el) => { const r = outOf(el.dataset.id); ui.modal({ title: kindName(r.o.kind) + ' 原文', wide: true, body: ui.pre(r.o.text), actions: [{ label: '关闭', close: true }] }); });
  Y15.actions.register('mt.diff', (el) => {
    const r = outOf(el.dataset.id), x = X.delivery[r.o.id];
    ui.modal({ title: '代码差异', wide: true, body: ui.kv([['提交', ui.code(x.git.commit)], ['父提交', ui.code(x.git.parent)], ['变化', esc(x.git.stat)]]) + ui.pre(x.diff), actions: [{ label: '关闭', close: true }] });
  });
  Y15.actions.register('mt.download', (el) => ui.modal({ title: el.dataset.path, body: ui.note('示例数据只有文件清单，没有文件内容。真实界面会从封存的交付快照核对摘要以后再下载。', 'warn'), actions: [{ label: '关闭', close: true }] }));

  // ================================================================ 观测

  const AST = { preparing: ['idle', '准备中'], requesting: ['running', '请求中'], running: ['running', '进行中'], succeeded: ['succeeded', '成功'], failed: ['failed', '失败'], cancelled: ['cancelled', '已取消'] };
  const AKIND = { work: '工作请求', compaction: '压缩请求', collaboration: '询问分支', review: '审查请求' };
  const fmtMs = (ms) => (ms === null ? '—' : ms < 1000 ? ms + ' 毫秒' : ui.duration(ms / 1000));
  const obs = { filters: {}, tab: {} };
  const filtersOf = (pid) => (obs.filters[pid] = obs.filters[pid] || { dept: '', status: '', item: '', model: '' });
  const wiring = (a) => X.wiring[a.dept];
  const shortId = (id) => '请求 ' + id.replace('r-', '');

  function attemptsOf(p) {
    const f = filtersOf(p.id);
    return X.attempts.filter((a) => a.project === p.id && (!f.dept || a.dept === f.dept) && (!f.status || a.status === f.status) && (!f.item || a.item === f.item) && (!f.model || wiring(a).model === f.model));
  }

  function filterBar(p) {
    const f = filtersOf(p.id);
    const sel = (key, label, opts, all) => '<label class="y15-obs-filter"><span>' + label + '</span><select class="y15-select" data-act="obs.filter" data-key="' + key + '"><option value="">' + all + '</option>' +
      opts.map((o) => '<option value="' + esc(o[0]) + '"' + (f[key] === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('') + '</select></label>';
    const models = [...new Set(p.depts.map((d) => X.wiring[d].model))].map((m) => [m, m]);
    return '<div class="y15-obs-filters">' + sel('dept', '部门', p.depts.map((d) => [d, H.dept(d) + '部门']), '全部部门') + sel('item', '事项', p.items.map((i) => [i.id, i.title]), '全部事项') +
      sel('status', '状态', Object.keys(AST).map((s) => [s, AST[s][1]]), '全部状态') + sel('model', '模型', models, '全部模型') +
      (Object.values(f).some(Boolean) ? '<button type="button" class="y15-link" data-act="obs.reset">清除筛选</button>' : '') + '</div>';
  }

  function recordsPanel(p, list) {
    return '<p class="y15-muted y15-small">用量没有上报时显示「未知」，不填 0；请求的模型和返回的模型分开列出。</p>' + ui.table({
      columns: [
        { label: '开始', render: (a) => esc(ui.time(a.start)) },
        { label: '状态', render: (a) => ui.status(AST[a.status][0], AST[a.status][1]) },
        { label: '耗时', render: (a) => (a.ms === null ? '<span class="y15-muted">进行中</span>' : esc(fmtMs(a.ms))) },
        { label: '部门 · 角色', render: (a) => esc(H.dept(a.dept)) + '<small class="y15-muted y15-block-line">' + esc(a.role) + '</small>' },
        { label: '请求的模型', render: (a) => stack(ui ? ui.code(wiring(a).model) : '', '<small class="y15-muted">' + esc(wiring(a).provider) + '</small>') },
        { label: '返回的模型', render: (a) => (a.status === 'failed' ? '<span class="y15-muted">未知</span>' : ui.code(wiring(a).model)) },
        { label: '类型', render: (a) => esc(AKIND[a.kind]) },
        { label: '输入 / 输出', render: (a) => (a.status === 'failed' || a.output === null ? '<span class="y15-muted">未知</span>' : Y15.num(a.input) + ' / ' + Y15.num(a.output)) },
        { label: '详情', className: 'y15-col-actions', render: (a) => ui.button({ label: '查看', kind: 'small', go: '#/p/' + p.id + '/observe/' + a.id }) }
      ], rows: list, empty: '没有符合筛选条件的请求'
    });
  }

  function usagePanel(p, list) {
    const sum = (k, rows) => rows.reduce((n, a) => n + (a[k] || 0), 0);
    const tot = (rows) => ({ n: rows.length, input: sum('input', rows), output: sum('output', rows), cache: sum('cache', rows) });
    const t = tot(list);
    const totals = '<div class="y15-totals">' + [['请求', t.n], ['输入（含缓存）', t.input], ['输出', t.output], ['缓存读取（输入的一部分）', t.cache], ['合计', t.input + t.output]].map((c) => '<div><span>' + c[0] + '</span><strong>' + Y15.num(c[1]) + '</strong></div>').join('') + '</div>';
    const groups = p.depts.map((d) => ({ d, rows: list.filter((a) => a.dept === d) })).filter((g) => g.rows.length);
    const by = ui.table({
      columns: [{ label: '部门', render: (g) => esc(H.dept(g.d)) + '部门' }, { label: '请求', render: (g) => g.rows.length }, { label: '输入（含缓存）', render: (g) => Y15.num(tot(g.rows).input) }, { label: '输出', render: (g) => Y15.num(tot(g.rows).output) },
        { label: '缓存读取', render: (g) => Y15.num(tot(g.rows).cache) }, { label: '费用', render: () => '<span class="y15-muted">未上报</span>' }], rows: groups, empty: '范围内还没有请求'
    });
    const limits = ui.table({
      columns: [{ label: '事项', render: (i) => stack('<strong>' + H.dot(i) + ' ' + esc(i.title) + '</strong>', '<small class="y15-muted">' + esc(Y15.ITEM_STATUS[i.status][0]) + '</small>') },
        { label: '已用时间 / 上限', render: (i) => esc(H.dur(i.used)) + ' / ' + esc(H.dur(i.limit)) + ui.meter(i.used, i.limit) }, { label: '轮次', render: (i) => (i.round ? '第 ' + i.round + ' 轮 / 上限 ' + i.round_limit : '<span class="y15-muted">未开始</span>') }],
      rows: p.items.filter((i) => !['adopted', 'open_closed', 'stopped'].includes(i.status))
    });
    return '<h3 class="y15-h3">筛选后的合计</h3>' + totals + '<h3 class="y15-h3">按部门</h3>' + by + '<h3 class="y15-h3">各事项的上限</h3>' + limits +
      '<p class="y15-muted y15-small">「输入（含缓存）」已包含缓存读取，两者不重复相加；用量只读显示，不是事项的预算。</p>';
  }

  let openLoop = null;
  function loopsPanel(p) {
    const L = X.loops[p.id];
    const state = (s) => '<span class="y15-loop is-' + X.loopStates[s][1] + '">' + X.loopStates[s][0] + '</span>';
    const layer = { run: '一次运行', activation: '一轮工作' };
    const row = (id, indent, cols, basis) => '<tr class="y15-loop-row' + (openLoop === id ? ' is-open' : '') + '" data-act="obs.loop" data-id="' + id + '">' + cols.map((c, i) => '<td data-label="' + ['层', '实例', '轮次', '已用量与上限', '收敛状态', '停止原因'][i] + '"><div class="y15-td"' + (i === 1 ? ' style="padding-left:' + indent * 16 + 'px"' : '') + '>' + (c === '' ? '<span class="y15-muted">—</span>' : c) + '</div></td>').join('') + '</tr>' +
      (openLoop === id && basis ? '<tr class="y15-loop-detail"><td colspan="6"><b>判定依据</b> ' + esc(basis) + '</td></tr>' : '');
    const pr = L.project;
    let rowsHtml = row(p.id + '-p', 0, [pr[0], esc(pr[1]), esc(pr[2]), esc(pr[3]), state(pr[4]), ''], pr[6] || '按事项的进度汇总');
    p.items.forEach((it) => {
      const list = L.items[it.id] || [];
      rowsHtml += '<tr class="y15-loop-item"><th colspan="6">' + H.dot(it) + ' ' + esc(it.title) + '</th></tr>';
      list.forEach((r, i) => { rowsHtml += row(it.id + '-' + i, r[0] === 'run' ? 1 : 2, [layer[r[0]], esc(r[1]), esc(r[2]), esc(r[3]), state(r[4]), esc(r[5]) ], r[6]); });
    });
    return '<p class="y15-muted y15-small">每个事项一棵树：项目、一次运行、各部门的一轮工作。收敛状态由事件按规则算出；点一行看判定依据。「不判定」的行写着缺少哪些事实。</p>' +
      '<div class="y15-table-wrap"><table class="y15-table y15-loop-table"><thead><tr><th>层</th><th>实例</th><th>轮次</th><th>已用量与上限</th><th>收敛状态</th><th>停止原因</th></tr></thead><tbody>' + rowsHtml + '</tbody></table></div>';
  }

  Y15.views.register('observe', {
    render(ctx, p) {
      const list = attemptsOf(p);
      const running = list.filter((a) => ['requesting', 'running'].includes(a.status)).length;
      const items = [{ id: 'records', label: '请求记录', count: list.length }, { id: 'usage', label: '用量统计' }, { id: 'loops', label: '循环' }];
      const active = ui.activeTab('y15-obs', items, 'records');
      return '<div class="y15-page">' + head('观测', running + ' 个请求进行中 · 共 ' + list.length + ' 条') +
        ui.block({ title: '模型请求、用量与循环', subtitle: '按部门、事项、状态、模型筛选；请求记录和用量统计用同一组筛选', body: filterBar(p) + ui.tabs({ id: 'y15-obs', items, active }) +
          ui.tabPanels('y15-obs', active, { records: recordsPanel(p, list), usage: usagePanel(p, list), loops: loopsPanel(p) }) }) + '</div>';
    }
  });
  Y15.actions.register('obs.filter', (el) => { filtersOf(Y15.h.pid())[el.dataset.key] = el.value; Y15.rerender(); });
  Y15.actions.register('obs.reset', () => { obs.filters[Y15.h.pid()] = null; Y15.rerender(); });
  Y15.actions.register('obs.loop', (el) => { openLoop = openLoop === el.dataset.id ? null : el.dataset.id; Y15.rerender(); });

  // 请求详情
  Y15.views.register('observe-detail', {
    render(ctx, p) {
      const a = X.attempts.find((x) => x.id === ctx.route.params.attempt);
      if (!a) return '<div class="y15-gate"><h1>找不到这条请求</h1></div>';
      const w = wiring(a);
      const it = H.item(p, a.item);
      const live = ['requesting', 'running'].includes(a.status);
      const diag = ui.kv([['开始', esc(ui.time(a.start))], ['耗时', live ? '<span class="y15-muted">进行中</span>' : esc(fmtMs(a.ms))], ['状态', ui.status(AST[a.status][0], AST[a.status][1])], ['类型', AKIND[a.kind]],
        ['事项', it ? H.dot(it) + ' ' + H.link('#/p/' + p.id + '/w/' + it.id, it.title) : ''], ['部门 · 角色', esc(H.dept(a.dept) + ' · ' + a.role)], ['模型服务', esc(w.provider)],
        ['请求 → 返回', esc(w.model + ' → ' + (a.status === 'failed' ? '未知' : w.model))]].concat(a.err ? [['失败的分类', esc(a.err.category)], ['错误代码', ui.code(a.err.code)]] : [])) + (a.err ? ui.note('错误原文：' + esc(a.err.text), 'warn') : '');
      const target = ui.kv([['连接', esc(w.conn)], ['协议', esc(w.proto)], ['请求地址', ui.code(w.base)], ['上游模型', esc(w.model)], ['容量（窗口 / 最大输出）', Y15.num(w.window) + ' / ' + Y15.num(w.out)],
        ['凭据引用 / 版本', ui.code(w.cred + ' 第 ' + w.cv + ' 版')], ['选择来源', esc(w.src)], ['请求档位 → 发送档位', esc(w.level + ' → ' + w.level)], ['部门提示的版本', '第 ' + (X.deptPrompt[a.dept].indexOf('2') >= 0 ? 2 : 1) + ' 版']]);
      const sections = ui.table({ columns: [{ label: '栏目', render: (r) => esc(r[0]) }, { label: '版本', render: (r) => (r[1] ? ui.tag(r[1]) : '') }, { label: '放进请求', render: (r) => ui.status(r[2] ? 'succeeded' : 'idle', r[2] ? '放进了' : '没放进') }, { label: '原因', render: (r) => esc(r[3]) }], rows: X.sectionsOf(a) });
      const sibs = X.attempts.filter((x) => a.group && x.group === a.group).sort((x, y) => x.start.localeCompare(y.start));
      const sib = sibs.length > 1 ? ui.block({ title: '同一次调用的各次尝试', body: '<div class="y15-sibs">' + sibs.map((s, i) => '<button type="button" class="y15-sib' + (s.id === a.id ? ' is-on' : '') + '" data-go="#/p/' + p.id + '/observe/' + s.id + '"><strong>第 ' + (i + 1) + ' / ' + sibs.length + ' 次</strong><small>' + AST[s.status][1] + ' · ' + esc(ui.time(s.start)) + '</small></button>').join('') + '</div>' }) : '';
      const out = live ? '<p class="y15-muted">还在进行，已经收到的文字：</p>' + ui.pre('读取现有实现，确定入口在 orders/export.ts……\n正在整理要改的文件清单……') : (X.outputOf(a) ? ui.pre(X.outputOf(a)) : '<p class="y15-muted">没有保存的输出。</p>');
      return '<div class="y15-page">' + head(esc(shortId(a.id)) + ' ' + ui.status(AST[a.status][0], AST[a.status][1]), '调用目标、各栏目的来源、用量与上限；输出按保存的内容原样列出', ui.button({ label: '返回请求记录', icon: 'back', go: '#/p/' + p.id + '/observe' })) +
        ui.block({ title: '诊断', body: diag }) + ui.block({ title: '调用目标', subtitle: '请求档位和实际发送的档位分开列出；凭据只显示引用和版本', body: target }) +
        ui.block({ title: '各栏目的来源', subtitle: '每一栏为什么放进请求、有没有放进', body: sections }) +
        ui.block({ title: '用量与上限', body: ui.kv([['输入（含缓存）', Y15.num(a.input)], ['输出', Y15.num(a.output)], ['缓存读取（输入的一部分）', Y15.num(a.cache)], ['费用', '未上报'], ['事项已用时间 / 上限', it ? esc(H.dur(it.used) + ' / ' + H.dur(it.limit)) : '']]) }) + sib +
        ui.block({ title: '输出', body: out }) + '</div>';
    }
  });

  // ================================================================ 设置

  const cfg = { goal: {}, pinned: {}, archived: {}, sources: {}, dept: {}, roles: {}, auth: {}, place: {} };
  const MODELS = () => [...new Set(Object.values(X.wiring).map((w) => w.model).concat(Y15.readyModels ? Y15.readyModels() : []))];

  function deptSetting(pid, d) { return Object.assign({ model: '', prompt: '' }, (cfg.dept[pid] || {})[d]); }

  function settingsPage(ctx, p) {
    const S = X.settings[p.id];
    const archived = Boolean(cfg.archived[p.id]);
    const pinned = p.id in cfg.pinned ? cfg.pinned[p.id] : S.pinned;
    const goal = p.id in cfg.goal ? cfg.goal[p.id] : p.goal;
    const basic = ui.block({ title: '基本信息', body: '<div class="y15-form"><div class="y15-field"><span>名称</span><strong>' + esc(p.name) + '</strong></div>' +
      '<label class="y15-field"><span>长期目标</span><textarea class="y15-textarea" id="set-goal" rows="2"' + (archived ? ' readonly' : '') + '>' + esc(goal) + '</textarea><small class="y15-muted">进行中的事项不受影响，之后开始的事项用新目标。</small></label>' +
      '<div class="y15-row">' + ui.button({ label: '保存长期目标', kind: 'small', act: 'set.goal', disabled: archived }) + '</div>' +
      '<div class="y15-field"><span>置顶</span><div class="y15-row">' + (pinned ? ui.status('done', '已置顶') : '<span class="y15-muted">未置顶</span>') + ui.button({ label: pinned ? '取消置顶' : '置顶', kind: 'small', act: 'set.pin' }) + '</div></div>' +
      '<div class="y15-field"><span>归档</span><div class="y15-row">' + (archived ? ui.status('cancelled', '已归档') : '<span class="y15-muted">未归档</span>') +
      ui.button({ label: archived ? '恢复项目' : '归档', kind: 'small' + (archived ? ' primary' : ' danger'), act: 'set.archive' }) + '</div></div></div>' + (archived ? ui.note('归档以后只读：能看，不能改。', 'warn') : '') });
    const deptCards = p.depts.map((d) => {
      const w = X.wiring[d], s = deptSetting(p.id, d);
      return '<article class="y15-set-dept"><header><h3>' + esc(H.dept(d)) + '部门</h3></header>' + ui.kv([
        ['模型', s.model ? '<strong>' + esc(s.model) + '</strong> <small class="y15-muted">本项目写入</small>' : '<strong>' + esc(w.model) + '</strong> <small class="y15-muted">跟随部门使用</small>'],
        ['推理档位', '请求 ' + esc(w.level) + ' · 发送 ' + esc(w.level)], ['部门提示', ui.tag(s.prompt ? '本项目写入' : X.deptPrompt[d])]], 'is-rows') +
        '<div class="y15-row">' + ui.button({ label: '编辑部门设置', kind: 'small', act: 'set.dept', data: { d }, disabled: archived }) + '</div></article>';
    }).join('');
    const depts = ui.block({ title: '部门设置', subtitle: '只改本项目这个部门；没写入的项跟随模型管理页里的「部门使用」，不会改动它', body: '<div class="y15-set-depts">' + deptCards + '</div>' });
    const srcs = (cfg.sources[p.id] || S.source.slice());
    const source = ui.block({ title: '源目录', subtitle: '登记在这台控制主机上的代码目录：接入已有项目时从这里取快照，采纳的成果可以写回这里。新事项都从项目的起点开始。', body:
      (srcs.length ? ui.table({ columns: [{ label: '名称', render: (r) => ui.code(r.name) }, { label: '路径', render: (r) => '<span class="y15-wrap">' + esc(r.path) + '</span>' },
        { label: '采纳写回', render: (r) => (r.writeback ? ui.status('succeeded', '打开') + ' ' + esc(r.writeback.remote + ' → ' + r.writeback.branch) : '<span class="y15-muted">没有打开</span>') },
        { label: '写回前的检查命令', render: (r) => (r.checks.length ? r.checks.map(ui.code).join(' ') : '<span class="y15-muted">没有</span>') }], rows: srcs }) : ui.empty('还没有登记源目录')) +
      '<h3 class="y15-h3">登记源目录</h3><div class="y15-form"><div class="y15-grid-2"><label class="y15-field"><span>名称</span><input class="y15-input" id="src-name" placeholder="例如 webapp"></label>' +
      '<label class="y15-field"><span>路径</span><input class="y15-input" id="src-path" placeholder="控制主机上的绝对路径"></label></div><div class="y15-row">' + ui.button({ label: '保存源目录', kind: 'primary', act: 'set.source', disabled: archived }) + '<small class="y15-muted">同名登记会覆盖原来的。</small></div></div>' });
    const W = S.writeback;
    const writeback = ui.block({ title: '成果写回', subtitle: '把采纳的成果写回登记的源目录。当前只在本地记录合并请求，还没有在代码托管平台上创建。', actions: ui.button({ label: '写回成果', icon: 'import', kind: 'small primary', act: 'set.writeback', disabled: archived || !W.enabled }),
      body: (W.enabled ? '<p>' + ui.status('succeeded', '采纳写回已打开') + ' <span class="y15-muted">写回到 ' + esc(W.source) + '，目标分支 ' + esc(W.branch) + '</span></p>' : ui.note('源目录还没有打开采纳写回：在上面登记源目录并写明远端与目标分支。', 'info')) +
        (W.records.length ? ui.table({ columns: [{ label: '采纳的成果', render: (r) => esc(r.adoption) }, { label: '结果', render: (r) => ui.status('succeeded', r.text) }, { label: '时间', render: (r) => esc(ui.time(r.at)) }, { label: '说明', render: (r) => esc(r.detail) },
          { label: '合并请求', render: (r) => esc(r.mr) + ' ' + ui.tag('还只是本地记录') }], rows: W.records }) : ui.empty('还没有写回记录')) });
    const ml = Y15.machineList ? Y15.machineList() : [];
    const authSet = cfg.auth[p.id] || ml.filter((m) => m.projects.includes(p.id)).map((m) => m.id);
    const machines = ui.block({ title: '机器授权', subtitle: '从「机器」页登记的机器里，选本项目可以用的；命令在登记的目录里原样执行，不逐条授权。', body: '<div class="y15-set-depts">' + ml.map((m) =>
      '<label class="y15-set-dept"><span class="y15-field is-inline"><input type="checkbox" data-act="set.auth" data-id="' + esc(m.id) + '"' + (authSet.includes(m.id) ? ' checked' : '') + (archived || m.fixed ? ' disabled' : '') + '><span><strong>' + esc(m.name) + '</strong></span></span><small class="y15-muted">' + esc(m.address) + ' · ' + esc(m.purpose) + (m.online ? '' : ' · 离线') + '</small></label>').join('') + '</div>' });
    const place = cfg.place[p.id] || S.place;
    const where = (cur, extra) => '<option value="">' + extra + '</option><option value="local"' + (cur === 'local' ? ' selected' : '') + '>本机进程</option>' + ml.filter((m) => !m.fixed && authSet.includes(m.id)).map((m) => '<option value="' + esc(m.id) + '"' + (cur === m.id ? ' selected' : '') + '>' + esc(m.name) + '</option>').join('');
    const placement = ui.block({ title: '执行位置', subtitle: '运行工作区放在哪里，以及各部门做检查的地方：本机进程，或本项目已授权的机器。', body: '<div class="y15-grid-2">' +
      '<label class="y15-field"><span>运行工作区</span><select class="y15-select" data-act="set.place" data-k="workspace">' + where(place.workspace, '本机进程').replace('<option value="">本机进程</option>', '') + '</select></label>' +
      ['product', 'engineering', 'quality'].filter((d) => p.depts.includes(d)).map((d) => '<label class="y15-field"><span>' + H.dept(d) + '做检查的地方</span><select class="y15-select" data-act="set.place" data-k="' + d + '">' + where(place.checks[d], '和运行工作区相同') + '</select></label>').join('') + '</div>' });
    const mcp = X.tools.mcp.filter((s) => s.project === p.id);
    const mcpBlock = ui.block({ title: 'MCP 服务器', subtitle: '本项目接入的 MCP 服务器和哪些部门可以用；全部项目的汇总在「工具与扩展」', body: mcp.length ? ui.table({ columns: [{ label: '名称', render: (s) => esc(s.name) }, { label: '连接方式', render: (s) => ui.code(s.transport) }, { label: '部门', render: (s) => esc(s.depts.map(H.dept).join('、')) },
      { label: '最近一次状态', render: (s) => ui.status(s.last.ok ? 'succeeded' : 'failed', s.last.text) }], rows: mcp }) : ui.empty('本项目没有接入 MCP 服务器') });
    const rolesBlock = ui.block({ title: '各角色设置', subtitle: '解析顺序：本项目的角色设置、角色默认、本项目的部门设置、部门使用，取第一个写了的', body: p.depts.map((d) => '<section class="y15-set-roles"><h3 class="y15-h3">' + esc(H.dept(d)) + '部门</h3>' + (X.deptRoles[d] || []).map((r) =>
      '<div class="y15-set-role"><strong>' + esc(r) + '</strong><label class="y15-field"><span>模型</span><select class="y15-select" data-act="set.role" data-k="' + esc(d + '|' + r) + '"><option value="">跟随角色默认</option>' + MODELS().map((m) => '<option' + ((cfg.roles[p.id] || {})[d + '|' + r] === m ? ' selected' : '') + '>' + esc(m) + '</option>').join('') + '</select></label></div>').join('') + '</section>').join('') });
    return '<div class="y15-page">' + head('项目设置', esc(p.name) + ' · 基本信息、部门、源目录、机器、执行位置、角色') + basic + depts + source + writeback + machines + placement + mcpBlock + rolesBlock + '</div>';
  }
  Y15.views.register('settings', { render: settingsPage });

  const pidOf = () => Y15.h.pid();
  const A = (name, fn) => Y15.actions.register(name, fn);
  A('set.goal', () => { cfg.goal[pidOf()] = document.getElementById('set-goal').value; ui.toast('已保存长期目标；之后开始的事项使用新目标', 'ok'); });
  A('set.pin', () => { const p = pidOf(); cfg.pinned[p] = !(p in cfg.pinned ? cfg.pinned[p] : X.settings[p].pinned); Y15.rerender(); });
  A('set.archive', () => { const p = pidOf(); cfg.archived[p] = !cfg.archived[p]; Y15.rerender(); });
  A('set.source', () => {
    const p = pidOf(), name = document.getElementById('src-name').value.trim(), path = document.getElementById('src-path').value.trim();
    if (!name || !path) { ui.toast('名称和路径都要填', 'warn'); return; }
    const list = cfg.sources[p] || X.settings[p].source.slice();
    const at = list.findIndex((r) => r.name === name);
    const row = { name, path, writeback: null, checks: [] };
    if (at >= 0) list[at] = row; else list.push(row);
    cfg.sources[p] = list;
    Y15.rerender();
  });
  A('set.writeback', () => ui.toast('已发起写回：写回完成后，这里会多一条记录（演示）', 'ok'));
  A('set.auth', (el) => { const p = pidOf(); const cur = cfg.auth[p] || Y15.machineList().filter((m) => m.projects.includes(p)).map((m) => m.id); cfg.auth[p] = el.checked ? cur.concat(el.dataset.id) : cur.filter((x) => x !== el.dataset.id); Y15.rerender(); });
  A('set.place', (el) => { const p = pidOf(); const cur = cfg.place[p] || JSON.parse(JSON.stringify(X.settings[p].place)); if (el.dataset.k === 'workspace') cur.workspace = el.value || 'local'; else cur.checks[el.dataset.k] = el.value; cfg.place[p] = cur; ui.toast('已保存执行位置', 'ok'); });
  A('set.role', (el) => { const p = pidOf(); (cfg.roles[p] = cfg.roles[p] || {})[el.dataset.k] = el.value; ui.toast('已保存，从这个角色下一次模型请求起生效', 'ok'); });
  A('set.dept', (el) => {
    const p = pidOf(), d = el.dataset.d, s = deptSetting(p, d), w = X.wiring[d];
    ui.modal({ title: '本项目 · ' + H.dept(d) + '部门设置', body: '<div class="y15-form"><p class="y15-small y15-muted">写入本项目这个部门的设置，不会改动「模型管理」里的部门使用。</p>' +
      '<label class="y15-field"><span>模型</span><select class="y15-select" id="dm-model"><option value="">跟随部门使用（当前：' + esc(w.model) + '）</option>' + MODELS().map((m) => '<option' + (s.model === m ? ' selected' : '') + '>' + esc(m) + '</option>').join('') + '</select></label>' +
      '<label class="y15-field"><span>部门提示</span><textarea class="y15-textarea" id="dm-prompt" rows="4" placeholder="留空表示使用内置的提示">' + esc(s.prompt) + '</textarea></label></div>',
      actions: [{ label: '保存', kind: 'primary', act: 'set.dept-save', data: { d }, close: true }, { label: '取消', close: true }] });
  });
  A('set.dept-save', (el) => { const p = pidOf(); (cfg.dept[p] = cfg.dept[p] || {})[el.dataset.d] = { model: document.getElementById('dm-model').value, prompt: document.getElementById('dm-prompt').value }; ui.toast('已保存，从本部门下一次模型请求起生效', 'ok'); Y15.rerender(); });

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

  Y15.views.register('recovery', {
    render(ctx, p) {
      const it = H.item(p, ctx.route.params.item);
      if (!it) return '<div class="y15-gate"><h1>找不到事项</h1></div>';
      const st = recState(it, p);
      const int = p.interruptions.find((x) => x.item === it.id);
      const pills = '<ul class="y15-rc-states">' + RSTATES.map((r) => '<li class="y15-rc-state' + (r[0] === st.s ? ' is-on' : '') + '">' + (r[0] === st.s ? ui.status(r[2], r[1]) : esc(r[1])) + '</li>').join('') + '</ul>';
      const state = ui.block({ title: '恢复状态', subtitle: '事项：' + it.title, body: pills + '<p class="y15-rc-reason">' + esc(st.reason) + '</p>' + '<ul class="y15-rc-rules"><li>Yudao 启动时自动继续中断的运行，并写明最后确认的位置。</li><li>结果未知的动作先按核实方法自动核实；核实不出来的，作为工具结果交还给发出它的会话，由模型决定要不要重做。</li><li>等待模型服务、等待机器都有时长上限，超过以后会请你决定。</li><li>恢复不会清零已用的限额。</li></ul>' });
      const where = int ? ui.block({ title: '中断的位置', body: ui.kv([['被打断的工作', esc(int.what)], ['时间', esc(ui.time(int.at))], ['原因', esc(int.why)], ['现在', ui.status('interrupted', int.state)], ['自动继续', '<span class="y15-muted">还没有自动继续</span>']], 'is-rows') + '<p class="y15-small y15-muted">已开始但没有回执的动作，按核实方法核实；没有未完成的动作时直接自动继续。</p>' }) : '';
      const mine = H.decisions(p.id).filter((d) => d.item === it.id);
      const decide = ui.block({ title: '待你决定', subtitle: '需要你选版本、决定是否继续时，由这里的卡片交给你；结果未知的动作不在这里', body: mine.length ? '<div class="y15-cards">' + mine.map((d) => Y15.cards.one(d)).join('') + '</div>' : ui.empty('没有等你回答的决定') });
      const acts = X.unknownActions[it.id] || [];
      const unknown = ui.block({ title: '结果未知的动作', subtitle: '重新启动或失去联系时结果不明的动作：有核实方法的先自动核实，其余交还给发出它的会话；核实产生新的记录，不改原来的记录', body: acts.length ? '<div class="y15-rc-actions">' + acts.map((a) =>
        '<article class="y15-rc-action"><header>' + ui.status(HK[a.handling], a.handlingText) + ui.code(a.id) + ui.tag('结果未知') + '</header><p><strong>' + esc(a.label) + '</strong></p>' +
        ui.kv([['部门', esc(H.dept(a.dept))], ['发出它的会话', esc(a.session)], a.machine ? ['执行的机器', esc(a.machine)] : null, ['输入依据', esc(a.input)], ['执行前', esc(a.before)], ['执行后', esc(a.after)],
          a.basis ? ['依据', esc(a.basis)] : null, a.result ? ['核实的结果', esc(a.result)] : null, ['时间', esc(ui.time(a.at))]], 'is-rows') + (a.returned ? '<b>交还给会话的工具结果</b>' + ui.pre(a.returned) : '') + '</article>').join('') + '</div>' : ui.empty('没有结果未知的动作：所有动作都有回执') });
      const sess = X.sessionsOf(it);
      const limits = ui.block({ title: '限额与各会话的用量', body: '<div class="y15-rc-limits"><div class="y15-rc-limit is-wide"><span>已用时间 / 上限</span><strong>' + esc(H.dur(it.used)) + ' / ' + esc(H.dur(it.limit)) + '</strong>' + ui.meter(it.used, it.limit, { warnAt: 0.8 }) + '</div>' +
        '<div class="y15-rc-limit"><span>轮次</span><strong>' + it.round + ' / ' + it.round_limit + '</strong></div><div class="y15-rc-limit"><span>等待模型服务（不计入上限）</span><strong>' + (it.status === 'waiting_model' ? esc(H.waited(it.since)) : '无') + '</strong></div></div>' +
        (it.round ? '<h3 class="y15-h3">各会话的用量</h3>' + ui.table({ columns: [{ label: '会话', render: (s) => stack('<strong>' + esc(s.label) + '</strong>', '<small class="y15-muted">' + esc(s.note) + '</small>') }, { label: '已用时间', render: (s) => esc(H.dur(s.sec)) }, { label: '工作轮数', render: (s) => s.acts }, { label: '模型步骤', render: (s) => s.steps }], rows: sess }) : '') +
        '<p class="y15-small y15-muted">恢复不会清零；发出状态不明的请求仍然算在内；用量没有上报时写「未知」，不填零。</p>' });
      const holds = (X.slotHolders[p.id] || []).includes(it.id);
      const owner = ui.block({ title: '谁在执行', body: ui.kv([['当前执行者', it.dept ? '控制主机 · ' + esc(H.dept(it.dept)) : '<span class="y15-muted">没有</span>'], ['执行槽位', holds ? '占用一个执行槽位' : '<span class="y15-muted">没有占用执行槽位</span>']], 'is-rows') + '<p class="y15-small y15-muted">没有迟到的结果。旧执行者迟到的回执，只作为历史记下，不推进状态。</p>' });
      return '<div class="y15-page">' + head('恢复与动作核实 · ' + H.dot(it) + ' ' + esc(it.title), '这个事项的运行状态、中断、结果未知的动作和限额', ui.button({ label: '回到事项', icon: 'back', go: '#/p/' + p.id + '/w/' + it.id })) + state + where + decide + unknown + limits + owner + '</div>';
    }
  });
})();
