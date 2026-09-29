// 像素画面引擎：小人合成与离屏缓存、姿势与动作帧、画布缩放与动画循环、路径移动与缓动、粒子、
// 共用物件的绘制，以及事件到动作的对照表（设计说明第 8.3 节）。
(function () {
  const Y8 = window.Y8;
  const P = Y8.pixel;
  if (!P || !P.PAL || !P.CHAR) throw new Error('engine.js 需要先加载 js/pixel/sprites.js');
  const PAL = P.PAL;
  const FONT = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", "Source Han Sans SC", sans-serif';
  P.FONT = FONT;

  // ===========================================================================
  // 1. 事实与动作对照表

  function act(label, fact, source, action, room, level, anim) {
    return { label, fact, source, action, room, level, anim };
  }

  // 动作名称到说明：与设计说明第 8.3 节逐行对应（「暂停、失败、完成、取消」一行拆成四个动作）
  P.ACTIONS = {
    tea: act('喝茶与伸懒腰', '部门未工作', '部门状态', '坐在工位喝茶，偶尔起身在房间里走动、伸懒腰', '灯光调暗', 'ui', 'tea'),
    activate: act('起身走到工位', '部门开始工作', 'department_activated', '起身走到工位', '屏幕亮起，CRT 显示目标', 'ui', 'walk'),
    fetch_folder: act('取出文件夹', '装配上下文', 'context_assembled', '从文件柜取出文件夹放到桌上', '—', 'ui', 'rummage'),
    type_think: act('打字与思考气泡', '模型请求中', 'model_requested、model_request_serialized', '打字，头顶思考气泡', '屏幕滚动字符', 'ui', 'type'),
    stream_text: act('气泡逐字出现', '流式输出', 'model_stream_progress', '气泡中逐字出现文字', '—', 'ui', 'type'),
    idea: act('气泡变成灯泡', '请求完成', 'model_attempt_finished', '气泡变成灯泡', '—', 'ui', 'sit_happy'),
    retry_wait: act('沙漏与重试次数', '等待重试', 'model_retry_scheduled', '头顶沙漏与「第 n/m 次」', '—', 'ui', 'sit_wait'),
    slump: act('趴在桌上', '请求失败', 'model_attempt_failed', '趴在桌上', '桌上红灯', 'ui', 'slump'),
    search: act('翻文件柜举放大镜', '搜索', 'tool_started（search）', '翻文件柜，举放大镜', '文件柜抽屉打开', 'ui', 'magnify'),
    read: act('捧着文件阅读', '按区间阅读', 'tool_started（read_range、read_file）', '捧着文件阅读', '—', 'ui', 'read_sit'),
    write: act('在文件上写字', '编辑', 'tool_started（edit_range、write_file）', '在文件上写字', '屏幕显示增删的行', 'ui', 'write'),
    run_command: act('走到终端拉下拉杆', '执行登记命令', 'tool_started（run_command）到 tool_called', '走到终端拉下拉杆', '终端滚动输出；结束时退出状态灯亮绿灯或红灯；超时时终端冒烟', 'ui', 'lever'),
    toss: act('摇头扔纸团', '工具被拒绝', 'tool_skipped', '摇头，把纸团扔进废纸篓', '—', 'ui', 'shake'),
    submit: act('放进提案托盘', '提交提案', 'proposal_submitted', '把文件放进提案托盘', '—', 'ui', 'side_place'),
    returned: act('文件退回挠头', '提案被退回', 'proposal_rejected', '文件被退回，小人挠头', '—', 'ui', 'scratch'),
    stamp_valid: act('卷轴盖「有效」章', '需求接纳', 'spec_accepted、contract_accepted', '产品在卷轴上盖「有效」章，卷起后放进管道口', '卷轴放上卷轴架', 'ui', 'stamp'),
    pin_plan: act('计划贴上白板', '计划接纳', 'plan_accepted', '工程把计划贴上白板', '—', 'ui', 'board_pin'),
    seal: act('装箱贴封条盖章', '交付封存', 'delivery_accepted', '工程装箱、贴封条、盖封存章，把箱子推进管道口', '—', 'ui', 'stamp'),
    take_box: act('从管道口取出箱子', '质检取件', '交接到达质检（transition，to 为 quality）', '从管道口取出箱子放上检验台', '—', 'ui', 'reach'),
    inspect: act('放大镜检查箱子', '质检核验', '质检的检查动作（tool_started：run_check）', '用放大镜检查箱子，清单逐项打勾', '—', 'ui', 'inspect'),
    stamp_release: act('盖绿色「放行」章', '放行', 'qa_submitted（release）', '盖绿色「放行」章，把放行单与箱子放进通往成果库的管道', '—', 'ui', 'stamp'),
    stamp_rework: act('盖红色「返工」章', '返工', 'qa_submitted（rework_engineering、rework_product）', '盖红色「返工」章，把箱子放进回流管道', '—', 'ui', 'stamp'),
    send_letter: act('写纸条塞进传信管口', '发出询问', 'collaboration_requested', '写纸条装进信筒，塞进传信管口，在管道口等待', '—', 'ui', 'side_place'),
    answer_letter: act('取出信筒并回答', '收到询问并回答', 'collaboration_responded', '从传信管口取出信筒，写回答后塞回', '—', 'ui', 'catch'),
    guidance_in: act('门缝塞进纸条', '收到指导', 'department_guidance_received', '—', '门缝塞进纸条，信箱灯亮', 'ui', 'sit'),
    guidance_read: act('阅读并钉上纸条', '指导进入输入', 'department_guidance_applied', '拿起纸条阅读，钉在墙上', '—', 'ui', 'read_stand'),
    guidance_reply: act('在纸条上写回复', '回应指导', 'department_guidance_responded', '在纸条上写回复', '—', 'ui', 'board_write'),
    compact: act('纸堆整理进档案盒', '压缩', 'compaction_recorded', '把桌上成堆的纸整理进「摘要」档案盒', '档案盒上的编号加一', 'ui', 'gather'),
    compact_fail: act('纸堆散落重新整理', '压缩未生效', 'compaction_failed', '纸堆散落，小人重新整理', '—', 'ui', 'crouch'),
    paused: act('坐下', '暂停', 'run_paused', '坐下', '门口立「已暂停」牌', 'ui', 'sit_relax'),
    failed: act('趴下', '失败', 'run_failed', '趴下', '门口立「失败」牌与停止原因', 'ui', 'slump'),
    done: act('举手欢呼', '完成', 'run_done', '举手欢呼', '门口立「已完成」牌', 'ui', 'cheer'),
    cancelled: act('收拾桌面', '取消', 'run_failed（reason 为 cancelled）', '收拾桌面', '门口立「已取消」牌', 'ui', 'tidy'),
    hold_card: act('举牌写明缺少的项', '待恢复', '模型引用无法使用（waiting_resume）', '举牌，牌上写缺少的项', '门口立「待恢复」牌', 'ui', 'hold_sign'),
    freeze: act('静止不动', '中断', '恢复观察状态（x_run_interrupted）', '静止不动', '灯灭，墙上时钟停住', '3.1', 'freeze'),
    resume: act('伸懒腰回到工位', '自动继续', 'Yudao 启动时自动继续（x_run_auto_resumed）', '伸懒腰后回到工位', '灯亮起，时钟继续走', '3.1', 'stretch'),
    puzzled: act('头顶黄色问号', '待核实', '恢复观察状态与未完成动作（x_action_unknown）', '站在未完成动作的物件旁，头顶黄色问号', '物件闪烁', '3.1', 'puzzled'),
    decided: act('接过决定单照着做', '用户对结果未知的动作作出决定', '决定请求的回答（x_decision_answered）', '从门缝接过决定单，读完后按决定走向终端重新执行、回到工位继续或收拾桌面', '物件停止闪烁', '3.1', 'read_stand'),
    remote_run: act('终端显示机器名称与线', '远程执行', '动作在登记的机器上执行（x_remote_action_started）', '走到终端，终端屏幕上显示机器名称与一根通往门外的线', '动作结束前线上有流动的光点', '3.2C', 'lever'),
    remote_unknown: act('盯着终端头顶问号', '远程动作结果未知', '执行代理心跳超时（x_machine_offline）', '盯着终端，头顶黄色问号', '终端屏幕变为雪花', '3.2C', 'watch_r'),
    read_existing: act('搬旧档案逐本阅读', '阅读已有项目', '建档事项中的 tool_started（read_file、read_range、search）', '从大厅搬来一摞旧档案，逐本阅读并做摘录', '白板上出现「现有行为」清单', '3.8', 'read_sit'),
    net_fetch: act('邮筒寄出请求取回资料', '网络取回', '网络取回工具（x_network_fetch）', '走到门口的邮筒寄出请求，取回资料', '—', '3.2B', 'walk'),
    mcp_press: act('按下工具面板的按钮', '调用 MCP 工具', 'MCP 工具调用（x_mcp_called）', '在墙上的工具面板上按下对应的按钮', '面板上该按钮亮灯', '3.2B', 'reach'),
    trial: act('坐在试用台前点击与输入', '试用网页或桌面程序', '浏览器与 computer use 工具调用（x_trial_step）', '测试工程师坐在试用台前点击与输入', '试用台显示器嵌入最近一张真实截图的缩略图（像素边框）；模型不能看图时显示可访问性结构的文字行', '3.2D', 'type'),
    self_test: act('在自己的显示器前点击', '工程自测网页', '工程的浏览器工具调用（tool_started：browser）', '工程在自己的显示器前点击', '显示器嵌入截图缩略图', '3.2D', 'type'),
    deploy: act('推车把箱子推进门', '部署', '运维的部署记录（x_deployed）', '运维推车把箱子推进通往机房的门', '备份柜先亮一格（部署前备份）', 'S4', 'push'),
    rollback: act('从门里取回旧版本', '回滚', '运维的回滚记录（x_rolled_back）', '运维从门里取回旧版本的箱子', '—', 'S4', 'carry'),
    fault: act('跑向监控屏写故障信', '发现故障', '故障记录（x_fault_recorded）', '运维跑向监控屏，写故障信件放进通往大厅的管道', '监控屏变红', 'S4', 'run'),
    wait_provider: act('坐着看墙上的时钟', '等待模型服务', '进入等待模型服务（x_provider_wait_entered）', '坐在工位上看着墙上的时钟', '灯光调暗，管道停止流动', 'S4', 'sit_wait'),
    hold_form: act('举着申请单在门口等待', '外部动作待授权', '运维对常设授权清单以外动作的决定请求（external_action）', '举着申请单在门口等待', '—', 'S4', 'hold_form'),
    assign: act('递任务卡', '分派角色任务', '角色任务事件（x_role_task_assigned）', '中心角色把任务卡递到工具角色的桌上', '白板上的计划条目标上分派对象', 'S5', 'give'),
    hand_back: act('交回结果卡', '角色交回结果', '角色结果事件（x_role_result_returned）', '工具角色把结果卡交回中心角色', '条目改为已交回', 'S5', 'give'),
    review: act('红笔批注盖章', '审查', '审查任务（x_review_recorded）', '审查者拿红笔在成果上批注，盖「通过」或「退回」', '—', 'S5', 'stamp'),
    explore: act('背包出门查资料', '探索者查资料', '探索者的网络取回（x_explorer_fetch）', '背上背包走出门，回来时抱着资料', '—', 'S5', 'walk'),
    replan: act('擦掉计划重写', '停滞后重新规划', '部门账本的进展判断（x_replanned）', '中心角色在白板上擦掉计划重写', '—', 'S5', 'board_erase'),
    manager_out: act('经理走到管道口', '经理对外', '经理转交询问、提交部门成果（Stage 5）', '经理走到管道口与传信管口', '—', 'S5', 'walk'),
    semantic: act('卡片放进语义记录柜', '语义整理', '语义整理事件（x_semantic_recorded）', '—', '墙边的语义记录柜里卡片增加', 'S5', 'side_place')
  };

  // 由状态驱动的动作：部门状态或恢复观察状态对应的持续姿势
  P.STATUS_ACTIONS = {
    idle: 'tea', paused: 'paused', failed: 'failed', done: 'done', cancelled: 'cancelled',
    interrupted: 'freeze', pending_verification: 'puzzled', waiting_resume: 'hold_card'
  };

  // 基础动作：移动与待机，动作图鉴单独列出
  P.BASE_MOTIONS = {
    idle: { label: '待机呼吸与眨眼', fact: '站立待机', anim: 'idle' },
    walk: { label: '走路四帧', fact: '在房间与走廊中移动', anim: 'walk' },
    carry: { label: '搬运', fact: '搬运包裹与资料', anim: 'carry' },
    run: { label: '跑步', fact: '发现故障时赶往监控屏', anim: 'run' },
    sit: { label: '坐在工位', fact: '在工位上', anim: 'sit' },
    type: { label: '打字', fact: '在工位工作', anim: 'type' }
  };

  // 事件类型到动作名称：与设计说明第 8.3 节的「来源」一列对应
  P.EVENT_ACTIONS = {
    department_activated: 'activate',
    context_assembled: 'fetch_folder',
    model_requested: 'type_think',
    model_request_serialized: 'type_think',
    model_stream_progress: 'stream_text',
    model_attempt_finished: 'idea',
    model_retry_scheduled: 'retry_wait',
    model_attempt_failed: 'slump',
    tool_started: { by: 'tool', map: { search: 'search', read_range: 'read', read_file: 'read', edit_range: 'write', write_file: 'write', run_command: 'run_command', run_check: 'inspect', browser: 'self_test' } },
    tool_called: { by: 'tool', map: { run_command: 'run_command', browser: 'self_test' } },
    tool_skipped: 'toss',
    proposal_submitted: 'submit',
    proposal_rejected: 'returned',
    spec_accepted: 'stamp_valid',
    contract_accepted: 'stamp_valid',
    plan_accepted: 'pin_plan',
    delivery_accepted: 'seal',
    qa_submitted: { by: 'verdict', map: { release: 'stamp_release', rework_engineering: 'stamp_rework', rework_product: 'stamp_rework' } },
    collaboration_requested: 'send_letter',
    collaboration_responded: 'answer_letter',
    department_guidance_received: 'guidance_in',
    department_guidance_applied: 'guidance_read',
    department_guidance_responded: 'guidance_reply',
    compaction_recorded: 'compact',
    compaction_failed: 'compact_fail',
    run_paused: 'paused',
    run_failed: { by: 'reason', map: { cancelled: 'cancelled' }, default: 'failed' },
    run_done: 'done',
    x_run_interrupted: 'freeze',
    x_run_auto_resumed: 'resume',
    x_action_unknown: 'puzzled',
    x_decision_answered: { by: 'kind', map: { unknown_action: 'decided' }, default: null },
    x_decision_issued: { by: 'kind', map: { external_action: 'hold_form', waiting_resume: 'hold_card' }, default: null },
    x_remote_action_started: 'remote_run',
    x_machine_offline: 'remote_unknown',
    x_network_fetch: 'net_fetch',
    x_mcp_called: 'mcp_press',
    x_trial_step: 'trial',
    x_deployed: 'deploy',
    x_rolled_back: 'rollback',
    x_fault_recorded: 'fault',
    x_provider_wait_entered: 'wait_provider',
    x_role_task_assigned: 'assign',
    x_role_result_returned: 'hand_back',
    x_review_recorded: 'review',
    x_explorer_fetch: 'explore',
    x_replanned: 'replan',
    x_semantic_recorded: 'semantic'
  };

  P.resolveAction = function resolveAction(event) {
    if (!event || !event.type) throw new Error('事件缺少 type');
    const entry = P.EVENT_ACTIONS[event.type];
    if (!entry) return null;
    if (typeof entry === 'string') return entry;
    const payload = event.payload || {};
    const key = entry.by === 'tool' ? (event.tool || payload.tool)
      : entry.by === 'reason' ? (payload.reason || payload.stopReason)
        : entry.by === 'kind' ? payload.kind
          : payload.verdict;
    return entry.map[key] || entry.default || null;
  };

  // 档位比较：按 Y8.LEVELS 的顺序；level 为空时取界面工作线
  P.levelAtLeast = function levelAtLeast(level, min) {
    const a = Y8.LEVELS.indexOf(level || 'ui');
    const b = Y8.LEVELS.indexOf(min || 'ui');
    if (a < 0 || b < 0) throw new Error('未知档位：' + level + ' / ' + min);
    return a >= b;
  };

  // ===========================================================================
  // 2. 颜色与点阵工具

  const rgbCache = new Map();
  function rgb(hex) {
    let v = rgbCache.get(hex);
    if (v) return v;
    if (!/^#[0-9a-f]{6}$/i.test(hex)) throw new Error('颜色格式无效：' + hex);
    v = [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
    rgbCache.set(hex, v);
    return v;
  }
  function hex2(n) { return Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0'); }
  function mix(a, b, t) {
    const x = rgb(a), y = rgb(b);
    return '#' + hex2(x[0] + (y[0] - x[0]) * t) + hex2(x[1] + (y[1] - x[1]) * t) + hex2(x[2] + (y[2] - x[2]) * t);
  }
  P.mix = mix;
  P.rgba = function rgba(hex, a) { const c = rgb(hex); return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; };

  function makeCanvas(w, h) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    return c;
  }
  P.makeCanvas = makeCanvas;

  function gridCanvas(grid, w, h) {
    const c = makeCanvas(w, h);
    const cx = c.getContext('2d');
    const img = cx.createImageData(w, h);
    for (let i = 0; i < w * h; i++) {
      const col = grid[i];
      if (!col) continue;
      const v = rgb(col);
      img.data[i * 4] = v[0]; img.data[i * 4 + 1] = v[1]; img.data[i * 4 + 2] = v[2]; img.data[i * 4 + 3] = 255;
    }
    cx.putImageData(img, 0, 0);
    return c;
  }

  function flipCanvas(src) {
    const c = makeCanvas(src.width, src.height);
    const cx = c.getContext('2d');
    cx.translate(src.width, 0);
    cx.scale(-1, 1);
    cx.drawImage(src, 0, 0);
    return c;
  }

  function outlineGrid(grid, w, h, color) {
    const out = grid.slice();
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x;
        if (grid[i]) continue;
        if ((x > 0 && grid[i - 1]) || (x < w - 1 && grid[i + 1]) || (y > 0 && grid[i - w]) || (y < h - 1 && grid[i + w])) out[i] = color;
      }
    }
    return out;
  }

  // 位图：按名称与改色缓存为离屏画布
  const bmpCache = new Map();
  const ITEM_ALIAS = {
    stamp_valid: ['stamp', { X: '#d4353f' }],
    stamp_green: ['stamp', { X: PAL.green2 }],
    stamp_red: ['stamp', { X: PAL.red2 }],
    stamp_seal: ['stamp', { X: PAL.blue2 }],
    card_task: ['card', { X: PAL.yellow2 }]
  };
  function bitmapDef(name) {
    const alias = ITEM_ALIAS[name];
    if (alias) {
      const baseDef = P.BITMAPS[alias[0]];
      return { rows: baseDef.rows, map: Object.assign({}, baseDef.map, alias[1]), outline: baseDef.outline };
    }
    const d = P.BITMAPS[name];
    if (!d) throw new Error('未知位图：' + name);
    return d;
  }
  P.bitmapDef = bitmapDef;

  P.bitmap = function bitmap(name, recolor) {
    const key = recolor ? name + '|' + JSON.stringify(recolor) : name;
    let entry = bmpCache.get(key);
    if (entry) return entry;
    const d = bitmapDef(name);
    const map = recolor ? Object.assign({}, d.map, recolor) : d.map;
    const pad = d.outline ? 1 : 0;
    const bw = d.rows[0].length, bh = d.rows.length;
    const w = bw + pad * 2, h = bh + pad * 2;
    let grid = new Array(w * h).fill(null);
    for (let y = 0; y < bh; y++) {
      for (let x = 0; x < bw; x++) {
        const ch = d.rows[y][x];
        if (ch === '.') continue;
        const col = map[ch];
        if (!col) throw new Error('位图 ' + name + ' 的字符没有颜色：' + ch);
        grid[(y + pad) * w + x + pad] = col;
      }
    }
    if (pad) grid = outlineGrid(grid, w, h, PAL.ink);
    const canvas = gridCanvas(grid, w, h);
    entry = { canvas, flipped: null, pad, w: bw, h: bh };
    bmpCache.set(key, entry);
    return entry;
  };

  // 在 (x, y) 处画位图，(x, y) 为位图自身第一个像素（不含描边）的位置
  P.drawBitmap = function drawBitmap(ctx, name, x, y, opts) {
    const o = opts || {};
    const b = P.bitmap(name, o.recolor);
    let c = b.canvas;
    if (o.flip) {
      if (!b.flipped) b.flipped = flipCanvas(b.canvas);
      c = b.flipped;
    }
    if (o.alpha !== undefined) ctx.globalAlpha = o.alpha;
    ctx.drawImage(c, Math.round(x) - b.pad, Math.round(y) - b.pad);
    if (o.alpha !== undefined) ctx.globalAlpha = 1;
    return b;
  };

  // ===========================================================================
  // 3. 小人合成

  const CW = 32, CH = 40;
  P.CHAR_W = CW; P.CHAR_H = CH;

  function parseSpriteKey(key) {
    const parts = String(key).split(':');
    const base = parts[0];
    const item = parts.length > 1 && parts[1] !== '' ? Number(parts[1]) : null;
    let dept, kind;
    if (base.includes('.')) {
      [dept, kind] = base.split('.');
    } else {
      kind = base;
      dept = { ops: 'operations' }[kind];
    }
    if (!dept || !P.ROLE_KINDS[kind]) throw new Error('小人标识无效：' + key);
    if (item !== null && !(item >= 0 && item < P.ITEM_COLORS.length)) throw new Error('事项颜色序号无效：' + key);
    return { dept, kind, item };
  }
  P.parseSpriteKey = parseSpriteKey;

  const specCache = new Map();
  function spriteSpec(key) {
    let s = specCache.get(key);
    if (s) return s;
    const k = parseSpriteKey(key);
    const pal = P.rolePalette(k.dept, k.kind, k.item);
    s = { key, dept: k.dept, kind: k.kind, role: P.ROLE_KINDS[k.kind], map: pal.map, sleeve: pal.sleeve };
    specCache.set(key, s);
    return s;
  }

  function put(g, x, y, c) {
    if (x < 0 || y < 0 || x >= CW || y >= CH) return;
    g[y * CW + x] = c;
  }
  function blk(g, x, y, c) { put(g, x, y, c); put(g, x + 1, y, c); put(g, x, y + 1, c); put(g, x + 1, y + 1, c); }
  function blit(g, rows, x, y, map, flip) {
    if (!rows) return;
    const w = rows[0].length;
    for (let r = 0; r < rows.length; r++) {
      const row = rows[r];
      for (let c = 0; c < w; c++) {
        const ch = flip ? row[w - 1 - c] : row[c];
        if (ch === '.') continue;
        const col = map[ch];
        if (!col) throw new Error('小人部件字符没有颜色：' + ch);
        put(g, x + c, y + r, col);
      }
    }
  }
  function linePts(x0, y0, x1, y1) {
    const pts = [];
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy, x = x0, y = y0;
    for (let guard = 0; guard < 200; guard++) {
      pts.push([x, y]);
      if (x === x1 && y === y1) break;
      const e2 = 2 * err;
      if (e2 >= dy) { err += dy; x += sx; }
      if (e2 <= dx) { err += dx; y += sy; }
    }
    return pts;
  }
  P.linePts = linePts;

  // 侧面走路与跑步的腿：n 近侧脚踝，f 远侧脚踝（2×2 块的左上角），bob 为身体起伏
  const LEGS_S = {
    ss: { n: [15, 34], f: [13, 34], bob: 0 },
    w0: { n: [18, 34], f: [11, 34], bob: 0 },
    w1: { n: [15, 34], f: [13, 32], bob: -1 },
    w2: { n: [11, 34], f: [18, 34], bob: 0 },
    w3: { n: [14, 32], f: [13, 34], bob: -1 },
    r0: { n: [19, 33], f: [10, 34], bob: -1 },
    r1: { n: [15, 34], f: [12, 31], bob: -2 },
    r2: { n: [10, 34], f: [19, 33], bob: -1 },
    r3: { n: [14, 31], f: [15, 34], bob: -2 }
  };

  // 姿势：v 视角（f 正面、s 侧面朝右、b 背面），sit 坐姿，bob 身体起伏，hx/hy 头部偏移，
  // A/B 两只手相对肩部的偏移（侧面时 A 为近侧、B 为远侧），item 手持物件，idle 手持角色的待机物件
  const POSES = {};
  P.POSES = POSES;
  function pz(name, v, o) {
    POSES[name] = Object.assign({ v, sit: 0, bob: 0, hx: 0, hy: 0, face: null, legs: v === 's' ? 'ss' : 'stand', A: [0, 5], B: [0, 5], item: null, item2: null, headDown: false, idle: false }, o);
  }

  // 正面站立
  pz('stand', 'f', { idle: true });
  pz('stand_b', 'f', { hy: 1, idle: true });
  pz('stand_happy', 'f', { face: 'happy', idle: true });
  pz('stand_sad', 'f', { face: 'sad', A: [1, 5], B: [-1, 5] });
  pz('look_l', 'f', { face: 'left', idle: true });
  pz('look_r', 'f', { face: 'right', idle: true });
  pz('look_up', 'f', { face: 'up', idle: true });
  pz('wait0', 'f', { face: 'right', A: [4, 3], B: [-4, 3] });
  pz('wait1', 'f', { face: 'right', A: [4, 3], B: [-4, 3], legs: 'tap' });
  pz('cheer0', 'f', { bob: -3, face: 'happy', A: [-2, -7], B: [2, -7] });
  pz('cheer1', 'f', { face: 'happy', A: [-2, -4], B: [2, -4] });
  pz('stretch0', 'f', { face: 'closed', A: [-1, -6], B: [1, -6] });
  pz('stretch1', 'f', { bob: -1, hy: -1, face: 'closed', A: [-2, -8], B: [2, -8] });
  pz('scratch0', 'f', { face: 'worried', B: [-2, -8] });
  pz('scratch1', 'f', { face: 'worried', B: [-1, -9], hx: -1 });
  pz('shake0', 'f', { face: 'sad', hx: -1 });
  pz('shake1', 'f', { face: 'sad', hx: 1 });
  pz('puzzled', 'f', { face: 'worried', B: [-4, -1] });
  pz('puzzled_b', 'f', { face: 'worried', B: [-4, -1], hx: 1 });
  pz('hold_sign', 'f', { A: [1, -10], B: [-1, -10] });
  pz('hold_sign_b', 'f', { A: [1, -10], B: [-1, -10], hy: 1 });
  pz('hold_form', 'f', { A: [3, -1], B: [-3, -1], item: { id: 'form', at: 'both', dy: 2 } });
  pz('hold_form_b', 'f', { A: [3, -1], B: [-3, -1], hy: 1, face: 'up', item: { id: 'form', at: 'both', dy: 2 } });
  pz('hold_ticket', 'f', { A: [3, 2], B: [-3, 2], item: { id: 'ticket', at: 'both', dy: 1 } });
  pz('hold_ticket_b', 'f', { A: [3, 2], B: [-3, 2], hy: 1, face: 'left', item: { id: 'ticket', at: 'both', dy: 1 } });
  pz('carry_f', 'f', { A: [2, 3], B: [-2, 3], item: { id: '$hold', at: 'both', dy: 1 } });
  pz('reach_r0', 'f', { face: 'right', B: [3, -2] });
  pz('reach_r1', 'f', { face: 'right', B: [4, -3] });
  pz('rummage0', 'f', { face: 'right', B: [4, -2], hx: 1 });
  pz('rummage1', 'f', { face: 'right', B: [3, -4], hx: 1 });
  pz('grab_folder', 'f', { face: 'happy', B: [4, -3], item: { id: 'folder', hand: 'B', dx: -1, dy: -5 } });
  pz('magnify', 'f', { B: [-1, -2], item: { id: 'magnifier', hand: 'B', dx: -5, dy: -5 } });
  pz('magnify_b', 'f', { B: [-2, -2], hx: -1, item: { id: 'magnifier', hand: 'B', dx: -5, dy: -5 } });
  pz('read_stand', 'f', { face: 'down', A: [3, 2], B: [-3, 2], item: { id: '$hold', at: 'both', dy: 2 } });
  pz('read_stand_b', 'f', { face: 'down', A: [3, 2], B: [-3, 2], hy: 1, item: { id: '$hold', at: 'both', dy: 2 } });
  pz('give', 'f', { face: 'right', B: [5, 0], item: { id: '$hold', hand: 'B', dx: 1, dy: -3 } });
  pz('give_b', 'f', { face: 'happy', B: [5, 1], item: { id: '$hold', hand: 'B', dx: 1, dy: -3 } });
  pz('take', 'f', { face: 'happy', A: [-5, 0], item: { id: '$hold', hand: 'A', dx: -5, dy: -3 } });
  pz('throw0', 'f', { face: 'right', B: [2, -7], item: { id: '$hold', hand: 'B', dx: -2, dy: -4 } });
  pz('throw1', 'f', { face: 'happy', B: [6, -2] });
  pz('catch0', 'f', { face: 'surprised', A: [-1, -7], B: [1, -7] });
  pz('catch1', 'f', { face: 'happy', A: [2, -4], B: [-2, -4], item: { id: 'letter', at: 'both', dy: -1 } });
  pz('fold0', 'f', { face: 'down', A: [3, 3], B: [-3, 3], item: { id: 'doc_write', at: 'both' } });
  pz('fold1', 'f', { face: 'down', A: [2, 3], B: [-2, 3], item: { id: 'letter', at: 'both' } });
  pz('place_low', 'f', { face: 'down', A: [3, 5], B: [-3, 5], item: { id: '$hold', at: 'both', dy: 2 } });
  pz('stamp_up', 'f', { B: [1, -8], item: { id: '$hold', hand: 'B', dx: -2, dy: -2 } });
  pz('stamp_mid', 'f', { face: 'closed', B: [-1, 0], item: { id: '$hold', hand: 'B', dx: -2, dy: -2 } });
  pz('stamp_down', 'f', { face: 'closed', bob: 1, B: [-3, 5], item: { id: '$hold', hand: 'B', dx: -2, dy: -2 } });
  pz('inspect0', 'f', { face: 'down', bob: 1, hy: 1, B: [-3, 3], item: { id: 'magnifier', hand: 'B', dx: -5, dy: -5 } });
  pz('inspect1', 'f', { face: 'down', bob: 1, hy: 1, hx: -1, B: [-6, 3], item: { id: 'magnifier', hand: 'B', dx: -5, dy: -5 } });
  pz('tick0', 'f', { face: 'down', A: [3, 2], B: [-2, 2], item: { id: 'clipboard', hand: 'A', dx: -1, dy: -6 }, item2: { id: 'pen', hand: 'B', dx: 0, dy: -3 } });
  pz('tick1', 'f', { face: 'down', A: [3, 2], B: [-1, 3], item: { id: 'clipboard', hand: 'A', dx: -1, dy: -6 }, item2: { id: 'pen', hand: 'B', dx: 0, dy: -3 } });
  pz('hold_clip0', 'f', { face: 'down', A: [3, 2], B: [-2, 2], item: { id: 'clipboard', hand: 'A', dx: -1, dy: -6 }, item2: { id: 'pen', hand: 'B', dx: 0, dy: -3 } });
  pz('hold_clip1', 'f', { face: 'normal', A: [3, 2], B: [-3, 4], item: { id: 'clipboard', hand: 'A', dx: -1, dy: -6 } });
  pz('lever_up', 'f', { face: 'right', B: [2, -6] });
  pz('lever_down', 'f', { face: 'happy', bob: 1, B: [2, 1] });
  pz('watch_r', 'f', { face: 'right', A: [1, 5], B: [-1, 5] });
  pz('crouch0', 'f', { face: 'down', legs: 'crouch', A: [-1, 5], B: [1, 5] });
  pz('crouch1', 'f', { face: 'down', legs: 'crouch', A: [1, 4], B: [-1, 6] });
  pz('gather0', 'f', { face: 'down', A: [3, 4], B: [-3, 4], item: { id: 'docs', at: 'both', dy: 1 } });
  pz('gather1', 'f', { face: 'happy', hy: 1, A: [3, 3], B: [-3, 3], item: { id: 'docs', at: 'both', dy: 1 } });
  pz('tidy0', 'f', { face: 'down', A: [3, 6], B: [-5, 4] });
  pz('tidy1', 'f', { face: 'down', A: [5, 4], B: [-3, 6] });
  pz('arms_crossed', 'f', { face: 'bored', A: [4, 3], B: [-4, 3] });
  pz('point_r', 'f', { face: 'right', B: [5, -3] });
  pz('talk', 'f', { face: 'talk', B: [-2, 2] });
  pz('shock', 'f', { face: 'surprised', A: [-2, -2], B: [2, -2] });

  // 正面坐姿（身体下沉 3 行，腿被桌子挡住）
  pz('sit', 'f', { sit: 1, A: [2, 6], B: [-2, 6] });
  pz('sit_b', 'f', { sit: 1, hy: 1, A: [2, 6], B: [-2, 6] });
  pz('type0', 'f', { sit: 1, face: 'down', A: [3, 6], B: [-3, 5] });
  pz('type1', 'f', { sit: 1, face: 'down', A: [3, 5], B: [-3, 6] });
  pz('think', 'f', { sit: 1, face: 'up', A: [3, 6], B: [-4, -1] });
  pz('think_b', 'f', { sit: 1, face: 'up', hx: 1, A: [3, 6], B: [-4, -1] });
  pz('tea0', 'f', { sit: 1, A: [2, 6], B: [-3, 3], item: { id: 'cup', hand: 'B', dx: -3, dy: -2 } });
  pz('tea1', 'f', { sit: 1, face: 'closed', hy: -1, A: [2, 6], B: [-4, 0], item: { id: 'cup', hand: 'B', dx: -3, dy: -2 } });
  pz('sit_stretch0', 'f', { sit: 1, face: 'closed', A: [-1, -6], B: [1, -6] });
  pz('sit_stretch1', 'f', { sit: 1, face: 'closed', hy: -1, A: [-2, -8], B: [2, -8] });
  pz('slump0', 'f', { sit: 1, headDown: true, hy: 5, A: [4, 6], B: [-4, 6] });
  pz('slump1', 'f', { sit: 1, headDown: true, hy: 4, A: [4, 6], B: [-4, 6] });
  pz('read_sit0', 'f', { sit: 1, face: 'down', A: [3, 3], B: [-3, 3], item: { id: '$hold', at: 'both', dy: 2 } });
  pz('read_sit1', 'f', { sit: 1, face: 'down', hy: 1, A: [3, 3], B: [-3, 3], item: { id: '$hold', at: 'both', dy: 2 } });
  pz('write0', 'f', { sit: 1, face: 'down', A: [3, 6], B: [-3, 5], item: { id: 'pen', hand: 'B', dx: 0, dy: -3 } });
  pz('write1', 'f', { sit: 1, face: 'down', A: [3, 6], B: [-2, 5], item: { id: 'pen', hand: 'B', dx: 0, dy: -3 } });
  pz('write2', 'f', { sit: 1, face: 'down', A: [3, 6], B: [-4, 6], item: { id: 'pen', hand: 'B', dx: 0, dy: -3 } });
  pz('sit_relax', 'f', { sit: 1, face: 'bored', A: [4, 4], B: [-4, 4] });
  pz('sit_relax_b', 'f', { sit: 1, face: 'blink', hy: 1, A: [4, 4], B: [-4, 4] });
  pz('sit_happy', 'f', { sit: 1, face: 'happy', A: [2, 6], B: [-2, 6] });
  pz('sit_up', 'f', { sit: 1, face: 'up', A: [2, 6], B: [-2, 6] });
  pz('sit_wait', 'f', { sit: 1, face: 'up', A: [4, 4], B: [-4, 4] });
  pz('sit_fold0', 'f', { sit: 1, face: 'down', A: [3, 4], B: [-3, 4], item: { id: 'doc_write', at: 'both' } });
  pz('sit_fold1', 'f', { sit: 1, face: 'happy', A: [2, 4], B: [-2, 4], item: { id: 'letter', at: 'both' } });
  pz('sit_card', 'f', { sit: 1, face: 'down', A: [3, 3], B: [-3, 3], item: { id: '$hold', at: 'both', dy: 1 } });
  pz('sit_scratch0', 'f', { sit: 1, face: 'worried', A: [2, 6], B: [-2, -8] });
  pz('sit_scratch1', 'f', { sit: 1, face: 'worried', hx: -1, A: [2, 6], B: [-1, -9] });

  // 侧面（朝右；朝左时整帧水平翻转）
  const SW = [[2, 4], [0, 5], [-2, 4], [0, 5]];
  const SR = [[3, 2], [0, 4], [-3, 3], [0, 4]];
  ['w0', 'w1', 'w2', 'w3'].forEach((l, i) => {
    pz('walk' + i, 's', { legs: l, bob: LEGS_S[l].bob, A: SW[i], B: SW[(i + 2) % 4], idle: true });
    pz('carry' + i, 's', { legs: l, bob: LEGS_S[l].bob, A: [3, 3], B: [3, 3], item: { id: '$hold', at: 'front' } });
    pz('push' + i, 's', { legs: l, bob: LEGS_S[l].bob, hx: 1, A: [4, 3], B: [4, 3] });
  });
  ['r0', 'r1', 'r2', 'r3'].forEach((l, i) => {
    pz('run' + i, 's', { legs: l, bob: LEGS_S[l].bob, hx: 1, A: SR[i], B: SR[(i + 2) % 4] });
  });
  pz('side', 's', { idle: true });
  pz('side_b', 's', { hy: 1, idle: true });
  pz('side_reach', 's', { A: [5, 0] });
  pz('side_place', 's', { face: 'down', A: [5, 2], item: { id: '$hold', at: 'front', dx: 4, dy: 1 } });
  pz('side_throw0', 's', { A: [-3, -5], item: { id: '$hold', hand: 'A', dx: -2, dy: -3 } });
  pz('side_throw1', 's', { face: 'happy', A: [6, -2] });

  // 背面（面向墙）
  pz('back', 'b', {});
  pz('back_b', 'b', { hy: 1 });
  pz('back_write0', 'b', { B: [-1, -8], item: { id: 'pen', hand: 'B', dx: 0, dy: -3 } });
  pz('back_write1', 'b', { B: [1, -8], item: { id: 'pen', hand: 'B', dx: 0, dy: -3 } });
  pz('back_write2', 'b', { B: [2, -7], item: { id: 'pen', hand: 'B', dx: 0, dy: -3 } });
  pz('back_pin0', 'b', { B: [0, -9], item: { id: '$hold', hand: 'B', dx: -1, dy: -4 } });
  pz('back_pin1', 'b', { A: [1, -9], B: [0, -9] });
  pz('back_post', 'b', { A: [2, -8], B: [-2, -8], item: { id: '$hold', at: 'both', dy: -1 } });
  pz('back_erase0', 'b', { B: [-3, -8], item: { id: 'eraser', hand: 'B', dx: -1, dy: -2 } });
  pz('back_erase1', 'b', { B: [3, -8], item: { id: 'eraser', hand: 'B', dx: -1, dy: -2 } });

  // 待机时手持角色物件的位置（相对 A 手）
  const IDLE_ITEM = {
    clipboard: { id: 'clipboard', f: [-4, -5], s: [-3, -5] },
    blueprint: { id: 'blueprint_v', f: [-2, -6], s: [-1, -6] },
    magnifier: { id: 'magnifier', f: [-4, 1], s: [-3, 1] },
    pen_red: { id: 'pen_red', f: [-2, -5], s: [-1, -5] }
  };

  function placeItem(g, id, it, handA, handB) {
    const d = bitmapDef(id);
    const w = d.rows[0].length, h = d.rows.length;
    let x, y;
    if (it.at === 'both') {
      const cx = (handA[0] + handB[0] + 2) / 2;
      x = Math.round(cx - w / 2) + (it.dx || 0);
      y = Math.max(handA[1], handB[1]) + 2 - h + (it.dy || 0);
    } else if (it.at === 'front') {
      x = handA[0] - Math.floor(w / 2) + 1 + (it.dx || 0);
      y = handA[1] + 3 - h + (it.dy || 0);
    } else {
      const hnd = it.hand === 'B' ? handB : handA;
      x = hnd[0] + (it.dx || 0);
      y = hnd[1] + (it.dy || 0);
    }
    blit(g, d.rows, x, y, d.map, it.flip);
    return [x, y, w, h];
  }

  function drawFace(g, view, face, hx, hy, map, glasses) {
    const set = P.CHAR.faces[view];
    const f = set[face] || set.normal;
    (f.s || []).forEach(([x, y]) => put(g, hx + x, hy + y, map.s));
    if (!glasses) (f.B || []).forEach(([x, y]) => put(g, hx + x, hy + y, map.B));
    (f.E || []).forEach(([x, y]) => put(g, hx + x, hy + y, map.E));
    (f.M || []).forEach(([x, y]) => put(g, hx + x, hy + y, map.M));
  }

  function sideLeg(g, hip, ank, pants, shoe) {
    linePts(hip[0], hip[1], ank[0], ank[1]).forEach((p) => blk(g, p[0], p[1], pants));
    for (let x = 0; x < 3; x++) {
      put(g, ank[0] + x, ank[1] + 2, shoe);
      put(g, ank[0] + x, ank[1] + 3, shoe);
    }
  }

  function composeChar(key, poseName, face, hold) {
    const sp = spriteSpec(key);
    const pose = POSES[poseName];
    if (!pose) throw new Error('未知姿势：' + poseName);
    const map = sp.map, role = sp.role, view = pose.v;
    const base = new Array(CW * CH).fill(null);
    const front = new Array(CW * CH).fill(null);
    const dy = pose.bob + (pose.sit ? 3 : 0) + (pose.legs === 'crouch' ? 4 : 0);
    const sleeve = map[sp.sleeve.color], sleeveShade = map[sp.sleeve.shade], skin = map.S;
    const outfit = P.CHAR.outfit[role.outfit];
    const headView = pose.headDown ? 'b' : view;
    const hx = 10 + pose.hx, hy = 16 + dy + pose.hy;
    const shA = view === 's' ? [15, 26 + dy] : [9, 26 + dy];
    const shB = view === 's' ? [13, 26 + dy] : [21, 26 + dy];
    const handA = pose.A ? [shA[0] + pose.A[0], shA[1] + pose.A[1]] : null;
    const handB = pose.B ? [shB[0] + pose.B[0], shB[1] + pose.B[1]] : null;

    // 后景：侧面的背包、远侧手臂、帽兜
    if (view === 's') {
      if (role.pack) blit(base, P.CHAR.pack.s.rows, P.CHAR.pack.s.x, P.CHAR.pack.s.y + dy, map);
      if (handB) {
        linePts(shB[0], shB[1], handB[0], handB[1]).forEach((p) => blk(base, p[0], p[1], sleeveShade));
        blk(base, handB[0], handB[1], map.s);
      }
    }
    // 腿
    if (view === 's') {
      const L = LEGS_S[pose.legs];
      if (!L) throw new Error('侧面腿部帧未定义：' + pose.legs);
      const pantsN = role.outfit === 'jumpsuit' ? map.C : map.P;
      const pantsF = role.outfit === 'jumpsuit' ? map.c : map.p;
      sideLeg(base, [13, 32 + pose.bob], L.f, pantsF, map.f);
      sideLeg(base, [15, 32 + pose.bob], L.n, pantsN, map.F);
    } else {
      const legs = P.CHAR.legs[pose.legs];
      if (!legs) throw new Error('腿部帧未定义：' + pose.legs);
      const lx = pose.legs === 'crouch' ? 10 : 11;
      const ly = pose.legs === 'sit' ? 35 : pose.legs === 'crouch' ? 35 : 32 + pose.bob;
      blit(base, legs, lx, ly, map);
    }
    // 躯干
    blit(base, outfit[view], view === 's' ? 12 : 11, 26 + dy, map);
    if (view === 'b' && role.pack) blit(base, P.CHAR.pack.b.rows, P.CHAR.pack.b.x, P.CHAR.pack.b.y + dy, map);
    if (role.hood && view !== 'b') {
      const hd = P.CHAR.hood[view];
      blit(base, hd.rows, hd.x, hd.y + dy, map);
    }
    // 头、发型、眼镜、表情、头部配件
    blit(base, P.CHAR.head[headView], hx, hy, map);
    blit(base, P.CHAR.hair[role.hair][headView], hx - 1, hy - 2, map);
    const glasses = role.acc.includes('glasses') && headView !== 'b';
    if (glasses) blit(base, P.CHAR.acc.glasses[headView], hx - 1, hy - 2, map);
    if (headView !== 'b') drawFace(base, headView, face || pose.face || 'normal', hx, hy, map, glasses);
    role.acc.forEach((a) => {
      if (a === 'glasses') return;
      blit(base, P.CHAR.acc[a][headView], hx - 1, hy - 2, map);
    });
    if (role.hood && view === 'b') blit(base, P.CHAR.hood.b.rows, P.CHAR.hood.b.x, P.CHAR.hood.b.y + dy, map);

    // 前景：袖子、手持物件、手
    const arms = view === 's' ? [[shA, handA]] : [[shA, handA], [shB, handB]];
    arms.forEach(([s, h]) => {
      if (!h) return;
      linePts(s[0], s[1], h[0], h[1]).forEach((p) => blk(front, p[0], p[1], sleeve));
    });
    // 审查者的袖标画在手臂中段
    if (role.armband && handA) {
      const bx = Math.round(shA[0] + (handA[0] - shA[0]) * 0.6);
      const by = Math.round(shA[1] + (handA[1] - shA[1]) * 0.6);
      blk(front, bx, by, map.K);
    }
    let itemRect = null;
    [pose.item, pose.item2].forEach((it) => {
      if (!it) return;
      const id = it.id === '$hold' ? hold : it.id;
      if (!id) return;
      const r = placeItem(front, id, it, handA || shA, handB || shB);
      if (!itemRect) itemRect = r;
    });
    if (pose.idle && role.idleItem && !pose.item && handA) {
      const ii = IDLE_ITEM[role.idleItem];
      const off = ii[view === 's' ? 's' : 'f'];
      if (view !== 'b') placeItem(front, ii.id, { hand: 'A', dx: off[0], dy: off[1] }, handA, handB || handA);
    }
    arms.forEach(([, h]) => { if (h) blk(front, h[0], h[1], skin); });

    // 描边：身体外轮廓用墨色；前景在身体上的边缘用下层颜色的暗色
    const baseOut = outlineGrid(base, CW, CH, PAL.ink);
    const frontOut = front.slice();
    for (let y = 0; y < CH; y++) {
      for (let x = 0; x < CW; x++) {
        const i = y * CW + x;
        if (front[i]) continue;
        if ((x > 0 && front[i - 1]) || (x < CW - 1 && front[i + 1]) || (y > 0 && front[i - CW]) || (y < CH - 1 && front[i + CW])) {
          frontOut[i] = baseOut[i] ? mix(baseOut[i], PAL.ink, 0.62) : PAL.ink;
        }
      }
    }
    return { base: gridCanvas(baseOut, CW, CH), front: gridCanvas(frontOut, CW, CH), item: itemRect, baseF: null, frontF: null };
  }

  const frameCache = new Map();
  P.charFrame = function charFrame(key, poseName, face, hold) {
    const ck = key + '|' + poseName + '|' + (face || '') + '|' + (hold || '');
    let f = frameCache.get(ck);
    if (!f) {
      f = composeChar(key, poseName, face, hold);
      frameCache.set(ck, f);
    }
    return f;
  };

  // ===========================================================================
  // 4. 动作帧序列

  const ANIMS = {};
  P.ANIMS = ANIMS;
  function an(name, frames, loop, still) {
    frames.forEach((fr) => { if (!POSES[fr[0]]) throw new Error('动作 ' + name + ' 使用了未定义的姿势 ' + fr[0]); });
    ANIMS[name] = { frames, loop: loop !== false, still: still || 0, total: frames.reduce((s, f) => s + f[1], 0) };
  }
  an('idle', [['stand', 1300], ['stand_b', 900]]);
  an('idle_happy', [['stand_happy', 900], ['stand_b', 700]]);
  an('stand_sad', [['stand_sad', 1000]]);
  an('look_l', [['look_l', 900], ['stand_b', 700]]);
  an('look_r', [['look_r', 900], ['stand_b', 700]]);
  an('look_up', [['look_up', 1000]]);
  an('walk', [['walk0', 95], ['walk1', 95], ['walk2', 95], ['walk3', 95]]);
  an('carry', [['carry0', 115], ['carry1', 115], ['carry2', 115], ['carry3', 115]]);
  an('run', [['run0', 85], ['run1', 85], ['run2', 85], ['run3', 85]]);
  an('push', [['push0', 170], ['push1', 170], ['push2', 170], ['push3', 170]]);
  an('side', [['side', 1200], ['side_b', 900]]);
  an('sit', [['sit', 1500], ['sit_b', 1000]]);
  an('type', [['type0', 110], ['type1', 110]]);
  an('think', [['think', 1100], ['think_b', 900]]);
  an('tea', [['tea0', 2000], ['tea1', 1000], ['tea0', 1600]]);
  an('stretch_sit', [['sit_stretch0', 260], ['sit_stretch1', 1100], ['sit_stretch0', 260]], false, 1);
  an('stretch', [['stretch0', 260], ['stretch1', 1100], ['stretch0', 260]], false, 1);
  an('slump', [['slump0', 1500], ['slump1', 1100]]);
  an('read_sit', [['read_sit0', 1000], ['read_sit1', 1000]]);
  an('read_stand', [['read_stand', 1000], ['read_stand_b', 1000]]);
  an('write', [['write0', 150], ['write1', 150], ['write2', 150], ['write1', 150]]);
  an('rummage', [['rummage0', 170], ['rummage1', 170]]);
  an('reach', [['reach_r0', 200], ['reach_r1', 500]], false, 1);
  an('grab_folder', [['grab_folder', 700]], false);
  an('magnify', [['magnify', 700], ['magnify_b', 700]]);
  an('lever', [['lever_up', 450], ['lever_down', 450]], false, 1);
  an('watch_r', [['watch_r', 1000], ['look_r', 800]]);
  an('shake', [['shake0', 150], ['shake1', 150], ['shake0', 150], ['shake1', 150], ['stand_sad', 500]], false, 0);
  an('throw', [['throw0', 450], ['throw1', 550]], false, 1);
  an('side_throw', [['side_throw0', 400], ['side_throw1', 500]], false, 1);
  an('catch', [['catch0', 400], ['catch1', 800]], false, 1);
  an('fold', [['fold0', 500], ['fold1', 600]], false, 1);
  an('sit_fold', [['sit_fold0', 600], ['sit_fold1', 600]], false, 1);
  an('place', [['place_low', 700]], false);
  an('side_place', [['side_place', 700]], false);
  an('side_reach', [['side_reach', 600]], false);
  an('scratch', [['scratch0', 180], ['scratch1', 180]]);
  an('sit_scratch', [['sit_scratch0', 180], ['sit_scratch1', 180]]);
  an('stamp', [['stamp_up', 380], ['stamp_mid', 70], ['stamp_down', 450], ['stamp_up', 300], ['stamp_mid', 70], ['stamp_down', 520]], false, 2);
  an('stamp_once', [['stamp_up', 400], ['stamp_mid', 70], ['stamp_down', 650]], false, 2);
  an('inspect', [['inspect0', 520], ['inspect1', 520]]);
  an('tick', [['tick0', 260], ['tick1', 260]]);
  an('hold_clip', [['hold_clip0', 300], ['hold_clip1', 900]]);
  an('board_write', [['back_write0', 170], ['back_write1', 170], ['back_write2', 170], ['back_write1', 170]]);
  an('board_pin', [['back_post', 700], ['back_pin1', 600]], false, 0);
  an('note_pin', [['back_pin0', 500], ['back_pin1', 600]], false, 0);
  an('board_erase', [['back_erase0', 130], ['back_erase1', 130]]);
  an('back', [['back', 1200], ['back_b', 900]]);
  an('wait', [['wait0', 320], ['wait1', 320]]);
  an('hold_sign', [['hold_sign', 900], ['hold_sign_b', 900]]);
  an('hold_form', [['hold_form', 900], ['hold_form_b', 900]]);
  an('hold_ticket', [['hold_ticket', 1100], ['hold_ticket_b', 1000]]);
  an('carry_f', [['carry_f', 1000]]);
  an('cheer', [['cheer0', 260], ['cheer1', 260]]);
  an('crouch', [['crouch0', 300], ['crouch1', 300]]);
  an('gather', [['gather0', 500], ['gather1', 500]]);
  an('tidy', [['tidy0', 260], ['tidy1', 260]]);
  an('sit_relax', [['sit_relax', 1700], ['sit_relax_b', 1300]]);
  an('sit_happy', [['sit_happy', 1000], ['sit_b', 700]]);
  an('sit_up', [['sit_up', 1000]]);
  an('sit_wait', [['sit_wait', 900], ['sit_relax_b', 900]]);
  an('sit_card', [['sit_card', 1000]]);
  an('puzzled', [['puzzled', 900], ['puzzled_b', 900]]);
  an('freeze', [['stand', 1000]]);
  an('give', [['give', 600], ['give_b', 600]], false);
  an('take', [['take', 600]], false);
  an('arms_crossed', [['arms_crossed', 1300], ['wait1', 300]]);
  an('point_r', [['point_r', 800]]);
  an('shock', [['shock', 600]], false);
  an('talk', [['talk', 240], ['stand', 240]]);

  function animFrame(animName, elapsed, reduced) {
    const a = ANIMS[animName];
    if (!a) throw new Error('未知动作帧序列：' + animName);
    if (reduced) return a.frames[a.still][0];
    let t = a.loop ? elapsed % a.total : Math.min(elapsed, a.total - 1);
    for (const fr of a.frames) {
      if (t < fr[1]) return fr[0];
      t -= fr[1];
    }
    return a.frames[a.frames.length - 1][0];
  }
  P.animFrame = animFrame;
  P.animDuration = (name) => {
    const a = ANIMS[name];
    if (!a) throw new Error('未知动作帧序列：' + name);
    return a.total;
  };

  // ===========================================================================
  // 5. 缓动

  P.ease = {
    linear: (t) => t,
    inOut: (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2),
    out: (t) => 1 - Math.pow(1 - t, 3),
    in: (t) => t * t * t,
    outBack: (t) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
    bounce: (t) => {
      const n1 = 7.5625, d1 = 2.75;
      if (t < 1 / d1) return n1 * t * t;
      if (t < 2 / d1) { t -= 1.5 / d1; return n1 * t * t + 0.75; }
      if (t < 2.5 / d1) { t -= 2.25 / d1; return n1 * t * t + 0.9375; }
      t -= 2.625 / d1; return n1 * t * t + 0.984375;
    }
  };

  function hash(n) {
    let x = (n | 0) * 374761393 + 668265263;
    x = (x ^ (x >>> 13)) * 1274126177;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967296;
  }
  P.hash = hash;

  // ===========================================================================
  // 6. 画面：画布缩放、动画循环、小人与脚本、粒子、飞行物、定时器

  P.reducedMotion = function reducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  };

  P.createScene = function createScene(canvas, spec) {
    if (!canvas || canvas.tagName !== 'CANVAS') throw new Error('像素画面需要 canvas 元素');
    if (!spec || !spec.W || !spec.H || typeof spec.draw !== 'function') throw new Error('像素画面缺少 W、H 或 draw');
    const ctx = canvas.getContext('2d');
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const scene = {
      canvas, ctx, W: spec.W, H: spec.H,
      realT: 0, animT: 0, scale: 1, reduced: mq.matches, frozen: false, destroyed: false,
      actors: [], particles: [], flyers: [], timers: [], tweens: [],
      lastDraw: -1e9, spec
    };

    // 画面填满容器宽度：按不小于显示尺寸（设备像素）的整数倍渲染，再用 pixelated 缩放到容器宽度
    scene.resize = function resize() {
      const parent = canvas.parentElement;
      if (!parent) throw new Error('像素画面的 canvas 需要放在容器里');
      const cs = getComputedStyle(parent);
      const avail = Math.max(40, parent.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
      const dpr = window.devicePixelRatio || 1;
      const k = Math.max(1, Math.ceil((avail * dpr) / scene.W - 1e-6));
      const bw = scene.W * k, bh = scene.H * k;
      if (canvas.width !== bw || canvas.height !== bh) {
        canvas.width = bw;
        canvas.height = bh;
      }
      canvas.style.display = 'block';
      canvas.style.width = '100%';
      canvas.style.height = 'auto';
      canvas.style.imageRendering = 'pixelated';
      scene.scale = k;
      scene.cssScale = avail / scene.W;
      scene.lastDraw = -1e9;
    };

    // 改变画面的逻辑尺寸（楼的层数变化时使用）
    scene.setSize = function setSize(w, h) {
      if (!(w > 0 && h > 0)) throw new Error('画面尺寸无效：' + w + '×' + h);
      if (scene.W === w && scene.H === h) return;
      scene.W = w;
      scene.H = h;
      scene.resize();
    };

    scene.addActor = function addActor(o) {
      const a = {
        id: o.id, sprite: o.sprite, x: o.x, y: o.y, facing: o.facing || 1,
        anim: o.anim || 'idle', animStart: 0, clock: 0, seed: Math.floor(hash(scene.actors.length + 7) * 3000),
        hold: o.hold || null, face: null, alpha: o.alpha === undefined ? 1 : o.alpha, dim: 1,
        visible: o.visible !== false, seat: null, script: null, step: null, icon: null, sign: null, bubble: null,
        speed: o.speed || 84, shadow: o.shadow !== false, data: o.data || {}
      };
      scene.actors.push(a);
      return a;
    };
    scene.removeActor = function removeActor(a) {
      if (a.script && a.script.finalize) a.script.finalize();
      scene.actors = scene.actors.filter((x) => x !== a);
    };

    scene.play = function play(a, animName, restart) {
      if (!ANIMS[animName]) throw new Error('未知动作帧序列：' + animName);
      if (a.anim !== animName || restart) {
        a.anim = animName;
        a.animStart = a.clock;
      }
    };

    // 脚本：一组依次执行的步骤；新脚本取代旧脚本，旧脚本的 finalize 负责把房间状态补到最终结果。
    // tail 为可以被打断的部分的起点：关键步骤做完之后的步骤，以及明确标出的收尾步骤（例如走回工位）
    scene.run = function run(a, steps, opts) {
      if (a.script && a.script.finalize) a.script.finalize();
      const explicit = opts && opts.tail !== undefined && opts.tail !== null ? opts.tail : steps.length;
      const key = steps.findIndex((s) => s.key);
      const tail = Math.min(explicit, key >= 0 ? key + 1 : steps.length);
      a.script = { steps: steps.slice(), i: 0, tail, finalize: opts && opts.finalize, onDone: opts && opts.onDone };
      a.step = null;
    };
    scene.inTail = (a) => !a.script || a.script.i >= a.script.tail;
    scene.cancel = function cancel(a) {
      if (a.script && a.script.finalize) a.script.finalize();
      a.script = null;
      a.step = null;
    };

    function startStep(a, st) {
      a.step = { st, t0: scene.realT, fromX: a.x, fromY: a.y };
      const reduced = scene.reduced;
      switch (st.t) {
        case 'go': {
          const dx = st.x - a.x, dy = st.y - a.y;
          const dist = Math.hypot(dx, dy);
          if (Math.abs(dx) > 0.5) a.facing = dx > 0 ? 1 : -1;
          a.step.dur = reduced || dist < 0.5 ? 0 : (dist / (st.speed || a.speed)) * 1000;
          scene.play(a, st.gait || 'walk');
          a.seat = null;
          break;
        }
        case 'anim':
          scene.play(a, st.name, true);
          if (st.facing) a.facing = st.facing;
          a.step.dur = reduced ? (st.key ? Math.max(st.ms || 0, 1600) : 0) : (st.ms !== undefined ? st.ms : ANIMS[st.name].total);
          break;
        case 'wait':
          a.step.dur = reduced ? (st.key ? Math.max(st.ms, 1600) : 0) : st.ms;
          break;
        case 'fade':
          a.step.from = a.alpha;
          a.step.dur = reduced ? 0 : st.ms;
          break;
        case 'until':
          if (st.name) scene.play(a, st.name);
          a.step.dur = st.max;
          break;
        default:
          a.step.dur = 0;
      }
    }

    function updateActor(a, dt) {
      if (!scene.reduced && !scene.frozen) a.clock += dt;
      if (scene.frozen || !a.script) return;
      let guard = 0;
      while (a.script && guard++ < 40) {
        if (!a.step) {
          const st = a.script.steps[a.script.i];
          if (!st) {
            const done = a.script.onDone;
            a.script = null;
            if (done) done();
            return;
          }
          startStep(a, st);
          if (st.t === 'call') st.fn(a);
          if (st.t === 'hold') a.hold = st.item;
          if (st.t === 'turn') a.facing = st.facing;
          if (st.t === 'icon') a.icon = st.icon ? Object.assign({ t0: scene.realT }, st.icon) : null;
          if (st.t === 'seat') a.seat = st.seat;
        }
        const s = a.step;
        const el = scene.realT - s.t0;
        const k = s.dur > 0 ? Math.min(1, el / s.dur) : 1;
        if (s.st.t === 'go') {
          a.x = s.fromX + (s.st.x - s.fromX) * k;
          a.y = s.fromY + (s.st.y - s.fromY) * k;
        } else if (s.st.t === 'fade') {
          a.alpha = s.from + (s.st.to - s.from) * k;
        }
        const untilOk = s.st.t === 'until' && s.st.test();
        if (k >= 1 || untilOk) {
          a.step = null;
          a.script.i++;
          continue;
        }
        return;
      }
    }

    // 粒子
    scene.emit = function emit(kind, x, y, n, o) {
      if (scene.reduced) return;
      const opt = o || {};
      for (let i = 0; i < n; i++) {
        const r1 = Math.random(), r2 = Math.random(), r3 = Math.random();
        const p = { kind, x, y, vx: 0, vy: 0, g: 0, life: 800, age: 0, size: 1, color: PAL.white, drag: 1 };
        switch (kind) {
          case 'dust':
            p.vx = (r1 - 0.5) * 70; p.vy = -r2 * 30 - 6; p.g = 90; p.life = 420 + r3 * 250;
            p.color = r3 > 0.5 ? PAL.paper3 : PAL.white2; p.size = r2 > 0.6 ? 2 : 1;
            break;
          case 'confetti':
            p.x = x + (r1 - 0.5) * (opt.spread || 120); p.y = y - r2 * 20;
            p.vx = (r2 - 0.5) * 20; p.vy = 10 + r3 * 20; p.g = 8; p.life = 2200 + r1 * 1200;
            p.color = [PAL.red2, PAL.yellow2, PAL.blue2, PAL.green2, PAL.pink2, PAL.orange2][Math.floor(r3 * 6)];
            p.size = 2; p.sway = r1 * 6.28;
            break;
          case 'smoke':
            p.x = x + (r1 - 0.5) * 6; p.vx = (r2 - 0.5) * 8; p.vy = -12 - r3 * 10; p.life = 1400 + r1 * 700; p.size = r2 > 0.5 ? 2 : 1;
            break;
          case 'spark':
            p.vx = Math.cos(r1 * 6.28) * (20 + r2 * 25); p.vy = Math.sin(r1 * 6.28) * (20 + r2 * 25); p.life = 380 + r3 * 200;
            p.color = r3 > 0.5 ? PAL.yellow1 : PAL.white;
            break;
          case 'steam':
            p.x = x + (r1 - 0.5) * 3; p.vx = (r2 - 0.5) * 3; p.vy = -6 - r3 * 4; p.life = 900 + r1 * 400; p.color = PAL.white2;
            break;
          case 'paper':
            p.vx = (r1 - 0.5) * 90; p.vy = -30 - r2 * 40; p.g = 110; p.life = 900 + r3 * 400; p.color = PAL.white; p.size = 3; p.drag = 0.96;
            p.floor = opt.floor;
            break;
          case 'glow':
            p.vx = (r1 - 0.5) * 8; p.vy = -r2 * 10; p.life = 600; p.color = opt.color || PAL.yellow1; p.size = 1;
            break;
          default:
            throw new Error('未知粒子：' + kind);
        }
        if (opt.color && kind !== 'confetti') p.color = opt.color;
        scene.particles.push(p);
      }
    };

    function updateParticles(dt) {
      if (scene.frozen) return;
      const s = dt / 1000;
      scene.particles.forEach((p) => {
        p.age += dt;
        p.vy += p.g * s;
        p.vx *= p.drag; p.vy *= p.drag;
        p.x += p.vx * s; p.y += p.vy * s;
        if (p.kind === 'confetti') p.x += Math.sin(p.age / 180 + p.sway) * 0.4;
        if (p.floor !== undefined && p.y > p.floor) { p.y = p.floor; p.vy = 0; p.vx *= 0.5; }
      });
      scene.particles = scene.particles.filter((p) => p.age < p.life);
    }

    scene.drawParticles = function drawParticles(c) {
      scene.particles.forEach((p) => {
        const k = 1 - p.age / p.life;
        if (p.kind === 'smoke') {
          const r = 2 + Math.floor((p.age / p.life) * 5);
          const x = Math.round(p.x), y = Math.round(p.y);
          c.fillStyle = P.rgba('#5c606b', 0.75 * k);
          c.fillRect(x - r, y - r + 1, r * 2, r * 2 - 2);
          c.fillRect(x - r + 1, y - r, r * 2 - 2, r * 2);
          c.fillStyle = P.rgba('#a9adb6', 0.7 * k);
          c.fillRect(x - r + 1, y - r + 1, r * 2 - 3, r - 1);
          return;
        }
        if (p.kind === 'paper') {
          c.fillStyle = PAL.ink;
          c.fillRect(Math.round(p.x) - 2, Math.round(p.y) - 1, 5, 3);
          c.fillStyle = (Math.floor(p.age / 90) % 2) ? PAL.white : PAL.white2;
          c.fillRect(Math.round(p.x) - 1, Math.round(p.y), 3, 1);
          return;
        }
        c.globalAlpha = p.kind === 'confetti' ? Math.min(1, k * 3) : k;
        c.fillStyle = p.color;
        c.fillRect(Math.round(p.x), Math.round(p.y), p.size, p.size);
        c.globalAlpha = 1;
      });
    };

    // 飞行物：纸飞机、纸团、信件等沿弧线飞行
    scene.fly = function fly(o) {
      if (scene.reduced) {
        if (o.onDone) scene.after(0, o.onDone);
        return null;
      }
      const f = Object.assign({ t0: scene.realT, arc: 10, ms: 900, ease: 'inOut', frames: null, alpha: 1 }, o);
      scene.flyers.push(f);
      return f;
    };
    function updateFlyers() {
      if (scene.frozen) return;
      scene.flyers.forEach((f) => {
        const k = Math.min(1, (scene.realT - f.t0) / f.ms);
        f.k = k;
        if (k >= 1 && !f.done) {
          f.done = true;
          if (f.onDone) f.onDone();
        }
      });
      scene.flyers = scene.flyers.filter((f) => !f.done || f.keep);
    }
    scene.flyerPos = function flyerPos(f) {
      const e = P.ease[f.ease](f.k || 0);
      const x = f.from[0] + (f.to[0] - f.from[0]) * e;
      const y = f.from[1] + (f.to[1] - f.from[1]) * e - Math.sin(Math.PI * e) * f.arc;
      return [x, y];
    };
    scene.drawFlyers = function drawFlyers(c) {
      scene.flyers.forEach((f) => {
        const [x, y] = scene.flyerPos(f);
        if (f.draw) { f.draw(c, x, y, f.k || 0); return; }
        const frames = f.frames || [f.bmp];
        const name = frames[Math.floor(scene.animT / 140) % frames.length];
        const b = P.bitmap(name);
        P.drawBitmap(c, name, x - b.w / 2, y - b.h / 2, { flip: f.flip, alpha: f.alpha });
      });
    };

    // 定时器与数值补间（按真实时间推进）
    scene.after = function after(ms, fn) {
      scene.timers.push({ at: scene.realT + ms, fn });
    };
    scene.tween = function tween(obj, key, to, ms, ease) {
      scene.tweens = scene.tweens.filter((tw) => !(tw.obj === obj && tw.key === key));
      if (scene.reduced || ms <= 0) {
        obj[key] = to;
        return;
      }
      scene.tweens.push({ obj, key, from: obj[key], to, t0: scene.realT, ms, ease: ease || 'inOut' });
    };
    function updateTimers() {
      const due = scene.timers.filter((tm) => tm.at <= scene.realT);
      scene.timers = scene.timers.filter((tm) => tm.at > scene.realT);
      due.forEach((tm) => tm.fn());
      scene.tweens.forEach((tw) => {
        const k = Math.min(1, (scene.realT - tw.t0) / tw.ms);
        tw.obj[tw.key] = tw.from + (tw.to - tw.from) * P.ease[tw.ease](k);
        tw.done = k >= 1;
      });
      scene.tweens = scene.tweens.filter((tw) => !tw.done);
    }

    let last = performance.now();
    function frame(now) {
      if (scene.destroyed) return;
      const dt = Math.min(50, Math.max(0, now - last));
      last = now;
      // paused 为不在视口内的画面（动作图鉴中滚出屏幕的小画布），暂停推进与绘制
      if (scene.paused) {
        scene.raf = requestAnimationFrame(frame);
        return;
      }
      scene.realT += dt;
      if (!scene.frozen && !scene.reduced) scene.animT += dt;
      updateTimers();
      scene.actors.slice().forEach((a) => updateActor(a, dt));
      updateParticles(dt);
      updateFlyers();
      if (spec.update) spec.update(scene, dt);
      const interval = scene.reduced ? 250 : (spec.interval || 0);
      if (scene.realT - scene.lastDraw >= interval) {
        scene.lastDraw = scene.realT;
        draw();
      }
      scene.raf = requestAnimationFrame(frame);
    }

    function draw() {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(scene.scale, 0, 0, scene.scale, 0, 0);
      ctx.imageSmoothingEnabled = false;
      P.currentScale = scene.scale;
      spec.draw(scene, ctx);
    }
    scene.drawNow = draw;

    function onMotionChange() {
      scene.reduced = mq.matches;
      scene.lastDraw = -1e9;
      if (spec.onReducedChange) spec.onReducedChange(scene);
    }
    mq.addEventListener('change', onMotionChange);

    const ro = new ResizeObserver(() => scene.resize());
    ro.observe(canvas.parentElement);

    scene.destroy = function destroy() {
      scene.destroyed = true;
      cancelAnimationFrame(scene.raf);
      ro.disconnect();
      mq.removeEventListener('change', onMotionChange);
    };

    scene.resize();
    scene.raf = requestAnimationFrame(frame);
    return scene;
  };

  // ===========================================================================
  // 7. 绘制小人、头顶图标、气泡、牌子、印章、箭头

  P.drawShadow = function drawShadow(c, x, y, w) {
    const hw = Math.round((w || 12) / 2);
    c.fillStyle = PAL.shadow;
    c.fillRect(Math.round(x) - hw, Math.round(y) - 1, hw * 2, 2);
    c.fillRect(Math.round(x) - hw + 2, Math.round(y) + 1, hw * 2 - 4, 1);
  };

  P.actorFrame = function actorFrame(scene, a) {
    const poseName = animFrame(a.anim, a.clock - a.animStart, scene.reduced);
    const pose = POSES[poseName];
    let face = a.face;
    if (!face && !scene.reduced && !scene.frozen && (!pose.face || pose.face === 'normal') && ((a.clock + a.seed) % 3600) < 140) face = 'blink';
    return { poseName, pose, fr: P.charFrame(a.sprite, poseName, face, a.hold) };
  };

  P.drawActor = function drawActor(c, scene, a, part) {
    if (!a.visible || a.alpha <= 0.01) return null;
    const info = P.actorFrame(scene, a);
    const fr = info.fr;
    const x = Math.round(a.x) - 16, y = Math.round(a.y) - 38;
    const flip = a.facing < 0;
    if (flip && !fr.baseF) { fr.baseF = flipCanvas(fr.base); fr.frontF = flipCanvas(fr.front); }
    const alpha = a.alpha * a.dim;
    if (alpha < 1) c.globalAlpha = alpha;
    if (part !== 'front') {
      if (a.shadow && !info.pose.sit && part !== 'base-noshadow') P.drawShadow(c, a.x, a.y, 12);
      c.drawImage(flip ? fr.baseF : fr.base, x, y);
    }
    if (part !== 'base' && part !== 'base-noshadow') c.drawImage(flip ? fr.frontF : fr.front, x, y);
    if (alpha < 1) c.globalAlpha = 1;
    return info;
  };

  // 头顶位置：头发最高处上方
  P.headTop = function headTop(scene, a) {
    const info = P.actorFrame(scene, a);
    const p = info.pose;
    const dy = p.bob + (p.sit ? 3 : 0) + (p.legs === 'crouch' ? 4 : 0) + p.hy;
    return [Math.round(a.x), Math.round(a.y) - 38 + 14 + dy];
  };

  // 手持物件在画面中的位置（号码牌上的数字等）
  P.itemRect = function itemRect(scene, a) {
    const info = P.actorFrame(scene, a);
    const r = info.fr.item;
    if (!r) return null;
    const flip = a.facing < 0;
    const x = flip ? CW - r[0] - r[2] : r[0];
    return [Math.round(a.x) - 16 + x, Math.round(a.y) - 38 + r[1], r[2], r[3]];
  };

  function textFont(size, weight) { return (weight || 500) + ' ' + size + 'px ' + FONT; }
  P.measure = function measure(c, str, size, weight) {
    c.font = textFont(size || 8, weight);
    return c.measureText(String(str)).width;
  };
  function fitText(c, s, max) {
    if (c.measureText(s).width <= max) return s;
    let t = s;
    while (t.length > 1 && c.measureText(t + '…').width > max) t = t.slice(0, -1);
    return t + '…';
  }
  P.fitText = function (c, s, max, size, weight) { c.font = textFont(size || 8, weight); return fitText(c, String(s), max); };

  P.text = function text(c, str, x, y, o) {
    const opt = o || {};
    c.font = textFont(opt.size || 8, opt.weight);
    c.textAlign = opt.align || 'left';
    c.textBaseline = opt.base || 'middle';
    let s = String(str);
    if (opt.max) s = fitText(c, s, opt.max);
    if (opt.outline) {
      c.lineJoin = 'round';
      c.lineWidth = opt.outlineW || 2;
      c.strokeStyle = opt.outline;
      c.strokeText(s, x, y);
    }
    if (opt.glow) {
      c.shadowColor = opt.glow;
      c.shadowBlur = (opt.glowR || 3) * (P.currentScale || 1);
    }
    c.fillStyle = opt.color || PAL.ink;
    c.fillText(s, x, y);
    if (opt.glow) { c.shadowBlur = 0; c.shadowColor = 'transparent'; }
    return c.measureText(s).width;
  };

  // 3×5 像素数字
  P.pixText = function pixText(c, str, x, y, color, align) {
    const s = String(str);
    let w = 0;
    for (const ch of s) w += (P.FONT3[ch] ? 4 : 0);
    w = Math.max(0, w - 1);
    let cx = Math.round(align === 'center' ? x - w / 2 : align === 'right' ? x - w : x);
    c.fillStyle = color;
    for (const ch of s) {
      const g = P.FONT3[ch];
      if (!g) continue;
      for (let r = 0; r < 5; r++) for (let q = 0; q < 3; q++) if (g[r][q] === '1') c.fillRect(cx + q, Math.round(y) + r, 1, 1);
      cx += 4;
    }
    return w;
  };

  // 像素圆角框：外边墨色、内部填色、上沿高光
  P.box = function box(c, x, y, w, h, fill, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y); w = Math.round(w); h = Math.round(h);
    c.fillStyle = opt.ink || PAL.ink;
    c.fillRect(x + 1, y, w - 2, h);
    c.fillRect(x, y + 1, w, h - 2);
    c.fillStyle = fill;
    c.fillRect(x + 1, y + 1, w - 2, h - 2);
    if (opt.hi) { c.fillStyle = opt.hi; c.fillRect(x + 2, y + 1, w - 4, 1); }
    if (opt.lo) { c.fillStyle = opt.lo; c.fillRect(x + 2, y + h - 2, w - 4, 1); }
  };

  // 气泡：say 为说话气泡（三角尾巴），think 为思考气泡（小圆点尾巴）
  P.bubble = function bubble(c, x, y, w, h, o) {
    const opt = o || {};
    const fill = opt.fill || PAL.white;
    P.box(c, x, y, w, h, fill, { lo: PAL.white2 });
    const tx = Math.round(opt.tx !== undefined ? opt.tx : x + w / 2);
    if (opt.kind === 'think') {
      c.fillStyle = PAL.ink; c.fillRect(tx - 2, y + h + 1, 4, 3); c.fillRect(tx - 1, y + h, 2, 5);
      c.fillStyle = fill; c.fillRect(tx - 1, y + h + 1, 2, 3);
      c.fillStyle = PAL.ink; c.fillRect(tx - 4, y + h + 5, 3, 3);
      c.fillStyle = fill; c.fillRect(tx - 3, y + h + 6, 1, 1);
    } else {
      c.fillStyle = PAL.ink;
      c.fillRect(tx - 3, y + h - 1, 7, 1); c.fillRect(tx - 2, y + h, 5, 1); c.fillRect(tx - 1, y + h + 1, 3, 1); c.fillRect(tx, y + h + 2, 1, 1);
      c.fillStyle = fill;
      c.fillRect(tx - 2, y + h - 1, 5, 1); c.fillRect(tx - 1, y + h, 3, 1); c.fillRect(tx, y + h + 1, 1, 1);
    }
  };

  // 牌子：cx 为中心，bottom 为牌子下沿；pole 为下方手柄长度，nail 为挂绳的钉子高度
  P.sign = function sign(c, cx, bottom, str, o) {
    const opt = o || {};
    const size = opt.size || 7;
    const lines = String(str).split('\n');
    c.font = textFont(size, 600);
    const maxW = opt.maxW || 200;
    const texts = lines.map((s) => fitText(c, s, maxW - 8));
    const tw = Math.max(...texts.map((s) => c.measureText(s).width));
    const w = Math.round(Math.max(opt.minW || 18, tw + 8));
    const lh = size + 2;
    const h = Math.round(lines.length * lh + 5);
    const x = Math.round(cx - w / 2), y = Math.round(bottom - h);
    if (opt.nail !== undefined) {
      c.fillStyle = opt.string || PAL.wood4;
      P.linePts(x + 3, y, Math.round(cx), Math.round(opt.nail)).forEach((p) => c.fillRect(p[0], p[1], 1, 1));
      P.linePts(x + w - 4, y, Math.round(cx), Math.round(opt.nail)).forEach((p) => c.fillRect(p[0], p[1], 1, 1));
      c.fillStyle = PAL.metal3; c.fillRect(Math.round(cx) - 1, Math.round(opt.nail) - 1, 2, 2);
    }
    if (opt.pole) {
      c.fillStyle = PAL.ink; c.fillRect(Math.round(cx) - 2, bottom - 1, 4, opt.pole + 1);
      c.fillStyle = PAL.wood2; c.fillRect(Math.round(cx) - 1, bottom - 1, 2, opt.pole);
    }
    P.box(c, x, y, w, h, opt.bg || PAL.paper, { hi: opt.hi || PAL.white, lo: opt.lo || P.mix(opt.bg || PAL.paper, PAL.ink, 0.18) });
    if (opt.stripe) { c.fillStyle = opt.stripe; c.fillRect(x + 1, y + 1, 2, h - 2); }
    texts.forEach((s, i) => P.text(c, s, cx + (opt.stripe ? 1 : 0), y + 3 + i * lh + size / 2, { size, weight: 600, align: 'center', color: opt.fg || PAL.ink }));
    return { x, y, w, h };
  };

  // 门牌与举牌的配色：按牌上的文字决定
  P.signStyle = function signStyle(text) {
    const s = String(text || '');
    if (/中断/.test(s)) return { bg: '#3d4250', fg: PAL.white, stripe: PAL.grey2 };
    if (/待恢复/.test(s)) return { bg: PAL.yellow2, fg: PAL.ink, stripe: PAL.orange2 };
    if (/待核实/.test(s)) return { bg: PAL.yellow1, fg: PAL.ink, stripe: PAL.yellow3 };
    if (/暂停/.test(s)) return { bg: PAL.blue1, fg: PAL.ink, stripe: PAL.blue2 };
    if (/失败|不通过/.test(s)) return { bg: PAL.red2, fg: PAL.white, stripe: PAL.red3 };
    if (/完成|通过|放行/.test(s)) return { bg: PAL.green2, fg: PAL.white, stripe: PAL.green3 };
    if (/取消/.test(s)) return { bg: PAL.grey1, fg: PAL.ink, stripe: PAL.grey3 };
    if (/不确定/.test(s)) return { bg: PAL.yellow1, fg: PAL.ink, stripe: PAL.yellow3 };
    return { bg: PAL.paper, fg: PAL.ink, stripe: PAL.paper3 };
  };

  // 印章印记
  P.stampMark = function stampMark(c, cx, cy, str, color, o) {
    const opt = o || {};
    const size = opt.size || 7;
    c.save();
    c.translate(Math.round(cx), Math.round(cy));
    c.rotate(opt.rot === undefined ? -0.14 : opt.rot);
    c.globalAlpha = opt.alpha === undefined ? 1 : opt.alpha;
    c.font = textFont(size, 800);
    const w = Math.round(c.measureText(str).width + 6), h = size + 5;
    c.fillStyle = color;
    c.fillRect(-w / 2, -h / 2, w, 1); c.fillRect(-w / 2, h / 2 - 1, w, 1);
    c.fillRect(-w / 2, -h / 2, 1, h); c.fillRect(w / 2 - 1, -h / 2, 1, h);
    c.fillRect(-w / 2 + 2, -h / 2 + 2, w - 4, 1); c.fillRect(-w / 2 + 2, h / 2 - 3, w - 4, 1);
    c.textAlign = 'center'; c.textBaseline = 'middle';
    c.fillText(str, 0, 0.5);
    c.restore();
  };

  // 箭头：减少动画时表示交接
  P.arrow = function arrow(c, pts, color, o) {
    const opt = o || {};
    c.fillStyle = PAL.ink;
    const all = [];
    for (let i = 0; i < pts.length - 1; i++) {
      const seg = P.linePts(Math.round(pts[i][0]), Math.round(pts[i][1]), Math.round(pts[i + 1][0]), Math.round(pts[i + 1][1]));
      seg.forEach((p, j) => all.push(p));
    }
    all.forEach((p, j) => { if (!opt.dash || (j % 6) < 4) c.fillRect(p[0] - 1, p[1] - 1, 3, 3); });
    c.fillStyle = color;
    all.forEach((p, j) => { if (!opt.dash || (j % 6) < 4) c.fillRect(p[0], p[1], 1, 1); });
    const a = pts[pts.length - 2], b = pts[pts.length - 1];
    const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
    const tip = [Math.round(b[0]), Math.round(b[1])];
    for (let s = -1; s <= 1; s += 2) {
      const ex = Math.round(b[0] - Math.cos(ang + s * 0.6) * 6), ey = Math.round(b[1] - Math.sin(ang + s * 0.6) * 6);
      const seg = P.linePts(tip[0], tip[1], ex, ey);
      c.fillStyle = PAL.ink; seg.forEach((p) => c.fillRect(p[0] - 1, p[1] - 1, 3, 3));
      c.fillStyle = color; seg.forEach((p) => c.fillRect(p[0], p[1], 1, 1));
    }
  };

  // 沙漏
  P.hourglass = function hourglass(c, x, y, t) {
    const phase = (t % 2400) / 2400;
    x = Math.round(x); y = Math.round(y);
    c.fillStyle = PAL.ink; c.fillRect(x - 1, y - 1, 9, 13);
    c.fillStyle = PAL.wood2; c.fillRect(x - 1, y - 1, 9, 2); c.fillRect(x - 1, y + 10, 9, 2);
    const glass = PAL.glass;
    const rows = [[1, 5], [1, 5], [2, 3], [3, 1], [3, 1], [2, 3], [1, 5], [1, 5]];
    rows.forEach(([ox, w], i) => { c.fillStyle = glass; c.fillRect(x + ox, y + 1 + i, w, 1); });
    c.fillStyle = PAL.yellow2;
    const top = Math.round((1 - phase) * 3), bot = Math.round(phase * 3);
    // 上半沙子贴近瓶颈（第 0-2 行），下半沙子从底部堆起（第 5-7 行）
    for (let r = 3 - top; r < 3; r++) c.fillRect(x + rows[r][0], y + 1 + r, rows[r][1], 1);
    for (let i = 0; i < bot; i++) { const r = 7 - i; c.fillRect(x + rows[r][0], y + 1 + r, rows[r][1], 1); }
    if (phase < 0.95) c.fillRect(x + 3, y + 4 + (Math.floor(t / 120) % 2), 1, 2);
  };

  // 头顶图标：think 思考气泡，stream 逐字气泡，bulb 灯泡，hourglass 沙漏，question 问号，exclaim 叹号，check、cross、zzz、heart
  P.drawIcon = function drawIcon(c, scene, a) {
    const ic = a.icon;
    if (!ic || !a.visible) return;
    const [hx, hy] = P.headTop(scene, a);
    const t = scene.reduced ? 0 : scene.animT;
    const bob = scene.reduced ? 0 : Math.round(Math.sin(t / 260) * 1);
    const el = scene.realT - (ic.t0 || 0);
    switch (ic.kind) {
      case 'think': {
        const w = 22, h = 11, x = hx + 2, y = hy - 22 + bob;
        P.bubble(c, x, y, w, h, { kind: 'think', tx: hx + 3 });
        const n = scene.reduced ? 3 : 1 + (Math.floor(t / 280) % 3);
        c.fillStyle = PAL.ink2;
        for (let i = 0; i < n; i++) c.fillRect(x + 5 + i * 5, y + 5, 2, 2);
        break;
      }
      case 'stream': {
        const full = String(ic.text || '');
        const count = scene.reduced ? full.length : Math.min(full.length, 1 + Math.floor(el / 110));
        const shown = full.slice(0, count);
        c.font = textFont(7, 500);
        const tw = Math.min(110, Math.max(20, c.measureText(full).width));
        const w = Math.round(tw + 8), h = 12, x = Math.round(hx - w / 2 + 6), y = hy - 22 + bob;
        P.bubble(c, x, y, w, h, { kind: 'think', tx: hx + 3 });
        P.text(c, shown + (count < full.length && Math.floor(t / 200) % 2 ? '▌' : ''), x + 4, y + h / 2 + 0.5, { size: 7, max: tw, color: PAL.ink2 });
        break;
      }
      case 'bulb': {
        const x = hx - 4, y = hy - 16 + bob;
        if (!scene.reduced) {
          c.fillStyle = P.rgba(PAL.yellow1, 0.35 + 0.2 * Math.sin(t / 150));
          c.fillRect(x - 3, y - 2, 15, 14);
        }
        c.fillStyle = PAL.yellow2;
        const rays = [[-5, 3], [13, 3], [4, -5], [-3, -3], [11, -3]];
        rays.forEach(([rx, ry]) => c.fillRect(x + rx, y + ry, 2, 1));
        P.drawBitmap(c, 'bulb', x, y);
        break;
      }
      case 'hourglass': {
        const x = hx - 4, y = hy - 17 + bob;
        P.hourglass(c, x, y, t);
        if (ic.text) P.sign(c, hx + 18, y + 10, ic.text, { size: 6, bg: PAL.white, minW: 10 });
        break;
      }
      case 'question': P.drawBitmap(c, 'question', hx - 2, hy - 12 + bob); break;
      case 'exclaim': P.drawBitmap(c, 'exclaim', hx - 1, hy - 11 + bob); break;
      case 'check': P.drawBitmap(c, 'check', hx - 3, hy - 9 + bob); break;
      case 'cross': P.drawBitmap(c, 'cross', hx - 3, hy - 8 + bob); break;
      case 'heart': P.drawBitmap(c, 'heart', hx - 3, hy - 9 + bob); break;
      case 'zzz': {
        const k = scene.reduced ? 0 : (t % 1800) / 1800;
        P.drawBitmap(c, 'zzz', hx + 4 + Math.round(k * 4), hy - 8 - Math.round(k * 6), { alpha: 1 - k * 0.6 });
        break;
      }
      case 'text': {
        P.sign(c, hx, hy - 2 + bob, ic.text, { size: 6, bg: PAL.white, minW: 10 });
        break;
      }
      default:
        throw new Error('未知头顶图标：' + ic.kind);
    }
  };

  // ===========================================================================
  // 8. 共用物件的绘制

  const paint = {};
  P.paint = paint;

  function R(c, x, y, w, h, col) { c.fillStyle = col; c.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); }
  P.R = R;
  // 带墨色外框的矩形
  function RB(c, x, y, w, h, col, ink) { R(c, x - 1, y - 1, w + 2, h + 2, ink || PAL.ink); R(c, x, y, w, h, col); }
  P.RB = RB;

  // 屏幕内容：off 关闭，idle 光标，boot 开机，code 滚动字符，diff 增删的行，term 终端输出，error 红色，ok 绿色，alert 黄色闪烁
  paint.screen = function screen(c, x, y, w, h, mode, t, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const seed = opt.seed || 0;
    if (mode === 'off') {
      R(c, x, y, w, h, '#141a20');
      R(c, x + 1, y + 1, Math.max(1, Math.floor(w / 3)), 1, '#2a333d');
      R(c, x + 1, y + 2, 1, Math.max(1, Math.floor(h / 3)), '#2a333d');
      return;
    }
    const bg = mode === 'error' ? '#3a0d12' : mode === 'alert' ? '#2e2508' : PAL.screen0;
    R(c, x, y, w, h, bg);
    const fg = mode === 'error' ? PAL.red1 : mode === 'alert' ? PAL.yellow2 : PAL.screen3;
    const dim = mode === 'error' ? PAL.red3 : mode === 'alert' ? PAL.yellow4 : PAL.screen2;
    const rows = Math.floor((h - 2) / 2);
    if (mode === 'boot') {
      const k = Math.min(1, opt.k === undefined ? 1 : opt.k);
      const lw = Math.round((w - 2) * k);
      R(c, x + Math.round((w - lw) / 2), y + Math.floor(h / 2), lw, 1, PAL.screen4);
      return;
    }
    if (mode === 'idle') {
      if (Math.floor(t / 500) % 2 === 0) R(c, x + 2, y + 2, 2, 2, dim);
      R(c, x + 5, y + 3, Math.min(w - 8, 6), 1, dim);
      return;
    }
    if (mode === 'code' || mode === 'term' || mode === 'alert') {
      const off = mode === 'alert' ? 0 : Math.floor(t / (mode === 'term' ? 70 : 110));
      for (let r = 0; r < rows; r++) {
        const n = r + off + seed * 31;
        const len = 2 + Math.floor(hash(n) * (w - 6));
        const ind = mode === 'code' ? Math.floor(hash(n * 7) * 3) * 2 : 0;
        R(c, x + 2 + ind, y + 1 + r * 2, Math.min(len, w - 4 - ind), 1, r === rows - 1 && mode !== 'alert' ? fg : dim);
      }
      if (mode === 'alert' && Math.floor(t / 300) % 2 === 0) R(c, x, y, w, h, 'rgba(247,203,70,0.22)');
      return;
    }
    if (mode === 'diff') {
      const off = Math.floor(t / 240);
      for (let r = 0; r < rows; r++) {
        const n = r + off + seed * 17;
        const kind = hash(n * 3) < 0.34 ? '+' : hash(n * 3) < 0.6 ? '-' : ' ';
        const col = kind === '+' ? PAL.green2 : kind === '-' ? PAL.red2 : PAL.screen1;
        if (kind !== ' ') R(c, x + 1, y + 1 + r * 2, w - 2, 1, kind === '+' ? '#14391f' : '#3a1418');
        R(c, x + 1, y + 1 + r * 2, 1, 1, col);
        R(c, x + 3, y + 1 + r * 2, 2 + Math.floor(hash(n) * (w - 7)), 1, kind === ' ' ? PAL.screen2 : col);
      }
      return;
    }
    if (mode === 'error') {
      const cx = x + Math.floor(w / 2), cy = y + Math.floor(h / 2);
      for (let i = -2; i <= 2; i++) { R(c, cx + i, cy + i, 1, 1, fg); R(c, cx + i, cy - i, 1, 1, fg); }
      return;
    }
    if (mode === 'ok') {
      const cx = x + Math.floor(w / 2) - 2, cy = y + Math.floor(h / 2);
      [[0, 0], [1, 1], [2, 0], [3, -1], [4, -2]].forEach(([dx, dy]) => R(c, cx + dx, cy + dy, 1, 1, PAL.green1));
      return;
    }
    if (mode === 'snow') {
      // 雪花：静态噪声，随帧变化
      const off = Math.floor(t / 90);
      for (let r = 0; r < h; r++) {
        for (let q = 0; q < w; q++) {
          const n = hash((r * 31 + q) * 7 + off + seed * 13);
          if (n < 0.42) R(c, x + q, y + r, 1, 1, n < 0.12 ? PAL.white : n < 0.26 ? PAL.grey2 : PAL.grey4);
        }
      }
      return;
    }
    if (mode === 'shot') {
      // 截图缩略图：像素边框与内容示意
      R(c, x, y, w, h, PAL.screen0);
      RB(c, x + 1, y + 1, w - 2, h - 2, PAL.white, PAL.ink);
      R(c, x + 2, y + 2, w - 4, 2, PAL.blue1);
      const n = opt.shot || 0;
      for (let r = 0; r < Math.floor((h - 8) / 3); r++) {
        const len = 3 + Math.floor(hash(r * 11 + n * 5) * (w - 8));
        R(c, x + 3, y + 6 + r * 3, len, 1, [PAL.grey1, PAL.pline, PAL.yellow2][r % 3]);
      }
      return;
    }
    throw new Error('未知屏幕模式：' + mode);
  };
  paint.scanlines = function scanlines(c, x, y, w, h, a) {
    c.fillStyle = 'rgba(0,0,0,' + (a || 0.22) + ')';
    for (let r = 1; r < h; r += 2) c.fillRect(Math.round(x), Math.round(y) + r, w, 1);
  };

  // 办公桌：x 左边，y 为桌面前沿（坐着的小人的脚在这条线上），w 宽度
  paint.desk = function desk(c, x, y, o) {
    const opt = o || {};
    const w = opt.w || 64;
    const wood = opt.wood || [PAL.wood1, PAL.wood2, PAL.wood3, PAL.wood4];
    x = Math.round(x); y = Math.round(y);
    // 桌面与前板
    R(c, x - 1, y - 7, w + 2, 20, PAL.ink);
    R(c, x, y - 6, w, 6, wood[0]);
    R(c, x, y - 6, w, 1, P.mix(wood[0], PAL.white, 0.25));
    R(c, x, y - 1, w, 1, wood[1]);
    R(c, x, y, w, 12, wood[1]);
    R(c, x, y, w, 1, wood[2]);
    R(c, x + 3, y + 3, w - 6, 1, wood[2]);
    R(c, x + w - 20, y + 4, 16, 6, wood[2]);
    R(c, x + w - 19, y + 5, 14, 4, wood[1]);
    R(c, x + w - 14, y + 6, 4, 1, PAL.yellow3);
    R(c, x + 2, y + 11, 3, 1, wood[3]);
    R(c, x + w - 5, y + 11, 3, 1, wood[3]);
  };

  // 桌上物件：纸堆、文件夹、写字用的纸、键盘、茶杯、显示器、状态灯、名牌
  paint.deskItems = function deskItems(c, x, y, o, t) {
    const opt = o || {};
    const w = opt.w || 64;
    x = Math.round(x); y = Math.round(y);
    const papers = Math.min(opt.papers || 0, 9);
    for (let i = 0; i < papers; i++) {
      const px = x + 3 + (i % 2 ? 1 : 0), py = y - 3 - i * 1.5;
      R(c, px - 1, py - 1, 12, 3, PAL.ink);
      R(c, px, py, 10, 1, i % 2 ? PAL.white2 : PAL.white);
    }
    if (opt.folder) P.drawBitmap(c, 'folder', x + 4, y - 5 - Math.min(papers, 9) * 1.5);
    if (opt.docOnDesk) P.drawBitmap(c, 'doc_write', x + Math.round(w / 2) - 12, y - 5);
    if (opt.keyboard !== false) P.drawBitmap(c, 'keyboard', x + Math.round(w / 2) - 7, y - 4);
    if (opt.cup) {
      P.drawBitmap(c, 'cup', x + w - 32, y - 5);
    }
    if (opt.box) P.drawBitmap(c, 'box_open', x + 4, y - 10);
    if (opt.card) P.drawBitmap(c, 'card', x + Math.round(w / 2) + 6, y - 5);
    if (opt.cardResult) P.drawBitmap(c, 'card_result', x + Math.round(w / 2) + 6, y - 5);
    if (opt.monitor !== false) {
      const mx = x + w - 22, my = y - 19;
      P.drawBitmap(c, 'deskMonitor', mx, my);
      paint.screen(c, mx + 3, my + 2, 14, 9, opt.monitor || 'off', t, { seed: opt.seed || 0, k: opt.bootK });
      if (opt.monitorBlink && Math.floor(t / 300) % 2 === 0) R(c, mx + 3, my + 2, 14, 9, 'rgba(247,203,70,0.55)');
    }
    if (opt.lamp) {
      const lx = x + w - 4, ly = y - 9;
      R(c, lx - 1, ly - 1, 4, 5, PAL.ink);
      const on = opt.lamp === 'red' ? (Math.floor(t / 350) % 2 === 0) : true;
      R(c, lx, ly, 2, 2, opt.lamp === 'red' ? (on ? PAL.red2 : PAL.red4) : PAL.green2);
      R(c, lx, ly + 2, 2, 1, PAL.grey3);
    }
    if (opt.nameplate) {
      c.font = textFont(6, 600);
      const tw = Math.min(w - 10, c.measureText(opt.nameplate).width + 6);
      const nx = Math.round(x + w / 2 - tw / 2);
      R(c, nx - 1, y + 2, tw + 2, 9, PAL.ink);
      R(c, nx, y + 3, tw, 7, opt.plateColor || PAL.paper);
      P.text(c, opt.nameplate, x + w / 2, y + 6.5, { size: 6, weight: 600, align: 'center', max: w - 12, color: PAL.ink });
    }
  };

  // 椅子：cx 中心，y 为桌面前沿
  paint.chair = function chair(c, cx, y, o) {
    const opt = o || {};
    cx = Math.round(cx); y = Math.round(y);
    const col = opt.color || PAL.grey3;
    RB(c, cx - 10, y - 16, 20, 9, col);
    R(c, cx - 9, y - 16, 18, 1, P.mix(col, PAL.white, 0.35));
    R(c, cx - 8, y - 14, 16, 5, P.mix(col, PAL.white, 0.14));
    RB(c, cx - 9, y - 7, 18, 2, P.mix(col, PAL.ink, 0.25));
  };

  // 文件柜：x 左边，y 底边；open 为中间抽屉拉开程度 0-1
  paint.cabinet = function cabinet(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = 28, h = 40;
    const body = opt.color || '#8fa3a0', shade = P.mix(body, PAL.ink, 0.3), hi = P.mix(body, PAL.white, 0.3);
    RB(c, x, y - h, w, h, body);
    R(c, x, y - h, w, 2, hi);
    R(c, x + w - 2, y - h, 2, h, shade);
    for (let i = 0; i < 3; i++) {
      const dy0 = y - h + 3 + i * 12;
      const openK = i === 1 ? (opt.open || 0) : 0;
      if (openK > 0) {
        R(c, x + 2, dy0, w - 4, 11, '#2b2f38');
        const tabs = [PAL.yellow2, PAL.blue2, PAL.red2, PAL.green2, PAL.white];
        tabs.forEach((col, j) => R(c, x + 4 + j * 4, dy0 + 1 + Math.round((1 - openK) * 4), 3, 3, col));
      }
      const off = Math.round(openK * 4);
      const fx = x + 2 - Math.round(openK * 2), fw = w - 4 + Math.round(openK * 4);
      RB(c, fx, dy0 + off, fw, 10, P.mix(body, PAL.white, 0.12));
      R(c, fx, dy0 + off + 9, fw, 1, shade);
      R(c, fx + Math.round(fw / 2) - 5, dy0 + off + 2, 10, 3, PAL.white);
      R(c, fx + Math.round(fw / 2) - 4, dy0 + off + 3, 8, 1, PAL.pline);
      R(c, fx + Math.round(fw / 2) - 4, dy0 + off + 6, 8, 2, PAL.metal4);
      R(c, fx + Math.round(fw / 2) - 3, dy0 + off + 6, 6, 1, PAL.metal1);
    }
    if (opt.blink && Math.floor(t / 300) % 2 === 0) blinkFrame(c, x, y - h, w, h);
  };

  function blinkFrame(c, x, y, w, h) {
    R(c, x - 2, y - 2, w + 4, 1, PAL.yellow2); R(c, x - 2, y + h + 1, w + 4, 1, PAL.yellow2);
    R(c, x - 2, y - 2, 1, h + 4, PAL.yellow2); R(c, x + w + 1, y - 2, 1, h + 4, PAL.yellow2);
    R(c, x, y, w, h, 'rgba(247,203,70,0.22)');
  }
  paint.blinkFrame = blinkFrame;

  // 终端与拉杆：x 左边，y 底边；lever 0 抬起、1 拉下；exit 为 null、'green'、'red'
  paint.terminal = function terminal(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = 28, h = 34;
    RB(c, x, y - h, w, h, PAL.grey4);
    R(c, x, y - h, w, 1, PAL.grey3);
    R(c, x + w - 2, y - h, 2, h, PAL.grey5);
    // 退出状态灯
    const lampCol = opt.exit === 'green' ? PAL.green2 : opt.exit === 'red' ? PAL.red2 : PAL.grey5;
    RB(c, x + 10, y - h - 5, 8, 4, lampCol);
    if (opt.exit) R(c, x + 11, y - h - 5, 3, 1, opt.exit === 'green' ? PAL.green1 : PAL.red1);
    R(c, x + 9, y - h - 1, 10, 1, PAL.grey5);
    // 屏幕
    RB(c, x + 3, y - h + 3, 22, 13, PAL.screen0);
    paint.screen(c, x + 3, y - h + 3, 22, 13, opt.screen || 'idle', t, { seed: 3 });
    paint.scanlines(c, x + 3, y - h + 3, 22, 13, 0.18);
    // 按键与出风口
    for (let i = 0; i < 5; i++) R(c, x + 4 + i * 4, y - h + 19, 3, 2, i === 4 ? PAL.red3 : PAL.grey2);
    for (let i = 0; i < 3; i++) R(c, x + 5, y - 9 + i * 3, 18, 1, PAL.grey5);
    // 拉杆（左侧）
    const k = opt.lever || 0;
    const px = x - 1, py = y - 11;
    const ang = -2.2 + k * 1.5;
    const kx = Math.round(px + Math.cos(ang) * 8), ky = Math.round(py + Math.sin(ang) * 8);
    RB(c, px - 1, py - 2, 3, 5, PAL.grey3);
    const pts = P.linePts(px, py, kx, ky);
    c.fillStyle = PAL.ink; pts.forEach((p) => c.fillRect(p[0] - 1, p[1] - 1, 3, 3));
    c.fillStyle = PAL.metal2; pts.forEach((p) => c.fillRect(p[0], p[1], 1, 1));
    RB(c, kx - 1, ky - 1, 3, 3, PAL.red2);
    if (opt.blink && Math.floor(t / 300) % 2 === 0) blinkFrame(c, x - 8, y - h - 6, w + 8, h + 6);
    return { lampX: x + 14, lampY: y - h - 3, knob: [kx, ky], top: [x + 14, y - h - 6] };
  };

  // 门：x 左边，y 底边；open 0-1；返回门牌钉子与信箱缝的位置
  paint.door = function door(c, x, y, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = opt.w || 36, h = opt.h || 60;
    const wood = opt.color || PAL.wood2;
    R(c, x - 3, y - h - 3, w + 6, h + 3, PAL.ink);
    R(c, x - 2, y - h - 2, w + 4, h + 2, PAL.wood3);
    R(c, x, y - h, w, h, '#1c1a26');
    const k = opt.open || 0;
    if (k > 0) {
      c.fillStyle = 'rgba(255,236,190,' + (0.35 * k) + ')';
      c.fillRect(x, y - h, w, h);
    }
    const pw = Math.max(4, Math.round(w * (1 - 0.8 * k)));
    const px = x + w - pw;
    R(c, px, y - h, pw, h, wood);
    if (pw > 12) {
      R(c, px + 4, y - h + 5, pw - 8, 16, P.mix(wood, PAL.white, 0.15));
      R(c, px + 4, y - h + 5, pw - 8, 1, P.mix(wood, PAL.ink, 0.3));
      R(c, px + 5, y - h + 7, pw - 10, 10, opt.glass || '#a9d3ef');
      R(c, px + 5, y - h + 7, 3, 3, PAL.white);
      R(c, px + 4, y - h + 26, pw - 8, 22, P.mix(wood, PAL.white, 0.1));
      R(c, px + 4, y - h + 26, pw - 8, 1, P.mix(wood, PAL.ink, 0.3));
      // 信箱缝
      R(c, px + Math.round(pw / 2) - 6, y - 10, 12, 3, PAL.yellow3);
      R(c, px + Math.round(pw / 2) - 5, y - 9, 10, 1, PAL.ink);
      // 门把手
      R(c, px + 3, y - Math.round(h / 2) + 2, 3, 3, PAL.yellow2);
      R(c, px + 3, y - Math.round(h / 2) + 2, 1, 1, PAL.yellow1);
    } else {
      R(c, px + 1, y - h + 2, 1, h - 4, P.mix(wood, PAL.white, 0.2));
    }
    return { nail: [x + Math.round(w / 2), y - h + 2], slot: [x + Math.round(w / 2), y - 9], w, h };
  };

  // 可移动白板：x 左边，y 板面上沿，floor 地面；title 标题，lines 条目，sheet 贴上的计划纸，erase 擦除进度
  paint.whiteboard = function whiteboard(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = opt.w || 88, h = opt.h || 46;
    // 支架
    const fy = Math.round(opt.floor || y + h + 20);
    [x + 6, x + w - 8].forEach((lx) => { RB(c, lx, y + h, 2, fy - y - h - 2, PAL.metal3); RB(c, lx - 3, fy - 2, 8, 2, PAL.metal4); });
    RB(c, x - 2, y - 2, w + 4, h + 4, PAL.metal2);
    R(c, x - 2, y - 2, w + 4, 1, PAL.metal1);
    R(c, x, y, w, h, '#fbfcff');
    R(c, x, y, w, 1, '#e8ecf5');
    // 笔槽
    RB(c, x + 4, y + h + 2, w - 8, 2, PAL.metal3);
    R(c, x + 10, y + h + 1, 6, 1, PAL.red2); R(c, x + 18, y + h + 1, 6, 1, PAL.blue2); R(c, x + 26, y + h + 1, 6, 1, PAL.green2);
    const lines = opt.lines || [];
    const sheetW = opt.sheet ? 24 : 0;
    if (opt.title) P.text(c, opt.title, x + 4, y + 6, { size: 6.5, weight: 700, color: PAL.blue3, max: w - 8 - sheetW });
    lines.forEach((ln, i) => {
      const ly = y + 15 + i * 8;
      if (ly > y + h - 4) return;
      const col = ln.color || PAL.ink2;
      R(c, x + 4, ly - 1, 2, 2, ln.done ? PAL.green2 : col);
      if (ln.text) {
        P.text(c, ln.text, x + 8, ly, { size: 6, color: col, max: w - 12 - sheetW - (ln.tag ? 34 : 0) });
      } else {
        R(c, x + 8, ly, Math.round((0.4 + hash(i + 3) * 0.5) * (w - 16 - sheetW)), 1, col);
      }
      if (ln.tag) {
        c.font = textFont(5, 700);
        const tw = Math.min(34, c.measureText(ln.tag).width + 4);
        const tx = x + w - 3 - sheetW - tw;
        R(c, tx, ly - 3, tw, 7, ln.tagColor || PAL.yellow2);
        P.text(c, ln.tag, tx + tw / 2, ly + 0.5, { size: 5, weight: 700, align: 'center', color: PAL.ink, max: tw - 2 });
      }
      if (ln.done) { R(c, x + 3, ly - 2, 1, 1, PAL.green3); }
    });
    if (opt.sheet) {
      const sx = x + w - sheetW - 1, sy = y + 4;
      RB(c, sx, sy, 22, h - 10, PAL.white);
      R(c, sx, sy, 22, 3, PAL.blue2);
      for (let i = 0; i < 5; i++) R(c, sx + 3, sy + 7 + i * 5, 12 + Math.round(hash(i + 9) * 5), 1, PAL.pline);
      R(c, sx + 3, sy - 1, 3, 3, PAL.red2); R(c, sx + 16, sy - 1, 3, 3, PAL.red2);
    }
    if (opt.erase !== undefined && opt.erase > 0 && opt.erase < 1) {
      const ew = Math.round((w - 2) * opt.erase);
      R(c, x + 1, y + 11, ew, h - 13, '#fbfcff');
      for (let i = 0; i < 6; i++) R(c, x + 1 + ew - 3, y + 12 + i * 5, 2, 2, '#dfe5f0');
    }
    if (opt.blink && Math.floor(t / 300) % 2 === 0) blinkFrame(c, x, y, w, h);
  };

  // 软木板（钉指导纸条）：x 左边，y 上沿；notes 为纸条数量，done 为已回复数量
  paint.corkboard = function corkboard(c, x, y, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = opt.w || 30, h = opt.h || 30;
    RB(c, x - 2, y - 2, w + 4, h + 4, PAL.wood3);
    R(c, x, y, w, h, '#c9955c');
    for (let i = 0; i < 22; i++) R(c, x + Math.floor(hash(i) * w), y + Math.floor(hash(i + 40) * h), 1, 1, '#a8763f');
    const n = Math.min(opt.notes || 0, 6);
    for (let i = 0; i < n; i++) {
      const nx = x + 3 + (i % 3) * 9, ny = y + 3 + Math.floor(i / 3) * 13;
      // done 为前几张已回复；doneIndex 为某一张刚写完回复
      const done = i < (opt.done || 0) || i === opt.doneIndex;
      P.drawBitmap(c, done ? 'note_done' : 'note', nx, ny + 1);
      R(c, nx + 2, ny, 2, 2, done ? PAL.green2 : PAL.red2);
    }
    if (opt.label) P.text(c, opt.label, x + w / 2, y + h + 6, { size: 5.5, align: 'center', color: PAL.ink2, weight: 600 });
  };

  // 墙上的大 CRT：x、y 左上角，w、h 尺寸；lines 为 [{ k, v, color }]；power 0 关闭、1 开启；boot 为开机动画进度
  paint.crt = function crt(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = opt.w || 128, h = opt.h || 64;
    const shell = opt.shell || PAL.beige1, shell2 = PAL.beige2, shell3 = PAL.beige3;
    // 支架
    R(c, x + 20, y - 8, 3, 8, PAL.grey4); R(c, x + w - 23, y - 8, 3, 8, PAL.grey4);
    R(c, x + 16, y - 9, 11, 2, PAL.grey5); R(c, x + w - 27, y - 9, 11, 2, PAL.grey5);
    // 外壳
    R(c, x + 2, y - 1, w - 4, h + 2, PAL.ink); R(c, x - 1, y + 2, w + 2, h - 4, PAL.ink);
    R(c, x + 2, y, w - 4, h, shell); R(c, x, y + 2, w, h - 4, shell);
    R(c, x + 2, y, w - 4, 1, PAL.white);
    R(c, x, y + h - 12, w, 10, shell2); R(c, x + 2, y + h - 2, w - 4, 2, shell2);
    R(c, x + w - 3, y + 2, 2, h - 6, shell2);
    // 屏幕
    const sx = x + 6, sy = y + 5, sw = w - 12, sh = h - 19;
    R(c, sx - 1, sy - 1, sw + 2, sh + 2, shell3);
    R(c, sx, sy, sw, sh, PAL.ink);
    const on = opt.power !== 0;
    R(c, sx + 1, sy + 1, sw - 2, sh - 2, on ? (opt.bg || PAL.screen0) : '#12171c');
    if (!on) {
      R(c, sx + 4, sy + 3, Math.round(sw / 4), 1, '#2c353f');
      R(c, sx + 3, sy + 4, 1, Math.round(sh / 3), '#2c353f');
    } else if (opt.boot !== undefined && opt.boot < 1) {
      const k = opt.boot;
      const lw = Math.round((sw - 4) * Math.min(1, k * 2));
      const lh = k < 0.5 ? 1 : Math.round((sh - 4) * (k - 0.5) * 2);
      R(c, sx + Math.round((sw - lw) / 2), sy + Math.round((sh - lh) / 2), lw, Math.max(1, lh), P.rgba(PAL.screen4, 0.9));
    } else {
      const lines = opt.lines || [];
      const lh = Math.min(9, Math.floor((sh - 4) / Math.max(1, lines.length)));
      const size = Math.min(7.5, lh - 1);
      lines.forEach((ln, i) => {
        const ly = sy + 3 + i * lh + lh / 2;
        const col = ln.color || (opt.dim ? PAL.screen2 : PAL.screen3);
        const glow = opt.dim ? null : P.rgba(col, 0.8);
        let lx = sx + 4;
        if (ln.k) lx += P.text(c, ln.k, lx, ly, { size, color: opt.dim ? PAL.screen1 : PAL.screen2, weight: 600 }) + 2;
        P.text(c, ln.v, lx, ly, { size, color: col, glow, weight: 600, max: sx + sw - 4 - lx });
      });
      if (opt.cursor && Math.floor(t / 450) % 2 === 0) R(c, sx + sw - 8, sy + sh - 6, 3, 3, PAL.screen3);
      if (opt.alert && Math.floor(t / 300) % 2 === 0) R(c, sx + 1, sy + 1, sw - 2, sh - 2, 'rgba(247,203,70,0.18)');
      // 屏幕弧面高光
      R(c, sx + 2, sy + 2, 6, 1, 'rgba(255,255,255,0.18)');
      R(c, sx + 2, sy + 2, 1, 4, 'rgba(255,255,255,0.18)');
    }
    paint.scanlines(c, sx + 1, sy + 1, sw - 2, sh - 2, 0.16);
    // 下沿：旋钮、喇叭孔、电源灯
    const by = y + h - 9;
    RB(c, x + 8, by, 5, 5, PAL.grey3); R(c, x + 10, by + 1, 1, 2, PAL.grey1);
    RB(c, x + 16, by, 5, 5, PAL.grey3); R(c, x + 18, by + 1, 1, 2, PAL.grey1);
    for (let i = 0; i < 8; i++) R(c, x + w - 40 + i * 3, by + 1, 2, 4, shell3);
    R(c, x + w - 10, by + 2, 3, 2, on ? PAL.green2 : PAL.red3);
    if (opt.label) P.text(c, opt.label, x + 26, by + 2.5, { size: 5.5, weight: 700, color: shell3 });
  };

  // 窗户：night 为夜景，clouds 随时间移动
  paint.window = function windowPaint(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = opt.w || 46, h = opt.h || 40;
    RB(c, x - 2, y - 2, w + 4, h + 4, PAL.white);
    const skies = opt.night ? ['#1b2350', '#232d62', '#2c3875'] : ['#7fc4f0', '#9dd3f5', '#bfe3f8'];
    const bands = [0, Math.round(h * 0.45), Math.round(h * 0.75)];
    bands.forEach((b, i) => R(c, x, y + b, w, h - b, skies[i]));
    if (opt.night) {
      [[6, 5], [30, 8], [18, 14], [38, 20], [10, 24]].forEach(([sx, sy]) => R(c, x + sx, y + sy, 1, 1, PAL.white));
      R(c, x + w - 12, y + 5, 5, 5, PAL.yellow1); R(c, x + w - 10, y + 5, 3, 3, '#1b2350');
    } else {
      const off = Math.floor(t / 700) % (w + 20);
      [[0, 8], [26, 20]].forEach(([cx0, cy]) => {
        const cx = x + ((cx0 + off) % (w + 20)) - 14;
        c.save(); c.beginPath(); c.rect(x, y, w, h); c.clip();
        R(c, cx, y + cy, 12, 3, PAL.white); R(c, cx + 3, y + cy - 2, 6, 2, PAL.white);
        c.restore();
      });
      R(c, x + 3, y + h - 6, 8, 6, '#6fae5e'); R(c, x + 12, y + h - 9, 10, 9, '#5d9b50'); R(c, x + 30, y + h - 7, 12, 7, '#6fae5e');
    }
    R(c, x + Math.floor(w / 2) - 1, y, 2, h, PAL.white);
    R(c, x, y + Math.floor(h / 2) - 1, w, 2, PAL.white);
    RB(c, x - 4, y + h + 2, w + 8, 3, PAL.white2);
  };

  // 挂钟：time 为毫秒
  paint.clock = function clockPaint(c, x, y, time, o) {
    const opt = o || {};
    P.drawBitmap(c, 'clock', x, y);
    const cx = x + 6, cy = y + 6;
    const min = (time / 60000) % 60, hr = ((time / 3600000) % 12) + min / 60;
    const hand = (ang, len, col) => {
      const ex = Math.round(cx + Math.sin(ang) * len), ey = Math.round(cy - Math.cos(ang) * len);
      c.fillStyle = col;
      P.linePts(cx, cy, ex, ey).forEach((p) => c.fillRect(p[0], p[1], 1, 1));
    };
    hand((hr / 12) * Math.PI * 2, 3, PAL.ink);
    hand((min / 60) * Math.PI * 2, 5, PAL.ink2);
    if (opt.seconds !== false) hand(((time / 1000) % 60) / 60 * Math.PI * 2, 5, PAL.red2);
    R(c, cx, cy, 1, 1, PAL.red3);
    if (opt.stopped) {
      R(c, x + 10, y - 3, 7, 7, PAL.ink); R(c, x + 11, y - 2, 5, 5, PAL.red2); R(c, x + 12, y, 3, 1, PAL.white);
    }
  };

  // 吊灯与光锥
  // 吊灯：from 为吊线的起点（天花板高度）
  paint.lamp = function lamp(c, cx, y, on, from) {
    const recolor = on ? null : { y: PAL.grey3 };
    const top = Math.round(from || 0);
    R(c, Math.round(cx), top, 1, Math.round(y) - top, PAL.grey4);
    P.drawBitmap(c, 'lamp', Math.round(cx) - 7, Math.round(y), { recolor });
  };
  paint.lightCone = function lightCone(c, cx, y, len, w, color, alpha) {
    const g = c.createLinearGradient(0, y, 0, y + len);
    g.addColorStop(0, P.rgba(color, alpha));
    g.addColorStop(1, P.rgba(color, 0));
    c.save();
    c.globalCompositeOperation = 'lighter';
    c.fillStyle = g;
    c.beginPath();
    c.moveTo(cx - 5, y); c.lineTo(cx + 5, y); c.lineTo(cx + w / 2, y + len); c.lineTo(cx - w / 2, y + len);
    c.closePath(); c.fill();
    c.restore();
  };
  paint.glow = function glow(c, cx, cy, r, color, alpha) {
    const g = c.createRadialGradient(cx, cy, 0, cx, cy, r);
    g.addColorStop(0, P.rgba(color, alpha));
    g.addColorStop(1, P.rgba(color, 0));
    c.save();
    c.globalCompositeOperation = 'lighter';
    c.fillStyle = g;
    c.fillRect(cx - r, cy - r, r * 2, r * 2);
    c.restore();
  };

  // 提案托盘（放在小边桌上）：x 左边，y 底边
  paint.tray = function tray(c, x, y, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    RB(c, x, y - 18, 26, 18, PAL.wood2);
    R(c, x, y - 18, 26, 2, PAL.wood1);
    R(c, x + 3, y - 13, 20, 8, PAL.wood3);
    R(c, x + 4, y - 12, 18, 6, PAL.wood2);
    P.text(c, opt.label || '提案', x + 13, y - 9, { size: 5.5, weight: 700, align: 'center', color: PAL.paper });
    const n = Math.min(opt.count || 0, 6);
    for (let i = 0; i < n; i++) { R(c, x + 3, y - 21 - i * 1.5, 20, 2, PAL.ink); R(c, x + 4, y - 21 - i * 1.5, 18, 1, i % 2 ? PAL.white2 : PAL.white); }
    RB(c, x + 2, y - 22, 22, 3, PAL.wood3);
    R(c, x + 2, y - 22, 22, 1, PAL.wood2);
    if (opt.blink) blinkFrame(c, x, y - 24, 26, 24);
  };

  // 废纸篓
  paint.bin = function bin(c, x, y, o) {
    const opt = o || {};
    P.drawBitmap(c, 'bin', x, y - 8);
    const n = Math.min(opt.count || 0, 3);
    for (let i = 0; i < n; i++) P.drawBitmap(c, 'paperball', x + 2 + i * 3, y - 10 - (i % 2));
  };

  // 摘要档案盒：n 为编号
  paint.archive = function archive(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = 30, h = 14;
    RB(c, x, y - h, w, h, PAL.card2);
    R(c, x, y - h, w, 3, PAL.card1);
    R(c, x, y - 1, w, 1, PAL.card3);
    R(c, x + 2, y - h + 4, 14, 8, PAL.white);
    P.text(c, '摘要', x + 9, y - h + 8, { size: 5.5, weight: 700, align: 'center', color: PAL.ink2 });
    // 编号用文字绘制：「#2」
    const label = '#' + (opt.n || 0);
    R(c, x + 17, y - h + 4, 11, 8, PAL.paper);
    P.text(c, label, x + 22.5, y - h + 8.2, { size: label.length > 2 ? 5 : 6, weight: 800, align: 'center', color: PAL.red3 });
    if (opt.flash && Math.floor(t / 150) % 2 === 0) { R(c, x - 2, y - h - 2, w + 4, 1, PAL.yellow2); R(c, x - 2, y + 1, w + 4, 1, PAL.yellow2); }
  };

  // 门缝下的信箱：count 为未读指导数量，灯在有未读时亮
  paint.mailbox = function mailbox(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const n = opt.count || 0;
    RB(c, x, y - 7, 14, 7, PAL.metal3);
    R(c, x, y - 7, 14, 1, PAL.metal1);
    for (let i = 0; i < Math.min(n, 4); i++) { R(c, x + 2 + i, y - 9 - i, 10, 2, PAL.ink); R(c, x + 3 + i, y - 9 - i, 8, 1, PAL.yellow1); }
    // 信箱灯立在信箱左侧
    RB(c, x - 4, y - 14, 2, 14, PAL.grey3);
    const lit = n > 0;
    RB(c, x - 6, y - 19, 6, 5, lit ? PAL.yellow2 : PAL.grey5);
    if (lit) R(c, x - 5, y - 19, 2, 1, PAL.yellow1);
    if (n > 0) P.pixText(c, String(n), x + 7, y - 6, PAL.white, 'center');
    return { lamp: [x - 3, y - 17] };
  };

  // 产品的卷轴架：count 为已接纳的卷轴数量
  paint.scrollRack = function scrollRack(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = 60, h = 52;
    RB(c, x, y - h, w, h, PAL.wood3);
    R(c, x, y - h, w, 3, PAL.wood2);
    const n = opt.count || 0;
    for (let r = 0; r < 3; r++) {
      for (let q = 0; q < 4; q++) {
        const cx = x + 3 + q * 14, cy = y - h + 5 + r * 15;
        R(c, cx, cy, 12, 13, PAL.wood4);
        const idx = r * 4 + q;
        if (idx < n) {
          R(c, cx + 1, cy + 4, 10, 8, PAL.paper2);
          R(c, cx + 3, cy + 5, 6, 6, PAL.paper);
          R(c, cx + 5, cy + 7, 2, 2, PAL.paper3);
          R(c, cx + 1, cy + 7, 10, 1, idx === n - 1 && opt.flash && Math.floor(t / 150) % 2 === 0 ? PAL.yellow2 : PAL.red2);
        }
      }
    }
    if (opt.label) P.text(c, opt.label, x + w / 2, y - h - 5, { size: 6, weight: 700, align: 'center', color: PAL.wood4 });
  };

  // 通用的地面桌子：x 左边，y 为桌面前沿，w 宽度
  paint.table = function table(c, x, y, w, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const top = opt.top || PAL.wood1, face = opt.face || PAL.wood2, edge = opt.edge || PAL.wood3;
    R(c, x - 1, y - 7, w + 2, 20, PAL.ink);
    R(c, x, y - 6, w, 6, top);
    R(c, x, y - 6, w, 1, P.mix(top, PAL.white, 0.25));
    R(c, x, y, w, 12, face);
    R(c, x, y, w, 1, edge);
    if (opt.label) {
      c.font = textFont(6, 700);
      const tw = c.measureText(opt.label).width + 8;
      R(c, x + w / 2 - tw / 2 - 1, y + 2, tw + 2, 9, PAL.ink);
      R(c, x + w / 2 - tw / 2, y + 3, tw, 7, opt.labelBg || PAL.paper);
      P.text(c, opt.label, x + w / 2, y + 6.5, { size: 6, weight: 700, align: 'center', color: PAL.ink });
    }
  };

  // 服务器机柜：on 运行，alarm 告警，label 版本
  paint.rack = function rack(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = 28, h = opt.h || 70;
    RB(c, x, y - h, w, h, PAL.grey5);
    R(c, x, y - h, w, 2, PAL.grey4);
    const units = Math.floor((h - 8) / 11);
    for (let i = 0; i < units; i++) {
      const uy = y - h + 4 + i * 11;
      RB(c, x + 2, uy, w - 4, 9, PAL.grey4);
      for (let v = 0; v < 4; v++) R(c, x + 12 + v * 3, uy + 2, 2, 5, PAL.grey5);
      for (let l = 0; l < 2; l++) {
        const phase = hash(i * 5 + l + (opt.seed || 0) * 13);
        let col = PAL.grey5;
        if (opt.on) {
          const blinkOn = Math.floor((t + phase * 1000) / (180 + phase * 300)) % 3 !== 0;
          col = opt.alarm ? (Math.floor(t / 220) % 2 ? PAL.red2 : PAL.red4) : blinkOn ? (l ? PAL.yellow2 : PAL.green2) : PAL.green4;
        }
        R(c, x + 4 + l * 3, uy + 3, 2, 2, col);
      }
    }
    if (opt.label) {
      RB(c, x + 5, y - h - 9, 18, 7, PAL.paper);
      P.text(c, opt.label, x + 14, y - h - 5.3, { size: 6, weight: 800, align: 'center', color: PAL.ink });
    }
    if (opt.blink && Math.floor(t / 300) % 2 === 0) blinkFrame(c, x, y - h, w, h);
  };

  // 墙上的架子：x 左边，y 为架子板面
  paint.shelf = function shelf(c, x, y, w, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    RB(c, x, y, w, 3, opt.color || PAL.wood2);
    R(c, x, y, w, 1, PAL.wood1);
    R(c, x + 3, y + 3, 2, 4, PAL.wood4); R(c, x + w - 5, y + 3, 2, 4, PAL.wood4);
  };

  // 警示灯：color 为 yellow 或 red，on 时旋转发光
  paint.beacon = function beacon(c, x, y, o, t) {
    const opt = o || {};
    P.drawBitmap(c, opt.color === 'red' ? 'beacon_red' : 'beacon', x, y, { recolor: opt.on ? null : { L: PAL.grey3, W: PAL.grey2 } });
  };
  paint.beaconLight = function beaconLight(c, x, y, o, t) {
    const opt = o || {};
    if (!opt.on) return;
    const col = opt.color === 'red' ? PAL.red2 : PAL.yellow2;
    const cx = x + 3, cy = y + 2;
    if (opt.reduced) { paint.glow(c, cx, cy, 16, col, 0.45); return; }
    const ang = (t / 380) % (Math.PI * 2);
    c.save();
    c.globalCompositeOperation = 'lighter';
    for (let s = 0; s < 2; s++) {
      const a = ang + s * Math.PI;
      const len = opt.len || 70;
      const g = c.createRadialGradient(cx, cy, 0, cx, cy, len);
      g.addColorStop(0, P.rgba(col, 0.5));
      g.addColorStop(1, P.rgba(col, 0));
      c.fillStyle = g;
      c.beginPath();
      c.moveTo(cx, cy);
      c.arc(cx, cy, len, a - 0.35, a + 0.35);
      c.closePath();
      c.fill();
    }
    c.restore();
    paint.glow(c, cx, cy, 8, col, 0.6);
  };

  // 语义记录柜：cards 为卡片数量
  paint.cardCabinet = function cardCabinet(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = 24, h = 28;
    RB(c, x, y - h, w, h, PAL.wood2);
    R(c, x, y - h, w, 2, PAL.wood1);
    for (let r = 0; r < 3; r++) for (let q = 0; q < 2; q++) {
      const dx = x + 2 + q * 11, dy = y - h + 4 + r * 8;
      RB(c, dx, dy, 9, 6, PAL.wood1);
      R(c, dx + 3, dy + 1, 3, 2, PAL.white);
      R(c, dx + 4, dy + 4, 1, 1, PAL.yellow3);
    }
    const n = Math.min(opt.cards || 0, 10);
    for (let i = 0; i < n; i++) {
      const cx = x + 2 + i * 2;
      R(c, cx, y - h - 5 + (i % 2), 2, 5, PAL.ink);
      R(c, cx, y - h - 4 + (i % 2), 1, 4, i === n - 1 && opt.flash && Math.floor(t / 150) % 2 === 0 ? PAL.yellow2 : [PAL.white, PAL.blue1, PAL.yellow1][i % 3]);
    }
    if (opt.label) {
      c.font = textFont(5.5, 700);
      const lw = c.measureText(opt.label).width + 6;
      R(c, x + w / 2 - lw / 2, y - h - 14, lw, 8, PAL.paper);
      P.text(c, opt.label, x + w / 2, y - h - 10, { size: 5.5, weight: 700, align: 'center', color: PAL.ink2 });
    }
  };

  // 推车，box 为车上的箱子位图
  paint.cart = function cart(c, x, y, o) {
    const opt = o || {};
    if (opt.box) P.drawBitmap(c, opt.box, x + 8, y - 19);
    P.drawBitmap(c, 'cart', x, y - 11, { flip: opt.flip });
  };

  // 植物、地毯、海报
  paint.plant = function plant(c, x, y) { P.drawBitmap(c, 'plant', x, y - 18); };
  paint.rug = function rug(c, x, y, w, h, col, col2) {
    x = Math.round(x); y = Math.round(y);
    R(c, x + 2, y, w - 4, h, col); R(c, x, y + 1, w, h - 2, col);
    R(c, x + 3, y + 2, w - 6, 1, col2); R(c, x + 3, y + h - 3, w - 6, 1, col2);
    for (let i = 4; i < w - 4; i += 6) R(c, x + i, y + Math.floor(h / 2), 2, 1, col2);
  };
  paint.poster = function poster(c, x, y, w, h, bg, draw) {
    RB(c, x, y, w, h, bg);
    if (draw) draw(c, x, y, w, h);
  };

  // 截图：assets/ 中的本地文件用 Image 加载，加载完成前与文件缺失时画占位框
  const shotCache = new Map();
  function shotImage(file) {
    if (!file) return null;
    let img = shotCache.get(file);
    if (!img) {
      img = new Image();
      img.src = 'assets/' + file;
      shotCache.set(file, img);
    }
    return img.complete && img.naturalWidth > 0 ? img : null;
  }
  P.shotImage = shotImage;

  // 显示器里的一张截图或文字行：x、y 左上角，像素边框。浏览器的每一步都有截图，模型不能看图时（text_only）
  // 显示器同样显示截图，角落标出「只读文字」（3.2D 设计说明第 7.3 节）
  paint.shot = function shot(c, x, y, w, h, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    RB(c, x, y, w, h, PAL.grey5, PAL.ink);
    R(c, x + 1, y + 1, w - 2, h - 2, '#0e1420');
    const img = shotImage(opt.screenshot);
    if (img) {
      c.imageSmoothingEnabled = false;
      c.drawImage(img, x + 2, y + 2, w - 4, h - 4);
    } else if (opt.text_lines && opt.text_lines.length) {
      opt.text_lines.slice(0, Math.max(1, Math.floor((h - 4) / 6))).forEach((s, i) => {
        P.text(c, s, x + 3, y + 5 + i * 6, { size: 4.5, color: PAL.white, max: w - 6 });
      });
    } else {
      for (let r = 1; r < h - 3; r += 3) for (let q = 2; q < w - 4; q += 2) {
        if (hash(r * 13 + q + Math.floor(t / 400)) > 0.55) R(c, x + q, y + r, 1, 1, PAL.white3);
      }
    }
    paint.scanlines(c, x + 1, y + 1, w - 2, h - 2, 0.14);
    if (opt.text_only) {
      R(c, x + w - 13, y + h - 8, 12, 7, PAL.yellow2);
      P.text(c, '文字', x + w - 7, y + h - 4.5, { size: 4.5, weight: 700, align: 'center', color: PAL.ink });
    }
  };

  // 交接管道口：地面或墙上的方口，包裹进出；out 为 flowing 时口上有流动的光点
  paint.pipe = function pipe(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    RB(c, x - 2, y - 18, 22, 18, PAL.metal4, PAL.ink);
    R(c, x, y - 16, 18, 14, '#141a20');
    R(c, x, y - 16, 18, 2, PAL.metal3);
    if (opt.out === 'flowing') {
      const on = Math.floor(t / 160) % 2 === 0;
      R(c, x + 1, y - 15, 16, 12, on ? 'rgba(63,191,102,0.30)' : 'rgba(63,191,102,0.12)');
    }
    if (opt.out === 'stopped') {
      R(c, x - 2, y - 20, 22, 2, PAL.red3);
      P.text(c, '停止', x + 9, y - 27, { size: 5, weight: 700, align: 'center', color: PAL.red1, max: 34 });
    }
    if (opt.letters) P.drawBitmap(c, 'letter', x + 5, y - 12);
  };

  // 传信管口：细管与塞着的信筒
  paint.tube = function tube(c, x, y, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    R(c, x, y - 5, 26, 5, PAL.yellow4);
    R(c, x, y - 5, 26, 1, PAL.yellow3);
    RB(c, x - 4, y - 8, 6, 8, PAL.yellow2, PAL.ink);
    if (opt.letters) P.drawBitmap(c, 'letter', x - 3, y - 12);
  };

  // 门口的邮筒
  paint.postbox = function postbox(c, x, y, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    RB(c, x, y - 18, 12, 18, PAL.red2, PAL.ink);
    R(c, x + 2, y - 15, 8, 2, PAL.red4);
    R(c, x + 3, y - 9, 6, 3, PAL.ink);
    if (opt.flag) { R(c, x + 12, y - 10, 2, 6, PAL.yellow2); R(c, x + 12, y - 10, 5, 3, PAL.yellow1); }
  };

  // 备份柜：三格，lit 为亮起的格数
  paint.backup = function backup(c, x, y, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    RB(c, x, y - 34, 22, 34, PAL.grey5, PAL.ink);
    for (let i = 0; i < 3; i++) {
      const lit = i < (opt.lit || 0);
      R(c, x + 3, y - 31 + i * 10, 16, 8, lit ? PAL.green3 : PAL.grey6);
      R(c, x + 3, y - 31 + i * 10, 16, 1, lit ? PAL.green2 : PAL.grey5);
      if (lit && opt.flash && Math.floor(performance.now() / 200) % 2 === 0) R(c, x + 3, y - 31 + i * 10, 16, 8, PAL.green1);
    }
    P.text(c, '备份', x + 11, y + 5, { size: 5, align: 'center', color: PAL.ink2 });
  };

  // 通往机房的门
  paint.machineDoor = function machineDoor(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = opt.w || 26, h = opt.h || 40;
    RB(c, x, y - h, w, h, PAL.grey5, PAL.ink);
    const open = opt.glow ? 0.4 + 0.15 * Math.sin(t / 260) : 0;
    R(c, x + 2, y - h + 2, w - 4, h - 4, open ? mix('#141a20', PAL.yellow1, open) : '#141a20');
    R(c, x + w - 6, y - Math.round(h / 2), 2, 3, PAL.yellow2);
    P.text(c, '机房', x + w / 2, y - h - 6, { size: 5, weight: 700, align: 'center', color: PAL.ink2, max: 30 });
  };

  // 运维监控屏：正常为绿色网格，故障时变红
  paint.monitor = function monitor(c, x, y, o, t) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = opt.w || 46, h = opt.h || 30;
    RB(c, x, y, w, h, PAL.grey5, PAL.ink);
    const alarm = opt.alarm && Math.floor(t / 300) % 2 === 0;
    const line = alarm ? PAL.red1 : PAL.screen2;
    R(c, x + 2, y + 2, w - 4, h - 4, alarm ? '#3a0d12' : PAL.screen0);
    for (let r = 1; r < 4; r++) {
      const yy = y + 4 + r * 5;
      let px = x + 3;
      while (px < x + w - 4) {
        const len = 2 + Math.floor(hash(r * 7 + px) * 6);
        R(c, px, yy, Math.min(len, x + w - 4 - px), 1, line);
        px += len + 3;
      }
    }
    if (opt.label !== false) P.text(c, alarm ? '故障' : '运行', x + w / 2, y + h + 5, { size: 5, weight: 700, align: 'center', color: alarm ? PAL.red1 : PAL.ink2, max: 34 });
  };

  // 墙上的 MCP 工具面板：按下的按钮亮灯
  paint.toolPanel = function toolPanel(c, x, y, o) {
    const opt = o || {};
    x = Math.round(x); y = Math.round(y);
    const w = opt.w || 46, h = opt.h || 26;
    RB(c, x, y, w, h, PAL.grey4, PAL.ink);
    P.text(c, 'MCP', x + w / 2, y + 6, { size: 5, weight: 700, align: 'center', color: PAL.white, max: w - 4 });
    const labels = opt.labels || [];
    const n = Math.max(1, opt.buttons || labels.length || 3);
    for (let i = 0; i < n; i++) {
      const lit = i === opt.lit;
      const bw = Math.floor((w - 6) / n) - 2;
      const bx = x + 3 + i * Math.floor((w - 6) / n);
      R(c, bx, y + h - 13, bw, 9, lit ? PAL.yellow2 : PAL.grey2);
      if (lit) scene0Spark(c, bx + bw / 2, y + h - 13);
      if (labels[i]) P.text(c, labels[i], bx + bw / 2, y + h - 9, { size: 4.5, align: 'center', color: lit ? PAL.ink : PAL.grey5, max: bw });
    }
  };
  function scene0Spark(c, x, y) { R(c, x - 1, y - 1, 3, 1, PAL.yellow1); R(c, x, y - 2, 1, 3, PAL.yellow1); }

  // ===========================================================================
  // 9. 动作图鉴的小画面：每个动作一段循环播放的小场景

  const VW = 120, VH = 76, VWALL = 50, VBASE = 56, VDESK = 64;
  const VS = {
    go: (x, y, gait, speed) => ({ t: 'go', x, y, gait, speed }),
    anim: (name, ms, key) => ({ t: 'anim', name, ms, key }),
    wait: (ms, key) => ({ t: 'wait', ms, key }),
    call: (fn) => ({ t: 'call', fn }),
    hold: (item) => ({ t: 'hold', item }),
    turn: (facing) => ({ t: 'turn', facing }),
    icon: (icon) => ({ t: 'icon', icon }),
    seat: (d) => ({ t: 'seat', seat: d }),
    fade: (to, ms) => ({ t: 'fade', to, ms })
  };
  an('type_still', [['type0', 1000]]);

  // 每个动作默认使用的小人；动作图鉴可以统一换成某个角色
  P.VIGNETTE_SPRITES = {
    tea: 'product.agent', activate: 'engineering.agent', fetch_folder: 'product.agent', type_think: 'engineering.agent',
    stream_text: 'quality.agent', idea: 'product.agent', retry_wait: 'engineering.agent', slump: 'quality.agent',
    search: 'product.agent', read: 'quality.agent', write: 'engineering.agent', run_command: 'engineering.agent',
    toss: 'engineering.agent', submit: 'product.agent', returned: 'product.agent', stamp_valid: 'product.agent',
    pin_plan: 'engineering.agent', seal: 'engineering.lead', take_box: 'quality.tester', inspect: 'quality.tester',
    stamp_release: 'quality.tester', stamp_rework: 'quality.tester',
    send_letter: 'engineering.agent', answer_letter: 'product.agent', guidance_in: 'quality.agent',
    guidance_read: 'engineering.agent', guidance_reply: 'engineering.agent', compact: 'engineering.agent', compact_fail: 'product.agent',
    paused: 'product.agent', failed: 'quality.agent', done: 'engineering.agent', cancelled: 'product.agent',
    freeze: 'engineering.agent', resume: 'engineering.agent', puzzled: 'engineering.agent', decided: 'engineering.agent',
    hold_card: 'quality.agent', remote_run: 'engineering.agent', remote_unknown: 'engineering.agent',
    read_existing: 'product.agent', net_fetch: 'engineering.agent', mcp_press: 'engineering.lead', trial: 'quality.tester',
    self_test: 'engineering.lead', deploy: 'operations.ops', rollback: 'operations.ops', fault: 'operations.ops',
    wait_provider: 'engineering.agent', hold_form: 'operations.ops',
    assign: 'engineering.manager', hand_back: 'engineering.lead', review: 'quality.reviewer', explore: 'engineering.explorer',
    replan: 'engineering.architect', manager_out: 'engineering.manager', semantic: 'product.architect',
    idle: 'engineering.agent', walk: 'engineering.agent', carry: 'engineering.lead:2', run: 'operations.ops', sit: 'product.agent', type: 'engineering.agent',
    role: 'engineering.agent'
  };
  // 这些动作的小人不随图鉴选择的角色改变（两个角色同场或已指定角色）
  const VIGNETTE_FIXED = new Set(['assign', 'hand_back', 'review', 'manager_out']);

  // 每个动作的小场景：v 提供物件与小人，返回主角的步骤
  const VIG = {};
  P.VIGNETTES = VIG;

  VIG.role = (v) => {
    v.actor({ x: 60, y: 62 });
    return [VS.anim('idle', 1600, true), VS.go(84, 62), VS.turn(-1), VS.anim('look_l', 900), VS.go(38, 62), VS.turn(1), VS.anim('idle_happy', 900), VS.go(60, 62), VS.turn(1)];
  };
  VIG.idle = (v) => { v.actor({ x: 60, y: 62 }); return [VS.anim('idle', 3200, true)]; };
  VIG.walk = (v) => { v.actor({ x: 16, y: 62 }); return [VS.anim('walk', 1, true), VS.go(104, 62), VS.go(16, 62)]; };
  VIG.carry = (v) => { v.actor({ x: 16, y: 62, hold: 'box_sealed' }); return [VS.anim('carry', 1, true), VS.go(104, 62, 'carry'), VS.go(16, 62, 'carry')]; };
  VIG.run = (v) => { v.actor({ x: 12, y: 62 }); return [VS.anim('run', 1, true), VS.go(108, 62, 'run', 90), VS.go(12, 62, 'run', 90)]; };
  VIG.sit = (v) => { const d = v.desk(34); v.actor({ seat: d }); return [VS.anim('sit', 3000, true)]; };
  VIG.type = (v) => { const d = v.desk(34, { monitor: 'code' }); v.actor({ seat: d }); return [VS.anim('type', 3000, true)]; };

  VIG.tea = (v) => {
    const d = v.desk(34);
    v.st.dark = 0.32;
    v.actor({ seat: d, anim: 'tea' });
    return [VS.anim('tea', 4200, true), VS.anim('stretch_sit'), VS.anim('sit', 600)];
  };
  VIG.activate = (v) => {
    const d = v.desk(56);
    const scr = v.prop('screen', { x: 62, y: 6, w: 46, h: 30, power: 0 });
    v.st.dark = 0.3;
    v.actor({ x: 18, y: 60 });
    return [VS.anim('look_up', 500), VS.call(() => { v.tween(v.st, 'dark', 0, 500); scr.power = 1; scr.boot = 0; v.tween(scr, 'boot', 1, 900); }),
      VS.go(80, 58), VS.anim('look_up', 1000, true), VS.go(d.seatX, d.seatY), VS.seat(d), VS.anim('type', 1400)];
  };
  VIG.fetch_folder = (v) => {
    const cab = v.prop('cabinet', { x: 6, base: VBASE, open: 0 });
    const d = v.desk(62, { papers: 1 });
    const me = v.actor({ seat: d });
    return [VS.seat(null), VS.anim('idle', 200), VS.go(46, 58), VS.turn(-1),
      VS.call(() => v.tween(cab, 'open', 1, 300)), VS.anim('rummage', 900), VS.anim('grab_folder', 700, true),
      VS.call(() => v.tween(cab, 'open', 0, 300)), VS.hold('folder'), VS.go(d.seatX, 52, 'carry'), VS.go(d.seatX, d.seatY, 'carry'), VS.seat(d), VS.turn(1),
      VS.call(() => { d.folder = true; me.hold = null; }), VS.hold(null), VS.anim('sit_happy', 900)];
  };
  VIG.type_think = (v) => { const d = v.desk(34, { monitor: 'code' }); v.actor({ seat: d }); return [VS.icon({ kind: 'think' }), VS.anim('type', 3600, true), VS.icon(null)]; };
  VIG.stream_text = (v) => { const d = v.desk(34, { monitor: 'code' }); v.actor({ seat: d }); return [VS.icon({ kind: 'stream', text: '按首次出现顺序输出' }), VS.anim('type', 3600, true), VS.icon(null)]; };
  VIG.idea = (v) => {
    const d = v.desk(34, { monitor: 'code' });
    const me = v.actor({ seat: d });
    return [VS.icon({ kind: 'think' }), VS.anim('type', 1500), VS.icon({ kind: 'bulb' }), VS.call(() => { const [hx, hy] = P.headTop(v.scene, me); v.scene.emit('spark', hx, hy - 10, 12); }), VS.anim('sit_happy', 1900, true), VS.icon(null)];
  };
  VIG.retry_wait = (v) => { const d = v.desk(34, { monitor: 'idle' }); v.actor({ seat: d }); return [VS.icon({ kind: 'hourglass', text: '第 2/3 次' }), VS.anim('sit_wait', 3400, true), VS.icon(null)]; };
  VIG.slump = (v) => {
    const d = v.desk(34, { monitor: 'code' });
    v.actor({ seat: d });
    return [VS.anim('type', 1000), VS.call(() => { d.lamp = 'red'; d.monitor = 'error'; }), VS.anim('shock', 300), VS.anim('slump', 2800, true)];
  };
  VIG.search = (v) => {
    const cab = v.prop('cabinet', { x: 6, base: VBASE, open: 0 });
    v.actor({ x: 46, y: 58, facing: -1 });
    return [VS.call(() => v.tween(cab, 'open', 1, 300)), VS.anim('rummage', 1300), VS.anim('magnify', 1900, true), VS.call(() => v.tween(cab, 'open', 0, 300)), VS.anim('idle', 500)];
  };
  VIG.read = (v) => { const d = v.desk(34, { monitor: 'idle' }); v.actor({ seat: d, hold: 'doc' }); return [VS.anim('read_sit', 3400, true)]; };
  VIG.write = (v) => { const d = v.desk(34, { monitor: 'diff', doc: true }); v.actor({ seat: d }); return [VS.anim('write', 3400, true)]; };
  VIG.run_command = (v) => {
    const term = v.prop('terminal', { x: 72, base: VBASE, lever: 0, exit: null, screen: 'idle' });
    v.actor({ x: 56, y: 58 });
    return [VS.call(() => v.after(450, () => { v.tween(term, 'lever', 1, 200); term.screen = 'term'; v.scene.emit('dust', 64, 50, 5); })), VS.anim('lever', 1000, true),
      VS.anim('watch_r', 1700), VS.call(() => { term.exit = 'green'; term.screen = 'idle'; v.tween(term, 'lever', 0, 300); }), VS.icon({ kind: 'check' }), VS.anim('idle_happy', 1000), VS.icon(null)];
  };
  VIG.toss = (v) => {
    const d = v.desk(26);
    const bin = v.prop('bin', { x: 98, base: 70, count: 0 });
    const me = v.actor({ x: d.seatX, y: d.seatY });
    return [VS.anim('shake', undefined, true), VS.anim('fold', 600), VS.hold('paperball'),
      VS.call(() => v.after(450, () => { me.hold = null; v.fly({ bmp: 'paperball', from: [me.x + 6, me.y - 20], to: [bin.x + 5, bin.base - 10], ms: 700, arc: 20, ease: 'linear', onDone: () => { bin.count += 1; } }); })),
      VS.anim('throw', 1000), VS.anim('idle', 600)];
  };
  VIG.submit = (v) => {
    const tray = v.prop('tray', { x: 78, base: 58, count: 1 });
    v.actor({ x: 22, y: 60, hold: 'doc' });
    return [VS.go(68, 60, 'carry'), VS.turn(1), VS.anim('side_place', 800, true), VS.call(() => { tray.count += 1; }), VS.hold(null), VS.anim('side', 500)];
  };
  VIG.returned = (v) => {
    const tray = v.prop('tray', { x: 84, base: 58, count: 2 });
    const d = v.desk(14);
    v.actor({ seat: d });
    return [VS.anim('sit', 500), VS.call(() => { tray.count -= 1; v.fly({ bmp: 'doc', from: [tray.x + 13, tray.base - 24], to: [d.x + 22, d.y - 6], ms: 800, arc: 22, onDone: () => { d.doc = true; } }); }),
      VS.anim('sit_up', 700), VS.icon({ kind: 'question' }), VS.anim('sit_scratch', 2200, true), VS.icon(null)];
  };
  function stampVignette(v, o) {
    const tbl = v.prop('table', { x: 22, w: 76, y: VDESK, label: o.label, top: o.top, face: o.face, item: o.item || null, slip: o.slip || null, mark: null, slipMark: null, ticks: 0 });
    const me = v.actor({ x: 58, y: VDESK });
    const hits = o.anim === 'stamp' ? [830, 1720] : [480];
    return { tbl, me, steps: [VS.hold(o.stamp), VS.call(() => hits.forEach((ms) => v.after(ms, () => { v.scene.emit('dust', 60, VDESK - 5, 12); o.hit(tbl); }))), VS.anim(o.anim || 'stamp_once', undefined, true), VS.hold(null)] };
  }
  VIG.stamp_valid = (v) => {
    const s = stampVignette(v, { label: '卷轴台', item: 'scroll_open', stamp: 'stamp_valid', anim: 'stamp', hit: (t) => { t.mark = { text: '有效', color: '#d4353f' }; } });
    return s.steps.concat([VS.anim('idle_happy', 900)]);
  };
  VIG.pin_plan = (v) => {
    const wb = v.prop('whiteboard', { x: 30, y: 18, w: 60, h: 26, floor: 58, sheet: false });
    v.actor({ x: 14, y: 62, hold: 'doc' });
    return [VS.go(60, 62, 'carry'), VS.anim('board_pin', undefined, true), VS.call(() => { wb.sheet = true; }), VS.hold(null), VS.anim('back', 700)];
  };
  VIG.seal = (v) => {
    const s = stampVignette(v, { label: '封存台', top: PAL.metal1, face: PAL.metal3, item: 'box_open', stamp: 'stamp_seal', hit: (t) => { t.mark = { text: '封存', color: PAL.blue2 }; } });
    return [VS.hold('docs'), VS.anim('place', 800), VS.hold(null), VS.call(() => { s.tbl.item = 'box'; s.tbl.tape = 0; v.tween(s.tbl, 'tape', 1, 700, 'linear'); }), VS.anim('tidy', 800),
      VS.call(() => { s.tbl.item = 'box_sealed'; })].concat(s.steps, [VS.anim('idle_happy', 800)]);
  };
  VIG.inspect = (v) => {
    const tbl = v.prop('table', { x: 22, w: 76, y: VDESK, label: '检验台', top: PAL.white, face: '#c3a0f2', item: 'box_sealed', checklist: true, ticks: 0, lamp: true });
    v.actor({ x: 58, y: VDESK });
    return [VS.anim('inspect', 1800, true), VS.call(() => [0, 1, 2].forEach((i) => v.after(300 + i * 450, () => { tbl.ticks = i + 1; }))), VS.anim('tick', 1700), VS.anim('idle_happy', 700)];
  };
  VIG.stamp_release = (v) => {
    const s = stampVignette(v, { label: '检验台', top: PAL.white, face: '#c3a0f2', item: 'box_sealed', slip: 'release', stamp: 'stamp_green', hit: (t) => { t.slipMark = { text: '放行', color: PAL.green2 }; v.scene.emit('spark', 76, VDESK - 10, 10); } });
    return s.steps.concat([VS.icon({ kind: 'check' }), VS.anim('idle_happy', 1000), VS.icon(null)]);
  };
  VIG.stamp_rework = (v) => {
    const s = stampVignette(v, { label: '检验台', top: PAL.white, face: '#c3a0f2', item: 'box_sealed', slip: 'defect', stamp: 'stamp_red', hit: (t) => { t.slipMark = { text: '返工', color: PAL.red2 }; } });
    return s.steps.concat([VS.call(() => { s.tbl.item = 'box_rework'; }), VS.icon({ kind: 'exclaim' }), VS.anim('stand_sad', 1000), VS.icon(null)]);
  };
  VIG.send_letter = (v) => {
    const tube = v.prop('tube', { x: 78, base: VBASE, letters: 0 });
    const me = v.actor({ x: 34, y: 62 });
    return [VS.anim('write', 1100), VS.hold('letter'), VS.go(64, 60, 'carry'), VS.turn(1),
      VS.anim('side_place', 800, true), VS.call(() => { tube.letters = 1; me.hold = null; }), VS.hold(null), VS.anim('wait', 2200)];
  };
  VIG.answer_letter = (v) => {
    const tube = v.prop('tube', { x: 78, base: VBASE, letters: 1 });
    const me = v.actor({ x: 56, y: 62 });
    return [VS.call(() => { tube.letters = 0; v.fly({ bmp: 'letter', from: [tube.x + 4, tube.base - 12], to: [me.x, me.y - 20], ms: 550, arc: 8 }); }),
      VS.anim('catch', 1100, true), VS.hold('letter'), VS.anim('write', 1200), VS.anim('side_place', 800),
      VS.call(() => { tube.letters = 1; me.hold = null; }), VS.hold(null), VS.anim('idle', 500)];
  };
  VIG.take_box = (v) => {
    const pipe = v.prop('pipe', { x: 78, base: VBASE, out: 'flowing' });
    const tbl = v.prop('table', { x: 22, w: 76, y: VDESK, label: '检验台', top: PAL.white, face: '#c3a0f2', item: null, ticks: 0 });
    v.actor({ x: 64, y: 60 });
    return [VS.call(() => { v.fly({ bmp: 'box_sealed', from: [pipe.x + 6, pipe.base - 14], to: [tbl.x + 52, tbl.y - 16], ms: 700, arc: 12, onDone: () => { tbl.item = 'box_sealed'; } }); }),
      VS.anim('reach', 900, true), VS.go(58, VDESK, 'carry'), VS.anim('place', 700), VS.anim('idle', 600)];
  };
  VIG.remote_run = (v) => {
    const term = v.prop('terminal', { x: 60, base: VBASE, lever: 0, exit: null, screen: 'term', machine: '控制主机', link: true });
    v.actor({ x: 44, y: 58 });
    return [VS.call(() => v.after(450, () => { v.tween(term, 'lever', 1, 200); })), VS.anim('lever', 1000, true), VS.anim('watch_r', 2600, true)];
  };
  VIG.remote_unknown = (v) => {
    const term = v.prop('terminal', { x: 60, base: VBASE, lever: 1, exit: null, screen: 'snow', blink: true, machine: '客厅树莓派' });
    v.actor({ x: 46, y: 58 });
    return [VS.anim('watch_r', 1400), VS.icon({ kind: 'question' }), VS.anim('puzzled', 2800, true), VS.icon(null)];
  };
  VIG.read_existing = (v) => {
    const d = v.desk(34, { papers: 0, docs: 0 });
    const me = v.actor({ seat: d });
    return [VS.seat(null), VS.go(74, 58), VS.hold('docs'), VS.anim('carry_f', 700, true), VS.go(d.seatX, 52, 'carry'), VS.go(d.seatX, d.seatY, 'carry'), VS.seat(d),
      VS.call(() => { d.docs = 1; me.hold = null; }), VS.hold(null), VS.anim('read_sit', 2000, true), VS.call(() => { d.docs = 3; }), VS.anim('read_sit', 1400)];
  };
  VIG.net_fetch = (v) => {
    const post = v.prop('postbox', { x: 92, base: VBASE, flag: 0 });
    const me = v.actor({ x: 20, y: 62, hold: 'letter' });
    return [VS.go(80, 60, 'carry'), VS.turn(1), VS.anim('side_place', 700, true), VS.call(() => { post.flag = 1; me.hold = null; }), VS.hold(null),
      VS.wait(700), VS.call(() => { post.flag = 0; v.fly({ bmp: 'docs', from: [post.x + 8, post.base - 20], to: [me.x + 2, me.y - 20], ms: 600, arc: 10 }); }),
      VS.anim('catch', 900), VS.hold('docs'), VS.anim('carry_f', 800, true), VS.call(() => { me.hold = null; }), VS.hold(null), VS.anim('idle', 500)];
  };
  VIG.mcp_press = (v) => {
    const panel = v.prop('toolpanel', { x: 74, y: 22, w: 34, h: 22, buttons: 3, lit: -1, labels: ['检', '网', '图'] });
    v.actor({ x: 58, y: 60 });
    return [VS.go(64, 58), VS.turn(1), VS.anim('reach', 900, true), VS.call(() => { panel.lit = 1; v.scene.emit('spark', panel.x + 18, panel.y + 24, 8); }), VS.anim('idle_happy', 900)];
  };
  VIG.trial = (v) => {
    const trial = v.prop('trial', { x: 30, w: 64, y: VDESK, label: '试用台', step: 1, lines: ['搜索框', '新增按钮'] });
    v.actor({ seat: { seatX: 60, seatY: VDESK, trial: true }, sprite: 'quality.tester' });
    return [VS.anim('type', 1400), VS.call(() => { trial.step = 2; trial.lines = ['点击新增', '输入标题']; }), VS.anim('type', 1600), VS.call(() => { trial.step = 3; }), VS.anim('sit_up', 1200, true)];
  };
  VIG.self_test = (v) => {
    const d = v.desk(34, { monitor: 'shot' });
    v.actor({ seat: d });
    return [VS.anim('type', 1400), VS.call(() => { d.shot = 1; }), VS.anim('type', 1400), VS.call(() => { d.shot = 2; }), VS.anim('sit_happy', 1200, true)];
  };
  VIG.guidance_in = (v) => {
    const door = v.prop('door', { x: 64, base: VBASE, w: 28, h: 44 });
    const mb = v.prop('mailbox', { x: 100, base: 62, count: 0 });
    const d = v.desk(2);
    v.actor({ seat: d });
    return [VS.anim('sit', 700), VS.call(() => v.fly({ bmp: 'note', from: [door.x + 14, door.base - 9], to: [mb.x + 7, mb.base - 9], ms: 800, arc: 2, ease: 'out', onDone: () => { mb.count = 1; } })),
      VS.anim('sit', 900), VS.anim('sit_up', 1800, true)];
  };
  VIG.guidance_read = (v) => {
    const mb = v.prop('mailbox', { x: 22, base: 62, count: 1 });
    const cork = v.prop('cork', { x: 72, y: 12, w: 30, h: 26, notes: 0, done: 0 });
    const me = v.actor({ x: 34, y: 64 });
    return [VS.anim('crouch', 700), VS.call(() => { mb.count = 0; }), VS.hold('note'), VS.anim('read_stand', 1500, true), VS.go(87, 62), VS.anim('note_pin'),
      VS.call(() => v.fly({ bmp: 'note', from: [me.x, me.y - 24], to: [cork.x + 5, cork.y + 6], ms: 350, arc: 4, onDone: () => { cork.notes = 1; } })), VS.hold(null), VS.anim('back', 700)];
  };
  VIG.guidance_reply = (v) => {
    const cork = v.prop('cork', { x: 45, y: 12, w: 30, h: 26, notes: 1, done: 0 });
    v.actor({ x: 60, y: 62 });
    return [VS.anim('board_write', 2200, true), VS.call(() => { cork.done = 1; }), VS.anim('back', 900)];
  };
  VIG.compact = (v) => {
    v.prop('cabinet', { x: 6, base: VBASE, open: 0 });
    const arc = v.prop('archive', { x: 6, base: VBASE - 40, n: 2, flash: 0 });
    const d = v.desk(62, { papers: 6 });
    const me = v.actor({ seat: d });
    return [VS.seat(null), VS.anim('gather', 1100, true), VS.call(() => { d.papers = 0; }), VS.hold('docs'), VS.go(46, 58, 'carry'), VS.turn(-1), VS.anim('side_place', 400),
      VS.call(() => { me.hold = null; v.fly({ bmp: 'docs', from: [me.x - 8, me.y - 22], to: [arc.x + 14, arc.base - 8], ms: 450, arc: 10, onDone: () => { arc.n += 1; arc.flash = v.scene.realT + 1500; } }); }),
      VS.anim('idle_happy', 900)];
  };
  VIG.compact_fail = (v) => {
    const d = v.desk(34, { papers: 5 });
    v.actor({ seat: d });
    return [VS.call(() => { d.papers = 0; v.scene.emit('paper', d.x + 10, d.y - 8, 10, { floor: 52 }); }), VS.seat(null), VS.anim('shock', 600), VS.go(38, 52), VS.anim('crouch', 900, true),
      VS.go(76, 52), VS.anim('crouch', 700), VS.hold('docs'), VS.anim('gather', 600), VS.call(() => { d.papers = 5; }), VS.hold(null), VS.go(d.seatX, d.seatY), VS.seat(d), VS.anim('sit', 500)];
  };
  function signDesk(v, text, deskOpts) {
    const d = v.desk(10, deskOpts);
    v.prop('door', { x: 72, base: VBASE, w: 28, h: 44, sign: text });
    return d;
  }
  VIG.paused = (v) => { const d = signDesk(v, '已暂停'); v.st.dark = 0.28; v.actor({ seat: d }); return [VS.icon({ kind: 'zzz' }), VS.anim('sit_relax', 3400, true), VS.icon(null)]; };
  VIG.failed = (v) => { const d = signDesk(v, '失败：provider_error', { lamp: 'red', monitor: 'error' }); v.st.dark = 0.28; v.actor({ seat: d }); return [VS.anim('slump', 3400, true)]; };
  VIG.done = (v) => {
    const d = signDesk(v, '已完成', { monitor: 'ok' });
    v.actor({ x: d.seatX, y: d.seatY });
    return [VS.call(() => v.scene.emit('confetti', 60, 2, 30, { spread: 110 })), VS.anim('cheer', 2600, true), VS.anim('idle_happy', 600)];
  };
  VIG.cancelled = (v) => {
    const d = signDesk(v, '已取消', { papers: 4 });
    v.st.dark = 0.28;
    v.actor({ x: d.seatX, y: d.seatY });
    return [VS.call(() => { d.box = true; }), VS.anim('tidy', 2400, true), VS.call(() => { d.papers = 0; }), VS.anim('idle', 900)];
  };
  VIG.freeze = (v) => {
    const d = v.desk(20, { monitor: 'code' });
    const door = v.prop('door', { x: 84, base: VBASE, w: 28, h: 44 });
    v.prop('clock', { x: 58, y: 8, stopped: false });
    v.actor({ seat: d });
    return [VS.anim('type', 1400), VS.call(() => { v.st.dark = 0.62; v.st.stop = true; d.monitor = 'off'; door.sign = '中断'; }), VS.anim('type_still', 3000, true)];
  };
  VIG.puzzled = (v) => {
    v.prop('terminal', { x: 72, base: VBASE, lever: 1, exit: null, screen: 'alert', blink: true });
    v.prop('beacon', { x: 10, y: 8, on: true });
    v.st.yellow = true;
    v.actor({ x: 56, y: 58 });
    return [VS.icon({ kind: 'question' }), VS.anim('puzzled', 3400, true), VS.icon(null)];
  };
  VIG.decided = (v) => {
    const term = v.prop('terminal', { x: 40, base: VBASE, lever: 0, exit: null, screen: 'alert', blink: true });
    const door = v.prop('door', { x: 86, base: VBASE, w: 28, h: 44 });
    v.st.yellow = true;
    const me = v.actor({ x: 72, y: 60 });
    return [VS.icon({ kind: 'question' }), VS.anim('puzzled', 900), VS.icon(null),
      VS.call(() => { v.fly({ bmp: 'decision', from: [door.x + 14, door.base - 9], to: [me.x + 6, me.y - 2], ms: 500, arc: 2, ease: 'out' }); }),
      VS.anim('crouch', 700), VS.hold('decision'), VS.call(() => { v.st.yellow = false; term.blink = false; term.screen = 'idle'; }),
      VS.icon({ kind: 'text', text: '重新执行' }), VS.anim('read_stand', 1600, true), VS.icon(null), VS.hold(null),
      VS.go(24, 58), VS.turn(1), VS.call(() => v.after(450, () => { v.tween(term, 'lever', 1, 200); term.screen = 'term'; })), VS.anim('lever', 1000), VS.anim('watch_r', 1200)];
  };
  VIG.hold_card = (v) => { v.actor({ x: 60, y: 66, data: { sign: '凭据被上游拒绝' } }); return [VS.anim('hold_sign', 3400, true)]; };
  VIG.resume = (v) => {
    const d = v.desk(56, { monitor: 'off' });
    v.st.dark = 0.6;
    v.actor({ x: 20, y: 62 });
    return [VS.anim('freeze', 700), VS.call(() => { v.tween(v.st, 'dark', 0, 500); d.monitor = 'code'; }), VS.anim('stretch', undefined, true), VS.go(d.seatX, 52), VS.go(d.seatX, d.seatY), VS.seat(d), VS.anim('type', 1200)];
  };
  VIG.assign = (v) => {
    const d = v.desk(64, { monitor: 'code' });
    const other = v.actor({ seat: d, sprite: 'engineering.lead', anim: 'type' });
    const me = v.actor({ x: 20, y: 64, hold: 'card_task' });
    v.main = me;
    return [VS.go(56, 64), VS.turn(1), VS.anim('give', undefined, true), VS.call(() => { d.card = true; v.scene.run(other, [VS.anim('sit_up', 1400), VS.anim('sit_card', 800)], {}); }), VS.hold(null), VS.anim('idle_happy', 500), VS.go(20, 64), VS.turn(1)];
  };
  VIG.hand_back = (v) => {
    const d = v.desk(64, { monitor: 'code' });
    const other = v.actor({ seat: d, sprite: 'engineering.manager', anim: 'type' });
    const me = v.actor({ x: 20, y: 64, hold: 'card_result' });
    v.main = me;
    return [VS.go(56, 64), VS.turn(1), VS.anim('give', undefined, true), VS.call(() => { d.cardResult = true; v.scene.run(other, [VS.anim('sit_happy', 1600)], {}); }), VS.hold(null), VS.anim('idle_happy', 500), VS.go(20, 64), VS.turn(1)];
  };
  VIG.explore = (v) => {
    const door = v.prop('door', { x: 84, base: VBASE, w: 28, h: 44, open: 0 });
    const d = v.desk(8, { papers: 1 });
    const me = v.actor({ seat: d });
    return [VS.seat(null), VS.anim('idle', 200), VS.go(98, 58), VS.call(() => v.tween(door, 'open', 1, 250)), VS.go(98, 50), VS.fade(0, 250), VS.call(() => v.tween(door, 'open', 0, 300)),
      VS.wait(1200), VS.hold('docs'), VS.call(() => v.tween(door, 'open', 1, 250)), VS.fade(1, 250), VS.go(98, 60, 'carry'), VS.call(() => v.tween(door, 'open', 0, 300)),
      VS.anim('carry_f', 900, true), VS.go(d.seatX, 52, 'carry'), VS.go(d.seatX, d.seatY, 'carry'), VS.seat(d), VS.call(() => { d.papers = 4; me.hold = null; }), VS.hold(null), VS.anim('sit_happy', 800)];
  };
  VIG.replan = (v) => {
    const wb = v.prop('whiteboard', { x: 30, y: 18, w: 60, h: 26, floor: 58, erase: 0, seed: 1 });
    v.actor({ x: 60, y: 62 });
    return [VS.call(() => { wb.erase = 0; v.tween(wb, 'erase', 1, 1400, 'linear'); }), VS.anim('board_erase', 1500, true), VS.call(() => { wb.erase = 0; wb.seed += 1; }), VS.anim('board_write', 1800), VS.anim('back', 600)];
  };
  VIG.semantic = (v) => {
    const cab = v.prop('cards', { x: 84, base: VBASE, cards: 3, flash: 0 });
    const d = v.desk(6, { monitor: 'code' });
    v.actor({ seat: d });
    return [VS.anim('type', 700), VS.call(() => v.fly({ bmp: 'card', from: [d.seatX, d.y - 22], to: [cab.x + 12, cab.base - 32], ms: 900, arc: 22, onDone: () => { cab.cards += 1; cab.flash = v.scene.realT + 1500; } })), VS.anim('sit_up', 1900, true)];
  };
  VIG.deploy = (v) => {
    const backup = v.prop('backup', { x: 4, base: VBASE, lit: 0 });
    const mdoor = v.prop('mdoor', { x: 92, base: VBASE, w: 26, h: 40, glow: 0 });
    const cart = v.prop('cart', { x: 14, y: 70, box: 'box_sealed', follow: true });
    const me = v.actor({ x: 8, y: 62 });
    cart.actor = me;
    return [VS.call(() => { backup.lit = 1; }), VS.go(64, 62, 'push', 26), VS.anim('side_reach', 800, true),
      VS.call(() => { cart.box = null; mdoor.glow = 1; v.scene.emit('spark', mdoor.x + 12, mdoor.base - 24, 10, { color: PAL.green1 }); }), VS.anim('idle_happy', 900)];
  };
  VIG.rollback = (v) => {
    const mdoor = v.prop('mdoor', { x: 80, base: VBASE, w: 26, h: 40, glow: 1 });
    const me = v.actor({ x: 52, y: 62 });
    return [VS.turn(1), VS.anim('reach', 800, true),
      VS.call(() => { v.fly({ bmp: 'box', from: [mdoor.x + 10, mdoor.base - 26], to: [me.x, me.y - 22], ms: 600, arc: 10 }); }),
      VS.anim('catch', 900), VS.hold('box'), VS.anim('carry_f', 900, true), VS.call(() => { mdoor.glow = 0; me.hold = null; }), VS.hold(null)];
  };
  VIG.fault = (v) => {
    const mon = v.prop('monitor', { x: 66, y: 14, w: 42, h: 26, alarm: 0 });
    const pipe = v.prop('pipe', { x: 104, base: VBASE, out: 'idle' });
    const d = v.desk(4);
    v.actor({ seat: d });
    return [VS.seat(null), VS.icon({ kind: 'exclaim' }), VS.anim('shock', 500), VS.call(() => { mon.alarm = 1; }), VS.go(52, 58, 'run', 80), VS.icon(null),
      VS.anim('write', 1000), VS.hold('letter'), VS.go(96, 60, 'carry'), VS.turn(1), VS.anim('side_place', 700), VS.call(() => { pipe.letters = 1; }), VS.hold(null), VS.anim('idle', 600)];
  };
  VIG.wait_provider = (v) => {
    const d = v.desk(34, { monitor: 'idle' });
    v.prop('clock', { x: 58, y: 8, stopped: false });
    v.st.dark = 0.42;
    v.actor({ seat: d });
    return [VS.anim('sit_wait', 3400, true)];
  };
  VIG.hold_form = (v) => { v.actor({ x: 60, y: 66, data: { form: '待授权：重启服务' } }); return [VS.anim('hold_form', 3400, true)]; };
  VIG.review = (v) => {
    const tbl = v.prop('table', { x: 22, w: 76, y: VDESK, label: '检验台', top: PAL.white, face: '#c3a0f2', item: 'box_sealed', ticks: 0 });
    v.actor({ x: 58, y: VDESK, sprite: 'quality.reviewer' });
    return [VS.hold('pen_red'), VS.anim('write', 1200), VS.hold(null), VS.anim('inspect', 1000),
      VS.hold('stamp_green'), VS.anim('stamp_once', undefined, true), VS.hold(null),
      VS.call(() => { tbl.mark = { text: '通过', color: PAL.green2 }; }), VS.icon({ kind: 'check' }), VS.anim('idle_happy', 900), VS.icon(null)];
  };
  VIG.manager_out = (v) => {
    const pipe = v.prop('pipe', { x: 92, base: VBASE, out: 'flowing' });
    const tube = v.prop('tube', { x: 66, base: VBASE - 12, letters: 0 });
    const me = v.actor({ x: 24, y: 62, sprite: 'engineering.manager' });
    return [VS.go(82, 60, 'carry'), VS.turn(1), VS.anim('side_reach', 900, true),
      VS.go(58, 58, 'carry'), VS.turn(1), VS.hold('letter'), VS.anim('side_place', 800), VS.call(() => { tube.letters = 1; me.hold = null; }), VS.hold(null), VS.anim('idle', 600)];
  };

  P.createVignette = function createVignette(canvas, opts) {
    const name = opts.action;
    const setup = VIG[name];
    if (!setup) throw new Error('动作图鉴没有这个动作的小场景：' + name);
    const chosen = opts.sprite && !VIGNETTE_FIXED.has(name) ? opts.sprite : P.VIGNETTE_SPRITES[name];
    const deptOf = P.parseSpriteKey(chosen).dept;
    const D = P.DEPTS[deptOf];
    if (!D) throw new Error('动作图鉴的角色部门无效：' + deptOf);
    let v = null;
    let restartAt = null;

    const scene = P.createScene(canvas, { W: VW, H: VH, draw, update, interval: 33 });

    function build() {
      scene.actors.slice().forEach((a) => scene.removeActor(a));
      scene.particles = []; scene.flyers = []; scene.timers = []; scene.tweens = [];
      scene.frozen = false;
      v = {
        scene, sprite: chosen, props: [], st: { dark: 0, yellow: false, red: false, stop: false }, main: null,
        actor(o) {
          const a = scene.addActor({ id: 'v' + scene.actors.length, sprite: o.sprite || chosen, x: o.x || 0, y: o.y || 0, anim: o.anim || 'idle', facing: o.facing || 1, hold: o.hold || null, data: o.data || {} });
          if (o.seat) { a.seat = o.seat; a.x = o.seat.seatX; a.y = o.seat.seatY; if (!o.anim) a.anim = 'sit'; }
          if (!v.main) v.main = a;
          return a;
        },
        desk(x, o) {
          const d = Object.assign({ kind: 'desk', x, w: 52, y: VDESK, seatX: x + 16, seatY: VDESK, papers: 2 }, o || {});
          v.props.push(d);
          return d;
        },
        prop(kind, o) { const p = Object.assign({ kind }, o); v.props.push(p); return p; },
        after: (ms, fn) => scene.after(scene.reduced ? 0 : ms, fn),
        fly: (o) => scene.fly(o),
        tween: (obj, key, to, ms, ease) => scene.tween(obj, key, to, ms, ease)
      };
      let steps = setup(v);
      if (scene.reduced) {
        // 减少动画：停在关键动作的静止姿势
        const k = steps.findIndex((s) => s.key);
        if (k >= 0) steps = steps.slice(0, k).concat([Object.assign({}, steps[k], { ms: 1e9 })]);
      }
      scene.run(v.main, steps, { onDone: () => { restartAt = scene.realT + 700; } });
      restartAt = null;
    }

    function update() {
      if (restartAt !== null && scene.realT >= restartAt && !scene.reduced) build();
      scene.actors.forEach((a) => {
        if (a.anim === 'tea' && a.seat && Math.random() < 0.04) {
          const [hx, hy] = P.headTop(scene, a);
          scene.emit('steam', hx + 2, hy + 12, 1);
        }
      });
      v.props.forEach((p) => {
        if (p.kind === 'cart' && p.follow && p.actor) p.x = p.actor.x + (p.actor.facing > 0 ? 6 : -32);
      });
    }

    function draw(sc, c) {
      const t = sc.animT;
      // 墙与地面
      R(c, 0, 0, VW, VWALL, D.wall);
      for (let x = 3; x < VW; x += 10) R(c, x, 4, 1, VWALL - 8, D.wall2);
      R(c, 0, 0, VW, 3, D.trim);
      R(c, 0, VWALL - 4, VW, 4, D.trim);
      R(c, 0, VWALL, VW, VH - VWALL, D.floor);
      for (let y = VWALL + 6; y < VH; y += 7) R(c, 0, y, VW, 1, D.floor2);
      R(c, 0, VWALL, VW, 2, 'rgba(0,0,0,0.12)');
      // 墙上的物件
      v.props.forEach((p) => {
        if (p.kind === 'screen') {
          const lines = [{ k: '目标', v: '汇总报表' }, { k: '状态', v: '工作中' }];
          paint.crt(c, p.x, p.y, { w: p.w, h: p.h, lines, power: p.power, boot: p.boot !== undefined && p.boot < 1 ? p.boot : undefined }, t);
        }
        if (p.kind === 'whiteboard') paint.whiteboard(c, p.x, p.y, { w: p.w, h: p.h, floor: p.floor, title: '工作计划', lines: [0, 1].map((i) => ({ color: [PAL.blue3, PAL.red3, PAL.ink2][(i + (p.seed || 0)) % 3] })), sheet: p.sheet, erase: p.erase }, t);
        if (p.kind === 'cork') paint.corkboard(c, p.x, p.y, { w: p.w, h: p.h, notes: p.notes, done: p.done });
        if (p.kind === 'door') p.info = paint.door(c, p.x, p.base, { w: p.w, h: p.h, open: p.open || 0 });
        if (p.kind === 'clock') paint.clock(c, p.x, p.y, v.st.stop ? 15.5 * 3600000 : 15.5 * 3600000 + sc.realT * 60, { stopped: v.st.stop });
        if (p.kind === 'beacon') paint.beacon(c, p.x, p.y, { on: p.on, color: p.color }, t);
        if (p.kind === 'slots') {
          RB(c, p.x, p.y, 48, 24, PAL.grey5);
          P.text(c, '执行槽位 ' + p.used + '/' + p.total, p.x + 24, p.y + 6, { size: 5.5, weight: 700, align: 'center', color: PAL.white });
          for (let i = 0; i < p.total; i++) RB(c, p.x + 8 + i * 12, p.y + 13, 7, 7, i < p.used ? PAL.green2 : PAL.grey4);
        }
      });
      // 地面物件与小人：按深度排序
      const items = [];
      v.props.forEach((p) => {
        switch (p.kind) {
          case 'desk':
            items.push({ y: p.y - 1, draw: () => paint.chair(c, p.seatX, p.y, { color: D.shade }) });
            items.push({ y: p.y + 0.5, draw: () => drawVDesk(c, sc, p, t) });
            break;
          case 'cabinet': items.push({ y: p.base, draw: () => paint.cabinet(c, p.x, p.base, { open: p.open }, t) }); break;
          case 'archive': items.push({ y: p.base + 41, draw: () => paint.archive(c, p.x, p.base, { n: p.n, flash: sc.realT < (p.flash || 0) }, t) }); break;
          case 'terminal': items.push({ y: p.base, draw: () => drawVTerminal(c, p, t) }); break;
          case 'tray': items.push({ y: p.base, draw: () => paint.tray(c, p.x, p.base, { count: p.count }) }); break;
          case 'bin': items.push({ y: p.base, draw: () => paint.bin(c, p.x, p.base, { count: p.count }) }); break;
          case 'mailbox': items.push({ y: p.base, draw: () => { p.info = paint.mailbox(c, p.x, p.base, { count: p.count }, t); } }); break;
          case 'cards': items.push({ y: p.base, draw: () => paint.cardCabinet(c, p.x, p.base, { cards: p.cards, flash: sc.realT < (p.flash || 0), label: '语义记录' }, t) }); break;
          case 'rack': items.push({ y: p.base, draw: () => paint.rack(c, p.x, p.base, { on: p.on, alarm: p.alarm, h: 50, label: 'r3', blink: sc.realT < (p.flash || 0) }, t) }); break;
          case 'cart': items.push({ y: p.y - 8, draw: () => paint.cart(c, Math.round(p.x), p.y, { box: p.box }) }); break;
          case 'table': items.push({ y: p.y + 0.5, draw: () => drawVTable(c, p, t) }); break;
          case 'pipe': items.push({ y: p.base, draw: () => paint.pipe(c, p.x, p.base, { out: p.out, letters: p.letters, stopped: p.stopped }, t) }); break;
          case 'tube': items.push({ y: p.base, draw: () => paint.tube(c, p.x, p.base, { letters: p.letters }) }); break;
          case 'postbox': items.push({ y: p.base, draw: () => paint.postbox(c, p.x, p.base, { flag: p.flag }) }); break;
          case 'backup': items.push({ y: p.base, draw: () => paint.backup(c, p.x, p.base, { lit: p.lit, flash: p.flash }) }); break;
          case 'mdoor': items.push({ y: p.base, draw: () => paint.machineDoor(c, p.x, p.base, { w: p.w, h: p.h, glow: p.glow }, t) }); break;
          case 'toolpanel': items.push({ y: p.y + p.h, draw: () => paint.toolPanel(c, p.x, p.y, { w: p.w, h: p.h, buttons: p.buttons, lit: p.lit, labels: p.labels }) }); break;
          case 'trial': items.push({ y: p.y + 0.5, draw: () => drawVTrial(c, sc, p, t) }); break;
          case 'monitor': items.push({ y: p.y + p.h, draw: () => paint.monitor(c, p.x, p.y, { w: p.w, h: p.h, alarm: p.alarm }, t) }); break;
          default:
        }
      });
      sc.actors.forEach((a) => { if (!a.seat) items.push({ y: a.y, draw: () => P.drawActor(c, sc, a) }); });
      items.sort((p, q) => p.y - q.y);
      items.forEach((it) => it.draw());
      sc.drawParticles(c);
      sc.drawFlyers(c);
      // 灯光
      if (v.st.dark > 0.01) { c.fillStyle = 'rgba(14,12,34,' + v.st.dark.toFixed(3) + ')'; c.fillRect(0, 0, VW, VH); }
      if (v.st.yellow) { c.fillStyle = 'rgba(255,196,40,' + (sc.reduced ? 0.1 : 0.07 + 0.05 * Math.sin(t / 240)).toFixed(3) + ')'; c.fillRect(0, 0, VW, VH); }
      if (v.st.red) { c.fillStyle = 'rgba(255,50,50,' + (sc.reduced ? 0.1 : 0.06 + 0.06 * Math.max(0, Math.sin(t / 160))).toFixed(3) + ')'; c.fillRect(0, 0, VW, VH); }
      v.props.forEach((p) => {
        if (p.kind === 'beacon') paint.beaconLight(c, p.x, p.y, { on: p.on, color: p.color, reduced: sc.reduced, len: 60 }, t);
        if (p.kind === 'mailbox' && p.count > 0 && p.info) paint.glow(c, p.info.lamp[0], p.info.lamp[1], 6, PAL.yellow2, 0.7);
        if (p.kind === 'door' && p.sign && p.info) {
          const ss = P.signStyle(p.sign);
          P.sign(c, p.info.nail[0], p.info.nail[1] + 16, p.sign, { size: 6, bg: ss.bg, fg: ss.fg, stripe: ss.stripe, nail: p.info.nail[1], maxW: 70 });
        }
      });
      // 头顶图标、举牌、号码牌
      sc.actors.forEach((a) => {
        if (!a.visible) return;
        if (a.data.sign && a.anim === 'hold_sign') {
          const [hx, hy] = P.headTop(sc, a);
          const ss = P.signStyle(/凭据|缺少|模型/.test(a.data.sign) ? '待恢复' : a.data.sign);
          P.sign(c, hx, hy - 1, a.data.sign, { size: 7, bg: ss.bg, fg: ss.fg, stripe: ss.stripe, pole: 3, maxW: 116 });
        }
        if (a.data.form && a.anim === 'hold_form') {
          const [hx, hy] = P.headTop(sc, a);
          P.sign(c, hx, hy - 4, a.data.form, { size: 6.5, bg: PAL.white, stripe: PAL.orange2, maxW: 116 });
        }
        if (a.data.ticket) {
          const r = P.itemRect(sc, a);
          if (r) P.pixText(c, String(a.data.ticket), r[0] + r[2] / 2, r[1] + 0.5, PAL.ink, 'center');
        }
        P.drawIcon(c, sc, a);
      });
    }

    function drawVDesk(c, sc, d, t) {
      const a = sc.actors.find((x) => x.seat === d && x.visible);
      if (a) P.drawActor(c, sc, a, 'base');
      paint.desk(c, d.x, d.y, { w: d.w });
      let mode = d.monitor;
      if (!mode) mode = a && a.anim === 'type' ? 'code' : a && a.anim === 'write' ? 'diff' : 'idle';
      paint.deskItems(c, d.x, d.y, { w: d.w, papers: d.papers, folder: d.folder, docOnDesk: d.doc, box: d.box, card: d.card, cardResult: d.cardResult, cup: !(a && a.anim === 'tea'), monitor: mode, lamp: d.lamp || null, seed: d.shot === undefined ? d.x : d.shot }, t);
      if (d.docs) P.drawBitmap(c, 'docs', d.x + 6, d.y - 6);
      if (a) {
        c.save(); c.beginPath(); c.rect(0, 0, VW, d.y); c.clip();
        P.drawActor(c, sc, a, 'front');
        c.restore();
      }
    }

    function drawVTable(c, p, t) {
      paint.table(c, p.x, p.y, p.w, { top: p.top, face: p.face, edge: p.face ? P.mix(p.face, PAL.ink, 0.3) : undefined, label: p.label });
      const cx = p.x + Math.round(p.w / 2);
      if (p.lamp) {
        R(c, p.x + p.w - 10, p.y - 26, 2, 21, PAL.grey3); R(c, p.x + p.w - 20, p.y - 28, 12, 2, PAL.grey3);
        RB(c, p.x + p.w - 26, p.y - 30, 9, 5, PAL.grey4);
        paint.lightCone(c, p.x + p.w - 22, p.y - 25, 18, 26, '#fff4c4', 0.28);
      }
      if (p.checklist) {
        RB(c, p.x + 5, p.y - 6, 14, 5, PAL.white);
        for (let i = 0; i < 3; i++) R(c, p.x + 7 + i * 4, p.y - 5, 2, 2, i < (p.ticks || 0) ? PAL.green2 : PAL.grey2);
      }
      if (p.item === 'scroll_open') {
        RB(c, cx - 18, p.y - 6, 36, 5, PAL.paper);
        R(c, cx - 20, p.y - 7, 3, 7, PAL.wood3); R(c, cx + 17, p.y - 7, 3, 7, PAL.wood3);
        R(c, cx - 14, p.y - 4, 12, 1, PAL.pline);
      } else if (p.item) {
        const bm = P.bitmapDef(p.item);
        P.drawBitmap(c, p.item, cx - Math.floor(bm.rows[0].length / 2), p.y - 3 - bm.rows.length);
        if (p.item === 'box' && p.tape > 0 && p.tape < 1) R(c, cx - 1, p.y - 11, 2, Math.round(8 * p.tape), '#efe0b8');
      }
      if (p.mark) P.stampMark(c, cx + (p.item === 'scroll_open' ? 6 : 0), p.y - (p.item === 'scroll_open' ? 5 : 8), p.mark.text, p.mark.color, { size: 6 });
      if (p.slip) {
        P.drawBitmap(c, p.slip === 'release' ? 'slip_release' : 'slip_defect', cx + 14, p.y - 8);
        if (p.slipMark) P.stampMark(c, cx + 17, p.y - 8, p.slipMark.text, p.slipMark.color, { size: 6, rot: -0.2 });
      }
    }

    function drawVTerminal(c, p, t) {
      paint.terminal(c, p.x, p.base, { lever: p.lever, exit: p.exit, screen: p.screen, blink: p.blink }, t);
      if (!p.machine) return;
      P.text(c, p.machine, p.x + 14, p.base - 44, { size: 5, weight: 600, align: 'center', color: PAL.ink2, max: 60 });
      const y0 = p.base - 38;
      R(c, p.x + 14, y0, VW - (p.x + 14) - 6, 1, PAL.metal3);
      if (p.link) {
        const off = Math.floor(t / 130);
        for (let i = 0; i < 14; i++) R(c, p.x + 18 + ((i * 6 + off) % (VW - p.x - 32)), y0, 2, 1, PAL.yellow2);
      }
    }
    // 质检试用台：显示器嵌入最近一张截图的缩略图（像素边框）；没有截图时显示文字行
    function drawVTrial(c, sc, p, t) {
      const y = Math.round(p.y);
      const a = sc.actors.find((x) => x.seat && x.seat.trial && x.visible);
      if (a) P.drawActor(c, sc, a, 'base');
      paint.table(c, p.x, y, p.w, { top: PAL.white, face: '#c3a0f2', edge: P.mix('#c3a0f2', PAL.ink, 0.3), label: p.label });
      const mw = 30, mh = 22, mx = p.x + p.w - mw - 4, my = y - mh - 12;
      paint.shot(c, mx, my, mw, mh, { screenshot: p.screenshot, text_lines: p.lines }, t);
      (p.lines || []).forEach((s, i) => P.text(c, s, p.x + 4, y - 8 - i * 6, { size: 4.5, color: PAL.ink2, max: p.w - mw - 10 }));
      P.text(c, '第 ' + (p.step || 1) + ' 步', p.x + 8, y + 5, { size: 5, align: 'center', color: PAL.ink2 });
      if (a) {
        c.save();
        c.beginPath(); c.rect(0, 0, VW, y); c.clip();
        P.drawActor(c, sc, a, 'front');
        c.restore();
      }
    }

    function onReduced() { build(); }
    scene.spec.onReducedChange = onReduced;
    build();

    return {
      scene,
      pause: (on) => {
        const next = Boolean(on);
        // 滚出视口的画面先留下当前一帧，卡片上不会是一块空画布
        if (next && !scene.paused) scene.drawNow();
        scene.paused = next;
      },
      destroy: () => scene.destroy()
    };
  };

  // ===========================================================================
  // 10. 单个小人渲染（动作图鉴与静态预览）

  P.renderSprite = function renderSprite(canvas, spriteId, action, frame) {
    const animName = ANIMS[action] ? action : (P.ACTIONS[action] ? P.ACTIONS[action].anim : (P.BASE_MOTIONS[action] ? P.BASE_MOTIONS[action].anim : null));
    if (!animName) throw new Error('未知动作：' + action);
    const a = ANIMS[animName];
    const fr = a.frames[Math.abs(frame || 0) % a.frames.length];
    const hold = { stamp: 'stamp_valid', read_sit: 'doc', read_stand: 'note', carry: 'box_sealed', carry_f: 'box', give: 'card', side_place: 'doc', sit_card: 'card', board_pin: 'doc', note_pin: 'note', place: 'doc' }[animName] || null;
    const f = P.charFrame(spriteId, fr[0], null, hold);
    const c = canvas.getContext('2d');
    const k = Math.max(1, Math.floor(Math.min(canvas.width / CW, canvas.height / CH)));
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, canvas.width, canvas.height);
    c.imageSmoothingEnabled = false;
    const ox = Math.round((canvas.width - CW * k) / 2), oy = Math.round((canvas.height - CH * k) / 2);
    c.drawImage(f.base, ox, oy, CW * k, CH * k);
    c.drawImage(f.front, ox, oy, CW * k, CH * k);
    return fr[0];
  };
})();
