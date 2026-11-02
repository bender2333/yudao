// 组织页、部门详情、子组织、加部门、文档视图、采用与历史、事项冻结的组织。逻辑都在 org.js，这里只画和接线。
(function () {
  'use strict';
  const Y17 = window.Y17;
  const O = Y17.org;
  const H = Y17.h;
  const ui = Y17.ui;
  const esc = Y17.esc;
  const X = Y17.EXTRA;

  const SRC = { follow: '跟随发布', changed: '本项目改过', added: '本项目加的', removed: '已去掉' };
  const srcTag = (s) => ui.tag(SRC[s], s);
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const pathOf = (r) => (r.params.path ? r.params.path.split('.') : []);
  const goOrg = (p, path, tail) => '#/p/' + p.id + '/org' + (path.length ? '/s/' + path.join('.') : '') + (tail || '');
  const pidNow = () => H.project(H.pid());
  const small = (cls) => 'y17-btn small' + (cls ? ' ' + cls : '');

  // ---------------------------------------------------------------- 面包屑

  function pathCrumbs(p, path) {
    const out = [];
    const root = O.draft.get(p.id) ? O.draftCompose(O.draft.get(p.id)) : p.composed;
    let node = root;
    path.forEach((id, i) => {
      const d = node && node.depts.find((x) => x.id === id);
      out.push('<button type="button" class="y17-crumb" data-go="#/p/' + p.id + '/org' + (i ? '/s/' + path.slice(0, i).join('.') : '') + '/d/' + id + '">' + esc(d ? d.name : id) + '</button>');
      out.push('<button type="button" class="y17-crumb" data-go="' + goOrg(p, path.slice(0, i + 1)) + '">内部</button>');
      node = d && d.sub;
    });
    return out;
  }
  function crumbs(r, p) {
    const orgLink = '<button type="button" class="y17-crumb" data-go="#/p/' + p.id + '/org">组织</button>';
    if (r.name === 'item-org') { const it = H.item(p, r.params.item); return [it ? '<button type="button" class="y17-crumb" data-go="#/p/' + p.id + '/w/' + it.id + '">' + esc(it.title) + '</button>' : '', '<strong>这个事项用的组织</strong>']; }
    const path = pathOf(r);
    if (r.name === 'org') return ['<strong>组织</strong>'];
    if (r.name === 'org-sub') { const c = pathCrumbs(p, path); c[c.length - 1] = c[c.length - 1].replace('class="y17-crumb"', 'class="y17-crumb is-current"'); return [orgLink].concat(c); }
    const root = O.draft.get(p.id) ? O.draftCompose(O.draft.get(p.id)) : p.composed;
    const node = O.nodeAt(root, path);
    const d = node && node.depts.find((x) => x.id === r.params.dept);
    if (r.name === 'org-dept') return [orgLink].concat(pathCrumbs(p, path), ['<strong>' + esc(d ? d.name : r.params.dept) + '</strong>']);
    if (r.name === 'org-new') return [orgLink].concat(pathCrumbs(p, path), ['<strong>加部门</strong>']);
    return ['<strong>组织</strong>'];
  }
  Y17.orgpage = { crumbs };

  // ---------------------------------------------------------------- 校验结果（草稿里常驻）

  function checkPanel(ck) {
    const v = ck.v;
    const fixes = (x) => (x.source ? '<span class="y17-org-fix">改给：' + x.options.map((o) => '<button type="button" class="y17-btn small" data-act="og.src-fix" data-s="' + x.source + '" data-d="' + o.id + '">' + esc(o.name) + '</button>').join('') + '</span>' : '');
    const rej = v.rejects.length ? '<ul class="y17-org-list is-reject">' + v.rejects.map((x) => '<li data-rule="r' + x.rule + '"><b>拒绝</b> ' + esc(x.text) + fixes(x) + '<small>' + esc(O.REJECT_TITLES[x.rule]) + '</small></li>').join('') + '</ul>' : '';
    const warn = v.warns.length ? '<ul class="y17-org-list is-warn">' + v.warns.map((x) => '<li data-rule="w' + x.rule + '"><b>提醒</b> ' + esc(x.text) + '</li>').join('') + '</ul>' : '';
    const ok = !v.rejects.length ? '<p class="y17-org-pass">' + ui.status('succeeded', '过了结构校验，可以采用') + '</p>' : '';
    const notes = (v.notes || []).map((t) => '<p class="y17-small y17-muted">' + esc(t) + '</p>').join('');
    return '<div class="y17-org-check">' + ok + rej + warn + notes +
      '<p class="y17-org-end"><span class="y17-muted">这样改以后事项怎么结束</span><strong id="org-end">' + esc(v.ending.text) + '</strong></p></div>';
  }

  function barHtml(p, d, extra) {
    const ck = O.draftCheck(p, d);
    const bad = ck.v.rejects.length || (extra && extra.docInvalid);
    return '<div class="y17-org-bar"><div class="y17-org-bar-head"><strong class="y17-org-draft-title">草稿，还没有生效</strong><span class="y17-muted">改动只对之后新建的事项生效；草稿存在这个浏览器里，别的电脑看不到。</span>' +
      '<span class="y17-org-bar-btns">' + ui.button({ label: '编辑定义', kind: 'small', act: 'og.doc', icon: 'step' }) + ui.button({ label: '放弃草稿', kind: 'small', act: 'og.discard' }) +
      '<button type="button" class="y17-btn small primary" id="og-adopt-btn" data-act="og.adopt"' + (bad ? ' disabled title="有拒绝项，不能采用"' : '') + '>采用</button></span></div>' +
      (d.rebased ? '<div class="y17-note is-info">你看到的组织版本已经变了（别处采用了新的组织，或发布升级了形态），草稿已经按新的版本 <code class="y17-code">' + esc(p.version) + '</code> 重新校验。 ' + ui.button({ label: '知道了', kind: 'small', act: 'og.ack' }) + '</div>' : '') +
      checkPanel(ck) + '</div>';
  }

  // ---------------------------------------------------------------- 组织页

  function viewOf(p, r) {
    const path = pathOf(r);
    const d = O.draft.sync(p);
    const root = d ? O.draftCompose(d) : p.composed;
    return { path, draft: d, root, node: O.nodeAt(root, path), formId: d ? d.form : p.org.form };
  }
  const gate = (t, s) => '<div class="y17-gate"><h1>' + esc(t) + '</h1><p class="y17-muted">' + esc(s) + '</p></div>';

  function modelCell(p, d, depth, path) {
    const pending = (O.draft.get(p.id) || {}).pending;
    const m = depth > 0 ? O.nodeModel(p, path.concat(d.id), pending) : O.modelOf(p, d.id, pending);
    return m ? ui.code(m) : '<span class="y17-warn-text">还没有可用的模型</span>';
  }

  function deptTable(p, v, mode) {
    const c = v.node, depth = c.depth, rot = c.rotation;
    const editing = mode === 'draft';
    const frozen = mode === 'frozen';
    const link = (d) => (frozen ? esc(d.name) : '<button type="button" class="y17-link" data-go="#/p/' + p.id + '/org' + (v.path.length ? '/s/' + v.path.join('.') : '') + '/d/' + d.id + '">' + esc(d.name) + '</button>');
    const marks = (d) => [d.verifies ? ui.tag('核验角色', 'new') : '', d.who && d.who.type === 'outsourced' ? ui.tag('外包 · ' + (d.who.agent || '未选'), 'changed') : '', d.who && d.who.type === 'suborg' ? ui.tag('内部是子组织', 'added') : ''].join(' ');
    const verCell = (d) => {
      const parts = [];
      if (d.verifies) { const t = c.depts.find((x) => x.id === d.verifies.dept); parts.push('核验「' + esc(t ? t.name : '？') + '」的「' + esc(O.kindName(c, d.verifies.kind)) + '」'); }
      c.depts.filter((x) => x.verifies && x.verifies.dept === d.id && d.produces.includes(x.verifies.kind)).forEach((x) => parts.push('由「' + esc(x.name) + '」核验'));
      return parts.length ? '<div class="y17-cell-stack">' + parts.map((t) => '<span>' + t + '</span>').join('') + '</div>' : '<span class="y17-muted">没有人核验，也不核验别人</span>';
    };
    const recv = (d) => (d.receives || []).map((s) => s.name);
    const when = (d) => {
      const r = recv(d), w = d.watches.map((k) => O.kindName(c, k));
      if (rot === 'direct') return r.length ? '接「' + esc(r.join('」「')) + '」这' + (r.length > 1 ? '几种' : '一种') + '来源' + (c.depth ? '' : '，也在收到指导、询问时') : '在收到指导、询问时' + (w.length ? '；关注：' + esc(w.join('、')) : '');
      return (r.length ? '接来源「' + esc(r.join('」「')) + '」' + (w.length ? '<br>' : '') : '') + (w.length ? '关注：' + esc(w.join('、')) : r.length ? '' : '<span class="y17-muted">不关注任何成果</span>');
    };
    const cols = [
      { label: v.path.length ? '角色' : '部门', render: (d) => link(d) + ' ' + marks(d) + '<br><small class="y17-muted">' + esc(d.who && d.who.type === 'suborg' && d.sub ? '内部：' + d.sub.depts.map((x) => x.name).join('、') : d.roles.join('、')) + '</small>' },
      { label: '目标', render: (d) => esc(d.goal) || '<span class="y17-warn-text">还没写</span>' },
      { label: '什么时候开工', render: when },
      { label: '交出什么', render: (d) => (d.produces.length ? esc(d.produces.map((k) => O.kindName(c, k)).join('、')) : '<span class="y17-muted">不交出成果，只回答询问</span>') }
    ];
    if (rot === 'direct') cols.push({ label: '谁交完成', render: (d) => (d.completes ? ui.status('succeeded', '交完成') : '<span class="y17-muted">—</span>') });
    else cols.push({ label: '谁核验它 · 它核验谁', render: verCell });
    if (rot === 'pool') cols.push({ label: '工作单元的大小', render: () => esc(c.unit || '未写') });
    cols.push({ label: '模型', render: (d) => modelCell(p, d, depth, v.path) });
    cols.push({ label: '来源', render: (d) => srcTag(d.src) });
    if (editing) {
      cols.push({ label: '操作', className: 'y17-col-actions', render: (d) => '<div class="y17-row">' + ui.button({ label: '改名', kind: 'small', act: 'og.rename', data: { d: d.id, path: v.path.join('.') } }) + ui.button({ label: '去掉', kind: 'small danger', act: 'og.remove', data: { d: d.id, path: v.path.join('.') } }) + '</div>' });
    }
    let html = ui.table({ className: 'y17-org-table', columns: cols, rows: c.depts, rowAttrs: (d) => 'data-dept="' + esc(d.id) + '"', empty: '没有部门' });
    if (c.removedDepts.length) {
      const rows = c.removedDepts.map((d) => '<tr class="is-removed" data-dept="' + esc(d.id) + '"><td colspan="2"><s>' + esc(d.name) + '</s> ' + ui.tag('已去掉') + '</td><td colspan="' + (cols.length - 2) + '"><span class="y17-muted">灰着显示，采用以后新建的事项没有这个部门；还在跑的事项不受影响。</span> ' +
        (editing ? ui.button({ label: '恢复', kind: 'small', act: 'og.restore-dept', data: { d: d.id, path: v.path.join('.') } }) : '') + '</td></tr>').join('');
      html += '<div class="y17-table-wrap"><table class="y17-table y17-org-removed"><tbody>' + rows + '</tbody></table></div>';
    }
    return html;
  }

  function flowBlock(c) {
    const lines = O.flow(c);
    return ui.block({ title: '成果怎么走', subtitle: '由「关注哪些成果」和「谁核验谁」得出',
      body: lines.length ? '<ol class="y17-flow">' + lines.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ol>' : ui.empty('还没有成果在流转') });
  }

  function observersBlock(p, c, editing) {
    if (!c.observers.length) return ui.block({ title: '观察者', body: ui.empty('这份形态没有观察者。观察者不算部门，不能核验，开关与读取范围写在项目的组织里。') });
    const rows = c.observers;
    const table = ui.table({
      className: 'y17-org-obs',
      columns: [
        { label: '名字', render: (o) => esc(o.name) + ' ' + (o.src === 'changed' ? srcTag('changed') : '') },
        { label: '看什么（读取范围）', render: (o) => (editing ? '<select class="y17-select" data-act="og.obs-scope" data-o="' + o.id + '">' + O.OBSERVERS[o.id].scopes.map((s) => '<option' + (o.scope === s ? ' selected' : '') + '>' + esc(s) + '</option>').join('') + '</select>' : esc(o.scope)) },
        { label: '产出什么', render: (o) => esc(o.makes) },
        { label: '开或关', render: (o) => (editing ? '<label class="y17-field is-inline"><input type="checkbox" data-act="og.obs-on" data-o="' + o.id + '"' + (o.on ? ' checked' : '') + '><span>' + (o.on ? '开' : '关') + '</span></label>' : ui.status(o.on ? 'running' : 'idle', o.on ? '开' : '关')) },
        { label: '最近的产出', render: (o) => esc((p.observerRecent && p.observerRecent[o.id]) || (o.on ? o.recent : '关着，没有产出')) + ' ' + H.link('#/sys/tools', '看系统页') }
      ], rows, rowAttrs: (o) => 'data-obs="' + o.id + '"'
    });
    return ui.block({ title: '观察者', subtitle: '观察者在事项外面读项目现在的组织，开关与读取范围采用以后立即生效，不随事项冻结；观察者的实现随发布，这里只改开关与读取范围', body: table });
  }

  function historyBlock(p, editing) {
    const hs = p.org.history.map((h, i) => ({ h, i })).reverse();
    const table = ui.table({
      className: 'y17-org-history',
      columns: [
        { label: '时间 · 谁', render: (x) => esc(ui.time(x.h.at)) + '<br><small class="y17-muted">' + esc(x.h.by) + '</small>' },
        { label: '版本', render: (x) => (x.h.fromVersion ? ui.code(x.h.fromVersion) + ' → ' : '') + ui.code(x.h.toVersion) + (x.i === p.org.history.length - 1 ? ' ' + ui.tag('现在') : '') },
        { label: '理由', render: (x) => esc(x.h.reason) },
        { label: '差异', render: (x) => '<ul class="y17-org-diff">' + x.h.diff.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul>' },
        { label: '操作', className: 'y17-col-actions', render: (x) => (x.i === p.org.history.length - 1 ? '' : ui.button({ label: '改回这一条', kind: 'small', act: 'og.revert', data: { i: x.i } })) }
      ], rows: hs
    });
    return ui.block({ id: 'org-history', title: '历史', subtitle: '每次采用的时间、谁、原版本、新版本、理由、差异。改回就是把那一条的形态与改动再采用一次，照常合成、校验。', body: table });
  }

  function candidatesBlock(p) {
    const list = p.candidates || [];
    if (!list.length) return '';
    const d = O.draft.get(p.id);
    const cards = list.map((cd) => {
      const merged = clone(p.org.changes);
      ['observers', 'depts', 'outcomes'].forEach((k) => { if (cd.changes[k]) merged[k] = Object.assign({}, merged[k] || {}, cd.changes[k]); });
      const diff = O.diff(p.composed, O.compose({ form: p.org.form, changes: merged }));
      return '<article class="y17-org-cand" data-cand="' + cd.id + '"><header><strong>' + esc(cd.title) + '</strong> ' + ui.tag('系统提的候选', 'new') + '<span class="y17-muted y17-small">来自' + esc(cd.from) + ' · ' + esc(ui.time(cd.at)) + '</span></header>' +
        '<h4>差异</h4><ul class="y17-org-diff">' + diff.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul>' +
        '<h4>证据</h4><p>' + esc(cd.evidence) + '</p><h4>对照</h4><p>' + ui.status('succeeded', '已通过对照') + ' ' + esc(cd.comparison) + '</p>' +
        '<div class="y17-row">' + (d && d.cand === cd.id ? ui.status('done', '已放进草稿') : ui.button({ label: '放进草稿', kind: 'small primary', act: 'og.cand', data: { id: cd.id } })) + '<span class="y17-small y17-muted">通过对照以后，走和你自己改一样的「采用」命令。</span></div></article>';
    }).join('');
    return ui.block({ id: 'org-cands', title: '待采用的候选', subtitle: '系统根据运行证据提出的修改，写明差异与证据；不会自己生效', body: cards });
  }

  function oldItems(p) {
    const core = O.coreDigest(p.composed);
    return p.items.filter((i) => O.unfinished(i) && i.org && i.org.core !== core);
  }

  function lastItemDiff(p) {
    const items = p.items.slice().sort((a, b) => (b.created || '').localeCompare(a.created || ''));
    const last = items[0];
    if (!last || !last.org || last.org.core === O.coreDigest(p.composed)) return '';
    const lines = O.diff(last.org.composed, p.composed);
    return '<div class="y17-note is-info" id="org-vs-last"><b>和这个项目上一个事项（' + esc(last.title) + '）用的组织相比，有这些不同</b><ul class="y17-org-diff">' + lines.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul>' +
      '<small>发布升级以后，跟随发布的项下一个事项自动用上新内容；这里比较的是两份合成结果。</small></div>';
  }

  // 小图：来源 → 接它的部门 → 关注关系 → 核验 → 结束，和「成果怎么走」是同一份计算
  function diagram(c) {
    const fp = O.flowParts(c), e = O.ending(c), g = O.sourceGroups(c);
    const box = (title, inner, cls) => '<div class="y17-dg-box' + (cls ? ' ' + cls : '') + '"><b>' + esc(title) + '</b>' + inner + '</div>';
    const chips = (list, cls) => list.map((t) => '<span class="y17-dg-chip' + (cls ? ' ' + cls : '') + '">' + esc(t) + '</span>').join('');
    const srcs = c.sources.map((s) => '<span class="y17-dg-chip' + (c.depts.some((d) => d.id === s.to) ? '' : ' is-bad') + '">' + esc(s.name) + '</span>').join('');
    const recvs = g.map((x) => '<span class="y17-dg-chip is-dept' + (x.dept ? '' : ' is-bad') + '">' + esc(x.dept ? x.dept.name + (x.dept.who && x.dept.who.type === 'outsourced' ? '（外包）' : '') : '没有部门接') + '</span>').join('');
    const rel = fp.out.length ? fp.out.map((t) => '<span class="y17-dg-line">' + esc(t.replace(/^[^→]*、[^→]*→ /, '').replace(/^你的输入 → |^建档 → |^上一层交来的任务 → /, '')) + '</span>').join('') : '<span class="y17-muted">没有成果在流转</span>';
    const ver = fp.ver.length ? fp.ver.map((t) => '<span class="y17-dg-line">' + esc(t) + '</span>').join('') : '<span class="y17-muted">没有核验角色</span>';
    const end = '<span class="y17-dg-chip' + (e.open ? ' is-open' : ' is-ok') + '">' + esc(e.open ? '开环完成' + (e.outsourced ? '（注明外包）' : '') : '放行才结束') + '</span>';
    const arrow = '<span class="y17-dg-arrow" aria-hidden="true">→</span>';
    return '<div class="y17-dg" id="org-diagram" role="img" aria-label="事项的来源、接它的部门、关注关系、核验、结束">' +
      box('事项的来源', srcs) + arrow + box('接它的部门', recvs) + arrow + box('关注关系', rel) + arrow + box('核验', ver) + arrow + box('结束', end) + '</div>';
  }
  function questions(c) {
    const a = O.answers(c);
    return '<dl class="y17-qa" id="org-qa"><div><dt>事项从哪来</dt><dd id="org-q-from">' + esc(a.from) + '</dd></div><div><dt>谁做</dt><dd id="org-q-who">' + esc(a.who) + '</dd></div>' +
      '<div><dt>谁核验</dt><dd id="org-q-verify">' + esc(a.verify) + '</dd></div><div><dt>怎么结束</dt><dd id="org-q-end">' + esc(a.end) + '</dd></div></dl>';
  }
  // 改接来源的部门：每一种来源一行下拉，走草稿、校验、采用同一条路
  function sourceRows(c, path) {
    return '<div class="y17-srcrows" id="org-sources"><b>事项的来源由谁接</b> <span class="y17-small y17-muted">来源的种类由发布给出，只能改接它的部门，不能增减</span>' +
      c.sources.map((s) => '<label class="y17-field is-inline"><span>' + esc(s.name) + '</span><select class="y17-select" data-act="og.src" data-s="' + s.id + '" data-path="' + path.join('.') + '">' +
        (c.depts.some((d) => d.id === s.to) ? '' : '<option value="" selected>（没有部门接）</option>') + c.depts.map((d) => '<option value="' + d.id + '"' + (d.id === s.to ? ' selected' : '') + '>' + esc(d.name) + '</option>').join('') + '</select>' + (s.src === 'changed' ? ' ' + srcTag('changed') : '') + '</label>').join('') + '</div>';
  }

  function headBlock(p, v, ck) {
    const c = v.node;
    const sub = v.path.length > 0;
    const n = O.count(sub ? subChanges(p, v) : (v.draft ? v.draft.changes : p.org.changes));
    const old = oldItems(p);
    const end = (ck ? ck.v : O.validate(c, O.ctxFor(p))).ending;
    const base = O.status(p);
    let title = sub ? '子组织：' + v.path.map((id, i) => { const x = O.nodeAt(v.root, v.path.slice(0, i)); const d = x && x.depts.find((y) => y.id === id); return d ? d.name : id; }).join(' › ') + ' › 内部' : '组织';
    const kv = ui.kv([
      ['用哪份形态', '<strong>' + esc(c.formName) + '</strong> ' + (n ? '<span class="y17-tag is-changed">改过 ' + n + ' 处</span>' : '<span class="y17-tag is-follow">全部跟随发布</span>')],
      ['版本', ui.code(O.version(c)) + (sub ? '' : ' <small class="y17-muted">合成结果的内容摘要</small>')],
      ['轮转方式', '<strong>' + esc(O.ROTATIONS[c.rotation] || c.rotation) + '</strong> <small class="y17-muted">' + esc(O.ROTATION_NOTE[c.rotation] || '') + '</small>']
    ], 'is-rows y17-org-kv');
    const buttons = v.draft ? '' : ui.button({ label: '修改', kind: 'primary', act: 'og.start', icon: 'step' }) + (sub ? '' : ui.button({ label: '换一份', act: 'og.switch' }));
    const hint = sub ? '' : '<p class="y17-small y17-muted" id="org-hint">改动只对之后新建的事项生效。' + (old.length ? '现在有 <button type="button" class="y17-link" data-act="og.old" id="org-old-link">' + old.length + ' 个事项</button>在按旧组织跑。' : '现在没有事项在按旧组织跑。') + '</p>';
    const open = end.open && !sub && !v.draft && c.rotation === 'direct' && base.ok ? '<div class="y17-note is-warn" id="org-open-note"><b>提醒：</b>这个组织没有核验角色，事项交完成就以开环完成结束' + (end.outsourced ? '，注明外包' : '') + '。加一个核验角色（在「修改」里「加部门」，从发布的部门里选质检），交完成以后就会等它放行。</div>' : '';
    const broken = !sub && !v.draft && !base.ok ? '<div class="y17-note is-warn" id="org-broken"><b>发布的改动与本项目的改动合不到一起</b><ul class="y17-org-list is-reject">' + base.v.rejects.map((x) => '<li data-rule="r' + x.rule + '">' + esc(x.text) + '</li>').join('') +
      '</ul><small>新建事项暂时不可用，会给出同样的原因；进行中的事项不受影响。请在草稿里处理，处理好再采用。</small> ' + ui.button({ label: '在草稿里处理', kind: 'small primary', act: 'og.start' }) + '</div>' : '';
    const flow = O.flow(c);
    const flowHtml = '<h3 class="y17-h3" id="org-flow-title">成果怎么走</h3>' + (flow.length ? '<ol class="y17-flow" id="org-flow">' + flow.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ol>' : ui.empty('还没有成果在流转'));
    return ui.block({ id: 'org-head', title, subtitle: sub ? '' : p.name, actions: ui.tag('新增', 'new') + buttons,
      body: questions(c) + diagram(c) + flowHtml + (v.draft ? sourceRows(c, v.path) : '') + kv + hint + open + broken + (sub || v.draft ? '' : lastItemDiff(p)) });
  }
  // 子组织自己的改动数：沿路径往下取嵌套的改动
  function subChanges(p, v) {
    let ch = v.draft ? v.draft.changes : p.org.changes;
    v.path.forEach((id) => { const e = (ch.depts || {})[id]; ch = e && e.who && e.who.changes ? e.who.changes : {}; });
    return ch;
  }

  function orgPage(ctx, p) {
    const r = ctx.route;
    const v = viewOf(p, r);
    if (!v.node) return gate('找不到这个子组织', '路径对不上：这个部门现在没有指向子组织。');
    const ck = v.draft ? O.draftCheck(p, v.draft) : null;
    const docMode = v.draft && r.query.view === 'doc' && !v.path.length;
    const editing = Boolean(v.draft);
    const mode = editing ? 'draft' : 'view';
    const bar = '<div id="org-bar">' + (v.draft ? barHtml(p, v.draft) : '') + '</div>';
    if (docMode) return '<div class="y17-page y17-org">' + bar + docView(p, v) + '</div>';
    const addBtn = editing ? ui.button({ label: '加部门', kind: 'small primary', icon: 'plus', go: goOrg(p, v.path, '/new') }) : '';
    return '<div class="y17-page y17-org">' + bar + headBlock(p, v, ck) +
      ui.block({ id: 'org-depts', title: v.path.length ? '角色' : '部门', subtitle: v.path.length ? '每一行是一个角色；点一行进角色详情' : '点一行进部门详情；观察者不算部门，在下面单独列出', actions: addBtn, body: deptTable(p, v, mode) }) +
      (v.path.length ? '' : observersBlock(p, v.node, editing) + candidatesBlock(p) + historyBlock(p, editing)) + '</div>';
  }
  Y17.views.register('org', { render: orgPage });
  Y17.views.register('org-sub', { render: orgPage });

  // ---------------------------------------------------------------- 文档视图

  const docText = (p, v) => JSON.stringify(O.toDoc(v.draft.changes, O.form(v.draft.form)), null, 2);
  function docView(p, v) {
    const c = v.root;
    return ui.block({ id: 'org-doc', title: '编辑定义', subtitle: '左边是本项目的改动（只写和形态不同的项），右边是合成结果，只读。和表单过同一套校验。',
      actions: ui.button({ label: '回到表单', kind: 'small', go: '#/p/' + p.id + '/org' }),
      body: '<div class="y17-doc"><div class="y17-doc-col"><h3 class="y17-h3">本项目的改动</h3><textarea id="doc-edit" class="y17-textarea y17-doc-text" data-live data-act="og.doc-edit" spellcheck="false" rows="22">' + esc(docText(p, v)) + '</textarea>' +
        '<div id="doc-err" class="y17-small"></div><p class="y17-small y17-muted">字段名认不出的，会按「未知的字段」拒绝。要去掉的部门写「去掉」: true；新增写「新增」: true 并写全部内容。</p></div>' +
        '<div class="y17-doc-col"><h3 class="y17-h3">合成结果</h3><pre id="doc-result" class="y17-pre y17-doc-result">' + esc(JSON.stringify(O.resultDoc(c), null, 2)) + '</pre></div></div>' });
  }
  Y17.actions.register('og.doc', () => { const p = pidNow(); O.draft.start(p); Y17.go('#/p/' + p.id + '/org?view=doc'); });
  Y17.actions.register('og.doc-edit', (el) => {
    const p = pidNow(), d = O.draft.start(p), err = document.getElementById('doc-err');
    let doc;
    try { doc = JSON.parse(el.value); } catch (e) {
      err.innerHTML = '<span class="y17-warn-text">文档的 JSON 格式有误（' + esc(e.message) + '），草稿保持上一次合法的内容，暂时不能采用。</span>';
      document.getElementById('org-bar').innerHTML = barHtml(p, d, { docInvalid: true });
      return;
    }
    err.textContent = '';
    const parsed = O.fromDoc(doc, O.form(d.form));
    d.changes = parsed.changes;
    O.draft.set(p.id, d);
    document.getElementById('doc-result').textContent = JSON.stringify(O.resultDoc(O.draftCompose(d)), null, 2);
    document.getElementById('org-bar').innerHTML = barHtml(p, d);
  });

  // ---------------------------------------------------------------- 草稿的动作

  function mut(fn) {
    const p = pidNow(), d = O.draft.start(p);
    fn(d, p);
    O.draft.set(p.id, d);
    Y17.rerender();
  }
  const A = (name, fn) => Y17.actions.register(name, fn);
  const pathFrom0 = (el) => (el.dataset.path ? el.dataset.path.split('.') : []);
  A('og.start', () => { const p = pidNow(); O.draft.start(p); Y17.rerender(); });
  A('og.ack', () => mut((d) => { d.rebased = false; }));
  A('og.discard', () => { const p = pidNow(); O.draft.clear(p.id); ui.toast('已放弃草稿，组织还是 ' + p.version + ' 那一版', 'ok'); Y17.go('#/p/' + p.id + '/org'); });
  A('og.rename', (el) => {
    const p = pidNow(), v = O.draftCompose(O.draft.get(p.id)), node = O.nodeAt(v, el.dataset.path ? el.dataset.path.split('.') : []);
    const d = node.depts.find((x) => x.id === el.dataset.d);
    ui.modal({ title: '改名：' + d.name, body: '<div class="y17-form"><label class="y17-field"><span>显示名</span><input class="y17-input" id="og-name" value="' + esc(d.name) + '"></label><p class="y17-small y17-muted">只改显示名，部门的身份不变；全站一起变，改了名的部门仍然跟随原来那一行的模型设置。</p></div>',
      actions: [{ label: '改名', kind: 'primary', act: 'og.rename-do', data: { d: d.id, path: el.dataset.path }, close: true }, { label: '取消', close: true }] });
  });
  A('og.rename-do', (el) => {
    const name = document.getElementById('og-name').value.trim();
    if (!name) { ui.toast('显示名不能是空的', 'warn'); return; }
    mut((d) => O.setField(d.changes, d.form, el.dataset.path ? el.dataset.path.split('.') : [], 'depts', el.dataset.d, 'name', name));
  });
  A('og.remove', (el) => mut((d) => O.removeDept(d.changes, d.form, el.dataset.path ? el.dataset.path.split('.') : [], el.dataset.d)));
  A('og.restore-dept', (el) => mut((d) => O.restoreDept(d.changes, d.form, el.dataset.path ? el.dataset.path.split('.') : [], el.dataset.d)));
  A('og.src', (el) => mut((d) => { if (el.value) O.setSource(d.changes, d.form, pathFrom0(el), el.dataset.s, el.value); }));
  A('og.src-fix', (el) => mut((d) => O.setSource(d.changes, d.form, [], el.dataset.s, el.dataset.d)));
  A('og.obs-on', (el) => mut((d) => O.setField(d.changes, d.form, [], 'observers', el.dataset.o, 'on', el.checked)));
  A('og.obs-scope', (el) => mut((d) => O.setField(d.changes, d.form, [], 'observers', el.dataset.o, 'scope', el.value)));
  A('og.cand', (el) => {
    const p = pidNow(), cd = p.candidates.find((x) => x.id === el.dataset.id);
    mut((d) => {
      ['observers', 'depts', 'outcomes'].forEach((k) => { if (cd.changes[k]) d.changes[k] = Object.assign({}, d.changes[k] || {}, clone(cd.changes[k])); });
      d.cand = cd.id;
    });
    ui.toast('已把候选放进草稿，写理由后采用', 'ok');
  });
  A('og.revert', (el) => {
    const p = pidNow(), h = p.org.history[Number(el.dataset.i)];
    O.draft.set(p.id, { base: p.version, form: h.form, changes: clone(h.changes), pending: {}, rebased: false, revertOf: h.toVersion });
    ui.toast('已把这一条（' + h.toVersion + '）的形态与改动放进草稿，写理由后采用', 'ok');
    Y17.go('#/p/' + p.id + '/org');
    Y17.rerender();
  });
  A('og.old', () => {
    const p = pidNow(), old = oldItems(p);
    ui.modal({ title: '在按旧组织跑的事项', wide: true, body: ui.table({ columns: [
      { label: '事项', render: (i) => H.dot(i) + ' ' + H.link('#/p/' + p.id + '/w/' + i.id, i.title) },
      { label: '状态', render: (i) => H.status(i) },
      { label: '冻结的组织', render: (i) => esc(i.org.formName) + ' ' + ui.code(i.org.version) + ' · ' + H.link('#/p/' + p.id + '/w/' + i.id + '/org', '看那一份') }
    ], rows: old, empty: '没有' }) + '<p class="y17-small y17-muted">事项走到一半不能换人，所以按建立时那份组织跑完；之后新建的事项用现在的。</p>', actions: [{ label: '关闭', close: true }] });
  });

  // 目录：五份形态、两个层；换一份和新建项目共用。radio 的 name、点选时的动作由调用方给
  function catalogHtml(opts) {
    const cat = O.CATALOG();
    const qa = (a) => '<dl class="y17-cat-qa"><div><dt>事项从哪来</dt><dd>' + esc(a.from) + '</dd></div><div><dt>谁做</dt><dd>' + esc(a.who) + '</dd></div><div><dt>谁核验</dt><dd>' + esc(a.verify) + '</dd></div><div><dt>怎么结束</dt><dd>' + esc(a.end) + '</dd></div></dl>';
    const forms = cat.forms.map((f) => {
      const cur = f.id === opts.currentId;
      return '<label class="y17-org-radio y17-cat-card' + (f.selectable ? '' : ' is-reserved') + '" data-cat="' + f.id + '"' + (f.selectable ? '' : ' title="预留：' + f.stage + '，现在不能选"') + '><input type="radio" name="' + opts.name + '" value="' + f.id + '"' +
        (f.selectable && (opts.checkedId === f.id) ? ' checked' : '') + (!f.selectable || (cur && opts.disableCurrent) ? ' disabled' : '') + ' data-act="' + opts.act + '"><span><span class="y17-org-radio-title"><strong>' + esc(f.name) + '</strong>' +
        (cur && opts.currentTag ? ui.tag(opts.currentTag) : '') + (f.selectable ? '' : '<span class="y17-side-stage">' + f.stage + '</span>') + '</span><small>' + esc(f.note) + '</small>' + qa(f.a) + '</span></label>';
    }).join('');
    const layers = cat.layers.map((l) => '<div class="y17-org-radio y17-cat-card is-layer" data-cat="' + l.id + '"><span><span class="y17-org-radio-title"><strong>' + esc(l.name) + '</strong>' + ui.tag('层，不是形态') + '</span><small>' + esc(l.note) + '</small>' + qa(l.a) + '</span></div>').join('');
    return '<div class="y17-cat"><div class="y17-org-radios" id="y17-cat-forms">' + forms + '</div>' + (opts.noLayers ? '' : '<h4 class="y17-cat-h">两个层：能叠在任何一份形态上</h4><div class="y17-org-radios" id="y17-cat-layers">' + layers + '</div>') + '</div>';
  }
  Y17.orgpage.catalogHtml = catalogHtml;

  // 换一份：打开目录
  A('og.switch', () => {
    const p = pidNow(), d = O.draft.get(p.id);
    const cur = d ? d.form : p.org.form;
    const lost = O.diff(O.compose({ form: cur, changes: {} }), O.compose({ form: cur, changes: d ? d.changes : p.org.changes }));
    ui.modal({ title: '换一份', wide: true, body: '<div class="y17-form"><p class="y17-small y17-muted">' + ui.tag('新增', 'new') + ' 目录：五份形态、两个层，每一级回答四个问题。</p>' + catalogHtml({ name: 'og-form', act: 'og.switch-pick', currentId: cur, currentTag: '现在用的', disableCurrent: true }) + '<div id="og-lost" class="y17-note is-warn"><b>换了以后本项目的改动清空</b>' +
      (lost.length ? '<p>现在的 ' + lost.length + ' 项改动会丢掉：</p><ul class="y17-org-diff">' + lost.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul>' : '<p>现在没有本项目的改动，什么也不会丢。</p>') +
      '<small>历史里还在，之后可以改回。换了以后先进草稿，写理由采用才生效。</small></div></div>', actions: [{ label: '换成所选的形态，进草稿', kind: 'primary', act: 'og.switch-do', close: true, disabled: true }, { label: '取消', close: true }] });
  });
  A('og.switch-pick', () => { const b = document.querySelector('[data-act="og.switch-do"]'); if (b) b.disabled = false; });
  A('og.switch-do', () => {
    const pick = document.querySelector('input[name="og-form"]:checked');
    if (!pick) return;
    const p = pidNow();
    O.draft.set(p.id, { base: p.version, form: pick.value, changes: {}, pending: {}, rebased: false });
    Y17.rerender();
  });

  // 采用
  A('og.adopt', () => {
    const p = pidNow(), d = O.draft.get(p.id);
    if (!d) return;
    d.key = d.key || ('cmd-' + Date.now().toString(36));
    O.draft.set(p.id, d);
    const ck = O.draftCheck(p, d);
    const diff = O.diff(p.composed, ck.c);
    const body = '<div class="y17-form"><div><h3 class="y17-h3">差异（和现在的组织比）</h3>' + (diff.length ? '<ul class="y17-org-diff" id="adopt-diff">' + diff.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul>' : '<p class="y17-muted">没有差异。</p>') + '</div>' +
      (ck.v.warns.length ? '<div><h3 class="y17-h3">提醒（不挡采用）</h3><ul class="y17-org-list is-warn">' + ck.v.warns.map((x) => '<li>' + esc(x.text) + '</li>').join('') + '</ul></div>' : '') +
      '<p><span class="y17-muted">这样改以后事项怎么结束：</span><strong>' + esc(ck.v.ending.text) + '</strong></p>' +
      '<label class="y17-field"><span>理由（必填）</span><textarea class="y17-textarea" id="adopt-reason" rows="3" placeholder="为什么要这样改"></textarea></label>' +
      '<p class="y17-small y17-muted">你看到的组织版本是 ' + esc(d.base) + '。采用写成项目流的一条事件，范围只有这个项目。</p><div id="adopt-err" class="y17-warn-text"></div></div>';
    ui.modal({ title: '采用这份组织', wide: true, body, actions: [{ label: '确认采用', kind: 'primary', act: 'og.adopt-do' }, { label: '取消', close: true }] });
  });
  A('og.adopt-do', () => {
    const p = pidNow(), d = O.draft.get(p.id);
    const res = O.adopt(p, { base: d.base, form: d.form, changes: d.changes, pending: d.pending, reason: document.getElementById('adopt-reason').value, key: d.key });
    if (!res.ok) { document.getElementById('adopt-err').textContent = res.error + (res.rejects ? '：' + res.rejects.map((x) => x.text).join('；') : ''); return; }
    O.draft.clear(p.id);
    ui.closeModal();
    ui.toast('已采用，组织的新版本是 ' + p.version + '。之后新建的事项用它，进行中的事项不变。', 'ok');
    Y17.go('#/p/' + p.id + '/org');
    Y17.rerender();
  });

  // ---------------------------------------------------------------- 部门详情

  function sourceOf(d, f) { return d.src === 'added' ? 'added' : d.fieldSrc[f] ? 'changed' : 'follow'; }
  function row(label, ctrl, d, f, editing, path) {
    const s = f ? sourceOf(d, f) : null;
    const rest = editing && s === 'changed' ? '<button type="button" class="y17-link y17-small" data-act="od.restore" data-f="' + f + '" data-d="' + d.id + '" data-path="' + path + '">恢复为跟随发布</button>' : '';
    return '<div class="y17-dv-row" data-f="' + (f || '') + '"><div class="y17-dv-k">' + esc(label) + '</div><div class="y17-dv-v">' + ctrl + '</div><div class="y17-dv-s">' + (s ? srcTag(s) : '') + ' ' + rest + '</div></div>';
  }
  const group = (title, when, body, id) => ui.block({ id, title, subtitle: '', actions: ui.tag(when, 'follow'), body: '<div class="y17-dv">' + body + '</div>' });

  function checks(list, chosen, attrs, disabled) {
    return '<div class="y17-checks">' + list.map((x) => '<label class="y17-check"><input type="checkbox" ' + attrs + ' data-v="' + esc(x[0]) + '"' + (chosen.includes(x[0]) ? ' checked' : '') + (disabled ? ' disabled' : '') + '><span>' + esc(x[1]) + '</span></label>').join('') + '</div>';
  }

  function deptDetail(ctx, p) {
    const r = ctx.route;
    const v = viewOf(p, r);
    if (!v.node) return gate('找不到这个子组织', '路径对不上。');
    const c = v.node;
    const d = c.depts.find((x) => x.id === r.params.dept);
    const removed = !d && c.removedDepts.find((x) => x.id === r.params.dept);
    if (!d && !removed) return gate('找不到这个部门', '这份组织里没有这个部门。');
    const dd = d || removed;
    const editing = Boolean(v.draft) && !removed;
    const ps = v.path.join('.');
    const at = 'data-d="' + dd.id + '" data-path="' + ps + '"';
    const depth = c.depth;
    const bar = '<div id="org-bar">' + (v.draft ? barHtml(p, v.draft) : '') + '</div>';
    const head = '<div class="y17-page-head"><div class="y17-page-titles"><h1>' + esc(dd.name) + (removed ? ' ' + ui.tag('在草稿里已去掉') : '') + '</h1><p class="y17-muted">' + esc(p.name) + ' · ' + esc(c.formName) + (v.path.length ? '（子组织）' : '') + ' · ' + srcTag(dd.src === 'removed' ? 'removed' : dd.src) + '</p></div>' +
      '<div class="y17-page-actions">' + (v.draft ? '' : ui.button({ label: '修改', kind: 'primary', act: 'og.start' })) + ui.button({ label: '回到组织页', icon: 'back', go: goOrg(p, v.path) }) + '</div></div>' +
      (removed ? ui.note('这个部门在草稿里已去掉。' + ui.button({ label: '恢复', kind: 'small', act: 'og.restore-dept', data: { d: dd.id, path: ps } }), 'warn') : '');

    // 职责
    const names = c.outcomes.map((o) => [o.id, o.name]);
    const watchOpts = names;
    const verOpts = [['', '不核验']].concat([].concat(...c.depts.filter((x) => x.id !== dd.id).map((x) => x.produces.map((k) => [x.id + '|' + k, '核验「' + x.name + '」的「' + O.kindName(c, k) + '」']))));
    const verNow = dd.verifies ? dd.verifies.dept + '|' + dd.verifies.kind : '';
    const verCtl = editing
      ? '<select class="y17-select" aria-label="核验声明" data-act="od.ver" ' + at + '>' + verOpts.map((o) => '<option value="' + esc(o[0]) + '"' + (o[0] === verNow ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('') + '</select>'
      : esc((verOpts.find((o) => o[0] === verNow) || ['', '不核验'])[1]);
    const FN = { goal: '它对什么负责', judge: '凭什么判断', how: '怎么工作' };
    const text = (f, rows) => (editing ? '<textarea class="y17-textarea" rows="' + rows + '" aria-label="' + FN[f] + '" data-act="od.text" data-f="' + f + '" ' + at + '>' + esc(dd[f]) + '</textarea>' : '<p>' + (esc(dd[f]) || '<span class="y17-warn-text">还没写</span>') + '</p>');
    const duty = group('职责', '之后新建的事项',
      row('显示名', editing ? '<input class="y17-input" id="od-name" aria-label="显示名" data-act="od.text" data-f="name" ' + at + ' value="' + esc(dd.name) + '">' : '<strong>' + esc(dd.name) + '</strong>', dd, 'name', editing, ps) +
      row('它对什么负责', text('goal', 2), dd, 'goal', editing, ps) + row('凭什么判断', text('judge', 2), dd, 'judge', editing, ps) + row('怎么工作', text('how', 3), dd, 'how', editing, ps) +
      row('接哪些事项的来源', esc((dd.receives || []).map((x) => x.name).join('、') || '不接来源，在收到指导、询问或关注的成果交出来时开工') + (editing ? '（要改，在组织页头部的「事项的来源由谁接」里改）' : ''), dd, null, false, ps) +
      row('关注的成果', editing ? checks(watchOpts, dd.watches, 'data-act="od.list" data-f="watches" ' + at) : esc(dd.watches.map((k) => O.kindName(c, k)).join('、') || '无'), dd, 'watches', editing, ps) +
      row('交出的成果', editing ? checks(names, dd.produces, 'data-act="od.list" data-f="produces" ' + at) : esc(dd.produces.map((k) => O.kindName(c, k)).join('、') || '不交出成果，只回答询问'), dd, 'produces', editing, ps) +
      (c.rotation === 'direct' ? row('交完成', editing ? '<label class="y17-check"><input type="checkbox" data-act="od.done" ' + at + (dd.completes ? ' checked' : '') + '><span>由它交完成</span></label>' : (dd.completes ? '是' : '否'), dd, 'completes', editing, ps) : '') +
      row('核验声明', verCtl, dd, 'verifies', editing, ps), 'dv-duty');

    // 由谁做
    const who = dd.who || { type: 'own' };
    const subOpts = ['hub'].concat(O.PUBLISHED);
    const tooDeep = depth + 1 > O.MAX_DEPTH;
    const whoCtl = editing
      ? '<div class="y17-org-radios is-inline">' + Object.keys(O.WHO).map((t) => '<label class="y17-check"><input type="radio" name="od-who" data-act="od.who" data-t="' + t + '" ' + at + (who.type === t ? ' checked' : '') + (t === 'suborg' && tooDeep ? ' disabled' : '') + (t === 'outsourced' && dd.verifies ? ' disabled' : '') + '><span>' + O.WHO[t] + (t === 'suborg' && tooDeep ? '（已到嵌套上限，不能再选）' : '') + (t === 'outsourced' && dd.verifies ? '（核验角色不能外包）' : '') + '</span></label>').join('') + '</div>' +
        (who.type === 'outsourced' ? '<label class="y17-field is-inline"><span>外部 agent</span><select class="y17-select" data-act="od.agent" ' + at + '>' + O.AGENTS.map((a) => '<option' + (who.agent === a ? ' selected' : '') + '>' + esc(a) + '</option>').join('') + '</select></label>' : '') +
        (who.type === 'suborg' ? '<label class="y17-field is-inline"><span>从哪份形态起步</span><select class="y17-select" data-act="od.subform" ' + at + '>' + subOpts.map((f) => '<option value="' + f + '"' + (who.form === f ? ' selected' : '') + '>' + esc(O.formName(f)) + '</option>').join('') + '</select></label>' : '')
      : esc(O.WHO[who.type] + (who.type === 'outsourced' ? '（' + (who.agent || '未选') + '）' : who.type === 'suborg' ? '（' + O.formName(who.form) + '）' : ''));
    const whoRow = row('谁来做这个角色', whoCtl + (who.type === 'suborg' && dd.sub ? '<p>' + ui.button({ label: '打开内部', kind: 'small', go: goOrg(p, v.path.concat(dd.id)), data: { x: 'open-sub' } }) + ' <span class="y17-small y17-muted">' + esc(dd.sub.formName) + '，' + dd.sub.depts.length + ' 个角色</span></p>' : ''), dd, 'who', editing, ps);
    const who_ = group('由谁做', '之后新建的事项', whoRow + (who.type === 'outsourced' ? '<p class="y17-small y17-muted">外包角色：模型与工具走受控入口，交回快照与差异，经写入口成为提案。</p>' : ''), 'dv-who');

    // 权限
    const cat = O.catalog();
    const known = cat.map((t) => t[0]);
    const cats = {};
    cat.forEach((t) => { (cats[t[1]] = cats[t[1]] || []).push(t[0]); });
    dd.tools.filter((t) => !known.includes(t)).forEach((t) => { (cats['这个发布已经没有的工具'] = cats['这个发布已经没有的工具'] || []).push(t); });
    const toolCtl = editing
      ? Object.keys(cats).map((k) => '<div class="y17-tool-cat"><b>' + esc(k) + '</b>' + checks(cats[k].map((t) => [t, t]), dd.tools, 'data-act="od.list" data-f="tools" ' + at) + '</div>').join('')
      : esc(dd.tools.join('、') || '无');
    const writeCtl = editing
      ? '<select class="y17-select" aria-label="写入范围" data-act="od.write" ' + at + (dd.verifies ? ' disabled' : '') + '>' + Object.keys(O.WRITE).map((w) => '<option value="' + w + '"' + (dd.write === w ? ' selected' : '') + '>' + O.WRITE[w] + '</option>').join('') + '</select>' + (dd.verifies ? ' <small class="y17-muted">核验角色固定只写检查材料</small>' : '')
      : esc(O.WRITE[dd.write] || dd.write);
    const perm = group('权限', '之后新建的事项',
      row('工具许可', toolCtl, dd, 'tools', editing, ps) + row('写入范围', writeCtl, dd, 'write', editing, ps) +
      row('可见范围', esc((dd.visible || []).join('、') || '无') + ' <small class="y17-muted">写在定义里，现值按参数的规矩改，不经采用</small>', dd, null, false, ps), 'dv-perm');

    // 模型与 Prompt
    let modelBlock;
    const models = O.modelChoices();
    const isSub = dd.who && dd.who.type === 'suborg';
    const modelOpts = (cur) => models.map((m) => '<option' + (cur === m ? ' selected' : '') + '>' + esc(m) + '</option>').join('');
    const vision = (m) => m && O.MODELS[m] && !O.MODELS[m].vision;
    if (removed) {
      modelBlock = group('模型与 Prompt', '下一次模型请求', row('模型', '<span class="y17-muted">这个部门在草稿里已经去掉</span>', dd, null, false, ps), 'dv-model');
    } else if (depth > 0) {
      // 子组织里的角色：模型与角色 Prompt 写在这个角色自己的详情里，没写入的跟随上一层的部门
      const key = v.path.concat(dd.id).join('.');
      const s = (p.settings.nodes || {})[key] || { model: '', prompt: '' };
      const parentModel = O.nodeModel(p, v.path);
      const eff = s.model || parentModel || '';
      const advN = dd.verifies && vision(eff) ? '<div class="y17-note is-warn">提醒：核验角色最好用能看图像的模型。「' + esc(eff) + '」不能看图像，依赖外观或桌面程序的验收条件无法核验。仍然可以使用。</div>' : '';
      modelBlock = group('模型与 Prompt', '下一次模型请求，包括进行中的事项',
        row('生效的模型', eff ? ui.code(eff) + ' <small class="y17-muted">' + (s.model ? '本项目写入' : '跟随上一层的部门') + '</small>' : '<span class="y17-warn-text">还没有可用的模型，新建事项会被拒绝</span>', dd, null, false, ps) +
        row('模型', '<select class="y17-select" id="dn-model" aria-label="模型"><option value="">跟随这个部门（当前：' + esc(parentModel || '未选') + '）</option>' + modelOpts(s.model) + '</select>', dd, null, false, ps) + advN +
        row('角色 Prompt', '<textarea class="y17-textarea" id="dn-prompt" rows="4" aria-label="角色 Prompt" placeholder="留空表示使用内置的 Prompt">' + esc(s.prompt) + '</textarea><small class="y17-muted">没写入时用内置的 Prompt</small>', dd, null, false, ps) +
        '<div class="y17-row"><button type="button" class="y17-btn primary small" data-act="od.save-node" data-key="' + esc(key) + '">保存到本项目</button><small class="y17-muted">写进项目角色设置，不改上一层部门的设置。</small></div>', 'dv-model');
    } else {
      const s = p.settings.dept[dd.id] || { model: '', prompt: '' };
      const g = X.wiring[dd.id];
      const eff = s.model || (g && g.model) || '';
      const modelSel = '<select class="y17-select" id="dm-model" aria-label="模型"><option value="">' + (g ? '跟随部门使用（当前：' + esc(g.model) + '）' : '请选择模型') + '</option>' + modelOpts(s.model) + '</select>';
      const adv = dd.verifies && vision(eff) ? '<div class="y17-note is-warn">提醒：核验角色最好用能看图像的模型。「' + esc(eff) + '」不能看图像，依赖外观或桌面程序的验收条件无法核验。仍然可以使用。</div>' : '';
      const roleRows = dd.roles.map((rn) => {
        const rs = p.settings.roles[dd.id + '|' + rn] || { model: '', prompt: '' };
        return '<div class="y17-dv-role"><b>' + esc(rn) + '</b><select class="y17-select" data-role="' + esc(rn) + '" data-k="model" aria-label="' + esc(rn) + '的模型"><option value="">跟随部门</option>' + modelOpts(rs.model) + '</select>' +
          '<textarea class="y17-textarea" rows="2" data-role="' + esc(rn) + '" data-k="prompt" aria-label="' + esc(rn) + '的 Prompt" placeholder="角色 Prompt，留空表示用内置的">' + esc(rs.prompt) + '</textarea></div>';
      }).join('');
      const rolesPart = isSub
        ? '<div class="y17-dv-roles"><h4>角色</h4><p class="y17-small">内部的角色在各自的详情里写，没写入的跟随这个部门。 ' + ui.button({ label: '打开内部', kind: 'small', go: goOrg(p, v.path.concat(dd.id)) }) + '</p></div>'
        : '<div class="y17-dv-roles"><h4>角色</h4>' + roleRows + '</div>';
      modelBlock = group('模型与 Prompt', '下一次模型请求，包括进行中的事项',
        row('生效的模型', eff ? ui.code(eff) + ' <small class="y17-muted">' + (s.model ? '本项目写入' : '跟随模型管理里的「部门使用」') + '</small>' : '<span class="y17-warn-text">还没有可用的模型，新建事项会被拒绝</span>', dd, null, false, ps) +
        row('模型', modelSel, dd, null, false, ps) + adv +
        row('推理档位', g ? '请求 ' + esc(g.level) + ' · 发送 ' + esc(g.level) + ' <small class="y17-muted">在模型管理的「部门使用」里改</small>' : '跟随模型默认', dd, null, false, ps) +
        row('部门 Prompt', '<textarea class="y17-textarea" id="dm-prompt" rows="4" aria-label="部门 Prompt" placeholder="留空表示使用内置的 Prompt">' + esc(s.prompt) + '</textarea><small class="y17-muted">' + (dd.src === 'added' ? '加部门时写的那份就是内置的；以后改这里。' : '没写入时用内置的 Prompt') + '</small>', dd, null, false, ps) +
        rolesPart +
        '<div class="y17-row"><button type="button" class="y17-btn primary small" data-act="od.save-model" ' + at + '>保存到本项目</button><small class="y17-muted">写进项目部门设置' + (isSub ? '' : '与项目角色设置') + '，不改模型管理里的部门使用；解析顺序：项目角色设置、角色默认、项目部门设置、部门使用。</small></div>', 'dv-model');
    }

    // 位置
    const SET = X.settings[p.id] || { place: { checks: {} } };
    const place = (SET.place.checks || {})[dd.id];
    const placeName = !place ? '和运行工作区相同' : place === 'local' ? '本机进程' : ((X.machines().find((m) => m.id === place) || {}).name || place);
    const mcps = X.tools.mcp.filter((s) => s.project === p.id && s.depts.includes(dd.id));
    const loc = group('位置', '创建 run 时',
      row('做检查的地方', esc(placeName) + ' <button type="button" class="y17-link y17-small" data-go="#/p/' + p.id + '/settings">到设置页改</button>', dd, null, false, ps) +
      row('能用的 MCP 服务器', mcps.length ? esc(mcps.map((s) => s.name).join('、')) : '没有', dd, null, false, ps) +
      '<p class="y17-small y17-muted">只读显示；位置和 MCP 服务器在设置页里改，选项取自这份组织的部门。</p>', 'dv-place');

    const work = '<details class="y17-details y17-org-work"><summary>事项种类的工作说明（内置，跟随发布）</summary><p class="y17-small">每种事项怎么做、交什么、怎么验，是发布带的内置材料；材料提到别的部门时按身份引用，发给模型时填当时的显示名。要改，在「编辑定义」里改。</p>' +
      (v.draft ? ui.button({ label: '编辑定义', kind: 'small', act: 'og.doc' }) : '') + '</details>';
    return '<div class="y17-page y17-org">' + bar + head + duty + who_ + perm + modelBlock + loc + work + '</div>';
  }
  Y17.views.register('org-dept', { render: deptDetail });

  // 部门详情上的字段动作
  const pathFrom = (el) => (el.dataset.path ? el.dataset.path.split('.') : []);
  const setF = (el, f, val) => mut((d) => O.setField(d.changes, d.form, pathFrom(el), 'depts', el.dataset.d, f, val));
  A('od.text', (el) => setF(el, el.dataset.f, el.value.trim() || (el.dataset.f === 'name' ? '未命名的部门' : '')));
  A('od.list', (el) => {
    // 整张清单取页面上这个字段全部勾选的项（工具分了几个类别，在不同的容器里）
    const f = el.dataset.f;
    setF(el, f, [...document.querySelectorAll('.y17-dv input[data-f="' + f + '"]:checked')].map((i) => i.dataset.v));
  });
  A('od.done', (el) => mut((d) => {
    const p = pidNow(), c = O.nodeAt(O.draftCompose(d), pathFrom(el));
    c.depts.forEach((x) => { const want = x.id === el.dataset.d ? el.checked : false; if (x.completes !== want) O.setField(d.changes, d.form, pathFrom(el), 'depts', x.id, 'completes', want); });
  }));
  A('od.ver', (el) => mut((d) => {
    const val = el.value ? { dept: el.value.split('|')[0], kind: el.value.split('|')[1] } : null;
    O.setField(d.changes, d.form, pathFrom(el), 'depts', el.dataset.d, 'verifies', val);
    if (val) O.setField(d.changes, d.form, pathFrom(el), 'depts', el.dataset.d, 'write', 'check_only');
  }));
  A('od.write', (el) => setF(el, 'write', el.value));
  A('od.who', (el) => {
    const t = el.dataset.t;
    const val = t === 'own' ? { type: 'own' } : t === 'outsourced' ? { type: 'outsourced', agent: O.AGENTS[0] } : { type: 'suborg', form: 'hub', changes: {} };
    setF(el, 'who', val);
  });
  A('od.agent', (el) => setF(el, 'who', { type: 'outsourced', agent: el.value }));
  A('od.subform', (el) => setF(el, 'who', { type: 'suborg', form: el.value, changes: {} }));
  A('od.restore', (el) => mut((d) => O.restoreField(d.changes, d.form, pathFrom(el), 'depts', el.dataset.d, el.dataset.f)));
  A('od.save-node', (el) => {
    const p = pidNow();
    p.settings.nodes = p.settings.nodes || {};
    const model = document.getElementById('dn-model').value, prompt = document.getElementById('dn-prompt').value;
    if (model || prompt) p.settings.nodes[el.dataset.key] = { model, prompt }; else delete p.settings.nodes[el.dataset.key];
    ui.toast('已保存到本项目，从这个角色下一次模型请求起生效；进行中的事项也用', 'ok');
    Y17.rerender();
  });
  A('od.save-model', (el) => {
    const p = pidNow(), id = el.dataset.d;
    const model = document.getElementById('dm-model').value, prompt = document.getElementById('dm-prompt').value;
    if (model || prompt) p.settings.dept[id] = { model, prompt }; else delete p.settings.dept[id];
    document.querySelectorAll('.y17-dv-role').forEach((box) => {
      const rn = box.querySelector('select').dataset.role;
      const rm = box.querySelector('select').value, rp = box.querySelector('textarea').value;
      if (rm || rp) p.settings.roles[id + '|' + rn] = { model: rm, prompt: rp }; else delete p.settings.roles[id + '|' + rn];
    });
    ui.toast('已保存到本项目，从这个部门下一次模型请求起生效；进行中的事项也用', 'ok');
    Y17.rerender();
  });

  // ---------------------------------------------------------------- 加部门

  function newPage(ctx, p) {
    const r = ctx.route;
    const v = viewOf(p, r);
    if (!v.node) return gate('找不到这个子组织', '路径对不上。');
    const c = v.node;
    const ps = v.path.join('.');
    const names = c.outcomes.map((o) => [o.id, o.name]);
    const watchOpts = names;
    const tools = O.catalog().map((t) => [t[0], t[0]]);
    const models = O.modelChoices();
    const pubs = O.releaseDepts(c).map((id) => '<option value="pub:' + id + '">发布的部门：' + esc(O.releaseDeptName(id)) + '（带上它的三样说明、工具、写入范围、核验声明）</option>').join('');
    const copyOpts = '<option value="">空白</option>' + pubs + c.depts.map((d) => '<option value="' + d.id + '">复制「' + esc(d.name) + '」</option>').join('');
    const bar = '<div id="org-bar">' + (v.draft ? barHtml(p, v.draft) : '') + '</div>';
    return '<div class="y17-page y17-org">' + bar + '<div class="y17-page-head"><div class="y17-page-titles"><h1>加部门</h1><p class="y17-muted">' + esc(p.name) + (v.path.length ? ' · 子组织' : '') + '。加进草稿，采用以后才对之后新建的事项生效。</p></div>' +
      '<div class="y17-page-actions">' + ui.button({ label: '回到组织页', icon: 'back', go: goOrg(p, v.path) }) + '</div></div>' +
      ui.block({ title: '起点 ' + ui.tag('新增', 'new'), body: '<label class="y17-field"><span>从哪里起步</span><select class="y17-select" id="nd-copy" data-act="on.copy">' + copyOpts + '</select><small class="y17-muted">发布的部门：身份就是发布的那个，模型跟随模型管理里的「部门使用」；直做的组织里它默认核验交完成的角色。复制：带上工具、写入范围、核验声明，模型预选被复制部门的生效模型。</small></label>' }) +
      ui.block({ title: '它是谁', subtitle: '这三样必填，基础规则要求：新增的部门要写明它对什么负责、凭什么判断、怎么工作；它们同时生成下面的 Prompt 底稿', body: '<div class="y17-form">' +
        '<label class="y17-field"><span>显示名</span><input class="y17-input" id="nd-name" placeholder="例如 设计"></label>' +
        '<label class="y17-field"><span>它对什么负责</span><textarea class="y17-textarea" id="nd-goal" rows="2" data-live data-act="on.three"></textarea></label>' +
        '<label class="y17-field"><span>凭什么判断</span><textarea class="y17-textarea" id="nd-judge" rows="2" data-live data-act="on.three"></textarea></label>' +
        '<label class="y17-field"><span>怎么工作</span><textarea class="y17-textarea" id="nd-how" rows="2" data-live data-act="on.three"></textarea></label>' +
        '<label class="y17-field"><span>Prompt 底稿（可以改）</span><textarea class="y17-textarea" id="nd-prompt" rows="5" data-live data-act="on.prompt"></textarea></label></div>' }) +
      ui.block({ title: '成果', body: '<div class="y17-form"><div class="y17-field"><span>关注的成果</span>' + checks(watchOpts, [], 'data-nd="watches"') + '</div>' +
        '<div class="y17-field"><span>交出的成果</span>' + checks(names, [], 'data-nd="produces"') + '</div>' +
        '<label class="y17-check"><input type="checkbox" id="nd-newkind-on" data-act="on.kind"><span>新建一种成果</span></label>' +
        '<div id="nd-newkind" class="y17-org-newkind" hidden><label class="y17-field"><span>名字</span><input class="y17-input" id="nk-name" placeholder="例如 设计稿"></label>' +
        '<label class="y17-field"><span>一句说明</span><input class="y17-input" id="nk-desc"></label>' +
        '<label class="y17-field"><span>依据哪种成果的当前版</span><select class="y17-select" id="nk-based">' + watchOpts.map((o) => '<option value="' + o[0] + '">' + esc(o[1]) + '</option>').join('') + '</select></label>' +
        '<div class="y17-row"><label class="y17-check"><input type="checkbox" id="nk-receipt"><span>带检查回执</span></label><label class="y17-check"><input type="checkbox" id="nk-snapshot"><span>带代码快照</span></label></div>' +
        '<div class="y17-field"><span>让哪些部门关注这种新成果</span>' + checks(c.depts.map((d) => [d.id, d.name]), [], 'data-nd="kindwatch"') + '</div>' +
        '<small class="y17-muted">新种类走通用的成果接纳；更细的写法在「编辑定义」里。新成果由这个新部门交出。</small></div></div>' }) +
      ui.block({ title: '权限与模型', body: '<div class="y17-form"><div class="y17-field"><span>工具许可</span>' + checks(tools, [], 'data-nd="tools"') + '</div>' +
        '<label class="y17-field"><span>写入范围</span><select class="y17-select" id="nd-write">' + Object.keys(O.WRITE).map((w) => '<option value="' + w + '"' + (w === 'none' ? ' selected' : '') + '>' + O.WRITE[w] + '</option>').join('') + '</select><small class="y17-muted">运行工作区只能有一个写入者；现在已经有的话，选「不写入」。</small></label>' +
        '<p id="nd-ver" class="y17-small y17-muted"></p>' +
        '<label class="y17-field"><span>模型（自己加的必选；发布的部门跟随全局）</span><select class="y17-select" id="nd-model" data-act="on.model"><option value="">请选择</option>' + models.map((m) => '<option>' + esc(m) + '</option>').join('') + '</select><small class="y17-muted">写进本项目的部门设置；自己加的部门不进模型管理里的「部门使用」。</small></label></div>' }) +
      '<div class="y17-row y17-org-addbar"><button type="button" class="y17-btn primary" id="nd-add" data-act="on.add" data-path="' + ps + '" disabled>加入草稿</button><span id="nd-hint" class="y17-small y17-muted">还缺显示名和模型。</span></div></div>';
  }
  let ndVer = null; // 复制来的核验声明
  let ndPub = null; // 起点是发布的部门时，它的身份
  let promptTouched = false;
  Y17.views.register('org-new', { render: newPage, mount() { ndVer = null; ndPub = null; promptTouched = false; newHint(); } });
  function newHint() {
    const name = document.getElementById('nd-name'), model = document.getElementById('nd-model');
    if (!name) return;
    const miss = [!name.value.trim() ? '显示名' : '', !model.value && !ndPub ? '模型' : ''].filter(Boolean);
    const btn = document.getElementById('nd-add');
    btn.disabled = miss.length > 0;
    const three = ['nd-goal', 'nd-judge', 'nd-how'].some((id) => !document.getElementById(id).value.trim());
    document.getElementById('nd-hint').textContent = miss.length ? '还缺' + miss.join('和') + '。' : (three ? '三样说明还没写全：加入草稿后，校验会拒绝，补全才能采用。' : '可以加入草稿。');
  }
  document.addEventListener('input', (ev) => { if (ev.target.id === 'nd-name') newHint(); });
  A('on.model', newHint);
  A('on.prompt', () => { promptTouched = true; });
  A('on.three', () => {
    if (!promptTouched) {
      document.getElementById('nd-prompt').value = O.promptDraft(document.getElementById('nd-name').value.trim() || '新部门', document.getElementById('nd-goal').value.trim(), document.getElementById('nd-judge').value.trim(), document.getElementById('nd-how').value.trim());
    }
    newHint();
  });
  A('on.kind', (el) => { document.getElementById('nd-newkind').hidden = !el.checked; });
  A('on.copy', (el) => {
    const p = pidNow(), v = viewOf(p, Y17.state.route);
    const pub = el.value.indexOf('pub:') === 0 ? O.publishedDept(v.node, el.value.slice(4)) : null;
    const src = pub || v.node.depts.find((x) => x.id === el.value);
    ndVer = null; ndPub = pub ? pub.id : null;
    const tick = (key, list) => document.querySelectorAll('input[data-nd="' + key + '"]').forEach((i) => { i.checked = list.includes(i.dataset.v); });
    if (pub) document.getElementById('nd-name').value = pub.name;
    if (!src) { tick('watches', []); tick('produces', []); tick('tools', []); document.getElementById('nd-write').value = 'none'; document.getElementById('nd-ver').textContent = ''; return; }
    tick('watches', src.watches); tick('produces', pub ? src.produces : []); tick('tools', src.tools);
    document.getElementById('nd-write').value = src.write === 'workspace' && !pub ? 'none' : src.write;
    if (src.verifies) { ndVer = clone(src.verifies); document.getElementById('nd-ver').textContent = '核验声明跟着复制：' + (src.name) + '的核验声明（核验「' + ((v.node.depts.find((x) => x.id === src.verifies.dept) || {}).name || '？') + '」的「' + O.kindName(v.node, src.verifies.kind) + '」）。'; }
    else document.getElementById('nd-ver').textContent = '';
    const g = X.wiring[src.id];
    const s = p.settings.dept[src.id];
    const m = (s && s.model) || (g && g.model) || src.model || '';
    if (m && !pub) document.getElementById('nd-model').value = m; else if (pub) document.getElementById('nd-model').value = '';
    document.getElementById('nd-goal').value = src.goal; document.getElementById('nd-judge').value = src.judge; document.getElementById('nd-how').value = src.how;
    promptTouched = false;
    document.getElementById('nd-goal').dispatchEvent(new Event('input', { bubbles: true }));
  });
  A('on.add', (el) => {
    const p = pidNow(), path = el.dataset.path ? el.dataset.path.split('.') : [];
    const val = (id) => document.getElementById(id).value.trim();
    const vals = (key) => [...document.querySelectorAll('input[data-nd="' + key + '"]:checked')].map((i) => i.dataset.v);
    mut((d) => {
      const at = O.changesAt(d.changes, d.form, path);
      const used = Object.keys(at.changes.depts || {}).concat(at.form.depts.map((x) => x.id));
      let k = 1; while (used.includes('n' + k)) k += 1;
      const id = ndPub || 'n' + k;
      let produces = vals('produces');
      if (document.getElementById('nd-newkind-on').checked && val('nk-name')) {
        const oused = Object.keys(at.changes.outcomes || {}).concat(at.form.outcomes.map((x) => x.id));
        let j = 1; while (oused.includes('k' + j)) j += 1;
        const kid = 'k' + j;
        at.changes.outcomes = at.changes.outcomes || {};
        at.changes.outcomes[kid] = { added: true, name: val('nk-name'), desc: val('nk-desc'), basedOn: document.getElementById('nk-based').value, receipt: document.getElementById('nk-receipt').checked, snapshot: document.getElementById('nk-snapshot').checked };
        produces = produces.concat(kid);
        const comp = O.nodeAt(O.compose({ form: d.form, changes: d.changes }), path);
        vals('kindwatch').forEach((wid) => {
          const w = comp.depts.find((x) => x.id === wid);
          if (w) O.setField(d.changes, d.form, path, 'depts', wid, 'watches', w.watches.concat(kid));
        });
      }
      at.changes.depts = at.changes.depts || {};
      at.changes.depts[id] = { added: true, name: val('nd-name'), goal: val('nd-goal'), judge: val('nd-judge'), how: val('nd-how'), watches: vals('watches'), produces, tools: vals('tools'),
        write: document.getElementById('nd-write').value, who: { type: 'own' }, verifies: ndVer, completes: false };
      d.pending = d.pending || {};
      if (!ndPub || document.getElementById('nd-model').value) d.pending[id] = { model: document.getElementById('nd-model').value, prompt: val('nd-prompt') || O.promptDraft(val('nd-name'), val('nd-goal'), val('nd-judge'), val('nd-how')) };
    });
    ui.toast('已加进草稿。采用以后才对之后新建的事项生效', 'ok');
    Y17.go(goOrg(p, path));
  });

  // ---------------------------------------------------------------- 事项冻结的组织（只读）

  Y17.views.register('item-org', {
    render(ctx, p) {
      const it = H.item(p, ctx.route.params.item);
      if (!it || !it.org) return gate('找不到事项', '');
      const c = it.org.composed;
      const same = it.org.core === O.coreDigest(p.composed);
      const diff = same ? [] : O.diff(c, p.composed);
      const v = { path: [], node: c, root: c, draft: null, formId: c.form };
      const ck = O.validate(c, O.ctxFor(p));
      return '<div class="y17-page y17-org"><div class="y17-page-head"><div class="y17-page-titles"><h1>这个事项用的组织</h1><p class="y17-muted">' + H.dot(it) + ' ' + esc(it.title) + ' · 事项建立时冻结的那一份，只读</p></div>' +
        '<div class="y17-page-actions">' + ui.button({ label: '回到事项', icon: 'back', go: '#/p/' + p.id + '/w/' + it.id }) + '</div></div>' +
        ui.block({ title: '形态与版本', body: ui.kv([['形态', '<strong>' + esc(c.formName) + '</strong>'], ['版本', ui.code(it.org.version)], ['事项怎么结束', '<strong>' + esc(ck.ending.text) + '</strong>'],
          ['和项目现在的组织', same ? ui.status('succeeded', '相同') : ui.status('paused', '不同（比较部门、角色、成果、核验与轮转，不含观察者）')]], 'is-rows') +
          (diff.length ? '<h3 class="y17-h3">不同的地方（冻结的 → 现在的）</h3><ul class="y17-org-diff" id="item-org-diff">' + diff.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul>' : '') }) +
        ui.block({ title: '部门', body: deptTable(p, v, 'frozen') }) + flowBlock(c) + '</div>';
    }
  });
})();
