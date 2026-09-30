// 观测与请求详情（设计说明第 7.4 节）
(function () {
  'use strict';
  const Y9 = window.Y9;
  const esc = Y9.esc;
  const ui = Y9.ui;

  const STATUS_KIND = { preparing: 'idle', requesting: 'running', running: 'running', succeeded: 'succeeded', failed: 'failed', cancelled: 'cancelled' };
  const KIND_LABELS = { work: '工作请求', compaction: '压缩请求', collaboration: '协作请求', review: '审查请求' };
  const ERROR_LABELS = { timeout: '超时', auth: '认证失败', empty_output: '空输出', rate_limit: '限流', server: '上游服务错误', provider_unavailable: '模型服务不可用' };
  const USAGE_FIELDS = [
    ['input', '输入（含缓存）'],
    ['output', '输出'],
    ['cache_read', '缓存读取（输入子集）'],
    ['total', '总 Token'],
    ['cost', '成本']
  ];
  const PAGE = 30;

  const numberFormat = new Intl.NumberFormat('zh-CN');

  // 每个项目的筛选条件与显示条数；路径参数只在第一次进入时作为筛选的预设
  const st = { filters: {}, limit: {}, preset: null };

  function fmtNum(value) {
    return value === null || value === undefined ? '未上报' : numberFormat.format(value);
  }

  function fmtMs(ms) {
    if (ms === null || ms === undefined) return '—';
    if (ms < 1000) return ms + ' 毫秒';
    return ui.duration(ms / 1000);
  }

  function filtersOf(projectId) {
    if (!st.filters[projectId]) {
      st.filters[projectId] = { department: '', role: '', status: '', provider: '', model: '', text: '' };
    }
    return st.filters[projectId];
  }

  function roleOptions(ctx) {
    if (!Y9.cap.query('role.detail') || !Y9.cap.query('project.settings')) return null;
    const settings = Y9.api.query('project.settings', { project: ctx.projectId }).data;
    if (!settings.roles) return null;
    const out = [];
    Object.keys(settings.roles).forEach((department) => {
      (settings.roles[department] || []).forEach((role) => out.push({ id: role.role_id, name: role.name || role.role_id }));
    });
    return out;
  }

  function limitOf(projectId) {
    if (!st.limit[projectId]) st.limit[projectId] = PAGE;
    return st.limit[projectId];
  }

  function clean(filters) {
    const out = {};
    Object.keys(filters).forEach((key) => { if (filters[key]) out[key] = filters[key]; });
    return out;
  }

  function applyPreset(ctx) {
    if (st.preset === ctx.route.hash) return;
    st.preset = ctx.route.hash;
    const f = filtersOf(ctx.projectId);
    f.department = ctx.route.query.dept || '';
    f.role = ctx.route.query.role && Y9.cap.query('role.detail') ? ctx.route.query.role : '';
    if (ctx.route.query.status) f.status = ctx.route.query.status;
    st.limit[ctx.projectId] = PAGE;
  }

  function attemptsQuery(ctx, filters, limit) {
    const params = { project: ctx.projectId, limit: limit };
    if (ctx.workItemId) params.work_item = ctx.workItemId;
    Object.assign(params, clean(filters));
    return Y9.api.query('project.attempts', params).data;
  }

  function usageQuery(ctx, filters) {
    const params = { project: ctx.projectId };
    if (ctx.workItemId) params.work_item = ctx.workItemId;
    if (filters.department) params.department = filters.department;
    return Y9.api.query('project.usage', params).data;
  }

  function roleName(projectId, roleId) {
    if (!roleId) return null;
    if (!Y9.cap.query('project.settings') || !Y9.cap.query('role.detail')) return roleId;
    const settings = Y9.api.query('project.settings', { project: projectId }).data;
    if (!settings.roles) return roleId;
    let found = null;
    Object.keys(settings.roles).forEach((department) => {
      (settings.roles[department] || []).forEach((role) => { if (role.role_id === roleId) found = role.name; });
    });
    return found || roleId;
  }

  // ---------------------------------------------------------------------------
  // 请求记录

  function filterBar(ctx, data) {
    const f = filtersOf(ctx.projectId);
    const departments = ['product', 'engineering', 'quality'].concat(Y9.cap.query('ops.status') ? ['operations'] : []);
    const statuses = ['preparing', 'requesting', 'running', 'succeeded', 'failed', 'cancelled'];
    const DEPT_LABELS = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
    const STATUS_TEXT = { preparing: '准备中', requesting: '请求中', running: '进行中', succeeded: '成功', failed: '失败', cancelled: '已取消' };
    const select = (key, label, list, labelFn, allLabel) =>
      '<label class="y9-obs-filter"><span>' + esc(label) + '</span><select class="y9-select" data-act="obs.filter" data-key="' + key + '">' +
      '<option value="">' + esc(allLabel) + '</option>' + list.map((value) =>
        '<option value="' + esc(value) + '"' + (value === f[key] ? ' selected' : '') + '>' + esc(labelFn(value)) + '</option>'
      ).join('') + '</select></label>';
    const active = Object.keys(f).some((key) => f[key]);
    const roles = roleOptions(ctx);
    const roleSelect = roles
      ? '<label class="y9-obs-filter"><span>角色</span><select class="y9-select" data-act="obs.filter" data-key="role">' +
        '<option value="">全部角色</option>' + roles.map((role) => '<option value="' + esc(role.id) + '"' + (role.id === f.role ? ' selected' : '') + '>' + esc(role.name) + '</option>').join('') + '</select></label>'
      : '';
    return '<div class="y9-obs-filters">' +
      select('department', '部门', departments, (id) => DEPT_LABELS[id] + '部门', '全部部门') +
      roleSelect +
      select('status', '状态', statuses, (id) => STATUS_TEXT[id], '全部状态') +
      '<label class="y9-obs-filter"><span>Provider</span><input class="y9-input" type="text" data-act="obs.input" data-key="provider" value="' + esc(f.provider) + '" placeholder="全部"></label>' +
      '<label class="y9-obs-filter"><span>模型</span><input class="y9-input" type="text" data-act="obs.input" data-key="model" value="' + esc(f.model) + '" placeholder="请求或返回的模型"></label>' +
      '<label class="y9-obs-filter is-search"><span>搜索</span><input class="y9-input" type="search" data-act="obs.input" data-key="text" value="' + esc(f.text) + '" placeholder="请求编号、错误或输出片段"></label>' +
      (active ? '<button type="button" class="y9-link y9-obs-reset" data-act="obs.reset">清除筛选</button>' : '') +
      '</div><p class="y9-muted y9-small y9-obs-scope">共 ' + esc(data.total) + ' 条记录；事项范围在顶栏的「范围」中选择。</p>';
  }

  function recordsPanel(ctx, data) {
    if (!data.attempts.length) return ui.empty('没有符合筛选条件的请求');
    const columns = [
      { key: 'started_at', label: '开始', className: 'y9-col-status', render: (row) => esc(Y9.ui.time(row.started_at)) },
      { key: 'status', label: '状态', className: 'y9-col-status', render: (row) => ui.status(STATUS_KIND[row.status] || 'idle', row.status_text) },
      { key: 'duration_ms', label: '耗时', className: 'y9-col-status', render: (row) => ['requesting', 'running', 'preparing'].includes(row.status) ? '<span class="y9-muted">进行中</span>' : esc(fmtMs(row.duration_ms)) },
      { key: 'department', label: '部门 · 角色', className: 'y9-col-status', render: (row) => esc(row.department) + (row.role ? '<small class="y9-muted y9-block-line">' + esc(roleName(ctx.projectId, row.role)) + '</small>' : '') },
      { key: 'requested_model', label: '请求', render: (row) => '<div class="y9-cell-stack"><span class="y9-obs-model">' + esc(row.requested_model || '—') + '</span><small class="y9-muted">' + esc(row.provider || '') + '</small></div>' },
      { key: 'actual_model', label: '返回', render: (row) => row.actual_model ? '<span class="y9-obs-model">' + esc(row.actual_model) + '</span>' : '<span class="y9-muted">未知</span>' },
      { key: 'kind', label: '请求类型', className: 'y9-col-status', render: (row) => esc(KIND_LABELS[row.kind] || row.kind || '') },
      { key: 'usage', label: '输入 / 输出', className: 'y9-col-status', render: (row) => row.usage ? '<span class="y9-obs-num">' + esc(fmtNum(row.usage.input)) + ' / ' + esc(fmtNum(row.usage.output)) + '</span>' : '<span class="y9-muted">未知</span>' },
      { key: 'ops', label: '详情', className: 'y9-col-actions', render: (row) => ui.button({ label: '查看', kind: 'small', go: Y9.paths.observeDetail(ctx.projectId, row.id, row.work_item_id) }) }
    ];
    const more = data.total > data.attempts.length
      ? '<div class="y9-row y9-obs-more">' + ui.button({ label: '加载更多（还有 ' + (data.total - data.attempts.length) + ' 条）', kind: 'small', act: 'obs.more' }) + '</div>'
      : '';
    return '<p class="y9-muted y9-small">用量没有上报时显示「未知」，不填 0；请求与返回的模型分开列出。</p>' + ui.table({ columns: columns, rows: data.attempts }) + more;
  }

  function bar(value, max) {
    const ratio = value && max ? Math.min(1, value / max) : 0;
    return '<span class="y9-obs-bar" aria-hidden="true"><span style="width:' + (ratio * 100).toFixed(1) + '%"></span></span>';
  }

  function usagePanel(ctx, filters) {
    const usage = usageQuery(ctx, filters);
    const totals = '<div class="y9-obs-totals">' + USAGE_FIELDS.map(([key, label]) =>
      '<div class="y9-obs-total"><span>' + esc(label) + '</span><strong>' + (key === 'cost' && usage.totals.cost === null ? '未上报' : esc(fmtNum(usage.totals[key]))) + '</strong></div>'
    ).join('') + '</div>';
    const max = usage.groups.reduce((m, group) => Math.max(m, group.total || 0), 0);
    const groups = usage.groups.length
      ? ui.table({
        columns: [
          { key: 'department', label: '分组', render: (row) => '<div class="y9-cell-stack"><strong>' + esc(row.department) + '部门</strong>' + bar(row.total, max) + '</div>' },
          { key: 'attempts', label: '尝试', render: (row) => esc(row.attempts) },
          { key: 'input', label: '输入（含缓存）', render: (row) => '<span class="y9-obs-num">' + esc(fmtNum(row.input)) + '</span>' },
          { key: 'output', label: '输出', render: (row) => '<span class="y9-obs-num">' + esc(fmtNum(row.output)) + '</span>' },
          { key: 'cache_read', label: '缓存读取（输入子集）', render: (row) => '<span class="y9-obs-num">' + esc(fmtNum(row.cache_read)) + '</span>' },
          { key: 'total', label: '总 Token', render: (row) => '<span class="y9-obs-num">' + esc(fmtNum(row.total)) + '</span>' },
          { key: 'cost', label: '成本', render: (row) => (row.cost === null ? '<span class="y9-muted">未上报</span>' : esc(row.cost)) }
        ],
        rows: usage.groups
      })
      : ui.empty('范围内还没有调用尝试');
    const limits = usage.limits.length
      ? ui.table({
        columns: [
          { key: 'title', label: '事项', render: (row) => '<div class="y9-cell-stack"><strong>' + esc(row.title) + '</strong><small class="y9-muted">' + esc(row.phase) + '</small></div>' },
          { key: 'time', label: '已用时间 / 时间上限', render: (row) => '<div class="y9-obs-limit"><span>' + esc(Y9.ui.duration(row.elapsed_sec)) + ' / ' + esc(Y9.ui.duration(row.limit_sec)) + '</span>' + ui.meter(row.elapsed_sec, row.limit_sec) + '</div>' },
          { key: 'cycle', label: '循环次数', render: (row) => (row.cycle ? esc('第 ' + row.cycle + ' 轮') : '<span class="y9-muted">未开始</span>') },
          { key: 'waiting', label: '等待模型服务', render: (row) => (row.waiting_provider_sec !== undefined ? esc(Y9.ui.duration(row.waiting_provider_sec)) + '（不计入上限）' : '<span class="y9-muted">—</span>') }
        ],
        rows: usage.limits
      })
      : ui.empty('没有运行中的 run');
    return '<h3 class="y9-h3">筛选总计</h3>' + totals + '<h3 class="y9-h3">按部门</h3>' + groups + '<h3 class="y9-h3">运行限制</h3>' + limits +
      '<p class="y9-muted y9-small">输入（含缓存）与缓存读取（输入子集）不重复相加；用量只读显示，不是事项的预算。</p>';
  }

  function resultsHtml(ctx) {
    const f = filtersOf(ctx.projectId);
    const data = attemptsQuery(ctx, f, limitOf(ctx.projectId));
    const items = [
      { id: 'records', label: '请求记录', count: data.total },
      { id: 'usage', label: '用量统计' }
    ];
    const active = ui.activeTab('y9-obs', items, 'records');
    return ui.tabs({ id: 'y9-obs', items: items, active: active }) +
      ui.tabPanels('y9-obs', active, { records: recordsPanel(ctx, data), usage: usagePanel(ctx, f) });
  }

  function render(ctx) {
    applyPreset(ctx);
    const data = attemptsQuery(ctx, filtersOf(ctx.projectId), limitOf(ctx.projectId));
    const inFlight = data.attempts.filter((row) => ['requesting', 'running'].includes(row.status)).length;
    const head = '<header class="y9-page-head"><div class="y9-page-titles"><p class="y9-eyebrow">观测 · ' + esc(ctx.workItemId ? '事项范围' : '整个项目') + '</p><h1>模型请求</h1>' +
      '<p class="y9-subtitle">' + esc(inFlight) + ' 个请求进行中 · 共 ' + esc(data.total) + ' 条记录。调用目标、按栏目的来源与用量、运行限制都在这里；用量只读显示。</p></div></header>';
    return '<div class="y9-obs">' + head + ui.block({
      title: '请求记录与用量', query: ['project.attempts', 'project.usage'],
      subtitle: '按部门、状态、Provider 与模型筛选；两个页签使用同一组筛选。',
      body: filterBar(ctx, data) + '<div data-obs-results>' + resultsHtml(ctx) + '</div>'
    }) + '</div>';
  }

  function refresh() {
    const ctx = Y9.app.ctx();
    const data = attemptsQuery(ctx, filtersOf(ctx.projectId), limitOf(ctx.projectId));
    const bar = document.querySelector('.y9-obs-filters');
    if (!bar) return;
    const holder = document.createElement('div');
    holder.innerHTML = filterBar(ctx, data);
    bar.nextElementSibling.remove();
    bar.replaceWith.apply(bar, holder.childNodes);
    const results = document.querySelector('[data-obs-results]');
    if (results) results.innerHTML = resultsHtml(ctx);
  }

  Y9.views.register('observe', {
    title: () => '观测',
    needs: { queries: ['project.attempts', 'project.usage'] },
    scope: (ctx) => ({ project: ctx.projectId }),
    render: render,
    update(ctx, root) {
      const results = root.querySelector('[data-obs-results]');
      if (results) results.innerHTML = resultsHtml(ctx);
    }
  });

  Y9.actions.register('obs.filter', (el) => {
    const ctx = Y9.app.ctx();
    filtersOf(ctx.projectId)[el.dataset.key] = el.value;
    limitOf(ctx.projectId);
    refresh();
  });

  Y9.actions.register('obs.input', (el) => {
    const ctx = Y9.app.ctx();
    filtersOf(ctx.projectId)[el.dataset.key] = el.value;
  });

  Y9.actions.register('obs.reset', () => {
    const ctx = Y9.app.ctx();
    filtersOf(ctx.projectId);
    Object.keys(st.filters[ctx.projectId]).forEach((key) => { st.filters[ctx.projectId][key] = ''; });
    refresh();
  });

  Y9.actions.register('obs.more', () => {
    const ctx = Y9.app.ctx();
    st.limit[ctx.projectId] = limitOf(ctx.projectId) + PAGE;
    refresh();
  });

  // ---------------------------------------------------------------------------
  // 请求详情

  function detail(ctx) {
    return Y9.api.query('run.attempt', { attempt: ctx.route.params.attemptId }).data;
  }

  function diagnosticsBlock(d) {
    const pairs = [
      ['开始', esc(Y9.ui.time(d.started_at))],
      ['耗时', ['requesting', 'running', 'preparing'].includes(d.status) ? '<span class="y9-muted">进行中</span>' : esc(fmtMs(d.duration_ms))],
      ['状态', ui.status(STATUS_KIND[d.status] || 'idle', d.status_text)],
      ['请求类型', esc(KIND_LABELS[d.kind] || d.kind || '')],
      ['Provider', esc(d.provider || '—')],
      ['请求 → 返回', esc((d.requested_model || '—') + ' → ' + (d.actual_model || '未知'))]
    ];
    const err = d.error;
    if (err) {
      pairs.push(['错误分类', esc(ERROR_LABELS[err.category] || err.category)]);
      pairs.push(['错误代码', ui.code(err.code || '—')]);
    }
    return ui.block({
      title: '诊断', query: 'run.attempt',
      body: ui.kv(pairs) + (err ? ui.note('错误原文：' + esc(err.text || ''), 'warn') : '')
    });
  }

  function targetBlock(d) {
    const t = d.target || {};
    return ui.block({
      title: '调用目标', query: 'run.attempt',
      subtitle: '请求档位与实际发送的档位分开列出；凭据只显示引用与版本。',
      body: ui.kv([
        ['连接', esc(t.connection_name || t.connection || '—')],
        ['协议', esc(t.protocol || '—')],
        ['请求基址', t.base_url ? ui.code(t.base_url) : ''],
        ['上游模型', esc(t.model || '—')],
        ['容量（窗口 / 输出上限）', (t.window || t.max_output) ? esc(fmtNum(t.window) + ' / ' + fmtNum(t.max_output)) : ''],
        ['凭据引用 / 版本', t.credential_ref ? ui.code(t.credential_ref + ' v' + (t.credential_version === null || t.credential_version === undefined ? '—' : t.credential_version)) : ''],
        ['选择来源', esc(t.source || '—')],
        ['请求档位 → 发送档位', esc((t.request_level || '模型默认') + ' → ' + (t.sent_level || '不带推理参数'))],
        ['部门 Prompt 版本', 'v' + esc(t.prompt_version === null || t.prompt_version === undefined ? '—' : t.prompt_version)]
      ])
    });
  }

  function limitBlock(d) {
    const l = d.limits || {};
    return ui.block({
      title: '运行限制', query: 'run.attempt',
      subtitle: '时间上限与已用时间、循环次数；等待模型服务的时间单独列出，不计入上限。',
      body: ui.kv([
        ['已用时间 / 时间上限', esc(Y9.ui.duration(l.elapsed_sec || 0) + ' / ' + Y9.ui.duration(l.limit_sec || 0))],
        ['循环次数', l.cycle ? esc('第 ' + l.cycle + ' 轮') : '<span class="y9-muted">未开始</span>'],
        ['等待模型服务', l.waiting_provider_sec !== undefined ? esc(Y9.ui.duration(l.waiting_provider_sec)) : '']
      ])
    });
  }

  function sectionsBlock(d) {
    const rows = (d.sections || []).map((section) => ({
      label: section.label,
      version: section.version,
      included: section.included,
      reason: section.reason
    }));
    return ui.block({
      title: '按栏目的来源', query: 'run.attempt',
      subtitle: '每一栏放入原因与是否装入；没有上报原因时留空。',
      body: rows.length
        ? ui.table({
          columns: [
            { key: 'label', label: '栏目' },
            { key: 'version', label: '版本', render: (row) => (row.version ? ui.tag(row.version) : '') },
            { key: 'included', label: '装入', render: (row) => ui.status(row.included ? 'succeeded' : 'idle', row.included ? '装入' : '未装入') },
            { key: 'reason', label: '原因', render: (row) => esc(row.reason || '') }
          ],
          rows: rows
        })
        : ui.empty('这次请求没有对应的 Context 快照')
    });
  }

  function siblingBlock(d) {
    if (!d.siblings || !d.siblings.length) return '';
    return ui.block({
      title: '同一次逻辑调用的尝试', query: 'run.attempt',
      body: '<div class="y9-obs-sibs">' + d.siblings.map((sib) =>
        '<button type="button" class="y9-obs-sib' + (sib.id === d.id ? ' is-on' : '') + '" data-go="' + esc(Y9.paths.observeDetail(Y9.app.ctx().projectId, sib.id, d.work_item_id)) + '">' +
        '<strong>第 ' + esc(sib.n) + '/' + esc(sib.of) + ' 次</strong><small>' + esc(sib.status_text || sib.status) + ' · ' + esc(Y9.ui.time(sib.started_at)) + '</small></button>'
      ).join('') + '</div>'
    });
  }

  function liveBlock(d) {
    if (!d || !['preparing', 'requesting', 'running'].includes(d.status)) return '';
    if (!Y9.cap.query('attempt.live')) return '';
    return ui.block({
      title: '已收到的文字', query: 'attempt.live',
      subtitle: '调用尝试进行中，这里显示已收到的输出文字；结束后以本页下方输出的最终内容为准。',
      body: '<div data-live>' + liveHtml(d.id) + '</div>'
    });
  }

  function liveHtml(attemptId) {
    const live = Y9.api.query('attempt.live', { attempt: attemptId }).data;
    return ui.kv([['状态', esc(live.status_text)], ['字数', esc(live.chars)]]) +
      (live.text ? ui.pre(live.text) : '<p class="y9-muted">还没有收到文字。</p>');
  }

  function renderDetail(ctx) {
    const d = detail(ctx);
    return '<div class="y9-obs">' +
      '<div class="y9-row y9-obs-back">' + ui.button({ label: '返回请求记录', icon: 'back', kind: 'small', go: Y9.paths.observe(ctx.projectId, ctx.workItemId) }) + '</div>' +
      '<header class="y9-page-head"><div class="y9-page-titles"><p class="y9-eyebrow">请求详情 · 事项 ' + esc(d.work_item_id) + '</p>' +
      '<div class="y9-obs-title"><h1>' + esc(d.id) + '</h1>' + ui.status(STATUS_KIND[d.status] || 'idle', d.status_text) + '</div>' +
      '<p class="y9-subtitle">调用目标、按栏目的来源与用量、运行限制；输出与输入按保存的内容原样列出。</p></div></header>' +
      diagnosticsBlock(d) + liveBlock(d) + targetBlock(d) + sectionsBlock(d) + limitBlock(d) + siblingBlock(d) +
      ui.block({
        title: '输出与输入', query: 'run.attempt',
        body: (d.output ? '<h3 class="y9-h3">输出</h3>' + ui.pre(d.output) : '<p class="y9-muted">没有保存的输出。</p>') +
          (d.input ? '<h3 class="y9-h3">输入</h3>' + ui.pre(d.input) : '') +
          (d.semantic_view && d.semantic_view.length ? '<h3 class="y9-h3">语义视图 ' + ui.tag('Stage 5') + '</h3>' + ui.pre(JSON.stringify(d.semantic_view, null, 2)) : '')
      }) +
      '</div>';
  }

  Y9.views.register('observe-detail', {
    title: () => '请求详情',
    needs: { queries: ['run.attempt'] },
    render: renderDetail,
    mount(ctx, root) {
      const d = detail(ctx);
      if (!['preparing', 'requesting', 'running'].includes(d.status) || !Y9.cap.query('attempt.live')) return;
      st.timer = setInterval(() => {
        const holder = document.querySelector('[data-live]');
        if (!holder || !Y9.api.connected()) return;
        holder.innerHTML = liveHtml(d.id);
      }, 2000);
    },
    unmount() {
      if (st.timer) {
        clearInterval(st.timer);
        st.timer = null;
      }
    }
  });
})();
