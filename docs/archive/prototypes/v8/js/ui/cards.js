// 决定卡片（设计说明第 6 节）：首页与项目页面共用。卡片头、按种类的材料、回答（选项与说明）、在项目中查看
(function () {
  'use strict';
  const Y8 = window.Y8;
  const esc = Y8.esc;

  // 已提交、事件流还没有送来结果的决定请求
  const submitted = {};

  const DEPT = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const dept = (d) => (d ? DEPT[d] || d : '');

  function machineName(id) {
    if (!id || !Y8.cap.query('machines.list')) return id || '';
    const m = Y8.api.query('machines.list', {}).data.find((x) => x.id === id);
    return m ? m.name : id;
  }

  function linkLabel(href) {
    if (href.startsWith('#/sys/models')) return '前往模型管理';
    if (/\/settings$/.test(href)) return '前往本项目的部门设置';
    if (/\/dept\//.test(href)) return '给该部门写指导';
    return '打开';
  }

  // 每种决定请求需要的材料（BUILD.md 第 8.2 节）
  function materialsHtml(d) {
    const m = d.materials || {};
    const kv = [];
    const code = (v) => (v === undefined || v === null || v === '' ? '' : Y8.ui.code(v));
    const text = (v) => (v === undefined || v === null ? '' : esc(v));
    switch (d.kind) {
      case 'waiting_resume':
        kv.push(['部门', text(dept(m.department))], ['模型', code(m.model)], ['具体问题', text(m.problem)]);
        break;
      case 'unknown_action':
        kv.push(['动作', code(m.action_id)], ['所属部门', text(dept(m.department))]);
        if (m.machine_id) kv.push(['执行的机器', text(machineName(m.machine_id))]);
        kv.push(['输入依据', text(m.input)], ['执行前快照', text(m.before)], ['执行后快照', text(m.after)], ['核实依据', text(m.basis)],
          ['契约是否声明可以重复', m.repeatable ? '可以重复执行' : '不能重复执行']);
        break;
      case 'tool_once':
        kv.push(['工具', text(m.tool)], ['目标', code(m.target)], ['本项目的授权范围', text(m.scope)], ['超出的部分', text(m.exceeds)]);
        break;
      case 'cannot_verify':
        kv.push(['质检模型', code(m.model)], ['输入方式', text(m.input)]);
        (m.items || []).forEach((it) => kv.push([it.criterion, text(it.reason)]));
        break;
      case 'initial_prd':
        kv.push(['初始 PRD 摘要', text(m.prd_summary)]);
        if (m.prd_material_id) kv.push(['原文', '<button type="button" class="y8-link" data-go="' + esc(Y8.paths.materials(d.project_id, d.work_item_id)) + '">在资料中查看初始 PRD</button>']);
        if (m.structure_material_id) kv.push(['现有结构说明', '<button type="button" class="y8-link" data-go="' + esc(Y8.paths.materials(d.project_id, d.work_item_id)) + '">工程写出的现有结构说明</button>']);
        break;
      case 'provider_wait':
        kv.push(['部门', text(dept(m.department))], ['模型服务', text(m.provider)], ['失败的分类', text(m.category)], ['下一次重试', m.next_retry_at ? esc(Y8.ui.time(m.next_retry_at)) : '']);
        break;
      case 'external_action':
        kv.push(['动作', text(m.action)], ['运行环境', text(machineName(m.machine_id))], ['运维给出的理由', text(m.reason)], ['证据', text(m.evidence)]);
        break;
      case 'rollback_restore':
        kv.push(['故障记录', code(m.fault_id)], ['回滚的目标版本', code(m.to_version)],
          ['将要恢复的备份', m.backup ? esc(m.backup.id) + ' · ' + esc(Y8.ui.time(m.backup.at)) : ''], ['交付说明中不兼容的说明', text(m.incompatible)]);
        break;
      case 'repair_stopped':
        kv.push(['故障记录', code(m.fault_id)], ['当前运行的版本', code(m.running_version)]);
        (m.repairs || []).forEach((r, i) => kv.push(['第 ' + (i + 1) + ' 次修复', code(r.work_item_id) + ' ' + text(r.evidence)]));
        break;
      case 'rework_reminder':
        kv.push(['计划条目', text(m.plan_item)], ['退回次数', text(m.returns)], ['最近一次的审查意见', text(m.last_review)]);
        break;
      default:
        throw new Error('未知的决定种类：' + d.kind);
    }
    const links = (m.links || []).map((href) => '<button type="button" class="y8-btn small" data-go="' + esc(href) + '">' + esc(linkLabel(href)) + '</button>').join('');
    return Y8.ui.kv(kv, 'y8-card-kv') + (links ? '<div class="y8-row y8-card-links">' + links + '</div>' : '');
  }

  function blocksHtml(d) {
    const b = d.blocks;
    if (!b || !b.scope) return '<span class="y8-muted">不挡住事项</span>';
    const parts = [];
    if (b.work_item_title) parts.push('挡住「' + esc(b.work_item_title) + '」');
    else if (d.work_item_title) parts.push('挡住「' + esc(d.work_item_title) + '」');
    if (b.queued_behind) parts.push('同一项目中排在它后面的事项 ' + b.queued_behind + ' 个');
    return parts.join('，') || '挡住本事项';
  }

  function render(d, opts) {
    const o = opts || {};
    const tag = Y8.registry.tagOf('decision', d.kind);
    const isSubmitted = submitted[d.id] && d.status === 'waiting';
    const answered = d.status !== 'waiting';
    const note = 'decision.' + d.id + '.note';
    const options = d.options.map((op) => Y8.ui.button({
      label: op.label, kind: 'small' + (op.kind === 'primary' ? ' primary' : op.kind === 'danger' ? ' danger' : ''),
      act: 'cards.answer', disabled: isSubmitted || answered,
      data: { decisionId: d.id, option: op.id, version: d.version },
      title: op.requires === 'model_ok' ? '修复模型配置以后才能继续' : op.note_required ? '需要在说明中写明修改意见' : null
    })).join('');
    const answerHtml = answered
      ? '<p class="y8-card-result">' + (d.status === 'answered' ? '已回答：' + esc(d.answer ? d.answer.label || d.answer.option : '') : '已撤销') + '</p>'
      : '<div class="y8-card-answer">' +
          '<textarea class="y8-textarea" rows="2" data-draft="' + esc(note) + '" placeholder="说明（可选）"' + (isSubmitted ? ' disabled' : '') + '></textarea>' +
          '<div class="y8-row">' + options + (isSubmitted ? '<span class="y8-card-submitted">已提交，等待控制主机确认</span>' : '') + '</div></div>';
    const where = esc(d.project_name) + (d.work_item_title ? ' · ' + esc(d.work_item_title) : '');
    return '<article class="y8-card is-' + esc(d.kind) + (isSubmitted ? ' is-submitted' : '') + '" id="decision-' + esc(d.id) + '">' +
      '<header class="y8-card-head">' +
        '<div class="y8-card-title">' + Y8.ui.icon('decide') + '<strong>' + esc(d.kind_label) + '</strong>' + Y8.ui.tag(tag) + '</div>' +
        '<div class="y8-card-meta"><span>' + where + '</span><span>已等待 ' + esc(Y8.ui.duration(d.waited_sec)) + '</span><span>' + blocksHtml(d) + '</span></div>' +
      '</header>' +
      '<details class="y8-card-body"' + (o.compact ? '' : ' open') + '><summary>材料</summary>' + materialsHtml(d) + '</details>' +
      answerHtml +
      (d.view ? '<footer class="y8-card-foot"><button type="button" class="y8-link" data-go="' + esc(d.view) + '">在项目中查看</button></footer>' : '') +
    '</article>';
  }

  function list(filter) {
    const f = filter || {};
    const items = Y8.api.query('decisions.list', f.project ? { project: f.project } : {}).data;
    Object.keys(submitted).forEach((id) => { if (!items.some((d) => d.id === id)) delete submitted[id]; });
    if (!items.length) return Y8.ui.empty(f.project ? '本项目没有等待回答的决定' : '没有等待回答的决定');
    return '<div class="y8-cards">' + items.map((d) => render(d, { compact: f.compact })).join('') + '</div>';
  }

  Y8.actions.register('cards.answer', (el) => {
    const id = el.dataset.decisionId;
    const card = el.closest('.y8-card');
    const noteEl = card ? card.querySelector('textarea') : null;
    const result = Y8.run('decision.answer', { decision_id: id, option: el.dataset.option, note: noteEl ? noteEl.value : '', base_version: Number(el.dataset.version) });
    if (!result.accepted) return;
    submitted[id] = result.position;
    Y8.app.clearDraft('decision.' + id + '.note');
    if (card) {
      card.classList.add('is-submitted');
      card.querySelectorAll('button[data-act="cards.answer"], textarea').forEach((b) => { b.disabled = true; });
      const row = card.querySelector('.y8-card-answer .y8-row');
      if (row && !row.querySelector('.y8-card-submitted')) row.insertAdjacentHTML('beforeend', '<span class="y8-card-submitted">已提交，等待控制主机确认</span>');
    }
  });

  Y8.cards = { render, list };
})();
