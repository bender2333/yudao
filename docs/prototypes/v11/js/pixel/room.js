// 部门房间画面（设计说明第 8.1 至 8.3 节）：房间布置、按 roomModel 决定的状态姿势、按事件播放的一次性动作。
(function () {
  const Y11 = window.Y11;
  const P = Y11.pixel;
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
    beacon: { x: 405, y: 44 },
    pipe: { x: 428, base: 176 },          // 交接管道口（3.2C 前也有）
    tube: { x: 428, base: 150 },          // 传信管口
    post: { x: 76, base: 182 },           // 门口的邮筒（3.2B）
    tool: { x: 330, y: 30, w: 46, h: 26 },// 墙上的 MCP 工具面板（3.2B）
    trial: { x: 216, w: 76, y: ROW_A },   // 质检试用台（3.2D）
    monitor: { x: 314, y: 44, w: 48, h: 30 }, // 运维监控屏（S4）
    backup: { x: 316, base: BASE },       // 备份柜（S4）
    mdoor: { x: 34, base: 182, w: 26, h: 40 } // 通往机房的门（S4）
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
    pipe: [420, 186, -1],
    tube: [418, 152, -1],
    post: [66, 186, 1],
    mdoor: [28, 186, 1],
    monitor: [352, 92, 1],
    tool: [350, 150, 1],
    trial: [254, ROW_A, 1]
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
    let level = o.level || 'ui';
    P.levelAtLeast(level, 'ui');
    if (level !== 'ui' && !Y11.LEVELS.includes(level)) throw new Error('未知档位：' + level);

    // 画面上的数量（信箱、档案盒编号、卷轴、钉着的纸条、语义卡片）一律取自 roomModel；
    // st 只保存动作过程中的临时状态，动作结束后画面回到只由数据决定的样子
    let model = {
      department: dept, level, status: 'idle', crt: {}, roles: [], pose: null, door: null,
      hold_card: null, pending_tool: null, mailbox: 0, summaries: 0, scrolls: 0, pinned_notes: 0, semantic_cards: 0,
      machine: null, remote_unknown: false, waiting_provider: false, pipes: null, existing_read: false,
      trial: null, tool_panel: null, self_test: null
    };
    const st = {
      dark: 0.36, darkTarget: 0.36, yellow: false,
      clock: 15.5 * 3600000, crtBoot: 1,
      drawer: 0, lever: 0, exit: null, termRun: false, smokeUntil: 0,
      // scrollHide、noteHide、cardHide：新加的一件在动作放上去之前先不显示，值为最迟恢复显示的时间
      trayPaper: false, scrollFlash: 0, scrollHide: 0, noteHide: 0, replyUntil: 0, cardHide: 0, cardFlash: 0,
      archiveFlash: 0,
      door: 0, doorEvent: null, eventStatus: null, eventCard: null, eventTool: null, lastPendingTool: null,
      bench: { item: null, mark: null, slip: null, slipMark: null, ticks: 0, tape: 0, until: 0 },
      wbSheetUntil: 0, wbErase: 0, wbSeed: 1, wbTags: {}, wbDone: {}, wbExisting: false,
      binUntil: 0, alarmUntil: 0, cart: { x: 296, box: null, pushed: false },
      backupLit: 0, backupFlash: 0, mdoorGlow: 0, monitorAlarmUntil: 0, postFlag: 0, toolLit: -1,
      eventRemote: false, eventMachine: null, eventWaiting: false, eventStep: 0, eventLines: null, selfShot: false,
      desks: [], deskState: {}, confettiAt: 0
    };
    // 动作留在桌上、工作台上的物件在动作结束后保留一段时间
    const PROP_KEEP = 7000;
    let bg = null;
    let bgKey = '';

    const scene = P.createScene(canvas, { W, H, draw, update });

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

    // Stage 5：中心角色在中央，工具角色在两侧，经理靠近门与管道口（设计说明第 8.1 与 8.2 节）
    const CENTER_KIND = { product: 'architect', engineering: 'architect', quality: 'tester', operations: 'ops' };
    const SLOT_X = [16, 92, 168, 244, 320];
    const TOOL_ORDER = ['lead', 'explorer', 'reviewer', 'architect', 'tester'];

    function layoutDesks(roles) {
      const n = roles.length;
      if (n <= 1) return [{ x: 150, w: 64 }];
      if (!P.levelAtLeast(level, 'S5')) {
        const w = n >= 5 ? 54 : 60, gap = n >= 5 ? 6 : n === 4 ? 16 : 30;
        const total = n * w + (n - 1) * gap;
        const x0 = Math.round((296 - total) / 2) + 4;
        const out = [];
        for (let i = 0; i < n; i++) out.push({ x: x0 + i * (w + gap), w });
        return out;
      }
      const centerIdx = roles.findIndex((r) => r.kind === CENTER_KIND[dept]);
      const mgrIdx = roles.findIndex((r) => r.kind === 'manager');
      const toolCount = Math.max(0, n - (centerIdx >= 0 ? 1 : 0) - (mgrIdx >= 0 ? 1 : 0));
      const TOOL_SLOTS = { 1: [1], 2: [0, 3], 3: [0, 1, 3], 4: [0, 1, 3, 4] };
      const tools = (TOOL_SLOTS[toolCount] || [0, 1, 3, 4]).slice();
      return roles.map((r, i) => {
        let slot;
        if (i === centerIdx) slot = 2;
        else if (i === mgrIdx) slot = 4;
        else slot = tools.shift();
        return { x: SLOT_X[slot === undefined ? 0 : slot], w: 56 };
      });
    }

    function syncRoles() {
      const roles = rolesOf(model);
      const lay = layoutDesks(roles);
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
        // papers 为桌上固定的纸堆；folder、doc 等为动作放在桌上的物件，值为保留到的时间
        if (!st.deskState[r.id]) st.deskState[r.id] = { papers: 3 + (i % 3), hidePapers: false, folder: 0, doc: 0, box: 0, card: 0, cardResult: 0, scroll: 0, letter: 0, redLamp: false };
        return d;
      });
      const prim = primary();
      st.bin = { x: st.desks[0].x + st.desks[0].w + 2, y: ROW_B + 9 };
      if (prim && prim.data.desk) st.bin.x = prim.data.desk.x + prim.data.desk.w + 2;
      // 质检的试用台座位（3.2D）
      st.trialSeat = dept === 'quality' && P.levelAtLeast(level, '3.2D')
        ? { seatX: SPOT.trial[0], seatY: SPOT.trial[1], trial: true } : null;
    }

    function roleActors() { return scene.actors.filter((a) => a.data.role); }
    function primary() {
      const list = roleActors();
      return list.find((a) => a.data.role.kind === CENTER_KIND[dept])
        || list.find((a) => a.data.role.kind === 'manager') || list[0];
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
    function keep(a, key) { ds(a)[key] = scene.realT + PROP_KEEP; }
    function drop(a, key) { ds(a)[key] = 0; }
    function shown(s, key) { return s[key] > scene.realT; }

    // 说话气泡：小人开始做一件事时头顶说一句话（内容来自 P.say，js/pixel/say.js），说完在头顶留一段时间
    function nameOfRole(k) {
      const x = roleActors().find((r) => r.id === k || r.data.role.kind === k || r.data.role.name === k);
      return x ? x.data.role.name : null;
    }
    // side 为 'to' 表示这个小人是事件里收东西的一方
    function say(ev, a, side) {
      const text = P.say(ev, { dept, side, roleName: nameOfRole });
      if (a && text) a.data.say = { text, until: scene.realT + P.sayMs(text) };
    }

    // 询问信的两端：发问的部门与回答的部门（示例数据里回答事件的 from 是回答方，v8 构建约定里 to 是回答方）
    function letterSides(ev) {
      const pl = ev.payload || {};
      if (ev.type === 'collaboration_requested') return { asker: pl.from || ev.department, answerer: pl.to };
      const answerer = ev.department || pl.to;
      return { asker: pl.from === answerer ? pl.to : pl.from, answerer };
    }
    // 工作台上的物件：每次改动后保留 12 秒，之后工作台回到空的样子
    function tickBench() {
      const b = st.bench;
      const sig = [b.item, b.mark && b.mark.text, b.slip, b.slipMark && b.slipMark.text, b.ticks, b.tape].join('|');
      if (sig !== b.sig) { b.sig = sig; b.until = scene.realT + 12000; }
      if ((b.item || b.slip) && b.until <= scene.realT) Object.assign(b, { item: null, mark: null, slip: null, slipMark: null, ticks: 0, tape: 0 });
    }

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

    // 交接到达时放在房间里的位置（物件由数据决定，动作只播放一次）
    function arrivalArt(a, art) {
      if (art === 'prd') keep(a, 'scroll');
      else if (art === 'box') { st.bench.item = 'box_sealed'; st.bench.mark = { text: '封存', color: PAL.blue2 }; st.bench.slip = null; st.bench.slipMark = null; st.bench.ticks = 0; }
      else if (art === 'defect') {
        if (isOps()) keep(a, 'box');
        else { st.bench.item = 'box_rework'; st.bench.slip = 'defect'; st.bench.slipMark = { text: '返工', color: PAL.red2 }; }
      } else if (art === 'release') {
        if (isOps()) keep(a, 'box');
        else { st.bench.item = 'box_sealed'; st.bench.slip = 'release'; st.bench.slipMark = null; }
      }
    }

    // -------------------------------------------------------------------------
    // 状态

    function effStatus() { return st.eventStatus || model.status || 'idle'; }
    function isOps() { return dept === 'operations'; }
    function opsRoom() { return isOps() && P.levelAtLeast(level, 'S4'); }
    function waitingProvider() { return Boolean(model.waiting_provider || st.eventWaiting); }
    function remoteUnknown() { return Boolean(model.remote_unknown || st.eventRemote); }
    function machineName() { return st.eventMachine || model.machine || null; }
    function lettersWaiting() { return (model.pipes && model.pipes.letters_waiting) || 0; }
    function pipeMode() {
      if (effStatus() === 'interrupted' || waitingProvider()) return 'stopped';
      return (model.pipes && model.pipes.out) || 'idle';
    }

    function applyLights() {
      const s = effStatus();
      const wait = waitingProvider();
      const target = s === 'interrupted' ? 0.74 : wait ? 0.42 : (s === 'working' || s === 'asking' || s === 'pending_verification' || s === 'done') ? 0 : 0.36;
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
        const tool = st.eventTool || model.pending_tool;
        const spot = toolSpot(tool);
        if (spot === 'desk') return seatRest('sit_scratch', { icon: { kind: 'question' } });
        const sp = SPOT[spot];
        return standRest(sp[0], sp[1], 'puzzled', { icon: { kind: 'question' }, facing: sp[2] || 1 });
      }
      if (s === 'waiting_resume' && isPrim) {
        return standRest(SPOT.center[0], SPOT.center[1], 'hold_sign', { sign: model.hold_card || st.eventCard || '待恢复' });
      }
      if (s === 'asking' && isPrim) return standRest(SPOT.door[0] - 14, SPOT.door[1] + 2, 'wait', { facing: 1 });
      // 等待模型服务：坐在工位上看着墙上的时钟（Stage 4）
      if (waitingProvider() && isPrim && (s === 'working' || s === 'idle')) return seatRest('sit_up');
      // 远程动作结果未知：盯着终端，头顶黄色问号（3.2C）
      if (remoteUnknown() && isPrim) return standRest(SPOT.terminal[0], SPOT.terminal[1], 'watch_r', { icon: { kind: 'question' }, facing: 1 });
      // 试用台：测试工程师坐在试用台前（3.2D）
      if (st.trialSeat && model.trial && r.kind === 'tester') {
        return { x: st.trialSeat.seatX, y: st.trialSeat.seatY, seat: st.trialSeat, anim: 'type', facing: 1 };
      }
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
      if (model.pose && (model.pose.role_id === a.id || (!model.pose.role_id && isPrim))) {
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
        if (r.seat && r.seat !== a.data.desk) {
          // 试用台等不在工位上的座位：走到位置坐下
          p.to(r.x, r.y);
          p.steps.push(S.seat(r.seat), S.turn(r.facing || 1));
          p.seated = true;
        } else if (r.seat) {
          p.sit();
        } else {
          p.to(r.x, r.y);
        }
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
      tickBench();
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
        const place = () => { if (!placed) { placed = true; keep(a, 'folder'); } };
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
        p.add(S.call(() => scene.tween(st, 'drawer', 1, 300, 'out')), S.anim('rummage', 1300), S.anim('magnify', 1600, true),
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
        p.add(S.call(() => { keep(a, 'doc'); }), S.anim('write', 1800, true));
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
          scene.fly({ bmp: 'paperball', from: [a.x + 6, a.y - 20], to: [st.bin.x + 5, st.bin.y - 10], ms: 650, arc: 22, ease: 'linear', onDone: () => { st.binUntil = scene.realT + 3500; } });
        })), S.anim('throw', 1000, true));
        p.back();
        p.run(() => { a.hold = null; });
      },
      submit(ev, a) {
        setPersist(a, null);
        let placed = false;
        // 托盘里的纸只在提案送进去之后出现，提案被接纳或退回时清空
        const place = () => { if (!placed) { placed = true; st.trayPaper = true; a.hold = null; } };
        const p = plan(a);
        p.stand();
        p.add(S.hold('doc'), S.call(() => { drop(a, 'doc'); }));
        p.spot('tray', 'carry');
        p.add(S.call(() => scene.after(scene.reduced ? 0 : 450, place)), S.anim('side_place', 700, true), S.anim('side', 300));
        p.back();
        p.run(place);
      },
      returned(ev, a) {
        setPersist(a, null);
        const d = a.data.desk;
        st.trayPaper = false;
        scene.fly({ bmp: 'doc', from: [L.tray.x + 13, L.tray.base - 24], to: [d.x + d.w / 2 - 8, ROW_B - 6], ms: 800, arc: 26, onDone: () => { keep(a, 'doc'); } });
        const p = plan(a);
        p.sit();
        p.add(S.anim('sit_up', 700), S.icon({ kind: 'question' }), S.anim('sit_scratch', 1800, true), S.icon(null));
        p.run(() => { keep(a, 'doc'); });
      },
      stamp_valid(ev, a) {
        setPersist(a, null);
        // 盖章之后卷轴要放上卷轴架；被下一个动作打断时直接放上去
        let shelved = false;
        // 卷轴数取自 roomModel.scrolls；新卷轴在放上架子之前先不显示
        const shelve = () => { if (!shelved) { shelved = true; st.scrollHide = 0; st.scrollFlash = scene.realT + 1500; st.bench.item = null; st.bench.mark = null; } };
        const p = plan(a);
        p.add(S.call(() => { st.bench.item = 'scroll_open'; st.bench.mark = null; }));
        p.spot('bench');
        p.add(...stampSteps('stamp_valid', () => { st.bench.mark = { text: '有效', color: '#d4353f' }; }, 'stamp'));
        p.add(S.anim('idle_happy', 400), S.call(() => { st.bench.item = null; st.bench.mark = null; }), S.hold('scroll'));
        p.spot('pipe', 'carry');
        p.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
          a.hold = null;
          scene.fly({ bmp: 'scroll', from: [a.x + 6, a.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8, ease: 'linear', onDone: shelve });
        })), S.anim('side_reach', 900, true));
        p.back();
        p.run(() => { a.hold = null; shelve(); });
      },
      pin_plan(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.stand();
        p.add(S.hold('doc'));
        p.spot('wb', 'carry');
        p.add(S.anim('board_pin', undefined, true), S.call(() => { st.wbSheetUntil = scene.realT + PROP_KEEP; }), S.hold(null), S.anim('back', 500), S.anim('idle_happy', 400));
        p.back();
        p.run(() => { if (st.wbSheetUntil < scene.realT) st.wbSheetUntil = scene.realT + PROP_KEEP; a.hold = null; });
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
          const pa = primary();
          const p2 = plan(pa);
          p2.stand();
          p2.spot('bench');
          p2.add(S.call(() => { st.bench.item = null; st.bench.mark = null; }), S.hold('box_sealed'));
          p2.spot('pipe', 'carry');
          p2.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
            pa.hold = null;
            scene.fly({ bmp: 'box_sealed', from: [pa.x + 6, pa.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8, ease: 'linear' });
          })), S.anim('side_reach', 900, true));
          p2.back();
          p2.run(() => { pa.hold = null; });
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
        p.add(S.icon({ kind: 'check' }), S.anim('idle_happy', 700), S.icon(null));
        p.add(S.call(() => { st.bench.item = null; st.bench.slip = null; st.bench.slipMark = null; }), S.hold('box_sealed'));
        p.spot('pipe', 'carry');
        p.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
          a.hold = null;
          scene.fly({ bmp: 'box_sealed', from: [a.x + 6, a.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8, ease: 'linear' });
        })), S.anim('side_reach', 900, true));
        p.back();
        p.run(() => { a.hold = null; st.bench.item = null; st.bench.slip = null; st.bench.slipMark = null; });
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
          const pa = primary();
          const p2 = plan(pa);
          p2.stand();
          p2.spot('bench');
          p2.add(S.call(() => { st.bench.item = null; st.bench.slip = null; st.bench.slipMark = null; }), S.hold('box_rework'));
          p2.spot('pipe', 'carry');
          p2.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
            pa.hold = null;
            scene.fly({ bmp: 'box_rework', from: [pa.x + 6, pa.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8, ease: 'linear' });
          })), S.anim('side_reach', 900, true));
          p2.back();
          p2.run(() => { pa.hold = null; });
        });
      },
      // 发出询问：写纸条装进信筒，塞进传信管口，在管道口等待（设计说明第 8.3 节）
      send_letter(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.sit();
        p.add(S.anim('write', 1200), S.hold('letter'));
        p.spot('tube', 'carry');
        p.add(S.anim('side_place', 800, true), S.call(() => { a.hold = null; }), S.anim('wait', 2600, true));
        p.back();
        p.run(() => { a.hold = null; });
      },
      // 从传信管口取出信筒：收到询问的一方与收到回答的一方读信，回答方读完询问以后写回答塞回；发问方在管道口接住回答
      answer_letter(ev, a) {
        setPersist(a, null);
        const sides = letterSides(ev);
        const reads = ev.type === 'collaboration_requested' || sides.asker === dept;
        const p = plan(a);
        const take = (ms) => S.call(() => {
          scene.fly({ bmp: 'letter', from: [L.tube.x + 4, L.tube.base - 8], to: [a.x + 4, a.y - 20], ms, arc: 8, onDone: () => { a.hold = 'letter'; } });
        });
        p.spot('tube');
        p.add(take(600), S.anim('reach', 800, true), S.anim('catch', 700));
        if (reads) {
          p.add(S.anim('read_stand', 1500, true), S.hold(null));
        } else {
          p.add(S.hold('letter'), S.anim('write', 1400));
          p.add(S.anim('side_place', 800, true), S.call(() => { a.hold = null; }), S.anim('wait', 900, true));
        }
        p.back();
        p.run(() => { a.hold = null; });
      },
      // 信箱数字以 roomModel.mailbox 为准，这里只播放纸条从门缝滑进信箱
      guidance_in() {
        const slot = [L.door.x + 18, L.door.base - 9];
        scene.fly({ bmp: 'note', from: slot, to: [L.mailbox.x + 7, L.mailbox.base - 9], ms: 700, arc: 2, ease: 'out' });
      },
      // 钉着的纸条数取自 roomModel.pinned_notes；读完的纸条在钉上之前先不显示
      guidance_read(ev, a) {
        setPersist(a, null);
        const pin = () => { st.noteHide = 0; };
        const p = plan(a);
        p.spot('mailbox');
        p.add(S.anim('crouch', 700), S.hold('note'), S.anim('read_stand', 1400));
        p.spot('cork');
        p.add(S.call(() => scene.after(scene.reduced ? 0 : 450, () => {
          a.hold = null;
          const k = Math.max(0, (model.pinned_notes || 1) - 1) % 6;
          scene.fly({ bmp: 'note', from: [SPOT.cork[0], SPOT.cork[1] - 24], to: [L.cork.x + 3 + (k % 3) * 9, L.cork.y + 4 + Math.floor(k / 3) * 13], ms: 350, arc: 4, onDone: pin });
        })), S.anim('note_pin', undefined, true), S.hold(null), S.anim('back', 500));
        p.back();
        p.run(() => { a.hold = null; pin(); });
      },
      // 在最新的纸条上写回复：写完时纸条上出现勾，过一会儿恢复
      guidance_reply(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.spot('cork');
        p.add(S.anim('board_write', 1700, true), S.call(() => { st.replyUntil = scene.realT + 3000; }), S.anim('back', 400));
        p.back();
        p.run();
      },
      compact(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.stand();
        // 档案盒编号以 roomModel.summaries 为准，这里只播放整理纸堆、放进档案盒
        p.add(S.anim('gather', 1000), S.call(() => { ds(a).hidePapers = true; drop(a, 'folder'); }), S.hold('docs'));
        p.spot('archive', 'carry');
        p.add(S.call(() => {
          a.hold = null;
          scene.fly({ bmp: 'docs', from: [a.x - 8, a.y - 22], to: [L.cabinet.x + 12, L.cabinet.base - 50], ms: 450, arc: 10, onDone: () => { st.archiveFlash = scene.realT + 1600; } });
        }), S.anim('side_place', 900, true), S.anim('idle_happy', 600));
        p.back();
        p.run(() => { a.hold = null; ds(a).hidePapers = false; });
      },
      compact_fail(ev, a) {
        setPersist(a, null);
        const d = a.data.desk;
        ds(a).hidePapers = true;
        scene.emit('paper', d.x + 10, ROW_B - 8, ds(a).papers * 2, { floor: ROW_B - 12 });
        const p = plan(a);
        p.stand();
        p.add(S.anim('shock', 500));
        p.to(d.seatX - 14, ROW_B - 12);
        p.add(S.anim('crouch', 900, true));
        p.to(d.seatX + 16, ROW_B - 14);
        p.add(S.anim('crouch', 900), S.hold('docs'), S.anim('gather', 700), S.call(() => { ds(a).hidePapers = false; }), S.hold(null));
        p.back();
        p.run(() => { ds(a).hidePapers = false; a.hold = null; });
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
        // 已取消时桌上的纸收进箱子：桌面的样子由取消状态决定
        const p = plan(a);
        p.stand();
        p.add(S.anim('tidy', 1800, true), S.anim('idle', 400));
        p.run();
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
        const tool = ev.tool || pl.tool || st.lastPendingTool || model.pending_tool || 'run_command';
        const words = { rerun: '重新执行', accept_current: '按当前实际状态继续', stop: '停止事项' }[choice] || choice;
        st.eventStatus = choice === 'stop' ? 'cancelled' : 'working';
        st.eventTool = null;
        if (choice === 'stop') st.doorEvent = '已停止';
        applyLights();
        setPersist(a, null);
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
          p.add(S.anim('tidy', 1600));
        } else {
          p.back();
          p.add(S.anim('type', 800));
        }
        p.run(() => { a.hold = null; });
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
          keep(target, 'card');
          st.wbTags[target.id] = true;
          say(ev, target, 'to');
        }), S.hold(null), S.anim('idle_happy', 400));
        p.back();
        p.run(() => { mgr.hold = null; if (!shown(ds(target), 'card')) keep(target, 'card'); st.wbTags[target.id] = true; });
        if (scene.inTail(target)) scene.run(target, [S.anim('sit_up', 1600)], { tail: 0 });
      },
      hand_back(ev, a) {
        const mgr = byKind('manager') || primary();
        const worker = a === mgr ? roleActors().find((x) => x !== mgr) : a;
        if (!worker) return;
        const gs = giveSpot(mgr.data.desk);
        say(ev, worker);
        const p = plan(worker);
        p.stand();
        p.add(S.call(() => { drop(worker, 'card'); }), S.hold('card_result'));
        p.to(gs[0], gs[1]);
        p.add(S.turn(gs[2]), S.anim('give', undefined, true), S.call(() => {
          keep(mgr, 'cardResult');
          st.wbDone[worker.id] = true;
          say(ev, mgr, 'to');
        }), S.hold(null), S.anim('idle_happy', 400));
        p.back();
        p.run(() => { worker.hold = null; if (!shown(ds(mgr), 'cardResult')) keep(mgr, 'cardResult'); st.wbDone[worker.id] = true; });
        if (scene.inTail(mgr)) scene.run(mgr, [S.anim(mgr.seat ? 'sit_happy' : 'idle_happy', 1800)], { tail: 0 });
      },
      explore(ev, a) {
        const ex = byKind('explorer') || a;
        setPersist(ex, null);
        let filed = false;
        const file = () => { if (!filed) { filed = true; keep(ex, 'folder'); } };
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
        const rewrite = () => { if (!rewritten) { rewritten = true; st.wbErase = 0; st.wbSeed += 1; st.wbSheetUntil = 0; st.wbTags = {}; st.wbDone = {}; } };
        const p = plan(mgr);
        p.spot('wb');
        p.add(S.call(() => { st.wbErase = 0; scene.tween(st, 'wbErase', 1, 1400, 'linear'); }), S.anim('board_erase', 1500, true),
          S.call(rewrite), S.anim('board_write', 1600), S.anim('back', 300));
        p.back();
        p.run(rewrite);
      },
      semantic(ev, a) {
        const d = a.data.desk;
        // 卡片数取自 roomModel.semantic_cards；新卡片在飞进柜子之前先不显示
        if ((model.semantic_cards || 0) > 0) st.cardHide = scene.realT + 5000;
        scene.fly({ bmp: 'card', from: [d.seatX, ROW_B - 22], to: [L.cards.x + 12, L.cards.base - 32], ms: 900, arc: 30, onDone: () => { st.cardHide = 0; st.cardFlash = scene.realT + 1600; } });
        if (scene.inTail(a)) scene.run(a, [S.anim(a.seat ? 'sit_up' : 'look_l', 1200)], { tail: 0 });
      },
      // 部署：推车把箱子推进通往机房的门，备份柜先亮一格（Stage 4）
      deploy(ev, a) {
        const p = plan(a);
        st.cart.box = 'box_sealed';
        st.cart.pushed = true;
        st.mdoorGlow = 1;
        p.stand();
        p.add(S.anim('push', undefined, true));
        p.to(SPOT.mdoor[0], SPOT.mdoor[1], 'push', 30);
        p.add(S.turn(1), S.anim('side_reach', 700, true), S.call(() => {
          st.cart.box = null;
          st.cart.pushed = false;
          st.cart.x = 296;
          st.backupLit = Math.min(3, st.backupLit + 1);
          st.backupFlash = scene.realT + 1800;
          scene.emit('spark', L.mdoor.x + 8, L.mdoor.base - 34, 10, { color: PAL.green1 });
        }), S.anim('idle_happy', 600));
        p.back();
        p.run(() => { st.mdoorGlow = 0; st.cart.pushed = false; st.cart.box = null; st.cart.x = 296; });
      },
      // 回滚：从门里取回旧版本的箱子
      rollback(ev, a) {
        const p = plan(a);
        p.spot('mdoor');
        p.add(S.call(() => { st.mdoorGlow = 1; }), S.anim('reach', 700, true), S.call(() => {
          scene.fly({ bmp: 'box', from: [L.mdoor.x + 8, L.mdoor.base - 30], to: [a.x + 4, a.y - 20], ms: 700, arc: 10, onDone: () => { a.hold = 'box'; } });
        }), S.anim('catch', 900), S.anim('idle_happy', 600));
        p.back('carry');
        p.run(() => { a.hold = null; st.mdoorGlow = 0; });
      },
      // 发现故障：跑向监控屏，写故障信件放进通往大厅的管道
      fault(ev, a) {
        const p = plan(a);
        p.stand();
        p.add(S.icon({ kind: 'exclaim' }), S.anim('shock', 400));
        p.to(SPOT.monitor[0], SPOT.monitor[1], 'run', 90);
        p.add(S.icon(null), S.anim('board_write', 1400, true), S.call(() => { st.monitorAlarmUntil = scene.realT + 9000; }), S.hold('letter'));
        p.spot('pipe', 'carry');
        p.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
          a.hold = null;
          scene.fly({ bmp: 'letter', from: [a.x + 6, a.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8, ease: 'linear' });
        })), S.anim('side_reach', 900, true));
        p.back();
        p.run(() => { a.hold = null; st.monitorAlarmUntil = scene.realT + 9000; });
      },
      // 等待模型服务：坐在工位上看着墙上的时钟，灯光调暗，管道停止（Stage 4）
      wait_provider(ev, a) {
        setPersist(a, null);
        st.eventWaiting = true;
        applyLights();
        const p = plan(a);
        p.sit();
        p.add(S.anim('sit_up', 2600, true));
        p.run(() => { st.eventWaiting = false; applyLights(); });
      },
      // 远程执行：走到终端，屏幕上显示机器名称与一根通往门外的线；线上有流动的光点（3.2C）
      remote_run(ev, a) {
        setPersist(a, null);
        const pl = ev.payload || {};
        st.eventMachine = pl.machine_name || pl.label || model.machine || '登记的机器';
        const p = plan(a);
        p.spot('terminal');
        p.add(S.call(() => scene.after(scene.reduced ? 0 : 400, () => { scene.tween(st, 'lever', 1, 220, 'out'); st.termRun = true; st.exit = null; })), S.anim('lever', 1000), S.anim('watch_r', 2600, true));
        p.run(() => { st.eventMachine = null; st.termRun = false; });
      },
      // 远程动作结果未知：盯着终端，头顶黄色问号；终端屏幕变为雪花（3.2C）
      remote_unknown(ev, a) {
        const pl = ev.payload || {};
        st.eventRemote = true;
        st.eventMachine = pl.machine_name || model.machine || null;
        st.termRun = false;
        const p = plan(a);
        p.spot('terminal');
        p.add(S.icon({ kind: 'question' }), S.anim('watch_r', 1500), S.anim('puzzled', 3000, true), S.icon(null));
        p.run(() => { st.eventRemote = false; });
      },
      // 网络取回：走到门口的邮筒寄出请求，取回资料（3.2B）
      net_fetch(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.spot('post', 'carry');
        p.add(S.hold('letter'), S.anim('side_place', 700, true), S.call(() => { a.hold = null; st.postFlag = 1; }), S.anim('wait', 1400, true));
        p.add(S.call(() => {
          st.postFlag = 0;
          scene.fly({ bmp: 'docs', from: [L.post.x + 6, L.post.base - 22], to: [a.x + 4, a.y - 20], ms: 620, arc: 12, onDone: () => { a.hold = 'docs'; } });
        }), S.anim('catch', 900));
        p.back('carry');
        p.run(() => { a.hold = null; st.postFlag = 0; });
      },
      // 调用 MCP 工具：在墙上的工具面板上按下对应的按钮，按钮亮灯（3.2B）
      mcp_press(ev, a) {
        setPersist(a, null);
        const pl = ev.payload || {};
        const idx = pl.index !== undefined ? pl.index : pl.button !== undefined ? pl.button : 0;
        const panel = model.tool_panel || {};
        const n = (panel.buttons && panel.buttons.length) || panel.buttons || 3;
        const k = Math.max(0, Math.min(n - 1, idx));
        const p = plan(a);
        p.spot('tool');
        p.add(S.anim('reach', 900, true), S.call(() => {
          st.toolLit = k;
          scene.emit('spark', L.tool.x + 6 + k * 14, L.tool.y + L.tool.h - 4, 8);
        }), S.anim('idle_happy', 800));
        p.back();
        p.run(() => { st.toolLit = -1; });
      },
      // 试用网页或桌面程序：测试工程师坐在试用台前点击与输入；显示器嵌入最近一张截图的缩略图（3.2D）
      trial(ev, a) {
        setPersist(a, null);
        const pl = ev.payload || {};
        const t = byKind('tester') || a;
        st.eventStep = pl.step || (model.trial && model.trial.step) || 1;
        if (pl.text_lines) st.eventLines = pl.text_lines;
        if (!st.trialSeat) return;
        const p = plan(t);
        p.to(st.trialSeat.seatX, st.trialSeat.seatY);
        p.steps.push(S.seat(st.trialSeat), S.turn(1));
        p.seated = true;
        p.add(S.anim('type', 2200, true));
        p.back();
        p.run(() => { st.eventStep = 0; st.eventLines = null; });
      },
      // 工程自测网页：工程在自己的显示器前点击，显示器嵌入截图缩略图（3.2D）
      self_test(ev, a) {
        setPersist(a, { anim: 'type' });
        st.selfShot = true;
        const p = plan(a);
        p.sit();
        p.add(S.anim('type', 2200, true), S.anim('sit_up', 900, true));
        p.run(() => { st.selfShot = true; });
      },
      // 阅读已有项目：从门口搬来一摞旧档案，逐本阅读，白板出现「现有行为」清单（3.8）
      read_existing(ev, a) {
        setPersist(a, null);
        const p = plan(a);
        p.to(SPOT.door[0], SPOT.door[1]);
        p.add(S.call(openDoor), S.go(SPOT.doorIn[0], SPOT.doorIn[1]), S.fade(0, 260), S.call(closeDoor), S.wait(1400), S.hold('docs'), S.call(openDoor), S.fade(1, 260));
        p.x = SPOT.doorIn[0]; p.y = SPOT.doorIn[1];
        p.to(SPOT.door[0], SPOT.door[1], 'carry');
        p.add(S.call(closeDoor));
        p.sit('carry');
        p.add(S.call(() => { st.wbExisting = true; keep(a, 'docs'); }), S.hold('doc'), S.anim('read_sit', 3200, true));
        p.run(() => { a.hold = null; st.wbExisting = true; });
      },
      // 审查：审查者拿红笔在成果上批注，盖「通过」或「退回」（Stage 5）
      review(ev, a) {
        setPersist(a, null);
        const pl = ev.payload || {};
        const verdict = pl.verdict === 'return' || pl.verdict === 'reject' ? '退回' : '通过';
        const color = verdict === '通过' ? PAL.green2 : PAL.red2;
        const rv = byKind('reviewer') || a;
        const p = plan(rv);
        p.stand();
        p.spot('bench');
        p.add(S.hold('pen_red'), S.anim('write', 1200), S.hold(null), S.anim('inspect', 900));
        p.add(...stampSteps('stamp', () => { st.bench.mark = { text: verdict, color }; }, 'stamp_once'));
        p.back();
        p.run(() => { st.bench.mark = { text: verdict, color }; });
      },
      // 经理对外：经理走到管道口与传信管口（Stage 5）
      manager_out(ev, a) {
        setPersist(a, null);
        const mgr = byKind('manager') || a;
        const p = plan(mgr);
        p.stand();
        p.spot('pipe', 'carry');
        p.add(S.hold('box_sealed'), S.anim('side_reach', 800, true), S.call(() => { mgr.hold = null; }), S.anim('idle', 400));
        p.spot('tube', 'carry');
        p.add(S.hold('letter'), S.anim('side_place', 800, true), S.call(() => { mgr.hold = null; }), S.anim('idle', 500));
        p.back();
        p.run(() => { mgr.hold = null; });
      },
      hold_form(ev, a) {
        const pl = ev.payload || {};
        const what = pl.action || (pl.kind === 'external_action' ? '外部动作' : pl.kind) || quoted(ev.label) || '外部动作';
        const text = '待授权：' + what;
        // 举着申请单在门口等待（设计说明第 8.3 节）
        const p = plan(a);
        p.stand();
        p.to(SPOT.door[0] - 16, SPOT.door[1] + 4);
        p.add(S.turn(1), S.call(() => { a.data.formSign = text; }), S.anim('hold_form', 1600, true));
        p.mark();
        p.add(S.anim('hold_form', 3600), S.call(() => { a.data.formSign = null; }));
        p.back();
        p.run(() => { a.data.formSign = null; });
      }
    };

    function commandDone(ev, a) {
      const pl = ev.payload || {};
      const code = pl.exit_code;
      const timedOut = Boolean(pl.timed_out);
      st.termRun = false;
      st.exit = timedOut ? 'red' : code === 0 ? 'green' : 'red';
      if (timedOut) st.smokeUntil = scene.realT + 4200;
      scene.tween(st, 'lever', 0, 300, 'inOut');
      const ok = st.exit === 'green';
      const p = plan(a);
      p.spot('terminal');
      p.add(S.icon({ kind: timedOut ? 'exclaim' : ok ? 'check' : 'cross' }), S.anim(ok ? 'idle_happy' : 'stand_sad', 1200, true), S.icon(null));
      p.back();
      p.run();
    }

    // 交接：本部门把包裹放进管道口，或从管道口取出（设计说明第 8.1 与 8.3 节）
    const ART_BMP = { prd: 'scroll', box: 'box_sealed', defect: 'box_rework', release: 'box_release', letter: 'letter' };
    function transition(ev) {
      const pl = ev.payload || {};
      const art = pl.artifact;
      const bmp = ART_BMP[art];
      if (!bmp) return;
      const a = primary();
      if (pl.from === dept) {
        say(ev, a, 'from');
        // 交出的物件先在工作台上或卷轴架上取走
        const p = plan(a);
        p.stand();
        if (st.bench.item === bmp) p.add(S.call(() => { st.bench.item = null; st.bench.mark = null; }));
        else if (dept === 'quality' && st.bench.slip) p.add(S.call(() => { st.bench.slip = null; st.bench.slipMark = null; st.bench.item = null; }));
        p.add(S.hold(bmp));
        p.spot('pipe', 'carry');
        p.add(S.call(() => scene.after(scene.reduced ? 0 : 260, () => {
          a.hold = null;
          scene.fly({ bmp, from: [a.x + 6, a.y - 20], to: [L.pipe.x + 10, L.pipe.base - 8], ms: 620, arc: 8, ease: 'linear' });
        })), S.anim('side_reach', 900, true));
        p.back();
        p.run(() => { a.hold = null; });
      } else if (pl.to === dept) {
        // 收到的一方在动作开始时说话（v11 第 1 条）：随后从管道口取出，带到工作台或桌上放下
        say(ev, a, 'to');
        const p = plan(a);
        a.data.handoff = true;
        p.spot('pipe');
        p.add(S.call(() => {
          scene.fly({ bmp, from: [L.pipe.x + 10, L.pipe.base - 8], to: [a.x + 6, a.y - 18], ms: 620, arc: 8, ease: 'out', onDone: () => { a.hold = bmp; } });
        }), S.anim('reach', 700, true), S.anim('catch', 900));
        if (isOps() || art === 'prd') {
          p.sit('carry');
          p.add(S.call(() => arrivalArt(a, art)), S.hold(null), S.anim('sit_happy', 600));
        } else {
          p.spot('bench', 'carry');
          p.add(S.anim('place', 700), S.hold(null), S.call(() => arrivalArt(a, art)));
        }
        p.back();
        p.run(() => { a.hold = null; a.data.handoff = false; });
      }
    }

    function playEvent(ev) {
      if (!ev || !ev.type) throw new Error('playEvent 需要事件对象');
      const pl = ev.payload || {};
      const related = !ev.department || ev.department === dept || pl.from === dept || pl.to === dept;
      if (!related) return;
      // 提案被接纳或退回后托盘清空
      if (PROPOSAL_DONE.has(ev.type)) st.trayPaper = false;
      // 数据中已经加上的卷轴与纸条，在动作把它们放上去之前先不显示
      if ((ev.type === 'spec_accepted' || ev.type === 'contract_accepted') && dept === 'product' && (model.scrolls || 0) > 0) st.scrollHide = scene.realT + 15000;
      if (ev.type === 'department_guidance_applied' && (model.pinned_notes || 0) > 0) st.noteHide = scene.realT + 15000;
      if (ev.type === 'transition') { transition(ev); return; }
      if (ev.type === 'collaboration_closed') {
        roleActors().forEach((x) => { if (x.script && x.anim === 'wait') scene.cancel(x); });
        if (st.eventStatus === 'asking') st.eventStatus = null;
        return;
      }
      let action = P.resolveAction(ev);
      // 建档事项（3.8）中读取与搜索工具的 tool_started 播放「阅读已有项目」：接入已有项目设计说明第 3.3 节
      if (model.existing_read && (action === 'read' || action === 'search')) action = 'read_existing';
      // 收到询问的部门走到传信管口取信阅读
      if (action === 'send_letter') {
        const sides = letterSides(ev);
        if (sides.answerer === dept && sides.asker !== dept) action = 'answer_letter';
      }
      if (!action) {
        if (ev.type === 'tool_started') {
          const a = actorFor(ev);
          setPersist(a, { anim: 'type' });
          if (!scene.frozen) say(ev, a);
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
      if (SIDE_ONLY.has(action)) { say(ev, a); fn(ev, a); return; }
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
        a.data.handoff = false;
        if (!OWN_SPEECH.has(action) && !THINK_ACTIONS.has(action)) say(ev, a);
        fn(ev, a);
      };
      // 状态类动作立即执行；其他动作在当前动作的主要部分做完后执行
      if (IMMEDIATE.has(action) || scene.inTail(a)) {
        if (keepPending(a)) {
          // 交接与盖章先做完：状态类动作排在它们后面（v11 第 2 条）
          a.data.queue = a.data.queue || [];
          a.data.queue.push({ fn: start, at: scene.realT, action });
          return;
        }
        a.data.queue = [];
        start();
        return;
      }
      a.data.queue = a.data.queue || [];
      a.data.queue.push({ fn: start, at: scene.realT, action });
      if (a.data.queue.length > 3) {
        // 队满时挤掉最早的一条；交接与盖章不挤掉（v11 第 2 条）
        const index = a.data.queue.findIndex((item) => !KEEP_ACTIONS.has(item.action));
        a.data.queue.splice(index >= 0 ? index : 0, 1);
      }
    }
    const SIDE_ONLY = new Set(['guidance_in', 'semantic', 'freeze']);
    // hand_back 由动作自己让交回结果的角色与收下结果的经理各说一句；打字思考时头顶已经有思考气泡
    const OWN_SPEECH = new Set(['hand_back']);
    const THINK_ACTIONS = new Set(['type_think', 'stream_text']);
    const PROPOSAL_DONE = new Set(['spec_accepted', 'contract_accepted', 'plan_accepted', 'delivery_accepted', 'qa_submitted', 'proposal_rejected']);
    const IMMEDIATE = new Set(['paused', 'failed', 'done', 'cancelled', 'puzzled', 'hold_card', 'resume']);
    // 交接与盖章这两类先做完（v11 第 2 条）：它们还在做或排在队里时，状态类动作排在它们后面，
    // 说出的话停留到读得完；队满时也不挤掉它们
    const KEEP_ACTIONS = new Set(['seal', 'stamp_valid', 'stamp_release', 'stamp_rework']);

    function keepPending(a) {
      // 正在做或排在队里的交接与盖章
      if (a.data.handoff) return true;
      if (a.data.doing && KEEP_ACTIONS.has(a.data.doing)) return true;
      const q = a.data.queue;
      return !!(q && q.length && KEEP_ACTIONS.has(q[0].action));
    }

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
      const pinned = Math.max(0, (model.pinned_notes || 0) - (st.noteHide > sc.realT ? 1 : 0));
      paint.corkboard(c, L.cork.x, L.cork.y, { w: L.cork.w, h: L.cork.h, notes: pinned, doneIndex: st.replyUntil > sc.realT ? Math.min(pinned, 6) - 1 : -1, label: '部门指导' });
      const doorInfo = paint.door(c, L.door.x, L.door.base, { w: L.door.w, h: L.door.h, open: st.door });
      R(c, L.door.x + 4, L.door.base - L.door.h - 12, L.door.w - 8, 8, PAL.ink);
      R(c, L.door.x + 5, L.door.base - L.door.h - 11, L.door.w - 10, 6, D.main);
      if (P.levelAtLeast(level, '3.1')) paint.beacon(c, L.beacon.x, L.beacon.y, { on: st.yellow }, t);
      if (isOps()) paint.beacon(c, L.back.x + 11, L.back.y !== undefined ? L.back.y : 50, { on: alarmOn(), color: 'red' }, t);
      if (P.levelAtLeast(level, '3.2B')) {
        paint.toolPanel(c, L.tool.x, L.tool.y, { w: L.tool.w, h: L.tool.h, buttons: toolLabels().length, lit: toolLit(), labels: toolLabels() }, t);
      }
      if (P.levelAtLeast(level, '3.2C')) drawMachineLink(c, t);
      L.lamps.forEach((lx) => paint.lamp(c, lx, 6, st.darkTarget === 0));

      // 地面物件与小人：按深度排序
      const items = [];
      items.push({ y: BASE, draw: () => { paint.cabinet(c, L.cabinet.x, L.cabinet.base, { open: st.drawer, blink: blinkTool('search') }, t); paint.archive(c, L.cabinet.x + 2, L.cabinet.base - 40, { n: model.summaries || 0, flash: sc.realT < st.archiveFlash }, t); } });
      if (P.levelAtLeast(level, 'S5')) items.push({ y: BASE, draw: () => paint.cardCabinet(c, L.cards.x, L.cards.base, { cards: Math.max(0, (model.semantic_cards || 0) - (st.cardHide > sc.realT ? 1 : 0)), flash: sc.realT < st.cardFlash, label: '语义记录' }, t) });
      items.push({ y: BASE, draw: () => { st.termInfo = paint.terminal(c, L.terminal.x, L.terminal.base, termOpts(), t); } });
      items.push({ y: BASE + 2, draw: () => paint.tray(c, L.tray.x, L.tray.base, { count: st.trayPaper ? 1 : 0 }) });
      items.push({ y: BASE, draw: () => drawBackPiece(c, t) });
      items.push({ y: BASE + 2, draw: () => { st.mailInfo = paint.mailbox(c, L.mailbox.x, L.mailbox.base, { count: mailCount() }, t); } });
      items.push({ y: BASE + 4, draw: () => paint.plant(c, L.plant.x, L.plant.base) });
      items.push({ y: 160, draw: () => paint.plant(c, 452, 160) });
      // 交接管道口与传信管口（设计说明第 8.1 节）
      items.push({ y: L.pipe.base, draw: () => paint.pipe(c, L.pipe.x, L.pipe.base, { out: pipeMode(), letters: 0 }, t) });
      items.push({ y: L.tube.base, draw: () => paint.tube(c, L.tube.x, L.tube.base, { letters: lettersWaiting() }) });
      if (P.levelAtLeast(level, '3.2B')) items.push({ y: L.post.base, draw: () => paint.postbox(c, L.post.x, L.post.base, { flag: st.postFlag }) });
      if (dept === 'quality' && st.trialSeat) items.push({ y: L.trial.y + 0.5, draw: () => drawTrialTable(c, t) });
      if (isOps()) {
        if (opsRoom()) {
          items.push({ y: L.mdoor.base, draw: () => paint.machineDoor(c, L.mdoor.x, L.mdoor.base, { w: L.mdoor.w, h: L.mdoor.h, glow: st.mdoorGlow }, t) });
        }
      }
      if (dept !== 'operations') items.push({ y: ROW_A + 0.5, draw: () => drawBench(c, t) });
      else if (opsRoom()) {
        const cp = cartPos();
        items.push({ y: cp[1] - 1, draw: () => paint.cart(c, Math.round(cp[0]), Math.round(cp[1]), { box: st.cart.box }) });
      }
      st.desks.forEach((d) => {
        items.push({ y: ROW_B - 1, draw: () => paint.chair(c, d.seatX, ROW_B, { color: D.shade }) });
        items.push({ y: ROW_B + 0.5, draw: () => drawDesk(c, d, t) });
      });
      items.push({ y: st.bin.y, draw: () => paint.bin(c, st.bin.x, st.bin.y, { count: st.binUntil > sc.realT ? 1 : 0 }) });
      if (!isOps()) items.push({ y: ROW_B + 12, draw: () => drawTeaStation(c, t) });
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
      if (dept === 'engineering' && P.levelAtLeast(level, '3.2D') && (st.selfShot || model.self_test)) drawSelfShot(c, t);
      if (P.levelAtLeast(level, '3.1')) paint.beaconLight(c, L.beacon.x, L.beacon.y, { on: st.yellow, reduced: sc.reduced, len: 90 }, t);
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
      // 说话气泡：画在最上层，减少动画时也照说
      const says = [];
      sc.actors.forEach((a) => {
        const s = a.data.say;
        if (s && a.visible && sc.realT < s.until) says.push({ a, text: s.text, kind: 'say', until: s.until });
      });
      P.drawSpeeches(c, sc, says, { W, size: 7, maxW: 108 });
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

    function alarmOn() {
      return isOps() && (st.alarmUntil > scene.realT || st.monitorAlarmUntil > scene.realT || Boolean(model.monitor_alarm));
    }
    // 推车停在工作台一排；运维推着走时跟在小人前面，底边与小人脚下同高
    function cartPos() {
      if (!st.cart.pushed) return [st.cart.x, ROW_A + 12];
      const a = primary();
      return [a.x + (a.facing > 0 ? 6 : -32), a.y + 1];
    }
    function mailCount() { return model.mailbox || 0; }
    function blinkTool(tool) {
      if (effStatus() !== 'pending_verification') return false;
      const pt = st.eventTool || model.pending_tool;
      if (tool === 'desk') return pt === 'edit_range' || pt === 'write_file' || pt === 'read_file' || pt === 'read_range' || (pt && toolSpot(pt) === 'desk');
      return pt === tool;
    }

    function termOpts() {
      const off = effStatus() === 'interrupted';
      const snow = remoteUnknown();
      return { lever: st.lever, exit: off ? null : st.exit, screen: off ? 'off' : snow ? 'snow' : st.termRun ? 'term' : 'idle', blink: blinkTool('run_command') || snow };
    }

    // 墙上的 MCP 工具面板：按钮与亮灯（3.2B）
    function toolLabels() {
      const tp = model.tool_panel;
      if (tp && Array.isArray(tp.buttons)) return tp.buttons;
      return ['检', '网', '图'];
    }
    function toolLit() {
      if (st.toolLit >= 0) return st.toolLit;
      if (model.tool_panel && model.tool_panel.lit !== undefined) return model.tool_panel.lit;
      return -1;
    }

    // 终端屏幕上的机器名称与一根通往门外的线，动作结束前线上有流动的光点（3.2C）
    function drawMachineLink(c, t) {
      const name = machineName();
      if (!name) return;
      const y0 = L.terminal.base + 8;
      P.text(c, name, L.terminal.x + 14, y0 - 7, { size: 5, weight: 600, align: 'center', color: PAL.ink2, max: 76 });
      const span = L.door.x - (L.terminal.x + 14) + 16;
      R(c, L.terminal.x + 14, y0, span, 1, PAL.metal3);
      if (remoteUnknown()) return;
      const off = Math.floor(t / 130);
      for (let i = 0; i < 36; i++) R(c, L.terminal.x + 16 + ((i * 8 + off) % span), y0, 2, 1, PAL.yellow2);
    }

    // 工程自测网页：显示器嵌入最近一张截图的缩略图（3.2D）
    function drawSelfShot(c, t) {
      const pa = primary();
      const d = pa.data.desk;
      const shot = model.trial || model.self_test || {};
      paint.shot(c, d.x + d.w - 52, d.y - 74, 48, 32, { screenshot: shot.screenshot, text_lines: shot.text_lines || st.eventLines, text_only: shot.model_saw === false }, t);
      P.text(c, '本机浏览器', d.x + d.w - 28, d.y - 78, { size: 5, align: 'center', color: PAL.ink2, max: 60 });
    }

    // 质检试用台：显示器嵌入最近一张截图的缩略图（像素边框）；模型不能看图时同样显示截图，旁边标明「模型只读取文字」（3.2D）
    function drawTrialTable(c, t) {
      const tb = L.trial;
      const a = scene.actors.find((x) => x.seat === st.trialSeat && x.visible);
      if (a) P.drawActor(c, scene, a, 'base');
      paint.table(c, tb.x, tb.y, tb.w, { top: PAL.white, face: D.light, edge: P.mix(D.light, PAL.ink, 0.3), label: '试用台' });
      const trial = model.trial || {};
      const step = st.eventStep || trial.step || 0;
      const lines = st.eventLines || trial.text_lines || null;
      const textOnly = trial.model_saw === false;
      paint.shot(c, tb.x + tb.w - 34, tb.y - 42, 30, 22, { screenshot: trial.screenshot, text_lines: lines, text_only: textOnly }, t);
      if (step) P.text(c, '第 ' + step + ' 步', tb.x + 8, tb.y + 4, { size: 5, color: PAL.ink2, max: 50 });
      if (textOnly) P.sign(c, tb.x + tb.w - 19, tb.y - 44, '模型只读取文字', { size: 4.5, bg: PAL.yellow1, stripe: PAL.orange2, maxW: 70 });
      if (a) {
        c.save();
        c.beginPath(); c.rect(0, 0, W, tb.y); c.clip();
        P.drawActor(c, scene, a, 'front');
        c.restore();
      }
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
      const s5 = P.levelAtLeast(level, 'S5');
      let lines;
      if (s5 && rolesOf(model).length === 1) {
        const r = rolesOf(model)[0];
        lines = [{ text: r.task || (model.crt && model.crt.target) || r.name, color: PAL.ink2 }, { color: PAL.blue3 }, { color: PAL.ink2 }];
      } else if (s5) {
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
      // 阅读已有项目：白板上出现「现有行为」清单（3.8）
      if (st.wbExisting || model.existing_read) {
        lines = [{ text: '现有行为', color: PAL.blue3 }].concat([0, 1, 2].map((i) => ({ color: PAL.ink2 })));
      }
      return { w: L.wb.w, h: L.wb.h, floor: L.wb.floor, title: s5 ? '部门账本' : '工作计划', lines, sheet: st.wbSheetUntil > scene.realT, erase: st.wbErase, blink: false };
    }

    function drawBackPiece(c, t) {
      const x = L.back.x;
      if (dept === 'product') {
        paint.scrollRack(c, x, BASE, { count: Math.max(0, (model.scrolls || 0) - (st.scrollHide > scene.realT ? 1 : 0)), flash: scene.realT < st.scrollFlash, label: '卷轴架' }, t);
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
        // 运维：监控屏与备份柜（Stage 4）；v7 的机柜已删除
        paint.monitor(c, L.monitor.x, L.monitor.y, { w: L.monitor.w, h: L.monitor.h, alarm: alarmOn() }, t);
        paint.backup(c, L.backup.x, L.backup.base, { lit: st.backupLit || (model.ops && model.ops.backup) || 0, flash: scene.realT < st.backupFlash });
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
      // 已取消时纸收进箱子；其余桌上物件是动作留下的，过一段时间收走
      const cancelled = effStatus() === 'cancelled';
      const writing = a && a.data.persist && a.data.persist.write;
      paint.deskItems(c, d.x, d.y, {
        w: d.w, papers: cancelled || s.hidePapers ? 0 : s.papers, folder: !cancelled && shown(s, 'folder'), docOnDesk: !cancelled && (shown(s, 'doc') || writing),
        box: cancelled || shown(s, 'box'), card: shown(s, 'card'), cardResult: shown(s, 'cardResult'),
        cup: !(a && (a.anim === 'tea' || a.anim === 'tea0')), monitor: null, lamp: s.redLamp ? 'red' : null, nameplate: d.role.name,
        plateColor: D.light, seed: d.i
      }, t);
      if (shown(s, 'scroll')) P.drawBitmap(c, 'scroll', d.x + 6, d.y - 5);
      if (shown(s, 'letter')) P.drawBitmap(c, 'letter', d.x + d.w / 2 - 12, d.y - 6);
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
        const mode = off ? 'off' : remoteUnknown() ? 'snow' : st.termRun ? 'term' : 'idle';
        paint.screen(c, L.terminal.x + 3, L.terminal.base - 34 + 3, 22, 13, mode, t, { seed: 3 });
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
      if (m.level && m.level !== level) {
        if (m.level !== 'ui' && !Y11.LEVELS.includes(m.level)) throw new Error('未知档位：' + m.level);
        level = m.level;
      }
      st.eventStatus = null; st.eventCard = null; st.eventTool = null;
      st.eventRemote = false; st.eventMachine = null; st.eventWaiting = false; st.eventStep = 0; st.eventLines = null;
      if (m.pending_tool) st.lastPendingTool = m.pending_tool;
      if (m.door !== undefined) st.doorEvent = null;
      // 白板上的分派标记以角色状态为准
      st.wbTags = {}; st.wbDone = {};
      syncRoles();
      const s = effStatus();
      if (s !== prevStatus) {
        roleActors().forEach((a) => {
          if (s === 'interrupted') return;
          if (a.script && (s === 'waiting_resume' || s === 'pending_verification' || s === 'asking' || prevStatus === 'asking')) scene.cancel(a);
          if (s !== 'working') { a.data.persist = null; a.data.queue = (a.data.queue || []).filter((item) => KEEP_ACTIONS.has(item.action) || IMMEDIATE.has(item.action)); }
        });
        if (s !== 'failed') roleActors().forEach((a) => { if (!a.data.persist) ds(a).redLamp = false; });
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
