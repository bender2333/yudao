// 家庭温湿度监测服务。种子是出现时的状态，历史补丁收到现在。
(function () {
  'use strict';
  const Y8 = window.Y8;
  const P = 'p-sensor';

  function modelOf(definition, source, unusable) {
    return {
      definition: definition,
      connection: definition.split('/')[0],
      protocol: 'Responses',
      source: source,
      level: definition.indexOf('kimi') >= 0 ? 'high' : null,
      sent_level: definition.indexOf('kimi') >= 0 ? 'high' : 'medium',
      unusable: unusable || null
    };
  }

  function attempt(fields) {
    return Object.assign({
      n: 1, of: 1, status: 'succeeded', duration_ms: 26000,
      provider: 'opencode-go-responses', error: null, semantic_units: [],
      usage: { input: 7600, output: 1400, cache_read: 0, total: 9000, cost: null }
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
    const row = (id, name, kind) => ({
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

  function emptyMessages() {
    return { product: [], engineering: [], quality: [], operations: [] };
  }

  function emptyContexts() {
    return { product: [], engineering: [], quality: [] };
  }

  function blankPrompts() {
    return {
      product: { config_version: 1, request_version: 1, text: '' },
      engineering: { config_version: 1, request_version: 1, text: '' },
      quality: { config_version: 1, request_version: 1, text: '' }
    };
  }

  function ev(fields) {
    return Object.assign({
      project_id: P, work_item_id: null, run_id: null, department: null, role: null,
      actor: 'system', payload: {}, patch: []
    }, fields);
  }

  // 场景中新建的修复事项与 run（与种子中的字段一致）
  function repairItem(id, title, bornAt) {
    return {
      id: id, project_id: P, title: title, color_index: 4, kind: 'repair',
      status: 'queued', queue_reason: 'project', queue_pos: 0, run_id: id.replace('w-', 'r-'),
      version: 1, created_at: bornAt, born_at: bornAt
    };
  }

  function repairRun(id, workItemId, bornAt) {
    return {
      id: id, work_item_id: workItemId, project_id: P, yudao_version: '0.8.0',
      phase: 'QUEUED', department: null, last_department: null, cycle: 0,
      started_at: bornAt, elapsed_sec: 0, limit_sec: 7200,
      waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
      recovery: { state: 'running', reason: '排队中', unusable: null, last_confirmed: null, owner: null, late_results: [], verifications: [], unfinished: [], limits: { elapsed_sec: 0, limit_sec: 7200, activations: 0, model_steps: 0, retries: 0 }, auto_resumed_at: null },
      born_at: bornAt,
      inputs: [], flow: [], requests: [], guidance: [],
      messages: emptyMessages(), actions: [], contexts: emptyContexts(),
      prompts: blankPrompts(), compactions: [],
      effective_model: {
        product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
        engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
        quality: modelOf('opencode-go-responses/glm-5', '项目设置', null)
      },
      roles: { level: 'S5', product: [], engineering: [], quality: [] },
      ledger: ledger({}),
      attempts: [], source: null
    };
  }

  function decision(id, kind, materials, view, bornAt, extra) {
    return Object.assign({
      id: id, kind: kind, project_id: P, work_item_id: null, run_id: null,
      status: 'waiting', issued_at: bornAt, born_at: bornAt, version: 1, level: 'S4',
      blocks: null, materials: materials, view: view, answer: null,
      options: [{ id: 'ack', label: '知道了', kind: 'primary' }]
    }, extra || {});
  }

  Y8.data.define({
    seed: {
      projects: [{
        id: P, name: '家庭温湿度监测服务',
        goal: '在客厅树莓派上长期运行：读取 DHT22 的温湿度，每分钟写入 SQLite，网页显示当前值与曲线，由 systemd 管理并输出结构化日志。',
        pinned: false, archived: false, version: 1, source: 'idea',
        created_at: '2026-09-10T09:00:00+08:00',
        last_activity_at: '2026-09-10T09:00:00+08:00',
        adoptions: [{ version: 'r1', work_item_id: 'w-sensor-base', summary: '采集与网页展示', adopted_at: '2026-09-12T15:30:00+08:00' }]
      }],
      work_items: [
        {
          id: 'w-sensor-base', project_id: P, title: '采集与网页展示', color_index: 0, kind: 'request',
          status: 'adopted', queue_reason: null, queue_pos: null, run_id: 'r-sensor-base', version: 1,
          created_at: '2026-09-10T09:10:00+08:00'
        },
        {
          id: 'w-sensor-chart', project_id: P, title: '增加 7 天曲线', color_index: 1, kind: 'request',
          status: 'not_started', queue_reason: null, queue_pos: null, run_id: 'r-sensor-chart', version: 1,
          created_at: '2026-09-28T09:00:00+08:00', born_at: '2026-09-28T09:00:00+08:00', until: 'S4'
        },
        {
          id: 'w-sensor-fix1', project_id: P, title: '修复传感器读取超时', color_index: 2, kind: 'repair',
          status: 'queued', queue_reason: 'project', queue_pos: 0, run_id: 'r-sensor-fix1', version: 1,
          created_at: '2026-09-28T02:30:00+08:00', born_at: '2026-09-28T02:30:00+08:00', level: 'S4'
        },
        {
          id: 'w-sensor-fix2', project_id: P, title: '修复夜间写入数据库失败', color_index: 3, kind: 'repair',
          status: 'queued', queue_reason: 'project', queue_pos: 0, run_id: 'r-sensor-fix2', version: 1,
          created_at: '2026-09-29T12:35:00+08:00', born_at: '2026-09-29T12:35:00+08:00', level: 'S4'
        }
      ],
      runs: [
        {
          id: 'r-sensor-base', work_item_id: 'w-sensor-base', project_id: P, yudao_version: '0.8.0',
          phase: 'DONE', department: null, last_department: 'quality', cycle: 2,
          started_at: '2026-09-10T09:20:00+08:00', elapsed_sec: 3860, limit_sec: 7200,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: {
            state: 'running', reason: '已完成并采纳', unusable: null,
            last_confirmed: { seq: 22, text: 'r2 的质检放行并采纳' },
            owner: null, late_results: [], verifications: [], unfinished: [],
            limits: { elapsed_sec: 3860, limit_sec: 7200, activations: 7, model_steps: 12, retries: 1 },
            auto_resumed_at: null
          },
          inputs: [
            { version: 1, kind: 'user', progress: 'accepted', at: '2026-09-10T09:10:00+08:00', bytes: 420, text: '树莓派读取 DHT22 的温湿度，每分钟写入 SQLite，网页显示当前值与曲线。' },
            { version: 2, kind: 'user', progress: 'accepted', at: '2026-09-24T08:40:00+08:00', bytes: 260, text: '读取失败重试 3 次；输出结构化日志，每行一条 JSON，运维按这个格式读取；启动时输出版本号。' }
          ],
          flow: [
            { seq: 1, at: '2026-09-10T09:50:00+08:00', from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：每分钟采样、SQLite 写入、网页曲线', status: 'accepted', event_position: null },
            { seq: 2, at: '2026-09-12T14:40:00+08:00', from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r1：reader、store、web 与 systemd 单元', status: 'accepted', event_position: null },
            { seq: 3, at: '2026-09-12T15:30:00+08:00', from: 'quality', to: 'library', kind: 'release', content: '放行 r1：读数误差 ±0.5 摄氏度以内', status: 'accepted', event_position: null },
            { seq: 4, at: '2026-09-24T15:30:00+08:00', from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r2：重试 3 次、结构化日志、版本号输出', status: 'accepted', event_position: null },
            { seq: 5, at: '2026-09-24T16:20:00+08:00', from: 'quality', to: 'library', kind: 'release', content: '放行 r2：日志逐行 JSON，可被运维读取', status: 'accepted', event_position: null }
          ],
          requests: [{
            id: 'q-sensor-dht', from: 'engineering', to: 'product', kind: 'consult',
            question: 'DHT22 接在哪个引脚？采样间隔可以调整吗？', status: 'closed',
            answer: '接 GPIO 4。间隔固定每分钟，不做成可配置。',
            born_at: '2026-09-10T10:05:00+08:00'
          }],
          guidance: [],
          messages: {
            product: [{ seq: 1, at: '2026-09-10T10:20:00+08:00', source: 'self', from: 'product', text: '接 GPIO 4。间隔固定每分钟，不做成可配置。', event_id: null }],
            engineering: [{ seq: 1, at: '2026-09-10T10:05:00+08:00', source: 'self', from: 'engineering', text: 'DHT22 接在哪个引脚？采样间隔可以调整吗？', event_id: null }],
            quality: [{ seq: 1, at: '2026-09-12T15:20:00+08:00', source: 'self', from: 'quality', text: '连续 60 次读数与标准温度计比对，误差都在 ±0.5 摄氏度以内。', event_id: null }],
            operations: []
          },
          actions: [
            {
              id: 'a-sensor-write-store', department: 'engineering', role: 'eng-lead', tool: 'write_file',
              summary: '写入 store.py：SQLite WAL 与每分钟写入', input: 'src/store.py',
              state: 'done', machine_id: 'm-host', at: '2026-09-11T16:20:00+08:00',
              before: '文件不存在', after: '写入 148 行',
              receipt: { command: 'write_file', argv: ['src/store.py'], exit_code: 0, output: '148 lines', truncated: false, timed_out: false, duration_ms: 210, snapshot: 'src/store.py' }
            },
            {
              id: 'a-sensor-pytest', department: 'engineering', role: 'eng-lead', tool: 'run_command',
              summary: '登记命令 pytest', input: 'python -m pytest tests',
              state: 'done', machine_id: 'm-host', at: '2026-09-24T15:10:00+08:00',
              before: '重试与日志测试已写入', after: '6 passed',
              receipt: { command: 'pytest', argv: ['python', '-m', 'pytest', 'tests'], exit_code: 0, output: '6 passed', truncated: false, timed_out: false, duration_ms: 3100, snapshot: 'tests' }
            }
          ],
          contexts: {
            product: [{ id: 'ctx-sbase-p1', at: '2026-09-10T09:22:00+08:00', title: '产品激活 1', attempt_id: 'att-sbase-p1', sources: [{ label: '用户原文', version: 'v1', included: true }] }],
            engineering: [{ id: 'ctx-sbase-e1', at: '2026-09-24T09:10:00+08:00', title: '工程激活 3（v2 增量）', attempt_id: 'att-sbase-e2', sources: [{ label: '当前合同', version: 'PRD r2', included: true }, { label: '已采纳', version: 'r1', included: true }] }],
            quality: [{ id: 'ctx-sbase-q2', at: '2026-09-24T15:40:00+08:00', title: '质检激活 2', attempt_id: 'att-sbase-q2', sources: [{ label: '交付', version: 'r2', included: true }, { label: '当前合同', version: 'PRD r2', included: true }] }]
          },
          prompts: {
            product: { config_version: 1, request_version: 1, text: '采样间隔、存储与网页展示写清；日志格式按运维读取的需要写明。' },
            engineering: { config_version: 1, request_version: 2, text: 'SQLite 用 WAL；读取失败重试 3 次；日志逐行 JSON。' },
            quality: { config_version: 1, request_version: 2, text: '比对读数误差；核对日志每行是合法 JSON。' }
          },
          compactions: [],
          effective_model: {
            product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            quality: modelOf('opencode-go-responses/mimo-v2.5', '部门默认', null)
          },
          roles: roles(null),
          ledger: ledger({
            engineering: {
              items: [
                { id: 'P-1', text: '采集循环与 SQLite 写入', assignee: 'eng-lead', status: 'returned', result: '每分钟写入，WAL 模式' },
                { id: 'P-2', text: '重试 3 次与结构化日志', assignee: 'eng-lead', status: 'returned', result: '日志逐行 JSON，版本号随启动输出' }
              ],
              facts: ['采样间隔固定每分钟，不做成可配置'],
              questions: [],
              progress: [{ cycle: 2, text: '两轮共 3860 秒，流程内完成', stalled: false }]
            },
            quality: {
              items: [{ id: 'Q-1', text: '读数误差与日志格式核验', assignee: 'qa-tester', status: 'returned', result: '全部验收条件通过' }],
              facts: ['连续 60 次读数误差在 ±0.5 摄氏度以内'],
              questions: [],
              progress: [{ cycle: 2, text: '两轮都放行', stalled: false }]
            }
          }),
          attempts: [
            attempt({ id: 'att-sbase-p1', logical_call_id: 'call-sbase-p1', department: 'product', role: 'prod-architect', started_at: '2026-09-10T09:22:00+08:00', requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 3600, output: 1500, cache_read: 0, total: 5100, cost: null } }),
            attempt({ id: 'att-sbase-e2', logical_call_id: 'call-sbase-e2', department: 'engineering', role: 'eng-lead', started_at: '2026-09-24T09:15:00+08:00', duration_ms: 33100, requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 12100, output: 2600, cache_read: 0, total: 14700, cost: null } }),
            attempt({ id: 'att-sbase-q2', logical_call_id: 'call-sbase-q2', department: 'quality', role: 'qa-tester', started_at: '2026-09-24T15:40:00+08:00', requested_model: 'mimo-v2.5', actual_model: 'mimo-v2.5', target: target('mimo-v2.5', '部门默认'), usage: { input: 8200, output: 900, cache_read: 0, total: 9100, cost: null } })
          ],
          source: null
        },
        {
          id: 'r-sensor-chart', work_item_id: 'w-sensor-chart', project_id: P, yudao_version: '0.8.0',
          phase: 'PRODUCT_SPEC', department: null, last_department: null, cycle: 0,
          started_at: '2026-09-28T09:00:00+08:00', elapsed_sec: 0, limit_sec: 7200,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: {
            state: 'running', reason: '运行中', unusable: null,
            last_confirmed: { seq: 6, text: '质检已按 PRD 核对写入间隔，开始检查曲线' },
            owner: { id: '质检部门', since: '2026-09-28T09:40:00+08:00' },
            late_results: [], verifications: [], unfinished: [],
            limits: { elapsed_sec: 2400, limit_sec: 7200, activations: 2, model_steps: 3, retries: 0 },
            auto_resumed_at: null
          },
          born_at: '2026-09-28T09:00:00+08:00', until: 'S4',
          inputs: [{ version: 1, kind: 'user', progress: 'accepted', at: '2026-09-28T09:00:00+08:00', bytes: 190, text: '网页上增加最近 7 天的温湿度曲线，按住小时聚合。' }],
          flow: [
            { seq: 1, at: '2026-09-28T09:15:00+08:00', from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD：7 天窗口、按小时聚合', status: 'accepted', event_position: null },
            { seq: 2, at: '2026-09-28T09:30:00+08:00', from: 'engineering', to: 'quality', kind: 'delivery', content: '交付：曲线页与聚合查询', status: 'accepted', event_position: null }
          ],
          requests: [],
          guidance: [],
          messages: {
            product: [],
            engineering: [{ seq: 1, at: '2026-09-28T09:25:00+08:00', source: 'self', from: 'engineering', text: '曲线用 Canvas 画，先固定 7 天窗口，不做缩放。', event_id: null }],
            quality: [{ seq: 1, at: '2026-09-28T09:40:00+08:00', source: 'self', from: 'quality', text: '开始逐条对照验收条件检查曲线。', event_id: null }],
            operations: []
          },
          actions: [{
            id: 'a-sensor-chart-read', department: 'engineering', role: 'eng-explorer', tool: 'read_file',
            summary: '阅读 store.py 的读写方式', input: 'src/store.py',
            state: 'done', machine_id: 'm-host', at: '2026-09-28T09:20:00+08:00',
            before: '文件未读', after: '按分钟一行，聚合需要按小时分组',
            receipt: { command: 'read_file', argv: ['src/store.py'], exit_code: 0, output: '148 lines', truncated: false, timed_out: false, duration_ms: 160, snapshot: null }
          }],
          contexts: {
            product: [{ id: 'ctx-schart-p1', at: '2026-09-28T09:02:00+08:00', title: '产品激活 1', attempt_id: 'att-schart-p1', sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '已采纳', version: 'r2', included: true }] }],
            engineering: [{ id: 'ctx-schart-e1', at: '2026-09-28T09:16:00+08:00', title: '工程激活 1', attempt_id: 'att-schart-e1', sources: [{ label: '当前合同', version: 'PRD r1', included: true }] }],
            quality: [{ id: 'ctx-schart-q1', at: '2026-09-28T09:40:00+08:00', title: '质检激活 1', attempt_id: 'att-schart-q1', sources: [{ label: '交付', version: 'r1', included: true }, { label: '当前合同', version: 'PRD r1', included: true }] }]
          },
          prompts: {
            product: { config_version: 1, request_version: 1, text: '7 天窗口与按小时聚合写进验收条件。' },
            engineering: { config_version: 1, request_version: 1, text: '曲线只读 store 的读数，不新增写入路径。' },
            quality: { config_version: 1, request_version: 1, text: '核验 7 天窗口的起止与聚合结果。' }
          },
          compactions: [],
          effective_model: {
            product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            quality: modelOf('opencode-go-responses/glm-5', '项目设置', '准入已作废')
          },
          roles: roles({ id: 'qa-tester', status: 'assigned', task: '按 PRD 检查 7 天曲线（模型引用无法使用）' }),
          ledger: ledger({
            quality: {
              items: [{ id: 'Q-1', text: '按验收条件检查 7 天曲线', assignee: 'qa-tester', status: 'working', result: null }],
              facts: [],
              questions: [],
              progress: [{ cycle: 1, text: '模型引用无法使用，检查停在第一步', stalled: true }]
            }
          }),
          attempts: [
            attempt({ id: 'att-schart-p1', logical_call_id: 'call-schart-p1', department: 'product', role: 'prod-architect', started_at: '2026-09-28T09:02:00+08:00', requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 4400, output: 1100, cache_read: 0, total: 5500, cost: null } }),
            attempt({ id: 'att-schart-e1', logical_call_id: 'call-schart-e1', department: 'engineering', role: 'eng-lead', started_at: '2026-09-28T09:18:00+08:00', duration_ms: 29800, requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 10200, output: 2100, cache_read: 0, total: 12300, cost: null } }),
            attempt({ id: 'att-schart-q1', logical_call_id: 'call-schart-q1', department: 'quality', role: 'qa-tester', n: 1, of: 2, status: 'failed', duration_ms: 300, started_at: '2026-09-28T09:40:00+08:00', requested_model: 'glm-5', actual_model: null, error: { category: '准入已作废', code: null, http: null, text: '模型访问定义的准入已作废，请求没有发出' }, target: target('glm-5', '项目设置'), usage: { input: null, output: null, cache_read: null, total: null, cost: null } })
          ],
          source: null
        },
        {
          id: 'r-sensor-fix1', work_item_id: 'w-sensor-fix1', project_id: P, yudao_version: '0.8.0',
          phase: 'QUEUED', department: null, last_department: null, cycle: 0,
          started_at: '2026-09-28T03:05:00+08:00', elapsed_sec: 0, limit_sec: 7200,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: {
            state: 'running', reason: '修复完成，已采纳 r3 并部署',
            unusable: null,
            last_confirmed: { seq: 18, text: '部署 r3 以后 30 分钟没有新的重启记录' },
            owner: null, late_results: [], verifications: [], unfinished: [],
            limits: { elapsed_sec: 4200, limit_sec: 7200, activations: 4, model_steps: 6, retries: 0 },
            auto_resumed_at: null
          },
          born_at: '2026-09-28T02:30:00+08:00', level: 'S4',
          inputs: [{
            version: 1, kind: 'command', progress: 'accepted', at: '2026-09-28T02:30:00+08:00', bytes: 240,
            text: '故障 F-1：树莓派重启后传感器读取超时，服务反复重启。证据：02:05 至 02:14 之间 journal 记录 5 次重启。'
          }],
          flow: [
            { seq: 1, at: '2026-09-28T03:40:00+08:00', from: 'product', to: 'engineering', kind: 'handoff', content: '故障成立：读取超时发生在重启后的第一次采样', status: 'accepted', event_position: null },
            { seq: 2, at: '2026-09-28T05:20:00+08:00', from: 'engineering', to: 'quality', kind: 'delivery', content: '交付：重启后延迟首次采样，并加大读取超时到 3 秒', status: 'accepted', event_position: null },
            { seq: 3, at: '2026-09-28T06:20:00+08:00', from: 'quality', to: 'operations', kind: 'release', content: '核验通过，交运维部署', status: 'accepted', event_position: null }
          ],
          requests: [],
          guidance: [],
          messages: {
            product: [],
            engineering: [{ seq: 1, at: '2026-09-28T04:50:00+08:00', source: 'self', from: 'engineering', text: '重启后先等 5 秒再读，超时放宽到 3 秒重试。', event_id: null }],
            quality: [{ seq: 1, at: '2026-09-28T06:10:00+08:00', source: 'self', from: 'quality', text: '连续 20 次重启后采样都成功。', event_id: null }],
            operations: [{ seq: 1, at: '2026-09-28T06:42:00+08:00', source: 'self', from: 'operations', text: '备份后部署 r3，进入 24 小时观察窗口。', event_id: null }]
          },
          actions: [
            {
              id: 'a-sensor-fix1-journal', department: 'engineering', role: 'eng-explorer', tool: 'run_command',
              summary: '读取 journal 的重启记录', input: 'journalctl -u sensor --since "02:00"',
              state: 'done', machine_id: 'm-pi', at: '2026-09-28T03:20:00+08:00',
              before: '尚未读取', after: '5 次重启，都在重启后第一次采样超时',
              receipt: { command: 'run_command', argv: ['journalctl', '-u', 'sensor'], exit_code: 0, output: '5 restarts, timeout on first read', truncated: false, timed_out: false, duration_ms: 900, snapshot: null }
            },
            {
              id: 'a-sensor-fix1-edit', department: 'engineering', role: 'eng-lead', tool: 'edit_range',
              summary: '重启后延迟首次采样', input: 'src/reader.py',
              state: 'done', machine_id: 'm-host', at: '2026-09-28T04:40:00+08:00',
              before: '首次采样立即执行', after: '等待 5 秒；超时放宽到 3 秒',
              receipt: { command: 'edit_range', argv: ['src/reader.py'], exit_code: 0, output: '2 hunks', truncated: false, timed_out: false, duration_ms: 240, snapshot: 'src/reader.py' }
            },
            {
              id: 'a-sensor-fix1-check', department: 'engineering', role: 'eng-lead', tool: 'run_command',
              summary: '登记命令 deploy_check', input: 'python scripts/deploy_check.py',
              state: 'done', machine_id: 'm-host', at: '2026-09-28T05:10:00+08:00',
              before: '修复已写入', after: '检查通过',
              receipt: { command: 'deploy_check', argv: ['python', 'scripts/deploy_check.py'], exit_code: 0, output: 'ok', truncated: false, timed_out: false, duration_ms: 1500, snapshot: null }
            }
          ],
          contexts: {
            product: [{ id: 'ctx-sfix1-p1', at: '2026-09-28T03:06:00+08:00', title: '产品激活 1', attempt_id: 'att-sfix1-p1', sources: [{ label: '故障证据', version: 'F-1', included: true }, { label: '当前合同', version: 'PRD r2', included: true }] }],
            engineering: [{ id: 'ctx-sfix1-e1', at: '2026-09-28T03:42:00+08:00', title: '工程激活 1', attempt_id: 'att-sfix1-e1', sources: [{ label: '故障证据', version: 'F-1', included: true }, { label: '当前合同', version: 'PRD r2', included: true }] }],
            quality: [{ id: 'ctx-sfix1-q1', at: '2026-09-28T05:22:00+08:00', title: '质检激活 1', attempt_id: 'att-sfix1-q1', sources: [{ label: '交付', version: 'r3', included: true }] }]
          },
          prompts: {
            product: { config_version: 1, request_version: 2, text: '判断故障是否成立；修复范围只限读取超时。' },
            engineering: { config_version: 1, request_version: 2, text: '故障修复引用观察证据；改动保持最小。' },
            quality: { config_version: 1, request_version: 2, text: '用重启后采样复核，覆盖 20 次。' }
          },
          compactions: [],
          effective_model: {
            product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            quality: modelOf('opencode-go-responses/mimo-v2.5', '部门默认', null)
          },
          roles: roles(null),
          ledger: ledger({
            engineering: {
              items: [{ id: 'P-1', text: '定位重启后的首次读取超时', assignee: 'eng-explorer', status: 'returned', result: 'journal 证据与代码一致' },
                { id: 'P-2', text: '重启后延迟采样并放宽超时', assignee: 'eng-lead', status: 'returned', result: 'deploy_check 通过' }],
              facts: ['读取超时出现在重启后的第一次采样'],
              questions: [],
              progress: [{ cycle: 1, text: '一次修复完成', stalled: false }]
            }
          }),
          attempts: [
            attempt({ id: 'att-sfix1-p1', logical_call_id: 'call-sfix1-p1', department: 'product', role: 'prod-architect', started_at: '2026-09-28T03:06:00+08:00', requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 3800, output: 1200, cache_read: 0, total: 5000, cost: null } }),
            attempt({ id: 'att-sfix1-e1', logical_call_id: 'call-sfix1-e1', department: 'engineering', role: 'eng-lead', started_at: '2026-09-28T03:42:00+08:00', duration_ms: 35200, requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 9900, output: 2400, cache_read: 0, total: 12300, cost: null } }),
            attempt({ id: 'att-sfix1-q1', logical_call_id: 'call-sfix1-q1', department: 'quality', role: 'qa-tester', started_at: '2026-09-28T05:22:00+08:00', requested_model: 'mimo-v2.5', actual_model: 'mimo-v2.5', target: target('mimo-v2.5', '部门默认'), usage: { input: 6900, output: 800, cache_read: 0, total: 7700, cost: null } })
          ],
          source: null
        },
        {
          id: 'r-sensor-fix2', work_item_id: 'w-sensor-fix2', project_id: P, yudao_version: '0.8.0',
          phase: 'QUEUED', department: null, last_department: null, cycle: 0,
          started_at: '2026-09-29T12:40:00+08:00', elapsed_sec: 0, limit_sec: 7200,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: {
            state: 'running', reason: '运行中', unusable: null,
            last_confirmed: { seq: 5, text: '修复范围已定：夜间并发写入改为单写者队列' },
            owner: { id: '工程部门', since: '2026-09-29T12:50:00+08:00' },
            late_results: [], verifications: [], unfinished: [],
            limits: { elapsed_sec: 900, limit_sec: 7200, activations: 2, model_steps: 2, retries: 1 },
            auto_resumed_at: null
          },
          born_at: '2026-09-29T12:35:00+08:00', level: 'S4',
          inputs: [{
            version: 1, kind: 'command', progress: 'accepted', at: '2026-09-29T12:35:00+08:00', bytes: 210,
            text: '故障 F-2：夜间写入数据库失败。证据：01:10 至 12:20 之间 journal 记录 14 次 database is locked。'
          }],
          flow: [
            { seq: 1, at: '2026-09-29T12:50:00+08:00', from: 'product', to: 'engineering', kind: 'handoff', content: '故障成立：夜间上传任务与采样写入并发', status: 'accepted', event_position: null }
          ],
          requests: [],
          guidance: [],
          messages: {
            product: [],
            engineering: [{ seq: 1, at: '2026-09-29T12:50:00+08:00', source: 'self', from: 'engineering', text: '把写入改成单写者队列，等模型服务恢复后继续。', event_id: null }],
            quality: [],
            operations: []
          },
          actions: [{
            id: 'a-sensor-fix2-journal', department: 'engineering', role: 'eng-explorer', tool: 'run_command',
            summary: '读取 journal 的锁表记录', input: 'journalctl -u sensor --since "01:00"',
            state: 'done', machine_id: 'm-pi', at: '2026-09-29T12:45:00+08:00',
            before: '尚未读取', after: '14 次 database is locked，集中在夜间上传时段',
            receipt: { command: 'run_command', argv: ['journalctl', '-u', 'sensor'], exit_code: 0, output: '14 database is locked', truncated: false, timed_out: false, duration_ms: 800, snapshot: null }
          }],
          contexts: {
            product: [{ id: 'ctx-sfix2-p1', at: '2026-09-29T12:36:00+08:00', title: '产品激活 1', attempt_id: 'att-sfix2-p1', sources: [{ label: '故障证据', version: 'F-2', included: true }, { label: '当前合同', version: 'PRD r2', included: true }] }],
            engineering: [{ id: 'ctx-sfix2-e1', at: '2026-09-29T12:50:00+08:00', title: '工程激活 1', attempt_id: 'att-sfix2-e1', sources: [{ label: '故障证据', version: 'F-2', included: true }] }],
            quality: []
          },
          prompts: {
            product: { config_version: 1, request_version: 2, text: '判断故障是否成立；修复范围只限写入并发。' },
            engineering: { config_version: 1, request_version: 2, text: '写入改单写者队列；不改变对外格式。' },
            quality: { config_version: 1, request_version: 2, text: '复核夜间写入不再失败。' }
          },
          compactions: [],
          effective_model: {
            product: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            engineering: modelOf('opencode-go-responses/kimi-k2.6', '部门默认', null),
            quality: modelOf('opencode-go-responses/mimo-v2.5', '部门默认', null)
          },
          roles: roles({ id: 'eng-lead', status: 'working', task: '等待模型服务恢复后继续修复夜间写入失败' }),
          ledger: ledger({
            engineering: {
              items: [{ id: 'P-1', text: '写入改为单写者队列', assignee: 'eng-lead', status: 'working', result: null }],
              facts: ['锁表只出现在夜间上传与采样写入并发时'],
              questions: [],
              progress: [{ cycle: 1, text: '等待模型服务恢复', stalled: false }]
            }
          }),
          attempts: [
            attempt({ id: 'att-sfix2-p1', logical_call_id: 'call-sfix2-p1', department: 'product', role: 'prod-architect', started_at: '2026-09-29T12:36:00+08:00', requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 3500, output: 1000, cache_read: 0, total: 4500, cost: null } }),
            attempt({ id: 'att-sfix2-e1', logical_call_id: 'call-sfix2-e1', department: 'engineering', role: 'eng-lead', started_at: '2026-09-29T12:50:00+08:00', requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6', target: target('kimi-k2.6', '部门默认'), usage: { input: 8100, output: 1500, cache_read: 0, total: 9600, cost: null } }),
            attempt({ id: 'att-sfix2-e2', logical_call_id: 'call-sfix2-e1', department: 'engineering', role: 'eng-lead', n: 1, of: 3, status: 'failed', duration_ms: 1500, started_at: '2026-09-29T13:05:00+08:00', requested_model: 'kimi-k2.6', actual_model: null, error: { category: '上游服务错误', code: '503', http: 503, text: '上游返回 503，稍后重试' }, target: target('kimi-k2.6', '部门默认'), usage: { input: null, output: null, cache_read: null, total: null, cost: null } })
          ],
          source: null
        }
      ],
      decisions: [
        {
          id: 'd-sensor-glm', kind: 'waiting_resume', project_id: P,
          work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart',
          status: 'waiting', issued_at: '2026-09-28T09:40:00+08:00', born_at: '2026-09-28T09:40:00+08:00',
          version: 1, level: 'ui', until: 'S4',
          blocks: { scope: 'run', work_item_id: 'w-sensor-chart', queued_behind: null },
          materials: {
            department: 'quality', model: 'glm-5', problem: '准入已作废',
            links: ['#/sys/models', '#/p/p-sensor/settings']
          },
          view: '#/p/p-sensor/w/w-sensor-chart/recovery',
          answer: null,
          options: [
            {
              id: 'continue', label: '继续执行', kind: 'primary', requires: 'model_ok',
              events: [{
                type: 'department_activated', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality',
                label: '配置已修复，质检继续检查 7 天曲线',
                payload: {},
                patch: [
                  { path: 'runs[id=r-sensor-chart].recovery.state', value: 'running' },
                  { path: 'runs[id=r-sensor-chart].recovery.reason', value: '配置已修复，继续执行' },
                  { path: 'work_items[id=w-sensor-chart].status', value: 'in_progress' }
                ]
              }]
            },
            {
              id: 'stop', label: '停止事项', kind: 'danger',
              events: [{
                type: 'run_failed', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart',
                label: '用户停止 7 天曲线事项',
                payload: { reason: 'stopped_by_user' },
                patch: [
                  { path: 'work_items[id=w-sensor-chart].status', value: 'stopped' },
                  { path: 'runs[id=r-sensor-chart].phase', value: 'FAILED' },
                  { path: 'runs[id=r-sensor-chart].stop_reason', value: { code: 'stopped_by_user', text: '用户在待恢复中停止事项' } },
                  { path: 'runs[id=r-sensor-chart].recovery.state', value: 'terminated' }
                ]
              }]
            }
          ]
        },
        {
          id: 'd-sensor-wait', kind: 'provider_wait', project_id: P,
          work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2',
          status: 'waiting', issued_at: '2026-09-29T13:05:00+08:00', born_at: '2026-09-29T13:05:00+08:00',
          version: 1, level: 'S4',
          blocks: null,
          materials: {
            department: 'engineering', provider: 'opencode-go-responses',
            category: '上游返回 503', next_retry_at: '2026-09-29T15:42:00+08:00'
          },
          view: '#/p/p-sensor/w/w-sensor-fix2/overview',
          answer: null,
          options: [
            { id: 'ack', label: '知道了', kind: 'primary', events: [] },
            {
              id: 'stop', label: '停止事项', kind: 'danger',
              events: [{
                type: 'run_failed', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2',
                label: '用户停止夜间写入修复事项',
                payload: { reason: 'stopped_by_user' },
                patch: [
                  { path: 'work_items[id=w-sensor-fix2].status', value: 'stopped' },
                  { path: 'runs[id=r-sensor-fix2].phase', value: 'FAILED' },
                  { path: 'runs[id=r-sensor-fix2].stop_reason', value: { code: 'stopped_by_user', text: '用户在等待模型服务时停止事项' } },
                  { path: 'runs[id=r-sensor-fix2].waiting_provider', value: null }
                ]
              }]
            }
          ]
        }
      ],
      materials: [
        {
          id: 'm-sensor-intend', project_id: P, work_item_id: null, kind: 'intend', version: 1,
          title: '立项：家庭温湿度监测服务', at: '2026-09-10T09:00:00+08:00',
          text: '在客厅树莓派上做温湿度监测：读取 DHT22，每分钟写入 SQLite，网页显示当前值与曲线。'
        },
        {
          id: 'm-sensor-prd', project_id: P, work_item_id: 'w-sensor-base', kind: 'prd', version: 1,
          title: 'PRD r1 采集与网页展示', at: '2026-09-10T09:45:00+08:00',
          text: '树莓派读取 DHT22（GPIO 4），每分钟采样一次，写入 SQLite（表 readings：at、temperature、humidity）。网页显示当前值与最近曲线。服务由 systemd 管理，开机自启。\n验收条件：读数与标准温度计的误差在 ±0.5 摄氏度以内；断网不影响写入；每分钟恰好一行记录。\n非目标：告警、远程访问、数据导出。'
        },
        {
          id: 'm-sensor-plan', project_id: P, work_item_id: 'w-sensor-base', kind: 'plan', version: 1,
          title: 'PLAN r1', at: '2026-09-10T10:40:00+08:00',
          text: '1. reader.py 采样循环（每分钟）\n2. store.py SQLite 写入（WAL）\n3. web.py 当前值与曲线\n4. deploy/sensor.service\n5. pytest 覆盖误差与写入频率'
        },
        {
          id: 'm-sensor-delivery', project_id: P, work_item_id: 'w-sensor-base', kind: 'delivery', version: 1,
          title: '交付 r1', at: '2026-09-12T14:40:00+08:00',
          files: [
            { path: 'src/reader.py', bytes: 1980 },
            { path: 'src/store.py', bytes: 1480 },
            { path: 'src/web.py', bytes: 2360 },
            { path: 'deploy/sensor.service', bytes: 420 }
          ],
          text: '完成计划 1 至 5。读数误差 +/-0.5 摄氏度以内；每分钟一行；断网时写入继续。'
        },
        {
          id: 'm-sensor-qa', project_id: P, work_item_id: 'w-sensor-base', kind: 'qa', version: 1,
          title: '质检结论 r1', at: '2026-09-12T15:25:00+08:00', verdict: 'release',
          text: '放行。连续 60 次读数与标准温度计比对，误差都在 ±0.5 摄氏度以内；拔掉网线 10 分钟，写入没有中断。'
        },
        {
          id: 'm-sensor-prd-v2', project_id: P, work_item_id: 'w-sensor-base', kind: 'prd', version: 2,
          title: 'PRD r2 增量：可运维性', at: '2026-09-24T08:50:00+08:00',
          text: '在 r1 之上增量：读取失败重试 3 次，仍失败则记一条错误日志；输出结构化日志，每行一条 JSON（字段：time、level、event），运维按这个格式读取；启动时输出版本号。其余要求不变。'
        },
        {
          id: 'm-sensor-plan-v2', project_id: P, work_item_id: 'w-sensor-base', kind: 'plan', version: 2,
          title: 'PLAN r2', at: '2026-09-24T09:05:00+08:00',
          text: '1. reader.py 重试 3 次\n2. 日志改逐行 JSON\n3. 启动输出版本号\n4. pytest 覆盖重试与日志格式'
        },
        {
          id: 'm-sensor-delivery-v2', project_id: P, work_item_id: 'w-sensor-base', kind: 'delivery', version: 2,
          title: '交付 r2', at: '2026-09-24T15:20:00+08:00',
          files: [
            { path: 'src/reader.py', bytes: 2340 },
            { path: 'src/store.py', bytes: 1480 },
            { path: 'src/web.py', bytes: 2360 },
            { path: 'deploy/sensor.service', bytes: 450 }
          ],
          text: '重试 3 次；日志逐行 JSON；启动输出版本号。pytest 6 passed。'
        },
        {
          id: 'm-sensor-qa-v2', project_id: P, work_item_id: 'w-sensor-base', kind: 'qa', version: 2,
          title: '质检结论 r2', at: '2026-09-24T16:15:00+08:00', verdict: 'release',
          text: '放行。重试计数准确；日志每行是合法 JSON；启动日志第一行含版本号。'
        },
        {
          id: 'm-sensor-note', project_id: P, work_item_id: null, kind: 'note', version: 1,
          title: '运行环境与常设授权', at: '2026-09-25T10:00:00+08:00',
          text: '运行环境为客厅树莓派（m-pi）。常设授权：重启服务、查看日志、部署已放行的版本；部署前备份，保留最近 3 份。'
        }
      ],
      project_settings: {
        'p-sensor': {
          version: 1,
          departments: {
            product: null,
            engineering: null,
            quality: { model: 'opencode-go-responses/glm-5', level: null, prompt_version: 2, prompt_text: '对照验收条件逐项检查；曲线只读数据库，不写入。' },
            operations: null
          },
          commands: [
            { name: 'pytest', argv: 'python -m pytest', args: ['tests'], timeout_sec: 120, output_limit: 200000, version: 1 },
            { name: 'deploy_check', argv: 'python scripts/deploy_check.py', args: [], timeout_sec: 60, output_limit: 20000, version: 1 }
          ],
          tools: [
            { id: 'network', label: '网络取回', scope: '未授权', approval: '每次使用逐次批准', level: '3.2B' }
          ],
          machines: [
            { machine_id: 'm-host', dirs: ['/work/p-sensor'], operations: ['构建', '测试'], level: '3.2C' },
            {
              machine_id: 'm-pi', dirs: ['/srv/sensor'], operations: ['重启服务', '查看日志', '部署'], level: '3.2C',
              runtime_env: true, standing: ['重启服务', '查看日志', '部署已放行的版本']
            }
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
      },
      ops: {
        'p-sensor': {
          level: 'S4',
          env: { machine_id: 'm-pi', version: 'r1' },
          releases: [{ version: 'r1', at: '2026-09-12T16:10:00+08:00', method: '常设授权以内', note: '首次部署' }],
          faults: [],
          backups: [{ id: 'b-sensor-r1', at: '2026-09-12T16:00:00+08:00', version: 'r0', note: '首次部署前的备份' }],
          indicators: [
            { id: 'writes_24h', label: '过去 24 小时写入成功', value: 1398, of: 1440, unit: '分钟' },
            { id: 'online_7d', label: '过去 7 天服务在线', value: 166, of: 168, unit: '小时' }
          ],
          check_in: { last_at: '2026-09-22T15:30:00+08:00', every_min: 360, ok: true }
        }
      }
    },
    history: [
      ev({
        at: '2026-09-24T09:00:00+08:00', type: 'department_activated', work_item_id: 'w-sensor-base', run_id: 'r-sensor-base', department: 'engineering',
        label: '工程按增量的 r2 要求调整重试与日志',
        payload: {},
        patch: [
          { path: 'runs[id=r-sensor-base].cycle', value: 2 },
          { path: 'runs[id=r-sensor-base].elapsed_sec', value: 2400 },
          { path: 'projects[id=p-sensor].last_activity_at', value: '2026-09-24T09:00:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-24T15:30:00+08:00', type: 'transition', work_item_id: 'w-sensor-base', run_id: 'r-sensor-base', department: 'engineering',
        label: '工程把 r2 交付交给质检',
        payload: { from: 'engineering', to: 'quality', artifact: 'box' },
        patch: [
          { path: 'runs[id=r-sensor-base].department', value: 'quality' },
          { path: 'runs[id=r-sensor-base].last_department', value: 'engineering' }
        ]
      }),
      ev({
        at: '2026-09-24T16:20:00+08:00', type: 'qa_submitted', work_item_id: 'w-sensor-base', run_id: 'r-sensor-base', department: 'quality',
        label: '质检放行可运维性的 r2',
        payload: { verdict: 'release', material_id: 'm-sensor-qa-v2' },
        patch: [{ path: 'projects[id=p-sensor].last_activity_at', value: '2026-09-24T16:20:00+08:00' }]
      }),
      ev({
        at: '2026-09-24T16:25:00+08:00', type: 'transition', work_item_id: 'w-sensor-base', run_id: 'r-sensor-base', department: 'quality',
        label: 'r2 送到成果库',
        payload: { from: 'quality', to: 'library', artifact: 'release' },
        patch: [
          { path: 'runs[id=r-sensor-base].department', value: null },
          { path: 'runs[id=r-sensor-base].last_department', value: 'quality' }
        ]
      }),
      ev({
        at: '2026-09-25T09:40:00+08:00', type: 'deliverable_adopted', work_item_id: 'w-sensor-base', run_id: 'r-sensor-base', actor: 'user',
        label: '用户采纳可运维性的 r2',
        payload: { version: 'r2' },
        patch: [
          { path: 'projects[id=p-sensor].adoptions', push: { version: 'r2', work_item_id: 'w-sensor-base', summary: '重试 3 次、结构化日志与版本号输出', adopted_at: '2026-09-25T09:40:00+08:00' } },
          { path: 'runs[id=r-sensor-base].phase', value: 'DONE' },
          { path: 'projects[id=p-sensor].last_activity_at', value: '2026-09-25T09:40:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-25T10:10:00+08:00', type: 'x_backup_taken', level: 'S4',
        label: '部署 r2 之前备份数据',
        payload: { backup_id: 'b-sensor-r2', version: 'r1' },
        patch: [{ path: 'ops.p-sensor.backups', push: { id: 'b-sensor-r2', at: '2026-09-25T10:10:00+08:00', version: 'r1', note: '部署 r2 之前的备份' } }]
      }),
      ev({
        at: '2026-09-25T10:15:00+08:00', type: 'x_deployed', level: 'S4',
        label: '把已采纳的 r2 部署到客厅树莓派',
        payload: { version: 'r2', machine_id: 'm-pi' },
        patch: [
          { path: 'ops.p-sensor.env.version', value: 'r2' },
          { path: 'ops.p-sensor.releases', push: { version: 'r2', at: '2026-09-25T10:15:00+08:00', method: '常设授权以内' } },
          { path: 'machines[id=m-pi].actions', push: { project_id: P, work_item_id: 'w-sensor-base', department: 'operations', action_id: 'a-sensor-deploy-r2', label: '部署 r2', state: 'done' } },
          { path: 'machines[id=m-pi].last_heartbeat_at', value: '2026-09-25T10:15:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T02:14:00+08:00', type: 'x_fault_recorded', level: 'S4',
        label: '记录故障 F-1：树莓派重启后传感器读取超时，服务反复重启',
        payload: { fault_id: 'F-1', machine_id: 'm-pi' },
        patch: [
          {
            path: 'ops.p-sensor.faults',
            push: { id: 'F-1', title: '树莓派重启后传感器读取超时，服务反复重启', status: 'open', repair_work_item_ids: [], failures: 0, observe_until: null, born_at: '2026-09-28T02:14:00+08:00' }
          },
          { path: 'machines[id=m-pi].last_heartbeat_at', value: '2026-09-28T02:14:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T02:30:00+08:00', type: 'x_repair_created', work_item_id: 'w-sensor-fix1', run_id: 'r-sensor-fix1', level: 'S4',
        label: '自动建立修复事项 w-sensor-fix1',
        payload: { fault_id: 'F-1' },
        patch: [
          { path: 'ops.p-sensor.faults[id=F-1].status', value: 'repairing' },
          { path: 'ops.p-sensor.faults[id=F-1].repair_work_item_ids', push: 'w-sensor-fix1' },
          { path: 'projects[id=p-sensor].last_activity_at', value: '2026-09-28T02:30:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T03:05:00+08:00', type: 'x_slot_acquired', work_item_id: 'w-sensor-fix1', run_id: 'r-sensor-fix1', department: 'product', level: 'S4',
        label: '修复事项取得执行槽位，产品先判断故障是否成立',
        payload: {},
        patch: [
          { path: 'work_items[id=w-sensor-fix1].status', value: 'in_progress' },
          { path: 'work_items[id=w-sensor-fix1].queue_reason', value: null },
          { path: 'work_items[id=w-sensor-fix1].queue_pos', value: null },
          { path: 'runs[id=r-sensor-fix1].phase', value: 'PRODUCT_SPEC' },
          { path: 'runs[id=r-sensor-fix1].department', value: 'product' },
          { path: 'runs[id=r-sensor-fix1].cycle', value: 1 },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-sensor-fix1', department: 'product', role: null } }
        ]
      }),
      ev({
        at: '2026-09-28T03:40:00+08:00', type: 'transition', work_item_id: 'w-sensor-fix1', run_id: 'r-sensor-fix1', department: 'product', level: 'S4',
        label: '故障成立，修复交给工程',
        payload: { from: 'product', to: 'engineering', artifact: 'defect' },
        patch: [
          { path: 'runs[id=r-sensor-fix1].department', value: 'engineering' },
          { path: 'runs[id=r-sensor-fix1].last_department', value: 'product' },
          { path: 'runs[id=r-sensor-fix1].phase', value: 'ENGINEERING' },
          { path: 'runtime.slots.used[work_item_id=w-sensor-fix1].department', value: 'engineering' }
        ]
      }),
      ev({
        at: '2026-09-28T05:20:00+08:00', type: 'transition', work_item_id: 'w-sensor-fix1', run_id: 'r-sensor-fix1', department: 'engineering', level: 'S4',
        label: '修复交给质检核验',
        payload: { from: 'engineering', to: 'quality', artifact: 'box' },
        patch: [
          { path: 'runs[id=r-sensor-fix1].department', value: 'quality' },
          { path: 'runs[id=r-sensor-fix1].last_department', value: 'engineering' },
          { path: 'runs[id=r-sensor-fix1].phase', value: 'QUALITY' },
          { path: 'runtime.slots.used[work_item_id=w-sensor-fix1].department', value: 'quality' }
        ]
      }),
      ev({
        at: '2026-09-28T06:20:00+08:00', type: 'transition', work_item_id: 'w-sensor-fix1', run_id: 'r-sensor-fix1', department: 'quality', level: 'S4',
        label: '核验通过，交运维部署',
        payload: { from: 'quality', to: 'operations', artifact: 'release' },
        patch: [
          { path: 'runs[id=r-sensor-fix1].department', value: 'operations' },
          { path: 'runs[id=r-sensor-fix1].last_department', value: 'quality' },
          { path: 'runtime.slots.used[work_item_id=w-sensor-fix1].department', value: 'operations' }
        ]
      }),
      ev({
        at: '2026-09-28T06:30:00+08:00', type: 'deliverable_adopted', work_item_id: 'w-sensor-fix1', run_id: 'r-sensor-fix1', level: 'S4',
        label: '采纳修复 F-1 的交付，版本 r3',
        payload: { version: 'r3' },
        patch: [
          { path: 'projects[id=p-sensor].adoptions', push: { version: 'r3', work_item_id: 'w-sensor-fix1', summary: '重启后延迟首次采样并放宽读取超时', adopted_at: '2026-09-28T06:30:00+08:00' } },
          { path: 'work_items[id=w-sensor-fix1].status', value: 'adopted' },
          { path: 'runs[id=r-sensor-fix1].phase', value: 'DONE' },
          { path: 'runs[id=r-sensor-fix1].elapsed_sec', value: 4200 },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-sensor-fix1' } }
        ]
      }),
      ev({
        at: '2026-09-28T06:40:00+08:00', type: 'x_backup_taken', level: 'S4',
        label: '部署 r3 之前备份数据',
        payload: { backup_id: 'b-sensor-0928-0640', version: 'r2' },
        patch: [{ path: 'ops.p-sensor.backups', push: { id: 'b-sensor-0928-0640', at: '2026-09-28T06:40:00+08:00', version: 'r2', note: '部署 r3 之前的备份' } }]
      }),
      ev({
        at: '2026-09-28T06:42:00+08:00', type: 'x_deployed', work_item_id: 'w-sensor-fix1', run_id: 'r-sensor-fix1', department: 'operations', level: 'S4',
        label: '把用户已采纳的 r3 部署到客厅树莓派，进入观察窗口',
        payload: { version: 'r3', machine_id: 'm-pi' },
        patch: [
          { path: 'ops.p-sensor.env.version', value: 'r3' },
          { path: 'ops.p-sensor.releases', push: { version: 'r3', at: '2026-09-28T06:42:00+08:00', method: '常设授权以内', note: '修复 F-1' } },
          { path: 'ops.p-sensor.faults[id=F-1].status', value: 'observing' },
          { path: 'ops.p-sensor.faults[id=F-1].observe_until', value: '2026-09-29T06:42:00+08:00' },
          { path: 'runs[id=r-sensor-fix1].department', value: null },
          { path: 'machines[id=m-pi].actions', push: { project_id: P, work_item_id: 'w-sensor-fix1', department: 'operations', action_id: 'a-sensor-deploy-r3', label: '部署 r3', state: 'done' } },
          { path: 'machines[id=m-pi].last_heartbeat_at', value: '2026-09-28T06:42:00+08:00' },
          { path: 'projects[id=p-sensor].last_activity_at', value: '2026-09-28T06:42:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-28T09:00:00+08:00', type: 'work_item_created', work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', actor: 'user',
        label: '用户提出事项「增加 7 天曲线」',
        payload: { title: '增加 7 天曲线' },
        patch: [{ path: 'projects[id=p-sensor].last_activity_at', value: '2026-09-28T09:00:00+08:00' }]
      }),
      ev({
        at: '2026-09-28T09:00:00+08:00', type: 'run_created', work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart',
        label: '7 天曲线的 run 建立',
        payload: { yudao_version: '0.8.0' }
      }),
      ev({
        at: '2026-09-28T09:05:00+08:00', type: 'department_activated', work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'product',
        label: '产品部门开始写曲线的验收条件',
        payload: {},
        patch: [
          { path: 'work_items[id=w-sensor-chart].status', value: 'in_progress' },
          { path: 'runs[id=r-sensor-chart].phase', value: 'PRODUCT_SPEC' },
          { path: 'runs[id=r-sensor-chart].department', value: 'product' },
          { path: 'runs[id=r-sensor-chart].cycle', value: 1 }
        ]
      }),
      ev({
        at: '2026-09-28T09:15:00+08:00', type: 'transition', work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'product',
        label: '曲线要求交给工程',
        payload: { from: 'product', to: 'engineering', artifact: 'prd' },
        patch: [
          { path: 'runs[id=r-sensor-chart].department', value: 'engineering' },
          { path: 'runs[id=r-sensor-chart].last_department', value: 'product' },
          { path: 'runs[id=r-sensor-chart].phase', value: 'ENGINEERING' }
        ]
      }),
      ev({
        at: '2026-09-28T09:30:00+08:00', type: 'transition', work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'engineering',
        label: '曲线页交给质检',
        payload: { from: 'engineering', to: 'quality', artifact: 'box' },
        patch: [
          { path: 'runs[id=r-sensor-chart].department', value: 'quality' },
          { path: 'runs[id=r-sensor-chart].last_department', value: 'engineering' },
          { path: 'runs[id=r-sensor-chart].phase', value: 'QUALITY' }
        ]
      }),
      ev({
        at: '2026-09-28T09:40:00+08:00', type: 'department_activated', work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality',
        label: '质检开始按验收条件检查曲线',
        payload: {},
        patch: [{ path: 'projects[id=p-sensor].last_activity_at', value: '2026-09-28T09:40:00+08:00' }]
      }),
      ev({
        at: '2026-09-28T09:40:00+08:00', type: 'model_attempt_failed', work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality',
        label: '质检的模型请求没有发出：glm-5 的准入已作废',
        payload: { category: '准入已作废', text: '上游返回的实际模型与定义不符，09:30 重新测试未通过' },
        patch: []
      }),
      ev({
        at: '2026-09-28T09:40:00+08:00', type: 'x_decision_issued', work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality',
        label: '发出决定请求：模型引用无法使用时的待恢复',
        payload: { decision_id: 'd-sensor-glm', kind: 'waiting_resume' },
        patch: [
          { path: 'decisions[id=d-sensor-glm].status', value: 'waiting' },
          { path: 'runs[id=r-sensor-chart].recovery.state', value: 'waiting_resume' },
          { path: 'runs[id=r-sensor-chart].recovery.reason', value: '质检的模型 glm-5 准入已作废，事务停在开始检查曲线之前' },
          { path: 'runs[id=r-sensor-chart].recovery.unusable', value: { department: 'quality', model: 'glm-5', problem: '准入已作废' } },
          { path: 'projects[id=p-sensor].last_activity_at', value: '2026-09-28T09:40:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-29T09:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：客厅树莓派服务正常，F-1 的观察窗口已结束',
        payload: { ok: true },
        patch: [
          { path: 'ops.p-sensor.check_in.last_at', value: '2026-09-29T09:10:00+08:00' },
          { path: 'ops.p-sensor.check_in.ok', value: true },
          { path: 'ops.p-sensor.faults[id=F-1].status', value: 'fixed' },
          { path: 'machines[id=m-pi].last_heartbeat_at', value: '2026-09-29T09:10:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-29T12:30:00+08:00', type: 'x_fault_recorded', level: 'S4',
        label: '记录故障 F-2：夜间写入数据库失败',
        payload: { fault_id: 'F-2', machine_id: 'm-pi' },
        patch: [
          {
            path: 'ops.p-sensor.faults',
            push: { id: 'F-2', title: '夜间写入数据库失败', status: 'open', repair_work_item_ids: [], failures: 0, observe_until: null, born_at: '2026-09-29T12:30:00+08:00' }
          },
          { path: 'machines[id=m-pi].last_heartbeat_at', value: '2026-09-29T12:30:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-29T12:35:00+08:00', type: 'x_repair_created', work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', level: 'S4',
        label: '故障 F-2 建立修复事项 w-sensor-fix2',
        payload: { title: '修复夜间写入数据库失败', fault_id: 'F-2' },
        patch: [
          { path: 'ops.p-sensor.faults[id=F-2].status', value: 'repairing' },
          { path: 'ops.p-sensor.faults[id=F-2].repair_work_item_ids', push: 'w-sensor-fix2' },
          { path: 'projects[id=p-sensor].last_activity_at', value: '2026-09-29T12:35:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-29T12:40:00+08:00', type: 'x_slot_acquired', work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'product', level: 'S4',
        label: '修复事项取得执行槽位，产品先判断故障是否成立',
        payload: {},
        patch: [
          { path: 'work_items[id=w-sensor-fix2].status', value: 'in_progress' },
          { path: 'work_items[id=w-sensor-fix2].queue_reason', value: null },
          { path: 'work_items[id=w-sensor-fix2].queue_pos', value: null },
          { path: 'runs[id=r-sensor-fix2].phase', value: 'PRODUCT_SPEC' },
          { path: 'runs[id=r-sensor-fix2].department', value: 'product' },
          { path: 'runs[id=r-sensor-fix2].cycle', value: 1 },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-sensor-fix2', department: 'product', role: null } }
        ]
      }),
      ev({
        at: '2026-09-29T12:50:00+08:00', type: 'transition', work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'product', level: 'S4',
        label: '故障成立，修复交给工程，写入改为单写者队列',
        payload: { from: 'product', to: 'engineering', artifact: 'defect' },
        patch: [
          { path: 'runs[id=r-sensor-fix2].department', value: 'engineering' },
          { path: 'runs[id=r-sensor-fix2].last_department', value: 'product' },
          { path: 'runs[id=r-sensor-fix2].phase', value: 'ENGINEERING' },
          { path: 'runtime.slots.used[work_item_id=w-sensor-fix2].department', value: 'engineering' }
        ]
      }),
      ev({
        at: '2026-09-29T13:05:00+08:00', type: 'model_attempt_failed', work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', level: 'S4',
        label: '工程的模型请求失败：上游返回 503',
        payload: { category: '上游服务错误', code: '503', http: 503 },
        patch: []
      }),
      ev({
        at: '2026-09-29T13:05:00+08:00', type: 'x_provider_wait_entered', work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', level: 'S4',
        label: '工程进入等待模型服务，下一次重试 15:42',
        payload: { department: 'engineering', next_retry_at: '2026-09-29T15:42:00+08:00', category: '上游返回 503' },
        patch: [
          { path: 'runs[id=r-sensor-fix2].waiting_provider', value: { department: 'engineering', since: '2026-09-29T13:05:00+08:00', next_retry_at: '2026-09-29T15:42:00+08:00', category: '上游返回 503' } },
          { path: 'runs[id=r-sensor-fix2].waiting_provider_sec', value: 0 },
          { path: 'projects[id=p-sensor].last_activity_at', value: '2026-09-29T13:05:00+08:00' }
        ]
      }),
      ev({
        at: '2026-09-29T13:05:00+08:00', type: 'x_decision_issued', work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', level: 'S4',
        label: '发出决定请求：进入等待模型服务的通知',
        payload: { decision_id: 'd-sensor-wait', kind: 'provider_wait' },
        patch: [{ path: 'decisions[id=d-sensor-wait].status', value: 'waiting' }]
      }),
      ev({
        at: '2026-09-29T15:10:00+08:00', type: 'x_check_in', work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', level: 'S4',
        label: '外部报到：服务正常，工程仍在等待模型服务（已等待 2 小时 25 分）',
        payload: { ok: true },
        patch: [
          { path: 'ops.p-sensor.check_in.last_at', value: '2026-09-29T15:10:00+08:00' },
          { path: 'runs[id=r-sensor-fix2].waiting_provider_sec', value: 8700 }
        ]
      })
    ],
    scenarios: [
      {
        no: 6, id: 'sc-sensor-resume', name: '模型引用无法使用与待恢复', level: 'ui', go: '#/p/p-sensor/overview',
        setup: [
          { path: 'decisions[id=d-sensor-glm].status', value: 'withdrawn' },
          { path: 'runs[id=r-sensor-chart].recovery.state', value: 'running' },
          { path: 'runs[id=r-sensor-chart].recovery.unusable', value: null },
          { path: 'runs[id=r-sensor-chart].recovery.reason', value: '运行中' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-sensor/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality', label: '质检开始按验收条件检查 7 天曲线', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'model_requested', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality', label: '质检发起模型请求', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'model_attempt_failed', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality', label: '模型请求没有发出：glm-5 的准入已作废', payload: { category: '准入已作废' } }, patch: [] },
          { delay: 1400, event: { type: 'x_decision_issued', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality', label: '发出决定请求：模型引用无法使用时的待恢复', payload: { decision_id: 'd-sensor-glm', kind: 'waiting_resume' } }, patch: [{ path: 'decisions[id=d-sensor-glm].status', value: 'waiting' }, { path: 'runs[id=r-sensor-chart].recovery.state', value: 'waiting_resume' }, { path: 'runs[id=r-sensor-chart].recovery.reason', value: '质检的模型 glm-5 准入已作废' }, { path: 'runs[id=r-sensor-chart].recovery.unusable', value: { department: 'quality', model: 'glm-5', problem: '准入已作废' } }] },
          { delay: 1200, go: '#/p/p-sensor/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality', label: '质检房间门口立起「待恢复」牌，写明缺少的项', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'x_department_settings_saved', project_id: P, department: 'quality', actor: 'user', label: '用户把质检部门的模型改为跟随部门默认', payload: { department: 'quality' } }, patch: [{ path: 'project_settings.p-sensor.departments.quality.model', value: null }] },
          { delay: 1200, event: { type: 'x_decision_answered', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', actor: 'user', label: '用户回答「继续执行」', payload: { decision_id: 'd-sensor-glm', kind: 'waiting_resume', option: 'continue' } }, patch: [{ path: 'decisions[id=d-sensor-glm].status', value: 'answered' }, { path: 'decisions[id=d-sensor-glm].answer', value: { option: 'continue', label: '继续执行', note: '', at: '2026-09-29T15:31:00+08:00' } }, { path: 'runs[id=r-sensor-chart].recovery.state', value: 'running' }, { path: 'runs[id=r-sensor-chart].recovery.reason', value: '配置已修复，继续执行' }, { path: 'runs[id=r-sensor-chart].recovery.unusable', value: null }] },
          { delay: 1200, event: { type: 'model_requested', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality', label: '质检改用部门默认的 mimo 请求模型', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'model_attempt_finished', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality', label: '请求完成，质检继续检查曲线', payload: {} }, patch: [] },
          { delay: 1000, go: '#/p/p-sensor/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality', label: '「待恢复」牌摘下，质检继续工作', payload: {} }, patch: [] }
        ]
      },
      {
        no: 15, id: 'sc-sensor-provider-wait', name: '等待模型服务', level: 'S4', go: '#/p/p-sensor/overview',
        setup: [
          { path: 'runs[id=r-sensor-fix2].waiting_provider', value: null },
          { path: 'runs[id=r-sensor-fix2].waiting_provider_sec', value: 0 },
          { path: 'decisions[id=d-sensor-wait].status', value: 'withdrawn' }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-sensor/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '工程正在把写入改成单写者队列', payload: {} }, patch: [] },
          { delay: 1200, event: { type: 'model_requested', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '工程发起模型请求', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'model_attempt_failed', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '上游返回 503，本次请求失败', payload: { category: '上游服务错误', code: '503', http: 503 } }, patch: [] },
          { delay: 1400, event: { type: 'x_provider_wait_entered', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '进入等待模型服务，管道停止，显示下一次重试时间', payload: { department: 'engineering', next_retry_at: '2026-09-29T15:42:00+08:00', category: '上游返回 503' } }, patch: [{ path: 'runs[id=r-sensor-fix2].waiting_provider', value: { department: 'engineering', since: '2026-09-29T15:30:00+08:00', next_retry_at: '2026-09-29T15:42:00+08:00', category: '上游返回 503' } }, { path: 'runs[id=r-sensor-fix2].waiting_provider_sec', value: 0 }] },
          { delay: 1200, event: { type: 'x_decision_issued', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '发出通知决定：工程部门进入等待模型服务', payload: { decision_id: 'd-sensor-wait', kind: 'provider_wait' } }, patch: [{ path: 'decisions[id=d-sensor-wait].status', value: 'waiting' }] },
          { delay: 1200, go: '#/p/p-sensor/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '房间灯光调暗，工程坐在工位上等重试时间', payload: {} }, patch: [] },
          { delay: 1400, event: { type: 'model_retry_scheduled', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '上游仍不可用，下一次重试改到 15:52', payload: { n: 1, of: 3 } }, patch: [{ path: 'runs[id=r-sensor-fix2].waiting_provider.next_retry_at', value: '2026-09-29T15:52:00+08:00' }] },
          { delay: 1400, event: { type: 'model_attempt_finished', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '重试成功，上游恢复', payload: {} }, patch: [{ path: 'runs[id=r-sensor-fix2].waiting_provider_sec', value: 1320 }] },
          { delay: 1200, event: { type: 'x_provider_wait_left', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '离开等待模型服务，管道恢复流动', payload: { department: 'engineering' } }, patch: [{ path: 'runs[id=r-sensor-fix2].waiting_provider', value: null }] },
          { delay: 1200, event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '灯光恢复，工程继续修复夜间写入失败', payload: {} }, patch: [] },
          { delay: 1000, go: '#/p/p-sensor/overview', event: { type: 'model_stream_progress', project_id: P, work_item_id: 'w-sensor-fix2', run_id: 'r-sensor-fix2', department: 'engineering', label: '工程继续输出修复说明', payload: { text: '单写者队列已通过检查。' } }, patch: [] }
        ]
      },
      {
        no: 16, id: 'sc-sensor-fault-rollback', name: '故障、修复与回滚', level: 'S4', go: '#/p/p-sensor/overview',
        setup: [],
        steps: [
          { delay: 1200, go: '#/p/p-sensor/overview', event: { type: 'x_fault_recorded', project_id: P, label: '记录故障 F-3：凌晨上传任务占用内存过高，服务重启', payload: { fault_id: 'F-3', machine_id: 'm-pi' } }, patch: [{ path: 'ops.p-sensor.faults', push: { id: 'F-3', title: '凌晨上传任务占用内存过高，服务重启', status: 'open', repair_work_item_ids: [], failures: 0, observe_until: null, born_at: '2026-09-29T15:30:00+08:00' } }, { path: 'machines[id=m-pi].last_heartbeat_at', value: '2026-09-29T15:30:00+08:00' }] },
          { delay: 1400, event: { type: 'x_repair_created', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', label: '自动建立修复事项 w-sensor-fix3', payload: { fault_id: 'F-3' } }, patch: [{ path: 'ops.p-sensor.faults[id=F-3].status', value: 'repairing' }, { path: 'ops.p-sensor.faults[id=F-3].repair_work_item_ids', push: 'w-sensor-fix3' }, { path: 'work_items', push: repairItem('w-sensor-fix3', '修复内存占用过高', '2026-09-29T15:30:00+08:00') }, { path: 'runs', push: repairRun('r-sensor-fix3', 'w-sensor-fix3', '2026-09-29T15:30:00+08:00') }] },
          { delay: 1200, event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', department: 'product', label: '产品判断故障成立，修复范围只限上传任务', payload: {} }, patch: [{ path: 'work_items[id=w-sensor-fix3].status', value: 'in_progress' }, { path: 'work_items[id=w-sensor-fix3].queue_reason', value: null }, { path: 'work_items[id=w-sensor-fix3].queue_pos', value: null }, { path: 'runs[id=r-sensor-fix3].department', value: 'product' }, { path: 'runs[id=r-sensor-fix3].phase', value: 'PRODUCT_SPEC' }] },
          { delay: 1200, event: { type: 'transition', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', department: 'product', label: '修复交给工程', payload: { from: 'product', to: 'engineering', artifact: 'defect' } }, patch: [{ path: 'runs[id=r-sensor-fix3].department', value: 'engineering' }, { path: 'runs[id=r-sensor-fix3].last_department', value: 'product' }, { path: 'runs[id=r-sensor-fix3].phase', value: 'ENGINEERING' }] },
          { delay: 1200, event: { type: 'tool_started', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', department: 'engineering', label: '工程阅读上传任务的内存记录', payload: { tool: 'read_file' } }, patch: [] },
          { delay: 1400, event: { type: 'tool_called', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', department: 'engineering', label: '登记命令 deploy_check 通过', payload: { tool: 'run_command', exit_code: 0, timed_out: false } }, patch: [] },
          { delay: 1200, event: { type: 'transition', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', department: 'engineering', label: '修复交给质检', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, patch: [{ path: 'runs[id=r-sensor-fix3].department', value: 'quality' }, { path: 'runs[id=r-sensor-fix3].last_department', value: 'engineering' }, { path: 'runs[id=r-sensor-fix3].phase', value: 'QUALITY' }] },
          { delay: 1400, event: { type: 'qa_submitted', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', department: 'quality', label: '质检放行修复', payload: { verdict: 'release' } }, patch: [{ path: 'work_items[id=w-sensor-fix3].status', value: 'released' }] },
          { delay: 1200, event: { type: 'transition', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', department: 'quality', label: '放行的修复交运维部署', payload: { from: 'quality', to: 'operations', artifact: 'release' } }, patch: [{ path: 'runs[id=r-sensor-fix3].department', value: 'operations' }, { path: 'runs[id=r-sensor-fix3].last_department', value: 'quality' }] },
          { delay: 1200, event: { type: 'x_backup_taken', project_id: P, label: '部署 r4 之前备份数据', payload: { backup_id: 'b-sensor-sc16', version: 'r3' } }, patch: [{ path: 'ops.p-sensor.backups', push: { id: 'b-sensor-sc16', at: '2026-09-29T15:30:00+08:00', version: 'r3', note: '部署 r4 之前的备份' } }] },
          { delay: 1400, event: { type: 'x_deployed', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', department: 'operations', label: '部署 r4，进入观察窗口', payload: { version: 'r4', machine_id: 'm-pi' } }, patch: [{ path: 'ops.p-sensor.env.version', value: 'r4' }, { path: 'ops.p-sensor.releases', push: { version: 'r4', at: '2026-09-29T15:30:00+08:00', method: '常设授权以内', note: '修复 F-3' } }, { path: 'ops.p-sensor.faults[id=F-3].status', value: 'observing' }, { path: 'work_items[id=w-sensor-fix3].status', value: 'adopted' }, { path: 'runs[id=r-sensor-fix3].phase', value: 'DONE' }, { path: 'runs[id=r-sensor-fix3].department', value: null }, { path: 'machines[id=m-pi].actions', push: { project_id: P, work_item_id: 'w-sensor-fix3', department: 'operations', action_id: 'a-sensor-deploy-r4', label: '部署 r4', state: 'done' } }] },
          { delay: 1400, event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', department: 'operations', label: '运维发现 r4 的数据库结构不兼容，发出回滚决定请求', payload: {} }, patch: [{ path: 'decisions', push: decision('d-sensor-rollback', 'rollback_restore', { fault_id: 'F-3', to_version: 'r3', backup: { id: 'b-sensor-sc16', at: '2026-09-29T15:30:00+08:00' }, incompatible: 'r4 把 readings 表加了一列默认值，回滚到 r3 需要恢复备份' }, '#/p/p-sensor/overview', '2026-09-29T15:30:00+08:00', { work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', options: [{ id: 'rollback', label: '回滚并恢复备份', kind: 'primary', events: [] }, { id: 'keep', label: '不回滚', kind: null, events: [] }] }) }] },
          { delay: 1400, event: { type: 'x_decision_answered', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', actor: 'user', label: '用户选择「回滚并恢复备份」', payload: { decision_id: 'd-sensor-rollback', kind: 'rollback_restore', option: 'rollback' } }, patch: [{ path: 'decisions[id=d-sensor-rollback].status', value: 'answered' }, { path: 'decisions[id=d-sensor-rollback].answer', value: { option: 'rollback', label: '回滚并恢复备份', note: '', at: '2026-09-29T15:31:00+08:00' } }] },
          { delay: 1400, event: { type: 'x_rolled_back', project_id: P, department: 'operations', label: '回滚到 r3 并恢复备份', payload: { from_version: 'r4', to_version: 'r3', machine_id: 'm-pi' } }, patch: [{ path: 'ops.p-sensor.env.version', value: 'r3' }, { path: 'ops.p-sensor.releases', push: { version: 'r3', at: '2026-09-29T15:31:00+08:00', method: '回滚并恢复备份', note: '从 b-sensor-sc16 恢复' } }, { path: 'ops.p-sensor.faults[id=F-3].status', value: 'open' }, { path: 'machines[id=m-pi].actions', push: { project_id: P, work_item_id: 'w-sensor-fix3', department: 'operations', action_id: 'a-sensor-rollback-r3', label: '回滚到 r3', state: 'done' } }, { path: 'machines[id=m-pi].last_heartbeat_at', value: '2026-09-29T15:31:00+08:00' }] },
          { delay: 1200, go: '#/p/p-sensor/overview', event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-fix3', run_id: 'r-sensor-fix3', department: 'operations', label: '服务回到 r3 并恢复运行，F-3 仍待修复', payload: {} }, patch: [] }
        ]
      },
      {
        no: 17, id: 'sc-sensor-repair-stop', name: '连续修复失败后停止自动修复', level: 'S4', go: '#/p/p-sensor/overview',
        setup: [
          { path: 'ops.p-sensor.faults', push: { id: 'F-4', title: '传感器读数间歇性为零，曲线出现断点', status: 'open', repair_work_item_ids: [], failures: 0, observe_until: null, born_at: '2026-09-29T15:30:00+08:00' } }
        ],
        steps: [
          { delay: 1200, go: '#/p/p-sensor/overview', event: { type: 'x_fault_recorded', project_id: P, label: '记录故障 F-4：传感器读数间歇性为零', payload: { fault_id: 'F-4', machine_id: 'm-pi' } }, patch: [{ path: 'machines[id=m-pi].last_heartbeat_at', value: '2026-09-29T15:30:00+08:00' }] },
          { delay: 1400, event: { type: 'x_repair_created', project_id: P, work_item_id: 'w-sensor-fix4', run_id: 'r-sensor-fix4', label: '自动建立第 1 个修复事项 w-sensor-fix4', payload: { fault_id: 'F-4' } }, patch: [{ path: 'ops.p-sensor.faults[id=F-4].status', value: 'repairing' }, { path: 'ops.p-sensor.faults[id=F-4].repair_work_item_ids', push: 'w-sensor-fix4' }, { path: 'work_items', push: repairItem('w-sensor-fix4', '修复读数间歇性为零', '2026-09-29T15:30:00+08:00') }, { path: 'runs', push: repairRun('r-sensor-fix4', 'w-sensor-fix4', '2026-09-29T15:30:00+08:00') }] },
          { delay: 1200, event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-fix4', run_id: 'r-sensor-fix4', department: 'product', label: '产品判断故障成立', payload: {} }, patch: [{ path: 'work_items[id=w-sensor-fix4].status', value: 'in_progress' }, { path: 'work_items[id=w-sensor-fix4].queue_reason', value: null }, { path: 'work_items[id=w-sensor-fix4].queue_pos', value: null }, { path: 'runs[id=r-sensor-fix4].department', value: 'product' }, { path: 'runs[id=r-sensor-fix4].phase', value: 'PRODUCT_SPEC' }] },
          { delay: 1200, event: { type: 'transition', project_id: P, work_item_id: 'w-sensor-fix4', run_id: 'r-sensor-fix4', department: 'product', label: '第 1 个修复交给工程', payload: { from: 'product', to: 'engineering', artifact: 'defect' } }, patch: [{ path: 'runs[id=r-sensor-fix4].department', value: 'engineering' }, { path: 'runs[id=r-sensor-fix4].last_department', value: 'product' }, { path: 'runs[id=r-sensor-fix4].phase', value: 'ENGINEERING' }] },
          { delay: 1400, event: { type: 'tool_called', project_id: P, work_item_id: 'w-sensor-fix4', run_id: 'r-sensor-fix4', department: 'engineering', label: '工程把采样改为读两遍取中值，deploy_check 通过', payload: { tool: 'run_command', exit_code: 0, timed_out: false } }, patch: [] },
          { delay: 1400, event: { type: 'x_deployed', project_id: P, department: 'operations', work_item_id: 'w-sensor-fix4', run_id: 'r-sensor-fix4', label: '部署第 1 个修复 r5，进入观察窗口', payload: { version: 'r5', machine_id: 'm-pi' } }, patch: [{ path: 'ops.p-sensor.env.version', value: 'r5' }, { path: 'ops.p-sensor.releases', push: { version: 'r5', at: '2026-09-29T15:31:00+08:00', method: '常设授权以内', note: '修复 F-4 的第 1 次' } }, { path: 'ops.p-sensor.faults[id=F-4].observe_until', value: '2026-09-30T15:31:00+08:00' }] },
          { delay: 1400, go: '#/p/p-sensor/overview', event: { type: 'x_fault_recorded', project_id: P, label: '观察窗口内同一故障再次出现', payload: { fault_id: 'F-4', machine_id: 'm-pi' } }, patch: [{ path: 'ops.p-sensor.faults[id=F-4].status', value: 'open' }] },
          { delay: 1400, event: { type: 'x_repair_failed', project_id: P, work_item_id: 'w-sensor-fix4', run_id: 'r-sensor-fix4', label: '第 1 次修复记为失败，自动建立第 2 个修复事项 w-sensor-fix5', payload: { fault_id: 'F-4' } }, patch: [{ path: 'ops.p-sensor.faults[id=F-4].failures', value: 1 }, { path: 'ops.p-sensor.faults[id=F-4].status', value: 'repairing' }, { path: 'ops.p-sensor.faults[id=F-4].repair_work_item_ids', push: 'w-sensor-fix5' }, { path: 'work_items', push: repairItem('w-sensor-fix5', '再次修复读数间歇性为零', '2026-09-29T15:31:00+08:00') }, { path: 'runs', push: repairRun('r-sensor-fix5', 'w-sensor-fix5', '2026-09-29T15:31:00+08:00') }] },
          { delay: 1200, event: { type: 'department_activated', project_id: P, work_item_id: 'w-sensor-fix5', run_id: 'r-sensor-fix5', department: 'product', label: '第 2 个修复事项开始，产品再次确认', payload: {} }, patch: [{ path: 'work_items[id=w-sensor-fix5].status', value: 'in_progress' }, { path: 'work_items[id=w-sensor-fix5].queue_reason', value: null }, { path: 'work_items[id=w-sensor-fix5].queue_pos', value: null }, { path: 'runs[id=r-sensor-fix5].department', value: 'product' }, { path: 'runs[id=r-sensor-fix5].phase', value: 'PRODUCT_SPEC' }] },
          { delay: 1400, event: { type: 'x_deployed', project_id: P, department: 'operations', work_item_id: 'w-sensor-fix5', run_id: 'r-sensor-fix5', label: '部署第 2 个修复 r6', payload: { version: 'r6', machine_id: 'm-pi' } }, patch: [{ path: 'ops.p-sensor.env.version', value: 'r6' }, { path: 'ops.p-sensor.releases', push: { version: 'r6', at: '2026-09-29T15:32:00+08:00', method: '常设授权以内', note: '修复 F-4 的第 2 次' } }] },
          { delay: 1400, event: { type: 'x_repair_failed', project_id: P, work_item_id: 'w-sensor-fix5', run_id: 'r-sensor-fix5', label: '第 2 次修复也失败', payload: { fault_id: 'F-4' } }, patch: [{ path: 'ops.p-sensor.faults[id=F-4].failures', value: 2 }] },
          { delay: 1400, event: { type: 'x_auto_repair_stopped', project_id: P, label: '同一故障连续修复失败达到上限，停止自动修复', payload: { fault_id: 'F-4' } }, patch: [{ path: 'ops.p-sensor.faults[id=F-4].status', value: 'repair_stopped' }] },
          { delay: 1400, event: { type: 'x_decision_issued', project_id: P, department: 'operations', label: '发出决定请求：同一故障连续修复失败后停止自动修复', payload: { decision_id: 'd-sensor-repair-stop', kind: 'repair_stopped' } }, patch: [{ path: 'decisions', push: decision('d-sensor-repair-stop', 'repair_stopped', { fault_id: 'F-4', repairs: [{ work_item_id: 'w-sensor-fix4', evidence: '观察窗口内读数再次为零 3 次' }, { work_item_id: 'w-sensor-fix5', evidence: '观察窗口内读数再次为零 2 次' }], running_version: 'r6' }, '#/p/p-sensor/overview', '2026-09-29T15:32:00+08:00', { options: [{ id: 'ack', label: '知道了', kind: 'primary', events: [] }] }) }] },
          { delay: 1200, go: '#/p/p-sensor/overview', event: { type: 'department_activated', project_id: P, department: 'operations', label: '运维房间门口立起「停止自动修复」牌，监控屏列出两次修复编号', payload: {} }, patch: [] }
        ]
      }
    ]
  });
})();
