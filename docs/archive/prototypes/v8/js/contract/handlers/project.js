// 概览、恢复、资料的查询与命令（BUILD.md 第 5.3 节）
(function () {
  'use strict';
  const Y8 = window.Y8;
  const B = Y8.backend;
  if (!B || !B.helpers) throw new Error('handlers/project.js 需要先加载 handlers/core.js');
  const H = B.helpers;

  const DEPT = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const PLACE = Object.assign({ user: '用户', hall: '大厅', library: '成果库', adoption: '采纳' }, DEPT);
  const FLOW_KIND = {
    handoff: '需求交接', delivery: '版本交付', defect: '问题反馈', ask: '咨询',
    answer: '回答', rework: '返工', release: '放行', adopt: '采纳'
  };
  const FLOW_STATUS = { accepted: '已接纳', open: '未完成', closed: '已关闭', rejected: '已拒绝' };
  const PHASE = {
    PRODUCT_SPEC: '产品规格', ENGINEERING: '工程实现', DELIVERY: '交付', QUALITY: '质检',
    REWORK_PRODUCT: '返工到产品', REWORK_ENGINEERING: '返工到工程',
    DONE: '已完成', PAUSED: '已暂停', FAILED: '已失败', QUEUED: '排队中'
  };
  const RECOVERING = ['interrupted', 'pending_verification', 'waiting_resume'];
  const TERMINAL_STATUS = ['adopted', 'released', 'stopped'];

  function rawById(db, list, id) {
    return ((db.raw && db.raw[list]) || []).find((item) => item.id === id) || null;
  }

  function defined(obj) {
    const out = {};
    Object.keys(obj).forEach((key) => { if (obj[key] !== undefined) out[key] = obj[key]; });
    return out;
  }

  function textOf(value) {
    return String(value || '').trim();
  }

  function bytesOf(text) {
    return new TextEncoder().encode(text).length;
  }

  function titleFrom(text, given) {
    const title = textOf(given);
    if (title) return title;
    const first = text.split(/\r?\n/)[0].trim();
    return first.length > 24 ? first.slice(0, 24) + '…' : first;
  }

  function stale(raw, params) {
    if (params.base_version === undefined || params.base_version === null || params.base_version === '') return null;
    if (Number(params.base_version) !== raw.version) {
      return H.reject('stale_base', '内容已经变化，请刷新后再提交', { current_version: raw.version });
    }
    return null;
  }

  function flag(value) {
    if (value === true || value === 'true') return true;
    if (value === false || value === 'false') return false;
    throw new Error('布尔参数无效：' + value);
  }

  function visibleProject(db, id) {
    if (!id) return H.reject('not_found', '没有给出项目');
    const raw = rawById(db, 'projects', id);
    if (!raw || !db.project(id)) return H.reject('not_found', '项目不存在：' + id);
    return raw;
  }

  function visibleItem(db, id) {
    if (!id) return H.reject('not_found', '没有给出事项');
    const raw = rawById(db, 'work_items', id);
    if (!raw || !db.workItem(id)) return H.reject('not_found', '事项不存在：' + id);
    return raw;
  }

  function archived(raw) {
    return raw.archived ? H.reject('project_archived', '归档项目只读') : null;
  }

  function providerProblem(db, projectId) {
    const models = B.models;
    if (!models || typeof models.resolve !== 'function') {
      throw new Error('模型解析还没有登记：Y8.backend.models.resolve');
    }
    for (const dept of ['product', 'engineering', 'quality']) {
      const target = models.resolve(db, projectId || null, dept);
      if (!target.ok) return (DEPT[dept] || dept) + '部门的模型无法使用：' + (target.problem || '无法解析');
    }
    return null;
  }

  function displayOf(db, item, run) {
    if (item.status === 'released') return { kind: 'released', text: '已放行' };
    const status = H.sceneStatus(db, item, run);
    if (item.kind === 'repair' && status === 'queued') return { kind: 'repair', text: '修复' };
    const map = {
      running: ['running', '运行中'],
      asking: ['asking', '询问中'],
      queued: ['queued', '排队中'],
      waiting_slot: ['waiting_slot', '等待执行槽位'],
      waiting_provider: ['waiting_provider', '等待模型服务'],
      waiting_decision: ['waiting', '等待你的决定'],
      interrupted: ['interrupted', '中断'],
      pending_verification: ['pending', '待核实'],
      waiting_resume: ['waiting', '待恢复'],
      paused: ['paused', '已暂停'],
      failed: ['failed', run && run.stop_reason && run.stop_reason.text ? run.stop_reason.text : '失败'],
      done: ['done', '已完成'],
      cancelled: ['cancelled', '已取消'],
      stopped_for_upgrade: ['failed', '因升级停止'],
      adopted: ['adopted', '已采纳']
    };
    if (!status) return { kind: 'idle', text: '未开始' };
    const pair = map[status];
    if (!pair) throw new Error('无法显示事项状态：' + status);
    if (status === 'waiting_resume' && run && run.recovery && run.recovery.unusable && run.recovery.unusable.problem) {
      return { kind: 'waiting', text: '待恢复：' + run.recovery.unusable.problem };
    }
    return { kind: pair[0], text: pair[1] };
  }

  function openQuestion(run) {
    if (!run) return null;
    const open = (run.requests || []).find((request) => request.status === 'open');
    return open ? open.question : null;
  }

  function itemOut(db, item) {
    const run = item.run_id ? db.run(item.run_id) : null;
    const scene = H.sceneStatus(db, item, run);
    const out = {
      id: item.id,
      title: item.title,
      color_index: item.color_index,
      kind: item.kind || 'request',
      status: item.status,
      phase: run ? run.phase : null,
      department: run ? (run.department || run.last_department || null) : null,
      cycle: run ? run.cycle : 0,
      started_at: run ? run.started_at : null,
      elapsed_sec: run ? run.elapsed_sec : 0,
      limit_sec: run ? run.limit_sec : 7200,
      stop_reason: run ? run.stop_reason : null,
      pending_question: openQuestion(run),
      version: item.version,
      display: displayOf(db, item, run)
    };
    if (db.atLeast('3.4A')) {
      out.queue_pos = scene === 'waiting_decision' ? null : (item.queue_pos == null ? null : item.queue_pos);
      out.queue_reason = item.status === 'queued' ? (item.queue_reason || null) : null;
    }
    if (db.atLeast('3.1')) out.recovery_state = run && run.recovery ? run.recovery.state : null;
    return out;
  }

  function phaseText(phase) {
    if (!PHASE[phase]) throw new Error('未知的 run 阶段：' + phase);
    return PHASE[phase];
  }

  function flowStatusText(status) {
    if (FLOW_STATUS[status]) return FLOW_STATUS[status];
    if (status && /[\u4e00-\u9fff]/.test(status)) return status;
    throw new Error('未知的流转状态：' + status);
  }

  function flowRows(db, projectId, workItemId) {
    const items = db.workItemsOf(projectId).filter((item) => !workItemId || item.id === workItemId);
    const rows = [];
    items.forEach((item) => {
      const run = item.run_id ? db.run(item.run_id) : null;
      (run && run.flow || []).forEach((row) => {
        if (!FLOW_KIND[row.kind]) throw new Error('未知的流转类型：' + row.kind);
        if (row.from && !PLACE[row.from]) throw new Error('未知的流转位置：' + row.from);
        if (row.to && !PLACE[row.to]) throw new Error('未知的流转位置：' + row.to);
        rows.push({
          at: row.at,
          from: row.from,
          to: row.to,
          kind: row.kind,
          content: row.content,
          status: flowStatusText(row.status),
          work_item_id: item.id,
          event_position: row.event_position == null ? null : row.event_position
        });
      });
    });
    rows.sort((a, b) => Y8.time.ms(b.at) - Y8.time.ms(a.at));
    return rows;
  }

  function copyMaterial(db, material) {
    const out = {
      id: material.id,
      project_id: material.project_id,
      work_item_id: material.work_item_id,
      kind: material.kind,
      version: material.version,
      title: material.title,
      text: material.text || '',
      at: material.at
    };
    ['accepted_from', 'goal', 'summary', 'verdict', 'files', 'git', 'diff', 'checks', 'receipts', 'confirmed'].forEach((key) => {
      if (material[key] != null) out[key] = material[key];
    });
    if (db.atLeast('3.2D') && material.screenshots) out.screenshots = material.screenshots;
    return out;
  }

  function structureIds(db, projectId) {
    const ids = new Set();
    (db.data.decisions || []).forEach((decision) => {
      if (decision.project_id === projectId && decision.materials && decision.materials.structure_material_id) {
        ids.add(decision.materials.structure_material_id);
      }
    });
    return ids;
  }

  function runsOfItem(db, workItemId) {
    return (db.data.runs || []).filter((run) => run.work_item_id === workItemId);
  }

  function oldRuns(db, runs) {
    const current = db.data.deployment.service_version;
    return runs.filter((run) => run.yudao_version && run.yudao_version !== current).map((run) => ({
      id: run.id,
      work_item_id: run.work_item_id,
      yudao_version: run.yudao_version,
      phase: run.phase,
      stop_reason: run.stop_reason,
      readonly: true,
      events: db.log({ run: run.id }).map((ev) => ({ position: ev.position, at: ev.at, type: ev.type, label: ev.label }))
    }));
  }

  function unfinishedOut(db, run) {
    return (run.recovery.unfinished || []).map((entry) => {
      const id = typeof entry === 'string' ? entry : entry.id;
      if (!id) throw new Error('未完成动作缺少标识');
      const action = (run.actions || []).find((item) => item.id === id);
      const out = {
        id,
        label: (entry && entry.label) || (action && action.summary) || id,
        department: action ? action.department : (run.department || null),
        state: action ? action.state : 'unknown',
        input: action ? action.input : null,
        before: action ? action.before : null,
        after: action ? action.after : null
      };
      if (db.atLeast('3.2C')) out.machine_id = action ? action.machine_id || null : null;
      return out;
    });
  }

  function upgradeOf(db, item) {
    const runs = runsOfItem(db, item.id);
    const stopped = runs.find((run) => run.stop_reason && run.stop_reason.code === 'upgrade');
    if (!stopped) return null;
    const newer = item.run_id && item.run_id !== stopped.id ? db.run(item.run_id) : null;
    return {
      yudao_version: stopped.yudao_version,
      stopped_run_id: stopped.id,
      new_run_id: newer ? newer.id : null,
      new_yudao_version: newer ? newer.yudao_version : null,
      queue_pos: item.queue_pos == null ? null : item.queue_pos
    };
  }

  // ---------------------------------------------------------------------------
  // 查询

  B.query('project.overview', (params, db) => {
    const project = H.requireProject(db, params.project);
    const items = db.workItemsOf(project.id).map((item) => itemOut(db, item));
    const adopted = H.adoptions(project);
    const settings = db.settings(project.id);
    const out = {
      project: defined({
        id: project.id,
        name: project.name,
        goal: project.goal,
        pinned: Boolean(project.pinned),
        archived: Boolean(project.archived),
        version: project.version,
        created_at: project.created_at,
        last_activity_at: project.last_activity_at,
        source: db.atLeast('3.8') ? (project.source || 'idea') : undefined
      }),
      adoption: adopted.length ? adopted[adopted.length - 1] : null,
      stats: {
        in_progress: items.filter((item) => item.status === 'in_progress').length,
        queued: items.filter((item) => item.status === 'queued').length,
        adopted: items.filter((item) => item.status === 'adopted').length
      },
      work_items: items
    };
    if (settings && Array.isArray(settings.source_directories)) out.source_directories = settings.source_directories;
    return out;
  });

  B.query('project.flow', (params, db) => {
    H.requireProject(db, params.project);
    if (params.work_item && !db.workItem(params.work_item)) throw new Error('事项不存在或不在当前档位：' + params.work_item);
    return { rows: flowRows(db, params.project, params.work_item || null) };
  });

  B.query('work_item.inputs', (params, db) => {
    const item = db.workItem(params.work_item);
    if (!item) throw new Error('事项不存在或不在当前档位：' + params.work_item);
    const run = item.run_id ? db.run(item.run_id) : null;
    return {
      work_item: { id: item.id, title: item.title, project_id: item.project_id, status: item.status },
      run_id: run ? run.id : null,
      inputs: run ? (run.inputs || []).map((input) => ({
        version: input.version,
        kind: input.kind,
        text: input.text,
        at: input.at,
        progress: input.progress,
        bytes: input.bytes == null ? null : input.bytes
      })) : []
    };
  });

  B.query('run.recovery', (params, db) => {
    const item = db.workItem(params.work_item);
    if (!item) throw new Error('事项不存在或不在当前档位：' + params.work_item);
    const run = item.run_id ? db.run(item.run_id) : null;
    if (!run) throw new Error('事项没有 run：' + item.id);
    if (!run.recovery) throw new Error('run 没有恢复观察：' + run.id);
    const rec = run.recovery;
    const project = db.project(item.project_id);
    const limits = Object.assign({}, rec.limits || {});
    if (db.atLeast('S4')) limits.waiting_provider_sec = run.waiting_provider_sec || 0;
    const out = {
      project: { id: project.id, name: project.name, archived: Boolean(project.archived), version: project.version },
      work_item: { id: item.id, title: item.title, status: item.status, kind: item.kind || 'request', version: item.version },
      display: displayOf(db, item, run),
      run: {
        id: run.id, phase: run.phase, phase_text: phaseText(run.phase), department: run.department, last_department: run.last_department || null,
        cycle: run.cycle, started_at: run.started_at, elapsed_sec: run.elapsed_sec, limit_sec: run.limit_sec,
        stop_reason: run.stop_reason, yudao_version: run.yudao_version
      },
      state: rec.state,
      reason: rec.reason || null,
      unusable: rec.unusable || null,
      last_confirmed: rec.last_confirmed || null,
      auto_resumed_at: rec.auto_resumed_at || null,
      unfinished: unfinishedOut(db, run),
      verifications: rec.verifications || [],
      owner: rec.owner || null,
      late_results: rec.late_results || [],
      limits,
      upgrade: upgradeOf(db, item)
    };
    if (db.atLeast('3.4A') && db.data.runtime && db.data.runtime.slots) {
      out.holds_slot = db.data.runtime.slots.used.some((entry) => entry.work_item_id === item.id);
    }
    if (db.atLeast('S4')) out.waiting_provider = run.waiting_provider || null;
    return out;
  });

  B.query('work_item.materials', (params, db) => {
    const project = H.requireProject(db, params.project);
    const all = (db.data.materials || []).filter((material) => material.project_id === project.id);
    const structs = db.atLeast('3.8') ? structureIds(db, project.id) : new Set();
    const items = db.workItemsOf(project.id).map((item) => {
      const mine = all.filter((material) => material.work_item_id === item.id);
      const counts = {};
      ['intend', 'prd', 'plan', 'delivery', 'qa', 'note'].forEach((kind) => {
        counts[kind] = mine.filter((material) => material.kind === kind).length;
      });
      const run = item.run_id ? db.run(item.run_id) : null;
      return { id: item.id, title: item.title, color_index: item.color_index, kind: item.kind || 'request', display: displayOf(db, item, run), counts };
    });
    const out = {
      project: { id: project.id, name: project.name },
      items,
      notes: all.filter((material) => material.kind === 'note' && !material.work_item_id && !structs.has(material.id)).map((material) => copyMaterial(db, material)),
      work_item: null
    };
    if (db.atLeast('3.8')) {
      out.structure = all.filter((material) => material.kind === 'structure' || structs.has(material.id)).map((material) => copyMaterial(db, material));
    }
    if (db.atLeast('3.1')) {
      const runs = params.work_item ? runsOfItem(db, params.work_item) : (db.data.runs || []).filter((run) => run.project_id === project.id);
      out.old_runs = oldRuns(db, runs);
    }
    if (!params.work_item) return out;
    const item = db.workItem(params.work_item);
    if (!item || item.project_id !== project.id) throw new Error('事项不在这个项目或当前档位：' + params.work_item);
    const run = item.run_id ? db.run(item.run_id) : null;
    const mine = all.filter((material) => material.work_item_id === item.id);
    const decisionOf = (materialId) => (db.data.decisions || []).find((decision) => decision.kind === 'initial_prd' && decision.materials && decision.materials.prd_material_id === materialId);
    const byKind = (kind) => mine.filter((material) => material.kind === kind).sort((a, b) => a.version - b.version).map((material) => {
      const copy = copyMaterial(db, material);
      if (kind === 'prd') {
        const decision = db.atLeast('3.8') ? decisionOf(material.id) : null;
        if (decision) {
          copy.initial = true;
          copy.confirmation = decision.answer || null;
        }
      }
      if (kind === 'qa' && material.receipts) {
        copy.receipt_actions = material.receipts.map((id) => {
          const action = ((run && run.actions) || []).find((entry) => entry.id === id);
          if (!action) throw new Error('质检结论「' + material.id + '」引用的检查回执不存在：' + id);
          const receipt = {
            id: action.id, department: action.department, tool: action.tool, summary: action.summary, state: action.state,
            receipt: action.receipt || null
          };
          if (db.atLeast('3.2C')) receipt.machine_id = action.machine_id || null;
          return receipt;
        });
      }
      return copy;
    });
    out.work_item = { id: item.id, title: item.title, kind: item.kind || 'request' };
    out.intend = byKind('intend');
    out.prd = byKind('prd');
    out.plan = byKind('plan');
    out.delivery = byKind('delivery');
    out.qa = byKind('qa');
    out.notes = out.notes.concat(mine.filter((material) => material.kind === 'note' && !structs.has(material.id)).map((material) => copyMaterial(db, material)));
    return out;
  });

  B.query('delivery.file', (params, db) => {
    const material = (db.data.materials || []).find((item) => item.id === params.material_id);
    if (!material) throw new Error('交付资料不存在：' + params.material_id);
    if (material.kind !== 'delivery') throw new Error('这份资料不是交付：' + material.id);
    const file = (material.files || []).find((item) => item.path === params.path);
    if (!file) throw new Error('交付中找不到文件：' + params.path);
    return {
      material_id: material.id,
      title: material.title,
      path: file.path,
      bytes: file.bytes,
      content: file.content == null ? null : file.content
    };
  });

  // ---------------------------------------------------------------------------
  // 命令

  function defaultSettings(sourceDirectories) {
    const dept = () => ({ version: 1, model: null, level: null, prompt_version: null, prompt_text: null });
    return {
      version: 1,
      departments: { product: dept(), engineering: dept(), quality: dept(), operations: null },
      commands: [],
      tools: [],
      machines: [],
      source_directories: sourceDirectories || [],
      roles: { level: 'S5' }
    };
  }

  function emptyRun(id, workItemId, projectId, now, text, extra) {
    const messages = { product: [], engineering: [], quality: [], operations: [] };
    return Object.assign({
      id, work_item_id: workItemId, project_id: projectId, yudao_version: '0.8.0',
      phase: 'PRODUCT_SPEC', department: null, last_department: null, cycle: 0,
      started_at: null, elapsed_sec: 0, limit_sec: 7200,
      waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
      recovery: {
        state: 'running', reason: '运行中', unusable: null, last_confirmed: null, owner: null,
        late_results: [], verifications: [], unfinished: [],
        limits: { elapsed_sec: 0, limit_sec: 7200, activations: 0, model_steps: 0, retries: 0 },
        auto_resumed_at: null
      },
      born_at: now, version: 1,
      inputs: [{ version: 1, kind: 'user', text, at: now, progress: 'received', bytes: bytesOf(text) }],
      flow: [], requests: [], guidance: [], messages,
      actions: [], contexts: { product: [], engineering: [], quality: [], operations: [] },
      prompts: {
        product: { config_version: 0, request_version: null, text: null },
        engineering: { config_version: 0, request_version: null, text: null },
        quality: { config_version: 0, request_version: null, text: null }
      },
      compactions: [], effective_model: { product: null, engineering: null, quality: null },
      roles: { product: [], engineering: [], quality: [] }, ledger: {}, attempts: [], trials: [], source: null
    }, extra || {});
  }

  function nextColor(items) {
    const used = items.map((item) => item.color_index);
    const free = [0, 1, 2, 3, 4, 5].find((index) => !used.includes(index));
    return free === undefined ? items.length % 6 : free;
  }

  function sourceProblem(name, path) {
    if (!textOf(name)) return '请填写源目录名称';
    if (!textOf(path)) return '请填写源目录路径';
    const value = textOf(path);
    if (value.includes('..')) return '源目录路径不能包含 .. ：' + value;
    const lower = value.toLowerCase();
    const marks = ['\\windows\\', '/etc/', '\\appdata\\', '/private/', '\\system32\\'];
    if (marks.some((mark) => lower.includes(mark))) return '源目录含有宿主私有路径：' + value;
    if (/[?*\u0000]/.test(value)) return '公开树中有无法表示的条目：' + value;
    return null;
  }

  function slotBook(db) {
    const runtime = db.raw.runtime;
    if (!runtime || !runtime.slots) throw new Error('缺少执行槽位');
    return runtime;
  }

  function queuePosNext(db, projectId) {
    const queued = (db.raw.work_items || []).filter((item) => item.project_id === projectId && item.status === 'queued');
    return queued.reduce((max, item) => Math.max(max, item.queue_pos || 0), 0) + 1;
  }

  function slotQueuePosNext(db) {
    const queue = db.raw.runtime.queue || [];
    return queue.reduce((max, entry) => Math.max(max, entry.position || 0), 0) + 1;
  }

  function queueRenumber(db, skipId) {
    const queue = (db.raw.runtime.queue || []).filter((entry) => entry.work_item_id !== skipId).slice().sort((a, b) => a.position - b.position);
    return queue.map((entry, index) => ({ path: 'runtime.queue[work_item_id=' + entry.work_item_id + '].position', value: index + 1 }));
  }

  function startFields(now) {
    return { phase: 'PRODUCT_SPEC', department: 'product', cycle: 1, started_at: now };
  }

  function acquirePatches(item, runId, now, fromSlotQueue) {
    const fields = startFields(now);
    const patches = [
      { path: 'work_items[id=' + item.id + '].status', value: 'in_progress' },
      { path: 'work_items[id=' + item.id + '].queue_reason', value: null },
      { path: 'work_items[id=' + item.id + '].queue_pos', value: null },
      { path: 'runs[id=' + runId + '].phase', value: fields.phase },
      { path: 'runs[id=' + runId + '].department', value: fields.department },
      { path: 'runs[id=' + runId + '].cycle', value: fields.cycle },
      { path: 'runs[id=' + runId + '].started_at', value: fields.started_at },
      { path: 'runtime.slots.used', push: { work_item_id: item.id, department: 'product', role: null } },
      { path: 'projects[id=' + item.project_id + '].last_activity_at', value: now }
    ];
    if (fromSlotQueue) patches.push({ path: 'runtime.queue', remove: { key: 'work_item_id', value: item.id } });
    return patches;
  }

  function renumber(db, projectId, skipId) {
    const queued = (db.raw.work_items || []).filter((item) => item.project_id === projectId && item.status === 'queued' && item.id !== skipId);
    const repairs = queued.filter((item) => item.kind === 'repair').sort((a, b) => (a.queue_pos || 0) - (b.queue_pos || 0));
    const rest = queued.filter((item) => item.kind !== 'repair').sort((a, b) => (a.queue_pos || 0) - (b.queue_pos || 0));
    return repairs.concat(rest).map((item, index) => ({ path: 'work_items[id=' + item.id + '].queue_pos', value: index + 1 }));
  }

  // 新事项的开始方式：3.4A 起先看执行槽位与同一项目的进行中事项，放不下就排队
  function planStart(db, projectId, running) {
    const plan = { status: 'in_progress', queueReason: null, queuePos: null, slotQueuePosition: null };
    if (!db.atLeast('3.4A')) return plan;
    const slots = slotBook(db).slots;
    if ((slots.used || []).length >= slots.total) {
      plan.status = 'queued';
      plan.queueReason = 'slot';
      plan.queuePos = queuePosNext(db, projectId);
      plan.slotQueuePosition = slotQueuePosNext(db);
    } else if (running) {
      plan.status = 'queued';
      plan.queueReason = 'project';
      plan.queuePos = queuePosNext(db, projectId);
    }
    return plan;
  }

  B.command('project.create', (params, db) => {
    const name = textOf(params.name);
    if (!name) throw new Error('请填写项目名称');
    if ((db.raw.projects || []).some((project) => project.name === name)) return H.reject('already_exists', '已经有同名项目：' + name);
    const id = Y8.uid('p');
    const goal = textOf(params.goal);
    return {
      events: [{
        type: 'project_registered', project_id: id,
        label: '用户从想法建立项目「' + name + '」',
        payload: { name, goal, source: 'idea' },
        patch: [
          { path: 'projects', push: {
            id, name, goal, pinned: false, archived: false, version: 1, source: 'idea',
            created_at: db.now, last_activity_at: db.now, born_at: db.now, adoptions: []
          } },
          { path: 'project_settings', put: { key: id, value: defaultSettings([]) } }
        ]
      }],
      refs: { project_id: id },
      message: '已提交：已新建项目「' + name + '」'
    };
  });

  B.command('project.onboard', (params, db) => {
    const problem = sourceProblem(params.source_name, params.source_path);
    if (problem) return H.reject('source_invalid', problem);
    const name = textOf(params.name);
    if (!name) throw new Error('请填写项目名称');
    if (!db.atLeast('3.4A') && (db.data.work_items || []).some((item) => item.status === 'in_progress')) {
      return H.reject('busy', '3.4A 之前同时只能有一个进行中的事项');
    }
    const unavailable = providerProblem(db, null);
    if (unavailable) return H.reject('provider_unavailable', unavailable);
    const id = Y8.uid('p');
    const workId = Y8.uid('w');
    const runId = 'r' + workId.slice(1);
    const goal = textOf(params.goal);
    const sourceName = textOf(params.source_name);
    const sourcePath = textOf(params.source_path);
    const text = '接入已有项目「' + name + '」，源目录「' + sourceName + '」。';
    const plan = planStart(db, id, false);
    const run = emptyRun(runId, workId, id, db.now, text, Object.assign({ kind: 'onboarding' }, plan.status === 'in_progress' ? startFields(db.now) : { phase: 'QUEUED' }));
    run.source = { name: sourceName, path: sourcePath };
    const events = [
      {
        type: 'project_registered', project_id: id,
        label: '用户接入已有项目「' + name + '」',
        payload: { name, goal, source: 'existing', source_name: sourceName, source_path: sourcePath },
        patch: [
          { path: 'projects', push: {
            id, name, goal, pinned: false, archived: false, version: 1, source: 'existing',
            created_at: db.now, last_activity_at: db.now, born_at: db.now, adoptions: []
          } },
          { path: 'project_settings', put: { key: id, value: defaultSettings([{ name: sourceName, path: sourcePath }]) } }
        ]
      },
      {
        type: 'work_item_created', project_id: id, work_item_id: workId, run_id: runId,
        label: '建立建档事项「接入 ' + name + '」',
        payload: { title: '接入 ' + name, kind: 'onboarding', snapshot: { source_name: sourceName, source_path: sourcePath } },
        patch: [{ path: 'work_items', push: {
          id: workId, project_id: id, title: '接入 ' + name, color_index: 0, kind: 'onboarding',
          status: plan.status, queue_reason: plan.queueReason, queue_pos: plan.queuePos, run_id: runId, version: 1,
          created_at: db.now, born_at: db.now
        } }]
      },
      {
        type: 'run_created', project_id: id, work_item_id: workId, run_id: runId,
        label: '建档 run 建立',
        payload: { kind: 'onboarding', yudao_version: '0.8.0' },
        patch: [{ path: 'runs', push: run }]
      },
      {
        type: 'user_input_received', project_id: id, work_item_id: workId, run_id: runId,
        label: '建档事项收到接入说明',
        payload: { progress: 'received', kind: 'onboarding' },
        patch: plan.status === 'in_progress' && db.atLeast('3.4A')
          ? [{ path: 'runtime.slots.used', push: { work_item_id: workId, department: 'product', role: null } }]
          : []
      }
    ];
    if (plan.status === 'queued') {
      events.push({
        type: 'x_queued', project_id: id, work_item_id: workId, run_id: runId, level: '3.4A',
        label: '建档事项进入队列：执行槽位已满',
        payload: { queue_reason: plan.queueReason, queue_pos: plan.queuePos },
        patch: [{ path: 'runtime.queue', push: { work_item_id: workId, project_id: id, since: db.now, position: plan.slotQueuePosition, queue_reason: 'slot' } }]
      });
    }
    return {
      events,
      refs: { project_id: id, work_item_id: workId, run_id: runId },
      message: plan.status === 'queued' ? '已提交：执行槽位已满，建档事项进入队列' : '已提交：开始接入「' + name + '」'
    };
  });

  B.command('onboarding.restart', (params, db) => {
    const project = visibleProject(db, params.project);
    if (project.reject) return project;
    const denied = archived(project);
    if (denied) return denied;
    if ((project.source || 'idea') !== 'existing') return H.reject('not_allowed', '项目由想法新建，不能重新开始建档');
    if (H.adoptions(db.project(project.id)).length) return H.reject('not_allowed', '项目已有基线采纳');
    const waiting = (db.data.decisions || []).some((decision) => decision.project_id === project.id && decision.kind === 'initial_prd' && decision.status === 'waiting');
    const active = db.workItemsOf(project.id).some((item) => item.kind === 'onboarding' && (item.status === 'in_progress' || item.status === 'queued'));
    if (waiting || active) return H.reject('not_allowed', '已有进行中或等待确认的建档事项');
    const settings = db.raw.project_settings && db.raw.project_settings[project.id];
    const dirs = settings && settings.source_directories || [];
    const source = dirs.find((dir) => dir.name === params.source_name);
    if (!source) return H.reject('source_invalid', '没有这个源目录：' + (params.source_name || ''));
    const workId = Y8.uid('w');
    const runId = 'r' + workId.slice(1);
    const text = '重新开始建档，源目录「' + source.name + '」。';
    const items = db.workItemsOf(project.id);
    const plan = planStart(db, project.id, items.some((item) => item.status === 'in_progress'));
    const run = emptyRun(runId, workId, project.id, db.now, text, Object.assign({ kind: 'onboarding' }, plan.status === 'in_progress' ? startFields(db.now) : { phase: 'QUEUED' }));
    run.source = { name: source.name, path: source.path };
    const events = [
      {
        type: 'work_item_created', project_id: project.id, work_item_id: workId, run_id: runId,
        label: '重新开始建档',
        payload: { kind: 'onboarding', source_name: source.name },
        patch: [
          { path: 'work_items', push: {
            id: workId, project_id: project.id, title: '重新建档', color_index: nextColor(items), kind: 'onboarding',
            status: plan.status, queue_reason: plan.queueReason, queue_pos: plan.queuePos, run_id: runId, version: 1,
            created_at: db.now, born_at: db.now
          } },
          { path: 'projects[id=' + project.id + '].last_activity_at', value: db.now }
        ]
      },
      {
        type: 'run_created', project_id: project.id, work_item_id: workId, run_id: runId,
        label: '新的建档 run 建立',
        payload: { kind: 'onboarding' },
        patch: [{ path: 'runs', push: run }]
      },
      {
        type: 'user_input_received', project_id: project.id, work_item_id: workId, run_id: runId,
        label: '重新建档的说明已接收',
        payload: { progress: 'received' },
        patch: plan.status === 'in_progress' && db.atLeast('3.4A')
          ? [{ path: 'runtime.slots.used', push: { work_item_id: workId, department: 'product', role: null } }]
          : []
      }
    ];
    if (plan.status === 'queued') {
      events.push({
        type: 'x_queued', project_id: project.id, work_item_id: workId, run_id: runId, level: '3.4A',
        label: '重新建档的事项进入队列',
        payload: { queue_reason: plan.queueReason, queue_pos: plan.queuePos },
        patch: plan.queueReason === 'slot'
          ? [{ path: 'runtime.queue', push: { work_item_id: workId, project_id: project.id, since: db.now, position: plan.slotQueuePosition, queue_reason: 'slot' } }]
          : []
      });
    }
    return {
      events,
      refs: { project_id: project.id, work_item_id: workId, run_id: runId },
      message: plan.status === 'queued' ? '已提交：重新开始建档，事项进入队列' : '已提交：重新开始建档'
    };
  });

  B.command('project.rename', (params, db) => {
    const project = visibleProject(db, params.project);
    if (project.reject) return project;
    const denied = archived(project) || stale(project, params);
    if (denied) return denied;
    const name = textOf(params.name);
    if (!name) throw new Error('项目名称不能为空');
    return {
      events: [{
        type: 'project_renamed', project_id: project.id,
        label: '项目重命名为「' + name + '」',
        payload: { name },
        patch: [{ path: 'projects[id=' + project.id + '].name', value: name }]
      }],
      refs: { project_id: project.id },
      message: '已提交：项目已重命名为「' + name + '」'
    };
  });

  B.command('project.pin', (params, db) => {
    const project = visibleProject(db, params.project);
    if (project.reject) return project;
    const denied = archived(project) || stale(project, params);
    if (denied) return denied;
    const pinned = flag(params.pinned);
    return {
      events: [{
        type: 'project_pinned', project_id: project.id,
        label: pinned ? '置顶项目「' + project.name + '」' : '取消置顶「' + project.name + '」',
        payload: { pinned },
        patch: [{ path: 'projects[id=' + project.id + '].pinned', value: pinned }]
      }],
      refs: { project_id: project.id },
      message: pinned ? '已提交：已置顶' : '已提交：已取消置顶'
    };
  });

  B.command('project.archive', (params, db) => {
    const project = visibleProject(db, params.project);
    if (project.reject) return project;
    const denied = archived(project) || stale(project, params);
    if (denied) return denied;
    const blocking = db.workItemsOf(project.id).find((item) => {
      if (item.status === 'in_progress' || item.status === 'queued') return true;
      const run = item.run_id ? db.run(item.run_id) : null;
      return run && run.recovery && RECOVERING.includes(run.recovery.state);
    });
    if (blocking) return H.reject('work_item_in_progress', '项目还有进行中、排队中或待处理的事项：' + blocking.title);
    return {
      events: [{
        type: 'project_archived', project_id: project.id,
        label: '归档项目「' + project.name + '」',
        payload: {},
        patch: [{ path: 'projects[id=' + project.id + '].archived', value: true }]
      }],
      refs: { project_id: project.id },
      message: '已提交：已归档「' + project.name + '」'
    };
  });

  B.command('project.restore', (params, db) => {
    const project = visibleProject(db, params.project);
    if (project.reject) return project;
    const denied = stale(project, params);
    if (denied) return denied;
    return {
      events: [{
        type: 'project_restored', project_id: project.id,
        label: '恢复项目「' + project.name + '」',
        payload: {},
        patch: [{ path: 'projects[id=' + project.id + '].archived', value: false }]
      }],
      refs: { project_id: project.id },
      message: '已提交：已恢复项目「' + project.name + '」'
    };
  });

  B.command('material.record', (params, db) => {
    const project = visibleProject(db, params.project);
    if (project.reject) return project;
    const denied = archived(project);
    if (denied) return denied;
    const text = textOf(params.text);
    if (!text) throw new Error('请先输入要记录的原文');
    if (params.department && !DEPT[params.department]) throw new Error('未知部门：' + params.department);
    const id = Y8.uid('m');
    return {
      events: [{
        type: 'material_recorded', project_id: project.id,
        label: '记录原文',
        payload: { material_id: id, department: params.department || null },
        patch: [
          { path: 'materials', push: {
            id, project_id: project.id, work_item_id: null, kind: 'note', version: 1,
            title: params.department ? DEPT[params.department] + '部门材料' : '项目材料',
            department: params.department || null, text, at: db.now
          } },
          { path: 'projects[id=' + project.id + '].last_activity_at', value: db.now }
        ]
      }],
      refs: { project_id: project.id, material_id: id },
      message: '已提交：已记录原文'
    };
  });

  B.command('work_item.create', (params, db) => {
    const project = visibleProject(db, params.project);
    if (project.reject) return project;
    const denied = archived(project);
    if (denied) return denied;
    const text = textOf(params.text);
    if (!text) throw new Error('请先输入事项原文');
    const items = db.workItemsOf(project.id);
    const running = items.some((item) => item.status === 'in_progress');
    if (!db.atLeast('3.4A') && running) return H.reject('work_item_in_progress', '本项目已有进行中的事项');
    if (db.atLeast('3.1') && db.data.system.drain && db.data.system.drain.state !== 'none') {
      return H.reject('busy', '正在排空，不能新建事项');
    }
    const unavailable = providerProblem(db, project.id);
    if (unavailable) return H.reject('provider_unavailable', unavailable);
    const workId = Y8.uid('w');
    const runId = 'r' + workId.slice(1);
    const plan = planStart(db, project.id, running);
    let message = '已提交：已新建事项，进入产品部门';
    if (plan.queueReason === 'slot') message = '已提交：执行槽位已满，事项进入队列';
    if (plan.queueReason === 'project') message = '已提交：本项目已有进行中的事项，新事项进入队列';
    const runExtra = plan.status === 'in_progress' ? startFields(db.now) : { phase: 'QUEUED' };
    if (params.source_dir) runExtra.source = { dir: textOf(params.source_dir), digest: null, files: null };
    const run = emptyRun(runId, workId, project.id, db.now, text, runExtra);
    const item = {
      id: workId, project_id: project.id, title: titleFrom(text, params.title), color_index: nextColor(items),
      kind: 'request', status: plan.status, queue_reason: plan.queueReason, queue_pos: plan.queuePos, run_id: runId, version: 1,
      created_at: db.now, born_at: db.now
    };
    const events = [
      {
        type: 'work_item_created', project_id: project.id, work_item_id: workId, run_id: runId,
        label: '用户提出事项「' + item.title + '」',
        payload: { title: item.title, source_dir: params.source_dir || null },
        patch: [
          { path: 'work_items', push: item },
          { path: 'projects[id=' + project.id + '].last_activity_at', value: db.now }
        ]
      },
      {
        type: 'run_created', project_id: project.id, work_item_id: workId, run_id: runId,
        label: '事项「' + item.title + '」的 run 建立',
        payload: { yudao_version: '0.8.0' },
        patch: [{ path: 'runs', push: run }]
      },
      {
        type: 'user_input_received', project_id: project.id, work_item_id: workId, run_id: runId,
        label: '事项原文已接收',
        payload: { progress: 'received' },
        patch: []
      }
    ];
    if (plan.status === 'queued') {
      events.push({
        type: 'x_queued', project_id: project.id, work_item_id: workId, run_id: runId, level: '3.4A',
        label: '事项「' + item.title + '」进入队列，原因是' + (plan.queueReason === 'slot' ? '执行槽位已满' : '同一项目已有进行中的事项'),
        payload: { queue_reason: plan.queueReason, queue_pos: plan.queuePos },
        patch: plan.queueReason === 'slot' ? [{ path: 'runtime.queue', push: { work_item_id: workId, project_id: project.id, since: db.now, position: plan.slotQueuePosition, queue_reason: 'slot' } }] : []
      });
    } else if (db.atLeast('3.4A')) {
      events.push({
        type: 'x_slot_acquired', project_id: project.id, work_item_id: workId, run_id: runId, department: 'product', level: '3.4A',
        label: '事项「' + item.title + '」取得执行槽位',
        payload: {},
        patch: [{ path: 'runtime.slots.used', push: { work_item_id: workId, department: 'product', role: null } }]
      });
    }
    return { events, refs: { project_id: project.id, work_item_id: workId, run_id: runId }, message };
  });

  function terminal(db, item, run) {
    const recovering = run && run.recovery && RECOVERING.includes(run.recovery.state);
    if (recovering) return false;
    if (TERMINAL_STATUS.includes(item.status)) return true;
    return Boolean(run && H.TERMINAL_PHASES.includes(run.phase));
  }

  function cancelEvents(db, item, run, label) {
    const events = [{
      type: 'run_failed', project_id: item.project_id, work_item_id: item.id, run_id: run.id,
      department: run.department, label,
      payload: { reason: 'cancelled' },
      patch: [
        { path: 'work_items[id=' + item.id + '].status', value: 'stopped' },
        { path: 'work_items[id=' + item.id + '].queue_reason', value: null },
        { path: 'work_items[id=' + item.id + '].queue_pos', value: null },
        { path: 'runs[id=' + run.id + '].phase', value: 'FAILED' },
        { path: 'runs[id=' + run.id + '].department', value: null },
        { path: 'runs[id=' + run.id + '].last_department', value: run.department || run.last_department },
        { path: 'runs[id=' + run.id + '].stop_reason', value: { code: 'cancelled', text: '用户取消事项' } },
        { path: 'runs[id=' + run.id + '].recovery.state', value: 'terminated' },
        { path: 'runs[id=' + run.id + '].recovery.reason', value: '事项已取消' },
        { path: 'projects[id=' + item.project_id + '].last_activity_at', value: db.now }
      ]
    }];
    if (!db.atLeast('3.4A')) return events;
    const runtime = slotBook(db);
    const holds = (runtime.slots.used || []).some((entry) => entry.work_item_id === item.id);
    const queued = (runtime.queue || []).some((entry) => entry.work_item_id === item.id);
    if (item.status === 'queued') events[0].patch.push.apply(events[0].patch, renumber(db, item.project_id, item.id));
    const release = [];
    if (holds) release.push({ path: 'runtime.slots.used', remove: { key: 'work_item_id', value: item.id } });
    if (queued) release.push({ path: 'runtime.queue', remove: { key: 'work_item_id', value: item.id } });
    if (release.length) {
      events.push({
        type: 'x_queue_cancelled', project_id: item.project_id, work_item_id: item.id, run_id: run.id, level: '3.4A',
        label: '取消事项后释放执行槽位',
        payload: { reason: 'cancelled' },
        patch: release.concat(queued ? queueRenumber(db, item.id) : [])
      });
    }
    const usedAfter = (runtime.slots.used || []).filter((entry) => entry.work_item_id !== item.id).length;
    if (usedAfter >= runtime.slots.total) return events;
    const global = (runtime.queue || []).filter((entry) => entry.work_item_id !== item.id).slice().sort((a, b) => a.position - b.position);
    const head = global.length ? rawById(db, 'work_items', global[0].work_item_id) : null;
    let next = head && head.status === 'queued' ? head : null;
    const fromSlot = Boolean(next);
    if (!next && (holds || item.status === 'in_progress')) {
      const local = (db.raw.work_items || []).filter((other) => other.project_id === item.project_id && other.status === 'queued' && other.id !== item.id);
      local.sort((a, b) => (a.kind === 'repair' ? -1 : 1) - (b.kind === 'repair' ? -1 : 1) || ((a.queue_pos || 0) - (b.queue_pos || 0)));
      next = local[0] || null;
    }
    if (!next || !next.run_id) return events;
    const patches = acquirePatches(next, next.run_id, db.now, fromSlot).concat(renumber(db, next.project_id, next.id));
    if (fromSlot) patches.push.apply(patches, queueRenumber(db, next.id));
    events.push({
      type: 'x_slot_acquired', project_id: next.project_id, work_item_id: next.id, run_id: next.run_id, department: 'product', level: '3.4A',
      label: '队首事项「' + next.title + '」取得执行槽位',
      payload: {},
      patch: patches
    });
    return events;
  }

  B.command('work_item.append_input', (params, db) => {
    const item = visibleItem(db, params.work_item);
    if (item.reject) return item;
    const project = rawById(db, 'projects', item.project_id);
    const denied = project && archived(project);
    if (denied) return denied;
    const run = rawById(db, 'runs', item.run_id);
    if (!run) return H.reject('not_found', '事项没有 run');
    const text = textOf(params.text);
    if (!text) throw new Error('请先输入要追加的内容');
    if (terminal(db, item, run)) return H.reject('run_terminal', '事项已结束，不会自动新建');
    const version = (run.inputs || []).length + 1;
    const input = { version, kind: text === '/stop' || text === '/cancel' ? 'command' : 'user', text, at: db.now, progress: 'received', bytes: bytesOf(text) };
    const received = {
      type: 'user_input_received', project_id: item.project_id, work_item_id: item.id, run_id: run.id,
      label: input.kind === 'command' ? '收到停止命令 ' + text : '追加需求已接收，版本 v' + version,
      payload: { progress: 'received', version },
      patch: [{ path: 'runs[id=' + run.id + '].inputs', push: input }]
    };
    if (input.kind === 'command') {
      return { events: [received].concat(cancelEvents(db, item, run, '文本命令 ' + text + ' 停止事项')), refs: { work_item_id: item.id }, message: '已提交：' + text + ' 已停止事项' };
    }
    return { events: [received], refs: { work_item_id: item.id }, message: '已提交：已追加为用户输入 v' + version };
  });

  B.command('work_item.cancel', (params, db) => {
    const item = visibleItem(db, params.work_item);
    if (item.reject) return item;
    const run = rawById(db, 'runs', item.run_id);
    if (!run) return H.reject('not_found', '事项没有 run');
    if (terminal(db, item, run)) return H.reject('run_terminal', '事项已结束，不能取消');
    return {
      events: cancelEvents(db, item, run, '用户取消事项「' + item.title + '」'),
      refs: { work_item_id: item.id, run_id: run.id },
      message: '已提交：已取消事项「' + item.title + '」'
    };
  });

  B.command('work_item.reorder', (params, db) => {
    const raw = params.project ? rawById(db, 'projects', params.project) : null;
    if (!raw || !db.project(raw.id)) return H.reject('not_allowed', '项目不存在：' + (params.project || ''));
    const project = raw;
    const denied = stale(project, params);
    if (denied) return denied;
    const order = Array.isArray(params.order) ? params.order.slice() : String(params.order || '').split(',').map((id) => id.trim()).filter(Boolean);
    if (!order.length) throw new Error('调整顺序需要 order');
    const queued = (db.raw.work_items || []).filter((item) => item.project_id === project.id && item.status === 'queued' && db.workItem(item.id));
    const repairs = queued.filter((item) => item.kind === 'repair');
    const blocked = queued.filter((item) => item.kind !== 'repair' && item.queue_reason === 'decision');
    const movable = queued.filter((item) => item.kind !== 'repair' && item.queue_reason !== 'decision');
    if (order.some((id) => blocked.some((item) => item.id === id))) return H.reject('not_allowed', '等待你的决定的事项不参与调整');
    if (order.some((id) => repairs.some((item) => item.id === id))) return H.reject('not_allowed', '修复事项固定在队列前面，不参与调整');
    const movableIds = movable.map((item) => item.id).sort();
    const given = order.slice().sort();
    if (movableIds.length !== given.length || movableIds.some((id, index) => id !== given[index])) {
      return H.reject('not_allowed', '顺序必须正好包含本项目排队中、且不是修复事项的事项');
    }
    const patches = repairs.sort((a, b) => (a.queue_pos || 0) - (b.queue_pos || 0)).map((item, index) => ({ path: 'work_items[id=' + item.id + '].queue_pos', value: index + 1 }));
    order.forEach((id, index) => patches.push({ path: 'work_items[id=' + id + '].queue_pos', value: repairs.length + index + 1 }));
    patches.push({ path: 'projects[id=' + project.id + '].last_activity_at', value: db.now });
    return {
      events: [{
        type: 'x_queue_reordered', project_id: project.id, level: '3.4A',
        label: '用户调整了本项目的排队顺序',
        payload: { order },
        patch: patches
      }],
      refs: { project_id: project.id },
      message: '已提交：排队顺序已调整'
    };
  });
})();
