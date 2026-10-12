// 资料（设计说明第 4.4 节）：按事项只读查看 intend、PRD、PLAN、交付（文件清单、Git 差异、文件下载）、质检与项目材料；
// Stage 4 起加入语义记录（有效要求集合、更替链、冲突、数据流核对）。注册页面 materials、查询 work_item.materials、semantic.records。
(function () {
  'use strict';

  const Y7 = window.Y7;
  const esc = Y7.esc;
  const ui = Y7.ui;
  const kit = Y7.projectKit;
  if (!kit) throw new Error('materials.js 需要先加载 js/views/overview.js（Y7.projectKit）');

  const KIND_LABELS = { intend: 'intend', prd: 'PRD', plan: 'PLAN', delivery: '交付', qa: '质检' };
  const UNIT_TYPES = ['用户输入', '要求', '验收条件', '约束', '决定', '计划项', '交付', '检查结果', '缺陷', '放行'];
  const UNIT_STATES = { valid: '有效', superseded: '已取代', invalid: '已失效', conflict: '有冲突' };
  const VERDICTS = { release: '质检放行', rework_engineering: '返工 · 工程', rework_product: '返工 · 产品' };

  // 语义记录的查看方式（页面内的显示选项，不写入数据）
  const view = { showAll: false, onlyItem: false };

  // ---------------------------------------------------------------------------
  // 查询

  function byVersion(list) {
    return list.slice().sort((a, b) => a.version - b.version);
  }

  Y7.queries.register('work_item.materials', (params) => {
    const projectId = params.projectId || Y7.state.projectId;
    const project = Y7.project(projectId);
    if (!project) throw new Error('项目不在当前档位或不存在：' + projectId);
    const all = Y7.resolve(Y7.data.materials).filter((m) => m.projectId === projectId);
    const notes = all.filter((m) => m.kind === 'note').sort((a, b) => new Date(b.at) - new Date(a.at));
    const items = Y7.workItemsOf(projectId).map((item) => {
      const mine = all.filter((m) => m.workItemId === item.id);
      const counts = {};
      Object.keys(KIND_LABELS).forEach((kind) => { counts[kind] = mine.filter((m) => m.kind === kind).length; });
      return { item, display: Y7.workItemStatus(item, item.runId ? Y7.run(item.runId) : null), counts };
    });
    const result = { project, items, notes, workItem: null };
    if (!params.workItemId) return result;
    const item = Y7.workItem(params.workItemId);
    if (!item || item.projectId !== projectId) throw new Error('事项不在这个项目或当前档位：' + params.workItemId);
    const run = item.runId ? Y7.run(item.runId) : null;
    const mine = all.filter((m) => m.workItemId === item.id);
    const actions = run ? run.actions : [];
    const qa = byVersion(mine.filter((m) => m.kind === 'qa')).map((m) => Object.assign({}, m, {
      receiptActions: (m.receipts || []).map((id) => {
        const action = actions.find((a) => a.id === id);
        if (!action) throw new Error('质检回执引用的动作不存在：' + id);
        return action;
      })
    }));
    return Object.assign(result, {
      workItem: item,
      display: Y7.workItemStatus(item, run),
      intend: byVersion(mine.filter((m) => m.kind === 'intend')),
      prd: byVersion(mine.filter((m) => m.kind === 'prd')),
      plan: byVersion(mine.filter((m) => m.kind === 'plan')),
      delivery: byVersion(mine.filter((m) => m.kind === 'delivery')),
      qa,
      adoption: (project.adoptions || []).find((entry) => entry.workItemId === item.id) || null
    });
  });

  // 可选参数 department：给出时返回项目共享单元与该部门的私有单元（部门工作间的语义面板使用），冲突与更替链按同一范围过滤；
  // 不给时只返回项目共享单元（资料页使用）
  Y7.queries.register('semantic.records', (params) => {
    if (!Y7.atLeast('s4')) return null;
    const projectId = params.projectId || Y7.state.projectId;
    const department = params.department || null;
    const privateScope = department ? Y7.deptLabel(department) + '私有' : null;
    const records = Y7.resolve(Y7.data.semantic)[projectId];
    if (!records) return { department, units: [], privateCount: 0, conflicts: [], dataflow: [], chains: [] };
    const units = records.units.map((unit) => {
      const item = unit.workItemId ? Y7.workItem(unit.workItemId) : null;
      return Object.assign({}, unit, { workItemTitle: item ? item.title : null });
    });
    const byId = {};
    units.forEach((unit) => { byId[unit.id] = unit; });
    const need = (id) => {
      if (!byId[id]) throw new Error('语义记录引用的单元不存在：' + id);
      return byId[id];
    };
    const inScope = (unit) => unit.scope === '项目共享' || (privateScope !== null && unit.scope === privateScope);
    // 更替链：从没有被别的单元指向的最旧单元开始，沿 supersededBy 走到最新的单元；只保留范围内的单元，少于两个时不成链
    const chains = units.filter((unit) => unit.supersededBy && !units.some((other) => other.supersededBy === unit.id)).map((start) => {
      const steps = [start];
      let current = start;
      while (current.supersededBy) {
        current = need(current.supersededBy);
        steps.push(current);
      }
      return steps.filter(inScope);
    }).filter((steps) => steps.length >= 2);
    const visible = units.filter(inScope);
    return {
      department,
      units: visible,
      privateCount: units.filter((unit) => unit.scope !== '项目共享' && !inScope(unit)).length,
      conflicts: records.conflicts.map((c) => ({ a: need(c.a), b: need(c.b), text: c.text })).filter((c) => inScope(c.a) && inScope(c.b)),
      dataflow: records.dataflow,
      chains
    };
  });

  // ---------------------------------------------------------------------------
  // 各部分

  function viewButton(material, label) {
    return ui.button({ label: label || '查看原文', kind: 'small', act: 'mt.view', data: { materialId: material.id } });
  }

  function indexBlock(m) {
    const cards = m.items.map((entry) => {
      const c = entry.counts;
      const total = Object.keys(c).reduce((sum, kind) => sum + c[kind], 0);
      return '<article class="y7-mt-index-card" style="--item:' + kit.itemColor(entry.item.colorIndex) + '">' +
        '<button type="button" class="y7-pp-title" data-go="' + esc(Y7.paths.materials(m.project.id, entry.item.id)) + '">' + esc(entry.item.title) + '</button>' +
        ui.status(entry.display.kind, entry.display.text) +
        '<p class="y7-mt-counts">' + Object.keys(KIND_LABELS).map((kind) => '<span' + (c[kind] ? '' : ' class="is-zero"') + '>' + esc(KIND_LABELS[kind]) + ' ' + c[kind] + '</span>').join('') + '</p>' +
        (total ? '' : '<p class="y7-small y7-muted">还没有资料</p>') + '</article>';
    }).join('');
    return ui.block({
      title: '按事项查看', level: 'now', query: 'work_item.materials',
      subtitle: '资料按事项保存；点击事项，或在顶栏选择事项，查看它的 intend、PRD、PLAN、交付与质检',
      body: m.items.length ? '<div class="y7-mt-index">' + cards + '</div>' : ui.empty('项目还没有事项')
    });
  }

  function switcher(m) {
    return '<nav class="y7-mt-switch" aria-label="切换事项">' + m.items.map((entry) =>
      '<button type="button" class="y7-pp-chip' + (entry.item.id === m.workItem.id ? ' is-on' : '') + '" data-go="' + esc(Y7.paths.materials(m.project.id, entry.item.id)) + '">' +
      kit.swatch(entry.item.colorIndex) + esc(entry.item.title) + '</button>').join('') + '</nav>';
  }

  function intendBlock(m) {
    const body = m.intend.length
      ? '<ol class="y7-mt-list">' + m.intend.map((doc) => '<li class="y7-mt-doc">' +
        '<header class="y7-mt-doc-head"><strong>' + esc(doc.title) + '</strong>' + ui.tag(doc.version === 1 ? '首次输入' : '第 ' + doc.version + ' 次输入') +
        '<span class="y7-muted">' + esc(kit.fullTime(doc.at)) + ' 接收</span>' + (doc.bytes ? '<span class="y7-muted y7-pp-mono">' + esc(kit.bytes(doc.bytes)) + '</span>' : '') + '</header>' +
        '<blockquote class="y7-mt-quote">' + esc(doc.text) + '</blockquote></li>').join('') + '</ol>'
      : ui.empty('这个事项还没有 intend 原文');
    return ui.block({ title: 'intend 原文', level: 'now', query: 'work_item.materials', subtitle: 'intend.md 按接收顺序追加保存用户原文；每个版本对应一段字节范围', body });
  }

  function prdBlock(m) {
    const latest = m.prd.length ? m.prd[m.prd.length - 1] : null;
    const body = m.prd.length
      ? '<ol class="y7-mt-list">' + m.prd.slice().reverse().map((doc) => {
        const next = m.prd.find((other) => other.version === doc.version + 1);
        return '<li class="y7-mt-doc' + (doc === latest ? ' is-current' : ' is-old') + '"><header class="y7-mt-doc-head"><strong>' + esc(doc.title) + '</strong>' +
          (doc === latest ? '<span class="y7-mt-badge is-current">当前有效</span>' : '<span class="y7-mt-badge">已被 ' + esc(next ? next.title : '新版本') + ' 取代</span>') +
          '<span class="y7-muted">' + esc(ui.time(doc.at)) + '</span></header>' +
          ui.kv([['接纳来源', esc(doc.acceptedFrom || '')]], 'is-rows') +
          '<div class="y7-row">' + viewButton(doc, '查看 PRD 原文') + '</div></li>';
      }).join('') + '</ol>'
      : ui.empty('产品部门还没有提交 PRD');
    return ui.block({ title: 'PRD', level: 'now', query: 'work_item.materials', subtitle: '产品部门提交并被接纳的各版本', body });
  }

  function planBlock(m) {
    const latest = m.plan.length ? m.plan[m.plan.length - 1] : null;
    const body = m.plan.length
      ? '<ol class="y7-mt-list">' + m.plan.slice().reverse().map((doc) => '<li class="y7-mt-doc' + (doc === latest ? ' is-current' : ' is-old') + '"><header class="y7-mt-doc-head"><strong>' + esc(doc.title) + '</strong>' +
        (doc === latest ? '<span class="y7-mt-badge is-current">当前计划</span>' : '') + '<span class="y7-muted">' + esc(ui.time(doc.at)) + '</span></header>' +
        ui.kv([['目标', esc(doc.goal || '')]], 'is-rows') + '<div class="y7-row">' + viewButton(doc, '查看 PLAN 原文') + '</div></li>').join('') + '</ol>'
      : ui.empty('工程部门还没有提交计划');
    return ui.block({ title: 'PLAN', level: 'now', query: 'work_item.materials', subtitle: '工程部门的计划各版本', body });
  }

  function verdictChip(verdict) {
    if (!(verdict in VERDICTS)) throw new Error('未知的质检结论：' + verdict);
    return verdict === 'release' ? kit.outcome('release', VERDICTS.release) : kit.flowKind('rework', VERDICTS[verdict]);
  }

  function deliveryBlock(m) {
    const latest = m.delivery.length ? m.delivery[m.delivery.length - 1] : null;
    const item = m.workItem;
    const body = m.delivery.length
      ? '<ol class="y7-mt-list">' + m.delivery.slice().reverse().map((doc) => {
        const qa = m.qa.find((q) => q.version === doc.version);
        const marks = [];
        if (qa) marks.push(verdictChip(qa.verdict));
        if (doc === latest && m.adoption) marks.push(kit.outcome('adopt', '项目采纳为 ' + m.adoption.version));
        if (doc === latest && item.status === 'held') marks.push(ui.status('held', Y7.atLeast('s3') ? '未采纳候选' : '基线已变'));
        const files = (doc.files || []).length
          ? '<ul class="y7-mt-files" aria-label="文件清单">' + doc.files.map((f) => '<li>' + ui.code(f.path) + '<span class="y7-muted">' + esc(ui.num(f.bytes)) + ' 字节</span>' +
            ui.button({ label: '下载', kind: 'small', act: 'mt.download', data: { materialId: doc.id, path: f.path } }) + '</li>').join('') + '</ul>'
          : ui.empty('交付没有文件');
        const git = doc.git
          ? '<p class="y7-mt-git">Git 提交 ' + ui.code(doc.git.commit) + ' · ' + (doc.git.parent ? '父提交 ' + ui.code(doc.git.parent) : '初始版本') + ' · ' + esc(doc.git.stat) + '</p>'
          : '';
        return '<li class="y7-mt-doc' + (doc === latest ? ' is-current' : ' is-old') + '"><header class="y7-mt-doc-head"><strong>' + esc(doc.title) + '</strong>' + marks.join('') +
          '<span class="y7-muted">' + esc(ui.time(doc.at)) + ' 封存</span></header>' +
          '<p>' + esc(doc.summary || doc.text) + '</p>' + git + files +
          '<div class="y7-row">' + (doc.diff ? ui.button({ label: '查看 Git 差异', kind: 'small', act: 'mt.diff', data: { materialId: doc.id } }) : '') +
          ui.button({ label: '下载封存清单', kind: 'small', act: 'mt.manifest', data: { materialId: doc.id } }) + viewButton(doc, '查看交付说明') + '</div></li>';
      }).join('') + '</ol>'
      : ui.empty('工程部门还没有封存交付');
    return ui.block({ title: '交付', level: 'now', query: 'work_item.materials', subtitle: '各版本的封存快照：文件清单、摘要、Git 差异与文件下载；标记为同版本的质检结论与项目采纳', body });
  }

  function qaBlock(m) {
    const body = m.qa.length
      ? '<ol class="y7-mt-list">' + m.qa.slice().reverse().map((doc) => '<li class="y7-mt-doc' + (doc.verdict === 'release' ? ' is-release' : ' is-rework') + '">' +
        '<header class="y7-mt-doc-head"><strong>' + esc(doc.title) + '</strong>' + verdictChip(doc.verdict) + '<span class="y7-muted">' + esc(ui.time(doc.at)) + '</span></header>' +
        ui.kv([['理由', esc(doc.text)]], 'is-rows') +
        (doc.checks && doc.checks.length ? '<ul class="y7-mt-checks">' + doc.checks.map((check) => '<li class="' + (check.ok ? 'is-ok' : 'is-fail') + '">' +
          ui.icon(check.ok ? 'succeeded' : 'failed') + '<span>' + esc(check.label) + '</span><small>' + (check.ok ? '通过' : '未通过') + '</small></li>').join('') + '</ul>' : '') +
        '<h4 class="y7-pp-sub">检查回执</h4>' +
        (doc.receiptActions.length ? '<ul class="y7-mt-receipts">' + doc.receiptActions.map((action) => '<li>' + ui.code(action.id) + kit.receiptOutcome(action) + '<span>' + esc(action.summary) + '</span>' +
          (action.receipt && action.receipt.snapshot ? '<small class="y7-muted">快照 ' + esc(action.receipt.snapshot) + '</small>' : '') + '</li>').join('') + '</ul>'
          : '<p class="y7-small y7-muted">这次结论没有引用主机回执</p>') + '</li>').join('') + '</ol>'
      : ui.empty('质检部门还没有给出结论');
    return ui.block({ title: '质检', level: 'now', query: ['work_item.materials', 'run.actions'], subtitle: '质检结论、理由与检查回执；放行引用质检部门自己的主机回执', body });
  }

  function notesBlock(m) {
    const body = m.notes.length
      ? '<ul class="y7-mt-notes">' + m.notes.map((note) => '<li><header class="y7-mt-doc-head"><strong>' + esc(note.department ? Y7.deptLabel(note.department) + '部门' : '项目') + '</strong><span class="y7-muted">' + esc(kit.fullTime(note.at)) + ' 记录</span></header>' +
        '<blockquote class="y7-mt-quote">' + esc(note.text) + '</blockquote></li>').join('') + '</ul>'
      : ui.empty('还没有记录原文');
    return ui.block({
      title: '项目材料', level: 'now', query: 'work_item.materials',
      subtitle: '「记录原文」保存的材料（项目或某部门）；项目材料只记录原文，不注入后续事项。已记录原文 ' + m.notes.length + ' 条',
      body
    });
  }

  // ---------------------------------------------------------------------------
  // 语义记录（Stage 4）

  function unitState(unit) {
    if (!(unit.status in UNIT_STATES)) throw new Error('未知的语义单元状态：' + unit.status);
    return '<span class="y7-msem-state is-' + esc(unit.status) + '">' + esc(UNIT_STATES[unit.status]) + '</span>';
  }

  function unitNote(unit) {
    if (unit.status === 'superseded') return '已被 ' + unit.supersededBy + ' 取代' + (unit.reason ? '，' + unit.reason : '');
    if (unit.status === 'invalid') return '已失效，' + ui.time(unit.at) + (unit.reason ? '，' + unit.reason : '');
    return '';
  }

  function unitRow(unit) {
    const note = unitNote(unit);
    return '<li class="y7-msem-unit is-' + esc(unit.status) + '">' +
      '<span class="y7-msem-id">' + ui.code(unit.id) + '</span>' +
      '<span class="y7-msem-text">' + esc(unit.text) + '</span>' +
      '<span class="y7-msem-flags">' + unitState(unit) + (unit.fromHeld ? ui.tag('来自未采纳事项') : '') + '</span>' +
      '<span class="y7-msem-meta">来源 ' + ui.code(unit.source) + (unit.workItemTitle ? ' · 事项「' + esc(unit.workItemTitle) + '」' : '') + ' · ' + esc(ui.time(unit.at)) + (note ? ' · ' + esc(note) : '') + '</span></li>';
  }

  function semanticBlock(ctx) {
    if (!Y7.atLeast('s4')) return '';
    const s = Y7.query('semantic.records', { projectId: ctx.project.id });
    const item = ctx.workItem;
    let units = s.units.filter((unit) => view.showAll || unit.status === 'valid' || unit.status === 'conflict');
    if (item && view.onlyItem) units = units.filter((unit) => unit.workItemId === item.id);
    const types = UNIT_TYPES.concat(Array.from(new Set(units.map((u) => u.type))).filter((t) => !UNIT_TYPES.includes(t)));
    const groups = types.map((type) => {
      const list = units.filter((unit) => unit.type === type);
      if (!list.length) return '';
      return '<section class="y7-msem-group"><h4>' + esc(type) + '<span class="y7-count">' + list.length + '</span></h4><ul class="y7-msem-units">' + list.map(unitRow).join('') + '</ul></section>';
    }).join('');
    const controls = '<div class="y7-msem-controls">' +
      '<label class="y7-pp-check"><input type="checkbox" data-act="mt.semAll"' + (view.showAll ? ' checked' : '') + '><span>显示已取代与已失效的单元</span></label>' +
      (item ? '<label class="y7-pp-check"><input type="checkbox" data-act="mt.semItem"' + (view.onlyItem ? ' checked' : '') + '><span>只看「' + esc(item.title) + '」的单元</span></label>' : '') +
      '<span class="y7-small y7-muted">部门私有的单元 ' + s.privateCount + ' 条，在部门工作间的语义面板查看</span></div>';
    const chains = s.chains.length
      ? '<ol class="y7-msem-chains">' + s.chains.map((steps) => '<li><ol class="y7-msem-chain">' + steps.map((unit, i) => {
        const prev = i > 0 ? steps[i - 1] : null;
        return (prev ? '<li class="y7-msem-link"><span class="y7-msem-down" aria-hidden="true">↓</span><small>' + esc(ui.time(unit.at)) + ' 取代' + (prev.reason ? ' · 原因：' + esc(prev.reason) : '') + '</small></li>' : '') +
          '<li class="y7-msem-step is-' + esc(unit.status) + '">' + ui.code(unit.id) + unitState(unit) + '<small class="y7-muted">' + esc(ui.time(unit.at)) + '</small><p>' + esc(unit.text) + '</p></li>';
      }).join('') + '</ol></li>').join('') + '</ol>'
      : ui.empty('没有更替链');
    const conflicts = s.conflicts.length
      ? s.conflicts.map((c) => '<div class="y7-msem-conflict"><div class="y7-msem-pair">' +
        '<div class="y7-msem-side">' + ui.code(c.a.id) + '<p>' + esc(c.a.text) + '</p></div><span class="y7-msem-vs" aria-label="冲突">↔</span>' +
        '<div class="y7-msem-side">' + ui.code(c.b.id) + '<p>' + esc(c.b.text) + '</p></div></div><p class="y7-msem-why"><b>矛盾之处</b>' + esc(c.text) + '</p></div>').join('')
      : ui.empty('没有冲突');
    const passed = s.dataflow.filter((d) => d.ok).length;
    const dataflow = '<p class="y7-small y7-msem-df-sum">通过 <strong>' + passed + '</strong> / ' + s.dataflow.length + ' 项</p><ol class="y7-msem-df">' + s.dataflow.map((d) => '<li class="' + (d.ok ? 'is-ok' : 'is-fail') + '">' +
      ui.icon(d.ok ? 'succeeded' : 'failed') + '<span class="y7-pp-mono">' + esc(d.id) + '</span><span>' + esc(d.label) + '</span>' +
      (d.missing.length ? '<span class="y7-msem-missing">缺失：' + d.missing.map((id) => ui.code(id)).join('') + '</span>' : '<span class="y7-msem-missing is-none">没有缺失</span>') + '</li>').join('') + '</ol>';
    const body = controls +
      '<h3 class="y7-h3">有效要求集合</h3>' + (groups || ui.empty('没有符合条件的单元')) +
      '<div class="y7-grid-2 y7-msem-grid"><section><h3 class="y7-h3">更替链（从旧到新）</h3>' + chains + '</section>' +
      '<section><h3 class="y7-h3">冲突</h3>' + conflicts + '</section></div>' +
      '<h3 class="y7-h3">数据流核对</h3>' + dataflow;
    return ui.block({
      title: '语义记录', tag: 'Stage 4', level: 's4', query: 'semantic.records',
      subtitle: '项目共享的语义单元由事件投影得到：每个单元有编号、类型、来源事件与有效状态；已采纳事项的单元进入之后事项的语义视图',
      body
    });
  }

  // ---------------------------------------------------------------------------
  // 页面

  Y7.views.register('materials', {
    title: () => '资料',
    render(ctx) {
      const m = Y7.query('work_item.materials', { projectId: ctx.project.id, workItemId: ctx.workItem ? ctx.workItem.id : null });
      const head = kit.pageHead('资料 · 只读', ctx.workItem ? ctx.workItem.title : '资料',
        ctx.workItem
          ? ui.status(m.display.kind, m.display.text) + ' ' + esc(ctx.project.name) + ' · 按事项查看的资料全部只读'
          : esc(ctx.project.name) + ' · intend、PRD、PLAN、交付与质检按事项查看，全部只读');
      const itemParts = ctx.workItem
        ? switcher(m) + intendBlock(m) + '<div class="y7-grid-2">' + prdBlock(m) + planBlock(m) + '</div>' + deliveryBlock(m) + qaBlock(m)
        : indexBlock(m);
      return '<div class="y7-pp y7-mt">' + head + itemParts + notesBlock(m) + semanticBlock(ctx) + '</div>';
    }
  });

  // ---------------------------------------------------------------------------
  // 界面动作

  function material(id) {
    const found = Y7.resolve(Y7.data.materials).find((m) => m.id === id);
    if (!found) throw new Error('找不到资料：' + id);
    return found;
  }

  Y7.actions.register('mt.view', (el) => {
    const doc = material(el.dataset.materialId);
    ui.modal({ title: doc.title + ' 原文', wide: true, body: ui.pre(doc.text), actions: [{ label: '关闭', close: true }] });
  });

  Y7.actions.register('mt.diff', (el) => {
    const doc = material(el.dataset.materialId);
    ui.modal({
      title: doc.title + ' · Git 差异', wide: true,
      body: ui.kv([
        ['提交', ui.code(doc.git.commit)],
        ['父提交', doc.git.parent ? ui.code(doc.git.parent) : '初始版本'],
        ['文件变化', esc(doc.git.stat)]
      ]) + '<pre class="y7-pre y7-mt-diff">' + doc.diff.split('\n').map((line) => {
        const cls = line.startsWith('+') ? 'is-add' : line.startsWith('-') ? 'is-del' : line.startsWith('@@') ? 'is-hunk' : '';
        return '<span class="' + cls + '">' + esc(line) + '</span>';
      }).join('\n') + '</pre>',
      actions: [{ label: '关闭', close: true }]
    });
  });

  Y7.actions.register('mt.download', (el) => {
    const doc = material(el.dataset.materialId);
    const file = (doc.files || []).find((f) => f.path === el.dataset.path);
    if (!file) throw new Error('交付中找不到文件：' + el.dataset.path);
    ui.toast('下载 ' + file.path + '（' + ui.num(file.bytes) + ' 字节，来自' + doc.title + '）：原型示例数据不含文件内容，真实界面从交付封存工件下载', 'warn');
  });

  // 封存清单：交付的提交、父提交与文件清单，内容全部来自示例数据
  Y7.actions.register('mt.manifest', (el) => {
    const doc = material(el.dataset.materialId);
    const manifest = { delivery: doc.title, workItemId: doc.workItemId, sealedAt: doc.at, git: doc.git || null, files: doc.files || [] };
    const url = URL.createObjectURL(new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = doc.workItemId + '-' + doc.title.replace(/\s+/g, '-') + '-manifest.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });

  Y7.actions.register('mt.semAll', (el) => {
    view.showAll = el.checked;
    Y7.renderContent(true);
  });

  Y7.actions.register('mt.semItem', (el) => {
    view.onlyItem = el.checked;
    Y7.renderContent(true);
  });
})();
