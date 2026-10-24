// 能力登记表：查询、命令、决定种类、覆盖层与事件种类所属的档位。名称以应用层与接口层设计说明第 3 至 6 节为准；
// replay 表示查询可回放（接受 at 参数，应用层设计说明第 4.1 节）
(function () {
  'use strict';
  const Y13 = window.Y13;

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
    // 一个事项中进行中与已结束的询问（三部门的循环结构第 4.7 节）
    'run.asks': q('ui', '询问'),
    'attempt.live': q('ui', '进行中的输出'),
    'role.detail': q('S5', '角色详情'),
    'semantic.records': q('S5', '语义记录'),
    'overlay.context_usage': q('S5', '上下文用量'),
    'run.recovery': q('3.1', '恢复与动作核实'),
    'run.trials': q('3.2D', '试用记录'),
    'evidence.screenshot': q('3.2D', '截图证据'),
    'acceptance.coverage': q('pilot', '检验覆盖与开环', { replay: true }),
    'run.loops': q('pilot', '循环实例与收敛状态', { replay: true }),
    'work_item.materials': q('ui', '资料'),
    'delivery.file': q('ui', '交付文件'),
    'project.attempts': q('ui', '请求记录'),
    'project.usage': q('ui', '用量统计'),
    'run.attempt': q('ui', '请求详情'),
    'project.settings': q('ui', '项目设置'),
    // 本项目的写回记录（应用层与接口层设计说明「写回在页面上的显示」，工单 #709）
    'project.writeback': q('3.8', '写回记录'),
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
    'project.create': c('ui', ['already_exists', 'source_invalid']),
    'project.rename': c('ui', EDIT),
    'project.set_goal': c('ui', EDIT.concat(['not_allowed'])),
    'project.pin': c('ui', EDIT),
    'project.archive': c('ui', EDIT.concat(['work_item_in_progress'])),
    'project.restore': c('ui', ['stale_base', 'not_found']),
    'project.onboard': c('3.8', ['source_invalid', 'busy', 'provider_unavailable']),
    'onboarding.restart': c('3.8', ['not_found', 'project_archived', 'not_allowed', 'source_invalid']),
    'execution_placement.save': c('3.2C', EDIT.concat(['not_allowed'])),
    'material.record': c('ui', ['not_found', 'project_archived']),
    'work_item.create': c('ui', ['not_found', 'project_archived', 'work_item_in_progress', 'provider_unavailable', 'busy']),
    'work_item.append_input': c('ui', ['not_found', 'run_terminal', 'project_archived']),
    'work_item.cancel': c('ui', ['not_found', 'run_terminal']),
    'work_item.reorder': c('3.4A', ['stale_base', 'not_allowed']),
    'guidance.send': c('ui', ['not_found', 'run_terminal']),
    'department_settings.save': c('ui', EDIT),
    'machine_authorization.save': c('3.2C', EDIT.concat(['not_allowed'])),
    'writeback.execute': c('3.8', ['not_found', 'project_archived', 'not_allowed']),
    'role_settings.save': c('S5', EDIT),
    'decision.answer': c('ui', ['stale_base', 'not_found', 'decision_closed', 'option_invalid', 'not_allowed']),
    'home.mark_seen': c('ui', []),
    'machine.save': c('3.2C', ['stale_base', 'already_exists']),
    'runtime.set_slots': c('3.4A', ['stale_base', 'not_allowed']),
    'runtime.start_drain': c('3.1', ['not_allowed']),
    'runtime.force_upgrade': c('3.1', ['not_allowed']),
    'source_directory.save': c('ui', EDIT.concat(['not_allowed'])),
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

  // 决定种类（应用层与接口层设计说明第 3.3 节）
  const d = (level, label, blocks) => ({ level, label, blocks });
  const decisions = {
    waiting_resume: d('ui', '模型引用无法使用时的待恢复', 'run'),
    // 因为模型连续不调用工具或工作区出现无法表示的条目而暂停（D09）
    paused_continue: d('3.1', '暂停以后继续', 'run'),
    definitions_changed: d('3.1', '继续旧事项时定义版本不同', 'run'),
    // 等待模型服务、等待机器、等待桌面、等待桌面解锁超过时长上限（循环与收敛设计说明第 3 节）；最早的一种是 3.2C 的等待机器
    wait_limit: d('3.2C', '等待超过时长上限', 'run'),
    // 初始 PRD 的确认是项目流中的决定（接入已有项目设计说明第 3.3 节），回答写入 project_decision_answered
    initial_prd: Object.assign(d('3.8', '确认接入已有项目的初始 PRD', 'work_item'), { stream: 'project' }),
    cannot_verify: d('3.2D', '质检无法核验', 'run'),
    // 实例升级写在目录流中，不属于任何项目与 run，也不阻塞它们（可信内核设计说明第 4 节）
    instance_upgrade: Object.assign(d('pilot', '实例升级', null), { stream: 'catalog' }),
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
    semantic_records: { level: 'S5', label: '语义记录', queries: ['semantic.records'] },
    loops: { level: 'pilot', label: '循环', queries: ['run.loops'] },
    // 事实元素的来源事件由 project.loop 给出，事件对象带 source
    sources: { level: 'pilot', label: '来源', queries: ['project.loop'] },
    coverage: { level: 'pilot', label: '检验', queries: ['acceptance.coverage'] }
  };

  // 事件种类；key 为关键事实的种类（时间轴刻度与离开期间的报告使用）
  const e = (level, key) => ({ level, key: key || null });
  const events = {
    project_registered: e('ui'), project_renamed: e('ui'), project_pinned: e('ui'), project_archived: e('ui'), project_restored: e('ui'),
    material_recorded: e('ui'), user_input_received: e('ui'), work_item_created: e('ui'), run_created: e('ui'),
    department_activated: e('ui'), context_assembled: e('ui'), model_requested: e('ui'), model_request_serialized: e('ui'),
    model_stream_progress: e('ui'), model_attempt_finished: e('ui'), model_retry_scheduled: e('ui'), model_attempt_failed: e('ui'),
    tool_started: e('ui'), tool_called: e('ui'), tool_skipped: e('ui'), proposal_submitted: e('ui'), proposal_rejected: e('ui'),
    spec_accepted: e('ui'), contract_accepted: e('ui'), delivery_accepted: e('ui'),
    qa_submitted: e('ui', 'qa'),
    // 询问的开始与结束（三部门的循环结构第 4.7 节）：两条事件都写明提问方与被询问的部门
    ask_started: e('ui', 'ask'), ask_answered: e('ui', 'answer'),
    department_guidance_received: e('ui'), department_guidance_applied: e('ui'), department_guidance_responded: e('ui'),
    compaction_recorded: e('ui'), compaction_failed: e('ui'),
    run_paused: e('ui'), run_failed: e('ui'), run_done: e('ui'),
    deliverable_adopted: e('ui', 'adopt'),
    department_prompt_configured: e('ui'), project_goal_changed: e('ui'),
    catalog_revised: e('ui'), catalog_candidates_collected: e('ui'), catalog_test_finished: e('ui'), credential_changed: e('ui'),
    x_decision_issued: e('ui', 'decision'), x_decision_answered: e('ui', 'decision'), x_decision_withdrawn: e('ui'),
    x_home_seen: e('ui'), x_department_settings_saved: e('ui'), x_scenario_setup: e('ui'), x_source_directory_saved: e('ui'),
    x_run_interrupted: e('3.1'), x_run_auto_resumed: e('3.1'), x_action_unknown: e('3.1'),
    // 结果未知的动作的处理：核实确认，或者作为工具结果交还发出它的会话（恢复契约第 4 节）
    action_verified: e('3.1'),
    x_drain_started: e('3.1'), x_upgrade_forced: e('3.1'), x_run_stopped_for_upgrade: e('3.1'),
    x_machine_saved: e('3.2C'), x_machine_offline: e('3.2C'), x_machine_online: e('3.2C'),
    x_remote_action_started: e('3.2C'), x_remote_action_finished: e('3.2C'), x_late_receipt: e('3.2C'),
    x_machine_authorization_saved: e('3.2C'),
    // 等待超过时长上限以后用户选择继续等待，重新计时（循环与收敛设计说明第 3 节）
    x_wait_restarted: e('3.2C'),
    x_queued: e('3.4A'), x_slot_acquired: e('3.4A'), x_queue_cancelled: e('3.4A'), x_queue_reordered: e('3.4A'), x_slots_set: e('3.4A'),
    initial_prd_proposed: e('3.8'), onboarding_revision_started: e('3.8'), baseline_adopted: e('3.8', 'adopt'),
    structure_accepted: e('3.8'), baseline_review_accepted: e('3.8'), execution_placement_configured: e('3.2C'),
    project_decision_requested: e('3.8', 'decision'), project_decision_answered: e('3.8', 'decision'), project_decision_withdrawn: e('3.8'),
    // 采纳写回的五种结果（ADR-0034，工单 #347、#709）
    writeback_completed: e('3.8'), writeback_verified: e('3.8'), writeback_stopped: e('3.8'), writeback_held: e('3.8'), writeback_not_needed: e('3.8'),
    x_network_fetch: e('3.2B'), x_mcp_called: e('3.2B'),
    x_trial_step: e('3.2D'),
    x_provider_wait_entered: e('S4', 'wait'), x_provider_wait_left: e('S4', 'wait'),
    x_backup_taken: e('S4'), x_deployed: e('S4', 'deploy'), x_rolled_back: e('S4', 'deploy'),
    x_fault_recorded: e('S4', 'fault'), x_repair_created: e('S4', 'repair'), x_repair_failed: e('S4', 'repair'),
    x_auto_repair_stopped: e('S4', 'repair'), x_check_in: e('S4'),
    x_role_task_assigned: e('S5'), x_role_result_returned: e('S5'), x_review_recorded: e('S5'), x_explorer_fetch: e('S5'),
    x_replanned: e('S5'), x_semantic_recorded: e('S5'), x_role_settings_saved: e('S5'),
    x_evidence_checked: e('S5')
  };

  // 事实来源（应用层与接口层设计说明第 5.2 节）：每个事件种类由谁给出。确定规则是控制核心与流程编排的判断，
  // 主机测量是主机执行与测量得到的，角色陈述是部门提交与说出的，用户是用户的命令，决策模型是判定点（载荷带 probability）。
  // 按载荷或提出者区分的种类写成函数
  const RULE = 'rule', HOST = 'host_measurement', ROLE = 'role_statement', USER = 'user', MODEL = 'decision_model';
  const byUser = (ev) => (String(ev.actor || '').indexOf('user') === 0 ? USER : RULE);
  const SOURCES = {
    project_registered: USER, project_renamed: USER, project_pinned: USER, project_archived: USER, project_restored: USER,
    material_recorded: USER, user_input_received: USER, work_item_created: USER, run_created: RULE,
    department_activated: RULE, context_assembled: RULE, model_requested: HOST, model_request_serialized: HOST,
    model_stream_progress: ROLE, model_attempt_finished: HOST, model_retry_scheduled: RULE, model_attempt_failed: HOST,
    tool_started: HOST, tool_called: HOST, tool_skipped: RULE, proposal_submitted: ROLE, proposal_rejected: RULE,
    spec_accepted: RULE, contract_accepted: RULE, delivery_accepted: RULE,
    qa_submitted: ROLE,
    // 询问的问题与回答是部门说的话；没能回答的原因同样写在回答里
    ask_started: ROLE, ask_answered: ROLE,
    department_guidance_received: USER, department_guidance_applied: ROLE, department_guidance_responded: ROLE,
    compaction_recorded: ROLE, compaction_failed: HOST,
    run_paused: RULE, run_done: RULE,
    // 取消事项是用户的命令，其余的失败是控制核心的结算
    run_failed: (ev) => (ev.payload && ev.payload.reason === 'cancelled' ? USER : RULE),
    deliverable_adopted: byUser,
    department_prompt_configured: USER, project_goal_changed: USER,
    catalog_revised: USER, catalog_candidates_collected: HOST, catalog_test_finished: HOST, credential_changed: USER,
    x_decision_issued: RULE, x_decision_answered: USER, x_decision_withdrawn: RULE,
    x_home_seen: USER, x_department_settings_saved: USER, x_scenario_setup: RULE, x_source_directory_saved: USER,
    x_run_interrupted: HOST, x_run_auto_resumed: RULE, x_action_unknown: HOST, action_verified: HOST,
    x_drain_started: USER, x_upgrade_forced: USER, x_run_stopped_for_upgrade: RULE,
    x_machine_saved: USER, x_machine_offline: HOST, x_machine_online: HOST,
    x_remote_action_started: HOST, x_remote_action_finished: HOST, x_late_receipt: HOST,
    x_machine_authorization_saved: USER, x_wait_restarted: RULE,
    x_queued: RULE, x_slot_acquired: RULE, x_queue_cancelled: RULE, x_queue_reordered: USER, x_slots_set: USER,
    initial_prd_proposed: ROLE, onboarding_revision_started: USER, baseline_adopted: RULE,
    structure_accepted: RULE, baseline_review_accepted: RULE, execution_placement_configured: USER,
    project_decision_requested: RULE, project_decision_answered: USER, project_decision_withdrawn: RULE,
    writeback_completed: HOST, writeback_verified: HOST, writeback_stopped: HOST, writeback_held: RULE, writeback_not_needed: HOST,
    x_network_fetch: HOST, x_mcp_called: HOST,
    x_trial_step: HOST,
    x_provider_wait_entered: HOST, x_provider_wait_left: HOST,
    x_backup_taken: HOST, x_deployed: HOST, x_rolled_back: HOST,
    x_fault_recorded: HOST, x_repair_created: RULE, x_repair_failed: HOST, x_auto_repair_stopped: RULE, x_check_in: HOST,
    x_role_task_assigned: ROLE, x_role_result_returned: ROLE, x_review_recorded: ROLE, x_explorer_fetch: HOST,
    x_replanned: ROLE, x_semantic_recorded: ROLE, x_role_settings_saved: USER,
    x_evidence_checked: MODEL
  };

  // 按字段覆盖：一条事件里的测量值由主机测出，来源固定为主机测量，不论这条事件的种类。
  // elapsed_sec 已用时间；steps 步数；activations、model_steps、retries 已用次数；receipt 检查回执的结果；
  // unmet 由检查结果算出的未满足的验收条件数（只计有可执行检验的条件）
  const FIELD_SOURCES = {
    elapsed_sec: HOST, steps: HOST, activations: HOST, model_steps: HOST, retries: HOST, receipt: HOST, unmet: HOST
  };

  // 来源种类的名称；unverified 为没有经过主机核实的来源，画面上的标记要醒目
  const SOURCE_KINDS = {
    rule: { label: '确定规则', unverified: false },
    decision_model: { label: '决策模型', unverified: true },
    role_statement: { label: '角色陈述', unverified: true },
    host_measurement: { label: '主机测量', unverified: false },
    user: { label: '用户', unverified: false }
  };

  // 检验方式（验证的独立性设计说明第 7 节）：executable 为可执行的检验，其余的条件开环；model 为靠模型阅读作出判断
  const CHECK_METHODS = {
    command_check: { label: '命令检查', executable: true },
    trial_case: { label: '试用用例', executable: true },
    host_measurement: { label: '主机测量', executable: true },
    judgement: { label: '带参照材料的判定点', executable: false, model: true },
    human: { label: '人', executable: false },
    open: { label: '开环', executable: false }
  };

  // 关键事实的种类名称与刻度颜色；部门按关注的成果开始工作以后没有交接（ADR-0039），关键事实里也没有这一种
  const KEY_KINDS = {
    ask: { label: '询问', color: '#7c6bd6' },
    answer: { label: '回答', color: '#9d8ff0' },
    rework: { label: '缺陷记录', color: '#d64f4f' },
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

  Y13.registry = {
    queries, commands, decisions, overlays, events, KEY_KINDS, SOURCES, FIELD_SOURCES, SOURCE_KINDS, CHECK_METHODS,
    // 一条事实的来源：事件加字段。字段在覆盖表里时按字段，否则按事件种类（事件对象的 source 只按事件种类，不带字段）
    sourceOf(event, field) {
      if (field && FIELD_SOURCES[field]) return FIELD_SOURCES[field];
      const s = SOURCES[event.type];
      if (!s) throw new Error('事件种类没有登记来源：' + event.type);
      return typeof s === 'function' ? s(event) : s;
    },
    has(kind, name) {
      return Object.prototype.hasOwnProperty.call(table(kind), name);
    },
    entry(kind, name) {
      const t = table(kind);
      if (!Object.prototype.hasOwnProperty.call(t, name)) throw new Error('登记表中没有' + kind + '：' + name);
      return t[name];
    },
    levelOf(kind, name) {
      return Y13.registry.entry(kind, name).level;
    },
    tagOf(kind, name) {
      return Y13.LEVEL_TAGS[Y13.registry.levelOf(kind, name)];
    },
    // 关键事实的种类；qa_submitted 按结论分为放行与缺陷记录（键名沿用 rework）；不是关键事实时返回 null
    keyOf(event) {
      const entry = events[event.type];
      if (!entry || !entry.key) return null;
      if (entry.key === 'qa') return event.payload && event.payload.verdict === 'release' ? 'release' : 'rework';
      return entry.key;
    }
  };
})();
