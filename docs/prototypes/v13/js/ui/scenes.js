// 画面面板（画面与播放设计说明第 3 节）：页面里只做连接。查询结果与事件（Yudao 的说法）交给翻译层（js/translate/），
// 翻译层给出的画面合同交给像素画面（楼、机房、项目楼层），画面的回调变成命令或跳转；另附文字列表、覆盖层切换与回放时间轴。
// 页面只把面板放进容器，并转交 update、onEvent 与 destroy（BUILD.md 第 6.4 节）。
// 状态什么时候上画面由画面自己的播放时间线决定：打开面板、从后台切回、回放时直接显示（jump），其余时候等它之前的动作演完（setState）
(function () {
  'use strict';
  const Y13 = window.Y13;
  const esc = Y13.esc;
  const P = Y13.pixel;
  const T = Y13.translate;

  const DEPT = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const STATUS_TEXT = {
    waiting_decision: '等待你的决定',
    queued: '排队中', waiting_slot: '等待执行槽位', running: '运行中', asking: '询问中', waiting_provider: '等待模型服务', paused: '已暂停',
    failed: '失败', done: '已完成', cancelled: '已取消', interrupted: '中断', waiting_resume: '待恢复',
    stopped_for_upgrade: '因升级停止', adopted: '已采纳'
  };

  // 带位置的查询（位置是这份查询结果来自的快照）
  const qp = (name, params, at) => Y13.api.query(name, Object.assign({}, params || {}, at !== null && at !== undefined ? { at } : {}));
  const q = (name, params, at) => qp(name, params, at).data;

  // 从后台切回来（浏览器的标签页，或者原型工具条模拟的后台）：每个挂着的面板跳到最新，积下的动作不补播
  const panels = new Set();
  const backToFront = () => panels.forEach((p) => p.jumpToLatest());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) backToFront(); });
  Y13.bus.on('tab-visible', backToFront);

  // ---------------------------------------------------------------------------
  // 楼与机房

  function buildingStates(at) {
    const r = qp('projects.list', {}, at);
    const projects = r.data.filter((p) => !p.archived);
    const loops = {};
    projects.forEach((p) => { loops[p.id] = q('project.loop', { project: p.id }, at); });
    const hasMachines = Y13.cap.query('machines.list');
    const building = T.building.state({ position: r.position, projects, loops, machines: hasMachines });
    const room = hasMachines ? T.building.machineState({ position: r.position, machines: q('machines.list', {}, at) }, building) : null;
    return { building, room };
  }

  const SIGN_TEXT = {
    working: '运行中', queued: '排队中', waiting_slot: '等待执行槽位', waiting_model: '等待模型服务',
    waiting_resume: '待恢复', waiting_user: '等待你的决定', interrupted: '中断', idle: '空闲'
  };

  function buildingList(states) {
    const floors = states.building.floors.map((f) => {
      const lit = Object.keys(f.lit).filter((d) => f.lit[d]).map((d) => DEPT[d]).join('、');
      return '<li><button type="button" class="y13-link" data-go="' + esc(Y13.paths.overview(f.project_id, null)) + '">' + esc(f.name) + '</button>' +
        '<span>' + esc(SIGN_TEXT[f.status]) + '</span><span class="y13-muted">' + (lit ? esc(lit) + '在工作' : '没有部门在工作') + '</span>' +
        (f.decisions ? '<span class="y13-count is-decide">待你决定 ' + f.decisions + '</span>' : '') + '</li>';
    }).join('');
    const machines = states.room ? states.room.machines.map((m) =>
      '<li><strong>' + esc(m.name) + '</strong><span>' + (m.online ? '在线' : '离线') + '</span><span class="y13-muted">' +
      (m.actions.length ? m.actions.map((a) => esc(a.project_name + ' · ' + a.label + (a.state === 'unknown' ? '（结果未知）' : ''))).join('；') : '没有正在执行的动作') + '</span></li>'
    ).join('') : '';
    return '<details class="y13-scene-list"><summary>文字列表</summary><ul>' + floors + '</ul>' + (machines ? '<h4>机房</h4><ul>' + machines + '</ul>' : '') + '</details>';
  }

  // 楼与机房的动作：楼里的给楼，机房里的给机房
  function playBuilding(building, room, ev) {
    T.building.actions(ev).forEach((a) => {
      if (a.kind.indexOf('machine_') === 0) { if (room) room.play(a); } else building.play(a);
    });
  }

  // 首页：楼（每个项目一层）+ 地下室机房（3.2C）；时间轴放在 opts.timelineEl（报告下方）
  function mountBuilding(el, opts) {
    const o = opts || {};
    el.innerHTML = '<div class="y13-scene y13-building-wrap"><div class="y13-building-scroll"><canvas aria-label="楼：每个项目一层"></canvas></div>' +
      (Y13.cap.query('machines.list') ? '<div class="y13-machine-room"><canvas aria-label="地下室：机房"></canvas></div>' : '') + '</div><div class="y13-scene-text"></div>';
    const canvases = el.querySelectorAll('canvas');
    const building = P.createBuildingScene(canvases[0], { onFloorClick: (pid) => Y13.go(Y13.paths.overview(pid, null)) });
    const room = canvases[1] ? P.createMachineRoomScene(canvases[1], { onMachineClick: () => Y13.go('#/sys/machines') }) : null;
    let at = null;
    // jump 为真：直接显示（打开、回放、从后台切回）；否则等它之前的动作演完
    function refresh(jump) {
      const states = buildingStates(at);
      building[jump ? 'jump' : 'setState'](states.building);
      if (room && states.room) room[jump ? 'jump' : 'setState'](states.room);
      el.querySelector('.y13-scene-text').innerHTML = buildingList(states);
    }
    refresh(true);
    let replay = null;
    if (o.timelineEl) {
      replay = Y13.replay.create({
        el: o.timelineEl, range: o.range,
        onPosition(pos) { at = pos; refresh(true); el.classList.toggle('is-replay', pos !== null); },
        onFact(f) { playBuilding(building, room, f.event); },
        onSelect: o.onSelect
      });
    }
    const panel = {
      replay,
      building, room,
      highlightMachines(ids) { if (room) room.highlight(ids); },
      update() { if (at === null) refresh(false); if (replay) replay.reload(); },
      onEvent(ev) { if (at === null) playBuilding(building, room, ev); },
      jumpToLatest() { if (at === null) refresh(true); },
      destroy() { panels.delete(panel); building.destroy(); if (room) room.destroy(); if (replay) replay.destroy(); }
    };
    panels.add(panel);
    return panel;
  }

  function mountMachineRoom(el, opts) {
    const o = opts || {};
    el.innerHTML = '<div class="y13-scene y13-machine-room is-large"><canvas aria-label="机房"></canvas></div>';
    const room = P.createMachineRoomScene(el.querySelector('canvas'), { onMachineClick: o.onMachineClick });
    const refresh = (jump) => room[jump ? 'jump' : 'setState'](buildingStates(null).room);
    refresh(true);
    if (o.highlight) room.highlight(o.highlight);
    const panel = {
      room,
      update: () => refresh(false),
      onEvent: (ev) => T.building.actions(ev).filter((a) => a.kind.indexOf('machine_') === 0).forEach((a) => room.play(a)),
      highlight: (ids) => room.highlight(ids),
      jumpToLatest: () => refresh(true),
      destroy: () => { panels.delete(panel); room.destroy(); }
    };
    panels.add(panel);
    return panel;
  }

  // ---------------------------------------------------------------------------
  // 项目楼层

  // 覆盖层要的查询结果（覆盖层是用户打开的叠加信息，实时显示）
  function overlayInput(id, projectId, loop) {
    if (id === 'flow') return { rows: Y13.api.query('project.flow', { project: projectId }).data.rows || [] };
    if (id === 'waiting') return { loop, decisions: Y13.api.query('decisions.list', { project: projectId }).data, now: Y13.app.now() };
    if (id === 'recovery') return { loop };
    if (id === 'context_usage') return Y13.api.query('overlay.context_usage', { project: projectId }).data;
    if (id === 'semantic_records') return Y13.api.query('semantic.records', { project: projectId }).data;
    if (id === 'loops') return Y13.api.query('run.loops', { project_id: projectId }).data;
    // 事实元素与它们的来源由 project.loop 给出，楼层已经拿到
    if (id === 'sources') return {};
    if (id === 'coverage') return Y13.api.query('acceptance.coverage', { project_id: projectId }).data;
    throw new Error('未知的覆盖层：' + id);
  }

  // 一条事件的来源种类与说明（来源卡片、覆盖层里只有位置的事实）
  const eventAt = (position) => Y13.api.query('event.detail', { position }).data.event;
  const sourceOf = (position) => { const ev = eventAt(position); return ev && ev.source ? ev.source : null; };

  // 场景的一步要打开覆盖层或点开事实元素：页面正在跳转时，等新的楼层挂载以后再做
  let activeFloor = null;
  const pending = { overlay: null, fact: null };
  const routeSettled = () => location.hash === Y13.route().hash;

  // Stage 5：部门里有几个角色，各自的状态（空闲、被分派、工作、交回、外出）；低档位没有角色，画面按一个部门一个小人画。
  // 回放到过去的时间点时也没有角色（部门工作间的查询不能回放），画面同样按一个部门一个小人画
  function rolesFor(loop, projectId, workItemId, at) {
    if (at !== null || !Y13.cap.query('role.detail')) return null;
    const out = {};
    Object.keys(DEPT).filter((d) => d !== 'operations' || loop.ops).forEach((d) => {
      out[d] = q('department.workspace', { project: projectId, department: d, work_item: workItemId || undefined }, at).roles;
    });
    return out;
  }

  // 等待回答的决定请求：像素画面里在大厅的板上，点开以后在画面里回答；这里给出同样内容的文字版本（画面之外的读取与操作方式）。
  // 回放到过去的时间点时不显示：回放里不能回答决定
  function decisionsFor(projectId, at) {
    if (at !== null || !Y13.cap.query('decisions.list')) return [];
    return q('decisions.list', { project: projectId });
  }

  function floorList(loop, projectId) {
    const rows = loop.items.map((it) => '<li><span class="y13-dot-color" style="--c:' + P.ITEM_COLORS[it.color_index % 6] + '"></span>' + esc(it.title) +
      '<span>' + esc(it.department ? DEPT[it.department] : '大厅') + '</span><span>' + (it.cycle ? '第 ' + it.cycle + ' 轮' : '') + '</span><span>' + esc(STATUS_TEXT[it.status] || it.status) + '</span></li>').join('');
    const decisions = Y13.cap.query('decisions.list') && q('decisions.list', { project: projectId }).length ? '<h4>待你决定</h4>' + Y13.cards.list({ project: projectId }) : '';
    return '<details class="y13-scene-list"><summary>文字列表</summary><ul>' + (rows || '<li class="y13-muted">没有事项</li>') + '</ul>' + decisions + '</details>';
  }

  function mountFloor(el, opts) {
    const o = opts || {};
    const overlays = Y13.cap.get().overlays;
    let overlay = null;
    let at = null;
    let roles = null;
    el.innerHTML = '<div class="y13-scene y13-floor-wrap">' +
      (overlays.length ? '<div class="y13-overlay-bar" role="group" aria-label="覆盖层">' + overlays.map((ov) =>
        '<button type="button" class="y13-seg-btn" data-overlay="' + esc(ov.id) + '">' + esc(ov.label) + Y13.ui.tag(Y13.registry.tagOf('overlay', ov.id)) + '</button>').join('') + '</div>' : '') +
      '<canvas aria-label="项目楼层：三部门循环"></canvas></div>' +
      '<div class="y13-scene-text"></div><div class="y13-floor-timeline"></div>';
    const floor = P.createFloorScene(el.querySelector('canvas'), {
      onDoorClick(ids) {
        Y13.go('#/home');
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const room = document.querySelector('.y13-machine-room');
          if (room) room.scrollIntoView({ behavior: 'smooth', block: 'center' });
          const home = Y13.views.get('home');
          if (home && home.highlightMachines) home.highlightMachines(ids);
        }));
      },
      // 决定请求在画面里回答：命令与提示跟页面上的卡片一样
      onDecide: (payload) => Y13.run('decision.answer', payload),
      onGo: (href) => Y13.go(href),
      // 来源卡片：给出这条事实的事件的说明；「在时间轴上查看」让时间轴跳到这条事件
      describe: (position) => T.floor.describe(eventAt(position)),
      onSeek: (position) => replay.seekPosition(position)
    });
    const roleName = (id) => {
      const all = roles ? Object.values(roles).reduce((list, r) => list.concat(r), []) : [];
      const hit = all.find((r) => r.id === id || r.kind === id);
      return hit ? hit.name : null;
    };
    // jump 为真：直接显示（打开、回放、从后台切回、打开覆盖层以后）；否则等它之前的动作演完
    function refresh(jump) {
      const r = qp('project.loop', { project: o.projectId }, at);
      const loop = r.data;
      roles = rolesFor(loop, o.projectId, o.workItemId, at);
      const state = T.floor.state({ position: r.position, loop, roles, focus: o.workItemId || null });
      floor[jump ? 'jump' : 'setState'](state);
      floor.setDecisions(T.floor.cards(decisionsFor(o.projectId, at)));
      floor.focus(o.workItemId || null);
      floor.setOverlay(overlay, overlay && at === null ? T.floor.overlay(overlay, overlayInput(overlay, o.projectId, loop), sourceOf) : null);
      el.querySelector('.y13-scene-text').innerHTML = floorList(loop, o.projectId);
    }
    function setOverlay(id) {
      overlay = id || null;
      el.querySelectorAll('[data-overlay]').forEach((b) => b.classList.toggle('is-on', b.dataset.overlay === overlay));
      const loop = q('project.loop', { project: o.projectId }, at);
      floor.setOverlay(overlay, overlay && at === null ? T.floor.overlay(overlay, overlayInput(overlay, o.projectId, loop), sourceOf) : null);
    }
    // 一条事件：动作进时间线，流式文字到了就显示
    function play(ev) {
      const s = T.stream(ev);
      if (s) floor.stream(s.who, s.text);
      T.floor.actions(ev, { roleName }).forEach((a) => floor.play(a));
    }
    el.querySelectorAll('[data-overlay]').forEach((btn) => btn.addEventListener('click', () => setOverlay(overlay === btn.dataset.overlay ? null : btn.dataset.overlay)));
    refresh(true);
    const replay = Y13.replay.create({
      el: el.querySelector('.y13-floor-timeline'), project: o.projectId,
      onPosition(pos) { at = pos; refresh(true); el.classList.toggle('is-replay', pos !== null); },
      onFact(f) { play(f.event); }
    });
    const panel = {
      floor,
      replay,
      setOverlay,
      update() { if (at === null) refresh(false); replay.reload(); },
      onEvent(ev) { if (at === null && ev.project_id === o.projectId) play(ev); },
      jumpToLatest() { if (at === null) refresh(true); },
      destroy() {
        panels.delete(panel);
        if (activeFloor === panel) activeFloor = null;
        floor.destroy();
        replay.destroy();
      }
    };
    panels.add(panel);
    activeFloor = panel;
    if (pending.overlay && overlays.some((ov) => ov.id === pending.overlay)) setOverlay(pending.overlay);
    if (pending.fact) floor.openFact(pending.fact);
    pending.overlay = null;
    pending.fact = null;
    return panel;
  }

  // ---------------------------------------------------------------------------
  // 部门房间：department.workspace 翻成房间的状态，事件翻成这个部门的动作

  function mountRoom(canvas, opts) {
    const o = opts || {};
    const room = P.createRoomScene(canvas, { department: o.department });
    let roles = [];
    const roleName = (id) => { const hit = roles.find((r) => r.id === id || r.kind === id); return hit ? hit.name : null; };
    // workspace：带位置的 department.workspace 查询结果
    function show(r, jump) {
      roles = r.data.room.roles;
      room[jump ? 'jump' : 'setState'](T.room.state({ position: r.position, workspace: r.data }));
    }
    const panel = {
      room,
      show,
      onEvent(ev) {
        const s = T.stream(ev);
        if (s && s.who.room === o.department) room.stream(s.who, s.text);
        T.room.actions(ev, o.department, { roleName }).forEach((a) => room.play(a));
      },
      jumpToLatest() { if (o.latest) show(o.latest(), true); },
      destroy() { panels.delete(panel); room.destroy(); }
    };
    panels.add(panel);
    return panel;
  }

  // 场景的一步：打开某个覆盖层（data-overlay）、点开某一种事实元素（data-kind）
  Y13.actions.register('scene.overlay', (el) => {
    if (activeFloor && routeSettled()) activeFloor.setOverlay(el.dataset.overlay);
    else pending.overlay = el.dataset.overlay;
  });
  Y13.actions.register('scene.fact', (el) => {
    if (activeFloor && routeSettled()) activeFloor.floor.openFact(el.dataset.kind);
    else pending.fact = el.dataset.kind;
  });

  // activeFloor：当前挂载的项目楼层面板（验收脚本读取它的画面）；panels：全部挂着的面板（调节面板读取它们的时间线）
  Y13.scenes = { mountBuilding, mountMachineRoom, mountFloor, mountRoom, buildingStates, activeFloor: () => activeFloor, panels: () => Array.from(panels) };
})();
