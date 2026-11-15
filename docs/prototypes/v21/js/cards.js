// 决定卡片：首页与恢复详情页共用。「定义版本不同」列出变了哪几份定义，路由改变走同一张卡片
(function () {
  'use strict';
  const Y21 = window.Y21;
  const esc = Y21.esc;
  const H = Y21.h;

  function body(d) {
    if (d.kind === 'definitions_changed') {
      const rows = d.changed.map((c) => '<tr><td>' + esc(c.name) + '</td><td>' + Y21.ui.tag(c.type) + '</td><td><code class="y21-code">' + esc(c.before) + '</code></td><td><code class="y21-code">' + esc(c.now) + '</code></td></tr>').join('');
      return '<p class="y21-small">' + esc(d.basis) + '</p>' +
        '<div class="y21-table-wrap"><table class="y21-table y21-def-table"><thead><tr><th>变了的定义</th><th>类别</th><th>事项开始时</th><th>现在</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '<p class="y21-muted y21-small">其余 ' + d.unchanged + ' 份定义没有变。</p>';
    }
    if (d.kind === 'role_choice') {
      if (d.questions && d.questions.length) {
        const roundTxt = d.round ? '第 ' + d.round + '/' + (d.maxRounds || 2) + ' 轮' : '';
        const list = '<ol class="y21-card-qs">' + d.questions.map((q) =>
          '<li><strong>' + esc(q.prompt) + '</strong>' +
          (q.recommended ? '<div class="y21-small y21-muted">推荐：' + esc(q.recommended) + (q.why ? '（' + esc(q.why) + '）' : '') + '</div>' : '') +
          '</li>'
        ).join('') + '</ol>';
        return Y21.ui.kv([['谁拿不准', esc(d.from) + (roundTxt ? ' · ' + esc(roundTxt) : '')], ['待答清单', list]], 'y21-card-kv');
      }
      return Y21.ui.kv([['谁拿不准', esc(d.from)], ['问题', esc(d.question)]], 'y21-card-kv');
    }
    if (d.kind === 'waiting_resume') {
      const p = H.project(d.project), it = p && H.item(p, d.item);
      const int = p && p.interruptions.find((i) => i.item === d.item);
      return Y21.ui.kv([['被打断的工作', esc(int ? int.what : '一轮工作')], ['原因', esc(int ? int.why : '控制主机重启')], ['事项现在的状态', it ? H.status(it) : '']], 'y21-card-kv');
    }
    return '';
  }

  function card(d) { return H.in(d.project, () => cardHtml(d)); }

  function cardHtml(d) {
    const p = H.project(d.project), it = p && H.item(p, d.item);
    const opts = d.options.map((o) => '<button type="button" class="y21-btn small' + (o.primary ? ' primary' : '') + '" data-act="decide" data-id="' + esc(d.id) + '" data-opt="' + esc(o.id) + '">' + esc(o.label) + '</button>').join('');
    return '<article class="y21-card is-' + d.kind + '" id="decision-' + esc(d.id) + '"><div class="y21-card-title"><strong>' + esc(d.label) + '</strong>' +
      (p ? ' <span class="y21-muted">·</span> ' + H.link('#/p/' + p.id, p.name) : '') + (it ? ' <span class="y21-muted">·</span> ' + H.link('#/p/' + p.id + '?item=' + it.id, it.title) : '') + '</div>' +
      '<div class="y21-card-meta"><span>已等待 ' + esc(H.waited(d.at)) + '</span><span>' + esc(d.blocks) + '</span></div>' +
      body(d) + '<div class="y21-row y21-card-answer">' + opts + '</div></article>';
  }

  Y21.cards = {
    one: card,
    // 首页只列出来并跳到项目对话里的气泡；拍板只在对话里
    list(pid) {
      const list = H.decisions(pid);
      if (!pid) return list.length ? '<ul class="y21-jumps">' + list.map((d) => { const p = H.project(d.project); return '<li><strong>' + esc(d.label) + '</strong> · ' + esc(p ? p.name : '') + ' <button type="button" class="y21-link" data-act="ln.jump" data-p="' + esc(d.project) + '">去对话里决定</button></li>'; }).join('') + '</ul>' : Y21.ui.empty('没有等你回答的决定');
      return list.length ? '<div class="y21-cards">' + list.map(card).join('') + '</div>' : Y21.ui.empty('没有等你回答的决定');
    }
  };

  Y21.actions.register('decide', (el) => {
    const W = Y21.W();
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
    Y21.ui.toast('已回答「' + d.label + '」：' + opt.label, 'ok');
    Y21.rerender();
  });
})();
