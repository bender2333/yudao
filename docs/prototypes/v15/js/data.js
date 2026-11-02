// 示例数据与场景：全部是假数据，不连任何服务。world() 每次返回一份新的数据，场景在上面改几处
(function () {
  'use strict';
  const Y15 = window.Y15;

  const NOW = '2026-11-01T14:30:00+08:00';
  const at = (d, hm) => '2026-' + (d === 'y' ? '10-31' : '11-01') + 'T' + hm + ':00+08:00';

  Y15.DEPTS = { product: '产品', engineering: '工程', quality: '质检', solo: '执行' };
  Y15.ITEM_COLORS = ['#e8505b', '#f7c948', '#3fc1e8', '#f27ec2', '#8fd14f', '#b98558'];
  Y15.SOURCE_KINDS = {
    rule: ['确定规则', '规则按事实算出来的，同样的输入总是同样的结果'],
    decision_model: ['决策模型', '由模型判断出来的，没有独立核验'],
    role_statement: ['角色陈述', '角色自己写下的说法，没有独立核验'],
    host_measurement: ['主机测量', '控制主机实际量到的数'],
    user: ['用户', '你自己输入或回答的']
  };
  Y15.OUTCOME_KINDS = {
    input: '用户输入', prd: 'PRD', delivery: '交付', defect: '缺陷记录', ask: '询问',
    answer: '回答', release: '放行', adopt: '采纳', open_close: '开环完成'
  };
  // 事项状态：[页面上的写法, 状态图标]
  Y15.ITEM_STATUS = {
    working: ['进行中', 'running'], waiting_slot: ['排队中 · 等执行槽位', 'waiting_slot'], waiting_model: ['等待模型服务', 'waiting_provider'],
    asking: ['等待回答', 'asking'], waiting_user: ['等你决定', 'pending'], waiting_resume: ['中断 · 待恢复', 'interrupted'],
    queued: ['排队中', 'queued'], stopped: ['已停止', 'cancelled'], adopted: ['已采纳', 'adopted'], open_closed: ['开环完成', 'held']
  };

  // 事件的来源种类按类型给默认值；事实上的事件一条一个位置，位置按时间排出
  const DEFAULT_SOURCE = {
    input: 'user', prd: 'role_statement', delivery: 'role_statement', defect: 'decision_model', ask: 'role_statement',
    answer: 'role_statement', release: 'rule', adopt: 'rule', open_close: 'rule'
  };

  function world() {
    const events = [];       // 手写的事件：{ key, project, item, type, label, source, by, at, detail }
    const ev = (key, project, item, type, label, source, by, time, detail) => events.push({ key, project, item, type, label, source, by, at: time, detail: detail || null });

    // ------------------------------------------------------------ 项目一：三个部门，按成果流转
    const orders = {
      id: 'orders', name: '订单系统重构', mode: '三部门', verifier: true,
      goal: '把订单模块重构成可导出、可分页、退款金额准确的版本',
      depts: ['product', 'engineering', 'quality'],
      items: [
        { id: 'w0', door: 'A-1', title: '订单状态机', color: 4, dept: null, status: 'adopted', round: 5, round_limit: 8, used: 13200, limit: 14400, reason: '质检放行后已采纳第 2 版' },
        { id: 'w1', door: 'A-4', title: '导出订单为 CSV', color: 0, dept: 'engineering', status: 'working', round: 3, round_limit: 8, used: 4320, limit: 14400, reason: '工程在写第 1 版交付' },
        { id: 'w2', door: 'A-3', title: '订单列表分页', color: 2, dept: 'quality', status: 'working', round: 4, round_limit: 8, used: 7500, limit: 14400, reason: '质检在核验交付第 2 版' },
        { id: 'w3', door: 'A-5', title: '退款金额取整', color: 1, dept: 'engineering', status: 'asking', round: 2, round_limit: 8, used: 1500, limit: 14400, reason: '工程向产品提出询问，等产品回答', since: at('t', '14:22') },
        { id: 'w4', door: 'A-6', title: '支付回调重试', color: 3, dept: 'engineering', status: 'waiting_slot', round: 0, round_limit: 8, used: 0, limit: 14400, reason: '三个执行槽位都占满了，下一个空出来就开始', since: at('t', '14:05') }
      ],
      deptState: {
        product: { text: '回答工程的询问（退款金额取整）', state: 'running', reason: '工程在「退款金额取整」上提出询问，产品正在回答', waits: [], role: '产品经理', model: 'deepseek-v3.2', items: ['w3'] },
        engineering: { text: '写导出功能（导出订单为 CSV）', state: 'running', reason: '一轮工作进行中，第 3 轮', role: '工程师', model: 'qwen3-coder-plus', items: ['w1', 'w3', 'w4'],
          waits: [{ item: 'w3', on: '产品对询问的回答', since: at('t', '14:22') }, { item: 'w4', on: '执行槽位', since: at('t', '14:05') }] },
        quality: { text: '核验订单列表分页（交付第 2 版）', state: 'running', reason: '一轮工作进行中，第 4 轮', waits: [], role: '质检员', model: 'glm-4.6', items: ['w2'] }
      },
      asks: [{ id: 'q1', item: 'w3', from: 'engineering', to: 'product', text: '退款金额取整：按分取整还是按元取整？银行侧按分记账。', at: at('t', '14:22'), key: 'o-ask1' }],
      interruptions: [],
      elapsed: { used: 26400, limit: 86400, key: 'elapsed-orders' },
      slots: { used: 3, limit: 3, waiting: 1 },
      provider_wait: [],
      hand: {
        product: { summaries: ['退款规则现状', '订单状态机的 PRD 摘要'], notes: 4 },
        engineering: { summaries: ['导出接口现状', '订单表结构', '分页实现的读后摘要'], notes: 7 },
        quality: { summaries: ['分页交付第 1 版的缺陷记录摘要'], notes: 3 }
      },
      outcomes: [
        { id: 'o-in0', item: 'w0', kind: 'input', text: '把订单状态改成明确的状态机，不再用散落的 if', from: 'user', to: 'product', at: at('y', '19:02') },
        { id: 'o-prd0', item: 'w0', kind: 'prd', version: 1, text: '订单状态机 PRD：6 个状态、9 条转换', from: 'product', to: 'engineering', at: at('y', '19:20'),
          detail: { type: 'diff', lines: ['+ 状态：待支付、已支付、发货中、已完成、已取消、已退款', '+ 转换：待支付 → 已支付（收到支付回调）', '+ 转换：已支付 → 已退款（退款成功）'] } },
        { id: 'o-del0a', item: 'w0', kind: 'delivery', version: 1, text: '状态机交付第 1 版', from: 'engineering', to: 'quality', at: at('y', '20:41'), concl: { kind: 'defect', text: '缺陷记录 2 条，退回工程' } },
        { id: 'o-def0', item: 'w0', kind: 'defect', version: 1, text: '已取消的订单还能被标记为已支付；转换表缺「发货中 → 已取消」', from: 'quality', to: 'engineering', at: at('y', '21:05'),
          detail: { type: 'receipt', lines: ['检验：状态转换用例 12 条，通过 10 条，未通过 2 条', '命令：npm test -- order-state，退出码 1'] } },
        { id: 'o-del0b', item: 'w0', kind: 'delivery', version: 2, text: '状态机交付第 2 版', from: 'engineering', to: 'quality', at: at('y', '21:58'), concl: { kind: 'release', text: '放行 · 检验覆盖 6/6' } },
        { id: 'o-rel0', item: 'w0', kind: 'release', version: 2, text: '质检放行交付第 2 版：检验 6 条全部有可执行的检验，全部通过', from: 'quality', to: 'output', at: at('y', '22:03') },
        { id: 'o-ad0', item: 'w0', kind: 'adopt', version: 2, text: '采纳第 2 版为项目当前成果', from: 'output', to: 'output', at: at('y', '22:04') },
        { id: 'o-prd2', item: 'w2', kind: 'prd', version: 1, text: '订单列表分页 PRD：每页 20 条，可选 50 / 100', from: 'product', to: 'engineering', at: at('t', '09:12'), detail: { type: 'diff', lines: ['+ 每页默认 20 条，可选 50、100', '+ 翻页保留当前筛选条件'] } },
        { id: 'o-del2a', item: 'w2', kind: 'delivery', version: 1, text: '分页交付第 1 版', from: 'engineering', to: 'quality', at: at('t', '10:30'), concl: { kind: 'defect', text: '缺陷记录 1 条，退回工程' } },
        { id: 'o-def2', item: 'w2', kind: 'defect', version: 1, text: '翻到最后一页再切换每页条数，页码超出范围', from: 'quality', to: 'engineering', at: at('t', '11:02'), detail: { type: 'receipt', lines: ['试用用例：翻页后切换每页条数，期望回到第 1 页，实际页码为 9'] } },
        { id: 'o-del2b', item: 'w2', kind: 'delivery', version: 2, text: '分页交付第 2 版', from: 'engineering', to: 'quality', at: at('t', '13:48'), concl: { kind: 'waiting', text: '质检正在核验' } },
        { id: 'o-prd1', item: 'w1', kind: 'prd', version: 1, text: '导出订单为 CSV：按创建时间倒序，最多 5 万行', from: 'product', to: 'engineering', at: at('t', '13:20'), detail: { type: 'diff', lines: ['+ 导出按钮放在订单列表右上角', '+ 文件名：orders-日期.csv，编码 UTF-8 带 BOM'] } },
        { id: 'o-prd3', item: 'w3', kind: 'prd', version: 1, text: '退款金额取整规则（取整位数待产品回答）', from: 'product', to: 'engineering', at: at('t', '14:08') },
        { id: 'o-ask1', item: 'w3', kind: 'ask', text: '退款金额取整：按分取整还是按元取整？', from: 'engineering', to: 'product', at: at('t', '14:22') }
      ]
    };
    // 手写事件：门牌、轮次、已用时间、状态
    orders.items.forEach((w) => {
      ev('door-' + w.id, 'orders', w.id, '事项创建', '事项「' + w.title + '」建立，门牌 ' + w.door, 'rule', '系统', at('y', '18:50'));
      ev('round-' + w.id, 'orders', w.id, '一轮工作开始', '「' + w.title + '」开始第 ' + Math.max(w.round, 1) + ' 轮', 'rule', '系统', at('t', '13:55'));
      ev('status-' + w.id, 'orders', w.id, '状态变化', '「' + w.title + '」现在的状态：' + Y15.ITEM_STATUS[w.status][0], 'rule', '系统', at('t', '14:10'));
    });
    ev('elapsed-orders', 'orders', null, '用时统计', '项目累计用时 7 小时 20 分（上限 24 小时）', 'host_measurement', '控制主机', at('t', '14:29'),
      { type: 'receipt', lines: ['回执：控制主机按各轮工作的开始与结束时间累加', '累计 26400 秒，上限 86400 秒'] });
    ['product', 'engineering', 'quality'].forEach((d) => ev('dept-orders-' + d, 'orders', null, '角色陈述', Y15.DEPTS[d] + '写下它此刻在做的事', 'role_statement', Y15.DEPTS[d], at('t', '14:25')));
    ev('slot-orders', 'orders', 'w4', '等待执行槽位', '「支付回调重试」排队等执行槽位', 'rule', '系统', at('t', '14:05'));

    // ------------------------------------------------------------ 项目二：等待模型服务、远程结果未知
    const report = {
      id: 'report', name: '内部报表工具', mode: '三部门', verifier: true,
      goal: '给运营做一个能按月出销售报表、定时发送的内部工具',
      depts: ['product', 'engineering', 'quality'],
      items: [
        { id: 'w5', door: 'B-2', title: '月度销售报表', color: 5, dept: 'engineering', status: 'waiting_model', round: 2, round_limit: 8, used: 2400, limit: 14400, reason: '模型服务限流，第 2 次重试（共 5 次），下一次 14:31', since: at('t', '14:26') },
        { id: 'w6', door: 'B-3', title: '部署到测试机', color: 0, dept: 'engineering', status: 'working', round: 1, round_limit: 8, used: 1260, limit: 14400, reason: '部署动作的结果未知，工程正在核实' },
        { id: 'w10', door: 'B-4', title: '报表筛选条件', color: 3, dept: 'quality', status: 'working', round: 2, round_limit: 8, used: 3000, limit: 14400, reason: '质检已决定放行，在等产品处理完新的输入', progress: '结论：放行（等产品处理完新输入）' },
        { id: 'w9', door: 'B-1', title: '数据源接入', color: 2, dept: null, status: 'adopted', round: 3, round_limit: 8, used: 9000, limit: 14400, reason: '放行时有 1 条开环的条件，已采纳第 1 版' }
      ],
      deptState: {
        product: { text: '处理你的新输入（筛选条件加「按区域」）', state: 'running', reason: '你在 14:20 发来新的输入，产品正在改 PRD', waits: [], role: '产品经理', model: 'deepseek-v3.2', items: ['w10'] },
        engineering: { text: '写月度销售报表', state: 'waiting_provider', reason: '模型服务限流，等重试', role: '工程师', model: 'qwen3-coder-plus', items: ['w5', 'w6'],
          waits: [{ item: 'w5', on: '模型服务（第 2 次重试，共 5 次）', since: at('t', '14:26') }, { item: 'w6', on: '部署动作的核实结果', since: at('t', '14:11') }] },
        quality: { text: '等待工作', state: 'waiting_work', reason: '放行在等产品处理完新的输入', progress: '结论：放行（等产品处理完新输入）', waits: [{ item: 'w10', on: '产品处理完发给它的新输入', since: at('t', '14:20') }], role: '质检员', model: 'glm-4.6', items: ['w10'] }
      },
      asks: [], interruptions: [],
      elapsed: { used: 12660, limit: 86400, key: 'elapsed-report' },
      slots: { used: 1, limit: 3, waiting: 0 },
      provider_wait: [{ dept: 'engineering', item: 'w5', model: 'qwen3-coder-plus', category: '请求过多（限流）', attempt: 2, of: 5, since: at('t', '14:26'), next: at('t', '14:31') }],
      remote: { engineering: [{ item: 'w6', action: '把报表服务部署到测试机 test-01', since: at('t', '14:11'), text: '部署命令超时，没有收到结果。正在核实机器上的版本（第 1 次，共 2 次）；核实不出来会请你决定。' }] },
      hand: {
        product: { summaries: ['运营的报表需求汇总'], notes: 2 },
        engineering: { summaries: ['数据库表结构', '报表样例'], notes: 5 },
        quality: { summaries: [], notes: 0 }
      },
      outcomes: [
        { id: 'o-r1', item: 'w9', kind: 'input', text: '先把销售数据从订单库接进来', from: 'user', to: 'product', at: at('y', '15:10') },
        { id: 'o-r2', item: 'w9', kind: 'delivery', version: 1, text: '数据源接入交付第 1 版', from: 'engineering', to: 'quality', at: at('y', '17:30'), concl: { kind: 'release', text: '放行 · 检验覆盖 7/8 · 开环 1' } },
        { id: 'o-r3', item: 'w9', kind: 'release', version: 1, text: '质检放行：8 条检验中 7 条可执行并通过，1 条（报表口径与财务一致）只能由人判断，作为开环的条件记下', from: 'quality', to: 'output', at: at('y', '17:42') },
        { id: 'o-r4', item: 'w9', kind: 'adopt', version: 1, text: '采纳第 1 版为项目当前成果', from: 'output', to: 'output', at: at('y', '17:43') },
        { id: 'o-r7', item: 'w10', kind: 'delivery', version: 2, text: '筛选条件交付第 2 版', from: 'engineering', to: 'quality', at: at('t', '13:58'), concl: { kind: 'release', text: '放行（等产品处理完新输入）' } },
        { id: 'o-r8', item: 'w10', kind: 'input', text: '筛选条件再加一个「按区域」', from: 'user', to: 'product', at: at('t', '14:20') },
        { id: 'o-r5', item: 'w5', kind: 'prd', version: 1, text: '月度销售报表：按商品类目汇总，含环比', from: 'product', to: 'engineering', at: at('t', '12:40') },
        { id: 'o-r6', item: 'w6', kind: 'prd', version: 1, text: '部署到测试机 test-01，保留上一版以便回滚', from: 'product', to: 'engineering', at: at('t', '13:50') }
      ]
    };
    report.items.forEach((w) => {
      ev('door-' + w.id, 'report', w.id, '事项创建', '事项「' + w.title + '」建立，门牌 ' + w.door, 'rule', '系统', at('y', '14:50'));
      ev('round-' + w.id, 'report', w.id, '一轮工作开始', '「' + w.title + '」开始第 ' + Math.max(w.round, 1) + ' 轮', 'rule', '系统', at('t', '13:55'));
      ev('status-' + w.id, 'report', w.id, '状态变化', '「' + w.title + '」现在的状态：' + Y15.ITEM_STATUS[w.status][0], 'rule', '系统', at('t', '14:26'));
    });
    ev('elapsed-report', 'report', null, '用时统计', '项目累计用时 3 小时 31 分（上限 24 小时）', 'host_measurement', '控制主机', at('t', '14:29'));
    ev('provider-w5', 'report', 'w5', '模型服务失败', '模型服务返回「请求过多」，第 2 次重试', 'host_measurement', '控制主机', at('t', '14:26'),
      { type: 'receipt', lines: ['回执：HTTP 429，服务商 DeepSeek 兼容接口', '重试间隔 5 分钟的 1/5 起步，下一次 14:31'] });
    ev('remote-w6', 'report', 'w6', '动作结果未知', '部署命令超时，没有收到结果', 'host_measurement', '控制主机', at('t', '14:11'),
      { type: 'receipt', lines: ['回执：到 test-01 的连接在 120 秒后超时', '核实方法：读机器上运行的版本号'] });
    ['product', 'engineering', 'quality'].forEach((d) => ev('dept-report-' + d, 'report', null, '角色陈述', Y15.DEPTS[d] + '写下它此刻在做的事', 'role_statement', Y15.DEPTS[d], at('t', '14:25')));

    // ------------------------------------------------------------ 项目三：一个角色直做，没有核验角色
    const blog = {
      id: 'blog', name: '个人博客', mode: '一个角色直做', verifier: false,
      goal: '把博客搬到新的静态站点，文章和链接都不丢',
      depts: ['solo'],
      items: [
        { id: 'w7', door: 'C-1', title: '迁移文章', color: 2, dept: null, status: 'open_closed', round: 2, round_limit: 6, used: 3300, limit: 7200, reason: '定义里没有核验角色，交完成后直接采纳' },
        { id: 'w8', door: 'C-2', title: '更新首页文案', color: 1, dept: 'solo', status: 'working', round: 1, round_limit: 6, used: 420, limit: 7200, reason: '通才在改首页文案' }
      ],
      deptState: { solo: { text: '改首页文案', state: 'running', reason: '一轮工作进行中，第 1 轮', waits: [], role: '通才', model: 'deepseek-v3.2', items: ['w8'] } },
      asks: [], interruptions: [],
      elapsed: { used: 3720, limit: 28800, key: 'elapsed-blog' },
      slots: { used: 1, limit: 3, waiting: 0 },
      provider_wait: [],
      hand: { solo: { summaries: ['旧站点的文章清单'], notes: 3 } },
      outcomes: [
        { id: 'o-b1', item: 'w7', kind: 'input', text: '把旧站点的 128 篇文章迁到新站点', from: 'user', to: 'solo', at: at('t', '10:00') },
        { id: 'o-b2', item: 'w7', kind: 'delivery', version: 1, text: '文章迁移交付：128 篇已转成新格式，链接保持', from: 'solo', to: 'output', at: at('t', '11:10'), concl: { kind: 'open', text: '开环完成 · 没有核验角色 · 是否外包：否' } },
        { id: 'o-b3', item: 'w7', kind: 'open_close', version: 1, text: '开环完成并采纳第 1 版；记录上写开环完成，不写放行', from: 'output', to: 'output', at: at('t', '11:11') }
      ]
    };
    blog.items.forEach((w) => {
      ev('door-' + w.id, 'blog', w.id, '事项创建', '事项「' + w.title + '」建立，门牌 ' + w.door, 'rule', '系统', at('t', '09:55'));
      ev('round-' + w.id, 'blog', w.id, '一轮工作开始', '「' + w.title + '」开始第 ' + Math.max(w.round, 1) + ' 轮', 'rule', '系统', at('t', '14:00'));
      ev('status-' + w.id, 'blog', w.id, '状态变化', '「' + w.title + '」现在的状态：' + Y15.ITEM_STATUS[w.status][0], 'rule', '系统', at('t', '14:00'));
    });
    ev('elapsed-blog', 'blog', null, '用时统计', '项目累计用时 1 小时 2 分（上限 8 小时）', 'host_measurement', '控制主机', at('t', '14:29'));
    ev('dept-blog-solo', 'blog', null, '角色陈述', '通才写下它此刻在做的事', 'role_statement', '通才', at('t', '14:25'));

    const projects = [orders, report, blog];

    // outcomes 变成事件，并给全部事件排出全局位置
    const outcomeLabel = (o) => Y15.OUTCOME_KINDS[o.kind] + (o.version ? ' 第 ' + o.version + ' 版' : '') + '：' + o.text;
    projects.forEach((p) => p.outcomes.forEach((o) => {
      o.project = p.id;
      events.push({ key: o.id, project: p.id, item: o.item, type: Y15.OUTCOME_KINDS[o.kind], label: outcomeLabel(o), source: o.source || DEFAULT_SOURCE[o.kind],
        by: o.from === 'user' ? '用户' : o.from === 'output' ? '系统' : Y15.DEPTS[o.from], at: o.at, detail: o.detail || null });
    }));
    events.sort((a, b) => a.at.localeCompare(b.at));
    events.forEach((e, i) => { e.pos = 4200 + i * 3; });
    const byKey = Object.fromEntries(events.map((e) => [e.key, e]));

    // 离开期间的报告（上次查看 昨晚 22:10）：前八项沿用，后四项是新增
    const R = (key) => byKey[key].pos;
    const report_ = {
      last_seen: at('y', '22:10'),
      summary: [
        { id: 'done', label: '完成与放行的事项', value: 2, unit: '项', detail: '订单状态机放行并采纳；数据源接入此前已采纳', refs: [R('o-rel0'), R('o-ad0')] },
        { id: 'open_release', label: '带开环条件的放行', value: 1, unit: '项', detail: '数据源接入：放行时有 1 条检验只能由人判断', refs: [R('o-r3')], isOpenRelease: true },
        { id: 'rework', label: '返工与询问', value: 4, unit: '次', detail: '缺陷记录 2 份（共退回工程 2 次），询问 1 次，回答 1 次', refs: [R('o-def0'), R('o-def2'), R('o-ask1')] },
        { id: 'converge', label: '收敛状态的变化', value: 1, unit: '项', detail: '订单列表分页：收敛中 → 停滞', refs: [R('status-w2')] },
        { id: 'limit_fail', label: '达到上限的失败', value: 1, unit: '项', detail: '部署到测试机：核实次数用到上限前先停下，等你决定', refs: [R('remote-w6')], isNew: true,
          rows: ['部署到测试机（内部报表工具）：部署动作结果未知，自动核实 1 次，上限 2 次'] },
        { id: 'open_closed', label: '开环完成的事项', value: 1, unit: '项', detail: '迁移文章：没有核验角色', refs: [R('o-b3')], isNew: true,
          rows: ['迁移文章（个人博客）：是否外包：否。定义里没有核验角色，交完成后直接采纳，记录上写「开环完成」。'] },
        { id: 'auto_adjust', label: '参数的自动调节', value: 2, unit: '处', detail: '重试间隔、执行槽位上限', refs: [R('provider-w5')], isNew: true,
          rows: ['等待模型服务的重试间隔：5 分钟 → 3 分钟（连续 3 次限流后，由规则调整）', '执行槽位上限：保持 3，没有改动，只记下了「槽位占满 25 分钟」'] },
        { id: 'repeat_back', label: '反复退回的提醒', value: 1, unit: '项', detail: '订单状态机被退回 2 次，已经放行', refs: [R('o-def0'), R('o-rel0')], isNew: true,
          rows: ['订单状态机：同一计划条目被缺陷记录退回 2 次，最近一次意见「已取消的订单还能被标记为已支付」。已在第 2 版放行。'] }
      ]
    };

    // 决定：正常运行时没有，场景里加
    const decisions = [];

    return { now: NOW, projects, events, byKey, report: report_, decisions, desktop: null, versions: { server: 12, page: 12 }, interrupted: false };
  }

  // ---------------------------------------------------------------- 决定

  const DEC = {
    definitions_changed: () => ({
      id: 'd-def', kind: 'definitions_changed', label: '定义版本不同', project: 'orders', item: 'w3', at: at('t', '14:12'),
      blocks: '挡住「退款金额取整」；同一项目中排在它后面的事项 1 个',
      changed: [
        { name: '产品 · 角色材料', type: '角色定义', before: 'a3f9c1', now: '7be204' },
        { name: '质检 · 检验规范', type: '角色定义', before: '5d20e8', now: 'c91b47' },
        { name: '路由（谁开工、一轮怎么结束）', type: '组织定义', before: '按成果 · 11ab90', now: '直做 · e4407d' }
      ],
      unchanged: 6,
      basis: '这个事项开始时记下了每份定义各自的摘要，现在加载的定义里有 3 份和当时不一样。路由属于组织定义，改了路由也走这张卡片。',
      options: [{ id: 'continue', label: '按现在的定义继续', primary: true }, { id: 'stop', label: '停止这个事项' }]
    }),
    role_choice: () => ({
      id: 'd-ask', kind: 'role_choice', label: '角色拿不准', project: 'report', item: 'w5', at: at('t', '14:18'),
      blocks: '只挡住产品的这一轮，其他事项照常',
      question: '「月度销售报表」里，退款订单算不算销售额？需求文字里两处说法不一致。',
      from: '产品经理',
      options: [{ id: 'net', label: '扣除退款，按净额算', primary: true }, { id: 'gross', label: '不扣除，按成交额算' }, { id: 'both', label: '两列都出' }]
    }),
    waiting_resume: (item, project, when) => ({
      id: 'd-res-' + item, kind: 'waiting_resume', label: '待恢复', project, item, at: when,
      blocks: '挡住这个事项',
      options: [{ id: 'resume', label: '从中断的位置继续', primary: true }, { id: 'stop', label: '停止这个事项' }]
    })
  };

  // ---------------------------------------------------------------- 场景

  function mark(w, pid, iid, patch) {
    const item = w.projects.find((p) => p.id === pid).items.find((i) => i.id === iid);
    Object.assign(item, patch);
    return item;
  }

  Y15.SCENARIOS = [
    { id: 'normal', label: '三部门正常运行', go: '#/home', build: (w) => w },
    { id: 'solo', label: '一个角色直做，以开环完成结束', go: '#/p/blog', build(w) {
      w.projects = w.projects.filter((p) => p.id === 'blog');
      return w;
    } },
    { id: 'interrupted', label: '有中断待恢复', go: '#/p/orders', build(w) {
      const p = w.projects.find((x) => x.id === 'orders');
      mark(w, 'orders', 'w1', { status: 'waiting_resume', reason: '服务重启时这一轮工作被打断，等你决定是否从中断处继续' });
      mark(w, 'orders', 'w2', { status: 'waiting_resume', reason: '服务重启时这一轮工作被打断，等你决定是否从中断处继续' });
      p.deptState.engineering.state = 'interrupted'; p.deptState.engineering.text = '被中断：写导出功能'; p.deptState.engineering.reason = '服务重启时被打断';
      p.deptState.quality.state = 'interrupted'; p.deptState.quality.text = '被中断：核验订单列表分页'; p.deptState.quality.reason = '服务重启时被打断';
      p.interruptions = [
        { item: 'w1', dept: 'engineering', what: '工程的一轮工作（第 3 轮）', at: at('t', '14:16'), why: '控制主机重启（升级后自动重启）', state: '待恢复，等你决定', key: 'int-w1' },
        { item: 'w2', dept: 'quality', what: '质检的一轮工作（第 4 轮）', at: at('t', '14:16'), why: '控制主机重启（升级后自动重启）', state: '待恢复，等你决定', key: 'int-w2' }
      ];
      w.events.push({ key: 'int-w1', project: 'orders', item: 'w1', type: '工作中断', label: '控制主机重启，「导出订单为 CSV」的一轮工作被打断', source: 'host_measurement', by: '控制主机', at: at('t', '14:16'),
        detail: { type: 'receipt', lines: ['回执：服务进程在 14:16 退出并重新启动', '被打断的一轮工作：工程第 3 轮，已写入但未交付的内容保存在运行工作区'] }, pos: 9001 });
      w.events.push({ key: 'int-w2', project: 'orders', item: 'w2', type: '工作中断', label: '控制主机重启，「订单列表分页」的一轮工作被打断', source: 'host_measurement', by: '控制主机', at: at('t', '14:16'), detail: null, pos: 9002 });
      w.byKey['int-w1'] = w.events[w.events.length - 2]; w.byKey['int-w2'] = w.events[w.events.length - 1];
      w.decisions.push(DEC.waiting_resume('w1', 'orders', at('t', '14:17')), DEC.waiting_resume('w2', 'orders', at('t', '14:17')));
      return w;
    } },
    { id: 'asking', label: '有等待回答的决定', go: '#/home', build(w) {
      w.decisions.push(DEC.definitions_changed(), DEC.role_choice());
      mark(w, 'orders', 'w3', { status: 'waiting_user', reason: '定义版本不同，等你决定继续还是停止', dept: 'engineering' });
      mark(w, 'report', 'w5', { status: 'waiting_user', reason: '产品拿不准退款订单算不算销售额，等你回答' });
      return w;
    } },
    { id: 'desktop', label: '桌面会话进行中', go: '#/home', build(w) {
      w.desktop = { dept: 'quality', project: 'orders', item: 'w2', what: '在桌面上试用订单列表分页', since: at('t', '14:26') };
      const q = w.projects.find((x) => x.id === 'orders').deptState.quality;
      q.text = '在桌面上试用订单列表分页'; q.reason = '桌面会话进行中，本机桌面交给质检使用';
      return w;
    } },
    { id: 'mismatch', label: '版本不一致', go: '#/home', build(w) {
      w.versions = { server: 12, page: 11 };
      return w;
    } }
  ];

  Y15.buildWorld = function buildWorld(id) {
    const s = Y15.SCENARIOS.find((x) => x.id === id) || Y15.SCENARIOS[0];
    return s.build(world());
  };
})();
