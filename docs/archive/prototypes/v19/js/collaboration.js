// 工作页的常驻协作视图：从组织关系和运行事实生成，选中部门即可指导。
(function () {
  'use strict';
  const Y = window.Y19, O = Y.org, H = Y.h, esc = Y.esc;
  const state = (p) => Y.thread.state(p);
  const definition = (p) => { const it = Y.thread.active(p); return it ? it.org.composed : p.composed; };
  const selected = (p) => {
    const c = definition(p), s = state(p), it = Y.thread.active(p);
    return c.depts.some((d) => d.id === s.focusDept) ? s.focusDept : (it && c.depts.some((d) => d.id === it.dept) ? it.dept : (O.firstReceivers(c)[0] || c.depts[0]).id);
  };
  const name = (c, id) => (c.depts.find((d) => d.id === id) || { name: id }).name;
  const unfinished = (it) => it && !['adopted', 'open_closed', 'stopped'].includes(it.status);
  function relations(c, d) {
    const lines = [];
    d.produces.forEach((kind) => {
      const targets = c.depts.filter((other) => other.id !== d.id && (other.watches.includes(kind) || other.verifies && other.verifies.dept === d.id && other.verifies.kind === kind)).map((other) => other.name);
      c.sources.filter((source) => source.id === kind && source.to !== d.id).forEach((source) => { const target = name(c, source.to); if (!targets.includes(target)) targets.push(target); });
      if (targets.length) lines.push(O.kindName(c, kind) + ' → ' + targets.join('、'));
    });
    if (d.verifies) lines.push('核验' + name(c, d.verifies.dept) + ' · 打回' + name(c, d.verifies.dept) + '返工');
    if (c.rotation === 'direct') {
      const maker = O.completer(c);
      if (maker && maker.id !== d.id && !d.verifies && !d.produces.length) lines.push('回应' + maker.name + '的询问');
      if (maker && maker.id === d.id && !lines.length) lines.push('主执行 · ' + (O.ending(c).open ? '交完成即结束' : '交完成后独立核验'));
    }
    return lines.length ? lines : [d.produces.length ? '产出' + d.produces.map((kind) => O.kindName(c, kind)).join('、') : '按职责协作'];
  }
  function departmentState(p, d) {
    const c = definition(p), s = state(p), it = Y.thread.active(p), raw = p.deptState[d.id] || {};
    const otherItems = (raw.items || []).map((id) => H.item(p, id)).filter((item) => unfinished(item) && (!it || item.id !== it.id));
    const question = s.msgs.find((m) => m.t === 'ask' && !m.answer && m.who === d.id && unfinished(H.item(p, m.item)) && (!it || m.item === it.id));
    const result = (label, tone, text, scope, reason) => ({ label, tone, text, scope, reason: reason || text, otherItems, waits: raw.waits || [] });
    if (question) return Object.assign(result('等你决定', 'attention', question.text, it ? '当前事项' : '其他事项'), { question });
    if (['interrupted', 'waiting_provider'].includes(raw.state)) return result(raw.state === 'interrupted' ? '已中断' : '等模型服务', 'attention', raw.text, (raw.items || []).includes(it && it.id) ? '当前事项' : '项目运行', raw.reason);
    if (c.rotation === 'pool' && it) {
      const units = p.workUnits || [], mine = units.filter((unit) => unit.owner === d.id && ['doing', 'review'].includes(unit.status));
      if (mine.length) return result(mine.some((unit) => unit.status === 'doing') ? '执行中' : '待单元核验', mine.some((unit) => unit.status === 'doing') ? 'running' : 'waiting', mine.map((unit) => unit.title).join('、'), '当前事项');
      if (d.verifies && units.length) {
        const reviewing = units.filter((unit) => unit.status === 'review').length;
        return result(units.every((unit) => unit.status === 'done') ? '待整份核验' : reviewing ? '待单元核验' : '等待交付', 'waiting', units.every((unit) => unit.status === 'done') ? '全部单元已通过，等待整份交付核验' : reviewing ? reviewing + ' 个单元等待核验，整份交付另行核验' : '等待工作单元完成后核验整份交付', '当前事项');
      }
      return result('可认领', 'idle', '按资格认领工作单元', '当前事项');
    }
    const ownsCurrent = it && (it.dept === d.id || s.phase && s.phase.state === 'verify' && O.verifiers(c).some((verifier) => verifier.id === d.id) || !it.ran && (raw.items || []).includes(it.id) && raw.state === 'running');
    if (ownsCurrent) {
      const verifying = s.phase && s.phase.state === 'verify' || d.verifies && d.verifies.kind === c.adopt;
      const latest = s.msgs.filter((m) => m.t === 'fold' && m.item === it.id).flatMap((m) => m.kids).filter((kid) => kid.who === d.id).slice(-1)[0];
      return result(verifying ? '核验中' : '执行中', 'running', it.title, '当前事项', it.ran ? (verifying ? '独立核验当前交付，放行后事项完成' : latest ? latest.text : '接到事项，准备开始工作') : raw.reason || raw.text);
    }
    if (otherItems.length) {
      const includesCurrent = it && (raw.items || []).includes(it.id), busy = includesCurrent ? otherItems.some((item) => item.status === 'working') : raw.state === 'running';
      return result(busy ? '执行中' : '等待中', busy ? 'running' : 'waiting', includesCurrent ? otherItems.map((item) => item.title).join('、') : raw.text, '其他事项', includesCurrent ? otherItems.map((item) => item.title + '：' + item.reason).join('；') : raw.reason);
    }
    if (it && it.ran && (raw.items || []).includes(it.id)) return result('等待中', 'waiting', '当前交给' + name(c, it.dept) + '处理', '当前事项');
    if (d.id === 'operations') return result(p.operations ? p.operations.health : '未接入环境', p.operations ? p.operations.health === '运行正常' ? 'running' : 'attention' : 'waiting', p.operations ? p.operations.version + ' · ' + p.operations.environment : '登记环境后查看运行状态', '运行环境', p.operations ? '已部署第 ' + p.operations.deployed + ' 版；部署与事项放行分别记录' : '运行环境与授权需要单独登记');
    if (raw.state === 'running') return result('执行中', 'running', raw.text, '项目运行', raw.reason);
    if (raw.state === 'waiting_work') return result('等待中', 'waiting', raw.text, '项目运行', raw.reason);
    return result('空闲', 'idle', d.verifies ? '等待需要核验的交付' : c.rotation === 'direct' && !d.completes ? '按需参与协助' : '等待相关输入或成果', '项目运行');
  }
  function context(p, c, d, status) {
    const s = state(p), it = Y.thread.active(p);
    const latest = s.msgs.filter((m) => m.t === 'you' && m.target === d.id && (!m.item || it && m.item === it.id)).slice(-1)[0];
    const asking = status.question;
    const internals = (p.deptState[d.id] || {}).inner || [];
    const inner = d.who.type === 'suborg' ? '<div class="ws-inner-status"><b>内部小组</b>' + (internals.length ? internals.map((r) => '<span title="' + esc(r.text) + '">' + esc(r.role) + ' · ' + esc({ running: '执行中', waiting_work: '等待中', idle: '空闲' }[r.state] || r.state) + '</span>').join('') : '<span>内部状态尚无记录</span>') + '<button type="button" class="y19-link" data-act="co.inner" data-dept="' + esc(d.id) + '">查看内部工作</button></div>' : '';
    return '<section class="ws-dept-context" aria-label="' + esc(d.name) + '当前工作"><div class="ws-context-heading"><strong>' + esc(d.name) + '</strong><span>' + esc(status.scope) + '</span></div><p>' + esc(status.reason) + '</p>' +
      (status.waits.length ? '<ul class="ws-waits">' + status.waits.map((wait) => '<li>' + esc((H.item(p, wait.item) || {}).title || wait.item) + '：等' + esc(wait.on) + '</li>').join('') + '</ul>' : '') +
      (status.otherItems.length ? '<p class="ws-related-items">另有 ' + status.otherItems.length + ' 项：' + esc(status.otherItems.map((item) => item.title).join('、')) + '</p>' : '') +
      (asking ? '<div class="ln-opts">' + asking.options.map((option) => '<button type="button" class="y19-btn small" data-act="ln.answer" data-i="' + s.msgs.indexOf(asking) + '" data-o="' + esc(option) + '">' + esc(option) + '</button>').join('') + '</div>' : '') + inner +
      (latest ? '<div class="ws-guidance-receipt"><small>' + (latest.readAt ? '指导已读取' : '指导已记录 · 等待下一轮读取') + '</small><p>' + esc(latest.text) + '</p></div>' : '') +
      '<div class="ws-context-actions"><button type="button" class="y19-btn small" data-act="co.guide" data-dept="' + esc(d.id) + '">指导' + esc(d.name) + '</button><button type="button" class="y19-link" data-act="co.messages" data-dept="' + esc(d.id) + '">查看往来</button><button type="button" class="y19-link" data-go="#/p/' + p.id + '/org/d/' + esc(d.id) + '">配置</button></div></section>';
  }
  function render(p) {
    const c = definition(p);
    if (c.depts.length < 2) return '';
    const it = Y.thread.active(p), chosen = selected(p), d = c.depts.find((dept) => dept.id === chosen), first = O.firstReceivers(c)[0];
    const source = c.sources.find((entry) => it && entry.id === it.source) || c.sources.find((entry) => entry.id === 'input' || entry.id === 'task');
    const mode = c.rotation === 'direct' ? (O.completer(c) || first).name + '主执行 · 按需协助' : c.rotation === 'pool' ? '按资格认领 · 依赖就绪后开工' : '成果就绪后，关注它的部门开工';
    const ending = O.ending(c), verifiers = O.verifiers(c).map((v) => v.name).join('、');
    return '<div class="ws-collab-heading"><h2>协作状态</h2><span>' + esc(O.ROTATIONS[c.rotation]) + '</span></div><p class="ws-collab-mode">' + esc(mode) + '</p>' +
      '<div class="ws-current-item"><small>' + (it ? '当前事项' : '当前没有进行中的事项') + '</small>' + (it ? '<strong>' + esc(it.title) + '</strong>' : '') + (it && it.org.version !== p.version ? '<span>沿用开始时的组织</span>' : '') + '</div>' +
      '<p class="ws-collab-source">' + esc((source ? source.name + ' → ' + name(c, source.to) : '输入未指定接收方') + (ending.open ? ' · 开环完成' : ' · ' + verifiers + '放行后完成')) + '</p>' +
      (c.rotation === 'pool' && Y.pool ? Y.pool.summary(p) : '') +
      '<div class="ws-dept-list" aria-label="点选部门查看状态并指导">' + c.depts.map((dept) => {
        const status = departmentState(p, dept), lines = relations(c, dept);
        return '<button type="button" class="ws-dept-node' + (dept.id === chosen ? ' is-selected' : '') + '" data-act="co.select" data-dept="' + esc(dept.id) + '" aria-pressed="' + (dept.id === chosen) + '" aria-controls="co-context"><span class="ws-node-heading"><strong>' + esc(dept.name) + (dept.who.type === 'suborg' ? '<small>内部小组</small>' : '') + '</strong><span class="ws-status is-' + status.tone + '">' + esc(status.label) + '</span></span><span class="ws-node-work">' + esc(status.scope + ' · ' + status.text) + '</span><span class="ws-node-flow">' + lines.map(esc).join('<br>') + '</span></button>';
      }).join('') + '</div><div id="co-context">' + context(p, c, d, departmentState(p, d)) + '</div>' +
      (c.depts.some((dept) => dept.id === 'operations') ? '<button type="button" class="y19-link ws-operations-link" data-act="ops.open">运行环境与部署 · 设计预览</button>' : '') + '<p class="ws-collab-footnote">点选部门即可指导 · 状态随工作更新</p>';
  }
  function choose(p, id, focus) {
    if (!definition(p).depts.some((d) => d.id === id)) return;
    const s = state(p); s.focusDept = id; s.to = 'g:' + id; s.manual = true;
    Y.thread.refresh(p);
    if (focus) document.getElementById('ln-text').focus();
    else Array.from(document.querySelectorAll('[data-act="co.select"]')).find((el) => el.dataset.dept === id).focus({ preventScroll: true });
  }
  Y.actions.register('co.select', (el) => choose(H.project(H.pid()), el.dataset.dept, false));
  Y.actions.register('co.guide', (el) => choose(H.project(H.pid()), el.dataset.dept, true));
  Y.actions.register('co.inner', (el) => {
    const p = H.project(H.pid()), c = definition(p), d = c.depts.find((dept) => dept.id === el.dataset.dept), rows = (p.deptState[d.id] || {}).inner || [];
    Y.ui.modal({ title: d.name + ' › 内部工作', body: '<p class="y19-muted">当前事项沿用开始时的组织，内部完成后向外层交回提案。</p><div class="ws-log">' + (rows.map((row) => '<div><strong>' + esc(row.role) + '</strong><p>' + esc(row.text) + '</p><small>' + esc(row.child) + '</small></div>').join('') || '<p>内部状态尚无记录。</p>') + '</div>', actions: [{ label: '返回工作页', close: true }] });
  });
  Y.actions.register('co.messages', (el) => {
    const p = H.project(H.pid()), s = state(p), it = Y.thread.active(p);
    const messages = s.msgs.filter((m) => m.t === 'fold' && m.roles.includes(el.dataset.dept) && (!it || m.item === it.id));
    if (!messages.length) { Y.ui.toast('该部门在当前对话中还没有往来记录', 'info'); return; }
    const latest = messages[messages.length - 1]; latest.open = true; s.only = false;
    s.openItems = s.openItems || {}; s.openItems[latest.item] = true;
    Y.thread.refresh(p);
    document.getElementById('ln-fold-' + s.msgs.indexOf(latest)).scrollIntoView({ block: 'nearest' });
  });
  const guidanceItem = (p, id) => {
    const it = Y.thread.active(p), d = definition(p).depts.find((dept) => dept.id === id);
    return it && d && departmentState(p, d).scope === '当前事项' ? it : null;
  };
  Y.collaboration = { render, selected, departmentState, relations, guidanceItem };
})();
