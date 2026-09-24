// 原型 v7 示例数据：项目、事项、run、资料、语义记录、项目设置、模型目录、执行槽位、工具、运维、元观察与场景
// 字段的基础值表示现有实现的行为；带 level 的对象只在该档位及以上出现；levels 中的值在对应档位起覆盖基础值
(function () {
  'use strict';

  // 时间：T('14:10') 为 2026-09-24 14:10，T('17:40', '23') 为 9 月 23 日 17:40
  function T(hm, day) {
    const time = hm.length === 5 ? hm + ':00' : hm;
    return '2026-09-' + (day || '24') + 'T' + time + '+08:00';
  }

  const CONN = {
    'opencode-go-responses': { protocol: 'Responses', baseUrl: 'https://opencode.ai/zen/go/v1', credentialRef: 'OPENCODE_GO_KEY', credentialVersion: 'k3' },
    'opencode-go-chat': { protocol: 'Chat Completions', baseUrl: 'https://opencode.ai/zen/go/v1', credentialRef: 'OPENCODE_GO_LAB_KEY', credentialVersion: 'k1' },
    'local-custom': { protocol: 'Chat Completions', baseUrl: 'http://127.0.0.1:8080/v1', credentialRef: null, credentialVersion: null }
  };
  const CAP = { 'kimi-k2.6': [262144, 32768], 'glm-5': [204800, 32768], 'mimo-v2.5': [1048576, 65536], 'qwen3-coder-30b': [131072, 16384] };

  // 调用目标（D24 第 6 节）：一次请求实际使用的连接、协议、地址、上游模型、容量、凭据引用与版本、选择来源、档位与部门 Prompt 版本
  function tgt(connection, model, source, requestLevel, sentLevel, promptVersion, basis) {
    const conn = CONN[connection];
    return {
      level: 's3',
      connection, protocol: conn.protocol, baseUrl: conn.baseUrl, model,
      window: CAP[model][0], maxOutput: CAP[model][1],
      credentialRef: conn.credentialRef, credentialVersion: conn.credentialVersion,
      source, requestLevel, sentLevel, promptVersion,
      usageBasis: basis || null
    };
  }

  // 调用尝试；role 在 Stage 4 起通过 levels 覆盖
  function att(o) {
    const out = Object.assign({
      kind: 'work', role: null, n: 1, of: 3, status: 'succeeded', durationMs: 12000, error: null,
      usage: null, semanticUnits: []
    }, o);
    if (o.r) {
      out.levels = { s4: { role: o.r } };
      delete out.r;
    }
    return out;
  }

  function usage(input, output, cacheRead) {
    return { input, output, cacheRead, total: input + output, cost: null };
  }

  function units(list) {
    return list.map((id) => ({ id, version: 1 }));
  }

  function withRole(obj, role) {
    obj.levels = { s4: { role } };
    return obj;
  }

  function recoveryTerminated(text, seq, limits) {
    return {
      level: 's3', state: 'terminated', reason: text, unusable: null,
      lastConfirmed: { seq, text }, canResume: false, resumeBlockedReason: '事项已完成',
      owner: null, lateResults: [], verifications: [], nextActions: [], unfinished: [], limits
    };
  }

  function roleSet(statuses) {
    const s = statuses || {};
    const pick = (id, fallback) => Object.assign({ status: 'idle', task: null }, fallback || {}, s[id] || {});
    return {
      level: 's4',
      product: [
        Object.assign({ id: 'prod-manager', name: '产品部门经理', kind: 'manager', model: 'opencode-go-responses/glm-5' }, pick('prod-manager')),
        Object.assign({ id: 'prod-architect', name: '产品架构师', kind: 'architect', model: 'opencode-go-responses/glm-5' }, pick('prod-architect')),
        Object.assign({ id: 'prod-explorer', name: '产品探索者', kind: 'explorer', model: 'opencode-go-responses/glm-5' }, pick('prod-explorer'))
      ],
      engineering: [
        Object.assign({ id: 'eng-manager', name: '工程经理', kind: 'manager', model: 'opencode-go-responses/kimi-k2.6' }, pick('eng-manager')),
        Object.assign({ id: 'eng-architect', name: '工程架构师', kind: 'architect', model: 'opencode-go-responses/kimi-k2.6' }, pick('eng-architect')),
        Object.assign({ id: 'eng-dev', name: '开发者', kind: 'developer', model: 'opencode-go-responses/kimi-k2.6' }, pick('eng-dev')),
        Object.assign({ id: 'eng-explorer', name: '工程探索者', kind: 'explorer', model: 'opencode-go-responses/glm-5' }, pick('eng-explorer'))
      ],
      quality: [
        Object.assign({ id: 'qa-manager', name: '质检经理', kind: 'manager', model: 'opencode-go-responses/mimo-v2.5' }, pick('qa-manager')),
        Object.assign({ id: 'qa-tester', name: '测试工程师', kind: 'tester', model: 'opencode-go-responses/mimo-v2.5' }, pick('qa-tester')),
        Object.assign({ id: 'qa-explorer', name: '质检探索者', kind: 'explorer', model: 'opencode-go-responses/glm-5' }, pick('qa-explorer'))
      ]
    };
  }

  const PROMPTS = {
    product: '（内置默认 Prompt）你是产品部门。依据用户原文维护 PRD：写清目标、边界、验收条件与非目标；回答其他部门的需求咨询时，只依据有效要求与用户原文。',
    engineering: '修改代码前先按区间阅读相关代码；每次修改后运行登记命令 unit_tests；只修改与当前计划有关的文件；交付说明逐条对应计划项。',
    quality: '在独立副本中运行检查；逐条对照验收条件记录证据与主机回执；发现问题时写明复现步骤与违反的验收条件。'
  };

  function prompts(engineeringVersion, qualityVersion) {
    return {
      product: { configVersion: 0, requestVersion: 0, text: PROMPTS.product },
      engineering: { configVersion: engineeringVersion, requestVersion: engineeringVersion, text: engineeringVersion ? PROMPTS.engineering : '（内置默认 Prompt）你是工程部门。依据有效 PRD 先写工程计划，再实现、自测并提交交付。' },
      quality: { configVersion: qualityVersion, requestVersion: qualityVersion, text: qualityVersion ? PROMPTS.quality : '（内置默认 Prompt）你是质检部门。依据有效 PRD 独立验证交付，给出缺陷或放行。' }
    };
  }

  function effective(map) {
    return Object.assign({ level: 's3' }, map);
  }

  const EM = {
    productDefault: { definition: 'opencode-go-responses/glm-5', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: null, sentLevel: 'medium', unusable: null },
    engineeringProject: { definition: 'opencode-go-responses/kimi-k2.6', connection: 'opencode-go-responses', protocol: 'Responses', source: '项目设置', level: 'high', sentLevel: 'high', unusable: null },
    engineeringDefault: { definition: 'opencode-go-responses/kimi-k2.6', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: 'high', sentLevel: 'high', unusable: null },
    qualityDefault: { definition: 'opencode-go-responses/mimo-v2.5', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: null, sentLevel: 'medium', unusable: null }
  };

  // 场景中新建的集成事项使用的空 run
  function emptyRun(id, workItemId) {
    return {
      id, workItemId, phase: 'PRODUCT_SPEC', department: 'product', lastDepartment: null, cycle: 1,
      startedAt: T('15:30'), elapsedSec: 0, limitSec: 7200, stopReason: null,
      recovery: { level: 's3', state: 'running', reason: null, unusable: null, lastConfirmed: null, canResume: false, resumeBlockedReason: '事项正在运行', owner: { id: 'exec-5d20', since: T('15:30') }, lateResults: [], verifications: [], nextActions: [], unfinished: [], limits: { activations: 1, modelSteps: 0, retries: 0 } },
      inputs: [], flow: [], requests: [], guidance: [],
      messages: { product: [], engineering: [], quality: [], operations: [] },
      actions: [], contexts: { product: [], engineering: [], quality: [] },
      prompts: prompts(2, 1), compactions: [],
      effectiveModel: effective({ product: EM.productDefault, engineering: EM.engineeringProject, quality: EM.qualityDefault }),
      roles: roleSet(), ledger: { level: 's4' }, attempts: [], source: null
    };
  }

  // ---------------------------------------------------------------------------
  // run：r-base 建立基线（已采纳 r1）

  const rBase = {
    id: 'r-base', workItemId: 'w-base', phase: 'DONE', department: null, lastDepartment: 'quality', cycle: 1,
    startedAt: T('10:05', '22'), elapsedSec: 3010, limitSec: 7200, stopReason: null,
    recovery: recoveryTerminated('质检放行，事项已完成并被采纳为 r1', 64, { activations: 3, modelSteps: 22, retries: 0 }),
    inputs: [
      { version: 1, kind: 'user', text: '做一个命令行工具：读取 sales.csv，按行输出日期、类别、金额，最后一行给出合计金额。', at: T('10:05', '22'), progress: 'accepted', bytes: [0, 132] }
    ],
    flow: [
      { seq: 2, at: T('10:05', '22'), from: 'user', to: 'product', kind: 'handoff', content: '用户输入 v1：逐行输出与合计金额', status: '已接收', eventId: 'e-rbase-0002' },
      { seq: 5, at: T('10:13', '22'), from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：逐行输出日期、类别、金额，最后一行为合计（AC-1 至 AC-3）', status: '已接收', eventId: 'e-rbase-0005' },
      { seq: 38, at: T('10:41', '22'), from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r1：report.py 与 12 条单元测试', status: '已验收', eventId: 'e-rbase-0038' },
      { seq: 57, at: T('10:52', '22'), from: 'quality', to: 'adoption', kind: 'release', content: '放行：12 条检查全部通过', status: '已放行', eventId: 'e-rbase-0057' },
      { seq: 64, at: T('11:02', '22'), from: 'quality', to: 'adoption', kind: 'adopt', content: '项目采纳 r1', status: '已采纳', eventId: 'e-rbase-0064' }
    ],
    requests: [], guidance: [],
    messages: {
      product: [
        { seq: 2, at: T('10:05', '22'), source: 'user', from: 'user', text: '做一个命令行工具：读取 sales.csv，按行输出日期、类别、金额，最后一行给出合计金额。', eventId: 'e-rbase-0002' },
        { seq: 4, at: T('10:12', '22'), source: 'self', from: 'product', text: 'PRD r1 已提交：逐行输出与合计，3 条验收条件', eventId: 'e-rbase-0004' }
      ],
      engineering: [
        { seq: 5, at: T('10:13', '22'), source: 'other', from: 'product', text: 'PRD r1 交接：逐行输出与合计金额', eventId: 'e-rbase-0005' },
        { seq: 37, at: T('10:40', '22'), source: 'self', from: 'engineering', text: '交付 r1 已提交：report.py、tests/test_report.py', eventId: 'e-rbase-0037' }
      ],
      quality: [
        { seq: 38, at: T('10:41', '22'), source: 'other', from: 'engineering', text: '交付 r1 交接', eventId: 'e-rbase-0038' },
        { seq: 56, at: T('10:51', '22'), source: 'self', from: 'quality', text: 'QA：放行，12 条检查全部通过', eventId: 'e-rbase-0056' }
      ],
      operations: []
    },
    actions: [
      withRole({ id: 'a-b1', department: 'engineering', role: null, tool: 'write_file', summary: '新建 report.py：读取 CSV 并逐行输出', input: 'PLAN r1 第 1 项', state: 'done', receipt: null, before: '工作区 000000（空）', after: '工作区 1d7a02', result: '写入 118 行', at: T('10:24', '22') }, 'eng-dev'),
      withRole({ id: 'a-b2', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 unit_tests', input: 'PLAN r1 第 3 项：自测', state: 'done', receipt: { command: 'unit_tests', argv: ['python', '-m', 'pytest', 'tests', '-q'], exitCode: 0, output: '............ [100%]\n12 passed in 0.38s', truncated: false, timedOut: false, durationMs: 1710, snapshot: 'ws-1d7a02' }, before: '工作区 1d7a02', after: '工作区 1d7a02（未改动）', result: '退出 0 · 12 条通过', at: T('10:36', '22') }, 'eng-dev'),
      withRole({ id: 'a-b3', department: 'quality', role: null, tool: 'run_command', summary: '质检执行登记命令 unit_tests（质检副本）', input: 'PRD r1 AC-1 至 AC-3', state: 'done', receipt: { command: 'unit_tests', argv: ['python', '-m', 'pytest', 'tests', '-q'], exitCode: 0, output: '............ [100%]\n12 passed in 0.40s', truncated: false, timedOut: false, durationMs: 1760, snapshot: 'qa-1d7a02' }, before: '质检副本 1d7a02', after: '质检副本 1d7a02（未改动）', result: '退出 0 · 12 条通过', at: T('10:47', '22') }, 'qa-tester')
    ],
    contexts: {
      product: [{ id: 'ctx-b-p1', at: T('10:06', '22'), title: '产品激活 1', attemptId: 'att-rbase-01', sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '部门规则', version: '默认 v0', included: true }, { label: '工具定义', version: '5 个工具', included: true }] }],
      engineering: [{ id: 'ctx-b-e1', at: T('10:14', '22'), title: '工程激活 1', attemptId: 'att-rbase-02', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '部门规则', version: '默认 v0', included: true }, { label: '工具定义', version: '7 个工具', included: true }] }],
      quality: [{ id: 'ctx-b-q1', at: T('10:42', '22'), title: '质检激活 1', attemptId: 'att-rbase-03', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '前次交付', version: '交付 r1', included: true }] }]
    },
    prompts: prompts(0, 0), compactions: [],
    effectiveModel: effective({ product: EM.productDefault, engineering: EM.engineeringDefault, quality: EM.qualityDefault }),
    roles: roleSet(), ledger: { level: 's4' },
    attempts: [
      att({ id: 'att-rbase-01', logicalCallId: 'call-b-p1', department: 'product', r: 'prod-architect', startedAt: T('10:06', '22'), durationMs: 21400, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(6120, 1480, 0), target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0) }),
      att({ id: 'att-rbase-02', logicalCallId: 'call-b-e1', department: 'engineering', r: 'eng-dev', startedAt: T('10:15', '22'), durationMs: 38200, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(11240, 4310, 0), target: tgt('opencode-go-responses', 'kimi-k2.6', '部门默认', 'high', 'high', 0) }),
      att({ id: 'att-rbase-03', logicalCallId: 'call-b-q1', department: 'quality', r: 'qa-tester', startedAt: T('10:43', '22'), durationMs: 17600, provider: 'opencode-go-responses', requestedModel: 'mimo-v2.5', actualModel: 'mimo-v2.5', usage: usage(9870, 1120, 0), target: tgt('opencode-go-responses', 'mimo-v2.5', '部门默认', null, 'medium', 0) })
    ],
    source: null
  };

  // ---------------------------------------------------------------------------
  // run：r-sum 按类别汇总（返工一次，已采纳 r2）

  const rSum = {
    id: 'r-sum', workItemId: 'w-sum', phase: 'DONE', department: null, lastDepartment: 'quality', cycle: 2,
    startedAt: T('15:20', '23'), elapsedSec: 7680, limitSec: 10800, stopReason: null,
    recovery: recoveryTerminated('质检放行，事项已完成并被采纳为 r2', 131, { activations: 5, modelSteps: 48, retries: 1 }),
    inputs: [
      { version: 1, kind: 'user', text: '按类别汇总金额与笔数，类别按字母顺序排列，最后一行为合计金额。', at: T('15:20', '23'), progress: 'accepted', bytes: [0, 93] }
    ],
    flow: [
      { seq: 3, at: T('15:20', '23'), from: 'user', to: 'product', kind: 'handoff', content: '用户输入 v1：按类别汇总', status: '已接收', eventId: 'e-rsum-0003' },
      { seq: 8, at: T('15:28', '23'), from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：按类别汇总金额与笔数（AC-1 至 AC-4）', status: '已接收', eventId: 'e-rsum-0008' },
      { seq: 47, at: T('16:10', '23'), from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r1：新增 --by-category', status: '已验收', eventId: 'e-rsum-0047' },
      { seq: 60, at: T('16:31', '23'), from: 'quality', to: 'engineering', kind: 'rework', content: '返工：合计金额有浮点误差，0.1+0.2 显示为 0.30000000000000004（D-1，违反 AC-4）', status: '已处理', eventId: 'e-rsum-0060' },
      { seq: 102, at: T('17:05', '23'), from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r2：金额改用 Decimal 并保留两位小数', status: '已验收', eventId: 'e-rsum-0102' },
      { seq: 124, at: T('17:28', '23'), from: 'quality', to: 'adoption', kind: 'release', content: '放行：15 条检查全部通过', status: '已放行', eventId: 'e-rsum-0124' },
      { seq: 131, at: T('17:40', '23'), from: 'quality', to: 'adoption', kind: 'adopt', content: '项目采纳 r2', status: '已采纳', eventId: 'e-rsum-0131' }
    ],
    requests: [],
    guidance: [
      { id: 'g-s1', department: 'quality', version: 1, text: '金额比较要按两位小数，不要按浮点直接比较。', status: 'completed', response: '检查清单第 4 项已改为按两位小数比较，见回执 a-s6。', at: T('16:20', '23') }
    ],
    messages: {
      product: [
        { seq: 3, at: T('15:20', '23'), source: 'user', from: 'user', text: '按类别汇总金额与笔数，类别按字母顺序排列，最后一行为合计金额。', eventId: 'e-rsum-0003' },
        { seq: 7, at: T('15:27', '23'), source: 'self', from: 'product', text: 'PRD r1 已提交：4 条验收条件', eventId: 'e-rsum-0007' }
      ],
      engineering: [
        { seq: 8, at: T('15:28', '23'), source: 'other', from: 'product', text: 'PRD r1 交接', eventId: 'e-rsum-0008' },
        { seq: 60, at: T('16:31', '23'), source: 'other', from: 'quality', text: '返工：合计金额有浮点误差（D-1）', eventId: 'e-rsum-0060' },
        { seq: 101, at: T('17:04', '23'), source: 'self', from: 'engineering', text: '交付 r2 已提交：金额改用 Decimal', eventId: 'e-rsum-0101' }
      ],
      quality: [
        { seq: 59, at: T('16:30', '23'), source: 'self', from: 'quality', text: 'QA：返工工程（D-1）', eventId: 'e-rsum-0059' },
        { seq: 123, at: T('17:27', '23'), source: 'self', from: 'quality', text: 'QA：放行，15 条检查全部通过', eventId: 'e-rsum-0123' }
      ],
      operations: []
    },
    actions: [
      withRole({ id: 'a-s1', department: 'engineering', role: null, tool: 'search', summary: '搜索 "def summarize" 定位汇总入口', input: 'PLAN r1 第 1 项', state: 'done', receipt: null, before: null, after: null, result: '1 处：report.py:58', at: T('15:34', '23') }, 'eng-dev'),
      withRole({ id: 'a-s2', department: 'engineering', role: null, tool: 'edit_range', summary: '按区间编辑 report.py 第 58–96 行：新增按类别汇总', input: 'PLAN r1 第 1、2 项', state: 'done', receipt: null, before: 'report.py @ 1d7a02', after: 'report.py @ 6b2e40', result: '+31 −4 行', at: T('15:49', '23') }, 'eng-dev'),
      withRole({ id: 'a-s3', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 report_categorized（超时）', input: 'PLAN r1 第 3 项：自测', state: 'done', receipt: { command: 'report_categorized', argv: ['python', 'report.py', 'samples/sales.csv', '--by-category'], exitCode: null, output: '类别  笔数  金额\n办公  3  96.00\n办公  3  96.00\n办公  3  96.00\n…（输出超过上限，已截断）', truncated: true, timedOut: true, durationMs: 30000, snapshot: 'ws-6b2e40' }, before: '工作区 6b2e40', after: '工作区 6b2e40（进程树已结束，未残留）', result: '超时 30 秒，进程树已结束', at: T('15:52', '23') }, 'eng-dev'),
      withRole({ id: 'a-s4', department: 'engineering', role: null, tool: 'edit_range', summary: '按区间编辑 report.py 第 71–75 行：修正循环条件', input: '回执 a-s3：输出重复', state: 'done', receipt: null, before: 'report.py @ 6b2e40', after: 'report.py @ 7c11f5', result: '+2 −2 行', at: T('15:58', '23') }, 'eng-dev'),
      withRole({ id: 'a-s5', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 unit_tests', input: 'PLAN r2 第 2 项', state: 'done', receipt: { command: 'unit_tests', argv: ['python', '-m', 'pytest', 'tests', '-q'], exitCode: 0, output: '............... [100%]\n15 passed in 0.52s', truncated: false, timedOut: false, durationMs: 1920, snapshot: 'ws-a90d33' }, before: '工作区 a90d33', after: '工作区 a90d33（未改动）', result: '退出 0 · 15 条通过', at: T('17:01', '23') }, 'eng-dev'),
      withRole({ id: 'a-s6', department: 'quality', role: null, tool: 'run_command', summary: '质检执行登记命令 unit_tests（质检副本）', input: 'PRD r1 AC-1 至 AC-4；部门指导 g-s1', state: 'done', receipt: { command: 'unit_tests', argv: ['python', '-m', 'pytest', 'tests', '-q'], exitCode: 0, output: '............... [100%]\n15 passed in 0.55s', truncated: false, timedOut: false, durationMs: 1980, snapshot: 'qa-a90d33' }, before: '质检副本 a90d33', after: '质检副本 a90d33（未改动）', result: '退出 0 · 15 条通过', at: T('17:22', '23') }, 'qa-tester')
    ],
    contexts: {
      product: [{ id: 'ctx-s-p1', at: T('15:21', '23'), title: '产品激活 1', attemptId: 'att-rsum-01', sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '项目上下文', version: '采纳 r1', included: true }] }],
      engineering: [
        { id: 'ctx-s-e1', at: T('15:29', '23'), title: '工程激活 1', attemptId: 'att-rsum-02', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '项目上下文', version: '采纳 r1', included: true }] },
        { id: 'ctx-s-e2', at: T('16:32', '23'), title: '工程激活 2（返工）', attemptId: 'att-rsum-04', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '质检缺陷', version: 'D-1', included: true }, { label: '部门历史', version: '摘要 1', included: true }] }
      ],
      quality: [{ id: 'ctx-s-q1', at: T('17:06', '23'), title: '质检激活 2', attemptId: 'att-rsum-05', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '前次交付', version: '交付 r2', included: true }, { label: '部门指导', version: 'g-s1', included: true }] }]
    },
    prompts: prompts(1, 1), compactions: [{ department: 'engineering', n: 1, at: T('16:32', '23'), coverage: 'seq 9–58', eventId: 'e-rsum-0061' }],
    effectiveModel: effective({ product: EM.productDefault, engineering: EM.engineeringProject, quality: EM.qualityDefault }),
    roles: roleSet(), ledger: { level: 's4' },
    attempts: [
      att({ id: 'att-rsum-01', logicalCallId: 'call-s-p1', department: 'product', r: 'prod-architect', startedAt: T('15:21', '23'), durationMs: 19800, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(7310, 1690, 0), target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0) }),
      att({ id: 'att-rsum-02', logicalCallId: 'call-s-e1', department: 'engineering', r: 'eng-dev', startedAt: T('15:30', '23'), durationMs: 41200, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(14320, 3870, 0), target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'high', 1) }),
      att({ id: 'att-rsum-03', logicalCallId: 'call-s-q1', department: 'quality', r: 'qa-tester', startedAt: T('16:12', '23'), durationMs: 16800, provider: 'opencode-go-responses', requestedModel: 'mimo-v2.5', actualModel: 'mimo-v2.5', usage: usage(11020, 1350, 0), target: tgt('opencode-go-responses', 'mimo-v2.5', '部门默认', null, 'medium', 1) }),
      att({ id: 'att-rsum-04', logicalCallId: 'call-s-e2', department: 'engineering', r: 'eng-dev', startedAt: T('16:33', '23'), durationMs: 36400, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(22840, 3120, 12288), target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'high', 1) }),
      att({ id: 'att-rsum-05', logicalCallId: 'call-s-q2', department: 'quality', r: 'qa-tester', startedAt: T('17:07', '23'), durationMs: 15900, provider: 'opencode-go-responses', requestedModel: 'mimo-v2.5', actualModel: 'mimo-v2.5', usage: usage(13380, 1060, 9216), target: tgt('opencode-go-responses', 'mimo-v2.5', '部门默认', null, 'medium', 1) })
    ],
    source: null
  };

  // ---------------------------------------------------------------------------
  // run：r-cat 类别按首次出现顺序输出（进行中，工程，第 3 轮）

  const rCat = {
    id: 'r-cat', workItemId: 'w-cat', phase: 'ENGINEERING', department: 'engineering', lastDepartment: 'engineering', cycle: 3,
    startedAt: T('14:10'), elapsedSec: 4800, limitSec: 7200, stopReason: null,
    recovery: {
      level: 's3', state: 'running', reason: null, unusable: null,
      lastConfirmed: { seq: 94, text: '工程按区间编辑 report.py 第 88–90 行（已完成）' },
      canResume: false, resumeBlockedReason: '事项正在运行，已有有效执行者',
      owner: { id: 'exec-2c91', since: T('15:02:14') }, lateResults: [], verifications: [], nextActions: [], unfinished: [],
      limits: { activations: 6, modelSteps: 57, retries: 1 }
    },
    inputs: [
      { version: 1, kind: 'user', text: '汇总表里类别的顺序改为按在输入中首次出现的顺序，不再按字母排序。', at: T('14:10'), progress: 'accepted', bytes: [0, 99] },
      { version: 2, kind: 'user', text: '汇总表最后加一行「共 N 个类别」。', at: T('15:12'), progress: 'assigned', bytes: [99, 150] }
    ],
    flow: [
      { seq: 3, at: T('14:10'), from: 'user', to: 'product', kind: 'handoff', content: '用户输入 v1：类别按首次出现顺序输出', status: '已接收', eventId: 'e-rcat-0003' },
      { seq: 9, at: T('14:18'), from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：类别按首次出现顺序输出（AC-1 至 AC-3）', status: '已接收', eventId: 'e-rcat-0009' },
      { seq: 41, at: T('14:41'), from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r1：修改 report.py 的汇总顺序', status: '已验收', eventId: 'e-rcat-0041' },
      { seq: 52, at: T('14:52'), from: 'quality', to: 'engineering', kind: 'rework', content: '返工：多次出现的类别只计入第一次的笔数（D-1，违反 AC-2）', status: '已处理', eventId: 'e-rcat-0052' },
      { seq: 61, at: T('15:05'), from: 'engineering', to: 'product', kind: 'ask', content: '咨询：空类别名应显示为空白还是「未分类」？', status: '已回答', eventId: 'e-rcat-0061' },
      { seq: 66, at: T('15:08'), from: 'product', to: 'engineering', kind: 'answer', content: '回答：显示为「未分类」；PRD r2 增加 AC-4', status: '已接收', eventId: 'e-rcat-0066' },
      { seq: 79, at: T('15:18'), from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r2：修复 D-1，空类别名显示为「未分类」', status: '已验收', eventId: 'e-rcat-0079' },
      { seq: 88, at: T('15:24'), from: 'quality', to: 'engineering', kind: 'rework', content: '返工：输出末尾缺少换行，report_categorized 比较失败（D-2，违反 AC-3）', status: '处理中', eventId: 'e-rcat-0088' }
    ],
    requests: [
      { id: 'q-1', from: 'engineering', to: 'product', kind: 'ask', question: '空类别名应显示为空白还是「未分类」？', status: 'answered', answer: '显示为「未分类」，已写入 PRD r2 的验收条件 AC-4。', askedAt: T('15:05'), answeredAt: T('15:08'), eventId: 'e-rcat-0061' }
    ],
    guidance: [
      { id: 'g-1', department: 'engineering', version: 1, text: '修改前先运行 unit_tests，确认原有用例全部通过。', status: 'completed', response: '已在修改前后各运行一次 unit_tests，结果见动作 a-3 与 a-12。', at: T('14:24'), contextId: 'ctx-e1', eventId: 'e-rcat-0014' },
      { id: 'g-3', department: 'quality', version: 1, text: '检查同一类别多次出现的情况。', status: 'explained', response: '已加入检查清单第 3 项：同一类别出现 3 次的样例。', at: T('14:45'), contextId: 'ctx-q1', eventId: 'e-rcat-0045' },
      { id: 'g-2', department: 'engineering', version: 2, text: '不要改动 CSV 解析部分。', status: 'in_input', response: null, at: T('15:26'), contextId: 'ctx-e3', eventId: 'e-rcat-0091' }
    ],
    messages: {
      product: [
        { seq: 3, at: T('14:10'), source: 'user', from: 'user', text: '汇总表里类别的顺序改为按在输入中首次出现的顺序，不再按字母排序。', eventId: 'e-rcat-0003' },
        { seq: 8, at: T('14:17'), source: 'self', from: 'product', text: 'PRD r1 已提交：类别按首次出现顺序输出，3 条验收条件', eventId: 'e-rcat-0008' },
        { seq: 61, at: T('15:05'), source: 'other', from: 'engineering', text: '咨询：空类别名应显示为空白还是「未分类」？', eventId: 'e-rcat-0061' },
        { seq: 65, at: T('15:08'), source: 'self', from: 'product', text: '回答：显示为「未分类」；PRD r2 增加 AC-4', eventId: 'e-rcat-0065' },
        { seq: 70, at: T('15:12'), source: 'user', from: 'user', text: '汇总表最后加一行「共 N 个类别」。', eventId: 'e-rcat-0070' }
      ],
      engineering: [
        { seq: 9, at: T('14:18'), source: 'other', from: 'product', text: 'PRD r1 交接：类别按首次出现顺序输出', eventId: 'e-rcat-0009' },
        { seq: 12, at: T('14:22'), source: 'self', from: 'engineering', text: 'PLAN r1：修改 report.py 的汇总顺序；运行 unit_tests 与 report_categorized', eventId: 'e-rcat-0012' },
        { seq: 14, at: T('14:24'), source: 'user', from: 'user', text: '指导 v1：修改前先运行 unit_tests，确认原有用例全部通过。', eventId: 'e-rcat-0014' },
        { seq: 40, at: T('14:40'), source: 'self', from: 'engineering', text: '交付 r1 已提交', eventId: 'e-rcat-0040' },
        { seq: 52, at: T('14:52'), source: 'other', from: 'quality', text: '返工：多次出现的类别笔数统计错误（D-1）', eventId: 'e-rcat-0052' },
        { seq: 60, at: T('15:05'), source: 'self', from: 'engineering', text: '已向产品咨询空类别名的显示方式', eventId: 'e-rcat-0060' },
        { seq: 66, at: T('15:08'), source: 'other', from: 'product', text: '回答：显示为「未分类」', eventId: 'e-rcat-0066' },
        { seq: 78, at: T('15:18'), source: 'self', from: 'engineering', text: '交付 r2 已提交', eventId: 'e-rcat-0078' },
        { seq: 88, at: T('15:24'), source: 'other', from: 'quality', text: '返工：输出末尾缺少换行（D-2）', eventId: 'e-rcat-0088' },
        { seq: 91, at: T('15:26'), source: 'user', from: 'user', text: '指导 v2：不要改动 CSV 解析部分。', eventId: 'e-rcat-0091' },
        { seq: 94, at: T('15:27'), source: 'self', from: 'engineering', text: '按区间编辑 report.py 第 88–90 行，补上末尾换行', eventId: 'e-rcat-0094' }
      ],
      quality: [
        { seq: 41, at: T('14:41'), source: 'other', from: 'engineering', text: '交付 r1 交接', eventId: 'e-rcat-0041' },
        { seq: 45, at: T('14:45'), source: 'user', from: 'user', text: '指导 v1：检查同一类别多次出现的情况。', eventId: 'e-rcat-0045' },
        { seq: 51, at: T('14:52'), source: 'self', from: 'quality', text: 'QA：返工工程（D-1）', eventId: 'e-rcat-0051' },
        { seq: 79, at: T('15:19'), source: 'other', from: 'engineering', text: '交付 r2 交接', eventId: 'e-rcat-0079' },
        { seq: 87, at: T('15:24'), source: 'self', from: 'quality', text: 'QA：返工工程（D-2）', eventId: 'e-rcat-0087' }
      ],
      operations: []
    },
    actions: [
      withRole({ id: 'a-1', department: 'engineering', role: null, tool: 'search', summary: '搜索 "sorted(" 定位类别排序的位置', input: 'PRD r1 AC-1', state: 'done', receipt: null, before: null, after: null, result: '2 处：report.py:41、report.py:77', at: T('14:23') }, 'eng-dev'),
      withRole({ id: 'a-2', department: 'engineering', role: null, tool: 'read_range', summary: '按区间阅读 report.py 第 30–90 行', input: '搜索结果 a-1', state: 'done', receipt: null, before: null, after: null, result: '61 行', at: T('14:24') }, 'eng-dev'),
      withRole({ id: 'a-3', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 unit_tests（修改前）', input: '部门指导 g-1', state: 'done', receipt: { command: 'unit_tests', argv: ['python', '-m', 'pytest', 'tests', '-q'], exitCode: 0, output: '............ [100%]\n12 passed in 0.41s', truncated: false, timedOut: false, durationMs: 1830, snapshot: 'ws-3f9c21' }, before: '工作区 3f9c21', after: '工作区 3f9c21（未改动）', result: '退出 0 · 12 条通过', at: T('14:25') }, 'eng-dev'),
      withRole({ id: 'a-4', department: 'engineering', role: null, tool: 'edit_range', summary: '按区间编辑 report.py 第 41–52 行：用按首次出现顺序记录的字典替换 sorted()', input: 'PLAN r1 第 1 项', state: 'done', receipt: null, before: 'report.py @ 3f9c21', after: 'report.py @ 8d04e7', result: '+9 −5 行', at: T('14:31') }, 'eng-dev'),
      withRole({ id: 'a-5', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 report_categorized', input: 'PLAN r1 第 2 项：自测', state: 'done', receipt: { command: 'report_categorized', argv: ['python', 'report.py', 'samples/sales.csv', '--by-category'], exitCode: 1, output: 'Traceback (most recent call last):\n  File "check_output.py", line 18\nAssertionError: 期望第一行为「食品」，实际为「办公」', truncated: false, timedOut: false, durationMs: 640, snapshot: 'ws-8d04e7' }, before: '工作区 8d04e7', after: '工作区 8d04e7（未改动）', result: '退出 1', at: T('14:33') }, 'eng-dev'),
      withRole({ id: 'a-6', department: 'engineering', role: null, tool: 'edit_range', summary: '按区间编辑 report.py 第 55–60 行：修正读取顺序', input: '回执 a-5：退出 1', state: 'done', receipt: null, before: 'report.py @ 8d04e7', after: 'report.py @ 2a6f18', result: '+3 −3 行', at: T('14:36') }, 'eng-dev'),
      withRole({ id: 'a-7', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 report_categorized（修改后）', input: '回执 a-5', state: 'done', receipt: { command: 'report_categorized', argv: ['python', 'report.py', 'samples/sales.csv', '--by-category'], exitCode: 0, output: '类别  笔数  金额\n食品  4  312.50\n办公  3  96.00\n交通  2  58.00\n合计  9  466.50', truncated: false, timedOut: false, durationMs: 610, snapshot: 'ws-2a6f18' }, before: '工作区 2a6f18', after: '工作区 2a6f18（未改动）', result: '退出 0', at: T('14:37') }, 'eng-dev'),
      withRole({ id: 'a-8', department: 'quality', role: null, tool: 'run_command', summary: '质检执行登记命令 unit_tests（质检副本）', input: 'PRD r1 AC-1、AC-2', state: 'done', receipt: { command: 'unit_tests', argv: ['python', '-m', 'pytest', 'tests', '-q'], exitCode: 0, output: '............ [100%]\n12 passed in 0.43s', truncated: false, timedOut: false, durationMs: 1790, snapshot: 'qa-2a6f18' }, before: '质检副本 2a6f18', after: '质检副本 2a6f18（未改动）', result: '退出 0 · 12 条通过', at: T('14:44') }, 'qa-tester'),
      withRole({ id: 'a-9', department: 'quality', role: null, tool: 'read_file', summary: '读取质检副本中的 out/categorized.txt', input: '检查清单第 3 项', state: 'done', receipt: null, before: null, after: null, result: '5 行：「办公」笔数为 1，应为 3', at: T('14:47') }, 'qa-tester'),
      withRole({ id: 'a-10', department: 'engineering', role: null, tool: 'run_command', summary: '请求执行未登记的命令 pip install pandas', input: '模型提出的工具调用', state: 'done', skipped: true, receipt: { command: 'pip', argv: ['pip', 'install', 'pandas'], exitCode: null, output: '未登记的命令，没有执行', truncated: false, timedOut: false, durationMs: 0, snapshot: null }, before: null, after: null, result: '被拒绝：未登记的命令', at: T('15:02') }, 'eng-dev'),
      withRole({ id: 'a-11', department: 'engineering', role: null, tool: 'edit_range', summary: '按区间编辑 report.py 第 63–70 行：同一类别累计笔数', input: '质检缺陷 D-1', state: 'done', receipt: null, before: 'report.py @ 2a6f18', after: 'report.py @ c47b9e', result: '+4 −2 行', at: T('15:04') }, 'eng-dev'),
      withRole({ id: 'a-12', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 unit_tests（修改后）', input: '部门指导 g-1', state: 'done', receipt: { command: 'unit_tests', argv: ['python', '-m', 'pytest', 'tests', '-q'], exitCode: 0, output: '............. [100%]\n13 passed in 0.44s', truncated: false, timedOut: false, durationMs: 1850, snapshot: 'ws-e05d71' }, before: '工作区 e05d71', after: '工作区 e05d71（未改动）', result: '退出 0 · 13 条通过', at: T('15:15') }, 'eng-dev'),
      withRole({ id: 'a-13', department: 'quality', role: null, tool: 'run_command', summary: '质检执行登记命令 report_categorized（质检副本）', input: 'PRD r2 AC-3', state: 'done', receipt: { command: 'report_categorized', argv: ['python', 'report.py', 'samples/sales.csv', '--by-category'], exitCode: 1, output: '--- expected/categorized.txt\n+++ actual\n@@ -5 +5 @@\n-合计  9  466.50\n+合计  9  466.50\\ No newline at end of file', truncated: false, timedOut: false, durationMs: 700, snapshot: 'qa-e05d71' }, before: '质检副本 e05d71', after: '质检副本 e05d71（未改动）', result: '退出 1：末尾缺少换行', at: T('15:22') }, 'qa-tester'),
      withRole({ id: 'a-14', department: 'engineering', role: null, tool: 'edit_range', summary: '按区间编辑 report.py 第 88–90 行：输出末尾补换行', input: '质检缺陷 D-2；部门指导 g-2', state: 'done', receipt: null, before: 'report.py @ e05d71', after: 'report.py @ 5f3a0c', result: '+1 −1 行', at: T('15:27') }, 'eng-dev')
    ],
    contexts: {
      product: [
        { id: 'ctx-p2', at: T('15:06'), title: '产品激活 2（回答咨询）', attemptId: 'att-rcat-09', sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '待处理协作', version: 'q-1', included: true }, { label: '当前合同', version: 'PRD r1', included: true }, { label: '部门规则', version: '默认 v0', included: true }, { label: '项目上下文', version: '采纳 r2', included: true }] },
        { id: 'ctx-p1', at: T('14:11'), title: '产品激活 1', attemptId: 'att-rcat-01', sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '部门规则', version: '默认 v0', included: true }, { label: '工具定义', version: '5 个工具', included: true }, { label: '项目上下文', version: '采纳 r2', included: true }] }
      ],
      engineering: [
        { id: 'ctx-e3', at: T('15:25'), title: '工程激活 3（返工 D-2）', attemptId: 'att-rcat-12', sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '部门规则', version: 'v2', included: true }, { label: '当前合同', version: 'PRD r2', included: true }, { label: '当前工程计划', version: 'PLAN r3', included: true }, { label: '质检缺陷', version: 'D-2', included: true }, { label: '部门历史', version: '摘要 2 + 最近 18 条', included: true }, { label: '部门指导', version: 'g-2', included: true }, { label: '工具定义', version: '7 个工具', included: true }, { label: '项目上下文', version: '采纳 r2', included: true }, { label: '用户原文', version: 'v2', included: false, note: '已交给产品处理，工程尚不可见' }] },
        { id: 'ctx-e2', at: T('15:03'), title: '工程激活 2（返工 D-1）', attemptId: 'att-rcat-08', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '质检缺陷', version: 'D-1', included: true }, { label: '部门历史', version: '摘要 1 + 最近 24 条', included: true }, { label: '工具定义', version: '7 个工具', included: true }] },
        { id: 'ctx-e1', at: T('14:19'), title: '工程激活 1', attemptId: 'att-rcat-03', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '部门规则', version: 'v2', included: true }, { label: '部门指导', version: 'g-1', included: true }, { label: '工具定义', version: '7 个工具', included: true }, { label: '项目上下文', version: '采纳 r2', included: true }] }
      ],
      quality: [
        { id: 'ctx-q2', at: T('15:19'), title: '质检激活 2', attemptId: 'att-rcat-10', sources: [{ label: '当前合同', version: 'PRD r2', included: true }, { label: '前次交付', version: '交付 r2', included: true }, { label: '部门规则', version: 'v1', included: true }] },
        { id: 'ctx-q1', at: T('14:42'), title: '质检激活 1', attemptId: 'att-rcat-06', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '前次交付', version: '交付 r1', included: true }, { label: '部门指导', version: 'g-3', included: true }] }
      ]
    },
    prompts: prompts(2, 1),
    compactions: [
      { department: 'engineering', n: 1, at: T('15:02'), coverage: 'seq 10–55', eventId: 'e-rcat-0057' },
      { department: 'engineering', n: 2, at: T('15:25'), coverage: 'seq 10–89', eventId: 'e-rcat-0090' }
    ],
    effectiveModel: effective({ product: EM.productDefault, engineering: EM.engineeringProject, quality: EM.qualityDefault }),
    roles: roleSet({
      'eng-manager': { status: 'working', task: '核对 D-2 的修复进展，准备提交交付 r3' },
      'eng-architect': { status: 'returned', task: 'PLAN r3：输出末尾补换行（已交回）' },
      'eng-dev': { status: 'working', task: '修正 report.py 末尾换行并运行 report_categorized' },
      'eng-explorer': { status: 'away', task: '查阅 Python csv 模块的换行处理' },
      'prod-manager': { status: 'idle', task: '用户输入 v2 等待下一次产品激活' }
    }),
    ledger: {
      level: 's4',
      product: {
        items: [
          { id: 'PP-1', text: '整理用户输入 v1 为 PRD r1', assignee: 'prod-architect', status: 'returned', result: 'PRD r1 已接纳' },
          { id: 'PP-2', text: '回答工程咨询 q-1', assignee: 'prod-architect', status: 'returned', result: 'PRD r2 增加 AC-4' },
          { id: 'PP-3', text: '处理用户输入 v2：「共 N 个类别」', assignee: 'prod-architect', status: 'assigned', result: null }
        ],
        facts: ['用户输入 v2 与 r2 的「最后一行为合计金额」冲突（U-13 ↔ U-14）'],
        questions: ['「共 N 个类别」放在合计之前还是之后'],
        progress: [{ cycle: 1, judgment: '有进展', text: 'PRD r1' }, { cycle: 2, judgment: '有进展', text: 'PRD r2' }]
      },
      engineering: {
        items: [
          { id: 'P-1', text: '按首次出现顺序汇总（AC-1、AC-2）', assignee: 'eng-dev', status: 'returned', result: '交付 r1' },
          { id: 'P-2', text: '同一类别累计笔数（D-1）', assignee: 'eng-dev', status: 'returned', result: '交付 r2' },
          { id: 'P-3', text: '空类别名显示为「未分类」（AC-4）', assignee: 'eng-dev', status: 'returned', result: '交付 r2' },
          { id: 'P-4', text: '输出末尾补换行（D-2）', assignee: 'eng-dev', status: 'working', result: null },
          { id: 'P-5', text: '查阅 csv 模块的换行处理', assignee: 'eng-explorer', status: 'assigned', result: null }
        ],
        facts: ['unit_tests 共 13 条用例，15:15 全部通过（回执 a-12）', 'report_categorized 按字节比较输出，末尾换行会影响结果'],
        questions: ['用户输入 v2 是否影响本轮交付（产品尚未处理）'],
        progress: [
          { cycle: 1, judgment: '有进展', text: '交付 r1' },
          { cycle: 2, judgment: '有进展', text: '修复 D-1，交付 r2' },
          { cycle: 3, judgment: '有进展', text: '正在修复 D-2' }
        ]
      },
      quality: {
        items: [
          { id: 'QP-1', text: '按 AC-1 至 AC-4 设计检查', assignee: 'qa-tester', status: 'returned', result: '检查清单 6 项' },
          { id: 'QP-2', text: '探索性检查空文件与超长类别名', assignee: 'qa-explorer', status: 'returned', result: '发现 1 项：超长类别名被截断（未违反验收条件，记为观察）' }
        ],
        facts: ['D-2 可稳定复现：report_categorized 退出 1'],
        questions: [],
        progress: [{ cycle: 1, judgment: '有进展', text: 'D-1' }, { cycle: 2, judgment: '有进展', text: 'D-2' }]
      }
    },
    attempts: [
      att({ id: 'att-rcat-01', logicalCallId: 'call-p1-1', department: 'product', r: 'prod-architect', startedAt: T('14:11:05'), durationMs: 18400, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(8421, 1320, 0), target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0), semanticUnits: units(['U-1', 'U-12']) }),
      att({ id: 'att-rcat-02', logicalCallId: 'call-p1-2', department: 'product', r: 'prod-architect', startedAt: T('14:15:12'), durationMs: 22100, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(10288, 2210, 6144), target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0), semanticUnits: units(['U-1', 'U-12', 'U-13']) }),
      att({ id: 'att-rcat-03', logicalCallId: 'call-e1-1', department: 'engineering', r: 'eng-architect', startedAt: T('14:19:30'), durationMs: 26800, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(15530, 1804, 0), target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'high', 2), semanticUnits: units(['U-2', 'U-3', 'U-4', 'U-5']) }),
      att({ id: 'att-rcat-04', logicalCallId: 'call-e1-2', department: 'engineering', r: 'eng-dev', n: 1, of: 3, status: 'failed', startedAt: T('14:26:02'), durationMs: 120000, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: null, usage: null, error: { category: 'timeout', code: 'provider_timeout', http: null, text: '120 秒内没有收到响应，按重试规则等待后第 2 次请求' }, target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'high', 2), semanticUnits: units(['U-2', 'U-3', 'U-4', 'U-5']) }),
      att({ id: 'att-rcat-05', logicalCallId: 'call-e1-2', department: 'engineering', r: 'eng-dev', n: 2, of: 3, startedAt: T('14:28:10'), durationMs: 31200, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(21044, 2630, 14336), target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'high', 2), semanticUnits: units(['U-2', 'U-3', 'U-4', 'U-5']) }),
      att({ id: 'att-rcat-06', logicalCallId: 'call-q1-1', department: 'quality', r: 'qa-tester', startedAt: T('14:42:20'), durationMs: 16900, provider: 'opencode-go-responses', requestedModel: 'mimo-v2.5', actualModel: 'mimo-v2.5', usage: usage(12876, 1422, 0), target: tgt('opencode-go-responses', 'mimo-v2.5', '部门默认', null, 'medium', 1), semanticUnits: units(['U-3', 'U-4', 'U-5']) }),
      att({ id: 'att-rcat-07', logicalCallId: 'call-q1-2', department: 'quality', r: 'qa-tester', startedAt: T('14:49:02'), durationMs: 14300, provider: 'opencode-go-responses', requestedModel: 'mimo-v2.5', actualModel: 'mimo-v2.5', usage: usage(16011, 980, 11264), target: tgt('opencode-go-responses', 'mimo-v2.5', '部门默认', null, 'medium', 1), semanticUnits: units(['U-3', 'U-4', 'U-5', 'U-11']) }),
      att({ id: 'att-rcat-08', logicalCallId: 'call-e2-1', department: 'engineering', r: 'eng-dev', startedAt: T('15:03:10'), durationMs: 29400, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(33410, 2980, 24576), target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'high', 2, { upstream: 36390, local: 34120 }), semanticUnits: units(['U-2', 'U-4', 'U-11', 'U-15']) }),
      att({ id: 'att-rcat-09', logicalCallId: 'call-p2-1', department: 'product', r: 'prod-architect', kind: 'collaboration', startedAt: T('15:06:01'), durationMs: 12700, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(9120, 860, 5120), target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0), semanticUnits: units(['U-2', 'U-6']) }),
      att({ id: 'att-rcat-10', logicalCallId: 'call-q2-1', department: 'quality', r: 'qa-tester', startedAt: T('15:21:30'), durationMs: 15600, provider: 'opencode-go-responses', requestedModel: 'mimo-v2.5', actualModel: 'mimo-v2.5', usage: usage(18842, 1204, 16384), target: tgt('opencode-go-responses', 'mimo-v2.5', '部门默认', null, 'medium', 1), semanticUnits: units(['U-3', 'U-4', 'U-5', 'U-7']) }),
      att({ id: 'att-rcat-11', logicalCallId: 'call-e3-c', department: 'engineering', r: 'eng-dev', kind: 'compaction', startedAt: T('15:25:04'), durationMs: 24100, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(41022, 3120, 0), target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'low', 2, { upstream: 44142, local: 45380 }), semanticUnits: [] }),
      att({ id: 'att-rcat-12', logicalCallId: 'call-e3-1', department: 'engineering', r: 'eng-dev', status: 'running', startedAt: T('15:28:40'), durationMs: null, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: null, usage: null, target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'high', 2, { upstream: 21010, local: 22460 }), semanticUnits: units(['U-2', 'U-5', 'U-8', 'U-9', 'U-10', 'U-15']) }),
      { level: 's4', id: 'att-rcat-13', logicalCallId: 'call-e3-m', department: 'engineering', role: 'eng-manager', kind: 'work', n: 1, of: 3, status: 'succeeded', startedAt: T('15:26:10'), durationMs: 9800, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(12310, 640, 8192), error: null, target: tgt('opencode-go-responses', 'kimi-k2.6', '部门默认', 'high', 'high', 2), semanticUnits: units(['U-5', 'U-9', 'U-10']) },
      { level: 's4', id: 'att-rcat-14', logicalCallId: 'call-e3-x', department: 'engineering', role: 'eng-explorer', kind: 'work', n: 1, of: 3, status: 'succeeded', startedAt: T('15:27:20'), durationMs: 7600, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(6420, 910, 0), error: null, target: tgt('opencode-go-responses', 'glm-5', '项目设置', 'low', 'low', 2), semanticUnits: units(['U-15']) }
    ],
    source: null
  };

  // ---------------------------------------------------------------------------
  // run：r-empty 空输入时给出提示（当前档未开始；s3 起排队中）

  const rEmpty = {
    id: 'r-empty', workItemId: 'w-empty', phase: 'PRODUCT_SPEC', department: null, lastDepartment: null, cycle: 0,
    startedAt: null, elapsedSec: 0, limitSec: 7200, stopReason: null,
    recovery: {
      level: 's3', state: 'running', reason: '排队中，尚未取得执行槽位', unusable: null, lastConfirmed: null,
      canResume: false, resumeBlockedReason: '事项在排队，尚未开始', owner: null, lateResults: [], verifications: [], nextActions: [{ id: 'cancel-queue', label: '取消排队' }], unfinished: [],
      limits: { activations: 0, modelSteps: 0, retries: 0 }
    },
    inputs: [
      { version: 1, kind: 'user', text: '输入文件为空时给出提示「没有可汇总的记录」，退出码为 0。', at: T('15:18'), progress: 'received', bytes: [0, 90] }
    ],
    flow: [], requests: [], guidance: [],
    messages: { product: [], engineering: [], quality: [], operations: [] },
    actions: [], contexts: { product: [], engineering: [], quality: [] },
    prompts: prompts(2, 1), compactions: [],
    effectiveModel: effective({ product: EM.productDefault, engineering: EM.engineeringProject, quality: EM.qualityDefault }),
    roles: roleSet(), ledger: { level: 's4' }, attempts: [], source: null
  };

  // ---------------------------------------------------------------------------
  // run：r-head 表头改为中文（已放行，基线已变；s3 起为未采纳候选）

  const rHead = {
    id: 'r-head', workItemId: 'w-head', phase: 'DONE', department: null, lastDepartment: 'quality', cycle: 1,
    startedAt: T('16:05', '23'), elapsedSec: 6180, limitSec: 7200, stopReason: null,
    recovery: recoveryTerminated('质检放行；开始时的基线 r1 已被 r2 取代，成果保留为未采纳候选', 71, { activations: 3, modelSteps: 26, retries: 0 }),
    inputs: [
      { version: 1, kind: 'user', text: '汇总表的表头改为中文：日期、类别、金额。', at: T('16:05', '23'), progress: 'accepted', bytes: [0, 60] }
    ],
    flow: [
      { seq: 2, at: T('16:05', '23'), from: 'user', to: 'product', kind: 'handoff', content: '用户输入 v1：表头改为中文', status: '已接收', eventId: 'e-rhead-0002' },
      { seq: 6, at: T('16:12', '23'), from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：表头改为中文（AC-1、AC-2）', status: '已接收', eventId: 'e-rhead-0006' },
      { seq: 40, at: T('17:21', '23'), from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r1：表头常量改为中文', status: '已验收', eventId: 'e-rhead-0040' },
      { seq: 66, at: T('17:46', '23'), from: 'quality', to: 'adoption', kind: 'release', content: '放行：8 条检查全部通过', status: '已放行', eventId: 'e-rhead-0066' },
      { seq: 71, at: T('17:50', '23'), from: 'quality', to: 'adoption', kind: 'held', content: '未采纳：开始时的基线为 r1，r2（按类别汇总）已在 17:40 被采纳', status: '未采纳候选', eventId: 'e-rhead-0071' }
    ],
    requests: [], guidance: [],
    messages: {
      product: [{ seq: 2, at: T('16:05', '23'), source: 'user', from: 'user', text: '汇总表的表头改为中文：日期、类别、金额。', eventId: 'e-rhead-0002' }],
      engineering: [{ seq: 39, at: T('17:20', '23'), source: 'self', from: 'engineering', text: '交付 r1 已提交', eventId: 'e-rhead-0039' }],
      quality: [{ seq: 65, at: T('17:45', '23'), source: 'self', from: 'quality', text: 'QA：放行', eventId: 'e-rhead-0065' }],
      operations: []
    },
    actions: [
      withRole({ id: 'a-h1', department: 'engineering', role: null, tool: 'edit_range', summary: '按区间编辑 report.py 第 12–16 行：表头常量改为中文', input: 'PLAN r1 第 1 项', state: 'done', receipt: null, before: 'report.py @ 1d7a02（基线 r1）', after: 'report.py @ 90ab3e', result: '+3 −3 行', at: T('16:40', '23') }, 'eng-dev'),
      withRole({ id: 'a-h2', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 unit_tests', input: 'PLAN r1 第 2 项', state: 'done', receipt: { command: 'unit_tests', argv: ['python', '-m', 'pytest', 'tests', '-q'], exitCode: 0, output: '............ [100%]\n12 passed in 0.39s', truncated: false, timedOut: false, durationMs: 1720, snapshot: 'ws-90ab3e' }, before: '工作区 90ab3e', after: '工作区 90ab3e（未改动）', result: '退出 0 · 12 条通过', at: T('17:12', '23') }, 'eng-dev')
    ],
    contexts: { product: [], engineering: [{ id: 'ctx-h-e1', at: T('16:13', '23'), title: '工程激活 1', attemptId: 'att-rhead-01', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '项目上下文', version: '采纳 r1', included: true }] }], quality: [] },
    prompts: prompts(1, 1), compactions: [],
    effectiveModel: effective({ product: EM.productDefault, engineering: EM.engineeringProject, quality: EM.qualityDefault }),
    roles: roleSet(), ledger: { level: 's4' },
    attempts: [
      att({ id: 'att-rhead-01', logicalCallId: 'call-h-e1', department: 'engineering', r: 'eng-dev', startedAt: T('16:14', '23'), durationMs: 28800, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(12880, 2440, 0), target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'high', 1) }),
      att({ id: 'att-rhead-02', logicalCallId: 'call-h-q1', department: 'quality', r: 'qa-tester', startedAt: T('17:23', '23'), durationMs: 14100, provider: 'opencode-go-responses', requestedModel: 'mimo-v2.5', actualModel: 'mimo-v2.5', usage: usage(10440, 910, 0), target: tgt('opencode-go-responses', 'mimo-v2.5', '部门默认', null, 'medium', 1) })
    ],
    source: null
  };

  // ---------------------------------------------------------------------------
  // run：r-weight 超重箱子单独列出（当前档工程进行中；s3 起待核实）

  const rWeight = {
    id: 'r-weight', workItemId: 'w-weight', phase: 'ENGINEERING', department: 'engineering', lastDepartment: 'engineering', cycle: 1,
    startedAt: T('14:20'), elapsedSec: 4200, limitSec: 7200, stopReason: null,
    levels: { s3: { elapsedSec: 2441 } },
    recovery: {
      level: 's3', state: 'pending_verification',
      reason: '服务在 15:01 重启时，工程部门的登记命令 unit_tests 已开始但没有回执，结果未知',
      unusable: null,
      lastConfirmed: { seq: 57, text: '工程按区间编辑 planner.py 第 12–40 行（已完成，快照 71c0de）' },
      canResume: false, resumeBlockedReason: '有结果未知的动作，需要先核实',
      owner: { id: 'exec-2c91', since: T('15:02:14') },
      lateResults: [],
      verifications: [],
      nextActions: [
        { id: 'verify-a-w4', label: '核实 unit_tests 的结果' },
        { id: 'rerun-a-w4', label: '确认未产生副作用后重新执行' }
      ],
      unfinished: ['a-w4'],
      limits: { activations: 2, modelSteps: 19, retries: 0 }
    },
    inputs: [
      { version: 1, kind: 'user', text: '装载清单里超过单车载重的箱子单独列出，不参与装车顺序。', at: T('14:20'), progress: 'accepted', bytes: [0, 84] }
    ],
    flow: [
      { seq: 2, at: T('14:20'), from: 'user', to: 'product', kind: 'handoff', content: '用户输入 v1：超重箱子单独列出', status: '已接收', eventId: 'e-rw-0002' },
      { seq: 7, at: T('14:31'), from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：超重箱子单独列出（AC-1 至 AC-3）', status: '已接收', eventId: 'e-rw-0007' }
    ],
    requests: [], guidance: [],
    messages: {
      product: [
        { seq: 2, at: T('14:20'), source: 'user', from: 'user', text: '装载清单里超过单车载重的箱子单独列出，不参与装车顺序。', eventId: 'e-rw-0002' },
        { seq: 6, at: T('14:30'), source: 'self', from: 'product', text: 'PRD r1 已提交：3 条验收条件', eventId: 'e-rw-0006' }
      ],
      engineering: [
        { seq: 7, at: T('14:31'), source: 'other', from: 'product', text: 'PRD r1 交接', eventId: 'e-rw-0007' },
        { seq: 11, at: T('14:36'), source: 'self', from: 'engineering', text: 'PLAN r1：在 planner.py 中先筛出超重箱子，再排序其余箱子', eventId: 'e-rw-0011' },
        { seq: 57, at: T('14:58'), source: 'self', from: 'engineering', text: '按区间编辑 planner.py 第 12–40 行', eventId: 'e-rw-0057' },
        { seq: 60, at: T('15:00:41'), source: 'self', from: 'engineering', text: '开始执行登记命令 unit_tests', eventId: 'e-rw-0060' }
      ],
      quality: [],
      operations: []
    },
    actions: [
      withRole({ id: 'a-w1', department: 'engineering', role: null, tool: 'search', summary: '搜索 "max_load" 定位载重检查', input: 'PRD r1 AC-1', state: 'done', receipt: null, before: null, after: null, result: '3 处：planner.py:14、planner.py:52、tests/test_planner.py:8', at: T('14:40') }, 'eng-dev'),
      withRole({ id: 'a-w2', department: 'engineering', role: null, tool: 'read_range', summary: '按区间阅读 planner.py 第 1–60 行', input: '搜索结果 a-w1', state: 'done', receipt: null, before: null, after: null, result: '60 行', at: T('14:42') }, 'eng-dev'),
      withRole({ id: 'a-w3', department: 'engineering', role: null, tool: 'edit_range', summary: '按区间编辑 planner.py 第 12–40 行：先筛出超重箱子', input: 'PLAN r1 第 1 项', state: 'done', receipt: null, before: 'planner.py @ 5a1c90', after: 'planner.py @ 71c0de', result: '+14 −3 行', at: T('14:58') }, 'eng-dev'),
      withRole({ level: 's3', id: 'a-w4', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 unit_tests', input: 'PLAN r1 第 3 项：自测', state: 'unknown', receipt: null, before: '工作区 71c0de（编辑后）', after: null, result: '已开始，没有回执', at: T('15:00:41'), startedEvent: 'e-rw-0060' }, 'eng-dev')
    ],
    contexts: {
      product: [{ id: 'ctx-w-p1', at: T('14:21'), title: '产品激活 1', attemptId: 'att-rw-01', sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '部门规则', version: '默认 v0', included: true }] }],
      engineering: [{ id: 'ctx-w-e1', at: T('14:32'), title: '工程激活 1', attemptId: 'att-rw-03', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '部门规则', version: '默认 v0', included: true }, { label: '工具定义', version: '7 个工具', included: true }] }],
      quality: []
    },
    prompts: prompts(0, 0), compactions: [],
    effectiveModel: effective({
      product: EM.productDefault, engineering: EM.engineeringDefault,
      quality: { definition: 'local-custom/qwen3-coder-30b', connection: 'local-custom', protocol: 'Chat Completions', source: '项目设置', level: null, sentLevel: null, unusable: '准入已作废' }
    }),
    roles: roleSet({ 'eng-dev': { status: 'working', task: '运行 unit_tests 自测（结果未知）' }, 'eng-manager': { status: 'assigned', task: '等待开发者交回结果' } }),
    ledger: {
      level: 's4',
      engineering: {
        items: [
          { id: 'P-1', text: '先筛出超重箱子（AC-1）', assignee: 'eng-dev', status: 'returned', result: 'planner.py 第 12–40 行' },
          { id: 'P-2', text: '超重箱子单独列在输出末尾（AC-2）', assignee: 'eng-dev', status: 'working', result: null }
        ],
        facts: ['单车载重在 config.toml 的 max_load 中'],
        questions: [],
        progress: [{ cycle: 1, judgment: '有进展', text: '完成 P-1' }]
      }
    },
    attempts: [
      att({ id: 'att-rw-01', logicalCallId: 'call-w-p1', department: 'product', r: 'prod-architect', startedAt: T('14:21'), durationMs: 20300, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(5980, 1510, 0), target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0) }),
      att({ id: 'att-rw-02', logicalCallId: 'call-w-p2', department: 'product', r: 'prod-architect', startedAt: T('14:26'), durationMs: 16100, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(7420, 1260, 4096), target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0) }),
      att({ id: 'att-rw-03', logicalCallId: 'call-w-e1', department: 'engineering', r: 'eng-dev', startedAt: T('14:33'), durationMs: 27400, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(11760, 2380, 0), target: tgt('opencode-go-responses', 'kimi-k2.6', '部门默认', 'high', 'high', 0) }),
      att({ id: 'att-rw-04', logicalCallId: 'call-w-e2', department: 'engineering', r: 'eng-dev', startedAt: T('14:52'), durationMs: 25900, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(16330, 2860, 10240), target: tgt('opencode-go-responses', 'kimi-k2.6', '部门默认', 'high', 'high', 0) }),
      att({ id: 'att-rw-05', logicalCallId: 'call-w-e3', department: 'engineering', r: 'eng-dev', startedAt: T('15:00:05'), durationMs: 24600, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(19040, 1120, 14336), target: tgt('opencode-go-responses', 'kimi-k2.6', '部门默认', 'high', 'high', 0) })
    ],
    source: { dir: 'D:/work/cargo-planner', digest: 'sha256:5a1c90…', files: 14 }
  };

  // ---------------------------------------------------------------------------
  // run：r-export 导出 CSV（当前档执行失败 provider_error；s3 起待恢复）

  const rExport = {
    id: 'r-export', workItemId: 'w-export', phase: 'FAILED', department: null, lastDepartment: 'quality', cycle: 1,
    startedAt: T('14:05'), elapsedSec: 3900, limitSec: 7200,
    stopReason: { code: 'provider_error', text: '质检部门模型请求失败：HTTP 401，凭据被上游拒绝' },
    recovery: {
      level: 's3', state: 'waiting_resume',
      reason: '模型引用无法使用：质检部门的 mimo-v2.5（Provider 配置 opencode-go-chat）凭据被上游拒绝。事项停在这次请求之前，已完成的工作与已用限额保留。',
      unusable: { department: 'quality', model: 'opencode-go-chat/mimo-v2.5', problem: '凭据被上游拒绝', credentialRef: 'OPENCODE_GO_LAB_KEY', http: 401, links: [{ label: '在模型管理更新凭据', go: '#/sys/models' }, { label: '在本项目的质检设置另选模型', go: '#/p/p-lab/settings' }] },
      lastConfirmed: { seq: 83, text: '交付 r1 已封存并交给质检（15:00）' },
      canResume: false, resumeBlockedReason: '原因尚未修复：OPENCODE_GO_LAB_KEY 仍被上游拒绝',
      owner: null, lateResults: [], verifications: [],
      nextActions: [
        { id: 'fix-credential', label: '在模型管理更新凭据', go: '#/sys/models' },
        { id: 'choose-model', label: '在本项目的质检设置另选模型', go: '#/p/p-lab/settings' },
        { id: 'resume', label: '继续执行' }
      ],
      unfinished: [],
      limits: { activations: 3, modelSteps: 31, retries: 0 }
    },
    inputs: [
      { version: 1, kind: 'user', text: '实验记录可以导出为 CSV：每个实验一行，包含步骤数与各次观测值。', at: T('14:05'), progress: 'accepted', bytes: [0, 96] }
    ],
    flow: [
      { seq: 2, at: T('14:05'), from: 'user', to: 'product', kind: 'handoff', content: '用户输入 v1：导出 CSV', status: '已接收', eventId: 'e-rx-0002' },
      { seq: 8, at: T('14:14'), from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：每个实验一行（AC-1 至 AC-4）', status: '已接收', eventId: 'e-rx-0008' },
      { seq: 83, at: T('15:00'), from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r1：新增 lab/export.py 与 export_csv 命令', status: '质检中断', eventId: 'e-rx-0083' }
    ],
    requests: [], guidance: [],
    messages: {
      product: [
        { seq: 2, at: T('14:05'), source: 'user', from: 'user', text: '实验记录可以导出为 CSV：每个实验一行，包含步骤数与各次观测值。', eventId: 'e-rx-0002' },
        { seq: 7, at: T('14:13'), source: 'self', from: 'product', text: 'PRD r1 已提交：4 条验收条件', eventId: 'e-rx-0007' }
      ],
      engineering: [
        { seq: 8, at: T('14:14'), source: 'other', from: 'product', text: 'PRD r1 交接', eventId: 'e-rx-0008' },
        { seq: 82, at: T('14:59'), source: 'self', from: 'engineering', text: '交付 r1 已提交', eventId: 'e-rx-0082' }
      ],
      quality: [
        { seq: 83, at: T('15:00'), source: 'other', from: 'engineering', text: '交付 r1 交接', eventId: 'e-rx-0083' },
        { seq: 86, at: T('15:10'), source: 'self', from: 'quality', text: '模型请求失败：HTTP 401（Invalid API key）', eventId: 'e-rx-0086' }
      ],
      operations: []
    },
    actions: [
      withRole({ id: 'a-x1', department: 'engineering', role: null, tool: 'search', summary: '搜索 "class Experiment" 定位数据结构', input: 'PRD r1 AC-1', state: 'done', receipt: null, before: null, after: null, result: '1 处：lab/models.py:9', at: T('14:20') }, 'eng-dev'),
      withRole({ id: 'a-x2', department: 'engineering', role: null, tool: 'write_file', summary: '新建 lab/export.py：按实验逐行写出 CSV', input: 'PLAN r1 第 1 项', state: 'done', receipt: null, before: '工作区 0c44e1', after: '工作区 b73a50', result: '写入 64 行', at: T('14:38') }, 'eng-dev'),
      withRole({ id: 'a-x3', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 unit_tests', input: 'PLAN r1 第 3 项', state: 'done', receipt: { command: 'unit_tests', argv: ['python', '-m', 'pytest', '-q'], exitCode: 0, output: '......... [100%]\n9 passed in 0.62s', truncated: false, timedOut: false, durationMs: 2010, snapshot: 'ws-b73a50' }, before: '工作区 b73a50', after: '工作区 b73a50（未改动）', result: '退出 0 · 9 条通过', at: T('14:51') }, 'eng-dev'),
      withRole({ id: 'a-x4', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 export_csv', input: 'PRD r1 AC-2', state: 'done', receipt: { command: 'export_csv', argv: ['python', 'lab.py', 'export', '--format', 'csv'], exitCode: 0, output: 'wrote exports/lab-0924.csv (3 rows)', truncated: false, timedOut: false, durationMs: 880, snapshot: 'ws-b73a50' }, before: '工作区 b73a50', after: '工作区 b73a50 + exports/lab-0924.csv', result: '退出 0 · 3 行', at: T('14:55') }, 'eng-dev')
    ],
    contexts: {
      product: [{ id: 'ctx-x-p1', at: T('14:06'), title: '产品激活 1', attemptId: 'att-rx-01', sources: [{ label: '用户原文', version: 'v1', included: true }] }],
      engineering: [{ id: 'ctx-x-e1', at: T('14:15'), title: '工程激活 1', attemptId: 'att-rx-03', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '工具定义', version: '7 个工具', included: true }] }],
      quality: [{ id: 'ctx-x-q1', at: T('15:09'), title: '质检激活 1', attemptId: 'att-rx-06', sources: [{ label: '当前合同', version: 'PRD r1', included: true }, { label: '前次交付', version: '交付 r1', included: true }] }]
    },
    prompts: prompts(0, 1), compactions: [],
    effectiveModel: effective({
      product: EM.productDefault, engineering: EM.engineeringDefault,
      quality: { definition: 'opencode-go-chat/mimo-v2.5', connection: 'opencode-go-chat', protocol: 'Chat Completions', source: '项目设置', level: null, sentLevel: 'medium', unusable: '凭据被上游拒绝：OPENCODE_GO_LAB_KEY' }
    }),
    roles: roleSet({ 'qa-tester': { status: 'failed', task: '按 AC-1 至 AC-4 检查交付 r1（模型请求失败）' } }),
    ledger: { level: 's4' },
    attempts: [
      att({ id: 'att-rx-01', logicalCallId: 'call-x-p1', department: 'product', r: 'prod-architect', startedAt: T('14:06'), durationMs: 18800, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(5410, 1390, 0), target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0) }),
      att({ id: 'att-rx-02', logicalCallId: 'call-x-p2', department: 'product', r: 'prod-architect', startedAt: T('14:10'), durationMs: 15200, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(6880, 1010, 4096), target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0) }),
      att({ id: 'att-rx-03', logicalCallId: 'call-x-e1', department: 'engineering', r: 'eng-dev', startedAt: T('14:16'), durationMs: 30100, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(10220, 2740, 0), target: tgt('opencode-go-responses', 'kimi-k2.6', '部门默认', 'high', 'high', 0) }),
      att({ id: 'att-rx-04', logicalCallId: 'call-x-e2', department: 'engineering', r: 'eng-dev', startedAt: T('14:33'), durationMs: 27600, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(15870, 2310, 8192), target: tgt('opencode-go-responses', 'kimi-k2.6', '部门默认', 'high', 'high', 0) }),
      att({ id: 'att-rx-05', logicalCallId: 'call-x-e3', department: 'engineering', r: 'eng-dev', startedAt: T('14:52'), durationMs: 21900, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: 'kimi-k2.6', usage: usage(19950, 1680, 14336), target: tgt('opencode-go-responses', 'kimi-k2.6', '部门默认', 'high', 'high', 0) }),
      att({ id: 'att-rx-06', logicalCallId: 'call-x-q1', department: 'quality', r: 'qa-tester', n: 1, of: 1, status: 'failed', startedAt: T('15:10:02'), durationMs: 640, provider: 'opencode-go-chat', requestedModel: 'mimo-v2.5', actualModel: null, usage: null, error: { category: 'auth', code: 'invalid_api_key', http: 401, text: 'Invalid API key（凭据被上游拒绝，不重试）' }, target: tgt('opencode-go-chat', 'mimo-v2.5', '项目设置', null, 'medium', 1) })
    ],
    source: null
  };

  // ---------------------------------------------------------------------------
  // run：r-timeout 排班页面加载超时（Stage 5，运维提出，产品处理中）

  const rTimeout = {
    level: 's5',
    id: 'r-timeout', workItemId: 'w-timeout', phase: 'PRODUCT_SPEC', department: 'product', lastDepartment: 'product', cycle: 1,
    startedAt: T('15:14'), elapsedSec: 960, limitSec: 7200, stopReason: null,
    recovery: { level: 's3', state: 'running', reason: null, unusable: null, lastConfirmed: { seq: 12, text: '产品收到运维的回答' }, canResume: false, resumeBlockedReason: '事项正在运行，已有有效执行者', owner: { id: 'exec-7b02', since: T('15:14') }, lateResults: [], verifications: [], nextActions: [], unfinished: [], limits: { activations: 2, modelSteps: 9, retries: 0 } },
    inputs: [
      { version: 1, kind: 'user', origin: 'operations', text: '运维报告 INC-7：排班页面在 9:00–9:30 打开时约 5.6% 超时（23/410），需要修复。', at: T('15:14'), progress: 'assigned', bytes: [0, 112] }
    ],
    flow: [
      { seq: 2, at: T('15:14'), from: 'operations', to: 'product', kind: 'defect', content: '问题反馈：INC-7 排班页面加载超时（23/410 次入口失败）', status: '已接收', eventId: 'e-rt-0002' },
      { seq: 7, at: T('15:19'), from: 'product', to: 'operations', kind: 'ask', content: '咨询：超时集中在哪个时段、哪些门店？', status: '已回答', eventId: 'e-rt-0007' },
      { seq: 11, at: T('15:23'), from: 'operations', to: 'product', kind: 'answer', content: '回答：9:00–9:30，门店数最多的两个区域；缓解后仍有 1.2%', status: '已接收', eventId: 'e-rt-0011' }
    ],
    requests: [
      { id: 'q-t1', from: 'product', to: 'operations', kind: 'ask', question: '超时集中在哪个时段、哪些门店？', status: 'answered', answer: '9:00–9:30，华东与华南两个区域；重启页面服务后降到 1.2%。', askedAt: T('15:19'), answeredAt: T('15:23'), eventId: 'e-rt-0007' }
    ],
    guidance: [],
    messages: {
      product: [
        { seq: 2, at: T('15:14'), source: 'other', from: 'operations', text: '问题反馈：INC-7 排班页面加载超时', eventId: 'e-rt-0002' },
        { seq: 7, at: T('15:19'), source: 'self', from: 'product', text: '咨询运维：超时集中在哪个时段、哪些门店？', eventId: 'e-rt-0007' },
        { seq: 11, at: T('15:23'), source: 'other', from: 'operations', text: '回答：9:00–9:30，华东与华南两个区域', eventId: 'e-rt-0011' }
      ],
      engineering: [], quality: [],
      operations: [
        { level: 's5', seq: 1, at: T('15:12'), source: 'self', from: 'operations', text: '探针：排班页面入口失败 23/410，影响已确认', eventId: 'e-rt-0001' },
        { level: 's5', seq: 2, at: T('15:14'), source: 'self', from: 'operations', text: '修复进入事项：排班页面加载超时', eventId: 'e-rt-0002' },
        { level: 's5', seq: 7, at: T('15:19'), source: 'other', from: 'product', text: '咨询：超时集中在哪个时段、哪些门店？', eventId: 'e-rt-0007' },
        { level: 's5', seq: 11, at: T('15:23'), source: 'self', from: 'operations', text: '回答：9:00–9:30，华东与华南两个区域', eventId: 'e-rt-0011' }
      ]
    },
    actions: [],
    contexts: {
      product: [{ id: 'ctx-t-p1', at: T('15:15'), title: '产品激活 1', attemptId: 'att-rt-01', sources: [{ label: '用户原文', version: 'v1（运维提出）', included: true }, { label: '项目上下文', version: '采纳 r3', included: true }, { label: '运维故障记录', version: 'INC-7', included: true }] }],
      engineering: [], quality: []
    },
    prompts: prompts(0, 0), compactions: [],
    effectiveModel: effective({ product: EM.productDefault, engineering: EM.engineeringDefault, quality: EM.qualityDefault, operations: { definition: 'opencode-go-responses/glm-5', connection: 'opencode-go-responses', protocol: 'Responses', source: '部门默认', level: 'low', sentLevel: 'low', unusable: null } }),
    roles: roleSet({ 'prod-manager': { status: 'working', task: '判断 INC-7 的修复范围' }, 'prod-architect': { status: 'working', task: '起草 PRD r1：9:00–9:30 峰值下 3 秒内打开' }, 'prod-explorer': { status: 'returned', task: '查阅排班页面的加载时序（已交回）' } }),
    ledger: {
      level: 's4',
      product: {
        items: [
          { id: 'PP-1', text: '确定超时的时段与范围', assignee: 'prod-manager', status: 'returned', result: '运维回答 q-t1' },
          { id: 'PP-2', text: '起草 PRD r1 与运行目标', assignee: 'prod-architect', status: 'working', result: null }
        ],
        facts: ['r3 发布后入口失败 23/410'], questions: ['运行目标用 p95 还是成功率'], progress: [{ cycle: 1, judgment: '有进展', text: '范围已确定' }]
      }
    },
    attempts: [
      att({ id: 'att-rt-01', logicalCallId: 'call-t-p1', department: 'product', r: 'prod-architect', startedAt: T('15:15'), durationMs: 17400, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: 'glm-5', usage: usage(8840, 1210, 0), target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0) }),
      att({ id: 'att-rt-02', logicalCallId: 'call-t-p2', department: 'product', r: 'prod-architect', status: 'running', startedAt: T('15:28'), durationMs: null, provider: 'opencode-go-responses', requestedModel: 'glm-5', actualModel: null, usage: null, target: tgt('opencode-go-responses', 'glm-5', '部门默认', null, 'medium', 0) })
    ],
    source: null
  };

  // ---------------------------------------------------------------------------
  // 资料：intend、PRD、PLAN、交付、质检的各版本与项目材料

  const materials = [
    // w-base
    { id: 'm-base-i1', projectId: 'p-report', workItemId: 'w-base', kind: 'intend', version: 1, title: 'intend v1', text: '做一个命令行工具：读取 sales.csv，按行输出日期、类别、金额，最后一行给出合计金额。', at: T('10:05', '22'), bytes: [0, 132], files: null, verdict: null },
    { id: 'm-base-p1', projectId: 'p-report', workItemId: 'w-base', kind: 'prd', version: 1, title: 'PRD r1', text: '# 目标\n逐行输出销售记录，最后一行给出合计金额。\n\n# 验收条件\n- AC-1 每行依次为日期、类别、金额\n- AC-2 金额保留两位小数\n- AC-3 最后一行为「合计」与总金额', acceptedFrom: '用户输入 v1', at: T('10:12', '22'), files: null, verdict: null, eventId: 'e-rbase-0004' },
    { id: 'm-base-l1', projectId: 'p-report', workItemId: 'w-base', kind: 'plan', version: 1, title: 'PLAN r1', goal: '实现 report.py 与单元测试', text: '1. 新建 report.py：读取 CSV 并逐行输出\n2. 输出合计行\n3. 编写 12 条单元测试并运行 unit_tests', at: T('10:16', '22'), files: null, verdict: null },
    { id: 'm-base-d1', projectId: 'p-report', workItemId: 'w-base', kind: 'delivery', version: 1, title: '交付 r1', summary: '新增 report.py 与 tests/test_report.py；unit_tests 12 条通过', text: '交付 r1：report.py（逐行输出与合计）、tests/test_report.py（12 条）。', at: T('10:40', '22'), files: [{ path: 'report.py', bytes: 3120 }, { path: 'tests/test_report.py', bytes: 1980 }, { path: 'samples/sales.csv', bytes: 612 }], git: { commit: '1d7a02e', parent: null, stat: '3 个文件 · +161' }, diff: '新增 report.py（118 行）\n新增 tests/test_report.py（43 行）', verdict: null },
    { id: 'm-base-q1', projectId: 'p-report', workItemId: 'w-base', kind: 'qa', version: 1, title: '质检结论 r1', text: '12 条检查全部通过，交付与 PRD r1 一致。', verdict: 'release', receipts: ['a-b3'], checks: [{ label: 'AC-1 每行字段顺序', ok: true }, { label: 'AC-2 两位小数', ok: true }, { label: 'AC-3 合计行', ok: true }], at: T('10:51', '22'), files: null },
    // w-sum
    { id: 'm-sum-i1', projectId: 'p-report', workItemId: 'w-sum', kind: 'intend', version: 1, title: 'intend v1', text: '按类别汇总金额与笔数，类别按字母顺序排列，最后一行为合计金额。', at: T('15:20', '23'), bytes: [0, 93], files: null, verdict: null },
    { id: 'm-sum-p1', projectId: 'p-report', workItemId: 'w-sum', kind: 'prd', version: 1, title: 'PRD r1', text: '# 目标\n按类别汇总金额与笔数。\n\n# 验收条件\n- AC-1 每个类别一行：类别、笔数、金额\n- AC-2 类别按字母顺序排列\n- AC-3 最后一行为合计金额\n- AC-4 金额精确到分，没有浮点误差', acceptedFrom: '用户输入 v1', at: T('15:27', '23'), files: null, verdict: null },
    { id: 'm-sum-l1', projectId: 'p-report', workItemId: 'w-sum', kind: 'plan', version: 1, title: 'PLAN r1', goal: '新增 --by-category', text: '1. 在 report.py 中新增 summarize()\n2. 新增 --by-category 参数\n3. 运行 report_categorized 自测', at: T('15:31', '23'), files: null, verdict: null },
    { id: 'm-sum-l2', projectId: 'p-report', workItemId: 'w-sum', kind: 'plan', version: 2, title: 'PLAN r2', goal: '修复 D-1', text: '1. 金额改用 Decimal\n2. 运行 unit_tests', at: T('16:34', '23'), files: null, verdict: null },
    { id: 'm-sum-d1', projectId: 'p-report', workItemId: 'w-sum', kind: 'delivery', version: 1, title: '交付 r1', summary: '新增 --by-category', text: '交付 r1：summarize() 与 --by-category。', at: T('16:09', '23'), files: [{ path: 'report.py', bytes: 3980 }, { path: 'tests/test_report.py', bytes: 2210 }], git: { commit: '7c11f5a', parent: '1d7a02e', stat: '2 个文件 · +35 −6' }, diff: '@@ report.py @@\n+def summarize(rows):\n+    totals = {}\n…', verdict: null },
    { id: 'm-sum-d2', projectId: 'p-report', workItemId: 'w-sum', kind: 'delivery', version: 2, title: '交付 r2', summary: '金额改用 Decimal 并保留两位小数', text: '交付 r2：修复 D-1。', at: T('17:04', '23'), files: [{ path: 'report.py', bytes: 4060 }, { path: 'tests/test_report.py', bytes: 2388 }], git: { commit: 'a90d33c', parent: '7c11f5a', stat: '2 个文件 · +9 −4' }, diff: '@@ report.py @@\n-    total += float(row.amount)\n+    total += Decimal(row.amount)', verdict: null },
    { id: 'm-sum-q1', projectId: 'p-report', workItemId: 'w-sum', kind: 'qa', version: 1, title: '质检结论 r1', text: '合计金额有浮点误差（D-1，违反 AC-4）。', verdict: 'rework_engineering', receipts: [], checks: [{ label: 'AC-4 金额精确到分', ok: false }], at: T('16:30', '23'), files: null },
    { id: 'm-sum-q2', projectId: 'p-report', workItemId: 'w-sum', kind: 'qa', version: 2, title: '质检结论 r2', text: '15 条检查全部通过。', verdict: 'release', receipts: ['a-s6'], checks: [{ label: 'AC-1 至 AC-4', ok: true }], at: T('17:27', '23'), files: null },
    // w-cat
    { id: 'm-cat-i1', projectId: 'p-report', workItemId: 'w-cat', kind: 'intend', version: 1, title: 'intend v1', text: '汇总表里类别的顺序改为按在输入中首次出现的顺序，不再按字母排序。', at: T('14:10'), bytes: [0, 99], files: null, verdict: null },
    { id: 'm-cat-i2', projectId: 'p-report', workItemId: 'w-cat', kind: 'intend', version: 2, title: 'intend v2', text: '汇总表最后加一行「共 N 个类别」。', at: T('15:12'), bytes: [99, 150], files: null, verdict: null },
    { id: 'm-cat-p1', projectId: 'p-report', workItemId: 'w-cat', kind: 'prd', version: 1, title: 'PRD r1', text: '# 目标\n类别按在输入中首次出现的顺序输出。\n\n# 验收条件\n- AC-1 sales.csv 的汇总第一行为「食品」\n- AC-2 同一类别多次出现时笔数累计\n- AC-3 输出与 expected/categorized.txt 逐字节一致', acceptedFrom: '用户输入 v1', at: T('14:17'), files: null, verdict: null, eventId: 'e-rcat-0008' },
    { id: 'm-cat-p2', projectId: 'p-report', workItemId: 'w-cat', kind: 'prd', version: 2, title: 'PRD r2', text: '# 目标\n类别按在输入中首次出现的顺序输出。\n\n# 验收条件\n- AC-1 至 AC-3 同 r1\n- AC-4 空类别名的记录归入「未分类」', acceptedFrom: '回答工程咨询 q-1', at: T('15:08'), files: null, verdict: null, eventId: 'e-rcat-0065' },
    { id: 'm-cat-l1', projectId: 'p-report', workItemId: 'w-cat', kind: 'plan', version: 1, title: 'PLAN r1', goal: '修改汇总顺序', text: '1. 用按首次出现顺序记录的字典替换 sorted()\n2. 运行 report_categorized 与 unit_tests', at: T('14:22'), files: null, verdict: null },
    { id: 'm-cat-l2', projectId: 'p-report', workItemId: 'w-cat', kind: 'plan', version: 2, title: 'PLAN r2', goal: '修复 D-1，实现 AC-4', text: '1. 同一类别累计笔数\n2. 空类别名归入「未分类」\n3. 运行 unit_tests', at: T('15:03'), files: null, verdict: null },
    { id: 'm-cat-l3', projectId: 'p-report', workItemId: 'w-cat', kind: 'plan', version: 3, title: 'PLAN r3', goal: '修复 D-2', text: '1. 输出末尾补换行（不改动 CSV 解析部分）\n2. 运行 report_categorized', at: T('15:26'), files: null, verdict: null },
    { id: 'm-cat-d1', projectId: 'p-report', workItemId: 'w-cat', kind: 'delivery', version: 1, title: '交付 r1', summary: '类别按首次出现顺序输出', text: '交付 r1：修改 report.py 第 41–60 行。', at: T('14:40'), files: [{ path: 'report.py', bytes: 4180 }, { path: 'tests/test_report.py', bytes: 2388 }], git: { commit: '2a6f18d', parent: 'a90d33c', stat: '1 个文件 · +12 −8' }, diff: '@@ -41,12 +41,16 @@ def summarize(rows):\n-    for name in sorted(totals):\n+    for name in order:\n', verdict: null },
    { id: 'm-cat-d2', projectId: 'p-report', workItemId: 'w-cat', kind: 'delivery', version: 2, title: '交付 r2', summary: '修复 D-1；空类别名显示为「未分类」', text: '交付 r2：修改 report.py 第 63–70 行，新增 1 条单元测试。', at: T('15:18'), files: [{ path: 'report.py', bytes: 4262 }, { path: 'tests/test_report.py', bytes: 2610 }], git: { commit: 'e05d71b', parent: '2a6f18d', stat: '2 个文件 · +11 −2' }, diff: '@@ -63,8 +63,10 @@\n-        counts[name] = 1\n+        counts[name] = counts.get(name, 0) + 1\n+    name = name or "未分类"', verdict: null },
    { id: 'm-cat-q1', projectId: 'p-report', workItemId: 'w-cat', kind: 'qa', version: 1, title: '质检结论 r1', text: '多次出现的类别只计入第一次的笔数（D-1，违反 AC-2）。', verdict: 'rework_engineering', receipts: ['a-8'], checks: [{ label: 'AC-1 第一行为「食品」', ok: true }, { label: 'AC-2 笔数累计', ok: false }, { label: 'AC-3 逐字节一致', ok: false }], at: T('14:51'), files: null },
    { id: 'm-cat-q2', projectId: 'p-report', workItemId: 'w-cat', kind: 'qa', version: 2, title: '质检结论 r2', text: '输出末尾缺少换行（D-2，违反 AC-3）。', verdict: 'rework_engineering', receipts: ['a-13'], checks: [{ label: 'AC-1', ok: true }, { label: 'AC-2', ok: true }, { label: 'AC-3 逐字节一致', ok: false }, { label: 'AC-4 未分类', ok: true }], at: T('15:24'), files: null },
    // w-empty
    { id: 'm-empty-i1', projectId: 'p-report', workItemId: 'w-empty', kind: 'intend', version: 1, title: 'intend v1', text: '输入文件为空时给出提示「没有可汇总的记录」，退出码为 0。', at: T('15:18'), bytes: [0, 90], files: null, verdict: null },
    // w-head
    { id: 'm-head-i1', projectId: 'p-report', workItemId: 'w-head', kind: 'intend', version: 1, title: 'intend v1', text: '汇总表的表头改为中文：日期、类别、金额。', at: T('16:05', '23'), bytes: [0, 60], files: null, verdict: null },
    { id: 'm-head-p1', projectId: 'p-report', workItemId: 'w-head', kind: 'prd', version: 1, title: 'PRD r1', text: '# 目标\n表头改为中文。\n\n# 验收条件\n- AC-1 表头为「日期、类别、金额」\n- AC-2 其他输出不变', acceptedFrom: '用户输入 v1', at: T('16:11', '23'), files: null, verdict: null },
    { id: 'm-head-d1', projectId: 'p-report', workItemId: 'w-head', kind: 'delivery', version: 1, title: '交付 r1', summary: '表头常量改为中文（基于 r1）', text: '交付 r1：修改 report.py 第 12–16 行。', at: T('17:20', '23'), files: [{ path: 'report.py', bytes: 3130 }], git: { commit: '90ab3e1', parent: '1d7a02e', stat: '1 个文件 · +3 −3' }, diff: '@@ -12,3 +12,3 @@\n-HEADER = ("date", "category", "amount")\n+HEADER = ("日期", "类别", "金额")', verdict: null },
    { id: 'm-head-q1', projectId: 'p-report', workItemId: 'w-head', kind: 'qa', version: 1, title: '质检结论 r1', text: '8 条检查全部通过。', verdict: 'release', receipts: [], checks: [{ label: 'AC-1、AC-2', ok: true }], at: T('17:45', '23'), files: null },
    // w-weight
    { id: 'm-weight-i1', projectId: 'p-cargo', workItemId: 'w-weight', kind: 'intend', version: 1, title: 'intend v1', text: '装载清单里超过单车载重的箱子单独列出，不参与装车顺序。', at: T('14:20'), bytes: [0, 84], files: null, verdict: null },
    { id: 'm-weight-p1', projectId: 'p-cargo', workItemId: 'w-weight', kind: 'prd', version: 1, title: 'PRD r1', text: '# 目标\n超重箱子单独列出。\n\n# 验收条件\n- AC-1 重量大于 max_load 的箱子不参与排序\n- AC-2 超重箱子列在输出末尾「超重」一节\n- AC-3 没有超重箱子时不输出该节', acceptedFrom: '用户输入 v1', at: T('14:30'), files: null, verdict: null },
    { id: 'm-weight-l1', projectId: 'p-cargo', workItemId: 'w-weight', kind: 'plan', version: 1, title: 'PLAN r1', goal: '先筛出超重箱子', text: '1. planner.py 先筛出超重箱子\n2. 输出末尾列出超重箱子\n3. 运行 unit_tests', at: T('14:36'), files: null, verdict: null },
    // w-export
    { id: 'm-export-i1', projectId: 'p-lab', workItemId: 'w-export', kind: 'intend', version: 1, title: 'intend v1', text: '实验记录可以导出为 CSV：每个实验一行，包含步骤数与各次观测值。', at: T('14:05'), bytes: [0, 96], files: null, verdict: null },
    { id: 'm-export-p1', projectId: 'p-lab', workItemId: 'w-export', kind: 'prd', version: 1, title: 'PRD r1', text: '# 目标\n导出 CSV。\n\n# 验收条件\n- AC-1 每个实验一行\n- AC-2 列为实验名、步骤数、观测值 1…n\n- AC-3 UTF-8 带表头\n- AC-4 没有实验时只输出表头', acceptedFrom: '用户输入 v1', at: T('14:13'), files: null, verdict: null },
    { id: 'm-export-l1', projectId: 'p-lab', workItemId: 'w-export', kind: 'plan', version: 1, title: 'PLAN r1', goal: '新增 lab/export.py', text: '1. 新建 lab/export.py\n2. 登记命令 export_csv\n3. 运行 unit_tests', at: T('14:17'), files: null, verdict: null },
    { id: 'm-export-d1', projectId: 'p-lab', workItemId: 'w-export', kind: 'delivery', version: 1, title: '交付 r1', summary: '新增 lab/export.py 与导出命令', text: '交付 r1：lab/export.py（64 行）。', at: T('14:59'), files: [{ path: 'lab/export.py', bytes: 2140 }, { path: 'tests/test_export.py', bytes: 1320 }], git: { commit: 'b73a50e', parent: '0c44e1f', stat: '2 个文件 · +98' }, diff: '新增 lab/export.py（64 行）\n新增 tests/test_export.py（34 行）', verdict: null },
    // w-timeout（Stage 5）
    { level: 's5', id: 'm-timeout-i1', projectId: 'p-shift', workItemId: 'w-timeout', kind: 'intend', version: 1, title: 'intend v1（运维提出）', text: '运维报告 INC-7：排班页面在 9:00–9:30 打开时约 5.6% 超时（23/410），需要修复。', at: T('15:14'), bytes: [0, 112], files: null, verdict: null },
    // 项目材料
    { id: 'm-note-1', projectId: 'p-report', workItemId: null, kind: 'note', version: 1, title: '项目材料', department: null, text: 'sales.csv 由门店每天 23:00 导出，编码为 UTF-8，第一行是表头。', at: T('09:40', '22'), files: null, verdict: null },
    { id: 'm-note-2', projectId: 'p-report', workItemId: null, kind: 'note', version: 1, title: '工程部门材料', department: 'engineering', text: '本机 Python 为 3.12；测试只用标准库与 pytest。', at: T('14:02'), files: null, verdict: null },
    { id: 'm-note-3', projectId: 'p-cargo', workItemId: null, kind: 'note', version: 1, title: '项目材料', department: null, text: '单车载重 1200 kg，见 config.toml。', at: T('14:15'), files: null, verdict: null }
  ];

  // ---------------------------------------------------------------------------
  // 场景

  const S = []; // 场景列表

  // 1. 正常循环：工程完成返工，质检放行，项目采纳 r3
  S.push({
    id: 'sc-normal', name: '正常循环', level: 'now', projectId: 'p-report', workItemId: 'w-cat', view: 'overview',
    steps: [
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'engineering', label: '工程部门的模型请求完成，提出执行登记命令 report_categorized' }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-12].status', value: 'succeeded' }, { path: 'runs[id=r-cat].attempts[id=att-rcat-12].usage', value: { input: 22460, output: 1180, cacheRead: 18432, total: 23640, cost: null } }] },
      { delay: 1200, event: { type: 'tool_started', department: 'engineering', tool: 'run_command', label: '工程走到终端，拉下拉杆：执行 report_categorized', payload: { command: 'report_categorized' } } },
      { delay: 1400, event: { type: 'tool_called', department: 'engineering', tool: 'run_command', label: 'report_categorized 退出 0，终端亮绿灯', payload: { exitCode: 0 } }, patch: [{ path: 'runs[id=r-cat].actions', push: { id: 'a-15', department: 'engineering', role: null, tool: 'run_command', summary: '执行登记命令 report_categorized（补换行后）', input: '质检缺陷 D-2', state: 'done', receipt: { command: 'report_categorized', argv: ['python', 'report.py', 'samples/sales.csv', '--by-category'], exitCode: 0, output: '类别  笔数  金额\n食品  4  312.50\n办公  3  96.00\n交通  2  58.00\n合计  9  466.50\n', truncated: false, timedOut: false, durationMs: 590, snapshot: 'ws-5f3a0c' }, before: '工作区 5f3a0c', after: '工作区 5f3a0c（未改动）', result: '退出 0', at: T('15:30') } }] },
      { delay: 1200, event: { type: 'proposal_submitted', department: 'engineering', label: '工程把交付说明放进提案托盘' } },
      { delay: 1400, event: { type: 'delivery_accepted', department: 'engineering', label: '交付 r3 封存：装箱、贴封条、盖封存章', payload: { version: 'r3' } }, patch: [{ path: 'materials', push: { id: 'm-cat-d3', projectId: 'p-report', workItemId: 'w-cat', kind: 'delivery', version: 3, title: '交付 r3', summary: '修复 D-2：输出末尾补换行', text: '交付 r3：修改 report.py 第 88–90 行。', at: T('15:31'), files: [{ path: 'report.py', bytes: 4263 }], git: { commit: '5f3a0c9', parent: 'e05d71b', stat: '1 个文件 · +1 −1' }, diff: '@@ -88,3 +88,3 @@\n-    out.write(line)\n+    out.write(line + "\\n")', verdict: null } }] },
      { delay: 1600, event: { type: 'transition', department: 'engineering', label: '送件小人把封存的交付箱从工程搬到质检', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, patch: [{ path: 'runs[id=r-cat].phase', value: 'QUALITY' }, { path: 'runs[id=r-cat].department', value: 'quality' }, { path: 'runs[id=r-cat].flow', push: { seq: 97, at: T('15:31'), from: 'engineering', to: 'quality', kind: 'delivery', content: '交付 r3：修复 D-2', status: '已接收', eventId: 'e-rcat-0097' } }, { path: 'runs[id=r-cat].flow.7.status', value: '已处理' }] },
      { delay: 1200, event: { type: 'department_activated', department: 'quality', label: '质检房间亮灯，质检部门 Agent 起身走到工位' } },
      { delay: 1200, event: { type: 'context_assembled', department: 'quality', label: '质检从文件柜取出 PRD r2 与交付 r3' }, patch: [{ path: 'runs[id=r-cat].contexts.quality', push: { id: 'ctx-q3', at: T('15:32'), title: '质检激活 3', attemptId: 'att-rcat-15', sources: [{ label: '当前合同', version: 'PRD r2', included: true }, { label: '前次交付', version: '交付 r3', included: true }, { label: '部门规则', version: 'v1', included: true }] } }] },
      { delay: 1200, event: { type: 'model_requested', department: 'quality', label: '质检开始模型请求，头顶出现思考气泡' }, patch: [{ path: 'runs[id=r-cat].attempts', push: { id: 'att-rcat-15', logicalCallId: 'call-q3-1', department: 'quality', role: null, kind: 'work', n: 1, of: 3, status: 'requesting', startedAt: T('15:32'), durationMs: null, provider: 'opencode-go-responses', requestedModel: 'mimo-v2.5', actualModel: null, usage: null, error: null, target: tgt('opencode-go-responses', 'mimo-v2.5', '部门默认', null, 'medium', 1), semanticUnits: units(['U-3', 'U-4', 'U-5', 'U-7']) } }] },
      { delay: 1000, event: { type: 'model_request_serialized', department: 'quality', label: '请求已按 Responses 协议编码并发出，屏幕滚动字符' } },
      { delay: 1400, event: { type: 'model_attempt_failed', department: 'quality', label: '第 1 次尝试 120 秒内没有响应，小人趴在桌上，桌上红灯亮' }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-15].status', value: 'failed' }, { path: 'runs[id=r-cat].attempts[id=att-rcat-15].error', value: { category: 'timeout', code: 'provider_timeout', http: null, text: '120 秒内没有收到响应' } }] },
      { delay: 1400, event: { type: 'model_retry_scheduled', department: 'quality', label: '头顶出现沙漏与「第 2/3 次」：等待后重试，事项不提前标为失败', payload: { n: 2, of: 3 } }, patch: [{ path: 'runs[id=r-cat].attempts', push: { id: 'att-rcat-16', logicalCallId: 'call-q3-1', department: 'quality', role: null, kind: 'work', n: 2, of: 3, status: 'running', startedAt: T('15:34'), durationMs: null, provider: 'opencode-go-responses', requestedModel: 'mimo-v2.5', actualModel: null, usage: null, error: null, target: tgt('opencode-go-responses', 'mimo-v2.5', '部门默认', null, 'medium', 1), semanticUnits: units(['U-3', 'U-4', 'U-5', 'U-7']) } }] },
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'quality', label: '第 2 次尝试完成，气泡变成灯泡：提出执行 report_categorized' }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-16].status', value: 'succeeded' }, { path: 'runs[id=r-cat].attempts[id=att-rcat-16].actualModel', value: 'mimo-v2.5' }] },
      { delay: 1200, event: { type: 'tool_started', department: 'quality', tool: 'run_command', label: '质检用放大镜检查箱子：在独立副本中执行 report_categorized' } },
      { delay: 1400, event: { type: 'tool_called', department: 'quality', tool: 'run_command', label: '质检主机回执：退出 0，与期望输出逐字节一致，清单逐项打勾' }, patch: [{ path: 'runs[id=r-cat].actions', push: { id: 'a-16', department: 'quality', role: null, tool: 'run_command', summary: '质检执行登记命令 report_categorized（质检副本）', input: 'PRD r2 AC-3', state: 'done', receipt: { command: 'report_categorized', argv: ['python', 'report.py', 'samples/sales.csv', '--by-category'], exitCode: 0, output: '与 expected/categorized.txt 逐字节一致', truncated: false, timedOut: false, durationMs: 610, snapshot: 'qa-5f3a0c' }, before: '质检副本 5f3a0c', after: '质检副本 5f3a0c（未改动）', result: '退出 0', at: T('15:35') } }] },
      { delay: 1500, event: { type: 'qa_submitted', department: 'quality', label: '质检盖绿色「放行」章', payload: { verdict: 'release' } }, patch: [{ path: 'materials', push: { id: 'm-cat-q3', projectId: 'p-report', workItemId: 'w-cat', kind: 'qa', version: 3, title: '质检结论 r3', text: 'AC-1 至 AC-4 全部通过。', verdict: 'release', receipts: ['a-16'], checks: [{ label: 'AC-1 至 AC-4', ok: true }], at: T('15:34'), files: null } }] },
      { delay: 1600, event: { type: 'transition', department: 'quality', label: '送件小人把放行单与交付箱送到成果库', payload: { from: 'quality', to: 'adoption', artifact: 'release' } }, patch: [{ path: 'runs[id=r-cat].phase', value: 'DONE' }, { path: 'runs[id=r-cat].department', value: null }, { path: 'runs[id=r-cat].lastDepartment', value: 'quality' }, { path: 'workItems[id=w-cat].status', value: 'released_unsettled' }, { path: 'runs[id=r-cat].flow', push: { seq: 104, at: T('15:34'), from: 'quality', to: 'adoption', kind: 'release', content: '放行：AC-1 至 AC-4 全部通过', status: '已放行', eventId: 'e-rcat-0104' } }] },
      { delay: 1600, event: { type: 'deliverable_adopted', label: '箱子放上成果库的架子，版本号变为 r3', payload: { version: 'r3' } }, patch: [{ path: 'workItems[id=w-cat].status', value: 'adopted' }, { path: 'projects[id=p-report].adoption', value: { version: 'r3', summary: '类别按首次出现顺序输出，空类别名显示为「未分类」', adoptedAt: T('15:35'), workItemId: 'w-cat' } }, { path: 'projects[id=p-report].adoptions', push: { version: 'r3', workItemId: 'w-cat', at: T('15:35') } }, { path: 'runs[id=r-cat].flow', push: { seq: 106, at: T('15:35'), from: 'quality', to: 'adoption', kind: 'adopt', content: '项目采纳 r3', status: '已采纳', eventId: 'e-rcat-0106' } }] },
      { delay: 1400, event: { type: 'run_done', label: '事项完成：门上挂「完成」牌，小人举手欢呼' }, patch: [{ path: 'runs[id=r-cat].recovery.state', value: 'terminated' }, { path: 'runs[id=r-cat].recovery.resumeBlockedReason', value: '事项已完成' }] }
    ]
  });

  // 2. 返工：质检发现缺陷，交付箱贴红色返工单退回工程
  S.push({
    id: 'sc-rework', name: '返工', level: 'now', projectId: 'p-report', workItemId: 'w-cat', view: 'dept', department: 'quality',
    steps: [
      { delay: 1200, event: { type: 'delivery_accepted', department: 'engineering', label: '工程封存交付 r3', payload: { version: 'r3' } }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-12].status', value: 'succeeded' }] },
      { delay: 1600, event: { type: 'transition', department: 'engineering', label: '交付箱从工程搬到质检', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, patch: [{ path: 'runs[id=r-cat].phase', value: 'QUALITY' }, { path: 'runs[id=r-cat].department', value: 'quality' }] },
      { delay: 1200, event: { type: 'department_activated', department: 'quality', label: '质检房间亮灯，小人走到检验台' } },
      { delay: 1200, event: { type: 'context_assembled', department: 'quality', label: '质检取出 PRD r2 与交付 r3' } },
      { delay: 1200, event: { type: 'model_requested', department: 'quality', label: '质检开始模型请求' } },
      { delay: 1000, event: { type: 'model_stream_progress', department: 'quality', label: '气泡中逐字出现：「检查未分类行的金额格式…」' } },
      { delay: 1200, event: { type: 'tool_started', department: 'quality', tool: 'run_command', label: '质检执行登记命令 unit_tests' } },
      { delay: 1400, event: { type: 'tool_called', department: 'quality', tool: 'run_command', label: 'unit_tests 退出 1：test_empty_category 失败，终端亮红灯', payload: { exitCode: 1 } }, patch: [{ path: 'runs[id=r-cat].actions', push: { id: 'a-17', department: 'quality', role: null, tool: 'run_command', summary: '质检执行登记命令 unit_tests（质检副本）', input: 'PRD r2 AC-4', state: 'done', receipt: { command: 'unit_tests', argv: ['python', '-m', 'pytest', 'tests', '-q'], exitCode: 1, output: '............F [100%]\nFAILED tests/test_report.py::test_empty_category - 期望 0.00，实际 0', truncated: false, timedOut: false, durationMs: 1880, snapshot: 'qa-5f3a0c' }, before: '质检副本 5f3a0c', after: '质检副本 5f3a0c（未改动）', result: '退出 1', at: T('15:33') } }] },
      { delay: 1500, event: { type: 'qa_submitted', department: 'quality', label: '质检盖红色「返工」章：「未分类」行的金额没有保留两位小数（D-3）', payload: { verdict: 'rework_engineering' } }, patch: [{ path: 'materials', push: { id: 'm-cat-q3', projectId: 'p-report', workItemId: 'w-cat', kind: 'qa', version: 3, title: '质检结论 r3', text: '「未分类」行的金额没有保留两位小数（D-3，违反 AC-4）。', verdict: 'rework_engineering', receipts: ['a-17'], checks: [{ label: 'AC-3', ok: true }, { label: 'AC-4 金额格式', ok: false }], at: T('15:34'), files: null } }] },
      { delay: 1800, event: { type: 'transition', department: 'quality', label: '交付箱贴上红色返工单，沿原路退回工程', payload: { from: 'quality', to: 'engineering', artifact: 'defect' } }, patch: [{ path: 'runs[id=r-cat].phase', value: 'REWORK_ENGINEERING' }, { path: 'runs[id=r-cat].department', value: 'engineering' }, { path: 'runs[id=r-cat].cycle', value: 4 }, { path: 'runs[id=r-cat].elapsedSec', value: 6480 }, { path: 'runs[id=r-cat].flow', push: { seq: 102, at: T('15:34'), from: 'quality', to: 'engineering', kind: 'rework', content: '返工：「未分类」行的金额没有保留两位小数（D-3，违反 AC-4）', status: '处理中', eventId: 'e-rcat-0102' } }] },
      { delay: 1200, event: { type: 'department_activated', department: 'engineering', label: '工程房间亮灯，信息条显示「第 4 轮」，已用 1 小时 48 分 / 2 小时，时间进度条变为警示色' }, patch: [{ path: 'runs[id=r-cat].phase', value: 'ENGINEERING' }] },
      { delay: 1200, event: { type: 'context_assembled', department: 'engineering', label: '工程取出质检缺陷 D-3 放到桌上' } },
      { delay: 1200, event: { type: 'model_requested', department: 'engineering', label: '工程开始模型请求' } },
      { delay: 1200, event: { type: 'tool_started', department: 'engineering', tool: 'read_range', label: '工程捧着 report.py 第 60–75 行阅读' } },
      { delay: 1200, event: { type: 'tool_started', department: 'engineering', tool: 'edit_range', label: '工程在文件上写字：金额格式改为两位小数' } },
      { delay: 1200, event: { type: 'tool_called', department: 'engineering', tool: 'edit_range', label: '按区间编辑完成，屏幕显示 +1 −1 行' }, patch: [{ path: 'runs[id=r-cat].actions', push: { id: 'a-18', department: 'engineering', role: null, tool: 'edit_range', summary: '按区间编辑 report.py 第 66 行：金额保留两位小数', input: '质检缺陷 D-3', state: 'done', receipt: null, before: 'report.py @ 5f3a0c', after: 'report.py @ 61d0b2', result: '+1 −1 行', at: T('15:36') } }] },
      { delay: 1600, event: { type: 'run_paused', department: 'engineering', label: '第 4 轮用完模型步骤（model_steps_exhausted）：事项暂停，小人坐下，门上挂「已暂停」牌', payload: { reason: 'model_steps_exhausted' } }, patch: [{ path: 'runs[id=r-cat].phase', value: 'PAUSED' }, { path: 'runs[id=r-cat].lastDepartment', value: 'engineering' }, { path: 'runs[id=r-cat].department', value: null }, { path: 'runs[id=r-cat].stopReason', value: { code: 'model_steps_exhausted', text: '模型步骤用完，事项暂停' } }, { path: 'workItems[id=w-cat].status', value: 'stopped' }, { path: 'runs[id=r-cat].recovery.state', value: 'terminated' }, { path: 'runs[id=r-cat].recovery.reason', value: '模型步骤用完，事项暂停' }] }
    ]
  });

  // 3. 询问与回答：工程向产品咨询，纸飞机往返
  S.push({
    id: 'sc-ask', name: '询问与回答', level: 'now', projectId: 'p-report', workItemId: 'w-cat', view: 'overview',
    steps: [
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'engineering', label: '工程的模型请求完成，决定向产品咨询' }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-12].status', value: 'succeeded' }] },
      { delay: 1600, event: { type: 'collaboration_requested', department: 'engineering', label: '工程写纸条折成纸飞机飞向产品，在门口等待', payload: { from: 'engineering', to: 'product' } }, patch: [{ path: 'runs[id=r-cat].requests', push: { id: 'q-2', from: 'engineering', to: 'product', kind: 'ask', question: '「共 N 个类别」是否计入「未分类」？放在合计之前还是之后？', status: 'open', answer: null, askedAt: T('15:30'), answeredAt: null, eventId: 'e-rcat-0096' } }, { path: 'runs[id=r-cat].flow', push: { seq: 96, at: T('15:30'), from: 'engineering', to: 'product', kind: 'ask', content: '咨询：「共 N 个类别」是否计入「未分类」？', status: '待回应', eventId: 'e-rcat-0096' } }, { path: 'runs[id=r-cat].messages.product', push: { seq: 96, at: T('15:30'), source: 'other', from: 'engineering', text: '咨询：「共 N 个类别」是否计入「未分类」？放在合计之前还是之后？', eventId: 'e-rcat-0096' } }] },
      { delay: 1200, event: { type: 'department_activated', department: 'product', label: '产品房间亮灯，接住纸飞机' } },
      { delay: 1200, event: { type: 'context_assembled', department: 'product', label: '产品取出用户输入 v2 与 PRD r2' }, patch: [{ path: 'runs[id=r-cat].inputs.1.progress', value: 'assigned' }] },
      { delay: 1200, event: { type: 'model_requested', department: 'product', label: '产品开始模型请求' } },
      { delay: 1000, event: { type: 'model_stream_progress', department: 'product', label: '气泡中逐字出现：「用户输入 v2 要求最后加一行…」' } },
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'product', label: '产品的模型请求完成' } },
      { delay: 1500, event: { type: 'spec_accepted', department: 'product', label: '产品在卷轴上盖「有效」章：PRD r3 增加 AC-5' }, patch: [{ path: 'runs[id=r-cat].inputs.1.progress', value: 'accepted' }, { path: 'materials', push: { id: 'm-cat-p3', projectId: 'p-report', workItemId: 'w-cat', kind: 'prd', version: 3, title: 'PRD r3', text: '# 验收条件\n- AC-1 至 AC-4 同 r2\n- AC-5 合计之后另起一行「共 N 个类别」，计入「未分类」', acceptedFrom: '用户输入 v2；回答工程咨询 q-2', at: T('15:32'), files: null, verdict: null } }] },
      { delay: 1600, event: { type: 'collaboration_responded', department: 'product', label: '产品写回答后把纸飞机放回工程', payload: { from: 'product', to: 'engineering' } }, patch: [{ path: 'runs[id=r-cat].requests[id=q-2].status', value: 'answered' }, { path: 'runs[id=r-cat].requests[id=q-2].answer', value: '计入「未分类」；放在合计之后另起一行，已写入 PRD r3 的 AC-5。' }, { path: 'runs[id=r-cat].requests[id=q-2].answeredAt', value: T('15:32') }, { path: 'runs[id=r-cat].flow', push: { seq: 99, at: T('15:32'), from: 'product', to: 'engineering', kind: 'answer', content: '回答：计入「未分类」，放在合计之后；PRD r3 增加 AC-5', status: '已接收', eventId: 'e-rcat-0099' } }] },
      { delay: 1400, event: { type: 'contract_accepted', department: 'product', label: '有效合同更新为 PRD r3：卷轴放上卷轴架' } },
      { delay: 1200, event: { type: 'collaboration_closed', department: 'engineering', label: '工程接住回答，这次咨询关闭' }, patch: [{ path: 'runs[id=r-cat].flow.8.status', value: '已回答' }] },
      { delay: 1200, event: { type: 'department_activated', department: 'engineering', label: '工程回到工位继续工作' } },
      { delay: 1200, event: { type: 'context_assembled', department: 'engineering', label: '工程取出 PRD r3 与产品的回答' } },
      { delay: 1200, event: { type: 'tool_started', department: 'engineering', tool: 'read_file', label: '工程捧着 expected/categorized.txt 阅读' } },
      { delay: 1400, event: { type: 'proposal_submitted', department: 'engineering', label: '工程把 PLAN r4 放进提案托盘' } },
      { delay: 1500, event: { type: 'proposal_rejected', department: 'engineering', label: '提案被退回：PLAN r4 没有计划项对应 AC-5，小人挠头' }, patch: [{ path: 'runs[id=r-cat].messages.engineering', push: { seq: 104, at: T('15:33'), source: 'self', from: 'engineering', text: '提案被退回：PLAN r4 没有计划项对应 AC-5', eventId: 'e-rcat-0104' } }] },
      { delay: 1500, event: { type: 'plan_accepted', department: 'engineering', label: '补上计划项后 PLAN r4 被接纳，工程把计划贴上白板' }, patch: [{ path: 'materials', push: { id: 'm-cat-l4', projectId: 'p-report', workItemId: 'w-cat', kind: 'plan', version: 4, title: 'PLAN r4', goal: '修复 D-2，实现 AC-5', text: '1. 输出末尾补换行\n2. 合计之后输出「共 N 个类别」（计入「未分类」）\n3. 运行 report_categorized 与 unit_tests', at: T('15:34'), files: null, verdict: null } }] }
    ]
  });

  // 4. 部门指导：用户向工程下达指导，门缝塞进纸条
  S.push({
    id: 'sc-guidance', name: '部门指导', level: 'now', projectId: 'p-report', workItemId: 'w-cat', view: 'dept', department: 'engineering',
    steps: [
      { delay: 1400, event: { type: 'department_guidance_received', department: 'engineering', label: '门缝塞进纸条，工程信箱灯亮：指导 v3 已接收' }, patch: [{ path: 'runs[id=r-cat].guidance', push: { id: 'g-4', department: 'engineering', version: 3, text: '换行只在 write_report 函数内处理，不要改 format_row。', status: 'received', response: null, at: T('15:30'), contextId: null, eventId: 'e-rcat-0097' } }, { path: 'runs[id=r-cat].messages.engineering', push: { seq: 97, at: T('15:30'), source: 'user', from: 'user', text: '指导 v3：换行只在 write_report 函数内处理，不要改 format_row。', eventId: 'e-rcat-0097' } }] },
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'engineering', label: '正在进行的模型请求照常完成，指导等下一次安全激活' }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-12].status', value: 'succeeded' }] },
      { delay: 1400, event: { type: 'context_assembled', department: 'engineering', label: '工程装配上下文，指导 v3 进入本次模型输入' }, patch: [{ path: 'runs[id=r-cat].guidance[id=g-4].status', value: 'in_input' }, { path: 'runs[id=r-cat].guidance[id=g-4].contextId', value: 'ctx-e4' }, { path: 'runs[id=r-cat].contexts.engineering', push: { id: 'ctx-e4', at: T('15:31'), title: '工程激活 3（指导 v3）', attemptId: null, sources: [{ label: '部门指导', version: 'g-4', included: true }, { label: '当前合同', version: 'PRD r2', included: true }, { label: '质检缺陷', version: 'D-2', included: true }] } }] },
      { delay: 1400, event: { type: 'department_guidance_applied', department: 'engineering', label: '工程拿起纸条阅读，钉在墙上' } },
      { delay: 1200, event: { type: 'model_requested', department: 'engineering', label: '工程开始模型请求' } },
      { delay: 1000, event: { type: 'model_stream_progress', department: 'engineering', label: '气泡中逐字出现：「按指导只修改 write_report…」' } },
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'engineering', label: '模型请求完成' } },
      { delay: 1300, event: { type: 'tool_skipped', department: 'engineering', tool: 'run_command', label: '请求执行未登记的命令 pip install pandas 被拒绝：小人摇头，把纸团扔进废纸篓' }, patch: [{ path: 'runs[id=r-cat].actions', push: { id: 'a-20', department: 'engineering', role: null, tool: 'run_command', summary: '请求执行未登记的命令 pip install pandas', input: '模型提出的工具调用', state: 'done', skipped: true, receipt: { command: 'pip', argv: ['pip', 'install', 'pandas'], exitCode: null, output: '未登记的命令，没有执行', truncated: false, timedOut: false, durationMs: 0, snapshot: null }, before: null, after: null, result: '被拒绝：未登记的命令', at: T('15:32') } }] },
      { delay: 1200, event: { type: 'tool_started', department: 'engineering', tool: 'write_file', label: '工程新建 tests/test_newline.py，在文件上写字' } },
      { delay: 1200, event: { type: 'tool_called', department: 'engineering', tool: 'write_file', label: '写入完成：屏幕显示新增 18 行' }, patch: [{ path: 'runs[id=r-cat].actions', push: { id: 'a-21', department: 'engineering', role: null, tool: 'write_file', summary: '新建 tests/test_newline.py：检查输出末尾换行', input: '质检缺陷 D-2', state: 'done', receipt: null, before: '工作区 5f3a0c', after: '工作区 6c8d12', result: '写入 18 行', at: T('15:33') } }] },
      { delay: 1200, event: { type: 'tool_started', department: 'engineering', tool: 'edit_range', label: '工程在 write_report 函数上写字' } },
      { delay: 1200, event: { type: 'tool_called', department: 'engineering', tool: 'edit_range', label: '按区间编辑完成：只改动 write_report' }, patch: [{ path: 'runs[id=r-cat].actions', push: { id: 'a-19', department: 'engineering', role: null, tool: 'edit_range', summary: '按区间编辑 report.py 第 84–90 行：换行移到 write_report 内', input: '部门指导 g-4', state: 'done', receipt: null, before: 'report.py @ 5f3a0c', after: 'report.py @ 77e2a1', result: '+2 −2 行', at: T('15:33') } }] },
      { delay: 1500, event: { type: 'department_guidance_responded', department: 'engineering', label: '工程在纸条上写回复：已按指导修改，见动作 a-19' }, patch: [{ path: 'runs[id=r-cat].guidance[id=g-4].status', value: 'completed' }, { path: 'runs[id=r-cat].guidance[id=g-4].response', value: '换行已移到 write_report 内，format_row 未改动，见动作 a-19。' }, { path: 'runs[id=r-cat].guidance[id=g-2].status', value: 'explained' }, { path: 'runs[id=r-cat].guidance[id=g-2].response', value: '本轮只改动输出部分，CSV 解析未改动。' }] }
    ]
  });

  // 5. 压缩：第一次压缩未生效，下一步重试成功
  S.push({
    id: 'sc-compaction', name: '压缩', level: 'now', projectId: 'p-report', workItemId: 'w-cat', view: 'dept', department: 'engineering',
    steps: [
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'engineering', label: '工程的模型请求完成，上游回报用量 223 104，超过压缩阈值 222 823' }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-12].status', value: 'succeeded' }, { path: 'runs[id=r-cat].attempts[id=att-rcat-12].usage', value: { input: 219880, output: 3224, cacheRead: 204800, total: 223104, cost: null } }] },
      { delay: 1200, event: { type: 'context_assembled', department: 'engineering', label: '桌上的纸越堆越高，准备整理' } },
      { delay: 1200, event: { type: 'model_requested', department: 'engineering', label: '工程发出摘要请求（不带工具，最低支持档位 low）' }, patch: [{ path: 'runs[id=r-cat].attempts', push: { id: 'att-rcat-c1', logicalCallId: 'call-e3-c2', department: 'engineering', role: null, kind: 'compaction', n: 1, of: 1, status: 'running', startedAt: T('15:30'), durationMs: null, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: null, usage: null, error: null, target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'low', 2, { upstream: 223104, local: 226870 }), semanticUnits: [] } }] },
      { delay: 1400, event: { type: 'model_attempt_failed', department: 'engineering', label: '摘要请求返回空内容，小人趴在桌上' }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-c1].status', value: 'failed' }, { path: 'runs[id=r-cat].attempts[id=att-rcat-c1].error', value: { category: 'empty_output', code: 'summary_empty', http: 200, text: '摘要为空' } }] },
      { delay: 1400, event: { type: 'compaction_failed', department: 'engineering', label: '压缩未生效：纸堆散落，小人重新整理；这一步按未压缩的历史照常发送' } },
      { delay: 1200, event: { type: 'model_requested', department: 'engineering', label: '工程按未压缩的历史发送工作请求' } },
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'engineering', label: '工作请求完成' } },
      { delay: 1200, event: { type: 'tool_started', department: 'engineering', tool: 'search', label: '工程翻文件柜，举放大镜搜索 "write_report"' } },
      { delay: 1000, event: { type: 'tool_called', department: 'engineering', tool: 'search', label: '搜索完成：1 处' } },
      { delay: 1200, event: { type: 'model_requested', department: 'engineering', label: '下一步再次发出摘要请求' }, patch: [{ path: 'runs[id=r-cat].attempts', push: { id: 'att-rcat-c2', logicalCallId: 'call-e3-c3', department: 'engineering', role: null, kind: 'compaction', n: 1, of: 1, status: 'running', startedAt: T('15:32'), durationMs: null, provider: 'opencode-go-responses', requestedModel: 'kimi-k2.6', actualModel: null, usage: null, error: null, target: tgt('opencode-go-responses', 'kimi-k2.6', '项目设置', 'high', 'low', 2, { upstream: 226410, local: 229930 }), semanticUnits: [] } }] },
      { delay: 1000, event: { type: 'model_stream_progress', department: 'engineering', label: '摘要逐段写出：目标、约束与偏好、进展、关键决定、下一步、关键上下文' } },
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'engineering', label: '摘要请求完成' }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-c2].status', value: 'succeeded' }, { path: 'runs[id=r-cat].attempts[id=att-rcat-c2].usage', value: { input: 206300, output: 5870, cacheRead: 0, total: 212170, cost: null } }] },
      { delay: 1500, event: { type: 'compaction_recorded', department: 'engineering', label: '小人把桌上的纸整理进「摘要」档案盒，编号变为 3' }, patch: [{ path: 'runs[id=r-cat].compactions', push: { department: 'engineering', n: 3, at: T('15:33'), coverage: 'seq 10–121', eventId: 'e-rcat-0122' } }] },
      { delay: 1200, event: { type: 'context_assembled', department: 'engineering', label: '下一次请求使用摘要 3 与最近约 20 000 token 的原始记录' }, patch: [{ path: 'runs[id=r-cat].contexts.engineering', push: { id: 'ctx-e5', at: T('15:33'), title: '工程激活 3（压缩后）', attemptId: null, sources: [{ label: '部门历史', version: '摘要 3 + 最近 16 条', included: true }, { label: '当前合同', version: 'PRD r2', included: true }, { label: '质检缺陷', version: 'D-2', included: true }] } }] }
    ]
  });

  // 6. 中断与待核实：服务重启时 unit_tests 没有回执
  S.push({
    id: 'sc-interrupt', name: '中断与待核实', level: 's3', projectId: 'p-cargo', workItemId: 'w-weight', view: 'recovery',
    steps: [
      { delay: 1400, event: { type: 'tool_started', department: 'engineering', tool: 'run_command', label: '工程拉下拉杆，开始执行 unit_tests（15:00:41）' }, patch: [{ path: 'runs[id=r-weight].recovery.state', value: 'running' }, { path: 'runs[id=r-weight].recovery.reason', value: null }, { path: 'runs[id=r-weight].recovery.owner', value: { id: 'exec-7f3a', since: T('14:20') } }] },
      { delay: 1800, event: { type: 'x_run_interrupted', department: 'engineering', label: '服务进程在 15:01 停止：整层变暗，墙上时钟停住，门上挂「中断」牌' }, patch: [{ path: 'runs[id=r-weight].recovery.state', value: 'interrupted' }, { path: 'runs[id=r-weight].recovery.reason', value: '服务进程在 15:01 停止，执行者 exec-7f3a 失去联系' }, { path: 'service.restartedAt', value: T('15:02:10') }] },
      { delay: 1800, event: { type: 'x_action_unknown', department: 'engineering', label: '服务重启后核对：unit_tests 已开始、没有回执，结果未知；房间亮黄灯，终端闪烁' }, patch: [{ path: 'runs[id=r-weight].recovery.state', value: 'pending_verification' }, { path: 'runs[id=r-weight].recovery.reason', value: '服务在 15:01 重启时，工程部门的登记命令 unit_tests 已开始但没有回执，结果未知' }, { path: 'runs[id=r-weight].recovery.owner', value: { id: 'exec-2c91', since: T('15:02:14') } }] },
      { delay: 1600, event: { type: 'tool_called', department: 'engineering', tool: 'run_command', label: '旧执行者 exec-7f3a 送回 unit_tests 输出：作为迟到结果记录，不推进状态' }, patch: [{ path: 'runs[id=r-weight].recovery.lateResults', push: { at: T('15:03:40'), text: '旧执行者 exec-7f3a 送回的 unit_tests 输出（退出 0）。迟到结果只作历史事实，不推进状态。' } }] },
      { delay: 1800, event: { type: 'tool_called', department: 'engineering', tool: 'run_command', label: '核实：在工作区找到 unit_tests 的主机回执，动作改为已完成' }, patch: [{ path: 'runs[id=r-weight].recovery.verifications', push: { at: T('15:04:20'), actionId: 'a-w4', basis: '比对工作区快照 71c0de 与主机回执文件 receipts.jsonl 第 4 行', result: '命令已执行完毕：退出 0，18 条通过；工作区未被改动' } }, { path: 'runs[id=r-weight].actions[id=a-w4].state', value: 'done' }, { path: 'runs[id=r-weight].actions[id=a-w4].receipt', value: { command: 'unit_tests', argv: ['python', '-m', 'pytest', '-q'], exitCode: 0, output: '.................. [100%]\n18 passed in 0.71s', truncated: false, timedOut: false, durationMs: 2140, snapshot: 'ws-71c0de' } }, { path: 'runs[id=r-weight].actions[id=a-w4].after', value: '工作区 71c0de（未改动）' }, { path: 'runs[id=r-weight].actions[id=a-w4].result', value: '退出 0 · 18 条通过（核实后确认）' }, { path: 'runs[id=r-weight].recovery.unfinished', value: [] }, { path: 'runs[id=r-weight].recovery.canResume', value: true }, { path: 'runs[id=r-weight].recovery.resumeBlockedReason', value: null }, { path: 'runs[id=r-weight].recovery.lastConfirmed', value: { seq: 61, text: '工程执行 unit_tests（核实后确认已完成，退出 0）' } }, { path: 'runs[id=r-weight].recovery.nextActions', value: [{ id: 'resume', label: '继续执行' }] }] },
      { delay: 1800, event: { type: 'x_resume_accepted', department: 'engineering', label: '继续执行被接受：小人伸懒腰回到工位，灯亮起，时钟继续走' }, patch: [{ path: 'runs[id=r-weight].recovery.state', value: 'running' }, { path: 'runs[id=r-weight].recovery.reason', value: null }, { path: 'runs[id=r-weight].recovery.canResume', value: false }, { path: 'runs[id=r-weight].recovery.resumeBlockedReason', value: '事项正在运行，已有有效执行者' }, { path: 'runs[id=r-weight].recovery.nextActions', value: [] }, { path: 'service.pendingResumeCount', value: 1 }] },
      { delay: 1200, event: { type: 'department_activated', department: 'engineering', label: '工程从核实后的位置接着工作，已用限额保留' } },
      { delay: 1200, event: { type: 'context_assembled', department: 'engineering', label: '工程装配上下文，包含核实结果' } },
      { delay: 1200, event: { type: 'model_requested', department: 'engineering', label: '工程开始模型请求' } },
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'engineering', label: '模型请求完成，决定提交交付' } },
      { delay: 1200, event: { type: 'proposal_submitted', department: 'engineering', label: '工程把交付说明放进提案托盘' } },
      { delay: 1400, event: { type: 'delivery_accepted', department: 'engineering', label: '交付 r1 封存' }, patch: [{ path: 'materials', push: { id: 'm-weight-d1', projectId: 'p-cargo', workItemId: 'w-weight', kind: 'delivery', version: 1, title: '交付 r1', summary: '超重箱子单独列出', text: '交付 r1：planner.py 第 12–40 行。', at: T('15:08'), files: [{ path: 'planner.py', bytes: 5310 }, { path: 'tests/test_planner.py', bytes: 2940 }], git: { commit: '71c0de4', parent: '5a1c90e', stat: '2 个文件 · +22 −3' }, diff: '@@ -12,3 +12,14 @@ def plan(boxes, max_load):\n+    heavy = [b for b in boxes if b.weight > max_load]', verdict: null } }] },
      { delay: 1600, event: { type: 'transition', department: 'engineering', label: '交付箱从工程搬到质检', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, patch: [{ path: 'runs[id=r-weight].phase', value: 'QUALITY' }, { path: 'runs[id=r-weight].department', value: 'quality' }] }
    ]
  });

  // 7. 模型不可用与继续执行：凭据被上游拒绝，修复后继续
  S.push({
    id: 'sc-unusable', name: '模型不可用与继续执行', level: 's3', projectId: 'p-lab', workItemId: 'w-export', view: 'recovery',
    steps: [
      { delay: 1400, event: { type: 'department_activated', department: 'quality', label: '质检房间亮灯，准备检查交付 r1' }, patch: [{ path: 'runs[id=r-export].recovery.state', value: 'running' }, { path: 'runs[id=r-export].phase', value: 'QUALITY' }, { path: 'runs[id=r-export].department', value: 'quality' }, { path: 'runs[id=r-export].stopReason', value: null }, { path: 'workItems[id=w-export].status', value: 'in_progress' }, { path: 'runs[id=r-export].attempts[id=att-rx-06].status', value: 'preparing' }] },
      { delay: 1200, event: { type: 'context_assembled', department: 'quality', label: '质检取出 PRD r1 与交付 r1' } },
      { delay: 1200, event: { type: 'model_requested', department: 'quality', label: '质检按项目设置向 opencode-go-chat 的 mimo-v2.5 发出请求' }, patch: [{ path: 'runs[id=r-export].attempts[id=att-rx-06].status', value: 'requesting' }] },
      { delay: 1500, event: { type: 'model_attempt_failed', department: 'quality', label: '上游返回 HTTP 401：凭据被上游拒绝，桌上红灯亮' }, patch: [{ path: 'runs[id=r-export].attempts[id=att-rx-06].status', value: 'failed' }] },
      { delay: 1800, event: { type: 'x_waiting_resume', department: 'quality', label: '事项进入待恢复：质检门口挂「待恢复」牌，写明「凭据被上游拒绝：OPENCODE_GO_LAB_KEY」' }, patch: [{ path: 'runs[id=r-export].recovery.state', value: 'waiting_resume' }, { path: 'runs[id=r-export].recovery.canResume', value: false }, { path: 'workItems[id=w-export].status', value: 'stopped' }, { path: 'runs[id=r-export].phase', value: 'FAILED' }, { path: 'runs[id=r-export].department', value: null }, { path: 'runs[id=r-export].stopReason', value: { code: 'provider_error', text: '质检部门模型请求失败：HTTP 401，凭据被上游拒绝' } }] },
      { delay: 1800, go: '#/sys/models', event: { type: 'x_waiting_resume', department: 'quality', label: '用户在模型管理为 OPENCODE_GO_LAB_KEY 保存新的 Key（只在本进程有效）' }, patch: [{ path: 'catalog.credentials[ref=OPENCODE_GO_LAB_KEY].rejected', value: false }, { path: 'catalog.credentials[ref=OPENCODE_GO_LAB_KEY].state', value: 'memory' }, { path: 'catalog.credentials[ref=OPENCODE_GO_LAB_KEY].version', value: 'k2' }, { path: 'catalog.credentials[ref=OPENCODE_GO_LAB_KEY].note', value: '进程内存（临时 Key，优先于 .env）' }] },
      { delay: 1600, event: { type: 'x_waiting_resume', department: 'quality', label: '连接测试通过；服务端重新判断：原因已修复，可以继续执行' }, patch: [{ path: 'catalog.connectionTests.opencode-go-chat', value: { at: T('15:31'), ok: true, text: '连接测试通过 · 388 ms' } }, { path: 'runs[id=r-export].recovery.canResume', value: true }, { path: 'runs[id=r-export].recovery.resumeBlockedReason', value: null }, { path: 'runs[id=r-export].recovery.nextActions', value: [{ id: 'resume', label: '继续执行' }] }] },
      { delay: 1800, go: '#/p/p-lab/w/w-export/recovery', event: { type: 'x_resume_accepted', department: 'quality', label: '继续执行被接受：从这次请求接着进行，已完成的工作与已用限额保留' }, patch: [{ path: 'runs[id=r-export].recovery.state', value: 'running' }, { path: 'runs[id=r-export].recovery.reason', value: null }, { path: 'runs[id=r-export].recovery.unusable', value: null }, { path: 'runs[id=r-export].recovery.owner', value: { id: 'exec-9a41', since: T('15:32') } }, { path: 'runs[id=r-export].recovery.nextActions', value: [] }, { path: 'runs[id=r-export].phase', value: 'QUALITY' }, { path: 'runs[id=r-export].department', value: 'quality' }, { path: 'runs[id=r-export].stopReason', value: null }, { path: 'workItems[id=w-export].status', value: 'in_progress' }, { path: 'runs[id=r-export].effectiveModel.quality.unusable', value: null }, { path: 'service.pendingResumeCount', value: 1 }] },
      { delay: 1200, event: { type: 'department_activated', department: 'quality', label: '质检伸懒腰后回到工位' } },
      { delay: 1200, event: { type: 'model_requested', department: 'quality', label: '质检重新发出这次请求，调用目标使用新的凭据版本 k2' }, patch: [{ path: 'runs[id=r-export].attempts', push: { id: 'att-rx-07', logicalCallId: 'call-x-q1', department: 'quality', role: null, kind: 'work', n: 1, of: 3, status: 'running', startedAt: T('15:32'), durationMs: null, provider: 'opencode-go-chat', requestedModel: 'mimo-v2.5', actualModel: null, usage: null, error: null, target: Object.assign(tgt('opencode-go-chat', 'mimo-v2.5', '项目设置', null, 'medium', 1), { credentialVersion: 'k2' }), semanticUnits: [] } }] },
      { delay: 1200, event: { type: 'model_attempt_finished', department: 'quality', label: '请求完成：气泡变成灯泡' }, patch: [{ path: 'runs[id=r-export].attempts[id=att-rx-07].status', value: 'succeeded' }, { path: 'runs[id=r-export].attempts[id=att-rx-07].actualModel', value: 'mimo-v2.5' }] },
      { delay: 1200, event: { type: 'tool_started', department: 'quality', tool: 'run_command', label: '质检执行登记命令 export_csv' } },
      { delay: 1400, event: { type: 'tool_called', department: 'quality', tool: 'run_command', label: 'export_csv 退出 0，质检检查 CSV 内容' }, patch: [{ path: 'runs[id=r-export].actions', push: { id: 'a-x5', department: 'quality', role: null, tool: 'run_command', summary: '质检执行登记命令 export_csv（质检副本）', input: 'PRD r1 AC-1 至 AC-4', state: 'done', receipt: { command: 'export_csv', argv: ['python', 'lab.py', 'export', '--format', 'csv'], exitCode: 0, output: 'wrote exports/lab-0924.csv (3 rows)', truncated: false, timedOut: false, durationMs: 910, snapshot: 'qa-b73a50' }, before: '质检副本 b73a50', after: '质检副本 b73a50 + exports/lab-0924.csv', result: '退出 0', at: T('15:34') } }] },
      { delay: 1500, event: { type: 'qa_submitted', department: 'quality', label: '质检盖绿色「放行」章', payload: { verdict: 'release' } } },
      { delay: 1600, event: { type: 'transition', department: 'quality', label: '放行单与交付箱送到成果库', payload: { from: 'quality', to: 'adoption', artifact: 'release' } }, patch: [{ path: 'runs[id=r-export].phase', value: 'DONE' }, { path: 'runs[id=r-export].department', value: null }, { path: 'workItems[id=w-export].status', value: 'released_unsettled' }] },
      { delay: 1500, event: { type: 'deliverable_adopted', label: '成果库架子上放上 r1', payload: { version: 'r1' } }, patch: [{ path: 'workItems[id=w-export].status', value: 'adopted' }, { path: 'projects[id=p-lab].adoption', value: { version: 'r1', summary: '实验记录导出为 CSV', adoptedAt: T('15:36'), workItemId: 'w-export' } }, { path: 'projects[id=p-lab].adoptions', push: { version: 'r1', workItemId: 'w-export', at: T('15:36') } }] },
      { delay: 1200, event: { type: 'run_done', label: '事项完成：门上挂「完成」牌' }, patch: [{ path: 'runs[id=r-export].recovery.state', value: 'terminated' }] }
    ]
  });

  // 8. 并行排队：槽位占满时排队，槽位空出后取得
  S.push({
    id: 'sc-queue', name: '并行排队', level: 's3', projectId: 'p-report', workItemId: 'w-empty', view: 'overview',
    steps: [
      { delay: 1400, event: { type: 'x_queued', workItemId: 'w-empty', label: '执行槽位 3/3 已占满：「空输入时给出提示」在大厅排队，手持 1 号牌' }, patch: [{ path: 'runtime.queue.0.since', value: T('15:18') }] },
      { delay: 1500, event: { type: 'x_queued', workItemId: 'w-md', label: '用户新建事项「汇总另存为 Markdown」：排在第 2 位，手持 2 号牌' }, patch: [{ path: 'workItems', push: { id: 'w-md', projectId: 'p-report', title: '汇总另存为 Markdown', colorIndex: 5, status: 'queued', runId: 'r-md', queuePos: 2, heldReason: null } }, { path: 'runs', push: Object.assign(emptyRun('r-md', 'w-md'), { department: null, cycle: 0, startedAt: null, inputs: [{ version: 1, kind: 'user', text: '汇总结果另存一份 Markdown 表格。', at: T('15:30'), progress: 'received', bytes: [0, 45] }] }) }, { path: 'projects[id=p-report].workItemIds', push: 'w-md' }, { path: 'runtime.queue', push: { workItemId: 'w-md', since: T('15:30'), position: 2 } }] },
      { delay: 1500, event: { type: 'x_queue_cancelled', workItemId: 'w-md', label: '用户取消排队中的「汇总另存为 Markdown」：离开队伍，运行中的事项不受影响' }, patch: [{ path: 'workItems[id=w-md].status', value: 'stopped' }, { path: 'workItems[id=w-md].queuePos', value: null }, { path: 'runs[id=r-md].phase', value: 'FAILED' }, { path: 'runs[id=r-md].stopReason', value: { code: 'cancelled', text: '用户取消排队' } }, { path: 'runs[id=r-md].recovery.state', value: 'terminated' }, { path: 'runtime.queue', remove: { key: 'workItemId', value: 'w-md' } }] },
      { delay: 1200, event: { type: 'model_attempt_finished', workItemId: 'w-cat', department: 'engineering', label: '「类别按首次出现顺序输出」工程的模型请求完成' }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-12].status', value: 'succeeded' }] },
      { delay: 1400, event: { type: 'tool_called', workItemId: 'w-cat', department: 'engineering', tool: 'run_command', label: 'report_categorized 退出 0' } },
      { delay: 1400, event: { type: 'delivery_accepted', workItemId: 'w-cat', department: 'engineering', label: '交付 r3 封存' } },
      { delay: 1600, event: { type: 'transition', workItemId: 'w-cat', department: 'engineering', label: '交付箱搬到质检', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, patch: [{ path: 'runs[id=r-cat].phase', value: 'QUALITY' }, { path: 'runs[id=r-cat].department', value: 'quality' }, { path: 'runtime.slots.used.0.department', value: 'quality' }] },
      { delay: 1500, event: { type: 'qa_submitted', workItemId: 'w-cat', department: 'quality', label: '「类别按首次出现顺序输出」质检盖绿色「放行」章', payload: { verdict: 'release' } } },
      { delay: 1600, event: { type: 'deliverable_adopted', workItemId: 'w-cat', label: '「类别按首次出现顺序输出」被采纳为 r3，执行槽位空出一个', payload: { version: 'r3' } }, patch: [{ path: 'workItems[id=w-cat].status', value: 'adopted' }, { path: 'runs[id=r-cat].phase', value: 'DONE' }, { path: 'runs[id=r-cat].department', value: null }, { path: 'projects[id=p-report].adoption', value: { version: 'r3', summary: '类别按首次出现顺序输出', adoptedAt: T('15:34'), workItemId: 'w-cat' } }, { path: 'projects[id=p-report].adoptions', push: { version: 'r3', workItemId: 'w-cat', at: T('15:34') } }, { path: 'runtime.slots.used', remove: { key: 'workItemId', value: 'w-cat' } }] },
      { delay: 1200, event: { type: 'run_done', workItemId: 'w-cat', label: '「类别按首次出现顺序输出」完成' }, patch: [{ path: 'runs[id=r-cat].recovery.state', value: 'terminated' }] },
      { delay: 1800, event: { type: 'x_slot_acquired', workItemId: 'w-empty', label: '「空输入时给出提示」取得执行槽位：离开队伍走向产品房间，槽位灯亮起' }, patch: [{ path: 'workItems[id=w-empty].levels.s3.status', value: 'in_progress' }, { path: 'workItems[id=w-empty].queuePos', value: null }, { path: 'runtime.queue', remove: { key: 'workItemId', value: 'w-empty' } }, { path: 'runtime.slots.used', push: { workItemId: 'w-empty', department: 'product', role: null } }, { path: 'runs[id=r-empty].department', value: 'product' }, { path: 'runs[id=r-empty].cycle', value: 1 }, { path: 'runs[id=r-empty].startedAt', value: T('15:34') }, { path: 'runs[id=r-empty].recovery.reason', value: null }, { path: 'runs[id=r-empty].recovery.nextActions', value: [] }, { path: 'runs[id=r-empty].recovery.owner', value: { id: 'exec-5d20', since: T('15:34') } }] },
      { delay: 1200, event: { type: 'department_activated', workItemId: 'w-empty', department: 'product', label: '产品房间亮灯，小旗换成「空输入时给出提示」的颜色' } },
      { delay: 1200, event: { type: 'context_assembled', workItemId: 'w-empty', department: 'product', label: '产品取出用户输入 v1 与采纳 r3' }, patch: [{ path: 'runs[id=r-empty].inputs.0.progress', value: 'assigned' }] },
      { delay: 1200, event: { type: 'model_requested', workItemId: 'w-empty', department: 'product', label: '产品开始模型请求' } },
      { delay: 1500, event: { type: 'spec_accepted', workItemId: 'w-empty', department: 'product', label: '产品盖「有效」章：PRD r1' }, patch: [{ path: 'runs[id=r-empty].inputs.0.progress', value: 'accepted' }] },
      { delay: 1600, event: { type: 'transition', workItemId: 'w-empty', department: 'product', label: '送件小人把 PRD 卷轴从产品搬到工程', payload: { from: 'product', to: 'engineering', artifact: 'prd' } }, patch: [{ path: 'runs[id=r-empty].phase', value: 'ENGINEERING' }, { path: 'runs[id=r-empty].department', value: 'engineering' }, { path: 'runs[id=r-empty].flow', push: { seq: 9, at: T('15:36'), from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：空输入时给出提示', status: '已接收', eventId: 'e-re-0009' } }] },
      { delay: 1800, event: { type: 'run_failed', projectId: 'p-lab', workItemId: 'w-export', department: 'quality', label: '另一个项目中，用户取消待恢复的「导出 CSV」：门上挂「已取消」牌，小人收拾桌面，槽位空出', payload: { reason: 'cancelled' } }, patch: [{ path: 'workItems[id=w-export].status', value: 'stopped' }, { path: 'runs[id=r-export].stopReason', value: { code: 'cancelled', text: '用户取消事项' } }, { path: 'runs[id=r-export].recovery.state', value: 'terminated' }, { path: 'runs[id=r-export].recovery.canResume', value: false }, { path: 'runs[id=r-export].recovery.resumeBlockedReason', value: '事项已取消' }, { path: 'runs[id=r-export].recovery.nextActions', value: [] }, { path: 'runtime.slots.used', remove: { key: 'workItemId', value: 'w-export' } }, { path: 'service.pendingResumeCount', value: 1 }] }
    ]
  });

  // 9. 采纳竞争：两份成果只接受一个有效采纳，另一份成为未采纳候选
  S.push({
    id: 'sc-adoption', name: '采纳竞争', level: 's3', projectId: 'p-report', workItemId: 'w-head', view: 'overview',
    steps: [
      { delay: 1400, event: { type: 'transition', workItemId: 'w-sum', department: 'engineering', label: '回放 9 月 23 日：「按类别汇总」的交付箱搬到质检；「表头改为中文」同时在工程进行', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, patch: [{ path: 'workItems[id=w-sum].status', value: 'in_progress' }, { path: 'runs[id=r-sum].phase', value: 'QUALITY' }, { path: 'runs[id=r-sum].department', value: 'quality' }, { path: 'workItems[id=w-head].status', value: 'in_progress' }, { path: 'workItems[id=w-head].heldReason', value: null }, { path: 'runs[id=r-head].phase', value: 'ENGINEERING' }, { path: 'runs[id=r-head].department', value: 'engineering' }, { path: 'projects[id=p-report].adoption', value: { version: 'r1', summary: '逐行输出与合计金额', adoptedAt: T('11:02', '22'), workItemId: 'w-base' } }] },
      { delay: 1500, event: { type: 'qa_submitted', workItemId: 'w-sum', department: 'quality', label: '「按类别汇总」质检放行', payload: { verdict: 'release' } } },
      { delay: 1600, event: { type: 'deliverable_adopted', workItemId: 'w-sum', label: '「按类别汇总」先被采纳：成果库架子上的版本号变为 r2', payload: { version: 'r2' } }, patch: [{ path: 'workItems[id=w-sum].status', value: 'adopted' }, { path: 'runs[id=r-sum].phase', value: 'DONE' }, { path: 'runs[id=r-sum].department', value: null }, { path: 'projects[id=p-report].adoption', value: { version: 'r2', summary: '按类别汇总金额与笔数，输出纯文本表格', adoptedAt: T('17:40', '23'), workItemId: 'w-sum' } }] },
      { delay: 1200, event: { type: 'run_done', workItemId: 'w-sum', label: '「按类别汇总」完成' } },
      { delay: 1400, event: { type: 'delivery_accepted', workItemId: 'w-head', department: 'engineering', label: '「表头改为中文」交付 r1 封存（基于 r1）' } },
      { delay: 1600, event: { type: 'transition', workItemId: 'w-head', department: 'engineering', label: '「表头改为中文」的交付箱搬到质检', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, patch: [{ path: 'runs[id=r-head].phase', value: 'QUALITY' }, { path: 'runs[id=r-head].department', value: 'quality' }] },
      { delay: 1500, event: { type: 'qa_submitted', workItemId: 'w-head', department: 'quality', label: '「表头改为中文」质检放行', payload: { verdict: 'release' } }, patch: [{ path: 'workItems[id=w-head].status', value: 'released_unsettled' }, { path: 'runs[id=r-head].phase', value: 'DONE' }, { path: 'runs[id=r-head].department', value: null }] },
      { delay: 1800, event: { type: 'adoption_held', workItemId: 'w-head', label: '基线已变：箱子放上「未采纳候选」架，贴「基线已变」标签' }, patch: [{ path: 'workItems[id=w-head].status', value: 'held' }, { path: 'workItems[id=w-head].heldReason', value: '基线已变：开始时的基线为 r1，r2（按类别汇总）已在 17:40 被采纳；本成果没有包含 r2 的改动' }] },
      { delay: 1200, event: { type: 'run_done', workItemId: 'w-head', label: '「表头改为中文」完成，成果保留为未采纳候选，可以取回' } },
      { delay: 1800, event: { type: 'work_item_created', workItemId: 'w-merge', label: '用户以候选开始集成事项：「集成表头改为中文到 r2」有自己的合同与质检，不自动合并冲突' }, patch: [{ path: 'workItems', push: { id: 'w-merge', projectId: 'p-report', title: '集成「表头改为中文」到 r2', colorIndex: 5, status: 'in_progress', runId: 'r-merge', queuePos: null, heldReason: null, fromCandidate: 'w-head' } }, { path: 'runs', push: emptyRun('r-merge', 'w-merge') }, { path: 'projects[id=p-report].workItemIds', push: 'w-merge' }] },
      { delay: 1200, event: { type: 'user_input_received', workItemId: 'w-merge', department: 'product', label: '集成事项的输入：以未采纳候选「表头改为中文」为材料' }, patch: [{ path: 'runs[id=r-merge].inputs', push: { version: 1, kind: 'user', text: '把未采纳候选「表头改为中文」的改动集成到当前采纳 r2 上。', at: T('15:30'), progress: 'received', bytes: [0, 84] } }] },
      { delay: 1200, event: { type: 'department_activated', workItemId: 'w-merge', department: 'product', label: '产品房间亮灯，小旗换成集成事项的颜色' } },
      { delay: 1200, event: { type: 'context_assembled', workItemId: 'w-merge', department: 'product', label: '产品取出候选的交付 r1 与当前采纳 r2' }, patch: [{ path: 'runs[id=r-merge].contexts.product', push: { id: 'ctx-m-p1', at: T('15:30'), title: '产品激活 1', attemptId: null, sources: [{ label: '用户原文', version: 'v1', included: true }, { label: '未采纳候选', version: '表头改为中文 · 交付 r1', included: true }, { label: '项目上下文', version: '采纳 r2', included: true }] } }] }
    ]
  });

  // 10. 部门内多角色：工程经理分派任务，角色交回结果
  S.push({
    id: 'sc-roles', name: '部门内多角色', level: 's4', projectId: 'p-report', workItemId: 'w-cat', view: 'dept', department: 'engineering',
    steps: [
      { delay: 1400, event: { type: 'department_activated', department: 'engineering', role: 'eng-manager', label: '工程经理拿着记录板走到白板前' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-manager].status', value: 'working' }, { path: 'runs[id=r-cat].roles.engineering[id=eng-dev].status', value: 'idle' }, { path: 'runs[id=r-cat].roles.engineering[id=eng-explorer].status', value: 'idle' }, { path: 'runs[id=r-cat].roles.engineering[id=eng-architect].status', value: 'idle' }] },
      { delay: 1500, event: { type: 'x_role_task_assigned', department: 'engineering', role: 'eng-architect', label: '工程经理把任务卡递给工程架构师：起草 PLAN r4（D-2 与 AC-5）' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-architect].status', value: 'assigned' }, { path: 'runs[id=r-cat].roles.engineering[id=eng-architect].task', value: '起草 PLAN r4：修复 D-2，实现 AC-5' }, { path: 'runs[id=r-cat].ledger.engineering.items', push: { id: 'P-6', text: '起草 PLAN r4', assignee: 'eng-architect', status: 'assigned', result: null } }] },
      { delay: 1200, event: { type: 'model_requested', department: 'engineering', role: 'eng-architect', label: '工程架构师戴上眼镜，展开图纸卷' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-architect].status', value: 'working' }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-6].status', value: 'working' }] },
      { delay: 1500, event: { type: 'x_role_result_returned', department: 'engineering', role: 'eng-architect', label: '工程架构师把结果卡交回经理：PLAN r4 草案' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-architect].status', value: 'returned' }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-6].status', value: 'returned' }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-6].result', value: 'PLAN r4 草案：2 个计划项' }] },
      { delay: 1500, event: { type: 'plan_accepted', department: 'engineering', role: 'eng-manager', label: '工程经理提交计划，主机接纳 PLAN r4，贴上白板' } },
      { delay: 1400, event: { type: 'x_role_task_assigned', department: 'engineering', role: 'eng-dev', label: '工程经理把任务卡递给开发者：修正末尾换行' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-dev].status', value: 'assigned' }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-4].status', value: 'assigned' }] },
      { delay: 1400, event: { type: 'x_role_task_assigned', department: 'engineering', role: 'eng-explorer', label: '工程经理把任务卡递给工程探索者：查阅 csv 模块的换行处理' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-explorer].status', value: 'assigned' }] },
      { delay: 1600, event: { type: 'x_explorer_fetch', department: 'engineering', role: 'eng-explorer', label: '工程探索者背上背包走出门去查资料（网络取回 docs.python.org）' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-explorer].status', value: 'away' }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-5].status', value: 'working' }] },
      { delay: 1200, event: { type: 'tool_started', department: 'engineering', role: 'eng-dev', tool: 'edit_range', label: '开发者戴着耳机，在 report.py 上写字' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-dev].status', value: 'working' }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-4].status', value: 'working' }] },
      { delay: 1200, event: { type: 'tool_called', department: 'engineering', role: 'eng-dev', tool: 'edit_range', label: '按区间编辑完成' } },
      { delay: 1600, event: { type: 'x_role_result_returned', department: 'engineering', role: 'eng-explorer', label: '工程探索者抱着资料回来，把发现交回经理' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-explorer].status', value: 'returned' }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-5].status', value: 'returned' }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-5].result', value: '发现：csv.writer 默认使用 \\r\\n，需要 lineterminator="\\n"（来源 docs.python.org）' }] },
      { delay: 1400, event: { type: 'x_semantic_recorded', department: 'engineering', label: '语义整理：墙边的语义记录柜里增加一张卡片（发现 U-19）' }, patch: [{ path: 'semantic.p-report.units', push: { id: 'U-19', type: '发现', scope: '工程私有', text: 'csv.writer 默认使用 \\r\\n，需要 lineterminator="\\n"', status: 'valid', source: 'e-rcat-0110', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('15:33') } }, { path: 'runs[id=r-cat].ledger.engineering.facts', push: 'csv.writer 默认使用 \\r\\n（工程探索者的发现 U-19）' }] },
      { delay: 1200, event: { type: 'tool_started', department: 'engineering', role: 'eng-dev', tool: 'run_command', label: '开发者走到终端拉下拉杆：report_categorized' } },
      { delay: 1400, event: { type: 'tool_called', department: 'engineering', role: 'eng-dev', tool: 'run_command', label: 'report_categorized 退出 1：仍有 \\r，终端亮红灯', payload: { exitCode: 1 } } },
      { delay: 1600, event: { type: 'x_replanned', department: 'engineering', role: 'eng-manager', label: '进展判断：连续 3 轮没有新进展，工程经理在白板上擦掉计划重写' }, patch: [{ path: 'runs[id=r-cat].ledger.engineering.progress', push: { cycle: 3, judgment: '停滞', text: '连续 3 轮输出比较失败，按发现 U-19 更新计划' } }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-4].text', value: '输出末尾补换行，并设置 lineterminator="\\n"（D-2、U-19）' }] },
      { delay: 1200, event: { type: 'tool_called', department: 'engineering', role: 'eng-dev', tool: 'run_command', label: '开发者按新计划修改后，report_categorized 退出 0', payload: { exitCode: 0 } } },
      { delay: 1500, event: { type: 'x_role_result_returned', department: 'engineering', role: 'eng-dev', label: '开发者把结果卡交回经理：D-2 已修复' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-dev].status', value: 'returned' }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-4].status', value: 'returned' }, { path: 'runs[id=r-cat].ledger.engineering.items[id=P-4].result', value: 'report_categorized 退出 0' }] },
      { delay: 1400, event: { type: 'proposal_submitted', department: 'engineering', role: 'eng-manager', label: '工程经理代表部门提交交付说明' }, patch: [{ path: 'runs[id=r-cat].roles.engineering[id=eng-manager].task', value: '交付 r3 已提交' }] }
    ]
  });

  // 11. 运维故障：告警、授权缓解、修复进入事项
  S.push({
    id: 'sc-ops', name: '运维故障', level: 's5', projectId: 'p-shift', workItemId: 'w-timeout', view: 'dept', department: 'operations',
    steps: [
      { delay: 1600, event: { type: 'x_ops_alarm', department: 'operations', label: '探针入口失败 23/410：告警灯旋转，运维跑向机柜' }, patch: [{ path: 'ops.p-shift.incidents.0.steps', value: [{ label: '症状已报告', state: 'done', at: T('09:12') }, { label: '影响已确认', state: 'current', at: null }, { label: '缓解已执行', state: 'todo', at: null }, { label: '修复进入事项', state: 'todo', at: null }, { label: '确认恢复', state: 'todo', at: null }, { label: '复盘', state: 'todo', at: null }] }, { path: 'ops.p-shift.pendingActions', value: [] }] },
      { delay: 1500, event: { type: 'x_ops_alarm', department: 'operations', label: '影响已确认：9:00–9:30 两个区域，已知 23 次入口失败 / 分母 410' }, patch: [{ path: 'ops.p-shift.incidents.0.steps.1', value: { label: '影响已确认', state: 'done', at: T('09:26'), note: '已知 23 次入口失败 / 分母 410' } }, { path: 'ops.p-shift.incidents.0.steps.2.state', value: 'current' }] },
      { delay: 1600, event: { type: 'x_ops_action_requested', department: 'operations', label: '运维举着申请单等待：重启排班页面服务（登记过的缓解动作）' }, patch: [{ path: 'ops.p-shift.pendingActions', push: { id: 'OA-2', kind: '重启', target: '排班页面服务', reason: '缓解 INC-7：内存持续上涨', requestedAt: T('09:30'), state: 'pending' } }] },
      { delay: 1600, event: { type: 'tool_called', department: 'operations', tool: 'restart_service', label: '用户授权后，运维执行登记过的重启动作；入口失败降到 1.2%' }, patch: [{ path: 'ops.p-shift.pendingActions', remove: { key: 'id', value: 'OA-2' } }, { path: 'ops.p-shift.incidents.0.steps.2', value: { label: '缓解已执行', state: 'done', at: T('09:41'), note: '重启排班页面服务（用户逐项授权）' } }, { path: 'ops.p-shift.incidents.0.steps.3.state', value: 'current' }, { path: 'ops.p-shift.indicators.0.value', value: '98.8%' }] },
      { delay: 1800, event: { type: 'work_item_created', department: 'operations', label: '运维把修复写成信件送回大厅：新事项「排班页面加载超时」' }, patch: [{ path: 'ops.p-shift.incidents.0.steps.3', value: { label: '修复进入事项', state: 'done', at: T('15:14'), note: '事项「排班页面加载超时」' } }, { path: 'ops.p-shift.incidents.0.steps.4.state', value: 'current' }] },
      { delay: 1600, event: { type: 'transition', department: 'operations', label: '运维的故障记录送到产品', payload: { from: 'operations', to: 'product', artifact: 'defect' } } },
      { delay: 1200, event: { type: 'department_activated', department: 'product', label: '产品房间亮灯' } },
      { delay: 1500, event: { type: 'collaboration_requested', department: 'product', label: '产品的纸飞机飞向运维：超时集中在哪个时段？', payload: { from: 'product', to: 'operations' } } },
      { delay: 1500, event: { type: 'collaboration_responded', department: 'operations', label: '运维接住纸飞机写回答：9:00–9:30，华东与华南', payload: { from: 'operations', to: 'product' } } },
      { delay: 1500, event: { type: 'spec_accepted', department: 'product', label: '产品盖「有效」章：PRD r1 写入运行目标（峰值 3 秒内打开，成功率 ≥ 99.5%）' }, patch: [{ path: 'runs[id=r-timeout].inputs.0.progress', value: 'accepted' }] },
      { delay: 1600, event: { type: 'transition', department: 'product', label: 'PRD 卷轴从产品搬到工程', payload: { from: 'product', to: 'engineering', artifact: 'prd' } }, patch: [{ path: 'runs[id=r-timeout].phase', value: 'ENGINEERING' }, { path: 'runs[id=r-timeout].department', value: 'engineering' }, { path: 'runs[id=r-timeout].flow', push: { seq: 16, at: T('15:34'), from: 'product', to: 'engineering', kind: 'handoff', content: 'PRD r1：峰值时段 3 秒内打开', status: '已接收', eventId: 'e-rt-0016' } }] },
      { delay: 1500, event: { type: 'x_ops_released', department: 'operations', label: '发布记录：r3 仍在运行，发布 digest 与采纳 digest 一致' } }
    ]
  });

  // 12. 元观察判定：观察员在交接经过的走廊上方举牌
  S.push({
    id: 'sc-judgment', name: '元观察判定', level: 's5', projectId: 'p-report', workItemId: 'w-cat', view: 'overview',
    steps: [
      { delay: 1400, event: { type: 'delivery_accepted', department: 'engineering', label: '工程封存交付 r3' }, patch: [{ path: 'runs[id=r-cat].attempts[id=att-rcat-12].status', value: 'succeeded' }] },
      { delay: 1600, event: { type: 'transition', department: 'engineering', label: '交付箱经过走廊搬到质检', payload: { from: 'engineering', to: 'quality', artifact: 'box' } }, patch: [{ path: 'runs[id=r-cat].phase', value: 'QUALITY' }, { path: 'runs[id=r-cat].department', value: 'quality' }] },
      { delay: 1800, event: { type: 'x_judgment_recorded', department: null, label: '观察员举牌：交付覆盖全部计划项——通过，置信度 0.91', payload: { judgmentPointId: 'JP-5', result: 'pass', confidence: 0.91 } }, patch: [{ path: 'meta.judgments', push: { id: 'J-31', judgmentPointId: 'JP-5', projectId: 'p-report', workItemId: 'w-cat', handoff: '工程 → 质检', at: T('15:31'), result: 'pass', probability: 0.94, confidence: 0.91, route: '推进（控制层自动推进）' } }, { path: 'meta.judgmentPoints[id=JP-5].lastResult', value: 'pass' }, { path: 'meta.judgmentPoints[id=JP-5].probability', value: 0.94 }, { path: 'meta.judgmentPoints[id=JP-5].confidence', value: 0.91 }] },
      { delay: 1200, event: { type: 'department_activated', department: 'quality', label: '质检房间亮灯' } },
      { delay: 1500, event: { type: 'qa_submitted', department: 'quality', label: '质检盖绿色「放行」章', payload: { verdict: 'release' } } },
      { delay: 1800, event: { type: 'x_judgment_recorded', department: null, label: '观察员举牌：每条有效验收条件都有通过的检查结果——通过，置信度 0.93；控制层自动推进', payload: { judgmentPointId: 'JP-1', result: 'pass', confidence: 0.93 } }, patch: [{ path: 'meta.judgments', push: { id: 'J-32', judgmentPointId: 'JP-1', projectId: 'p-report', workItemId: 'w-cat', handoff: '质检 → 成果库', at: T('15:33'), result: 'pass', probability: 0.97, confidence: 0.93, route: '推进（控制层自动推进）' } }, { path: 'meta.judgmentPoints[id=JP-1].lastResult', value: 'pass' }] },
      { delay: 1600, event: { type: 'transition', department: 'quality', label: '放行单与交付箱送到成果库', payload: { from: 'quality', to: 'adoption', artifact: 'release' } }, patch: [{ path: 'runs[id=r-cat].phase', value: 'DONE' }, { path: 'runs[id=r-cat].department', value: null }, { path: 'workItems[id=w-cat].status', value: 'released_unsettled' }] },
      { delay: 1600, event: { type: 'deliverable_adopted', label: '成果库版本号变为 r3', payload: { version: 'r3' } }, patch: [{ path: 'workItems[id=w-cat].status', value: 'adopted' }, { path: 'projects[id=p-report].adoption', value: { version: 'r3', summary: '类别按首次出现顺序输出', adoptedAt: T('15:34'), workItemId: 'w-cat' } }, { path: 'projects[id=p-report].adoptions', push: { version: 'r3', workItemId: 'w-cat', at: T('15:34') } }] },
      { delay: 1800, event: { type: 'x_judgment_recorded', department: null, label: '观察员举牌：本轮工程是否在重复上一轮的修改——不确定，置信度 0.42；判定点未通过校准，只记录', payload: { judgmentPointId: 'JP-3', result: 'uncertain', confidence: 0.42 } }, patch: [{ path: 'meta.judgments', push: { id: 'J-33', judgmentPointId: 'JP-3', projectId: 'p-report', workItemId: 'w-cat', handoff: '质检 → 工程（第 2 次返工）', at: T('15:34'), result: 'uncertain', probability: 0.51, confidence: 0.42, route: '只记录（未通过校准）' } }, { path: 'meta.findings', push: { id: 'F-4', projectId: 'p-report', workItemId: 'w-cat', rule: '同一缺陷不应连续返工两次以上', text: 'D-2 相关的输出比较连续失败 2 次，建议复查计划', at: T('15:34') } }] },
      { delay: 1800, event: { type: 'x_judgment_recorded', department: null, projectId: 'p-shift', workItemId: 'w-timeout', label: '观察员举牌：INC-7 是否由 r3 发布引起——不确定，置信度 0.39，交给用户决定', payload: { judgmentPointId: 'JP-4', result: 'uncertain', confidence: 0.39 } }, patch: [{ path: 'meta.judgments', push: { id: 'J-34', judgmentPointId: 'JP-4', projectId: 'p-shift', workItemId: 'w-timeout', handoff: '运维 → 产品', at: T('15:35'), result: 'uncertain', probability: 0.58, confidence: 0.39, route: '交给用户决定' } }, { path: 'meta.pendingDecisions', push: { id: 'PD-2', judgmentPointId: 'JP-4', question: '「排班页面加载超时」是否需要先回滚到 r2？判定置信度 0.39，低于 0.70', options: ['先回滚到 r2', '不回滚，按修复事项继续', '暂不决定，继续观察 30 分钟'] } }] }
    ]
  });

  // ---------------------------------------------------------------------------

  Y7.data = {
    now: T('15:30'),
    service: { level: 's3', restartedAt: T('15:02:10'), pendingResumeCount: 2 },

    projects: [
      { id: 'p-report', name: '文本报表工具', goal: '把门店的 CSV 销售记录整理成按类别汇总的文本报表，命令行运行，输出稳定、可以逐字节核对。', pinned: true, archived: false, adoption: { version: 'r2', summary: '按类别汇总金额与笔数，输出纯文本表格', adoptedAt: T('17:40', '23'), workItemId: 'w-sum' }, adoptions: [{ version: 'r1', workItemId: 'w-base', at: T('11:02', '22') }, { version: 'r2', workItemId: 'w-sum', at: T('17:40', '23') }], workItemIds: ['w-base', 'w-sum', 'w-cat', 'w-empty', 'w-head'], kind: 'code' },
      { id: 'p-cargo', name: '货物装载规划', goal: '根据箱子的重量与尺寸给出装车顺序，超出单车载重时单独提示。', pinned: false, archived: false, adoption: null, adoptions: [], workItemIds: ['w-weight'], kind: 'code' },
      { id: 'p-lab', name: '实验记录助手', goal: '记录实验步骤与观测值，按实验导出表格，供组会使用。', pinned: false, archived: false, adoption: null, adoptions: [], workItemIds: ['w-export'], kind: 'code' },
      { level: 's5', id: 'p-shift', name: '门店排班', goal: '为门店生成每周排班并在线查看；排班页面在营业高峰也能稳定打开。', pinned: false, archived: false, adoption: { version: 'r3', summary: '排班页面支持按区域筛选', adoptedAt: T('19:55', '23'), workItemId: null }, adoptions: [{ version: 'r1', workItemId: null, at: T('10:20', '20') }, { version: 'r2', workItemId: null, at: T('16:05', '21') }, { version: 'r3', workItemId: null, at: T('19:55', '23') }], workItemIds: ['w-timeout'], kind: 'service' }
    ],

    workItems: [
      { id: 'w-base', projectId: 'p-report', title: '建立基线', colorIndex: 0, status: 'adopted', runId: 'r-base', queuePos: null, heldReason: null },
      { id: 'w-sum', projectId: 'p-report', title: '按类别汇总', colorIndex: 1, status: 'adopted', runId: 'r-sum', queuePos: null, heldReason: null },
      { id: 'w-cat', projectId: 'p-report', title: '类别按首次出现顺序输出', colorIndex: 2, status: 'in_progress', runId: 'r-cat', queuePos: null, heldReason: null },
      { id: 'w-empty', projectId: 'p-report', title: '空输入时给出提示', colorIndex: 3, status: 'not_started', runId: 'r-empty', queuePos: 1, heldReason: null, levels: { s3: { status: 'queued' } } },
      { id: 'w-head', projectId: 'p-report', title: '表头改为中文', colorIndex: 4, status: 'held', runId: 'r-head', queuePos: null, heldReason: '基线已变：开始时的基线为 r1，r2（按类别汇总）已在 9 月 23 日 17:40 被采纳；本成果没有包含 r2 的改动' },
      { id: 'w-weight', projectId: 'p-cargo', title: '超重箱子单独列出', colorIndex: 0, status: 'in_progress', runId: 'r-weight', queuePos: null, heldReason: null },
      { id: 'w-export', projectId: 'p-lab', title: '导出 CSV', colorIndex: 0, status: 'stopped', runId: 'r-export', queuePos: null, heldReason: null },
      { level: 's5', id: 'w-timeout', projectId: 'p-shift', title: '排班页面加载超时', colorIndex: 0, status: 'in_progress', runId: 'r-timeout', queuePos: null, heldReason: null, origin: 'operations', incidentId: 'INC-7' }
    ],

    runs: [rBase, rSum, rCat, rEmpty, rHead, rWeight, rExport, rTimeout],

    materials,

    semantic: {
      level: 's4',
      'p-report': {
        units: [
          { id: 'U-1', type: '用户输入', scope: '项目共享', text: '用户输入 v1：类别按首次出现顺序输出', status: 'valid', source: 'e-rcat-0003', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('14:10') },
          { id: 'U-2', type: '要求', scope: '项目共享', text: 'R-3 汇总表中的类别按在输入中首次出现的顺序排列', status: 'valid', source: 'e-rcat-0008', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('14:17') },
          { id: 'U-3', type: '验收条件', scope: '项目共享', text: 'AC-1 sales.csv 的汇总第一行为「食品」', status: 'valid', source: 'e-rcat-0008', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('14:17') },
          { id: 'U-4', type: '验收条件', scope: '项目共享', text: 'AC-2 同一类别多次出现时笔数累计', status: 'valid', source: 'e-rcat-0008', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('14:17') },
          { id: 'U-5', type: '验收条件', scope: '项目共享', text: 'AC-3 输出与 expected/categorized.txt 逐字节一致（含末尾换行）', status: 'valid', source: 'e-rcat-0008', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('14:17') },
          { id: 'U-6', type: '决定', scope: '项目共享', text: '空类别名显示为「未分类」（回答工程咨询 q-1）', status: 'valid', source: 'e-rcat-0065', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('15:08') },
          { id: 'U-7', type: '验收条件', scope: '项目共享', text: 'AC-4 空类别名的记录归入「未分类」', status: 'valid', source: 'e-rcat-0065', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('15:08') },
          { id: 'U-8', type: '约束', scope: '项目共享', text: 'C-1 不改动 CSV 解析部分（部门指导 g-2）', status: 'valid', source: 'e-rcat-0091', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('15:26') },
          { id: 'U-9', type: '计划项', scope: '项目共享', text: 'P-4 输出末尾补换行（处理 D-2）', status: 'valid', source: 'e-rcat-0092', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('15:26') },
          { id: 'U-10', type: '缺陷', scope: '项目共享', text: 'D-2 输出末尾缺少换行（违反 AC-3）', status: 'valid', source: 'e-rcat-0087', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('15:24') },
          { id: 'U-11', type: '缺陷', scope: '项目共享', text: 'D-1 多次出现的类别只计入第一次的笔数（违反 AC-2）', status: 'invalid', source: 'e-rcat-0051', workItemId: 'w-cat', supersededBy: null, reason: '交付 r2 已处理，质检检查通过', at: T('15:24') },
          { id: 'U-12', type: '要求', scope: '项目共享', text: 'R-2 类别按字母顺序排列（事项「按类别汇总」）', status: 'superseded', source: 'e-rsum-0007', workItemId: 'w-sum', supersededBy: 'U-2', reason: '用户输入 v1 改为按首次出现顺序', at: T('14:17') },
          { id: 'U-13', type: '要求', scope: '项目共享', text: 'R-4 汇总表最后一行为合计金额（事项「按类别汇总」）', status: 'conflict', source: 'e-rsum-0007', workItemId: 'w-sum', supersededBy: null, reason: null, at: T('17:27', '23') },
          { id: 'U-14', type: '用户输入', scope: '项目共享', text: '用户输入 v2：汇总表最后加一行「共 N 个类别」', status: 'conflict', source: 'e-rcat-0070', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('15:12') },
          { id: 'U-15', type: '事实', scope: '工程私有', text: 'report_categorized 按字节比较输出，末尾换行会影响结果', status: 'valid', source: 'e-rcat-0087', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('15:25') },
          { id: 'U-16', type: '工作做法', scope: '工程私有', text: 'unit_tests 需要在项目根目录运行，参数为 -q', status: 'valid', source: 'e-rcat-0020', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('14:25') },
          { id: 'U-17', type: '要求', scope: '项目共享', text: 'R-5 表头改为中文（来自未采纳事项「表头改为中文」）', status: 'valid', source: 'e-rhead-0005', workItemId: 'w-head', fromHeld: true, supersededBy: null, reason: null, at: T('16:11', '23') },
          { id: 'U-18', type: '检查结果', scope: '项目共享', text: 'K-7 AC-2 检查通过（质检回执 a-13 所在的检查）', status: 'valid', source: 'e-rcat-0087', workItemId: 'w-cat', supersededBy: null, reason: null, at: T('15:24') }
        ],
        conflicts: [
          { a: 'U-13', b: 'U-14', text: '最后一行的内容：R-4 要求最后一行为合计金额，用户输入 v2 要求最后加一行「共 N 个类别」，两者都要求占用最后一行' }
        ],
        dataflow: [
          { id: 'DF-1', label: '每个已接收的用户输入版本都已被 ProductSpec 处理', ok: false, missing: ['用户输入 v2'] },
          { id: 'DF-2', label: '每条有效决定在新版本 ProductSpec 中已保留、整合或废止', ok: true, missing: [] },
          { id: 'DF-3', label: '每条有效要求至少有一条验收条件', ok: true, missing: [] },
          { id: 'DF-4', label: '每条有效要求至少有一个计划项', ok: true, missing: [] },
          { id: 'DF-5', label: '每个计划项在交付中已完成，或写明未完成的原因', ok: false, missing: ['P-4'] },
          { id: 'DF-6', label: '每个未关闭的缺陷在下一次交付中有处理', ok: false, missing: ['D-2'] },
          { id: 'DF-7', label: '每条有效验收条件都有检查结果与证据', ok: false, missing: ['AC-3', 'AC-4'] },
          { id: 'DF-8', label: '有冲突的单元数量', ok: false, missing: ['U-13 ↔ U-14'], count: 1 }
        ]
      }
    },

    projectSettings: {
      'p-report': {
        departments: {
          product: { model: null, level: null, promptVersion: 0, promptText: null, version: 3 },
          engineering: { model: 'opencode-go-responses/kimi-k2.6', level: 'high', promptVersion: 2, promptText: PROMPTS.engineering, version: 5 },
          quality: { model: null, level: null, promptVersion: 1, promptText: PROMPTS.quality, version: 2 }
        },
        roles: {
          level: 's4',
          engineering: [
            { roleId: 'eng-explorer', model: 'opencode-go-responses/glm-5', level: 'low', promptText: null },
            { roleId: 'eng-dev', model: null, level: 'medium', promptText: '每次只改动一个计划项涉及的区间。' }
          ],
          quality: [{ roleId: 'qa-explorer', model: 'opencode-go-responses/glm-5', level: 'low', promptText: null }]
        },
        commands: [
          { name: 'unit_tests', argv: ['python', '-m', 'pytest', 'tests', '-q'], args: ['-k', '--maxfail'], timeoutSec: 120, outputLimit: 65536, version: 3 },
          { name: 'report_categorized', argv: ['python', 'report.py', 'samples/sales.csv', '--by-category'], args: ['--limit'], timeoutSec: 30, outputLimit: 16384, version: 2 }
        ],
        tools: [
          { id: 'network', label: '网络取回', scope: '只读取回：docs.python.org、pypi.org', approval: '超出范围时逐次批准' },
          { id: 'mcp-github.search_code', label: 'MCP · GitHub search_code', scope: '本项目仓库，只读', approval: '已授权' },
          { id: 'mcp-github.create_issue', label: 'MCP · GitHub create_issue', scope: '未授权', approval: '每次使用逐次批准' }
        ]
      },
      'p-cargo': {
        departments: {
          product: { model: null, level: null, promptVersion: 0, promptText: null, version: 1 },
          engineering: { model: null, level: null, promptVersion: 0, promptText: null, version: 1 },
          quality: { model: 'local-custom/qwen3-coder-30b', level: null, promptVersion: 0, promptText: null, version: 2 }
        },
        roles: { level: 's4' },
        commands: [
          { name: 'unit_tests', argv: ['python', '-m', 'pytest', '-q'], args: ['-k'], timeoutSec: 120, outputLimit: 65536, version: 1 }
        ],
        tools: [{ id: 'network', label: '网络取回', scope: '未授权', approval: '每次使用逐次批准' }]
      },
      'p-lab': {
        departments: {
          product: { model: null, level: null, promptVersion: 0, promptText: null, version: 1 },
          engineering: { model: null, level: null, promptVersion: 0, promptText: null, version: 1 },
          quality: { model: 'opencode-go-chat/mimo-v2.5', level: null, promptVersion: 1, promptText: PROMPTS.quality, version: 3 }
        },
        roles: { level: 's4' },
        commands: [
          { name: 'unit_tests', argv: ['python', '-m', 'pytest', '-q'], args: ['-k'], timeoutSec: 120, outputLimit: 65536, version: 1 },
          { name: 'export_csv', argv: ['python', 'lab.py', 'export', '--format', 'csv'], args: ['--since'], timeoutSec: 60, outputLimit: 16384, version: 1 }
        ],
        tools: []
      },
      'p-shift': {
        departments: {
          product: { model: null, level: null, promptVersion: 0, promptText: null, version: 1 },
          engineering: { model: null, level: null, promptVersion: 0, promptText: null, version: 1 },
          quality: { model: null, level: null, promptVersion: 0, promptText: null, version: 1 },
          operations: { model: null, level: 'low', promptVersion: 1, promptText: '缓解动作只在登记过的清单内执行；外部动作逐项申请授权。', version: 2 }
        },
        roles: { level: 's4' },
        commands: [
          { name: 'unit_tests', argv: ['npm', 'test'], args: [], timeoutSec: 180, outputLimit: 65536, version: 2 },
          { name: 'probe_schedule_page', argv: ['node', 'probe.js', '--page', 'schedule'], args: ['--region'], timeoutSec: 60, outputLimit: 16384, version: 1 }
        ],
        tools: [{ id: 'deploy', label: '发布与重启（运维）', scope: '门店生产环境', approval: '每次逐项授权' }]
      }
    },

    catalog: {
      file: { path: '.yudao/catalog.json', revision: 18, reloadedAt: T('11:18'), reloadError: null },
      presets: {
        revision: '2026-09-24.1',
        source: 'https://opencode.ai/docs/go/（2026-09-24 采集）',
        schemes: [
          {
            id: 'opencode-go', name: 'OpenCode Go',
            protocols: [
              { protocol: 'responses', baseUrl: 'https://opencode.ai/zen/go/v1' },
              { protocol: 'chat', baseUrl: 'https://opencode.ai/zen/go/v1' },
              { protocol: 'messages', baseUrl: 'https://opencode.ai/zen/go/v1' }
            ],
            auth: 'API Key', headers: ['真实客户端 User-Agent', 'x-opencode-session'],
            modelsUrl: 'https://opencode.ai/zen/go/v1/models', docsUrl: 'https://opencode.ai/docs/go/'
          },
          { id: 'custom', name: '自定义', protocols: [], auth: '由用户填写', headers: [], modelsUrl: null, docsUrl: null }
        ]
      },
      connections: [
        { id: 'opencode-go-responses', name: 'OpenCode Go · Responses', scheme: 'opencode-go', protocol: 'responses', baseUrl: 'https://opencode.ai/zen/go/v1', credentialRef: 'OPENCODE_GO_KEY', timeoutSec: 120, modelsUrl: '' },
        { id: 'opencode-go-chat', name: 'OpenCode Go · Chat', scheme: 'opencode-go', protocol: 'chat', baseUrl: 'https://opencode.ai/zen/go/v1', credentialRef: 'OPENCODE_GO_LAB_KEY', timeoutSec: 120, modelsUrl: '' },
        { id: 'local-custom', name: '本机兼容服务', scheme: 'custom', protocol: 'chat', baseUrl: 'http://127.0.0.1:8080/v1', credentialRef: null, timeoutSec: 300, modelsUrl: 'http://127.0.0.1:8080/v1/models' },
        { level: 's5', id: 'jev-decision', name: '决策模型 · JEV', scheme: 'custom', protocol: 'decision', baseUrl: 'http://127.0.0.1:9100/v1', credentialRef: null, timeoutSec: 30, modelsUrl: '' }
      ],
      definitions: [
        { id: 'opencode-go-responses/kimi-k2.6', connectionId: 'opencode-go-responses', upstreamModel: 'kimi-k2.6', window: 262144, maxOutput: 32768, reasoning: { levels: ['low', 'medium', 'high'], defaultLevel: 'medium', method: 'effort' }, capacityAccepted: true, admission: { testedAt: T('09:12'), actualModel: 'kimi-k2.6', protocol: 'Responses' }, admissionRevoked: null },
        { id: 'opencode-go-responses/glm-5', connectionId: 'opencode-go-responses', upstreamModel: 'glm-5', window: 204800, maxOutput: 32768, reasoning: { levels: ['low', 'medium', 'high'], defaultLevel: 'medium', method: 'effort' }, capacityAccepted: true, admission: { testedAt: T('09:14'), actualModel: 'glm-5', protocol: 'Responses' }, admissionRevoked: null },
        { id: 'opencode-go-responses/mimo-v2.5', connectionId: 'opencode-go-responses', upstreamModel: 'mimo-v2.5', window: 1048576, maxOutput: 65536, reasoning: { levels: ['minimal', 'low', 'medium', 'high'], defaultLevel: 'medium', method: 'effort' }, capacityAccepted: true, admission: { testedAt: T('09:16'), actualModel: 'mimo-v2.5', protocol: 'Responses' }, admissionRevoked: null },
        { id: 'opencode-go-chat/mimo-v2.5', connectionId: 'opencode-go-chat', upstreamModel: 'mimo-v2.5', window: 1048576, maxOutput: 65536, reasoning: { levels: ['minimal', 'low', 'medium', 'high'], defaultLevel: 'medium', method: 'effort' }, capacityAccepted: true, admission: { testedAt: T('16:40', '23'), actualModel: 'mimo-v2.5', protocol: 'Chat Completions' }, admissionRevoked: null },
        { id: 'opencode-go-chat/glm-5', connectionId: 'opencode-go-chat', upstreamModel: 'glm-5', window: 204800, maxOutput: 32768, reasoning: null, capacityAccepted: false, admission: null, admissionRevoked: null, prefill: '预填自 OpenCode Go · Responses 的同名定义，尚未接受' },
        { id: 'local-custom/qwen3-coder-30b', connectionId: 'local-custom', upstreamModel: 'qwen3-coder-30b', window: 131072, maxOutput: 16384, reasoning: null, capacityAccepted: true, admission: null, admissionRevoked: { at: T('11:18'), reason: '连接地址由 http://127.0.0.1:8000/v1 改为 http://127.0.0.1:8080/v1', previous: { testedAt: T('10:02', '23'), actualModel: 'qwen3-coder-30b', protocol: 'Chat Completions' } } },
        { level: 's5', id: 'jev-decision/jev-judge-2', connectionId: 'jev-decision', upstreamModel: 'jev-judge-2', window: 32768, maxOutput: 1024, reasoning: null, capacityAccepted: true, admission: null, admissionRevoked: null, admissionByPoint: [{ judgmentPointId: 'JP-1', calibrated: true, samples: 120, agreement: 0.96 }, { judgmentPointId: 'JP-2', calibrated: true, samples: 84, agreement: 0.92 }, { judgmentPointId: 'JP-5', calibrated: true, samples: 66, agreement: 0.9 }, { judgmentPointId: 'JP-3', calibrated: false, samples: 18, agreement: 0.61 }, { judgmentPointId: 'JP-4', calibrated: false, samples: 9, agreement: 0.55 }] }
      ],
      candidates: {
        'opencode-go-responses': { source: 'https://opencode.ai/zen/go/v1/models', collectedAt: T('09:05'), ids: ['kimi-k2.6', 'glm-5', 'mimo-v2.5', 'qwen3.6-plus', 'minimax-m2.7', 'deepseek-v4-flash'], unknownReason: null },
        'opencode-go-chat': { source: 'https://opencode.ai/zen/go/v1/models', collectedAt: T('16:31', '23'), ids: ['kimi-k2.6', 'glm-5', 'mimo-v2.5', 'qwen3.6-plus', 'minimax-m2.7', 'deepseek-v4-flash'], unknownReason: null },
        'local-custom': { source: 'http://127.0.0.1:8080/v1/models', collectedAt: T('11:20'), ids: [], unknownReason: '请求失败：连接被拒绝（ECONNREFUSED）' }
      },
      credentials: [
        { ref: 'OPENCODE_GO_KEY', state: 'env', sources: { memory: false, env: true, dotenv: false }, version: 'k3', rejected: false, rejectedSource: null, note: '宿主进程环境' },
        { ref: 'OPENCODE_GO_LAB_KEY', state: 'dotenv', sources: { memory: false, env: false, dotenv: true }, version: 'k1', rejected: true, rejectedSource: 'dotenv', rejectedAt: T('15:10'), note: '.yudao/.env · 上游在 15:10 拒绝（HTTP 401）' }
      ],
      connectionTests: {
        'opencode-go-responses': { at: T('09:10'), ok: true, text: '连接测试通过 · 412 ms' },
        'opencode-go-chat': { at: T('15:12'), ok: false, text: '连接测试失败：HTTP 401，凭据被上游拒绝' },
        'local-custom': null
      },
      modelTests: {},
      departmentDefaults: {
        product: { definition: 'opencode-go-responses/glm-5', level: null },
        engineering: { definition: 'opencode-go-responses/kimi-k2.6', level: 'high' },
        quality: { definition: 'opencode-go-responses/mimo-v2.5', level: null },
        levels: { s5: { operations: { definition: 'opencode-go-responses/glm-5', level: 'low' } } }
      },
      roleDefaults: {
        level: 's4',
        'prod-manager': { definition: 'opencode-go-responses/glm-5', level: 'medium' },
        'prod-architect': { definition: null, level: null },
        'prod-explorer': { definition: 'opencode-go-responses/glm-5', level: 'low' },
        'eng-manager': { definition: 'opencode-go-responses/kimi-k2.6', level: 'high' },
        'eng-architect': { definition: 'opencode-go-responses/kimi-k2.6', level: 'high' },
        'eng-dev': { definition: 'opencode-go-responses/kimi-k2.6', level: 'medium' },
        'eng-explorer': { definition: 'opencode-go-responses/glm-5', level: 'low' },
        'qa-manager': { definition: null, level: null },
        'qa-tester': { definition: 'opencode-go-responses/mimo-v2.5', level: null },
        'qa-explorer': { definition: 'opencode-go-responses/glm-5', level: 'low' }
      },
      roleCatalog: {
        level: 's4',
        product: [
          { id: 'prod-manager', name: '产品部门经理', kind: 'manager', duty: '接收产品部门的工作，代表部门对外，提交产品成果' },
          { id: 'prod-architect', name: '产品架构师', kind: 'architect', duty: '挖掘需求，起草 ProductSpec，回答需求咨询' },
          { id: 'prod-explorer', name: '产品探索者', kind: 'explorer', duty: '查资料，交回带来源的发现（一次性）' }
        ],
        engineering: [
          { id: 'eng-manager', name: '工程经理', kind: 'manager', duty: '接收工程部门的工作，代表部门对外，提交工程成果' },
          { id: 'eng-architect', name: '工程架构师', kind: 'architect', duty: '架构与技术设计，起草工程计划' },
          { id: 'eng-dev', name: '开发者', kind: 'developer', duty: '按计划实现代码并自测，工作区唯一的写入者' },
          { id: 'eng-explorer', name: '工程探索者', kind: 'explorer', duty: '阅读代码、查阅文档、复现问题（一次性）' }
        ],
        quality: [
          { id: 'qa-manager', name: '质检经理', kind: 'manager', duty: '接收质检部门的工作，代表部门对外' },
          { id: 'qa-tester', name: '测试工程师', kind: 'tester', duty: '依据 PRD 设计并运行检查，记录缺陷' },
          { id: 'qa-explorer', name: '质检探索者', kind: 'explorer', duty: '探索性地操作交付物，交回观察（一次性）' }
        ]
      },
      // 现有实现的模型页（「当前」档显示）
      current: {
        title: '模型与 Provider',
        subtitle: '保存后只影响新事项，在途事项沿用创建时快照。页面 Key 默认只进内存，勾选才落盘。',
        revision: 14,
        presetVersion: '2026-09-19.1',
        presets: [{ id: 'opencode-go', name: 'OpenCode Go', endpoints: [['Responses', 'https://opencode.ai/zen/go/v1/responses'], ['Chat Completions', 'https://opencode.ai/zen/go/v1/chat/completions'], ['Messages', 'https://opencode.ai/zen/go/v1/messages']], modelsUrl: 'https://opencode.ai/zen/go/v1/models', docsUrl: 'https://opencode.ai/docs/go/' }],
        providers: [
          { name: 'OpenCode Go', models: 3, baseUrl: 'https://opencode.ai/zen/go/v1', credentialRef: 'OPENCODE_GO_KEY', status: '就绪 · 3/3 模型已准入' },
          { name: '本机兼容服务', models: 1, baseUrl: 'http://127.0.0.1:8080/v1', credentialRef: '无需凭据', status: '就绪但未测试' }
        ],
        models: [
          { provider: 'OpenCode Go', model: 'kimi-k2.6', protocol: 'Responses', window: 262144, maxOutput: 32768, admission: '已准入' },
          { provider: 'OpenCode Go', model: 'glm-5', protocol: 'Chat Completions', window: 204800, maxOutput: 32768, admission: '已准入' },
          { provider: 'OpenCode Go', model: 'mimo-v2.5', protocol: 'Responses', window: 1048576, maxOutput: 65536, admission: '已准入' },
          { provider: '本机兼容服务', model: 'qwen3-coder-30b', protocol: 'Chat Completions', window: 131072, maxOutput: 16384, admission: '测试结果不对应当前修订' }
        ],
        departments: [
          { department: 'product', value: 'OpenCode Go / glm-5 · 204800 · 32768' },
          { department: 'engineering', value: 'OpenCode Go / kimi-k2.6 · 262144 · 32768' },
          { department: 'quality', value: 'OpenCode Go / mimo-v2.5 · 1048576 · 65536' }
        ],
        credentials: [{ ref: 'OPENCODE_GO_KEY', status: '已配置 · 宿主进程环境' }],
        readiness: [
          ['配置', '就绪 · 3/4 模型已准入'],
          ['凭据', '已配置 · 宿主进程环境'],
          ['准入', '3/4 已准入 · 1 测试结果不对应当前修订'],
          ['额度', '未知（不显示零，也不以此判断可用性）']
        ]
      }
    },

    runtime: {
      level: 's3',
      slots: {
        total: 3,
        used: [
          { workItemId: 'w-cat', department: 'engineering', role: null, levels: { s4: { role: 'eng-dev' } } },
          { workItemId: 'w-weight', department: 'engineering', role: null, levels: { s4: { role: 'eng-dev' } } },
          { workItemId: 'w-export', department: 'quality', role: null, levels: { s4: { role: 'qa-tester' } } },
          { level: 's5', workItemId: 'w-timeout', department: 'product', role: 'prod-architect' }
        ],
        levels: { s5: { total: 4 } }
      },
      queue: [{ workItemId: 'w-empty', since: T('15:18'), position: 1 }],
      restartNote: '服务在 15:02 重启。重启前排队的事项按原顺序保留；重启前占用槽位的事项中，「超重箱子单独列出」待核实、「导出 CSV」待恢复，确认或取消之前不释放槽位。'
    },

    tools: {
      level: 's3',
      network: {
        scope: '只读取回。各项目在设置中授权域名；超出授权时逐次批准，批准一次不作为永久授权。',
        recent: [
          { at: T('15:27'), url: 'https://docs.python.org/3/library/csv.html', workItemId: 'w-cat', projectId: 'p-report', result: '已取回 · 48 KB' },
          { at: T('15:02'), url: 'https://pypi.org/project/pandas/', workItemId: 'w-cat', projectId: 'p-report', result: '已取回 · 12 KB' },
          { at: T('14:41'), url: 'https://stackoverflow.com/questions/3191528', workItemId: 'w-cat', projectId: 'p-report', result: '超出授权：等待逐次批准' },
          { at: T('14:38'), url: 'https://developer.mozilla.org/zh-CN/docs/Web/HTTP', workItemId: 'w-weight', projectId: 'p-cargo', result: '未授权：没有取回' }
        ]
      },
      mcp: [
        { id: 'mcp-github', name: 'GitHub（官方 MCP 服务）', tools: [
          { name: 'search_code', recovery: '只读；结果未知时重新查询', retry: '可以重复' },
          { name: 'get_file_contents', recovery: '只读；结果未知时重新读取', retry: '可以重复' },
          { name: 'create_issue', recovery: null, retry: '不自动重试' }
        ] },
        { id: 'mcp-docs', name: '文档检索服务', tools: [
          { name: 'lookup', recovery: '只读；按请求编号查询结果', retry: '可以重复' },
          { name: 'annotate', recovery: null, retry: '不自动重试' }
        ] }
      ],
      hooks: [
        { id: 'H-1', name: '禁止访问 materials/ 目录', effect: '收紧：工具参数中出现 materials/ 时拒绝' },
        { id: 'H-2', name: '登记命令时限不超过 300 秒', effect: '收紧：超出时拒绝登记' },
        { id: 'H-3', name: '网络取回只允许 HTTPS', effect: '收紧：拒绝 http:// 地址' }
      ],
      observers: [
        { id: 'O-1', name: '元观察与规则检查部门', scope: '全部项目的交接、询问与回答、缺陷、放行与返工事件（Stage 5 使用）' },
        { id: 'O-2', name: 'CI 导出', scope: '文本报表工具的 run 终态事件' }
      ]
    },

    ops: {
      level: 's5',
      'p-shift': {
        responsibility: { version: 'r3', env: '门店生产环境', acceptedAt: T('20:10', '23'), owner: '运维部门', platform: '平台运行责任在 Yudao 服务；交付物运行责任在运维部门' },
        releases: [
          { version: 'r3', adoptionDigest: 'sha256:9c1e4b…', releaseDigest: 'sha256:9c1e4b…', at: T('20:05', '23'), state: '已发布 · 运维已接收' },
          { version: 'r2', adoptionDigest: 'sha256:47d0a2…', releaseDigest: 'sha256:47d0a2…', at: T('16:40', '21'), state: '已被 r3 取代' },
          { version: 'r1', adoptionDigest: 'sha256:0b93fe…', releaseDigest: 'sha256:0b93fe…', at: T('10:55', '20'), state: '已被 r2 取代' }
        ],
        incidents: [
          { id: 'INC-7', title: '排班页面加载超时', workItemId: 'w-timeout', steps: [
            { label: '症状已报告', state: 'done', at: T('09:12'), note: '探针入口失败' },
            { label: '影响已确认', state: 'done', at: T('09:26'), note: '已知 23 次入口失败 / 分母 410' },
            { label: '缓解已执行', state: 'done', at: T('09:41'), note: '重启排班页面服务（用户逐项授权）' },
            { label: '修复进入事项', state: 'current', at: T('15:14'), note: '事项「排班页面加载超时」' },
            { label: '确认恢复', state: 'todo', at: null, note: null },
            { label: '复盘', state: 'todo', at: null, note: null }
          ] }
        ],
        indicators: [
          { label: '排班页面打开成功率', value: '94.4%', numerator: 387, denominator: 410, window: '今天 9:00–9:30' },
          { label: '缓解后打开成功率', value: '98.8%', numerator: 1284, denominator: 1300, window: '9:41 之后' },
          { label: '成功时延 p95', value: '2.8 秒', numerator: null, denominator: 387, window: '今天 9:00–9:30' },
          { label: '失败时延 p95', value: '30 秒（超时）', numerator: null, denominator: 23, window: '今天 9:00–9:30' }
        ],
        pendingActions: [
          { id: 'OA-3', kind: '重启', target: '排班页面服务', reason: '缓解期间内存再次上涨到 85%', requestedAt: T('15:22'), state: 'pending' },
          { id: 'OA-4', kind: '回滚', target: 'r3 → r2', reason: '若 16:00 前修复事项没有进入工程', requestedAt: T('15:25'), state: 'pending' }
        ]
      }
    },

    meta: {
      level: 's5',
      flowStats: [
        { label: '交接', count: 16, avgIntervalSec: 1260 },
        { label: '询问与回答', count: 4, avgIntervalSec: 190 },
        { label: '缺陷', count: 4, avgIntervalSec: 1380 },
        { label: '放行', count: 4, avgIntervalSec: 2410 },
        { label: '返工', count: 3, avgIntervalSec: 1790 }
      ],
      findings: [
        { id: 'F-1', projectId: 'p-report', workItemId: 'w-cat', rule: '交付前运行登记命令 unit_tests', text: '交付 r1 前只运行了 report_categorized，没有运行 unit_tests', at: T('14:41') },
        { id: 'F-2', projectId: 'p-report', workItemId: 'w-cat', rule: '返工单引用验收条件编号', text: '返工 D-2 的说明中没有写明违反的验收条件，由质检在 15:25 补充', at: T('15:24') },
        { id: 'F-3', projectId: 'p-shift', workItemId: 'w-timeout', rule: '运维提出的事项写明故障编号与分母', text: '已写明 INC-7 与 23/410，符合', at: T('15:14'), ok: true }
      ],
      judgmentPoints: [
        { id: 'JP-1', question: '质检放行前，每条有效验收条件都有通过的检查结果吗？', calibrated: true, lastResult: 'pass', probability: 0.97, confidence: 0.93, route: '推进（控制层自动推进）' },
        { id: 'JP-2', question: '返工单描述的缺陷能否复现？', calibrated: true, lastResult: 'fail', probability: 0.22, confidence: 0.88, route: '退回质检补充复现步骤' },
        { id: 'JP-3', question: '本轮工程是否在重复上一轮的修改？', calibrated: false, lastResult: 'uncertain', probability: 0.51, confidence: 0.42, route: '只记录（未通过校准）' },
        { id: 'JP-4', question: '运维报告的故障是否由最近一次发布引起？', calibrated: false, lastResult: 'uncertain', probability: 0.58, confidence: 0.39, route: '交给用户决定' },
        { id: 'JP-5', question: '交付覆盖了工程计划的全部计划项吗？', calibrated: true, lastResult: 'pass', probability: 0.92, confidence: 0.9, route: '推进（控制层自动推进）' }
      ],
      judgments: [
        { id: 'J-29', judgmentPointId: 'JP-2', projectId: 'p-report', workItemId: 'w-cat', handoff: '质检 → 工程', at: T('15:24'), result: 'pass', probability: 0.9, confidence: 0.88, route: '推进（控制层自动推进）' },
        { id: 'J-30', judgmentPointId: 'JP-4', projectId: 'p-shift', workItemId: 'w-timeout', handoff: '运维 → 产品', at: T('15:14'), result: 'uncertain', probability: 0.58, confidence: 0.39, route: '交给用户决定' }
      ],
      pendingDecisions: [
        { id: 'PD-1', judgmentPointId: 'JP-4', question: 'INC-7 是否由 r3 发布引起？判定置信度 0.39，低于 0.70', options: ['是，由 r3 引起', '否，与发布无关', '暂不决定，继续观察'] }
      ],
      decisions: []
    },

    scenarios: S
  };
})();
