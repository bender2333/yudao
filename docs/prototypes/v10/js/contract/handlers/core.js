// 外壳、首页与画面使用的查询与命令：system.status、projects.list、decisions.list、home.away_report、project.loop、machines.list、
// event.detail；decision.answer、home.mark_seen
(function () {
  'use strict';
  const Y10 = window.Y10;
  const B = Y10.backend;
  if (!B) throw new Error('handlers/core.js 需要先加载 contract/backend.js');

  const TERMINAL_PHASES = ['DONE', 'PAUSED', 'FAILED'];

  // 决定选项需要的检查：由其他处理文件登记，例如 system.js 登记 model_ok
  B.checks = B.checks || {};

  function since(db, iso) {
    return Math.max(0, Y10.time.between(iso, db.now));
  }

  function requireProject(db, id) {
    const project = db.project(id);
    if (!project) throw new Error('项目不存在或不在当前档位：' + id);
    return project;
  }

  // ---------------------------------------------------------------------------
  // 事项在画面上的状态（BUILD.md 第 7.3 节）

  function sceneStatus(db, item, run) {
    const rec = run && run.recovery ? run.recovery.state : null;
    if (rec === 'interrupted' || rec === 'pending_verification' || rec === 'waiting_resume') return rec;
    if (run && run.waiting_provider) return 'waiting_provider';
    switch (item.status) {
      case 'queued':
        // 已经有 run、停下来等用户决定的事项在最后所在的房间等待；还没开始的事项在大厅排队
        if (item.queue_reason === 'decision' && run) return 'waiting_decision';
        return item.queue_reason === 'slot' ? 'waiting_slot' : 'queued';
      case 'in_progress': {
        const asking = (run.requests || []).some((r) => r.status === 'open' && r.from === run.department);
        return asking ? 'asking' : 'running';
      }
      case 'adopted': return 'adopted';
      case 'released': return 'done';
      case 'not_started': return null;
      case 'stopped': {
        const code = run && run.stop_reason ? run.stop_reason.code : null;
        if (code === 'cancelled') return 'cancelled';
        if (code === 'upgrade') return 'stopped_for_upgrade';
        if (run && run.phase === 'PAUSED') return 'paused';
        if (run && run.phase === 'DONE') return 'done';
        return 'failed';
      }
      default: throw new Error('未知事项状态：' + item.status);
    }
  }

  const SIGN = {
    interrupted: '中断', pending_verification: '待核实', waiting_provider: '等待模型服务', paused: '已暂停',
    done: '已完成', cancelled: '已取消', stopped_for_upgrade: '因升级停止'
  };

  function signOf(status, run, db, item) {
    if (status === 'waiting_decision') {
      const d = db && item ? (db.data.decisions || []).find((x) => x.status === 'waiting' && x.blocks && x.blocks.work_item_id === item.id) : null;
      return '待你决定' + (d ? '：' + Y10.registry.entry('decision', d.kind).label : '');
    }
    if (status === 'waiting_resume') {
      const u = run.recovery && run.recovery.unusable;
      return '待恢复' + (u && u.problem ? '：' + u.problem : '');
    }
    if (status === 'failed') return '失败' + (run && run.stop_reason ? '：' + (run.stop_reason.text || run.stop_reason.code) : '');
    return SIGN[status] || null;
  }

  function adoptions(project) {
    return Array.isArray(project.adoptions) ? project.adoptions : [];
  }

  // ---------------------------------------------------------------------------
  // 事实元素的来源（自举试点起，应用层与接口层设计说明第 5.8 节 H4）：给出这条事实的事件是最后一次改动对应字段的事件，
  // 字段在出现以后没有被改动过时是事项出现的事件；来源按「事件加字段」由登记表给出（已用时间这类测量值固定为主机测量）。
  // 每个来源写成 { position, field, source }，没有给出它的事件时为 null

  function lastTrace(db, paths) {
    const list = db.trace(paths);
    return list.length ? list[list.length - 1].position : null;
  }

  function refOf(db, position, field) {
    const ev = position ? db.event(position) : null;
    return ev ? { position, field, source: Y10.registry.sourceOf(ev, field) } : null;
  }

  function itemRefs(db, item, run, status) {
    const born = db.log({ work_item: item.id }).find((ev) => ['work_item_created', 'x_repair_created', 'run_created'].includes(ev.type));
    const first = born ? born.position : null;
    const or = (pos) => (pos === null ? first : pos);
    const w = 'work_items[id=' + item.id + ']';
    const r = run ? 'runs[id=' + run.id + ']' : null;
    const signPaths = [w + '.status', w + '.queue_reason'].concat(r ? [r + '.phase', r + '.stop_reason', r + '.recovery.state', r + '.waiting_provider'] : []);
    if (status === 'waiting_decision') {
      (db.data.decisions || []).filter((d) => d.blocks && d.blocks.work_item_id === item.id).forEach((d) => signPaths.push('decisions[id=' + d.id + '].status'));
    }
    return {
      round: refOf(db, r ? or(lastTrace(db, r + '.cycle')) : first, 'cycle'),
      time: refOf(db, r ? or(lastTrace(db, r + '.elapsed_sec')) : first, 'elapsed_sec'),
      // 门口的牌子与信息条上的状态：最后一次改动事项状态的事件
      sign: refOf(db, or(lastTrace(db, signPaths)), 'status'),
      // 信息条上的当前部门：把 run 交到这个部门的事件
      department: refOf(db, r ? or(lastTrace(db, r + '.department')) : first, 'department'),
      // 停放的包裹：大厅队列里的包裹与部门门口的小旗，来源是把事项放到这里的事件
      parcel: refOf(db, or(lastTrace(db, [w + '.status', w + '.queue_pos'].concat(r ? [r + '.department'] : []))), 'location')
    };
  }

  function loopOf(db, projectId) {
    requireProject(db, projectId);
    const withRefs = db.atLeast('pilot');
    const items = db.workItemsOf(projectId).map((item) => {
      const run = item.run_id ? db.run(item.run_id) : null;
      const status = sceneStatus(db, item, run);
      if (!status) return null;
      const out = {
        id: item.id, title: item.title, color_index: item.color_index, kind: item.kind || 'request', status,
        department: run ? (run.department || run.last_department || null) : null,
        cycle: run ? run.cycle : 0,
        elapsed_sec: run ? run.elapsed_sec : 0,
        limit_sec: run ? run.limit_sec : 7200,
        sign: run ? signOf(status, run, db, item) : null,
        recovery_state: run && run.recovery ? run.recovery.state : null
      };
      if (db.atLeast('3.4A')) out.queue_pos = status === 'waiting_decision' ? null : item.queue_pos || null;
      if (db.atLeast('S4')) out.waiting_provider_sec = run ? run.waiting_provider_sec || 0 : 0;
      if (withRefs) out.refs = itemRefs(db, item, run, status);
      return out;
    }).filter(Boolean);
    const runs = db.workItemsOf(projectId).map((item) => (item.run_id ? db.run(item.run_id) : null)).filter(Boolean);
    const openRequests = [];
    runs.forEach((run) => (run.requests || []).forEach((r) => {
      if (r.status === 'open') openRequests.push({ from: r.from, to: r.to, work_item_id: run.work_item_id, request_id: r.id, since: r.born_at || null, question: r.question || null });
    }));
    const project = db.project(projectId);
    const out = {
      project_id: projectId,
      items,
      open_requests: openRequests,
      shelves: { adopted: adoptions(project).map((a) => a.version) },
      interrupted: items.some((it) => it.status === 'interrupted')
    };
    if (withRefs) {
      // 成果库的箱子：采纳这个版本的事件；质检的盖章：本项目最近一次放行
      const adopted = db.log({ project: projectId, types: ['deliverable_adopted', 'baseline_adopted'] });
      out.shelves.boxes = adoptions(project).map((a) => {
        const ev = adopted.filter((e) => e.payload && e.payload.version === a.version).pop();
        return { version: a.version, ref: ev ? refOf(db, ev.position, 'adoption') : null };
      });
      const release = db.log({ project: projectId, types: ['qa_submitted'] }).filter((e) => e.payload.verdict === 'release').pop();
      out.stamp = release ? { work_item_id: release.work_item_id, ref: refOf(db, release.position, 'verdict') } : null;
    }
    if (db.atLeast('3.4A') && db.data.runtime) {
      out.slots = { total: db.data.runtime.slots.total, used: db.data.runtime.slots.used.length };
    }
    if (db.atLeast('S4')) {
      out.waiting_provider = runs.filter((run) => run.waiting_provider).map((run) => ({
        department: run.waiting_provider.department, next_retry_at: run.waiting_provider.next_retry_at, work_item_id: run.work_item_id
      }));
      const ops = db.data.ops && db.data.ops[projectId];
      out.ops = ops ? {
        version: ops.env ? ops.env.version : null,
        machine_id: ops.env ? ops.env.machine_id : null,
        fault: (ops.faults || []).some((f) => f.status === 'open' || f.status === 'repairing'),
        auto_repair_stopped: (ops.faults || []).some((f) => f.status === 'repair_stopped')
      } : null;
    }
    if (db.atLeast('3.2C')) {
      const settings = db.settings(projectId);
      const auth = settings && settings.machines ? settings.machines : [];
      out.machines = auth.map((a) => {
        const m = db.machine(a.machine_id);
        if (!m) return null;
        const acts = (m.actions || []).filter((act) => act.project_id === projectId);
        return {
          id: m.id, name: m.name, online: m.online, actions: acts.length,
          unknown: acts.some((act) => act.state === 'unknown')
        };
      }).filter(Boolean);
    }
    return out;
  }

  // 项目的状态标记（左侧栏、楼层的状态灯）
  const MARKER_ORDER = [
    ['waiting_resume', 'waiting', '待恢复'], ['pending_verification', 'pending', '待核实'], ['interrupted', 'interrupted', '中断'],
    ['waiting_decision', 'waiting', '等待你的决定'],
    ['waiting_provider', 'waiting_provider', '等待模型服务'], ['waiting_slot', 'waiting_slot', '等待执行槽位'],
    ['running', 'running', '运行中'], ['asking', 'running', '运行中'], ['queued', 'queued', '排队中']
  ];

  function markerOf(loop, project) {
    if (project.archived) return { kind: 'cancelled', status: 'archived', text: '已归档' };
    for (const [status, kind, text] of MARKER_ORDER) {
      if (loop.items.some((it) => it.status === status)) return { kind, status, text };
    }
    return { kind: 'idle', status: 'idle', text: '空闲' };
  }

  function waitingDecisions(db, filter) {
    return (db.data.decisions || []).filter((d) => d.status === 'waiting' && Y10.level.atLeast(Y10.registry.levelOf('decision', d.kind)) &&
      (!filter || !filter.project || d.project_id === filter.project));
  }

  // ---------------------------------------------------------------------------
  // 查询

  B.query('system.status', (params, db) => {
    const s = db.data.system;
    const runs = db.data.runs || [];
    const activeRuns = runs.filter((run) => {
      const item = db.workItem(run.work_item_id);
      return item && !['adopted', 'released'].includes(item.status);
    });
    const firstOf = (list) => (list.length ? { project_id: list[0].project_id, work_item_id: list[0].work_item_id } : null);
    const out = {
      now: db.now,
      deployment: Y10.clone(db.data.deployment),
      booted_at: s.booted_at,
      provider_ready: s.provider_ready,
      catalog_revision: s.catalog_revision,
      waiting_resume: activeRuns.filter((run) => run.recovery && run.recovery.state === 'waiting_resume').length,
      home_status: {}
    };
    if (db.atLeast('3.1')) {
      out.auto_resumed = s.auto_resumed;
      out.pending_verification = activeRuns.filter((run) => run.recovery && run.recovery.state === 'pending_verification').length;
      out.drain = s.drain;
      const unknown = [];
      activeRuns.forEach((run) => (run.actions || []).forEach((a) => {
        if (a.state === 'unknown') unknown.push({ project_id: run.project_id, work_item_id: run.work_item_id, action_id: a.id });
      }));
      out.home_status.unknown_actions = { count: unknown.length, first: firstOf(unknown) };
    }
    if (db.atLeast('3.2C')) {
      const offline = (db.data.machines || []).filter((m) => !m.online);
      out.home_status.offline_machines = { count: offline.length, first: offline.length ? offline[0].id : null };
    }
    if (db.atLeast('S4')) {
      const waiting = activeRuns.filter((run) => run.waiting_provider).map((run) => ({ project_id: run.project_id, work_item_id: run.work_item_id }));
      out.home_status.waiting_provider = { count: waiting.length, first: firstOf(waiting) };
      out.home_status.disk = { free_gb: s.disk.free_gb, threshold_gb: s.disk.threshold_gb, low: s.disk.free_gb < s.disk.threshold_gb };
      const repairing = [];
      Object.keys(db.data.ops || {}).forEach((pid) => (db.data.ops[pid].faults || []).forEach((f) => {
        if (f.status === 'repairing') repairing.push({ project_id: pid, work_item_id: (f.repair_work_item_ids || []).slice(-1)[0] || null, fault_id: f.id });
      }));
      out.home_status.repairing_faults = { count: repairing.length, first: firstOf(repairing) };
      out.check_in = s.check_in;
    }
    return out;
  });

  B.query('projects.list', (params, db) => {
    const list = (db.data.projects || []).map((project) => {
      const loop = loopOf(db, project.id);
      const items = db.workItemsOf(project.id);
      const out = {
        id: project.id, name: project.name, goal: project.goal, pinned: Boolean(project.pinned), archived: Boolean(project.archived),
        version: project.version, created_at: project.created_at, last_activity_at: project.last_activity_at,
        adoption: adoptions(project).slice(-1)[0] || null,
        active_count: items.filter((it) => it.status === 'in_progress').length,
        queued_count: items.filter((it) => it.status === 'queued').length,
        decisions_waiting: waitingDecisions(db, { project: project.id }).length,
        marker: markerOf(loop, project)
      };
      if (db.atLeast('3.8')) out.source = project.source || 'idea';
      return out;
    });
    return list.sort((a, b) => (Number(a.archived) - Number(b.archived)) || (Number(b.pinned) - Number(a.pinned)) ||
      (Y10.time.ms(b.last_activity_at) - Y10.time.ms(a.last_activity_at)));
  });

  function decisionOut(db, d) {
    const project = db.project(d.project_id);
    const item = d.work_item_id ? db.workItem(d.work_item_id) : null;
    const blocked = d.blocks && d.blocks.work_item_id ? db.workItem(d.blocks.work_item_id) : null;
    const out = Y10.clone(d);
    out.options = d.options.map((o) => ({ id: o.id, label: o.label, kind: o.kind || null, requires: o.requires || null, note_required: Boolean(o.note_required) }));
    out.kind_label = Y10.registry.entry('decision', d.kind).label;
    out.project_name = project ? project.name : d.project_id;
    out.work_item_title = item ? item.title : null;
    out.waited_sec = since(db, d.issued_at);
    if (out.blocks) out.blocks.work_item_title = blocked ? blocked.title : null;
    if (!db.atLeast('3.2C') && out.materials) delete out.materials.machine_id;
    return out;
  }

  B.query('decisions.list', (params, db) => {
    const statuses = params.status ? [].concat(params.status) : ['waiting'];
    return (db.data.decisions || [])
      .filter((d) => Y10.level.atLeast(Y10.registry.levelOf('decision', d.kind)))
      .filter((d) => statuses.includes(d.status))
      .filter((d) => !params.project || d.project_id === params.project)
      .filter((d) => !params.work_item || d.work_item_id === params.work_item)
      .filter((d) => !params.kind || d.kind === params.kind)
      .sort((a, b) => Y10.time.ms(a.issued_at) - Y10.time.ms(b.issued_at))
      .map((d) => decisionOut(db, d));
  });

  B.query('project.loop', (params, db) => loopOf(db, params.project));

  B.query('machines.list', (params, db) => {
    const projects = db.data.projects || [];
    return (db.data.machines || []).map((m) => {
      const authorized = projects.filter((p) => {
        const s = db.settings(p.id);
        return s && (s.machines || []).some((a) => a.machine_id === m.id);
      });
      const out = {
        id: m.id, name: m.name, address: m.address, purpose: m.purpose, kind: m.kind, version: m.version,
        online: m.online, last_heartbeat_at: m.last_heartbeat_at, containers: m.containers || 0,
        actions: (m.actions || []).map((a) => {
          const p = db.project(a.project_id);
          return Object.assign({}, a, { project_name: p ? p.name : a.project_id });
        }),
        late_receipts: m.late_receipts || [],
        authorized_projects: authorized.map((p) => ({ project_id: p.id, name: p.name }))
      };
      if (db.atLeast('S4')) {
        out.runtime_for = projects.filter((p) => {
          const ops = db.data.ops && db.data.ops[p.id];
          return ops && ops.env && ops.env.machine_id === m.id;
        }).map((p) => ({ project_id: p.id, name: p.name, version: db.data.ops[p.id].env.version }));
        out.fault = out.runtime_for.some((r) => (db.data.ops[r.project_id].faults || []).some((f) => f.status === 'open' || f.status === 'repairing'));
      }
      return out;
    });
  });

  B.query('event.detail', (params, db) => {
    const position = Number(params.position);
    const ev = db.log().find((item) => item.position === position);
    if (!ev) throw new Error('事件不存在或不在当前档位：' + params.position);
    const refs = [];
    const p = ev.payload || {};
    ['material_id', 'prd_material_id', 'structure_material_id'].forEach((key) => {
      if (p[key]) {
        const m = (db.data.materials || []).find((item) => item.id === p[key]);
        if (m) refs.push({ id: m.id, title: m.title, kind: m.kind, text: m.text });
      }
    });
    return { event: ev, artifacts: refs };
  });

  // 离开期间的报告：汇总与关键事实（应用层设计说明第 4.3 节）
  const RANGES = {
    since_seen: '自上次查看',
    '24h': '最近 24 小时',
    '7d': '最近 7 天'
  };

  B.query('home.away_report', (params, db) => {
    const range = params.range || 'since_seen';
    if (!RANGES[range]) throw new Error('报告范围无效：' + range);
    const home = db.data.home;
    let fromPosition;
    let fromAt;
    if (range === 'since_seen') {
      fromPosition = home.last_seen_position;
      fromAt = home.last_seen_at;
    } else {
      fromAt = Y10.time.add(db.now, range === '24h' ? -86400 : -7 * 86400);
      const earlier = db.log().filter((ev) => Y10.time.ms(ev.at) <= Y10.time.ms(fromAt));
      fromPosition = earlier.length ? earlier[earlier.length - 1].position : 0;
    }
    const events = db.log().filter((ev) => ev.position > fromPosition && (!params.project || ev.project_id === params.project));
    const facts = events.map((ev) => {
      const kind = Y10.registry.keyOf(ev);
      return kind ? { position: ev.position, at: ev.at, kind, project_id: ev.project_id, work_item_id: ev.work_item_id, label: ev.label, event: ev } : null;
    }).filter(Boolean);
    const summary = [];
    const add = (id, label, list, value, unit, extra) => {
      if (!list.length) return;
      summary.push(Object.assign({ id, label, value, unit, refs: list.map((ev) => ev.position) }, extra || {}));
    };
    const releasedEvents = events.filter((ev) => (ev.type === 'qa_submitted' && ev.payload.verdict === 'release') || ev.type === 'deliverable_adopted');
    const releasedItems = new Set(releasedEvents.map((ev) => ev.work_item_id));
    add('released', '完成与放行的事项', releasedEvents, releasedItems.size, '项');
    // 用量：范围内开始的调用尝试，来源为对应的模型请求事件
    let tokens = 0;
    let attempts = 0;
    (db.data.runs || []).forEach((run) => {
      if (params.project && run.project_id !== params.project) return;
      (run.attempts || []).forEach((a) => {
        if (Y10.time.ms(a.started_at) > Y10.time.ms(fromAt) && a.usage && typeof a.usage.total === 'number') {
          tokens += a.usage.total;
          attempts += 1;
        }
      });
    });
    if (attempts) summary.push({ id: 'usage', label: '用量', value: tokens, unit: 'token', detail: attempts + ' 次模型请求', refs: [] });
    if (db.atLeast('S4')) {
      add('faults', '发现的故障', events.filter((ev) => ev.type === 'x_fault_recorded'), events.filter((ev) => ev.type === 'x_fault_recorded').length, '次');
      const repairs = events.filter((ev) => ev.type === 'x_repair_created');
      add('repairs', '自动修复', repairs, repairs.length, '次');
      const deploys = events.filter((ev) => ev.type === 'x_deployed' || ev.type === 'x_rolled_back');
      add('deploys', '部署与回滚', deploys, deploys.length, '次');
      const waits = events.filter((ev) => ev.type === 'x_provider_wait_entered');
      add('provider_waits', '进入等待模型服务', waits, waits.length, '次');
      const checks = events.filter((ev) => ev.type === 'x_check_in');
      const s = db.data.system;
      add('health', '磁盘与报到', checks, s.disk.free_gb, 'GB 可用', { detail: s.check_in && s.check_in.ok ? '报到正常' : '报到中断' });
    }
    if (db.atLeast('pilot')) {
      // 收敛状态的变化：来源事件是引起变化的那一轮事件（handlers/project.js 的 B.loops）
      const changes = B.loops.changes(db, params.project || null, fromPosition);
      add('loop_changes', '收敛状态的变化', changes, changes.length, '条', { changes });
      // 带开环条件的放行：范围内的放行中带开环条件的（handlers/project.js 的 B.coverage）
      const releases = events.filter((ev) => ev.type === 'qa_submitted' && ev.payload.verdict === 'release')
        .map((ev) => B.coverage.openOfRelease(db, ev)).filter((r) => r && r.open.length);
      add('open_releases', '带开环条件的放行', releases, releases.length, '次', { releases });
    }
    return {
      last_seen: { at: home.last_seen_at, position: home.last_seen_position },
      range: { id: range, label: RANGES[range], from_at: fromAt, from_position: fromPosition, to_position: db.position, to_at: db.now },
      ranges: Object.keys(RANGES).map((id) => ({ id, label: RANGES[id] })),
      summary,
      facts
    };
  });

  // ---------------------------------------------------------------------------
  // 命令

  function reject(reason, message, extra) {
    return { reject: Object.assign({ reason, message }, extra || {}) };
  }

  B.command('decision.answer', (params, db) => {
    const raw = (db.raw.decisions || []).find((d) => d.id === params.decision_id);
    if (!raw) return reject('not_found', '决定请求不存在');
    if (raw.status !== 'waiting') return reject('decision_closed', '这个决定请求已经' + (raw.status === 'answered' ? '回答' : '撤销'));
    if (params.base_version !== undefined && params.base_version !== null && params.base_version !== '' && Number(params.base_version) !== raw.version) {
      return reject('stale_base', '决定请求已经变化，请刷新后再回答', { current_version: raw.version });
    }
    const option = raw.options.find((o) => o.id === params.option);
    if (!option) return reject('option_invalid', '没有这个选项：' + params.option);
    if (option.requires) {
      const check = B.checks[option.requires];
      if (!check) throw new Error('决定选项需要的检查没有登记：' + option.requires);
      const problem = check(db, raw);
      if (problem) return reject('option_invalid', problem);
    }
    const note = (params.note || '').trim();
    if (option.note_required && !note) return reject('not_allowed', '「' + option.label + '」需要写明说明');
    const path = 'decisions[id=' + raw.id + ']';
    const projectStream = Y10.registry.entry('decision', raw.kind).stream === 'project';
    const answered = {
      type: projectStream ? 'project_decision_answered' : 'x_decision_answered', project_id: raw.project_id, work_item_id: raw.work_item_id, run_id: raw.run_id,
      label: '用户回答「' + Y10.registry.entry('decision', raw.kind).label + '」：' + option.label,
      payload: { decision_id: raw.id, kind: raw.kind, option: option.id },
      patch: [
        { path: path + '.status', value: 'answered' },
        { path: path + '.answer', value: { option: option.id, label: option.label, note, at: db.now } }
      ]
    };
    return { events: [answered].concat(Y10.clone(option.events || [])), message: '已提交回答：' + option.label };
  });

  B.command('home.mark_seen', (params, db) => {
    const position = params.position !== undefined ? Number(params.position) : db.position;
    return {
      events: [{
        type: 'x_home_seen', label: '用户点击「已看过」',
        payload: { position },
        patch: [{ path: 'home.last_seen_at', value: db.now }, { path: 'home.last_seen_position', value: position }]
      }],
      message: '已记下查看的位置'
    };
  });

  // 供其他处理文件使用
  B.helpers = { sceneStatus, signOf, loopOf, markerOf, requireProject, reject, since, TERMINAL_PHASES, adoptions };
})();
