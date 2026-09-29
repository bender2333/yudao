// 示例后端：初始数据与事件日志、按档位与位置折叠、查询与命令的执行、事件流、断开与接口版本的模拟、场景的数据部分。
// 界面层只通过 Y8.api 使用这里（BUILD.md 第 5 节）；真实客户端接入时整个 js/contract 目录被替换
(function () {
  'use strict';
  const Y8 = window.Y8;
  if (!Y8.registry) throw new Error('backend.js 需要先加载 contract/registry.js');

  // ---------------------------------------------------------------------------
  // 数据登记：各 data/*.js 调用 Y8.data.define

  const parts = [];
  Y8.data = {
    define(part) {
      if (!part || typeof part !== 'object') throw new Error('Y8.data.define 需要对象');
      Object.keys(part).forEach((key) => {
        if (!['seed', 'history', 'scenarios'].includes(key)) throw new Error('Y8.data.define 不认识的键：' + key);
      });
      parts.push(part);
    }
  };

  // 合并各文件的 seed：数组拼接，普通对象按键合并（键重复时抛出错误），其他值只能出现一次
  function mergeSeed(target, source, where) {
    Object.keys(source).forEach((key) => {
      const value = source[key];
      if (!(key in target)) {
        target[key] = Y8.clone(value);
        return;
      }
      if (Array.isArray(target[key]) && Array.isArray(value)) {
        target[key] = target[key].concat(Y8.clone(value));
      } else if (Y8.isPlainObject(target[key]) && Y8.isPlainObject(value)) {
        Object.keys(value).forEach((sub) => {
          if (sub in target[key]) throw new Error('示例数据重复：' + where + ' 的 ' + key + '.' + sub);
          target[key][sub] = Y8.clone(value[sub]);
        });
      } else {
        throw new Error('示例数据重复：' + key + '（' + where + '）');
      }
    });
  }

  // ---------------------------------------------------------------------------
  // 状态

  const WINDOW_START = '2026-09-22T15:30:00+08:00';

  let seed = null;          // 初始数据
  let history = [];         // data 文件登记的事件（已编号）
  let log = [];             // 全部事件：history 之后接场景与命令产生的事件
  let state = null;         // 当前数据（按当前档位折叠）
  let delivered = 0;        // 事件流已推送到的位置
  let connected = true;
  let apiVersionOverride = null;
  let stateVersion = 0;     // 当前数据每次变化加一，用于缓存
  const viewCache = new Map();
  const subscribers = [];
  const commandResults = new Map();
  const queryHandlers = {};
  const commandHandlers = {};

  function reached(ev) {
    return Y8.level.reached(ev);
  }

  function isObjectWithVersion(value) {
    return Y8.isPlainObject(value) && typeof value.version === 'number';
  }

  // 沿补丁路径找到被修改的最深的一个带 version 的对象，版本号加一
  function bumpVersion(root, path, patch) {
    const segments = path.split('.');
    let container = root;
    let owner = isObjectWithVersion(root) ? root : null;
    const walk = 'value' in patch ? segments.length - 1 : segments.length;
    for (let i = 0; i < walk; i++) {
      container = Y8.path.get(container, segments[i]);
      if (isObjectWithVersion(container)) owner = container;
    }
    if ('value' in patch) {
      const last = segments[segments.length - 1];
      if (/\[\w+=/.test(last)) {
        const replaced = Y8.path.get(container, last);
        if (isObjectWithVersion(replaced)) owner = replaced;
      }
    }
    if (owner) owner.version += 1;
  }

  function applyEvent(target, ev) {
    (ev.patch || []).forEach((patch) => {
      try {
        Y8.applyPatch(target, patch);
      } catch (error) {
        throw new Error('事件 ' + ev.position + '（' + ev.type + '，' + ev.at + '）的补丁无法应用：' + error.message);
      }
      bumpVersion(target, patch.path, patch);
    });
  }

  function fold(upTo) {
    const out = Y8.clone(seed);
    for (const ev of log) {
      if (upTo !== undefined && ev.position > upTo) break;
      if (reached(ev)) applyEvent(out, ev);
    }
    return out;
  }

  function refold() {
    state = fold();
    stateVersion += 1;
    viewCache.clear();
  }

  function head() {
    return log.length ? log[log.length - 1].position : 0;
  }

  // 当前档位下最后一条已折叠的事件的位置
  function reachedHead(upTo) {
    for (let i = log.length - 1; i >= 0; i--) {
      const ev = log[i];
      if (upTo !== undefined && ev.position > upTo) continue;
      if (reached(ev)) return ev.position;
    }
    return 0;
  }

  // ---------------------------------------------------------------------------
  // 解析：去掉档位范围之外与尚未出现的对象（BUILD.md 第 5.5 节规则 1、2）

  function makeVisible(timeMs) {
    return function visible(obj) {
      if (!Y8.isPlainObject(obj)) return true;
      if (!Y8.level.reached(obj)) return false;
      if (timeMs !== null && obj.born_at && Y8.time.ms(obj.born_at) > timeMs) return false;
      return true;
    };
  }

  function resolveTree(value, visible) {
    if (Array.isArray(value)) return value.filter(visible).map((item) => resolveTree(item, visible));
    if (!Y8.isPlainObject(value)) return value;
    const out = {};
    Object.keys(value).forEach((key) => {
      if ((key === 'level' || key === 'until') && Y8.isLevel(value[key])) return;
      const item = value[key];
      if (Y8.isPlainObject(item) && !visible(item)) return;
      out[key] = resolveTree(item, visible);
    });
    return out;
  }

  function strip(ev) {
    const out = {};
    ['position', 'event_id', 'type', 'at', 'project_id', 'work_item_id', 'run_id', 'department', 'role', 'actor', 'command_id', 'label', 'payload']
      .forEach((key) => { out[key] = key in ev ? Y8.clone(ev[key]) : null; });
    if (!out.payload) out.payload = {};
    return out;
  }

  function eventMatches(ev, filter) {
    if (!filter) return true;
    const test = (value, want) => want === undefined || want === null || (Array.isArray(want) ? want.includes(value) : value === want);
    return test(ev.project_id, filter.project) && test(ev.work_item_id, filter.work_item) && test(ev.run_id, filter.run) &&
      test(ev.department, filter.department) && test(ev.type, filter.types);
  }

  // 数据视图：查询与命令的处理函数读取它
  function makeDb(raw, position, time) {
    const data = resolveTree(raw, makeVisible(time ? Y8.time.ms(time) : null));
    const find = (list, id) => (data[list] || []).find((item) => item.id === id) || null;
    const db = {
      data,
      raw: null,
      position,
      now: time || data.now,
      atLeast: (level) => Y8.level.atLeast(level),
      project: (id) => find('projects', id),
      workItem: (id) => find('work_items', id),
      run: (id) => find('runs', id),
      runOf(workItemId) {
        const item = find('work_items', workItemId);
        return item && item.run_id ? find('runs', item.run_id) : null;
      },
      workItemsOf: (projectId) => (data.work_items || []).filter((item) => item.project_id === projectId),
      decision: (id) => find('decisions', id),
      machine: (id) => find('machines', id),
      settings: (projectId) => (data.project_settings && data.project_settings[projectId]) || null,
      log(filter) {
        const timeMs = time ? Y8.time.ms(time) : null;
        return log
          .filter((ev) => ev.position <= position && reached(ev) && !ev.silent && (timeMs === null || Y8.time.ms(ev.at) <= timeMs))
          .filter((ev) => eventMatches(ev, filter))
          .map(strip);
      }
    };
    return db;
  }

  function currentView() {
    const key = 'now|' + Y8.level.current() + '|' + stateVersion;
    if (!viewCache.has(key)) viewCache.set(key, makeDb(state, reachedHead(), null));
    return viewCache.get(key);
  }

  function viewAt(position) {
    const p = Number(position);
    if (!Number.isInteger(p) || p < 0 || p > head()) throw new Error('回放位置无效：' + position);
    const key = 'at|' + Y8.level.current() + '|' + p + '|' + stateVersion;
    if (!viewCache.has(key)) {
      const ev = log.find((item) => item.position === p);
      const time = ev ? ev.at : WINDOW_START;
      viewCache.set(key, makeDb(fold(p), p, time));
    }
    return viewCache.get(key);
  }

  // ---------------------------------------------------------------------------
  // 追加事件与事件流

  function append(spec, opts) {
    const o = opts || {};
    if (!spec || !spec.type) throw new Error('事件缺少 type');
    if (!Y8.registry.has('event', spec.type)) throw new Error('事件种类没有登记：' + spec.type);
    const ev = Object.assign({
      project_id: null, work_item_id: null, run_id: null, department: null, role: null,
      actor: o.actor || 'system', command_id: o.command_id || null, payload: {}, patch: []
    }, Y8.clone(spec));
    ev.position = head() + 1;
    ev.event_id = 'ev-' + ev.position;
    ev.at = spec.at || state.now;
    if (!ev.label) ev.label = ev.type;
    if (o.silent) ev.silent = true;
    log.push(ev);
    if (reached(ev)) {
      applyEvent(state, ev);
      stateVersion += 1;
      viewCache.clear();
    }
    return ev;
  }

  function deliverUpTo(position) {
    if (!connected) return;
    const due = log.filter((ev) => ev.position > delivered && ev.position <= position);
    delivered = Math.max(delivered, position);
    due.forEach((ev) => {
      if (!reached(ev) || ev.silent) return;
      const out = strip(ev);
      subscribers.slice().forEach((sub) => {
        if (eventMatches(out, sub.filter)) sub.fn(Y8.clone(out));
      });
    });
  }

  // ---------------------------------------------------------------------------
  // 能力清单

  function capabilities() {
    const level = (entry) => Y8.level.atLeast(entry.level);
    const r = Y8.registry;
    const queries = Object.keys(r.queries).filter((name) => level(r.queries[name]) && queryHandlers[name]);
    const commands = Object.keys(r.commands).filter((name) => level(r.commands[name]) && commandHandlers[name]);
    const overlays = Object.keys(r.overlays)
      .filter((id) => level(r.overlays[id]) && r.overlays[id].queries.every((name) => queries.includes(name)))
      .map((id) => ({ id, label: r.overlays[id].label, queries: r.overlays[id].queries.slice() }));
    const dep = state.deployment;
    return {
      deployment: {
        log_id: dep.log_id, boot_id: dep.boot_id, service_version: dep.service_version,
        api_version: apiVersionOverride === null ? dep.api_version : apiVersionOverride, access: dep.access
      },
      queries: queries.map((name) => ({ name, replay: Boolean(r.queries[name].replay) })),
      commands: commands.map((name) => ({ name, reasons: r.commands[name].reasons.slice(), pending: Boolean(r.commands[name].pending) })),
      decisions: Object.keys(r.decisions).filter((kind) => level(r.decisions[kind])),
      event_types: Object.keys(r.events).filter((type) => level(r.events[type])),
      overlays,
      stream: { live: true }
    };
  }

  function requireConnected() {
    if (!connected) throw new Error('与控制主机的连接已断开');
  }

  // ---------------------------------------------------------------------------
  // 接口

  Y8.api = {
    // 与控制主机的连接状态（真实客户端取事件流连接的状态）
    connected: () => connected,
    capabilities() {
      requireConnected();
      return capabilities();
    },
    query(name, params) {
      requireConnected();
      const p = params || {};
      if (!Y8.registry.has('query', name)) throw new Error('查询没有登记：' + name);
      const entry = Y8.registry.entry('query', name);
      if (!Y8.level.atLeast(entry.level)) throw new Error('查询「' + name + '」在当前档位没有部署');
      const fn = queryHandlers[name];
      if (!fn) throw new Error('查询没有处理函数：' + name);
      let db;
      if (p.at !== undefined && p.at !== null && p.at !== '') {
        if (!entry.replay) throw new Error('查询「' + name + '」不接受 at');
        db = viewAt(p.at);
      } else {
        db = currentView();
      }
      const data = fn(p, db);
      if (data === undefined) throw new Error('查询「' + name + '」没有返回结果');
      return { position: db.position, data: Y8.clone(data) };
    },
    command(name, params) {
      requireConnected();
      const p = Object.assign({}, params || {});
      if (!Y8.registry.has('command', name)) throw new Error('命令没有登记：' + name);
      const entry = Y8.registry.entry('command', name);
      if (!Y8.level.atLeast(entry.level)) throw new Error('命令「' + name + '」在当前档位没有部署');
      const fn = commandHandlers[name];
      if (!fn) throw new Error('命令没有处理函数：' + name);
      const commandId = p.command_id || Y8.uid('cmd');
      if (commandResults.has(commandId)) return Object.assign({}, commandResults.get(commandId), { duplicate: true });
      const db = Object.assign({}, currentView(), { raw: state });
      const result = fn(p, db);
      if (!result || (!result.reject && !Array.isArray(result.events))) throw new Error('命令「' + name + '」的处理函数需要返回 { reject } 或 { events }');
      if (result.reject) {
        if (!entry.reasons.includes(result.reject.reason)) throw new Error('命令「' + name + '」返回了没有声明的拒绝原因：' + result.reject.reason);
        return { accepted: false, command_id: commandId, reason: result.reject.reason, message: result.reject.message, current_version: result.reject.current_version };
      }
      const events = result.events.map((spec) => append(spec, { actor: 'user:local', command_id: commandId }));
      const position = events.length ? events[events.length - 1].position : reachedHead();
      const out = { accepted: true, command_id: commandId, position, refs: result.refs || {}, message: result.message || null, duplicate: false };
      commandResults.set(commandId, out);
      setTimeout(() => deliverUpTo(position), Y8.backend.latency);
      return out;
    },
    subscribe(filter, fn, opts) {
      if (typeof fn !== 'function') throw new Error('subscribe 需要回调函数');
      const sub = { filter: filter || null, fn };
      subscribers.push(sub);
      const after = opts && opts.after !== undefined && opts.after !== null ? Number(opts.after) : null;
      if (after !== null && connected) {
        log.filter((ev) => ev.position > after && ev.position <= delivered && reached(ev) && !ev.silent)
          .map(strip).filter((ev) => eventMatches(ev, sub.filter)).forEach((ev) => fn(ev));
      }
      return () => {
        const index = subscribers.indexOf(sub);
        if (index >= 0) subscribers.splice(index, 1);
      };
    }
  };

  Y8.CLIENT_API_VERSION = 1;

  // 界面层按能力清单决定显示什么
  let capCache = null;
  Y8.cap = {
    refresh() { capCache = connected ? capabilities() : capCache; return capCache; },
    get() { return capCache || Y8.cap.refresh(); },
    query: (name) => Y8.cap.get().queries.some((item) => item.name === name),
    command: (name) => Y8.cap.get().commands.some((item) => item.name === name),
    decision: (kind) => Y8.cap.get().decisions.includes(kind),
    overlay: (id) => Y8.cap.get().overlays.some((item) => item.id === id)
  };

  // ---------------------------------------------------------------------------
  // 检查（BUILD.md 第 5.5 节）

  function validate() {
    const s = seed;
    const ids = new Map();
    const need = (cond, message) => { if (!cond) throw new Error('示例数据检查未通过：' + message); };
    ['projects', 'work_items', 'runs', 'decisions', 'machines', 'materials'].forEach((list) => {
      (s[list] || []).forEach((item) => {
        need(item && item.id, list + ' 中有对象缺少 id');
        need(!ids.has(item.id), '标识重复：' + item.id + '（' + list + '、' + ids.get(item.id) + '）');
        ids.set(item.id, list);
      });
    });
    const has = (list, id) => (s[list] || []).some((item) => item.id === id);
    (s.work_items || []).forEach((item) => {
      need(has('projects', item.project_id), '事项 ' + item.id + ' 的项目不存在：' + item.project_id);
      if (item.run_id) need(has('runs', item.run_id), '事项 ' + item.id + ' 的 run 不存在：' + item.run_id);
    });
    (s.runs || []).forEach((run) => {
      need(has('work_items', run.work_item_id), 'run ' + run.id + ' 的事项不存在：' + run.work_item_id);
    });
    (s.decisions || []).forEach((dec) => {
      need(Y8.registry.has('decision', dec.kind), '决定请求 ' + dec.id + ' 的种类没有登记：' + dec.kind);
      need(has('projects', dec.project_id), '决定请求 ' + dec.id + ' 的项目不存在');
      if (dec.work_item_id) need(has('work_items', dec.work_item_id), '决定请求 ' + dec.id + ' 的事项不存在');
      if (dec.run_id) need(has('runs', dec.run_id), '决定请求 ' + dec.id + ' 的 run 不存在');
      need(Array.isArray(dec.options) && dec.options.length, '决定请求 ' + dec.id + ' 没有选项');
      need(dec.materials && typeof dec.materials === 'object', '决定请求 ' + dec.id + ' 没有材料');
    });
    (s.materials || []).forEach((m) => need(has('projects', m.project_id), '资料 ' + m.id + ' 的项目不存在'));
    Object.keys(s.project_settings || {}).forEach((pid) => need(has('projects', pid), '项目设置的项目不存在：' + pid));
    history.forEach((ev) => {
      need(Y8.time.ms(ev.at) <= Y8.time.ms(s.now), '事件晚于现在：' + ev.type + ' ' + ev.at);
      if (ev.project_id) need(has('projects', ev.project_id), '事件 ' + ev.position + ' 的项目不存在：' + ev.project_id);
      if (ev.work_item_id) need(has('work_items', ev.work_item_id), '事件 ' + ev.position + ' 的事项不存在：' + ev.work_item_id);
      if (ev.run_id) need(has('runs', ev.run_id), '事件 ' + ev.position + ' 的 run 不存在：' + ev.run_id);
      need(ev.label && ev.label !== ev.type, '事件 ' + ev.position + '（' + ev.type + '）缺少中文说明 label');
    });
    // 窗口内出现的对象要有同一时间的出现事件
    const appear = (list, types, keyOf) => (s[list] || []).filter((item) => item.born_at).forEach((item) => {
      const found = history.some((ev) => types.includes(ev.type) && keyOf(ev) === item.id && ev.at === item.born_at);
      need(found, list + ' 中的 ' + item.id + ' 带 born_at，但没有同一时间的出现事件（' + types.join('、') + '）');
    });
    appear('projects', ['project_registered'], (ev) => ev.project_id);
    appear('work_items', ['work_item_created', 'x_repair_created'], (ev) => ev.work_item_id);
    appear('runs', ['run_created', 'work_item_created', 'x_repair_created', 'onboarding_revision_started'], (ev) => ev.run_id);
    appear('decisions', ['x_decision_issued', 'project_decision_requested'], (ev) => ev.payload && ev.payload.decision_id);
    // 场景
    const nos = new Set();
    scenarioList.forEach((sc) => {
      need(sc.id && sc.name && Number.isInteger(sc.no), '场景缺少 id、name 或 no');
      need(!nos.has(sc.no), '场景编号重复：' + sc.no);
      nos.add(sc.no);
      need(Y8.isLevel(sc.level || 'ui'), '场景 ' + sc.id + ' 的档位无效');
      need(Array.isArray(sc.steps) && sc.steps.length, '场景 ' + sc.id + ' 没有步骤');
      sc.steps.forEach((st, i) => {
        need(st.event || st.act || (st.go && st.label), '场景 ' + sc.id + ' 第 ' + (i + 1) + ' 步没有 event、act，也不是带 label 的跳转');
        if (st.event) need(Y8.registry.has('event', st.event.type), '场景 ' + sc.id + ' 第 ' + (i + 1) + ' 步的事件种类没有登记：' + st.event.type);
      });
    });
    // 在全部档位上折叠一次，确认每条补丁都能应用
    const saved = Y8.level.current();
    const probe = { level: 'S5' };
    Y8.LEVELS.forEach((lv) => {
      probe.level = lv;
      const out = Y8.clone(seed);
      log.forEach((ev) => {
        const ok = (!ev.level || Y8.level.compare(lv, ev.level) >= 0) && (!ev.until || Y8.level.compare(lv, ev.until) < 0);
        if (ok) applyEvent(out, ev);
      });
    });
    need(Y8.level.current() === saved, '检查改变了档位');
  }

  // ---------------------------------------------------------------------------
  // 初始化、场景与模拟

  let scenarioList = [];

  function lastSeenPosition(iso) {
    const t = Y8.time.ms(iso);
    let pos = 0;
    history.forEach((ev) => { if (Y8.time.ms(ev.at) <= t) pos = ev.position; });
    return pos;
  }

  function buildLog() {
    log = history.map((ev) => Y8.clone(ev));
    refold();
    delivered = head();
  }

  Y8.backend = {
    latency: 500,
    WINDOW_START,
    query(name, fn) {
      if (!Y8.registry.has('query', name)) throw new Error('查询没有登记：' + name);
      if (queryHandlers[name]) throw new Error('查询处理函数重复：' + name);
      queryHandlers[name] = fn;
    },
    command(name, fn) {
      if (!Y8.registry.has('command', name)) throw new Error('命令没有登记：' + name);
      if (commandHandlers[name]) throw new Error('命令处理函数重复：' + name);
      commandHandlers[name] = fn;
    },
    init() {
      if (!parts.length) throw new Error('没有示例数据：js/contract/data/*.js 需要调用 Y8.data.define');
      seed = {};
      const events = [];
      scenarioList = [];
      parts.forEach((part, index) => {
        if (part.seed) mergeSeed(seed, part.seed, '第 ' + (index + 1) + ' 个数据文件');
        (part.history || []).forEach((ev, order) => events.push({ ev, index, order }));
        (part.scenarios || []).forEach((sc) => scenarioList.push(sc));
      });
      ['now', 'deployment', 'home', 'system'].forEach((key) => {
        if (!seed[key]) throw new Error('示例数据缺少 ' + key + '（由 data/system.js 登记）');
      });
      events.sort((a, b) => (Y8.time.ms(a.ev.at) - Y8.time.ms(b.ev.at)) || (a.index - b.index) || (a.order - b.order));
      history = events.map((item, i) => {
        const ev = Y8.clone(item.ev);
        if (!ev.type || !ev.at) throw new Error('历史事件缺少 type 或 at');
        if (!Y8.registry.has('event', ev.type)) throw new Error('历史事件的种类没有登记：' + ev.type);
        return Object.assign({ project_id: null, work_item_id: null, run_id: null, department: null, role: null, actor: 'system', command_id: null, payload: {}, patch: [] },
          ev, { position: i + 1, event_id: 'ev-' + (i + 1) });
      });
      if (seed.home.last_seen_position === undefined) seed.home.last_seen_position = lastSeenPosition(seed.home.last_seen_at);
      scenarioList.sort((a, b) => a.no - b.no);
      buildLog();
      validate();
    },
    validate,
    head,
    reachedHead: () => reachedHead(),
    // 档位切换以后重新折叠
    refold() {
      refold();
      Y8.cap.refresh();
    },
    scenarios: () => scenarioList,
    // 回到默认数据与事件日志（选择场景、重置）
    reset() {
      buildLog();
      commandResults.clear();
      Y8.cap.refresh();
    },
    // 场景的准备：作为一条不进入报告、不推送的事件应用
    setup(patches, label) {
      if (!patches || !patches.length) return null;
      const ev = append({ type: 'x_scenario_setup', label: label || '场景准备', patch: patches }, { silent: true });
      delivered = ev.position;
      return ev;
    },
    // 场景的一步：追加事件并立即推送
    emit(spec) {
      const ev = append(spec, { actor: spec.actor || 'system' });
      deliverUpTo(ev.position);
      return strip(ev);
    },
    sim: {
      connected: () => connected,
      setConnected(on) {
        connected = Boolean(on);
        if (connected) {
          Y8.cap.refresh();
          deliverUpTo(head());
        }
        Y8.bus.emit('connection-changed', connected);
      },
      apiVersion: () => (apiVersionOverride === null ? state.deployment.api_version : apiVersionOverride),
      setApiVersion(n) {
        apiVersionOverride = n === null || n === undefined ? null : Number(n);
        Y8.cap.refresh();
        Y8.bus.emit('api-version-changed', Y8.backend.sim.apiVersion());
      },
      setLastSeen(iso) {
        state.home.last_seen_at = iso;
        state.home.last_seen_position = lastSeenPosition(iso);
        seed.home.last_seen_at = iso;
        seed.home.last_seen_position = state.home.last_seen_position;
        stateVersion += 1;
        viewCache.clear();
        Y8.bus.emit('last-seen-changed', iso);
      }
    }
  };

  Y8.bus.on('level-changed', () => Y8.backend.refold());
})();
