// 北京地铁票价（评测场景 3，PRDBench 44）。种子是出现时的状态，历史补丁收到现在。
(function () {
  'use strict';
  const Y8 = window.Y8;
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

  function ev(fields) {
    return Object.assign({
      project_id: P, work_item_id: null, run_id: null, department: null, role: null,
      actor: 'system', payload: {}, patch: []
    }, fields);
  }

  const fareAsk = '12 公里整是否按 6 元？分段表里 12 公里是 4 元档的上界，还是已经进入 6 元档？';
  const fareAnswer = '12 公里整按 4 元。分段按左开右闭：6 公里及以内 3 元，超过 6 公里至 12 公里（含）4 元，超过 12 公里至 22 公里 5 元，超过 22 公里至 32 公里 6 元。12 公里整不进入 6 元档。Sum_money 的输入单位是米，12000 米对应 4 元。';

  Y8.data.define({
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
            { seq: 1, at: '2026-09-26T18:41:00+08:00', from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：分段票价与 12 公里整按 4 元', status: 'accepted', event_position: null },
            { seq: 2, at: '2026-09-28T10:51:00+08:00', from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r1：fare_calculator、cli、文本与 JSON 导出', status: 'accepted', event_position: null },
            { seq: 3, at: '2026-09-28T11:21:00+08:00', from: 'quality', to: 'library', kind: 'release', content: '放行：12000 米票价为 4 元', status: 'accepted', event_position: null }
          ],
          requests: [{
            id: 'q-fare-12km', from: 'engineering', to: 'product', kind: 'consult',
            question: fareAsk, status: 'open', answer: fareAnswer,
            born_at: '2026-09-26T19:05:00+08:00'
          }],
          guidance: [],
          messages: {
            product: [{ seq: 1, at: '2026-09-26T19:22:00+08:00', source: 'self', from: 'product', text: fareAnswer, event_id: null }],
            engineering: [{ seq: 1, at: '2026-09-26T19:05:00+08:00', source: 'self', from: 'engineering', text: fareAsk, event_id: null }],
            quality: [{ seq: 1, at: '2026-09-28T11:20:00+08:00', source: 'self', from: 'quality', text: '12000 米断言通过，放行。', event_id: null }],
            operations: []
          },
          actions: [{
            id: 'a-metro-fare-pytest', department: 'engineering', role: 'eng-lead', tool: 'run_command',
            summary: '登记命令 pytest：边界 12000 米', input: 'python -m pytest tests/test_fare.py',
            state: 'done', machine_id: 'm-host', at: '2026-09-28T10:40:00+08:00',
            before: '测试文件已写入 12000 米期望 4 元', after: '1 passed',
            receipt: { command: 'pytest', argv: ['python', '-m', 'pytest', 'tests/test_fare.py'], exit_code: 0, output: '1 passed', truncated: false, timed_out: false, duration_ms: 2400, snapshot: 'tests/test_fare.py' }
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
            last_confirmed: { seq: 17, text: '工程已写完换乘站去重与最短路径，登记命令 unit_tests 已开始、尚未收到退出码' },
            owner: { id: '工程部门', since: '2026-09-29T03:02:00+08:00' },
            late_results: [], verifications: [],
            unfinished: [{ id: 'a-metro-unit-17', label: '登记命令 unit_tests' }],
            limits: { elapsed_sec: 4980, limit_sec: 7200, activations: 6, model_steps: 11, retries: 1 },
            auto_resumed_at: null
          },
          born_at: '2026-09-28T13:00:00+08:00',
          inputs: [{
            version: 1, kind: 'user', progress: 'accepted', at: '2026-09-28T13:00:00+08:00', bytes: 640,
            text: '接着做换乘站与最短路径：三种路径模式、最大换乘数、线路偏好。换乘站在一条路径里只计一次。'
          }],
          flow: [
            { seq: 1, at: '2026-09-28T13:40:00+08:00', from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：三种路径、最大换乘数、线路偏好、换乘站只计一次', status: 'accepted', event_position: null }
          ],
          requests: [],
          guidance: [],
          messages: {
            product: [],
            engineering: [{ seq: 1, at: '2026-09-29T03:02:00+08:00', source: 'self', from: 'engineering', text: '开始执行登记命令 unit_tests。', event_id: null }],
            quality: [],
            operations: []
          },
          actions: [
            {
              id: 'a-metro-read-graph', department: 'engineering', role: 'eng-explorer', tool: 'read_file',
              summary: '阅读 subway_data.json 的换乘站', input: 'subway_data.json',
              state: 'done', machine_id: 'm-host', at: '2026-09-28T15:10:00+08:00',
              before: '文件未读', after: '换乘站按站名出现在多条线路',
              receipt: { command: 'read_file', argv: ['subway_data.json'], exit_code: 0, output: 'stations 328', truncated: false, timed_out: false, duration_ms: 180, snapshot: null }
            },
            {
              id: 'a-metro-unit-17', department: 'engineering', role: 'eng-lead', tool: 'run_command',
              summary: '登记命令 unit_tests', input: '契约声明可以重复。命令：python -m pytest tests',
              state: 'running', machine_id: null, at: '2026-09-29T03:02:00+08:00',
              before: '工作区 src/pathfinding.py 已写入换乘站去重，测试尚未开始', after: null,
              receipt: null
            }
          ],
          contexts: {
            product: [{ id: 'ctx-xfer-p1', at: '2026-09-28T13:06:00+08:00', title: '产品激活 1', attempt_id: 'att-xfer-p1', sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '已采纳', version: 'r1', included: true }] }],
            engineering: [{ id: 'ctx-xfer-e2', at: '2026-09-28T14:32:00+08:00', title: '工程激活 2', attempt_id: 'att-xfer-e1', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '计划', version: 'PLAN r1', included: true }] }],
            quality: []
          },
          prompts: {
            product: { config_version: 1, request_version: 1, text: '三种路径模式、最大换乘数、线路偏好写进 PRD。换乘站只计一次。' },
            engineering: { config_version: 1, request_version: 1, text: '按 PLAN 实现 pathfinding。自测使用登记命令 unit_tests。' },
            quality: { config_version: 1, request_version: 1, text: '本事项尚未交给质检。' }
          },
          compactions: [],
          effective_model: {
            product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            quality: modelOf('opencode-go-responses/mimo-v2.5', '部门默认', null)
          },
          roles: roles({ id: 'eng-lead', status: 'working', task: '登记命令 unit_tests 的结果尚未收回' }),
          ledger: ledger({
            engineering: {
              items: [
                { id: 'P-1', text: '换乘站在路径中只计一次', assignee: 'eng-lead', status: 'returned', result: 'pathfinding.py 已按站名去重' },
                { id: 'P-2', text: '跑通登记命令 unit_tests', assignee: 'eng-lead', status: 'working', result: null }
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
          flow: [], requests: [], guidance: [],
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
          flow: [], requests: [], guidance: [],
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
      decisions: [{
        id: 'd-metro-unknown', kind: 'unknown_action', project_id: P,
        work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer',
        status: 'waiting', issued_at: '2026-09-29T03:14:00+08:00', born_at: '2026-09-29T03:14:00+08:00',
        version: 1, level: '3.1',
        blocks: { scope: 'action', work_item_id: 'w-metro-transfer', action_id: 'a-metro-unit-17' },
        materials: {
          action_id: 'a-metro-unit-17', department: 'engineering', machine_id: 'm-laptop',
          input: '契约声明可以重复。命令：python -m pytest tests',
          before: '工作区 src/pathfinding.py 已写入换乘站去重，测试尚未开始',
          after: null,
          basis: '控制主机 03:12 断电。03:13 自动继续后，登记命令 unit_tests 没有退出码。',
          repeatable: true
        },
        view: '#/p/p-metro/w/w-metro-transfer/recovery',
        answer: null,
        options: [
          {
            id: 'retry', label: '重新执行', kind: 'primary',
            events: [{
              type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
              label: '用户选择重新执行，工程部门再次启动登记命令 unit_tests',
              payload: { tool: 'run_command', action_id: 'a-metro-unit-17' },
              patch: [
                { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
                { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'running' }
              ]
            }]
          },
          {
            id: 'accept', label: '按已完成继续', kind: null,
            events: [{
              type: 'tool_called', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
              label: '用户确认该动作按已完成继续',
              payload: { tool: 'run_command', exit_code: 0, timed_out: false },
              patch: [
                { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
                { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'done' }
              ]
            }]
          },
          {
            id: 'stop', label: '停止事项', kind: 'danger',
            events: [{
              type: 'run_failed', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
              label: '用户停止换乘站事项',
              payload: { reason: 'stopped_by_user' },
              patch: [
                { path: 'work_items[id=w-metro-transfer].status', value: 'stopped' },
                { path: 'runs[id=r-metro-transfer].phase', value: 'FAILED' },
                { path: 'runs[id=r-metro-transfer].stop_reason', value: { code: 'stopped_by_user', text: '用户在核实中停止事项' } },
                { path: 'runs[id=r-metro-transfer].recovery.state', value: 'terminated' }
              ]
            }]
          }
        ]
      }],
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
          id: 'm-metro-plan', project_id: P, work_item_id: 'w-metro-fare', kind: 'plan', version: 1,
          title: 'PLAN r1 分段票价', at: '2026-09-27T10:20:00+08:00',
          text: '1. fare_calculator.Sum_money：输入米，按 PRD 的分段表返回元；12000 米必须返回 4。\n2. calculate_estimated_time(米, 换乘数)。\n3. src/cli.py 连续查询，文本版面与 JSON 字段名按接口约定。\n4. data_loader 做完整性检查。\n5. 登记命令 pytest 覆盖 6000 米、12000 米、12001 米三个边界。'
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
          text: '完成计划 1 至 5。Sum_money(12000) 返回 4。文本导出含起点、终点、距离、票价、预计时间。JSON 字段为 origin、destination、distance_m、fare_yuan、estimated_min。pytest 3 passed。路径搜索留在换乘事项。'
        },
        {
          id: 'm-metro-qa', project_id: P, work_item_id: 'w-metro-fare', kind: 'qa', version: 1,
          title: '质检结论 r1', at: '2026-09-28T11:20:00+08:00', verdict: 'release',
          text: '放行。检查了分段边界：6000 米 3 元，12000 米 4 元，12001 米 5 元。命令行连续查询两次后退出码 0。JSON 字段名与接口约定一致。数据文件缺少终点站时完整性检查拒绝加载。三种路径模式不在本事项验收范围内。'
        },
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
          commands: [
            { name: 'pytest', argv: 'python -m pytest', args: ['tests'], timeout_sec: 120, output_limit: 200000, version: 1 },
            { name: 'fare_cli', argv: 'python src/cli.py', args: [], timeout_sec: 30, output_limit: 20000, version: 1 },
            { name: 'unit_tests', argv: 'python -m pytest tests', args: ['tests'], timeout_sec: 180, output_limit: 200000, version: 1 }
          ],
          tools: [
            { id: 'network', label: '网络取回', scope: '只读取回：docs.python.org、pypi.org', approval: '超出范围时逐次批准', level: '3.2B' }
          ],
          machines: [
            { machine_id: 'm-host', dirs: ['/work/p-metro'], operations: ['构建', '测试'], level: '3.2C' },
            { machine_id: 'm-laptop', dirs: ['/work/p-metro'], operations: ['测试'], level: '3.2C' }
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
        label: '主机接纳 PRD r1，12 公里整写明按 4 元',
        payload: { material_id: 'm-metro-prd' }
      }),
      ev({
        at: '2026-09-26T18:41:00+08:00', type: 'transition', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'product',
        label: '产品把 PRD 交给工程',
        payload: { from: 'product', to: 'engineering', artifact: 'prd' },
        patch: [
          { path: 'runs[id=r-metro-fare].department', value: 'engineering' },
          { path: 'runs[id=r-metro-fare].last_department', value: 'product' },
          { path: 'runs[id=r-metro-fare].phase', value: 'ENGINEERING' },
          { path: 'runtime.slots.used[work_item_id=w-metro-fare].department', value: 'engineering' },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-26T18:41:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-26T18:42:00+08:00', type: 'department_activated', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '工程部门开始按 PRD 实现票价',
        payload: {}
      }),
      ev({
        at: '2026-09-26T19:05:00+08:00', type: 'collaboration_requested', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '工程向产品询问：12 公里整是否按 6 元',
        payload: { from: 'engineering', to: 'product', request_id: 'q-fare-12km' },
        patch: [{ path: 'projects[id=p-metro].last_activity_at', value: '2026-09-26T19:05:00+08:00' }]
      }),
      ev({
        at: '2026-09-26T19:22:00+08:00', type: 'collaboration_responded', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'product',
        label: '产品回答：12 公里整按 4 元，不进入 6 元档',
        payload: { from: 'product', to: 'engineering', request_id: 'q-fare-12km' },
        patch: [
          { path: 'runs[id=r-metro-fare].requests[id=q-fare-12km].status', value: 'answered' },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-26T19:22:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-26T19:23:00+08:00', type: 'collaboration_closed', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '12 公里整的询问已关闭',
        payload: { from: 'engineering', to: 'product', request_id: 'q-fare-12km' }
      }),
      ev({
        at: '2026-09-27T10:20:00+08:00', type: 'plan_accepted', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '主机接纳 PLAN r1，边界测试先于实现',
        payload: { material_id: 'm-metro-plan' },
        patch: [{ path: 'projects[id=p-metro].last_activity_at', value: '2026-09-27T10:20:00+08:00' }]
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
        label: '登记命令 pytest 通过，12000 米为 4 元',
        payload: { tool: 'run_command', exit_code: 0, timed_out: false },
        patch: [{ path: 'runs[id=r-metro-fare].elapsed_sec', value: 5200 }]
      }),
      ev({
        at: '2026-09-28T10:50:00+08:00', type: 'delivery_accepted', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '主机接纳交付 r1',
        payload: { material_id: 'm-metro-delivery' }
      }),
      ev({
        at: '2026-09-28T10:51:00+08:00', type: 'transition', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'engineering',
        label: '工程把交付交给质检',
        payload: { from: 'engineering', to: 'quality', artifact: 'box' },
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
        payload: { verdict: 'release' },
        patch: [
          { path: 'work_items[id=w-metro-fare].status', value: 'released' },
          { path: 'runs[id=r-metro-fare].elapsed_sec', value: 5400 },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-28T11:20:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T11:21:00+08:00', type: 'transition', work_item_id: 'w-metro-fare', run_id: 'r-metro-fare', department: 'quality',
        label: '放行的交付送到成果库',
        payload: { from: 'quality', to: 'library', artifact: 'release' },
        patch: [
          { path: 'runs[id=r-metro-fare].department', value: null },
          { path: 'runs[id=r-metro-fare].last_department', value: 'quality' }
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
        at: '2026-09-28T13:40:00+08:00', type: 'transition', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'product',
        label: '产品把换乘规则交给工程',
        payload: { from: 'product', to: 'engineering', artifact: 'prd' },
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
        at: '2026-09-28T14:30:00+08:00', type: 'plan_accepted', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
        label: '主机接纳换乘路径的计划，进入第 2 轮实现',
        payload: { material_id: 'm-metro-note' },
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
        label: '工程部门开始执行登记命令 unit_tests',
        payload: { tool: 'run_command' },
        patch: [
          { path: 'runs[id=r-metro-transfer].elapsed_sec', value: 4980 },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-29T03:02:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-29T03:02:00+08:00', type: 'x_remote_action_started', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.2C',
        label: '登记命令 unit_tests 在笔记本上开始执行',
        payload: { machine_id: 'm-laptop', action_id: 'a-metro-unit-17', label: '登记命令 unit_tests' },
        patch: [
          { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].machine_id', value: 'm-laptop' },
          {
            path: 'machines[id=m-laptop].actions',
            push: { project_id: P, work_item_id: 'w-metro-transfer', department: 'engineering', action_id: 'a-metro-unit-17', label: '登记命令 unit_tests', state: 'running' }
          }
        ]
      }),
      ev({
        at: '2026-09-29T03:11:00+08:00', type: 'model_stream_progress', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
        label: '工程仍在等待 unit_tests 的退出码',
        payload: { text: 'unit_tests 仍在笔记本上运行，还没有退出码。' },
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
      ev({
        at: '2026-09-29T03:14:00+08:00', type: 'x_action_unknown', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.1',
        label: '登记命令 unit_tests 的结果未知，事项进入待核实',
        payload: { action_id: 'a-metro-unit-17' },
        patch: [
          { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'unknown' },
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'pending_verification' },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: '最后已确认的位置是换乘站去重已写入，unit_tests 已开始但没有退出码' },
          { path: 'projects[id=p-metro].last_activity_at', value: '2026-09-29T03:14:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-29T03:14:00+08:00', type: 'x_action_unknown', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.2C',
        label: '笔记本上的 unit_tests 标记为结果未知',
        payload: { action_id: 'a-metro-unit-17', machine_id: 'm-laptop' },
        patch: [{ path: 'machines[id=m-laptop].actions[action_id=a-metro-unit-17].state', value: 'unknown' }]
      }),
      ev({
        at: '2026-09-29T03:14:00+08:00', type: 'x_decision_issued', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', level: '3.1',
        label: '发出决定请求：核实结果未知的登记命令 unit_tests',
        payload: { decision_id: 'd-metro-unknown', kind: 'unknown_action' },
        patch: [{ path: 'decisions[id=d-metro-unknown].status', value: 'waiting' }]
      })
    ],
    scenarios: [
      {
        no: 3, id: 'sc-metro-ask', name: '询问与回答', level: 'ui', go: '#/p/p-metro/overview',
        setup: [],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门站在传信管前，准备询问产品', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'collaboration_requested', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程向产品询问：线路偏好是否改变最短距离', payload: { from: 'engineering', to: 'product', request_id: 'q-sc-prefer' } }, patch: [{ path: 'runs[id=r-metro-transfer].requests', push: { id: 'q-sc-prefer', from: 'engineering', to: 'product', kind: 'consult', question: '线路偏好是否改变最短距离模式的实际距离？', status: 'open', answer: null, born_at: '2026-09-29T15:31:00+08:00' } }] },
          { delay: 1400, event: { type: 'model_requested', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'product', label: '产品部门展开询问信', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'collaboration_responded', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'product', label: '产品回答：最短距离不乘 0.8，只影响综合最优', payload: { from: 'product', to: 'engineering', request_id: 'q-sc-prefer' } }, patch: [{ path: 'runs[id=r-metro-transfer].requests[id=q-sc-prefer].status', value: 'answered' }] },
          { delay: 1000, event: { type: 'collaboration_closed', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '线路偏好的询问已关闭，信件离开传信管', payload: { from: 'engineering', to: 'product', request_id: 'q-sc-prefer' } }, patch: [] },
          { delay: 1200, event: { type: 'transition', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程把当前实现交给质检看一眼边界', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, patch: [{ path: 'runs[id=r-metro-transfer].department', value: 'quality' }] },
          { delay: 1200, event: { type: 'collaboration_requested', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'quality', label: '质检向工程询问：西直门是否只计一次换乘', payload: { from: 'quality', to: 'engineering', request_id: 'q-sc-xzm' } }, patch: [{ path: 'runs[id=r-metro-transfer].requests', push: { id: 'q-sc-xzm', from: 'quality', to: 'engineering', kind: 'consult', question: '西直门同时在 2 号线与 4 号线，一条路径是否只计一次换乘？', status: 'open', answer: null, born_at: '2026-09-29T15:33:00+08:00' } }] },
          { delay: 1400, event: { type: 'collaboration_responded', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程回答：按站名合并，西直门只计一次', payload: { from: 'engineering', to: 'quality', request_id: 'q-sc-xzm' } }, patch: [{ path: 'runs[id=r-metro-transfer].requests[id=q-sc-xzm].status', value: 'answered' }] },
          { delay: 1200, event: { type: 'collaboration_requested', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'quality', label: '质检又问最大换乘数默认值，信件停在工程传信管出口', payload: { from: 'quality', to: 'engineering', request_id: 'q-sc-max' } }, patch: [{ path: 'runs[id=r-metro-transfer].requests', push: { id: 'q-sc-max', from: 'quality', to: 'engineering', kind: 'consult', question: '用户不填最大换乘数时，默认不限制，还是默认 3 次？', status: 'open', answer: null, born_at: '2026-09-29T15:34:00+08:00' } }] },
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程小人等在传信管出口，这封信还没有回答', payload: {} }, patch: [] }
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
          { delay: 1400, event: { type: 'compaction_failed', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '第二次整理没有生效，纸堆散落', payload: { reason: '摘要没有覆盖未完成的 unit_tests' } }, patch: [] },
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
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程正在跑登记命令，管道正常流动', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门在终端前执行 unit_tests', payload: { tool: 'run_command' } }, patch: [] },
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
        no: 8, id: 'sc-metro-unknown', name: '结果未知的动作与决定', level: '3.1', go: '#/p/p-metro/overview',
        setup: [
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
          { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'running' },
          { path: 'decisions[id=d-metro-unknown].status', value: 'withdrawn' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门执行登记命令 unit_tests', payload: { tool: 'run_command' } }, patch: [] },
          { delay: 1400, event: { type: 'x_action_unknown', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: 'unit_tests 没有退出码，未完成动作开始闪烁', payload: { action_id: 'a-metro-unit-17' } }, patch: [{ path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'unknown' }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'pending_verification' }] },
          { delay: 1200, event: { type: 'x_decision_issued', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '发出决定请求：核实结果未知的动作', payload: { decision_id: 'd-metro-unknown', kind: 'unknown_action' } }, patch: [{ path: 'decisions[id=d-metro-unknown].status', value: 'waiting' }] },
          { delay: 1400, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程房间亮黄灯，小人头顶出现问号', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'x_decision_answered', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', actor: 'user', label: '用户选择「重新执行」', payload: { decision_id: 'd-metro-unknown', kind: 'unknown_action', option: 'retry' } }, patch: [{ path: 'decisions[id=d-metro-unknown].status', value: 'answered' }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' }, { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'running' }] },
          { delay: 1200, event: { type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门按决定重新执行 unit_tests', payload: { tool: 'run_command', action_id: 'a-metro-unit-17' } }, patch: [] },
          { delay: 1400, event: { type: 'tool_called', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: 'unit_tests 重新执行完成，退出码 0', payload: { tool: 'run_command', exit_code: 0, timed_out: false } }, patch: [{ path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'done' }, { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].after', value: '12 passed' }] },
          { delay: 1200, event: { type: 'model_attempt_finished', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程部门读完回执，问号消失', payload: {} }, patch: [] },
          { delay: 1000, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程回到工位，准备提交交付', payload: {} }, patch: [] },
          { delay: 1000, event: { type: 'proposal_submitted', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程提交换乘路径的交付说明', payload: {} }, patch: [] }
        ]
      },
      {
        no: 10, id: 'sc-metro-offline', name: '执行代理离线导致结果未知', level: '3.2C', go: '#/p/p-metro/overview',
        setup: [
          { path: 'machines[id=m-laptop].online', value: true },
          { path: 'machines[id=m-laptop].actions', remove: { key: 'action_id', value: 'a-metro-unit-17' } },
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
          { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'running' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'x_remote_action_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '笔记本开始执行登记命令 unit_tests', payload: { machine_id: 'm-laptop', action_id: 'a-metro-unit-17', label: '登记命令 unit_tests' } }, patch: [{ path: 'machines[id=m-laptop].actions', push: { project_id: P, work_item_id: 'w-metro-transfer', department: 'engineering', action_id: 'a-metro-unit-17', label: '登记命令 unit_tests', state: 'running' } }] },
          { delay: 1200, event: { type: 'tool_started', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '通往机房的门上出现笔记本的动作', payload: { tool: 'run_command' } }, patch: [] },
          { delay: 1400, event: { type: 'x_machine_offline', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', label: '笔记本的执行代理心跳中断', payload: { machine_id: 'm-laptop' } }, patch: [{ path: 'machines[id=m-laptop].online', value: false }] },
          { delay: 1400, event: { type: 'x_action_unknown', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '笔记本离线，unit_tests 的结果未知', payload: { action_id: 'a-metro-unit-17', machine_id: 'm-laptop' } }, patch: [{ path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'unknown' }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'pending_verification' }, { path: 'machines[id=m-laptop].actions[action_id=a-metro-unit-17].state', value: 'unknown' }] },
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '通往机房的门上出现黄色问号', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'x_machine_online', project_id: P, label: '笔记本重新上线', payload: { machine_id: 'm-laptop' } }, patch: [{ path: 'machines[id=m-laptop].online', value: true }] },
          { delay: 1400, event: { type: 'x_late_receipt', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '笔记本送来迟到回执，只作为历史事实列出，不推进状态', payload: { machine_id: 'm-laptop' } }, patch: [{ path: 'machines[id=m-laptop].late_receipts', push: { at: '2026-09-29T15:36:00+08:00', action_id: 'a-metro-unit-17', text: '迟到回执：unit_tests 退出码 0。不改变恢复观察状态，也不把动作标成已完成。' } }] },
          { delay: 1200, event: { type: 'model_stream_progress', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '恢复观察状态仍是待核实，迟到回执没有改写它', payload: { text: '迟到回执已列入历史，动作状态仍是结果未知。' } }, patch: [] },
          { delay: 1000, go: '#/home', event: { type: 'x_decision_issued', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '结果未知仍等待用户核实', payload: { decision_id: 'd-metro-unknown', kind: 'unknown_action' } }, patch: [{ path: 'decisions[id=d-metro-unknown].status', value: 'waiting' }] },
          { delay: 1000, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '工程仍站在问号旁，等待用户决定', payload: {} }, patch: [] }
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
          { path: 'work_items[id=w-metro-report].queue_pos', value: null }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'user_input_received', project_id: P, work_item_id: 'w-metro-card', run_id: 'r-metro-card', actor: 'user', label: '用户投入新要求：公交卡折扣', payload: { progress: 'received' } }, patch: [] },
          { delay: 1200, event: { type: 'x_queued', project_id: P, work_item_id: 'w-metro-card', run_id: 'r-metro-card', label: '公交卡折扣进入大厅队列，排在第 1 位', payload: {} }, patch: [{ path: 'work_items[id=w-metro-card].status', value: 'queued' }, { path: 'work_items[id=w-metro-card].queue_reason', value: 'project' }, { path: 'work_items[id=w-metro-card].queue_pos', value: 1 }] },
          { delay: 1200, event: { type: 'user_input_received', project_id: P, work_item_id: 'w-metro-report', run_id: 'r-metro-report', actor: 'user', label: '用户再投入：导出月度出行统计', payload: { progress: 'received' } }, patch: [] },
          { delay: 1200, event: { type: 'x_queued', project_id: P, work_item_id: 'w-metro-report', run_id: 'r-metro-report', label: '月度出行统计进入队列，排在第 2 位', payload: {} }, patch: [{ path: 'work_items[id=w-metro-report].status', value: 'queued' }, { path: 'work_items[id=w-metro-report].queue_reason', value: 'project' }, { path: 'work_items[id=w-metro-report].queue_pos', value: 2 }] },
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '当前事项仍在工程，两个包裹在大厅管道入口排队', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'x_queue_reordered', project_id: P, actor: 'user', label: '用户把月度出行统计调到公交卡折扣前面', payload: { order: ['w-metro-report', 'w-metro-card'] } }, patch: [{ path: 'work_items[id=w-metro-report].queue_pos', value: 1 }, { path: 'work_items[id=w-metro-card].queue_pos', value: 2 }] },
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'model_stream_progress', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering', label: '队列顺序已变为月度统计、公交卡折扣', payload: { text: '大厅包裹顺序已调整。' } }, patch: [] },
          { delay: 1400, event: { type: 'deliverable_adopted', project_id: P, work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', actor: 'user', label: '当前事项换乘站被采纳，执行槽位空出', payload: { version: 'r2' } }, patch: [{ path: 'work_items[id=w-metro-transfer].status', value: 'adopted' }, { path: 'runs[id=r-metro-transfer].phase', value: 'DONE' }, { path: 'runs[id=r-metro-transfer].department', value: null }, { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' }, { path: 'runs[id=r-metro-transfer].actions[id=a-metro-unit-17].state', value: 'done' }, { path: 'projects[id=p-metro].adoptions', push: { version: 'r2', work_item_id: 'w-metro-transfer', summary: '三种路径与换乘站去重', adopted_at: '2026-09-29T15:36:00+08:00' } }] },
          { delay: 1400, event: { type: 'x_slot_acquired', project_id: P, work_item_id: 'w-metro-report', run_id: 'r-metro-report', department: 'product', label: '队首的月度出行统计取得执行槽位并开始', payload: {} }, patch: [{ path: 'work_items[id=w-metro-report].status', value: 'in_progress' }, { path: 'work_items[id=w-metro-report].queue_reason', value: null }, { path: 'work_items[id=w-metro-report].queue_pos', value: null }, { path: 'runs[id=r-metro-report].phase', value: 'PRODUCT_SPEC' }, { path: 'runs[id=r-metro-report].department', value: 'product' }, { path: 'runs[id=r-metro-report].cycle', value: 1 }, { path: 'runtime.slots.used', push: { work_item_id: 'w-metro-report', department: 'product', role: null } }] },
          { delay: 1200, go: '#/p/p-metro/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-metro-report', run_id: 'r-metro-report', department: 'product', label: '产品开始处理队首事项，公交卡折扣仍排在大厅', payload: {} }, patch: [] }
        ]
      }
    ]
  });
})();
