// 行为检查：用手写的数据驱动项目楼层、楼与机房画面，按确定的时钟检查 v9 的新增行为，全部通过才算通过。
//   多角色    一个部门里有几个角色，同时做着不同的任务；事件按角色找到人，交接由经理做
//   自主行为  空闲的角色自己挑事情做（走动、翻文件柜、互相说话），关闭自主行为以后一件也没有
//   管道流动  流速与光点带着惯性：停止时光点留在管道里，空闲时光点淡出
//   机房      远程动作、部署、回滚的包裹沿项目通往设备的管线走
//   决定卡片  决定单贴在大厅的板上，点开在画面里回答；提出决定时小人送单
//   声明      去掉一个房间、加一个房间，都只改声明，ecs.js 与 floor.js 没有任何具体的部门名
// 用法：node docs/prototypes/v9/checks/behaviors.js
const fs = require('fs');
const path = require('path');
const { chromium, EXE, v9Url } = require('./env');

// ---------------------------------------------------------------------------
// 声明与引擎的分离：去掉注释以后，ecs.js、floor.js、decision-card.js 里不能出现具体的部门名
function staticChecks() {
  const out = [];
  const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/\s\/\/ .*$/gm, '');
  ['ecs.js', 'floor.js', 'decision-card.js'].forEach((f) => {
    const src = strip(fs.readFileSync(path.join(__dirname, '../js/pixel', f), 'utf8'));
    const hits = src.match(/['"`](product|engineering|quality|operations)['"`]/g) || [];
    out.push({ name: f + ' 里没有具体的部门名', ok: hits.length === 0, detail: hits.join(' ') });
  });
  return out;
}

// ---------------------------------------------------------------------------
// 在页面里运行的检查
const DRIVER = async () => {
  const P = window.Y8.pixel;
  const E = P.ecs;
  const results = [];
  const check = (name, ok, detail) => results.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail) });

  // 确定的时钟与随机数
  let t = 0;
  const q = [];
  window.requestAnimationFrame = (cb) => { q.push(cb); return q.length; };
  window.cancelAnimationFrame = () => {};
  performance.now = () => t;
  let seed = 246813579;
  Math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const step = (ms, dt) => {
    const d = dt || 50;
    const n = Math.max(1, Math.round(ms / d));
    for (let i = 0; i < n; i++) { t += d; const cbs = q.splice(0); for (const cb of cbs) cb(t); }
  };

  const clone = (v) => JSON.parse(JSON.stringify(v));
  const box = () => {
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;left:0;top:0;width:640px;height:320px;z-index:99999;background:#000';
    const canvas = document.createElement('canvas');
    host.appendChild(canvas);
    document.body.appendChild(host);
    return { host, canvas };
  };
  const mountFloor = (model, opts) => {
    const b = box();
    const fl = P.createFloorScene(b.canvas, opts || {});
    fl.setModel(clone(model));
    return Object.assign(b, { fl });
  };
  const drop = (m) => { m.fl.destroy(); m.host.remove(); };

  const role = (id, kind, name, status) => ({ id, kind, name, status: status || 'idle', task: null });
  const ROLES = {
    product: [role('p-mgr', 'manager', '产品部门经理'), role('p-arch', 'architect', '产品架构师', 'working'), role('p-exp', 'explorer', '产品探索者'), role('p-rev', 'reviewer', '产品审查者')],
    engineering: [role('e-mgr', 'manager', '工程经理'), role('e-arch', 'architect', '工程架构师', 'working'), role('e-lead', 'lead', '主程'), role('e-exp', 'explorer', '工程探索者'), role('e-rev', 'reviewer', '工程审查者')],
    quality: [role('q-mgr', 'manager', '质检经理'), role('q-test', 'tester', '测试工程师', 'working'), role('q-exp', 'explorer', '质检探索者'), role('q-rev', 'reviewer', '质检审查者')]
  };
  const item = (status, department) => ({ id: 'w1', title: '测试事项', color_index: 0, kind: 'request', status, department, cycle: 1, elapsed_sec: 100, limit_sec: 7200 });
  const MODEL = (over) => Object.assign({
    items: [item('running', 'engineering')], open_requests: [], shelves: { adopted: [] }, slots: { total: 3, used: 1 }, waiting_provider: [],
    machines: null, ops: null, interrupted: false, roles: ROLES, decisions: []
  }, over || {});

  try {
    // ------------------------------------------------------------------ 多角色
    E.config.autonomy = false;
    let m = mountFloor(MODEL());
    step(1500);
    let ins = m.fl.inspect();
    check('多角色：三个部门共 13 个角色实体', Object.keys(ins.world.characters).length === 13, Object.keys(ins.world.characters).length);
    const eng = ins.world.rooms.engineering;
    const seatX = E.charsOf(ins.world, 'engineering').map((c) => eng.seats[c.seatIndex].seatX);
    check('多角色：工程部门 5 个角色的工位各不相同', new Set(seatX).size === 5, seatX.join(','));
    const sprites = m.fl.scene.actors.filter((a) => a.data.ecsChar && a.data.dept === 'engineering').map((a) => a.sprite).sort();
    check('多角色：工程部门的小人按角色种类取精灵', sprites.join() === 'engineering.architect,engineering.explorer,engineering.lead,engineering.manager,engineering.reviewer', sprites.join());

    // 同一个部门同时有几个角色做着不同的任务：事件按角色找到人
    const ev = (type, role, payload) => ({ type, department: 'engineering', role, work_item_id: 'w1', payload: payload || {} });
    m.fl.playEvent(ev('x_role_task_assigned', 'e-lead', { to: 'e-lead', task: '实现' }));
    m.fl.playEvent(ev('x_explorer_fetch', 'e-exp'));
    m.fl.playEvent(ev('x_review_recorded', 'e-rev', { verdict: 'passed' }));
    m.fl.playEvent(ev('model_request_serialized', 'e-arch'));
    step(600);
    ins = m.fl.inspect();
    const busy = E.charsOf(ins.world, 'engineering').filter((c) => c.current);
    check('多角色：同一个部门里至少 4 个角色同时有正在做的任务', busy.length >= 4, busy.map((c) => c.id + ':' + c.current.taskKey).join(' '));
    check('多角色：任务各不相同', new Set(busy.map((c) => c.current.taskKey)).size >= 4, busy.map((c) => c.current.taskKey).join(' '));
    check('多角色：分派任务由经理做', ins.world.characters['e-mgr'].current && ins.world.characters['e-mgr'].current.taskKey === 'x_role_task_assigned');
    check('多角色：分派走到接任务的角色的工位旁', ins.world.characters['e-mgr'].current && ins.world.characters['e-mgr'].current.withId === 'e-lead');
    check('多角色：探索者查资料', ins.world.characters['e-exp'].current && ins.world.characters['e-exp'].current.taskKey === 'x_explorer_fetch');
    check('多角色：审查者盖章', ins.world.characters['e-rev'].current && ins.world.characters['e-rev'].current.taskKey === 'x_review_recorded_passed');
    check('多角色：架构师打字', ins.world.characters['e-arch'].current && ins.world.characters['e-arch'].current.taskKey === 'model_requested');
    // 交回结果：工具角色走向经理，经理收下
    m.fl.playEvent(ev('x_role_result_returned', 'e-lead', { to: 'e-lead' }));
    step(6000);
    ins = m.fl.inspect();
    check('多角色：所有任务做完以后角色回到工位', E.charsOf(ins.world, 'engineering').every((c) => !c.current && !c.queue.length));
    // 对外的交接由经理做
    m.fl.playEvent({ type: 'transition', work_item_id: 'w1', payload: { from: 'engineering', to: 'quality', artifact: 'box' } });
    step(200);
    ins = m.fl.inspect();
    const mgrTask = ins.world.characters['e-mgr'].current || ins.world.characters['e-mgr'].queue[0];
    check('多角色：交接由经理走到管道口放下包裹', mgrTask && mgrTask.taskKey === 'package_handoff_out', mgrTask && mgrTask.taskKey);
    check('多角色：中心角色不做交接', !ins.world.characters['e-arch'].current && !ins.world.characters['e-arch'].queue.length);
    step(8000);
    ins = m.fl.inspect();
    check('多角色：包裹走完以后质检的经理取出', !ins.world.characters['q-mgr'].current && !ins.world.characters['q-mgr'].queue.length && Object.keys(ins.world.packages).length === 0);
    // 没有角色设置（低档位）：一个部门一个小人，分派事件没有反应也不出错
    drop(m);
    m = mountFloor(MODEL({ roles: null }));
    step(500);
    ins = m.fl.inspect();
    check('没有角色设置：一个部门一个小人', Object.keys(ins.world.characters).length === 3, Object.keys(ins.world.characters).join());
    m.fl.playEvent(ev('x_role_task_assigned', 'e-lead', { to: 'e-lead' }));
    step(300);
    check('没有角色设置：分派事件不产生任务', E.charsOf(m.fl.inspect().world, 'engineering').every((c) => !c.current && !c.queue.length));
    drop(m);

    // ------------------------------------------------------------------ 自主行为
    const idleModel = MODEL({ items: [] });
    const calls = [];
    const orig = E.enqueue;
    E.enqueue = function (world, who, key) { if (String(key).indexOf('idle_') === 0) calls.push(key); return orig.apply(this, arguments); };
    E.config.autonomy = false;
    m = mountFloor(idleModel);
    step(40000, 100);
    check('自主行为关闭：没有待机活动', calls.length === 0, calls.length);
    drop(m);
    E.config.autonomy = true;
    m = mountFloor(idleModel);
    step(60000, 100);
    const kinds = Array.from(new Set(calls));
    check('自主行为：空闲的角色自己挑事情做', calls.length >= 8, calls.length);
    check('自主行为：不止一种待机活动', kinds.length >= 3, kinds.join());
    check('自主行为：互相说话的两个角色成对出现', calls.filter((k) => k === 'idle_chat').length % 2 === 0, calls.filter((k) => k === 'idle_chat').length);
    // 真正的任务优先：待机活动进行中来了事件，立刻放弃待机
    let victim = null;
    for (let i = 0; i < 400 && !victim; i++) {
      step(100);
      victim = Object.values(m.fl.inspect().world.characters).find((c) => c.current && c.current.idle && c.department === 'engineering');
    }
    check('自主行为：找到一个正在待机活动中的角色', Boolean(victim));
    if (victim) {
      m.fl.playEvent({ type: 'model_request_serialized', department: 'engineering', role: victim.id, work_item_id: 'w1', payload: {} });
      step(100);
      check('自主行为：真正的任务来了，待机活动立刻放弃', victim.current && victim.current.taskKey === 'model_requested', victim.current && victim.current.taskKey);
    }
    E.enqueue = orig;
    drop(m);
    E.config.autonomy = false;

    // ------------------------------------------------------------------ 管道流动
    E.config.autonomy = true;
    m = mountFloor(MODEL());
    step(2500);
    let link = m.fl.inspect().world.links['product>engineering'];
    check('管道：有活跃事项时满速流动，光点布满', link.flow.state === 'flowing' && link.flow.speed > 0.99 && link.flow.load > 0.95, JSON.stringify(link.flow));
    const phase0 = link.flow.phase;
    step(500);
    check('管道：光点持续向前移动', link.flow.phase > phase0 + 400, link.flow.phase - phase0);
    m.fl.setModel(clone(MODEL({ items: [item('waiting_provider', 'engineering')], waiting_provider: [{ department: 'engineering', next_retry_at: '2026-09-29T12:00:00+08:00' }] })));
    step(1500);
    link = m.fl.inspect().world.links['product>engineering'];
    check('管道：等待模型服务时停下，光点留在管道里', link.flow.state === 'stopped' && link.flow.speed < 0.05 && link.flow.load > 0.9, JSON.stringify(link.flow));
    const phaseStop = link.flow.phase;
    step(1000);
    check('管道：停下的管道里光点不再移动', Math.abs(link.flow.phase - phaseStop) < 1, link.flow.phase - phaseStop);
    m.fl.setModel(clone(MODEL({ items: [] })));
    step(3500);
    link = m.fl.inspect().world.links['product>engineering'];
    check('管道：空闲以后减速，光点淡出', link.flow.state === 'idle' && link.flow.speed < 0.02 && link.flow.load < 0.05, JSON.stringify(link.flow));
    drop(m);
    E.config.autonomy = false;

    // ------------------------------------------------------------------ 机房与楼
    let b = box();
    const room = P.createMachineRoomScene(b.canvas, {});
    room.setModel({
      machines: [{ id: 'm1', name: '主机', kind: 'host', online: true, containers: 2, actions: [], runtime_for: [], late_receipts: [] }],
      links: [{ project_id: 'p1', color_index: 0, machine_id: 'm1', active: true }]
    });
    const rw = () => room.inspect().world;
    check('机房：设备是节点，管线是管道实体', rw().rooms.m1 && rw().rooms.m1.roomKind === 'device' && Boolean(rw().links['shaft:p1>m1']));
    room.playEvent({ type: 'x_remote_action_started', project_id: 'p1', payload: { machine_id: 'm1' } });
    step(300);
    let pk = Object.values(rw().packages);
    check('机房：远程动作的包裹沿项目的管线走', pk.length === 1 && pk[0].transit && pk[0].transit.linkKey === 'shaft:p1>m1', pk.map((x) => x.transit && x.transit.linkKey).join());
    step(4000);
    check('机房：包裹到达以后消失', Object.keys(rw().packages).length === 0);
    room.playEvent({ type: 'x_rolled_back', project_id: 'p1', payload: { machine_id: 'm1' } });
    step(100);
    pk = Object.values(rw().packages);
    check('机房：回滚的包裹从设备往上走', pk.length === 1 && pk[0].transit.pts[0][1] > pk[0].transit.pts[pk[0].transit.pts.length - 1][1], pk.length);
    room.destroy(); b.host.remove();
    b = box();
    const bld = P.createBuildingScene(b.canvas, {});
    bld.setModel({ floors: [{ project_id: 'p1', name: 'p1', status: 'running', lit: {}, has_ops: false, flags: [], valve_closed: false, machine_ids: ['m1'], link_active: true, decisions: 0, runtime_machine: null }], show_basement: true });
    check('楼：通往机房的管线是管道实体', Boolean(bld.inspect().world.links['floor:p1>basement']));
    bld.playEvent({ type: 'x_remote_action_started', project_id: 'p1', payload: { machine_id: 'm1' } });
    step(200);
    check('楼：远程动作的包裹沿竖井往下走', Object.values(bld.inspect().world.packages).length === 1);
    bld.destroy(); b.host.remove();

    // ------------------------------------------------------------------ 决定卡片
    const face = (id, over) => Object.assign({
      id, kind: 'waiting_resume', version: 3, title: '模型引用无法使用时的待恢复', work_item_id: 'w1', where: '项目 · 测试事项', waited: '已等待 1 分', blocks: '不挡住事项',
      rows: [['部门', '工程']], links: [], options: [{ id: 'go', label: '继续执行', kind: 'primary' }, { id: 'stop', label: '停止事项', kind: 'danger' }], view: null
    }, over || {});
    const answers = [];
    m = mountFloor(MODEL({ decisions: [face('d1')] }), { onDecide: (p) => { answers.push(p); return { accepted: true, message: '已提交' }; } });
    step(200);
    const click = (x, y) => m.canvas.dispatchEvent(new MouseEvent('click', { clientX: x, clientY: y, bubbles: true }));
    let card = m.fl.inspect().card;
    check('决定卡片：没有点开以前卡片关着', !card.isOpen());
    click(82, 172);
    check('决定卡片：点大厅的板子打开卡片', card.isOpen() && card.openId() === 'd1');
    step(100);
    click(110, 270);
    check('决定卡片：点选项调用回答命令，带着决定的版本', answers.length === 1 && answers[0].decision_id === 'd1' && answers[0].option === 'go' && answers[0].base_version === 3, JSON.stringify(answers));
    step(1500);
    check('决定卡片：盖章以后卡片关上', !card.isOpen());
    drop(m);
    // 需要说明的选项：没写说明不提交
    const needNote = face('d2', { options: [{ id: 'revise', label: '提出修改', kind: null, note_required: true }] });
    answers.length = 0;
    m = mountFloor(MODEL({ decisions: [needNote] }), { onDecide: (p) => { answers.push(p); return { accepted: true }; } });
    step(200);
    card = m.fl.inspect().card;
    click(82, 172);
    step(100);
    click(110, 270);
    check('决定卡片：需要说明的选项，没写说明就不提交', answers.length === 0 && card.isOpen());
    drop(m);
    // 回答以后事件流带来的新列表里已经没有这个决定：纸留到盖章结束，说明栏的文字也留着
    const pixel = (canvas, x, y) => Array.from(canvas.getContext('2d').getImageData(x, y, 1, 1).data.slice(0, 3));
    const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
    answers.length = 0;
    m = mountFloor(MODEL({ decisions: [face('d5')] }), { onDecide: (p) => { answers.push(p); return { accepted: true }; } });
    step(200);
    card = m.fl.inspect().card;
    click(82, 172);
    step(100);
    const noteBox = m.host.querySelector('textarea[aria-label="决定的说明"]');
    noteBox.value = '照旧继续';
    noteBox.dispatchEvent(new Event('input', { bubbles: true }));
    click(110, 270);
    m.fl.setModel(clone(MODEL({ decisions: [] })));
    step(300);
    check('决定卡片：回答以后列表里没有这个决定，纸仍然留着', card.isOpen() && JSON.stringify(pixel(m.canvas, 200, 130)) === JSON.stringify(hex(P.PAL.paper)), JSON.stringify(pixel(m.canvas, 200, 130)));
    check('决定卡片：盖章期间说明栏的文字还在', noteBox.value === '照旧继续', noteBox.value);
    step(1500);
    check('决定卡片：盖章结束纸收起', !card.isOpen());
    drop(m);
    // 翻页与关闭：两组按钮不重叠，点翻页翻到下一张，点关闭关上；别处文本框里的方向键不翻页
    m = mountFloor(MODEL({ decisions: [face('d6'), face('d7')] }));
    step(200);
    card = m.fl.inspect().card;
    click(82, 172);
    step(100);
    click(506, 38);
    check('决定卡片：点翻页按钮的中心翻到下一张', card.isOpen() && card.openId() === 'd7', card.openId());
    const other = document.createElement('input');
    document.body.appendChild(other);
    other.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    check('决定卡片：别处文本框里的方向键不翻页', card.openId() === 'd7', card.openId());
    other.remove();
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    check('决定卡片：方向键翻页', card.openId() === 'd6', card.openId());
    click(536, 38);
    check('决定卡片：点关闭按钮关上', !card.isOpen());
    drop(m);
    // 板子立在地面上，不压槽位灯与墙钟：槽位总数很多时板子所在的位置仍然是木板
    m = mountFloor(MODEL({ slots: { total: 8, used: 2 }, decisions: [face('d8')] }));
    step(300);
    check('决定板：槽位灯很多时板子不被压住', JSON.stringify(pixel(m.canvas, 94, 180)) === JSON.stringify(hex('#c9955c')), JSON.stringify(pixel(m.canvas, 94, 180)));
    drop(m);
    // 回答的方向：回答方是事件所在的部门
    m = mountFloor(MODEL());
    step(500);
    m.fl.playEvent({ type: 'collaboration_responded', department: 'product', work_item_id: 'w1', payload: { from: 'product', to: 'engineering', request_id: 'q1' } });
    step(200);
    ins = m.fl.inspect();
    const answerTask = ins.world.characters['p-mgr'].current || ins.world.characters['p-mgr'].queue[0];
    check('询问的回答：回答的部门的经理走到传信管口', answerTask && answerTask.taskKey === 'letter_out', answerTask && answerTask.taskKey);
    let flew = false;
    for (let i = 0; i < 60 && !flew; i++) { step(100); flew = Object.values(m.fl.inspect().world.packages).some((pk) => pk.transit && pk.transit.linkKey === 'product~engineering'); }
    check('询问的回答：回信沿产品到工程的传信管走', flew);
    drop(m);
    // 快照里运维数据出现：房间重新声明，在途的包裹、角色与任务原样保留
    m = mountFloor(MODEL());
    step(500);
    m.fl.playEvent({ type: 'transition', work_item_id: 'w1', payload: { from: 'engineering', to: 'quality', artifact: 'box' } });
    let inFlightPk = 0;
    for (let i = 0; i < 80 && !inFlightPk; i++) { step(100); inFlightPk = Object.keys(m.fl.inspect().world.packages).length; }
    const before = m.fl.inspect().world.characters['e-mgr'];
    m.fl.setModel(clone(MODEL({ ops: { version: 'r1', fault: false } })));
    step(100);
    ins = m.fl.inspect();
    check('运维数据出现：房间重新声明，运维房间出现', ins.world.roomOrder.indexOf('operations') >= 0);
    check('运维数据出现：在途的包裹与原来的角色实体保留', inFlightPk === 1 && Object.keys(ins.world.packages).length === 1 && ins.world.characters['e-mgr'] === before);
    step(8000);
    ins = m.fl.inspect();
    check('运维数据出现：包裹照常走完，接收方的经理取出', Object.keys(ins.world.packages).length === 0 && !ins.world.characters['q-mgr'].current && !ins.world.characters['q-mgr'].queue.length);
    drop(m);
    // 决定请求发出：提出决定的部门的经理走到门口送出决定单
    m = mountFloor(MODEL({ decisions: [face('d3')] }));
    step(300);
    m.fl.playEvent({ type: 'x_decision_issued', department: 'engineering', work_item_id: 'w1', payload: { decision_id: 'd3', kind: 'waiting_resume' } });
    step(200);
    ins = m.fl.inspect();
    const post = ins.world.characters['e-mgr'].current || ins.world.characters['e-mgr'].queue[0];
    check('决定卡片：提出决定的部门的经理去门口送决定单', post && post.taskKey === 'x_decision_issued', post && post.taskKey);
    let flying = 0;
    for (let i = 0; i < 80 && !flying; i++) { step(100); flying = m.fl.scene.flyers.length; }
    check('决定卡片：送出以后决定单飞向大厅的板子', flying === 1, flying);
    step(3000);
    check('决定卡片：决定单落到板上，飞行结束', m.fl.scene.flyers.length === 0);
    drop(m);

    // ------------------------------------------------------------------ 声明
    const D = P.floorDecl;
    const savedRooms = D.rooms.slice();
    const opsAt = D.rooms.findIndex((r) => r.id === 'operations');
    const opsModel = MODEL({ ops: { version: 'r1', fault: false }, items: [item('running', 'engineering')] });
    m = mountFloor(opsModel);
    step(300);
    check('声明：有运维数据时运维房间出现', m.fl.inspect().world.roomOrder.indexOf('operations') >= 0);
    m.fl.playEvent({ type: 'x_deployed', work_item_id: 'w1', payload: { version: 'r1', machine_id: 'm1' } });
    step(200);
    const opsCh = Object.values(m.fl.inspect().world.characters).find((c) => c.department === 'operations');
    check('声明：运维的部署事件变成运维小人的任务', opsCh && opsCh.current && opsCh.current.taskKey === 'x_deployed', opsCh && opsCh.current && opsCh.current.taskKey);
    drop(m);
    D.rooms.splice(opsAt, 1);
    m = mountFloor(opsModel);
    step(300);
    m.fl.playEvent({ type: 'x_deployed', work_item_id: 'w1', payload: { version: 'r1', machine_id: 'm1' } });
    step(300);
    check('声明：去掉运维的声明以后，房间不出现，运维事件没有反应也不出错', m.fl.inspect().world.roomOrder.indexOf('operations') < 0 && Object.keys(m.fl.inspect().world.packages).length === 0);
    drop(m);
    D.rooms.splice(0, D.rooms.length, ...savedRooms);
    // 只写声明就加一个新房间：一个房间节点加一种任务，不改 ecs.js 与 floor.js
    P.DEPTS.audit = P.DEPTS.quality;
    D.rooms.splice(D.rooms.findIndex((r) => r.id === 'library'), 0, {
      id: 'audit', label: '审计', roomKind: 'dept', w: 100, agentKind: 'agent', ports: ['in', 'out'],
      props(c, r) { c.fillStyle = '#5a6070'; c.fillRect(r.x + r.w - 30, 190, 20, 12); }
    });
    D.tasks.x_audit_done = { dept: 'audit', label: '审计完成', spot: 'desk', pose: 'sit_happy', bubble: 'say', ms: 800 };
    let threw = null;
    try {
      m = mountFloor(MODEL());
      step(300);
      m.fl.playEvent({ type: 'x_audit_done', work_item_id: 'w1', payload: {} });
      step(200);
      ins = m.fl.inspect();
      const order = ins.world.roomOrder;
      check('声明：新房间按声明的顺序排进去', order.indexOf('audit') === order.indexOf('quality') + 1, order.join());
      const rooms = order.map((id) => ins.world.rooms[id]);
      check('声明：新房间与其他房间不重叠', rooms.every((r, i) => i === 0 || r.x >= rooms[i - 1].x + rooms[i - 1].w));
      check('声明：新房间里有它的小人', Object.values(ins.world.characters).some((c) => c.department === 'audit'));
      check('声明：新任务落在新房间的小人身上', ins.world.characters.audit && ins.world.characters.audit.current && ins.world.characters.audit.current.taskKey === 'x_audit_done');
      m.fl.scene.drawNow();
      drop(m);
    } catch (e) {
      threw = e;
    }
    D.rooms.splice(0, D.rooms.length, ...savedRooms);
    delete D.tasks.x_audit_done;
    delete P.DEPTS.audit;
    check('声明：加一个只有声明的房间不抛出错误', !threw, threw && (threw.stack || threw).toString().slice(0, 300));
  } catch (e) {
    check('检查过程没有抛出错误', false, (e && e.stack) || e);
  }
  return results;
};

(async () => {
  const results = staticChecks();
  const browser = await chromium.launch({ executablePath: EXE });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript((lv) => sessionStorage.setItem('y8.level', JSON.stringify(lv)), 'S5');
  await page.goto(v9Url + '#/sys/machines');
  await page.waitForTimeout(700);
  const inPage = await page.evaluate(DRIVER);
  results.push(...inPage);
  results.push({ name: '页面没有控制台错误', ok: errors.length === 0, detail: errors.slice(0, 3).join(' | ') });

  // 回放：Stage 5 档位下项目概览页点时间轴的刻度与单步没有错误；带回放位置的地址直接打开也能装载
  const replayPage = async (hash, act) => {
    const p = await ctx.newPage();
    const errs = [];
    p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
    p.on('pageerror', (e) => errs.push(String(e)));
    await p.addInitScript((lv) => sessionStorage.setItem('y8.level', JSON.stringify(lv)), 'S5');
    await p.goto(v9Url + hash);
    await p.waitForTimeout(1500);
    const info = await act(p);
    const canvas = await p.locator('.y8-floor-wrap canvas').count();
    const hashAfter = new URL(p.url()).hash;
    await p.close();
    return { errs, canvas, info, hashAfter };
  };
  const seek = await replayPage('#/p/p-todo/overview', async (p) => {
    const ticks = p.locator('.y8-floor-timeline [data-act="replay.seek"]');
    const n = await ticks.count();
    if (n) { await ticks.nth(Math.min(3, n - 1)).click(); await p.waitForTimeout(600); }
    await p.locator('.y8-floor-timeline [data-act="replay.step"]').first().click();
    await p.waitForTimeout(600);
    return n;
  });
  results.push({ name: '回放：Stage 5 档位下点时间轴的刻度与单步没有错误', ok: seek.info > 0 && seek.errs.length === 0 && seek.canvas === 1, detail: seek.info + ' 个刻度；' + seek.errs.slice(0, 2).join(' | ') });
  // 点刻度以后地址里带着回放位置：用这个地址重新打开
  const loadAt = await replayPage(seek.hashAfter.includes('at=') ? seek.hashAfter : '#/p/p-todo/overview?at=40', async () => 0);
  results.push({ name: '回放：带回放位置的地址直接打开概览页能装载楼层画面', ok: loadAt.errs.length === 0 && loadAt.canvas === 1, detail: loadAt.canvas + ' 个画布；' + loadAt.errs.slice(0, 2).join(' | ') });
  await browser.close();
  results.forEach((r) => console.log((r.ok ? 'PASS ' : 'FAIL ') + r.name + (r.ok || !r.detail ? '' : '  ← ' + r.detail)));
  const bad = results.filter((r) => !r.ok);
  console.log('共 ' + results.length + ' 项，失败 ' + bad.length + ' 项');
  console.log(bad.length ? 'RESULT: FAIL' : 'RESULT: PASS');
  process.exit(bad.length ? 1 : 0);
})();
