// 部门工作间（设计说明第 7.1 节）：标题区、部门房间、检查区、部门消息与指导、部门设置弹窗；运维工作间（Stage 4）
(function () {
  'use strict';
  const Y13 = window.Y13;
  const esc = Y13.esc;
  const ui = Y13.ui;

  const DEPT = {
    product: { label: '产品', duty: '维护原始意图与有效规范，回答其他部门的询问' },
    engineering: { label: '工程', duty: '依据有效规范设计、实现、自测并提交交付' },
    quality: { label: '质检', duty: '在独立副本中验证交付，给出缺陷或放行' },
    operations: { label: '运维', duty: '接收交付物的运行责任，处理运行问题' }
  };
  const DEPTS = ['product', 'engineering', 'quality', 'operations'];
  const ROLE_STATUS = { idle: 'idle', assigned: 'queued', working: 'running', returned: 'succeeded', failed: 'failed', away: 'asking' };
  const ROLE_STATUS_TEXT = { idle: '空闲', assigned: '已分派', working: '工作中', returned: '已交回', failed: '失败', away: '外出查资料' };
  const ROLE_KIND = { manager: '经理', architect: '连续角色', lead: '连续角色', tester: '连续角色', explorer: '一次性角色', agent: '部门 Agent', ops: '部门 Agent' };
  const ATTEMPT_KIND = { work: '工作请求', compaction: '压缩请求', collaboration: '询问分支', review: '审查请求' };
  const ACTION_STATE_TEXT = { not_sent: '未发送', done: '已完成', unknown: '结果未知', running: '进行中' };
  const ITEM_STATUS = { assigned: ['queued', '已分派'], working: ['running', '进行中'], returned: ['succeeded', '已交回'], failed: ['failed', '失败'], cancelled: ['cancelled', '已取消'] };
  const AT_LEAST_S5 = () => Y13.cap.query('role.detail');

  const st = { role: null, scene: null, modal: null, pending: null };

  function deptLabel(id) {
    if (!DEPT[id]) throw new Error('未知部门：' + id);
    return DEPT[id].label;
  }

  function rerender() {
    Y13.app.renderContent(true);
  }

  function workspace(ctx) {
    const params = { project: ctx.projectId, department: ctx.department };
    if (ctx.workItemId) params.work_item = ctx.workItemId;
    return Y13.api.query('department.workspace', params).data;
  }

  function actions(ctx, v) {
    if (!Y13.cap.query('run.actions')) return null;
    const workItem = ctx.workItemId || (v.work_item ? v.work_item.id : null);
    if (!workItem) return [];
    return Y13.api.query('run.actions', { work_item: workItem, department: ctx.department }).data.actions;
  }

  function catalog() {
    if (!Y13.cap.query('catalog')) return null;
    return Y13.api.query('catalog', {}).data;
  }

  function settings(ctx) {
    if (!Y13.cap.query('project.settings')) return null;
    return Y13.api.query('project.settings', { project: ctx.projectId }).data;
  }

  // ---------------------------------------------------------------------------
  // 标题区

  function modelHtml(v) {
    const m = v.model;
    const parts = [];
    if (!m.definition) {
      parts.push('<span class="y13-ws-inline"><span class="y13-muted">未设置</span></span>');
    } else {
      parts.push('<span class="y13-ws-inline"><strong>' + esc(m.label) + '</strong>' + ui.tag(m.source || '—') + '</span>');
      if (m.problem) parts.push(ui.status('unusable', '无法使用：' + m.problem));
      parts.push('<small class="y13-muted">发送档位 ' + esc(m.sent_level || '不带推理参数') + (m.request_level ? '（请求 ' + esc(m.request_level) + '）' : '') + '</small>');
    }
    return parts.join(' ');
  }

  // 三个部门同时运行（ADR-0036）：标题区写出这个事项里三个部门各自的状态，本部门加粗
  function statesLine(v) {
    if (!v.states) return '';
    return '<p class="y13-ws-item y13-ws-states"><span class="y13-muted">三个部门</span>' + Object.keys(v.states).map((d) => {
      const s = v.states[d];
      const name = (DEPT[d] ? DEPT[d].label : d) + ' ' + s.text + (s.note ? '（' + s.note + '）' : '');
      return d === v.department.id ? '<strong>' + esc(name) + '</strong>' : '<span>' + esc(name) + '</span>';
    }).join('<span class="y13-muted">·</span>') + '</p>';
  }

  function headInner(v) {
    const item = v.work_item;
    const itemLine = item
      ? '<p class="y13-ws-item"><span class="y13-muted">事项</span><strong>' + esc(item.title) + '</strong>' + statusOfItem(item) + '</p>' + statesLine(v)
      : '<p class="y13-ws-item y13-muted">本项目没有进行中的事项</p>';
    const last = v.last_target;
    const lastLine = last
      ? ui.kv([
        ['最近一次请求', esc(last.model || '—') + ' · ' + esc(last.connection_name || last.connection || '—')],
        ['协议与档位', esc(last.protocol || '—') + ' · ' + esc(last.sent_level || '不带推理参数')],
        ['部门 Prompt 版本', 'v' + esc(last.prompt_version === null || last.prompt_version === undefined ? '—' : last.prompt_version)],
        ['状态', esc(last.status_text || last.status)]
      ], 'is-inline y13-ws-model')
      : '';
    const warning = v.image_warning
      ? ui.note(esc(v.image_warning.text) + '<span class="y13-note-actions">' +
        ui.button({ label: '前往模型管理', kind: 'small', go: '#/sys/models' }) +
        ui.button({ label: '前往本项目的部门设置', kind: 'small', act: 'dept.selfSettings' }) + '</span>', 'warn')
      : '';
    return '<div class="y13-ws-head">' +
        '<div class="y13-ws-titles">' +
          '<p class="y13-eyebrow">部门工作间</p>' +
          '<div class="y13-ws-title-row"><h1>' + esc(v.department.label) + '部门</h1>' + ui.status(v.status.kind, v.status.text) +
            (v.status.note ? '<small class="y13-muted">' + esc(v.status.note) + '</small>' : '') + '</div>' +
          '<p class="y13-ws-duty">' + esc(v.department.duty) + '</p>' + itemLine +
          '<div class="y13-ws-inline"><span class="y13-ws-k">当前生效模型</span>' + modelHtml(v) + '</div>' +
        '</div>' +
        '<div class="y13-ws-head-actions">' +
          ui.button({ label: '部门设置', icon: 'tools', kind: 'small', act: 'dept.openSettings', data: { project: v.project.id, department: v.department.id } }) +
          ui.button({ label: '本部门的模型请求', icon: 'search', kind: 'small', go: observeLink(v) }) +
        '</div>' +
      '</div>' + lastLine + warning;
  }

  function observeLink(v) {
    const base = Y13.paths.observe(v.project.id, v.work_item ? v.work_item.id : null);
    return base + (base.indexOf('?') >= 0 ? '&' : '?') + 'dept=' + v.department.id;
  }

  const ITEM_KIND = {
    not_started: ['idle', '未开始'], queued: ['queued', '排队中'], in_progress: ['running', '进行中'],
    adopted: ['adopted', '已采纳'], released: ['released', '已放行'], stopped: ['cancelled', '已停止']
  };

  function statusOfItem(item) {
    const entry = ITEM_KIND[item.status] || ['idle', item.status];
    return ui.status(entry[0], entry[1]);
  }

  // ---------------------------------------------------------------------------
  // 房间信息

  function infoInner(v) {
    const room = v.room;
    const facts = ui.kv([
      ['状态', esc(v.status.text)],
      ['第几轮', v.run ? esc('第 ' + v.run.cycle + ' 轮') : ''],
      ['已用时间 / 上限', v.run ? esc(Y13.ui.duration(v.run.elapsed_sec) + ' / ' + Y13.ui.duration(v.run.limit_sec)) : ''],
      ['执行机器', room.machine ? esc(room.machine) : '<span class="y13-muted">—</span>'],
      ['信箱', esc(String(room.mailbox)) + ' 封未读指导'],
      ['传信管', room.pipes.letters_waiting ? esc(room.pipes.letters_waiting + ' 封询问等待本部门回答') : '<span class="y13-muted">没有等待回答的询问</span>']
    ], 'is-inline y13-ws-facts');
    const roles = '<div class="y13-ws-roles"><span class="y13-ws-k">房间里的角色</span><ul>' + room.roles.map((role) =>
      '<li><strong>' + esc(role.name) + '</strong>' + ui.status(role.kind === 'ops' ? 'running' : 'idle', role.task || ROLE_STATUS_TEXT[role.status] || role.status) + '</li>'
    ).join('') + '</ul></div>';
    const door = room.door ? '<p class="y13-ws-event"><code>' + esc(room.door) + '</code><span>' + esc(room.hold_card || '门口立起了牌子') + '</span></p>' : '';
    return facts + roles + door;
  }

  // ---------------------------------------------------------------------------
  // 检查区

  function actionsPanel(ctx, v) {
    const list = actions(ctx, v);
    if (list === null) return ui.empty('本页没有登记动作查询');
    if (!list.length) return ui.empty('本部门还没有动作记录');
    return '<div class="y13-ws-acts">' + list.slice().sort((a, b) => Y13.time.ms(b.at) - Y13.time.ms(a.at)).map((action) => {
      const kind = action.state === 'unknown' ? 'is-unknown' : '';
      const head = '<div class="y13-ws-act-head"><strong>' + esc(action.summary) + '</strong>' +
        '<span class="y13-ws-act-tool">' + esc(action.tool) + '</span>' +
        (action.state_text ? ui.status(action.state === 'unknown' ? 'unknown' : action.state === 'not_sent' ? 'idle' : 'succeeded', action.state_text) : '') +
        (action.machine_name ? ui.tag(action.machine_name) : '') + '</div>';
      const meta = ui.kv([
        ['时间', esc(Y13.ui.time(action.at))],
        ['角色', action.role ? esc(action.role) : ''],
        ['执行机器', action.machine_name ? esc(action.machine_name) : '']
      ], 'is-inline y13-ws-act-meta');
      const snaps = (action.before || action.after)
        ? '<div class="y13-ws-snaps"><span class="y13-muted">快照</span><span>' + esc(action.before || '—') + '</span><span class="y13-ws-arrow">→</span><span>' + esc(action.after || '—') + '</span></div>'
        : '';
      const input = '<div class="y13-ws-snaps"><span class="y13-muted">输入依据</span><span>' + esc(action.input || '—') + '</span></div>';
      let receipt = '';
      const r = action.receipt;
      if (r) {
        receipt = '<div class="y13-ws-receipt"><div class="y13-ws-receipt-title">回执' +
          (r.exit_code !== undefined ? ui.status(r.exit_code === 0 ? 'succeeded' : 'failed', '退出码 ' + r.exit_code) : '') +
          (r.timed_out ? ui.status('failed', '超时') : '') +
          (r.truncated ? ui.tag('输出截断') : '') +
          '<span class="y13-muted">' + esc(Y13.ui.duration(Math.round((r.duration_ms || 0) / 1000))) + '</span></div>' +
          // 命令按函数直接执行，没有登记名（ADR-0038）；文件与网络工具的回执写目标
          // 网络取回与 MCP 调用的结果另存为外部来源工件（网络取回与 MCP 工具设计说明第 11.2 节）
          ui.kv([
            r.command ? ['命令', ui.code(r.command)] : ['目标', ui.code(r.target || '—')],
            r.artifact ? ['外部来源工件', ui.code(r.artifact)] : ['快照', ui.code(r.snapshot || '—')]
          ], 'is-inline y13-ws-receipt-kv') +
          (r.output ? ui.pre(r.output) : '') + '</div>';
      }
      return '<article class="y13-ws-act ' + kind + '">' + head + meta + input + snaps + receipt + '</article>';
    }).join('') + '</div>';
  }

  // 试用记录（3.2D，查询 run.trials）：每一步的操作、截图缩略图与对应的需求条目；每张截图标明模型是否看到它，
  // 点击截图查看原尺寸（evidence.screenshot），旁边列出同一步的可访问性结构摘录
  function trialsPanel(v) {
    const data = Y13.api.query('run.trials', { work_item: v.work_item.id }).data;
    if (!data.trials.length) return ui.empty('还没有试用记录');
    const head = '<p class="y13-muted y13-small">质检模型：' + esc(data.model) + (data.image_input ? '（支持图像输入）' : '（只有文本输入：显示器照常显示截图，模型只读取可访问性结构的文字）') + '</p>';
    return head + '<ol class="y13-ws-summaries y13-trials">' + data.trials.map((trial) =>
      '<li><strong>第 ' + esc(trial.step) + ' 步</strong><span>' + esc(trial.action) + '</span>' +
      (trial.requirement ? ui.tag('对应需求：' + trial.requirement) : '') + '<span class="y13-muted">' + esc(Y13.ui.time(trial.at)) + '</span>' +
      (trial.screenshot
        ? '<button type="button" class="y13-trial-shot" data-act="dept.shot" data-work-item="' + esc(v.work_item.id) + '" data-step="' + esc(trial.step) + '" title="查看原尺寸">' +
          '<img src="assets/' + esc(trial.screenshot) + '" alt="第 ' + esc(trial.step) + ' 步的截图" loading="lazy"></button>'
        : '') +
      '<span class="y13-trial-saw' + (trial.model_saw ? '' : ' is-text') + '">' + (trial.model_saw ? '模型看到了这张截图' : '模型只读取文字') + '</span></li>'
    ).join('') + '</ol>';
  }

  function contextPanel(v) {
    const snaps = v.context.snapshots || [];
    const list = snaps.length
      ? '<ul class="y13-ws-summaries">' + snaps.map((snap) =>
        '<li><strong>' + esc(snap.title || snap.id) + '</strong><span class="y13-muted">' + esc(Y13.ui.time(snap.at)) + '</span>' + ui.code(snap.attempt_id || '') +
        '<ul class="y13-obs-sources">' + (snap.sources || []).map((source) =>
          '<li>' + ui.status(source.included ? 'succeeded' : 'idle', source.included ? '装入' : '未装入') +
          '<span>' + esc(source.label) + '</span>' + (source.version ? ui.tag(source.version) : '') + '</li>'
        ).join('') + '</ul></li>'
      ).join('') + '</ul>'
      : ui.empty('还没有 Context 快照');
    const compactions = (v.context.compactions || []).length
      ? ui.table({
        columns: [
          { key: 'n', label: '编号', render: (row) => esc('摘要 ' + row.n) },
          { key: 'at', label: '时间', render: (row) => esc(Y13.ui.time(row.at)) },
          { key: 'coverage', label: '覆盖范围' }
        ],
        rows: v.context.compactions
      })
      : ui.empty('还没有压缩记录');
    return '<h3 class="y13-h3">上下文清单</h3>' + list + '<h3 class="y13-h3">压缩记录</h3>' + compactions;
  }

  function promptPanel(v) {
    const p = v.prompt;
    const config = '<section><h3 class="y13-h3">项目当前配置 ' + ui.tag(p.config_version ? 'v' + p.config_version : '内置默认 v0') + '</h3>' +
      ui.pre(p.config_text || '（没有配置文本）') + '</section>';
    const request = '<section><h3 class="y13-h3">所选请求实际使用 ' + ui.tag(p.request_version === null ? '尚未发生请求' : 'v' + p.request_version) + '</h3>' +
      (p.request_text ? ui.pre(p.request_text) : '<p class="y13-muted">这个事项还没有发生本部门的模型请求。</p>') + '</section>';
    return '<div class="y13-ws-prompt y13-grid-2">' + config + request + '</div>';
  }

  function rolesPanel(ctx, v) {
    if (!v.roles) return ui.empty('本页没有角色名单');
    const table = ui.table({
      columns: [
        { key: 'name', label: '角色', render: (row) => '<div class="y13-cell-stack"><strong>' + esc(row.name) + '</strong><small class="y13-muted">' + esc(ROLE_KIND[row.kind] || row.kind) + (row.predictive ? ' · 预测性任务' : '') + '</small></div>' },
        { key: 'status', label: '状态', className: 'y13-col-status', render: (row) => ui.status(ROLE_STATUS[row.status] || 'idle', ROLE_STATUS_TEXT[row.status] || row.status) },
        { key: 'model', label: '模型', render: (row) => (row.resolved && row.resolved.definition
          ? '<div class="y13-cell-stack"><span>' + esc(row.resolved.model || row.resolved.definition) + '</span><small class="y13-muted">来源：' + esc(row.resolved.source || '—') + ' · 发送 ' + esc(row.resolved.sent_level || '不带推理参数') + '</small></div>'
          : '<span class="y13-muted">未设置</span>') },
        { key: 'task', label: '当前任务', render: (row) => (row.task ? esc(row.task) : '<span class="y13-muted">没有任务</span>') },
        { key: 'ops', label: '详情', className: 'y13-col-actions', render: (row) => ui.button({ label: '查看', kind: 'small', act: 'dept.roleDetail', data: { role: row.id } }) }
      ],
      rows: v.roles
    });
    let detail = '';
    if (st.role) {
      const d = Y13.api.query('role.detail', { project: ctx.projectId, department: v.department.id, role: st.role, work_item: ctx.workItemId || undefined });
      const role = d.role;
      const history = d.history.length
        ? ui.table({
          columns: [
            { key: 'started_at', label: '开始', render: (row) => esc(Y13.ui.time(row.started_at)) },
            { key: 'status', label: '状态', render: (row) => esc(row.status_text) },
            { key: 'kind', label: '请求类型', render: (row) => esc(ATTEMPT_KIND[row.kind] || row.kind || '') },
            { key: 'requested_model', label: '请求模型', render: (row) => '<span class="y13-obs-model">' + esc(row.requested_model || '—') + '</span>' },
            { key: 'usage', label: '输入 / 输出', render: (row) => row.usage ? '<span class="y13-obs-num">' + esc(row.usage.input) + ' / ' + esc(row.usage.output) + '</span>' : '' },
            { key: 'ops', label: '详情', className: 'y13-col-actions', render: (row) => ui.button({ label: '查看', kind: 'small', go: Y13.paths.observeDetail(ctx.projectId, row.id, row.work_item_id) }) }
          ],
          rows: d.history
        })
        : ui.empty('这个角色还没有历史请求');
      const actions = d.steps.length
        ? d.steps.map((step) => '<h4 class="y13-h3">事项 ' + esc(step.work_item_id) + '</h4>' + ui.table({
          columns: [
            { key: 'summary', label: '动作' },
            { key: 'tool', label: '工具' },
            { key: 'state', label: '状态', render: (row) => esc(ACTION_STATE_TEXT[row.state] || row.state || '') }
          ],
          rows: step.actions
        })).join('')
        : ui.empty('这个角色还没有动作记录');
      detail = '<section class="y13-ws-ctx-detail"><h3 class="y13-h3">' + esc(role.name) + ' 的详情</h3>' +
        ui.kv([
          ['职责', esc(role.duty)],
          ['状态', esc(ROLE_STATUS_TEXT[role.status] || role.status)],
          ['当前任务', role.task ? esc(role.task) : ''],
          ['焦点', role.focus ? esc(role.focus) : ''],
          ['目录', role.directory ? ui.code(role.directory) : ''],
          ['已附加的实体', (role.entities || []).map((entity) => ui.tag(entity)).join(' ') || '']
        ]) +
        '<h3 class="y13-h3">历史请求</h3>' + history +
        '<h3 class="y13-h3">每一步的动作</h3>' + actions + '</section>';
    }
    return table + detail;
  }

  // 账本的分派对象是角色标识；页面上显示角色名，找不到时退回标识
  function roleNameOf(projectId, roleId) {
    if (!roleId) return roleId;
    const data = Y13.api.query('project.settings', { project: projectId }).data;
    const groups = data && data.roles ? data.roles : {};
    let name = null;
    Object.keys(groups).forEach((department) => {
      (groups[department] || []).forEach((role) => { if (role.role_id === roleId) name = role.name || roleId; });
    });
    return name || roleId;
  }

  function ledgerPanel(ctx, v) {
    const ledger = v.ledger;
    if (!ledger) return ui.empty('本页没有部门账本');
    const items = (ledger.items || []).length
      ? ui.table({
        columns: [
          { key: 'id', label: '编号', render: (row) => ui.code(row.id) },
          { key: 'text', label: '计划条目' },
          { key: 'assignee', label: '分派对象', render: (row) => esc(roleNameOf(ctx.projectId, row.assignee) || '—') },
          { key: 'status', label: '状态', render: (row) => { const s = ITEM_STATUS[row.status] || ['idle', row.status]; return ui.status(s[0], s[1]); } },
          { key: 'result', label: '结果摘要', render: (row) => esc(row.result || '') }
        ],
        rows: ledger.items
      })
      : ui.empty('账本还没有计划条目');
    const facts = (ledger.facts || []).length
      ? ui.kv((ledger.facts || []).map((fact) => [fact.id || '事实', esc(fact.text || fact)]))
      : ui.empty('还没有事实');
    const questions = (ledger.questions || []).length
      ? '<ul class="y13-ws-progress">' + ledger.questions.map((q) =>
        '<li>' + ui.status(q.status === 'answered' ? 'succeeded' : 'asking', q.status === 'answered' ? '已回答' : '待决') +
        '<span>' + esc(q.text || q.question || '') + '</span>' + (q.to ? ui.tag('询问 ' + q.to) : '') + '</li>'
      ).join('') + '</ul>'
      : ui.empty('没有待决问题与对外询问');
    const progress = (ledger.progress || []).length
      ? '<ul class="y13-ws-progress">' + ledger.progress.map((entry) =>
        '<li' + (entry.stalled ? ' class="is-stalled"' : '') + '><strong>第 ' + esc(entry.cycle || '—') + ' 轮</strong><span>' + esc(entry.text || '') + '</span>' +
        (entry.review_count !== undefined ? ui.tag('审查 ' + entry.review_count + ' 次') : '') + '</li>'
      ).join('') + '</ul>'
      : ui.empty('还没有每轮的进展判断');
    return '<div class="y13-ws-ledger"><h3 class="y13-h3">计划条目</h3>' + items +
      '<h3 class="y13-h3">事实</h3>' + facts +
      '<h3 class="y13-h3">待决问题与对外询问</h3>' + questions +
      '<h3 class="y13-h3">每轮的进展判断</h3>' + progress + '</div>';
  }

  function semanticPanel(ctx, v) {
    if (!Y13.cap.query('semantic.records')) return ui.empty('本页没有登记语义记录查询');
    const data = Y13.api.query('semantic.records', { project: ctx.projectId, department: v.department.id }).data;
    const groups = { valid: [], invalid: [], superseded: [] };
    data.entries.forEach((unit) => { (groups[unit.status] || groups.valid).push(unit); });
    const group = (title, list, cls) => list.length
      ? '<section class="y13-ws-unit-group"><h4 class="y13-h3">' + esc(title) + '（' + list.length + '）</h4><ul>' + list.map((unit) =>
        '<li class="y13-ws-unit ' + cls + '"><div class="y13-ws-unit-head"><span class="y13-ws-unit-type">' + esc(unit.type || '记录') + '</span>' + ui.tag(unit.scope || '') + '</div>' +
        '<p>' + esc(unit.text) + '</p><small class="y13-muted">' + esc(unit.id) + ' · ' + esc(unit.at ? Y13.ui.time(unit.at) : '') + (unit.reason ? ' · ' + esc(unit.reason) : '') + '</small></li>'
      ).join('') + '</ul></section>'
      : '';
    const conflicts = data.conflicts.length
      ? '<h3 class="y13-h3">冲突（' + data.conflicts.length + '）</h3><ul class="y13-ws-inactive">' + data.conflicts.map((entry) =>
        '<li class="y13-ws-unit is-conflict"><p>' + esc(entry.text || (entry.a + ' 与 ' + entry.b + ' 冲突')) + '</p><small class="y13-muted">' + esc(entry.a || '') + ' · ' + esc(entry.b || '') + '</small></li>'
      ).join('') + '</ul>'
      : '';
    const chains = data.chains.length
      ? '<h3 class="y13-h3">更替链</h3><ul class="y13-ws-chain">' + data.chains.map((chain) =>
        '<li><span class="y13-ws-chain-step">' + ui.code(chain.from) + '<span class="y13-ws-arrow">→</span>' + ui.code(chain.to) + '</span><span class="y13-muted">' + esc(chain.reason || '') + '</span></li>'
      ).join('') + '</ul>'
      : '';
    return '<div class="y13-ws-units">' + group('有效', groups.valid, '') + group('已失效', groups.invalid, 'is-invalid') + group('已被取代', groups.superseded, 'is-superseded') + '</div>' + conflicts + chains;
  }

  function checksInner(ctx, v) {
    const items = [
      { id: 'actions', label: '动作与回执' },
      { id: 'trials', label: '试用记录', tag: '3.2D', show: Boolean(v.trials && v.work_item && Y13.cap.query('run.trials')) },
      { id: 'context', label: 'Context' },
      { id: 'prompt', label: '部门 Prompt' },
      { id: 'roles', label: '角色名单', tag: v.roles ? 'Stage 5' : null, show: Boolean(v.roles) },
      { id: 'ledger', label: '部门账本', tag: v.ledger ? 'Stage 5' : null, show: Boolean(v.ledger) },
      { id: 'semantic', label: '语义面板', tag: 'Stage 5', show: Boolean(AT_LEAST_S5()) }
    ];
    const active = ui.activeTab('dept.checks', items, 'actions');
    const panels = {};
    items.forEach((item) => {
      if (item.show === false) return;
      if (item.id === 'actions') panels[item.id] = actionsPanel(ctx, v);
      else if (item.id === 'trials') panels[item.id] = trialsPanel(v);
      else if (item.id === 'context') panels[item.id] = contextPanel(v);
      else if (item.id === 'prompt') panels[item.id] = promptPanel(v);
      else if (item.id === 'roles') panels[item.id] = rolesPanel(ctx, v);
      else if (item.id === 'ledger') panels[item.id] = ledgerPanel(ctx, v);
      else if (item.id === 'semantic') panels[item.id] = semanticPanel(ctx, v);
    });
    return ui.tabs({ id: 'dept.checks', items, active }) + ui.tabPanels('dept.checks', active, panels);
  }

  // ---------------------------------------------------------------------------
  // 部门消息与指导

  const SOURCE_LABELS = { user: '用户', self: '本部门', other: '其他部门' };
  const GUIDANCE_KIND = { received: 'queued', in_input: 'running', answered: 'succeeded' };
  const ASK_KIND = { open: 'asking', answered: 'succeeded', unable: 'failed' };
  const deptName = (d) => (DEPT[d] ? DEPT[d].label : d);

  // 询问（三部门的循环结构第 4 节）：本部门发出与收到的询问，写明询问链、问题、状态与回答；产品的回答附带 PRD 的新版本时写出版本
  function asksList(v) {
    if (!v.asks || !v.asks.length) return '<p class="y13-muted y13-small">这个事项里本部门还没有发出或收到询问</p>';
    return '<ul class="y13-ws-guidance y13-ws-asks">' + v.asks.map((a) => {
      const out = a.requester === v.department.id;
      return '<li><div class="y13-ws-log-meta"><strong>' + (out ? '问' + esc(deptName(a.recipient)) : esc(deptName(a.requester)) + '问本部门') + '</strong>' +
        ui.status(ASK_KIND[a.status] || 'idle', a.status_text) +
        '<span class="y13-muted">询问链 ' + esc(a.chain.map(deptName).join(' → ')) + '</span>' +
        (a.parent ? ui.tag('回问') : '') + '</div><p>' + esc(a.question) + '</p>' +
        (a.answer ? '<p class="y13-ws-reply">' + esc(a.answer) + (a.prd_version ? ' ' + ui.tag('附带 PRD ' + a.prd_version) : '') + '</p>' : '') +
        (a.reason ? '<p class="y13-ws-reply">没能回答：' + esc(a.reason) + '</p>' : '') + '</li>';
    }).join('') + '</ul>';
  }

  function commsInner(ctx, v) {
    const log = v.messages.length
      ? '<ul class="y13-ws-log">' + v.messages.map((message) =>
        '<li class="is-' + esc(message.source) + '"><div class="y13-ws-log-meta"><span class="y13-ws-src">' + esc(SOURCE_LABELS[message.source] || message.source) + '</span>' +
        '<span class="y13-muted">' + esc(Y13.ui.time(message.at)) + '</span>' + ui.tag('#' + message.seq) + '</div><p>' + esc(message.text) + '</p></li>'
      ).join('') + '</ul>'
      : ui.empty('本部门还没有消息');
    const records = v.guidance.length
      ? '<ul class="y13-ws-guidance">' + v.guidance.map((entry) =>
        '<li><div class="y13-ws-log-meta"><strong>指导 v' + esc(entry.version) + '</strong>' +
        ui.status(GUIDANCE_KIND[entry.status] || 'idle', entry.status_text || entry.status) +
        '<span class="y13-muted">' + esc(Y13.ui.time(entry.at)) + '</span></div><p>' + esc(entry.text) + '</p>' +
        (entry.response ? '<p class="y13-ws-reply">' + esc(entry.response) + '</p>' : '') + '</li>'
      ).join('') + '</ul>'
      : '<p class="y13-muted y13-small">还没有部门指导</p>';
    const active = v.run && !['DONE', 'PAUSED', 'FAILED'].includes(v.run.phase);
    const composer = active
      ? '<div class="y13-ws-composer"><p class="y13-ws-recipient"><span class="y13-muted">当前接收方</span><strong>发给' + esc(v.department.label) + '部门</strong></p>' +
        '<label class="y13-field"><span>向' + esc(v.department.label) + '部门下达指导或追加人类反馈</span>' +
        '<textarea class="y13-textarea" rows="3" id="y13-ws-guidance" data-draft="' + esc('dept.guidance.' + v.run.id + '.' + v.department.id) + '" placeholder="追加对话或指导"></textarea></label>' +
        '<div class="y13-row">' + ui.button({ label: '发送指导', kind: 'primary small', act: 'dept.sendGuidance', data: { workItem: v.work_item.id, department: v.department.id, draftKey: 'dept.guidance.' + v.run.id + '.' + v.department.id } }) +
        '<small class="y13-muted">部门正在工作时，指导在它的下一步作为通知加入；部门在等待工作时，以这段指导开始一轮工作。与修改 Prompt、模型回复分开记录。</small></div></div>'
      : ui.note(v.run ? '事项已结束，不会自动新建；草稿保留在输入框中。' : '本项目没有进行中的事项；在概览页新建事项。', 'info');
    return '<div class="y13-ws-comms-grid"><div class="y13-ws-col"><h3 class="y13-h3">询问 <span class="y13-muted y13-small">提问方停在询问上等待，被询问的部门在询问分支里回答</span></h3>' + asksList(v) +
      '<h3 class="y13-h3">部门消息 <span class="y13-muted y13-small">最新在上 · 用户、本部门与其他部门分开标记</span></h3>' + log + '</div>' +
      '<div class="y13-ws-col"><h3 class="y13-h3">部门指导</h3>' + composer + '<h3 class="y13-h3">指导记录</h3>' + records + '</div></div>';
  }

  // ---------------------------------------------------------------------------
  // 运维工作间（Stage 4）

  function opsBlocks(ctx) {
    if (ctx.department !== 'operations' || !Y13.cap.query('ops.status')) return '';
    const data = Y13.api.query('ops.status', { project: ctx.projectId }).data;
    let env;
    if (data.env) {
      const standing = (data.env.standing || []).length
        ? data.env.standing.map((entry) => ui.tag(entry.machine_name + '：' + (entry.standing.join('、') || '空'))).join(' ')
        : '<span class="y13-muted">没有</span>';
      const backups = data.backups.length
        ? '<h3 class="y13-h3">最近备份</h3>' + ui.table({
          columns: [
            { key: 'id', label: '编号', render: (row) => ui.code(row.id) },
            { key: 'at', label: '时间', render: (row) => esc(Y13.ui.time(row.at)) },
            { key: 'version', label: '版本', render: (row) => esc(row.version || '') },
            { key: 'note', label: '说明', render: (row) => esc(row.note || '') }
          ],
          rows: data.backups
        })
        : '';
      env = ui.block({
        title: '运行环境', query: 'ops.status',
        subtitle: '机器、当前部署的版本、常设授权清单与最近 3 份备份。',
        body: ui.kv([
          ['运行环境', esc(data.env.machine_name)],
          ['当前版本', esc(data.env.version)],
          ['常设授权清单', standing]
        ]) + backups
      });
    } else {
      env = ui.block({ title: '运行环境', query: 'ops.status', body: ui.note('本项目还没有接收运行责任。', 'info') });
    }
    const faults = ui.block({
      title: '故障记录', query: 'ops.status',
      subtitle: '状态、关联的修复事项、修复失败次数与观察窗口剩余时间。',
      body: data.faults.length ? '<div class="y13-ws-incident">' + data.faults.map((fault) =>
        '<div class="y13-ws-incident"><header><strong>' + esc(fault.title) + '</strong>' + ui.status(fault.status === 'open' ? 'failed' : fault.status === 'repairing' ? 'running' : 'done', fault.status === 'open' ? '未处理' : fault.status === 'repairing' ? '修复中' : '观察中') +
        ui.tag('修复 ' + fault.failures + ' 次') + (fault.observe_remaining_sec !== null ? '<span class="y13-muted">观察窗口剩余 ' + esc(Y13.ui.duration(fault.observe_remaining_sec)) + '</span>' : '') + '</header>' +
        (fault.repairs.length ? ui.table({ columns: [{ key: 'work_item_id', label: '修复事项', render: (row) => esc(row.title) }], rows: fault.repairs }) : '<p class="y13-muted">还没有修复事项</p>') +
        '</div>').join('') + '</div>' : ui.empty('还没有故障记录')
    });
    const releases = ui.block({
      title: '发布与回滚记录', query: 'ops.status',
      body: data.releases.length ? ui.table({
        columns: [
          { key: 'at', label: '时间', render: (row) => esc(Y13.ui.time(row.at)) },
          { key: 'version', label: '版本', render: (row) => esc(row.version) },
          { key: 'method', label: '方式', render: (row) => esc(row.method || '') },
          { key: 'note', label: '说明', render: (row) => esc(row.note || '') }
        ],
        rows: data.releases
      }) : ui.empty('还没有发布记录')
    });
    const indicators = ui.block({
      title: '运行指标与报到', query: 'ops.status',
      body: '<div class="y13-ws-indicators">' + data.indicators.map((indicator) =>
        '<div class="y13-ws-indicator"><span>' + esc(indicator.label) + '</span><strong>' + esc(indicator.value) + ' / ' + esc(indicator.of) + '</strong><small>' + esc(indicator.unit || '') + '</small></div>'
      ).join('') + '</div>' +
      (data.check_in ? ui.kv([['最近报到', esc(Y13.ui.time(data.check_in.last_at))], ['报到间隔', esc(data.check_in.every_min + ' 分钟')], ['状态', data.check_in.ok ? '正常' : '异常']]) : ui.note('还没有报到记录', 'info'))
    });
    const decisions = data.decisions.length
      ? ui.block({
        title: '等待回答的决定', query: 'ops.status', command: 'decision.answer',
        body: '<div class="y13-cards">' + data.decisions.map((d) => Y13.cards.render(d, { compact: true })).join('') + '</div>'
      })
      : '';
    return env + faults + releases + indicators + decisions;
  }

  function opsInner(ctx) {
    if (ctx.department !== 'operations') return '';
    if (!Y13.cap.query('ops.status')) {
      return ui.block({ title: '运维工作间', body: ui.note('运维工作间属于「Stage 4」，控制主机的能力清单里还没有 <code>ops.status</code>。', 'info') });
    }
    return opsBlocks(ctx);
  }

  // ---------------------------------------------------------------------------
  // 页面

  function pageHtml(ctx) {
    const v = workspace(ctx);
    return '<div class="y13-ws" data-dept="' + esc(ctx.department) + '">' +
      ui.block({
        query: 'department.workspace', className: 'y13-ws-head-block',
        body: '<div data-ws-head>' + headInner(v) + '</div>'
      }) +
      ui.block({
        title: '部门房间', query: 'department.workspace',
        body: '<div class="y13-ws-stage"><canvas class="y13-ws-canvas"></canvas></div>' +
          '<div class="y13-ws-room-info" data-ws-info>' + infoInner(v) + '</div>'
      }) +
      ui.block({
        title: '检查区', query: ['department.workspace', 'run.actions'],
        subtitle: '房间下方按页签切换；每个页签的内容来自能力清单中登记的查询。',
        body: '<div data-ws-checks>' + checksInner(ctx, v) + '</div>'
      }) +
      ui.block({
        title: '询问、部门消息与指导', query: 'department.workspace', command: 'guidance.send',
        body: '<div data-ws-comms>' + commsInner(ctx, v) + '</div>'
      }) +
      '<div data-ws-ops>' + opsInner(ctx) + '</div>' +
      '</div>';
  }

  function paint(ctx, root) {
    const v = workspace(ctx);
    const head = root.querySelector('[data-ws-head]');
    if (head) head.innerHTML = headInner(v);
    const info = root.querySelector('[data-ws-info]');
    if (info) info.innerHTML = infoInner(v);
    const checks = root.querySelector('[data-ws-checks]');
    if (checks) checks.innerHTML = checksInner(ctx, v);
    const comms = root.querySelector('[data-ws-comms]');
    if (comms) comms.innerHTML = commsInner(ctx, v);
    const ops = root.querySelector('[data-ws-ops]');
    if (ops) ops.innerHTML = opsInner(ctx);
    if (st.scene) st.scene.setModel(v.room);
  }

  function mountRoom(ctx, root) {
    const canvas = root.querySelector('canvas.y13-ws-canvas');
    if (!canvas) throw new Error('部门工作间缺少房间画布');
    const v = workspace(ctx);
    st.scene = Y13.pixel.createRoomScene(canvas, { department: ctx.department });
    st.scene.setModel(v.room);
  }

  Y13.views.register('dept', {
    title: (ctx) => deptLabel(ctx.department) + '部门',
    needs: { queries: ['department.workspace', 'run.actions'], commands: ['guidance.send'] },
    scope: (ctx) => ({ project: ctx.projectId }),
    render: pageHtml,
    mount(ctx, root) {
      st.role = null;
      mountRoom(ctx, root);
      if (st.pending && st.pending.project === ctx.projectId && st.pending.department === ctx.department) {
        st.pending = null;
        openSettings(ctx);
      }
    },
    update(ctx, root, event) {
      paint(ctx, root);
    },
    onEvent(ctx, root, event) {
      if (st.scene) Y13.scenes.playOn(st.scene, event);
    },
    unmount() {
      if (st.modal) {
        Y13.ui.closeModal();
        st.modal = null;
      }
      if (st.scene) {
        st.scene.destroy();
        st.scene = null;
      }
      st.role = null;
    }
  });

  // ---------------------------------------------------------------------------
  // 部门设置弹窗

  const REASONING_LEVELS = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];

  function modelOptions(admitted, current, followLabel) {
    const options = ['<option value=""' + (current ? '' : ' selected') + '>' + esc(followLabel) + '</option>'];
    (admitted || []).forEach((def) => {
      options.push('<option value="' + esc(def.id) + '"' + (def.id === current ? ' selected' : '') + '>' + esc(def.label || def.upstream_model || def.id) + (def.image_input ? '' : '（不支持图像）') + '</option>');
    });
    return options.join('');
  }

  function levelOptions(current, followLabel) {
    return '<option value=""' + (current ? '' : ' selected') + '>' + esc(followLabel) + '</option>' + REASONING_LEVELS.map((level) =>
      '<option value="' + level + '"' + (level === current ? ' selected' : '') + '>' + esc(level) + '</option>'
    ).join('');
  }

  function modalBody() {
    const m = st.modal;
    const v = m.workspace;
    const cat = catalog();
    const admitted = cat ? cat.admitted : [];
    const entry = m.entry;
    const dept = v.department.id;
    const rolesSection = m.rolesSettings && m.rolesSettings.roles && m.rolesSettings.roles[dept] && m.rolesSettings.roles[dept].length
      ? '<section class="y13-dm-roles"><h3 class="y13-h3">本项目各角色设置 ' + ui.tag('Stage 5') + '</h3>' +
        '<p class="y13-muted y13-small">解析顺序：项目角色设置、角色默认、项目部门设置、部门默认，取第一个写入了的。角色 Prompt 没有写入时使用内置角色 Prompt；部门 Prompt 作为全部门规则放入每个角色的请求。</p>' +
        m.rolesSettings.roles[dept].map((role) => {
          const spec = { name: role.name || role.role_id, duty: role.duty || '' };
          return '<div class="y13-dm-role" data-role-id="' + esc(role.role_id) + '">' +
            '<div class="y13-dm-role-name"><strong>' + esc(spec.name) + '</strong><small class="y13-muted">' + esc(spec.duty) + '</small></div>' +
            '<label class="y13-field"><span>模型</span><select class="y13-select" data-role-model>' + modelOptions(admitted, role.model, '跟随角色默认') + '</select></label>' +
            '<label class="y13-field"><span>推理档位</span><select class="y13-select" data-role-level>' + levelOptions(role.request_level, '跟随模型默认') + '</select></label>' +
            '<label class="y13-field y13-dm-role-prompt"><span>角色 Prompt</span><textarea class="y13-textarea" rows="2" data-role-prompt placeholder="空为内置默认">' + esc(role.prompt_text || '') + '</textarea></label>' +
            '</div>';
        }).join('') +
        '<div class="y13-row">' + ui.button({ label: '保存角色设置', kind: 'primary small', act: 'dept.saveRoles' }) +
        '<small class="y13-muted">从这些角色下一次模型请求起生效。当前版本 v' + esc(m.rolesSettings.roles_version) + '。</small></div></section>'
      : '';
    const promptText = entry.prompt_text || '';
    return '<div class="y13-form">' +
      '<label class="y13-field"><span>模型</span><select class="y13-select" id="y13-dm-model">' + modelOptions(admitted, entry.model, '跟随部门默认') + '</select>' +
      '<small class="y13-muted">只列出已准入的模型访问定义；留空表示跟随部门默认。</small></label>' +
      '<label class="y13-field"><span>推理档位</span><select class="y13-select" id="y13-dm-level">' + levelOptions(entry.request_level, '跟随模型默认') + '</select></label>' +
      '<label class="y13-field"><span>部门 Prompt</span><textarea class="y13-textarea" rows="6" id="y13-dm-prompt" placeholder="留空表示使用内置默认 Prompt">' + esc(promptText) + '</textarea>' +
      '<small class="y13-muted">当前版本 v' + esc(entry.version) + '；保存只写入本项目' + esc(v.department.label) + '部门的项目部门设置，不改部门默认。</small></label>' +
      rolesSection +
      '<div class="y13-row">' + ui.button({ label: '保存部门设置', kind: 'primary', act: 'dept.saveSettings' }) + ui.button({ label: '关闭', close: true }) + '</div>' +
      '</div>';
  }

  function openSettings(ctx) {
    const v = workspace(ctx);
    const s = settings(ctx);
    const entry = (s && s.departments && s.departments[v.department.id]) || { version: v.settings_version, model: null, request_level: null, prompt_text: null, prompt_version: 0 };
    const hasRoles = s && s.roles && Array.isArray(s.roles[v.department.id]) && s.roles[v.department.id].length;
    st.modal = {
      projectId: v.project.id,
      department: v.department.id,
      workspace: v,
      entry: entry,
      rolesSettings: AT_LEAST_S5() && hasRoles ? s : null
    };
    Y13.ui.modal({
      title: '本项目 · ' + v.department.label + '部门设置',
      wide: Boolean(st.modal.rolesSettings),
      className: 'y13-dm',
      body: modalBody()
    });
  }

  Y13.actions.register('dept.shot', (el) => {
    const s = Y13.api.query('evidence.screenshot', { work_item: el.dataset.workItem, step: Number(el.dataset.step) }).data;
    const lines = s.text_lines.length ? ui.pre(s.text_lines.join('\n')) : ui.empty('这一步没有记录可访问性结构摘录');
    ui.modal({
      title: '第 ' + s.step + ' 步的截图', wide: true,
      body: '<div class="y13-shot-view"><figure><img src="assets/' + esc(s.screenshot) + '" alt="第 ' + esc(s.step) + ' 步的截图">' +
        '<figcaption>' + esc(s.action || '') + ' · 虚拟屏幕 ' + s.width + '×' + s.height + ' · ' + (s.model_saw ? '模型看到了这张截图' : '模型只读取文字') + '</figcaption></figure>' +
        '<div><h3 class="y13-h3">同一步的可访问性结构摘录</h3>' + lines + '</div></div>',
      actions: [{ label: '关闭', close: true }]
    });
  });

  Y13.actions.register('dept.openSettings', (el) => {
    const ctx = Y13.app.ctx();
    const target = { project: el.dataset.project || ctx.projectId, department: el.dataset.department || ctx.department };
    if (target.project !== ctx.projectId || target.department !== ctx.department) {
      st.pending = target;
      Y13.go(Y13.paths.dept(target.project, target.department, ctx.workItemId));
      return;
    }
    openSettings(ctx);
  });

  Y13.actions.register('dept.selfSettings', () => {
    openSettings(Y13.app.ctx());
  });

  Y13.actions.register('dept.roleDetail', (el) => {
    st.role = st.role === el.dataset.role ? null : el.dataset.role;
    rerender();
  });

  Y13.actions.register('dept.sendGuidance', (el) => {
    const area = document.getElementById('y13-ws-guidance');
    const text = area ? area.value.trim() : '';
    if (!text) {
      Y13.ui.toast('请先写明指导内容', 'warn');
      return;
    }
    const result = Y13.run('guidance.send', { work_item: el.dataset.workItem, department: el.dataset.department, text: text });
    if (!result.accepted) return;
    Y13.app.clearDraft(el.dataset.draftKey);
    if (area) area.value = '';
  });

  Y13.actions.register('dept.saveSettings', () => {
    const m = st.modal;
    if (!m) return;
    const model = document.getElementById('y13-dm-model');
    const level = document.getElementById('y13-dm-level');
    const prompt = document.getElementById('y13-dm-prompt');
    const result = Y13.run('department_settings.save', {
      project: m.projectId,
      department: m.department,
      model: model ? model.value || null : null,
      request_level: level ? level.value || null : null,
      prompt_text: prompt ? prompt.value.trim() || null : null,
      base_version: m.entry.version
    });
    if (!result.accepted) return;
    if (result.refs && result.refs.warning) Y13.ui.toast(result.refs.warning.text, 'warn');
    Y13.ui.closeModal();
    st.modal = null;
    rerender();
  });

  Y13.actions.register('dept.saveRoles', () => {
    const m = st.modal;
    if (!m || !m.rolesSettings) return;
    const rows = Array.prototype.slice.call(document.querySelectorAll('.y13-dm-role[data-role-id]'));
    const roles = rows.map((row) => ({
      role_id: row.dataset.roleId,
      model: row.querySelector('[data-role-model]').value || null,
      request_level: row.querySelector('[data-role-level]').value || null,
      prompt_text: row.querySelector('[data-role-prompt]').value.trim() || null
    }));
    const result = Y13.run('role_settings.save', {
      project: m.projectId,
      department: m.department,
      roles: roles,
      base_version: m.rolesSettings.roles_version
    });
    if (!result.accepted) return;
    if (result.refs && result.refs.warning) Y13.ui.toast(result.refs.warning.text, 'warn');
    Y13.ui.closeModal();
    st.modal = null;
    rerender();
  });
})();
