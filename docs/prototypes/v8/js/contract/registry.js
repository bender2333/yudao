// 能力登记表：查询、命令、决定种类、覆盖层与事件种类所属的档位。名称以应用层与接口层设计说明第 3 至 6 节为准，
// pending 表示应用层设计说明尚未列出、原型先用的临时名称（标注模式显示「合同待补」）
(function () {
  'use strict';
  const Y8 = window.Y8;

  const q = (level, label, extra) => Object.assign({ level, label }, extra || {});

  const queries = {
    'system.status': q('ui', '系统状态与首页状态项', { replay: true }),
    'projects.list': q('ui', '项目列表', { replay: true }),
    'decisions.list': q('ui', '决定请求', { replay: true }),
    'home.away_report': q('ui', '离开期间的报告'),
    'project.overview': q('ui', '概览摘要与事项看板'),
    'project.loop': q('ui', '循环画面', { replay: true }),
    'project.flow': q('ui', '流转记录'),
    'work_item.inputs': q('ui', '输入记录'),
    'event.detail': q('ui', '事件详情'),
    'department.workspace': q('ui', '部门工作间'),
    'run.actions': q('ui', '动作与回执'),
    'attempt.live': q('ui', '进行中的输出'),
    'role.detail': q('S5', '角色详情'),
    'semantic.records': q('S5', '语义记录'),
    'overlay.context_usage': q('S5', '上下文用量'),
    'run.recovery': q('3.1', '恢复与动作核实'),
    'work_item.materials': q('ui', '资料'),
    'delivery.file': q('ui', '交付文件'),
    'project.attempts': q('ui', '请求记录'),
    'project.usage': q('ui', '用量统计'),
    'run.attempt': q('ui', '请求详情'),
    'project.settings': q('ui', '项目设置'),
    catalog: q('ui', '模型目录'),
    'catalog.document': q('ui', '目录文档'),
    'runtime.slots': q('3.4A', '执行槽位与队列'),
    'tools.registry': q('3.2B', '工具与扩展'),
    'machines.list': q('3.2C', '机器', { replay: true }),
    'ops.status': q('S4', '运维状态')
  };

  const c = (level, reasons, extra) => Object.assign({ level, reasons }, extra || {});
  const EDIT = ['stale_base', 'not_found', 'project_archived'];

  const commands = {
    'project.create': c('ui', ['already_exists']),
    'project.rename': c('ui', EDIT),
    'project.pin': c('ui', EDIT),
    'project.archive': c('ui', EDIT.concat(['work_item_in_progress'])),
    'project.restore': c('ui', ['stale_base', 'not_found']),
    'project.onboard': c('3.8', ['source_invalid', 'busy', 'provider_unavailable']),
    'onboarding.restart': c('3.8', ['not_found', 'project_archived', 'not_allowed', 'source_invalid']),
    'execution_placement.save': c('3.2C', EDIT),
    'material.record': c('ui', ['not_found', 'project_archived']),
    'work_item.create': c('ui', ['not_found', 'project_archived', 'work_item_in_progress', 'provider_unavailable', 'busy']),
    'work_item.append_input': c('ui', ['not_found', 'run_terminal', 'project_archived']),
    'work_item.cancel': c('ui', ['not_found', 'run_terminal']),
    'work_item.reorder': c('3.4A', ['stale_base', 'not_allowed']),
    'guidance.send': c('ui', ['not_found', 'run_terminal']),
    'department_settings.save': c('ui', EDIT),
    'command_registration.save': c('ui', EDIT),
    'tool_authorization.save': c('3.2B', EDIT),
    'machine_authorization.save': c('3.2C', EDIT),
    'role_settings.save': c('S5', EDIT),
    'decision.answer': c('ui', ['stale_base', 'not_found', 'decision_closed', 'option_invalid']),
    'home.mark_seen': c('ui', []),
    'machine.save': c('3.2C', ['stale_base', 'already_exists']),
    'runtime.set_slots': c('3.4A', ['stale_base', 'not_allowed']),
    'runtime.start_drain': c('3.1', ['not_allowed']),
    'runtime.force_upgrade': c('3.1', ['not_allowed']),
    'source_directory.save': c('ui', EDIT),
    'queue.cancel': c('3.4A', ['not_found', 'not_allowed']),
    'catalog.connection.save': c('ui', ['stale_base', 'catalog_invalid']),
    'catalog.connection.delete': c('ui', ['stale_base', 'in_use']),
    'catalog.document.save': c('ui', ['stale_base', 'catalog_invalid']),
    'catalog.reload': c('ui', ['catalog_invalid']),
    'catalog.candidates.collect': c('ui', ['not_found']),
    'catalog.connection.test': c('ui', ['not_found']),
    'catalog.model.test': c('ui', ['not_found']),
    'catalog.department_defaults.save': c('ui', ['stale_base', 'catalog_invalid']),
    'catalog.role_defaults.save': c('S5', ['stale_base', 'catalog_invalid']),
    'credential.set': c('ui', ['stale_base']),
    'credential.clear_override': c('ui', ['stale_base']),
    'credential.remove_persisted': c('ui', ['stale_base']),
    'semantic.mark_invalid': c('S5', EDIT),
    'semantic.correct': c('S5', EDIT)
  };

  const d = (level, label, blocks) => ({ level, label, blocks });
  const decisions = {
    waiting_resume: d('ui', '模型引用无法使用时的待恢复', 'run'),
    unknown_action: d('3.1', '核实结果未知的动作', 'action'),
    // 初始 PRD 的确认是项目流中的决定（接入已有项目设计说明第 3.3 节），回答写入 project_decision_answered
    initial_prd: Object.assign(d('3.8', '确认接入已有项目的初始 PRD', 'work_item'), { stream: 'project' }),
    tool_once: d('3.2B', '授权网络取回与 MCP 工具', 'action'),
    provider_wait: d('S4', '进入等待模型服务的通知', null),
    external_action: d('S4', '授权常设授权清单以外的外部动作', 'action'),
    rollback_restore: d('S4', '需要恢复备份的回滚', 'fault'),
    repair_stopped: d('S4', '同一故障连续修复失败后停止自动修复', 'fault'),
    rework_reminder: d('S5', '反复退回的提醒', null)
  };

  const overlays = {
    flow: { level: 'ui', label: '流转', queries: ['project.flow'] },
    waiting: { level: 'ui', label: '等待', queries: ['project.loop', 'decisions.list'] },
    recovery: { level: '3.1', label: '恢复', queries: ['run.recovery'] },
    context_usage: { level: 'S5', label: '上下文用量', queries: ['overlay.context_usage'] },
    semantic_records: { level: 'S5', label: '语义记录', queries: ['semantic.records'] }
  };

  // 事件种类；key 为关键事实的种类（时间轴刻度与离开期间的报告使用）
  const e = (level, key) => ({ level, key: key || null });
  const events = {
    project_registered: e('ui'), project_renamed: e('ui'), project_pinned: e('ui'), project_archived: e('ui'), project_restored: e('ui'),
    material_recorded: e('ui'), user_input_received: e('ui'), work_item_created: e('ui'), run_created: e('ui'),
    department_activated: e('ui'), context_assembled: e('ui'), model_requested: e('ui'), model_request_serialized: e('ui'),
    model_stream_progress: e('ui'), model_attempt_finished: e('ui'), model_retry_scheduled: e('ui'), model_attempt_failed: e('ui'),
    tool_started: e('ui'), tool_called: e('ui'), tool_skipped: e('ui'), proposal_submitted: e('ui'), proposal_rejected: e('ui'),
    spec_accepted: e('ui'), contract_accepted: e('ui'), plan_accepted: e('ui'), delivery_accepted: e('ui'),
    qa_submitted: e('ui', 'qa'),
    collaboration_requested: e('ui', 'ask'), collaboration_responded: e('ui', 'answer'), collaboration_closed: e('ui'),
    department_guidance_received: e('ui'), department_guidance_applied: e('ui'), department_guidance_responded: e('ui'),
    compaction_recorded: e('ui'), compaction_failed: e('ui'),
    transition: e('ui', 'handoff'),
    run_paused: e('ui'), run_failed: e('ui'), run_done: e('ui'),
    deliverable_adopted: e('ui', 'adopt'),
    department_prompt_configured: e('ui'), command_configured: e('ui'),
    catalog_revised: e('ui'), catalog_candidates_collected: e('ui'), catalog_test_finished: e('ui'), credential_changed: e('ui'),
    x_decision_issued: e('ui', 'decision'), x_decision_answered: e('ui', 'decision'), x_decision_withdrawn: e('ui'),
    x_home_seen: e('ui'), x_department_settings_saved: e('ui'), x_scenario_setup: e('ui'),
    x_run_interrupted: e('3.1'), x_run_auto_resumed: e('3.1'), x_action_unknown: e('3.1'),
    x_drain_started: e('3.1'), x_upgrade_forced: e('3.1'), x_run_stopped_for_upgrade: e('3.1'),
    x_machine_saved: e('3.2C'), x_machine_offline: e('3.2C'), x_machine_online: e('3.2C'),
    x_remote_action_started: e('3.2C'), x_remote_action_finished: e('3.2C'), x_late_receipt: e('3.2C'),
    x_machine_authorization_saved: e('3.2C'),
    x_queued: e('3.4A'), x_slot_acquired: e('3.4A'), x_queue_cancelled: e('3.4A'), x_queue_reordered: e('3.4A'), x_slots_set: e('3.4A'),
    initial_prd_proposed: e('3.8'), onboarding_revision_started: e('3.8'), baseline_adopted: e('3.8', 'adopt'),
    structure_accepted: e('3.8'), baseline_review_accepted: e('3.8'), execution_placement_configured: e('3.2C'),
    project_decision_requested: e('3.8', 'decision'), project_decision_answered: e('3.8', 'decision'), project_decision_withdrawn: e('3.8'),
    x_network_fetch: e('3.2B'), x_mcp_called: e('3.2B'), x_tool_authorization_saved: e('3.2B'),
    x_trial_step: e('3.2D'),
    x_provider_wait_entered: e('S4', 'wait'), x_provider_wait_left: e('S4', 'wait'),
    x_backup_taken: e('S4'), x_deployed: e('S4', 'deploy'), x_rolled_back: e('S4', 'deploy'),
    x_fault_recorded: e('S4', 'fault'), x_repair_created: e('S4', 'repair'), x_repair_failed: e('S4', 'repair'),
    x_auto_repair_stopped: e('S4', 'repair'), x_check_in: e('S4'),
    x_role_task_assigned: e('S5'), x_role_result_returned: e('S5'), x_review_recorded: e('S5'), x_explorer_fetch: e('S5'),
    x_replanned: e('S5'), x_semantic_recorded: e('S5'), x_role_settings_saved: e('S5')
  };

  // 关键事实的种类名称与刻度颜色
  const KEY_KINDS = {
    handoff: { label: '交接', color: '#4f8fd6' },
    ask: { label: '询问', color: '#7c6bd6' },
    answer: { label: '回答', color: '#9d8ff0' },
    rework: { label: '返工', color: '#d64f4f' },
    release: { label: '放行', color: '#3fa76a' },
    adopt: { label: '采纳', color: '#1f7a4a' },
    fault: { label: '故障', color: '#c2331f' },
    repair: { label: '修复', color: '#e08a2e' },
    deploy: { label: '部署与回滚', color: '#2f8f9d' },
    wait: { label: '进入与离开等待', color: '#8a8f99' },
    decision: { label: '决定请求', color: '#d4a017' }
  };

  function table(kind) {
    const t = { query: queries, command: commands, decision: decisions, overlay: overlays, event: events }[kind];
    if (!t) throw new Error('未知的登记种类：' + kind);
    return t;
  }

  Y8.registry = {
    queries, commands, decisions, overlays, events, KEY_KINDS,
    has(kind, name) {
      return Object.prototype.hasOwnProperty.call(table(kind), name);
    },
    entry(kind, name) {
      const t = table(kind);
      if (!Object.prototype.hasOwnProperty.call(t, name)) throw new Error('登记表中没有' + kind + '：' + name);
      return t[name];
    },
    levelOf(kind, name) {
      return Y8.registry.entry(kind, name).level;
    },
    tagOf(kind, name) {
      return Y8.LEVEL_TAGS[Y8.registry.levelOf(kind, name)];
    },
    // 关键事实的种类；qa_submitted 按结论分为放行与返工；不是关键事实时返回 null
    keyOf(event) {
      const entry = events[event.type];
      if (!entry || !entry.key) return null;
      if (entry.key === 'qa') return event.payload && event.payload.verdict === 'release' ? 'release' : 'rework';
      return entry.key;
    }
  };
})();
