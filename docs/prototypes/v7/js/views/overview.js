// 概览（设计说明第 4.1 节）：项目摘要、循环画面、当前事项、事项看板、流转记录、元观察发现。
// 注册查询 project.loop、project.flow、work_item.inputs，命令 retrieveCandidate、startIntegration。
// Y7.projectKit 放概览、恢复、资料三个页面共用的界面函数：结果标记、流转类型、循环画面的挂载、原始事件弹窗、取消确认。
(function () {
  'use strict';

  const Y7 = window.Y7;
  const esc = Y7.esc;
  const ui = Y7.ui;

  // ===========================================================================
  // 共用的界面函数

  const PLACE_LABELS = { user: '用户', product: '产品', engineering: '工程', quality: '质检', operations: '运维', adoption: '成果库' };
  const RECOVERING = ['interrupted', 'pending_verification', 'waiting_resume'];
  function place(id) {
    if (!(id in PLACE_LABELS)) throw new Error('未知的流转位置：' + id);
    return PLACE_LABELS[id];
  }

  function direction(from, to) {
    return '<span class="y7-pp-dir">' + esc(place(from)) + '<span class="y7-pp-arrow" aria-hidden="true">→</span><span class="y7-pp-sr">到</span>' + esc(place(to)) + '</span>';
  }

  function itemColor(index) {
    const colors = Y7.pixel && Y7.pixel.ITEM_COLORS;
    if (!colors || !colors[index]) throw new Error('事项颜色序号无效：' + index);
    return colors[index];
  }

  function swatch(index) {
    return '<span class="y7-pp-swatch" style="--item:' + itemColor(index) + '" aria-hidden="true"></span>';
  }

  function isRecovering(run) {
    return Boolean(run && run.recovery && Y7.atLeast('s3') && RECOVERING.includes(run.recovery.state));
  }

  // 模型请求完成、工具返回成功、质检放行、事项完成、项目采纳：各有自己的图标与文字
  const OUTCOME_ICONS = {
    model: '<rect x="4" y="4" width="8" height="8" rx="1.3"/><path d="M6.4 1.8v2.2M9.6 1.8v2.2M6.4 12v2.2M9.6 12v2.2M1.8 6.4h2.2M1.8 9.6h2.2M12 6.4h2.2M12 9.6h2.2"/><path d="M6.3 8.1l1.2 1.2 2.2-2.4"/>',
    tool: '<rect x="1.8" y="2.8" width="12.4" height="10.4" rx="1.4"/><path d="M4.4 6.2l2.1 1.8-2.1 1.8"/><path d="M8.3 10h3.3"/>'
  };

  function outcome(kind, text) {
    const chip = (cls, icon, label) => '<span class="y7-pp-outcome ' + cls + '">' + Y7.svg(icon, 'y7-status-icon') + '<span>' + esc(label) + '</span></span>';
    switch (kind) {
      case 'model': return chip('is-model', OUTCOME_ICONS.model, text || '模型请求完成');
      case 'tool': return chip('is-tool', OUTCOME_ICONS.tool, text || '工具返回成功');
      case 'toolFail': return chip('is-tool-fail', OUTCOME_ICONS.tool, text || '命令退出非零');
      case 'release': return ui.status('released', text || '质检放行');
      case 'done': return ui.status('done', text || '事项完成');
      case 'adopt': return ui.status('adopted', text || '项目采纳');
      default: throw new Error('未知的结果种类：' + kind);
    }
  }

  // 登记命令的回执：退出 0 为命令退出 0，其他为命令退出非零；超时、没有退出状态与被拒绝分开写
  function receiptOutcome(action) {
    if (action.skipped) return outcome('toolFail', '被拒绝：未登记的命令');
    const receipt = action.receipt;
    if (!receipt) return action.state === 'done' ? outcome('tool', '工具返回成功') : '';
    if (receipt.timedOut) return outcome('toolFail', '超时 ' + Math.round(receipt.durationMs / 1000) + ' 秒');
    if (receipt.exitCode === 0) return outcome('tool', '命令退出 0');
    if (receipt.exitCode === null || receipt.exitCode === undefined) return outcome('toolFail', '没有退出状态');
    return outcome('toolFail', '命令退出 ' + receipt.exitCode);
  }

  const FLOW_ICONS = {
    handoff: '<path d="M4 1.8h5.4L12.5 5v9.2H4z"/><path d="M9.2 1.8V5h3.3"/><path d="M6 8h4.4M6 10.6h4.4"/>',
    delivery: '<path d="M2.4 5.1L8 2.4l5.6 2.7v5.8L8 13.6l-5.6-2.7z"/><path d="M2.4 5.1L8 7.9l5.6-2.8M8 7.9v5.7"/>',
    answer: '<path d="M6.4 3.6L2.6 7.4l3.8 3.8"/><path d="M2.9 7.4h6.8a3.6 3.6 0 0 1 3.6 3.6v1.6"/>',
    rework: '<path d="M5.6 2.8L2.6 5.8l3 3"/><path d="M2.8 5.8h7a3.7 3.7 0 0 1 0 7.4H6.2"/>'
  };
  const FLOW_STATUS_ICON = { defect: 'unusable', ask: 'asking', release: 'released', adopt: 'adopted', held: 'held' };

  function flowLabel(kind) {
    if (kind === 'held' && !Y7.atLeast('s3')) return '基线已变';
    if (!(kind in Y7.FLOW_KIND_LABELS)) throw new Error('未知的流转类型：' + kind);
    return Y7.FLOW_KIND_LABELS[kind];
  }

  function flowKind(kind, text) {
    const icon = FLOW_ICONS[kind] ? Y7.svg(FLOW_ICONS[kind], 'y7-status-icon') : ui.icon(FLOW_STATUS_ICON[kind], 'y7-status-icon');
    return '<span class="y7-pp-flowkind is-' + esc(kind) + '">' + icon + '<span>' + esc(text || flowLabel(kind)) + '</span></span>';
  }

  function pageHead(eyebrow, title, subtitleHtml, actionsHtml) {
    return '<header class="y7-page-head y7-pp-head"><div class="y7-page-titles"><p class="y7-eyebrow">' + esc(eyebrow) + '</p><h1>' + esc(title) + '</h1>' +
      (subtitleHtml ? '<p class="y7-subtitle">' + subtitleHtml + '</p>' : '') + '</div>' +
      (actionsHtml ? '<div class="y7-page-actions">' + actionsHtml + '</div>' : '') + '</header>';
  }

  function slot(name, html, attrs) {
    return '<div data-slot="' + esc(name) + '"' + (attrs || '') + '>' + html + '</div>';
  }

  // 局部刷新：用新的 HTML 替换各个 data-slot 的内容，画布所在的部分不动
  function fillSlots(root, parts) {
    Object.keys(parts).forEach((name) => {
      const el = root.querySelector('[data-slot="' + name + '"]');
      if (!el) throw new Error('页面缺少区块位置：' + name);
      el.innerHTML = parts[name];
    });
  }

  const fullFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
  function fullTime(iso) {
    return fullFormat.format(new Date(iso));
  }

  function bytes(range) {
    if (!range) return '';
    return '字节 ' + range[0] + '–' + range[1];
  }

  // 原始事件：流转记录的一行对应 run 事件库中的一条事件
  function openFlowEvent(runId, eventId) {
    const run = Y7.run(runId);
    if (!run) throw new Error('找不到 run：' + runId);
    const record = run.flow.find((item) => item.eventId === eventId);
    if (!record) throw new Error('流转记录中找不到事件：' + eventId);
    const item = Y7.workItem(run.workItemId);
    const raw = { event_id: record.eventId, seq: record.seq, at: record.at, run_id: run.id, work_item_id: run.workItemId, from: record.from, to: record.to, kind: record.kind, content: record.content, status: record.status };
    ui.modal({
      title: '原始事件 ' + record.eventId,
      wide: true,
      body: ui.kv([
        ['事件编号', ui.code(record.eventId)],
        ['序号', esc('seq ' + record.seq)],
        ['时间', esc(fullTime(record.at))],
        ['事项', esc(item ? item.title : run.workItemId)],
        ['方向', direction(record.from, record.to)],
        ['类型', flowKind(record.kind)],
        ['状态', esc(record.status)]
      ]) +
        '<p class="y7-pp-event-content' + (record.kind === 'rework' ? ' is-rework' : '') + '">' + esc(record.content) + '</p>' +
        '<details class="y7-details" open><summary>事件原文</summary>' + ui.pre(JSON.stringify(raw, null, 2)) + '</details>',
      actions: [{ label: '关闭', close: true }]
    });
  }

  function confirmCancel(workItemId) {
    const item = Y7.workItem(workItemId);
    if (!item) throw new Error('找不到事项：' + workItemId);
    ui.modal({
      title: '取消事项',
      body: '<p>取消事项「' + esc(item.title) + '」？</p><p class="y7-muted y7-small">已完成的工作、输入记录与已用限额保留为历史；取消后事项不会自动重新开始，需要时另开新事项。</p>',
      actions: [
        { label: '不取消', close: true },
        { label: '取消事项', kind: 'primary danger', act: 'kit.cancelConfirm', data: { workItemId } }
      ]
    });
  }

  Y7.actions.register('kit.cancelConfirm', (el) => {
    const result = Y7.command('cancelWorkItem', { workItemId: el.dataset.workItemId });
    if (result.ok) ui.closeModal();
  });

  Y7.actions.register('kit.cancel', (el) => confirmCancel(el.dataset.workItemId));

  Y7.actions.register('kit.event', (el) => openFlowEvent(el.dataset.runId, el.dataset.eventId));

  // ---------------------------------------------------------------------------
  // 循环画面：画布、事件说明与文字列表

  const LOOP_HINT = '画面停在当前状态；用工具条播放场景时，这里显示驱动画面的事件';

  function judgmentText(result) {
    const map = { pass: '通过', fail: '不通过', uncertain: '不确定' };
    if (!(result in map)) throw new Error('未知的判定结果：' + result);
    return map[result];
  }

  function eventOutcome(ev) {
    const p = ev.payload || {};
    switch (ev.type) {
      case 'model_attempt_finished': return outcome('model');
      case 'tool_called':
        if (p.exitCode === 0) return outcome('tool', '命令退出 0');
        if (typeof p.exitCode === 'number') return outcome('toolFail', '命令退出 ' + p.exitCode);
        return ev.tool && ev.tool !== 'run_command' ? outcome('tool') : '';
      case 'tool_skipped': return outcome('toolFail', '工具被拒绝');
      case 'qa_submitted': return p.verdict === 'release' ? outcome('release') : flowKind('rework', p.verdict === 'rework_product' ? '返工 · 产品' : '返工 · 工程');
      case 'run_done': return outcome('done');
      case 'deliverable_adopted': return outcome('adopt', '项目采纳' + (p.version ? ' ' + p.version : ''));
      case 'adoption_held': return ui.status('held', Y7.atLeast('s3') ? '未采纳候选' : '基线已变');
      case 'x_judgment_recorded': return p.result ? ui.status(p.result === 'pass' ? 'admitted' : p.result === 'fail' ? 'failed' : 'unknown', '判定：' + judgmentText(p.result)) : '';
      default: return '';
    }
  }

  function eventLineHtml(ev) {
    if (!ev) return '<span class="y7-muted">' + esc(LOOP_HINT) + '</span>';
    return '<code class="y7-code">' + esc(ev.type) + '</code>' + eventOutcome(ev) + '<span>' + esc(ev.label || '') + '</span>';
  }

  function loopBlock(opts) {
    const last = Y7.state.scenario.lastEvent;
    const initial = last && last.projectId === opts.projectId ? last : null;
    return ui.block({
      title: opts.title || '循环画面',
      subtitle: opts.subtitle || '画面的每个动作由事项状态或事件决定；在顶栏选择一个事项时，其他事项变淡。画面下方的列表与画面内容相同。',
      level: 'now',
      query: ['project.loop', '事件流'],
      className: 'y7-pp-loop',
      body: '<div class="y7-pp-loop-stage"><canvas data-loop-canvas role="img" aria-label="三部门循环画面：大厅、产品、工程、质检与成果库；内容见下方列表"></canvas></div>' +
        '<p class="y7-pp-loop-event" data-loop-event aria-live="polite">' + eventLineHtml(initial) + '</p>' +
        slot(opts.listSlot || 'loop-list', opts.listHtml || '')
    });
  }

  function mountLoop(root, opts) {
    const canvas = root.querySelector('[data-loop-canvas]');
    if (!canvas) throw new Error('页面缺少循环画面的 canvas');
    if (!Y7.pixel || typeof Y7.pixel.createLoopScene !== 'function') throw new Error('像素画面未加载：需要 js/pixel/loop.js');
    const scene = Y7.pixel.createLoopScene(canvas, { level: Y7.state.level });
    const line = root.querySelector('[data-loop-event]');
    const refresh = () => {
      scene.setModel(Y7.query('project.loop', { projectId: opts.projectId, focusId: opts.focusId || null }));
      scene.focus(opts.focusId || null);
    };
    refresh();
    const onEvent = (ev) => {
      if (ev.projectId && ev.projectId !== opts.projectId) return;
      scene.playEvent(ev);
      if (line) line.innerHTML = eventLineHtml(ev);
    };
    Y7.bus.on('domain-event', onEvent);
    return {
      scene,
      refresh,
      destroy() {
        Y7.bus.off('domain-event', onEvent);
        scene.destroy();
      }
    };
  }

  // 循环画面里事项所在的位置（文字列表用）
  function loopPlace(item, loopItem) {
    if (item.status === 'queued') return '大厅排队' + (item.queuePos ? ' · 第 ' + item.queuePos + ' 位' : '');
    if (item.status === 'adopted') return '成果库 · 已采纳';
    if (item.status === 'held') return Y7.atLeast('s3') ? '成果库 · 未采纳候选' : '已放行，未采纳';
    if (loopItem && loopItem.department) {
      const name = Y7.deptLabel(loopItem.department);
      if (loopItem.status === 'asking') return name + ' · 门口等待回答';
      if (loopItem.sign) return name + ' · 门上挂「' + loopItem.sign + '」';
      return name;
    }
    return '未进入部门';
  }

  function loopListHtml(projectId, focusId) {
    const ov = Y7.query('project.overview', { projectId });
    const model = Y7.query('project.loop', { projectId, focusId });
    const byId = {};
    model.items.forEach((entry) => { byId[entry.id] = entry; });
    const rows = ov.workItems.map((item) => {
      const loopItem = byId[item.id] || null;
      const active = ['in_progress', 'queued'].includes(item.status) || (Y7.atLeast('s3') && RECOVERING.includes(item.recoveryState));
      const time = active && item.limitSec
        ? '<span class="y7-pp-loop-time"><span>已用 ' + esc(ui.duration(item.elapsedSec)) + ' / 上限 ' + esc(ui.duration(item.limitSec)) + '</span>' + ui.meter(item.elapsedSec, item.limitSec, { warnAt: 0.8 }) + '</span>'
        : '<span class="y7-pp-loop-time y7-muted">—</span>';
      return '<li class="y7-pp-loop-row' + (item.id === focusId ? ' is-focus' : '') + (focusId && item.id !== focusId ? ' is-dim' : '') + '">' +
        swatch(item.colorIndex) +
        '<button type="button" class="y7-link y7-pp-loop-title" data-go="' + esc(Y7.paths.overview(projectId, item.id)) + '">' + esc(item.title) + '</button>' +
        '<span class="y7-pp-loop-status">' + ui.status(item.display.kind, item.display.text) + '</span>' +
        '<span class="y7-pp-loop-place">' + esc(loopPlace(item, loopItem)) + '</span>' +
        '<span class="y7-pp-loop-cycle">' + (item.cycle ? '第 ' + item.cycle + ' 轮' : '未开始') + '</span>' +
        time + '</li>';
    }).join('');
    const facts = [];
    if (Y7.atLeast('s3') && model.slots) facts.push('<span class="y7-pp-loop-fact">' + ui.tag('3.4A') + '执行槽位 ' + model.slots.used + ' / ' + model.slots.total + '（全部项目共用）</span>');
    facts.push('<span class="y7-pp-loop-fact">成果库：' + (model.shelves.adopted.length ? esc('已采纳 ' + model.shelves.adopted.join('、')) : '尚未采纳') + '</span>');
    if (Y7.atLeast('s3')) facts.push('<span class="y7-pp-loop-fact">' + ui.tag('3.4B') + '未采纳候选：' + (model.shelves.held.length ? esc(model.shelves.held.map((h) => h.label).join('、')) : '没有') + '</span>');
    model.openRequests.forEach((request) => {
      const item = Y7.workItem(request.workItemId);
      facts.push('<span class="y7-pp-loop-fact">' + flowKind('ask', '询问中') + direction(request.from, request.to) + (item ? '（' + esc(item.title) + '）' : '') + '</span>');
    });
    if (model.ops) facts.push('<span class="y7-pp-loop-fact">' + ui.tag('Stage 5') + '运维：' + esc(model.ops.version + (model.ops.running ? ' 运行中' : ' 未运行')) + (model.ops.alarm ? ' · <strong class="y7-pp-loop-alarm">故障处理中</strong>' : '') + '</span>');
    if (model.observer) {
      const last = model.observer.last;
      facts.push('<span class="y7-pp-loop-fact">' + ui.tag('Stage 5') + '观察台：' + (last ? esc('最近判定 ' + judgmentText(last.result) + ' · 置信度 ' + Number(last.confidence).toFixed(2)) : '本项目还没有判定') + '</span>');
    }
    return '<ul class="y7-pp-loop-list" aria-label="画面中的事项">' + rows + '</ul><div class="y7-pp-loop-facts">' + facts.join('') + '</div>';
  }

  Y7.projectKit = {
    place, direction, itemColor, swatch, isRecovering, outcome, receiptOutcome, flowKind, flowLabel,
    pageHead, slot, fillSlots, fullTime, bytes, openFlowEvent, confirmCancel, loopBlock, mountLoop, loopListHtml, judgmentText,
    RECOVERING
  };

  // ===========================================================================
  // 查询

  // 循环画面中事项的状态：s3 起恢复观察状态优先
  function loopStatus(item, run) {
    if (isRecovering(run)) return run.recovery.state;
    switch (item.status) {
      case 'queued': return 'queued';
      case 'in_progress': return run && (run.requests || []).some((request) => request.status === 'open') ? 'asking' : 'running';
      case 'adopted': return 'adopted';
      case 'held': return 'held';
      case 'released_unsettled': return 'done';
      case 'not_started': return null;
      case 'stopped': {
        if (run && run.stopReason && run.stopReason.code === 'cancelled') return 'cancelled';
        if (run && run.phase === 'PAUSED') return 'paused';
        return 'failed';
      }
      default: throw new Error('未知事项状态：' + item.status);
    }
  }

  // 待核实的动作写登记名（登记命令）或工具名：登记名取主机回执或动作契约中的命令名
  function pendingActionName(run) {
    const rec = run.recovery;
    const unfinished = rec.unfinished || [];
    const action = run.actions.find((a) => unfinished.includes(a.id)) || run.actions.find((a) => a.state === 'unknown');
    if (!action) return null;
    if (action.tool !== 'run_command') return action.tool;
    if (action.receipt && action.receipt.command) return action.receipt.command;
    const decision = (rec.decisions || []).find((d) => d.actionId === action.id && d.contract);
    return decision ? decision.contract.command : action.tool;
  }

  // 门牌文字（BUILD.md 第 5.2 节）：待恢复、失败、暂停、中断、待核实、已取消写明原因，其他状态没有门牌
  function loopSign(status, run) {
    switch (status) {
      case 'waiting_resume': return run.recovery.unusable ? '待恢复：' + run.recovery.unusable.problem : '待恢复';
      case 'failed': return run.stopReason ? '失败：' + run.stopReason.text : '失败';
      case 'paused': return run.stopReason ? '已暂停：' + run.stopReason.text : '已暂停';
      case 'interrupted': return '中断';
      case 'pending_verification': {
        const name = pendingActionName(run);
        return name ? '待核实：' + name : '待核实';
      }
      case 'cancelled': return '已取消';
      default: return null;
    }
  }

  // 已采纳的版本：到当前采纳为止（场景回放较早的采纳时，架子上只放到那一版）
  function adoptedShelf(project) {
    const list = (project.adoptions || []).map((entry) => entry.version);
    if (!project.adoption) return list;
    const index = list.indexOf(project.adoption.version);
    if (index >= 0) return list.slice(0, index + 1);
    return list.concat([project.adoption.version]);
  }

  Y7.queries.register('project.loop', (params) => {
    const projectId = params.projectId || Y7.state.projectId;
    const project = Y7.project(projectId);
    if (!project) throw new Error('项目不在当前档位或不存在：' + projectId);
    const items = [];
    const openRequests = [];
    const held = [];
    Y7.workItemsOf(projectId).forEach((item) => {
      const run = item.runId ? Y7.run(item.runId) : null;
      if (run) (run.requests || []).filter((request) => request.status === 'open').forEach((request) => openRequests.push({ from: request.from, to: request.to, workItemId: item.id }));
      if (item.status === 'held' && Y7.atLeast('s3')) held.push({ id: item.id, label: item.title });
      const status = loopStatus(item, run);
      if (!status) return;
      const inRoom = !['queued', 'adopted', 'held'].includes(status);
      items.push({
        id: item.id, title: item.title, colorIndex: item.colorIndex, status,
        department: inRoom && run ? (run.department || run.lastDepartment || null) : null,
        cycle: run ? run.cycle : 0, elapsedSec: run ? run.elapsedSec : 0, limitSec: run ? run.limitSec : 7200,
        queuePos: item.queuePos || null, sign: run ? loopSign(status, run) : null
      });
    });
    const model = {
      level: Y7.state.level, items, focusId: params.focusId || null,
      shelves: { adopted: adoptedShelf(project), held }, openRequests, ops: null, observer: null
    };
    if (Y7.atLeast('s3')) {
      const slots = Y7.runtime.slots();
      model.slots = { total: slots.total, used: slots.used.length };
    }
    if (Y7.atLeast('s5')) {
      const ops = Y7.resolve(Y7.data.ops)[projectId];
      if (ops) {
        const open = ops.incidents.some((incident) => !incident.steps.some((step) => step.label === '确认恢复' && step.state === 'done'));
        model.ops = { running: Boolean(ops.responsibility), alarm: open, version: ops.responsibility ? ops.responsibility.version : null };
      }
      const judgments = Y7.query('meta.observations').judgments.filter((entry) => entry.projectId === projectId)
        .sort((a, b) => new Date(b.at) - new Date(a.at));
      model.observer = { active: true, last: judgments.length ? { result: judgments[0].result, confidence: judgments[0].confidence } : null };
    }
    return model;
  });

  Y7.queries.register('project.flow', (params) => {
    const projectId = params.projectId || Y7.state.projectId;
    if (!Y7.project(projectId)) throw new Error('项目不在当前档位或不存在：' + projectId);
    const rows = [];
    Y7.workItemsOf(projectId).filter((item) => !params.workItemId || item.id === params.workItemId).forEach((item) => {
      const run = item.runId ? Y7.run(item.runId) : null;
      if (!run) return;
      run.flow.forEach((record) => rows.push(Object.assign({}, record, { workItemId: item.id, title: item.title, colorIndex: item.colorIndex, runId: run.id })));
    });
    rows.sort((a, b) => (new Date(b.at) - new Date(a.at)) || (b.seq - a.seq));
    return rows;
  });

  Y7.queries.register('work_item.inputs', (params) => {
    const item = Y7.workItem(params.workItemId);
    if (!item) throw new Error('事项不在当前档位或不存在：' + params.workItemId);
    const project = Y7.project(item.projectId);
    const run = item.runId ? Y7.run(item.runId) : null;
    const recovering = isRecovering(run);
    const ended = !run || (Y7.TERMINAL_PHASES.includes(run.phase) && !(recovering && run.recovery.state === 'waiting_resume'));
    const cancellable = recovering || !['adopted', 'held', 'released_unsettled', 'stopped'].includes(item.status);
    let blocked = null;
    if (project.archived) blocked = '归档项目只读：查询仍可用，写命令会返回冲突';
    else if (ended) blocked = '事项已结束，不会自动新建';
    const inputs = (run ? run.inputs : []).map((input) => Object.assign({}, input, {
      kindLabel: input.kind === 'command' ? '系统命令' : (input.origin === 'operations' ? '运维提出' : '用户'),
      progressLabel: Y7.INPUT_PROGRESS_LABELS[input.progress]
    }));
    return {
      workItem: item,
      display: Y7.workItemStatus(item, run),
      run: run ? {
        id: run.id, phase: run.phase, department: run.department, lastDepartment: run.lastDepartment || null, cycle: run.cycle,
        elapsedSec: run.elapsedSec, limitSec: run.limitSec, stopReason: run.stopReason, source: run.source || null,
        recovery: run.recovery || null
      } : null,
      inputs,
      canAppend: !blocked,
      canCancel: cancellable && !project.archived,
      blockedReason: blocked
    };
  });

  // ===========================================================================
  // 命令

  function latestDelivery(workItemId) {
    const list = Y7.resolve(Y7.data.materials).filter((m) => m.workItemId === workItemId && m.kind === 'delivery');
    return list.sort((a, b) => b.version - a.version)[0] || null;
  }

  // 取回未采纳候选（3.4B）：取回候选成果的交付快照，当前采纳不变
  Y7.commands.register('retrieveCandidate', (params) => {
    if (!Y7.atLeast('s3')) return { ok: false, message: '取回未采纳候选属于 3.4B，切换到「Stage 3 与 D24」档后使用' };
    const item = Y7.raw.workItem(params.workItemId);
    if (!item) throw new Error('找不到事项：' + params.workItemId);
    const visible = Y7.workItem(item.id);
    if (!visible || visible.status !== 'held') return { ok: false, message: '事项「' + item.title + '」不是未采纳候选' };
    const delivery = latestDelivery(item.id);
    if (!delivery) return { ok: false, message: '候选「' + item.title + '」没有封存的交付，不能取回' };
    item.retrieved = { at: Y7.data.now, delivery: delivery.title, commit: delivery.git ? delivery.git.commit : null, files: delivery.files.length };
    return {
      ok: true,
      message: '已取回未采纳候选「' + item.title + '」：' + delivery.title + (delivery.git ? '（提交 ' + delivery.git.commit + '）' : '') + '，' + delivery.files.length + ' 个文件；当前采纳不变',
      paths: ['workItems[id=' + item.id + ']']
    };
  });

  // 以候选开始集成事项（3.4B）：集成事项有自己的合同与质检，不自动合并冲突
  Y7.commands.register('startIntegration', (params) => {
    if (!Y7.atLeast('s3')) return { ok: false, message: '以候选开始集成事项属于 3.4B，切换到「Stage 3 与 D24」档后使用' };
    const candidate = Y7.raw.workItem(params.workItemId);
    if (!candidate) throw new Error('找不到事项：' + params.workItemId);
    const visible = Y7.workItem(candidate.id);
    if (!visible || visible.status !== 'held') return { ok: false, message: '事项「' + candidate.title + '」不是未采纳候选' };
    const project = Y7.raw.project(candidate.projectId);
    if (project.archived) return { ok: false, message: '归档项目只读' };
    for (const dept of ['product', 'engineering', 'quality']) {
      const target = Y7.model.resolve(project.id, dept);
      if (!target.ok) return { ok: false, message: '不能开始集成事项：' + Y7.deptLabel(dept) + '部门的模型' + (target.model ? ' ' + target.model : '') + '无法使用（' + target.problem + '）' };
    }
    const baseline = project.adoption ? project.adoption.version : null;
    const text = (params.text || '').trim() || '把未采纳候选「' + candidate.title + '」的改动集成到当前采纳' + (baseline ? ' ' + baseline : '') + ' 上。';
    const workItemId = Y7.uid('w-int');
    const runId = Y7.uid('r-int');
    const used = Y7.data.workItems.filter((item) => item.projectId === project.id).map((item) => item.colorIndex);
    const free = [0, 1, 2, 3, 4, 5].find((index) => !used.includes(index));
    const item = {
      id: workItemId, projectId: project.id, title: '集成「' + candidate.title + '」到 ' + (baseline || '当前成果'),
      colorIndex: free === undefined ? used.length % 6 : free, status: 'in_progress', runId, queuePos: null, heldReason: null, fromCandidate: candidate.id
    };
    const run = Y7.emptyRun(runId, workItemId, project.id);
    run.inputs.push({ version: 1, kind: 'user', text, at: Y7.data.now, progress: 'received', bytes: [0, new TextEncoder().encode(text).length] });
    const runtime = Y7.data.runtime;
    const slots = Y7.runtime.slots();
    let message;
    if (slots.used.length >= slots.total) {
      item.status = 'queued';
      item.queuePos = runtime.queue.length + 1;
      runtime.queue.push({ workItemId, since: Y7.data.now, position: item.queuePos });
      message = '已开始集成事项「' + item.title + '」：执行槽位已满，排在第 ' + item.queuePos + ' 位';
    } else {
      runtime.slots.used.push({ workItemId, department: 'product', role: null });
      run.department = 'product';
      run.lastDepartment = 'product';
      run.cycle = 1;
      run.startedAt = Y7.data.now;
      run.recovery.owner = { id: Y7.uid('exec'), since: Y7.data.now };
      message = '已开始集成事项「' + item.title + '」，进入产品部门；候选本身保持未采纳';
    }
    Y7.data.workItems.push(item);
    Y7.data.runs.push(run);
    project.workItemIds.push(workItemId);
    return { ok: true, message, paths: ['workItems', 'runs', 'projects[id=' + project.id + '].workItemIds', 'runtime'], workItemId };
  });

  // ===========================================================================
  // 页面

  let loop = null;
  let flowAll = false;

  function activeItems(items) {
    const recovering = (item) => Y7.atLeast('s3') && RECOVERING.includes(item.recoveryState);
    const rank = (item) => (recovering(item) ? 1 : item.status === 'queued' ? 2 : 0);
    return items.filter((item) => item.status === 'in_progress' || item.status === 'queued' || recovering(item))
      .sort((a, b) => rank(a) - rank(b));
  }

  function stat(label, value, tag, kind) {
    return '<div class="y7-pp-stat' + (kind ? ' is-' + kind : '') + '"><span class="y7-pp-stat-num">' + esc(value) + '</span><span class="y7-pp-stat-label">' + esc(label) + (tag ? ui.tag(tag) : '') + '</span></div>';
  }

  // 1. 项目摘要
  function summaryBlock(ctx) {
    const ov = Y7.query('project.overview', { projectId: ctx.project.id });
    const p = ov.project;
    const adoption = ov.adoption;
    const fromItem = adoption && adoption.workItemId ? Y7.workItem(adoption.workItemId) : null;
    const adoptCard = adoption
      ? '<div class="y7-ov-adopt"><div class="y7-ov-adopt-top">' + outcome('adopt', '当前成果') + '<strong class="y7-ov-adopt-ver">' + esc(adoption.version) + '</strong></div>' +
        '<p>' + esc(adoption.summary) + '</p><small class="y7-muted">' + esc(ui.time(adoption.adoptedAt)) + ' 采纳' + (fromItem ? ' · 来自事项「' + esc(fromItem.title) + '」' : '') + '</small></div>'
      : '<div class="y7-ov-adopt is-empty"><span class="y7-muted y7-small">当前成果</span><strong>尚未采纳</strong><small class="y7-muted">事项放行并被项目采纳后，这里显示采纳的版本与摘要</small></div>';
    const stats = [stat('进行中', ov.stats.inProgress, null, 'running')];
    if (Y7.atLeast('s3')) stats.push(stat('排队中', ov.stats.queued, '3.4A', 'queued'));
    stats.push(stat('已采纳', ov.stats.adopted, null, 'adopted'));
    if (Y7.atLeast('s3')) stats.push(stat('未采纳候选', ov.stats.held, '3.4B', 'held'));
    else if (ov.stats.held) stats.push(stat('基线已变', ov.stats.held, null, 'held'));
    const running = ov.workItems.filter((item) => item.status === 'in_progress');
    const pending = ov.workItems.find((item) => item.pendingQuestion);
    const lines = [
      '<div><dt>进行中</dt><dd>' + (running.length ? running.map((item) => '<button type="button" class="y7-link" data-go="' + esc(Y7.paths.overview(p.id, item.id)) + '">' + esc(item.title) + '</button>').join('、') : '<span class="y7-muted">没有进行中的事项</span>') + '</dd></div>',
      '<div><dt>待决</dt><dd>' + (pending ? esc(pending.pendingQuestion) + ' <span class="y7-muted">（' + esc(pending.title) + '）</span>' : '<span class="y7-muted">没有待决问题</span>') + '</dd></div>'
    ];
    const body = '<div class="y7-ov-hero"><div class="y7-ov-hero-main"><p class="y7-eyebrow">项目概览</p><h1>' + esc(p.name) + '</h1>' +
      '<p class="y7-ov-goal"><span class="y7-muted">长期目标</span>' + esc(p.goal || '没有填写长期目标') + '</p>' +
      (p.archived ? ui.note('归档只读：查询仍可用，写命令会返回冲突。', 'warn') : '') +
      '</div>' + adoptCard + '</div>' +
      '<div class="y7-ov-stats">' + stats.join('') + '</div>' +
      '<dl class="y7-kv is-rows y7-ov-lines">' + lines.join('') + '</dl>';
    return ui.block({ level: 'now', query: 'project.overview', body, className: 'y7-ov-summary' });
  }

  // 3. 当前事项
  function inputList(info) {
    if (!info.inputs.length) return ui.empty('还没有输入记录');
    const steps = ['received', 'assigned', 'accepted'];
    return '<ol class="y7-ov-inputs">' + info.inputs.slice().reverse().map((input) => {
      const reached = steps.indexOf(input.progress);
      const progress = input.kind === 'command'
        ? '<p class="y7-small y7-muted">文本命令已执行</p>'
        : '<ol class="y7-ov-steps" aria-label="处理进度">' + steps.map((step, i) =>
          '<li class="' + (i < reached ? 'is-done' : i === reached ? 'is-current' : '') + '"' + (i === reached ? ' aria-current="step"' : '') + '>' + esc(Y7.INPUT_PROGRESS_LABELS[step]) + '</li>').join('') + '</ol>';
      return '<li class="y7-ov-input' + (input.kind === 'command' ? ' is-command' : '') + '">' +
        '<div class="y7-ov-input-head"><strong>' + esc(input.kindLabel) + ' · v' + esc(input.version) + '</strong>' +
        ui.tag(input.version === 1 ? '首次输入' : '追加') +
        '<span class="y7-muted">' + esc(ui.time(input.at)) + '</span>' + (input.bytes ? '<span class="y7-muted y7-pp-mono">' + esc(bytes(input.bytes)) + '</span>' : '') + '</div>' +
        '<p class="y7-ov-input-text">' + esc(input.text) + '</p>' + progress + '</li>';
    }).join('') + '</ol>';
  }

  function candidateNote(item) {
    const retrieved = item.retrieved
      ? '<p class="y7-small y7-ov-retrieved">已取回：' + esc(item.retrieved.delivery) + (item.retrieved.commit ? ' · 提交 ' + ui.code(item.retrieved.commit) : '') + ' · ' + esc(ui.time(item.retrieved.at)) +
        ' · <button type="button" class="y7-link" data-go="' + esc(Y7.paths.materials(item.projectId, item.id)) + '">在资料页查看与下载</button></p>'
      : '';
    return ui.note(ui.tag('3.4B') + ' ' + ui.status('held', '未采纳候选') + ' ' + esc(item.heldReason || '') + retrieved +
      '<span class="y7-note-actions">' + ui.button({ label: '取回候选', kind: 'small', cmd: 'retrieveCandidate', data: { workItemId: item.id } }) +
      ui.button({ label: '以候选开始集成事项', kind: 'small primary', act: 'ov.integrate', data: { workItemId: item.id } }) + '</span>', 'warn');
  }

  function itemNotes(ctx, item, info) {
    const pid = ctx.project.id;
    const notes = [];
    const run = info.run;
    if (item.fromCandidate) {
      const candidate = Y7.workItem(item.fromCandidate);
      notes.push(ui.note(ui.tag('3.4B') + ' 以未采纳候选「' + esc(candidate ? candidate.title : item.fromCandidate) + '」开始的集成事项：有自己的合同与质检，不自动合并冲突。', 'info'));
    }
    if (run && isRecovering(run)) {
      const rec = run.recovery;
      notes.push(ui.note(ui.status(Y7.RECOVERY_KIND[rec.state], Y7.RECOVERY_LABELS[rec.state]) + ' ' + esc(rec.reason || '') +
        '<span class="y7-note-actions">' + ui.button({ label: rec.state === 'waiting_resume' ? '查看原因并继续执行' : '查看恢复与动作核实', kind: 'small primary', go: Y7.paths.recovery(pid, item.id) }) + '</span>', 'warn'));
    } else if (item.status === 'queued') {
      notes.push(ui.note(ui.tag('3.4A') + ' 排队中' + (item.queuePos ? ' · 第 ' + esc(item.queuePos) + ' 位' : '') + '：执行槽位空出后进入产品部门。' +
        '<span class="y7-note-actions">' + ui.button({ label: '取消排队', kind: 'small danger', cmd: 'cancelQueued', data: { workItemId: item.id } }) + '</span>', 'info'));
    } else if (item.status === 'held') {
      notes.push(Y7.atLeast('s3') ? candidateNote(item) : ui.note(ui.status('held', '基线已变') + ' 质检已放行，但开始时的基线已被新的采纳取代，成果没有被采纳。', 'warn'));
    } else if (item.status === 'adopted') {
      const entry = (ctx.project.adoptions || []).find((a) => a.workItemId === item.id);
      notes.push(ui.note(outcome('done') + ' ' + outcome('adopt', '项目采纳' + (entry ? ' ' + entry.version : '')) + ' 事项已完成，成果已被项目采纳。'));
    } else if (item.status === 'released_unsettled') {
      notes.push(ui.note(outcome('release') + ' 质检已放行，等待项目采纳。'));
    } else if (item.status === 'stopped' && run && run.stopReason) {
      notes.push(ui.note(ui.status(item.display.kind, item.display.text) + ' ' + esc(run.stopReason.text) + ' ' + ui.code(run.stopReason.code), 'warn'));
    }
    if (run && run.source) {
      notes.push('<p class="y7-ov-source">' + ui.tag('3.2A') + ' 代码快照：' + ui.code(run.source.dir) + (run.source.digest ? ' · ' + ui.code(run.source.digest) : '') + (run.source.files ? ' · ' + esc(run.source.files) + ' 个文件' : '') + '</p>');
    }
    return notes.join('');
  }

  function currentBody(ctx, target, active) {
    const pid = ctx.project.id;
    const switcher = !ctx.workItem && active.length > 1
      ? '<div class="y7-ov-switch"><span class="y7-muted y7-small">同时进行的事项：</span>' + active.map((item) =>
        '<button type="button" class="y7-pp-chip' + (target && item.id === target.id ? ' is-on' : '') + '" data-go="' + esc(Y7.paths.overview(pid, item.id)) + '">' + swatch(item.colorIndex) + esc(item.title) + '</button>').join('') + '</div>'
      : '';
    if (!target) return switcher + '<p class="y7-muted">没有进行中的事项。输入想法后可以记录原文，或作为新事项开始。</p>';
    const info = Y7.query('work_item.inputs', { workItemId: target.id });
    const run = info.run;
    const deptText = run && run.department ? Y7.deptLabel(run.department) : (run && run.lastDepartment ? '最后在' + Y7.deptLabel(run.lastDepartment) : '未进入部门');
    let phase = run ? Y7.PHASE_LABELS[run.phase] : '没有 run';
    if (target.status === 'queued') phase = '等待执行槽位';
    else if (target.status === 'not_started') phase = '未开始';
    else if (run && isRecovering(run)) phase = Y7.RECOVERY_LABELS[run.recovery.state];
    const head = '<div class="y7-ov-item-head">' + swatch(target.colorIndex) + '<h3>' + esc(target.title) + '</h3>' + ui.status(info.display.kind, info.display.text) + '</div>' +
      '<div class="y7-ov-item-meta">' +
      '<span>' + esc(phase) + '</span><span>所在部门：' + esc(deptText) + '</span>' +
      (run && run.cycle ? '<span>第 ' + esc(run.cycle) + ' 轮</span>' : '') +
      (run ? '<span class="y7-ov-time"><span>已用 ' + esc(ui.duration(run.elapsedSec)) + ' / 上限 ' + esc(ui.duration(run.limitSec)) + '</span>' + ui.meter(run.elapsedSec, run.limitSec, { warnAt: 0.8 }) + '</span>' : '') +
      '</div>';
    return switcher + head + itemNotes(ctx, target, info) + '<h3 class="y7-h3">输入记录与处理进度</h3>' + inputList(info);
  }

  function newComposer(project) {
    const pid = project.id;
    return '<div class="y7-ov-composer">' +
      '<label class="y7-field"><span>新的想法或材料</span><textarea class="y7-textarea" rows="3" id="y7-ov-new" data-draft="ov.new.' + esc(pid) + '" placeholder="描述这次要改变什么，或先记下原文"></textarea></label>' +
      '<label class="y7-field"><span>可信源目录（可选）' + ui.tag('3.2A') + '</span><input type="text" class="y7-input" id="y7-ov-src" data-draft="ov.src.' + esc(pid) + '" placeholder="例如 D:/work/report-tool"><small class="y7-muted">作为新事项的代码快照：只读取目录内容，不修改源目录</small></label>' +
      '<div class="y7-ov-composer-foot"><small class="y7-muted">记录原文只保存为项目材料，不调用模型，也不注入后续事项；作为新事项开始时进入产品部门</small>' +
      '<div class="y7-row">' + ui.button({ label: '记录原文', act: 'ov.record', data: { projectId: pid } }) + ui.button({ label: '作为新事项开始', kind: 'primary', act: 'ov.create', data: { projectId: pid } }) + '</div></div></div>';
  }

  function appendComposer(target, info) {
    return '<div class="y7-ov-composer">' +
      '<label class="y7-field"><span>追加需求 · 「' + esc(target.title) + '」</span><textarea class="y7-textarea" rows="3" id="y7-ov-append" data-draft="ov.append.' + esc(target.id) + '" placeholder="补充或修改这个事项的要求；输入 /stop 或 /cancel 立即停止"></textarea></label>' +
      '<div class="y7-ov-composer-foot"><small class="y7-muted">提交后进入当前事项的产品入口，由产品部门处理</small><div class="y7-row">' +
      (info.canCancel ? ui.button({ label: '取消事项', kind: 'danger', act: 'kit.cancel', data: { workItemId: target.id } }) : '') +
      ui.button({ label: '发送', kind: 'primary', act: 'ov.append', data: { workItemId: target.id } }) + '</div></div></div>';
  }

  // 输入框：选中进行中的事项时为追加需求；没有进行中的事项或事项已结束时为记录原文与新事项；s3 起可以另开并行的新事项
  function composer(ctx, target) {
    const project = ctx.project;
    if (project.archived) return { sig: 'archived', html: ui.note('归档项目只读：不能追加需求、记录原文或新建事项。', 'warn') };
    if (!target) return { sig: 'new', html: newComposer(project) };
    const info = Y7.query('work_item.inputs', { workItemId: target.id });
    if (!info.canAppend) {
      return { sig: 'ended:' + target.id, html: ui.note(esc(info.blockedReason) + '。输入会作为新事项或项目材料。', 'info') + newComposer(project) };
    }
    const parallel = Y7.atLeast('s3')
      ? '<details class="y7-details y7-ov-parallel"><summary>另开一个新事项 ' + ui.tag('3.4B') + '</summary><p class="y7-small y7-muted">同一项目的多个事项可以同时进行，各自使用开始时的基线与独立的工作区；执行槽位已满时新事项排队。</p>' + newComposer(project) + '</details>'
      : '';
    return { sig: 'append:' + target.id + ':' + info.canCancel, html: appendComposer(target, info) + parallel };
  }

  function currentTarget(ctx) {
    const ov = Y7.query('project.overview', { projectId: ctx.project.id });
    const active = activeItems(ov.workItems);
    const target = ctx.workItem ? ov.workItems.find((item) => item.id === ctx.workItem.id) : (active[0] || null);
    return { active, target };
  }

  function currentBlock(ctx) {
    const t = currentTarget(ctx);
    const c = composer(ctx, t.target);
    const commands = ['addInput', 'cancelWorkItem', 'recordMaterial', 'createWorkItem'];
    if (Y7.atLeast('s3')) commands.push('cancelQueued', 'retrieveCandidate', 'startIntegration');
    return ui.block({
      title: '当前事项',
      subtitle: ctx.workItem ? '顶栏选中的事项：输入记录、处理进度与追加需求' : '范围为整个项目时显示进行中的事项；在顶栏选择事项查看其他事项',
      level: 'now',
      query: 'work_item.inputs',
      command: commands,
      className: 'y7-ov-current',
      body: slot('current-body', currentBody(ctx, t.target, t.active)) + slot('composer', c.html, ' data-sig="' + esc(c.sig) + '"')
    });
  }

  // 4. 事项看板
  const COLUMNS = [
    { id: 'queued', label: '排队中', level: 's3', tag: '3.4A' },
    { id: 'product', label: '产品' },
    { id: 'engineering', label: '工程' },
    { id: 'quality', label: '质检' },
    { id: 'operations', label: '运维', level: 's5', tag: 'Stage 5', onlyIfUsed: true },
    { id: 'released', label: '已放行' },
    { id: 'adopted', label: '已采纳' },
    { id: 'held', label: '未采纳候选', level: 's3', tag: '3.4B' }
  ];
  const DEPT_IDS = ['product', 'engineering', 'quality', 'operations'];

  function boardColumn(item) {
    if (item.status === 'queued') return 'queued';
    if (item.status === 'adopted') return 'adopted';
    if (item.status === 'released_unsettled') return 'released';
    if (item.status === 'held') return Y7.atLeast('s3') ? 'held' : 'released';
    const dept = item.department || item.lastDepartment;
    return DEPT_IDS.includes(dept) ? dept : 'product';
  }

  function cardDetail(item) {
    const run = item.runId ? Y7.run(item.runId) : null;
    if (Y7.atLeast('s3') && RECOVERING.includes(item.recoveryState)) {
      const rec = run.recovery;
      return rec.state === 'waiting_resume' && rec.unusable ? '待恢复：' + Y7.deptLabel(rec.unusable.department) + '部门的模型' + rec.unusable.problem : (rec.resumeBlockedReason || rec.reason || '');
    }
    if (item.pendingQuestion) return '待决：' + item.pendingQuestion;
    if (item.status === 'queued') return '第 ' + (item.queuePos || '?') + ' 位，等待执行槽位';
    if (item.status === 'held' && item.heldReason) return item.heldReason;
    if (item.status === 'stopped' && item.stopReason) return item.stopReason.text;
    if (item.status === 'adopted') {
      const project = Y7.project(item.projectId);
      const entry = (project.adoptions || []).find((a) => a.workItemId === item.id);
      return entry ? '项目采纳为 ' + entry.version : '已被项目采纳';
    }
    if (item.status === 'not_started') return '';
    return item.phase ? Y7.PHASE_LABELS[item.phase] : '';
  }

  function boardCard(ctx, item) {
    const pid = ctx.project.id;
    const dept = item.department || item.lastDepartment;
    const inDept = DEPT_IDS.includes(dept);
    const go = inDept && item.status !== 'queued' ? Y7.paths.dept(pid, dept, item.id) : Y7.paths.overview(pid, item.id);
    const where = item.status === 'queued' ? '大厅排队' : item.status === 'adopted' ? '成果库' : item.department ? '所在部门：' + Y7.deptLabel(item.department) : (inDept ? '最后在' + Y7.deptLabel(dept) : '未进入部门');
    const recovering = Y7.atLeast('s3') && RECOVERING.includes(item.recoveryState);
    const actions = [];
    if (recovering) actions.push(ui.button({ label: '查看恢复', kind: 'small', go: Y7.paths.recovery(pid, item.id) }));
    if (item.status === 'queued') actions.push(ui.button({ label: '取消排队', kind: 'small danger', cmd: 'cancelQueued', data: { workItemId: item.id } }));
    if (item.status === 'held' && Y7.atLeast('s3')) {
      actions.push(ui.button({ label: '取回候选', kind: 'small', cmd: 'retrieveCandidate', data: { workItemId: item.id } }));
      actions.push(ui.button({ label: '以候选开始集成', kind: 'small primary', act: 'ov.integrate', data: { workItemId: item.id } }));
    }
    const selected = ctx.workItem && ctx.workItem.id === item.id;
    const detail = cardDetail(item);
    return '<article class="y7-ov-card' + (selected ? ' is-selected' : '') + (recovering ? ' is-alert' : '') + '" style="--item:' + itemColor(item.colorIndex) + '">' +
      '<button type="button" class="y7-pp-title" data-go="' + esc(go) + '">' + esc(item.title) + '</button>' +
      '<div class="y7-ov-card-status">' + ui.status(item.display.kind, item.display.text) + '</div>' +
      '<p class="y7-ov-card-meta">' + esc(where) + (item.cycle ? ' · 第 ' + esc(item.cycle) + ' 轮' : '') + '</p>' +
      (detail ? '<p class="y7-ov-card-detail">' + esc(detail) + '</p>' : '') +
      (item.retrieved ? '<p class="y7-ov-card-detail">已取回 ' + esc(item.retrieved.delivery) + ' · ' + esc(ui.time(item.retrieved.at)) + '</p>' : '') +
      (item.fromCandidate ? '<p class="y7-ov-card-detail">' + ui.tag('3.4B') + ' 集成事项</p>' : '') +
      (actions.length ? '<div class="y7-ov-card-actions">' + actions.join('') + '</div>' : '') +
      '</article>';
  }

  function boardBlock(ctx) {
    const ov = Y7.query('project.overview', { projectId: ctx.project.id });
    const groups = {};
    ov.workItems.forEach((item) => {
      const col = boardColumn(item);
      (groups[col] = groups[col] || []).push(item);
    });
    const columns = COLUMNS.filter((col) => Y7.atLeast(col.level) && (!col.onlyIfUsed || (groups[col.id] || []).length));
    // 宽屏时有事项的列更宽，空列收窄
    const widths = columns.map((col) => ((groups[col.id] || []).length ? 'minmax(150px, 1.5fr)' : 'minmax(76px, .7fr)')).join(' ');
    const body = '<div class="y7-ov-board" style="--board:' + widths + '">' + columns.map((col) => {
      const cards = groups[col.id] || [];
      return '<section class="y7-ov-board-col is-' + col.id + (cards.length ? '' : ' is-empty') + '" aria-label="' + esc(col.label) + '"><header class="y7-ov-board-head"><h3>' + esc(col.label) + '</h3>' + (col.tag ? ui.tag(col.tag) : '') + '<span class="y7-count">' + cards.length + '</span></header>' +
        (cards.length ? cards.map((item) => boardCard(ctx, item)).join('') : '<p class="y7-ov-board-empty">没有事项</p>') + '</section>';
    }).join('') + '</div>';
    return ui.block({
      title: '事项看板',
      subtitle: '卡片不可拖拽；点击标题进入该事项所在部门的工作间' + (Y7.atLeast('s3') ? '，排队中的事项进入概览' : ''),
      level: 'now', query: 'project.overview', command: Y7.atLeast('s3') ? ['cancelQueued', 'retrieveCandidate', 'startIntegration'] : null, body
    });
  }

  // 5. 流转记录：宽屏为表格样式的行，窄屏为紧凑的卡片
  function flowRow(row, showItem) {
    return '<li class="y7-ov-flow-row' + (row.kind === 'rework' ? ' is-rework' : '') + '">' +
      '<span class="y7-ov-flow-time">' + esc(ui.time(row.at)) + '</span>' +
      (showItem ? '<span class="y7-ov-flow-item">' + swatch(row.colorIndex) + '<span>' + esc(row.title) + '</span></span>' : '') +
      '<span class="y7-ov-flow-dir">' + direction(row.from, row.to) + '</span>' +
      '<span class="y7-ov-flow-kind">' + flowKind(row.kind) + '</span>' +
      '<span class="y7-ov-flow-content">' + esc(row.content) + '</span>' +
      '<span class="y7-ov-flow-status">' + esc(row.status) + '</span>' +
      '<span class="y7-ov-flow-event"><button type="button" class="y7-link y7-pp-mono" data-act="kit.event" data-run-id="' + esc(row.runId) + '" data-event-id="' + esc(row.eventId) + '" title="查看原始事件">' + esc(row.eventId) + '</button></span>' +
      '</li>';
  }

  function flowBlock(ctx) {
    const rows = Y7.query('project.flow', { projectId: ctx.project.id, workItemId: ctx.workItem ? ctx.workItem.id : null });
    const shown = flowAll ? rows : rows.slice(0, 12);
    const showItem = !ctx.workItem;
    const head = '<li class="y7-ov-flow-row is-head" aria-hidden="true"><span>时间</span>' + (showItem ? '<span>事项</span>' : '') + '<span>方向</span><span>类型</span><span>内容</span><span>状态</span><span>原始事件</span></li>';
    const list = rows.length
      ? '<ol class="y7-ov-flow' + (showItem ? ' has-item' : '') + '" aria-label="流转记录">' + head + shown.map((row) => flowRow(row, showItem)).join('') + '</ol>'
      : ui.empty(ctx.workItem ? '这个事项还没有跨部门流转' : '项目还没有跨部门流转');
    const more = rows.length > 12
      ? '<div class="y7-row y7-ov-flow-more">' + ui.button({ label: flowAll ? '只显示最近 12 条' : '显示全部 ' + rows.length + ' 条', kind: 'small', act: 'ov.flowAll' }) + '</div>'
      : '';
    return ui.block({
      title: '流转记录',
      subtitle: '部门之间的交接、交付、问题反馈、咨询与返工，最新的在上；返工用醒目的颜色，点击事件编号查看原始事件',
      level: 'now', query: 'project.flow', body: list + more
    });
  }

  // 6. 元观察发现（Stage 5）
  function metaBlock(ctx) {
    if (!Y7.atLeast('s5')) return '';
    const pid = ctx.project.id;
    const meta = Y7.query('meta.observations');
    const flows = Y7.query('project.flow', { projectId: pid });
    const count = (kinds) => flows.filter((row) => kinds.includes(row.kind)).length;
    const stats = [['交接', count(['handoff', 'delivery'])], ['询问与回答', count(['ask', 'answer'])], ['问题反馈', count(['defect'])], ['放行', count(['release'])], ['返工', count(['rework'])]];
    const nonconform = meta.findings.filter((entry) => entry.projectId === pid && !entry.ok);
    const judgments = meta.judgments.filter((entry) => entry.projectId === pid).sort((a, b) => new Date(b.at) - new Date(a.at));
    const body = '<div class="y7-ov-stats">' + stats.map((s) => stat(s[0], s[1])).join('') + stat('不符合项', nonconform.length, null, nonconform.length ? 'alert' : null) + '</div>' +
      (nonconform.length ? '<ul class="y7-ov-findings">' + nonconform.slice(0, 4).map((f) => '<li><strong>' + esc(f.rule) + '</strong><span>' + esc(f.text) + '</span><small class="y7-muted">' + esc(f.where) + ' · ' + esc(ui.time(f.at)) + '</small></li>').join('') + '</ul>' : '<p class="y7-muted y7-small">本项目没有不符合项。</p>') +
      (judgments.length ? '<p class="y7-small y7-ov-judgment">最近判定：' + esc(judgments[0].handoff) + ' · ' + esc(judgmentText(judgments[0].result)) + ' · 置信度 ' + esc(Number(judgments[0].confidence).toFixed(2)) + ' · ' + esc(judgments[0].route) + '</p>' : '');
    return ui.block({
      title: '元观察发现', tag: 'Stage 5', level: 's5', query: ['meta.observations', 'project.flow'],
      subtitle: '本项目的流转统计（由流转记录计算）与规则审查的不符合项',
      actions: ui.button({ label: '查看元观察', kind: 'small', go: Y7.paths.sys('meta') }),
      body
    });
  }

  function parts(ctx) {
    const t = currentTarget(ctx);
    return {
      summary: summaryBlock(ctx),
      'loop-list': loopListHtml(ctx.project.id, ctx.workItem ? ctx.workItem.id : null),
      'current-body': currentBody(ctx, t.target, t.active),
      board: boardBlock(ctx),
      flow: flowBlock(ctx),
      meta: metaBlock(ctx)
    };
  }

  Y7.views.register('overview', {
    title: () => '概览',
    render(ctx) {
      const p = parts(ctx);
      return '<div class="y7-pp y7-ov">' +
        slot('summary', p.summary) +
        loopBlock({ projectId: ctx.project.id, listHtml: p['loop-list'] }) +
        currentBlock(ctx) +
        slot('board', p.board) +
        slot('flow', p.flow) +
        slot('meta', p.meta) +
        '</div>';
    },
    mount(ctx, root) {
      loop = mountLoop(root, { projectId: ctx.project.id, focusId: ctx.workItem ? ctx.workItem.id : null });
    },
    update(ctx, root) {
      if (loop) loop.refresh();
      fillSlots(root, parts(ctx));
      const c = composer(ctx, currentTarget(ctx).target);
      const box = root.querySelector('[data-slot="composer"]');
      if (box.dataset.sig !== c.sig) {
        box.innerHTML = c.html;
        box.dataset.sig = c.sig;
      }
    },
    unmount() {
      if (loop) loop.destroy();
      loop = null;
    }
  });

  // ===========================================================================
  // 界面动作

  Y7.actions.register('ov.append', (el) => {
    const box = document.getElementById('y7-ov-append');
    const result = Y7.command('addInput', { workItemId: el.dataset.workItemId, text: box.value, draftKey: box.dataset.draft });
    if (result.ok) box.value = '';
  });

  Y7.actions.register('ov.record', (el) => {
    const box = document.getElementById('y7-ov-new');
    const result = Y7.command('recordMaterial', { projectId: el.dataset.projectId, text: box.value, draftKey: box.dataset.draft });
    if (result.ok) box.value = '';
  });

  Y7.actions.register('ov.create', (el) => {
    const box = document.getElementById('y7-ov-new');
    const src = document.getElementById('y7-ov-src');
    const result = Y7.command('createWorkItem', { projectId: el.dataset.projectId, text: box.value, sourceDir: src.value.trim() || null, draftKey: box.dataset.draft });
    if (!result.ok) return;
    box.value = '';
    src.value = '';
    Y7.clearDraft(src.dataset.draft);
    Y7.go(Y7.paths.overview(el.dataset.projectId, result.workItemId));
  });

  Y7.actions.register('ov.flowAll', () => {
    flowAll = !flowAll;
    fillSlots(Y7.dom.content, { flow: flowBlock(Y7.ctx()) });
  });

  Y7.actions.register('ov.integrate', (el) => {
    const item = Y7.workItem(el.dataset.workItemId);
    if (!item) throw new Error('找不到事项：' + el.dataset.workItemId);
    const project = Y7.project(item.projectId);
    const delivery = latestDelivery(item.id);
    const baseline = project.adoption ? project.adoption.version : null;
    ui.modal({
      title: '以候选开始集成事项',
      body: ui.kv([
        ['未采纳候选', esc(item.title)],
        ['候选的交付', delivery ? esc(delivery.title + ' · ' + delivery.summary) + (delivery.git ? ' · ' + ui.code(delivery.git.commit) : '') : '<span class="y7-muted">没有封存的交付</span>'],
        ['当前采纳', esc(baseline ? baseline + ' · ' + project.adoption.summary : '尚未采纳')]
      ], 'is-rows') +
        '<label class="y7-field"><span>集成事项的原文</span><textarea class="y7-textarea" rows="3" id="y7-ov-int-text">' + esc('把未采纳候选「' + item.title + '」的改动集成到当前采纳' + (baseline ? ' ' + baseline : '') + ' 上。') + '</textarea></label>' +
        ui.note('集成事项有自己的合同与质检，不自动合并冲突；候选本身保持未采纳。执行槽位已满时集成事项排队。', 'info'),
      actions: [
        { label: '取消', close: true },
        { label: '开始集成事项', kind: 'primary', act: 'ov.integrateConfirm', data: { workItemId: item.id } }
      ]
    });
  });

  Y7.actions.register('ov.integrateConfirm', (el) => {
    const item = Y7.workItem(el.dataset.workItemId);
    const result = Y7.command('startIntegration', { workItemId: item.id, text: document.getElementById('y7-ov-int-text').value });
    if (!result.ok) return;
    ui.closeModal();
    Y7.go(Y7.paths.overview(item.projectId, result.workItemId));
  });
})();
