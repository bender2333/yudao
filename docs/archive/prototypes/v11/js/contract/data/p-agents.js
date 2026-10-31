// openai-agents 增加功能（评测场景 2，FeatBench openai-agents-python-842）：接入已有项目、初始 PRD、决定请求、离开期间的事件与场景
(function () {
  'use strict';
  const Y11 = window.Y11;

  const PRODUCT_PROMPT = '你是产品部门。依据用户原文维护 PRD：写清目标、边界、验收条件与非目标，每条要求至少有一条验收条件；用户的新输入逐版本处理，写明新增、修改或保留了哪些要求。回答其他部门的需求咨询时，只依据有效要求与用户原文；需要取舍时写明理由。';
  const ENGINEERING_PROMPT = '你是工程部门。依据有效 PRD 先写工程计划，计划项逐条对应要求；再按计划实现代码、编写单元测试，并用登记命令自测。交付说明逐条写明完成的计划项与处理的缺陷；实现有疑问时向产品咨询，不自行改变要求。';
  const QUALITY_PROMPT = '你是质检部门。依据有效 PRD 在独立副本中验证交付：逐条对照验收条件记录检查结果、证据与主机回执。发现问题时写明复现步骤与违反的验收条件，给出返工结论；全部验收条件都有通过的检查时给出放行结论。';

  const ISSUE_TEXT = 'I want to be able to pass custom parameters directly to my model provider\'s API when making requests, even if those parameters aren\'t explicitly supported by the standard configuration options. Sometimes different model providers have unique parameters that aren\'t covered by the standard settings, and I need an escape hatch to access these provider-specific features without waiting for the system to add official support.\n\nWhen I configure my model settings, I want to be able to specify a dictionary of arbitrary keyword arguments called "extra_args" that will be passed through to the underlying model API call. These parameters should be completely flexible and not restricted to any predefined set, allowing me to experiment with provider-specific capabilities.\n\nI need this extra_args configuration to work consistently across all my model integrations. When I make API calls through the system, any extra_args I\'ve specified should be merged with other request parameters and passed directly to the model provider. The system should handle cases where I don\'t provide any extra_args by simply not including them in the API call.\n\nWhen I have multiple layers of model settings (like base settings and override settings), I want the extra_args from different configuration levels to be merged together rather than having one completely replace the other. If both my base configuration and my override configuration include extra_args, I want the final settings to combine all the parameters from both sources, with override values taking precedence if there are conflicting keys.\n\nThe system should automatically filter out any None values from the extra_args to ensure clean API requests. I also want appropriate documentation and cautionary notes since not all model providers will support all possible parameters, and I understand that using unsupported parameters might cause errors.\n\nThis functionality should work seamlessly with my existing model configuration workflow without breaking any current features. I should be able to continue using all the standard model settings while having this additional flexibility for provider-specific parameters when I need it.';

  Y11.data.define({
    seed: {
      projects: [
        {
          id: 'p-agents', name: 'openai-agents 增加功能',
          goal: '在 openai-agents-python 上按 issue 增加功能，并保持仓库原有的测试通过。',
          pinned: false, archived: false, source: 'existing', version: 1,
          created_at: '2026-09-27T09:00:00+08:00', last_activity_at: '2026-09-27T09:00:00+08:00',
          adoptions: [],
          born_at: '2026-09-27T09:00:00+08:00',
          level: '3.8'
        }
      ],
      work_items: [
        {
          id: 'w-agents-onboard', project_id: 'p-agents', title: '接入 openai-agents-python', color_index: 1, kind: 'onboarding',
          status: 'in_progress', queue_reason: null, run_id: 'r-agents-onboard', queue_pos: null, version: 1,
          created_at: '2026-09-27T09:00:00+08:00', born_at: '2026-09-27T09:00:00+08:00', level: '3.8'
        },
        {
          id: 'w-agents-842', project_id: 'p-agents', title: '实现 issue 842：ModelSettings 支持 extra_args', color_index: 2, kind: 'change',
          status: 'queued', queue_reason: 'project', run_id: null, queue_pos: 1, version: 1,
          created_at: '2026-09-27T09:30:00+08:00', born_at: '2026-09-27T09:30:00+08:00', level: '3.8'
        }
      ],
      runs: [
        {
          id: 'r-agents-onboard', work_item_id: 'w-agents-onboard', project_id: 'p-agents', yudao_version: '0.8.0', kind: 'onboarding',
          phase: 'PRODUCT_SPEC', department: 'product', last_department: null, cycle: 1,
          started_at: '2026-09-27T09:00:00+08:00', elapsed_sec: 0, limit_sec: 7200,
          waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
          recovery: {
            state: 'running', reason: null, unusable: null,
            last_confirmed: { seq: 0, text: '建档事项已登记，等待产品开始' },
            owner: { id: '产品部门', since: '2026-09-27T09:00:00+08:00' },
            late_results: [], verifications: [], unfinished: [],
            limits: { activations: 3, model_steps: 21, retries: 0 }, auto_resumed_at: null
          },
          inputs: [
            {
              version: 1, kind: 'user',
              text: '接入已有项目 openai-agents-python：读现有代码与文档，写出初始 PRD 与现有结构说明，交用户确认。',
              at: '2026-09-27T09:00:00+08:00', progress: 'accepted', bytes: [0, 62]
            }
          ],
          flow: [
            { seq: 1, at: '2026-09-27T09:00:00+08:00', from: 'user', to: 'product', kind: 'handoff', content: '用户要求：接入 openai-agents-python 并确认现有行为', status: '已接收', event_position: null },
            { seq: 2, at: '2026-09-27T09:45:00+08:00', from: 'product', to: 'engineering', kind: 'handoff', content: '初始 PRD r1：9 条要求（模型设置、模型调用、运行、工具、会话、追踪）', status: '已接收', event_position: null },
            { seq: 3, at: '2026-09-27T09:52:00+08:00', from: 'engineering', to: 'quality', kind: 'handoff', content: '现有结构说明（STRUCTURE.md）与构建、测试回执', status: '已接收', event_position: null },
            { seq: 4, at: '2026-09-27T10:02:00+08:00', from: 'quality', to: 'library', kind: 'delivery', content: '基线核验：9 条要求全部核实，8 条失败用例列为已知缺陷', status: '已接收', event_position: null }
          ],
          requests: [],
          guidance: [],
          messages: {
            product: [
              { seq: 1, at: '2026-09-27T09:00:00+08:00', source: 'user', from: 'user', text: '接入已有项目 openai-agents-python，读现有代码与文档，写初始 PRD 与现有结构说明。', event_position: null },
              { seq: 2, at: '2026-09-27T09:45:00+08:00', source: 'self', from: 'product', text: '初始 PRD r1 已提交：9 条要求', event_position: null }
            ],
            engineering: [
              { seq: 3, at: '2026-09-27T09:46:00+08:00', source: 'other', from: 'product', text: '初始 PRD r1 交接', event_position: null },
              { seq: 4, at: '2026-09-27T09:52:00+08:00', source: 'self', from: 'engineering', text: '现有结构说明已提交：模块、入口、构建与测试', event_position: null }
            ],
            quality: [
              { seq: 5, at: '2026-09-27T09:53:00+08:00', source: 'other', from: 'engineering', text: '现有结构说明交接', event_position: null },
              { seq: 6, at: '2026-09-27T10:02:00+08:00', source: 'self', from: 'quality', text: '基线核验结论：一致（9 条要求全部核实）', event_position: null }
            ],
            operations: []
          },
          actions: [
            {
              id: 'a-agents-1', department: 'product', role: null, tool: 'read_file',
              summary: '阅读 README 与 docs 的对外说明', input: '仓库概况的建议顺序', state: 'done', receipt: null,
              before: '快照 8dfd6ff', after: '快照 8dfd6ff（只读）', machine_id: 'm-host', at: '2026-09-27T09:05:00+08:00'
            },
            {
              id: 'a-agents-2', department: 'product', role: null, tool: 'search',
              summary: '搜索 ModelSettings、extra_args 与公开入口', input: '初始 PRD 的要求条目', state: 'done', receipt: null,
              before: '快照 8dfd6ff', after: '快照 8dfd6ff（只读）', machine_id: 'm-host', at: '2026-09-27T09:15:00+08:00'
            },
            {
              id: 'a-agents-3', department: 'engineering', role: null, tool: 'read_range',
              summary: '按区间阅读 src/agents 的入口与模块边界', input: '现有结构说明的模块一节', state: 'done', receipt: null,
              before: '快照 8dfd6ff', after: '快照 8dfd6ff（只读）', machine_id: 'm-host', at: '2026-09-27T09:30:00+08:00'
            },
            {
              id: 'a-agents-4', department: 'engineering', role: null, tool: 'run_command',
              summary: '执行登记命令 pytest 核实构建与测试', input: '现有结构说明的构建与测试一节', state: 'done',
              receipt: { command: 'pytest', argv: ['python', '-m', 'pytest', '-q'], exit_code: 1, output: '8 failed, 331 passed in 13.2s', truncated: false, timed_out: false, duration_ms: 13400, snapshot: 'snap-8dfd6ff' },
              before: '快照 8dfd6ff', after: '快照 8dfd6ff（未改动）', machine_id: 'm-host', at: '2026-09-27T09:48:00+08:00'
            },
            {
              id: 'a-agents-5', department: 'quality', role: null, tool: 'run_check',
              summary: '质检独立运行已有测试（检查副本）', input: '初始 PRD 的验收一节', state: 'done',
              receipt: { command: 'pytest', argv: ['python', '-m', 'pytest', '-q'], exit_code: 1, output: '8 failed, 331 passed in 13.4s', truncated: false, timed_out: false, duration_ms: 13600, snapshot: 'qa-8dfd6ff' },
              before: '检查副本 8dfd6ff', after: '检查副本 8dfd6ff（未改动）', machine_id: 'm-study', at: '2026-09-27T09:56:00+08:00'
            },
            {
              id: 'a-agents-6', department: 'quality', role: null, tool: 'run_check',
              summary: '运行 ruff check 核实静态检查', input: '现有结构说明的构建与测试一节', state: 'done',
              receipt: { command: 'ruff', argv: ['ruff', 'check', 'src', 'tests'], exit_code: 0, output: 'All checks passed!', truncated: false, timed_out: false, duration_ms: 900, snapshot: 'qa-8dfd6ff' },
              before: '检查副本 8dfd6ff', after: '检查副本 8dfd6ff（未改动）', machine_id: 'm-study', at: '2026-09-27T09:58:00+08:00'
            }
          ],
          trials: [],
          contexts: {
            product: [
              {
                id: 'ctx-agents-p1', at: '2026-09-27T09:01:00+08:00', title: '产品激活 1（建档）', attempt_id: 'att-agents-01',
                sources: [{ label: '仓库概况', version: 'existing_overview', included: true }, { label: '用户原文', version: 'v1', included: true }, { label: '建档产品说明', version: '默认 v0', included: true }]
              }
            ],
            engineering: [
              {
                id: 'ctx-agents-e1', at: '2026-09-27T09:47:00+08:00', title: '工程激活 1（建档）', attempt_id: 'att-agents-02',
                sources: [{ label: '仓库概况', version: 'existing_overview', included: true }, { label: '初始 PRD', version: '初始 PRD r1', included: true }, { label: '建档工程说明', version: '默认 v0', included: true }]
              }
            ],
            quality: [
              {
                id: 'ctx-agents-q1', at: '2026-09-27T09:54:00+08:00', title: '质检激活 1（建档）', attempt_id: 'att-agents-03',
                sources: [{ label: '初始 PRD', version: '初始 PRD r1', included: true }, { label: '快照', version: '8dfd6ff', included: true }, { label: '建档质检说明', version: '默认 v0', included: true }]
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
              { id: 'prod-architect', name: '产品架构师', kind: 'architect', status: 'returned', model: 'opencode-go-responses/kimi-k2.6', task: '初始 PRD r1 已提交' },
              { id: 'prod-explorer', name: '产品探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'prod-reviewer', name: '产品审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null }
            ],
            engineering: [
              { id: 'eng-manager', name: '工程经理', kind: 'manager', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'eng-architect', name: '工程架构师', kind: 'architect', status: 'returned', model: 'opencode-go-responses/kimi-k2.6', task: '现有结构说明已提交' },
              { id: 'eng-lead', name: '主程', kind: 'lead', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'eng-explorer', name: '工程探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null },
              { id: 'eng-reviewer', name: '工程审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/kimi-k2.6', task: null }
            ],
            quality: [
              { id: 'qa-manager', name: '质检经理', kind: 'manager', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null },
              { id: 'qa-tester', name: '测试工程师', kind: 'tester', status: 'returned', model: 'opencode-go-responses/mimo-v2.5', task: '基线核验结论：一致' },
              { id: 'qa-explorer', name: '质检探索者', kind: 'explorer', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null },
              { id: 'qa-reviewer', name: '质检审查者', kind: 'reviewer', status: 'idle', model: 'opencode-go-responses/mimo-v2.5', task: null }
            ]
          },
          ledger: {
            level: 'S5',
            product: { items: [], facts: [], questions: [], progress: [] },
            engineering: { items: [], facts: [], questions: [], progress: [] },
            quality: { items: [], facts: [], questions: [], progress: [] }
          },
          attempts: [
            {
              id: 'att-agents-01', logical_call_id: 'call-agents-p1', department: 'product', role: 'prod-architect', kind: 'work', n: 1, of: 3, status: 'succeeded',
              started_at: '2026-09-27T09:02:00+08:00', duration_ms: 42600, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 28400, output: 3860, cache_read: 0, total: 32260, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: null, sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-agents-02', logical_call_id: 'call-agents-p2', department: 'product', role: 'prod-architect', kind: 'work', n: 2, of: 3, status: 'succeeded',
              started_at: '2026-09-27T09:24:00+08:00', duration_ms: 38400, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 32100, output: 3120, cache_read: 8192, total: 35220, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: null, sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-agents-03', logical_call_id: 'call-agents-e1', department: 'engineering', role: 'eng-architect', kind: 'work', n: 1, of: 3, status: 'succeeded',
              started_at: '2026-09-27T09:47:00+08:00', duration_ms: 34200, provider: 'opencode-go-responses',
              requested_model: 'kimi-k2.6', actual_model: 'kimi-k2.6',
              usage: { input: 24800, output: 2680, cache_read: 6144, total: 27480, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'kimi-k2.6', window: 262144, max_output: 32768, source: '部门默认', request_level: 'high', sent_level: 'high', prompt_version: 0 },
              semantic_units: []
            },
            {
              id: 'att-agents-04', logical_call_id: 'call-agents-q1', department: 'quality', role: 'qa-tester', kind: 'work', n: 1, of: 3, status: 'succeeded',
              started_at: '2026-09-27T09:54:00+08:00', duration_ms: 31200, provider: 'opencode-go-responses',
              requested_model: 'mimo-v2.5', actual_model: 'mimo-v2.5',
              usage: { input: 18600, output: 2140, cache_read: 0, total: 20740, cost: null }, error: null,
              target: { connection: 'opencode-go-responses', protocol: 'Responses', base_url: 'https://opencode.ai/zen/go/v1', model: 'mimo-v2.5', window: 1048576, max_output: 65536, source: '部门默认', request_level: null, sent_level: 'medium', prompt_version: 0 },
              semantic_units: []
            }
          ],
          source: null,
          level: '3.8'
        }
      ],
      materials: [
        {
          id: 'm-agents-intend-1', project_id: 'p-agents', work_item_id: 'w-agents-onboard', kind: 'intend', version: 1,
          title: '用户原文（接入）', at: '2026-09-27T09:00:00+08:00', files: null, verdict: null, level: '3.8',
          text: '接入已有项目 openai-agents-python：读现有代码与文档，写出初始 PRD 与现有结构说明，交用户确认。'
        },
        {
          id: 'm-agents-prd-1', project_id: 'p-agents', work_item_id: 'w-agents-onboard', kind: 'prd', version: 1,
          title: '初始 PRD r1', at: '2026-09-27T09:45:00+08:00', files: null, verdict: null, level: '3.8',
          accepted_from: '用户输入 v1',
          text: '# 目标\nopenai-agents-python 是构建智能体应用的 Python 库；本次接入记录它现有的对外能力，作为以后变更与核验的基线。\n\n# 要求与核实方式\n- [模型设置] ModelSettings 保存模型调用参数，能够序列化；多层设置合并（resolve）时按覆盖方优先\n- [模型调用] 调用 OpenAI Chat Completions 接口时透传设置里的参数\n- [模型调用] 调用 OpenAI Responses 接口时透传设置里的参数\n- [模型调用] 通过 LiteLLM 扩展调用时透传设置里的参数\n- [运行] Runner 驱动工具调用循环，支持流式事件与运行结果\n- [工具] 函数工具按 JSON schema 校验参数；MCP 服务可以作为工具接入\n- [会话] 会话保存与取回对话历史；SQLite 会话可用\n- [追踪] 运行产生 trace 与 span，可以导出\n- [命令行] 仓库的示例入口可以在不调用真实模型的情况下运行\n\n# 边界\nexamples/ 与 tests/ 不作为产品行为承诺，只用于核实；标为实验的特性不在本次范围。\n\n# 约束\nPython 3.9 及以上；依赖见 pyproject.toml。\n\n# 验收\npython -m pytest -q 运行仓库测试；ruff check src tests 通过。\n\n# 现有缺陷\n基线核验记录：8 条用例因缺少 API key 或环境不符失败，列为已知缺陷。\n\n# 非目标\n不包含尚未发布的实验特性与云端服务。'
        },
        {
          id: 'm-agents-structure-1', project_id: 'p-agents', work_item_id: 'w-agents-onboard', kind: 'note', version: 1,
          title: '现有结构说明（STRUCTURE.md）', at: '2026-09-27T09:52:00+08:00', files: null, verdict: null, level: '3.8',
          text: '# 现有结构说明（STRUCTURE.md）\n## 总体\n单一 Python 包，源码在 src/agents，测试在 tests/，示例在 examples/；用 pyproject.toml 管理依赖与工具配置。\n\n## 模块\n- src/agents/agent.py：Agent 定义\n- src/agents/run.py：Runner 与运行循环\n- src/agents/model_settings.py：模型设置、序列化与合并\n- src/agents/models/openai_chatcompletions.py、openai_responses.py、litellm_model.py：三种模型适配\n- src/agents/tool.py 与 src/agents/mcp/：函数工具与 MCP\n- src/agents/memory/：会话存储\n- src/agents/tracing/：追踪\n\n## 入口\n- 库入口：src/agents/__init__.py；示例入口见 examples/。\n\n## 构建与测试\n- pytest：python -m pytest -q（Python 3.9；约 13 秒；退出 1——8 条用例因缺少 API key 或环境不符失败）\n- ruff check src tests（退出 0）\n\n## 要求所在的位置\n- [模型设置] src/agents/model_settings.py\n- [模型调用] src/agents/models/\n- [运行] src/agents/run.py\n- [工具] src/agents/tool.py、src/agents/mcp/\n- [会话] src/agents/memory/\n- [追踪] src/agents/tracing/\n\n## 约定与注意事项\n- 需要网络或 API key 的用例不在基线检查中运行；筛选清单见资料页。'
        },
        {
          id: 'm-agents-842-i1', project_id: 'p-agents', work_item_id: 'w-agents-842', kind: 'intend', version: 1,
          title: '用户原文（issue 842）', at: '2026-09-27T09:30:00+08:00', files: null, verdict: null, level: '3.8',
          text: ISSUE_TEXT
        }
      ],
      project_settings: {
        'p-agents': {
          version: 1, level: '3.8',
          departments: {
            product: { version: 1, model: null, level: null, prompt_version: null, prompt_text: null },
            engineering: { version: 1, model: null, level: null, prompt_version: null, prompt_text: null },
            quality: { version: 1, model: null, level: null, prompt_version: null, prompt_text: null }
          },
          commands: [
            { name: 'pytest', argv: ['python', '-m', 'pytest', '-q'], args: [], timeout_sec: 900, output_limit: 200000, version: 1 },
            { name: 'ruff', argv: ['ruff', 'check', 'src', 'tests'], args: [], timeout_sec: 300, output_limit: 100000, version: 1 }
          ],
          tools: [
            { id: 'network', label: '网络取回', scope: '只读取回：pypi.org、docs.python.org', approval: '超出范围时逐次批准' }
          ],
          machines: [
            { machine_id: 'm-host', dirs: ['工作区'], operations: ['pytest', 'ruff'], runtime_env: false, standing: false }
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
          id: 'd-agents-prd', kind: 'initial_prd', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard',
          status: 'waiting', issued_at: '2026-09-27T10:05:00+08:00', born_at: '2026-09-27T10:05:00+08:00', version: 1,
          blocks: { scope: 'work_item', work_item_id: 'w-agents-onboard', queued_behind: 1 },
          materials: {
            prd_summary: '初始 PRD：9 条要求，覆盖模型设置、模型调用、运行、工具、会话与追踪；8 条既有失败用例列为已知缺陷',
            prd_material_id: 'm-agents-prd-1',
            structure_material_id: 'm-agents-structure-1'
          },
          view: '#/p/p-agents/w/w-agents-onboard/materials',
          answer: null,
          options: [
            {
              id: 'confirm', label: '确认初始 PRD', kind: 'primary', events: [
                {
                  type: 'baseline_adopted', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard',
                  label: '用户确认初始 PRD，代码快照成为第一次采纳（基线）', payload: { version: '基线', work_item_id: 'w-agents-onboard' },
                  patch: [
                    { path: 'projects[id=p-agents].adoptions', push: { version: '基线', work_item_id: 'w-agents-onboard', summary: '接入时的代码快照与初始 PRD', adopted_at: '2026-09-29T15:30:00+08:00' } },
                    { path: 'work_items[id=w-agents-onboard].status', value: 'adopted' },
                    { path: 'projects[id=p-agents].last_activity_at', value: '2026-09-29T15:30:00+08:00' }
                  ]
                }
              ]
            },
            {
              id: 'revise', label: '提出修改', kind: null, note_required: true, events: [
                {
                  type: 'onboarding_revision_started', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard',
                  label: '用户提出修改，建档进入新一轮', payload: { base_event: 'initial_prd_proposed' },
                  patch: [
                    {
                      path: 'runs', push: {
                        id: 'r-agents-onboard-2', work_item_id: 'w-agents-onboard', project_id: 'p-agents', yudao_version: '0.8.0', kind: 'onboarding',
                        phase: 'PRODUCT_SPEC', department: 'product', last_department: null, cycle: 1,
                        started_at: '2026-09-29T15:30:00+08:00', elapsed_sec: 0, limit_sec: 7200,
                        waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
                        recovery: {
                          state: 'running', reason: null, unusable: null,
                          last_confirmed: { seq: 0, text: '修改轮已登记，等待产品开始' },
                          owner: { id: '产品部门', since: '2026-09-29T15:30:00+08:00' },
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
                          product: { items: [], facts: [], questions: [], progress: [] },
                          engineering: { items: [], facts: [], questions: [], progress: [] },
                          quality: { items: [], facts: [], questions: [], progress: [] }
                        },
                        attempts: [], source: null, born_at: '2026-09-29T15:30:00+08:00'
                      }
                    },
                    { path: 'work_items[id=w-agents-onboard].status', value: 'in_progress' },
                    { path: 'work_items[id=w-agents-onboard].queue_reason', value: null },
                    { path: 'work_items[id=w-agents-onboard].queue_pos', value: null },
                    { path: 'work_items[id=w-agents-onboard].run_id', value: 'r-agents-onboard-2' },
                    { path: 'projects[id=p-agents].last_activity_at', value: '2026-09-29T15:30:00+08:00' }
                  ]
                },
                {
                  type: 'run_created', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard-2',
                  label: '修改轮的 run 创建（依据上一轮候选与修改意见）', payload: { kind: 'onboarding', onboarding_basis: 'initial_prd_proposed' }, patch: []
                },
                {
                  type: 'user_input_received', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard-2',
                  label: '用户的修改意见作为输入进入新一轮', payload: { version: 2 },
                  patch: [{
                    path: 'runs[id=r-agents-onboard-2].inputs', push: {
                      version: 2, kind: 'user', text: '（随回答提交的修改意见）', at: '2026-09-29T15:30:00+08:00', progress: 'received', bytes: null
                    }
                  }]
                }
              ]
            }
          ]
        }
      ]
    },
    history: [
      {
        at: '2026-09-27T09:00:00+08:00', type: 'project_registered', project_id: 'p-agents', level: '3.8',
        label: '接入已有项目「openai-agents 增加功能」（源目录 openai-agents-python）',
        payload: { source: 'existing', name: 'openai-agents 增加功能' }, patch: []
      },
      {
        at: '2026-09-27T09:00:00+08:00', type: 'work_item_created', project_id: 'p-agents', work_item_id: 'w-agents-onboard', level: '3.8',
        label: '登记建档事项「接入 openai-agents-python」，只读采集代码快照',
        payload: {
          kind: 'onboarding',
          snapshot: { source_dir: 'openai-agents-python', commit: '8dfd6ff35c1b', branch: 'main', dirty: false, tree_digest: 'snap-8dfd6ff', files: 363, bytes: 1812280 }
        },
        patch: [
          { path: 'work_items[id=w-agents-onboard].status', value: 'in_progress' },
          { path: 'projects[id=p-agents].last_activity_at', value: '2026-09-27T09:00:00+08:00' }
        ]
      },
      {
        at: '2026-09-27T09:00:00+08:00', type: 'run_created', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', level: '3.8',
        label: '建档 run 创建，产品部门开始阅读已有项目', payload: { kind: 'onboarding' }, patch: []
      },
      {
        at: '2026-09-27T09:00:00+08:00', type: 'x_slot_acquired', project_id: 'p-agents', work_item_id: 'w-agents-onboard', level: '3.8',
        label: '建档事项取得执行槽位', payload: { department: 'product' },
        patch: [{ path: 'runtime.slots.used', push: { work_item_id: 'w-agents-onboard', department: 'product', role: null } }]
      },
      {
        at: '2026-09-27T09:00:00+08:00', type: 'department_activated', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'product', level: '3.8',
        label: '产品部门从仓库概况开始阅读已有项目', payload: {}, patch: []
      },
      {
        at: '2026-09-27T09:05:00+08:00', type: 'tool_started', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'product', level: '3.8',
        label: '产品阅读 README 与 docs', payload: { tool: 'read_file', target: 'README.md' }, patch: []
      },
      {
        at: '2026-09-27T09:15:00+08:00', type: 'tool_started', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'product', level: '3.8',
        label: '产品搜索 ModelSettings 与公开入口', payload: { tool: 'search', query: 'ModelSettings' }, patch: []
      },
      {
        at: '2026-09-27T09:30:00+08:00', type: 'work_item_created', project_id: 'p-agents', work_item_id: 'w-agents-842', level: '3.8',
        label: '用户提交 issue 842，事项在大厅排队（建档进行中）', payload: { kind: 'change' },
        patch: [{ path: 'projects[id=p-agents].last_activity_at', value: '2026-09-27T09:30:00+08:00' }]
      },
      {
        at: '2026-09-27T09:30:00+08:00', type: 'user_input_received', project_id: 'p-agents', level: '3.8',
        label: '用户提交 issue 842 的需求原文（ModelSettings 透传 extra_args）',
        payload: { version: 1, material_id: 'm-agents-842-i1' }, patch: []
      },
      {
        at: '2026-09-27T09:45:00+08:00', type: 'spec_accepted', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'product', level: '3.8',
        label: '产品的初始 PRD 被接纳（9 条要求，覆盖现有对外能力）', payload: { material_id: 'm-agents-prd-1' },
        patch: [{ path: 'runs[id=r-agents-onboard].elapsed_sec', value: 2700 }]
      },
      {
        at: '2026-09-27T09:46:00+08:00', type: 'transition', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', level: '3.8',
        label: '初始 PRD r1 交给工程部门核对现有结构', payload: { from: 'product', to: 'engineering', artifact: 'prd' },
        patch: [
          { path: 'runs[id=r-agents-onboard].department', value: 'engineering' },
          { path: 'runs[id=r-agents-onboard].last_department', value: 'product' },
          { path: 'runs[id=r-agents-onboard].elapsed_sec', value: 2760 },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-agents-onboard' } },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-agents-onboard', department: 'engineering', role: null } }
        ]
      },
      {
        at: '2026-09-27T09:47:00+08:00', type: 'department_activated', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'engineering', level: '3.8',
        label: '工程部门读清单、构建与测试配置，核实命令', payload: {}, patch: []
      },
      {
        at: '2026-09-27T09:50:00+08:00', type: 'structure_accepted', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'engineering', level: '3.8',
        label: '工程的现有结构说明被接纳，主机生成 STRUCTURE.md', payload: { material_id: 'm-agents-structure-1' },
        patch: [{ path: 'runs[id=r-agents-onboard].elapsed_sec', value: 3000 }]
      },
      {
        at: '2026-09-27T09:52:00+08:00', type: 'transition', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', level: '3.8',
        label: '结构说明与回执送到质检部门', payload: { from: 'engineering', to: 'quality', artifact: 'box' },
        patch: [
          { path: 'runs[id=r-agents-onboard].department', value: 'quality' },
          { path: 'runs[id=r-agents-onboard].last_department', value: 'engineering' },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-agents-onboard' } },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-agents-onboard', department: 'quality', role: null } }
        ]
      },
      {
        at: '2026-09-27T09:53:00+08:00', type: 'department_activated', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'quality', level: '3.8',
        label: '质检部门自己找出测试命令并运行已有测试', payload: {}, patch: []
      },
      {
        at: '2026-09-27T10:00:00+08:00', type: 'baseline_review_accepted', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'quality', level: '3.8',
        label: '基线核验：9 条要求全部核实，结论一致；8 条失败用例记为现有缺陷', payload: {},
        patch: [{ path: 'runs[id=r-agents-onboard].elapsed_sec', value: 3600 }]
      },
      {
        at: '2026-09-27T10:02:00+08:00', type: 'run_done', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'quality', level: '3.8',
        label: '建档 run 结束（停止原因：基线核验通过）', payload: { code: 'baseline_verified', text: '基线核验通过' },
        patch: [
          { path: 'runs[id=r-agents-onboard].phase', value: 'DONE' },
          { path: 'runs[id=r-agents-onboard].department', value: null },
          { path: 'runs[id=r-agents-onboard].last_department', value: 'quality' },
          { path: 'runs[id=r-agents-onboard].stop_reason', value: { code: 'baseline_verified', text: '基线核验通过' } },
          { path: 'runs[id=r-agents-onboard].recovery.state', value: 'terminated' },
          { path: 'runs[id=r-agents-onboard].recovery.reason', value: '基线核验通过，run 结束，等待用户确认初始 PRD' },
          { path: 'runs[id=r-agents-onboard].elapsed_sec', value: 3720 },
          { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-agents-onboard' } }
        ]
      },
      {
        at: '2026-09-27T10:04:00+08:00', type: 'initial_prd_proposed', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', level: '3.8',
        label: '结算：写出建档候选（初始 PRD、结构说明与基线核验）',
        payload: { prd_material_id: 'm-agents-prd-1', structure_material_id: 'm-agents-structure-1' }, patch: []
      },
      {
        at: '2026-09-27T10:05:00+08:00', type: 'project_decision_requested', project_id: 'p-agents', work_item_id: 'w-agents-onboard', level: '3.8',
        label: '发出决定请求：确认接入已有项目的初始 PRD', payload: { decision_id: 'd-agents-prd', kind: 'initial_prd' },
        patch: [
          { path: 'decisions[id=d-agents-prd].status', value: 'waiting' },
          { path: 'work_items[id=w-agents-onboard].status', value: 'queued' },
          { path: 'work_items[id=w-agents-onboard].queue_reason', value: 'decision' },
          { path: 'work_items[id=w-agents-onboard].queue_pos', value: 0 },
          { path: 'work_items[id=w-agents-842].queue_reason', value: 'decision' },
          { path: 'work_items[id=w-agents-842].queue_pos', value: 1 },
          { path: 'projects[id=p-agents].last_activity_at', value: '2026-09-27T10:05:00+08:00' }
        ]
      }
    ],
    scenarios: [
      {
        no: 13, id: 'sc-agents-onboard', name: '接入已有项目并确认初始 PRD', level: '3.8', go: '#/p/p-agents/overview',
        setup: [
          { path: 'decisions', remove: { key: 'id', value: 'd-agents-prd' } },
          { path: 'work_items', remove: { key: 'id', value: 'w-agents-842' } },
          { path: 'work_items[id=w-agents-onboard].status', value: 'in_progress' },
          { path: 'work_items[id=w-agents-onboard].queue_reason', value: null },
          { path: 'work_items[id=w-agents-onboard].queue_pos', value: null },
          { path: 'runs[id=r-agents-onboard].phase', value: 'PRODUCT_SPEC' },
          { path: 'runs[id=r-agents-onboard].department', value: 'product' },
          { path: 'runs[id=r-agents-onboard].last_department', value: null },
          { path: 'runs[id=r-agents-onboard].stop_reason', value: null },
          { path: 'runs[id=r-agents-onboard].recovery.state', value: 'running' },
          { path: 'runs[id=r-agents-onboard].recovery.reason', value: null },
          { path: 'runs[id=r-agents-onboard].elapsed_sec', value: 0 },
          { path: 'runtime.slots.used', push: { work_item_id: 'w-agents-onboard', department: 'product', role: null } }
        ],
        steps: [
          {
            delay: 1200,
            event: {
              type: 'department_activated', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'product',
              label: '产品从大厅搬来一摞旧档案，按仓库概况的顺序开始阅读', payload: {}
            },
            patch: []
          },
          {
            delay: 1400,
            event: {
              type: 'tool_started', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'product',
              label: '产品阅读 README 与 docs', payload: { tool: 'read_file', target: 'README.md' }
            },
            patch: []
          },
          {
            delay: 1400,
            event: {
              type: 'tool_started', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'product',
              label: '产品搜索公开入口与模型设置的实现', payload: { tool: 'search', query: 'ModelSettings' }
            },
            patch: []
          },
          {
            delay: 1600,
            event: {
              type: 'spec_accepted', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'product',
              label: '初始 PRD r1 被接纳：9 条要求覆盖现有对外能力', payload: { material_id: 'm-agents-prd-1' }
            },
            patch: [{ path: 'runs[id=r-agents-onboard].elapsed_sec', value: 2700 }]
          },
          {
            delay: 1200,
            event: {
              type: 'transition', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard',
              label: '初始 PRD r1 交给工程部门核对现有结构', payload: { from: 'product', to: 'engineering', artifact: 'prd' }
            },
            patch: [
              { path: 'runs[id=r-agents-onboard].department', value: 'engineering' },
              { path: 'runs[id=r-agents-onboard].last_department', value: 'product' },
              { path: 'runs[id=r-agents-onboard].elapsed_sec', value: 2760 },
              { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-agents-onboard' } },
              { path: 'runtime.slots.used', push: { work_item_id: 'w-agents-onboard', department: 'engineering', role: null } }
            ]
          },
          {
            delay: 1200,
            event: {
              type: 'department_activated', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'engineering',
              label: '工程读清单、构建与测试配置，并用登记命令核实', payload: {}
            },
            patch: []
          },
          {
            delay: 1600,
            event: {
              type: 'tool_started', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'engineering',
              label: '工程按区间阅读 src/agents 的入口与模块边界', payload: { tool: 'read_range', target: 'src/agents' }
            },
            patch: []
          },
          {
            delay: 1600,
            event: {
              type: 'structure_accepted', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'engineering',
              label: '工程的现有结构说明被接纳，主机生成 STRUCTURE.md', payload: { material_id: 'm-agents-structure-1' }
            },
            patch: [{ path: 'runs[id=r-agents-onboard].elapsed_sec', value: 3000 }]
          },
          {
            delay: 1200,
            event: {
              type: 'transition', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard',
              label: '结构说明与回执送到质检部门', payload: { from: 'engineering', to: 'quality', artifact: 'box' }
            },
            patch: [
              { path: 'runs[id=r-agents-onboard].department', value: 'quality' },
              { path: 'runs[id=r-agents-onboard].last_department', value: 'engineering' },
              { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-agents-onboard' } },
              { path: 'runtime.slots.used', push: { work_item_id: 'w-agents-onboard', department: 'quality', role: null } }
            ]
          },
          {
            delay: 1200,
            event: {
              type: 'department_activated', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'quality',
              label: '质检自己找出测试命令，在检查副本中运行', payload: {}
            },
            patch: []
          },
          {
            delay: 1600,
            event: {
              type: 'baseline_review_accepted', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'quality',
              label: '基线核验结论一致：9 条要求全部核实，8 条失败用例记为现有缺陷', payload: {}
            },
            patch: [{ path: 'runs[id=r-agents-onboard].elapsed_sec', value: 3600 }]
          },
          {
            delay: 1400,
            event: {
              type: 'run_done', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard', department: 'quality',
              label: '建档 run 结束（停止原因：基线核验通过）', payload: { code: 'baseline_verified', text: '基线核验通过' }
            },
            patch: [
              { path: 'runs[id=r-agents-onboard].phase', value: 'DONE' },
              { path: 'runs[id=r-agents-onboard].department', value: null },
              { path: 'runs[id=r-agents-onboard].last_department', value: 'quality' },
              { path: 'runs[id=r-agents-onboard].stop_reason', value: { code: 'baseline_verified', text: '基线核验通过' } },
              { path: 'runs[id=r-agents-onboard].recovery.state', value: 'terminated' },
              { path: 'runs[id=r-agents-onboard].elapsed_sec', value: 3720 },
              { path: 'runtime.slots.used', remove: { key: 'work_item_id', value: 'w-agents-onboard' } }
            ]
          },
          {
            delay: 1200,
            event: {
              type: 'initial_prd_proposed', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard',
              label: '结算：写出建档候选（初始 PRD、结构说明与基线核验）',
              payload: { prd_material_id: 'm-agents-prd-1', structure_material_id: 'm-agents-structure-1' }
            },
            patch: []
          },
          {
            delay: 1600,
            event: {
              type: 'project_decision_requested', project_id: 'p-agents', work_item_id: 'w-agents-onboard',
              label: '发出决定请求：确认接入已有项目的初始 PRD', payload: { decision_id: 'd-agents-prd', kind: 'initial_prd' }
            },
            patch: [
              {
                path: 'decisions', push: {
                  id: 'd-agents-prd', kind: 'initial_prd', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard',
                  status: 'waiting', issued_at: '2026-09-29T15:30:00+08:00', born_at: '2026-09-29T15:30:00+08:00', version: 1,
                  blocks: { scope: 'work_item', work_item_id: 'w-agents-onboard', queued_behind: 1 },
                  materials: {
                    prd_summary: '初始 PRD：9 条要求，覆盖模型设置、模型调用、运行、工具、会话与追踪；8 条既有失败用例列为已知缺陷',
                    prd_material_id: 'm-agents-prd-1',
                    structure_material_id: 'm-agents-structure-1'
                  },
                  view: '#/p/p-agents/w/w-agents-onboard/materials',
                  answer: null,
                  options: [
                    { id: 'confirm', label: '确认初始 PRD', kind: 'primary', events: [] },
                    { id: 'revise', label: '提出修改', kind: null, note_required: true, events: [] }
                  ]
                }
              },
              { path: 'work_items[id=w-agents-onboard].status', value: 'queued' },
              { path: 'work_items[id=w-agents-onboard].queue_reason', value: 'decision' },
              { path: 'work_items[id=w-agents-onboard].queue_pos', value: 0 },
              { path: 'projects[id=p-agents].last_activity_at', value: '2026-09-29T15:30:00+08:00' }
            ]
          },
          {
            delay: 1800,
            event: {
              type: 'project_decision_answered', project_id: 'p-agents', work_item_id: 'w-agents-onboard',
              label: '用户回答「确认接入已有项目的初始 PRD」：确认初始 PRD', payload: { decision_id: 'd-agents-prd', kind: 'initial_prd', option: 'confirm' }
            },
            patch: [
              { path: 'decisions[id=d-agents-prd].status', value: 'answered' },
              { path: 'decisions[id=d-agents-prd].answer', value: { option: 'confirm', label: '确认初始 PRD', note: '', at: '2026-09-29T15:30:00+08:00' } }
            ]
          },
          {
            delay: 1600,
            event: {
              type: 'baseline_adopted', project_id: 'p-agents', work_item_id: 'w-agents-onboard', run_id: 'r-agents-onboard',
              label: '基线采纳：代码快照成为第一次采纳，初始 PRD 成为当前有效要求', payload: { version: '基线', work_item_id: 'w-agents-onboard' }
            },
            patch: [
              { path: 'projects[id=p-agents].adoptions', push: { version: '基线', work_item_id: 'w-agents-onboard', summary: '接入时的代码快照与初始 PRD', adopted_at: '2026-09-29T15:30:00+08:00' } },
              { path: 'work_items[id=w-agents-onboard].status', value: 'adopted' },
              { path: 'projects[id=p-agents].last_activity_at', value: '2026-09-29T15:30:00+08:00' }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'work_item_created', project_id: 'p-agents', work_item_id: 'w-agents-842',
              label: '用户提交 issue 842，事项进入队列', payload: { kind: 'change' }
            },
            patch: [
              {
                path: 'work_items', push: {
                  id: 'w-agents-842', project_id: 'p-agents', title: '实现 issue 842：ModelSettings 支持 extra_args', color_index: 2, kind: 'change',
                  status: 'queued', queue_reason: 'decision', run_id: null, queue_pos: 1, version: 1,
                  created_at: '2026-09-29T15:30:00+08:00', born_at: '2026-09-29T15:30:00+08:00', level: '3.8'
                }
              },
              { path: 'projects[id=p-agents].last_activity_at', value: '2026-09-29T15:30:00+08:00' }
            ]
          },
          {
            delay: 1400,
            event: {
              type: 'run_created', project_id: 'p-agents', work_item_id: 'w-agents-842', run_id: 'r-agents-842',
              label: '基线采纳以后，issue 842 的 run 创建', payload: { kind: 'change' }
            },
            patch: [
              {
                path: 'runs', push: {
                  id: 'r-agents-842', work_item_id: 'w-agents-842', project_id: 'p-agents', yudao_version: '0.8.0', kind: 'change',
                  phase: 'PRODUCT_SPEC', department: 'product', last_department: null, cycle: 1,
                  started_at: '2026-09-29T15:30:00+08:00', elapsed_sec: 0, limit_sec: 7200,
                  waiting_provider_sec: 0, waiting_provider: null, stop_reason: null,
                  recovery: {
                    state: 'running', reason: null, unusable: null,
                    last_confirmed: { seq: 0, text: '事项已登记，等待产品开始' },
                    owner: { id: '产品部门', since: '2026-09-29T15:30:00+08:00' },
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
                    product: { items: [], facts: [], questions: [], progress: [] },
                    engineering: { items: [], facts: [], questions: [], progress: [] },
                    quality: { items: [], facts: [], questions: [], progress: [] }
                  },
                  attempts: [], source: null, born_at: '2026-09-29T15:30:00+08:00'
                }
              },
              { path: 'work_items[id=w-agents-842].run_id', value: 'r-agents-842' },
              { path: 'work_items[id=w-agents-842].status', value: 'in_progress' },
              { path: 'work_items[id=w-agents-842].queue_reason', value: null },
              { path: 'work_items[id=w-agents-842].queue_pos', value: null }
            ]
          },
          {
            delay: 1200,
            event: {
              type: 'x_slot_acquired', project_id: 'p-agents', work_item_id: 'w-agents-842', run_id: 'r-agents-842',
              label: 'issue 842 的事项取得执行槽位', payload: { department: 'product' }
            },
            patch: [{ path: 'runtime.slots.used', push: { work_item_id: 'w-agents-842', department: 'product', role: null } }]
          },
          {
            delay: 1400,
            event: {
              type: 'department_activated', project_id: 'p-agents', work_item_id: 'w-agents-842', run_id: 'r-agents-842', department: 'product',
              label: '产品部门开始处理 issue 842：extra_args 的透传参数', payload: {}
            },
            patch: [{ path: 'projects[id=p-agents].last_activity_at', value: '2026-09-29T15:30:00+08:00' }]
          }
        ]
      }
    ]
  });
})();
