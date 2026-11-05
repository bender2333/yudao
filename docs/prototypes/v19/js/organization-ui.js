// 简洁的组织与角色页面。草稿、结构校验与采用仍使用 org.js 的同一份定义。
(function () {
  'use strict';
  const Y = window.Y19, O = Y.org, H = Y.h, ui = Y.ui, esc = Y.esc;
  const A = Y.actions.register, clone = (x) => JSON.parse(JSON.stringify(x));
  const project = () => H.project(H.pid());
  const pathOf = (r) => r.params.path ? r.params.path.split('.') : [];
  const url = (p, path, tail) => '#/p/' + p.id + '/org' + (path.length ? '/s/' + path.join('.') : '') + (tail || '');
  const button = (text, act, data, kind) => ui.button({ label: text, act, data, kind });
  const link = (text, go) => ui.button({ label: text, go, kind: 'small' });
  const field = (label, control) => '<label class="y19-field"><span>' + esc(label) + '</span>' + control + '</label>';
  const details = (title, body, open) => '<details class="ws-detail"' + (open ? ' open' : '') + '><summary>' + esc(title) + '</summary><div class="ws-detail-body">' + body + '</div></details>';
  function view(p, r) {
    const draft = O.draft.sync(p), path = pathOf(r), root = draft ? O.draftCompose(draft) : p.composed;
    return { draft, path, root, c: O.nodeAt(root, path) };
  }
  function mutate(fn) {
    const p = project(), d = O.draft.start(p);
    fn(d, p); O.draft.set(p.id, d); Y.rerender();
  }
  function draftBar(p, d) {
    if (!d) return '';
    const check = O.draftCheck(p, d), errors = check.v.rejects;
    return '<section class="ws-draft"><div class="ws-heading"><strong>组织草稿 · 尚未生效</strong><div class="ws-actions">' + button('放弃', 'og.discard') + '<button type="button" class="y19-btn primary" data-act="og.adopt"' + (errors.length ? ' disabled' : '') + '>查看差异并采用</button></div></div><p>只影响之后新建的事项；进行中的事项保留原组织。</p>' + (errors.length ? '<ul class="ws-errors">' + errors.map((x) => '<li>' + esc(x.text) + '</li>').join('') + '</ul>' : '<small>结构校验通过</small>') + (check.v.warns.length ? details('提醒（' + check.v.warns.length + '）', check.v.warns.map((x) => '<p>' + esc(x.text) + '</p>').join('')) : '') + '</section>';
  }
  const modeText = (c) => c.rotation === 'direct' ? '接到输入就做，其他角色通过询问协助。' : c.rotation === 'pool' ? '把工作放入任务池，由角色认领，逐项交回核验。' : '围绕成果交接；关注的成果更新后，相关部门继续工作。';
  function summary(c) {
    const a = O.answers(c);
    return '<section class="ws-summary"><span class="ws-eyebrow">协作方式</span><h2>' + esc(O.ROTATIONS[c.rotation]) + '</h2><p>' + esc(modeText(c)) + '</p><dl><div><dt>输入交给谁</dt><dd>' + esc(a.from) + '</dd></div><div><dt>核验关系</dt><dd>' + esc(a.verify) + '</dd></div><div><dt>怎样结束</dt><dd>' + esc(a.end) + '</dd></div></dl></section>';
  }
  function relationships(p, v) {
    const c = v.c, at = ' data-path="' + v.path.join('.') + '"', opts = (selected) => c.depts.map((d) => '<option value="' + esc(d.id) + '"' + (d.id === selected ? ' selected' : '') + '>' + esc(d.name) + '</option>').join('');
    const sources = c.sources.map((s) => field(s.name + '交给', '<select class="y19-select" data-act="ws.source" data-source="' + esc(s.id) + '"' + at + '>' + opts(s.to) + '</select>')).join('');
    let body = v.draft ? '<div class="ws-fields">' + sources + '</div>' : '';
    if (c.rotation === 'direct') {
      const done = O.completer(c);
      body += v.draft ? field('谁交完成', '<select class="y19-select" data-act="ws.completer"' + at + '>' + opts(done && done.id) + '</select>') : '<p>' + esc(done ? done.name + '交完成；其他角色按需协助。' : '需要指定交完成的角色。') + '</p>';
    } else {
      body += '<div class="ws-flow">' + c.outcomes.map((o) => {
        const producers = c.depts.filter((d) => d.produces.includes(o.id)).map((d) => d.name);
        const watchers = c.depts.filter((d) => d.watches.includes(o.id)).map((d) => d.name);
        return '<div><strong>' + esc(o.name) + '</strong><span>' + esc(producers.join('、') || '暂无产出方') + '产出</span><span>' + esc(watchers.length ? watchers.join('、') + '关注' : '没有后续关注方') + '</span></div>';
      }).join('') + '</div>';
      if (v.draft) body += field('事项最后采纳', '<select class="y19-select" data-act="ws.top" data-key="adopt"' + at + '>' + c.outcomes.map((o) => '<option value="' + esc(o.id) + '"' + (o.id === c.adopt ? ' selected' : '') + '>' + esc(o.name) + '</option>').join('') + '</select>');
      if (c.rotation === 'pool') body += (v.draft ? field('工作单元大小', '<input type="text" class="y19-input" data-act="ws.top" data-key="unit"' + at + ' value="' + esc(c.unit) + '">') : '<p>工作单元：' + esc(c.unit) + '</p>') + '<p>非核验角色可认领单元。单元交回后核验，全部完成后再按上面的结束条件核验整份交付。</p>';
    }
    return details(c.rotation === 'direct' ? '输入与完成安排' : '成果与交接关系', body + (v.draft ? button('编辑成果与核验定义', 'ws.advanced', { to: url(p, v.path) }) : ''), Boolean(v.draft));
  }
  function orgPage(ctx, p) {
    const v = view(p, ctx.route), c = v.c;
    if (!c) return '<p>这个内部组织已经被移除。' + link('返回组织', url(p, [])) + '</p>';
    const preview = p.designPreview || ['pool_preview', 'ops_preview'].includes(v.draft ? v.draft.form : p.org.form) || c.depts.some((d) => d.id === 'operations');
    const validation = !v.draft ? O.validate(c, O.ctxFor(p)) : null;
    const problems = validation && validation.rejects.length ? '<section class="ws-draft"><strong>当前组织需要处理</strong><ul class="ws-errors">' + validation.rejects.map((x) => '<li>' + esc(x.text) + '</li>').join('') + '</ul>' + button('查看并处理完整定义', 'ws.advanced', { to: url(p, v.path) }) + '</section>' : '';
    const candidates = !v.path.length && p.candidates.length ? '<p>' + button('查看组织候选（' + p.candidates.length + '）', 'ws.advanced', { to: url(p, []) }) + '</p>' : '';
    const members = c.depts.map((d) => {
      const state = !v.path.length && p.deptState[d.id];
      return '<a class="ws-member" href="' + url(p, v.path, '/d/' + d.id) + '"><div><strong>' + esc(d.name) + '</strong>' + (d.verifies ? ui.tag('核验') : '') + '<p>' + esc(d.goal) + '</p></div><div class="ws-member-meta"><span>' + esc(d.who.type === 'suborg' ? '内部小组 · ' + d.sub.depts.length + ' 个角色' : O.WHO[d.who.type]) + '</span><small>' + esc(state ? state.text : '按本层定义工作') + '</small><span aria-hidden="true">›</span></div></a>';
    }).join('');
    const observers = c.observers.length ? details('观察者 · ' + c.observers.filter((x) => x.on).length + ' 个已启用', '<p>在事项外读取事实，产生证据、提案与振荡信号。</p>' + c.observers.map((ob) => '<label class="y19-check"><input type="checkbox" data-act="ws.observer" data-id="' + ob.id + '" data-path="' + v.path.join('.') + '"' + (ob.on ? ' checked' : '') + (v.draft ? '' : ' disabled') + '><span>' + esc(ob.name) + ' · ' + esc(ob.scope) + '</span></label>').join('')) : '';
    return '<div class="ws-page">' + draftBar(p, v.draft) + (preview ? '<p class="ws-preview">设计预览 · 任务池与运维使用本页示例数据</p>' : '') + '<div class="ws-heading"><div><span class="ws-eyebrow">' + (v.path.length ? '角色内部' : '项目组织') + '</span><h1>' + esc(v.path.length ? c.formName : '协作安排') + '</h1></div><div class="ws-actions">' + (!v.draft ? button('调整组织', 'og.start', {}, 'primary') : '') + (!v.path.length ? button('换模板', 'ws.templates') : link('返回上层', url(p, v.path.slice(0, -1), '/d/' + v.path[v.path.length - 1]))) + '</div></div>' + problems + candidates + summary(c) + (v.path.length ? '<div class="ws-inner-note"><p>本层用量从上层剩余时间与用量范围中分配。内部完成后将结果作为上层角色的提案返回，外层仍按自己的核验安排结束。</p>' + button('查看内部线程演示', 'ws.inner', { path: v.path.join('.') }) + '</div>' : '') + '<section><div class="ws-heading"><h2>' + (v.path.length ? '内部角色' : '部门与角色') + '<small> ' + c.depts.length + '</small></h2>' + (v.draft ? button('添加部门', 'ws.add', { path: v.path.join('.') }) : '') + '</div><div class="ws-members">' + members + '</div></section>' + relationships(p, v) + observers + details('版本与高级配置', '<p>当前版本：' + esc(p.version) + '</p>' + button('采用历史', 'og.history') + ' ' + button('完整组织配置', 'ws.advanced', { to: url(p, v.path) })) + '</div>';
  }
  function modelGroup(p, v, d) {
    const key = v.path.concat(d.id).join('.'), table = v.path.length ? p.settings.nodes : p.settings.dept;
    const pending = v.draft && v.draft.pending, s = (!v.path.length && pending && pending[key]) || table[key] || {};
    const effective = O.nodeModel(p, v.path.concat(d.id), pending);
    return '<p>当前生效：<strong>' + esc(effective || '尚未配置') + '</strong> · ' + (s.model ? '本项目覆盖' : v.path.length ? '跟随上层角色' : '跟随模型管理中的部门使用') + '</p>' + field('模型', '<select id="ws-model" class="y19-select"><option value="">跟随默认来源</option>' + O.modelChoices().map((m) => '<option' + (m === s.model ? ' selected' : '') + '>' + esc(m) + '</option>').join('') + '</select>') + field('Prompt 补充', '<textarea id="ws-prompt" class="y19-textarea" rows="3" placeholder="跟随职责生成的底稿，可补充项目要求">' + esc(s.prompt || '') + '</textarea>') + '<p class="y19-small y19-muted">保存后从下一次模型请求起生效。</p><div class="ws-actions">' + button('保存模型与 Prompt', 'ws.model-save', { key, nested: v.path.length ? '1' : '' }) + button('恢复跟随', 'ws.model-reset', { key, nested: v.path.length ? '1' : '' }) + '</div>';
  }
  function deptPage(ctx, p) {
    const v = view(p, ctx.route), d = v.c && v.c.depts.find((x) => x.id === ctx.route.params.dept);
    if (!d) return '<p>这个角色已经被移除。' + link('返回组织', url(p, v.path)) + '</p>';
    const data = ' data-path="' + v.path.join('.') + '" data-dept="' + esc(d.id) + '"';
    const roleFields = [['goal', '职责'], ['judge', '判断依据'], ['how', '工作方法']].map(([k, label]) => v.draft ? field(label, '<textarea class="y19-textarea" rows="2" data-act="ws.field" data-field="' + k + '"' + data + '>' + esc(d[k]) + '</textarea>') : '<p><b>' + label + '</b><br>' + esc(d[k]) + '</p>').join('');
    const tooDeep = v.path.length + 1 > O.MAX_DEPTH;
    let who = v.draft ? field('由谁执行', '<select class="y19-select" data-act="ws.who"' + data + '>' + Object.entries(O.WHO).map(([k, name]) => '<option value="' + k + '"' + (d.who.type === k ? ' selected' : '') + ((k === 'outsourced' && d.verifies) || (k === 'suborg' && tooDeep) ? ' disabled' : '') + '>' + esc(name + (k === 'outsourced' && d.verifies ? '（核验角色不可外包）' : k === 'suborg' && tooDeep ? '（已到嵌套上限）' : '')) + '</option>').join('') + '</select>') : '<p>' + esc(O.WHO[d.who.type]) + '</p>';
    if (d.who.type === 'outsourced') who += v.draft ? field('外部 agent', '<select class="y19-select" data-act="ws.agent"' + data + '>' + O.AGENTS.map((a) => '<option' + (a === d.who.agent ? ' selected' : '') + '>' + esc(a) + '</option>').join('') + '</select>') : '<p>' + esc(d.who.agent) + '</p>';
    if (d.sub) who += '<p>' + esc(d.sub.formName) + ' · ' + d.sub.depts.map((x) => esc(x.name)).join('、') + '</p>' + link('进入内部小组', url(p, v.path.concat(d.id))) + '<p class="y19-small y19-muted">内部结束条件：' + esc(O.ending(d.sub).text) + '。结果作为「' + esc(d.name) + '」的提案返回外层。</p>';
    const verify = d.verifies ? d.name + '核验' + ((v.c.depts.find((x) => x.id === d.verifies.dept) || {}).name || d.verifies.dept) + '的' + O.kindName(v.c, d.verifies.kind) : v.c.depts.filter((x) => x.verifies && x.verifies.dept === d.id).map((x) => x.name + '核验' + O.kindName(v.c, x.verifies.kind)).join('；') || '这个角色没有独立核验关系';
    return '<div class="ws-page">' + draftBar(p, v.draft) + '<div class="ws-heading"><h1>' + esc(d.name) + '</h1><div class="ws-actions">' + link('返回组织', url(p, v.path)) + (!v.draft ? button('调整角色', 'og.start', {}, 'primary') : button('移除角色', 'ws.remove', { path: v.path.join('.'), dept: d.id })) + '</div></div>' + details('职责', roleFields, true) + details('执行方式 · ' + O.WHO[d.who.type], who, Boolean(v.draft)) + details('模型与 Prompt · ' + (O.nodeModel(p, v.path.concat(d.id), v.draft && v.draft.pending) || '尚未配置'), modelGroup(p, v, d)) + details('成果与核验', '<p>' + esc(verify) + '</p><p>产出：' + esc(d.produces.map((k) => O.kindName(v.c, k)).join('、') || '按需回答询问') + '</p>' + button('调整成果与核验关系', 'ws.advanced', { to: url(p, v.path, '/d/' + d.id), edit: '1' })) + details('工具与写入范围', '<p>' + esc(d.tools.join('、')) + '</p><p>写入范围：' + esc(O.WRITE[d.write]) + '</p>' + button('调整工具与权限', 'ws.advanced', { to: url(p, v.path, '/d/' + d.id), edit: '1' })) + (d.id === 'operations' ? '<section class="ws-summary"><h2>运行环境 · 设计预览</h2><p>部署与健康记录独立于开发事项的核验结论。</p>' + button('查看运行环境', 'ops.open') + '</section>' : '') + '</div>';
  }
  function settings(ctx, p) {
    const r = O.firstReceivers(p.composed)[0], single = p.composed.depts.length === 1;
    return '<div class="ws-page ws-settings"><h1>项目设置</h1>' + field('项目名字', '<input type="text" class="y19-input" data-act="ln.name" value="' + esc(p.name) + '">') + field('起始文件夹', '<input type="text" class="y19-input" data-act="ln.dir" value="' + esc(p.dir || '') + '" placeholder="可选">') + details('长期目标（可选）', field('希望这个项目长期做成什么', '<textarea class="y19-textarea" rows="3" data-act="ln.goal">' + esc(p.goal.startsWith('（还没有') ? '' : p.goal) + '</textarea>')) + '<section class="ws-setting-row"><div><h2>当前组织</h2><p>' + esc(O.ROTATIONS[p.composed.rotation] + ' · ' + p.composed.depts.map((d) => d.name).join('、')) + '</p><small>' + esc(O.ending(p.composed).text) + '</small></div>' + link('查看与调整', url(p, [])) + '</section>' + (single ? details('模型 · ' + (O.modelOf(p, r.id) || '尚未配置'), modelGroup(p, { path: [], draft: null }, r)) : '<section class="ws-setting-row"><div><h2>模型与 Prompt</h2><p>各角色的生效模型与跟随来源在角色详情中查看。</p></div>' + link('查看角色', url(p, [])) + '</section>') + details('高级配置', '<p>执行位置、机器授权、MCP 服务器与成果写回。</p>' + button('打开高级配置', 'ws.advanced', { to: '#/p/' + p.id + '/settings' })) + '</div>';
  }
  Y.leanViews.org = { render: orgPage }; Y.leanViews['org-sub'] = { render: orgPage };
  Y.leanViews['org-dept'] = { render: deptPage }; Y.leanViews.settings = { render: settings };
  A('ws.source', (el) => mutate((d) => O.setSource(d.changes, d.form, pathOf({ params: el.dataset }), el.dataset.source, el.value)));
  A('ws.top', (el) => mutate((d) => O.setTop(d.changes, d.form, pathOf({ params: el.dataset }), el.dataset.key, el.value)));
  A('ws.completer', (el) => mutate((d) => { const path = pathOf({ params: el.dataset }), c = O.nodeAt(O.draftCompose(d), path); c.depts.forEach((x) => O.setField(d.changes, d.form, path, 'depts', x.id, 'completes', x.id === el.value)); }));
  A('ws.field', (el) => mutate((d) => O.setField(d.changes, d.form, pathOf({ params: el.dataset }), 'depts', el.dataset.dept, el.dataset.field, el.value.trim())));
  A('ws.who', (el) => mutate((d) => O.setField(d.changes, d.form, pathOf({ params: el.dataset }), 'depts', el.dataset.dept, 'who', el.value === 'own' ? { type: 'own' } : el.value === 'suborg' ? { type: 'suborg', form: 'hub', changes: {} } : { type: 'outsourced', agent: O.AGENTS[0] })));
  A('ws.agent', (el) => mutate((d) => O.setField(d.changes, d.form, pathOf({ params: el.dataset }), 'depts', el.dataset.dept, 'who', { type: 'outsourced', agent: el.value })));
  A('og.history', () => ui.modal({ title: '组织采用历史', wide: true, body: '<div class="ws-log">' + project().org.history.slice().reverse().map((h) => '<section><strong>' + esc(h.reason) + '</strong><p>' + esc(ui.time(h.at)) + ' · ' + esc(h.toVersion) + '</p><ul>' + (h.diff || []).map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul></section>').join('') + '</div>', actions: [{ label: '关闭', close: true }] }));
  A('ws.remove', (el) => { mutate((d) => O.removeDept(d.changes, d.form, pathOf({ params: el.dataset }), el.dataset.dept)); Y.go(url(project(), pathOf({ params: el.dataset }))); });
  A('ws.observer', (el) => mutate((d) => O.setField(d.changes, d.form, pathOf({ params: el.dataset }), 'observers', el.dataset.id, 'on', el.checked)));
  A('ws.model-save', (el) => { const p = project(), table = el.dataset.nested ? p.settings.nodes : p.settings.dept; table[el.dataset.key] = { model: document.getElementById('ws-model').value, prompt: document.getElementById('ws-prompt').value }; const d = O.draft.get(p.id); if (!el.dataset.nested && d && d.pending[el.dataset.key]) { d.pending[el.dataset.key] = clone(table[el.dataset.key]); O.draft.set(p.id, d); } ui.toast('已保存，从下一次模型请求起生效', 'ok'); Y.rerender(); });
  A('ws.model-reset', (el) => { const p = project(); delete (el.dataset.nested ? p.settings.nodes : p.settings.dept)[el.dataset.key]; const d = O.draft.get(p.id); if (!el.dataset.nested && d && d.pending[el.dataset.key]) { delete d.pending[el.dataset.key]; O.draft.set(p.id, d); } ui.toast('已恢复跟随默认来源', 'ok'); Y.rerender(); });
  Y.advancedReturn = null;
  A('ws.advanced', (el) => { Y.advancedReturn = { hash: location.hash, y: window.scrollY, open: [...document.querySelectorAll('.ws-detail')].map((d) => d.open) }; if (el.dataset.edit) O.draft.start(project()); Y.go(el.dataset.to + '?advanced=1'); });
  A('ws.return', () => { const back = Y.advancedReturn; Y.go(back ? back.hash : url(project(), [])); setTimeout(() => { if (!back) return; document.querySelectorAll('.ws-detail').forEach((d, i) => { if (i < back.open.length) d.open = back.open[i]; }); window.scrollTo(0, back.y); }, 0); });
  A('ws.templates', () => ui.modal({ title: '选择组织模板', wide: true, body: '<p>选择后先生成草稿，查看差异并采用后生效。现有草稿中的改动将被替换。</p><div class="ln-cards">' + Y.thread.templates('ws.template') + '</div>', actions: [{ label: '取消', close: true }] }));
  A('ws.template', (el) => { const p = project(); O.draft.set(p.id, { base: p.version, form: el.dataset.form, changes: {}, pending: el.dataset.form === 'ops_preview' ? { operations: { model: Y.EXTRA.wiring.engineering.model } } : {}, rebased: false }); ui.closeModal(); Y.rerender(); });
  A('ws.add', (el) => ui.modal({ title: '添加部门', body: '<p>自定义部门需填写职责、判断依据、工作方法与模型，再经过同一套组织校验。</p>' + button('自定义或复制部门', 'ws.custom', { path: el.dataset.path }) + (!el.dataset.path && !O.draftCompose(O.draft.get(project().id)).depts.some((d) => d.id === 'operations') ? '<hr><p>运维 · 设计预览。新增部门后，运行环境授权需单独登记。</p>' + button('添加运维预览', 'ws.add-ops') : ''), actions: [{ label: '取消', close: true }] }));
  A('ws.custom', (el) => { ui.closeModal(); Y.go(url(project(), pathOf({ params: el.dataset }), '/new')); });
  A('ws.add-ops', () => { mutate((d) => { const c = O.draftCompose(d), maker = O.completer(c), finalKind = c.rotation === 'direct' ? (maker && maker.produces[0]) : c.adopt; d.changes.depts = d.changes.depts || {}; d.changes.depts.operations = Object.assign({ added: true }, clone(Y.designPreview.operations), { watches: finalKind ? [finalKind] : [] }); d.changes.outcomes = d.changes.outcomes || {}; Y.designPreview.opsOutcomes.forEach((o) => { d.changes.outcomes[o.id] = Object.assign({ added: true }, clone(o), { basedOn: finalKind || 'input' }); }); d.pending.operations = { model: Y.EXTRA.wiring.engineering.model }; }); ui.closeModal(); });
})();
