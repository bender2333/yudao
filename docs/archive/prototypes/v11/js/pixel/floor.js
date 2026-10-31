// 项目楼层（设计说明第 5.2 至 5.6 节）：大厅（信箱、排队的包裹、槽位灯）、部门房间与交接管道、传信管、
// 回流管道、成果库、通往机房的门（3.2C）、上方信息条。房间、管道、任务、陈设都来自 floor-decl.js 的声明，这里没有具体的部门名。
// 状态以 setModel 为准，事件变成角色的任务或者信号
(function () {
  'use strict';
  const Y11 = window.Y11;
  const P = Y11.pixel;
  if (!P || !P.createScene) throw new Error('floor.js 需要先加载 js/pixel/engine.js');
  if (!P.ecs) throw new Error('floor.js 需要先加载 js/pixel/ecs.js');
  if (!P.floorDecl) throw new Error('floor.js 需要先加载 js/pixel/floor-decl.js');
  const ECS = P.ecs;
  const DECL = P.floorDecl;
  const G = ECS.GEO;
  const PAL = P.PAL;
  const R = P.R, RB = P.RB, paint = P.paint;

  const W = 640, H = 320;
  const BAR = 18;                 // 信息条高度
  const TOP = G.TOP;              // 房间上沿
  const FLOOR_LINE = G.FLOOR_LINE; // 房间内墙与地面的分界
  const ROOM_B = G.ROOM_B;        // 房间下沿（门所在的墙）
  const DESK_Y = G.DESK_Y;        // 工位的桌面前沿
  const PIPE_Y = G.PIPE_Y;        // 交接管道的高度
  const TUBE_Y = G.TUBE_Y;        // 相邻房间之间传信管的高度
  const CORR_Y = 238;             // 走廊
  const ART_BMP = { prd: 'scroll', box: 'box_sealed', defect: 'box_rework', release: 'box_release', letter: 'letter' };
  const IN_ROOM = ['running', 'asking', 'waiting_provider', 'paused', 'failed', 'done', 'cancelled', 'interrupted', 'pending_verification', 'waiting_resume', 'waiting_decision', 'stopped_for_upgrade'];
  const ACTIVE = ['running', 'asking', 'pending_verification'];
  const STATUS_TEXT = {
    queued: '排队中', waiting_slot: '等待执行槽位', running: '运行中', asking: '询问中', waiting_provider: '等待模型服务', paused: '已暂停',
    failed: '失败', done: '已完成', cancelled: '已取消', interrupted: '中断', pending_verification: '待核实', waiting_resume: '待恢复',
    stopped_for_upgrade: '因升级停止', adopted: '已采纳', waiting_decision: '等待你的决定'
  };
  const STATUS_CHIP = {
    waiting_decision: PAL.yellow2,
    running: PAL.green2, asking: PAL.blue2, queued: PAL.grey2, waiting_slot: PAL.grey2, waiting_provider: PAL.grey3, paused: PAL.blue1,
    failed: PAL.red2, done: PAL.green1, cancelled: PAL.grey2, interrupted: PAL.grey3, pending_verification: PAL.yellow2,
    waiting_resume: PAL.yellow2, stopped_for_upgrade: PAL.orange2, adopted: PAL.green3
  };
  const TUBE = '#7fc3e8', TUBE_D = '#3f86b0';

  // 五种收敛状态与「不判定」：颜色与文字一起表示状态，覆盖层「循环」的图例、观测页与离开期间的报告共用这一组（design.md 第 3 节）
  P.LOOP_STATES = {
    converging: { label: '收敛中', color: PAL.green2, fg: PAL.white },
    stalled: { label: '停滞', color: PAL.yellow2, fg: PAL.ink },
    oscillating: { label: '震荡', color: PAL.orange2, fg: PAL.ink },
    drifting: { label: '漂移', color: '#8f5fcf', fg: PAL.white },
    at_bound: { label: '达到边界', color: PAL.red2, fg: PAL.white },
    not_judged: { label: '不判定', color: PAL.grey2, fg: PAL.ink }
  };
  const RESULT_TEXT = { pass: '通过', fail: '未通过', not_run: '还没有在当前快照上运行' };

  // 画面状态与事实的对照：动作图鉴列出（设计说明第 5.4 节）
  P.FLOOR_VIEWS = [
    { id: 'working', fact: '部门正在工作', source: '事项的当前部门与 department_activated', picture: '该房间亮灯，房间里的小人在工位工作', level: 'ui', events: ['department_activated'] },
    { id: 'handoff', fact: '交接', source: 'transition 与交接内容', picture: '包裹在交接管道中移动', level: 'ui', events: ['transition'] },
    { id: 'rework', fact: '返工', source: 'qa_submitted 的结论为 rework_engineering', picture: '包裹贴红色返工单反向或经回流管道流动，管道闪红色', level: 'ui', events: ['qa_submitted', 'transition'] },
    { id: 'ask', fact: '询问与回答', source: 'collaboration_requested、collaboration_responded、collaboration_closed', picture: '信件在传信管中往返；未回答的信件停在出口', level: 'ui', events: ['collaboration_requested', 'collaboration_responded'] },
    { id: 'cycle', fact: '循环次数与时间', source: 'run 的循环计数、已用时间与时间上限', picture: '信息条显示「第 N 轮」与时间进度条；接近上限时变为警示色', level: 'ui', events: [] },
    { id: 'adopt', fact: '采纳', source: 'deliverable_adopted', picture: '箱子放上成果库的架子，版本号加一', level: 'ui', events: ['deliverable_adopted'] },
    { id: 'waiting_resume', fact: '待恢复', source: '模型引用无法使用的决定请求', picture: '涉及的房间门口立「待恢复」牌，写明缺少的项', level: 'ui', events: ['x_decision_issued'] },
    { id: 'interrupted', fact: '中断', source: '恢复观察状态为中断', picture: '整层变暗，墙上时钟停住，管道停止', level: '3.1', events: ['x_run_interrupted'] },
    { id: 'resumed', fact: '自动继续', source: 'Yudao 启动时自动继续中断的 run', picture: '灯亮起，时钟继续走，管道恢复流动', level: '3.1', events: ['x_run_auto_resumed'] },
    { id: 'pending', fact: '待核实', source: '恢复观察状态为待核实', picture: '涉及的房间亮黄灯，小人头顶出现问号', level: '3.1', events: ['x_action_unknown'] },
    { id: 'upgrade', fact: '因升级停止', source: '停止原因为因升级停止', picture: '门口立「因升级停止」牌；该事项的新包裹排到大厅队首', level: '3.1', events: ['x_run_stopped_for_upgrade'] },
    { id: 'remote', fact: '远程动作', source: '动作的执行机器', picture: '通往机房的门上的动作数变化，门缝透出光', level: '3.2C', events: ['x_remote_action_started', 'x_remote_action_finished'] },
    { id: 'agent_offline', fact: '执行代理离线', source: '心跳超时，动作结果未知', picture: '通往机房的门上出现黄色问号', level: '3.2C', events: ['x_machine_offline'] },
    { id: 'queue', fact: '同一项目排队', source: '项目的排队顺序', picture: '大厅管道入口前的包裹队列，顺序随调整变化', level: '3.4A', events: ['x_queued', 'x_queue_reordered'] },
    { id: 'slot', fact: '等待执行槽位', source: '执行槽位已满', picture: '大厅的槽位灯全亮，队首包裹停在入口，阀门关闭', level: '3.4A', events: ['x_slot_acquired'] },
    { id: 'provider', fact: '等待模型服务', source: '进入与离开等待模型服务的事件', picture: '涉及部门的管道停止，显示下一次重试时间；房间灯光调暗', level: 'S4', events: ['x_provider_wait_entered', 'x_provider_wait_left'] },
    { id: 'deploy', fact: '发布与回滚', source: '运维的部署与回滚记录', picture: '包裹从运维房间送进通往机房的门；回滚时旧版本的包裹从门里送出', level: 'S4', events: ['x_deployed', 'x_rolled_back'] },
    { id: 'fault', fact: '故障与修复', source: '故障记录与修复事项', picture: '运维房间监控屏变红；故障信件经地板下的管道送回大厅成为修复事项包裹', level: 'S4', events: ['x_fault_recorded', 'x_repair_created'] },
    { id: 'repair_stopped', fact: '停止自动修复', source: '同一故障连续修复失败', picture: '运维房间门口立「停止自动修复」牌', level: 'S4', events: ['x_auto_repair_stopped'] },
    { id: 'terminal', fact: '终止', source: 'run_done、run_failed、run_paused、取消', picture: '门口立完成、失败（停止原因）、暂停或已取消的牌子', level: 'ui', events: ['run_done', 'run_failed', 'run_paused'] },
    { id: 'decision', fact: '等待回答的决定请求', source: '决定请求（decisions.list）与 x_decision_issued', picture: '提出决定的部门的经理走到门口送出决定单，飞到大厅墙上的板子；点板子，卡片在画面里摊开，点章回答；回答过的决定单飞回部门门口，经理收下', level: 'ui', events: ['x_decision_issued', 'x_decision_answered', 'project_decision_requested', 'project_decision_answered'] },
    { id: 'roles', fact: '部门内的分派与交回', source: '角色任务事件（x_role_task_assigned、x_role_result_returned）、审查与探索者事件', picture: '经理走到角色的工位旁递任务卡，角色走到经理身旁交回结果，审查者盖章，探索者走到文件柜；房间里有几个角色就有几个小人', level: 'S5', events: ['x_role_task_assigned', 'x_role_result_returned', 'x_review_recorded', 'x_explorer_fetch'] },
    { id: 'idle', fact: '空闲', source: '部门没有事项，角色没有任务', picture: '坐着喝茶的小人隔几秒自己挑一件事：伸懒腰、走动、翻文件柜、门口抬头看、两个空闲的小人碰头说话；管道停止时光点留在管道里', level: 'ui', events: [] },
    { id: 'loops', fact: '循环实例与收敛状态', source: 'run.loops：由事件按规则算出的收敛状态与判定依据', picture: '覆盖层「循环」：信息条写 run 的收敛状态，部门房间写这次激活的已用时间与上限，正在工作的角色头顶写步骤循环；颜色与文字一起表示状态，右上角有图例', level: 'pilot', events: ['qa_submitted', 'tool_started', 'transition', 'run_failed'] },
    { id: 'sources', fact: '事实来源', source: 'project.loop 按「事件加字段」给出每个事实元素的来源（已用时间这类测量值为主机测量）', picture: '覆盖层「来源」：画面其余部分调暗，事实元素按确定规则、决策模型、角色陈述、主机测量、用户描边，角色陈述与决策模型用加粗的虚线；点元素打开来源卡片', level: 'pilot', events: [] },
    { id: 'coverage', fact: '检验覆盖与开环', source: 'acceptance.coverage：每条验收条件的检验方式、最近的结果与是否开环', picture: '覆盖层「检验」：质检房间写检验覆盖比例、模型阅读与开环的条件数，开环时黄底；点开是逐条清单；放行的盖章旁写这次放行的覆盖比例', level: 'pilot', events: ['qa_submitted', 'x_evidence_checked'] }
  ];

  // ---------------------------------------------------------------------------
  // 房间与管道：按声明排布（floor-decl.js）；有些房间只在快照带着对应字段时出现（声明里的 when，例如运维房间）

  function flagsOf(m) {
    const f = {};
    DECL.flags.forEach((k) => { f[k] = Boolean(m[k]); });
    return f;
  }

  function declareWorld(flags) {
    const world = ECS.world({ tasks: DECL.tasks, idle: DECL.idle, keyOf: DECL.keyOf });
    ECS.declareRooms(world, DECL.rooms, flags);
    ECS.declareLinks(world, DECL.links);
    return world;
  }

  // 画面按房间种类取用的排布：大厅、成果库、部门房间（按排布顺序），大厅交接管道通到的第一个房间
  function layOf(world) {
    const rooms = world.roomOrder.map((id) => world.rooms[id]);
    const hall = rooms.find((r) => r.roomKind === 'hall');
    const out = Object.values(world.links).find((l) => l.from === hall.id && l.linkKind === 'handoff');
    return {
      hall, lib: rooms.find((r) => r.roomKind === 'shelf'), depts: rooms.filter((r) => r.roomKind === 'dept'),
      out, gate: world.rooms[out.to], door: world.machineDoor,
      verify: rooms.find((r) => r.def.verifies) || null
    };
  }

  // ---------------------------------------------------------------------------

  P.createFloorScene = function createFloorScene(canvas, opts) {
    const o = opts || {};
    let model = { items: [], open_requests: [], shelves: { adopted: [] }, slots: null, waiting_provider: [], machines: null, ops: null, interrupted: false, roles: null, decisions: [] };
    let flags = flagsOf(model);
    let world = declareWorld(flags);
    let lay = layOf(world);
    let focusId = null;
    let overlay = { id: null, data: null };
    const st = {
      clock: 15.5 * 3600000, flash: {}, pipeFlash: {}, arrows: [], hidden: {}, remoteDots: [], queueX: {}, n: 0, said: {},
      facts: [], labels: [], barX: 0, wantFact: null
    };
    const scene = P.createScene(canvas, { W, H, draw, update });
    // 世界里的决定卡片：决定单贴在大厅的板上，点开在画面里回答（decision-card.js）
    const card = P.createDecisionCard(scene, canvas, { onDecide: o.onDecide, onGo: o.onGo });
    // 来源卡片：点事实元素打开，写给出这条事实的事件与来源种类（source-card.js）
    const sourceCard = P.createSourceCard(scene, canvas, { onSeek: o.onSeek, fetchEvent: o.fetchEvent });
    let bg = null, bgKey = '';

    // -------------------------------------------------------------------------
    // 事实元素（design.md 第 5 节）：每帧画的时候收集 { kind, rect, position, field, source }，供覆盖层「来源」、点击与验收脚本使用。
    // 来源按「事件加字段」由读取模型给出（refs 写成 { position, field, source }）；覆盖层的标签只有事件位置时按事件种类。
    // 快照里没有来源（自举试点以前的档位）时，画面照旧，元素不是事实元素

    const sourceCache = new Map();
    function sourceOf(position) {
      if (!position || !o.fetchEvent) return null;
      if (!sourceCache.has(position)) {
        const ev = o.fetchEvent(position);
        sourceCache.set(position, ev && ev.source ? ev.source : null);
      }
      return sourceCache.get(position);
    }

    function fact(kind, rect, ref, extra) {
      const r = ref && typeof ref === 'object' ? ref : { position: ref || null, field: null, source: sourceOf(ref) };
      const f = Object.assign({
        kind, rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.w), h: Math.round(rect.h) },
        position: r.position || null, field: r.field || null, source: r.source || null
      }, extra || {});
      st.facts.push(f);
      return f;
    }

    // 快照带着来源时，没有来源的元素不画
    const noSource = (refs, key) => Boolean(refs) && !refs[key];

    const itemById = (id) => model.items.find((it) => it.id === id) || null;
    const dimFor = (itemId) => (focusId && itemId && itemId !== focusId ? 0.3 : 1);
    const itemsIn = (d) => model.items.filter((it) => it.department === d && IN_ROOM.includes(it.status));
    const waitingDept = (d) => (model.waiting_provider || []).find((w) => w.department === d) || null;
    const roomById = (id) => (id === 'adopted' || id === 'adoption' ? lay.lib : world.rooms[id] || null);
    const sig = (name) => ECS.signalOn(world, scene, name);

    // 声明里的规则读取画面数据的窗口
    const ctx = { model, order: world.roomOrder, waitingDept, time: Y11.time, sig, get reduced() { return scene.reduced; } };

    // -------------------------------------------------------------------------
    // 房间里的小人：每个房间按角色设置有几个，没有角色设置时一个部门一个

    function primaryItem(d) {
      const here = itemsIn(d);
      return here.find((it) => ACTIVE.includes(it.status)) || here.find((it) => it.status === 'waiting_provider') || here[0] || null;
    }

    function specsFor() {
      const out = [];
      lay.depts.forEach((r) => {
        const roles = model.roles && model.roles[r.id];
        if (roles && roles.length) roles.forEach((ro) => out.push({ id: ro.id, department: r.id, roleKind: ro.kind, name: ro.name, role: ro }));
        else out.push({ id: r.id, department: r.id, roleKind: r.def.agentKind, name: r.label, role: null });
      });
      return out;
    }

    // 每个角色一个实体（P.ecs）：快照决定小人现在该干什么（ch.rest），事件变成任务放进队列
    function syncWorkers() {
      ctx.model = model;
      ctx.order = world.roomOrder;
      const specs = specsFor();
      ECS.syncCharacters(world, scene, specs, (s) => s.department + '.' + s.roleKind);
      specs.forEach((s) => {
        const ch = world.characters[s.id];
        const room = world.rooms[s.department];
        ch.item = primaryItem(s.department);
        ch.roleInfo = s.role;
        ch.rest = DECL.roleRest(ctx, s.department, ch.item, s.role, ECS.primaryOf(world, s.department) === ch, room.def.rest || DECL.deptRest);
      });
    }

    function workerOf(ch) { return ECS.actorOf(world, scene, ch.id); }

    // 小人头顶说的内容：来自事件（P.say，js/pixel/say.js）；目录里没有这类事件时，任务用自己声明的标签。
    // side 为 'to' 表示说话的小人是事件里收东西的一方
    function sayOf(ev, dept, side) {
      const text = P.say(ev, { dept, side, roleName: (id) => (world.characters[id] || {}).name || null });
      return text ? { label: text } : {};
    }

    function said(ch, text) {
      st.said[ch.id] = { text, kind: 'say', until: scene.realT + P.sayMs(text) };
    }

    // 小人走到管道口放下或取出包裹：任务放到队首（交接不排队），做完以后执行 after；没有角色时直接执行。
    // 减少动画时小人不走动，只在原处说话
    function trip(d, key, after, extra) {
      if (scene.reduced) {
        const def = world.catalog.tasks[key];
        const ch = def && ECS.charFor(world, d, null, def.actor || def.by);
        if (ch && extra && extra.label) said(ch, extra.label);
        if (after) after();
        return;
      }
      if (!ECS.enqueue(world, d, key, Object.assign({ front: true, must: true, onDone: after }, extra))) { if (after) after(); }
    }

    // -------------------------------------------------------------------------
    // 管道中的包裹

    function pathFor(from, to) {
      const l = ECS.linkBetween(world, from, to, 'handoff');
      return l ? { pts: l.pts, key: l.key, link: l.link } : null;
    }

    function tubeFor(from, to) {
      const l = ECS.linkBetween(world, from, to, 'tube');
      return l ? l.pts : null;
    }

    function tubeKeyOf(from, to) {
      const l = ECS.linkBetween(world, from, to, 'tube');
      return l ? l.key : null;
    }

    // 包裹是 world.packages 里的实体：沿管道移动，到达终点后销毁并执行 onDone；linkKey 标出它经过的管道
    let packageSeq = 0;
    function send(pts, bmp, opt) {
      const option = opt || {};
      if (!pts) { if (option.onDone) option.onDone(); return; }
      if (scene.reduced) {
        st.arrows.push({ pts, color: option.color || PAL.white, bmp, until: scene.realT + 3600, itemId: option.itemId, dash: option.small });
        if (option.onDone) option.onDone();
        return;
      }
      const id = 'pk-' + (++packageSeq);
      const pk = ECS.spawnPackage(world, id, option.itemId || null, null, option.artifact || null, null);
      Object.assign(pk, { bmp, color: option.color, small: option.small, fact: option.fact || null });
      ECS.sendPackage(world, id, option.linkKey || null, pts, option.ms, () => {
        ECS.removePackage(world, id);
        if (option.onDone) option.onDone();
      });
    }

    function drawPackages(c) {
      Object.values(world.packages).forEach((pk) => {
        const pos = ECS.packagePosition(pk);
        if (!pos) return;
        const [x, y] = pos;
        c.globalAlpha = dimFor(pk.workItemId);
        let rect;
        if (pk.small) {
          RB(c, Math.round(x) - 2, Math.round(y) - 1, 5, 3, PAL.white);
          R(c, Math.round(x) - 1, Math.round(y), 3, 1, pk.color || PAL.blue2);
          rect = { x: x - 4, y: y - 3, w: 8, h: 7 };
        } else {
          const b = P.bitmap(pk.bmp);
          P.drawBitmap(c, pk.bmp, Math.round(x - b.w / 2), Math.round(y - b.h / 2));
          if (pk.color) R(c, Math.round(x - b.w / 2), Math.round(y + b.h / 2), b.w, 2, pk.color);
          rect = { x: x - b.w / 2, y: y - b.h / 2, w: b.w, h: b.h + 2 };
        }
        c.globalAlpha = 1;
        // 管道中的包裹：来源是引起这次交接或传信的事件（事件对象带 source）
        if (pk.fact) fact('package', rect, pk.fact, { title: pk.fact.title });
      });
    }

    // 管道中的包裹：来源是引起这次移动的事件，按事件种类
    const transitFact = (ev) => (ev.source && ev.position ? { position: ev.position, field: null, source: ev.source, title: '管道中的包裹：' + (ev.label || ev.type) } : null);

    // -------------------------------------------------------------------------
    // 事件

    function flash(id, color, ms) { st.flash[id] = { color, until: scene.realT + (ms || 900) }; }

    // 任务声明里的效果（floor-decl.js 的 fx）：信号、房间闪光、包裹沿管道走
    function applyFx(f, ev, ch) {
      if (f.signal) ECS.signal(world, scene, f.signal, f.ms);
      if (f.flash) flash(f.flash.room === 'self' ? ch.department : f.flash.room, PAL[f.flash.color], f.flash.ms);
      if (f.send) {
        const link = world.links[f.send.link];
        if (!link) return;
        send(f.send.reverse ? link.pts.slice().reverse() : link.pts, f.send.bmp, {
          color: f.send.color ? PAL[f.send.color] : null, linkKey: link.id, fact: transitFact(ev),
          onDone: () => (f.send.then || []).forEach((g) => applyFx(g, ev, ch))
        });
      }
    }

    // 交给 ECS.dispatch 的 make：任务头顶说的内容与声明里的效果
    function extrasOf(def, ev, ch, side) {
      const out = sayOf(ev, ch.department, side);
      if (def.fx) {
        const run = (when) => () => def.fx.filter((f) => f.when === when).forEach((f) => applyFx(f, ev, ch));
        out.start = run('start');
        out.done = run('done');
      }
      return out;
    }

    function dispatchTask(ev) { return ECS.dispatch(world, ev, extrasOf); }

    function playEvent(ev) {
      if (!ev || !ev.type) throw new Error('playEvent 需要事件对象');
      const pl = ev.payload || {};
      const wid = ev.work_item_id;
      const it = itemById(wid);
      const color = it ? P.ITEM_COLORS[it.color_index % P.ITEM_COLORS.length] : null;
      const order = world.roomOrder;
      switch (ev.type) {
        case 'user_input_received':
        case 'work_item_created':
          if (!scene.reduced) scene.fly({ bmp: 'letter', from: [-6, PIPE_Y - 20], to: [lay.hall.x + 16, PIPE_Y + 6], ms: 900, arc: 20, onDone: () => { ECS.signal(world, scene, 'mail', 1500); } });
          else ECS.signal(world, scene, 'mail', 1500);
          return;
        case 'department_activated':
          if (ev.department && roomById(ev.department)) flash(ev.department, PAL.yellow1, 700);
          return;
        case 'transition': {
          let to = pl.to;
          if (to === 'adopted' || to === 'adoption') to = lay.lib.id;
          const from = pl.from;
          // 两个房间之间没有直接的管道时，包裹沿声明的管道一段一段走过去（例如质检放行交给运维，中间经过成果库）
          const hops = ECS.route(world, from, to);
          if (!hops.length) return;
          const ids = lay.depts.map((r) => r.id);
          const rework = pl.artifact === 'defect' || hops[0].link.linkKind === 'return' || (ids.includes(from) && ids.includes(to) && order.indexOf(from) > order.indexOf(to));
          if (rework) hops.forEach((h) => { st.pipeFlash[h.key] = scene.realT + 2600; });
          const bmp = ART_BMP[pl.artifact] || 'box_sealed';
          // 交出方走到管道口放下包裹，包裹沿管道移动，接收方走到管道口取出：两端各是一个任务
          const arrive = () => { flash(to, PAL.white, 500); trip(to, rework ? 'package_return_in' : 'package_handoff_in', null, sayOf(ev, to, 'to')); };
          const leg = (i) => send(hops[i].pts, bmp, { itemId: wid, color, linkKey: hops[i].key, fact: transitFact(ev), onDone: () => (i + 1 < hops.length ? leg(i + 1) : arrive()) });
          trip(from, rework ? 'package_return_out' : 'package_handoff_out', () => leg(0), sayOf(ev, from, 'from'));
          return;
        }
        case 'qa_submitted':
          if (ev.department) flash(ev.department, pl.verdict === 'release' ? PAL.green2 : PAL.red2, 1200);
          dispatchTask(ev);
          return;
        // 传信：发信的经理走到管口塞进信，信沿传信管走，收信的经理走到信来的那一侧管口取信
        case 'collaboration_requested': {
          const pts = tubeFor(pl.from, pl.to);
          const forward = order.indexOf(pl.to) > order.indexOf(pl.from);
          trip(pl.from, forward ? 'letter_out' : 'letter_in', () => send(pts, 'letter', {
            small: true, itemId: wid, color: PAL.blue2, linkKey: tubeKeyOf(pl.from, pl.to), fact: transitFact(ev),
            onDone: () => trip(pl.to, forward ? 'letter_arrive_in' : 'letter_arrive_out', null, sayOf(ev, pl.to, 'to'))
          }), sayOf(ev, pl.from, 'from'));
          return;
        }
        case 'collaboration_responded': {
          // 回答方是事件所在的部门（示例数据里 from 是回答方，v8 构建约定里 to 是回答方），另一头是发问方
          const answerer = ev.department || pl.to;
          const asker = pl.from === answerer ? pl.to : pl.from;
          const pts = tubeFor(answerer, asker);
          const forward = order.indexOf(asker) > order.indexOf(answerer);
          trip(answerer, forward ? 'letter_out' : 'letter_in', () => send(pts, 'letter', {
            small: true, itemId: wid, color: PAL.green2, linkKey: tubeKeyOf(answerer, asker), fact: transitFact(ev),
            onDone: () => trip(asker, forward ? 'letter_arrive_in' : 'letter_arrive_out', null, sayOf(ev, asker, 'to'))
          }), sayOf(ev, answerer, 'from'));
          return;
        }
        case 'deliverable_adopted':
          ECS.signal(world, scene, 'shelf', 1800);
          scene.emit('spark', lay.lib.x + lay.lib.w / 2, 110, 16);
          return;
        case 'x_queued':
        case 'x_repair_created':
          ECS.signal(world, scene, 'mail', 1500);
          if (!scene.reduced) scene.fly({ bmp: ev.type === 'x_repair_created' ? 'box_rework' : 'box', from: [lay.hall.x + 16, PIPE_Y + 10], to: [lay.hall.x + 50, PIPE_Y - 4], ms: 700, arc: 14 });
          return;
        case 'x_slot_acquired': {
          st.flash[lay.hall.id] = { color: PAL.green2, until: scene.realT + 900 };
          send(lay.out.pts, 'box', { itemId: wid, color, linkKey: lay.out.id, fact: transitFact(ev), onDone: () => trip(lay.out.to, 'package_handoff_in') });
          return;
        }
        case 'x_queue_reordered':
          st.flash[lay.hall.id] = { color: PAL.blue1, until: scene.realT + 900 };
          return;
        case 'x_run_interrupted':
          return;
        case 'x_run_auto_resumed':
          Object.keys(world.characters).forEach((id) => ECS.enqueue(world, id, 'x_run_auto_resumed'));
          lay.depts.forEach((r) => flash(r.id, PAL.yellow1, 700));
          return;
        case 'x_action_unknown':
          if (ev.department) flash(ev.department, PAL.yellow2, 1400);
          return;
        case 'x_remote_action_started':
        case 'x_remote_action_finished':
        case 'x_late_receipt': {
          ECS.signal(world, scene, 'door', 1800);
          const r = ev.department ? roomById(ev.department) : null;
          if (r && !scene.reduced) {
            const from = ev.type === 'x_remote_action_started' ? [r.door, ROOM_B + 6] : [lay.door.x, CORR_Y];
            const to = ev.type === 'x_remote_action_started' ? [lay.door.x, CORR_Y] : [r.door, ROOM_B + 6];
            st.remoteDots.push({ from, to, t0: scene.realT, ms: 1400 });
          }
          return;
        }
        case 'x_decision_issued':
        case 'project_decision_requested': {
          // 提出决定的部门的小人走到门口送出决定单，决定单飞到大厅的板上；决定单在路上的时候板上还看不到它
          const d = ev.department || (it && it.department);
          const room = d && world.rooms[d] && world.rooms[d].roomKind === 'dept' ? world.rooms[d] : null;
          const b = boardRect();
          if (pl.decision_id) st.hidden[pl.decision_id] = scene.realT + 12000;
          let posted = false;
          const post = () => {
            if (posted) return;
            posted = true;
            scene.fly({
              bmp: 'decision', from: room ? [room.door, ROOM_B + 4] : [b.x + b.w / 2, TOP - 6], to: [b.x + b.w / 2, b.y + b.h / 2], ms: 1000, arc: 26,
              onDone: () => { delete st.hidden[pl.decision_id]; ECS.signal(world, scene, 'board', 1600); }
            });
          };
          if (room && !scene.reduced && ECS.dispatch(world, Object.assign({}, ev, { department: d }), () => ({ done: post }))) scene.after(8000, post);
          else post();
          return;
        }
        case 'x_decision_answered':
        case 'project_decision_answered': {
          // 回答过的决定单从板上飞回提出决定的部门的门口，小人在门口收下
          const d = ev.department || (it && it.department);
          const room = d && world.rooms[d] && world.rooms[d].roomKind === 'dept' ? world.rooms[d] : null;
          const b = boardRect();
          if (pl.decision_id && card.openId() === pl.decision_id) card.stamp(pl.decision_id, '已回答');
          if (room) {
            scene.fly({
              bmp: 'decision', from: [b.x + b.w / 2, b.y + b.h / 2], to: [room.door, ROOM_B + 4], ms: 1000, arc: 26,
              onDone: () => { if (!scene.reduced) ECS.dispatch(world, Object.assign({}, ev, { department: d })); }
            });
          }
          return;
        }
        case 'x_provider_wait_entered':
        case 'x_provider_wait_left':
          if (ev.department) flash(ev.department, ev.type === 'x_provider_wait_entered' ? PAL.grey3 : PAL.yellow1, 900);
          if (ev.type === 'x_provider_wait_left') dispatchTask(ev);
          return;
        case 'run_done':
          scene.emit('confetti', W / 2, 60, 40, { spread: 560 });
          dispatchTask(ev);
          return;
        default:
          // 其余事件由任务目录决定：命中的事件变成角色的任务，没有命中的事件在画面上没有小人的动作
          dispatchTask(ev);
      }
    }

    // -------------------------------------------------------------------------
    // 更新

    function update() {
      if (!model.interrupted) st.clock += scene.reduced ? 0 : 16.7;
      ECS.stepPackages(world, scene);
      ECS.stepPipes(world, scene, pipeState);
      ECS.stepCharacters(world, scene);
      Object.values(world.characters).forEach((ch) => {
        const a = workerOf(ch);
        if (a) a.dim = dimFor(ch.item && ch.item.id);
      });
      st.arrows = st.arrows.filter((ar) => ar.until > scene.realT);
      st.remoteDots = st.remoteDots.filter((d) => scene.realT - d.t0 < d.ms);
      // 队列中的包裹滑到自己的位置
      queueItems().forEach((it, i) => {
        const target = queueSlotX(i);
        const cur = st.queueX[it.id] === undefined ? target : st.queueX[it.id];
        st.queueX[it.id] = scene.reduced ? target : cur + (target - cur) * 0.12;
      });
    }

    // -------------------------------------------------------------------------
    // 背景：外墙、房间外壳、走廊与地面

    function buildBackground() {
      const key = world.roomOrder.join(',');
      if (bg && bgKey === key) return bg;
      bgKey = key;
      bg = P.makeCanvas(W, H);
      const c = bg.getContext('2d');
      c.imageSmoothingEnabled = false;
      R(c, 0, BAR, W, 32, '#9fd0ee');
      [[30, 28], [250, 24], [470, 30]].forEach(([x, y]) => { R(c, x, y, 26, 5, PAL.white); R(c, x + 6, y - 3, 14, 3, PAL.white); });
      R(c, 0, TOP - 6, W, 6, '#6f7a8c'); R(c, 0, TOP - 6, W, 1, '#8e98a9');
      R(c, 0, TOP - 2, W, ROOM_B - TOP + 4, '#4d5466');
      // 走廊与地面
      R(c, 0, ROOM_B, W, 48, '#d8cfbd');
      for (let x = 0; x < W; x += 16) R(c, x, ROOM_B, 1, 48, '#cbc1ad');
      R(c, 0, ROOM_B + 48, W, 3, '#b3a78e');
      R(c, 0, ROOM_B + 51, W, 38, '#8a7f6c');
      for (let x = 6; x < W; x += 12) R(c, x, ROOM_B + 52, 1, 36, '#7c725f');
      R(c, 0, H - 16, W, 16, '#7fae62');
      for (let x = 0; x < W; x += 6) R(c, x + (x % 12 ? 2 : 0), H - 16, 2, 2, '#6c9a52');
      // 大厅
      const hall = lay.hall;
      R(c, hall.x, TOP, hall.w, FLOOR_LINE - TOP, '#e9e2d2');
      for (let y = TOP + 8; y < FLOOR_LINE; y += 14) R(c, hall.x, y, hall.w, 1, '#ddd4c1');
      R(c, hall.x, FLOOR_LINE, hall.w, ROOM_B - FLOOR_LINE, '#c9a77a');
      for (let x = hall.x; x < hall.x + hall.w; x += 10) R(c, x, FLOOR_LINE, 1, ROOM_B - FLOOR_LINE, '#b8966a');
      lay.depts.forEach((r) => roomShell(c, r, P.DEPTS[r.id]));
      roomShell(c, lay.lib, { wall: '#efe6d2', wall2: '#e2d5b8', floor: '#b88a58', floor2: '#a37748', trim: '#6a4a2e' });
      return bg;
    }

    function roomShell(c, r, D) {
      R(c, r.x, TOP, r.w, FLOOR_LINE - TOP, D.wall);
      for (let yy = TOP + 6; yy < FLOOR_LINE; yy += 10) R(c, r.x + 4, yy, r.w - 8, 1, D.wall2);
      R(c, r.x, FLOOR_LINE, r.w, ROOM_B - FLOOR_LINE, D.floor);
      for (let yy = FLOOR_LINE + 4; yy < ROOM_B; yy += 8) R(c, r.x, yy, r.w, 1, D.floor2 || D.floor);
      R(c, r.x, FLOOR_LINE - 2, r.w, 3, D.trim);
      R(c, r.x - 3, TOP - 2, 3, ROOM_B - TOP + 4, '#2e3240');
      R(c, r.x + r.w, TOP - 2, 3, ROOM_B - TOP + 4, '#2e3240');
      R(c, r.x - 3, ROOM_B - 2, r.w + 6, 5, '#2e3240');
    }

    // -------------------------------------------------------------------------
    // 绘制：管道

    // 管道通不通：快照里两端有活跃事项，或者管道上有包裹在移动
    function pipeState(p) {
      if (model.interrupted) return 'stopped';
      const [a, b] = p.id.split(/[>~]/);
      if (waitingDept(a) || waitingDept(b)) return 'stopped';
      const active = (d) => itemsIn(d).some((it) => ACTIVE.includes(it.status));
      if (ECS.linkActive(world, p.id)) return 'flowing';
      if (p.linkKind === 'tube') return (model.open_requests || []).length ? 'flowing' : 'idle';
      return active(a) || active(b) ? 'flowing' : 'idle';
    }

    function drawPipe(c, p, t) {
      const state = pipeState(p);
      const tube = p.linkKind === 'tube';
      const thick = tube ? 3 : 8;
      const flashing = (st.pipeFlash[p.id] || 0) > scene.realT && Math.floor(t / 180) % 2 === 0;
      const outline = PAL.ink;
      const body = flashing ? PAL.red2 : tube ? TUBE : state === 'stopped' ? '#9aa0aa' : p.linkKind === 'return' ? '#c9b48a' : PAL.glass;
      const hi = PAL.white;
      for (let i = 1; i < p.pts.length; i++) {
        const [x0, y0] = p.pts[i - 1], [x1, y1] = p.pts[i];
        const x = Math.min(x0, x1) - thick / 2, y = Math.min(y0, y1) - thick / 2;
        const w = Math.abs(x1 - x0) + thick, h = Math.abs(y1 - y0) + thick;
        RB(c, x, y, w, h, body, outline);
        if (y0 === y1) R(c, x + 1, y + 1, w - 2, 1, hi);
        else R(c, x + 1, y + 1, 1, h - 2, hi);
      }
      // 金属接头
      if (!tube) p.pts.forEach(([x, y]) => RB(c, x - thick / 2 - 1, y - thick / 2 - 1, thick + 2, thick + 2, PAL.metal3));
      // 流动：沿管道移动的亮点。管道是持续运转的：流速与光点数量带着惯性（ECS.stepPipes），停下时光点留在管道里
      if (scene.reduced) return;
      const len = ECS.polyLength(p.pts);
      const gap = tube ? 14 : 22;
      const f = p.flow;
      let off, alpha;
      if (ECS.config.autonomy) {
        if (!f || f.load <= 0.02) return;
        off = (f.phase / (tube ? 30 : 45)) % gap;
        alpha = f.load;
      } else {
        if (state !== 'flowing' || scene.frozen) return;
        off = (t / (tube ? 30 : 45)) % gap;
        alpha = 1;
      }
      c.globalAlpha = alpha;
      c.fillStyle = tube ? TUBE_D : P.rgba(PAL.blue2, 0.55);
      for (let d = off; d < len; d += gap) {
        const [x, y] = ECS.pointAt(p.pts, d);
        c.fillRect(Math.round(x) - 1, Math.round(y) - (tube ? 0 : 1), 2, tube ? 1 : 2);
      }
      c.globalAlpha = 1;
    }

    function drawPort(c, x, y, kind) {
      if (kind === 'tube') { RB(c, x - 3, y - 4, 6, 8, TUBE_D); R(c, x - 1, y - 2, 2, 4, PAL.ink); return; }
      RB(c, x - 6, y - 8, 12, 16, PAL.metal2);
      R(c, x - 4, y - 5, 8, 10, PAL.ink2);
      R(c, x - 4, y - 5, 8, 1, PAL.metal1);
    }

    function drawPipes(c, t) {
      Object.values(world.links).forEach((p) => drawPipe(c, p, t));
      world.roomOrder.forEach((id) => {
        const r = world.rooms[id];
        const ports = r.def.ports || [];
        if (ports.includes('in')) drawPort(c, r.inPort, PIPE_Y, 'handoff');
        if (ports.includes('out')) drawPort(c, r.outPort, PIPE_Y, 'handoff');
        if (ports.includes('tubeIn')) drawPort(c, r.inPort, TUBE_Y, 'tube');
        if (ports.includes('tubeOut')) drawPort(c, r.outPort, TUBE_Y, 'tube');
      });
      // Stage 6 的判定阀门位置：交接管道上的空卡座
      Object.values(world.links).filter((p) => p.def.valve).forEach((p) => {
        const mx = Math.round((p.pts[0][0] + p.pts[1][0]) / 2);
        R(c, mx - 3, PIPE_Y - 9, 6, 2, PAL.metal4);
      });
      // 停止流动的说明：等待模型服务
      (model.waiting_provider || []).forEach((w) => {
        const r = roomById(w.department);
        if (!r) return;
        const text = '等待模型服务' + (w.next_retry_at ? ' · ' + Y11.time.clock(w.next_retry_at) + ' 重试' : '');
        P.sign(c, r.x + r.w / 2, PIPE_Y - 12, text, { size: 5.5, bg: PAL.grey1, stripe: PAL.grey3, maxW: r.w + 20 });
      });
      // 未回答的询问：信件停在接收方的传信管出口
      (model.open_requests || []).forEach((q, i) => {
        const pts = tubeFor(q.from, q.to);
        if (!pts) return;
        const [x, y] = pts[pts.length - 1];
        c.globalAlpha = dimFor(q.work_item_id);
        const bob = scene.reduced ? 0 : Math.round(Math.sin(t / 300 + i) * 1);
        RB(c, Math.round(x) - 4, Math.round(y) + 5 + bob, 8, 5, PAL.white);
        R(c, Math.round(x) - 3, Math.round(y) + 6 + bob, 6, 1, PAL.blue2);
        c.globalAlpha = 1;
      });
    }

    // -------------------------------------------------------------------------
    // 绘制：大厅与队列

    function queueItems() {
      return model.items.filter((it) => it.status === 'queued' || it.status === 'waiting_slot')
        .sort((a, b) => (Number(b.kind === 'repair') - Number(a.kind === 'repair')) || ((a.queue_pos || 99) - (b.queue_pos || 99)));
    }
    function queueSlotX(i) { return lay.gate.inPort - 20 - i * 15; }

    function drawHall(c, t) {
      const hall = lay.hall;
      const x = hall.x;
      P.sign(c, x + 40, TOP + 16, '大厅', { size: 7, bg: PAL.paper, stripe: PAL.wood3 });
      paint.clock(c, x + hall.w - 22, TOP + 6, st.clock, { stopped: model.interrupted });
      // 信箱：用户的输入以信件投进来，管道从这里出发
      RB(c, x + 8, PIPE_Y - 2, 14, 18, PAL.red2);
      R(c, x + 10, PIPE_Y + 1, 10, 2, PAL.ink);
      RB(c, x + 12, PIPE_Y - 7, 6, 3, sig('mail') ? PAL.yellow2 : PAL.grey4);
      P.text(c, '信箱', x + 15, PIPE_Y + 24, { size: 5.5, weight: 700, align: 'center', color: PAL.ink2 });
      // 执行槽位灯（3.4A）：整个系统的占用数与总数
      if (model.slots) {
        const total = Math.max(1, model.slots.total);
        const used = model.slots.used;
        const pw = Math.min(hall.w - 12, 12 + total * 11);
        RB(c, x + 6, TOP + 30, pw, 28, PAL.grey5);
        P.text(c, '执行槽位 ' + used + '/' + total, x + 6 + pw / 2, TOP + 36, { size: 5.5, weight: 700, align: 'center', color: PAL.white, max: pw - 4 });
        for (let i = 0; i < total; i++) {
          const on = i < used;
          RB(c, x + 11 + i * 11, TOP + 44, 7, 7, on ? PAL.green2 : PAL.grey4);
          if (on) R(c, x + 12 + i * 11, TOP + 45, 2, 2, PAL.green1);
        }
      }
      // 队列：管道入口前的一串包裹；修复事项带红色十字
      const q = queueItems();
      const slotWait = q.some((it) => it.status === 'waiting_slot');
      q.forEach((it, i) => {
        const px = Math.round(st.queueX[it.id] === undefined ? queueSlotX(i) : st.queueX[it.id]);
        if (px < x + 24 || noSource(it.refs, 'parcel')) return;
        c.globalAlpha = dimFor(it.id);
        P.drawBitmap(c, 'box', px - 6, PIPE_Y - 16);
        R(c, px - 6, PIPE_Y - 4, 12, 2, P.ITEM_COLORS[it.color_index % P.ITEM_COLORS.length]);
        if (it.kind === 'repair') { R(c, px - 1, PIPE_Y - 14, 2, 6, PAL.red2); R(c, px - 3, PIPE_Y - 12, 6, 2, PAL.red2); }
        if (it.queue_pos) P.pixText(c, String(it.queue_pos), px, PIPE_Y - 24, PAL.ink, 'center');
        c.globalAlpha = 1;
        if (it.refs) fact('parcel', { x: px - 7, y: PIPE_Y - 25, w: 14, h: 23 }, it.refs.parcel, { title: '大厅里排队的包裹：' + it.title, itemId: it.id });
      });
      // 入口阀门：等待执行槽位时关闭
      const vx = lay.gate.inPort - 8;
      RB(c, vx - 2, PIPE_Y - 7, 4, 14, PAL.metal3);
      RB(c, vx - 5, PIPE_Y - 12, 10, 3, slotWait ? PAL.red2 : PAL.green2);
      if (slotWait) P.sign(c, x + hall.w / 2 + 6, PIPE_Y + 38, '等待执行槽位', { size: 5.5, bg: PAL.yellow1, stripe: PAL.orange2, maxW: hall.w });
      if ((st.flash[hall.id] || {}).until > scene.realT) paint.blinkFrame(c, x + 26, PIPE_Y - 20, lay.gate.inPort - x - 30, 22);
      // 长椅与植物
      RB(c, x + 30, ROOM_B - 14, 34, 4, PAL.wood2); R(c, x + 32, ROOM_B - 10, 2, 8, PAL.wood4); R(c, x + 60, ROOM_B - 10, 2, 8, PAL.wood4);
      paint.plant(c, x + hall.w - 16, ROOM_B - 2);
      drawBoard(c);
    }

    // 大厅的决定板：立在大厅地面上的告示板，等待回答的决定请求一张一张贴在上面（还在路上的不算），点板子打开卡片。
    // 板子在地面上，不与墙上的钟、槽位灯、管道重叠
    function boardRect() {
      const h = lay.hall;
      return { x: h.x + 62, y: FLOOR_LINE + 10, w: 32, h: 24 };
    }

    // 决定单还在路上（从部门门口飞往板子）：最长藏 12 秒，落到板上时提前解除
    const inFlight = (id) => (st.hidden[id] || 0) > scene.realT;

    function decisionColor(d) {
      const it = d.work_item_id ? itemById(d.work_item_id) : null;
      return it ? P.ITEM_COLORS[it.color_index % P.ITEM_COLORS.length] : PAL.grey2;
    }

    function drawBoard(c) {
      const ds = model.decisions || [];
      if (!ds.length) return;
      const b = boardRect();
      P.sign(c, b.x + b.w / 2, b.y - 3, '待你决定', { size: 5.5, bg: PAL.yellow1, stripe: PAL.orange2 });
      R(c, b.x + 3, b.y + b.h + 2, 2, 8, PAL.wood4);
      R(c, b.x + b.w - 5, b.y + b.h + 2, 2, 8, PAL.wood4);
      RB(c, b.x - 2, b.y - 2, b.w + 4, b.h + 4, PAL.wood3);
      R(c, b.x, b.y, b.w, b.h, '#c9955c');
      const shown = ds.filter((d) => !inFlight(d.id));
      shown.slice(0, 6).forEach((d, i) => {
        const nx = b.x + 3 + (i % 3) * 10, ny = b.y + 3 + Math.floor(i / 3) * 12;
        RB(c, nx, ny, 8, 10, PAL.white);
        R(c, nx, ny, 8, 2, decisionColor(d));
        R(c, nx + 2, ny + 4, 4, 1, PAL.grey2);
        R(c, nx + 2, ny + 6, 4, 1, PAL.grey2);
      });
      if (shown.length > 6) P.text(c, '+' + (shown.length - 6), b.x + b.w - 3, b.y + b.h - 4, { size: 5.5, weight: 800, align: 'right', color: PAL.ink });
      if (sig('board') && !scene.reduced) paint.blinkFrame(c, b.x - 3, b.y - 3, b.w + 6, b.h + 6);
    }

    const overBoard = (x, y) => {
      const b = boardRect();
      return (model.decisions || []).length > 0 && x >= b.x - 2 && x <= b.x + b.w + 2 && y >= b.y - 12 && y <= b.y + b.h + 10;
    };

    // -------------------------------------------------------------------------
    // 绘制：部门房间、成果库

    function deskMode(ch) {
      if (model.interrupted) return 'off';
      const info = ch.roleInfo;
      // 房间里有多个角色时，中心角色的屏幕反映事项的状态，其余角色的屏幕看自己有没有在工作
      if (info && ECS.primaryOf(world, ch.department) !== ch) return info.status === 'working' ? 'code' : 'idle';
      const it = ch.item;
      return it && it.status === 'running' ? 'code' : it && it.status === 'failed' ? 'error' : it && it.status === 'pending_verification' ? 'alert' : 'idle';
    }

    function drawDeptRoom(c, r, t) {
      const D = P.DEPTS[r.id];
      const here = itemsIn(r.id);
      const working = here.some((it) => ACTIVE.includes(it.status));
      const sx = r.x + Math.round(r.w / 2) - 22, sy = TOP + 18;
      RB(c, sx - 2, sy - 2, 32, 22, PAL.beige2);
      paint.screen(c, sx, sy, 28, 18, model.interrupted ? 'off' : working ? 'code' : 'idle', t, { seed: r.x });
      paint.scanlines(c, sx, sy, 28, 18, 0.18);
      paint.lamp(c, r.x + r.w - 30, TOP + 8, working, TOP);
      if (r.def.props) r.def.props(c, r, t, ctx);
      const chars = ECS.charsOf(world, r.id).sort((p, q) => p.seatIndex - q.seatIndex);
      const prim = ECS.primaryOf(world, r.id);
      const standing = [];
      chars.forEach((ch) => {
        const a = workerOf(ch);
        if (!a) return;
        const desk = (r.seats && r.seats[ch.seatIndex]) || r.desk;
        paint.chair(c, desk.seatX, desk.seatY, { color: D.shade });
        const sitting = a.seat === desk;
        if (sitting) P.drawActor(c, scene, a, 'base');
        paint.desk(c, desk.x, desk.seatY, { w: desk.w });
        // 显示器：桌子太窄时不画
        if (desk.w >= 30) {
          R(c, desk.x + desk.w - 11, desk.seatY - 9, 9, 6, PAL.ink);
          paint.screen(c, desk.x + desk.w - 10, desk.seatY - 8, 7, 4, deskMode(ch), t, { seed: desk.x });
        }
        if (ch === prim && ch.item) {
          c.globalAlpha = dimFor(ch.item.id);
          R(c, desk.x + 2, desk.seatY - 12, 1, 7, PAL.metal3);
          R(c, desk.x + 3, desk.seatY - 12, 5, 3, P.ITEM_COLORS[ch.item.color_index % P.ITEM_COLORS.length]);
          c.globalAlpha = 1;
        }
        if (sitting) {
          c.save(); c.beginPath(); c.rect(0, 0, W, desk.seatY); c.clip();
          P.drawActor(c, scene, a, 'front');
          c.restore();
        } else {
          standing.push(a);
        }
      });
      standing.sort((p, q) => p.y - q.y).forEach((a) => P.drawActor(c, scene, a));
      drawDoor(c, r);
    }

    function drawDoor(c, r) {
      const dx = r.door - 9;
      R(c, dx - 1, ROOM_B - 3, 20, 7, PAL.ink);
      R(c, dx, ROOM_B - 2, 18, 5, PAL.wood2);
      R(c, dx + 1, ROOM_B - 2, 16, 1, PAL.wood1);
      R(c, dx + 13, ROOM_B, 2, 2, PAL.yellow2);
    }

    function drawLibrary(c, t) {
      const r = lay.lib;
      P.sign(c, r.x + r.w / 2, TOP + 18, '成果库', { size: 7, bg: PAL.paper, stripe: PAL.green3 });
      const adopted = (model.shelves && model.shelves.adopted) || [];
      P.text(c, '已采纳', r.x + 20, TOP + 32, { size: 6, weight: 700, color: PAL.green3 });
      paint.shelf(c, r.x + 18, FLOOR_LINE - 24, r.w - 24);
      const per = Math.max(1, Math.floor((r.w - 26) / 18));
      // 自举试点起每只箱子带着采纳它的事件（shelves.boxes）
      const boxes = model.shelves && model.shelves.boxes ? model.shelves.boxes.slice(-per) : null;
      adopted.slice(-per).forEach((v, i, arr) => {
        const box = boxes ? boxes[i] : null;
        if (boxes && !(box && box.ref)) return;
        const bx = r.x + 20 + i * 18;
        P.drawBitmap(c, 'box_sealed', bx, FLOOR_LINE - 33);
        RB(c, bx + 1, FLOOR_LINE - 20, 13, 7, PAL.white);
        P.text(c, v, bx + 7.5, FLOOR_LINE - 16.2, { size: 6, weight: 800, align: 'center', color: PAL.green3, max: 13 });
        if (i === arr.length - 1 && sig('shelf')) paint.blinkFrame(c, bx - 1, FLOOR_LINE - 35, 15, 23);
        if (box) fact('box', { x: bx, y: FLOOR_LINE - 33, w: 15, h: 21 }, box.ref, { title: '成果库的箱子：采纳 ' + v });
      });
      if (!adopted.length) P.text(c, '尚未采纳', r.x + r.w / 2, FLOOR_LINE - 30, { size: 6, align: 'center', color: PAL.grey3 });
      drawDoor(c, r);
    }

    // 通往机房的门（3.2C）：门上列出本项目正在使用的机器与其上的动作数
    function drawMachineDoor(c, t) {
      if (!model.machines) return;
      const d = lay.door;
      const acts = model.machines.reduce((n, m) => n + m.actions, 0);
      const unknown = model.machines.some((m) => m.unknown);
      RB(c, d.x, d.y, d.w, d.h, '#3b3f4c');
      R(c, d.x + 2, d.y + 2, d.w - 4, d.h - 2, '#565c6c');
      R(c, d.x + d.w - 7, d.y + d.h / 2, 2, 3, PAL.yellow2);
      if (acts || sig('door')) {
        const k = scene.reduced ? 0.8 : 0.5 + 0.3 * Math.sin(t / 200);
        c.fillStyle = P.rgba(PAL.yellow1, k);
        c.fillRect(d.x + 2, d.y + d.h - 2, d.w - 4, 2);
        c.fillRect(d.x + d.w - 3, d.y + 4, 1, d.h - 6);
      }
      P.text(c, '机房', d.x + d.w / 2, d.y + 8, { size: 5.5, weight: 700, align: 'center', color: PAL.white });
      const lines = model.machines.map((m) => m.name.replace(/（.*）/, '') + ' · ' + m.actions + (m.online === false ? ' · 离线' : ''));
      if (lines.length) {
        const w = 74;
        const h = lines.length * 8 + 4;
        // 牌子挂在走廊里门的左边，不遮住上面的房间
        const px = d.x - w - 4, py = d.y + 2;
        RB(c, px, py, w, h, PAL.paper);
        lines.forEach((line, i) => P.text(c, line, px + 3, py + 6 + i * 8, { size: 5.5, weight: 600, color: PAL.ink, max: w - 6 }));
      }
      if (unknown) P.drawBitmap(c, 'question', d.x + 10, d.y + 14);
      st.remoteDots.forEach((dot) => {
        const k = Math.min(1, (scene.realT - dot.t0) / dot.ms);
        const x = dot.from[0] + (dot.to[0] - dot.from[0]) * k;
        const y = dot.from[1] + (dot.to[1] - dot.from[1]) * k;
        R(c, Math.round(x) - 1, Math.round(y) - 1, 3, 3, PAL.yellow2);
      });
    }

    // -------------------------------------------------------------------------
    // 覆盖层（设计说明第 5.6 节）

    function drawOverlay(c) {
      st.labels = [];
      if (!overlay.id || !overlay.data) return;
      // 来源的标记要等全部事实元素（包括信息条）画完再画，见 drawOverlayTop
      if (overlay.id === 'sources') {
        drawStamp(c, null);
        return;
      }
      c.fillStyle = 'rgba(12,14,30,0.35)';
      c.fillRect(0, BAR, W, H - BAR);
      const label = (x, y, text, bg) => P.sign(c, x, y, text, { size: 6, bg: bg || PAL.white, stripe: PAL.blue2, maxW: 150 });
      const data = overlay.data;
      if (overlay.id === 'flow') {
        (data.segments || []).forEach((s) => {
          const path = pathFor(s.from, s.to) || { pts: tubeFor(s.from, s.to) };
          if (!path || !path.pts) return;
          const [x, y] = ECS.pointAt(path.pts, ECS.polyLength(path.pts) / 2);
          label(x, y - 6, s.count + ' 次 · ' + Y11.time.clock(s.last_at), s.kind === 'rework' ? PAL.red1 : PAL.white);
        });
      } else if (overlay.id === 'waiting') {
        (data.entries || []).forEach((e) => {
          const r = roomById(e.department) || lay.hall;
          label(r.x + r.w / 2, (e.row || 0) * 14 + TOP + 44, e.text + ' · ' + Y11.time.duration(e.waited_sec), PAL.yellow1);
        });
      } else if (overlay.id === 'recovery') {
        (data.entries || []).forEach((e) => {
          const r = roomById(e.department);
          if (!r) return;
          label(r.x + r.w / 2, TOP + 44, e.text, e.state === 'pending_verification' ? PAL.yellow1 : PAL.white);
        });
      } else if (overlay.id === 'context_usage') {
        // 每个角色头顶显示自己的用量：标签落在这个角色的工位上方，相邻的角色错开一行
        (data.entries || []).forEach((e) => {
          const r = roomById(e.department);
          if (!r) return;
          const pct = Math.round(e.ratio * 100);
          const ch = ECS.charsOf(world, e.department).find((x) => x.id === e.role || x.roleKind === e.role);
          const seat = ch && ((r.seats && r.seats[ch.seatIndex]) || r.desk);
          const x = seat ? seat.seatX : r.x + r.w / 2;
          const row = ch ? ch.seatIndex % 2 : 0;
          label(x, DESK_Y - 44 - row * 11, ((ch && ch.name) || e.role || '') + ' ' + pct + '%', e.ratio >= 0.8 ? PAL.orange1 : PAL.green1);
        });
      } else if (overlay.id === 'semantic_records') {
        (data.entries || []).forEach((e) => {
          const r = roomById(e.department);
          if (!r) return;
          label(r.x + r.w / 2, TOP + 44, '有效 ' + e.valid + ' · 冲突 ' + e.conflicts, e.conflicts ? PAL.orange1 : PAL.white);
        });
      } else if (overlay.id === 'loops') {
        drawLoops(c, data);
      } else if (overlay.id === 'coverage') {
        drawCoverage(c, data);
      }
    }

    // -------------------------------------------------------------------------
    // 覆盖层「循环」（design.md 第 3 节）：取值只来自 run.loops 的结果

    function usedText(u) {
      const fmt = (v) => (u.unit === '秒' ? Y11.time.duration(v) : v + ' ' + u.unit);
      return u.limit === null || u.limit === undefined ? fmt(u.value) : fmt(u.value) + ' / ' + fmt(u.limit);
    }

    // 标签也是事实元素：判定过的写给出状态的事件，「不判定」写缺少的事实。
    // 状态由进展度量的某一轮给出时，来源是这一轮数值的来源（按事件加字段，例如检查结果是主机测量）
    function loopFact(inst, rect) {
      const title = inst.label + '：' + P.LOOP_STATES[inst.state].label;
      if (inst.state === 'not_judged') return fact('missing', rect, null, { title, missing: inst.missing, instanceId: inst.id });
      const notes = [inst.basis].concat(inst.stop_reason ? ['停止原因：' + inst.stop_reason] : []).filter(Boolean);
      const point = inst.measure && inst.measure.series.find((p) => p.position === inst.position);
      const ref = point ? { position: inst.position, field: inst.measure.field, source: point.source } : inst.position;
      return fact('loop', rect, ref, { title, notes, instanceId: inst.id });
    }

    function stateSign(c, x, bottom, text, state, maxW) {
      const s = P.LOOP_STATES[state];
      return P.sign(c, x, bottom, text, { size: 6, bg: s.color, fg: s.fg, stripe: PAL.ink, maxW });
    }

    function drawLoops(c, data) {
      const it = infoItem();
      const entry = it && (data.items || []).find((x) => x.work_item_id === it.id);
      if (entry) {
        // 部门房间的中央：这个 run 里本部门最近的一次激活
        lay.depts.forEach((r) => {
          const act = entry.instances.filter((x) => x.layer === 'activation' && x.department === r.id).pop();
          if (!act) return;
          const text = act.label + '\n' + usedText(act.used[0]) + (act.used[0].at_bound ? '（到上限）' : '') + '\n' + P.LOOP_STATES[act.state].label;
          loopFact(act, stateSign(c, r.x + r.w / 2, TOP + 62, text, act.state, r.w - 4));
          st.labels.push({ layer: 'activation', id: act.id, state: act.state, text });
        });
        // 正在工作的角色头顶：还没有结束的激活里的步骤循环
        const open = entry.instances.filter((x) => x.layer === 'activation' && !x.stop_reason).pop();
        const step = open && entry.instances.find((x) => x.layer === 'step' && x.parent === open.id);
        const ch = step && ((step.role && world.characters[step.role]) || ECS.primaryOf(world, step.department));
        const a = ch && workerOf(ch);
        if (step && a && a.visible) {
          const text = '步骤 ' + step.used[0].value + '/' + step.used[0].limit + ' · ' + P.LOOP_STATES[step.state].label;
          loopFact(step, stateSign(c, Math.round(a.x), Math.round(a.y) - 36, text, step.state, 120));
          st.labels.push({ layer: 'step', id: step.id, state: step.state, text });
        }
      }
      drawLegend(c, Object.keys(P.LOOP_STATES).map((k) => ({ color: P.LOOP_STATES[k].color, text: P.LOOP_STATES[k].label })));
    }

    // 信息条：紧接「第 N 轮」与时间进度条写 run 的收敛状态；run 已经停止时写停止原因
    function drawLoopsBar(c, data) {
      const it = infoItem();
      const entry = it && (data.items || []).find((x) => x.work_item_id === it.id);
      const run = entry && entry.instances.find((x) => x.layer === 'run');
      if (!run) return;
      const s = P.LOOP_STATES[run.state];
      const text = 'run：' + s.label + (run.stop_reason ? ' · ' + run.stop_reason : '');
      c.font = '700 6.5px ' + P.FONT;
      const w = Math.min(150, c.measureText(text).width + 8);
      R(c, st.barX, 4, w, 10, PAL.ink);
      R(c, st.barX + 1, 5, w - 2, 8, s.color);
      P.text(c, text, st.barX + w / 2, 9, { size: 6.5, weight: 700, align: 'center', color: s.fg, max: w - 4 });
      loopFact(run, { x: st.barX, y: 4, w, h: 10 });
      st.labels.push({ layer: 'run', id: run.id, state: run.state, text });
    }

    // 右上角的图例
    // 来源的一行：图标、画面上的描边样式、名称与个数
    function drawLegend(c, rows) {
      const sources = rows.some((row) => row.source);
      const rh = sources ? 14 : 9;
      const w = sources ? 106 : 92, h = rows.length * rh + 6;
      const x = W - w - 4, y = BAR + 4;
      RB(c, x, y, w, h, PAL.paper);
      rows.forEach((row, i) => {
        const cy = y + 3 + i * rh + rh / 2;
        let tx = x + 15;
        if (row.source) {
          P.drawSourceIcon(c, row.source, x + 5, cy - 5.5);
          R(c, x + 21, cy - 3, 11, 6, PAL.grey4);
          strokeSource(c, row.source, x + 20.5, cy - 3.5, 12, 7);
          tx = x + 37;
        } else {
          RB(c, x + 4, cy - 3.5, 7, 7, row.color);
        }
        P.text(c, row.text, tx, cy, { size: 6, weight: 600, color: PAL.ink, max: x + w - tx - 2 });
      });
    }

    // -------------------------------------------------------------------------
    // 覆盖层「检验」（design.md 第 6.1 节）：取值只来自 acceptance.coverage 的结果

    // 质检房间写哪一个事项：信息条上的事项有逐条结论时写它，否则写最近有逐条结论的事项
    function coverageSubject(data) {
      const items = data.items || [];
      const it = infoItem();
      const latest = (x) => Math.max.apply(null, x.criteria.map((cr) => cr.position));
      return (it && items.find((x) => x.work_item_id === it.id)) || items.slice().sort((a, b) => latest(b) - latest(a))[0] || null;
    }

    function drawCoverage(c, data) {
      const r = lay.verify;
      const subject = coverageSubject(data);
      if (r && subject) {
        const title = (itemById(subject.work_item_id) || { title: subject.work_item_id }).title;
        const text = title + '\n' + Y11.coverageText(subject);
        const rect = P.sign(c, r.x + r.w / 2, TOP + 60, text, { size: 6, bg: subject.open_count > 0 ? PAL.yellow1 : PAL.white, stripe: PAL.blue2, maxW: r.w + 40 });
        const pos = Math.max.apply(null, subject.criteria.map((cr) => cr.position));
        fact('coverage', rect, pos, { title: title + '：' + Y11.coverageText(subject), subject });
        st.labels.push({ kind: 'coverage', work_item_id: subject.work_item_id, covered: subject.covered, total: subject.total, model_read: subject.model_read, open_count: subject.open_count, text });
      }
      drawStamp(c, data);
    }

    // 质检房间里放行的盖章（本项目最近一次放行，project.loop 的 stamp），覆盖层「检验」打开时旁边写这次放行的覆盖比例
    function drawStamp(c, data) {
      const r = lay.verify;
      const stamp = model.stamp;
      if (!r || !stamp || !stamp.ref) return;
      // 盖章贴在墙的下半截，房间中央的标签下面
      const sx = r.x + 22, sy = TUBE_Y + 18;
      RB(c, sx - 15, sy - 9, 30, 18, PAL.paper);
      P.stampMark(c, sx, sy, '放行', PAL.green3, { size: 7 });
      fact('stamp', { x: sx - 15, y: sy - 9, w: 30, h: 18 }, stamp.ref, { title: '质检的盖章：「' + ((itemById(stamp.work_item_id) || {}).title || stamp.work_item_id) + '」放行' });
      const cov = data && (data.items || []).find((x) => x.release && x.release.position === stamp.ref.position);
      if (cov) {
        // 写在盖章下方：第一行覆盖比例，第二行开环（放不下一行）
        const full = '放行时 ' + Y11.coverageText(cov.release.ratio);
        const text = full.replace(' · ', '\n');
        const rect = P.sign(c, r.x + r.w / 2, FLOOR_LINE + 8, text, { size: 6, bg: PAL.white, stripe: PAL.green3, maxW: r.w - 4 });
        fact('release', rect, cov.release.position, { title: full });
        st.labels.push({ kind: 'release', work_item_id: cov.work_item_id, covered: cov.release.ratio.covered, total: cov.release.ratio.total, text });
      }
    }

    // -------------------------------------------------------------------------
    // 画在信息条之后的覆盖层内容：信息条上的循环状态、来源的着色与图例

    function drawOverlayTop(c) {
      if (!overlay.id || !overlay.data) return;
      if (overlay.id === 'loops') drawLoopsBar(c, overlay.data);
      if (overlay.id === 'sources') drawSourceMarks(c);
    }

    // 覆盖层「来源」（design.md 第 5.2 节）：画面其余部分调暗，事实元素按自己的来源描边（确定规则灰、主机测量蓝、用户绿，
    // 角色陈述与决策模型用加粗的虚线）；右上角的图例写每种来源在画面上有几个元素
    let dimMask = null;
    function strokeSource(c, source, x, y, w, h) {
      const s = P.SOURCE_STYLE[source];
      c.save();
      c.strokeStyle = s.line;
      c.lineWidth = s.dash ? 2 : 1;
      c.setLineDash(s.dash ? [3, 2] : []);
      c.strokeRect(x, y, w, h);
      c.restore();
    }

    function drawSourceMarks(c) {
      const facts = st.facts.filter((f) => f.source);
      // 在一张遮罩上挖掉事实元素所在的位置，再盖到画面上
      if (!dimMask) dimMask = P.makeCanvas(W, H);
      const m = dimMask.getContext('2d');
      m.clearRect(0, 0, W, H);
      m.fillStyle = 'rgba(12,14,30,0.6)';
      m.fillRect(0, BAR, W, H - BAR);
      facts.forEach((f) => m.clearRect(f.rect.x - 1, f.rect.y - 1, f.rect.w + 2, f.rect.h + 2));
      c.drawImage(dimMask, 0, 0);
      facts.forEach((f) => strokeSource(c, f.source, f.rect.x - 1.5, f.rect.y - 1.5, f.rect.w + 3, f.rect.h + 3));
      const counts = {};
      facts.forEach((f) => { counts[f.source] = (counts[f.source] || 0) + 1; });
      drawLegend(c, Object.keys(Y11.registry.SOURCE_KINDS).map((k) => ({ source: k, text: Y11.registry.SOURCE_KINDS[k].label + ' ' + (counts[k] || 0) })));
      st.labels.push({ kind: 'sources', counts });
    }

    // -------------------------------------------------------------------------

    // 头顶对话框：说话气泡是正在做的任务，思考气泡是队列里的下一项；内容只来自任务自己的字段。
    // 任务做完以后这句话再留一会儿，够读完；减少动画时小人不走动，气泡照样显示
    function drawBubbles(c) {
      const list = [];
      Object.values(world.characters).forEach((ch) => {
        const a = workerOf(ch);
        const b = ch.bubble;
        let s = st.said[ch.id];
        if (b && (!s || s.text !== b.text || s.kind !== b.kind)) s = st.said[ch.id] = { text: b.text, kind: b.kind, until: scene.realT + P.sayMs(b.text) };
        if (!a || !a.visible || !s || (!b && s.until <= scene.realT)) return;
        list.push({ a, text: s.text, kind: s.kind, tail: Boolean(b && b.tail), until: b ? 0 : s.until });
      });
      P.drawSpeeches(c, scene, list, { W, size: 6, maxW: 84 });
    }

    function draw(sc, c) {
      const t = sc.animT;
      st.facts = [];
      c.drawImage(buildBackground(), 0, 0);
      drawHall(c, t);
      lay.depts.forEach((r) => drawDeptRoom(c, r, t));
      drawLibrary(c, t);
      drawPipes(c, t);
      drawPackages(c);
      drawMachineDoor(c, t);
      sc.drawFlyers(c);
      sc.drawParticles(c);

      // 灯光：未工作的房间调暗、闪光、待核实黄灯、等待模型服务调暗、整层中断变暗
      lay.depts.forEach((r) => {
        const d = r.id;
        const here = itemsIn(d);
        const lit = here.some((it) => ACTIVE.includes(it.status) || it.status === 'done') || Boolean(r.def.lit && r.def.lit(ctx));
        if (!lit) { c.fillStyle = 'rgba(14,12,34,0.32)'; c.fillRect(r.x, TOP, r.w, ROOM_B - TOP); }
        if (waitingDept(d)) { c.fillStyle = 'rgba(40,44,60,0.25)'; c.fillRect(r.x, TOP, r.w, ROOM_B - TOP); }
        if (here.some((it) => it.status === 'pending_verification')) {
          const k = sc.reduced ? 0.14 : 0.1 + 0.08 * Math.sin(t / 240);
          c.fillStyle = 'rgba(255,196,40,' + k.toFixed(3) + ')';
          c.fillRect(r.x, TOP, r.w, ROOM_B - TOP);
          paint.beacon(c, r.x + r.w - 14, TOP + 4, { on: true }, t);
        }
        const fl = st.flash[d];
        if (fl && fl.until > sc.realT) {
          c.fillStyle = P.rgba(fl.color, Math.min(0.35, ((fl.until - sc.realT) / 900) * 0.35));
          c.fillRect(r.x, TOP, r.w, ROOM_B - TOP);
        }
        if (r.def.tint) r.def.tint(c, r, t, ctx);
      });
      if (model.interrupted) { c.fillStyle = 'rgba(8,8,24,0.55)'; c.fillRect(0, BAR, W, H - BAR); }

      // 房间名、门口的小旗与门牌
      lay.depts.forEach((r) => {
        const D = P.DEPTS[r.id];
        P.sign(c, r.x + r.w / 2, TOP + 4, D.name, { size: 7, bg: D.main, fg: PAL.white, hi: D.light, lo: D.shade, minW: 30 });
        const here = itemsIn(r.id);
        here.forEach((it, i) => {
          if (noSource(it.refs, 'parcel')) return;
          c.globalAlpha = dimFor(it.id);
          const fx = r.door - 22 - i * 9;
          P.drawBitmap(c, (Math.floor(t / 320) + i) % 2 && !sc.reduced ? 'flag2' : 'flag', fx, ROOM_B + 4, { recolor: { X: P.ITEM_COLORS[it.color_index % 6], x: P.ITEM_SHADES[it.color_index % 6] } });
          c.globalAlpha = 1;
          if (it.refs) {
            const b = P.bitmap('flag');
            fact('parcel', { x: fx, y: ROOM_B + 4, w: b.w, h: b.h }, it.refs.parcel, { title: '停放在' + r.label + '门口的包裹：' + it.title, itemId: it.id });
          }
        });
        let row = 0;
        here.forEach((it) => {
          if (!it.sign || noSource(it.refs, 'sign')) return;
          const ss = P.signStyle(it.sign);
          const maxW = r.w - 6;
          const w = Math.min(maxW, Math.max(18, P.measure(c, it.sign, 6, 600) + 8));
          c.globalAlpha = dimFor(it.id);
          const rect = P.sign(c, r.door + 12 + w / 2 - 20, ROOM_B + 18 + row * 12, it.sign, { size: 6, bg: ss.bg, fg: ss.fg, stripe: ss.stripe, maxW, nail: row === 0 ? ROOM_B + 3 : undefined });
          c.globalAlpha = 1;
          if (it.refs) fact('sign', rect, it.refs.sign, { title: '门口的牌子：' + it.sign, itemId: it.id });
          row += 1;
        });
      });
      sc.actors.forEach((a) => { if (a.icon) { c.globalAlpha = a.dim; P.drawIcon(c, sc, a); c.globalAlpha = 1; } });
      drawBubbles(c);

      // 减少动画时的交接箭头
      st.arrows.forEach((ar) => {
        c.globalAlpha = dimFor(ar.itemId);
        P.arrow(c, ar.pts, ar.color, { dash: ar.dash });
        const mid = ECS.pointAt(ar.pts, ECS.polyLength(ar.pts) / 2);
        const b = P.bitmap(ar.bmp);
        P.drawBitmap(c, ar.bmp, mid[0] - b.w / 2, mid[1] - b.h - 3);
        c.globalAlpha = 1;
      });

      drawOverlay(c);
      drawInfoBar(c);
      drawOverlayTop(c);
      card.draw(c);
      sourceCard.draw(c);
      // 场景要求点开某一种事实元素（scene.fact）：等这种元素画出来再打开
      if (st.wantFact) {
        const f = st.facts.find((x) => x.kind === st.wantFact);
        if (f) { st.wantFact = null; openFact(f); }
      }
    }

    // 信息条上写的事项：聚焦的事项，否则是正在进行的事项
    function infoItem() {
      return (focusId && itemById(focusId)) || model.items.find((x) => ACTIVE.includes(x.status) || x.status === 'waiting_provider') || model.items.find((x) => IN_ROOM.includes(x.status)) || null;
    }

    function drawInfoBar(c) {
      R(c, 0, 0, W, BAR, '#1f2230');
      R(c, 0, BAR - 1, W, 1, '#3a3f52');
      const it = infoItem();
      if (!it) { P.text(c, '没有进行中的事项', 8, 9, { size: 7, color: PAL.grey1 }); return; }
      R(c, 6, 5, 8, 8, PAL.ink); R(c, 7, 6, 6, 6, P.ITEM_COLORS[it.color_index % 6]);
      let x = 18;
      x += P.text(c, it.title || it.id, x, 9, { size: 7, weight: 700, color: PAL.white, max: 170 }) + 8;
      const chip = (text, bg, fg) => {
        c.font = '700 6.5px ' + P.FONT;
        const w = c.measureText(text).width + 8;
        R(c, x, 4, w, 10, bg);
        P.text(c, text, x + w / 2, 9, { size: 6.5, weight: 700, align: 'center', color: fg || PAL.ink });
        const rect = { x, y: 4, w, h: 10 };
        x += w + 4;
        return rect;
      };
      if (it.cycle) {
        const rect = chip('第 ' + it.cycle + ' 轮', PAL.paper);
        if (it.refs) fact('round', rect, it.refs.round, { title: '信息条：' + it.title + ' 第 ' + it.cycle + ' 轮', itemId: it.id });
      }
      if (it.department && P.DEPTS[it.department]) {
        const rect = chip('当前部门：' + P.DEPTS[it.department].name, P.DEPTS[it.department].light);
        if (it.refs) fact('department', rect, it.refs.department, { title: '信息条：当前部门 ' + P.DEPTS[it.department].name, itemId: it.id });
      }
      const statusRect = chip(STATUS_TEXT[it.status] || it.status, STATUS_CHIP[it.status] || PAL.grey2, ['running', 'failed', 'adopted', 'asking'].includes(it.status) ? PAL.white : PAL.ink);
      if (it.refs) fact('status', statusRect, it.refs.sign, { title: '信息条：' + (STATUS_TEXT[it.status] || it.status), itemId: it.id });
      st.barX = x;
      if (it.limit_sec) {
        const k = Math.min(1, (it.elapsed_sec || 0) / it.limit_sec);
        const wk = Math.min(1 - k, (it.waiting_provider_sec || 0) / it.limit_sec);
        const bw = 110, bx = W - bw - 8;
        const col = k >= 0.95 ? PAL.red2 : k >= 0.8 ? PAL.orange2 : PAL.green2;
        const timeText = '已用 ' + Math.round((it.elapsed_sec || 0) / 60) + ' 分 / 上限 ' + Math.round(it.limit_sec / 60) + ' 分' + (it.waiting_provider_sec ? ' · 等待 ' + Math.round(it.waiting_provider_sec / 60) + ' 分不计入' : '');
        const tw = P.text(c, timeText, bx - 6, 9, { size: 6.5, weight: 600, align: 'right', color: k >= 0.8 ? PAL.orange1 : PAL.grey1 });
        if (it.refs) fact('time', { x: bx - 6 - tw, y: 4, w: tw + 6 + bw, h: 10 }, it.refs.time, { title: '信息条：' + timeText, itemId: it.id });
        R(c, bx, 5, bw, 8, PAL.ink); R(c, bx + 1, 6, bw - 2, 6, '#383d50');
        const ew = Math.round((bw - 2) * k);
        R(c, bx + 1, 6, ew, 6, col);
        if (wk > 0) {
          const ww = Math.max(2, Math.round((bw - 2) * wk));
          R(c, bx + 1 + ew, 6, ww, 6, PAL.grey3);
          c.fillStyle = PAL.grey1;
          for (let i = 0; i < ww; i += 3) c.fillRect(bx + 1 + ew + i, 6 + (i % 6 < 3 ? 0 : 3), 1, 3);
        }
      }
    }

    // -------------------------------------------------------------------------
    // 点击：打开着的决定卡片先处理，其次是大厅的决定板，再其次是通往机房的门

    const worldXY = (ev) => {
      const rect = canvas.getBoundingClientRect();
      return [((ev.clientX - rect.left) / rect.width) * W, ((ev.clientY - rect.top) / rect.height) * H];
    };
    const overDoor = (x, y) => {
      const d = lay.door;
      return Boolean(model.machines) && x >= d.x - 80 && x <= d.x + d.w && y >= d.y && y <= d.y + d.h;
    };

    // 事实元素：后画的在上面
    function factAt(x, y) {
      for (let i = st.facts.length - 1; i >= 0; i--) {
        const r = st.facts[i].rect;
        if (x >= r.x - 1 && x <= r.x + r.w + 1 && y >= r.y - 1 && y <= r.y + r.h + 1) return st.facts[i];
      }
      return null;
    }

    // 点开事实元素：覆盖层「检验」的标签打开逐条清单，其余打开来源卡片
    function openFact(f) {
      if (f.kind !== 'coverage') { sourceCard.open(f); return; }
      const methods = Y11.registry.CHECK_METHODS;
      const rows = f.subject.criteria.map((cr) => ({
        label: cr.id + ' ' + cr.text, method: methods[cr.method].label, result: cr.result, resultText: RESULT_TEXT[cr.result], open: cr.open,
        fact: {
          kind: 'criterion', rect: f.rect, position: cr.position, field: cr.field, source: cr.source, title: cr.id + ' ' + cr.text,
          notes: ['检验方式：' + methods[cr.method].label + ' · 最近一次结果：' + RESULT_TEXT[cr.result]].concat(cr.open ? ['开环：没有可执行的检验'] : [])
        }
      }));
      sourceCard.openList(f.title + ' · 逐条清单', rows, f.rect);
    }

    // 点击的顺序：打开着的决定卡片与来源卡片、决定板、通往机房的门、事实元素
    canvas.addEventListener('click', (ev) => {
      const [x, y] = worldXY(ev);
      if (card.click(x, y)) return;
      if (sourceCard.click(x, y)) return;
      if (overBoard(x, y)) { card.open(); return; }
      if (overDoor(x, y) && o.onDoorClick) { o.onDoorClick(model.machines.map((m) => m.id)); return; }
      const f = factAt(x, y);
      if (f) openFact(f);
    });
    canvas.addEventListener('mousemove', (ev) => {
      const [x, y] = worldXY(ev);
      const free = !card.isOpen() && !sourceCard.isOpen();
      canvas.style.cursor = card.cursor(x, y) || sourceCard.cursor(x, y) || (free && (overBoard(x, y) || (overDoor(x, y) && o.onDoorClick) || factAt(x, y)) ? 'pointer' : 'default');
    });

    // -------------------------------------------------------------------------
    // 接口

    function setModel(m) {
      if (!m || !Array.isArray(m.items)) throw new Error('setModel 需要 floorModel');
      model = Object.assign({ open_requests: [], shelves: { adopted: [] }, slots: null, waiting_provider: [], machines: null, ops: null, interrupted: false, roles: null, decisions: [] }, m);
      const next = flagsOf(model);
      if (JSON.stringify(next) !== JSON.stringify(flags)) {
        // 快照里的运维数据出现或消失：房间与管道按新的条件重新声明，角色、包裹、信号与管道的流动状态原样带过去
        flags = next;
        const old = world;
        world = declareWorld(flags);
        world.characters = old.characters;
        world.packages = old.packages;
        world.signals = old.signals;
        Object.keys(world.links).forEach((k) => { if (old.links[k]) world.links[k].flow = old.links[k].flow; });
        lay = layOf(world);
        bg = null;
      }
      if (m.focus_id !== undefined && focusId === null) focusId = m.focus_id;
      card.setDecisions(model.decisions || []);
      syncWorkers();
      scene.frozen = Boolean(model.interrupted);
    }

    syncWorkers();

    return {
      scene,
      // 验收脚本读取世界的当前状态、决定卡片与来源卡片、这一帧的事实元素与覆盖层上写出的标签
      inspect: () => ({ world, model, card, sourceCard, facts: st.facts.slice(), overlay: { id: overlay.id, data: overlay.data, labels: st.labels.slice() } }),
      setModel,
      playEvent,
      focus(id) { focusId = id || null; },
      setOverlay(id, data) {
        if (id !== overlay.id) sourceCard.close();
        overlay = { id: id || null, data: data || null };
      },
      // 点开某一种事实元素（场景的一步）：下一帧画出来以后打开
      openFact(kind) { st.wantFact = kind; },
      resize: () => scene.resize(),
      destroy: () => { card.destroy(); sourceCard.destroy(); scene.destroy(); }
    };
  };
})();
