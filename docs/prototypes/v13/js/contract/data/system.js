// 系统数据：部署、首页、系统状态、机器、执行槽位、工具、模型目录、内置 Prompt 与跨项目场景（BUILD.md 第 8、9 节）
(function () {
  'use strict';
  const Y13 = window.Y13;

  Y13.data.define({
    seed: {
      now: '2026-09-29T15:30:00+08:00',
      deployment: { log_id: 'log-7f3a', boot_id: 'boot-0929-0313', service_version: '0.8.0', api_version: 2, access: 'lan' },
      home: { last_seen_at: '2026-09-26T21:10:00+08:00' },
      system: {
        booted_at: '2026-09-21T09:00:00+08:00',
        auto_resumed: 0,
        provider_ready: { ready: 3, total: 3 },
        catalog_revision: 14,
        drain: { state: 'none', since: null, running: [] },
        disk: { free_gb: 41, threshold_gb: 10, snapshots_gb: 6.2, workspaces_gb: 3.1 },
        check_in: { last_at: '2026-09-22T15:30:00+08:00', every_min: 30, ok: true }
      },
      machines: [
        {
          id: 'm-host', name: '控制主机（小主机）', address: '192.168.1.10', purpose: '控制核心与本机进程，工程构建', kind: 'host',
          version: 1, online: true, last_heartbeat_at: '2026-09-22T15:30:00+08:00', containers: 3, actions: [], late_receipts: [], level: '3.2C'
        },
        {
          id: 'm-study', name: '书房台式机', address: '192.168.1.21', purpose: '质检的检查与试用', kind: 'desktop',
          version: 1, online: true, last_heartbeat_at: '2026-09-22T15:30:00+08:00', containers: 0, actions: [], late_receipts: [], level: '3.2C'
        },
        {
          id: 'm-pi', name: '客厅树莓派', address: '192.168.1.40', purpose: '温湿度监测服务的运行环境', kind: 'pi',
          version: 1, online: true, last_heartbeat_at: '2026-09-22T15:30:00+08:00', containers: 0, actions: [], late_receipts: [], level: '3.2C'
        },
        {
          id: 'm-laptop', name: '笔记本', address: '192.168.1.33', purpose: '外出时的备用执行环境', kind: 'laptop',
          version: 1, online: true, last_heartbeat_at: '2026-09-22T15:30:00+08:00', containers: 0, actions: [], late_receipts: [], level: '3.2C'
        }
      ],
      runtime: { version: 1, slots: { total: 3, used: [] }, queue: [], level: '3.4A' },
      decisions: [
        {
          // 实例升级（可信内核设计说明第 4 节）：发布检查对待发布的提交运行以后，由用户决定是否升级这台电脑上安装的那一份；
          // 请求写在目录流中，不属于任何项目与 run，也不阻塞它们
          id: 'd-instance-upgrade', kind: 'instance_upgrade', project_id: null, work_item_id: null, run_id: null,
          status: 'waiting', issued_at: '2026-09-29T09:00:00+08:00', born_at: '2026-09-29T09:00:00+08:00', version: 1, level: 'pilot',
          blocks: null, view: null, answer: null,
          materials: {
            current: '0.8.0', candidate: '0.9.0', commit: 'main 7c2e1a4',
            checks: [
              { name: '内核差异', ok: true, text: '待发布的提交没有改动内核清单里的路径' },
              { name: '行数', ok: true, text: '内核 2,814 行，没有超过上限 2,840 行' },
              { name: '导入方向', ok: true, text: '内核文件只导入内核文件、标准库与 pydantic' },
              { name: '探针 reference_passes_all', ok: true, text: '参考解法通过全部隐藏检查' },
              { name: '探针 seeded_defect_fails', ok: true, text: '植入缺陷的交付被评分器判为失败' },
              { name: '探针 out_of_scope_write_denied', ok: true, text: '越界写入被工具许可拒绝' },
              { name: '探针 false_release_reported', ok: true, text: '过程检查点报出了质检误放行' },
              { name: '回归场景', ok: true, text: '场景 1 与场景 3：无差别' }
            ]
          },
          options: [
            { id: 'approve', label: '批准升级', kind: 'primary', events: [] },
            { id: 'reject', label: '拒绝', kind: null, events: [] }
          ]
        }
      ],
      default_prompts: {
        product: '你是产品部门。依据用户原文维护 PRD：写清目标、边界、验收条件与非目标，每条要求至少有一条验收条件；用户的新输入逐版本处理，写明新增、修改或保留了哪些要求。回答其他部门的询问时，只依据有效要求与用户原文；需要取舍时写明理由，澄清的结果写进 PRD。',
        engineering: '你是工程部门。依据有效 PRD 实现代码、编写单元测试，并运行命令自测；怎样安排工作由你自己决定。交付说明写明做了什么与处理的缺陷；要求有疑问时询问产品，不自行改变要求。',
        quality: '你是质检部门。依据有效 PRD 在独立副本中验证交付：逐条对照验收条件记录检查结果、证据与主机回执。交付到达之前按 PRD 起草测试用例。发现问题时写明复现步骤与违反的验收条件，提交缺陷记录；要求本身有问题时询问产品；全部验收条件都有通过的检查时给出放行结论。',
        operations: '你是运维部门。接收已采纳交付物的运行责任后，按运行目标观察运行指标，指标都带分母；发现故障时依次确认影响、执行常设授权以内的缓解动作，把修复写成新事项交给产品。常设授权以外的外部动作逐项申请用户授权。'
      },
      catalog: {
        file: { path: '.yudao/catalog.json', revision: 18, reloaded_at: '2026-09-22T11:18:00+08:00', reload_error: null },
        capability_table: {
          source: 'models.dev',
          revision: '2026-09-20',
          models: {
            'kimi-k2.6': { image_input: true },
            'mimo-v2.5': { image_input: true },
            'glm-5': { image_input: false },
            'qwen3-coder-30b': { image_input: false }
          }
        },
        presets: {
          revision: '2026-09-24.1',
          source: 'https://opencode.ai/docs/go/（2026-09-24 采集）',
          schemes: [
            {
              id: 'opencode-go', name: 'OpenCode Go',
              protocols: [
                { protocol: 'responses', base_url: 'https://opencode.ai/zen/go/v1' },
                { protocol: 'chat', base_url: 'https://opencode.ai/zen/go/v1' },
                { protocol: 'messages', base_url: 'https://opencode.ai/zen/go/v1' }
              ],
              auth: 'API Key', headers: ['真实客户端 User-Agent', 'x-opencode-session'],
              models_url: 'https://opencode.ai/zen/go/v1/models', docs_url: 'https://opencode.ai/docs/go/'
            },
            { id: 'custom', name: '自定义', protocols: [], auth: '由用户填写', headers: [], models_url: null, docs_url: null }
          ]
        },
        connections: [
          { id: 'opencode-go-responses', name: 'OpenCode Go · Responses', scheme: 'opencode-go', protocol: 'responses', base_url: 'https://opencode.ai/zen/go/v1', credential_ref: 'OPENCODE_GO_KEY', timeout_sec: 120, models_url: '' },
          { id: 'opencode-go-chat', name: 'OpenCode Go · Chat', scheme: 'opencode-go', protocol: 'chat', base_url: 'https://opencode.ai/zen/go/v1', credential_ref: 'OPENCODE_GO_LAB_KEY', timeout_sec: 120, models_url: '' },
          { id: 'local-custom', name: '本机兼容服务', scheme: 'custom', protocol: 'chat', base_url: 'http://127.0.0.1:8080/v1', credential_ref: null, timeout_sec: 300, models_url: 'http://127.0.0.1:8080/v1/models' }
        ],
        definitions: [
          { id: 'opencode-go-responses/kimi-k2.6', connection_id: 'opencode-go-responses', upstream_model: 'kimi-k2.6', window: 262144, max_output: 32768, image_input: true, image_input_source: '能力表', accepts_required_tool_call: true,reasoning: { levels: ['low', 'medium', 'high'], default_level: 'medium', method: 'effort' }, capacity_accepted: true, admission: { tested_at: '2026-09-22T09:12:00+08:00', actual_model: 'kimi-k2.6', protocol: 'Responses' }, admission_revoked: null },
          { id: 'opencode-go-responses/glm-5', connection_id: 'opencode-go-responses', upstream_model: 'glm-5', window: 204800, max_output: 32768, image_input: false, image_input_source: '能力表', accepts_required_tool_call: true,reasoning: { levels: ['low', 'medium', 'high'], default_level: 'medium', method: 'effort' }, capacity_accepted: true, admission: { tested_at: '2026-09-22T09:14:00+08:00', actual_model: 'glm-5', protocol: 'Responses' }, admission_revoked: null },
          { id: 'opencode-go-responses/mimo-v2.5', connection_id: 'opencode-go-responses', upstream_model: 'mimo-v2.5', window: 1048576, max_output: 65536, image_input: true, image_input_source: '能力表', accepts_required_tool_call: true,reasoning: { levels: ['minimal', 'low', 'medium', 'high'], default_level: 'medium', method: 'effort' }, capacity_accepted: true, admission: { tested_at: '2026-09-22T09:16:00+08:00', actual_model: 'mimo-v2.5', protocol: 'Responses' }, admission_revoked: null },
          { id: 'opencode-go-chat/mimo-v2.5', connection_id: 'opencode-go-chat', upstream_model: 'mimo-v2.5', window: 1048576, max_output: 65536, image_input: true, image_input_source: '能力表', accepts_required_tool_call: true,reasoning: { levels: ['minimal', 'low', 'medium', 'high'], default_level: 'medium', method: 'effort' }, capacity_accepted: true, admission: { tested_at: '2026-09-21T16:40:00+08:00', actual_model: 'mimo-v2.5', protocol: 'Chat Completions' }, admission_revoked: null },
          { id: 'opencode-go-chat/glm-5', connection_id: 'opencode-go-chat', upstream_model: 'glm-5', window: 204800, max_output: 32768, image_input: false, image_input_source: '能力表', accepts_required_tool_call: true,reasoning: null, capacity_accepted: false, admission: null, admission_revoked: null, prefill: '预填自 OpenCode Go · Responses 的同名定义，尚未接受' },
          { id: 'local-custom/qwen3-coder-30b', connection_id: 'local-custom', upstream_model: 'qwen3-coder-30b', window: 131072, max_output: 16384, image_input: false, image_input_source: '能力表', accepts_required_tool_call: false,reasoning: null, capacity_accepted: true, admission: null, admission_revoked: { at: '2026-09-22T11:18:00+08:00', reason: '连接地址由 http://127.0.0.1:8000/v1 改为 http://127.0.0.1:8080/v1', previous: { tested_at: '2026-09-21T10:02:00+08:00', actual_model: 'qwen3-coder-30b', protocol: 'Chat Completions' } } }
        ],
        candidates: {
          'opencode-go-responses': { source: 'https://opencode.ai/zen/go/v1/models', collected_at: '2026-09-22T09:05:00+08:00', ids: ['kimi-k2.6', 'glm-5', 'mimo-v2.5', 'qwen3.6-plus', 'minimax-m2.7', 'deepseek-v4-flash'], unknown_reason: null },
          'opencode-go-chat': { source: 'https://opencode.ai/zen/go/v1/models', collected_at: '2026-09-21T16:31:00+08:00', ids: ['kimi-k2.6', 'glm-5', 'mimo-v2.5', 'qwen3.6-plus', 'minimax-m2.7', 'deepseek-v4-flash'], unknown_reason: null },
          'local-custom': { source: 'http://127.0.0.1:8080/v1/models', collected_at: '2026-09-22T11:20:00+08:00', ids: [], unknown_reason: '请求失败：连接被拒绝（ECONNREFUSED）' }
        },
        credentials: [
          { ref: 'OPENCODE_GO_KEY', state: 'env', sources: { memory: false, env: true, dotenv: false }, version: 'k3', rejected: false, rejected_source: null, note: '宿主进程环境' },
          { ref: 'OPENCODE_GO_LAB_KEY', state: 'dotenv', sources: { memory: false, env: false, dotenv: true }, version: 'k1', rejected: true, rejected_source: 'dotenv', rejected_at: '2026-09-22T15:10:00+08:00', note: '.yudao/.env · 上游拒绝（HTTP 401）' }
        ],
        connection_tests: {
          'opencode-go-responses': { at: '2026-09-22T09:10:00+08:00', ok: true, text: '连接测试通过 · 412 ms' },
          'opencode-go-chat': { at: '2026-09-22T15:12:00+08:00', ok: false, text: '连接测试失败：HTTP 401，凭据被上游拒绝' },
          'local-custom': null
        },
        model_tests: {},
        department_defaults: {
          product: { definition: 'opencode-go-responses/kimi-k2.6', request_level: null },
          engineering: { definition: 'opencode-go-responses/kimi-k2.6', request_level: 'high' },
          quality: { definition: 'opencode-go-responses/mimo-v2.5', request_level: null },
          operations: { level: 'S4', definition: 'opencode-go-responses/kimi-k2.6', request_level: null }
        },
        role_defaults: {
          level: 'S5',
          'prod-manager': { definition: 'opencode-go-responses/kimi-k2.6', request_level: 'medium' },
          'prod-architect': { definition: null, request_level: null },
          'prod-explorer': { definition: 'opencode-go-responses/kimi-k2.6', request_level: 'low' },
          'prod-reviewer': { definition: 'opencode-go-responses/kimi-k2.6', request_level: 'medium' },
          'eng-manager': { definition: 'opencode-go-responses/kimi-k2.6', request_level: 'high' },
          'eng-architect': { definition: 'opencode-go-responses/kimi-k2.6', request_level: 'high' },
          'eng-lead': { definition: 'opencode-go-responses/kimi-k2.6', request_level: 'medium' },
          'eng-explorer': { definition: 'opencode-go-responses/kimi-k2.6', request_level: 'low' },
          'eng-reviewer': { definition: 'opencode-go-responses/kimi-k2.6', request_level: 'medium' },
          'qa-manager': { definition: null, request_level: null },
          'qa-tester': { definition: 'opencode-go-responses/mimo-v2.5', request_level: null },
          'qa-explorer': { definition: 'opencode-go-responses/mimo-v2.5', request_level: 'low' },
          'qa-reviewer': { definition: 'opencode-go-responses/mimo-v2.5', request_level: null }
        },
        role_catalog: {
          level: 'S5',
          product: [
            { id: 'prod-manager', name: '产品部门经理', kind: 'manager', duty: '对外沟通，关注部门做到什么程度，提交产品成果' },
            { id: 'prod-architect', name: '产品架构师', kind: 'architect', duty: '挖掘用户需求，起草 ProductSpec，回答其他部门的询问' },
            { id: 'prod-explorer', name: '产品探索者', kind: 'explorer', duty: '查资料，交回带来源的发现' },
            { id: 'prod-reviewer', name: '产品审查者', kind: 'reviewer', duty: '审查需求与规格' }
          ],
          engineering: [
            { id: 'eng-manager', name: '工程经理', kind: 'manager', duty: '对外沟通，提交工程成果' },
            { id: 'eng-architect', name: '工程架构师', kind: 'architect', duty: '架构与技术设计，起草工程计划' },
            { id: 'eng-lead', name: '主程', kind: 'lead', duty: '按计划实现代码并自测，工作区唯一的写入者' },
            { id: 'eng-explorer', name: '工程探索者', kind: 'explorer', duty: '阅读代码、查阅文档、复现问题' },
            { id: 'eng-reviewer', name: '工程审查者', kind: 'reviewer', duty: '审查设计与代码' }
          ],
          quality: [
            { id: 'qa-manager', name: '质检经理', kind: 'manager', duty: '对外沟通，提交质检结论' },
            { id: 'qa-tester', name: '测试工程师', kind: 'tester', duty: '依据 PRD 设计并运行检查，记录缺陷' },
            { id: 'qa-explorer', name: '质检探索者', kind: 'explorer', duty: '探索性地操作交付物，交回观察' },
            { id: 'qa-reviewer', name: '质检审查者', kind: 'reviewer', duty: '审查检查设计是否覆盖每条验收条件' }
          ]
        }
      },
      tools: {
        level: '3.2B',
        // 网络取回三个部门都有，任何 http 与 https 地址都可以取回（ADR-0038）：这里只汇总最近的取回记录
        network: {
          scope: '三个部门都可以取回任何 http 与 https 地址：只发 GET，不带凭据与 Cookie，拒绝 Yudao 服务自己的地址；取回的内容保存为外部来源工件。',
          recent: [
            { at: '2026-09-29T14:18:00+08:00', url: 'https://developer.mozilla.org/zh-CN/docs/Web/HTML/Element/input/date', work_item_id: 'w-todo-due', project_id: 'p-todo', result: '已取回 · 52 KB' },
            { at: '2026-09-28T11:05:00+08:00', url: 'https://docs.python.org/3/library/heapq.html', work_item_id: 'w-metro-fare', project_id: 'p-metro', result: '已取回 · 36 KB' },
            { at: '2026-09-27T16:40:00+08:00', url: 'https://pypi.org/project/networkx/', work_item_id: 'w-metro-transfer', project_id: 'p-metro', result: '已取回 · 18 KB' },
            { at: '2026-09-27T09:20:00+08:00', url: 'https://stackoverflow.com/questions/3191528', work_item_id: 'w-todo-base', project_id: 'p-todo', result: '已取回 · 21 KB' }
          ]
        },
        // 各项目在设置中写明的 MCP 服务器：怎样启动或连接、哪些部门可以使用，服务器提供的工具全部直接提供（ADR-0038）
        mcp: [
          {
            id: 'mcp-github', project_id: 'p-todo', name: 'GitHub（官方 MCP 服务）', transport: 'stdio', departments: ['engineering', 'quality'],
            last: { at: '2026-09-29T13:42:00+08:00', ok: true, text: '已连接 · 3 个工具' },
            tools: [
              { name: 'search_code', description: '在仓库中搜索代码' },
              { name: 'get_file_contents', description: '读取仓库中的文件' },
              { name: 'create_issue', description: '在仓库中新建 issue' }
            ]
          },
          {
            id: 'mcp-docs', project_id: 'p-metro', name: '文档检索服务', transport: 'http', departments: ['product', 'engineering', 'quality'],
            last: { at: '2026-09-28T10:50:00+08:00', ok: false, text: '连接失败：HTTP 503（服务暂时不可用）' },
            tools: [
              { name: 'lookup', description: '按关键词检索文档' },
              { name: 'annotate', description: '在文档上写批注' }
            ]
          }
        ],
        browser: {
          level: '3.2D',
          name: '浏览器（Playwright MCP）',
          note: '每个动作一个工具。每一步交给模型页面的可访问性结构；模型能看图时同时附上截图，截图另存为证据。不支持图像时只给可访问性结构，不给截图。',
          tools: [
            { name: 'browser_snapshot', description: '读取页面的可访问性结构' },
            { name: 'browser_screenshot', description: '截图' },
            { name: 'browser_navigate', description: '打开地址' },
            { name: 'browser_click', description: '点击元素' },
            { name: 'browser_type', description: '输入文字' }
          ]
        },
        computer_use: {
          level: '3.2D',
          name: 'computer use',
          screen: { width: 1024, height: 768, place: '控制主机上用户的交互桌面' },
          note: '桌面程序在控制主机上用户的交互桌面中运行（桌面会话），开始之前经用户同意，整台控制主机同一时刻只有一个桌面会话。只提供给输入方式包含图像的部门。网页应用使用浏览器工具。',
          tools: [
            { name: 'screenshot', description: '截图' },
            { name: 'left_click', description: '点击' },
            { name: 'type', description: '输入文字' },
            { name: 'key', description: '按键' },
            { name: 'scroll', description: '滚动' }
          ]
        },
        observers: {
          level: 'S5',
          note: '观察者以名称登记，读取范围由控制核心给出，观察者不能扩大。从某个全局位置开始按读取范围订阅事件，结果只以提案提交（#98）。',
          items: [
            { id: 'obs-lessons', name: '教训发现', scope: '全部项目的放行、缺陷记录与采纳事件' },
            { id: 'obs-meta', name: '元观察', scope: '全部项目的正式成果、询问与回答；不读取部门私有上下文' }
          ]
        }
      }
    },
    history: [
      {
        at: '2026-09-26T22:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，磁盘剩余 41 GB',
        payload: { ok: true },
        patch: [
          { path: 'system.check_in.last_at', value: '2026-09-26T22:10:00+08:00' },
          { path: 'system.check_in.ok', value: true }
        ]
      },
      {
        at: '2026-09-27T04:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，服务正常',
        payload: { ok: true },
        patch: [{ path: 'system.check_in.last_at', value: '2026-09-27T04:10:00+08:00' }]
      },
      {
        at: '2026-09-27T10:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，服务正常',
        payload: { ok: true },
        patch: [{ path: 'system.check_in.last_at', value: '2026-09-27T10:10:00+08:00' }]
      },
      {
        at: '2026-09-27T16:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，磁盘剩余 40 GB',
        payload: { ok: true, free_gb: 40 },
        patch: [
          { path: 'system.check_in.last_at', value: '2026-09-27T16:10:00+08:00' },
          { path: 'system.disk.free_gb', value: 40 }
        ]
      },
      {
        at: '2026-09-27T22:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，服务正常',
        payload: { ok: true },
        patch: [{ path: 'system.check_in.last_at', value: '2026-09-27T22:10:00+08:00' }]
      },
      {
        at: '2026-09-28T04:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，服务正常',
        payload: { ok: true },
        patch: [{ path: 'system.check_in.last_at', value: '2026-09-28T04:10:00+08:00' }]
      },
      {
        at: '2026-09-28T09:30:00+08:00', type: 'catalog_revised', level: 'ui',
        label: '重新测试未通过：opencode-go-responses/glm-5 的准入已作废，上游返回的实际模型与定义不符',
        payload: { definition_id: 'opencode-go-responses/glm-5', catalog_revision: 15 },
        patch: [
          { path: 'catalog.definitions[id=opencode-go-responses/glm-5].admission', value: null },
          { path: 'catalog.definitions[id=opencode-go-responses/glm-5].admission_revoked', value: { at: '2026-09-28T09:30:00+08:00', reason: '重新测试未通过：上游返回的实际模型与定义不符' } },
          { path: 'system.catalog_revision', value: 15 }
        ]
      },
      {
        at: '2026-09-28T10:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，服务正常',
        payload: { ok: true },
        patch: [{ path: 'system.check_in.last_at', value: '2026-09-28T10:10:00+08:00' }]
      },
      {
        at: '2026-09-28T16:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，磁盘剩余 39 GB',
        payload: { ok: true, free_gb: 39 },
        patch: [
          { path: 'system.check_in.last_at', value: '2026-09-28T16:10:00+08:00' },
          { path: 'system.disk.free_gb', value: 39 }
        ]
      },
      {
        at: '2026-09-28T22:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，服务正常',
        payload: { ok: true },
        patch: [{ path: 'system.check_in.last_at', value: '2026-09-28T22:10:00+08:00' }]
      },
      {
        at: '2026-09-29T03:10:00+08:00', type: 'x_machine_offline', level: '3.2C',
        label: '笔记本的执行代理心跳中断', payload: { machine_id: 'm-laptop' },
        patch: [
          { path: 'machines[id=m-laptop].online', value: false },
          { path: 'machines[id=m-laptop].last_heartbeat_at', value: '2026-09-29T03:09:40+08:00' }
        ]
      },
      {
        at: '2026-09-29T03:13:00+08:00', type: 'x_run_auto_resumed', level: '3.1',
        label: '控制主机断电后重新启动，自动继续中断的 run 共 2 个', payload: { count: 2 },
        patch: [
          { path: 'system.booted_at', value: '2026-09-29T03:13:00+08:00' },
          { path: 'system.auto_resumed', value: 2 }
        ]
      },
      {
        at: '2026-09-29T04:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机已重新启动，服务正常',
        payload: { ok: true },
        patch: [{ path: 'system.check_in.last_at', value: '2026-09-29T04:10:00+08:00' }]
      },
      {
        at: '2026-09-29T09:00:00+08:00', type: 'x_decision_issued', level: 'pilot',
        label: '发出决定请求：实例升级到 0.9.0，发布检查全部通过',
        payload: { decision_id: 'd-instance-upgrade', kind: 'instance_upgrade' },
        patch: []
      },
      {
        at: '2026-09-29T10:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，磁盘剩余 38 GB',
        payload: { ok: true, free_gb: 38 },
        patch: [
          { path: 'system.check_in.last_at', value: '2026-09-29T10:10:00+08:00' },
          { path: 'system.disk.free_gb', value: 38 }
        ]
      },
      {
        at: '2026-09-29T15:10:00+08:00', type: 'x_check_in', level: 'S4',
        label: '外部报到：控制主机在线，磁盘剩余 38 GB，高于提示线',
        payload: { ok: true, free_gb: 38 },
        patch: [{ path: 'system.check_in.last_at', value: '2026-09-29T15:10:00+08:00' }]
      }
    ],
    scenarios: [
      {
        no: 9, id: 'sc-drain-upgrade', name: '排空与因升级停止', level: '3.1', go: '#/sys/runtime',
        setup: [],
        steps: [
          {
            delay: 1200,
            event: {
              type: 'x_drain_started',
              label: '开始排空：停止开始新事项，等正在进行的 run 结束',
              payload: { running: ['r-todo-due', 'r-metro-transfer'] }
            },
            patch: [{ path: 'system.drain', value: { state: 'draining', since: '2026-09-29T15:30:00+08:00', running: ['r-todo-due', 'r-metro-transfer'] } }]
          },
          {
            delay: 1400,
            event: {
              type: 'qa_submitted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '待办清单增加截止日期的交付在排空期间质检放行',
              payload: { verdict: 'release' }
            },
            patch: [
              { path: 'work_items[id=w-todo-due].status', value: 'released' },
              { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-due' } }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'run_done', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '待办清单的 run 在排空期间结束，排空继续等地铁票价的 run',
              payload: { finished: 'r-todo-due' }
            },
            patch: [
              { path: 'system.drain.running', value: ['r-metro-transfer'] },
              { path: 'runs[id=r-todo-due].phase', value: 'DONE' },
              { path: 'runs[id=r-todo-due].department', value: null },
              { path: 'runs[id=r-todo-due].recovery.state', value: 'completed' },
              { path: 'runs[id=r-todo-due].recovery.reason', value: '质检放行，事项已完成' }
            ]
          },
          {
            delay: 1200,
            event: {
              type: 'x_upgrade_forced',
              label: '用户强制升级：仍在进行的 run 将记为因升级停止',
              payload: { from_version: '0.8.0', to_version: '0.9.0' }
            },
            patch: [
              { path: 'system.drain.state', value: 'forced' },
              { path: 'deployment.service_version', value: '0.9.0' }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'x_run_stopped_for_upgrade', project_id: 'p-metro', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
              label: '地铁票价换乘站的 run 记为因升级停止：事项状态为已停止，旧 run 保留只读',
              payload: { stop_reason: { code: 'upgrade', text: '因升级停止' } }
            },
            patch: [
              { path: 'work_items[id=w-metro-transfer].status', value: 'stopped' },
              { path: 'runs[id=r-metro-transfer].phase', value: 'DONE' },
              { path: 'runs[id=r-metro-transfer].stop_reason', value: { code: 'upgrade', text: '因升级停止' } },
              { path: 'runs[id=r-metro-transfer].yudao_version', value: '0.8.0' },
              { path: 'runs[id=r-metro-transfer].recovery.state', value: 'stopped' },
              { path: 'runs[id=r-metro-transfer].recovery.reason', value: '因升级停止，旧 run 保留只读' },
              { path: 'system.drain.running', value: [] }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'run_created', project_id: 'p-metro', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer-new', department: 'engineering',
              label: '对应事项用项目的起点（采纳成果 r1）重新开始，生成新的 run',
              payload: { start_point: '采纳成果 r1', queue_pos: 1, upgrade_restart: true }
            },
            patch: [
              { path: 'runs', push: {
                id: 'r-metro-transfer-new', work_item_id: 'w-metro-transfer', project_id: 'p-metro',
                yudao_version: '0.9.0', phase: 'QUEUED', department: null, last_department: null, cycle: 0,
                started_at: '2026-09-29T15:30:00+08:00', elapsed_sec: 0, limit_sec: 7200,
                stop_reason: null, recovery: { state: 'running' }, born_at: '2026-09-29T15:30:00+08:00'
              } },
              { path: 'work_items[id=w-metro-transfer].status', value: 'queued' },
              { path: 'work_items[id=w-metro-transfer].queue_reason', value: null },
              { path: 'work_items[id=w-metro-transfer].run_id', value: 'r-metro-transfer-new' }
            ]
          },
          {
            delay: 1200, go: '#/p/p-metro/overview',
            event: {
              type: 'x_queued', project_id: 'p-metro', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer-new',
              label: '因升级重新开始的事项排在地铁票价队列最前面，其余排队事项依次后退',
              payload: { queue_pos: 1, upgrade_restart: true }
            },
            patch: [
              { path: 'work_items[id=w-metro-transfer].queue_pos', value: 1 },
              { path: 'work_items[id=w-metro-card].queue_pos', value: 2 },
              { path: 'work_items[id=w-metro-report].queue_pos', value: 3 }
            ]
          },
          {
            delay: 1200, go: '#/p/p-metro/materials?w=w-metro-transfer',
            label: '资料页只读列出旧 run 的事件，Yudao 版本为升级前的 0.8.0'
          }
        ]
      },
      {
        no: 11, id: 'sc-slot-wait', name: '跨项目并行与等待执行槽位', level: '3.4A', go: '#/home',
        setup: [
          { path: 'runtime.slots.total', value: 2 },
          { path: 'runtime.slots.used', value: [
            { work_item_id: 'w-todo-due', department: 'quality', role: null },
            { work_item_id: 'w-metro-transfer', department: 'engineering', role: null }
          ] },
          { path: 'runs[id=r-metro-transfer].recovery.state', value: 'running' },
          { path: 'runs[id=r-metro-transfer].recovery.reason', value: null },
          { path: 'work_items[id=w-metro-transfer].status', value: 'in_progress' }
        ],
        steps: [
          {
            delay: 1200, go: '#/home',
            event: {
              type: 'x_queued', project_id: 'p-sensor', work_item_id: 'w-sensor-chart',
              label: '三个项目同时有事项要开始：待办清单与地铁票价占着两个执行槽位，温湿度服务的事项停在关闭的入口阀门前',
              payload: {}
            },
            patch: [
              { path: 'runtime.queue', push: { work_item_id: 'w-sensor-chart', project_id: 'p-sensor', since: '2026-09-29T15:30:00+08:00', position: 1, queue_reason: 'slot' } },
              { path: 'work_items[id=w-sensor-chart].status', value: 'queued' },
              { path: 'work_items[id=w-sensor-chart].queue_reason', value: 'slot' },
              { path: 'work_items[id=w-sensor-chart].queue_pos', value: 1 },
              { path: 'runs[id=r-sensor-chart].recovery.state', value: 'running' },
              { path: 'runs[id=r-sensor-chart].recovery.reason', value: '排队中，尚未取得执行槽位' },
              { path: 'runs[id=r-sensor-chart].recovery.unusable', value: null }
            ]
          },
          {
            delay: 1200, go: '#/p/p-sensor/overview',
            event: {
              type: 'x_queued', project_id: 'p-sensor', work_item_id: 'w-sensor-chart',
              label: '概览显示这个事项在等待执行槽位，槽位灯 2/2',
              payload: {}
            },
            patch: []
          },
          {
            delay: 1200, go: '#/p/p-todo/overview',
            event: {
              type: 'qa_submitted', project_id: 'p-todo', work_item_id: 'w-todo-due', run_id: 'r-todo-due', department: 'quality',
              label: '待办清单的交付在质检放行，空出一个执行槽位',
              payload: { verdict: 'release' }
            },
            patch: [
              { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-todo-due' } },
              { path: 'work_items[id=w-todo-due].status', value: 'released' }
            ]
          },
          {
            delay: 1400, go: '#/home',
            event: {
              type: 'x_slot_acquired', project_id: 'p-sensor', work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality',
              label: '等待的事项取得执行槽位，该层入口阀门打开',
              payload: {}
            },
            patch: [
              { path: 'runtime.queue', remove: { key: 'work_item_id', value: 'w-sensor-chart' } },
              { path: 'runtime.slots.used', push: { work_item_id: 'w-sensor-chart', department: 'quality', role: null } },
              { path: 'work_items[id=w-sensor-chart].status', value: 'in_progress' },
              { path: 'work_items[id=w-sensor-chart].queue_reason', value: null },
              { path: 'runs[id=r-sensor-chart].recovery.reason', value: null }
            ]
          },
          {
            delay: 1200, go: '#/p/p-sensor/overview',
            event: {
              type: 'department_activated', project_id: 'p-sensor', work_item_id: 'w-sensor-chart', run_id: 'r-sensor-chart', department: 'quality',
              label: '温湿度服务取得槽位以后质检开始工作',
              payload: {}
            },
            patch: []
          },
          {
            delay: 1200, go: '#/p/p-todo/overview',
            event: {
              type: 'deliverable_adopted', project_id: 'p-todo', work_item_id: 'w-todo-due',
              label: '放行的交付被采纳，成果架上的版本号加一',
              payload: { version: 'r2' }
            },
            patch: [
              { path: 'work_items[id=w-todo-due].status', value: 'adopted' },
              { path: 'projects[id=p-todo].adoptions', push: { version: 'r2', work_item_id: 'w-todo-due', summary: '增加截止日期与逾期提醒', adopted_at: '2026-09-29T15:30:00+08:00' } },
              { path: 'runs[id=r-todo-due].phase', value: 'DONE' },
              { path: 'runs[id=r-todo-due].recovery.state', value: 'completed' },
              { path: 'runs[id=r-todo-due].recovery.reason', value: '质检放行并采纳为 r2' }
            ]
          },
          {
            delay: 1200, go: '#/p/p-metro/overview',
            event: {
              type: 'department_activated', project_id: 'p-metro', work_item_id: 'w-metro-transfer', run_id: 'r-metro-transfer', department: 'engineering',
              label: '地铁票价的换乘站事项继续在工程进行，占用第二个执行槽位',
              payload: {}
            },
            patch: []
          },
          {
            delay: 1200, go: '#/home',
            label: '回到首页：槽位 2/2，温湿度服务与地铁票价各占一个，入口阀门都打开'
          }
        ]
      },
      {
        no: 19, id: 'sc-return-home', name: '离开三天后回来', level: 'ui', go: '#/home',
        setup: [],
        steps: [
          {
            delay: 1800, go: '#/home',
            label: '回到首页，先看顶部的状态项：每一项来自事实，正常的显示灰色的「无」，亮起的项写明数量，点击跳到对应位置。'
          },
          {
            delay: 1800, go: '#/home',
            label: '往下是「待你决定」：跨项目的决定卡片按发出时间排列，写明等了多久、挡住了哪个事项，展开可以看到这个决定需要的材料。'
          },
          {
            delay: 1800, go: '#/home',
            label: '再往下是离开期间的报告：汇总项的数字都能点开，看到来源事件，并在时间轴上标出对应的刻度。'
          },
          {
            delay: 1600, act: 'replay.start',
            label: '开始回放：楼的画面回到上次查看时（9月26日 21:10）的状态；状态项、决定卡片与报告保持现在的内容。'
          },
          {
            delay: 1400, act: 'replay.step',
            label: '时间轴前进到离开期间的第一件关键事实：对应楼层闪一下，灯与小旗按该时刻更新。'
          },
          {
            delay: 1400, act: 'replay.step',
            label: '继续前进：没有关键事实的时段直接跳过，时间轴上用折断符号标出跳过的时长。'
          },
          {
            delay: 1400, act: 'replay.step',
            label: '继续前进：缺陷记录、故障、决定请求等不同种类的刻度用不同颜色，已经播放过的刻度变淡。'
          },
          {
            delay: 1400, act: 'replay.step',
            label: '继续前进：地下室机房的设备与管线同样按该时刻显示，例如笔记本在 9月29日 03:10 以后离线。'
          },
          {
            delay: 1600, act: 'replay.live',
            label: '回到现在：楼的画面恢复实时状态。看完以后点「已看过」，下次的报告从这里开始。'
          }
        ]
      }
    ]
  });
})();
