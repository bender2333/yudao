// 任务池的原型交互：认领、交回、单元核验与整份交付核验分别推进。
(function () {
  'use strict';
  const Y = window.Y20, O = Y.org, H = Y.h, ui = Y.ui, esc = Y.esc;
  const A = Y.actions.register;
  const project = () => H.project(H.pid());
  const units = (p) => p.workUnits || (p.workUnits = []);
  const blocked = (p, u) => u.depends.some((id) => !units(p).some((x) => x.id === id && x.status === 'done'));
  const refresh = () => { Y.rerender(); if (ui.modalOpen()) open(project()); };
  const note = (p, text) => Y.thread.state(p).msgs.push({ t: 'notice', text, at: Y.app.now() });
  function open(p) {
    const it = Y.thread.active(p), c = it ? it.org.composed : p.composed, end = O.ending(c);
    const workerChoices = c.depts.filter((d) => !d.verifies).map((d) => '<option value="' + esc(d.id) + '">' + esc(d.name) + '</option>').join('');
    ui.modal({ title: '工作单元', wide: true, body: '<div class="ws-unit-list">' + (units(p).map((u) => {
      const status = { ready: blocked(p, u) ? '等待前置工作' : '待认领', doing: '进行中', review: '等待单元核验', done: '单元已完成' }[u.status];
      let action = '';
      if (u.status === 'ready' && !blocked(p, u)) action = '<select class="y20-select" id="owner-' + esc(u.id) + '" aria-label="' + esc(u.title) + '的认领角色">' + workerChoices + '</select><button class="y20-btn small" data-act="pool.claim" data-unit="' + u.id + '">认领</button>';
      if (u.status === 'doing') action = '<button class="y20-btn small" data-act="pool.submit" data-unit="' + u.id + '">交回结果</button>';
      if (u.status === 'review') action = '<button class="y20-btn small primary" data-act="pool.pass" data-unit="' + u.id + '">单元核验通过</button><button class="y20-btn small" data-act="pool.reject" data-unit="' + u.id + '">打回修改</button>';
      return '<section class="ws-unit"><div><strong>' + esc(u.title) + '</strong><p>' + esc(status) + (u.owner ? ' · ' + esc(O.deptName(p, u.owner)) : '') + '</p>' + (u.depends.length ? '<small>前置工作：' + esc(u.depends.map((id) => units(p).find((x) => x.id === id).title).join('、')) + '</small>' : '') + (u.review ? '<small>' + esc(u.review) + '</small>' : '') + '</div><div class="ws-unit-actions">' + action + '</div></section>';
    }).join('') || '<p class="y20-muted">发送一个新事项后，工作单元出现在这里。</p>') + '</div><div class="ws-final-review"><strong>整份交付</strong><p>' + esc(p.poolReleased ? p.poolConclusion : end.text) + '</p><p>单元全部通过后，仍按本事项的结束条件处理整份交付。</p><button class="y20-btn primary" data-act="pool.release"' + (!it || !units(p).length || !units(p).every((u) => u.status === 'done') || p.poolReleased ? ' disabled' : '') + '>' + (end.open ? '交回整份结果，开环完成' : '核验整份交付并放行') + '</button></div>', actions: [{ label: '回到对话', close: true }] });
  }
  Y.pool = {
    summary(p) {
      const counts = { ready: 0, doing: 0, review: 0, done: 0, blocked: 0 }; units(p).forEach((u) => counts[u.status === 'ready' && blocked(p, u) ? 'blocked' : u.status]++);
      return '<button class="ws-pool-summary" type="button" data-act="pool.open"><strong>任务池</strong><span>待认领 ' + counts.ready + ' · 依赖阻塞 ' + counts.blocked + ' · 进行中 ' + counts.doing + ' · 待核验 ' + counts.review + ' · 已完成 ' + counts.done + '</span><span class="y20-link">查看工作单元</span></button>';
    },
    start(p, it) {
      p.workUnits = [{ id: it.id + '-1', title: it.title, status: 'ready', owner: '', depends: [], review: '' }]; p.poolReleased = false;
      note(p, '工作已放入任务池，等待角色认领。');
    },
    stop(p) {
      p.workUnits = []; p.poolReleased = false;
      note(p, '事项已停止，工作单元不再等待认领或核验。');
    }
  };
  A('pool.open', () => open(project()));
  A('pool.claim', (el) => { const p = project(), u = units(p).find((x) => x.id === el.dataset.unit); if (u.status !== 'ready' || blocked(p, u)) throw new Error('工作单元现在不能认领'); u.owner = document.getElementById('owner-' + u.id).value; u.status = 'doing'; Y.thread.readGuidance(p, [u.owner], Y.thread.active(p).id); note(p, O.deptName(p, u.owner) + '认领了「' + u.title + '」。'); refresh(); });
  A('pool.submit', (el) => { const p = project(), u = units(p).find((x) => x.id === el.dataset.unit); if (u.status !== 'doing') throw new Error('只有进行中的单元可以交回'); u.status = 'review'; note(p, '「' + u.title + '」已交回，等待单元核验。'); refresh(); });
  A('pool.pass', (el) => { const p = project(), u = units(p).find((x) => x.id === el.dataset.unit); if (u.status !== 'review') throw new Error('单元尚未交回'); u.status = 'done'; u.review = '单元核验通过'; note(p, '「' + u.title + '」单元核验通过。'); refresh(); });
  A('pool.reject', (el) => { const p = project(), u = units(p).find((x) => x.id === el.dataset.unit); if (u.status !== 'review') throw new Error('单元尚未交回'); u.status = 'doing'; u.review = '核验未通过，请补充边界检查'; note(p, '「' + u.title + '」被打回，原认领角色继续修改。'); refresh(); });
  A('pool.release', () => {
    const p = project(), it = Y.thread.active(p); if (!it || p.poolReleased || !units(p).length || units(p).some((u) => u.status !== 'done')) throw new Error('整份交付还不能结束');
    const s = Y.thread.state(p), c = it.org.composed, end = O.ending(c), names = O.verifiers(c).map((v) => v.name).join('、');
    p.poolReleased = true; p.poolConclusion = end.open ? '开环完成：整份交付没有独立核验' : names + '已核验整份交付，事项放行';
    const n = s.vers.length + 1; s.vers.push({ n, item: it.id, at: Y.app.now(), text: '所有工作单元已交回整份结果', concl: end.open ? '开环完成' : '放行', files: ['export.csv'], diff: ['+ 工作单元的改动已汇总'] });
    s.msgs.push({ t: end.open ? 'done' : 'rel', who: names || '执行角色', item: it.id, text: p.poolConclusion, vno: n, at: Y.app.now() });
    Y.thread.finish(p, it, end.open ? 'open_closed' : 'adopted');
    refresh();
  });
})();
