// 画面面板：把查询结果变成像素画面的模型（楼、机房、项目楼层），附上文字列表、覆盖层切换与回放时间轴。
// 页面只把面板放进容器，并转交 update、onEvent 与 destroy（BUILD.md 第 6.4 节）
(function () {
  'use strict';
  const Y12 = window.Y12;
  const esc = Y12.esc;
  const P = Y12.pixel;

  const DEPT = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const ROOM_STATUS = ['running', 'asking'];
  const IN_ROOM = ['running', 'asking', 'waiting_provider', 'paused', 'failed', 'done', 'cancelled', 'interrupted', 'waiting_resume', 'waiting_decision', 'stopped_for_upgrade'];
  const STATUS_TEXT = {
    waiting_decision: '等待你的决定',
    queued: '排队中', waiting_slot: '等待执行槽位', running: '运行中', asking: '询问中', waiting_provider: '等待模型服务', paused: '已暂停',
    failed: '失败', done: '已完成', cancelled: '已取消', interrupted: '中断', waiting_resume: '待恢复',
    stopped_for_upgrade: '因升级停止', adopted: '已采纳'
  };

  const q = (name, params, at) => Y12.api.query(name, Object.assign({}, params || {}, at !== null && at !== undefined ? { at } : {})).data;

  // ---------------------------------------------------------------------------
  // 像素画面沿用 v11 的事件词汇（BUILD.md 第 3 节）：正式成果被接纳以后关注它的部门开始一轮工作，
  // 画面上是包裹沿管道走到那个部门（transition）；询问是一次工具调用，画面上是信件在传信管里往返
  // （collaboration_requested、collaboration_responded、collaboration_closed）。这里把 v12 的事件转成画面认得的事件，像素代码不改
  const FLOW_OF = {
    spec_accepted: () => ({ from: 'product', to: 'engineering', artifact: 'prd' }),
    contract_accepted: () => ({ from: 'product', to: 'engineering', artifact: 'prd' }),
    delivery_accepted: () => ({ from: 'engineering', to: 'quality', artifact: 'box' }),
    structure_accepted: () => ({ from: 'engineering', to: 'quality', artifact: 'box' }),
    qa_submitted: (pl) => (pl.verdict === 'release'
      ? { from: 'quality', to: pl.release_to || 'library', artifact: 'release' }
      : { from: 'quality', to: 'engineering', artifact: 'defect' })
  };

  function pixelEvents(ev) {
    const pl = ev.payload || {};
    const as = (type, payload) => Object.assign({}, ev, { type, payload: Object.assign({}, pl, payload) });
    if (ev.type === 'ask_started') return [as('collaboration_requested', { from: pl.requester, to: pl.recipient, request_id: pl.ask_id })];
    if (ev.type === 'ask_answered') {
      const ids = { from: pl.recipient, to: pl.requester, request_id: pl.ask_id };
      return [as('collaboration_responded', ids), as('collaboration_closed', { from: pl.requester, to: pl.recipient, request_id: pl.ask_id })];
    }
    const flow = FLOW_OF[ev.type];
    return flow ? [ev, as('transition', flow(pl))] : [ev];
  }
  const playOn = (scene, ev) => pixelEvents(ev).forEach((e) => scene.playEvent(e));

  // ---------------------------------------------------------------------------
  // 楼与机房的模型

  function buildingModels(at) {
    const projects = q('projects.list', {}, at).filter((p) => !p.archived);
    const floors = projects.map((p) => {
      const loop = q('project.loop', { project: p.id }, at);
      const lit = {};
      // 几个部门同时工作时（预测性探索、回答询问）几个房间同时亮灯
      const busy = (it, d) => Boolean(it.departments && it.departments[d] && ['working', 'answering'].includes(it.departments[d].state));
      ['product', 'engineering', 'quality', 'operations'].forEach((d) => {
        lit[d] = loop.items.some((it) => ROOM_STATUS.includes(it.status) && (it.department === d || busy(it, d)));
      });
      if (loop.ops && loop.ops.version) lit.operations = true;
      const inUse = (loop.machines || []).filter((m) => m.actions > 0).map((m) => m.id);
      return {
        project_id: p.id, name: p.name, status: p.marker.status === 'archived' ? 'idle' : p.marker.status,
        lit, has_ops: Boolean(loop.ops),
        flags: loop.items.filter((it) => it.department && IN_ROOM.includes(it.status)).map((it) => ({ work_item_id: it.id, color_index: it.color_index, department: it.department })),
        valve_closed: loop.items.some((it) => it.status === 'waiting_slot'),
        machine_ids: inUse, link_active: inUse.length > 0,
        decisions: p.decisions_waiting,
        runtime_machine: loop.ops ? loop.ops.machine_id : null
      };
    });
    const hasMachines = Y12.cap.query('machines.list');
    let room = null;
    if (hasMachines) {
      const machines = q('machines.list', {}, at);
      const links = [];
      floors.forEach((f, i) => {
        f.machine_ids.forEach((id) => links.push({ project_id: f.project_id, color_index: i, machine_id: id, active: true }));
        if (f.runtime_machine && !f.machine_ids.includes(f.runtime_machine)) links.push({ project_id: f.project_id, color_index: i, machine_id: f.runtime_machine, active: false });
      });
      room = { machines, links };
    }
    return { building: { floors, show_basement: hasMachines }, room };
  }

  function buildingList(models) {
    const floors = models.building.floors.map((f) => {
      const lit = Object.keys(f.lit).filter((d) => f.lit[d]).map((d) => DEPT[d]).join('、');
      return '<li><button type="button" class="y12-link" data-go="' + esc(Y12.paths.overview(f.project_id, null)) + '">' + esc(f.name) + '</button>' +
        '<span>' + esc(STATUS_LABEL[f.status] || f.status) + '</span><span class="y12-muted">' + (lit ? esc(lit) + '在工作' : '没有部门在工作') + '</span>' +
        (f.decisions ? '<span class="y12-count is-decide">待你决定 ' + f.decisions + '</span>' : '') + '</li>';
    }).join('');
    const machines = models.room ? models.room.machines.map((m) =>
      '<li><strong>' + esc(m.name) + '</strong><span>' + (m.online ? '在线' : '离线') + '</span><span class="y12-muted">' +
      (m.actions.length ? m.actions.map((a) => esc(a.project_name + ' · ' + a.label + (a.state === 'unknown' ? '（结果未知）' : ''))).join('；') : '没有正在执行的动作') + '</span></li>'
    ).join('') : '';
    return '<details class="y12-scene-list"><summary>文字列表</summary><ul>' + floors + '</ul>' + (machines ? '<h4>机房</h4><ul>' + machines + '</ul>' : '') + '</details>';
  }

  const STATUS_LABEL = {
    waiting_decision: '等待你的决定',
    running: '运行中', queued: '排队中', waiting_slot: '等待执行槽位', waiting_provider: '等待模型服务',
    waiting_resume: '待恢复', interrupted: '中断', idle: '空闲'
  };

  // 首页：楼（每个项目一层）+ 地下室机房（3.2C）；时间轴放在 opts.timelineEl（报告下方）
  function mountBuilding(el, opts) {
    const o = opts || {};
    el.innerHTML = '<div class="y12-scene y12-building-wrap"><div class="y12-building-scroll"><canvas aria-label="楼：每个项目一层"></canvas></div>' +
      (Y12.cap.query('machines.list') ? '<div class="y12-machine-room"><canvas aria-label="地下室：机房"></canvas></div>' : '') + '</div><div class="y12-scene-text"></div>';
    const canvases = el.querySelectorAll('canvas');
    const building = P.createBuildingScene(canvases[0], { onFloorClick: (pid) => Y12.go(Y12.paths.overview(pid, null)) });
    const room = canvases[1] ? P.createMachineRoomScene(canvases[1], { onMachineClick: () => Y12.go('#/sys/machines') }) : null;
    let at = null;
    function refresh() {
      const models = buildingModels(at);
      building.setModel(models.building);
      if (room && models.room) room.setModel(models.room);
      el.querySelector('.y12-scene-text').innerHTML = buildingList(models);
    }
    refresh();
    let replay = null;
    if (o.timelineEl) {
      replay = Y12.replay.create({
        el: o.timelineEl, range: o.range,
        onPosition(pos) { at = pos; refresh(); el.classList.toggle('is-replay', pos !== null); },
        onFact(f) { building.playEvent(f.event); if (room) room.playEvent(f.event); },
        onSelect: o.onSelect
      });
    }
    return {
      replay,
      highlightMachines(ids) { if (room) room.highlight(ids); },
      update() { if (at === null) refresh(); if (replay) replay.reload(); },
      onEvent(ev) { if (at === null) { building.playEvent(ev); if (room) room.playEvent(ev); } },
      destroy() { building.destroy(); if (room) room.destroy(); if (replay) replay.destroy(); }
    };
  }

  function mountMachineRoom(el, opts) {
    const o = opts || {};
    el.innerHTML = '<div class="y12-scene y12-machine-room is-large"><canvas aria-label="机房"></canvas></div>';
    const room = P.createMachineRoomScene(el.querySelector('canvas'), { onMachineClick: o.onMachineClick });
    const refresh = () => room.setModel(buildingModels(null).room);
    refresh();
    if (o.highlight) room.highlight(o.highlight);
    return {
      update: refresh,
      onEvent: (ev) => room.playEvent(ev),
      highlight: (ids) => room.highlight(ids),
      destroy: () => room.destroy()
    };
  }

  // ---------------------------------------------------------------------------
  // 项目楼层

  function overlayData(id, projectId, loop) {
    if (id === 'flow') {
      const rows = Y12.api.query('project.flow', { project: projectId }).data.rows || [];
      const groups = {};
      rows.forEach((r) => {
        if (!r.from || !r.to) return;
        // 缺陷记录的流向在画面上沿用 v11 的返工画法
        const back = r.kind === 'defect';
        const key = r.from + '>' + r.to + '>' + (back ? 'rework' : '');
        const g = groups[key] || (groups[key] = { from: r.from, to: r.to, kind: back ? 'rework' : r.kind, count: 0, last_at: r.at });
        g.count += 1;
        if (Y12.time.ms(r.at) > Y12.time.ms(g.last_at)) g.last_at = r.at;
      });
      return { segments: Object.values(groups) };
    }
    if (id === 'waiting') {
      const now = Y12.app.now();
      const entries = [];
      const rows = {};
      const push = (department, text, since) => {
        const row = rows[department] || 0;
        rows[department] = row + 1;
        entries.push({ department, text, waited_sec: since ? Math.max(0, Y12.time.between(since, now)) : 0, row });
      };
      (loop.open_requests || []).forEach((r) => push(r.to, DEPT[r.from] + '的询问未回答', r.since));
      Y12.api.query('decisions.list', { project: projectId }).data.forEach((d) => {
        const it = loop.items.find((x) => x.id === d.work_item_id);
        push(it && it.department ? it.department : 'hall', '待你决定：' + d.kind_label, d.issued_at);
      });
      loop.items.filter((it) => it.status === 'waiting_slot').forEach((it) => push('hall', '等待执行槽位', null));
      (loop.waiting_provider || []).forEach((w) => push(w.department, '等待模型服务，' + Y12.time.clock(w.next_retry_at) + ' 重试', null));
      return { entries };
    }
    if (id === 'recovery') {
      return { entries: loop.items.filter((it) => ['interrupted', 'waiting_resume'].includes(it.status) && it.department)
        .map((it) => ({ department: it.department, state: it.status, text: STATUS_TEXT[it.status] + '：' + it.title })) };
    }
    if (id === 'context_usage') return Y12.api.query('overlay.context_usage', { project: projectId }).data;
    if (id === 'semantic_records') {
      const data = Y12.api.query('semantic.records', { project: projectId }).data;
      return { entries: data.summary || [] };
    }
    if (id === 'loops') return Y12.api.query('run.loops', { project_id: projectId }).data;
    // 事实元素与它们的来源由 project.loop 给出，楼层已经拿到
    if (id === 'sources') return {};
    if (id === 'coverage') return Y12.api.query('acceptance.coverage', { project_id: projectId }).data;
    throw new Error('未知的覆盖层：' + id);
  }

  // 场景的一步要打开覆盖层或点开事实元素：页面正在跳转时，等新的楼层挂载以后再做
  let activeFloor = null;
  const pending = { overlay: null, fact: null };
  const routeSettled = () => location.hash === Y12.route().hash;

  // Stage 5：部门里有几个角色，各自的状态（空闲、被分派、工作、交回、外出）；低档位没有角色，画面按一个部门一个小人画。
  // 回放到过去的时间点时也没有角色（部门工作间的查询不能回放），画面同样按一个部门一个小人画
  function rolesFor(loop, projectId, workItemId, at) {
    if (at !== null || !Y12.cap.query('role.detail')) return null;
    const out = {};
    Object.keys(DEPT).filter((d) => d !== 'operations' || loop.ops).forEach((d) => {
      out[d] = q('department.workspace', { project: projectId, department: d, work_item: workItemId || undefined }, at).roles;
    });
    return out;
  }

  // 等待回答的决定请求：像素画面里在大厅的板上，点开以后在画面里回答；这里给出同样内容的文字版本（画面之外的读取与操作方式）。
  // 回放到过去的时间点时不显示：回放里不能回答决定
  function decisionsFor(projectId, at) {
    if (at !== null || !Y12.cap.query('decisions.list')) return [];
    return q('decisions.list', { project: projectId }).map(Y12.cards.face);
  }

  function floorList(loop, projectId) {
    const rows = loop.items.map((it) => '<li><span class="y12-dot-color" style="--c:' + P.ITEM_COLORS[it.color_index % 6] + '"></span>' + esc(it.title) +
      '<span>' + esc(it.department ? DEPT[it.department] : '大厅') + '</span><span>' + (it.cycle ? '第 ' + it.cycle + ' 轮' : '') + '</span><span>' + esc(STATUS_TEXT[it.status] || it.status) + '</span></li>').join('');
    const decisions = loop.decisions && loop.decisions.length ? '<h4>待你决定</h4>' + Y12.cards.list({ project: projectId }) : '';
    return '<details class="y12-scene-list"><summary>文字列表</summary><ul>' + (rows || '<li class="y12-muted">没有事项</li>') + '</ul>' + decisions + '</details>';
  }

  function mountFloor(el, opts) {
    const o = opts || {};
    const overlays = Y12.cap.get().overlays;
    let overlay = null;
    let at = null;
    el.innerHTML = '<div class="y12-scene y12-floor-wrap">' +
      (overlays.length ? '<div class="y12-overlay-bar" role="group" aria-label="覆盖层">' + overlays.map((ov) =>
        '<button type="button" class="y12-seg-btn" data-overlay="' + esc(ov.id) + '">' + esc(ov.label) + Y12.ui.tag(Y12.registry.tagOf('overlay', ov.id)) + '</button>').join('') + '</div>' : '') +
      '<canvas aria-label="项目楼层：三部门循环"></canvas></div>' +
      '<div class="y12-scene-text"></div><div class="y12-floor-timeline"></div>';
    const floor = P.createFloorScene(el.querySelector('canvas'), {
      onDoorClick(ids) {
        Y12.go('#/home');
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const room = document.querySelector('.y12-machine-room');
          if (room) room.scrollIntoView({ behavior: 'smooth', block: 'center' });
          const home = Y12.views.get('home');
          if (home && home.highlightMachines) home.highlightMachines(ids);
        }));
      },
      // 决定请求在画面里回答：命令与提示跟页面上的卡片一样
      onDecide: (payload) => Y12.run('decision.answer', payload),
      onGo: (href) => Y12.go(href),
      // 来源卡片：读给出这条事实的事件；「在时间轴上查看」让时间轴跳到这条事件
      fetchEvent: (position) => Y12.api.query('event.detail', { position }).data.event,
      onSeek: (position) => replay.seekPosition(position)
    });
    function refresh() {
      const loop = q('project.loop', { project: o.projectId }, at);
      loop.focus_id = o.workItemId || null;
      loop.roles = rolesFor(loop, o.projectId, o.workItemId, at);
      loop.decisions = decisionsFor(o.projectId, at);
      floor.setModel(loop);
      floor.focus(o.workItemId || null);
      floor.setOverlay(overlay, overlay && at === null ? overlayData(overlay, o.projectId, loop) : null);
      el.querySelector('.y12-scene-text').innerHTML = floorList(loop, o.projectId);
    }
    function setOverlay(id) {
      overlay = id || null;
      el.querySelectorAll('[data-overlay]').forEach((b) => b.classList.toggle('is-on', b.dataset.overlay === overlay));
      refresh();
    }
    el.querySelectorAll('[data-overlay]').forEach((btn) => btn.addEventListener('click', () => setOverlay(overlay === btn.dataset.overlay ? null : btn.dataset.overlay)));
    refresh();
    const replay = Y12.replay.create({
      el: el.querySelector('.y12-floor-timeline'), project: o.projectId,
      onPosition(pos) { at = pos; refresh(); el.classList.toggle('is-replay', pos !== null); },
      onFact(f) { playOn(floor, f.event); }
    });
    const panel = {
      floor,
      replay,
      setOverlay,
      update() { if (at === null) refresh(); replay.reload(); },
      onEvent(ev) { if (at === null && ev.project_id === o.projectId) playOn(floor, ev); },
      destroy() {
        if (activeFloor === panel) activeFloor = null;
        floor.destroy();
        replay.destroy();
      }
    };
    activeFloor = panel;
    if (pending.overlay && overlays.some((ov) => ov.id === pending.overlay)) setOverlay(pending.overlay);
    if (pending.fact) floor.openFact(pending.fact);
    pending.overlay = null;
    pending.fact = null;
    return panel;
  }

  // 场景的一步：打开某个覆盖层（data-overlay）、点开某一种事实元素（data-kind）
  Y12.actions.register('scene.overlay', (el) => {
    if (activeFloor && routeSettled()) activeFloor.setOverlay(el.dataset.overlay);
    else pending.overlay = el.dataset.overlay;
  });
  Y12.actions.register('scene.fact', (el) => {
    if (activeFloor && routeSettled()) activeFloor.floor.openFact(el.dataset.kind);
    else pending.fact = el.dataset.kind;
  });

  // activeFloor：当前挂载的项目楼层面板（验收脚本读取它的画面）
  Y12.scenes = { mountBuilding, mountMachineRoom, mountFloor, buildingModels, pixelEvents, playOn, activeFloor: () => activeFloor };
})();
