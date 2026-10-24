// 北京地铁票价（评测场景 3，PRDBench 44）。种子是出现时的状态，历史补丁收到现在。
(function () {
  'use strict';
  const Y13 = window.Y13;
  const P = 'p-metro';

  function modelOf(definition, source, unusable) {
    const connection = definition.split('/')[0];
    return {
      definition: definition,
      connection: connection,
      protocol: 'Responses',
      source: source,
      level: definition.indexOf('kimi') >= 0 ? 'high' : null,
      sent_level: definition.indexOf('kimi') >= 0 ? 'high' : 'medium',
      unusable: unusable || null
    };
  }

  function attempt(fields) {
    return Object.assign({
      n: 1, of: 1, status: 'succeeded', duration_ms: 28000,
      provider: 'opencode-go-responses', error: null, semantic_units: [],
      usage: { input: 8000, output: 1600, cache_read: 0, total: 9600, cost: null }
    }, fields);
  }

  function target(model, source) {
    return {
      connection: 'opencode-go-responses', protocol: 'Responses',
      base_url: 'https://opencode.ai/zen/go/v1', model: model, window: 262144, max_output: 32768,
      credential_ref: 'OPENCODE_GO_KEY', source: source, request_level: 'high', sent_level: 'high', prompt_version: 1
    };
  }

  function roles(active) {
    const row = (id, name, kind, task) => ({
      id: id, name: name, kind: kind,
      status: active && active.id === id ? active.status : 'idle',
      model: 'opencode-go-responses/kimi-k2.6',
      task: active && active.id === id ? active.task : null
    });
    return {
      level: 'S5',
      product: [
        row('prod-manager', '产品部门经理', 'manager'),
        row('prod-architect', '产品架构师', 'architect'),
        row('prod-explorer', '产品探索者', 'explorer'),
        row('prod-reviewer', '产品审查者', 'reviewer')
      ],
      engineering: [
        row('eng-manager', '工程经理', 'manager'),
        row('eng-architect', '工程架构师', 'architect'),
        row('eng-lead', '主程', 'lead'),
        row('eng-explorer', '工程探索者', 'explorer'),
        row('eng-reviewer', '工程审查者', 'reviewer')
      ],
      quality: [
        row('qa-manager', '质检经理', 'manager'),
        row('qa-tester', '测试工程师', 'tester'),
        row('qa-explorer', '质检探索者', 'explorer'),
        row('qa-reviewer', '质检审查者', 'reviewer')
      ]
    };
  }

  function blank() {
    return { items: [], facts: [], questions: [], progress: [] };
  }

  function ledger(entries) {
    const out = { level: 'S5', product: blank(), engineering: blank(), quality: blank() };
    Object.keys(entries).forEach((department) => { out[department] = entries[department]; });
    return out;
  }

  // ---------------------------------------------------------------------------
  // 原型 v13 的两个播放场景（场景 24、25）：换乘站的事项在工程手里，质检同时做预测性探索

  const W = 'w-metro-transfer', RUN = 'r-metro-transfer';
  const BURST_SETUP = [
    { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
    { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: null },
    { path: 'runs[id=r-metro-transfer].recovery.reason', value: '运行中' },
    { path: 'runs[id=r-metro-transfer].department', value: 'engineering' },
    { path: 'runs[id=r-metro-transfer].cycle', value: 1 },
    { path: 'runs[id=r-metro-transfer].departments', value: { quality: { state: 'working', note: '预测性探索：按 PRD r2 起草测试用例' } } },
    { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' }
  ];
  // 一条事件与它的补丁（extra.patch）；extra 的其余字段写进事件；at 不写时是示例时间的「现在」
  const happen = (type, department, role, label, payload, extra) => {
    const x = Object.assign({}, extra || {});
    const patch = x.patch || [];
    delete x.patch;
    return { event: Object.assign({ type, project_id: P, work_item_id: W, run_id: RUN, department, role: role || null, label, payload: payload || {} }, x), patch };
  };
  const tool = (department, role, name, label, payload) => happen('tool_started', department, role, label, Object.assign({ tool: name }, payload || {}), { tool: name });
  const ran = (department, role, command, code) => happen('tool_called', department, role, '命令 ' + command + (code === 0 ? ' 通过' : ' 没有通过'), { tool: 'bash', command, exit_code: code, timed_out: false }, { tool: 'bash' });
  const think = (department, role, what) => happen('model_requested', department, role, what, {});
  const ask = (id, from, to, question) => happen('ask_started', from, null, (from === 'quality' ? '质检' : '工程') + '询问' + (to === 'engineering' ? '工程' : '产品') + '：' + question,
    { ask_id: id, requester: from, recipient: to, question },
    { patch: [{ path: 'runs[id=r-metro-transfer].asks', push: { id, requester: from, recipient: to, parent: null, question, status: 'open', answer: null, reason: null, prd_version: null, born_at: '2026-09-29T15:30:00+08:00', answered_at: null } }] });
  const answer = (id, from, to, text) => happen('ask_answered', to, null, (to === 'engineering' ? '工程' : '产品') + '回答：' + text,
    { ask_id: id, requester: from, recipient: to, result: 'answered', answer: text },
    { patch: [{ path: 'runs[id=r-metro-transfer].asks[id=' + id + '].status', value: 'answered' }, { path: 'runs[id=r-metro-transfer].asks[id=' + id + '].answer', value: text }, { path: 'runs[id=r-metro-transfer].asks[id=' + id + '].answered_at', value: '2026-09-29T15:30:00+08:00' }] });
  const deliver = (version) => happen('delivery_accepted', 'engineering', 'eng-manager', '交付 ' + version + ' 被接纳：换乘站去重与最短路径，质检关注的交付有了新版本', { version },
    { patch: [{ path: 'runs[id=r-metro-transfer].department', value: 'quality' }, { path: 'runs[id=r-metro-transfer].last_department', value: 'engineering' }] });

  const BURST_FIRST = [
    think('engineering', 'eng-architect', '工程架构师整理换乘站去重的思路'),
    tool('engineering', 'eng-explorer', 'read_file', '工程探索者阅读 subway_data.json', { path: 'subway_data.json' }),
    tool('engineering', 'eng-lead', 'edit_range', '主程按区间编辑 pathfinding.py：换乘站按站名合并', { path: 'pathfinding.py' }),
    happen('model_stream_progress', 'engineering', 'eng-architect', '输出片段', { text: '换乘站按站名合并，一条路径里只计一次换乘……' }),
    tool('engineering', 'eng-lead', 'bash', '主程执行命令 python -m pytest tests/test_transfer.py', { command: 'python -m pytest tests/test_transfer.py' }),
    ran('engineering', 'eng-lead', 'python -m pytest tests/test_transfer.py', 1),
    tool('quality', 'qa-tester', 'read_file', '测试工程师阅读 PRD r2 的验收条件', { path: 'PRD.md' }),
    think('quality', 'qa-tester', '测试工程师起草换乘站的测试用例'),
    happen('context_assembled', 'product', 'prod-architect', '产品架构师整理询问用到的资料', {}),
    happen('x_role_task_assigned', 'engineering', 'eng-reviewer', '工程经理把审查交给工程审查者', { to: 'eng-reviewer', task: '审查换乘站去重' }),
    tool('engineering', 'eng-lead', 'edit_range', '主程按区间编辑 transfer.py：修正同站多线', { path: 'transfer.py' }),
    tool('engineering', 'eng-explorer', 'read_range', '工程探索者阅读 pathfinding.py 的权重函数', { path: 'pathfinding.py' }),
    tool('quality', 'qa-tester', 'edit_range', '测试工程师编辑 tests/test_transfer_cases.py', { path: 'tests/test_transfer_cases.py' }),
    ask('q-burst-xzm', 'quality', 'engineering', '西直门同时在 2 号线与 4 号线，一条路径是否只计一次换乘？'),
    tool('engineering', 'eng-lead', 'bash', '主程执行命令 python -m pytest tests/test_transfer.py', { command: 'python -m pytest tests/test_transfer.py' }),
    ran('engineering', 'eng-lead', 'python -m pytest tests/test_transfer.py', 0),
    think('engineering', 'eng-architect', '工程架构师核对最短路径的结果'),
    answer('q-burst-xzm', 'quality', 'engineering', '按站名合并，西直门在一条路径里只计一次换乘。'),
    happen('x_role_result_returned', 'engineering', 'eng-reviewer', '工程审查者把审查结果交回经理', { to: 'eng-manager' }),
    happen('x_review_recorded', 'engineering', 'eng-reviewer', '工程审查者审查通过', { verdict: 'passed' }),
    tool('engineering', 'eng-lead', 'edit_range', '主程按区间编辑 README.md：写明换乘的计法', { path: 'README.md' }),
    think('product', 'prod-architect', '产品架构师核对 PRD r2 的说法'),
    tool('quality', 'qa-tester', 'edit_range', '测试工程师补一条最大换乘数的用例', { path: 'tests/test_transfer_cases.py' }),
    happen('proposal_submitted', 'engineering', 'eng-manager', '工程经理代表部门提交交付说明', { kind: 'delivery_spec' }),
    deliver('r1'),
    happen('department_activated', 'quality', null, '质检开始检查交付 r1', {}),
    tool('quality', 'qa-tester', 'run_check', '测试工程师运行检查 python -m pytest tests', { command: 'python -m pytest tests' }),
    think('quality', 'qa-tester', '测试工程师比对检查结果与验收条件'),
    tool('quality', 'qa-explorer', 'read_file', '质检探索者阅读交付说明', { path: 'DELIVERY.md' }),
    tool('quality', 'qa-tester', 'run_check', '测试工程师运行检查 python -m pytest tests/test_transfer_cases.py', { command: 'python -m pytest tests/test_transfer_cases.py' })
  ];

  const BURST_SECOND = [
    think('quality', 'qa-tester', '测试工程师写缺陷记录'),
    tool('quality', 'qa-tester', 'run_check', '测试工程师复核最大换乘数为 0 的路径', {}),
    happen('qa_submitted', 'quality', 'qa-manager', '质检记下缺陷记录：最大换乘数为 0 时仍然返回换乘路径（D-1）', { verdict: 'rework_engineering' },
      { patch: [{ path: 'runs[id=r-metro-transfer].department', value: 'engineering' }, { path: 'runs[id=r-metro-transfer].last_department', value: 'quality' }, { path: 'runs[id=r-metro-transfer].cycle', value: 2 }] }),
    happen('department_activated', 'engineering', null, '工程开始修复 D-1', {}),
    think('engineering', 'eng-architect', '工程架构师分析 D-1'),
    tool('engineering', 'eng-lead', 'edit_range', '主程按区间编辑 pathfinding.py：最大换乘数为 0 时只走同一条线', { path: 'pathfinding.py' }),
    tool('engineering', 'eng-lead', 'bash', '主程执行命令 python -m pytest tests', { command: 'python -m pytest tests' }),
    ran('engineering', 'eng-lead', 'python -m pytest tests', 0),
    tool('engineering', 'eng-lead', 'edit_range', '主程按区间编辑 transfer.py', { path: 'transfer.py' }),
    think('engineering', 'eng-architect', '工程架构师写交付说明'),
    happen('proposal_submitted', 'engineering', 'eng-manager', '工程经理代表部门提交交付说明', { kind: 'delivery_spec' }),
    deliver('r2'),
    happen('department_activated', 'quality', null, '质检检查交付 r2', {}),
    tool('quality', 'qa-tester', 'run_check', '测试工程师运行检查 python -m pytest tests', { command: 'python -m pytest tests' }),
    happen('qa_submitted', 'quality', 'qa-manager', '质检放行：验收条件全部通过', { verdict: 'release' },
      { patch: [{ path: 'work_items[id=w-metro-transfer].status', value: 'released' }, { path: 'runs[id=r-metro-transfer].phase', value: 'DONE' }] })
  ];

  // 标签页在后台的几分钟里到达的事件：时间相隔二三十秒
  const at = (min, sec) => '2026-09-29T15:' + String(31 + min).padStart(2, '0') + ':' + String(sec).padStart(2, '0') + '+08:00';
  const stamp = (step, t) => Object.assign({}, step, { event: Object.assign({}, step.event, { at: t }) });
  const AWAY_EVENTS = [
    stamp(tool('engineering', 'eng-lead', 'edit_range', '主程按区间编辑 pathfinding.py', { path: 'pathfinding.py' }), at(0, 10)),
    stamp(tool('engineering', 'eng-lead', 'bash', '主程执行命令 python -m pytest tests', { command: 'python -m pytest tests' }), at(0, 40)),
    stamp(ran('engineering', 'eng-lead', 'python -m pytest tests', 0), at(1, 5)),
    stamp(ask('q-away-max', 'quality', 'engineering', '用户不填最大换乘数时，默认不限制还是默认 3 次？'), at(1, 30)),
    stamp(answer('q-away-max', 'quality', 'engineering', '默认不限制，界面上写明「不限」。'), at(2, 0)),
    stamp(happen('proposal_submitted', 'engineering', 'eng-manager', '工程经理代表部门提交交付说明', { kind: 'delivery_spec' }), at(2, 30)),
    stamp(deliver('r1'), at(2, 50)),
    stamp(happen('department_activated', 'quality', null, '质检开始检查交付 r1', {}), at(3, 10)),
    stamp(tool('quality', 'qa-tester', 'run_check', '测试工程师运行检查 python -m pytest tests', { command: 'python -m pytest tests' }), at(3, 40)),
    stamp(happen('qa_submitted', 'quality', 'qa-manager', '质检记下缺陷记录：最大换乘数为 0 时仍然返回换乘路径（D-1）', { verdict: 'rework_engineering' },
      { patch: [{ path: 'runs[id=r-metro-transfer].department', value: 'engineering' }, { path: 'runs[id=r-metro-transfer].last_department', value: 'quality' }, { path: 'runs[id=r-metro-transfer].cycle', value: 2 }] }), at(4, 20)),
    stamp(happen('department_activated', 'engineering', null, '工程开始修复 D-1', {}), at(4, 40)),
    stamp(tool('engineering', 'eng-lead', 'edit_range', '主程按区间编辑 pathfinding.py：最大换乘数为 0 时只走同一条线', { path: 'pathfinding.py' }), at(5, 10)),
    stamp(tool('engineering', 'eng-lead', 'bash', '主程执行命令 python -m pytest tests', { command: 'python -m pytest tests' }), at(5, 40)),
    stamp(ran('engineering', 'eng-lead', 'python -m pytest tests', 0), at(6, 5)),
    stamp(think('engineering', 'eng-architect', '工程架构师写交付说明'), at(6, 30))
  ];

  function ev(fields) {
    return Object.assign({
      project_id: P, work_item_id: null, run_id: null, department: null, role: null,
      actor: 'system', payload: {}, patch: []
    }, fields);
  }

  // 质检的逐条结论（3.2D 起出现在资料里）：[验收条件, 说明, 检验方式, 检查]；results 按验收条件给出 [结果, 说明]，没有写的为通过
  function criteriaOf(list, results) {
    return list.map(([criterion, text, method, checks]) => {
      const r = results[criterion] || ['pass', null];
      return { criterion, text, method, result: r[0], checks, trial_cases: [], note: r[1] };
    });
  }

  const FARE_AC = [
    ['AC-1', '分段票价：6000 米 3 元，12000 米 4 元，12001 米 5 元', 'command_check', ['pytest：tests/test_fare.py']],
    ['AC-2', '行程时间：每公里 2 分钟，每次换乘另加 5 分钟', 'command_check', ['pytest：tests/test_time.py']],
    ['AC-3', '命令行连续查询两次后退出码 0', 'command_check', ['fare_cli：连续查询']],
    ['AC-4', 'JSON 字段名与接口约定一致', 'command_check', ['pytest：tests/test_export.py']],
    ['AC-5', '数据文件缺少终点站时完整性检查拒绝加载', 'command_check', ['pytest：tests/test_loader.py']]
  ];

  // 「夜间票价」（自举试点的示例数据，design.md 第 8.1 节）：AC-2 的结论通过、不通过、通过、不通过（run 层震荡），
  // run 用完运行时间（7200/7200 秒）停止（达到边界）；最后一次工程激活里同名同参数的工具调用重复 3 次（步骤循环震荡）
  const NIGHT_AC = [
    ['AC-1', '23:00 至次日 5:00 进站的行程按夜间票价计算', 'command_check', ['pytest：tests/test_night_fare.py::test_window']],
    ['AC-2', '夜间票价在分段票价上加 1 元；跨过 5:00 出站的行程仍按进站时间判定', 'command_check', ['pytest：tests/test_night_fare.py::test_cross_dawn']],
    ['AC-3', '夜间行程在文本与 JSON 导出中标出「夜间」', 'command_check', ['pytest：tests/test_export.py::test_night_flag']],
    ['AC-4', '22:59 与 23:00 两个边界时刻各有一条断言', 'command_check', ['pytest：tests/test_night_fare.py::test_edges']]
  ];
  const NIGHT = { work_item_id: 'w-metro-night', run_id: 'r-metro-night', level: 'pilot' };
  const night = (fields) => ev(Object.assign({}, NIGHT, fields));
  const nightRun = (field, value) => ({ path: 'runs[id=r-metro-night].' + field, value });
  // 一轮：工程的交付被接纳（质检关注的交付到达），质检开始一轮工作并提交缺陷记录，工程关注的缺陷记录到达，开始下一轮
  const nightRound = (n, times, snapshot, elapsed, label) => [
    night({
      at: '2026-09-28T' + times[0] + ':00+08:00', type: 'delivery_accepted', department: 'engineering',
      label: '工程的交付 r' + n + ' 被接纳，质检关注的交付到达（夜间票价）', payload: { snapshot },
      patch: [nightRun('elapsed_sec', elapsed[0]), nightRun('department', 'quality'), nightRun('last_department', 'engineering')]
    }),
    night({ at: '2026-09-28T' + times[1] + ':00+08:00', type: 'department_activated', department: 'quality', label: '质检部门开始核验交付 r' + n }),
    night({
      at: '2026-09-28T' + times[2] + ':00+08:00', type: 'qa_submitted', department: 'quality', label,
      payload: { verdict: 'rework_engineering', material_id: 'm-metro-night-q' + n },
      patch: [nightRun('cycle', n + 1), nightRun('elapsed_sec', elapsed[1]), nightRun('department', 'engineering'), nightRun('last_department', 'quality')]
    }),
    night({ at: '2026-09-28T' + times[3] + ':00+08:00', type: 'department_activated', department: 'engineering', label: '工程部门关注的缺陷记录到达，开始第 ' + (n + 1) + ' 轮' })
  ];
  const nightStep = (time, tool, target, label, extra) => night({
    at: '2026-09-28T' + time + ':00+08:00', type: 'tool_started', department: 'engineering', label,
    payload: Object.assign({ tool }, tool === 'bash' ? { command: target } : { path: target, plan_item: 'P-2' }), patch: extra || []
  });
  const nightQa = (n, snapshot, results, text) => ({
    id: 'm-metro-night-q' + n, project_id: P, work_item_id: 'w-metro-night', kind: 'qa', version: n, level: 'pilot',
    title: '质检结论 r' + n + '（夜间票价）', at: '2026-09-28T12:00:00+08:00', verdict: 'rework_engineering',
    text, snapshot, criteria: criteriaOf(NIGHT_AC, results)
  });

  const fareAsk = '12 公里整是否按 6 元？分段表里 12 公里是 4 元档的上界，还是已经进入 6 元档？';
  const fareAnswer = '12 公里整按 4 元。分段按左开右闭：6 公里及以内 3 元，超过 6 公里至 12 公里（含）4 元，超过 12 公里至 22 公里 5 元，超过 22 公里至 32 公里 6 元。12 公里整不进入 6 元档。Sum_money 的输入单位是米，12000 米对应 4 元。';

  Y13.data.define({
    seed: {
      projects: [{
        id: P, name: '北京地铁票价',
        goal: '按 PRDBench 44 实现北京地铁票价：三种路径、最大换乘数、线路偏好、分段票价、行程时间、命令行连续查询、文本与 JSON 导出、数据完整性检查。',
        pinned: false, archived: false, version: 1, source: 'idea',
        created_at: '2026-09-26T18:00:00+08:00',
        last_activity_at: '2026-09-26T18:00:00+08:00',
        born_at: '2026-09-26T18:00:00+08:00',
        adoptions: []
      }],
      work_items: [
        {
          id: 'w-metro-fare', project_id: P, title: '按里程计算票价', color_index: 0, kind: 'request',
          status: 'not_started', queue_reason: null, queue_pos: null, run_id: 'r-metro-fare', version: 1,
          created_at: '2026-09-26T18:10:00+08:00', born_at: '2026-09-26T18:10:00+08:00'
        },
        {
          id: 'w-metro-transfer', project_id: P, title: '换乘站与最短路径', color_index: 1, kind: 'request',
          status: 'not_started', queue_reason: null, queue_pos: null, run_id: 'r-metro-transfer', version: 1,
          created_at: '2026-09-28T13:00:00+08:00', born_at: '2026-09-28T13:00:00+08:00'
        },
        {
          id: 'w-metro-card', project_id: P, title: '公交卡折扣', color_index: 2, kind: 'request',
          status: 'queued', queue_reason: 'project', queue_pos: 1, run_id: 'r-metro-card', version: 1,
          created_at: '2026-09-28T15:40:00+08:00', born_at: '2026-09-28T15:40:00+08:00', level: '3.4A'
        },
        {
          id: 'w-metro-report', project_id: P, title: '导出月度出行统计', color_index: 3, kind: 'request',
          status: 'queued', queue_reason: 'project', queue_pos: 2, run_id: 'r-metro-report', version: 1,
          created_at: '2026-09-28T16:10:00+08:00', born_at: '2026-09-28T16:10:00+08:00', level: '3.4A'
        },
        {
          id: 'w-metro-night', project_id: P, title: '夜间票价', color_index: 4, kind: 'request',
          status: 'not_started', queue_reason: null, queue_pos: null, run_id: 'r-metro-night', version: 1,
          created_at: '2026-09-28T10:58:00+08:00', born_at: '2026-09-28T10:58:00+08:00', level: 'pilot'
        }
      ],
      runs: [
        {
          id: 'r-metro-fare', work_item_id: 'w-metro-fare', project_id: P, yudao_version: '0.8.0',
          phase: 'PRODUCT_SPEC', department: null, last_department: null, cycle: 0,
          started_at: '2026-09-26T18:10:00+08:00', elapsed_sec: 0, limit_sec: 7200,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: {
            state: 'running', reason: '运行中', unusable: null,
            last_confirmed: { seq: 12, text: '质检已放行按里程计算票价' },
            owner: { id: '质检部门', since: '2026-09-28T10:52:00+08:00' },
            late_results: [], verifications: [], unfinished: [],
            limits: { elapsed_sec: 5400, limit_sec: 7200, activations: 4, model_steps: 9, retries: 0 },
            auto_resumed_at: null
          },
          born_at: '2026-09-26T18:10:00+08:00',
          inputs: [{
            version: 1, kind: 'user', progress: 'accepted', at: '2026-09-26T18:10:00+08:00', bytes: 860,
            text: '按 PRDBench 44 做北京地铁票价。先完成分段票价、行程时间和命令行查询，换乘路径放到下一个事项。'
          }],
          flow: [
            { seq: 1, at: '2026-09-26T18:36:00+08:00', from: 'product', to: 'engineering', kind: 'prd', content: 'PRD r1：分段票价与 12 公里整按 4 元', status: 'accepted', event_position: null },
            { seq: 2, at: '2026-09-28T10:51:00+08:00', from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r1：fare_calculator、cli、文本与 JSON 导出', status: 'accepted', event_position: null },
            { seq: 3, at: '2026-09-28T11:21:00+08:00', from: 'quality', to: 'library', kind: 'release', content: '放行：12000 米票价为 4 元', status: 'accepted', event_position: null }
          ],
          asks: [{
            id: 'q-fare-12km', requester: 'engineering', recipient: 'product', parent: null,
            question: fareAsk, status: 'open', answer: null, reason: null,
            born_at: '2026-09-26T19:05:00+08:00', answered_at: null
          }],
          guidance: [],
          messages: {
            product: [{ seq: 1, at: '2026-09-26T19:22:00+08:00', source: 'self', from: 'product', text: fareAnswer, event_id: null }],
            engineering: [{ seq: 1, at: '2026-09-26T19:05:00+08:00', source: 'self', from: 'engineering', text: fareAsk, event_id: null }],
            quality: [{ seq: 1, at: '2026-09-28T11:20:00+08:00', source: 'self', from: 'quality', text: '12000 米断言通过，放行。', event_id: null }],
            operations: []
          },
          actions: [{
            id: 'a-metro-fare-pytest', department: 'engineering', role: 'eng-lead', tool: 'bash',
            summary: '执行命令 python -m pytest tests/test_fare.py：边界 12000 米', input: '分段票价的边界自测',
            state: 'done', machine_id: 'm-host', at: '2026-09-28T10:40:00+08:00',
            before: '测试文件已写入 12000 米期望 4 元', after: '1 passed',
            receipt: { command: 'python -m pytest tests/test_fare.py', exit_code: 0, output: '1 passed', truncated: false, timed_out: false, duration_ms: 2400, snapshot: 'tests/test_fare.py' }
          }],
          contexts: {
            product: [{ id: 'ctx-fare-p1', at: '2026-09-26T18:16:00+08:00', title: '产品激活 1', attempt_id: 'att-fare-p1', sources: [{ label: '用户原文', version: 'v1', included: true }] }],
            engineering: [{ id: 'ctx-fare-e2', at: '2026-09-27T16:41:00+08:00', title: '工程激活 2（压缩后）', attempt_id: 'att-fare-e2', sources: [{ label: '部门历史', version: '摘要 1', included: true }, { label: '当前合同', version: 'PRD r1', included: true }] }],
            quality: [{ id: 'ctx-fare-q1', at: '2026-09-28T10:53:00+08:00', title: '质检激活 1', attempt_id: 'att-fare-q1', sources: [{ label: '交付', version: 'r1', included: true }, { label: '当前合同', version: 'PRD r1', included: true }] }]
          },
          prompts: {
            product: { config_version: 1, request_version: 1, text: '依据用户原文写清分段票价的边界，12 公里整必须有明确归属。' },
            engineering: { config_version: 1, request_version: 2, text: 'Sum_money 输入单位为米。先写边界测试，再实现 fare_calculator。' },
            quality: { config_version: 1, request_version: 1, text: '对照 PRD 检查 12000 米是否为 4 元，并核对导出字段名。' }
          },
          compactions: [{ department: 'engineering', n: 1, at: '2026-09-27T16:40:00+08:00', coverage: 'seq 8–46', event_id: null }],
          effective_model: {
            product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            quality: modelOf('opencode-go-responses/mimo-v2.5', '部门默认', null)
          },
          roles: roles(null),
          ledger: ledger({
            engineering: {
              items: [
                { id: 'P-1', text: 'Sum_money 按分段表实现，边界 6000 与 12000 米', assignee: 'eng-lead', status: 'returned', result: '3 处边界断言通过' },
                { id: 'P-2', text: '命令行连续查询与文本、JSON 导出', assignee: 'eng-lead', status: 'returned', result: '两次查询后退出码 0' }
              ],
              facts: ['12 公里整按 4 元，不进入 6 元档'],
              questions: [],
              progress: [{ cycle: 1, text: '三轮内交付，边界断言通过', stalled: false }]
            }
          }),
          attempts: [
            attempt({ id: 'att-fare-p1', logical_call_id: 'call-fare-p1', department: 'product', role: 'prod-architect', started_at: '2026-09-26T18:16:00+08:00', requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 4200, output: 1800, cache_read: 0, total: 6000, cost: null } }),
            attempt({ id: 'att-fare-e2', logical_call_id: 'call-fare-e2', department: 'engineering', role: 'eng-lead', started_at: '2026-09-27T16:32:00+08:00', duration_ms: 42100, requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 18420, output: 2360, cache_read: 0, total: 20780, cost: null } }),
            attempt({ id: 'att-fare-q1', logical_call_id: 'call-fare-q1', department: 'quality', role: 'qa-tester', started_at: '2026-09-28T11:05:00+08:00', requested_model: 'mimo-v2.5', actual_model: 'mimo-v2.5', target: target('mimo-v2.5', '部门默认'), usage: { input: 9600, output: 1100, cache_read: 0, total: 10700, cost: null } })
          ],
          source: null
        },
        {
          id: 'r-metro-transfer', work_item_id: 'w-metro-transfer', project_id: P, yudao_version: '0.8.0',
          phase: 'PRODUCT_SPEC', department: null, last_department: null, cycle: 0,
          started_at: '2026-09-28T13:00:00+08:00', elapsed_sec: 0, limit_sec: 7200,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: {
            state: 'running', reason: '运行中', unusable: null,
            last_confirmed: { seq: 17, text: '工程已写完换乘站去重与最短路径，命令 python -m pytest tests 已开始、尚未收到退出码' },
            owner: { id: '工程部门', since: '2026-09-29T03:02:00+08:00' },
            late_results: [], verifications: [], unfinished: [], waiting_machine: null,
            limits: { elapsed_sec: 4980, limit_sec: 7200, activations: 6, model_steps: 11, retries: 1 },
            auto_resumed_at: null
          },
          // 会话的用量各自累计（三部门的循环结构第 9 节）：质检在 PRD 被接纳以后做过一轮预测性探索
          sessions: [
            { id: 's-xfer-product', department: 'product', kind: 'main', label: '产品：写三种路径与换乘限制的 PRD', elapsed_sec: 720, activations: 1, model_steps: 3 },
            { id: 's-xfer-engineering', department: 'engineering', kind: 'main', label: '工程：换乘站去重与最短路径', elapsed_sec: 3780, activations: 4, model_steps: 6 },
            { id: 's-xfer-quality', department: 'quality', kind: 'main', label: '质检：预测性探索，按 PRD r1 起草测试用例', elapsed_sec: 480, activations: 1, model_steps: 2 }
          ],
          born_at: '2026-09-28T13:00:00+08:00',
          inputs: [{
            version: 1, kind: 'user', progress: 'accepted', at: '2026-09-28T13:00:00+08:00', bytes: 640,
            text: '接着做换乘站与最短路径：三种路径模式、最大换乘数、线路偏好。换乘站在一条路径里只计一次。'
          }],
          flow: [
            { seq: 1, at: '2026-09-28T13:40:00+08:00', from: 'product', to: 'engineering', kind: 'prd', content: 'PRD r1：三种路径、最大换乘数、线路偏好、换乘站只计一次', status: 'accepted', event_position: null },
            { seq: 2, at: '2026-09-28T13:40:00+08:00', from: 'product', to: 'quality', kind: 'prd', content: 'PRD r1 被接纳：质检开始预测性探索', status: 'accepted', event_position: null }
          ],
          asks: [],
          // 写明了的部门状态（例如预测性探索）；没写的由事实推出
          departments: null,
          guidance: [],
          messages: {
            product: [],
            engineering: [{ seq: 1, at: '2026-09-29T03:02:00+08:00', source: 'self', from: 'engineering', text: '开始执行命令 python -m pytest tests。', event_id: null }],
            quality: [],
            operations: []
          },
          actions: [
            {
              id: 'a-metro-read-graph', department: 'engineering', role: 'eng-explorer', tool: 'read_file',
              summary: '阅读 subway_data.json 的换乘站', input: 'subway_data.json',
              state: 'done', machine_id: 'm-host', at: '2026-09-28T15:10:00+08:00',
              before: '文件未读', after: '换乘站按站名出现在多条线路',
              receipt: { target: 'subway_data.json', output: 'stations 328', truncated: false, timed_out: false, duration_ms: 180, snapshot: null }
            },
            {
              id: 'a-metro-unit-17', department: 'engineering', role: 'eng-lead', tool: 'bash',
              summary: '执行命令 python -m pytest tests', input: '换乘站去重与最短路径的自测',
              state: 'running', machine_id: null, at: '2026-09-29T03:02:00+08:00',
              before: '工作区 src/pathfinding.py 已写入换乘站去重，测试尚未开始', after: null,
              receipt: null
            }
          ],
          contexts: {
            product: [{ id: 'ctx-xfer-p1', at: '2026-09-28T13:06:00+08:00', title: '产品激活 1', attempt_id: 'att-xfer-p1', sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '已采纳', version: 'r1', included: true }] }],
            engineering: [{ id: 'ctx-xfer-e2', at: '2026-09-28T14:32:00+08:00', title: '工程激活 2', attempt_id: 'att-xfer-e1', sources: [{ label: '当前合同', version: 'PRD r1', included: true }] }],
            quality: []
          },
          prompts: {
            product: { config_version: 1, request_version: 1, text: '三种路径模式、最大换乘数、线路偏好写进 PRD。换乘站只计一次。' },
            engineering: { config_version: 1, request_version: 1, text: '实现 pathfinding 的三种路径与换乘站去重，运行 python -m pytest tests 自测。' },
            quality: { config_version: 1, request_version: 1, text: '交付到达之前按 PRD r1 起草换乘与路径的测试用例。' }
          },
          compactions: [],
          effective_model: {
            product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            quality: modelOf('opencode-go-responses/mimo-v2.5', '部门默认', null)
          },
          roles: roles({ id: 'eng-lead', status: 'working', task: '命令 python -m pytest tests 的结果尚未收回' }),
          ledger: ledger({
            engineering: {
              items: [
                { id: 'P-1', text: '换乘站在路径中只计一次', assignee: 'eng-lead', status: 'returned', result: 'pathfinding.py 已按站名去重' },
                { id: 'P-2', text: '跑通 python -m pytest tests', assignee: 'eng-lead', status: 'working', result: null }
              ],
              facts: ['综合最优的评分公式按距离（米）加换乘次数乘 800'],
              questions: [],
              progress: [{ cycle: 2, text: '实现已写完，自测命令结果未知', stalled: false }]
            }
          }),
          attempts: [
            attempt({ id: 'att-xfer-p1', logical_call_id: 'call-xfer-p1', department: 'product', role: 'prod-architect', started_at: '2026-09-28T13:06:00+08:00', requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 5100, output: 1400, cache_read: 0, total: 6500, cost: null } }),
            attempt({ id: 'att-xfer-e1', logical_call_id: 'call-xfer-e1', department: 'engineering', role: 'eng-lead', started_at: '2026-09-28T14:40:00+08:00', duration_ms: 38600, requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 14220, output: 3100, cache_read: 0, total: 17320, cost: null } }),
            attempt({ id: 'att-xfer-e2', logical_call_id: 'call-xfer-e2', department: 'engineering', role: 'eng-lead', started_at: '2026-09-29T02:50:00+08:00', duration_ms: 22400, requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 9800, output: 900, cache_read: 0, total: 10700, cost: null } })
          ],
          source: null
        },
        {
          id: 'r-metro-card', work_item_id: 'w-metro-card', project_id: P, yudao_version: '0.8.0',
          phase: 'QUEUED', department: null, last_department: null, cycle: 0,
          started_at: null, elapsed_sec: 0, limit_sec: 7200,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: { state: 'running', reason: '排队中', unusable: null, last_confirmed: null, owner: null, late_results: [], verifications: [], unfinished: [], limits: { elapsed_sec: 0, limit_sec: 7200, activations: 0, model_steps: 0, retries: 0 }, auto_resumed_at: null },
          born_at: '2026-09-28T15:40:00+08:00', level: '3.4A',
          inputs: [{ version: 1, kind: 'user', progress: 'received', at: '2026-09-28T15:40:00+08:00', bytes: 180, text: '公交卡折扣：普通卡 9 折，学生卡 5 折，折扣后四舍五入到角。' }],
          flow: [], asks: [], guidance: [],
          messages: { product: [], engineering: [], quality: [], operations: [] },
          actions: [], contexts: { product: [], engineering: [], quality: [] },
          prompts: { product: { config_version: 1, request_version: 1, text: '' }, engineering: { config_version: 1, request_version: 1, text: '' }, quality: { config_version: 1, request_version: 1, text: '' } },
          compactions: [],
          effective_model: { product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null), engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null), quality: modelOf('opencode-go-responses/mimo-v2.5', '部门默认', null) },
          roles: { level: 'S5', product: [], engineering: [], quality: [] },
          ledger: ledger({}),
          attempts: [], source: null
        },
        {
          id: 'r-metro-report', work_item_id: 'w-metro-report', project_id: P, yudao_version: '0.8.0',
          phase: 'QUEUED', department: null, last_department: null, cycle: 0,
          started_at: null, elapsed_sec: 0, limit_sec: 7200,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: { state: 'running', reason: '排队中', unusable: null, last_confirmed: null, owner: null, late_results: [], verifications: [], unfinished: [], limits: { elapsed_sec: 0, limit_sec: 7200, activations: 0, model_steps: 0, retries: 0 }, auto_resumed_at: null },
          born_at: '2026-09-28T16:10:00+08:00', level: '3.4A',
          inputs: [{ version: 1, kind: 'user', progress: 'received', at: '2026-09-28T16:10:00+08:00', bytes: 160, text: '导出月度出行统计：按自然月汇总次数、总里程和总票价，文本与 JSON 各一份。' }],
          flow: [], asks: [], guidance: [],
          messages: { product: [], engineering: [], quality: [], operations: [] },
          actions: [], contexts: { product: [], engineering: [], quality: [] },
          prompts: { product: { config_version: 1, request_version: 1, text: '' }, engineering: { config_version: 1, request_version: 1, text: '' }, quality: { config_version: 1, request_version: 1, text: '' } },
          compactions: [],
          effective_model: { product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null), engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null), quality: modelOf('opencode-go-responses/mimo-v2.5', '部门默认', null) },
          roles: { level: 'S5', product: [], engineering: [], quality: [] },
          ledger: ledger({}),
          attempts: [], source: null
        },
        {
          id: 'r-metro-night', work_item_id: 'w-metro-night', project_id: P, yudao_version: '0.8.0',
          phase: 'PRODUCT_SPEC', department: 'product', last_department: null, cycle: 1,
          started_at: '2026-09-28T10:58:00+08:00', elapsed_sec: 0, limit_sec: 7200,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: { state: 'running', reason: '运行中', unusable: null, last_confirmed: null, owner: null, late_results: [], verifications: [], unfinished: [], limits: { elapsed_sec: 0, limit_sec: 7200, activations: 10, model_steps: 27, retries: 0 }, auto_resumed_at: null },
          born_at: '2026-09-28T10:58:00+08:00', level: 'pilot',
          inputs: [{ version: 1, kind: 'user', progress: 'accepted', at: '2026-09-28T10:58:00+08:00', bytes: 150, text: '夜间票价：23:00 到次日 5:00 进站的行程在分段票价上加 1 元，导出里标出夜间。' }],
          flow: [], asks: [], guidance: [],
          messages: { product: [], engineering: [], quality: [], operations: [] },
          actions: [], contexts: { product: [], engineering: [], quality: [] },
          prompts: { product: { config_version: 1, request_version: 1, text: '' }, engineering: { config_version: 1, request_version: 1, text: '' }, quality: { config_version: 1, request_version: 1, text: '' } },
          compactions: [],
          effective_model: { product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null), engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null), quality: modelOf('opencode-go-responses/mimo-v2.5', '部门默认', null) },
          roles: { level: 'S5', product: [], engineering: [], quality: [] },
          ledger: ledger({}),
          attempts: [], source: null
        }
      ],
      // 三张只在场景中发出的决定请求（场景 22、23），发出之前不显示
      decisions: [
        {
          id: 'd-metro-paused', kind: 'paused_continue', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer',
          status: 'withdrawn', issued_at: '2026-09-29T15:30:00+08:00', version: 1, level: '3.1',
          blocks: { scope: 'run', work_item_id: 'w-metro-transfer', queued_behind: null },
          materials: {
            department: 'engineering', reason_code: 'no_tool_call', reason: '工程部门的模型连续 4 次回复没有调用工具',
            guide: '可以先在项目设置中更换工程部门的模型，从下一次请求起生效。继续以后从暂停的位置开始：已确认的工具结果不重新执行，已用的激活次数、模型步数与运行时间不重新计算，连续不调用工具的计数从零开始。',
            paths: [], links: ['#/p/p-metro/settings']
          },
          view: '#/p/p-metro/w/w-metro-transfer/recovery', answer: null,
          options: [
            {
              id: 'continue', label: '处理以后继续执行', kind: 'primary',
              events: [{
                type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
                label: '用户选择处理以后继续执行，工程从暂停的位置继续', payload: {},
                patch: [
                  { path: 'runs[id=r-metro-transfer].phase', value: 'ENGINEERING' },
                  { path: 'runs[id=r-metro-transfer].stop_reason', value: null },
                  { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
                  { path: 'runs[id=r-metro-transfer].recovery.reason', value: '从暂停的位置继续，连续不调用工具的计数从零开始' },
                  { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' },
                  { path: 'work_items[id=w-metro-transfer].queue_reason', value: null }
                ]
              }]
            },
            {
              id: 'stop', label: '停止事项', kind: 'danger',
              events: [{
                type: 'run_failed', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer',
                label: '用户停止换乘站的事项，停止原因保持暂停时的原因', payload: { reason: 'no_tool_call' },
                patch: [
                  { path: 'work_items[id=w-metro-transfer].status', value: 'stopped' },
                  { path: 'work_items[id=w-metro-transfer].queue_reason', value: null },
                  { path: 'runs[id=r-metro-transfer].phase', value: 'FAILED' },
                  { path: 'runs[id=r-metro-transfer].recovery.state', value: 'stopped' },
                  { path: 'runs[id=r-metro-transfer].recovery.reason', value: '用户在暂停以后停止事项' }
                ]
              }]
            }
          ]
        },
        {
          id: 'd-metro-defs', kind: 'definitions_changed', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer',
          status: 'withdrawn', issued_at: '2026-09-29T15:30:00+08:00', version: 1, level: '3.1',
          blocks: { scope: 'run', work_item_id: 'w-metro-transfer', queued_behind: null },
          materials: {
            recorded_version: 'v14', current_version: 'v15',
            basis: '事项开始时记录了它使用的定义版本 v14；控制主机重新启动以后加载的定义是 v15。中断的 run 自动继续之前先由你决定。'
          },
          view: '#/p/p-metro/w/w-metro-transfer/recovery', answer: null,
          options: [
            {
              id: 'continue_new', label: '按新版本继续', kind: 'primary',
              events: [{
                type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
                label: '用户选择按新版本继续，工程按定义版本 v15 继续', payload: {},
                patch: [
                  { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
                  { path: 'runs[id=r-metro-transfer].recovery.reason', value: '按定义版本 v15 继续' },
                  { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' },
                  { path: 'work_items[id=w-metro-transfer].queue_reason', value: null }
                ]
              }]
            },
            {
              id: 'stop', label: '停止事项', kind: 'danger',
              events: [{
                type: 'run_failed', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer',
                label: '用户停止换乘站的事项', payload: { reason: 'stopped_by_user' },
                patch: [
                  { path: 'work_items[id=w-metro-transfer].status', value: 'stopped' },
                  { path: 'work_items[id=w-metro-transfer].queue_reason', value: null },
                  { path: 'runs[id=r-metro-transfer].phase', value: 'FAILED' },
                  { path: 'runs[id=r-metro-transfer].stop_reason', value: { code: 'stopped_by_user', text: '定义版本不同，用户停止事项' } },
                  { path: 'runs[id=r-metro-transfer].recovery.state', value: 'stopped' },
                  { path: 'runs[id=r-metro-transfer].recovery.reason', value: '定义版本不同，用户停止事项' }
                ]
              }]
            }
          ]
        },
        {
          id: 'd-metro-wait', kind: 'wait_limit', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer',
          status: 'withdrawn', issued_at: '2026-09-29T15:30:00+08:00', version: 1, level: '3.2C',
          blocks: { scope: 'run', work_item_id: 'w-metro-transfer', queued_behind: null },
          materials: {
            wait: '等待机器', target: '笔记本', machine_id: 'm-laptop', since: '2026-09-28T15:30:00+08:00', limit_sec: 86400,
            note: '等待期间不计入运行时间上限。选择继续等待以后重新计时，再次超过上限时再问一次。'
          },
          view: '#/p/p-metro/w/w-metro-transfer/recovery', answer: null,
          options: [
            {
              id: 'keep_waiting', label: '继续等待', kind: 'primary',
              events: [{
                type: 'x_wait_restarted', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer',
                label: '继续等待笔记本，重新计时', payload: { wait: 'machine', machine_id: 'm-laptop' },
                patch: [
                  { path: 'runs[id=r-metro-transfer].recovery.waiting_machine.since', value: '2026-09-29T15:30:00+08:00' },
                  { path: 'runs[id=r-metro-transfer].recovery.reason', value: '继续等待笔记本恢复在线，从 15:30 起重新计时' }
                ]
              }]
            },
            {
              id: 'stop', label: '停止事项', kind: 'danger',
              events: [{
                type: 'run_failed', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer',
                label: '用户停止换乘站的事项', payload: { reason: 'stopped_by_user' },
                patch: [
                  { path: 'work_items[id=w-metro-transfer].status', value: 'stopped' },
                  { path: 'runs[id=r-metro-transfer].phase', value: 'FAILED' },
                  { path: 'runs[id=r-metro-transfer].stop_reason', value: { code: 'stopped_by_user', text: '等待机器超过时长上限，用户停止事项' } },
                  { path: 'runs[id=r-metro-transfer].recovery.state', value: 'stopped' },
                  { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: null },
                  { path: 'runs[id=r-metro-transfer].recovery.reason', value: '等待机器超过时长上限，用户停止事项' }
                ]
              }]
            }
          ]
        }
      ],
      materials: [
        {
          id: 'm-metro-intend', project_id: P, work_item_id: null, kind: 'intend', version: 1,
          title: '立项：北京地铁票价', at: '2026-09-26T18:00:00+08:00',
          text: '从空目录加题目提供的 subway_data.json 开始，按 PRDBench 44 做北京地铁票价计算系统。先做分段票价与命令行，再做换乘路径。'
        },
        {
          id: 'm-metro-prd', project_id: P, work_item_id: 'w-metro-fare', kind: 'prd', version: 1,
          title: 'PRD r1 分段票价', at: '2026-09-26T18:36:00+08:00',
          text: '北京地铁票价计算系统。用户给出起点站与终点站，系统读取 subway_data.json。\n路径三种：最短距离、最少换乘、综合最优。综合分 = 距离（米）+ 换乘次数 × 800，取综合分最小的路径。换乘站在一条路径中只计一次。\n换乘限制：用户可设置最大换乘数，超过的路径不可用。线路偏好：指定优先线路后，该线路上的边权按 0.8 计入综合分，不改变最短距离模式的实际距离。\n票价由 Sum_money 计算，输入单位为米。6 公里及以内 3 元；超过 6 公里至 12 公里（含）4 元；超过 12 公里至 22 公里 5 元；超过 22 公里至 32 公里 6 元；超过 32 公里至 52 公里 7 元；超过 52 公里至 72 公里 8 元；超过 72 公里至 92 公里 9 元；超过 92 公里 10 元。12 公里整为 4 元。\n行程时间：calculate_estimated_time(米, 换乘数)，每公里 2 分钟，每次换乘另加 5 分钟。\n程序入口 src/cli.py，支持连续查询、文本导出与 JSON 导出。启动时检查站点唯一、边的两端站点存在、距离为正。\n模块：models、data_loader、pathfinding、fare_calculator。类型：Edge、Graph、ShortestPath、PathfindingConfig。load_subway_data 与 DATA_FILE_PATH。\n本事项先交付票价、行程时间、命令行与导出。三种路径与换乘限制由下一事项交付。'
        },
        {
          id: 'm-metro-delivery', project_id: P, work_item_id: 'w-metro-fare', kind: 'delivery', version: 1,
          title: '交付 r1', at: '2026-09-28T10:50:00+08:00',
          files: [
            { path: 'src/fare_calculator.py', bytes: 4820 },
            { path: 'src/cli.py', bytes: 2310 },
            { path: 'src/data_loader.py', bytes: 3560 },
            { path: 'tests/test_fare.py', bytes: 1680 }
          ],
          text: '实现 PRD r1 的票价、行程时间、命令行与导出。Sum_money(12000) 返回 4。文本导出含起点、终点、距离、票价、预计时间。JSON 字段为 origin、destination、distance_m、fare_yuan、estimated_min。pytest 3 passed。路径搜索留在换乘事项。'
        },
        {
          id: 'm-metro-qa', project_id: P, work_item_id: 'w-metro-fare', kind: 'qa', version: 1,
          title: '质检结论 r1', at: '2026-09-28T11:20:00+08:00', verdict: 'release',
          text: '放行。检查了分段边界：6000 米 3 元，12000 米 4 元，12001 米 5 元。命令行连续查询两次后退出码 0。JSON 字段名与接口约定一致。数据文件缺少终点站时完整性检查拒绝加载。三种路径模式不在本事项验收范围内。',
          snapshot: '7d2e915', criteria: criteriaOf(FARE_AC, {})
        },
        {
          id: 'm-metro-night-prd', project_id: P, work_item_id: 'w-metro-night', kind: 'prd', version: 1, level: 'pilot',
          title: 'PRD r1 夜间票价', at: '2026-09-28T11:06:00+08:00',
          text: '夜间票价。\n' + NIGHT_AC.map((ac) => ac[0] + ' ' + ac[1]).join('\n') + '\n验收：python -m pytest tests 覆盖每条验收条件。'
        },
        nightQa(1, 'n1a7c02', { 'AC-3': ['fail', 'JSON 导出没有 night 字段'], 'AC-4': ['fail', '缺少 22:59 的断言'] }, '导出没有标出夜间（AC-3），缺少 22:59 的边界断言（AC-4）。'),
        nightQa(2, 'n2b3e15', { 'AC-2': ['fail', '跨过 5:00 出站时按出站时间判定，少收 1 元'] }, '跨过 5:00 出站的行程按出站时间判定，少收 1 元（AC-2）。'),
        nightQa(3, 'n3c9d40', { 'AC-1': ['fail', '23:00 整进站被算成日间'] }, 'AC-2 改回按进站时间判定；23:00 整进站被算成日间（AC-1）。'),
        nightQa(4, 'n4d1f88', { 'AC-2': ['fail', '又改成按出站时间判定，跨过 5:00 少收 1 元'] }, '修 AC-1 时又把判定改回出站时间，跨过 5:00 的行程少收 1 元（AC-2）。'),
        {
          id: 'm-metro-note', project_id: P, work_item_id: 'w-metro-transfer', kind: 'note', version: 1,
          title: '换乘站处理', at: '2026-09-28T13:36:00+08:00',
          text: '换乘站按站名合并，不按线路分别计数。西直门同时在 2 号线与 4 号线时，一条路径只计一次换乘。综合最优不写入接口约定，评分用距离（米）加换乘次数乘 800。'
        }
      ],
      project_settings: {
        'p-metro': {
          version: 1,
          departments: { product: null, engineering: null, quality: null, operations: null },
          machines: [
            { machine_id: 'm-host', dirs: ['/work/p-metro'], level: '3.2C' },
            { machine_id: 'm-laptop', dirs: ['/work/p-metro'], level: '3.2C' }
          ],
          ops: { observe_hours: 24, max_repair_failures: 2, level: 'S4' },
          roles: {
            level: 'S5',
            product: [
              { role_id: 'prod-manager', model: null, level: null, prompt_text: null },
              { role_id: 'prod-architect', model: null, level: null, prompt_text: null }
            ],
            engineering: [
              { role_id: 'eng-manager', model: null, level: null, prompt_text: null },
              { role_id: 'eng-architect', model: null, level: null, prompt_text: null },
              { role_id: 'eng-lead', model: null, level: null, prompt_text: null },
              { role_id: 'eng-explorer', model: null, level: null, prompt_text: null },
              { role_id: 'eng-reviewer', model: null, level: null, prompt_text: null }
            ],
            quality: [
              { role_id: 'qa-manager', model: null, level: null, prompt_text: null },
              { role_id: 'qa-tester', model: null, level: null, prompt_text: null },
              { role_id: 'qa-explorer', model: null, level: null, prompt_text: null },
              { role_id: 'qa-reviewer', model: null, level: null, prompt_text: null }
            ]
          }
        }
      }
    },
    history: [
      ev({
        at: '2026-09-26T18:00:00+08:00', type: 'project_registered', actor: 'user',
        label: '用户从想法建立项目「北京地铁票价」',
        payload: { name: '北京地铁票价', source: 'idea' },
        patch: [{ path: 'projects[id=p-metro].last_activity_at', value: '2026-09-26T18:00:00+08:00' }]
      }),
      ev({
        at: '2026-09-26T18:10:00+08:00', type: 'work_item_created', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', actor: 'user',
        label: '用户提出事项「按里程计算票价」',
        payload: { title: '按里程计算票价' },
        patch: [{ path: 'projects[id=p-metro].last_activity_at', value: '2026-09-26T18:10:00+08:00' }]
      }),
      ev({
        at: '2026-09-26T18:10:00+08:00', type: 'run_created', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare',
        label: '按里程计算票价的 run 建立',
        payload: { yudao_version: '0.8.0' }
      }),
      ev({
        at: '2026-09-26T18:12:00+08:00', type: 'user_input_received', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', actor: 'user',
        label: '用户原文已接收：先做分段票价与命令行',
        payload: { progress: 'received' }
      }),
      ev({
        at: '2026-09-26T18:15:00+08:00', type: 'department_activated', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'product',
        label: '产品部门开始写分段票价的 PRD',
        payload: {},
        patch: [
          { path: 'work_items[id=w-metro-fare].status', value: 'in_progress' },
          { path: 'runs[id=r-metro-fare].phase', value: 'PRODUCT_SPEC' },
          { path: 'runs[id=r-metro-fare].department', value: 'product' },
          { path: 'runs[id=r-metro-fare].cycle', value: 1 },
          { path: 'runs[id=r-metro-fare].elapsed_sec', value: 300 },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-metro-fare', department: 'product', role: null } },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-26T18:15:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-26T18:36:00+08:00', type: 'spec_accepted', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'product',
        label: '主机接纳 PRD r1，12 公里整写明按 4 元；工程关注的 PRD 有了新版本',
        payload: { material_id: 'm-metro-prd' },
        patch: [
          { path: 'runs[id=r-metro-fare].department', value: 'engineering' },
          { path: 'runs[id=r-metro-fare].last_department', value: 'product' },
          { path: 'runs[id=r-metro-fare].phase', value: 'ENGINEERING' },
          { path: 'runtime.slots.used[work_item_id=w-metro-fare].department', value: 'engineering' },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-26T18:36:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-26T18:42:00+08:00', type: 'department_activated', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '工程部门开始按 PRD 实现票价',
        payload: {}
      }),
      ev({
        at: '2026-09-26T19:05:00+08:00', type: 'ask_started', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '工程询问产品：12 公里整是否按 6 元',
        payload: { ask_id: 'q-fare-12km', requester: 'engineering', recipient: 'product', question: fareAsk },
        patch: [{ path: 'projects[id=p-metro].last_activity_at', value: '2026-09-26T19:05:00+08:00' }]
      }),
      ev({
        at: '2026-09-26T19:22:00+08:00', type: 'ask_answered', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'product',
        label: '产品回答工程：12 公里整按 4 元，不进入 6 元档',
        payload: { ask_id: 'q-fare-12km', requester: 'engineering', recipient: 'product', result: 'answered', answer: fareAnswer },
        patch: [
          { path: 'runs[id=r-metro-fare].asks[id=q-fare-12km].status', value: 'answered' },
          { path: 'runs[id=r-metro-fare].asks[id=q-fare-12km].answer', value: fareAnswer },
          { path: 'runs[id=r-metro-fare].asks[id=q-fare-12km].answered_at', value: '2026-09-26T19:22:00+08:00' },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-26T19:22:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-27T16:40:00+08:00', type: 'compaction_recorded', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '工程上下文接近上限，整理出摘要 1',
        payload: { n: 1, coverage: 'seq 8–46' },
        patch: [
          { path: 'runs[id=r-metro-fare].elapsed_sec', value: 4100 },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-27T16:40:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T10:40:00+08:00', type: 'tool_called', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '命令 python -m pytest tests/test_fare.py 通过，12000 米为 4 元',
        payload: { tool: 'bash', command: 'python -m pytest tests/test_fare.py', exit_code: 0, timed_out: false },
        patch: [{ path: 'runs[id=r-metro-fare].elapsed_sec', value: 5200 }]
      }),
      ev({
        at: '2026-09-28T10:50:00+08:00', type: 'delivery_accepted', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '主机接纳交付 r1，质检关注的交付到达',
        payload: { material_id: 'm-metro-delivery' },
        patch: [
          { path: 'runs[id=r-metro-fare].department', value: 'quality' },
          { path: 'runs[id=r-metro-fare].last_department', value: 'engineering' },
          { path: 'runs[id=r-metro-fare].phase', value: 'QUALITY' },
          { path: 'runtime.slots.used[work_item_id=w-metro-fare].department', value: 'quality' }
        ]
      }),
      ev({
        at: '2026-09-28T10:52:00+08:00', type: 'department_activated', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'quality',
        label: '质检开始核对 12000 米的票价',
        payload: {}
      }),
      ev({
        at: '2026-09-28T11:20:00+08:00', type: 'qa_submitted', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'quality',
        label: '质检放行按里程计算票价',
        payload: { verdict: 'release', material_id: 'm-metro-qa' },
        patch: [
          { path: 'work_items[id=w-metro-fare].status', value: 'released' },
          { path: 'runs[id=r-metro-fare].elapsed_sec', value: 5400 },
          { path: 'runs[id=r-metro-fare].department', value: null },
          { path: 'runs[id=r-metro-fare].last_department', value: 'quality' },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-28T11:20:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T11:25:00+08:00', type: 'deliverable_adopted', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', actor: 'user',
        label: '用户采纳按里程计算票价 r1',
        payload: { version: 'r1' },
        patch: [
          { path: 'work_items[id=w-metro-fare].status', value: 'adopted' },
          { path: 'runs[id=r-metro-fare].phase', value: 'DONE' },
          { path: 'runs[id=r-metro-fare].department', value: null },
          { path: 'projects[id=p-metro].adoptions', push: { version: 'r1', work_item_id: 'w-metro-fare', summary: '分段票价与命令行查询，12 公里整为 4 元', adopted_at: '2026-09-28T11:25:00+08:00' } },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-metro-fare' } },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-28T11:25:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T13:00:00+08:00', type: 'work_item_created', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', actor: 'user',
        label: '用户提出事项「换乘站与最短路径」',
        payload: { title: '换乘站与最短路径' },
        patch: [{ path: 'projects[id=p-metro].last_activity_at', value: '2026-09-28T13:00:00+08:00' }]
      }),
      ev({
        at: '2026-09-28T13:00:00+08:00', type: 'run_created', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer',
        label: '换乘站与最短路径的 run 建立',
        payload: { yudao_version: '0.8.0' }
      }),
      ev({
        at: '2026-09-28T13:05:00+08:00', type: 'department_activated', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'product',
        label: '产品部门开始写三种路径与换乘限制',
        payload: {},
        patch: [
          { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' },
          { path: 'runs[id=r-metro-transfer].phase', value: 'PRODUCT_SPEC' },
          { path: 'runs[id=r-metro-transfer].department', value: 'product' },
          { path: 'runs[id=r-metro-transfer].cycle', value: 1 },
          { path: 'runs[id=r-metro-transfer].elapsed_sec', value: 240 },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-metro-transfer', department: 'product', role: null } }
        ]
      }),
      ev({
        at: '2026-09-28T13:40:00+08:00', type: 'spec_accepted', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'product',
        label: '主机接纳换乘路径的 PRD r1，工程与质检关注的 PRD 有了新版本',
        payload: {},
        patch: [
          { path: 'runs[id=r-metro-transfer].department', value: 'engineering' },
          { path: 'runs[id=r-metro-transfer].last_department', value: 'product' },
          { path: 'runs[id=r-metro-transfer].phase', value: 'ENGINEERING' },
          { path: 'runtime.slots.used[work_item_id=w-metro-transfer].department', value: 'engineering' },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-28T13:40:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T13:41:00+08:00', type: 'department_activated', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
        label: '工程部门开始实现换乘站去重',
        payload: {}
      }),
      ev({
        at: '2026-09-28T14:30:00+08:00', type: 'department_activated', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
        label: '工程部门进入第 2 轮：按站名合并换乘站以后实现最短路径',
        payload: {},
        patch: [
          { path: 'runs[id=r-metro-transfer].cycle', value: 2 },
          { path: 'runs[id=r-metro-transfer].elapsed_sec', value: 3200 },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-28T14:30:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T15:40:00+08:00', type: 'work_item_created', work_item_id: 'w-metro-card', run_id: 'r-metro-card', actor: 'user', level: '3.4A',
        label: '用户提出事项「公交卡折扣」，进入同一项目的队列',
        payload: { title: '公交卡折扣' }
      }),
      ev({
        at: '2026-09-28T15:40:00+08:00', type: 'run_created', work_item_id: 'w-metro-card', run_id: 'r-metro-card', level: '3.4A',
        label: '公交卡折扣的 run 建立，尚未取得执行槽位',
        payload: { yudao_version: '0.8.0' }
      }),
      ev({
        at: '2026-09-28T15:40:00+08:00', type: 'x_queued', work_item_id: 'w-metro-card', run_id: 'r-metro-card', level: '3.4A',
        label: '公交卡折扣排在本项目队列第 1 位',
        payload: {},
        patch: [
          { path: 'work_items[id=w-metro-card].status', value: 'queued' },
          { path: 'work_items[id=w-metro-card].queue_reason', value: 'project' },
          { path: 'work_items[id=w-metro-card].queue_pos', value: 1 },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-28T15:40:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T16:10:00+08:00', type: 'work_item_created', work_item_id: 'w-metro-report', run_id: 'r-metro-report', actor: 'user', level: '3.4A',
        label: '用户提出事项「导出月度出行统计」',
        payload: { title: '导出月度出行统计' }
      }),
      ev({
        at: '2026-09-28T16:10:00+08:00', type: 'run_created', work_item_id: 'w-metro-report', run_id: 'r-metro-report', level: '3.4A',
        label: '月度出行统计的 run 建立，尚未取得执行槽位',
        payload: { yudao_version: '0.8.0' }
      }),
      ev({
        at: '2026-09-28T16:10:00+08:00', type: 'x_queued', work_item_id: 'w-metro-report', run_id: 'r-metro-report', level: '3.4A',
        label: '月度出行统计排在本项目队列第 2 位',
        payload: {},
        patch: [
          { path: 'work_items[id=w-metro-report].status', value: 'queued' },
          { path: 'work_items[id=w-metro-report].queue_reason', value: 'project' },
          { path: 'work_items[id=w-metro-report].queue_pos', value: 2 }
        ]
      }),
      ev({
        at: '2026-09-29T03:02:00+08:00', type: 'tool_started', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
        label: '工程部门开始执行命令 python -m pytest tests',
        payload: { tool: 'bash', command: 'python -m pytest tests' },
        patch: [
          { path: 'runs[id=r-metro-transfer].elapsed_sec', value: 4980 },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-29T03:02:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-29T03:02:00+08:00', type: 'x_remote_action_started', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.2C',
        label: '命令 python -m pytest tests 在笔记本上开始执行',
        payload: { machine_id: 'm-laptop', action_id: 'a-metro-unit-17', label: '命令 python -m pytest tests' },
        patch: [
          { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].machine_id', value: 'm-laptop' },
          {
            path: 'machines[id=m-laptop].actions',
            push: { project_id: P, work_item_id: 'w-metro-transfer', department: 'engineering', action_id: 'a-metro-unit-17', label: '命令 python -m pytest tests', state: 'running' }
          }
        ]
      }),
      ev({
        at: '2026-09-29T03:11:00+08:00', type: 'model_stream_progress', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
        label: '工程仍在等待测试命令的退出码',
        payload: { text: 'python -m pytest tests 还在运行，还没有退出码。' },
        patch: [{ path: 'projects[id=p-metro].last_activity_at', value: '2026-09-29T03:11:00+08:00' }]
      }),
      ev({
        at: '2026-09-29T03:12:00+08:00', type: 'x_run_interrupted', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.1',
        label: '控制主机断电，换乘站的 run 中断',
        payload: { reason: '控制主机断电' },
        patch: [
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'interrupted' },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '控制主机断电，时钟停在 03:12' },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-metro-transfer' } }
        ]
      }),
      ev({
        at: '2026-09-29T03:13:00+08:00', type: 'x_run_auto_resumed', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.1',
        label: '控制主机重新启动，自动继续换乘站的 run',
        payload: { boot_id: 'boot-0929-0313' },
        patch: [
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
          { path: 'runs[id=r-metro-transfer].recovery.auto_resumed_at', value: '2026-09-29T03:13:00+08:00' },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '已自动继续，正在核实断电前的动作' }
        ]
      }),
      // 重新启动时结果未知的动作（恢复契约第 4 节）：本机进程在断电时一起结束，命令不能按快照核实，
      // 作为工具结果交还工程的会话，由模型检查以后决定是否重新执行（3.1）；
      // 3.2C 起这条命令在笔记本上执行，笔记本 03:10 起离线，事项待恢复，显示等待机器，等它恢复在线以后按尝试身份核实
      ev({
        at: '2026-09-29T03:14:00+08:00', type: 'x_action_unknown', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.1',
        label: '命令 python -m pytest tests 的结果未知：断电时没有收到退出码',
        payload: { action_id: 'a-metro-unit-17' },
        patch: [
          { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'unknown' },
          { path: 'runs[id=r-metro-transfer].recovery.unfinished', push: { id: 'a-metro-unit-17', label: '命令 python -m pytest tests' } },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '最后已确认的位置是换乘站去重已写入，测试命令已开始但没有退出码' },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-29T03:14:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-29T03:14:00+08:00', type: 'action_verified', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.1', until: '3.2C',
        label: '结果未知的命令交还工程的会话：执行被中断、结果未知，附上已经收到的输出',
        payload: { action_id: 'a-metro-unit-17', handling: 'returned', session: 's-xfer-engineering' },
        patch: [
          {
            path: 'runs[id=r-metro-transfer].recovery.verifications', push: {
              action_id: 'a-metro-unit-17', handling: 'returned', session: '工程：换乘站去重与最短路径', at: '2026-09-29T03:14:00+08:00',
              basis: '本机进程：控制主机断电时进程树一起结束，没有退出码；命令没有可以按快照核实的结果',
              returned: '执行被中断，结果未知。已经收到的输出：tests/test_pathfinding.py ........（8 个用例通过，其余没有输出）。请检查工作区的实际状态以后决定是否重新执行。'
            }
          },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '已自动继续；断电前的测试命令结果未知，已交还工程的会话' }
        ]
      }),
      ev({
        at: '2026-09-29T03:16:00+08:00', type: 'tool_started', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.1', until: '3.2C',
        label: '工程读到交还的工具结果，重新执行 python -m pytest tests',
        payload: { tool: 'bash', command: 'python -m pytest tests' },
        patch: [{
          path: 'runs[id=r-metro-transfer].actions', push: {
            id: 'a-metro-unit-18', department: 'engineering', role: 'eng-lead', tool: 'bash',
            summary: '执行命令 python -m pytest tests（重新执行）', input: '交还的工具结果：上一次执行被中断、结果未知',
            state: 'done', machine_id: null, at: '2026-09-29T03:16:00+08:00',
            before: '工作区与断电前相同', after: '12 passed',
            receipt: { command: 'python -m pytest tests', exit_code: 0, output: '12 passed in 4.1s', truncated: false, timed_out: false, duration_ms: 4100, snapshot: 'ws-9c04e1b' }
          }
        }]
      }),
      ev({
        at: '2026-09-29T03:14:00+08:00', type: 'x_action_unknown', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.2C',
        label: '笔记本离线，命令 python -m pytest tests 的结果未知，事项等待机器',
        payload: { action_id: 'a-metro-unit-17', machine_id: 'm-laptop' },
        patch: [
          { path: 'machines[id=m-laptop].actions[action_id=a-metro-unit-17].state', value: 'unknown' },
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'waiting_resume' },
          { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: { machine_id: 'm-laptop', since: '2026-09-29T03:10:00+08:00', problem: '离线' } },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '笔记本 03:10 起离线：测试命令的结果要等它恢复在线以后按尝试身份核实' }
        ]
      }),
      // 「夜间票价」：四轮质检 AC-2 来回翻转，run 在 12:58 用完运行时间
      night({
        at: '2026-09-28T10:58:00+08:00', type: 'work_item_created', actor: 'user', label: '用户提出事项「夜间票价」', payload: { kind: 'request' },
        patch: [{ path: 'work_items[id=w-metro-night].status', value: 'in_progress' }]
      }),
      night({ at: '2026-09-28T10:58:00+08:00', type: 'run_created', label: '夜间票价的 run 创建，产品部门开始' }),
      night({ at: '2026-09-28T10:58:00+08:00', type: 'department_activated', department: 'product', label: '产品部门整理夜间票价的要求' }),
      night({
        at: '2026-09-28T11:06:00+08:00', type: 'spec_accepted', department: 'product', label: '产品提交 PRD r1（夜间票价，4 条验收条件），主机接纳；工程关注的 PRD 有了新版本',
        payload: { material_id: 'm-metro-night-prd' }, patch: [nightRun('elapsed_sec', 540), nightRun('department', 'engineering'), nightRun('last_department', 'product')]
      }),
      night({ at: '2026-09-28T11:07:00+08:00', type: 'department_activated', department: 'engineering', label: '工程部门开始实现夜间票价', patch: [nightRun('elapsed_sec', 1080)] }),
      ...nightRound(1, ['11:24', '11:25', '11:30', '11:31'], 'n1a7c02', [1560, 1920], '质检结论 r1：缺陷记录——导出没有标出夜间，缺少 22:59 的断言（2 条未满足）'),
      ...nightRound(2, ['11:40', '11:41', '11:46', '11:47'], 'n2b3e15', [2700, 3300], '质检结论 r2：缺陷记录——跨过 5:00 出站时按出站时间判定（1 条未满足）'),
      ...nightRound(3, ['11:56', '11:57', '12:02', '12:03'], 'n3c9d40', [3900, 4500], '质检结论 r3：缺陷记录——23:00 整进站被算成日间（1 条未满足）'),
      ...nightRound(4, ['12:12', '12:13', '12:18', '12:19'], 'n4d1f88', [5100, 5700], '质检结论 r4：缺陷记录——跨过 5:00 又按出站时间判定（1 条未满足）'),
      nightStep('12:24', 'edit_range', 'src/fare_calculator.py', '工程部门按区间编辑 src/fare_calculator.py：夜间判定按进站时间'),
      nightStep('12:32', 'bash', 'python -m pytest tests/test_night_fare.py', '工程部门执行命令 python -m pytest tests/test_night_fare.py', [nightRun('elapsed_sec', 6300)]),
      nightStep('12:40', 'edit_range', 'src/fare_calculator.py', '工程部门按区间编辑 src/fare_calculator.py：23:00 整算作夜间'),
      nightStep('12:48', 'bash', 'python -m pytest tests/test_night_fare.py', '工程部门再次执行同一条测试命令', [nightRun('elapsed_sec', 6720)]),
      nightStep('12:54', 'bash', 'python -m pytest tests/test_night_fare.py', '工程部门第三次执行同一条测试命令', [nightRun('elapsed_sec', 6960)]),
      night({
        at: '2026-09-28T12:58:00+08:00', type: 'run_failed', department: 'engineering', label: '夜间票价的 run 用完运行时间（7200/7200 秒），停止',
        payload: { reason: 'time_limit' },
        patch: [
          { path: 'work_items[id=w-metro-night].status', value: 'stopped' },
          nightRun('phase', 'FAILED'), nightRun('department', null), nightRun('last_department', 'engineering'),
          nightRun('stop_reason', { code: 'time_limit', text: '运行时间上限' }), nightRun('elapsed_sec', 7200),
          nightRun('recovery.state', 'stopped'), nightRun('recovery.reason', '用完运行时间')
        ]
      })
    ],
    scenarios: [
      {
        no: 3, id: 'sc-metro-ask', name: '询问与回答', level: 'ui', go: '#/p/p-metro/overview',
        // 询问是一次工具调用（三部门的循环结构第 4 节）：提问方停在这次调用上，被询问的部门在询问分支里回答；
        // 产品回答前回问工程（询问链：工程 → 产品 → 工程），回答里附带 PRD 的新版本，质检关注的 PRD 被接纳，开始预测性探索
        setup: [
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
          { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: null },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '运行中' },
          { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门在一轮工作中，要先弄清线路偏好的含义', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'ask_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程询问产品：线路偏好是否改变最短距离模式的实际距离', payload: { ask_id: 'q-sc-prefer', requester: 'engineering', recipient: 'product', question: '线路偏好是否改变最短距离模式的实际距离？' } }, patch: [{ path: 'runs[id=r-metro-transfer].asks', push: { id: 'q-sc-prefer', requester: 'engineering', recipient: 'product', parent: null, question: '线路偏好是否改变最短距离模式的实际距离？', status: 'open', answer: null, reason: null, prd_version: null, born_at: '2026-09-29T15:31:00+08:00', answered_at: null } }] },
          { delay: 1400, event: { type: 'ask_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'product', label: '产品在询问分支里回问工程：综合最优现在怎样计算权重', payload: { ask_id: 'q-sc-back', requester: 'product', recipient: 'engineering', question: '综合最优现在怎样计算权重？我要先看现有实现再回答。' } }, patch: [{ path: 'runs[id=r-metro-transfer].asks', push: { id: 'q-sc-back', requester: 'product', recipient: 'engineering', parent: 'q-sc-prefer', question: '综合最优现在怎样计算权重？我要先看现有实现再回答。', status: 'open', answer: null, reason: null, born_at: '2026-09-29T15:31:00+08:00', answered_at: null } }] },
          { delay: 1400, event: { type: 'ask_answered', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程在另开的询问分支里回答产品：综合分 = 距离 + 换乘次数 × 800', payload: { ask_id: 'q-sc-back', requester: 'product', recipient: 'engineering', result: 'answered', answer: '综合分 = 距离（米）+ 换乘次数 × 800；线路偏好的边权在 pathfinding.weight() 里乘 0.8。' } }, patch: [{ path: 'runs[id=r-metro-transfer].asks[id=q-sc-back].status', value: 'answered' }, { path: 'runs[id=r-metro-transfer].asks[id=q-sc-back].answer', value: '综合分 = 距离（米）+ 换乘次数 × 800；线路偏好的边权在 pathfinding.weight() 里乘 0.8。' }, { path: 'runs[id=r-metro-transfer].asks[id=q-sc-back].answered_at', value: '2026-09-29T15:32:00+08:00' }] },
          { delay: 1400, event: { type: 'ask_answered', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'product', label: '产品回答工程：最短距离不乘 0.8，只影响综合最优；PRD 修订为 r2', payload: { ask_id: 'q-sc-prefer', requester: 'engineering', recipient: 'product', result: 'answered', answer: '最短距离模式按实际距离，不乘 0.8；线路偏好只影响综合最优。PRD 修订为 r2，写明这一点。', prd_version: 'r2' } }, patch: [{ path: 'runs[id=r-metro-transfer].asks[id=q-sc-prefer].status', value: 'answered' }, { path: 'runs[id=r-metro-transfer].asks[id=q-sc-prefer].answer', value: '最短距离模式按实际距离，不乘 0.8；线路偏好只影响综合最优。PRD 修订为 r2，写明这一点。' }, { path: 'runs[id=r-metro-transfer].asks[id=q-sc-prefer].prd_version', value: 'r2' }, { path: 'runs[id=r-metro-transfer].asks[id=q-sc-prefer].answered_at', value: '2026-09-29T15:32:00+08:00' }] },
          { delay: 1400, event: { type: 'spec_accepted', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'product', label: 'PRD r2 被接纳：工程在下一步收到通知接着工作，质检关注的 PRD 有了新版本', payload: { version: 'r2' } }, patch: [] },
          { delay: 1200, event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'quality', label: '质检开始预测性探索：交付到达之前按 PRD r2 起草测试用例，与工程同时工作', payload: { predictive: true } }, patch: [{ path: 'runs[id=r-metro-transfer].departments', value: { quality: { state: 'working', note: '预测性探索：按 PRD r2 起草测试用例' } } }] },
          { delay: 1200, event: { type: 'ask_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'quality', label: '质检询问工程：西直门是否只计一次换乘', payload: { ask_id: 'q-sc-xzm', requester: 'quality', recipient: 'engineering', question: '西直门同时在 2 号线与 4 号线，一条路径是否只计一次换乘？' } }, patch: [{ path: 'runs[id=r-metro-transfer].asks', push: { id: 'q-sc-xzm', requester: 'quality', recipient: 'engineering', parent: null, question: '西直门同时在 2 号线与 4 号线，一条路径是否只计一次换乘？', status: 'open', answer: null, reason: null, born_at: '2026-09-29T15:33:00+08:00', answered_at: null } }] },
          { delay: 1400, event: { type: 'ask_answered', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程回答质检：按站名合并，西直门只计一次', payload: { ask_id: 'q-sc-xzm', requester: 'quality', recipient: 'engineering', result: 'answered', answer: '按站名合并，西直门在一条路径里只计一次换乘。' } }, patch: [{ path: 'runs[id=r-metro-transfer].asks[id=q-sc-xzm].status', value: 'answered' }, { path: 'runs[id=r-metro-transfer].asks[id=q-sc-xzm].answer', value: '按站名合并，西直门在一条路径里只计一次换乘。' }, { path: 'runs[id=r-metro-transfer].asks[id=q-sc-xzm].answered_at', value: '2026-09-29T15:34:00+08:00' }] },
          { delay: 1200, event: { type: 'ask_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'quality', label: '质检又问最大换乘数的默认值，信件停在工程的传信管出口', payload: { ask_id: 'q-sc-max', requester: 'quality', recipient: 'engineering', question: '用户不填最大换乘数时，默认不限制，还是默认 3 次？' } }, patch: [{ path: 'runs[id=r-metro-transfer].asks', push: { id: 'q-sc-max', requester: 'quality', recipient: 'engineering', parent: null, question: '用户不填最大换乘数时，默认不限制，还是默认 3 次？', status: 'open', answer: null, reason: null, born_at: '2026-09-29T15:34:00+08:00', answered_at: null } }] },
          { delay: 1200, go: '#/p/p-metro/overview', label: '概览列出这个事项的询问与询问链；质检写着「在等待工程的回答」，工程一边工作一边回答质检的询问' }
        ]
      },
      {
        no: 5, id: 'sc-metro-compact', name: '压缩', level: 'ui', go: '#/p/p-metro/overview',
        setup: [],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'context_assembled', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程上下文装入全部路径搜索记录，接近工作上限', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'model_stream_progress', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '模型还在输出路径比较，桌上的纸堆升高', payload: { text: '最短距离与最少换乘的差异集中在西直门、建国门两个换乘站。' } }, patch: [] },
          { delay: 1400, event: { type: 'compaction_recorded', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '小人把桌上的纸整理进摘要档案盒，编号变为 1', payload: { n: 1 } }, patch: [{ path: 'runs[id=r-metro-transfer].compactions', push: { department: 'engineering', n: 1, at: '2026-09-29T15:32:00+08:00', coverage: 'seq 1–40', event_id: null } }] },
          { delay: 1200, event: { type: 'context_assembled', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '下一次请求使用摘要 1 与最近的原始记录', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'model_requested', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门再次请求模型，上下文已经用上摘要', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'compaction_failed', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '第二次整理没有生效，纸堆散落', payload: { reason: '摘要没有覆盖未完成的测试命令' } }, patch: [] },
          { delay: 1400, event: { type: 'context_assembled', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '小人重新整理散落的纸，先拣出未完成动作', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'compaction_recorded', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '重新整理完成，摘要编号变为 2', payload: { n: 2 } }, patch: [{ path: 'runs[id=r-metro-transfer].compactions', push: { department: 'engineering', n: 2, at: '2026-09-29T15:34:00+08:00', coverage: 'seq 1–52', event_id: null } }] },
          { delay: 1200, event: { type: 'model_attempt_finished', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '使用摘要 2 的请求完成', payload: {} }, patch: [] },
          { delay: 1000, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程继续工作，档案盒上是摘要 2', payload: {} }, patch: [] }
        ]
      },
      {
        no: 7, id: 'sc-metro-interrupt', name: '中断与自动继续', level: '3.1', go: '#/p/p-metro/overview',
        setup: [
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '运行中' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程正在执行测试命令，管道正常流动', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门在终端前执行命令 python -m pytest tests', payload: { tool: 'bash', command: 'python -m pytest tests' } }, patch: [] },
          { delay: 1400, event: { type: 'x_run_interrupted', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '控制主机断电，整层变暗，时钟停住，管道停止', payload: { reason: '控制主机断电' } }, patch: [{ path: 'runs[id=r-metro-transfer].recovery.state', value: 'interrupted' }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '控制主机断电，时钟停住' }] },
          { delay: 1600, go: '#/p/p-metro/overview', event: { type: 'model_stream_progress', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '中断期间没有新的模型输出，小人静止', payload: { text: '' } }, patch: [] },
          { delay: 1400, event: { type: 'x_run_auto_resumed', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '控制主机重新启动，灯亮起，时钟继续走，管道恢复流动', payload: { boot_id: 'boot-0929-0313' } }, patch: [{ path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' }, { path: 'runs[id=r-metro-transfer].recovery.auto_resumed_at', value: '2026-09-29T15:33:00+08:00' }] },
          { delay: 1200, event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门伸懒腰后回到工位', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'context_assembled', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '自动继续后重新装配上下文，恢复不清零已用时间', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'model_requested', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门继续核对断电前写到哪一步', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'model_attempt_finished', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '核对完成，最后已确认的位置仍是换乘站去重已写入', payload: {} }, patch: [] },
          { delay: 1000, go: '#/p/p-metro/overview', event: { type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '管道恢复流动，工程继续查看测试输出', payload: { tool: 'read_file' } }, patch: [] }
        ]
      },
      {
        // 重新启动时结果未知的动作（恢复契约第 4 节）：有核实方法的文件编辑按快照核实确认；命令没有核实方法，
        // 作为工具结果交还发出它的会话，由模型检查以后决定重新执行。没有用户的决定
        no: 8, id: 'sc-metro-unknown', name: '结果未知的动作：核实与交还会话', level: '3.1', go: '#/p/p-metro/overview',
        setup: [
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
          { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: null },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '运行中' },
          { path: 'runs[id=r-metro-transfer].recovery.unfinished', value: [] },
          { path: 'runs[id=r-metro-transfer].recovery.verifications', value: [] },
          { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门按区间编辑 src/pathfinding.py：最大换乘数默认不限制', payload: { tool: 'edit_range', target: 'src/pathfinding.py' } }, patch: [{ path: 'runs[id=r-metro-transfer].actions', push: { id: 'a-metro-sc-edit', department: 'engineering', role: 'eng-lead', tool: 'edit_range', summary: '按区间编辑 src/pathfinding.py：最大换乘数默认不限制', input: 'PRD r2：用户不填最大换乘数时不限制', state: 'running', machine_id: null, at: '2026-09-29T15:30:00+08:00', before: '快照 ws-9c04e1b：max_transfers 默认 3', after: null, receipt: null } }] },
          { delay: 1200, event: { type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门执行命令 python -m pytest tests/test_transfer.py', payload: { tool: 'bash', command: 'python -m pytest tests/test_transfer.py' } }, patch: [{ path: 'runs[id=r-metro-transfer].actions', push: { id: 'a-metro-sc-test', department: 'engineering', role: 'eng-lead', tool: 'bash', summary: '执行命令 python -m pytest tests/test_transfer.py', input: '最大换乘数的自测', state: 'running', machine_id: null, at: '2026-09-29T15:30:00+08:00', before: '测试尚未开始', after: null, receipt: null } }] },
          { delay: 1400, event: { type: 'x_run_interrupted', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '控制主机断电，整层变暗，两个动作都没有收到结果', payload: { reason: '控制主机断电' } }, patch: [{ path: 'runs[id=r-metro-transfer].recovery.state', value: 'interrupted' }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '控制主机断电，时钟停住' }] },
          { delay: 1400, event: { type: 'x_run_auto_resumed', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '控制主机重新启动，自动继续，先处理断电前没有结果的动作', payload: { boot_id: 'boot-0929-1531' } }, patch: [{ path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' }, { path: 'runs[id=r-metro-transfer].recovery.auto_resumed_at', value: '2026-09-29T15:31:00+08:00' }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '已自动继续，正在核实断电前的动作' }] },
          { delay: 1200, event: { type: 'x_action_unknown', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '编辑 src/pathfinding.py 的结果未知', payload: { action_id: 'a-metro-sc-edit' } }, patch: [{ path: 'runs[id=r-metro-transfer].actions[id=a-metro-sc-edit].state', value: 'unknown' }, { path: 'runs[id=r-metro-transfer].recovery.unfinished', push: { id: 'a-metro-sc-edit', label: '按区间编辑 src/pathfinding.py' } }] },
          { delay: 1200, event: { type: 'x_action_unknown', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '命令 python -m pytest tests/test_transfer.py 的结果未知', payload: { action_id: 'a-metro-sc-test' } }, patch: [{ path: 'runs[id=r-metro-transfer].actions[id=a-metro-sc-test].state', value: 'unknown' }, { path: 'runs[id=r-metro-transfer].recovery.unfinished', push: { id: 'a-metro-sc-test', label: '命令 python -m pytest tests/test_transfer.py' } }] },
          { delay: 1400, event: { type: 'action_verified', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '编辑按快照核实确认：文件内容与这次编辑的结果相同', payload: { action_id: 'a-metro-sc-edit', handling: 'confirmed' } }, patch: [{ path: 'runs[id=r-metro-transfer].actions[id=a-metro-sc-edit].state', value: 'done' }, { path: 'runs[id=r-metro-transfer].actions[id=a-metro-sc-edit].after', value: 'max_transfers 默认不限制' }, { path: 'runs[id=r-metro-transfer].recovery.verifications', push: { action_id: 'a-metro-sc-edit', handling: 'confirmed', session: '工程：换乘站去重与最短路径', at: '2026-09-29T15:31:00+08:00', basis: '文件工具按动作前后的快照核实：src/pathfinding.py 的当前内容与这次编辑的结果相同', result: '编辑已经写入，交回工程的会话', returned: null } }] },
          { delay: 1400, event: { type: 'action_verified', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '命令没有核实方法，作为工具结果交还工程的会话', payload: { action_id: 'a-metro-sc-test', handling: 'returned', session: 's-xfer-engineering' } }, patch: [{ path: 'runs[id=r-metro-transfer].recovery.verifications', push: { action_id: 'a-metro-sc-test', handling: 'returned', session: '工程：换乘站去重与最短路径', at: '2026-09-29T15:31:00+08:00', basis: '本机进程：控制主机断电时进程树一起结束，没有退出码；命令没有可以按快照核实的结果', result: null, returned: '执行被中断，结果未知。已经收到的输出：tests/test_transfer.py ...（3 个用例通过，其余没有输出）。请检查工作区的实际状态以后决定是否重新执行。' } }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '已自动继续；断电前的编辑已核实确认，测试命令结果未知，已交还工程的会话' }] },
          { delay: 1400, go: '#/p/p-metro/w/w-metro-transfer/recovery', label: '恢复页列出两条结果未知的动作：编辑核实确认，命令交还会话，各写明依据；没有要你回答的决定' },
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'model_requested', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程读到交还的工具结果，决定重新执行测试', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门重新执行命令 python -m pytest tests/test_transfer.py', payload: { tool: 'bash', command: 'python -m pytest tests/test_transfer.py' } }, patch: [{ path: 'runs[id=r-metro-transfer].actions', push: { id: 'a-metro-sc-test2', department: 'engineering', role: 'eng-lead', tool: 'bash', summary: '执行命令 python -m pytest tests/test_transfer.py（重新执行）', input: '交还的工具结果：上一次执行被中断、结果未知', state: 'running', machine_id: null, at: '2026-09-29T15:32:00+08:00', before: '工作区与核实时相同', after: null, receipt: null } }] },
          { delay: 1400, event: { type: 'tool_called', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '测试命令执行完成，退出码 0', payload: { tool: 'bash', command: 'python -m pytest tests/test_transfer.py', exit_code: 0, timed_out: false } }, patch: [{ path: 'runs[id=r-metro-transfer].actions[id=a-metro-sc-test2].state', value: 'done' }, { path: 'runs[id=r-metro-transfer].actions[id=a-metro-sc-test2].after', value: '6 passed' }, { path: 'runs[id=r-metro-transfer].actions[id=a-metro-sc-test2].receipt', value: { command: 'python -m pytest tests/test_transfer.py', exit_code: 0, output: '6 passed in 1.8s', truncated: false, timed_out: false, duration_ms: 1800, snapshot: 'ws-9c05a20' } }] },
          { delay: 1000, event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程回到工位继续工作', payload: {} }, patch: [] }
        ]
      },
      {
        // 远程动作的结果未知（执行环境服务设计说明第 6.3 至 6.5 节）：笔记本离线时事项待恢复，显示等待机器；
        // 恢复在线以后按尝试身份取得动作记录，已结束的取得回执，核实确认，事项自动继续
        no: 10, id: 'sc-metro-offline', name: '执行代理离线：等待机器与按尝试身份核实', level: '3.2C', go: '#/p/p-metro/overview',
        setup: [
          { path: 'machines[id=m-laptop].online', value: true },
          { path: 'machines[id=m-laptop].actions', remove: { key: 'action_id', value: 'a-metro-unit-17' } },
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
          { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: null },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '运行中' },
          { path: 'runs[id=r-metro-transfer].recovery.unfinished', value: [] },
          { path: 'runs[id=r-metro-transfer].recovery.verifications', value: [] },
          { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'running' },
          { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'x_remote_action_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '笔记本开始执行命令 python -m pytest tests', payload: { machine_id: 'm-laptop', action_id: 'a-metro-unit-17', label: '命令 python -m pytest tests' } }, patch: [{ path: 'machines[id=m-laptop].actions', push: { project_id: P, work_item_id: 'w-metro-transfer', department: 'engineering', action_id: 'a-metro-unit-17', label: '命令 python -m pytest tests', state: 'running' } }] },
          { delay: 1200, event: { type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '通往机房的门上出现笔记本的动作', payload: { tool: 'bash', command: 'python -m pytest tests' } }, patch: [] },
          { delay: 1400, event: { type: 'x_machine_offline', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', label: '笔记本的执行代理心跳中断', payload: { machine_id: 'm-laptop' } }, patch: [{ path: 'machines[id=m-laptop].online', value: false }] },
          { delay: 1400, event: { type: 'x_action_unknown', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '40 秒没有心跳，测试命令的结果未知，事项等待机器', payload: { action_id: 'a-metro-unit-17', machine_id: 'm-laptop' } }, patch: [{ path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'unknown' }, { path: 'runs[id=r-metro-transfer].recovery.unfinished', push: { id: 'a-metro-unit-17', label: '命令 python -m pytest tests' } }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'waiting_resume' }, { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: { machine_id: 'm-laptop', since: '2026-09-29T15:30:00+08:00', problem: '离线' } }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '笔记本离线：测试命令的结果要等它恢复在线以后按尝试身份核实' }, { path: 'machines[id=m-laptop].actions[action_id=a-metro-unit-17].state', value: 'unknown' }] },
          { delay: 1200, go: '#/p/p-metro/overview', label: '工程房间门口写着「等待机器：笔记本」；等待期间不计入运行时间上限' },
          { delay: 1200, go: '#/p/p-metro/w/w-metro-transfer/recovery', label: '恢复页写着等待机器、机器名与已经等待的时长，可以取消事项' },
          { delay: 1400, event: { type: 'x_machine_online', project_id: P, label: '笔记本重新上线', payload: { machine_id: 'm-laptop' } }, patch: [{ path: 'machines[id=m-laptop].online', value: true }] },
          { delay: 1400, event: { type: 'x_late_receipt', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '按尝试身份取得动作记录：已结束，回执写成迟到回执', payload: { machine_id: 'm-laptop' } }, patch: [{ path: 'machines[id=m-laptop].late_receipts', push: { at: '2026-09-29T15:32:00+08:00', action_id: 'a-metro-unit-17', text: '迟到回执：命令 python -m pytest tests 退出码 0，12 passed。不改写结果未知的记录；核实引用这份回执。' } }, { path: 'machines[id=m-laptop].actions[action_id=a-metro-unit-17].state', value: 'done' }] },
          { delay: 1400, event: { type: 'action_verified', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '核实确认：交回取得的回执，事项自动继续', payload: { action_id: 'a-metro-unit-17', handling: 'confirmed' } }, patch: [{ path: 'runs[id=r-metro-transfer].recovery.verifications', push: { action_id: 'a-metro-unit-17', handling: 'confirmed', session: '工程：换乘站去重与最短路径', at: '2026-09-29T15:32:00+08:00', basis: '笔记本恢复在线以后按尝试身份查询动作记录：已结束，取得回执', result: '退出码 0，12 passed；交回工程的会话', returned: null } }, { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'done' }, { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].after', value: '12 passed' }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' }, { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: null }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '笔记本恢复在线，测试命令已核实确认，自动继续' }] },
          { delay: 1000, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程拿到核实的结果，继续工作', payload: {} }, patch: [] }
        ]
      },
      {
        no: 12, id: 'sc-metro-queue', name: '同一项目排队与调整顺序', level: '3.4A', go: '#/p/p-metro/overview',
        setup: [
          { path: 'work_items[id=w-metro-card].status', value: 'not_started' },
          { path: 'work_items[id=w-metro-card].queue_reason', value: null },
          { path: 'work_items[id=w-metro-card].queue_pos', value: null },
          { path: 'work_items[id=w-metro-report].status', value: 'not_started' },
          { path: 'work_items[id=w-metro-report].queue_reason', value: null },
          { path: 'work_items[id=w-metro-report].queue_pos', value: null },
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
          { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: null },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '运行中' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'user_input_received', project_id: P, work_item_id: 'w-metro-card', run_id: 'r-metro-card', actor: 'user', label: '用户投入新要求：公交卡折扣', payload: { progress: 'received' } }, patch: [] },
          { delay: 1200, event: { type: 'x_queued', project_id: P, work_item_id: 'w-metro-card', run_id: 'r-metro-card', label: '公交卡折扣进入大厅队列，排在第 1 位', payload: {} }, patch: [{ path: 'work_items[id=w-metro-card].status', value: 'queued' }, { path: 'work_items[id=w-metro-card].queue_reason', value: 'project' }, { path: 'work_items[id=w-metro-card].queue_pos', value: 1 }] },
          { delay: 1200, event: { type: 'user_input_received', project_id: P, work_item_id: 'w-metro-report', run_id: 'r-metro-report', actor: 'user', label: '用户再投入：导出月度出行统计', payload: { progress: 'received' } }, patch: [] },
          { delay: 1200, event: { type: 'x_queued', project_id: P, work_item_id: 'w-metro-report', run_id: 'r-metro-report', label: '月度出行统计进入队列，排在第 2 位', payload: {} }, patch: [{ path: 'work_items[id=w-metro-report].status', value: 'queued' }, { path: 'work_items[id=w-metro-report].queue_reason', value: 'project' }, { path: 'work_items[id=w-metro-report].queue_pos', value: 2 }] },
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '当前事项仍在工程，两个包裹在大厅管道入口排队', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'x_queue_reordered', project_id: P, actor: 'user', label: '用户把月度出行统计调到公交卡折扣前面', payload: { order: ['w-metro-report', 'w-metro-card'] } }, patch: [{ path: 'work_items[id=w-metro-report].queue_pos', value: 1 }, { path: 'work_items[id=w-metro-card].queue_pos', value: 2 }] },
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'model_stream_progress', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '队列顺序已变为月度统计、公交卡折扣', payload: { text: '大厅包裹顺序已调整。' } }, patch: [] },
          { delay: 1400, event: { type: 'deliverable_adopted', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', actor: 'user', label: '当前事项换乘站被采纳，执行槽位空出', payload: { version: 'r2' } }, patch: [{ path: 'work_items[id=w-metro-transfer].status', value: 'adopted' }, { path: 'runs[id=r-metro-transfer].phase', value: 'DONE' }, { path: 'runs[id=r-metro-transfer].department', value: null }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'completed' }, { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: null }, { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'done' }, { path: 'projects[id=p-metro].adoptions', push: { version: 'r2', work_item_id: 'w-metro-transfer', summary: '三种路径与换乘站去重', adopted_at: '2026-09-29T15:36:00+08:00' } }] },
          { delay: 1400, event: { type: 'x_slot_acquired', project_id: P, work_item_id: 'w-metro-report', run_id: 'r-metro-report', department: 'product', label: '队首的月度出行统计取得执行槽位并开始', payload: {} }, patch: [{ path: 'work_items[id=w-metro-report].status', value: 'in_progress' }, { path: 'work_items[id=w-metro-report].queue_reason', value: null }, { path: 'work_items[id=w-metro-report].queue_pos', value: null }, { path: 'runs[id=r-metro-report].phase', value: 'PRODUCT_SPEC' }, { path: 'runs[id=r-metro-report].department', value: 'product' }, { path: 'runs[id=r-metro-report].cycle', value: 1 }, { path: 'runtime.slots.used', push: { work_item_id: 'w-metro-report', department: 'product', role: null } }] },
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-report', run_id: 'r-metro-report', department: 'product', label: '产品开始处理队首事项，公交卡折扣仍排在大厅', payload: {} }, patch: [] }
        ]
      },
      {
        // 暂停以后继续（D09）与继续旧事项时定义版本不同（总体架构第 7.4 节）：两种 3.1 的决定请求，阻塞范围都是 run
        no: 22, id: 'sc-metro-paused', name: '暂停以后继续与定义版本不同', level: '3.1', go: '#/p/p-metro/overview',
        setup: [
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
          { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: null },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '运行中' },
          { path: 'runs[id=r-metro-transfer].recovery.unfinished', value: [] },
          { path: 'runs[id=r-metro-transfer].recovery.verifications', value: [] },
          { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'model_attempt_finished', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门的模型回复只有文字，没有调用工具（连续第 4 次）', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'run_paused', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '模型连续 4 次回复没有调用工具，事项暂停', payload: { reason: 'no_tool_call' } }, patch: [{ path: 'runs[id=r-metro-transfer].phase', value: 'PAUSED' }, { path: 'runs[id=r-metro-transfer].stop_reason', value: { code: 'no_tool_call', text: '模型连续不调用工具' } }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'paused' }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '工程部门的模型连续 4 次回复没有调用工具，已暂停' }, { path: 'work_items[id=w-metro-transfer].status', value: 'queued' }, { path: 'work_items[id=w-metro-transfer].queue_reason', value: 'decision' }] },
          { delay: 1200, event: { type: 'x_decision_issued', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '发出决定请求：暂停以后继续', payload: { decision_id: 'd-metro-paused', kind: 'paused_continue' } }, patch: [{ path: 'decisions[id=d-metro-paused].status', value: 'waiting' }] },
          { delay: 1400, go: '#/home', label: '首页「待你决定」出现暂停以后继续的卡片：停止原因与人工处理说明，选项是处理以后继续执行、停止事项' },
          { delay: 1400, event: { type: 'x_decision_answered', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', actor: 'user', label: '用户选择「处理以后继续执行」', payload: { decision_id: 'd-metro-paused', kind: 'paused_continue', option: 'continue' } }, patch: [{ path: 'decisions[id=d-metro-paused].status', value: 'answered' }, { path: 'decisions[id=d-metro-paused].answer', value: { option: 'continue', label: '处理以后继续执行', note: '', at: '2026-09-29T15:30:00+08:00' } }, { path: 'runs[id=r-metro-transfer].phase', value: 'ENGINEERING' }, { path: 'runs[id=r-metro-transfer].stop_reason', value: null }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '从暂停的位置继续，连续不调用工具的计数从零开始' }, { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' }, { path: 'work_items[id=w-metro-transfer].queue_reason', value: null }] },
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程从暂停的位置继续，已用的次数与时间不重新计算', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'x_run_interrupted', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '控制主机重新启动，加载的定义版本变为 v15', payload: { reason: '控制主机重新启动' } }, patch: [{ path: 'runs[id=r-metro-transfer].recovery.state', value: 'interrupted' }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '控制主机重新启动' }] },
          { delay: 1400, event: { type: 'x_decision_issued', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '事项记录的定义版本 v14 与当前加载的 v15 不同，自动继续之前发出决定请求', payload: { decision_id: 'd-metro-defs', kind: 'definitions_changed' } }, patch: [{ path: 'decisions[id=d-metro-defs].status', value: 'waiting' }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'waiting_resume' }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '事项记录的定义版本是 v14，当前加载的是 v15：等你决定按新版本继续还是停止事项' }, { path: 'work_items[id=w-metro-transfer].status', value: 'queued' }, { path: 'work_items[id=w-metro-transfer].queue_reason', value: 'decision' }] },
          { delay: 1400, go: '#/p/p-metro/w/w-metro-transfer/recovery', label: '恢复页写着待恢复、两个定义版本与这张决定请求' },
          { delay: 1400, event: { type: 'x_decision_answered', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', actor: 'user', label: '用户选择「按新版本继续」', payload: { decision_id: 'd-metro-defs', kind: 'definitions_changed', option: 'continue_new' } }, patch: [{ path: 'decisions[id=d-metro-defs].status', value: 'answered' }, { path: 'decisions[id=d-metro-defs].answer', value: { option: 'continue_new', label: '按新版本继续', note: '', at: '2026-09-29T15:30:00+08:00' } }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' }, { path: 'runs[id=r-metro-transfer].recovery.auto_resumed_at', value: '2026-09-29T15:30:00+08:00' }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '按定义版本 v15 继续' }, { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' }, { path: 'work_items[id=w-metro-transfer].queue_reason', value: null }] },
          { delay: 1000, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程按新版本的定义继续工作', payload: {} }, patch: [] }
        ]
      },
      {
        // 等待超过时长上限（循环与收敛设计说明第 3 节）：等待机器的上限是 24 小时（规则登记第 8 节），
        // 超过时发出决定请求并通知一次；选择继续等待以后重新计时
        no: 23, id: 'sc-metro-wait-limit', name: '等待机器超过时长上限', level: '3.2C', go: '#/p/p-metro/overview',
        setup: [
          { path: 'machines[id=m-laptop].online', value: false },
          { path: 'machines[id=m-laptop].last_heartbeat_at', value: '2026-09-28T15:29:40+08:00' },
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'waiting_resume' },
          { path: 'runs[id=r-metro-transfer].recovery.waiting_machine', value: { machine_id: 'm-laptop', since: '2026-09-28T15:30:00+08:00', problem: '离线' } },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '笔记本离线：测试命令的结果要等它恢复在线以后按尝试身份核实' },
          { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', label: '换乘站的事项等待机器：笔记本，已经等了 24 小时' },
          { delay: 1400, event: { type: 'x_decision_issued', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '等待机器达到时长上限 24 小时，发出决定请求并通知一次', payload: { decision_id: 'd-metro-wait', kind: 'wait_limit' } }, patch: [{ path: 'decisions[id=d-metro-wait].status', value: 'waiting' }] },
          { delay: 1400, go: '#/home', label: '首页「待你决定」出现等待超过时长上限的卡片：等待的种类、机器、已经等待的时长与上限' },
          { delay: 1400, event: { type: 'x_decision_answered', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', actor: 'user', label: '用户选择「继续等待」，重新计时', payload: { decision_id: 'd-metro-wait', kind: 'wait_limit', option: 'keep_waiting' } }, patch: [{ path: 'decisions[id=d-metro-wait].status', value: 'answered' }, { path: 'decisions[id=d-metro-wait].answer', value: { option: 'keep_waiting', label: '继续等待', note: '', at: '2026-09-29T15:30:00+08:00' } }] },
          { delay: 1200, event: { type: 'x_wait_restarted', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', label: '继续等待笔记本，重新计时', payload: { wait: 'machine', machine_id: 'm-laptop' } }, patch: [{ path: 'runs[id=r-metro-transfer].recovery.waiting_machine.since', value: '2026-09-29T15:30:00+08:00' }, { path: 'runs[id=r-metro-transfer].recovery.reason', value: '继续等待笔记本恢复在线，从 15:30 起重新计时' }] },
          { delay: 1200, go: '#/p/p-metro/w/w-metro-transfer/recovery', label: '恢复页的已等待时长从零开始，24 小时以后再问一次' }
        ]
      },
      {
        // 原型 v13（画面与播放设计说明第 7.2 节）：几秒内到达几十条事件。工具调用与模型请求是进度，不排队；普通动作排队，
        // 画面落后接近上限时丢掉排在后面的；交接、询问这类关键动作全部演，来不及时缩短；状态跟在它之前的动作后面上画面，最多落后 5 秒
        no: 24, id: 'sc-metro-burst', name: '短时间内大量事件堆积', level: 'S5', go: '#/p/p-metro/overview',
        setup: BURST_SETUP,
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', label: '工程与质检同时在工作；下一步一下子到达三十多条事件。打开工具条的「节奏」看画面落后几秒' },
          { delay: 4000, go: '#/p/p-metro/overview', label: '第一批：工程连续调用工具、分派与审查，质检起草测试用例，中间夹着一次询问与回答和一次交付', burst: BURST_FIRST },
          { delay: 9000, go: '#/p/p-metro/overview', label: '第一批还没演完，第二批又到：质检检查交付、记下缺陷记录，工程修复以后再交付，质检放行', burst: BURST_SECOND },
          { delay: 1200, go: '#/p/p-metro/overview', label: '画面最多落后 5 秒：普通动作丢掉，关键动作缩短，同一个角色连续的同类动作合并；最后显示的是最新的状态' }
        ]
      },
      {
        // 原型 v13（画面与播放设计说明第 5.2 节「跳到最新」）：标签页在后台时浏览器暂停画面的动画，事件照样到达；
        // 切回来时画面清空时间线，直接显示最新的状态，不补播。错过的经过由离开报告交代
        no: 25, id: 'sc-metro-background', name: '标签页在后台放几分钟以后切回', level: 'S5', go: '#/p/p-metro/overview',
        setup: BURST_SETUP,
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', label: '画面在前台，工程在工作' },
          { delay: 1200, act: 'sim.hidden', data: { hidden: 'true' }, label: '标签页切到后台：浏览器暂停画面的动画，事件照样到达（原型工具条模拟）' }
        ].concat(AWAY_EVENTS.map((s) => Object.assign({ delay: 400 }, s))).concat([
          { delay: 1600, act: 'sim.hidden', data: { hidden: 'false' }, label: '过了几分钟切回前台：画面直接显示最新的状态，积下的动作不补播；错过的经过看离开期间的报告' }
        ])
      }
    ]
  });
})();
