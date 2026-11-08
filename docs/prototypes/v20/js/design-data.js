// 设计预览的组织与示例：仅供静态原型，独立于发布带的目录。
(function () {
  'use strict';
  const Y = window.Y20, O = Y.org;
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const publishedForm = O.form, publishedName = O.formName;
  const ops = {
    id: 'operations', name: '运维', goal: '照看已部署的软件，记录故障并部署已放行的交付',
    judge: '运行环境的健康记录、故障记录与当前交付的核验结论',
    how: '读取运行状态，提出修复事项，在常设授权范围内操作运行环境',
    watches: ['delivery'], produces: ['deployment', 'fault'], verifies: null, completes: false,
    tools: ['读文件', '运行命令'], write: 'none', roles: ['运维工程师'], visible: ['交付', '运行状态'], who: { type: 'own' }
  };
  const forms = {};
  forms.pool_preview = Object.assign(publishedForm('three'), {
    id: 'pool_preview', name: '产品 · 工程 · 质检', rotation: 'pool', unit: '一项可独立核验的改动',
    note: '工作单元由角色认领，逐项核验后再核验整份交付', tip: '设计预览，未连接真实任务池'
  });
  forms.ops_preview = Object.assign(publishedForm('three'), {
    id: 'ops_preview', name: '产品 · 工程 · 质检 · 运维', note: '发布带还没有；多一个运维职能，事项多一种来源「运维发现的故障」', tip: '设计预览，未操作真实运行环境'
  });
  forms.ops_preview.depts.push(clone(ops));
  forms.ops_preview.sources.push({ id: 'fault', name: '运维发现的故障', to: 'product' });
  const opsOutcomes = [
    { id: 'deployment', name: '部署记录', desc: '记录部署版本与运行环境', basedOn: 'delivery', receipt: false, snapshot: false },
    { id: 'fault', name: '故障记录', desc: '运行软件的问题与证据', basedOn: 'delivery', receipt: false, snapshot: false }
  ];
  forms.ops_preview.outcomes.push(...clone(opsOutcomes));
  O.form = (id) => forms[id] ? clone(forms[id]) : publishedForm(id);
  O.formName = (id) => forms[id] ? forms[id].name : publishedName(id);
  Y.designPreview = { forms: Object.keys(forms), operations: ops, opsOutcomes, init(p) {
    p.designPreview = Object.keys(forms).includes(p.org.form) || p.org.changes.rotation === 'pool' || Boolean(p.org.changes.depts && p.org.changes.depts.operations);
    if (p.org.form === 'ops_preview' && !p.settings.dept.operations) p.settings.dept.operations = { model: Y.EXTRA.wiring.engineering.model };
  } };
  const refresh = O.refresh;
  O.refresh = (p) => { Y.designPreview.init(p); refresh(p); };

  const build = Y.buildWorld;
  Y.buildWorld = (scenario) => {
    const w = build(scenario), base = w.projects.find((p) => p.id === 'orders');
    if (!base) return w;
    for (const [id, name, form] of [['pool-demo', '任务池 · 设计预览', 'pool_preview'], ['ops-demo', '线上服务与运维 · 设计预览', 'ops_preview']]) {
      const p = clone(base);
      Object.assign(p, { id, name, goal: '', items: [], outcomes: [], candidates: [], asks: [], interruptions: [], provider_wait: [], deptState: {}, designPreview: true,
        org: { form, changes: {}, keys: {}, history: [] }, settings: { dept: {}, roles: {}, nodes: {} }, elapsed: { used: 0, limit: 7200 }, slots: { used: 0, limit: 3, waiting: 0 } });
      if (form === 'ops_preview') p.settings.dept.operations = { model: Y.EXTRA.wiring.engineering.model };
      O.refresh(p);
      p.org.history.push({ at: w.now, by: '原型', fromVersion: '', toVersion: p.version, form, changes: {}, reason: '设计预览的示例组织', diff: ['采用「' + p.composed.formName + '」'] });
      const pool = form === 'pool_preview', itemId = pool ? 'wpool1' : 'wops1';
      p.items = [{ id: itemId, door: pool ? 'P-1' : 'O-1', title: pool ? '把订单导出成 CSV' : '提供订单服务', text: pool ? '把订单导出成 CSV' : '提供订单服务', color: 1, dept: pool ? 'engineering' : 'quality', status: pool ? 'working' : 'adopted', round: 1, round_limit: 8, used: 0, limit: 7200, reason: pool ? '工作单元等待认领' : '交付已核验', created: w.now, org: O.freeze(p.composed) }];
      p.demoThread = { vers: pool ? [] : [{ n: 1, item: itemId, at: w.now, text: '订单服务基础交付', concl: '放行', files: ['service/orders.ts'], diff: ['+ 订单服务基础实现'] }], phase: null, cur: pool ? itemId : null, stage: null, queue: [], to: null, manual: false, only: false, openV: {}, arrows: pool ? [{ item: itemId, from: 'src', to: 'product', name: '原文', v: 1, round: 1, text: '把订单导出成 CSV' }] : [{ item: itemId, from: 'src', to: 'product', name: '原文', v: 1, round: 1, text: '提供订单服务' }, { item: itemId, from: 'product', to: 'engineering', name: 'PRD', v: 1, round: 1, text: '订单服务：下单、查询、取消' }, { item: itemId, from: 'engineering', to: 'quality', name: '交付', v: 1, round: 1, verdict: { t: 'release', by: '质检' }, text: '订单服务基础交付', files: ['service/orders.ts'], diff: ['+ 订单服务基础实现'] }, { item: itemId, from: 'quality', to: 'operations', name: '交付', v: 1, round: 1, text: '放行的交付 v1 交给运维部署' }, { item: itemId, from: 'operations', to: 'end', name: '部署记录', v: 1, round: 1, text: '第 1 版部署到演示运行环境' }], msgs: [{ t: 'sep', item: itemId }, { t: 'you', item: itemId, text: p.items[0].text, tag: '开始一个新事项', at: w.now }].concat(pool ? [{ t: 'notice', text: '格式定义单元已通过，其余工作等待认领。', at: w.now }] : [{ t: 'rel', who: 'quality', text: '放行：质检核验交付 v1 通过', item: itemId, ai: 2, at: w.now }]) };
      if (pool) { p.slots.used = 1; p.items[0].ran = true; Y.EXTRA.slotHolders[id] = [itemId]; }
      if (pool) p.workUnits = [
        { id: 'u1', title: '定义导出文件格式', status: 'done', owner: 'product', depends: [], review: '单元核验通过' },
        { id: 'u2', title: '实现 CSV 导出', status: 'ready', owner: '', depends: ['u1'], review: '' },
        { id: 'u3', title: '补充导出边界检查', status: 'ready', owner: '', depends: ['u2'], review: '' }
      ];
      if (!pool) p.operations = { version: '第 1 版', health: '运行正常', environment: '演示运行环境', permission: '读取日志、重启服务、部署已放行的交付', faults: [], deployed: 1 };
      w.projects.push(p); w.doorNext[id] = 1; Y.EXTRA.ensure(p);
    }
    return w;
  };
})();
