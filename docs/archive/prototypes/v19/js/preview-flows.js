// 静态原型中的运维与内部小组演示，不连接运行环境或模型服务。
(function () {
  'use strict';
  const Y = window.Y19, O = Y.org, H = Y.h, ui = Y.ui, esc = Y.esc, A = Y.actions.register;
  const project = () => H.project(H.pid());
  const opsState = (p) => p.operations || (p.operations = { version: '尚未部署', deployed: 0, health: '尚未登记', environment: '', permission: '', faults: [] });
  const note = (p, text) => Y.thread.state(p).msgs.push({ t: 'notice', text, at: Y.app.now() });
  function opsOpen() {
    const p = project(), o = opsState(p), versions = Y.thread.state(p).vers.filter((v) => v.concl === '放行' || v.concl.startsWith('放行 ·'));
    const source = p.composed.sources.find((s) => s.id === 'fault');
    ui.modal({ title: '运维 · 运行环境', wide: true, body: '<div class="ws-page" style="padding-bottom:0"><p class="ws-preview">设计预览 · 所有动作仅修改示例数据</p><section class="ws-summary"><h2>' + esc(o.environment || '尚未登记运行环境') + '</h2><div class="ws-ops-status"><strong>' + esc(o.health) + '</strong><span>部署版本：' + esc(o.version) + '</span></div><p>常设授权：' + esc(o.permission || '无') + '</p></section>' + (!o.environment ? '<p>新增运维部门后，需要单独登记演示环境及授权。</p><button type="button" class="y19-btn" data-act="ops.register">登记演示环境与授权</button>' : '') + '<section><h2>部署已放行的交付</h2><p>开发核验结论与部署记录分别保留。</p><select id="ops-version" class="y19-select" aria-label="选择已放行的版本">' + versions.map((v) => '<option value="' + v.n + '">第 ' + v.n + ' 版 · ' + esc(v.text) + '</option>').join('') + '</select><p><button type="button" class="y19-btn primary" data-act="ops.deploy"' + (!o.environment || !versions.length ? ' disabled' : '') + '>部署所选交付（演示）</button></p></section><section><h2>故障与修复事项</h2><p>' + esc(source ? '故障交给' + O.deptName(p, source.to) + '。已有事项进行中时，修复事项排在后面。' : '当前模板没有故障事项来源。可换用「按成果协作与运维」预览模板查看完整流程。') + '</p><p><button type="button" class="y19-btn" data-act="ops.fault"' + (!o.environment || !source ? ' disabled' : '') + '>模拟发现故障</button></p><div class="ws-log">' + (o.faults.map((f) => '<div><strong>' + esc(f.title) + '</strong><p>' + esc(f.state) + '</p></div>').join('') || '<p>没有故障记录</p>') + '</div></section><details class="ws-detail"><summary>授权之外的操作</summary><div class="ws-detail-body"><p>清理数据库不在常设授权范围内，需要用户决定。</p><button type="button" class="y19-btn" data-act="ops.request">演示授权请求</button></div></details></div>', actions: [{ label: '回到项目', close: true }] });
  }
  A('ops.open', opsOpen);
  A('ops.register', () => { const o = opsState(project()); o.environment = '演示运行环境'; o.permission = '读取日志、重启服务、部署已放行的交付'; o.health = '运行正常'; opsOpen(); });
  A('ops.deploy', () => {
    const p = project(), o = opsState(p), n = Number(document.getElementById('ops-version').value);
    const v = Y.thread.state(p).vers.find((v) => v.n === n && (v.concl === '放行' || v.concl.startsWith('放行 ·')));
    if (!o.environment || !v) { ui.toast('需要先登记环境，并选择已放行的交付', 'warn'); return; }
    o.version = '第 ' + n + ' 版'; o.deployed = n; o.health = '运行正常';
    o.faults.forEach((f) => { const it = p.items.find((i) => i.text === f.request); if (it && it.status === 'adopted' && v.item === it.id) f.state = '修复已放行并部署，等待持续观察'; });
    note(p, '运维已将第 ' + n + ' 版部署到' + o.environment + '（演示）。'); opsOpen(); Y.rerender();
  });
  A('ops.fault', () => {
    const p = project(), o = opsState(p), source = p.composed.sources.find((s) => s.id === 'fault');
    if (!source || !o.environment) return;
    const title = '导出接口出现错误 #' + (o.faults.length + 1), request = '修复运维故障：' + title + '。证据：演示运行环境出现 500 响应。';
    const ok = Y.thread.enqueue(p, request, 'fault');
    if (!ok) return;
    o.health = '发现故障'; o.faults.push({ title, request, state: '修复事项已提交 · 按项目组织处理，放行后可部署' });
    opsOpen(); Y.rerender();
  });
  A('ops.request', () => ui.modal({ title: '需要你决定 · 设计预览', body: '<p>运维申请在演示环境清理数据库，此动作超出常设授权。</p><p>本次决定仅适用于这条演示请求。</p>', actions: [{ label: '拒绝', act: 'ops.decide', data: { answer: '拒绝' } }, { label: '仅本次允许（演示）', act: 'ops.decide', data: { answer: '仅本次允许' }, kind: 'primary' }] }));
  A('ops.decide', (el) => { note(project(), '你对演示授权请求的决定：' + el.dataset.answer + '。常设授权范围保持原设置。'); ui.toast('已记录演示决定，未操作真实数据库', 'ok'); opsOpen(); });

  function internalOpen(path) {
    const p = project(), draft = O.draft.get(p.id), root = draft ? O.draftCompose(draft) : p.composed, ids = path.split('.'), c = O.nodeAt(root, ids);
    if (!c) return;
    p.internalThreads = p.internalThreads || {};
    const state = p.internalThreads[path] || { done: false };
    const parent = O.nodeAt(root, ids.slice(0, -1)).depts.find((d) => d.id === ids[ids.length - 1]);
    ui.modal({ title: parent.name + ' › 内部线程演示', wide: true, body: '<p class="ws-preview">使用本层定义的示例对话，未调用模型</p><p>本层结束条件：' + esc(O.ending(c).text) + '</p><div class="ws-log">' + c.depts.map((d) => '<div><strong>' + esc(d.name) + '</strong><p>' + esc(d.goal) + '</p></div>').join('') + '</div><p>' + (state.done ? '内部已完成，结果作为上层角色的提案返回；外层核验仍需单独通过。' : '内部角色按本层成果关系工作，完成后向上层交回。') + '</p><p>资源范围：从上层剩余预算中分配，不独立增加项目上限。</p>', actions: [{ label: state.done ? '已交回上层' : '演示内部核验并交回', act: 'ws.inner-complete', data: { path }, kind: 'primary', disabled: state.done }, { label: '返回内部组织', close: true }] });
  }
  A('ws.inner', (el) => internalOpen(el.dataset.path));
  A('ws.inner-complete', (el) => { const p = project(); if ((p.internalThreads[el.dataset.path] || {}).done) return; p.internalThreads[el.dataset.path] = { done: true }; note(p, '内部小组完成演示，已交回上层角色的提案；外层事项的核验结论另行产生。'); internalOpen(el.dataset.path); });
})();
