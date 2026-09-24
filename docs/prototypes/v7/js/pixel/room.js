// 部门房间画面（设计说明第 6 节）：房间布置、按 roomModel 决定的状态姿势、按事件播放的一次性动作。
(function () {
  const Y7 = window.Y7;
  const P = Y7.pixel;
  if (!P || !P.createScene) throw new Error('room.js 需要先加载 js/pixel/engine.js');
  const PAL = P.PAL;
  const R = P.R, RB = P.RB, paint = P.paint;

  const W = 480, H = 240;
  const BASE = 130;      // 靠墙家具的底边
  const AISLE = 140;     // 靠墙走道
  const ROW_A = 176;     // 部门工作台的桌面前沿
  const ROW_B = 216;     // 办公桌的桌面前沿

  const L = {
    window: { x: 12, y: 16, w: 46, h: 40 },
    clock: { x: 64, y: 12 },
    crt: { x: 82, y: 10, w: 128, h: 70 },
    wb: { x: 222, y: 72, w: 84, h: 42, floor: 132 },
    back: { x: 316 },
    door: { x: 390, base: 120, w: 36, h: 60 },
    cork: { x: 434, y: 74, w: 30, h: 28 },
    mailbox: { x: 430, base: 132 },
    plant: { x: 464, base: 134 },
    cabinet: { x: 12, base: 130 },
    cards: { x: 46, base: 130 },
    terminal: { x: 100, base: 130 },
    tray: { x: 170, base: 132 },
    bench: { x: 300, w: 86, y: ROW_A },
    lamps: [140, 270, 380],
    beacon: { x: 405, y: 44 }
  };
  const SPOT = {
    cabinet: [52, 132, -1],
    archive: [52, 132, -1],
    cards: [82, 134, -1],
    terminal: [84, 132, 1],
    tray: [157, 134, 1],
    wb: [264, 134],
    rack: [346, 134],
    bench: [343, ROW_A],
    benchSide: [290, ROW_A, 1],
    door: [408, 136],
    doorIn: [408, 122],
    mailbox: [440, 139, 1],
    cork: [451, 136],
    crtLook: [146, 140],
    center: [262, 142],
    racks: [330, 134]
  };

  const STATUS_TEXT = {
    idle: '未工作', working: '工作中', asking: '等待回答', paused: '已暂停', failed: '失败', done: '已完成',
    cancelled: '已取消', interrupted: '中断', pending_verification: '待核实', waiting_resume: '待恢复'
  };
  const STATUS_COLOR = {
    working: PAL.screen3, asking: PAL.blue1, paused: PAL.blue1, failed: PAL.red1, done: PAL.green1,
    cancelled: PAL.grey1, interrupted: PAL.grey2, pending_verification: PAL.yellow2, waiting_resume: PAL.yellow2, idle: PAL.screen2
  };
  const POSE_ALIAS = {
    typing: 'type', type: 'type', reading: 'read_sit', read: 'read_sit', writing: 'write', write: 'write', thinking: 'think', think: 'think',
    searching: 'rummage', waiting: 'sit_wait', tea: 'tea', idle: 'sit', inspecting: 'inspect'
  };
  const BENCH_LABEL = { product: '卷轴台', engineering: '封存台', quality: '检验台' };

  const S = {
    go: (x, y, gait, speed) => ({ t: 'go', x, y, gait, speed }),
    anim: (name, ms, key, facing) => ({ t: 'anim', name, ms, key, facing }),
    wait: (ms, key) => ({ t: 'wait', ms, key }),
    call: (fn) => ({ t: 'call', fn }),
    hold: (item) => ({ t: 'hold', item }),
    turn: (facing) => ({ t: 'turn', facing }),
    icon: (icon) => ({ t: 'icon', icon }),
    seat: (seat) => ({ t: 'seat', seat }),
    fade: (to, ms) => ({ t: 'fade', to, ms })
  };

  P.createRoomScene = function createRoomScene(canvas, opts) {
    const o = opts || {};
    const dept = o.department;
    if (!['product', 'engineering', 'quality', 'operations'].includes(dept)) throw new Error('部门房间的部门无效：' + dept);
    const D = P.DEPTS[dept];
    let level = o.level || 'now';
    P.levelAtLeast(level, 'now');

    let model = { department: dept, level, status: 'idle', crt: {}, roles: [], pose: null, door: null, holdCard: null, pendingTool: null, mailbox: 0, summaries: 0 };
    const st = {
      dark: 0.36, darkTarget: 0.36, yellow: false,
      clock: 15.5 * 3600000, crtBoot: 1,
      drawer: 0, lever: 0, exit: null, termRun: false, smokeUntil: 0,
      tray: 1, scrolls: 3, scrollFlash: 0, notes: 0, notesDone: 0, cards: 3, cardFlash: 0,
      archiveFlash: 0,
      door: 0, doorEvent: null, eventStatus: null, eventCard: null, eventTool: null, lastPendingTool: null,
      bench: { item: dept === 'product' ? 'scroll' : dept === 'quality' ? null : null, mark: null, slip: null, slipMark: null, ticks: 0, tape: 0 },
      wbSheet: false, wbErase: 0, wbSeed: 1, wbTags: {}, wbDone: {},
      binCount: 0, rackOn: true, rackFlash: 0, alarmUntil: 0, cart: { x: 296, box: null },
      desks: [], deskState: {}, confettiAt: 0, courierN: 0
    };
    let bg = null;
    let bgKey = '';

    const scene = P.createScene(canvas, { W, H, draw, update, maxScale: 6 });

    // -------------------------------------------------------------------------
    // 角色与工位

    function spriteFor(role) {
      let kind = role.kind || 'agent';
      if (dept === 'operations' && (kind === 'agent' || kind === 'ops')) kind = 'ops';
      if (!P.ROLE_KINDS[kind]) throw new Error('未知角色种类：' + kind);
      return dept + '.' + kind;
    }
    function rolesOf(m) {
      const list = (m.roles && m.roles.length) ? m.roles : [{ id: 'agent', kind: dept === 'operations' ? 'ops' : 'agent' }];
      return list.map((r) => Object.assign({ name: r.name || P.ROLE_NAMES[spriteFor(r)] || r.id }, r));
    }

    function layoutDesks(n) {
      if (n <= 1) return [{ x: 150, w: 64 }];
      const w = n >= 5 ? 54 : 60, gap = n >= 5 ? 6 : n === 4 ? 16 : 30;
      const total = n * w + (n - 1) * gap;
      const x0 = Math.round((296 - total) / 2) + 4;
      const out = [];
      for (let i = 0; i < n; i++) out.push({ x: x0 + i * (w + gap), w });
      return out;
    }

    function syncRoles() {
      const roles = rolesOf(model);
      const lay = layoutDesks(roles.length);
      const keep = new Set(roles.map((r) => r.id));
      scene.actors.filter((a) => a.data.role && !keep.has(a.id)).forEach((a) => scene.removeActor(a));
      st.desks = roles.map((r, i) => {
        const d = { i, x: lay[i].x, w: lay[i].w, y: ROW_B, seatX: lay[i].x + 18, seatY: ROW_B, roleId: r.id, role: r };
        let a = scene.actors.find((x) => x.id === r.id);
        const sprite = spriteFor(r);
        if (!a) {
          a = scene.addActor({ id: r.id, sprite, x: d.seatX, y: d.seatY, anim: 'sit', data: { role: r } });
          a.seat = d;
        }
        a.sprite = sprite;
        a.data.role = r;
        a.data.desk = d;
        if (a.seat && a.seat.roleId === r.id) a.seat = d;
        if (!st.deskState[r.id]) st.deskState[r.id] = { papers: 3 + (i % 3), folder: false, doc: false, box: false, card: false, cardResult: false, redLamp: false, scroll: false, plane: false };
        return d;
      });
      const prim = primary();
      st.bin = { x: st.desks[0].x + st.desks[0].w + 2, y: ROW_B + 9 };
      if (prim && prim.data.desk) st.bin.x = prim.data.desk.x + prim.data.desk.w + 2;
    }

    function roleActors() { return scene.actors.filter((a) => a.data.role); }
    function primary() {
      const list = roleActors();
      return list.find((a) => a.data.role.kind === 'manager') || list[0];
    }
    function actorFor(ev) {
      const list = roleActors();
      if (ev && ev.role) {
        const hit = list.find((a) => a.id === ev.role || a.data.role.kind === ev.role || a.data.role.name === ev.role);
        if (hit) return hit;
      }
      return primary();
    }
    function byKind(kind) { return roleActors().find((a) => a.data.role.kind === kind); }
    function ds(a) { return st.deskState[a.id]; }

    // -------------------------------------------------------------------------
    // 路线：工作台前板是障碍，其余地面可以直接走

    const BLOCKS = dept === 'operations' ? [] : [{ x0: L.bench.x - 4, x1: L.bench.x + L.bench.w + 4, y0: ROW_A + 1, y1: ROW_A + 16 }];
    function blocked(p0, p1) {
      const n = Math.max(1, Math.ceil(Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / 3));
      for (let i = 1; i < n; i++) {
        const x = p0[0] + (p1[0] - p0[0]) * i / n, y = p0[1] + (p1[1] - p0[1]) * i / n;
        if (BLOCKS.some((b) => x > b.x0 && x < b.x1 && y > b.y0 && y < b.y1)) return true;
      }
      return false;
    }

    function plan(a) {
      const p = { steps: [], x: a.x, y: a.y, seated: !!a.seat };
      p.stand = () => {
        if (p.seated) { p.steps.push(S.seat(null), S.anim('idle', 180)); p.seated = false; }
        return p;
      };
      // 直线走过去；离开或走回工位时先在桌后站一步；路线穿过工作台时从工作台旁边绕过去
      p.to = (x, y, gait, speed) => {
        p.stand();
        const pts = [];
        const behindDesk = ROW_B - 14;
        if (p.y >= ROW_B - 2 && Math.abs(p.y - y) > 2) pts.push([p.x, behindDesk]);
        const goal = (y >= ROW_B - 2 && Math.abs(p.y - y) > 2) ? [x, behindDesk] : [x, y];
        const from = pts.length ? pts[pts.length - 1] : [p.x, p.y];
        if (blocked(from, goal)) {
          const vias = BLOCKS.flatMap((b) => [[b.x0 - 8, b.y0 - 10], [b.x1 + 8, b.y0 - 10], [b.x0 - 8, b.y1 + 6], [b.x1 + 8, b.y1 + 6]]);
          const via = vias
            .filter((v) => !blocked(from, v) && !blocked(v, goal))
            .sort((m, n) => (Math.hypot(m[0] - from[0], m[1] - from[1]) + Math.hypot(goal[0] - m[0], goal[1] - m[1])) - (Math.hypot(n[0] - from[0], n[1] - from[1]) + Math.hypot(goal[0] - n[0], goal[1] - n[1])))[0];
          if (via) pts.push(via);
          else pts.push([from[0], AISLE], [goal[0], AISLE]);
        }
        pts.push(goal);
        if (goal[1] !== y || goal[0] !== x) pts.push([x, y]);
        let cx = p.x, cy = p.y;
        pts.forEach(([px, py]) => {
          if (Math.hypot(px - cx, py - cy) > 0.5) p.steps.push(S.go(px, py, gait, speed));
          cx = px; cy = py;
        });
        p.x = x; p.y = y;
        return p;
      };
      p.spot = (name, gait) => {
        const s = SPOT[name];
        p.to(s[0], s[1], gait);
        if (s[2]) p.steps.push(S.turn(s[2]));
        return p;
      };
      p.sit = (gait) => {
        const d = a.data.desk;
        if (!p.seated) {
          p.to(d.seatX, d.seatY, gait);
          p.steps.push(S.seat(d), S.turn(1));
          p.seated = true;
        }
        return p;
      };
      p.add = (...list) => { p.steps.push(...list); return p; };
      // mark 标出收尾步骤的起点；back 为「标出收尾后走回工位坐下」
      p.mark = () => { p.tailAt = p.steps.length; return p; };
      p.back = (gait) => { p.mark(); return p.sit(gait); };
      p.run = (finalize, tail) => {
        const t = tail !== undefined ? tail : p.tailAt;
        scene.run(a, p.steps, { tail: t, finalize: () => { if (finalize) finalize(); a.icon = null; } });
        return p;
      };
      return p;
    }

    // 递卡片时站在桌子旁边：左边放得下就站左边，否则站右边
    function giveSpot(d) {
      return d.x - 8 >= 10 ? [d.x - 8, ROW_B, 1] : [d.x + d.w + 8, ROW_B, -1];
    }

    function openDoor() { scene.tween(st, 'door', 1, 260, 'out'); }
    function closeDoor() { scene.tween(st, 'door', 0, 320, 'inOut'); }

    // 送件小人：从门进来，放下或取走物件，再从门出去
    function courier(o2) {
      st.courierN += 1;
      const ci = o2.colorIndex === null || o2.colorIndex === undefined ? '' : ':' + o2.colorIndex;
      const c = scene.addActor({ id: 'courier-' + st.courierN, sprite: 'courier.courier' + ci, x: SPOT.doorIn[0], y: SPOT.doorIn[1], alpha: 0, speed: 50 });
      const p = plan(c);
      const inGait = o2.bring ? 'carry' : 'walk';
      p.add(S.call(openDoor), S.hold(o2.bring || null), S.fade(1, 260));
      p.to(SPOT.door[0], SPOT.door[1], inGait);
      p.add(S.call(closeDoor));
      p.to(o2.at[0], o2.at[1], inGait);
      p.add(S.turn(o2.at[2] || 1));
      if (o2.back) p.add(S.anim('back', 500, true)); else p.add(S.anim('side_reach', 600, true));
      p.add(S.call(() => {
        if (o2.onArrive) o2.onArrive(c);
        c.hold = o2.take || null;
      }), S.anim('idle_happy', 300));
      const outGait = o2.take ? 'carry' : 'walk';
      p.to(SPOT.door[0], SPOT.door[1], outGait);
      p.add(S.call(openDoor), S.go(SPOT.doorIn[0], SPOT.doorIn[1], outGait), S.fade(0, 240), S.call(closeDoor), S.call(() => scene.removeActor(c)));
      scene.run(c, p.steps, {});
      return c;
    }

    // -------------------------------------------------------------------------
    // 状态

    function effStatus() { return st.eventStatus || model.status || 'idle'; }
    function isOps() { return dept === 'operations'; }

    function applyLights() {
      const s = effStatus();
      const target = s === 'interrupted' ? 0.74 : (s === 'working' || s === 'asking' || s === 'pending_verification' || s === 'done') ? 0 : 0.36;
      if (target !== st.darkTarget) {
        st.darkTarget = target;
        if (s === 'interrupted' && !scene.reduced) {
          // 灯管闪两下后熄灭
          st.dark = 0.5;
          scene.after(90, () => { st.dark = 0.1; });
          scene.after(180, () => { st.dark = 0.6; });
          scene.after(260, () => { st.dark = 0.3; });
          scene.after(360, () => { st.dark = target; });
        } else {
          scene.tween(st, 'dark', target, 600, 'inOut');
        }
      }
      st.yellow = s === 'pending_verification';
      scene.frozen = s === 'interrupted';
    }

    // 每个角色的状态姿势
    function restFor(a) {
      const s = effStatus();
      const d = a.data.desk;
      const r = a.data.role;
      const isPrim = a === primary();
      const seatRest = (anim, extra) => Object.assign({ x: d.seatX, y: d.seatY, seat: d, anim, facing: 1 }, extra || {});
      const standRest = (x, y, anim, extra) => Object.assign({ x, y, seat: null, anim }, extra || {});
      if (s === 'pending_verification' && isPrim) {
        const tool = st.eventTool || model.pendingTool;
        const spot = toolSpot(tool);
        if (spot === 'desk') return seatRest('sit_scratch', { icon: { kind: 'question' } });
        const sp = SPOT[spot];
        return standRest(sp[0], sp[1], 'puzzled', { icon: { kind: 'question' }, facing: sp[2] || 1 });
      }
      if (s === 'waiting_resume' && isPrim) {
        return standRest(SPOT.center[0], SPOT.center[1], 'hold_sign', { sign: model.holdCard || st.eventCard || '待恢复' });
      }
      if (s === 'asking' && isPrim) return standRest(SPOT.door[0] - 14, SPOT.door[1] + 2, 'wait', { facing: 1 });
      if (s === 'idle') return seatRest('tea');
      if (s === 'paused') return seatRest('sit_relax', { icon: isPrim ? { kind: 'zzz' } : null });
      if (s === 'failed') return seatRest('slump');
      if (s === 'done') return standRest(d.seatX, d.seatY, isPrim ? 'cheer' : 'idle_happy');
      if (s === 'cancelled') return standRest(d.seatX, d.seatY, 'idle');
      if (s === 'interrupted') return null;
      // 工作中：按角色状态与持续动作
      if (a.data.persist && (!a.data.persist.until || scene.realT < a.data.persist.until)) {
        const ps = a.data.persist;
        return seatRest(ps.anim || 'type', { icon: ps.icon || null, hold: ps.hold || null });
      }
      if (r.status === 'away') return { x: SPOT.doorIn[0], y: SPOT.doorIn[1], seat: null, anim: 'idle', away: true };
      if (r.status === 'idle') return seatRest('tea');
      if (r.status === 'assigned') return seatRest('sit_card', { hold: 'card_task' });
      if (r.status === 'returned') return seatRest('sit_happy');
      if (r.status === 'failed') return seatRest('slump');
      if (model.pose && (model.pose.roleId === a.id || (!model.pose.roleId && isPrim))) {
        const act = model.pose.action;
        const anim = POSE_ALIAS[act] || (P.ANIMS[act] ? act : (P.ACTIONS[act] ? P.ACTIONS[act].anim : null));
        if (!anim) throw new Error('roomModel.pose.action 无法对应到动作：' + act);
        return seatRest(anim, { hold: anim === 'read_sit' ? 'doc' : null });
      }
      return seatRest('type');
    }

    function toolSpot(tool) {
      if (tool === 'run_command') return 'terminal';
      if (tool === 'search') return 'cabinet';
      if (tool === 'run_check') return 'bench';
      return 'desk';
    }

    function applyRest(a) {
      const r = restFor(a);
      if (!r) return;
      if (r.away) {
        a.visible = false;
        a.seat = null;
        a.x = r.x; a.y = r.y;
        return;
      }
      if (!a.visible) {
        // 从门外回来
        a.visible = true; a.alpha = 0; a.x = SPOT.doorIn[0]; a.y = SPOT.doorIn[1];
        const p = plan(a);
        p.add(S.call(openDoor), S.fade(1, 240));
        p.to(SPOT.door[0], SPOT.door[1]);
        p.add(S.call(closeDoor));
        p.run(null, 0);
        return;
      }
      const atSpot = Math.hypot(a.x - r.x, a.y - r.y) < 1.5 && (r.seat ? a.seat === r.seat : !a.seat);
      if (!atSpot) {
        // 回到状态姿势的路线可以被新的动作随时打断
        const p = plan(a);
        if (r.seat) p.sit(); else p.to(r.x, r.y);
        if (r.facing) p.add(S.turn(r.facing));
        p.run(null, 0);
        return;
      }
      if (r.facing) a.facing = r.facing;
      a.hold = r.hold || null;
      a.sign = r.sign || null;
      if (r.icon) { if (!a.icon || a.icon.kind !== r.icon.kind || a.icon.text !== r.icon.text) a.icon = Object.assign({ t0: scene.realT }, r.icon); } else a.icon = null;
      scene.play(a, r.anim);
      // 待机时偶尔伸懒腰；打字时偶尔停下来想一想或抬头看屏幕；完成时撒彩带
      if (r.anim === 'tea') {
        if (!a.data.nextStretch) a.data.nextStretch = scene.realT + 5000 + P.hash(a.seed) * 6000;
        if (scene.realT > a.data.nextStretch) {
          a.data.nextStretch = scene.realT + 9000 + Math.random() * 6000;
          scene.run(a, [S.anim('stretch_sit'), S.anim('sit', 400)], { tail: 0 });
        }
      }
      if (r.anim === 'type' && !r.icon) {
        if (!a.data.nextPause) a.data.nextPause = scene.realT + 4000 + P.hash(a.seed + 5) * 5000;
        if (scene.realT > a.data.nextPause) {
          a.data.nextPause = scene.realT + 7000 + Math.random() * 6000;
          scene.run(a, [S.anim(Math.random() < 0.5 ? 'think' : 'sit_up', 1300)], { tail: 0 });
        }
      }
      if (r.anim === 'cheer' && scene.realT > st.confettiAt) {
        st.confettiAt = scene.realT + 2600;
        scene.emit('confetti', 240, 10, 40, { spread: 440 });
      }
    }

    function update() {
      if (effStatus() !== 'interrupted') st.clock += 16.7 * (scene.reduced ? 0 : 1);
      roleActors().forEach((a) => {
        // 排队的动作：当前动作的关键步骤做完（或进入收尾步骤）后立即开始；
        // 等了 0.9 秒仍未轮到时打断当前动作，只让刚开始的关键步骤再显示到 0.6 秒
        const q = a.data.queue;
        if (q && q.length && !scene.frozen) {
          const waited = scene.realT - q[0].at;
          const keyJustStarted = a.step && a.step.st.key && (scene.realT - a.step.t0) < 600;
          if (scene.inTail(a) || (waited >= 900 && !keyJustStarted)) {
            const next = q.shift();
            if (a.script) scene.cancel(a);
            next.fn();
            return;
          }
        }
        if (!a.script) applyRest(a);
      });
      if (st.smokeUntil > scene.realT && !scene.reduced && Math.random() < 0.3) scene.emit('smoke', L.terminal.x + 14, L.terminal.base - 38, 1);
      if (!scene.frozen && Math.random() < 0.035) scene.emit('steam', 413, ROW_B - 15, 1);
      // 喝茶时杯口冒热气
      roleActors().forEach((a) => {
        if (a.anim === 'tea' && a.seat && !scene.frozen && Math.random() < 0.03) {
          const [hx, hy] = P.headTop(scene, a);
          scene.emit('steam', hx + 2, hy + 12, 1);
        }
      });
    }

    // -------------------------------------------------------------------------
    // 事件

    function setPersist(a, ps) { a.data.persist = ps; }

    // 事件说明中用「」括起的部分：没有 payload.text 时作为气泡与举牌上的文字
    function quoted(label) {
      const m = /「([^」]+)」/.exec(String(label || ''));
      return m ? m[1] : (label || null);
    }

    // 盖章：在工作台上盖章，impact 为落章时的回调
    function stampSteps(item, hitFn, anim) {
      const name = anim || 'stamp_once';
      const hits = name === 'stamp' ? [450 + 380, 380 + 70 + 450 + 300 + 70 + 450] : [400 + 70 + 10];
      return [
        S.hold(item),
        S.call(() => hits.forEach((ms, i) => scene.after(scene.reduced ? 0 : ms, () => {
          scene.emit('dust', SPOT.bench[0] - 3, ROW_A - 5, 14);
          hitFn(i);
        }))),
        S.anim(name, undefined, true),
        S.hold(null)
      ];
    }

    function planeOut(a) {
      const hx = a.x + 8, hy = a.y - 20;
      scene.fly({ bmp: 'plane', frames: ['plane', 'plane2'], from: [hx, hy], to: [L.door.x + 18, L.door.base - 34], ms: 700, arc: 10 });
    }
    // 侧身把纸飞机扔出门：抬手 400 毫秒后出手
    function throwSteps(a) {
      return [
        S.call(() => scene.after(scene.reduced ? 0 : 400, () => { a.hold = null; planeOut(a); })),
        S.anim('side_throw', 900, true)
      ];
    }

    const handlers = {
      activate(ev, a) {
        if ((model.status || 'idle') === 'idle') st.eventStatus = 'working';
        applyLights();
        setPersist(a, null);
        st.crtBoot = 0;
        const p = plan(a);
        p.add(S.anim(a.seat ? 'sit_up' : 'look_up', 300));
        p.to(SPOT.crtLook[0], SPOT.crtLook[1]);
        p.add(S.call(() => scene.tween(st, 'crtBoot', 1, 1000, 'linear')), S.anim('look_up', 1300, true), S.anim('idle_happy', 500));
        p.sit();
        p.add(S.anim('type', 500));
        p.run(() => { st.crtBoot = 1; });
      },
      fetch_folder(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.spot('cabinet');
        let placed = false;
        const place = () => { if (!placed) { placed = true; const s = ds(a); s.folder = true; s.papers += 2; } };
        p.add(S.call(() => scene.tween(st, 'drawer', 1, 300, 'out')), S.anim('rummage', 1100), S.anim('grab_folder', 700, true),
          S.call(() => scene.tween(st, 'drawer', 0, 300, 'inOut')), S.hold('folder'));
        p.sit('carry');
        p.add(S.call(place), S.hold(null), S.anim('sit_happy', 600));
        p.run(() => { st.drawer = 0; a.hold = null; place(); });
      },
      type_think(ev, a) {
        setPersist(a, { anim: 'type', icon: { kind: 'think' } });
        ds(a).redLamp = false;
        const p = plan(a);
        p.sit();
        p.add(S.icon({ kind: 'think' }), S.anim('type', 1200, true));
        p.run();
      },
      stream_text(ev, a) {
        const pl = ev.payload || {};
        const text = pl.text || pl.delta || pl.chunk || quoted(ev.label) || '……';
        setPersist(a, { anim: 'type', icon: { kind: 'stream', text } });
        const p = plan(a);
        p.sit();
        p.add(S.icon({ kind: 'stream', text }), S.anim('type', 1500, true));
        p.run();
      },
      idea(ev, a) {
        setPersist(a, { anim: 'sit_happy', icon: { kind: 'bulb' }, until: scene.realT + 2600 });
        const p = plan(a);
        p.sit();
        p.add(S.icon({ kind: 'bulb' }), S.call(() => {
          const [hx, hy] = P.headTop(scene, a);
          scene.emit('spark', hx, hy - 10, 12);
        }), S.anim('sit_happy', 1600, true));
        p.run();
      },
      retry_wait(ev, a) {
        const pl = ev.payload || {};
        const n = pl.n || pl.attempt || pl.attempt_no || 2;
        const of = pl.of || pl.max || pl.max_attempts || 3;
        const text = '第 ' + n + '/' + of + ' 次';
        setPersist(a, { anim: 'sit_wait', icon: { kind: 'hourglass', text } });
        const p = plan(a);
        p.sit();
        p.add(S.icon({ kind: 'hourglass', text }), S.anim('sit_wait', 1600, true));
        p.run();
      },
      slump(ev, a) {
        setPersist(a, { anim: 'slump' });
        ds(a).redLamp = true;
        const p = plan(a);
        p.sit();
        p.add(S.anim('shock', 300), S.anim('slump', 1600, true));
        p.run();
      },
      search(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.spot('cabinet');
        p.add(S.call(() => scene.tween(st, 'drawer', 1, 300, 'out')), S.anim('rummage', 1300), S.call(() => { ds(a).papers += 1; }), S.anim('magnify', 1600, true),
          S.call(() => scene.tween(st, 'drawer', 0, 320, 'inOut')));
        p.back();
        p.run(() => { st.drawer = 0; });
      },
      read(ev, a) {
        setPersist(a, { anim: 'read_sit', hold: 'doc' });
        const p = plan(a);
        p.sit();
        p.add(S.hold('doc'), S.anim('read_sit', 1800, true));
        p.run();
      },
      write(ev, a) {
        setPersist(a, { anim: 'write', write: true });
        const p = plan(a);
        p.sit();
        p.add(S.call(() => { ds(a).doc = true; }), S.anim('write', 1800, true));
        p.run();
      },
      run_command(ev, a) {
        if (ev.type === 'tool_called') return commandDone(ev, a);
        setPersist(a, null);
        st.exit = null;
        const p = plan(a);
        p.spot('terminal');
        p.add(S.call(() => scene.after(scene.reduced ? 0 : 450, () => {
          scene.tween(st, 'lever', 1, 220, 'out');
          st.termRun = true;
          scene.emit('dust', L.terminal.x - 8, L.terminal.base - 8, 5);
        })), S.anim('lever', 1000, true));
        p.mark();
        p.add(S.anim('watch_r', 14000));
        p.run();
      },
      toss(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.stand();
        p.add(S.anim('shake', undefined), S.anim('fold', 600), S.hold('paperball'), S.call(() => scene.after(scene.reduced ? 0 : 450, () => {
          a.hold = null;
          scene.fly({ bmp: 'paperball', from: [a.x + 6, a.y - 20], to: [st.bin.x + 5, st.bin.y - 10], ms: 650, arc: 22, ease: 'linear', onDone: () => { st.binCount += 1; } });
        })), S.anim('throw', 1000, true));
        p.back();
        p.run(() => { a.hold = null; });
      },
      submit(ev, a) {
        setPersist(a, null);
        let placed = false;
        const place = () => { if (!placed) { placed = true; st.tray += 1; a.hold = null; } };
        const p = plan(a);
        p.stand();
        p.add(S.hold('doc'), S.call(() => { ds(a).doc = false; }));
        p.spot('tray', 'carry');
        p.add(S.call(() => scene.after(scene.reduced ? 0 : 450, place)), S.anim('side_place', 700, true), S.anim('side', 300));
        p.back();
        p.run(place);
      },
      returned(ev, a) {
        setPersist(a, null);
        const d = a.data.desk;
        st.tray = Math.max(0, st.tray - 1);
        scene.fly({ bmp: 'doc', from: [L.tray.x + 13, L.tray.base - 24], to: [d.x + d.w / 2 - 8, ROW_B - 6], ms: 800, arc: 26, onDone: () => { ds(a).doc = true; } });
        const p = plan(a);
        p.sit();
        p.add(S.anim('sit_up', 700), S.icon({ kind: 'question' }), S.anim('sit_scratch', 1800, true), S.icon(null));
        p.run(() => { ds(a).doc = true; });
      },
      stamp_valid(ev, a) {
        setPersist(a, null);
        // 盖章之后卷轴要放上卷轴架；被下一个动作打断时直接放上去
        let shelved = false;
        const shelve = () => { if (!shelved) { shelved = true; st.scrolls = Math.min(12, st.scrolls + 1); st.scrollFlash = scene.realT + 1500; st.bench.item = null; st.bench.mark = null; } };
        const p = plan(a);
        p.add(S.call(() => { st.bench.item = 'scroll_open'; st.bench.mark = null; }));
        p.spot('bench');
        p.add(...stampSteps('stamp_valid', () => { st.bench.mark = { text: '有效', color: '#d4353f' }; }, 'stamp'));
        p.add(S.anim('idle_happy', 400), S.call(() => { st.bench.item = null; st.bench.mark = null; }), S.hold('scroll'));
        p.spot('rack', 'carry');
        p.add(S.anim('board_pin', undefined), S.call(() => {
          a.hold = null;
          scene.fly({ bmp: 'scroll', from: [SPOT.rack[0], SPOT.rack[1] - 24], to: [L.back.x + 30, BASE - 40], ms: 500, arc: 6, onDone: shelve });
        }), S.anim('back', 400));
        p.back();
        p.run(() => { a.hold = null; shelve(); });
      },
      pin_plan(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.stand();
        p.add(S.hold('doc'));
        p.spot('wb', 'carry');
        p.add(S.anim('board_pin', undefined, true), S.call(() => { st.wbSheet = true; }), S.hold(null), S.anim('back', 500), S.anim('idle_happy', 400));
        p.back();
        p.run(() => { st.wbSheet = true; a.hold = null; });
      },
      seal(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.add(S.call(() => { st.bench.item = 'box_open'; st.bench.mark = null; st.bench.tape = 0; }));
        p.stand();
        p.add(S.hold('docs'));
        p.spot('bench', 'carry');
        p.add(S.anim('place', 700), S.hold(null), S.call(() => { st.bench.item = 'box'; }),
          S.call(() => scene.tween(st.bench, 'tape', 1, 700, 'linear')), S.anim('tidy', 800),
          S.call(() => { st.bench.item = 'box_sealed'; }));
        p.add(...stampSteps('stamp_seal', () => { st.bench.mark = { text: '封存', color: PAL.blue2 }; }));
        p.add(S.anim('idle_happy', 500));
        p.back();
        p.run(() => {
          if (st.bench.item === 'box' || st.bench.item === 'box_open') st.bench.item = 'box_sealed';
          if (st.bench.item === 'box_sealed' && !st.bench.mark) st.bench.mark = { text: '封存', color: PAL.blue2 };
          st.bench.tape = 1; a.hold = null;
        });
        scene.after(scene.reduced ? 1700 : 4600, () => {
          if (st.bench.item !== 'box_sealed') return;
          courier({ at: SPOT.benchSide, colorIndex: ev.payload && ev.payload.colorIndex, onArrive: () => { st.bench.item = null; st.bench.mark = null; }, take: 'box_sealed' });
        });
      },
      inspect(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.add(S.call(() => { if (!st.bench.item) st.bench.item = 'box_sealed'; st.bench.ticks = 0; }));
        p.spot('bench');
        p.add(S.anim('inspect', 1800, true), S.call(() => {
          [0, 1, 2].forEach((i) => scene.after(scene.reduced ? 0 : 300 + i * 450, () => { st.bench.ticks = i + 1; }));
        }), S.anim('tick', 1600), S.anim('idle_happy', 400));
        p.back();
        p.run(() => { st.bench.ticks = 3; });
      },
      stamp_release(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.add(S.call(() => { st.bench.slip = 'release'; st.bench.slipMark = null; }));
        p.spot('bench');
        p.add(...stampSteps('stamp_green', () => {
          st.bench.slipMark = { text: '放行', color: PAL.green2 };
          scene.emit('spark', SPOT.bench[0] + 10, ROW_A - 10, 10);
        }));
        p.add(S.icon({ kind: 'check' }), S.anim('idle_happy', 900), S.icon(null));
        p.back();
        p.run(() => { st.bench.slipMark = { text: '放行', color: PAL.green2 }; });
      },
      stamp_rework(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.add(S.call(() => { st.bench.slip = 'defect'; st.bench.slipMark = null; if (!st.bench.item) st.bench.item = 'box_sealed'; }));
        p.spot('bench');
        p.add(...stampSteps('stamp_red', () => { st.bench.slipMark = { text: '返工', color: PAL.red2 }; }));
        p.add(S.call(() => { st.bench.item = 'box_rework'; }), S.icon({ kind: 'exclaim' }), S.anim('stand_sad', 800), S.icon(null));
        p.back();
        p.run(() => { st.bench.item = 'box_rework'; st.bench.slipMark = { text: '返工', color: PAL.red2 }; });
        scene.after(scene.reduced ? 1700 : 3800, () => {
          if (st.bench.item !== 'box_rework') return;
          courier({ at: SPOT.benchSide, onArrive: () => { st.bench.item = null; st.bench.slip = null; st.bench.slipMark = null; }, take: 'box_rework' });
        });
      },
      send_plane(ev, a) {
        const pl = ev.payload || {};
        if (pl.to === dept && pl.from !== dept) {
          // 本部门是被询问方：纸飞机从门外飞进来，落在桌上
          const pa = primary();
          const d = pa.data.desk;
          openDoor();
          scene.fly({ bmp: 'plane', frames: ['plane', 'plane2'], from: [L.door.x + 18, L.door.base - 30], to: [d.x + d.w / 2, ROW_B - 8], ms: 1100, arc: 18, flip: true, onDone: () => { ds(pa).plane = true; closeDoor(); } });
          if (scene.inTail(pa)) scene.run(pa, [S.anim(pa.seat ? 'sit_up' : 'look_up', 1200, true)], { tail: 0 });
          return;
        }
        setPersist(a, null);
        const p = plan(a);
        p.sit();
        p.add(S.anim('sit_fold', undefined));
        p.to(SPOT.door[0] - 14, SPOT.door[1] + 2);
        p.add(S.turn(1), S.hold('plane'), S.call(openDoor), ...throwSteps(a), S.call(closeDoor));
        p.mark();
        p.add(S.anim('wait', 2600));
        p.run(() => { st.door = 0; a.hold = null; });
      },
      answer_plane(ev, a) {
        const pl = ev.payload || {};
        const asker = pl.from === dept && pl.to !== dept;
        if (asker) {
          // 发问方收到回答：在门口接住纸飞机，读完回到工位
          const p = plan(a);
          p.to(SPOT.door[0] - 14, SPOT.door[1] + 2);
          p.add(S.turn(1), S.call(() => {
            openDoor();
            scene.fly({ bmp: 'plane', frames: ['plane', 'plane2'], from: [L.door.x + 18, L.door.base - 30], to: [a.x + 2, a.y - 22], ms: 800, arc: 8, flip: true, onDone: closeDoor });
          }), S.anim('catch', 1200, true), S.hold('doc'), S.anim('read_stand', 1400), S.hold(null));
          p.back();
          p.run(() => { a.hold = null; st.door = 0; });
          return;
        }
        // 本部门回答：接住纸飞机，写回答，再从门口放回
        const d = a.data.desk;
        const p = plan(a);
        p.stand();
        p.add(S.call(() => {
          if (ds(a).plane) { ds(a).plane = false; scene.fly({ bmp: 'plane', from: [d.x + d.w / 2, ROW_B - 8], to: [a.x, a.y - 22], ms: 400, arc: 6 }); } else {
            openDoor();
            scene.fly({ bmp: 'plane', frames: ['plane', 'plane2'], from: [L.door.x + 18, L.door.base - 30], to: [a.x, a.y - 22], ms: 900, arc: 14, flip: true, onDone: closeDoor });
          }
        }), S.anim('catch', 1100));
        p.sit();
        p.add(S.anim('write', 1300), S.anim('sit_fold', undefined));
        p.to(SPOT.door[0] - 14, SPOT.door[1] + 2);
        p.add(S.turn(1), S.hold('plane'), S.call(openDoor), ...throwSteps(a), S.call(closeDoor));
        p.back();
        p.run(() => { ds(a).plane = false; st.door = 0; a.hold = null; });
      },
      // 信箱数字以 roomModel.mailbox 为准，这里只播放纸条从门缝滑进信箱
      guidance_in() {
        const slot = [L.door.x + 18, L.door.base - 9];
        scene.fly({ bmp: 'note', from: slot, to: [L.mailbox.x + 7, L.mailbox.base - 9], ms: 700, arc: 2, ease: 'out' });
      },
      guidance_read(ev, a) {
        setPersist(a, null);
        let pinned = false;
        const pin = () => { if (!pinned) { pinned = true; st.notes += 1; } };
        const p = plan(a);
        p.spot('mailbox');
        p.add(S.anim('crouch', 700), S.hold('note'), S.anim('read_stand', 1400));
        p.spot('cork');
        p.add(S.call(() => scene.after(scene.reduced ? 0 : 450, () => {
          a.hold = null;
          scene.fly({ bmp: 'note', from: [SPOT.cork[0], SPOT.cork[1] - 24], to: [L.cork.x + 5 + (st.notes % 3) * 9, L.cork.y + 6 + Math.floor((st.notes % 6) / 3) * 13], ms: 350, arc: 4, onDone: pin });
        })), S.anim('note_pin', undefined, true), S.hold(null), S.anim('back', 500));
        p.back();
        p.run(() => { a.hold = null; pin(); });
      },
      guidance_reply(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.spot('cork');
        p.add(S.anim('board_write', 1700, true), S.call(() => { st.notesDone = Math.min(Math.max(st.notes, 1), st.notesDone + 1); if (!st.notes) st.notes = 1; }), S.anim('back', 400));
        p.back();
        p.run();
      },
      compact(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.stand();
        // 档案盒编号以 roomModel.summaries 为准，这里只播放整理纸堆、放进档案盒
        p.add(S.anim('gather', 1000), S.call(() => { ds(a).papers = 0; ds(a).folder = false; }), S.hold('docs'));
        p.spot('archive', 'carry');
        p.add(S.call(() => {
          a.hold = null;
          scene.fly({ bmp: 'docs', from: [a.x - 8, a.y - 22], to: [L.cabinet.x + 12, L.cabinet.base - 50], ms: 450, arc: 10, onDone: () => { st.archiveFlash = scene.realT + 1600; } });
        }), S.anim('side_place', 900, true), S.anim('idle_happy', 600));
        p.back();
        p.run(() => { a.hold = null; ds(a).papers = 0; });
      },
      compact_fail(ev, a) {
        setPersist(a, null);
        const d = a.data.desk;
        const n = Math.max(3, ds(a).papers);
        ds(a).papers = 0;
        scene.emit('paper', d.x + 10, ROW_B - 8, n * 2, { floor: ROW_B - 12 });
        const p = plan(a);
        p.stand();
        p.add(S.anim('shock', 500));
        p.to(d.seatX - 14, ROW_B - 12);
        p.add(S.anim('crouch', 900, true));
        p.to(d.seatX + 16, ROW_B - 14);
        p.add(S.anim('crouch', 900), S.hold('docs'), S.anim('gather', 700), S.call(() => { ds(a).papers = n; }), S.hold(null));
        p.back();
        p.run(() => { ds(a).papers = n; a.hold = null; });
      },
      paused(ev, a) {
        st.doorEvent = '已暂停';
        st.eventStatus = 'paused';
        applyLights();
        const p = plan(a);
        p.sit();
        p.add(S.anim('sit_relax', 1200, true));
        p.run();
      },
      failed(ev, a) {
        const pl = ev.payload || {};
        st.doorEvent = '失败' + (pl.reason || pl.stopReason ? '：' + (pl.reason || pl.stopReason) : '');
        st.eventStatus = 'failed';
        applyLights();
        ds(a).redLamp = true;
        const p = plan(a);
        p.sit();
        p.add(S.anim('slump', 1400, true));
        p.run();
      },
      done(ev, a) {
        st.doorEvent = '已完成';
        st.eventStatus = 'done';
        applyLights();
        const p = plan(a);
        p.stand();
        p.add(S.call(() => scene.emit('confetti', 240, 8, 60, { spread: 460 })), S.anim('cheer', 2200, true));
        p.run();
      },
      cancelled(ev, a) {
        st.doorEvent = '已取消';
        st.eventStatus = 'cancelled';
        applyLights();
        const p = plan(a);
        p.stand();
        p.add(S.call(() => { ds(a).box = true; }), S.anim('tidy', 1800, true), S.call(() => {
          const s = ds(a); s.papers = 0; s.folder = false; s.doc = false;
        }), S.anim('idle', 400));
        p.run(() => { const s = ds(a); s.papers = 0; s.folder = false; s.doc = false; s.box = true; });
      },
      freeze() {
        st.eventStatus = 'interrupted';
        st.doorEvent = '中断';
        applyLights();
      },
      puzzled(ev) {
        st.eventStatus = 'pending_verification';
        st.eventTool = (ev.payload && ev.payload.tool) || ev.tool || 'run_command';
        st.lastPendingTool = st.eventTool;
        scene.frozen = false;
        applyLights();
      },
      // 用户对结果未知的动作作出决定：从门缝接过决定单，读完后照着做；物件停止闪烁
      decided(ev, a) {
        const pl = ev.payload || {};
        const choice = pl.choice || 'accept_current';
        const tool = ev.tool || pl.tool || st.lastPendingTool || model.pendingTool || 'run_command';
        const words = { rerun: '重新执行', accept_current: '按当前实际状态继续', stop: '停止事项' }[choice] || choice;
        st.eventStatus = choice === 'stop' ? 'cancelled' : 'working';
        st.eventTool = null;
        if (choice === 'stop') st.doorEvent = '已停止';
        applyLights();
        setPersist(a, null);
        let tidied = false;
        const tidy = () => { if (!tidied) { tidied = true; const s = ds(a); s.papers = 0; s.folder = false; s.doc = false; s.box = true; } };
        const p = plan(a);
        p.to(SPOT.door[0] - 14, SPOT.door[1] + 2);
        p.add(S.turn(1), S.call(() => {
          scene.fly({ bmp: 'decision', from: [L.door.x + 18, L.door.base - 9], to: [a.x + 6, a.y - 2], ms: 500, arc: 2, ease: 'out' });
        }), S.anim('crouch', 700), S.hold('decision'), S.icon({ kind: 'text', text: words }), S.anim('read_stand', 1500, true), S.icon(null), S.hold(null));
        if (choice === 'rerun') {
          const spot = toolSpot(tool);
          if (spot === 'terminal') {
            p.spot('terminal');
            p.add(S.call(() => scene.after(scene.reduced ? 0 : 450, () => { scene.tween(st, 'lever', 1, 220, 'out'); st.termRun = true; st.exit = null; })), S.anim('lever', 1000), S.anim('watch_r', 1600));
          } else if (spot === 'cabinet') {
            p.spot('cabinet');
            p.add(S.call(() => scene.tween(st, 'drawer', 1, 300, 'out')), S.anim('rummage', 1200), S.call(() => scene.tween(st, 'drawer', 0, 300, 'inOut')));
          } else if (spot === 'bench') {
            p.spot('bench');
            p.add(S.anim('inspect', 1400));
          } else {
            p.sit();
            p.add(S.anim('write', 1400));
          }
          p.back();
        } else if (choice === 'stop') {
          p.to(a.data.desk.seatX, a.data.desk.seatY);
          p.add(S.call(() => { ds(a).box = true; }), S.anim('tidy', 1600), S.call(tidy));
        } else {
          p.back();
          p.add(S.anim('type', 800));
        }
        p.run(() => { a.hold = null; if (choice === 'stop') tidy(); });
      },
      hold_card(ev) {
        const pl = ev.payload || {};
        st.eventStatus = 'waiting_resume';
        st.eventCard = pl.missing || pl.text || quoted(ev.label) || '待恢复';
        st.doorEvent = '待恢复';
        scene.frozen = false;
        applyLights();
      },
      resume(ev, a) {
        st.eventStatus = 'working';
        st.eventCard = null; st.eventTool = null;
        st.doorEvent = null;
        scene.frozen = false;
        applyLights();
        roleActors().forEach((x) => {
          if (x.script) scene.cancel(x);
          setPersist(x, null);
          const p = plan(x);
          p.add(S.anim(x.seat ? 'stretch_sit' : 'stretch', undefined, x === a));
          p.back();
          p.run();
        });
      },
      assign(ev, a) {
        const mgr = byKind('manager') || primary();
        const target = roleActors().find((x) => x.id === ((ev.payload && ev.payload.to) || ev.role) && x !== mgr) || roleActors().find((x) => x !== mgr);
        if (!target) return;
        const d = target.data.desk;
        const gs = giveSpot(d);
        const p = plan(mgr);
        p.stand();
        p.add(S.hold('card_task'));
        p.to(gs[0], gs[1]);
        p.add(S.turn(gs[2]), S.anim('give', undefined, true), S.call(() => {
          ds(target).card = true;
          st.wbTags[target.id] = true;
        }), S.hold(null), S.anim('idle_happy', 400));
        p.back();
        p.run(() => { mgr.hold = null; ds(target).card = true; st.wbTags[target.id] = true; });
        if (scene.inTail(target)) scene.run(target, [S.anim('sit_up', 1600)], { tail: 0 });
      },
      hand_back(ev, a) {
        const mgr = byKind('manager') || primary();
        const worker = a === mgr ? roleActors().find((x) => x !== mgr) : a;
        if (!worker) return;
        const gs = giveSpot(mgr.data.desk);
        const p = plan(worker);
        p.stand();
        p.add(S.call(() => { ds(worker).card = false; }), S.hold('card_result'));
        p.to(gs[0], gs[1]);
        p.add(S.turn(gs[2]), S.anim('give', undefined, true), S.call(() => {
          ds(mgr).cardResult = true;
          st.wbDone[worker.id] = true;
        }), S.hold(null), S.anim('idle_happy', 400));
        p.back();
        p.run(() => { worker.hold = null; ds(mgr).cardResult = true; st.wbDone[worker.id] = true; });
        if (scene.inTail(mgr)) scene.run(mgr, [S.anim(mgr.seat ? 'sit_happy' : 'idle_happy', 1800)], { tail: 0 });
      },
      explore(ev, a) {
        const ex = byKind('explorer') || a;
        setPersist(ex, null);
        let filed = false;
        const file = () => { if (!filed) { filed = true; ds(ex).papers += 3; } };
        const p = plan(ex);
        p.stand();
        p.to(SPOT.door[0], SPOT.door[1]);
        p.add(S.call(openDoor), S.go(SPOT.doorIn[0], SPOT.doorIn[1]), S.fade(0, 260), S.call(closeDoor),
          S.wait(2400), S.hold('docs'), S.call(openDoor), S.fade(1, 260));
        p.x = SPOT.doorIn[0]; p.y = SPOT.doorIn[1];
        p.to(SPOT.door[0], SPOT.door[1], 'carry');
        p.add(S.call(closeDoor), S.anim('carry_f', 800, true));
        p.sit('carry');
        p.add(S.call(file), S.hold(null), S.anim('sit_happy', 800));
        p.run(() => { ex.alpha = 1; ex.hold = null; st.door = 0; file(); });
      },
      replan(ev, a) {
        const mgr = byKind('manager') || primary();
        // 擦掉后重写：被打断时直接换成新的计划
        let rewritten = false;
        const rewrite = () => { if (!rewritten) { rewritten = true; st.wbErase = 0; st.wbSeed += 1; st.wbSheet = false; st.wbTags = {}; st.wbDone = {}; } };
        const p = plan(mgr);
        p.spot('wb');
        p.add(S.call(() => { st.wbErase = 0; scene.tween(st, 'wbErase', 1, 1400, 'linear'); }), S.anim('board_erase', 1500, true),
          S.call(rewrite), S.anim('board_write', 1600), S.anim('back', 300));
        p.back();
        p.run(rewrite);
      },
      semantic(ev, a) {
        const d = a.data.desk;
        scene.fly({ bmp: 'card', from: [d.seatX, ROW_B - 22], to: [L.cards.x + 12, L.cards.base - 32], ms: 900, arc: 30, onDone: () => { st.cards += 1; st.cardFlash = scene.realT + 1600; } });
        if (scene.inTail(a)) scene.run(a, [S.anim(a.seat ? 'sit_up' : 'look_l', 1200)], { tail: 0 });
      },
      push_cart(ev, a) {
        const p = plan(a);
        p.to(SPOT.door[0], SPOT.door[1]);
        p.add(S.call(() => { openDoor(); st.cart.box = 'box_sealed'; st.cart.x = SPOT.door[0] + 4; st.cart.pushed = true; }), S.anim('side_reach', 400), S.call(closeDoor));
        p.to(SPOT.racks[0] + 14, SPOT.racks[1] + 2, 'push', 30);
        p.add(S.turn(-1), S.anim('side_reach', 700, true), S.call(() => {
          st.cart.box = null; st.rackOn = true; st.rackFlash = scene.realT + 1800;
          scene.emit('spark', L.back.x + 14, BASE - 40, 12, { color: PAL.green1 });
        }), S.anim('idle_happy', 500));
        p.to(300, ROW_A, 'push', 30);
        p.add(S.call(() => { st.cart.pushed = false; st.cart.x = 296; }));
        p.back();
        p.run(() => { st.cart.pushed = false; st.cart.box = null; st.cart.x = 296; st.rackOn = true; });
      },
      run_alarm(ev, a) {
        st.alarmUntil = scene.realT + 9000;
        const p = plan(a);
        p.stand();
        p.add(S.icon({ kind: 'exclaim' }), S.anim('shock', 400));
        p.to(SPOT.racks[0], SPOT.racks[1], 'run', 90);
        p.add(S.icon(null), S.anim('board_write', 1400, true), S.anim('back', 1400));
        p.back();
        p.run();
      },
      hold_form(ev, a) {
        const pl = ev.payload || {};
        const text = '待授权：' + (pl.kind || pl.action || quoted(ev.label) || '外部动作');
        // 就地举起申请单：坐着时先站起来
        const p = plan(a);
        p.stand();
        p.add(S.call(() => { a.data.formSign = text; }), S.anim('hold_form', 1600, true));
        p.mark();
        p.add(S.anim('hold_form', 3600), S.call(() => { a.data.formSign = null; }));
        p.sit();
        p.run(() => { a.data.formSign = null; });
      }
    };

    function commandDone(ev, a) {
      const pl = ev.payload || {};
      const code = pl.exitCode !== undefined ? pl.exitCode : pl.exit_code !== undefined ? pl.exit_code : (pl.receipt && pl.receipt.exitCode);
      const timedOut = Boolean(pl.timedOut || pl.timed_out || (pl.receipt && pl.receipt.timedOut));
      st.termRun = false;
      st.exit = timedOut ? 'red' : code === 0 || pl.ok === true ? 'green' : 'red';
      if (timedOut) st.smokeUntil = scene.realT + 4200;
      scene.tween(st, 'lever', 0, 300, 'inOut');
      const ok = st.exit === 'green';
      const p = plan(a);
      p.spot('terminal');
      p.add(S.icon({ kind: timedOut ? 'exclaim' : ok ? 'check' : 'cross' }), S.anim(ok ? 'idle_happy' : 'stand_sad', 1200, true), S.icon(null));
      p.back();
      p.run();
    }

    // 交接：本部门交出或收到交接物件时，送件小人进出房间
    function transition(ev) {
      const pl = ev.payload || {};
      const art = pl.artifact;
      const ci = pl.colorIndex;
      if (pl.from === dept) {
        if (dept === 'product' && art === 'prd') courier({ at: SPOT.rack, back: true, take: 'scroll', colorIndex: ci });
        else if (dept === 'engineering' && art === 'box' && st.bench.item === 'box_sealed') courier({ at: SPOT.benchSide, take: 'box_sealed', colorIndex: ci, onArrive: () => { st.bench.item = null; st.bench.mark = null; } });
        else if (dept === 'quality' && art === 'release') courier({ at: SPOT.benchSide, take: 'box_release', colorIndex: ci, onArrive: () => { st.bench.item = null; st.bench.slip = null; st.bench.slipMark = null; } });
        else if (dept === 'quality' && art === 'defect' && st.bench.item) courier({ at: SPOT.benchSide, take: 'box_rework', colorIndex: ci, onArrive: () => { st.bench.item = null; st.bench.slip = null; st.bench.slipMark = null; } });
      } else if (pl.to === dept) {
        const pa = primary();
        const d = pa.data.desk;
        if (art === 'prd') courier({ at: [d.x - 8, ROW_B, 1], bring: 'scroll', colorIndex: ci, onArrive: () => { ds(pa).scroll = true; } });
        else if (art === 'box') courier({ at: SPOT.benchSide, bring: 'box_sealed', colorIndex: ci, onArrive: () => { st.bench.item = 'box_sealed'; st.bench.mark = { text: '封存', color: PAL.blue2 }; st.bench.slip = null; st.bench.slipMark = null; st.bench.ticks = 0; } });
        else if (art === 'defect') courier({ at: isOps() ? [d.x - 8, ROW_B, 1] : SPOT.benchSide, bring: 'box_rework', colorIndex: ci, onArrive: () => { if (isOps()) ds(pa).box = true; else { st.bench.item = 'box_rework'; st.bench.slip = 'defect'; st.bench.slipMark = { text: '返工', color: PAL.red2 }; } } });
        else if (art === 'release' && isOps()) courier({ at: [d.x - 8, ROW_B, 1], bring: 'box_sealed', colorIndex: ci, onArrive: () => { ds(pa).box = true; } });
      }
    }

    function playEvent(ev) {
      if (!ev || !ev.type) throw new Error('playEvent 需要事件对象');
      const pl = ev.payload || {};
      const related = !ev.department || ev.department === dept || pl.from === dept || pl.to === dept;
      if (!related) return;
      if (ev.type === 'transition') { transition(ev); return; }
      if (ev.type === 'collaboration_closed') {
        roleActors().forEach((x) => { if (x.script && x.anim === 'wait') scene.cancel(x); });
        if (st.eventStatus === 'asking') st.eventStatus = null;
        return;
      }
      const action = P.resolveAction(ev);
      if (!action) {
        if (ev.type === 'tool_started') {
          const a = actorFor(ev);
          setPersist(a, { anim: 'type' });
        }
        return;
      }
      const fn = handlers[action];
      if (!fn) return;
      // 分派任务与重新规划由经理做，探索由探索者做；事件的 role 为被分派的角色
      const a = (action === 'assign' || action === 'replan') ? (byKind('manager') || primary())
        : action === 'explore' ? (byKind('explorer') || actorFor(ev)) : actorFor(ev);
      if (scene.frozen && action !== 'resume' && action !== 'puzzled' && action !== 'hold_card') return;
      if (a.data.role && a.data.role.status === 'away' && action !== 'explore') return;
      // 只改变房间物件的事件不影响小人正在做和排队的动作
      if (SIDE_ONLY.has(action)) { fn(ev, a); return; }
      // 正在做同一个动作时，重复的事件并入当前动作（告警只延长告警灯）
      if (!IMMEDIATE.has(action) && !scene.inTail(a) && a.data.doing === action) {
        if (action === 'run_alarm') st.alarmUntil = scene.realT + 9000;
        return;
      }
      if (action !== 'slump' && action !== 'failed') ds(a).redLamp = false;
      // 新动作开始时去掉上一个动作留在头顶的图标
      const start = () => {
        a.icon = null;
        a.data.doing = action;
        fn(ev, a);
      };
      // 状态类动作立即执行；其他动作在当前动作的主要部分做完后执行
      if (IMMEDIATE.has(action) || scene.inTail(a)) {
        a.data.queue = [];
        start();
        return;
      }
      a.data.queue = a.data.queue || [];
      a.data.queue.push({ fn: start, at: scene.realT });
      if (a.data.queue.length > 3) a.data.queue.shift();
    }
    const SIDE_ONLY = new Set(['guidance_in', 'semantic', 'freeze']);
    const IMMEDIATE = new Set(['paused', 'failed', 'done', 'cancelled', 'puzzled', 'hold_card', 'resume']);

    // -------------------------------------------------------------------------
    // 绘制：背景

    function buildBackground() {
      const key = dept + '|' + level;
      if (bg && bgKey === key) return bg;
      bgKey = key;
      bg = P.makeCanvas(W, H);
      const c = bg.getContext('2d');
      c.imageSmoothingEnabled = false;
      // 墙
      R(c, 0, 0, W, 120, D.wall);
      if (dept === 'product') {
        for (let x = 4; x < W; x += 12) R(c, x, 6, 2, 88, D.wall2);
        R(c, 0, 92, W, 3, D.trim); R(c, 0, 95, W, 21, D.wall3);
        for (let x = 0; x < W; x += 20) R(c, x, 95, 1, 21, D.trim);
      } else if (dept === 'engineering') {
        for (let y = 6; y < 116; y += 16) R(c, 0, y, W, 1, D.wall2);
        for (let x = 0; x < W; x += 24) R(c, x, 6, 1, 110, D.wall2);
        R(c, 0, 7, W, 4, PAL.metal3); R(c, 0, 7, W, 1, PAL.metal2);
        for (let x = 30; x < W; x += 90) R(c, x, 5, 4, 8, PAL.metal4);
      } else if (dept === 'quality') {
        R(c, 0, 86, W, 5, D.rug); R(c, 0, 91, W, 25, D.wall2);
        for (let x = 6; x < W; x += 30) R(c, x, 20, 1, 60, P.mix(D.wall, D.wall2, 0.5));
      } else {
        for (let x = 0; x < W; x += 24) { R(c, x, 6, 1, 110, D.wall3); R(c, x + 3, 12, 1, 1, PAL.grey3); R(c, x + 3, 100, 1, 1, PAL.grey3); }
        R(c, 0, 6, W, 6, PAL.grey5); R(c, 0, 12, W, 1, PAL.grey4);
        [PAL.red3, PAL.blue3, PAL.yellow3, PAL.green3].forEach((col, i) => {
          for (let x = 0; x < W; x += 2) R(c, x, 12 + Math.round(2 + Math.sin(x / (18 + i * 5) + i) * 2) + i, 1, 1, col);
        });
      }
      // 天花板与踢脚线
      R(c, 0, 0, W, 5, D.trim); R(c, 0, 5, W, 1, P.mix(D.trim, PAL.ink, 0.3));
      R(c, 0, 114, W, 6, D.trim); R(c, 0, 114, W, 1, P.mix(D.trim, PAL.white, 0.2));
      // 地面
      R(c, 0, 120, W, H - 120, D.floor);
      if (dept === 'product') {
        for (let y = 120, i = 0; y < H; y += 8, i++) {
          R(c, 0, y, W, 1, D.floor3);
          for (let x = (i % 2) * 24; x < W; x += 48) R(c, x, y, 1, 8, D.floor2);
        }
      } else if (dept === 'engineering') {
        for (let y = 120; y < H; y += 20) for (let x = 0; x < W; x += 20) {
          R(c, x, y, 20, 20, ((x + y) / 20) % 2 ? D.floor : D.floor2);
          R(c, x, y, 20, 1, D.floor3); R(c, x, y, 1, 20, D.floor3);
        }
      } else if (dept === 'quality') {
        for (let y = 120; y < H; y += 12) for (let x = 0; x < W; x += 12) R(c, x, y, 12, 12, ((x + y) / 12) % 2 ? D.floor : D.floor2);
      } else {
        for (let y = 122; y < H; y += 4) for (let x = (y % 8 ? 2 : 0); x < W; x += 4) R(c, x, y, 1, 1, D.floor3);
        for (let x = 280; x < 400; x += 8) { R(c, x, 150, 4, 3, PAL.yellow2); R(c, x + 4, 150, 4, 3, PAL.ink); }
      }
      R(c, 0, 120, W, 3, 'rgba(0,0,0,0.12)');
      // 地毯：铺在工位下面
      if (dept !== 'operations') paint.rug(c, 4, 200, 300, 34, D.rug, D.rug2);
      // 装饰
      if (dept === 'product') {
        paint.poster(c, 236, 20, 28, 34, PAL.white, (cc, x, y) => {
          R(cc, x + 4, y + 5, 20, 14, '#ffe3a3'); R(cc, x + 11, y + 8, 6, 6, PAL.yellow2); R(cc, x + 13, y + 14, 2, 3, PAL.grey3);
          R(cc, x + 4, y + 23, 16, 1, PAL.pline); R(cc, x + 4, y + 27, 12, 1, PAL.pline);
        });
        P.RB(c, 272, 44, 34, 3, PAL.wood3);
        [PAL.red2, PAL.blue2, PAL.green2, PAL.yellow2, D.main].forEach((col, i) => R(c, 274 + i * 6, 32 + (i % 2) * 2, 5, 12 - (i % 2) * 2, col));
      } else if (dept === 'engineering') {
        paint.poster(c, 234, 18, 42, 36, '#2f5da8', (cc, x, y, w, h) => {
          for (let i = 4; i < w; i += 6) R(cc, x + i, y + 2, 1, h - 4, '#4a78c2');
          for (let i = 4; i < h; i += 6) R(cc, x + 2, y + i, w - 4, 1, '#4a78c2');
          R(cc, x + 12, y + 10, 16, 16, PAL.white); R(cc, x + 14, y + 12, 12, 12, '#2f5da8'); R(cc, x + 18, y + 16, 4, 4, PAL.white);
        });
        P.RB(c, 282, 22, 24, 30, '#c79a62');
        for (let i = 0; i < 4; i++) for (let j = 0; j < 5; j++) R(c, 284 + i * 6, 24 + j * 6, 1, 1, '#8a6238');
        R(c, 286, 26, 2, 10, PAL.grey3); R(c, 292, 28, 6, 2, PAL.red2); R(c, 298, 26, 2, 12, PAL.yellow3);
      } else if (dept === 'quality') {
        paint.poster(c, 236, 20, 30, 34, PAL.white, (cc, x, y) => {
          [[6, 16], [8, 18], [10, 20], [12, 18], [14, 16], [16, 14], [18, 12], [20, 10]].forEach(([dx, dy]) => R(cc, x + dx, y + dy, 3, 3, PAL.green2));
          R(cc, x + 5, y + 27, 20, 1, PAL.pline);
        });
        P.RB(c, 276, 24, 30, 22, PAL.white2);
        for (let i = 0; i < 4; i++) { R(c, 279 + i * 7, 30, 4, 12, [PAL.blue1, PAL.pink1, PAL.green1, PAL.yellow1][i]); R(c, 279 + i * 7, 29, 4, 1, PAL.grey3); }
      } else {
        paint.poster(c, 236, 20, 40, 30, PAL.grey6, (cc, x, y, w, h) => {
          let py = y + 20;
          for (let i = 0; i < w - 6; i += 2) { const ny = y + 8 + Math.round(P.hash(i) * 14); R(cc, x + 3 + i, Math.min(py, ny), 1, Math.abs(py - ny) + 1, PAL.green2); py = ny; }
        });
        for (let i = 0; i < 3; i++) P.RB(c, 12, 18 + i * 12, 46, 8, PAL.grey4);
        for (let i = 0; i < 3; i++) for (let x = 14; x < 56; x += 3) R(c, x, 20 + i * 12, 1, 4, PAL.grey6);
      }
      return bg;
    }

    // -------------------------------------------------------------------------
    // 绘制：画面

    function draw(sc, c) {
      const t = sc.animT;
      const status = effStatus();
      const off = status === 'interrupted';
      c.drawImage(buildBackground(), 0, 0);

      // 墙上物件
      if (!isOps()) paint.window(c, L.window.x, L.window.y, { w: L.window.w, h: L.window.h, night: off }, t);
      paint.clock(c, L.clock.x, L.clock.y, st.clock, { stopped: off });
      paint.whiteboard(c, L.wb.x, L.wb.y, whiteboardOpts(), t);
      paint.corkboard(c, L.cork.x, L.cork.y, { w: L.cork.w, h: L.cork.h, notes: st.notes, done: st.notesDone, label: '部门指导' });
      const doorInfo = paint.door(c, L.door.x, L.door.base, { w: L.door.w, h: L.door.h, open: st.door });
      R(c, L.door.x + 4, L.door.base - L.door.h - 12, L.door.w - 8, 8, PAL.ink);
      R(c, L.door.x + 5, L.door.base - L.door.h - 11, L.door.w - 10, 6, D.main);
      if (P.levelAtLeast(level, 's3')) paint.beacon(c, L.beacon.x, L.beacon.y, { on: st.yellow }, t);
      if (isOps()) paint.beacon(c, L.back.x + 11, L.back.y !== undefined ? L.back.y : 50, { on: alarmOn(), color: 'red' }, t);
      L.lamps.forEach((lx) => paint.lamp(c, lx, 6, st.darkTarget === 0));

      // 地面物件与小人：按深度排序
      const items = [];
      items.push({ y: BASE, draw: () => { paint.cabinet(c, L.cabinet.x, L.cabinet.base, { open: st.drawer, blink: blinkTool('search') }, t); paint.archive(c, L.cabinet.x + 2, L.cabinet.base - 40, { n: model.summaries || 0, flash: sc.realT < st.archiveFlash }, t); } });
      if (P.levelAtLeast(level, 's4')) items.push({ y: BASE, draw: () => paint.cardCabinet(c, L.cards.x, L.cards.base, { cards: st.cards, flash: sc.realT < st.cardFlash, label: '语义记录' }, t) });
      items.push({ y: BASE, draw: () => { st.termInfo = paint.terminal(c, L.terminal.x, L.terminal.base, termOpts(), t); } });
      items.push({ y: BASE + 2, draw: () => paint.tray(c, L.tray.x, L.tray.base, { count: st.tray }) });
      items.push({ y: BASE, draw: () => drawBackPiece(c, t) });
      items.push({ y: BASE + 2, draw: () => { st.mailInfo = paint.mailbox(c, L.mailbox.x, L.mailbox.base, { count: mailCount() }, t); } });
      items.push({ y: BASE + 4, draw: () => paint.plant(c, L.plant.x, L.plant.base) });
      items.push({ y: 160, draw: () => paint.plant(c, 452, 160) });
      if (dept !== 'operations') items.push({ y: ROW_A + 0.5, draw: () => drawBench(c, t) });
      else {
        const cp = cartPos();
        items.push({ y: cp[1] - 1, draw: () => paint.cart(c, Math.round(cp[0]), Math.round(cp[1]), { box: st.cart.box }) });
      }
      st.desks.forEach((d) => {
        items.push({ y: ROW_B - 1, draw: () => paint.chair(c, d.seatX, ROW_B, { color: D.shade }) });
        items.push({ y: ROW_B + 0.5, draw: () => drawDesk(c, d, t) });
      });
      items.push({ y: st.bin.y, draw: () => paint.bin(c, st.bin.x, st.bin.y, { count: st.binCount }) });
      items.push({ y: ROW_B + 12, draw: () => drawTeaStation(c, t) });
      sc.actors.forEach((a) => { if (!a.seat) items.push({ y: a.y, draw: () => P.drawActor(c, sc, a) }); });
      items.sort((p, q) => p.y - q.y);
      items.forEach((it) => it.draw());

      sc.drawParticles(c);
      sc.drawFlyers(c);

      // 灯光
      if (st.dark > 0.01) { c.fillStyle = 'rgba(14,12,34,' + st.dark.toFixed(3) + ')'; c.fillRect(0, 0, W, H); }
      if (st.yellow) {
        const k = sc.reduced ? 0.1 : 0.07 + 0.05 * Math.sin(t / 240);
        c.fillStyle = 'rgba(255,196,40,' + k.toFixed(3) + ')';
        c.fillRect(0, 0, W, H);
      }
      if (alarmOn()) {
        const k = sc.reduced ? 0.1 : 0.06 + 0.06 * Math.max(0, Math.sin(t / 160));
        c.fillStyle = 'rgba(255,50,50,' + k.toFixed(3) + ')';
        c.fillRect(0, 0, W, H);
      }
      if (st.darkTarget === 0 && !off) L.lamps.forEach((lx) => paint.lightCone(c, lx, 12, 150, 110, '#fff1c9', 0.1));

      // 发光物件：画在灯光之上
      paint.crt(c, L.crt.x, L.crt.y, crtOpts(), t);
      drawScreens(c, t);
      if (P.levelAtLeast(level, 's3')) paint.beaconLight(c, L.beacon.x, L.beacon.y, { on: st.yellow, reduced: sc.reduced, len: 90 }, t);
      if (isOps()) paint.beaconLight(c, L.back.x + 11, 50, { on: alarmOn(), color: 'red', reduced: sc.reduced, len: 120 }, t);
      if (st.mailInfo && mailCount() > 0) paint.glow(c, st.mailInfo.lamp[0], st.mailInfo.lamp[1], 7, PAL.yellow2, 0.7);

      // 门牌、举牌、头顶图标
      const doorText = model.door || st.doorEvent;
      if (doorText) {
        const ss = P.signStyle(doorText);
        P.sign(c, doorInfo.nail[0], doorInfo.nail[1] + 18, doorText, { size: 7, bg: ss.bg, fg: ss.fg, stripe: ss.stripe, nail: doorInfo.nail[1], maxW: 96 });
      }
      P.text(c, D.name + '部门', L.door.x + L.door.w / 2, L.door.base - L.door.h - 8, { size: 5.5, weight: 700, align: 'center', color: PAL.white });
      sc.actors.forEach((a) => {
        if (!a.visible) return;
        if (a.sign && a.anim === 'hold_sign') drawHeldSign(c, sc, a, a.sign);
        if (a.data.formSign && a.anim === 'hold_form') {
          const [hx, hy] = P.headTop(sc, a);
          P.sign(c, hx, hy - 4, a.data.formSign, { size: 6.5, bg: PAL.white, stripe: PAL.orange2, maxW: 150 });
        }
        P.drawIcon(c, sc, a);
      });
    }

    // 茶水台：饮水机、茶壶与杯子
    function drawTeaStation(c, t) {
      const x = 404, y = ROW_B + 12;
      RB(c, x, y - 18, 40, 18, dept === 'operations' ? PAL.grey4 : PAL.wood2);
      R(c, x, y - 18, 40, 2, dept === 'operations' ? PAL.grey3 : PAL.wood1);
      R(c, x + 3, y - 13, 16, 10, dept === 'operations' ? PAL.grey5 : PAL.wood3);
      R(c, x + 21, y - 13, 16, 10, dept === 'operations' ? PAL.grey5 : PAL.wood3);
      // 饮水机
      RB(c, x + 24, y - 34, 12, 16, PAL.white2);
      RB(c, x + 25, y - 46, 10, 11, '#8fc8f0');
      R(c, x + 27, y - 44, 2, 7, '#c4e4fa');
      R(c, x + 26, y - 28, 3, 2, PAL.red2); R(c, x + 31, y - 28, 3, 2, PAL.blue2);
      P.drawBitmap(c, 'teapot', x + 4, y - 26);
      P.drawBitmap(c, 'cup', x + 14, y - 23);
    }

    function drawHeldSign(c, sc, a, text) {
      const [hx, hy] = P.headTop(sc, a);
      const ss = P.signStyle(/待恢复|缺少|凭据|模型/.test(text) ? '待恢复' : text);
      P.sign(c, hx, hy - 1, text, { size: 7, bg: ss.bg, fg: ss.fg, stripe: ss.stripe, maxW: 210, pole: 3 });
    }

    function alarmOn() { return isOps() && (st.alarmUntil > scene.realT || Boolean(model.alarm)); }
    // 推车停在工作台一排；运维推着走时跟在小人前面，底边与小人脚下对齐
    function cartPos() {
      if (!st.cart.pushed) return [st.cart.x, ROW_A + 12];
      const a = primary();
      return [a.x + (a.facing > 0 ? 6 : -32), a.y + 1];
    }
    function mailCount() { return model.mailbox || 0; }
    function blinkTool(tool) {
      if (effStatus() !== 'pending_verification') return false;
      const pt = st.eventTool || model.pendingTool;
      if (tool === 'desk') return pt === 'edit_range' || pt === 'write_file' || pt === 'read_file' || pt === 'read_range' || (pt && toolSpot(pt) === 'desk');
      return pt === tool;
    }

    function termOpts() {
      const off = effStatus() === 'interrupted';
      return { lever: st.lever, exit: off ? null : st.exit, screen: off ? 'off' : st.termRun ? 'term' : 'idle', blink: blinkTool('run_command') };
    }

    function crtOpts() {
      const s = effStatus();
      const cr = model.crt || {};
      const power = s === 'interrupted' ? 0 : 1;
      const lines = [
        { k: '目标', v: cr.target || '—' },
        { k: '模型', v: cr.model || '—' },
        { k: '协议', v: cr.protocol || '—' },
        { k: '状态', v: cr.status || STATUS_TEXT[s] || s, color: STATUS_COLOR[s] },
        { k: '循环', v: cr.cycle ? '第 ' + cr.cycle + ' 轮' : '—' }
      ];
      return { w: L.crt.w, h: L.crt.h, lines, power, boot: st.crtBoot < 1 ? st.crtBoot : undefined, dim: s === 'idle', cursor: s === 'working', alert: s === 'pending_verification' || s === 'waiting_resume', label: D.name + ' CRT' };
    }

    function whiteboardOpts() {
      const s4 = P.levelAtLeast(level, 's4');
      let lines;
      if (s4 && rolesOf(model).length === 1) {
        const r = rolesOf(model)[0];
        lines = [{ text: r.task || (model.crt && model.crt.target) || r.name, color: PAL.ink2 }, { color: PAL.blue3 }, { color: PAL.ink2 }];
      } else if (s4) {
        const roles = rolesOf(model).filter((r) => r.kind !== 'manager');
        lines = roles.map((r) => ({
          text: r.task || r.name,
          tag: (st.wbTags[r.id] || r.status === 'assigned' || r.status === 'working' || r.status === 'returned' || r.status === 'away') ? r.name : null,
          tagColor: r.status === 'returned' || st.wbDone[r.id] ? PAL.green1 : PAL.yellow1,
          done: r.status === 'returned' || st.wbDone[r.id]
        }));
      } else {
        lines = [0, 1, 2, 3].map((i) => ({ color: [PAL.blue3, PAL.ink2, PAL.red3, PAL.ink2][(i + st.wbSeed) % 4] }));
      }
      return { w: L.wb.w, h: L.wb.h, floor: L.wb.floor, title: s4 ? '部门账本' : '工作计划', lines, sheet: st.wbSheet, erase: st.wbErase, blink: false };
    }

    function drawBackPiece(c, t) {
      const x = L.back.x;
      if (dept === 'product') {
        paint.scrollRack(c, x, BASE, { count: st.scrolls, flash: scene.realT < st.scrollFlash, label: '卷轴架' }, t);
      } else if (dept === 'engineering') {
        RB(c, x, BASE - 50, 60, 50, PAL.metal3);
        R(c, x, BASE - 50, 60, 2, PAL.metal2);
        [BASE - 34, BASE - 17].forEach((sy) => R(c, x, sy, 60, 2, PAL.metal4));
        [[x + 4, BASE - 48], [x + 20, BASE - 48], [x + 38, BASE - 48], [x + 8, BASE - 31], [x + 30, BASE - 31], [x + 14, BASE - 14]].forEach(([bx, by], i) => {
          P.drawBitmap(c, i % 3 === 0 ? 'box_sealed' : 'box', bx, by + 3);
        });
        P.text(c, '交付存放', x + 30, BASE - 56, { size: 6, weight: 700, align: 'center', color: PAL.ink2 });
      } else if (dept === 'quality') {
        RB(c, x, BASE - 50, 60, 50, PAL.white2);
        R(c, x, BASE - 50, 60, 2, PAL.white);
        [BASE - 34, BASE - 17].forEach((sy) => R(c, x, sy, 60, 2, PAL.grey2));
        for (let r = 0; r < 3; r++) for (let q = 0; q < 5; q++) {
          const jx = x + 4 + q * 11, jy = BASE - 47 + r * 17;
          R(c, jx, jy + 2, 7, 11, PAL.ink); R(c, jx + 1, jy + 3, 5, 9, [PAL.blue1, PAL.green1, PAL.pink1, PAL.yellow1, PAL.glass][(q + r) % 5]);
          R(c, jx + 1, jy + 1, 5, 2, PAL.grey3);
        }
        P.text(c, '样本柜', x + 30, BASE - 56, { size: 6, weight: 700, align: 'center', color: PAL.ink2 });
      } else {
        paint.rack(c, x - 4, BASE, { on: st.rackOn, alarm: alarmOn(), label: model.version || 'r3', seed: 1, blink: scene.realT < st.rackFlash }, t);
        paint.rack(c, x + 28, BASE, { on: st.rackOn, alarm: alarmOn(), seed: 2 }, t);
        paint.rack(c, x + 60, BASE, { on: st.rackOn, alarm: false, seed: 3, h: 56 }, t);
      }
    }

    function drawBench(c, t) {
      const b = L.bench, bs = st.bench;
      const top = dept === 'engineering' ? PAL.metal1 : dept === 'quality' ? PAL.white : PAL.wood1;
      const face = dept === 'engineering' ? PAL.metal3 : dept === 'quality' ? D.light : PAL.wood2;
      paint.table(c, b.x, b.y, b.w, { top, face, edge: P.mix(face, PAL.ink, 0.3), label: BENCH_LABEL[dept] });
      const cx = b.x + Math.round(b.w / 2);
      if (dept === 'engineering') {
        // 胶带座与印台
        RB(c, b.x + b.w - 16, b.y - 9, 12, 5, PAL.red3); P.drawBitmap(c, 'tape', b.x + b.w - 13, b.y - 12);
        RB(c, b.x + 5, b.y - 6, 10, 3, PAL.blue3);
      }
      if (dept === 'quality') {
        // 台灯
        R(c, b.x + b.w - 10, b.y - 26, 2, 21, PAL.grey3); R(c, b.x + b.w - 20, b.y - 28, 12, 2, PAL.grey3);
        RB(c, b.x + b.w - 26, b.y - 30, 9, 5, PAL.grey4);
        if (st.darkTarget === 0 || bs.ticks) paint.lightCone(c, b.x + b.w - 22, b.y - 25, 18, 26, '#fff4c4', 0.28);
        // 清单
        RB(c, b.x + 5, b.y - 6, 14, 5, PAL.white);
        for (let i = 0; i < 3; i++) {
          R(c, b.x + 7 + i * 4, b.y - 5, 2, 2, i < bs.ticks ? PAL.green2 : PAL.grey2);
        }
      }
      if (bs.item === 'scroll_open') {
        RB(c, cx - 18, b.y - 6, 36, 5, PAL.paper);
        R(c, cx - 20, b.y - 7, 3, 7, PAL.wood3); R(c, cx + 17, b.y - 7, 3, 7, PAL.wood3);
        for (let i = 0; i < 3; i++) R(c, cx - 14 + i * 3, b.y - 4, 1, 1, PAL.pline);
        R(c, cx - 14, b.y - 4, 12, 1, PAL.pline);
      } else if (bs.item === 'scroll') {
        P.drawBitmap(c, 'scroll', cx - 5, b.y - 5);
      } else if (bs.item) {
        const bm = P.bitmapDef(bs.item);
        P.drawBitmap(c, bs.item, cx - Math.floor(bm.rows[0].length / 2), b.y - 3 - bm.rows.length);
        if (bs.item === 'box' && bs.tape > 0 && bs.tape < 1) R(c, cx - 1, b.y - 11, 2, Math.round(8 * bs.tape), '#efe0b8');
      }
      if (bs.mark) P.stampMark(c, cx + (bs.item === 'scroll_open' ? 6 : 0), b.y - (bs.item === 'scroll_open' ? 5 : 8), bs.mark.text, bs.mark.color, { size: 6 });
      if (bs.slip) {
        P.drawBitmap(c, bs.slip === 'release' ? 'slip_release' : 'slip_defect', cx + 14, b.y - 8);
        if (bs.slipMark) P.stampMark(c, cx + 17, b.y - 8, bs.slipMark.text, bs.slipMark.color, { size: 6, rot: -0.2 });
      }
      if (blinkTool('run_check')) paint.blinkFrame(c, b.x, b.y - 12, b.w, 24);
    }

    function monitorMode(a, d) {
      const s = effStatus();
      if (s === 'interrupted') return 'off';
      if (st.crtBoot < 1 && a === primary()) return 'boot';
      if (!a.visible) return 'idle';
      if (s === 'failed' || ds(a).redLamp) return 'error';
      if (s === 'done') return 'ok';
      if (s === 'idle' || s === 'paused' || s === 'cancelled' || s === 'waiting_resume') return 'idle';
      if (s === 'pending_verification') return a === primary() ? 'alert' : 'idle';
      if (a.anim === 'write' || (a.data.persist && a.data.persist.write)) return 'diff';
      if (a.anim === 'type' || a.anim === 'think') return 'code';
      return 'idle';
    }

    function drawDesk(c, d, t) {
      const a = scene.actors.find((x) => x.id === d.roleId);
      const s = ds(a);
      const seated = a && a.seat === d && a.visible;
      if (seated) P.drawActor(c, scene, a, 'base');
      paint.desk(c, d.x, d.y, { w: d.w, wood: dept === 'operations' ? [PAL.grey2, PAL.grey3, PAL.grey4, PAL.grey5] : dept === 'quality' ? [PAL.white, PAL.white2, PAL.white3, PAL.grey3] : null });
      paint.deskItems(c, d.x, d.y, {
        w: d.w, papers: s.papers, folder: s.folder, docOnDesk: s.doc, box: s.box, card: s.card, cardResult: s.cardResult,
        cup: !(a && (a.anim === 'tea' || a.anim === 'tea0')), monitor: null, lamp: s.redLamp ? 'red' : null, nameplate: d.role.name,
        plateColor: D.light, seed: d.i
      }, t);
      if (s.scroll) P.drawBitmap(c, 'scroll', d.x + 6, d.y - 5);
      if (s.plane) P.drawBitmap(c, 'plane', d.x + d.w / 2 - 12, d.y - 6);
      if (seated) {
        c.save();
        c.beginPath(); c.rect(0, 0, W, d.y); c.clip();
        P.drawActor(c, scene, a, 'front');
        c.restore();
      }
      if (blinkTool('desk') && a === primary()) paint.blinkFrame(c, d.x + d.w - 22, d.y - 19, 20, 16);
    }

    // 灯光之上重画屏幕，暗处的屏幕仍然发光
    function drawScreens(c, t) {
      st.desks.forEach((d) => {
        const a = scene.actors.find((x) => x.id === d.roleId);
        const mode = monitorMode(a, d);
        const mx = d.x + d.w - 22 + 3, my = d.y - 19 + 2;
        paint.screen(c, mx, my, 14, 9, mode, t, { seed: d.i, k: st.crtBoot });
        if (mode !== 'off' && mode !== 'idle') paint.glow(c, mx + 7, my + 4, 12, mode === 'error' ? PAL.red2 : mode === 'alert' ? PAL.yellow2 : PAL.screen3, 0.18);
        if (blinkTool('desk') && a === primary() && Math.floor(t / 300) % 2 === 0) R(c, mx, my, 14, 9, 'rgba(247,203,70,0.5)');
        if (ds(a).redLamp) {
          const on = scene.reduced || Math.floor(t / 350) % 2 === 0;
          if (on) paint.glow(c, d.x + d.w - 3, d.y - 8, 8, PAL.red2, 0.7);
        }
      });
      const ti = st.termInfo;
      if (ti) {
        const off = effStatus() === 'interrupted';
        paint.screen(c, L.terminal.x + 3, L.terminal.base - 34 + 3, 22, 13, off ? 'off' : st.termRun ? 'term' : 'idle', t, { seed: 3 });
        paint.scanlines(c, L.terminal.x + 3, L.terminal.base - 31, 22, 13, 0.18);
        if (st.exit && !off) paint.glow(c, ti.lampX, ti.lampY, 9, st.exit === 'green' ? PAL.green2 : PAL.red2, 0.8);
      }
    }

    // -------------------------------------------------------------------------
    // 接口

    function setModel(m) {
      if (!m) throw new Error('setModel 需要 roomModel');
      if (m.department && m.department !== dept) throw new Error('roomModel 的部门与画面不一致：' + m.department);
      const prevStatus = effStatus();
      model = Object.assign({}, m);
      if (m.level && m.level !== level) { level = m.level; P.levelAtLeast(level, 'now'); }
      st.eventStatus = null; st.eventCard = null; st.eventTool = null;
      if (m.pendingTool) st.lastPendingTool = m.pendingTool;
      if (m.door !== undefined) st.doorEvent = null;
      syncRoles();
      const s = effStatus();
      if (s !== prevStatus) {
        roleActors().forEach((a) => {
          if (s === 'interrupted') return;
          if (a.script && (s === 'waiting_resume' || s === 'pending_verification' || s === 'asking' || prevStatus === 'asking')) scene.cancel(a);
          if (s !== 'working') { a.data.persist = null; a.data.queue = []; }
        });
        if (s !== 'failed') roleActors().forEach((a) => { if (!a.data.persist) ds(a).redLamp = false; });
        if (s === 'cancelled') roleActors().forEach((a) => { const x = ds(a); x.papers = 0; x.folder = false; x.doc = false; x.box = true; });
        if (prevStatus === 'cancelled' && s !== 'cancelled') roleActors().forEach((a) => { ds(a).box = false; });
      }
      applyLights();
    }

    syncRoles();
    applyLights();
    st.dark = st.darkTarget;

    return {
      scene,
      setModel,
      playEvent,
      resize: () => scene.resize(),
      destroy: () => scene.destroy()
    };
  };
})();
