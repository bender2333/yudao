// 部门工作间（设计说明第 4.2 节）：标题区、部门房间、检查区、部门消息与指导、部门设置弹窗；运维部门工作间（Stage 5）
(function () {
  'use strict';

  const Y7 = window.Y7;
  const esc = Y7.esc;
  const ui = Y7.ui;

  const TOOL_LABELS = {
    search: '搜索', read_range: '按区间阅读', read_file: '读取文件', edit_range: '按区间编辑', write_file: '写入文件',
    run_command: '执行登记命令', run_check: '运行检查', restart_service: '重启服务'
  };
  const STATUS_VIEW = {
    idle: { kind: 'idle', text: '未工作' },
    working: { kind: 'running', text: '工作中' },
    asking: { kind: 'asking', text: '等待回答' },
    paused: { kind: 'paused', text: '已暂停' },
    failed: { kind: 'failed', text: '执行失败' },
    done: { kind: 'done', text: '已完成' },
    cancelled: { kind: 'cancelled', text: '已取消' },
    interrupted: { kind: 'interrupted', text: '中断' },
    pending_verification: { kind: 'pending', text: '待核实' },
    waiting_resume: { kind: 'waiting', text: '待恢复' }
  };
  const SOURCE_LABELS = { user: '用户', self: '本部门', other: '其他部门' };
  const GUIDANCE_KIND = { received: 'queued', in_input: 'running', explained: 'done', completed: 'succeeded', declined: 'cancelled', needs_work: 'pending' };
  const ROLE_KIND_LABELS = { manager: '经理', architect: '连续角色', developer: '连续角色', tester: '连续角色', explorer: '一次性角色', agent: '部门 Agent', ops: '部门 Agent' };
  const ROLE_STATUS_KIND = { idle: 'idle', assigned: 'queued', working: 'running', returned: 'succeeded', failed: 'failed', away: 'asking' };
  const LEDGER_STATUS = { assigned: ['queued', '已分派'], working: ['running', '进行中'], returned: ['succeeded', '已交回'], failed: ['failed', '失败'], cancelled: ['cancelled', '已取消'] };
  const UNIT_STATUS = { valid: ['admitted', '有效'], superseded: ['held', '已取代'], invalid: ['cancelled', '已失效'], conflict: ['unusable', '有冲突'] };
  const ACTION_STATE_KIND = { not_sent: 'idle', done: 'succeeded', unknown: 'unknown' };
  const RECOVERING = ['interrupted', 'pending_verification', 'waiting_resume'];
  const TERMINAL_EVENTS = ['run_done', 'run_failed', 'run_paused', 'cancellation_recorded'];

  // 页面自己的界面状态：房间画面、最近事件、所选 Context、弹窗草稿
  const st = { room: null, onEvent: null, view: null, lastEvent: null, contextSel: {}, showInactive: false, modal: null };
  const defaultPromptCache = {};

  // ---------------------------------------------------------------------------
  // 工具函数

  function deptInfo(dept) {
    const info = Y7.DEPARTMENTS.find((item) => item.id === dept);
    if (!info) throw new Error('未知部门：' + dept);
    return info;
  }

  function agentName(dept) {
    return Y7.deptLabel(dept) + '部门 Agent';
  }

  function fromLabel(from) {
    if (from === 'user') return '用户';
    return Y7.deptLabel(from) + '部门';
  }

  function byStartDesc(a, b) {
    return String(b.startedAt || '').localeCompare(String(a.startedAt || ''));
  }

  function byAtDesc(a, b) {
    return String(b.at || '').localeCompare(String(a.at || ''));
  }

  function fmtMs(ms) {
    if (ms === null || ms === undefined) return '—';
    if (ms < 1000) return ms + ' 毫秒';
    if (ms < 60000) return (ms / 1000).toFixed(1).replace(/\.0$/, '') + ' 秒';
    return Y7.ui.duration(ms / 1000);
  }

  function isRecovering(run) {
    return Boolean(Y7.atLeast('s3') && run && run.recovery && RECOVERING.includes(run.recovery.state));
  }

  function isActiveRun(run) {
    return Boolean(run) && (!Y7.TERMINAL_PHASES.includes(run.phase) || isRecovering(run));
  }

  function attemptsOf(run, dept) {
    return run ? (run.attempts || []).filter((att) => att.department === dept).slice().sort(byStartDesc) : [];
  }

  function nextSeq(run) {
    let max = 0;
    Object.keys(run.messages).forEach((dept) => run.messages[dept].forEach((msg) => { max = Math.max(max, msg.seq || 0); }));
    run.flow.forEach((entry) => { max = Math.max(max, entry.seq || 0); });
    return max + 1;
  }

  // 内置默认 Prompt（版本 0）的原文：取自示例数据中未配置 Prompt 的请求
  function builtInPrompt(dept) {
    if (dept in defaultPromptCache) return defaultPromptCache[dept];
    const hit = Y7.resolve(Y7.data.runs).map((run) => run.prompts && run.prompts[dept]).find((p) => p && p.configVersion === 0 && p.text);
    defaultPromptCache[dept] = hit ? hit.text : null;
    return defaultPromptCache[dept];
  }

  function managerName(dept) {
    return { product: '产品部门经理', engineering: '工程经理', quality: '质检经理' }[dept] || Y7.deptLabel(dept) + '部门';
  }

  // ---------------------------------------------------------------------------
  // 所选范围对应的事项：选择了事项时就是它；整个项目时取本部门正在处理的、恢复中的、进行中的，最后是最近开始的

  function focusOf(projectId, workItemId, dept) {
    if (workItemId) {
      const item = Y7.workItem(workItemId);
      if (!item) throw new Error('事项不在当前档位或不存在：' + workItemId);
      return { item, run: item.runId ? Y7.run(item.runId) : null, scoped: true, reason: null };
    }
    const pairs = Y7.workItemsOf(projectId)
      .map((item) => ({ item, run: item.runId ? Y7.run(item.runId) : null }))
      .filter((pair) => pair.run);
    const rules = [
      [(pair) => pair.run.department === dept && !Y7.TERMINAL_PHASES.includes(pair.run.phase), '本部门正在处理的事项'],
      [(pair) => isRecovering(pair.run), '恢复中的事项'],
      [(pair) => pair.item.status === 'in_progress', '进行中的事项'],
      [(pair) => Boolean(pair.run.startedAt), '最近开始的事项']
    ];
    for (const [test, reason] of rules) {
      const hit = pairs.filter(test).sort((a, b) => byStartDesc(a.run, b.run))[0];
      if (hit) return { item: hit.item, run: hit.run, scoped: false, reason };
    }
    return { item: null, run: null, scoped: false, reason: null };
  }

  // ---------------------------------------------------------------------------
  // 部门状态：s3 起恢复观察状态优先；终态只挂在最后所在的部门

  function unknownActions(run) {
    return Y7.atLeast('s3') ? (run.actions || []).filter((act) => act.state === 'unknown') : [];
  }

  function roomStatus(run, dept) {
    if (!run) return 'idle';
    const rec = Y7.atLeast('s3') && run.recovery ? run.recovery : null;
    if (rec && rec.state === 'interrupted') return 'interrupted';
    if (rec && rec.state === 'pending_verification') {
      const owners = unknownActions(run).map((act) => act.department);
      return owners.includes(dept) || (!owners.length && run.department === dept) ? 'pending_verification' : 'idle';
    }
    if (rec && rec.state === 'waiting_resume') {
      const where = rec.unusable ? rec.unusable.department : (run.department || run.lastDepartment);
      return where === dept ? 'waiting_resume' : 'idle';
    }
    if (Y7.TERMINAL_PHASES.includes(run.phase)) {
      if ((run.lastDepartment || run.department) !== dept) return 'idle';
      if (run.phase === 'DONE') return 'done';
      if (run.phase === 'PAUSED') return 'paused';
      return run.stopReason && run.stopReason.code === 'cancelled' ? 'cancelled' : 'failed';
    }
    if (run.department !== dept) return 'idle';
    return (run.requests || []).some((req) => req.status === 'open' && req.from === dept) ? 'asking' : 'working';
  }

  function statusView(status, run) {
    const base = STATUS_VIEW[status];
    if (!base) throw new Error('未知部门状态：' + status);
    if (status === 'failed' && run && run.stopReason) return { kind: base.kind, text: '执行失败 · ' + run.stopReason.code };
    if (status === 'paused' && run && run.stopReason) return { kind: base.kind, text: '已暂停 · ' + run.stopReason.code };
    return base;
  }

  function doorText(status, run) {
    switch (status) {
      case 'interrupted': return '中断';
      case 'pending_verification': return '待核实';
      case 'waiting_resume': return '待恢复';
      case 'done': return '已完成';
      case 'paused': return '已暂停';
      case 'cancelled': return '已取消';
      case 'failed': return '失败：' + (run && run.stopReason ? run.stopReason.code : '停止原因未知');
      default: return null;
    }
  }

  function holdCardOf(run) {
    const rec = run.recovery;
    if (rec.unusable) return rec.unusable.problem + (rec.unusable.credentialRef ? '：' + rec.unusable.credentialRef : '');
    return rec.reason || '待恢复';
  }

  // ---------------------------------------------------------------------------
  // 模型显示：「当前」档为本次任务的模型快照；s3 起为当前生效的模型及来源与最近一次请求（D24 第 9.3 节）

  function latestAttempt(run, dept) {
    return attemptsOf(run, dept)[0] || null;
  }

  function modelView(projectId, dept, run) {
    const last = latestAttempt(run, dept);
    if (!Y7.atLeast('s3')) {
      const cur = Y7.query('catalog').current;
      const binding = cur.departments.find((entry) => entry.department === dept) || null;
      const snapshot = last ? cur.models.find((entry) => entry.model === last.requestedModel) || null : null;
      return { mode: 'snapshot', binding: binding ? binding.value : null, snapshot, last };
    }
    const target = Y7.model.resolve(projectId, dept);
    return { mode: 'effective', target, last };
  }

  // ---------------------------------------------------------------------------
  // 运维（Stage 5）

  function opsOf(projectId) {
    return Y7.atLeast('s5') ? Y7.query('ops.status', { projectId }) : null;
  }

  function opsRoomStatus(ops) {
    if (!ops) return 'idle';
    return ops.incidents.some((inc) => inc.open) || ops.pendingActions.some((act) => act.state === 'pending') ? 'working' : 'idle';
  }

  function opsStatusView(ops, status) {
    if (!ops) return { kind: 'idle', text: '没有运行责任' };
    const inc = ops.incidents.find((entry) => entry.current);
    if (inc) return { kind: inc.alarm ? 'failed' : 'running', text: inc.id + ' · 当前步骤「' + inc.current.label + '」' };
    return status === 'working' ? { kind: 'running', text: '有待授权的外部动作' } : { kind: 'idle', text: '运行中，没有告警' };
  }

  // 项目部门设置还没有写入过时，按「全部跟随」创建一份空设置
  function ensureDeptSettings(projectId, dept) {
    const all = Y7.data.projectSettings[projectId];
    if (!all) throw new Error('示例数据缺少项目设置：' + projectId);
    if (!all.departments[dept]) all.departments[dept] = { model: null, level: null, promptVersion: 0, promptText: null, version: 0 };
    return all.departments[dept];
  }

  // ---------------------------------------------------------------------------
  // roomModel：房间画面的状态（BUILD.md 第 5.2 节）

  function roomModelFor(v) {
    const dept = v.department.id;
    const run = v.run;
    const status = v.roomStatus;
    const s4 = Y7.atLeast('s4');
    let roles;
    const incident = dept === 'operations' && v.ops ? v.ops.incidents.find((inc) => inc.current) || null : null;
    if (dept === 'operations') {
      roles = [{ id: 'ops', name: agentName('operations'), kind: 'ops', status: status === 'working' ? 'working' : 'idle', task: incident ? incident.title : null }];
    } else if (s4 && v.roles) {
      roles = v.roles.map((role) => ({ id: role.id, name: role.name, kind: role.kind, status: role.status, task: role.task }));
    } else {
      roles = [{ id: 'agent', name: agentName(dept), kind: 'agent', status: status === 'working' || status === 'asking' ? 'working' : 'idle', task: v.item ? v.item.title : null }];
    }
    const running = attemptsOf(run, dept).find((att) => ['requesting', 'running'].includes(att.status));
    const pose = status === 'working' && running
      ? { roleId: s4 && running.role && roles.some((role) => role.id === running.role) ? running.role : roles[0].id, action: 'typing' }
      : null;
    const pendingAction = status === 'pending_verification' ? unknownActions(run).find((act) => act.department === dept) : null;
    const crtModel = v.model.mode === 'effective' ? (v.model.target.model || '未设置') : (v.model.last ? v.model.last.requestedModel : null);
    const crtProtocol = v.model.mode === 'effective' ? v.model.target.protocol : (v.model.snapshot ? v.model.snapshot.protocol : null);
    const model = {
      department: dept,
      level: Y7.state.level,
      status,
      crt: {
        target: dept === 'operations' ? (incident ? incident.id + ' ' + incident.title : '运行 ' + (v.ops ? v.ops.responsibility.version : '—')) : (v.item ? v.item.title : null),
        model: crtModel,
        protocol: crtProtocol,
        status: incident ? incident.current.label : v.status.text,
        cycle: run && dept !== 'operations' ? run.cycle : null
      },
      roles,
      pose,
      door: doorText(status, run),
      holdCard: status === 'waiting_resume' ? holdCardOf(run) : null,
      pendingTool: pendingAction ? pendingAction.tool : null,
      mailbox: v.guidance.filter((g) => g.status === 'received').length,
      summaries: v.compactions.reduce((max, entry) => Math.max(max, entry.n), 0)
    };
    if (dept === 'operations') {
      model.alarm = Boolean(v.ops && v.ops.incidents.some((inc) => inc.alarm));
      model.version = v.ops ? v.ops.responsibility.version : null;
    }
    return model;
  }

  // ---------------------------------------------------------------------------
  // 查询

  Y7.queries.register('department.workspace', (params) => {
    const projectId = params.projectId || Y7.state.projectId;
    const project = Y7.project(projectId);
    if (!project) throw new Error('项目不在当前档位或不存在：' + projectId);
    const info = deptInfo(params.department);
    if (!Y7.atLeast(info.level)) throw new Error('部门不在当前档位：' + info.id);
    const dept = info.id;
    const focus = focusOf(projectId, params.workItemId || null, dept);
    const run = focus.run;
    const ops = dept === 'operations' ? opsOf(projectId) : null;
    const status = dept === 'operations' ? opsRoomStatus(ops) : roomStatus(run, dept);
    const settings = Y7.query('project.settings', { projectId });
    const s4 = Y7.atLeast('s4');

    const messages = run && run.messages[dept] ? run.messages[dept].slice().sort((a, b) => (b.seq || 0) - (a.seq || 0)) : [];
    const guidance = run ? (run.guidance || []).filter((g) => g.department === dept).slice().sort(byAtDesc) : [];
    const contexts = run && run.contexts && run.contexts[dept] ? run.contexts[dept].slice().sort(byAtDesc) : [];
    const compactions = run ? (run.compactions || []).filter((entry) => entry.department === dept).slice().sort((a, b) => b.n - a.n) : [];

    const deptSettings = settings.departments[dept];
    const attempts = attemptsOf(run, dept);
    const reqPrompt = run && run.prompts ? run.prompts[dept] : null;
    const prompt = {
      config: {
        version: deptSettings.promptVersion,
        isDefault: deptSettings.promptText === null,
        text: deptSettings.promptText === null ? builtInPrompt(dept) : deptSettings.promptText
      },
      request: attempts.length && reqPrompt && reqPrompt.requestVersion !== null && reqPrompt.requestVersion !== undefined
        ? { version: reqPrompt.requestVersion, text: reqPrompt.text, attemptId: attempts[0].id } : null,
      history: Y7.atLeast('s3') ? attempts.filter((att) => att.target).map((att) => ({ id: att.id, at: att.startedAt, kind: att.kind, version: att.target.promptVersion })) : []
    };
    prompt.pending = Boolean(prompt.request) && prompt.request.version !== prompt.config.version;

    let roles = null;
    let ledger = null;
    let semantic = null;
    if (s4 && dept !== 'operations') {
      const runRoles = run && run.roles && run.roles[dept] ? run.roles[dept] : [];
      roles = settings.roles[dept].map((role) => {
        const live = runRoles.find((entry) => entry.id === role.id) || { status: 'idle', task: null };
        return Object.assign({}, role, { status: live.status, task: live.task });
      });
      ledger = run && run.ledger && run.ledger[dept] ? run.ledger[dept] : null;
      const records = Y7.resolve(Y7.data.semantic)[projectId] || null;
      if (records) {
        const scopeName = Y7.deptLabel(dept) + '私有';
        const units = records.units.filter((unit) => unit.scope === '项目共享' || unit.scope === scopeName);
        const ids = new Set(units.map((unit) => unit.id));
        semantic = {
          units,
          conflicts: records.conflicts.filter((pair) => ids.has(pair.a) && ids.has(pair.b)),
          dataflow: records.dataflow,
          privateScope: scopeName
        };
      }
    }

    const view = {
      project,
      department: { id: dept, label: info.label, duty: info.duty },
      item: focus.item,
      run,
      scoped: focus.scoped,
      focusReason: focus.reason,
      roomStatus: status,
      status: dept === 'operations' ? opsStatusView(ops, status) : statusView(status, run),
      itemStatus: focus.item ? Y7.workItemStatus(focus.item, run) : null,
      model: modelView(projectId, dept, run),
      messages,
      guidance,
      contexts,
      compactions,
      prompt,
      settingsVersion: deptSettings.version,
      roles,
      ledger,
      semantic,
      ops,
      unknownActions: run ? unknownActions(run) : [],
      composer: run && isActiveRun(run)
        ? { mode: 'guidance', runId: run.id, receiver: s4 && dept !== 'operations' ? managerName(dept) : Y7.deptLabel(dept) + '部门' }
        : { mode: 'new', ended: Boolean(run) }
    };
    view.roomModel = roomModelFor(view);
    return view;
  });

  // 动作与回执：身份、部门或角色、类型、输入依据、前后快照（s3）、状态（s3）、回执
  Y7.queries.register('run.actions', (params) => {
    const run = Y7.run(params.runId);
    if (!run) throw new Error('run 不在当前档位或不存在：' + params.runId);
    return (run.actions || [])
      .filter((act) => !params.department || act.department === params.department)
      .filter((act) => !params.role || act.role === params.role)
      .map((act) => {
        const out = Object.assign({}, act, { toolLabel: TOOL_LABELS[act.tool] || act.tool });
        if (!Y7.atLeast('s3')) delete out.state;
        if (!Y7.atLeast('s4')) delete out.role;
        return out;
      })
      .sort(byAtDesc);
  });

  // 运维状态（Stage 5）：运行责任、发布记录、故障链路、运行指标、待授权的外部动作
  Y7.queries.register('ops.status', (params) => {
    if (!Y7.atLeast('s5')) return null;
    const projectId = params.projectId || Y7.state.projectId;
    const ops = Y7.resolve(Y7.data.ops)[projectId];
    if (!ops) return null;
    return {
      responsibility: ops.responsibility,
      releases: ops.releases.map((rel) => Object.assign({ digestMatch: rel.adoptionDigest === rel.releaseDigest, awaiting: !/运维已接收|已被/.test(rel.state) }, rel)),
      incidents: ops.incidents.map((inc) => {
        const current = inc.steps.find((step) => step.state === 'current') || null;
        const open = inc.steps.some((step) => step.state !== 'done');
        const mitigation = inc.steps.find((step) => step.label === '缓解已执行');
        return Object.assign({}, inc, {
          current: current ? { label: current.label, at: current.at } : null,
          open,
          alarm: open && Boolean(mitigation) && mitigation.state !== 'done',
          item: inc.workItemId ? Y7.workItem(inc.workItemId) : null
        });
      }),
      indicators: ops.indicators,
      pendingActions: ops.pendingActions
    };
  });

  // ---------------------------------------------------------------------------
  // 命令

  // 发送部门指导
  Y7.commands.register('sendGuidance', (params) => {
    const run = Y7.raw.run(params.runId);
    if (!run) throw new Error('找不到 run：' + params.runId);
    const dept = params.department;
    const label = Y7.deptLabel(dept);
    const text = (params.text || '').trim();
    if (!text) return { ok: false, message: '请先输入部门指导' };
    const item = Y7.raw.workItem(run.workItemId);
    if (Y7.raw.project(item.projectId).archived) return { ok: false, message: '归档项目只读：写命令会返回冲突' };
    const visible = Y7.run(run.id);
    if (!isActiveRun(visible)) return { ok: false, message: '事项已结束，不会自动新建；草稿保留在输入框中' };
    const version = run.guidance.filter((g) => g.department === dept).length + 1;
    const eventId = Y7.uid('e-guidance');
    run.guidance.push({ id: Y7.uid('g'), department: dept, version, text, status: 'received', response: null, at: Y7.data.now, contextId: null, eventId });
    const message = { seq: nextSeq(run), at: Y7.data.now, source: 'user', from: 'user', text: '指导 v' + version + '：' + text, eventId };
    if (dept === 'operations') message.level = 's5';
    if (!run.messages[dept]) throw new Error('run 缺少部门消息列表：' + dept);
    run.messages[dept].push(message);
    if (params.draftKey) Y7.clearDraft(params.draftKey);
    const receiver = Y7.atLeast('s4') && dept !== 'operations' ? managerName(dept) + '（由经理决定交给哪个角色）' : label + '部门';
    return {
      ok: true,
      message: '指导 v' + version + ' 已送达' + receiver + '：保存后由目标部门在下一次安全激活中处理',
      paths: ['runs[id=' + run.id + '].guidance', 'runs[id=' + run.id + '].messages.' + dept],
      version,
      eventId
    };
  });

  // 保存项目部门设置：模型与推理档位（s3 起，D24）、部门 Prompt，带版本
  Y7.commands.register('saveDepartmentSettings', (params) => {
    const projectId = params.projectId;
    const dept = params.department;
    const label = Y7.deptLabel(dept);
    const project = Y7.raw.project(projectId);
    if (!project) throw new Error('找不到项目：' + projectId);
    if (project.archived) return { ok: false, message: '归档项目只读：写命令会返回冲突' };
    const entry = ensureDeptSettings(projectId, dept);
    if (Number(params.baseVersion) !== entry.version) {
      const what = Y7.atLeast('s3') ? '本部门设置已更新为 v' + entry.version : '部门 Prompt 配置已在另一处更新';
      return { ok: false, conflict: true, message: '版本冲突：' + what + '，草稿仍保留，请重新读取后再保存' };
    }
    let modelChanged = false;
    let promptChanged = false;
    if (Y7.atLeast('s3')) {
      const model = params.model || null;
      if (model && !(Y7.model.definition(model) && Y7.model.definition(model).admission)) {
        return { ok: false, message: '只能选择已准入的模型访问定义' };
      }
      const level = params.level || null;
      if (model !== entry.model || level !== entry.level) {
        entry.model = model;
        entry.level = level;
        modelChanged = true;
      }
    }
    if (params.promptText !== undefined) {
      const text = params.promptText === null ? null : String(params.promptText);
      if (text !== entry.promptText) {
        if (text === null) {
          entry.lastPromptVersion = Math.max(entry.lastPromptVersion || 0, entry.promptVersion);
          entry.promptVersion = 0;
        } else {
          entry.promptVersion = Math.max(entry.lastPromptVersion || 0, entry.promptVersion) + 1;
        }
        entry.promptText = text;
        promptChanged = true;
      }
    }
    if (!modelChanged && !promptChanged) return { ok: false, message: '没有需要保存的修改' };
    entry.version += 1;
    let paths = ['projectSettings.' + projectId + '.departments.' + dept];
    if (modelChanged) paths = paths.concat(Y7.model.afterChange());
    const promptNote = promptChanged ? (entry.promptText === null ? '部门 Prompt 恢复为内置默认（版本 0）；' : '部门 Prompt 配置 v' + entry.promptVersion + '；') : '';
    return { ok: true, message: '已保存本项目' + label + '部门设置 v' + entry.version + '：' + promptNote + '从本部门下一次模型请求起生效', paths, version: entry.version };
  });

  // 授权外部动作（Stage 5）：部署、回滚、重启逐项授权
  Y7.commands.register('authorizeOpsAction', (params) => {
    const ops = Y7.data.ops[params.projectId];
    if (!ops) throw new Error('项目没有运维记录：' + params.projectId);
    const action = ops.pendingActions.find((entry) => entry.id === params.actionId);
    if (!action) throw new Error('找不到待授权的外部动作：' + params.actionId);
    if (action.state !== 'pending') return { ok: false, message: '这项外部动作已经处理过' };
    if (!['approve', 'reject'].includes(params.decision)) throw new Error('授权决定无效：' + params.decision);
    action.state = params.decision === 'approve' ? 'approved' : 'rejected';
    action.decidedAt = Y7.data.now;
    const what = action.kind + ' · ' + action.target;
    return {
      ok: true,
      message: params.decision === 'approve' ? '已授权「' + what + '」：只授权这一次，运维按登记过的清单执行' : '已拒绝「' + what + '」：运维不会执行这项动作',
      paths: ['ops.' + params.projectId + '.pendingActions']
    };
  });

  // 接收运行责任（Stage 5）
  Y7.commands.register('acceptResponsibility', (params) => {
    const ops = Y7.data.ops[params.projectId];
    if (!ops) throw new Error('项目没有运维记录：' + params.projectId);
    const release = ops.releases.find((entry) => entry.version === params.version);
    if (!release) throw new Error('找不到发布记录：' + params.version);
    if (/运维已接收/.test(release.state)) return { ok: false, message: '运维部门已经接收 ' + release.version };
    release.state = '已发布 · 运维已接收';
    ops.responsibility = Object.assign({}, ops.responsibility, { version: release.version, acceptedAt: Y7.data.now, owner: '运维部门' });
    return { ok: true, message: '运维部门已接收 ' + release.version + ' 的运行责任', paths: ['ops.' + params.projectId + '.responsibility', 'ops.' + params.projectId + '.releases'] };
  });

  // ---------------------------------------------------------------------------
  // 渲染：标题区

  function modelHtml(v) {
    const m = v.model;
    const last = m.last;
    const lastLine = last
      ? '<span class="y7-ws-inline">' + '<strong>' + esc(last.actualModel || (['preparing', 'requesting', 'running'].includes(last.status) ? '未知（尚未返回）' : '未知（没有返回）')) + '</strong>' +
        (last.target ? '<span>' + esc(last.target.protocol) + '</span><span>发送 ' + esc(last.target.sentLevel || '不带推理参数') + '</span>' : '') +
        '<span class="y7-muted">' + esc(Y7.ui.time(last.startedAt)) + '</span>' +
        ui.status(attemptKind(last.status), Y7.ATTEMPT_LABELS[last.status] + ' · 第 ' + last.n + '/' + last.of + ' 次') +
        '<button type="button" class="y7-link" data-go="' + esc(Y7.paths.observeDetail(v.project.id, last.id, v.item ? v.item.id : null)) + '">请求详情</button></span>'
      : '<span class="y7-muted">本部门在这个事项中还没有模型请求</span>';
    if (m.mode === 'snapshot') {
      const snap = m.snapshot;
      const pairs = [
        ['运行目标', snap ? '<strong>' + esc(snap.model) + '（' + esc(snap.provider) + '）</strong>' : esc(m.binding || '未绑定')],
        ['协议', snap ? esc(snap.protocol) : ''],
        ['上下文窗', snap ? esc(Y7.ui.num(snap.window)) : ''],
        ['最大输出', snap ? esc(Y7.ui.num(snap.maxOutput)) : ''],
        ['最近一次请求', lastLine]
      ];
      return ui.kv(pairs, 'y7-ws-model') + '<p class="y7-muted y7-small">以上为本次任务采用的只读快照；在「模型与 Provider」中修改只影响新事项。</p>';
    }
    const t = m.target;
    let current;
    if (!t.definition) current = ui.status('idle', '未设置');
    else {
      current = '<span class="y7-ws-inline"><strong>' + esc(Y7.model.label(t.definition)) + '</strong><span class="y7-muted">来源：' + esc(t.source) + '</span>' +
        (t.problem ? ui.status('unusable', '无法使用：' + t.problem) : ui.status('admitted', '已准入')) + '</span>';
    }
    const level = t.definition
      ? esc(t.requestLevel ? '请求 ' + t.requestLevel : '请求档位为空（使用模型默认档位）') + ' · ' + esc('发送 ' + (t.sentLevel || '不带推理参数'))
      : '';
    const pairs = [
      ['当前生效的模型', current],
      ['协议', t.definition && !t.problem ? esc(t.protocol) : (t.definition ? esc(t.protocol || '—') : '')],
      ['推理档位', level],
      ['最近一次请求实际使用', lastLine]
    ];
    let note = '';
    if (t.problem) {
      const fix = [
        '<button type="button" class="y7-link" data-go="#/sys/models">在模型管理修复</button>',
        '<button type="button" class="y7-link" data-act="dept.openSettings" data-project-id="' + esc(v.project.id) + '" data-department="' + esc(v.department.id) + '">在部门设置另选模型</button>'
      ];
      if (v.roomStatus === 'waiting_resume') fix.push('<button type="button" class="y7-link" data-go="' + esc(Y7.paths.recovery(v.project.id, v.item.id)) + '">恢复页的继续执行</button>');
      note = ui.note((t.definition ? '本部门的下一次模型请求不会发送：' + esc(t.problem) + '。不改用其他模型。' : '本部门没有设置模型，部门默认也为未设置。') + '<span class="y7-note-actions y7-row">' + fix.join('') + '</span>', 'warn');
    }
    return ui.kv(pairs, 'y7-ws-model') + note;
  }

  function attemptKind(status) {
    return { preparing: 'idle', requesting: 'running', running: 'running', succeeded: 'succeeded', failed: 'failed', cancelled: 'cancelled' }[status];
  }

  function itemLineHtml(v) {
    if (!v.item) return '<p class="y7-ws-item y7-muted">本项目还没有事项</p>';
    const run = v.run;
    const scopeText = v.scoped ? '事项' : '范围：整个项目 · 显示' + v.focusReason;
    const parts = [
      '<span class="y7-muted">' + esc(scopeText) + '</span>',
      '<strong>「' + esc(v.item.title) + '」</strong>',
      ui.status(v.itemStatus.kind, v.itemStatus.text)
    ];
    if (run && v.department.id !== 'operations') {
      if (Y7.TERMINAL_PHASES.includes(run.phase)) {
        if (run.stopReason && !isRecovering(run)) parts.push('<span class="y7-muted">' + esc(run.stopReason.text) + '</span>');
      } else {
        parts.push('<span>' + esc(Y7.PHASE_LABELS[run.phase]) + '</span>');
      }
      if (run.cycle) parts.push('<span>第 ' + run.cycle + ' 轮</span>');
    }
    if (!v.scoped) parts.push('<button type="button" class="y7-link" data-go="' + esc(Y7.paths.dept(v.project.id, v.department.id, v.item.id)) + '">只看这个事项</button>');
    return '<p class="y7-ws-item">' + parts.join('') + '</p>';
  }

  function headBlock(v) {
    const d = v.department;
    const w = v.item ? v.item.id : null;
    const observe = Y7.paths.observe(v.project.id, w) + (w ? '&' : '?') + 'dept=' + d.id;
    const body = '<div class="y7-ws-head">' +
        '<div class="y7-ws-titles">' +
          '<p class="y7-eyebrow">部门工作间</p>' +
          '<div class="y7-ws-title-row"><h1>' + esc(d.label) + '部门</h1>' + ui.status(v.status.kind, v.status.text) + '</div>' +
          '<p class="y7-ws-duty">' + esc(d.duty) + '</p>' +
          itemLineHtml(v) +
        '</div>' +
        '<div class="y7-ws-head-actions">' +
          ui.button({ label: '部门设置', icon: 'tools', act: 'dept.openSettings', data: { projectId: v.project.id, department: d.id } }) +
          ui.button({ label: '本部门的模型请求', icon: 'search', go: observe }) +
        '</div>' +
      '</div>' + modelHtml(v);
    return ui.block({
      level: 'now', tag: Y7.atLeast('s3') ? 'D24' : '当前', query: 'department.workspace', command: '无',
      className: 'y7-ws-head-block', body
    });
  }

  // ---------------------------------------------------------------------------
  // 渲染：部门房间与画面下方的文字列表

  function roomFacts(v) {
    const m = v.roomModel;
    const crt = m.crt;
    // 单个部门 Agent 的状态就是部门状态；Stage 4 起每个角色有自己的任务状态
    const single = m.roles.length === 1 && ['agent', 'ops'].includes(m.roles[0].kind);
    const roles = m.roles.map((role) =>
      '<li><strong>' + esc(role.name) + '</strong>' + (single ? ui.status(v.status.kind, v.status.text) : ui.status(ROLE_STATUS_KIND[role.status] || 'idle', Y7.ROLE_STATUS_LABELS[role.status] || role.status)) +
      (role.task ? '<span class="y7-muted">' + esc(role.task) + '</span>' : '') + '</li>'
    ).join('');
    const pairs = [
      ['部门状态', ui.status(v.status.kind, v.status.text)],
      ['监视器', esc([crt.target || '—', crt.model || '—', crt.protocol || '—', crt.status, crt.cycle ? '第 ' + crt.cycle + ' 轮' : null].filter(Boolean).join(' · '))],
      ['门牌', m.door ? esc(m.door) : '<span class="y7-muted">无</span>'],
      ['信箱', m.mailbox ? esc(m.mailbox + ' 条指导待进入模型输入') : '<span class="y7-muted">没有未读指导</span>'],
      ['摘要档案盒', m.summaries ? esc('编号 ' + m.summaries) : '<span class="y7-muted">还没有压缩</span>']
    ];
    if (m.holdCard) pairs.push(['举牌', esc(m.holdCard)]);
    if (m.pendingTool) pairs.push(['闪烁的物件', esc((TOOL_LABELS[m.pendingTool] || m.pendingTool) + '（结果未知，等待核实）')]);
    if (v.department.id === 'operations') {
      pairs.push(['告警灯', m.alarm ? ui.status('failed', '旋转：故障尚未缓解') : '<span class="y7-muted">熄灭</span>']);
      pairs.push(['机柜', esc(m.version ? '运行 ' + m.version : '没有运行中的版本')]);
    }
    const ev = st.lastEvent;
    const eventLine = ev
      ? '<p class="y7-ws-event"><span class="y7-muted">最近的事件</span><code>' + esc(ev.type) + '</code><span>' + esc(ev.label || '') + '</span></p>'
      : '<p class="y7-ws-event y7-muted">画面按上面的状态显示；事件流中本部门的新事件会在画面中播放一次动作。</p>';
    return ui.kv(pairs, 'y7-ws-facts') + '<div class="y7-ws-roles"><span class="y7-ws-k">工位</span><ul>' + roles + '</ul></div>' + eventLine;
  }

  function roomBlock(v) {
    const label = v.department.label + '部门';
    const body = '<div class="y7-ws-stage"><canvas class="y7-ws-canvas" role="img" aria-label="' + esc(label) + '房间画面：' + esc(v.status.text) + '"></canvas></div>' +
      '<div class="y7-ws-room-info" data-ws-region="room-info">' + roomFacts(v) + '</div>';
    return ui.block({
      title: label + '房间', tag: v.department.id === 'operations' ? 'Stage 5' : (Y7.atLeast('s4') ? '当前 · Stage 4' : '当前'), level: 'now',
      query: ['department.workspace', '事件流'], command: '无', className: 'y7-ws-room-block',
      subtitle: '画面的每个动作来自下方列出的状态，或来自事件流中本部门的事件。',
      body
    });
  }

  // ---------------------------------------------------------------------------
  // 渲染：检查区

  function exitHtml(act) {
    const r = act.receipt;
    if (!r) return '';
    if (act.skipped) return ui.status('cancelled', '被拒绝：没有执行');
    if (r.timedOut) return ui.status('failed', '超时 ' + fmtMs(r.durationMs));
    if (r.exitCode === null || r.exitCode === undefined) return ui.status('unknown', '退出状态未知');
    return ui.status(r.exitCode === 0 ? 'succeeded' : 'failed', '退出 ' + r.exitCode);
  }

  function actionCard(act, dept) {
    const r = act.receipt;
    const head = '<header class="y7-ws-act-head">' +
      '<span class="y7-ws-act-tool">' + esc(act.toolLabel) + '</span>' +
      '<strong>' + esc(act.summary) + '</strong>' +
      (act.state ? ui.status(ACTION_STATE_KIND[act.state], Y7.ACTION_STATE_LABELS[act.state]) : '') +
      '</header>';
    const meta = [
      ['动作', ui.code(act.id)],
      ['时间', esc(Y7.ui.time(act.at))],
      ['输入依据', esc(act.input)],
      act.result ? ['结果', esc(act.result)] : null,
      act.role ? ['角色', esc(roleName(act.role))] : null
    ];
    let receipt = '';
    if (r) {
      const title = dept === 'quality' && act.tool === 'run_command' ? '质检主机回执' : act.skipped ? '工具被拒绝' : '主机回执';
      receipt = '<div class="y7-ws-receipt"><p class="y7-ws-receipt-title">' + esc(title) + exitHtml(act) + (r.truncated ? ui.tag('输出已截断') : '') + '</p>' +
        ui.kv([
          ['登记名', ui.code(r.command)],
          ['完整参数', ui.code(r.argv.join(' '))],
          ['耗时', esc(fmtMs(r.durationMs))],
          ['快照', r.snapshot ? ui.code(r.snapshot) : '<span class="y7-muted">没有快照</span>']
        ], 'y7-ws-receipt-kv') +
        ui.pre(r.output) + '</div>';
    }
    let snaps = '';
    if ('before' in act || 'after' in act) {
      snaps = '<p class="y7-ws-snaps"><span class="y7-muted">执行前</span>' + esc(act.before || '—') + '<span class="y7-ws-arrow">→</span><span class="y7-muted">执行后</span>' + esc(act.after || '—') + '</p>';
    }
    return '<article class="y7-ws-act' + (act.state === 'unknown' ? ' is-unknown' : '') + '">' + head + ui.kv(meta, 'is-inline y7-ws-act-meta') + snaps + receipt + '</article>';
  }

  function actionsPanel(v) {
    if (!v.run) return ui.empty('还没有事项，没有动作');
    const list = Y7.query('run.actions', { runId: v.run.id, department: v.department.id });
    const warn = v.unknownActions.length && v.unknownActions.some((act) => act.department === v.department.id)
      ? ui.note('有结果未知的动作，需要先核实。<span class="y7-note-actions">' + ui.button({ label: '前往恢复与动作核实', kind: 'small primary', go: Y7.paths.recovery(v.project.id, v.item.id) }) + '</span>', 'warn')
      : '';
    const intro = '<p class="y7-muted y7-small">工程命令结果与质检主机回执分开记录；成功退出只证明这一条命令成功。' + (Y7.atLeast('s3') ? '动作状态分为未发送、已完成、结果未知，核实记录追加保存。' : '') + '</p>';
    return intro + warn + (list.length ? '<div class="y7-ws-acts">' + list.map((act) => actionCard(act, v.department.id)).join('') + '</div>' : ui.empty('本部门在这个事项中还没有动作'));
  }

  function contextPanel(v) {
    if (!v.contexts.length && !v.compactions.length) return ui.empty('本部门在这个事项中还没有 Context 快照');
    const key = (v.run ? v.run.id : '') + '.' + v.department.id;
    const selectedId = st.contextSel[key] && v.contexts.some((ctx) => ctx.id === st.contextSel[key]) ? st.contextSel[key] : (v.contexts[0] ? v.contexts[0].id : null);
    const list = v.contexts.map((ctx) =>
      '<li><button type="button" class="y7-ws-ctx' + (ctx.id === selectedId ? ' is-on' : '') + '" data-act="dept.pickContext" data-key="' + esc(key) + '" data-context-id="' + esc(ctx.id) + '">' +
      '<strong>' + esc(ctx.title) + '</strong><small>' + esc(Y7.ui.time(ctx.at)) + ' · ' + esc(ctx.sources.length) + ' 项来源</small></button></li>'
    ).join('');
    const sel = v.contexts.find((ctx) => ctx.id === selectedId) || null;
    let detail = '';
    if (sel) {
      const rows = sel.sources.map((src) => ({ label: src.label, version: src.version, included: src.included, note: src.note || '' }));
      detail = '<div class="y7-ws-ctx-detail"><h3 class="y7-h3">' + esc(sel.title) + ' · ' + esc(Y7.ui.time(sel.at)) + '</h3>' +
        ui.table({
          columns: [
            { key: 'label', label: '来源' },
            { key: 'version', label: '版本', render: (row) => ui.code(row.version) },
            { key: 'included', label: '本次输入', render: (row) => row.included ? ui.status('admitted', '已注入') : ui.status('idle', '未包含') + (row.note ? '<small class="y7-muted y7-block-line">' + esc(row.note) + '</small>' : '') }
          ],
          rows
        }) +
        '<div class="y7-row y7-ws-ctx-foot">' + (sel.attemptId
          ? ui.button({ label: '查看模型请求', kind: 'small', go: Y7.paths.observeDetail(v.project.id, sel.attemptId, v.item ? v.item.id : null) })
          : '<span class="y7-muted y7-small">本次 Context 尚未发起模型请求</span>') + '</div></div>';
    }
    const summaries = v.compactions.length
      ? '<h3 class="y7-h3">部门历史摘要</h3><ul class="y7-ws-summaries">' + v.compactions.map((entry) =>
        '<li><strong>摘要 ' + entry.n + '</strong><span>覆盖范围 ' + esc(entry.coverage) + '</span><span class="y7-muted">' + esc(Y7.ui.time(entry.at)) + '</span>' +
        '<button type="button" class="y7-link" data-act="dept.openEvent" data-run-id="' + esc(v.run.id) + '" data-event-id="' + esc(entry.eventId) + '">打开摘要来源事件</button></li>'
      ).join('') + '</ul>'
      : '';
    return '<div class="y7-ws-ctx-grid"><ul class="y7-ws-ctx-list">' + list + '</ul>' + detail + '</div>' + summaries;
  }

  function promptPanel(v) {
    const p = v.prompt;
    const configLabel = p.config.isDefault ? '默认 v0' : '配置 v' + p.config.version;
    const configText = p.config.text || '内置默认 Prompt（版本 0），内容随系统版本发布。';
    const left = '<section class="y7-ws-prompt"><h3 class="y7-h3">项目当前配置 ' + ui.tag(configLabel) +
      (p.request ? (p.pending ? ui.status('queued', '待下次激活') : ui.status('running', '生效中')) : '') + '</h3>' + ui.pre(configText) +
      '<div class="y7-row">' + ui.button({ label: '配置 Prompt', kind: 'small', act: 'dept.openSettings', data: { projectId: v.project.id, department: v.department.id } }) + '</div></section>';
    const right = '<section class="y7-ws-prompt"><h3 class="y7-h3">所选请求实际使用 ' + (p.request ? ui.tag('run Prompt v' + p.request.version) : '') + '</h3>' +
      (p.request ? ui.pre(p.request.text || '') : ui.empty('尚未绑定请求')) +
      '<p class="y7-muted y7-small">历史请求不从当前配置回填。</p></section>';
    const history = p.history.length
      ? '<h3 class="y7-h3">各次请求使用的部门 Prompt 版本 ' + ui.tag('D24') + '</h3>' + ui.table({
        columns: [
          { key: 'at', label: '时间', render: (row) => esc(Y7.ui.time(row.at)) },
          { key: 'kind', label: '请求类型', render: (row) => esc({ work: '工作请求', compaction: '压缩请求', collaboration: '协作请求' }[row.kind] || row.kind) },
          { key: 'version', label: '部门 Prompt 版本', render: (row) => ui.code('v' + row.version) },
          { key: 'id', label: '请求', className: 'y7-col-actions', render: (row) => ui.button({ label: '请求详情', kind: 'small', go: Y7.paths.observeDetail(v.project.id, row.id, v.item ? v.item.id : null) }) }
        ],
        rows: p.history
      })
      : '';
    return '<div class="y7-grid-2 y7-ws-prompt-grid">' + left + right + '</div>' + history;
  }

  function roleName(roleId) {
    const catalog = Y7.resolve(Y7.data.catalog).roleCatalog;
    if (!catalog) return roleId;
    for (const dept of ['product', 'engineering', 'quality']) {
      const found = (catalog[dept] || []).find((role) => role.id === roleId);
      if (found) return found.name;
    }
    return roleId;
  }

  function rolesPanel(v) {
    if (!v.roles) return ui.empty('本部门没有角色名单');
    return '<p class="y7-muted y7-small">角色是固定的，随系统版本发布。经理是部门唯一的对外接口；开发者是工作区唯一的写入者。模型按项目角色设置、角色默认、项目部门设置、部门默认的顺序取第一个写入了的。</p>' +
      ui.table({
        columns: [
          { key: 'name', label: '角色', render: (row) => '<div class="y7-cell-stack"><strong>' + esc(row.name) + '</strong><small class="y7-muted">' + esc(ROLE_KIND_LABELS[row.kind]) + ' · ' + esc(row.duty) + '</small></div>' },
          { key: 'status', label: '状态', className: 'y7-col-status', render: (row) => ui.status(ROLE_STATUS_KIND[row.status] || 'idle', Y7.ROLE_STATUS_LABELS[row.status] || row.status) },
          { key: 'model', label: '模型', render: (row) => '<div class="y7-cell-stack"><span>' + esc(row.resolved.definition ? Y7.model.label(row.resolved.definition) : '未设置') + '</span><small class="y7-muted">来源：' + esc(row.resolved.source || '—') + ' · 发送 ' + esc(row.resolved.sentLevel || '不带推理参数') + '</small>' + (row.resolved.problem ? ui.status('unusable', '无法使用：' + row.resolved.problem) : '') + '</div>' },
          { key: 'task', label: '当前任务', render: (row) => row.task ? esc(row.task) : '<span class="y7-muted">没有任务</span>' },
          { key: 'ops', label: '历史', className: 'y7-col-actions', render: (row) => ui.button({ label: '历史与请求', kind: 'small', act: 'dept.roleHistory', data: { roleId: row.id } }) }
        ],
        rows: v.roles
      });
  }

  function ledgerPanel(v) {
    const l = v.ledger;
    if (!l) return ui.empty('本部门在这个事项中还没有部门账本');
    const roles = v.roles || [];
    const nameOf = (id) => (roles.find((role) => role.id === id) || { name: id }).name;
    const items = ui.table({
      columns: [
        { key: 'id', label: '编号', render: (row) => ui.code(row.id) },
        { key: 'text', label: '工作计划条目' },
        { key: 'assignee', label: '分派对象', render: (row) => esc(nameOf(row.assignee)) },
        { key: 'status', label: '状态', className: 'y7-col-status', render: (row) => ui.status((LEDGER_STATUS[row.status] || ['idle'])[0], (LEDGER_STATUS[row.status] || [null, row.status])[1]) },
        { key: 'result', label: '结果摘要', render: (row) => row.result ? esc(row.result) : '<span class="y7-muted">尚未交回</span>' }
      ],
      rows: l.items
    });
    const list = (arr, empty) => arr.length ? '<ul class="y7-list">' + arr.map((text) => '<li>' + esc(text) + '</li>').join('') + '</ul>' : '<p class="y7-muted y7-small">' + esc(empty) + '</p>';
    const progress = l.progress.length
      ? '<ol class="y7-ws-progress">' + l.progress.map((p) => '<li class="' + (p.judgment === '停滞' ? 'is-stalled' : '') + '"><strong>第 ' + p.cycle + ' 轮</strong>' +
        ui.status(p.judgment === '停滞' ? 'paused' : 'running', p.judgment) + '<span>' + esc(p.text) + '</span></li>').join('') + '</ol>'
      : '<p class="y7-muted y7-small">还没有进展判断</p>';
    const dataflow = v.semantic && v.semantic.dataflow.length
      ? '<h3 class="y7-h3">数据流核对（项目共享单元）</h3><ul class="y7-ws-dataflow">' + v.semantic.dataflow.map((row) =>
        '<li>' + ui.status(row.ok ? 'succeeded' : 'failed', row.ok ? '通过' : '未通过') + '<span>' + esc(row.label) + '</span>' +
        (row.missing.length ? '<small class="y7-muted">缺失：' + row.missing.map((id) => ui.code(id)).join(' ') + '</small>' : '') + '</li>').join('') + '</ul>'
      : '';
    return '<div class="y7-ws-ledger"><section><h3 class="y7-h3">任务部分</h3>' + items +
      '<div class="y7-grid-2"><div><h3 class="y7-h3">已核实事实</h3>' + list(l.facts, '还没有已核实的事实') + '</div><div><h3 class="y7-h3">待决问题</h3>' + list(l.questions, '没有待决问题') + '</div></div></section>' +
      '<section><h3 class="y7-h3">进展部分：每一轮的进展判断</h3>' + progress + '<p class="y7-muted y7-small">经理的进展判断与主机的进展事实都显示没有进展、并且连续 3 轮时，主机要求更新工作计划；停滞不结束事项。</p>' + dataflow + '</section></div>';
  }

  function unitRow(unit, all) {
    const s = UNIT_STATUS[unit.status] || ['idle', unit.status];
    const extra = [];
    if (unit.status === 'superseded' && unit.supersededBy) extra.push('已被 ' + unit.supersededBy + ' 取代' + (unit.reason ? '：' + unit.reason : ''));
    if (unit.status === 'invalid' && unit.reason) extra.push('已失效：' + unit.reason);
    if (unit.fromHeld) extra.push('来自未采纳事项');
    const next = unit.supersededBy ? all.find((u) => u.id === unit.supersededBy) : null;
    return '<li class="y7-ws-unit is-' + esc(unit.status) + '"><div class="y7-ws-unit-head">' + ui.code(unit.id) + '<span class="y7-ws-unit-type">' + esc(unit.type) + '</span>' + ui.status(s[0], s[1]) +
      '<span class="y7-muted y7-small">' + esc(unit.scope) + '</span></div><p>' + esc(unit.text) + '</p>' +
      (extra.length ? '<small class="y7-muted">' + esc(extra.join('；')) + (next ? ' → ' + esc(next.text) : '') + '</small>' : '') +
      '<small class="y7-muted">来源事件 ' + ui.code(unit.source) + ' · ' + esc(Y7.ui.time(unit.at)) + '</small></li>';
  }

  function semanticPanel(v) {
    const s = v.semantic;
    if (!s) return ui.empty('本项目还没有语义记录');
    const active = s.units.filter((unit) => unit.status === 'valid' || unit.status === 'conflict');
    const inactive = s.units.filter((unit) => unit.status === 'superseded' || unit.status === 'invalid');
    const types = [];
    active.forEach((unit) => { if (!types.includes(unit.type)) types.push(unit.type); });
    const groups = types.map((type) => '<section class="y7-ws-unit-group"><h3 class="y7-h3">' + esc(type) + '</h3><ul>' + active.filter((unit) => unit.type === type).map((unit) => unitRow(unit, s.units)).join('') + '</ul></section>').join('');
    const conflicts = s.conflicts.length
      ? '<h3 class="y7-h3">冲突</h3>' + s.conflicts.map((pair) => ui.note(ui.code(pair.a) + ' ↔ ' + ui.code(pair.b) + ' ' + esc(pair.text), 'warn')).join('')
      : '';
    const chain = inactive.filter((unit) => unit.status === 'superseded').map((unit) => {
      const next = s.units.find((u) => u.id === unit.supersededBy);
      return '<li><span class="y7-muted">' + esc(Y7.ui.time(unit.at)) + '</span>' + ui.code(unit.id) + '<span>' + esc(unit.text) + '</span><span class="y7-ws-arrow">→</span>' + ui.code(unit.supersededBy) + '<span>' + esc(next ? next.text : '') + '</span><small class="y7-muted">原因：' + esc(unit.reason || '—') + '</small></li>';
    }).join('');
    const toggle = '<label class="y7-ws-toggle"><input type="checkbox" data-act="dept.toggleInactive"' + (st.showInactive ? ' checked' : '') + '> 显示已取代与已失效的单元（' + inactive.length + '）</label>';
    return '<p class="y7-muted y7-small">本部门可见的单元：项目共享，以及' + esc(s.privateScope) + '。质检各角色看不到工程私有单元。</p>' + conflicts +
      '<div class="y7-ws-units">' + groups + '</div>' +
      (chain ? '<h3 class="y7-h3">更替链（从旧到新）</h3><ul class="y7-ws-chain">' + chain + '</ul>' : '') +
      toggle + (st.showInactive && inactive.length ? '<ul class="y7-ws-inactive">' + inactive.map((unit) => unitRow(unit, s.units)).join('') + '</ul>' : '');
  }

  function inspectBlock(v) {
    const ops = v.department.id === 'operations';
    const actionsCount = v.run ? Y7.query('run.actions', { runId: v.run.id, department: v.department.id }).length : 0;
    const items = [
      { id: 'actions', label: '动作与回执', count: actionsCount },
      { id: 'context', label: 'Context' },
      { id: 'prompt', label: '部门 Prompt' }
    ];
    if (!ops) {
      items.push({ id: 'roles', label: '角色名单', level: 's4', tag: 'Stage 4' });
      items.push({ id: 'ledger', label: '部门账本', level: 's4', tag: 'Stage 4' });
      items.push({ id: 'semantic', label: '语义面板', level: 's4', tag: 'Stage 4' });
    }
    const visible = items.filter((item) => Y7.atLeast(item.level));
    const active = Y7.ui.activeTab('dept.inspect', visible, 'actions');
    const panels = {};
    const renderers = { actions: actionsPanel, context: contextPanel, prompt: promptPanel, roles: rolesPanel, ledger: ledgerPanel, semantic: semanticPanel };
    visible.forEach((item) => { panels[item.id] = renderers[item.id](v); });
    return ui.block({
      title: '检查区', tag: Y7.atLeast('s4') && !ops ? '当前 · Stage 4' : '当前 · 3.2A', level: 'now',
      query: ['department.workspace', 'run.actions'], command: '无', className: 'y7-ws-inspect',
      body: ui.tabs({ id: 'dept.inspect', items: visible, active }) + ui.tabPanels('dept.inspect', active, panels)
    });
  }

  // ---------------------------------------------------------------------------
  // 渲染：部门消息与指导

  function messagesHtml(v) {
    if (!v.messages.length) return ui.empty('本部门在这个事项中还没有消息');
    return '<ol class="y7-ws-log">' + v.messages.map((msg) =>
      '<li class="is-' + esc(msg.source) + '"><div class="y7-ws-log-meta"><span class="y7-ws-src">' + esc(SOURCE_LABELS[msg.source] || msg.source) + (msg.source === 'other' ? ' · ' + esc(fromLabel(msg.from)) : '') + '</span>' +
      '<span class="y7-muted">' + esc(Y7.ui.time(msg.at)) + ' · seq ' + esc(msg.seq) + '</span>' +
      '<button type="button" class="y7-link" data-act="dept.openEvent" data-run-id="' + esc(v.run.id) + '" data-event-id="' + esc(msg.eventId) + '">查看事件</button></div>' +
      '<p>' + esc(msg.text) + '</p></li>'
    ).join('') + '</ol>';
  }

  function guidanceRecords(v) {
    if (!v.guidance.length) return '<p class="y7-muted y7-small">还没有部门指导</p>';
    return '<ul class="y7-ws-guidance">' + v.guidance.map((g) =>
      '<li><div class="y7-ws-log-meta"><strong>指导 v' + esc(g.version) + '</strong>' + ui.status(GUIDANCE_KIND[g.status] || 'idle', Y7.GUIDANCE_LABELS[g.status] || g.status) +
      '<span class="y7-muted">' + esc(Y7.ui.time(g.at)) + '</span></div>' +
      '<p>' + esc(g.text) + '</p>' +
      '<p class="y7-muted y7-small">指导 ID ' + ui.code(g.id) + (g.contextId ? ' · Context ' + '<button type="button" class="y7-link" data-act="dept.showContext" data-key="' + esc(v.run.id + '.' + v.department.id) + '" data-context-id="' + esc(g.contextId) + '">' + esc(g.contextId) + '</button>' : ' · 尚未进入模型输入') +
      (g.eventId ? ' · <button type="button" class="y7-link" data-act="dept.openEvent" data-run-id="' + esc(v.run.id) + '" data-event-id="' + esc(g.eventId) + '">查看事件</button>' : '') + '</p>' +
      (g.response ? '<p class="y7-ws-reply"><span class="y7-muted">部门回应</span>' + esc(g.response) + '</p>' : '') + '</li>'
    ).join('') + '</ul>';
  }

  function composerHtml(v) {
    const c = v.composer;
    const d = v.department;
    if (c.mode === 'guidance') {
      const key = 'dept.guidance.' + c.runId + '.' + d.id;
      return '<div class="y7-ws-composer">' +
        '<p class="y7-ws-recipient"><span class="y7-muted">当前接收方</span><strong>发给' + esc(c.receiver) + '</strong>' + (Y7.atLeast('s4') && d.id !== 'operations' ? ui.tag('Stage 4') : '') + '</p>' +
        '<label class="y7-field"><span>向' + esc(d.label) + '部门下达指导或追加人类反馈</span><textarea class="y7-textarea" rows="3" id="y7-ws-guidance" data-draft="' + esc(key) + '" placeholder="追加对话或指导"></textarea></label>' +
        '<div class="y7-row"><button type="button" class="y7-btn primary" data-act="dept.sendGuidance" data-run-id="' + esc(c.runId) + '" data-department="' + esc(d.id) + '" data-draft-key="' + esc(key) + '"><span>发送指导</span></button>' +
        '<span class="y7-muted y7-small">保存后由目标部门在下一次安全激活中处理；与修改 Prompt、模型回复分开记录。</span></div></div>';
    }
    const key = 'dept.new.' + v.project.id + '.' + d.id;
    return '<div class="y7-ws-composer">' +
      (c.ended ? '<p class="y7-muted y7-small">所选事项已结束：部门指导不会自动新建事项。</p>' : '') +
      '<label class="y7-field"><span>作为新事项开始，或记录原文</span><textarea class="y7-textarea" rows="3" id="y7-ws-new" data-draft="' + esc(key) + '" placeholder="描述这次要改变什么，或先记下原文"></textarea></label>' +
      '<div class="y7-row">' +
        '<button type="button" class="y7-btn" data-act="dept.recordMaterial" data-project-id="' + esc(v.project.id) + '" data-department="' + esc(d.id) + '" data-draft-key="' + esc(key) + '"><span>记录原文</span></button>' +
        '<button type="button" class="y7-btn primary" data-act="dept.startItem" data-project-id="' + esc(v.project.id) + '" data-department="' + esc(d.id) + '" data-draft-key="' + esc(key) + '"><span>作为新事项开始</span></button>' +
        '<span class="y7-muted y7-small">没有进行中的事项时，不会调用模型。</span></div></div>';
  }

  function commsBlock(v) {
    const log = '<section class="y7-ws-col"><h3 class="y7-h3">部门消息 <span class="y7-muted y7-small">最新在上 · 用户、本部门与其他部门分开标记</span></h3>' + (v.run ? messagesHtml(v) : ui.empty('本项目还没有事项')) + '</section>';
    const guide = '<section class="y7-ws-col"><h3 class="y7-h3">部门指导</h3>' + composerHtml(v) + (v.run ? '<h3 class="y7-h3">指导记录</h3>' + guidanceRecords(v) : '') + '</section>';
    return ui.block({
      title: '部门消息与指导', tag: '当前', level: 'now', query: 'department.workspace',
      command: v.composer.mode === 'guidance' ? 'sendGuidance' : ['recordMaterial', 'createWorkItem'],
      className: 'y7-ws-comms', body: '<div class="y7-ws-comms-grid">' + log + guide + '</div>'
    });
  }

  // ---------------------------------------------------------------------------
  // 渲染：运维部门工作间（Stage 5）

  function opsBlocks(v) {
    const ops = v.ops;
    const pid = v.project.id;
    if (!ops) {
      return ui.block({
        title: '运行责任', tag: 'Stage 5', level: 's5', query: 'ops.status', command: 'acceptResponsibility',
        body: ui.empty('本项目还没有交给运维部门的运行责任：项目采纳的交付物发布后，由运维部门接收并长期负责运行。')
      });
    }
    const r = ops.responsibility;
    const awaiting = ops.releases.filter((rel) => rel.awaiting);
    const resp = ui.kv([
      ['交付物版本', ui.code(r.version)],
      ['环境', esc(r.env)],
      ['接收时间', esc(Y7.ui.time(r.acceptedAt))],
      ['责任方', esc(r.owner)]
    ]) + ui.note(esc(r.platform), 'info') +
      (awaiting.length
        ? '<div class="y7-row y7-ws-accept">' + awaiting.map((rel) => '<span>已发布版本 ' + esc(rel.version) + '，运维未接收</span>' + ui.button({ label: '接收 ' + rel.version + ' 的运行责任', kind: 'small primary', cmd: 'acceptResponsibility', data: { projectId: pid, version: rel.version } })).join('') + '</div>'
        : '<p class="y7-muted y7-small">没有等待接收的发布；发布成功与运维接收分别记录。</p>');
    const releases = ui.table({
      columns: [
        { key: 'version', label: '版本', className: 'y7-col-status', render: (row) => ui.code(row.version) },
        { key: 'adoptionDigest', label: '采纳 digest', render: (row) => ui.code(row.adoptionDigest) },
        { key: 'releaseDigest', label: '发布 digest', render: (row) => ui.code(row.releaseDigest) },
        { key: 'digestMatch', label: '对照', className: 'y7-col-status', render: (row) => row.digestMatch ? ui.status('succeeded', '一致') : ui.status('failed', '不一致') },
        { key: 'at', label: '发布时间', className: 'y7-col-status', render: (row) => esc(Y7.ui.time(row.at)) },
        { key: 'state', label: '状态' }
      ],
      rows: ops.releases
    });
    const incidents = ops.incidents.map((inc) =>
      '<article class="y7-ws-incident"><header><strong>' + esc(inc.id) + ' · ' + esc(inc.title) + '</strong>' +
      (inc.alarm ? ui.status('failed', '告警中') : inc.open ? ui.status('running', '处理中') : ui.status('done', '已复盘')) +
      (inc.item ? '<button type="button" class="y7-link" data-go="' + esc(Y7.paths.overview(pid, inc.item.id)) + '">修复事项「' + esc(inc.item.title) + '」</button>' : '') + '</header>' +
      '<ol class="y7-ws-steps">' + inc.steps.map((step) =>
        '<li class="is-' + esc(step.state) + '"><span class="y7-ws-step-dot" aria-hidden="true"></span><div><strong>' + esc(step.label) + '</strong>' +
        '<small>' + esc({ done: '已完成', current: '进行中', todo: '未开始' }[step.state]) + (step.at ? ' · ' + esc(Y7.ui.time(step.at)) : '') + '</small>' +
        (step.note ? '<small class="y7-muted">' + esc(step.note) + '</small>' : '') + '</div></li>'
      ).join('') + '</ol></article>'
    ).join('');
    const indicators = '<div class="y7-ws-indicators">' + ops.indicators.map((ind) =>
      '<div class="y7-ws-indicator"><span>' + esc(ind.label) + '</span><strong>' + esc(ind.value) + '</strong>' +
      '<small>' + (ind.numerator !== null && ind.numerator !== undefined ? esc(ind.numerator) + ' / ' : '分母 ') + esc(ind.denominator) + ' · ' + esc(ind.window) + '</small></div>'
    ).join('') + '</div><p class="y7-muted y7-small">每项指标都带分母；分母为空时不记为 100% 成功。</p>';
    const pending = ops.pendingActions.filter((act) => act.state === 'pending');
    const decided = ops.pendingActions.filter((act) => act.state !== 'pending');
    const actionRows = pending.length
      ? pending.map((act) =>
        '<article class="y7-ws-ext"><header><span class="y7-ws-ext-kind">' + esc(act.kind) + '</span><strong>' + esc(act.target) + '</strong><span class="y7-muted">' + esc(Y7.ui.time(act.requestedAt)) + ' 申请</span></header>' +
        '<p>' + esc(act.reason) + '</p><div class="y7-row">' +
        ui.button({ label: '授权这一次', kind: 'small primary', cmd: 'authorizeOpsAction', data: { projectId: pid, actionId: act.id, decision: 'approve' } }) +
        ui.button({ label: '拒绝', kind: 'small danger', cmd: 'authorizeOpsAction', data: { projectId: pid, actionId: act.id, decision: 'reject' } }) + '</div></article>'
      ).join('')
      : ui.empty('没有待授权的外部动作');
    const decidedRows = decided.length
      ? '<h3 class="y7-h3">已处理</h3><ul class="y7-ws-decided">' + decided.map((act) => '<li>' + ui.status(act.state === 'approved' ? 'succeeded' : 'cancelled', act.state === 'approved' ? '已授权一次' : '已拒绝') + '<span>' + esc(act.kind + ' · ' + act.target) + '</span><span class="y7-muted">' + esc(Y7.ui.time(act.decidedAt)) + '</span></li>').join('') + '</ul>'
      : '';
    return '<div class="y7-ws-ops-grid">' +
        ui.block({ title: '运行责任', tag: 'Stage 5', level: 's5', query: 'ops.status', command: 'acceptResponsibility', body: resp }) +
        ui.block({ title: '发布记录', tag: 'Stage 5', level: 's5', query: 'ops.status', command: '无', subtitle: '发布 digest 与项目采纳 digest 对照', body: releases }) +
      '</div>' +
      ui.block({ title: '故障链路', tag: 'Stage 5', level: 's5', query: 'ops.status', command: '无', body: incidents || ui.empty('没有故障记录') }) +
      ui.block({ title: '运行指标', tag: 'Stage 5', level: 's5', query: 'ops.status', command: '无', body: indicators }) +
      ui.block({ title: '待授权的外部动作', tag: 'Stage 5', level: 's5', query: 'ops.status', command: 'authorizeOpsAction', subtitle: '部署、回滚、重启逐项授权；缓解只在登记过的清单内执行，授权一次不作为永久授权。', body: actionRows + decidedRows });
  }

  // ---------------------------------------------------------------------------
  // 页面

  function viewFor(ctx) {
    return Y7.query('department.workspace', {
      projectId: ctx.project.id,
      department: ctx.route.params.department,
      workItemId: ctx.workItem ? ctx.workItem.id : null
    });
  }

  function regions(v) {
    return {
      head: headBlock(v),
      ops: v.department.id === 'operations' ? opsBlocks(v) : '',
      inspect: inspectBlock(v),
      comms: commsBlock(v)
    };
  }

  function rememberView(v) {
    st.view = {
      projectId: v.project.id,
      department: v.department.id,
      workItemId: v.item ? v.item.id : null,
      lastDepartment: v.run ? (v.run.department || v.run.lastDepartment) : null,
      model: v
    };
  }

  // 事件属于本部门：同一项目与事项，部门是事件的部门或交接的一端；没有部门的终止事件属于最后所在的部门
  function belongs(ev) {
    const view = st.view;
    if (!view) return false;
    if (ev.projectId && ev.projectId !== view.projectId) return false;
    if (ev.workItemId && view.workItemId && ev.workItemId !== view.workItemId) return false;
    const pl = ev.payload || {};
    if (ev.department) return ev.department === view.department || pl.from === view.department || pl.to === view.department;
    if (pl.from === view.department || pl.to === view.department) return true;
    return TERMINAL_EVENTS.includes(ev.type) && view.lastDepartment === view.department;
  }

  function onDomainEvent(ev) {
    if (!st.room || !belongs(ev)) return;
    st.lastEvent = ev;
    st.room.playEvent(ev);
    const info = document.querySelector('[data-ws-region="room-info"]');
    if (info && st.view) info.innerHTML = roomFacts(st.view.model);
  }

  // 重新渲染区块时保持正在输入的草稿框的焦点与光标
  function keepFocus(fn) {
    const el = document.activeElement;
    const key = el && el.dataset ? el.dataset.draft : null;
    const start = key ? el.selectionStart : null;
    const end = key ? el.selectionEnd : null;
    fn();
    if (!key) return;
    const next = document.querySelector('[data-draft="' + CSS.escape(key) + '"]');
    if (!next) return;
    next.value = Y7.draft(key);
    next.focus();
    next.setSelectionRange(start, end);
  }

  Y7.views.register('dept', {
    title: (ctx) => Y7.deptLabel(ctx.route.params.department) + '部门',
    render(ctx) {
      const v = viewFor(ctx);
      rememberView(v);
      const r = regions(v);
      return '<div class="y7-ws" data-dept="' + esc(v.department.id) + '">' +
        '<div data-ws-region="head">' + r.head + '</div>' +
        roomBlock(v) +
        '<div data-ws-region="ops">' + r.ops + '</div>' +
        '<div data-ws-region="inspect">' + r.inspect + '</div>' +
        '<div data-ws-region="comms">' + r.comms + '</div>' +
        '</div>';
    },
    mount(ctx, root) {
      const canvas = root.querySelector('.y7-ws-canvas');
      if (!canvas) throw new Error('部门房间缺少画布');
      if (!Y7.pixel || typeof Y7.pixel.createRoomScene !== 'function') throw new Error('像素画面未加载：需要 js/pixel/room.js');
      st.lastEvent = null;
      st.room = Y7.pixel.createRoomScene(canvas, { department: st.view.department, level: Y7.state.level });
      st.room.setModel(st.view.model.roomModel);
      st.onEvent = onDomainEvent;
      Y7.bus.on('domain-event', st.onEvent);
    },
    update(ctx, root) {
      const v = viewFor(ctx);
      rememberView(v);
      const r = regions(v);
      keepFocus(() => {
        ['head', 'ops', 'inspect', 'comms'].forEach((name) => {
          const el = root.querySelector('[data-ws-region="' + name + '"]');
          if (!el) throw new Error('部门工作间缺少区域：' + name);
          el.innerHTML = r[name];
        });
        root.querySelector('[data-ws-region="room-info"]').innerHTML = roomFacts(v);
      });
      st.room.setModel(v.roomModel);
      if (st.modal) refreshModalSummary();
    },
    unmount() {
      if (st.onEvent) Y7.bus.off('domain-event', st.onEvent);
      st.onEvent = null;
      if (st.room) st.room.destroy();
      st.room = null;
      st.view = null;
    }
  });

  function rerenderInspect() {
    if (!st.view) return;
    const el = document.querySelector('[data-ws-region="inspect"]');
    if (el) el.innerHTML = inspectBlock(st.view.model);
  }

  // ---------------------------------------------------------------------------
  // 部门设置弹窗（D24 第 9.2 节；Stage 4 增加本项目各角色的设置）

  function modalCtx() {
    const m = st.modal;
    const settings = Y7.query('project.settings', { projectId: m.projectId });
    return { m, settings, entry: settings.departments[m.dept], cat: Y7.atLeast('s3') ? Y7.query('catalog') : null };
  }

  function modelOptions(cat, selected, followLabel) {
    const admitted = cat.admittedDefinitions;
    const groups = cat.connections.map((conn) => {
      const defs = admitted.filter((def) => def.connectionId === conn.id);
      if (!defs.length) return '';
      return '<optgroup label="' + esc(conn.name) + '">' + defs.map((def) => '<option value="' + esc(def.id) + '"' + (def.id === selected ? ' selected' : '') + '>' + esc(def.upstreamModel) + '</option>').join('') + '</optgroup>';
    }).join('');
    const orphan = selected && !admitted.some((def) => def.id === selected)
      ? '<option value="' + esc(selected) + '" selected>' + esc(Y7.model.label(selected)) + '（无法使用：' + esc(Y7.model.problemOf(selected)) + '）</option>'
      : '';
    return '<option value=""' + (selected ? '' : ' selected') + '>' + esc(followLabel) + '</option>' + orphan + groups;
  }

  function levelFieldHtml(definitionId, selected, inheritedLevel, attrs) {
    const def = definitionId ? Y7.model.definition(definitionId) : null;
    if (!def) return '<select class="y7-select" ' + attrs + ' disabled><option>跟随</option></select><small class="y7-muted">没有生效的模型：先选择模型</small>';
    const levels = def.reasoning ? def.reasoning.levels : [];
    if (!levels.length) return '<select class="y7-select" ' + attrs + ' disabled><option>跟随</option></select><small class="y7-muted">该模型未声明推理档位，请求不带推理参数</small>';
    const inherited = inheritedLevel ? inheritedLevel : '模型默认 ' + def.reasoning.defaultLevel;
    const value = selected && levels.includes(selected) ? selected : '';
    const sent = Y7.model.clampLevel(value || inheritedLevel || null, def.reasoning);
    return '<select class="y7-select" ' + attrs + '><option value=""' + (value ? '' : ' selected') + '>跟随（当前：' + esc(inherited) + '）</option>' +
      levels.map((level) => '<option value="' + esc(level) + '"' + (level === value ? ' selected' : '') + '>' + esc(level) + '</option>').join('') + '</select>' +
      '<small class="y7-muted">支持 ' + esc(levels.join('、')) + ' · 实际发送 ' + esc(sent) + (selected && !levels.includes(selected) ? ' · 原选择 ' + esc(selected) + ' 不在支持范围内，已改为跟随' : '') + '</small>';
  }

  function deptModelSection(c) {
    const { m, cat } = c;
    const deptDefault = cat.departmentDefaults[m.dept] || null;
    const followLabel = '跟随部门默认（当前：' + (deptDefault && deptDefault.definition ? Y7.model.label(deptDefault.definition) : '未设置') + '）';
    const effective = m.model || (deptDefault ? deptDefault.definition : null);
    const problem = effective ? Y7.model.problemOf(effective) : '未设置';
    const status = problem ? ui.status(problem === '未设置' ? 'idle' : 'unusable', problem === '未设置' ? '未设置' : '无法使用：' + problem) : ui.status('admitted', '已准入');
    return '<label class="y7-field"><span>模型</span><select class="y7-select" id="y7-dm-model" data-act="dept.modalModel">' + modelOptions(cat, m.model, followLabel) + '</select>' +
        '<small class="y7-ws-inline"><span class="y7-muted">生效：' + esc(effective ? Y7.model.label(effective) : '未设置') + '</span>' + status + '</small></label>' +
      '<div class="y7-field" id="y7-dm-level-field"><span>推理档位</span>' + levelFieldHtml(effective, m.level, deptDefault ? deptDefault.level : null, 'id="y7-dm-level" data-act="dept.modalLevel"') + '</div>';
  }

  function promptSection(c) {
    const { m, entry } = c;
    const label = entry.promptText === null ? '默认 v0' : '配置 v' + entry.promptVersion;
    const def = builtInPrompt(m.dept);
    const value = entry.promptText === null ? (def || '') : entry.promptText;
    return '<div class="y7-field"><span>部门 Prompt</span>' +
      '<p class="y7-ws-inline y7-small"><span class="y7-muted">当前</span>' + ui.tag(label) + (Y7.atLeast('s3') ? '<span class="y7-muted">设置版本 v' + esc(entry.version) + '</span>' : '') + '</p>' +
      '<textarea class="y7-textarea" rows="7" id="y7-dm-prompt" data-draft="' + esc(m.draftKey) + '" placeholder="内置默认 Prompt（版本 0）">' + esc(value) + '</textarea>' +
      '<div class="y7-row">' + ui.button({ label: '恢复默认', kind: 'small', act: 'dept.promptDefault' }) + '<small class="y7-muted">恢复默认或留空时使用内置默认 Prompt（版本 0）；运行中的请求不中断。</small></div></div>';
  }

  function rolesSection(c) {
    const { m, settings, cat } = c;
    const roles = settings.roles[m.dept] || [];
    if (!roles.length) return '';
    const rows = roles.map((role) => {
      const draft = m.roles[role.id];
      const inherited = role.inherited;
      const followLabel = '跟随（当前：' + (inherited.definition ? Y7.model.label(inherited.definition) + ' · ' + inherited.source : '未设置') + '）';
      const effective = draft.model || inherited.definition;
      return '<div class="y7-dm-role" data-role-id="' + esc(role.id) + '">' +
        '<div class="y7-dm-role-name"><strong>' + esc(role.name) + '</strong><small class="y7-muted">' + esc(role.duty) + '</small>' +
        '<small class="y7-ws-inline"><span class="y7-muted">生效：' + esc(role.resolved.definition ? Y7.model.label(role.resolved.definition) : '未设置') + ' · ' + esc(role.resolved.source || '—') + '</span></small></div>' +
        '<label class="y7-field"><span>模型</span><select class="y7-select" data-act="dept.roleModel" data-role-id="' + esc(role.id) + '">' + modelOptions(cat, draft.model, followLabel) + '</select></label>' +
        '<div class="y7-field" data-role-level="' + esc(role.id) + '"><span>推理档位</span>' + levelFieldHtml(effective, draft.level, inherited.requestLevel, 'data-act="dept.roleLevel" data-role-id="' + esc(role.id) + '"') + '</div>' +
        '<label class="y7-field y7-dm-role-prompt"><span>角色 Prompt</span><textarea class="y7-textarea" rows="2" data-role-prompt="' + esc(role.id) + '" data-draft="' + esc(m.draftKey + '.role.' + role.id) + '" placeholder="内置角色 Prompt">' + esc(role.setting && role.setting.promptText ? role.setting.promptText : '') + '</textarea></label>' +
        '</div>';
    }).join('');
    return '<section class="y7-dm-roles"><h3 class="y7-h3">本项目各角色设置 ' + ui.tag('Stage 4') + '</h3>' +
      '<p class="y7-muted y7-small">解析顺序：项目角色设置、角色默认、项目部门设置、部门默认，取第一个写入了的。角色 Prompt 没有写入时使用内置角色 Prompt；部门 Prompt 作为全部门规则放入每个角色的请求。</p>' +
      rows + '<div class="y7-row">' + ui.button({ label: '保存角色设置', kind: 'primary small', act: 'dept.saveRoles' }) + '<small class="y7-muted">从这些角色下一次模型请求起生效。</small></div></section>';
  }

  function conflictNote(c) {
    const { m, entry } = c;
    if (!m.conflict) return '';
    if (!Y7.atLeast('s3')) {
      return ui.note('当前配置 ' + esc(entry.promptText === null ? '默认 v0' : 'v' + entry.promptVersion) + '（已在另一处更新，草稿仍保留）。' +
        '<span class="y7-note-actions">' + ui.button({ label: '重新读取', kind: 'small primary', act: 'dept.modalReload' }) + '</span>', 'warn');
    }
    const latest = [];
    if (Y7.atLeast('s3')) {
      latest.push('模型 ' + (entry.model ? Y7.model.label(entry.model) : '跟随部门默认'));
      latest.push('推理档位 ' + (entry.level || '跟随'));
    }
    latest.push('部门 Prompt ' + (entry.promptText === null ? '默认 v0' : '配置 v' + entry.promptVersion));
    return ui.note('版本冲突：本部门设置已被更新为 v' + esc(entry.version) + '（你打开时为 v' + esc(m.baseVersion) + '）。最新内容：' + esc(latest.join('，')) + '。你的草稿仍保留。' +
      '<span class="y7-note-actions">' + ui.button({ label: '重新读取', kind: 'small primary', act: 'dept.modalReload' }) + '</span>', 'warn');
  }

  function modalBody() {
    const c = modalCtx();
    const label = Y7.deptLabel(c.m.dept);
    const parts = ['<p class="y7-muted y7-small" data-dm-summary>' + modalSummary(c) + '</p>', conflictNote(c)];
    if (Y7.atLeast('s3')) parts.push(deptModelSection(c));
    else parts.push(ui.note('本次模型在「模型与 Provider」页的三部门绑定中设置，在途事项沿用创建时的快照。<span class="y7-note-actions">' + ui.button({ label: '模型与 Provider', kind: 'small', go: '#/sys/models', close: true }) + '</span>', 'info'));
    parts.push(promptSection(c));
    if (Y7.atLeast('s4') && c.m.dept !== 'operations') parts.push(rolesSection(c));
    parts.push('<p class="y7-proto-helper">原型演示：<button type="button" class="y7-link" data-act="dept.simulateConflict">模拟另一处先保存了' + esc(label) + (Y7.atLeast('s3') ? '部门设置' : '部门 Prompt') + '</button>，用来查看版本冲突的提示。</p>');
    return parts.join('');
  }

  function modalSummary(c) {
    const name = esc(Y7.project(c.m.projectId).name);
    const dept = esc(Y7.deptLabel(c.m.dept));
    if (!Y7.atLeast('s3')) {
      return '配置本项目「' + name + '」' + dept + '部门的部门 Prompt。当前配置 ' + esc(c.entry.promptText === null ? '默认 v0' : 'v' + c.entry.promptVersion) + '；已发出的请求不从当前配置回填。';
    }
    return '写入本项目「' + name + '」' + dept + '部门的项目部门设置，不修改部门默认；只写入你修改的项。当前设置版本 v' + esc(c.entry.version) + '。';
  }

  function refreshModalSummary() {
    const el = Y7.dom.modal.querySelector('[data-dm-summary]');
    if (el && st.modal) el.innerHTML = modalSummary(modalCtx());
  }

  function openModal() {
    const m = st.modal;
    Y7.ui.modal({
      title: '本项目 · ' + Y7.deptLabel(m.dept) + '部门设置',
      wide: Y7.atLeast('s4') && m.dept !== 'operations',
      className: 'y7-dm',
      body: modalBody(),
      actions: [
        { label: '取消', close: true },
        { label: '保存', kind: 'primary', act: 'dept.saveSettings' }
      ]
    });
  }

  function startModal(projectId, dept) {
    const settings = Y7.query('project.settings', { projectId });
    const entry = settings.departments[dept];
    if (!entry) throw new Error('项目没有这个部门的设置：' + dept);
    const roles = {};
    if (Y7.atLeast('s4') && settings.roles[dept]) {
      settings.roles[dept].forEach((role) => {
        roles[role.id] = { model: role.setting && role.setting.model ? role.setting.model : '', level: role.setting && role.setting.level ? role.setting.level : '' };
      });
    }
    st.modal = {
      projectId, dept,
      baseVersion: entry.version,
      model: entry.model || '',
      level: entry.level || '',
      conflict: false,
      roles,
      draftKey: 'dept.prompt.' + projectId + '.' + dept
    };
    openModal();
  }

  // ---------------------------------------------------------------------------
  // 界面动作

  Y7.actions.register('dept.openSettings', (el) => startModal(el.dataset.projectId, el.dataset.department));

  Y7.actions.register('dept.modalModel', (el) => {
    st.modal.model = el.value;
    const c = modalCtx();
    const deptDefault = c.cat.departmentDefaults[st.modal.dept] || null;
    const effective = st.modal.model || (deptDefault ? deptDefault.definition : null);
    const def = effective ? Y7.model.definition(effective) : null;
    if (st.modal.level && !(def && def.reasoning && def.reasoning.levels.includes(st.modal.level))) st.modal.level = '';
    const body = Y7.dom.modal.querySelector('.y7-modal-body');
    const scroll = body.scrollTop;
    body.innerHTML = modalBody();
    Y7.restoreDrafts(body);
    body.scrollTop = scroll;
  });

  Y7.actions.register('dept.modalLevel', (el) => {
    st.modal.level = el.value;
    const c = modalCtx();
    const deptDefault = c.cat.departmentDefaults[st.modal.dept] || null;
    const effective = st.modal.model || (deptDefault ? deptDefault.definition : null);
    Y7.dom.modal.querySelector('#y7-dm-level-field').innerHTML = '<span>推理档位</span>' + levelFieldHtml(effective, st.modal.level, deptDefault ? deptDefault.level : null, 'id="y7-dm-level" data-act="dept.modalLevel"');
  });

  Y7.actions.register('dept.roleModel', (el) => {
    const roleId = el.dataset.roleId;
    st.modal.roles[roleId].model = el.value;
    const role = modalCtx().settings.roles[st.modal.dept].find((entry) => entry.id === roleId);
    const effective = el.value || role.inherited.definition;
    const def = effective ? Y7.model.definition(effective) : null;
    const draft = st.modal.roles[roleId];
    if (draft.level && !(def && def.reasoning && def.reasoning.levels.includes(draft.level))) draft.level = '';
    Y7.dom.modal.querySelector('[data-role-level="' + CSS.escape(roleId) + '"]').innerHTML = '<span>推理档位</span>' + levelFieldHtml(effective, draft.level, role.inherited.requestLevel, 'data-act="dept.roleLevel" data-role-id="' + esc(roleId) + '"');
  });

  Y7.actions.register('dept.roleLevel', (el) => {
    st.modal.roles[el.dataset.roleId].level = el.value;
  });

  Y7.actions.register('dept.promptDefault', () => {
    const area = Y7.dom.modal.querySelector('#y7-dm-prompt');
    area.value = builtInPrompt(st.modal.dept) || '';
    Y7.setDraft(st.modal.draftKey, area.value);
    area.focus();
  });

  Y7.actions.register('dept.modalReload', () => {
    const c = modalCtx();
    st.modal.baseVersion = c.entry.version;
    st.modal.conflict = false;
    const body = Y7.dom.modal.querySelector('.y7-modal-body');
    body.innerHTML = modalBody();
    Y7.restoreDrafts(body);
    Y7.ui.toast('已重新读取 v' + c.entry.version + '；草稿保留，检查后再保存');
  });

  // 原型演示：另一处先保存了本部门设置，下一次保存会遇到版本冲突
  Y7.actions.register('dept.simulateConflict', () => {
    const entry = ensureDeptSettings(st.modal.projectId, st.modal.dept);
    entry.version += 1;
    Y7.ui.toast(Y7.atLeast('s3') ? '原型：本部门设置已在另一处保存为 v' + entry.version : '原型：部门 Prompt 配置已在另一处保存');
    refreshModalSummary();
  });

  // 部门 Prompt 的保存值：留空或与内置默认相同时为 null（恢复默认）
  function promptValue(text) {
    const trimmed = text.trim();
    if (!trimmed) return null;
    const def = builtInPrompt(st.modal.dept);
    return def && trimmed === def.trim() ? null : trimmed;
  }

  Y7.actions.register('dept.saveSettings', () => {
    const m = st.modal;
    const area = Y7.dom.modal.querySelector('#y7-dm-prompt');
    const params = { projectId: m.projectId, department: m.dept, baseVersion: m.baseVersion, promptText: promptValue(area.value) };
    if (Y7.atLeast('s3')) {
      params.model = m.model;
      params.level = m.level;
    }
    const result = Y7.command('saveDepartmentSettings', params);
    if (result.ok) {
      Y7.clearDraft(m.draftKey);
      st.modal = null;
      Y7.ui.closeModal();
      return;
    }
    if (result.conflict) {
      m.conflict = true;
      const body = Y7.dom.modal.querySelector('.y7-modal-body');
      Y7.setDraft(m.draftKey, area.value);
      body.innerHTML = modalBody();
      Y7.restoreDrafts(body);
      body.scrollTop = 0;
    }
  });

  Y7.actions.register('dept.saveRoles', () => {
    const m = st.modal;
    const entries = Object.keys(m.roles).map((roleId) => {
      const area = Y7.dom.modal.querySelector('[data-role-prompt="' + CSS.escape(roleId) + '"]');
      const text = area.value.trim();
      return { roleId, model: m.roles[roleId].model || null, level: m.roles[roleId].level || null, promptText: text || null };
    });
    const result = Y7.command('saveRoleSettings', { projectId: m.projectId, department: m.dept, entries });
    if (!result.ok) return;
    Object.keys(m.roles).forEach((roleId) => Y7.clearDraft(m.draftKey + '.role.' + roleId));
    const body = Y7.dom.modal.querySelector('.y7-modal-body');
    const scroll = body.scrollTop;
    body.innerHTML = modalBody();
    Y7.restoreDrafts(body);
    body.scrollTop = scroll;
  });

  Y7.actions.register('dept.sendGuidance', (el) => {
    const area = document.getElementById('y7-ws-guidance');
    const run = Y7.run(el.dataset.runId);
    const item = Y7.workItem(run.workItemId);
    const result = Y7.command('sendGuidance', { runId: el.dataset.runId, department: el.dataset.department, text: area.value, draftKey: el.dataset.draftKey });
    if (!result.ok) return;
    // 事件流送回 department_guidance_received：房间里门缝塞进纸条，信箱灯亮
    Y7.bus.emit('domain-event', {
      seq: Date.now(), type: 'department_guidance_received', at: Y7.data.now, projectId: item.projectId, workItemId: item.id,
      department: el.dataset.department, role: null, tool: null, label: '门缝塞进纸条，信箱灯亮：指导 v' + result.version + ' 已接收', payload: { guidanceVersion: result.version }
    });
  });

  Y7.actions.register('dept.recordMaterial', (el) => {
    const area = document.getElementById('y7-ws-new');
    Y7.command('recordMaterial', { projectId: el.dataset.projectId, department: el.dataset.department, text: area.value, draftKey: el.dataset.draftKey });
  });

  Y7.actions.register('dept.startItem', (el) => {
    const area = document.getElementById('y7-ws-new');
    const result = Y7.command('createWorkItem', { projectId: el.dataset.projectId, text: area.value, draftKey: el.dataset.draftKey });
    if (result.ok) Y7.go(Y7.paths.dept(el.dataset.projectId, el.dataset.department, result.workItemId));
  });

  Y7.actions.register('dept.pickContext', (el) => {
    st.contextSel[el.dataset.key] = el.dataset.contextId;
    rerenderInspect();
  });

  Y7.actions.register('dept.showContext', (el) => {
    st.contextSel[el.dataset.key] = el.dataset.contextId;
    Y7.state.tabs['dept.inspect'] = 'context';
    rerenderInspect();
    const block = document.querySelector('[data-ws-region="inspect"]');
    if (block) block.scrollIntoView({ block: 'start' });
  });

  Y7.actions.register('dept.toggleInactive', (el) => {
    st.showInactive = el.checked;
    rerenderInspect();
  });

  // 原始事件：按事件 ID 汇总 run 中引用它的记录
  Y7.actions.register('dept.openEvent', (el) => {
    const run = Y7.run(el.dataset.runId);
    if (!run) throw new Error('run 不在当前档位或不存在：' + el.dataset.runId);
    const id = el.dataset.eventId;
    const records = [];
    Object.keys(run.messages).forEach((dept) => run.messages[dept].filter((msg) => msg.eventId === id).forEach((msg) => records.push(Object.assign({ record: '部门消息', department: dept }, msg))));
    run.flow.filter((entry) => entry.eventId === id).forEach((entry) => records.push(Object.assign({ record: '流转记录' }, entry)));
    (run.guidance || []).filter((g) => g.eventId === id).forEach((g) => records.push(Object.assign({ record: '部门指导' }, g)));
    (run.requests || []).filter((req) => req.eventId === id).forEach((req) => records.push(Object.assign({ record: '协作请求' }, req)));
    (run.compactions || []).filter((entry) => entry.eventId === id).forEach((entry) => records.push(Object.assign({ record: '压缩记录' }, entry)));
    const item = Y7.workItem(run.workItemId);
    const doc = { event_id: id, run_id: run.id, work_item_id: item.id, project_id: item.projectId, records };
    Y7.ui.modal({
      title: '事件 ' + id,
      wide: true,
      body: '<p class="y7-muted y7-small">原型按事件 ID 汇总示例数据中引用它的记录；真实界面读取事件库中的原始事件与工件。</p>' + ui.pre(JSON.stringify(doc, null, 2)),
      actions: [{ label: '关闭', close: true }]
    });
  });

  Y7.actions.register('dept.roleHistory', (el) => {
    const v = st.view.model;
    const role = v.roles.find((entry) => entry.id === el.dataset.roleId);
    if (!role) throw new Error('找不到角色：' + el.dataset.roleId);
    const tasks = v.ledger ? v.ledger.items.filter((entry) => entry.assignee === role.id) : [];
    const actions = v.run ? Y7.query('run.actions', { runId: v.run.id, department: v.department.id, role: role.id }) : [];
    const attempts = v.run ? attemptsOf(v.run, v.department.id).filter((att) => att.role === role.id) : [];
    const w = v.item ? v.item.id : null;
    const body = ui.kv([
      ['状态', ui.status(ROLE_STATUS_KIND[role.status] || 'idle', Y7.ROLE_STATUS_LABELS[role.status] || role.status)],
      ['类型', esc(ROLE_KIND_LABELS[role.kind])],
      ['模型', esc(role.resolved.definition ? Y7.model.label(role.resolved.definition) : '未设置') + '<small class="y7-muted y7-block-line">来源：' + esc(role.resolved.source || '—') + '</small>'],
      ['当前任务', esc(role.task || '没有任务')]
    ]) +
      '<h3 class="y7-h3">角色任务</h3>' + (tasks.length ? '<ul class="y7-list">' + tasks.map((task) => '<li>' + ui.code(task.id) + ' ' + esc(task.text) + ' · ' + esc((LEDGER_STATUS[task.status] || [null, task.status])[1]) + (task.result ? ' · ' + esc(task.result) : '') + '</li>').join('') + '</ul>' : '<p class="y7-muted y7-small">没有分派给这个角色的任务</p>') +
      '<h3 class="y7-h3">模型请求</h3>' + (attempts.length ? '<ul class="y7-list">' + attempts.map((att) => '<li><button type="button" class="y7-link" data-go="' + esc(Y7.paths.observeDetail(v.project.id, att.id, w)) + '" data-close-modal>' + esc(Y7.ui.time(att.startedAt)) + ' · ' + esc(att.requestedModel) + ' · ' + esc(Y7.ATTEMPT_LABELS[att.status]) + '</button></li>').join('') + '</ul>' : '<p class="y7-muted y7-small">这个角色在本事项中还没有模型请求</p>') +
      '<h3 class="y7-h3">动作</h3>' + (actions.length ? '<ul class="y7-list">' + actions.map((act) => '<li>' + esc(Y7.ui.time(act.at)) + ' · ' + esc(act.toolLabel) + ' · ' + esc(act.summary) + '</li>').join('') + '</ul>' : '<p class="y7-muted y7-small">没有动作</p>');
    const observe = Y7.paths.observe(v.project.id, w) + (w ? '&' : '?') + 'dept=' + v.department.id + '&role=' + role.id;
    Y7.ui.modal({
      title: role.name + ' · 历史与请求',
      body,
      actions: [{ label: '在观测中按角色筛选', go: observe, close: true }, { label: '关闭', kind: 'primary', close: true }]
    });
  });
})();
