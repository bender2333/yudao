// 实体—组件—系统（v9 构建约定第 3 节）：房间与管道的图结构声明、任务派发、角色与包裹的推进、头顶对话框。
// 只依赖 engine.js 已有的画布与动画原语，不新增画布画法；floor.js、room.js、building.js 在这之上重写。
(function () {
  'use strict';
  const Y8 = window.Y8;
  const P = Y8.pixel;
  if (!P || !P.createScene) throw new Error('ecs.js 需要先加载 js/pixel/engine.js');

  const ECS = {};
  P.ecs = ECS;

  // ---------------------------------------------------------------------------
  // 第 3.1 节：世界

  ECS.world = function world() {
    return { rooms: {}, roomOrder: {}, links: {}, characters: {}, packages: {} };
  };

  // ---------------------------------------------------------------------------
  // 第 3.2 节：房间与管道的声明
  //
  // 沿用 v8 floor.js 的几个常量（像素级一致，不是重新设计画面）：
  const GEO = {
    TOP: 50, ROOM_B: 214, FLOOR_LINE: 150, DESK_Y: 196, PORT_STAND: 176,
    PIPE_Y: 138, TUBE_Y: 104, DUCT_Y: 30, DUCT_TUBE_Y: 42, UNDER_Y: 276, GAP: 6
  };
  ECS.GEO = GEO;

  // defs: [{ id, label, roomKind: 'hall'|'dept'|'shelf', w, optional }]
  // hasOps 为假时跳过 optional 的房间；宽度沿用 v8：hall 100，部门房间 110，成果库 hasOps 时 82 否则 136，运维 88
  ECS.declareRooms = function declareRooms(world, defs, opts) {
    const o = opts || {};
    world.rooms = {};
    world.roomOrder = [];
    let x = 4;
    defs.forEach((d) => {
      if (d.optional && !o.hasOps) return;
      const w = d.w != null ? d.w : (d.roomKind === 'shelf' ? (o.hasOps ? 82 : 136) : d.roomKind === 'hall' ? 100 : d.roomKind === 'dept' && d.id === 'operations' ? 88 : 110);
      const r = {
        kind: 'room', id: d.id, label: d.label, roomKind: d.roomKind, x, y: GEO.TOP, w,
        door: x + Math.round(w / 2),
        inPort: x + 12,
        outPort: x + w - 12,
        // 管道在房间外墙上的起点：大厅沿用 v8 floor.js 的 hall.x + 22（信箱那一侧），其余房间就是 outPort
        pipeOut: d.roomKind === 'hall' ? x + 22 : x + w - 12,
        desk: { x: x + Math.round(w / 2) - 17, w: 34, seatX: x + Math.round(w / 2) - 5, seatY: GEO.DESK_Y },
        cabinet: { x: x + 8, y: GEO.FLOOR_LINE + 6 },
        terminal: { x: x + w - 16, y: GEO.PORT_STAND }
      };
      world.rooms[d.id] = r;
      world.roomOrder.push(d.id);
      x += w + GEO.GAP;
    });
    // 通往机房的门：走廊尽头，位置固定（跟 v8 一样不随房间数量变化）
    world.machineDoor = { x: 606, y: 218, w: 28, h: 40 };
    return world;
  };

  function roomIndex(world, id) { return world.roomOrder.indexOf(id); }
  function adjacent(world, a, b) { return Math.abs(roomIndex(world, a) - roomIndex(world, b)) === 1; }

  // 管道端点：房间，或者走廊尽头通往机房的门（它不是房间，位置固定）
  function endpoint(world, id) {
    return world.rooms[id] || (id === 'machine_room' ? world.machineDoor : null);
  }
  ECS.endpoint = endpoint;

  // links: [{ from, to, kind: 'handoff'|'tube'|'return', via: 'ceiling'|'under', optional }]
  ECS.declareLinks = function declareLinks(world, defs) {
    world.links = {};
    defs.forEach((d) => {
      const a = endpoint(world, d.from);
      const b = endpoint(world, d.to);
      if (d.optional && (!a || !b)) return;
      if (!a || !b) return;
      const key = d.from + (d.kind === 'tube' ? '~' : '>') + d.to;
      world.links[key] = { kind: 'pipe', id: key, from: d.from, to: d.to, linkKind: d.kind, pts: routeLink(world, d, a, b) };
    });
    return world;
  };

  function routeLink(world, d, a, b) {
    const isMachine = d.to === 'machine_room';
    if (d.kind === 'handoff' && !isMachine) {
      const ax = a.pipeOut !== undefined ? a.pipeOut : a.outPort;
      return [[ax, GEO.PIPE_Y], [b.inPort, GEO.PIPE_Y]];
    }
    if (d.kind === 'handoff' && isMachine) {
      return [[a.outPort, GEO.PIPE_Y], [a.outPort, GEO.ROOM_B + 10], [b.x + 14, GEO.ROOM_B + 10], [b.x + 14, b.y + 12]];
    }
    if (d.kind === 'tube') {
      if (adjacent(world, d.from, d.to)) return [[a.outPort, GEO.TUBE_Y], [b.inPort, GEO.TUBE_Y]];
      // 跨过一个房间的传信管，走天花板的长传信管
      return [[a.x + 22, GEO.TUBE_Y - 12], [a.x + 22, GEO.DUCT_TUBE_Y], [b.x + b.w - 22, GEO.DUCT_TUBE_Y], [b.x + b.w - 22, GEO.TUBE_Y - 12]];
    }
    if (d.kind === 'return') {
      // via 由声明指定，不猜测：'under' 走地板下（运维回大厅这类隔得远的），省略时走天花板（质检回产品这类）
      if (d.via === 'under') {
        return [[a.x + 20, GEO.ROOM_B - 4], [a.x + 20, GEO.UNDER_Y], [b.x + 12, GEO.UNDER_Y], [b.x + 12, GEO.ROOM_B + 26]];
      }
      return [[a.outPort - 8, GEO.PIPE_Y - 8], [a.outPort - 8, GEO.DUCT_Y], [b.inPort + 8, GEO.DUCT_Y], [b.inPort + 8, GEO.PIPE_Y - 8]];
    }
    throw new Error('未知的管道种类：' + d.kind);
  }

  ECS.roomOf = function roomOf(world, id) {
    if (id === 'adopted' || id === 'adoption') return world.rooms.library;
    return world.rooms[id] || null;
  };

  // 两个房间之间已声明的管道（反向也可以，返回 reversed 标记）
  ECS.linkBetween = function linkBetween(world, from, to, kind) {
    const sep = kind === 'tube' ? '~' : '>';
    const direct = world.links[from + sep + to];
    if (direct) return { pts: direct.pts, key: direct.id, reversed: false, link: direct };
    const back = world.links[to + sep + from];
    if (back) return { pts: back.pts.slice().reverse(), key: back.id, reversed: true, link: back };
    return null;
  };

  // ---------------------------------------------------------------------------
  // 几何：折线长度与沿线取点（跟 v8 floor.js 的 polyLength/pointAt 相同算法）

  ECS.polyLength = function polyLength(pts) {
    let len = 0;
    for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    return len;
  };

  ECS.pointAt = function pointAt(pts, d) {
    let left = d;
    for (let i = 1; i < pts.length; i++) {
      const seg = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
      if (left <= seg || i === pts.length - 1) {
        const k = seg ? Math.min(1, left / seg) : 1;
        return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * k, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * k];
      }
      left -= seg;
    }
    return pts[pts.length - 1];
  };

  // ---------------------------------------------------------------------------
  // 第 3.3 节：任务目录
  //
  // 每一项：{ label, spot, pose, bubble, ms, icon }
  // spot：'desk'｜'cabinet'｜'terminal'｜'port_in'｜'port_out'｜'inspect'｜'stand'｜null（原地）
  // pose 必须是 engine.js 已注册的动作名（P.ANIMS 的键）
  // bubble：'say' 头顶说话气泡，内容为 label（或者事件的 payload.text，逐字追加）｜'think' 不显示，只供下一项被预告时显示思考气泡｜null 不显示
  // 覆盖 v8 design.md 第 8.3 节里所有"小人动作"的行；纯房间/管道变化（灯、牌子、队列、槽位灯）不在这里，由 floor.js 直接改画面状态。
  ECS.TASKS = {
    department_activated: { label: '开始工作', spot: 'desk', pose: 'idle', bubble: null, ms: 400 },
    context_assembled: { label: '整理资料', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 900 },
    model_requested: { label: '打字', spot: 'desk', pose: 'type', bubble: 'say', ms: 1400, hold: 'model' },
    model_stream_progress: { label: '', spot: 'desk', pose: 'type', bubble: 'say', ms: 1, streaming: true },
    model_attempt_finished: { label: '有想法了', spot: 'desk', pose: 'sit_happy', bubble: null, ms: 600, icon: 'bulb' },
    model_retry_scheduled: { label: '等待重试', spot: 'desk', pose: 'sit_wait', bubble: 'say', ms: 1400, icon: 'hourglass' },
    model_attempt_failed: { label: '失败了', spot: 'desk', pose: 'slump', bubble: null, ms: 900, icon: 'cross' },
    tool_started_search: { label: '翻找资料', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 1200 },
    tool_started_read: { label: '阅读文件', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 1100 },
    tool_started_write: { label: '编辑', spot: 'desk', pose: 'type', bubble: 'say', ms: 1200 },
    tool_started_run_command: { label: '执行登记命令', spot: 'terminal', pose: 'lever', bubble: 'say', ms: 1600 },
    tool_started_fetch: { label: '网络取回', spot: 'port_in', pose: 'side_place', bubble: 'say', ms: 1200 },
    tool_started_mcp: { label: '调用工具', spot: 'terminal', pose: 'lever', bubble: 'say', ms: 1200 },
    tool_started_browser: { label: '试用网页', spot: 'desk', pose: 'type', bubble: 'say', ms: 1400 },
    tool_started_test: { label: '自测网页', spot: 'desk', pose: 'type', bubble: 'say', ms: 1400 },
    tool_started_scan: { label: '阅读旧档案', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 1200 },
    tool_skipped: { label: '', spot: 'desk', pose: 'sit_scratch', bubble: null, ms: 700, icon: 'cross' },
    proposal_submitted: { label: '提交提案', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 900 },
    proposal_rejected: { label: '提案被退回', spot: 'desk', pose: 'sit_scratch', bubble: null, ms: 900, icon: 'question' },
    spec_accepted: { label: '盖上有效章', spot: 'desk', pose: 'sit_happy', bubble: 'say', ms: 800, icon: 'check' },
    contract_accepted: { label: '盖上有效章', spot: 'desk', pose: 'sit_happy', bubble: 'say', ms: 800, icon: 'check' },
    plan_accepted: { label: '贴上白板', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 800, icon: 'check' },
    delivery_accepted: { label: '装箱封存', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 900, icon: 'check' },
    qa_started: { label: '放大镜检查', spot: 'inspect', pose: 'magnify', bubble: 'say', ms: 1200 },
    qa_submitted_release: { label: '放行', spot: 'inspect', pose: 'stamp_once', bubble: 'say', ms: 1100, icon: 'check' },
    qa_submitted_rework: { label: '打回返工', spot: 'inspect', pose: 'stamp_once', bubble: 'say', ms: 1100, icon: 'exclaim' },
    collaboration_requested: { label: '发出询问', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 900 },
    collaboration_responded: { label: '回答询问', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 900 },
    department_guidance_received: { label: '门缝塞进纸条', spot: 'port_in', pose: 'crouch', bubble: null, ms: 700, icon: 'exclaim' },
    department_guidance_applied: { label: '阅读指导', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 900 },
    department_guidance_responded: { label: '写回复', spot: 'desk', pose: 'type', bubble: 'say', ms: 900 },
    compaction_recorded: { label: '整理摘要', spot: 'cabinet', pose: 'sit_up', bubble: 'say', ms: 900 },
    compaction_failed: { label: '重新整理', spot: 'desk', pose: 'sit_scratch', bubble: 'say', ms: 900, icon: 'cross' },
    run_paused: { label: '事项暂停', spot: 'desk', pose: 'sit_relax', bubble: null, ms: 1200, icon: 'zzz' },
    run_failed: { label: '事项失败', spot: 'desk', pose: 'slump', bubble: null, ms: 1200, icon: 'cross' },
    run_done: { label: '举手欢呼', spot: 'desk', pose: 'cheer', bubble: null, ms: 1200 },
    x_run_stopped_for_upgrade: { label: '收拾桌面', spot: 'stand', pose: 'tidy', bubble: null, ms: 1200 },
    x_run_auto_resumed: { label: '伸懒腰', spot: 'desk', pose: 'stretch_sit', bubble: null, ms: 800 },
    x_action_unknown: { label: '待核实', spot: 'terminal', pose: 'wait', bubble: null, ms: 1600, icon: 'question' },
    x_decision_answered: { label: '按决定处理', spot: 'terminal', pose: 'lever', bubble: 'say', ms: 1000 },
    project_decision_answered: { label: '按决定处理', spot: 'terminal', pose: 'lever', bubble: 'say', ms: 1000 },
    x_remote_action_started: { label: '远程执行', spot: 'terminal', pose: 'lever', bubble: 'say', ms: 1400 },
    x_machine_offline: { label: '盯着终端', spot: 'terminal', pose: 'wait', bubble: null, ms: 1600, icon: 'question' },
    x_deployed: { label: '推车送到门口', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 1000 },
    x_rolled_back: { label: '取回旧版本', spot: 'port_out', pose: 'crouch', bubble: 'say', ms: 1000 },
    x_fault_recorded: { label: '跑向监控屏', spot: 'terminal', pose: 'watch_r', bubble: 'say', ms: 1000 },
    x_provider_wait_entered: { label: '等待模型服务', spot: 'desk', pose: 'sit_wait', bubble: null, ms: 1600, icon: 'hourglass', hold: 'provider' },
    x_provider_wait_left: { label: '模型服务恢复', spot: 'desk', pose: 'sit_up', bubble: 'say', ms: 700 },
    x_auto_repair_stopped: { label: '停止自动修复', spot: 'desk', pose: 'sit_wait', bubble: null, ms: 1200, icon: 'cross' },
    x_decision_issued: { label: '待你决定', spot: 'desk', pose: 'sit_wait', bubble: null, ms: 1600, icon: 'text', hold: 'decision' },
    project_decision_requested: { label: '待你决定', spot: 'desk', pose: 'sit_wait', bubble: null, ms: 1600, icon: 'text', hold: 'decision' },
    package_handoff_out: { label: '放进管道口', spot: 'port_out', pose: 'side_place', bubble: null, ms: 520, facing: 1 },
    package_handoff_in: { label: '从管道口取出', spot: 'port_in', pose: 'crouch', bubble: null, ms: 520, facing: -1 },
    package_return_out: { label: '放进回流口', spot: 'port_in', pose: 'side_place', bubble: null, ms: 520, facing: -1 },
    package_return_in: { label: '从回流口取出', spot: 'port_out', pose: 'crouch', bubble: null, ms: 520, facing: 1 }
  };

  // 事件类型到任务键的解析：大多数事件类型本身就是任务键；少数按 payload 再分支
  function taskKeyFor(ev) {
    const pl = ev.payload || {};
    if (ev.type === 'qa_submitted') return pl.verdict === 'release' ? 'qa_submitted_release' : 'qa_submitted_rework';
    if (ev.type === 'tool_started') {
      const tool = String(pl.tool || '');
      if (tool === 'search') return 'tool_started_search';
      if (tool === 'run_command') return 'tool_started_run_command';
      if (/write|edit/.test(tool)) return 'tool_started_write';
      if (/fetch|http|net|url/.test(tool)) return 'tool_started_fetch';
      if (/mcp/.test(tool)) return 'tool_started_mcp';
      if (/browser|computer/.test(tool)) return ev.department === 'quality' ? 'tool_started_browser' : 'tool_started_test';
      if (/scan|legacy|repo/.test(tool)) return 'tool_started_scan';
      return 'tool_started_read';
    }
    if (ev.type === 'model_request_serialized') return 'model_requested';
    return ev.type;
  }
  ECS.taskKeyFor = taskKeyFor;

  // ---------------------------------------------------------------------------
  // 第 3.4 节：系统

  // 事件到达：命中任务目录则入队（角色动作走队列）；带 hold 的任务停在角色身上，等同部门的下一个事件把它清掉
  // （第 3.4 节的"收到完成事件"）；没有任务的事件原样交回调用方按信号处理（房间/管道级旗标由 floor.js 自己改画面）
  ECS.dispatch = function dispatch(world, ev) {
    if (!ev || !ev.type) throw new Error('dispatch 需要事件对象');
    const pl = ev.payload || {};
    if (!ev.department) return false;
    const key = taskKeyFor(ev);
    const def = ECS.TASKS[key];
    if (!def) return false;
    const ch = world.characters[ev.department];
    if (!ch) return false;
    if (def.streaming) {
      if (ch.current && (ch.current.streaming || ch.current.taskKey === 'model_requested')) {
        ch.current.streaming = true;
        ch.current.label = ((ch.current.label || '') + (pl.text || '')).slice(0, 120);
        return true;
      }
      return false;
    }
    // 上一个事件留下的"持续状态"（hold）由这个事件收尾
    if (ch.current && ch.current.hold && ch.current.taskKey !== key) ch.current = null;
    const task = Object.assign({ taskKey: key }, def, { label: def.label, workItemId: ev.work_item_id });
    if (pl.n !== undefined && pl.of !== undefined) task.iconText = String(pl.n) + '/' + String(pl.of);
    if (pl.next_retry_at && Y8 && Y8.time && Y8.time.clock) task.iconText = Y8.time.clock(pl.next_retry_at) + ' 重试';
    ch.queue.push(task);
    return true;
  };

  function spotXY(world, ch, spotKind) {
    const r = ECS.roomOf(world, ch.department);
    if (!r || !spotKind) return { x: ch.spot.x, y: ch.spot.y, seat: null };
    if (spotKind === 'desk') return { x: r.desk.seatX, y: r.desk.seatY, seat: r.desk };
    if (spotKind === 'stand') return { x: r.desk.seatX, y: r.desk.seatY, seat: null };
    if (spotKind === 'cabinet') return { x: r.cabinet.x, y: GEO.DESK_Y, seat: null };
    if (spotKind === 'terminal') return { x: r.terminal.x, y: GEO.PORT_STAND, seat: null };
    if (spotKind === 'inspect') return { x: r.desk.seatX, y: r.desk.seatY, seat: r.desk };
    if (spotKind === 'port_out') return { x: r.outPort - 6, y: GEO.PORT_STAND, seat: null };
    if (spotKind === 'port_in') return { x: r.inPort + 6, y: GEO.PORT_STAND, seat: null };
    return { x: r.desk.seatX, y: r.desk.seatY, seat: r.desk };
  }
  ECS.spotXY = spotXY;

  // 待机行为：跟 v8 design.md 第 5.4 节第一行相同——坐在工位喝茶
  function idleRestFor(world, ch) {
    const r = ECS.roomOf(world, ch.department);
    if (!r) return { x: ch.spot.x, y: ch.spot.y, seat: null, anim: 'idle' };
    return { x: r.desk.seatX, y: r.desk.seatY, seat: r.desk, anim: 'tea' };
  }

  // 每帧调用一次。scene 用于驱动 v7/v8 已有的 actor 补间（scene.run/scene.play），不重写走动与缓动逻辑。
  // ch.rest 是调用方按当前快照写入的"现在该干什么"（形状同任务：spot/pose/icon/facing），
  // 只在没有事件任务在播放时生效——画面上的持续状态取自快照，动作的起点取自事件，两者走同一段推进代码。
  ECS.stepCharacters = function stepCharacters(world, scene) {
    Object.values(world.characters).forEach((ch) => {
      const a = scene.actors.find((x) => x.id === 'ch-' + ch.id);
      if (!a) return;
      if (!ch.current && ch.queue.length && !a.script) ch.current = ch.queue.shift();
      const task = ch.current || null;
      const rest = task ? spotXY(world, ch, task.spot) : (ch.rest ? spotXY(world, ch, ch.rest.spot) : idleRestFor(world, ch));
      const anim = task ? task.pose : (ch.rest ? ch.rest.pose : rest.anim);
      const seat = rest.seat;
      const atSpot = Math.hypot(a.x - rest.x, a.y - rest.y) < 1.5 && (seat ? a.seat === seat : !a.seat);
      if (!atSpot && !a.script) {
        const steps = [];
        if (a.seat) steps.push({ t: 'seat', seat: null }, { t: 'anim', name: 'idle', ms: 100 });
        steps.push({ t: 'go', x: rest.x, y: rest.y });
        if (seat) steps.push({ t: 'seat', seat: seat }, { t: 'turn', facing: 1 });
        const facing = (task && task.facing) || (ch.rest && ch.rest.facing);
        if (facing && !seat) steps.push({ t: 'turn', facing: facing });
        scene.run(a, steps, {});
        return;
      }
      const facing = (task && task.facing) || (ch.rest && ch.rest.facing);
      if (!a.script) {
        scene.play(a, anim);
        if (facing) a.facing = facing;
      }
      const iconTask = task || ch.rest;
      if (iconTask && iconTask.icon) {
        const text = iconTask.iconText || (iconTask.icon === 'text' ? iconTask.label : null);
        if (!a.icon || a.icon.kind !== iconTask.icon || a.icon.text !== text) a.icon = { kind: iconTask.icon, text: text, t0: scene.realT, fromTask: true };
      } else if (a.icon && a.icon.fromTask) a.icon = null;
      if (task && !task._t0) task._t0 = scene.realT;
      if (task && !task.hold && !task.streaming && scene.realT - task._t0 > task.ms) {
        a.icon = null;
        ch.current = null;
        if (task.onDone) task.onDone();
      }
      ch.bubble = ECS.bubbleFor(ch);
    });
  };

  // 第 3.4 节：P.ecs.bubbleFor —— 只读取已有的任务数据，不产生新的事实
  ECS.bubbleFor = function bubbleFor(ch) {
    const cur = ch.current;
    if (cur && cur.bubble === 'say' && cur.label) return { text: cur.label, kind: 'say' };
    const next = ch.queue[0];
    if (next && next.bubble !== null && next.label) return { text: next.label, kind: 'think' };
    return null;
  };

  ECS.syncCharacters = function syncCharacters(world, scene, wantDepts, spriteOf) {
    scene.actors.filter((a) => a.data.ecsChar && !wantDepts.includes(a.data.dept)).forEach((a) => scene.removeActor(a));
    wantDepts.forEach((d) => {
      if (!world.characters[d]) {
        const r = ECS.roomOf(world, d);
        world.characters[d] = { kind: 'character', id: d, department: d, spot: { x: r ? r.desk.seatX : 0, y: r ? r.desk.seatY : 0 }, queue: [], current: null, rest: null, bubble: null };
      }
      const r = ECS.roomOf(world, d);
      if (!r) return;
      let a = scene.actors.find((x) => x.id === 'ch-' + d);
      if (!a) {
        a = scene.addActor({ id: 'ch-' + d, sprite: spriteOf(d), x: r.desk.seatX, y: r.desk.seatY, anim: 'sit', data: { ecsChar: true, dept: d } });
        a.seat = r.desk;
      } else if (!a.script) {
        a.data.dept = d;
      }
      world.characters[d].spot = { x: a.x, y: a.y };
    });
  };

  // 角色实体对应的 actor（floor.js 与 room.js 用它读取快照状态来画旗标、算变暗）
  ECS.actorOf = function actorOf(world, scene, dept) {
    return scene.actors.find((x) => x.id === 'ch-' + dept) || null;
  };

  // ---------------------------------------------------------------------------
  // 第 3.4 节：包裹

  ECS.spawnPackage = function spawnPackage(world, id, workItemId, colorIndex, artifact, roomId) {
    world.packages[id] = { kind: 'package', id, workItemId, colorIndex, artifact, atRest: { roomId: roomId || null, spotKind: 'port_in' }, transit: null };
    return world.packages[id];
  };

  ECS.removePackage = function removePackage(world, id) {
    delete world.packages[id];
  };

  ECS.sendPackage = function sendPackage(world, id, linkKey, pts, ms, onDone, destRoomId) {
    const pk = world.packages[id];
    if (!pk) return;
    pk.atRest = null;
    pk.transit = { linkKey, pts, t0: null, k: 0, ms: ms || Math.max(700, ECS.polyLength(pts) * 9), onDone: onDone || null, destRoomId: destRoomId || null };
  };

  ECS.stepPackages = function stepPackages(world, scene) {
    Object.values(world.packages).forEach((pk) => {
      if (!pk.transit) return;
      if (pk.transit.t0 == null) pk.transit.t0 = scene.realT;
      const k = Math.min(1, (scene.realT - pk.transit.t0) / pk.transit.ms);
      pk.transit.k = k;
      pk.transit.pos = ECS.pointAt(pk.transit.pts, ECS.polyLength(pk.transit.pts) * P.ease.inOut(k));
      if (k >= 1) {
        const done = pk.transit.onDone;
        const dest = pk.transit.destRoomId;
        pk.atRest = { roomId: dest || null, spotKind: 'port_out' };
        pk.transit = null;
        if (done) done();
      }
    });
  };

  // 当前画面坐标：正在移动时取沿线插值的点，静止时返回 null（调用方按 atRest 决定画在房间的哪个位置）
  ECS.packagePosition = function packagePosition(pk) {
    return pk.transit ? pk.transit.pos : null;
  };

  // 这条管道上有没有正在移动的包裹（第 3.5 节：判断"通不通"的依据）
  ECS.linkActive = function linkActive(world, linkKey) {
    return Object.values(world.packages).some((pk) => pk.transit && pk.transit.linkKey === linkKey);
  };
})();
