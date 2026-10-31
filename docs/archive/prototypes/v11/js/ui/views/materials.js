// 资料（设计说明第 7.3 节）：按事项只读查看 intend、PRD、PLAN、交付、质检、项目材料、结构说明与旧版本的 run
(function () {
  'use strict';
  const Y11 = window.Y11;
  const esc = Y11.esc;

  const DEPT_LABEL = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const VERDICT = {
    release: { cls: 'is-release', kind: 'released', label: '放行' },
    rework_engineering: { cls: 'is-rework', kind: 'failed', label: '退回工程' }
  };
  const PHASE = {
    PRODUCT_SPEC: '产品规格', ENGINEERING: '工程实现', DELIVERY: '交付', QUALITY: '质检',
    REWORK_PRODUCT: '返工到产品', REWORK_ENGINEERING: '返工到工程',
    DONE: '已完成', PAUSED: '已暂停', FAILED: '已失败', QUEUED: '排队中'
  };

  function materials(pid, workItemId) {
    const params = { project: pid };
    if (workItemId) params.work_item = workItemId;
    return Y11.api.query('work_item.materials', params).data;
  }

  function fullTime(iso) {
    return Y11.ui.time(iso);
  }

  function viewButton(material, label) {
    return Y11.ui.button({ label: label || '查看原文', kind: 'small', act: 'mt.view', data: { materialId: material.id } });
  }

  // 试用截图：数据里存文件名（BUILD.md 第 8.5 节），页面上放在 assets/ 下
  function shotSrc(path) {
    return 'assets/' + path;
  }

  function docHead(doc, extra) {
    const version = Y11.ui.tag('v' + doc.version);
    const confirmed = doc.confirmation
      ? Y11.ui.tag('已确认：' + doc.confirmation.label)
      : (doc.initial ? Y11.ui.tag('等待确认') : '');
    return '<header class="y11-mt-doc-head"><strong>' + esc(doc.title) + '</strong>' + version + confirmed +
      (doc.accepted_from ? '<span class="y11-muted">接纳来源：' + esc(doc.accepted_from) + '</span>' : '') +
      '<span class="y11-muted">' + esc(fullTime(doc.at)) + '</span>' + (extra || '') + '</header>';
  }

  // ---------------------------------------------------------------------------
  // 索引与区块

  function indexBlock(m) {
    const cards = m.items.map((entry) => {
      const counts = entry.counts;
      const total = Object.keys(counts).reduce((sum, kind) => sum + counts[kind], 0);
      const label = { intend: 'intend', prd: 'PRD', plan: 'PLAN', delivery: '交付', qa: '质检', note: '材料' };
      const chips = Object.keys(counts).map((kind) =>
        '<span class="' + (counts[kind] ? '' : 'is-zero') + '">' + esc(label[kind]) + ' ' + counts[kind] + '</span>').join('');
      const current = m.work_item && m.work_item.id === entry.id;
      return '<article class="y11-mt-index-card' + (current ? ' is-current' : '') + '" style="--item:' + Y11.pixel.ITEM_COLORS[entry.color_index % 6] + '">' +
        '<button type="button" class="y11-pp-title" data-go="' + esc(Y11.paths.materials(m.project.id, entry.id)) + '">' + esc(entry.title) + '</button>' +
        '<div>' + Y11.ui.status(entry.display.kind, entry.display.text) + '</div>' +
        '<div class="y11-mt-counts">' + (total ? chips : '<span class="is-zero">还没有资料</span>') + '</div>' +
      '</article>';
    }).join('');
    return Y11.ui.block({
      id: 'mt-index', title: '按事项查看', query: 'work_item.materials',
      subtitle: '资料按事项保存；点击事项查看它的 intend、PRD、PLAN、交付、质检与项目材料',
      body: m.items.length ? '<div class="y11-mt-index">' + cards + '</div>' : Y11.ui.empty('项目还没有事项')
    });
  }

  function intendBlock(m) {
    if (!m.intend) return '';
    const body = m.intend.length
      ? '<ol class="y11-mt-list">' + m.intend.map((doc) => '<li class="y11-mt-doc">' +
        docHead(doc, Y11.ui.tag(doc.version === 1 ? '首次输入' : '第 ' + doc.version + ' 次输入')) +
        '<p class="y11-clamp">' + esc(doc.text) + '</p>' + viewButton(doc) + '</li>').join('') + '</ol>'
      : Y11.ui.empty('这个事项还没有 intend 原文');
    return Y11.ui.block({ id: 'mt-intend', title: 'intend 原文', query: 'work_item.materials', subtitle: '按接收顺序保存的用户原文', body });
  }

  function prdBlock(m) {
    if (!m.prd) return '';
    const latest = m.prd.length ? m.prd[m.prd.length - 1] : null;
    const body = m.prd.length
      ? '<ol class="y11-mt-list">' + m.prd.slice().reverse().map((doc) => '<li class="y11-mt-doc' + (doc === latest ? ' is-current' : ' is-old') + '">' +
        docHead(doc) + '<p class="y11-clamp">' + esc(doc.text) + '</p>' + viewButton(doc) + '</li>').join('') + '</ol>'
      : Y11.ui.empty('产品部门还没有提交 PRD');
    return Y11.ui.block({
      id: 'mt-prd', title: 'PRD', query: 'work_item.materials',
      subtitle: '产品部门提交并被接纳的各版本；接入已有项目的初始 PRD 标明确认记录', body
    });
  }

  function planBlock(m) {
    if (!m.plan) return '';
    const latest = m.plan.length ? m.plan[m.plan.length - 1] : null;
    const body = m.plan.length
      ? '<ol class="y11-mt-list">' + m.plan.slice().reverse().map((doc) => '<li class="y11-mt-doc' + (doc === latest ? ' is-current' : ' is-old') + '">' +
        docHead(doc, doc.goal ? Y11.ui.tag('目标：' + doc.goal) : '') + '<p class="y11-clamp">' + esc(doc.text) + '</p>' + viewButton(doc) + '</li>').join('') + '</ol>'
      : Y11.ui.empty('工程部门还没有提交计划');
    return Y11.ui.block({ id: 'mt-plan', title: 'PLAN', query: 'work_item.materials', subtitle: '工程部门的计划各版本', body });
  }

  function deliveryBlock(m) {
    if (!m.delivery) return '';
    const latest = m.delivery.length ? m.delivery[m.delivery.length - 1] : null;
    const body = m.delivery.length
      ? '<ol class="y11-mt-list">' + m.delivery.slice().reverse().map((doc) => {
        const files = (doc.files || []).map((file) => '<li><code class="y11-code">' + esc(file.path) + '</code>' +
          '<span class="y11-muted">' + esc(Y11.num(file.bytes)) + ' 字节</span>' +
          Y11.ui.button({ label: '下载', kind: 'small', act: 'mt.download', data: { materialId: doc.id, path: file.path } }) + '</li>').join('');
        const git = doc.git
          ? '<p class="y11-mt-git">' + Y11.ui.icon('link') + '提交 ' + Y11.ui.code(doc.git.commit) +
            (doc.git.parent ? ' <span class="y11-muted">父提交 ' + esc(doc.git.parent) + '</span>' : '') +
            ' <span class="y11-muted">' + esc(doc.git.stat || '') + '</span>' +
            Y11.ui.button({ label: 'Git 差异', kind: 'small', act: 'mt.diff', data: { materialId: doc.id } }) + '</p>'
          : '';
        return '<li class="y11-mt-doc' + (doc === latest ? ' is-current' : ' is-old') + '">' + docHead(doc) +
          (doc.summary ? '<p>' + esc(doc.summary) + '</p>' : '') +
          (files ? '<ul class="y11-mt-files">' + files + '</ul>' : '') + git + viewButton(doc, '查看交付说明') + '</li>';
      }).join('') + '</ol>'
      : Y11.ui.empty('工程部门还没有封存交付');
    return Y11.ui.block({
      id: 'mt-delivery', title: '交付', query: ['work_item.materials', 'delivery.file'],
      subtitle: '各版本的封存快照：文件清单、摘要、Git 差异与文件下载', body
    });
  }

  // 质检的逐条结论表（3.2D，#154）：每条验收条件一行；表头写交付快照的摘要与检验覆盖比例；开环的条件带「开环」标记
  const RESULT = { pass: ['succeeded', '通过'], fail: ['failed', '未通过'], not_run: ['idle', '没有运行'] };

  function criteriaTable(doc) {
    const methods = Y11.registry.CHECK_METHODS;
    const rows = doc.criteria;
    const counts = {
      covered: rows.filter((c) => methods[c.method].executable && c.result !== 'not_run').length,
      total: rows.length,
      model_read: rows.filter((c) => methods[c.method].model).length,
      open_count: rows.filter((c) => !methods[c.method].executable).length
    };
    const head = '<p class="y11-mt-criteria-head">交付快照 ' + Y11.ui.code(doc.snapshot || '—') + ' · ' + esc(Y11.coverageText(counts)) + '</p>';
    const table = Y11.ui.table({
      className: 'y11-mt-criteria',
      columns: [
        { label: '验收条件', render: (c) => '<strong>' + esc(c.criterion) + '</strong> ' + esc(c.text) + (methods[c.method].executable ? '' : ' ' + Y11.ui.tag('开环', 'open')) },
        { label: '检验方式', render: (c) => esc(methods[c.method].label) },
        { label: '结果', render: (c) => Y11.ui.status(RESULT[c.result][0], RESULT[c.result][1]) + (c.note ? '<small class="y11-muted y11-block-line">' + esc(c.note) + '</small>' : '') },
        { label: '证据', render: (c) => (c.checks || []).concat((c.trial_cases || []).map((t) => t.name)).map((s) => '<span class="y11-block-line">' + esc(s) + '</span>').join('') },
        {
          label: '截图', render: (c) => (c.trial_cases || []).filter((t) => t.screenshot).map((t) =>
            '<button type="button" class="y11-mt-shot is-thumb" data-act="mt.shot" data-path="' + esc(shotSrc(t.screenshot)) + '" data-title="' + esc(doc.title + ' · ' + c.criterion) + '">' +
            '<img src="' + esc(shotSrc(t.screenshot)) + '" alt="' + esc(c.criterion + ' 的截图') + '" loading="lazy"></button>').join('')
        }
      ],
      rows,
      rowAttrs: (c) => 'data-criterion="' + esc(c.criterion) + '"' + (methods[c.method].executable ? '' : ' data-open="1"')
    });
    return head + table;
  }

  function qaBlock(m) {
    if (!m.qa) return '';
    const body = m.qa.length
      ? '<ol class="y11-mt-list">' + m.qa.slice().reverse().map((doc) => {
        const verdict = VERDICT[doc.verdict];
        if (!verdict) throw new Error('未知的质检结论：' + doc.verdict);
        const checks = doc.criteria ? '' : (doc.checks || []).map((check) =>
          '<li class="' + (check.ok ? 'is-ok' : 'is-fail') + '">' + Y11.ui.icon(check.ok ? 'succeeded' : 'failed') +
          '<span>' + esc(check.label) + '</span><small class="y11-muted">' + (check.ok ? '通过' : '不通过') + '</small></li>').join('');
        const receipts = (doc.receipt_actions || []).map((action) =>
          '<li>' + Y11.ui.status(action.state === 'done' ? 'succeeded' : 'unknown', action.state === 'done' ? '已完成' : '结果未知') +
          Y11.ui.code(action.receipt && action.receipt.command ? action.receipt.command : action.id) +
          '<span>' + esc(action.summary || '') + '</span>' +
          (action.machine_id ? '<span class="y11-muted">机器 ' + esc(action.machine_id) + '</span>' : '') +
          (action.receipt ? '<span class="y11-muted">退出状态 ' + esc(action.receipt.exit_code) + '</span>' : '') + '</li>').join('');
        // 有逐条结论时截图在表里每一行的试用用例旁
        const shots = doc.criteria ? '' : (doc.screenshots || []).map((path) =>
          '<button type="button" class="y11-mt-shot" data-act="mt.shot" data-path="' + esc(shotSrc(path)) + '" data-title="' + esc(doc.title) + '">' +
          '<img src="' + esc(shotSrc(path)) + '" alt="' + esc(doc.title) + ' 的截图" loading="lazy"></button>').join('');
        return '<li class="y11-mt-doc ' + verdict.cls + '">' + docHead(doc, Y11.ui.status(verdict.kind, verdict.label)) +
          '<p>' + esc(doc.text) + '</p>' +
          (doc.criteria ? criteriaTable(doc) : '') +
          (checks ? '<ul class="y11-mt-checks">' + checks + '</ul>' : '') +
          (receipts ? '<div class="y11-pp-sub">检查回执</div><ul class="y11-mt-receipts">' + receipts + '</ul>' : '') +
          (shots ? '<div class="y11-pp-sub">试用截图</div><div class="y11-mt-shots">' + shots + '</div>' : '') + '</li>';
      }).join('') + '</ol>'
      : Y11.ui.empty('质检部门还没有给出结论');
    return Y11.ui.block({
      id: 'mt-qa', title: '质检', query: 'work_item.materials',
      subtitle: '结论、理由、检查回执；截图绑定到交付快照', body
    });
  }

  function notesBlock(m, item) {
    const body = m.notes.length
      ? '<ul class="y11-mt-notes">' + m.notes.map((note) =>
        '<li><header class="y11-mt-doc-head"><strong>' + esc(note.title) + '</strong>' +
        (note.department ? Y11.ui.tag(DEPT_LABEL[note.department] + '部门') : '') +
        '<span class="y11-muted">' + esc(fullTime(note.at)) + ' 记录</span></header>' +
        '<blockquote class="y11-mt-quote">' + esc(note.text) + '</blockquote></li>').join('') + '</ul>'
      : Y11.ui.empty(item ? '这个范围还没有项目材料' : '项目还没有记录原文');
    return Y11.ui.block({
      id: 'mt-notes', title: '项目材料', query: 'work_item.materials',
      subtitle: '「记录原文」保存的材料；项目材料只记录原文，不注入后续事项', body
    });
  }

  function structureBlock(m) {
    if (!m.structure || !m.structure.length) return '';
    const body = '<ol class="y11-mt-list">' + m.structure.map((doc) => '<li class="y11-mt-doc">' +
      docHead(doc, Y11.ui.tag('现有结构说明')) + '<p class="y11-clamp">' + esc(doc.text) + '</p>' + viewButton(doc) + '</li>').join('') + '</ol>';
    return Y11.ui.block({
      id: 'mt-structure', title: '结构说明', query: 'work_item.materials',
      subtitle: '接入已有项目时工程写出的现有结构说明', body
    });
  }

  function oldRunsBlock(m) {
    if (!m.old_runs || !m.old_runs.length) return '';
    const body = '<ol class="y11-mt-list">' + m.old_runs.map((run) => {
      if (!PHASE[run.phase]) throw new Error('未知的 run 阶段：' + run.phase);
      const events = run.events.length
        ? '<ul class="y11-mt-oldevents">' + run.events.map((ev) =>
          '<li><span class="y11-muted">' + esc(fullTime(ev.at)) + '</span>' + Y11.ui.code(ev.type) + '<span>' + esc(ev.label) + '</span></li>').join('') + '</ul>'
        : '<p class="y11-muted y11-small">没有记录的事件</p>';
      return '<li class="y11-mt-doc is-old">' +
        '<header class="y11-mt-doc-head"><strong>旧 run ' + esc(run.id) + '</strong>' + Y11.ui.tag('只读') + Y11.ui.tag('Yudao ' + run.yudao_version) +
        '<span class="y11-muted">' + esc(PHASE[run.phase]) + (run.stop_reason ? ' · ' + esc(run.stop_reason.text || run.stop_reason.code) : '') + '</span></header>' +
        events + '</li>';
    }).join('') + '</ol>';
    return Y11.ui.block({
      id: 'mt-oldruns', title: '旧版本的 run', query: 'work_item.materials',
      subtitle: 'Yudao 版本与当前部署的服务版本不同的 run，只读列出', body
    });
  }

  // ---------------------------------------------------------------------------
  // 页面

  function render(ctx) {
    const m = materials(ctx.projectId, ctx.workItemId);
    const head = ctx.workItemId
      ? '<header class="y11-pp-head"><h1>资料 · ' + esc(m.work_item.title) + '</h1>' +
        '<p class="y11-block-sub">' + esc(m.project.name) + ' · 按事项查看的资料全部只读</p></header>'
      : '<header class="y11-pp-head"><h1>资料</h1><p class="y11-block-sub">' + esc(m.project.name) + ' · 在顶栏选择事项以后查看这个事项的完整资料</p></header>';
    return '<div class="y11-pp y11-mt">' + head + indexBlock(m) +
      intendBlock(m) + prdBlock(m) + planBlock(m) + deliveryBlock(m) + qaBlock(m) +
      notesBlock(m, ctx.workItemId) + structureBlock(m) + oldRunsBlock(m) +
    '</div>';
  }

  function refresh(root, selector, html) {
    if (!html) return;
    const el = root.querySelector(selector);
    if (!el) return;
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const next = tmp.firstElementChild;
    if (next) el.replaceWith(next);
  }

  // 可能消失的区块：为空时换成同 id 的隐藏占位，之后还能重新出现
  function refreshOrHide(root, selector, html, id) {
    const el = root.querySelector(selector);
    if (!el) return;
    if (!html) {
      el.outerHTML = '<section id="' + id + '" hidden></section>';
      return;
    }
    refresh(root, selector, html);
  }

  function update(ctx, root) {
    const m = materials(ctx.projectId, ctx.workItemId);
    refresh(root, '#mt-index', indexBlock(m));
    refreshOrHide(root, '#mt-intend', intendBlock(m), 'mt-intend');
    refreshOrHide(root, '#mt-prd', prdBlock(m), 'mt-prd');
    refreshOrHide(root, '#mt-plan', planBlock(m), 'mt-plan');
    refreshOrHide(root, '#mt-delivery', deliveryBlock(m), 'mt-delivery');
    refreshOrHide(root, '#mt-qa', qaBlock(m), 'mt-qa');
    refresh(root, '#mt-notes', notesBlock(m, ctx.workItemId));
    refreshOrHide(root, '#mt-structure', structureBlock(m), 'mt-structure');
    refreshOrHide(root, '#mt-oldruns', oldRunsBlock(m), 'mt-oldruns');
  }

  Y11.views.register('materials', {
    title: () => '资料',
    needs: { queries: ['work_item.materials'] },
    render, update
  });

  // ---------------------------------------------------------------------------
  // 界面动作

  function currentMaterials() {
    const route = Y11.route();
    return materials(route.params.projectId, route.query.w || null);
  }

  function materialOf(materialId) {
    const data = currentMaterials();
    const lists = ['intend', 'prd', 'plan', 'delivery', 'qa', 'notes', 'structure'];
    const found = [];
    lists.forEach((key) => (data[key] || []).forEach((doc) => found.push(doc)));
    const doc = found.find((entry) => entry.id === materialId);
    if (!doc) throw new Error('找不到资料：' + materialId);
    return doc;
  }

  Y11.actions.register('mt.view', (el) => {
    const doc = materialOf(el.dataset.materialId);
    Y11.ui.modal({
      title: doc.title + ' 原文', wide: true,
      body: Y11.ui.pre(doc.text || ''),
      actions: [{ label: '关闭', close: true }]
    });
  });

  Y11.actions.register('mt.diff', (el) => {
    const doc = materialOf(el.dataset.materialId);
    if (!doc.git || !doc.diff) throw new Error('这份交付没有 Git 差异：' + doc.id);
    const lines = doc.diff.split('\n').map((line) => {
      const cls = line.startsWith('+') ? 'is-add' : line.startsWith('-') ? 'is-del' : line.startsWith('@@') ? 'is-hunk' : '';
      return '<span class="' + cls + '">' + esc(line) + '</span>';
    }).join('\n');
    Y11.ui.modal({
      title: doc.title + ' · Git 差异', wide: true,
      body: Y11.ui.kv([
        ['提交', Y11.ui.code(doc.git.commit)],
        ['父提交', doc.git.parent ? Y11.ui.code(doc.git.parent) : '初始版本'],
        ['文件变化', esc(doc.git.stat || '')]
      ]) + '<pre class="y11-pre y11-mt-diff">' + lines + '</pre>',
      actions: [{ label: '关闭', close: true }]
    });
  });

  Y11.actions.register('mt.download', (el) => {
    const data = Y11.api.query('delivery.file', { material_id: el.dataset.materialId, path: el.dataset.path }).data;
    const body = data.content === null
      ? Y11.ui.note('原型示例数据只保存文件清单，不含文件内容；真实界面从交付封存工件按摘要核对以后下载。', 'warn')
      : Y11.ui.pre(data.content);
    Y11.ui.modal({
      title: data.title + ' · ' + data.path, wide: true,
      body: Y11.ui.kv([['路径', Y11.ui.code(data.path)], ['字节', esc(Y11.num(data.bytes))]]) + body,
      actions: [{ label: '关闭', close: true }]
    });
  });

  Y11.actions.register('mt.shot', (el) => {
    Y11.ui.modal({
      title: el.dataset.title + ' · 试用截图', wide: true,
      body: '<figure class="y11-shot-modal"><img src="' + esc(el.dataset.path) + '" alt="' + esc(el.dataset.title) + ' 的截图"></figure>',
      actions: [{ label: '关闭', close: true }]
    });
  });
})();
