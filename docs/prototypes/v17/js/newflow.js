// 新建项目、接入已有项目、新建事项：选组织，建在内存里（刷新页面就没有了）。
(function () {
  'use strict';
  const Y17 = window.Y17;
  const O = Y17.org;
  const H = Y17.h;
  const ui = Y17.ui;
  const esc = Y17.esc;
  const X = Y17.EXTRA;
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const A = (name, fn) => Y17.actions.register(name, fn);
  const $ = (id) => document.getElementById(id);
  let counter = 0;

  // ---------------------------------------------------------------- 选组织

  function orgPicker(prefix) {
    const w = Y17.W();
    const projects = w.projects.map((p) => '<option value="' + p.id + '">' + esc(p.name) + '</option>').join('');
    const cat = Y17.orgpage.catalogHtml({ name: prefix + '-org', act: 'np.pick', checkedId: 'three', currentId: 'three', currentTag: '默认', noLayers: true });
    return '<div class="y17-field"><span>组织 ' + ui.tag('新增', 'new') + '</span>' + cat + '<div class="y17-org-radios">' +
      '<label class="y17-org-radio"><input type="radio" name="' + prefix + '-org" value="same" data-act="np.pick"><span><strong>和某项目一样</strong><select class="y17-select" id="' + prefix + '-same" data-act="np.pick" disabled>' + projects + '</select>' +
      '<small>复制一次形态名、本项目的改动、项目部门设置与项目角色设置；机器授权、执行位置、源目录、MCP 服务器不复制；之后两边各改各的。</small></span></label></div>' +
      '<div class="y17-layers"><b>两个可选的层 ' + ui.tag('新增', 'new') + '</b>' +
      '<label class="y17-check"><input type="checkbox" id="' + prefix + '-obs" data-act="np.pick"><span>加观察者：在事项外面读事实，产出证据、提案、振荡信号；不进部门表，不改事项怎么结束</span></label>' +
      '<label class="y17-check"><input type="checkbox" id="' + prefix + '-sub" data-act="np.pick"><span>工程内部用子组织（中心型小组）：工程的一轮工作开一个子事项，结果作为工程的提案回到上一层</span></label></div>' +
      '<div class="y17-note is-info" id="' + prefix + '-sum"></div></div>';
  }
  function pickedOrg(prefix) {
    const val = (document.querySelector('input[name="' + prefix + '-org"]:checked') || {}).value || 'three';
    let o;
    if (val === 'same') { const src = H.project($(prefix + '-same').value); o = { kind: 'same', form: src.org.form, changes: clone(src.org.changes), from: src }; }
    else o = { kind: val === 'three' ? 'default' : 'form', form: val, changes: {} };
    o.layers = [];
    if ($(prefix + '-obs').checked) { o.changes.observers = Object.assign({}, o.changes.observers, { lessons: { on: true }, oscillation: { on: true } }); o.layers.push('观察者'); }
    // 外包角色本来就由别人做，不再分形
    const eng = O.compose({ form: o.form, changes: o.changes }).depts.find((d) => d.id === 'engineering');
    o.subBlocked = !!(eng && eng.who && eng.who.type === 'outsourced');
    $(prefix + '-sub').disabled = o.subBlocked;
    if (o.subBlocked) $(prefix + '-sub').checked = false;
    if ($(prefix + '-sub').checked) { o.changes.depts = Object.assign({}, o.changes.depts); o.changes.depts.engineering = Object.assign({}, o.changes.depts.engineering, { who: { type: 'suborg', form: 'hub', changes: {} } }); o.layers.push('工程内部用子组织'); }
    return o;
  }
  function refreshPick(prefix) {
    $(prefix + '-same').disabled = !document.querySelector('input[name="' + prefix + '-org"][value="same"]').checked;
    const o = pickedOrg(prefix);
    const c = O.compose({ form: o.form, changes: o.changes });
    const a = O.answers(c), f = O.form(o.form);
    $(prefix + '-sum').innerHTML = '选用：<b>' + esc(c.formName) + '</b>' + (O.count(o.changes) ? '，带 ' + O.count(o.changes) + ' 处改动' : '') + (o.layers.length ? '，加上「' + esc(o.layers.join('」「')) + '」' : '') + ' · ' + esc(O.ROTATIONS[c.rotation]) + '。<br>' +
      '事项的来源：' + esc(a.from) + '；谁做：' + esc(a.who) + '；谁核验：' + esc(a.verify) + '；怎么结束：' + esc(a.end) + '。' + (f && f.tip && o.kind !== 'same' ? '<br>' + esc(f.tip) + '。' : '');
    if (o.subBlocked) $(prefix + '-sum').innerHTML += '<br>工程是外包角色，本来就由别人做，没有子组织层。';
  }
  A('np.pick', (el) => { const prefix = el.closest('[data-np]').dataset.np; refreshPick(prefix); });

  // ---------------------------------------------------------------- 往内存里建

  function nowIso(extraMin) { return Y17.time.add(Y17.app.now(), 60 * (extraMin || 0)); }

  function pushEvent(w, p, item, type, label, source, by, detail) {
    const pos = Math.max.apply(null, w.events.map((e) => e.pos)) + 3;
    const e = { key: 'ev-' + pos, project: p.id, item, type, label, source, by, at: nowIso(), detail: detail || null, pos };
    w.events.push(e); w.byKey[e.key] = e;
    return e;
  }

  // 新建事项：合成、校验、冻结。返回 { ok, item } 或 { ok:false, rejects }
  function addItem(p, opts) {
    const w = Y17.W();
    const info = O.itemOrg(p, opts.form || '');
    if (info.rejects.length) return { ok: false, rejects: info.rejects };
    const recv = O.firstReceivers(info.c)[0];
    const n = (w.doorNext[p.id] = (w.doorNext[p.id] || 1));
    w.doorNext[p.id] += 1;
    const it = { id: 'w' + p.id.replace(/\W/g, '') + n, door: (p.letter || 'N') + '-' + n, title: opts.title, color: n % 6, dept: recv.id, status: 'working', round: 1, round_limit: 8, used: 0, limit: 14400,
      reason: opts.reason || (recv.name + '接到你的输入，正在开始第 1 轮'), created: nowIso(), org: info.org, text: opts.text };
    p.items.unshift(it);
    const inId = 'o-' + it.id + '-in';
    const o = { id: inId, project: p.id, item: it.id, kind: 'input', text: opts.text, from: 'user', to: recv.id, at: nowIso() };
    p.outcomes.push(o);
    const ev = pushEvent(w, p, it.id, '事项创建', '事项「' + it.title + '」建立，门牌 ' + it.door + '，冻结的组织是「' + info.org.formName + '」' + info.org.version, 'rule', '系统');
    w.byKey['door-' + it.id] = ev;
    w.byKey['round-' + it.id] = pushEvent(w, p, it.id, '一轮工作开始', '「' + it.title + '」开始第 1 轮', 'rule', '系统');
    w.byKey['status-' + it.id] = pushEvent(w, p, it.id, '状态变化', '「' + it.title + '」现在的状态：进行中', 'rule', '系统');
    w.byKey[inId] = pushEvent(w, p, it.id, Y17.OUTCOME_KINDS.input, Y17.OUTCOME_KINDS.input + '：' + opts.text, 'user', '用户');
    const ds = p.deptState[recv.id] || (p.deptState[recv.id] = O.idleState(p, recv.id));
    ds.items = (ds.items || []).concat(it.id);
    if (ds.state === 'idle') { ds.state = 'running'; ds.text = '接到你的输入：' + it.title; ds.reason = '一轮工作进行中，第 1 轮'; }
    X.slotHolders[p.id] = (X.slotHolders[p.id] || []).concat(it.id);
    p.slots.used = Math.min(p.slots.limit, p.slots.used + 1);
    O.refresh(p);
    return { ok: true, item: it, info };
  }
  Y17.newItem = addItem;

  function createProject(spec) {
    const w = Y17.W();
    counter += 1;
    const id = 'np' + counter;
    const letter = 'HJKLMNPQR'[(counter - 1) % 9];
    const o = spec.org;
    const c0 = O.compose({ form: o.form, changes: o.changes });
    const p = { id, name: spec.name, goal: spec.goal || '（还没有写长期目标）', letter, dir: spec.dir || '', items: [], depts: [], deptState: {}, asks: [], interruptions: [], elapsed: { used: 0, limit: 86400, key: null },
      slots: { used: 0, limit: 3, waiting: 0 }, provider_wait: [], hand: {}, outcomes: [], candidates: [],
      settings: o.from ? clone(o.from.settings) : { dept: {}, roles: {}, nodes: {} },
      org: { form: o.form, changes: clone(o.changes), keys: {}, history: [{ at: nowIso(), by: '你', fromVersion: '', toVersion: O.version(c0), form: o.form, changes: clone(o.changes),
        reason: (o.from ? '建项目时和「' + o.from.name + '」一样' : o.kind === 'form' ? '建项目时选用发布带的「' + c0.formName + '」' : '建项目时选用默认的三部门') + (o.layers.length ? '，加上' + o.layers.join('、') : ''),
        diff: ['建项目，选用「' + c0.formName + '」'].concat(o.layers.map((t) => '加上「' + t + '」')).concat(o.from ? ['复制了「' + o.from.name + '」的 ' + O.count(o.changes) + ' 处改动、项目部门设置与项目角色设置；机器授权、执行位置、源目录、MCP 服务器没有复制'] : []) }] } };
    X.ensure(p);
    O.refresh(p);
    w.projects.push(p);
    w.doorNext[id] = 1;
    return p;
  }

  // ---------------------------------------------------------------- 新建项目、接入已有项目

  function projectDialog(attach) {
    const prefix = attach ? 'pa' : 'pn';
    const body = '<div class="y17-form" data-np="' + prefix + '"><label class="y17-field"><span>名称（必填）</span><input class="y17-input" id="' + prefix + '-name" data-live data-act="np.check" placeholder="例如 官网改版"></label>' +
      '<label class="y17-field"><span>长期目标</span><textarea class="y17-textarea" id="' + prefix + '-goal" rows="2" placeholder="这个项目长期要做成什么样"></textarea></label>' +
      (attach ? '<label class="y17-field"><span>源目录（必填）</span><input class="y17-input" id="pa-dir" data-live data-act="np.check" placeholder="控制主机上已有项目的绝对路径"><small class="y17-muted">从这里取快照；没有核验角色的组织，建档以开环完成结束。</small></label>'
        : '<label class="y17-field"><span>起始文件夹（可选）</span><input class="y17-input" id="pn-dir" placeholder="控制主机上的路径，可以不填"></label>') +
      orgPicker(prefix) + '</div>';
    ui.modal({ title: attach ? '接入已有项目' : '新建项目', wide: true, body, actions: [{ label: attach ? '接入' : '新建项目', kind: 'primary', act: attach ? 'np.attach-do' : 'np.new-do', disabled: true, data: { x: prefix } }, { label: '取消', close: true }] });
    refreshPick(prefix);
  }
  A('np.new', () => projectDialog(false));
  A('np.attach', () => projectDialog(true));
  A('np.check', (el) => {
    const prefix = el.closest('[data-np]').dataset.np;
    const ok = $(prefix + '-name').value.trim() && (prefix === 'pn' || $('pa-dir').value.trim());
    document.querySelector('.y17-modal-foot [data-act]').disabled = !ok;
  });
  function readProject(prefix) {
    return { name: $(prefix + '-name').value.trim(), goal: $(prefix + '-goal').value.trim(), dir: $(prefix + '-dir').value.trim(), org: pickedOrg(prefix) };
  }
  A('np.new-do', () => {
    const p = createProject(readProject('pn'));
    ui.closeModal();
    ui.toast('已新建项目「' + p.name + '」，组织是' + p.composed.formName + '。接着可以新建事项', 'ok');
    Y17.go('#/p/' + p.id);
  });
  A('np.attach-do', () => {
    const p = createProject(readProject('pa'));
    const e = O.ending(p.composed);
    const res = addItem(p, { title: '建档：为已有项目建立基线', text: '接入已有项目，源目录 ' + p.dir + '。请读源目录，建立项目的基线。',
      reason: e.open ? '没有核验角色，建档以开环完成结束；初始 PRD 照常请你确认，确认时看得到没有经过基线核验' : O.sourceReceiver(p.composed, 'intake').name + '在读源目录，基线核验由' + O.verifiers(p.composed)[0].name + '做' });
    ui.closeModal();
    ui.toast(res.ok ? '已接入项目「' + p.name + '」，带一个进行中的建档事项' : '项目已建好，但建档事项建不了：' + res.rejects.join('；'), res.ok ? 'ok' : 'warn');
    Y17.go('#/p/' + p.id);
  });

  // ---------------------------------------------------------------- 新建事项

  A('ni.new', () => {
    const p = H.project(H.pid());
    const body = '<div class="y17-form"><label class="y17-field"><span>原文（必填）</span><textarea class="y17-textarea" id="ni-text" rows="4" data-live data-act="ni.check" placeholder="用你自己的话写想做什么"></textarea></label>' +
      '<label class="y17-field"><span>标题（可选）</span><input class="y17-input" id="ni-title" placeholder="不写就用原文的开头"></label>' +
      '<div class="y17-field"><span>组织（默认本项目的组织，也可以临时选一份，只影响这个事项）</span><div class="y17-org-radios"><label class="y17-org-radio"><input type="radio" name="ni-org" value="" checked data-act="ni.check"><span><strong>本项目的组织：' + esc(p.composed.formName) + '</strong><small>版本 ' + esc(p.version) + '</small></span></label></div>' + Y17.orgpage.catalogHtml({ name: 'ni-org', act: 'ni.check', noLayers: true }) + '</div>' +
      '<div id="ni-info"></div></div>';
    ui.modal({ title: '新建事项', wide: true, body, actions: [{ label: '新建事项', kind: 'primary', act: 'ni.do', disabled: true }, { label: '取消', close: true }] });
    niRefresh();
  });
  function niState() {
    const p = H.project(H.pid());
    const form = (document.querySelector('input[name="ni-org"]:checked') || {}).value || '';
    const info = O.itemOrg(p, form);
    return { p, form, info, text: $('ni-text').value.trim() };
  }
  function niRefresh() {
    const s = niState();
    const c = s.info.c, e = O.ending(c);
    const recv = O.firstReceivers(c).map((d) => d.name + (d.who && d.who.type === 'outsourced' ? '（外包）' : ''));
    let html = '<div class="y17-note is-info" id="ni-recv">这段话先交给：<b>' + esc(recv.join('、') || '没有部门') + '</b>（由事项的来源「你的输入」接它的部门得出）。</div>';
    html += '<p>这个事项怎么结束：<strong id="ni-end">' + esc(e.text) + '</strong></p>';
    if (e.open) html += '<div class="y17-note is-warn" id="ni-open">这个组织没有核验角色核验最后的成果：事项交了完成就以<b>开环完成</b>结束' + (e.outsourced ? '，注明外包' : '') + '，记录上写开环完成，不写放行。</div>';
    if (s.form) html += '<p class="y17-small y17-muted" id="ni-temp">临时选的形态只影响这个事项，项目的组织不变。</p>';
    html += '<p class="y17-small y17-muted">新建时这份组织整份冻结进事项，版本 <code class="y17-code">' + esc(s.info.org.version) + '</code>。</p>';
    if (s.info.rejects.length) html += '<div class="y17-note is-warn" id="ni-reject"><b>现在不能新建事项</b><ul class="y17-org-list is-reject">' + s.info.rejects.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul><small>到组织页里处理。</small></div>';
    $('ni-info').innerHTML = html;
    document.querySelector('.y17-modal-foot [data-act="ni.do"]').disabled = !s.text || s.info.rejects.length > 0;
  }
  A('ni.check', niRefresh);
  A('ni.do', () => {
    const s = niState();
    const title = $('ni-title').value.trim() || s.text.replace(/\s+/g, ' ').slice(0, 14);
    const res = addItem(s.p, { title, text: s.text, form: s.form });
    if (!res.ok) { niRefresh(); return; }
    ui.closeModal();
    ui.toast('已新建事项「' + res.item.title + '」，冻结的组织是「' + res.item.org.formName + '」' + res.item.org.version, 'ok');
    Y17.go('#/p/' + s.p.id + '/w/' + res.item.id);
  });
})();
