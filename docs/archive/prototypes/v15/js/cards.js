// 决定卡片：首页与项目概览共用。「定义版本不同」列出变了哪几份定义，路由改变走同一张卡片
(function () {
  'use strict';
  const Y15 = window.Y15;
  const esc = Y15.esc;
  const H = Y15.h;

  function body(d) {
    if (d.kind === 'definitions_changed') {
      const rows = d.changed.map((c) => '<tr><td>' + esc(c.name) + '</td><td>' + Y15.ui.tag(c.type) + '</td><td><code class="y15-code">' + esc(c.before) + '</code></td><td><code class="y15-code">' + esc(c.now) + '</code></td></tr>').join('');
      return '<p class="y15-small">' + esc(d.basis) + '</p>' +
        '<div class="y15-table-wrap"><table class="y15-table y15-def-table"><thead><tr><th>变了的定义</th><th>类别</th><th>事项开始时</th><th>现在</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '<p class="y15-muted y15-small">其余 ' + d.unchanged + ' 份定义没有变。</p>';
    }
    if (d.kind === 'role_choice') return Y15.ui.kv([['谁拿不准', esc(d.from)], ['问题', esc(d.question)]], 'y15-card-kv');
    if (d.kind === 'waiting_resume') {
      const p = H.project(d.project), it = p && H.item(p, d.item);
      const int = p && p.interruptions.find((i) => i.item === d.item);
      return Y15.ui.kv([['被打断的工作', esc(int ? int.what : '一轮工作')], ['原因', esc(int ? int.why : '控制主机重启')], ['事项现在的状态', it ? H.status(it) : '']], 'y15-card-kv');
    }
    return '';
  }

  function card(d) {
    const p = H.project(d.project), it = p && H.item(p, d.item);
    const opts = d.options.map((o) => '<button type="button" class="y15-btn small' + (o.primary ? ' primary' : '') + '" data-act="decide" data-id="' + esc(d.id) + '" data-opt="' + esc(o.id) + '">' + esc(o.label) + '</button>').join('');
    return '<article class="y15-card is-' + d.kind + '" id="decision-' + esc(d.id) + '"><div class="y15-card-title"><strong>' + esc(d.label) + '</strong>' +
      (p ? ' <span class="y15-muted">·</span> ' + H.link('#/p/' + p.id, p.name) : '') + (it ? ' <span class="y15-muted">·</span> ' + H.link('#/p/' + p.id + '/w/' + it.id, it.title) : '') + '</div>' +
      '<div class="y15-card-meta"><span>已等待 ' + esc(H.waited(d.at)) + '</span><span>' + esc(d.blocks) + '</span></div>' +
      body(d) + '<div class="y15-row y15-card-answer">' + opts + '</div></article>';
  }

  Y15.cards = {
    one: card,
    list(pid) {
      const list = H.decisions(pid);
      return list.length ? '<div class="y15-cards">' + list.map(card).join('') + '</div>' : Y15.ui.empty('没有等你回答的决定');
    }
  };

  Y15.actions.register('decide', (el) => {
    const W = Y15.W();
    const d = W.decisions.find((x) => x.id === el.dataset.id);
    if (!d) return;
    const opt = d.options.find((o) => o.id === el.dataset.opt);
    const p = H.project(d.project), it = p && H.item(p, d.item);
    W.decisions = W.decisions.filter((x) => x !== d);
    const stop = opt.id === 'stop';
    if (it) it.status = stop ? 'stopped' : 'working';
    if (it) it.reason = stop ? '你决定停止这个事项' : '你回答后继续：' + opt.label;
    if (p && d.kind === 'waiting_resume') {
      p.interruptions = p.interruptions.filter((i) => i.item !== d.item);
      const ds = p.deptState[it.dept];
      if (ds && !stop && !p.interruptions.some((i) => i.dept === it.dept)) { ds.state = 'running'; ds.text = it.dept === 'engineering' ? '写导出功能（导出订单为 CSV）' : '核验订单列表分页（交付第 2 版）'; ds.reason = '从中断的位置继续'; }
    }
    Y15.ui.toast('已回答「' + d.label + '」：' + opt.label, 'ok');
    Y15.rerender();
  });
})();
