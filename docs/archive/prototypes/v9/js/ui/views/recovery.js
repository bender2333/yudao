// 恢复与动作核实（设计说明第 7.2 节，3.1）：恢复观察状态、原因、自动继续、动作核实、限额、执行所有权、因升级停止
(function () {
  'use strict';
  const Y9 = window.Y9;
  const esc = Y9.esc;

  const STATES = ['running', 'interrupted', 'pending_verification', 'waiting_resume', 'terminated'];
  const STATE_LABEL = { running: '运行中', interrupted: '中断', pending_verification: '待核实', waiting_resume: '待恢复', terminated: '已终止' };
  const STATE_KIND = { running: 'running', interrupted: 'interrupted', pending_verification: 'pending', waiting_resume: 'waiting', terminated: 'cancelled' };
  const ACTION_KIND = { not_sent: 'pending', done: 'succeeded', unknown: 'unknown' };
  const ACTION_LABEL = { not_sent: '未发送', done: '已完成', unknown: '结果未知' };
  const ACTION_CLASS = { not_sent: 'is-not_sent', done: 'is-done', unknown: 'is-unknown' };
  const DEPT_LABEL = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };

  function recovery(workItemId) {
    return Y9.api.query('run.recovery', { work_item: workItemId }).data;
  }

  function machineName(id) {
    if (!id) return null;
    if (!Y9.cap.query('machines.list')) return id;
    const machine = Y9.api.query('machines.list', {}).data.find((item) => item.id === id);
    return machine ? machine.name : id;
  }

  function stateBlock(r) {
    const pills = STATES.map((state) => '<li class="y9-rc-state' + (state === r.state ? ' is-on is-' + state : '') + '">' +
      (state === r.state ? Y9.ui.status(STATE_KIND[state], STATE_LABEL[state]) : esc(STATE_LABEL[state])) + '</li>').join('');
    const rules = '<ul class="y9-rc-rules">' +
      '<li>Yudao 启动时自动继续中断的 run；最后已确认的位置与自动继续的时间在下方列出。</li>' +
      '<li>重新连接事件流只补齐观察，不新建执行，也不重发模型请求或工具调用。</li>' +
      '<li>恢复不清零已用限额。</li></ul>';
    return Y9.ui.block({
      id: 'rc-state', title: '恢复观察状态', query: 'run.recovery',
      subtitle: '事项：' + esc(r.work_item.title) + ' · ' + esc(Y9.ui.time(r.run.started_at) || '尚未开始'),
      className: 'y9-rc-state-block is-' + r.state,
      body: '<ul class="y9-rc-states">' + pills + '</ul>' +
        (r.reason ? '<p class="y9-rc-reason">' + esc(r.reason) + '</p>' : '') + rules
    });
  }

  function reasonBlock(r) {
    if (r.state === 'waiting_resume') {
      const u = r.unusable;
      if (!u) throw new Error('待恢复缺少原因');
      const body = '<div class="y9-rc-unusable">' + Y9.ui.status('unusable', '待恢复') +
        '<strong>' + esc(DEPT_LABEL[u.department] || u.department) + '部门的模型无法使用</strong></div>' +
        Y9.ui.kv([
          ['部门', esc(DEPT_LABEL[u.department] || u.department)],
          ['模型', Y9.ui.code(u.model || '未设置')],
          ['问题', esc(u.problem || '—')]
        ], 'is-rows') +
        '<p class="y9-small y9-muted">修复以后控制主机在合适的位置重新判断能否继续；在本项目的部门设置里另选模型只影响本项目，从这个部门下一次模型请求起生效。回答使用下方决定卡片。</p>';
      return Y9.ui.block({ id: 'rc-reason', title: '待恢复原因', query: 'run.recovery', body, className: 'y9-rc-reason-block' });
    }
    if (r.state === 'interrupted') {
      const last = r.last_confirmed;
      const body = '<p class="y9-rc-reason">' + esc(r.reason || '服务进程停止') + '</p>' +
        Y9.ui.kv([
          ['最后已确认', last ? esc(last.text || String(last.seq)) : '—'],
          ['自动继续时间', r.auto_resumed_at ? esc(Y9.ui.time(r.auto_resumed_at)) : '<span class="y9-muted">还没有自动继续</span>']
        ], 'is-rows') +
        '<p class="y9-small y9-muted">按持久事实核对：已开始但没有回执的动作进入待核实；没有未完成动作时自动继续。</p>';
      return Y9.ui.block({ id: 'rc-reason', title: '中断位置', query: 'run.recovery', body, className: 'y9-rc-reason-block' });
    }
    if (r.state === 'terminated') {
      const stop = r.run.stop_reason;
      return Y9.ui.block({
        id: 'rc-reason', title: '已终止', query: 'run.recovery',
        body: Y9.ui.kv([
          ['停止原因', esc(stop ? (stop.text || stop.code) : '—')],
          ['所在部门', esc(r.run.department ? DEPT_LABEL[r.run.department] : (r.run.last_department ? DEPT_LABEL[r.run.last_department] + '（最后）' : '—'))]
        ], 'is-rows')
      });
    }
    return '';
  }

  function decideBlock(r) {
    const items = Y9.api.query('decisions.list', { work_item: r.work_item.id }).data;
    const body = items.length
      ? '<div class="y9-cards">' + items.map((d) => Y9.cards.render(d)).join('') + '</div>'
      : Y9.ui.empty('没有等待你回答的决定');
    return Y9.ui.block({
      id: 'rc-decide', title: '决定请求', query: ['run.recovery', 'decisions.list'], command: 'decision.answer',
      subtitle: '主机无法确定结果或需要修复入口时，由这里的卡片交给你',
      body, className: 'y9-rc-decide-block'
    });
  }

  function verifyCard(r, entry) {
    const state = entry.state || 'unknown';
    if (!(state in ACTION_KIND)) throw new Error('未知的动作状态：' + state);
    const machine = machineName(entry.machine_id);
    const checks = r.verifications.filter((v) => (v.action_id || v.actionId) === entry.id);
    const rows = [
      ['部门', esc(DEPT_LABEL[entry.department] || entry.department || '—')],
      machine ? ['执行的机器', esc(machine)] : null,
      ['输入依据', esc(entry.input || '—')],
      ['执行前', esc(entry.before || '—')],
      ['执行后', esc(entry.after || '—')]
    ].filter(Boolean);
    const verify = checks.length
      ? '<ul class="y9-rc-checks">' + checks.map((v) => '<li class="' + ((v.decided_by || v.decidedBy) === 'user' ? 'is-user' : '') + '">' +
        '<div><b>核实依据</b>' + esc(v.basis || '—') + '</div><div><b>核实结果</b>' + esc(v.result || '—') + '</div>' +
        '<small class="y9-muted">' + esc(Y9.ui.time(v.at)) + ((v.decided_by || v.decidedBy) === 'user' ? ' · 用户决定' : '') + '</small></li>').join('') + '</ul>'
      : '';
    return '<article class="y9-rc-action ' + ACTION_CLASS[state] + ' is-pending">' +
      '<header class="y9-rc-action-head">' + Y9.ui.status(ACTION_KIND[state], ACTION_LABEL[state]) +
        '<code class="y9-code">' + esc(entry.id) + '</code>' + Y9.ui.tag('未完成') + '</header>' +
      '<p class="y9-rc-action-sum">' + esc(entry.label || '') + '</p>' +
      Y9.ui.kv(rows, 'is-rows') + verify + '</article>';
  }

  function verifyBlock(r) {
    const list = r.unfinished.map((entry) => verifyCard(r, entry)).join('');
    const records = r.verifications.length
      ? '<h3 class="y9-h3">核实记录</h3><ul class="y9-rc-checks">' + r.verifications.map((v) => '<li class="' + ((v.decided_by || v.decidedBy) === 'user' ? 'is-user' : '') + '">' +
        '<div><b>动作</b>' + Y9.ui.code(v.action_id || v.actionId || '—') + '</div>' +
        '<div><b>核实依据</b>' + esc(v.basis || '—') + '</div><div><b>核实结果</b>' + esc(v.result || '—') + '</div>' +
        '<small class="y9-muted">' + esc(Y9.ui.time(v.at)) + ((v.decided_by || v.decidedBy) === 'user' ? ' · 用户决定' : '') + '</small></li>').join('') + '</ul>'
      : '';
    const body = (list ? '<div class="y9-rc-actions">' + list + '</div>' : Y9.ui.empty('没有未完成的动作：所有动作都有回执')) + records;
    const queries = Y9.cap.query('machines.list') ? ['run.recovery', 'machines.list'] : 'run.recovery';
    return Y9.ui.block({
      id: 'rc-verify', title: '动作核实', query: queries,
      subtitle: '未完成动作与核实记录；核实结果追加到记录，原始观察不改写', body
    });
  }

  function ownerBlock(r) {
    const owner = r.owner
      ? Y9.ui.kv([['当前执行者', esc(r.owner.id)], ['取得时间', esc(Y9.ui.time(r.owner.since))], ['执行槽位', r.holds_slot ? '占用一个执行槽位' : '<span class="y9-muted">没有占用执行槽位</span>']], 'is-rows')
      : Y9.ui.kv([['当前执行者', '<span class="y9-muted">没有有效执行者</span>'], ['执行槽位', r.holds_slot ? '保留一个执行槽位' : '<span class="y9-muted">没有占用执行槽位</span>']], 'is-rows');
    const late = r.late_results.length
      ? '<h3 class="y9-h3">迟到结果</h3><p class="y9-small y9-muted">旧执行者的迟到回执作为历史事实列出，不推进状态。</p>' +
        '<ul class="y9-rc-late">' + r.late_results.map((entry) =>
          '<li><span class="y9-muted">' + esc(Y9.ui.time(entry.at)) + '</span><span>' + esc(entry.text) + '</span></li>').join('') + '</ul>'
      : '<p class="y9-small y9-muted">没有迟到结果。</p>';
    return Y9.ui.block({ id: 'rc-owner', title: '执行所有权', query: 'run.recovery', body: owner + late });
  }

  function limitsBlock(r) {
    const l = r.limits;
    const waiting = l.waiting_provider_sec !== undefined
      ? '<div class="y9-rc-limit"><span>等待模型服务（不计入上限）</span><strong>' + esc(Y9.ui.duration(l.waiting_provider_sec)) + '</strong></div>'
      : '';
    const body = '<div class="y9-rc-limits">' +
      '<div class="y9-rc-limit is-wide"><span>已用时间与时间上限</span><strong>' + esc(Y9.ui.duration(r.run.elapsed_sec)) + ' / ' + esc(Y9.ui.duration(r.run.limit_sec)) + '</strong>' +
        Y9.ui.meter(r.run.elapsed_sec, r.run.limit_sec, { warnAt: 0.8 }) + '</div>' +
      '<div class="y9-rc-limit"><span>已用激活次数</span><strong>' + esc(l.activations || 0) + '</strong></div>' +
      '<div class="y9-rc-limit"><span>模型步骤</span><strong>' + esc(l.model_steps || 0) + '</strong></div>' +
      '<div class="y9-rc-limit"><span>重试尝试</span><strong>' + esc(l.retries || 0) + '</strong></div>' +
      waiting +
      '</div><p class="y9-small y9-muted">恢复不清零；发送状态未知的尝试仍然占用；用量未上报时显示未知，不填零。</p>';
    return Y9.ui.block({ id: 'rc-limits', title: '限额', query: 'run.recovery', body });
  }

  function upgradeBlock(r, oldRuns) {
    if (!r.upgrade) return '';
    const up = r.upgrade;
    const newRun = up.new_run_id
      ? Y9.ui.kv([
        ['新 run', esc(r.work_item.title) + '<small class="y9-muted">' + esc(up.new_run_id) + '</small>'],
        ['新 run 的 Yudao 版本', esc(up.new_yudao_version || '—')],
        ['队列位置', up.queue_pos != null ? '排队中第 ' + esc(up.queue_pos) + ' 位' : '—']
      ], 'is-rows')
      : '<p class="y9-muted">还没有重新开始的新 run。</p>';
    const runs = oldRuns.filter((entry) => entry.id === up.stopped_run_id);
    const events = runs.length && runs[0].events.length
      ? '<h3 class="y9-h3">旧 run 的事件（只读）</h3><ul class="y9-rc-events">' + runs[0].events.map((ev) =>
        '<li><span class="y9-muted">' + esc(Y9.ui.time(ev.at)) + '</span>' + Y9.ui.code(ev.type) + '<span>' + esc(ev.label) + '</span></li>').join('') + '</ul>'
      : '';
    return Y9.ui.block({
      id: 'rc-upgrade', title: '因升级停止', query: ['run.recovery', 'work_item.materials'],
      subtitle: '停止时的 Yudao 版本与用已采纳成果重新开始的新 run',
      className: 'y9-rc-state-block is-interrupted',
      body: Y9.ui.kv([['停止时的 Yudao 版本', esc(up.yudao_version || '—')], ['旧 run', esc(r.work_item.title) + '<small class="y9-muted">' + esc(up.stopped_run_id) + '</small>']], 'is-rows') + newRun + events
    });
  }

  function restartBlock(r) {
    if (!Y9.cap.command('onboarding.restart')) return '';
    if (r.work_item.kind !== 'onboarding') return '';
    const ov = Y9.api.query('project.overview', { project: r.project.id }).data;
    if (ov.project.source !== 'existing' || ov.adoption) return '';
    if (r.work_item.status !== 'stopped') return '';
    const dirs = ov.source_directories || [];
    if (!dirs.length) return '';
    const options = dirs.map((dir) => '<option value="' + esc(dir.name) + '">' + esc(dir.name) + ' · ' + esc(dir.path) + '</option>').join('');
    return Y9.ui.block({
      id: 'rc-restart', title: '重新开始建档', query: ['run.recovery', 'project.overview'], command: 'onboarding.restart',
      subtitle: '从登记的源目录重新采集快照，开始新的建档事项',
      body: '<div class="y9-form"><label class="y9-field"><span>源目录（登记名）</span><select class="y9-input" id="rc-restart-src">' + options + '</select></label>' +
        '<div class="y9-row">' + Y9.ui.button({ label: '重新开始建档', kind: 'primary', act: 'rc.restart', data: { project: r.project.id } }) + '</div></div>'
    });
  }

  function render(ctx) {
    const r = recovery(ctx.workItemId);
    const oldRuns = Y9.cap.query('work_item.materials')
      ? Y9.api.query('work_item.materials', { project: ctx.projectId, work_item: ctx.workItemId }).data.old_runs || []
      : [];
    return '<div class="y9-pp y9-rc">' +
      stateBlock(r) + (reasonBlock(r) || '<section id="rc-reason" hidden></section>') + decideBlock(r) + verifyBlock(r) + limitsBlock(r) + ownerBlock(r) +
      (upgradeBlock(r, oldRuns) || '<section id="rc-upgrade" hidden></section>') + (restartBlock(r) || '<section id="rc-restart" hidden></section>') +
    '</div>';
  }

  function refresh(root, selector, html) {
    if (!html) return;
    const el = root.querySelector(selector);
    if (!el) return;
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const next = tmp.firstElementChild;
    if (next) el.replaceWith(next);
  }

  function update(ctx, root) {
    const r = recovery(ctx.workItemId);
    const oldRuns = Y9.cap.query('work_item.materials')
      ? Y9.api.query('work_item.materials', { project: ctx.projectId, work_item: ctx.workItemId }).data.old_runs || []
      : [];
    refresh(root, '#rc-state', stateBlock(r));
    refresh(root, '#rc-reason', reasonBlock(r) || '<section id="rc-reason" hidden></section>');
    refresh(root, '#rc-decide', decideBlock(r));
    refresh(root, '#rc-verify', verifyBlock(r));
    refresh(root, '#rc-limits', limitsBlock(r));
    refresh(root, '#rc-owner', ownerBlock(r));
    refresh(root, '#rc-upgrade', upgradeBlock(r, oldRuns) || '<section id="rc-upgrade" hidden></section>');
    refresh(root, '#rc-restart', restartBlock(r) || '<section id="rc-restart" hidden></section>');
  }

  Y9.views.register('recovery', {
    title: () => '恢复与动作核实',
    needs: { queries: ['run.recovery'] },
    render, update
  });

  Y9.actions.register('rc.restart', (el) => {
    const src = document.getElementById('rc-restart-src');
    Y9.run('onboarding.restart', { project: el.dataset.project, source_name: src ? src.value : '' });
  });
})();
