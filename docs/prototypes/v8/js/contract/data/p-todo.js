// 待办清单网页（评测场景 1，WebGen-Bench 000080）：项目、两个事项与它们的 run、资料、设置、决定、离开期间的事件与场景
(function () {
  'use strict';
  const Y8 = window.Y8;

  const PRODUCT_PROMPT = '你是产品部门。依据用户原文维护 PRD：写清目标、边界、验收条件与非目标，每条要求至少有一条验收条件；用户的新输入逐版本处理，写明新增、修改或保留了哪些要求。回答其他部门的需求咨询时，只依据有效要求与用户原文；需要取舍时写明理由。';
  const ENGINEERING_PROMPT = '你是工程部门。依据有效 PRD 先写工程计划，计划项逐条对应要求；再按计划实现代码、编写单元测试，并用登记命令自测。交付说明逐条写明完成的计划项与处理的缺陷；实现有疑问时向产品咨询，不自行改变要求。';
  const QUALITY_PROMPT = '你是质检部门。依据有效 PRD 在独立副本中验证交付：逐条对照验收条件记录检查结果、证据与主机回执。发现问题时写明复现步骤与违反的验收条件，给出返工结论；全部验收条件都有通过的检查时给出放行结论。';

  const INTEND_TEXT = 'Please implement an advanced to-do list web application where users can create, edit, and delete to-do items. The application should have functionalities for adding new tasks, marking tasks as completed, deleting tasks, filtering tasks, and searching tasks. Users should be able to browse all to-do items, create new tasks, edit existing tasks, and delete unnecessary tasks. Set all pages to have a lavender background and indigo components.';

  Y8.data.define({
    seed: {
      projects: [
        {
          id: 'p-todo', name: '待办清单网页',
          goal: '待办清单网页：新增、编辑、删除与标记完成任务，按完成状态筛选与搜索；任务可以设置截止日期，超过截止日期未完成时显示逾期提醒。',
          pinned: true, archived: false, source: 'idea', version: 1,
          created_at: '2026-09-26T20:30:00+08:00', last_activity_at: '2026-09-26T20:30:00+08:00',
          adoptions: [],
          born_at: '2026-09-26T20:30:00+08:00'
        }
      ],
      work_items: [
        {
          id: 'w-todo-base', project_id: 'p-todo', title: '建立待办清单页面', color_index: 0, kind: 'change',
          status: 'not_started', queue_reason: null, run_id: 'r-todo-base', queue_pos: null, version: 1,
          created_at: '2026-09-27T08:00:00+08:00', born_at: '2026-09-27T08:00:00+08:00'
        },
        {
          id: 'w-todo-due', project_id: 'p-todo', title: '增加截止日期与逾期提醒', color_index: 3, kind: 'change',
          status: 'not_started', queue_reason: null, run_id: 'r-todo-due', queue_pos: null, version: 1,
          created_at: '2026-09-28T10:00:00+08:00', born_at: '2026-09-28T10:00:00+08:00'
        }
      ],
      runs: [
        {
          id: 'r-todo-base', work_item_id: 'w-todo-base', project_id: 'p-todo', yudao_version: '0.8.0',
          phase: 'PRODUCT_SPEC', department: 'product', last_department: null, cycle: 1,
          started_at: '2026-09-27T08:00:00+08:00', elapsed_sec: 0, limit_sec: 86400,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: {
            state: 'running', reason: null, unusable: null,
            last_confirmed: { seq: 0, text: '事项已登记，等待产品开始' },
            owner: { id: '产品部门', since: '2026-09-27T08:00:00+08:00' },
            late_results: [], verifications: [], unfinished: [],
            limits: { activations: 3, model_steps: 22, retries: 0 }, auto_resumed_at: null
          },
          inputs: [
            {
              version: 1, kind: 'user', text: INTEND_TEXT, at: '2026-09-27T08:00:00+08:00',
              progress: 'accepted', bytes: [0, 441]
            }
          ],
          flow: [
            { seq: 1, at: '2026-09-27T08:00:00+08:00', from: 'user', to: 'product', kind: 'handoff', content: '用户输入 v1：待办清单网页的完整需求', status: '已接收', event_position: null },
            { seq: 2, at: '2026-09-27T09:10:00+08:00', from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：待办清单页面与 8 条验收条件', status: '已接收', event_position: null },
            { seq: 3, at: '2026-09-27T10:42:00+08:00', from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r1：index.html、app.js、styles.css 与 12 条测试', status: '已验收', event_position: null },
            { seq: 4, at: '2026-09-27T11:52:00+08:00', from: 'quality', to: 'engineering', kind: 'rework', content: '返工：筛选按钮不生效，点击「已完成」列表不变化（D-1，违反 AC-5）', status: '已处理', event_position: null },
            { seq: 5, at: '2026-09-27T16:42:00+08:00', from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r2：修复 D-1，筛选按完成状态过滤', status: '已验收', event_position: null },
            { seq: 6, at: '2026-09-27T18:36:00+08:00', from: 'quality', to: 'library', kind: 'release', content: '放行：8 条验收条件全部通过', status: '已放行', event_position: null },
            { seq: 7, at: '2026-09-27T18:40:00+08:00', from: 'library', to: 'adoption', kind: 'adopt', content: '项目采纳 r1', status: '已采纳', event_position: null }
          ],
          requests: [],
          guidance: [],
          messages: {
            product: [
              { seq: 1, at: '2026-09-27T08:00:00+08:00', source: 'user', from: 'user', text: '用户输入 v1：待办清单网页（新增、编辑、删除、完成、筛选、搜索；淡紫色背景、靛蓝色组件）', event_position: null },
              { seq: 2, at: '2026-09-27T09:10:00+08:00', source: 'self', from: 'product', text: 'PRD r1 已提交：8 条验收条件', event_position: null }
            ],
            engineering: [
              { seq: 3, at: '2026-09-27T09:12:00+08:00', source: 'other', from: 'product', text: 'PRD r1 交接', event_position: null },
              { seq: 4, at: '2026-09-27T09:20:00+08:00', source: 'self', from: 'engineering', text: 'PLAN r1：新建页面文件与 12 条测试', event_position: null },
              { seq: 5, at: '2026-09-27T10:40:00+08:00', source: 'self', from: 'engineering', text: '交付 r1 已提交：待办清单页面', event_position: null },
              { seq: 6, at: '2026-09-27T11:52:00+08:00', source: 'other', from: 'quality', text: '返工：筛选按钮不生效（D-1）', event_position: null },
              { seq: 7, at: '2026-09-27T16:40:00+08:00', source: 'self', from: 'engineering', text: '交付 r2 已提交：修复 D-1', event_position: null }
            ],
            quality: [
              { seq: 8, at: '2026-09-27T10:42:00+08:00', source: 'other', from: 'engineering', text: '交付 r1 交接', event_position: null },
              { seq: 9, at: '2026-09-27T11:50:00+08:00', source: 'self', from: 'quality', text: 'QA：返工工程（D-1：筛选按钮不生效）', event_position: null },
              { seq: 10, at: '2026-09-27T18:36:00+08:00', source: 'self', from: 'quality', text: 'QA：放行，8 条验收条件全部通过', event_position: null }
            ],
            operations: []
          },
          actions: [
            {
              id: 'a-todo-base-1', department: 'engineering', role: null, tool: 'write_file',
              summary: '新建 index.html：列表、表单与筛选按钮', input: 'PLAN r1 第 1 项', state: 'done', receipt: null,
              before: '工作区 000000（空）', after: '工作区 3f1c20', machine_id: 'm-host', at: '2026-09-27T09:40:00+08:00'
            },
            {
              id: 'a-todo-base-2', department: 'engineering', role: null, tool: 'run_command',
              summary: '执行登记命令 npm_test', input: 'PLAN r1 第 3 项：自测', state: 'done',
              receipt: { command: 'npm_test', argv: ['npm', 'test'], exit_code: 0, output: '12 passing (0.4s)', truncated: false, timed_out: false, duration_ms: 1620, snapshot: 'ws-3f1c20' },
              before: '工作区 3f1c20', after: '工作区 3f1c20（未改动）', machine_id: 'm-host', at: '2026-09-27T10:20:00+08:00'
            },
            {
              id: 'a-todo-trial-1', department: 'quality', role: null, tool: 'browser',
              summary: '试用待办清单页面（第 1 轮，m-study）', input: '交付 r1 与 PRD r1', state: 'done', receipt: null,
              before: '试用副本 3f1c20', after: '试用副本 3f1c20（未改动）', machine_id: 'm-study', at: '2026-09-27T11:00:00+08:00'
            },
            {
              id: 'a-todo-base-3', department: 'engineering', role: null, tool: 'edit_range',
              summary: '按区间编辑 app.js：筛选按完成状态过滤', input: '质检结论 r1 的 D-1', state: 'done', receipt: null,
              before: 'app.js @ 3f1c20', after: 'app.js @ a1c3f20', machine_id: 'm-host', at: '2026-09-27T14:10:00+08:00'
            },
            {
              id: 'a-todo-base-4', department: 'engineering', role: null, tool: 'run_command',
              summary: '执行登记命令 npm_test（回归与新增用例）', input: 'PLAN 的 D-1 修复项', state: 'done',
              receipt: { command: 'npm_test', argv: ['npm', 'test'], exit_code: 0, output: '13 passing (0.4s)', truncated: false, timed_out: false, duration_ms: 1740, snapshot: 'ws-a1c3f20' },
              before: '工作区 a1c3f20', after: '工作区 a1c3f20（未改动）', machine_id: 'm-host', at: '2026-09-27T16:30:00+08:00'
            },
            {
              id: 'a-todo-trial-2', department: 'quality', role: null, tool: 'browser',
              summary: '试用待办清单页面（第 2 轮重测，m-study）', input: '交付 r2 与 PRD r1', state: 'done', receipt: null,
              before: '试用副本 a1c3f20', after: '试用副本 a1c3f20（未改动）', machine_id: 'm-study', at: '2026-09-27T17:00:00+08:00'
            }
          ],
          trials: [
            {
              step: 1, at: '2026-09-27T11:02:00+08:00', action: '打开页面，确认列表、导航与配色',
              screenshot: 'todo-trial-1.png',
              text_lines: ['标题：待办清单', '导航：全部待办、关于', '列表：预约体检；整理房间'],
              requirement: '页面导航与配色'
            },
            {
              step: 2, at: '2026-09-27T11:10:00+08:00', action: '新增任务「预约体检」，确认出现在列表中',
              screenshot: 'todo-trial-2.png',
              text_lines: ['输入框：预约体检', '按钮：新增', '列表出现：预约体检'],
              requirement: '新建任务'
            },
            {
              step: 3, at: '2026-09-27T11:18:00+08:00', action: '点击「已完成」筛选，列表没有变化',
              screenshot: 'todo-trial-3.png',
              text_lines: ['筛选按钮：已完成（已按下）', '列表仍然显示：预约体检、整理房间'],
              requirement: '按完成状态筛选'
            }
          ],
          contexts: {
            product: [
              {
                id: 'ctx-todo-base-p1', at: '2026-09-27T08:01:00+08:00', title: '产品激活 1', attempt_id: 'att-todo-base-01',
                sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '部门规则', version: '默认 v0', included: true }, { label: '工具定义', version: '5 个工具', included: true }]
              }
            ],
            engineering: [
              {
                id: 'ctx-todo-base-e1', at: '2026-09-27T09:13:00+08:00', title: '工程激活 1', attempt_id: 'att-todo-base-02',
                sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '项目上下文', version: '尚未采纳', included: true }, { label: '工具定义', version: '7 个工具', included: true }]
              },
              {
                id: 'ctx-todo-base-e2', at: '2026-09-27T14:22:00+08:00', title: '工程激活 2（返工）', attempt_id: 'att-todo-base-05',
                sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '质检结论', version: '质检结论 r1', included: true }]
              }
            ],
            quality: [
              {
                id: 'ctx-todo-base-q1', at: '2026-09-27T10:44:00+08:00', title: '质检激活 1', attempt_id: 'att-todo-base-04',
                sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '前次交付', version: '交付 r1', included: true }, { label: '浏览器工具', version: '5 个工具', included: true }]
              },
              {
                id: 'ctx-todo-base-q2', at: '2026-09-27T17:02:00+08:00', title: '质检激活 2（重测)', attempt_id: 'att-todo-base-06',
                sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '前次交付', version: '交付 r2', included: true }]
              }
            ]
          },
          prompts: {
            product: { config_version: 0, request_version: 0, text: PRODUCT_PROMPT },
            engineering: { config_version: 0, request_version: 0, text: ENGINEERING_PROMPT },
            quality: { config_version: 0, request_version: 0, text: QUALITY_PROMPT }
          },
          compactions: [],
          effective_model: {
            product: { definition: 'opencode-go-responses/kimi-k2.6', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: null, sent_level: 'medium', unusable: null },
            engineering: { definition: 'opencode-go-responses/kimi-k2.6', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: 'high', sent_level: 'high', unusable: null },
            quality: { definition: 'opencode-go-responses/mimo-v2.5', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: null, sent_level: 'medium', unusable: null }
          },
          roles: {
            level: 'S5',
            product: [
              { id: 'prod-manager', name: '产品部门经理', kind: 'manager', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'prod-architect', name: '产品架构师', kind: 'architect', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'prod-explorer', name: '产品探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'prod-reviewer', name: '产品审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null }
            ],
            engineering: [
              { id: 'eng-manager', name: '工程经理', kind: 'manager', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'eng-architect', name: '工程架构师', kind: 'architect', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'eng-lead', name: '主程', kind: 'lead', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'eng-explorer', name: '工程探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'eng-reviewer', name: '工程审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null }
            ],
            quality: [
              { id: 'qa-manager', name: '质检经理', kind: 'manager', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null },
              { id: 'qa-tester', name: '测试工程师', kind: 'tester', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null },
              { id: 'qa-explorer', name: '质检探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null },
              { id: 'qa-reviewer', name: '质检审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null }
            ]
          },
          ledger: {
            level: 'S5',
            engineering: { items: [], facts: [], questions: [], progress: [] },
            quality: { items: [], facts: [], questions: [], progress: [] }
          },
          attempts: [
            {
              id: 'att-todo-base-01', logical_call_id: 'call-todo-base-p1', department: 'product', role: 'prod-architect', kind: 'work', n: 1, of: 3, status: 'succeeded',
              started_at: '2026-09-27T08:02:00+08:00', duration_ms: 24800, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 6120, output: 1480, cache_read: 0, total: 7600, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: null, sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-base-02', logical_call_id: 'call-todo-base-e1', department: 'engineering', role: 'eng-architect', kind: 'work', n: 1, of: 3, status: 'succeeded',
              started_at: '2026-09-27T09:14:00+08:00', duration_ms: 31200, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 9840, output: 2160, cache_read: 0, total: 12000, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: 'high', sent_level: 'high', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-base-03', logical_call_id: 'call-todo-base-e2', department: 'engineering', role: 'eng-lead', kind: 'work', n: 2, of: 3, status: 'succeeded',
              started_at: '2026-09-27T09:30:00+08:00', duration_ms: 74200, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 18240, output: 4310, cache_read: 8192, total: 22550, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: 'high', sent_level: 'high', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-base-04', logical_call_id: 'call-todo-base-q1', department: 'quality', role: 'qa-tester', kind: 'work', n: 1, of: 3, status: 'succeeded',
              started_at: '2026-09-27T10:44:00+08:00', duration_ms: 28600, provider: 'opencode-go-responses',
              requested_model: 'mimo-v2.5', actual_model: 'mimo-v2.5',
              usage: { input: 11240, output: 1520, cache_read: 0, total: 12760, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'mimo-v2.5', window: 1048576, max_output: 65536, source: '部门默认', request_level: null, sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-base-05', logical_call_id: 'call-todo-base-e3', department: 'engineering', role: 'eng-lead', kind: 'work', n: 3, of: 3, status: 'succeeded',
              started_at: '2026-09-27T14:24:00+08:00', duration_ms: 46800, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 16380, output: 2480, cache_read: 6144, total: 18860, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: 'high', sent_level: 'high', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-base-06', logical_call_id: 'call-todo-base-q2', department: 'quality', role: 'qa-tester', kind: 'work', n: 2, of: 3, status: 'succeeded',
              started_at: '2026-09-27T17:03:00+08:00', duration_ms: 30100, provider: 'opencode-go-responses',
              requested_model: 'mimo-v2.5', actual_model: 'mimo-v2.5',
              usage: { input: 12860, output: 1980, cache_read: 4096, total: 14840, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'mimo-v2.5', window: 1048576, max_output: 65536, source: '部门默认', request_level: null, sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            }
          ],
          source: null
        },
        {
          id: 'r-todo-due', work_item_id: 'w-todo-due', project_id: 'p-todo', yudao_version: '0.8.0',
          phase: 'PRODUCT_SPEC', department: 'product', last_department: null, cycle: 1,
          started_at: '2026-09-28T10:00:00+08:00', elapsed_sec: 0, limit_sec: 172800,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: {
            state: 'running', reason: null, unusable: null,
            last_confirmed: { seq: 0, text: '事项已登记，等待产品开始' },
            owner: { id: '产品部门', since: '2026-09-28T10:00:00+08:00' },
            late_results: [], verifications: [], unfinished: [],
            limits: { activations: 8, model_steps: 64, retries: 1 }, auto_resumed_at: null
          },
          inputs: [
            {
              version: 1, kind: 'user', text: '给待办清单增加截止日期与逾期提醒：任务可以设置截止日期，列表显示截止日期，超过截止日期但没有完成的任务显示逾期提醒。',
              at: '2026-09-28T09:58:00+08:00', progress: 'accepted', bytes: [0, 92]
            }
          ],
          flow: [
            { seq: 8, at: '2026-09-28T09:58:00+08:00', from: 'user', to: 'product', kind: 'handoff', content: '用户输入 v1：截止日期与逾期提醒', status: '已接收', event_position: null },
            { seq: 9, at: '2026-09-28T10:40:00+08:00', from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：截止日期显示与逾期提醒（AC-1 至 AC-5）', status: '已接收', event_position: null },
            { seq: 10, at: '2026-09-28T11:02:00+08:00', from: 'engineering', to: 'product', kind: 'ask', content: '咨询：逾期是否按本地时区判定？', status: '已回答', event_position: null },
            { seq: 11, at: '2026-09-28T11:20:00+08:00', from: 'product', to: 'engineering', kind: 'answer', content: '回答：按本地时区（Asia/Shanghai）判定，跨午夜后按本地日历日期比较', status: '已接收', event_position: null },
            { seq: 12, at: '2026-09-29T14:05:00+08:00', from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r1：截止日期与逾期提醒', status: '已验收', event_position: null }
          ],
          requests: [
            {
              id: 'q-todo-due-tz', from: 'engineering', to: 'product', kind: 'ask',
              question: '逾期是否按本地时区判定？', status: 'open', answer: null,
              born_at: '2026-09-28T11:02:00+08:00'
            }
          ],
          guidance: [],
          messages: {
            product: [
              { seq: 11, at: '2026-09-28T09:58:00+08:00', source: 'user', from: 'user', text: '用户输入 v1：截止日期与逾期提醒', event_position: null },
              { seq: 12, at: '2026-09-28T10:38:00+08:00', source: 'self', from: 'product', text: 'PRD r1 已提交：5 条验收条件', event_position: null },
              { seq: 13, at: '2026-09-28T11:02:00+08:00', source: 'other', from: 'engineering', text: '咨询：逾期是否按本地时区判定？', event_position: null },
              { seq: 14, at: '2026-09-28T11:20:00+08:00', source: 'self', from: 'product', text: '回答：按本地时区（Asia/Shanghai）判定，跨午夜后按本地日历日期比较', event_position: null }
            ],
            engineering: [
              { seq: 15, at: '2026-09-28T10:40:00+08:00', source: 'other', from: 'product', text: 'PRD r1 交接', event_position: null },
              { seq: 16, at: '2026-09-28T10:55:00+08:00', source: 'self', from: 'engineering', text: 'PLAN r1：截止日期显示、逾期判定与回归用例', event_position: null },
              { seq: 17, at: '2026-09-28T11:20:00+08:00', source: 'other', from: 'product', text: '回答：跨午夜后按本地日历日期比较', event_position: null },
              { seq: 18, at: '2026-09-29T14:00:00+08:00', source: 'self', from: 'engineering', text: '交付 r1 已提交：截止日期与逾期提醒', event_position: null }
            ],
            quality: [
              { seq: 19, at: '2026-09-29T14:05:00+08:00', source: 'other', from: 'engineering', text: '交付 r1 交接', event_position: null },
              { seq: 20, at: '2026-09-29T14:10:00+08:00', source: 'self', from: 'quality', text: '开始试用：逐步检查截止日期与逾期提醒', event_position: null },
              { seq: 21, at: '2026-09-29T14:20:00+08:00', source: 'self', from: 'quality', text: '申请取回 MDN 的日期输入控件说明，等待一次批准', event_position: null }
            ],
            operations: []
          },
          actions: [
            {
              id: 'a-todo-due-1', department: 'engineering', role: null, tool: 'read_range',
              summary: '阅读列表渲染与日期显示的代码', input: 'PLAN r1 第 1 项', state: 'done', receipt: null,
              before: 'app.js @ a1c3f20', after: 'app.js @ a1c3f20（未改动）', machine_id: 'm-host', at: '2026-09-28T11:05:00+08:00'
            },
            {
              id: 'a-todo-due-2', department: 'engineering', role: null, tool: 'edit_range',
              summary: '按区间编辑 app.js：增加截止日期输入与逾期标记', input: 'PLAN r1 第 1、2 项', state: 'done', receipt: null,
              before: 'app.js @ a1c3f20', after: 'app.js @ b7e91d4（第 1 次交回）', machine_id: 'm-host', at: '2026-09-28T11:40:00+08:00'
            },
            {
              id: 'a-todo-due-3', department: 'engineering', role: null, tool: 'edit_range',
              summary: '按区间编辑 app.js：逾期判定改为按本地日历日期比较', input: '审查意见（第 3 次退回）', state: 'done', receipt: null,
              before: 'app.js @ b7e91d4（第 3 次交回前）', after: 'app.js @ b7e91d4', machine_id: 'm-host', at: '2026-09-29T12:10:00+08:00'
            },
            {
              id: 'a-todo-due-4', department: 'engineering', role: null, tool: 'run_command',
              summary: '执行登记命令 npm_test', input: 'PLAN r1 第 3 项：自测与回归', state: 'done',
              receipt: { command: 'npm_test', argv: ['npm', 'test'], exit_code: 0, output: '16 passing (0.5s)', truncated: false, timed_out: false, duration_ms: 1810, snapshot: 'ws-b7e91d4' },
              before: '工作区 b7e91d4', after: '工作区 b7e91d4（未改动）', machine_id: 'm-host', at: '2026-09-29T12:22:00+08:00'
            },
            {
              id: 'a-todo-mdn-1', department: 'quality', role: null, tool: 'network_fetch',
              summary: '取回 MDN 的日期输入控件说明（等待一次性批准）', input: '试用第 5 步的准备', state: 'not_sent', receipt: null,
              before: null, after: null, machine_id: null, at: '2026-09-29T14:18:00+08:00'
            },
            {
              id: 'a-todo-trial-3', department: 'quality', role: null, tool: 'browser',
              summary: '试用待办清单页面（截止日期与逾期提醒，m-study）', input: '交付 r1 与 PRD r1', state: 'running', receipt: null,
              before: '试用副本 b7e91d4', after: null, machine_id: 'm-study', at: '2026-09-29T14:10:00+08:00'
            }
          ],
          trials: [
            {
              step: 1, at: '2026-09-29T14:11:00+08:00', action: '打开页面，确认列表与截止日期的显示',
              screenshot: 'todo-trial-1.png',
              text_lines: ['标题：待办清单', '导航：全部待办、关于', '列表：续费域名（截止 2026-09-30）；预约体检'],
              requirement: '列表与截止日期显示'
            },
            {
              step: 2, at: '2026-09-29T14:16:00+08:00', action: '新增任务「续费域名」，填写截止日期 09-30',
              screenshot: 'todo-trial-2.png',
              text_lines: ['标题输入框：续费域名', '截止日期：2026-09-30', '列表出现：续费域名（截止 2026-09-30）'],
              requirement: '新建任务与截止日期'
            }
          ],
          contexts: {
            product: [
              {
                id: 'ctx-todo-due-p1', at: '2026-09-28T09:59:00+08:00', title: '产品激活 1', attempt_id: 'att-todo-due-01',
                sources: [{ label: '用户原文', version: 'v2', included: true }, { label: '项目上下文', version: '采纳 r1', included: true }, { label: '部门规则', version: '默认 v0', included: true }]
              }
            ],
            engineering: [
              {
                id: 'ctx-todo-due-e1', at: '2026-09-28T10:41:00+08:00', title: '工程激活 1', attempt_id: 'att-todo-due-03',
                sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '项目上下文', version: '采纳 r1', included: true }, { label: '部门规则', version: '默认 v0', included: true }]
              },
              {
                id: 'ctx-todo-due-e2', at: '2026-09-28T14:24:00+08:00', title: '工程激活 2（审查退回 1）', attempt_id: 'att-todo-due-05',
                sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '审查意见', version: '第 1 次退回', included: true }, { label: '部门账本', version: 'P-1', included: true }]
              },
              {
                id: 'ctx-todo-due-e3', at: '2026-09-29T12:05:00+08:00', title: '工程激活 3（审查退回 3）', attempt_id: 'att-todo-due-08',
                sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '审查意见', version: '第 3 次退回', included: true }, { label: '用户指导', version: '无', included: false }]
              }
            ],
            quality: [
              {
                id: 'ctx-todo-due-q1', at: '2026-09-29T14:06:00+08:00', title: '质检激活 1', attempt_id: 'att-todo-due-09',
                sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '前次交付', version: '交付 r1', included: true }, { label: '浏览器工具', version: '5 个工具', included: true }]
              }
            ]
          },
          prompts: {
            product: { config_version: 0, request_version: 0, text: PRODUCT_PROMPT },
            engineering: { config_version: 0, request_version: 0, text: ENGINEERING_PROMPT },
            quality: { config_version: 0, request_version: 0, text: QUALITY_PROMPT }
          },
          compactions: [],
          effective_model: {
            product: { definition: 'opencode-go-responses/kimi-k2.6', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: null, sent_level: 'medium', unusable: null },
            engineering: { definition: 'opencode-go-responses/kimi-k2.6', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: 'high', sent_level: 'high', unusable: null },
            quality: { definition: 'opencode-go-responses/mimo-v2.5', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: null, sent_level: 'medium', unusable: null }
          },
          roles: {
            level: 'S5',
            product: [
              { id: 'prod-manager', name: '产品部门经理', kind: 'manager', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'prod-architect', name: '产品架构师', kind: 'architect', status: 'returned', model: 'opencode-go-responses/kimi-k2.6', task: 'PRD r1（截止日期与逾期提醒）已交接；回答工程的时区咨询' },
              { id: 'prod-explorer', name: '产品探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'prod-reviewer', name: '产品审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null }
            ],
            engineering: [
              { id: 'eng-manager', name: '工程经理', kind: 'manager', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: '交付 r1 已提交，等待质检结论' },
              { id: 'eng-architect', name: '工程架构师', kind: 'architect', status: 'returned', model: 'opencode-go-responses/kimi-k2.6', task: 'PLAN r1 已接纳' },
              { id: 'eng-lead', name: '主程', kind: 'lead', status: 'returned', model: 'opencode-go-responses/kimi-k2.6', task: 'P-1 至 P-3 已交回，审查退回 3 次后通过' },
              { id: 'eng-explorer', name: '工程探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'eng-reviewer', name: '工程审查者', kind: 'reviewer', status: 'returned', model: 'opencode-go-responses/kimi-k2.6', task: 'P-1 退回 3 次后通过' }
            ],
            quality: [
              { id: 'qa-manager', name: '质检经理', kind: 'manager', status: 'returned', model: 'opencode-go-responses/mimo-v2.5', task: '已接收交付 r1，组织试用' },
              { id: 'qa-tester', name: '测试工程师', kind: 'tester', status: 'working', model: 'opencode-go-responses/mimo-v2.5', task: '在 m-study 上试用待办清单页面' },
              { id: 'qa-explorer', name: '质检探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null },
              { id: 'qa-reviewer', name: '质检审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null }
            ]
          },
          ledger: {
            level: 'S5',
            engineering: {
              items: [
                {
                  id: 'P-1', text: '逾期提醒的时区换算：按本地日历日期比较，补跨午夜的用例', assignee: 'eng-lead', status: 'returned',
                  result: '已交回：本地日期比较与 2 条跨午夜用例',
                  reviews: [
                    { at: '2026-09-28T14:30:00+08:00', verdict: 'returned', text: '逾期判定用 UTC 毫秒比较，跨午夜后当天到期的任务会提前显示逾期；改为按本地日历日期比较。' },
                    { at: '2026-09-28T16:08:00+08:00', verdict: 'returned', text: '跨午夜的用例只覆盖了次日，缺少当天到期的样例；补样例。' },
                    { at: '2026-09-29T11:48:00+08:00', verdict: 'returned', text: '样例通过，但文案仍写「已超过截止日期」；写明截止日期与超期天数。' },
                    { at: '2026-09-29T12:30:00+08:00', verdict: 'passed', text: 'P-1 通过：本地日期比较、跨午夜用例与文案都符合 PRD。' }
                  ]
                },
                { id: 'P-2', text: '列表与筛选结果显示截止日期', assignee: 'eng-lead', status: 'returned', result: '已交回', reviews: [] },
                { id: 'P-3', text: 'npm_test 回归与新增跨午夜用例', assignee: 'eng-lead', status: 'returned', result: '退出 0 · 16 条通过', reviews: [] }
              ],
              facts: ['跨午夜样例在审查中被指出 3 次', 'npm_test 退出 0', '计划条目都有对应实现'],
              questions: [],
              progress: [
                { cycle: 1, judgment: '有进展', text: 'PLAN 接纳，主程开始实现' },
                { cycle: 2, judgment: '有进展', text: '按审查意见改为本地日期比较并补样例' },
                { cycle: 3, judgment: '有进展', text: '文案与样例补齐后通过审查' }
              ]
            },
            quality: {
              items: [
                { id: 'Q-1', text: '对照 PRD 的 5 条验收条件试用页面', assignee: 'qa-tester', status: 'working', result: null, reviews: [] }
              ],
              facts: ['试用完成 2 个步骤', '申请取回 MDN 说明，等待批准'],
              questions: [],
              progress: [{ cycle: 1, judgment: '有进展', text: '试用开始，截止日期显示正常' }]
            }
          },
          attempts: [
            {
              id: 'att-todo-due-01', logical_call_id: 'call-todo-due-p1', department: 'product', role: 'prod-architect', kind: 'work', n: 1, of: 4, status: 'succeeded',
              started_at: '2026-09-28T09:59:00+08:00', duration_ms: 22600, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 6840, output: 1610, cache_read: 0, total: 8450, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: null, sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-due-02', logical_call_id: 'call-todo-due-p2', department: 'product', role: 'prod-architect', kind: 'work', n: 2, of: 4, status: 'succeeded',
              started_at: '2026-09-28T11:21:00+08:00', duration_ms: 14200, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 7920, output: 880, cache_read: 3072, total: 8800, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: null, sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-due-03', logical_call_id: 'call-todo-due-e1', department: 'engineering', role: 'eng-architect', kind: 'work', n: 1, of: 4, status: 'succeeded',
              started_at: '2026-09-28T10:44:00+08:00', duration_ms: 26400, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 10420, output: 1880, cache_read: 0, total: 12300, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: 'high', sent_level: 'high', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-due-04', logical_call_id: 'call-todo-due-e2', department: 'engineering', role: 'eng-lead', kind: 'work', n: 2, of: 4, status: 'succeeded',
              started_at: '2026-09-28T11:06:00+08:00', duration_ms: 68200, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 21400, output: 3320, cache_read: 12288, total: 24720, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: 'high', sent_level: 'high', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-due-05', logical_call_id: 'call-todo-due-e3', department: 'engineering', role: 'eng-reviewer', kind: 'review', n: 1, of: 2, status: 'succeeded',
              started_at: '2026-09-28T14:25:00+08:00', duration_ms: 12100, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 9840, output: 1160, cache_read: 0, total: 11000, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: 'medium', sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-due-06', logical_call_id: 'call-todo-due-e4', department: 'engineering', role: 'eng-lead', kind: 'work', n: 3, of: 4, status: 'succeeded',
              started_at: '2026-09-28T14:40:00+08:00', duration_ms: 41200, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 15860, output: 2240, cache_read: 6144, total: 18100, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: 'high', sent_level: 'high', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-due-07', logical_call_id: 'call-todo-due-e5', department: 'engineering', role: 'eng-lead', kind: 'work', n: 3, of: 4, status: 'succeeded',
              started_at: '2026-09-28T16:22:00+08:00', duration_ms: 36400, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 13620, output: 1980, cache_read: 5120, total: 15600, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: 'high', sent_level: 'high', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-due-08', logical_call_id: 'call-todo-due-e6', department: 'engineering', role: 'eng-lead', kind: 'work', n: 4, of: 4, status: 'succeeded',
              started_at: '2026-09-29T12:06:00+08:00', duration_ms: 33800, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 14280, output: 2060, cache_read: 6144, total: 16340, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: 'high', sent_level: 'high', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-due-09', logical_call_id: 'call-todo-due-q1', department: 'quality', role: 'qa-tester', kind: 'work', n: 1, of: 3, status: 'succeeded',
              started_at: '2026-09-29T14:06:00+08:00', duration_ms: 24600, provider: 'opencode-go-responses',
              requested_model: 'mimo-v2.5', actual_model: 'mimo-v2.5',
              usage: { input: 12180, output: 1640, cache_read: 0, total: 13820, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'mimo-v2.5', window: 1048576, max_output: 65536, source: '部门默认', request_level: null, sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-todo-due-10', logical_call_id: 'call-todo-due-q2', department: 'quality', role: 'qa-tester', kind: 'work', n: 2, of: 3, status: 'running',
              started_at: '2026-09-29T14:24:00+08:00', duration_ms: null, provider: 'opencode-go-responses',
              requested_model: 'mimo-v2.5', actual_model: 'mimo-v2.5',
              usage: { input: 9860, output: 620, cache_read: 2048, total: 10480, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'mimo-v2.5', window: 1048576, max_output: 65536, source: '部门默认', request_level: null, sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            }
          ],
          source: null
        }
      ],
      materials: [
        {
          id: 'm-todo-base-i1', project_id: 'p-todo', work_item_id: 'w-todo-base', kind: 'intend', version: 1,
          title: '用户原文 v1', text: INTEND_TEXT, at: '2026-09-26T20:30:00+08:00', files: null, verdict: null
        },
        {
          id: 'm-todo-base-p1', project_id: 'p-todo', work_item_id: 'w-todo-base', kind: 'prd', version: 1,
          title: 'PRD r1', at: '2026-09-27T09:10:00+08:00', files: null, verdict: null,
          accepted_from: '用户输入 v1',
          text: '# 目标\n做一个待办清单网页：新增、编辑、删除与标记完成任务，按完成状态筛选与搜索；淡紫色（lavender）背景，靛蓝色（indigo）组件。\n\n# 要求与验收条件\n- AC-1 新建：填写「新增任务」表单并提交，新任务出现在列表中\n- AC-2 编辑：修改已有任务的说明并保存，列表中的内容随之更新\n- AC-3 完成：标记任务为已完成，任务有可见的完成标记（划线或勾选）\n- AC-4 删除：选择任务旁的删除，任务从列表中移除\n- AC-5 筛选：按全部、未完成、已完成筛选，列表只显示符合条件的任务，未筛选的任务状态不变\n- AC-6 搜索：按标题或说明搜索，结果只包含匹配的任务\n- AC-7 导航：页面内的导航链接可以切换到「全部待办」与「关于」，不出现错误\n- AC-8 配色：背景为淡紫色，按钮、卡片与标题栏等组件为靛蓝色\n\n# 边界\n单页面，数据保存在浏览器本地；不要求登录与多用户。\n\n# 验收\n用 Playwright 在浏览器中逐条操作；npm_test 运行单元测试。'
        },
        {
          id: 'm-todo-base-l1', project_id: 'p-todo', work_item_id: 'w-todo-base', kind: 'plan', version: 1,
          title: 'PLAN r1', at: '2026-09-27T09:20:00+08:00', files: null, verdict: null,
          goal: '实现待办清单页面与 12 条测试',
          text: '1. 新建 index.html、styles.css 与 app.js\n2. 用 localStorage 保存任务，实现新增、编辑、删除、完成、筛选与搜索\n3. 编写 tests/todo.test.js 并运行登记命令 npm_test'
        },
        {
          id: 'm-todo-base-d1', project_id: 'p-todo', work_item_id: 'w-todo-base', kind: 'delivery', version: 1,
          title: '交付 r1', at: '2026-09-27T10:40:00+08:00', verdict: null,
          summary: '待办清单页面：新增、编辑、删除、完成、筛选与搜索；12 条测试',
          text: '交付 r1：index.html、styles.css、app.js 与 tests/todo.test.js。',
          files: [
            { path: 'index.html', bytes: 2480 }, { path: 'styles.css', bytes: 1820 }, { path: 'app.js', bytes: 5240 },
            { path: 'tests/todo.test.js', bytes: 2110 }, { path: 'package.json', bytes: 340 }
          ],
          git: { commit: 'a1c3f20', parent: null, stat: '5 个文件 · +312' },
          diff: '新增 index.html（86 行）\n新增 styles.css（72 行）\n新增 app.js（184 行）\n新增 tests/todo.test.js（64 行）'
        },
        {
          id: 'm-todo-base-q1', project_id: 'p-todo', work_item_id: 'w-todo-base', kind: 'qa', version: 1,
          title: '质检结论 r1', at: '2026-09-27T11:50:00+08:00', verdict: 'rework_engineering',
          text: '试用第 3 步发现筛选按钮不生效：点击「已完成」后列表没有按状态过滤（D-1，违反 AC-5）。其余 7 条验收条件通过；npm_test 13 条通过。',
          checks: [
            { label: 'AC-1 至 AC-4、AC-6 至 AC-8', ok: true },
            { label: 'AC-5 按完成状态筛选', ok: false }
          ],
          receipts: ['a-todo-base-2'],
          screenshots: ['todo-trial-3.png'],
          files: null
        },
        {
          id: 'm-todo-base-q2', project_id: 'p-todo', work_item_id: 'w-todo-base', kind: 'qa', version: 2,
          title: '质检结论 r2', at: '2026-09-27T18:36:00+08:00', verdict: 'release',
          text: '重测 D-1：筛选按完成状态过滤；8 条验收条件全部通过（npm_test 13 条）。',
          checks: [{ label: 'AC-1 至 AC-8', ok: true }],
          receipts: ['a-todo-base-4'],
          screenshots: ['todo-trial-1.png', 'todo-trial-2.png'],
          files: null
        },
        {
          id: 'm-todo-due-i1', project_id: 'p-todo', work_item_id: 'w-todo-due', kind: 'intend', version: 1,
          title: '用户原文 v2', at: '2026-09-28T09:58:00+08:00', files: null, verdict: null,
          text: '给待办清单增加截止日期与逾期提醒：任务可以设置截止日期，列表显示截止日期，超过截止日期但没有完成的任务显示逾期提醒。'
        },
        {
          id: 'm-todo-due-p1', project_id: 'p-todo', work_item_id: 'w-todo-due', kind: 'prd', version: 1,
          title: 'PRD r1（截止日期与逾期提醒）', at: '2026-09-28T10:38:00+08:00', files: null, verdict: null,
          accepted_from: '用户输入 v1',
          text: '# 目标\n为待办清单增加截止日期与逾期提醒，不改变现有的新增、编辑、删除、完成、筛选与搜索行为。\n\n# 要求与验收条件\n- AC-1 新增任务时可以填写截止日期；不填写时任务不显示截止日期\n- AC-2 列表显示每个任务的截止日期\n- AC-3 超过截止日期但没有完成的任务显示逾期提醒；提醒写明截止日期\n- AC-4 逾期按本地时区（Asia/Shanghai）判定，跨午夜后以本地日历日期比较；截止当天不算逾期\n- AC-5 新增、编辑、删除、完成、筛选与搜索的原有行为不变\n\n# 边界\n不做重复任务与通知提醒。\n\n# 验收\n用 Playwright 逐条操作（含跨午夜的样例）；npm_test 全部通过。'
        },
        {
          id: 'm-todo-due-l1', project_id: 'p-todo', work_item_id: 'w-todo-due', kind: 'plan', version: 1,
          title: 'PLAN r1（截止日期与逾期提醒）', at: '2026-09-28T10:55:00+08:00', files: null, verdict: null,
          goal: '实现截止日期显示与逾期提醒',
          text: '1. 在新增表单增加日期输入，任务对象增加 due 字段\n2. 列表与筛选结果里显示截止日期；逾期任务加标记\n3. 逾期判定按本地日历日期比较，补跨午夜用例\n4. 运行 npm_test 回归'
        },
        {
          id: 'm-todo-due-d1', project_id: 'p-todo', work_item_id: 'w-todo-due', kind: 'delivery', version: 1,
          title: '交付 r1（截止日期与逾期提醒）', at: '2026-09-29T14:00:00+08:00', verdict: null,
          summary: '截止日期输入与显示、逾期提醒（按本地日历日期比较）与跨午夜用例；16 条测试通过',
          text: '交付 r1：在 r1 的基础上修改 index.html、styles.css、app.js 与 tests/todo.test.js。',
          files: [
            { path: 'index.html', bytes: 2960 }, { path: 'styles.css', bytes: 2040 }, { path: 'app.js', bytes: 6120 },
            { path: 'tests/todo.test.js', bytes: 2980 }
          ],
          git: { commit: 'b7e91d4', parent: 'a1c3f20', stat: '4 个文件 · +96 −18' },
          diff: '修改 app.js：日期输入、列表截止日期、逾期标记与本地日期比较\n修改 tests/todo.test.js：新增 2 条跨午夜用例'
        }
      ],
      project_settings: {
        'p-todo': {
          version: 1,
          departments: {
            product: { version: 1, model: null, level: null, prompt_version: null, prompt_text: null },
            engineering: { version: 1, model: null, level: null, prompt_version: null, prompt_text: null },
            quality: { version: 1, model: null, level: null, prompt_version: null, prompt_text: null }
          },
          commands: [
            { name: 'npm_test', argv: ['npm', 'test'], args: [], timeout_sec: 600, output_limit: 200000, version: 1 },
            { name: 'serve_preview', argv: ['npm', 'run', 'preview', '--', '--port', '4173'], args: [], timeout_sec: 300, output_limit: 100000, version: 1 }
          ],
          tools: [
            { id: 'network', label: '网络取回', scope: '只读取回：registry.npmjs.org', approval: '超出范围时逐次批准' }
          ],
          machines: [
            { machine_id: 'm-host', dirs: ['工作区'], operations: ['npm_test', 'serve_preview'], runtime_env: false, standing: false },
            { machine_id: 'm-study', dirs: ['检查副本', '试用浏览器'], operations: ['npm_test', '浏览器试用'], runtime_env: false, standing: false }
          ],
          roles: {
            level: 'S5',
            product: [
              { role_id: 'prod-manager', model: null, level: null, prompt_text: null },
              { role_id: 'prod-architect', model: null, level: null, prompt_text: null },
              { role_id: 'prod-explorer', model: null, level: null, prompt_text: null },
              { role_id: 'prod-reviewer', model: null, level: null, prompt_text: null }
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
      },
      decisions: [
        {
          id: 'd-todo-mdn', kind: 'tool_once', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
          status: 'waiting', issued_at: '2026-09-29T14:20:00+08:00', born_at: '2026-09-29T14:20:00+08:00', version: 1,
          blocks: { scope: 'action', work_item_id: 'w-todo-due', queued_behind: 0 },
          materials: {
            tool: '网络取回', target: 'https://developer.mozilla.org/zh-CN/docs/Web/HTML/Element/input/date',
            scope: '只读取回：registry.npmjs.org',
            exceeds: 'developer.mozilla.org 不在本项目的授权域名中'
          },
          view: '#/p/p-todo/w/w-todo-due/dept/quality',
          answer: null,
          options: [
            {
              id: 'approve', label: '批准这一次取回', kind: 'primary', events: [
                {
                  type: 'x_network_fetch', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
                  label: '用户批准取回 MDN 的日期输入控件说明',
                  payload: { tool: '网络取回', target: 'https://developer.mozilla.org/zh-CN/docs/Web/HTML/Element/input/date', result: '已取回 · 24 KB' },
                  patch: []
                }
              ]
            },
            {
              id: 'deny', label: '不批准', kind: 'danger', events: [
                {
                  type: 'tool_skipped', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
                  label: '用户不批准取回 MDN 的说明，质检部门改用页面本身的可访问性结构',
                  payload: { tool: '网络取回', target: 'https://developer.mozilla.org/zh-CN/docs/Web/HTML/Element/input/date' },
                  patch: []
                }
              ]
            }
          ]
        },
        {
          id: 'd-todo-rework-1', kind: 'rework_reminder', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
          status: 'waiting', issued_at: '2026-09-28T16:10:00+08:00', born_at: '2026-09-28T16:10:00+08:00', version: 1,
          blocks: { scope: null, work_item_id: null, queued_behind: 0 },
          materials: {
            plan_item: '逾期提醒的时区换算', returns: 2,
            last_review: '跨午夜的用例只覆盖了次日，缺少当天到期的样例；补样例。'
          },
          view: '#/p/p-todo/w/w-todo-due/dept/engineering',
          answer: null,
          options: [{ id: 'read', label: '已阅', kind: 'primary', events: [] }]
        },
        {
          id: 'd-todo-rework', kind: 'rework_reminder', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
          status: 'waiting', issued_at: '2026-09-29T11:50:00+08:00', born_at: '2026-09-29T11:50:00+08:00', version: 1,
          blocks: { scope: null, work_item_id: null, queued_behind: 0 },
          materials: {
            plan_item: '逾期提醒的时区换算', returns: 3,
            last_review: '样例通过，但文案仍写「已超过截止日期」；写明截止日期与超期天数。'
          },
          view: '#/p/p-todo/w/w-todo-due/dept/engineering',
          answer: null,
          options: [{ id: 'read', label: '已阅', kind: 'primary', events: [] }]
        }
      ]
    },
    history: [
      {
        at: '2026-09-26T20:30:00+08:00', type: 'project_registered', project_id: 'p-todo',
        label: '新建项目「待办清单网页」', payload: { source: 'idea', name: '待办清单网页' }, patch: []
      },
      {
        at: '2026-09-26T20:30:00+08:00', type: 'user_input_received', project_id: 'p-todo',
        label: '用户提交待办清单网页的需求原文', payload: { version: 1, material_id: 'm-todo-base-i1' }, patch: []
      },
      {
        at: '2026-09-27T08:00:00+08:00', type: 'work_item_created', project_id: 'p-todo', work_item_id: 'w-todo-base',
        label: '事项「建立待办清单页面」从大厅信箱进入', payload: { kind: 'change' },
        patch: [
          { path: 'work_items[id=w-todo-base].status', value: 'in_progress' },
          { path: 'projects[id=p-todo].last_activity_at', value: '2026-09-27T08:00:00+08:00' },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-todo-base', department: 'product', role: null } }
        ]
      },
      {
        at: '2026-09-27T08:00:00+08:00', type: 'run_created', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base',
        label: '建立待办清单页面的 run 创建，产品部门开始', payload: {}, patch: []
      },
      {
        at: '2026-09-27T08:00:00+08:00', type: 'x_slot_acquired', level: '3.4A', project_id: 'p-todo', work_item_id: 'w-todo-base',
        label: '待办清单页面的事项取得执行槽位', payload: { department: 'product' }, patch: []
      },
      {
        at: '2026-09-27T08:00:00+08:00', type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'product',
        label: '产品部门开始整理待办清单页面的需求', payload: {}, patch: []
      },
      {
        at: '2026-09-27T09:10:00+08:00', type: 'spec_accepted', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'product',
        label: '产品提交 PRD r1，主机接纳（8 条验收条件）', payload: { material_id: 'm-todo-base-p1' },
        patch: [{ path: 'runs[id=r-todo-base].elapsed_sec', value: 4200 }]
      },
      {
        at: '2026-09-27T09:12:00+08:00', type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base',
        label: 'PRD r1 交付给工程部门', payload: { from: 'product', to: 'engineering', artifact: 'prd' },
        patch: [
          { path: 'runs[id=r-todo-base].department', value: 'engineering' },
          { path: 'runs[id=r-todo-base].last_department', value: 'product' },
          { path: 'runs[id=r-todo-base].elapsed_sec', value: 4320 },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-base' } },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-todo-base', department: 'engineering', role: null } }
        ]
      },
      {
        at: '2026-09-27T09:20:00+08:00', type: 'plan_accepted', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'engineering',
        label: '工程提交 PLAN r1，主机接纳', payload: { material_id: 'm-todo-base-l1' },
        patch: [{ path: 'runs[id=r-todo-base].elapsed_sec', value: 6600 }]
      },
      {
        at: '2026-09-27T10:40:00+08:00', type: 'delivery_accepted', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'engineering',
        label: '工程封存交付 r1：待办清单页面与 12 条测试', payload: { material_id: 'm-todo-base-d1' },
        patch: [{ path: 'runs[id=r-todo-base].elapsed_sec', value: 9600 }]
      },
      {
        at: '2026-09-27T10:42:00+08:00', type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base',
        label: '交付 r1 送到质检部门', payload: { from: 'engineering', to: 'quality', artifact: 'box' },
        patch: [
          { path: 'runs[id=r-todo-base].department', value: 'quality' },
          { path: 'runs[id=r-todo-base].last_department', value: 'engineering' },
          { path: 'runs[id=r-todo-base].elapsed_sec', value: 9720 },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-base' } },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-todo-base', department: 'quality', role: null } }
        ]
      },
      {
        at: '2026-09-27T11:00:00+08:00', type: 'x_remote_action_started', level: '3.2C', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'quality',
        label: '质检在书房台式机上开始试用待办清单页面', payload: { machine_id: 'm-study', action_id: 'a-todo-trial-1', label: '试用待办清单页面（第 1 轮）' },
        patch: [{ path: 'machines[id=m-study].actions', push: { project_id: 'p-todo', work_item_id: 'w-todo-base', department: 'quality', action_id: 'a-todo-trial-1', label: '试用待办清单页面（第 1 轮）', state: 'running' } }]
      },
      {
        at: '2026-09-27T11:02:00+08:00', type: 'x_trial_step', level: '3.2D', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'quality',
        label: '试用第 1 步：打开页面，确认列表、导航与配色', payload: { step: 1, screenshot: 'todo-trial-1.png', text: '列表与导航正常，背景为淡紫色、组件为靛蓝色' }, patch: []
      },
      {
        at: '2026-09-27T11:10:00+08:00', type: 'x_trial_step', level: '3.2D', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'quality',
        label: '试用第 2 步：新增任务「预约体检」', payload: { step: 2, screenshot: 'todo-trial-2.png', text: '新任务出现在列表中' }, patch: []
      },
      {
        at: '2026-09-27T11:18:00+08:00', type: 'x_trial_step', level: '3.2D', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'quality',
        label: '试用第 3 步：点击「已完成」筛选，列表没有变化', payload: { step: 3, screenshot: 'todo-trial-3.png', text: '筛选按钮已按下，列表仍然显示全部任务' }, patch: []
      },
      {
        at: '2026-09-27T11:40:00+08:00', type: 'x_remote_action_finished', level: '3.2C', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'quality',
        label: '试用结束：筛选按钮不生效，记录缺陷 D-1', payload: { machine_id: 'm-study', action_id: 'a-todo-trial-1' },
        patch: [{ path: 'machines[id=m-study].actions', remove: { key: 'action_id', value: 'a-todo-trial-1' } }]
      },
      {
        at: '2026-09-27T11:50:00+08:00', type: 'qa_submitted', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'quality',
        label: '质检结论 r1：返工——筛选按钮不生效（D-1）', payload: { verdict: 'rework_engineering', material_id: 'm-todo-base-q1' },
        patch: [
          { path: 'runs[id=r-todo-base].cycle', value: 2 },
          { path: 'runs[id=r-todo-base].elapsed_sec', value: 13800 }
        ]
      },
      {
        at: '2026-09-27T11:52:00+08:00', type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base',
        label: '交付 r1 退回工程部门', payload: { from: 'quality', to: 'engineering', artifact: 'defect' },
        patch: [
          { path: 'runs[id=r-todo-base].department', value: 'engineering' },
          { path: 'runs[id=r-todo-base].last_department', value: 'quality' },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-base' } },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-todo-base', department: 'engineering', role: null } }
        ]
      },
      {
        at: '2026-09-27T14:20:00+08:00', type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'engineering',
        label: '工程部门按 D-1 修改筛选逻辑', payload: {}, patch: []
      },
      {
        at: '2026-09-27T16:40:00+08:00', type: 'delivery_accepted', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'engineering',
        label: '工程封存交付 r2：修复筛选按钮', payload: { material_id: 'm-todo-base-d1' },
        patch: [{ path: 'runs[id=r-todo-base].elapsed_sec', value: 31000 }]
      },
      {
        at: '2026-09-27T16:42:00+08:00', type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base',
        label: '交付 r2 送到质检部门', payload: { from: 'engineering', to: 'quality', artifact: 'box' },
        patch: [
          { path: 'runs[id=r-todo-base].department', value: 'quality' },
          { path: 'runs[id=r-todo-base].last_department', value: 'engineering' },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-base' } },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-todo-base', department: 'quality', role: null } }
        ]
      },
      {
        at: '2026-09-27T17:00:00+08:00', type: 'x_remote_action_started', level: '3.2C', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'quality',
        label: '质检开始重测待办清单页面', payload: { machine_id: 'm-study', action_id: 'a-todo-trial-2', label: '试用待办清单页面（第 2 轮）' },
        patch: [{ path: 'machines[id=m-study].actions', push: { project_id: 'p-todo', work_item_id: 'w-todo-base', department: 'quality', action_id: 'a-todo-trial-2', label: '试用待办清单页面（第 2 轮）', state: 'running' } }]
      },
      {
        at: '2026-09-27T18:30:00+08:00', type: 'x_remote_action_finished', level: '3.2C', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'quality',
        label: '重测结束：筛选按钮已修复', payload: { machine_id: 'm-study', action_id: 'a-todo-trial-2' },
        patch: [{ path: 'machines[id=m-study].actions', remove: { key: 'action_id', value: 'a-todo-trial-2' } }]
      },
      {
        at: '2026-09-27T18:36:00+08:00', type: 'qa_submitted', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base', department: 'quality',
        label: '质检结论 r2：放行——8 条验收条件全部通过', payload: { verdict: 'release', material_id: 'm-todo-base-q2' },
        patch: [
          { path: 'work_items[id=w-todo-base].status', value: 'released' },
          { path: 'runs[id=r-todo-base].phase', value: 'DONE' },
          { path: 'runs[id=r-todo-base].department', value: null },
          { path: 'runs[id=r-todo-base].last_department', value: 'quality' },
          { path: 'runs[id=r-todo-base].recovery.state', value: 'terminated' },
          { path: 'runs[id=r-todo-base].recovery.last_confirmed', value: { seq: 6, text: '质检放行，8 条验收条件全部通过' } },
          { path: 'runs[id=r-todo-base].elapsed_sec', value: 37200 },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-base' } }
        ]
      },
      {
        at: '2026-09-27T18:38:00+08:00', type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base',
        label: '放行单与交付 r2 送到成果库', payload: { from: 'quality', to: 'library', artifact: 'release' },
        patch: [{ path: 'projects[id=p-todo].last_activity_at', value: '2026-09-27T18:38:00+08:00' }]
      },
      {
        at: '2026-09-27T18:40:00+08:00', type: 'deliverable_adopted', project_id: 'p-todo', work_item_id: 'w-todo-base', run_id: 'r-todo-base',
        label: '项目采纳 r1：待办清单页面', payload: { version: 'r1', work_item_id: 'w-todo-base' },
        patch: [
          { path: 'projects[id=p-todo].adoptions', push: { version: 'r1', work_item_id: 'w-todo-base', summary: '待办清单页面：新增、编辑、删除、完成、筛选与搜索', adopted_at: '2026-09-27T18:40:00+08:00' } },
          { path: 'work_items[id=w-todo-base].status', value: 'adopted' },
          { path: 'runs[id=r-todo-base].recovery.reason', value: '质检放行，事项已完成并被采纳为 r1' },
          { path: 'projects[id=p-todo].last_activity_at', value: '2026-09-27T18:40:00+08:00' }
        ]
      },
      {
        at: '2026-09-28T09:58:00+08:00', type: 'user_input_received', project_id: 'p-todo',
        label: '用户追加输入：截止日期与逾期提醒', payload: { version: 1, material_id: 'm-todo-due-i1' },
        patch: [{ path: 'projects[id=p-todo].last_activity_at', value: '2026-09-28T09:58:00+08:00' }]
      },
      {
        at: '2026-09-28T10:00:00+08:00', type: 'work_item_created', project_id: 'p-todo', work_item_id: 'w-todo-due',
        label: '事项「增加截止日期与逾期提醒」从大厅信箱进入', payload: { kind: 'change' },
        patch: [
          { path: 'work_items[id=w-todo-due].status', value: 'in_progress' },
          { path: 'projects[id=p-todo].last_activity_at', value: '2026-09-28T10:00:00+08:00' },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-todo-due', department: 'product', role: null } }
        ]
      },
      {
        at: '2026-09-28T10:00:00+08:00', type: 'run_created', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
        label: '截止日期与逾期提醒的 run 创建，产品部门开始', payload: {}, patch: []
      },
      {
        at: '2026-09-28T10:00:00+08:00', type: 'x_slot_acquired', level: '3.4A', project_id: 'p-todo', work_item_id: 'w-todo-due',
        label: '截止日期与逾期提醒的事项取得执行槽位', payload: { department: 'product' }, patch: []
      },
      {
        at: '2026-09-28T10:00:00+08:00', type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'product',
        label: '产品部门开始写截止日期与逾期提醒的 PRD', payload: {}, patch: []
      },
      {
        at: '2026-09-28T10:38:00+08:00', type: 'spec_accepted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'product',
        label: '产品提交 PRD r1（截止日期与逾期提醒），主机接纳', payload: { material_id: 'm-todo-due-p1' },
        patch: [{ path: 'runs[id=r-todo-due].elapsed_sec', value: 2280 }]
      },
      {
        at: '2026-09-28T10:40:00+08:00', type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
        label: 'PRD r1 交付给工程部门', payload: { from: 'product', to: 'engineering', artifact: 'prd' },
        patch: [
          { path: 'runs[id=r-todo-due].department', value: 'engineering' },
          { path: 'runs[id=r-todo-due].last_department', value: 'product' },
          { path: 'runs[id=r-todo-due].elapsed_sec', value: 2400 },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-due' } },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-todo-due', department: 'engineering', role: null } }
        ]
      },
      {
        at: '2026-09-28T10:42:00+08:00', type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
        label: '工程部门开始计划截止日期与逾期提醒', payload: {}, patch: []
      },
      {
        at: '2026-09-28T10:44:00+08:00', type: 'x_role_task_assigned', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-architect',
        label: '工程经理把「起草 PLAN」任务卡递给工程架构师', payload: { to: 'eng-architect', task: '起草 PLAN r1：截止日期显示与逾期判定' },
        patch: [
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-architect].status', value: 'assigned' },
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-architect].task', value: '起草 PLAN r1：截止日期显示与逾期判定' }
        ]
      },
      {
        at: '2026-09-28T10:50:00+08:00', type: 'x_role_result_returned', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-architect',
        label: '工程架构师把 PLAN r1 草案交回经理', payload: { to: 'eng-architect' },
        patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-architect].status', value: 'returned' }]
      },
      {
        at: '2026-09-28T10:52:00+08:00', type: 'x_review_recorded', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-reviewer',
        label: '工程审查者审查 PLAN r1：通过', payload: { verdict: 'passed', text: '计划项与 PRD 的 5 条验收条件对应，通过。' },
        patch: [
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].status', value: 'returned' },
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].task', value: 'PLAN r1 审查通过' }
        ]
      },
      {
        at: '2026-09-28T10:55:00+08:00', type: 'plan_accepted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
        label: '工程提交 PLAN r1，主机接纳', payload: { material_id: 'm-todo-due-l1' },
        patch: [{ path: 'runs[id=r-todo-due].elapsed_sec', value: 3300 }]
      },
      {
        at: '2026-09-28T11:00:00+08:00', type: 'x_role_task_assigned', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead',
        label: '工程经理把实现任务递给主程：P-1 的时区换算与 P-2 的显示', payload: { to: 'eng-lead', task: '实现 P-1 与 P-2' },
        patch: [
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'assigned' },
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].task', value: '实现 P-1 与 P-2' }
        ]
      },
      {
        at: '2026-09-28T11:02:00+08:00', type: 'collaboration_requested', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
        label: '工程询问产品：逾期是否按本地时区判定', payload: { from: 'engineering', to: 'product', request_id: 'q-todo-due-tz' },
        patch: [
          { path: 'runs[id=r-todo-due].requests[id=q-todo-due-tz].status', value: 'open' },
          { path: 'runs[id=r-todo-due].elapsed_sec', value: 3720 },
          { path: 'projects[id=p-todo].last_activity_at', value: '2026-09-28T11:02:00+08:00' }
        ]
      },
      {
        at: '2026-09-28T11:20:00+08:00', type: 'collaboration_responded', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'product',
        label: '产品回答：按本地时区判定，跨午夜后按本地日历日期比较', payload: { from: 'product', to: 'engineering', request_id: 'q-todo-due-tz' },
        patch: [
          { path: 'runs[id=r-todo-due].requests[id=q-todo-due-tz].status', value: 'answered' },
          { path: 'runs[id=r-todo-due].requests[id=q-todo-due-tz].answer', value: '按本地时区（Asia/Shanghai）判定；跨午夜后按本地日历日期比较，截止当天不显示逾期。' },
          { path: 'runs[id=r-todo-due].elapsed_sec', value: 4800 },
          { path: 'projects[id=p-todo].last_activity_at', value: '2026-09-28T11:20:00+08:00' }
        ]
      },
      {
        at: '2026-09-28T14:20:00+08:00', type: 'x_role_result_returned', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead',
        label: '主程把第一版实现交回经理', payload: { to: 'eng-lead' },
        patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'returned' }]
      },
      {
        at: '2026-09-28T14:30:00+08:00', type: 'x_review_recorded', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-reviewer',
        label: '工程审查者退回 P-1（第 1 次）：逾期判定用 UTC 毫秒比较', payload: { verdict: 'returned', text: '逾期判定用 UTC 毫秒比较，跨午夜后当天到期的任务会提前显示逾期；改为按本地日历日期比较。' },
        patch: [
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].status', value: 'returned' },
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].task', value: 'P-1 退回 1 次' }
        ]
      },
      {
        at: '2026-09-28T14:35:00+08:00', type: 'x_role_task_assigned', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead',
        label: '工程经理把退回意见转给主程', payload: { to: 'eng-lead', task: '按审查意见改为本地日历日期比较' },
        patch: [
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'assigned' },
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].task', value: '按审查意见改为本地日历日期比较' }
        ]
      },
      {
        at: '2026-09-28T16:00:00+08:00', type: 'x_role_result_returned', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead',
        label: '主程交回修改后的实现', payload: { to: 'eng-lead' },
        patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'returned' }]
      },
      {
        at: '2026-09-28T16:08:00+08:00', type: 'x_review_recorded', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-reviewer',
        label: '工程审查者退回 P-1（第 2 次）：缺少当天到期的样例', payload: { verdict: 'returned', text: '跨午夜的用例只覆盖了次日，缺少当天到期的样例；补样例。' },
        patch: [
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].task', value: 'P-1 退回 2 次' }
        ]
      },
      {
        at: '2026-09-28T16:10:00+08:00', type: 'x_decision_issued', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
        label: '提醒用户：计划条目「逾期提醒的时区换算」被退回 2 次', payload: { decision_id: 'd-todo-rework-1', kind: 'rework_reminder' },
        patch: [{ path: 'decisions[id=d-todo-rework-1].status', value: 'waiting' }]
      },
      {
        at: '2026-09-28T16:15:00+08:00', type: 'x_decision_answered', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
        label: '用户回答「反复退回的提醒」：已阅', payload: { decision_id: 'd-todo-rework-1', kind: 'rework_reminder', option: 'read' },
        patch: [
          { path: 'decisions[id=d-todo-rework-1].status', value: 'answered' },
          { path: 'decisions[id=d-todo-rework-1].answer', value: { option: 'read', label: '已阅', note: '', at: '2026-09-28T16:15:00+08:00' } }
        ]
      },
      {
        at: '2026-09-28T16:20:00+08:00', type: 'x_role_task_assigned', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead',
        label: '工程经理把 P-1 的第二次修改任务递给主程', payload: { to: 'eng-lead', task: '补当天到期的样例' },
        patch: [
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'assigned' },
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].task', value: '补当天到期的样例' }
        ]
      },
      {
        at: '2026-09-29T03:12:00+08:00', type: 'x_run_interrupted', level: '3.1', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
        label: '控制主机断电重启，截止日期与逾期提醒的 run 中断', payload: {},
        patch: [
          { path: 'runs[id=r-todo-due].recovery.state', value: 'interrupted' },
          { path: 'runs[id=r-todo-due].recovery.reason', value: '控制主机断电重启，进程中断' }
        ]
      },
      {
        at: '2026-09-29T03:13:00+08:00', type: 'x_run_auto_resumed', level: '3.1', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
        label: '控制主机重新启动后自动继续截止日期与逾期提醒的 run', payload: { auto_resumed_at: '2026-09-29T03:13:00+08:00' },
        patch: [
          { path: 'runs[id=r-todo-due].recovery.state', value: 'running' },
          { path: 'runs[id=r-todo-due].recovery.reason', value: null },
          { path: 'runs[id=r-todo-due].recovery.auto_resumed_at', value: '2026-09-29T03:13:00+08:00' }
        ]
      },
      {
        at: '2026-09-29T11:40:00+08:00', type: 'x_role_result_returned', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead',
        label: '主程交回补齐样例的实现', payload: { to: 'eng-lead' },
        patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'returned' }]
      },
      {
        at: '2026-09-29T11:48:00+08:00', type: 'x_review_recorded', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-reviewer',
        label: '工程审查者退回 P-1（第 3 次）：提醒文案不完整', payload: { verdict: 'returned', text: '样例通过，但文案仍写「已超过截止日期」；写明截止日期与超期天数。' },
        patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].task', value: 'P-1 退回 3 次' }]
      },
      {
        at: '2026-09-29T11:50:00+08:00', type: 'x_decision_issued', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
        label: '再次提醒用户：计划条目「逾期提醒的时区换算」被退回 3 次', payload: { decision_id: 'd-todo-rework', kind: 'rework_reminder' },
        patch: [
          { path: 'decisions[id=d-todo-rework].status', value: 'waiting' },
          { path: 'projects[id=p-todo].last_activity_at', value: '2026-09-29T11:50:00+08:00' }
        ]
      },
      {
        at: '2026-09-29T12:05:00+08:00', type: 'x_role_task_assigned', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead',
        label: '工程经理把 P-1 的第三次修改任务递给主程', payload: { to: 'eng-lead', task: '补全提醒文案并重跑 npm_test' },
        patch: [
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'assigned' },
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].task', value: '补全提醒文案并重跑 npm_test' }
        ]
      },
      {
        at: '2026-09-29T12:20:00+08:00', type: 'x_role_result_returned', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead',
        label: '主程把 P-1 至 P-3 的最新结果交回经理', payload: { to: 'eng-lead' },
        patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'returned' }]
      },
      {
        at: '2026-09-29T12:30:00+08:00', type: 'x_review_recorded', level: 'S5', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-reviewer',
        label: '工程审查者审查 P-1：通过', payload: { verdict: 'passed', text: '本地日期比较、跨午夜用例与文案都符合 PRD。' },
        patch: [
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].task', value: 'P-1 退回 3 次后通过' },
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].task', value: 'P-1 至 P-3 已交回，审查退回 3 次后通过' }
        ]
      },
      {
        at: '2026-09-29T13:58:00+08:00', type: 'proposal_submitted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
        label: '工程部门提交交付说明', payload: { material_id: 'm-todo-due-d1' },
        patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-manager].status', value: 'working' }]
      },
      {
        at: '2026-09-29T14:00:00+08:00', type: 'delivery_accepted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
        label: '工程封存交付 r1：截止日期与逾期提醒', payload: { material_id: 'm-todo-due-d1' },
        patch: [
          { path: 'runs[id=r-todo-due].elapsed_sec', value: 100000 },
          { path: 'runs[id=r-todo-due].recovery.last_confirmed', value: { seq: 12, text: '工程封存交付 r1（截止日期与逾期提醒）' } },
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-manager].status', value: 'returned' },
          { path: 'runs[id=r-todo-due].roles.engineering[id=eng-manager].task', value: '交付 r1 已提交' }
        ]
      },
      {
        at: '2026-09-29T14:05:00+08:00', type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
        label: '交付 r1 送到质检部门', payload: { from: 'engineering', to: 'quality', artifact: 'box' },
        patch: [
          { path: 'runs[id=r-todo-due].department', value: 'quality' },
          { path: 'runs[id=r-todo-due].last_department', value: 'engineering' },
          { path: 'runs[id=r-todo-due].elapsed_sec', value: 100200 },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-due' } },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-todo-due', department: 'quality', role: null } },
          { path: 'projects[id=p-todo].last_activity_at', value: '2026-09-29T14:05:00+08:00' }
        ]
      },
      {
        at: '2026-09-29T14:05:00+08:00', type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
        label: '质检部门开始核验截止日期与逾期提醒', payload: {}, patch: []
      },
      {
        at: '2026-09-29T14:10:00+08:00', type: 'x_remote_action_started', level: '3.2C', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
        label: '质检在书房台式机上开始试用待办清单页面', payload: { machine_id: 'm-study', action_id: 'a-todo-trial-3', label: '试用待办清单页面（截止日期与逾期提醒）' },
        patch: [{ path: 'machines[id=m-study].actions', push: { project_id: 'p-todo', work_item_id: 'w-todo-due', department: 'quality', action_id: 'a-todo-trial-3', label: '试用待办清单页面（截止日期与逾期提醒）', state: 'running' } }]
      },
      {
        at: '2026-09-29T14:11:00+08:00', type: 'x_trial_step', level: '3.2D', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
        label: '试用第 1 步：打开页面，确认列表与截止日期的显示', payload: { step: 1, screenshot: 'todo-trial-1.png', text: '列表正常，任务显示截止日期' }, patch: []
      },
      {
        at: '2026-09-29T14:16:00+08:00', type: 'x_trial_step', level: '3.2D', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
        label: '试用第 2 步：新增任务「续费域名」，填写截止日期 09-30', payload: { step: 2, screenshot: 'todo-trial-2.png', text: '新任务出现在列表中，带截止日期' }, patch: []
      },
      {
        at: '2026-09-29T14:18:00+08:00', type: 'x_network_fetch', level: '3.2B', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
        label: '质检申请取回 MDN 的日期输入控件说明，超出本项目的网络授权', payload: { tool: '网络取回', target: 'https://developer.mozilla.org/zh-CN/docs/Web/HTML/Element/input/date', result: '超出授权：等待逐次批准' },
        patch: []
      },
      {
        at: '2026-09-29T14:20:00+08:00', type: 'x_decision_issued', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
        label: '发出决定请求：授权取回 MDN 的日期输入控件说明', payload: { decision_id: 'd-todo-mdn', kind: 'tool_once' },
        patch: [
          { path: 'decisions[id=d-todo-mdn].status', value: 'waiting' },
          { path: 'projects[id=p-todo].last_activity_at', value: '2026-09-29T14:20:00+08:00' }
        ]
      }
    ],
    scenarios: [
      {
        no: 1, id: 'sc-todo-loop', name: '正常循环', level: 'ui', go: '#/p/p-todo/overview',
        setup: [
          {
            path: 'runs', push: {
              id: 'r-todo-export', work_item_id: 'w-todo-export', project_id: 'p-todo', yudao_version: '0.8.0',
              phase: 'PRODUCT_SPEC', department: 'product', last_department: null, cycle: 1,
              started_at: '2026-09-29T15:30:00+08:00', elapsed_sec: 0, limit_sec: 86400,
              waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
              recovery: {
                state: 'running', reason: null, unusable: null,
                last_confirmed: { seq: 0, text: '事项已登记，等待产品开始' },
                owner: { id: 'exec-92b1', since: '2026-09-29T15:30:00+08:00' },
                late_results: [], verifications: [], unfinished: [],
                limits: { activations: 0, model_steps: 0, retries: 0 }, auto_resumed_at: null
              },
              inputs: [], flow: [], requests: [], guidance: [],
              messages: { product: [], engineering: [], quality: [], operations: [] },
              actions: [], trials: [],
              contexts: { product: [], engineering: [], quality: [] },
              prompts: {
                product: { config_version: 0, request_version: 0, text: PRODUCT_PROMPT },
                engineering: { config_version: 0, request_version: 0, text: ENGINEERING_PROMPT },
                quality: { config_version: 0, request_version: 0, text: QUALITY_PROMPT }
              },
              compactions: [],
              effective_model: {
                product: { definition: 'opencode-go-responses/kimi-k2.6', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: null, sent_level: 'medium', unusable: null },
                engineering: { definition: 'opencode-go-responses/kimi-k2.6', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: 'high', sent_level: 'high', unusable: null },
                quality: { definition: 'opencode-go-responses/mimo-v2.5', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: null, sent_level: 'medium', unusable: null }
              },
              roles: {
                level: 'S5',
                product: [
                  { id: 'prod-manager', name: '产品部门经理', kind: 'manager', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
                  { id: 'prod-architect', name: '产品架构师', kind: 'architect', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
                  { id: 'prod-explorer', name: '产品探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
                  { id: 'prod-reviewer', name: '产品审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null }
                ],
                engineering: [
                  { id: 'eng-manager', name: '工程经理', kind: 'manager', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
                  { id: 'eng-architect', name: '工程架构师', kind: 'architect', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
                  { id: 'eng-lead', name: '主程', kind: 'lead', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
                  { id: 'eng-explorer', name: '工程探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
                  { id: 'eng-reviewer', name: '工程审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null }
                ],
                quality: [
                  { id: 'qa-manager', name: '质检经理', kind: 'manager', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null },
                  { id: 'qa-tester', name: '测试工程师', kind: 'tester', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null },
                  { id: 'qa-explorer', name: '质检探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null },
                  { id: 'qa-reviewer', name: '质检审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null }
                ]
              },
              ledger: {
                level: 'S5',
                engineering: { items: [], facts: [], questions: [], progress: [] },
                quality: { items: [], facts: [], questions: [], progress: [] }
              },
              attempts: [], source: null, born_at: '2026-09-29T15:30:00+08:00'
            }
          },
          {
            path: 'work_items', push: {
              id: 'w-todo-export', project_id: 'p-todo', title: '导出待办为 CSV', color_index: 4, kind: 'change',
              status: 'not_started', queue_reason: null, run_id: 'r-todo-export', queue_pos: null, version: 1,
              created_at: '2026-09-29T15:30:00+08:00', born_at: '2026-09-29T15:30:00+08:00'
            }
          }
        ],
        steps: [
          {
            delay: 1200, go: '#/home',
            event: {
              type: 'work_item_created', project_id: 'p-todo', work_item_id: 'w-todo-export',
              label: '新事项「导出待办为 CSV」从大厅信箱进入', payload: { kind: 'change' }
            },
            patch: [
              { path: 'work_items[id=w-todo-export].status', value: 'in_progress' },
              { path: 'projects[id=p-todo].last_activity_at', value: '2026-09-29T15:30:00+08:00' }
            ]
          },
          {
            delay: 1200, go: '#/p/p-todo/overview',
            event: {
              type: 'run_created', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export',
              label: '导出待办为 CSV 的 run 创建，产品部门开始', payload: {}
            },
            patch: []
          },
          {
            delay: 1200,
            event: {
              type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export', department: 'product',
              label: '产品部门读取需求原文，整理导出为 CSV 的要求', payload: {}
            },
            patch: []
          },
          {
            delay: 1400,
            event: {
              type: 'spec_accepted', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export', department: 'product',
              label: '产品提交 PRD r1：导出为 CSV（3 条验收条件），主机接纳', payload: {}
            },
            patch: [{ path: 'runs[id=r-todo-export].elapsed_sec', value: 1600 }]
          },
          {
            delay: 1200,
            event: {
              type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export',
              label: 'PRD r1 交付给工程部门', payload: { from: 'product', to: 'engineering', artifact: 'prd' }
            },
            patch: [
              { path: 'runs[id=r-todo-export].department', value: 'engineering' },
              { path: 'runs[id=r-todo-export].last_department', value: 'product' },
              { path: 'runs[id=r-todo-export].elapsed_sec', value: 1700 }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'plan_accepted', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export', department: 'engineering',
              label: '工程提交 PLAN r1：导出按钮与 CSV 生成，主机接纳', payload: {}
            },
            patch: [{ path: 'runs[id=r-todo-export].elapsed_sec', value: 2800 }]
          },
          {
            delay: 1200,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export', department: 'engineering', tool: 'edit_range',
              label: '工程部门按区间编辑 app.js：导出为 CSV', payload: {}
            },
            patch: [{
              path: 'runs[id=r-todo-export].actions', push: {
                id: 'a-todo-export-1', department: 'engineering', role: null, tool: 'edit_range',
                summary: '按区间编辑 app.js：导出为 CSV', input: 'PLAN r1 第 1 项', state: 'done', receipt: null,
                before: 'app.js @ b7e91d4', after: 'app.js @ c3a7f10', machine_id: 'm-host', at: '2026-09-29T15:30:00+08:00'
              }
            }]
          },
          {
            delay: 1400,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export', department: 'engineering', tool: 'run_command',
              label: '工程部门走到终端执行登记命令 npm_test', payload: {}
            },
            patch: [{
              path: 'runs[id=r-todo-export].actions', push: {
                id: 'a-todo-export-2', department: 'engineering', role: null, tool: 'run_command',
                summary: '执行登记命令 npm_test', input: 'PLAN r1 第 3 项：自测', state: 'done',
                receipt: { command: 'npm_test', argv: ['npm', 'test'], exit_code: 0, output: '19 passing (0.6s)', truncated: false, timed_out: false, duration_ms: 1900, snapshot: 'ws-c3a7f10' },
                before: '工作区 c3a7f10', after: '工作区 c3a7f10（未改动）', machine_id: 'm-host', at: '2026-09-29T15:30:00+08:00'
              }
            }]
          },
          {
            delay: 1400,
            event: {
              type: 'delivery_accepted', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export', department: 'engineering',
              label: '工程封存交付 r1：导出为 CSV', payload: {}
            },
            patch: [{ path: 'runs[id=r-todo-export].elapsed_sec', value: 5400 }]
          },
          {
            delay: 1200,
            event: {
              type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export',
              label: '交付 r1 送到质检部门', payload: { from: 'engineering', to: 'quality', artifact: 'box' }
            },
            patch: [
              { path: 'runs[id=r-todo-export].department', value: 'quality' },
              { path: 'runs[id=r-todo-export].last_department', value: 'engineering' }
            ]
          },
          {
            delay: 1200,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export', department: 'quality', tool: 'browser',
              label: '质检部门在 m-study 上打开页面，检查导出', payload: {}
            },
            patch: []
          },
          {
            delay: 1600,
            event: {
              type: 'qa_submitted', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export', department: 'quality',
              label: '质检放行：导出为 CSV 的 3 条验收条件全部通过', payload: { verdict: 'release' }
            },
            patch: [
              { path: 'work_items[id=w-todo-export].status', value: 'released' },
              { path: 'runs[id=r-todo-export].phase', value: 'DONE' },
              { path: 'runs[id=r-todo-export].department', value: null },
              { path: 'runs[id=r-todo-export].last_department', value: 'quality' },
              { path: 'runs[id=r-todo-export].recovery.state', value: 'terminated' },
              { path: 'runs[id=r-todo-export].elapsed_sec', value: 6600 }
            ]
          },
          {
            delay: 1200,
            event: {
              type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export',
              label: '放行单与交付 r1 送到成果库', payload: { from: 'quality', to: 'library', artifact: 'release' }
            },
            patch: [{ path: 'projects[id=p-todo].last_activity_at', value: '2026-09-29T15:30:00+08:00' }]
          },
          {
            delay: 1400,
            event: {
              type: 'deliverable_adopted', project_id: 'p-todo', work_item_id: 'w-todo-export', run_id: 'r-todo-export',
              label: '项目采纳 r2：导出为 CSV', payload: { version: 'r2', work_item_id: 'w-todo-export' }
            },
            patch: [
              { path: 'projects[id=p-todo].adoptions', push: { version: 'r2', work_item_id: 'w-todo-export', summary: '导出为 CSV', adopted_at: '2026-09-29T15:30:00+08:00' } },
              { path: 'work_items[id=w-todo-export].status', value: 'adopted' },
              { path: 'runs[id=r-todo-export].recovery.reason', value: '质检放行，事项已完成并被采纳为 r2' },
              { path: 'projects[id=p-todo].last_activity_at', value: '2026-09-29T15:30:00+08:00' }
            ]
          }
        ]
      },
      {
        no: 2, id: 'sc-todo-rework', name: '返工', level: 'ui', go: '#/p/p-todo/dept/quality',
        setup: [],
        steps: [
          {
            delay: 1200,
            event: {
              type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '质检部门回到试用台前，继续试用剩下的步骤', payload: {}
            },
            patch: []
          },
          {
            delay: 1400, at: '2026-09-29T15:31:00+08:00',
            event: {
              type: 'x_trial_step', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '试用第 3 步：标记「续费域名」为已完成，任务显示划线',
              payload: { step: 3, screenshot: 'todo-trial-4.png', text: '任务显示已完成' }
            },
            patch: [{
              path: 'runs[id=r-todo-due].trials', push: {
                step: 3, at: '2026-09-29T15:31:00+08:00', action: '标记「续费域名」为已完成', screenshot: 'todo-trial-4.png',
                text_lines: ['任务：续费域名（已完成）', '标题显示划线'], requirement: '标记完成'
              }
            }]
          },
          {
            delay: 1400, at: '2026-09-29T15:32:00+08:00',
            event: {
              type: 'x_trial_step', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '试用第 4 步：删除任务「整理房间」，任务从列表消失',
              payload: { step: 4, screenshot: 'todo-trial-5.png', text: '任务从列表消失' }
            },
            patch: [{
              path: 'runs[id=r-todo-due].trials', push: {
                step: 4, at: '2026-09-29T15:32:00+08:00', action: '删除任务「整理房间」', screenshot: 'todo-trial-5.png',
                text_lines: ['删除按钮：整理房间', '列表中不再显示'], requirement: '删除任务'
              }
            }]
          },
          {
            delay: 1600, at: '2026-09-29T15:33:00+08:00',
            event: {
              type: 'x_trial_step', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '试用第 5 步：跨午夜后当天到期的任务被显示为逾期（D-1）',
              payload: { step: 5, screenshot: 'todo-trial-6.png', text: '任务「交物业费」显示「已超过截止日期 2026-09-27」；跨午夜后当天到期的任务也会显示提醒，实际尚未到期' }
            },
            patch: [
              {
                path: 'runs[id=r-todo-due].trials', push: {
                  step: 5, at: '2026-09-29T15:33:00+08:00', action: '检查逾期提醒：把任务的截止日期设为本日，跨午夜后查看', screenshot: 'todo-trial-6.png',
                  text_lines: ['任务：交物业费（截止 2026-09-27）', '提醒：已超过截止日期 2026-09-27'], requirement: '逾期提醒'
                }
              },
              {
                path: 'materials', push: {
                  id: 'm-todo-due-q1', project_id: 'p-todo', work_item_id: 'w-todo-due', kind: 'qa', version: 1,
                  title: '质检结论 r1', at: '2026-09-29T15:33:00+08:00', verdict: 'rework_engineering',
                  text: '试用发现：跨午夜后当天到期的任务被显示为逾期（D-1，违反 AC-4）；其余验收条件通过。',
                  checks: [{ label: 'AC-4 跨午夜后按本地日历日期比较', ok: false }, { label: 'AC-1 至 AC-3、AC-5', ok: true }],
                  receipts: [], screenshots: ['todo-trial-6.png'], files: null
                }
              }
            ]
          },
          {
            delay: 1600,
            event: {
              type: 'qa_submitted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '质检结论 r1：返工——逾期提醒在跨午夜时显示错误（D-1）',
              payload: { verdict: 'rework_engineering', material_id: 'm-todo-due-q1' }
            },
            patch: [
              { path: 'runs[id=r-todo-due].cycle', value: 2 },
              { path: 'runs[id=r-todo-due].elapsed_sec', value: 103800 }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
              label: '交付 r1 退回工程部门', payload: { from: 'quality', to: 'engineering', artifact: 'defect' }
            },
            patch: [
              { path: 'runs[id=r-todo-due].department', value: 'engineering' },
              { path: 'runs[id=r-todo-due].last_department', value: 'quality' },
              { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-due' } },
              { path: 'runtime.slots.used', push: { work_item_id: 'w-todo-due', department: 'engineering', role: null } }
            ]
          },
          {
            delay: 1200,
            event: {
              type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '工程部门按 D-1 修改逾期判定', payload: {}
            },
            patch: []
          },
          {
            delay: 1400,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', tool: 'edit_range',
              label: '工程部门按区间编辑 app.js：逾期改为按本地日历日期比较', payload: {}
            },
            patch: [{
              path: 'runs[id=r-todo-due].actions', push: {
                id: 'a-todo-due-6', department: 'engineering', role: null, tool: 'edit_range',
                summary: '按区间编辑 app.js：逾期按本地日历日期比较并补跨午夜用例', input: '质检结论 r1 的 D-1', state: 'done', receipt: null,
                before: 'app.js @ b7e91d4', after: 'app.js @ e02b7c1', machine_id: 'm-host', at: '2026-09-29T15:34:00+08:00'
              }
            }]
          },
          {
            delay: 1400,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', tool: 'run_command',
              label: '工程部门执行登记命令 npm_test，退出 0', payload: {}
            },
            patch: [{
              path: 'runs[id=r-todo-due].actions', push: {
                id: 'a-todo-due-7', department: 'engineering', role: null, tool: 'run_command',
                summary: '执行登记命令 npm_test（含跨午夜用例）', input: 'D-1 修复项', state: 'done',
                receipt: { command: 'npm_test', argv: ['npm', 'test'], exit_code: 0, output: '18 passing (0.5s)', truncated: false, timed_out: false, duration_ms: 1980, snapshot: 'ws-e02b7c1' },
                before: '工作区 e02b7c1', after: '工作区 e02b7c1（未改动）', machine_id: 'm-host', at: '2026-09-29T15:34:00+08:00'
              }
            }]
          },
          {
            delay: 1400,
            event: {
              type: 'delivery_accepted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '工程封存交付 r2：修复 D-1', payload: {}
            },
            patch: [{ path: 'runs[id=r-todo-due].elapsed_sec', value: 106200 }]
          },
          {
            delay: 1200,
            event: {
              type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
              label: '交付 r2 送到质检部门', payload: { from: 'engineering', to: 'quality', artifact: 'box' }
            },
            patch: [
              { path: 'runs[id=r-todo-due].department', value: 'quality' },
              { path: 'runs[id=r-todo-due].last_department', value: 'engineering' },
              { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-due' } },
              { path: 'runtime.slots.used', push: { work_item_id: 'w-todo-due', department: 'quality', role: null } }
            ]
          },
          {
            delay: 1200,
            event: {
              type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '质检重测跨午夜的样例', payload: {}
            },
            patch: []
          },
          {
            delay: 1600,
            event: {
              type: 'qa_submitted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '质检放行：重测 D-1 通过，5 条验收条件全部通过', payload: { verdict: 'release' }
            },
            patch: [
              { path: 'work_items[id=w-todo-due].status', value: 'released' },
              { path: 'runs[id=r-todo-due].phase', value: 'DONE' },
              { path: 'runs[id=r-todo-due].department', value: null },
              { path: 'runs[id=r-todo-due].last_department', value: 'quality' },
              { path: 'runs[id=r-todo-due].recovery.state', value: 'terminated' },
              { path: 'runs[id=r-todo-due].elapsed_sec', value: 106800 },
              { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-due' } }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'transition', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due',
              label: '放行单与交付 r2 送到成果库', payload: { from: 'quality', to: 'library', artifact: 'release' }
            },
            patch: [{ path: 'projects[id=p-todo].last_activity_at', value: '2026-09-29T15:36:00+08:00' }]
          }
        ]
      },
      {
        no: 4, id: 'sc-todo-guidance', name: '部门指导', level: 'ui', go: '#/p/p-todo/dept/engineering',
        setup: [],
        steps: [
          {
            delay: 1200,
            event: {
              type: 'department_guidance_received', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '用户给工程部门写指导：逾期提醒要写明截止日期与超期天数', payload: { guidance_id: 'g-todo-due-1', department: 'engineering', version: 1 }
            },
            patch: [{
              path: 'runs[id=r-todo-due].guidance', push: {
                id: 'g-todo-due-1', department: 'engineering', version: 1,
                text: '逾期提醒要写明截止日期与超期天数，不要只显示红点；跨午夜的情况要有测试。',
                status: 'received', response: null, at: '2026-09-29T15:30:00+08:00'
              }
            }]
          },
          {
            delay: 1400,
            event: {
              type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '工程部门在下一次安全激活中打开信箱里的指导', payload: {}
            },
            patch: []
          },
          {
            delay: 1400,
            event: {
              type: 'department_guidance_applied', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '指导进入工程的输入：经理把它转给中心角色', payload: { guidance_id: 'g-todo-due-1' }
            },
            patch: [{ path: 'runs[id=r-todo-due].guidance[id=g-todo-due-1].status', value: 'in_input' }]
          },
          {
            delay: 1400,
            event: {
              type: 'context_assembled', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '工程装配上下文：PRD r1 与指导 g-todo-due-1', payload: {}
            },
            patch: []
          },
          {
            delay: 1200,
            event: {
              type: 'model_requested', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '工程部门按指导更新计划', payload: {}
            },
            patch: []
          },
          {
            delay: 1400,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', tool: 'edit_range',
              label: '工程部门按指导修改逾期提醒的文案', payload: {}
            },
            patch: [{
              path: 'runs[id=r-todo-due].actions', push: {
                id: 'a-todo-due-8', department: 'engineering', role: null, tool: 'edit_range',
                summary: '按指导修改逾期提醒文案：写明截止日期与超期天数', input: '部门指导 g-todo-due-1', state: 'done', receipt: null,
                before: 'app.js @ b7e91d4', after: 'app.js @ d5c40aa', machine_id: 'm-host', at: '2026-09-29T15:30:00+08:00'
              }
            }]
          },
          {
            delay: 1200,
            event: {
              type: 'model_attempt_finished', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '工程完成修改与自测', payload: {}
            },
            patch: []
          },
          {
            delay: 1600,
            event: {
              type: 'department_guidance_responded', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '工程回应指导：已加入计划与用例', payload: { guidance_id: 'g-todo-due-1' }
            },
            patch: [
              { path: 'runs[id=r-todo-due].guidance[id=g-todo-due-1].status', value: 'completed' },
              { path: 'runs[id=r-todo-due].guidance[id=g-todo-due-1].response', value: '已按指导处理：提醒写明截止日期与超期天数，并补了跨午夜的用例（见 PLAN r2，npm_test 18 条通过）。' },
              {
                path: 'materials', push: {
                  id: 'm-todo-due-l2', project_id: 'p-todo', work_item_id: 'w-todo-due', kind: 'plan', version: 2,
                  title: 'PLAN r2（按指导）', at: '2026-09-29T15:30:00+08:00', files: null, verdict: null,
                  goal: '按用户指导补文案与跨午夜用例',
                  text: '1. 逾期提醒写明截止日期与超期天数\n2. 补当天到期的跨午夜用例\n3. 运行 npm_test 回归'
                }
              }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'plan_accepted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '工程提交更新后的 PLAN r2，主机接纳', payload: { material_id: 'm-todo-due-l2' }
            },
            patch: [{ path: 'runs[id=r-todo-due].elapsed_sec', value: 102000 }]
          }
        ]
      },
      {
        no: 14, id: 'sc-todo-trial', name: '质检试用网页', level: '3.2D', go: '#/p/p-todo/dept/quality',
        setup: [],
        steps: [
          {
            delay: 1200,
            event: {
              type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '质检部门坐到试用台前，继续试用', payload: {}
            },
            patch: []
          },
          {
            delay: 1400,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality', tool: 'browser_navigate',
              label: '打开预览服务上的待办清单页面', payload: {}
            },
            patch: []
          },
          {
            delay: 1400, at: '2026-09-29T15:31:00+08:00',
            event: {
              type: 'x_trial_step', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '试用第 3 步：标记「续费域名」为已完成，任务显示划线',
              payload: { step: 3, screenshot: 'todo-trial-4.png', text: '任务显示已完成' }
            },
            patch: [{
              path: 'runs[id=r-todo-due].trials', push: {
                step: 3, at: '2026-09-29T15:31:00+08:00', action: '标记「续费域名」为已完成', screenshot: 'todo-trial-4.png',
                text_lines: ['任务：续费域名（已完成）', '标题显示划线'], requirement: '标记完成'
              }
            }]
          },
          {
            delay: 1200,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality', tool: 'browser_click',
              label: '点击任务旁的「完成」按钮', payload: {}
            },
            patch: []
          },
          {
            delay: 1400, at: '2026-09-29T15:32:00+08:00',
            event: {
              type: 'x_trial_step', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '试用第 4 步：删除任务「整理房间」，任务从列表消失',
              payload: { step: 4, screenshot: 'todo-trial-5.png', text: '任务从列表消失' }
            },
            patch: [{
              path: 'runs[id=r-todo-due].trials', push: {
                step: 4, at: '2026-09-29T15:32:00+08:00', action: '删除任务「整理房间」', screenshot: 'todo-trial-5.png',
                text_lines: ['删除按钮：整理房间', '列表中不再显示'], requirement: '删除任务'
              }
            }]
          },
          {
            delay: 1200,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality', tool: 'browser_click',
              label: '点击任务旁的「删除」按钮', payload: {}
            },
            patch: []
          },
          {
            delay: 1600, at: '2026-09-29T15:33:00+08:00',
            event: {
              type: 'x_trial_step', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '试用第 5 步：检查逾期提醒，已过截止日期的任务显示提醒',
              payload: { step: 5, screenshot: 'todo-trial-6.png', text: '任务「交物业费」显示「已超过截止日期 2026-09-27」' }
            },
            patch: [{
              path: 'runs[id=r-todo-due].trials', push: {
                step: 5, at: '2026-09-29T15:33:00+08:00', action: '检查逾期提醒：已过截止日期的任务显示提醒', screenshot: 'todo-trial-6.png',
                text_lines: ['任务：交物业费（截止 2026-09-27）', '提醒：已超过截止日期 2026-09-27'], requirement: '逾期提醒'
              }
            }]
          },
          {
            delay: 1200,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality', tool: 'browser_snapshot',
              label: '读取逾期任务的列表结构与截图，作为证据', payload: {}
            },
            patch: []
          }
        ]
      },
      {
        no: 18, id: 'sc-todo-roles', name: '部门内多角色', level: 'S5', go: '#/p/p-todo/dept/engineering',
        setup: [],
        steps: [
          {
            delay: 1200,
            event: {
              type: 'department_activated', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '工程经理接手「增加截止日期与逾期提醒」', payload: {}
            },
            patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-manager].status', value: 'working' }]
          },
          {
            delay: 1400,
            event: {
              type: 'x_role_task_assigned', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-architect',
              label: '工程经理把「起草 PLAN」任务卡递给工程架构师', payload: { to: 'eng-architect', task: '起草 PLAN r1：截止日期显示与逾期判定' }
            },
            patch: [
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-architect].status', value: 'assigned' },
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-architect].task', value: '起草 PLAN r1：截止日期显示与逾期判定' }
            ]
          },
          {
            delay: 1200,
            event: {
              type: 'model_requested', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-architect',
              label: '工程架构师摊开图纸卷，起草计划', payload: {}
            },
            patch: [
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-architect].status', value: 'working' },
              { path: 'runs[id=r-todo-due].ledger.engineering.items[id=P-1].status', value: 'working' }
            ]
          },
          {
            delay: 1500,
            event: {
              type: 'x_role_result_returned', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-architect',
              label: '工程架构师把 PLAN r1 草案交回经理', payload: { to: 'eng-architect' }
            },
            patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-architect].status', value: 'returned' }]
          },
          {
            delay: 1400,
            event: {
              type: 'x_review_recorded', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-reviewer',
              label: '工程审查者审查 PLAN：通过', payload: { verdict: 'passed', text: '计划项与 PRD 的 5 条验收条件对应，通过。' }
            },
            patch: [
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].status', value: 'returned' },
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].task', value: 'PLAN 审查通过' }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'x_role_task_assigned', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead',
              label: '工程经理把实现任务递给主程：P-1 的时区换算与 P-2 的显示', payload: { to: 'eng-lead', task: '实现 P-1 与 P-2' }
            },
            patch: [
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'assigned' },
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].task', value: '实现 P-1 与 P-2' }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead', tool: 'edit_range',
              label: '主程按区间编辑 app.js：截止日期显示与逾期标记', payload: {}
            },
            patch: [
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'working' },
              {
                path: 'runs[id=r-todo-due].actions', push: {
                  id: 'a-todo-due-2', department: 'engineering', role: 'eng-lead', tool: 'edit_range',
                  summary: '按区间编辑 app.js：增加截止日期输入与逾期标记', input: 'PLAN r1 第 1、2 项', state: 'done', receipt: null,
                  before: 'app.js @ a1c3f20', after: 'app.js @ b7e91d4（第 1 次交回）', machine_id: 'm-host', at: '2026-09-28T11:40:00+08:00'
                }
              }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'x_explorer_fetch', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-explorer',
              label: '工程探索者取回 date-fns 的说明，确认日期比较的封装方式',
              payload: { tool: '网络取回', target: 'https://registry.npmjs.org/date-fns', result: '已取回 · 12 KB' }
            },
            patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-explorer].status', value: 'away' }]
          },
          {
            delay: 1200,
            event: {
              type: 'x_role_result_returned', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-explorer',
              label: '工程探索者交回发现：按本地日历日期比较最稳妥', payload: { to: 'eng-explorer' }
            },
            patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-explorer].status', value: 'returned' }]
          },
          {
            delay: 1600,
            event: {
              type: 'x_review_recorded', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-reviewer',
              label: '工程审查者退回 P-1：逾期判定用 UTC 毫秒比较', payload: { verdict: 'returned', text: '逾期判定用 UTC 毫秒比较，跨午夜后当天到期的任务会提前显示逾期；改为按本地日历日期比较。' }
            },
            patch: [
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].status', value: 'returned' },
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].task', value: 'P-1 退回 1 次' },
              { path: 'runs[id=r-todo-due].ledger.engineering.items[id=P-1].status', value: 'working' }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'x_role_task_assigned', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead',
              label: '工程经理把退回意见转给主程：改为本地日历日期比较', payload: { to: 'eng-lead', task: '按审查意见改为本地日历日期比较' }
            },
            patch: [
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'assigned' },
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].task', value: '按审查意见改为本地日历日期比较' }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead', tool: 'edit_range',
              label: '主程改为按本地日历日期比较，并补跨午夜的用例', payload: {}
            },
            patch: [
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'working' },
              {
                path: 'runs[id=r-todo-due].actions', push: {
                  id: 'a-todo-due-3', department: 'engineering', role: 'eng-lead', tool: 'edit_range',
                  summary: '按区间编辑 app.js：逾期判定改为按本地日历日期比较', input: '审查意见（第 1 次退回）', state: 'done', receipt: null,
                  before: 'app.js @ b7e91d4（第 1 次交回前）', after: 'app.js @ b7e91d4', machine_id: 'm-host', at: '2026-09-29T12:10:00+08:00'
                }
              }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'tool_started', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-lead', tool: 'run_command',
              label: '主程执行登记命令 npm_test，退出 0', payload: { exit_code: 0, timed_out: false }
            },
            patch: [
              { path: 'runs[id=r-todo-due].ledger.engineering.items[id=P-3].result', value: '退出 0 · 16 条通过' },
              {
                path: 'runs[id=r-todo-due].actions', push: {
                  id: 'a-todo-due-4', department: 'engineering', role: 'eng-lead', tool: 'run_command',
                  summary: '执行登记命令 npm_test', input: 'PLAN r1 第 3 项：自测与回归', state: 'done',
                  receipt: { command: 'npm_test', argv: ['npm', 'test'], exit_code: 0, output: '16 passing (0.5s)', truncated: false, timed_out: false, duration_ms: 1810, snapshot: 'ws-b7e91d4' },
                  before: '工作区 b7e91d4', after: '工作区 b7e91d4（未改动）', machine_id: 'm-host', at: '2026-09-29T12:22:00+08:00'
                }
              }
            ]
          },
          {
            delay: 1600,
            event: {
              type: 'x_review_recorded', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-reviewer',
              label: '工程审查者复审 P-1：通过', payload: { verdict: 'passed', text: '本地日期比较与跨午夜用例都符合 PRD。' }
            },
            patch: [
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].status', value: 'returned' },
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-reviewer].task', value: 'P-1 退回 1 次后通过' },
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-lead].status', value: 'returned' },
              { path: 'runs[id=r-todo-due].ledger.engineering.items[id=P-1].status', value: 'returned' }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'proposal_submitted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering', role: 'eng-manager',
              label: '工程经理代表部门提交交付说明', payload: {}
            },
            patch: [{ path: 'runs[id=r-todo-due].roles.engineering[id=eng-manager].status', value: 'working' }]
          },
          {
            delay: 1400,
            event: {
              type: 'delivery_accepted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'engineering',
              label: '主机接纳交付 r1（截止日期与逾期提醒）', payload: {}
            },
            patch: [
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-manager].status', value: 'returned' },
              { path: 'runs[id=r-todo-due].roles.engineering[id=eng-manager].task', value: '交付 r1 已提交' },
              { path: 'runs[id=r-todo-due].elapsed_sec', value: 100000 }
            ]
          }
        ]
      }
    ]
  });
})();
