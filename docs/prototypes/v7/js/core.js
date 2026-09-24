// Yudao 界面原型 v7 核心：命名空间、状态与档位、事件总线、路由、页面与查询命令注册、界面辅助函数、事件委托、浮动工具条与场景播放器
(function () {
  'use strict';

  const Y7 = {};
  window.Y7 = Y7;

  const LEVELS = ['now', 's3', 's4', 's5'];
  Y7.LEVELS = LEVELS;
  Y7.LEVEL_LABELS = { now: '当前', s3: 'Stage 3 与 D24', s4: 'Stage 4', s5: 'Stage 5' };

  // ---------------------------------------------------------------------------
  // 持久化：档位、标注、草稿、页签与来源页面保存在 sessionStorage，主题保存在 localStorage

  const session = window.sessionStorage;
  const local = window.localStorage;

  function readStored(storage, key, fallback) {
    const text = storage.getItem(key);
    return text === null ? fallback : JSON.parse(text);
  }

  function writeStored(storage, key, value) {
    storage.setItem(key, JSON.stringify(value));
  }

  // ---------------------------------------------------------------------------
  // 状态与档位

  Y7.state = {
    level: readStored(session, 'y7.level', 'now'),
    annotate: readStored(session, 'y7.annotate', false),
    route: { name: null, params: {}, query: {} },
    projectId: 'p-report',
    workItemId: null,
    drafts: readStored(session, 'y7.drafts', {}),
    scenario: { id: null, step: 0, playing: false, lastEvent: null },
    theme: readStored(local, 'y7.theme', 'system'),
    tabs: readStored(session, 'y7.tabs', {}),
    source: readStored(session, 'y7.source', null),
    lastWorkItem: readStored(session, 'y7.lastWorkItem', {}),
    drawerOpen: false,
    toolbarOpen: window.innerWidth > 760
  };

  function isStage(value) {
    return typeof value === 'string' && LEVELS.includes(value);
  }
  Y7.isStage = isStage;

  Y7.atLeast = function atLeast(level) {
    if (level === undefined || level === null || level === '') return true;
    if (!isStage(level)) throw new Error('未知档位：' + level);
    return LEVELS.indexOf(Y7.state.level) >= LEVELS.indexOf(level);
  };

  Y7.setLevel = function setLevel(level) {
    if (!isStage(level)) throw new Error('未知档位：' + level);
    if (Y7.state.level === level) return;
    Y7.state.level = level;
    writeStored(session, 'y7.level', level);
    Y7.bus.emit('level-changed', level);
  };

  Y7.setAnnotate = function setAnnotate(on) {
    Y7.state.annotate = Boolean(on);
    writeStored(session, 'y7.annotate', Y7.state.annotate);
    document.documentElement.classList.toggle('is-annotate', Y7.state.annotate);
    Y7.bus.emit('annotate-changed', Y7.state.annotate);
  };

  Y7.setTheme = function setTheme(theme) {
    if (!['system', 'light', 'dark'].includes(theme)) throw new Error('未知主题：' + theme);
    Y7.state.theme = theme;
    writeStored(local, 'y7.theme', theme);
    applyTheme();
    Y7.bus.emit('theme-changed', theme);
  };

  function applyTheme() {
    const html = document.documentElement;
    if (Y7.state.theme === 'system') delete html.dataset.theme;
    else html.dataset.theme = Y7.state.theme;
  }

  // ---------------------------------------------------------------------------
  // 事件总线

  const handlers = {};
  Y7.bus = {
    on(type, fn) {
      (handlers[type] = handlers[type] || []).push(fn);
    },
    off(type, fn) {
      handlers[type] = (handlers[type] || []).filter((item) => item !== fn);
    },
    emit(type, payload) {
      (handlers[type] || []).slice().forEach((fn) => fn(payload));
    }
  };

  // ---------------------------------------------------------------------------
  // 数据访问：档位过滤、路径读写与场景补丁

  // 这些字段在 BUILD.md 中标为某档位起出现，Y7.resolve 在档位未到时去掉它们
  const FIELD_LEVELS = { queuePos: 's3', heldReason: 's3', semanticUnits: 's4', before: 's3', after: 's3' };

  function isPlainObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function hiddenByLevel(value) {
    return isPlainObject(value) && isStage(value.level) && !Y7.atLeast(value.level);
  }

  // 返回按当前档位过滤后的深拷贝：带 level 的对象在档位未到时去掉；levels 对象中各档的覆盖值按档位合并；
  // 表示档位的 level 键不出现在结果中（推理档位同名字段保留；推理档位声明中的 levels 数组保留）
  Y7.resolve = function resolve(value) {
    if (Array.isArray(value)) return value.filter((item) => !hiddenByLevel(item)).map(resolve);
    if (!isPlainObject(value)) return value;
    const out = {};
    Object.keys(value).forEach((key) => {
      if (key === 'levels' && isPlainObject(value.levels)) return;
      if (key === 'level' && isStage(value.level)) return;
      if (FIELD_LEVELS[key] && !Y7.atLeast(FIELD_LEVELS[key])) return;
      const item = value[key];
      if (hiddenByLevel(item)) return;
      out[key] = resolve(item);
    });
    if (isPlainObject(value.levels)) {
      LEVELS.forEach((level) => {
        if (value.levels[level] && Y7.atLeast(level)) Object.assign(out, resolve(value.levels[level]));
      });
    }
    return out;
  };

  function parseSegment(segment, path) {
    const match = /^([^[\]]+)(?:\[(\w+)=([^\]]+)\])?$/.exec(segment);
    if (!match) throw new Error('路径格式无效：' + path);
    return { key: match[1], matchKey: match[2] || null, matchValue: match[3] || null };
  }

  function stepInto(container, segment, path) {
    const { key, matchKey, matchValue } = parseSegment(segment, path);
    if (container === null || typeof container !== 'object' || !(key in container)) {
      throw new Error('路径中找不到「' + key + '」：' + path);
    }
    let next = container[key];
    if (matchKey) {
      if (!Array.isArray(next)) throw new Error('「' + key + '」不是数组，不能按 ' + matchKey + ' 查找：' + path);
      next = next.find((item) => item && String(item[matchKey]) === matchValue);
      if (next === undefined) throw new Error('数组「' + key + '」中找不到 ' + matchKey + '=' + matchValue + '：' + path);
    }
    return next;
  }

  function splitPath(path) {
    if (typeof path !== 'string' || !path) throw new Error('路径必须是非空字符串');
    return path.split('.');
  }

  Y7.getPath = function getPath(path, rootObject) {
    return splitPath(path).reduce((container, segment) => stepInto(container, segment, path), rootObject || Y7.data);
  };

  // 修改已存在的字段；最后一段可以带 [id=…]，表示替换数组中的该对象
  Y7.setPath = function setPath(path, value) {
    const segments = splitPath(path);
    const last = segments.pop();
    const parent = segments.reduce((container, segment) => stepInto(container, segment, path), Y7.data);
    const { key, matchKey, matchValue } = parseSegment(last, path);
    if (parent === null || typeof parent !== 'object' || !(key in parent)) {
      throw new Error('路径中找不到「' + key + '」：' + path);
    }
    if (matchKey) {
      const list = parent[key];
      if (!Array.isArray(list)) throw new Error('「' + key + '」不是数组：' + path);
      const index = list.findIndex((item) => item && String(item[matchKey]) === matchValue);
      if (index < 0) throw new Error('数组「' + key + '」中找不到 ' + matchKey + '=' + matchValue + '：' + path);
      list[index] = value;
    } else {
      if (Array.isArray(parent) && Number(key) >= parent.length) throw new Error('数组下标越界：' + path);
      parent[key] = value;
    }
    return path;
  };

  Y7.pushPath = function pushPath(path, item) {
    const list = Y7.getPath(path);
    if (!Array.isArray(list)) throw new Error('「' + path + '」不是数组，不能追加');
    list.push(item);
    return path;
  };

  Y7.removeFromPath = function removeFromPath(path, matchKey, matchValue) {
    const list = Y7.getPath(path);
    if (!Array.isArray(list)) throw new Error('「' + path + '」不是数组，不能删除');
    const index = list.findIndex((item) => item && String(item[matchKey]) === String(matchValue));
    if (index < 0) throw new Error('数组「' + path + '」中找不到 ' + matchKey + '=' + matchValue);
    list.splice(index, 1);
    return path;
  };

  // 场景补丁：{ path, value } 修改字段；{ path, push } 追加到数组；{ path, remove: { key, value } } 从数组删除
  Y7.applyPatch = function applyPatch(patch) {
    if ('push' in patch) return Y7.pushPath(patch.path, Y7.clone(patch.push));
    if ('remove' in patch) return Y7.removeFromPath(patch.path, patch.remove.key, patch.remove.value);
    if (!('value' in patch)) throw new Error('补丁缺少 value、push 或 remove：' + patch.path);
    return Y7.setPath(patch.path, Y7.clone(patch.value));
  };

  Y7.clone = function clone(value) {
    return value === undefined ? undefined : structuredClone(value);
  };

  let idCounter = 0;
  Y7.uid = function uid(prefix) {
    idCounter += 1;
    return prefix + '-' + Date.now().toString(36).slice(-4) + idCounter;
  };

  function rawList(name) {
    const list = Y7.data[name];
    if (!Array.isArray(list)) throw new Error('示例数据缺少数组：' + name);
    return list;
  }

  Y7.raw = {
    project: (id) => rawList('projects').find((item) => item.id === id) || null,
    workItem: (id) => rawList('workItems').find((item) => item.id === id) || null,
    run: (id) => rawList('runs').find((item) => item.id === id) || null,
    runOf: (workItemId) => {
      const item = Y7.raw.workItem(workItemId);
      return item && item.runId ? Y7.raw.run(item.runId) : null;
    }
  };

  function resolvedOrNull(item) {
    if (!item || hiddenByLevel(item)) return null;
    return Y7.resolve(item);
  }

  // 按当前档位过滤后的对象；档位未到或不存在时为 null
  Y7.project = (id) => resolvedOrNull(Y7.raw.project(id));
  Y7.workItem = (id) => resolvedOrNull(Y7.raw.workItem(id));
  Y7.run = (id) => resolvedOrNull(Y7.raw.run(id));
  Y7.runOf = (workItemId) => {
    const item = Y7.workItem(workItemId);
    return item && item.runId ? Y7.run(item.runId) : null;
  };
  Y7.workItemsOf = (projectId) => Y7.resolve(rawList('workItems').filter((item) => item.projectId === projectId));

  // ---------------------------------------------------------------------------
  // 共用的名称与说明

  Y7.DEPARTMENTS = [
    { id: 'product', label: '产品', duty: '维护原始意图与有效规范，回答需求咨询' },
    { id: 'engineering', label: '工程', duty: '依据有效规范设计、实现、自测并提交交付' },
    { id: 'quality', label: '质检', duty: '在独立副本中验证交付，给出缺陷或放行' },
    { id: 'operations', label: '运维', duty: '接收交付物的运行责任，处理运行问题', level: 's5' }
  ];
  Y7.DEPT_LABELS = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  Y7.deptLabel = (id) => {
    if (!(id in Y7.DEPT_LABELS)) throw new Error('未知部门：' + id);
    return Y7.DEPT_LABELS[id];
  };
  Y7.departments = () => Y7.DEPARTMENTS.filter((item) => Y7.atLeast(item.level));

  // 部门的内置默认 Prompt（版本 0）原文；运维部门从 Stage 5 起才有
  Y7.defaultPrompt = function defaultPrompt(department) {
    const dept = Y7.DEPARTMENTS.find((item) => item.id === department);
    if (!dept) throw new Error('未知部门：' + department);
    if (!Y7.atLeast(dept.level)) throw new Error(Y7.deptLabel(department) + '部门从「' + Y7.LEVEL_LABELS[dept.level] + '」档起才有内置默认 Prompt');
    const text = Y7.data.defaultPrompts[department];
    if (typeof text !== 'string') throw new Error('示例数据缺少内置默认 Prompt：' + department);
    return text;
  };

  Y7.PHASE_LABELS = {
    PRODUCT_SPEC: '产品处理中', ENGINEERING: '工程处理中', DELIVERY: '工程交付中', QUALITY: '质检处理中',
    REWORK_PRODUCT: '返工 · 产品', REWORK_ENGINEERING: '返工 · 工程', DONE: '已完成', PAUSED: '已暂停', FAILED: '执行失败'
  };
  Y7.TERMINAL_PHASES = ['DONE', 'PAUSED', 'FAILED'];

  Y7.WORK_STATUS = {
    not_started: '未开始', queued: '排队中', in_progress: '进行中', adopted: '已采纳',
    held: '基线已变', released_unsettled: '已放行', stopped: '已停止'
  };

  Y7.RECOVERY_LABELS = {
    running: '运行中', interrupted: '中断', pending_verification: '待核实', waiting_resume: '待恢复', terminated: '已终止'
  };
  Y7.RECOVERY_KIND = {
    running: 'running', interrupted: 'interrupted', pending_verification: 'pending', waiting_resume: 'waiting', terminated: 'done'
  };
  Y7.ACTION_STATE_LABELS = { not_sent: '未发送', done: '已完成', unknown: '结果未知' };
  Y7.FLOW_KIND_LABELS = {
    handoff: '需求交接', delivery: '版本交付', defect: '问题反馈', ask: '咨询', answer: '回答', rework: '返工',
    release: '放行', adopt: '采纳', held: '未采纳候选'
  };
  Y7.GUIDANCE_LABELS = {
    received: '已接收', in_input: '已进入模型输入', explained: '已解释', completed: '动作已核实', declined: '已说明边界', needs_work: '需要后续处理'
  };
  Y7.INPUT_PROGRESS_LABELS = { received: '已接收', assigned: '已交给产品处理', accepted: '已由有效需求接纳' };
  Y7.ATTEMPT_LABELS = { preparing: '准备中', requesting: '请求中', running: '进行中', succeeded: '成功', failed: '失败', cancelled: '已取消' };
  Y7.ROLE_STATUS_LABELS = { idle: '空闲', assigned: '已分派', working: '进行中', returned: '已交回', failed: '失败', away: '外出查资料' };
  Y7.PROTOCOL_LABELS = {
    responses: 'Responses', chat: 'Chat Completions', messages: 'Anthropic Messages', decision: '决策模型协议'
  };
  Y7.REASONING_LEVELS = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];

  // 事项在界面上的状态标记：s3 起恢复观察状态优先
  Y7.workItemStatus = function workItemStatus(item, run) {
    if (!item) throw new Error('workItemStatus 需要事项');
    const recovery = run && run.recovery && Y7.atLeast('s3') ? run.recovery : null;
    if (recovery && ['interrupted', 'pending_verification', 'waiting_resume'].includes(recovery.state)) {
      return { kind: Y7.RECOVERY_KIND[recovery.state], text: Y7.RECOVERY_LABELS[recovery.state] };
    }
    switch (item.status) {
      case 'queued': return { kind: 'queued', text: item.queuePos ? '排队中 · 第 ' + item.queuePos + ' 位' : '排队中' };
      case 'in_progress': {
        const asking = run && (run.requests || []).some((request) => request.status === 'open');
        return asking ? { kind: 'asking', text: '咨询待回应' } : { kind: 'running', text: '进行中' };
      }
      case 'adopted': return { kind: 'adopted', text: '已采纳' };
      case 'held': return Y7.atLeast('s3') ? { kind: 'held', text: '未采纳候选' } : { kind: 'held', text: '基线已变' };
      case 'released_unsettled': return { kind: 'released', text: '已放行' };
      case 'not_started': return { kind: 'idle', text: '未开始' };
      case 'stopped': {
        const code = run && run.stopReason ? run.stopReason.code : null;
        if (code === 'cancelled') return { kind: 'cancelled', text: '已停止 · 已取消' };
        if (run && run.phase === 'PAUSED') return { kind: 'paused', text: '已停止 · 已暂停' };
        return { kind: 'failed', text: '已停止 · 执行失败' };
      }
      default: throw new Error('未知事项状态：' + item.status);
    }
  };

  // ---------------------------------------------------------------------------
  // 模型选择的解析（D24 第 5.3 节）：项目部门设置优先，其次部门默认；检查引用、准入、窗口与凭据

  Y7.model = {
    definition(id) {
      return Y7.data.catalog.definitions.find((item) => item.id === id) || null;
    },
    connection(id) {
      return Y7.data.catalog.connections.find((item) => item.id === id) || null;
    },
    credential(ref) {
      return Y7.data.catalog.credentials.find((item) => item.ref === ref) || null;
    },
    // 显示用名称：「上游模型 · Provider 配置名称」
    label(definitionId) {
      if (!definitionId) return '未设置';
      const def = Y7.model.definition(definitionId);
      if (!def) return definitionId + '（定义已移除）';
      const conn = Y7.model.connection(def.connectionId);
      return def.upstreamModel + ' · ' + (conn ? conn.name : def.connectionId);
    },
    // 第 7.3 节：取不高于请求档位的最高支持档位；没有时取最低支持档位；没有声明时不发送
    clampLevel(requested, reasoning) {
      if (!reasoning || !reasoning.levels || reasoning.levels.length === 0) return null;
      const wanted = requested || reasoning.defaultLevel;
      const order = Y7.REASONING_LEVELS;
      const supported = reasoning.levels.slice().sort((a, b) => order.indexOf(a) - order.indexOf(b));
      const below = supported.filter((item) => order.indexOf(item) <= order.indexOf(wanted));
      return below.length ? below[below.length - 1] : supported[0];
    },
    // 检查一个定义能否使用；返回问题说明或 null
    problemOf(definitionId) {
      const def = Y7.model.definition(definitionId);
      if (!def) return '定义被移除';
      if (!def.admission) return def.admissionRevoked ? '准入已作废' : '尚未准入';
      if (!def.window) return '窗口未知';
      const conn = Y7.model.connection(def.connectionId);
      if (!conn) return '定义被移除';
      if (conn.credentialRef) {
        const cred = Y7.model.credential(conn.credentialRef);
        if (!cred || cred.state === 'missing') return '凭据缺失：' + conn.credentialRef;
        if (cred.rejected) return '凭据被上游拒绝：' + conn.credentialRef;
      }
      return null;
    },
    // 按层次取得选择：layers 为 [[来源, 设置项, 模型字段名], …]，模型与请求档位分别取第一个写入了的层
    pick(layers) {
      const modelLayer = layers.find((layer) => layer[1] && layer[1][layer[2]]);
      const levelLayer = layers.find((layer) => layer[1] && layer[1].level);
      const target = Y7.model.targetOf(
        modelLayer ? modelLayer[1][modelLayer[2]] : null,
        modelLayer ? modelLayer[0] : null,
        levelLayer ? levelLayer[1].level : null
      );
      target.levelSource = levelLayer ? levelLayer[0] : null;
      return target;
    },
    // 由选择得到调用目标的公开部分，或无法使用的具体原因
    targetOf(definitionId, source, requestLevel) {
      if (!definitionId) {
        return { ok: false, definition: null, model: null, connection: null, connectionName: null, protocol: null, source: null, requestLevel, sentLevel: null, problem: '未设置' };
      }
      const def = Y7.model.definition(definitionId);
      const problem = Y7.model.problemOf(definitionId);
      const conn = def ? Y7.model.connection(def.connectionId) : null;
      return {
        ok: !problem,
        definition: definitionId,
        model: def ? def.upstreamModel : null,
        connection: conn ? conn.id : null,
        connectionName: conn ? conn.name : null,
        protocol: conn ? Y7.PROTOCOL_LABELS[conn.protocol] : null,
        source,
        requestLevel,
        sentLevel: def ? Y7.model.clampLevel(requestLevel, def.reasoning) : null,
        problem
      };
    },
    // 某项目某部门的选择与调用目标（D24 第 5.3 节）：项目部门设置、部门默认
    resolve(projectId, department) {
      const catalog = Y7.resolve(Y7.data.catalog);
      const settings = projectId && Y7.data.projectSettings[projectId] ? Y7.data.projectSettings[projectId].departments[department] || null : null;
      const deptDefault = catalog.departmentDefaults[department] || null;
      return Y7.model.pick([
        ['项目设置', settings, 'model'],
        ['部门默认', deptDefault, 'definition']
      ]);
    },
    // 某项目某部门某角色的选择与调用目标（多角色草案第 12 节）：项目角色设置、角色默认、项目部门设置、部门默认。
    // 返回值与 resolve 相同，另有 roleId、levelSource、角色 Prompt 与来源；Stage 4 之前角色层不存在，按部门解析
    resolveRole(projectId, department, roleId) {
      const roles = Y7.data.catalog.roleCatalog[department] || [];
      if (!roles.some((role) => role.id === roleId)) throw new Error('部门「' + department + '」没有角色：' + roleId);
      const catalog = Y7.resolve(Y7.data.catalog);
      const project = projectId && Y7.data.projectSettings[projectId] ? Y7.resolve(Y7.data.projectSettings[projectId]) : null;
      const roleList = project && project.roles && Array.isArray(project.roles[department]) ? project.roles[department] : [];
      const roleSetting = roleList.find((entry) => entry.roleId === roleId) || null;
      const roleDefault = catalog.roleDefaults ? catalog.roleDefaults[roleId] || null : null;
      const deptSetting = project ? project.departments[department] || null : null;
      const deptDefault = catalog.departmentDefaults[department] || null;
      const target = Y7.model.pick([
        ['项目角色设置', roleSetting, 'model'],
        ['角色默认', roleDefault, 'definition'],
        ['项目设置', deptSetting, 'model'],
        ['部门默认', deptDefault, 'definition']
      ]);
      target.roleId = roleId;
      target.promptText = roleSetting && roleSetting.promptText ? roleSetting.promptText : null;
      target.promptSource = target.promptText ? '项目角色设置' : '内置角色 Prompt';
      return target;
    },
    // 目录或设置修改后，未结束的 run 的生效模型按新的选择重新解析（从下一次模型请求起生效）
    refreshRuns() {
      const paths = [];
      rawList('runs').forEach((run) => {
        const item = Y7.raw.workItem(run.workItemId);
        if (!item || !run.effectiveModel) return;
        const active = !Y7.TERMINAL_PHASES.includes(run.phase) || (run.recovery && run.recovery.state === 'waiting_resume');
        if (!active) return;
        Object.keys(run.effectiveModel).forEach((dept) => {
          if (!(dept in Y7.DEPT_LABELS)) return;
          const target = Y7.model.resolve(item.projectId, dept);
          run.effectiveModel[dept] = {
            definition: target.definition, connection: target.connection, protocol: target.protocol,
            source: target.source, level: target.requestLevel, sentLevel: target.sentLevel, unusable: target.problem
          };
        });
        paths.push('runs[id=' + run.id + '].effectiveModel');
      });
      return paths;
    },
    // 目录、凭据、部门默认或项目部门设置修改后调用：刷新生效模型，并重新判断待恢复事项
    afterChange() {
      return Y7.model.refreshRuns().concat(Y7.model.reevaluateRecovery());
    },
    // 目录或设置修改后，服务端重新判断待恢复事项能否继续执行（模型引用无法使用的情况）
    reevaluateRecovery() {
      const paths = [];
      rawList('runs').forEach((run) => {
        const recovery = run.recovery;
        if (!recovery || recovery.state !== 'waiting_resume' || !recovery.unusable) return;
        const item = Y7.raw.workItem(run.workItemId);
        const target = Y7.model.resolve(item.projectId, recovery.unusable.department);
        recovery.canResume = target.ok;
        recovery.resumeBlockedReason = target.ok ? null : '原因尚未修复：' + Y7.deptLabel(recovery.unusable.department) + '部门的 ' + (target.model || '模型') + ' ' + target.problem;
        paths.push('runs[id=' + run.id + '].recovery');
      });
      return paths;
    }
  };

  // ---------------------------------------------------------------------------
  // 执行槽位（3.4A）：槽位空出时排队中的第一个事项取得槽位

  Y7.runtime = {
    // 当前档位生效的槽位：总数可能在 levels 中覆盖，占用中带档位的条目按档位过滤
    slots() {
      const slots = Y7.resolve(Y7.data.runtime.slots);
      return { total: slots.total, used: slots.used };
    },
    fill() {
      const runtime = Y7.data.runtime;
      const paths = [];
      while (runtime.queue.length && Y7.runtime.slots().used.length < Y7.runtime.slots().total) {
        const next = runtime.queue.shift();
        const item = Y7.raw.workItem(next.workItemId);
        const run = Y7.raw.run(item.runId);
        setWorkItemStatus(item, 'in_progress');
        Y7.setEffective(item, 'queuePos', null);
        run.phase = 'PRODUCT_SPEC';
        run.department = 'product';
        run.cycle = Math.max(run.cycle, 1);
        run.startedAt = Y7.data.now;
        runtime.slots.used.push({ workItemId: item.id, department: 'product', role: null });
        paths.push('workItems[id=' + item.id + ']', 'runs[id=' + run.id + ']');
      }
      runtime.queue.forEach((entry, index) => {
        entry.position = index + 1;
        Y7.setEffective(Y7.raw.workItem(entry.workItemId), 'queuePos', index + 1);
      });
      paths.push('runtime');
      return paths;
    },
    release(workItemId) {
      const runtime = Y7.data.runtime;
      runtime.slots.used = runtime.slots.used.filter((entry) => entry.workItemId !== workItemId);
      runtime.queue = runtime.queue.filter((entry) => entry.workItemId !== workItemId);
      return Y7.runtime.fill();
    }
  };

  // 字段可能写在 levels 的覆盖值中（例如 s3 起为排队中），修改时同时改写各档位的覆盖值，使任何档位看到的都是新值
  Y7.setEffective = function setEffective(obj, key, value) {
    obj[key] = value;
    if (key !== 'levels' && isPlainObject(obj.levels)) {
      LEVELS.forEach((level) => {
        if (obj.levels[level] && key in obj.levels[level]) obj.levels[level][key] = value;
      });
    }
  };

  function setWorkItemStatus(item, status) {
    Y7.setEffective(item, 'status', status);
  }
  Y7.setWorkItemStatus = setWorkItemStatus;

  // ---------------------------------------------------------------------------
  // 页面、查询、命令与界面动作的注册

  const views = {};
  Y7.views = {
    register(name, view) {
      if (views[name]) throw new Error('页面重复注册：' + name);
      if (!view || typeof view.render !== 'function') throw new Error('页面缺少 render：' + name);
      views[name] = view;
    },
    get(name) {
      return views[name] || null;
    },
    names() {
      return Object.keys(views);
    }
  };

  const queries = {};
  Y7.queries = {
    register(name, fn) {
      if (queries[name]) throw new Error('查询重复注册：' + name);
      queries[name] = fn;
    },
    has(name) {
      return Boolean(queries[name]);
    }
  };
  Y7.query = function query(name, params) {
    const fn = queries[name];
    if (!fn) throw new Error('查询未注册：' + name);
    return fn(params || {});
  };

  const commands = {};
  Y7.commands = {
    register(name, fn) {
      if (commands[name]) throw new Error('命令重复注册：' + name);
      commands[name] = fn;
    },
    has(name) {
      return Boolean(commands[name]);
    }
  };
  Y7.command = function command(name, params) {
    const fn = commands[name];
    if (!fn) throw new Error('命令未注册：' + name);
    const result = fn(params || {});
    if (!result || typeof result.ok !== 'boolean') throw new Error('命令 ' + name + ' 没有返回 { ok, message, paths }');
    if (result.ok && result.paths && result.paths.length) Y7.bus.emit('data-changed', result.paths);
    if (result.message) Y7.ui.toast(result.message, result.ok ? 'ok' : 'warn');
    return result;
  };

  const actions = {};
  Y7.actions = {
    register(name, fn) {
      if (actions[name]) throw new Error('界面动作重复注册：' + name);
      actions[name] = fn;
    },
    run(name, el, ev) {
      const fn = actions[name];
      if (!fn) throw new Error('界面动作未注册：' + name);
      return fn(el, ev);
    }
  };

  // ---------------------------------------------------------------------------
  // 草稿：带 data-draft="键" 的输入框自动保存草稿，重新渲染后恢复

  Y7.draft = (key) => (key in Y7.state.drafts ? Y7.state.drafts[key] : '');
  Y7.setDraft = function setDraft(key, value) {
    if (value === '' || value === null || value === undefined) delete Y7.state.drafts[key];
    else Y7.state.drafts[key] = value;
    writeStored(session, 'y7.drafts', Y7.state.drafts);
  };
  Y7.clearDraft = (key) => Y7.setDraft(key, '');

  function restoreDrafts(scope) {
    scope.querySelectorAll('[data-draft]').forEach((el) => {
      const key = el.dataset.draft;
      if (key in Y7.state.drafts) el.value = Y7.state.drafts[key];
    });
  }
  Y7.restoreDrafts = restoreDrafts;

  // ---------------------------------------------------------------------------
  // 路由

  const SYS_PAGES = { models: 'sys-models', runtime: 'sys-runtime', tools: 'sys-tools', meta: 'sys-meta' };
  const RESERVED = ['nodes', 'evolution', 'lessons'];
  const PROJECT_PAGES = ['overview', 'materials', 'observe', 'settings'];

  function parseHash(hash) {
    const text = (hash || '').replace(/^#/, '');
    const questionMark = text.indexOf('?');
    const pathPart = questionMark >= 0 ? text.slice(0, questionMark) : text;
    const queryPart = questionMark >= 0 ? text.slice(questionMark + 1) : '';
    const query = Object.fromEntries(new URLSearchParams(queryPart));
    const seg = pathPart.split('/').filter(Boolean).map(decodeURIComponent);
    const route = { name: 'not-found', params: {}, query, hash: '#' + text };
    if (seg[0] === 'p' && seg[1]) {
      const projectId = seg[1];
      if (seg.length === 3 && PROJECT_PAGES.includes(seg[2])) {
        route.name = seg[2];
        route.params = { projectId };
      } else if (seg[2] === 'dept' && seg[3] && seg.length === 4) {
        route.name = 'dept';
        route.params = { projectId, department: seg[3], dept: seg[3] };
      } else if (seg[2] === 'w' && seg[3] && seg[4] === 'recovery' && seg.length === 5) {
        route.name = 'recovery';
        route.params = { projectId, workItemId: seg[3] };
      } else if (seg[2] === 'observe' && seg[3] && seg.length === 4) {
        route.name = 'observe-detail';
        route.params = { projectId, attemptId: seg[3], attempt: seg[3] };
      }
    } else if (seg[0] === 'sys' && seg.length === 2) {
      if (SYS_PAGES[seg[1]]) route.name = SYS_PAGES[seg[1]];
      else if (RESERVED.includes(seg[1])) {
        route.name = 'sys-reserved';
        route.params = { which: seg[1] };
      }
    } else if (seg[0] === 'gallery' && seg.length === 1) {
      route.name = 'gallery';
    }
    return route;
  }
  Y7.parseHash = parseHash;

  Y7.isSystemRoute = (name) => typeof name === 'string' && name.startsWith('sys-');

  function scopeQuery(workItemId) {
    return workItemId ? '?w=' + encodeURIComponent(workItemId) : '';
  }

  Y7.paths = {
    overview: (projectId, workItemId) => '#/p/' + projectId + '/overview' + scopeQuery(workItemId),
    dept: (projectId, department, workItemId) => '#/p/' + projectId + '/dept/' + department + scopeQuery(workItemId),
    recovery: (projectId, workItemId) => '#/p/' + projectId + '/w/' + workItemId + '/recovery',
    materials: (projectId, workItemId) => '#/p/' + projectId + '/materials' + scopeQuery(workItemId),
    observe: (projectId, workItemId) => '#/p/' + projectId + '/observe' + scopeQuery(workItemId),
    observeDetail: (projectId, attemptId, workItemId) => '#/p/' + projectId + '/observe/' + attemptId + scopeQuery(workItemId),
    settings: (projectId) => '#/p/' + projectId + '/settings',
    sys: (which) => '#/sys/' + which,
    gallery: () => '#/gallery'
  };

  // 同一页面换一个事项范围
  Y7.withScope = function withScope(route, workItemId) {
    const p = route.params;
    switch (route.name) {
      case 'overview': return Y7.paths.overview(p.projectId, workItemId);
      case 'dept': return Y7.paths.dept(p.projectId, p.department, workItemId);
      case 'recovery': return workItemId ? Y7.paths.recovery(p.projectId, workItemId) : Y7.paths.overview(p.projectId, null);
      case 'materials': return Y7.paths.materials(p.projectId, workItemId);
      case 'observe': return Y7.paths.observe(p.projectId, workItemId);
      case 'observe-detail': return Y7.paths.observe(p.projectId, workItemId);
      case 'settings': return Y7.paths.overview(p.projectId, workItemId);
      default: return Y7.paths.overview(Y7.state.projectId, workItemId);
    }
  };

  Y7.go = function go(hash) {
    if (typeof hash !== 'string' || !hash.startsWith('#/')) throw new Error('跳转路径无效：' + hash);
    Y7.state.drawerOpen = false;
    if (location.hash === hash) handleRoute();
    else location.hash = hash;
  };

  Y7.back = function back() {
    const target = Y7.state.source || Y7.paths.overview(Y7.state.projectId, Y7.state.lastWorkItem[Y7.state.projectId] || null);
    Y7.go(target);
  };

  Y7.router = {
    current: () => Y7.state.route,
    parse: parseHash
  };

  let lastHash = null;

  function handleRoute() {
    const route = parseHash(location.hash);
    const previous = Y7.state.route;
    if (Y7.isSystemRoute(route.name) && previous.name && !Y7.isSystemRoute(previous.name) && lastHash) {
      Y7.state.source = lastHash;
      writeStored(session, 'y7.source', Y7.state.source);
    }
    if (route.params.projectId) {
      Y7.state.projectId = route.params.projectId;
      Y7.state.workItemId = route.params.workItemId || route.query.w || null;
      Y7.state.lastWorkItem[route.params.projectId] = Y7.state.workItemId;
      writeStored(session, 'y7.lastWorkItem', Y7.state.lastWorkItem);
    }
    const sameRoute = previous.hash === route.hash;
    Y7.state.route = route;
    lastHash = route.hash;
    Y7.state.drawerOpen = false;
    renderAll(sameRoute);
    Y7.bus.emit('route-changed', route);
  }

  // ---------------------------------------------------------------------------
  // 渲染

  const dom = {};
  let mounted = null;

  function buildCtx() {
    const route = Y7.state.route;
    const project = Y7.project(Y7.state.projectId);
    let workItem = Y7.state.workItemId ? Y7.workItem(Y7.state.workItemId) : null;
    if (workItem && project && workItem.projectId !== project.id) workItem = null;
    const run = workItem && workItem.runId ? Y7.run(workItem.runId) : null;
    return {
      state: Y7.state,
      route,
      project,
      workItem,
      run,
      level: Y7.state.level,
      department: route.params.department || null
    };
  }
  Y7.ctx = buildCtx;

  const VIEW_FILES = {
    overview: 'js/views/overview.js', dept: 'js/views/department.js', recovery: 'js/views/recovery.js',
    materials: 'js/views/materials.js', observe: 'js/views/observe.js', 'observe-detail': 'js/views/observe.js',
    settings: 'js/views/settings.js', gallery: 'js/views/gallery.js'
  };

  // 页面需要的档位未到、对象不在当前档位、路径无效时显示的说明；返回 null 表示可以渲染页面
  function gateFor(ctx) {
    const route = ctx.route;
    if (route.name === 'not-found') {
      return gateHtml('找不到这个页面', '路径「' + Y7.esc(route.hash) + '」不对应任何页面。', null);
    }
    if (route.params.projectId) {
      const raw = Y7.raw.project(route.params.projectId);
      if (!raw) return gateHtml('找不到项目', '示例数据中没有项目「' + Y7.esc(route.params.projectId) + '」。', null);
      if (!ctx.project) return gateHtml('项目「' + Y7.esc(raw.name) + '」从「' + Y7.LEVEL_LABELS[raw.level] + '」档开始出现', '切换档位后查看这个项目。', raw.level);
    }
    const workItemId = route.params.workItemId || route.query.w || null;
    if (workItemId) {
      const rawItem = Y7.raw.workItem(workItemId);
      if (!rawItem) return gateHtml('找不到事项', '示例数据中没有事项「' + Y7.esc(workItemId) + '」。', null);
      if (!ctx.workItem) {
        if (rawItem.projectId !== route.params.projectId) return gateHtml('事项不属于这个项目', '事项「' + Y7.esc(rawItem.title) + '」属于另一个项目。', null);
        return gateHtml('事项「' + Y7.esc(rawItem.title) + '」从「' + Y7.LEVEL_LABELS[rawItem.level] + '」档开始出现', '切换档位后查看这个事项。', rawItem.level);
      }
    }
    if (route.name === 'dept') {
      const dept = Y7.DEPARTMENTS.find((item) => item.id === route.params.department);
      if (!dept) return gateHtml('找不到部门', '部门「' + Y7.esc(route.params.department) + '」不存在。', null);
      if (!Y7.atLeast(dept.level)) return gateHtml('运维部门从「' + Y7.LEVEL_LABELS[dept.level] + '」档开始出现', '运维部门工作间属于 Stage 5。', dept.level);
    }
    const view = views[route.name];
    if (view && view.level && !Y7.atLeast(view.level)) {
      const title = typeof view.title === 'function' ? view.title(ctx) : route.name;
      return gateHtml('「' + Y7.esc(title) + '」从「' + Y7.LEVEL_LABELS[view.level] + '」档开始出现', view.gateText ? Y7.esc(view.gateText) : '当前档位只显示已实现的能力。', view.level);
    }
    return null;
  }

  function gateHtml(title, text, level) {
    const homeProject = Y7.project(Y7.state.projectId) ? Y7.state.projectId : 'p-report';
    const button = level
      ? '<button class="y7-btn primary" data-act="core.level" data-level="' + level + '">切换到「' + Y7.LEVEL_LABELS[level] + '」档</button>'
      : '<button class="y7-btn" data-go="' + Y7.paths.overview(homeProject) + '">回到项目概览</button>';
    return '<div class="y7-gate"><div class="y7-gate-card"><h1>' + title + '</h1><p>' + text + '</p><div class="y7-row">' + button + '</div></div></div>';
  }

  function unmountCurrent() {
    if (mounted && mounted.view && mounted.view.unmount) mounted.view.unmount(mounted.ctx, dom.content);
    mounted = null;
  }

  function renderShell() {
    if (!Y7.shell || typeof Y7.shell.render !== 'function') throw new Error('外壳未注册：js/views/shell.js 需要定义 Y7.shell.render');
    Y7.shell.render(buildCtx());
    document.body.classList.toggle('is-drawer-open', Y7.state.drawerOpen);
  }
  Y7.renderShell = renderShell;

  function renderContent(keepScroll) {
    const ctx = buildCtx();
    const scrollY = window.scrollY;
    unmountCurrent();
    const gate = gateFor(ctx);
    dom.content.dataset.view = ctx.route.name;
    if (gate) {
      dom.content.innerHTML = gate;
      mounted = { name: ctx.route.name, view: null, ctx };
      window.scrollTo(0, 0);
      return;
    }
    const view = views[ctx.route.name];
    if (!view) {
      const file = VIEW_FILES[ctx.route.name] || '对应的页面文件';
      dom.content.innerHTML = gateHtml('页面尚未注册', '页面「' + Y7.esc(ctx.route.name) + '」由 ' + Y7.esc(file) + ' 提供，这个文件还没有注册它。', null);
      mounted = { name: ctx.route.name, view: null, ctx };
      throw new Error('页面未注册：' + ctx.route.name + '（由 ' + file + ' 提供）');
    }
    dom.content.innerHTML = view.render(ctx);
    restoreDrafts(dom.content);
    mounted = { name: ctx.route.name, view, ctx };
    if (view.mount) view.mount(ctx, dom.content);
    window.scrollTo(0, keepScroll ? scrollY : 0);
  }
  Y7.renderContent = renderContent;

  function renderAll(keepScroll) {
    renderShell();
    renderToolbar();
    renderContent(keepScroll);
  }
  Y7.renderAll = renderAll;

  function onDataChanged(paths) {
    renderShell();
    if (!mounted) return;
    if (!mounted.view) {
      // 说明页（档位未到等）可能因为数据变化而改变
      if (views[mounted.name] || gateFor(buildCtx()) !== null) renderContent(true);
      return;
    }
    if (mounted.view.update) {
      const ctx = buildCtx();
      if (gateFor(ctx)) {
        renderContent(true);
        return;
      }
      mounted.ctx = ctx;
      mounted.view.update(ctx, dom.content, paths);
      restoreDrafts(dom.content);
    } else {
      renderContent(true);
    }
  }

  // ---------------------------------------------------------------------------
  // 界面辅助函数

  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  Y7.esc = function esc(text) {
    if (text === null || text === undefined) return '';
    return String(text).replace(/[&<>"']/g, (ch) => ESC[ch]);
  };

  function kebab(key) {
    return key.replace(/[A-Z]/g, (ch) => '-' + ch.toLowerCase());
  }

  Y7.dataAttrs = function dataAttrs(data) {
    if (!data) return '';
    return Object.keys(data)
      .filter((key) => data[key] !== undefined && data[key] !== null)
      .map((key) => ' data-' + kebab(key) + '="' + Y7.esc(data[key]) + '"')
      .join('');
  };

  const ICON_PATHS = {
    running: '<circle cx="8" cy="8" r="3.6" fill="currentColor" stroke="none"/><circle cx="8" cy="8" r="6.2" opacity=".35"/>',
    succeeded: '<path d="M3.2 8.4l3 3 6.6-7"/>',
    queued: '<rect x="2" y="4" width="12" height="8" rx="1.5"/><path d="M6 4v8"/><path d="M8.6 7h3M8.6 9h2"/>',
    asking: '<path d="M1.8 7.6L14 2.4l-3.6 11.2-2.6-4.4z"/><path d="M7.8 9.2L14 2.4"/>',
    paused: '<path d="M5.5 3.5v9M10.5 3.5v9"/>',
    failed: '<circle cx="8" cy="8" r="6"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/>',
    done: '<path d="M4 14.2V2.4"/><path d="M4 2.8h7.6l-1.8 2.6 1.8 2.6H4"/>',
    cancelled: '<circle cx="8" cy="8" r="6"/><path d="M3.8 12.2l8.4-8.4"/>',
    interrupted: '<path d="M9.2 1.6L3.8 9h4l-1 5.4L12.2 7h-4z"/>',
    pending: '<circle cx="8" cy="8" r="6"/><path d="M6.2 6.2a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1v.5"/><path d="M8 11.4v.2"/>',
    waiting: '<path d="M5 2.2L8 4.4l3-2.2"/><rect x="2" y="4.4" width="12" height="7.4" rx="1"/><path d="M5 8.1h6"/>',
    adopted: '<rect x="1.8" y="2.4" width="12.4" height="3.2" rx=".6"/><path d="M2.8 5.6v7.8h10.4V5.6"/><path d="M6.2 8.4h3.6"/>',
    held: '<path d="M2.4 2.4h5.8l5.4 5.4-5.8 5.8-5.4-5.4z"/><circle cx="5.4" cy="5.4" r="1"/>',
    released: '<path d="M6.2 2h3.6v3.8l2.4 1.6v2.2H3.8V7.4l2.4-1.6z"/><path d="M2.6 13.6h10.8"/>',
    candidate: '<circle cx="8" cy="8" r="5.6" stroke-dasharray="2.2 2"/>',
    admitted: '<path d="M8 1.6l5.2 2v4.2c0 3-2.2 5.3-5.2 6.6-3-1.3-5.2-3.6-5.2-6.6V3.6z"/><path d="M5.6 8l1.7 1.7 3.1-3.3"/>',
    unusable: '<path d="M8 1.8l6.6 11.6H1.4z"/><path d="M8 6.4v3.2"/><path d="M8 11.4v.2"/>',
    unknown: '<path d="M5.6 5.6a2.4 2.4 0 1 1 3.4 2.2c-.7.3-1 .8-1 1.5v.6"/><path d="M8 12.4v.2"/>',
    idle: '<circle cx="8" cy="8" r="5.6"/>'
  };
  Y7.STATUS_KINDS = Object.keys(ICON_PATHS);

  function svg(inner, className) {
    return '<svg class="' + (className || 'y7-icon') + '" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + '</svg>';
  }
  Y7.svg = svg;

  const GLYPHS = {
    brand: '<path d="M2.5 3.5h11v9h-11z"/><path d="M2.5 7.5h11M6.5 7.5v5M9.5 3.5v4"/>',
    menu: '<path d="M2.5 4h11M2.5 8h11M2.5 12h11"/>',
    close: '<path d="M4 4l8 8M12 4l-8 8"/>',
    plus: '<path d="M8 3v10M3 8h10"/>',
    search: '<circle cx="7" cy="7" r="4.3"/><path d="M10.2 10.2l3.3 3.3"/>',
    back: '<path d="M9.8 3.6L5.4 8l4.4 4.4"/>',
    models: '<rect x="3.5" y="3.5" width="9" height="9" rx="1.5"/><path d="M6.2 1.5v2M9.8 1.5v2M6.2 12.5v2M9.8 12.5v2M1.5 6.2h2M1.5 9.8h2M12.5 6.2h2M12.5 9.8h2"/>',
    runtime: '<rect x="2" y="3" width="3.2" height="10" rx=".6"/><rect x="6.4" y="3" width="3.2" height="10" rx=".6"/><rect x="10.8" y="3" width="3.2" height="10" rx=".6"/>',
    tools: '<path d="M10.4 2.2a3.2 3.2 0 0 0-3.6 4.4L2.6 10.8a1.3 1.3 0 0 0 1.8 1.8l4.2-4.2a3.2 3.2 0 0 0 4.4-3.6l-2 2-1.8-.4-.4-1.8z"/>',
    meta: '<path d="M1.6 8s2.4-4.4 6.4-4.4S14.4 8 14.4 8 12 12.4 8 12.4 1.6 8 1.6 8z"/><circle cx="8" cy="8" r="2"/>',
    nodes: '<rect x="2.5" y="2" width="11" height="4.6" rx="1"/><rect x="2.5" y="9.4" width="11" height="4.6" rx="1"/><path d="M5 4.3h.1M5 11.7h.1"/>',
    evolution: '<circle cx="4.5" cy="3.5" r="1.6"/><circle cx="4.5" cy="12.5" r="1.6"/><circle cx="11.5" cy="6" r="1.6"/><path d="M4.5 5.1v5.8M11.5 7.6c0 2.4-2.6 2.6-5.6 3.9"/>',
    lessons: '<path d="M2.5 3.2c2-.8 3.8-.6 5.5.6 1.7-1.2 3.5-1.4 5.5-.6v9.6c-2-.8-3.8-.6-5.5.6-1.7-1.2-3.5-1.4-5.5-.6z"/><path d="M8 3.8v9.6"/>',
    gallery: '<rect x="2.5" y="2.5" width="11" height="11" rx="1.5"/><circle cx="6" cy="6" r="1.3"/><path d="M13.5 10.5L10 7l-7 6.5"/>',
    more: '<circle cx="3.5" cy="8" r=".9" fill="currentColor"/><circle cx="8" cy="8" r=".9" fill="currentColor"/><circle cx="12.5" cy="8" r=".9" fill="currentColor"/>',
    chevron: '<path d="M4.5 6.2L8 9.8l3.5-3.6"/>',
    restart: '<path d="M13 8a5 5 0 1 1-1.5-3.6"/><path d="M13 2.6v2.6h-2.6"/>',
    lock: '<rect x="3.5" y="7" width="9" height="6.5" rx="1"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/>',
    play: '<path d="M5 3.2l7.6 4.8L5 12.8z" fill="currentColor"/>',
    pause: '<path d="M5.4 3.4v9.2M10.6 3.4v9.2"/>',
    step: '<path d="M4 3.4l6.4 4.6L4 12.6z"/><path d="M12.4 3.4v9.2"/>',
    reset: '<path d="M3 8a5 5 0 1 0 1.5-3.6"/><path d="M3 2.6v2.6h2.6"/>',
    tag: '<path d="M2.4 2.4h5.8l5.4 5.4-5.8 5.8-5.4-5.4z"/><circle cx="5.4" cy="5.4" r="1"/>'
  };

  Y7.ui = {};

  Y7.ui.icon = function icon(name, className) {
    const inner = GLYPHS[name] || ICON_PATHS[name];
    if (!inner) throw new Error('未知图标：' + name);
    return svg(inner, className);
  };

  Y7.ui.tag = function tag(text) {
    if (!text) return '';
    return '<span class="y7-tag">' + Y7.esc(text) + '</span>';
  };

  Y7.ui.status = function status(kind, text) {
    if (!ICON_PATHS[kind]) throw new Error('未知状态种类：' + kind);
    return '<span class="y7-status is-' + kind + '">' + svg(ICON_PATHS[kind], 'y7-status-icon') + '<span>' + Y7.esc(text) + '</span></span>';
  };

  function annotationHtml(opts) {
    const list = (value) => (Array.isArray(value) ? value.join('、') : value) || '无';
    const stage = opts.tag || (opts.level ? Y7.LEVEL_LABELS[opts.level] : '当前');
    return '<div class="y7-annot" role="note"><span><b>查询</b>' + Y7.esc(list(opts.query)) + '</span><span><b>命令</b>' + Y7.esc(list(opts.command)) + '</span><span><b>阶段</b>' + Y7.esc(stage) + '</span></div>';
  }

  Y7.ui.block = function block(opts) {
    if (!opts) throw new Error('block 需要参数');
    if (opts.level && !Y7.atLeast(opts.level)) return '';
    const head = opts.title || opts.actions
      ? '<header class="y7-block-head"><div class="y7-block-titles">' +
        (opts.title ? '<h2 class="y7-block-title">' + Y7.esc(opts.title) + '</h2>' : '') +
        Y7.ui.tag(opts.tag) +
        (opts.subtitle ? '<p class="y7-block-sub">' + Y7.esc(opts.subtitle) + '</p>' : '') +
        '</div>' + (opts.actions ? '<div class="y7-block-actions">' + opts.actions + '</div>' : '') + '</header>'
      : '';
    return '<section class="y7-block' + (opts.className ? ' ' + opts.className : '') + '"' +
      (opts.id ? ' id="' + Y7.esc(opts.id) + '"' : '') +
      ' data-level="' + (opts.level || 'now') + '"' +
      (opts.query ? ' data-query="' + Y7.esc([].concat(opts.query).join(' ')) + '"' : '') +
      (opts.command ? ' data-command="' + Y7.esc([].concat(opts.command).join(' ')) + '"' : '') + '>' +
      (Y7.state.annotate ? annotationHtml(opts) : '') +
      head + '<div class="y7-block-body">' + (opts.body || '') + '</div></section>';
  };

  Y7.ui.button = function button(opts) {
    const kind = opts.kind ? ' ' + opts.kind.split(' ').join(' ') : '';
    const attrs = (opts.act ? ' data-act="' + Y7.esc(opts.act) + '"' : '') +
      (opts.cmd ? ' data-cmd="' + Y7.esc(opts.cmd) + '"' : '') +
      (opts.go ? ' data-go="' + Y7.esc(opts.go) + '"' : '') +
      (opts.close ? ' data-close-modal' : '') +
      (opts.title ? ' title="' + Y7.esc(opts.title) + '"' : '') +
      (opts.disabled ? ' disabled' : '') +
      Y7.dataAttrs(opts.data);
    return '<button type="button" class="y7-btn' + kind + '"' + attrs + '>' + (opts.icon ? Y7.ui.icon(opts.icon) : '') + '<span>' + Y7.esc(opts.label) + '</span></button>';
  };

  Y7.ui.table = function table(opts) {
    const columns = opts.columns || [];
    const rows = opts.rows || [];
    if (!rows.length) return Y7.ui.empty(opts.empty || '没有记录');
    const head = columns.map((col) => '<th' + (col.className ? ' class="' + col.className + '"' : '') + '>' + Y7.esc(col.label) + '</th>').join('');
    const body = rows.map((row) => {
      const cells = columns.map((col) => {
        const value = col.render ? col.render(row) : Y7.esc(row[col.key]);
        return '<td data-label="' + Y7.esc(col.label) + '"' + (col.className ? ' class="' + col.className + '"' : '') + '><div class="y7-td">' + (value === '' || value === undefined ? '<span class="y7-muted">—</span>' : value) + '</div></td>';
      }).join('');
      const attrs = opts.rowAttrs ? opts.rowAttrs(row) : '';
      return '<tr' + (attrs ? ' ' + attrs : '') + '>' + cells + '</tr>';
    }).join('');
    return '<div class="y7-table-wrap"><table class="y7-table' + (opts.className ? ' ' + opts.className : '') + '"><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
  };

  Y7.ui.activeTab = function activeTab(id, items, fallback) {
    const visible = (items || []).filter((item) => Y7.atLeast(item.level));
    const stored = Y7.state.tabs[id];
    if (visible.some((item) => item.id === stored)) return stored;
    if (fallback && visible.some((item) => item.id === fallback)) return fallback;
    return visible.length ? visible[0].id : null;
  };

  Y7.ui.tabs = function tabs(opts) {
    const items = (opts.items || []).filter((item) => Y7.atLeast(item.level));
    const active = Y7.ui.activeTab(opts.id, items, opts.active);
    return '<div class="y7-tabs" role="tablist" data-tab-group-root="' + Y7.esc(opts.id) + '">' + items.map((item) =>
      '<button type="button" role="tab" class="y7-tab' + (item.id === active ? ' is-active' : '') + '" aria-selected="' + (item.id === active) + '" data-tab-group="' + Y7.esc(opts.id) + '" data-tab="' + Y7.esc(item.id) + '">' +
      Y7.esc(item.label) + (item.tag ? Y7.ui.tag(item.tag) : '') + (item.count !== undefined ? '<span class="y7-count">' + Y7.esc(item.count) + '</span>' : '') + '</button>'
    ).join('') + '</div>';
  };

  // 页签内容：panels 为 { 页签 id: html }；切换时只改显示，不重新渲染
  Y7.ui.tabPanels = function tabPanels(group, active, panels) {
    return Object.keys(panels).map((id) =>
      '<div class="y7-tab-panel" role="tabpanel" data-tab-panel="' + Y7.esc(group) + '" data-tab-id="' + Y7.esc(id) + '"' + (id === active ? '' : ' hidden') + '>' + panels[id] + '</div>'
    ).join('');
  };

  function selectTab(group, tab) {
    Y7.state.tabs[group] = tab;
    writeStored(session, 'y7.tabs', Y7.state.tabs);
    const panels = document.querySelectorAll('[data-tab-panel="' + CSS.escape(group) + '"]');
    document.querySelectorAll('[data-tab-group="' + CSS.escape(group) + '"]').forEach((el) => {
      const on = el.dataset.tab === tab;
      el.classList.toggle('is-active', on);
      el.setAttribute('aria-selected', String(on));
    });
    if (panels.length) {
      panels.forEach((el) => { el.hidden = el.dataset.tabId !== tab; });
    } else {
      renderContent(true);
    }
    Y7.bus.emit('tab-changed', { group, tab });
  }
  Y7.ui.selectTab = selectTab;

  Y7.ui.modal = function modal(opts) {
    const actions = Array.isArray(opts.actions)
      ? opts.actions.map((item) => Y7.ui.button(item)).join('')
      : (opts.actions || '');
    dom.modal.innerHTML = '<div class="y7-modal-backdrop" data-modal-backdrop>' +
      '<div class="y7-modal' + (opts.wide ? ' is-wide' : '') + (opts.className ? ' ' + opts.className : '') + '" role="dialog" aria-modal="true" aria-label="' + Y7.esc(opts.title) + '">' +
      '<header class="y7-modal-head"><h2>' + Y7.esc(opts.title) + '</h2>' +
      '<button type="button" class="y7-icon-btn" data-close-modal aria-label="关闭">' + Y7.ui.icon('close') + '</button></header>' +
      '<div class="y7-modal-body">' + (opts.body || '') + '</div>' +
      (actions ? '<footer class="y7-modal-foot">' + actions + '</footer>' : '') +
      '</div></div>';
    document.body.classList.add('has-modal');
    restoreDrafts(dom.modal);
    const card = dom.modal.querySelector('.y7-modal');
    const focusTarget = card.querySelector('textarea, input, select') || card.querySelector('.y7-modal-foot .y7-btn');
    if (focusTarget) focusTarget.focus();
    return card;
  };

  Y7.ui.closeModal = function closeModal() {
    dom.modal.innerHTML = '';
    document.body.classList.remove('has-modal');
  };

  Y7.ui.modalOpen = () => Boolean(dom.modal && dom.modal.firstChild);

  Y7.ui.toast = function toast(message, kind) {
    const el = document.createElement('div');
    el.className = 'y7-toast is-' + (kind || 'ok');
    el.setAttribute('role', 'status');
    el.textContent = message;
    dom.toast.appendChild(el);
    setTimeout(() => el.classList.add('is-leaving'), 3600);
    setTimeout(() => el.remove(), 4000);
  };

  Y7.ui.empty = function empty(text) {
    return '<div class="y7-empty">' + Y7.esc(text) + '</div>';
  };

  Y7.ui.note = function note(html, kind) {
    return '<div class="y7-note' + (kind ? ' is-' + kind : '') + '">' + html + '</div>';
  };

  // 键值列表：pairs 为 [[名称, 已转义的 HTML], …]
  Y7.ui.kv = function kv(pairs, className) {
    return '<dl class="y7-kv' + (className ? ' ' + className : '') + '">' + pairs.filter(Boolean).map((pair) =>
      '<div><dt>' + Y7.esc(pair[0]) + '</dt><dd>' + (pair[1] === '' || pair[1] === null || pair[1] === undefined ? '<span class="y7-muted">—</span>' : pair[1]) + '</dd></div>'
    ).join('') + '</dl>';
  };

  Y7.ui.meter = function meter(value, max, opts) {
    const ratio = max ? Math.min(1, Math.max(0, value / max)) : 0;
    const warn = opts && opts.warnAt !== undefined ? ratio >= opts.warnAt : ratio >= 0.85;
    return '<div class="y7-meter' + (warn ? ' is-warn' : '') + '" role="meter" aria-valuemin="0" aria-valuemax="' + max + '" aria-valuenow="' + value + '"><span style="width:' + (ratio * 100).toFixed(1) + '%"></span></div>';
  };

  Y7.ui.code = (text) => '<code class="y7-code">' + Y7.esc(text) + '</code>';
  Y7.ui.pre = (text) => '<pre class="y7-pre">' + Y7.esc(text) + '</pre>';

  const timeFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const dateFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric' });
  const dayKey = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' });

  Y7.ui.time = function time(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) throw new Error('时间格式无效：' + iso);
    const today = dayKey.format(new Date(Y7.data.now)) === dayKey.format(date);
    return today ? timeFormat.format(date) : dateFormat.format(date) + ' ' + timeFormat.format(date);
  };

  Y7.ui.duration = function duration(sec) {
    if (sec === null || sec === undefined) return '—';
    const total = Math.round(sec);
    if (total < 60) return total + ' 秒';
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    if (hours) return hours + ' 小时' + (minutes ? ' ' + minutes + ' 分' : '');
    return minutes + ' 分' + (seconds ? ' ' + seconds + ' 秒' : '');
  };

  // 从现在往前的时长（秒）
  Y7.ui.since = (iso) => Math.max(0, Math.round((new Date(Y7.data.now) - new Date(iso)) / 1000));

  const numberFormat = new Intl.NumberFormat('zh-CN');
  Y7.ui.num = (value) => (value === null || value === undefined ? '未上报' : numberFormat.format(value));

  // ---------------------------------------------------------------------------
  // 事件委托

  function closestAction(target) {
    return target.closest('[data-go],[data-cmd],[data-act],[data-tab],[data-close-modal]');
  }

  function isFormControl(el) {
    return el.matches('select, input, textarea');
  }

  function dispatch(el, ev) {
    if (el.dataset.tab && el.dataset.tabGroup) {
      selectTab(el.dataset.tabGroup, el.dataset.tab);
      return;
    }
    if (el.dataset.go) {
      ev.preventDefault();
      Y7.go(el.dataset.go);
    }
    if (el.dataset.cmd) {
      const params = Object.assign({}, el.dataset);
      delete params.cmd;
      Y7.command(el.dataset.cmd, params);
    }
    if (el.dataset.act) Y7.actions.run(el.dataset.act, el, ev);
    if (el.hasAttribute('data-close-modal')) Y7.ui.closeModal();
  }

  function onClick(ev) {
    if (ev.target.matches('[data-modal-backdrop]')) {
      Y7.ui.closeModal();
      return;
    }
    const el = closestAction(ev.target);
    if (!el || isFormControl(el)) return;
    if (el.disabled) return;
    dispatch(el, ev);
  }

  function onChange(ev) {
    const el = ev.target;
    if (!isFormControl(el)) return;
    const textual = el.matches('textarea, input:not([type]), input[type=text], input[type=search], input[type=number], input[type=password], input[type=url]');
    if (textual) return;
    if (el.dataset.act) Y7.actions.run(el.dataset.act, el, ev);
    if (el.dataset.go) Y7.go(el.dataset.go);
  }

  function onInput(ev) {
    const el = ev.target;
    if (!isFormControl(el)) return;
    if (el.dataset.draft) Y7.setDraft(el.dataset.draft, el.value);
    const textual = el.matches('textarea, input:not([type]), input[type=text], input[type=search], input[type=number], input[type=password], input[type=url]');
    if (textual && el.dataset.act) Y7.actions.run(el.dataset.act, el, ev);
  }

  function onKeydown(ev) {
    if (ev.key !== 'Escape') return;
    if (Y7.ui.modalOpen()) Y7.ui.closeModal();
    else if (Y7.state.drawerOpen) {
      Y7.state.drawerOpen = false;
      document.body.classList.remove('is-drawer-open');
    }
  }

  // ---------------------------------------------------------------------------
  // 浮动工具条与场景播放器

  let initialData = null;
  let playTimer = null;
  let eventSeq = 1000;

  function scenarios() {
    return Array.isArray(Y7.data.scenarios) ? Y7.data.scenarios : [];
  }

  function currentScenario() {
    const id = Y7.state.scenario.id;
    if (!id) return null;
    const found = scenarios().find((item) => item.id === id);
    if (!found) throw new Error('找不到场景：' + id);
    return found;
  }

  function restoreInitialData() {
    if (!initialData) throw new Error('初始数据尚未保存，Y7.start 需要先运行');
    const fresh = Y7.clone(initialData);
    Object.keys(Y7.data).forEach((key) => { if (!(key in fresh)) delete Y7.data[key]; });
    Object.keys(fresh).forEach((key) => { Y7.data[key] = fresh[key]; });
  }

  function scenarioHash(sc) {
    if (sc.view === 'overview') return Y7.paths.overview(sc.projectId, sc.workItemId);
    if (sc.view === 'dept') return Y7.paths.dept(sc.projectId, sc.department, sc.workItemId);
    if (sc.view === 'recovery') return Y7.paths.recovery(sc.projectId, sc.workItemId);
    if (typeof sc.view === 'string' && sc.view.startsWith('#/')) return sc.view;
    throw new Error('场景的页面无效：' + sc.view);
  }

  function stopPlaying() {
    if (playTimer) clearTimeout(playTimer);
    playTimer = null;
    Y7.state.scenario.playing = false;
  }

  Y7.scenario = {
    list: scenarios,
    current: currentScenario,
    select(id) {
      stopPlaying();
      restoreInitialData();
      Y7.state.scenario = { id: id || null, step: 0, playing: false, lastEvent: null };
      const sc = currentScenario();
      if (sc && sc.level && !Y7.atLeast(sc.level)) {
        Y7.state.level = sc.level;
        writeStored(session, 'y7.level', sc.level);
        Y7.bus.emit('level-changed', sc.level);
      }
      Y7.bus.emit('scenario-changed', Y7.state.scenario);
      Y7.bus.emit('data-changed', ['*']);
      if (sc) Y7.go(scenarioHash(sc));
      else renderAll(true);
    },
    reset() {
      Y7.scenario.select(Y7.state.scenario.id);
    },
    step() {
      const sc = currentScenario();
      if (!sc) throw new Error('没有选择场景');
      if (Y7.state.scenario.step >= sc.steps.length) {
        stopPlaying();
        renderToolbar();
        return false;
      }
      const step = sc.steps[Y7.state.scenario.step];
      if (!step.event || !step.event.type) throw new Error('场景「' + sc.name + '」第 ' + (Y7.state.scenario.step + 1) + ' 步缺少事件');
      if (step.go) Y7.go(step.go);
      const paths = (step.patch || []).map((patch) => Y7.applyPatch(patch));
      eventSeq += 1;
      const event = Object.assign({
        seq: eventSeq, at: Y7.data.now, projectId: sc.projectId, workItemId: sc.workItemId,
        department: null, role: null, tool: null, payload: {}
      }, Y7.clone(step.event));
      Y7.state.scenario.step += 1;
      Y7.state.scenario.lastEvent = event;
      if (Y7.state.scenario.step >= sc.steps.length) stopPlaying();
      renderToolbar();
      if (paths.length) Y7.bus.emit('data-changed', paths);
      Y7.bus.emit('domain-event', event);
      return true;
    },
    play() {
      const sc = currentScenario();
      if (!sc) throw new Error('没有选择场景');
      if (Y7.state.scenario.step >= sc.steps.length) Y7.scenario.select(sc.id);
      Y7.state.scenario.playing = true;
      renderToolbar();
      const tick = () => {
        const current = currentScenario();
        if (!Y7.state.scenario.playing || !current) return;
        const next = current.steps[Y7.state.scenario.step];
        if (!next) {
          stopPlaying();
          renderToolbar();
          return;
        }
        playTimer = setTimeout(() => {
          Y7.scenario.step();
          tick();
        }, next.delay || 1200);
      };
      tick();
    },
    pause() {
      stopPlaying();
      renderToolbar();
    }
  };

  function renderToolbar() {
    if (!dom.toolbar) return;
    const st = Y7.state;
    const sc = st.scenario.id ? currentScenario() : null;
    const total = sc ? sc.steps.length : 0;
    const ev = st.scenario.lastEvent;
    const levelButtons = LEVELS.map((level) =>
      '<button type="button" class="y7-tb-level' + (st.level === level ? ' is-on' : '') + '" data-act="core.level" data-level="' + level + '" aria-pressed="' + (st.level === level) + '">' + Y7.LEVEL_LABELS[level] + '</button>'
    ).join('');
    const options = '<option value="">选择场景…</option>' + scenarios().map((item) =>
      '<option value="' + Y7.esc(item.id) + '"' + (item.id === st.scenario.id ? ' selected' : '') + '>' + Y7.esc(item.name) + ' · ' + Y7.esc(Y7.LEVEL_LABELS[item.level || 'now']) + '</option>'
    ).join('');
    const themeOptions = [['system', '跟随系统'], ['light', '浅色'], ['dark', '深色']].map((pair) =>
      '<option value="' + pair[0] + '"' + (st.theme === pair[0] ? ' selected' : '') + '>' + pair[1] + '</option>'
    ).join('');
    const eventLine = sc
      ? (ev
        ? '<code>' + Y7.esc(ev.type) + '</code><span>' + Y7.esc(ev.label || '') + '</span>'
        : '<span class="y7-tb-hint">场景「' + Y7.esc(sc.name) + '」共 ' + total + ' 步，点击「单步」或「播放」开始</span>')
      : '<span class="y7-tb-hint">选择场景后逐步播放事件，每一步显示驱动画面的事件</span>';
    dom.toolbar.className = 'y7-toolbar' + (st.toolbarOpen ? ' is-open' : '');
    dom.toolbar.innerHTML =
      '<div class="y7-tb-bar">' +
        '<span class="y7-tb-brand">原型工具</span>' +
        '<div class="y7-tb-seg" role="group" aria-label="阶段显示">' + levelButtons + '</div>' +
        '<label class="y7-tb-switch"><input type="checkbox" data-act="core.annotate"' + (st.annotate ? ' checked' : '') + '><span>标注</span></label>' +
        '<span class="y7-tb-sep"></span>' +
        '<select class="y7-tb-select" data-act="core.scenario" aria-label="场景">' + options + '</select>' +
        '<button type="button" class="y7-tb-btn" data-act="core.reset" title="重置场景"' + (sc ? '' : ' disabled') + '>' + Y7.ui.icon('reset') + '<span>重置</span></button>' +
        '<button type="button" class="y7-tb-btn" data-act="core.step" title="单步"' + (sc && st.scenario.step < total ? '' : ' disabled') + '>' + Y7.ui.icon('step') + '<span>单步</span></button>' +
        '<button type="button" class="y7-tb-btn" data-act="core.play" title="' + (st.scenario.playing ? '暂停' : '播放') + '"' + (sc ? '' : ' disabled') + '>' + Y7.ui.icon(st.scenario.playing ? 'pause' : 'play') + '<span>' + (st.scenario.playing ? '暂停' : '播放') + '</span></button>' +
        '<span class="y7-tb-count">' + (sc ? st.scenario.step + ' / ' + total : '— / —') + '</span>' +
        '<span class="y7-tb-sep"></span>' +
        '<a class="y7-tb-link" href="#/gallery">动作图鉴</a>' +
        '<select class="y7-tb-select is-theme" data-act="core.theme" aria-label="主题">' + themeOptions + '</select>' +
      '</div>' +
      '<div class="y7-tb-event">' + eventLine + '</div>' +
      '<button type="button" class="y7-tb-toggle" data-act="core.toolbar" aria-expanded="' + st.toolbarOpen + '">' +
        '<span class="y7-tb-mini">原型工具 · ' + Y7.esc(Y7.LEVEL_LABELS[st.level]) + (sc ? ' · ' + st.scenario.step + '/' + total : '') + '</span>' +
        Y7.ui.icon('chevron', 'y7-icon y7-tb-chevron') + '</button>';
  }
  Y7.renderToolbar = renderToolbar;

  function registerCoreActions() {
    Y7.actions.register('core.level', (el) => Y7.setLevel(el.dataset.level));
    Y7.actions.register('core.annotate', (el) => Y7.setAnnotate(el.checked));
    Y7.actions.register('core.theme', (el) => Y7.setTheme(el.value));
    Y7.actions.register('core.scenario', (el) => Y7.scenario.select(el.value || null));
    Y7.actions.register('core.reset', () => Y7.scenario.reset());
    Y7.actions.register('core.step', () => Y7.scenario.step());
    Y7.actions.register('core.play', () => (Y7.state.scenario.playing ? Y7.scenario.pause() : Y7.scenario.play()));
    Y7.actions.register('core.toolbar', () => {
      Y7.state.toolbarOpen = !Y7.state.toolbarOpen;
      renderToolbar();
    });
    Y7.actions.register('core.back', () => Y7.back());
  }

  // ---------------------------------------------------------------------------
  // core.js 负责的查询

  function projectMarker(items, runs) {
    const pairs = items.map((item) => ({ item, run: runs[item.id] }));
    if (Y7.atLeast('s3')) {
      const recoveryOrder = [['waiting_resume', 'waiting', '待恢复'], ['pending_verification', 'pending', '待核实'], ['interrupted', 'interrupted', '中断']];
      for (const [state, kind, text] of recoveryOrder) {
        const count = pairs.filter((pair) => pair.run && pair.run.recovery && pair.run.recovery.state === state).length;
        if (count) return { kind, text, count };
      }
    }
    const running = pairs.filter((pair) => pair.item.status === 'in_progress').length;
    const queued = pairs.filter((pair) => pair.item.status === 'queued').length;
    if (running) return { kind: 'running', text: '运行中', count: running + queued };
    if (queued) return { kind: 'queued', text: '排队中', count: queued };
    return null;
  }

  function registerCoreQueries() {
    // 左侧栏：项目名称、置顶、归档、进行中事项数量与状态标记
    Y7.queries.register('projects.list', () => {
      const projects = Y7.resolve(rawList('projects'));
      const list = projects.map((project) => {
        const items = Y7.workItemsOf(project.id);
        const runs = {};
        items.forEach((item) => { runs[item.id] = item.runId ? Y7.run(item.runId) : null; });
        const marker = project.archived ? { kind: 'cancelled', text: '已归档', count: 0 } : projectMarker(items, runs);
        const active = items.filter((item) => ['in_progress', 'queued'].includes(item.status)).length;
        return {
          id: project.id, name: project.name, goal: project.goal, pinned: Boolean(project.pinned), archived: Boolean(project.archived),
          workItemCount: items.length, activeCount: active, marker
        };
      });
      return list.slice().sort((a, b) => (Number(b.pinned) - Number(a.pinned)) || (Number(a.archived) - Number(b.archived)));
    });

    // 概览摘要与事项看板：长期目标、当前成果、事项统计、事项列表
    Y7.queries.register('project.overview', (params) => {
      const projectId = params.projectId || Y7.state.projectId;
      const project = Y7.project(projectId);
      if (!project) throw new Error('项目不在当前档位或不存在：' + projectId);
      const items = Y7.workItemsOf(projectId).map((item) => {
        const run = item.runId ? Y7.run(item.runId) : null;
        const openRequest = run ? (run.requests || []).find((request) => request.status === 'open') : null;
        return Object.assign({}, item, {
          phase: run ? run.phase : null,
          department: run ? run.department : null,
          lastDepartment: run ? (run.department || run.lastDepartment || null) : null,
          cycle: run ? run.cycle : 0,
          startedAt: run ? run.startedAt : null,
          elapsedSec: run ? run.elapsedSec : 0,
          limitSec: run ? run.limitSec : 7200,
          stopReason: run ? run.stopReason : null,
          recoveryState: run && run.recovery ? run.recovery.state : null,
          pendingQuestion: openRequest ? openRequest.question : null,
          display: Y7.workItemStatus(item, run)
        });
      });
      const count = (fn) => items.filter(fn).length;
      return {
        project,
        adoption: project.adoption || null,
        stats: {
          inProgress: count((item) => item.status === 'in_progress'),
          queued: count((item) => item.status === 'queued'),
          adopted: count((item) => item.status === 'adopted'),
          held: count((item) => item.status === 'held'),
          total: items.length
        },
        workItems: items
      };
    });
  }

  // ---------------------------------------------------------------------------
  // core.js 负责的命令

  function requireProject(projectId) {
    const project = Y7.raw.project(projectId);
    if (!project) throw new Error('找不到项目：' + projectId);
    return project;
  }

  // 新建事项使用的空 run 结构（尚未开始：没有部门、第 0 轮）。给出 projectId 时，按该项目的设置与模型目录
  // 填入部门 Prompt 版本、各部门的生效模型与 Stage 4 的角色名单；不给时只返回结构（data.js 在加载时使用）
  Y7.emptyRun = function emptyRun(id, workItemId, projectId) {
    if (!id || !workItemId) throw new Error('emptyRun 需要 id 与 workItemId');
    const ledger = () => ({ items: [], facts: [], questions: [], progress: [] });
    const run = {
      id, workItemId, phase: 'PRODUCT_SPEC', department: null, lastDepartment: null, cycle: 0,
      startedAt: null, elapsedSec: 0, limitSec: 7200, stopReason: null,
      recovery: {
        level: 's3', state: 'running', reason: null, unusable: null, lastConfirmed: null,
        canResume: false, resumeBlockedReason: '事项正在运行，已有有效执行者', owner: null,
        lateResults: [], verifications: [], decisions: [], nextActions: [], unfinished: [],
        limits: { activations: 0, modelSteps: 0, retries: 0 }
      },
      inputs: [], flow: [], requests: [], guidance: [],
      messages: { product: [], engineering: [], quality: [], operations: [] },
      actions: [], contexts: { product: [], engineering: [], quality: [] },
      prompts: {
        product: { configVersion: 0, requestVersion: null, text: null },
        engineering: { configVersion: 0, requestVersion: null, text: null },
        quality: { configVersion: 0, requestVersion: null, text: null }
      },
      compactions: [],
      effectiveModel: { level: 's3', product: null, engineering: null, quality: null },
      roles: { level: 's4', product: [], engineering: [], quality: [] },
      ledger: { level: 's4', product: ledger(), engineering: ledger(), quality: ledger() },
      attempts: [],
      source: null
    };
    if (projectId) initRunFromProject(run, projectId);
    return run;
  };

  function initRunFromProject(run, projectId) {
    const settings = Y7.data.projectSettings[projectId];
    if (!settings) throw new Error('项目没有项目设置：' + projectId);
    ['product', 'engineering', 'quality'].forEach((dept) => {
      const entry = settings.departments[dept];
      run.prompts[dept] = { configVersion: entry.promptText ? entry.promptVersion : 0, requestVersion: null, text: entry.promptText || Y7.defaultPrompt(dept) };
      const target = Y7.model.resolve(projectId, dept);
      run.effectiveModel[dept] = {
        definition: target.definition, connection: target.connection, protocol: target.protocol,
        source: target.source, level: target.requestLevel, sentLevel: target.sentLevel, unusable: target.problem
      };
      run.roles[dept] = (Y7.data.catalog.roleCatalog[dept] || []).map((role) => ({
        id: role.id, name: role.name, kind: role.kind, status: 'idle',
        model: Y7.model.resolveRole(projectId, dept, role.id).definition, task: null
      }));
    });
  }

  function titleFrom(text) {
    const first = text.split(/\r?\n/)[0].trim();
    return first.length > 18 ? first.slice(0, 18) + '…' : first;
  }

  function registerCoreCommands() {
    // 新建项目
    Y7.commands.register('createProject', (params) => {
      const name = (params.name || '').trim();
      if (!name) return { ok: false, message: '请填写项目名称' };
      const id = Y7.uid('p-new');
      rawList('projects').push({ id, name, goal: (params.goal || '').trim(), pinned: false, archived: false, adoption: null, workItemIds: [] });
      Y7.data.projectSettings[id] = {
        departments: {
          product: { model: null, level: null, promptVersion: 0, promptText: null },
          engineering: { model: null, level: null, promptVersion: 0, promptText: null },
          quality: { model: null, level: null, promptVersion: 0, promptText: null }
        },
        roles: { level: 's4' },
        commands: [],
        tools: []
      };
      return { ok: true, message: '已新建项目「' + name + '」', paths: ['projects', 'projectSettings'], projectId: id };
    });

    // 重命名
    Y7.commands.register('renameProject', (params) => {
      const project = requireProject(params.projectId);
      const name = (params.name || '').trim();
      if (!name) return { ok: false, message: '项目名称不能为空' };
      if (project.archived) return { ok: false, message: '归档项目只读：写命令会返回冲突' };
      project.name = name;
      return { ok: true, message: '项目已重命名为「' + name + '」', paths: ['projects[id=' + project.id + '].name'] };
    });

    // 置顶或取消置顶
    Y7.commands.register('pinProject', (params) => {
      const project = requireProject(params.projectId);
      project.pinned = !project.pinned;
      return { ok: true, message: project.pinned ? '已置顶「' + project.name + '」' : '已取消置顶「' + project.name + '」', paths: ['projects[id=' + project.id + '].pinned'] };
    });

    // 归档
    Y7.commands.register('archiveProject', (params) => {
      const project = requireProject(params.projectId);
      const items = Y7.workItemsOf(project.id);
      const active = items.some((item) => ['in_progress', 'queued'].includes(item.status));
      if (active) return { ok: false, message: '项目还有进行中或排队中的事项，先取消事项再归档' };
      const recovering = items.some((item) => {
        const run = item.runId ? Y7.run(item.runId) : null;
        return run && run.recovery && ['interrupted', 'pending_verification', 'waiting_resume'].includes(run.recovery.state);
      });
      if (recovering) return { ok: false, message: '项目还有待恢复或待核实的事项，先继续执行或取消事项再归档' };
      project.archived = true;
      return { ok: true, message: '已归档「' + project.name + '」：查询仍可用，写命令会返回冲突', paths: ['projects[id=' + project.id + '].archived'] };
    });

    // 恢复项目
    Y7.commands.register('restoreProject', (params) => {
      const project = requireProject(params.projectId);
      project.archived = false;
      return { ok: true, message: '已恢复项目「' + project.name + '」', paths: ['projects[id=' + project.id + '].archived'] };
    });

    // 记录原文（项目材料或某部门的材料，不调用模型）
    Y7.commands.register('recordMaterial', (params) => {
      const project = requireProject(params.projectId || Y7.state.projectId);
      const text = (params.text || '').trim();
      if (!text) return { ok: false, message: '请先输入要记录的原文' };
      if (project.archived) return { ok: false, message: '归档项目只读' };
      const id = Y7.uid('m-note');
      rawList('materials').push({
        id, projectId: project.id, workItemId: null, kind: 'note', version: 1,
        title: params.department ? Y7.deptLabel(params.department) + '部门材料' : '项目材料',
        department: params.department || null, text, at: Y7.data.now, files: null, verdict: null
      });
      if (params.draftKey) Y7.clearDraft(params.draftKey);
      return { ok: true, message: '已记录原文，不注入后续事项，也不调用模型', paths: ['materials'], materialId: id };
    });

    // 新建事项：只提交事项原文与可选的代码快照来源（D24、3.2A）
    Y7.commands.register('createWorkItem', (params) => {
      const project = requireProject(params.projectId || Y7.state.projectId);
      const text = (params.text || '').trim();
      if (!text) return { ok: false, message: '请先输入事项原文' };
      if (project.archived) return { ok: false, message: '归档项目只读' };
      const items = rawList('workItems').filter((item) => item.projectId === project.id);
      if (!Y7.atLeast('s3') && items.some((item) => item.status === 'in_progress')) {
        return { ok: false, message: '本项目已有进行中的事项，输入会作为追加需求进入当前事项' };
      }
      if (Y7.atLeast('s3')) {
        for (const dept of ['product', 'engineering', 'quality']) {
          const target = Y7.model.resolve(project.id, dept);
          if (!target.ok) {
            return { ok: false, message: '不能新建事项：' + Y7.deptLabel(dept) + '部门的模型' + (target.model ? ' ' + target.model : '') + '无法使用（' + target.problem + '）' };
          }
        }
      }
      const workItemId = Y7.uid('w-new');
      const runId = Y7.uid('r-new');
      const run = Y7.emptyRun(runId, workItemId, project.id);
      run.inputs.push({ version: 1, kind: 'user', text, at: Y7.data.now, progress: 'received', bytes: [0, new TextEncoder().encode(text).length] });
      if (params.sourceDir) run.source = { dir: params.sourceDir, digest: null, files: null };
      const usedColors = items.map((item) => item.colorIndex);
      const colorIndex = [0, 1, 2, 3, 4, 5].find((index) => !usedColors.includes(index));
      const item = { id: workItemId, projectId: project.id, title: (params.title || '').trim() || titleFrom(text), colorIndex: colorIndex === undefined ? items.length % 6 : colorIndex, status: 'in_progress', runId, queuePos: null, heldReason: null };
      const paths = ['workItems', 'runs', 'projects[id=' + project.id + '].workItemIds'];
      let message = '已新建事项「' + item.title + '」，进入产品部门';
      if (Y7.atLeast('s3')) {
        const runtime = Y7.data.runtime;
        const slots = Y7.runtime.slots();
        if (slots.used.length >= slots.total) {
          item.status = 'queued';
          item.queuePos = runtime.queue.length + 1;
          runtime.queue.push({ workItemId, since: Y7.data.now, position: item.queuePos });
          message = '执行槽位已满，事项「' + item.title + '」排在第 ' + item.queuePos + ' 位';
        } else {
          runtime.slots.used.push({ workItemId, department: 'product', role: null });
        }
        paths.push('runtime');
      }
      if (item.status === 'in_progress') {
        run.department = 'product';
        run.cycle = 1;
        run.startedAt = Y7.data.now;
      }
      rawList('workItems').push(item);
      rawList('runs').push(run);
      project.workItemIds.push(workItemId);
      if (params.draftKey) Y7.clearDraft(params.draftKey);
      return { ok: true, message, paths, workItemId };
    });

    // 追加需求：进入当前事项的产品入口；/stop 与 /cancel 立即停止
    Y7.commands.register('addInput', (params) => {
      const run = params.runId ? Y7.raw.run(params.runId) : Y7.raw.runOf(params.workItemId);
      if (!run) throw new Error('找不到事项的 run：' + (params.runId || params.workItemId));
      const item = Y7.raw.workItem(run.workItemId);
      const text = (params.text || '').trim();
      if (!text) return { ok: false, message: '请先输入要追加的内容' };
      if (Y7.TERMINAL_PHASES.includes(run.phase) && !(run.recovery && Y7.atLeast('s3') && run.recovery.state === 'waiting_resume')) {
        return { ok: false, message: '事项已结束，不会自动新建' };
      }
      const version = run.inputs.length + 1;
      if (text === '/stop' || text === '/cancel') {
        run.inputs.push({ version, kind: 'command', text, at: Y7.data.now, progress: 'received' });
        if (params.draftKey) Y7.clearDraft(params.draftKey);
        const result = Y7.commands.has('cancelWorkItem') ? commands.cancelWorkItem({ workItemId: item.id }) : null;
        return { ok: true, message: '文本命令 ' + text + ' 已执行：' + (result ? result.message : '事项已停止'), paths: ['runs[id=' + run.id + ']'].concat(result ? result.paths : []) };
      }
      run.inputs.push({ version, kind: 'user', text, at: Y7.data.now, progress: 'received', bytes: null });
      if (params.draftKey) Y7.clearDraft(params.draftKey);
      return { ok: true, message: '已追加为用户输入 v' + version + '，提交后进入当前事项的产品入口', paths: ['runs[id=' + run.id + '].inputs'] };
    });

    // 取消事项
    Y7.commands.register('cancelWorkItem', (params) => {
      const item = Y7.raw.workItem(params.workItemId);
      if (!item) throw new Error('找不到事项：' + params.workItemId);
      const run = Y7.raw.run(item.runId);
      const visibleRun = Y7.run(item.runId);
      const recovering = visibleRun && visibleRun.recovery && ['interrupted', 'pending_verification', 'waiting_resume'].includes(visibleRun.recovery.state);
      if (!recovering && ['adopted', 'held', 'released_unsettled', 'stopped'].includes(Y7.workItem(item.id).status)) {
        return { ok: false, message: '事项已结束，不能取消' };
      }
      const wasQueued = Y7.workItem(item.id).status === 'queued';
      setWorkItemStatus(item, 'stopped');
      Y7.setEffective(item, 'queuePos', null);
      run.lastDepartment = run.department || run.lastDepartment;
      run.department = null;
      run.phase = 'FAILED';
      run.stopReason = { code: 'cancelled', text: '用户取消事项' };
      if (run.recovery) {
        run.recovery.state = 'terminated';
        run.recovery.canResume = false;
        run.recovery.resumeBlockedReason = '事项已取消';
        run.recovery.nextActions = [];
      }
      let paths = ['workItems[id=' + item.id + ']', 'runs[id=' + run.id + ']'];
      let message = wasQueued ? '已取消排队中的事项「' + item.title + '」' : '已取消事项「' + item.title + '」';
      const holdsSlot = Y7.data.runtime.slots.used.some((entry) => entry.workItemId === item.id);
      if (Y7.atLeast('s3') && (holdsSlot || wasQueued)) {
        const before = Y7.data.runtime.queue.map((entry) => entry.workItemId);
        paths = paths.concat(Y7.runtime.release(item.id));
        const promoted = before.filter((id) => id !== item.id && !Y7.data.runtime.queue.some((entry) => entry.workItemId === id));
        if (promoted.length) message += '；「' + Y7.raw.workItem(promoted[0]).title + '」取得执行槽位';
      }
      return { ok: true, message, paths };
    });
  }

  // ---------------------------------------------------------------------------
  // 启动

  Y7.start = function start() {
    if (!Y7.data) throw new Error('示例数据未加载：js/data.js 需要定义 Y7.data');
    initialData = Y7.clone(Y7.data);
    dom.sidebar = document.getElementById('y7-sidebar');
    dom.topbar = document.getElementById('y7-topbar');
    dom.tabs = document.getElementById('y7-tabs');
    dom.content = document.getElementById('y7-content');
    dom.toolbar = document.getElementById('y7-toolbar');
    dom.modal = document.getElementById('y7-modal-root');
    dom.toast = document.getElementById('y7-toast-root');
    Object.keys(dom).forEach((key) => {
      if (!dom[key]) throw new Error('index.html 缺少外壳元素：' + key);
    });
    Y7.dom = dom;
    applyTheme();
    document.documentElement.classList.toggle('is-annotate', Y7.state.annotate);
    document.addEventListener('click', onClick);
    document.addEventListener('change', onChange);
    document.addEventListener('input', onInput);
    document.addEventListener('keydown', onKeydown);
    window.addEventListener('hashchange', handleRoute);
    Y7.bus.on('data-changed', onDataChanged);
    Y7.bus.on('level-changed', () => renderAll(true));
    Y7.bus.on('annotate-changed', () => renderAll(true));
    handleRoute();
  };

  registerCoreActions();
  registerCoreQueries();
  registerCoreCommands();
})();
