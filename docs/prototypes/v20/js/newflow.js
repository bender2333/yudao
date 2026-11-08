// 新建项目、接入已有项目、新建事项：选组织，建在内存里（刷新页面就没有了）。
(function () {
  'use strict';
  const Y20 = window.Y20;
  const O = Y20.org;
  const H = Y20.h;
  const ui = Y20.ui;
  const esc = Y20.esc;
  const X = Y20.EXTRA;
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const A = (name, fn) => Y20.actions.register(name, fn);
  const $ = (id) => document.getElementById(id);
  let counter = 0;

  // ---------------------------------------------------------------- 选组织

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
  // ---------------------------------------------------------------- 往内存里建

  function nowIso(extraMin) { return Y20.time.add(Y20.app.now(), 60 * (extraMin || 0)); }

  function pushEvent(w, p, item, type, label, source, by, detail) {
    const pos = Math.max.apply(null, w.events.map((e) => e.pos)) + 3;
    const e = { key: 'ev-' + pos, project: p.id, item, type, label, source, by, at: nowIso(), detail: detail || null, pos };
    w.events.push(e); w.byKey[e.key] = e;
    return e;
  }

  // 新建事项：合成、校验、冻结。返回 { ok, item } 或 { ok:false, rejects }
  function addItem(p, opts) {
    const w = Y20.W();
    const info = O.itemOrg(p, opts.form || '');
    if (info.rejects.length) return { ok: false, rejects: info.rejects };
    const recv = opts.source ? O.sourceReceiver(info.c, opts.source) : O.firstReceivers(info.c)[0];
    if (!recv) return { ok: false, rejects: ['该事项来源没有接收方'] };
    const n = (w.doorNext[p.id] = (w.doorNext[p.id] || 1));
    w.doorNext[p.id] += 1;
    const it = { id: 'w' + p.id.replace(/\W/g, '') + n, door: (p.letter || 'N') + '-' + n, title: opts.title, color: n % 6, dept: recv.id, status: 'working', round: 1, round_limit: 8, used: 0, limit: 14400,
      reason: opts.reason || (recv.name + '接到输入，正在开始第 1 轮'), created: nowIso(), org: info.org, text: opts.text, source: opts.source || 'input' };
    p.items.unshift(it);
    const inId = 'o-' + it.id + '-in';
    const o = { id: inId, project: p.id, item: it.id, kind: 'input', text: opts.text, from: 'user', to: recv.id, at: nowIso() };
    p.outcomes.push(o);
    const ev = pushEvent(w, p, it.id, '事项创建', '事项「' + it.title + '」建立，门牌 ' + it.door + '，冻结的组织是「' + info.org.formName + '」' + info.org.version, 'rule', '系统');
    w.byKey['door-' + it.id] = ev;
    w.byKey['round-' + it.id] = pushEvent(w, p, it.id, '一轮工作开始', '「' + it.title + '」开始第 1 轮', 'rule', '系统');
    w.byKey['status-' + it.id] = pushEvent(w, p, it.id, '状态变化', '「' + it.title + '」现在的状态：进行中', 'rule', '系统');
    w.byKey[inId] = pushEvent(w, p, it.id, Y20.OUTCOME_KINDS.input, Y20.OUTCOME_KINDS.input + '：' + opts.text, 'user', '用户');
    const ds = p.deptState[recv.id] || (p.deptState[recv.id] = O.idleState(p, recv.id));
    ds.items = (ds.items || []).concat(it.id);
    if (ds.state === 'idle') { ds.state = 'running'; ds.text = (opts.source === 'fault' ? '接到运维发现的故障：' : '接到你的输入：') + it.title; ds.reason = '一轮工作进行中，第 1 轮'; }
    X.slotHolders[p.id] = (X.slotHolders[p.id] || []).concat(it.id);
    p.slots.used = Math.min(p.slots.limit, p.slots.used + 1);
    O.refresh(p);
    return { ok: true, item: it, info };
  }
  Y20.newItem = addItem;

  function createProject(spec) {
    const w = Y20.W();
    counter += 1;
    const id = 'np' + counter;
    const letter = 'HJKLMNPQR'[(counter - 1) % 9];
    const o = spec.org;
    const c0 = O.compose({ form: o.form, changes: o.changes });
    const p = { id, name: spec.name, goal: spec.goal || '（还没有写长期目标）', letter, dir: spec.dir || '', items: [], depts: [], deptState: {}, asks: [], interruptions: [], elapsed: { used: 0, limit: 86400, key: null },
      slots: { used: 0, limit: 3, waiting: 0 }, provider_wait: [], hand: {}, outcomes: [], candidates: [],
      settings: o.from ? clone(o.from.settings) : { dept: {}, roles: {}, nodes: {} },
      org: { form: o.form, changes: clone(o.changes), keys: {}, history: [{ at: nowIso(), by: '你', fromVersion: '', toVersion: O.version(c0), form: o.form, changes: clone(o.changes),
        reason: (o.from ? '建项目时和「' + o.from.name + '」一样' : o.kind === 'form' ? (o.form.endsWith('_preview') ? '建项目时选用设计预览「' : '建项目时选用发布带的「') + c0.formName + '」' : '建项目时选用默认的「产品 · 工程 · 质检」') + (o.layers.length ? '，加上' + o.layers.join('、') : ''),
        diff: ['建项目，选用「' + c0.formName + '」'].concat(o.layers.map((t) => '加上「' + t + '」')).concat(o.from ? ['复制了「' + o.from.name + '」的 ' + O.count(o.changes) + ' 处改动、项目职能设置与项目角色设置；机器授权、执行位置、源目录、MCP 服务器没有复制'] : []) }] } };
    X.ensure(p);
    if (Y20.designPreview) Y20.designPreview.init(p);
    O.refresh(p);
    w.projects.push(p);
    w.doorNext[id] = 1;
    return p;
  }

  Y20.np = { createProject, pickedOrg, attachDo };
  function attachDo(spec) {
    const p = createProject(spec);
    const e = O.ending(p.composed);
    const res = addItem(p, { title: '建档：为已有项目建立基线', text: '接入已有项目，源目录 ' + p.dir + '。请读源目录，建立项目的基线。',
      reason: e.open ? '没有核验角色，建档以开环完成结束；初始 PRD 照常请你确认，确认时看得到没有经过基线核验' : O.sourceReceiver(p.composed, 'intake').name + '在读源目录，基线核验由' + O.verifiers(p.composed)[0].name + '做' });
    ui.closeModal();
    ui.toast(res.ok ? '已接入项目「' + p.name + '」，带一个进行中的建档事项' : '项目已建好，但建档事项建不了：' + res.rejects.join('；'), res.ok ? 'ok' : 'warn');
    Y20.go('#/p/' + p.id);
  }
})();
