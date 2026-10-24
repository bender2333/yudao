// 恢复与动作核实（设计说明第 7.2 节，3.1）：恢复观察状态、原因、自动继续、结果未知的动作的处理、会话的用量与限额、执行所有权、因升级停止
(function () {
  'use strict';
  const Y12 = window.Y12;
  const esc = Y12.esc;

  // 恢复观察状态：运行中、中断、待恢复与四种结束方式（恢复契约第 1 节，工单 #747）；机器离线时的待恢复写「等待机器」
  const STATES = ['running', 'interrupted', 'waiting_resume', 'completed', 'paused', 'cancelled', 'stopped'];
  const STATE_LABEL = {
    running: '运行中', interrupted: '中断', waiting_resume: '待恢复',
    completed: '已完成', paused: '已暂停', cancelled: '已取消', stopped: '已停止'
  };
  const STATE_KIND = {
    running: 'running', interrupted: 'interrupted', waiting_resume: 'waiting',
    completed: 'done', paused: 'paused', cancelled: 'cancelled', stopped: 'failed'
  };
  const ENDED = ['completed', 'paused', 'cancelled', 'stopped'];
  // 结果未知的动作的处理（恢复契约第 4 节）
  const HANDLING_KIND = { confirmed: 'succeeded', returned: 'asking', waiting: 'waiting' };
  const DEPT_LABEL = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };

  function recovery(workItemId) {
    return Y12.api.query('run.recovery', { work_item: workItemId }).data;
  }

  function machineName(id) {
    if (!id) return null;
    if (!Y12.cap.query('machines.list')) return id;
    const machine = Y12.api.query('machines.list', {}).data.find((item) => item.id === id);
    return machine ? machine.name : id;
  }

  const stateText = (r, state) => (state === 'waiting_resume' && r.waiting_machine ? '待恢复（等待机器）' : STATE_LABEL[state]);

  function stateBlock(r) {
    if (!STATE_LABEL[r.state]) throw new Error('未知的恢复观察状态：' + r.state);
    const pills = STATES.map((state) => '<li class="y12-rc-state' + (state === r.state ? ' is-on is-' + state : '') + '">' +
      (state === r.state ? Y12.ui.status(STATE_KIND[state], stateText(r, state)) : esc(STATE_LABEL[state])) + '</li>').join('');
    const rules = '<ul class="y12-rc-rules">' +
      '<li>Yudao 启动时自动继续中断的 run；最后已确认的位置与自动继续的时间在下方列出。</li>' +
      '<li>结果未知的动作先按核实方法自动核实；核实不出确定结果时作为工具结果交还发出它的会话，由模型决定是否重新执行，不发决定请求。</li>' +
      '<li>等待模型服务、等待机器各有时长上限，超过时发出决定请求并通知一次；等待时间不计入运行时间上限。</li>' +
      '<li>重新连接事件流只补齐观察，不新建执行，也不重发模型请求或工具调用；恢复不清零已用限额。</li></ul>';
    return Y12.ui.block({
      id: 'rc-state', title: '恢复观察状态', query: 'run.recovery',
      subtitle: '事项：' + esc(r.work_item.title) + ' · ' + esc(Y12.ui.time(r.run.started_at) || '尚未开始'),
      className: 'y12-rc-state-block is-' + r.state,
      body: '<ul class="y12-rc-states">' + pills + '</ul>' +
        (r.reason ? '<p class="y12-rc-reason">' + esc(r.reason) + '</p>' : '') + rules
    });
  }

  function lastDept(r) {
    return r.run.department ? DEPT_LABEL[r.run.department] : (r.run.last_department ? DEPT_LABEL[r.run.last_department] + '（最后）' : '—');
  }

  function reasonBlock(r) {
    if (r.state === 'waiting_resume' && r.waiting_machine) {
      // 等待机器（执行环境服务设计说明第 6.5 节）：机器名称与已经等待的时长；恢复在线以后按尝试身份核实，自动继续
      const w = r.waiting_machine;
      const body = '<div class="y12-rc-unusable">' + Y12.ui.status('waiting', '等待机器') + '<strong>' + esc(w.machine_name) + '：' + esc(w.problem) + '</strong></div>' +
        Y12.ui.kv([
          ['机器', esc(w.machine_name)],
          ['问题', esc(w.problem)],
          ['开始等待', esc(Y12.ui.time(w.since))],
          ['已经等待', esc(Y12.ui.duration(w.waited_sec))]
        ], 'is-rows') +
        '<p class="y12-small y12-muted">机器恢复在线以后，按尝试身份查询动作记录：已结束的取得回执，核实确认；没有回执可用的作为工具结果交还发出它的会话。等待的时长上限是 24 小时，超过时发出决定请求。等待期间可以在概览页取消事项。</p>';
      return Y12.ui.block({ id: 'rc-reason', title: '待恢复原因', query: 'run.recovery', body, className: 'y12-rc-reason-block' });
    }
    if (r.state === 'waiting_resume' && r.unusable) {
      const u = r.unusable;
      const body = '<div class="y12-rc-unusable">' + Y12.ui.status('unusable', '待恢复') +
        '<strong>' + esc(DEPT_LABEL[u.department] || u.department) + '部门的模型无法使用</strong></div>' +
        Y12.ui.kv([
          ['部门', esc(DEPT_LABEL[u.department] || u.department)],
          ['模型', Y12.ui.code(u.model || '未设置')],
          ['问题', esc(u.problem || '—')]
        ], 'is-rows') +
        '<p class="y12-small y12-muted">修复以后控制主机在合适的位置重新判断能否继续；在本项目的部门设置里另选模型只影响本项目，从这个部门下一次模型请求起生效。回答使用下方决定卡片。</p>';
      return Y12.ui.block({ id: 'rc-reason', title: '待恢复原因', query: 'run.recovery', body, className: 'y12-rc-reason-block' });
    }
    if (r.state === 'waiting_resume') {
      // 其余的待恢复由决定请求结束（例如继续旧事项时定义版本不同）
      if (!r.reason) throw new Error('待恢复缺少原因');
      return Y12.ui.block({
        id: 'rc-reason', title: '待恢复原因', query: 'run.recovery', className: 'y12-rc-reason-block',
        body: '<p class="y12-rc-reason">' + esc(r.reason) + '</p><p class="y12-small y12-muted">回答使用下方决定卡片。</p>'
      });
    }
    if (r.state === 'interrupted') {
      const last = r.last_confirmed;
      const body = '<p class="y12-rc-reason">' + esc(r.reason || '服务进程停止') + '</p>' +
        Y12.ui.kv([
          ['最后已确认', last ? esc(last.text || String(last.seq)) : '—'],
          ['自动继续时间', r.auto_resumed_at ? esc(Y12.ui.time(r.auto_resumed_at)) : '<span class="y12-muted">还没有自动继续</span>']
        ], 'is-rows') +
        '<p class="y12-small y12-muted">按持久事实核对：已开始但没有回执的动作按核实方法核实，核实不出确定结果时交还发出它的会话；没有未完成动作时直接自动继续。</p>';
      return Y12.ui.block({ id: 'rc-reason', title: '中断位置', query: 'run.recovery', body, className: 'y12-rc-reason-block' });
    }
    if (ENDED.includes(r.state)) {
      const stop = r.run.stop_reason;
      return Y12.ui.block({
        id: 'rc-reason', title: STATE_LABEL[r.state], query: 'run.recovery',
        body: Y12.ui.kv([
          ['结束方式', esc(STATE_LABEL[r.state])],
          ['停止原因', esc(stop ? (stop.text || stop.code) : (r.state === 'completed' ? '质检放行' : '—'))],
          ['最后已确认', r.last_confirmed ? esc(r.last_confirmed.text || String(r.last_confirmed.seq)) : '—'],
          ['所在部门', esc(lastDept(r))]
        ], 'is-rows')
      });
    }
    return '';
  }

  function decideBlock(r) {
    const items = Y12.api.query('decisions.list', { work_item: r.work_item.id }).data;
    const body = items.length
      ? '<div class="y12-cards">' + items.map((d) => Y12.cards.render(d)).join('') + '</div>'
      : Y12.ui.empty('没有等待你回答的决定');
    return Y12.ui.block({
      id: 'rc-decide', title: '决定请求', query: ['run.recovery', 'decisions.list'], command: 'decision.answer',
      subtitle: '需要你修复入口、选择版本或决定是否继续等待时，由这里的卡片交给你；结果未知的动作不在这里',
      body, className: 'y12-rc-decide-block'
    });
  }

  // 一条结果未知的动作：处理方式（核实确认、交还会话、等待机器恢复以后核实）、依据、交回会话的内容
  function unknownCard(entry) {
    if (!HANDLING_KIND[entry.handling]) throw new Error('未知的处理方式：' + entry.handling);
    const machine = machineName(entry.machine_id);
    const rows = [
      ['部门', esc(DEPT_LABEL[entry.department] || entry.department || '—')],
      entry.session ? ['发出它的会话', esc(entry.session)] : null,
      machine ? ['执行的机器', esc(machine)] : null,
      ['输入依据', esc(entry.input || '—')],
      ['执行前', esc(entry.before || '—')],
      ['执行后', esc(entry.after || '—')],
      entry.basis ? ['依据', esc(entry.basis)] : null,
      entry.result ? ['核实的结果', esc(entry.result)] : null,
      entry.at ? ['处理时间', esc(Y12.ui.time(entry.at))] : null
    ].filter(Boolean);
    const returned = entry.returned
      ? '<div class="y12-rc-returned"><b>交还会话的工具结果</b>' + Y12.ui.pre(entry.returned) + '</div>'
      : '';
    return '<article class="y12-rc-action is-unknown is-' + esc(entry.handling) + '">' +
      '<header class="y12-rc-action-head">' + Y12.ui.status(HANDLING_KIND[entry.handling], entry.handling_text) +
        '<code class="y12-code">' + esc(entry.id) + '</code>' + Y12.ui.tag('结果未知') + '</header>' +
      '<p class="y12-rc-action-sum">' + esc(entry.label || '') + '</p>' +
      Y12.ui.kv(rows, 'is-rows') + returned + '</article>';
  }

  function verifyBlock(r) {
    const list = r.unknown_actions.map(unknownCard).join('');
    const body = list ? '<div class="y12-rc-actions">' + list + '</div>' : Y12.ui.empty('没有结果未知的动作：所有动作都有回执');
    const queries = Y12.cap.query('machines.list') ? ['run.recovery', 'machines.list'] : 'run.recovery';
    return Y12.ui.block({
      id: 'rc-verify', title: '结果未知的动作', query: queries,
      subtitle: '重新启动时结果未知的动作：有核实方法的先自动核实（核实确认），其余作为工具结果交还发出它的会话（交还会话）；核实产生新的记录，不改写原始观察', body
    });
  }

  function ownerBlock(r) {
    const owner = r.owner
      ? Y12.ui.kv([['当前执行者', esc(r.owner.id)], ['取得时间', esc(Y12.ui.time(r.owner.since))], ['执行槽位', r.holds_slot ? '占用一个执行槽位' : '<span class="y12-muted">没有占用执行槽位</span>']], 'is-rows')
      : Y12.ui.kv([['当前执行者', '<span class="y12-muted">没有有效执行者</span>'], ['执行槽位', r.holds_slot ? '保留一个执行槽位' : '<span class="y12-muted">没有占用执行槽位</span>']], 'is-rows');
    const late = r.late_results.length
      ? '<h3 class="y12-h3">迟到结果</h3><p class="y12-small y12-muted">旧执行者的迟到回执作为历史事实列出，不推进状态。</p>' +
        '<ul class="y12-rc-late">' + r.late_results.map((entry) =>
          '<li><span class="y12-muted">' + esc(Y12.ui.time(entry.at)) + '</span><span>' + esc(entry.text) + '</span></li>').join('') + '</ul>'
      : '<p class="y12-small y12-muted">没有迟到结果。</p>';
    return Y12.ui.block({ id: 'rc-owner', title: '执行所有权', query: 'run.recovery', body: owner + late });
  }

  // 会话的用量各自累计（三部门的循环结构第 9 节）：部门主线与询问分支各是一个会话，询问分支的用量计入提问方
  function sessionsTable(r) {
    if (!r.sessions.length) return '';
    return '<h3 class="y12-h3">各会话的用量</h3>' + Y12.ui.table({
      columns: [
        { key: 'label', label: '会话', render: (row) => '<div class="y12-cell-stack"><strong>' + esc(row.label) + '</strong><small class="y12-muted">' + esc(row.department_text) + (row.kind === 'branch' ? ' · 询问分支' : ' · 部门主线') + '</small></div>' },
        { key: 'elapsed_sec', label: '已用时间', render: (row) => esc(Y12.ui.duration(row.elapsed_sec)) },
        { key: 'activations', label: '工作轮数', render: (row) => esc(row.activations) },
        { key: 'model_steps', label: '模型步骤', render: (row) => esc(row.model_steps) }
      ],
      rows: r.sessions
    });
  }

  function limitsBlock(r) {
    const l = r.limits;
    const waiting = l.waiting_provider_sec !== undefined
      ? '<div class="y12-rc-limit"><span>等待模型服务（不计入上限）</span><strong>' + esc(Y12.ui.duration(l.waiting_provider_sec)) + '</strong></div>'
      : '';
    const body = '<div class="y12-rc-limits">' +
      '<div class="y12-rc-limit is-wide"><span>已用时间与时间上限</span><strong>' + esc(Y12.ui.duration(r.run.elapsed_sec)) + ' / ' + esc(Y12.ui.duration(r.run.limit_sec)) + '</strong>' +
        Y12.ui.meter(r.run.elapsed_sec, r.run.limit_sec, { warnAt: 0.8 }) + '</div>' +
      '<div class="y12-rc-limit"><span>已用的工作轮数</span><strong>' + esc(l.activations || 0) + '</strong></div>' +
      '<div class="y12-rc-limit"><span>模型步骤</span><strong>' + esc(l.model_steps || 0) + '</strong></div>' +
      '<div class="y12-rc-limit"><span>重试尝试</span><strong>' + esc(l.retries || 0) + '</strong></div>' +
      waiting +
      '</div>' + sessionsTable(r) + '<p class="y12-small y12-muted">恢复不清零；发送状态未知的尝试仍然占用；用量未上报时显示未知，不填零。</p>';
    return Y12.ui.block({ id: 'rc-limits', title: '限额与会话的用量', query: 'run.recovery', body });
  }

  function upgradeBlock(r, oldRuns) {
    if (!r.upgrade) return '';
    const up = r.upgrade;
    const newRun = up.new_run_id
      ? Y12.ui.kv([
        ['新 run', esc(r.work_item.title) + '<small class="y12-muted">' + esc(up.new_run_id) + '</small>'],
        ['新 run 的 Yudao 版本', esc(up.new_yudao_version || '—')],
        ['队列位置', up.queue_pos != null ? '排队中第 ' + esc(up.queue_pos) + ' 位' : '—']
      ], 'is-rows')
      : '<p class="y12-muted">还没有重新开始的新 run。</p>';
    const runs = oldRuns.filter((entry) => entry.id === up.stopped_run_id);
    const events = runs.length && runs[0].events.length
      ? '<h3 class="y12-h3">旧 run 的事件（只读）</h3><ul class="y12-rc-events">' + runs[0].events.map((ev) =>
        '<li><span class="y12-muted">' + esc(Y12.ui.time(ev.at)) + '</span>' + Y12.ui.code(ev.type) + '<span>' + esc(ev.label) + '</span></li>').join('') + '</ul>'
      : '';
    return Y12.ui.block({
      id: 'rc-upgrade', title: '因升级停止', query: ['run.recovery', 'work_item.materials'],
      subtitle: '停止时的 Yudao 版本与从项目的起点重新开始的新 run（起点是采纳成果；没有采纳成果时是起始文件夹快照，都没有时是空树）',
      className: 'y12-rc-state-block is-interrupted',
      body: Y12.ui.kv([
        ['停止时的 Yudao 版本', esc(up.yudao_version || '—')],
        ['旧 run', esc(r.work_item.title) + '<small class="y12-muted">' + esc(up.stopped_run_id) + '</small>'],
        ['重新开始的起点', esc(up.start_point)]
      ], 'is-rows') + newRun + events
    });
  }

  function restartBlock(r) {
    if (!Y12.cap.command('onboarding.restart')) return '';
    if (r.work_item.kind !== 'onboarding') return '';
    const ov = Y12.api.query('project.overview', { project: r.project.id }).data;
    if (ov.project.source !== 'existing' || ov.adoption) return '';
    if (r.work_item.status !== 'stopped') return '';
    const dirs = ov.source_directories || [];
    if (!dirs.length) return '';
    const options = dirs.map((dir) => '<option value="' + esc(dir.name) + '">' + esc(dir.name) + ' · ' + esc(dir.path) + '</option>').join('');
    return Y12.ui.block({
      id: 'rc-restart', title: '重新开始建档', query: ['run.recovery', 'project.overview'], command: 'onboarding.restart',
      subtitle: '从登记的源目录重新采集快照，开始新的建档事项',
      body: '<div class="y12-form"><label class="y12-field"><span>源目录（登记名）</span><select class="y12-input" id="rc-restart-src">' + options + '</select></label>' +
        '<div class="y12-row">' + Y12.ui.button({ label: '重新开始建档', kind: 'primary', act: 'rc.restart', data: { project: r.project.id } }) + '</div></div>'
    });
  }

  function render(ctx) {
    const r = recovery(ctx.workItemId);
    const oldRuns = Y12.cap.query('work_item.materials')
      ? Y12.api.query('work_item.materials', { project: ctx.projectId, work_item: ctx.workItemId }).data.old_runs || []
      : [];
    return '<div class="y12-pp y12-rc">' +
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
    const oldRuns = Y12.cap.query('work_item.materials')
      ? Y12.api.query('work_item.materials', { project: ctx.projectId, work_item: ctx.workItemId }).data.old_runs || []
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

  Y12.views.register('recovery', {
    title: () => '恢复与动作核实',
    needs: { queries: ['run.recovery'] },
    render, update
  });

  Y12.actions.register('rc.restart', (el) => {
    const src = document.getElementById('rc-restart-src');
    Y12.run('onboarding.restart', { project: el.dataset.project, source_name: src ? src.value : '' });
  });
})();
