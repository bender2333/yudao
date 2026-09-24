// 循环画面（设计说明第 5 节）：大厅、三个部门房间成环、走廊、成果库、运维房间与观察台、上方信息条。
(function () {
  const Y7 = window.Y7;
  const P = Y7.pixel;
  if (!P || !P.createScene) throw new Error('loop.js 需要先加载 js/pixel/engine.js');
  const PAL = P.PAL;
  const R = P.R, RB = P.RB, paint = P.paint;

  const W = 640, H = 300;
  const TOP = 60;          // 房间上沿
  const ROOM_B = 196;      // 房间下沿（门所在的墙）
  const DESK_Y = 180;      // 房间内桌面前沿
  const CORR_Y = 226;      // 走廊（去程）脚下
  const RET_Y = 262;       // 回程通道脚下
  const HALL_Q = 232;      // 大厅排队的位置
  const DEPTS = ['product', 'engineering', 'quality'];
  const ART_BMP = { prd: 'scroll', box: 'box_sealed', defect: 'box_rework', release: 'box_release', letter: 'letter' };
  const STATUS_TEXT = {
    queued: '排队中', running: '运行中', asking: '询问中', paused: '已暂停', failed: '失败', done: '已完成', cancelled: '已取消',
    interrupted: '中断', pending_verification: '待核实', waiting_resume: '待恢复', adopted: '已采纳', held: '未采纳候选'
  };
  const STATUS_CHIP = {
    running: PAL.green2, asking: PAL.blue2, queued: PAL.grey2, paused: PAL.blue1, failed: PAL.red2, done: PAL.green1,
    cancelled: PAL.grey2, interrupted: PAL.grey3, pending_verification: PAL.yellow2, waiting_resume: PAL.yellow2, adopted: PAL.green3, held: PAL.orange2
  };
  const DOOR_SIGN = { paused: '已暂停', failed: '失败', done: '已完成', cancelled: '已取消', interrupted: '中断', waiting_resume: '待恢复' };
  const IN_ROOM = ['running', 'asking', 'paused', 'failed', 'done', 'cancelled', 'interrupted', 'pending_verification', 'waiting_resume'];

  function layoutFor(level) {
    const s5 = P.levelAtLeast(level, 's5');
    const hallW = s5 ? 92 : 108, roomW = s5 ? 96 : 120, libW = s5 ? 92 : 140, gap = 6;
    let x = 4;
    const hall = { x, w: hallW };
    x += hallW + gap;
    const rooms = {};
    DEPTS.forEach((d) => { rooms[d] = { id: d, x, w: roomW, door: x + Math.round(roomW / 2) }; x += roomW + gap; });
    const lib = { id: 'library', x, w: libW, door: x + 22 };
    x += libW + gap;
    const ops = s5 ? { id: 'operations', x, w: W - 4 - x, door: x + 22 } : null;
    return { hall, rooms, lib, ops, s5 };
  }

  P.createLoopScene = function createLoopScene(canvas, opts) {
    const o = opts || {};
    let level = o.level || 'now';
    P.levelAtLeast(level, 'now');
    let lay = layoutFor(level);
    let model = { level, items: [], focusId: null, slots: { total: 3, used: 0 }, shelves: { adopted: [], held: [] }, openRequests: [], ops: null, observer: null };
    let focusId = null;
    const st = {
      clock: 15.5 * 3600000,
      flash: {}, eventSign: {}, eventStatus: {}, interrupted: false,
      extraAdopted: [], extraHeld: [], shelfFlash: { adopted: 0, held: 0 },
      mailFlash: 0, slotFlash: 0, alarmUntil: 0, rackFlash: 0, rackBox: false,
      observerSign: null, arrows: [], doorOpen: {}, n: 0, lastHandoffX: null, queueArrivals: new Set(), decisions: {}
    };
    const scene = P.createScene(canvas, { W, H, draw, update, maxScale: 5 });
    let bg = null, bgKey = '';

    // -------------------------------------------------------------------------
    // 位置

    function roomOf(id) {
      if (id === 'library' || id === 'adopted' || id === 'adoption') return lay.lib;
      if (id === 'operations') return lay.ops;
      if (id === 'hall') return { id: 'hall', x: lay.hall.x, w: lay.hall.w, door: lay.hall.x + lay.hall.w - 12 };
      return lay.rooms[id] || null;
    }
    function doorX(id) {
      const r = roomOf(id);
      if (!r) throw new Error('循环画面没有这个位置：' + id);
      return r.door;
    }
    function itemById(id) { return model.items.find((it) => it.id === id) || null; }
    function statusOf(it) { return st.eventStatus[it.id] || it.status; }
    function dimFor(itemId) { return focusId && itemId && itemId !== focusId ? 0.28 : 1; }
    function anyInterrupted() { return st.interrupted || model.items.some((it) => statusOf(it) === 'interrupted'); }
    function openDoor(id) { st.doorOpen[id] = scene.realT + 700; }

    // -------------------------------------------------------------------------
    // 房间里的工作者：每个在房间里的事项一个小人

    function syncWorkers() {
      const want = [];
      DEPTS.concat(lay.ops ? ['operations'] : []).forEach((d) => {
        const here = model.items.filter((it) => it.department === d && IN_ROOM.includes(statusOf(it)));
        const cap = lay.s5 ? 2 : 3;
        here.slice(0, cap).forEach((it, i) => want.push({ key: 'w-' + it.id, dept: d, item: it, slot: i, count: Math.min(here.length, cap), extra: Math.max(0, here.length - cap) }));
        if (!here.length) want.push({ key: 'w-idle-' + d, dept: d, item: null, slot: 0, count: 1, extra: 0 });
      });
      const keys = new Set(want.map((w) => w.key));
      scene.actors.filter((a) => a.data.worker && !keys.has(a.id)).forEach((a) => scene.removeActor(a));
      want.forEach((w) => {
        const r = roomOf(w.dept);
        const dw = 34;
        const inner = r.w - 8;
        const total = w.count * dw + (w.count - 1) * 4;
        const dx = r.x + 4 + Math.round((inner - total) / 2) + w.slot * (dw + 4);
        const desk = { x: dx, w: dw, y: DESK_Y, seatX: dx + 12, seatY: DESK_Y };
        let a = scene.actors.find((x) => x.id === w.key);
        const sprite = w.dept === 'operations' ? 'operations.ops' : w.dept + '.agent';
        if (!a) {
          a = scene.addActor({ id: w.key, sprite, x: desk.seatX, y: desk.seatY, anim: 'sit', data: { worker: true } });
          a.seat = desk;
        }
        if (a.seat) a.seat = desk;
        Object.assign(a.data, { desk, dept: w.dept, item: w.item, extra: w.extra });
      });
    }

    function workerRest(a) {
      const it = a.data.item;
      const d = a.data.desk;
      const seat = (anim, icon) => ({ x: d.seatX, y: d.seatY, seat: d, anim, icon });
      if (!it) return seat('tea');
      const s = statusOf(it);
      if (s === 'running') {
        if (a.data.tempUntil > scene.realT) return seat(a.data.tempAnim || 'type', a.data.tempIcon || null);
        return seat('type');
      }
      // 发问方在门口等待：事项状态为询问中，或有从本部门发出、尚未关闭的询问
      const open = (model.openRequests || []).some((r) => r.workItemId === it.id && r.from === a.data.dept);
      if (s === 'asking' || (s === 'running' && open)) return { x: doorX(a.data.dept) - 10, y: ROOM_B + 10, seat: null, anim: 'wait', facing: 1 };
      if (s === 'paused') return seat('sit_relax', { kind: 'zzz' });
      if (s === 'failed') return seat('slump');
      if (s === 'done') return { x: d.seatX, y: d.seatY, seat: null, anim: 'cheer' };
      if (s === 'cancelled') return { x: d.seatX, y: d.seatY, seat: null, anim: 'idle' };
      if (s === 'pending_verification') return seat('sit_scratch', { kind: 'question' });
      if (s === 'waiting_resume') return seat('sit_wait', { kind: 'text', text: '待恢复' });
      return seat('sit');
    }

    function applyWorker(a) {
      const r = workerRest(a);
      a.dim = dimFor(a.data.item && a.data.item.id);
      const atSpot = Math.hypot(a.x - r.x, a.y - r.y) < 1.5 && (r.seat ? a.seat === r.seat : !a.seat);
      if (!atSpot) {
        const steps = [];
        if (a.seat) steps.push({ t: 'seat', seat: null }, { t: 'anim', name: 'idle', ms: 150 });
        const outside = r.y > ROOM_B || a.y > ROOM_B;
        if (outside) {
          const dxr = doorX(a.data.dept);
          if (a.y < ROOM_B) steps.push({ t: 'go', x: dxr, y: ROOM_B - 6 }, { t: 'call', fn: () => openDoor(a.data.dept) }, { t: 'go', x: dxr, y: ROOM_B + 10 });
          else steps.push({ t: 'go', x: dxr, y: ROOM_B + 10 }, { t: 'call', fn: () => openDoor(a.data.dept) }, { t: 'go', x: dxr, y: ROOM_B - 6 });
        }
        steps.push({ t: 'go', x: r.x, y: r.y });
        if (r.seat) steps.push({ t: 'seat', seat: r.seat }, { t: 'turn', facing: 1 });
        if (r.facing) steps.push({ t: 'turn', facing: r.facing });
        scene.run(a, steps, {});
        return;
      }
      if (r.facing) a.facing = r.facing;
      if (r.icon) { if (!a.icon || a.icon.kind !== r.icon.kind) a.icon = Object.assign({ t0: scene.realT }, r.icon); } else a.icon = null;
      scene.play(a, r.anim);
    }

    // 排队的事项：大厅里手持号码牌
    function syncQueue() {
      const q = P.levelAtLeast(level, 's3') ? model.items.filter((it) => statusOf(it) === 'queued').sort((p, q2) => (p.queuePos || 0) - (q2.queuePos || 0)) : [];
      const keys = new Set(q.map((it) => 'q-' + it.id));
      scene.actors.filter((a) => a.data.queue && !keys.has(a.id) && !a.data.leaving).forEach((a) => scene.removeActor(a));
      const hall = lay.hall;
      const spacing = Math.min(15, Math.floor((hall.w - 24) / Math.max(1, q.length)));
      q.forEach((it, i) => {
        const id = 'q-' + it.id;
        let a = scene.actors.find((x) => x.id === id);
        const x = hall.x + hall.w - 14 - i * spacing;
        if (!a) {
          // 由排队事件加入时从大厅入口走进来；画面初次显示时直接站在队伍里
          const walkIn = st.queueArrivals.has(it.id);
          a = scene.addActor({ id, sprite: 'courier.courier:' + it.colorIndex, x: walkIn ? hall.x + 6 : x, y: HALL_Q, anim: 'hold_ticket', data: { queue: true } });
          if (walkIn) {
            st.queueArrivals.delete(it.id);
            a.alpha = 0;
            scene.run(a, [{ t: 'fade', to: 1, ms: 300 }, { t: 'go', x, y: HALL_Q }, { t: 'turn', facing: 1 }], {});
          }
        }
        a.data.item = it;
        a.data.qx = x;
      });
    }

    function applyQueue(a) {
      a.dim = dimFor(a.data.item && a.data.item.id);
      if (Math.abs(a.x - a.data.qx) > 1) {
        scene.run(a, [{ t: 'go', x: a.data.qx, y: HALL_Q }, { t: 'turn', facing: 1 }], {});
        return;
      }
      a.facing = 1;
      scene.play(a, 'hold_ticket');
    }

    // -------------------------------------------------------------------------
    // 送件小人

    function lanePath(fromId, toId, back) {
      const fx = doorX(fromId), tx = doorX(toId);
      const y = back ? RET_Y : CORR_Y;
      const fromIsHall = fromId === 'hall', toIsHall = toId === 'hall';
      const pts = [];
      pts.push([fx, fromIsHall ? HALL_Q : ROOM_B - 6]);
      if (!fromIsHall) pts.push([fx, ROOM_B + 8]);
      pts.push([fx, y]);
      pts.push([tx, y]);
      if (!toIsHall) { pts.push([tx, ROOM_B + 8]); pts.push([tx, ROOM_B - 6]); } else pts.push([tx, HALL_Q]);
      return pts;
    }

    function courier(fromId, toId, bmp, itemId, opt) {
      const it = itemById(itemId);
      const ci = it ? it.colorIndex : (opt && opt.colorIndex);
      const back = Boolean(opt && opt.back);
      const pts = lanePath(fromId, toId, back);
      const mid = [(pts[0][0] + pts[pts.length - 1][0]) / 2, back ? RET_Y : CORR_Y];
      st.lastHandoffX = mid[0];
      if (scene.reduced) {
        st.arrows.push({ pts: pts.slice(1, -1), color: ci !== undefined && ci !== null ? P.ITEM_COLORS[ci] : PAL.white, bmp, until: scene.realT + 3600, itemId });
        if (opt && opt.onDone) opt.onDone();
        return;
      }
      st.n += 1;
      const a = scene.addActor({ id: 'c-' + st.n, sprite: 'courier.courier' + (ci !== undefined && ci !== null ? ':' + ci : ''), x: pts[0][0], y: pts[0][1], alpha: 0, hold: bmp, speed: 58, data: { courier: true, item: it } });
      const steps = [{ t: 'call', fn: () => openDoor(fromId) }, { t: 'fade', to: 1, ms: 220 }];
      pts.slice(1).forEach((p, i) => {
        if (i === pts.length - 2 && toId !== 'hall') steps.push({ t: 'call', fn: () => openDoor(toId) });
        steps.push({ t: 'go', x: p[0], y: p[1], gait: bmp ? 'carry' : 'walk' });
      });
      steps.push({ t: 'fade', to: 0, ms: 220 }, { t: 'call', fn: () => { if (opt && opt.onDone) opt.onDone(); scene.removeActor(a); } });
      scene.run(a, steps, {});
    }

    function plane(fromId, toId, itemId) {
      const fx = doorX(fromId), tx = doorX(toId);
      const it = itemById(itemId);
      st.lastHandoffX = (fx + tx) / 2;
      if (scene.reduced) {
        st.arrows.push({ pts: [[fx, ROOM_B + 6], [tx, ROOM_B + 6]], color: PAL.white, bmp: 'plane', until: scene.realT + 3600, dash: true, itemId });
        return;
      }
      scene.fly({ bmp: 'plane', frames: ['plane', 'plane2'], from: [fx, ROOM_B + 4], to: [tx, ROOM_B + 4], ms: 1400 + Math.abs(tx - fx) * 3, arc: 34, flip: tx < fx, alpha: dimFor(it && it.id) });
    }

    // -------------------------------------------------------------------------
    // 事件

    function flash(roomId, color, ms) { st.flash[roomId] = { color, until: scene.realT + (ms || 900) }; }

    function workerFor(ev) {
      const list = scene.actors.filter((a) => a.data.worker && a.data.dept === ev.department);
      return list.find((a) => a.data.item && a.data.item.id === ev.workItemId) || list[0] || null;
    }
    function tempWorker(ev, anim, icon, ms) {
      const a = workerFor(ev);
      if (!a) return;
      a.data.tempAnim = anim; a.data.tempIcon = icon; a.data.tempUntil = scene.realT + (ms || 2200);
    }

    function playEvent(ev) {
      if (!ev || !ev.type) throw new Error('playEvent 需要事件对象');
      const pl = ev.payload || {};
      const wid = ev.workItemId;
      switch (ev.type) {
        case 'user_input_received':
        case 'work_item_created': {
          const hall = lay.hall;
          if (!scene.reduced) scene.fly({ bmp: 'letter', from: [-6, 208], to: [hall.x + 10, 214], ms: 900, arc: 20, onDone: () => { st.mailFlash = scene.realT + 1500; } });
          else st.mailFlash = scene.realT + 1500;
          return;
        }
        case 'department_activated':
          if (ev.department && roomOf(ev.department)) flash(ev.department, PAL.yellow1, 700);
          tempWorker(ev, 'type', null, 1500);
          return;
        case 'transition': {
          const from = pl.from, art = pl.artifact || 'box';
          let to = pl.to;
          if (!to || to === 'adopted' || to === 'adoption') to = 'library';
          if (!roomOf(from) || !roomOf(to)) return;
          const back = art === 'defect' || DEPTS.indexOf(to) >= 0 && DEPTS.indexOf(from) > DEPTS.indexOf(to);
          courier(from, to, ART_BMP[art] || 'box', wid, { back, onDone: () => flash(to, PAL.white, 500) });
          return;
        }
        case 'qa_submitted':
          flash('quality', pl.verdict === 'release' ? PAL.green2 : PAL.red2, 1200);
          tempWorker(ev, pl.verdict === 'release' ? 'sit_happy' : 'sit_scratch', { kind: pl.verdict === 'release' ? 'check' : 'exclaim' }, 1800);
          return;
        case 'collaboration_requested':
          if (roomOf(pl.from) && roomOf(pl.to)) plane(pl.from, pl.to, wid);
          return;
        case 'collaboration_responded':
          if (roomOf(pl.from) && roomOf(pl.to)) plane(pl.to, pl.from, wid);
          return;
        case 'collaboration_closed':
          return;
        case 'deliverable_adopted': {
          const v = pl.version;
          if (v && !(model.shelves.adopted || []).includes(v) && !st.extraAdopted.includes(v)) st.extraAdopted.push(v);
          st.shelfFlash.adopted = scene.realT + 1800;
          scene.emit('spark', lay.lib.x + lay.lib.w / 2, 108, 16);
          return;
        }
        case 'adoption_held': {
          const label = pl.label || wid || '候选';
          if (!(model.shelves.held || []).some((h) => h.label === label || h.id === wid)) st.extraHeld.push({ id: wid, label });
          st.shelfFlash.held = scene.realT + 1800;
          return;
        }
        case 'x_queued':
          st.eventStatus[wid] = 'queued';
          st.queueArrivals.add(wid);
          syncQueue();
          return;
        case 'x_slot_acquired': {
          st.slotFlash = scene.realT + 1400;
          const a = scene.actors.find((x) => x.id === 'q-' + wid);
          if (a && !scene.reduced) {
            a.data.leaving = true;
            const tx = doorX('product');
            scene.run(a, [{ t: 'go', x: lay.hall.x + lay.hall.w + 4, y: CORR_Y }, { t: 'go', x: tx, y: CORR_Y }, { t: 'call', fn: () => openDoor('product') }, { t: 'go', x: tx, y: ROOM_B - 6 }, { t: 'fade', to: 0, ms: 200 }, { t: 'call', fn: () => scene.removeActor(a) }], {});
          }
          delete st.eventStatus[wid];
          return;
        }
        case 'x_queue_cancelled': {
          const a = scene.actors.find((x) => x.id === 'q-' + wid);
          if (a) {
            a.data.leaving = true;
            scene.run(a, [{ t: 'go', x: lay.hall.x + 2, y: HALL_Q }, { t: 'fade', to: 0, ms: 300 }, { t: 'call', fn: () => scene.removeActor(a) }], {});
          }
          return;
        }
        case 'x_run_interrupted':
          st.interrupted = true;
          if (wid) st.eventStatus[wid] = 'interrupted';
          applyFreeze();
          return;
        case 'x_action_unknown':
          if (wid) st.eventStatus[wid] = 'pending_verification';
          st.interrupted = false;
          applyFreeze();
          return;
        case 'x_action_decided': {
          // 用户作出决定：待核实结束，房间门口出现一张小的决定单
          const choice = pl.choice || 'accept_current';
          if (wid) st.eventStatus[wid] = choice === 'stop' ? 'cancelled' : 'running';
          const it = itemById(wid);
          const d = ev.department || (it && it.department);
          const words = { rerun: '决定：重新执行', accept_current: '决定：按当前状态继续', stop: '决定：停止事项' }[choice] || choice;
          if (d && roomOf(d)) st.decisions[d] = { until: scene.realT + 5000, text: words, itemId: wid };
          applyFreeze();
          return;
        }
        case 'x_waiting_resume':
          if (wid) { st.eventStatus[wid] = 'waiting_resume'; st.eventSign[wid] = '待恢复' + (pl.missing ? '：' + pl.missing : ''); }
          st.interrupted = false;
          applyFreeze();
          return;
        case 'x_resume_accepted':
          st.interrupted = false;
          if (wid) { st.eventStatus[wid] = 'running'; delete st.eventSign[wid]; }
          applyFreeze();
          scene.actors.filter((a) => a.data.worker && (!wid || (a.data.item && a.data.item.id === wid))).forEach((a) => {
            scene.run(a, [{ t: 'anim', name: a.seat ? 'stretch_sit' : 'stretch' }], {});
          });
          if (ev.department) flash(ev.department, PAL.yellow1, 700);
          return;
        case 'run_done': case 'run_failed': case 'run_paused': case 'cancellation_recorded': {
          const map = { run_done: 'done', run_failed: 'failed', run_paused: 'paused', cancellation_recorded: 'cancelled' };
          const cancelled = ev.type === 'run_failed' && P.resolveAction(ev) === 'cancelled';
          if (wid) {
            st.eventStatus[wid] = cancelled ? 'cancelled' : map[ev.type];
            if (ev.type === 'run_failed' && !cancelled && (pl.reason || pl.stopReason)) st.eventSign[wid] = '失败：' + (pl.reason || pl.stopReason);
          }
          if (ev.type === 'run_done') scene.emit('confetti', W / 2, 60, 40, { spread: 560 });
          applyFreeze();
          return;
        }
        case 'x_ops_released':
          if (!lay.ops) return;
          st.rackBox = true;
          scene.after(scene.reduced ? 0 : 2600, () => { st.rackBox = false; st.rackFlash = scene.realT + 1800; });
          return;
        case 'x_ops_alarm':
          if (!lay.ops) return;
          st.alarmUntil = scene.realT + 8000;
          scene.after(scene.reduced ? 0 : 1600, () => courier('operations', 'hall', 'letter', wid, { back: true, onDone: () => { st.mailFlash = scene.realT + 1800; } }));
          return;
        case 'x_judgment_recorded': {
          if (!lay.s5) return;
          const res = pl.result || 'uncertain';
          const text = ({ pass: '通过', fail: '不通过', uncertain: '不确定', passed: '通过', failed: '不通过' }[res] || res) + (pl.confidence !== undefined ? ' · ' + Number(pl.confidence).toFixed(2) : '');
          const x = pl.from && pl.to && roomOf(pl.from) && roomOf(pl.to) ? (doorX(pl.from) + doorX(pl.to)) / 2 : (st.lastHandoffX || W / 2);
          st.observerSign = { text, until: scene.realT + 5200, x };
          return;
        }
        default: {
          const action = P.resolveAction(ev);
          if (!action || !ev.department) return;
          const iconMap = { type_think: { kind: 'think' }, stream_text: { kind: 'think' }, idea: { kind: 'bulb' }, retry_wait: { kind: 'hourglass' }, slump: { kind: 'cross' }, toss: { kind: 'cross' }, returned: { kind: 'question' }, stamp_valid: { kind: 'check' }, seal: { kind: 'check' } };
          const animMap = { read: 'read_sit', write: 'write', slump: 'slump', idea: 'sit_happy', retry_wait: 'sit_wait', search: 'sit_up', inspect: 'read_sit', returned: 'sit_scratch' };
          tempWorker(ev, animMap[action] || 'type', iconMap[action] || null, 2400);
        }
      }
    }

    // 事件改变了事项的状态：重新排出工作者与排队的人，并决定整层是否停住
    function applyFreeze() {
      syncWorkers();
      syncQueue();
      scene.frozen = anyInterrupted();
    }

    // -------------------------------------------------------------------------
    // 更新

    function update() {
      if (!anyInterrupted()) st.clock += scene.reduced ? 0 : 16.7;
      scene.actors.forEach((a) => {
        if (a.data.worker && !a.script) applyWorker(a);
        if (a.data.queue && !a.script && !a.data.leaving) applyQueue(a);
        if (a.data.courier) a.dim = dimFor(a.data.item && a.data.item.id);
      });
      st.arrows = st.arrows.filter((ar) => ar.until > scene.realT);
    }

    // -------------------------------------------------------------------------
    // 背景

    function buildBackground() {
      const key = level;
      if (bg && bgKey === key) return bg;
      bgKey = key;
      bg = P.makeCanvas(W, H);
      const c = bg.getContext('2d');
      c.imageSmoothingEnabled = false;
      // 天空与楼顶
      R(c, 0, 0, W, 60, '#9fd0ee');
      R(c, 0, 34, W, 26, '#b8ddf3');
      [[30, 28], [180, 24], [420, 30], [560, 22]].forEach(([x, y]) => { R(c, x, y, 26, 5, PAL.white); R(c, x + 6, y - 3, 14, 3, PAL.white); });
      R(c, 0, 52, W, 8, '#6f7a8c'); R(c, 0, 52, W, 1, '#8e98a9');
      // 楼层外墙、走廊、回程通道、地面
      R(c, 0, TOP - 2, W, 222, '#4d5466');
      R(c, 0, ROOM_B, W, 48, '#d8cfbd');
      for (let x = 0; x < W; x += 16) R(c, x, ROOM_B, 1, 48, '#cbc1ad');
      R(c, 0, 244, W, 34, '#c9bfa9');
      for (let x = 8; x < W; x += 16) R(c, x, 244, 1, 34, '#bdb29b');
      R(c, 0, 244, W, 1, '#b3a78e');
      R(c, 0, 278, W, 4, '#4d5466');
      R(c, 0, 282, W, 18, '#7fae62');
      for (let x = 0; x < W; x += 6) R(c, x + (x % 12 ? 2 : 0), 282, 2, 2, '#6c9a52');
      // 回程通道边上的花盆与长椅
      for (let x = lay.hall.x + lay.hall.w + 40, i = 0; x < W - 30; x += 96, i++) {
        if (i % 2) {
          RB(c, x, 268, 30, 4, PAL.wood2); R(c, x + 2, 272, 2, 5, PAL.wood4); R(c, x + 26, 272, 2, 5, PAL.wood4);
        } else {
          P.drawBitmap(c, 'plant', x, 259);
        }
      }
      // 环形路线：去程向右，回程向左
      const x0 = lay.rooms.product.door - 8;
      const x1 = lay.rooms.quality.door + 8;
      const ringCol = 'rgba(255,255,255,0.55)';
      for (let x = x0; x < lay.lib.door; x += 8) R(c, x, 238, 4, 1, ringCol);
      for (let x = x0; x < x1; x += 8) R(c, x, 250, 4, 1, ringCol);
      for (let y = 238; y <= 250; y += 3) { R(c, x0 - 2, y, 1, 2, ringCol); R(c, x1 + 2, y, 1, 2, ringCol); }
      for (let x = x0 + 30; x < lay.lib.door - 10; x += 60) { R(c, x, 236, 1, 5, ringCol); R(c, x + 1, 237, 1, 3, ringCol); R(c, x + 2, 238, 1, 1, ringCol); }
      for (let x = x0 + 50; x < x1 - 10; x += 60) { R(c, x + 2, 248, 1, 5, ringCol); R(c, x + 1, 249, 1, 3, ringCol); R(c, x, 250, 1, 1, ringCol); }
      // 大厅
      const hall = lay.hall;
      R(c, hall.x, TOP, hall.w, 136, '#e9e2d2');
      for (let y = TOP + 8; y < ROOM_B - 36; y += 14) R(c, hall.x, y, hall.w, 1, '#ddd4c1');
      R(c, hall.x, ROOM_B - 36, hall.w, 36, '#c9a77a');
      for (let x = hall.x; x < hall.x + hall.w; x += 10) R(c, x, ROOM_B - 36, 1, 36, '#b8966a');
      R(c, hall.x, ROOM_B - 37, hall.w, 2, '#8f7050');
      RB(c, hall.x, TOP, hall.w, 2, '#3a3f4c');
      // 大厅的入口（左墙开口）
      R(c, 0, ROOM_B, 4, 48, '#d8cfbd');
      // 三个部门房间、成果库、运维房间的外壳
      DEPTS.forEach((d) => roomShell(c, lay.rooms[d], P.DEPTS[d]));
      roomShell(c, lay.lib, { wall: '#efe6d2', wall2: '#e2d5b8', floor: '#b88a58', floor2: '#a37748', trim: '#6a4a2e' });
      if (lay.ops) roomShell(c, lay.ops, P.DEPTS.operations);
      return bg;
    }

    function roomShell(c, r, D) {
      const x = r.x, w = r.w;
      R(c, x, TOP, w, ROOM_B - TOP, D.wall);
      for (let yy = TOP + 6; yy < 148; yy += 10) R(c, x + 4, yy, w - 8, 1, D.wall2);
      R(c, x, 148, w, ROOM_B - 148, D.floor);
      for (let yy = 152; yy < ROOM_B; yy += 8) R(c, x, yy, w, 1, D.floor2 || D.floor);
      R(c, x, 146, w, 3, D.trim);
      // 外墙
      R(c, x - 2, TOP - 2, w + 4, 4, '#2e3240');
      R(c, x - 2, TOP - 2, 4, ROOM_B - TOP + 6, '#2e3240');
      R(c, x + w - 2, TOP - 2, 4, ROOM_B - TOP + 6, '#2e3240');
      R(c, x - 2, ROOM_B - 2, w + 4, 6, '#2e3240');
      R(c, x - 2, ROOM_B - 2, w + 4, 1, '#515868');
    }

    // -------------------------------------------------------------------------
    // 绘制

    function drawRoomDoor(c, r) {
      const dx = r.door - 9;
      const open = (st.doorOpen[r.id] || 0) > scene.realT;
      R(c, dx - 1, ROOM_B - 3, 20, 7, PAL.ink);
      R(c, dx, ROOM_B - 2, 18, 5, open ? '#3a3226' : PAL.wood2);
      if (!open) { R(c, dx + 1, ROOM_B - 2, 16, 1, PAL.wood1); R(c, dx + 13, ROOM_B, 2, 2, PAL.yellow2); }
      else R(c, dx, ROOM_B - 2, 3, 5, PAL.wood2);
    }

    function drawDeptRoom(c, d, t) {
      const r = roomOf(d);
      const D = P.DEPTS[d];
      const here = model.items.filter((it) => it.department === d && IN_ROOM.includes(statusOf(it)));
      const working = here.some((it) => ['running', 'asking', 'pending_verification'].includes(statusOf(it)));
      // 墙上小屏幕与吊灯
      const sx = r.x + 8, sy = TOP + 12;
      RB(c, sx - 2, sy - 2, 32, 22, PAL.beige2);
      paint.screen(c, sx, sy, 28, 18, anyInterrupted() ? 'off' : working ? 'code' : 'idle', t, { seed: r.x });
      paint.scanlines(c, sx, sy, 28, 18, 0.18);
      paint.lamp(c, r.x + r.w - 26, TOP + 8, working, TOP);
      // 部门的小物件
      if (d === 'product') { RB(c, r.x + r.w - 30, 110, 22, 34, PAL.wood3); for (let i = 0; i < 3; i++) R(c, r.x + r.w - 27, 114 + i * 10, 16, 6, PAL.paper2); }
      if (d === 'engineering') { RB(c, r.x + r.w - 32, 128, 24, 18, PAL.metal3); P.drawBitmap(c, 'box_sealed', r.x + r.w - 26, 118); }
      if (d === 'quality') { RB(c, r.x + r.w - 32, 132, 24, 14, PAL.white2); P.drawBitmap(c, 'magnifier', r.x + r.w - 24, 122); }
      if (d === 'operations') {
        paint.rack(c, r.x + r.w - 62, 146, { on: model.ops ? model.ops.running !== false : true, alarm: alarmOn(), h: 56, seed: 1, label: model.ops && model.ops.version ? model.ops.version : null, blink: scene.realT < st.rackFlash }, t);
        paint.rack(c, r.x + r.w - 32, 146, { on: model.ops ? model.ops.running !== false : true, alarm: alarmOn(), h: 56, seed: 2 }, t);
        paint.beacon(c, r.x + r.w - 52, 80, { on: alarmOn(), color: 'red' }, t);
        const cx = st.rackBox ? r.x + 16 + Math.min(1, (scene.realT % 2600) / 2600) * 30 : r.x + 10;
        paint.cart(c, Math.round(cx), 192, { box: st.rackBox ? 'box_sealed' : null });
      }
      // 工位与小人
      const workers = scene.actors.filter((a) => a.data.worker && a.data.dept === d);
      workers.forEach((a) => {
        const desk = a.data.desk;
        paint.chair(c, desk.seatX, desk.y, { color: D.shade });
        if (a.seat === desk) P.drawActor(c, scene, a, 'base');
        paint.desk(c, desk.x, desk.y, { w: desk.w });
        R(c, desk.x + desk.w - 11, desk.y - 9, 9, 6, PAL.ink); R(c, desk.x + desk.w - 10, desk.y - 8, 7, 4, PAL.grey4);
        R(c, desk.x + desk.w - 12, desk.y - 3, 11, 2, PAL.grey3);
        const it = a.data.item;
        const s = it ? statusOf(it) : null;
        const lmode = anyInterrupted() ? 'off' : s === 'running' ? 'code' : s === 'failed' ? 'error' : s === 'pending_verification' ? 'alert' : 'idle';
        paint.screen(c, desk.x + desk.w - 10, desk.y - 8, 7, 4, lmode, t, { seed: desk.x });
        if (it) {
          const col = P.ITEM_COLORS[it.colorIndex];
          c.globalAlpha = dimFor(it.id);
          R(c, desk.x + 2, desk.y - 12, 1, 7, PAL.metal3);
          R(c, desk.x + 3, desk.y - 12, 5, 3, col);
          c.globalAlpha = 1;
        }
        if (a.seat === desk) {
          c.save(); c.beginPath(); c.rect(0, 0, W, desk.y); c.clip();
          P.drawActor(c, scene, a, 'front');
          c.restore();
        }
        if (a.data.extra) P.text(c, '+' + a.data.extra, r.x + r.w - 10, desk.y + 6, { size: 6, weight: 700, color: PAL.white, align: 'center' });
      });
      drawRoomDoor(c, r);
    }

    function drawHall(c, t) {
      const hall = lay.hall;
      const x = hall.x;
      // 信箱（左墙）
      RB(c, x + 3, ROOM_B + 6, 10, 12, PAL.red2);
      R(c, x + 4, ROOM_B + 8, 8, 2, PAL.ink);
      const lit = st.mailFlash > scene.realT;
      RB(c, x + 6, ROOM_B + 1, 4, 3, lit ? PAL.yellow2 : PAL.grey4);
      P.text(c, '信箱', x + 8, ROOM_B + 24, { size: 5.5, weight: 700, align: 'center', color: PAL.ink2 });
      // 挂钟
      paint.clock(c, x + hall.w - 22, TOP + 8, st.clock, { stopped: anyInterrupted() });
      // 大厅名牌
      P.sign(c, x + 34, TOP + 22, '大厅', { size: 7, bg: PAL.paper, stripe: PAL.wood3 });
      // 执行槽位灯（3.4A）
      if (P.levelAtLeast(level, 's3')) {
        const slots = model.slots || { total: 3, used: 0 };
        const total = Math.max(1, slots.total || 0);
        const used = Array.isArray(slots.used) ? slots.used.length : (slots.used || 0);
        const pw = Math.min(hall.w - 12, 10 + total * 11);
        RB(c, x + 6, TOP + 34, pw, 30, PAL.grey5);
        P.text(c, '执行槽位 ' + used + '/' + total, x + 6 + pw / 2, TOP + 40, { size: 5.5, weight: 700, align: 'center', color: PAL.white, max: pw - 4 });
        for (let i = 0; i < total; i++) {
          const on = i < used;
          const lx = x + 11 + i * 11, ly = TOP + 48;
          RB(c, lx, ly, 7, 7, on ? PAL.green2 : PAL.grey4);
          if (on) R(c, lx + 1, ly + 1, 2, 2, PAL.green1);
        }
        if (st.slotFlash > scene.realT) paint.blinkFrame(c, x + 6, TOP + 34, pw, 30);
      }
      // 长椅与植物
      RB(c, x + 8, ROOM_B - 14, 34, 4, PAL.wood2); R(c, x + 10, ROOM_B - 10, 2, 8, PAL.wood4); R(c, x + 38, ROOM_B - 10, 2, 8, PAL.wood4);
      paint.plant(c, x + hall.w - 18, ROOM_B - 2);
    }

    function drawLibrary(c, t) {
      const r = lay.lib;
      const x = r.x;
      P.sign(c, x + r.w / 2, TOP + 20, '成果库', { size: 7, bg: PAL.paper, stripe: PAL.green3 });
      // 已采纳架
      const adopted = (model.shelves && model.shelves.adopted || []).concat(st.extraAdopted);
      P.text(c, '已采纳', x + 8, TOP + 32, { size: 6, weight: 700, color: PAL.green3 });
      paint.shelf(c, x + 6, 112, r.w - 12);
      const per = Math.max(1, Math.floor((r.w - 16) / 18));
      adopted.slice(-per).forEach((v, i, arr) => {
        const bx = x + 9 + i * 18;
        P.drawBitmap(c, 'box_sealed', bx, 103);
        RB(c, bx + 1, 116, 13, 7, PAL.white);
        P.pixText(c, v, bx + 7.5, 117, PAL.green3, 'center');
        if (i === arr.length - 1 && st.shelfFlash.adopted > scene.realT) paint.blinkFrame(c, bx - 1, 101, 15, 23);
      });
      // 未采纳候选架（3.4B）
      if (P.levelAtLeast(level, 's3')) {
        const held = (model.shelves && model.shelves.held || []).concat(st.extraHeld);
        P.text(c, '未采纳候选', x + 8, 132, { size: 6, weight: 700, color: PAL.orange2 });
        paint.shelf(c, x + 6, 168, r.w - 12);
        const per2 = Math.max(1, Math.floor((r.w - 16) / 30));
        held.slice(-per2).forEach((h, i, arr) => {
          const bx = x + 9 + i * 30;
          P.drawBitmap(c, 'box', bx, 159);
          R(c, bx + 3, 162, 7, 3, PAL.yellow2);
          RB(c, bx - 2, 172, 28, 8, PAL.yellow1);
          P.text(c, '基线已变', bx + 12, 176, { size: 5.5, weight: 700, align: 'center', color: PAL.ink, max: 26 });
          if (i === arr.length - 1 && st.shelfFlash.held > scene.realT) paint.blinkFrame(c, bx - 2, 157, 28, 24);
        });
      }
      drawRoomDoor(c, r);
    }

    function drawDeck(c, t) {
      // 观察台（Stage 5）：楼层上方的走廊与栏杆
      R(c, 0, 18, W, 34, '#c5d7e6');
      R(c, 0, 44, W, 8, '#8e98a9');
      R(c, 0, 44, W, 1, '#aeb7c5');
      for (let x = 4; x < W; x += 14) R(c, x, 30, 2, 14, '#6f7a8c');
      R(c, 0, 30, W, 2, '#6f7a8c');
      P.sign(c, 36, 30, '观察台', { size: 6.5, bg: PAL.white, stripe: P.DEPTS.meta.main });
    }

    function alarmOn() { return Boolean(lay.ops) && (st.alarmUntil > scene.realT || Boolean(model.ops && model.ops.alarm)); }

    function draw(sc, c) {
      const t = sc.animT;
      c.drawImage(buildBackground(), 0, 0);
      if (lay.s5) drawDeck(c, t);
      drawHall(c, t);
      DEPTS.forEach((d) => drawDeptRoom(c, d, t));
      drawLibrary(c, t);
      if (lay.ops) drawDeptRoom(c, 'operations', t);

      // 走廊上的小人
      const walkers = sc.actors.filter((a) => !a.seat && (!a.data.worker || a.y > ROOM_B - 8) && !a.data.observer).sort((p, q) => p.y - q.y);
      const inside = sc.actors.filter((a) => a.data.worker && !a.seat && a.y <= ROOM_B - 8);
      inside.forEach((a) => P.drawActor(c, sc, a));
      walkers.forEach((a) => P.drawActor(c, sc, a));
      sc.drawFlyers(c);
      sc.drawParticles(c);

      // 灯光：房间暗、闪光、待核实黄灯、告警红光、整层中断变暗
      DEPTS.concat(lay.ops ? ['operations'] : []).forEach((d) => {
        const r = roomOf(d);
        const here = model.items.filter((it) => it.department === d && IN_ROOM.includes(statusOf(it)));
        const lit = here.some((it) => ['running', 'asking', 'pending_verification', 'done'].includes(statusOf(it))) || (d === 'operations' && model.ops && model.ops.running);
        if (!lit) { c.fillStyle = 'rgba(14,12,34,0.34)'; c.fillRect(r.x, TOP, r.w, ROOM_B - TOP); }
        if (here.some((it) => statusOf(it) === 'pending_verification')) {
          const k = sc.reduced ? 0.14 : 0.1 + 0.08 * Math.sin(t / 240);
          c.fillStyle = 'rgba(255,196,40,' + k.toFixed(3) + ')';
          c.fillRect(r.x, TOP, r.w, ROOM_B - TOP);
        }
        const fl = st.flash[d];
        if (fl && fl.until > sc.realT) {
          const k = (fl.until - sc.realT) / 900;
          c.fillStyle = P.rgba(fl.color, Math.min(0.35, k * 0.35));
          c.fillRect(r.x, TOP, r.w, ROOM_B - TOP);
        }
      });
      if (alarmOn()) {
        const k = sc.reduced ? 0.12 : 0.08 + 0.08 * Math.max(0, Math.sin(t / 160));
        c.fillStyle = 'rgba(255,50,50,' + k.toFixed(3) + ')';
        c.fillRect(lay.ops.x, TOP, lay.ops.w, ROOM_B - TOP);
      }
      if (anyInterrupted()) { c.fillStyle = 'rgba(8,8,24,0.55)'; c.fillRect(0, 18, W, H - 18); }

      // 发光：待核实的黄灯、告警灯
      DEPTS.concat(lay.ops ? ['operations'] : []).forEach((d) => {
        const r = roomOf(d);
        const here = model.items.filter((it) => it.department === d && IN_ROOM.includes(statusOf(it)));
        if (here.some((it) => statusOf(it) === 'pending_verification')) {
          paint.beacon(c, r.x + r.w - 14, TOP + 4, { on: true }, t);
          paint.beaconLight(c, r.x + r.w - 14, TOP + 4, { on: true, reduced: sc.reduced, len: 60 }, t);
        }
      });
      if (alarmOn()) paint.beaconLight(c, lay.ops.x + lay.ops.w - 52, 80, { on: true, color: 'red', reduced: sc.reduced, len: 90 }, t);

      // 门牌、小旗、房间名
      DEPTS.concat(lay.ops ? ['operations'] : []).forEach((d) => {
        const r = roomOf(d);
        const D = P.DEPTS[d];
        P.sign(c, r.x + r.w / 2, TOP + 4, D.name, { size: 7, bg: D.main, fg: PAL.white, hi: D.light, lo: D.shade, minW: 30 });
        const here = model.items.filter((it) => it.department === d && IN_ROOM.includes(statusOf(it)));
        here.forEach((it, i) => {
          const fx = r.door - 18 - i * 9;
          c.globalAlpha = dimFor(it.id);
          P.drawBitmap(c, (Math.floor(t / 320) + i) % 2 && !sc.reduced ? 'flag2' : 'flag', fx, ROOM_B + 4, { recolor: { X: P.ITEM_COLORS[it.colorIndex], x: P.ITEM_SHADES[it.colorIndex] } });
          c.globalAlpha = 1;
        });
        let sx = r.door + 12;
        here.forEach((it) => {
          const s = statusOf(it);
          let text = st.eventSign[it.id] || it.sign || DOOR_SIGN[s];
          if (s === 'waiting_resume' && !st.eventSign[it.id] && it.sign) text = it.sign;
          if (!text || !DOOR_SIGN[s]) return;
          const ss = P.signStyle(text);
          c.globalAlpha = dimFor(it.id);
          const box = P.sign(c, sx + 18, ROOM_B + 17, text, { size: 6, bg: ss.bg, fg: ss.fg, stripe: ss.stripe, maxW: lay.s5 ? 58 : 76, nail: ROOM_B + 3 });
          c.globalAlpha = 1;
          sx += box.w + 3;
        });
      });

      // 作出决定后，房间门上贴一张小的决定单
      Object.keys(st.decisions).forEach((d) => {
        const dc = st.decisions[d];
        if (dc.until < sc.realT) { delete st.decisions[d]; return; }
        const r = roomOf(d);
        c.globalAlpha = dimFor(dc.itemId);
        P.drawBitmap(c, 'decision', r.door - 3, ROOM_B - 5);
        P.sign(c, r.door, ROOM_B + 30, dc.text, { size: 5.5, bg: PAL.white, stripe: PAL.blue2, maxW: lay.s5 ? 90 : 110 });
        c.globalAlpha = 1;
      });

      // 排队的号码牌
      sc.actors.filter((a) => a.data.queue && a.visible && a.data.item).forEach((a) => {
        const rct = P.itemRect(sc, a);
        if (rct && a.data.item.queuePos) {
          c.globalAlpha = a.alpha * a.dim;
          P.pixText(c, String(a.data.item.queuePos), rct[0] + rct[2] / 2, rct[1] + 0.5, PAL.ink, 'center');
          c.globalAlpha = 1;
        }
      });

      // 头顶图标
      sc.actors.forEach((a) => { if (a.icon) { c.globalAlpha = a.dim; P.drawIcon(c, sc, a); c.globalAlpha = 1; } });

      // 观察员
      if (lay.s5) drawObserver(c, sc, t);

      // 减少动画时的交接箭头
      st.arrows.forEach((ar) => {
        c.globalAlpha = dimFor(ar.itemId);
        P.arrow(c, ar.pts, ar.color, { dash: ar.dash });
        const m = ar.pts[Math.floor(ar.pts.length / 2) - (ar.pts.length % 2 ? 0 : 1)];
        const n = ar.pts[Math.floor(ar.pts.length / 2)];
        const bmp = P.bitmap(ar.bmp);
        P.drawBitmap(c, ar.bmp, (m[0] + n[0]) / 2 - bmp.w / 2, (m[1] + n[1]) / 2 - bmp.h - 3);
        c.globalAlpha = 1;
      });

      drawInfoBar(c);
    }

    // 观察员：站在观察台上，判定时走到交接经过的位置上方举牌
    let observer = null;
    function drawObserver(c, sc, t) {
      const on = model.observer ? model.observer.active !== false : true;
      if (!observer) {
        observer = sc.addActor({ id: 'observer', sprite: 'meta.observer', x: 120, y: 50, anim: 'hold_clip', data: { observer: true } });
      }
      observer.visible = on;
      if (!on) return;
      const sign = st.observerSign && st.observerSign.until > sc.realT ? st.observerSign : null;
      if (!observer.script) {
        if (sign && Math.abs(observer.x - sign.x) > 1) sc.run(observer, [{ t: 'go', x: sign.x, y: 50 }, { t: 'turn', facing: 1 }], {});
        else if (sign) sc.play(observer, 'hold_sign');
        else {
          sc.play(observer, 'hold_clip');
          if (!observer.data.next || sc.realT > observer.data.next) {
            observer.data.next = sc.realT + 5000 + Math.random() * 4000;
            const nx = 60 + Math.random() * (W - 120);
            sc.run(observer, [{ t: 'go', x: nx, y: 50, speed: 24 }, { t: 'turn', facing: 1 }], {});
          }
        }
      }
      P.drawActor(c, sc, observer);
      if (sign && observer.anim === 'hold_sign') {
        const [hx, hy] = P.headTop(sc, observer);
        const ss = P.signStyle(sign.text);
        P.sign(c, hx, hy - 1, sign.text, { size: 7, bg: ss.bg, fg: ss.fg, stripe: ss.stripe, pole: 3, maxW: 120 });
      } else if (model.observer && model.observer.last) {
        const l = model.observer.last;
        const txt = '最近判定：' + ({ pass: '通过', fail: '不通过', uncertain: '不确定' }[l.result] || l.result) + (l.confidence !== undefined ? ' ' + Number(l.confidence).toFixed(2) : '');
        P.text(c, txt, W - 8, 24, { size: 6, weight: 600, align: 'right', color: PAL.ink2 });
      }
    }

    function drawInfoBar(c) {
      R(c, 0, 0, W, 18, '#1f2230');
      R(c, 0, 17, W, 1, '#3a3f52');
      const fid = focusId || model.focusId;
      const it = (fid && itemById(fid)) || model.items.find((x) => statusOf(x) === 'running') || model.items[0];
      if (!it) { P.text(c, '没有进行中的事项', 8, 9, { size: 7, color: PAL.grey1 }); return; }
      const s = statusOf(it);
      R(c, 6, 5, 8, 8, PAL.ink); R(c, 7, 6, 6, 6, P.ITEM_COLORS[it.colorIndex]);
      let x = 18;
      x += P.text(c, it.title || it.id, x, 9, { size: 7, weight: 700, color: PAL.white, max: 190 }) + 8;
      const chip = (text, bg, fg) => {
        c.font = '700 6.5px ' + P.FONT;
        const w = c.measureText(text).width + 8;
        R(c, x, 4, w, 10, bg);
        P.text(c, text, x + w / 2, 9, { size: 6.5, weight: 700, align: 'center', color: fg || PAL.ink });
        x += w + 4;
      };
      if (it.cycle) chip('第 ' + it.cycle + ' 轮', PAL.paper);
      if (it.department && P.DEPTS[it.department]) chip('当前部门：' + P.DEPTS[it.department].name, P.DEPTS[it.department].light);
      chip(STATUS_TEXT[s] || s, STATUS_CHIP[s] || PAL.grey2, ['running', 'failed', 'adopted', 'asking'].includes(s) ? PAL.white : PAL.ink);
      // 时间进度条
      if (it.limitSec) {
        const k = Math.min(1, (it.elapsedSec || 0) / it.limitSec);
        const bw = 110, bx = W - bw - 8;
        const col = k >= 0.95 ? PAL.red2 : k >= 0.8 ? PAL.orange2 : PAL.green2;
        P.text(c, '已用 ' + Math.round((it.elapsedSec || 0) / 60) + ' 分 / 上限 ' + Math.round(it.limitSec / 60) + ' 分', bx - 6, 9, { size: 6.5, weight: 600, align: 'right', color: k >= 0.8 ? PAL.orange1 : PAL.grey1 });
        R(c, bx, 5, bw, 8, PAL.ink); R(c, bx + 1, 6, bw - 2, 6, '#383d50');
        R(c, bx + 1, 6, Math.round((bw - 2) * k), 6, col);
        R(c, bx + 1, 6, Math.round((bw - 2) * k), 1, P.mix(col, PAL.white, 0.4));
      }
    }

    // -------------------------------------------------------------------------
    // 接口

    function setModel(m) {
      if (!m) throw new Error('setModel 需要 loopModel');
      model = Object.assign({ items: [], slots: { total: 3, used: 0 }, shelves: { adopted: [], held: [] }, openRequests: [] }, m);
      model.shelves = Object.assign({ adopted: [], held: [] }, m.shelves || {});
      if (m.level && m.level !== level) {
        level = m.level;
        lay = layoutFor(level);
        bg = null;
        scene.actors.filter((a) => a.data.worker).forEach((a) => scene.removeActor(a));
        if (observer && !lay.s5) { scene.removeActor(observer); observer = null; }
      }
      if (m.focusId !== undefined && focusId === null) focusId = m.focusId;
      st.eventStatus = {}; st.eventSign = {}; st.interrupted = false;
      st.extraAdopted = st.extraAdopted.filter((v) => !(model.shelves.adopted || []).includes(v));
      st.extraHeld = st.extraHeld.filter((h) => !(model.shelves.held || []).some((x) => x.id === h.id || x.label === h.label));
      applyFreeze();
    }

    function focus(id) {
      focusId = id || null;
    }

    syncWorkers();

    return {
      scene,
      setModel,
      playEvent,
      focus,
      resize: () => scene.resize(),
      destroy: () => scene.destroy()
    };
  };
})();
