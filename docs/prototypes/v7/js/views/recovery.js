// 恢复与动作核实（设计说明第 4.3 节，3.1）：恢复观察状态、待恢复原因、继续执行、动作核实、限额、执行所有权与迟到结果。
// 注册页面 recovery、查询 run.recovery、命令 resumeRun；继续执行被接受后通过总线发出 x_resume_accepted。
(function () {
  'use strict';

  const Y7 = window.Y7;
  const esc = Y7.esc;
  const ui = Y7.ui;
  const kit = Y7.projectKit;
  if (!kit) throw new Error('recovery.js 需要先加载 js/views/overview.js（Y7.projectKit）');

  const STATES = ['running', 'interrupted', 'pending_verification', 'waiting_resume', 'terminated'];
  const PHASE_BY_DEPT = { product: 'PRODUCT_SPEC', engineering: 'ENGINEERING', quality: 'QUALITY' };
  const ACTION_KIND = { not_sent: 'idle', done: 'succeeded', unknown: 'unknown' };
  const TOOL_LABELS = {
    search: '搜索', read_range: '按区间阅读', read_file: '读取文件', edit_range: '按区间编辑', write_file: '写入文件', run_command: '执行登记命令'
  };

  // 恢复方式：可以自动继续、需要先确认外部结果、需要明确人工决定
  function recoveryMode(rec) {
    switch (rec.state) {
      case 'running': return '正在运行，不需要恢复';
      case 'interrupted': return (rec.unfinished || []).length ? '需要先确认外部结果：有已开始但没有回执的动作' : '可以自动继续：没有结果未知的动作';
      case 'pending_verification': return '需要先确认外部结果：核实未完成动作之后才能继续';
      case 'waiting_resume': return '需要明确人工决定：修复原因后由你继续执行';
      case 'terminated': return '已终止：不能通过恢复重新开始，需要时另开新事项';
      default: throw new Error('未知的恢复观察状态：' + rec.state);
    }
  }

  function roleName(roleId) {
    if (!roleId) return null;
    const catalog = Y7.resolve(Y7.data.catalog).roleCatalog;
    if (!catalog) return roleId;
    for (const dept of Object.keys(catalog)) {
      const found = (catalog[dept] || []).find((role) => role.id === roleId);
      if (found) return found.name;
    }
    return roleId;
  }

  // ---------------------------------------------------------------------------
  // 查询

  Y7.queries.register('run.recovery', (params) => {
    const item = Y7.workItem(params.workItemId);
    if (!item) throw new Error('事项不在当前档位或不存在：' + params.workItemId);
    const run = item.runId ? Y7.run(item.runId) : null;
    if (!run) throw new Error('事项没有 run：' + item.id);
    const project = Y7.project(item.projectId);
    const rec = run.recovery;
    if (!rec) throw new Error('恢复观察属于 3.1，当前档位没有恢复数据');
    const unfinished = rec.unfinished || [];
    const verifications = rec.verifications || [];
    const involved = run.actions.filter((action) => unfinished.includes(action.id) || verifications.some((v) => v.actionId === action.id) || (action.state && action.state !== 'done'));
    const actions = involved.map((action) => Object.assign({}, action, {
      unfinished: unfinished.includes(action.id),
      roleName: Y7.atLeast('s4') ? roleName(action.role) : null,
      verifications: verifications.filter((v) => v.actionId === action.id)
    }));
    const unusable = rec.unusable ? Object.assign({}, rec.unusable, { modelLabel: Y7.model.label(rec.unusable.model) }) : null;
    return {
      project, workItem: item, display: Y7.workItemStatus(item, run),
      run: {
        id: run.id, phase: run.phase, department: run.department, lastDepartment: run.lastDepartment || null, cycle: run.cycle,
        startedAt: run.startedAt, elapsedSec: run.elapsedSec, limitSec: run.limitSec, stopReason: run.stopReason
      },
      state: rec.state, reason: rec.reason, mode: recoveryMode(rec), unusable,
      lastConfirmed: rec.lastConfirmed, canResume: Boolean(rec.canResume), blockedReason: rec.resumeBlockedReason,
      nextActions: rec.nextActions || [], owner: rec.owner, lateResults: rec.lateResults || [], verifications,
      limits: rec.limits || null, actions,
      holdsSlot: Y7.resolve(Y7.data.runtime).slots.used.some((entry) => entry.workItemId === item.id),
      restartedAt: Y7.data.service && Y7.atLeast('s3') ? Y7.data.service.restartedAt : null
    };
  });

  // ---------------------------------------------------------------------------
  // 命令

  function pendingCount() {
    return Y7.data.runs.filter((run) => run.recovery && kit.RECOVERING.includes(run.recovery.state)).length;
  }

  // 继续执行：是否可用由服务端判断（recovery.canResume）；接受后从最后已确认位置之后接着进行，已用限额保留
  Y7.commands.register('resumeRun', (params) => {
    if (!Y7.atLeast('s3')) return { ok: false, message: '继续执行属于 3.1，切换到「Stage 3 与 D24」档后使用' };
    const item = Y7.raw.workItem(params.workItemId);
    if (!item) throw new Error('找不到事项：' + params.workItemId);
    const run = Y7.raw.run(item.runId);
    const rec = run.recovery;
    if (!rec) throw new Error('run 没有恢复数据：' + run.id);
    if (!rec.canResume) return { ok: false, message: '不能继续执行：' + (rec.resumeBlockedReason || '服务端判断当前不能继续') };
    const project = Y7.raw.project(item.projectId);
    if (project.archived) return { ok: false, message: '归档项目只读' };
    const runtime = Y7.data.runtime;
    if (!runtime.slots.used.some((entry) => entry.workItemId === item.id)) {
      const slots = Y7.runtime.slots();
      if (slots.used.length >= slots.total) return { ok: false, message: '不能继续执行：执行槽位已满（' + slots.used.length + ' / ' + slots.total + '），槽位空出后再继续' };
      runtime.slots.used.push({ workItemId: item.id, department: run.department || run.lastDepartment || 'product', role: null });
    }
    const dept = run.department || run.lastDepartment || 'product';
    if (!(dept in PHASE_BY_DEPT)) throw new Error('继续执行找不到部门对应的阶段：' + dept);
    if (Y7.TERMINAL_PHASES.includes(run.phase)) run.phase = PHASE_BY_DEPT[dept];
    run.department = dept;
    run.lastDepartment = dept;
    run.stopReason = null;
    Y7.setWorkItemStatus(item, 'in_progress');
    const from = rec.lastConfirmed ? rec.lastConfirmed.text : null;
    rec.state = 'running';
    rec.reason = null;
    rec.unusable = null;
    rec.canResume = false;
    rec.resumeBlockedReason = '事项正在运行，已有有效执行者';
    rec.nextActions = [];
    rec.owner = { id: Y7.uid('exec'), since: Y7.data.now };
    Y7.data.service.pendingResumeCount = pendingCount();
    const paths = ['workItems[id=' + item.id + ']', 'runs[id=' + run.id + ']', 'runtime', 'service'].concat(Y7.model.refreshRuns());
    // data-changed 发出之后再发出领域事件，画面先按新状态排好，再播放「伸懒腰回到工位」
    queueMicrotask(() => Y7.bus.emit('domain-event', {
      seq: Date.now(), type: 'x_resume_accepted', at: Y7.data.now, projectId: item.projectId, workItemId: item.id,
      department: dept, role: null, tool: null,
      label: '继续执行被接受：小人伸懒腰回到工位，灯亮起，时钟继续走', payload: {}
    }));
    return {
      ok: true,
      message: '继续执行已被接受：' + (from ? '从「' + from + '」之后' : '从最后已确认位置') + '接着进行，已完成的工作与已用限额保留',
      paths
    };
  });

  // ---------------------------------------------------------------------------
  // 页面

  let loop = null;

  // 中断、待核实、待恢复时写停在哪个部门，不沿用 run 终态阶段的文字
  function phaseText(r) {
    const dept = r.run.department || r.run.lastDepartment;
    const deptName = dept ? Y7.deptLabel(dept) : null;
    if (kit.RECOVERING.includes(r.state)) return deptName ? '停在' + deptName + '部门' : '尚未进入部门';
    return Y7.PHASE_LABELS[r.run.phase] + ' · ' + (r.run.department ? deptName : (deptName ? '最后在' + deptName : '未进入部门'));
  }

  function stateBlock(r) {
    const pills = STATES.map((state) => '<li class="y7-rc-state' + (state === r.state ? ' is-on is-' + state : '') + '"' + (state === r.state ? ' aria-current="step"' : '') + '>' +
      (state === r.state ? ui.status(Y7.RECOVERY_KIND[state], Y7.RECOVERY_LABELS[state]) : '<span>' + esc(Y7.RECOVERY_LABELS[state]) + '</span>') + '</li>').join('');
    const cancelled = r.run.stopReason && r.run.stopReason.code === 'cancelled';
    const pairs = [
      ['事项状态', ui.status(r.display.kind, r.display.text)],
      ['原因', r.reason ? esc(r.reason) : '<span class="y7-muted">没有需要恢复的原因</span>'],
      ['恢复方式', esc(r.mode)],
      ['最后已确认的位置', r.lastConfirmed ? '<span class="y7-pp-mono">seq ' + esc(r.lastConfirmed.seq) + '</span> · ' + esc(r.lastConfirmed.text) : '<span class="y7-muted">还没有已确认的位置</span>'],
      ['阶段与部门', esc(phaseText(r)) + (r.run.cycle ? ' · 第 ' + esc(r.run.cycle) + ' 轮' : '')],
      r.restartedAt ? ['服务重启', esc(ui.time(r.restartedAt)) + ' 重启；重启后由持久事实重建恢复观察状态'] : null,
      cancelled ? ['取消', '已停止执行 · ' + esc(r.run.stopReason.text) + '；先已生效的取消不能被继续执行越过'] : null
    ];
    const body = '<ol class="y7-rc-states" aria-label="恢复观察状态">' + pills + '</ol>' + ui.kv(pairs, 'is-rows') +
      '<ul class="y7-rc-rules"><li>重新连接事件流只补齐观察，不新建执行，也不重发模型请求或工具调用。</li><li>导出与重放只读取事件与工件，不触发执行。</li></ul>';
    return ui.block({ title: '恢复观察状态', tag: '3.1', level: 's3', query: 'run.recovery', body, className: 'y7-rc-state-block is-' + r.state });
  }

  function reasonBlock(r) {
    const pid = r.project.id;
    if (r.state === 'waiting_resume') {
      const u = r.unusable;
      const links = u && u.links && u.links.length
        ? u.links.map((link) => ui.button({ label: link.label, kind: 'small', go: link.go })).join('')
        : ui.button({ label: '打开模型管理', kind: 'small', go: Y7.paths.sys('models') }) + ui.button({ label: '打开本项目的部门设置', kind: 'small', go: Y7.paths.settings(pid) });
      const body = (u
        ? '<div class="y7-rc-unusable">' + ui.status('unusable', '模型引用无法使用') + '<strong>' + esc(u.problem) + '</strong></div>' +
          ui.kv([
            ['部门', esc(Y7.deptLabel(u.department))],
            ['模型', esc(u.modelLabel) + ' ' + ui.code(u.model)],
            ['具体问题', esc(u.problem)],
            u.credentialRef ? ['凭据引用', ui.code(u.credentialRef)] : null,
            u.http ? ['上游返回', esc('HTTP ' + u.http)] : null
          ], 'is-rows')
        : '<p class="y7-rc-reason">' + esc(r.reason || '') + '</p>') +
        '<div class="y7-row y7-rc-links">' + links + '</div>' +
        '<p class="y7-small y7-muted">修复后服务端重新判断能否继续执行；在本项目的部门设置另选模型只影响本项目，从这个部门下一次模型请求起生效。</p>';
      return ui.block({ title: '待恢复原因', tag: '3.1', level: 's3', query: ['run.recovery', 'catalog'], body, className: 'y7-rc-reason-block' });
    }
    if (r.state === 'interrupted') {
      const body = '<p class="y7-rc-reason">' + esc(r.reason || '服务进程停止') + '</p>' +
        ui.kv([['中断位置', r.lastConfirmed ? 'seq ' + esc(r.lastConfirmed.seq) + ' 之后 · 最后已确认：' + esc(r.lastConfirmed.text) : '<span class="y7-muted">还没有已确认的位置</span>']], 'is-rows') +
        '<p class="y7-small y7-muted">服务重启后按持久事实核对：已开始但没有回执的动作进入待核实，没有未完成动作时可以继续执行。</p>';
      return ui.block({ title: '中断位置', tag: '3.1', level: 's3', query: 'run.recovery', body, className: 'y7-rc-reason-block' });
    }
    return '';
  }

  function resumeBlock(r) {
    const recovering = kit.RECOVERING.includes(r.state);
    const button = ui.button({ label: '继续执行', kind: 'primary', cmd: 'resumeRun', data: { workItemId: r.workItem.id }, disabled: !r.canResume, title: r.canResume ? '服务端判断可以继续执行' : '不可用：' + (r.blockedReason || '') });
    const status = r.canResume
      ? '<p class="y7-rc-can">' + ui.status('running', '可以继续执行') + ' 原因已修复，从最后已确认位置之后接着进行</p>'
      : '<p class="y7-rc-cannot">' + ui.status(recovering ? 'waiting' : 'cancelled', '不可用') + ' <strong>' + esc(r.blockedReason || '服务端判断当前不能继续') + '</strong></p>';
    const cancel = recovering && !r.project.archived
      ? ui.button({ label: '取消事项', kind: 'danger', act: 'kit.cancel', data: { workItemId: r.workItem.id } })
      : '';
    const body = status + '<div class="y7-row">' + button + cancel + '</div>' +
      '<p class="y7-small y7-muted">是否可用由服务端判断：应用版本不兼容、事项已完成或已取消、已有有效执行者、原因尚未修复、先已生效的取消，都会使继续执行不可用。继续执行不清零已用限额，不重复已完成的动作。</p>';
    return ui.block({ title: '继续执行', tag: '3.1', level: 's3', query: 'run.recovery', command: ['resumeRun', 'cancelWorkItem'], body, className: 'y7-rc-resume' + (r.canResume ? ' is-ready' : '') });
  }

  function actionCard(action) {
    const state = action.state || 'done';
    const tool = TOOL_LABELS[action.tool] || action.tool;
    const receipt = action.receipt
      ? '<div class="y7-rc-receipt"><div class="y7-rc-receipt-head">' + kit.receiptOutcome(action) + '<span>主机回执：</span>' + ui.code((action.receipt.argv || [action.receipt.command]).join(' ')) +
        (action.receipt.snapshot ? '<span>快照</span>' + ui.code(action.receipt.snapshot) : '') + '</div>' + ui.pre(action.receipt.output || '') + '</div>'
      : '';
    const checks = action.verifications.length
      ? '<ol class="y7-rc-checks">' + action.verifications.map((v) => '<li><span class="y7-muted">' + esc(ui.time(v.at)) + '</span><div><b>核实依据</b>' + esc(v.basis) + '</div><div><b>核实结果</b>' + esc(v.result) + '</div></li>').join('') + '</ol>'
      : '<p class="y7-small y7-muted">还没有核实记录</p>';
    return '<article class="y7-rc-action is-' + esc(state) + '">' +
      '<header class="y7-rc-action-head">' + ui.code(action.id) + '<strong>' + esc(tool) + '</strong>' + ui.status(ACTION_KIND[state], Y7.ACTION_STATE_LABELS[state]) +
      (action.unfinished ? '<span class="y7-tag">未完成</span>' : '<span class="y7-tag">核实后确认</span>') + '</header>' +
      '<p class="y7-rc-action-sum">' + esc(action.summary) + '</p>' +
      ui.kv([
        ['所属部门', esc(Y7.deptLabel(action.department)) + (action.roleName ? ' · ' + esc(action.roleName) : '')],
        ['输入依据', esc(action.input)],
        ['执行前快照', action.before ? esc(action.before) : '<span class="y7-muted">没有记录</span>'],
        ['执行后快照', action.after ? esc(action.after) : '<span class="y7-muted">尚无（没有回执）</span>'],
        ['开始事件', action.startedEvent ? ui.code(action.startedEvent) + ' · ' + esc(ui.time(action.at)) : esc(ui.time(action.at))],
        ['观察到的结果', esc(action.result || '')]
      ], 'is-rows') + receipt +
      '<h4 class="y7-pp-sub">核实依据与结果</h4>' + checks + '</article>';
  }

  function nextActionsHtml(r) {
    if (!r.nextActions.length) return '<p class="y7-muted y7-small">没有需要处理的下一项操作</p>';
    return '<ol class="y7-rc-next">' + r.nextActions.map((next) => {
      let control;
      if (next.id === 'resume') control = ui.button({ label: next.label, kind: 'small primary', cmd: 'resumeRun', data: { workItemId: r.workItem.id }, disabled: !r.canResume });
      else if (next.go) control = ui.button({ label: next.label, kind: 'small', go: next.go });
      else if (next.id === 'cancel-queue') control = ui.button({ label: next.label, kind: 'small danger', cmd: 'cancelQueued', data: { workItemId: r.workItem.id } });
      else control = '<span class="y7-rc-next-text">' + esc(next.label) + '</span><small class="y7-muted">由服务端执行，结果追加到核实记录</small>';
      return '<li>' + control + '</li>';
    }).join('') + '</ol>';
  }

  function verifyBlock(r) {
    const cards = r.actions.length
      ? r.actions.map(actionCard).join('')
      : ui.empty('没有未完成的动作：所有动作都有回执');
    const log = r.verifications.length
      ? '<ol class="y7-rc-log">' + r.verifications.map((v) => '<li><span class="y7-muted">' + esc(ui.time(v.at)) + '</span> ' + ui.code(v.actionId) + ' ' + esc(v.result) + '</li>').join('') + '</ol>'
      : '<p class="y7-muted y7-small">还没有核实记录</p>';
    const body = ui.kv([['最后已确认的位置', r.lastConfirmed ? '<span class="y7-pp-mono">seq ' + esc(r.lastConfirmed.seq) + '</span> · ' + esc(r.lastConfirmed.text) : '<span class="y7-muted">还没有已确认的位置</span>']], 'is-rows') +
      '<h3 class="y7-h3">未完成与已核实的动作</h3><div class="y7-rc-actions">' + cards + '</div>' +
      '<h3 class="y7-h3">核实记录</h3><p class="y7-small y7-muted">核实记录追加保存，原始观察不改写。</p>' + log +
      '<h3 class="y7-h3">下一项合法操作</h3>' + nextActionsHtml(r);
    return ui.block({ title: '动作核实', tag: '3.1', level: 's3', query: ['run.recovery', 'run.actions'], command: 'resumeRun', body, className: 'y7-rc-verify' });
  }

  function limitsBlock(r) {
    const l = r.limits || { activations: 0, modelSteps: 0, retries: 0 };
    const body = '<div class="y7-rc-limits">' +
      '<div class="y7-rc-limit is-wide"><span class="y7-muted">已用时间与时间上限</span><strong>' + esc(ui.duration(r.run.elapsedSec)) + ' / ' + esc(ui.duration(r.run.limitSec)) + '</strong>' + ui.meter(r.run.elapsedSec, r.run.limitSec, { warnAt: 0.8 }) + '</div>' +
      '<div class="y7-rc-limit"><span class="y7-muted">部门激活</span><strong>' + esc(l.activations) + ' 次</strong></div>' +
      '<div class="y7-rc-limit"><span class="y7-muted">模型步骤</span><strong>' + esc(l.modelSteps) + '</strong></div>' +
      '<div class="y7-rc-limit"><span class="y7-muted">重试尝试</span><strong>' + esc(l.retries) + ' 次</strong></div>' +
      '<div class="y7-rc-limit"><span class="y7-muted">第几轮（只作为观察）</span><strong>第 ' + esc(r.run.cycle) + ' 轮</strong></div></div>' +
      '<p class="y7-small y7-muted">恢复不清零；发送状态未知的尝试仍然占用；用量未上报时显示未知，不填零。</p>';
    return ui.block({ title: '限额', tag: '3.1', level: 's3', query: 'run.recovery', body, className: 'y7-rc-limits-block' });
  }

  function ownerBlock(r) {
    const owner = r.owner
      ? ui.kv([['当前执行者', ui.code(r.owner.id)], ['取得时间', esc(kit.fullTime(r.owner.since))], ['执行槽位', r.holdsSlot ? '占用一个执行槽位' : '<span class="y7-muted">没有占用执行槽位</span>']], 'is-rows')
      : ui.kv([['当前执行者', '<span class="y7-muted">没有有效执行者</span>'], ['说明', esc(r.state === 'waiting_resume' ? '继续执行被接受时取得新的执行所有权' : r.state === 'terminated' ? '事项已终止，不再取得执行所有权' : '服务端确认之后取得执行所有权')], ['执行槽位', r.holdsSlot ? '确认或取消之前保留执行槽位' : '<span class="y7-muted">没有占用执行槽位</span>']], 'is-rows');
    const late = r.lateResults.length
      ? '<ol class="y7-rc-late">' + r.lateResults.map((entry) => '<li><span class="y7-muted">' + esc(kit.fullTime(entry.at)) + '</span>' + esc(entry.text) + '</li>').join('') + '</ol>'
      : '<p class="y7-muted y7-small">没有迟到结果</p>';
    const body = owner + '<h3 class="y7-h3">旧执行者的迟到结果</h3><p class="y7-small y7-muted">作为历史事实列出，不推进状态。</p>' + late;
    return ui.block({ title: '执行所有权', tag: '3.1', level: 's3', query: 'run.recovery', body, className: 'y7-rc-owner' });
  }

  function parts(ctx) {
    const r = Y7.query('run.recovery', { workItemId: ctx.workItem.id });
    return {
      state: stateBlock(r),
      reason: reasonBlock(r),
      resume: resumeBlock(r),
      verify: verifyBlock(r),
      side: limitsBlock(r) + ownerBlock(r),
      'rc-loop-list': kit.loopListHtml(ctx.project.id, ctx.workItem.id)
    };
  }

  Y7.views.register('recovery', {
    level: 's3',
    gateText: '恢复能力属于 3.1（单机可靠恢复）：恢复观察状态、待恢复原因、继续执行与动作核实。当前档位只显示已实现的能力。',
    title: () => '恢复与动作核实',
    render(ctx) {
      const p = parts(ctx);
      const head = kit.pageHead('恢复与动作核实 · 3.1', ctx.workItem.title,
        esc(ctx.project.name) + ' · 恢复观察状态由服务端按持久事实判断，界面只显示事实与服务端给出的下一项操作',
        ui.button({ label: '返回概览', icon: 'back', go: Y7.paths.overview(ctx.project.id, ctx.workItem.id) }));
      return '<div class="y7-pp y7-rc">' + head +
        kit.slot('state', p.state) +
        kit.slot('reason', p.reason) +
        kit.slot('resume', p.resume) +
        kit.loopBlock({ projectId: ctx.project.id, listHtml: p['rc-loop-list'], listSlot: 'rc-loop-list', title: '循环画面 · 本事项', subtitle: '中断时整层变暗、时钟停住；待核实的房间亮黄灯；待恢复的房间门口挂牌；继续执行后小人回到工位。其他事项变淡。' }) +
        kit.slot('verify', p.verify) +
        kit.slot('side', p.side, ' class="y7-grid-2 y7-rc-side"') +
        '</div>';
    },
    mount(ctx, root) {
      loop = kit.mountLoop(root, { projectId: ctx.project.id, focusId: ctx.workItem.id });
    },
    update(ctx, root) {
      if (loop) loop.refresh();
      kit.fillSlots(root, parts(ctx));
    },
    unmount() {
      if (loop) loop.destroy();
      loop = null;
    }
  });
})();
