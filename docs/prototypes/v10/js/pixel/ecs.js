// 实体—组件—系统（v9 构建约定第 3 节）：房间与管道的图结构声明、任务派发、角色与包裹的推进、管道的流动、头顶对话框的数据。
// 只依赖 engine.js 已有的画布与动画原语，不新增画布画法，也不出现任何具体的部门名：房间、管道、任务目录、待机活动都来自
// 声明（floor-decl.js），floor.js、building.js 在这之上改写。
(function () {
  'use strict';
  const Y10 = window.Y10;
  const P = Y10.pixel;
  if (!P || !P.createScene) throw new Error('ecs.js 需要先加载 js/pixel/engine.js');

  const ECS = {};
  P.ecs = ECS;

  // ---------------------------------------------------------------------------
  // 第 3.1 节：世界

  // catalog：{ tasks, idle, keyOf }，见第 3.4 节；每个世界带着自己的目录
  ECS.world = function world(catalog) {
    return {
      rooms: {}, roomOrder: [], links: {}, characters: {}, packages: {}, signals: {},
      catalog: Object.assign({ tasks: {}, idle: [], keyOf: (ev) => ev.type }, catalog || {})
    };
  };

  // 行为开关：autonomy 为假时，待机活动与管道的惯性都关闭，静止的画面只由快照决定（验收脚本用它逐像素比较）
  ECS.config = { autonomy: true };

  // ---------------------------------------------------------------------------
  // 第 3.2 节：房间与管道的声明
  //
  // 沿用 v8 floor.js 的几个常量（像素级一致）：
  const GEO = {
    TOP: 50, ROOM_B: 214, FLOOR_LINE: 150, DESK_Y: 196, PORT_STAND: 176,
    PIPE_Y: 138, TUBE_Y: 104, DUCT_Y: 30, DUCT_TUBE_Y: 42, UNDER_Y: 276, GAP: 6
  };
  ECS.GEO = GEO;

  // defs: [{ id, label, roomKind, w, when, pipeOutX, spots }]
  //   w：房间宽度，数字，或者 (flags) => 数字
  //   when：出现的条件名，flags[when] 为真才生成这个房间
  //   pipeOutX：交接管道离开房间的位置（房间左边缘起算），省略时是右墙的管道口
  //   spots：{ cabinet｜terminal｜monitor: (房间) => x }，把任务的位置对到房间里已有的陈设上
  // 房间实体的 def 字段是它的声明，画面用它取陈设与持续状态的规则
  ECS.declareRooms = function declareRooms(world, defs, flags) {
    const fl = flags || {};
    world.rooms = {};
    world.roomOrder = [];
    let x = 4;
    defs.forEach((d) => {
      if (d.when && !fl[d.when]) return;
      const w = typeof d.w === 'function' ? d.w(fl) : d.w;
      if (!(w > 0)) throw new Error('房间没有声明宽度：' + d.id);
      const r = {
        kind: 'room', id: d.id, label: d.label, roomKind: d.roomKind, x, y: GEO.TOP, w,
        door: x + Math.round(w / 2),
        inPort: x + 12,
        outPort: x + w - 12,
        pipeOut: d.pipeOutX != null ? x + d.pipeOutX : x + w - 12,
        desk: { x: x + Math.round(w / 2) - 17, w: 34, seatX: x + Math.round(w / 2) - 5, seatY: GEO.DESK_Y },
        cabinet: { x: x + 8, y: GEO.FLOOR_LINE + 6 },
        terminal: { x: x + w - 16, y: GEO.PORT_STAND },
        monitor: { x: x + w - 26, y: GEO.PORT_STAND },
        seats: null,
        def: d
      };
      Object.keys(d.spots || {}).forEach((k) => { r[k] = Object.assign({}, r[k], { x: d.spots[k](r) }); });
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

  // 不是房间的节点（机房里的设备……）：按明确的几何声明，[{ id, roomKind, x, y, w, h, def }]
  ECS.declareNodes = function declareNodes(world, defs) {
    world.rooms = {};
    world.roomOrder = [];
    defs.forEach((d) => {
      world.rooms[d.id] = Object.assign({ kind: 'room', seats: null }, d);
      world.roomOrder.push(d.id);
    });
    return world;
  };

  // links: [{ from, to, kind: 'handoff'|'tube'|'return'|其他, via: 'under', optional, pts }]
  // pts 是声明自己给出的折线（非房间的节点之间的管道用它）；重新声明时同一根管道保留原来的流动状态
  ECS.declareLinks = function declareLinks(world, defs) {
    const old = world.links || {};
    world.links = {};
    defs.forEach((d) => {
      const key = d.from + (d.kind === 'tube' ? '~' : '>') + d.to;
      let pts = d.pts;
      if (!pts) {
        const a = endpoint(world, d.from);
        const b = endpoint(world, d.to);
        if (!a || !b) {
          if (d.optional) return;
          throw new Error('管道的端点未声明：' + d.from + ' → ' + d.to);
        }
        pts = routeLink(world, d, a, b);
      }
      world.links[key] = { kind: 'pipe', id: key, from: d.from, to: d.to, linkKind: d.kind, pts, flow: old[key] ? old[key].flow : null, def: d };
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
      // via 由声明指定，不猜测：'under' 走地板下（隔得远的回流），省略时走天花板
      if (d.via === 'under') {
        return [[a.x + 20, GEO.ROOM_B - 4], [a.x + 20, GEO.UNDER_Y], [b.x + 12, GEO.UNDER_Y], [b.x + 12, GEO.ROOM_B + 26]];
      }
      return [[a.outPort - 8, GEO.PIPE_Y - 8], [a.outPort - 8, GEO.DUCT_Y], [b.inPort + 8, GEO.DUCT_Y], [b.inPort + 8, GEO.PIPE_Y - 8]];
    }
    throw new Error('未知的管道种类：' + d.kind);
  }

  ECS.roomOf = function roomOf(world, id) {
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

  // 一次交接经过的管道：两个房间之间直接有管道就是它（反向也可以），没有就沿声明的交接管道找一条最短的路，
  // 一段一根管道。找不到返回空数组。
  ECS.route = function route(world, from, to) {
    const direct = ECS.linkBetween(world, from, to, 'handoff');
    if (direct) return [direct];
    const edges = Object.values(world.links).filter((l) => l.linkKind === 'handoff');
    const prev = { [from]: null };
    const queue = [from];
    while (queue.length) {
      const at = queue.shift();
      if (at === to) break;
      edges.filter((l) => l.from === at && !(l.to in prev)).forEach((l) => { prev[l.to] = l; queue.push(l.to); });
    }
    if (!(to in prev)) return [];
    const hops = [];
    for (let l = prev[to]; l; l = prev[l.from]) hops.unshift({ pts: l.pts, key: l.id, reversed: false, link: l });
    return hops;
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
  // 第 3.3 节：工位与角色
  //
  // 一个房间里有 n 个角色时沿房间排开 n 个工位；只有一个角色时就是 declareRooms 算出的 desk（与 v8 一样）
  ECS.layoutSeats = function layoutSeats(room, n) {
    if (n <= 1) { room.seats = [room.desk]; return room.seats; }
    const gap = 2;
    const w = Math.min(34, Math.floor((room.w - 10) / n) - gap);
    const total = n * (w + gap) - gap;
    const x0 = room.x + Math.round((room.w - total) / 2);
    room.seats = [];
    for (let i = 0; i < n; i++) {
      const x = x0 + i * (w + gap);
      room.seats.push({ x, w, seatX: x + Math.round(w * 12 / 34), seatY: GEO.DESK_Y });
    }
    return room.seats;
  };

  // 工具角色在两侧，中心角色居中，经理靠近右墙的管道口（跟 room.js 部门房间的排布规则一致）
  const SEAT_RANK = { explorer: 0, reviewer: 1, lead: 2, agent: 3, ops: 3, architect: 3, tester: 3, manager: 4 };
  const CENTER_KINDS = ['architect', 'tester', 'agent', 'ops'];

  ECS.charsOf = function charsOf(world, dept) {
    return Object.values(world.characters).filter((c) => c.department === dept);
  };

  // 部门里的中心角色：没有中心角色时是经理，再没有就是第一个
  ECS.primaryOf = function primaryOf(world, dept) {
    const list = ECS.charsOf(world, dept);
    return list.find((c) => CENTER_KINDS.includes(c.roleKind)) || list.find((c) => c.roleKind === 'manager') || list[0] || null;
  };

  // 事件或任务落在哪个角色上：指定了角色（id 或种类）就是它，否则按任务声明的 by（角色种类），再没有就是中心角色
  ECS.charFor = function charFor(world, dept, role, by) {
    const list = ECS.charsOf(world, dept);
    if (!list.length) return null;
    const hit = (k) => list.find((c) => c.id === k || c.roleKind === k);
    return (role && hit(role)) || (by && hit(by)) || ECS.primaryOf(world, dept);
  };

  function seatOf(room, ch) {
    return (room.seats && room.seats[ch.seatIndex]) || room.desk;
  }

  // ---------------------------------------------------------------------------
  // 第 3.4 节：任务目录、待机活动与信号（内容全部来自声明）
  //
  // 任务：{ label, spot, pose, bubble, ms, icon, facing, dept, by, actor, toward, then, start, done }
  //   spot：'desk'｜'stand'｜'cabinet'｜'terminal'｜'monitor'｜'inspect'｜'port_in'｜'port_out'
  //         ｜'peer'（另一个角色的工位旁，toward 指定是谁）｜'at'（任务自带的坐标 at）
  //   dept：由哪个部门做（事件没有部门字段时用，例如故障记录由运维做）
  //   by：事件没有指定角色时由哪种角色做；actor：不管事件指定了谁，都由这种角色做（分派任务是经理做的）
  //   toward：spot 为 'peer' 时走向谁：'role'（事件指定的角色）或者角色种类；then：做完以后放进走向对象队列的任务
  //   start／done：任务开始（到达位置）与做完时的回调，由 floor.js 按声明的效果装上
  // 待机活动：[{ key（任务目录里的键）, weight, kinds（限定角色种类）, needs: 'mate'（需要一个空闲的同伴）, at: 'wander'｜'door' }]
  // keyOf(事件)：事件落在哪个任务上；没有命中任务目录的事件是信号。

  // 信号：不需要角色去做什么的画面指示（门缝亮灯、信箱闪、监控屏告警、设备闪光……），在 ms 毫秒内为真，可以带一个值（例如颜色）
  ECS.signal = function signal(world, scene, name, ms, value) {
    world.signals[name] = { until: scene.realT + ms, value: value === undefined ? true : value };
  };
  ECS.signalOn = function signalOn(world, scene, name) {
    const s = world.signals[name];
    return Boolean(s) && s.until > scene.realT;
  };
  // 信号的值；没有亮着的信号返回 null
  ECS.signalValue = function signalValue(world, scene, name) {
    return ECS.signalOn(world, scene, name) ? world.signals[name].value : null;
  };

  // 队列里最多留几个可以被挤掉的任务（must 的任务不受限制）；房间里的动作排队太长时，画面会落后于事实
  const MAX_QUEUE = 3;

  // 把一个任务放进角色的队列。who 是角色 id 或部门 id（部门按 extra.role 与任务的 by 找角色），key 取自任务目录，
  // extra 覆盖任务的字段（label、facing、onDone……）。
  // extra.front 为真：插到队首，并放弃正在做的非 must 任务；extra.must 为真：不会被队列上限挤掉。
  ECS.enqueue = function enqueue(world, who, key, extra) {
    const def = world.catalog.tasks[key];
    if (!def) return null;
    const e = extra || {};
    const ch = world.characters[who] || ECS.charFor(world, who, def.actor ? null : e.role, def.actor || def.by);
    if (!ch) return null;
    const task = Object.assign({ taskKey: key }, def, e);
    if (!task.idle) {
      // 真正的事情优先：正在做和排着的待机活动放弃
      if (ch.current && ch.current.idle) ch.current = null;
      ch.queue = ch.queue.filter((t) => !t.idle);
    }
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
  // 参数 make(task 定义, 事件, 执行的角色, 一方)：调用方为任务装上事件相关的字段（效果回调、气泡文字……），可以省略；
  // 一方为 'to' 表示这个任务是事件里收东西的一方做的（任务的 then 后续任务）
  ECS.dispatch = function dispatch(world, ev, make) {
    if (!ev || !ev.type) throw new Error('dispatch 需要事件对象');
    const key = world.catalog.keyOf(ev);
    const def = world.catalog.tasks[key];
    if (!def) return false;
    // 任务声明了 dept 就由那个部门做（事件本身可以没有部门字段），否则是事件的部门
    const dept = def.dept || ev.department;
    if (!dept) return false;
    const ch = ECS.charFor(world, dept, def.actor ? null : ev.role, def.actor || def.by);
    if (!ch) return false;
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
    // 走向另一个角色的任务：对象是事件指定的角色，或者部门里某种角色
    if (def.spot === 'peer') {
      const to = def.toward === 'role' ? ECS.charFor(world, dept, ev.role) : ECS.charFor(world, dept, null, def.toward);
      if (!to || to === ch) return false;
      extra.withId = to.id;
      if (def.then) extra.onDone = () => { ECS.enqueue(world, to.id, def.then, make ? make(world.catalog.tasks[def.then], ev, to, 'to') : null); };
    }
    if (make) Object.assign(extra, make(def, ev, ch));
    return Boolean(ECS.enqueue(world, ch.id, key, extra));
  };

  function spotXY(world, ch, kind, task) {
    const r = ECS.roomOf(world, ch.department);
    if (!r || !kind) return { x: ch.spot.x, y: ch.spot.y, seat: null };
    const seat = seatOf(r, ch);
    if (kind === 'desk' || kind === 'inspect') return { x: seat.seatX, y: seat.seatY, seat };
    if (kind === 'stand') return { x: seat.seatX, y: seat.seatY, seat: null };
    if (kind === 'cabinet') return { x: r.cabinet.x, y: GEO.DESK_Y, seat: null };
    if (kind === 'terminal') return { x: r.terminal.x, y: r.terminal.y, seat: null };
    if (kind === 'monitor') return { x: r.monitor.x, y: r.monitor.y, seat: null };
    if (kind === 'door') return { x: r.door, y: GEO.ROOM_B - 10, seat: null };
    if (kind === 'port_out') return { x: r.outPort - 6, y: GEO.PORT_STAND, seat: null };
    if (kind === 'port_in') return { x: r.inPort + 6, y: GEO.PORT_STAND, seat: null };
    if (kind === 'at') return { x: task.at.x, y: task.at.y, seat: null };
    if (kind === 'peer') {
      const peer = world.characters[task.withId];
      const pr = peer && ECS.roomOf(world, peer.department);
      if (!pr) return { x: seat.seatX, y: seat.seatY, seat: null };
      const ps = seatOf(pr, peer);
      const dir = ps.seatX >= seat.seatX ? 1 : -1;
      return { x: ps.seatX - dir * 12, y: GEO.PORT_STAND, seat: null, facing: dir };
    }
    throw new Error('未知的 spot：' + kind);
  }
  ECS.spotXY = spotXY;

  // 待机行为：跟 v8 design.md 第 5.4 节第一行相同——坐在工位喝茶
  function idleRestFor(world, ch) {
    const r = ECS.roomOf(world, ch.department);
    if (!r) return { x: ch.spot.x, y: ch.spot.y, seat: null };
    const seat = seatOf(r, ch);
    return { x: seat.seatX, y: seat.seatY, seat };
  }

  // 每帧调用一次。scene 用于驱动 v7/v8 已有的 actor 补间（scene.run/scene.play），不重写走动与缓动逻辑。
  // ch.rest 是调用方按当前快照写入的"现在该干什么"（形状同任务：spot、pose、icon、iconText、facing、hold；away 为真表示不在房间里），
  // 只在没有事件任务在做时生效：画面上的持续状态取自快照，动作的起点取自事件，两者走同一段推进代码。
  ECS.stepCharacters = function stepCharacters(world, scene) {
    Object.values(world.characters).forEach((ch) => stepOne(world, scene, ch));
  };

  function stepOne(world, scene, ch) {
    const a = ECS.actorOf(world, scene, ch.id);
    if (!a) return;
    if (ch.current || ch.queue.length) ch.idleAt = null;
    // 待机活动的走路被真正的任务打断：放弃走到一半的路，直接去做真正的任务
    if (!ch.current && ch.queue.length && a.script && a.data.idleWalk) { scene.cancel(a); a.data.idleWalk = false; }
    // 走路的脚本还没结束不换任务；整层静止（中断）时小人不出发，队列等着
    if (!ch.current && ch.queue.length && !a.script && !scene.frozen) {
      ch.current = ch.queue.shift();
      ch.current._t0 = null;
    }
    const task = ch.current;
    const goal = task || ch.rest || null;
    const room = ECS.roomOf(world, ch.department);
    // 不在房间里（外出）：从画面上消失，回来时从门口走进来
    if (goal && goal.away) {
      a.visible = false; a.seat = null; ch.bubble = null;
      return;
    }
    if (!a.visible && room) { a.visible = true; a.seat = null; a.x = room.door; a.y = GEO.ROOM_B - 6; }
    const spot = goal ? spotXY(world, ch, goal.spot, goal) : idleRestFor(world, ch);
    const pose = goal ? goal.pose : (spot.seat ? 'tea' : 'idle');
    const facing = (goal && goal.facing) || spot.facing || 0;
    const atSpot = Math.hypot(a.x - spot.x, a.y - spot.y) < 1.5 && (spot.seat ? a.seat === spot.seat : !a.seat);
    if (!atSpot) {
      if (!a.script && !scene.frozen) {
        const steps = [];
        if (a.seat) steps.push({ t: 'seat', seat: null }, { t: 'anim', name: 'idle', ms: 120 });
        steps.push({ t: 'go', x: spot.x, y: spot.y });
        if (spot.seat) steps.push({ t: 'seat', seat: spot.seat }, { t: 'turn', facing: 1 });
        if (facing) steps.push({ t: 'turn', facing });
        scene.run(a, steps, {});
        a.data.idleWalk = Boolean(goal && goal.idle);
      }
      ch.bubble = ECS.bubbleFor(ch);
      return;
    }
    if (!a.script) {
      if (facing) a.facing = facing;
      scene.play(a, pose);
      a.hold = (goal && goal.hold) || null;
    }
    if (goal && goal.icon) {
      const text = goal.iconText || (goal.icon === 'text' ? goal.label : null);
      if (!a.icon || a.icon.kind !== goal.icon || a.icon.text !== text) a.icon = { kind: goal.icon, text: text, t0: scene.realT, fromTask: true };
    } else if (a.icon && a.icon.fromTask) {
      a.icon = null;
    }
    if (task) {
      // 任务从到达位置开始计时：走路的时间不算在动作里
      if (task._t0 == null) {
        task._t0 = scene.realT;
        if (task.start && !task._started) { task._started = true; task.start(task); }
      }
      if (scene.realT - task._t0 >= task.ms) {
        ch.current = null;
        if (task.onDone) task.onDone(task);
        if (task.done) task.done(task);
      }
    }
    // 待机（快照的持续状态是喝茶）时隔几秒自己挑一件事做；同一个房间里的角色越多，每个人挑得越稀
    if (!task && !ch.queue.length && goal && goal.pose === 'tea' && spot.seat && ECS.config.autonomy && !scene.frozen && !scene.reduced) {
      if (ch.idleAt == null) ch.idleAt = scene.realT + (5000 + Math.random() * 7000) * (1 + 0.15 * (ECS.charsOf(world, ch.department).length - 1));
      else if (scene.realT >= ch.idleAt) { ch.idleAt = null; startIdle(world, ch); }
    }
    ch.bubble = ECS.bubbleFor(ch);
  }

  // 空闲的角色自己挑一件事：从目录的待机活动里按权重抽一项（限定角色种类、需要空闲的同伴的都要满足条件）。
  // 待机活动不产生事实，头顶没有对话框，遇到真正的任务立刻放弃。
  function startIdle(world, ch) {
    const room = ECS.roomOf(world, ch.department);
    if (!room) return;
    const mates = ECS.charsOf(world, ch.department).filter((c) => c !== ch && free(world, c));
    const pool = world.catalog.idle.filter((it) => (!it.kinds || it.kinds.includes(ch.roleKind)) && (!it.needs || mates.length));
    const total = pool.reduce((s, it) => s + it.weight, 0);
    if (!total) return;
    let k = Math.random() * total;
    const pick = pool.find((it) => (k -= it.weight) < 0) || pool[pool.length - 1];
    const mate = pick.needs ? mates[Math.floor(Math.random() * mates.length)] : null;
    const pos = (frac) => Math.round(room.x + 18 + frac * (room.w - 36));
    if (pick.at === 'wander') {
      ECS.enqueue(world, ch.id, pick.key, { idle: true, at: { x: pos(Math.random()), y: GEO.PORT_STAND } });
    } else if (pick.at === 'door') {
      ECS.enqueue(world, ch.id, pick.key, { idle: true, at: { x: room.door, y: GEO.PORT_STAND } });
    } else if (pick.needs && mate) {
      // 两个空闲的角色在房间中间碰头说话
      const mid = pos(Math.random());
      ECS.enqueue(world, ch.id, pick.key, { idle: true, at: { x: mid - 9, y: GEO.PORT_STAND }, facing: 1 });
      ECS.enqueue(world, mate.id, pick.key, { idle: true, at: { x: mid + 9, y: GEO.PORT_STAND }, facing: -1 });
    } else {
      ECS.enqueue(world, ch.id, pick.key, { idle: true });
    }
  }

  function free(world, c) {
    return !c.current && !c.queue.length && c.rest && c.rest.pose === 'tea' && !c.rest.away;
  }

  // 第 3.4 节：P.ecs.bubbleFor —— 只读取已有的任务数据，不产生新的事实
  ECS.bubbleFor = function bubbleFor(ch) {
    const cur = ch.current;
    if (cur && cur.bubble === 'say' && cur.label) return { text: cur.label, kind: 'say', tail: Boolean(cur.streamed) };
    const next = ch.queue[0];
    if (next && next.bubble === 'say' && next.label) return { text: next.label, kind: 'think' };
    return null;
  };

  // 让 specs 里的每个角色都有一个角色实体与对应的 actor（id 为 'ch-' + 角色 id），去掉不再需要的，并给每个房间排好工位。
  // specs: [{ id, department, roleKind, name }]；spriteOf(spec) 给出精灵名
  ECS.syncCharacters = function syncCharacters(world, scene, specs, spriteOf) {
    const want = new Set(specs.map((s) => s.id));
    scene.actors.filter((a) => a.data.ecsChar && !want.has(a.data.charId)).forEach((a) => scene.removeActor(a));
    Object.keys(world.characters).forEach((id) => { if (!want.has(id)) delete world.characters[id]; });
    const byRoom = {};
    specs.forEach((s) => { (byRoom[s.department] = byRoom[s.department] || []).push(s); });
    Object.keys(byRoom).forEach((dept) => {
      const r = ECS.roomOf(world, dept);
      if (!r) throw new Error('角色所在的房间未声明：' + dept);
      const list = byRoom[dept].slice().sort((p, q) => ((SEAT_RANK[p.roleKind] || 0) - (SEAT_RANK[q.roleKind] || 0)) || (p.id < q.id ? -1 : 1));
      const relayout = !r.seats || r.seats.length !== list.length;
      if (relayout) ECS.layoutSeats(r, list.length);
      list.forEach((s, i) => {
        const seat = r.seats[i];
        let ch = world.characters[s.id];
        if (!ch) {
          ch = world.characters[s.id] = { kind: 'character', id: s.id, department: dept, roleKind: s.roleKind, name: s.name, spot: { x: seat.seatX, y: seat.seatY }, seatIndex: i, queue: [], current: null, rest: null, bubble: null };
        }
        ch.seatIndex = i; ch.roleKind = s.roleKind; ch.name = s.name;
        let a = ECS.actorOf(world, scene, s.id);
        if (!a) {
          a = scene.addActor({ id: 'ch-' + s.id, sprite: spriteOf(s), x: seat.seatX, y: seat.seatY, anim: 'sit', data: { ecsChar: true, dept, charId: s.id } });
          a.seat = seat;
        } else if (relayout && a.seat) {
          a.seat = seat;
        }
      });
    });
  };

  // 角色实体对应的 actor
  ECS.actorOf = function actorOf(world, scene, id) {
    return scene.actors.find((x) => x.id === 'ch-' + id) || null;
  };

  // ---------------------------------------------------------------------------
  // 第 3.5 节：包裹

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

  // ---------------------------------------------------------------------------
  // 第 3.6 节：管道的流动
  //
  // 管道是持续运转的实体：流速带着惯性跟随状态，光点按累计的相位向前移动，管道里的光点（load）随状态增减。
  //   flowing：加速到满速，光点逐渐布满；idle：减速，光点淡出；stopped：迅速停下，光点留在原处，等恢复以后继续流动。
  // stateOf(pipe) 由调用方按快照给出 'flowing'｜'idle'｜'stopped'。autonomy 关闭时状态直接对应 v8 的画法（满速或没有）。
  ECS.stepPipes = function stepPipes(world, scene, stateOf) {
    const now = scene.realT;
    Object.values(world.links).forEach((p) => {
      const f = p.flow || (p.flow = { state: 'idle', speed: 0, load: 0, phase: 0, t: now });
      const dt = Math.max(0, Math.min(200, now - f.t));
      f.t = now;
      f.state = stateOf(p);
      if (!ECS.config.autonomy) { f.speed = f.state === 'flowing' ? 1 : 0; f.load = f.speed; return; }
      const goal = f.state === 'flowing' ? 1 : 0;
      f.speed += (goal - f.speed) * Math.min(1, dt / (f.state === 'stopped' ? 120 : 350));
      if (Math.abs(goal - f.speed) < 0.01) f.speed = goal;
      if (f.state === 'flowing') f.load = Math.min(1, f.load + dt / 500);
      else if (f.state === 'idle') f.load = Math.max(0, f.load - dt / 1600);
      f.phase += f.speed * dt;
    });
  };
})();
