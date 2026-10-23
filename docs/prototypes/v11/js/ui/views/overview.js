// 概览（设计说明第 5.1 节）：项目摘要、待你决定、循环画面、当前事项、事项看板、流转记录
(function () {
  'use strict';
  const Y11 = window.Y11;
  const esc = Y11.esc;

  let panel = null;
  let flowAll = false;
  let draggedId = null;

  const DEPT_IDS = ['product', 'engineering', 'quality', 'operations'];
  const DEPT_LABEL = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const PLACE = Object.assign({ user: '用户', hall: '大厅', library: '成果库', adoption: '采纳' }, DEPT_LABEL);
  const KIND_LABEL = {
    handoff: '需求交接', delivery: '版本交付', defect: '问题反馈', ask: '咨询',
    answer: '回答', rework: '返工', release: '放行', adopt: '采纳'
  };
  const RECOVERING = ['interrupted', 'pending_verification', 'waiting_resume'];
  const ACTIVE_STATUS = ['not_started', 'queued', 'in_progress'];

  function overview(pid) {
    return Y11.api.query('project.overview', { project: pid }).data;
  }

  function colorOf(index) {
    const colors = Y11.pixel.ITEM_COLORS;
    if (!(index >= 0 && index < colors.length)) throw new Error('事项颜色序号无效：' + index);
    return colors[index];
  }

  function swatch(index) {
    return '<span class="y11-pp-swatch" style="--item:' + colorOf(index) + '" aria-hidden="true"></span>';
  }

  function directionText(from, to) {
    const name = (id) => {
      if (!id) return '—';
      if (!(id in PLACE)) throw new Error('未知的流转位置：' + id);
      return PLACE[id];
    };
    return '<span class="y11-pp-dir">' + esc(name(from)) + '<span class="y11-pp-arrow" aria-hidden="true">→</span>' + esc(name(to)) + '</span>';
  }

  function kindChip(kind) {
    if (!KIND_LABEL[kind]) throw new Error('未知的流转类型：' + kind);
    return '<span class="y11-pp-flowkind is-' + esc(kind) + '"><span>' + esc(KIND_LABEL[kind]) + '</span></span>';
  }

  function stat(label, value, cls) {
    return '<div class="y11-pp-stat' + (cls ? ' is-' + cls : '') + '"><span class="y11-pp-stat-num">' + esc(value) + '</span>' +
      '<span class="y11-pp-stat-label">' + esc(label) + '</span></div>';
  }

  // ---------------------------------------------------------------------------
  // 各区块

  function summaryBlock(ov) {
    const p = ov.project;
    const adoption = ov.adoption;
    const adopt = adoption
      ? '<div class="y11-ov-adopt"><div class="y11-ov-adopt-top"><span class="y11-ov-adopt-ver">' + esc(adoption.version) + '</span>' + Y11.ui.status('adopted', '当前成果') + '</div>' +
        '<p>' + esc(adoption.summary || '（没有摘要）') + '</p>' +
        '<p class="y11-muted y11-small">' + esc(Y11.ui.time(adoption.adopted_at)) + ' 采纳</p></div>'
      : '<div class="y11-ov-adopt is-empty"><span class="y11-muted">当前成果</span><strong>尚未采纳</strong></div>';
    const archived = p.archived ? Y11.ui.note('归档项目只读：查询仍可用，写命令会被拒绝。', 'warn') : '';
    return Y11.ui.block({
      id: 'ov-summary', query: 'project.overview', className: 'y11-ov-summary',
      body: '<div class="y11-ov-hero"><div class="y11-ov-hero-main"><h1 class="y11-ov-title">' + esc(p.name) + '</h1>' +
        '<div class="y11-ov-goal"><span class="y11-muted">长期目标</span><span>' + esc(p.goal || '—') + '</span></div>' +
        (p.source === 'existing' ? '<p class="y11-ov-source">' + Y11.ui.tag('已有项目') + '<span class="y11-muted">从已有代码接入，初始 PRD 由你确认</span></p>' : '') +
        archived + '</div>' + adopt + '</div>' +
        '<div class="y11-ov-stats">' +
          stat('进行中', ov.stats.in_progress, 'running') +
          stat('排队中', ov.stats.queued, 'queued') +
          stat('已采纳', ov.stats.adopted, 'adopted') +
        '</div>'
    });
  }

  function loopBlock(pid, workItemId) {
    return Y11.ui.block({
      id: 'ov-loop', title: '循环画面', query: ['project.loop', 'project.flow'],
      subtitle: '三部门循环、包裹与管道；等待回答的决定贴在大厅的板上，点开就在画面里回答；右上角切换覆盖层，下方时间轴回放本项目的关键事实',
      body: '<div id="ov-floor"></div>'
    });
  }

  function activeOf(ov, ctx) {
    if (ctx.workItemId) {
      const found = ov.work_items.find((item) => item.id === ctx.workItemId);
      if (!found) throw new Error('这个项目里没有事项：' + ctx.workItemId);
      return found;
    }
    return ov.work_items.find((item) => item.status === 'in_progress') || null;
  }

  function inputList(item) {
    const info = Y11.api.query('work_item.inputs', { work_item: item.id }).data;
    if (!info.inputs.length) return Y11.ui.empty('这个事项还没有输入记录');
    const steps = ['received', 'assigned', 'accepted'];
    const labels = { received: '已接收', assigned: '已交给产品处理', accepted: '已由有效需求接纳' };
    return '<ol class="y11-ov-inputs">' + info.inputs.slice().reverse().map((input) => {
      const at = steps.indexOf(input.progress);
      if (at < 0) throw new Error('未知的处理进度：' + input.progress);
      const bytes = Array.isArray(input.bytes)
        ? '字节 ' + input.bytes[0] + '–' + input.bytes[1]
        : (typeof input.bytes === 'number' ? Y11.ui.num(input.bytes) + ' 字节' : '');
      return '<li class="y11-ov-input' + (input.kind === 'command' ? ' is-command' : '') + '">' +
        '<div class="y11-ov-input-head"><strong>v' + esc(input.version) + '</strong>' +
          (input.kind === 'command' ? Y11.ui.tag('文本命令') : Y11.ui.tag('用户输入')) +
          '<span class="y11-muted">' + esc(Y11.ui.time(input.at)) + (bytes ? ' · ' + esc(bytes) : '') + '</span></div>' +
        '<p class="y11-ov-input-text">' + esc(input.text) + '</p>' +
        '<ul class="y11-ov-steps">' + steps.map((step, index) =>
          '<li class="' + (index < at ? 'is-done' : index === at ? 'is-current' : '') + '">' + esc(labels[step]) + '</li>').join('') + '</ul>' +
      '</li>';
    }).join('') + '</ol>';
  }

  function itemMeta(item) {
    const parts = [];
    parts.push('<span>所在部门：' + esc(item.department ? DEPT_LABEL[item.department] : '大厅') + '</span>');
    if (item.cycle) parts.push('<span>第 ' + esc(item.cycle) + ' 轮</span>');
    if (item.started_at) {
      parts.push('<span class="y11-ov-time">已用 ' + esc(Y11.ui.duration(item.elapsed_sec)) + ' / ' + esc(Y11.ui.duration(item.limit_sec)) +
        Y11.ui.meter(item.elapsed_sec, item.limit_sec, { warnAt: 0.8 }) + '</span>');
    }
    return '<div class="y11-ov-item-meta">' + parts.join('') + '</div>';
  }

  function currentBody(ov, target, ctx) {
    const pid = ov.project.id;
    if (!target) {
      if (!ov.work_items.length) return Y11.ui.empty('这个项目还没有事项') + composerHtml(ov, null);
      const switchRow = '<div class="y11-ov-switch"><span class="y11-muted y11-small">这个项目没有进行中的事项；选择一个事项查看它的输入记录：</span>' + ov.work_items.map((item) =>
        '<button type="button" class="y11-pp-chip" data-go="' + esc(Y11.paths.overview(pid, item.id)) + '">' + swatch(item.color_index) + esc(item.title) + '</button>').join('') + '</div>';
      return switchRow + composerHtml(ov, null);
    }
    const head = '<div class="y11-ov-item-head">' + swatch(target.color_index) + '<h3>' + esc(target.title) + '</h3>' +
      Y11.ui.status(target.display.kind, target.display.text) + '</div>' + itemMeta(target);
    const recovering = RECOVERING.includes(target.recovery_state);
    const note = recovering
      ? Y11.ui.note(Y11.ui.status(target.display.kind, target.display.text) + ' ' + esc(target.display.text) +
        '<span class="y11-note-actions">' + Y11.ui.button({ label: '查看恢复与动作核实', kind: 'small primary', go: Y11.paths.recovery(pid, target.id) }) + '</span>', 'warn')
      : (target.pending_question ? Y11.ui.note('待决问题：' + esc(target.pending_question), 'warn') : '');
    const switcher = !ctx.workItemId && ov.work_items.length > 1
      ? '<div class="y11-ov-switch"><span class="y11-muted y11-small">全部事项：</span>' + ov.work_items.map((item) =>
        '<button type="button" class="y11-pp-chip" data-go="' + esc(Y11.paths.overview(pid, item.id)) + '">' + swatch(item.color_index) + esc(item.title) + '</button>').join('') + '</div>'
      : '';
    return switcher + head + note + inputList(target) + composerHtml(ov, target);
  }

  function composerHtml(ov, target) {
    const pid = ov.project.id;
    if (ov.project.archived) return Y11.ui.note('归档项目只读：不能追加需求、记录原文或新建事项。', 'warn');
    if (target && ACTIVE_STATUS.includes(target.status)) {
      return '<div class="y11-ov-composer">' +
        '<label class="y11-field"><span>追加需求 · 「' + esc(target.title) + '」</span>' +
          '<textarea class="y11-textarea" rows="3" id="ov-append-text" data-draft="ov.append.' + esc(target.id) + '" placeholder="补充或修改这个事项的要求；输入 /stop 或 /cancel 立即停止"></textarea></label>' +
        '<div class="y11-ov-composer-foot"><small class="y11-muted">提交后进入当前事项的产品入口，由产品部门处理</small>' +
          '<div class="y11-row">' +
            Y11.ui.button({ label: '取消事项', kind: 'small', act: 'ov.cancel', data: { workItem: target.id } }) +
            Y11.ui.button({ label: '追加需求', kind: 'small primary', act: 'ov.append', data: { workItem: target.id } }) +
          '</div></div></div>';
    }
    const dirs = ov.source_directories || [];
    const source = dirs.length
      ? '<label class="y11-field"><span>可信源目录（可选，作为新事项的代码快照来源）</span>' +
        '<select class="y11-input" id="ov-new-src"><option value="">不使用源目录</option>' +
        dirs.map((dir) => '<option value="' + esc(dir.path) + '">' + esc(dir.name) + ' · ' + esc(dir.path) + '</option>').join('') + '</select></label>'
      : '';
    return '<div class="y11-ov-composer">' +
      '<label class="y11-field"><span>新的想法或材料</span>' +
        '<textarea class="y11-textarea" rows="3" id="ov-new-text" data-draft="ov.new.' + esc(pid) + '" placeholder="描述这次要改变什么，或先记下原文"></textarea></label>' +
      '<label class="y11-field"><span>事项标题（可选）</span>' +
        '<input type="text" class="y11-input" id="ov-new-title" data-draft="ov.title.' + esc(pid) + '" placeholder="留空时取原文第一行"></label>' +
      source +
      '<div class="y11-ov-composer-foot"><small class="y11-muted">「记录原文」只保存材料，不调用模型；「作为新事项开始」进入产品部门</small>' +
        '<div class="y11-row">' +
          Y11.ui.button({ label: '记录原文', kind: 'small', act: 'ov.record', data: { project: pid } }) +
          Y11.ui.button({ label: '作为新事项开始', kind: 'small primary', act: 'ov.create', data: { project: pid } }) +
        '</div></div></div>';
  }

  function currentBlock(ov, target, ctx) {
    return Y11.ui.block({
      id: 'ov-current', title: '当前事项',
      query: ['work_item.inputs'], command: ['material.record', 'work_item.create', 'work_item.append_input', 'work_item.cancel'],
      body: currentBody(ov, target, ctx)
    });
  }

  function columnOf(item) {
    if (item.status === 'queued' && item.display.kind === 'waiting' && DEPT_IDS.includes(item.department)) return item.department;
    if (item.status === 'queued' || item.status === 'not_started') return 'queued';
    if (item.status === 'adopted') return 'adopted';
    if (item.status === 'released') return 'released';
    if (DEPT_IDS.includes(item.department)) return item.department;
    if (item.status === 'in_progress') return 'product';
    return null;
  }

  function cardDetail(item) {
    if (RECOVERING.includes(item.recovery_state)) return '待恢复或待核实：' + item.display.text;
    if (item.pending_question) return '待决：' + item.pending_question;
    if (item.stop_reason) return item.stop_reason.text || item.stop_reason.code;
    return '';
  }

  function boardCard(pid, item) {
    const movable = item.status === 'queued' && item.kind !== 'repair' && item.queue_reason !== 'decision' && Y11.cap.command('work_item.reorder');
    const detail = cardDetail(item);
    const actions = RECOVERING.includes(item.recovery_state)
      ? '<div class="y11-ov-card-actions">' + Y11.ui.button({ label: '查看恢复与动作核实', kind: 'small primary', go: Y11.paths.recovery(pid, item.id) }) + '</div>'
      : '';
    return '<article class="y11-ov-card' + (item.kind === 'repair' ? ' is-repair' : '') + '" style="--item:' + colorOf(item.color_index) + '"' +
      ' data-card-work-item="' + esc(item.id) + '"' + (movable ? ' draggable="true"' : '') + '>' +
      '<header class="y11-ov-card-head">' + swatch(item.color_index) + '<strong class="y11-ov-card-title"><button type="button" class="y11-pp-title" data-go="' + esc(Y11.paths.overview(pid, item.id)) + '">' + esc(item.title) + '</button></strong>' +
        (item.kind === 'repair' ? Y11.ui.tag('修复') : '') + '</header>' +
      '<div class="y11-ov-card-status">' + Y11.ui.status(item.display.kind, item.display.text) + '</div>' +
      '<div class="y11-ov-card-meta">' + esc(item.department ? DEPT_LABEL[item.department] : '大厅') + (item.cycle ? ' · 第 ' + esc(item.cycle) + ' 轮' : '') +
        (item.status === 'queued' && item.queue_pos != null ? ' · 第 ' + esc(item.queue_pos) + ' 位' : '') + '</div>' +
      (detail ? '<p class="y11-ov-card-detail">' + esc(detail) + '</p>' : '') + actions +
    '</article>';
  }

  function boardBlock(ov) {
    const pid = ov.project.id;
    const columns = [
      { id: 'queued', label: '排队中' },
      { id: 'product', label: '产品' },
      { id: 'engineering', label: '工程' },
      { id: 'quality', label: '质检' }
    ];
    if (ov.work_items.some((item) => columnOf(item) === 'operations')) columns.push({ id: 'operations', label: '运维' });
    columns.push({ id: 'released', label: '已放行' }, { id: 'adopted', label: '已采纳' });
    const groups = {};
    ov.work_items.forEach((item) => {
      const col = columnOf(item);
      if (!col) return;
      (groups[col] = groups[col] || []).push(item);
    });
    if (groups.queued) {
      groups.queued.sort((a, b) => (a.kind === 'repair' ? 0 : 1) - (b.kind === 'repair' ? 0 : 1) || ((a.queue_pos || 0) - (b.queue_pos || 0)));
    }
    const body = '<div class="y11-ov-board">' + columns.map((col) => {
      const items = groups[col.id] || [];
      const cards = items.map((item) => boardCard(pid, item)).join('');
      const dropHint = col.id === 'queued' && Y11.cap.command('work_item.reorder')
        ? '<p class="y11-ov-board-hint">拖动调整顺序；修复事项固定在最前面</p>' : '';
      return '<section class="y11-ov-board-col is-' + col.id + '" data-col="' + col.id + '">' +
        '<header class="y11-ov-board-head"><h3>' + esc(col.label) + '</h3><span class="y11-count">' + items.length + '</span></header>' +
        (cards || '<p class="y11-ov-board-empty">没有事项</p>') + dropHint + '</section>';
    }).join('') + '</div>';
    return Y11.ui.block({
      id: 'ov-board', title: '事项看板', query: 'project.overview',
      command: Y11.cap.command('work_item.reorder') ? 'work_item.reorder' : null,
      subtitle: '卡片显示标题、状态、所在部门与轮次；排队中的顺序就是执行顺序', body
    });
  }

  function flowBlock(pid, workItemId) {
    const params = { project: pid };
    if (workItemId) params.work_item = workItemId;
    const rows = Y11.api.query('project.flow', params).data.rows;
    const shown = flowAll ? rows : rows.slice(0, 12);
    const showItem = !workItemId;
    let body;
    if (!shown.length) {
      body = Y11.ui.empty('这个范围内还没有流转记录');
    } else {
      const head = '<li class="y11-ov-flow-row is-head"><span>时间</span>' + (showItem ? '<span>事项</span>' : '') +
        '<span>方向</span><span>类型</span><span>内容</span><span>状态</span><span>原始事件</span></li>';
      const list = shown.map((row) => '<li class="y11-ov-flow-row' + (row.kind === 'rework' ? ' is-rework' : '') + '">' +
        '<span class="y11-ov-flow-time">' + esc(Y11.ui.time(row.at)) + '</span>' +
        (showItem ? '<span class="y11-ov-flow-item">' + esc(itemTitle(pid, row.work_item_id)) + '</span>' : '') +
        '<span class="y11-ov-flow-dir">' + directionText(row.from, row.to) + '</span>' +
        '<span class="y11-ov-flow-kind">' + kindChip(row.kind) + '</span>' +
        '<span class="y11-ov-flow-content">' + esc(row.content) + '</span>' +
        '<span class="y11-ov-flow-status">' + esc(row.status) + '</span>' +
        '<span class="y11-ov-flow-event">' + (row.event_position
          ? '<button type="button" class="y11-link" data-act="ov.event" data-position="' + esc(row.event_position) + '">打开事件</button>'
          : '<span class="y11-muted">—</span>') + '</span></li>').join('');
      body = '<ul class="y11-ov-flow' + (showItem ? ' has-item' : '') + '">' + head + list + '</ul>' +
        (rows.length > 12 ? '<div class="y11-ov-flow-more">' + Y11.ui.button({ label: flowAll ? '只看最近 12 条' : '显示全部 ' + rows.length + ' 条', kind: 'small', act: 'ov.flowAll' }) + '</div>' : '');
    }
    return Y11.ui.block({
      id: 'ov-flow', title: '流转记录', query: 'project.flow',
      subtitle: workItemId ? '所选事项的流转' : '整个项目；返工行用醒目的颜色标出', body
    });
  }

  function itemTitle(pid, workItemId) {
    const item = overview(pid).work_items.find((entry) => entry.id === workItemId);
    return item ? item.title : workItemId;
  }

  // ---------------------------------------------------------------------------
  // 页面

  function render(ctx) {
    const pid = ctx.projectId;
    const ov = overview(pid);
    const target = activeOf(ov, ctx);
    return '<div class="y11-pp y11-ov">' +
      summaryBlock(ov) +
      loopBlock(pid, ctx.workItemId) +
      currentBlock(ov, target, ctx) +
      boardBlock(ov) +
      flowBlock(pid, ctx.workItemId) +
    '</div>';
  }

  function bindBoard(root) {
    const board = root.querySelector('#ov-board');
    if (!board) return;
    const queueCol = board.querySelector('[data-col="queued"]');
    if (!queueCol) return;
    queueCol.querySelectorAll('[data-card-work-item][draggable="true"]').forEach((card) => {
      card.addEventListener('dragstart', (ev) => {
        draggedId = card.dataset.cardWorkItem;
        ev.dataTransfer.effectAllowed = 'move';
        ev.dataTransfer.setData('text/plain', draggedId);
        card.classList.add('is-dragging');
      });
      card.addEventListener('dragend', () => {
        draggedId = null;
        card.classList.remove('is-dragging');
        queueCol.classList.remove('is-drop');
      });
      card.addEventListener('dragover', (ev) => {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';
        queueCol.classList.add('is-drop');
      });
      card.addEventListener('dragleave', () => queueCol.classList.remove('is-drop'));
      card.addEventListener('drop', (ev) => {
        ev.preventDefault();
        queueCol.classList.remove('is-drop');
        if (!draggedId || draggedId === card.dataset.cardWorkItem) return;
        const pid = Y11.route().params.projectId;
        const ov = overview(pid);
        const movable = ov.work_items.filter((item) => item.status === 'queued' && item.kind !== 'repair' && item.queue_reason !== 'decision').map((item) => item.id);
        const order = movable.filter((id) => id !== draggedId);
        const at = order.indexOf(card.dataset.cardWorkItem);
        order.splice(at < 0 ? order.length : at, 0, draggedId);
        Y11.run('work_item.reorder', { project: pid, order: order.join(','), base_version: ov.project.version });
      });
    });
  }

  function mount(ctx, root) {
    panel = Y11.scenes.mountFloor(root.querySelector('#ov-floor'), { projectId: ctx.projectId, workItemId: ctx.workItemId });
    bindBoard(root);
  }

  function refresh(root, selector, html) {
    const el = root.querySelector(selector);
    if (!el) return;
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const next = tmp.firstElementChild;
    if (next) el.replaceWith(next);
  }

  function update(ctx, root) {
    const pid = ctx.projectId;
    const ov = overview(pid);
    const target = activeOf(ov, ctx);
    refresh(root, '#ov-summary', summaryBlock(ov));
    refresh(root, '#ov-current', currentBlock(ov, target, ctx));
    refresh(root, '#ov-board', boardBlock(ov));
    refresh(root, '#ov-flow', flowBlock(pid, ctx.workItemId));
    bindBoard(root);
    if (panel) panel.update();
  }

  Y11.views.register('overview', {
    title: () => '概览',
    needs: { queries: ['project.overview', 'project.loop', 'project.flow', 'work_item.inputs'] },
    render,
    mount,
    update,
    onEvent: (ctx, root, ev) => { if (panel) panel.onEvent(ev); },
    unmount: () => { if (panel) panel.destroy(); panel = null; },
    scope: (ctx) => ({ project: ctx.projectId })
  });

  // ---------------------------------------------------------------------------
  // 界面动作

  Y11.actions.register('ov.append', (el) => {
    const box = document.getElementById('ov-append-text');
    const result = Y11.run('work_item.append_input', { work_item: el.dataset.workItem, text: box.value });
    if (!result.accepted) return;
    box.value = '';
    Y11.app.clearDraft('ov.append.' + el.dataset.workItem);
  });

  Y11.actions.register('ov.cancel', (el) => {
    const pid = Y11.route().params.projectId;
    const item = overview(pid).work_items.find((entry) => entry.id === el.dataset.workItem);
    if (!item) throw new Error('事项不存在：' + el.dataset.workItem);
    Y11.ui.modal({
      title: '取消事项',
      body: '<p>取消「' + esc(item.title) + '」：run 记为失败（原因为用户取消），执行槽位释放，队首事项取得槽位。取消以后不能恢复。</p>',
      actions: [
        { label: '返回', close: true },
        { label: '取消事项', kind: 'primary', act: 'ov.cancelConfirm', data: { workItem: item.id } }
      ]
    });
  });

  Y11.actions.register('ov.cancelConfirm', (el) => {
    const result = Y11.run('work_item.cancel', { work_item: el.dataset.workItem });
    if (result.accepted) Y11.ui.closeModal();
  });

  Y11.actions.register('ov.record', (el) => {
    const box = document.getElementById('ov-new-text');
    const result = Y11.run('material.record', { project: el.dataset.project, text: box.value });
    if (!result.accepted) return;
    box.value = '';
    Y11.app.clearDraft('ov.new.' + el.dataset.project);
  });

  Y11.actions.register('ov.create', (el) => {
    const pid = el.dataset.project;
    const box = document.getElementById('ov-new-text');
    const titleEl = document.getElementById('ov-new-title');
    const srcEl = document.getElementById('ov-new-src');
    const result = Y11.run('work_item.create', {
      project: pid, text: box.value,
      title: titleEl ? titleEl.value : null,
      source_dir: srcEl && srcEl.value ? srcEl.value : null
    });
    if (!result.accepted) return;
    box.value = '';
    if (titleEl) titleEl.value = '';
    Y11.app.clearDraft('ov.new.' + pid);
    Y11.app.clearDraft('ov.title.' + pid);
    Y11.go(Y11.paths.overview(pid, result.refs.work_item_id));
  });

  Y11.actions.register('ov.flowAll', () => {
    flowAll = !flowAll;
    const pid = Y11.route().params.projectId;
    const route = Y11.route();
    refresh(Y11.app.dom.content, '#ov-flow', flowBlock(pid, route.query.w || null));
  });

  Y11.actions.register('ov.event', (el) => {
    const data = Y11.api.query('event.detail', { position: Number(el.dataset.position) }).data;
    const ev = data.event;
    const rows = [
      ['时间', esc(Y11.ui.time(ev.at))],
      ['类型', Y11.ui.code(ev.type)],
      ['说明', esc(ev.label)],
      ['项目', esc(ev.project_id || '—')],
      ['事项', esc(ev.work_item_id || '—')],
      ['run', esc(ev.run_id || '—')],
      ['部门', esc(ev.department ? (DEPT_LABEL[ev.department] || ev.department) : '—')],
      ['角色', esc(ev.role || '—')],
      ['发起者', esc(ev.actor || '—')]
    ];
    const artifacts = data.artifacts.length
      ? '<h3 class="y11-h3">引用的工件</h3><ul class="y11-source-list">' + data.artifacts.map((a) =>
        '<li><strong>' + esc(a.title) + '</strong> <span class="y11-muted">' + esc(a.kind) + '</span>' + Y11.ui.pre(a.text) + '</li>').join('') + '</ul>'
      : '';
    Y11.ui.modal({
      title: '事件 ' + ev.position, wide: true,
      body: Y11.ui.kv(rows, 'is-rows') +
        '<h3 class="y11-h3">载荷</h3>' + Y11.ui.pre(JSON.stringify(ev.payload || {}, null, 2)) + artifacts,
      actions: [{ label: '关闭', close: true }]
    });
  });
})();
