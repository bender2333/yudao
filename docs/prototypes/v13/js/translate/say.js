// 翻译层：小人头顶说的话（画面与播放设计说明第 6 节）。内容只来自事件已经带着的事实（事件种类、载荷里的字段、事件说明），
// 翻译层把它写进动作的 say（做事的一方）与 sayTo（收东西的一方），画面层只管画（js/pixel/say.js）。
(function () {
  'use strict';
  const Y13 = window.Y13;
  const T = Y13.translate = Y13.translate || {};

  const DEPT_NAMES = { product: '产品', engineering: '工程', quality: '质检', operations: '运维', library: '成果库' };
  const deptName = (id) => DEPT_NAMES[id] || id || '';
  const cut = (s, n) => {
    const t = String(s === undefined || s === null ? '' : s).replace(/\s+/g, ' ').trim();
    return t.length > n ? t.slice(0, n - 1) + '…' : t;
  };
  const baseName = (p) => String(p || '').split(/[\\/]/).pop();
  // 事件说明里冒号后面的部分（询问与回答的具体内容）
  const afterColon = (label) => {
    const m = /[：:]\s*(.+)$/.exec(String(label || ''));
    return m ? m[1] : '';
  };

  // 提案的种类（真实系统的 proposal 字段）；示例数据的提交事件没有种类，就取事件说明里「提交」后面的部分，再没有就按部门
  const PROPOSAL = {
    product_spec: '产品规格', product_decision: '产品决定', engineering_plan: '工程计划', delivery_spec: '交付说明',
    qa_review: '质检结论', collaboration_request: '询问', collaboration_response: '回答', department_guidance_response: '指导回复'
  };
  const DEFAULT_PROPOSAL = { product: '产品规格', engineering: '交付说明', quality: '质检结论', operations: '运维记录' };
  const ARTIFACT = { prd: 'PRD', box: '交付箱', defect: '返工单', release: '放行单' };

  function proposalName(ev, pl) {
    if (PROPOSAL[pl.kind]) return PROPOSAL[pl.kind];
    const m = /提交(.+?)(?:[，。：:（(]|$)/.exec(String(ev.label || ''));
    return (m && m[1]) || DEFAULT_PROPOSAL[ev.department] || '提案';
  }

  const FILE_RE = /([\w\-./]+\.[A-Za-z0-9]{1,5})(?![A-Za-z0-9])/;
  const fileOf = (ev, pl) => pl.path || pl.file || (FILE_RE.exec(String(ev.label || '')) || [])[1] || null;
  // 命令：载荷里有就用载荷，没有就取事件说明末尾的英文名称
  const commandOf = (ev, pl) => pl.command || pl.name || (/([A-Za-z][\w.\-]*)\s*$/.exec(String(ev.label || '')) || [])[1] || null;

  function toolText(ev, pl) {
    const tool = String(ev.tool || pl.tool || '');
    const file = fileOf(ev, pl);
    if (tool === 'search') return '现在翻找资料' + (pl.query ? '：' + cut(pl.query, 12) : '');
    if (/^read/.test(tool)) return '现在阅读' + (file ? ' ' + cut(baseName(file), 16) : '资料');
    if (/^(edit|write)/.test(tool)) return '现在编辑' + (file ? ' ' + cut(baseName(file), 16) : '文件');
    if (tool === 'run_command' || tool === 'bash') {
      const name = commandOf(ev, pl);
      return '现在执行' + (name ? ' ' + cut(name, 14) : '命令');
    }
    if (tool === 'run_check') return '现在检查交付';
    if (/^browser/.test(tool)) return ev.department === 'quality' ? '现在试用网页' : '现在自测网页';
    if (/^(fetch|http|net|url)/.test(tool)) return '现在取回网络资料';
    if (/^mcp/.test(tool)) return '现在调用工具';
    return null;
  }

  // 没有登记在目录里的事件：拿事件说明去掉开头的主语，就是这个小人在做的事
  function fromLabel(ev) {
    const label = String(ev.label || '');
    if (!label) return null;
    const t = label.replace(/^[^，。：:、]{0,8}?(?:部门|经理|架构师|测试工程师|探索者|审查者|主程|Agent|系统|用户)(?:代表部门)?/, '');
    return cut(t || label, 26);
  }

  // 目录：事件种类 → 一句话（返回 null 表示这件事没有小人说话）。参数 (事件, 载荷, x)：x.side 为 'to' 表示这个小人是收东西的一方，
  // x.roleName(角色) 给出角色名称
  const TEXT = {
    department_activated: () => '现在开始工作',
    context_assembled: () => '现在整理资料',
    model_requested: () => '现在思考',
    model_request_serialized: () => '现在思考',
    model_attempt_finished: () => '想到办法了',
    model_retry_scheduled: (ev, pl) => {
      const n = pl.n || pl.attempt || pl.attempt_no, of = pl.of || pl.max || pl.max_attempts;
      return '等一会儿再试' + (n && of ? '（第 ' + n + '/' + of + ' 次）' : '');
    },
    model_attempt_failed: () => '请求失败了',
    tool_started: toolText,
    tool_called: (ev, pl) => {
      if (!['run_command', 'bash'].includes(String(ev.tool || pl.tool || ''))) return null;
      return pl.timed_out ? '命令超时了' : pl.exit_code === 0 ? '命令通过了' : '命令没有通过';
    },
    tool_skipped: () => '这个工具没有获准，换个办法',
    proposal_submitted: (ev, pl) => '现在提交' + proposalName(ev, pl),
    proposal_rejected: () => '提案被退回，重新修改',
    spec_accepted: () => '现在盖上有效章',
    contract_accepted: () => '现在盖上有效章',
    delivery_accepted: () => '现在装箱封存',
    qa_submitted: (ev, pl) => (pl.verdict === 'release' ? '现在盖放行章' : '现在盖返工章'),
    independent_judgement_committed: () => '现在交上独立判断',
    department_guidance_received: () => '收到用户的指导',
    department_guidance_applied: () => '现在阅读指导',
    department_guidance_responded: () => '现在写指导的回复',
    compaction_recorded: () => '现在把资料整理成摘要',
    compaction_failed: () => '整理没有生效，重新整理',
    run_paused: () => '先暂停一下',
    run_failed: (ev, pl) => {
      const reason = pl.reason || pl.stopReason;
      return reason === 'cancelled' ? '事项取消了，收拾桌面' : '失败了' + (reason ? '：' + cut(reason, 12) : '');
    },
    run_done: () => '完成了！',
    x_run_auto_resumed: () => '继续工作',
    x_run_stopped_for_upgrade: () => '因为升级停下，收拾桌面',
    x_action_unknown: () => '这个动作的结果不确定',
    x_decision_issued: (ev, pl) => (pl.kind === 'external_action' ? '举着申请单等待授权' : pl.kind === 'waiting_resume' ? '模型引用用不了，等你决定' : '现在送出决定单'),
    project_decision_requested: () => '现在送出决定单',
    x_decision_answered: () => '收到你的回答',
    project_decision_answered: () => '收到你的回答',
    x_remote_action_started: (ev, pl) => '现在在' + cut(pl.machine_name || '远程机器', 10) + '上执行',
    x_machine_offline: (ev, pl) => cut(pl.machine_name || '机器', 10) + '没有回应',
    x_network_fetch: () => '现在取回网络资料',
    x_mcp_called: (ev, pl) => '现在调用' + cut(pl.tool || pl.name || '工具', 12),
    x_trial_step: () => '现在试用网页',
    x_deployed: (ev, pl) => '现在部署' + (pl.version ? ' ' + pl.version : ''),
    x_rolled_back: (ev, pl) => '现在回滚' + (pl.to_version ? '到 ' + pl.to_version : ''),
    x_fault_recorded: (ev, pl) => '发现故障' + (pl.fault_id ? ' ' + pl.fault_id : ''),
    x_provider_wait_entered: () => '模型服务不可用，先等一等',
    x_provider_wait_left: () => '模型服务恢复了',
    x_role_task_assigned: (ev, pl, x) => {
      const task = pl.task ? '：' + cut(pl.task, 16) : '';
      return x.side === 'to' ? '收到任务' + task : '现在把任务交给' + (x.roleName(pl.to || ev.role) || '同事') + task;
    },
    x_role_result_returned: (ev, pl, x) => (x.side === 'to' ? '收到结果' : '现在把结果交回经理'),
    x_review_recorded: (ev, pl) => (pl.verdict === 'passed' || pl.verdict === 'pass' ? '审查通过' : '审查退回' + (pl.text ? '：' + cut(pl.text, 14) : '')),
    x_explorer_fetch: () => '现在出门查资料',
    x_replanned: () => '现在重新规划',
    x_semantic_recorded: () => '现在整理一张语义卡片'
  };

  // 一件事的一句话。x：{ side（'to' 为收东西的一方）, roleName(角色 id) → 角色名称 }
  T.say = function say(ev, x) {
    const o = x || {};
    const ctx = { side: o.side || null, roleName: (k) => (o.roleName && o.roleName(k)) || null };
    const f = TEXT[ev.type];
    if (!f) return fromLabel(ev);
    const text = f(ev, ev.payload || {}, ctx);
    return text === undefined ? fromLabel(ev) : text;
  };
  T.say.catalog = TEXT;

  // 交接的两端：交出方说把什么送给谁，接收方说收到什么
  T.sayHandoff = (artifact, from, to) => ({
    say: '现在把' + ARTIFACT[artifact] + '送给' + deptName(to),
    sayTo: '收到' + ARTIFACT[artifact] + '，来自' + deptName(from)
  });

  // 询问与回答的两端：发信的一方与收信的一方
  T.sayAsk = (ev) => {
    const pl = ev.payload || {};
    const q = pl.question || afterColon(ev.label);
    const tail = q ? '：' + cut(q, 14) : '';
    return { say: '现在向' + deptName(pl.recipient) + '发出询问' + tail, sayTo: '收到' + deptName(pl.requester) + '的询问' + tail };
  };
  T.sayAnswer = (ev) => {
    const pl = ev.payload || {};
    const a = pl.answer || afterColon(ev.label);
    const tail = a ? '：' + cut(a, 14) : '';
    return { say: '现在回答' + deptName(pl.requester) + '的询问', sayTo: '收到' + deptName(pl.recipient) + '的回答' + tail };
  };

  T.cut = cut;
  T.DEPT_NAMES = DEPT_NAMES;
})();
