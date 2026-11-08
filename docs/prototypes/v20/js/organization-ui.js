// 简洁的组织与角色页面。草稿、结构校验与采用仍使用 org.js 的同一份定义。
(function () {
  'use strict';
  const Y = window.Y20, O = Y.org, H = Y.h, ui = Y.ui, esc = Y.esc;
  const A = Y.actions.register, clone = (x) => JSON.parse(JSON.stringify(x));
  const project = () => H.project(H.pid());
  const pathOf = (r) => r.params.path ? r.params.path.split('.') : [];
  const url = (p, path, tail) => '#/p/' + p.id + '/org' + (path.length ? '/s/' + path.join('.') : '') + (tail || '');
  const button = (text, act, data, kind) => ui.button({ label: text, act, data, kind });
  const link = (text, go) => ui.button({ label: text, go, kind: 'small' });
  const field = (label, control) => '<label class="y20-field"><span>' + esc(label) + '</span>' + control + '</label>';
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
    return '<section class="ws-draft"><div class="ws-heading"><strong>组织草稿 · 尚未生效</strong><div class="ws-actions">' + button('放弃', 'og.discard') + '<button type="button" class="y20-btn primary" data-act="og.adopt"' + (errors.length ? ' disabled' : '') + '>查看差异并采用</button></div></div><p>只影响之后新建的事项；进行中的事项保留原组织。</p>' + (errors.length ? '<ul class="ws-errors">' + errors.map((x) => '<li>' + esc(x.text) + '</li>').join('') + '</ul>' : '<small>结构校验通过</small>') + (check.v.warns.length ? details('提醒（' + check.v.warns.length + '）', check.v.warns.map((x) => '<p>' + esc(x.text) + '</p>').join('')) : '') + '</section>';
  }
  function modelGroup(p, v, d) {
    const key = v.path.concat(d.id).join('.'), table = v.path.length ? p.settings.nodes : p.settings.dept;
    const pending = v.draft && v.draft.pending, s = (!v.path.length && pending && pending[key]) || table[key] || {};
    const effective = O.nodeModel(p, v.path.concat(d.id), pending);
    return '<p>当前生效：<strong>' + esc(effective || '尚未配置') + '</strong> · ' + (s.model ? '本项目覆盖' : v.path.length ? '跟随上层角色' : '跟随模型管理中的职能使用') + '</p>' + field('模型', '<select id="ws-model" class="y20-select"><option value="">跟随默认来源</option>' + O.modelChoices().map((m) => '<option' + (m === s.model ? ' selected' : '') + '>' + esc(m) + '</option>').join('') + '</select>') + field('Prompt 补充', '<textarea id="ws-prompt" class="y20-textarea" rows="3" placeholder="跟随职责生成的底稿，可补充项目要求">' + esc(s.prompt || '') + '</textarea>') + '<p class="y20-small y20-muted">保存后从下一次模型请求起生效。</p><div class="ws-actions">' + button('保存模型与 Prompt', 'ws.model-save', { key, nested: v.path.length ? '1' : '' }) + button('恢复跟随', 'ws.model-reset', { key, nested: v.path.length ? '1' : '' }) + '</div>';
  }
  // 职能详情：从循环图的节点进。由谁做一步生效，不经草稿；职责、权限与成果在「高级」里改。
  function deptPage(ctx, p) {
    const v = view(p, ctx.route), d = v.c && v.c.depts.find((x) => x.id === ctx.route.params.dept);
    if (!d) return '<p>这个职能已经被去掉。' + link('回到对话', '#/p/' + p.id) + '</p>';
    const data = ' data-path="' + v.path.join('.') + '" data-dept="' + esc(d.id) + '"';
    const tooDeep = v.path.length + 1 > O.MAX_DEPTH;
    const out = d.who.type === 'outsourced', sub = d.who.type === 'suborg';
    const kind = '<label class="y20-check"><input type="radio" name="ws-who" value="own" data-act="ws.who"' + data + (d.who.type !== 'outsourced' ? ' checked' : '') + '><span>自有角色</span></label>' +
      '<label class="y20-check"><input type="radio" name="ws-who" value="outsourced" data-act="ws.who"' + data + (out ? ' checked' : '') + (d.verifies ? ' disabled' : '') + '><span>外部 agent' + (d.verifies ? '（核验角色不外包）' : '') + '</span></label>' +
      (out ? field('选一个外部 agent', '<select class="y20-select" data-act="ws.agent"' + data + '>' + O.AGENTS.map((a) => '<option' + (a === d.who.agent ? ' selected' : '') + '>' + esc(a) + '</option>').join('') + '</select>') : '');
    const size = out ? '<p class="y20-small y20-muted">外部 agent 本来就由别人做，不再分一个角色还是一个小组。</p>' :
      '<label class="y20-check"><input type="radio" name="ws-size" value="one" data-act="ws.size"' + data + (sub ? '' : ' checked') + '><span>一个角色</span></label>' +
      '<label class="y20-check"><input type="radio" name="ws-size" value="group" data-act="ws.size"' + data + (sub ? ' checked' : '') + (tooDeep ? ' disabled' : '') + '><span>一个小组（子组织，默认中心型小组）' + (tooDeep ? '：层数到上限，不能再选' : '') + '</span></label>' +
      (d.sub ? '<p class="y20-small">' + esc(d.sub.formName) + '：' + d.sub.depts.map((x) => esc(x.name) + (x.verifies ? '（核验）' : '')).join('、') + '。这个职能的一轮工作开一个子事项，结果作为' + esc(d.name) + '的提案回到上一层。</p>' + link('看内部的职能', url(p, v.path.concat(d.id))) : '');
    const verify = d.verifies ? '核验' + ((v.c.depts.find((x) => x.id === d.verifies.dept) || {}).name || d.verifies.dept) + '交的' + O.kindName(v.c, d.verifies.kind) + '（它的角色是核验角色）' : v.c.depts.filter((x) => x.verifies && x.verifies.dept === d.id).map((x) => x.name + '核验它交的' + O.kindName(v.c, x.verifies.kind)).join('；') || '没有人核验它';
    const model = out ? '<p>模型经受控入口由本项目定；推理档位由外部 agent 自己定。</p><p>模型：<strong>' + esc(O.nodeModel(p, v.path.concat(d.id)) || '尚未配置') + '</strong></p>' : modelGroup(p, v, d);
    const crumb = v.path.length ? v.path.map((id, i) => esc((O.nodeAt(v.root, v.path.slice(0, i)).depts.find((x) => x.id === id) || {}).name || id)).join(' › ') + ' › 内部 › ' : '';
    const back = v.path.length ? link('回到上一层', url(p, v.path.slice(0, -1), '/d/' + v.path[v.path.length - 1])) : link('回到对话', '#/p/' + p.id);
    const marks = (d.verifies ? ui.tag('核验') : '') + (out ? ui.tag(d.who.agent) : '') + (sub ? ui.tag('子组织') : '');
    return '<div class="ws-page lp-dept"><div class="ws-heading"><div><span class="ws-eyebrow">职能详情</span><h1>' + crumb + esc(d.name) + ' ' + marks + '</h1></div><div class="ws-actions">' + back + '</div></div>' +
      '<p class="y20-muted y20-small">由谁做、模型与 Prompt 在这里改，一步生效；职责、权限、关注与交出的成果在设置页的「高级」里改。</p>' +
      details('职责 · 之后新建的事项', '<p><b>它对什么负责</b><br>' + esc(d.goal) + '</p><p><b>凭什么判断</b><br>' + esc(d.judge) + '</p><p><b>怎么工作</b><br>' + esc(d.how) + '</p><p>关注：' + esc(d.watches.map((k) => O.kindName(v.c, k)).join('、') || '你的输入') + '；交出：' + esc(d.produces.map((k) => O.kindName(v.c, k)).join('、') || '只回答询问') + '；' + esc(verify) + '</p>', true) +
      details('由谁做 · 之后新建的事项', '<div class="lp-who"><div><b class="y20-small">谁来做</b>' + kind + '</div><div><b class="y20-small">一个角色还是一个小组</b>' + size + '</div></div>', true) +
      details('模型与 Prompt · 下一次模型请求', model, true) +
      details('权限 · 之后新建的事项', '<p>工具：' + esc(d.tools.join('、')) + '</p><p>写入范围：' + esc(O.WRITE[d.write]) + '</p>' + button('在高级里改', 'ws.advanced', { to: url(p, v.path, '/d/' + d.id), edit: '1' })) + '</div>';
  }
  // 由谁做：一步采用，理由自动写
  function adoptWho(el, who, label) {
    const p = project(), path = pathOf({ params: el.dataset }), ch = clone(p.org.changes);
    O.setField(ch, p.org.form, path, 'depts', el.dataset.dept, 'who', who);
    const res = O.adopt(p, { form: p.org.form, changes: ch, reason: label, base: p.version, key: Y.uid('who'), pending: {} });
    if (!res.ok) { ui.toast(res.error + (res.rejects ? '：' + res.rejects.map((r) => r.text).join('；') : ''), 'warn'); Y.rerender(); return; }
    ui.toast('已生效：' + label + '；只对之后新建的事项生效', 'ok'); Y.rerender();
  }
  A('ws.who', (el) => adoptWho(el, el.value === 'own' ? { type: 'own' } : { type: 'outsourced', agent: O.AGENTS[0] }, el.value === 'own' ? '由谁做：自有角色' : '由谁做：外部 agent（' + O.AGENTS[0] + '）'));
  A('ws.agent', (el) => adoptWho(el, { type: 'outsourced', agent: el.value }, '由谁做：外部 agent（' + el.value + '）'));
  A('ws.size', (el) => adoptWho(el, el.value === 'group' ? { type: 'suborg', form: 'hub', changes: {} } : { type: 'own' }, el.value === 'group' ? '由谁做：一个小组（中心型小组）' : '由谁做：一个角色'));
  Y.leanViews['org-dept'] = { render: deptPage };
  A('ws.source', (el) => mutate((d) => O.setSource(d.changes, d.form, pathOf({ params: el.dataset }), el.dataset.source, el.value)));
  A('ws.top', (el) => mutate((d) => O.setTop(d.changes, d.form, pathOf({ params: el.dataset }), el.dataset.key, el.value)));
  A('ws.completer', (el) => mutate((d) => { const path = pathOf({ params: el.dataset }), c = O.nodeAt(O.draftCompose(d), path); c.depts.forEach((x) => O.setField(d.changes, d.form, path, 'depts', x.id, 'completes', x.id === el.value)); }));
  A('ws.field', (el) => mutate((d) => O.setField(d.changes, d.form, pathOf({ params: el.dataset }), 'depts', el.dataset.dept, el.dataset.field, el.value.trim())));
  A('og.history', () => ui.modal({ title: '组织采用历史', wide: true, body: '<div class="ws-log">' + project().org.history.slice().reverse().map((h) => '<section><strong>' + esc(h.reason) + '</strong><p>' + esc(ui.time(h.at)) + ' · ' + esc(h.toVersion) + '</p><ul>' + (h.diff || []).map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul></section>').join('') + '</div>', actions: [{ label: '关闭', close: true }] }));
  A('ws.remove', (el) => { mutate((d) => O.removeDept(d.changes, d.form, pathOf({ params: el.dataset }), el.dataset.dept)); Y.go(url(project(), pathOf({ params: el.dataset }))); });
  A('ws.observer', (el) => mutate((d) => O.setField(d.changes, d.form, pathOf({ params: el.dataset }), 'observers', el.dataset.id, 'on', el.checked)));
  A('ws.model-save', (el) => { const p = project(), table = el.dataset.nested ? p.settings.nodes : p.settings.dept; table[el.dataset.key] = { model: document.getElementById('ws-model').value, prompt: document.getElementById('ws-prompt').value }; const d = O.draft.get(p.id); if (!el.dataset.nested && d && d.pending[el.dataset.key]) { d.pending[el.dataset.key] = clone(table[el.dataset.key]); O.draft.set(p.id, d); } ui.toast('已保存，从下一次模型请求起生效', 'ok'); Y.rerender(); });
  A('ws.model-reset', (el) => { const p = project(); delete (el.dataset.nested ? p.settings.nodes : p.settings.dept)[el.dataset.key]; const d = O.draft.get(p.id); if (!el.dataset.nested && d && d.pending[el.dataset.key]) { delete d.pending[el.dataset.key]; O.draft.set(p.id, d); } ui.toast('已恢复跟随默认来源', 'ok'); Y.rerender(); });
  Y.advancedReturn = null;
  A('ws.advanced', (el) => { Y.advancedReturn = { hash: location.hash, y: window.scrollY, open: [...document.querySelectorAll('.ws-detail')].map((d) => d.open) }; if (el.dataset.edit) O.draft.start(project()); Y.go(el.dataset.to + '?advanced=1'); });
  A('ws.return', () => { const back = Y.advancedReturn; Y.go(back ? back.hash : url(project(), [])); setTimeout(() => { if (!back) return; document.querySelectorAll('.ws-detail').forEach((d, i) => { if (i < back.open.length) d.open = back.open[i]; }); window.scrollTo(0, back.y); }, 0); });
  A('ws.add', (el) => ui.modal({ title: '添加职能', body: '<p>自定义职能需填写职责、判断依据、工作方法与模型，再经过同一套组织校验。</p>' + button('自定义或复制职能', 'ws.custom', { path: el.dataset.path }) + (!el.dataset.path && !O.draftCompose(O.draft.get(project().id)).depts.some((d) => d.id === 'operations') ? '<hr><p>运维 · 设计预览。新增职能后，运行环境授权需单独登记。</p>' + button('添加运维预览', 'ws.add-ops') : ''), actions: [{ label: '取消', close: true }] }));
  A('ws.custom', (el) => { ui.closeModal(); Y.go(url(project(), pathOf({ params: el.dataset }), '/new')); });
  A('ws.add-ops', () => { mutate((d) => { const c = O.draftCompose(d), maker = O.completer(c), finalKind = c.rotation === 'direct' ? (maker && maker.produces[0]) : c.adopt; d.changes.depts = d.changes.depts || {}; d.changes.depts.operations = Object.assign({ added: true }, clone(Y.designPreview.operations), { watches: finalKind ? [finalKind] : [] }); d.changes.outcomes = d.changes.outcomes || {}; Y.designPreview.opsOutcomes.forEach((o) => { d.changes.outcomes[o.id] = Object.assign({ added: true }, clone(o), { basedOn: finalKind || 'input' }); }); d.pending.operations = { model: Y.EXTRA.wiring.engineering.model }; }); ui.closeModal(); });
})();
