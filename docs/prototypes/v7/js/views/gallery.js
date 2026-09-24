// 动作图鉴（原型专用，#/gallery）：按角色与动作列出全部小人动画，每项写明驱动它的事实与所属阶段；
// 另有部门房间与循环画面的预览，旁边列出事件按钮，逐个检查画面。
(function () {
  const Y7 = window.Y7;
  const P = Y7.pixel;
  if (!P || !P.createVignette) throw new Error('gallery.js 需要先加载 js/pixel/*.js');
  const esc = Y7.esc;

  const TAG_OF_LEVEL = { now: '当前', s3: 'Stage 3', s4: 'Stage 4', s5: 'Stage 5' };
  const ROLE_ORDER = [
    'product.agent', 'engineering.agent', 'quality.agent', 'courier.courier:2',
    'product.manager', 'product.architect', 'product.explorer',
    'engineering.manager', 'engineering.architect', 'engineering.developer', 'engineering.explorer',
    'quality.manager', 'quality.tester', 'quality.explorer',
    'operations.ops', 'meta.observer'
  ];
  const ROLE_LOOK = {
    agent: '部门颜色的制服、胸前工牌、头顶一撮翘发',
    manager: '部门颜色的西装、红领带、手拿记录板',
    architect: '部门颜色的毛衣、圆眼镜、手拿图纸卷',
    developer: '部门颜色的连帽衫、耳机',
    explorer: '部门颜色的马甲、宽檐帽、背包',
    tester: '白大褂、部门颜色的衬衫、手拿放大镜',
    ops: '运维颜色的连体工作服、工具腰带、耳麦',
    observer: '灰色外套、眼镜、记录板',
    courier: '邮差制服与帽子，背包颜色与事项颜色一致'
  };
  const DEPT_OPTIONS = [['product', '产品'], ['engineering', '工程'], ['quality', '质检'], ['operations', '运维（Stage 5）']];
  const LEVEL_OPTIONS = [['now', '当前'], ['s3', 'Stage 3 与 D24'], ['s4', 'Stage 4'], ['s5', 'Stage 5']];
  const STATUS_OPTIONS = [
    ['working', '工作中'], ['idle', '未工作'], ['asking', '等待回答'], ['paused', '已暂停'], ['failed', '失败'], ['done', '已完成'],
    ['cancelled', '已取消'], ['interrupted', '中断（3.1）'], ['pending_verification', '待核实（3.1）'], ['waiting_resume', '待恢复（3.1）']
  ];

  // 页面选择，重新渲染后保留
  const sel = { role: '', stage: 'all', dept: 'engineering', roomLevel: 'now', status: 'working', loopLevel: 's3', preset: 'normal', focus: '' };
  let live = null;

  // ---------------------------------------------------------------------------
  // 预览用的示例模型（原型专用页面的固定内容）

  const CRT = {
    product: { target: '空输入时给出提示', model: 'mimo-v2.5', protocol: 'Responses', cycle: 1 },
    engineering: { target: '类别按首次出现顺序输出', model: 'glm-5', protocol: 'Chat Completions', cycle: 3 },
    quality: { target: '核验交付 r3', model: 'kimi-k2.6', protocol: 'Chat Completions', cycle: 2 },
    operations: { target: '排班页面加载超时', model: 'glm-5', protocol: 'Chat Completions', cycle: 1 }
  };
  const ROLES_S4 = {
    product: [
      { id: 'pm', name: '产品部门经理', kind: 'manager', status: 'working', task: '整理需求' },
      { id: 'pa', name: '产品架构师', kind: 'architect', status: 'assigned', task: '拆分验收条件' },
      { id: 'px', name: '产品探索者', kind: 'explorer', status: 'idle', task: '调研同类工具' }
    ],
    engineering: [
      { id: 'em', name: '工程经理', kind: 'manager', status: 'working', task: '分派计划' },
      { id: 'ea', name: '工程架构师', kind: 'architect', status: 'working', task: '确定排序方式' },
      { id: 'ed', name: '开发者', kind: 'developer', status: 'working', task: '修改汇总函数' },
      { id: 'ex', name: '工程探索者', kind: 'explorer', status: 'assigned', task: '查阅 CSV 规范' }
    ],
    quality: [
      { id: 'qm', name: '质检经理', kind: 'manager', status: 'working', task: '安排核验' },
      { id: 'qt', name: '测试工程师', kind: 'tester', status: 'working', task: '运行回归测试' },
      { id: 'qx', name: '质检探索者', kind: 'explorer', status: 'idle', task: '查阅导出格式' }
    ]
  };
  function roomLevel() { return sel.dept === 'operations' ? 's5' : sel.roomLevel; }
  function roomModel() {
    const dept = sel.dept, level = roomLevel();
    const s4 = level === 's4' || level === 's5';
    let roles;
    if (dept === 'operations') roles = [{ id: 'ops', name: '运维部门 Agent', kind: 'ops', status: 'working', task: '观察运行指标' }];
    else if (s4) roles = ROLES_S4[dept].map((r) => Object.assign({}, r));
    else roles = [{ id: 'agent', name: P.ROLE_NAMES[dept + '.agent'], kind: 'agent', status: 'working' }];
    const status = sel.status;
    const door = { paused: '已暂停', failed: '失败：provider_error', done: '已完成', cancelled: '已取消', interrupted: '中断', pending_verification: '待核实', waiting_resume: '待恢复' }[status] || null;
    return {
      department: dept, level, status, crt: CRT[dept], roles, pose: null, door,
      holdCard: status === 'waiting_resume' ? '凭据被上游拒绝：OPENCODE_GO_KEY' : null,
      pendingTool: status === 'pending_verification' ? 'run_command' : null,
      mailbox: 1, summaries: 2, scrolls: dept === 'product' ? 3 : 0, pinnedNotes: 1, semanticCards: s4 ? 4 : 0,
      version: dept === 'operations' ? 'r3' : null, alarm: false
    };
  }
  function roomEvents() {
    const dept = sel.dept;
    const other = dept === 'product' ? 'engineering' : 'product';
    const s4 = roomLevel() === 's4' || roomLevel() === 's5';
    const r = (id) => (s4 && dept !== 'operations' ? id : null);
    const ev = (type, extra) => Object.assign({ type, department: dept, workItemId: 'w-cat', label: type }, extra || {});
    const list = [
      ['当前', ev('department_activated')], ['当前', ev('context_assembled')], ['当前', ev('model_requested')], ['当前', ev('model_request_serialized')],
      ['当前', ev('model_stream_progress', { payload: { text: '按首次出现顺序输出类别' } })], ['当前', ev('model_attempt_finished')],
      ['当前', ev('model_retry_scheduled', { payload: { n: 2, of: 3 } })], ['当前', ev('model_attempt_failed')],
      ['当前', ev('tool_started', { tool: 'search' })], ['当前', ev('tool_started', { tool: 'read_range' })], ['当前', ev('tool_started', { tool: 'read_file' })],
      ['当前', ev('tool_started', { tool: 'edit_range' })], ['当前', ev('tool_started', { tool: 'write_file' })], ['当前', ev('tool_started', { tool: 'run_command' })],
      ['当前', ev('tool_called', { tool: 'run_command', payload: { exitCode: 0 } })], ['当前', ev('tool_called', { tool: 'run_command', payload: { exitCode: 1 } })],
      ['当前', ev('tool_called', { tool: 'run_command', payload: { timedOut: true } })], ['当前', ev('tool_skipped')],
      ['当前', ev('proposal_submitted')], ['当前', ev('proposal_rejected')],
      ['当前', ev('spec_accepted')], ['当前', ev('contract_accepted')], ['当前', ev('plan_accepted')], ['当前', ev('delivery_accepted')],
      ['当前', ev('tool_started', { tool: 'run_check' })], ['当前', ev('qa_submitted', { payload: { verdict: 'release' } })],
      ['当前', ev('qa_submitted', { payload: { verdict: 'rework_engineering' } })], ['当前', ev('qa_submitted', { payload: { verdict: 'rework_product' } })],
      ['当前', ev('collaboration_requested', { payload: { from: dept, to: other }, note: '本部门发问' })],
      ['当前', ev('collaboration_requested', { department: other, payload: { from: other, to: dept }, note: '别的部门来问' })],
      ['当前', ev('collaboration_responded', { payload: { from: other, to: dept }, note: '本部门回答' })],
      ['当前', ev('collaboration_responded', { department: other, payload: { from: dept, to: other }, note: '收到回答' })],
      ['当前', ev('collaboration_closed', { payload: { from: dept, to: other } })],
      ['当前', ev('department_guidance_received')], ['当前', ev('department_guidance_applied')], ['当前', ev('department_guidance_responded')],
      ['当前', ev('compaction_recorded')], ['当前', ev('compaction_failed')],
      ['当前', ev('transition', { department: other, payload: { from: other, to: dept, artifact: dept === 'quality' ? 'box' : dept === 'engineering' ? 'prd' : dept === 'operations' ? 'release' : 'defect', colorIndex: 2 }, note: '送来' })],
      ['当前', ev('transition', { payload: { from: dept, to: 'quality', artifact: dept === 'product' ? 'prd' : dept === 'quality' ? 'release' : 'box', colorIndex: 2 }, note: '取走' })],
      ['当前', ev('run_paused')], ['当前', ev('run_failed', { payload: { reason: 'provider_error' } })], ['当前', ev('run_done')], ['当前', ev('cancellation_recorded')],
      ['3.1', ev('x_run_interrupted')], ['3.1', ev('x_action_unknown', { payload: { tool: 'run_command' } })],
      ['3.1', ev('x_action_decided', { tool: 'run_command', payload: { actionId: 'a-w4', choice: 'rerun' }, note: '重新执行' })],
      ['3.1', ev('x_action_decided', { tool: 'run_command', payload: { actionId: 'a-w4', choice: 'accept_current' }, note: '按当前实际状态继续' })],
      ['3.1', ev('x_action_decided', { tool: 'run_command', payload: { actionId: 'a-w4', choice: 'stop' }, note: '停止事项' })],
      ['3.1', ev('x_waiting_resume', { payload: { missing: '凭据被上游拒绝：OPENCODE_GO_KEY' } })], ['3.1', ev('x_resume_accepted')]
    ];
    if (dept !== 'operations') {
      const target = { product: 'pa', engineering: 'ed', quality: 'qt' }[dept];
      const explorer = { product: 'px', engineering: 'ex', quality: 'qx' }[dept];
      list.push(
        ['Stage 4', ev('x_role_task_assigned', { payload: { to: r(target) } })], ['Stage 4', ev('x_role_result_returned', { role: r(target) })],
        ['Stage 4', ev('x_explorer_fetch', { role: r(explorer) })], ['Stage 4', ev('x_replanned')], ['Stage 4', ev('x_semantic_recorded')]
      );
    } else {
      list.push(['Stage 5', ev('x_ops_released')], ['Stage 5', ev('x_ops_alarm')], ['Stage 5', ev('x_ops_action_requested', { payload: { kind: '重启服务' } })]);
    }
    return list;
  }

  const LOOP_ITEMS = {
    cat: { id: 'w-cat', title: '类别按首次出现顺序输出', colorIndex: 2, status: 'running', department: 'engineering', cycle: 3, elapsedSec: 2280, limitSec: 7200 },
    sum: { id: 'w-x', title: '报表加总计行', colorIndex: 0, status: 'running', department: 'product', cycle: 1, elapsedSec: 600, limitSec: 7200 },
    empty: { id: 'w-empty', title: '空输入时给出提示', colorIndex: 1, status: 'queued', queuePos: 1 },
    md: { id: 'w-md', title: '导出为 Markdown', colorIndex: 3, status: 'queued', queuePos: 2 },
    head: { id: 'w-head', title: '表头改为中文', colorIndex: 4, status: 'held' },
    shift: { id: 'w-timeout', title: '排班页面加载超时', colorIndex: 5, status: 'running', department: 'operations', cycle: 1, elapsedSec: 300, limitSec: 7200 }
  };
  const LOOP_PRESETS = [
    ['normal', '正常循环', (m) => m],
    ['queue', '并行排队（3.4A）', (m) => m],
    ['interrupted', '中断（3.1）', (m) => { m.items.forEach((it) => { if (it.department) it.status = 'interrupted'; }); }],
    ['pending', '待核实（3.1）', (m) => { m.items[0].status = 'pending_verification'; }],
    ['waiting', '待恢复（3.1）', (m) => { m.items[1].status = 'waiting_resume'; m.items[1].sign = '待恢复：凭据缺失'; }],
    ['terminal', '终止的牌子', (m) => { m.items[0].status = 'failed'; m.items[0].sign = '失败：provider_error'; m.items[1].status = 'paused'; }],
    ['asking', '询问与回答', (m) => { m.items[0].status = 'asking'; m.openRequests = [{ from: 'engineering', to: 'product', workItemId: 'w-cat' }]; }],
    ['time', '接近时间上限', (m) => { m.items[0].elapsedSec = 6700; }],
    ['ops', '运维告警与判定（Stage 5）', (m) => { if (m.ops) m.ops.alarm = true; }]
  ];
  function loopModel() {
    const level = sel.preset === 'ops' ? 's5' : (sel.preset === 'queue' || ['interrupted', 'pending', 'waiting'].includes(sel.preset)) && sel.loopLevel === 'now' ? 's3' : sel.loopLevel;
    const s3 = level !== 'now';
    const items = [LOOP_ITEMS.cat, LOOP_ITEMS.sum].concat(s3 ? [LOOP_ITEMS.empty, LOOP_ITEMS.md, LOOP_ITEMS.head] : []).concat(level === 's5' ? [LOOP_ITEMS.shift] : []).map((x) => Object.assign({}, x));
    const m = {
      level, focusId: null, items, openRequests: [],
      slots: { total: 3, used: 2 },
      shelves: { adopted: ['r1', 'r2'], held: s3 ? [{ id: 'w-head', label: '表头改为中文' }] : [] },
      ops: level === 's5' ? { running: true, alarm: false, version: 'r3' } : null,
      observer: level === 's5' ? { active: true, last: { result: 'pass', confidence: 0.82 } } : null
    };
    LOOP_PRESETS.find((p) => p[0] === sel.preset)[2](m);
    return m;
  }
  function loopEvents() {
    const e = (type, extra) => Object.assign({ type, label: type }, extra || {});
    return [
      ['当前', e('user_input_received', { workItemId: 'w-cat' })],
      ['当前', e('department_activated', { department: 'quality', workItemId: 'w-cat' })],
      ['当前', e('transition', { workItemId: 'w-x', payload: { from: 'product', to: 'engineering', artifact: 'prd' }, note: '产品到工程' })],
      ['当前', e('transition', { workItemId: 'w-cat', payload: { from: 'engineering', to: 'quality', artifact: 'box' }, note: '工程到质检' })],
      ['当前', e('qa_submitted', { department: 'quality', workItemId: 'w-cat', payload: { verdict: 'rework_engineering' } })],
      ['当前', e('transition', { workItemId: 'w-cat', payload: { from: 'quality', to: 'engineering', artifact: 'defect' }, note: '退回工程' })],
      ['当前', e('qa_submitted', { department: 'quality', workItemId: 'w-cat', payload: { verdict: 'release' } })],
      ['当前', e('transition', { workItemId: 'w-cat', payload: { from: 'quality', to: 'library', artifact: 'release' }, note: '送到成果库' })],
      ['当前', e('deliverable_adopted', { workItemId: 'w-cat', payload: { version: 'r3' } })],
      ['当前', e('collaboration_requested', { workItemId: 'w-cat', payload: { from: 'engineering', to: 'product' } })],
      ['当前', e('collaboration_responded', { workItemId: 'w-cat', payload: { from: 'engineering', to: 'product' } })],
      ['当前', e('collaboration_closed', { workItemId: 'w-cat', payload: { from: 'engineering', to: 'product' } })],
      ['当前', e('model_requested', { department: 'engineering', workItemId: 'w-cat' })],
      ['当前', e('run_done', { workItemId: 'w-cat' })], ['当前', e('run_failed', { workItemId: 'w-x', payload: { reason: 'provider_error' } })],
      ['当前', e('run_paused', { workItemId: 'w-x' })], ['当前', e('cancellation_recorded', { workItemId: 'w-x' })],
      ['3.4B', e('adoption_held', { workItemId: 'w-md', payload: { label: '导出为 Markdown' } })],
      ['3.4A', e('x_queued', { workItemId: 'w-empty' })], ['3.4A', e('x_slot_acquired', { workItemId: 'w-empty' })], ['3.4A', e('x_queue_cancelled', { workItemId: 'w-md' })],
      ['3.1', e('x_run_interrupted', { workItemId: 'w-cat', department: 'engineering' })],
      ['3.1', e('x_action_unknown', { workItemId: 'w-cat', department: 'engineering', payload: { tool: 'run_command' } })],
      ['3.1', e('x_action_decided', { workItemId: 'w-cat', department: 'engineering', tool: 'run_command', payload: { actionId: 'a-w4', choice: 'rerun' } })],
      ['3.1', e('x_waiting_resume', { workItemId: 'w-x', department: 'product', payload: { missing: '凭据缺失' } })],
      ['3.1', e('x_resume_accepted', { workItemId: 'w-cat', department: 'engineering' })],
      ['Stage 5', e('x_ops_released', { department: 'operations', workItemId: 'w-timeout' })],
      ['Stage 5', e('x_ops_alarm', { department: 'operations', workItemId: 'w-timeout' })],
      ['Stage 5', e('x_judgment_recorded', { payload: { result: 'uncertain', confidence: 0.54, from: 'engineering', to: 'quality' } })]
    ];
  }

  // ---------------------------------------------------------------------------
  // 渲染

  function options(list, value) {
    return list.map(([v, label]) => '<option value="' + esc(v) + '"' + (v === value ? ' selected' : '') + '>' + esc(label) + '</option>').join('');
  }
  function select(act, list, value, label) {
    return '<label class="y7-field is-inline y7-g-ctl"><span>' + esc(label) + '</span><select class="y7-select" data-act="' + act + '">' + options(list, value) + '</select></label>';
  }
  function roleName(key) { return P.ROLE_NAMES[key.split(':')[0]] || key; }
  function roleOptions() {
    return [['', '按动作自动选择']].concat(ROLE_ORDER.map((k) => [k, roleName(k) + '（' + TAG_OF_LEVEL[P.ROLE_LEVELS[k.split(':')[0]]] + '）']));
  }

  function roleCards() {
    return '<div class="y7-g-grid is-roles">' + ROLE_ORDER.map((key) => {
      const base = key.split(':')[0];
      const kind = P.parseSpriteKey(key).kind;
      return '<figure class="y7-g-card">' +
        '<div class="y7-g-stage"><canvas data-vig="role" data-sprite="' + esc(key) + '" aria-label="' + esc(roleName(key)) + '"></canvas></div>' +
        '<figcaption><div class="y7-g-name">' + esc(roleName(key)) + Y7.ui.tag(TAG_OF_LEVEL[P.ROLE_LEVELS[base]]) + '</div>' +
        '<p class="y7-g-desc">' + esc(ROLE_LOOK[kind]) + '</p></figcaption></figure>';
    }).join('') + '</div>';
  }

  function stageClass(tag) { return 'is-stage-' + String(tag).replace(/[^a-z0-9]/gi, '').toLowerCase(); }

  function frameStrip(action, sprite) {
    const def = P.ACTIONS[action] || P.BASE_MOTIONS[action];
    const anim = P.ANIMS[def.anim];
    return '<details class="y7-g-frames"><summary>逐帧（' + anim.frames.length + ' 帧，动作「' + esc(def.anim) + '」）</summary><div class="y7-g-strip">' +
      anim.frames.map((f, i) => '<canvas width="64" height="80" data-frame="' + i + '" data-anim="' + esc(def.anim) + '" data-sprite="' + esc(sprite) + '" title="' + esc(f[0] + ' · ' + f[1] + ' 毫秒') + '"></canvas>').join('') +
      '</div></details>';
  }

  function actionCard(name, def, isBase) {
    const sprite = sel.role && !['queue', 'judge'].includes(name) ? sel.role : P.VIGNETTE_SPRITES[name];
    const tag = isBase ? '当前' : def.tag;
    const events = isBase ? '' : Object.keys(P.EVENT_ACTIONS).filter((k) => {
      const e = P.EVENT_ACTIONS[k];
      return e === name || (typeof e === 'object' && Object.values(e.map).includes(name));
    });
    return '<figure class="y7-g-card ' + stageClass(tag) + '" data-stage="' + esc(tag) + '">' +
      '<div class="y7-g-stage"><canvas data-vig="' + esc(name) + '" data-sprite="' + esc(sprite) + '" aria-label="' + esc(def.label) + '"></canvas></div>' +
      '<figcaption><div class="y7-g-name">' + esc(def.label) + Y7.ui.tag(tag) + '</div>' +
      (isBase
        ? '<dl class="y7-g-facts"><dt>用途</dt><dd>' + esc(def.fact) + '</dd></dl>'
        : '<dl class="y7-g-facts"><dt>事实</dt><dd>' + esc(def.fact) + '</dd><dt>来源</dt><dd class="y7-g-mono">' + esc(def.source) + '</dd>' +
          '<dt>小人动作</dt><dd>' + esc(def.action) + '</dd><dt>房间变化</dt><dd>' + esc(def.room) + '</dd>' +
          (events.length ? '<dt>对照表</dt><dd class="y7-g-mono">' + esc(events.join('、')) + ' → ' + esc(name) + '</dd>' : '') + '</dl>') +
      frameStrip(name, sprite) +
      '</figcaption></figure>';
  }

  function actionCards() {
    const base = Object.keys(P.BASE_MOTIONS).map((k) => actionCard(k, P.BASE_MOTIONS[k], true)).join('');
    const acts = Object.keys(P.ACTIONS).map((k) => actionCard(k, P.ACTIONS[k], false)).join('');
    return '<h3 class="y7-g-sub">基础动作</h3><div class="y7-g-grid" data-g-actions>' + base + '</div>' +
      '<h3 class="y7-g-sub">事实驱动的动作（设计说明第 6.3 节）</h3><div class="y7-g-grid" data-g-actions>' + acts + '</div>';
  }

  function eventButtons(list, act) {
    const groups = {};
    list.forEach(([tag, ev], i) => { (groups[tag] = groups[tag] || []).push([ev, i]); });
    return Object.keys(groups).map((tag) => '<div class="y7-g-evgroup"><div class="y7-g-evtag">' + Y7.ui.tag(tag) + '</div><div class="y7-g-evs">' +
      groups[tag].map(([ev, i]) => {
        const action = P.resolveAction(ev);
        const detail = ev.tool || (ev.payload && (ev.payload.verdict || ev.payload.artifact)) || '';
        const label = ev.type + (detail ? '（' + detail + '）' : '') + (ev.note ? ' · ' + ev.note : '');
        const title = action ? (P.ACTIONS[action] ? P.ACTIONS[action].label : action) : '画面变化';
        return '<button type="button" class="y7-g-ev" data-act="' + act + '" data-i="' + i + '" title="' + esc(title) + '"><span class="y7-g-mono">' + esc(label) + '</span><small>' + esc(title) + '</small></button>';
      }).join('') + '</div></div>').join('');
  }

  function roomBlock() {
    const controls = '<div class="y7-g-ctls">' + select('gallery.dept', DEPT_OPTIONS, sel.dept, '部门') +
      (sel.dept === 'operations' ? '<span class="y7-small y7-muted">运维房间只在 Stage 5 出现</span>' : select('gallery.roomLevel', LEVEL_OPTIONS, sel.roomLevel, '档位')) +
      select('gallery.status', STATUS_OPTIONS, sel.status, '部门状态') + '</div>';
    return controls + '<div class="y7-g-preview"><div class="y7-g-canvas"><canvas data-g-room aria-label="部门房间预览"></canvas></div>' +
      '<div class="y7-g-events" data-g-room-events>' + eventButtons(roomEvents(), 'gallery.roomEvent') + '</div></div>';
  }

  function loopBlock() {
    const focusList = [['', '不聚焦']].concat(Object.values(LOOP_ITEMS).map((it) => [it.id, it.title]));
    const controls = '<div class="y7-g-ctls">' + select('gallery.loopLevel', LEVEL_OPTIONS, sel.loopLevel, '档位') +
      select('gallery.preset', LOOP_PRESETS.map((p) => [p[0], p[1]]), sel.preset, '状态') + select('gallery.focus', focusList, sel.focus, '聚焦事项') + '</div>';
    return controls + '<div class="y7-g-canvas is-wide"><canvas data-g-loop aria-label="循环画面预览"></canvas></div>' +
      '<div class="y7-g-events is-row">' + eventButtons(loopEvents(), 'gallery.loopEvent') + '</div>';
  }

  function loopTable() {
    return Y7.ui.table({
      columns: [
        { key: 'fact', label: '事实' },
        { key: 'source', label: '来源', className: 'y7-g-mono' },
        { key: 'picture', label: '画面' },
        { key: 'tag', label: '阶段', render: (r) => Y7.ui.tag(r.tag) }
      ],
      rows: P.LOOP_VIEWS
    });
  }

  function render() {
    const stageFilter = '<div class="y7-g-ctls">' + select('gallery.role', roleOptions(), sel.role, '角色') +
      select('gallery.stage', [['all', '全部阶段'], ['当前', '当前'], ['3.1', '3.1'], ['3.4A', '3.4A'], ['Stage 4', 'Stage 4'], ['Stage 5', 'Stage 5']], sel.stage, '阶段') + '</div>';
    return '<header class="y7-page-head"><div class="y7-page-titles"><p class="y7-eyebrow">原型专用</p><h1>动作图鉴</h1>' +
      '<p class="y7-g-intro">部门房间与循环画面里的全部小人和动画。每个动作写明驱动它的事实、来源事件、房间变化与所属阶段；系统设置为减少动画时，每个画面停在动作的关键姿势。</p></div></header>' +
      Y7.ui.block({ title: '角色', subtitle: '衣服颜色按部门区分，角色靠配件区分（设计说明第 6.2 节）。', body: roleCards(), className: 'y7-gallery' }) +
      Y7.ui.block({ title: '动作', subtitle: '每项循环播放一次该动作；可以统一换成某个角色查看。', body: stageFilter + '<div data-g-action-list>' + actionCards() + '</div>', className: 'y7-gallery' }) +
      Y7.ui.block({ title: '部门房间预览', subtitle: '选择部门、档位与状态，点击右侧的事件按钮播放对应动作；播放完回到状态姿势。', body: roomBlock(), className: 'y7-gallery' }) +
      Y7.ui.block({ title: '循环画面预览', subtitle: '大厅、三个部门房间成环、走廊、成果库；Stage 5 加运维房间与观察台。', body: loopBlock(), className: 'y7-gallery' }) +
      Y7.ui.block({ title: '循环画面的状态与画面', subtitle: '设计说明第 5.2 节逐行对应。', body: loopTable(), className: 'y7-gallery' });
  }

  // ---------------------------------------------------------------------------
  // 画面的创建与销毁

  function mountVignettes(root) {
    live.vigs.forEach((v) => v.destroy());
    live.vigs = [];
    if (live.io) live.io.disconnect();
    live.io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        const v = live.vigs.find((x) => x.canvas === en.target);
        if (v) v.pause(!en.isIntersecting);
      });
    }, { rootMargin: '120px' });
    root.querySelectorAll('canvas[data-vig]').forEach((cv) => {
      const v = P.createVignette(cv, { action: cv.dataset.vig, sprite: cv.dataset.sprite });
      v.canvas = cv;
      v.pause(true);
      live.vigs.push(v);
      live.io.observe(cv);
    });
    root.querySelectorAll('canvas[data-frame]').forEach((cv) => P.renderSprite(cv, cv.dataset.sprite, cv.dataset.anim, Number(cv.dataset.frame)));
    applyStageFilter(root);
  }

  function applyStageFilter(root) {
    root.querySelectorAll('[data-g-actions] .y7-g-card').forEach((card) => {
      card.hidden = sel.stage !== 'all' && card.dataset.stage !== sel.stage;
    });
  }

  function mountRoom(root) {
    if (live.room) live.room.destroy();
    live.room = P.createRoomScene(root.querySelector('canvas[data-g-room]'), { department: sel.dept, level: roomLevel() });
    live.roomModel = roomModel();
    live.room.setModel(live.roomModel);
    live.roomEvents = roomEvents();
  }

  // 与真实页面一样先改数据再播放事件：信箱与摘要档案盒的数字以 roomModel 为准
  const ROOM_COUNT_PATCH = {
    department_guidance_received: (m) => { m.mailbox += 1; },
    department_guidance_applied: (m) => { m.mailbox = Math.max(0, m.mailbox - 1); m.pinnedNotes += 1; },
    compaction_recorded: (m) => { m.summaries += 1; },
    spec_accepted: (m) => { if (m.department === 'product') m.scrolls += 1; },
    contract_accepted: (m) => { if (m.department === 'product') m.scrolls += 1; },
    x_semantic_recorded: (m) => { if (m.level === 's4' || m.level === 's5') m.semanticCards += 1; }
  };

  function mountLoop(root) {
    if (live.loop) live.loop.destroy();
    const m = loopModel();
    live.loop = P.createLoopScene(root.querySelector('canvas[data-g-loop]'), { level: m.level });
    live.loopModel = m;
    live.loop.setModel(m);
    live.loop.focus(sel.focus || null);
    live.loopEvents = loopEvents();
  }

  function mount(ctx, root) {
    live = { root, vigs: [], io: null, room: null, loop: null, roomEvents: [], loopEvents: [] };
    mountVignettes(root);
    mountRoom(root);
    mountLoop(root);
  }

  function unmount() {
    if (!live) return;
    live.vigs.forEach((v) => v.destroy());
    if (live.io) live.io.disconnect();
    if (live.room) live.room.destroy();
    if (live.loop) live.loop.destroy();
    live = null;
  }

  function need() {
    if (!live) throw new Error('动作图鉴没有挂载');
    return live;
  }

  Y7.actions.register('gallery.role', (el) => {
    sel.role = el.value;
    const L = need();
    L.root.querySelector('[data-g-action-list]').innerHTML = actionCards();
    mountVignettes(L.root);
  });
  Y7.actions.register('gallery.stage', (el) => { sel.stage = el.value; applyStageFilter(need().root); });
  Y7.actions.register('gallery.dept', (el) => {
    sel.dept = el.value;
    const L = need();
    L.root.querySelector('canvas[data-g-room]').closest('.y7-block-body').innerHTML = roomBlock();
    mountRoom(L.root);
  });
  Y7.actions.register('gallery.roomLevel', (el) => {
    sel.roomLevel = el.value;
    const L = need();
    L.root.querySelector('[data-g-room-events]').innerHTML = eventButtons(roomEvents(), 'gallery.roomEvent');
    mountRoom(L.root);
  });
  Y7.actions.register('gallery.status', (el) => {
    sel.status = el.value;
    const L = need();
    L.roomModel = roomModel();
    L.room.setModel(L.roomModel);
  });
  Y7.actions.register('gallery.roomEvent', (el) => {
    const L = need();
    const item = L.roomEvents[Number(el.dataset.i)];
    if (!item) throw new Error('没有这个事件按钮：' + el.dataset.i);
    const patch = ROOM_COUNT_PATCH[item[1].type];
    if (patch) {
      patch(L.roomModel);
      L.room.setModel(L.roomModel);
    }
    L.room.playEvent(Object.assign({ seq: Date.now(), at: new Date().toISOString(), projectId: 'p-report' }, item[1]));
  });
  Y7.actions.register('gallery.loopLevel', (el) => { sel.loopLevel = el.value; mountLoop(need().root); });
  Y7.actions.register('gallery.preset', (el) => { sel.preset = el.value; mountLoop(need().root); });
  Y7.actions.register('gallery.focus', (el) => { sel.focus = el.value; need().loop.focus(sel.focus || null); });
  Y7.actions.register('gallery.loopEvent', (el) => {
    const L = need();
    const item = L.loopEvents[Number(el.dataset.i)];
    if (!item) throw new Error('没有这个事件按钮：' + el.dataset.i);
    // 架子上的版本与候选取自 loopModel：先改数据再播放事件
    const ev = item[1];
    const sh = L.loopModel.shelves;
    if (ev.type === 'deliverable_adopted' && ev.payload && ev.payload.version && !sh.adopted.includes(ev.payload.version)) { sh.adopted.push(ev.payload.version); L.loop.setModel(L.loopModel); }
    if (ev.type === 'adoption_held' && !sh.held.some((h) => h.id === ev.workItemId)) { sh.held.push({ id: ev.workItemId, label: (ev.payload && ev.payload.label) || ev.workItemId }); L.loop.setModel(L.loopModel); }
    L.loop.playEvent(Object.assign({ seq: Date.now(), at: new Date().toISOString(), projectId: 'p-report' }, item[1]));
  });

  Y7.views.register('gallery', {
    title: () => '动作图鉴',
    render,
    mount,
    update: () => {},
    unmount
  });
})();
