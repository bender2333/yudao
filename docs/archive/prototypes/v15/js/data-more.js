// 其余页面的假数据：机器、运行、工具、资料、观测、设置、恢复。项目、事项、部门与 data.js 对得上；状态仍从当前场景的数据里读
(function () {
  'use strict';
  const Y15 = window.Y15;
  const at = (d, hm) => '2026-' + (d === 'y' ? '10-31' : '11-01') + 'T' + hm + ':00+08:00';

  const X = Y15.EXTRA = {};

  // ---------------------------------------------------------------- 机器（可在页面上改，刷新页面回到原样）
  X.machines = () => [
    { id: 'host', name: '控制主机', kind: '控制主机', address: '127.0.0.1:8765', purpose: '运行 Yudao 服务', online: true, beat: at('t', '14:30'), projects: ['orders', 'report', 'blog'], fixed: true },
    { id: 'desk-01', name: '办公室台式机', kind: '台式机', address: '192.168.1.20:8800', purpose: '跑桌面试用', online: true, beat: at('t', '14:29'), projects: ['orders'] },
    { id: 'test-01', name: '测试机 test-01', kind: '树莓派', address: '192.168.1.41:8800', purpose: '部署内部报表工具做冒烟', online: false, beat: at('t', '14:08'), projects: ['report'] }
  ];

  // ---------------------------------------------------------------- 运行
  // 占着执行槽位的事项（项目里的 slots.used 与它对得上）
  X.slotHolders = { orders: ['w1', 'w2', 'w3'], report: ['w6'], blog: ['w8'] };
  X.disk = { free_gb: 182, threshold_gb: 50, snapshots_gb: 14.6, workspaces_gb: 9.2 };

  // ---------------------------------------------------------------- 工具与扩展
  X.tools = {
    network: { scope: '部门可以取回任意地址的网页；只读取，不提交表单。', recent: [
      { at: at('t', '13:12'), url: 'https://docs.example-pay.com/refund/rounding', project: 'orders', result: '成功，取回 18 KB' },
      { at: at('t', '11:40'), url: 'https://nodejs.org/api/stream.html', project: 'orders', result: '成功，取回 212 KB' },
      { at: at('y', '17:05'), url: 'https://internal.example.com/sales-schema', project: 'report', result: '失败：连接超时' }
    ] },
    mcp: [
      { name: 'orders-db', project: 'orders', transport: '本机进程：orders-db-mcp', depts: ['engineering', 'quality'], last: { ok: true, text: '连接正常，3 个工具', at: at('t', '14:00') },
        tools: [['query_orders', '按条件只读查询订单表'], ['describe_table', '查看表结构'], ['explain_query', '查看查询计划']] },
      { name: 'warehouse', project: 'report', transport: '网络地址：https://warehouse.example.com/mcp', depts: ['product', 'engineering'], last: { ok: false, text: '连接失败：证书已过期', at: at('t', '13:40') },
        tools: [['list_metrics', '列出指标'], ['run_report_sql', '运行只读的报表查询']] }
    ],
    browser: { note: '质检用来打开页面、点击、填写、读取页面结构；模型不看图像时只给页面结构，不给截图。', tools: [
      ['browser_open', '打开一个网址'], ['browser_click', '点击页面上的元素'], ['browser_type', '在输入框里输入文字'], ['browser_read', '读取页面结构'], ['browser_take_screenshot', '截图（需要模型能看图像）']] },
    computer: { note: '质检在本机桌面上试用桌面程序；使用期间每一页顶部都有「停止使用」一条。需要模型能看图像。', screen: '1280 × 800，用办公室台式机的虚拟屏幕', tools: [
      ['screen_capture', '截一张屏幕'], ['mouse_click', '点击一个位置'], ['mouse_drag', '拖动'], ['keyboard_type', '输入文字'], ['keyboard_key', '按键'], ['scroll', '滚动']] },
    observers: [
      { name: '用量统计', scope: '所有项目的模型请求事件' },
      { name: '教训发现', scope: '所有项目的缺陷记录与返工' }
    ]
  };

  // ---------------------------------------------------------------- 预留入口
  X.reserved = {
    meta: { title: '元观察', stage: '阶段六', outcome: '根据运行证据提出组织或规则的修改，经独立评价、限定采用，可以撤销；部门之间的流转有独立的流程审查。' },
    evolution: { title: '演化', stage: '阶段六', outcome: '根据运行证据提出组织或规则的修改，经独立评价、限定采用，可以撤销。' },
    lessons: { title: '经验', stage: '持续改进', outcome: '从重复出现的问题里形成经过验证、可以停用的跨任务经验，并证明有收益。' }
  };

  // ---------------------------------------------------------------- 资料：成果之外的补充
  X.delivery = {
    'o-del0b': {
      summary: '状态机集中在 order-state.ts，转换表 9 条；已取消订单不能再标记为已支付；补了发货中到已取消的转换。',
      files: [['src/orders/order-state.ts', 4210], ['src/orders/transitions.ts', 1180], ['test/order-state.test.ts', 3560]],
      git: { commit: '7be2041', parent: 'a3f9c15', stat: '3 个文件，+212 -37' },
      diff: '@@ src/orders/order-state.ts\n-  if (status === "paid" && cancelled) status = "paid";\n+  if (isCancelled(order)) throw new IllegalTransition(order.status, "paid");\n@@ src/orders/transitions.ts\n+  { from: "shipping", to: "cancelled", on: "cancel" },'
    },
    'o-del2b': { summary: '分页改为服务端分页，切换每页条数时回到第 1 页，筛选条件在翻页时保留。', files: [['src/orders/list.ts', 2890], ['src/ui/Pager.tsx', 1740]], git: { commit: 'c91b470', parent: '5d20e81', stat: '2 个文件，+96 -22' }, diff: '@@ src/ui/Pager.tsx\n-  setPage(page);\n+  setPage(1);  // 切换每页条数后回到第 1 页' }
  };
  // 逐条检验结果：key 是放行的成果；method: run 可执行、model 靠模型阅读、human 只能由人判断
  X.criteria = {
    'o-rel0': { snapshot: 'f20b9d3', rows: [
      ['C1', '待支付的订单收到支付回调后变为已支付', 'run', 'pass', 'npm test -- order-state'], ['C2', '已取消的订单不能被标记为已支付', 'run', 'pass', 'npm test -- order-state'],
      ['C3', '发货中的订单可以取消', 'run', 'pass', 'npm test -- order-state'], ['C4', '已退款是终态', 'run', 'pass', 'npm test -- order-state'],
      ['C5', '不合法的转换抛出明确的错误', 'run', 'pass', 'npm test -- order-state'], ['C6', '转换表与 PRD 一致', 'run', 'pass', '对照脚本 check-transitions']] },
    'o-r3': { snapshot: '2c71e0a', rows: [
      ['C1', '能从订单库读到销售数据', 'run', 'pass', '集成测试 source-orders'], ['C2', '增量同步不重复', 'run', 'pass', '集成测试 source-incremental'],
      ['C3', '字段类型与订单库一致', 'run', 'pass', '结构对照'], ['C4', '空数据时不报错', 'run', 'pass', '集成测试 source-empty'],
      ['C5', '同步失败会留下记录', 'run', 'pass', '集成测试 source-fail'], ['C6', '凭据不写进日志', 'run', 'pass', '日志扫描'],
      ['C7', '连接池耗尽时有清楚的提示', 'run', 'pass', '集成测试 source-pool-exhausted'], ['C8', '报表口径与财务一致', 'human', 'not_run', '只能由人判断，作为开环的条件记下']] }
  };
  X.notes = {
    orders: [{ title: '银行侧按分记账', dept: 'product', at: at('t', '14:10'), text: '对账规则：渠道侧金额单位是分，订单表 amount 字段也是分，取整不要做元级舍入。' },
      { title: '导出文件要能被 Excel 直接打开', dept: 'engineering', at: at('t', '13:25'), text: 'CSV 用 UTF-8 带 BOM；日期用 yyyy-MM-dd HH:mm:ss。' }],
    report: [{ title: '运营的报表需求汇总', dept: 'product', at: at('y', '15:30'), text: '按月出销售报表，按商品类目汇总，需要环比；每月 1 号早上 9 点前发出。' }],
    blog: [{ title: '旧站点的文章清单', dept: 'solo', at: at('t', '09:58'), text: '共 128 篇，分 6 个栏目；链接格式为 /posts/年/月/标题。' }]
  };
  X.oldRuns = { orders: [{ item: 'w0', id: 'run-0a31', ver: '0.9.2', state: '已完成', events: [[at('y', '19:03'), '事项创建', '建立事项「订单状态机」'], [at('y', '22:04'), '采纳', '采纳第 2 版']] }] };

  // ---------------------------------------------------------------- 观测：模型请求
  // 每个部门的模型接线（和部门页一致）
  X.wiring = {
    product: { provider: 'DeepSeek', model: 'deepseek-v3.2', conn: 'api.deepseek.example', proto: 'Chat Completions', base: 'https://api.deepseek.example/v1', window: 128000, out: 8192, cred: 'API_DEEPSEEK_EXAMPLE_KEY', cv: 3, level: '中', src: '部门使用' },
    engineering: { provider: '阿里云百炼', model: 'qwen3-coder-plus', conn: 'dashscope.example', proto: 'Chat Completions', base: 'https://dashscope.example/v1', window: 262144, out: 32768, cred: 'DASHSCOPE_EXAMPLE_KEY', cv: 2, level: '高', src: '部门使用' },
    quality: { provider: '智谱', model: 'glm-4.6', conn: 'open.zhipu.example', proto: 'Chat Completions', base: 'https://open.zhipu.example/v4', window: 204800, out: 32768, cred: 'OPEN_ZHIPU_EXAMPLE_KEY', cv: 1, level: '中', src: '部门使用' },
    solo: { provider: 'DeepSeek', model: 'deepseek-v3.2', conn: 'api.deepseek.example', proto: 'Chat Completions', base: 'https://api.deepseek.example/v1', window: 128000, out: 8192, cred: 'API_DEEPSEEK_EXAMPLE_KEY', cv: 3, level: '中', src: '部门使用' }
  };
  // [id, 项目, 事项, 部门, 角色, 类型, 状态, 开始, 耗时毫秒, 输入, 输出, 缓存读取, 错误, 同组编号]
  const A = (id, project, item, dept, role, kind, status, start, ms, input, output, cache, err, group) => ({ id, project, item, dept, role, kind, status, start, ms, input, output, cache, err: err || null, group: group || null });
  X.attempts = [
    A('r-2041', 'orders', 'w1', 'engineering', '工程师', 'work', 'running', at('t', '14:27'), null, 31200, null, 24000),
    A('r-2040', 'orders', 'w3', 'product', '产品经理', 'work', 'succeeded', at('t', '14:23'), 41000, 18420, 912, 15200),
    A('r-2039', 'orders', 'w3', 'engineering', '工程师', 'collaboration', 'succeeded', at('t', '14:22'), 9000, 6200, 410, 0),
    A('r-2038', 'orders', 'w2', 'quality', '质检员', 'work', 'succeeded', at('t', '14:21'), 52000, 26110, 1530, 22000),
    A('r-2037', 'orders', 'w1', 'engineering', '工程师', 'compaction', 'succeeded', at('t', '14:09'), 18000, 41000, 2100, 0),
    A('r-2036', 'orders', 'w2', 'quality', '质检员', 'work', 'succeeded', at('t', '13:53'), 47000, 24800, 1210, 20400, null, 'g-1'),
    A('r-2035', 'orders', 'w2', 'quality', '质检员', 'work', 'failed', at('t', '13:50'), 120000, null, null, null, { category: '超时', code: 'idle_timeout', text: '120 秒没有收到新数据，已放弃这次请求' }, 'g-1'),
    A('r-2034', 'orders', 'w0', 'product', '产品经理', 'work', 'succeeded', at('y', '19:10'), 38000, 12900, 1480, 8000),
    A('r-2051', 'report', 'w5', 'engineering', '工程师', 'work', 'failed', at('t', '14:26'), 2300, 19800, null, 0, { category: '限流', code: 'HTTP 429', text: '请求过多，请稍后再试' }, 'g-2'),
    A('r-2050', 'report', 'w5', 'engineering', '工程师', 'work', 'failed', at('t', '14:21'), 2100, 19700, null, 0, { category: '限流', code: 'HTTP 429', text: '请求过多，请稍后再试' }, 'g-2'),
    A('r-2049', 'report', 'w10', 'product', '产品经理', 'work', 'running', at('t', '14:21'), null, 9800, null, 6000),
    A('r-2048', 'report', 'w10', 'quality', '质检员', 'work', 'succeeded', at('t', '13:59'), 36000, 14100, 760, 9000),
    A('r-2047', 'report', 'w6', 'engineering', '工程师', 'work', 'succeeded', at('t', '13:58'), 44000, 21300, 1330, 16800),
    A('r-2060', 'blog', 'w8', 'solo', '通才', 'work', 'running', at('t', '14:28'), null, 8200, null, 5000),
    A('r-2059', 'blog', 'w7', 'solo', '通才', 'work', 'succeeded', at('t', '11:00'), 61000, 22400, 3100, 14000)
  ];
  X.sectionsOf = (a) => [
    ['部门提示', '版本 3', true, '这个部门每次请求都带'], ['事项要求', '', true, '这个事项现在的 PRD'], ['手边的摘要', '', a.kind !== 'collaboration', '本部门留着用的摘要'],
    ['历史对话', '', a.kind !== 'compaction', '上一轮之后的对话'], ['项目材料', '', false, '项目材料只记录原文，不放进请求']
  ];
  X.outputOf = (a) => (a.status === 'failed' ? '' : a.kind === 'compaction' ? '（压缩结果）前 3 轮：读取导出接口现状，确定按创建时间倒序、最多 5 万行；决定新增 exportOrdersCsv。' : '读到交付，先对照缺陷记录逐条核对，再运行试用用例。\n用例通过，继续核验筛选条件在翻页时是否保留。');

  // ---------------------------------------------------------------- 观测：循环（收敛状态）
  // 每个事项的实例：[层, 名称, 轮次, 已用, 上限, 状态, 停止原因, 依据]
  X.loopStates = { converging: ['收敛中', 'green'], stalled: ['停滞', 'amber'], oscillating: ['震荡', 'orange'], drifting: ['漂移', 'violet'], at_bound: ['达到边界', 'red'], not_judged: ['不判定', 'muted'], done: ['已结束', 'muted'] };
  X.loops = {
    orders: { project: ['项目循环', '订单系统重构', '5 项事项', '累计 7 小时 20 分 / 24 小时', 'converging', '', '5 个事项里 1 个已采纳，3 个进行中，进度在增加'],
      items: { w0: [['run', '第 1 次运行', 5, '13200 / 14400 秒', 'done', '质检放行后采纳', '']], w1: [['run', '第 1 次运行', 3, '4320 / 14400 秒', 'converging', '', '交付的检验通过数从 2 增加到 4'], ['activation', '工程 · 第 3 轮', 3, '14 步', 'converging', '', '']],
        w2: [['run', '第 1 次运行', 4, '7500 / 14400 秒', 'stalled', '', '连续两轮缺陷记录的条数没有减少（1 → 1）'], ['activation', '质检 · 第 4 轮', 4, '9 步', 'stalled', '', '']],
        w3: [['run', '第 1 次运行', 2, '1500 / 14400 秒', 'not_judged', '', '缺少事实：第一次放行前还没有可比较的轮次']], w4: [['run', '还没有开始', 0, '0 / 14400 秒', 'not_judged', '', '缺少事实：事项还没有开始运行']] } },
    report: { project: ['项目循环', '内部报表工具', '4 项事项', '累计 3 小时 31 分 / 24 小时', 'converging', '', ''],
      items: { w5: [['run', '第 1 次运行', 2, '2400 / 14400 秒', 'converging', '', ''], ['activation', '工程 · 第 2 轮', 2, '等待模型服务中', 'not_judged', '', '缺少事实：这一轮还没有拿到模型的输出']],
        w6: [['run', '第 1 次运行', 1, '1260 / 14400 秒', 'converging', '', '']], w10: [['run', '第 1 次运行', 2, '3000 / 14400 秒', 'converging', '', '放行已给出，等产品处理完新输入']], w9: [['run', '第 1 次运行', 3, '9000 / 14400 秒', 'done', '质检放行后采纳', '']] } },
    blog: { project: ['项目循环', '个人博客', '2 项事项', '累计 1 小时 2 分 / 8 小时', 'converging', '', ''],
      items: { w7: [['run', '第 1 次运行', 2, '3300 / 7200 秒', 'done', '开环完成，没有核验角色', '']], w8: [['run', '第 1 次运行', 1, '420 / 7200 秒', 'converging', '', '']] } }
  };

  // ---------------------------------------------------------------- 项目设置
  X.settings = {
    orders: { pinned: true, source: [{ name: 'orders-web', path: 'D:\\work\\orders-web', writeback: { remote: 'origin', branch: 'main' }, checks: ['npm test'] }],
      writeback: { enabled: true, source: 'orders-web', branch: 'main', records: [{ adoption: '订单状态机 · 第 2 版', status: 'completed', text: '写回完成', at: at('y', '22:20'), detail: '推送分支 yudao/order-state → 目标分支 main', mr: '订单状态机：集中状态转换（还只是本地记录）' }] },
      place: { workspace: 'local', checks: { product: '', engineering: '', quality: 'desk-01' } } },
    report: { pinned: false, source: [{ name: 'report-service', path: 'D:\\work\\report-service', writeback: null, checks: [] }],
      writeback: { enabled: false, records: [] }, place: { workspace: 'test-01', checks: { product: '', engineering: 'test-01', quality: '' } } },
    blog: { pinned: false, source: [], writeback: { enabled: false, records: [] }, place: { workspace: 'local', checks: { product: '', engineering: '', quality: '' } } }
  };
  X.deptRoles = { product: ['产品经理'], engineering: ['工程师', '探索者'], quality: ['质检员'], solo: ['通才'] };
  X.deptPrompt = { product: '配置 第 2 版', engineering: '内置默认', quality: '配置 第 1 版', solo: '内置默认' };

  // ---------------------------------------------------------------- 恢复与动作核实：按事项
  // 没有写到的事项按"没有中断"处理
  X.unknownActions = {
    w6: [{ id: '动作-9021', label: '把报表服务部署到测试机 test-01', handling: 'waiting', handlingText: '等待机器恢复后核实', dept: 'engineering', machine: 'test-01', session: '工程 · 第 1 轮', input: '部署包 report-svc-0.3.1.tgz', before: '机器上运行的版本是 0.3.0', after: '还不知道', basis: '到 test-01 的连接在 120 秒后超时，没有收到回执', at: at('t', '14:11') }],
    w1: [{ id: '动作-8812', label: '写入 orders/export-csv.ts', handling: 'confirmed', handlingText: '核实确认', dept: 'engineering', session: '工程 · 第 3 轮', input: '文件内容 1.2 KB', before: '文件不存在', after: '文件存在，摘要与要写的内容一致', result: '写入已完成', at: at('t', '14:17') }],
    w2: [{ id: '动作-8830', label: '运行试用用例：翻页后切换每页条数', handling: 'returned', handlingText: '已交还会话', dept: 'quality', session: '质检 · 第 4 轮', input: '试用用例 pager-switch', before: '页面在第 9 页', after: '不知道', returned: '这个动作被中断，结果未知。已经收到的输出：\n打开列表页 → 翻到最后一页 → 切换每页条数 → （输出中断）\n请检查页面现在的状态，再决定要不要重新运行。', at: at('t', '14:17') }]
  };
  X.sessionsOf = (item) => [
    { label: '工程 · 主线', note: '部门主线', sec: Math.round(item.used * 0.55), acts: Math.max(item.round - 1, 1), steps: 24 + item.round * 6 },
    { label: '质检 · 主线', note: '部门主线', sec: Math.round(item.used * 0.3), acts: Math.max(item.round - 2, 0), steps: 10 + item.round * 3 },
    { label: '工程 · 询问分支', note: '询问分支，用量计入提问方', sec: Math.round(item.used * 0.05), acts: 1, steps: 6 }
  ];
})();
