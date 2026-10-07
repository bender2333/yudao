// 行为检查：用手写的数据驱动项目楼层、楼与机房画面，按确定的时钟检查 v9 的新增行为，全部通过才算通过。
//   多角色    一个部门里有几个角色，同时做着不同的任务；事件按角色找到人，交接由经理做
//   自主行为  空闲的角色自己挑事情做（走动、翻文件柜、互相说话），关闭自主行为以后一件也没有
//   管道流动  流速与光点带着惯性：停止时光点留在管道里，空闲时光点淡出
//   机房      远程动作、部署、回滚的包裹沿项目通往设备的管线走
//   决定卡片  决定单贴在大厅的板上，点开在画面里回答；提出决定时小人送单
//   声明      去掉一个房间、加一个房间，都只改声明，ecs.js 与 floor.js 没有任何具体的部门名
//   自举试点  覆盖层的档位、H1、H4、H5、覆盖层「来源」的着色、run 层只计有可执行检验的条件、两个新场景（pilotChecks）
// 用法：node docs/prototypes/v10/checks/behaviors.js
const fs = require('fs');
const path = require('path');
const { chromium, EXE, v10Url } = require('./env');

// ---------------------------------------------------------------------------
// 声明与引擎的分离：去掉注释以后，ecs.js、floor.js、decision-card.js、source-card.js 里不能出现具体的部门名
function staticChecks() {
  const out = [];
  const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/\s\/\/ .*$/gm, '');
  ['ecs.js', 'floor.js', 'decision-card.js', 'source-card.js'].forEach((f) => {
    const src = strip(fs.readFileSync(path.join(__dirname, '../js/pixel', f), 'utf8'));
    const hits = src.match(/['"`](product|engineering|quality|operations)['"`]/g) || [];
    out.push({ name: f + ' 里没有具体的部门名', ok: hits.length === 0, detail: hits.join(' ') });
  });
  return out;
}

// ---------------------------------------------------------------------------
// 在页面里运行的检查
const DRIVER = async () => {
  const P = window.Y10.pixel;
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

    // ------------------------------------------------------------------ 说话气泡
    // 目录：每个会引起动作的事件都有一句话；话的内容来自事件已经带着的事实
    const say = (ev) => P.say(ev);
    check('说话气泡：每个会引起动作的事件类型都在目录里', Object.keys(P.EVENT_ACTIONS).every((k) => k in P.say.catalog), Object.keys(P.EVENT_ACTIONS).filter((k) => !(k in P.say.catalog)).join());
    check('说话气泡：提交事件取事件说明里「提交」后面的部分',
      say({ type: 'proposal_submitted', department: 'engineering', label: '工程经理代表部门提交交付说明', payload: {} }) === '现在提交交付说明');
    check('说话气泡：提交事件带着提案种类时用提案种类', say({ type: 'proposal_submitted', department: 'quality', payload: { kind: 'qa_review' } }) === '现在提交质检结论');
    check('说话气泡：工具事件的话带着文件名', say({ type: 'tool_started', tool: 'edit_range', department: 'engineering', label: '工程部门按区间编辑 app.js：导出为 CSV', payload: {} }) === '现在编辑 app.js');
    check('说话气泡：登记命令的话带着命令名', say({ type: 'tool_started', tool: 'run_command', department: 'engineering', label: '工程部门走到终端执行登记命令 npm_test', payload: {} }) === '现在执行 npm_test');
    check('说话气泡：交接的两端说不同的话',
      P.say({ type: 'transition', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, { dept: 'engineering' }) === '现在把交付箱送给质检'
      && P.say({ type: 'transition', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, { dept: 'quality' }) === '收到交付箱，来自工程');

    // 部门房间：工程经理提交交付说明时头顶冒泡
    const roomModel = (department, roles) => ({
      department, level: 'S5', status: 'working', crt: {}, roles, pose: null, door: null, hold_card: null, pending_tool: null,
      mailbox: 0, summaries: 0, scrolls: 0, pinned_notes: 0, semantic_cards: 0, machine: null, remote_unknown: false,
      waiting_provider: false, pipes: null, existing_read: false, trial: null, tool_panel: null, self_test: null
    });
    const mountRoom = (department, roles) => {
      const bx = box();
      const rm = P.createRoomScene(bx.canvas, { department });
      rm.setModel(roomModel(department, roles));
      return Object.assign(bx, { rm });
    };
    const dropRoom = (r) => { r.rm.destroy(); r.host.remove(); };
    const saidBy = (r, id) => { const a = r.rm.scene.actors.find((x) => x.id === id); return a && a.data.say ? a.data.say.text : null; };
    const taskOf = (c) => c.current || c.queue[0] || null;
    // 画一帧，收集画出来的文字
    const drawnTexts = (scene) => {
      const orig = P.text;
      const out = [];
      P.text = function (c, str) { out.push(String(str)); return orig.apply(this, arguments); };
      try { scene.drawNow(); } finally { P.text = orig; }
      return out;
    };
    const engRoles = [role('eng-manager', 'manager', '工程经理'), role('eng-architect', 'architect', '工程架构师', 'working'), role('eng-lead', 'lead', '主程')];
    const proR = [role('p-mgr', 'manager', '产品部门经理'), role('p-arch', 'architect', '产品架构师', 'working')];
    const quaR = [role('q-mgr', 'manager', '质检经理'), role('q-test', 'tester', '测试工程师', 'working')];
    let rm = mountRoom('engineering', engRoles);
    step(500);
    rm.rm.playEvent({ type: 'proposal_submitted', department: 'engineering', role: 'eng-manager', work_item_id: 'w1', label: '工程经理代表部门提交交付说明', payload: {} });
    step(1200);
    check('说话气泡：工程经理代表部门提交交付说明，头顶说「现在提交交付说明」', saidBy(rm, 'eng-manager') === '现在提交交付说明', saidBy(rm, 'eng-manager'));
    check('说话气泡：这句话画在画面上', drawnTexts(rm.rm.scene).includes('现在提交交付说明'));
    rm.rm.scene.reduced = true;
    check('说话气泡：减少动画时照样画出来', drawnTexts(rm.rm.scene).includes('现在提交交付说明'));
    rm.rm.scene.reduced = false;
    step(6000);
    check('说话气泡：说完过几秒气泡消失', !drawnTexts(rm.rm.scene).includes('现在提交交付说明'));
    // 分派与交回：两端的角色各说一句
    rm.rm.playEvent({ type: 'x_role_task_assigned', department: 'engineering', role: 'eng-lead', work_item_id: 'w1', payload: { to: 'eng-lead', task: '起草 PLAN' } });
    step(1200);
    check('说话气泡：经理分派任务时说要把任务交给谁', saidBy(rm, 'eng-manager') === '现在把任务交给主程：起草 PLAN', saidBy(rm, 'eng-manager'));
    step(9000);
    check('说话气泡：接任务的角色收到任务时说话', saidBy(rm, 'eng-lead') === '收到任务：起草 PLAN', saidBy(rm, 'eng-lead'));
    rm.rm.playEvent({ type: 'x_role_result_returned', department: 'engineering', role: 'eng-lead', work_item_id: 'w1', payload: { to: 'eng-lead' } });
    step(1500);
    check('说话气泡：交回结果的角色说要把结果交回经理', saidBy(rm, 'eng-lead') === '现在把结果交回经理', saidBy(rm, 'eng-lead'));
    step(9000);
    check('说话气泡：经理收下结果时说话', saidBy(rm, 'eng-manager') === '收到结果', saidBy(rm, 'eng-manager'));
    // 打字思考时头顶已经有思考气泡，不再重复说话
    const beforeThink = saidBy(rm, 'eng-architect');
    rm.rm.playEvent({ type: 'model_requested', department: 'engineering', role: 'eng-architect', work_item_id: 'w1', payload: {} });
    step(1500);
    check('说话气泡：模型请求时只有思考气泡，不重复说话', saidBy(rm, 'eng-architect') === beforeThink, saidBy(rm, 'eng-architect'));
    // 交接：交出的部门说送给谁，收下的部门说收到什么
    rm.rm.playEvent({ type: 'transition', work_item_id: 'w1', payload: { from: 'engineering', to: 'quality', artifact: 'box' } });
    step(100);
    check('说话气泡：交出交付箱的部门说「现在把交付箱送给质检」', saidBy(rm, 'eng-architect') === '现在把交付箱送给质检', saidBy(rm, 'eng-architect'));
    let qr = mountRoom('quality', quaR);
    step(500);
    qr.rm.playEvent({ type: 'transition', work_item_id: 'w1', payload: { from: 'engineering', to: 'quality', artifact: 'box' } });
    step(6000);
    check('说话气泡：收下交付箱的部门说「收到交付箱，来自工程」', saidBy(qr, 'q-test') === '收到交付箱，来自工程', saidBy(qr, 'q-test'));
    qr.rm.playEvent({ type: 'tool_started', tool: 'browser_navigate', department: 'quality', role: 'q-test', work_item_id: 'w1', label: '质检打开页面', payload: {} });
    step(300);
    check('说话气泡：没有专门动作的工具事件也说话', saidBy(qr, 'q-test') === '现在试用网页', saidBy(qr, 'q-test'));
    dropRoom(qr);
    dropRoom(rm);
    // 询问与回答：发问方、回答方各说各的；收到询问的房间走到传信管口取信，而不是写信
    const ask = { type: 'collaboration_requested', department: 'engineering', work_item_id: 'w1', label: '工程询问产品：线路偏好是否改变最短距离', payload: { from: 'engineering', to: 'product', request_id: 'q1' } };
    const reply = { type: 'collaboration_responded', department: 'product', work_item_id: 'w1', label: '产品回答：不改变', payload: { from: 'product', to: 'engineering', request_id: 'q1' } };
    rm = mountRoom('engineering', engRoles);
    const pr = mountRoom('product', proR);
    step(500);
    rm.rm.playEvent(ask); pr.rm.playEvent(ask);
    step(1200);
    check('说话气泡：发问的部门说「现在向产品发出询问：……」', saidBy(rm, 'eng-architect') === '现在向产品发出询问：线路偏好是否改变最短距离', saidBy(rm, 'eng-architect'));
    check('说话气泡：收到询问的部门说「收到工程的询问：……」', saidBy(pr, 'p-arch') === '收到工程的询问：线路偏好是否改变最短距离', saidBy(pr, 'p-arch'));
    check('说话气泡：收到询问的部门的小人走到传信管口取信（不是写信）', pr.rm.scene.actors.find((x) => x.id === 'p-arch').data.doing === 'answer_letter', pr.rm.scene.actors.find((x) => x.id === 'p-arch').data.doing);
    step(6000);
    rm.rm.playEvent(reply); pr.rm.playEvent(reply);
    step(1500);
    check('说话气泡：回答的部门说「现在回答工程的询问」', saidBy(pr, 'p-arch') === '现在回答工程的询问', saidBy(pr, 'p-arch'));
    check('说话气泡：收到回答的部门说「收到产品的回答：……」', (saidBy(rm, 'eng-architect') || '').indexOf('收到产品的回答：') === 0, saidBy(rm, 'eng-architect'));
    dropRoom(pr);
    dropRoom(rm);

    // 项目楼层：同样的话
    m = mountFloor(MODEL());
    step(500);
    m.fl.playEvent({ type: 'proposal_submitted', department: 'engineering', role: 'e-mgr', work_item_id: 'w1', label: '工程经理代表部门提交交付说明', payload: {} });
    step(100);
    let mgr = m.fl.inspect().world.characters['e-mgr'];
    check('说话气泡：楼层里经理提交交付说明，头顶也说「现在提交交付说明」', mgr.bubble && mgr.bubble.text === '现在提交交付说明' && mgr.bubble.kind === 'say', JSON.stringify(mgr.bubble));
    check('说话气泡：楼层里这句话画在画面上', drawnTexts(m.fl.scene).includes('现在提交交付说明'));
    step(6000);
    check('说话气泡：楼层里说完过几秒气泡消失', !drawnTexts(m.fl.scene).includes('现在提交交付说明'));
    m.fl.playEvent({ type: 'transition', work_item_id: 'w1', payload: { from: 'engineering', to: 'quality', artifact: 'box' } });
    step(100);
    mgr = taskOf(m.fl.inspect().world.characters['e-mgr']);
    check('说话气泡：楼层里交出交付箱的经理说「现在把交付箱送给质检」', mgr && mgr.label === '现在把交付箱送给质检', mgr && mgr.label);
    let recv = null;
    for (let i = 0; i < 80 && !recv; i++) {
      step(100);
      const qm = m.fl.inspect().world.characters['q-mgr'];
      if (qm.current && qm.current.taskKey === 'package_handoff_in') recv = qm.current.label;
    }
    check('说话气泡：楼层里收下交付箱的经理说「收到交付箱，来自工程」', recv === '收到交付箱，来自工程', recv);
    step(3000);
    m.fl.playEvent(ask);
    step(100);
    const asking = taskOf(m.fl.inspect().world.characters['e-mgr']);
    check('说话气泡：楼层里发问的经理说「现在向产品发出询问：……」', asking && asking.label === '现在向产品发出询问：线路偏好是否改变最短距离', asking && asking.label);
    recv = null;
    for (let i = 0; i < 80 && !recv; i++) {
      step(100);
      const pm = m.fl.inspect().world.characters['p-mgr'];
      if (pm.current && /^letter_arrive_/.test(pm.current.taskKey)) recv = pm.current.label;
    }
    check('说话气泡：楼层里收到询问的经理走到管口说「收到工程的询问：……」', recv === '收到工程的询问：线路偏好是否改变最短距离', recv);
    step(4000);
    m.fl.playEvent({ type: 'x_role_task_assigned', department: 'engineering', role: 'e-lead', work_item_id: 'w1', payload: { to: 'e-lead', task: '实现' } });
    step(100);
    const giving = taskOf(m.fl.inspect().world.characters['e-mgr']);
    check('说话气泡：楼层里经理分派任务时说要把任务交给谁', giving && giving.label === '现在把任务交给主程：实现', giving && giving.label);
    recv = null;
    for (let i = 0; i < 80 && !recv; i++) {
      step(100);
      const lead = m.fl.inspect().world.characters['e-lead'];
      if (lead.current && lead.current.taskKey === 'role_task_received') recv = lead.current.label;
    }
    check('说话气泡：楼层里接任务的角色说「收到任务：实现」', recv === '收到任务：实现', recv);
    drop(m);
    // 减少动画：小人不走动，交接的话仍然在原处说出来
    m = mountFloor(MODEL());
    step(500);
    m.fl.scene.reduced = true;
    m.fl.playEvent({ type: 'transition', work_item_id: 'w1', payload: { from: 'engineering', to: 'quality', artifact: 'box' } });
    step(200);
    const reducedTexts = drawnTexts(m.fl.scene);
    check('说话气泡：减少动画时交接的两端仍然说话', reducedTexts.includes('现在把交付箱送给质检') && reducedTexts.includes('收到交付箱，来自工程'), reducedTexts.filter((s) => /交付箱/.test(s)).join('|'));
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

// ---------------------------------------------------------------------------
// 自举试点的行为检查（design.md 第 9 节）：覆盖层的档位、H1（覆盖层的取值等于查询的结果）、
// H4（事实元素都有来源，来源等于来源表按「事件加字段」给出的结果）、H5（开环的条件带开环标记）、覆盖层「来源」的着色、两个新场景
async function pilotChecks(ctx) {
  const out = [];
  const push = (name, ok, detail) => out.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
  const open = async (level, hash) => {
    const p = await ctx.newPage();
    const errs = [];
    p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
    p.on('pageerror', (e) => errs.push(String(e)));
    await p.addInitScript((lv) => sessionStorage.setItem('y10.level', JSON.stringify(lv)), level);
    await p.goto(v10Url + hash);
    await p.waitForTimeout(1200);
    return { p, errs };
  };
  // 在页面里用到的小工具：当前楼层、按事实元素的位置点击画布
  const helpers = () => {
    window.__fl = () => window.Y10.scenes.activeFloor().floor;
    window.__click = (f) => {
      const cv = window.__fl().scene.canvas;
      const b = cv.getBoundingClientRect();
      cv.dispatchEvent(new MouseEvent('click', { clientX: b.left + ((f.rect.x + f.rect.w / 2) * b.width) / 640, clientY: b.top + ((f.rect.y + f.rect.h / 2) * b.height) / 320, bubbles: true }));
    };
    window.__texts = () => {
      const P = window.Y10.pixel;
      const orig = P.text;
      const seen = [];
      P.text = function (c, str) { seen.push(String(str)); return orig.apply(this, arguments); };
      try { window.__fl().scene.drawNow(); } finally { P.text = orig; }
      return seen;
    };
    window.__wait = (ms) => new Promise((r) => setTimeout(r, ms));
  };

  // 覆盖层与查询的档位；事件对象的 source
  {
    const { p, errs } = await open('3.2D', '#/sys/machines');
    const capsAt = (lv) => p.evaluate((l) => { window.Y10.level.set(l); const c = window.Y10.cap.get(); return { ov: c.overlays.map((o) => o.id), q: c.queries.map((x) => x.name) }; }, lv);
    const d = await capsAt('3.2D');
    const pl = await capsAt('pilot');
    const NEW = ['loops', 'sources', 'coverage'];
    push('覆盖层：3.2D 档没有「循环」「来源」「检验」', NEW.every((id) => !d.ov.includes(id)), d.ov.join());
    push('覆盖层：自举试点起列出「循环」「来源」「检验」', NEW.every((id) => pl.ov.includes(id)), pl.ov.join());
    push('查询：acceptance.coverage 与 run.loops 在自举试点出现，3.2D 档没有', !d.q.includes('acceptance.coverage') && !d.q.includes('run.loops') && pl.q.includes('acceptance.coverage') && pl.q.includes('run.loops'));
    const src = await p.evaluate(() => {
      const Y = window.Y10;
      Y.level.set('3.2D');
      const a = Y.api.query('event.detail', { position: 5 }).data.event;
      Y.level.set('pilot');
      const b = Y.api.query('event.detail', { position: 5 }).data.event;
      const kinds = Object.keys(Y.registry.SOURCE_KINDS);
      return { a: 'source' in a, b: b.source, every: Y.api.query('home.away_report', { range: '7d' }).data.facts.every((f) => kinds.includes(f.event.source)) };
    });
    push('事件对象：3.2D 档没有 source，自举试点起每条事件都带五种来源之一', !src.a && src.b && src.every, JSON.stringify(src));
    push('档位与来源的检查没有控制台错误', errs.length === 0, errs.slice(0, 2).join(' | '));
    await p.close();
  }

  // H1：覆盖层「循环」「检验」上的取值等于对应查询的结果；H5：逐条清单里开环的条件带开环标记
  {
    const { p, errs } = await open('pilot', '#/p/p-todo/overview?w=w-todo-csv');
    await p.evaluate(helpers);
    await p.click('[data-overlay="loops"]');
    await p.waitForTimeout(500);
    const loops = await p.evaluate(() => {
      const ins = window.__fl().inspect();
      const q = window.Y10.api.query('run.loops', { project_id: 'p-todo' }).data;
      const byId = {};
      [q.project].concat(...q.items.map((i) => i.instances)).forEach((x) => { byId[x.id] = x; });
      const labels = ins.overlay.labels.filter((l) => l.id);
      const bad = labels.filter((l) => !byId[l.id] || byId[l.id].state !== l.state || l.text.indexOf(window.Y10.pixel.LOOP_STATES[l.state].label) < 0);
      const missing = ins.facts.filter((f) => f.kind === 'missing');
      return { n: labels.length, layers: Array.from(new Set(labels.map((l) => l.layer))), bad, missing: missing.length, missingText: missing.every((f) => f.missing && !f.position) };
    });
    push('H1 覆盖层「循环」：信息条、房间、角色头顶的状态等于 run.loops 的结果', loops.n >= 3 && !loops.bad.length && ['run', 'activation', 'step'].every((l) => loops.layers.includes(l)), JSON.stringify(loops));
    push('覆盖层「循环」：「不判定」的标签点开写缺少的事实', loops.missing > 0 && loops.missingText);
    await p.click('[data-overlay="coverage"]');
    await p.waitForTimeout(500);
    const cov = await p.evaluate(async () => {
      const fl = window.__fl();
      const ins = fl.inspect();
      const q = window.Y10.api.query('acceptance.coverage', { project_id: 'p-todo' }).data.items;
      const l = ins.overlay.labels.find((x) => x.kind === 'coverage');
      const it = l && q.find((x) => x.work_item_id === l.work_item_id);
      const rel = ins.overlay.labels.find((x) => x.kind === 'release');
      const relIt = rel && q.find((x) => x.work_item_id === rel.work_item_id);
      fl.openFact('coverage');
      await window.__wait(300);
      const s = fl.inspect().sourceCard.state();
      const openRows = s && s.rows ? s.rows.filter((r) => r.open).map((r) => r.label.split(' ')[0]) : null;
      const drawn = window.__texts().filter((t) => t === '开环').length;
      return {
        same: Boolean(it) && ['covered', 'total', 'model_read', 'open_count'].every((k) => it[k] === l[k]) && l.text.indexOf(window.Y10.coverageText(it)) >= 0 &&
          s && s.title.indexOf(window.Y10.coverageText(it)) >= 0,
        rel: Boolean(relIt) && relIt.release.ratio.covered === rel.covered && relIt.release.ratio.total === rel.total,
        list: s && s.mode, openRows, openIds: it ? it.criteria.filter((c) => c.open).map((c) => c.id) : null, drawn, label: l
      };
    });
    push('H1 覆盖层「检验」：质检房间与逐条清单的标题写「覆盖 · 开环（其中模型阅读）」，取值等于 acceptance.coverage', cov.same, JSON.stringify(cov.label));
    push('H1 覆盖层「检验」：放行盖章旁的覆盖比例等于这次放行的结果', cov.rel);
    push('H5 覆盖层「检验」：逐条清单里开环的条件都带「开环」标记', cov.list === 'list' && cov.openRows && cov.openRows.join() === cov.openIds.join() && cov.openIds.length > 0 && cov.drawn >= cov.openIds.length, JSON.stringify(cov));
    push('覆盖层「循环」「检验」没有控制台错误', errs.length === 0, errs.slice(0, 2).join(' | '));
    await p.close();
  }

  // H5：资料页的逐条结论表里，开环的条件带「开环」标记，且与 acceptance.coverage 一致
  for (const wid of ['w-todo-base', 'w-todo-csv']) {
    const { p, errs } = await open('pilot', '#/p/p-todo/materials?w=' + wid);
    const r = await p.evaluate((w) => {
      const rows = Array.from(document.querySelectorAll('#mt-qa tr[data-criterion]'));
      const openRows = rows.filter((tr) => tr.dataset.open === '1');
      const tagged = openRows.every((tr) => tr.querySelector('.y10-tag.is-open') && tr.querySelector('.y10-tag.is-open').textContent === '开环');
      const untagged = rows.filter((tr) => tr.dataset.open !== '1').every((tr) => !tr.querySelector('.y10-tag.is-open'));
      const cov = window.Y10.api.query('acceptance.coverage', { project_id: 'p-todo', work_item_id: w }).data.items[0];
      const ids = new Set(openRows.map((tr) => tr.dataset.criterion));
      return { rows: rows.length, open: openRows.length, tagged, untagged, covOpen: cov.criteria.filter((c) => c.open).map((c) => c.id), inTable: cov.criteria.filter((c) => c.open).every((c) => ids.has(c.id)) };
    }, wid);
    push('H5 资料页「' + wid + '」：逐条结论表里开环的条件带「开环」标记，与 acceptance.coverage 一致', r.rows > 0 && r.open > 0 && r.tagged && r.untagged && r.inTable && errs.length === 0, JSON.stringify(r));
    await p.close();
  }

  // H4：每个项目的楼层上，事实元素都有来源事件，来源等于来源表按「事件加字段」给出的结果；
  // 信息条上的已用时间是事件里的测量值（主机测量），轮次按事件种类；点开的来源卡片写同一条事件与同一种来源
  for (const pid of ['p-todo', 'p-metro', 'p-sensor', 'p-agents']) {
    for (const level of ['pilot', 'S5']) {
      const { p, errs } = await open(level, '#/p/' + pid + '/overview');
      await p.evaluate(helpers);
      const r = await p.evaluate(async () => {
        const Y = window.Y10;
        const fl = window.__fl();
        fl.scene.drawNow();
        const ins = fl.inspect();
        const evOf = (f) => Y.api.query('event.detail', { position: f.position }).data.event;
        const bad = ins.facts.filter((f) => !f.position || !f.source || Y.registry.sourceOf(evOf(f), f.field) !== f.source);
        const time = ins.facts.filter((f) => f.kind === 'time');
        const round = ins.facts.filter((f) => f.kind === 'round');
        const noRef = ins.model.items.filter((it) => !it.refs || ['round', 'time', 'sign', 'department', 'parcel'].some((k) => !it.refs[k])).map((it) => it.id);
        const noBox = (ins.model.shelves.boxes || []).filter((b) => !b.ref).length;
        const target = ins.facts.find((f) => f.kind === 'time') || ins.facts[0];
        window.__click(target);
        await window.__wait(100);
        const s = fl.inspect().sourceCard.state();
        return {
          n: ins.facts.length, kinds: Array.from(new Set(ins.facts.map((f) => f.kind))), bad: bad.map((f) => f.kind + '@' + f.position + ':' + f.source), noRef, noBox,
          time: time.every((f) => f.source === 'host_measurement') && time.length > 0,
          round: round.every((f) => f.source === evOf(f).source),
          card: s && s.event ? { pos: s.event.position, source: s.fact.source } : null, want: { pos: target.position, source: target.source }
        };
      });
      push('H4 ' + pid + '（' + level + '）：每个事实元素都有来源事件，来源等于来源表按「事件加字段」给出的结果', r.n > 0 && !r.bad.length, JSON.stringify(r));
      push('H4 ' + pid + '（' + level + '）：信息条上的已用时间是主机测量，轮次按事件种类', r.time && r.round, JSON.stringify({ time: r.time, round: r.round }));
      push('H4 ' + pid + '（' + level + '）：牌子、包裹、箱子与信息条都有来源事件，没有因为缺少来源而不画的元素', !r.noRef.length && !r.noBox, JSON.stringify({ noRef: r.noRef, noBox: r.noBox }));
      push('H4 ' + pid + '（' + level + '）：点事实元素打开的来源卡片写给出它的事件与这个元素的来源', r.card && r.card.pos === r.want.pos && r.card.source === r.want.source && errs.length === 0, JSON.stringify(r.card) + ' ' + errs.slice(0, 2).join(' | '));
      await p.close();
    }
  }

  // 决策模型给出的事实（Stage 5）：带参照材料的判定点的结论来自决策模型，来源卡片写概率
  {
    const { p, errs } = await open('S5', '#/p/p-todo/overview?w=w-todo-base');
    await p.evaluate(helpers);
    await p.click('[data-overlay="coverage"]');
    await p.waitForTimeout(500);
    const r = await p.evaluate(async () => {
      const fl = window.__fl();
      const it = window.Y10.api.query('acceptance.coverage', { project_id: 'p-todo', work_item_id: 'w-todo-base' }).data.items[0];
      const ac8 = it.criteria.find((c) => c.id === 'AC-8');
      const ev = window.Y10.api.query('event.detail', { position: ac8.position }).data.event;
      fl.openFact('coverage');
      await window.__wait(300);
      const row = fl.inspect().sourceCard.state().rows.find((x) => x.label.indexOf('AC-8') === 0);
      fl.inspect().sourceCard.open(row.fact);
      const texts = window.__texts();
      return { source: ac8.source, probability: ev.payload.probability, card: fl.inspect().sourceCard.state().fact.source, drawn: texts.some((t) => t.indexOf('概率 0.86') === 0) };
    });
    push('S5：判定点的结论来自决策模型，来源卡片写概率', r.source === 'decision_model' && r.probability === 0.86 && r.card === 'decision_model' && r.drawn && errs.length === 0, JSON.stringify(r));
    await p.close();
  }

  // 覆盖层「来源」的着色：画面其余部分调暗，事实元素本身不调暗，四周按自己的来源描边；图例的个数等于画面上各种来源的元素数
  {
    const { p, errs } = await open('pilot', '#/p/p-todo/overview');
    await p.evaluate(helpers);
    // 在画面上取一个像素（逻辑坐标），返回 RGB
    const pixelsAt = (pts) => p.evaluate((list) => {
      const fl = window.__fl();
      fl.scene.drawNow();
      const cv = fl.scene.canvas;
      const k = cv.width / 640;
      const c = cv.getContext('2d');
      return list.map(([x, y]) => Array.from(c.getImageData(Math.floor(x * k), Math.floor(y * k), 1, 1).data.slice(0, 3)));
    }, pts);
    const facts = await p.evaluate(() => { window.__fl().scene.drawNow(); return window.__fl().inspect().facts.map((f) => ({ kind: f.kind, rect: f.rect, source: f.source })); });
    const inside = facts.find((f) => f.kind === 'box') || facts[0];
    const spotIn = [inside.rect.x + inside.rect.w / 2, inside.rect.y + inside.rect.h / 2];
    const spotOut = [320, 250];    // 走廊的地面，不是事实元素
    const before = await pixelsAt([spotIn, spotOut]);
    await p.click('[data-overlay="sources"]');
    await p.waitForTimeout(500);
    const after = await pixelsAt([spotIn, spotOut, [inside.rect.x - 1.5, inside.rect.y + inside.rect.h / 2]]);
    const r = await p.evaluate((src) => {
      const P = window.Y10.pixel;
      const ins = window.__fl().inspect();
      const label = ins.overlay.labels.find((l) => l.kind === 'sources');
      const tally = {};
      ins.facts.filter((f) => f.source).forEach((f) => { tally[f.source] = (tally[f.source] || 0) + 1; });
      const hex = P.SOURCE_STYLE[src].line;
      return { counts: label && label.counts, tally, line: [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) };
    }, inside.source);
    const sum = (c) => c[0] + c[1] + c[2];
    push('覆盖层「来源」：画面其余部分调暗，事实元素本身不调暗', sum(after[1]) < sum(before[1]) * 0.6 && sum(after[0]) === sum(before[0]), JSON.stringify({ before, after }));
    push('覆盖层「来源」：事实元素按来源描边', after[2].every((v, i) => Math.abs(v - r.line[i]) <= 8), JSON.stringify({ edge: after[2], line: r.line, source: inside.source }));
    push('覆盖层「来源」：图例写的个数等于画面上各种来源的元素数', JSON.stringify(r.counts) === JSON.stringify(r.tally), JSON.stringify(r));
    push('覆盖层「来源」没有控制台错误', errs.length === 0, errs.slice(0, 2).join(' | '));
    await p.close();
  }

  // 两个新场景播完以后的画面与数据
  {
    const { p, errs } = await open('pilot', '#/home');
    const r = await p.evaluate(async () => {
      const Y = window.Y10;
      const wait = (ms) => new Promise((res) => setTimeout(res, ms));
      const ids = Y.api.query('home.away_report', {}).data.summary.map((s) => s.id);
      const play = async (id, probe) => {
        Y.scenario.select(id);
        await wait(600);
        const seen = {};
        const total = Y.scenario.current().steps.length;
        while (Y.scenario.state().step < total) {
          Y.scenario.step();
          await wait(450);
          if (probe) probe(Y.scenario.state().step, seen);
        }
        return seen;
      };
      const s20 = await play('sc-todo-loops', (n, seen) => {
        const f = Y.scenes.activeFloor();
        if (n === 1) seen.overlay = f && f.floor.inspect().overlay.id;
        if (n === 6) seen.runLabel = f && f.floor.inspect().overlay.labels.find((l) => l.layer === 'run');
      });
      const csv = Y.api.query('run.loops', { project_id: 'p-todo' }).data.items.find((i) => i.work_item_id === 'w-todo-csv').instances.find((x) => x.layer === 'run');
      const change = Y.api.query('home.away_report', {}).data.summary.find((s) => s.id === 'loop_changes').changes.find((c) => c.work_item_id === 'w-todo-csv');
      const openRow = document.querySelector('#obs-loop .y10-loop-row.is-open');
      const bars = document.querySelectorAll('#obs-loop .y10-loop-detail .y10-loop-bar').length;
      const kinds = Array.from(document.querySelectorAll('#obs-loop .y10-loop-detail .y10-loop-bar .y10-source-kind')).map((el) => el.textContent);
      const opens = Array.from(document.querySelectorAll('#obs-loop .y10-loop-detail .y10-loop-open')).map((el) => el.textContent);
      const s21 = await play('sc-todo-sources', (n, seen) => {
        const f = Y.scenes.activeFloor();
        const st = f && f.floor.inspect().sourceCard.state();
        if (n === 1) seen.overlay = f && f.floor.inspect().overlay.id;
        if (n === 2) seen.parcel = st && st.fact && st.fact.kind;
        if (n === 3) seen.time = st && st.fact && st.fact.kind + ':' + st.fact.source;
        if (n === 5) seen.list = st && st.mode;
        if (n === 6) seen.stamp = st && st.fact && st.fact.kind;
        if (n === 7) seen.materials = document.querySelectorAll('#mt-qa tr[data-open="1"]').length;
      });
      await wait(400);
      const item = document.querySelector('.y10-report-item.is-open');
      return {
        ids, s20, state: csv.state, values: csv.measure.series.map((x) => x.value), sources: csv.measure.series.map((x) => x.source), opensData: csv.measure.series.map((x) => x.open),
        basis: csv.basis, change, open: openRow && openRow.dataset.id, bars, kinds, opens, s21, report: item ? item.textContent : null
      };
    });
    push('离开期间的报告：自举试点起有「收敛状态的变化」与「带开环条件的放行」', r.ids.includes('loop_changes') && r.ids.includes('open_releases'), r.ids.join());
    push('场景「循环与收敛」：打开覆盖层「循环」，第 4 轮质检结论到达以后信息条写 run 停滞', r.s20.overlay === 'loops' && r.s20.runLabel && r.s20.runLabel.state === 'stalled', JSON.stringify(r.s20));
    push('场景「循环与收敛」：「导入 CSV」的未满足数 3 → 2 → 2 → 2，run 停滞', r.state === 'stalled' && r.values.join() === '3,2,2,2', r.state + ' ' + r.values.join());
    push('场景「循环与收敛」：报告里有「导入 CSV · run：收敛中 → 停滞」', r.change && r.change.from === 'converging' && r.change.to === 'stalled', JSON.stringify(r.change));
    push('场景「循环与收敛」：观测页的「循环」区块展开 run 一行，显示 4 轮数值', r.open === 'run:r-todo-csv' && r.bars === 4, r.open + ' ' + r.bars);
    push('run 层只计有可执行检验的条件：判定依据写明，每一轮另写开环数（开环 1）',
      r.basis.indexOf('只计有可执行检验的条件') === 0 && r.opensData.join() === '1,1,1,1' && r.opens.join() === '开环 1,开环 1,开环 1,开环 1', JSON.stringify({ basis: r.basis, opens: r.opens }));
    push('run 层每一轮数值的来源是主机测量（观测页的来源标签也写「主机测量」）',
      r.sources.every((s) => s === 'host_measurement') && r.kinds.length === 4 && r.kinds.every((k) => k === '主机测量'), JSON.stringify({ sources: r.sources, kinds: r.kinds }));
    push('场景「来源与检验」：着色、包裹与已用时间的来源卡片、逐条清单、放行盖章、资料页的开环标记依次出现',
      r.s21.overlay === 'sources' && r.s21.parcel === 'parcel' && r.s21.time === 'time:host_measurement' && r.s21.list === 'list' && r.s21.stamp === 'stamp' && r.s21.materials > 0, JSON.stringify(r.s21));
    push('场景「来源与检验」：首页展开「带开环条件的放行」，写「覆盖 7/8 · 开环 1（其中模型阅读 1）」并列出开环的条件',
      r.report && r.report.indexOf('带开环条件的放行') >= 0 && r.report.indexOf('覆盖 7/8 · 开环 1（其中模型阅读 1）') >= 0 && r.report.indexOf('AC-8') >= 0, r.report);
    push('两个新场景播放没有控制台错误', errs.length === 0, errs.slice(0, 2).join(' | '));
    await p.close();
  }
  return out;
}

(async () => {
  const results = staticChecks();
  const browser = await chromium.launch({ executablePath: EXE });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript((lv) => sessionStorage.setItem('y10.level', JSON.stringify(lv)), 'S5');
  await page.goto(v10Url + '#/sys/machines');
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
    await p.addInitScript((lv) => sessionStorage.setItem('y10.level', JSON.stringify(lv)), 'S5');
    await p.goto(v10Url + hash);
    await p.waitForTimeout(1500);
    const info = await act(p);
    const canvas = await p.locator('.y10-floor-wrap canvas').count();
    const hashAfter = new URL(p.url()).hash;
    await p.close();
    return { errs, canvas, info, hashAfter };
  };
  const seek = await replayPage('#/p/p-todo/overview', async (p) => {
    const ticks = p.locator('.y10-floor-timeline [data-act="replay.seek"]');
    const n = await ticks.count();
    if (n) { await ticks.nth(Math.min(3, n - 1)).click(); await p.waitForTimeout(600); }
    await p.locator('.y10-floor-timeline [data-act="replay.step"]').first().click();
    await p.waitForTimeout(600);
    return n;
  });
  results.push({ name: '回放：Stage 5 档位下点时间轴的刻度与单步没有错误', ok: seek.info > 0 && seek.errs.length === 0 && seek.canvas === 1, detail: seek.info + ' 个刻度；' + seek.errs.slice(0, 2).join(' | ') });
  // 点刻度以后地址里带着回放位置：用这个地址重新打开
  const loadAt = await replayPage(seek.hashAfter.includes('at=') ? seek.hashAfter : '#/p/p-todo/overview?at=40', async () => 0);
  results.push({ name: '回放：带回放位置的地址直接打开概览页能装载楼层画面', ok: loadAt.errs.length === 0 && loadAt.canvas === 1, detail: loadAt.canvas + ' 个画布；' + loadAt.errs.slice(0, 2).join(' | ') });
  results.push(...await pilotChecks(ctx));
  await browser.close();
  results.forEach((r) => console.log((r.ok ? 'PASS ' : 'FAIL ') + r.name + (r.ok || !r.detail ? '' : '  ← ' + r.detail)));
  const bad = results.filter((r) => !r.ok);
  console.log('共 ' + results.length + ' 项，失败 ' + bad.length + ' 项');
  console.log(bad.length ? 'RESULT: FAIL' : 'RESULT: PASS');
  process.exit(bad.length ? 1 : 0);
})();
