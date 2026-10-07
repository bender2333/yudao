// 部门工作间、观测、设置的查询与命令（BUILD.md 第 5.3 节）
// 登记表还没有命令登记与源目录的事件种类，这里补上，交付说明里写明需要写入 registry.js。
// execution_placement.save、machine_authorization.save 需要 not_allowed，登记表的拒绝原因里没有，这里补上。
(function () {
  'use strict';
  const Y10 = window.Y10;
  const B = Y10.backend;
  if (!B || !B.helpers) throw new Error('handlers/department.js 需要先加载 handlers/core.js');

  const reject = B.helpers.reject;
  const TERMINAL = B.helpers.TERMINAL_PHASES;
  const DEPTS = ['product', 'engineering', 'quality', 'operations'];
  const LABELS = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const DUTY = {
    product: '维护原始意图与有效规范，回答需求咨询',
    engineering: '依据有效规范设计、实现、自测并提交交付',
    quality: '在独立副本中验证交付，给出缺陷或放行',
    operations: '接收交付物的运行责任，处理运行问题'
  };
  const PROTOCOL_LABELS = { responses: 'Responses', chat: 'Chat Completions', messages: 'Anthropic Messages' };
  const GUIDANCE_LABELS = {
    received: '已接收', in_input: '已进入模型输入', explained: '已解释',
    completed: '动作已核实', declined: '已说明边界', needs_work: '需要后续处理'
  };
  const PINNED = ['in_input', 'explained', 'completed', 'declined', 'needs_work'];
  const STATUS_TEXT = {
    idle: '未工作', working: '工作中', asking: '等待回答', paused: '已暂停', failed: '失败',
    done: '已完成', cancelled: '已取消', interrupted: '中断', pending_verification: '待核实', waiting_resume: '待恢复'
  };
  const STATUS_KIND = {
    idle: 'idle', working: 'running', asking: 'asking', paused: 'paused', failed: 'failed',
    done: 'done', cancelled: 'cancelled', interrupted: 'interrupted', pending_verification: 'pending', waiting_resume: 'waiting'
  };
  const ACTION_TEXT = { not_sent: '未发送', done: '已完成', unknown: '结果未知', running: '进行中' };
  const ATTEMPT_TEXT = {
    preparing: '准备中', requesting: '请求中', running: '进行中', succeeded: '成功', failed: '失败', cancelled: '已取消'
  };
  const LIVE = ['preparing', 'requesting', 'running'];
  const OPS_KINDS = ['external_action', 'rollback_restore', 'repair_stopped'];
  const LOCAL_PROCESS = 'local_process';
  const LOCAL_CONTAINER = 'local_container';
  const PAGE = 30;

  function models() {
    if (!B.models) throw new Error('模型解析尚未登记：handlers/system.js');
    return B.models;
  }

  function deptLabel(id) {
    if (!LABELS[id]) throw new Error('未知部门：' + id);
    return LABELS[id];
  }

  function requireText(value, name) {
    if (value === undefined || value === null || String(value).trim() === '') throw new Error('缺少' + name);
    return String(value);
  }

  function versionParam(params) {
    if (params.base_version === undefined || params.base_version === null || params.base_version === '') {
      throw new Error('缺少 base_version');
    }
    const n = Number(params.base_version);
    if (!Number.isFinite(n)) throw new Error('base_version 不是数字');
    return n;
  }

  function stale(current) {
    return reject('stale_base', '版本冲突：当前版本是 v' + current + '，请重新读取后再保存', { current_version: current });
  }

  function projectOf(db, id) {
    const project = db.project(id);
    if (!project) return null;
    return project;
  }

  function requireProjectQuery(db, id) {
    return B.helpers.requireProject(db, id);
  }

  function archived(project) {
    if (project.archived) return reject('project_archived', '项目已归档');
    return null;
  }

  function settingsRaw(db, projectId) {
    const all = db.raw && db.raw.project_settings;
    if (!all || !all[projectId]) throw new Error('项目设置不存在：' + projectId);
    return all[projectId];
  }

  function numOrNull(value) {
    if (value === undefined || value === null || value === '') return null;
    const n = Number(value);
    if (!Number.isFinite(n)) throw new Error('需要数字：' + value);
    return n;
  }

  function listParam(value) {
    if (Array.isArray(value)) return value;
    if (value === undefined || value === null || value === '') return [];
    if (typeof value === 'string') {
      const text = value.trim();
      if (!text) return [];
      if (text[0] === '[') return JSON.parse(text);
      return text.split(/[、,，]/).map((item) => item.trim()).filter(Boolean);
    }
    throw new Error('需要数组');
  }

  function event(type, fields, patch) {
    return Object.assign({ type: type, payload: {}, patch: patch || [] }, fields);
  }

  function accepted(events, refs) {
    return { events: events, refs: refs || {}, message: '已提交' };
  }

  function keyExists(obj, key) {
    return obj && Object.prototype.hasOwnProperty.call(obj, key);
  }

  function versionKeyPatch(projectId, key, current, has) {
    const base = 'project_settings.' + projectId;
    if (!has) return { path: base, put: { key: key, value: 1 } };
    return { path: base + '.' + key, value: current + 1 };
  }

  function requestLevel(entry) {
    if (!entry) return null;
    if (entry.request_level !== undefined && entry.request_level !== null) return entry.request_level;
    return entry.level || null;
  }

  function deptEntry(settings, department) {
    if (!settings || !settings.departments) return null;
    return settings.departments[department] || null;
  }

  function promptOf(db, settings, run, department) {
    const entry = deptEntry(settings, department);
    const defaults = db.data.default_prompts || {};
    const configText = entry && entry.prompt_text ? entry.prompt_text : (defaults[department] || '');
    const configVersion = entry && entry.prompt_text ? (entry.prompt_version || 0) : 0;
    const used = run && run.prompts && run.prompts[department] ? run.prompts[department] : null;
    return {
      config_version: configVersion,
      config_text: configText,
      request_version: used ? used.request_version : null,
      request_text: used ? used.text : null
    };
  }

  function imageWarning(target) {
    if (!target || target.image_input !== false) return null;
    const model = target.model || target.definition || '未设置';
    return {
      department: 'quality',
      model: model,
      definition: target.definition,
      missing: '图像输入',
      impact: '不提供 computer use，浏览器只给可访问性结构，不给截图',
      text: '质检的模型 ' + model + ' 缺少图像输入。不提供 computer use，浏览器只给可访问性结构，不给截图。'
    };
  }

  // 试用记录的一步：model_saw 表示模型是否看到这张截图（数据中没有写时按质检解析到的模型是否支持图像输入）
  function trialOut(trial, target) {
    const sawDefault = !target || target.image_input !== false;
    return Object.assign({}, trial, { model_saw: trial.model_saw === undefined ? sawDefault : Boolean(trial.model_saw) });
  }

  function focusItem(db, projectId, workItemId) {
    if (workItemId) {
      const item = db.workItem(workItemId);
      if (!item || item.project_id !== projectId) throw new Error('事项不存在或不属于该项目：' + workItemId);
      return item;
    }
    const items = db.workItemsOf(projectId);
    const active = items.find((item) => item.status === 'in_progress');
    if (active) return active;
    return items.slice().sort((a, b) => Y10.time.ms(b.created_at) - Y10.time.ms(a.created_at))[0] || null;
  }

  function roomStatus(db, run, department) {
    if (!run) return 'idle';
    const mine = run.department === department || run.last_department === department;
    if (run.department === department) {
      const recovery = db.atLeast('3.1') && run.recovery ? run.recovery.state : null;
      if (recovery === 'interrupted') return 'interrupted';
      if (recovery === 'pending_verification') return 'pending_verification';
      if (recovery === 'waiting_resume') return 'waiting_resume';
      if ((run.requests || []).some((req) => req.to === department && req.status === 'open')) return 'asking';
      if (run.phase === 'PAUSED') return 'paused';
      if (run.phase === 'FAILED') return 'failed';
      if (run.phase === 'DONE') return 'done';
      return 'working';
    }
    if (!mine) return 'idle';
    if (run.stop_reason && run.stop_reason.code === 'cancelled') return 'cancelled';
    if (run.phase === 'FAILED') return 'failed';
    if (run.phase === 'PAUSED') return 'paused';
    if (run.phase === 'DONE') return 'done';
    return 'idle';
  }

  function doorOf(status, run) {
    if (status === 'paused') return '已暂停';
    if (status === 'interrupted') return '中断';
    if (status === 'waiting_resume') return '待恢复';
    if (status === 'pending_verification') return '待核实';
    if (status === 'failed') return run && run.stop_reason ? '失败：' + (run.stop_reason.text || run.stop_reason.code) : '失败';
    if (status === 'done') return '已完成';
    if (status === 'cancelled') return '已取消';
    if (run && run.stop_reason && run.stop_reason.code === 'upgrade') return '因升级停止';
    return null;
  }

  function machineName(db, id) {
    if (!id) return null;
    const machine = db.machine(id);
    return machine ? machine.name : id;
  }

  function attemptsOf(db, projectId) {
    const out = [];
    (db.data.runs || []).forEach((run) => {
      if (run.project_id !== projectId) return;
      (run.attempts || []).forEach((attempt) => {
        out.push({ attempt: attempt, run: run });
      });
    });
    return out;
  }

  function findAttempt(db, id) {
    let found = null;
    (db.data.runs || []).some((run) => {
      const attempt = (run.attempts || []).find((item) => item.id === id);
      if (!attempt) return false;
      found = { attempt: attempt, run: run };
      return true;
    });
    return found;
  }

  function publicTarget(db, attempt) {
    const target = attempt.target || {};
    const catalog = db.data.catalog || {};
    const conn = (catalog.connections || []).find((item) => item.id === target.connection);
    const cred = conn && conn.credential_ref ? (catalog.credentials || []).find((item) => item.ref === conn.credential_ref) : null;
    return {
      connection: target.connection || null,
      connection_name: conn ? conn.name : null,
      protocol: target.protocol || null,
      base_url: target.base_url || (conn ? conn.base_url : null),
      model: target.model || attempt.actual_model || null,
      window: target.window || null,
      max_output: target.max_output || null,
      credential_ref: conn ? conn.credential_ref : null,
      credential_version: cred ? cred.version : null,
      source: target.source || null,
      request_level: target.request_level || null,
      sent_level: target.sent_level || null,
      prompt_version: target.prompt_version !== undefined ? target.prompt_version : null
    };
  }

  function attemptOut(db, pair) {
    const attempt = pair.attempt;
    const out = {
      id: attempt.id,
      logical_call_id: attempt.logical_call_id,
      project_id: pair.run.project_id,
      work_item_id: pair.run.work_item_id,
      run_id: pair.run.id,
      department: attempt.department,
      status: attempt.status,
      status_text: ATTEMPT_TEXT[attempt.status] || attempt.status,
      started_at: attempt.started_at,
      duration_ms: attempt.duration_ms,
      provider: attempt.provider || null,
      requested_model: attempt.requested_model || null,
      actual_model: attempt.actual_model || null,
      usage: attempt.usage || null,
      error: attempt.error || null,
      target: publicTarget(db, attempt)
    };
    if (db.atLeast('S5')) {
      out.role = attempt.role || null;
      out.kind = attempt.kind || null;
      out.semantic_units = attempt.semantic_units || [];
    }
    return out;
  }

  function sectionsOf(run, attempt) {
    const list = run.contexts && run.contexts[attempt.department];
    if (!Array.isArray(list)) return [];
    const found = list.find((item) => item.attempt_id === attempt.id) || list[list.length - 1];
    if (!found || !found.sources) return [];
    return found.sources.map((source) => ({
      label: source.label,
      version: source.version,
      included: source.included,
      reason: source.reason || null
    }));
  }

  function liveText(db, pair) {
    const attempt = pair.attempt;
    if (attempt.text) return String(attempt.text);
    if (attempt.received) return String(attempt.received);
    const started = attempt.started_at ? Y10.time.ms(attempt.started_at) : 0;
    return db.log({ run: pair.run.id, department: attempt.department, types: 'model_stream_progress' })
      .filter((ev) => !started || Y10.time.ms(ev.at) >= started)
      .map((ev) => (ev.payload && ev.payload.text) || '')
      .join('');
  }

  function semanticStore(db, projectId, raw) {
    const root = raw ? db.raw : db.data;
    const top = root && root.semantic && root.semantic[projectId];
    if (top && typeof top === 'object') return { where: 'top', value: top };
    const settings = raw ? settingsRaw(db, projectId) : db.settings(projectId);
    if (settings && settings.semantic && typeof settings.semantic === 'object') return { where: 'settings', value: settings.semantic };
    return null;
  }

  function semanticOut(db, projectId, department) {
    const store = semanticStore(db, projectId, false);
    const units = store && Array.isArray(store.value.units) ? store.value.units : [];
    const conflicts = store && Array.isArray(store.value.conflicts) ? store.value.conflicts : [];
    const visible = department ? units.filter((unit) => !unit.department || unit.department === department) : units;
    const visibleConflicts = department
      ? conflicts.filter((item) => !item.department || item.department === department || visible.some((unit) => unit.id === item.a || unit.id === item.b))
      : conflicts;
    const depts = ['product', 'engineering', 'quality'].concat(db.atLeast('S4') ? ['operations'] : []);
    const summary = depts.map((id) => ({
      department: id,
      valid: units.filter((unit) => unit.department === id && unit.status !== 'invalid' && unit.status !== 'superseded').length,
      conflicts: conflicts.filter((item) => item.department === id || units.some((unit) => unit.department === id && (unit.id === item.a || unit.id === item.b))).length
    }));
    return {
      version: store && typeof store.value.version === 'number' ? store.value.version : 0,
      entries: visible.map((unit) => ({
        id: unit.id,
        department: unit.department || null,
        type: unit.type || null,
        scope: unit.scope || null,
        text: unit.text,
        status: unit.status || 'valid',
        reason: unit.reason || null,
        superseded_by: unit.superseded_by || null,
        at: unit.at || null
      })),
      conflicts: visibleConflicts,
      chains: visible.filter((unit) => unit.superseded_by).map((unit) => ({
        from: unit.id, to: unit.superseded_by, reason: unit.reason || null, department: unit.department || null
      })),
      summary: summary
    };
  }

  function decisionCard(db, d) {
    const project = db.project(d.project_id);
    const item = d.work_item_id ? db.workItem(d.work_item_id) : null;
    const blocked = d.blocks && d.blocks.work_item_id ? db.workItem(d.blocks.work_item_id) : null;
    const out = Y10.clone(d);
    out.options = (d.options || []).map((option) => ({ id: option.id, label: option.label, kind: option.kind || null, requires: option.requires || null }));
    out.kind_label = Y10.registry.entry('decision', d.kind).label;
    out.project_name = project ? project.name : d.project_id;
    out.work_item_title = item ? item.title : null;
    out.waited_sec = B.helpers.since(db, d.issued_at);
    if (out.blocks) out.blocks.work_item_title = blocked ? blocked.title : null;
    return out;
  }

  // ---------------------------------------------------------------------------
  // 查询

  B.query('department.workspace', (params, db) => {
    const project = requireProjectQuery(db, requireText(params.project, '项目'));
    const department = requireText(params.department, '部门');
    deptLabel(department);
    const settings = db.settings(project.id);
    const item = focusItem(db, project.id, params.work_item || null);
    const run = item ? db.runOf(item.id) : null;
    const status = roomStatus(db, run, department);
    const resolved = models().resolve(db, project.id, department);
    const deptAttempts = run ? (run.attempts || []).filter((attempt) => attempt.department === department) : [];
    const last = deptAttempts.slice().sort((a, b) => Y10.time.ms(b.started_at) - Y10.time.ms(a.started_at))[0] || null;
    const guidance = run ? (run.guidance || []).filter((entry) => entry.department === department) : [];
    const messages = run && run.messages && run.messages[department] ? run.messages[department] : [];
    const contexts = run && run.contexts && run.contexts[department] ? run.contexts[department] : [];
    const compactions = run ? (run.compactions || []).filter((entry) => entry.department === department) : [];
    const actions = run ? (run.actions || []).filter((action) => action.department === department) : [];
    const unknown = db.atLeast('3.1') ? actions.find((action) => action.state === 'unknown') : null;
    const remote = db.atLeast('3.2C') ? actions.slice().reverse().find((action) => action.machine_id) : null;
    const openLetters = (run && run.requests || []).filter((req) => req.to === department && req.status === 'open').length;
    const entry = deptEntry(settings, department);
    const targetTitle = item ? item.title : '—';
    const roles = [];
    if (db.atLeast('S5') && run && run.roles && Array.isArray(run.roles[department]) && run.roles[department].length) {
      run.roles[department].forEach((role) => roles.push({
        id: role.id, name: role.name, kind: role.kind, status: role.status || 'idle', task: role.task || null
      }));
    } else {
      roles.push({
        id: department + '-agent',
        name: deptLabel(department) + '部门 Agent',
        kind: department === 'operations' ? 'ops' : 'agent',
        status: status === 'working' ? 'working' : 'idle',
        task: targetTitle === '—' ? null : targetTitle
      });
    }
    const primary = roles.find((role) => role.kind === 'architect' || role.kind === 'lead' || role.kind === 'tester' || role.kind === 'agent' || role.kind === 'ops') || roles[0];
    const prdCount = item ? (db.data.materials || []).filter((material) => material.work_item_id === item.id && material.kind === 'prd').length : 0;
    const room = {
      department: department,
      level: Y10.level.current(),
      status: status,
      crt: {
        target: targetTitle,
        model: resolved.model || '—',
        protocol: resolved.protocol || '—',
        status: STATUS_TEXT[status],
        cycle: run ? run.cycle : null
      },
      roles: roles,
      existing_read: Boolean(item && item.kind === 'onboarding'),
      pose: status === 'working' && primary ? { role_id: primary.id, action: 'typing' } : null,
      door: doorOf(status, run),
      hold_card: status === 'waiting_resume' && run && run.recovery && run.recovery.unusable ? run.recovery.unusable.problem : null,
      pending_tool: unknown ? unknown.tool : null,
      mailbox: guidance.filter((entryItem) => entryItem.status === 'received').length,
      summaries: compactions.reduce((max, entryItem) => Math.max(max, entryItem.n || 0), 0),
      scrolls: department === 'product' ? prdCount : 0,
      pinned_notes: guidance.filter((entryItem) => PINNED.includes(entryItem.status)).length,
      pipes: {
        out: status === 'interrupted' || (db.atLeast('S4') && run && run.waiting_provider && run.waiting_provider.department === department) ? 'stopped' : (status === 'working' ? 'flowing' : 'idle'),
        letters_waiting: openLetters
      }
    };
    if (db.atLeast('3.2C')) {
      room.machine = remote ? machineName(db, remote.machine_id) : null;
      room.remote_unknown = Boolean(unknown && unknown.machine_id);
    }
    if (db.atLeast('3.2B')) {
      const mcp = db.data.tools && db.data.tools.mcp ? db.data.tools.mcp : [];
      const buttons = [];
      mcp.forEach((service) => (service.tools || []).forEach((tool) => buttons.push(tool.name)));
      room.tool_panel = { buttons: buttons.slice(0, 6), lit: -1 };
    }
    if (db.atLeast('3.2D') && department === 'quality' && run && run.trials && run.trials.length) {
      const trial = trialOut(run.trials[run.trials.length - 1], resolved);
      room.trial = { screenshot: trial.screenshot || null, text_lines: trial.text_lines || null, step: trial.step, model_saw: trial.model_saw };
    }
    if (db.atLeast('S4')) {
      room.waiting_provider = Boolean(run && run.waiting_provider && run.waiting_provider.department === department);
    }
    if (db.atLeast('S5')) {
      const semantic = semanticOut(db, project.id, department);
      room.semantic_cards = semantic.entries.filter((unit) => unit.status !== 'invalid' && unit.status !== 'superseded').length;
    }
    const out = {
      project: { id: project.id, name: project.name, goal: project.goal, version: project.version, archived: Boolean(project.archived) },
      department: { id: department, label: deptLabel(department), duty: DUTY[department] },
      work_item: item ? { id: item.id, title: item.title, status: item.status, color_index: item.color_index } : null,
      run: run ? {
        id: run.id, phase: run.phase, cycle: run.cycle, elapsed_sec: run.elapsed_sec, limit_sec: run.limit_sec,
        department: run.department, yudao_version: run.yudao_version
      } : null,
      status: { id: status, kind: STATUS_KIND[status], text: STATUS_TEXT[status] },
      model: {
        definition: resolved.definition,
        label: resolved.definition ? models().label(resolved.definition) : '未设置',
        source: resolved.source,
        request_level: resolved.request_level,
        sent_level: resolved.sent_level,
        protocol: resolved.protocol,
        problem: resolved.problem,
        image_input: resolved.image_input
      },
      last_target: last ? Object.assign({ attempt_id: last.id, at: last.started_at, status: last.status, status_text: ATTEMPT_TEXT[last.status] || last.status }, publicTarget(db, last)) : null,
      prompt: promptOf(db, settings, run, department),
      messages: messages.slice().sort((a, b) => (b.seq || 0) - (a.seq || 0)),
      guidance: guidance.slice().sort((a, b) => Y10.time.ms(b.at) - Y10.time.ms(a.at)).map((entryItem) => Object.assign({}, entryItem, {
        status_text: GUIDANCE_LABELS[entryItem.status] || entryItem.status
      })),
      context: { snapshots: contexts, compactions: compactions },
      settings_version: entry && typeof entry.version === 'number' ? entry.version : 0,
      room: room
    };
    if (db.atLeast('3.1') && run) {
      out.run.recovery_state = run.recovery ? run.recovery.state : null;
      out.run.stop_reason = run.stop_reason || null;
    }
    if (db.atLeast('3.2D') && department === 'quality') {
      out.image_warning = imageWarning(resolved);
      out.trials = run && run.trials ? run.trials.map((trial) => trialOut(trial, resolved)) : [];
    }
    if (db.atLeast('S5')) {
      out.roles = roles.map((role) => {
        const detail = run && run.roles && Array.isArray(run.roles[department])
          ? run.roles[department].find((itemRole) => itemRole.id === role.id) : null;
        const resolvedRole = detail ? models().resolveRole(db, project.id, department, role.id) : null;
        return Object.assign({}, role, {
          model: detail ? detail.model : null,
          resolved: resolvedRole,
          predictive: Boolean(detail && detail.predictive)
        });
      });
      out.ledger = run && run.ledger && run.ledger[department] ? run.ledger[department] : { items: [], facts: [], questions: [], progress: [] };
    }
    const live = deptAttempts.find((attempt) => LIVE.includes(attempt.status));
    if (live) out.live_attempt = live.id;
    return out;
  });

  B.query('run.actions', (params, db) => {
    const item = db.workItem(requireText(params.work_item, '事项'));
    if (!item) throw new Error('事项不存在：' + params.work_item);
    const run = db.runOf(item.id);
    if (!run) return { work_item: item.id, run_id: null, actions: [] };
    const department = params.department || null;
    if (department) deptLabel(department);
    const actions = (run.actions || []).filter((action) => !department || action.department === department).map((action) => {
      const out = {
        id: action.id, department: action.department, tool: action.tool, summary: action.summary,
        input: action.input, receipt: action.receipt || null, at: action.at
      };
      if (db.atLeast('3.1')) {
        out.state = action.state || 'done';
        out.state_text = ACTION_TEXT[out.state] || out.state;
        out.before = action.before || null;
        out.after = action.after || null;
      }
      if (db.atLeast('3.2C')) {
        out.machine_id = action.machine_id || null;
        out.machine_name = machineName(db, action.machine_id);
      }
      if (db.atLeast('S5')) out.role = action.role || null;
      return out;
    });
    return { work_item: item.id, run_id: run.id, actions: actions };
  });

  B.query('attempt.live', (params, db) => {
    const found = findAttempt(db, requireText(params.attempt, '调用尝试'));
    if (!found) throw new Error('调用尝试不存在：' + params.attempt);
    const text = liveText(db, found);
    const finished = !LIVE.includes(found.attempt.status);
    return {
      attempt: found.attempt.id,
      run_id: found.run.id,
      department: found.attempt.department,
      status: found.attempt.status,
      status_text: ATTEMPT_TEXT[found.attempt.status] || found.attempt.status,
      finished: finished,
      text: text,
      chars: text.length
    };
  });

  B.query('role.detail', (params, db) => {
    const project = requireProjectQuery(db, requireText(params.project, '项目'));
    const department = requireText(params.department, '部门');
    deptLabel(department);
    const roleId = params.role || params.role_id;
    requireText(roleId, '角色');
    const catalog = db.data.catalog && db.data.catalog.role_catalog && db.data.catalog.role_catalog[department];
    if (!Array.isArray(catalog)) throw new Error('当前档位没有部门「' + department + '」的角色目录');
    const spec = catalog.find((role) => role.id === roleId);
    if (!spec) throw new Error('部门「' + department + '」没有角色：' + roleId);
    const runs = (db.data.runs || []).filter((run) => run.project_id === project.id && (!params.work_item || run.work_item_id === params.work_item));
    let live = null;
    runs.forEach((run) => {
      const list = run.roles && run.roles[department];
      if (!Array.isArray(list)) return;
      const found = list.find((role) => role.id === roleId);
      if (found) live = found;
    });
    const history = [];
    runs.forEach((run) => {
      (run.attempts || []).filter((attempt) => attempt.role === roleId).forEach((attempt) => {
        history.push(attemptOut(db, { attempt: attempt, run: run }));
      });
    });
    const steps = [];
    runs.forEach((run) => {
      const actions = (run.actions || []).filter((action) => action.role === roleId);
      if (actions.length) steps.push({ run_id: run.id, work_item_id: run.work_item_id, actions: actions });
    });
    const resolved = models().resolveRole(db, project.id, department, roleId);
    return {
      role: {
        id: spec.id, name: spec.name, kind: spec.kind, duty: spec.duty,
        status: live ? live.status : 'idle',
        task: live ? live.task : null,
        model: resolved,
        predictive: Boolean(live && live.predictive)
      },
      history: history,
      steps: steps,
      focus: live && live.focus ? live.focus : null,
      directory: live && live.directory ? live.directory : null,
      entities: live && live.entities ? live.entities : []
    };
  });

  B.query('overlay.context_usage', (params, db) => {
    const project = requireProjectQuery(db, requireText(params.project, '项目'));
    const entries = [];
    const pairs = attemptsOf(db, project.id).filter((pair) => pair.attempt.usage && pair.attempt.target && pair.attempt.target.window);
    const latest = {};
    pairs.forEach((pair) => {
      const key = pair.attempt.department + ':' + (pair.attempt.role || '');
      const prev = latest[key];
      if (!prev || Y10.time.ms(pair.attempt.started_at) > Y10.time.ms(prev.attempt.started_at)) latest[key] = pair;
    });
    Object.keys(latest).forEach((key) => {
      const pair = latest[key];
      const window = pair.attempt.target.window;
      if (!window) return;
      entries.push({
        department: pair.attempt.department,
        role: pair.attempt.role || (pair.attempt.department + '-agent'),
        ratio: Math.round((pair.attempt.usage.input || 0) / window * 1000) / 1000
      });
    });
    return { entries: entries };
  });

  B.query('semantic.records', (params, db) => {
    const project = requireProjectQuery(db, requireText(params.project, '项目'));
    if (params.department) deptLabel(params.department);
    return semanticOut(db, project.id, params.department || null);
  });

  B.query('ops.status', (params, db) => {
    const project = requireProjectQuery(db, requireText(params.project, '项目'));
    const ops = db.data.ops && db.data.ops[project.id];
    if (!ops) {
      const decisions = (db.data.decisions || []).filter((d) => d.project_id === project.id && d.status === 'waiting' && (
        OPS_KINDS.includes(d.kind) || (d.materials && d.materials.department === 'operations')
      )).map((d) => decisionCard(db, d));
      return { configured: false, env: null, releases: [], faults: [], backups: [], indicators: [], check_in: null, decisions: decisions };
    }
    const settings = db.settings(project.id);
    const envMachine = ops.env ? db.machine(ops.env.machine_id) : null;
    const standing = (settings && settings.machines || []).filter((item) => item.runtime_env).map((item) => ({
      machine_id: item.machine_id,
      machine_name: machineName(db, item.machine_id),
      standing: item.standing || []
    }));
    const faults = (ops.faults || []).map((fault) => ({
      id: fault.id,
      title: fault.title,
      status: fault.status,
      repair_work_item_ids: fault.repair_work_item_ids || [],
      repairs: (fault.repair_work_item_ids || []).map((id) => {
        const item = db.workItem(id);
        return { work_item_id: id, title: item ? item.title : id };
      }),
      failures: fault.failures || 0,
      observe_until: fault.observe_until || null,
      observe_remaining_sec: fault.observe_until ? Math.max(0, Y10.time.between(db.now, fault.observe_until)) : null
    }));
    const backups = (ops.backups || []).slice().sort((a, b) => Y10.time.ms(b.at) - Y10.time.ms(a.at)).slice(0, 3);
    const decisions = (db.data.decisions || []).filter((d) => d.project_id === project.id && d.status === 'waiting' && (
      OPS_KINDS.includes(d.kind) || (d.materials && d.materials.department === 'operations')
    )).map((d) => decisionCard(db, d));
    return {
      env: ops.env ? {
        machine_id: ops.env.machine_id,
        machine_name: envMachine ? envMachine.name : ops.env.machine_id,
        version: ops.env.version,
        standing: standing
      } : null,
      releases: ops.releases || [],
      faults: faults,
      backups: backups,
      indicators: ops.indicators || [],
      check_in: ops.check_in || null,
      decisions: decisions
    };
  });

  B.query('project.attempts', (params, db) => {
    const project = requireProjectQuery(db, requireText(params.project, '项目'));
    if (params.role && !db.atLeast('S5')) throw new Error('当前档位不能按角色筛选');
    let rows = attemptsOf(db, project.id);
    if (params.work_item) rows = rows.filter((pair) => pair.run.work_item_id === params.work_item);
    if (params.department) rows = rows.filter((pair) => pair.attempt.department === params.department);
    if (params.role) rows = rows.filter((pair) => pair.attempt.role === params.role);
    if (params.status) rows = rows.filter((pair) => pair.attempt.status === params.status);
    if (params.provider) rows = rows.filter((pair) => pair.attempt.provider === params.provider);
    if (params.model) rows = rows.filter((pair) => pair.attempt.requested_model === params.model || pair.attempt.actual_model === params.model);
    if (params.text) {
      const text = String(params.text);
      rows = rows.filter((pair) => JSON.stringify(pair.attempt).indexOf(text) >= 0);
    }
    rows.sort((a, b) => Y10.time.ms(b.attempt.started_at) - Y10.time.ms(a.attempt.started_at));
    const offset = params.cursor ? Number(params.cursor) : 0;
    if (!Number.isFinite(offset) || offset < 0) throw new Error('cursor 无效');
    const pageSize = params.limit ? Math.min(200, Math.max(1, Number(params.limit))) : PAGE;
    if (!Number.isFinite(pageSize)) throw new Error('limit 无效');
    const page = rows.slice(offset, offset + pageSize).map((pair) => attemptOut(db, pair));
    return {
      total: rows.length,
      attempts: page,
      next_cursor: offset + pageSize < rows.length ? String(offset + pageSize) : null
    };
  });

  B.query('project.usage', (params, db) => {
    const project = requireProjectQuery(db, requireText(params.project, '项目'));
    let rows = attemptsOf(db, project.id);
    if (params.work_item) rows = rows.filter((pair) => pair.run.work_item_id === params.work_item);
    if (params.department) rows = rows.filter((pair) => pair.attempt.department === params.department);
    const groups = {};
    rows.forEach((pair) => {
      const key = pair.attempt.department || '—';
      if (!groups[key]) groups[key] = { department: key, attempts: 0, input: 0, output: 0, cache_read: 0, total: 0, cost: null, cost_known: true };
      const group = groups[key];
      const usage = pair.attempt.usage || {};
      group.attempts += 1;
      group.input += usage.input || 0;
      group.output += usage.output || 0;
      group.cache_read += usage.cache_read || 0;
      group.total += usage.total || 0;
      if (usage.cost === null || usage.cost === undefined) group.cost_known = false;
      else group.cost = (group.cost || 0) + usage.cost;
    });
    const list = Object.keys(groups).map((key) => {
      const group = groups[key];
      if (!group.cost_known) group.cost = null;
      delete group.cost_known;
      return group;
    });
    const totals = list.reduce((sum, group) => {
      sum.attempts += group.attempts;
      sum.input += group.input;
      sum.output += group.output;
      sum.cache_read += group.cache_read;
      sum.total += group.total;
      if (group.cost === null) sum.cost = null;
      else if (sum.cost !== null) sum.cost += group.cost;
      return sum;
    }, { attempts: 0, input: 0, output: 0, cache_read: 0, total: 0, cost: list.length ? 0 : null });
    const limits = (db.data.runs || []).filter((run) => run.project_id === project.id)
      .filter((run) => !params.work_item || run.work_item_id === params.work_item)
      .map((run) => {
        const item = db.workItem(run.work_item_id);
        const row = {
          run_id: run.id,
          work_item_id: run.work_item_id,
          title: item ? item.title : run.work_item_id,
          phase: run.phase,
          cycle: run.cycle,
          elapsed_sec: run.elapsed_sec,
          limit_sec: run.limit_sec
        };
        if (db.atLeast('S4')) row.waiting_provider_sec = run.waiting_provider_sec || 0;
        return row;
      });
    return { groups: list, totals: totals, limits: limits };
  });

  B.query('run.attempt', (params, db) => {
    const found = findAttempt(db, requireText(params.attempt, '调用尝试'));
    if (!found) throw new Error('调用尝试不存在：' + params.attempt);
    const out = attemptOut(db, found);
    out.sections = sectionsOf(found.run, found.attempt);
    out.limits = {
      elapsed_sec: found.run.elapsed_sec,
      limit_sec: found.run.limit_sec,
      cycle: found.run.cycle,
      waiting_provider_sec: db.atLeast('S4') ? found.run.waiting_provider_sec || 0 : undefined
    };
    if (!db.atLeast('S4')) delete out.limits.waiting_provider_sec;
    out.output = found.attempt.output || null;
    out.input = found.attempt.input || null;
    const siblings = (found.run.attempts || []).filter((item) => item.department === found.attempt.department).map((item) => ({
      id: item.id, n: item.n, of: item.of, status: item.status, status_text: ATTEMPT_TEXT[item.status] || item.status, started_at: item.started_at
    }));
    out.siblings = siblings;
    if (db.atLeast('S5')) out.semantic_view = found.attempt.semantic_units || [];
    return out;
  });

  B.query('project.settings', (params, db) => {
    const project = requireProjectQuery(db, requireText(params.project, '项目'));
    const settings = db.settings(project.id);
    if (!settings) throw new Error('项目设置不存在：' + project.id);
    const departments = ['product', 'engineering', 'quality'].concat(db.atLeast('S4') ? ['operations'] : []);
    const deptOut = {};
    const warnings = [];
    departments.forEach((department) => {
      const entry = deptEntry(settings, department);
      const resolved = models().resolve(db, project.id, department);
      deptOut[department] = {
        version: entry && typeof entry.version === 'number' ? entry.version : 0,
        model: entry ? entry.model || null : null,
        request_level: requestLevel(entry),
        prompt_version: entry ? entry.prompt_version || 0 : 0,
        prompt_text: entry ? entry.prompt_text || null : null,
        resolved: {
          definition: resolved.definition,
          label: resolved.definition ? models().label(resolved.definition) : '未设置',
          source: resolved.source,
          request_level: resolved.request_level,
          sent_level: resolved.sent_level,
          problem: resolved.problem
        }
      };
      if (db.atLeast('3.2D') && department === 'quality') {
        const warning = imageWarning(resolved);
        if (warning) warnings.push(warning);
      }
    });
    const out = {
      project: { id: project.id, name: project.name, goal: project.goal, pinned: Boolean(project.pinned), archived: Boolean(project.archived), version: project.version },
      version: settings.version,
      departments: deptOut,
      commands: (settings.commands || []).map((command) => ({
        name: command.name, argv: command.argv, args: command.args || [], timeout_sec: command.timeout_sec,
        output_limit: command.output_limit, version: command.version
      })),
      source_directories: {
        version: settings.source_directories && typeof settings.source_directories.version === 'number' ? settings.source_directories.version : 0,
        items: settings.source_directories && settings.source_directories.items ? settings.source_directories.items : []
      }
    };
    if (db.atLeast('3.2B')) {
      out.tools = (settings.tools || []).map((tool) => ({ id: tool.id, label: tool.label, scope: tool.scope, approval: tool.approval }));
      out.tools_version = typeof settings.tools_version === 'number' ? settings.tools_version : 0;
    }
    if (db.atLeast('3.2C')) {
      out.machines = (settings.machines || []).map((item) => {
        const row = {
          machine_id: item.machine_id,
          machine_name: machineName(db, item.machine_id),
          dirs: item.dirs || [],
          operations: item.operations || []
        };
        if (db.atLeast('S4')) {
          row.runtime_env = Boolean(item.runtime_env);
          row.standing = item.standing || [];
        }
        return row;
      });
      out.machines_version = typeof settings.machines_version === 'number' ? settings.machines_version : 0;
      const place = settings.execution_placement;
      out.execution_placement = {
        version: place && typeof place.version === 'number' ? place.version : 0,
        workspace: place && place.workspace ? place.workspace : LOCAL_PROCESS,
        checks: place && place.checks ? place.checks : { product: null, engineering: null, quality: null },
        image: place ? place.image || null : null
      };
    }
    if (db.atLeast('3.2D')) out.warnings = warnings;
    if (db.atLeast('S4')) {
      out.ops = settings.ops ? { observe_hours: settings.ops.observe_hours, max_repair_failures: settings.ops.max_repair_failures } : { observe_hours: 24, max_repair_failures: 2 };
    }
    if (db.atLeast('S5')) {
      const roles = {};
      const catalogRoles = db.data.catalog && db.data.catalog.role_catalog ? db.data.catalog.role_catalog : {};
      departments.forEach((department) => {
        const list = settings.roles && Array.isArray(settings.roles[department]) ? settings.roles[department] : [];
        const specs = Array.isArray(catalogRoles[department]) ? catalogRoles[department] : [];
        roles[department] = list.map((role) => {
          const spec = specs.find((item) => item.id === role.role_id);
          return {
            role_id: role.role_id,
            name: spec ? spec.name : role.role_id,
            duty: spec ? spec.duty : null,
            model: role.model || null,
            request_level: requestLevel(role),
            prompt_text: role.prompt_text || null
          };
        });
      });
      out.roles = roles;
      out.roles_version = typeof settings.roles_version === 'number' ? settings.roles_version : 0;
    }
    return out;
  });

  // ---------------------------------------------------------------------------
  // 命令

  B.command('guidance.send', (params, db) => {
    const item = db.workItem(requireText(params.work_item, '事项'));
    if (!item) return reject('not_found', '事项不存在');
    const department = requireText(params.department, '部门');
    deptLabel(department);
    const run = db.runOf(item.id);
    if (!run) return reject('not_found', '事项没有 run');
    if (TERMINAL.includes(run.phase)) return reject('run_terminal', '事项已结束，不能再发送指导');
    const text = requireText(params.text, '指导原文').trim();
    const version = (run.guidance || []).filter((entry) => entry.department === department).length + 1;
    const id = Y10.uid('g');
    const record = { id: id, department: department, version: version, text: text, status: 'received', response: null, at: db.now };
    const message = {
      seq: ((run.messages && run.messages[department]) || []).reduce((max, entry) => Math.max(max, entry.seq || 0), 0) + 1,
      at: db.now, source: 'user', from: 'user', text: '指导 v' + version + '：' + text, event_id: null
    };
    return accepted([event('department_guidance_received', {
      project_id: item.project_id, work_item_id: item.id, run_id: run.id, department: department,
      label: '门缝塞进纸条，信箱灯亮：指导 v' + version + ' 已接收',
      payload: { guidance_id: id, version: version }
    }, [
      { path: 'runs[id=' + run.id + '].guidance', push: record },
      { path: 'runs[id=' + run.id + '].messages.' + department, push: message }
    ])], { guidance_id: id, version: version });
  });

  function deptSettingsPatch(db, projectId, department, next) {
    const raw = settingsRaw(db, projectId);
    if (!raw.departments || !keyExists(raw.departments, department)) {
      return [{ path: 'project_settings.' + projectId + '.departments', put: { key: department, value: next } }];
    }
    return [{ path: 'project_settings.' + projectId + '.departments.' + department, value: next }];
  }

  function modelPreview(db, definitionId, fallback) {
    if (!definitionId) return fallback;
    const catalog = db.data.catalog || {};
    const def = (catalog.definitions || []).find((item) => item.id === definitionId);
    const conn = def ? (catalog.connections || []).find((item) => item.id === def.connection_id) : null;
    return {
      definition: definitionId,
      model: def ? def.upstream_model : definitionId,
      connection: conn ? conn.id : null,
      protocol: conn ? (PROTOCOL_LABELS[conn.protocol] || conn.protocol) : null,
      image_input: def ? Boolean(def.image_input) : null
    };
  }

  B.command('department_settings.save', (params, db) => {
    const project = projectOf(db, requireText(params.project, '项目'));
    if (!project) return reject('not_found', '项目不存在');
    const denied = archived(project);
    if (denied) return denied;
    const department = requireText(params.department, '部门');
    deptLabel(department);
    const settings = db.settings(project.id);
    if (!settings) return reject('not_found', '项目设置不存在');
    const entry = deptEntry(settings, department);
    const current = entry && typeof entry.version === 'number' ? entry.version : 0;
    if (versionParam(params) !== current) return stale(current);
    const promptText = params.prompt_text ? String(params.prompt_text) : null;
    const samePrompt = Boolean(entry && entry.prompt_text === promptText);
    const next = {
      version: current === 0 ? 1 : current + 1,
      model: params.model || null,
      request_level: params.request_level || null,
      level: params.request_level || null,
      prompt_version: promptText ? ((entry && entry.prompt_version) || 0) + (samePrompt ? 0 : 1) : null,
      prompt_text: promptText
    };
    const resolved = models().resolve(db, project.id, department);
    const preview = modelPreview(db, next.model, resolved);
    const warning = db.atLeast('3.2D') && department === 'quality' ? imageWarning(preview) : null;
    return accepted([event('x_department_settings_saved', {
      project_id: project.id, department: department,
      label: '保存' + deptLabel(department) + '部门设置',
      payload: { department: department, warning: warning }
    }, deptSettingsPatch(db, project.id, department, next))], { warning: warning });
  });

  B.command('command_registration.save', (params, db) => {
    const project = projectOf(db, requireText(params.project, '项目'));
    if (!project) return reject('not_found', '项目不存在');
    const denied = archived(project);
    if (denied) return denied;
    const name = requireText(params.name, '登记名').trim();
    const settings = db.settings(project.id);
    if (!settings) return reject('not_found', '项目设置不存在');
    const commands = settings.commands || [];
    const existing = commands.find((command) => command.name === name);
    const current = existing ? existing.version : 0;
    if (versionParam(params) !== current) return stale(current);
    const next = {
      name: name,
      argv: Array.isArray(params.argv) ? params.argv : String(params.argv || ''),
      args: listParam(params.args),
      timeout_sec: numOrNull(params.timeout_sec) || 60,
      output_limit: numOrNull(params.output_limit) || 200000,
      version: current === 0 ? 1 : current
    };
    const path = 'project_settings.' + project.id + '.commands';
    const patch = existing
      ? [{ path: path + '[name=' + name + ']', value: next }]
      : [{ path: path, push: next }];
    return accepted([event('command_configured', {
      project_id: project.id,
      label: (existing ? '修改' : '登记') + '命令 ' + name,
      payload: { name: name }
    }, patch)]);
  });

  B.command('source_directory.save', (params, db) => {
    const project = projectOf(db, requireText(params.project, '项目'));
    if (!project) return reject('not_found', '项目不存在');
    const denied = archived(project);
    if (denied) return denied;
    const name = requireText(params.name, '源目录名称').trim();
    const dirPath = requireText(params.path, '源目录路径').trim();
    const raw = settingsRaw(db, project.id);
    const store = raw.source_directories;
    const current = store && typeof store.version === 'number' ? store.version : 0;
    if (versionParam(params) !== current) return stale(current);
    const items = (store && store.items ? store.items.slice() : []).filter((item) => item.name !== name);
    items.push({ name: name, path: dirPath });
    const next = { version: current === 0 ? 1 : current, items: items };
    const base = 'project_settings.' + project.id;
    const patch = store
      ? [{ path: base + '.source_directories', value: next }]
      : [{ path: base, put: { key: 'source_directories', value: next } }];
    return accepted([event('x_source_directory_saved', {
      project_id: project.id,
      label: '登记源目录 ' + name,
      payload: { name: name, path: dirPath }
    }, patch)]);
  });

  B.command('tool_authorization.save', (params, db) => {
    const project = projectOf(db, requireText(params.project, '项目'));
    if (!project) return reject('not_found', '项目不存在');
    const denied = archived(project);
    if (denied) return denied;
    const raw = settingsRaw(db, project.id);
    const current = typeof raw.tools_version === 'number' ? raw.tools_version : 0;
    if (versionParam(params) !== current) return stale(current);
    const tools = (raw.tools || []).map((tool) => Object.assign({}, tool));
    const incoming = Array.isArray(params.tools) ? params.tools : [{ id: params.id, label: params.label, scope: params.scope, approval: params.approval }];
    incoming.forEach((item) => {
      const id = requireText(item.id, '工具');
      const prev = tools.find((tool) => tool.id === id);
      const next = {
        id: id,
        label: item.label || (prev ? prev.label : id),
        scope: item.scope || '',
        approval: item.approval || ''
      };
      if (prev && prev.level) next.level = prev.level;
      const index = tools.findIndex((tool) => tool.id === id);
      if (index >= 0) tools[index] = next;
      else tools.push(next);
    });
    const base = 'project_settings.' + project.id;
    const patch = [
      versionKeyPatch(project.id, 'tools_version', current, keyExists(raw, 'tools_version')),
      { path: base + '.tools', value: tools }
    ];
    return accepted([event('x_tool_authorization_saved', {
      project_id: project.id,
      label: '保存工具授权',
      payload: { ids: incoming.map((item) => item.id) }
    }, patch)]);
  });

  B.command('machine_authorization.save', (params, db) => {
    const project = projectOf(db, requireText(params.project, '项目'));
    if (!project) return reject('not_found', '项目不存在');
    const denied = archived(project);
    if (denied) return denied;
    const raw = settingsRaw(db, project.id);
    const current = typeof raw.machines_version === 'number' ? raw.machines_version : 0;
    if (versionParam(params) !== current) return stale(current);
    const incoming = listParam(params.machines);
    if (!incoming.length) return reject('not_found', '机器授权不能为空');
    if (!db.atLeast('S4') && incoming.some((item) => item && (keyExists(item, 'runtime_env') || keyExists(item, 'standing')))) {
      return reject('not_allowed', 'S4 之前不接受运行环境与常设授权');
    }
    const place = raw.execution_placement;
    const next = incoming.map((item) => {
      const id = requireText(item.machine_id, '机器');
      if (!db.machine(id) && !(db.raw.machines || []).some((machine) => machine.id === id)) return reject('not_found', '机器不存在：' + id);
      const prev = (raw.machines || []).find((entry) => entry.machine_id === id) || {};
      const row = {
        machine_id: id,
        dirs: listParam(item.dirs),
        operations: listParam(item.operations)
      };
      if (prev.level) row.level = prev.level;
      if (db.atLeast('S4')) {
        row.runtime_env = Boolean(item.runtime_env);
        row.standing = listParam(item.standing);
      } else {
        if (keyExists(prev, 'runtime_env')) row.runtime_env = prev.runtime_env;
        if (keyExists(prev, 'standing')) row.standing = prev.standing;
      }
      return row;
    });
    if (next.some((item) => item && item.reject)) return next.find((item) => item && item.reject);
    if (place) {
      const needed = [];
      if (place.workspace && place.workspace !== LOCAL_PROCESS && place.workspace !== LOCAL_CONTAINER) needed.push({ id: place.workspace, kind: 'workspace' });
      ['product', 'engineering', 'quality'].forEach((department) => {
        const location = place.checks && place.checks[department];
        if (location && location !== LOCAL_PROCESS && location !== LOCAL_CONTAINER) needed.push({ id: location, kind: 'check' });
      });
      for (const entry of needed) {
        const kept = next.find((item) => item.machine_id === entry.id);
        if (!kept) return reject('not_allowed', '执行位置「' + entry.id + '」仍在使用这台机器，不能取消授权');
        if (entry.kind === 'workspace' && (!kept.dirs.length || !kept.operations.length)) {
          return reject('not_allowed', '执行位置「' + entry.id + '」需要登记的目录与可以执行的操作，授权不能减少到这些以下');
        }
        if (entry.kind === 'check' && !kept.operations.length) {
          return reject('not_allowed', '执行位置「' + entry.id + '」需要可以执行的操作，授权不能减少到这些以下');
        }
      }
    }
    const patch = [
      versionKeyPatch(project.id, 'machines_version', current, keyExists(raw, 'machines_version')),
      { path: 'project_settings.' + project.id + '.machines', value: next }
    ];
    return accepted([event('x_machine_authorization_saved', {
      project_id: project.id,
      label: '保存机器授权',
      payload: { machine_ids: next.map((item) => item.machine_id) }
    }, patch)]);
  });

  function placementProblem(db, projectId, location, kind) {
    if (!location || location === LOCAL_PROCESS) return null;
    if (location === LOCAL_CONTAINER) {
      const host = (db.data.machines || []).find((machine) => machine.kind === 'host');
      if (!host || !host.online) return '控制主机的容器引擎不可用';
      return null;
    }
    const settings = db.settings(projectId);
    const auth = settings && (settings.machines || []).find((item) => item.machine_id === location);
    if (!auth) return '机器不在本项目的授权中：' + location;
    const dirs = auth.dirs || [];
    const operations = auth.operations || [];
    if (kind === 'workspace' && (!dirs.length || !operations.length)) return '运行工作区需要登记的目录，以及读取、写入与登记的命令';
    if (kind === 'check' && !operations.length) return '检查的位置需要可以执行的操作';
    return null;
  }

  B.command('execution_placement.save', (params, db) => {
    const project = projectOf(db, requireText(params.project, '项目'));
    if (!project) return reject('not_found', '项目不存在');
    const denied = archived(project);
    if (denied) return denied;
    const raw = settingsRaw(db, project.id);
    const place = raw.execution_placement;
    const current = place && typeof place.version === 'number' ? place.version : 0;
    if (versionParam(params) !== current) return stale(current);
    const checks = params.checks && typeof params.checks === 'object' ? params.checks : {};
    const next = {
      version: current === 0 ? 1 : current,
      level: '3.2C',
      workspace: params.workspace || LOCAL_PROCESS,
      checks: {
        product: checks.product || null,
        engineering: checks.engineering || null,
        quality: checks.quality || null
      },
      image: params.image || null
    };
    const problem = placementProblem(db, project.id, next.workspace, 'workspace')
      || placementProblem(db, project.id, next.checks.product, 'check')
      || placementProblem(db, project.id, next.checks.engineering, 'check')
      || placementProblem(db, project.id, next.checks.quality, 'check');
    if (problem) return reject('not_allowed', problem);
    const base = 'project_settings.' + project.id;
    const patch = place
      ? [{ path: base + '.execution_placement', value: next }]
      : [{ path: base, put: { key: 'execution_placement', value: next } }];
    return accepted([event('execution_placement_configured', {
      project_id: project.id,
      label: '保存执行位置',
      payload: { workspace: next.workspace }
    }, patch)]);
  });

  B.command('role_settings.save', (params, db) => {
    const project = projectOf(db, requireText(params.project, '项目'));
    if (!project) return reject('not_found', '项目不存在');
    const denied = archived(project);
    if (denied) return denied;
    const department = requireText(params.department, '部门');
    deptLabel(department);
    const raw = settingsRaw(db, project.id);
    const current = typeof raw.roles_version === 'number' ? raw.roles_version : 0;
    if (versionParam(params) !== current) return stale(current);
    const incoming = listParam(params.roles);
    if (!raw.roles || !Array.isArray(raw.roles[department])) return reject('not_found', '部门没有角色设置：' + department);
    const roles = raw.roles[department].map((role) => Object.assign({}, role));
    incoming.forEach((item) => {
      const id = requireText(item.role_id, '角色');
      const index = roles.findIndex((role) => role.role_id === id);
      if (index < 0) throw new Error('部门「' + department + '」没有角色：' + id);
      const next = Object.assign({}, roles[index], {
        model: item.model || null,
        request_level: item.request_level || null,
        prompt_text: item.prompt_text || null
      });
      if (keyExists(roles[index], 'level')) next.level = item.request_level || null;
      roles[index] = next;
    });
    const warning = db.atLeast('3.2D') && department === 'quality'
      ? imageWarning(models().resolve(db, project.id, department))
      : null;
    const patch = [
      versionKeyPatch(project.id, 'roles_version', current, keyExists(raw, 'roles_version')),
      { path: 'project_settings.' + project.id + '.roles.' + department, value: roles }
    ];
    return accepted([event('x_role_settings_saved', {
      project_id: project.id, department: department,
      label: '保存' + deptLabel(department) + '的角色设置',
      payload: { department: department, warning: warning }
    }, patch)], { warning: warning });
  });

  function semanticPatch(db, projectId, next) {
    const top = db.raw.semantic && db.raw.semantic[projectId];
    if (top) return [{ path: 'semantic.' + projectId, value: next }];
    const raw = settingsRaw(db, projectId);
    if (raw.semantic) return [{ path: 'project_settings.' + projectId + '.semantic', value: next }];
    return [{ path: 'project_settings.' + projectId, put: { key: 'semantic', value: next } }];
  }

  function loadSemantic(db, projectId) {
    const top = db.raw.semantic && db.raw.semantic[projectId];
    if (top) return Y10.clone(top);
    const raw = settingsRaw(db, projectId);
    if (raw.semantic) return Y10.clone(raw.semantic);
    return null;
  }

  B.command('semantic.mark_invalid', (params, db) => {
    const project = projectOf(db, requireText(params.project, '项目'));
    if (!project) return reject('not_found', '项目不存在');
    const denied = archived(project);
    if (denied) return denied;
    const unitId = requireText(params.unit || params.unit_id, '语义单元');
    const store = loadSemantic(db, project.id);
    if (!store || !Array.isArray(store.units)) return reject('not_found', '没有语义记录');
    const current = typeof store.version === 'number' ? store.version : 0;
    if (versionParam(params) !== current) return stale(current);
    const unit = store.units.find((item) => item.id === unitId);
    if (!unit) return reject('not_found', '语义单元不存在：' + unitId);
    unit.status = 'invalid';
    unit.reason = requireText(params.reason, '理由');
    store.version = current === 0 ? 1 : current + 1;
    return accepted([event('x_semantic_recorded', {
      project_id: project.id, department: unit.department || params.department || null,
      label: '把语义单元 ' + unitId + ' 标记失效',
      payload: { unit_id: unitId }
    }, semanticPatch(db, project.id, store))]);
  });

  B.command('semantic.correct', (params, db) => {
    const project = projectOf(db, requireText(params.project, '项目'));
    if (!project) return reject('not_found', '项目不存在');
    const denied = archived(project);
    if (denied) return denied;
    const department = params.department ? requireText(params.department, '部门') : null;
    if (department) deptLabel(department);
    const text = requireText(params.text, '更正文字');
    const reason = requireText(params.reason, '理由');
    const store = loadSemantic(db, project.id) || { version: 0, level: 'S5', units: [], conflicts: [] };
    const current = typeof store.version === 'number' ? store.version : 0;
    if (versionParam(params) !== current) return stale(current);
    const unitId = params.unit || params.unit_id || null;
    const id = Y10.uid('su');
    if (unitId) {
      const prev = (store.units || []).find((item) => item.id === unitId);
      if (!prev) return reject('not_found', '语义单元不存在：' + unitId);
      prev.status = 'superseded';
      prev.superseded_by = id;
      prev.reason = reason;
    }
    store.units = store.units || [];
    store.units.push({
      id: id, department: department, type: 'correction', text: text,
      status: 'valid', reason: reason, superseded_by: null, at: db.now
    });
    store.version = current === 0 ? 1 : current + 1;
    store.level = 'S5';
    return accepted([event('x_semantic_recorded', {
      project_id: project.id, department: department,
      label: '写入语义更正',
      payload: { unit_id: id, replaces: unitId }
    }, semanticPatch(db, project.id, store))], { unit_id: id });
  });

  // 3.2D：试用记录与截图证据（浏览器与 computer use 设计说明第 7、8 节）
  B.query('run.trials', (params, db) => {
    const item = db.workItem(requireText(params.work_item, '事项'));
    if (!item) throw new Error('事项不存在或不在当前档位：' + params.work_item);
    const run = db.runOf(item.id);
    const target = models().resolve(db, item.project_id, 'quality');
    return {
      work_item_id: item.id,
      run_id: run ? run.id : null,
      model: target.definition ? models().label(target.definition) : '未设置',
      image_input: target.image_input !== false,
      trials: run && run.trials ? run.trials.map((trial) => trialOut(trial, target)) : []
    };
  });

  B.query('evidence.screenshot', (params, db) => {
    const item = db.workItem(requireText(params.work_item, '事项'));
    if (!item) throw new Error('事项不存在或不在当前档位：' + params.work_item);
    const run = db.runOf(item.id);
    const step = Number(params.step);
    const trial = run && run.trials ? run.trials.find((entry) => entry.step === step) : null;
    if (!trial) throw new Error('试用记录中没有第 ' + params.step + ' 步');
    const out = trialOut(trial, models().resolve(db, item.project_id, 'quality'));
    return { step: out.step, at: out.at, action: out.action, screenshot: out.screenshot || null, width: 1280, height: 800, text_lines: out.text_lines || [], model_saw: out.model_saw, requirement: out.requirement || null };
  });
})();
