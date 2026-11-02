// 项目楼层的声明（设计说明第 3 节）：房间、管道、任务目录、待机活动、每个房间自己的陈设与持续状态。
// 加一个部门只需要在这里写它的房间节点与任务种类，ecs.js 与 floor.js 里没有任何具体的部门名（checks/declarative.js 检查这一点）。
(function () {
  'use strict';
  const Y13 = window.Y13;
  const P = Y13.pixel;
  if (!P || !P.ecs) throw new Error('floor-decl.js 需要先加载 js/pixel/ecs.js');
  const PAL = P.PAL;
  const R = P.R, RB = P.RB, paint = P.paint;
  const G = P.ecs.GEO;

  // ---------------------------------------------------------------------------
  // 房间：roomKind 决定画法（hall 大厅、shelf 成果库、dept 部门房间），w 是宽度，when 是出现的条件名（取自 floorModel 的同名字段），
  // agentKind 是没有角色设置时那个唯一角色的种类，ports 是墙上画哪几个管道口（in、out 交接管道，tubeIn、tubeOut 传信管），
  // spots 把任务的位置对到房间里已有的陈设上，rest 是这个房间的持续状态，props 画陈设，verifies 标出出具放行结论的房间

  const DEPT_PORTS = ['in', 'out', 'tubeIn', 'tubeOut'];

  const ROOMS = [
    { id: 'hall', label: '大厅', roomKind: 'hall', w: 100, pipeOutX: 22 },
    {
      id: 'product', label: '产品', roomKind: 'dept', w: 110, agentKind: 'agent', ports: DEPT_PORTS,
      spots: { cabinet: (r) => r.x + r.w - 25, terminal: (r) => r.x + r.w - 25 },
      props(c, r) {
        RB(c, r.x + r.w - 34, G.FLOOR_LINE + 8, 20, 30, PAL.wood3);
        for (let i = 0; i < 3; i++) R(c, r.x + r.w - 31, G.FLOOR_LINE + 12 + i * 9, 14, 5, PAL.paper2);
      }
    },
    {
      id: 'engineering', label: '工程', roomKind: 'dept', w: 110, agentKind: 'agent', ports: DEPT_PORTS,
      spots: { cabinet: (r) => r.x + r.w - 25, terminal: (r) => r.x + r.w - 25 },
      props(c, r) {
        RB(c, r.x + r.w - 36, G.FLOOR_LINE + 22, 22, 16, PAL.metal3);
        P.drawBitmap(c, 'box_sealed', r.x + r.w - 31, G.FLOOR_LINE + 12);
      }
    },
    {
      // verifies：这个房间出具放行结论，覆盖层「检验」的数与放行的盖章画在这里
      id: 'quality', label: '质检', roomKind: 'dept', w: 110, agentKind: 'agent', ports: DEPT_PORTS, verifies: true,
      spots: { cabinet: (r) => r.x + r.w - 25, terminal: (r) => r.x + r.w - 25 },
      props(c, r) {
        RB(c, r.x + r.w - 36, G.FLOOR_LINE + 24, 22, 12, PAL.white2);
        P.drawBitmap(c, 'magnifier', r.x + r.w - 29, G.FLOOR_LINE + 14);
      }
    },
    { id: 'library', label: '成果库', roomKind: 'shelf', w: (fl) => (fl.ops ? 82 : 136), ports: ['in'] },
    {
      id: 'operations', label: '运维', roomKind: 'dept', w: 88, when: 'ops', agentKind: 'ops', ports: ['in', 'out'],
      spots: { cabinet: (r) => r.x + 17 },
      // 有运维数据的项目里这个房间始终亮着；监控屏出现故障时整个房间泛红光
      lit: (ctx) => Boolean(ctx.model.ops),
      tint(c, r, t, ctx) {
        if (!((ctx.model.ops && ctx.model.ops.fault) || ctx.sig('monitor'))) return;
        const k = ctx.reduced ? 0.12 : 0.08 + 0.07 * Math.max(0, Math.sin(t / 160));
        c.fillStyle = 'rgba(255,50,50,' + k.toFixed(3) + ')';
        c.fillRect(r.x, G.TOP, r.w, G.ROOM_B - G.TOP);
      },
      // 有故障时盯着监控屏，否则在工位上工作（快照里没有运维数据时是待机）
      rest(ctx) {
        const ops = ctx.model.ops;
        if (ops && ops.fault) return { spot: 'monitor', pose: 'watch_r', icon: 'exclaim', facing: 1 };
        return { spot: 'desk', pose: ops ? 'type' : 'tea' };
      },
      props(c, r, t, ctx) {
        const ops = ctx.model.ops;
        const fault = (ops && ops.fault) || ctx.sig('monitor');
        // 监控屏
        const mx = r.x + r.w - 44, my = G.TOP + 16;
        RB(c, mx - 2, my - 2, 40, 26, PAL.grey5);
        paint.screen(c, mx, my, 36, 22, fault ? 'error' : 'ok', t, { seed: 3 });
        P.text(c, ops && ops.version ? '运行 ' + ops.version : '监控屏', mx + 18, my + 30, { size: 5.5, weight: 700, align: 'center', color: PAL.white });
        // 备份柜与小推车
        RB(c, r.x + 8, G.FLOOR_LINE + 4, 18, 34, PAL.metal3);
        for (let i = 0; i < 3; i++) RB(c, r.x + 10, G.FLOOR_LINE + 7 + i * 10, 14, 7, i === 0 ? PAL.green2 : PAL.metal2);
        paint.cart(c, r.x + 30, G.ROOM_B - 6, {});
        if (ops && ops.auto_repair_stopped) {
          P.sign(c, r.x + r.w / 2, G.ROOM_B + 26, '停止自动修复', { size: 6, bg: PAL.red2, fg: PAL.white, stripe: PAL.red3, maxW: r.w + 10, nail: G.ROOM_B + 3 });
        }
      }
    }
  ];

  // 管道：交接管道 handoff（粗的玻璃管）、传信管 tube（细的蓝色管）、回流管道 return；optional 的管道在端点不存在时跳过；
  // valve 标出 Stage 6 判定阀门的位置（管道中间画一个空卡座）
  const LINKS = [
    { from: 'hall', to: 'product', kind: 'handoff' },
    { from: 'product', to: 'engineering', kind: 'handoff', valve: true },
    { from: 'engineering', to: 'quality', kind: 'handoff', valve: true },
    { from: 'quality', to: 'library', kind: 'handoff', valve: true },
    { from: 'quality', to: 'product', kind: 'return' },
    { from: 'product', to: 'engineering', kind: 'tube' },
    { from: 'engineering', to: 'quality', kind: 'tube' },
    { from: 'product', to: 'quality', kind: 'tube' },
    { from: 'library', to: 'operations', kind: 'handoff', optional: true },
    { from: 'operations', to: 'machine_room', kind: 'handoff', optional: true },
    { from: 'operations', to: 'hall', kind: 'return', via: 'under', optional: true }
  ];

  // ---------------------------------------------------------------------------
  // 状态对应的持续姿势（v8 design.md 第 8.3 节的状态行）：返回 { spot, pose, icon, iconText, facing, hold, away }。
  // ctx：{ model（楼层的状态）, order（房间的排布顺序）, waitingDept(d) }

  function deptRest(ctx, d, it) {
    const seat = (pose, icon, iconText) => ({ spot: 'desk', pose, icon: icon || null, iconText: iconText || null });
    if (!it) return seat('tea');
    // 事项停在别的房间，这个部门同时在工作中或回答询问（ADR-0036）：坐在桌前打字
    if (it.department !== d && it.departments && it.departments[d]) return seat('type');
    const openFrom = (ctx.model.open_requests || []).find((q) => q.from === d && q.work_item_id === it.id);
    switch (it.status) {
      case 'working': return seat('type');
      case 'asking': {
        const target = openFrom ? openFrom.to : null;
        const right = target && ctx.order.indexOf(target) > ctx.order.indexOf(d);
        return { spot: right ? 'port_out' : 'port_in', pose: 'wait', facing: right ? 1 : -1 };
      }
      case 'waiting_model': {
        const w = ctx.waitingDept(d);
        return seat('sit_wait', 'hourglass', w && w.retry_text ? w.retry_text : '等待');
      }
      case 'paused': return seat('sit_relax', 'zzz');
      case 'failed': return seat('slump');
      case 'done': return { spot: 'stand', pose: 'cheer' };
      case 'cancelled': return { spot: 'stand', pose: 'idle' };
      case 'waiting_resume': return seat('sit_wait', 'text', '待恢复');
      case 'waiting_user': return seat('sit_wait', 'text', '待你决定');
      case 'upgrade_stopped': return { spot: 'stand', pose: 'idle' };
      default: return seat('sit');
    }
  }

  // 部门里每个角色的持续状态（Stage 5，跟 room.js 部门房间的规则一致）：部门整体的特殊状态（等待、待核实……）落在中心角色身上，
  // 暂停、失败、完成、取消对每个人都一样，其余的按角色自己的状态：空闲喝茶、被分派拿着任务卡、交回以后高兴、工作打字。
  function roleRest(ctx, d, it, role, isPrimary, roomRest) {
    const base = roomRest(ctx, d, it);
    if (!role || role.kind === 'agent' || role.kind === 'ops') return base;
    if (role.status === 'away') return { away: true };
    const seat = (pose, extra) => Object.assign({ spot: 'desk', pose }, extra || {});
    const st = it && it.status;
    if (st && st !== 'working') {
      if (isPrimary) return base;
      if (st === 'paused') return seat('sit_relax');
      if (st === 'failed') return seat('slump');
      if (st === 'done') return { spot: 'stand', pose: 'idle_happy' };
      if (st === 'cancelled' || st === 'upgrade_stopped') return { spot: 'stand', pose: 'idle' };
    }
    if (!it) return seat('tea');
    switch (role.status) {
      case 'idle': return seat('tea');
      case 'assigned': return seat('sit_card', { hold: 'card_task' });
      case 'returned': return seat('sit_happy');
      case 'failed': return seat('slump');
      default: return seat('type');
    }
  }

  // ---------------------------------------------------------------------------
  // 任务目录（v8 design.md 第 8.3 节那张表）：一个角色做的一件事。键是画面的动作种类；part 为真的是一个动作里的一步
  // （交接的放下与取出、传信的塞信与取信、决定单的送出与收下、分派与交回的接收一方），不单独作为动作出现。
  //
  // 每一项：{ tier, label, spot, pose, bubble, ms, icon, facing, by, actor, toward, then, fx, idle, part }
  // tier：动作的级别（key 关键、normal 普通、progress 进度，画面与播放设计说明第 5.1 节）；ms：到达位置以后演多久，也是声明的最短时长
  // fx：任务开始（到达位置）与做完时的效果，由 floor.js 执行：
  //   { when: 'start'｜'done', signal: 名字, ms }                        信号亮一段时间
  //   { when: ..., flash: { room, color, ms } }                          房间闪一下（room 为 'self' 是做这件事的角色所在的房间）
  //   { when: ..., send: { link, bmp, color, reverse, then: [效果] } }    包裹沿管道走，到达以后执行 then

  const TASKS = {
    // 进度：不排队，坐在桌前的姿势，头顶写最近的一项
    gather: { tier: 'progress', label: '整理资料', spot: 'desk', pose: 'type', bubble: 'say', ms: 900 },
    think: { tier: 'progress', label: '打字', spot: 'desk', pose: 'type', bubble: 'say', ms: 1400 },
    idea: { tier: 'progress', label: '有想法了', spot: 'desk', pose: 'sit_happy', bubble: 'say', ms: 600, icon: 'bulb' },
    retry: { tier: 'progress', label: '等待重试', spot: 'desk', pose: 'sit_wait', bubble: 'say', ms: 1400, icon: 'hourglass' },
    // 普通：开始一件事、读材料、写文件、运行命令
    request_failed: { tier: 'normal', label: '失败了', spot: 'desk', pose: 'slump', bubble: 'say', ms: 900, icon: 'cross' },
    search: { tier: 'normal', label: '翻找资料', spot: 'cabinet', pose: 'magnify', bubble: 'say', ms: 1200 },
    read: { tier: 'normal', label: '阅读文件', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 1100 },
    write: { tier: 'normal', label: '编辑', spot: 'desk', pose: 'type', bubble: 'say', ms: 1200 },
    command: { tier: 'normal', label: '执行命令', spot: 'terminal', pose: 'lever', bubble: 'say', ms: 1600 },
    fetch: { tier: 'normal', label: '网络取回', spot: 'port_in', pose: 'side_place', bubble: 'say', ms: 1200 },
    tool: { tier: 'normal', label: '调用工具', spot: 'terminal', pose: 'lever', bubble: 'say', ms: 1200 },
    browse: { tier: 'normal', label: '试用网页', spot: 'desk', pose: 'type', bubble: 'say', ms: 1400 },
    self_test: { tier: 'normal', label: '自测网页', spot: 'desk', pose: 'type', bubble: 'say', ms: 1400 },
    scan: { tier: 'normal', label: '阅读旧档案', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 1200 },
    inspect: { tier: 'normal', label: '放大镜检查', spot: 'inspect', pose: 'magnify', bubble: 'say', ms: 1200 },
    tool_denied: { tier: 'normal', label: '工具没有获准', spot: 'desk', pose: 'sit_scratch', bubble: 'say', ms: 700, icon: 'cross' },
    submit: { tier: 'normal', label: '提交提案', by: 'manager', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 900 },
    rejected: { tier: 'normal', label: '提案被退回', spot: 'desk', pose: 'sit_scratch', bubble: 'say', ms: 900, icon: 'question' },
    note_in: { tier: 'normal', label: '门缝塞进纸条', by: 'manager', spot: 'port_in', pose: 'crouch', bubble: 'say', ms: 700, icon: 'exclaim' },
    note_read: { tier: 'normal', label: '阅读指导', spot: 'cabinet', pose: 'read_sit', bubble: 'say', ms: 900 },
    note_reply: { tier: 'normal', label: '写回复', spot: 'desk', pose: 'type', bubble: 'say', ms: 900 },
    compact: { tier: 'normal', label: '整理摘要', spot: 'cabinet', pose: 'sit_up', bubble: 'say', ms: 900 },
    compact_fail: { tier: 'normal', label: '重新整理', spot: 'desk', pose: 'sit_scratch', bubble: 'say', ms: 900, icon: 'cross' },
    // 关键：采纳、质检结论、交付封存、终止与等待
    stamp_valid: { tier: 'key', label: '盖上有效章', spot: 'desk', pose: 'sit_happy', bubble: 'say', ms: 800, icon: 'check' },
    seal: { tier: 'key', label: '装箱封存', by: 'manager', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 900, icon: 'check' },
    stamp_release: { tier: 'key', label: '放行', spot: 'inspect', pose: 'stamp_once', bubble: 'say', ms: 1100, icon: 'check' },
    stamp_defect: { tier: 'key', label: '打回返工', spot: 'inspect', pose: 'stamp_once', bubble: 'say', ms: 1100, icon: 'exclaim' },
    paused: { tier: 'key', label: '事项暂停', spot: 'desk', pose: 'sit_relax', bubble: 'say', ms: 1200, icon: 'zzz' },
    failed: { tier: 'key', label: '事项失败', spot: 'desk', pose: 'slump', bubble: 'say', ms: 1200, icon: 'cross' },
    done: { tier: 'key', label: '事项完成', spot: 'stand', pose: 'cheer', bubble: 'say', ms: 1200 },
    upgrade_stop: { tier: 'key', label: '收拾桌面', spot: 'stand', pose: 'tidy', bubble: 'say', ms: 1200 },
    model_back: { tier: 'key', label: '模型服务恢复', spot: 'desk', pose: 'sit_up', bubble: 'say', ms: 700 },
    repair_stop: { tier: 'key', dept: 'operations', label: '停止自动修复', spot: 'desk', pose: 'sit_wait', bubble: 'say', ms: 1200, icon: 'cross' },
    // 自动继续时每个角色伸一个懒腰（动作 resume 的一步）
    stretch: { part: true, label: '伸懒腰', spot: 'desk', pose: 'stretch_sit', bubble: null, ms: 800 },
    // 交接：把包裹放进管道口、从管道口取出；返工与回流走另一侧的管道口。对外的事由经理做
    package_handoff_out: { part: true, label: '放进管道口', by: 'manager', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 520, facing: 1 },
    package_handoff_in: { part: true, label: '从管道口取出', by: 'manager', spot: 'port_in', pose: 'crouch', bubble: 'say', ms: 520, facing: -1 },
    package_return_out: { part: true, label: '放进回流口', by: 'manager', spot: 'port_in', pose: 'side_place', bubble: 'say', ms: 520, facing: -1 },
    package_return_in: { part: true, label: '从回流口取出', by: 'manager', spot: 'port_out', pose: 'crouch', bubble: 'say', ms: 520, facing: 1 },
    // 传信：信件塞进传信管口（方向由 spot 与 facing 决定），收信的经理走到信来的那一侧管口取信
    letter_out: { part: true, label: '发出询问', by: 'manager', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 520, facing: 1 },
    letter_in: { part: true, label: '回答询问', by: 'manager', spot: 'port_in', pose: 'side_place', bubble: 'say', ms: 520, facing: -1 },
    letter_arrive_in: { part: true, label: '收到来信', by: 'manager', spot: 'port_in', pose: 'crouch', bubble: 'say', ms: 520, facing: -1 },
    letter_arrive_out: { part: true, label: '收到来信', by: 'manager', spot: 'port_out', pose: 'crouch', bubble: 'say', ms: 520, facing: 1 },
    // 决定请求：提出决定的部门的小人走到门口送出决定单，回答以后在门口收下（决定单在大厅的板上，由 floor.js 处理）
    decision_give: { part: true, label: '现在送出决定单', by: 'manager', spot: 'door', pose: 'give', bubble: 'say', ms: 600 },
    decision_take: { part: true, label: '收到你的回答', by: 'manager', spot: 'door', pose: 'take', bubble: 'say', ms: 600 },
    // 部门内的角色之间（Stage 5）：经理把任务卡递到工具角色的工位，工具角色把结果卡交回经理，审查者盖章，探索者查资料
    assign: { tier: 'normal', label: '分派任务', actor: 'manager', spot: 'peer', toward: 'role', pose: 'give', bubble: 'say', ms: 700, then: 'role_task_received' },
    role_task_received: { part: true, label: '收到任务', spot: 'desk', pose: 'take', bubble: 'say', ms: 600 },
    hand_back: { tier: 'normal', label: '交回结果', by: 'manager', spot: 'peer', toward: 'manager', pose: 'give', bubble: 'say', ms: 600, then: 'role_result_received' },
    role_result_received: { part: true, label: '收到结果', spot: 'desk', pose: 'take', bubble: 'say', ms: 600 },
    review_pass: { tier: 'normal', label: '审查通过', spot: 'desk', pose: 'stamp_once', bubble: 'say', ms: 1100, icon: 'check' },
    review_return: { tier: 'normal', label: '审查退回', spot: 'desk', pose: 'stamp_once', bubble: 'say', ms: 1100, icon: 'exclaim' },
    explore: { tier: 'normal', label: '查资料', spot: 'cabinet', pose: 'rummage', bubble: 'say', ms: 1400 },
    // 运维（Stage 4）：发布与回滚是把包裹放进通往机房的管道口，故障是盯着监控屏并把故障信件送回大厅；做完以后才有包裹与信号
    deploy: {
      tier: 'key', dept: 'operations', label: '发布', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 700, facing: 1,
      fx: [{ when: 'done', send: { link: 'operations>machine_room', bmp: 'box_sealed', then: [{ signal: 'door', ms: 1800 }] } }]
    },
    rollback: {
      tier: 'key', dept: 'operations', label: '回滚', spot: 'port_out', pose: 'side_place', bubble: 'say', ms: 700, facing: 1,
      fx: [{ when: 'done', send: { link: 'operations>machine_room', reverse: true, bmp: 'box', then: [{ flash: { room: 'self', color: 'orange1', ms: 800 } }] } }]
    },
    fault: {
      tier: 'key', dept: 'operations', label: '发现故障', spot: 'monitor', pose: 'watch_r', bubble: 'say', ms: 1200, icon: 'exclaim', facing: 1,
      fx: [
        { when: 'start', signal: 'monitor', ms: 4000 },
        { when: 'done', send: { link: 'operations>hall', bmp: 'letter', color: 'red2', then: [{ signal: 'mail', ms: 1800 }] } }
      ]
    },
    // 待机活动：空闲的角色自己挑一件事做（位置由 ecs.js 抽定：房间里的一个位置、门口、同伴身边）
    idle_stretch_seat: { label: '', spot: 'desk', pose: 'stretch_sit', bubble: null, ms: 1300, idle: true },
    idle_wander: { label: '', spot: 'at', pose: 'stretch', bubble: null, ms: 1500, idle: true },
    idle_browse: { label: '', spot: 'cabinet', pose: 'rummage', bubble: null, ms: 2200, idle: true },
    idle_look: { label: '', spot: 'at', pose: 'look_up', bubble: null, ms: 2400, idle: true },
    idle_chat: { label: '', spot: 'at', pose: 'talk', bubble: null, ms: 3200, idle: true }
  };

  const IDLE = [
    { key: 'idle_stretch_seat', weight: 3 },
    { key: 'idle_wander', weight: 4, at: 'wander' },
    { key: 'idle_browse', weight: 3 },
    { key: 'idle_look', weight: 2, at: 'door' },
    { key: 'idle_chat', weight: 4, needs: 'mate' }
  ];

  // ---------------------------------------------------------------------------
  // 不是一个角色一件事的动作：包裹、信件、决定单、闪光与信号，floor.js 逐种演。ms 是声明的最短时长
  //   handoff：包裹沿管道从一个房间送到另一个房间（两端各有一个经理）；letter：信件沿传信管往返（询问与回答）；
  //   decision_out、decision_back：决定单从部门门口飞到大厅的板上、回答以后飞回来；adopt：成果库的架子亮起；
  //   parcel_enter：事项拿到执行槽位，包裹从大厅送进第一个房间；resume：自动继续，每个角色伸懒腰、房间亮起；
  //   mail：信件投进大厅的信箱；parcel_in：大厅队列多一个包裹；queue_moved：队列顺序改变；room_light：部门开始工作，房间亮一下；
  //   unsure：动作结果未知，房间闪黄光；remote：远程动作，门缝透光、光点在走廊里走；model_wait：进入等待模型服务，房间调暗一下

  const EFFECTS = {
    handoff: { tier: 'key', ms: 1800 },
    letter: { tier: 'key', ms: 1800 },
    decision_out: { tier: 'key', ms: 1600 },
    decision_back: { tier: 'key', ms: 1600 },
    adopt: { tier: 'key', ms: 1800 },
    parcel_enter: { tier: 'key', ms: 1200 },
    resume: { tier: 'key', ms: 800 },
    model_wait: { tier: 'key', ms: 900 },
    mail: { tier: 'normal', ms: 900 },
    parcel_in: { tier: 'normal', ms: 700 },
    queue_moved: { tier: 'normal', ms: 900 },
    room_light: { tier: 'normal', ms: 700 },
    unsure: { tier: 'normal', ms: 1400 },
    remote: { tier: 'normal', ms: 1400 }
  };

  // 楼层画面认的动作种类：任务目录里不是一步也不是待机活动的项，加上上面的动作
  const KINDS = {};
  Object.keys(TASKS).forEach((k) => { if (!TASKS[k].part && !TASKS[k].idle) KINDS[k] = { tier: TASKS[k].tier, ms: TASKS[k].ms }; });
  Object.keys(EFFECTS).forEach((k) => { KINDS[k] = EFFECTS[k]; });

  P.floorDecl = {
    rooms: ROOMS, links: LINKS, tasks: TASKS, effects: EFFECTS, kinds: KINDS, idle: IDLE,
    flags: ['ops'],
    deptRest, roleRest
  };
})();
