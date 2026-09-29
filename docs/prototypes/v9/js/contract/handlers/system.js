// 系统页的查询与命令，以及模型解析（BUILD.md 第 5.3 节）
// 项目部门设置读取 settings.departments[部门].model / request_level
// 项目角色设置读取 settings.roles[部门] 中 role_id、model、request_level
(function () {
  'use strict';
  const Y8 = window.Y8;
  const B = Y8.backend;
  if (!B || !B.helpers) throw new Error('handlers/system.js 需要先加载 handlers/core.js');

  const reject = B.helpers.reject;
  const DEPT_LABELS = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const DEPTS = ['product', 'engineering', 'quality'];
  const PROTOCOLS = ['responses', 'chat', 'messages'];
  const PROTOCOL_LABELS = { responses: 'Responses', chat: 'Chat Completions', messages: 'Anthropic Messages' };
  const REASONING_LEVELS = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
  const REASONING_METHODS = ['effort', 'adaptive', 'budget'];
  const DOC_CONN_FIELDS = ['id', 'name', 'scheme', 'protocol', 'base_url', 'credential_ref', 'timeout_sec', 'models_url', 'definitions'];
  const DOC_DEF_FIELDS = ['id', 'upstream_model', 'window', 'max_output', 'image_input', 'accepts_required_tool_call', 'reasoning', 'capacity_accepted'];
  const TERMINAL = B.helpers.TERMINAL_PHASES;

  let bound = null;

  function deptLabel(id) {
    if (!DEPT_LABELS[id]) throw new Error('未知部门：' + id);
    return DEPT_LABELS[id];
  }

  function catalogOf(db) {
    if (!db || !db.data || !db.data.catalog) throw new Error('当前数据没有模型目录');
    return db.data.catalog;
  }

  function definitionOf(catalog, id) {
    return (catalog.definitions || []).find((item) => item.id === id) || null;
  }

  function connectionOf(catalog, id) {
    return (catalog.connections || []).find((item) => item.id === id) || null;
  }

  function credentialOf(catalog, ref) {
    return (catalog.credentials || []).find((item) => item.ref === ref) || null;
  }

  function schemeOf(catalog, id) {
    const found = catalog.presets.schemes.find((item) => item.id === id);
    if (!found) throw new Error('未知服务方案：' + id);
    return found;
  }

  function clampLevel(requested, reasoning) {
    if (!reasoning || !reasoning.levels || !reasoning.levels.length) return null;
    const wanted = requested || reasoning.default_level;
    const supported = reasoning.levels.slice().sort((a, b) => REASONING_LEVELS.indexOf(a) - REASONING_LEVELS.indexOf(b));
    const below = supported.filter((item) => REASONING_LEVELS.indexOf(item) <= REASONING_LEVELS.indexOf(wanted));
    return below.length ? below[below.length - 1] : supported[0];
  }

  function problemOf(db, definitionId) {
    bound = db;
    const catalog = catalogOf(db);
    const def = definitionOf(catalog, definitionId);
    if (!def) return '定义被移除';
    if (!def.admission) return def.admission_revoked ? '准入已作废' : '尚未准入';
    if (!def.window) return '窗口未知';
    const conn = connectionOf(catalog, def.connection_id);
    if (!conn) return '定义被移除';
    if (conn.credential_ref) {
      const cred = credentialOf(catalog, conn.credential_ref);
      if (!cred || cred.state === 'missing') return '凭据缺失：' + conn.credential_ref;
      if (cred.rejected) return '凭据被上游拒绝：' + conn.credential_ref;
    }
    return null;
  }

  function label(definitionId) {
    if (!definitionId) return '未设置';
    if (!bound || !bound.data || !bound.data.catalog) throw new Error('label 缺少当前目录');
    const catalog = bound.data.catalog;
    const def = definitionOf(catalog, definitionId);
    if (!def) return definitionId + '（定义已移除）';
    const conn = connectionOf(catalog, def.connection_id);
    return def.upstream_model + ' · ' + (conn ? conn.name : def.connection_id);
  }

  function targetOf(db, definitionId, source, requestLevel) {
    if (!definitionId) {
      return {
        ok: false, definition: null, model: null, connection: null, connection_name: null, protocol: null,
        source: null, request_level: requestLevel || null, sent_level: null, problem: '未设置', image_input: null
      };
    }
    const catalog = catalogOf(db);
    const def = definitionOf(catalog, definitionId);
    const problem = problemOf(db, definitionId);
    const conn = def ? connectionOf(catalog, def.connection_id) : null;
    return {
      ok: !problem,
      definition: definitionId,
      model: def ? def.upstream_model : null,
      connection: conn ? conn.id : null,
      connection_name: conn ? conn.name : null,
      protocol: conn ? PROTOCOL_LABELS[conn.protocol] : null,
      source,
      request_level: requestLevel || null,
      sent_level: def ? clampLevel(requestLevel, def.reasoning) : null,
      problem,
      image_input: def ? Boolean(def.image_input) : null
    };
  }

  function pick(db, layers) {
    const modelLayer = layers.find((layer) => layer[1] && layer[1][layer[2]]);
    const levelLayer = layers.find((layer) => layer[1] && layer[1].request_level);
    const target = targetOf(
      db,
      modelLayer ? modelLayer[1][modelLayer[2]] : null,
      modelLayer ? modelLayer[0] : null,
      levelLayer ? levelLayer[1].request_level : null
    );
    target.level_source = levelLayer ? levelLayer[0] : null;
    return target;
  }

  function deptSetting(db, projectId, department) {
    const settings = projectId ? db.settings(projectId) : null;
    if (!settings || !settings.departments) return null;
    return settings.departments[department] || null;
  }

  function resolve(db, projectId, department) {
    bound = db;
    if (!DEPT_LABELS[department]) throw new Error('未知部门：' + department);
    const catalog = catalogOf(db);
    const defaults = catalog.department_defaults || {};
    return pick(db, [
      ['项目设置', deptSetting(db, projectId, department), 'model'],
      ['部门默认', defaults[department] || null, 'definition']
    ]);
  }

  function roleList(db, department) {
    const catalog = catalogOf(db);
    const roles = catalog.role_catalog && catalog.role_catalog[department];
    if (!Array.isArray(roles)) throw new Error('当前档位没有部门「' + department + '」的角色目录');
    return roles;
  }

  function resolveRole(db, projectId, department, roleId) {
    bound = db;
    const roles = roleList(db, department);
    if (!roles.some((role) => role.id === roleId)) throw new Error('部门「' + department + '」没有角色：' + roleId);
    const catalog = catalogOf(db);
    const settings = projectId ? db.settings(projectId) : null;
    const list = settings && settings.roles && Array.isArray(settings.roles[department]) ? settings.roles[department] : [];
    const roleSetting = list.find((entry) => entry.role_id === roleId) || null;
    const roleDefault = catalog.role_defaults ? catalog.role_defaults[roleId] || null : null;
    const target = pick(db, [
      ['项目角色设置', roleSetting, 'model'],
      ['角色默认', roleDefault, 'definition'],
      ['项目设置', deptSetting(db, projectId, department), 'model'],
      ['部门默认', (catalog.department_defaults || {})[department] || null, 'definition']
    ]);
    target.role_id = roleId;
    return target;
  }

  B.models = { label, problemOf, resolve, resolveRole };

  function imageWarning(db, department, definitionId, roleName) {
    if (department !== 'quality' || !definitionId) return null;
    const def = definitionOf(catalogOf(db), definitionId);
    if (!def || def.image_input) return null;
    const who = roleName ? '质检 · ' + roleName : '质检';
    return {
      department, role: roleName || null, model: def.upstream_model, definition: definitionId,
      missing: '图像输入',
      impact: '不提供 computer use，浏览器只给可访问性结构，不给截图',
      text: who + '的模型 ' + def.upstream_model + ' 缺少图像输入。不提供 computer use，浏览器只给可访问性结构，不给截图。'
    };
  }

  B.checks.model_ok = function modelOk(db, decision) {
    const materials = decision.materials;
    if (!materials || !materials.department) throw new Error('待恢复决定请求缺少 materials.department');
    const target = resolve(db, decision.project_id, materials.department);
    if (target.ok) return null;
    return '原因尚未修复：' + deptLabel(materials.department) + '部门的 ' + (target.model || '模型') + ' ' + target.problem;
  };

  function revisionOf(db) {
    return catalogOf(db).file.revision;
  }

  function needRevision(db, params) {
    if (params.base_version === undefined || params.base_version === null || params.base_version === '') return null;
    if (Number(params.base_version) !== revisionOf(db)) {
      return reject('stale_base', '目录已经变化，请刷新后再保存', { current_version: revisionOf(db) });
    }
    return null;
  }

  function bumpRevision(db) {
    const next = revisionOf(db) + 1;
    return [
      { path: 'catalog.file.revision', value: next },
      { path: 'system.catalog_revision', value: next }
    ];
  }

  function rawDefinition(db, id) {
    return (db.raw.catalog.definitions || []).find((item) => item.id === id) || null;
  }

  function referrersOf(db, definitionIds) {
    const ids = new Set(definitionIds);
    const out = [];
    const catalog = catalogOf(db);
    Object.keys(catalog.department_defaults || {}).forEach((dept) => {
      if (!DEPT_LABELS[dept]) return;
      const entry = catalog.department_defaults[dept];
      if (entry && ids.has(entry.definition)) out.push({ kind: 'department_default', department: dept, definition: entry.definition, text: '部门默认 · ' + deptLabel(dept) });
    });
    Object.keys(catalog.role_defaults || {}).forEach((roleId) => {
      if (roleId === 'level' || roleId === 'until') return;
      const entry = catalog.role_defaults[roleId];
      if (entry && ids.has(entry.definition)) out.push({ kind: 'role_default', role_id: roleId, definition: entry.definition, text: '角色默认 · ' + roleId });
    });
    const settingsAll = db.data.project_settings || {};
    Object.keys(settingsAll).forEach((projectId) => {
      const settings = settingsAll[projectId];
      const project = (db.data.projects || []).find((item) => item.id === projectId);
      const name = project ? project.name : projectId;
      Object.keys((settings && settings.departments) || {}).forEach((dept) => {
        const entry = settings.departments[dept];
        if (entry && ids.has(entry.model)) out.push({ kind: 'project_department', project_id: projectId, department: dept, definition: entry.model, text: name + ' · ' + deptLabel(dept) + '的项目部门设置' });
      });
      Object.keys((settings && settings.roles) || {}).forEach((dept) => {
        (settings.roles[dept] || []).forEach((entry) => {
          if (entry && ids.has(entry.model)) out.push({ kind: 'project_role', project_id: projectId, department: dept, role_id: entry.role_id, definition: entry.model, text: name + ' · 角色 ' + entry.role_id });
        });
      });
    });
    return out;
  }

  function effectivePatches(db, catalog) {
    const view = {
      data: Object.assign({}, db.data, { catalog }),
      settings: db.settings,
      atLeast: db.atLeast
    };
    const patches = [];
    (db.raw.runs || []).forEach((run) => {
      if (!run.effective_model || typeof run.effective_model !== 'object') return;
      const active = !TERMINAL.includes(run.phase) || (run.recovery && run.recovery.state === 'waiting_resume');
      if (!active) return;
      const item = (db.raw.work_items || []).find((work) => work.id === run.work_item_id);
      if (!item) return;
      const next = {};
      Object.keys(run.effective_model).forEach((dept) => {
        if (!DEPT_LABELS[dept]) return;
        const target = resolve(view, item.project_id, dept);
        next[dept] = {
          definition: target.definition, connection: target.connection, protocol: target.protocol,
          source: target.source, level: target.request_level, sent_level: target.sent_level, unusable: target.problem
        };
      });
      patches.push({ path: 'runs[id=' + run.id + '].effective_model', value: next });
    });
    return patches;
  }

  function admitted(def) {
    return Boolean(def && def.admission && !def.admission_revoked);
  }

  function warningList(db, pairs) {
    if (!db.atLeast('3.2D')) return [];
    return pairs.map((pair) => imageWarning(db, pair.department, pair.definition, pair.role || null)).filter(Boolean);
  }

  function warningMessage(base, warnings) {
    if (!warnings.length) return base;
    return base + warnings.map((item) => item.text).join('');
  }

  // ---------------------------------------------------------------------------
  // 查询

  function publicDefinition(db, def) {
    const refs = referrersOf(db, [def.id]);
    const out = {
      id: def.id,
      connection_id: def.connection_id,
      upstream_model: def.upstream_model,
      window: def.window,
      max_output: def.max_output,
      image_input: Boolean(def.image_input),
      image_input_source: def.image_input_source || null,
      accepts_required_tool_call: Boolean(def.accepts_required_tool_call),
      reasoning: def.reasoning ? Y8.clone(def.reasoning) : null,
      capacity_accepted: Boolean(def.capacity_accepted),
      admission: def.admission ? Y8.clone(def.admission) : null,
      admission_revoked: def.admission_revoked ? Y8.clone(def.admission_revoked) : null,
      prefill: def.prefill || null,
      referrers: refs
    };
    return out;
  }

  function prefillFor(catalog, scheme, upstream, listed) {
    if (scheme === 'custom') {
      return { image_input: false, image_source: '自定义服务方案，预填为只有文本', window: listed && listed.window || null, window_source: listed && listed.window ? '上游模型列表' : null, max_output: listed && listed.max_output || null, output_source: listed && listed.max_output ? '上游模型列表' : null };
    }
    const table = catalog.capability_table;
    const row = table && table.models ? table.models[upstream] : null;
    const hasImage = row && Object.prototype.hasOwnProperty.call(row, 'image_input');
    const fromList = listed && (listed.window || listed.max_output);
    return {
      image_input: hasImage ? Boolean(row.image_input) : false,
      image_source: hasImage ? '能力表 ' + table.revision : '能力表中没有该模型的输入方式，预填为只有文本',
      window: (listed && listed.window) || (row && row.window) || null,
      window_source: listed && listed.window ? '上游模型列表' : (row && row.window ? '能力表 ' + table.revision : null),
      max_output: (listed && listed.max_output) || (row && row.max_output) || null,
      output_source: listed && listed.max_output ? '上游模型列表' : (row && row.max_output ? '能力表 ' + table.revision : null),
      list_preferred: Boolean(fromList)
    };
  }

  B.query('catalog', (params, db) => {
    bound = db;
    const catalog = catalogOf(db);
    const departments = DEPTS.concat(db.atLeast('S4') ? ['operations'] : []);
    const defaults = {};
    departments.forEach((dept) => {
      const entry = (catalog.department_defaults || {})[dept];
      if (!entry) return;
      const row = {
        definition: entry.definition || null,
        request_level: entry.request_level || null,
        label: entry.definition ? label(entry.definition) : '未设置',
        problem: entry.definition ? problemOf(db, entry.definition) : '未设置'
      };
      if (db.atLeast('3.2D')) row.warning = imageWarning(db, dept, entry.definition, null);
      defaults[dept] = row;
    });
    const connections = (catalog.connections || []).map((conn) => {
      const defs = (catalog.definitions || []).filter((def) => def.connection_id === conn.id).map((def) => publicDefinition(db, def));
      const cred = conn.credential_ref ? credentialOf(catalog, conn.credential_ref) : null;
      const candidates = catalog.candidates ? catalog.candidates[conn.id] || null : null;
      const listed = candidates && candidates.listed ? candidates.listed : null;
      return {
        id: conn.id, name: conn.name, scheme: conn.scheme, protocol: conn.protocol, base_url: conn.base_url,
        credential_ref: conn.credential_ref, timeout_sec: conn.timeout_sec, models_url: conn.models_url || '',
        credential: cred ? { ref: cred.ref, state: cred.state, sources: Y8.clone(cred.sources), version: cred.version, rejected: cred.rejected, note: cred.note } : null,
        admitted_count: defs.filter((def) => def.admission).length,
        candidate_count: defs.filter((def) => !def.admission).length,
        definitions: defs,
        candidates: candidates ? {
          source: candidates.source || null,
          collected_at: candidates.collected_at || null,
          ids: candidates.ids || [],
          unknown_reason: candidates.unknown_reason || null,
          phase: candidates.phase || null,
          text: candidates.text || null,
          prefill: (candidates.ids || []).map((id) => Object.assign({ id }, prefillFor(catalog, conn.scheme, id, listed && listed[id])))
        } : null,
        connection_test: catalog.connection_tests ? catalog.connection_tests[conn.id] || null : null
      };
    });
    const out = {
      revision: catalog.file.revision,
      system_revision: db.data.system.catalog_revision,
      file: Y8.clone(catalog.file),
      capability_table: {
        source: catalog.capability_table.source,
        revision: catalog.capability_table.revision,
        models: Y8.clone(catalog.capability_table.models)
      },
      presets: Y8.clone(catalog.presets),
      connections,
      credentials: (catalog.credentials || []).map((cred) => ({
        ref: cred.ref, state: cred.state, sources: Y8.clone(cred.sources), version: cred.version,
        rejected: Boolean(cred.rejected), rejected_source: cred.rejected_source || null, note: cred.note
      })),
      model_tests: Y8.clone(catalog.model_tests || {}),
      department_defaults: defaults,
      admitted: (catalog.definitions || []).filter((def) => def.admission).map((def) => ({
        id: def.id, label: label(def.id), connection_id: def.connection_id,
        connection_name: (connectionOf(catalog, def.connection_id) || {}).name || def.connection_id,
        image_input: Boolean(def.image_input), upstream_model: def.upstream_model
      }))
    };
    if (db.atLeast('S5') && catalog.role_defaults) {
      const roleDefaults = {};
      Object.keys(catalog.role_defaults).forEach((roleId) => {
        if (roleId === 'level' || roleId === 'until') return;
        const entry = catalog.role_defaults[roleId];
        if (!entry || typeof entry !== 'object' || !('definition' in entry)) return;
        let department = null;
        let roleName = roleId;
        Object.keys(catalog.role_catalog || {}).forEach((dept) => {
          if (!Array.isArray(catalog.role_catalog[dept])) return;
          const role = catalog.role_catalog[dept].find((item) => item.id === roleId);
          if (role) { department = dept; roleName = role.name; }
        });
        const row = {
          definition: entry.definition || null,
          request_level: entry.request_level || null,
          department,
          name: roleName,
          label: entry.definition ? label(entry.definition) : '未设置',
          problem: entry.definition ? problemOf(db, entry.definition) : '未设置'
        };
        if (db.atLeast('3.2D')) row.warning = imageWarning(db, department, entry.definition, roleName);
        roleDefaults[roleId] = row;
      });
      out.role_defaults = roleDefaults;
      out.role_catalog = {};
      Object.keys(catalog.role_catalog || {}).forEach((dept) => {
        if (Array.isArray(catalog.role_catalog[dept])) out.role_catalog[dept] = Y8.clone(catalog.role_catalog[dept]);
      });
    }
    return out;
  });

  function documentOf(db) {
    const catalog = catalogOf(db);
    const doc = {
      connections: (catalog.connections || []).map((conn) => ({
        id: conn.id, name: conn.name, scheme: conn.scheme, protocol: conn.protocol, base_url: conn.base_url,
        credential_ref: conn.credential_ref, timeout_sec: conn.timeout_sec, models_url: conn.models_url || '',
        definitions: (catalog.definitions || []).filter((def) => def.connection_id === conn.id).map((def) => ({
          id: def.id, upstream_model: def.upstream_model, window: def.window, max_output: def.max_output,
          image_input: Boolean(def.image_input), accepts_required_tool_call: Boolean(def.accepts_required_tool_call),
          reasoning: def.reasoning ? Y8.clone(def.reasoning) : null,
          capacity_accepted: Boolean(def.capacity_accepted)
        }))
      })),
      department_defaults: {}
    };
    DEPTS.concat(db.atLeast('S4') ? ['operations'] : []).forEach((dept) => {
      const entry = (catalog.department_defaults || {})[dept];
      const def = entry && entry.definition ? definitionOf(catalog, entry.definition) : null;
      doc.department_defaults[dept] = entry && entry.definition
        ? { connection: def ? def.connection_id : null, definition: entry.definition, request_level: entry.request_level || null }
        : null;
    });
    if (db.atLeast('S5') && catalog.role_defaults) {
      doc.role_defaults = {};
      Object.keys(catalog.role_defaults).forEach((roleId) => {
        if (roleId === 'level' || roleId === 'until') return;
        const entry = catalog.role_defaults[roleId];
        if (!entry || typeof entry !== 'object' || !('definition' in entry)) return;
        const def = entry.definition ? definitionOf(catalog, entry.definition) : null;
        doc.role_defaults[roleId] = entry.definition
          ? { connection: def ? def.connection_id : null, definition: entry.definition, request_level: entry.request_level || null }
          : null;
      });
    }
    return doc;
  }

  B.query('catalog.document', (params, db) => ({ revision: revisionOf(db), document: documentOf(db) }));

  function workTitle(db, id) {
    const item = db.workItem(id);
    const project = item ? db.project(item.project_id) : null;
    return {
      work_item_id: id,
      title: item ? item.title : id,
      project_id: item ? item.project_id : null,
      project_name: project ? project.name : null,
      status: item ? item.status : null
    };
  }

  function roleNameOf(db, roleId) {
    if (!roleId) return null;
    const groups = catalogOf(db).role_catalog || {};
    let name = null;
    Object.keys(groups).forEach((department) => {
      if (!Array.isArray(groups[department])) return;
      groups[department].forEach((role) => { if (role.id === roleId) name = role.name; });
    });
    return name;
  }

  B.query('runtime.slots', (params, db) => {
    const runtime = db.data.runtime;
    if (!runtime) throw new Error('当前档位没有执行槽位');
    const used = (runtime.slots.used || []).map((row) => {
      const info = workTitle(db, row.work_item_id);
      const run = db.runOf ? db.runOf(row.work_item_id) : (db.data.runs || []).find((item) => item.work_item_id === row.work_item_id);
      const out = Object.assign({}, info, {
        department: row.department,
        department_label: DEPT_LABELS[row.department] || row.department,
        elapsed_sec: run ? run.elapsed_sec : null,
        limit_sec: run ? run.limit_sec : null
      });
      if (db.atLeast('S5')) {
        out.role = row.role || null;
        out.role_label = roleNameOf(db, row.role);
      }
      return out;
    });
    const queue = (runtime.queue || []).slice().sort((a, b) => a.position - b.position).map((row) => Object.assign({}, workTitle(db, row.work_item_id), {
      position: row.position,
      since: row.since,
      wait_sec: row.since ? B.helpers.since(db, row.since) : null,
      upgrade_restart: Boolean(row.upgrade_restart),
      queue_reason: row.queue_reason || null
    }));
    const out = {
      version: runtime.version,
      total: runtime.slots.total,
      used,
      queue,
      restart: {
        booted_at: db.data.system.booted_at,
        note: queue.some((row) => row.upgrade_restart) ? '队列中有因升级重新开始的事项，排在最前面' : '重启后队列保持，没有因升级重新开始的事项'
      }
    };
    if (db.atLeast('3.1')) out.drain = Y8.clone(db.data.system.drain);
    if (db.atLeast('S4')) out.disk = Y8.clone(db.data.system.disk);
    if (db.atLeast('S5')) out.unit = 'role';
    return out;
  });

  B.query('tools.registry', (params, db) => {
    const tools = db.data.tools;
    if (!tools) throw new Error('当前档位没有工具登记');
    const out = {
      design_note: '设计待定',
      network: Y8.clone(tools.network),
      mcp: Y8.clone(tools.mcp),
      hooks: { note: 'Stage 6 设计' }
    };
    if (db.atLeast('3.2D') && tools.browser) out.browser = Y8.clone(tools.browser);
    if (db.atLeast('3.2D') && tools.computer_use) out.computer_use = Y8.clone(tools.computer_use);
    if (db.atLeast('S5') && tools.observers) out.observers = Y8.clone(tools.observers);
    return out;
  });

  // ---------------------------------------------------------------------------
  // 目录修改

  function isUrl(text) {
    return typeof text === 'string' && /^https?:\/\/\S+$/.test(text);
  }

  function positiveInt(value) {
    return Number.isInteger(value) && value > 0;
  }

  function slug(name, taken) {
    const base = String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'connection';
    let id = base;
    let n = 2;
    while (taken.has(id)) {
      id = base + '-' + n;
      n += 1;
    }
    return id;
  }

  function normalizeReasoning(value, path, errors) {
    if (value === null || value === undefined) return null;
    if (!Y8.isPlainObject(value)) {
      errors.push({ path, message: '推理档位声明必须是对象或 null' });
      return null;
    }
    const unknown = Object.keys(value).filter((key) => !['levels', 'default_level', 'method'].includes(key));
    unknown.forEach((key) => errors.push({ path: path + '.' + key, message: '未知字段' }));
    const levels = value.levels;
    if (!Array.isArray(levels) || !levels.length || levels.some((level) => !REASONING_LEVELS.includes(level))) {
      errors.push({ path: path + '.levels', message: '支持档位必须是档位全集中的非空列表' });
      return null;
    }
    if (!REASONING_LEVELS.includes(value.default_level) || !levels.includes(value.default_level)) {
      errors.push({ path: path + '.default_level', message: '默认档位必须属于支持档位' });
    }
    if (!REASONING_METHODS.includes(value.method)) errors.push({ path: path + '.method', message: '推理参数方式无效' });
    return { levels: REASONING_LEVELS.filter((level) => levels.includes(level)), default_level: value.default_level, method: value.method };
  }

  function checkDefinitionFields(def, path, errors, requireAccepted) {
    if (!def.upstream_model || typeof def.upstream_model !== 'string') errors.push({ path: path + '.upstream_model', message: '缺少上游模型 ID' });
    if (!positiveInt(def.window)) errors.push({ path: path + '.window', message: '窗口必须是正整数' });
    if (!positiveInt(def.max_output)) errors.push({ path: path + '.max_output', message: '输出上限必须是正整数' });
    if (positiveInt(def.window) && positiveInt(def.max_output) && def.max_output > def.window) errors.push({ path: path + '.max_output', message: '输出上限不能大于窗口' });
    if (typeof def.image_input !== 'boolean') errors.push({ path: path + '.image_input', message: '输入方式必须声明是否支持图像' });
    if (typeof def.accepts_required_tool_call !== 'boolean') errors.push({ path: path + '.accepts_required_tool_call', message: '必须声明是否接受要求调用工具' });
    if (typeof def.capacity_accepted !== 'boolean') errors.push({ path: path + '.capacity_accepted', message: '缺少容量接受标记' });
    else if (requireAccepted && def.capacity_accepted !== true) errors.push({ path: path + '.capacity_accepted', message: '窗口与输出上限在接受之前不能保存' });
    return normalizeReasoning(def.reasoning, path + '.reasoning', errors);
  }

  function sameMethod(a, b) {
    const left = a && a.method;
    const right = b && b.method;
    return left === right;
  }

  function applyDefinitionList(db, connectionId, incoming, errors) {
    const catalog = db.raw.catalog;
    const kept = [];
    const removed = [];
    const nextIds = new Set();
    incoming.forEach((raw, index) => {
      const path = 'definitions[' + index + ']';
      if (!Y8.isPlainObject(raw)) {
        errors.push({ path, message: '模型访问定义必须是对象' });
        return;
      }
      Object.keys(raw).forEach((key) => {
        if (!DOC_DEF_FIELDS.includes(key) && key !== 'connection_id') errors.push({ path: path + '.' + key, message: '未知字段' });
      });
      const reasoning = checkDefinitionFields(raw, path, errors, true);
      const id = raw.id || (connectionId + '/' + raw.upstream_model);
      if (nextIds.has(id)) errors.push({ path: path + '.id', message: '模型访问定义标识重复' });
      nextIds.add(id);
      const old = rawDefinition(db, id);
      if (old && old.connection_id !== connectionId) errors.push({ path: path + '.id', message: '这个定义属于另一份连接' });
      const invalidating = old && old.admission && (old.upstream_model !== raw.upstream_model || !sameMethod(old.reasoning, reasoning));
      kept.push({
        id,
        connection_id: connectionId,
        upstream_model: raw.upstream_model,
        window: raw.window,
        max_output: raw.max_output,
        image_input: raw.image_input,
        image_input_source: old ? old.image_input_source : (raw.image_input ? '手动改写' : '手动声明只有文本'),
        accepts_required_tool_call: raw.accepts_required_tool_call,
        reasoning,
        capacity_accepted: true,
        admission: old && old.admission && !invalidating ? old.admission : null,
        admission_revoked: invalidating ? { at: db.now, reason: '修改上游模型 ID 或推理参数方式', previous: old.admission } : (old ? old.admission_revoked : null),
        prefill: old ? old.prefill || null : null
      });
    });
    (catalog.definitions || []).filter((def) => def.connection_id === connectionId && !nextIds.has(def.id)).forEach((def) => removed.push(def.id));
    const refs = referrersOf(db, removed);
    if (refs.length) errors.push({ path: 'definitions', message: '仍被引用的定义不能移除：' + refs.map((ref) => ref.text).join('、') });
    return { kept, removed, refs };
  }

  function connectionPayload(params, id) {
    return {
      id,
      name: String(params.name || '').trim(),
      scheme: params.scheme,
      protocol: params.protocol,
      base_url: String(params.base_url || '').trim(),
      credential_ref: params.credential_ref ? String(params.credential_ref).trim() : null,
      timeout_sec: Number(params.timeout_sec),
      models_url: params.models_url ? String(params.models_url).trim() : ''
    };
  }

  function validateConnection(db, row, errors) {
    if (!row.name) errors.push({ path: 'name', message: '缺少名称' });
    if (!row.scheme || !(catalogOf(db).presets.schemes || []).some((item) => item.id === row.scheme)) errors.push({ path: 'scheme', message: '服务方案无效' });
    if (!PROTOCOLS.includes(row.protocol)) errors.push({ path: 'protocol', message: '协议无效' });
    if (!isUrl(row.base_url)) errors.push({ path: 'base_url', message: '地址必须是 http 或 https URL' });
    if (!positiveInt(row.timeout_sec)) errors.push({ path: 'timeout_sec', message: '超时必须是正整数秒' });
    if (row.models_url && !isUrl(row.models_url)) errors.push({ path: 'models_url', message: '模型列表地址必须是 http 或 https URL' });
  }

  B.command('catalog.connection.save', (params, db) => {
    const stale = needRevision(db, params);
    if (stale) return stale;
    const errors = [];
    const creating = !params.connection_id;
    const taken = new Set((db.raw.catalog.connections || []).map((item) => item.id));
    const id = creating ? slug(params.name, taken) : params.connection_id;
    const original = creating ? null : (db.raw.catalog.connections || []).find((item) => item.id === id);
    if (!creating && !original) return reject('catalog_invalid', '没有这份 Provider 配置：' + id);
    const row = connectionPayload(params, id);
    validateConnection(db, row, errors);
    const invalidating = original && (
      (original.base_url || '') !== row.base_url ||
      (original.credential_ref || '') !== (row.credential_ref || '') ||
      original.protocol !== row.protocol
    );
    let prepared = null;
    if (Array.isArray(params.definitions)) prepared = applyDefinitionList(db, id, params.definitions, errors);
    if (errors.length) return reject('catalog_invalid', errors[0].path + '：' + errors[0].message);
    const patches = bumpRevision(db);
    if (creating) {
      patches.push({ path: 'catalog.connections', push: row });
      patches.push({ path: 'catalog.candidates', put: { key: id, value: { source: null, collected_at: null, ids: [], unknown_reason: null } } });
      patches.push({ path: 'catalog.connection_tests', put: { key: id, value: null } });
    } else {
      ['name', 'scheme', 'protocol', 'base_url', 'credential_ref', 'timeout_sec', 'models_url'].forEach((key) => {
        patches.push({ path: 'catalog.connections[id=' + id + '].' + key, value: row[key] });
      });
    }
    let nextDefinitions = null;
    if (prepared || invalidating) {
      nextDefinitions = (db.raw.catalog.definitions || []).slice();
      if (prepared) {
        nextDefinitions = nextDefinitions.filter((def) => !prepared.removed.includes(def.id));
        prepared.kept.forEach((def) => {
          const index = nextDefinitions.findIndex((item) => item.id === def.id);
          if (index < 0) nextDefinitions.push(def);
          else nextDefinitions[index] = def;
        });
      }
      if (invalidating) {
        nextDefinitions = nextDefinitions.map((def) => (def.connection_id === id && def.admission
          ? Object.assign({}, def, { admission: null, admission_revoked: { at: db.now, reason: '修改地址、凭据引用或协议', previous: def.admission } })
          : def));
      }
      patches.push({ path: 'catalog.definitions', value: nextDefinitions });
    }
    const nextCatalog = Y8.clone(db.raw.catalog);
    patches.forEach((patch) => {
      if (patch.path.indexOf('system.') === 0) return;
      Y8.applyPatch(nextCatalog, Object.assign({}, patch, { path: patch.path.replace(/^catalog\./, '') }));
    });
    const events = [{
      type: 'catalog_revised',
      label: (creating ? '添加' : '保存') + ' Provider 配置「' + row.name + '」',
      payload: { connection_id: id, catalog_revision: revisionOf(db) + 1, invalidating: Boolean(invalidating) },
      patch: patches.concat(effectivePatches(db, nextCatalog))
    }];
    return { events, refs: { connection_id: id }, message: (creating ? '已添加' : '已保存') + ' Provider 配置「' + row.name + '」，从下一次模型请求起生效' };
  });

  B.command('catalog.connection.delete', (params, db) => {
    const stale = needRevision(db, params);
    if (stale) return stale;
    const id = params.connection_id;
    const conn = (db.raw.catalog.connections || []).find((item) => item.id === id);
    if (!conn) return reject('catalog_invalid', '没有这份 Provider 配置：' + id);
    const defs = (db.raw.catalog.definitions || []).filter((def) => def.connection_id === id).map((def) => def.id);
    const refs = referrersOf(db, defs);
    if (refs.length) return reject('in_use', '仍被引用：' + refs.map((ref) => ref.text).join('、'));
    const patches = bumpRevision(db);
    defs.forEach((defId) => patches.push({ path: 'catalog.definitions', remove: { key: 'id', value: defId } }));
    patches.push({ path: 'catalog.connections', remove: { key: 'id', value: id } });
    return {
      events: [{
        type: 'catalog_revised',
        label: '删除 Provider 配置「' + conn.name + '」',
        payload: { connection_id: id, removed_definitions: defs },
        patch: patches
      }],
      message: '已删除「' + conn.name + '」'
    };
  });

  function unknownKeys(obj, allowed, path, errors) {
    Object.keys(obj).forEach((key) => {
      if (!allowed.includes(key)) errors.push({ path: path ? path + '.' + key : key, message: '未知字段' });
    });
  }

  function validateDocument(db, doc) {
    const errors = [];
    if (!Y8.isPlainObject(doc)) return [{ path: '(文档)', message: '目录文档必须是对象' }];
    unknownKeys(doc, db.atLeast('S5') ? ['connections', 'department_defaults', 'role_defaults'] : ['connections', 'department_defaults'], '', errors);
    if (!Array.isArray(doc.connections)) errors.push({ path: 'connections', message: '缺少连接列表' });
    const connIds = new Set();
    const defById = {};
    (doc.connections || []).forEach((conn, index) => {
      const path = 'connections[' + index + ']';
      if (!Y8.isPlainObject(conn)) {
        errors.push({ path, message: '连接必须是对象' });
        return;
      }
      unknownKeys(conn, DOC_CONN_FIELDS, path, errors);
      if (!conn.id || connIds.has(conn.id)) errors.push({ path: path + '.id', message: '连接标识缺失或重复' });
      connIds.add(conn.id);
      validateConnection(db, connectionPayload(conn, conn.id), errors.map ? errors : errors);
      if (!Array.isArray(conn.definitions)) errors.push({ path: path + '.definitions', message: '缺少模型访问定义列表' });
      (conn.definitions || []).forEach((def, defIndex) => {
        const defPath = path + '.definitions[' + defIndex + ']';
        if (!Y8.isPlainObject(def)) {
          errors.push({ path: defPath, message: '模型访问定义必须是对象' });
          return;
        }
        unknownKeys(def, DOC_DEF_FIELDS, defPath, errors);
        const reasoning = checkDefinitionFields(def, defPath, errors, false);
        const id = def.id || (conn.id + '/' + def.upstream_model);
        if (defById[id]) errors.push({ path: defPath + '.id', message: '定义标识重复' });
        defById[id] = { connection_id: conn.id, reasoning, capacity_accepted: def.capacity_accepted === true, upstream_model: def.upstream_model };
      });
    });
    const checkRefs = (bucket, path) => {
      if (!Y8.isPlainObject(doc[bucket])) {
        errors.push({ path, message: '必须是对象' });
        return;
      }
      Object.keys(doc[bucket]).forEach((key) => {
        const entry = doc[bucket][key];
        const at = path + '.' + key;
        if (entry === null) return;
        if (!Y8.isPlainObject(entry)) {
          errors.push({ path: at, message: '必须是对象或 null' });
          return;
        }
        unknownKeys(entry, ['connection', 'definition', 'request_level'], at, errors);
        if (!entry.definition) {
          errors.push({ path: at + '.definition', message: '未设置应写 null，不能写空定义' });
          return;
        }
        const found = defById[entry.definition];
        const old = rawDefinition(db, entry.definition);
        const usable = found && found.capacity_accepted && old && old.admission && old.connection_id === entry.connection && found.connection_id === entry.connection;
        if (!usable) errors.push({ path: at + '.definition', message: '只能引用已准入、并且属于所填连接的定义' });
        if (entry.request_level && (!found || !found.reasoning || !found.reasoning.levels.includes(entry.request_level))) {
          errors.push({ path: at + '.request_level', message: '请求档位必须属于该定义声明的支持档位' });
        }
      });
    };
    if (doc.department_defaults) checkRefs('department_defaults', 'department_defaults');
    if (doc.role_defaults) checkRefs('role_defaults', 'role_defaults');
    return errors;
  }

  B.command('catalog.document.save', (params, db) => {
    const stale = needRevision(db, params);
    if (stale) return stale;
    const doc = params.document;
    const errors = validateDocument(db, doc);
    if (errors.length) return reject('catalog_invalid', errors[0].path + '：' + errors[0].message);
    const patches = bumpRevision(db);
    const nextConnections = doc.connections.map((conn) => connectionPayload(conn, conn.id));
    const nextDefinitions = [];
    doc.connections.forEach((conn) => {
      (conn.definitions || []).forEach((raw) => {
        const id = raw.id || (conn.id + '/' + raw.upstream_model);
        const old = rawDefinition(db, id);
        const reasoning = raw.reasoning ? {
          levels: REASONING_LEVELS.filter((level) => raw.reasoning.levels.includes(level)),
          default_level: raw.reasoning.default_level,
          method: raw.reasoning.method
        } : null;
        const oldConn = old ? (db.raw.catalog.connections || []).find((item) => item.id === old.connection_id) : null;
        const invalidating = old && old.admission && (
          !oldConn || oldConn.base_url !== conn.base_url || (oldConn.credential_ref || '') !== (conn.credential_ref || '') || oldConn.protocol !== conn.protocol ||
          old.upstream_model !== raw.upstream_model || !sameMethod(old.reasoning, reasoning)
        );
        nextDefinitions.push({
          id, connection_id: conn.id, upstream_model: raw.upstream_model, window: raw.window, max_output: raw.max_output,
          image_input: raw.image_input, image_input_source: old ? old.image_input_source : '目录文档',
          accepts_required_tool_call: typeof raw.accepts_required_tool_call === 'boolean' ? raw.accepts_required_tool_call : true,
          reasoning, capacity_accepted: old && old.window === raw.window && old.max_output === raw.max_output ? Boolean(old.capacity_accepted) : true,
          admission: old && old.admission && !invalidating ? old.admission : null,
          admission_revoked: invalidating ? { at: db.now, reason: '目录文档修改了受影响字段', previous: old.admission } : (old ? old.admission_revoked : null)
        });
      });
    });
    patches.push({ path: 'catalog.connections', value: nextConnections });
    patches.push({ path: 'catalog.definitions', value: nextDefinitions });
    const defaults = {};
    Object.keys(doc.department_defaults || {}).forEach((dept) => {
      const entry = doc.department_defaults[dept];
      const old = db.raw.catalog.department_defaults[dept];
      defaults[dept] = entry ? { definition: entry.definition, request_level: entry.request_level || null, level: old && old.level } : { definition: null, request_level: null, level: old && old.level };
      if (defaults[dept].level === undefined) delete defaults[dept].level;
    });
    Object.keys(db.raw.catalog.department_defaults || {}).forEach((dept) => {
      if (!defaults[dept] && db.raw.catalog.department_defaults[dept] && db.raw.catalog.department_defaults[dept].level) {
        defaults[dept] = db.raw.catalog.department_defaults[dept];
      }
    });
    patches.push({ path: 'catalog.department_defaults', value: defaults });
    if (doc.role_defaults && db.atLeast('S5')) {
      const roles = { level: 'S5' };
      Object.keys(doc.role_defaults).forEach((roleId) => {
        const entry = doc.role_defaults[roleId];
        roles[roleId] = entry ? { definition: entry.definition, request_level: entry.request_level || null } : { definition: null, request_level: null };
      });
      patches.push({ path: 'catalog.role_defaults', value: roles });
    }
    const nextCatalog = Y8.clone(db.raw.catalog);
    nextCatalog.connections = nextConnections;
    nextCatalog.definitions = nextDefinitions;
    nextCatalog.department_defaults = defaults;
    return {
      events: [{
        type: 'catalog_revised',
        label: '保存目录文档',
        payload: { catalog_revision: revisionOf(db) + 1 },
        patch: patches.concat(effectivePatches(db, nextCatalog))
      }],
      message: '已保存目录文档，从下一次模型请求起生效'
    };
  });

  B.command('catalog.reload', (params, db) => {
    const file = catalogOf(db).file;
    if (file.reload_error) return reject('catalog_invalid', '目录文件无效：' + file.reload_error);
    const patches = bumpRevision(db);
    patches.push({ path: 'catalog.file.reloaded_at', value: db.now });
    patches.push({ path: 'catalog.file.reload_error', value: null });
    return {
      events: [{
        type: 'catalog_revised',
        label: '重新读取目录文件，内容与当前目录一致',
        payload: { catalog_revision: revisionOf(db) + 1, path: file.path },
        patch: patches
      }],
      message: '已重新读取 ' + file.path
    };
  });

  function requireConnection(db, id) {
    const conn = (db.raw.catalog.connections || []).find((item) => item.id === id);
    if (!conn) return null;
    return conn;
  }

  function modelsUrlOf(db, conn) {
    if (conn.models_url) return conn.models_url;
    const scheme = (catalogOf(db).presets.schemes || []).find((item) => item.id === conn.scheme);
    return scheme ? scheme.models_url : null;
  }

  function schedule(db, build) {
    const snap = {
      catalog: Y8.clone(db.data.catalog),
      runs: Y8.clone(db.raw.runs || []),
      work_items: Y8.clone(db.raw.work_items || []),
      project_settings: Y8.clone(db.raw.project_settings || {}),
      now: db.now
    };
    setTimeout(() => Y8.backend.emit(build(snap)), 1000);
  }

  function testKeyPatch(db, bucket, id, value) {
    if (Object.prototype.hasOwnProperty.call(db.raw.catalog[bucket], id)) return { path: 'catalog.' + bucket + '.' + id, value };
    return { path: 'catalog.' + bucket, put: { key: id, value } };
  }

  B.command('catalog.connection.test', (params, db) => {
    const conn = requireConnection(db, params.connection_id);
    if (!conn) return reject('not_found', '没有这份 Provider 配置');
    if (!modelsUrlOf(db, conn)) throw new Error('连接与服务方案都没有模型列表地址，不能做连接测试');
    const started = { phase: 'started', at: db.now, ok: null, text: '测试中' };
    schedule(db, () => {
      const cred = conn.credential_ref ? credentialOf(db.data.catalog, conn.credential_ref) : null;
      let result;
      if (conn.credential_ref && (!cred || cred.state === 'missing')) result = { ok: false, text: '连接测试失败：凭据缺失：' + conn.credential_ref };
      else if (cred && cred.rejected) result = { ok: false, text: '连接测试失败：HTTP 401，凭据被上游拒绝' };
      else {
        const known = db.data.catalog.candidates[conn.id];
        result = known && known.unknown_reason
          ? { ok: false, text: '连接测试失败：' + known.unknown_reason }
          : { ok: true, text: '连接测试通过 · 412 ms' };
      }
      return {
        type: 'catalog_test_finished',
        label: result.ok ? '连接测试通过：' + conn.name : '连接测试失败：' + conn.name,
        payload: { kind: 'connection', connection_id: conn.id, phase: 'finished', ok: result.ok, text: result.text },
        patch: [{ path: 'catalog.connection_tests.' + conn.id, value: { phase: 'finished', at: db.now, ok: result.ok, text: result.text } }]
      };
    });
    return {
      events: [{
        type: 'catalog_test_finished',
        label: '开始连接测试：' + conn.name,
        payload: { kind: 'connection', connection_id: conn.id, phase: 'started' },
        patch: [testKeyPatch(db, 'connection_tests', conn.id, started)]
      }],
      message: '测试中'
    };
  });

  B.command('catalog.candidates.collect', (params, db) => {
    const conn = requireConnection(db, params.connection_id);
    if (!conn) return reject('not_found', '没有这份 Provider 配置');
    const url = params.models_url || modelsUrlOf(db, conn);
    if (!url) throw new Error('没有模型列表地址');
    schedule(db, (snap) => {
      const known = snap.catalog.candidates[conn.id];
      const failed = known && known.unknown_reason && !params.models_url;
      const table = snap.catalog.capability_table.models || {};
      const ids = failed ? [] : Object.keys(table).concat(['qwen3.6-plus', 'minimax-m2.7', 'deepseek-v4-flash']);
      const value = failed
        ? { phase: 'finished', source: url, collected_at: snap.now, ids: [], unknown_reason: known.unknown_reason, text: '候选未知' }
        : { phase: 'finished', source: url, collected_at: snap.now, ids, unknown_reason: null, text: '已采集 ' + ids.length + ' 个模型' };
      return {
        type: 'catalog_candidates_collected',
        label: failed ? '获取模型列表失败：' + conn.name : '已获取模型列表：' + conn.name,
        payload: { connection_id: conn.id, phase: 'finished', source: url, count: ids.length, unknown_reason: value.unknown_reason },
        patch: [{ path: 'catalog.candidates.' + conn.id, value }]
      };
    });
    return {
      events: [{
        type: 'catalog_candidates_collected',
        label: '开始获取模型列表：' + conn.name,
        payload: { connection_id: conn.id, phase: 'started', source: url },
        patch: [{ path: 'catalog.candidates.' + conn.id, value: { phase: 'started', source: url, collected_at: null, ids: [], unknown_reason: null, text: '测试中' } }]
      }],
      message: '测试中'
    };
  });

  B.command('catalog.model.test', (params, db) => {
    const def = rawDefinition(db, params.definition_id);
    if (!def) return reject('not_found', '没有这个模型访问定义');
    const conn = requireConnection(db, def.connection_id);
    if (!conn) return reject('not_found', '定义所属的连接不存在');
    schedule(db, (snap) => {
      const cred = conn.credential_ref ? (snap.catalog.credentials || []).find((item) => item.ref === conn.credential_ref) : null;
      let result;
      if (conn.credential_ref && (!cred || cred.state === 'missing' || cred.rejected)) {
        result = { ok: false, text: cred && cred.rejected ? '模型测试失败：凭据被上游拒绝' : '模型测试失败：凭据缺失', admission: null };
      } else if (!def.capacity_accepted) {
        result = { ok: false, text: '模型测试未写入准入：容量尚未接受', admission: null };
      } else {
        const sent = def.reasoning ? def.reasoning.default_level : null;
        result = {
          ok: true,
          text: '模型测试通过' + (sent ? '，默认档位 ' + sent : ''),
          admission: { tested_at: snap.now, actual_model: def.upstream_model, protocol: PROTOCOL_LABELS[conn.protocol] }
        };
      }
      const patch = [{ path: 'catalog.model_tests', value: Object.assign({}, snap.catalog.model_tests, { [def.id]: { phase: 'finished', at: snap.now, ok: result.ok, text: result.text } }) }];
      if (result.admission) {
        patch.push({ path: 'catalog.definitions', value: (snap.catalog.definitions || []).map((item) => (item.id === def.id ? Object.assign({}, item, { admission: result.admission, admission_revoked: null }) : item)) });
        const next = Y8.clone(snap.catalog);
        const target = next.definitions.find((item) => item.id === def.id);
        target.admission = result.admission;
        target.admission_revoked = null;
        const fake = { data: { catalog: next, project_settings: snap.project_settings }, settings: (id) => snap.project_settings[id] || null, atLeast: db.atLeast, raw: { runs: snap.runs, work_items: snap.work_items } };
        patch.push.apply(patch, effectivePatches(fake, next));
      }
      return {
        type: 'catalog_test_finished',
        label: result.ok ? '模型测试通过：' + def.upstream_model : '模型测试失败：' + def.upstream_model,
        payload: { kind: 'model', definition_id: def.id, connection_id: conn.id, phase: 'finished', ok: result.ok, text: result.text, admission: result.admission },
        patch
      };
    });
    return {
      events: [{
        type: 'catalog_test_finished',
        label: '开始模型测试：' + def.upstream_model,
        payload: { kind: 'model', definition_id: def.id, connection_id: conn.id, phase: 'started' },
        patch: [{ path: 'catalog.model_tests', value: Object.assign({}, db.raw.catalog.model_tests, { [def.id]: { phase: 'started', at: db.now, ok: null, text: '测试中' } }) }]
      }],
      message: '测试中'
    };
  });

  function saveDefaults(db, params, bucket, labelText) {
    const stale = needRevision(db, params);
    if (stale) return stale;
    const incoming = params.defaults;
    if (!Y8.isPlainObject(incoming)) throw new Error(labelText + '缺少 defaults');
    const pairs = [];
    Object.keys(incoming).forEach((key) => {
      const entry = incoming[key];
      if (entry === null) return;
      if (!Y8.isPlainObject(entry)) throw new Error(labelText + '的一项必须是对象或 null：' + key);
      if (!entry.definition) return;
      pairs.push({ key, definition: entry.definition, request_level: entry.request_level || null });
    });
    for (const pair of pairs) {
      const def = rawDefinition(db, pair.definition);
      if (!def || !def.admission) return reject('catalog_invalid', '只能选择已准入的模型访问定义：' + pair.definition);
      if (pair.request_level && (!def.reasoning || !def.reasoning.levels.includes(pair.request_level))) {
        return reject('catalog_invalid', '请求档位不属于该定义的支持档位：' + pair.request_level);
      }
    }
    const patches = bumpRevision(db);
    const warnings = [];
    Object.keys(incoming).forEach((key) => {
      const entry = incoming[key] || { definition: null, request_level: null };
      patches.push({ path: 'catalog.' + bucket + '.' + key + '.definition', value: entry.definition || null });
      patches.push({ path: 'catalog.' + bucket + '.' + key + '.request_level', value: entry.request_level || null });
    });
    const next = Y8.clone(db.raw.catalog);
    Object.keys(incoming).forEach((key) => {
      const entry = incoming[key] || { definition: null, request_level: null };
      if (!next[bucket][key]) next[bucket][key] = {};
      next[bucket][key].definition = entry.definition || null;
      next[bucket][key].request_level = entry.request_level || null;
      if (bucket === 'department_defaults' && DEPT_LABELS[key]) {
        const warning = imageWarning(db, key, entry.definition, null);
        if (warning && db.atLeast('3.2D')) warnings.push(warning);
      }
      if (bucket === 'role_defaults') {
        let department = null;
        let roleName = key;
        Object.keys(next.role_catalog || {}).forEach((dept) => {
          if (!Array.isArray(next.role_catalog[dept])) return;
          const role = next.role_catalog[dept].find((item) => item.id === key);
          if (role) { department = dept; roleName = role.name; }
        });
        const warning = imageWarning(db, department, entry.definition, roleName);
        if (warning && db.atLeast('3.2D')) warnings.push(warning);
      }
    });
    return {
      events: [{
        type: 'catalog_revised',
        label: '保存' + labelText,
        payload: { catalog_revision: revisionOf(db) + 1, warnings: warnings.map((item) => item.text) },
        patch: patches.concat(effectivePatches(db, next))
      }],
      refs: { warnings },
      message: warningMessage('已保存' + labelText + '，从下一次模型请求起生效，包括进行中的事项。', warnings)
    };
  }

  B.command('catalog.department_defaults.save', (params, db) => saveDefaults(db, params, 'department_defaults', '部门默认'));
  B.command('catalog.role_defaults.save', (params, db) => saveDefaults(db, params, 'role_defaults', '角色默认'));

  function credState(cred) {
    if (cred.sources.memory) return 'memory';
    if (cred.sources.env) return 'env';
    if (cred.sources.dotenv) return 'dotenv';
    return 'missing';
  }

  function credNote(cred) {
    const notes = { memory: '只在本进程有效', env: '宿主进程环境', dotenv: '.yudao/.env', missing: '没有任何来源' };
    return notes[cred.state] + (cred.rejected ? ' · 上游拒绝（HTTP 401）' : '');
  }

  function bumpCred(version) {
    const n = Number(String(version || '').replace(/\D/g, '')) || 0;
    return 'k' + (n + 1);
  }

  function needCred(db, ref, params) {
    const cred = (db.raw.catalog.credentials || []).find((item) => item.ref === ref);
    if (!cred) throw new Error('没有这个凭据引用：' + ref);
    if (params.base_version !== undefined && params.base_version !== null && params.base_version !== '' && String(params.base_version) !== String(cred.version)) {
      return { cred, reject: reject('stale_base', '凭据已经变化，请刷新后再保存', { current_version: cred.version }) };
    }
    return { cred, reject: null };
  }

  function writeCred(db, cred, sourceKey, on) {
    const next = Y8.clone(cred);
    next.sources[sourceKey] = on;
    next.state = credState(next);
    next.rejected = next.state !== 'missing' && next.rejected_source === next.state;
    next.version = bumpCred(cred.version);
    next.note = credNote(next);
    const patches = ['state', 'sources', 'rejected', 'version', 'note'].map((key) => ({ path: 'catalog.credentials[ref=' + cred.ref + '].' + key, value: next[key] }));
    const catalog = Y8.clone(db.raw.catalog);
    const row = catalog.credentials.find((item) => item.ref === cred.ref);
    Object.assign(row, { state: next.state, sources: next.sources, rejected: next.rejected, version: next.version, note: next.note });
    return { next, patches: patches.concat(effectivePatches(db, catalog)), catalog };
  }

  B.command('credential.set', (params, db) => {
    const ref = String(params.ref || '').trim();
    if (!ref) throw new Error('缺少凭据引用');
    if (!params.key) throw new Error('缺少 API Key');
    if (!['memory', 'dotenv'].includes(params.persist)) throw new Error('写入方式必须是 memory 或 dotenv');
    const existing = (db.raw.catalog.credentials || []).find((item) => item.ref === ref);
    if (existing) {
      const checked = needCred(db, ref, params);
      if (checked.reject) return checked.reject;
    }
    const sourceKey = params.persist === 'memory' ? 'memory' : 'dotenv';
    if (!existing) {
      const cred = { ref, state: params.persist, sources: { memory: sourceKey === 'memory', env: false, dotenv: sourceKey === 'dotenv' }, version: 'k1', rejected: false, rejected_source: null, note: params.persist === 'memory' ? '只在本进程有效' : '.yudao/.env' };
      return {
        events: [{
          type: 'credential_changed',
          label: '保存凭据引用 ' + ref,
          payload: { ref, source: cred.state, version: cred.version },
          patch: [{ path: 'catalog.credentials', push: cred }]
        }],
        message: '已保存凭据引用 ' + ref + '，Key 不进入事件'
      };
    }
    const written = writeCred(db, existing, sourceKey, true);
    return {
      events: [{
        type: 'credential_changed',
        label: '保存凭据引用 ' + ref,
        payload: { ref, source: written.next.state, version: written.next.version },
        patch: written.patches
      }],
      message: '已保存凭据引用 ' + ref + '，从下一次模型请求起生效'
    };
  });

  B.command('credential.clear_override', (params, db) => {
    const checked = needCred(db, params.ref, params);
    if (checked.reject) return checked.reject;
    const written = writeCred(db, checked.cred, 'memory', false);
    return {
      events: [{
        type: 'credential_changed',
        label: '清除凭据引用 ' + params.ref + ' 的内存覆盖',
        payload: { ref: params.ref, source: written.next.state, version: written.next.version },
        patch: written.patches
      }],
      message: '已清除内存覆盖'
    };
  });

  B.command('credential.remove_persisted', (params, db) => {
    const checked = needCred(db, params.ref, params);
    if (checked.reject) return checked.reject;
    const written = writeCred(db, checked.cred, 'dotenv', false);
    return {
      events: [{
        type: 'credential_changed',
        label: '删除凭据引用 ' + params.ref + ' 的持久凭据',
        payload: { ref: params.ref, source: written.next.state, version: written.next.version },
        patch: written.patches
      }],
      message: '已删除持久凭据'
    };
  });

  // ---------------------------------------------------------------------------
  // 机器、槽位、排空

  B.command('machine.save', (params, db) => {
    const name = String(params.name || '').trim();
    const address = String(params.address || '').trim();
    const purpose = String(params.purpose || '').trim();
    if (!name || !address || !purpose) throw new Error('登记机器需要名称、地址和用途');
    const existing = params.machine_id ? (db.raw.machines || []).find((item) => item.id === params.machine_id) : null;
    if (params.machine_id && !existing) return reject('not_found', '没有这台机器');
    if (existing && params.base_version !== undefined && params.base_version !== null && params.base_version !== '' && Number(params.base_version) !== existing.version) {
      return reject('stale_base', '机器登记已经变化', { current_version: existing.version });
    }
    const dup = (db.raw.machines || []).find((item) => item.address === address && item.id !== (existing && existing.id));
    if (dup) return reject('already_exists', '地址已被「' + dup.name + '」使用');
    if (!existing) {
      const id = 'm-' + slug(name, new Set((db.raw.machines || []).map((item) => item.id)));
      return {
        events: [{
          type: 'x_machine_saved',
          label: '登记机器「' + name + '」',
          payload: { machine_id: id, name, address, purpose },
          patch: [{ path: 'machines', push: { id, name, address, purpose, kind: 'desktop', version: 1, online: false, last_heartbeat_at: null, containers: 0, actions: [], late_receipts: [], level: '3.2C' } }]
        }],
        refs: { machine_id: id },
        message: '已登记「' + name + '」'
      };
    }
    return {
      events: [{
        type: 'x_machine_saved',
        label: '修改机器「' + name + '」',
        payload: { machine_id: existing.id, name, address, purpose },
        patch: [
          { path: 'machines[id=' + existing.id + '].name', value: name },
          { path: 'machines[id=' + existing.id + '].address', value: address },
          { path: 'machines[id=' + existing.id + '].purpose', value: purpose }
        ]
      }],
      refs: { machine_id: existing.id },
      message: '已保存「' + name + '」'
    };
  });

  B.command('runtime.set_slots', (params, db) => {
    const runtime = db.raw.runtime;
    if (!runtime) throw new Error('当前档位没有执行槽位');
    if (params.base_version !== undefined && params.base_version !== null && params.base_version !== '' && Number(params.base_version) !== runtime.version) {
      return reject('stale_base', '槽位设置已经变化', { current_version: runtime.version });
    }
    const total = Number(params.total);
    if (!Number.isInteger(total) || total < 1 || total > 8) throw new Error('执行槽位数必须是 1 到 8 的整数');
    const used = (runtime.slots.used || []).length;
    if (total < used) return reject('not_allowed', '槽位数不能少于当前占用 ' + used);
    return {
      events: [{
        type: 'x_slots_set',
        label: '执行槽位数改为 ' + total,
        payload: { total },
        patch: [{ path: 'runtime.slots.total', value: total }]
      }],
      message: '已设置执行槽位数为 ' + total
    };
  });

  B.command('queue.cancel', (params, db) => {
    const id = params.work_item_id;
    const runtime = db.raw.runtime;
    if (!runtime) throw new Error('当前档位没有执行队列');
    const row = (runtime.queue || []).find((item) => item.work_item_id === id);
    if (!row) return reject('not_found', '这个事项不在队列中');
    const item = (db.raw.work_items || []).find((work) => work.id === id);
    if (!item) return reject('not_found', '事项不存在');
    if (item.status !== 'queued') return reject('not_allowed', '这个事项当前不是排队中');
    const run = (db.raw.runs || []).find((entry) => entry.id === item.run_id);
    const patch = [
      { path: 'runtime.queue', remove: { key: 'work_item_id', value: id } },
      { path: 'work_items[id=' + id + '].status', value: 'stopped' },
      { path: 'work_items[id=' + id + '].queue_reason', value: null }
    ];
    if (run && run.phase === 'QUEUED') {
      patch.push({ path: 'runs[id=' + run.id + '].phase', value: 'DONE' });
      patch.push({ path: 'runs[id=' + run.id + '].stop_reason', value: { code: 'cancelled', text: '取消排队' } });
    }
    return {
      events: [{
        type: 'x_queue_cancelled',
        project_id: item.project_id,
        work_item_id: id,
        run_id: item.run_id,
        label: '取消排队：' + item.title,
        payload: { work_item_id: id },
        patch
      }],
      message: '已取消「' + item.title + '」的排队'
    };
  });

  function runningRuns(db) {
    return (db.data.runs || []).filter((run) => {
      const item = db.workItem(run.work_item_id);
      return item && item.status === 'in_progress' && !TERMINAL.includes(run.phase);
    });
  }

  B.command('runtime.start_drain', (params, db) => {
    const drain = db.data.system.drain;
    if (!drain) throw new Error('当前档位没有排空状态');
    if (drain.state === 'draining' || drain.state === 'forced') return reject('not_allowed', '已经在排空');
    const running = runningRuns(db).map((run) => run.id);
    return {
      events: [{
        type: 'x_drain_started',
        label: '开始排空：停止开始新事项，等正在进行的 run 结束',
        payload: { running },
        patch: [{ path: 'system.drain', value: { state: 'draining', since: db.now, running } }]
      }],
      message: '已开始排空'
    };
  });

  B.command('runtime.force_upgrade', (params, db) => {
    const drain = db.data.system.drain;
    if (!drain || drain.state !== 'draining') return reject('not_allowed', '只在排空期间可以强制升级');
    const runningIds = drain.running || [];
    const events = [{
      type: 'x_upgrade_forced',
      label: '强制升级：正在进行的 run 记为因升级停止',
      payload: { running: runningIds },
      patch: [
        { path: 'system.drain.state', value: 'forced' },
        { path: 'system.drain.running', value: [] }
      ]
    }];
    const restartedIds = new Set();
    const byProject = new Map();
    const queue = [];
    runningIds.forEach((runId, index) => {
      const run = db.run(runId) || (db.raw.runs || []).find((item) => item.id === runId);
      if (!run) throw new Error('排空列表中的 run 不存在：' + runId);
      const item = db.workItem(run.work_item_id);
      if (!item) throw new Error('run 的事项不存在：' + run.work_item_id);
      const project = db.project(item.project_id);
      const adoption = project ? B.helpers.adoptions(project).slice(-1)[0] : null;
      const newId = run.id + '-upgrade';
      restartedIds.add(item.id);
      const restarted = byProject.get(item.project_id) || [];
      restarted.push(item);
      byProject.set(item.project_id, restarted);
      const pos = restarted.length;
      events.push({
        type: 'x_run_stopped_for_upgrade',
        project_id: item.project_id,
        work_item_id: item.id,
        run_id: run.id,
        department: run.department,
        label: item.title + ' 的 run 记为因升级停止',
        payload: { stop_reason: { code: 'upgrade', text: '因升级停止' }, recovery_state: 'terminated' },
        patch: [
          { path: 'runs[id=' + run.id + '].phase', value: 'DONE' },
          { path: 'runs[id=' + run.id + '].stop_reason', value: { code: 'upgrade', text: '因升级停止' } },
          { path: 'runs[id=' + run.id + '].recovery.state', value: 'terminated' },
          { path: 'runs[id=' + run.id + '].recovery.reason', value: '因升级停止，旧 run 保留只读' },
          { path: 'work_items[id=' + item.id + '].status', value: 'stopped' }
        ]
      });
      events.push({
        type: 'run_created',
        project_id: item.project_id,
        work_item_id: item.id,
        run_id: newId,
        label: item.title + ' 用已采纳成果重新开始，排在队列最前面',
        payload: { from_adoption: adoption ? adoption.version : null, queue_pos: pos, upgrade_restart: true },
        patch: [{
          path: 'runs',
          push: {
            id: newId, work_item_id: item.id, project_id: item.project_id, phase: 'QUEUED', department: null,
            last_department: null, cycle: 0, started_at: db.now, elapsed_sec: 0, limit_sec: run.limit_sec || 7200,
            stop_reason: null, recovery: { state: 'running', reason: '因升级重新开始，排队中' }, born_at: db.now
          }
        }]
      });
      queue.push({ work_item_id: item.id, project_id: item.project_id, since: db.now, position: index + 1, upgrade_restart: true });
      events.push({
        type: 'x_queued',
        project_id: item.project_id,
        work_item_id: item.id,
        run_id: newId,
        label: item.title + ' 排在队列第 ' + pos + ' 位',
        payload: { queue_pos: pos, upgrade_restart: true },
        patch: [
          { path: 'work_items[id=' + item.id + '].status', value: 'queued' },
          { path: 'work_items[id=' + item.id + '].queue_pos', value: pos },
          { path: 'work_items[id=' + item.id + '].queue_reason', value: null },
          { path: 'work_items[id=' + item.id + '].run_id', value: newId }
        ]
      });
    });
    if (runningIds.length) {
      const tail = events[events.length - 1];
      byProject.forEach((restarted, projectId) => {
        const following = (db.raw.work_items || [])
          .filter((item) => item.project_id === projectId && item.status === 'queued' && !restartedIds.has(item.id))
          .sort((a, b) => (a.queue_pos || 0) - (b.queue_pos || 0) || String(a.id).localeCompare(String(b.id)));
        following.forEach((item, i) => {
          tail.patch.push({ path: 'work_items[id=' + item.id + '].queue_pos', value: restarted.length + i + 1 });
        });
      });
      if (db.raw.runtime) {
        const rows = (db.raw.runtime.queue || []).filter((row) => !restartedIds.has(row.work_item_id)).sort((a, b) => a.position - b.position);
        rows.forEach((row, i) => queue.push(Object.assign({}, row, { position: runningIds.length + i + 1 })));
        tail.patch.push({ path: 'runtime.queue', value: queue });
      }
    }
    return {
      events,
      message: '已强制升级，正在进行的 run 记为因升级停止'
    };
  });
})();
