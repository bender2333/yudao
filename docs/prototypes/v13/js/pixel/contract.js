// 画面合同（画面与播放设计说明第 4 节）：画面层唯一认的输入。翻译层（js/translate/）照这里写的形状与取值给出状态、动作与实时内容，
// 画面层收到别的取值就报错。这里只用画面的说法：服务端的事件种类、查询名与状态值只出现在翻译层的对照表里。
//
// 状态（setState / jump）：一个场景此刻应该画出的事实，带 position（来自的查询快照的位置）。字段沿用 v12 画面模型的名字。
// 动作（play）：发生了什么，用来演，带 position（来源事件的位置）；kind 取自场景的声明表（floor-decl、room-decl、building-decl），
//   级别与时长写在声明表里，动作本身不带。
// 实时内容：决定卡片（楼层的 setDecisions）、流式文字（stream）、覆盖层（楼层的 setOverlay），到了就显示，不进时间线。
// 回调：选择决定选项、点击跳转、点开机房的门与楼层，由页面变成命令或跳转。
(function () {
  'use strict';
  const P = window.Y13.pixel;

  // 事项在楼层上的状态：在大厅排队、在房间里工作或等待、结束，以及采纳
  const ITEM_STATES = ['queued', 'waiting_slot', 'working', 'asking', 'waiting_model', 'waiting_resume', 'waiting_user', 'paused',
    'interrupted', 'failed', 'done', 'cancelled', 'upgrade_stopped', 'adopted'];
  // 一个部门同时在做什么（事项停在别的房间时这个房间也亮灯）
  const BUSY_STATES = ['working', 'answering', 'waiting_user'];
  // 楼里每一层的状态灯
  const FLOOR_SIGNS = ['working', 'queued', 'waiting_slot', 'waiting_model', 'waiting_resume', 'waiting_user', 'interrupted', 'idle'];
  // 部门房间的状态
  const ROOM_STATES = ['idle', 'working', 'asking', 'paused', 'failed', 'done', 'cancelled', 'interrupted', 'waiting_resume'];
  // 部门里一个角色的状态
  const ROLE_STATES = ['idle', 'assigned', 'working', 'returned', 'failed', 'away'];
  // 事实元素的来源种类（覆盖层「来源」与来源卡片）
  const SOURCES = ['rule', 'host_measurement', 'user', 'role_statement', 'decision_model'];
  // 收敛状态（覆盖层「循环」）
  const LOOP_STATES = ['converging', 'stalled', 'oscillating', 'drifting', 'at_bound', 'not_judged'];
  // 交接的包裹
  const ARTIFACTS = ['prd', 'box', 'defect', 'release'];
  // 房间里状态的姿势（roomState.pose.anim）
  const POSES = ['type', 'read_sit', 'write', 'think', 'rummage', 'sit_wait', 'tea', 'sit', 'inspect'];

  const fail = (what, v) => { throw new Error('画面合同：' + what + '：' + JSON.stringify(v)); };
  const oneOf = (list, v, what) => { if (!list.includes(v)) fail(what, v); };
  const pos = (s, what) => { if (!s || !Number.isFinite(s.position)) fail(what + '没有位置', s && s.position); };
  const ref = (r, what) => { if (r && r.source !== undefined && r.source !== null) oneOf(SOURCES, r.source, what + '的来源'); };
  const refs = (o, what) => { if (o) Object.keys(o).forEach((k) => ref(o[k], what + '.' + k)); };

  function floorState(s) {
    pos(s, '楼层的状态');
    if (!Array.isArray(s.items)) fail('楼层的状态缺少 items', s.items);
    s.items.forEach((it) => {
      oneOf(ITEM_STATES, it.status, '事项 ' + it.id + ' 的状态');
      if (it.departments) Object.keys(it.departments).forEach((d) => oneOf(BUSY_STATES, it.departments[d], '事项 ' + it.id + ' 里 ' + d + ' 的状态'));
      refs(it.refs, '事项 ' + it.id);
    });
    if (s.roles) Object.keys(s.roles).forEach((d) => s.roles[d].forEach((r) => oneOf(ROLE_STATES, r.status, '角色 ' + r.id + ' 的状态')));
    if (s.stamp) ref(s.stamp.ref, '盖章');
    return s;
  }

  function buildingState(s) {
    pos(s, '楼的状态');
    if (!Array.isArray(s.floors)) fail('楼的状态缺少 floors', s.floors);
    s.floors.forEach((f) => oneOf(FLOOR_SIGNS, f.status, '楼层 ' + f.project_id + ' 的状态灯'));
    return s;
  }

  function machineRoomState(s) {
    pos(s, '机房的状态');
    if (!Array.isArray(s.machines)) fail('机房的状态缺少 machines', s.machines);
    return s;
  }

  function roomState(s) {
    pos(s, '房间的状态');
    oneOf(ROOM_STATES, s.status, '房间的状态');
    (s.roles || []).forEach((r) => oneOf(ROLE_STATES, r.status, '角色 ' + r.id + ' 的状态'));
    if (s.pose) oneOf(POSES, s.pose.anim, '房间的姿势');
    return s;
  }

  // 动作：kind 在这个场景的声明表里，带位置；交接的包裹是四种之一
  function action(scene, a, kinds) {
    pos(a, scene + '的动作');
    if (!kinds[a.kind]) fail(scene + '的声明表里没有这种动作', a.kind);
    if (a.artifact !== undefined) oneOf(ARTIFACTS, a.artifact, '交接的包裹');
    return a;
  }

  P.contract = {
    ITEM_STATES, BUSY_STATES, FLOOR_SIGNS, ROOM_STATES, ROLE_STATES, SOURCES, LOOP_STATES, ARTIFACTS, POSES,
    floorState, buildingState, machineRoomState, roomState, action
  };
})();
