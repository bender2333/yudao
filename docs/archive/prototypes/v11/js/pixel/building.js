// 楼与机房（设计说明第 4.2 节）：首页画一栋楼，每个项目一层（部门房间的灯、事项小旗、入口阀门、状态灯、空闲时走动的小人）；
// 地下室是所有项目共用的机房（3.2C），每台机器是一台设备，项目楼层有管线通到它正在使用的设备。机器页上方复用机房画面。
// 楼里的小人、通往机房的管线、机房里的设备与管线、沿管线移动的包裹都是 P.ecs 的实体
(function () {
  'use strict';
  const Y11 = window.Y11;
  const P = Y11.pixel;
  if (!P || !P.createScene) throw new Error('building.js 需要先加载 js/pixel/engine.js');
  if (!P.ecs) throw new Error('building.js 需要先加载 js/pixel/ecs.js');
  const ECS = P.ecs;
  const PAL = P.PAL;
  const R = P.R, RB = P.RB;

  const W = 640;
  const ROOF = 34, FH = 66, BASE = 10;
  const ROOMS = ['product', 'engineering', 'quality', 'operations'];
  const STATUS = {
    running: { text: '运行中', color: PAL.green2 },
    queued: { text: '排队中', color: PAL.grey2 },
    waiting_slot: { text: '等待执行槽位', color: PAL.orange2 },
    waiting_provider: { text: '等待模型服务', color: PAL.grey3 },
    pending_verification: { text: '待核实', color: PAL.yellow2 },
    waiting_resume: { text: '待恢复', color: PAL.yellow2 },
    waiting_decision: { text: '等待你的决定', color: PAL.yellow2 },
    interrupted: { text: '中断', color: PAL.grey4 },
    idle: { text: '空闲', color: PAL.grey2 }
  };
  // 每个项目的管线颜色：取项目在楼中的序号
  const LINK_COLORS = ['#e8505b', '#3fc1e8', '#8fd14f', '#f7c948', '#f27ec2', '#b98558'];
  P.LINK_COLORS = LINK_COLORS;

  // 包裹沿管线走的时间：管线长度乘一个系数，最短 700 毫秒
  const travelMs = (pts) => Math.max(700, ECS.polyLength(pts) * 9);

  // ---------------------------------------------------------------------------
  // 楼

  P.createBuildingScene = function createBuildingScene(canvas, opts) {
    const o = opts || {};
    let model = { floors: [] };
    let hover = null;
    const flashes = {};
    const scene = P.createScene(canvas, { W, H: ROOF + FH + BASE, draw, update });

    const floorY = (i) => ROOF + i * FH;
    const roomX = (k) => 150 + k * 96;

    // 楼里的世界：每层一个小人（角色实体，没有房间，走位由 ECS.stepCharacters 推进），
    // 每个用着机器的项目一根通往机房的管线（管道实体，沿右侧竖井下到地下室），远程动作的包裹沿着它走。
    const world = ECS.world();
    // 速度沿用 v8：走到门口 40 像素/秒、随机走动 22 像素/秒（stepCharacters 的 go 步骤不写 speed，
    // engine.js 取 actor.speed，因此每次设目标时先写 a.speed）；随机走动的间隔沿用 v8
    const SPEED_WORK = 40, SPEED_ROAM = 22, ROAM_MIN = 3000, ROAM_SPAN = 5000;

    function walkerActor(pid) { return scene.actors.find((x) => x.id === 'ch-' + pid); }

    function addWalker(f, i) {
      const x = 130 + (i * 97) % 360;
      const y = floorY(i) + FH - 6;
      // department 置 null：楼里的小人不属于任何房间，走上面说的待机留在 spot 的分支
      world.characters[f.project_id] = { kind: 'character', id: f.project_id, department: null,
        spot: { x, y }, queue: [], current: null, rest: null, bubble: null };
      // ECS 用 'ch-' + 角色 id 找 actor，所以 actor id 必须是 'ch-' + project_id
      scene.addActor({ id: 'ch-' + f.project_id, sprite: ROOMS[i % 3] + '.agent', x, y, anim: 'idle',
        speed: SPEED_ROAM, data: { walker: true, next: 0 } });
    }

    function syncWalkers() {
      scene.actors.filter((a) => a.data.walker).forEach((a) => {
        const pid = a.id.slice(3);
        if (!model.floors.some((f) => f.project_id === pid)) {
          delete world.characters[pid];
          scene.removeActor(a);
        }
      });
      model.floors.forEach((f, i) => {
        const a = walkerActor(f.project_id);
        if (!a || !world.characters[f.project_id]) { addWalker(f, i); return; }
        const y = floorY(i) + FH - 6;
        a.y = y;
        world.characters[f.project_id].spot.y = y;
      });
    }

    // 通往机房的管线的几何：从这一层的出口横着走到右侧竖井，再沿竖井下到地下室
    function shaftOf(f, i) {
      const y = floorY(i);
      const x0 = roomX(3) + (f.has_ops ? 82 : 0);
      const sx = W - 22 - (i % 6) * 3;
      const drop = (model.floors.length - i) * FH - 30;
      return { col: LINK_COLORS[i % LINK_COLORS.length], y, x0, sx, drop, pts: [[x0, y + 31], [sx + 1, y + 31], [sx + 1, y + 30 + drop + BASE]] };
    }

    function declareShafts() {
      const defs = [];
      model.floors.forEach((f, i) => {
        if (f.machine_ids && f.machine_ids.length) defs.push({ from: 'floor:' + f.project_id, to: 'basement', kind: 'shaft', pts: shaftOf(f, i).pts, index: i, active: Boolean(f.link_active) });
      });
      ECS.declareLinks(world, defs);
    }

    const shaftKey = (pid) => 'floor:' + pid + '>basement';

    function update() {
      model.floors.forEach((f) => {
        const ch = world.characters[f.project_id];
        if (!ch) return;
        const a = walkerActor(f.project_id);
        // 走位脚本跑完之前不换目标（跟 v8 相同：v8 的 update 对 a.script 直接 return）
        if (!a || a.script) return;
        const working = ROOMS.findIndex((d) => f.lit && f.lit[d]);
        if (working >= 0) {
          // 有部门工作时站到本层那个部门门口，门口坐标跟 v8 相同
          const tx = roomX(working) + 40;
          a.speed = SPEED_WORK;
          ch.spot.y = a.y;
          if (Math.abs(a.x - tx) > 2) ch.spot.x = tx;
          else if (a.facing !== -1) a.facing = -1; // v8 到达门口后的 turn facing:-1
        } else {
          // 空闲时随机走动：到了下一趟的时间点就把待机的 spot 换成本层随机位置
          a.speed = SPEED_ROAM;
          ch.spot.y = a.y;
          if (scene.realT > a.data.next) {
            a.data.next = scene.realT + ROAM_MIN + Math.random() * ROAM_SPAN;
            ch.spot.x = 130 + Math.random() * 400;
          }
        }
      });
      // 待机的走位与 idle 动画交给 ecs.js 推进（首页的楼不进任务队列，queue 恒为空）；管线与包裹同样由 ecs.js 推进
      ECS.stepCharacters(world, scene);
      ECS.stepPipes(world, scene, (p) => (p.def.active ? 'flowing' : 'idle'));
      ECS.stepPackages(world, scene);
    }

    function drawFloor(c, f, i, t) {
      const y = floorY(i);
      const st = STATUS[f.status] || STATUS.idle;
      R(c, 12, y, W - 24, FH, '#e8e0cc');
      R(c, 12, y + FH - 14, W - 24, 14, '#c9a77a');
      for (let x = 12; x < W - 12; x += 10) R(c, x, y + FH - 14, 1, 14, '#b8966a');
      R(c, 12, y, W - 24, 2, '#4d5466');
      if (hover === f.project_id) { c.fillStyle = 'rgba(79,148,232,0.12)'; c.fillRect(12, y + 2, W - 24, FH - 2); }
      // 名牌与状态灯
      RB(c, 18, y + 8, 104, 20, PAL.paper);
      P.text(c, f.name, 22, y + 15, { size: 7, weight: 700, color: PAL.ink, max: 96 });
      RB(c, 22, y + 22, 6, 6, st.color);
      if (!scene.reduced && ['running', 'waiting_slot', 'pending_verification', 'waiting_resume'].includes(f.status) && Math.floor(t / 500) % 2) R(c, 23, y + 23, 2, 2, PAL.white);
      P.text(c, st.text, 32, y + 25.5, { size: 5.5, weight: 700, color: PAL.ink2, max: 88 });
      if (f.decisions) {
        RB(c, 106, y + 5, 14, 9, PAL.yellow2);
        P.text(c, String(f.decisions), 113, y + 9.5, { size: 6, weight: 800, align: 'center', color: PAL.ink });
      }
      // 入口阀门：等待执行槽位时关闭
      RB(c, 128, y + 32, 14, 6, PAL.metal3);
      RB(c, 131, y + 26, 8, 3, f.valve_closed ? PAL.red2 : PAL.green2);
      if (f.valve_closed) P.sign(c, 70, y + 50, '等待执行槽位', { size: 5.5, bg: PAL.yellow1, stripe: PAL.orange2, maxW: 100 });
      // 部门房间的灯
      ROOMS.forEach((d, k) => {
        if (d === 'operations' && !f.has_ops) return;
        const x = roomX(k);
        const D = P.DEPTS[d];
        const lit = f.lit && f.lit[d];
        RB(c, x, y + 8, 80, 36, lit ? D.wall : P.mix(D.wall, PAL.ink, 0.45));
        R(c, x + 2, y + 10, 76, 3, D.main);
        if (lit) {
          c.fillStyle = P.rgba(PAL.yellow1, scene.reduced ? 0.45 : 0.35 + 0.1 * Math.sin(t / 400 + k));
          c.fillRect(x + 2, y + 13, 76, 29);
        }
        P.text(c, D.name, x + 40, y + 20, { size: 6, weight: 700, align: 'center', color: lit ? PAL.ink : PAL.grey1 });
        (f.flags || []).filter((fl) => fl.department === d).forEach((fl, j) => {
          P.drawBitmap(c, (Math.floor(t / 320) + j) % 2 && !scene.reduced ? 'flag2' : 'flag', x + 6 + j * 9, y + 28, { recolor: { X: P.ITEM_COLORS[fl.color_index % 6], x: P.ITEM_SHADES[fl.color_index % 6] } });
        });
        if (k < 3 && (!f.has_ops ? k < 2 : true)) R(c, x + 80, y + 26, 16, 3, PAL.glass2);
      });
      // 管线出口：通往机房的管线沿右侧竖井下到地下室，管线里有光点在流动
      const link = world.links[shaftKey(f.project_id)];
      if (link) {
        const s = shaftOf(f, i);
        R(c, s.x0, y + 30, s.sx - s.x0, 2, s.col);
        R(c, s.sx, y + 30, 2, s.drop + BASE, s.col);
        if (!scene.reduced) {
          const fl = link.flow;
          if (ECS.config.autonomy) {
            if (fl && fl.load > 0.02) {
              const k = (fl.phase / 900 + i * 0.3) % 1;
              c.globalAlpha = fl.load;
              R(c, s.sx - 1, y + 30 + k * s.drop, 4, 3, PAL.yellow2);
              c.globalAlpha = 1;
            }
          } else if (f.link_active) {
            const k = (t / 900 + i * 0.3) % 1;
            R(c, s.sx - 1, y + 30 + k * s.drop, 4, 3, PAL.yellow2);
          }
        }
      }
      const fl = flashes[f.project_id];
      if (fl && fl.until > scene.realT) {
        c.fillStyle = P.rgba(fl.color, Math.min(0.3, ((fl.until - scene.realT) / 1200) * 0.3));
        c.fillRect(12, y + 2, W - 24, FH - 2);
      }
    }

    function drawPackages(c) {
      Object.values(world.packages).forEach((pk) => {
        const pos = ECS.packagePosition(pk);
        if (!pos) return;
        const b = P.bitmap(pk.bmp);
        P.drawBitmap(c, pk.bmp, Math.round(pos[0] - b.w / 2), Math.round(pos[1] - b.h / 2));
      });
    }

    function draw(sc, c) {
      const t = sc.animT;
      R(c, 0, 0, W, sc.H, '#9fd0ee');
      [[40, 10], [300, 6], [520, 14]].forEach(([x, y]) => { R(c, x, y, 26, 5, PAL.white); R(c, x + 6, y - 3, 14, 3, PAL.white); });
      // 屋顶
      R(c, 6, ROOF - 10, W - 12, 10, '#6f7a8c'); R(c, 6, ROOF - 10, W - 12, 1, '#8e98a9');
      P.sign(c, W / 2, ROOF - 12, 'Yudao 枢道', { size: 7, bg: PAL.paper, stripe: PAL.wood3 });
      R(c, 6, ROOF, 6, sc.H - ROOF, '#4d5466'); R(c, W - 12, ROOF, 6, sc.H - ROOF, '#4d5466');
      if (!model.floors.length) P.text(c, '还没有项目', W / 2, ROOF + 30, { size: 8, align: 'center', color: PAL.ink2 });
      model.floors.forEach((f, i) => drawFloor(c, f, i, t));
      const walkers = sc.actors.filter((a) => a.data.walker).sort((p, q) => p.y - q.y);
      walkers.forEach((a) => P.drawActor(c, sc, a));
      drawPackages(c);
      R(c, 0, sc.H - BASE, W, BASE, '#5a6070');
      P.text(c, model.show_basement ? '▼ 地下室：机房' : '', W / 2, sc.H - BASE / 2, { size: 6, weight: 700, align: 'center', color: PAL.white });
      sc.drawParticles(c);
    }

    function floorAt(ev) {
      const rect = canvas.getBoundingClientRect();
      const y = ((ev.clientY - rect.top) / rect.height) * scene.H;
      const i = Math.floor((y - ROOF) / FH);
      return i >= 0 && i < model.floors.length ? model.floors[i] : null;
    }

    canvas.addEventListener('click', (ev) => {
      const f = floorAt(ev);
      if (f && o.onFloorClick) o.onFloorClick(f.project_id);
    });
    canvas.addEventListener('mousemove', (ev) => {
      const f = floorAt(ev);
      hover = f ? f.project_id : null;
      canvas.style.cursor = f ? 'pointer' : 'default';
    });
    canvas.addEventListener('mouseleave', () => { hover = null; });

    let packageSeq = 0;
    // 远程动作与部署、回滚的包裹沿这一层通往机房的管线走：出去是往下，回滚与回执是往上
    function sendOnShaft(pid, bmp, up) {
      const link = world.links[shaftKey(pid)];
      if (!link || scene.reduced) return;
      const id = 'pk-' + (++packageSeq);
      ECS.spawnPackage(world, id, null, null, null, null);
      world.packages[id].bmp = bmp;
      const pts = up ? link.pts.slice().reverse() : link.pts;
      ECS.sendPackage(world, id, link.id, pts, travelMs(pts), () => ECS.removePackage(world, id));
    }

    return {
      scene,
      inspect: () => ({ world, model }),
      setModel(m) {
        if (!m || !Array.isArray(m.floors)) throw new Error('setModel 需要 buildingModel');
        model = m;
        scene.setSize(W, ROOF + Math.max(1, m.floors.length) * FH + BASE);
        declareShafts();
        syncWalkers();
      },
      playEvent(ev) {
        if (!ev || !ev.project_id) return;
        const key = Y11.registry.keyOf(ev);
        const color = key === 'rework' || key === 'fault' ? PAL.red2 : key === 'decision' ? PAL.yellow2 : key === 'adopt' || key === 'release' ? PAL.green2 : PAL.white;
        if (key || ev.type === 'department_activated') flashes[ev.project_id] = { color, until: scene.realT + 1200 };
        if (ev.type === 'deliverable_adopted') {
          const i = model.floors.findIndex((f) => f.project_id === ev.project_id);
          if (i >= 0) scene.emit('confetti', W / 2, floorY(i), 24, { spread: 400 });
        }
        if (ev.type === 'x_remote_action_started') sendOnShaft(ev.project_id, 'folder', false);
        else if (ev.type === 'x_remote_action_finished') sendOnShaft(ev.project_id, 'letter', true);
        else if (ev.type === 'x_deployed') sendOnShaft(ev.project_id, 'box_sealed', false);
        else if (ev.type === 'x_rolled_back') sendOnShaft(ev.project_id, 'box_sealed', true);
      },
      resize: () => scene.resize(),
      destroy: () => scene.destroy()
    };
  };

  // ---------------------------------------------------------------------------
  // 机房

  const MH = 164;
  const CEIL = 22;

  function drawDevice(c, m, x, t, reduced) {
    const base = 118;
    const on = m.online;
    const dim = (col) => (on ? col : P.mix(col, PAL.ink, 0.4));
    if (m.kind === 'host') {
      RB(c, x - 22, base - 70, 44, 70, dim(PAL.grey5));
      R(c, x - 20, base - 68, 40, 4, dim(PAL.grey4));
      for (let i = 0; i < Math.max(1, m.containers || 0); i++) {
        const busy = i < (m.actions || []).length;
        RB(c, x - 16 + (i % 3) * 12, base - 58 + Math.floor(i / 3) * 12, 9, 8, dim(busy ? PAL.blue2 : PAL.grey3));
      }
      for (let i = 0; i < 4; i++) R(c, x - 16 + i * 8, base - 18, 4, 2, on && !reduced && Math.floor(t / (200 + i * 70)) % 2 ? PAL.green2 : PAL.grey4);
    } else if (m.kind === 'desktop') {
      RB(c, x - 24, base - 44, 30, 22, dim(PAL.grey5));
      R(c, x - 22, base - 42, 26, 18, on ? '#2a4a6e' : '#1a1f28');
      R(c, x - 10, base - 22, 4, 6, dim(PAL.grey4)); R(c, x - 16, base - 16, 16, 2, dim(PAL.grey4));
      RB(c, x + 10, base - 40, 14, 40, dim(PAL.grey4));
      R(c, x + 13, base - 36, 8, 2, PAL.grey3);
      RB(c, x - 30, base - 2, 60, 3, PAL.wood2);
    } else if (m.kind === 'pi') {
      RB(c, x - 24, base - 22, 48, 4, PAL.wood2);
      RB(c, x - 14, base - 32, 28, 10, dim('#2f8f4a'));
      R(c, x - 10, base - 30, 6, 4, dim(PAL.grey1)); R(c, x + 2, base - 30, 8, 3, dim(PAL.metal2));
      for (let i = 0; i < 6; i++) R(c, x - 12 + i * 4, base - 33, 2, 1, PAL.yellow3);
    } else if (m.kind === 'laptop') {
      RB(c, x - 30, base - 2, 60, 3, PAL.wood2);
      RB(c, x - 18, base - 30, 36, 22, dim(PAL.grey4));
      R(c, x - 16, base - 28, 32, 18, on ? '#2a4a6e' : '#15181f');
      RB(c, x - 22, base - 8, 44, 5, dim(PAL.grey3));
    } else {
      throw new Error('未知的机器种类：' + m.kind);
    }
    // 在线指示灯
    RB(c, x + 18, base - 12, 4, 4, on ? PAL.green2 : PAL.grey4);
    if (on && !reduced && Math.floor(t / 700) % 2) R(c, x + 19, base - 11, 2, 2, PAL.green1);
    if (m.fault) {
      P.paint.beacon(c, x - 6, base - 88, { on: true, color: 'red' }, t);
    }
  }

  P.createMachineRoomScene = function createMachineRoomScene(canvas, opts) {
    const o = opts || {};
    let model = { machines: [], links: [] };
    const scene = P.createScene(canvas, { W, H: MH, draw, update });

    // 机房的世界：每台机器是一个设备节点，每个项目通往它正在使用的设备的管线是一根管道实体，
    // 部署、远程动作与回执的包裹沿着这根管道走；设备的闪光是带颜色的信号
    const world = ECS.world();

    const machineX = (i, n) => Math.round(W / (n + 1) * (i + 1));
    const xOf = (id) => (world.rooms[id] ? world.rooms[id].x : null);

    // 设备节点与管线：管线从天花板按项目颜色通到设备
    function declareWorld() {
      const n = model.machines.length;
      ECS.declareNodes(world, model.machines.map((m, i) => ({ id: m.id, roomKind: 'device', x: machineX(i, n), y: 118, w: 60, h: 90, def: m })));
      const defs = [];
      model.links.forEach((l, i) => {
        const x = xOf(l.machine_id);
        if (x === null) return;
        const ci = l.color_index % 6;
        const lx = x - 10 + (i % 5) * 5;
        const sx = W - 22 - ci * 3;
        const yh = CEIL + 2 + ci * 2;
        defs.push({ from: 'shaft:' + l.project_id, to: l.machine_id, kind: 'shaft', index: i, colorIndex: l.color_index, active: Boolean(l.active), lx, sx, yh,
          pts: [[sx + 1, 0], [sx + 1, yh + 1], [lx + 1, yh + 1], [lx + 1, CEIL + 28]] });
      });
      ECS.declareLinks(world, defs);
    }

    function update() {
      ECS.stepPipes(world, scene, (p) => (p.def.active ? 'flowing' : 'idle'));
      ECS.stepPackages(world, scene);
    }

    function draw(sc, c) {
      const t = sc.animT;
      R(c, 0, 0, W, MH, '#2b2f38');
      for (let x = 0; x < W; x += 20) R(c, x, 0, 1, MH, '#30343e');
      R(c, 0, 0, W, CEIL, '#3a3f4b'); R(c, 0, CEIL, W, 2, '#23262e');
      R(c, 0, 118, W, MH - 118, '#454a56');
      for (let x = 0; x < W; x += 16) R(c, x, 118, 1, MH - 118, '#3d424d');
      P.sign(c, 44, 16, '机房', { size: 7, bg: PAL.grey1, stripe: PAL.grey3 });
      // 管线：从天花板按项目颜色通到设备，管线里有光点在流动
      Object.values(world.links).forEach((p) => {
        const l = p.def;
        const col = LINK_COLORS[l.colorIndex % LINK_COLORS.length];
        const ci = l.colorIndex % 6;
        R(c, l.lx, l.yh, l.sx - l.lx + 2, 2, col);
        R(c, l.sx, 0, 2, l.yh + 2, col);
        R(c, l.lx, l.yh, 2, 118 - 70 - CEIL - ci * 2, col);
        if (sc.reduced) return;
        const f = p.flow;
        if (ECS.config.autonomy) {
          if (f && f.load > 0.02) {
            const k = (f.phase / 800 + l.index * 0.37) % 1;
            c.globalAlpha = f.load;
            R(c, l.lx - 1, CEIL + 2 + k * 40, 4, 3, PAL.yellow2);
            c.globalAlpha = 1;
          }
        } else if (l.active) {
          const k = (t / 800 + l.index * 0.37) % 1;
          R(c, l.lx - 1, CEIL + 2 + k * 40, 4, 3, PAL.yellow2);
        }
      });
      model.machines.forEach((m, i) => {
        const x = machineX(i, model.machines.length);
        drawDevice(c, m, x, t, sc.reduced);
        const flashColor = ECS.signalValue(world, scene, 'flash:' + m.id);
        if (flashColor) { c.fillStyle = P.rgba(flashColor, 0.3); c.fillRect(x - 40, 30, 80, 90); }
        P.text(c, m.name, x, 126, { size: 6.5, weight: 700, align: 'center', color: PAL.white, max: W / (model.machines.length + 1) - 6 });
        P.text(c, m.online ? '在线' : '离线', x, 135, { size: 5.5, weight: 600, align: 'center', color: m.online ? PAL.green1 : PAL.grey2 });
        let row = 0;
        (m.actions || []).slice(0, 2).forEach((a) => {
          const unknown = a.state === 'unknown';
          const text = (unknown ? '？结果未知 · ' : '') + a.label;
          P.sign(c, x, 152 + row * 11, text, { size: 5.5, bg: unknown ? PAL.yellow2 : PAL.white, stripe: unknown ? PAL.orange2 : PAL.blue2, maxW: W / (model.machines.length + 1) - 4 });
          row += 1;
        });
        if ((m.late_receipts || []).length) P.sign(c, x + 30, 98, '迟到回执', { size: 5.5, bg: PAL.grey1, stripe: PAL.grey3, maxW: 60 });
        (m.runtime_for || []).forEach((r, k) => P.sign(c, x, 44 + k * 12, r.name + ' · ' + r.version, { size: 5.5, bg: PAL.paper, stripe: PAL.green3, maxW: 120, pole: 2 }));
      });
      Object.values(world.packages).forEach((pk) => {
        const pos = ECS.packagePosition(pk);
        if (!pos) return;
        const b = P.bitmap(pk.bmp);
        P.drawBitmap(c, pk.bmp, Math.round(pos[0] - b.w / 2), Math.round(pos[1] - b.h / 2));
      });
      sc.drawParticles(c);
    }

    canvas.addEventListener('click', (ev) => {
      if (!o.onMachineClick) return;
      const rect = canvas.getBoundingClientRect();
      const x = ((ev.clientX - rect.left) / rect.width) * W;
      const n = model.machines.length;
      const i = model.machines.findIndex((m, k) => Math.abs(machineX(k, n) - x) < W / (n + 1) / 2);
      if (i >= 0) o.onMachineClick(model.machines[i].id);
    });

    let packageSeq = 0;
    // 包裹沿这个项目通往这台设备的管线走（往下是送到设备，往上是回执与回滚取回）；管线还没有画出来时从天花板直接落到设备上
    function sendToMachine(ev, machineId, bmp, up) {
      if (scene.reduced) return;
      const link = world.links['shaft:' + ev.project_id + '>' + machineId];
      let pts = link ? link.pts : [[xOf(machineId), CEIL], [xOf(machineId), CEIL + 50]];
      if (up) pts = pts.slice().reverse();
      const id = 'pk-' + (++packageSeq);
      ECS.spawnPackage(world, id, null, null, null, null);
      world.packages[id].bmp = bmp;
      ECS.sendPackage(world, id, link ? link.id : null, pts, travelMs(pts), () => ECS.removePackage(world, id));
    }

    return {
      scene,
      inspect: () => ({ world, model }),
      setModel(m) {
        if (!m || !Array.isArray(m.machines)) throw new Error('setModel 需要 machineRoomModel');
        model = Object.assign({ links: [] }, m);
        declareWorld();
        scene.setSize(W, MH + (model.machines.some((x) => (x.actions || []).length > 1) ? 12 : 0));
      },
      highlight(ids) {
        (ids || []).forEach((id) => { ECS.signal(world, scene, 'flash:' + id, 2500, PAL.yellow2); });
      },
      playEvent(ev) {
        const pl = (ev && ev.payload) || {};
        const x = pl.machine_id ? xOf(pl.machine_id) : null;
        if (x === null) return;
        const flash = (color, ms) => ECS.signal(world, scene, 'flash:' + pl.machine_id, ms, color);
        if (ev.type === 'x_machine_offline') flash(PAL.grey3, 1500);
        if (ev.type === 'x_machine_online' || ev.type === 'x_remote_action_finished') flash(PAL.green2, 1200);
        if (ev.type === 'x_action_unknown' || ev.type === 'x_late_receipt') flash(PAL.yellow2, 1500);
        if (ev.type === 'x_fault_recorded') flash(PAL.red2, 2500);
        if (ev.type === 'x_remote_action_started') sendToMachine(ev, pl.machine_id, 'folder', false);
        else if (ev.type === 'x_remote_action_finished') sendToMachine(ev, pl.machine_id, 'letter', true);
        else if (ev.type === 'x_deployed') sendToMachine(ev, pl.machine_id, 'box_sealed', false);
        else if (ev.type === 'x_rolled_back') sendToMachine(ev, pl.machine_id, 'box_sealed', true);
      },
      resize: () => scene.resize(),
      destroy: () => scene.destroy()
    };
  };
})();
