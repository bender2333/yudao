// 项目楼层（设计说明第 5.2 至 5.6 节）：大厅（信箱、排队的包裹、槽位灯）、产品·工程·质检三个房间与交接管道、传信管、
// 回流管道、成果库、运维房间（Stage 4）、通往机房的门（3.2C）、上方信息条。状态以 setModel 为准，事件只播放动作
(function () {
  'use strict';
  const Y8 = window.Y8;
  const P = Y8.pixel;
  if (!P || !P.createScene) throw new Error('floor.js 需要先加载 js/pixel/engine.js');
  const PAL = P.PAL;
  const R = P.R, RB = P.RB, paint = P.paint;

  const W = 640, H = 320;
  const BAR = 18;          // 信息条高度
  const TOP = 50;          // 房间上沿
  const FLOOR_LINE = 150;  // 房间内墙与地面的分界
  const ROOM_B = 214;      // 房间下沿（门所在的墙）
  const DESK_Y = 196;      // 工位的桌面前沿
  const PORT_STAND = 176;  // 小人站在管道口前的位置
  const PIPE_Y = 138;      // 交接管道的高度
  const TUBE_Y = 104;      // 相邻房间之间传信管的高度
  const DUCT_Y = 30;       // 天花板上的回流管道
  const DUCT_TUBE_Y = 42;  // 天花板上的长传信管（产品与质检之间）
  const CORR_Y = 238;      // 走廊
  const UNDER_Y = 276;     // 地板下的管道（运维故障信件回到大厅）
  const DEPTS = ['product', 'engineering', 'quality'];
  const ART_BMP = { prd: 'scroll', box: 'box_sealed', defect: 'box_rework', release: 'box_release', letter: 'letter' };
  const IN_ROOM = ['running', 'asking', 'waiting_provider', 'paused', 'failed', 'done', 'cancelled', 'interrupted', 'pending_verification', 'waiting_resume', 'stopped_for_upgrade'];
  const ACTIVE = ['running', 'asking', 'pending_verification'];
  const STATUS_TEXT = {
    queued: '排队中', waiting_slot: '等待执行槽位', running: '运行中', asking: '询问中', waiting_provider: '等待模型服务', paused: '已暂停',
    failed: '失败', done: '已完成', cancelled: '已取消', interrupted: '中断', pending_verification: '待核实', waiting_resume: '待恢复',
    stopped_for_upgrade: '因升级停止', adopted: '已采纳'
  };
  const STATUS_CHIP = {
    running: PAL.green2, asking: PAL.blue2, queued: PAL.grey2, waiting_slot: PAL.grey2, waiting_provider: PAL.grey3, paused: PAL.blue1,
    failed: PAL.red2, done: PAL.green1, cancelled: PAL.grey2, interrupted: PAL.grey3, pending_verification: PAL.yellow2,
    waiting_resume: PAL.yellow2, stopped_for_upgrade: PAL.orange2, adopted: PAL.green3
  };
  const TUBE = '#7fc3e8', TUBE_D = '#3f86b0';

  // 画面状态与事实的对照：动作图鉴列出（设计说明第 5.4 节）
  P.FLOOR_VIEWS = [
    { id: 'working', fact: '部门正在工作', source: '事项的当前部门与 department_activated', picture: '该房间亮灯，房间里的小人在工位工作', level: 'ui', events: ['department_activated'] },
    { id: 'handoff', fact: '交接', source: 'transition 与交接内容', picture: '包裹在交接管道中移动', level: 'ui', events: ['transition'] },
    { id: 'rework', fact: '返工', source: 'qa_submitted 的结论为 rework_engineering 或 rework_product', picture: '包裹贴红色返工单反向或经回流管道流动，管道闪红色', level: 'ui', events: ['qa_submitted', 'transition'] },
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
    { id: 'terminal', fact: '终止', source: 'run_done、run_failed、run_paused、取消', picture: '门口立完成、失败（停止原因）、暂停或已取消的牌子', level: 'ui', events: ['run_done', 'run_failed', 'run_paused'] }
  ];

  // ---------------------------------------------------------------------------
  // 布局：有运维房间（Stage 4）时成果库变窄

  function layoutFor(hasOps) {
    const hall = { id: 'hall', x: 4, w: 100 };
    const rooms = {};
    let x = 110;
    DEPTS.forEach((d) => { rooms[d] = { id: d, x, w: 110 }; x += 116; });
    const lib = { id: 'library', x, w: hasOps ? 82 : 136 };
    x += lib.w + 6;
    const ops = hasOps ? { id: 'operations', x, w: 88 } : null;
    const door = { x: 606, y: 218, w: 28, h: 40 };   // 通往机房的门，在走廊尽头
    [hall, lib, ops].concat(DEPTS.map((d) => rooms[d])).forEach((r) => {
      if (!r) return;
      r.door = r.x + Math.round(r.w / 2);
      r.inPort = r.x + 12;              // 左墙的管道口
      r.outPort = r.x + r.w - 12;       // 右墙的管道口
      r.desk = { x: r.x + Math.round(r.w / 2) - 17, w: 34, seatX: r.x + Math.round(r.w / 2) - 5, seatY: DESK_Y };
    });
    return { hall, rooms, lib, ops, door };
  }

  function roomOf(lay, id) {
    if (id === 'hall') return lay.hall;
    if (id === 'library' || id === 'adopted' || id === 'adoption') return lay.lib;
    if (id === 'operations') return lay.ops;
    return lay.rooms[id] || null;
  }

  // 管道：交接管道 handoff（粗的玻璃管）与传信管 tube（细的蓝色管）；pts 为画面坐标的折线
  function pipesFor(lay) {
    const r = lay.rooms;
    const pipes = {};
    const add = (key, kind, pts) => { pipes[key] = { key, kind, pts }; };
    add('hall>product', 'handoff', [[lay.hall.x + 22, PIPE_Y], [r.product.inPort, PIPE_Y]]);
    add('product>engineering', 'handoff', [[r.product.outPort, PIPE_Y], [r.engineering.inPort, PIPE_Y]]);
    add('engineering>quality', 'handoff', [[r.engineering.outPort, PIPE_Y], [r.quality.inPort, PIPE_Y]]);
    add('quality>library', 'handoff', [[r.quality.outPort, PIPE_Y], [lay.lib.inPort, PIPE_Y]]);
    // 回流管道：质检经天花板回到产品
    add('quality>product', 'return', [[r.quality.outPort - 8, PIPE_Y - 8], [r.quality.outPort - 8, DUCT_Y], [r.product.inPort + 8, DUCT_Y], [r.product.inPort + 8, PIPE_Y - 8]]);
    add('product~engineering', 'tube', [[r.product.outPort, TUBE_Y], [r.engineering.inPort, TUBE_Y]]);
    add('engineering~quality', 'tube', [[r.engineering.outPort, TUBE_Y], [r.quality.inPort, TUBE_Y]]);
    add('product~quality', 'tube', [[r.product.x + 30, TUBE_Y - 12], [r.product.x + 30, DUCT_TUBE_Y], [r.quality.x + r.quality.w - 30, DUCT_TUBE_Y], [r.quality.x + r.quality.w - 30, TUBE_Y - 12]]);
    if (lay.ops) {
      add('library>operations', 'handoff', [[lay.lib.outPort, PIPE_Y], [lay.ops.inPort, PIPE_Y]]);
      add('operations>machine_room', 'handoff', [[lay.ops.outPort, PIPE_Y], [lay.ops.outPort, ROOM_B + 10], [lay.door.x + 14, ROOM_B + 10], [lay.door.x + 14, lay.door.y + 12]]);
      add('operations>hall', 'return', [[lay.ops.x + 20, ROOM_B - 4], [lay.ops.x + 20, UNDER_Y], [lay.hall.x + 12, UNDER_Y], [lay.hall.x + 12, ROOM_B + 26]]);
    }
    return pipes;
  }

  function polyLength(pts) {
    let len = 0;
    for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    return len;
  }

  function pointAt(pts, d) {
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
  }

  // ---------------------------------------------------------------------------

  P.createFloorScene = function createFloorScene(canvas, opts) {
    const o = opts || {};
    let model = { items: [], open_requests: [], shelves: { adopted: [] }, slots: null, waiting_provider: [], machines: null, ops: null, interrupted: false };
    let lay = layoutFor(false);
    let pipes = pipesFor(lay);
    let focusId = null;
    let overlay = { id: null, data: null };
    const st = {
      clock: 15.5 * 3600000, flash: {}, pipeFlash: {}, movers: [], arrows: [], mailFlash: 0, shelfFlash: 0,
      doorFlash: 0, monitorFlash: 0, decisions: {}, remoteDots: [], queueX: {}, n: 0
    };
    const scene = P.createScene(canvas, { W, H, draw, update });
    let bg = null, bgKey = '';

    const itemById = (id) => model.items.find((it) => it.id === id) || null;
    const dimFor = (itemId) => (focusId && itemId && itemId !== focusId ? 0.3 : 1);
    const itemsIn = (d) => model.items.filter((it) => it.department === d && IN_ROOM.includes(it.status));
    const waitingDept = (d) => (model.waiting_provider || []).find((w) => w.department === d) || null;

    // -------------------------------------------------------------------------
    // 房间里的小人：每个房间一个；运维房间在 Stage 4 起出现

    function spriteOf(d) { return d === 'operations' ? 'operations.ops' : d + '.agent'; }

    function primaryItem(d) {
      const here = itemsIn(d);
      return here.find((it) => ACTIVE.includes(it.status)) || here.find((it) => it.status === 'waiting_provider') || here[0] || null;
    }

    function syncWorkers() {
      const want = DEPTS.concat(lay.ops ? ['operations'] : []);
      scene.actors.filter((a) => a.data.worker && !want.includes(a.data.dept)).forEach((a) => scene.removeActor(a));
      want.forEach((d) => {
        const r = roomOf(lay, d);
        let a = scene.actors.find((x) => x.data.worker && x.data.dept === d);
        if (!a) {
          a = scene.addActor({ id: 'w-' + d, sprite: spriteOf(d), x: r.desk.seatX, y: r.desk.seatY, anim: 'sit', data: { worker: true, dept: d } });
          a.seat = r.desk;
        }
        a.data.room = r;
        a.data.item = primaryItem(d);
      });
    }

    function restFor(a) {
      const d = a.data.dept;
      const r = a.data.room;
      const it = a.data.item;
      const seat = (anim, icon) => ({ x: r.desk.seatX, y: r.desk.seatY, seat: r.desk, anim, icon: icon || null });
      if (d === 'operations') {
        if (model.ops && model.ops.fault) return { x: r.x + r.w - 26, y: PORT_STAND, seat: null, anim: 'watch_r', icon: { kind: 'exclaim' } };
        return seat(model.ops ? 'type' : 'tea');
      }
      if (!it) return seat('tea');
      if (a.data.tempUntil > scene.realT) return seat(a.data.tempAnim, a.data.tempIcon);
      const openFrom = (model.open_requests || []).find((q) => q.from === d && q.work_item_id === it.id);
      switch (it.status) {
        case 'running': return seat('type');
        case 'asking': {
          const target = openFrom ? openFrom.to : null;
          const right = target && DEPTS.indexOf(target) > DEPTS.indexOf(d);
          return { x: right ? r.outPort - 6 : r.inPort + 6, y: PORT_STAND, seat: null, anim: 'wait', facing: right ? 1 : -1, icon: null };
        }
        case 'waiting_provider': {
          const w = waitingDept(d);
          return seat('sit_wait', { kind: 'hourglass', text: w && w.next_retry_at ? Y8.time.clock(w.next_retry_at) + ' 重试' : '等待' });
        }
        case 'paused': return seat('sit_relax', { kind: 'zzz' });
        case 'failed': return seat('slump');
        case 'done': return { x: r.desk.seatX, y: r.desk.seatY, seat: null, anim: 'cheer' };
        case 'cancelled': return { x: r.desk.seatX, y: r.desk.seatY, seat: null, anim: 'idle' };
        case 'pending_verification': return seat('sit_scratch', { kind: 'question' });
        case 'waiting_resume': return seat('sit_wait', { kind: 'text', text: '待恢复' });
        case 'stopped_for_upgrade': return { x: r.desk.seatX, y: r.desk.seatY, seat: null, anim: 'idle' };
        default: return seat('sit');
      }
    }

    function applyWorker(a) {
      const rest = restFor(a);
      a.dim = dimFor(a.data.item && a.data.item.id);
      const atSpot = Math.hypot(a.x - rest.x, a.y - rest.y) < 1.5 && (rest.seat ? a.seat === rest.seat : !a.seat);
      if (!atSpot) {
        const steps = [];
        if (a.seat) steps.push({ t: 'seat', seat: null }, { t: 'anim', name: 'idle', ms: 120 });
        steps.push({ t: 'go', x: rest.x, y: rest.y });
        if (rest.seat) steps.push({ t: 'seat', seat: rest.seat }, { t: 'turn', facing: 1 });
        if (rest.facing) steps.push({ t: 'turn', facing: rest.facing });
        scene.run(a, steps, {});
        return;
      }
      if (rest.facing) a.facing = rest.facing;
      if (rest.icon) {
        if (!a.icon || a.icon.kind !== rest.icon.kind || a.icon.text !== rest.icon.text) a.icon = Object.assign({ t0: scene.realT }, rest.icon);
      } else a.icon = null;
      scene.play(a, rest.anim);
    }

    function workerOf(d) { return scene.actors.find((a) => a.data.worker && a.data.dept === d) || null; }

    // 小人走到管道口放下或取出包裹
    function portTrip(d, side, anim, after) {
      const a = workerOf(d);
      if (!a || scene.reduced) { if (after) after(); return; }
      const r = roomOf(lay, d);
      const x = side === 'out' ? r.outPort - 6 : r.inPort + 6;
      scene.run(a, [
        { t: 'seat', seat: null }, { t: 'go', x, y: PORT_STAND }, { t: 'turn', facing: side === 'out' ? 1 : -1 },
        { t: 'anim', name: anim, ms: 520, key: true }, { t: 'call', fn: () => { if (after) after(); } }
      ], {});
    }

    function tempWorker(d, anim, icon, ms) {
      const a = workerOf(d);
      if (!a) return;
      a.data.tempAnim = anim; a.data.tempIcon = icon; a.data.tempUntil = scene.realT + (ms || 2200);
    }

    // -------------------------------------------------------------------------
    // 管道中的包裹

    function pathFor(from, to, artifact) {
      const direct = pipes[from + '>' + to];
      if (direct) return { pts: direct.pts, key: direct.key };
      if (artifact === 'defect' || (DEPTS.indexOf(from) > DEPTS.indexOf(to) && DEPTS.includes(to))) {
        if (from === 'quality' && to === 'product') return { pts: pipes['quality>product'].pts, key: 'quality>product' };
        const back = pipes[to + '>' + from];
        if (back) return { pts: back.pts.slice().reverse(), key: back.key };
      }
      const back = pipes[to + '>' + from];
      if (back) return { pts: back.pts.slice().reverse(), key: back.key };
      return null;
    }

    function tubeFor(from, to) {
      const a = pipes[from + '~' + to];
      if (a) return a.pts;
      const b = pipes[to + '~' + from];
      if (b) return b.pts.slice().reverse();
      return null;
    }

    function send(pts, bmp, opt) {
      const option = opt || {};
      if (!pts) { if (option.onDone) option.onDone(); return; }
      if (scene.reduced) {
        st.arrows.push({ pts, color: option.color || PAL.white, bmp, until: scene.realT + 3600, itemId: option.itemId, dash: option.small });
        if (option.onDone) option.onDone();
        return;
      }
      const len = polyLength(pts);
      st.movers.push({ pts, len, bmp, t0: scene.realT, ms: option.ms || Math.max(700, len * 9), itemId: option.itemId, small: option.small, color: option.color, onDone: option.onDone, cross: option.cross });
    }

    function drawMovers(c) {
      st.movers.forEach((m) => {
        const k = Math.min(1, (scene.realT - m.t0) / m.ms);
        const [x, y] = pointAt(m.pts, P.ease.inOut(k) * m.len);
        c.globalAlpha = dimFor(m.itemId);
        if (m.small) {
          RB(c, Math.round(x) - 2, Math.round(y) - 1, 5, 3, PAL.white);
          R(c, Math.round(x) - 1, Math.round(y), 3, 1, m.color || PAL.blue2);
        } else {
          const b = P.bitmap(m.bmp);
          P.drawBitmap(c, m.bmp, Math.round(x - b.w / 2), Math.round(y - b.h / 2));
          if (m.color) R(c, Math.round(x - b.w / 2), Math.round(y + b.h / 2), b.w, 2, m.color);
        }
        c.globalAlpha = 1;
      });
    }

    function updateMovers() {
      const done = st.movers.filter((m) => scene.realT - m.t0 >= m.ms);
      st.movers = st.movers.filter((m) => scene.realT - m.t0 < m.ms);
      done.forEach((m) => { if (m.onDone) m.onDone(); });
    }

    // -------------------------------------------------------------------------
    // 事件

    function flash(id, color, ms) { st.flash[id] = { color, until: scene.realT + (ms || 900) }; }

    function playEvent(ev) {
      if (!ev || !ev.type) throw new Error('playEvent 需要事件对象');
      const pl = ev.payload || {};
      const wid = ev.work_item_id;
      const it = itemById(wid);
      const color = it ? P.ITEM_COLORS[it.color_index % P.ITEM_COLORS.length] : null;
      switch (ev.type) {
        case 'user_input_received':
        case 'work_item_created':
          if (!scene.reduced) scene.fly({ bmp: 'letter', from: [-6, PIPE_Y - 20], to: [lay.hall.x + 16, PIPE_Y + 6], ms: 900, arc: 20, onDone: () => { st.mailFlash = scene.realT + 1500; } });
          else st.mailFlash = scene.realT + 1500;
          return;
        case 'department_activated':
          if (ev.department && roomOf(lay, ev.department)) flash(ev.department, PAL.yellow1, 700);
          return;
        case 'transition': {
          let to = pl.to;
          if (to === 'adopted' || to === 'adoption') to = 'library';
          const from = pl.from;
          const path = pathFor(from, to, pl.artifact);
          if (!path) return;
          const rework = pl.artifact === 'defect' || path.key === 'quality>product' || (DEPTS.includes(from) && DEPTS.includes(to) && DEPTS.indexOf(from) > DEPTS.indexOf(to));
          if (rework) st.pipeFlash[path.key] = scene.realT + 2600;
          const bmp = ART_BMP[pl.artifact] || 'box_sealed';
          const go = () => send(path.pts, bmp, { itemId: wid, color, onDone: () => { flash(to, PAL.white, 500); if (DEPTS.includes(to)) portTrip(to, rework ? 'out' : 'in', 'crouch'); } });
          if (DEPTS.includes(from) || from === 'operations') portTrip(from, rework ? 'in' : 'out', 'side_place', go);
          else go();
          return;
        }
        case 'qa_submitted':
          flash('quality', pl.verdict === 'release' ? PAL.green2 : PAL.red2, 1200);
          tempWorker('quality', pl.verdict === 'release' ? 'sit_happy' : 'sit_scratch', { kind: pl.verdict === 'release' ? 'check' : 'exclaim' }, 1800);
          return;
        case 'collaboration_requested': {
          const pts = tubeFor(pl.from, pl.to);
          portTrip(pl.from, DEPTS.indexOf(pl.to) > DEPTS.indexOf(pl.from) ? 'out' : 'in', 'side_place', () => send(pts, 'letter', { small: true, itemId: wid, color: PAL.blue2 }));
          return;
        }
        case 'collaboration_responded': {
          const pts = tubeFor(pl.to, pl.from);
          portTrip(pl.to, DEPTS.indexOf(pl.from) > DEPTS.indexOf(pl.to) ? 'out' : 'in', 'side_place', () => send(pts, 'letter', { small: true, itemId: wid, color: PAL.green2 }));
          return;
        }
        case 'deliverable_adopted':
          st.shelfFlash = scene.realT + 1800;
          scene.emit('spark', lay.lib.x + lay.lib.w / 2, 110, 16);
          return;
        case 'x_queued':
        case 'x_repair_created':
          st.mailFlash = scene.realT + 1500;
          if (!scene.reduced) scene.fly({ bmp: ev.type === 'x_repair_created' ? 'box_rework' : 'box', from: [lay.hall.x + 16, PIPE_Y + 10], to: [lay.hall.x + 50, PIPE_Y - 4], ms: 700, arc: 14 });
          return;
        case 'x_slot_acquired': {
          st.flash.hall = { color: PAL.green2, until: scene.realT + 900 };
          send(pipes['hall>product'].pts, 'box', { itemId: wid, color, onDone: () => portTrip('product', 'in', 'crouch') });
          return;
        }
        case 'x_queue_reordered':
          st.flash.hall = { color: PAL.blue1, until: scene.realT + 900 };
          return;
        case 'x_run_interrupted':
          return;
        case 'x_run_auto_resumed':
          scene.actors.filter((a) => a.data.worker).forEach((a) => scene.run(a, [{ t: 'anim', name: a.seat ? 'stretch_sit' : 'stretch' }], {}));
          DEPTS.forEach((d) => flash(d, PAL.yellow1, 700));
          return;
        case 'x_action_unknown':
          if (ev.department) flash(ev.department, PAL.yellow2, 1400);
          return;
        case 'x_remote_action_started':
        case 'x_remote_action_finished':
        case 'x_late_receipt': {
          st.doorFlash = scene.realT + 1800;
          const r = ev.department ? roomOf(lay, ev.department) : null;
          if (r && !scene.reduced) {
            const from = ev.type === 'x_remote_action_started' ? [r.door, ROOM_B + 6] : [lay.door.x, CORR_Y];
            const to = ev.type === 'x_remote_action_started' ? [lay.door.x, CORR_Y] : [r.door, ROOM_B + 6];
            st.remoteDots.push({ from, to, t0: scene.realT, ms: 1400 });
          }
          return;
        }
        case 'x_decision_issued':
        case 'x_decision_answered': {
          const d = ev.department || (it && it.department);
          if (d && roomOf(lay, d)) st.decisions[d] = { until: scene.realT + 5000, text: ev.type === 'x_decision_issued' ? '待你决定' : '已回答', itemId: wid, answered: ev.type === 'x_decision_answered' };
          return;
        }
        case 'x_provider_wait_entered':
        case 'x_provider_wait_left':
          if (ev.department) flash(ev.department, ev.type === 'x_provider_wait_entered' ? PAL.grey3 : PAL.yellow1, 900);
          return;
        case 'x_deployed':
          if (lay.ops) send(pipes['operations>machine_room'].pts, 'box_sealed', { onDone: () => { st.doorFlash = scene.realT + 1800; } });
          return;
        case 'x_rolled_back':
          if (lay.ops) send(pipes['operations>machine_room'].pts.slice().reverse(), 'box', { onDone: () => flash('operations', PAL.orange1, 800) });
          return;
        case 'x_fault_recorded':
          if (!lay.ops) return;
          st.monitorFlash = scene.realT + 4000;
          scene.after(scene.reduced ? 0 : 900, () => send(pipes['operations>hall'].pts, 'letter', { color: PAL.red2, onDone: () => { st.mailFlash = scene.realT + 1800; } }));
          return;
        case 'run_done':
          scene.emit('confetti', W / 2, 60, 40, { spread: 560 });
          return;
        default: {
          if (!ev.department || !roomOf(lay, ev.department) || ev.department === 'operations') return;
          const map = {
            model_requested: ['type', { kind: 'think' }], model_stream_progress: ['type', { kind: 'think' }], model_attempt_finished: ['sit_happy', { kind: 'bulb' }],
            model_retry_scheduled: ['sit_wait', { kind: 'hourglass', text: pl.n ? pl.n + '/' + pl.of : null }], model_attempt_failed: ['slump', { kind: 'cross' }],
            tool_started: ['read_sit', null], tool_skipped: ['sit_scratch', { kind: 'cross' }], proposal_rejected: ['sit_scratch', { kind: 'question' }],
            spec_accepted: ['sit_happy', { kind: 'check' }], plan_accepted: ['sit_happy', { kind: 'check' }], delivery_accepted: ['sit_happy', { kind: 'check' }],
            compaction_recorded: ['sit_up', null], department_guidance_received: ['sit_up', { kind: 'exclaim' }]
          };
          const entry = map[ev.type];
          if (entry) tempWorker(ev.department, entry[0], entry[1], 2400);
        }
      }
    }

    // -------------------------------------------------------------------------
    // 更新

    function update() {
      if (!model.interrupted) st.clock += scene.reduced ? 0 : 16.7;
      updateMovers();
      scene.actors.forEach((a) => { if (a.data.worker && !a.script) applyWorker(a); });
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
      const key = lay.ops ? 'ops' : 'base';
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
      DEPTS.forEach((d) => roomShell(c, lay.rooms[d], P.DEPTS[d]));
      roomShell(c, lay.lib, { wall: '#efe6d2', wall2: '#e2d5b8', floor: '#b88a58', floor2: '#a37748', trim: '#6a4a2e' });
      if (lay.ops) roomShell(c, lay.ops, P.DEPTS.operations);
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

    function pipeState(p) {
      if (model.interrupted) return 'stopped';
      const [a, b] = p.key.split(/[>~]/);
      if (waitingDept(a) || waitingDept(b)) return 'stopped';
      const active = (d) => itemsIn(d).some((it) => ACTIVE.includes(it.status));
      if (p.kind === 'tube') return (model.open_requests || []).length ? 'flowing' : 'idle';
      return active(a) || active(b) ? 'flowing' : 'idle';
    }

    function drawPipe(c, p, t) {
      const state = pipeState(p);
      const thick = p.kind === 'tube' ? 3 : 8;
      const flashing = (st.pipeFlash[p.key] || 0) > scene.realT && Math.floor(t / 180) % 2 === 0;
      const outline = PAL.ink;
      const body = flashing ? PAL.red2 : p.kind === 'tube' ? TUBE : state === 'stopped' ? '#9aa0aa' : p.kind === 'return' ? '#c9b48a' : PAL.glass;
      const hi = p.kind === 'tube' ? PAL.white : PAL.white;
      for (let i = 1; i < p.pts.length; i++) {
        const [x0, y0] = p.pts[i - 1], [x1, y1] = p.pts[i];
        const x = Math.min(x0, x1) - thick / 2, y = Math.min(y0, y1) - thick / 2;
        const w = Math.abs(x1 - x0) + thick, h = Math.abs(y1 - y0) + thick;
        RB(c, x, y, w, h, body, outline);
        if (y0 === y1) R(c, x + 1, y + 1, w - 2, 1, hi);
        else R(c, x + 1, y + 1, 1, h - 2, hi);
      }
      // 金属接头
      if (p.kind !== 'tube') p.pts.forEach(([x, y]) => RB(c, x - thick / 2 - 1, y - thick / 2 - 1, thick + 2, thick + 2, PAL.metal3));
      // 流动：沿管道移动的亮点
      if (state === 'flowing' && !scene.reduced && !scene.frozen) {
        const len = polyLength(p.pts);
        const gap = p.kind === 'tube' ? 14 : 22;
        const off = (t / (p.kind === 'tube' ? 30 : 45)) % gap;
        c.fillStyle = p.kind === 'tube' ? TUBE_D : P.rgba(PAL.blue2, 0.55);
        for (let d = off; d < len; d += gap) {
          const [x, y] = pointAt(p.pts, d);
          c.fillRect(Math.round(x) - 1, Math.round(y) - (p.kind === 'tube' ? 0 : 1), 2, p.kind === 'tube' ? 1 : 2);
        }
      }
    }

    function drawPort(c, x, y, kind) {
      if (kind === 'tube') { RB(c, x - 3, y - 4, 6, 8, TUBE_D); R(c, x - 1, y - 2, 2, 4, PAL.ink); return; }
      RB(c, x - 6, y - 8, 12, 16, PAL.metal2);
      R(c, x - 4, y - 5, 8, 10, PAL.ink2);
      R(c, x - 4, y - 5, 8, 1, PAL.metal1);
    }

    function drawPipes(c, t) {
      Object.values(pipes).forEach((p) => drawPipe(c, p, t));
      DEPTS.forEach((d) => {
        const r = lay.rooms[d];
        drawPort(c, r.inPort, PIPE_Y, 'handoff');
        drawPort(c, r.outPort, PIPE_Y, 'handoff');
        drawPort(c, r.inPort, TUBE_Y, 'tube');
        drawPort(c, r.outPort, TUBE_Y, 'tube');
      });
      drawPort(c, lay.lib.inPort, PIPE_Y, 'handoff');
      if (lay.ops) { drawPort(c, lay.ops.inPort, PIPE_Y, 'handoff'); drawPort(c, lay.ops.outPort, PIPE_Y, 'handoff'); }
      // Stage 6 的判定阀门位置：交接管道上的空卡座
      ['product>engineering', 'engineering>quality', 'quality>library'].forEach((key) => {
        const p = pipes[key];
        const mx = Math.round((p.pts[0][0] + p.pts[1][0]) / 2);
        R(c, mx - 3, PIPE_Y - 9, 6, 2, PAL.metal4);
      });
      // 停止流动的说明：等待模型服务
      (model.waiting_provider || []).forEach((w) => {
        const r = roomOf(lay, w.department);
        if (!r) return;
        const text = '等待模型服务' + (w.next_retry_at ? ' · ' + Y8.time.clock(w.next_retry_at) + ' 重试' : '');
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
    function queueSlotX(i) { return lay.rooms.product.inPort - 20 - i * 15; }

    function drawHall(c, t) {
      const hall = lay.hall;
      const x = hall.x;
      P.sign(c, x + 40, TOP + 16, '大厅', { size: 7, bg: PAL.paper, stripe: PAL.wood3 });
      paint.clock(c, x + hall.w - 22, TOP + 6, st.clock, { stopped: model.interrupted });
      // 信箱：用户的输入以信件投进来，管道从这里出发
      RB(c, x + 8, PIPE_Y - 2, 14, 18, PAL.red2);
      R(c, x + 10, PIPE_Y + 1, 10, 2, PAL.ink);
      RB(c, x + 12, PIPE_Y - 7, 6, 3, st.mailFlash > scene.realT ? PAL.yellow2 : PAL.grey4);
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
        if (px < x + 24) return;
        c.globalAlpha = dimFor(it.id);
        P.drawBitmap(c, 'box', px - 6, PIPE_Y - 16);
        R(c, px - 6, PIPE_Y - 4, 12, 2, P.ITEM_COLORS[it.color_index % P.ITEM_COLORS.length]);
        if (it.kind === 'repair') { R(c, px - 1, PIPE_Y - 14, 2, 6, PAL.red2); R(c, px - 3, PIPE_Y - 12, 6, 2, PAL.red2); }
        if (it.queue_pos) P.pixText(c, String(it.queue_pos), px, PIPE_Y - 24, PAL.ink, 'center');
        c.globalAlpha = 1;
      });
      // 入口阀门：等待执行槽位时关闭
      const vx = lay.rooms.product.inPort - 8;
      RB(c, vx - 2, PIPE_Y - 7, 4, 14, PAL.metal3);
      RB(c, vx - 5, PIPE_Y - 12, 10, 3, slotWait ? PAL.red2 : PAL.green2);
      if (slotWait) P.sign(c, x + hall.w / 2 + 6, PIPE_Y + 38, '等待执行槽位', { size: 5.5, bg: PAL.yellow1, stripe: PAL.orange2, maxW: hall.w });
      if ((st.flash.hall || {}).until > scene.realT) paint.blinkFrame(c, x + 26, PIPE_Y - 20, lay.rooms.product.inPort - x - 30, 22);
      // 长椅与植物
      RB(c, x + 30, ROOM_B - 14, 34, 4, PAL.wood2); R(c, x + 32, ROOM_B - 10, 2, 8, PAL.wood4); R(c, x + 60, ROOM_B - 10, 2, 8, PAL.wood4);
      paint.plant(c, x + hall.w - 16, ROOM_B - 2);
    }

    // -------------------------------------------------------------------------
    // 绘制：部门房间、成果库、运维房间

    function drawDeptRoom(c, d, t) {
      const r = roomOf(lay, d);
      const D = P.DEPTS[d];
      const here = itemsIn(d);
      const working = here.some((it) => ACTIVE.includes(it.status));
      const sx = r.x + 30, sy = TOP + 18;
      RB(c, sx - 2, sy - 2, 32, 22, PAL.beige2);
      paint.screen(c, sx, sy, 28, 18, model.interrupted ? 'off' : working ? 'code' : 'idle', t, { seed: r.x });
      paint.scanlines(c, sx, sy, 28, 18, 0.18);
      paint.lamp(c, r.x + r.w - 30, TOP + 8, working, TOP);
      if (d === 'product') { RB(c, r.x + r.w - 34, FLOOR_LINE + 8, 20, 30, PAL.wood3); for (let i = 0; i < 3; i++) R(c, r.x + r.w - 31, FLOOR_LINE + 12 + i * 9, 14, 5, PAL.paper2); }
      if (d === 'engineering') { RB(c, r.x + r.w - 36, FLOOR_LINE + 22, 22, 16, PAL.metal3); P.drawBitmap(c, 'box_sealed', r.x + r.w - 31, FLOOR_LINE + 12); }
      if (d === 'quality') { RB(c, r.x + r.w - 36, FLOOR_LINE + 24, 22, 12, PAL.white2); P.drawBitmap(c, 'magnifier', r.x + r.w - 29, FLOOR_LINE + 14); }
      if (d === 'operations') drawOpsProps(c, r, t);
      const a = workerOf(d);
      if (a) {
        const desk = r.desk;
        paint.chair(c, desk.seatX, desk.seatY, { color: D.shade });
        if (a.seat === desk) P.drawActor(c, scene, a, 'base');
        paint.desk(c, desk.x, desk.seatY, { w: desk.w });
        R(c, desk.x + desk.w - 11, desk.seatY - 9, 9, 6, PAL.ink);
        const it = a.data.item;
        const mode = model.interrupted ? 'off' : it && it.status === 'running' ? 'code' : it && it.status === 'failed' ? 'error' : it && it.status === 'pending_verification' ? 'alert' : 'idle';
        paint.screen(c, desk.x + desk.w - 10, desk.seatY - 8, 7, 4, mode, t, { seed: desk.x });
        if (it) {
          c.globalAlpha = dimFor(it.id);
          R(c, desk.x + 2, desk.seatY - 12, 1, 7, PAL.metal3);
          R(c, desk.x + 3, desk.seatY - 12, 5, 3, P.ITEM_COLORS[it.color_index % P.ITEM_COLORS.length]);
          c.globalAlpha = 1;
        }
        if (a.seat === desk) {
          c.save(); c.beginPath(); c.rect(0, 0, W, desk.seatY); c.clip();
          P.drawActor(c, scene, a, 'front');
          c.restore();
        } else {
          P.drawActor(c, scene, a);
        }
      }
      drawDoor(c, r);
    }

    function drawOpsProps(c, r, t) {
      const fault = (model.ops && model.ops.fault) || st.monitorFlash > scene.realT;
      // 监控屏
      const mx = r.x + r.w - 44, my = TOP + 16;
      RB(c, mx - 2, my - 2, 40, 26, PAL.grey5);
      paint.screen(c, mx, my, 36, 22, fault ? 'error' : 'ok', t, { seed: 3 });
      P.text(c, model.ops && model.ops.version ? '运行 ' + model.ops.version : '监控屏', mx + 18, my + 30, { size: 5.5, weight: 700, align: 'center', color: PAL.white });
      // 备份柜
      RB(c, r.x + 8, FLOOR_LINE + 4, 18, 34, PAL.metal3);
      for (let i = 0; i < 3; i++) RB(c, r.x + 10, FLOOR_LINE + 7 + i * 10, 14, 7, i === 0 ? PAL.green2 : PAL.metal2);
      paint.cart(c, r.x + 30, ROOM_B - 6, {});
      if (model.ops && model.ops.auto_repair_stopped) {
        const ss = P.signStyle('停止自动修复');
        P.sign(c, r.x + r.w / 2, ROOM_B + 26, '停止自动修复', { size: 6, bg: PAL.red2, fg: PAL.white, stripe: PAL.red3, maxW: r.w + 10, nail: ROOM_B + 3 });
        void ss;
      }
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
      adopted.slice(-per).forEach((v, i, arr) => {
        const bx = r.x + 20 + i * 18;
        P.drawBitmap(c, 'box_sealed', bx, FLOOR_LINE - 33);
        RB(c, bx + 1, FLOOR_LINE - 20, 13, 7, PAL.white);
        P.text(c, v, bx + 7.5, FLOOR_LINE - 16.2, { size: 6, weight: 800, align: 'center', color: PAL.green3, max: 13 });
        if (i === arr.length - 1 && st.shelfFlash > scene.realT) paint.blinkFrame(c, bx - 1, FLOOR_LINE - 35, 15, 23);
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
      if (acts || st.doorFlash > scene.realT) {
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
        RB(c, d.x + d.w - w, d.y - h - 4, w, h, PAL.paper);
        lines.forEach((line, i) => P.text(c, line, d.x + d.w - w + 3, d.y - h - 4 + 6 + i * 8, { size: 5.5, weight: 600, color: PAL.ink, max: w - 6 }));
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
      if (!overlay.id || !overlay.data) return;
      c.fillStyle = 'rgba(12,14,30,0.35)';
      c.fillRect(0, BAR, W, H - BAR);
      const label = (x, y, text, bg) => P.sign(c, x, y, text, { size: 6, bg: bg || PAL.white, stripe: PAL.blue2, maxW: 150 });
      const data = overlay.data;
      if (overlay.id === 'flow') {
        (data.segments || []).forEach((s) => {
          const path = pathFor(s.from, s.to, s.kind === 'rework' ? 'defect' : null) || { pts: tubeFor(s.from, s.to) };
          if (!path || !path.pts) return;
          const [x, y] = pointAt(path.pts, polyLength(path.pts) / 2);
          label(x, y - 6, s.count + ' 次 · ' + Y8.time.clock(s.last_at), s.kind === 'rework' ? PAL.red1 : PAL.white);
        });
      } else if (overlay.id === 'waiting') {
        (data.entries || []).forEach((e) => {
          const r = roomOf(lay, e.department) || lay.hall;
          label(r.x + r.w / 2, (e.row || 0) * 14 + TOP + 44, e.text + ' · ' + Y8.time.duration(e.waited_sec), PAL.yellow1);
        });
      } else if (overlay.id === 'recovery') {
        (data.entries || []).forEach((e) => {
          const r = roomOf(lay, e.department);
          if (!r) return;
          label(r.x + r.w / 2, TOP + 44, e.text, e.state === 'pending_verification' ? PAL.yellow1 : PAL.white);
        });
      } else if (overlay.id === 'context_usage') {
        (data.entries || []).forEach((e) => {
          const r = roomOf(lay, e.department);
          if (!r) return;
          const pct = Math.round(e.ratio * 100);
          label(r.x + r.w / 2, DESK_Y - 44, (e.role || '') + ' ' + pct + '%', e.ratio >= 0.8 ? PAL.orange1 : PAL.green1);
        });
      } else if (overlay.id === 'semantic_records') {
        (data.entries || []).forEach((e) => {
          const r = roomOf(lay, e.department);
          if (!r) return;
          label(r.x + r.w / 2, TOP + 44, '有效 ' + e.valid + ' · 冲突 ' + e.conflicts, e.conflicts ? PAL.orange1 : PAL.white);
        });
      }
    }

    // -------------------------------------------------------------------------

    function draw(sc, c) {
      const t = sc.animT;
      c.drawImage(buildBackground(), 0, 0);
      drawHall(c, t);
      DEPTS.forEach((d) => drawDeptRoom(c, d, t));
      drawLibrary(c, t);
      if (lay.ops) drawDeptRoom(c, 'operations', t);
      drawPipes(c, t);
      drawMovers(c);
      drawMachineDoor(c, t);
      sc.drawFlyers(c);
      sc.drawParticles(c);

      // 灯光：未工作的房间调暗、闪光、待核实黄灯、等待模型服务调暗、整层中断变暗
      DEPTS.concat(lay.ops ? ['operations'] : []).forEach((d) => {
        const r = roomOf(lay, d);
        const here = itemsIn(d);
        const lit = here.some((it) => ACTIVE.includes(it.status) || it.status === 'done') || (d === 'operations' && model.ops);
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
      });
      if (lay.ops && ((model.ops && model.ops.fault) || st.monitorFlash > sc.realT)) {
        const k = sc.reduced ? 0.12 : 0.08 + 0.07 * Math.max(0, Math.sin(t / 160));
        c.fillStyle = 'rgba(255,50,50,' + k.toFixed(3) + ')';
        c.fillRect(lay.ops.x, TOP, lay.ops.w, ROOM_B - TOP);
      }
      if (model.interrupted) { c.fillStyle = 'rgba(8,8,24,0.55)'; c.fillRect(0, BAR, W, H - BAR); }

      // 房间名、门口的小旗与门牌
      DEPTS.concat(lay.ops ? ['operations'] : []).forEach((d) => {
        const r = roomOf(lay, d);
        const D = P.DEPTS[d];
        P.sign(c, r.x + r.w / 2, TOP + 4, D.name, { size: 7, bg: D.main, fg: PAL.white, hi: D.light, lo: D.shade, minW: 30 });
        const here = itemsIn(d);
        here.forEach((it, i) => {
          c.globalAlpha = dimFor(it.id);
          P.drawBitmap(c, (Math.floor(t / 320) + i) % 2 && !sc.reduced ? 'flag2' : 'flag', r.door - 22 - i * 9, ROOM_B + 4, { recolor: { X: P.ITEM_COLORS[it.color_index % 6], x: P.ITEM_SHADES[it.color_index % 6] } });
          c.globalAlpha = 1;
        });
        let row = 0;
        here.forEach((it) => {
          if (!it.sign) return;
          const ss = P.signStyle(it.sign);
          const maxW = r.w - 6;
          const w = Math.min(maxW, Math.max(18, P.measure(c, it.sign, 6, 600) + 8));
          c.globalAlpha = dimFor(it.id);
          P.sign(c, r.door + 12 + w / 2 - 20, ROOM_B + 18 + row * 12, it.sign, { size: 6, bg: ss.bg, fg: ss.fg, stripe: ss.stripe, maxW, nail: row === 0 ? ROOM_B + 3 : undefined });
          c.globalAlpha = 1;
          row += 1;
        });
      });
      // 决定请求发出或回答时，门上贴一张小单子
      Object.keys(st.decisions).forEach((d) => {
        const dc = st.decisions[d];
        if (dc.until < sc.realT) { delete st.decisions[d]; return; }
        const r = roomOf(lay, d);
        c.globalAlpha = dimFor(dc.itemId);
        P.drawBitmap(c, 'decision', r.door - 3, ROOM_B - 5);
        P.sign(c, r.door, ROOM_B + 44, dc.text, { size: 5.5, bg: dc.answered ? PAL.green1 : PAL.yellow1, stripe: PAL.blue2, maxW: 90 });
        c.globalAlpha = 1;
      });

      sc.actors.forEach((a) => { if (a.icon) { c.globalAlpha = a.dim; P.drawIcon(c, sc, a); c.globalAlpha = 1; } });

      // 减少动画时的交接箭头
      st.arrows.forEach((ar) => {
        c.globalAlpha = dimFor(ar.itemId);
        P.arrow(c, ar.pts, ar.color, { dash: ar.dash });
        const mid = pointAt(ar.pts, polyLength(ar.pts) / 2);
        const b = P.bitmap(ar.bmp);
        P.drawBitmap(c, ar.bmp, mid[0] - b.w / 2, mid[1] - b.h - 3);
        c.globalAlpha = 1;
      });

      drawOverlay(c);
      drawInfoBar(c);
    }

    function drawInfoBar(c) {
      R(c, 0, 0, W, BAR, '#1f2230');
      R(c, 0, BAR - 1, W, 1, '#3a3f52');
      const it = (focusId && itemById(focusId)) || model.items.find((x) => ACTIVE.includes(x.status) || x.status === 'waiting_provider') || model.items.find((x) => IN_ROOM.includes(x.status)) || null;
      if (!it) { P.text(c, '没有进行中的事项', 8, 9, { size: 7, color: PAL.grey1 }); return; }
      R(c, 6, 5, 8, 8, PAL.ink); R(c, 7, 6, 6, 6, P.ITEM_COLORS[it.color_index % 6]);
      let x = 18;
      x += P.text(c, it.title || it.id, x, 9, { size: 7, weight: 700, color: PAL.white, max: 170 }) + 8;
      const chip = (text, bg, fg) => {
        c.font = '700 6.5px ' + P.FONT;
        const w = c.measureText(text).width + 8;
        R(c, x, 4, w, 10, bg);
        P.text(c, text, x + w / 2, 9, { size: 6.5, weight: 700, align: 'center', color: fg || PAL.ink });
        x += w + 4;
      };
      if (it.cycle) chip('第 ' + it.cycle + ' 轮', PAL.paper);
      if (it.department && P.DEPTS[it.department]) chip('当前部门：' + P.DEPTS[it.department].name, P.DEPTS[it.department].light);
      chip(STATUS_TEXT[it.status] || it.status, STATUS_CHIP[it.status] || PAL.grey2, ['running', 'failed', 'adopted', 'asking'].includes(it.status) ? PAL.white : PAL.ink);
      if (it.limit_sec) {
        const k = Math.min(1, (it.elapsed_sec || 0) / it.limit_sec);
        const wk = Math.min(1 - k, (it.waiting_provider_sec || 0) / it.limit_sec);
        const bw = 110, bx = W - bw - 8;
        const col = k >= 0.95 ? PAL.red2 : k >= 0.8 ? PAL.orange2 : PAL.green2;
        P.text(c, '已用 ' + Math.round((it.elapsed_sec || 0) / 60) + ' 分 / 上限 ' + Math.round(it.limit_sec / 60) + ' 分' + (it.waiting_provider_sec ? ' · 等待 ' + Math.round(it.waiting_provider_sec / 60) + ' 分不计入' : ''),
          bx - 6, 9, { size: 6.5, weight: 600, align: 'right', color: k >= 0.8 ? PAL.orange1 : PAL.grey1 });
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
    // 点击：通往机房的门

    canvas.addEventListener('click', (ev) => {
      const rect = canvas.getBoundingClientRect();
      const x = ((ev.clientX - rect.left) / rect.width) * W;
      const y = ((ev.clientY - rect.top) / rect.height) * H;
      const d = lay.door;
      if (model.machines && x >= d.x - 50 && x <= d.x + d.w && y >= d.y - 40 && y <= d.y + d.h && o.onDoorClick) {
        o.onDoorClick(model.machines.map((m) => m.id));
      }
    });

    // -------------------------------------------------------------------------
    // 接口

    function setModel(m) {
      if (!m || !Array.isArray(m.items)) throw new Error('setModel 需要 floorModel');
      model = Object.assign({ open_requests: [], shelves: { adopted: [] }, slots: null, waiting_provider: [], machines: null, ops: null, interrupted: false }, m);
      const hasOps = Boolean(m.ops);
      if (hasOps !== Boolean(lay.ops)) {
        lay = layoutFor(hasOps);
        pipes = pipesFor(lay);
        bg = null;
        scene.actors.filter((a) => a.data.worker).forEach((a) => scene.removeActor(a));
      }
      if (m.focus_id !== undefined && focusId === null) focusId = m.focus_id;
      syncWorkers();
      scene.frozen = Boolean(model.interrupted);
    }

    syncWorkers();

    return {
      scene,
      setModel,
      playEvent,
      focus(id) { focusId = id || null; },
      setOverlay(id, data) { overlay = { id: id || null, data: data || null }; },
      resize: () => scene.resize(),
      destroy: () => scene.destroy()
    };
  };
})();
