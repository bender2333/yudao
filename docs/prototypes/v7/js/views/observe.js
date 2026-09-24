// 观测（设计说明第 4.5 节）：请求记录、用量统计、运行限制与请求详情；调用目标（D24）、语义视图与按角色筛选（Stage 4）
(function () {
  'use strict';

  const Y7 = window.Y7;
  const esc = Y7.esc;
  const ui = Y7.ui;

  const KIND_LABELS = { work: '工作请求', compaction: '压缩请求', collaboration: '协作请求' };
  const STATUS_KIND = { preparing: 'idle', requesting: 'running', running: 'running', succeeded: 'succeeded', failed: 'failed', cancelled: 'cancelled' };
  const IN_FLIGHT = ['requesting', 'running'];
  const ERROR_LABELS = { timeout: '超时', auth: '认证失败', empty_output: '空输出', rate_limit: '限流', server: '上游服务错误' };
  const FILTER_KEYS = ['department', 'role', 'status', 'provider', 'requestedModel', 'actualModel', 'q'];
  const USAGE_FIELDS = [
    { key: 'input', label: '输入（含缓存）' },
    { key: 'output', label: '输出' },
    { key: 'cacheRead', label: '缓存读取（输入子集）' },
    { key: 'total', label: '总 Token' },
    { key: 'cost', label: '成本' }
  ];
  const PAGE = 20;

  // 页面自己的界面状态：每个项目的筛选条件与显示条数；路径参数只在第一次进入时作为筛选
  const st = { filters: {}, limit: {}, presetHash: null };

  const numberFormat = new Intl.NumberFormat('zh-CN');

  function fmtMs(ms) {
    if (ms === null || ms === undefined) return '—';
    if (ms < 1000) return ms + ' 毫秒';
    if (ms < 60000) return (ms / 1000).toFixed(1).replace(/\.0$/, '') + ' 秒';
    return Y7.ui.duration(ms / 1000);
  }

  function fmtTokens(value) {
    return value === null || value === undefined ? '未上报' : numberFormat.format(value);
  }

  function plusMs(iso, ms) {
    return new Date(new Date(iso).getTime() + ms).toISOString();
  }

  function byStartDesc(a, b) {
    return String(b.startedAt || '').localeCompare(String(a.startedAt || ''));
  }

  function roleName(roleId) {
    if (!roleId) return null;
    const catalog = Y7.resolve(Y7.data.catalog).roleCatalog;
    if (!catalog) return roleId;
    for (const dept of ['product', 'engineering', 'quality']) {
      const found = (catalog[dept] || []).find((role) => role.id === roleId);
      if (found) return found.name;
    }
    return roleId;
  }

  function filtersOf(projectId) {
    if (!st.filters[projectId]) {
      st.filters[projectId] = {};
      FILTER_KEYS.forEach((key) => { st.filters[projectId][key] = ''; });
    }
    return st.filters[projectId];
  }

  // ---------------------------------------------------------------------------
  // 数据：范围内的调用尝试

  function scopePairs(projectId, workItemId) {
    const items = workItemId ? [Y7.workItem(workItemId)] : Y7.workItemsOf(projectId);
    return items.filter(Boolean)
      .map((item) => ({ item, run: item.runId ? Y7.run(item.runId) : null }))
      .filter((pair) => pair.run);
  }

  function allAttempts(projectId, workItemId) {
    const out = [];
    scopePairs(projectId, workItemId).forEach(({ item, run }) => {
      run.attempts.forEach((att) => out.push(Object.assign({ workItemId: item.id, workItemTitle: item.title, runId: run.id }, att)));
    });
    return out.sort(byStartDesc);
  }

  function matchesText(att, q) {
    const text = q.toLowerCase();
    return [att.id, att.logicalCallId, att.provider, att.requestedModel, att.actualModel, att.workItemTitle, att.error ? att.error.text : null, att.error ? att.error.code : null]
      .some((value) => value && String(value).toLowerCase().includes(text));
  }

  function applyFilters(list, f) {
    return list.filter((att) =>
      (!f.department || att.department === f.department) &&
      (!f.role || att.role === f.role) &&
      (!f.status || att.status === f.status) &&
      (!f.provider || att.provider === f.provider) &&
      (!f.requestedModel || att.requestedModel === f.requestedModel) &&
      (!f.actualModel || (f.actualModel === '__unknown' ? !att.actualModel : att.actualModel === f.actualModel)) &&
      (!f.q || matchesText(att, f.q))
    );
  }

  function cleanFilters(filters) {
    const f = Object.assign({}, filters || {});
    if (!Y7.atLeast('s4')) f.role = '';
    return f;
  }

  function uniq(list) {
    return list.filter((value, index) => value && list.indexOf(value) === index);
  }

  // ---------------------------------------------------------------------------
  // 查询

  // 请求记录：筛选、状态、尝试 n/m、进行中数量与已发出数量
  Y7.queries.register('project.attempts', (params) => {
    const projectId = params.projectId || Y7.state.projectId;
    if (!Y7.project(projectId)) throw new Error('项目不在当前档位或不存在：' + projectId);
    const all = allAttempts(projectId, params.workItemId || null);
    const items = applyFilters(all, cleanFilters(params.filters));
    return {
      total: all.length,
      matched: items.length,
      sent: all.filter((att) => att.status !== 'preparing').length,
      inFlight: all.filter((att) => IN_FLIGHT.includes(att.status)).length,
      items: params.limit ? items.slice(0, params.limit) : items,
      options: {
        departments: uniq(all.map((att) => att.department)),
        roles: Y7.atLeast('s4') ? uniq(all.map((att) => att.role)) : [],
        statuses: uniq(all.map((att) => att.status)),
        providers: uniq(all.map((att) => att.provider)),
        requestedModels: uniq(all.map((att) => att.requestedModel)),
        actualModels: uniq(all.map((att) => att.actualModel)),
        hasUnknownActual: all.some((att) => !att.actualModel)
      }
    };
  });

  function sumUsage(list) {
    const out = { count: list.length, inFlight: list.filter((att) => IN_FLIGHT.includes(att.status)).length };
    USAGE_FIELDS.forEach((field) => { out[field.key] = null; });
    list.forEach((att) => {
      if (!att.usage) return;
      USAGE_FIELDS.forEach((field) => {
        const value = att.usage[field.key];
        if (value !== null && value !== undefined) out[field.key] = (out[field.key] || 0) + value;
      });
    });
    return out;
  }

  function groupBy(list, keyFn, labelFn) {
    const keys = uniq(list.map(keyFn).map((key) => key || '__none'));
    return keys.map((key) => Object.assign({ key, label: labelFn(key) }, sumUsage(list.filter((att) => (keyFn(att) || '__none') === key))));
  }

  // 用量统计与运行限制：覆盖率、按部门、按模型、按角色（s4）；用量只读，不是预算
  Y7.queries.register('project.usage', (params) => {
    const projectId = params.projectId || Y7.state.projectId;
    if (!Y7.project(projectId)) throw new Error('项目不在当前档位或不存在：' + projectId);
    const items = applyFilters(allAttempts(projectId, params.workItemId || null), cleanFilters(params.filters));
    const sent = items.filter((att) => att.status !== 'preparing');
    const out = {
      prepared: items.length - sent.length,
      coverage: {
        reported: sent.filter((att) => att.usage).length,
        sent: sent.length,
        fields: USAGE_FIELDS.map((field) => ({ key: field.key, label: field.label, count: sent.filter((att) => att.usage && att.usage[field.key] !== null && att.usage[field.key] !== undefined).length }))
      },
      totals: sumUsage(items),
      byDepartment: groupBy(items, (att) => att.department, (key) => Y7.deptLabel(key) + '部门'),
      byModel: groupBy(items, (att) => att.requestedModel, (key) => key),
      byRole: Y7.atLeast('s4') ? groupBy(items, (att) => att.role, (key) => (key === '__none' ? '没有角色' : roleName(key))) : null,
      limits: scopePairs(projectId, params.workItemId || null).map(({ item, run }) => ({
        item, runId: run.id, phase: run.phase, cycle: run.cycle, elapsedSec: run.elapsedSec, limitSec: run.limitSec,
        counters: Y7.atLeast('s3') && run.recovery ? run.recovery.limits : null,
        display: Y7.workItemStatus(item, run)
      }))
    };
    return out;
  });

  // 由调用尝试的记录整理出的事件列表
  function attemptEvents(att, siblings) {
    const events = [{ at: att.startedAt, type: 'model_requested', text: '发出' + (KIND_LABELS[att.kind] || '请求') + '：' + att.provider + ' / ' + att.requestedModel + ' · 第 ' + att.n + '/' + att.of + ' 次' }];
    if (att.status !== 'preparing') {
      events.push({ at: plusMs(att.startedAt, 200), type: 'model_request_serialized', text: att.target ? '按 ' + att.target.protocol + ' 协议编码并发出' + (att.target.sentLevel ? '，推理档位 ' + att.target.sentLevel : '，不带推理参数') : '请求已编码并发出' });
    }
    if (att.status === 'succeeded') {
      events.push({ at: plusMs(att.startedAt, att.durationMs || 0), type: 'model_attempt_finished', text: '完成：返回 ' + (att.actualModel || '未知') + (att.usage ? ' · 输入 ' + fmtTokens(att.usage.input) + ' · 输出 ' + fmtTokens(att.usage.output) : ' · 用量未上报') });
    } else if (att.status === 'failed') {
      events.push({ at: plusMs(att.startedAt, att.durationMs || 0), type: 'model_attempt_failed', text: '失败：' + (att.error ? att.error.text : '原因未记录') });
      const next = siblings.find((entry) => entry.n === att.n + 1);
      if (next) events.push({ at: plusMs(att.startedAt, (att.durationMs || 0) + 1000), type: 'model_retry_scheduled', text: '等待后第 ' + next.n + '/' + next.of + ' 次请求；重试期间事项不提前标为失败' });
    } else if (IN_FLIGHT.includes(att.status)) {
      events.push({ at: att.startedAt, type: 'model_stream_progress', text: '等待模型响应' });
    } else if (att.status === 'cancelled') {
      events.push({ at: plusMs(att.startedAt, att.durationMs || 0), type: 'model_attempt_cancelled', text: '已取消' });
    }
    return events;
  }

  function requestDoc(att, context) {
    const doc = { attempt_id: att.id, logical_call_id: att.logicalCallId, kind: att.kind, provider: att.provider, model: att.requestedModel };
    if (att.target) {
      doc.protocol = att.target.protocol;
      doc.base_url = att.target.baseUrl;
      doc.reasoning = att.target.sentLevel ? { level: att.target.sentLevel } : null;
      doc.max_output_tokens = att.target.maxOutput;
      doc.department_prompt_version = att.target.promptVersion;
    }
    doc.input = context ? context.sources.filter((src) => src.included).map((src) => ({ source: src.label, version: src.version })) : '没有对应的 Context 快照';
    if (att.semanticUnits && att.semanticUnits.length) doc.semantic_view = att.semanticUnits;
    return doc;
  }

  function responseDoc(att) {
    if (att.status === 'preparing') return null;
    if (IN_FLIGHT.includes(att.status)) return null;
    return { status: att.status, model: att.actualModel, usage: att.usage, error: att.error };
  }

  // 请求详情：诊断、同次调用的尝试、调用目标（s3）、语义视图（s4）、概览、Request、Response、事件
  Y7.queries.register('run.attempt', (params) => {
    const projectId = params.projectId || Y7.state.projectId;
    if (!Y7.project(projectId)) throw new Error('项目不在当前档位或不存在：' + projectId);
    let found = null;
    scopePairs(projectId, null).forEach(({ item, run }) => {
      const att = run.attempts.find((entry) => entry.id === params.attemptId);
      if (att) found = { item, run, att };
    });
    if (!found) return null;
    const { item, run, att } = found;
    const siblings = run.attempts.filter((entry) => entry.logicalCallId === att.logicalCallId).slice().sort((a, b) => a.n - b.n);
    const context = run.contexts && run.contexts[att.department] ? run.contexts[att.department].find((ctx) => ctx.attemptId === att.id) || null : null;
    const deptAttempts = run.attempts.filter((entry) => entry.department === att.department).slice().sort((a, b) => String(a.startedAt).localeCompare(String(b.startedAt)));
    const next = deptAttempts[deptAttempts.indexOf(att) + 1] || null;
    const tools = (run.actions || []).filter((act) => act.department === att.department && act.at >= att.startedAt && (!next || act.at < next.startedAt));
    const collaboration = att.kind === 'collaboration'
      ? (run.requests || []).filter((req) => req.to === att.department && (!req.askedAt || req.askedAt <= att.startedAt))
      : [];
    let semantic = null;
    if (Y7.atLeast('s4')) {
      const records = Y7.resolve(Y7.data.semantic)[projectId] || null;
      const units = records ? records.units : [];
      const listed = (att.semanticUnits || []).map((ref) => Object.assign({ version: ref.version }, units.find((unit) => unit.id === ref.id) || { id: ref.id, type: '—', text: '（语义记录中没有这个单元）', status: 'invalid' }));
      const visibleScope = Y7.deptLabel(att.department) + '私有';
      const notListed = units.filter((unit) => (unit.status === 'valid' || unit.status === 'conflict') && (unit.scope === '项目共享' || unit.scope === visibleScope) && !listed.some((entry) => entry.id === unit.id)).length;
      semantic = { listed, notListed, compaction: att.kind === 'compaction' };
    }
    const prompt = run.prompts ? run.prompts[att.department] || null : null;
    return {
      attempt: att,
      item,
      run: { id: run.id, phase: run.phase, cycle: run.cycle },
      siblings,
      context,
      tools: tools.map((act) => Object.assign({}, act)),
      collaboration,
      semantic,
      promptVersion: att.target ? att.target.promptVersion : (prompt ? prompt.requestVersion : null),
      events: attemptEvents(att, siblings),
      request: requestDoc(att, context),
      response: responseDoc(att)
    };
  });

  // ---------------------------------------------------------------------------
  // 渲染：请求记录

  function statusChip(att) {
    return ui.status(STATUS_KIND[att.status], Y7.ATTEMPT_LABELS[att.status] + ' · 第 ' + att.n + '/' + att.of + ' 次');
  }

  function usageCell(att) {
    if (IN_FLIGHT.includes(att.status) || att.status === 'preparing') return '<span class="y7-muted">等待响应</span>';
    if (!att.usage) return '<span class="y7-muted">未知</span>';
    return '<span class="y7-obs-num">' + esc(fmtTokens(att.usage.input)) + ' / ' + esc(fmtTokens(att.usage.output)) + '</span>';
  }

  function listTable(ctx, data) {
    const pid = ctx.project.id;
    const w = ctx.workItem ? ctx.workItem.id : null;
    const columns = [
      { key: 'startedAt', label: '开始', className: 'y7-col-status', render: (row) => esc(Y7.ui.time(row.startedAt)) },
      { key: 'status', label: '状态', className: 'y7-col-status', render: (row) => statusChip(row) },
      { key: 'durationMs', label: '耗时', className: 'y7-col-status', render: (row) => IN_FLIGHT.includes(row.status) ? '<span class="y7-muted">进行中</span>' : esc(fmtMs(row.durationMs)) }
    ];
    if (!w) columns.push({ key: 'workItemTitle', label: '事项' });
    columns.push(
      { key: 'department', label: Y7.atLeast('s4') ? '部门 · 角色' : '部门', className: 'y7-col-status', render: (row) => esc(Y7.deptLabel(row.department) + '部门') + (row.role ? '<small class="y7-muted y7-block-line">' + esc(roleName(row.role)) + '</small>' : '') },
      { key: 'requested', label: '请求', render: (row) => '<div class="y7-cell-stack"><span class="y7-obs-model">' + esc(row.requestedModel) + '</span><small class="y7-muted">' + esc(row.provider) + '</small></div>' },
      { key: 'actual', label: '返回', render: (row) => row.actualModel ? '<span class="y7-obs-model">' + esc(row.actualModel) + '</span>' : '<span class="y7-muted">未知</span>' },
      { key: 'kind', label: '请求类型', className: 'y7-col-status', render: (row) => esc(KIND_LABELS[row.kind] || row.kind) },
      { key: 'usage', label: '输入 / 输出', className: 'y7-col-status', render: usageCell },
      { key: 'ops', label: '详情', className: 'y7-col-actions', render: (row) => ui.button({ label: '查看', kind: 'small', go: Y7.paths.observeDetail(pid, row.id, w) }) }
    );
    return ui.table({ columns, rows: data.items, empty: '没有符合筛选条件的请求' });
  }

  function recordsPanel(ctx, data) {
    const pid = ctx.project.id;
    const limit = st.limit[pid] || PAGE;
    const more = data.matched > limit
      ? '<div class="y7-row y7-obs-more">' + ui.button({ label: '加载更多（还有 ' + (data.matched - limit) + ' 条）', kind: 'small', act: 'obs.more' }) + '</div>'
      : '';
    return '<p class="y7-muted y7-small">' + esc(data.matched === data.total ? '共 ' + data.total + ' 条记录' : '符合筛选 ' + data.matched + ' 条 / 共 ' + data.total + ' 条') + ' · 用量没有上报时显示「未知」，不填 0。</p>' +
      listTable(ctx, data) + more;
  }

  function bar(value, max) {
    const ratio = value && max ? Math.min(1, value / max) : 0;
    return '<span class="y7-obs-bar" aria-hidden="true"><span style="width:' + (ratio * 100).toFixed(1) + '%"></span></span>';
  }

  function groupTable(groups, title) {
    const max = groups.reduce((m, g) => Math.max(m, g.total || 0), 0);
    return '<h3 class="y7-h3">' + esc(title) + '</h3>' + ui.table({
      columns: [
        { key: 'label', label: '分组', render: (row) => '<div class="y7-cell-stack"><strong>' + esc(row.label) + '</strong>' + bar(row.total, max) + '</div>' },
        { key: 'count', label: '尝试', render: (row) => esc(row.count) + (row.inFlight ? '<small class="y7-muted y7-block-line">' + esc(row.inFlight) + ' 次进行中</small>' : '') },
        { key: 'input', label: '输入（含缓存）', render: (row) => '<span class="y7-obs-num">' + esc(fmtTokens(row.input)) + '</span>' },
        { key: 'output', label: '输出', render: (row) => '<span class="y7-obs-num">' + esc(fmtTokens(row.output)) + '</span>' },
        { key: 'cacheRead', label: '缓存读取（输入子集）', render: (row) => '<span class="y7-obs-num">' + esc(fmtTokens(row.cacheRead)) + '</span>' },
        { key: 'total', label: '总 Token', render: (row) => '<span class="y7-obs-num">' + esc(fmtTokens(row.total)) + '</span>' },
        { key: 'cost', label: '成本', render: (row) => row.cost === null ? '<span class="y7-muted">未上报</span>' : esc(row.cost) }
      ],
      rows: groups
    });
  }

  function usagePanel(usage) {
    const c = usage.coverage;
    const pct = c.sent ? Math.round((c.reported / c.sent) * 100) : 0;
    const fields = c.fields.map((field) => '<li><span>' + esc(field.label) + '</span><strong>' + esc(field.count) + ' / ' + esc(c.sent) + '</strong></li>').join('');
    const t = usage.totals;
    const totals = '<div class="y7-obs-totals">' + USAGE_FIELDS.map((field) =>
      '<div class="y7-obs-total"><span>' + esc(field.label) + '</span><strong>' + (field.key === 'cost' && t.cost === null ? '未上报' : esc(fmtTokens(t[field.key]))) + '</strong></div>'
    ).join('') + '</div>';
    return '<div class="y7-obs-coverage">' +
        '<div class="y7-obs-pct"><strong>' + esc(pct) + '%</strong><span>' + esc(c.reported + ' / ' + c.sent + ' 次尝试已上报 usage') + '</span>' + ui.meter(c.reported, c.sent || 1, { warnAt: 2 }) + '</div>' +
        '<ul class="y7-obs-fields">' + fields + '</ul>' +
      '</div>' +
      '<p class="y7-muted y7-small">' + (usage.prepared ? esc(usage.prepared + ' 条准备记录未发出，不计入覆盖率。') : '') + '输入（含缓存）与缓存读取（输入子集）不重复相加；用量只读显示，不是事项的预算。</p>' +
      '<h3 class="y7-h3">筛选总计</h3>' + totals +
      groupTable(usage.byDepartment, '按部门') +
      groupTable(usage.byModel, '按模型') +
      (usage.byRole ? groupTable(usage.byRole, '按角色') : '');
  }

  function limitsBlock(usage) {
    const rows = usage.limits;
    const table = ui.table({
      columns: [
        { key: 'item', label: '事项', render: (row) => '<div class="y7-cell-stack"><strong>' + esc(row.item.title) + '</strong>' + ui.status(row.display.kind, row.display.text) + '</div>' },
        { key: 'time', label: '已用时间 / 时间上限', render: (row) => '<div class="y7-obs-limit"><span>' + esc(Y7.ui.duration(row.elapsedSec)) + ' / ' + esc(Y7.ui.duration(row.limitSec)) + '</span>' + ui.meter(row.elapsedSec, row.limitSec) + '</div>' },
        { key: 'cycle', label: '循环次数', render: (row) => row.cycle ? esc('第 ' + row.cycle + ' 轮') : '<span class="y7-muted">未开始</span>' },
        { key: 'counters', label: '激活 · 模型步骤 · 重试', render: (row) => row.counters ? esc(row.counters.activations + ' 次激活 · ' + row.counters.modelSteps + ' 步 · ' + row.counters.retries + ' 次重试') : '<span class="y7-muted">—</span>' }
      ],
      rows
    });
    return ui.block({
      title: '运行限制', tag: Y7.atLeast('s3') ? '当前 · 3.1' : '当前', level: 'now', query: 'project.usage', command: '无',
      subtitle: '时间上限是事项整体收敛的保证；循环次数只作为观察。' + (Y7.atLeast('s3') ? '已用限额在恢复后保留，不清零。' : ''),
      body: table
    });
  }

  function options(list, selected, labelFn, allLabel) {
    return '<option value="">' + esc(allLabel) + '</option>' + list.map((value) => '<option value="' + esc(value) + '"' + (value === selected ? ' selected' : '') + '>' + esc(labelFn(value)) + '</option>').join('');
  }

  function filterBar(data, f) {
    const o = data.options;
    const select = (key, label, list, labelFn, allLabel, extra) =>
      '<label class="y7-obs-filter"><span>' + esc(label) + '</span><select class="y7-select" data-act="obs.filter" data-key="' + key + '">' + options(list, f[key], labelFn, allLabel) + (extra || '') + '</select></label>';
    const parts = [
      select('department', '部门', o.departments, (id) => Y7.deptLabel(id) + '部门', '全部部门'),
      Y7.atLeast('s4') ? select('role', '角色', o.roles, roleName, '全部角色') : '',
      select('status', '状态', o.statuses, (id) => Y7.ATTEMPT_LABELS[id], '全部状态'),
      select('provider', 'Provider', o.providers, (id) => id, '全部'),
      select('requestedModel', '请求模型', o.requestedModels, (id) => id, '全部'),
      select('actualModel', '实际模型', o.actualModels, (id) => id, '全部', o.hasUnknownActual ? '<option value="__unknown"' + (f.actualModel === '__unknown' ? ' selected' : '') + '>未知</option>' : ''),
      '<label class="y7-obs-filter is-search"><span>搜索</span><input class="y7-input" type="search" data-act="obs.search" value="' + esc(f.q) + '" placeholder="请求编号、模型或错误"></label>'
    ];
    const active = FILTER_KEYS.some((key) => f[key]);
    return '<div class="y7-obs-filters">' + parts.join('') + (active ? '<button type="button" class="y7-link y7-obs-reset" data-act="obs.reset">清除筛选</button>' : '') + '</div>' +
      '<p class="y7-muted y7-small y7-obs-scope">事项范围在顶栏的「范围」中选择。</p>';
  }

  function resultsHtml(ctx) {
    const pid = ctx.project.id;
    const w = ctx.workItem ? ctx.workItem.id : null;
    const f = filtersOf(pid);
    const data = Y7.query('project.attempts', { projectId: pid, workItemId: w, filters: f, limit: st.limit[pid] || PAGE });
    const usage = Y7.query('project.usage', { projectId: pid, workItemId: w, filters: f });
    const items = [
      { id: 'records', label: '请求记录', count: data.matched },
      { id: 'usage', label: '用量统计' }
    ];
    const active = Y7.ui.activeTab('obs.list', items, 'records');
    return ui.tabs({ id: 'obs.list', items, active }) + ui.tabPanels('obs.list', active, { records: recordsPanel(ctx, data), usage: usagePanel(usage) });
  }

  function applyPreset(ctx) {
    const q = ctx.route.query;
    if (st.presetHash === ctx.route.hash) return;
    st.presetHash = ctx.route.hash;
    if (!q.dept && !q.role) return;
    const f = filtersOf(ctx.project.id);
    FILTER_KEYS.forEach((key) => { f[key] = ''; });
    if (q.dept) f.department = q.dept;
    if (q.role && Y7.atLeast('s4')) f.role = q.role;
  }

  function renderList(ctx) {
    applyPreset(ctx);
    const pid = ctx.project.id;
    const w = ctx.workItem ? ctx.workItem.id : null;
    const f = filtersOf(pid);
    const data = Y7.query('project.attempts', { projectId: pid, workItemId: w, filters: f });
    const usage = Y7.query('project.usage', { projectId: pid, workItemId: w, filters: {} });
    const head = '<header class="y7-page-head"><div class="y7-page-titles"><p class="y7-eyebrow">观测 · ' + esc(w ? '事项「' + ctx.workItem.title + '」' : '整个项目') + '</p><h1>模型请求</h1>' +
      '<p class="y7-subtitle">' + esc(data.inFlight + ' 个请求进行中 · ' + data.total + ' 条记录 · ' + data.sent + ' 次已发出') + '</p></div></header>';
    const block = ui.block({
      title: '请求记录与用量', tag: Y7.atLeast('s4') ? '当前 · Stage 4' : '当前', level: 'now',
      query: ['project.attempts', 'project.usage'], command: '无', className: 'y7-obs-main',
      subtitle: Y7.atLeast('s4') ? '按部门、角色、状态、Provider 与模型筛选；两个页签使用同一组筛选。' : '按部门、状态、Provider 与模型筛选；两个页签使用同一组筛选。',
      body: filterBar(data, f) + '<div class="y7-obs-results" data-obs-results>' + resultsHtml(ctx) + '</div>'
    });
    return '<div class="y7-obs">' + head + block + limitsBlock(usage) + '</div>';
  }

  function refreshResults() {
    const ctx = Y7.ctx();
    const el = document.querySelector('[data-obs-results]');
    if (!el) throw new Error('观测页缺少结果区域');
    el.innerHTML = resultsHtml(ctx);
  }

  function refreshFilterBar() {
    const ctx = Y7.ctx();
    const pid = ctx.project.id;
    const data = Y7.query('project.attempts', { projectId: pid, workItemId: ctx.workItem ? ctx.workItem.id : null, filters: filtersOf(pid) });
    const bar = document.querySelector('.y7-obs-filters');
    const holder = document.createElement('div');
    holder.innerHTML = filterBar(data, filtersOf(pid));
    bar.nextElementSibling.remove();
    bar.replaceWith(...holder.childNodes);
  }

  // ---------------------------------------------------------------------------
  // 渲染：请求详情

  function diagnosticsBlock(d) {
    const a = d.attempt;
    const err = a.error;
    const pairs = [
      ['开始', esc(Y7.ui.time(a.startedAt))],
      ['耗时', IN_FLIGHT.includes(a.status) ? '<span class="y7-muted">进行中</span>' : esc(fmtMs(a.durationMs))],
      ['尝试', esc('第 ' + a.n + '/' + a.of + ' 次')],
      ['请求', esc(a.provider + ' / ' + a.requestedModel)],
      ['返回', a.actualModel ? esc(a.actualModel) : '<span class="y7-muted">未知</span>'],
      ['请求类型', esc(KIND_LABELS[a.kind] || a.kind)]
    ];
    if (err) {
      pairs.push(['错误分类', esc(ERROR_LABELS[err.category] || err.category)]);
      pairs.push(['错误代码', ui.code(err.code)]);
      pairs.push(['HTTP 状态', err.http ? esc(err.http) : '<span class="y7-muted">没有 HTTP 响应</span>']);
    }
    return ui.block({
      title: '诊断', tag: '当前', level: 'now', query: 'run.attempt', command: '无',
      body: ui.kv(pairs) + (err ? ui.note('错误原文：' + esc(err.text), 'warn') : '')
    });
  }

  function siblingsBlock(ctx, d) {
    const w = ctx.workItem ? ctx.workItem.id : null;
    const chips = d.siblings.map((att) =>
      '<button type="button" class="y7-obs-sib' + (att.id === d.attempt.id ? ' is-on' : '') + '" data-go="' + esc(Y7.paths.observeDetail(ctx.project.id, att.id, w)) + '"' + (att.id === d.attempt.id ? ' aria-current="true"' : '') + '>' +
      '<strong>第 ' + att.n + '/' + att.of + ' 次</strong>' + ui.status(STATUS_KIND[att.status], Y7.ATTEMPT_LABELS[att.status]) + '<small class="y7-muted">' + esc(Y7.ui.time(att.startedAt)) + '</small></button>'
    ).join('');
    return ui.block({
      title: '同次调用', tag: '当前', level: 'now', query: 'run.attempt', command: '无',
      subtitle: '同一个逻辑调用 ' + d.attempt.logicalCallId + ' 的全部尝试；一次请求内的重试沿用该请求的调用目标。',
      body: '<div class="y7-obs-sibs">' + chips + '</div>'
    });
  }

  function targetBlock(d) {
    const t = d.attempt.target;
    if (!t) return '';
    const pairs = [
      ['连接', ui.code(t.connection)],
      ['协议', esc(t.protocol)],
      ['地址', ui.code(t.baseUrl)],
      ['上游模型', esc(t.model)],
      ['容量', esc('窗口 ' + numberFormat.format(t.window) + ' · 输出上限 ' + numberFormat.format(t.maxOutput))],
      ['凭据引用与版本', t.credentialRef ? ui.code(t.credentialRef) + ' ' + ui.tag(t.credentialVersion) : '<span class="y7-muted">无需凭据</span>'],
      ['选择来源', esc(t.source)],
      ['推理档位', esc((t.requestLevel ? '请求 ' + t.requestLevel : '请求档位为空（使用模型默认档位）') + ' · 实际发送 ' + (t.sentLevel || '不带推理参数'))],
      ['部门 Prompt 版本', ui.code('v' + t.promptVersion)]
    ];
    if (t.usageBasis) pairs.push(['压缩判断用的用量', esc('上游回报 ' + numberFormat.format(t.usageBasis.upstream) + ' · 本地估算 ' + numberFormat.format(t.usageBasis.local))]);
    return ui.block({
      title: '调用目标', tag: 'D24', level: 's3', query: 'run.attempt', command: '无',
      subtitle: '这次请求实际使用的连接、协议、地址、上游模型、容量、凭据引用与版本，取自请求事件；不含 API Key。',
      body: ui.kv(pairs)
    });
  }

  function semanticBlock(d) {
    const s = d.semantic;
    if (!s) return '';
    const body = s.listed.length
      ? ui.table({
        columns: [
          { key: 'id', label: '编号', render: (row) => ui.code(row.id) },
          { key: 'version', label: '版本', render: (row) => ui.code('v' + row.version) },
          { key: 'type', label: '类型' },
          { key: 'text', label: '内容' },
          { key: 'status', label: '有效状态', render: (row) => ui.status({ valid: 'admitted', conflict: 'unusable', superseded: 'held', invalid: 'cancelled' }[row.status] || 'idle', { valid: '有效', conflict: '有冲突', superseded: '已取代', invalid: '已失效' }[row.status] || row.status) }
        ],
        rows: s.listed
      }) + (s.notListed ? '<p class="y7-muted y7-small">另有 ' + esc(s.notListed) + ' 条有效单元未列出，可以用查回工具查询。</p>' : '')
      : ui.empty(s.compaction ? '压缩请求不带语义视图' : '这次请求没有语义视图');
    return ui.block({ title: '语义视图', tag: 'Stage 4', level: 's4', query: 'run.attempt', command: '无', subtitle: '本次请求包含的语义单元编号与版本。', body });
  }

  function overviewPanel(ctx, d) {
    const a = d.attempt;
    const u = a.usage;
    const usage = '<div class="y7-obs-totals">' + USAGE_FIELDS.map((field) =>
      '<div class="y7-obs-total"><span>' + esc(field.label) + '</span><strong>' + (IN_FLIGHT.includes(a.status) ? '等待响应' : u && u[field.key] !== null && u[field.key] !== undefined ? esc(fmtTokens(u[field.key])) : '未上报') + '</strong></div>'
    ).join('') + '</div>';
    const w = ctx.workItem ? ctx.workItem.id : null;
    const pairs = [
      ['事项', esc(d.item.title) + '<small class="y7-muted y7-block-line">' + esc(Y7.PHASE_LABELS[d.run.phase]) + ' · 第 ' + d.run.cycle + ' 轮</small>'],
      ['部门', esc(Y7.deptLabel(a.department) + '部门') + (a.role ? '<small class="y7-muted y7-block-line">' + esc(roleName(a.role)) + '</small>' : '')],
      ['请求类型', esc(KIND_LABELS[a.kind] || a.kind)],
      ['部门 Prompt 版本', d.promptVersion !== null && d.promptVersion !== undefined ? ui.code('v' + d.promptVersion) : '<span class="y7-muted">—</span>']
    ];
    const context = d.context
      ? '<h3 class="y7-h3">Context 快照 · ' + esc(d.context.title) + '</h3><ul class="y7-obs-sources">' + d.context.sources.map((src) =>
        '<li>' + (src.included ? ui.status('admitted', '已注入') : ui.status('idle', '未包含')) + '<span>' + esc(src.label) + '</span>' + ui.code(src.version) + (src.note ? '<small class="y7-muted">' + esc(src.note) + '</small>' : '') + '</li>'
      ).join('') + '</ul>'
      : '<h3 class="y7-h3">Context 快照</h3><p class="y7-muted y7-small">没有对应的 Context 快照</p>';
    const collab = d.collaboration.length
      ? '<h3 class="y7-h3">协作请求</h3><ul class="y7-list">' + d.collaboration.map((req) => '<li>' + esc(Y7.deptLabel(req.from) + '部门 → ' + Y7.deptLabel(req.to) + '部门：' + req.question) + (req.answer ? '<small class="y7-muted y7-block-line">回答：' + esc(req.answer) + '</small>' : '') + '</li>').join('') + '</ul>'
      : '';
    const tools = d.tools.length
      ? '<h3 class="y7-h3">工具调用</h3><ul class="y7-list">' + d.tools.map((act) => '<li>' + esc(Y7.ui.time(act.at)) + ' · ' + esc(act.summary) + (act.result ? ' · ' + esc(act.result) : '') + '</li>').join('') + '</ul>'
      : '<h3 class="y7-h3">工具调用</h3><p class="y7-muted y7-small">这次请求之后没有记录工具调用</p>';
    const dept = '<div class="y7-row">' + ui.button({ label: '返回' + Y7.deptLabel(a.department) + '部门', kind: 'small', icon: 'back', go: Y7.paths.dept(ctx.project.id, a.department, w || d.item.id) }) + '</div>';
    return usage + ui.kv(pairs) + context + collab + tools + dept;
  }

  function eventsPanel(d) {
    return '<p class="y7-muted y7-small">原型按调用尝试的记录整理出事件；真实界面读取事件库中的原始事件。</p>' + ui.table({
      columns: [
        { key: 'at', label: '时间', render: (row) => esc(Y7.ui.time(row.at)) },
        { key: 'type', label: '类型', render: (row) => ui.code(row.type) },
        { key: 'text', label: '摘要' }
      ],
      rows: d.events
    });
  }

  function jsonPanel(doc, emptyText, note) {
    if (!doc) return ui.empty(emptyText);
    return (note ? '<p class="y7-muted y7-small">' + esc(note) + '</p>' : '') + ui.pre(JSON.stringify(doc, null, 2));
  }

  function detailTabs(ctx, d) {
    const a = d.attempt;
    const items = [
      { id: 'overview', label: '概览' },
      { id: 'request', label: 'Request' },
      { id: 'response', label: 'Response' },
      { id: 'events', label: '事件', count: d.events.length }
    ];
    const active = Y7.ui.activeTab('obs.detail', items, 'overview');
    const responseEmpty = a.status === 'preparing' ? '模型请求尚未发出' : '等待模型响应';
    return ui.block({
      title: '请求内容', tag: '当前', level: 'now', query: 'run.attempt', command: '无',
      body: ui.tabs({ id: 'obs.detail', items, active }) + ui.tabPanels('obs.detail', active, {
        overview: overviewPanel(ctx, d),
        request: jsonPanel(d.request, '模型请求尚未发出', '原型根据示例数据整理的请求结构；真实界面显示 sdk_request 工件原文，不含 API Key。'),
        response: jsonPanel(d.response, responseEmpty, null),
        events: eventsPanel(d)
      })
    });
  }

  function renderDetail(ctx) {
    const pid = ctx.project.id;
    const w = ctx.workItem ? ctx.workItem.id : null;
    const attemptId = ctx.route.params.attemptId;
    const d = Y7.query('run.attempt', { projectId: pid, attemptId });
    const back = ui.button({ label: '返回请求记录', icon: 'back', kind: 'small', go: Y7.paths.observe(pid, w) });
    if (!d) {
      return '<div class="y7-obs">' + ui.block({
        title: '找不到这次请求', tag: '当前', level: 'now', query: 'run.attempt', command: '无',
        body: ui.empty('调用尝试「' + attemptId + '」不在本项目中，或它所在的事项不在当前档位。') + '<div class="y7-row y7-obs-more">' + back + '</div>'
      }) + '</div>';
    }
    const a = d.attempt;
    const crumbs = [ctx.project.name, d.item.title, Y7.deptLabel(a.department) + '部门'];
    if (a.role) crumbs.push(roleName(a.role));
    crumbs.push('调用 ' + a.logicalCallId, '尝试 第 ' + a.n + '/' + a.of + ' 次');
    const head = '<div class="y7-row y7-obs-back">' + back +
      ui.button({ label: '返回' + Y7.deptLabel(a.department) + '部门', kind: 'small', go: Y7.paths.dept(pid, a.department, w || d.item.id) }) + '</div>' +
      '<header class="y7-page-head"><div class="y7-page-titles"><p class="y7-eyebrow">请求详情</p><div class="y7-obs-title"><h1>' + esc(a.id) + '</h1>' + statusChip(a) + '</div>' +
      '<p class="y7-subtitle y7-obs-path">' + crumbs.map((text) => '<span>' + esc(text) + '</span>').join('<span class="y7-crumb-sep">›</span>') + '</p></div></header>';
    return '<div class="y7-obs">' + head + diagnosticsBlock(d) + siblingsBlock(ctx, d) + targetBlock(d) + semanticBlock(d) + detailTabs(ctx, d) + '</div>';
  }

  Y7.views.register('observe', { title: () => '观测', render: renderList });
  Y7.views.register('observe-detail', { title: () => '请求详情', render: renderDetail });

  // ---------------------------------------------------------------------------
  // 界面动作

  Y7.actions.register('obs.filter', (el) => {
    const pid = Y7.state.projectId;
    filtersOf(pid)[el.dataset.key] = el.value;
    st.limit[pid] = PAGE;
    refreshFilterBar();
    refreshResults();
  });

  Y7.actions.register('obs.search', (el) => {
    const pid = Y7.state.projectId;
    filtersOf(pid).q = el.value.trim();
    st.limit[pid] = PAGE;
    refreshResults();
  });

  Y7.actions.register('obs.reset', () => {
    const pid = Y7.state.projectId;
    FILTER_KEYS.forEach((key) => { filtersOf(pid)[key] = ''; });
    st.limit[pid] = PAGE;
    Y7.renderContent(true);
  });

  Y7.actions.register('obs.more', () => {
    const pid = Y7.state.projectId;
    st.limit[pid] = (st.limit[pid] || PAGE) + PAGE;
    refreshResults();
  });
})();
