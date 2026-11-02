// 翻译层（画面与播放设计说明第 6 节）：唯一同时认识 Yudao 的说法与画面的说法的地方。
// 把查询结果翻成状态，把事件翻成动作，把决定请求与输出片段作为实时内容转交，输出只用画面合同（js/pixel/contract.js）的形状与取值。
// 事实只来自查询：状态由查询结果翻译而来，不把事件累加成事实；事件只翻成动作。
// 能力清单里的每种事件，在楼、楼层、房间三个场景里要么翻成动作（或实时内容），要么列在这个场景的「不画」清单里并写一句理由
// （checks/playback.js 核对）。
(function () {
  'use strict';
  const Y13 = window.Y13;
  const T = Y13.translate;
  if (!T || !T.say) throw new Error('translate.js 需要先加载 js/translate/say.js');

  // ---------------------------------------------------------------------------
  // 服务端的取值到画面的取值：只写在这里，只写一次

  const table = (name, map) => (v) => {
    if (!Object.prototype.hasOwnProperty.call(map, v)) throw new Error('翻译层没有对应的' + name + '：' + v);
    return map[v];
  };
  // 事项的状态（project.loop 的 items[].status）
  const itemStatus = table('事项状态', {
    queued: 'queued', waiting_slot: 'waiting_slot', running: 'working', asking: 'asking', waiting_provider: 'waiting_model',
    waiting_resume: 'waiting_resume', waiting_decision: 'waiting_user', paused: 'paused', interrupted: 'interrupted',
    failed: 'failed', done: 'done', cancelled: 'cancelled', stopped_for_upgrade: 'upgrade_stopped', adopted: 'adopted'
  });
  // 部门同时在做什么（project.loop 的 items[].departments）
  const busyStatus = table('部门状态', { working: 'working', answering: 'answering', waiting_user: 'waiting_user' });
  // 项目的状态标记（projects.list 的 marker.status）到楼里每层的状态灯；询问中的项目标记写「运行中」
  const floorSign = table('项目状态标记', {
    running: 'working', asking: 'working', queued: 'queued', waiting_slot: 'waiting_slot', waiting_provider: 'waiting_model',
    waiting_resume: 'waiting_resume', waiting_decision: 'waiting_user', interrupted: 'interrupted', idle: 'idle', archived: 'idle'
  });
  // 部门房间的状态（department.workspace 的 room.status）
  const roomStatus = table('房间状态', {
    idle: 'idle', working: 'working', asking: 'asking', paused: 'paused', failed: 'failed', done: 'done',
    cancelled: 'cancelled', interrupted: 'interrupted', waiting_resume: 'waiting_resume'
  });
  // 房间里状态的姿势（department.workspace 的 room.pose.action）
  const roomPose = table('房间姿势', {
    typing: 'type', reading: 'read_sit', writing: 'write', thinking: 'think', searching: 'rummage', waiting: 'sit_wait',
    tea: 'tea', idle: 'sit', inspecting: 'inspect'
  });
  // 角色的状态
  const roleStatus = table('角色状态', { idle: 'idle', assigned: 'assigned', working: 'working', returned: 'returned', failed: 'failed', away: 'away' });
  // 事实来源的种类（登记表的 SOURCE_KINDS）
  const sourceKind = table('来源种类', {
    rule: 'rule', host_measurement: 'host_measurement', user: 'user', role_statement: 'role_statement', decision_model: 'decision_model'
  });
  // 收敛状态（run.loops 的 instances[].state）
  const loopState = table('收敛状态', {
    converging: 'converging', stalled: 'stalled', oscillating: 'oscillating', drifting: 'drifting', at_bound: 'at_bound', not_judged: 'not_judged'
  });

  const ref = (r) => (r ? { position: r.position, field: r.field || null, source: r.source ? sourceKind(r.source) : null } : r);
  const refsOf = (rs) => {
    const out = {};
    Object.keys(rs).forEach((k) => { out[k] = ref(rs[k]); });
    return out;
  };
  // 只抄出现了的字段（与查询结果的形状一致：没有的字段在状态里也没有）
  const pick = (o, keys) => {
    const out = {};
    keys.forEach((k) => { if (o[k] !== undefined) out[k] = o[k]; });
    return out;
  };
  const role = (r) => ({ id: r.id, name: r.name, kind: r.kind, status: roleStatus(r.status), task: r.task === undefined ? null : r.task });
  const retryText = (iso) => (iso ? Y13.time.clock(iso) + ' 重试' : null);

  // ---------------------------------------------------------------------------
  // 楼层的状态：project.loop（带位置）、各部门的角色（department.workspace，Stage 5）与聚焦的事项

  function floorState(o) {
    const loop = o.loop;
    const s = {
      position: o.position,
      items: loop.items.map((x) => {
        const it = pick(x, ['id', 'title', 'color_index', 'kind', 'department', 'cycle', 'elapsed_sec', 'limit_sec', 'sign', 'queue_pos', 'waiting_provider_sec']);
        it.status = itemStatus(x.status);
        if (x.departments) {
          it.departments = {};
          Object.keys(x.departments).forEach((d) => { it.departments[d] = busyStatus(x.departments[d]); });
        }
        if (x.refs) it.refs = refsOf(x.refs);
        return it;
      }),
      open_requests: (loop.open_requests || []).map((q) => ({ from: q.from, to: q.to, work_item_id: q.work_item_id })),
      shelves: Object.assign({ adopted: loop.shelves.adopted.slice() },
        loop.shelves.boxes ? { boxes: loop.shelves.boxes.map((b) => ({ version: b.version, ref: ref(b.ref) })) } : {}),
      interrupted: Boolean(loop.interrupted),
      roles: o.roles ? Object.fromEntries(Object.keys(o.roles).map((d) => [d, o.roles[d].map(role)])) : null,
      focus_id: o.focus || null
    };
    if (loop.stamp !== undefined) s.stamp = loop.stamp ? { work_item_id: loop.stamp.work_item_id, ref: ref(loop.stamp.ref) } : null;
    if (loop.slots) s.slots = { total: loop.slots.total, used: loop.slots.used };
    if (loop.waiting_provider) s.waiting_provider = loop.waiting_provider.map((w) => ({ department: w.department, retry_text: retryText(w.next_retry_at), work_item_id: w.work_item_id }));
    if (loop.ops !== undefined) s.ops = loop.ops ? pick(loop.ops, ['version', 'machine_id', 'fault', 'auto_repair_stopped']) : null;
    if (loop.machines) s.machines = loop.machines.map((m) => pick(m, ['id', 'name', 'online', 'actions', 'unknown']));
    return s;
  }

  // ---------------------------------------------------------------------------
  // 楼层的覆盖层（用户打开的叠加信息，与页面文字一样实时，不进时间线）：各覆盖层用到的查询结果 → 画面合同的形状。
  // input 是页面查好的结果；sourceOf(位置) 给出那条事件的来源种类

  const DEPT_TEXT = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const RECOVERY_TEXT = { interrupted: '中断', waiting_resume: '待恢复' };

  function floorOverlay(id, input, sourceOf) {
    if (id === 'flow') {
      const groups = {};
      (input.rows || []).forEach((r) => {
        if (!r.from || !r.to) return;
        // 缺陷记录的流向画成回流
        const back = r.kind === 'defect';
        const key = r.from + '>' + r.to + '>' + (back ? 'rework' : '');
        const g = groups[key] || (groups[key] = { from: r.from, to: r.to, kind: back ? 'rework' : r.kind, count: 0, last_at: r.at });
        g.count += 1;
        if (Y13.time.ms(r.at) > Y13.time.ms(g.last_at)) g.last_at = r.at;
      });
      return { segments: Object.values(groups).map((g) => ({ from: g.from, to: g.to, kind: g.kind, count: g.count, last_text: Y13.time.clock(g.last_at) })) };
    }
    if (id === 'waiting') {
      const loop = input.loop;
      const entries = [];
      const rows = {};
      const push = (department, text, since) => {
        const row = rows[department] || 0;
        rows[department] = row + 1;
        entries.push({ department, text, waited_text: Y13.time.duration(since ? Math.max(0, Y13.time.between(since, input.now)) : 0), row });
      };
      (loop.open_requests || []).forEach((r) => push(r.to, DEPT_TEXT[r.from] + '的询问未回答', r.since));
      input.decisions.forEach((d) => {
        const it = loop.items.find((x) => x.id === d.work_item_id);
        push(it && it.department ? it.department : 'hall', '待你决定：' + d.kind_label, d.issued_at);
      });
      loop.items.filter((it) => it.status === 'waiting_slot').forEach(() => push('hall', '等待执行槽位', null));
      (loop.waiting_provider || []).forEach((w) => push(w.department, '等待模型服务，' + Y13.time.clock(w.next_retry_at) + ' 重试', null));
      return { entries };
    }
    if (id === 'recovery') {
      return { entries: input.loop.items.filter((it) => ['interrupted', 'waiting_resume'].includes(it.status) && it.department)
        .map((it) => ({ department: it.department, text: RECOVERY_TEXT[it.status] + '：' + it.title })) };
    }
    if (id === 'context_usage') return { entries: (input.entries || []).map((e) => ({ department: e.department, role: e.role, ratio: e.ratio })) };
    if (id === 'semantic_records') return { entries: (input.summary || []).map((e) => ({ department: e.department, valid: e.valid, conflicts: e.conflicts })) };
    if (id === 'loops') {
      const used = (u) => {
        const fmt = (v) => (u.unit === '秒' ? Y13.time.duration(v) : v + ' ' + u.unit);
        return { value: u.value, limit: u.limit, at_bound: Boolean(u.at_bound), text: u.limit === null || u.limit === undefined ? fmt(u.value) : fmt(u.value) + ' / ' + fmt(u.limit) };
      };
      return {
        items: (input.items || []).map((x) => ({
          work_item_id: x.work_item_id,
          instances: x.instances.map((inst) => ({
            id: inst.id, layer: inst.layer, department: inst.department || null, role: inst.role || null, parent: inst.parent || null,
            label: inst.label, state: loopState(inst.state), basis: inst.basis || null, stop_reason: inst.stop_reason || null, missing: inst.missing || null,
            position: inst.position || null,
            ref: inst.position ? { position: inst.position, field: null, source: sourceOf(inst.position) } : null,
            measure: inst.measure ? { field: inst.measure.field, series: inst.measure.series.map((p) => ({ position: p.position, source: sourceKind(p.source) })) } : null,
            used: (inst.used || []).map(used)
          }))
        }))
      };
    }
    if (id === 'sources') return {};
    if (id === 'coverage') {
      const methods = Y13.registry.CHECK_METHODS;
      return {
        items: (input.items || []).map((x) => {
          const pos = Math.max.apply(null, x.criteria.map((cr) => cr.position));
          return {
            work_item_id: x.work_item_id, covered: x.covered, total: x.total, model_read: x.model_read, open_count: x.open_count,
            text: Y13.coverageText(x), ref: { position: pos, field: null, source: sourceOf(pos) },
            criteria: x.criteria.map((cr) => ({
              id: cr.id, text: cr.text, method_text: methods[cr.method].label, result: cr.result, open: cr.open,
              position: cr.position, field: cr.field || null, source: cr.source ? sourceKind(cr.source) : null
            })),
            release: x.release ? {
              position: x.release.position, ref: { position: x.release.position, field: null, source: sourceOf(x.release.position) },
              ratio: { covered: x.release.ratio.covered, total: x.release.ratio.total }, text: Y13.coverageText(x.release.ratio)
            } : null
          };
        })
      };
    }
    throw new Error('未知的覆盖层：' + id);
  }

  // 来源卡片上写的事件说明（event.detail 的 event）
  function describe(ev) {
    return {
      position: ev.position, source: ev.source ? sourceKind(ev.source) : null,
      lines: [ev.label, ev.type + ' · ' + Y13.time.format(ev.at), '提出者 ' + ev.actor + ' · 全局位置 ' + ev.position],
      probability: ev.payload && ev.payload.probability !== undefined ? ev.payload.probability : null
    };
  }

  // 实时内容：等待回答的决定请求写成卡片
  const cards = (decisions) => decisions.map(Y13.cards.face);

  // ---------------------------------------------------------------------------
  // 楼层的动作

  const pl = (ev) => ev.payload || {};
  // 管道中的包裹是事实元素：来源是引起这次移动的事件
  const transit = (ev) => (ev.source && ev.position ? { position: ev.position, field: null, source: sourceKind(ev.source), title: '管道中的包裹：' + (ev.label || ev.type) } : null);
  // 一个部门里的一个角色做的事
  const one = (kind, ev, ctx, extra) => Object.assign({
    kind, position: ev.position, item: ev.work_item_id || null, room: ev.department || null, role: ev.role || null,
    say: T.say(ev, { roleName: ctx.roleName })
  }, extra || {});
  const handoff = (ev, from, to, artifact) => Object.assign({
    kind: 'handoff', position: ev.position, item: ev.work_item_id || null, from, to, artifact, fact: transit(ev)
  }, T.sayHandoff(artifact, from, to));
  // 楼层的工具：按工具的名称落在哪件事上
  function floorTool(ev) {
    const tool = String(ev.tool || pl(ev).tool || '');
    if (tool === 'search') return 'search';
    if (tool === 'run_command' || tool === 'bash') return 'command';
    if (tool === 'run_check') return 'inspect';
    if (/write|edit/.test(tool)) return 'write';
    if (/fetch|http|net|url/.test(tool)) return 'fetch';
    if (/mcp/.test(tool)) return 'tool';
    if (/browser|computer/.test(tool)) return ev.department === 'quality' ? 'browse' : 'self_test';
    if (/scan|legacy|repo/.test(tool)) return 'scan';
    return 'read';
  }
  const count = (ev) => (pl(ev).n !== undefined && pl(ev).of !== undefined ? String(pl(ev).n) + '/' + String(pl(ev).of) : null);
  const at = (kind, extra) => (ev) => [Object.assign({ kind, position: ev.position, item: ev.work_item_id || null, room: ev.department || null }, extra ? extra(ev) : {})];
  const task = (kind, extra) => (ev, ctx) => [one(kind, ev, ctx, extra ? extra(ev) : null)];

  const FLOOR = {
    user_input_received: at('mail'),
    work_item_created: at('mail'),
    department_activated: (ev) => (ev.department ? at('room_light')(ev) : []),
    context_assembled: task('gather'),
    model_requested: task('think'),
    model_request_serialized: task('think'),
    model_attempt_finished: task('idea'),
    model_retry_scheduled: task('retry', (ev) => ({ count: count(ev) })),
    model_attempt_failed: task('request_failed'),
    tool_started: (ev, ctx) => [one(floorTool(ev), ev, ctx)],
    tool_skipped: task('tool_denied'),
    proposal_submitted: task('submit'),
    proposal_rejected: task('rejected'),
    spec_accepted: (ev, ctx) => [one('stamp_valid', ev, ctx), handoff(ev, 'product', 'engineering', 'prd')],
    contract_accepted: (ev, ctx) => [one('stamp_valid', ev, ctx), handoff(ev, 'product', 'engineering', 'prd')],
    delivery_accepted: (ev, ctx) => [one('seal', ev, ctx), handoff(ev, 'engineering', 'quality', 'box')],
    structure_accepted: (ev) => [handoff(ev, 'engineering', 'quality', 'box')],
    // 放行：放行单送往成果库，载荷写明 release_to 时送往那个部门（运维接手放行的修复）；缺陷记录经回流管道送回工程
    qa_submitted: (ev, ctx) => (pl(ev).verdict === 'release'
      ? [one('stamp_release', ev, ctx), handoff(ev, 'quality', pl(ev).release_to || 'library', 'release')]
      : [one('stamp_defect', ev, ctx), handoff(ev, 'quality', 'engineering', 'defect')]),
    ask_started: (ev) => [Object.assign({ kind: 'letter', position: ev.position, item: ev.work_item_id || null, from: pl(ev).requester, to: pl(ev).recipient, answer: false, fact: transit(ev) }, T.sayAsk(ev))],
    ask_answered: (ev) => [Object.assign({ kind: 'letter', position: ev.position, item: ev.work_item_id || null, from: pl(ev).recipient, to: pl(ev).requester, answer: true, fact: transit(ev) }, T.sayAnswer(ev))],
    department_guidance_received: task('note_in'),
    department_guidance_applied: task('note_read'),
    department_guidance_responded: task('note_reply'),
    compaction_recorded: task('compact'),
    compaction_failed: task('compact_fail'),
    run_paused: task('paused'),
    run_failed: task('failed'),
    run_done: task('done'),
    deliverable_adopted: at('adopt'),
    baseline_adopted: at('adopt'),
    x_decision_issued: at('decision_out', (ev) => ({ decision: pl(ev).decision_id || null, say: T.say(ev) })),
    project_decision_requested: at('decision_out', (ev) => ({ decision: pl(ev).decision_id || null, say: T.say(ev) })),
    x_decision_answered: at('decision_back', (ev) => ({ decision: pl(ev).decision_id || null, say: T.say(ev) })),
    project_decision_answered: at('decision_back', (ev) => ({ decision: pl(ev).decision_id || null, say: T.say(ev) })),
    x_run_auto_resumed: at('resume'),
    x_action_unknown: at('unsure'),
    x_remote_action_started: at('remote', () => ({ out: true })),
    x_remote_action_finished: at('remote', () => ({ out: false })),
    x_late_receipt: at('remote', () => ({ out: false })),
    x_queued: at('parcel_in', () => ({ repair: false })),
    x_repair_created: at('parcel_in', () => ({ repair: true })),
    x_slot_acquired: at('parcel_enter', (ev) => ({ fact: transit(ev) })),
    x_queue_reordered: at('queue_moved'),
    x_provider_wait_entered: at('model_wait'),
    x_provider_wait_left: task('model_back'),
    x_run_stopped_for_upgrade: task('upgrade_stop'),
    x_auto_repair_stopped: task('repair_stop'),
    x_deployed: task('deploy', (ev) => ({ fact: transit(ev) })),
    x_rolled_back: task('rollback', (ev) => ({ fact: transit(ev) })),
    x_fault_recorded: task('fault', (ev) => ({ fact: transit(ev) })),
    // 分派：经理把任务卡递给事件指定的角色（role）；交回：这个角色把结果卡交回经理
    x_role_task_assigned: (ev, ctx) => [one('assign', ev, ctx, { role: ev.role || pl(ev).to || null, sayTo: T.say(ev, { side: 'to', roleName: ctx.roleName }) })],
    x_role_result_returned: (ev, ctx) => [one('hand_back', ev, ctx, { sayTo: T.say(ev, { side: 'to', roleName: ctx.roleName }) })],
    x_review_recorded: (ev, ctx) => [one(['passed', 'pass'].includes(pl(ev).verdict) ? 'review_pass' : 'review_return', ev, ctx)],
    x_explorer_fetch: task('explore')
  };

  // ---------------------------------------------------------------------------
  // 部门房间的动作：只给出与这个部门有关的动作

  // 房间的工具：按工具的名称（v12 动作图鉴的对照）；没有专门动作的工具调用是进度
  const ROOM_TOOL = { search: 'search', read_range: 'read', read_file: 'read', edit_range: 'write', write_file: 'write', bash: 'run_command', run_command: 'run_command', run_check: 'inspect', browser: 'self_test' };
  // 事件与这个房间有关：事件没有部门（整个事项的事），或者就是这个部门的事
  const mine = (ev, dept) => !ev.department || ev.department === dept;
  const own = (kind, extra) => (ev, dept, ctx) => (mine(ev, dept) ? [one(kind, ev, ctx, extra ? extra(ev) : null)] : []);
  // 交接的一端：交出的部门是 from 一侧，收到的部门是 to 一侧（说的话按这一侧）
  const handoffIn = (ev, dept, from, to, artifact) => {
    if (dept !== from && dept !== to) return [];
    const h = handoff(ev, from, to, artifact);
    return [Object.assign(h, { room: dept })];
  };
  const quoted = (label) => {
    const m = /「([^」]+)」/.exec(String(label || ''));
    return m ? m[1] : (label || null);
  };

  const ROOM = {
    department_activated: own('activate'),
    context_assembled: own('fetch_folder'),
    model_requested: own('type_think'),
    model_request_serialized: own('type_think'),
    model_attempt_finished: own('idea'),
    model_retry_scheduled: own('retry_wait', (ev) => ({ count: String(pl(ev).n || pl(ev).attempt || pl(ev).attempt_no || 2) + '/' + String(pl(ev).of || pl(ev).max || pl(ev).max_attempts || 3) })),
    model_attempt_failed: own('slump'),
    tool_started: (ev, dept, ctx) => (mine(ev, dept) ? [one(ROOM_TOOL[String(ev.tool || pl(ev).tool || '')] || 'tool_progress', ev, ctx)] : []),
    // 工具结束：命令亮出退出状态灯，浏览器自测看截图；其余工具结束时房间里没有变化
    tool_called: (ev, dept, ctx) => {
      if (!mine(ev, dept)) return [];
      const tool = String(ev.tool || pl(ev).tool || '');
      if (tool === 'bash' || tool === 'run_command') return [one('command_done', ev, ctx, { ok: pl(ev).exit_code === 0, timed_out: Boolean(pl(ev).timed_out) })];
      if (tool === 'browser') return [one('self_test', ev, ctx)];
      return [];
    },
    tool_skipped: own('toss'),
    proposal_submitted: own('submit'),
    proposal_rejected: own('returned'),
    spec_accepted: (ev, dept, ctx) => own('stamp_valid')(ev, dept, ctx).filter(() => ev.department === dept).concat(handoffIn(ev, dept, 'product', 'engineering', 'prd')),
    contract_accepted: (ev, dept, ctx) => own('stamp_valid')(ev, dept, ctx).filter(() => ev.department === dept).concat(handoffIn(ev, dept, 'product', 'engineering', 'prd')),
    delivery_accepted: (ev, dept, ctx) => own('seal')(ev, dept, ctx).filter(() => ev.department === dept).concat(handoffIn(ev, dept, 'engineering', 'quality', 'box')),
    structure_accepted: (ev, dept) => handoffIn(ev, dept, 'engineering', 'quality', 'box'),
    qa_submitted: (ev, dept, ctx) => {
      const release = pl(ev).verdict === 'release';
      const stamp = ev.department === dept ? [one(release ? 'stamp_release' : 'stamp_rework', ev, ctx)] : [];
      return stamp.concat(release ? handoffIn(ev, dept, 'quality', pl(ev).release_to || 'library', 'release') : handoffIn(ev, dept, 'quality', 'engineering', 'defect'));
    },
    // 询问：发问的部门写纸条塞进传信管口；被询问的部门取出来读
    ask_started: (ev, dept) => {
      const s = T.sayAsk(ev);
      const base = { position: ev.position, item: ev.work_item_id || null, room: dept, role: null };
      if (dept === pl(ev).requester) return [Object.assign({ kind: 'send_letter', say: s.say }, base)];
      if (dept === pl(ev).recipient) return [Object.assign({ kind: 'answer_letter', reads: true, say: s.sayTo }, base)];
      return [];
    },
    // 回答：被询问的部门写回答塞回；发问的部门在管道口接住回答读
    ask_answered: (ev, dept) => {
      const s = T.sayAnswer(ev);
      const base = { position: ev.position, item: ev.work_item_id || null, room: dept, role: null };
      if (dept === pl(ev).recipient) return [Object.assign({ kind: 'answer_letter', reads: false, say: s.say }, base)];
      if (dept === pl(ev).requester) return [Object.assign({ kind: 'answer_letter', reads: true, say: s.sayTo }, base)];
      return [];
    },
    department_guidance_received: own('guidance_in'),
    department_guidance_applied: own('guidance_read'),
    department_guidance_responded: own('guidance_reply'),
    compaction_recorded: own('compact'),
    compaction_failed: own('compact_fail'),
    run_paused: own('paused'),
    run_failed: (ev, dept, ctx) => {
      const reason = pl(ev).reason || pl(ev).stopReason;
      return own(reason === 'cancelled' ? 'cancelled' : 'failed', () => ({ text: reason || null }))(ev, dept, ctx);
    },
    run_done: own('done'),
    x_run_auto_resumed: own('resume'),
    x_action_unknown: own('puzzled'),
    // 决定请求：运维的外部动作举申请单，模型引用无法使用举「待恢复」的牌子；其余的决定在楼层的大厅板上，房间里不画
    x_decision_issued: (ev, dept, ctx) => {
      const k = pl(ev).kind;
      if (k === 'external_action') return own('hold_form', () => ({ text: pl(ev).action || '外部动作' }))(ev, dept, ctx);
      if (k === 'waiting_resume') return own('hold_card', () => ({ text: pl(ev).missing || pl(ev).text || quoted(ev.label) || '待恢复' }))(ev, dept, ctx);
      return [];
    },
    x_remote_action_started: own('remote_run', (ev) => ({ text: pl(ev).machine_name || pl(ev).label || null })),
    x_machine_offline: own('remote_unknown', (ev) => ({ text: pl(ev).machine_name || null })),
    x_network_fetch: own('net_fetch'),
    x_mcp_called: own('mcp_press', (ev) => ({ index: pl(ev).index !== undefined ? pl(ev).index : pl(ev).button !== undefined ? pl(ev).button : 0 })),
    x_trial_step: own('trial', (ev) => ({ step: pl(ev).step || null, lines: pl(ev).text_lines || null })),
    x_deployed: own('deploy'),
    x_rolled_back: own('rollback'),
    x_fault_recorded: own('fault'),
    x_provider_wait_entered: own('wait_provider'),
    x_role_task_assigned: (ev, dept, ctx) => (mine(ev, dept) ? [one('assign', ev, ctx, { role: pl(ev).to || ev.role || null, sayTo: T.say(ev, { side: 'to', roleName: ctx.roleName }) })] : []),
    x_role_result_returned: (ev, dept, ctx) => (mine(ev, dept) ? [one('hand_back', ev, ctx, { sayTo: T.say(ev, { side: 'to', roleName: ctx.roleName }) })] : []),
    x_review_recorded: own('review', (ev) => ({ verdict: ['passed', 'pass'].includes(pl(ev).verdict) ? 'pass' : 'return' })),
    x_explorer_fetch: own('explore'),
    x_replanned: own('replan'),
    x_semantic_recorded: own('semantic')
  };

  // ---------------------------------------------------------------------------
  // 楼与机房的动作：楼里一层闪一下、撒彩带、包裹沿通往机房的管线走；机房里设备闪光、包裹沿管线到设备

  // 关键事实的颜色：缺陷记录与故障红，决定请求黄，采纳与放行绿，其余白
  function keyColor(ev) {
    const key = Y13.registry.keyOf(ev);
    if (!key) return null;
    return key === 'rework' || key === 'fault' ? 'red' : key === 'decision' ? 'yellow' : key === 'adopt' || key === 'release' ? 'green' : 'white';
  }
  const flashFloor = (ev, color) => ({ kind: 'floor_flash', position: ev.position, project: ev.project_id, color });
  const shaft = (bmp, up) => (ev) => [{ kind: 'shaft', position: ev.position, project: ev.project_id, bmp, up }];
  const machine = (color) => (ev) => (pl(ev).machine_id ? [{ kind: 'machine_flash', position: ev.position, machine: pl(ev).machine_id, color }] : []);
  const toMachine = (bmp, up) => (ev) => (pl(ev).machine_id ? [{ kind: 'machine_send', position: ev.position, project: ev.project_id, machine: pl(ev).machine_id, bmp, up }] : []);
  const both = (...fs) => (ev) => fs.reduce((list, f) => list.concat(f(ev)), []);
  // 关键事实：这一层闪一下
  const keyFlash = (ev) => [flashFloor(ev, keyColor(ev))];

  const BUILDING = {
    department_activated: (ev) => [flashFloor(ev, 'white')],
    qa_submitted: keyFlash,
    ask_started: keyFlash,
    ask_answered: keyFlash,
    deliverable_adopted: (ev) => [{ kind: 'celebrate', position: ev.position, project: ev.project_id }],
    baseline_adopted: keyFlash,
    x_decision_issued: keyFlash,
    x_decision_answered: keyFlash,
    project_decision_requested: keyFlash,
    project_decision_answered: keyFlash,
    x_provider_wait_entered: keyFlash,
    x_provider_wait_left: keyFlash,
    x_repair_created: keyFlash,
    x_repair_failed: keyFlash,
    x_auto_repair_stopped: keyFlash,
    x_machine_offline: machine('grey'),
    x_machine_online: machine('green'),
    x_action_unknown: machine('yellow'),
    x_late_receipt: machine('yellow'),
    x_remote_action_started: both(shaft('folder', false), toMachine('folder', false)),
    x_remote_action_finished: both(shaft('letter', true), machine('green'), toMachine('letter', true)),
    x_deployed: both(keyFlash, shaft('box_sealed', false), toMachine('box_sealed', false)),
    x_rolled_back: both(keyFlash, shaft('box_sealed', true), toMachine('box_sealed', true)),
    x_fault_recorded: both(keyFlash, machine('red'))
  };

  // ---------------------------------------------------------------------------
  // 实时内容：流式文字接在说话的小人身上，不进时间线

  const REALTIME = {
    model_stream_progress: (ev) => ({ who: { room: ev.department || null, role: ev.role || null }, text: pl(ev).text || pl(ev).delta || pl(ev).chunk || quoted(ev.label) || '……' })
  };

  // ---------------------------------------------------------------------------
  // 不画：每个场景里没有画面的事件种类与理由

  const none = (out, types, reason) => { types.forEach((t) => { out[t] = reason; }); return out; };
  const SETTINGS = '设置与登记的修改，画面里没有对应物；改变了的事实由下一份状态给出';
  const CATALOG = '模型目录的变化，不属于项目的画面';
  const PROJECT_LIST = '项目的登记、改名、置顶、归档与恢复：楼的层数、名牌与顺序由状态给出';
  const PAGE_ONLY = '只在页面文字里（资料、恢复页、设置页、写回记录），画面里没有对应物';
  const SCENARIO = '原型场景的准备，不推送';
  const STATE_ONLY = '由状态表示，没有一次性的动作';

  const COMMON = {};
  none(COMMON, ['project_registered', 'project_renamed', 'project_pinned', 'project_archived', 'project_restored'], PROJECT_LIST);
  none(COMMON, ['material_recorded', 'department_prompt_configured', 'project_goal_changed', 'x_home_seen', 'x_department_settings_saved',
    'x_source_directory_saved', 'x_machine_saved', 'x_machine_authorization_saved', 'execution_placement_configured', 'x_role_settings_saved', 'x_slots_set'], SETTINGS);
  none(COMMON, ['catalog_revised', 'catalog_candidates_collected', 'catalog_test_finished', 'credential_changed'], CATALOG);
  none(COMMON, ['x_scenario_setup'], SCENARIO);
  none(COMMON, ['writeback_completed', 'writeback_verified', 'writeback_stopped', 'writeback_held', 'writeback_not_needed', 'onboarding_revision_started',
    'action_verified', 'x_drain_started', 'x_upgrade_forced', 'x_evidence_checked', 'x_check_in', 'x_backup_taken'], PAGE_ONLY);
  none(COMMON, ['run_created', 'x_wait_restarted'], STATE_ONLY + '（事项出现、重新计时）');
  none(COMMON, ['x_decision_withdrawn', 'project_decision_withdrawn'], '撤回的决定请求从实时的决定卡片里去掉');

  const FLOOR_NONE = none(none(none(Object.assign({}, COMMON), ['x_run_interrupted'], STATE_ONLY + '：整层变暗、时钟停住、管道停止'),
    ['tool_called', 'x_machine_offline', 'x_machine_online', 'x_queue_cancelled', 'x_repair_failed', 'baseline_review_accepted', 'initial_prd_proposed'],
    STATE_ONLY + '：工具结束、机器上下线、取消排队、修复失败与建档的提案与审查在楼层上没有一次性的动作（门上的问号、包裹离开队列由状态给出）'),
    ['x_network_fetch', 'x_mcp_called', 'x_trial_step', 'x_replanned', 'x_semantic_recorded'],
    '部门内部的细节只在部门房间里演（邮筒、工具面板、试用台、白板、语义记录柜），楼层上没有这些陈设');

  const ROOM_NONE = none(none(none(Object.assign({}, COMMON), ['x_run_interrupted', 'x_run_stopped_for_upgrade'], STATE_ONLY + '：中断时灯灭、时钟停住；因升级停止时门口立牌'),
    ['user_input_received', 'work_item_created', 'deliverable_adopted', 'baseline_adopted', 'x_queued', 'x_slot_acquired', 'x_queue_cancelled', 'x_queue_reordered',
      'x_repair_created', 'x_repair_failed', 'x_auto_repair_stopped', 'initial_prd_proposed', 'baseline_review_accepted'],
    '发生在大厅、成果库或运维的修复流程里，部门房间里没有对应物（楼层上画）'),
    ['x_decision_answered', 'project_decision_requested', 'project_decision_answered', 'x_provider_wait_left', 'x_remote_action_finished', 'x_late_receipt', 'x_machine_online'],
    STATE_ONLY + '：决定单在楼层大厅的板上来回；等待结束、远程动作结束与机器恢复由下一份状态给出（灯亮起、终端回到平常）');

  const BUILDING_NONE = none(none(Object.assign({}, COMMON), ['x_run_interrupted', 'x_run_auto_resumed', 'x_run_stopped_for_upgrade', 'x_queue_cancelled',
    'x_queued', 'x_slot_acquired', 'x_queue_reordered', 'user_input_received', 'work_item_created', 'tool_called', 'baseline_review_accepted', 'initial_prd_proposed',
    'spec_accepted', 'contract_accepted', 'delivery_accepted', 'structure_accepted', 'run_paused', 'run_failed', 'run_done'],
    STATE_ONLY + '：楼里每层只画状态灯、亮灯的房间、小旗与阀门，只在关键事实上闪一下（交接由接收的部门亮灯表示）'),
    ['context_assembled', 'model_requested', 'model_request_serialized', 'model_stream_progress', 'model_attempt_finished', 'model_retry_scheduled', 'model_attempt_failed',
      'tool_started', 'tool_skipped', 'proposal_submitted', 'proposal_rejected', 'department_guidance_received', 'department_guidance_applied', 'department_guidance_responded',
      'compaction_recorded', 'compaction_failed', 'x_network_fetch', 'x_mcp_called', 'x_trial_step', 'x_role_task_assigned', 'x_role_result_returned', 'x_review_recorded',
      'x_explorer_fetch', 'x_replanned', 'x_semantic_recorded'],
    '部门里的进度与细节：楼太小，只看哪个房间亮灯');

  // ---------------------------------------------------------------------------
  // 出口

  const drop = (list) => list.filter(Boolean);
  T.floor = {
    state: floorState,
    overlay: floorOverlay,
    describe,
    cards,
    // ctx：{ roleName(角色 id) → 名称 }
    actions(ev, ctx) {
      const f = FLOOR[ev.type];
      return f ? drop(f(ev, ctx || { roleName: () => null })) : [];
    }
  };

  T.room = {
    // 部门工作间的查询（department.workspace，带位置）→ 房间的状态
    state(o) {
      const r = o.workspace.room;
      const s = pick(r, ['department', 'level', 'door', 'hold_card', 'mailbox', 'summaries', 'scrolls', 'pinned_notes', 'semantic_cards', 'existing_read',
        'machine', 'remote_unknown', 'waiting_provider', 'tool_panel', 'trial', 'self_test', 'monitor_alarm']);
      s.position = o.position;
      s.status = roomStatus(r.status);
      s.crt = Object.assign({}, r.crt);
      s.roles = r.roles.map(role);
      s.pose = r.pose ? { role_id: r.pose.role_id || null, anim: roomPose(r.pose.action) } : null;
      if (r.pipes) s.pipes = { out: r.pipes.out, letters_waiting: r.pipes.letters_waiting };
      return s;
    },
    actions(ev, dept, ctx) {
      const f = ROOM[ev.type];
      return f ? drop(f(ev, dept, ctx || { roleName: () => null })) : [];
    }
  };

  T.building = {
    // 楼：projects.list 与每个项目的 project.loop（带位置）；机房：machines.list 与楼里每层用着的机器
    state(o) {
      const floors = o.projects.map((p) => {
        const loop = o.loops[p.id];
        const lit = {};
        // 几个部门同时工作时（预测性探索、回答询问）几个房间同时亮灯
        const busy = (it, d) => Boolean(it.departments && ['working', 'answering'].includes(it.departments[d]));
        ['product', 'engineering', 'quality', 'operations'].forEach((d) => {
          lit[d] = loop.items.some((it) => ['running', 'asking'].includes(it.status) && (it.department === d || busy(it, d)));
        });
        if (loop.ops && loop.ops.version) lit.operations = true;
        const inUse = (loop.machines || []).filter((m) => m.actions > 0).map((m) => m.id);
        const inRoom = (it) => it.department && !['queued', 'waiting_slot', 'adopted'].includes(it.status);
        return {
          project_id: p.id, name: p.name, status: floorSign(p.marker.status), lit, has_ops: Boolean(loop.ops),
          flags: loop.items.filter(inRoom).map((it) => ({ work_item_id: it.id, color_index: it.color_index, department: it.department })),
          valve_closed: loop.items.some((it) => it.status === 'waiting_slot'),
          machine_ids: inUse, link_active: inUse.length > 0,
          decisions: p.decisions_waiting,
          runtime_machine: loop.ops ? loop.ops.machine_id : null
        };
      });
      return { position: o.position, floors, show_basement: Boolean(o.machines) };
    },
    machineState(o, building) {
      const links = [];
      building.floors.forEach((f, i) => {
        f.machine_ids.forEach((id) => links.push({ project_id: f.project_id, color_index: i, machine_id: id, active: true }));
        if (f.runtime_machine && !f.machine_ids.includes(f.runtime_machine)) links.push({ project_id: f.project_id, color_index: i, machine_id: f.runtime_machine, active: false });
      });
      return {
        position: o.position,
        machines: o.machines.map((m) => Object.assign(pick(m, ['id', 'kind', 'name', 'online', 'containers', 'late_receipts', 'runtime_for', 'fault']), {
          actions: (m.actions || []).map((a) => ({ label: a.label, state: a.state, project_name: a.project_name }))
        })),
        links
      };
    },
    // 楼里的动作要有项目（画在那一层），机房的动作要有机器
    actions(ev) {
      const f = BUILDING[ev.type];
      return f ? drop(f(ev)).filter((a) => (a.kind.indexOf('machine_') === 0 ? Boolean(a.machine) : Boolean(ev.project_id))) : [];
    }
  };

  // 实时内容：这条事件的流式文字（{ who: { room, role }, text }），不是流式文字时为 null
  T.stream = (ev) => (REALTIME[ev.type] ? REALTIME[ev.type](ev) : null);

  // 覆盖核对用：三个场景翻成动作的、作为实时内容转交的、不画的事件种类
  T.coverage = {
    floor: { drawn: Object.keys(FLOOR), realtime: Object.keys(REALTIME), none: FLOOR_NONE },
    room: { drawn: Object.keys(ROOM), realtime: Object.keys(REALTIME), none: ROOM_NONE },
    building: { drawn: Object.keys(BUILDING), realtime: [], none: BUILDING_NONE }
  };
})();
