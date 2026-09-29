// 实体—组件—系统（v9 构建约定第 3 节）：房间与管道的图结构声明、任务派发、角色与包裹的推进、头顶对话框的数据。
// 只依赖 engine.js 已有的画布与动画原语，不新增画布画法；floor.js、building.js 在这之上改写。
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
    return { rooms: {}, roomOrder: [], links: {}, characters: {}, packages: {} };
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
      const w = d.w != null ? d.w : (d.roomKind === 'shelf' ? (o.hasOps ? 82 : 136) : d.roomKind === 'hall' ? 100 : d.id === 'operations' ? 88 : 110);
      const r = {
        kind: 'room', id: d.id, label: d.label, roomKind: d.roomKind, x, y: GEO.TOP, w,
        door: x + Math.round(w / 2),
        inPort: x + 12,
        outPort: x + w - 12,
        // 交接管道离开房间的位置：大厅从信箱那一侧（v8 的 hall.x + 22）出发，其余房间在右墙的管道口
        pipeOut: d.roomKind === 'hall' ? x + 22 : x + w - 12,
        desk: { x: x + Math.round(w / 2) - 17, w: 34, seatX: x + Math.round(w / 2) - 5, seatY: GEO.DESK_Y },
        cabinet: { x: x + 8, y: GEO.FLOOR_LINE + 6 },
        terminal: { x: x + w - 16, y: GEO.PORT_STAND },
        monitor: { x: x + w - 26, y: GEO.PORT_STAND }
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

  // links: [{ from, to, kind: 'handoff'|'tube'|'return', via: 'under', optional }]
  ECS.declareLinks = function declareLinks(world, defs) {
    world.links = {};
    defs.forEach((d) => {
      const a = endpoint(world, d.from);
      const b = endpoint(world, d.to);
      if (!a || !b) {
        if (d.optional) return;
        throw new Error('管道的端点未声明：' + d.from + ' → ' + d.to);
      }
      const key = d.from + (d.kind === 'tube' ? '~' : '>') + d.to;
      world.links[key] = { kind: 'pipe', id: key, from: d.from, to: d.to, linkKind: d.kind, pts: routeLink(world, d, a, b) };
    });
    return world;
  };

  function routeLink(world, d, a, b) {
    const isMachine = d.to === 'machine_room';
    if (d.kind === 'handoff' && !isMachine) {
      return [[a.pipeOut, GEO.PIPE_Y], [b.inPort, GEO.PIPE_Y]];
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
    if (direct) return { pts: direct.pts, key: direct.id, reversed: false };
    const back = world.links[to + sep + from];
    if (back) return { pts: back.pts.slice().reverse(), key: back.id, reversed: true };
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
  // 每一项：{ label, spot, pose, bubble, ms, icon, facing }
  // spot：'desk'｜'stand'｜'cabinet'｜'terminal'｜'monitor'｜'inspect'｜'port_in'｜'port_out'
  // pose：engine.js 已注册的动作名（P.ANIMS 的键）
  // bubble：'say' 做这个任务时头顶显示说话气泡，内容为 label（模型请求在流式输出到达时逐字追加）｜null 不显示；
  //   队列里的下一项带有 label 时，头顶显示思考气泡（见 bubbleFor）
  // ms：到达 spot 以后做这么久；streaming 的任务只在正在做的模型请求上追加文字并让它多留一会儿
  // 键取自驱动它的事件类型，少数事件按 payload 再分支（taskKeyFor）；交接与传信的任务由 floor.js 直接放进队列。
  ECS.TASKS = {
    context_assembled: { label: '整理资料', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 900 },
    model_requested: { label: '打字', spot: 'desk', pose: 'type', bubble: 'say', ms: 1400 },
    model_stream_progress: { label: '', spot: 'desk', pose: 'type', bubble: 'say', ms: 1, streaming: true },
    model_attempt_finished: { label: '有想法了', spot: 'desk', pose: 'sit_happy', bubble: null, ms: 600, icon: 'bulb' },
    model_retry_scheduled: { label: '等待重试', spot: 'desk', pose: 'sit_wait', bubble: 'say', ms: 1400, icon: 'hourglass' },
    model_attempt_failed: { label: '失败了', spot: 'desk', pose: 'slump', bubble: null, ms: 900, icon: 'cross' },
    tool_started_search: { label: '翻找资料', spot: 'cabinet', pose: 'magnify', bubble: 'say', ms: 1200 },
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
    proposal_rejected: { label: '提案被退回', spot: 'desk', pose: 'sit_scratch', bubble: 'say', ms: 900, icon: 'question' },
    spec_accepted: { label: '盖上有效章', spot: 'desk', pose: 'sit_happy', bubble: 'say', ms: 800, icon: 'check' },
    contract_accepted: { label: '盖上有效章', spot: 'desk', pose: 'sit_happy', bubble: 'say', ms: 800, icon: 'check' },
    plan_accepted: { label: '贴上白板', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 800, icon: 'check' },
    delivery_accepted: { label: '装箱封存', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 900, icon: 'check' },
    qa_started: { label: '放大镜检查', spot: 'inspect', pose: 'magnify', bubble: 'say', ms: 1200 },
    qa_submitted_release: { label: '放行', spot: 'inspect', pose: 'stamp_once', bubble: 'say', ms: 1100, icon: 'check' },
    qa_submitted_rework: { label: '打回返工', spot: 'inspect', pose: 'stamp_once', bubble: 'say', ms: 1100, icon: 'exclaim' },
    department_guidance_received: { label: '门缝塞进纸条', spot: 'port_in', pose: 'crouch', bubble: null, ms: 700, icon: 'exclaim' },
    department_guidance_applied: { label: '阅读指导', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 900 },
    department_guidance_responded: { label: '写回复', spot: 'desk', pose: 'type', bubble: 'say', ms: 900 },
    compaction_recorded: { label: '整理摘要', spot: 'cabinet', pose: 'sit_up', bubble: 'say', ms: 900 },
    compaction_failed: { label: '重新整理', spot: 'desk', pose: 'sit_scratch', bubble: 'say', ms: 900, icon: 'cross' },
    run_paused: { label: '事项暂停', spot: 'desk', pose: 'sit_relax', bubble: null, ms: 1200, icon: 'zzz' },
    run_failed: { label: '事项失败', spot: 'desk', pose: 'slump', bubble: null, ms: 1200, icon: 'cross' },
    run_done: { label: '举手欢呼', spot: 'stand', pose: 'cheer', bubble: null, ms: 1200 },
    x_run_stopped_for_upgrade: { label: '收拾桌面', spot: 'stand', pose: 'tidy', bubble: null, ms: 1200 },
    x_run_auto_resumed: { label: '伸懒腰', spot: 'desk', pose: 'stretch_sit', bubble: null, ms: 800 },
    x_provider_wait_left: { label: '模型服务恢复', spot: 'desk', pose: 'sit_up', bubble: 'say', ms: 700 },
    x_auto_repair_stopped: { label: '停止自动修复', spot: 'desk', pose: 'sit_wait', bubble: null, ms: 1200, icon: 'cross' },
    // 交接：把包裹放进管道口、从管道口取出；返工与回流走另一侧的管道口
    package_handoff_out: { label: '放进管道口', spot: 'port_out', pose: 'side_place', bubble: null, ms: 520, facing: 1 },
    package_handoff_in: { label: '从管道口取出', spot: 'port_in', pose: 'crouch', bubble: null, ms: 520, facing: -1 },
    package_return_out: { label: '放进回流口', spot: 'port_in', pose: 'side_place', bubble: null, ms: 520, facing: -1 },
    package_return_in: { label: '从回流口取出', spot: 'port_out', pose: 'crouch', bubble: null, ms: 520, facing: 1 },
    // 传信：信件塞进传信管口（方向由 spot 与 facing 决定）
    letter_out: { label: '发出询问', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 520, facing: 1 },
    letter_in: { label: '回答询问', spot: 'port_in', pose: 'side_place', bubble: 'say', ms: 520, facing: -1 },
    // 待机时偶尔起身：走到房间里的一个位置伸个懒腰（位置在 ch.wanderTo）
    idle_wander: { label: '', spot: 'wander', pose: 'stretch', bubble: null, ms: 1500 }
  };

  // 行为开关：验收脚本把随机走动关掉，让静止画面可以逐像素比较
  ECS.config = { idleWander: true };

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

  // ---------------------------------------------------------------------------
  // 第 3.4 节：系统

  // 队列里最多留几个可以被挤掉的任务（must 的任务不受限制）；房间里的动作排队太长时，画面会落后于事实
  const MAX_QUEUE = 3;

  // 把一个任务放进部门角色的队列。key 取自任务目录，extra 覆盖任务的字段（label、facing、onDone……）。
  // extra.front 为真：插到队首，并放弃正在做的非 must 任务；extra.must 为真：不会被队列上限挤掉。
  ECS.enqueue = function enqueue(world, dept, key, extra) {
    const def = ECS.TASKS[key];
    const ch = world.characters[dept];
    if (!def || !ch) return null;
    const e = extra || {};
    const task = Object.assign({ taskKey: key }, def, e);
    if (e.front) {
      ch.queue.unshift(task);
      if (ch.current && !ch.current.must) ch.current = null;
    } else {
      ch.queue.push(task);
    }
    while (ch.queue.filter((t) => !t.must).length > MAX_QUEUE) ch.queue.splice(ch.queue.findIndex((t) => !t.must), 1);
    return task;
  };

  // 事件到达：命中任务目录则入队（角色的动作走队列）；没有任务的事件返回 false，由调用方按信号处理
  // （房间与管道的灯、牌子、计数不经过队列）
  ECS.dispatch = function dispatch(world, ev) {
    if (!ev || !ev.type) throw new Error('dispatch 需要事件对象');
    if (!ev.department) return false;
    const key = taskKeyFor(ev);
    const def = ECS.TASKS[key];
    const ch = world.characters[ev.department];
    if (!def || !ch) return false;
    const pl = ev.payload || {};
    if (def.streaming) {
      // 流式输出：文字接在正在做的模型请求上（第一段文字取代默认的标签），任务从最后一段文字起多留一会儿；
      // 没有正在做的请求就不产生任务
      const cur = ch.current;
      if (cur && cur.taskKey === 'model_requested') {
        cur.label = ((cur.streamed ? cur.label : '') + (pl.text || '')).slice(-120);
        cur.streamed = true;
        cur._t0 = null;
        return true;
      }
      return false;
    }
    const extra = { workItemId: ev.work_item_id };
    if (pl.n !== undefined && pl.of !== undefined) extra.iconText = String(pl.n) + '/' + String(pl.of);
    return Boolean(ECS.enqueue(world, ev.department, key, extra));
  };

  function spotXY(world, ch, spotKind) {
    const r = ECS.roomOf(world, ch.department);
    if (!r || !spotKind) return { x: ch.spot.x, y: ch.spot.y, seat: null };
    if (spotKind === 'desk' || spotKind === 'inspect') return { x: r.desk.seatX, y: r.desk.seatY, seat: r.desk };
    if (spotKind === 'stand') return { x: r.desk.seatX, y: r.desk.seatY, seat: null };
    if (spotKind === 'cabinet') return { x: r.cabinet.x, y: GEO.DESK_Y, seat: null };
    if (spotKind === 'terminal') return { x: r.terminal.x, y: r.terminal.y, seat: null };
    if (spotKind === 'monitor') return { x: r.monitor.x, y: r.monitor.y, seat: null };
    if (spotKind === 'wander') return { x: ch.wanderTo, y: GEO.PORT_STAND, seat: null };
    if (spotKind === 'port_out') return { x: r.outPort - 6, y: GEO.PORT_STAND, seat: null };
    if (spotKind === 'port_in') return { x: r.inPort + 6, y: GEO.PORT_STAND, seat: null };
    throw new Error('未知的 spot：' + spotKind);
  }
  ECS.spotXY = spotXY;

  // 待机行为：跟 v8 design.md 第 5.4 节第一行相同——坐在工位喝茶
  function idleRestFor(world, ch) {
    const r = ECS.roomOf(world, ch.department);
    if (!r) return { x: ch.spot.x, y: ch.spot.y, seat: null };
    return { x: r.desk.seatX, y: r.desk.seatY, seat: r.desk };
  }

  // 每帧调用一次。scene 用于驱动 v7/v8 已有的 actor 补间（scene.run/scene.play），不重写走动与缓动逻辑。
  // ch.rest 是调用方按当前快照写入的"现在该干什么"（形状同任务：spot、pose、icon、iconText、facing），
  // 只在没有事件任务在做时生效：画面上的持续状态取自快照，动作的起点取自事件，两者走同一段推进代码。
  ECS.stepCharacters = function stepCharacters(world, scene) {
    Object.values(world.characters).forEach((ch) => {
      const a = scene.actors.find((x) => x.id === 'ch-' + ch.id);
      if (!a) return;
      if (ch.current || ch.queue.length) ch.wanderAt = null;
      // 走路的脚本还没结束不换任务；整层静止（中断）时小人不出发，队列等着
      if (!ch.current && ch.queue.length && !a.script && !scene.frozen) {
        ch.current = ch.queue.shift();
        ch.current._t0 = null;
      }
      const task = ch.current;
      const goal = task || ch.rest || null;
      const spot = goal ? spotXY(world, ch, goal.spot) : idleRestFor(world, ch);
      const pose = goal ? goal.pose : (spot.seat ? 'tea' : 'idle');
      const atSpot = Math.hypot(a.x - spot.x, a.y - spot.y) < 1.5 && (spot.seat ? a.seat === spot.seat : !a.seat);
      if (!atSpot) {
        if (!a.script && !scene.frozen) {
          const steps = [];
          if (a.seat) steps.push({ t: 'seat', seat: null }, { t: 'anim', name: 'idle', ms: 120 });
          steps.push({ t: 'go', x: spot.x, y: spot.y });
          if (spot.seat) steps.push({ t: 'seat', seat: spot.seat }, { t: 'turn', facing: 1 });
          if (goal && goal.facing) steps.push({ t: 'turn', facing: goal.facing });
          scene.run(a, steps, {});
        }
        ch.bubble = ECS.bubbleFor(ch);
        return;
      }
      if (!a.script) {
        if (goal && goal.facing) a.facing = goal.facing;
        scene.play(a, pose);
      }
      if (goal && goal.icon) {
        const text = goal.iconText || (goal.icon === 'text' ? goal.label : null);
        if (!a.icon || a.icon.kind !== goal.icon || a.icon.text !== text) a.icon = { kind: goal.icon, text: text, t0: scene.realT, fromTask: true };
      } else if (a.icon && a.icon.fromTask) {
        a.icon = null;
      }
      if (task) {
        // 任务从到达位置开始计时：走路的时间不算在动作里
        if (task._t0 == null) task._t0 = scene.realT;
        if (scene.realT - task._t0 >= task.ms) {
          ch.current = null;
          if (task.onDone) task.onDone(task);
        }
      }
      // 待机（快照的持续状态是喝茶）时偶尔起身：隔几秒走到房间里的一个位置伸个懒腰，再回到工位
      if (!task && !ch.queue.length && goal && goal.pose === 'tea' && spot.seat && ECS.config.idleWander && !scene.frozen && !scene.reduced) {
        if (ch.wanderAt == null) {
          ch.wanderAt = scene.realT + 5000 + Math.random() * 7000;
        } else if (scene.realT >= ch.wanderAt) {
          const r = ECS.roomOf(world, ch.department);
          ch.wanderTo = Math.round(r.x + 18 + Math.random() * (r.w - 36));
          ch.wanderAt = null;
          ECS.enqueue(world, ch.id, 'idle_wander');
        }
      }
      ch.bubble = ECS.bubbleFor(ch);
    });
  };

  // 第 3.4 节：P.ecs.bubbleFor —— 只读取已有的任务数据，不产生新的事实
  ECS.bubbleFor = function bubbleFor(ch) {
    const cur = ch.current;
    if (cur && cur.bubble === 'say' && cur.label) return { text: cur.label, kind: 'say' };
    const next = ch.queue[0];
    if (next && next.bubble === 'say' && next.label) return { text: next.label, kind: 'think' };
    return null;
  };

  // 让 wantDepts 里的每个部门都有一个角色实体与对应的 actor（id 为 'ch-' + 部门），去掉不再需要的
  ECS.syncCharacters = function syncCharacters(world, scene, wantDepts, spriteOf) {
    scene.actors.filter((a) => a.data.ecsChar && !wantDepts.includes(a.data.dept)).forEach((a) => scene.removeActor(a));
    Object.keys(world.characters).forEach((d) => { if (!wantDepts.includes(d)) delete world.characters[d]; });
    wantDepts.forEach((d) => {
      const r = ECS.roomOf(world, d);
      if (!r) throw new Error('角色所在的房间未声明：' + d);
      if (!world.characters[d]) {
        world.characters[d] = { kind: 'character', id: d, department: d, spot: { x: r.desk.seatX, y: r.desk.seatY }, queue: [], current: null, rest: null, bubble: null };
      }
      let a = scene.actors.find((x) => x.id === 'ch-' + d);
      if (!a) {
        a = scene.addActor({ id: 'ch-' + d, sprite: spriteOf(d), x: r.desk.seatX, y: r.desk.seatY, anim: 'sit', data: { ecsChar: true, dept: d } });
        a.seat = r.desk;
      }
    });
  };

  // 角色实体对应的 actor
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

  ECS.sendPackage = function sendPackage(world, id, linkKey, pts, ms, onDone) {
    const pk = world.packages[id];
    if (!pk) return;
    pk.atRest = null;
    pk.transit = { linkKey, pts, t0: null, k: 0, ms: ms || Math.max(700, ECS.polyLength(pts) * 9), onDone: onDone || null };
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
        pk.atRest = { roomId: null, spotKind: 'port_out' };
        pk.transit = null;
        if (done) done(pk);
      }
    });
  };

  // 当前画面坐标：正在移动时取沿线插值的点，静止时返回 null（调用方按 atRest 决定画在房间的哪个位置）
  ECS.packagePosition = function packagePosition(pk) {
    return pk.transit ? pk.transit.pos : null;
  };

  // 这条管道上有没有正在移动的包裹
  ECS.linkActive = function linkActive(world, linkKey) {
    return Object.values(world.packages).some((pk) => pk.transit && pk.transit.linkKey === linkKey);
  };
})();
